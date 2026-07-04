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
    time.sleep = sim.sleep_hook

    import standalone
    standalone.sensor.read_rgbw = lambda: (6400, 9600, 12800, 0)

    # We want to calibrate exactly 3 states
    # This should fail because calibrate_states doesn't accept any arguments yet!
    colors = standalone.calibrate_states(3)
    
    assert len(colors) == 3
