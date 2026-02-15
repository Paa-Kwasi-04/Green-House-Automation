"""
MQTT Communication Module for Green House Automation.

This module provides an MQTTClient class for handling MQTT communication
to publish sensor data and system status to an MQTT broker.
"""

import paho.mqtt.client as mqtt
import time
import logging

logger = logging.getLogger(__name__)

try:
    from communication.serial_comm import SerialComm
except ImportError:
    from serial_comm import SerialComm


class MQTTClient:
    """
    MQTT client for publishing greenhouse sensor data and system status.
    
    This class manages MQTT broker connections, automatic reconnection,
    and publishing of sensor data and system status messages.
    
    Parameters
    ----------
    broker : str
        The MQTT broker hostname or IP address.
    port : int, optional
        The MQTT broker port number (default is 1883).
    client_id : str, optional
        Unique identifier for this MQTT client (default is "greenhouse_pi").
    
    Attributes
    ----------
    broker : str
        The MQTT broker hostname or IP address.
    port : int
        The MQTT broker port number.
    client_id : str
        Unique identifier for this MQTT client.
    client : paho.mqtt.client.Client
        The underlying MQTT client instance.
    reconnect_interval : float
        Time in seconds between reconnection attempts.
    last_reconnect : float
        Timestamp of the last reconnection attempt.
    loop_started : bool
        Whether the MQTT client's network loop has been started.
    """

    def __init__(self, broker, port=1883, client_id="greenhouse_pi"):
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.client = mqtt.Client(client_id=self.client_id)
        self.client.on_disconnect = self.on_disconnect
        self.reconnect_interval = 5.0  # seconds
        self.last_reconnect = 0
        self.loop_started = False

    def on_disconnect(self, client, userdata, rc):
        """
        Callback function triggered when the client disconnects from the broker.
        
        Parameters
        ----------
        client : paho.mqtt.client.Client
            The MQTT client instance.
        userdata : any
            User-defined data passed to callbacks.
        rc : int
            The disconnection result code. 0 indicates a clean disconnect,
            non-zero indicates an unexpected disconnection.
        
        Notes
        -----
        This method is automatically called by the paho-mqtt library.
        """
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection: {rc}")
        else:
            logger.info("MQTT disconnected")

    def is_connected(self):
        """
        Check if the MQTT client is currently connected to the broker.
        
        Returns
        -------
        bool
            True if connected to the broker, False otherwise.
        """
        return self.client.is_connected()

    def ensure_connected(self):
        """
        Ensure the MQTT client is connected with automatic reconnection.
        
        Attempts to reconnect if disconnected, with throttling based on
        reconnect_interval to prevent excessive reconnection attempts.
        
        Returns
        -------
        bool
            True if connected after this call, False otherwise.
        
        Notes
        -----
        This method is throttled to prevent excessive reconnection attempts.
        It will only attempt reconnection if the reconnect_interval has
        elapsed since the last attempt.
        """
        if not self.is_connected():
            current_time = time.time()
            if current_time - self.last_reconnect >= self.reconnect_interval:
                logger.info("Attempting to reconnect to MQTT broker...")
                try:
                    self.client.reconnect()
                    self.last_reconnect = current_time
                    logger.info("Reconnected to MQTT broker")
                except Exception as e:
                    logger.error(f"MQTT reconnect failed: {e}")
        return self.is_connected()

    def connect(self):
        """
        Establish a connection to the MQTT broker.
        
        Connects to the MQTT broker and starts the network loop in a
        background thread for handling network traffic.
        
        Notes
        -----
        This method starts a background thread for network operations.
        The loop is only started once to avoid multiple threads.
        Connection errors are caught and printed to stdout.
        """
        try:
            self.client.connect(self.broker, self.port)
            if not self.loop_started:
                self.client.loop_start()  # Background networking thread
                self.loop_started = True
            logger.info(f"Connected to MQTT broker {self.broker}:{self.port}")
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")


    def publish_sensors(self, data: dict):
        """
        Publish sensor data from both greenhouse sections to individual MQTT topics.
        
        Publishes sensor values from both the controlled (fuzzy logic) and control
        (comparison) sections to separate topic hierarchies:
        - Controlled section: 'greenhouse/controlled/{sensor}'
        - Control section: 'greenhouse/control/{sensor}'
        - Timestamp: 'greenhouse/timestamp'
        
        Parameters
        ----------
        data : dict
            Dictionary containing nested sensor data with structure:
            {
                'timestamp': str,
                'controlled': {'temperature': float, 'humidity': float, 'co2': float, 
                              'light': float, 'moisture': float},
                'control': {'temperature': float, 'humidity': float, 'co2': float,
                           'light': float, 'moisture': float}
            }
        
        Examples
        --------
        >>> client.publish_sensors({
        ...     'timestamp': '2026-02-15 14:30:45.123',
        ...     'controlled': {'temperature': 25.5, 'humidity': 60.2, 'co2': 400.0,
        ...                   'light': 850.0, 'moisture': 45.0},
        ...     'control': {'temperature': 26.0, 'humidity': 58.5, 'co2': 420.0,
        ...                'light': 830.0, 'moisture': 42.0}
        ... })
        [MQTT] Published greenhouse/timestamp -> 2026-02-15 14:30:45.123
        [MQTT] Published greenhouse/controlled/temperature -> 25.5
        [MQTT] Published greenhouse/controlled/humidity -> 60.2
        ...
        [MQTT] Published greenhouse/control/temperature -> 26.0
        [MQTT] Published greenhouse/control/humidity -> 58.5
        ...
        """
        # Publish timestamp
        if 'timestamp' in data:
            topic = "greenhouse/timestamp"
            payload = str(data['timestamp'])
            self.client.publish(topic, payload)
        
        # Publish controlled section data
        if 'controlled' in data:
            for key, value in data['controlled'].items():
                topic = f"greenhouse/controlled/{key}"
                payload = str(value)
                self.client.publish(topic, payload)
        
        # Publish control section data
        if 'control' in data:
            for key, value in data['control'].items():
                topic = f"greenhouse/control/{key}"
                payload = str(value)
                self.client.publish(topic, payload)


    def publish_status(self, status: str):
        """
        Publish the system status to the MQTT broker.
        
        Publishes the system status to the 'greenhouse/system/status' topic.
        
        Parameters
        ----------
        status : str
            The system status string (e.g., 'ONLINE', 'OFFLINE', 'ERROR').
        
        Examples
        --------
        >>> client.publish_status('ONLINE')
        [MQTT] Published greenhouse/system/status -> ONLINE
        """
        topic = "greenhouse/system/status"
        self.client.publish(topic, status)


    def disconnect(self):
        """
        Disconnect from the MQTT broker and stop the network loop.
        
        Cleanly shuts down the MQTT client by stopping the network loop
        and disconnecting from the broker.
        
        Notes
        -----
        This method should be called when the MQTT client is no longer
        needed or before program termination to properly release resources.
        """
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("Disconnected from MQTT broker")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Configuration
    BROKER = "test.mosquitto.org"  # Public MQTT broker
    PORT = 1883
    SERIAL_PORT = "COM3"  
    BAUDRATE = 115200
    
    # Initialize components
    serial_comm = SerialComm(port=SERIAL_PORT, baudrate=BAUDRATE, timeout=1, reconnect_interval=0.5)
    mqtt_client = MQTTClient(broker=BROKER, port=PORT)
    
    # Connect MQTT
    mqtt_client.connect()
    
    # Connect Serial
    serial_comm.connect()
    
    logger.info("Starting sensor data publishing loop...")
    
    try:
        last_status = None
        last_publish_time = 0
        debug_counter = 0
        while True:
            # Ensure MQTT connection is active
            mqtt_client.ensure_connected()
            
            # Actively try to reconnect serial if disconnected
            serial_comm.ensure_connected()
            
            # Check serial connection status
            current_status = "ONLINE" if serial_comm.is_connected() else "OFFLINE"
            
            # Log status changes
            if current_status != last_status:
                logger.info(f"Serial status changed: {last_status} -> {current_status}")
                last_status = current_status
            
            # Publish status only once per second (not every 0.1s)
            current_time = time.time()
            if current_time - last_publish_time >= 1.0:
                mqtt_client.publish_status(current_status)
                last_publish_time = current_time
            
            # Debug output every 50 iterations
            debug_counter += 1
            if debug_counter % 50 == 0:
                logger.debug(f"Serial connected: {serial_comm.is_connected()}, MQTT connected: {mqtt_client.is_connected()}")
            
            # Read and publish sensor data if serial is connected
            if serial_comm.is_connected():
                line = serial_comm.data_reading()
                if line:
                    data = serial_comm.parse_data(line)
                    if data:
                        mqtt_client.publish_sensors(data)
            
            time.sleep(0.1)  # Small delay to prevent CPU overload
            
    except KeyboardInterrupt:
        logger.info("Stopping MQTT publisher...")
    finally:
        mqtt_client.disconnect()
        serial_comm.close()
        logger.info("Cleanup complete")


if __name__ == "__main__":
    main()