"""Main entry point for greenhouse control system."""

import time

from communication.mqtt import MQTTClient
from communication.serial_comm import SerialComm
from control.fuzzy_controller import FuzzyController


def main():
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

	# Connect
	mqtt_client.connect()
	serial_comm.connect()

	print("[INFO] Starting greenhouse control loop...")

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
				print(f"[STATUS CHANGE] Serial status: {last_status} -> {current_status}")
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
						mqtt_client.publish_sensors(data)
						data = data['controlled']
						outputs = controller.compute(data)
						print(f"[CONTROL] {outputs}")

			time.sleep(loop_delay)
	except KeyboardInterrupt:
		print("\n[INFO] Stopping greenhouse control loop...")
	finally:
		mqtt_client.disconnect()
		serial_comm.close()
		print("[INFO] Cleanup complete")


if __name__ == "__main__":
	main()
