import time
import math
import os
from datetime import datetime
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

# --- ANSI UI Constants ---
CLR = "\033[H\033[J"
RST = "\033[0m"
BLD = "\033[1m"
RED = "\033[91m"
GRN = "\033[92m"
YLW = "\033[93m"
CYN = "\033[96m"
BLU = "\033[94m"

# --- Hardware Initialization ---
bus = SMBus(I2C_BUS)

def init_hw():
    try:
        # BH1750 Wakeup
        bus.write_byte(ADDR_BH, 0x01) # Power On
        bus.write_byte(ADDR_BH, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(ADDR_BH, 0x10) # Continuous H-Res
        
        # MPU6050 Wakeup
        bus.write_byte_data(ADDR_MPU, 0x6B, 0x00)
        return True
    except:
        return False

buzzer = PWMOutputDevice(PIN_BUZZER)
led_red = LED(PIN_LED_RED)
led_grn = LED(PIN_LED_GRN)
touch_sensor = Button(PIN_TOUCH, pull_up=False)

# --- State Management ---
state = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "warning_start": None,
    "status": "MONITORING",
    "countdown": 5.0
}

def get_data():
    try:
        # Lux (Raw i2c_msg to prevent measurement reset)
        msg = i2c_msg.read(ADDR_BH, 2)
        bus.i2c_rdwr(msg)
        l_data = list(msg)
        lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
        # G-Force
        a_data = bus.read_i2c_block_data(ADDR_MPU, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(a_data[0], a_data[1]) / 16384.0
        ay = rw(a_data[2], a_data[3]) / 16384.0
        az = rw(a_data[4], a_data[5]) / 16384.0
        accel = math.sqrt(ax**2 + ay**2 + az**2)
        
        return lux, accel
    except:
        return state["lux"], state["accel"]

def draw_ui():
    print(CLR, end="")
    print(f"{BLD}{CYN}┌──────────────────────────────────────────────┐{RST}")
    print(f"{BLD}{CYN}│        SMART HELMET SAFETY SYSTEM            │{RST}")
    print(f"{BLD}{CYN}└──────────────────────────────────────────────┘{RST}\n")

    # Status Row
    status_color = RED if state["alarm"] else (YLW if state["warning"] else GRN)
    print(f" {BLD}SYSTEM STATE:{RST} {status_color}{BLD}[ {state['status']} ]{RST}\n")

    # Metrics
    print(f" {BLD}LIGHT LEVEL:  {RST}{state['lux']:>7.1f} Lux")
    print(f" {BLD}G-FORCE:      {RST}{state['accel']:>7.2f} g")
    print(f" {BLD}TOUCH STATE:  {RST}{'PRESSED' if touch_sensor.is_pressed else 'RELEASED'}\n")

    # Logic Warnings
    print(f"{BLU}────────────────────────────────────────────────{RST}")
    if state["warning"] and not state["alarm"]:
        print(f" {RED}{BLD}!! ALARM IN: [ {state['countdown']:.1f} ] SECONDS !!{RST}")
    elif state["alarm"]:
        print(f" {RED}{BLD}!! CRITICAL ALERT: PRESS TOUCH TO RESET !!{RST}")
    else:
        print(f" {GRN}SYSTEM SECURE - ALL SENSORS NOMINAL{RST}")
    print(f"{BLU}────────────────────────────────────────────────{RST}")
    
    # Timestamp
    print(f"\n {BLD}CLOCK:{RST} {datetime.now().strftime('%H:%M:%S')}")

def main():
    if not init_hw():
        print("Hardware Failure: Check I2C Wiring")
        return

    try:
        while True:
            lux, accel = get_data()
            touch = touch_sensor.is_pressed
            now = time.time()
            
            state["lux"] = lux
            state["accel"] = accel

            # 1. Reset Logic
            if touch:
                state["alarm"] = False
                state["warning"] = False
                state["warning_start"] = None
                state["status"] = "MONITORING"
                state["countdown"] = 5.0

            # 2. Safety Logic
            if not state["alarm"]:
                # Fall Detection
                if accel > THRESH_FALL:
                    state["alarm"] = True
                    state["status"] = "FALL DETECTED"
                
                # Removal Logic
                elif lux > THRESH_LUX:
                    if not state["warning"]:
                        state["warning"] = True
                        state["warning_start"] = now
                        state["status"] = "HELMET REMOVED"
                    
                    elapsed = now - state["warning_start"]
                    state["countdown"] = max(0, DELAY_REMOVAL - elapsed)
                    
                    if elapsed > DELAY_REMOVAL:
                        if not touch:
                            state["alarm"] = True
                            state["status"] = "REMOVAL ALARM"
                else:
                    state["warning"] = False
                    state["warning_start"] = None
                    if not state["alarm"]: state["status"] = "MONITORING"

            # 3. Hardware Output
            if state["alarm"]:
                led_grn.off()
                led_red.on()
                buzzer.value = 0.5 if int(time.time() * 8) % 2 else 0 # High-freq siren
            elif state["warning"]:
                led_grn.off()
                led_red.value = int(time.time() * 4) % 2 # Warning pulse
                buzzer.off()
            else:
                led_grn.on()
                led_red.off()
                buzzer.off()

            draw_ui()
            time.sleep(0.1)

    except KeyboardInterrupt:
        led_red.off()
        led_grn.off()
        buzzer.off()
        print(f"\n{GRN}Shutdown Successful.{RST}")

if __name__ == "__main__":
    main()
