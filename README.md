# Smart Mushroom Greenhouse Control System

An IoT-based smart mushroom greenhouse automation system using a hybrid Arduino-Raspberry Pi architecture with fuzzy logic control. This project implements real-time environmental monitoring, automated control, live camera streaming, and comparative data collection between controlled and uncontrolled greenhouse sections.

## System Overview

### Hardware Architecture
- **Arduino Uno**: Sensor data acquisition from both greenhouse sections
- **Raspberry Pi**: Fuzzy logic control, automation, MQTT publishing, data logging, and camera streaming
- **Control Method**: Mamdani fuzzy logic controllers (scikit-fuzzy)
- **Actuators** (PWM via gpiozero, BCM pin numbering):
  - Fan 1 → GPIO 22
  - Fan 2 → GPIO 17
  - Peristaltic Pump → GPIO 4
  - LED Grow Lights → GPIO 27
  - Humidifier → GPIO 10

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
- **MQTT Publishing**: Real-time data as a single JSON packet
  - Default broker: `test.mosquitto.org` (configurable via `GREENHOUSE_MQTT_BROKER`)
  - Default topic: `acity_greenhouse/paakwasi/data` (configurable via `GREENHOUSE_MQTT_DATA_TOPIC`)
  - Packet fields: `timestamp`, `status`, `controlled`, `control`, `image`, `stream`

### 3. Camera & Visual Monitoring
- **Raspberry Pi Camera**: Daily still capture and live MJPEG stream using `picamera2`
  - Captures one high-resolution image per day at the configured time (default 21:00)
  - Images saved under `<GREENHOUSE_IMAGE_DIR>/` and served via the built-in HTTP server
  - Live MJPEG stream accessible at `http://<host>:<port>/stream` (default 6 fps, 640×480)
  - Web viewer page available at `http://<host>:<port>/viewer`

### 4. HTTP Image Server
- Built-in HTTP server for camera image access and live streaming (default port 8000)
- Endpoints:
  - `GET /viewer` – browser-based viewer with live stream and latest snapshot
  - `GET /stream` – MJPEG live stream
  - `GET /latest` – latest captured image file
  - `GET /images/<name>` – access a specific stored image by filename
  - `POST /upload` – receive an image (raw bytes, `X-Filename` header for name)
  - `GET /health` – server health check

### 5. Data Logging & Storage
- **CSV Data Storage**: Live files updated continuously, archived weekly
  - `live/greenhouse_controlled.csv`: Controlled section sensor data
  - `live/greenhouse_control.csv`: Control section sensor data
  - `live/training_data.csv`: Sensor inputs + fuzzy controller outputs
  - `weekly/<YYYY-WW>/`: Weekly archives of the above files
- **Application Logging**: Rotating log files with date grouping
  - File: `logs/greenhouse.log`
  - Rotation: 10MB per file, max 5 files
  - Automatic date separators for readability

### 6. Robust Error Handling
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
│   │   └── actuators.py         # gpiozero PWM driver (BCM pins)
│   ├── communication/           # Communication modules
│   │   ├── serial_comm.py       # Arduino serial communication
│   │   ├── mqtt.py              # MQTT client for cloud publishing
│   │   └── http_image_server.py # HTTP server for images and live stream
│   ├── control/                 # Control system modules
│   │   └── fuzzy_controller.py  # Fuzzy logic controller (scikit-fuzzy)
│   ├── sensor/                  # Sensor modules
│   │   └── camera.py            # Raspberry Pi Camera (still capture + streaming)
│   └── storage/                 # Data logging modules
│       ├── logger.py            # Application logging setup
│       └── data_storage.py      # CSV data storage with weekly rotation
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Installation & Setup

### Prerequisites
- Python 3.7+
- Arduino with sensor setup
- Raspberry Pi with camera module

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Dependencies
- `gpiozero`: GPIO PWM control for Raspberry Pi actuators
- `paho-mqtt`: MQTT client for cloud communication
- `picamera2`: Raspberry Pi Camera interface (still capture and live streaming)
- `pyserial`: Serial communication with Arduino
- `scikit-fuzzy`: Fuzzy logic control system
- `numpy`: Numerical computations

