"""T006/T007/T008: machine + I2C shim -- enough to run ssd1306.py, servo.py,
adxl345.py, and timer-backed device code unmodified.

Unlike tests/fakes/machine.py (built for the existing device-code test
suite, which never drives a real SSD1306 write), SoftI2C here implements
writeto()/writevto() -- what SSD1306_I2C.write_cmd/.write_data actually
call -- and simply records what was written rather than interpreting the
SSD1306 command protocol. That's a deliberate simplification: ssd1306.py's
show() always writes the *entire* framebuffer in one write_data call after
setting the column/page range to full, so the emulator's replay renderer
reads the real FrameBuffer's own `buffer` attribute directly rather than
reconstructing GDDRAM from the I2C byte stream.

Timer callbacks run on the virtual scheduler, i.e. between device-code I/O
operations or explicit clock advancement, not truly pre-emptively. Real ISR
re-entrancy bugs will not reproduce in this shim.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.clock import EventScheduler, VirtualClock
from smotoremu.i2c import I2CBus, I2CDevice
from smotoremu.pinmap import BUTTON_PINS, KNOWN_PINS, PIN_SENSOR_PORT


class DeviceReset(RuntimeError):
    pass


class Board:
    ADC_SAMPLE_COST_US = 20  # GUESS: ESP32-C3 SAR ADC sample cost; needs bench data.

    def __init__(self, clock=None, unique_id=b"\x12\x34\x56\x78", trace=None):
        self.clock = clock or VirtualClock()
        self.trace = trace
        self.scheduler = EventScheduler(self.clock)
        self.pin_modes = {}
        self.pin_values = {pin: 1 for pin in BUTTON_PINS.values()}
        self.adc_values = {}
        self.adc_noise_callbacks = {}
        self.pwm_values = {}
        self.pwm_callbacks = {}
        self._port_adc_stub = None
        self.i2c_bus = I2CBus(clock=self.clock, trace=self.trace)
        self.timer_handles = {}
        self.set_unique_id(unique_id)

    def validate_pin(self, pin_id):
        if pin_id not in KNOWN_PINS:
            raise ValueError(f"unknown SmartMotor pin id {pin_id}")

    def set_pin_mode(self, pin_id, mode):
        self.validate_pin(pin_id)
        self.pin_modes[pin_id] = mode
        if pin_id not in self.pin_values:
            self.pin_values[pin_id] = 1 if mode == Pin.IN else 0

    def pin_value(self, pin_id, value=None):
        self.validate_pin(pin_id)
        if value is not None:
            self.pin_values[pin_id] = value
            self.record("pin", {"pin": pin_id, "value": value})
        return self.pin_values.get(pin_id, 1)

    def press(self, name):
        self.pin_value(BUTTON_PINS[name], 0)

    def release(self, name):
        self.pin_value(BUTTON_PINS[name], 1)

    def set_adc(self, pin_id, value):
        self.validate_pin(pin_id)
        self.adc_values[pin_id] = value

    def set_adc_noise(self, pin_id, callback):
        self.validate_pin(pin_id)
        self.adc_noise_callbacks[pin_id] = callback

    def set_port_adc_stub(self, callback):
        self._port_adc_stub = callback

    def adc_read(self, pin_id):
        self.validate_pin(pin_id)
        self.clock.sleep_us(self.ADC_SAMPLE_COST_US)
        if pin_id == PIN_SENSOR_PORT and self._port_adc_stub is not None:
            value = self._port_adc_stub(self.pin_values.get(PIN_SENSOR_PORT, 0))
        elif pin_id in self.adc_noise_callbacks:
            value = self.adc_noise_callbacks[pin_id]()
        else:
            value = self.adc_values.get(pin_id, 2048)
        self.record("adc", {"pin": pin_id, "value": value})
        return value

    def adc_read_uv(self, pin_id):
        return self.adc_read(pin_id) * 1000

    def pwm_set(self, pin_id, freq, duty):
        self.validate_pin(pin_id)
        self.pwm_values[pin_id] = {"freq": freq, "duty": duty}
        self.record("pwm", {"pin": pin_id, "freq": freq, "duty": duty})
        for callback in self.pwm_callbacks.get(pin_id, []):
            callback(pin_id, freq, duty)

    def on_pwm_change(self, pin_id, callback):
        self.validate_pin(pin_id)
        self.pwm_callbacks.setdefault(pin_id, []).append(callback)

    def set_unique_id(self, unique_id):
        if not isinstance(unique_id, (bytes, bytearray)) or len(unique_id) != 4:
            raise ValueError("unique_id must be exactly 4 bytes")
        self.unique_id = bytes(unique_id)

    def record(self, kind, detail):
        if self.trace is not None:
            self.trace.record(self.clock.now_us, kind, detail)


_DEFAULT_BOARD = Board()


def get_default_board():
    return _DEFAULT_BOARD


class Pin:
    IN = "IN"
    OUT = "OUT"
    _board = _DEFAULT_BOARD

    @classmethod
    def use_board(cls, board):
        cls._board = board

    def __init__(self, id, mode=IN, pull=-1, value=None):
        self._board.validate_pin(id)
        self.id = id
        self.mode = mode
        self._board.set_pin_mode(id, mode)
        if value is not None:
            self._board.pin_value(id, value)

    def value(self, val=None):
        return self._board.pin_value(self.id, val)

    def __call__(self, val=None):
        return self.value(val)


class ADC:
    ATTN_11DB = "11DB"

    def __init__(self, pin):
        self.pin = pin
        self._board = Pin._board
        self._value = 2048

    def atten(self, level):
        pass

    def set_value(self, v):
        self._value = v
        self._board.set_adc(self.pin.id, v)

    def read(self):
        return self._board.adc_read(self.pin.id)

    def read_uv(self):
        return self._board.adc_read_uv(self.pin.id)


class PWM:
    def __init__(self, pin, freq=50, duty=0):
        self.pin = pin
        self._board = Pin._board
        self.freq = freq
        self._duty = duty
        self._board.pwm_set(self.pin.id, self.freq, self._duty)

    def duty(self, val=None):
        if val is not None:
            self._duty = val
            self._board.pwm_set(self.pin.id, self.freq, self._duty)
        return self._duty


class Timer:
    ONE_SHOT = 0
    PERIODIC = 1

    def __init__(self, id):
        self.id = id
        self._board = Pin._board

    def init(self, period=1000, mode=PERIODIC, callback=None):
        if period <= 0:
            raise ValueError("period must be positive")
        if mode not in {self.ONE_SHOT, self.PERIODIC}:
            raise ValueError("unsupported timer mode")
        self.deinit()
        period_us = period * 1000

        def fire():
            self._board.record("timer", {"id": self.id, "action": "fire"})
            if callback is not None:
                callback(self)

        if mode == self.PERIODIC:
            handle = self._board.scheduler.every(period_us, fire)
        else:
            handle = self._board.scheduler.after(period_us, fire)
        self._board.timer_handles[self.id] = handle

    def deinit(self):
        handle = self._board.timer_handles.pop(self.id, None)
        if handle is not None:
            self._board.scheduler.cancel(handle)
            self._board.record("timer", {"id": self.id, "action": "deinit"})


class SoftI2C:
    def __init__(self, scl, sda, freq=400000):
        self.scl = scl
        self.sda = sda
        self.freq = freq
        self._board = Pin._board
        self._board.i2c_bus.freq = freq
        self.last_writeto = None
        self.last_writevto = None

    def set_devices(self, addrs):
        self._board.i2c_bus.devices = {}
        for addr in addrs:
            self._board.i2c_bus.register(addr, I2CDevice())

    def scan(self):
        return self._board.i2c_bus.scan()

    def writeto(self, addr, buf):
        self.last_writeto = (addr, buf)
        self._board.i2c_bus.writeto(addr, buf)

    def writevto(self, addr, vector):
        combined = b"".join(bytes(part) for part in vector)
        self.last_writevto = (addr, combined)
        self._board.i2c_bus.writevto(addr, vector)

    def readfrom(self, addr, nbytes):
        return self._board.i2c_bus.readfrom(addr, nbytes)

    def readfrom_mem(self, addr, memaddr, nbytes):
        return self._board.i2c_bus.readfrom_mem(addr, memaddr, nbytes)

    def writeto_mem(self, addr, memaddr, buf):
        self._board.i2c_bus.writeto_mem(addr, memaddr, buf)


class I2C(SoftI2C):
    pass


def unique_id():
    return Pin._board.unique_id


def reset():
    raise DeviceReset()


def const(x):
    return x
