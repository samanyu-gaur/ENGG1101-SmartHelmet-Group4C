# ENGG1101 Smart Helmet v2.1 (Pi 5 Optimized)

This version of the Smart Helmet system is specifically optimized for the Raspberry Pi 5 architecture, utilizing `gpiozero` for more robust hardware interaction and refined sensor initialization.

## 🛠 Hardware Fixes & Improvements

-   **Architecture:** Migrated from `RPi.GPIO` to `gpiozero` to avoid SOC-related instability on the Pi 5.
-   **BH1750 (Light Sensor):** Explicitly initialized with opcode `0x10` (Continuous High-Res Mode) to ensure real-time data updates.
-   **TTP223 (Touch Sensor):** Configured as a `gpiozero.Button` with `pull_up=False` to handle the active-high signal with an internal pull-down resistor.
-   **Alarm Logic:** Integrated event-driven callbacks for the "I'm Okay" reset and non-blocking pattern generation for SOS and Removal alarms.

## 🚀 Key Features

-   **Fall Detection:** Uses `numpy` for precise variance analysis during the stationary check.
-   **Manual SOS:** Hold the touch sensor for 3 seconds to trigger a high-frequency SOS alert.
-   **Event-Driven Reset:** Instantly dismiss false-positive fall alarms with a single tap.
-   **Real-time Monitoring:** 50Hz control loop with live debugging output for Lux, G-force, and Touch state.

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

-   `main.py`: Unified, optimized implementation.
-   `requirements.txt`: Updated dependencies (`smbus2`, `gpiozero`, `numpy`).
