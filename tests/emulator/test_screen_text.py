"""T005 glyph reverse-map tests for selectable emulator screen text.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu import framebuf_shim as framebuf
from smotoremu.screen_text import build_glyph_map, extract_lines, extract_text


def make_buffer(text="", x=0, y=0, width=128, height=64):
    buf = bytearray(width * height // 8)
    fb = framebuf.FrameBuffer(buf, width, height, framebuf.MONO_VLSB)
    fb.text(text, x, y, 1)
    return buf


def test_glyph_map_is_injective_except_explicit_blank_space():
    glyphs = build_glyph_map()
    non_blank = {bitmap: ch for bitmap, ch in glyphs.items() if bitmap != bytes(8)}

    assert glyphs[bytes(8)] == " "
    assert len(non_blank) == len(set(non_blank))


def test_extract_text_recovers_grid_aligned_text():
    rows = extract_text(make_buffer("HELLO", 0, 0), origin=(0, 0))

    assert rows[0].startswith("HELLO")


def test_extract_lines_finds_non_grid_text_origin():
    assert extract_lines(make_buffer("HELLO", 5, 15)) == ["HELLO"]


def test_unknown_glyph_cell_keeps_neighbouring_text():
    buf = make_buffer("HAI", 0, 0)
    fb = framebuf.FrameBuffer(buf, 128, 64, framebuf.MONO_VLSB)
    fb.fill_rect(8, 0, 8, 8, 1)

    rows = extract_text(buf, origin=(0, 0), unknown="·")

    assert rows[0].startswith("H·I")


def test_empty_buffer_extracts_no_lines():
    assert extract_lines(make_buffer()) == []
