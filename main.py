import time
import math
import sys
from datetime import datetime
from smbus2 import SMBus, i2c_msg
from gpiozero import PWMOutputDevice, LED, Button

# --- Configuration ---
I2C_BUS = 1
ADDR_BH = 0x23
ADDR_MPU = 0x68

PIN_BUZZER = 12
PIN_LED_RED = 27
PIN_TOUCH = 24

THRESH_LUX = 50
THRESH_FALL = 3.0
DELAY_REMOVAL = 5.0

# --- ANSI UI Constants ---
CLR = "\033[H\033[J"
RST = "\033[0m"
BLD = "\033[1m"
DIM = "\033[2m"
INV = "\033[7m"
BLINK = "\033[5m"

BRED = "\033[91m"
BGRN = "\033[92m"
BYLW = "\033[93m"
BBLU = "\033[94m"
BMAG = "\033[95m"
BCYN = "\033[96m"

# --- Globals and Hardware Init ---
try:
    bus = SMBus(I2C_BUS)
except:
    bus = None

def init_hw():
    if bus:
        try:
            # Wake up BH1750
            bus.write_byte(ADDR_BH, 0x01)
            bus.write_byte(ADDR_BH, 0x07)
            time.sleep(0.1)
            bus.write_byte(ADDR_BH, 0x10)
            # Wake up MPU6050
            bus.write_byte_data(ADDR_MPU, 0x6B, 0x00)
            return True
        except:
            return False
    return False

try:
    buzzer = PWMOutputDevice(PIN_BUZZER)
    led_red = LED(PIN_LED_RED)
    touch_sensor = Button(PIN_TOUCH, pull_up=False)
except:
    buzzer, led_red, touch_sensor = None, None, None

def get_sensors():
    if bus is None: return 0.0, 1.0
    try:
        msg = i2c_msg.read(ADDR_BH, 2)
        bus.i2c_rdwr(msg)
        l_data = list(msg)
        lux = ((l_data[0] << 8) | l_data[1]) / 1.2
        
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
        return 0.0, 1.0

# --- Display Utilities ---
def draw_bar(val, max_val, color, width=25):
    val = max(0, min(val, max_val))
    filled = int((val / max_val) * width)
    unfilled = width - filled
    return f"{color}{'█' * filled}{RST}{DIM}{'░' * unfilled}{RST}"

def pad_banner(text, width=58):
    pad_l = (width - len(text)) // 2
    pad_r = width - len(text) - pad_l
    return " " * pad_l, " " * pad_r

