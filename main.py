import time
import threading
import json
import math
import os
from datetime import datetime
from flask import Flask, render_template_string, jsonify
from gpiozero import TonalBuzzer, LED, Button
from gpiozero.tones import Tone
from smbus2 import SMBus

# --- Configuration ---
I2C_BUS = 1
MPU_ADDR = 0x68
BH_ADDR = 0x23
BUZZER_PIN = 12
RED_LED_PIN = 27
GREEN_LED_PIN = 17
TOUCH_PIN = 24

LUX_THRESHOLD = 50
REMOVAL_DELAY = 5.0
FALL_THRESHOLD = 3.0

# --- Global State & Locks ---
sensor_data = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "status": "Initializing...",
    "timestamp": ""
}
data_lock = threading.Lock()
i2c_lock = threading.Lock() # REQUIREMENT: Prevent I2C collisions

# --- Hardware Setup ---
bus = None
def setup_sensors():
    global bus
    with i2c_lock:
        try:
            if bus is not None:
                bus.close()
            bus = SMBus(I2C_BUS)
            bus.write_byte_data(MPU_ADDR, 0x6B, 0x00) # Wake MPU
            bus.write_byte(BH_ADDR, 0x01) # Power On BH
            time.sleep(0.1)
            bus.write_byte(BH_ADDR, 0x10) # Continuous High Res
            print("[SUCCESS] Sensors Initialized")
            return True
        except Exception as e:
            print(f"[ERROR] Setup failed: {e}")
            return False

buzzer = TonalBuzzer(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

# --- Logic Functions ---
def safe_get_lux():
    with i2c_lock:
        data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
        return ((data[0] << 8) | data[1]) / 1.2

def safe_get_accel():
    with i2c_lock:
        data = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 6)
        def read_word(h, l):
            val = (h << 8) | l
            return val - 65536 if val >= 32768 else val
        ax = read_word(data[0], data[1]) / 16384.0
        ay = read_word(data[2], data[3]) / 16384.0
        az = read_word(data[4], data[5]) / 16384.0
        return math.sqrt(ax**2 + ay**2 + az**2)

# --- Background Thread (Requirement: Crash-Proof) ---
def sensor_loop():
    global sensor_data
    warning_start = None
    failure_count = 0
    setup_sensors()
    
    while True:
        try: # REQUIREMENT: Robust Error Handling
            lux = safe_get_lux()
            accel = safe_get_accel()
            touch = touch_sensor.is_pressed
            failure_count = 0 # Reset failures on success
            
            with data_lock:
                sensor_data["lux"] = round(lux, 2)
                sensor_data["accel"] = round(accel, 2)
                sensor_data["timestamp"] = datetime.now().strftime("%H:%M:%S")

                # 1. Reset Logic
                if touch:
                    sensor_data["alarm"] = False
                    sensor_data["warning"] = False
                    sensor_data["status"] = "Safe"
                    warning_start = None

                # 2. Safety Logic (The 5-Second Rule)
                if not sensor_data["alarm"]:
                    if accel > FALL_THRESHOLD:
                        sensor_data["alarm"] = True
                        sensor_data["status"] = "Fall Detected"
                    elif lux > LUX_THRESHOLD:
                        if not sensor_data["warning"]:
                            sensor_data["warning"] = True
                            sensor_data["status"] = "Removal Warning"
                            warning_start = time.time()
                        elif time.time() - warning_start > REMOVAL_DELAY:
                            if not touch:
                                sensor_data["alarm"] = True
                                sensor_data["status"] = "Helmet Removed"
                    else:
                        sensor_data["warning"] = False
                        if not sensor_data["alarm"]: sensor_data["status"] = "Safe"
                        warning_start = None

            # 3. Hardware Feedback
            if sensor_data["alarm"]:
                led_green.off()
                led_red.on()
                buzzer.play(Tone(1000))
            elif sensor_data["warning"]:
                led_green.off()
                if int(time.time() * 4) % 2: led_red.on()
                else: led_red.off()
                buzzer.stop()
            else:
                led_green.on()
                led_red.off()
                buzzer.stop()

            time.sleep(0.05)

        except Exception as e:
            failure_count += 1
            print(f"[CRITICAL] Sensor loop error ({failure_count}): {e}")
            
            # REQUIREMENT: Smart Re-initialization
            if failure_count >= 3:
                print("[RECOVERY] 3 failures reached. Re-initializing I2C...")
                setup_sensors()
                failure_count = 0
            
            time.sleep(1) # REQUIREMENT: Wait before retry

