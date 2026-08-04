"""Testing facade and pytest fixtures for SmartMotor emulation.

Co-authored-by: GPT-5, Aug 2026
"""

import os

import pytest

from smotoremu.sensors import get_sensor
from smotoremu.session import Session
from smotoremu.world import World

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def launch(sensor=None, world=None, clock="instant", seed=0, headed=False):
    world_obj = _load_world(world)
    session = Session(seed=seed, clock_mode=clock, world=world_obj)
    facade = SmartMotor(session=session, headed=headed)
    if sensor is not None:
        sensor_model = get_sensor(sensor)(rng=session.rng)
        sensor_model.attach(session.port, session.world, session.clock)
        facade.sensor = sensor_model
    return facade


class SmartMotor:
    def __init__(self, session, headed=False):
        self.session = session
        self.headed = headed
        self.sensor = None
        self.pot = session.pot
        self.battery = session.battery
        self.world = session.world
        self.trace = session.trace
        self.arm = ArmFacade(session)
        self.screen = ScreenFacade(session)
        self._closed = False

    def boot(self, entry="main"):
        self.session.boot(entry)

    def close(self):
        if self._closed:
            return
        self.session.stop()
        self._closed = True

    def press(self, name):
        self.session.buttons.press(name)

    def release(self, name):
        self.session.buttons.release(name)

    def click(self, name, hold_ms=120):
        self.session.buttons.click(name, hold_ms=hold_ms)

    def tilt(self, roll, pitch):
        if self.session.accel is None:
            raise RuntimeError("session has no accelerometer")
        self.session.accel.set_orientation(roll, pitch)


class ArmFacade:
    def __init__(self, session):
        self.session = session

    @property
    def angle(self):
        return self.session.servo.actual_angle


class ScreenFacade:
    def __init__(self, session):
        self.session = session

    def lines(self):
        return self.session.display.text_lines()

    def png(self, scale=4):
        return self.session.display.to_png(scale=scale)


@pytest.fixture
def sm():
    session = launch()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sm_color():
    session = launch(sensor="VEML6040", world="worlds/three_patches.json")
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sm_analog():
    session = launch(sensor="GROVE_LIGHT", world="worlds/three_patches.json")
    try:
        yield session
    finally:
        session.close()


def _load_world(world):
    if isinstance(world, World):
        return world
    if world is None:
        return World()
    path = os.fspath(world)
    candidates = [path]
    if not os.path.isabs(path):
        candidates.append(os.path.join(PACKAGE_DIR, path))
        if path.startswith("worlds/"):
            candidates.append(os.path.join(PACKAGE_DIR, path))
    for candidate in candidates:
        if os.path.exists(candidate):
            return World.load(candidate)
    raise FileNotFoundError(f"world file not found: {world}")
