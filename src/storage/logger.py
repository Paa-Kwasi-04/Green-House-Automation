"""
Logging module for greenhouse control system.

This module provides a centralized logging configuration that saves all
application logs to a file for persistence and debugging. Logs are organized
by date with visual separators for improved readability.
"""

import logging
import logging.handlers
import os
from datetime import datetime


class DateSeparatorFilter(logging.Filter):
    """
    Logging filter that adds visual separators between logs from different days.
    
    This filter tracks the current date and inserts visual separators when
    the date changes, making it easier to distinguish logs from different days.
    """
    
    def __init__(self):
        """Initialize the date separator filter."""
        super().__init__()
        self.last_date = None
    
    def filter(self, record):
        """
        Add date separator if the date has changed.
        
        Parameters
        ----------
        record : logging.LogRecord
            The log record being processed.
        
        Returns
        -------
        bool
            Always returns True to allow the record through.
        """
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # If date has changed, inject a separator message
        if self.last_date is not None and self.last_date != current_date:
            # This will be handled by the custom formatter
            record.date_changed = True
        else:
            record.date_changed = False
        
        self.last_date = current_date
        record.current_date = current_date
        return True


class DayGroupedFormatter(logging.Formatter):
    """
    Custom formatter that adds visual separators and date headers for day grouping.
    
    Creates visually distinct sections for logs from each day, making it easier
    to scan through logs and identify which day's logs are being viewed.
    """
    
    def format(self, record):
        """
        Format log record with date grouping separators.
        
        Parameters
        ----------
        record : logging.LogRecord
            The log record to format.
        
        Returns
        -------
        str
            Formatted log message with separators if date changed.
        """
        # Get the base formatted message
        base_format = super().format(record)
        
        # Add separator if date changed
        if hasattr(record, 'date_changed') and record.date_changed:
            current_date = getattr(record, 'current_date', 'Unknown')
            separator = "\n" + "="*80 + "\n"
            date_header = f"LOG DATE: {current_date}\n"
            separator += date_header + "="*80 + "\n"
            return separator + base_format
        
        return base_format


class LoggerSetup:
    """
    Centralized logging configuration for the greenhouse control system.
    
    This class sets up rotating file handlers and console handlers to log
    all application events to both file and console output.
    
    Parameters
    ----------
    log_dir : str, optional
        Directory to store log files (default is 'logs' in current directory).
    log_level : int, optional
        Logging level (default is logging.INFO).
    
    Attributes
    ----------
    log_dir : str
        Directory where log files are stored.
    log_file : str
        Full path to the current log file.
    """
    
    def __init__(self, log_dir: str = "logs", log_level: int = logging.INFO):
        """Initialize logging setup with file and console handlers."""
        self.log_dir = log_dir
        
        # Create logs directory if it doesn't exist
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        # Use fixed filename with rotation (not timestamped per run)
        self.log_file = os.path.join(self.log_dir, "greenhouse.log")
    
    def setup(self):
        """
        Configure root logger with file and console handlers.
        
        Sets up rotating file handler (10MB per file, max 5 files) and
        console handler with consistent formatting. Adds date separation
        filter for better readability.
        
        Returns
        -------
        logging.Logger
            Configured root logger instance.
        """
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # Capture everything
        
        # Remove existing handlers to prevent duplicates
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create date separator filter
        date_filter = DateSeparatorFilter()
        
        # Format for all handlers
        file_formatter = DayGroupedFormatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        console_formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # File handler with rotation and day grouping
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(date_filter)
        root_logger.addHandler(file_handler)
        
        # Console handler - INFO level to hide DEBUG initialization messages
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        root_logger.debug(f"Logging initialized - Log file: {self.log_file}")
        return root_logger
    
    @staticmethod
    def get_logger(name: str):
        """
        Get a logger instance for a specific module.
        
        Parameters
        ----------
        name : str
            Module name (typically __name__).
        
        Returns
        -------
        logging.Logger
            Logger instance for the specified module.
        """
        return logging.getLogger(name)


def setup_logging(log_dir: str = "logs", log_level: int = logging.INFO):
    """
    Convenience function to quickly setup logging.
    
    Parameters
    ----------
    log_dir : str, optional
        Directory to store log files (default is 'logs').
    log_level : int, optional
        Console logging level (default is logging.INFO).
    
    Returns
    -------
    logging.Logger
        Configured root logger instance.
    
    Examples
    --------
    >>> setup_logging()
    >>> logger = logging.getLogger(__name__)
    >>> logger.info("Application started")
    """
    setup = LoggerSetup(log_dir=log_dir)
    setup.setup()
    
    # Set console handler level
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(log_level)
    
    return root_logger


if __name__ == "__main__":
    # Test logging setup
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Test log message")
    logger.warning("Test warning")
    logger.error("Test error")
