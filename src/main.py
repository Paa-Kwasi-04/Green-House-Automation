"""Main entry point for greenhouse control system."""

import time
import os
import logging
import shutil
from datetime import datetime
from urllib.parse import quote, urlparse
from communication.serial_comm import SerialComm
from communication.http_server import (
	HTTPServer,
	post_image,
	post_json,
	detect_lan_ip,
	resolve_public_base_url,
	host_is_local_or_private,
	latest_served_image_url,
)
from control.fuzzy_controller import FuzzyController
from actuators import ActuatorDriver
from sensor.camera import Camera
from storage.logger import setup_logging
from storage.data_storage import DataLogger, ControlOutputLogger

logger = logging.getLogger(__name__)


def _default_runtime_dir() -> str:
	"""Return default runtime output directory.

	Returns
	-------
	str
		Absolute path to the parent of the repository root where runtime
		artifacts (logs, images, CSVs) are stored by default.
	"""
	return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_env_int(name: str, default: int) -> int:
	"""Read integer environment variable with fallback behavior.

	Parameters
	----------
	name : str
		Environment variable name.
	default : int
		Fallback value when variable is missing or invalid.

	Returns
	-------
	int
		Parsed integer value or fallback.
	"""
	try:
		return int(os.getenv(name, str(default)))
	except ValueError:
		logger.warning("Invalid integer for %s. Using default: %s", name, default)
		return default


def _get_env_float(name: str, default: float) -> float:
	"""Read float environment variable with fallback behavior.

	Parameters
	----------
	name : str
		Environment variable name.
	default : float
		Fallback value when variable is missing or invalid.

	Returns
	-------
	float
		Parsed float value or fallback.
	"""
	try:
		return float(os.getenv(name, str(default)))
	except ValueError:
		logger.warning("Invalid float for %s. Using default: %s", name, default)
		return default


