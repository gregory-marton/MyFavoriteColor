"""T022 public smotor facade tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pytest

import smotor


def test_launch_returns_working_bare_session():
    sm = smotor.launch(seed=123)
    try:
        assert sm.session.seed == 123
        assert sm.world is not None
        sm.press("up")
        assert sm.session.buttons.held() == {"up"}
        sm.release("up")
        assert sm.session.buttons.held() == set()
        sm.pot.set_angle(90)
        sm.battery.set_state("low")
        sm.tilt(10, -5)
        assert sm.trace.events[0]["kind"] == "header"
    finally:
        sm.close()


def test_launch_with_color_sensor_and_world_attaches_veml6040():
    sm = smotor.launch(sensor="VEML6040", world="worlds/three_patches.json")
    try:
        assert sm.session.port.attached is not None
        assert 0x10 in sm.session.bus.scan()
        assert sm.world.patch_at(10).name == "red patch"
    finally:
        sm.close()


def test_launch_with_unknown_sensor_raises_helpful_error():
    with pytest.raises(KeyError, match="VEML6040"):
        smotor.launch(sensor="NOPE")


def test_close_is_idempotent():
    sm = smotor.launch()

    sm.close()
    sm.close()


def test_two_sequential_sessions_are_independent():
    first = smotor.launch(seed=1)
    first.press("select")
    first.close()

    second = smotor.launch(seed=2)
    try:
        assert second.session.seed == 2
        assert second.session.buttons.held() == set()
    finally:
        second.close()


def test_screen_helpers_return_lines_and_png():
    sm = smotor.launch()
    try:
        assert sm.screen.lines() == []
        assert sm.screen.png().startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        sm.close()


def test_sm_fixture_yields_bare_session(sm):
    assert sm.session.port.attached is None


def test_sm_color_fixture_yields_veml6040_session(sm_color):
    assert 0x10 in sm_color.session.bus.scan()


def test_sm_analog_fixture_yields_light_sensor_session(sm_analog):
    assert sm_analog.session.port.attached.interface == "analog"
