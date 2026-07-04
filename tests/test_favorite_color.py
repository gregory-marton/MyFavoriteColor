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
    original_sleep = time.sleep
    try:
        def wrapped_sleep(secs):
            original_sleep(secs)
            sim.sleep_hook(secs)
        time.sleep = wrapped_sleep

        import standalone
        standalone.sensor.read_rgbw = lambda: (7680, 9600, 11520, 0)
        machine.state.adc[3] = 2048

        rgb = standalone.capture_favorite_color()
        
        assert rgb == (120, 160, 255)
        assert machine.state.pwm[2] == 76
    finally:
        time.sleep = original_sleep
