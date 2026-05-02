"""Fuzzy logic controller for greenhouse environment.

This module defines a fuzzy logic controller that maps sensor readings
to actuator PWM outputs for humidifier, fan, LED, and pump.
"""

import numpy as np
import skfuzzy as fuzz
import logging
import os
from skfuzzy import control as ctrl

logger = logging.getLogger(__name__)



class FuzzyController:
    """Fuzzy logic controller for greenhouse actuators.

    Parameters
    ----------
    None

    Attributes
    ----------
    T_set : float
        Temperature setpoint in °C.
    H_set : float
        Humidity setpoint in %.
    L_set : float
        Light setpoint in lux.
    M_set : float
        Soil moisture setpoint in %.
    humidifier_sim : skfuzzy.control.ControlSystemSimulation
        Simulation for humidifier control.
    fan_sim : skfuzzy.control.ControlSystemSimulation
        Simulation for fan control.
    led_sim : skfuzzy.control.ControlSystemSimulation
        Simulation for LED control.
    pump_sim : skfuzzy.control.ControlSystemSimulation
        Simulation for pump control.
    """

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

    def _smooth_input(self, key: str, value: float) -> float:
        """Apply exponential smoothing to a sensor input."""
        previous = self._smoothed_inputs.get(key)
        if previous is None:
            smoothed = value
        else:
            alpha = max(0.0, min(1.0, self.input_smoothing_alpha))
            smoothed = (alpha * value) + ((1.0 - alpha) * previous)

        self._smoothed_inputs[key] = smoothed
        return smoothed

    def __init__(self):
        """Initialize setpoints and build fuzzy control systems."""

        # Setpoints (configurable via env vars, with stable defaults)
        # Defaults are tuned to the observed greenhouse operating range in the
        # saved training data. They can still be overridden via environment variables.
        self.T_set = self._get_env_float("GREENHOUSE_SETPOINT_TEMPERATURE", 25.5)
        self.H_set = self._get_env_float("GREENHOUSE_SETPOINT_HUMIDITY", 79.0)
        self.L_set = self._get_env_float("GREENHOUSE_SETPOINT_LIGHT", 110.0)
        self.M_set = self._get_env_float("GREENHOUSE_SETPOINT_MOISTURE", 65.0)
        self.M_deadband = self._get_env_float("GREENHOUSE_SETPOINT_MOISTURE_DEADBAND", 5.0)
        self.output_slew_step = max(1, int(self._get_env_float("GREENHOUSE_OUTPUT_SLEW_STEP_PWM", 30.0)))
        self.input_smoothing_alpha = self._get_env_float("GREENHOUSE_INPUT_SMOOTHING_ALPHA", 0.35)
        self.light_deadband = self._get_env_float("GREENHOUSE_LIGHT_DEADBAND", 10.0)
        self._last_outputs = {
            "humidifier_pwm": 0,
            "fan_pwm": 0,
            "led_pwm": 0,
            "pump_pwm": 0,
        }
        self._smoothed_inputs = {
            "temperature": None,
            "humidity": None,
            "light": None,
            "moisture": None,
        }

        logger.info(
            "Fuzzy setpoints: T=%.2f, H=%.2f, L=%.2f, M=%.2f (deadband=%.2f)",
            self.T_set,
            self.H_set,
            self.L_set,
            self.M_set,
            self.M_deadband,
        )

        # Build systems
        self._build_humidifier()
        self._build_fan()
        self._build_led()
        self._build_pump()


    def _build_humidifier(self):
        """Build humidifier fuzzy control system."""

        temp_error = ctrl.Antecedent(np.arange(-12, 13, 1), 'temp_error')
        hum_error = ctrl.Antecedent(np.arange(-35, 36, 1), 'hum_error')
        humidifier = ctrl.Consequent(np.arange(0, 101, 1), 'humidifier')

        # Membership Functions
        temp_error['Cold'] = fuzz.trimf(temp_error.universe, [-12, -12, -3])
        temp_error['Cool'] = fuzz.trimf(temp_error.universe, [-6, -3, 0])
        temp_error['Normal'] = fuzz.trimf(temp_error.universe, [-2, 0, 2])
        temp_error['Hot'] = fuzz.trimf(temp_error.universe, [0, 5, 9])
        temp_error['VeryHot'] = fuzz.trimf(temp_error.universe, [7, 12, 12])

        hum_error['VeryDry'] = fuzz.trimf(hum_error.universe, [-35, -35, -15])
        hum_error['Dry'] = fuzz.trimf(hum_error.universe, [-20, -8, 0])
        hum_error['OK'] = fuzz.trimf(hum_error.universe, [-6, 0, 6])
        hum_error['Humid'] = fuzz.trimf(hum_error.universe, [0, 10, 18])
        hum_error['VeryHumid'] = fuzz.trimf(hum_error.universe, [15, 35, 35])

        humidifier['OFF'] = fuzz.trimf(humidifier.universe, [0, 0, 25])
        humidifier['LOW'] = fuzz.trimf(humidifier.universe, [20, 40, 60])
        humidifier['MED'] = fuzz.trimf(humidifier.universe, [50, 70, 90])
        humidifier['HIGH'] = fuzz.trimf(humidifier.universe, [80, 100, 100])

        rules = [
            ctrl.Rule(hum_error['VeryHumid'], humidifier['OFF']),
            ctrl.Rule(hum_error['Humid'], humidifier['OFF']),
            ctrl.Rule(hum_error['OK'] & temp_error['Cold'], humidifier['LOW']),
            ctrl.Rule(hum_error['OK'] & temp_error['Normal'], humidifier['LOW']),
            ctrl.Rule(hum_error['Dry'] & temp_error['VeryHot'], humidifier['LOW']),
            ctrl.Rule(hum_error['Dry'] & temp_error['Hot'], humidifier['MED']),
            ctrl.Rule(hum_error['Dry'] & temp_error['Normal'], humidifier['HIGH']),
            ctrl.Rule(hum_error['VeryDry'] & temp_error['Hot'], humidifier['MED']),
            ctrl.Rule(hum_error['VeryDry'] & temp_error['Normal'], humidifier['HIGH']),
            ctrl.Rule(temp_error['VeryHot'], humidifier['LOW']),
            ctrl.Rule(temp_error['Cold'] & hum_error['Dry'], humidifier['HIGH'])
        ]

        system = ctrl.ControlSystem(rules)
        self.humidifier_sim = ctrl.ControlSystemSimulation(system)

    def _build_fan(self):
        """Build fan fuzzy control system."""

        temp_error = ctrl.Antecedent(np.arange(-12, 13, 1), 'temp_error')
        hum_error = ctrl.Antecedent(np.arange(-35, 36, 1), 'hum_error')
        fan = ctrl.Consequent(np.arange(0, 101, 1), 'fan')

        # Membership Functions
        temp_error['Cold'] = fuzz.trimf(temp_error.universe, [-12, -12, -4])
        temp_error['Cool'] = fuzz.trimf(temp_error.universe, [-6, -3, 0])
        temp_error['Normal'] = fuzz.trimf(temp_error.universe, [-2, 0, 2])
        temp_error['Warm'] = fuzz.trimf(temp_error.universe, [1, 4, 7])
        temp_error['Hot'] = fuzz.trimf(temp_error.universe, [5, 8, 12])

        hum_error['VeryDry'] = fuzz.trimf(hum_error.universe, [-35, -35, -15])
        hum_error['Dry'] = fuzz.trimf(hum_error.universe, [-20, -8, 0])
        hum_error['OK'] = fuzz.trimf(hum_error.universe, [-6, 0, 6])
        hum_error['Humid'] = fuzz.trimf(hum_error.universe, [0, 10, 18])
        hum_error['VeryHumid'] = fuzz.trimf(hum_error.universe, [15, 35, 35])

        fan['OFF'] = fuzz.trimf(fan.universe, [0, 0, 25])
        fan['LOW'] = fuzz.trimf(fan.universe, [20, 40, 60])
        fan['MED'] = fuzz.trimf(fan.universe, [50, 70, 90])
        fan['HIGH'] = fuzz.trimf(fan.universe, [80, 100, 100])

        rules = [
            ctrl.Rule(temp_error['Cold'], fan['OFF']),
            ctrl.Rule(temp_error['Cool'] & hum_error['VeryHumid'], fan['LOW']),
            ctrl.Rule(temp_error['Cool'] & hum_error['OK'], fan['LOW']),
            ctrl.Rule(temp_error['Normal'] & hum_error['OK'], fan['LOW']),
            ctrl.Rule(temp_error['Normal'] & hum_error['Dry'], fan['LOW']),
            ctrl.Rule(temp_error['Normal'] & hum_error['VeryDry'], fan['MED']),
            ctrl.Rule(temp_error['Warm'] & hum_error['OK'], fan['MED']),
            ctrl.Rule(temp_error['Warm'] & hum_error['Humid'], fan['MED']),
            ctrl.Rule(temp_error['Warm'] & hum_error['VeryHumid'], fan['HIGH']),
            ctrl.Rule(temp_error['Hot'], fan['HIGH']),
            ctrl.Rule(hum_error['VeryHumid'], fan['MED']),
            ctrl.Rule(hum_error['Humid'] & temp_error['Hot'], fan['HIGH'])
        ]

        system = ctrl.ControlSystem(rules)
        self.fan_sim = ctrl.ControlSystemSimulation(system)

    def _build_led(self):
        """Build LED fuzzy control system."""
        light_error = ctrl.Antecedent(np.arange(-150, 151, 1), 'light_error')
        led = ctrl.Consequent(np.arange(0, 101, 1), 'led')

        # Membership Functions
        light_error['Bright'] = fuzz.trimf(light_error.universe, [-150, -150, -20])
        light_error['OK'] = fuzz.trimf(light_error.universe, [-35, 0, 35])
        light_error['Dark'] = fuzz.trimf(light_error.universe, [20, 60, 100])
        light_error['VeryDark'] = fuzz.trimf(light_error.universe, [80, 150, 150])

        led['OFF'] = fuzz.trimf(led.universe, [0, 0, 20])
        led['LOW'] = fuzz.trimf(led.universe, [15, 35, 55])
        led['MEDIUM'] = fuzz.trimf(led.universe, [50, 70, 90])
        led['HIGH'] = fuzz.trimf(led.universe, [80, 100, 100])

        rules = [
            ctrl.Rule(light_error['Bright'], led['OFF']),
            ctrl.Rule(light_error['OK'], led['LOW']),
            ctrl.Rule(light_error['Dark'], led['MEDIUM']),
            ctrl.Rule(light_error['VeryDark'], led['HIGH'])
        ]

        system = ctrl.ControlSystem(rules)
        self.led_sim = ctrl.ControlSystemSimulation(system)

    def _build_pump(self):
        """Build pump fuzzy control system."""
        moisture_error = ctrl.Antecedent(np.arange(-35, 36, 1), 'moisture_error')
        pump = ctrl.Consequent(np.arange(0, 101, 1), 'pump')

        # Membership Functions
        moisture_error['Wet'] = fuzz.trimf(moisture_error.universe, [-35, -35, -8])
        moisture_error['OK'] = fuzz.trimf(moisture_error.universe, [-10, 0, 10])
        moisture_error['Dry'] = fuzz.trimf(moisture_error.universe, [6, 20, 35])

        pump['OFF'] = fuzz.trimf(pump.universe, [0, 0, 20])
        pump['LOW'] = fuzz.trimf(pump.universe, [15, 35, 55])
        pump['HIGH'] = fuzz.trimf(pump.universe, [50, 75, 100])

        rules = [
            ctrl.Rule(moisture_error['Wet'], pump['OFF']),
            ctrl.Rule(moisture_error['OK'], pump['OFF']),
            ctrl.Rule(moisture_error['Dry'], pump['HIGH'])
        ]

        system = ctrl.ControlSystem(rules)
        self.pump_sim = ctrl.ControlSystemSimulation(system)

    def compute(self, sensor_data: dict):
        """Compute actuator PWM outputs from sensor data.

        Parameters
        ----------
        sensor_data : dict
            Dictionary with keys: ``temperature``, ``humidity``,
            ``light``, and ``moisture``.

        Returns
        -------
        dict
            PWM outputs for ``humidifier_pwm``, ``fan_pwm``, ``led_pwm``,
            and ``pump_pwm``.
        """

        T = sensor_data["temperature"]
        H = sensor_data["humidity"]
        L = sensor_data["light"]
        M = sensor_data["moisture"]

        T = self._smooth_input("temperature", float(T))
        H = self._smooth_input("humidity", float(H))
        L = self._smooth_input("light", float(L))
        M = self._smooth_input("moisture", float(M))

        # Compute and clip errors to antecedent universes for robust inference.
        # Temperature/humidity use actual - setpoint.
        # Light/moisture use setpoint - actual so deficits map to stronger actuation.
        eT = float(np.clip(T - self.T_set, -12.0, 12.0))
        eH = float(np.clip(H - self.H_set, -35.0, 35.0))
        eL = float(np.clip(self.L_set - L, -150.0, 150.0))
        eM = float(np.clip(self.M_set - M, -35.0, 35.0))

        if abs(eL) <= self.light_deadband:
            eL = 0.0

        try:
            # HUMIDIFIER
            self.humidifier_sim.input['temp_error'] = eT
            self.humidifier_sim.input['hum_error'] = eH
            self.humidifier_sim.compute()
            humidifier_output = self.humidifier_sim.output['humidifier']

            # FAN
            self.fan_sim.input['temp_error'] = eT
            self.fan_sim.input['hum_error'] = eH
            self.fan_sim.compute()
            fan_output = self.fan_sim.output['fan']

            # LED
            self.led_sim.input['light_error'] = eL
            self.led_sim.compute()
            led_output = self.led_sim.output['led']

            # PUMP
            if M >= (self.M_set - self.M_deadband):
                pump_output = 0.0
            else:
                self.pump_sim.input['moisture_error'] = eM
                self.pump_sim.compute()
                pump_output = self.pump_sim.output['pump']
        except Exception as exc:
            logger.error(
                "Fuzzy compute failed with inputs: T=%.2f, H=%.2f, L=%.2f, M=%.2f, "
                "errors: eT=%.2f, eH=%.2f, eL=%.2f, eM=%.2f; reusing last outputs",
                T, H, L, M, eT, eH, eL, eM,
                exc_info=True
            )
            return dict(self._last_outputs)
        
        # Convert to PWM
        next_outputs = {
            "humidifier_pwm": int(np.clip((humidifier_output / 100) * 255, 0, 255)),
            "fan_pwm": int(np.clip((fan_output / 100) * 255, 0, 255)),
            "led_pwm": int(np.clip((led_output / 100) * 255, 0, 255)),
            "pump_pwm": int(np.clip((pump_output / 100) * 255, 0, 255)),
        }

        # Temperature protection: use fan first, humidifier second.
        if eT >= 8.0:
            next_outputs["fan_pwm"] = max(next_outputs["fan_pwm"], 220)
        elif eT >= 5.0:
            next_outputs["fan_pwm"] = max(next_outputs["fan_pwm"], 180)
        elif eT >= 2.5:
            next_outputs["fan_pwm"] = max(next_outputs["fan_pwm"], 140)

        if eT >= 4.0:
            next_outputs["humidifier_pwm"] = min(next_outputs["humidifier_pwm"], 100)
        if eT >= 7.0:
            next_outputs["humidifier_pwm"] = min(next_outputs["humidifier_pwm"], 60)

        # If humidity is already close to the setpoint, keep humidifier gentle.
        if abs(eH) <= 5.0:
            next_outputs["humidifier_pwm"] = min(next_outputs["humidifier_pwm"], 80)

        # Very dark readings should not jump straight to full LED power.
        if eL > 0:
            next_outputs["led_pwm"] = min(next_outputs["led_pwm"], 220)

        # Limit per-cycle actuator jumps to reduce oscillation and stress.
        outputs = {}
        for key, new_val in next_outputs.items():
            prev = int(self._last_outputs.get(key, 0))
            delta = int(new_val) - prev
            if delta > self.output_slew_step:
                new_val = prev + self.output_slew_step
            elif delta < -self.output_slew_step:
                new_val = prev - self.output_slew_step
            outputs[key] = int(np.clip(new_val, 0, 255))

        self._last_outputs = dict(outputs)
        return {
            "humidifier_pwm": outputs["humidifier_pwm"],
            "fan_pwm": outputs["fan_pwm"],
            "led_pwm": outputs["led_pwm"],
            "pump_pwm": outputs["pump_pwm"],
        }

