"""Device-side live mirror telemetry tests.

Co-authored-by: GPT-5, Aug 2026
Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import base64
import io
from types import SimpleNamespace

import smirror


def test_emit_frame_uses_line_protocol_without_json_braces():
    output = io.StringIO()
    smirror.set_writer(output)

    smirror.emit_frame(bytes([0xA5, 0x5A]), width=2, height=8)

    encoded = base64.b64encode(bytes([0xA5, 0x5A])).decode("ascii")
    assert output.getvalue() == f"@SMIRROR FRAME 1 2 8 {encoded}\n"
    assert "{" not in output.getvalue()


def test_emit_angle_reports_commanded_servo_angle():
    output = io.StringIO()
    smirror.set_writer(output)

    smirror.emit_angle(37.5)

    assert output.getvalue() == "@SMIRROR ANGLE 37.5\n"


def test_emit_inputs_reports_physical_pot_and_active_low_buttons():
    output = io.StringIO()
    smirror.set_writer(output)

    smirror.emit_inputs(1234, 0, 1, 0)

    assert output.getvalue() == "@SMIRROR INPUT 1234 0 1 0\n"


def test_install_hooks_display_and_servo_without_changing_their_results(monkeypatch):
    output = io.StringIO()
    smirror.set_writer(output)
    monkeypatch.setattr(smirror, "_installed", False)

    class Display:
        width = 2
        height = 8
        buffer = bytes([1, 2])

        def show(self):
            return "shown"

    class Servo:
        def write_angle(self, degrees=None, radians=None):
            return "moved"

    display_module = SimpleNamespace(SSD1306=Display)
    servo_module = SimpleNamespace(Servo=Servo)

    smirror.install(display_module=display_module, servo_module=servo_module)

    assert Display().show() == "shown"
    assert Servo().write_angle(degrees=42) == "moved"
    assert "@SMIRROR FRAME 1 2 8 " in output.getvalue()
    assert "@SMIRROR ANGLE 42\n" in output.getvalue()
