import time
import math
import smbus2
import numpy as np
from gpiozero import Button, LED, Buzzer

class SmartHelmet:
    # I2C Addresses
    MPU_ADDR, BH_ADDR = 0x68, 0x23
    # GPIO Pins (BCM)
    BUZZER_PIN, LED_PIN, TOUCH_PIN = 18, 27, 24
    # Thresholds
    LUX_THRESH = 30 # v2.5 Updated threshold
    REMOVAL_DELAY = 2.0
    FREEFALL_THRESH, IMPACT_THRESH = 0.5, 3.0
    STATIONARY_VAR_THRESH = 0.05
    SOS_HOLD_TIME = 3.0

    def __init__(self, bus_num=1):
        self.bus_num = bus_num
        self.bus = None
        self.init_bus()
        
        # Initialize gpiozero components
        self.touch_sensor = Button(self.TOUCH_PIN, pull_up=False)
        self.led = LED(self.LED_PIN)
        self.buzzer = Buzzer(self.BUZZER_PIN)

        # State Tracking
        self.last_lux = 0
        self.removal_start = None
        self.is_fall_alarm = False
        self.is_sos_alarm = False
        self.is_removal_alarm = False
        
        self.setup_sensors()
        
        # Event-driven Reset (Handles both Fall and Removal alarms)
        self.touch_sensor.when_pressed = self.reset_from_touch

    def init_bus(self):
        """Initialize or re-initialize the I2C bus."""
        try:
            if self.bus: self.bus.close()
            self.bus = smbus2.SMBus(self.bus_num)
            print(f"I2C Bus {self.bus_num} initialized.")
        except Exception as e:
            print(f"Failed to initialize I2C bus: {e}")

    def setup_sensors(self):
        """v2.5 Robust BH1750 Initialization Sequence."""
        try:
            # Wake up MPU6050
            self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0)
            
            # BH1750 Specific Initialization Sequence
            print("Initializing BH1750 (Robust Mode)...")
            self.bus.write_byte(self.BH_ADDR, 0x01) # 1. Power On
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x07) # 2. Data Reset
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x10) # 3. Continuous High-Res Mode
            
            print("Waiting for BH1750 stabilization (200ms)...")
            time.sleep(0.2) # 4. Wait 200ms before first read
            print("Sensors Online.")
        except Exception as e:
            print(f"Sensor Setup Error: {e}. Attempting bus re-init...")
            self.init_bus()

    def get_lux(self):
        """v2.5 Dynamic reading with last-good-value fallback."""
        try:
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x10, 2)
            lux = (data[0] << 8 | data[1]) / 1.2
            self.last_lux = lux
            return lux
        except Exception as e:
            # Return last known good value if I2C read fails
            return self.last_lux

    def get_accel(self):
        """Read raw acceleration data from MPU6050."""
        try:
            d = self.bus.read_i2c_block_data(self.MPU_ADDR, 0x3B, 6)
            def rw(h, l):
                v = (h << 8) + l
                return v - 65536 if v >= 0x8000 else v
            return rw(d[0], d[1])/16384.0, rw(d[2], d[3])/16384.0, rw(d[4], d[5])/16384.0
        except: return 0, 0, 0

    def reset_from_touch(self):
        """Callback for Touch Sensor Reset."""
        if self.is_fall_alarm or self.is_sos_alarm or self.is_removal_alarm:
            print("\n[RESET] Touch detected. Clearing all alarms.")
            self.reset_alarms()
            self.removal_start = None # Reset removal timer

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        self.led.off(); self.buzzer.off()

    def update_indicators(self):
        """Manage non-blocking indicator patterns."""
        t = time.time()
        if self.is_sos_alarm:
            self.led.value = self.buzzer.value = int(t * 10) % 2
        elif self.is_fall_alarm:
            self.led.on(); self.buzzer.on()
        elif self.is_removal_alarm:
            self.led.value = self.buzzer.value = int(t * 2) % 2
        else:
            self.led.off(); self.buzzer.off()

    def run_iteration(self):
        # 1. Read Sensors
        lux = self.get_lux()
        ax, ay, az = self.get_accel()
        at = math.sqrt(ax**2 + ay**2 + az**2)
        
        # 2. Helmet Removal Logic (v2.5: Lux > 30, continuous for 2s)
        status_msg = "[SAFE]"
        if lux > self.LUX_THRESH:
            if not self.removal_start:
                self.removal_start = time.time()
            elif time.time() - self.removal_start > self.REMOVAL_DELAY:
                self.is_removal_alarm = True
                status_msg = "[WARNING: HELMET REMOVED]"
        else:
            self.removal_start = None
            if not (self.is_fall_alarm or self.is_sos_alarm):
                self.is_removal_alarm = False

        # 3. Fall Detection Logic
        if at < self.FREEFALL_THRESH and not self.is_fall_alarm:
            time.sleep(0.05)
            ix, iy, iz = self.get_accel()
            it = math.sqrt(ix**2 + iy**2 + iz**2)
            if it > self.IMPACT_THRESH:
                print(f"\n[FALL] Impact: {it:.2f}g. Checking immobility...")
                time.sleep(3)
                samples = [math.sqrt(sum(x**2 for x in self.get_accel())) for _ in range(10)]
                if np.var(samples) < self.STATIONARY_VAR_THRESH:
                    self.is_fall_alarm = True
                    print("[FALL] Alarm Active: Worker Immobile.")

        # 4. SOS Logic
        if self.touch_sensor.is_pressed and self.touch_sensor.active_time:
            if self.touch_sensor.active_time > self.SOS_HOLD_TIME and not self.is_sos_alarm:
                self.is_sos_alarm = True
                print("\n[SOS] Manual Emergency Triggered.")

        # 5. Output Update
        self.update_indicators()
        print(f"{status_msg} Lux: {lux:7.2f} | Accel: {at:4.2f}g | Touch: {int(self.touch_sensor.value)}", end='\r')

def main():
    print("--- Smart Helmet v2.5 (Robust Sensor Logic) ---")
    helmet = SmartHelmet()
    print("Looping at 50Hz. Press Ctrl+C to terminate.")
    
    try:
        while True:
            start = time.time()
            helmet.run_iteration()
            
            elapsed = time.time() - start
            time.sleep(max(0, 0.02 - elapsed))
            
    except KeyboardInterrupt:
        print("\n[EXIT] Shutdown initiated.")
    finally:
        try: helmet.reset_alarms()
        except: pass
        print("Cleanup complete.")

if __name__ == "__main__":
    main()
