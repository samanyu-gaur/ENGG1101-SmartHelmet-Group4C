import time
import threading
import csv
import os
import math
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, jsonify
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objs as go
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
FALL_THRESHOLD = 3.0
REMOVAL_DELAY = 5.0
HISTORY_FILE = 'helmet_history.csv'

# --- Global State (Requirement: sensor_data dictionary) ---
sensor_data = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "alarm_type": None,
    "warning": False,
    "touch": False,
    "timestamp": "",
    "accel_history": [],
    "lux_history": [],
    "time_history": []
}
data_lock = threading.Lock()
MAX_HISTORY = 50

# --- Hardware Initialization ---
bus = SMBus(I2C_BUS)
buzzer = TonalBuzzer(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

def setup_sensors():
    try:
        bus.write_byte_data(MPU_ADDR, 0x6B, 0x00) # Wake MPU
        bus.write_byte(BH_ADDR, 0x01) # Power On BH
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x10) # Continuous High Res Mode
    except Exception as e:
        print(f"Sensor Init Error: {e}")

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
        ax, ay, az = read_word(data[0], data[1])/16384.0, read_word(data[2], data[3])/16384.0, read_word(data[4], data[5])/16384.0
        return math.sqrt(ax**2 + ay**2 + az**2)
    except: return 1.0

def log_incident(type, value):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Timestamp', 'Alarm Type', 'Sensor Value'])
        writer.writerow([now, type, f"{value:.2f}"])

# --- Background Thread (Requirement: sensor_loop) ---
def sensor_loop():
    global sensor_data
    setup_sensors()
    removal_start = None
    
    while True:
        lux = get_lux()
        accel = get_accel()
        touch = touch_sensor.is_pressed
        now_ts = datetime.now().strftime("%H:%M:%S")
        
        with data_lock:
            sensor_data["lux"] = lux
            sensor_data["accel"] = accel
            sensor_data["touch"] = touch
            sensor_data["timestamp"] = now_ts
            
            # History management
            sensor_data["accel_history"].append(accel)
            sensor_data["lux_history"].append(lux)
            sensor_data["time_history"].append(now_ts)
            if len(sensor_data["accel_history"]) > MAX_HISTORY:
                sensor_data["accel_history"].pop(0)
                sensor_data["lux_history"].pop(0)
                sensor_data["time_history"].pop(0)

            # Reset logic
            if touch:
                sensor_data["alarm"] = False
                sensor_data["warning"] = False
                sensor_data["alarm_type"] = None
                removal_start = None

            # Safety Logic
            if not sensor_data["alarm"]:
                if accel > FALL_THRESHOLD:
                    sensor_data["alarm"] = True
                    sensor_data["alarm_type"] = "Fall"
                    log_incident("Fall", accel)
                elif lux > LUX_THRESHOLD:
                    if not sensor_data["warning"]:
                        sensor_data["warning"] = True
                        removal_start = time.time()
                    elif time.time() - removal_start > REMOVAL_DELAY:
                        if not touch:
                            sensor_data["alarm"] = True
                            sensor_data["alarm_type"] = "Removal"
                            log_incident("Removal", lux)
                else:
                    sensor_data["warning"] = False
                    removal_start = None

        # Hardware Feedback
        if sensor_data["alarm"]:
            led_green.off()
            led_red.on()
            if sensor_data["alarm_type"] == "Fall":
                buzzer.play(Tone(1000))
            else:
                freq = 880 if int(time.time() * 4) % 2 else 440
                buzzer.play(Tone(freq))
        elif sensor_data["warning"]:
            led_green.off()
            if int(time.time() * 4) % 2: led_red.on()
            else: led_red.off()
            buzzer.stop()
        else:
            led_green.on()
            led_red.off()
            buzzer.stop()
            
        time.sleep(0.1)

# --- Flask & Dash Server ---
server = Flask(__name__)
app = Dash(__name__, server=server, url_base_pathname='/dashboard/')

