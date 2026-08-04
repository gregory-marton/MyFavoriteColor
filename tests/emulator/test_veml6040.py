"""T019 VEML6040 colour sensor plug-in tests.

Co-authored-by: GPT-5, Aug 2026
"""

import importlib

import pytest

from smotoremu.machine_shim import Pin, SoftI2C
from smotoremu.session import Session
from smotoremu.sensors import get_sensor
from smotoremu.world import World


def make_session_with_veml(world):
    session = Session(world=world)
    sensor = get_sensor("VEML6040")()
    sensor.attach(session.port, session.world, session.clock)
    return session, sensor


def make_driver(session, integration_time=None):
    myfavcolor = importlib.import_module("myfavcolor")
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    kwargs = {}
    if integration_time is not None:
        kwargs["integration_time"] = integration_time
    return myfavcolor, myfavcolor.VEML6040(i2c, **kwargs)


def test_scan_includes_veml_and_real_driver_constructs():
    world = World(patches=[{"from": 0, "to": 180, "color": "#ffffff", "name": "white"}])
    session, _ = make_session_with_veml(world)
    myfavcolor, driver = make_driver(session)

    assert 0x10 in session.bus.scan()
    assert isinstance(driver, myfavcolor.VEML6040)


def test_conf_write_read_round_trips_it_640ms():
    world = World(patches=[{"from": 0, "to": 180, "color": "#ffffff", "name": "white"}])
    session, _ = make_session_with_veml(world)
    myfavcolor, driver = make_driver(session)

    driver.set_integration_time(myfavcolor.IT_640MS)

    assert driver._read_word(driver._VEML6040_REG_CONF) == myfavcolor.IT_640MS


def test_shutdown_freezes_latched_counts():
    red_world = World(patches=[{"from": 0, "to": 180, "color": "#ff0000", "name": "red"}], blur_deg=0)
    blue_world = World(patches=[{"from": 0, "to": 180, "color": "#0000ff", "name": "blue"}], blur_deg=0)
    session, sensor = make_session_with_veml(red_world)
    myfavcolor = importlib.import_module("myfavcolor")
    myfavcolor, driver = make_driver(session, integration_time=myfavcolor.IT_640MS)
    session.clock.sleep_us(640_000)
    red = driver.read_rgbw()

    driver._write_word(driver._VEML6040_REG_CONF, myfavcolor.IT_640MS | driver._SD_MASK)
    sensor.world = blue_world
    session.world = blue_world
    session.clock.sleep_us(1_000_000)

    assert driver.read_rgbw() == red


def test_integration_time_gating_latches_only_after_conversion_time():
    red_world = World(patches=[{"from": 0, "to": 180, "color": "#ff0000", "name": "red"}], blur_deg=0)
    blue_world = World(patches=[{"from": 0, "to": 180, "color": "#0000ff", "name": "blue"}], blur_deg=0)
    session, sensor = make_session_with_veml(red_world)
    myfavcolor = importlib.import_module("myfavcolor")
    myfavcolor, driver = make_driver(session, integration_time=myfavcolor.IT_640MS)

    session.clock.sleep_us(640_000)
    red = driver.rgb
    sensor.world = blue_world
    session.world = blue_world
    immediate = driver.rgb
    session.clock.sleep_us(640_000)
    blue = driver.rgb

    assert red[0] > red[2]
    assert immediate == red
    assert blue[2] > blue[0]


def test_real_white_balance_calibration_matches_measured_factors(monkeypatch):
    world = World(patches=[{"from": 0, "to": 180, "color": "#ffffff", "name": "white"}], blur_deg=0)
    session, _ = make_session_with_veml(world)
    myfavcolor = importlib.import_module("myfavcolor")
    myfavcolor, driver = make_driver(session, integration_time=myfavcolor.IT_640MS)
    session.clock.sleep_us(640_000)

    monkeypatch.setattr(myfavcolor, "sensor", driver)
    monkeypatch.setattr(myfavcolor, "sens", type("SensorStub", (), {"readpot": lambda self: 0})())
    button_states = iter([True, False])
    monkeypatch.setattr(myfavcolor, "checkbuttons", lambda: next(button_states, False))
    monkeypatch.setattr(myfavcolor, "screen", lambda lines: None)
    monkeypatch.setattr(myfavcolor, "move_servo", lambda angle: angle)

    env = myfavcolor.Environment(auto_calibrate=False)
    env.calibrate_white_balance()
    wr, wg, wb = driver.white_balance
    normalized = (wr / wr, wg / wr, wb / wr)

    assert normalized[0] == pytest.approx(1.0)
    assert normalized[1] == pytest.approx(1.066, rel=0.15)
    assert normalized[2] == pytest.approx(1.948, rel=0.15)


def test_extremely_bright_world_saturates_raw_and_scaled_rgb():
    world = World(
        ambient_lux=100_000,
        patches=[{"from": 0, "to": 180, "color": "#ffffff", "name": "white"}],
        blur_deg=0,
    )
    session, _ = make_session_with_veml(world)
    myfavcolor = importlib.import_module("myfavcolor")
    myfavcolor, driver = make_driver(session, integration_time=myfavcolor.IT_640MS)

    session.clock.sleep_us(640_000)

    assert driver.read_rgbw()[:3] == (65535, 65535, 65535)
    assert driver.rgb == (255, 255, 255)
