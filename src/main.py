"""Main entry point for greenhouse control system."""

import time
import os
import logging
import shutil
import socket
import ipaddress
import subprocess
from datetime import datetime
from urllib.parse import quote, urlparse
from communication.mqtt import MQTTClient
from communication.serial_comm import SerialComm
from communication.http_image_server import ImageHTTPServer, post_image
from control.fuzzy_controller import FuzzyController
from actuators import ActuatorDriver
from sensor.camera import Camera
from storage.logger import setup_logging
from storage.data_storage import DataLogger, ControlOutputLogger

logger = logging.getLogger(__name__)


def _default_runtime_dir() -> str:
	"""Default runtime output directory (parent of repository root)."""
	return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_env_int(name: str, default: int) -> int:
	"""Read integer env var with fallback."""
	try:
		return int(os.getenv(name, str(default)))
	except ValueError:
		logger.warning("Invalid integer for %s. Using default: %s", name, default)
		return default


def _get_env_float(name: str, default: float) -> float:
	"""Read float env var with fallback."""
	try:
		return float(os.getenv(name, str(default)))
	except ValueError:
		logger.warning("Invalid float for %s. Using default: %s", name, default)
		return default


def _get_env_bool(name: str, default: bool) -> bool:
	"""Read boolean env var with fallback."""
	raw = os.getenv(name)
	if raw is None:
		return default
	value = raw.strip().lower()
	if value in {"1", "true", "yes", "on"}:
		return True
	if value in {"0", "false", "no", "off"}:
		return False
	logger.warning("Invalid boolean for %s. Using default: %s", name, default)
	return default


def _latest_served_image_url(upload_dir: str, image_base_url: str):
	"""Return URL of the latest image currently available on the HTTP server."""
	try:
		if not os.path.isdir(upload_dir):
			return None
		candidates = []
		for name in os.listdir(upload_dir):
			if name.lower().endswith((".jpg", ".jpeg", ".png")):
				full_path = os.path.join(upload_dir, name)
				if os.path.isfile(full_path):
					candidates.append(full_path)
		if not candidates:
			return None
		latest = max(candidates, key=os.path.getmtime)
		latest_name = os.path.basename(latest)
		return f"{image_base_url.rstrip('/')}/{quote(latest_name)}"
	except Exception as exc:
		logger.warning("Unable to resolve latest served image: %s", exc)
		return None


def _detect_lan_ip() -> str:
	"""Best-effort LAN IP detection for URLs shared to same-network clients."""
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
			# No packet is sent; connect() is used only to pick the outbound interface.
			sock.connect(("8.8.8.8", 80))
			ip = sock.getsockname()[0]
			if ip and not ip.startswith("127."):
				return ip
	except OSError:
		pass
	return "127.0.0.1"


def _detect_tailscale_ip() -> str | None:
	"""Try to find the local Tailscale 100.x.x.x address."""
	try:
		output = subprocess.check_output(
			["tailscale", "ip", "-4"],
			stderr=subprocess.DEVNULL,
			text=True,
		).strip()
		if output:
			# tailscale may return multiple IPv4 lines; prefer the first one.
			return output.splitlines()[0].strip()
	except Exception:
		return None
	return None


def _normalize_public_base_url(raw_value: str, default_scheme: str = "http") -> str:
	"""Normalize a public base URL (scheme://host[:port][/path]) without trailing slash."""
	raw = (raw_value or "").strip()
	if not raw:
		return ""
	if "://" not in raw:
		raw = f"{default_scheme}://{raw}"
	parsed = urlparse(raw)
	if not parsed.netloc and parsed.path:
		# Handles values like "example.com:8000" that urlparse treats as path.
		raw = f"{default_scheme}://{parsed.path}"
	return raw.rstrip("/")


