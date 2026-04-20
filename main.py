import time
import math
import os
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

# --- ANSI UI Codes ---
CLR = "\033[H\033[J"
RST = "\033[0m"
BLD = "\033[1m"
RED = "\033[91m"
GRN = "\033[92m"
YLW = "\033[93m"
CYN = "\033[96m"

# --- Hardware Initialization ---
bus = SMBus(I2C_BUS)
def init_hw():
    try:
        bus.write_byte(ADDR_BH, 0x01) # Power On
        bus.write_byte(ADDR_BH, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(ADDR_BH, 0x10) # Continuous H-Res
        bus.write_byte_data(ADDR_MPU, 0x6B, 0x00) # Wake MPU
        return True
    except: return False

buzzer = PWMOutputDevice(PIN_BUZZER)
led_red = LED(PIN_LED_RED)
led_grn = LED(PIN_LED_GRN)
touch_sensor = Button(PIN_TOUCH, pull_up=False)

# --- State Variables ---
removal_timer = None
alarm_active = False
current_lux = 0.0
current_accel = 1.0

def get_data():
    global current_lux, current_accel
    try:
        # Read Lux
        l_data = bus.read_i2c_block_data(ADDR_BH, 0x10, 2)
        current_lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
        # Read Accel
        a_data = bus.read_i2c_block_data(ADDR_MPU, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(a_data[0], a_data[1]) / 16384.0
        ay = rw(a_data[2], a_data[3]) / 16384.0
        az = rw(a_data[4], a_data[5]) / 16384.0
        current_accel = math.sqrt(ax**2 + ay**2 + az**2)
    except: pass

def main():
    global removal_timer, alarm_active, current_lux, current_accel
    init_hw()
    
    try:
        while True:
            get_data()
            touch = touch_sensor.is_pressed
            
            # --- Timing & Safety Logic ---
            # 1. Fall Detection (Immediate)
            if current_accel > THRESH_FALL:
                alarm_active = True

            # 2. Removal Logic
            if current_lux > THRESH_LUX:
                if removal_timer is None:
                    removal_timer = time.time()
                elif time.time() - removal_timer > DELAY_REMOVAL:
                    alarm_active = True
            
            # 3. Reset Logic (Lux OK or Touch Pressed)
            if current_lux <= THRESH_LUX or touch:
                if touch or not alarm_active:
                    removal_timer = None
                    if touch: alarm_active = False

            # --- Hardware Feedback ---
            if alarm_active:
                led_grn.off()
                led_red.on()
                buzzer.value = 0.5 # Siren
            elif removal_timer is not None:
                led_grn.off()
                led_red.value = int(time.time() * 4) % 2 # Warning Blink
                buzzer.off()
            else:
                led_grn.on()
                led_red.off()
                buzzer.off()

            # --- Static UI ---
            status = f"{RED}{BLD}ALARM{RST}" if alarm_active else \
                     (f"{YLW}{BLD}COUNTDOWN{RST}" if removal_timer else f"{GRN}{BLD}SAFE{RST}")
            
            timer_val = max(0, DELAY_REMOVAL - (time.time() - removal_timer)) if removal_timer else 0.0

            print(f"{CLR}{CYN}{BLD}========================================{RST}")
            print(f"{CYN}{BLD}      SMART HELMET MONITORING v4.2      {RST}")
            print(f"{CYN}{BLD}========================================{RST}\n")
            
            print(f" {BLD}HELMET STATUS:{RST}  {status}")
            print(f" {BLD}LUX LEVEL:    {RST}  {current_lux:>6.1f} lx")
            print(f" {BLD}G-FORCE:      {RST}  {current_accel:>6.2f} g")
            
            if removal_timer and not alarm_active:
                print(f" {BLD}TIMER:        {RST}  {YLW}{timer_val:.1f}s remaining{RST}")
            else:
                print(f" {BLD}TIMER:        {RST}  --")

            print(f"\n{CYN}----------------------------------------{RST}")
            if alarm_active:
                print(f"{RED}{BLD} !! CRITICAL ALERT: ACTION REQUIRED !! {RST}")
                print(f" Press Touch Sensor to Reset System")
            else:
                print(f"{GRN} System operating within safe limits.{RST}")

            time.sleep(0.1)

    except KeyboardInterrupt:
        led_red.off()
        led_grn.off()
        buzzer.off()
        print(f"\n{RST}System Shutdown.")

if __name__ == "__main__":
    main()
