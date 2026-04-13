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
    LUX_THRESH = 30
    REMOVAL_DELAY = 2.0
    FREEFALL_THRESH, IMPACT_THRESH = 0.5, 3.0
    STATIONARY_VAR_THRESH = 0.05
    SOS_HOLD_TIME = 3.0
    STAGNANT_LIMIT = 20 # v2.6: Re-init after 20 identical frames

    def __init__(self, bus_num=1):
        self.bus_num = bus_num
        self.bus = None
        self.init_bus()
        
        # Initialize gpiozero components
        self.touch_sensor = Button(self.TOUCH_PIN, pull_up=False)
        self.led = LED(self.LED_PIN)
        self.buzzer = Buzzer(self.BUZZER_PIN)

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
        """Initialize or re-initialize the I2C bus."""
        try:
            if self.bus: self.bus.close()
            self.bus = smbus2.SMBus(self.bus_num)
            print(f"I2C Bus {self.bus_num} initialized.")
        except Exception as e:
            print(f"Failed to initialize I2C bus: {e}")

    def re_init_bh1750(self):
        """Force re-initialization of the BH1750 sensor."""
        try:
            # Power On -> High-Res Mode 2
            self.bus.write_byte(self.BH_ADDR, 0x01) # Power On
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x11) # High-Res Mode 2 (0.5 lux precision)
            # print("\n[SENSORS] BH1750 Re-initialized to Mode 2.")
        except Exception as e:
            print(f"\n[I2C HANG] Attempting Bus Reset... Error: {e}")
            self.init_bus()

    def setup_sensors(self):
        """v2.6 High-Resolution Mode 2 Initialization."""
        try:
            # Wake up MPU6050
            self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0)
            
            # BH1750 Initial Setup
            print("Configuring BH1750 (High-Res Mode 2)...")
            self.bus.write_byte(self.BH_ADDR, 0x01) # Power On
            time.sleep(0.1)
            self.bus.write_byte(self.BH_ADDR, 0x07) # Reset Data
            time.sleep(0.05)
            self.bus.write_byte(self.BH_ADDR, 0x11) # Mode 2 (0.5 lux)
            
            print("Waiting for initial integration (200ms)...")
            time.sleep(0.2)
            print("Sensors Online.")
        except Exception as e:
            print(f"Sensor Setup Error: {e}. Attempting bus re-init...")
            self.init_bus()

    def get_lux(self):
        """v2.6 Stagnation detection with Mode 2 and 200ms integration delay."""
        try:
            # High-Resolution Mode 2 read command
            # Note: We send the command and wait 200ms for integration
            self.bus.write_byte(self.BH_ADDR, 0x11)
            time.sleep(0.2) # Essential 180ms+ refresh delay
            
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x11, 2)
            lux = ((data[0] << 8) | data[1]) / 1.2
            
            # Stagnation Logic
            if lux == self.last_lux:
                self.stagnant_count += 1
            else:
                self.stagnant_count = 0
                self.last_lux = lux
            
            # v2.6 Auto-Recovery
            if self.stagnant_count >= self.STAGNANT_LIMIT:
                print(f"\n[DEBUG] Lux stagnant for {self.stagnant_count} frames. Re-initializing...")
                self.re_init_bh1750()
                self.stagnant_count = 0
                
            return lux
        except Exception as e:
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
            print("\n[RESET] Touch detected. Clearing all alarms.")
            self.reset_alarms()
            self.removal_start = None

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        self.led.off(); self.buzzer.off()

    def update_indicators(self):
        """Alarm patterns."""
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
        # 1. Read Sensors (Lux read now includes a 0.2s sleep internally)
        lux = self.get_lux()
        ax, ay, az = self.get_accel()
        at = math.sqrt(ax**2 + ay**2 + az**2)
        
        # 2. Helmet Removal Logic
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

        # 4. SOS Logic
        if self.touch_sensor.is_pressed and self.touch_sensor.active_time:
            if self.touch_sensor.active_time > self.SOS_HOLD_TIME and not self.is_sos_alarm:
                self.is_sos_alarm = True

        # 5. Output Update
        self.update_indicators()
        print(f"{status_msg} Lux: {lux:7.2f} (S:{self.stagnant_count}) | Accel: {at:4.2f}g | Touch: {int(self.touch_sensor.value)}", end='\r')

def main():
    print("--- Smart Helmet v2.6 (Sensor Freshness Priority) ---")
    helmet = SmartHelmet()
    print("Looping with Sensor Freshness Priority. Press Ctrl+C to terminate.")
    
    try:
        while True:
            start = time.time()
            helmet.run_iteration()
            
            # maintain loop frequency (though get_lux 0.2s delay dictates speed)
            elapsed = time.time() - start
            time.sleep(max(0, 0.02 - elapsed))
            
    except KeyboardInterrupt:
        print("\n[EXIT] Shutdown.")
    finally:
        try: helmet.reset_alarms()
        except: pass
        print("Cleanup done.")

if __name__ == "__main__":
    main()
