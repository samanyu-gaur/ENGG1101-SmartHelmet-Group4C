# ENGG1101 Smart Helmet v2.7 (RGB & Passive Buzzer)

This version introduces advanced audible and visual feedback using a passive buzzer and an HW-479 RGB LED, providing clear status indication for industrial safety.

## 🛠 Hardware Updates (v2.7)

-   **Passive Buzzer (BCM 12):** Utilizes `gpiozero.TonalBuzzer` (PWM) to generate frequency-specific tones, replacing simple "clicks" with audible sirens and chirps.
-   **RGB LED (HW-479):**
    -   **Green (BCM 17):** Solid ON during `NORMAL` state.
    -   **Red (BCM 27):** Used for `WARNING` (blinking) and `CRITICAL` (solid) states.
-   **Touch Sensor (BCM 24):** Acts as the primary reset button to silence alarms and return the system to the Green/Safe state.

## 🧠 Operational States

-   **NORMAL:** Lux < 50, No Fall detected.
    -   *Feedback:* Green LED ON, Buzzer OFF.
-   **WARNING (Helmet Removed):** Lux > 50 for 2 seconds.
    -   *Feedback:* Red LED Blinking, Slow Chirp (440Hz).
-   **CRITICAL (Fall Detected):** IMU detects free-fall followed by impact and immobility.
    -   *Feedback:* Red LED Solid ON, Fast Siren (880Hz - 1000Hz).

## ⚙️ Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run the System:**
    ```bash
    python main.py
    ```
