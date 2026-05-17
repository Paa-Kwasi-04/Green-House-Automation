# Smart Mushroom Greenhouse Control System

An IoT-based smart mushroom greenhouse automation system using a hybrid Arduino-Raspberry Pi architecture with fuzzy logic control. This project implements real-time environmental monitoring, automated control, live camera streaming, and comparative data collection between controlled and uncontrolled greenhouse sections.

## System Overview

### Hardware Architecture
- **Arduino Uno**: Sensor data acquisition from both greenhouse sections
- **Raspberry Pi**: Fuzzy logic control, automation, HTTP telemetry publishing, data logging, and camera streaming
- **Control Method**: Mamdani fuzzy logic controllers (scikit-fuzzy)
- **Actuators** (BCM pin numbering):
  - Fan 1 – Intake → GPIO 22 (PWM 0-100% via gpiozero)
  - Fan 2 – Intake → GPIO 24 (PWM 0-100% via gpiozero)
  - Fan 3 – Exhaust → GPIO 17 (PWM 0-100% via gpiozero; derived from intake using model: 1.25× ratio + 20 PWM boost, clamped 80-255)
  - Peristaltic Pump → GPIO 4 (PWM 0-100% via gpiozero, time-gated pulse mode)
  - LED Grow Lights → GPIO 18 (NeoPixel strip: 120 LEDs, white output, via adafruit-circuitpython-neopixel)
  - Humidifier → GPIO 10 (PWM 0-100% via gpiozero)

### Monitored Parameters
- **Temperature** (°C)
- **Relative Humidity** (%)
- **CO₂ Concentration** (ppm) – monitored and logged; not used as fuzzy controller input
- **Light Intensity** (lux)
- **Substrate Moisture** (%)

### Dual-Section Design
The system monitors two greenhouse sections in parallel:
- **Controlled Section**: Automated fuzzy logic control with actuators
- **Control Section**: Natural conditions for comparison (no automated control)

This design enables data-driven comparison of automated vs. natural growing conditions.

## Features

### 1. Real-Time Fuzzy Logic Control
- **Temperature & Humidity Controller**: Fan speed adjustment (intake fans + exhaust fan derived from intake)
- **Temperature & Humidity Controller**: Humidifier output regulation
- **Light Controller**: NeoPixel LED brightness adjustment (optionally overridden by light schedule)
- **Substrate Moisture Controller**: Pump activation control (time-gated pulse mode)
- Default Setpoints: T=25.5°C, H=79%, Light=110 lux, Moisture=85%
- CO₂ is monitored and logged but not used as a fuzzy controller input

### 2. Communication Systems
- **Serial Communication**: Arduino → Raspberry Pi (115200 baud)
  - Automatic reconnection on disconnect
  - Robust data parsing with validation
  - Expected format: `Controlled|T,H,CO2,L,M;Control|T,H,CO2,L,M`
- **HTTP Telemetry**: Real-time data as a single JSON packet POSTed to the local HTTP server
  - POSTed to `/telemetry` endpoint (configurable via `GREENHOUSE_TELEMETRY_URL`)
  - Packet fields: `timestamp`, `status`, `controlled`, `control`, `latest_image`, `stream`
  - Live dashboard available at `/telemetry/view`

### 3. Camera & Visual Monitoring
- **Raspberry Pi Camera**: Daily still capture and live MJPEG stream using `picamera2`
  - Captures one high-resolution image per day at the configured time (default 21:00)
  - LED pre-lighting applied before capture (default 0.8s warmup at 220 PWM)
  - Images saved under `<GREENHOUSE_IMAGE_DIR>/` and served via the built-in HTTP server; POSTs to configured URL with fallback to local storage
  - Live MJPEG stream accessible at `http://<host>:<port>/stream` (default 6 fps, 640×480)

