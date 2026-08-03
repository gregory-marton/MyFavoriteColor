"""T003: framebuf shim -- enough of MicroPython's framebuf module to run the
real ssd1306.py driver unmodified.

Only MONO_VLSB is implemented: that's the only format ssd1306.py's SSD1306
base class constructs (see ssd1306.py, `framebuf.MONO_VLSB`). Byte index =
x + (y // 8) * width; bit index = y % 8, bit 0 is the top row of that
8-pixel vertical strip -- MicroPython's actual bit order.
"""

from smotoremu._font_data import FONT_DATA

MONO_VLSB = "MONO_VLSB"


class FrameBuffer:
    def __init__(self, buf, width, height, format, stride=None):
        if format != MONO_VLSB:
            raise NotImplementedError("only MONO_VLSB is implemented")
        self.buf = buf
        self.width = width
        self.height = height
        self.stride = stride if stride is not None else width

    def _in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def pixel(self, x, y, color=None):
        if not self._in_bounds(x, y):
            return 0 if color is None else None
        idx = x + (y // 8) * self.stride
        bit = y % 8
        if color is None:
            return (self.buf[idx] >> bit) & 1
        if color:
            self.buf[idx] |= 1 << bit
        else:
            self.buf[idx] &= ~(1 << bit) & 0xFF

    def fill(self, color):
        fill_byte = 0xFF if color else 0x00
        for i in range(len(self.buf)):
            self.buf[i] = fill_byte

    def hline(self, x, y, length, color):
        for i in range(length):
            self.pixel(x + i, y, color)

    def vline(self, x, y, length, color):
        for i in range(length):
            self.pixel(x, y + i, color)

    def rect(self, x, y, w, h, color):
        self.hline(x, y, w, color)
        self.hline(x, y + h - 1, w, color)
        self.vline(x, y, h, color)
        self.vline(x + w - 1, y, h, color)

    def fill_rect(self, x, y, w, h, color):
        for row in range(h):
            self.hline(x, y + row, w, color)

    def text(self, text, x, y, color=1):
        for i, ch in enumerate(text):
            code = ord(ch)
            if not (32 <= code <= 127):
                continue
            offset = (code - 32) * 8
            glyph = FONT_DATA[offset:offset + 8]
            cx = x + i * 8
            for col in range(8):
                col_bits = glyph[col]
                for row in range(8):
                    if col_bits & (1 << row):
                        self.pixel(cx + col, y + row, color)

    def blit(self, source, x, y, key=-1):
        for sy in range(source.height):
            for sx in range(source.width):
                p = source.pixel(sx, sy)
                if key != -1 and p == key:
                    continue
                self.pixel(x + sx, y + sy, p)
