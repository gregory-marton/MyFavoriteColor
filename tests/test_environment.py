import pytest
import standalone

def test_environment_dynamic_rewards():
    favorite_color = (255, 0, 0)
    # Calibrated states colors
    points = [
        [0, 0, 0],       # furthest (distance ~ 255), reward = 0
        [127, 0, 0],     # closer (distance ~ 128), reward = 100
        [255, 0, 0]      # closest (distance = 0), reward = 200
    ]
    indices = [0, 1, 2]
    
    # Initialize Environment
    env = standalone.Environment(points, indices, favorite_color, distance_metric="Euclidean")
    
    # Verify rewards calculation
    assert env.highest_reward_state == 2
    assert env.state_rewards[2] == 200
    assert env.state_rewards[0] == 0
    assert env.goal_state == [2]
    
    # Mock sensor rgb to return [255, 0, 0] (State 2)
    standalone.sensor.read_rgbw = lambda: (16384, 0, 0, 0) # 16384 >> 6 = 256 -> max 255
    
    # Reset env
    state = env.reset()
    assert state == 2
    
    # Step LEFT
    # Since start angle is 180 (State 0), step left moves it to max(0, 180 - 20) = 160 (State 1)
    env.current_angle = 180
    env.current_state = 0
    next_state, reward, done = env.step("LEFT")
    # nearestNeighbor will return 2 because sensor is mocked to return (255,0,0)
    assert next_state == 2
    assert reward == 200
    assert done is True
