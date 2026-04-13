# ENGG1101 Smart Helmet v2.5 (Robust Sensor Logic)

This version focuses on maximum reliability for the BH1750 light sensor and refined "Hat Off" detection logic, optimized for industrial safety standards.

## 🛠 Robust Sensor Logic (v2.5)

-   **Maximum Reliability Initialization:** Explicit sequence of `0x01` (Power On), `0x07` (Data Reset), and `0x10` (Continuous High-Res Mode) with a mandatory **200ms stabilization delay** before the first read.
-   **Dynamic Fallback:** The `get_lux()` function now uses a `try-except` block to return the **last known good value** in the event of an I2C read failure, preventing script crashes.
-   **Refined "Hat Off" Detection:**
    -   **Threshold:** Increased to `30 Lux` for better ambient light discrimination.
    -   **Continuous Validation:** Requires `2 continuous seconds` of high light levels to trigger the `Removal_Alarm`, eliminating false positives from flickering light.
-   **Touch Integration:** The TTP223 touch sensor (BCM 24) acts as a universal reset, silencing the buzzer and resetting the removal timer on a single tap.

## 🚀 Key Features

-   **Clear Safety Logging:** Console outputs `[SAFE]` during normal operation and `[WARNING: HELMET REMOVED]` when an alarm is active.
-   **Fall Detection:** Free-fall and impact monitoring with stationary verification.
-   **Manual SOS:** Emergency alert via a 3-second hold on the touch sensor.

## ⚙️ Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the System:**
    ```bash
    python main.py
    ```
