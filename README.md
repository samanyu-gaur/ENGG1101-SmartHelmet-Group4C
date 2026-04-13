# ENGG1101 Smart Helmet v2.2 (Hardware Resilience Fix)

This version focuses on sensor reliability and error recovery, specifically addressing "stuck" I2C sensors and Raspberry Pi 5 hardware interaction.

## 🛠 Critical Fixes (v2.2)

-   **BH1750 Reset Sequence:** During initialization, the code now sends `0x01` (Power On), `0x07` (Hard Reset), and `0x10` (Continuous High-Res Mode) with stabilization delays to fix unresponsive light readings.
-   **I2C Error Recovery:** I2C reads are wrapped in `try-except` blocks. If a sensor fails to respond, the system attempts to re-initialize the I2C bus and the sensor registers automatically without crashing.
-   **Touch Sensor Debugging:** The TTP223 state is explicitly mapped and printed as a raw digital value (`0` or `1`) in the main loop to verify hardware connection.
-   **Architecture:** Fully utilizes `gpiozero` for `Button`, `LED`, and `Buzzer` components for Pi 5 compatibility.

## 🚀 Key Features

-   **Fall Detection:** Resultant acceleration calculation ($a_{\text{total}} = \sqrt{a_x^2 + a_y^2 + a_z^2}$) with a 3-second stationary check.
-   **Touch-to-Reset:** Any active alarm (Fall, SOS, or Removal) can be instantly dismissed by tapping the touch sensor.
-   **Manual SOS:** A 3-second hold on the touch sensor triggers a high-frequency emergency alert.
-   **Robust Monitoring:** 50Hz control loop with detailed `[DEBUG]` output for all sensor values.

## ⚙️ Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the System:**
    ```bash
    python main.py
    ```

## 📂 Project Structure

-   `main.py`: Unified, resilient implementation.
-   `requirements.txt`: Dependencies (`smbus2`, `gpiozero`, `numpy`).
