"""Reverse-map MONO_VLSB screen buffers back to text.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu._font_data import FONT_DATA

GLYPH_WIDTH = 8
GLYPH_HEIGHT = 8
DEFAULT_WIDTH = 128
DEFAULT_HEIGHT = 64


class ExtractedText(list):
    def __init__(self, rows, origin, score):
        super().__init__(rows)
        self.origin = origin
        self.score = score


def build_glyph_map() -> dict[bytes, str]:
    glyphs = {bytes(8): " "}
    seen_non_blank = {}
    for code in range(32, 128):
        bitmap = bytes(FONT_DATA[(code - 32) * GLYPH_WIDTH : (code - 31) * GLYPH_WIDTH])
        ch = chr(code)
        if bitmap == bytes(8):
            continue
        if bitmap in seen_non_blank:
            other = seen_non_blank[bitmap]
            raise ValueError(f"duplicate glyph bitmap for {other!r} and {ch!r}")
        seen_non_blank[bitmap] = ch
        glyphs[bitmap] = ch
    return glyphs


GLYPHS = build_glyph_map()


def extract_text(
    buffer: bytes,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    unknown: str = "·",
    origin=None,
) -> list[str]:
    """Read a MONO_VLSB framebuffer on an 8x8 text grid."""
    if origin is not None:
        rows, score = _extract_at_origin(buffer, width, height, unknown, origin)
        return ExtractedText(rows, origin, score)

    best_rows = []
    best_origin = (0, 0)
    best_score = -1
    for dy in range(GLYPH_HEIGHT):
        for dx in range(GLYPH_WIDTH):
            rows, score = _extract_at_origin(buffer, width, height, unknown, (dx, dy))
            if score > best_score:
                best_rows = rows
                best_origin = (dx, dy)
                best_score = score
    return ExtractedText(best_rows, best_origin, best_score)


def extract_lines(buffer, **kw) -> list[str]:
    """As extract_text but right-stripped, with blank rows dropped."""
    rows = extract_text(buffer, **kw)
    lines = []
    for row in rows:
        line = row.rstrip()
        if line:
            lines.append(line)
    return lines


def _extract_at_origin(buffer, width, height, unknown, origin):
    dx, dy = origin
    if not (0 <= dx < GLYPH_WIDTH and 0 <= dy < GLYPH_HEIGHT):
        raise ValueError("origin offsets must be in 0..7")
    rows = []
    score = 0
    for y in range(dy, height - GLYPH_HEIGHT + 1, GLYPH_HEIGHT):
        chars = []
        for x in range(dx, width - GLYPH_WIDTH + 1, GLYPH_WIDTH):
            bitmap = _cell_bitmap(buffer, width, height, x, y)
            ch = GLYPHS.get(bitmap)
            if ch is None:
                chars.append(unknown)
                continue
            chars.append(ch)
            if ch != " ":
                score += 1
        rows.append("".join(chars))
    return rows, score


def _cell_bitmap(buffer, width, height, x, y):
    columns = []
    for col in range(GLYPH_WIDTH):
        bits = 0
        for row in range(GLYPH_HEIGHT):
            if _pixel(buffer, width, height, x + col, y + row):
                bits |= 1 << row
        columns.append(bits)
    return bytes(columns)


def _pixel(buffer, width, height, x, y):
    if not (0 <= x < width and 0 <= y < height):
        return 0
    idx = x + (y // 8) * width
    return (buffer[idx] >> (y % 8)) & 1
