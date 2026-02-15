"""
CSV Data Storage module for greenhouse sensor data and ML training.

This module provides functionality to store validated sensor data and control
outputs to CSV files for later use in machine learning model training.
"""

import csv
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DataLogger:
    """
    Store validated greenhouse sensor data to CSV files.
    
    Creates separate CSV files for controlled and control greenhouse sections,
    enabling easy comparison and ML model training on experimental data.
    
    Parameters
    ----------
    data_dir : str, optional
        Directory to store CSV files (default is 'data').
    prefix : str, optional
        Prefix for CSV filenames (default is 'greenhouse').
    
    Attributes
    ----------
    data_dir : str
        Directory where CSV files are stored.
    prefix : str
        Prefix for CSV filenames.
    controlled_file : str
        Path to controlled greenhouse CSV file.
    control_file : str
        Path to control greenhouse CSV file.
    controlled_writer : csv.DictWriter or None
        CSV writer for controlled data.
    control_writer : csv.DictWriter or None
        CSV writer for control data.
    """
    
    # Column names for controlled and control data
    SENSOR_COLUMNS = [
        'timestamp',
        'temperature',
        'humidity',
        'co2',
        'light',
        'moisture'
    ]
    
    # Column names for control outputs
    CONTROL_COLUMNS = [
        'timestamp',
        'temperature',
        'humidity',
        'co2',
        'light',
        'moisture',
        'humidifier_pwm',
        'fan_pwm',
        'led_pwm',
        'pump_pwm'
    ]
    
    def __init__(self, data_dir: str = "data", prefix: str = "greenhouse"):
        """Initialize data logger with file paths."""
        self.data_dir = data_dir
        self.prefix = prefix
        
        # Create data directory if it doesn't exist
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        # Use fixed filenames (append mode, no timestamps)
        self.controlled_file = os.path.join(
            self.data_dir,
            f"{prefix}_controlled.csv"
        )
        self.control_file = os.path.join(
            self.data_dir,
            f"{prefix}_control.csv"
        )
        
        # File handles and writers
        self.controlled_handle = None
        self.control_handle = None
        self.controlled_writer = None
        self.control_writer = None
        
        # Initialize files with headers
        self._initialize_files()
    
    def _initialize_files(self):
        """Initialize CSV files with headers (append if exists)."""
        try:
            # Check if controlled file exists, if not create with headers
            file_exists = os.path.exists(self.controlled_file)
            self.controlled_handle = open(self.controlled_file, 'a', newline='')
            self.controlled_writer = csv.DictWriter(
                self.controlled_handle,
                fieldnames=self.SENSOR_COLUMNS
            )
            if not file_exists:
                self.controlled_writer.writeheader()
                logger.debug(f"Created controlled data file: {self.controlled_file}")
            else:
                logger.debug(f"Appending to controlled data file: {self.controlled_file}")
            self.controlled_handle.flush()
            
            # Check if control file exists, if not create with headers
            file_exists = os.path.exists(self.control_file)
            self.control_handle = open(self.control_file, 'a', newline='')
            self.control_writer = csv.DictWriter(
                self.control_handle,
                fieldnames=self.SENSOR_COLUMNS
            )
            if not file_exists:
                self.control_writer.writeheader()
                logger.debug(f"Created control data file: {self.control_file}")
            else:
                logger.debug(f"Appending to control data file: {self.control_file}")
            self.control_handle.flush()
        except Exception as e:
            logger.error(f"Failed to initialize CSV files: {e}")
            raise
    
    def log_sensor_data(self, data: Dict):
        """
        Log sensor data from both greenhouse sections.
        
        Parameters
        ----------
        data : dict
            Dictionary with structure:
            {
                'timestamp': str,
                'controlled': {sensor_data},
                'control': {sensor_data}
            }
        
        Returns
        -------
        bool
            True if data was successfully logged, False otherwise.
        
        Examples
        --------
        >>> data = {
        ...     'timestamp': '2026-02-15 14:30:25.123',
        ...     'controlled': {'temperature': 25.5, 'humidity': 60.2, ...},
        ...     'control': {'temperature': 26.0, 'humidity': 58.5, ...}
        ... }
        >>> logger.log_sensor_data(data)
        """
        if not self.controlled_writer or not self.control_writer:
            logger.error("CSV writers not initialized")
            return False
        
        try:
            timestamp = data.get('timestamp', datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3])
            
            # Log controlled data
            if 'controlled' in data:
                controlled_row = {'timestamp': timestamp}
                controlled_row.update(data['controlled'])
                self.controlled_writer.writerow(controlled_row)
            
            # Log control data
            if 'control' in data:
                control_row = {'timestamp': timestamp}
                control_row.update(data['control'])
                self.control_writer.writerow(control_row)
            
            # Flush to ensure data is written
            self.controlled_handle.flush()
            self.control_handle.flush()
            
            return True
        except Exception as e:
            logger.error(f"Failed to log sensor data: {e}")
            return False
    
    def close(self):
        """
        Close CSV files and release resources.
        
        Should be called at program termination to ensure all data
        is written and files are properly closed.
        """
        try:
            if self.controlled_handle:
                self.controlled_handle.close()
                logger.info("Closed controlled data file")
            if self.control_handle:
                self.control_handle.close()
                logger.info("Closed control data file")
        except Exception as e:
            logger.error(f"Error closing CSV files: {e}")