# Requirement: /data route for lightweight JSON
@server.route('/data')
def get_sensor_data():
    with data_lock:
        # Return only the latest snapshot (excluding heavy history)
        return jsonify({
            "lux": sensor_data["lux"],
            "accel": sensor_data["accel"],
            "alarm": sensor_data["alarm"],
            "alarm_type": sensor_data["alarm_type"],
            "warning": sensor_data["warning"],
            "touch": sensor_data["touch"],
            "timestamp": sensor_data["timestamp"]
        })

@server.route('/')
def index():
    return render_template('index.html')

# Dash Layout & Callbacks
app.layout = html.Div(id='main-container', style={'padding': '20px', 'transition': 'background-color 0.5s'}, children=[
    html.H1("Smart Helmet Control Center", style={'textAlign': 'center', 'color': '#2c3e50'}),
    html.Div(id='status-indicator', style={'textAlign': 'center', 'fontSize': '24px', 'marginBottom': '20px', 'fontWeight': 'bold'}),
    
    html.Div(style={'display': 'flex', 'flexWrap': 'wrap'}, children=[
        html.Div(style={'flex': '1', 'minWidth': '400px'}, children=[dcc.Graph(id='accel-graph')]),
        html.Div(style={'flex': '1', 'minWidth': '400px'}, children=[dcc.Graph(id='lux-graph')])
    ]),
    
    html.Div(style={'marginTop': '40px'}, children=[
        html.H3("Recent Incident Log (CSV)"),
        html.Div(id='incident-table')
    ]),
    
    dcc.Interval(id='interval-component', interval=1000, n_intervals=0)
])

@app.callback(
    [Output('accel-graph', 'figure'),
     Output('lux-graph', 'figure'),
     Output('main-container', 'style'),
     Output('status-indicator', 'children'),
     Output('incident-table', 'children')],
    [Input('interval-component', 'n_intervals')]
)
def update_dashboard(n):
    with data_lock:
        time_hist = list(sensor_data["time_history"])
        accel_hist = list(sensor_data["accel_history"])
        lux_hist = list(sensor_data["lux_history"])
        is_alarm = sensor_data["alarm"]
        alarm_type = sensor_data["alarm_type"]
        is_warning = sensor_data["warning"]

    fig_accel = go.Figure(data=[go.Scatter(x=time_hist, y=accel_hist, mode='lines', name='G-Force', line=dict(color='#e74c3c', width=3))])
    fig_accel.update_layout(title='Real-time Acceleration (g)', xaxis_title='Time', yaxis_title='g', height=400)

    fig_lux = go.Figure(data=[go.Scatter(x=time_hist, y=lux_hist, mode='lines', name='Light Level', line=dict(color='#f1c40f', width=3))])
    fig_lux.update_layout(title='Real-time Light Levels (Lux)', xaxis_title='Time', yaxis_title='Lux', height=400)

    # Incident Table (Pandas)
    table_content = "No incidents logged yet."
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE)
            if not df.empty:
                last_incidents = df.tail(5).iloc[::-1]
                table_content = html.Table([
                    html.Thead(html.Tr([html.Th(col) for col in df.columns])),
                    html.Tbody([html.Tr([html.Td(last_incidents.iloc[i][col]) for col in df.columns]) for i in range(len(last_incidents))])
                ], style={'width': '100%', 'borderCollapse': 'collapse', 'textAlign': 'left'})
        except: pass

    bg_color = '#ffcccc' if is_alarm else ('#fff3cd' if is_warning else '#ccffcc')
    container_style = {'padding': '20px', 'transition': 'background-color 0.5s', 'backgroundColor': bg_color, 'minHeight': '100vh'}
    
    status_text = "STATUS: SAFE"
    if is_alarm: status_text = f"STATUS: ALARM ({alarm_type.upper()} DETECTED!)"
    elif is_warning: status_text = "STATUS: WARNING (HELMET REMOVAL DETECTED)"

    return fig_accel, fig_lux, container_style, status_text, table_content

# --- Main Entry Point (Requirement: Daemon Thread & Host Config) ---
if __name__ == '__main__':
    # Start the sensor loop as a background daemon thread
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()
    
    # Run the Flask server with specific requirements
    # host='0.0.0.0' for external access, threaded=True for handling multiple requests
    server.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
