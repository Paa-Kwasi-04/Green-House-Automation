"""Main entry point for greenhouse control system."""

import time
import os
import logging
from datetime import datetime
from communication.mqtt import MQTTClient
from communication.serial_comm import SerialComm
from control.fuzzy_controller import FuzzyController
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
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


def main():
	runtime_dir = os.getenv("GREENHOUSE_RUNTIME_DIR", _default_runtime_dir())
	log_dir = os.getenv("GREENHOUSE_LOG_DIR", os.path.join(runtime_dir, "logs"))
	data_dir = os.getenv("GREENHOUSE_DATA_DIR", os.path.join(runtime_dir, "data"))

	# Setup centralized logging with file rotation and date grouping
	setup_logging(log_dir=log_dir, log_level=logging.INFO)
	
	# Configuration
	broker = os.getenv("GREENHOUSE_MQTT_BROKER", "localhost")
	port = _get_env_int("GREENHOUSE_MQTT_PORT", 1883)
	serial_port = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyACM0")
	baudrate = _get_env_int("GREENHOUSE_SERIAL_BAUDRATE", 115200)
	status_publish_interval = _get_env_float("GREENHOUSE_STATUS_INTERVAL", 1.0)
	loop_delay = _get_env_float("GREENHOUSE_LOOP_DELAY", 0.1)
	fallback_ports = os.getenv(
		"GREENHOUSE_SERIAL_FALLBACKS",
		"/dev/ttyACM0"
	)
	allow_onboard_uart = _get_env_bool("GREENHOUSE_ALLOW_ONBOARD_UART", False)
	auto_discover_ports = _get_env_bool("GREENHOUSE_SERIAL_AUTO_DISCOVER", False)
	preferred_ports = [p.strip() for p in fallback_ports.split(",") if p.strip()]

	logger.info(
		"Runtime config: MQTT=%s:%s, serial=%s @ %s baud, data_dir=%s, log_dir=%s",
		broker,
		port,
		serial_port,
		baudrate,
		data_dir,
		log_dir,
	)

	# Initialize components
	serial_comm = SerialComm(
		port=serial_port,
		baudrate=baudrate,
		timeout=1,
		reconnect_interval=0.5,
		preferred_ports=preferred_ports,
		allow_onboard_uart=allow_onboard_uart,
		auto_discover_ports=auto_discover_ports,
	)
	mqtt_client = MQTTClient(broker=broker, port=port)
	controller = FuzzyController()
	
	# Initialize data storage
	sensor_logger = DataLogger(data_dir=data_dir, prefix="greenhouse")
	control_logger = ControlOutputLogger(data_dir=data_dir, prefix="training_data")

	# Initialize camera
	camera = Camera()

	last_capture_day = None
	capture_hour = 21  # 9 PM

	# Connect
	mqtt_client.connect()
	serial_comm.connect()

	logger.info("Starting greenhouse control loop...")

	try:
		last_status = None
		last_publish_time = 0.0
		while True:
			# Ensure connections are active
			mqtt_client.ensure_connected()
			serial_comm.ensure_connected()

			# Status handling
			current_status = "ONLINE" if serial_comm.is_connected() else "OFFLINE"
			if current_status != last_status:
				logger.info(f"Serial status changed: {last_status} -> {current_status}")
				last_status = current_status

			current_time = time.time()
			if current_time - last_publish_time >= status_publish_interval:
				mqtt_client.publish_status(current_status)
				last_publish_time = current_time

			now = datetime.now()

			if now.hour == capture_hour:
				
				if last_capture_day != now.date():
					image_path = camera.capture()
					logger.info(f"Growth image captured: {image_path}")
					last_capture_day = now.date()

			# Read, parse, publish, compute control
			if serial_comm.is_connected():
				line = serial_comm.data_reading()
				if line:
					data = serial_comm.parse_data(line)
					if data:
						# Log sensor data (both controlled and control)
						sensor_logger.log_sensor_data(data)
						
						# Publish to MQTT
						mqtt_client.publish_sensors(data)
						
						# Get controlled section and compute outputs
						controlled_data = data['controlled']
						outputs = controller.compute(controlled_data)
						
						# Log control cycle (sensors + outputs)
						control_logger.log_control_cycle(controlled_data, outputs)

	except KeyboardInterrupt:
		logger.info("Stopping greenhouse control loop...")
	finally:
		mqtt_client.disconnect()
		serial_comm.close()
		sensor_logger.close()
		control_logger.close()
		logger.info("Cleanup complete")


if __name__ == "__main__":
	main()
