import time
import math
import smbus2
import numpy as np
try:
    import RPi.GPIO as GPIO
except ImportError:
    # Mock for testing on non-Pi
    class GPIO_Mock:
        BCM, OUT, IN, HIGH, LOW, PUD_DOWN = 'BCM', 'OUT', 'IN', 1, 0, 'PUD_DOWN'
        def setmode(self, mode): pass
        def setup(self, pin, mode, pull_up_down=None): pass
        def output(self, pin, state): pass
        def input(self, pin): return 0
        def cleanup(self): pass
    GPIO = GPIO_Mock()

class SmartHelmet:
    # Addresses
    MPU_ADDR, BH_ADDR = 0x68, 0x23
    # Pins
    BUZZER, LED, TOUCH = 18, 27, 24
    # Thresholds
    LUX_THRESH, REMOVAL_DELAY = 20, 2.0
    FREEFALL_THRESH, IMPACT_THRESH = 0.5, 3.0
    STATIONARY_VAR_THRESH = 0.05
    SOS_HOLD_TIME = 3.0

    def __init__(self, bus_num=1):
        self.bus = smbus2.SMBus(bus_num)
        self.setup_gpio()
        self.setup_sensors()
        self.removal_start = None
        self.touch_start = None
        self.is_fall_alarm = False
        self.is_sos_alarm = False
        self.is_removal_alarm = False

    def setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        for p in [self.BUZZER, self.LED]: GPIO.setup(p, GPIO.OUT)
        GPIO.setup(self.TOUCH, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        self.reset_alarms()

    def setup_sensors(self):
        self.bus.write_byte_data(self.MPU_ADDR, 0x6B, 0)
        self.bus.write_byte(self.BH_ADDR, 0x01)
        self.bus.write_byte(self.BH_ADDR, 0x10)

    def get_lux(self):
        try:
            data = self.bus.read_i2c_block_data(self.BH_ADDR, 0x10, 2)
            return (data[0] << 8 | data[1]) / 1.2
        except: return 0

    def get_accel(self):
        try:
            d = self.bus.read_i2c_block_data(self.MPU_ADDR, 0x3B, 6)
            def rw(h, l):
                v = (h << 8) + l
                return v - 65536 if v >= 0x8000 else v
            return rw(d[0], d[1])/16384.0, rw(d[2], d[3])/16384.0, rw(d[4], d[5])/16384.0
        except: return 0, 0, 0

    def reset_alarms(self):
        self.is_fall_alarm = self.is_sos_alarm = self.is_removal_alarm = False
        GPIO.output(self.BUZZER, GPIO.LOW)
        GPIO.output(self.LED, GPIO.LOW)

    def trigger_alarm_state(self, buzzer=True, led=True):
        GPIO.output(self.BUZZER, GPIO.HIGH if buzzer else GPIO.LOW)
        GPIO.output(self.LED, GPIO.HIGH if led else GPIO.LOW)

    def process(self):
        lux = self.get_lux()
        ax, ay, az = self.get_accel()
        at = math.sqrt(ax**2 + ay**2 + az**2)
        touch_val = GPIO.input(self.TOUCH)

        # 1. Helmet Removal Check
        if lux > self.LUX_THRESH:
            if not self.removal_start: self.removal_start = time.time()
            elif time.time() - self.removal_start > self.REMOVAL_DELAY:
                self.is_removal_alarm = True
        else:
            self.removal_start = None
            if not (self.is_fall_alarm or self.is_sos_alarm): self.is_removal_alarm = False

        # 2. Touch Sensor: "I'm Okay" Reset vs Manual SOS
        if touch_val:
            if not self.touch_start: self.touch_start = time.time()
            # Reset Fall Alarm on single tap (if active)
            if self.is_fall_alarm:
                print("\n'I'm Okay' Reset Triggered.")
                self.reset_alarms()
            # Check for Manual SOS (Hold > 3s)
            elif time.time() - self.touch_start > self.SOS_HOLD_TIME:
                print("\nMANUAL SOS ACTIVATED!")
                self.is_sos_alarm = True
        else:
            self.touch_start = None

        # 3. Fall Detection
        if at < self.FREEFALL_THRESH and not self.is_fall_alarm:
            time.sleep(0.05)
            ix, iy, iz = self.get_accel()
            it = math.sqrt(ix**2 + iy**2 + iz**2)
            if it > self.IMPACT_THRESH:
                print(f"\nIMPACT! ({it:.2f}g). Checking for immobility...")
                time.sleep(3)
                samples = [math.sqrt(sum(x**2 for x in self.get_accel())) for _ in range(10)]
                if np.var(samples) < self.STATIONARY_VAR_THRESH:
                    print("Worker Stationary. ALARM ACTIVE.")
                    self.is_fall_alarm = True
                else: print("Movement detected. Fall dismissed.")

        # 4. Alarm Patterns (Non-blocking buzzer/LED control)
        if self.is_sos_alarm:
            # High-frequency SOS pattern
            state = int(time.time() * 10) % 2
            self.trigger_alarm_state(buzzer=state, led=state)
        elif self.is_fall_alarm:
            self.trigger_alarm_state(True, True)
        elif self.is_removal_alarm:
            # Slower beep for removal
            state = int(time.time() * 2) % 2
            self.trigger_alarm_state(buzzer=state, led=state)
        else:
            self.trigger_alarm_state(False, False)

        print(f"Lux: {lux:5.1f} | G: {at:4.2f} | Touch: {touch_val}", end='\r')

def main():
    helmet = SmartHelmet()
    print("Smart Helmet v2.0 Online (50Hz loop)")
    try:
        while True:
            helmet.process()
            time.sleep(0.02) # ~50Hz
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        helmet.reset_alarms()
        GPIO.cleanup()

if __name__ == "__main__": main()
