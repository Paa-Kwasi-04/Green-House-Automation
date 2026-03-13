# Smart Mushroom Greenhouse Control System

An IoT-based smart mushroom greenhouse automation system using a hybrid Arduino-Raspberry Pi architecture with fuzzy logic control. This project implements real-time environmental monitoring, automated control, and comparative data collection between controlled and uncontrolled greenhouse sections.

## System Overview

### Hardware Architecture
- **Arduino Uno**: Sensor data acquisition from both greenhouse sections
- **Raspberry Pi**: Fuzzy logic control, automation, MQTT publishing, and data logging
- **Control Method**: Mamdani fuzzy logic controllers (scikit-fuzzy)
- **Actuators**: 
  - Humidifier (PWM controlled)
  - Exhaust fan (PWM controlled)
  - LED grow lights (PWM controlled)
  - Water pump (PWM controlled)

### Monitored Parameters
- **Temperature** (°C)
- **Relative Humidity** (%)
- **CO₂ Concentration** (ppm)
- **Light Intensity** (lux)
- **Substrate Moisture** (%)

### Dual-Section Design
The system monitors two greenhouse sections in parallel:
- **Controlled Section**: Automated fuzzy logic control with actuators
- **Control Section**: Natural conditions for comparison (no automated control)

This design enables data-driven comparison of automated vs. natural growing conditions.

## Features

### 1. Real-Time Fuzzy Logic Control
- **Temperature & CO₂ Controller**: Fan speed adjustment
- **Temperature & Humidity Controller**: Humidifier output regulation
- **Light Controller**: LED brightness adjustment
- **Substrate Moisture Controller**: Pump activation control
- Setpoints: T=25°C, H=85%, CO₂=800ppm, Light=150lux, Moisture=65%

### 2. Communication Systems
- **Serial Communication**: Arduino → Raspberry Pi (115200 baud)
  - Automatic reconnection on disconnect
  - Robust data parsing with validation
  - Expected format: `Controlled|T,H,CO2,L,M;Control|T,H,CO2,L,M`
- **MQTT Publishing**: Real-time data to cloud broker
  - Topic structure: `greenhouse/{controlled|control}/{sensor}`
  - System status: `greenhouse/system/status`
  - Default broker: `localhost` (configurable via `GREENHOUSE_MQTT_BROKER`)

### 3. Camera & Visual Monitoring
- **Raspberry Pi Camera**: Daily growth image capture using `picamera2`
  - Captures one image per day at 21:00 (9 PM)
  - Images saved as `data/images/growth_<timestamp>.jpg`
  - Prevents duplicate captures within the same day

### 4. Data Logging & Storage
- **CSV Data Storage**: Separate files for each greenhouse section
  - `greenhouse_controlled.csv`: Controlled section sensor data
  - `greenhouse_control.csv`: Control section sensor data
  - `training_data.csv`: Sensor inputs + fuzzy controller outputs
- **Application Logging**: Rotating log files with date grouping
  - File: `logs/greenhouse.log`
  - Rotation: 10MB per file, max 5 files
  - Automatic date separators for readability

### 5. Robust Error Handling
- Automatic serial port reconnection
- MQTT broker reconnection with throttling
- Comprehensive logging for debugging
- Input validation and error recovery

## Repository Structure

