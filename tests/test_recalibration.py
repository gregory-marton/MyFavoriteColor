import sys
import pytest
import time
import machine

class RecalibSimulator:
    def __init__(self):
        self.phase = "FAV_COLOR_WAIT_1"
        machine.state.pins[8] = 1
        machine.state.pins[9] = 1
        machine.state.pins[10] = 1
        self.calibrated_states = 0
        self.episode_counter = 0

    def sleep_hook(self, secs):
        # Ignore sleeps during startup delay countdown
        import standalone
        if any(t[0].startswith("Starting in") for t in standalone.display.buffer):
            return

        if secs == 0.05:
            # --- RUN 1 ---
            if self.phase == "FAV_COLOR_WAIT_1":
                machine.state.pins[9] = 0 # SELECT
                self.phase = "FAV_COLOR_RELEASE_1"
            elif self.phase == "FAV_COLOR_RELEASE_1":
                machine.state.pins[9] = 1
                self.phase = "START_WAIT_1"
            elif self.phase == "START_WAIT_1":
                machine.state.pins[9] = 0
                self.phase = "START_RELEASE_1"
            elif self.phase == "START_RELEASE_1":
                machine.state.pins[9] = 1
                self.phase = "BEGIN_WAIT_1"
            elif self.phase == "BEGIN_WAIT_1":
                machine.state.pins[9] = 0
                self.phase = "CALIBRATE_START_RELEASE_1"
            elif self.phase == "CALIBRATE_START_RELEASE_1":
                machine.state.pins[9] = 1
                self.phase = "CALIBRATE_LOOP_1"
            elif self.phase == "CALIBRATE_LOOP_1":
                if machine.state.pins[9] == 0:
                    machine.state.pins[9] = 1
                else:
                    machine.state.pins[9] = 0
                    self.calibrated_states += 1
                    if self.calibrated_states == 7:
                        self.phase = "CONFIRM_REDO"
            
            # --- REDO CHOICE ---
            elif self.phase == "CONFIRM_REDO":
                # Press UP to trigger recalibration
                machine.state.pins[10] = 0
                self.phase = "REDO_RELEASE"
            elif self.phase == "REDO_RELEASE":
                machine.state.pins[10] = 1
                self.calibrated_states = 0
                self.phase = "FAV_COLOR_WAIT_2"
                
            # --- RUN 2 ---
            elif self.phase == "FAV_COLOR_WAIT_2":
                machine.state.pins[9] = 0
                self.phase = "FAV_COLOR_RELEASE_2"
            elif self.phase == "FAV_COLOR_RELEASE_2":
                machine.state.pins[9] = 1
                self.phase = "START_WAIT_2"
            elif self.phase == "START_WAIT_2":
                machine.state.pins[9] = 0
                self.phase = "START_RELEASE_2"
            elif self.phase == "START_RELEASE_2":
                machine.state.pins[9] = 1
                self.phase = "BEGIN_WAIT_2"
            elif self.phase == "BEGIN_WAIT_2":
                machine.state.pins[9] = 0
                self.phase = "CALIBRATE_START_RELEASE_2"
            elif self.phase == "CALIBRATE_START_RELEASE_2":
                machine.state.pins[9] = 1
                self.phase = "CALIBRATE_LOOP_2"
            elif self.phase == "CALIBRATE_LOOP_2":
                if machine.state.pins[9] == 0:
                    machine.state.pins[9] = 1
                else:
                    machine.state.pins[9] = 0
                    self.calibrated_states += 1
                    if self.calibrated_states == 7:
                        self.phase = "CONFIRM_START"
            
            # --- CONFIRM START Choice ---
            elif self.phase == "CONFIRM_START":
                machine.state.pins[9] = 0 # SELECT to start RL
                self.phase = "EPISODE_RELEASE"
                
            # --- EPISODE LOOPS ---
            elif self.phase == "EPISODE_WAIT":
                machine.state.pins[9] = 0
                self.episode_counter += 1
                self.phase = "EPISODE_RELEASE"
            elif self.phase == "EPISODE_RELEASE":
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"
                
        elif secs == 0.5:
            if self.phase == "EPISODE_RELEASE":
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"
            elif self.phase == "REDO_RELEASE":
                machine.state.pins[10] = 1
        elif secs == 1.0:
            if self.phase == "EPISODE_RELEASE":
                machine.state.pins[9] = 1
                self.phase = "EPISODE_WAIT"

        # Release pins during non-polling sleeps in config check
        if self.phase in ("CONFIRM_REDO", "CONFIRM_START") and secs > 0.1:
            machine.state.pins[8] = 1
            machine.state.pins[9] = 1
            machine.state.pins[10] = 1

def test_recalibration_flow():
    machine.reset_mock_state()
    sim = RecalibSimulator()
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
    finally:
        time.sleep = original_sleep
