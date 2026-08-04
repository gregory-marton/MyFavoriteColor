"""VEML6040 colour sensor plug-in placeholder.

T019 fills in the register-accurate I2C device model; T018 only needs the
plug-in to be discoverable and data-backed.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.sensors import SensorModel, register


@register("VEML6040")
class VEML6040Model(SensorModel):
    display_name = "VEML6040 Colour Sensor"
    interface = "i2c"

    def attach(self, port, world, clock):
        self.port = port
        self.world = world
        self.clock = clock

    @classmethod
    def ui_schema(cls):
        return {
            "fields": [
                {"name": "integration_time_ms", "type": "number"},
                {"name": "noise_lsb", "type": "number"},
            ]
        }
