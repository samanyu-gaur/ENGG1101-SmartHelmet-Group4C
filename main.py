import time
import math
import os
from smbus2 import SMBus
from gpiozero import PWMOutputDevice, Button

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

# --- ANSI Color Codes ---
CLR = "\033[H\033[J"
RED = "\033[91m"
GRN = "\033[92m"
YLW = "\033[93m"
BLU = "\033[94m"
BLD = "\033[1m"
RST = "\033[0m"

# --- Hardware Initialization ---
bus = SMBus(I2C_BUS)
def setup_sensors():
    try:
        bus.write_byte_data(MPU_ADDR, 0x6B, 0x00) # Wake MPU
        bus.write_byte(BH_ADDR, 0x01) # Power BH
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x10) # Continuous High Res
        return True
    except: return False

buzzer = PWMOutputDevice(BUZZER_PIN)
led_red = PWMOutputDevice(RED_LED_PIN)
led_green = PWMOutputDevice(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

# --- State Variables ---
alarm_active = False
warning_active = False
warning_start_time = None
status_msg = "SAFE"
current_lux = 0.0
current_accel = 1.0

def get_data():
    global current_lux, current_accel
    try:
        # Lux
        l_data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
        current_lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        # Accel
        a_data = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(a_data[0], a_data[1]) / 16384.0
        ay = rw(a_data[2], a_data[3]) / 16384.0
        az = rw(a_data[4], a_data[5]) / 16384.0
        current_accel = math.sqrt(ax**2 + ay**2 + az**2)
    except: pass

def main():
    global alarm_active, warning_active, warning_start_time, status_msg
    setup_sensors()
    
    print(CLR, end="")
    try:
        while True:
            get_data()
            touch = touch_sensor.is_pressed
            
            # --- Safety Logic ---
            if touch:
                alarm_active = False
                warning_active = False
                warning_start_time = None
                status_msg = "SAFE"

            if not alarm_active:
                if current_accel > FALL_THRESHOLD:
                    alarm_active = True
                    status_msg = "FALL DETECTED!"
                elif current_lux > LUX_THRESHOLD:
                    if not warning_active:
                        warning_active = True
                        warning_start_time = time.time()
                        status_msg = "REMOVAL WARNING"
                    elif time.time() - warning_start_time > REMOVAL_DELAY:
                        if not touch:
                            alarm_active = True
                            status_msg = "ALARM: HELMET REMOVED"
                else:
                    warning_active = False
                    warning_start_time = None
                    if not alarm_active: status_msg = "SAFE"

            # --- Hardware Control ---
            if alarm_active:
                led_green.value = 0
                led_red.value = 1
                buzzer.value = 0.5
                color = RED
            elif warning_active:
                led_green.value = 0
                led_red.value = 1 if int(time.time() * 4) % 2 else 0
                buzzer.value = 0
                color = YLW
            else:
                led_green.value = 1
                led_red.value = 0
                buzzer.value = 0
                color = GRN

            # --- Terminal UI ---
            print(f"{CLR}{BLD}{BLU}========================================{RST}")
            print(f"{BLD}{BLU}   GROUP 4C: SMART HELMET SYSTEM        {RST}")
            print(f"{BLD}{BLU}========================================{RST}\n")
            
            print(f"{BLD}SYSTEM STATUS:{RST} {color}{BLD}{status_msg}{RST}\n")
            
            print(f"{BLD}SENSOR DATA:{RST}")
            print(f"  - LUX LEVEL:  {current_lux:>7.1f} lx")
            print(f"  - G-FORCE:    {current_accel:>7.2f} g\n")
            
            print(f"{BLD}HARDWARE STATE:{RST}")
            bz_str = f"{RED}ACTIVE{RST}" if alarm_active else f"{GRN}OFF{RST}"
            lg_str = f"{GRN}ON{RST}" if not (alarm_active or warning_active) else f"{RED}OFF{RST}"
            lr_str = f"{RED}ON{RST}" if alarm_active or (warning_active and int(time.time()*4)%2) else f"{GRN}OFF{RST}"
            
            print(f"  - BUZZER:     {bz_str}")
            print(f"  - GREEN LED:  {lg_str}")
            print(f"  - RED LED:    {lr_str}\n")
            
            if warning_active and not alarm_active:
                rem = max(0, REMOVAL_DELAY - (time.time() - warning_start_time))
                print(f"{YLW}{BLD}>> TRIGGERING ALARM IN: {rem:.1f}s <<{RST}")
            elif alarm_active:
                print(f"{RED}{BLD}>> PRESS TOUCH SENSOR TO RESET <<{RST}")
            else:
                print(f"{GRN}SYSTEM OPERATING NORMALLY{RST}")

            time.sleep(0.1)
    except KeyboardInterrupt:
        led_red.off()
        led_green.off()
        buzzer.off()
        print(f"\n{RST}System Shutdown.")

if __name__ == "__main__":
    main()
