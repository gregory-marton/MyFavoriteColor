"""Rendering SCREEN events to real pixel buffers via the actual ssd1306.py
driver -- this is what makes the replay pixel-faithful rather than a text
mockup. Written before smotoremu/trace.py's render_screens exists.

Layout (x=4, y=8+row*12) must match spikes/S7_guided/guided_test_device.py's
Display.show() exactly, or the replay wouldn't show what the device
actually showed.
"""

import base64

from smotoremu.trace import render_screens


def test_adds_a_base64_buffer_to_each_screen_event():
    events = [{"type": "SCREEN", "t": 0, "lines": ["POT x3", "sweep fully"]}]
    rendered = render_screens(events)
    assert "screen_buffer_b64" in rendered[0]
    raw = base64.b64decode(rendered[0]["screen_buffer_b64"])
    assert len(raw) == 128 * 64 // 8  # full 128x64 MONO_VLSB buffer
    assert any(b != 0 for b in raw)  # text was actually drawn


def test_blank_lines_produce_a_blank_buffer():
    events = [{"type": "SCREEN", "t": 0, "lines": [""]}]
    rendered = render_screens(events)
    raw = base64.b64decode(rendered[0]["screen_buffer_b64"])
    assert all(b == 0 for b in raw)


def test_non_screen_events_pass_through_unchanged():
    events = [{"type": "SERVO", "t": 0, "angle": 90}]
    rendered = render_screens(events)
    assert rendered == events
    assert "screen_buffer_b64" not in rendered[0]


def test_matches_guided_test_device_display_layout():
    # two lines land at (4, 8) and (4, 20) -- guided_test_device.py's
    # Display.show(): text(text, 4, 8 + row * 12, 1)
    events = [{"type": "SCREEN", "t": 0, "lines": ["A", "B"]}]
    rendered = render_screens(events)
    raw = base64.b64decode(rendered[0]["screen_buffer_b64"])

    def pixel(buf, x, y, width=128):
        idx = x + (y // 8) * width
        return (buf[idx] >> (y % 8)) & 1

    # 'A' at (4,8): its glyph column data is nonzero somewhere in x=4..11, y=8..15
    assert any(pixel(raw, x, y) for x in range(4, 12) for y in range(8, 16))
    # 'B' at (4,20): same check in the second row's band
    assert any(pixel(raw, x, y) for x in range(4, 12) for y in range(20, 28))
