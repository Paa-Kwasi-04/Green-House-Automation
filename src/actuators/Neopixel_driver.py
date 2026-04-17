"""NeoPixel white-light driver for greenhouse lighting.

This module provides a small wrapper around Adafruit NeoPixel so code can
set LED brightness using the same 0-255 PWM-style values used elsewhere.
"""

from __future__ import annotations

import logging
import os
import sys
import time

import board
import neopixel

logger = logging.getLogger(__name__)


class NeoPixelDriver:
	"""Drive a NeoPixel strip/ring from GPIO18 using PWM-style brightness values.

	Parameters
	----------
	pin : board pin, optional
		Data pin used for NeoPixel output. Defaults to ``board.D18``.
	pixel_count : int, optional
		Number of LEDs on the strip/ring.
	brightness : float, optional
		Global NeoPixel brightness scaler in range 0.0-1.0.
	auto_write : bool, optional
		Whether each assignment writes immediately to hardware.

	Notes
	-----
	This driver sends neutral white by setting RGB channels equally to the
	provided 8-bit value.
	"""

	def __init__(
		self,
		pin=board.D18,
		pixel_count: int = 1,
		brightness: float = 1.0,
		auto_write: bool = False,
		log_transmissions: bool | None = None,
	) -> None:
		self._check_permissions()
		self.pin = pin
		self.pixel_count = int(max(1, pixel_count))
		self.brightness = self._clamp_float(brightness, 0.0, 1.0)
		self.auto_write = auto_write
		if log_transmissions is None:
			log_transmissions = os.getenv("GREENHOUSE_NEOPIXEL_LOG_TX", "1").lower() not in {"0", "false", "no"}
		self.log_transmissions = bool(log_transmissions)
		self._last_output_level: int | None = None
		self._pixels = neopixel.NeoPixel(
			self.pin,
			self.pixel_count,
			brightness=self.brightness,
			auto_write=self.auto_write,
			pixel_order=neopixel.GRB,
		)
		self._closed = False
		logger.info("NeoPixel initialized on GPIO18 (pixels=%d)", self.pixel_count)

	@staticmethod
	def _check_permissions() -> None:
		"""Fail early when process cannot access low-level memory mapping.

		On Raspberry Pi NeoPixel backends, missing /dev/mem permissions can
		trigger a native crash on first LED write. We preflight this here to
		provide a clear message instead.
		"""
		if os.name != "posix":
			return

		dev_mem = "/dev/mem"
		try:
			with open(dev_mem, "rb"):
				return
		except PermissionError as exc:
			raise PermissionError(
				"NeoPixel access requires elevated permissions for /dev/mem. "
				"Run with sudo using your venv interpreter, for example: "
				"sudo /home/pi/greenhouse_project/Green-House-Automation/src/.venv/bin/python "
				"actuators/Neopixel_driver.py"
			) from exc
		except FileNotFoundError:
			# Some environments may not expose /dev/mem. Let backend raise a
			# specific initialization error if needed.
			return

	@staticmethod
	def _clamp_int(value: int, lower: int, upper: int) -> int:
		return max(lower, min(upper, int(value)))

	@staticmethod
	def _clamp_float(value: float, lower: float, upper: float) -> float:
		return max(lower, min(upper, float(value)))

	def set_white_pwm(self, pwm_value: int) -> None:
		"""Set white light intensity from a PWM-like 8-bit value.

		Parameters
		----------
		pwm_value : int
			Value from 0-255. Values outside range are clamped.
		"""
		if self._closed:
			raise RuntimeError("NeoPixelDriver is closed")

		level = self._clamp_int(pwm_value, 0, 255)
		normalized = level / 255.0
		rgb = (level, level, level)
		if self._last_output_level == level:
			return
		if self.log_transmissions:
			logger.info(
				"NeoPixel TX GPIO18: value_0_to_1=%.3f",
				normalized,
			)
		self._pixels.fill(rgb)
		if not self.auto_write:
			self._pixels.show()
		self._last_output_level = level

	def off(self) -> None:
		"""Turn all pixels off."""
		if self._closed:
			return
		if self._last_output_level == 0:
			return
		if self.log_transmissions:
			logger.info("NeoPixel TX GPIO18: value_0_to_1=0.000")
		self._pixels.fill((0, 0, 0))
		if not self.auto_write:
			self._pixels.show()
		self._last_output_level = 0

	def cleanup(self) -> None:
		"""Turn LEDs off and release NeoPixel resources."""
		if self._closed:
			return
		try:
			self.off()
		finally:
			self._pixels.deinit()
			self._closed = True
			logger.info("NeoPixel driver cleaned up")


def main() -> None:
	"""Small manual test routine for NeoPixel brightness on GPIO18."""
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

	pixel_count = int(os.getenv("GREENHOUSE_NEOPIXEL_COUNT", "1"))
	delay = float(os.getenv("GREENHOUSE_NEOPIXEL_TEST_DELAY", "0.25"))

	try:
		driver = NeoPixelDriver(pixel_count=pixel_count)
	except Exception as exc:
		logger.error("Unable to initialize NeoPixel driver: %s", exc)
		raise SystemExit(1) from exc

	try:
		for value in (0, 32, 64, 128, 192, 255, 128, 64, 0):
			logger.info("Setting NeoPixel white PWM to %d", value)
			driver.set_white_pwm(value)
			time.sleep(delay)
	except KeyboardInterrupt:
		logger.info("NeoPixel test interrupted")
	finally:
		driver.cleanup()


if __name__ == "__main__":
	main()
