import serial
import time


class SerialComm:
    def __init__(self,port,baudrate=9600,timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

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

    
    def data_reading(self):
        try:
            if self.ser and self.ser.in_waiting > 0:
                line:str = self.ser.readline().decode("utf-8").strip()
                return line
        except Exception as e:
            print(f"[ERROR] Serial read failed: {e}")
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
                self.ser = None
                print("[INFO] Serial connection closed")
        except serial.SerialException as e:
            print(f"[ERROR] Could not close serial port: {e}")   


def main(): 
    serial_comm = SerialComm(port='COM6', baudrate=115200, timeout=1)
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