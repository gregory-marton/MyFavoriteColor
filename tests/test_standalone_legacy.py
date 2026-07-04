import sys
import pytest
import time
import machine

class FlowSimulator:
    def __init__(self):
        self.phase = "START_WAIT"
        # We start with pins all released (1)
        machine.state.pins[8] = 1 # down
        machine.state.pins[9] = 1 # select
        machine.state.pins[10] = 1 # up
        self.episode_counter = 0

    def sleep_hook(self, secs):
        # Trigger state transitions based on sleep durations and current phases
        if secs == 0.05:
            if self.phase == "START_WAIT":
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
                self.phase = "CALIBRATE_LOOP_S0"
            elif self.phase == "CALIBRATE_LOOP_S0":
                # Save State 0.
                # Press SELECT:
                machine.state.pins[9] = 0
                self.phase = "CALIBRATE_LOOP_S1_RELEASE"
            elif self.phase == "CALIBRATE_LOOP_S1_RELEASE":
                # Release SELECT to reset button_pressed to False.
                machine.state.pins[9] = 1
                self.phase = "CALIBRATE_LOOP_S1_PRESS"
            elif self.phase == "CALIBRATE_LOOP_S1_PRESS":
                # Press SELECT to save State 1.
                machine.state.pins[9] = 0
                self.phase = "CALIBRATE_LOOP_FINISH_RELEASE"
            elif self.phase == "CALIBRATE_LOOP_FINISH_RELEASE":
                # Release SELECT to reset button_pressed to False.
                machine.state.pins[9] = 1
                self.phase = "CALIBRATE_LOOP_FINISH_PRESS"
            elif self.phase == "CALIBRATE_LOOP_FINISH_PRESS":
                # Press UP to finish calibration.
                machine.state.pins[10] = 0
                self.phase = "CONFIRM_RELEASE"
            elif self.phase == "CONFIRM_RELEASE":
                # Release UP in confirmation menu.
                machine.state.pins[10] = 1
                self.phase = "CONFIRM_PRESS"
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
        elif secs == 0.1:
            if self.phase == "CONFIRM_PRESS":
                # Confirm finish calibration by pressing UP.
                machine.state.pins[10] = 0
                self.phase = "START_RL"
        elif secs == 0.5:
            if self.phase == "EPISODE_RELEASE":
                # Release SELECT after starting RL training
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"
        elif secs == 1.0:
            if self.phase == "EPISODE_RELEASE":
                # Release SELECT after starting an episode
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"
        
        # Release all pins when transitioning to START_RL and performing a non-button-polling sleep
        if self.phase == "START_RL" and secs > 0.1:
            machine.state.pins[8] = 1
            machine.state.pins[9] = 1
            machine.state.pins[10] = 1

def test_legacy_standalone_flow():
    # Reset mock state
    machine.reset_mock_state()
    
    # Initialize the flow simulator
    sim = FlowSimulator()
    
    # Mock time.sleep to run instantly but drive our simulator
    time.sleep = sim.sleep_hook

    # Import standalone, which will run the main loop to completion using our simulator
    import standalone
    
    # Assertions to verify it completed training successfully
    assert len(standalone.points) == 2
    assert standalone.calibration_mode is False
    assert sim.episode_counter == 10