def _host_is_local_or_private(host: str) -> bool:
	"""Return True if host is loopback/private IP or localhost."""
	host_value = (host or "").strip().lower()
	if host_value in {"localhost", "127.0.0.1", "0.0.0.0"}:
		return True
	try:
		ip_obj = ipaddress.ip_address(host_value)
		return ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local
	except ValueError:
		# Hostname/domain: cannot determine scope reliably.
		return False


def _resolve_public_base_url(http_public_host: str, http_port: int) -> str:
	"""Resolve externally shared base URL with priority: explicit > funnel > tailnet > detected tailscale > legacy host."""
	explicit_public = _normalize_public_base_url(
		os.getenv("GREENHOUSE_PUBLIC_BASE_URL", ""),
		default_scheme="http",
	)
	if explicit_public:
		return explicit_public

	funnel_public = _normalize_public_base_url(
		os.getenv("GREENHOUSE_TAILSCALE_FUNNEL_URL", ""),
		default_scheme="https",
	)
	if funnel_public:
		return funnel_public

	tailnet_host = (os.getenv("GREENHOUSE_TAILSCALE_HOST", "") or "").strip()
	if tailnet_host:
		tailnet_scheme = (os.getenv("GREENHOUSE_TAILSCALE_SCHEME", "http") or "http").strip().lower()
		if tailnet_scheme not in {"http", "https"}:
			logger.warning(
				"Invalid GREENHOUSE_TAILSCALE_SCHEME=%s. Using http.",
				tailnet_scheme,
			)
			tailnet_scheme = "http"
		return _normalize_public_base_url(tailnet_host, default_scheme=tailnet_scheme)

	ts_ip = _detect_tailscale_ip()
	if ts_ip:
		return f"http://{ts_ip}:{http_port}"

	return f"http://{http_public_host}:{http_port}"


