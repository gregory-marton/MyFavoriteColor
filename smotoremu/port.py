"""Sensor port model for analog/I2C attachment probing.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.pinmap import PIN_SENSOR_PORT


class Port:
    FLOATING_I2C_ADC = 2048  # ASSUMPTION: awaiting confirmation of analog/I2C toggle wiring.

    def __init__(self, board, bus, mode="i2c"):
        self.board = board
        self.bus = bus
        self.mode = mode
        self.attached = None
        self._registered_i2c_addr = None
        self.board.set_port_adc_stub(lambda driven_level: self.pin5_adc())

    def attach(self, sensor) -> None:
        self.detach()
        self.attached = sensor
        self._sync_i2c_registration()

    def detach(self) -> None:
        if self._registered_i2c_addr is not None:
            self.bus.unregister(self._registered_i2c_addr)
            self._registered_i2c_addr = None
        self.attached = None

    def set_mode(self, mode: str) -> None:
        if mode not in {"analog", "i2c"}:
            raise ValueError("mode must be 'analog' or 'i2c'")
        self.mode = mode
        self._sync_i2c_registration()

    def pin5_adc(self) -> int:
        if self.attached is None:
            return 4095 if self.board.pin_value(PIN_SENSOR_PORT) else 0
        if _is_i2c_sensor(self.attached):
            return self.FLOATING_I2C_ADC
        return _analog_raw(self.attached)

    def _sync_i2c_registration(self):
        if self._registered_i2c_addr is not None:
            self.bus.unregister(self._registered_i2c_addr)
            self._registered_i2c_addr = None

        if self.attached is None or self.mode != "i2c" or not _is_i2c_sensor(self.attached):
            return

        self.bus.register(self.attached.i2c_address, self.attached.device)
        self._registered_i2c_addr = self.attached.i2c_address


def _is_i2c_sensor(sensor):
    return hasattr(sensor, "i2c_address") and hasattr(sensor, "device")


def _analog_raw(sensor):
    if hasattr(sensor, "output_raw"):
        return int(sensor.output_raw())
    if hasattr(sensor, "pin5_adc"):
        return int(sensor.pin5_adc())
    raise TypeError("analog sensor must provide output_raw() or pin5_adc()")
