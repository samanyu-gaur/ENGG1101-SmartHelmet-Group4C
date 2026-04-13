import time
import math
import smbus2
import numpy as np
from gpiozero import Button, LED, TonalBuzzer
from gpiozero.tones import Tone

class SmartHelmet:
    # I2C Addresses
    MPU_ADDR, BH_ADDR = 0x68, 0x23
    
    # GPIO Pins (BCM)
    BUZZER_PIN = 12 # Passive Buzzer (PWM)
    RED_LED_PIN = 27
    GREEN_LED_PIN = 17
    TOUCH_PIN = 24
    
    # Thresholds
    LUX_THRESH = 50 # v2.7 Update
    REMOVAL_DELAY = 2.0
    FREEFALL_THRESH, IMPACT_THRESH = 0.5, 3.0
    STATIONARY_VAR_THRESH = 0.05
    SOS_HOLD_TIME = 3.0
    STAGNANT_LIMIT = 20

    def __init__(self, bus_num=1):
        self.bus_num = bus_num
        self.bus = None
        self.init_bus()
        
        # Initialize gpiozero components
        self.touch_sensor = Button(self.TOUCH_PIN, pull_up=False)
        self.red_led = LED(self.RED_LED_PIN)
        self.green_led = LED(self.GREEN_LED_PIN)
        
        # Passive Buzzer initialization (TonalBuzzer for frequency control)
        try:
            self.buzzer = TonalBuzzer(self.BUZZER_PIN)
        except Exception as e:
            print(f"Buzzer Init Error: {e}. Falling back to standard output.")
            self.buzzer = None

        # State Tracking
        self.last_lux = -1
        self.stagnant_count = 0
        self.removal_start = None
        self.is_fall_alarm = False
        self.is_sos_alarm = False
        self.is_removal_alarm = False
        
        self.setup_sensors()
        
        # Event-driven Reset
        self.touch_sensor.when_pressed = self.reset_from_touch

    def init_bus(self):
        try:
            if self.bus: self.bus.close()
            self.bus = smbus2.SMBus(self.bus_num)
        except Exception as e:
            print(f"I2C Bus Error: {e}")

    def setup_sensors(self):
        """v2.7 Initialization with Mode 2 and stabilization."""
        try:
            self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0) # Wake MPU
            self.bus.write_byte(self.BH_ADDR, 0x01) # Power On BH
            time.sleep(0.18)
            self.bus.write_byte(self.BH_ADDR, 0x07) # Reset BH
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x11) # Mode 2
            time.sleep(0.1)
        except:
            self.init_bus()

    def get_lux(self):
        """Read lux with stagnation check."""
        try:
            self.bus.write_byte(self.BH_ADDR, 0x11)
            time.sleep(0.2)
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x11, 2)
            lux = ((data[0] << 8) | data[1]) / 1.2
            
            if lux == self.last_lux: self.stagnant_count += 1
            else: self.stagnant_count = 0; self.last_lux = lux
            
            if self.stagnant_count >= self.STAGNANT_LIMIT:
                self.bus.write_byte(self.BH_ADDR, 0x11)
                self.stagnant_count = 0
            return lux
        except: return self.last_lux if self.last_lux != -1 else 0

    def get_accel(self):
        try:
            d = self.bus.read_i2c_block_data(self.MPU_ADDR, 0x3B, 6)
            def rw(h, l):
                v = (h << 8) + l
                return v - 65536 if v >= 0x8000 else v
            return rw(d[0], d[1])/16384.0, rw(d[2], d[3])/16384.0, rw(d[4], d[5])/16384.0
        except: return 0, 0, 0

    def reset_from_touch(self):
        if self.is_fall_alarm or self.is_sos_alarm or self.is_removal_alarm:
            print("\n[RESET] Touch detected. Returning to NORMAL state.")
            self.reset_alarms()

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        self.removal_start = None
        if self.buzzer: self.buzzer.stop()
        self.red_led.off()
        self.green_led.on()

    def update_indicators(self):
        """v2.7 RGB LED and Passive Buzzer logic."""
        t = time.time()
        
        # 1. CRITICAL STATE (Fall / SOS)
        if self.is_fall_alarm or self.is_sos_alarm:
            self.green_led.off()
            self.red_led.on()
            if self.buzzer:
                # Siren effect: Alternate between 880Hz and 1000Hz
                freq = 880 if int(t * 5) % 2 else 1000
                self.buzzer.play(Tone(freq))
        
        # 2. WARNING STATE (Helmet Removed)
        elif self.is_removal_alarm:
            self.green_led.off()
            # Blinking Red
            self.red_led.value = int(t * 2) % 2
            if self.buzzer:
                # Slow chirp: 440Hz pulse
                if int(t * 2) % 2:
                    self.buzzer.play(Tone(440))
                else:
                    self.buzzer.stop()
        
        # 3. NORMAL STATE
        else:
            self.red_led.off()
            self.green_led.on()
            if self.buzzer: self.buzzer.stop()

    def run_iteration(self):
        lux = self.get_lux()
        ax, ay, az = self.get_accel()
        at = math.sqrt(ax**2 + ay**2 + az**2)
        
        # Logic: Removal
        if lux > self.LUX_THRESH:
            if not self.removal_start: self.removal_start = time.time()
            elif time.time() - self.removal_start > self.REMOVAL_DELAY:
                self.is_removal_alarm = True
        else:
            self.removal_start = None
            if not (self.is_fall_alarm or self.is_sos_alarm): self.is_removal_alarm = False

        # Logic: Fall Detection
        if at < self.FREEFALL_THRESH and not self.is_fall_alarm:
            time.sleep(0.05)
            ix, iy, iz = self.get_accel()
            it = math.sqrt(ix**2 + iy**2 + iz**2)
            if it > self.IMPACT_THRESH:
                print(f"\n[FALL] Impact {it:.2f}g. Checking immobility...")
                time.sleep(3)
                samples = [math.sqrt(sum(x**2 for x in self.get_accel())) for _ in range(10)]
                if np.var(samples) < self.STATIONARY_VAR_THRESH:
                    self.is_fall_alarm = True

        self.update_indicators()
        
        state = "SAFE" if not (self.is_fall_alarm or self.is_removal_alarm or self.is_sos_alarm) else "ALARM"
        print(f"[{state}] Lux: {lux:6.1f} | G: {at:4.2f} | Touch: {int(self.touch_sensor.value)}", end='\r')

def main():
    print("--- Smart Helmet v2.7 (RGB & Passive Buzzer Fix) ---")
    helmet = SmartHelmet()
    print("System Online. Press Ctrl+C to exit.")
    try:
        while True:
            start = time.time()
            helmet.run_iteration()
            elapsed = time.time() - start
            time.sleep(max(0, 0.02 - elapsed))
    except KeyboardInterrupt:
        print("\nShutdown.")
    finally:
        helmet.reset_alarms()

if __name__ == "__main__": main()
