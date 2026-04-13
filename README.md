# ENGG1101 Smart Helmet v2.4 (High-Speed Lux Fix)

This update resolves stagnant BH1750 readings by implementing a precise initialization sequence and high-speed data acquisition logic.

## 🛠 BH1750 Optimization (v2.4)

-   **Initialization Fix:** Explicitly sends `0x01` (Power On) followed by a **180ms delay**, ensuring the sensor completes its first internal measurement before further commands.
-   **Register Reset:** Sends the `0x07` (Data Reset) opcode to clear any stale values from the sensor's register.
-   **Continuous High-Res Mode:** Forced activation of high-speed continuous measurement via the `0x10` command.
-   **Bit-Shifted 2-Byte Read:** Re-engineered the `get_lux` function to read two bytes, perform a high-byte shift (`data[0] << 8 | data[1]`), and apply the conversion constant (`/ 1.2`) for accurate real-time values.

## 🚀 Key Features

-   **Dynamic Lux Monitoring:** Real-time light level updates in the debug log, critical for helmet removal detection.
-   **Fall Detection:** Free-fall and impact sensing with immobility verification.
-   **SOS Signaling:** Emergency alert triggered by a 3-second hold on the touch sensor.
-   **Touch-to-Reset:** Rapid alarm cancellation via tap interaction.

## ⚙️ Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the System:**
    ```bash
    python main.py
    ```
