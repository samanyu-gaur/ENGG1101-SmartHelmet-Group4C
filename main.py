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

# --- ANSI Cyberpunk Styling ---
CLR = "\033[H\033[J"
RST = "\033[0m"
BLD = "\033[1m"
RED = "\033[31m"
GRN = "\033[32m"
YLW = "\033[33m"
BLU = "\033[34m"
MAG = "\033[35m"
CYN = "\033[36m"
BG_BLU = "\033[44m"

# --- Global State ---
state = {
    "lux": 0.0,
    "accel": 1.0,
    "alarm": False,
    "warning": False,
    "status": "SYSTEM NOMINAL",
    "warning_start": None,
    "logs": ["- SYSTEM BOOT INITIALIZED", "- WAITING FOR SENSORS", "- READY"],
    "glitch": False
}

# --- Hardware Initialization ---
bus = SMBus(I2C_BUS)

def kickstart_sensors():
    try:
        # BH1750 Kickstart (Power Down -> Power On -> Reset)
        bus.write_byte(BH_ADDR, 0x00) # Power Down
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x01) # Power On
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x07) # Reset
        time.sleep(0.1)
        bus.write_byte(BH_ADDR, 0x10) # Continuous High Res Mode
        
        # MPU6050 Wake
        bus.write_byte_data(MPU_ADDR, 0x6B, 0x00)
        return True
    except:
        return False

buzzer = PWMOutputDevice(BUZZER_PIN)
led_red = LED(RED_LED_PIN)
led_green = LED(GREEN_LED_PIN)
touch_sensor = Button(TOUCH_PIN, pull_up=False)

def get_sensor_data():
    try:
        # Lux
        l_data = bus.read_i2c_block_data(BH_ADDR, 0x10, 2)
        lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
        # Accel (G-Force)
        a_data = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 6)
        def rw(h, l):
            v = (h << 8) | l
            return v - 65536 if v >= 32768 else v
        ax = rw(a_data[0], a_data[1]) / 16384.0
        ay = rw(a_data[2], a_data[3]) / 16384.0
        az = rw(a_data[4], a_data[5]) / 16384.0
        accel = math.sqrt(ax**2 + ay**2 + az**2)
        
        return lux, accel, False
    except:
        return 0.0, 1.0, True

def add_log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    state["logs"].append(f"- [{ts}] {msg}")
    if len(state["logs"]) > 3:
        state["logs"].pop(0)

def draw_ui():
    # Header
    print(CLR, end="")
    print(f"{BLD}{BG_BLU}{' ' * 60}{RST}")
    print(f"{BLD}{BG_BLU}  HKU ENGG1101 - SMART HELMET SYSTEM - GROUP 4C        {RST}")
    print(f"{BLD}{BG_BLU}{' ' * 60}{RST}\n")

    # Status Bar
    status_color = RED if state["alarm"] else (YLW if state["warning"] else GRN)
    print(f"{BLD}SYSTEM STATE:{RST} {status_color}{BLD}{state['status']}{RST}")
    print(f"{BLU}------------------------------------------------------------{RST}")

    # Telemetry
    lux_color = YLW if state["warning"] else (RED if state["lux"] > LUX_THRESHOLD else GRN)
    accel_color = RED if state["accel"] > FALL_THRESHOLD else GRN
    
    if state["glitch"]:
        print(f"{RED}{BLD}!! SENSOR GLITCH - RETRYING HARDWARE BUS !!{RST}")
    else:
        print(f"{BLD}AMBIENT LIGHT:{RST} {lux_color}{state['lux']:>8.1f} Lux{RST}  (Limit: {LUX_THRESHOLD})")
        print(f"{BLD}RESULTANT G:  {RST} {accel_color}{state['accel']:>8.2f} g  {RST}  (Limit: {FALL_THRESHOLD})")

    # Warnings / Timers
    print(f"{BLU}------------------------------------------------------------{RST}")
    if state["warning"] and not state["alarm"]:
        rem = max(0, REMOVAL_DELAY - (time.time() - state["warning_start"]))
        print(f"{YLW}{BLD}>> REMOVAL WARNING: {rem:.1f}s UNTIL ALARM <<{RST}")
    elif state["alarm"]:
        print(f"{RED}{BLD}>> ALARM ACTIVE: PRESS TOUCH SENSOR TO CLEAR <<{RST}")
    else:
        print(f"{GRN}HELMET SECURE - MONITORING ACTIVE{RST}")

    # Logs
    print(f"\n{BLD}{CYN}EVENT LOG (RECENT 3):{RST}")
    for log in state["logs"]:
        print(f"{CYN}{log}{RST}")
    print(f"{BLU}------------------------------------------------------------{RST}")

def main():
    if not kickstart_sensors():
        print("CRITICAL: Failed to kickstart I2C bus.")
        return

    try:
        while True:
            lux, accel, glitch = get_sensor_data()
            touch = touch_sensor.is_pressed
            state["lux"] = lux
            state["accel"] = accel
            state["glitch"] = glitch

            # Reset Logic
            if touch:
                if state["alarm"] or state["warning"]:
                    add_log("MANUAL RESET DETECTED")
                state["alarm"] = False
                state["warning"] = False
                state["warning_start"] = None
                state["status"] = "SYSTEM NOMINAL"

            # Safety Logic
            if not state["alarm"]:
                if accel > FALL_THRESHOLD:
                    state["alarm"] = True
                    state["status"] = "FALL DETECTED!"
                    add_log(f"FALL IMPACT: {accel:.2f}g")
                elif lux > LUX_THRESHOLD:
                    if not state["warning"]:
                        state["warning"] = True
                        state["warning_start"] = time.time()
                        state["status"] = "HELMET REMOVAL DETECTED"
                        add_log("REMOVAL WARNING TRIGGERED")
                    elif time.time() - state["warning_start"] > REMOVAL_DELAY:
                        if not touch:
                            state["alarm"] = True
                            state["status"] = "ALARM: UNAUTHORIZED REMOVAL"
                            add_log("ALARM: 5S GRACE PERIOD EXPIRED")
                else:
                    state["warning"] = False
                    state["warning_start"] = None
                    if not state["alarm"]:
                        state["status"] = "SYSTEM NOMINAL"

            # Hardware Output
            if state["alarm"]:
                led_green.off()
                led_red.on()
                if state["status"].startswith("FALL"):
                    buzzer.value = 0.5 # Constant Siren
                else:
                    buzzer.value = 0.5 if int(time.time() * 5) % 2 else 0 # Fast Pulse
            elif state["warning"]:
                led_green.off()
                if int(time.time() * 4) % 2: led_red.on()
                else: led_red.off()
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
