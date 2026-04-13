import time
import math
import smbus2
try:
    import RPi.GPIO as GPIO
except ImportError:
    # Fallback for testing on non-Pi systems
    class GPIO_Mock:
        BCM = 'BCM'
        OUT = 'OUT'
        def setmode(self, mode): pass
        def setup(self, pin, mode): pass
        def output(self, pin, state): pass
        def cleanup(self): pass
    GPIO = GPIO_Mock()

class SmartHelmet:
    # I2C Addresses
    MPU6050_ADDR = 0x68
    BH1750_ADDR = 0x23

    # GPIO Pins (BCM)
    BUZZER_PIN = 18
    LED_PIN = 27

    # Thresholds
    LUX_THRESHOLD = 20
    REMOVAL_DELAY = 2.0
    FREEFALL_THRESHOLD = 0.5
    IMPACT_THRESHOLD = 3.0
    STATIONARY_VARIANCE_THRESHOLD = 0.05

    def __init__(self, bus_number=1):
        self.bus = smbus2.SMBus(bus_number)
        self.setup_gpio()
        self.setup_sensors()
        
        self.removal_start_time = None
        self.is_alarm_active = False

    def setup_gpio(self):
        """Initialize GPIO pins for Buzzer and LED."""
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.BUZZER_PIN, GPIO.OUT)
        GPIO.setup(self.LED_PIN, GPIO.OUT)
        self.set_alarm(False)

    def setup_sensors(self):
        """Initialize I2C sensors (MPU6050 and BH1750)."""
        # Initialize MPU6050 (Wake up from sleep mode)
        self.bus.write_byte_data(self.MPU6050_ADDR, 0x6B, 0)
        
        # Initialize BH1750 (Power on and continuous high-res mode)
        self.bus.write_byte(self.BH1750_ADDR, 0x01) # Power on
        self.bus.write_byte(self.BH1750_ADDR, 0x10) # Continuous high res

    def get_lux(self):
        """Read Lux value from BH1750."""
        try:
            data = self.bus.read_i2c_block_data(self.BH1750_ADDR, 0x10, 2)
            lux = (data[0] << 8 | data[1]) / 1.2
            return lux
        except Exception as e:
            print(f"Error reading BH1750: {e}")
            return 0

    def get_acceleration(self):
        """Read raw acceleration data from MPU6050 and convert to Gs."""
        try:
            # MPU6050 Acceleration registers: 0x3B (ACCEL_XOUT_H) to 0x40 (ACCEL_ZOUT_L)
            data = self.bus.read_i2c_block_data(self.MPU6050_ADDR, 0x3B, 6)
            
            def read_word(high, low):
                val = (high << 8) + low
                if val >= 0x8000:
                    return -((65535 - val) + 1)
                else:
                    return val

            # Default range is +/- 2g, scale factor is 16384.0
            ax = read_word(data[0], data[1]) / 16384.0
            ay = read_word(data[2], data[3]) / 16384.0
            az = read_word(data[4], data[5]) / 16384.0
            
            return ax, ay, az
        except Exception as e:
            print(f"Error reading MPU6050: {e}")
            return 0, 0, 0

    def set_alarm(self, state):
        """Control Buzzer and LED."""
        self.is_alarm_active = state
        GPIO.output(self.BUZZER_PIN, GPIO.HIGH if state else GPIO.LOW)
        GPIO.output(self.LED_PIN, GPIO.HIGH if state else GPIO.LOW)

    def run_check(self):
        """Main check loop iteration."""
        # 1. Helmet Removal Check
        lux = self.get_lux()
        if lux > self.LUX_THRESHOLD:
            if self.removal_start_time is None:
                self.removal_start_time = time.time()
            elif time.time() - self.removal_start_time > self.REMOVAL_DELAY:
                print(f"ALARM: Helmet Removed (Lux: {lux:.2f})")
                self.set_alarm(True)
        else:
            self.removal_start_time = None
            if not self.is_alarm_active:
                self.set_alarm(False)

        # 2. Fall Detection Logic
        ax, ay, az = self.get_acceleration()
        a_total = math.sqrt(ax**2 + ay**2 + az**2)
        
        print(f"Lux: {lux:6.2f} | Accel Total: {a_total:4.2f}g (X:{ax:4.2f}, Y:{ay:4.2f}, Z:{az:4.2f})", end='\r')

        # Fall Detection State Machine
        if a_total < self.FREEFALL_THRESHOLD:
            # Potential Free-fall detected
            time.sleep(0.05)
            # Check for impact immediately after
            ax_i, ay_i, az_i = self.get_acceleration()
            a_impact = math.sqrt(ax_i**2 + ay_i**2 + az_i**2)
            
            if a_impact > self.IMPACT_THRESHOLD:
                print(f"\nIMPACT DETECTED! Impact force: {a_impact:.2f}g. Waiting for stationary check...")
                self.set_alarm(True)
                
                # Stationary Check: Wait 3 seconds and check for movement
                time.sleep(3)
                samples = []
                for _ in range(10):
                    nx, ny, nz = self.get_acceleration()
                    samples.append(math.sqrt(nx**2 + ny**2 + nz**2))
                    time.sleep(0.1)
                
                variance = max(samples) - min(samples)
                if variance < self.STATIONARY_VARIANCE_THRESHOLD:
                    print(f"ALARM: Worker Stationary after fall (Variance: {variance:.4f}). Potential unconsciousness.")
                    # Keep alarm on
                else:
                    print("Worker is moving. Resetting alarm.")
                    self.set_alarm(False)

    def cleanup(self):
        """Cleanup GPIO and resources."""
        print("\nCleaning up GPIO and exiting...")
        self.set_alarm(False)
        GPIO.cleanup()

if __name__ == "__main__":
    helmet = SmartHelmet()
    try:
        while True:
            helmet.run_check()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        helmet.cleanup()
