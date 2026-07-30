import pytest
import myfavcolor

def test_environment_dynamic_rewards(monkeypatch):
    # Mock hardware calibration to prevent interactive loops in testing.
    monkeypatch.setattr(myfavcolor.Environment, "calibrate_white_balance", lambda self: None)
    monkeypatch.setattr(myfavcolor.Environment, "capture_favorite_color", lambda self: None)
    monkeypatch.setattr(myfavcolor.Environment, "calibrate_states", lambda self: None)
    monkeypatch.setattr(myfavcolor, "START_STATE", 0)
    monkeypatch.setattr(myfavcolor, "move_servo", lambda angle: angle)
    
    env = myfavcolor.Environment(distance_metric="Euclidean", auto_calibrate=False)
    env.favorite_color = (255, 0, 0)
    env.colors = [
        (0, 0, 0),       # furthest
        (127, 0, 0),     # closer
        (255, 0, 0)      # closest
    ]
    env.points = [140, 160, 180]
    env.states = [0, 1, 2]
    env.compute_rewards()
    
    assert env.rewards[2] == 100
    assert env.rewards[0] == 0
    
    # Reset env
    state = env.reset()
    assert state == 0
    
    # Step RIGHT from state 0 -> state 1
    next_state, reward = env.step("RIGHT")
    assert next_state == 1
    assert reward == env.rewards[1]
