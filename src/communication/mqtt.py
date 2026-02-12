import paho.mqtt.client as mqtt
import json
import time
from serial_comm import SerialComm


class MQTTClient:

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
        if rc != 0:
            print(f"[MQTT] Unexpected disconnection: {rc}")
        else:
            print("[MQTT] Disconnected")

    def is_connected(self):
        return self.client.is_connected()

    def ensure_connected(self):
        """Auto-reconnect if disconnected"""
        if not self.is_connected():
            current_time = time.time()
            if current_time - self.last_reconnect >= self.reconnect_interval:
                print("[MQTT] Attempting to reconnect...")
                try:
                    self.client.reconnect()
                    self.last_reconnect = current_time
                    print("[MQTT] Reconnected to broker")
                except Exception as e:
                    print(f"[MQTT] Reconnect failed: {e}")
        return self.is_connected()

    def connect(self):
        try:
            self.client.connect(self.broker, self.port)
            if not self.loop_started:
                self.client.loop_start()  # Background networking thread
                self.loop_started = True
            print("[MQTT] Connected to broker")
        except Exception as e:
            print(f"[MQTT ERROR] Connection failed: {e}")


    def publish_sensors(self, data: dict):
        """
        Publishes each sensor value to its own topic.
        """
        for key, value in data.items():
            topic = f"greenhouse/sensors/{key}"
            payload = str(value)  # MQTT requires string/bytes
            self.client.publish(topic, payload)
            print(f"[MQTT] Published {topic} -> {payload}")


    def publish_status(self, status: str):
        """
        Publishes system status (e.g., ONLINE, OFFLINE, ERROR)
        """
        topic = "greenhouse/system/status"
        self.client.publish(topic, status)
        print(f"[MQTT] Published {topic} -> {status}")


    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Disconnected from broker")


def main():
    # Configuration
    BROKER = "test.mosquitto.org"  # Public MQTT broker
    PORT = 1883
    SERIAL_PORT = "COM6"  
    BAUDRATE = 115200
    
    # Initialize components
    serial_comm = SerialComm(port=SERIAL_PORT, baudrate=BAUDRATE, timeout=1, reconnect_interval=0.5)
    mqtt_client = MQTTClient(broker=BROKER, port=PORT)
    
    # Connect MQTT
    mqtt_client.connect()
    
    # Connect Serial
    serial_comm.connect()
    
    print("[INFO] Starting sensor data publishing loop...")
    
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
                print(f"[STATUS CHANGE] Serial status: {last_status} -> {current_status}")
                last_status = current_status
            
            # Publish status only once per second (not every 0.1s)
            current_time = time.time()
            if current_time - last_publish_time >= 1.0:
                mqtt_client.publish_status(current_status)
                last_publish_time = current_time
            
            # Debug output every 50 iterations
            debug_counter += 1
            if debug_counter % 50 == 0:
                print(f"[DEBUG] Serial connected: {serial_comm.is_connected()}, MQTT connected: {mqtt_client.is_connected()}")
            
            # Read and publish sensor data if serial is connected
            if serial_comm.is_connected():
                line = serial_comm.data_reading()
                if line:
                    data = serial_comm.parse_data(line)
                    if data:
                        mqtt_client.publish_sensors(data)
            
            time.sleep(0.1)  # Small delay to prevent CPU overload
            
    except KeyboardInterrupt:
        print("\n[INFO] Stopping MQTT publisher...")
    finally:
        mqtt_client.disconnect()
        serial_comm.close()
        print("[INFO] Cleanup complete")


if __name__ == "__main__":
    main()