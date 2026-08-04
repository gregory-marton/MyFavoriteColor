"""T003: framebuf shim. Written before smotoremu/framebuf_shim.py exists.

MONO_VLSB bit layout, matching MicroPython's real framebuf module: byte
index = x + (y // 8) * width; bit index within that byte = y % 8, bit 0 is
the top row of the 8-pixel vertical strip. This is the format ssd1306.py's
SSD1306 base class actually constructs its buffer with -- see ssd1306.py
line ~38 (`framebuf.MONO_VLSB`), so getting this bit order right is what
makes the real, unmodified driver produce correct pixels under emulation.
"""

import pytest

from smotoremu import framebuf_shim as framebuf


def test_pixel_set_and_get_round_trips():
    buf = bytearray(16 * 8)  # 16 wide, 64 tall -> 8 pages
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.pixel(3, 5, 1)
    assert fb.pixel(3, 5) == 1
    assert fb.pixel(3, 6) == 0
    assert fb.pixel(4, 5) == 0


def test_pixel_bit_layout_matches_mono_vlsb():
    # top-left pixel (0,0) on -> bit 0 of byte 0
    buf = bytearray(16 * 8)
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.pixel(0, 0, 1)
    assert buf[0] == 0b00000001
    fb.pixel(0, 1, 1)
    assert buf[0] == 0b00000011
    # (1, 0) -> byte index 1 (x=1, page 0)
    fb.pixel(1, 0, 1)
    assert buf[1] == 0b00000001
    # (0, 8) -> next page down -> byte index = 0 + 1*16 = 16
    fb.pixel(0, 8, 1)
    assert buf[16] == 0b00000001


def test_fill_sets_every_pixel():
    buf = bytearray(16 * 8)
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.fill(1)
    assert all(b == 0xFF for b in buf)
    fb.fill(0)
    assert all(b == 0x00 for b in buf)


def test_hline_and_vline():
    buf = bytearray(16 * 8)
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.hline(2, 10, 5, 1)  # x=2..6, y=10
    for x in range(2, 7):
        assert fb.pixel(x, 10) == 1
    assert fb.pixel(7, 10) == 0
    fb.vline(0, 0, 4, 1)
    for y in range(4):
        assert fb.pixel(0, y) == 1
    assert fb.pixel(0, 4) == 0


def test_line_draws_bresenham_diagonal_and_clips():
    buf = bytearray(16 * 8)
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.line(-1, -1, 3, 3, 1)

    for point in ((0, 0), (1, 1), (2, 2), (3, 3)):
        assert fb.pixel(*point) == 1
    assert fb.pixel(3, 2) == 0


def test_rect_draws_outline_only():
    buf = bytearray(16 * 8)
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.rect(1, 1, 4, 4, 1)
    # corners and edges on
    assert fb.pixel(1, 1) == 1
    assert fb.pixel(4, 1) == 1
    assert fb.pixel(1, 4) == 1
    assert fb.pixel(4, 4) == 1
    # interior off
    assert fb.pixel(2, 2) == 0


def test_fill_rect_fills_interior():
    buf = bytearray(16 * 8)
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.fill_rect(1, 1, 4, 4, 1)
    assert fb.pixel(2, 2) == 1
    assert fb.pixel(4, 4) == 1
    assert fb.pixel(5, 5) == 0


def test_text_renders_known_glyph_from_the_real_font():
    # 'H' = ord 72; verify it draws *something* recognizable, not blank,
    # in an 8x8 cell at the given position -- the exact bit pattern is
    # covered by test_font.py against the source header directly.
    buf = bytearray(16 * 8)
    fb = framebuf.FrameBuffer(buf, 16, 64, framebuf.MONO_VLSB)
    fb.text("H", 0, 0, 1)
    lit = sum(1 for x in range(8) for y in range(8) if fb.pixel(x, y))
    assert lit > 0


def test_blit_copies_one_framebuffer_into_another():
    src_buf = bytearray(8 * 1)  # 8x8
    src = framebuf.FrameBuffer(src_buf, 8, 8, framebuf.MONO_VLSB)
    src.fill(1)
    dst_buf = bytearray(16 * 8)
    dst = framebuf.FrameBuffer(dst_buf, 16, 64, framebuf.MONO_VLSB)
    dst.blit(src, 4, 4)
    assert dst.pixel(4, 4) == 1
    assert dst.pixel(11, 11) == 1
    assert dst.pixel(0, 0) == 0
