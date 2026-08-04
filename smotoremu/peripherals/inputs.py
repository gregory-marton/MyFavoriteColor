"""Buttons, potentiometer, and battery models for SmartMotor emulation.

Co-authored-by: GPT-5, Aug 2026
"""

import random

from smotoremu.pinmap import BUTTON_PINS, PIN_BATTERY, PIN_POT


class Buttons:
    def __init__(self, board, bounce_ms=0):
        self.board = board
        self.bounce_ms = bounce_ms

    def press(self, name: str) -> None:
        self._set(name, 0)

    def release(self, name: str) -> None:
        self._set(name, 1)

    def click(self, name: str, hold_ms: int = 120) -> None:
        self.press(name)
        self.board.scheduler.after(hold_ms * 1000, self.release, name)

    def held(self) -> set[str]:
        return {name for name, pin in BUTTON_PINS.items() if self.board.pin_value(pin) == 0}

    def _set(self, name, stable_value):
        if name not in BUTTON_PINS:
            raise ValueError(f"unknown button {name!r}")
        pin = BUTTON_PINS[name]
        if self.bounce_ms <= 0:
            self.board.pin_value(pin, stable_value)
            return
        opposite = 1 - stable_value
        self.board.pin_value(pin, opposite)
        interval_us = max(1, self.bounce_ms * 1000 // 4)
        for step, value in enumerate((stable_value, opposite, stable_value), start=1):
            self.board.scheduler.after(interval_us * step, self.board.pin_value, pin, value)


class Potentiometer:
    """Pot raw values are inverted relative to servo angle.

    `set_angle()` follows `myfavcolor.update_motor_with_pot()`:
    angle = int((1 - raw / 4095) * 180).
    """

    def __init__(self, board, noise_lsb=8, rng=None, pin_id=PIN_POT):
        self.board = board
        self.pin_id = pin_id
        self.noise_lsb = noise_lsb
        self.rng = rng or random.Random(0)
        self.raw = 2048
        self.set_raw(self.raw)
        self.board.set_adc_noise(self.pin_id, self._read)

    def set_raw(self, raw: int) -> None:
        self.raw = min(4095, max(0, int(raw)))
        self.board.set_adc(self.pin_id, self.raw)

    def set_angle(self, degrees: float) -> None:
        raw = int(4095 * (1 - degrees / 180))
        self.set_raw(raw)

    def _read(self):
        if self.noise_lsb <= 0:
            return self.raw
        value = int(round(self.raw + self.rng.gauss(0, self.noise_lsb)))
        return min(4095, max(0, value))


class Battery:
    """Battery ADC model for sensors.readbattery().

    `sensors.readbattery()` has intentional quirks: 2850-2875 is ambiguous,
    and exact raw values 2500 and 2700 fall into no named band. Use `set_raw()`
    when a test needs those edge cases.
    """

    STATES = {
        "charging": 2900,
        "full": 2750,
        "half": 2600,
        "low": 2400,
    }

    def __init__(self, board, pin_id=PIN_BATTERY):
        self.board = board
        self.pin_id = pin_id
        self.raw = 2750
        self.set_raw(self.raw)

    def set_raw(self, raw: int) -> None:
        self.raw = min(4095, max(0, int(raw)))
        self.board.set_adc(self.pin_id, self.raw)

    def set_state(self, state: str) -> None:
        if state not in self.STATES:
            raise ValueError(f"unknown battery state {state!r}")
        self.set_raw(self.STATES[state])
