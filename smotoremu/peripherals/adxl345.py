"""ADXL345 accelerometer I2C peripheral model.

Co-authored-by: GPT-5, Aug 2026
"""

import math
import random

from smotoremu.i2c import I2CDevice

REG_POWER_CTL = 0x2D
REG_DATA = 0x32
LSB_PER_G = 256


class ADXL345Device(I2CDevice):
    def __init__(self, noise_lsb=2, rng=None):
        self.noise_lsb = noise_lsb
        self.rng = rng or random.Random(0)
        self.pointer = 0
        self.power_control = 0
        self.power_control_writes = []
        self._gravity = (0.0, 0.0, 1.0)

    def set_orientation(self, roll_deg: float, pitch_deg: float) -> None:
        roll = math.radians(roll_deg)
        pitch = math.radians(pitch_deg)
        x = -math.sin(pitch)
        y = math.sin(roll) * math.cos(pitch)
        z = math.cos(roll) * math.cos(pitch)
        self.set_gravity(x, y, z)

    def set_gravity(self, x: float, y: float, z: float) -> None:
        self._gravity = (x, y, z)

    def on_write(self, data: bytes, is_continuation: bool = False):
        if not data:
            return
        self.pointer = data[0]
        if self.pointer == REG_POWER_CTL and len(data) > 1:
            self.power_control = data[1]
            self.power_control_writes.append(data[1])

    def on_read(self, n: int) -> bytes:
        if self.pointer != REG_DATA:
            return bytes(n)
        payload = b"".join(_int16le(value) for value in self._raw_axes())
        return payload[:n].ljust(n, b"\x00")

    def _raw_axes(self):
        return tuple(
            int(round(axis_g * LSB_PER_G)) + self._noise()
            for axis_g in self._gravity
        )

    def _noise(self):
        if self.noise_lsb <= 0:
            return 0
        return self.rng.randint(-self.noise_lsb, self.noise_lsb)


def _int16le(value):
    value = min(32767, max(-32768, value))
    return int(value).to_bytes(2, "little", signed=True)
