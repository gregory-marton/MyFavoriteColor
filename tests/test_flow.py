import pytest
import myfavcolor
from unittest.mock import MagicMock

@pytest.mark.parametrize("angle_step, button_sequence", [
    (20, [None, None, "select"]), # Auto sweep: 2 loops in capture_favorite_color
    (0, [None, None, "select"] * 8)   # Pot mode: 1 fav color + 7 states, 2 loops each
])
def test_main_flow(monkeypatch, angle_step, button_sequence):
    # Set the angle step
    monkeypatch.setattr(myfavcolor, 'STATE_ANGLE_STEP', angle_step)
    
    # Setup mocks for hardware inputs
    mock_sensor = MagicMock()
    mock_sensor.rgb = (100, 150, 200)
    monkeypatch.setattr(myfavcolor, 'sensor', mock_sensor)
    
    mock_sens = MagicMock()
    # Initial read before loop is 2048. 
    # Loop 1 reads 4095 (diff > threshold, hits 'if' path). 
    # Loop 2 reads 4095 (diff = 0, hits 'else' path).
    import itertools
    mock_sens.readpot.side_effect = itertools.cycle([2048, 4095, 4095, 0, 0])
    monkeypatch.setattr(myfavcolor, 'sens', mock_sens)
    
    # Don't abort on startup
    mock_switch = MagicMock()
    mock_switch.value.return_value = 1
    monkeypatch.setattr(myfavcolor, 'switch_up', mock_switch)
    
    # Mock time
    monkeypatch.setattr(myfavcolor.time, 'sleep', lambda x: None)
    
    # Bypass the 2-second startup loop
    monkeypatch.setattr(myfavcolor.time, 'ticks_ms', lambda: 0)
    monkeypatch.setattr(myfavcolor.time, 'ticks_diff', lambda a,b: 3000)
    
    # Mock button polling
    seq = button_sequence.copy()
    def mock_checkbuttons():
        if seq:
            return seq.pop(0)
        return "select"
        
    def mock_waitforbutton():
        return "select"
        
    original_calibrate = myfavcolor.Environment.calibrate_states
    def patched_calibrate(self):
        original_calibrate(self)
        self.states = list(range(7))
    monkeypatch.setattr(myfavcolor.Environment, 'calibrate_states', patched_calibrate)

    monkeypatch.setattr(myfavcolor, 'checkbuttons', mock_checkbuttons)
    monkeypatch.setattr(myfavcolor, 'waitforbutton', mock_waitforbutton)
    
    # Run the entire flow
    try:
        myfavcolor.main()
    except Exception as e:
        pytest.fail(f"Flow crashed with {e}")
