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

# --- ANSI UI Codes ---
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
removal_warning = False
warning_start_time = None
last_lux = 0.0
last_accel = 1.0
status_msg = "MONITORING ACTIVE"

def init_sensors():
    """Requirement 1: BH1750 Wake Up Protocol"""
    try:
        # BH1750 initialization sequence
        bus.write_byte(BH_ADDR, 0x01) # Power On
        bus.write_byte(BH_ADDR, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x10) # Continuous H-Res Mode
        
        # MPU6050 Wake Up
        bus.write_byte_data(MPU_ADDR, 0x6B, 0x00)
        return True
    except:
        return False

# Hardware Setup
buzzer = PWMOutputDevice(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

def get_data():
    """Requirement 1: Robust data reading with recovery"""
    global last_lux, last_accel
    try:
        # Read BH1750
        l_data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
        lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
        # Read MPU6050
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
        # Mid-loop re-initialization if I2C fails
        init_sensors()
        return last_lux, last_accel

def draw_dashboard():
    """Requirement 2: High-End Terminal UI"""
    print(CLR, end="")
    print(f"{BLD}{CYN}╔══════════════════════════════════════════════════════╗{RST}")
    print(f"{BLD}{CYN}║       GROUP 4C - SMART HELMET COMMAND CENTER         ║{RST}")
    print(f"{BLD}{CYN}╚══════════════════════════════════════════════════════╝{RST}\n")

    # Status Bar
    status_color = RED if alarm_active else (YLW if removal_warning else GRN)
    print(f"{BLD} SYSTEM STATUS: {status_color}{status_msg.upper()}{RST}\n")

    # Sensor Rows
    lux_color = YLW if last_lux > LUX_THRESHOLD else GRN
    lux_label = f" {RED}{BLD}[REMOVAL DETECTED]{RST}" if last_lux > LUX_THRESHOLD else ""
    print(f"{BLD} >   LIGHT LEVEL: {lux_color}{last_lux:>8.1f} Lux{RST} {lux_label}")

    accel_color = RED if last_accel > FALL_THRESHOLD else GRN
    accel_label = f" {RED}{BLD}[FALL DETECTED]{RST}" if last_accel > FALL_THRESHOLD else ""
    print(f"{BLD} >   MOTION LOAD: {accel_color}{last_accel:>8.2f} g  {RST} {accel_label}\n")

    # Logic & Timers
    print(f"{BLU}────────────────────────────────────────────────────────{RST}")
    if removal_warning and not alarm_active:
        elapsed = time.time() - warning_start_time
        remaining = max(0, REMOVAL_DELAY - elapsed)
        # Visual countdown
        bar = "█" * int(remaining * 4)
        print(f"{YLW}{BLD} [TIMER] ALARM TRIGGER IN: {remaining:.1f}s {RST}")
        print(f"{YLW} [{bar:<20}]{RST}")
    elif alarm_active:
        print(f"{RED}{BLD} [ALERT] CRITICAL ALARM ACTIVE - CHECK OPERATOR{RST}")
        print(f"{RED} [ACTION] PRESS TOUCH SENSOR TO HARD RESET{RST}")
    else:
        print(f"{GRN} [SYSTEM] OPERATING NOMINALLY - ALL SYSTEMS GO{RST}")
    print(f"{BLU}────────────────────────────────────────────────────────{RST}")
    
    # Footer
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n {BLD}{CYN}LOGGED AT: {ts}{RST}")

def main():
    global alarm_active, removal_warning, warning_start_time, status_msg
    if not init_sensors():
        print("Initialization failed. Check I2C wiring.")
        return

    try:
        while True:
            lux, accel = get_data()
            touch = touch_sensor.is_pressed

            # Requirement 3: Reset Logic
            if touch:
                alarm_active = False
                removal_warning = False
                warning_start_time = None
                status_msg = "MONITORING ACTIVE"

            # Requirement 3: Safety Logic
            if not alarm_active:
                # Fall Detection (Immediate)
                if accel > FALL_THRESHOLD:
                    alarm_active = True
                    status_msg = "ALARM: CRITICAL IMPACT"
                
                # Removal Detection (5s Timer)
                elif lux > LUX_THRESHOLD:
                    if not removal_warning:
                        removal_warning = True
                        warning_start_time = time.time()
                        status_msg = "WARNING: HELMET REMOVED"
                    elif time.time() - warning_start_time > REMOVAL_DELAY:
                        if not touch: # Trigger if not reset
                            alarm_active = True
                            status_msg = "ALARM: UNAUTHORIZED REMOVAL"
                else:
                    removal_warning = False
                    if not alarm_active: status_msg = "MONITORING ACTIVE"

            # Requirement 3: Hardware Output
            if alarm_active:
                led_green.off()
                led_red.on()
                # Siren Effect
                buzzer.value = 0.5 if int(time.time() * 6) % 2 else 0
            elif removal_warning:
                led_green.off()
                # Warning Flash
                led_red.value = 1 if int(time.time() * 4) % 2 else 0
                buzzer.off()
            else:
                led_green.on()
                led_red.off()
                buzzer.off()

            draw_dashboard()
            time.sleep(0.1) # Requirement 4: CPU efficiency

    except KeyboardInterrupt:
        led_red.off()
        led_green.off()
        buzzer.off()
        print(f"\n{GRN}Shutdown successful.{RST}")

if __name__ == "__main__":
    main()
