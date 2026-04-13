"""
Main entry point for the Smart Helmet System (ENGG1101).
This script initializes the SmartHelmet class and runs the monitoring loop.
"""
import time
from smart_helmet import SmartHelmet

def main():
    print("Starting Smart Helmet System...")
    print("Initializing sensors and GPIO...")
    
    try:
        helmet = SmartHelmet()
        print("System Online. Monitoring for fall and removal events...")
        print("Press Ctrl+C to exit.")
        
        while True:
            helmet.run_check()
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\nShutdown requested by user.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    finally:
        # The cleanup is handled inside the class or here if initialized
        try:
            helmet.cleanup()
        except NameError:
            pass
        print("System shutdown complete.")

if __name__ == "__main__":
    main()
