import time
import threading
import math
import os
from datetime import datetime
from gpiozero import PWMOutputDevice, Button
from smbus2 import SMBus
from rich.live import Live
from rich.table import Table
from rich.layout import Layout
from rich.panel import Panel
from rich.console import Console
from rich import box
from flask import Flask, jsonify, render_template_string

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
state = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "status": "SAFE",
    "timestamp": "",
    "cpu_temp": 0.0,
    "logs": ["System Booting...", "Ready."],
    "online": True
}
data_lock = threading.Lock()
i2c_lock = threading.Lock()

# --- Hardware Setup ---
buzzer = PWMOutputDevice(BUZZER_PIN)
led_red = PWMOutputDevice(RED_LED_PIN)
led_green = PWMOutputDevice(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read()) / 1000.0
    except: return 0.0

def setup_sensors():
    global bus
    with i2c_lock:
        try:
            bus = SMBus(I2C_BUS)
            bus.write_byte_data(MPU_ADDR, 0x6B, 0x00)
            bus.write_byte(BH_ADDR, 0x01)
            time.sleep(0.1)
            bus.write_byte(BH_ADDR, 0x10)
            return True
        except: return False

def sensor_thread():
    global state
    warning_start = None
    setup_sensors()
    
    while True:
        lux, accel, online = 0.0, 1.0, False
        with i2c_lock:
            try:
                # Lux
                d = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
                lux = ((d[0] << 8) | d[1]) / 1.2
                # Accel
                d = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 6)
                def rw(h, l):
                    v = (h << 8) | l
                    return v - 65536 if v >= 32768 else v
                ax, ay, az = rw(d[0], d[1])/16384.0, rw(d[2], d[3])/16384.0, rw(d[4], d[5])/16384.0
                accel = math.sqrt(ax**2 + ay**2 + az**2)
                online = True
            except: pass

        touch = touch_sensor.is_pressed
        
        with data_lock:
            state["lux"] = round(lux, 2)
            state["accel"] = round(accel, 2)
            state["cpu_temp"] = round(get_cpu_temp(), 1)
            state["timestamp"] = datetime.now().strftime("%H:%M:%S")
            state["online"] = online

            if touch:
                if state["alarm"] or state["warning"]:
                    state["logs"].append(f"[{state['timestamp']}] Reset Pressed.")
                state["alarm"] = False
                state["warning"] = False
                state["status"] = "SAFE"
                warning_start = None

            if not state["alarm"]:
                if accel > FALL_THRESHOLD:
                    state["alarm"] = True
                    state["status"] = "FALL DETECTED"
                    state["logs"].append(f"[{state['timestamp']}] CRITICAL: Fall Detected ({accel}g)")
                elif lux > LUX_THRESHOLD:
                    if not state["warning"]:
                        state["warning"] = True
                        state["status"] = "REMOVAL WARNING"
                        warning_start = time.time()
                        state["logs"].append(f"[{state['timestamp']}] Warning: Helmet Removed")
                    elif time.time() - warning_start > REMOVAL_DELAY:
                        if not touch:
                            state["alarm"] = True
                            state["status"] = "ALARM: REMOVAL"
                            state["logs"].append(f"[{state['timestamp']}] CRITICAL: 5s Timer Expired")
                else:
                    state["warning"] = False
                    if not state["alarm"]: state["status"] = "SAFE"
                    warning_start = None
            
            # Keep logs to last 5
            if len(state["logs"]) > 5: state["logs"].pop(0)

        # Hardware Feedback
        if state["alarm"]:
            led_green.value = 0
            led_red.value = 1
            buzzer.value = 0.5
        elif state["warning"]:
            led_green.value = 0
            led_red.value = 1 if int(time.time() * 4) % 2 else 0
            buzzer.value = 0
        else:
            led_green.value = 1
            led_red.value = 0
            buzzer.value = 0

        time.sleep(0.05)

# --- Terminal UI Layout ---
def make_layout() -> Layout:
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", size=10),
        Layout(name="footer", size=8),
    )
    return layout

def update_ui(layout: Layout):
    with data_lock:
        # Header
        status_color = "red" if state["alarm"] else ("yellow" if state["warning"] else "green")
        online_str = "[green]ONLINE[/]" if state["online"] else "[red]OFFLINE[/]"
        header_table = Table.grid(expand=True)
        header_table.add_column(justify="left")
        header_table.add_column(justify="center")
        header_table.add_column(justify="right")
        header_table.add_row(
            f" [b]HELMET STATUS:[/] [{status_color}]{state['status']}[/]",
            f"[b]CORE TEMP:[/] {state['cpu_temp']}°C",
            f"{state['timestamp']} | {online_str} "
        )
        layout["header"].update(Panel(header_table, style="white on blue", box=box.ROUNDED))

        # Main Table
        main_table = Table(box=box.MINIMAL_DOUBLE_HEAD, expand=True)
        main_table.add_column("Sensor", justify="center", style="cyan")
        main_table.add_column("Current Reading", justify="center", style="magenta")
        main_table.add_column("Threshold", justify="center", style="white")
        main_table.add_column("Status", justify="center")

        lux_status = "[red]HIGH[/]" if state["lux"] > LUX_THRESHOLD else "[green]NORMAL[/]"
        accel_status = "[red]SPIKE[/]" if state["accel"] > FALL_THRESHOLD else "[green]NORMAL[/]"

        main_table.add_row("BH1750 (Lux)", f"{state['lux']} lx", f"> {LUX_THRESHOLD}", lux_status)
        main_table.add_row("MPU6050 (G)", f"{state['accel']} g", f"> {FALL_THRESHOLD}", accel_status)
        layout["main"].update(Panel(main_table, title="[b]Live Telemetry[/]", border_style="bright_blue"))

        # Footer / Logs
        log_content = "\n".join(state["logs"])
        layout["footer"].update(Panel(log_content, title="[b]Event History[/]", border_style="yellow"))

# --- Flask Server (Background) ---
app = Flask(__name__)
@app.route('/data')
def get_data():
    with data_lock: return jsonify(state)

def run_flask():
    app.run(host='0.0.0.0', port=8080, threaded=True, debug=False)

# --- Entry Point ---
if __name__ == "__main__":
    # Start Logic & Web
    t_sensor = threading.Thread(target=sensor_thread, daemon=True)
    t_sensor.start()
    
    t_flask = threading.Thread(target=run_flask, daemon=True)
    t_flask.start()

    # Launch Terminal UI
    console = Console()
    layout = make_layout()
    with Live(layout, refresh_per_second=10, screen=True) as live:
        while True:
            update_ui(layout)
            time.sleep(0.1)
