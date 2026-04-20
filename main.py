import time
import math
import threading
from datetime import datetime
from smbus2 import SMBus, i2c_msg
from gpiozero import PWMOutputDevice, LED, Button
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# --- Configuration ---
I2C_BUS = 1
ADDR_BH = 0x23
ADDR_MPU = 0x68

PIN_BUZZER = 12
PIN_LED_RED = 27
PIN_TOUCH = 24

THRESH_LUX = 150    # REQUIREMENT: Lux > 150 for removal
THRESH_FALL = 3.0   # REQUIREMENT: G-Force > 3.0g
DELAY_REMOVAL = 5.0

# --- Global State ---
try:
    bus = SMBus(I2C_BUS)
except:
    bus = None

state = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "warning_start": None,
    "status": "MONITORING",
    "countdown": 5.0,
    "touch_active": False
}

state_lock = threading.Lock()

# --- Hardware Setup ---
def init_hw():
    if bus is None:
        return False
    try:
        # BH1750 Wakeup
        bus.write_byte(ADDR_BH, 0x01) # Power On
        bus.write_byte(ADDR_BH, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(ADDR_BH, 0x10) # Continuous H-Res Mode
        
        # MPU6050 Wakeup
        bus.write_byte_data(ADDR_MPU, 0x6B, 0x00)
        return True
    except:
        return False

# Initialize GPIO with error handling (if run on non-pi)
try:
    buzzer = PWMOutputDevice(PIN_BUZZER)
    led_red = LED(PIN_LED_RED)
    touch_sensor = Button(PIN_TOUCH, pull_up=False)
except:
    buzzer = None
    led_red = None
    touch_sensor = None

def get_sensors():
    if bus is None:
        return state["lux"], state["accel"]
    try:
        # BH1750 Lux
        msg = i2c_msg.read(ADDR_BH, 2)
        bus.i2c_rdwr(msg)
        l_data = list(msg)
        lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
        # MPU6050 Accel
        a_data = bus.read_i2c_block_data(ADDR_MPU, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(a_data[0], a_data[1]) / 16384.0
        ay = rw(a_data[2], a_data[3]) / 16384.0
        az = rw(a_data[4], a_data[5]) / 16384.0
        accel = math.sqrt(ax**2 + ay**2 + az**2)
        
        return lux, accel
    except Exception as e:
        return state["lux"], state["accel"]

def hardware_loop():
    init_hw()
    while True:
        lux, accel = get_sensors()
        touch = touch_sensor.is_pressed if touch_sensor else False
        now = time.time()
        
        with state_lock:
            state["lux"] = lux
            state["accel"] = accel
            state["touch_active"] = touch

            # 1. Reset / Neutral Conditions
            if lux < THRESH_LUX or touch:
                state["warning"] = False
                state["warning_start"] = None
                state["countdown"] = 5.0
                if touch: # Manual silence
                    state["alarm"] = False
                    state["status"] = "MONITORING"

            # 2. Alarm Escalation
            if not state["alarm"]:
                # Immediate Fall Alarm
                if accel > THRESH_FALL:
                    state["alarm"] = True
                    state["status"] = "ALARM: CRITICAL FALL"
                
                # Removal Alarm (5s Countdown)
                elif lux > THRESH_LUX:
                    if not state["warning"]:
                        state["warning"] = True
                        state["warning_start"] = now
                        state["status"] = "WARNING: REMOVAL"
                    
                    elapsed = now - state["warning_start"]
                    state["countdown"] = max(0, DELAY_REMOVAL - elapsed)
                    
                    if elapsed > DELAY_REMOVAL:
                        if not touch: # Trigger if not cleared
                            state["alarm"] = True
                            state["status"] = "ALARM: HELMET DISCARDED"

            # 3. Hardware Drive
            if buzzer is not None and led_red is not None:
                if state["alarm"]:
                    led_red.on()
                    buzzer.value = 0.5 if int(now * 8) % 2 else 0
                elif state["lux"] > THRESH_LUX:
                    led_red.value = int(now * 4) % 2
                    buzzer.off()
                else:
                    led_red.off()
                    buzzer.off()
        time.sleep(0.1)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Helmet HUD</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            background-color: #0b0c10;
            color: #66fcf1;
            font-family: 'Courier New', Courier, monospace;
            text-align: center;
            margin: 0;
            padding: 20px;
        }
        h1 {
            color: #45a29e;
            text-shadow: 0 0 10px #45a29e;
        }
        .container {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 20px;
        }
        .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            width: 90%;
            max-width: 800px;
        }
        .card {
            background: #1f2833;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #45a29e;
            box-shadow: 0 0 15px #45a29e55;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        .timer {
            font-size: 4em;
            font-weight: bold;
            color: #fceea7;
            text-shadow: 0 0 20px #fceea7;
        }
        .alert {
            color: #ff3b3f !important;
            text-shadow: 0 0 20px #ff3b3f !important;
        }
        canvas {
            background: #1f2833;
            border-radius: 10px;
        }
        .status-box {
            font-size: 1.5em;
            font-weight: bold;
            margin-top: 10px;
            text-transform: uppercase;
        }
    </style>
