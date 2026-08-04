"""T006/T007: machine + I2C shim. Written before smotoremu/machine_shim.py exists.

Enough to run the real ssd1306.py, servo.py, and adxl345.py unmodified --
in particular SoftI2C needs writeto()/writevto() (what SSD1306_I2C.write_cmd
and .write_data actually call), which tests/fakes/machine.py -- built for
the existing device-code test suite -- does not implement, since that suite
never drives a real SSD1306 write.
"""

import pytest

from smotoremu.clock import VirtualClock
from smotoremu.i2c import I2CDevice
from smotoremu.machine_shim import ADC, Board, PWM, Pin, SoftI2C
from smotoremu.pinmap import PIN_BUTTON_UP, PIN_SENSOR_PORT, PIN_SERVO


def test_pin_in_defaults_high_like_pullup_switches():
    p = Pin(8, Pin.IN)
    assert p.value() == 1


def test_pin_out_value_round_trips():
    p = Pin(2, Pin.OUT)
    p.value(1)
    assert p.value() == 1
    p.value(0)
    assert p.value() == 0


def test_adc_read_returns_configured_value():
    p = Pin(3)
    a = ADC(p)
    a.atten(ADC.ATTN_11DB)
    a.set_value(2048)
    assert a.read() == 2048


def test_pwm_duty_round_trips():
    p = Pin(2, Pin.OUT)
    pwm = PWM(p, freq=50, duty=0)
    pwm.duty(512)
    assert pwm.duty() == 512


def test_soft_i2c_writeto_records_the_write():
    board = Board()
    Pin.use_board(board)
    board.i2c_bus.register(0x3C, I2CDevice())
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    i2c.writeto(0x3C, bytearray([0x80, 0xAE]))
    assert i2c.last_writeto == (0x3C, bytearray([0x80, 0xAE]))


def test_soft_i2c_writevto_records_the_concatenated_write():
    board = Board()
    Pin.use_board(board)
    board.i2c_bus.register(0x3C, I2CDevice())
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    i2c.writevto(0x3C, [b"@", bytearray([1, 2, 3])])
    assert i2c.last_writevto == (0x3C, b"@" + bytearray([1, 2, 3]))


def test_soft_i2c_scan_returns_configured_devices():
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    i2c.set_devices([0x3C, 0x53])
    assert i2c.scan() == [0x3C, 0x53]


def test_board_button_press_drives_active_low_pin():
    board = Board()
    Pin.use_board(board)

    assert Pin(PIN_BUTTON_UP, Pin.IN).value() == 1
    board.press("up")
    assert Pin(PIN_BUTTON_UP, Pin.IN).value() == 0
    board.release("up")
    assert Pin(PIN_BUTTON_UP, Pin.IN).value() == 1


def test_pin5_output_then_adc_uses_port_model_stub():
    board = Board()
    Pin.use_board(board)
    board.set_port_adc_stub(lambda digital_value: 1234 if digital_value else 4321)

    Pin(PIN_SENSOR_PORT, Pin.OUT).value(1)

    assert ADC(Pin(PIN_SENSOR_PORT)).read() == 1234


def test_pwm_change_callback_fires_for_servo_pin():
    board = Board()
    Pin.use_board(board)
    seen = []
    board.on_pwm_change(PIN_SERVO, lambda pin_id, freq, duty: seen.append((pin_id, freq, duty)))

    PWM(Pin(PIN_SERVO), freq=50, duty=61)

    assert seen == [(PIN_SERVO, 50, 61)]


def test_adc_read_advances_virtual_clock_by_sample_cost():
    clock = VirtualClock()
    board = Board(clock=clock)
    Pin.use_board(board)
    board.set_adc(PIN_SENSOR_PORT, 2048)

    assert ADC(Pin(PIN_SENSOR_PORT)).read() == 2048
    assert clock.now_us == board.ADC_SAMPLE_COST_US


def test_unknown_pin_id_raises():
    with pytest.raises(ValueError):
        Pin(99)
