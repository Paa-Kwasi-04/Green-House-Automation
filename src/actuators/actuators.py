"""Actuator driver for Raspberry Pi greenhouse hardware.

Hardware mapping (BCM numbering):
- Fan 1 -> GPIO 22
- Fan 2 -> GPIO 17
- Peristaltic Pump -> GPIO 4
- LED Light -> GPIO 27
- Humidifier -> GPIO 10
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict
from gpiozero import PWMOutputDevice  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


class ActuatorDriver:
	"""Controls greenhouse actuators connected through MOSFET modules.

	Uses BCM pin numbering via gpiozero and supports both direct ON/OFF and PWM duty control.
	"""

	PINS: Dict[str, int] = {
		"fan_1": 22,
		"fan_2": 17,
		"pump": 4,
		"led": 27,
		"humidifier": 10,
	}

	def __init__(self, pwm_frequency: int = 1000) -> None:
		self.pwm_frequency = pwm_frequency
		self._pwm_channels: Dict[str, PWMOutputDevice] = {}
		self._is_initialized = False
		self._initialize_gpio()

	def _initialize_gpio(self) -> None:
		for name, pin in self.PINS.items():
			device = PWMOutputDevice(
				pin,
				frequency=self.pwm_frequency,
				initial_value=0.0,
			)
			self._pwm_channels[name] = device

		self._is_initialized = True
		logger.info("Actuator GPIO initialized (BCM): %s", self.PINS)

	@staticmethod
	def _clamp(value: float, lower: float, upper: float) -> float:
		return max(lower, min(upper, value))

	def _require_actuator(self, name: str) -> None:
		if name not in self.PINS:
			valid = ", ".join(sorted(self.PINS.keys()))
			raise ValueError(f"Unknown actuator '{name}'. Valid names: {valid}")

	def set_on(self, name: str) -> None:
		"""Switch an actuator fully ON (100% duty)."""
		self._require_actuator(name)
		self._pwm_channels[name].on()

	def set_off(self, name: str) -> None:
		"""Switch an actuator fully OFF (0% duty)."""
		self._require_actuator(name)
		self._pwm_channels[name].off()

	def set_duty_cycle(self, name: str, duty_cycle: float) -> None:
		"""Set duty cycle in range 0-100 for a named actuator."""
		self._require_actuator(name)
		duty = self._clamp(float(duty_cycle), 0.0, 100.0)
		self._pwm_channels[name].value = duty / 100.0

	def set_pwm_255(self, name: str, pwm_value: int) -> None:
		"""Set actuator output from 8-bit value in range 0-255."""
		clamped = int(self._clamp(float(pwm_value), 0.0, 255.0))
		duty = (clamped / 255.0) * 100.0
		self.set_duty_cycle(name=name, duty_cycle=duty)

	def apply_outputs(self, outputs: Dict[str, int]) -> None:
		"""Apply fuzzy controller outputs to GPIO actuators.

		Expected keys:
		- humidifier_pwm
		- fan_pwm (applied to both fan_1 and fan_2)
		- led_pwm
		- pump_pwm
		"""
		humidifier_pwm = int(outputs.get("humidifier_pwm", 0))
		fan_pwm = int(outputs.get("fan_pwm", 0))
		led_pwm = int(outputs.get("led_pwm", 0))
		pump_pwm = int(outputs.get("pump_pwm", 0))

		self.set_pwm_255("humidifier", humidifier_pwm)
		self.set_pwm_255("fan_1", fan_pwm)
		self.set_pwm_255("fan_2", fan_pwm)
		self.set_pwm_255("led", led_pwm)
		self.set_pwm_255("pump", pump_pwm)

	def all_off(self) -> None:
		"""Turn all actuators OFF without releasing GPIO resources."""
		for name in self.PINS:
			self.set_off(name)

	def cleanup(self) -> None:
		"""Turn everything off and release GPIO resources."""
		if not self._is_initialized:
			return

		try:
			self.all_off()
			for pwm in self._pwm_channels.values():
				pwm.close()
			logger.info("Actuator driver cleaned up")
		finally:
			self._is_initialized = False
			self._pwm_channels.clear()

def main() -> None:
	"""Run actuator test loop using live sensor data from serial communication."""
	logging.basicConfig(
		level=logging.INFO,
		format="%(asctime)s %(levelname)s %(name)s: %(message)s",
	)

	# Ensure src directory is in path for direct script execution
	src_root = Path(__file__).resolve().parent.parent
	if str(src_root) not in sys.path:
		sys.path.insert(0, str(src_root))

	from communication.serial_comm import SerialComm
	from control.fuzzy_controller import FuzzyController

	serial_port = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyACM0")
	baudrate = int(os.getenv("GREENHOUSE_SERIAL_BAUDRATE", "115200"))
	loop_delay = float(os.getenv("GREENHOUSE_LOOP_DELAY", "0.1"))

	driver = ActuatorDriver()
	controller = FuzzyController()
	serial_comm = SerialComm(
		port=serial_port,
		baudrate=baudrate,
		timeout=1,
		reconnect_interval=0.5,
	)
	serial_comm.connect()
	logger.info("Starting serial-driven actuator test routine")

	try:
		while True:
			line = serial_comm.data_reading()
			if not line:
				time.sleep(loop_delay)
				continue

			data = serial_comm.parse_data(line)
			if not data:
				continue

			controlled_data = data.get("controlled")
			if not isinstance(controlled_data, dict):
				logger.warning("Missing 'controlled' data section in serial payload")
				continue

			outputs = controller.compute(controlled_data)
			driver.apply_outputs(outputs)
			logger.info(
				"Applied outputs from serial data: sensors=%s outputs=%s",
				controlled_data,
				outputs,
			)
	except KeyboardInterrupt:
		logger.info("Stopping actuator serial test loop...")
	finally:
		driver.cleanup()
		serial_comm.close()
		logger.info("Actuator serial test routine complete")


if __name__ == "__main__":
	main()
