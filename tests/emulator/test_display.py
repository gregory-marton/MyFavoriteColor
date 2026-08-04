"""T009 SSD1306 I2C peripheral tests.

Co-authored-by: GPT-5, Aug 2026
"""

import struct

from smotoremu.device_env import load_real_icons, load_real_ssd1306
from smotoremu.machine_shim import Board, Pin, SoftI2C
from smotoremu.peripherals.ssd1306 import SSD1306Device


def make_i2c_with_display():
    board = Board()
    Pin.use_board(board)
    device = SSD1306Device(width=128, height=64)
    board.i2c_bus.register(0x3C, device)
    return SoftI2C(scl=Pin(7), sda=Pin(6)), device


def write_cmd(i2c, cmd):
    i2c.writeto(0x3C, bytes([0x80, cmd]))


def test_real_init_display_sequence_sets_expected_controller_state():
    i2c, device = make_i2c_with_display()
    ssd1306 = load_real_ssd1306()

    ssd1306.SSD1306_I2C(128, 64, i2c)

    assert device.on is True
    assert device.inverted is False
    assert device.memory_addressing_mode == 0x00
    assert (device.col_start, device.col_end) == (0, 127)
    assert (device.page_start, device.page_end) == (0, 7)
    assert device.frame_count == 1
    assert device.gddram == bytes(1024)


def test_full_buffer_write_updates_gddram_byte_for_byte():
    i2c, device = make_i2c_with_display()
    payload = bytes([n % 256 for n in range(1024)])

    i2c.writevto(0x3C, [b"@", payload])

    assert device.gddram == payload
    assert device.frame_count == 1


def test_partial_write_lands_only_in_selected_columns():
    i2c, device = make_i2c_with_display()
    for cmd in (0x21, 0, 7, 0x22, 0, 0):
        write_cmd(i2c, cmd)

    i2c.writevto(0x3C, [b"@", bytes(range(8))])

    assert device.gddram[:8] == bytes(range(8))
    assert device.gddram[8:] == bytes(1016)


def test_invert_affects_pixels_but_not_gddram():
    i2c, device = make_i2c_with_display()
    write_cmd(i2c, 0xAF)
    i2c.writevto(0x3C, [b"@", b"\x01" + bytes(1023)])

    assert device.pixels()[0][0] == 1
    assert device.pixels()[1][0] == 0

    write_cmd(i2c, 0xA7)

    assert device.gddram[0] == 0x01
    assert device.pixels()[0][0] == 0
    assert device.pixels()[1][0] == 1


def test_real_icons_smart_display_renders_extractable_text():
    i2c, device = make_i2c_with_display()
    icons = load_real_icons()

    display = icons.SSD1306_SMART(128, 64, i2c)
    display.fill(0)
    display.text("HELLO", 5, 15, 1)
    display.show()

    assert device.text_lines() == ["HELLO"]


def test_to_png_has_png_magic_and_correct_size():
    _, device = make_i2c_with_display()

    png = device.to_png(scale=2)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert png[12:16] == b"IHDR"
    assert struct.unpack(">II", png[16:24]) == (256, 128)
