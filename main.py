import time
import math
import os
from datetime import datetime
from smbus2 import SMBus
from gpiozero import PWMOutputDevice, LED, Button

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

# --- ANSI UI Constants ---
CLR = "\033[H\033[J"
RST = "\033[0m"
BLD = "\033[1m"
RED = "\033[91m"
GRN = "\033[92m"
YLW = "\033[93m"
CYN = "\033[96m"
BLU = "\033[94m"

# --- Global State ---
bus = SMBus(I2C_BUS)
alarm_active = False
warning_active = False
warning_start = None
last_lux = 0.0
last_accel = 1.0
logs = ["- SYSTEM INITIALIZED", "- MONITORING STARTED", "- READY"]

def init_hw():
    try:
        bus.write_byte(BH_ADDR, 0x01) # Power On
        bus.write_byte(BH_ADDR, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x10) # Continuous H-Res
        bus.write_byte_data(MPU_ADDR, 0x6B, 0x00) # Wake MPU
        return True
    except:
        return False

# Hardware Components
buzzer = PWMOutputDevice(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

def get_sensors():
    global last_lux, last_accel
    try:
        # Lux with Reliability Fix
        l_data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
        lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
        if lux == 0: # Requirement: Bus Recovery
            bus.write_byte(BH_ADDR, 0x01) 
            
        # Accel
        a_data = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(a_data[0], a_data[1]) / 16384.0
        ay = rw(a_data[2], a_data[3]) / 16384.0
        az = rw(a_data[4], a_data[5]) / 16384.0
        accel = math.sqrt(ax**2 + ay**2 + az**2)
        
        last_lux, last_accel = lux, accel
        return lux, accel
    except:
        return last_lux, last_accel

def add_log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    logs.append(f"[{ts}] {msg}")
    if len(logs) > 3: logs.pop(0)

def draw_gauge(value, max_val, color):
    width = 20
    filled = int((min(value, max_val) / max_val) * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{color}[{bar}] {value:>6.2f}{RST}"

def draw_ui():
    print(CLR, end="")
    print(f"{BLD}{CYN}┌────────────────────────────────────────────────────────┐{RST}")
    print(f"{BLD}{CYN}│       PROJECT: GUARDIAN - SMART HELMET MONITOR         │{RST}")
    print(f"{BLD}{CYN}└────────────────────────────────────────────────────────┘{RST}\n")

    # Status Indicator
    if alarm_active:
        status = f"{RED}{BLD}[ ! ALARM ACTIVE ! ]{RST}"
    elif warning_active:
        status = f"{YLW}{BLD}[ ! WARNING: REMOVAL ! ]{RST}"
    else:
        status = f"{GRN}{BLD}[ OK - SECURE ]{RST}"
    print(f" SYSTEM STATE: {status}\n")

    # Gauges
    print(f" {BLD}LIGHT EXPOSURE (LUX){RST}")
    print(f" {draw_gauge(last_lux, 200, YLW if last_lux > LUX_THRESHOLD else GRN)}")
    print(f" {BLD}G-FORCE INTENSITY (G){RST}")
    print(f" {draw_gauge(last_accel, 5, RED if last_accel > FALL_THRESHOLD else GRN)}\n")

    # Countdown / Logs
    print(f"{BLU}──────────────────────────────────────────────────────────{RST}")
    if warning_active and not alarm_active:
        rem = max(0, REMOVAL_DELAY - (time.time() - warning_start))
        print(f"{YLW}{BLD} >> REMOVAL DETECTED: AUTO-ALARM IN {rem:.1f}s <<{RST}")
    elif alarm_active:
        print(f"{RED}{BLD} >> CRITICAL ALERT: PRESS RESET TO SILENCE <<{RST}")
    else:
        print(f"{GRN} >> SYSTEM MONITORING FOR FALLS & REMOVAL <<{RST}")
    print(f"{BLU}──────────────────────────────────────────────────────────{RST}")
    
    print(f"\n {BLD}RECENT EVENT LOG:{RST}")
    for log in logs:
        print(f" {CYN}{log}{RST}")

def main():
    global alarm_active, warning_active, warning_start
    if not init_hw():
        print("Hardware Failure. Check I2C bus.")
        return

    try:
        while True:
            lux, accel = get_sensors()
            touch = touch_sensor.is_pressed

            # Requirement: Reset Logic
            if touch:
                if alarm_active or warning_active:
                    add_log("ALARM MANUALLY RESET")
                alarm_active = False
                warning_active = False
                warning_start = None

            # Requirement: Safety Protocols
            if not alarm_active:
                if accel > FALL_THRESHOLD:
                    alarm_active = True
                    add_log(f"FALL DETECTED: {accel:.2f}g")
                elif lux > LUX_THRESHOLD:
                    if not warning_active:
                        warning_active = True
                        warning_start = time.time()
                        add_log("REMOVAL WARNING START")
                    elif time.time() - warning_start > REMOVAL_DELAY:
                        if not touch:
                            alarm_active = True
                            add_log("ALARM: REMOVAL TIMEOUT")
                else:
                    warning_active = False
                    warning_start = None

            # Requirement: Hardware Output
            if alarm_active:
                led_green.off()
                led_red.on()
                # Fast Pulse Siren
                buzzer.value = 0.5 if int(time.time() * 6) % 2 else 0
            elif warning_active:
                led_green.off()
                led_red.value = int(time.time() * 4) % 2
                buzzer.off()
            else:
                led_green.on()
                led_red.off()
                buzzer.off()

            draw_ui()
            time.sleep(0.1)

    except KeyboardInterrupt:
        led_red.off()
        led_green.off()
        buzzer.off()
        print(f"\n{GRN}SHUTDOWN COMPLETE.{RST}")

if __name__ == "__main__":
    main()
