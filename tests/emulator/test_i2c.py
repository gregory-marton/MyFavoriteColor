"""T007 I2C bus tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pytest

from smotoremu.clock import VirtualClock
from smotoremu.i2c import I2CBus, I2CDevice
from smotoremu.machine_shim import Board, Pin, SoftI2C


class RecordingDevice(I2CDevice):
    def __init__(self):
        self.writes = []
        self.read_data = b""

    def on_write(self, data, is_continuation=False):
        self.writes.append((data, is_continuation))

    def on_read(self, n):
        return self.read_data[:n].ljust(n, b"\x00")


class MemoryDevice(I2CDevice):
    def __init__(self):
        self.mem = {}
        self.pointer = 0

    def on_write(self, data, is_continuation=False):
        if len(data) == 1:
            self.pointer = data[0]
            return
        self.pointer = data[0]
        for offset, value in enumerate(data[1:]):
            self.mem[self.pointer + offset] = value

    def on_read(self, n):
        return bytes(self.mem.get(self.pointer + offset, 0) for offset in range(n))


def test_scan_returns_registered_addresses_sorted():
    bus = I2CBus()
    bus.register(0x53, RecordingDevice())
    bus.register(0x3C, RecordingDevice())

    assert bus.scan() == [0x3C, 0x53]


def test_writevto_delivers_combined_payload_as_one_transaction():
    board = Board()
    Pin.use_board(board)
    device = RecordingDevice()
    board.i2c_bus.register(0x3C, device)
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))

    i2c.writevto(0x3C, [b"@", bytearray(1024)])

    assert device.writes == [(b"@" + bytes(1024), False)]


def test_large_write_advances_clock_by_bus_timing():
    clock = VirtualClock()
    board = Board(clock=clock)
    Pin.use_board(board)
    board.i2c_bus.register(0x3C, RecordingDevice())
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))

    i2c.writevto(0x3C, [b"@", bytearray(1024)])

    assert 20_000 <= clock.now_us <= 27_000


def test_readfrom_mem_unregistered_address_raises_enodev():
    board = Board()
    Pin.use_board(board)
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))

    with pytest.raises(OSError) as excinfo:
        i2c.readfrom_mem(0x10, 0x08, 2)

    assert excinfo.value.args[0] == 19


def test_writeto_mem_and_readfrom_mem_round_trip_against_memory_device():
    board = Board()
    Pin.use_board(board)
    board.i2c_bus.register(0x10, MemoryDevice())
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))

    i2c.writeto_mem(0x10, 0x08, b"\x34\x12")

    assert i2c.readfrom_mem(0x10, 0x08, 2) == b"\x34\x12"
