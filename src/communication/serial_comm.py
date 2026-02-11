import serial
import time


class SerialComm:
    def __init__(self,port,baudrate=9600,timeout=1,reconnect_interval=2.0,max_retries=None):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reconnect_interval = reconnect_interval
        self.max_retries = max_retries
        self.ser = None

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def connect(self):
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
                )
            time.sleep(2)
            print(f"[INFO] Connected to {self.port}")
        except serial.SerialException as e:
            print(f"[ERROR] Could not open serial port: {e}")
            self.ser = None

    def ensure_connected(self):
        if self.is_connected():
            return True

        attempts = 0
        while not self.is_connected():
            if self.max_retries is not None and attempts >= self.max_retries:
                return False
            attempts += 1
            self.connect()
            if not self.is_connected():
                time.sleep(self.reconnect_interval)
        return True

    
    def data_reading(self):
        try:
            if not self.ensure_connected():
                return None
            if self.ser and self.ser.in_waiting > 0:
                line:str = self.ser.readline().decode("utf-8",errors="ignore").strip()
                return line
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