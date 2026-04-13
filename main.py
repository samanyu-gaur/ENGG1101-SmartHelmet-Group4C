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

    def __init__(self, bus_num=1):
        self.bus_num = bus_num
        self.bus = None
        self.init_bus()
        
        # Initialize gpiozero components
        # TTP223 is Active-High, so pull_up=False
        self.touch_sensor = Button(self.TOUCH_PIN, pull_up=False)
        self.led = LED(self.LED_PIN)
        self.buzzer = Buzzer(self.BUZZER_PIN)

        self.setup_sensors()
        
        # State Tracking
        self.removal_start = None
        self.is_fall_alarm = False
        self.is_sos_alarm = False
        self.is_removal_alarm = False
        
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
        """CRITICAL FIX: BH1750 Reset and MPU6050 Wake-up."""
        try:
            # Wake up MPU6050
            self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0)
            print("MPU6050: Power Management register set to 0 (Awake).")
            
            # BH1750 Reset Sequence
            self.bus.write_byte(self.BH_ADDR, 0x01) # Power On
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x07) # Reset opcode
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x10) # Continuous High-Res Mode
            print("BH1750: Reset sequence (PowerOn -> Reset -> ContinuousMode) complete.")
            
            time.sleep(0.2) # Stabilization delay
        except Exception as e:
            print(f"Sensor Setup Error: {e}. Attempting bus re-init...")
            self.init_bus()

    def get_lux(self):
        """Read continuous lux data from BH1750 with error handling."""
        try:
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x10, 2)
            lux = (data[0] << 8 | data[1]) / 1.2
            return lux
        except Exception as e:
            print(f"\nBH1750 Read Error: {e}")
            self.setup_sensors() # Try to reset sensors
            return 0

    def get_accel(self):
        """Read raw acceleration data from MPU6050 with error handling."""
        try:
            d = self.bus.read_i2c_block_data(self.MPU_ADDR, 0x3B, 6)
            def rw(h, l):
                v = (h << 8) + l
                return v - 65536 if v >= 0x8000 else v
            return rw(d[0], d[1])/16384.0, rw(d[2], d[3])/16384.0, rw(d[4], d[5])/16384.0
        except Exception as e:
            print(f"\nMPU6050 Read Error: {e}")
            self.setup_sensors() # Try to reset sensors
            return 0, 0, 0

    def reset_from_touch(self):
        """Callback for Touch Sensor Reset."""
        if self.is_fall_alarm or self.is_sos_alarm or self.is_removal_alarm:
            print("\nTOUCH RESET: All alarms cleared.")
            self.reset_alarms()

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        self.led.off()
        self.buzzer.off()

    def update_indicators(self):
        """Non-blocking alarm patterns."""
        if self.is_sos_alarm:
            if int(time.time() * 10) % 2:
                self.led.on(); self.buzzer.on()
            else:
                self.led.off(); self.buzzer.off()
        elif self.is_fall_alarm:
            self.led.on(); self.buzzer.on()
        elif self.is_removal_alarm:
            if int(time.time() * 2) % 2:
                self.led.on(); self.buzzer.on()
            else:
                self.led.off(); self.buzzer.off()
        else:
            self.led.off(); self.buzzer.off()

    def run_iteration(self):
        # 1. Read Sensors
        lux = self.get_lux()
        ax, ay, az = self.get_accel()
        at = math.sqrt(ax**2 + ay**2 + az**2)
        touch_state = self.touch_sensor.value # 1 if pressed, 0 if not
        
        # 2. Logic: Removal
        if lux > self.LUX_THRESH:
            if not self.removal_start: self.removal_start = time.time()
            elif time.time() - self.removal_start > self.REMOVAL_DELAY:
                self.is_removal_alarm = True
        else:
            self.removal_start = None
            if not (self.is_fall_alarm or self.is_sos_alarm): 
                self.is_removal_alarm = False

        # 3. Logic: SOS Hold
        if self.touch_sensor.is_pressed:
            if self.touch_sensor.active_time and self.touch_sensor.active_time > self.SOS_HOLD_TIME:
                if not self.is_sos_alarm:
                    print("\nSOS TRIGGERED: Manual Emergency!")
                    self.is_sos_alarm = True

        # 4. Logic: Fall Detection
        if at < self.FREEFALL_THRESH and not self.is_fall_alarm:
            time.sleep(0.05)
            ix, iy, iz = self.get_accel()
            it = math.sqrt(ix**2 + iy**2 + iz**2)
            if it > self.IMPACT_THRESH:
                print(f"\nFALL IMPACT: {it:.2f}g. Starting stationary check...")
                time.sleep(3)
                samples = [math.sqrt(sum(x**2 for x in self.get_accel())) for _ in range(10)]
                if np.var(samples) < self.STATIONARY_VAR_THRESH:
                    print("FALL ALARM: Worker is immobile.")
                    self.is_fall_alarm = True
                else:
                    print("FALL DISMISSED: Movement detected.")

        # 5. Indicators & Debug
        self.update_indicators()
        print(f"[DEBUG] Lux: {lux:7.2f} | Accel: {at:4.2f}g | Touch: {touch_state} | Active Alarms: F:{int(self.is_fall_alarm)} S:{int(self.is_sos_alarm)} R:{int(self.is_removal_alarm)}", end='\r')

def main():
    print("--- Smart Helmet v2.2 (Hardware Resilience Fix) ---")
    helmet = SmartHelmet()
    print("System started successfully. Monitoring loop at 50Hz.")
    
    try:
        while True:
            start = time.time()
            helmet.run_iteration()
            
            # Maintain 50Hz timing
            elapsed = time.time() - start
            time.sleep(max(0, 0.02 - elapsed))
            
    except KeyboardInterrupt:
        print("\nUser exit detected.")
    finally:
        try:
            helmet.reset_alarms()
        except: pass
        print("GPIO Cleaned up. Exiting.")

if __name__ == "__main__":
    main()
