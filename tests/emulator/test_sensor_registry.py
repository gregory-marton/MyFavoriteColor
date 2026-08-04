"""T018 sensor plug-in registry tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pytest

from smotoremu.sensors import SensorModel, get_sensor, list_sensors, register


@register("DUMMY-T018")
class DummySensor(SensorModel):
    display_name = "Dummy Sensor"
    interface = "analog"

    def attach(self, port, world, clock):
        self.attached = (port, world, clock)

    @classmethod
    def ui_schema(cls):
        return {"fields": []}


def test_decorator_registered_sensor_is_discoverable_by_name():
    assert get_sensor("DUMMY-T018") is DummySensor


def test_registering_duplicate_name_raises():
    with pytest.raises(ValueError, match="DUMMY-T018"):
        register("DUMMY-T018")(type("OtherDummySensor", (DummySensor,), {}))


def test_list_sensors_includes_registered_sensor():
    entries = list_sensors()

    assert {
        "part_number": "DUMMY-T018",
        "display_name": "Dummy Sensor",
        "interface": "analog",
    } in entries


def test_get_sensor_missing_name_reports_available_parts():
    with pytest.raises(KeyError, match="DUMMY-T018"):
        get_sensor("nope")


def test_package_auto_imports_veml6040_placeholder():
    cls = get_sensor("VEML6040")

    assert cls.display_name == "VEML6040 Colour Sensor"
    assert cls.interface == "i2c"


def test_sensor_calibration_loads_from_json_data_file():
    cls = get_sensor("VEML6040")

    calibration = cls.calibration()

    assert calibration["part_number"] == "VEML6040"
    assert "integration_time_ms" in calibration
