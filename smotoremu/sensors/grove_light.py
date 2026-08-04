"""Grove light sensor analog plug-in.

Co-authored-by: GPT-5, Aug 2026
"""

import math
import random

from smotoremu.sensors import SensorModel, register


@register("GROVE_LIGHT")
class GroveLightModel(SensorModel):
    display_name = "Grove Light Sensor"
    interface = "analog"

    def __init__(self, noise_lsb=None, rng=None):
        calibration = self.calibration()
        self.lux_curve = calibration["lux_curve"]
        self.noise_lsb = calibration.get("noise_lsb", 0) if noise_lsb is None else noise_lsb
        self.rng = rng or random.Random(0)
        self.port = None
        self.world = None
        self.clock = None

    def attach(self, port, world, clock):
        self.port = port
        self.world = world
        self.clock = clock
        port.attach(self)

    def output_raw(self):
        raw = self.raw_without_noise()
        if self.noise_lsb > 0:
            raw += self.rng.gauss(0, self.noise_lsb)
        return min(4095, max(0, int(round(raw))))

    def raw_without_noise(self):
        lux = self._sensed_lux()
        voltage = _interpolate_log_lux(lux, self.lux_curve)
        return voltage / 3.3 * 4095

    @classmethod
    def ui_schema(cls):
        return {
            "fields": [
                {"name": "noise_lsb", "type": "number", "min": 0}
            ]
        }

    def _sensed_lux(self):
        if self.world is None:
            return 0
        angle = 0
        servo = getattr(self.port.board, "servo_model", None) if self.port is not None else None
        if servo is not None:
            angle = servo.actual_angle
        return self.world.lux_at(angle) + self.world.ambient_lux


def _interpolate_log_lux(lux, table):
    points = sorted((float(point["lux"]), float(point["volts"])) for point in table)
    lux = max(0, float(lux))
    if lux <= points[0][0]:
        return points[0][1]
    if lux >= points[-1][0]:
        return points[-1][1]
    x = math.log10(max(lux, 1e-9))
    for (lux0, volts0), (lux1, volts1) in zip(points, points[1:]):
        if lux0 <= lux <= lux1:
            x0 = math.log10(max(lux0, 1e-9))
            x1 = math.log10(max(lux1, 1e-9))
            ratio = (x - x0) / (x1 - x0)
            return volts0 + ratio * (volts1 - volts0)
    return points[-1][1]