## Configuration

All runtime parameters are controlled via environment variables. The system falls back to sensible defaults when variables are not set.

| Environment Variable | Default | Description |
|---|---|---|
| `GREENHOUSE_MQTT_BROKER` | `test.mosquitto.org` | MQTT broker hostname or IP address |
| `GREENHOUSE_MQTT_PORT` | `1883` | MQTT broker port |
| `GREENHOUSE_MQTT_DATA_TOPIC` | `acity_greenhouse/paakwasi/data` | MQTT topic for the JSON data packet |
| `GREENHOUSE_MQTT_PUBLISH_INTERVAL` | `1.0` | Seconds between MQTT data publishes |
| `GREENHOUSE_SERIAL_PORT` | `/dev/ttyUSB0` | Serial port for Arduino |
| `GREENHOUSE_SERIAL_BAUDRATE` | `115200` | Serial baud rate |
| `GREENHOUSE_RUNTIME_DIR` | One directory above the repository root | Base directory for all runtime output |
| `GREENHOUSE_LOG_DIR` | `<RUNTIME_DIR>/logs` | Directory for log files |
| `GREENHOUSE_LIVE_DIR` | `<RUNTIME_DIR>/live` | Directory for live CSV data files |
| `GREENHOUSE_WEEKLY_DIR` | `<RUNTIME_DIR>/weekly` | Directory for weekly CSV archives |
| `GREENHOUSE_IMAGE_DIR` | `<RUNTIME_DIR>/image` | Directory for captured still images |
| `GREENHOUSE_HTTP_UPLOAD_DIR` | `<IMAGE_DIR>/posted` | Directory for images received via HTTP upload |
| `GREENHOUSE_HTTP_ENABLED` | `1` | Enable (`1`) or disable (`0`) the HTTP image server |
| `GREENHOUSE_HTTP_HOST` | `0.0.0.0` | Bind address for the HTTP server |
| `GREENHOUSE_HTTP_PORT` | `8000` | Port for the HTTP image server |
| `GREENHOUSE_HTTP_PUBLIC_HOST` | Auto-detected LAN IP | Hostname/IP used in public-facing URLs |
| `GREENHOUSE_HTTP_STREAM_FPS` | `6.0` | Target frame rate for the MJPEG live stream |
| `GREENHOUSE_HTTP_STREAM_WIDTH` | `640` | Live stream frame width (pixels) |
| `GREENHOUSE_HTTP_STREAM_HEIGHT` | `480` | Live stream frame height (pixels) |
| `GREENHOUSE_CAPTURE_HOUR` | `21` | Hour (0–23) for daily still capture |
| `GREENHOUSE_CAPTURE_MINUTE` | `0` | Minute (0–59) for daily still capture |
| `GREENHOUSE_POST_IMAGE_URL` | `http://127.0.0.1:8000/upload` | URL to POST captured images to |
| `GREENHOUSE_POST_TIMEOUT` | `5.0` | Timeout in seconds for image POST requests |
| `GREENHOUSE_IMAGE_BASE_URL` | `http://<public_host>:8000/images` | Base URL for serving stored images |
| `GREENHOUSE_STREAM_URL` | `http://<public_host>:8000/stream` | Public URL for the MJPEG live stream |
| `GREENHOUSE_LATEST_IMAGE_URL` | `http://<public_host>:8000/latest` | Public URL for the latest-image endpoint (used in MQTT packet) |
| `GREENHOUSE_PUBLIC_BASE_URL` | _(empty)_ | Explicit public base URL; overrides auto-detected host for all generated URLs |
| `GREENHOUSE_TAILSCALE_FUNNEL_URL` | _(empty)_ | Tailscale Funnel URL; used as the public base URL when set |
| `GREENHOUSE_TAILSCALE_HOST` | _(empty)_ | Tailscale host; used for public base URL when Funnel URL is not set |
| `GREENHOUSE_TAILSCALE_SCHEME` | `http` | URL scheme used with `GREENHOUSE_TAILSCALE_HOST` (`http` or `https`) |
| `GREENHOUSE_SETPOINT_TEMPERATURE` | `25.0` | Fuzzy controller temperature setpoint (°C) |
| `GREENHOUSE_SETPOINT_HUMIDITY` | `85.0` | Fuzzy controller humidity setpoint (%) |
| `GREENHOUSE_SETPOINT_CO2` | `800.0` | Fuzzy controller CO₂ setpoint (ppm) |
| `GREENHOUSE_SETPOINT_LIGHT` | `150.0` | Fuzzy controller light intensity setpoint (lux) |
| `GREENHOUSE_SETPOINT_MOISTURE` | `65.0` | Fuzzy controller substrate moisture setpoint (%) |
| `GREENHOUSE_ACTUATOR_QUIET` | `0` | Suppress info-level logging in actuator standalone test mode (`1` = quiet) |
| `GREENHOUSE_LOOP_DELAY` | `0.1` | Main loop delay in seconds |

