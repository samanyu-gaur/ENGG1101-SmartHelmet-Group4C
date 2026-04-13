# ENGG1101 Smart Helmet - Raspberry Pi 5

A production-ready implementation of a safety "Smart Helmet" using a Raspberry Pi 5, MPU6050 (IMU), and BH1750 (Light Sensor).

## 🚀 Overview

This project aims to enhance worker safety by monitoring helmet usage and detecting potential falls. It uses real-time sensor data to trigger alarms in case of helmet removal or serious impacts followed by immobility.

## 🛠 Hardware Configuration

- **Controller:** Raspberry Pi 5
- **Light Sensor:** BH1750 (I2C Address: `0x23`)
- **IMU:** MPU6050 (I2C Address: `0x68`)
- **Indicators:**
  - Buzzer: BCM Pin 18
  - LED: BCM Pin 27

## 🧠 Core Logic

### 1. Fall Detection Algorithm
The system calculates the resultant acceleration ($a_{\text{total}}$) using the formula:

$$a_{\text{total}} = \sqrt{a_x^2 + a_y^2 + a_z^2}$$

A **Fall Alarm** is triggered when:
1. **Free-fall phase:** $a_{\text{total}} < 0.5g$
2. **Impact phase:** $a_{\text{total}} > 3.0g$
3. **Stationary check:** After the impact, if movement variance stays below a threshold ($< 0.05$) for 3 seconds, the alarm sustains to signal a potentially unconscious worker.

### 2. Helmet-Removal Logic
The BH1750 sensor monitors light levels inside the helmet.
- **Threshold:** Lux > 20
- **Delay:** 2 seconds
If the Lux value remains above the threshold for more than 2 seconds, the **Removal Alarm** is triggered.

## ⚙️ Setup

1. **Enable I2C:**
   Run `sudo raspi-config`, go to `Interface Options`, and enable `I2C`.
2. **Permissions:**
   Add your user to the I2C group:
   ```bash
   sudo usermod -aG i2c $USER
   ```
3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Run the System:**
   ```bash
   python main.py
   ```

## 📂 Project Structure

- `main.py`: Entry point for the application.
- `smart_helmet.py`: Core logic and sensor interfacing.
- `requirements.txt`: Python dependencies.
