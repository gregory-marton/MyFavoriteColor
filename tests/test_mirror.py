"""Pure behavior tests for the standalone physical mirror firmware.

Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import mirror


def test_pot_maps_to_servo_angle():
    assert mirror.pot_to_angle(0) == 0
    assert mirror.pot_to_angle(2048) == 90
    assert mirror.pot_to_angle(4095) == 180


def test_mirror_uses_observed_physical_button_labels():
    assert mirror.MIRROR_BUTTON_PINS == {"up": 8, "down": 10, "select": 9}


def test_sensor_presence_uses_the_sensor_port_probe():
    assert mirror.sensor_attached(50, 4090) is False
    assert mirror.sensor_attached(500, 500) is True
    assert mirror.port_mode(50, 4090) == "i2c "
    assert mirror.port_mode(500, 500) == "anlg"


def test_device_numbers_are_two_significant_digits():
    assert mirror.short_number(2048) == "2.0k"
    assert mirror.short_number(65535) == "66k"
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


def test_failed_i2c_sensor_initialization_falls_back_to_analog_mode():
    class BrokenI2C:
        def scan(self):
            return [0x10]

        def writeto_mem(self, address, register, data):
            raise OSError("not a VEML6040")

    mode, sensor = mirror.initialize_i2c_sensor(BrokenI2C(), "i2c ")

    assert mode == "anlg"
    assert sensor is None


def test_delta_symbols_show_three_accelerometer_axes():
    assert mirror.delta_symbols((0, 0, 0), (100, -100, 100)) == "X^ Yv Z^"
    assert mirror.delta_symbols((0, 0, 0), (0, 0, 0)) == "X  Y  Z "


def test_delta_hysteresis_uses_1_1_percent_enter_and_0_9_percent_exit():
    text, states = mirror.delta_display((0, 0, 0), (12, 0, 0))
    assert text == "X^ Y  Z "
    assert states[0] == "^"

    text, states = mirror.delta_display((0, 0, 0), (10, 0, 0), states)
    assert text == "X^ Y  Z "
    assert states[0] == "^"

    text, states = mirror.delta_display((0, 0, 0), (8, 0, 0), states)
    assert text == "X~ Y  Z "
    assert states[0] == "~"


def test_screen_lines_show_power_usb_i2c_sensor_controls_and_motion():
    lines = mirror.screen_lines(
        battery_v=4.16,
        usb=True,
        port_mode="i2c ",
        sensor_is_attached=True,
        sensor_value=2345,
        pot=2048,
        angle=90,
        buttons={"up": 0, "down": 1, "select": 1},
        delta="X^ Yv Z^",
    )

    assert lines == (
        "4.2V USB+",
        "MODE i2c  SNS2.3k",
        "POT 20 ANG090",
        "BTN UP+ DN- SCT-",
        "MOVE X^ Yv Z^",
    )


def test_screen_lines_shows_unknown_battery_and_no_usb():
    lines = mirror.screen_lines(
        battery_v=None,
        usb=False,
        port_mode="anlg",
        sensor_is_attached=False,
        sensor_value=-1,
        pot=0,
        angle=0,
        buttons={"up": 1, "down": 1, "select": 1},
        delta=None,
    )

    assert lines[0] == "?V USBx"
    assert lines[2] == "POT 00 ANG000"
    assert lines[3] == "BTN UP- DN- SCT-"
