"""T017 sensor port and attachment probing tests.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.device_env import load_real_sensors
from smotoremu.i2c import I2CDevice
from smotoremu.machine_shim import Board, Pin
from smotoremu.port import Port


class AnalogStub:
    def output_raw(self):
        return 2048


class I2CStub:
    i2c_address = 0x10

    def __init__(self):
        self.device = I2CDevice()


def make_board_and_port():
    board = Board()
    Pin.use_board(board)
    return board, Port(board, board.i2c_bus)


def test_real_selectsensor_reports_false_when_nothing_attached():
    _, _ = make_board_and_port()
    sensors = load_real_sensors()

    real_sensors = sensors.SENSORS()

    assert real_sensors.attached is False


def test_real_selectsensor_reports_true_with_midscale_analog_sensor():
    _, port = make_board_and_port()
    port.attach(AnalogStub())
    sensors = load_real_sensors()

    real_sensors = sensors.SENSORS()

    assert real_sensors.attached is True


def test_pin5_adc_follows_drive_when_nothing_attached():
    board, port = make_board_and_port()

    board.pin_value(5, 0)
    assert port.pin5_adc() == 0

    board.pin_value(5, 1)
    assert port.pin5_adc() == 4095


def test_analog_i2c_toggle_gates_i2c_sensor_on_bus():
    _, port = make_board_and_port()
    sensor = I2CStub()

    port.attach(sensor)
    assert 0x10 in port.bus.scan()

    port.set_mode("analog")
    assert 0x10 not in port.bus.scan()

    port.set_mode("i2c")
    assert 0x10 in port.bus.scan()
