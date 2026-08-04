"""T010 servo model tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pytest

from smotoremu.device_env import load_real_servo
from smotoremu.machine_shim import Board, Pin
from smotoremu.peripherals.servo import ServoModel
from smotoremu.pinmap import PIN_SERVO


def make_servo():
    board = Board()
    Pin.use_board(board)
    model = ServoModel(board, pin_id=PIN_SERVO)
    servo_module = load_real_servo()
    return board, model, servo_module.Servo(Pin(PIN_SERVO))


def settle(board, model):
    while model.is_moving:
        board.clock.sleep_us(10_000)


def test_write_angle_zero_settles_at_zero_degrees():
    board, model, servo = make_servo()

    servo.write_angle(0)
    settle(board, model)

    assert model.actual_angle == 0.0


def test_write_angle_180_lands_within_one_quantum():
    board, model, servo = make_servo()

    servo.write_angle(180)
    settle(board, model)

    assert model.actual_angle == pytest.approx(178.28125)


def test_write_angle_90_preserves_pwm_quantization():
    _, model, servo = make_servo()

    servo.write_angle(90)

    assert model.commanded_angle == pytest.approx(88.4375)


def test_write_angle_above_range_clamps_to_servo_max():
    board, model, servo = make_servo()

    servo.write_angle(200)
    settle(board, model)

    assert model.actual_angle <= 180
    assert model.actual_angle == pytest.approx(178.28125)


def test_duty_zero_holds_current_position():
    board, model, servo = make_servo()
    servo.write_angle(90)
    settle(board, model)
    held = model.actual_angle

    servo.write_us(0)
    board.clock.sleep_us(1_000_000)

    assert model.actual_angle == held
    assert not model.is_moving


def test_full_range_move_slews_over_virtual_time():
    board, model, servo = make_servo()

    servo.write_angle(180)

    assert model.is_moving
    board.clock.sleep_us(225_000)
    assert model.is_moving
    assert model.actual_angle == pytest.approx(90, abs=2)
    board.clock.sleep_us(300_000)
    assert not model.is_moving
    assert model.actual_angle == pytest.approx(model.commanded_angle)
