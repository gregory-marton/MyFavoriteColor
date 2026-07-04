import pytest
import time
import machine

class CalibSimulator:
    def __init__(self):
        # We start with pins all released (1)
        machine.state.pins[8] = 1 # down
        machine.state.pins[9] = 1 # select
        machine.state.pins[10] = 1 # up
        self.state_saves = 0

    def sleep_hook(self, secs):
        # Trigger state saves on button-polling sleeps (0.05 seconds)
        if secs == 0.05:
            # We want to save 3 states: S0, S1, S2
            if self.state_saves < 3:
                # We need to simulate: release (all 1), then press SELECT (pins[9] = 0)
                if machine.state.pins[9] == 0:
                    machine.state.pins[9] = 1
                else:
                    machine.state.pins[9] = 0
                    self.state_saves += 1

def test_calibrate_states_fixed_count():
    machine.reset_mock_state()
    sim = CalibSimulator()
    original_sleep = time.sleep
    try:
        def wrapped_sleep(secs):
            original_sleep(secs)
            sim.sleep_hook(secs)
        time.sleep = wrapped_sleep

        import standalone
        standalone.sensor.read_rgbw = lambda: (6400, 9600, 12800, 0)

        colors = standalone.calibrate_states(3)
        
        assert len(colors) == 3
    finally:
        time.sleep = original_sleep
