import time
import math
import smbus2
import numpy as np
from gpiozero import Button, LED, Buzzer
from signal import pause

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
        self.bus = smbus2.SMBus(bus_num)
        
        # Initialize gpiozero components
        # TTP223 is Active-High, so pull_up=False (uses internal pull-down)
        self.touch_sensor = Button(self.TOUCH_PIN, pull_up=False)
        self.led = LED(self.LED_PIN)
        self.buzzer = Buzzer(self.BUZZER_PIN)

        self.setup_sensors()
        
        # State Tracking
        self.removal_start = None
        self.is_fall_alarm = False
        self.is_sos_alarm = False
        self.is_removal_alarm = False
        
        # Event-driven "I'm Okay" Reset
        self.touch_sensor.when_pressed = self.reset_from_touch

    def setup_sensors(self):
        """Initialize I2C sensors with correct opcodes."""
        try:
            # Wake up MPU6050
            self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0)
            
            # Initialize BH1750 (GY-302)
            self.bus.write_byte(self.BH_ADDR, 0x01) # Power On
            time.sleep(0.1)
            # Explicitly set Continuous High-Res Mode (0x10)
            self.bus.write_byte(self.BH_ADDR, 0x10)
            time.sleep(0.2) # Allow time for first reading
        except Exception as e:
            print(f"Sensor Initialization Error: {e}")

    def get_lux(self):
        """Read continuous lux data from BH1750."""
        try:
            # Read 2 bytes from continuous high-res mode
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x10, 2)
            return (data[0] << 8 | data[1]) / 1.2
        except: return 0

    def get_accel(self):
        """Read raw acceleration data from MPU6050."""
        try:
            d = self.bus.read_i2c_block_data(self.MPU_ADDR, 0x3B, 6)
            def rw(h, l):
                v = (h << 8) + l
                return v - 65536 if v >= 0x8000 else v
            # Scale factor for +/- 2g range is 16384.0
            return rw(d[0], d[1])/16384.0, rw(d[2], d[3])/16384.0, rw(d[4], d[5])/16384.0
        except: return 0, 0, 0

    def reset_from_touch(self):
        """Callback for 'I'm Okay' Reset."""
        if self.is_fall_alarm:
            print("\n'I'm Okay' Reset triggered via Touch Sensor.")
            self.reset_alarms()

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        self.led.off()
        self.buzzer.off()

    def update_indicators(self):
        """Handle alarm patterns based on current state."""
        if self.is_sos_alarm:
            # High-frequency SOS (fast blink/beep)
            if int(time.time() * 10) % 2:
                self.led.on(); self.buzzer.on()
            else:
                self.led.off(); self.buzzer.off()
        elif self.is_fall_alarm:
            # Solid Alarm
            self.led.on(); self.buzzer.on()
        elif self.is_removal_alarm:
            # Slower notification pattern
            if int(time.time() * 2) % 2:
                self.led.on(); self.buzzer.on()
            else:
                self.led.off(); self.buzzer.off()
        else:
            self.led.off(); self.buzzer.off()

    def process_loop(self):
        lux = self.get_lux()
        ax, ay, az = self.get_accel()
        at = math.sqrt(ax**2 + ay**2 + az**2)
        
        # Touch sensor hardware state for SOS hold check
        is_touched = self.touch_sensor.is_pressed
        
        # 1. Helmet Removal Logic
        if lux > self.LUX_THRESH:
            if not self.removal_start: self.removal_start = time.time()
            elif time.time() - self.removal_start > self.REMOVAL_DELAY:
                self.is_removal_alarm = True
        else:
            self.removal_start = None
            if not (self.is_fall_alarm or self.is_sos_alarm): 
                self.is_removal_alarm = False

        # 2. Manual SOS Hold Logic
        if is_touched:
            # Check if this touch has been held long enough for SOS
            # Note: touch_sensor.active_time is built-in to gpiozero
            if self.touch_sensor.active_time and self.touch_sensor.active_time > self.SOS_HOLD_TIME:
                if not self.is_sos_alarm:
                    print("\nMANUAL SOS ACTIVATED!")
                    self.is_sos_alarm = True
        
        # 3. Fall Detection logic
        if at < self.FREEFALL_THRESH and not self.is_fall_alarm:
            time.sleep(0.05)
            ix, iy, iz = self.get_accel()
            it = math.sqrt(ix**2 + iy**2 + iz**2)
            if it > self.IMPACT_THRESH:
                print(f"\nIMPACT DETECTED! ({it:.2f}g). Stationary check...")
                time.sleep(3)
                samples = [math.sqrt(sum(x**2 for x in self.get_accel())) for _ in range(10)]
                if np.var(samples) < self.STATIONARY_VAR_THRESH:
                    print("Worker IMMOBILE. Fall Alarm Active.")
                    self.is_fall_alarm = True
                else:
                    print("Movement detected. Fall dismissed.")

        self.update_indicators()
        print(f"Lux: {lux:6.2f} | Accel: {at:4.2f}g | Touch: {int(is_touched)}", end='\r')

def main():
    print("Smart Helmet v2.1 (Pi 5 optimized) - Starting...")
    helmet = SmartHelmet()
    print("System Online. Press Ctrl+C to exit.")
    
    try:
        while True:
            start_time = time.time()
            helmet.process_loop()
            
            # Maintain ~50Hz (0.02s loop)
            elapsed = time.time() - start_time
            sleep_time = max(0, 0.02 - elapsed)
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        print("\nShutdown requested.")
    finally:
        # gpiozero handles cleanup automatically on exit, but we force off first
        try:
            helmet.reset_alarms()
        except: pass
        print("GPIO Cleaned up. Goodbye.")

if __name__ == "__main__":
    main()
