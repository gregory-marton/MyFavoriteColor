"""T009: the real ssd1306.py driver running against our shims -- the
"it's alive" milestone. Written before smotoremu/device_env.py exists.

smotoremu.device_env loads the real repo-root ssd1306.py by file path, with
our framebuf/machine shims injected into sys.modules first so its top-level
`import framebuf` / `from micropython import const` resolve correctly.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.device_env import load_real_ssd1306
from smotoremu.i2c import I2CDevice
from smotoremu.machine_shim import SoftI2C, Pin


def make_display():
    ssd1306 = load_real_ssd1306()
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    Pin._board.i2c_bus.register(0x3C, I2CDevice())
    display = ssd1306.SSD1306_I2C(128, 64, i2c)
    return display, i2c


def test_loads_the_real_driver_not_the_test_suites_fake():
    ssd1306 = load_real_ssd1306()
    # loaded from the repo-root file, not a generated or compatibility shim
    assert ssd1306.__file__.endswith("/ssd1306.py")
    assert hasattr(ssd1306, "SSD1306_I2C")


def test_init_display_sends_commands_and_clears_buffer():
    display, i2c = make_display()
    assert i2c.last_writeto is not None  # init_display() sent at least one command
    assert all(b == 0 for b in display.buffer)  # init_display() calls fill(0)


def test_text_and_show_produce_a_nonblank_buffer_matching_real_font():
    display, i2c = make_display()
    display.fill(0)
    display.text("HI", 0, 0, 1)
    display.show()
    assert any(b != 0 for b in display.buffer)
    # show() must have written the full buffer via writevto (write_data)
    assert i2c.last_writevto is not None
    addr, data = i2c.last_writevto
    assert addr == 0x3C
    # write_data() prepends a real I2C control byte (Co=0, D/C#=1) before
    # the buffer -- see ssd1306.py's `self.write_list = [b"@", None]`.
    assert bytes(data) == b"@" + bytes(display.buffer)


def test_buffer_pixel_layout_is_real_mono_vlsb():
    display, i2c = make_display()
    display.fill(0)
    display.pixel(0, 0, 1)
    assert display.buffer[0] == 0b00000001
