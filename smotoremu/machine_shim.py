"""T006/T007: machine + I2C shim -- enough to run ssd1306.py, servo.py, and
adxl345.py unmodified.

Unlike tests/fakes/machine.py (built for the existing device-code test
suite, which never drives a real SSD1306 write), SoftI2C here implements
writeto()/writevto() -- what SSD1306_I2C.write_cmd/.write_data actually
call -- and simply records what was written rather than interpreting the
SSD1306 command protocol. That's a deliberate simplification: ssd1306.py's
show() always writes the *entire* framebuffer in one write_data call after
setting the column/page range to full, so the emulator's replay renderer
reads the real FrameBuffer's own `buffer` attribute directly rather than
reconstructing GDDRAM from the I2C byte stream.
"""


class Pin:
    IN = "IN"
    OUT = "OUT"

    def __init__(self, id, mode=IN, pull=-1, value=None):
        self.id = id
        self.mode = mode
        self._value = value if value is not None else (1 if mode == Pin.IN else 0)

    def value(self, val=None):
        if val is not None:
            self._value = val
        return self._value

    def __call__(self, val=None):
        return self.value(val)


class ADC:
    ATTN_11DB = "11DB"

    def __init__(self, pin):
        self.pin = pin
        self._value = 2048

    def atten(self, level):
        pass

    def set_value(self, v):
        self._value = v

    def read(self):
        return self._value

    def read_uv(self):
        return self._value * 1000  # rough proxy; not used by the OLED path


class PWM:
    def __init__(self, pin, freq=50, duty=0):
        self.pin = pin
        self.freq = freq
        self._duty = duty

    def duty(self, val=None):
        if val is not None:
            self._duty = val
        return self._duty


class SoftI2C:
    def __init__(self, scl, sda, freq=400000):
        self.scl = scl
        self.sda = sda
        self.freq = freq
        self.last_writeto = None
        self.last_writevto = None
        self._devices = []

    def set_devices(self, addrs):
        self._devices = list(addrs)

    def scan(self):
        return list(self._devices)

    def writeto(self, addr, buf):
        self.last_writeto = (addr, buf)

    def writevto(self, addr, vector):
        combined = b"".join(bytes(part) for part in vector)
        self.last_writevto = (addr, combined)

    def readfrom_mem(self, addr, memaddr, nbytes):
        return b"\x00" * nbytes

    def writeto_mem(self, addr, memaddr, buf):
        pass


class I2C(SoftI2C):
    pass


def unique_id():
    return b"\xac\x27\x6e\x7c\xb6\x98"


def const(x):
    return x
