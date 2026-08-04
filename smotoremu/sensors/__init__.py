"""Sensor plug-in registry.

Co-authored-by: GPT-5, Aug 2026
"""

import importlib
import pkgutil

from smotoremu.sensors.base import SensorModel

_REGISTRY = {}


def register(part_number: str):
    def decorator(cls):
        if part_number in _REGISTRY:
            raise ValueError(f"sensor {part_number} already registered")
        cls.part_number = part_number
        _REGISTRY[part_number] = cls
        return cls

    return decorator


def get_sensor(part_number: str) -> type[SensorModel]:
    try:
        return _REGISTRY[part_number]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY)) or "none"
        raise KeyError(f"unknown sensor {part_number!r}; available: {available}") from exc


def list_sensors() -> list[dict]:
    return [
        {
            "part_number": part_number,
            "display_name": cls.display_name,
            "interface": cls.interface,
        }
        for part_number, cls in sorted(_REGISTRY.items())
    ]


def _auto_import_plugins():
    for module in pkgutil.iter_modules(__path__):
        if module.name in {"base"} or module.ispkg:
            continue
        importlib.import_module(f"{__name__}.{module.name}")


_auto_import_plugins()
