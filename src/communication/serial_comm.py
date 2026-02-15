"""
Serial Communication Module for Green House Automation.

This module provides a SerialComm class for handling serial communication with
Arduino or other microcontrollers to read sensor data from the greenhouse.
"""

import serial
import time
import logging
from datetime import datetime
from serial.tools import list_ports

logger = logging.getLogger(__name__)


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
        self.reconnect_logged = False  # Track if we've logged this reconnection attempt
        self.connection_error_logged = False  # Track if we've logged connection errors this session

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
                logger.error("No serial ports detected")
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
                    logger.info(f"Connected to serial port {self.port}")
                    self.connection_error_logged = False  # Reset error flag on successful connection
                    return True
                except serial.SerialException:
                    self.ser = None
                    continue

            # Log connection failure only once per session
            if not self.connection_error_logged:
                logger.error("Could not open any detected serial port")
                self.connection_error_logged = True
            return False
        except Exception as e:
            logger.error(f"Serial connection failed: {e}")
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
            self.reconnect_logged = False  # Reset flag when successfully connected
            return True

        current_time = time.time()
        if current_time - self.last_reconnect_attempt >= self.reconnect_interval:
            # Log only once per reconnection session
            if not self.reconnect_logged:
                logger.info(f"Attempting to reconnect to {self.port}...")
                self.reconnect_logged = True
            
            self.last_reconnect_attempt = current_time
            result = self.connect()
            if result:
                logger.info(f"Successfully reconnected to {self.port}")
                self.reconnect_logged = False  # Reset flag on successful connection
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
            logger.error(f"Serial read failed: {e}")
            self.ser = None
            return None
        
    def parse_data(self, line: str):
        """
        Parse sensor data from two greenhouse sections.
        
        Expects data in the format:
        Controlled|temp,humidity,co2,light,moisture;Control|temp,humidity,co2,light,moisture
        
        The "Controlled" section contains data from the greenhouse controlled by fuzzy logic.
        The "Control" section contains data from the comparison greenhouse (no control).
        
        Parameters
        ----------
        line : str
            A formatted string containing sensor data from both sections.
        
        Returns
        -------
        dict or None
            A dictionary containing parsed sensor data with keys:
            - 'timestamp': Current timestamp
            - 'controlled': dict with 'temperature', 'humidity', 'co2', 'light', 'moisture'
            - 'control': dict with 'temperature', 'humidity', 'co2', 'light', 'moisture'
            Returns None if parsing fails or data format is invalid.
        
        Examples
        --------
        >>> serial_comm.parse_data("Controlled|25.5,60.2,400.0,850.0,45.0;Control|26.0,58.5,420.0,830.0,42.0")
        {'timestamp': '2026-02-15 14:30:25.123',
         'controlled': {'temperature': 25.5, 'humidity': 60.2, 'co2': 400.0, 
                       'light': 850.0, 'moisture': 45.0},
         'control': {'temperature': 26.0, 'humidity': 58.5, 'co2': 420.0, 
                    'light': 830.0, 'moisture': 42.0}}
        """
        try:
            # Split by semicolon to separate the two datasets
            sections = line.split(';')
            
            if len(sections) != 2:
                logger.warning(f"Invalid data format - expected 2 sections, got {len(sections)}")
                return None
            
            # Parse Controlled section
            controlled_section = sections[0]
            if not controlled_section.startswith("Controlled|"):
                logger.warning("Missing 'Controlled|' prefix")
                return None
            
            controlled_values = controlled_section.replace("Controlled|", "").split(',')
            if len(controlled_values) != 5:
                logger.warning(f"Invalid controlled data - expected 5 values, got {len(controlled_values)}")
                return None
            
            # Parse Control section
            control_section = sections[1]
            if not control_section.startswith("Control|"):
                logger.warning("Missing 'Control|' prefix")
                return None
            
            control_values = control_section.replace("Control|", "").split(',')
            if len(control_values) != 5:
                logger.warning(f"Invalid control data - expected 5 values, got {len(control_values)}")
                return None
            
            # Create data dictionary
            data = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "controlled": {
                    "temperature": float(controlled_values[0]),
                    "humidity": float(controlled_values[1]),
                    "co2": float(controlled_values[2]),
                    "light": float(controlled_values[3]),
                    "moisture": float(controlled_values[4])
                },
                "control": {
                    "temperature": float(control_values[0]),
                    "humidity": float(control_values[1]),
                    "co2": float(control_values[2]),
                    "light": float(control_values[3]),
                    "moisture": float(control_values[4])
                }
            }

            return data
        except Exception as e:
            logger.error(f"Data parsing failed: {e}")
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
                logger.info("Serial connection closed")
        except serial.SerialException as e:
            logger.error(f"Could not close serial port: {e}")  
        finally:
            self.ser = None 


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    serial_comm = SerialComm(port='COM3', baudrate=115200, timeout=1, reconnect_interval=2.0, max_retries=None)
    serial_comm.connect()
    try:
        while True:
            line = serial_comm.data_reading()
            if line:
                data = serial_comm.parse_data(line)
                if data:
                    logger.info(f"Received Data: {data}")
    except KeyboardInterrupt:
        logger.info("Stopping serial communication...")
    finally:
        serial_comm.close()


if __name__ == "__main__":
    main()