"""Main entry point for greenhouse control system."""

import time
import os
import logging
from datetime import datetime
from urllib.parse import quote
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
	post_timeout = _get_env_float("GREENHOUSE_POST_TIMEOUT", 5.0)
	default_post_url = f"http://127.0.0.1:{http_port}/upload"
	image_post_url = os.getenv("GREENHOUSE_POST_IMAGE_URL", default_post_url)
	image_base_url = os.getenv("GREENHOUSE_IMAGE_BASE_URL", f"http://127.0.0.1:{http_port}/images")

	logger.info(
		"Runtime config: MQTT=%s:%s topic=%s, serial=%s @ %s baud, live_dir=%s, weekly_dir=%s, image_dir=%s, log_dir=%s, http=%s:%s enabled=%s",
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
	camera = Camera(image_dir=image_dir)
	http_server = None
	if http_enabled:
		http_server = ImageHTTPServer(host=http_host, port=http_port, upload_dir=http_upload_dir)
		try:
			http_server.start()
			logger.info("HTTP image server started at http://%s:%s (upload_dir=%s)", http_host, http_port, http_upload_dir)
		except OSError as exc:
			logger.error("Unable to start HTTP image server: %s", exc)
			http_server = None

	last_capture_day = None
	last_image_url = None
	capture_hour = 21
	capture_minute = 00  

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

			if now.hour == capture_hour and now.minute == capture_minute:
				
				if last_capture_day != now.date():
					image_path = camera.capture()
					logger.info(f"Growth image captured: {image_path}")
					image_name = os.path.basename(image_path)
					last_image_url = f"{image_base_url.rstrip('/')}/{quote(image_name)}"
					if image_post_url:
						try:
							status_code, response_body = post_image(
								image_path,
								image_post_url,
								timeout=post_timeout,
							)
							if 200 <= status_code < 300:
								logger.info("Image posted to %s (status=%s): %s", image_post_url, status_code, response_body)
							else:
								logger.warning("Image post returned non-success status=%s: %s", status_code, response_body)
						except Exception as exc:
							logger.error("Failed to post image %s to %s: %s", image_path, image_post_url, exc)
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
					"image": last_image_url,
				}

				# Publish one JSON payload packet to the configured MQTT topic.
				mqtt_client.publish_data_packet(packet, qos=1)
				last_publish_time = current_time

			time.sleep(loop_delay)

	except KeyboardInterrupt:
		logger.info("Stopping greenhouse control loop...")
	finally:
		if http_server is not None:
			http_server.stop()
		actuators.cleanup()
		mqtt_client.disconnect()
		serial_comm.close()
		sensor_logger.close()
		control_logger.close()
		logger.info("Cleanup complete")


if __name__ == "__main__":
	main()
