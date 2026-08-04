"""T021 Grove light sensor plug-in tests.

Co-authored-by: GPT-5, Aug 2026
"""

import random

from smotoremu.device_env import load_real_sensors
from smotoremu.machine_shim import Board, Pin
from smotoremu.peripherals.inputs import Potentiometer
from smotoremu.port import Port
from smotoremu.sensors import get_sensor
from smotoremu.world import World


def make_attached_light(world, *, noise_lsb=0, rng=None):
    board = Board()
    Pin.use_board(board)
    pot = Potentiometer(board, noise_lsb=0)
    pot.set_raw(2048)
    port = Port(board, board.i2c_bus)
    sensor = get_sensor("GROVE_LIGHT")(noise_lsb=noise_lsb, rng=rng)
    sensor.attach(port, world, board.clock)
    return board, sensor


def white_world(ambient_lux):
    return World(
        ambient_lux=ambient_lux,
        patches=[{"from": 0, "to": 180, "color": "#ffffff", "name": "white"}],
        blur_deg=0,
    )


def test_light_sensor_output_is_monotonic_in_lux():
    _, low = make_attached_light(white_world(10))
    _, mid = make_attached_light(white_world(300))
    _, high = make_attached_light(white_world(3_000))

    assert low.output_raw() < mid.output_raw() < high.output_raw()


def test_light_sensor_saturates_at_high_lux():
    _, sensor = make_attached_light(white_world(1_000_000))

    assert sensor.output_raw() == 4095


def test_noise_is_per_read_but_bounded():
    _, sensor = make_attached_light(white_world(300), noise_lsb=8, rng=random.Random(0))

    readings = [sensor.output_raw() for _ in range(40)]
    center = sensor.raw_without_noise()

    assert len(set(readings)) > 1
    assert all(0 <= reading <= 4095 for reading in readings)
    assert all(abs(reading - center) <= 32 for reading in readings)


def test_real_readpoint_is_stable_against_sensor_noise():
    _, _ = make_attached_light(white_world(300), noise_lsb=8, rng=random.Random(0))
    real_sensors = load_real_sensors().SENSORS()

    first = real_sensors.readpoint()
    second = real_sensors.readpoint()

    assert abs(first[0] - second[0]) < 4
    assert first[1] == second[1]


def test_real_readpoint_moves_up_when_world_lux_increases():
    world = white_world(50)
    _, sensor = make_attached_light(world, noise_lsb=0)
    real_sensors = load_real_sensors().SENSORS()

    dim = real_sensors.readpoint()
    sensor.world = white_world(2_000)
    bright = real_sensors.readpoint()

    assert bright[0] > dim[0]
