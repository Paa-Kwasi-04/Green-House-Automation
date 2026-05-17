#!/usr/bin/env python3
"""Quick shutdown helper to force actuator GPIOs to a safe state.

Run by systemd ExecStop to ensure pumps and LEDs are turned off during reboot.
"""
import sys
import os
import logging

# Ensure project src is on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logger = logging.getLogger("shutdown_gpio")
logging.basicConfig(level=logging.INFO)

try:
    from actuators import ActuatorDriver
except Exception as exc:
    logger.error("Unable to import ActuatorDriver: %s", exc)
    ActuatorDriver = None

try:
    import RPi.GPIO as GPIO  # type: ignore[import-not-found]
except Exception:
    GPIO = None


def main() -> None:
    if ActuatorDriver is None:
        logger.error("ActuatorDriver unavailable; aborting shutdown GPIO sequence")
        return

    pins = getattr(ActuatorDriver, "PINS", {})
    gpio_ready = GPIO is not None
    if gpio_ready:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

    for name, pin in pins.items():
        try:
            if name == "led":
                # Best-effort: if NeoPixel driver exists, attempt to clean it up
                try:
                    # Import local Neopixel driver
                    from .Neopixel_driver import NeoPixelDriver
                except Exception:
                    try:
                        from Neopixel_driver import NeoPixelDriver
                    except Exception:
                        NeoPixelDriver = None
                if NeoPixelDriver is not None:
                    try:
                        d = NeoPixelDriver(pixel_count=1, brightness=0)
                        d.cleanup()
                        logger.info("NeoPixel cleanup requested")
                    except Exception as exc:
                        logger.debug("NeoPixel cleanup failed: %s", exc)
                continue

            if gpio_ready:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
                GPIO.output(pin, GPIO.LOW)
                logger.info("Set pin %s (actuator=%s) LOW", pin, name)
            else:
                logger.warning("RPi.GPIO not available; unable to force pin %s (%s) low", pin, name)
        except Exception as exc:
            logger.warning("Failed to set pin %s (%s) LOW: %s", pin, name, exc)

    # Do not call GPIO.cleanup() here. Keeping the pins configured as outputs
    # avoids them floating back to an active state while shutdown continues.

if __name__ == '__main__':
    main()