</head>
<body>
    <h1>SMART HELMET HUD</h1>
    <div class="container">
        <div class="dashboard-grid">
            <div class="card">
                <h2>G-Force Matrix</h2>
                <div style="font-size: 2em; margin-bottom: 10px;" id="accelVal">1.00 g</div>
                <div style="height:200px; width:100%;">
                    <canvas id="gforceChart"></canvas>
                </div>
            </div>
            <div class="card">
                <h2>System Status</h2>
                <div class="timer" id="countdownTimer">5.0</div>
                <div class="status-box" id="systemStatus">MONITORING</div>
                <h3 style="margin-top: 20px;">Lux Level: <span id="luxVal">0.0</span></h3>
                <h3>Touch Sensor: <span id="touchVal">INACTIVE</span></h3>
            </div>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('gforceChart').getContext('2d');
        const gforceChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: Array(20).fill(''),
                datasets: [{
                    label: 'G-Force (g)',
                    data: Array(20).fill(1),
                    borderColor: '#66fcf1',
                    backgroundColor: 'rgba(102, 252, 241, 0.2)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { min: 0, max: 10, ticks: { color: '#c5c6c7' }, grid: { color: '#45a29e55' } },
                    x: { ticks: { display: false }, grid: { display: false } }
                },
                plugins: {
                    legend: { display: false }
                },
                animation: false
            }
        });

        setInterval(() => {
            fetch('/data')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('accelVal').innerText = data.accel.toFixed(2) + ' g';
                    document.getElementById('luxVal').innerText = data.lux.toFixed(1);
                    document.getElementById('touchVal').innerText = data.touch_active ? 'ACTIVE' : 'INACTIVE';
                    
                    const timerEl = document.getElementById('countdownTimer');
                    timerEl.innerText = data.countdown.toFixed(1);
                    
                    const statusEl = document.getElementById('systemStatus');
                    statusEl.innerText = data.status;
                    
                    if (data.alarm) {
                        timerEl.classList.add('alert');
                        statusEl.classList.add('alert');
                    } else if (data.warning) {
                        timerEl.style.color = '#ffaa00';
                        statusEl.style.color = '#ffaa00';
                        timerEl.classList.remove('alert');
                        statusEl.classList.remove('alert');
                    } else {
                        timerEl.style.color = '#fceea7';
                        statusEl.style.color = '#66fcf1';
                        timerEl.classList.remove('alert');
                        statusEl.classList.remove('alert');
                    }

                    const chartData = gforceChart.data.datasets[0].data;
                    chartData.push(data.accel);
                    chartData.shift();
                    gforceChart.update();
                })
                .catch(err => console.error(err));
        }, 200);
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@app.route('/data')
def get_data():
    with state_lock:
        return jsonify(state)

if __name__ == '__main__':
    # Start the hardware background thread
    hw_thread = threading.Thread(target=hardware_loop, daemon=True)
    hw_thread.start()
    
    # Run the Flask app on 0.0.0.0
    app.run(host='0.0.0.0', port=5000)
