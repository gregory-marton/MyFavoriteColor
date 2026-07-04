import pytest
import time
import machine

class FavColorSimulator:
    def __init__(self):
        self.sleep_count = 0
        machine.state.pins[8] = 1 # down
        machine.state.pins[9] = 1 # select
        machine.state.pins[10] = 1 # up

    def sleep_hook(self, secs):
        self.sleep_count += 1
        # The first sleep inside capture_favorite_color is a button-release check loop:
        # while not switch_select.value() or not switch_up.value() or not switch_down.value(): time.sleep(0.05)
        # Since pins are initially 1, this exits immediately without sleeping.
        #
        # In the main loop:
        # 1. It reads pot and rgb, updates display.
        # 2. It checks: if not switch_select.value():
        # 3. It sleeps 0.05 at the end of the loop.
        # Let's trigger a SELECT press on the first sleep (which must be the end-of-loop sleep).
        if secs == 0.05:
            # Press SELECT
            machine.state.pins[9] = 0
        elif secs == 1.5:
            # Confirm lock-in, then release SELECT so the exit release wait exits
            machine.state.pins[9] = 1

def test_capture_favorite_color():
    machine.reset_mock_state()
    sim = FavColorSimulator()
    time.sleep = sim.sleep_hook

    # Mock sensor to return (120, 150, 180)
    machine.state.i2c_mem[(0x10, 0x08)] = b'\x00\x1e' # 1920 (>> 6 = 30 * wr=4 -> 120)
    # Let's just mock sensor.rgb property directly to be simple and independent of sensor gains:
    import standalone
    standalone.sensor.read_rgbw = lambda: (7680, 9600, 11520, 0) # R=120, G=150, B=180
    
    # Mock pot value to return 2048 (approx 90 degrees)
    machine.state.adc[3] = 2048

    # Call capture_favorite_color
    rgb = standalone.capture_favorite_color()
    
    assert rgb == (120, 160, 255)
    # Check that servo was written to 90 degrees (mapped from 2048 pot value)
    assert machine.state.pwm[2] == 76 # duty value for ~90 degrees (1500us)
