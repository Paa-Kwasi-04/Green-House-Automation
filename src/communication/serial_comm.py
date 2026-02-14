"""
Serial Communication Module for Green House Automation.

This module provides a SerialComm class for handling serial communication with
Arduino or other microcontrollers to read sensor data from the greenhouse.
"""

import serial
import time
from datetime import datetime
from serial.tools import list_ports


class SerialComm:
    """
    Serial communication handler for greenhouse sensor data.
    
    This class manages serial port connections, automatic reconnection,
    and parsing of sensor data from connected devices.
    
    Parameters
    ----------
    port : str
        The serial port identifier (e.g., 'COM6' on Windows, '/dev/ttyUSB0' on Linux).
    baudrate : int, optional
        The baud rate for serial communication (default is 9600).
    timeout : float, optional
        Read timeout in seconds (default is 1).
    reconnect_interval : float, optional
        Time in seconds between reconnection attempts (default is 0.5).
    max_retries : int or None, optional
        Maximum number of reconnection attempts. None for unlimited (default is None).
    
    Attributes
    ----------
    port : str
        The serial port identifier.
    baudrate : int
        The baud rate for serial communication.
    timeout : float
        Read timeout in seconds.
    reconnect_interval : float
        Time between reconnection attempts.
    max_retries : int or None
        Maximum reconnection attempts.
    ser : serial.Serial or None
        The serial connection object.
    last_reconnect_attempt : float
        Timestamp of the last reconnection attempt.
    """
    
    def __init__(self, port, baudrate=9600, timeout=1, reconnect_interval=0.5, max_retries=None):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reconnect_interval = reconnect_interval
        self.max_retries = max_retries
        self.ser = None
        self.last_reconnect_attempt = 0

    def is_connected(self):
        """
        Check if the serial port is currently connected and open.
        
        Returns
        -------
        bool
            True if serial port is connected and open, False otherwise.
        """
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
        """
        Establish a connection to the serial port.
        
        Opens the serial port with the configured parameters. Waits 2 seconds
        after connection to allow the device to initialize.
        
        Returns
        -------
        bool
            True if connection successful, False otherwise.
        
        Notes
        -----
        This method will print connection status messages to stdout.
        """
        try:
            candidate_ports = []

            if self.port:
                candidate_ports.append(self.port)

            available_ports = [port.device for port in list_ports.comports()]
            for port in available_ports:
                if port not in candidate_ports:
                    candidate_ports.append(port)

            if not candidate_ports:
                print("[ERROR] No serial ports detected.")
                return False

            for port in candidate_ports:
                try:
                    self.ser = serial.Serial(
                        port=port,
                        baudrate=self.baudrate,
                        timeout=self.timeout
                    )
                    time.sleep(2)
                    self.port = port
                    print(f"[INFO] Connected to {self.port}")
                    return True
                except serial.SerialException:
                    self.ser = None
                    continue

            print("[ERROR] Could not open any detected serial port.")
            return False
        except Exception as e:
            print(f"[ERROR] Serial connection failed: {e}")
            self.ser = None
            return False

    def ensure_connected(self):
        """
        Ensure serial connection is active with non-blocking reconnection.
        
        Attempts to reconnect if disconnected, with throttling based on
        reconnect_interval to prevent excessive reconnection attempts.
        
        Returns
        -------
        bool
            True if connected after this call, False otherwise.
        
        Notes
        -----
        This method is non-blocking and throttled to prevent excessive
        reconnection attempts. It will only attempt reconnection if the
        reconnect_interval has elapsed since the last attempt.
        """
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
        """
        Read a line of data from the serial port.
        
        Automatically attempts to reconnect if disconnected. Reads data only
        if the connection is active and data is available in the buffer.
        
        Returns
        -------
        str or None
            A line of text data from the serial port, or None if no data
            is available or if an error occurs.
        
        Notes
        -----
        This method uses UTF-8 decoding with error ignoring to handle
        potential encoding issues in the received data.
        """
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
        
    def parse_data(self, line: str):
        """
        Parse a comma-separated line of sensor data.
        
        Expects data in the format: temperature,humidity,co2,light,moisture
        
        Parameters
        ----------
        line : str
            A comma-separated string containing five sensor values.
        
        Returns
        -------
        dict or None
            A dictionary containing parsed sensor data with keys:
            'temperature', 'humidity', 'co2', 'light', and 'moisture'.
            Returns None if parsing fails or data format is invalid.
        
        Examples
        --------
        >>> serial_comm.parse_data("25.5,60.2,400.0,850.0,45.0")
        {'temperature': 25.5, 'humidity': 60.2, 'co2': 400.0, 
         'light': 850.0, 'moisture': 45.0}
        """
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
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
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
        """
        Close the serial port connection.
        
        Safely closes the serial port if it is open and sets the connection
        object to None. Handles potential exceptions during closure.
        
        Notes
        -----
        This method should be called when the serial communication is no longer
        needed or before program termination to properly release resources.
        """
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
                print("[INFO] Serial connection closed")
        except serial.SerialException as e:
            print(f"[ERROR] Could not close serial port: {e}")  
        finally:
            self.ser = None 


def main(): 
    serial_comm = SerialComm(port='COM3', baudrate=115200, timeout=1, reconnect_interval=2.0, max_retries=None)
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