"""SSD1306 I2C peripheral model for the SmartMotor emulator.

Co-authored-by: GPT-5, Aug 2026
"""

import struct
import zlib

from smotoremu.i2c import I2CDevice
from smotoremu.screen_text import extract_lines


class SSD1306Device(I2CDevice):
    def __init__(self, width=128, height=64):
        self.width = width
        self.height = height
        self.pages = height // 8
        self._gddram = bytearray(width * self.pages)
        self.on = False
        self.inverted = False
        self.memory_addressing_mode = 0
        self.col_start = 0
        self.col_end = width - 1
        self.page_start = 0
        self.page_end = self.pages - 1
        self.col = self.col_start
        self.page = self.page_start
        self.display_start_line = 0
        self.segment_remap = 0
        self.mux_ratio = height - 1
        self.com_scan_direction = 0
        self.display_offset = 0
        self.com_pin_config = 0
        self.display_clock_divide = 0
        self.precharge = 0
        self.vcom_deselect = 0
        self.contrast = 0
        self.entire_display_on = False
        self.charge_pump = 0
        self.frame_count = 0
        self.on_frame = None
        self._pending_command = None
        self._pending_params = []
        self._pending_count = 0

    @property
    def gddram(self) -> bytes:
        return bytes(self._gddram)

    def on_write(self, data: bytes, is_continuation: bool = False):
        if not data:
            return
        control = data[0]
        payload = data[1:]
        if control == 0x80:
            for value in payload:
                self._process_command_byte(value)
            return
        if control == 0x40:
            self._write_data(payload)
            return
        raise ValueError(f"unsupported SSD1306 control byte 0x{control:02x}")

    def pixels(self) -> list[list[int]]:
        rows = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                if not self.on:
                    row.append(0)
                    continue
                idx = x + (y // 8) * self.width
                bit = (self._gddram[idx] >> (y % 8)) & 1
                row.append(bit ^ int(self.inverted))
            rows.append(row)
        return rows

    def to_png(self, scale: int = 4) -> bytes:
        if scale <= 0:
            raise ValueError("scale must be positive")
        pixels = self.pixels()
        width = self.width * scale
        height = self.height * scale
        raw_rows = []
        for row in pixels:
            scaled = bytes(0 if bit else 255 for bit in row for _ in range(scale))
            for _ in range(scale):
                raw_rows.append(b"\x00" + scaled)
        return _png(width, height, b"".join(raw_rows))

    def text_lines(self) -> list[str]:
        return extract_lines(self.gddram, width=self.width, height=self.height)

    def _process_command_byte(self, value):
        if self._pending_command is not None:
            self._pending_params.append(value)
            if len(self._pending_params) == self._pending_count:
                self._apply_command(self._pending_command, self._pending_params)
                self._pending_command = None
                self._pending_params = []
                self._pending_count = 0
            return

        count = _PARAM_COUNTS.get(value, 0)
        if count:
            self._pending_command = value
            self._pending_params = []
            self._pending_count = count
            return
        self._apply_command(value, [])

    def _apply_command(self, command, params):
        if command in (0xAE, 0xAF):
            self.on = command == 0xAF
        elif command == 0x20:
            self.memory_addressing_mode = params[0]
        elif command == 0x21:
            self.col_start, self.col_end = params
            self.col = self.col_start
        elif command == 0x22:
            self.page_start, self.page_end = params
            self.page = self.page_start
        elif 0x40 <= command <= 0x7F:
            self.display_start_line = command & 0x3F
        elif command in (0xA0, 0xA1):
            self.segment_remap = command & 0x01
        elif command == 0xA8:
            self.mux_ratio = params[0]
        elif command in (0xC0, 0xC8):
            self.com_scan_direction = command
        elif command == 0xD3:
            self.display_offset = params[0]
        elif command == 0xDA:
            self.com_pin_config = params[0]
        elif command == 0xD5:
            self.display_clock_divide = params[0]
        elif command == 0xD9:
            self.precharge = params[0]
        elif command == 0xDB:
            self.vcom_deselect = params[0]
        elif command == 0x81:
            self.contrast = params[0]
        elif command in (0xA4, 0xA5):
            self.entire_display_on = command == 0xA5
        elif command in (0xA6, 0xA7):
            self.inverted = command == 0xA7
        elif command == 0x8D:
            self.charge_pump = params[0]

    def _write_data(self, payload):
        for value in payload:
            if 0 <= self.col < self.width and 0 <= self.page < self.pages:
                self._gddram[self.page * self.width + self.col] = value
            self.col += 1
            if self.col > self.col_end:
                self.col = self.col_start
                self.page += 1
                if self.page > self.page_end:
                    self.page = self.page_start
        if self._is_full_frame_write(payload):
            self.frame_count += 1
            if self.on_frame is not None:
                self.on_frame(self)

    def _is_full_frame_write(self, payload):
        return (
            len(payload) >= self.width * self.pages
            and self.col_start == 0
            and self.col_end == self.width - 1
            and self.page_start == 0
            and self.page_end == self.pages - 1
        )


_PARAM_COUNTS = {
    0x20: 1,
    0x21: 2,
    0x22: 2,
    0xA8: 1,
    0xD3: 1,
    0xDA: 1,
    0xD5: 1,
    0xD9: 1,
    0xDB: 1,
    0x81: 1,
    0x8D: 1,
}


def _png(width, height, raw_scanlines):
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(raw_scanlines)),
            _chunk(b"IEND", b""),
        ]
    )


def _chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)
