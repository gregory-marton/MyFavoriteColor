"""T006/T007: machine + I2C shim. Written before smotoremu/machine_shim.py exists.

Enough to run the real ssd1306.py, servo.py, and adxl345.py unmodified --
in particular SoftI2C needs writeto()/writevto() (what SSD1306_I2C.write_cmd
and .write_data actually call), which tests/fakes/machine.py -- built for
the existing device-code test suite -- does not implement, since that suite
never drives a real SSD1306 write.
"""

from smotoremu.machine_shim import ADC, PWM, Pin, SoftI2C


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
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    i2c.writeto(0x3C, bytearray([0x80, 0xAE]))
    assert i2c.last_writeto == (0x3C, bytearray([0x80, 0xAE]))


def test_soft_i2c_writevto_records_the_concatenated_write():
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    i2c.writevto(0x3C, [b"@", bytearray([1, 2, 3])])
    assert i2c.last_writevto == (0x3C, b"@" + bytearray([1, 2, 3]))


def test_soft_i2c_scan_returns_configured_devices():
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    i2c.set_devices([0x3C, 0x53])
    assert i2c.scan() == [0x3C, 0x53]
