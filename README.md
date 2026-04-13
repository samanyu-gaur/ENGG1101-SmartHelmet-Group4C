# ENGG1101 Smart Helmet v2.6 (Sensor Freshness Priority)

This version prioritizes sensor data accuracy and freshness, specifically targeting the BH1750 (0x23) stagnation issue on the Raspberry Pi 5 with an aggressive re-initialization strategy.

## 🛠 Sensor Reliability (v2.6)

-   **High-Resolution Mode 2:** Switched BH1750 to opcode `0x11`, providing 0.5 lux precision and improved hardware stability.
-   **Extended Integration Delay:** The `get_lux()` function now includes a mandatory `time.sleep(0.2)` after triggering a measurement, ensuring the sensor's internal register has fully refreshed (~180ms requirement).
-   **Stagnation Auto-Recovery:** The system monitors Lux readings for stagnation. If the value remains identical for **20 consecutive frames**, a `re_init_bh1750()` sequence is triggered to reset the sensor registers.
-   **Bus Persistence:** If sensor stagnation persists after re-initialization, the system prints `[I2C HANG]` and attempts a full software-level I2C bus reset.

## 🚀 Key Features

-   **Priority Logic:** Loop timing is dictated by sensor integration requirements to ensure every Lux value is fresh and accurate.
-   **Universal Touch Reset:** Single tap to clear Fall, SOS, or Removal alarms.
-   **Fall Detection:** Verified impact and immobility monitoring.
-   **Live Stagnation Debugging:** The console shows the stagnation counter (`S`) to monitor sensor health in real-time.

## ⚙️ Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the System:**
    ```bash
    python main.py
    ```