```
Green-House-Automation/
├── Control_Algorithms/          # MATLAB fuzzy logic design files
│   ├── Humidity_Controller.mlx
│   ├── LED_controller.mlx
│   ├── Substrate_moisture_controller.mlx
│   └── Temperature_C02_Controller.mlx
├── src/                         # Main application code
│   ├── main.py                  # Main control loop entry point
│   ├── actuators/               # Actuator control modules
│   │   └── actuators.py
│   ├── communication/           # Communication modules
│   │   ├── serial_comm.py       # Arduino serial communication
│   │   └── mqtt.py              # MQTT client for cloud publishing
│   ├── control/                 # Control system modules
│   │   └── fuzzy_controller.py  # Fuzzy logic controller (scikit-fuzzy)
│   ├── sensor/                  # Sensor modules
│   │   └── camera.py            # Raspberry Pi Camera (daily growth capture)
│   └── storage/                 # Data logging modules
│       ├── logger.py            # Application logging setup
│       └── data_storage.py      # CSV data storage
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Installation & Setup

### Prerequisites
- Python 3.7+
- Arduino with sensor setup
- Raspberry Pi (or any Linux/Windows system for development)

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Dependencies
- `paho-mqtt`: MQTT client for cloud communication
- `pyserial`: Serial communication with Arduino
- `scikit-fuzzy`: Fuzzy logic control system
- `numpy`: Numerical computations
- `networkx`: Required by scikit-fuzzy
- `picamera2`: Raspberry Pi Camera interface (daily growth image capture)

## Configuration

All runtime parameters are controlled via environment variables. The system falls back to sensible defaults when variables are not set.

| Environment Variable | Default | Description |
|---|---|---|
| `GREENHOUSE_MQTT_BROKER` | `localhost` | MQTT broker hostname or IP address |
| `GREENHOUSE_MQTT_PORT` | `1883` | MQTT broker port |
| `GREENHOUSE_SERIAL_PORT` | `/dev/ttyACM0` | Primary serial port for Arduino |
| `GREENHOUSE_SERIAL_BAUDRATE` | `115200` | Serial baud rate |
| `GREENHOUSE_SERIAL_FALLBACKS` | `/dev/ttyACM0` | Comma-separated list of additional serial ports to try if the primary fails (e.g., `/dev/ttyUSB0,/dev/ttyACM0`) |
| `GREENHOUSE_SERIAL_AUTO_DISCOVER` | `false` | Auto-discover available serial ports |
| `GREENHOUSE_ALLOW_ONBOARD_UART` | `false` | Allow Raspberry Pi onboard UART (`/dev/serial0`, `/dev/ttyAMA0`) |
| `GREENHOUSE_RUNTIME_DIR` | One directory above the repository root | Base directory for `data/` and `logs/` |
| `GREENHOUSE_DATA_DIR` | `<RUNTIME_DIR>/data` | Directory for CSV data files |
| `GREENHOUSE_LOG_DIR` | `<RUNTIME_DIR>/logs` | Directory for log files |
| `GREENHOUSE_STATUS_INTERVAL` | `1.0` | Seconds between MQTT status publishes |
| `GREENHOUSE_LOOP_DELAY` | `0.1` | Main loop delay in seconds |

**Example – run against a local MQTT broker on Linux:**
```bash
export GREENHOUSE_MQTT_BROKER=localhost
export GREENHOUSE_SERIAL_PORT=/dev/ttyACM0
cd src
python main.py
```

**Example – Windows development setup:**
```bash
set GREENHOUSE_MQTT_BROKER=localhost
set GREENHOUSE_SERIAL_PORT=COM3
cd src
python main.py
```

## Usage

### Run the Complete System
```bash
cd src
python main.py
```

This starts:
- Serial communication with Arduino
- MQTT publishing to cloud broker
- Fuzzy logic control computation
- Data logging to CSV files
- Application logging
- Daily growth image capture at 21:00 (9 PM)

### Run Individual Modules

**Test Serial Communication:**
```bash
cd src/communication
python serial_comm.py
```

**Test MQTT Publishing:**
```bash
cd src/communication
python mqtt.py
```

**Test Fuzzy Controller:**
```bash
cd src/control
python fuzzy_controller.py
```

**Test Camera Capture:**
```bash
cd src/sensor
python camera.py
```

### Data Collection

The system automatically logs data to three CSV files:
- `data/greenhouse_controlled.csv`: Sensor data from controlled section
- `data/greenhouse_control.csv`: Sensor data from control section  
- `data/training_data.csv`: Complete control cycles (sensors + PWM outputs)

Daily growth images are saved to:
- `data/images/growth_<timestamp>.jpg`: One image per day captured at 21:00 (9 PM)

These files can be used for:
- Machine learning model training
- Performance analysis
- Environmental condition studies
- Comparative analysis of control effectiveness
- Visual growth tracking over time

## MQTT Topics

The system publishes data to the following MQTT topics:

| Topic | Description | Example Value |
|-------|-------------|---------------|
| `greenhouse/timestamp` | Current timestamp | `2026-02-16 12:30:45.123` |
| `greenhouse/controlled/temperature` | Controlled section temp | `25.5` |
| `greenhouse/controlled/humidity` | Controlled section humidity | `85.2` |
| `greenhouse/controlled/co2` | Controlled section CO₂ | `750.0` |
| `greenhouse/controlled/light` | Controlled section light | `145.0` |
| `greenhouse/controlled/moisture` | Controlled section moisture | `67.5` |
| `greenhouse/control/temperature` | Control section temp | `26.8` |
| `greenhouse/control/humidity` | Control section humidity | `78.3` |
| `greenhouse/control/co2` | Control section CO₂ | `820.0` |
| `greenhouse/control/light` | Control section light | `140.0` |
| `greenhouse/control/moisture` | Control section moisture | `62.0` |
| `greenhouse/system/status` | System connection status | `ONLINE` or `OFFLINE` |

## System Status

✅ **Completed:**
- Fuzzy logic controller design (MATLAB)
- Python implementation with scikit-fuzzy
- Serial communication with Arduino
- MQTT cloud integration
- Data logging and storage system
- Comprehensive application logging
- Dual-section monitoring
- Automatic reconnection handling
- Training data generation for ML
- Daily growth image capture (Raspberry Pi Camera)
- Environment variable based configuration

🚧 **Future Enhancements:**
- Web dashboard for real-time monitoring
- Machine learning model for predictive control
- Historical data visualization
- Alert system for out-of-range conditions
- Mobile app integration

## License

This project is part of academic research on smart greenhouse automation systems.

## Contributors

Paa-Kwasi-04