### 4. HTTP Server
- Built-in HTTP server for camera image access, live streaming, and telemetry (default port 8000)
- Endpoints:
  - `GET /` – redirects to `/stream`
  - `GET /stream` – MJPEG live stream
  - `GET /latest` – latest captured image file
  - `GET /images/<name>` – access a specific stored image by filename
  - `POST /upload` – receive an image (raw bytes, `X-Filename` header for name)
  - `GET /telemetry` – latest telemetry JSON packet
  - `POST /telemetry` – store a telemetry JSON packet
  - `GET /telemetry/view` – live telemetry dashboard (auto-refreshes every second)
  - `GET /health` – server health check

### 5. Data Logging & Storage
- **CSV Data Storage**: Live files updated continuously, archived weekly
  - `live/greenhouse_controlled.csv`: Controlled section sensor data
  - `live/greenhouse_control.csv`: Control section sensor data
  - `live/training_data.csv`: Sensor inputs + fuzzy controller outputs
  - `weekly/<YYYY-WW>/`: Weekly archives of the above files
- **Application Logging**: Rotating log files with date grouping
  - File: `logs/greenhouse.log`
  - Rotation: 10 MB per file, max 5 files
  - Automatic date separators for readability
  - File log level configurable via `GREENHOUSE_FILE_LOG_LEVEL`

### 6. Pump Pulse Mode
- The pump is time-gated: it runs for a short configurable pulse rather than continuously
- A pulse is triggered at most once per configurable check interval (default 6 hours) when moisture is below the deadband
- Each pulse duration is independently configurable (default 5 seconds)
- Configurable via `GREENHOUSE_PUMP_CHECK_INTERVAL` and `GREENHOUSE_PUMP_PULSE_SECONDS`

### 7. Light Schedule (Optional Override)
- LED brightness can be controlled by a daily light schedule (independent of fuzzy control)
- Schedule-based control enabled by default; can be disabled to use fuzzy LED controller
- Configurable start hour, duration, and PWM level
- Useful for diurnal cycle simulation independent of thermal control

### 8. Robust Error Handling
- Automatic serial port reconnection
- HTTP telemetry post error throttling and recovery logging
- Comprehensive logging for debugging
- Input validation and error recovery
- Graceful shutdown handlers for SIGTERM and SIGINT signals

## Repository Structure

