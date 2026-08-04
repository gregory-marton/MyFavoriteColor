"""Low-overhead live telemetry hooks for a physical SmartMotor.

The protocol deliberately isn't JSON. Legacy ``webconnect.py`` looks for JSON
braces in the serial stream; the ``@SMIRROR`` prefix lets both protocols share
USB CDC without the old parser mistaking mirror frames for commands.

Co-authored-by: GPT-5, Aug 2026
"""

import sys

try:
    import ubinascii as _binascii
except ImportError:  # CPython tests
    import binascii as _binascii


_writer = sys.stdout
_frame_sequence = 0
_installed = False
_last_accel_ms = None


def set_writer(writer):
    """Set the telemetry sink; primarily useful for bounded desktop tests."""
    global _writer, _frame_sequence, _last_accel_ms
    _writer = writer
    _frame_sequence = 0
    _last_accel_ms = None


def emit_frame(buffer, width=128, height=64):
    global _frame_sequence
    _frame_sequence += 1
    encoded = _binascii.b2a_base64(bytes(buffer)).decode("ascii").strip()
    _write("@SMIRROR FRAME %d %d %d %s\n" % (_frame_sequence, width, height, encoded))


def emit_angle(degrees):
    _write("@SMIRROR ANGLE %s\n" % degrees)


def emit_accel(x, y, z):
    global _last_accel_ms
    now_ms = _now_ms()
    if _last_accel_ms is not None and _ticks_diff(now_ms, _last_accel_ms) < 100:
        return
    _last_accel_ms = now_ms
    _write("@SMIRROR ACCEL %s %s %s\n" % (x, y, z))


def install(display_module=None, servo_module=None):
    """Instrument the shared OLED and servo drivers once per device boot."""
    global _installed
    if _installed:
        return

    if servo_module is None:
        import servo as servo_module
    if display_module is None:
        import ssd1306 as display_module

    original_show = display_module.SSD1306.show
    original_write_angle = servo_module.Servo.write_angle

    def mirrored_show(display):
        result = original_show(display)
        emit_frame(display.buffer, display.width, display.height)
        return result

    def mirrored_write_angle(motor, degrees=None, radians=None):
        result = original_write_angle(motor, degrees=degrees, radians=radians)
        if degrees is None:
            import math
            reported_degrees = math.degrees(radians)
        else:
            reported_degrees = degrees
        emit_angle(reported_degrees % 360)
        return result

    display_module.SSD1306.show = mirrored_show
    servo_module.Servo.write_angle = mirrored_write_angle
    _installed = True
    _write("@SMIRROR READY 1\n")


def _write(text):
    try:
        _writer.write(text)
    except Exception:
        # Mirroring must never stop the physical activity it observes.
        pass


def _now_ms():
    import time
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.monotonic() * 1000)


def _ticks_diff(new, old):
    import time
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(new, old)
    return new - old