def main():
	"""Run greenhouse runtime loop.

	The loop coordinates serial ingestion, fuzzy control outputs, actuator
	updates, daily image capture/upload, HTTP server hosting, CSV logging,
	and periodic HTTP telemetry publishing.
	"""
	runtime_dir = os.getenv("GREENHOUSE_RUNTIME_DIR", _default_runtime_dir())
	log_dir = os.getenv("GREENHOUSE_LOG_DIR", os.path.join(runtime_dir, "logs"))
	live_data_dir = os.getenv("GREENHOUSE_LIVE_DIR", os.path.join(runtime_dir, "live"))
	weekly_data_dir = os.getenv("GREENHOUSE_WEEKLY_DIR", os.path.join(runtime_dir, "weekly"))
	image_dir = os.getenv("GREENHOUSE_IMAGE_DIR", os.path.join(runtime_dir, "image"))
	http_upload_dir = os.getenv("GREENHOUSE_HTTP_UPLOAD_DIR", os.path.join(image_dir, "posted"))
	file_log_level_name = os.getenv("GREENHOUSE_FILE_LOG_LEVEL", "INFO").upper()
	file_log_level = getattr(logging, file_log_level_name, logging.INFO)
	invalid_file_log_level = not isinstance(file_log_level, int)
	if invalid_file_log_level:
		file_log_level = logging.INFO

	# Setup centralized logging with file rotation and date grouping
	setup_logging(log_dir=log_dir, log_level=logging.INFO, file_log_level=file_log_level)
	if invalid_file_log_level:
		logger.warning("Invalid GREENHOUSE_FILE_LOG_LEVEL=%s; using INFO", file_log_level_name)
	
	# Configuration
	serial_port = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyUSB0")
	baudrate = _get_env_int("GREENHOUSE_SERIAL_BAUDRATE", 115200)
	telemetry_publish_interval = _get_env_float("GREENHOUSE_TELEMETRY_PUBLISH_INTERVAL", 1.0)
	telemetry_post_timeout = _get_env_float("GREENHOUSE_TELEMETRY_POST_TIMEOUT", 5.0)
	loop_delay = _get_env_float("GREENHOUSE_LOOP_DELAY", 0.1)
	pump_check_interval = _get_env_float("GREENHOUSE_PUMP_CHECK_INTERVAL", 6 * 60 * 60)
	pump_pulse_seconds = _get_env_float("GREENHOUSE_PUMP_PULSE_SECONDS", 5.0)
	http_enabled = os.getenv("GREENHOUSE_HTTP_ENABLED", "1").lower() not in {"0", "false", "no"}
	http_host = os.getenv("GREENHOUSE_HTTP_HOST", "0.0.0.0")
	http_port = _get_env_int("GREENHOUSE_HTTP_PORT", 8000)
	http_stream_fps = _get_env_float("GREENHOUSE_HTTP_STREAM_FPS", 6.0)
	http_stream_width = _get_env_int("GREENHOUSE_HTTP_STREAM_WIDTH", 640)
	http_stream_height = _get_env_int("GREENHOUSE_HTTP_STREAM_HEIGHT", 480)
	raw_capture_hour = _get_env_int("GREENHOUSE_CAPTURE_HOUR", 21)
	raw_capture_minute = _get_env_int("GREENHOUSE_CAPTURE_MINUTE", 0)
	post_timeout = _get_env_float("GREENHOUSE_POST_TIMEOUT", 5.0)
	http_public_host = os.getenv("GREENHOUSE_HTTP_PUBLIC_HOST", detect_lan_ip())
	public_base_url = resolve_public_base_url(http_public_host=http_public_host, http_port=http_port)
	default_post_url = f"http://127.0.0.1:{http_port}/upload"
	public_telemetry_url = f"{public_base_url}/telemetry"
	default_telemetry_view_url = f"{public_base_url}/telemetry/view"
	image_post_url = os.getenv("GREENHOUSE_POST_IMAGE_URL", default_post_url)
	telemetry_post_url = os.getenv("GREENHOUSE_TELEMETRY_URL", public_telemetry_url)
	telemetry_view_url = os.getenv("GREENHOUSE_TELEMETRY_VIEW_URL", default_telemetry_view_url)
	image_base_url = os.getenv("GREENHOUSE_IMAGE_BASE_URL", f"{public_base_url}/images")
	latest_image_url = os.getenv("GREENHOUSE_LATEST_IMAGE_URL", f"{public_base_url}/latest")
	default_stream_url = f"{public_base_url}/stream"
	stream_url = os.getenv("GREENHOUSE_STREAM_URL", default_stream_url)
	public_url_host = (urlparse(public_base_url).hostname or "").strip() or http_public_host

	if host_is_local_or_private(public_url_host):
		logger.warning(
			"Resolved public URL host is local/private (%s). External networks may not reach URLs in HTTP. "
			"Set GREENHOUSE_PUBLIC_BASE_URL or GREENHOUSE_TAILSCALE_FUNNEL_URL.",
			public_url_host,
		)

	capture_hour = max(0, min(23, raw_capture_hour))
	capture_minute = max(0, min(59, raw_capture_minute))
	if (capture_hour, capture_minute) != (raw_capture_hour, raw_capture_minute):
		logger.warning(
			"Invalid capture schedule (%s:%s); clamped to %02d:%02d",
			raw_capture_hour,
			raw_capture_minute,
			capture_hour,
			capture_minute,
		)

	logger.info(
		"Runtime config: telemetry_post_url=%s public_telemetry_url=%s telemetry_view_url=%s interval=%.2fs, serial=%s @ %s baud, live_dir=%s, weekly_dir=%s, image_dir=%s, log_dir=%s, http=%s:%s enabled=%s public_host=%s public_base=%s stream_fps=%.2f stream_size=%sx%s stream_url=%s latest_url=%s capture=%02d:%02d",
		telemetry_post_url,
		public_telemetry_url,
		telemetry_view_url,
		telemetry_publish_interval,
		serial_port,
		baudrate,
		live_data_dir,
		weekly_data_dir,
		image_dir,
		log_dir,
		http_host,
		http_port,
		http_enabled,
		http_public_host,
		public_base_url,
		http_stream_fps,
		http_stream_width,
		http_stream_height,
		stream_url,
		latest_image_url,
		capture_hour,
		capture_minute,
	)

	# Initialize components
	serial_comm = SerialComm(
		port=serial_port,
		baudrate=baudrate,
		timeout=1,
		reconnect_interval=0.5,
	)
	controller = FuzzyController()
	actuators = ActuatorDriver()
	
	# Initialize data storage
	sensor_logger = DataLogger(
		data_dir=live_data_dir,
		prefix="greenhouse",
		weekly_dir=weekly_data_dir,
	)
	control_logger = ControlOutputLogger(
		data_dir=live_data_dir,
		prefix="training_data",
		weekly_dir=weekly_data_dir,
	)

	# Initialize camera
	camera = Camera(image_dir=image_dir, stream_size=(http_stream_width, http_stream_height))
	http_server = None
	if http_enabled:
		http_server = HTTPServer(
			host=http_host,
			port=http_port,
			upload_dir=http_upload_dir,
			frame_provider=camera.capture_frame_jpeg,
			stream_fps=http_stream_fps,
		)
		try:
			http_server.start()
			logger.info("HTTP server started at http://%s:%s (upload_dir=%s)", http_host, http_port, http_upload_dir)
		except OSError as exc:
			logger.error("Unable to start HTTP server: %s", exc)
			http_server = None

	last_capture_day = None
	last_image_url = latest_served_image_url(http_upload_dir, image_base_url)
	if last_image_url:
		logger.info("Using last served image URL at startup: %s", last_image_url)

	# Connect
	serial_comm.connect()

	logger.info("Starting greenhouse control loop...")

	try:
		last_status = None
		last_telemetry_publish_time = 0.0
		telemetry_post_warned = False
		telemetry_post_fail_count = 0
		last_pump_check_time = 0.0
		pump_pulse_until = 0.0
		pump_pulse_pwm = 0
		raw_outputs_latest = {
			"humidifier_pwm": 0,
			"fan_pwm": 0,
			"led_pwm": 0,
			"pump_pwm": 0,
		}
		last_controlled = {}
		last_control = {}
		while True:
			current_time = time.time()
			has_fresh_control_data = False
			fresh_controlled_data = None

			# Ensure connections are active
			serial_comm.ensure_connected()

			# Status handling
			current_status = "ONLINE" if serial_comm.is_connected() else "OFFLINE"
			if current_status != last_status:
				logger.info(f"Serial status changed: {last_status} -> {current_status}")
				last_status = current_status

			now = datetime.now()

			today_capture_time = now.replace(hour=capture_hour, minute=capture_minute, second=0, microsecond=0)
			if last_capture_day != now.date() and now >= today_capture_time:
					image_path = camera.capture()
					logger.info(f"Growth image captured: {image_path}")
					image_name = os.path.basename(image_path)
					served_url = f"{image_base_url.rstrip('/')}/{quote(image_name)}"
					posted_ok = False
					if image_post_url:
						try:
							status_code, response_body = post_image(
								image_path,
								image_post_url,
								timeout=post_timeout,
							)
							if 200 <= status_code < 300:
								logger.info("Image posted to %s (status=%s): %s", image_post_url, status_code, response_body)
								posted_ok = True
							else:
								logger.warning("Image post returned non-success status=%s: %s", status_code, response_body)
						except Exception as exc:
							logger.error("Failed to post image %s to %s: %s", image_path, image_post_url, exc)

					if posted_ok:
						last_image_url = served_url
					else:
						# Keep /images URLs valid by copying the latest capture into the served upload directory.
						try:
							os.makedirs(http_upload_dir, exist_ok=True)
							fallback_path = os.path.join(http_upload_dir, image_name)
							shutil.copy2(image_path, fallback_path)
							last_image_url = served_url
							logger.warning("Image upload failed; copied capture to served directory: %s", fallback_path)
						except Exception as exc:
							logger.error("Failed to copy captured image to served directory: %s", exc)
					last_capture_day = now.date()

			# Read, parse, publish, compute control
			if serial_comm.is_connected():
				line = serial_comm.data_reading()
				if line:
					data = serial_comm.parse_data(line)
					if data:
						# Weekly rollover keeps live files updating without manual interruption.
						sensor_logger.rotate_weekly_if_needed(now=now)
						control_logger.rotate_weekly_if_needed(now=now)

						# Log sensor data (both controlled and control)
						sensor_logger.log_sensor_data(data)
						
						# Get controlled section and compute outputs
						controlled_data = data['controlled']
						control_data = data.get("control", {})
						last_controlled = controlled_data
						last_control = control_data
						raw_outputs_latest = controller.compute(controlled_data)
						has_fresh_control_data = True
						fresh_controlled_data = controlled_data

			# Build effective actuator command every loop from latest control output.
			outputs = dict(raw_outputs_latest)

			# Pump is time-gated. Pulse timing is enforced even if serial input stalls.
			if current_time < pump_pulse_until:
				outputs["pump_pwm"] = pump_pulse_pwm
			else:
				outputs["pump_pwm"] = 0
				pump_due = (current_time - last_pump_check_time) >= pump_check_interval
				if pump_due and has_fresh_control_data:
					last_pump_check_time = current_time
					requested_pump_pwm = int(raw_outputs_latest.get("pump_pwm", 0))
					if requested_pump_pwm > 0:
						pump_pulse_pwm = requested_pump_pwm
						pump_pulse_until = current_time + pump_pulse_seconds
						outputs["pump_pwm"] = pump_pulse_pwm
						logger.info(
							"Pump pulse started: pwm=%d duration=%.1fs (check interval=%.0fs)",
							pump_pulse_pwm,
							pump_pulse_seconds,
							pump_check_interval,
						)
					else:
						logger.info(
							"Pump check due; moisture is sufficient, skipping pulse (interval=%.0fs)",
							pump_check_interval,
						)

			actuators.apply_outputs(outputs)

			if has_fresh_control_data and fresh_controlled_data is not None:
				# Log control cycle (sensors + effective outputs)
				control_logger.log_control_cycle(fresh_controlled_data, outputs)

			if current_time - last_telemetry_publish_time >= telemetry_publish_interval:
				packet = {
					"timestamp": now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
					"status": current_status,
					"controlled": last_controlled,
					"control": last_control,
					"latest_image": last_image_url or latest_image_url,
					"stream": stream_url,
				}

				try:
					status_code, response_body = post_json(
						packet,
						telemetry_post_url,
						timeout=telemetry_post_timeout,
					)
					if 200 <= status_code < 300:
						if telemetry_post_warned:
							logger.info(
								"Telemetry posting recovered after %d failed attempt(s)",
								telemetry_post_fail_count,
							)
						telemetry_post_warned = False
						telemetry_post_fail_count = 0
					elif not telemetry_post_warned:
						logger.warning("Telemetry post returned non-success status=%s: %s", status_code, response_body)
						telemetry_post_warned = True
						telemetry_post_fail_count = 1
					else:
						telemetry_post_fail_count += 1
				except Exception as exc:
					if not telemetry_post_warned:
						logger.warning("Failed to post telemetry to %s: %s", telemetry_post_url, exc)
						telemetry_post_warned = True
						telemetry_post_fail_count = 1
					else:
						telemetry_post_fail_count += 1
				last_telemetry_publish_time = current_time

			time.sleep(loop_delay)

	except KeyboardInterrupt:
		logger.info("Stopping greenhouse control loop...")
	finally:
		if http_server is not None:
			http_server.stop()
		camera.shutdown()
		actuators.cleanup()
		serial_comm.close()
		sensor_logger.close()
		control_logger.close()
		logger.info("Cleanup complete")


if __name__ == "__main__":
	main()
