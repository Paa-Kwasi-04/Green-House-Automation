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

logger = logging.getLogger(__name__)


try:
	from gpiozero import PWMOutputDevice  # type: ignore[import-not-found]
	_GPIOZERO_AVAILABLE = True
except ImportError:
	_GPIOZERO_AVAILABLE = False

	class PWMOutputDevice:  # type: ignore[no-redef]
		"""Mock gpiozero PWMOutputDevice for non-Pi environments."""

		def __init__(self, pin: int, *, frequency: int = 1000, initial_value: float = 0.0):
			self.pin = pin
			self.frequency = frequency
			self.value = initial_value

		def on(self) -> None:
			self.value = 1.0

		def off(self) -> None:
			self.value = 0.0

		def close(self) -> None:
			self.value = 0.0


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
		self._hardware_gpio = _GPIOZERO_AVAILABLE
		self._initialize_gpio()

	def _initialize_gpio(self) -> None:
		if not self._hardware_gpio:
			logger.warning(
				"gpiozero is not available. Running actuator driver in mock mode."
			)

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

	try:
		from communication.serial_comm import SerialComm
	except ModuleNotFoundError:
		# Allow running this file directly via: python actuators/actuators.py
		src_root = Path(__file__).resolve().parent.parent
		if str(src_root) not in sys.path:
			sys.path.insert(0, str(src_root))
		from communication.serial_comm import SerialComm

	try:
		from control.fuzzy_controller import FuzzyController
	except ModuleNotFoundError as exc:
		logger.warning(
			"FuzzyController unavailable (%s). Using fallback test controller.",
			exc,
		)

		class FuzzyController:  # type: ignore[no-redef]
			"""Fallback controller for actuator testing without scikit-fuzzy."""

			@staticmethod
			def _to_pwm(value: float) -> int:
				return int(max(0.0, min(255.0, value)))

			def compute(self, sensors: Dict[str, float]) -> Dict[str, int]:
				temp = float(sensors.get("temperature", 25.0))
				humidity = float(sensors.get("humidity", 55.0))
				light = float(sensors.get("light", 500.0))
				moisture = float(sensors.get("moisture", 50.0))

				fan_pwm = self._to_pwm((temp - 22.0) * 12.0 + (humidity - 60.0) * 3.0)
				humidifier_pwm = self._to_pwm((60.0 - humidity) * 6.0)
				led_pwm = self._to_pwm((700.0 - light) * 0.35)
				pump_pwm = self._to_pwm((45.0 - moisture) * 6.0)

				return {
					"humidifier_pwm": humidifier_pwm,
					"fan_pwm": fan_pwm,
					"led_pwm": led_pwm,
					"pump_pwm": pump_pwm,
				}

	serial_port = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyACM0")
	baudrate = int(os.getenv("GREENHOUSE_SERIAL_BAUDRATE", "115200"))
	loop_delay = float(os.getenv("GREENHOUSE_LOOP_DELAY", "0.1"))
	allow_onboard_uart = os.getenv("GREENHOUSE_ALLOW_ONBOARD_UART", "false").strip().lower() in {
		"1",
		"true",
		"yes",
		"on",
	}
	fallback_ports = os.getenv("GREENHOUSE_SERIAL_FALLBACKS", "/dev/ttyACM0")
	auto_discover_ports = os.getenv("GREENHOUSE_SERIAL_AUTO_DISCOVER", "false").strip().lower() in {
		"1",
		"true",
		"yes",
		"on",
	}
	preferred_ports = [p.strip() for p in fallback_ports.split(",") if p.strip()]

	driver = ActuatorDriver()
	controller = FuzzyController()
	serial_comm = SerialComm(
		port=serial_port,
		baudrate=baudrate,
		timeout=1,
		reconnect_interval=0.5,
		preferred_ports=preferred_ports,
		allow_onboard_uart=allow_onboard_uart,
		auto_discover_ports=auto_discover_ports,
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
