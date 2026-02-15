"""Fuzzy logic controller for greenhouse environment.

This module defines a fuzzy logic controller that maps sensor readings
to actuator PWM outputs for humidifier, fan, LED, and pump.
"""

import numpy as np
import skfuzzy as fuzz
import logging
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
    CO2_set : float
        CO2 setpoint in ppm.
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

    def __init__(self):
        """Initialize setpoints and build fuzzy control systems."""

        # Setpoints
        self.T_set = 25
        self.H_set = 85
        self.CO2_set = 800
        self.L_set = 150
        self.M_set = 65

        # Build systems
        self._build_humidifier()
        self._build_fan()
        self._build_led()
        self._build_pump()


    def _build_humidifier(self):
        """Build humidifier fuzzy control system."""

        temp_error = ctrl.Antecedent(np.arange(-5, 6, 1), 'temp_error')
        hum_error = ctrl.Antecedent(np.arange(-30, 31, 1), 'hum_error')
        humidifier = ctrl.Consequent(np.arange(0, 101, 1), 'humidifier')

        # Membership Functions
        temp_error['Cold'] = fuzz.trimf(temp_error.universe, [-5, -5, 0])
        temp_error['Normal'] = fuzz.trimf(temp_error.universe, [-1, 0, 1])
        temp_error['Hot'] = fuzz.trimf(temp_error.universe, [0, 5, 5])

        hum_error['Low'] = fuzz.trimf(hum_error.universe, [-30, -30, 0])
        hum_error['OK'] = fuzz.trimf(hum_error.universe, [-10, 0, 10])
        hum_error['High'] = fuzz.trimf(hum_error.universe, [0, 30, 30])

        humidifier['OFF'] = fuzz.trimf(humidifier.universe, [0, 0, 25])
        humidifier['LOW'] = fuzz.trimf(humidifier.universe, [20, 40, 60])
        humidifier['MED'] = fuzz.trimf(humidifier.universe, [50, 70, 90])
        humidifier['HIGH'] = fuzz.trimf(humidifier.universe, [80, 100, 100])

        rules = [
            ctrl.Rule(hum_error['High'], humidifier['OFF']),
            ctrl.Rule(hum_error['OK'], humidifier['LOW']),
            ctrl.Rule(hum_error['Low'], humidifier['HIGH']),
            ctrl.Rule(temp_error['Hot'] & hum_error['Low'], humidifier['HIGH']),
            ctrl.Rule(temp_error['Cold'] & hum_error['High'], humidifier['OFF']),
            ctrl.Rule(temp_error['Normal'] & hum_error['Low'], humidifier['MED'])
        ]

        system = ctrl.ControlSystem(rules)
        self.humidifier_sim = ctrl.ControlSystemSimulation(system)

    def _build_fan(self):
        """Build fan fuzzy control system."""

        temp_error = ctrl.Antecedent(np.arange(-5, 6, 1), 'temp_error')
        co2_error = ctrl.Antecedent(np.arange(-1000, 1001, 10), 'co2_error')
        fan = ctrl.Consequent(np.arange(0, 101, 1), 'fan')

        # Membership Functions
        temp_error['Cold'] = fuzz.trimf(temp_error.universe, [-5, -5, 0])
        temp_error['Normal'] = fuzz.trimf(temp_error.universe, [-1, 0, 1])
        temp_error['Hot'] = fuzz.trimf(temp_error.universe, [0, 5, 5])

        co2_error['Low'] = fuzz.trimf(co2_error.universe, [-1000, -1000, 0])
        co2_error['OK'] = fuzz.trimf(co2_error.universe, [-300, 0, 300])
        co2_error['High'] = fuzz.trimf(co2_error.universe, [0, 1000, 1000])

        fan['OFF'] = fuzz.trimf(fan.universe, [0, 0, 25])
        fan['LOW'] = fuzz.trimf(fan.universe, [20, 40, 60])
        fan['MED'] = fuzz.trimf(fan.universe, [50, 70, 90])
        fan['HIGH'] = fuzz.trimf(fan.universe, [80, 100, 100])

        rules = [
            ctrl.Rule(temp_error['Cold'] & co2_error['Low'], fan['OFF']),
            ctrl.Rule(temp_error['Cold'] & co2_error['OK'], fan['LOW']),
            ctrl.Rule(temp_error['Cold'] & co2_error['High'], fan['MED']),

            ctrl.Rule(temp_error['Normal'] & co2_error['Low'], fan['LOW']),
            ctrl.Rule(temp_error['Normal'] & co2_error['OK'], fan['LOW']),
            ctrl.Rule(temp_error['Normal'] & co2_error['High'], fan['HIGH']),

            ctrl.Rule(temp_error['Hot'] & co2_error['Low'], fan['MED']),
            ctrl.Rule(temp_error['Hot'] & co2_error['OK'], fan['HIGH']),
            ctrl.Rule(temp_error['Hot'] & co2_error['High'], fan['HIGH'])
        ]

        system = ctrl.ControlSystem(rules)
        self.fan_sim = ctrl.ControlSystemSimulation(system)

    def _build_led(self):
        """Build LED fuzzy control system."""
        light_error = ctrl.Antecedent(np.arange(-200, 201, 1), 'light_error')
        led = ctrl.Consequent(np.arange(0, 101, 1), 'led')

        # Membership Functions
        light_error['Bright'] = fuzz.trimf(light_error.universe, [-200, -200, 0])
        light_error['OK'] = fuzz.trimf(light_error.universe, [-50, 0, 50])
        light_error['Dark'] = fuzz.trimf(light_error.universe, [0, 200, 200])

        led['OFF'] = fuzz.trimf(led.universe, [0, 0, 20])
        led['LOW'] = fuzz.trimf(led.universe, [15, 35, 55])
        led['MEDIUM'] = fuzz.trimf(led.universe, [50, 70, 90])
        led['HIGH'] = fuzz.trimf(led.universe, [80, 100, 100])

        rules = [
            ctrl.Rule(light_error['Bright'], led['OFF']),
            ctrl.Rule(light_error['OK'], led['LOW']),
            ctrl.Rule(light_error['Dark'], led['HIGH'])
        ]

        system = ctrl.ControlSystem(rules)
        self.led_sim = ctrl.ControlSystemSimulation(system)

    def _build_pump(self):
        """Build pump fuzzy control system."""
        moisture_error = ctrl.Antecedent(np.arange(-40, 41, 1), 'moisture_error')
        pump = ctrl.Consequent(np.arange(0, 101, 1), 'pump')

        # Membership Functions
        moisture_error['Wet'] = fuzz.trimf(moisture_error.universe, [-40, -40, 0])
        moisture_error['OK'] = fuzz.trimf(moisture_error.universe, [-10, 0, 10])
        moisture_error['Dry'] = fuzz.trimf(moisture_error.universe, [0, 40, 40])

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
            Dictionary with keys: ``temperature``, ``humidity``, ``co2``,
            ``light``, and ``moisture``.

        Returns
        -------
        dict
            PWM outputs for ``humidifier_pwm``, ``fan_pwm``, ``led_pwm``,
            and ``pump_pwm``.
        """

        T = sensor_data["temperature"]
        H = sensor_data["humidity"]
        CO2 = sensor_data["co2"]
        L = sensor_data["light"]
        M = sensor_data["moisture"]

        # Compute errors (actual - setpoint)
        eT = T - self.T_set
        eH = H - self.H_set
        eCO2 = CO2 - self.CO2_set
        eL = L - self.L_set
        eM = M - self.M_set

        # HUMIDIFIER
        self.humidifier_sim.input['temp_error'] = eT
        self.humidifier_sim.input['hum_error'] = eH
        self.humidifier_sim.compute()
        humidifier_output = self.humidifier_sim.output['humidifier']

        # FAN
        self.fan_sim.input['temp_error'] = eT   
        self.fan_sim.input['co2_error'] = eCO2
        self.fan_sim.compute()
        fan_output = self.fan_sim.output['fan']

        # LED
        self.led_sim.input['light_error'] = eL  
        self.led_sim.compute()
        led_output = self.led_sim.output['led']

        # PUMP
        self.pump_sim.input['moisture_error'] = eM
        self.pump_sim.compute()
        pump_output = self.pump_sim.output['pump']
        
        # Convert to PWM
        humidifier_pwm = int((humidifier_output / 100) * 255)
        fan_pwm = int((fan_output / 100) * 255)
        led_pwm = int((led_output / 100) * 255)
        pump_pwm = int((pump_output / 100) * 255)

        return {
            "humidifier_pwm": humidifier_pwm,
            "fan_pwm": fan_pwm,
            "led_pwm": led_pwm,
            "pump_pwm": pump_pwm
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
    serial_comm = SerialComm(port="COM3", baudrate=115200, timeout=1, reconnect_interval=0.5)

    serial_comm.connect()
    logger.info("Starting fuzzy controller loop...")

    try:
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
                        logger.info(f"Inputs: T={sensor_data['temperature']:.1f}, H={sensor_data['humidity']:.1f}, CO2={sensor_data['co2']:.0f}, L={sensor_data['light']:.0f}, M={sensor_data['moisture']:.1f}")
                        logger.info(f"Outputs: {outputs}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Stopping fuzzy controller...")
    finally:
        serial_comm.close()

if __name__ == "__main__":
    main()