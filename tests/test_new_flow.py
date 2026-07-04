import sys
import pytest
import time
import machine

class NewFlowSimulator:
    def __init__(self):
        self.phase = "FAV_COLOR_WAIT"
        # We start with pins all released (1)
        machine.state.pins[8] = 1 # down
        machine.state.pins[9] = 1 # select
        machine.state.pins[10] = 1 # up
        self.episode_counter = 0
        self.calibrated_states = 0

    def sleep_hook(self, secs):
        # Ignore sleeps during startup delay countdown
        import standalone
        if any(t[0].startswith("Starting in") for t in standalone.display.buffer):
            return

        # We trigger state transitions on button-polling sleeps (0.05 seconds)
        if secs == 0.05:
            if self.phase == "FAV_COLOR_WAIT":
                # Initial wait in capture_favorite_color
                machine.state.pins[9] = 0 # press SELECT to lock in favorite color
                self.phase = "FAV_COLOR_RELEASE"
            elif self.phase == "FAV_COLOR_RELEASE":
                # Release wait in capture_favorite_color
                machine.state.pins[9] = 1
                self.phase = "START_WAIT"
            elif self.phase == "START_WAIT":
                # Wait for any button to start calibration.
                # Press SELECT:
                machine.state.pins[9] = 0
                self.phase = "START_RELEASE"
            elif self.phase == "START_RELEASE":
                # Wait for all buttons to be released.
                machine.state.pins[9] = 1
                self.phase = "BEGIN_WAIT"
            elif self.phase == "BEGIN_WAIT":
                # Wait for press to begin calibration.
                # Press SELECT:
                machine.state.pins[9] = 0
                self.phase = "CALIBRATE_START_RELEASE"
            elif self.phase == "CALIBRATE_START_RELEASE":
                # Wait for all buttons to be released at start of calibration.
                machine.state.pins[9] = 1
                self.phase = "CALIBRATE_LOOP"
            elif self.phase == "CALIBRATE_LOOP":
                # We need to calibrate exactly 7 states.
                # Release SELECT first so button_pressed is False
                if machine.state.pins[9] == 0:
                    machine.state.pins[9] = 1
                else:
                    # Press SELECT to save current state
                    machine.state.pins[9] = 0
                    self.calibrated_states += 1
                    if self.calibrated_states == 7:
                        self.phase = "START_RL"
            elif self.phase == "START_RL":
                # Press SELECT to start RL training.
                machine.state.pins[9] = 0
                self.phase = "EPISODE_RELEASE"
            elif self.phase == "EPISODE_WAIT":
                # Waiting to start an episode.
                # Press SELECT:
                machine.state.pins[9] = 0
                self.episode_counter += 1
                self.phase = "EPISODE_RELEASE"
            elif self.phase == "EPISODE_RELEASE":
                # Release SELECT.
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"
        elif secs == 0.5:
            if self.phase == "EPISODE_RELEASE":
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"
        elif secs == 1.0:
            if self.phase == "EPISODE_RELEASE":
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"
        
        # Release all pins when transitioning to START_RL and performing a non-button-polling sleep
        if self.phase == "START_RL" and secs > 0.1:
            machine.state.pins[8] = 1
            machine.state.pins[9] = 1
            machine.state.pins[10] = 1

def test_new_standalone_flow():
    machine.reset_mock_state()
    sim = NewFlowSimulator()
    original_sleep = time.sleep
    try:
        def wrapped_sleep(secs):
            original_sleep(secs)
            sim.sleep_hook(secs)
        time.sleep = wrapped_sleep

        import standalone
        standalone.calibration_mode = True
        standalone.points = []
        standalone.favorite_color = None
        standalone.sensor.read_rgbw = lambda: (6400, 9600, 12800, 0)
        machine.state.adc[3] = 2048

        standalone.main()
        
        assert len(standalone.points) == 7
        assert standalone.calibration_mode is False
        assert sim.episode_counter == 10

        # Assertions for new calibration and training display features
        assert any("RGB: 100,160,255" in msg for msg in standalone.display.history)
        assert any("Rew:" in msg for msg in standalone.display.history)
        assert any("Act:" in msg for msg in standalone.display.history)

        # Assertions for virtual reward calculation and grand total
        assert standalone.rewards_history[0] == 1500
        assert any("15000" in msg for msg in standalone.display.history)
    finally:
        time.sleep = original_sleep
