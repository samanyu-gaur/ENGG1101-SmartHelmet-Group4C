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
PIN_LED_RED = 17
PIN_LED_GRN = 27
PIN_LED_BLU = 22
PIN_TOUCH = 24

THRESH_LUX = 150    # REQUIREMENT: Lux > 150 for removal
THRESH_FALL = 2.5   # REQUIREMENT: G-Force > 3.0g
DELAY_REMOVAL = 5.0

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
state = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "warning_start": None,
    "status": "MONITORING",
    "countdown": 5.0
}

# --- Hardware Setup ---
def init_hw():
    try:
        # BH1750 Wakeup
        bus.write_byte(ADDR_BH, 0x01) # Power On
        bus.write_byte(ADDR_BH, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(ADDR_BH, 0x10) # Continuous H-Res Mode
        
        # MPU6050 Wakeup
        bus.write_byte_data(ADDR_MPU, 0x6B, 0x00)
        return True
    except:
        return False

buzzer = PWMOutputDevice(PIN_BUZZER)
led_red = LED(PIN_LED_RED)
led_green = LED(PIN_LED_GRN)
led_blue = LED(PIN_LED_BLU)
touch_sensor = Button(PIN_TOUCH, pull_up=False)


def set_leds(r, g, b):
    """便捷控制LED组合"""
    if r: led_red.on() 
    else: led_red.off()
    if g: led_green.on() 
    else: led_green.off()
    if b: led_blue.on() 
    else: led_blue.off()


def get_sensors():
    """Robust sensor polling with i2c_msg for BH1750 consistency."""
    try:
        # BH1750 Lux
        msg = i2c_msg.read(ADDR_BH, 2)
        bus.i2c_rdwr(msg)
        l_data = list(msg)
        lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
        # MPU6050 Accel
        a_data = bus.read_i2c_block_data(ADDR_MPU, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(a_data[0], a_data[1]) / 16384.0
        ay = rw(a_data[2], a_data[3]) / 16384.0
        az = rw(a_data[4], a_data[5]) / 16384.0
        accel = math.sqrt(ax**2 + ay**2 + az**2)
        
        return lux, accel
    except Exception as e:
        # Graceful handling of I2C Remote I/O Errors
        return state["lux"], state["accel"]

def render_ui():
    """Non-scrolling High-Performance TUI."""
    print(CLR, end="")
    print(f"{BLD}{CYN}[ GROUP 4C - SMART HELMET SAFETY MONITOR ]{RST}\n")

    # Metrics Display
    lux_alert = f" {RED}{BLD}[ WARNING: HELMET REMOVED ]{RST}" if state["lux"] > THRESH_LUX else ""
    accel_alert = f" {RED}{BLD}[ !! FALL DETECTED !! ]{RST}" if state["accel"] > THRESH_FALL else ""
    
    print(f" {BLD}LUX:    {RST}{state['lux']:>8.1f}{lux_alert}")
    print(f" {BLD}G-FORCE:{RST}{state['accel']:>8.2f}g{accel_alert}")
    
    touch_str = f"{GRN}ACTIVE{RST}" if touch_sensor.is_pressed else f"{BLU}INACTIVE{RST}"
    print(f" {BLD}TOUCH:  {RST}{touch_str}")

    # Timer Logic Display
    if state["lux"] > THRESH_LUX and not state["alarm"]:
        print(f" {BLD}TIMER:  {YLW}{state['countdown']:.1f}s{RST}")
    else:
        print(f" {BLD}TIMER:  {RST}---")

    # System Message Box
    print(f"\n{BLU}───────────────────────────────────────────────────────{RST}")
    status_color = RED if state["alarm"] else (YLW if state["lux"] > THRESH_LUX else GRN)
    print(f" STATUS: {status_color}{BLD}{state['status'].upper()}{RST}")
    print(f"{BLU}───────────────────────────────────────────────────────{RST}")
    
    print(f"\n {BLD}CLOCK:  {RST}{datetime.now().strftime('%H:%M:%S')}")

def main():
    if not init_hw():
        print("CRITICAL: I2C Sensors not detected.")
        return

    try:
        while True:
            lux, accel = get_sensors()
            touch = touch_sensor.is_pressed
            now = time.time()
            
            state["lux"] = lux
            state["accel"] = accel

            # --- Logic Engine ---
            
            # 1. Reset / Neutral Conditions (Requirement: Instant Reset)
            if lux < THRESH_LUX or touch:
                state["warning"] = False
                state["warning_start"] = None
                state["countdown"] = 5.0
                if touch: # Manual silence
                    state["alarm"] = False
                    state["status"] = "MONITORING"

            # 2. Alarm Escalation
            if not state["alarm"]:
                # Immediate Fall Alarm
                if accel > THRESH_FALL:
                    state["alarm"] = True
                    state["status"] = "ALARM: CRITICAL FALL"
                
                # Removal Alarm (5s Countdown)
                elif lux > THRESH_LUX:
                    if not state["warning"]:
                        state["warning"] = True
                        state["warning_start"] = now
                        state["status"] = "WARNING: REMOVAL"
                    
                    elapsed = now - state["warning_start"]
                    state["countdown"] = max(0, DELAY_REMOVAL - elapsed)
                    
                    if elapsed > DELAY_REMOVAL:
                        if not touch: # Trigger if not cleared
                            state["alarm"] = True
                            state["status"] = "ALARM: HELMET DISCARDED"

            # --- Hardware Drive ---
            if state["alarm"]:
                # 状态1：紧急警报 (红灯闪烁 + 高频变调)
                led_green.off()
                led_blue.off()
                led_red.value = int(time.time() * 10) % 2  # 极快闪烁
                
                # 蜂鸣器：高频变调 (880Hz - 1200Hz 循环)
                freq = 880 + (math.sin(time.time() * 10) * 200)
                buzzer.frequency = freq
                buzzer.value = 0.5 

            elif state["lux"] > THRESH_LUX:
                # 状态2：移除警告 (蓝灯闪烁 + 低频间歇音)
                led_green.off()
                led_red.off()
                led_blue.value = int(time.time() * 2) % 2 # 慢闪
                
                # 蜂鸣器：440Hz 间歇短促音
                buzzer.frequency = 440
                buzzer.value = 0.2 if int(time.time() * 4) % 2 else 0
                
            else:
                # 状态3：正常运行 (常亮绿灯)
                led_green.on()
                led_red.off()
                led_blue.off()
                buzzer.off()

            render_ui()
            time.sleep(0.1)

    except KeyboardInterrupt:
        led_red.off()
        led_green.off()
        buzzer.off()
        print(f"\n{GRN}SYSTEM SHUTDOWN CLEANLY.{RST}")

if __name__ == "__main__":
    main()
