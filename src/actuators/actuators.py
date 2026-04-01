"""Actuator driver for Raspberry Pi greenhouse hardware.

Hardware mapping (BCM numbering):
	- Fan 1 (Intake) -> GPIO 22
	- Fan 2 (Intake) -> GPIO 17
	- Fan 3 (Exhaust) -> GPIO 23
	- pump -> GPIO 4
	- LED -> GPIO 27
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
		"fan_3": 23,
		"pump": 4,
		"led": 27,
		"humidifier": 10,
	}

	def __init__(self, pwm_frequency: int = 1000) -> None:
		"""Initialize PWM channels for all configured actuators.

		Parameters
		----------
		pwm_frequency : int, optional
			PWM base frequency in Hz used for all channels.
		"""
		self.pwm_frequency = pwm_frequency
		self._pwm_channels: Dict[str, PWMOutputDevice] = {}
		self._is_initialized = False
		self._initialize_gpio()

	def _initialize_gpio(self) -> None:
		"""Create gpiozero PWM devices for every mapped actuator pin."""
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
		"""Clamp a numeric value to a closed interval.

		Parameters
		----------
		value : float
			Input value to clamp.
		lower : float
			Lower bound.
		upper : float
			Upper bound.

		Returns
		-------
		float
			Clamped value.
		"""
		return max(lower, min(upper, value))

	def _require_actuator(self, name: str) -> None:
		"""Validate an actuator name.

		Parameters
		----------
		name : str
			Actuator key expected to exist in ``PINS``.

		Raises
		------
		ValueError
			If the actuator key is unknown.
		"""
		if name not in self.PINS:
			valid = ", ".join(sorted(self.PINS.keys()))
			raise ValueError(f"Unknown actuator '{name}'. Valid names: {valid}")

	def set_on(self, name: str) -> None:
		"""Switch an actuator fully ON (100% duty).

		Parameters
		----------
		name : str
			Actuator key in ``PINS``.
		"""
		self._require_actuator(name)
		self._pwm_channels[name].on()

	def set_off(self, name: str) -> None:
		"""Switch an actuator fully OFF (0% duty).

		Parameters
		----------
		name : str
			Actuator key in ``PINS``.
		"""
		self._require_actuator(name)
		self._pwm_channels[name].off()

	def set_duty_cycle(self, name: str, duty_cycle: float) -> None:
		"""Set actuator duty cycle using percentage units.

		Parameters
		----------
		name : str
			Actuator key in ``PINS``.
		duty_cycle : float
			Duty cycle percentage in range 0-100. Values outside range are clamped.
		"""
		self._require_actuator(name)
		duty = self._clamp(float(duty_cycle), 0.0, 100.0)
		self._pwm_channels[name].value = duty / 100.0

	def set_pwm_255(self, name: str, pwm_value: int) -> None:
		"""Set actuator output from an 8-bit PWM value.

		Parameters
		----------
		name : str
			Actuator key in ``PINS``.
		pwm_value : int
			8-bit PWM value in range 0-255. Values outside range are clamped.
		"""
		clamped = int(self._clamp(float(pwm_value), 0.0, 255.0))
		duty = (clamped / 255.0) * 100.0
		self.set_duty_cycle(name=name, duty_cycle=duty)

	def apply_outputs(self, outputs: Dict[str, int]) -> None:
		"""Apply fuzzy controller outputs to GPIO actuators.

		Parameters
		----------
		outputs : dict of str to int
			Controller output dictionary.

		Expected keys:
		- humidifier_pwm
		- fan_pwm (applied to intake fans: fan_1 and fan_2)
		- led_pwm
		- pump_pwm

		Notes
		-----
		Exhaust fan (fan_3) runs at 75% of intake fan PWM to maintain
		balanced air circulation and prevent negative pressure.
		"""
		humidifier_pwm = int(outputs.get("humidifier_pwm", 0))
		fan_pwm = int(outputs.get("fan_pwm", 0))
		exhaust_pwm = int(fan_pwm * 0.75)  # Exhaust at 75% of intake
		led_pwm = int(outputs.get("led_pwm", 0))
		pump_pwm = int(outputs.get("pump_pwm", 0))

		self.set_pwm_255("humidifier", humidifier_pwm)
		self.set_pwm_255("fan_1", fan_pwm)
		self.set_pwm_255("fan_2", fan_pwm)
		self.set_pwm_255("fan_3", exhaust_pwm)
		self.set_pwm_255("led", led_pwm)
		self.set_pwm_255("pump", pump_pwm)

	def all_off(self) -> None:
		"""Turn all actuators OFF without releasing GPIO resources."""
		for name in self.PINS:
			self.set_off(name)

	def cleanup(self) -> None:
		"""Turn everything off and release GPIO resources.

		Notes
		-----
		This method is idempotent and safe to call more than once.
		"""
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
	"""Run an actuator test loop driven by live serial sensor values.

	Notes
	-----
	Reads sensor data, computes fuzzy outputs, and applies PWM values to the
	mapped actuators until interrupted.
	"""
	quiet = os.getenv("GREENHOUSE_ACTUATOR_QUIET", "0").lower() in {"1", "true", "yes"}
	log_level = logging.WARNING if quiet else logging.INFO
	
	logging.basicConfig(
		level=log_level,
		format="%(asctime)s %(levelname)s %(name)s: %(message)s",
	)

	# Ensure src directory is in path for direct script execution
	src_root = Path(__file__).resolve().parent.parent
	if str(src_root) not in sys.path:
		sys.path.insert(0, str(src_root))

	from communication.serial_comm import SerialComm
	from control.fuzzy_controller import FuzzyController

	serial_port = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyUSB0")
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
	if not quiet:
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
		if not quiet:
			logger.info("Stopping actuator serial test loop...")
	finally:
		driver.cleanup()
		serial_comm.close()
		if not quiet:
			logger.info("Actuator serial test routine complete")


if __name__ == "__main__":
	main()
