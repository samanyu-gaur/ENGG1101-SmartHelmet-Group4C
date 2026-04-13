# ENGG1101 Smart Helmet v2.3 (BH1750 Stagnation Fix)

This version introduces specialized handling for the BH1750 light sensor to prevent stagnant readings, a common issue where the sensor stops updating its data register.

## 🛠 BH1750 Stagnation Fixes (v2.3)

-   **Refined Initialization:** Sends an explicit sequence of `0x01` (Power On), `0x07` (Data Reset), and `0x10` (Continuous High-Res Mode) with stabilization delays.
-   **Data Acquisition Delay:** Ensures a minimum stabilization period (~200ms) after initialization to allow the sensor to complete its first integration cycle (~120ms).
-   **Auto-Wakeup Logic:** The system tracks the number of consecutive identical Lux readings. If the value remains stagnant for more than 10 iterations while the IMU detects movement, the system automatically re-sends the `0x10` (Continuous Mode) command to "wake up" the sensor.
-   **Movement-Aware Logic:** Stagnation detection is cross-referenced with MPU6050 accelerometer data to ensure the sensor isn't just in a naturally stable lighting environment.

## 🚀 Key Features

-   **Robust Fall Detection:** 3-second stationary check using `numpy` variance analysis.
-   **Touch Interaction:** Tap to reset alarms; hold for 3 seconds for Manual SOS.
-   **Real-time Debugging:** Live console output for Lux, stagnation count (`S`), G-force, and Touch state.

## ⚙️ Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the System:**
    ```bash
    python main.py
    ```
