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
    LUX_THRESH, REMOVAL_DELAY = 20, 2.0
    FREEFALL_THRESH, IMPACT_THRESH = 0.5, 3.0
    STATIONARY_VAR_THRESH = 0.05
    SOS_HOLD_TIME = 3.0
    STAGNANT_LIMIT = 10 # consecutive identical readings before wakeup

    def __init__(self, bus_num=1):
        self.bus_num = bus_num
        self.bus = None
        self.init_bus()
        
        # Initialize gpiozero components
        self.touch_sensor = Button(self.TOUCH_PIN, pull_up=False)
        self.led = LED(self.LED_PIN)
        self.buzzer = Buzzer(self.BUZZER_PIN)

        self.setup_sensors()
        
        # State Tracking
        self.removal_start = None
        self.is_fall_alarm = False
        self.is_sos_alarm = False
        self.is_removal_alarm = False
        
        # Lux Stagnation Tracking
        self.last_lux = -1
        self.stagnant_count = 0
        
        # Event-driven Reset
        self.touch_sensor.when_pressed = self.reset_from_touch

    def init_bus(self):
        """Initialize or re-initialize the I2C bus."""
        try:
            if self.bus:
                self.bus.close()
            self.bus = smbus2.SMBus(self.bus_num)
            print(f"I2C Bus {self.bus_num} initialized.")
        except Exception as e:
            print(f"Failed to initialize I2C bus: {e}")

    def setup_sensors(self):
        """CRITICAL FIX: BH1750 Initialization Sequence."""
        try:
            # Wake up MPU6050
            self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0)
            
            # BH1750 Reset & Continuous Mode Sequence
            self.bus.write_byte(self.BH_ADDR, 0x01) # Power On
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x07) # Reset data register
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x10) # Set to Continuous High-Res Mode
            print("BH1750: PowerOn -> Reset -> ContinuousMode (0x10) sequence complete.")
            
            time.sleep(0.2) # Stabilization delay for integration
        except Exception as e:
            print(f"Sensor Setup Error: {e}. Attempting bus re-init...")
            self.init_bus()

    def get_lux(self, is_moving=False):
        """Read lux data with stagnation detection and auto-wakeup."""
        try:
            # Data Acquisition Delay: wait for sensor to update (integration time ~120ms)
            # This is handled by the 50Hz loop but we ensure a read delay here if needed
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x10, 2)
            lux = (data[0] << 8 | data[1]) / 1.2
            
            # Stagnation Check
            if lux == self.last_lux:
                self.stagnant_count += 1
            else:
                self.stagnant_count = 0
                self.last_lux = lux
                
            # Auto-wakeup: If stagnant for > 10 loops AND movement is detected
            if self.stagnant_count > self.STAGNANT_LIMIT and is_moving:
                # print(f"\n[SENSORS] BH1750 stagnant ({self.stagnant_count}). Sending 0x10 wakeup...")
                self.bus.write_byte(self.BH_ADDR, 0x10)
                self.stagnant_count = 0 # Reset after wakeup attempt
                
            return lux
        except Exception as e:
            # print(f"\nBH1750 Read Error: {e}")
            return self.last_lux if self.last_lux != -1 else 0

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
            print("\nTOUCH RESET: All alarms cleared.")
            self.reset_alarms()

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        self.led.off(); self.buzzer.off()

    def update_indicators(self):
        """Handle alarm patterns."""
        t = time.time()
        if self.is_sos_alarm:
            state = int(t * 10) % 2
            self.led.value = self.buzzer.value = state
        elif self.is_fall_alarm:
            self.led.on(); self.buzzer.on()
        elif self.is_removal_alarm:
            state = int(t * 2) % 2
            self.led.value = self.buzzer.value = state
        else:
            self.led.off(); self.buzzer.off()

    def run_iteration(self):
        # 1. Read Accelerometer first to check for movement
        ax, ay, az = self.get_accel()
        at = math.sqrt(ax**2 + ay**2 + az**2)
        
        # Determine if moving (acceleration variance or change)
        is_moving = at > 1.1 or at < 0.9 # Simple movement check relative to 1G
        
        # 2. Read Lux with movement context for stagnation fix
        lux = self.get_lux(is_moving=is_moving)
        touch_state = self.touch_sensor.value
        
        # 3. Logic: Removal
        if lux > self.LUX_THRESH:
            if not self.removal_start: self.removal_start = time.time()
            elif time.time() - self.removal_start > self.REMOVAL_DELAY:
                self.is_removal_alarm = True
        else:
            self.removal_start = None
            if not (self.is_fall_alarm or self.is_sos_alarm): self.is_removal_alarm = False

        # 4. Logic: SOS Hold
        if self.touch_sensor.is_pressed:
            if self.touch_sensor.active_time and self.touch_sensor.active_time > self.SOS_HOLD_TIME:
                if not self.is_sos_alarm:
                    print("\nSOS TRIGGERED!")
                    self.is_sos_alarm = True

        # 5. Logic: Fall Detection
        if at < self.FREEFALL_THRESH and not self.is_fall_alarm:
            time.sleep(0.05) # Brief pause to capture impact
            ix, iy, iz = self.get_accel()
            it = math.sqrt(ix**2 + iy**2 + iz**2)
            if it > self.IMPACT_THRESH:
                print(f"\nFALL DETECTED: {it:.2f}g. Checking immobility...")
                time.sleep(3)
                samples = [math.sqrt(sum(x**2 for x in self.get_accel())) for _ in range(10)]
                if np.var(samples) < self.STATIONARY_VAR_THRESH:
                    self.is_fall_alarm = True
                else: print("Movement detected. Fall dismissed.")

        # 6. Indicators & Debug
        self.update_indicators()
        print(f"[DEBUG] Lux: {lux:7.2f} (S:{self.stagnant_count}) | Accel: {at:4.2f}g | Touch: {touch_state} | Alarms: F:{int(self.is_fall_alarm)} S:{int(self.is_sos_alarm)} R:{int(self.is_removal_alarm)}", end='\r')

def main():
    print("--- Smart Helmet v2.3 (BH1750 Stagnation Fix) ---")
    helmet = SmartHelmet()
    print("Looping at 50Hz. Press Ctrl+C to exit.")
    
    try:
        while True:
            start = time.time()
            helmet.run_iteration()
            
            # Maintain 50Hz frequency
            # Adding an explicit small sleep for BH1750 update cycles
            elapsed = time.time() - start
            time.sleep(max(0, 0.02 - elapsed))
            
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        try: helmet.reset_alarms()
        except: pass
        print("Cleanup complete.")

if __name__ == "__main__":
    main()
