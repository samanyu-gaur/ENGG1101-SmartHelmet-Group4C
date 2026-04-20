import time
import threading
import math
import os
from datetime import datetime
from flask import Flask, render_template_string, jsonify
from gpiozero import PWMOutputDevice, LED, Button
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
# "Heartbeat" ensures the UI knows the Python script is still running even if I2C fails
system_state = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "status": "Initializing...",
    "timestamp": "",
    "heartbeat": 0,
    "i2c_online": False
}
data_lock = threading.Lock()
i2c_lock = threading.Lock()

# --- Hardware Initialization (Safe Mode) ---
# Using PWMOutputDevice for Buzzer to prevent "Out of Range" errors
buzzer = PWMOutputDevice(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

def setup_sensors():
    global bus
    with i2c_lock:
        try:
            bus = SMBus(I2C_BUS)
            bus.write_byte_data(MPU_ADDR, 0x6B, 0x00) # Wake MPU
            bus.write_byte(BH_ADDR, 0x01) # Power BH
            time.sleep(0.1)
            bus.write_byte(BH_ADDR, 0x10) # Continuous High Res
            return True
        except Exception as e:
            print(f"I2C Setup Warning: {e}")
            return False

# --- Sensor Logic (Robust Shield) ---
def get_safe_data():
    lux, accel = 0.0, 1.0
    online = False
    with i2c_lock:
        try:
            # Read Lux
            l_data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
            lux = ((l_data[0] << 8) | l_data[1]) / 1.2
            
            # Read Accel
            a_data = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 6)
            def rw(h, l):
                v = (h << 8) | l
                return v - 65536 if v >= 32768 else v
            ax = rw(a_data[0], a_data[1]) / 16384.0
            ay = rw(a_data[2], a_data[3]) / 16384.0
            az = rw(a_data[4], a_data[5]) / 16384.0
            accel = math.sqrt(ax**2 + ay**2 + az**2)
            online = True
        except:
            pass # REQUIREMENT: Do not crash if sensors fail
    return lux, accel, online

def sensor_thread():
    global system_state
    warning_start = None
    setup_sensors()
    
    while True:
        lux, accel, online = get_safe_data()
        touch = touch_sensor.is_pressed
        
        with data_lock:
            system_state["heartbeat"] += 1
            system_state["lux"] = round(lux, 2)
            system_state["accel"] = round(accel, 2)
            system_state["i2c_online"] = online
            system_state["timestamp"] = datetime.now().strftime("%H:%M:%S")

            if touch:
                system_state["alarm"] = False
                system_state["warning"] = False
                system_state["status"] = "Safe (Reset)"
                warning_start = None

            if not system_state["alarm"]:
                if accel > FALL_THRESHOLD:
                    system_state["alarm"] = True
                    system_state["status"] = "FALL DETECTED"
                elif lux > LUX_THRESHOLD:
                    if not system_state["warning"]:
                        system_state["warning"] = True
                        system_state["status"] = "REMOVAL WARNING"
                        warning_start = time.time()
                    elif time.time() - warning_start > REMOVAL_DELAY:
                        if not touch:
                            system_state["alarm"] = True
                            system_state["status"] = "HELMET REMOVED"
                else:
                    system_state["warning"] = False
                    if not system_state["alarm"]: system_state["status"] = "Normal"
                    warning_start = None

        # Hardware Feedback
        if system_state["alarm"]:
            led_green.off()
            led_red.on()
            buzzer.value = 0.5 # 50% Duty Cycle for Siren
        elif system_state["warning"]:
            led_green.off()
            led_red.value = int(time.time() * 4) % 2
            buzzer.off()
        else:
            led_green.on()
            led_red.off()
            buzzer.off()

        time.sleep(0.05)

# --- Web Interface (Emergency Template) ---
app = Flask(__name__)

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Emergency Smart Helmet Console</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0a0a0a; color: #fff; font-family: sans-serif; }
        .dashboard { max-width: 800px; margin: 40px auto; padding: 20px; }
        .status-card { background: #1a1a1a; border-radius: 15px; padding: 30px; text-align: center; border: 2px solid #333; }
        .alarm-active { border-color: #ff0000; box-shadow: 0 0 20px rgba(255,0,0,0.4); }
        .val-large { font-size: 4rem; font-weight: bold; margin: 10px 0; }
        .label { color: #888; text-transform: uppercase; font-size: 0.9rem; }
        .heartbeat { color: #00ff00; font-family: monospace; }
        .i2c-error { color: #ff0000; font-weight: bold; }
    </style>
</head>
<body>
    <div class="dashboard">
        <div id="main-card" class="status-card">
            <h2 id="status-text">INITIALIZING...</h2>
            <div id="val-display" class="val-large">0.0g</div>
            <div class="row mt-4">
                <div class="col-6">
                    <div class="label">Light Sensor</div>
                    <h3 id="lux-val">0 Lux</h3>
                </div>
                <div class="col-6">
                    <div class="label">System Heartbeat</div>
                    <div id="heartbeat" class="heartbeat">0</div>
                </div>
            </div>
            <div id="i2c-status" class="mt-3"></div>
        </div>
    </div>

    <script>
        async function update() {
            try {
                const res = await fetch('/data');
                const d = await res.json();
                
                document.getElementById('status-text').innerText = d.status.toUpperCase();
                document.getElementById('val-display').innerText = d.accel + 'g';
                document.getElementById('lux-val').innerText = d.lux + ' Lux';
                document.getElementById('heartbeat').innerText = 'PULSE: ' + d.heartbeat;
                
                const card = document.getElementById('main-card');
                if(d.alarm) {
                    card.style.borderColor = '#ff0000';
                    card.style.background = '#2a0000';
                } else if(d.warning) {
                    card.style.borderColor = '#ffff00';
                    card.style.background = '#1a1a00';
                } else {
                    card.style.borderColor = '#333';
                    card.style.background = '#1a1a1a';
                }

                const i2c = document.getElementById('i2c-status');
                i2c.innerHTML = d.i2c_online ? '' : '<span class="i2c-error">I2C BUS OFFLINE - CHECK WIRING</span>';
            } catch(e) {}
        }
        setInterval(update, 500);
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_PAGE)

@app.route('/data')
def data():
    with data_lock:
        return jsonify(system_state)

if __name__ == "__main__":
    t = threading.Thread(target=sensor_thread, daemon=True)
    t.start()
    # REQUIREMENT: Port 8080 for school networks
    app.run(host='0.0.0.0', port=8080, threaded=True, debug=False)
