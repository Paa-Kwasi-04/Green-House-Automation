"""Main entry point for greenhouse control system."""

import time
import logging
from communication.mqtt import MQTTClient
from communication.serial_comm import SerialComm
from control.fuzzy_controller import FuzzyController
from storage.logger import setup_logging
from storage.data_storage import DataLogger, ControlOutputLogger

logger = logging.getLogger(__name__)


def main():
	# Setup centralized logging with file rotation and date grouping
	setup_logging(log_dir="logs", log_level=logging.INFO)
	
	# Configuration
	broker = "test.mosquitto.org"
	port = 1883
	serial_port = "COM3"
	baudrate = 115200
	status_publish_interval = 1.0
	loop_delay = 0.1

	# Initialize components
	serial_comm = SerialComm(
		port=serial_port,
		baudrate=baudrate,
		timeout=1,
		reconnect_interval=0.5,
	)
	mqtt_client = MQTTClient(broker=broker, port=port)
	controller = FuzzyController()
	
	# Initialize data storage
	sensor_logger = DataLogger(data_dir="data", prefix="greenhouse")
	control_logger = ControlOutputLogger(data_dir="data", prefix="training_data")

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
