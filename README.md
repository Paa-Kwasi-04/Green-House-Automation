# Smart Mushroom Greenhouse Control System

This project implements an IoT-based smart mushroom greenhouse using a hybrid
Arduino–Raspberry Pi architecture and fuzzy logic control.

## System Overview
- Arduino Uno: sensor data acquisition
- Raspberry Pi: fuzzy logic control, automation, logging, and interface
- Control method: Mamdani fuzzy logic controllers
- Actuators: fans, humidifier, water pump, LED lighting

## Sensors
- Temperature
- Relative Humidity
- CO₂ concentration
- Light intensity
- Substrate moisture

## Repository Structure
See `/src` for system code and `/Control_Algorithms` for fuzzy logic design.

## Status
- Fuzzy logic designed in MATLAB
- Raspberry Pi control code in development
