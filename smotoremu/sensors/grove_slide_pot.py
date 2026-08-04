"""Grove slide potentiometer analog sensor plug-in.

Co-authored-by: GPT-5, Aug 2026
"""

import random

from smotoremu.sensors import SensorModel, register


@register("GROVE_SLIDE_POT")
class GroveSlidePotModel(SensorModel):
    display_name = "Grove Slide Potentiometer"
    interface = "analog"

    def __init__(self, position=0.5, noise_lsb=None, rng=None):
        calibration = self.calibration()
        self.adc_curve = calibration["adc_curve"]
        self.noise_lsb = calibration.get("noise_lsb", 0) if noise_lsb is None else noise_lsb
        self.rng = rng or random.Random(0)
        self.position = 0.5
        self.set_position(position)
        self.port = None
        self.world = None
        self.clock = None

    def attach(self, port, world, clock):
        self.port = port
        self.world = world
        self.clock = clock
        port.attach(self)

    def set_position(self, position):
        self.position = min(1.0, max(0.0, float(position)))

    def output_raw(self):
        ideal = self.position * 4095
        corrected = _piecewise(ideal, self.adc_curve)
        if self.noise_lsb > 0:
            corrected += self.rng.gauss(0, self.noise_lsb)
        return min(4095, max(0, int(round(corrected))))

    @classmethod
    def ui_schema(cls):
        return {
            "fields": [
                {"name": "position", "type": "slider", "min": 0.0, "max": 1.0}
            ]
        }


def _piecewise(x, table):
    # GUESS: identity by default; ESP32-C3 ADC is notably non-linear near rails
    # and should be replaced with bench data when available.
    points = sorted((float(point["in"]), float(point["out"])) for point in table)
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            ratio = (x - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return x