def main():
    """Read live serial data and print PWM outputs."""
    import time
    import os
    import sys

    src_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if src_root not in sys.path:
        sys.path.insert(0, src_root)

    try:
        from communication.serial_comm import SerialComm
    except ImportError:
        from serial_comm import SerialComm

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    controller = FuzzyController()
    serial_port = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyUSB0")
    baudrate = int(os.getenv("GREENHOUSE_SERIAL_BAUDRATE", "115200"))
    loop_delay = float(os.getenv("GREENHOUSE_LOOP_DELAY", "0.1"))
    log_interval = float(os.getenv("GREENHOUSE_FUZZY_LOG_INTERVAL", "5.0"))

    serial_comm = SerialComm(
        port=serial_port,
        baudrate=baudrate,
        timeout=1,
        reconnect_interval=0.5,
    )

    serial_comm.connect()
    logger.info("Starting fuzzy controller loop...")

    try:
        last_info_log_time = 0.0
        while True:
            serial_comm.ensure_connected()
            if serial_comm.is_connected():
                line = serial_comm.data_reading()
                if line:
                    parsed_data = serial_comm.parse_data(line)
                    if parsed_data:
                        # Use controlled section data for fuzzy logic
                        sensor_data = parsed_data['controlled']
                        outputs = controller.compute(sensor_data)
                        now_monotonic = time.monotonic()
                        if now_monotonic - last_info_log_time >= log_interval:
                            logger.info(
                                "Inputs: T=%.1f, H=%.1f, CO2=%.0f, L=%.0f, M=%.1f | Outputs: %s",
                                sensor_data['temperature'],
                                sensor_data['humidity'],
                                sensor_data['co2'],
                                sensor_data['light'],
                                sensor_data['moisture'],
                                outputs,
                            )
                            last_info_log_time = now_monotonic
            time.sleep(loop_delay)
    except KeyboardInterrupt:
        logger.info("Stopping fuzzy controller...")
    finally:
        serial_comm.close()

if __name__ == "__main__":
    main()