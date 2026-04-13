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
            if self.bus: self.bus.close()
            self.bus = smbus2.SMBus(self.bus_num)
            print(f"I2C Bus {self.bus_num} initialized.")
        except Exception as e:
            print(f"Failed to initialize I2C bus: {e}")

    def setup_sensors(self):
        """CRITICAL FIX: BH1750 High-Speed Mode & Reset."""
        try:
            # Wake up MPU6050
            self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0)
            
            # BH1750 Specific Initialization Sequence
            print("Resetting BH1750 light sensor...")
            self.bus.write_byte(self.BH_ADDR, 0x01) # Power On
            time.sleep(0.18) # Wait 180ms for BH1750 internal measurement completion
            self.bus.write_byte(self.BH_ADDR, 0x07) # Reset data register
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x10) # Set to Continuous High-Res Mode (0x10)
            print("BH1750 Continuous Mode activated.")
            
            time.sleep(0.1) # Stabilization
        except Exception as e:
            print(f"Sensor Setup Error: {e}. Attempting bus re-init...")
            self.init_bus()

    def get_lux(self):
        """Read 2-byte lux data from BH1750 with bit-shifting."""
        try:
            # Read 2 bytes starting from the Continuous High-Res opcode
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x10, 2)
            # 2-Byte Read & High-Byte Shift
            lux = (data[0] << 8 | data[1]) / 1.2
            return lux
        except Exception as e:
            return 0

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
            print("\nTOUCH RESET: Clearing active alarms.")
            self.reset_alarms()

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        self.led.off(); self.buzzer.off()

    def update_indicators(self):
        """Manage non-blocking indicators."""
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
        touch_state = self.touch_sensor.value
        
        # 2. Logic: Removal (Lux > Threshold)
        if lux > self.LUX_THRESH:
            if not self.removal_start: self.removal_start = time.time()
            elif time.time() - self.removal_start > self.REMOVAL_DELAY:
                self.is_removal_alarm = True
        else:
            self.removal_start = None
            if not (self.is_fall_alarm or self.is_sos_alarm): self.is_removal_alarm = False

        # 3. Logic: SOS Hold Check
        if self.touch_sensor.is_pressed:
            if self.touch_sensor.active_time and self.touch_sensor.active_time > self.SOS_HOLD_TIME:
                if not self.is_sos_alarm:
                    print("\nSOS EMERGENCY ACTIVATED!")
                    self.is_sos_alarm = True

        # 4. Logic: Fall Detection (Free-fall -> Impact -> Immobile)
        if at < self.FREEFALL_THRESH and not self.is_fall_alarm:
            time.sleep(0.05)
            ix, iy, iz = self.get_accel()
            it = math.sqrt(ix**2 + iy**2 + iz**2)
            if it > self.IMPACT_THRESH:
                print(f"\nIMPACT: {it:.2f}g. Stationary check...")
                time.sleep(3)
                samples = [math.sqrt(sum(x**2 for x in self.get_accel())) for _ in range(10)]
                if np.var(samples) < self.STATIONARY_VAR_THRESH:
                    self.is_fall_alarm = True
                else: print("Movement detected. Fall dismissed.")

        # 5. Output
        self.update_indicators()
        print(f"[DEBUG] Lux: {lux:7.2f} | Accel: {at:4.2f}g | Touch: {touch_state} | Alarms: F:{int(self.is_fall_alarm)} S:{int(self.is_sos_alarm)} R:{int(self.is_removal_alarm)}", end='\r')

def main():
    print("--- Smart Helmet v2.4 (High-Speed Lux Fix) ---")
    helmet = SmartHelmet()
    print("Looping at 50Hz. Press Ctrl+C to terminate.")
    
    try:
        while True:
            start = time.time()
            helmet.run_iteration()
            
            elapsed = time.time() - start
            time.sleep(max(0, 0.02 - elapsed))
            
    except KeyboardInterrupt:
        print("\nShutdown.")
    finally:
        try: helmet.reset_alarms()
        except: pass
        print("Done.")

if __name__ == "__main__":
    main()