def render_ui(mode, lux, accel, touch, countdown):
    sys.stdout.write(CLR)
    
    print(f"{BLD}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓{RST}")
    
    title_text = "SMART HELMET TERMINAL HUD"
    p_l, p_r = pad_banner(title_text)
    print(f"{BLD}┃{RST}{p_l}{BLD}{BCYN}{title_text}{RST}{p_r}{BLD}┃{RST}")
    print(f"{BLD}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫{RST}")
    
    if mode == "NORMAL":
        p_l, p_r = pad_banner("[  SYSTEM ARMED  ]")
        banner_str = f"{p_l}{BGRN}[  SYSTEM ARMED  ]{RST}{p_r}"
    elif mode == "REMOVAL_WARN":
        p_l, p_r = pad_banner("[  REMOVAL WARNING  ]")
        banner_str = f"{p_l}{BYLW}{BLINK}[  REMOVAL WARNING  ]{RST}{p_r}"
    elif mode == "INTENTIONAL_OFF":
        p_l, p_r = pad_banner("[  INTENTIONAL OFF  ]")
        banner_str = f"{p_l}{BBLU}{DIM}[  INTENTIONAL OFF  ]{RST}{p_r}"
    elif mode == "ALARM":
        p_l, p_r = pad_banner("[  !!! HELMET REMOVED !!!  ]")
        banner_str = f"{p_l}{BRED}{INV}[  !!! HELMET REMOVED !!!  ]{RST}{p_r}"
    elif mode == "FALL_ALARM":
        p_l, p_r = pad_banner("[  !!! FALL DETECTED !!!  ]")
        banner_str = f"{p_l}{BRED}{INV}[  !!! FALL DETECTED !!!  ]{RST}{p_r}"
        
    print(f"{BLD}┃{RST}{banner_str}{BLD}┃{RST}")
    print(f"{BLD}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫{RST}")
    
    l_bar = draw_bar(lux, 200, BCYN, 25) # Max 200 lux for visual scale
    raw_lux = f"{lux:.1f}lx"
    left_side_lux = f" {BLD}LUX LEVEL:{RST} {raw_lux:>8}  {l_bar}"
    print(f"{BLD}┃{RST}{left_side_lux}{' ' * 11}{BLD}┃{RST}")
    
    a_bar = draw_bar(accel, 5.0, BMAG, 25) # Max 5g for visual scale
    raw_accel = f"{accel:.2f}g"
    left_side_accel = f" {BLD}G-FORCE:  {RST} {raw_accel:>8}  {a_bar}"
    print(f"{BLD}┃{RST}{left_side_accel}{' ' * 11}{BLD}┃{RST}")
    print(f"{BLD}┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫{RST}")
    
    t_text = "PRESSED" if touch else "RELEASED"
    t_col = BGRN if touch else DIM
    left_side_t = f" {BLD}TOUCH SENSOR:{RST} {t_col}{t_text}{RST}"
    pad_t = 58 - (1 + 13 + 1 + len(t_text))
    print(f"{BLD}┃{RST}{left_side_t}{' ' * pad_t}{BLD}┃{RST}")
    
    c_text = f"{countdown:.1f}s" if mode == "REMOVAL_WARN" else "---"
    c_col = BYLW if mode == "REMOVAL_WARN" else DIM
    left_side_c = f" {BLD}COUNTDOWN:   {RST} {c_col}{c_text}{RST}"
    pad_c = 58 - (1 + 13 + 1 + len(c_text))
    print(f"{BLD}┃{RST}{left_side_c}{' ' * pad_c}{BLD}┃{RST}")
    
    print(f"{BLD}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛{RST}")
    sys.stdout.flush()


def main():
    init_hw()
    
    # State Engine Variables
    mode = "NORMAL"
    warn_start = 0
    countdown = 5.0
    
    try:
        while True:
            now = time.time()
            lux, accel = get_sensors()
            touch = touch_sensor.is_pressed if touch_sensor else False
            
            # --- Logic Rules ---
            
            # 1. Fall Detection Overrides (Immediate bypass)
            if accel > THRESH_FALL:
                mode = "FALL_ALARM"

            # 2. Touch Mute logic
            if touch:
                if mode in ["REMOVAL_WARN", "ALARM", "FALL_ALARM"]:
                    mode = "INTENTIONAL_OFF"
                    
            # 3. Rearm Logic (Auto-recover if helmet worn)
            if lux <= THRESH_LUX:
                if mode in ["INTENTIONAL_OFF", "REMOVAL_WARN", "ALARM"]:
                    mode = "NORMAL"
                    countdown = 5.0
                    
            # 4. Removal Warnings
            if mode == "NORMAL" and lux > THRESH_LUX:
                mode = "REMOVAL_WARN"
                warn_start = now
                
            if mode == "REMOVAL_WARN":
                elapsed = now - warn_start
                countdown = max(0, DELAY_REMOVAL - elapsed)
                if countdown == 0:
                    mode = "ALARM"
                    
            # --- Hardware Drive ---
            if buzzer is not None and led_red is not None:
                if mode in ["ALARM", "FALL_ALARM"]:
                    led_red.on()
                    buzzer.value = 0.5 if int(now * 8) % 2 else 0
                elif mode == "REMOVAL_WARN":
                    led_red.value = int(now * 4) % 2
                    buzzer.off()
                else: # INTENTIONAL_OFF or NORMAL
                    led_red.off()
                    buzzer.off()
                    
            # Render to screen
            render_ui(mode, lux, accel, touch, countdown)
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        if led_red: led_red.off()
        if buzzer: buzzer.off()
        print(CLR)
        print(f"{BGRN}System Shutdown Cleanly.{RST}")

if __name__ == "__main__":
    main()