def main():
	runtime_dir = os.getenv("GREENHOUSE_RUNTIME_DIR", _default_runtime_dir())
	log_dir = os.getenv("GREENHOUSE_LOG_DIR", os.path.join(runtime_dir, "logs"))
	live_data_dir = os.getenv("GREENHOUSE_LIVE_DIR", os.path.join(runtime_dir, "live"))
	weekly_data_dir = os.getenv("GREENHOUSE_WEEKLY_DIR", os.path.join(runtime_dir, "weekly"))
	image_dir = os.getenv("GREENHOUSE_IMAGE_DIR", os.path.join(runtime_dir, "image"))
	http_upload_dir = os.getenv("GREENHOUSE_HTTP_UPLOAD_DIR", os.path.join(image_dir, "posted"))

	# Setup centralized logging with file rotation and date grouping
	setup_logging(log_dir=log_dir, log_level=logging.INFO)
	
	# Configuration
	broker = os.getenv("GREENHOUSE_MQTT_BROKER", "test.mosquitto.org")
	port = _get_env_int("GREENHOUSE_MQTT_PORT", 1883)
	data_topic = os.getenv("GREENHOUSE_MQTT_DATA_TOPIC", "acity_greenhouse/paakwasi/data")
	serial_port = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyUSB0")
	baudrate = _get_env_int("GREENHOUSE_SERIAL_BAUDRATE", 115200)
	data_publish_interval = _get_env_float("GREENHOUSE_MQTT_PUBLISH_INTERVAL", 1.0)
	loop_delay = _get_env_float("GREENHOUSE_LOOP_DELAY", 0.1)
	http_enabled = os.getenv("GREENHOUSE_HTTP_ENABLED", "1").lower() not in {"0", "false", "no"}
	http_host = os.getenv("GREENHOUSE_HTTP_HOST", "0.0.0.0")
	http_port = _get_env_int("GREENHOUSE_HTTP_PORT", 8000)
	http_stream_fps = _get_env_float("GREENHOUSE_HTTP_STREAM_FPS", 6.0)
	http_stream_width = _get_env_int("GREENHOUSE_HTTP_STREAM_WIDTH", 640)
	http_stream_height = _get_env_int("GREENHOUSE_HTTP_STREAM_HEIGHT", 480)
	raw_capture_hour = _get_env_int("GREENHOUSE_CAPTURE_HOUR", 21)
	raw_capture_minute = _get_env_int("GREENHOUSE_CAPTURE_MINUTE", 0)
	post_timeout = _get_env_float("GREENHOUSE_POST_TIMEOUT", 5.0)
	http_public_host = os.getenv("GREENHOUSE_HTTP_PUBLIC_HOST", _detect_lan_ip())
	public_base_url = _resolve_public_base_url(http_public_host=http_public_host, http_port=http_port)
	default_post_url = f"http://127.0.0.1:{http_port}/upload"
	image_post_url = os.getenv("GREENHOUSE_POST_IMAGE_URL", default_post_url)
	image_base_url = os.getenv("GREENHOUSE_IMAGE_BASE_URL", f"{public_base_url}/images")
	latest_image_url = os.getenv("GREENHOUSE_LATEST_IMAGE_URL", f"{public_base_url}/latest")
	default_stream_url = f"{public_base_url}/stream"
	stream_url = os.getenv("GREENHOUSE_STREAM_URL", default_stream_url)
	public_url_host = (urlparse(public_base_url).hostname or "").strip() or http_public_host

	if _host_is_local_or_private(public_url_host):
		logger.warning(
			"Resolved public URL host is local/private (%s). External networks may not reach URLs in MQTT. "
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
		"Runtime config: MQTT=%s:%s topic=%s, serial=%s @ %s baud, live_dir=%s, weekly_dir=%s, image_dir=%s, log_dir=%s, http=%s:%s enabled=%s public_host=%s public_base=%s stream_fps=%.2f stream_size=%sx%s stream_url=%s latest_url=%s capture=%02d:%02d",
		broker,
		port,
		data_topic,
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
	mqtt_client = MQTTClient(broker=broker, port=port, data_topic=data_topic)
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
		http_server = ImageHTTPServer(
			host=http_host,
			port=http_port,
			upload_dir=http_upload_dir,
			frame_provider=camera.capture_frame_jpeg,
			stream_fps=http_stream_fps,
		)
		try:
			http_server.start()
			logger.info("HTTP image server started at http://%s:%s (upload_dir=%s)", http_host, http_port, http_upload_dir)
		except OSError as exc:
			logger.error("Unable to start HTTP image server: %s", exc)
			http_server = None

	last_capture_day = None
	last_image_url = _latest_served_image_url(http_upload_dir, image_base_url)
	if last_image_url:
		logger.info("Using last served image URL at startup: %s", last_image_url)

	# Connect
	mqtt_client.connect()
	serial_comm.connect()

	logger.info("Starting greenhouse control loop...")

	try:
		last_status = None
		last_publish_time = 0.0
		last_controlled = {}
		last_control = {}
		while True:
			# Ensure connections are active
			mqtt_client.ensure_connected()
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
						outputs = controller.compute(controlled_data)
						actuators.apply_outputs(outputs)
						
						# Log control cycle (sensors + outputs)
						control_logger.log_control_cycle(controlled_data, outputs)

			current_time = time.time()
			if current_time - last_publish_time >= data_publish_interval:
				packet = {
					"timestamp": now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
					"status": current_status,
					"controlled": last_controlled,
					"control": last_control,
					"latest_image": latest_image_url,
					"stream": stream_url,
				}

				# Retain the latest status packet so new subscribers receive endpoints immediately.
				mqtt_client.publish_data_packet(packet, qos=1, retain=True)
				last_publish_time = current_time

			time.sleep(loop_delay)

	except KeyboardInterrupt:
		logger.info("Stopping greenhouse control loop...")
	finally:
		if http_server is not None:
			http_server.stop()
		camera.shutdown()
		actuators.cleanup()
		mqtt_client.disconnect()
		serial_comm.close()
		sensor_logger.close()
		control_logger.close()
		logger.info("Cleanup complete")


if __name__ == "__main__":
	main()
