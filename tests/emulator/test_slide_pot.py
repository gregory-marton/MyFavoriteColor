"""T020 Grove slide potentiometer plug-in tests.

Co-authored-by: GPT-5, Aug 2026
"""

import random

from smotoremu.device_env import load_real_sensors
from smotoremu.machine_shim import Board, Pin
from smotoremu.port import Port
from smotoremu.sensors import get_sensor


def make_port():
    board = Board()
    Pin.use_board(board)
    return board, Port(board, board.i2c_bus)


def test_position_maps_to_adc_raw_values():
    sensor = get_sensor("GROVE_SLIDE_POT")(noise_lsb=0)

    sensor.set_position(0.0)
    assert sensor.output_raw() == 0

    sensor.set_position(0.5)
    assert sensor.output_raw() == 2048

    sensor.set_position(1.0)
    assert sensor.output_raw() == 4095


def test_noise_is_bounded_and_varies_per_read():
    sensor = get_sensor("GROVE_SLIDE_POT")(noise_lsb=8, rng=random.Random(0))
    sensor.set_position(0.5)

    readings = [sensor.output_raw() for _ in range(40)]

    assert all(0 <= reading <= 4095 for reading in readings)
    assert len(set(readings)) > 1
    assert all(abs(reading - 2048) <= 32 for reading in readings)


def test_attachment_probe_reports_attached_at_rail_and_mid_positions():
    for position in (0.0, 0.5, 1.0):
        _, port = make_port()
        sensor = get_sensor("GROVE_SLIDE_POT")(noise_lsb=0)
        sensor.set_position(position)
        sensor.attach(port, world=None, clock=port.board.clock)
        real_sensors = load_real_sensors().SENSORS()

        assert real_sensors.attached is True


def test_rail_position_zero_truth_table_keeps_sensor_attached():
    board, port = make_port()
    sensor = get_sensor("GROVE_SLIDE_POT")(noise_lsb=0)
    sensor.set_position(0.0)
    sensor.attach(port, world=None, clock=board.clock)

    board.pin_value(5, 0)
    low = port.pin5_adc()
    board.pin_value(5, 1)
    high = port.pin5_adc()

    assert low < 200
    assert high < 200
    assert not (low < 200 and high > 4000)


def test_ui_schema_exposes_slider():
    schema = get_sensor("GROVE_SLIDE_POT").ui_schema()

    assert schema["fields"] == [
        {"name": "position", "type": "slider", "min": 0.0, "max": 1.0}
    ]