```
Green-House-Automation/
├── Control_Algorithms/          # MATLAB fuzzy logic design files
│   ├── Humidity_Controller.mlx              # Humidifier: temp + humidity error
│   ├── LED_controller.mlx                   # LED: light error
│   ├── Substrate_moisture_controller.mlx    # Pump: moisture error
│   └── Temperature_C02_Controller.mlx       # Original fan design (temp + CO₂);
│                                            # Python implementation uses temp-only
├── src/                         # Main application code
│   ├── main.py                  # Main control loop entry point
│   ├── actuators/               # Actuator control modules
│   │   ├── __init__.py          # Package export (ActuatorDriver)
│   │   ├── actuators.py         # gpiozero PWM driver + exhaust fan model (BCM pins)
│   │   └── Neopixel_driver.py   # NeoPixel LED driver via GPIO18
│   ├── communication/           # Communication modules
│   │   ├── __init__.py
│   │   ├── serial_comm.py       # Arduino serial communication
│   │   └── http_server.py       # HTTP server (images, stream, telemetry)
│   ├── control/                 # Control system modules
│   │   ├── __init__.py
│   │   └── fuzzy_controller.py  # Fuzzy logic controller (scikit-fuzzy)
│   ├── sensor/                  # Sensor modules
│   │   └── camera.py            # Raspberry Pi Camera (still capture + streaming)
│   └── storage/                 # Data logging modules
│       ├── __init__.py
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
- Root / sudo access required for NeoPixel GPIO18 hardware access (`/dev/mem`). When using a virtualenv, pass the interpreter explicitly: `sudo /path/to/venv/bin/python main.py`

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Dependencies
- `adafruit-blinka`: CircuitPython compatibility layer providing the `board` module
- `adafruit-circuitpython-neopixel`: NeoPixel LED strip driver (`neopixel` module)
- `gpiozero`: GPIO PWM control for Raspberry Pi actuators
- `picamera2`: Raspberry Pi Camera interface (still capture and live streaming)
- `pyserial`: Serial communication with Arduino
- `scikit-fuzzy`: Fuzzy logic control system
- `numpy`: Numerical computations

## Configuration

All runtime parameters are controlled via environment variables. The system falls back to sensible defaults when variables are not set.

| Environment Variable | Default | Description |
|---|---|---|
| `GREENHOUSE_SERIAL_PORT` | `/dev/ttyUSB0` | Serial port for Arduino |
| `GREENHOUSE_SERIAL_BAUDRATE` | `115200` | Serial baud rate |
| `GREENHOUSE_RUNTIME_DIR` | One directory above the repository root | Base directory for all runtime output |
| `GREENHOUSE_LOG_DIR` | `<RUNTIME_DIR>/logs` | Directory for log files |
| `GREENHOUSE_FILE_LOG_LEVEL` | `INFO` | Log level written to the rotating log file |
| `GREENHOUSE_LIVE_DIR` | `<RUNTIME_DIR>/live` | Directory for live CSV data files |
| `GREENHOUSE_WEEKLY_DIR` | `<RUNTIME_DIR>/weekly` | Directory for weekly CSV archives |
| `GREENHOUSE_IMAGE_DIR` | `<RUNTIME_DIR>/image` | Directory for captured still images |
| `GREENHOUSE_HTTP_UPLOAD_DIR` | `<IMAGE_DIR>/posted` | Directory for images received via HTTP upload |
| `GREENHOUSE_HTTP_ENABLED` | `1` | Enable (`1`) or disable (`0`) the HTTP server |
| `GREENHOUSE_HTTP_HOST` | `0.0.0.0` | Bind address for the HTTP server |
| `GREENHOUSE_HTTP_PORT` | `8000` | Port for the HTTP server |
| `GREENHOUSE_HTTP_PUBLIC_HOST` | Auto-detected LAN IP | Hostname/IP used in public-facing URLs |
| `GREENHOUSE_HTTP_STREAM_FPS` | `6.0` | Target frame rate for the MJPEG live stream |
| `GREENHOUSE_HTTP_STREAM_WIDTH` | `640` | Live stream frame width (pixels) |
| `GREENHOUSE_HTTP_STREAM_HEIGHT` | `480` | Live stream frame height (pixels) |
| `GREENHOUSE_TELEMETRY_PUBLISH_INTERVAL` | `1.0` | Seconds between telemetry data posts |
| `GREENHOUSE_TELEMETRY_POST_TIMEOUT` | `5.0` | Timeout in seconds for telemetry POST requests |
| `GREENHOUSE_TELEMETRY_URL` | `<public_base_url>/telemetry` | URL to POST telemetry JSON to |
| `GREENHOUSE_TELEMETRY_VIEW_URL` | `<public_base_url>/telemetry/view` | URL of the live telemetry dashboard |
| `GREENHOUSE_CAPTURE_HOUR` | `21` | Hour (0–23) for daily still capture |
| `GREENHOUSE_CAPTURE_MINUTE` | `0` | Minute (0–59) for daily still capture |
| `GREENHOUSE_PHOTO_LIGHT_PWM` | `220` | PWM level for LED pre-lighting before photo capture |
| `GREENHOUSE_POST_IMAGE_URL` | `http://127.0.0.1:8000/upload` | URL to POST captured images to |
| `GREENHOUSE_POST_TIMEOUT` | `5.0` | Timeout in seconds for image POST requests |
| `GREENHOUSE_IMAGE_BASE_URL` | `<public_base_url>/images` | Base URL for serving stored images |
| `GREENHOUSE_STREAM_URL` | `<public_base_url>/stream` | Public URL for the MJPEG live stream |
| `GREENHOUSE_LATEST_IMAGE_URL` | `<public_base_url>/latest` | Public URL for the latest-image endpoint |
| `GREENHOUSE_PUBLIC_BASE_URL` | _(empty)_ | Explicit public base URL; overrides auto-detected host for all generated URLs |
| `GREENHOUSE_TAILSCALE_FUNNEL_URL` | _(empty)_ | Tailscale Funnel URL; used as the public base URL when set |
| `GREENHOUSE_TAILSCALE_HOST` | _(empty)_ | Tailscale host; used for public base URL when Funnel URL is not set |
| `GREENHOUSE_TAILSCALE_SCHEME` | `http` | URL scheme used with `GREENHOUSE_TAILSCALE_HOST` (`http` or `https`) |
| `GREENHOUSE_PUMP_CHECK_INTERVAL` | `21600` | Seconds between pump activation checks (default: 6 hours) |
| `GREENHOUSE_PUMP_PULSE_SECONDS` | `5.0` | Duration in seconds of each pump pulse |
| `GREENHOUSE_EXHAUST_RATIO` | `0.15` | Exhaust fan PWM scale factor relative to intake |
| `GREENHOUSE_EXHAUST_START_BOOST_PWM` | `20` | Startup boost added to exhaust PWM to overcome static friction |
| `GREENHOUSE_EXHAUST_MIN_PWM` | `95` | Minimum PWM applied to exhaust fan when it is spinning |
| `GREENHOUSE_EXHAUST_MAX_PWM` | `255` | Maximum PWM cap for exhaust fan |
| `GREENHOUSE_NEOPIXEL_BRIGHTNESS` | `1.0` | Global NeoPixel brightness scaler (0.0–1.0) |
| `GREENHOUSE_NEOPIXEL_COUNT` | `120` | Number of LEDs on the NeoPixel strip |
| `GREENHOUSE_NEOPIXEL_LOG_TX` | `1` | Log NeoPixel transmissions (`1` = enabled) |
| `GREENHOUSE_LED_FUZZY_ENABLED` | `0` | Enable fuzzy LED control (`1` = on); light schedule takes precedence when enabled |
| `GREENHOUSE_LIGHT_SCHEDULE_ENABLED` | `1` | Enable light schedule override (`1` = on, default behavior) |
| `GREENHOUSE_LIGHT_SCHEDULE_START_HOUR` | `6` | Hour (0–23) to start daily light schedule |
| `GREENHOUSE_LIGHT_SCHEDULE_ON_HOURS` | `12` | Duration in hours for light schedule (e.g., 12 = 6AM-6PM) |
| `GREENHOUSE_LIGHT_SCHEDULE_PWM` | `220` | PWM level for light schedule when active |
| `GREENHOUSE_SETPOINT_TEMPERATURE` | `25.5` | Fuzzy controller temperature setpoint (°C) |
| `GREENHOUSE_SETPOINT_HUMIDITY` | `79.0` | Fuzzy controller humidity setpoint (%) |
| `GREENHOUSE_SETPOINT_LIGHT` | `110.0` | Fuzzy controller light intensity setpoint (lux) |
| `GREENHOUSE_SETPOINT_MOISTURE` | `85.0` | Fuzzy controller substrate moisture setpoint (%) |
| `GREENHOUSE_SETPOINT_MOISTURE_DEADBAND` | `5.0` | Moisture deadband; pump skipped when moisture ≥ (setpoint − deadband) |
| `GREENHOUSE_FUZZY_INPUT_SMOOTHING_ALPHA` | `0.35` | Exponential smoothing factor for fuzzy controller inputs (0.0–1.0) |
| `GREENHOUSE_FUZZY_OUTPUT_SLEW_RATE` | `30` | Maximum PWM change per control step (limits ramp-up/down rate) |
| `GREENHOUSE_ACTUATOR_QUIET` | `0` | Suppress info-level logging in actuator standalone test mode (`1` = quiet) |
| `GREENHOUSE_LOOP_DELAY` | `0.1` | Main loop delay in seconds |

