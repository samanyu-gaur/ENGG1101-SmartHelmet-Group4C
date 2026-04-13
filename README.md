# ENGG1101 Smart Helmet v2.0 - Raspberry Pi 5

A professional embedded system implementation for a safety helmet featuring fall detection, removal monitoring, and manual SOS signaling.

## 🚀 Key Features

- **Multi-Sensor Integration:** Real-time processing of IMU (MPU6050) and Light (BH1750) data.
- **Advanced Fall Detection:** Detects free-fall and impact phases followed by a stationary/unconsciousness check using `numpy` variance analysis.
- **Interactive Reset:** A TTP223 touch sensor allows workers to dismiss false-positive fall alarms with a single tap.
- **Manual SOS:** Holding the touch sensor for >3 seconds triggers a high-frequency SOS alarm.
- **Helmet Removal Alert:** Triggers if the helmet is removed (Lux > 20) for more than 2 seconds.

## 🛠 Hardware Configuration

- **Controller:** Raspberry Pi 5
- **Light Sensor (GY-302/BH1750):** I2C Address `0x23`
- **IMU (MPU6050):** I2C Address `0x68`
- **Touch Sensor (TTP223):** BCM Pin 24 (Input)
- **Indicators:**
  - Buzzer: BCM Pin 18
  - LED: BCM Pin 27

## 🧠 Core Logic (v2.0)

### Fall Detection & Acknowledgment
The system utilizes the resultant acceleration $a_{\text{total}} = \sqrt{a_x^2 + a_y^2 + a_z^2}$ to identify potential falls. If a fall is detected and the worker remains stationary, the alarm activates. The **"I'm Okay" Reset** logic enables the worker to cancel the alarm via the touch sensor, addressing the critical engineering challenge of false positives.

### Manual SOS
Integrated as a safety redundancy, the **Manual SOS** feature allows a worker to call for help even without a fall event by holding the touch sensor for 3 seconds.

## ⚙️ Setup

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Run the System:**
   ```bash
   python main.py
   ```

## 📂 Repository Structure

- `main.py`: Unified single-file implementation for easy deployment.
- `requirements.txt`: Python package requirements (smbus2, RPi.GPIO, numpy).
