"""I2C bus and device protocol for the SmartMotor emulator.

Co-authored-by: GPT-5, Aug 2026
"""

I2C_START_STOP_OVERHEAD_US = 10  # GUESS: start/stop overhead; needs bench data.


class I2CDevice:
    def on_write(self, data: bytes, is_continuation: bool = False):
        pass

    def on_read(self, n: int) -> bytes:
        return b"\x00" * n


class I2CBus:
    def __init__(self, clock=None, freq=400_000):
        self.clock = clock
        self.freq = freq  # 400 kHz: MicroPython SoftI2C default when no freq= is passed.
        self.devices = {}

    def register(self, addr: int, device: I2CDevice) -> None:
        self.devices[addr] = device

    def unregister(self, addr: int) -> None:
        self.devices.pop(addr, None)

    def scan(self) -> list[int]:
        return sorted(self.devices)

    def writeto(self, addr, data):
        device = self._device(addr)
        payload = bytes(data)
        self._charge_time(len(payload))
        device.on_write(payload, is_continuation=False)

    def writevto(self, addr, vector):
        device = self._device(addr)
        payload = b"".join(bytes(part) for part in vector)
        self._charge_time(len(payload))
        device.on_write(payload, is_continuation=False)

    def readfrom(self, addr, n):
        device = self._device(addr)
        self._charge_time(n)
        return device.on_read(n)

    def writeto_mem(self, addr, memaddr, data):
        device = self._device(addr)
        payload = bytes([memaddr]) + bytes(data)
        self._charge_time(len(payload))
        device.on_write(payload, is_continuation=False)

    def readfrom_mem(self, addr, memaddr, n):
        device = self._device(addr)
        self._charge_time(1)
        device.on_write(bytes([memaddr]), is_continuation=False)
        self._charge_time(n)
        return device.on_read(n)

    def _device(self, addr):
        if addr not in self.devices:
            raise OSError(19)
        return self.devices[addr]

    def _charge_time(self, n_data_bytes):
        if self.clock is None:
            return
        bits = (n_data_bytes + 1) * 9
        bus_time_us = int(round(bits * 1_000_000 / self.freq))
        self.clock.sleep_us(bus_time_us + I2C_START_STOP_OVERHEAD_US)
