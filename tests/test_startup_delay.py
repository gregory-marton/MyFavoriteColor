import pytest
import time
import machine

class StartupAbortSimulator:
    def __init__(self):
        machine.state.pins[10] = 0 # UP pressed (0)
        machine.state.pins[8] = 1
        machine.state.pins[9] = 1

    def sleep_hook(self, secs):
        pass

class StartupProceedSimulator:
    def __init__(self):
        machine.state.pins[10] = 1 # UP not pressed (1)
        machine.state.pins[8] = 1
        machine.state.pins[9] = 1

    def sleep_hook(self, secs):
        # We need to raise an exception once we exit the countdown to avoid running the whole main loop
        # The first sleep inside calibration mode is:
        # while switch_up.value() and switch_down.value() and switch_select.value(): time.sleep(0.05)
        # We can detect this polling sleep and raise a custom exception to confirm we reached it!
        if secs == 0.05:
            raise ValueError("Reached calibration wait loop")

def test_startup_delay_abort():
    machine.reset_mock_state()
    sim = StartupAbortSimulator()
    original_sleep = time.sleep
    try:
        def wrapped_sleep(secs):
            original_sleep(secs)
            sim.sleep_hook(secs)
        time.sleep = wrapped_sleep

        import standalone
        standalone.calibration_mode = True
        standalone.points = []
        
        import sys
        original_exit = sys.exit
        sys.exit = lambda: (_ for _ in ()).throw(SystemExit("Aborted"))

        try:
            with pytest.raises(SystemExit):
                standalone.main()
        finally:
            sys.exit = original_exit

        # Verify that calibration mode was NOT cleared (we exited before calibration ran)
        assert standalone.calibration_mode is True
    finally:
        time.sleep = original_sleep

def test_startup_delay_proceed():
    machine.reset_mock_state()
    sim = StartupProceedSimulator()
    original_sleep = time.sleep
    try:
        def wrapped_sleep(secs):
            original_sleep(secs)
            sim.sleep_hook(secs)
        time.sleep = wrapped_sleep

        import standalone
        standalone.calibration_mode = True
        standalone.points = []

        # We expect it to pass the countdown and raise ValueError when it hits the calibration loop
        with pytest.raises(ValueError, match="Reached calibration wait loop"):
            standalone.main()
            
    finally:
        time.sleep = original_sleep
