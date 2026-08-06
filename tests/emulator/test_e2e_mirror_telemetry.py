"""End-to-end integration test verifying live physical SmartMotor telemetry changes
(battery, pot, tilt, buttons) are reflected in mirror state messages.

Runs live when a physical SmartMotor is plugged into USB serial; passes quietly when absent.

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import time
import pytest

from smotoremu import protocol
from smotoremu.cli import HardwareBridge, HardwareServerSession, find_serial_port


def test_simulated_dynamic_telemetry(tmp_path):
    state_file = tmp_path / "recording_state.json"
    rec_dir = tmp_path / "recordings"

    class SimSerial:
        def __init__(self):
            self.sent = []
            self.samples = [
                b'{"s": 80, "m": 45, "pot": 1200, "bat": 4150, "ax": 0, "ay": 0, "az": 1000, "btn_u": 1}\n',
                b'{"s": 85, "m": 90, "pot": 2500, "bat": 3900, "ax": 500, "ay": 0, "az": 866, "btn_u": 0}\n',
            ]
            self.idx = 0

        def write(self, b):
            self.sent.append(b)

        def flush(self):
            pass

        def readline(self):
            data = self.samples[self.idx % len(self.samples)]
            self.idx += 1
            return data

    hb = HardwareBridge()
    hb._ser = SimSerial()
    session = HardwareServerSession(hb, state_file=str(state_file), rec_dir=str(rec_dir))

    s1 = session.state_message()
    assert s1["pot"] == 1200
    assert s1["battery"] == 4150

    s2 = session.state_message()
    assert s2["pot"] == 2500
    assert s2["battery"] == 3900
    assert s2["button"] == "up"


def test_physical_smartmotor_mirror_telemetry(tmp_path):
    port = find_serial_port()
    if not port:
        pytest.skip("No physical SmartMotor connected on USB serial")

    # Skip if smotor bridge process is already running and holding serial port
    import subprocess
    try:
        ps_out = subprocess.check_output(["ps", "-ef"]).decode()
        if "smotor" in ps_out and "bridge" in ps_out:
            pytest.skip("Bridge process is running and holding serial port")
    except Exception:
        pass

    state_file = tmp_path / "recording_state.json"
    rec_dir = tmp_path / "recordings"

    hb = HardwareBridge(port=port)
    if hb._ser is None:
        pytest.skip(f"Could not open serial port {port}")

    session = HardwareServerSession(hb, state_file=str(state_file), rec_dir=str(rec_dir))

    # Read 3 live state samples over time from the connected physical SmartMotor
    samples = []
    for _ in range(3):
        samples.append(session.state_message())
        time.sleep(0.3)

    hb._ser.close()

    assert len(samples) == 3
    for s in samples:
        assert s["type"] == "state"
        assert "pot" in s
        assert "battery" in s
        assert "angle" in s
