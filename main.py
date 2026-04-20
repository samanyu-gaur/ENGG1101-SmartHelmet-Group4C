import time
import threading
import csv
import os
import math
import pandas as pd
from datetime import datetime
from flask import Flask
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

# --- Global State ---
class HelmetState:
    def __init__(self):
        self.lux = 0.0
        self.accel_total = 1.0
        self.alarm_active = False
        self.alarm_type = None  # 'Fall' or 'Removal'
        self.removal_warning = False
        self.removal_start_time = None
        self.touch_pressed = False
        self.lock = threading.Lock()
        
        # History for charts
        self.accel_history = []
        self.lux_history = []
        self.timestamps = []
        self.max_points = 50

state = HelmetState()

# --- Hardware Initialization ---
bus = SMBus(I2C_BUS)
buzzer = TonalBuzzer(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

def setup_sensors():
    try:
        # Wake up MPU6050
        bus.write_byte_data(MPU_ADDR, 0x6B, 0x00)
        # BH1750 Power On and Continuous High Res Mode
        bus.write_byte(BH_ADDR, 0x01) # Power On
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x10) # Continuous High Res Mode
    except Exception as e:
        print(f"Sensor Init Error: {e}")

def get_lux():
    try:
        data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
        return ((data[0] << 8) | data[1]) / 1.2
    except:
        return 0.0

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
    except:
        return 1.0

def log_incident(type, value):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.isfile(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Timestamp', 'Alarm Type', 'Sensor Value'])
        writer.writerow([now, type, f"{value:.2f}"])

# --- Background Logic ---
def sensor_loop():
    global state
    setup_sensors()
    
    while True:
        lux = get_lux()
        accel = get_accel()
        touch = touch_sensor.is_pressed
        now = time.time()
        
        with state.lock:
            state.lux = lux
            state.accel_total = accel
            state.touch_pressed = touch
            
            # Update history
            state.timestamps.append(datetime.now().strftime("%H:%M:%S"))
            state.accel_history.append(accel)
            state.lux_history.append(lux)
            if len(state.accel_history) > state.max_points:
                state.accel_history.pop(0)
                state.lux_history.pop(0)
                state.timestamps.pop(0)

            # Reset logic
            if touch:
                state.alarm_active = False
                state.removal_warning = False
                state.removal_start_time = None
                state.alarm_type = None

            # Safety Logic
            if not state.alarm_active:
                # Fall Detection
                if accel > FALL_THRESHOLD:
                    state.alarm_active = True
                    state.alarm_type = 'Fall'
                    log_incident('Fall', accel)
                
                # Removal Detection
                elif lux > LUX_THRESHOLD:
                    if not state.removal_warning:
                        state.removal_warning = True
                        state.removal_start_time = now
                    elif now - state.removal_start_time > REMOVAL_DELAY:
                        if not touch:
                            state.alarm_active = True
                            state.alarm_type = 'Removal'
                            log_incident('Removal', lux)
                else:
                    state.removal_warning = False
                    state.removal_start_time = None

        # Hardware Feedback
        if state.alarm_active:
            led_green.off()
            if state.alarm_type == 'Fall':
                led_red.on()
                # Continuous Siren
                buzzer.play(Tone(1000))
            else: # Removal Alarm
                led_red.on()
                # Pulsing Siren
                if int(time.time() * 4) % 2:
                    buzzer.play(Tone(880))
                else:
                    buzzer.play(Tone(440))
        elif state.removal_warning:
            led_green.off()
            # Blink Red LED at 2Hz
            if int(time.time() * 4) % 2:
                led_red.on()
            else:
                led_red.off()
            buzzer.stop()
        else:
            led_green.on()
            led_red.off()
            buzzer.stop()
            
        time.sleep(0.1)

# --- Web Interface (Dash + Flask) ---
server = Flask(__name__)
app = Dash(__name__, server=server, url_base_pathname='/dashboard/')

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
    with state.lock:
        timestamps = list(state.timestamps)
        accel_data = list(state.accel_history)
        lux_data = list(state.lux_history)
        is_alarm = state.alarm_active
        alarm_type = state.alarm_type
        is_warning = state.removal_warning

    # Accel Figure
    fig_accel = go.Figure(data=[go.Scatter(x=timestamps, y=accel_data, mode='lines', name='G-Force', line=dict(color='#e74c3c', width=3))])
    fig_accel.update_layout(title='Real-time Acceleration (g)', xaxis_title='Time', yaxis_title='g', height=400)

    # Lux Figure
    fig_lux = go.Figure(data=[go.Scatter(x=timestamps, y=lux_data, mode='lines', name='Light Level', line=dict(color='#f1c40f', width=3))])
    fig_lux.update_layout(title='Real-time Light Levels (Lux)', xaxis_title='Time', yaxis_title='Lux', height=400)

    # Incident Table
    table_content = "No incidents logged yet."
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_csv(HISTORY_FILE)
            if not df.empty:
                last_incidents = df.tail(5).iloc[::-1] # Last 5, reversed
                table_content = html.Table([
                    html.Thead(html.Tr([html.Th(col) for col in df.columns])),
                    html.Tbody([
                        html.Tr([html.Td(last_incidents.iloc[i][col]) for col in df.columns])
                        for i in range(len(last_incidents))
                    ])
                ], style={'width': '100%', 'borderCollapse': 'collapse', 'textAlign': 'left'})
        except Exception as e:
            table_content = f"Error reading log: {e}"

    # Styling
    bg_color = '#ffcccc' if is_alarm else ('#fff3cd' if is_warning else '#ccffcc')
    container_style = {'padding': '20px', 'transition': 'background-color 0.5s', 'backgroundColor': bg_color, 'minHeight': '100vh'}
    
    status_text = "STATUS: SAFE"
    if is_alarm:
        status_text = f"STATUS: ALARM ({alarm_type.upper()} DETECTED!)"
    elif is_warning:
        status_text = "STATUS: WARNING (HELMET REMOVAL DETECTED)"

    return fig_accel, fig_lux, container_style, status_text, table_content

@server.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # Start background thread
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()
    
    # Run server
    server.run(host='0.0.0.0', port=5000)
