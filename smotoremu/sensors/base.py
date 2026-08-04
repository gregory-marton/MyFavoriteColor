"""Base classes and registry primitives for emulator sensor plug-ins.

Co-authored-by: GPT-5, Aug 2026
"""

from abc import ABC, abstractmethod
import json
import os


class SensorModel(ABC):
    display_name = "Unnamed sensor"
    interface = "unknown"

    @abstractmethod
    def attach(self, port, world, clock):
        raise NotImplementedError

    @classmethod
    def ui_schema(cls):
        return {}

    @classmethod
    def calibration(cls):
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        filename = f"{getattr(cls, 'part_number', cls.__name__).lower()}.json"
        path = os.path.join(data_dir, filename)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
