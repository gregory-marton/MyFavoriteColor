import pytest
import myfavcolor

def test_distance_functions():
    c1 = (100, 100, 100)
    c2 = (100, 100, 100)
    assert myfavcolor.dist_euclidean(c1, c2) == 0.0
    assert myfavcolor.dist_perceptual(c1, c2) == 0.0

    c3 = (200, 100, 100)
    # Euclidean: sqrt((200-100)^2) = 100
    assert myfavcolor.dist_euclidean(c1, c3) == 100.0
    # Perceptual: sqrt(0.3 * (200-100)^2) = sqrt(3000) approx 54.77
    assert pytest.approx(myfavcolor.dist_perceptual(c1, c3), 0.01) == 54.77
