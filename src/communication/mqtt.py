"""
MQTT Communication Module for Green House Automation.

This module provides an MQTTClient class for handling MQTT communication
to publish sensor data and system status to an MQTT broker.
"""

import paho.mqtt.client as mqtt
import time
import logging
import os
import json
import socket
from datetime import datetime

logger = logging.getLogger(__name__)


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

    def __init__(self, broker, port=1883, client_id=None, data_topic="acity_greenhouse/paakwasi/data"):
        self.broker = broker
        self.port = port
        self.client_id = client_id or self._default_client_id()
        self.data_topic = data_topic
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=self.client_id)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.reconnect_interval = 5.0  # seconds
        self.last_reconnect = 0
        self.loop_started = False

    @staticmethod
    def _default_client_id():
        """Build a mostly-unique MQTT client id to prevent broker collisions."""
        host = socket.gethostname() or "pi"
        safe_host = "".join(ch for ch in host if ch.isalnum() or ch in "-_")
        return f"greenhouse_{safe_host}_{os.getpid()}"

    def on_connect(self, client, userdata, flags, rc):
        """Callback when the client connects or reconnects to the broker."""
        if rc == 0:
            logger.info("MQTT connected (client_id=%s)", self.client_id)
        else:
            logger.warning("MQTT connect returned rc=%s", rc)

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
                self.last_reconnect = current_time
                try:
                    self.client.reconnect()
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


    def publish_data_packet(self, packet: dict, topic: str = None, qos: int = 1, retain: bool = False):
        """
        Publish a single greenhouse JSON packet to one MQTT topic.

        Parameters
        ----------
        packet : dict
            Dictionary payload with timestamp, status, sections, outputs, and image URL.
        topic : str, optional
            MQTT topic override. Uses configured data_topic when omitted.
        qos : int, optional
            MQTT QoS level (default 1).
        retain : bool, optional
            Retain flag (default False).
        """
        resolved_topic = topic or self.data_topic
        try:
            if not self.ensure_connected():
                logger.warning("Skipping publish to %s because MQTT is disconnected", resolved_topic)
                return None
            payload = json.dumps(packet, ensure_ascii=True)
            result = self.client.publish(resolved_topic, payload, qos=qos, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.warning("Failed publishing packet to %s (rc=%s)", resolved_topic, result.rc)
            return result
        except Exception as exc:
            logger.error("Failed to publish MQTT packet: %s", exc)
            return None


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
    # Support both module execution and direct script execution.
    try:
        from communication.serial_comm import SerialComm
    except ModuleNotFoundError:
        from serial_comm import SerialComm
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Configuration
    BROKER = os.getenv("GREENHOUSE_MQTT_BROKER", "test.mosquitto.org")
    PORT = int(os.getenv("GREENHOUSE_MQTT_PORT", "1883"))
    DATA_TOPIC = os.getenv("GREENHOUSE_MQTT_DATA_TOPIC", "acity_greenhouse/paakwasi/data")
    SERIAL_PORT = os.getenv("GREENHOUSE_SERIAL_PORT", "/dev/ttyUSB0")
    BAUDRATE = int(os.getenv("GREENHOUSE_SERIAL_BAUDRATE", "115200"))
    DATA_PUBLISH_INTERVAL = float(os.getenv("GREENHOUSE_MQTT_PUBLISH_INTERVAL", "1.0"))
    LOOP_DELAY = float(os.getenv("GREENHOUSE_LOOP_DELAY", "0.1"))
    
    # Initialize components
    serial_comm = SerialComm(port=SERIAL_PORT, baudrate=BAUDRATE, timeout=1, reconnect_interval=0.5)
    mqtt_client = MQTTClient(broker=BROKER, port=PORT, data_topic=DATA_TOPIC)
    
    # Connect MQTT
    mqtt_client.connect()
    
    # Connect Serial
    serial_comm.connect()
    
    logger.info("Starting sensor data publishing loop...")
    
    try:
        last_status = None
        debug_counter = 0
        last_publish_time = 0.0
        last_controlled = {}
        last_control = {}
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
                        last_controlled = data.get("controlled", {})
                        last_control = data.get("control", {})

            current_time = time.time()
            if current_time - last_publish_time >= DATA_PUBLISH_INTERVAL:
                packet = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "status": current_status,
                    "controlled": last_controlled,
                    "control": last_control,
                }
                mqtt_client.publish_data_packet(packet, qos=1, retain=True)
                last_publish_time = current_time

            time.sleep(LOOP_DELAY)  # Small delay to prevent CPU overload
            
    except KeyboardInterrupt:
        logger.info("Stopping MQTT publisher...")
    finally:
        mqtt_client.disconnect()
        serial_comm.close()
        logger.info("Cleanup complete")


if __name__ == "__main__":
    main()