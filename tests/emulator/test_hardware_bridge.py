"""Unit tests for smotor hardware bridge functionality.

Co-authored-by: Gemini 3.6 Flash, Aug 2026
Co-authored-by: GPT-5, Aug 2026
Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import base64
import sys
import time
import threading
from types import SimpleNamespace

import pytest
from smotoremu.cli import HardwareBridge, HardwareServerSession, reset_hardware
from smotoremu._font_data import FONT_DATA


@pytest.fixture(autouse=True)
def do_not_open_physical_serial_for_unit_tests(monkeypatch):
    monkeypatch.setattr("smotoremu.cli.find_serial_port", lambda port=None: port)


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


def test_hardware_bridge_webconnect_translation():
    class DummySer:
        def __init__(self):
            self.sent = []
        def write(self, b):
            self.sent.append(b)
        def flush(self):
            pass
        def readline(self):
            return b'{"s": 85, "m": 90}\n'

    hb = HardwareBridge()
    hb._ser = DummySer()
    session = HardwareServerSession(hb)
    session.handle('{"v":1,"type":"press","button":"down"}')
    
    # Must NOT send raw {"type": "press"} to physical device because webconnect.py crashes without "st" key
    last_sent = hb._ser.sent[-1].decode()
    assert '"st"' in last_sent
    assert '"type"' not in last_sent

    state = session.state_message()
    assert state["type"] == "state"
    assert state["angle"] == 90.0


def test_hardware_bridge_full_telemetry():
    class DummySer:
        def __init__(self):
            pass
        def write(self, b):
            pass
        def flush(self):
            pass
        def readline(self):
            return b'{"s": 85, "m": 90, "pot": 3200, "ax": 0, "ay": 1000, "az": 0, "btn_d": 0}\n'

    hb = HardwareBridge()
    hb._ser = DummySer()
    state = hb.poll_hardware()
    assert state["pot"] == 3200
    assert state["angle"] == 90.0
    assert state["button"] == "down"


def test_hardware_bridge_sensor_detection():
    class DummySer:
        def __init__(self):
            pass
        def write(self, b):
            pass
        def flush(self):
            pass
        def readline(self):
            return b'{"s": 150, "attached": "VEML6040", "m": 90}\n'

    hb = HardwareBridge()
    hb._ser = DummySer()
    session = HardwareServerSession(hb)
    state = session.state_message()
    assert state["attached"] == "VEML6040"


def test_bridge_pushes_state_without_client_messages():
    """Bridge must proactively push hardware state to browser without
    the browser sending any messages first.  The current (broken)
    implementation only sends state in response to a client message,
    so this test will fail until the bridge handler is fixed."""
    import asyncio

    sent_messages = []
    call_count = 0

    class DummySer:
        def write(self, b):
            pass

        def flush(self):
            pass

        def readline(self):
            nonlocal call_count
            call_count += 1
            # Return slowly changing pot values to simulate live hardware
            pot = 1000 + call_count * 10
            return f'{{"s": 50, "m": 90, "pot": {pot}}}\n'.encode()

    class FakeWebSocket:
        """Simulates a WebSocket that never sends anything from client side."""
        def __init__(self):
            self._closed = asyncio.Event()

        async def send(self, data):
            sent_messages.append(data)

        async def recv(self):
            # Client never sends — simulate this by blocking forever
            await self._closed.wait()
            raise Exception("closed")

        def __aiter__(self):
            return self

        async def __anext__(self):
            await self._closed.wait()
            raise StopAsyncIteration

        async def close(self):
            self._closed.set()

    from smotoremu.cli import bridge_handler

    async def run_test():
        hb = HardwareBridge()
        hb._ser = DummySer()
        ws = FakeWebSocket()

        # Run the handler for up to 1.5s, then cancel it
        task = asyncio.create_task(bridge_handler(ws, hb))
        await asyncio.sleep(1.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_test())

    # We should have received the initial state + multiple proactive pushes
    import json
    state_msgs = [json.loads(m) for m in sent_messages if '"state"' in m]

    # Must have >1 state messages (initial + proactive pushes)
    assert len(state_msgs) >= 3, (
        f"Expected >=3 proactive state pushes in 1.5s, got {len(state_msgs)}"
    )


def test_hardware_mirror_frame_is_rendered_and_text_extracted():
    framebuffer = bytearray(128 * 8)
    framebuffer[0:8] = _glyph("H")
    framebuffer[8:16] = _glyph("I")
    encoded = base64.b64encode(framebuffer).decode("ascii")

    class MirrorSerial:
        in_waiting = 0

        def write(self, data):
            pass

        def flush(self):
            pass

        def readline(self):
            return f"@SMIRROR FRAME 1 128 64 {encoded}\n".encode()

    bridge = HardwareBridge()
    bridge._ser = MirrorSerial()
    session = HardwareServerSession(bridge)

    session.state_message()
    frame = session.frame_message()

    assert frame["type"] == "frame"
    assert frame["seq"] == 1
    assert base64.b64decode(frame["png"]).startswith(b"\x89PNG\r\n\x1a\n")
    assert frame["lines"] == ["HI"]


def test_hardware_mirror_accelerometer_updates_orientation():
    class MirrorSerial:
        in_waiting = 0

        def write(self, data):
            pass

        def flush(self):
            pass

        def readline(self):
            return b"@SMIRROR ACCEL 128 0 222\n"

    bridge = HardwareBridge()
    bridge._ser = MirrorSerial()

    state = bridge.poll_hardware()

    assert state["roll"] == pytest.approx(0.0)
    assert state["pitch"] == pytest.approx(-30.0, abs=0.2)


def test_soft_interrupt_leaves_device_at_repl_instead_of_rebooting(monkeypatch):
    writes = []

    class SerialPort:
        def write(self, data):
            writes.append(data)

        def close(self):
            pass

    serial_module = SimpleNamespace(Serial=lambda *args, **kwargs: SerialPort())
    monkeypatch.setitem(sys.modules, "serial", serial_module)
    monkeypatch.setattr("smotoremu.cli.time.sleep", lambda seconds: None)

    assert reset_hardware(port="/dev/test-smartmotor", soft=True) == 0
    assert writes == [b"\x03"] * 8


def test_mirror_parser_resynchronizes_after_interleaved_device_writes():
    class MirrorSerial:
        def write(self, data):
            pass

        def flush(self):
            pass

        def readline(self):
            return b"@SMIRROR ACCEL 1 2 -24@SMIRROR ACCEL 128 0 222\n"

    bridge = HardwareBridge()
    bridge._ser = MirrorSerial()

    state = bridge.poll_hardware()

    assert state["roll"] == pytest.approx(0.0)
    assert state["pitch"] == pytest.approx(-30.0, abs=0.2)


def test_hardware_serial_reads_are_shared_safely_across_browser_clients():
    active_reads = 0
    max_active_reads = 0

    class MirrorSerial:
        def write(self, data):
            pass

        def flush(self):
            pass

        def readline(self):
            nonlocal active_reads, max_active_reads
            active_reads += 1
            max_active_reads = max(max_active_reads, active_reads)
            time.sleep(0.03)
            active_reads -= 1
            return b"@SMIRROR ACCEL 0 0 256\n"

    bridge = HardwareBridge()
    bridge._ser = MirrorSerial()
    threads = [threading.Thread(target=bridge.poll_hardware) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active_reads == 1


def test_hardware_mirror_inputs_include_pot_and_button_states():
    class MirrorSerial:
        def write(self, data):
            pass

        def flush(self):
            pass

        def readline(self):
            return b"@SMIRROR INPUT 1234 0 1 0\n"

    bridge = HardwareBridge()
    bridge._ser = MirrorSerial()

    state = bridge.poll_hardware()

    assert state["pot"] == 1234
    assert state["buttons"] == {"up": True, "down": False, "select": True}


def test_hardware_mirror_status_preserves_full_sensor_and_power_values():
    class MirrorSerial:
        def write(self, data):
            pass

        def flush(self):
            pass

        def readline(self):
            return (
                b"@SMIRROR STATUS power=1 usb=1 mode=i2c sensor=1 "
                b"sensor_value=65535 sensor_r=4660 sensor_g=9029 "
                b"sensor_b=13398 sensor_w=17767 pot=2048 angle=90 "
                b"up=1 down=0 select=1 delta=^\n"
            )

    bridge = HardwareBridge()
    bridge._ser = MirrorSerial()

    state = bridge.poll_hardware()

    assert state["power"] is True
    assert state["usb"] is True
    assert state["mode"] == "i2c"
    assert state["sensor_attached"] is True
    assert state["sensor_value"] == 65535
    assert state["sensor_rgbw"] == [4660, 9029, 13398, 17767]
    assert state["buttons"] == {"up": False, "down": True, "select": False}


def _glyph(character):
    offset = (ord(character) - 32) * 8
    return FONT_DATA[offset : offset + 8]