**Example – run on Raspberry Pi:**
```bash
export GREENHOUSE_SERIAL_PORT=/dev/ttyUSB0
cd src
sudo python main.py
```

**Example – run with a custom HTTP port:**
```bash
export GREENHOUSE_HTTP_PORT=9000
export GREENHOUSE_SERIAL_PORT=/dev/ttyUSB0
cd src
sudo python main.py
```

## Usage

### Run the Complete System
```bash
cd src
sudo python main.py
```

This starts:
- Serial communication with Arduino
- Fuzzy logic control computation
- GPIO actuator control via gpiozero (fans, pump, humidifier)
- NeoPixel LED grow light control via GPIO18
- CSV data logging (live files + weekly rotation)
- Application logging
- HTTP server (default port 8000): stream, images, telemetry dashboard
- Daily still image capture at 21:00 (configurable)
- MJPEG live camera stream
- Periodic HTTP telemetry posting to `/telemetry` endpoint

### Run Individual Modules

**Test Serial Communication:**
```bash
cd src/communication
python serial_comm.py
```

**Test HTTP Server:**
```bash
cd src/communication
python http_server.py
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

**Test NeoPixel LED:**
```bash
cd src/actuators
sudo python Neopixel_driver.py
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

## HTTP Telemetry Packet

The system POSTs a single JSON packet to the configured telemetry URL at each publish interval and stores it on the local HTTP server at `/telemetry`.

