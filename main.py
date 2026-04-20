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

# --- Global State ---
sensor_data = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "status": "Safe",
    "timestamp": ""
}
data_lock = threading.Lock()

# --- Hardware Setup ---
try:
    bus = SMBus(I2C_BUS)
    bus.write_byte_data(MPU_ADDR, 0x6B, 0x00) # Wake MPU
    bus.write_byte(BH_ADDR, 0x01) # Power On BH
    time.sleep(0.1)
    bus.write_byte(BH_ADDR, 0x10) # Continuous High Res
except Exception as e:
    print(f"Hardware Init Error: {e}")

buzzer = TonalBuzzer(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

# --- Logic Functions ---
def get_lux():
    try:
        data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
        return ((data[0] << 8) | data[1]) / 1.2
    except: return 0.0

def get_accel():
    try:
        data = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 6)
        def read_word(h, l):
            val = (h << 8) | l
            return val - 65536 if val >= 32768 else val
        ax = read_word(data[0], data[1]) / 16384.0
        ay = read_word(data[2], data[3]) / 16384.0
        az = read_word(data[4], data[5]) / 16384.0
        return math.sqrt(ax**2 + ay**2 + az**2)
    except: return 1.0

def sensor_loop():
    global sensor_data
    warning_start = None
    
    while True:
        lux = get_lux()
        accel = get_accel()
        touch = touch_sensor.is_pressed
        
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
                        if not touch: # Trigger if not pressed by 5s
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

        time.sleep(0.05) # Prevent CPU Maxing

# --- Web Server ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Helmet Final Demo</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: 'Inter', sans-serif; }
        .card { background-color: #1e1e1e; border: none; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        .status-safe { color: #00e676; }
        .status-warning { color: #ffea00; }
        .status-alarm { color: #ff1744; }
        .display-1 { font-weight: 700; }
    </style>
</head>
<body>
    <div class="container py-5">
        <div class="row mb-4">
            <div class="col-12 text-center">
                <h1 class="display-4 mb-2">Showstopper Control Center</h1>
                <p class="lead text-muted">Final Demo - Raspberry Pi 5 Elite Version</p>
            </div>
        </div>

        <div class="row g-4">
            <!-- Main Status Card -->
            <div class="col-lg-6">
                <div class="card p-4 h-100">
                    <h3>System Status</h3>
                    <div id="status-box" class="display-1 text-center my-4 status-safe">SAFE</div>
                    <div class="row text-center mt-3">
                        <div class="col-6">
                            <h5>Light Level</h5>
                            <p id="lux-val" class="h2">0.0 Lux</p>
                        </div>
                        <div class="col-6">
                            <h5>G-Force</h5>
                            <p id="accel-val" class="h2">1.0 g</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Graph Card -->
            <div class="col-lg-6">
                <div class="card p-4 h-100">
                    <h3>Real-time Telemetry</h3>
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
                    label: 'G-Force (g)',
                    borderColor: '#ff1744',
                    data: [],
                    fill: false,
                    tension: 0.4
                }, {
                    label: 'Light (Lux/100)',
                    borderColor: '#00e676',
                    data: [],
                    fill: false,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: { ticks: { color: '#888' } },
                    y: { ticks: { color: '#888' }, beginAtZero: true }
                },
                plugins: { legend: { labels: { color: '#e0e0e0' } } }
            }
        });

        async function updateData() {
            const response = await fetch('/data');
            const data = await response.json();
            
            // Update UI
            const statusBox = document.getElementById('status-box');
            statusBox.innerText = data.status.toUpperCase();
            statusBox.className = 'display-1 text-center my-4 ' + 
                (data.alarm ? 'status-alarm' : (data.warning ? 'status-warning' : 'status-safe'));
            
            document.getElementById('lux-val').innerText = data.lux + ' Lux';
            document.getElementById('accel-val').innerText = data.accel + ' g';

            // Update Chart
            if (chart.data.labels.length > 20) {
                chart.data.labels.shift();
                chart.data.datasets[0].data.shift();
                chart.data.datasets[1].data.shift();
            }
            chart.data.labels.push(data.timestamp);
            chart.data.datasets[0].data.push(data.accel);
            chart.data.datasets[1].data.push(data.lux / 100);
            chart.update('none');
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
        return jsonify(sensor_data)

if __name__ == "__main__":
    # Start sensor thread
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()
    
    # Run server
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
