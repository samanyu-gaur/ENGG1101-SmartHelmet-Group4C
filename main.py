import time
import math
import os
import threading
from datetime import datetime
from smbus2 import SMBus
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

# --- ANSI UI Styling ---
CLR = "\033[H\033[J"
RST = "\033[0m"
BLD = "\033[1m"
RED = "\033[91m"
GRN = "\033[92m"
YLW = "\033[93m"
CYN = "\033[96m"
BLU = "\033[94m"
WHT = "\033[97m"

# --- Global State ---
state = {
    "lux": 0.0,
    "accel": 1.0,
    "status": "SAFE",
    "alarm": False,
    "warning": False,
    "warning_start": None,
    "sensor_health": "INITIALIZING",
    "last_reset": "NEVER",
    "timestamp": ""
}
data_lock = threading.Lock()

# --- Hardware Setup ---
bus = SMBus(I2C_BUS)
buzzer = PWMOutputDevice(PIN_BUZZER)
led_red = LED(PIN_LED_RED)
led_grn = LED(PIN_LED_GRN)
touch_sensor = Button(PIN_TOUCH, pull_up=False)

def init_bh1750():
    """Requirement 1: Resurrection Logic"""
    try:
        bus.write_byte(ADDR_BH, 0x01) # Power On
        bus.write_byte(ADDR_BH, 0x07) # Reset
        time.sleep(0.2)
        bus.write_byte(ADDR_BH, 0x10) # High-Res Mode
        return True
    except:
        return False

def setup_hardware():
    # Wake MPU6050
    try:
        bus.write_byte_data(ADDR_MPU, 0x6B, 0x00)
    except:
        pass
    
    # Init BH1750
    if init_bh1750():
        state["sensor_health"] = "ONLINE"
    else:
        state["sensor_health"] = "BH1750 ERROR"

def get_sensor_readings():
    lux, accel = 0.0, 1.0
    # Read Lux with Requirement 1: Resurrection/Soft Reset
    try:
        data = bus.read_i2c_block_data(ADDR_BH, 0x10, 2)
        lux = ((data[0] << 8) | data[1]) / 1.2
        if lux == 0.0:
            bus.write_byte(ADDR_BH, 0x01) # Soft Reset if stuck at 0
        state["sensor_health"] = "ONLINE"
    except:
        state["sensor_health"] = "SENSOR DISCONNECTED"

    # Read Accel
    try:
        d = bus.read_i2c_block_data(ADDR_MPU, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(d[0], d[1])/16384.0
        ay = rw(d[2], d[3])/16384.0
        az = rw(d[4], d[5])/16384.0
        accel = math.sqrt(ax**2 + ay**2 + az**2)
    except:
        pass
    
    return lux, accel

def draw_gauge(label, value, max_val, color):
    width = 20
    filled = int((min(value, max_val) / max_val) * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{BLD}{WHT}{label:<8}{RST} {color}[{bar}] {value:>6.2f}{RST}"

def render_ui():
    with data_lock:
        print(CLR, end="")
        
        # Flashing Header
        header_color = RED if (state["alarm"] and int(time.time()*2)%2) else CYN
        header_text = " !! ALARM !! " if state["alarm"] else " CYBER GUARDIAN OS "
        print(f"{BLD}{header_color}╔══════════════════════════════════════════════════════╗{RST}")
        print(f"{BLD}{header_color}║ {header_text:^52} ║{RST}")
        print(f"{BLD}{header_color}╚══════════════════════════════════════════════════════╝{RST}\n")

        # Telemetry Gauges
        print(draw_gauge("LIGHT", state["lux"], 200, YLW if state["lux"] > THRESH_LUX else GRN))
        print(draw_gauge("G-FORCE", state["accel"], 5, RED if state["accel"] > THRESH_FALL else GRN))
        print("")

        # Status Table
        print(f"{BLD}{BLU}┌──────────────────────┬───────────────────────────────┐{RST}")
        print(f"{BLD}{BLU}│ SENSOR HEALTH        │ {state['sensor_health']:<29} │{RST}")
        print(f"{BLD}{BLU}├──────────────────────┼───────────────────────────────┤{RST}")
        print(f"{BLD}{BLU}│ LAST RESET           │ {state['last_reset']:<29} │{RST}")
        print(f"{BLD}{BLU}├──────────────────────┼───────────────────────────────┤{RST}")
        curr_color = RED if state["alarm"] else (YLW if state["warning"] else GRN)
        print(f"{BLD}{BLU}│ CURRENT STATE        │ {curr_color}{state['status']:<29}{RST}{BLD}{BLU} │{RST}")
        print(f"{BLD}{BLU}└──────────────────────┴───────────────────────────────┘{RST}")

        # Live Countdown
        if state["warning"] and not state["alarm"]:
            rem = max(0, DELAY_REMOVAL - (time.time() - state["warning_start"]))
            print(f"\n{YLW}{BLD} >> ESCALATION IN: {rem:.1f}s <<{RST}")
        elif state["alarm"]:
            print(f"\n{RED}{BLD} >> CRITICAL ALERT: SYSTEM LOCKDOWN <<{RST}")
        else:
            print(f"\n{GRN} >> MONITORING ACTIVE <<{RST}")

def main():
    setup_hardware()
    last_ui_update = 0
    
    try:
        while True:
            lux, accel = get_sensor_readings()
            touch = touch_sensor.is_pressed
            
            with data_lock:
                state["lux"] = lux
                state["accel"] = accel
                state["timestamp"] = datetime.now().strftime("%H:%M:%S")

                # Reset Logic
                if touch:
                    if state["alarm"] or state["warning"]:
                        state["last_reset"] = state["timestamp"]
                    state["alarm"] = False
                    state["warning"] = False
                    state["warning_start"] = None
                    state["status"] = "SAFE"

                # Safety Protocols
                if not state["alarm"]:
                    if accel > THRESH_FALL:
                        state["alarm"] = True
                        state["status"] = "FALL DETECTED"
                    elif lux > THRESH_LUX:
                        if not state["warning"]:
                            state["warning"] = True
                            state["warning_start"] = time.time()
                            state["status"] = "REMOVAL WARNING"
                        elif time.time() - state["warning_start"] > DELAY_REMOVAL:
                            if not touch:
                                state["alarm"] = True
                                state["status"] = "ALARM: REMOVAL"
                    else:
                        state["warning"] = False
                        state["warning_start"] = None
                        if not state["alarm"]: state["status"] = "SAFE"

            # Hardware Feedback
            if state["alarm"]:
                led_grn.off()
                led_red.on()
                # Rapid Siren
                buzzer.value = 0.5 if int(time.time() * 8) % 2 else 0 
            elif state["warning"]:
                led_grn.off()
                led_red.value = int(time.time() * 4) % 2
                buzzer.off()
            else:
                led_grn.on()
                led_red.off()
                buzzer.off()

            # UI Update
            if time.time() - last_ui_update > 0.1:
                render_ui()
                last_ui_update = time.time()
            
            time.sleep(0.05)

    except KeyboardInterrupt:
        led_red.off()
        led_grn.off()
        buzzer.off()
        print(f"\n{GRN}SYSTEM SHUTDOWN CLEANLY.{RST}")

if __name__ == "__main__":
    main()