**Example – run on Raspberry Pi:**
```bash
export GREENHOUSE_MQTT_BROKER=test.mosquitto.org
export GREENHOUSE_SERIAL_PORT=/dev/ttyUSB0
cd src
python main.py
```

**Example – run with a local broker and custom HTTP port:**
```bash
export GREENHOUSE_MQTT_BROKER=localhost
export GREENHOUSE_HTTP_PORT=9000
export GREENHOUSE_SERIAL_PORT=/dev/ttyUSB0
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
- GPIO actuator control via gpiozero
- CSV data logging (live files + weekly rotation)
- Application logging
- HTTP image server (default port 8000)
- Daily still image capture at 21:00 (configurable)
- MJPEG live camera stream

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

**Test Actuator Driver:**
```bash
cd src/actuators
python actuators.py
```

### Data Collection

The system automatically logs data to CSV files under the live directory:
- `live/greenhouse_controlled.csv`: Sensor data from controlled section
- `live/greenhouse_control.csv`: Sensor data from control section
- `live/training_data.csv`: Complete control cycles (sensors + PWM outputs)

Files are archived weekly to `weekly/<YYYY-WW>/` and reset so live files remain small.

Daily still images are saved to `<GREENHOUSE_IMAGE_DIR>/` and served at:
- `http://<host>:<port>/images/<filename>` – individual image by name
- `http://<host>:<port>/latest` – most recently captured image

These files can be used for:
- Machine learning model training
- Performance analysis
- Environmental condition studies
- Comparative analysis of control effectiveness
- Visual growth tracking over time

## MQTT Data Packet

The system publishes a single JSON packet to the configured topic at each publish interval.

**Topic:** `acity_greenhouse/paakwasi/data` (configurable via `GREENHOUSE_MQTT_DATA_TOPIC`)

**Payload example:**
```json
{
  "timestamp": "2026-03-28 12:30:45.123",
  "status": "ONLINE",
  "controlled": {
    "temperature": 25.5,
    "humidity": 85.2,
    "co2": 750.0,
    "light": 145.0,
    "moisture": 67.5
  },
  "control": {
    "temperature": 26.8,
    "humidity": 78.3,
    "co2": 820.0,
    "light": 140.0,
    "moisture": 62.0
  },
  "latest_image": "http://<host>:8000/images/growth_2026-03-28_21-00-00.jpg",
  "stream": "http://<host>:8000/stream"
}
```

## System Status

✅ **Completed:**
- Fuzzy logic controller design (MATLAB)
- Python implementation with scikit-fuzzy
- Serial communication with Arduino
- MQTT cloud integration (single JSON packet per interval)
- CSV data logging with weekly rotation
- Comprehensive application logging
- Dual-section monitoring
- Automatic reconnection handling
- Training data generation for ML
- Daily still image capture (Raspberry Pi Camera)
- MJPEG live camera stream
- HTTP image server with viewer, stream, upload, and health endpoints
- GPIO actuator control via gpiozero (BCM pin numbering)
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
