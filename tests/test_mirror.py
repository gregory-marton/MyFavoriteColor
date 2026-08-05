"""Pure behavior tests for the standalone physical mirror firmware.

Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import mirror


def test_pot_maps_to_servo_angle():
    assert mirror.pot_to_angle(0) == 0
    assert mirror.pot_to_angle(2048) == 90
    assert mirror.pot_to_angle(4095) == 180


def test_sensor_presence_uses_the_sensor_port_probe():
    assert mirror.sensor_attached(50, 4090) is False
    assert mirror.sensor_attached(500, 500) is True
    assert mirror.port_mode(50, 4090) == "i2c"
    assert mirror.port_mode(500, 500) == "alg"


def test_device_numbers_are_two_significant_digits():
    assert mirror.short_number(2048) == "2.0k"
    assert mirror.short_number(90) == "90"
    assert mirror.short_number(1.25) == "1.2"


def test_i2c_sensor_reads_full_rgbw_words():
    class FakeI2C:
        def scan(self):
            return [0x10]

        def writeto_mem(self, address, register, data):
            assert address == 0x10

        def readfrom_mem(self, address, register, length):
            values = {8: 0x1234, 9: 0x2345, 10: 0x3456, 11: 0x4567}
            value = values[register]
            return bytes((value & 0xFF, value >> 8))

    sensor = mirror.I2CSensor(FakeI2C())

    assert sensor.read_rgbw() == (0x1234, 0x2345, 0x3456, 0x4567)


def test_delta_symbols_show_three_accelerometer_axes():
    assert mirror.delta_symbols((0, 0, 0), (100, -100, 100)) == ">vJ"
    assert mirror.delta_symbols((0, 0, 0), (10, 10, 10)) == ""


def test_screen_lines_show_power_usb_i2c_sensor_controls_and_motion():
    lines = mirror.screen_lines(
        power=True,
        usb=True,
        port_mode="i2c",
        sensor_is_attached=True,
        sensor_value=2345,
        pot=2048,
        angle=90,
        buttons={"up": 0, "down": 1, "select": 1},
        delta=">vJ",
    )

    assert lines == (
        "PWR ON USB ON",
        "MODE i2c SNS2.3k",
        "POT2.0k ANG90",
        "BTN UP",
        "MOVE >vJ",
    )
