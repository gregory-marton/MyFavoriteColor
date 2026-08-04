"""VEML6040 colour sensor plug-in.

Co-authored-by: GPT-5, Aug 2026
"""

import random

from smotoremu.i2c import I2CDevice
from smotoremu.sensors import SensorModel, register

REG_CONF = 0x00
REG_R = 0x08
REG_G = 0x09
REG_B = 0x0A
REG_W = 0x0B

SD_MASK = 0x01
IT_MASK = 0x70
LSB_PER_RGB_UNIT = 64


@register("VEML6040")
class VEML6040Model(SensorModel, I2CDevice):
    display_name = "VEML6040 Colour Sensor"
    interface = "i2c"
    i2c_address = 0x10

    def __init__(self, rng=None, noise_lsb=None):
        calibration = self.calibration()
        self.device = self
        self.rng = rng or random.Random(0)
        self.noise_lsb = calibration.get("noise_lsb", 0) if noise_lsb is None else noise_lsb
        self.sensitivity = calibration["sensitivity"]
        self.dark_counts = calibration["dark_counts"]
        self.conf = 0
        self.pointer = 0
        self.latched_counts = (0, 0, 0, 0)
        self._next_conversion_us = None
        self.port = None
        self.world = None
        self.clock = None

    def attach(self, port, world, clock):
        self.port = port
        self.world = world
        self.clock = clock
        port.attach(self)
        self._schedule_next_conversion()

    @classmethod
    def ui_schema(cls):
        return {
            "fields": [
                {"name": "integration_time_ms", "type": "number"},
                {"name": "noise_lsb", "type": "number"},
            ]
        }

    def on_write(self, data: bytes, is_continuation: bool = False):
        if not data:
            return
        self.pointer = data[0]
        if self.pointer == REG_CONF and len(data) >= 3:
            self.conf = int.from_bytes(data[1:3], "little")
            if not self._shutdown:
                self._schedule_next_conversion()

    def on_read(self, n: int) -> bytes:
        self._update_conversion()
        registers = {
            REG_CONF: self.conf,
            REG_R: self.latched_counts[0],
            REG_G: self.latched_counts[1],
            REG_B: self.latched_counts[2],
            REG_W: self.latched_counts[3],
        }
        value = registers.get(self.pointer, 0)
        return value.to_bytes(2, "little")[:n].ljust(n, b"\x00")

    @property
    def _shutdown(self):
        return bool(self.conf & SD_MASK)

    @property
    def integration_time_ms(self):
        shift = (self.conf & IT_MASK) >> 4
        return 40 << shift

    def _schedule_next_conversion(self):
        if self.clock is None or self._shutdown:
            return
        self._next_conversion_us = self.clock.now_us + self.integration_time_ms * 1000

    def _update_conversion(self):
        if self.clock is None or self._shutdown or self._next_conversion_us is None:
            return
        if self.clock.now_us < self._next_conversion_us:
            return
        self.latched_counts = self._measure()
        self._next_conversion_us = self.clock.now_us + self.integration_time_ms * 1000

    def _measure(self):
        if self.world is None:
            rgb = (255, 255, 255)
            lux = 300
        else:
            angle = 0
            rgb = self.world.color_at(angle)
            lux = self.world.lux_at(angle)
        reflectance = {
            "red": rgb[0] / 255,
            "green": rgb[1] / 255,
            "blue": rgb[2] / 255,
            "white": sum(rgb) / (3 * 255),
        }
        scale = self.integration_time_ms / 40
        return tuple(
            _clamp_u16(
                self.sensitivity[channel] * reflectance[channel] * lux * scale
                + self.dark_counts[channel]
                + self._noise()
            )
            for channel in ("red", "green", "blue", "white")
        )

    def _noise(self):
        if self.noise_lsb <= 0:
            return 0
        return self.rng.randint(-self.noise_lsb, self.noise_lsb)


def _clamp_u16(value):
    return min(65535, max(0, int(round(value))))