# --- Web Server ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Helmet - Crash-Proof Demo</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #0f0f0f; color: #f0f0f0; font-family: 'Inter', sans-serif; }
        .card { background-color: #1a1a1a; border: 1px solid #333; border-radius: 12px; box-shadow: 0 4px 30px rgba(0,0,0,0.7); }
        .status-safe { color: #00ff88; text-shadow: 0 0 10px rgba(0,255,136,0.3); }
        .status-warning { color: #ffdd00; text-shadow: 0 0 10px rgba(255,221,0,0.3); }
        .status-alarm { color: #ff3366; text-shadow: 0 0 10px rgba(255,51,102,0.3); }
        .display-1 { font-weight: 800; letter-spacing: -2px; }
        .metric-label { color: #888; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 1px; }
    </style>
</head>
<body>
    <div class="container py-5">
        <div class="row mb-5">
            <div class="col-12 text-center">
                <h1 class="display-5 mb-1">Helmet Protection System</h1>
                <p class="text-muted">High-Resiliency Sensor Monitoring | Raspberry Pi 5</p>
            </div>
        </div>

        <div class="row g-4">
            <div class="col-lg-6">
                <div class="card p-4 h-100">
                    <div class="metric-label mb-2">Live State</div>
                    <div id="status-box" class="display-1 text-center my-4 status-safe">SAFE</div>
                    <div class="row text-center mt-4">
                        <div class="col-6 border-end border-secondary">
                            <div class="metric-label">Ambient Light</div>
                            <p id="lux-val" class="h2 mb-0">0.0 Lux</p>
                        </div>
                        <div class="col-6">
                            <div class="metric-label">Force Load</div>
                            <p id="accel-val" class="h2 mb-0">1.0 g</p>
                        </div>
                    </div>
                </div>
            </div>

            <div class="col-lg-6">
                <div class="card p-4 h-100">
                    <div class="metric-label mb-3">Telemetry History</div>
                    <canvas id="telemetryChart"></canvas>
                </div>
            </div>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('telemetryChart').getContext('2d');
        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'G-Force',
                    borderColor: '#ff3366',
                    borderWidth: 2,
                    data: [],
                    fill: false,
                    pointRadius: 0,
                    tension: 0.3
                }, {
                    label: 'Lux/100',
                    borderColor: '#00ff88',
                    borderWidth: 2,
                    data: [],
                    fill: false,
                    pointRadius: 0,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { display: false },
                    y: { 
                        grid: { color: '#222' },
                        ticks: { color: '#666' },
                        beginAtZero: true
                    }
                },
                plugins: { legend: { display: false } }
            }
        });

        async function updateData() {
            try {
                const response = await fetch('/data');
                const data = await response.json();
                
                if (!data || Object.keys(data).length === 0) return;

                const statusBox = document.getElementById('status-box');
                statusBox.innerText = data.status.toUpperCase();
                statusBox.className = 'display-1 text-center my-4 ' + 
                    (data.alarm ? 'status-alarm' : (data.warning ? 'status-warning' : 'status-safe'));
                
                document.getElementById('lux-val').innerText = data.lux + ' Lux';
                document.getElementById('accel-val').innerText = data.accel + ' g';

                if (chart.data.labels.length > 30) {
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.shift();
                    chart.data.datasets[1].data.shift();
                }
                chart.data.labels.push(data.timestamp);
                chart.data.datasets[0].data.push(data.accel);
                chart.data.datasets[1].data.push(data.lux / 100);
                chart.update('none');
            } catch (e) { console.error("UI Fetch Error:", e); }
        }

        setInterval(updateData, 500);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data():
    with data_lock:
        # REQUIREMENT: Handle temporarily empty state
        if not sensor_data.get("timestamp"):
            return jsonify({"status": "Connecting...", "lux": 0, "accel": 1, "alarm": False, "warning": False})
        return jsonify(sensor_data)

if __name__ == "__main__":
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
