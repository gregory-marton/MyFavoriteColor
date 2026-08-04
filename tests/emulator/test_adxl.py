"""T012 ADXL345 accelerometer peripheral tests.

Co-authored-by: GPT-5, Aug 2026
"""

import random
import io

import pytest

from smotoremu.device_env import load_real_adxl345, load_real_sensors
from smotoremu.machine_shim import Board, Pin, SoftI2C
from smotoremu.peripherals.adxl345 import ADXL345Device
import smirror


def make_bus_with_adxl(**kwargs):
    board = Board()
    Pin.use_board(board)
    device = ADXL345Device(**kwargs)
    board.i2c_bus.register(0x53, device)
    return board, device, SoftI2C(scl=Pin(7), sda=Pin(6))


def test_flat_level_reads_zero_zero_one_g():
    _, device, i2c = make_bus_with_adxl(noise_lsb=0)
    adxl = load_real_adxl345().ADXL345(i2c)

    assert (adxl.xValue, adxl.yValue, adxl.zValue) == (0, 0, 256)
    assert device.power_control_writes == [0, 16, 8]


def test_orientation_round_trips_through_real_roll_pitch_math():
    _, device, i2c = make_bus_with_adxl(noise_lsb=0)
    adxl = load_real_adxl345().ADXL345(i2c)

    device.set_orientation(30, -20)
    roll, pitch = adxl.RP_calculate(adxl.xValue, adxl.yValue, adxl.zValue)

    assert roll == pytest.approx(30, abs=1)
    assert pitch == pytest.approx(-20, abs=1)


def test_noise_is_bounded_per_axis():
    _, device, i2c = make_bus_with_adxl(noise_lsb=2, rng=random.Random(0))
    adxl = load_real_adxl345().ADXL345(i2c)

    samples = [(adxl.xValue, adxl.yValue, adxl.zValue) for _ in range(20)]

    assert len(set(samples)) > 1
    for x, y, z in samples:
        assert -2 <= x <= 2
        assert -2 <= y <= 2
        assert 254 <= z <= 258


def test_gravity_setter_uses_g_units():
    _, device, i2c = make_bus_with_adxl(noise_lsb=0)
    adxl = load_real_adxl345().ADXL345(i2c)

    device.set_gravity(0.5, -0.25, 1.0)

    assert (adxl.xValue, adxl.yValue, adxl.zValue) == (128, -64, 256)


def test_absent_accelerometer_constructs_sensors_with_none_adx():
    board = Board()
    Pin.use_board(board)
    sensors = load_real_sensors()

    real_sensors = sensors.SENSORS()

    assert real_sensors.adx is None


def test_burst_read_supports_live_mirror_telemetry():
    _, device, i2c = make_bus_with_adxl(noise_lsb=0)
    adxl = load_real_adxl345().ADXL345(i2c)
    output = io.StringIO()
    smirror.set_writer(output)
    device.set_orientation(30, -20)

    x, y, z = adxl.read()

    assert (x, y, z) != (0, 0, 0)
    assert output.getvalue() == f"@SMIRROR ACCEL {x} {y} {z}\n"


def test_activity_pot_reads_also_sample_accelerometer_for_mirror():
    board, device, _ = make_bus_with_adxl(noise_lsb=0)
    sensors_module = load_real_sensors()
    sensors = sensors_module.SENSORS()
    output = io.StringIO()
    smirror.set_writer(output)
    device.set_orientation(-25, 15)

    sensors.readpot()

    assert output.getvalue().startswith("@SMIRROR ACCEL ")
