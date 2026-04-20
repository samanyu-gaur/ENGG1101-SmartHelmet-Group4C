import time
import threading
import math
import os
from datetime import datetime
from flask import Flask, render_template_string, jsonify
from smbus2 import SMBus, i2c_msg
from gpiozero import PWMOutputDevice, LED, Button

# --- Configuration ---
I2C_BUS = 1
ADDR_BH = 0x23
ADDR_MPU = 0x68

PIN_BUZZER = 12
PIN_LED_RED = 27
PIN_LED_GRN = 17
PIN_TOUCH = 24

THRESH_LUX = 50
THRESH_FALL = 3.0
DELAY_REMOVAL = 5.0

# --- Global State ---
state = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "status": "SAFE",
    "timestamp": "",
    "countdown": 0.0
}
data_lock = threading.Lock()

# --- Hardware Setup ---
bus = SMBus(I2C_BUS)

def init_hw():
    try:
        bus.write_byte(ADDR_BH, 0x01) # Power On
        bus.write_byte(ADDR_BH, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(ADDR_BH, 0x10) # Continuous H-Res
        bus.write_byte_data(ADDR_MPU, 0x6B, 0x00) # Wake MPU
        return True
    except:
        return False

buzzer = PWMOutputDevice(PIN_BUZZER)
led_red = LED(PIN_LED_RED)
led_grn = LED(PIN_LED_GRN)
touch_sensor = Button(PIN_TOUCH, pull_up=False)

# --- Sensor Logic (Multi-Threaded) ---
def sensor_loop():
    global state
    warning_start = None
    init_hw()
    
    while True:
        # 1. Fetch Data with i2c_msg fix
        try:
            # Lux
            msg = i2c_msg.read(ADDR_BH, 2)
            bus.i2c_rdwr(msg)
            l_data = list(msg)
            lux = ((l_data[0] << 8) | l_data[1]) / 1.2
            
            # Accel
            a_data = bus.read_i2c_block_data(ADDR_MPU, 0x3B, 6)
            def rw(h, l):
                v = (h << 8) | l
                return v - 65536 if v >= 32768 else v
            ax, ay, az = rw(a_data[0], a_data[1])/16384.0, rw(a_data[2], a_data[3])/16384.0, rw(a_data[4], a_data[5])/16384.0
            accel = math.sqrt(ax**2 + ay**2 + az**2)
        except:
            lux, accel = state["lux"], state["accel"]

        touch = touch_sensor.is_pressed
        now = time.time()

        with data_lock:
            state["lux"] = round(lux, 2)
            state["accel"] = round(accel, 2)
            state["timestamp"] = datetime.now().strftime("%H:%M:%S")

            # 2. Safety Logic
            if touch:
                state["alarm"] = False
                state["warning"] = False
                state["status"] = "SAFE"
                warning_start = None
                state["countdown"] = 0.0

            if not state["alarm"]:
                if accel > THRESH_FALL:
                    state["alarm"] = True
                    state["status"] = "FALL DETECTED"
                elif lux > THRESH_LUX:
                    if not state["warning"]:
                        state["warning"] = True
                        state["status"] = "REMOVAL WARNING"
                        warning_start = now
                    
                    elapsed = now - warning_start
                    state["countdown"] = max(0, round(DELAY_REMOVAL - elapsed, 1))
                    
                    if elapsed > DELAY_REMOVAL:
                        if not touch:
                            state["alarm"] = True
                            state["status"] = "ALARM: REMOVED"
                else:
                    state["warning"] = False
                    state["countdown"] = 0.0
                    if not state["alarm"]: state["status"] = "SAFE"
                    warning_start = None

        # 3. Hardware Feedback
        if state["alarm"]:
            led_grn.off()
            led_red.on()
            buzzer.value = 0.5 if int(time.time() * 6) % 2 else 0 # Siren
        elif state["warning"]:
            led_grn.off()
            led_red.value = int(time.time() * 4) % 2
            buzzer.off()
        else:
            led_grn.on()
            led_red.off()
            buzzer.off()

        time.sleep(0.05)

# --- Flask Web UI ---
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Group 4C: Smart Helmet Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #f8f9fa; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .stat-card { border-radius: 15px; border: none; box-shadow: 0 4px 15px rgba(0,0,0,0.1); padding: 20px; transition: all 0.3s; }
        .status-safe { background: #d1e7dd; color: #0f5132; }
        .status-warning { background: #fff3cd; color: #856404; border: 2px solid #ffe69c; }
        .status-alarm { background: #f8d7da; color: #842029; border: 2px solid #f5c2c7; animation: blink 1s infinite; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.7; } 100% { opacity: 1; } }
        .metric { font-size: 2.5rem; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container py-5">
        <div class="row mb-4">
            <div class="col-12 text-center">
                <h1 class="display-4 fw-bold">Smart Helmet Control Center</h1>
                <p class="text-muted">HKU ENGG1101 - Group 4C Final Deliverable</p>
            </div>
        </div>

        <div class="row g-4 mb-4">
            <div class="col-md-6">
                <div id="status-card" class="stat-card status-safe h-100 text-center">
                    <h2 class="text-uppercase mb-3">System Status</h2>
                    <div id="status-text" class="metric mb-2">SAFE</div>
                    <div id="countdown-area" class="h4 text-danger" style="display:none;">
                        Alert triggering in: <span id="timer">5.0</span>s
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card bg-white h-100 text-center">
                    <h6>Light Exposure</h6>
                    <div id="lux-metric" class="metric text-primary">0</div>
                    <div class="text-muted">Lux</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card bg-white h-100 text-center">
                    <h6>Impact Force</h6>
                    <div id="accel-metric" class="metric text-danger">1.0</div>
                    <div class="text-muted">G-Force</div>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-12">
                <div class="stat-card bg-white">
                    <h5 class="mb-4">Live Telemetry (G-Force)</h5>
                    <canvas id="telemetryChart" height="100"></canvas>
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
                    borderColor: '#dc3545',
                    backgroundColor: 'rgba(220, 53, 69, 0.1)',
                    data: [],
                    fill: true,
                    tension: 0.4
                }]
            },
            options: { responsive: true, scales: { y: { beginAtZero: false, min: 0, max: 5 } } }
        });

        async function updateData() {
            try {
                const res = await fetch('/data');
                const d = await res.json();
                
                // Update Metrics
                document.getElementById('status-text').innerText = d.status;
                document.getElementById('lux-metric').innerText = d.lux;
                document.getElementById('accel-metric').innerText = d.accel;
                
                // Update UI State
                const card = document.getElementById('status-card');
                const cdArea = document.getElementById('countdown-area');
                
                card.className = 'stat-card h-100 text-center ' + 
                    (d.alarm ? 'status-alarm' : (d.warning ? 'status-warning' : 'status-safe'));
                
                if (d.warning && !d.alarm) {
                    cdArea.style.display = 'block';
                    document.getElementById('timer').innerText = d.countdown;
                } else {
                    cdArea.style.display = 'none';
                }

                // Update Chart
                if (chart.data.labels.length > 30) {
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.shift();
                }
                chart.data.labels.push(d.timestamp);
                chart.data.datasets[0].data.push(d.accel);
                chart.update('none');
            } catch (e) {}
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
        return jsonify(state)

if __name__ == "__main__":
    # 1. Start Sensor Thread
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()
    
    # 2. Run Web Server
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
