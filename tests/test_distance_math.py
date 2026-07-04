import pytest
import standalone

def test_distance_functions():
    c1 = (100, 100, 100)
    c2 = (100, 100, 100)
    assert standalone.dist_euclidean(c1, c2) == 0.0
    assert standalone.dist_perceptual(c1, c2) == 0.0

    c3 = (200, 100, 100)
    # Euclidean: sqrt((200-100)^2) = 100
    assert standalone.dist_euclidean(c1, c3) == 100.0
    # Perceptual: sqrt(0.3 * (200-100)^2) = sqrt(3000) approx 54.77
    assert pytest.approx(standalone.dist_perceptual(c1, c3), 0.01) == 54.77

def test_compute_state_rewards():
    favorite = (255, 0, 0)
    states = [
        (255, 0, 0),   # exact match: dist = 0, reward = 200
        (127, 0, 0),   # dist = 128
        (0, 0, 0)      # max dist = 255, reward = 0
    ]
    rewards, dists = standalone.compute_state_rewards(states, favorite, standalone.dist_euclidean)
    assert rewards[0] == 200
    assert rewards[2] == 0
    assert rewards[1] == 100 # approx half reward
