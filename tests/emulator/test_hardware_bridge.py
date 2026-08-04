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


def test_find_serial_port():
    from smotoremu.cli import find_serial_port
    port = find_serial_port("/dev/cu.usbmodem2101")
    assert port == "/dev/cu.usbmodem2101"


def test_hardware_bridge_ping():
    class DummySer:
        def __init__(self):
            self.data = []
        def write(self, b):
            self.data.append(b)
        def flush(self):
            pass
        def readline(self):
            return b'{"s": 50}\n'

    hb = HardwareBridge()
    hb._ser = DummySer()
    hb.ping()
    assert b'{"st":"e"}\n' in hb._ser.data


def test_hardware_bridge_session():
    from smotoremu.cli import HardwareServerSession
    class DummySer:
        def __init__(self):
            self.sent = []
        def write(self, b):
            self.sent.append(b)
        def flush(self):
            pass
        def readline(self):
            return b'{"s": 50}\n'

    hb = HardwareBridge()
    hb._ser = DummySer()
    session = HardwareServerSession(hb)
    messages = session.handle('{"v":1,"type":"press","button":"up"}')
    assert len(hb._ser.sent) > 0
    assert messages[0]["type"] == "state"


def test_hardware_bridge_heartbeat():
    class DummySer:
        def __init__(self):
            self.data = []
        def write(self, b):
            self.data.append(b)
        def flush(self):
            pass

    hb = HardwareBridge()
    hb._ser = DummySer()
    hb.heartbeat()
    assert len(hb._ser.data) == 1
    hb.heartbeat()
    assert len(hb._ser.data) == 2
