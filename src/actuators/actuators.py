"""Actuator driver for Raspberry Pi greenhouse hardware.

Hardware mapping (BCM numbering):
	- Fan 1 (Intake) -> GPIO 22
	- Fan 2 (Intake) -> GPIO 24
	- Fan 3 (Exhaust) -> GPIO 17
	- pump -> GPIO 4
	- LED (NeoPixel data) -> GPIO 18
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

try:
	from .Neopixel_driver import NeoPixelDriver
except ImportError:
	from Neopixel_driver import NeoPixelDriver

logger = logging.getLogger(__name__)


class ActuatorDriver:
	"""Controls greenhouse actuators connected through MOSFET modules.

	Uses BCM pin numbering via gpiozero and supports both direct ON/OFF and PWM duty control.
	Intake fans are ``fan_1`` and ``fan_2``. Exhaust fan is ``fan_3`` and runs
	from a configurable intake-derived model in ``set_fan_pwm``.
	"""

	PINS: Dict[str, int] = {
		"fan_1": 22,
		"fan_2": 24,
		"fan_3": 17,
		"pump": 4,
		"led": 18,
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
		self.intake_scale = self._get_env_float("GREENHOUSE_INTAKE_SCALE", 1.0)
		self.exhaust_ratio = self._get_env_float("GREENHOUSE_EXHAUST_RATIO", 1.25)
		self.exhaust_min_pwm = self._get_env_int("GREENHOUSE_EXHAUST_MIN_PWM", 80)
		self.exhaust_start_boost_pwm = self._get_env_int("GREENHOUSE_EXHAUST_START_BOOST_PWM", 20)
		self.exhaust_max_pwm = self._get_env_int("GREENHOUSE_EXHAUST_MAX_PWM", 255)
		self.led_fuzzy_enabled = os.getenv("GREENHOUSE_LED_FUZZY_ENABLED", "0").lower() in {"1", "true", "yes"}
		self._pwm_channels: Dict[str, PWMOutputDevice] = {}
		self._led_driver: NeoPixelDriver | None = None
		self._is_initialized = False
		self._initialize_gpio()

	@staticmethod
	def _get_env_float(name: str, default: float) -> float:
		"""Read float env var with fallback and warning on invalid values."""
		raw = os.getenv(name)
		if raw is None:
			return default
		try:
			return float(raw)
		except ValueError:
			logger.warning("Invalid float for %s=%r; using default %s", name, raw, default)
			return default

	@staticmethod
	def _get_env_int(name: str, default: int) -> int:
		"""Read integer env var with fallback and warning on invalid values."""
		raw = os.getenv(name)
		if raw is None:
			return default
		try:
			return int(raw)
		except ValueError:
			logger.warning("Invalid int for %s=%r; using default %s", name, raw, default)
			return default

	def _initialize_gpio(self) -> None:
		"""Create gpiozero PWM devices for every mapped actuator pin."""
		led_count = 120
		led_brightness = float(os.getenv("GREENHOUSE_NEOPIXEL_BRIGHTNESS", "1.0"))
		self._led_driver = NeoPixelDriver(
			pixel_count=led_count,
			brightness=led_brightness,
			log_transmissions=False,
		)

		for name, pin in self.PINS.items():
			if name == "led":
				continue
			device = PWMOutputDevice(
				pin,
				frequency=self.pwm_frequency,
				initial_value=0.0,
			)
			self._pwm_channels[name] = device

		self._is_initialized = True
		logger.info("Actuator GPIO initialized (PWM pins): %s; LED via NeoPixel GPIO18", self.PINS)

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
		if name == "led":
			self.set_led_pwm(255)
			return
		self._pwm_channels[name].on()

	def set_off(self, name: str) -> None:
		"""Switch an actuator fully OFF (0% duty).

		Parameters
		----------
		name : str
			Actuator key in ``PINS``.
		"""
		self._require_actuator(name)
		if name == "led":
			self.set_led_pwm(0)
			return
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
		if name == "led":
			led_pwm = int((duty / 100.0) * 255)
			self.set_led_pwm(led_pwm)
			return
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

	def set_humidifier_pwm(self, pwm_value: int) -> None:
		"""Set humidifier PWM (0-255)."""
		self.set_pwm_255("humidifier", pwm_value)

	def _exhaust_from_intake_pwm(self, intake_pwm: int) -> int:
		"""Derive exhaust PWM from intake PWM using configurable airflow compensation.

		The mapping is tuned for setups where intake fans move more air than exhaust
		fans by applying ratio scaling, startup boost, and a minimum spin threshold.
		"""
		intake = int(self._clamp(float(intake_pwm), 0.0, 255.0))
		if intake <= 0:
			return 0

		min_pwm = int(self._clamp(float(self.exhaust_min_pwm), 0.0, 255.0))
		max_pwm = int(self._clamp(float(self.exhaust_max_pwm), 0.0, 255.0))
		if max_pwm < min_pwm:
			max_pwm = min_pwm

		derived = int(intake * self.exhaust_ratio) + int(self.exhaust_start_boost_pwm)
		exhaust = max(min_pwm, derived)
		return int(self._clamp(float(exhaust), 0.0, float(max_pwm)))

	def set_fan_pwm(self, intake_pwm: int) -> None:
		"""Set intake and exhaust fan PWM from one intake PWM input.

		Parameters
		----------
		intake_pwm : int
			Intake fan PWM value in range 0-255.
		Notes
		-----
		Both intake fans (``fan_1`` and ``fan_2``) receive ``intake_pwm``.
		Exhaust fan (``fan_3``) PWM is derived using the configurable model:
		- ``GREENHOUSE_EXHAUST_RATIO`` (default: 1.25)
		- ``GREENHOUSE_EXHAUST_START_BOOST_PWM`` (default: 20)
		- ``GREENHOUSE_EXHAUST_MIN_PWM`` (default: 80)
		- ``GREENHOUSE_EXHAUST_MAX_PWM`` (default: 255)
		"""
		raw_intake = int(self._clamp(float(intake_pwm), 0.0, 255.0))
		intake = int(self._clamp(raw_intake * self.intake_scale, 0.0, 255.0))
		exhaust = self._exhaust_from_intake_pwm(intake)
		self.set_pwm_255("fan_1", intake)
		self.set_pwm_255("fan_2", intake)
		self.set_pwm_255("fan_3", exhaust)

	def set_led_pwm(self, pwm_value: int) -> None:
		"""Set LED PWM (0-255)."""
		if self._led_driver is None:
			raise RuntimeError("NeoPixel LED driver is not initialized")
		level = int(self._clamp(float(pwm_value), 0.0, 255.0))
		self._led_driver.set_white_pwm(level)

	def set_pump_pwm(self, pwm_value: int) -> None:
		"""Set pump PWM (0-255)."""
		self.set_pwm_255("pump", pwm_value)

	def apply_outputs(self, outputs: Dict[str, int]) -> None:
		"""Apply fuzzy controller outputs to GPIO actuators.

		Parameters
		----------
		outputs : dict of str to int
			Controller output dictionary.

		Expected keys
		-------------
		- humidifier_pwm
		- fan_pwm (applied to intake fans: fan_1 and fan_2)
		- led_pwm
		- pump_pwm

		Notes
		-----
		Exhaust fan (fan_3) PWM is derived from intake fan PWM using a
		configurable ratio + startup boost + min/max thresholds.
		"""
		self.set_humidifier_pwm(int(outputs.get("humidifier_pwm", 0)))
		self.set_fan_pwm(int(outputs.get("fan_pwm", 0)))
		if self.led_fuzzy_enabled:
			self.set_led_pwm(int(outputs.get("led_pwm", 0)))
		else:
			self.set_led_pwm(0)
		self.set_pump_pwm(int(outputs.get("pump_pwm", 0)))

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
			if self._led_driver is not None:
				self._led_driver.cleanup()
			logger.info("Actuator driver cleaned up")
		finally:
			self._is_initialized = False
			self._pwm_channels.clear()
			self._led_driver = None

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
	log_interval = float(os.getenv("GREENHOUSE_ACTUATOR_LOG_INTERVAL", "5.0"))

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
		last_info_log_time = 0.0
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
			logged_outputs = dict(outputs)
			fan_pwm = int(logged_outputs.pop("fan_pwm", 0))
			logged_outputs["intake_pwm"] = fan_pwm
			logged_outputs["exhaust_pwm"] = driver._exhaust_from_intake_pwm(fan_pwm)
			led_pwm = int(logged_outputs.pop("led_pwm", 0))
			logged_outputs["led"] = round(led_pwm / 255.0, 3)
			now_monotonic = time.monotonic()
			if now_monotonic - last_info_log_time >= log_interval:
				logger.info(
					"Applied outputs from serial data: sensors=%s outputs=%s",
					controlled_data,
					logged_outputs,
				)
				last_info_log_time = now_monotonic
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
