import pytest
import myfavcolor

def test_environment_dynamic_rewards(monkeypatch):
    # Mock hardware init to prevent endless loops in testing
    monkeypatch.setattr(myfavcolor.Environment, "capture_favorite_color", lambda self: None)
    monkeypatch.setattr(myfavcolor.Environment, "calibrate_states", lambda self: None)
    
    env = myfavcolor.Environment(distance_metric="Euclidean")
    env.favorite_color = (255, 0, 0)
    env.colors = [
        (0, 0, 0),       # furthest
        (127, 0, 0),     # closer
        (255, 0, 0)      # closest
    ]
    env.points = [140, 160, 180]
    env.action_space = ["LEFT", "RIGHT"]
    env.states = [0, 1, 2]
    # mock rewards exactly how calibrate_states does it:
    env.rewards = [env.reward(c)[1] for c in env.colors]
    
    assert env.rewards[2] == 100
    assert env.rewards[0] == 0
    
    # Reset env
    state = env.reset()
    assert state == 0
    
    # Step RIGHT from state 0 -> state 1
    next_state, reward, done = env.step("RIGHT")
    assert next_state == 1
    assert reward == env.rewards[1]
    assert done is False
