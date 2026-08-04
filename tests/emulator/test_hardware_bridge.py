"""Unit tests for smotor hardware bridge functionality.

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import pytest
from smotoremu.cli import HardwareBridge


def test_hardware_bridge_mock_device():
    events = []

    class MockSerialLink:
        def __init__(self):
            self.sent = []

        def write(self, data):
            self.sent.append(data)

        def read_state(self):
            return {"angle": 45.0, "pot": 1200, "button": "up"}

    link = MockSerialLink()
    bridge = HardwareBridge(link=link)
    state = bridge.poll_hardware()
    assert state["angle"] == 45.0
    assert state["pot"] == 1200

    bridge.send_command({"type": "press", "button": "up"})
    assert len(link.sent) > 0