**Retrieve latest telemetry:**
```
GET http://<host>:<port>/telemetry
```

**Live dashboard:**
```
GET http://<host>:<port>/telemetry/view
```

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

## Control Algorithms

The `Control_Algorithms/` directory contains the original MATLAB fuzzy logic design files used as the basis for the Python implementation:

| File | Controller | Inputs | Output |
|---|---|---|---|
| `Humidity_Controller.mlx` | Humidifier | Temperature error, Humidity error | Humidifier PWM |
| `LED_controller.mlx` | LED | Light error | LED PWM |
| `Substrate_moisture_controller.mlx` | Pump | Moisture error | Pump PWM |
| `Temperature_C02_Controller.mlx` | Fan | Temperature error (+ CO₂ in original design) | Fan PWM |

> **Note:** The Python fan controller (`_build_fan` in `fuzzy_controller.py`) uses temperature error only. CO₂ concentration is still read from the sensor and logged to CSV, but it is not fed into the fuzzy controller in the current implementation.

## System Status

✅ **Completed:**
- Fuzzy logic controller design (MATLAB)
- Python implementation with scikit-fuzzy
- Serial communication with Arduino
- HTTP telemetry (single JSON packet posted to local HTTP server)
- CSV data logging with weekly rotation
- Comprehensive application logging with configurable file log level
- Dual-section monitoring
- Automatic serial reconnection handling
- Training data generation for ML
- Daily still image capture (Raspberry Pi Camera)
- MJPEG live camera stream
- HTTP server with stream, images, upload, telemetry, and health endpoints
- Live telemetry dashboard at `/telemetry/view`
- GPIO actuator control via gpiozero (BCM pin numbering)
- NeoPixel LED grow light control via GPIO18
- Dual intake fan + auto-derived exhaust fan speed
- Pump pulse mode with configurable interval and pulse duration
- Environment variable based configuration

🚧 **Future Enhancements:**
- Web dashboard for real-time monitoring
- Machine learning model for predictive control
- Historical data visualization
- Alert system for out-of-range conditions
- Mobile app integration
- CO₂-based fan control integration

## License

This project is part of academic research on smart greenhouse automation systems.

## Contributors

Paa-Kwasi-04
