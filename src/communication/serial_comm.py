import serial
import time


class SerialComm:
    def __init__(self,port,baudrate=9600,timeout=1,reconnect_interval=0.5,max_retries=None):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reconnect_interval = reconnect_interval
        self.max_retries = max_retries
        self.ser = None
        self.last_reconnect_attempt = 0

    def is_connected(self):
        if self.ser is None:
            return False
        try:
            # Check if port is actually open
            is_open = self.ser.is_open
            if not is_open:
                # Force reset if closed
                self.ser = None
            return is_open
        except:
            self.ser = None
            return False

    def connect(self):
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
                )
            time.sleep(2)
            print(f"[INFO] Connected to {self.port}")
            return True
        except serial.SerialException as e:
            print(f"[ERROR] Could not open serial port: {e}")
            self.ser = None
            return False

    def ensure_connected(self):
        """Non-blocking reconnection with throttling"""
        if self.is_connected():
            return True

        current_time = time.time()
        if current_time - self.last_reconnect_attempt >= self.reconnect_interval:
            print(f"[SERIAL] Attempting to reconnect to {self.port}...")
            self.last_reconnect_attempt = current_time
            result = self.connect()
            if result:
                print(f"[SERIAL] Successfully reconnected!")
            return result
        
        return False

    
    def data_reading(self):
        try:
            # Try to reconnect if disconnected
            self.ensure_connected()
            
            # Check if connected and has data waiting
            if self.is_connected() and self.ser.in_waiting > 0:
                line:str = self.ser.readline().decode("utf-8",errors="ignore").strip()
                return line
            return None
        except Exception as e:
            print(f"[ERROR] Serial read failed: {e}")
            self.ser = None
            return None
        
    def parse_data(self,line:str):
        try:
            values = line.split(',')
            
            if len(values) != 5:
                print("[WARNING] Invalid data format")
                return None
            
            temperature = float(values[0])
            humidity = float(values[1])
            co2 = float(values[2])
            light = float(values[3])
            moisture = float(values[4])

            data = {
                "temperature": temperature,
                "humidity": humidity,
                "co2": co2,
                "light": light,
                "moisture": moisture
            }

            return data
        except Exception as e:
            print(f"[ERROR] Data parsing failed: {e}")
            return None

    def close(self):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
                print("[INFO] Serial connection closed")
        except serial.SerialException as e:
            print(f"[ERROR] Could not close serial port: {e}")  
        finally:
            self.ser = None 


def main(): 
    serial_comm = SerialComm(port='COM6', baudrate=115200, timeout=1, reconnect_interval=2.0, max_retries=None)
    serial_comm.connect()
    try:
        while True:
            line = serial_comm.data_reading()
            if line:
                data = serial_comm.parse_data(line)
                if data:
                    print(f"Received Data: {data}")
    except KeyboardInterrupt:
        print("[INFO] Stopping serial communication...")
    finally:
        serial_comm.close()


if __name__ == "__main__":
    main()