class ControlOutputLogger:
    """
    Store sensor data with control outputs for ML model training.
    
    Logs synchronized sensor inputs with fuzzy controller outputs,
    creating a complete dataset for training predictive models.
    
    Parameters
    ----------
    data_dir : str, optional
        Directory to store CSV files (default is 'data').
    prefix : str, optional
        Prefix for CSV filename (default is 'training_data').
    
    Attributes
    ----------
    data_dir : str
        Directory where CSV files are stored.
    prefix : str
        Prefix for CSV filenames.
    file_path : str
        Path to the training data CSV file.
    """
    
    COLUMNS = [
        'timestamp',
        'temperature',
        'humidity',
        'co2',
        'light',
        'moisture',
        'humidifier_pwm',
        'fan_pwm',
        'led_pwm',
        'pump_pwm'
    ]
    
    def __init__(self, data_dir: str = "data", prefix: str = "training_data"):
        """Initialize control output logger."""
        self.data_dir = data_dir
        self.prefix = prefix
        
        # Create data directory if it doesn't exist
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        # Use fixed filename (append mode, no timestamps)
        self.file_path = os.path.join(
            self.data_dir,
            f"{prefix}.csv"
        )
        
        # File handle and writer
        self.file_handle = None
        self.writer = None
        
        # Initialize file
        self._initialize_file()
    
    def _initialize_file(self):
        """Initialize CSV file with headers (append if exists)."""
        try:
            file_exists = os.path.exists(self.file_path)
            self.file_handle = open(self.file_path, 'a', newline='')
            self.writer = csv.DictWriter(self.file_handle, fieldnames=self.COLUMNS)
            if not file_exists:
                self.writer.writeheader()
                logger.debug(f"Created training data file: {self.file_path}")
            else:
                logger.debug(f"Appending to training data file: {self.file_path}")
            self.file_handle.flush()
        except Exception as e:
            logger.error(f"Failed to initialize training data file: {e}")
            raise
    
    def log_control_cycle(self, sensor_data: Dict, control_outputs: Dict):
        """
        Log a complete control cycle (sensors + outputs).
        
        Parameters
        ----------
        sensor_data : dict
            Dictionary with sensor values: temperature, humidity, co2, light, moisture.
        control_outputs : dict
            Dictionary with PWM outputs: humidifier_pwm, fan_pwm, led_pwm, pump_pwm.
        
        Returns
        -------
        bool
            True if data was successfully logged, False otherwise.
        
        Examples
        --------
        >>> sensor_data = {'temperature': 25.5, 'humidity': 60.2, ...}
        >>> outputs = {'humidifier_pwm': 128, 'fan_pwm': 64, ...}
        >>> logger.log_control_cycle(sensor_data, outputs)
        """
        if not self.writer:
            logger.error("CSV writer not initialized")
            return False
        
        try:
            row = {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            }
            row.update(sensor_data)
            row.update(control_outputs)
            
            self.writer.writerow(row)
            self.file_handle.flush()
            
            return True
        except Exception as e:
            logger.error(f"Failed to log control cycle: {e}")
            return False
    
    def close(self):
        """
        Close CSV file and release resources.
        
        Should be called at program termination to ensure all data
        is written and file is properly closed.
        """
        try:
            if self.file_handle:
                self.file_handle.close()
                logger.info(f"Closed training data file: {self.file_path}")
        except Exception as e:
            logger.error(f"Error closing training data file: {e}")


if __name__ == "__main__":
    # Test data logging
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Test sensor data logging
    sensor_logger = DataLogger()
    test_data = {
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        'controlled': {
            'temperature': 25.5,
            'humidity': 60.2,
            'co2': 400.0,
            'light': 850.0,
            'moisture': 45.0
        },
        'control': {
            'temperature': 26.0,
            'humidity': 58.5,
            'co2': 420.0,
            'light': 830.0,
            'moisture': 42.0
        }
    }
    sensor_logger.log_sensor_data(test_data)
    sensor_logger.close()
    
    # Test control output logging
    control_logger = ControlOutputLogger()
    test_sensor = test_data['controlled']
    test_outputs = {
        'humidifier_pwm': 128,
        'fan_pwm': 64,
        'led_pwm': 200,
        'pump_pwm': 100
    }
    control_logger.log_control_cycle(test_sensor, test_outputs)
    control_logger.close()
    
    logger.info("Test completed successfully")
