import pytest

def test_constants_defined():
    import standalone

    assert standalone.NUM_STATES == 7
    assert standalone.EPISODES == 10
    assert standalone.TIMESTEPS == 15
    assert standalone.COLOR_INTEGRATION_TIME == standalone.IT_640MS
    assert standalone.WHITE_BALANCE_RGB == (1.0, 1.066, 1.948)
    assert standalone.MOTOR_SETTLE_TIME == 2.0
    assert standalone.ALPHA == 0.1
    assert standalone.GAMMA == 0.9
    assert standalone.EPSILON == 0.1
    assert standalone.MAX_REWARD == 200
    assert standalone.START_ANGLE == 180
    assert standalone.POT_THRESHOLD == 2
