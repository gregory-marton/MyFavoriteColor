"""T011 buttons, potentiometer, and battery peripheral tests.

Co-authored-by: GPT-5, Aug 2026
"""

import importlib
import random

from smotoremu.device_env import load_real_sensors
from smotoremu.machine_shim import Board, Pin
from smotoremu.peripherals.inputs import Battery, Buttons, Potentiometer
from smotoremu.pinmap import PIN_BATTERY, PIN_POT


def use_board():
    board = Board()
    Pin.use_board(board)
    return board


def test_buttons_press_release_and_held_are_active_low():
    board = use_board()
    buttons = Buttons(board)

    buttons.press("up")
    assert Pin(10).value() == 0
    assert buttons.held() == {"up"}

    buttons.release("up")
    assert Pin(10).value() == 1
    assert buttons.held() == set()


def test_button_click_auto_releases_after_hold():
    board = use_board()
    buttons = Buttons(board)

    buttons.click("select", hold_ms=120)
    assert buttons.held() == {"select"}

    board.clock.sleep_us(119_000)
    assert buttons.held() == {"select"}

    board.clock.sleep_us(1_000)
    assert buttons.held() == set()


def test_potentiometer_angle_round_trips_through_activity_mapping(monkeypatch):
    board = use_board()
    pot = Potentiometer(board, noise_lsb=0)
    pot.set_angle(90)
    myfavcolor = importlib.import_module("myfavcolor")
    monkeypatch.setattr(myfavcolor, "sens", type("SensorStub", (), {"readpot": lambda self: Pin._board.adc_read(PIN_POT)})())
    moved = []
    monkeypatch.setattr(myfavcolor, "move_servo", lambda angle: moved.append(angle) or angle)

    pot_value, angle = myfavcolor.update_motor_with_pot(last_pot_value=0, last_servo_angle=0)

    assert pot_value == 2047
    assert angle == 90
    assert moved == [90]


def test_potentiometer_noise_is_per_read_bounded_and_variable():
    board = use_board()
    pot = Potentiometer(board, noise_lsb=8, rng=random.Random(0))
    pot.set_raw(2048)

    readings = [Pin._board.adc_read(PIN_POT) for _ in range(40)]

    assert all(0 <= reading <= 4095 for reading in readings)
    assert len(set(readings)) > 1
    assert all(abs(reading - 2048) <= 32 for reading in readings)


def test_battery_states_match_real_readbattery():
    board = use_board()
    battery = Battery(board)
    sensors = load_real_sensors()
    real_sensors = sensors.SENSORS()

    for state in ("charging", "full", "half", "low"):
        battery.set_state(state)
        assert Pin._board.adc_read(PIN_BATTERY) == battery.raw
        assert real_sensors.readbattery() == state


def test_battery_raw_can_target_dead_zone():
    board = use_board()
    battery = Battery(board)
    sensors = load_real_sensors()
    real_sensors = sensors.SENSORS()

    battery.set_raw(2700)

    assert real_sensors.readbattery() == ""
