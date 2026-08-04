"""T008 Timer, reset, and unique_id machine shim tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pytest

from smotoremu.machine_shim import Board, DeviceReset, Pin, Timer, reset, unique_id


def use_fresh_board(**kwargs):
    board = Board(**kwargs)
    Pin.use_board(board)
    return board


def test_periodic_timer_fires_five_times_across_fifty_virtual_seconds():
    board = use_fresh_board()
    fired = []
    timer = Timer(1)

    timer.init(
        period=10_000,
        mode=Timer.PERIODIC,
        callback=lambda timer_arg: fired.append((timer_arg, board.clock.now_ms())),
    )
    board.clock.sleep_us(50_000_000)

    assert fired == [
        (timer, 10_000),
        (timer, 20_000),
        (timer, 30_000),
        (timer, 40_000),
        (timer, 50_000),
    ]


def test_deinit_stops_periodic_timer_and_is_safe_before_init():
    board = use_fresh_board()
    fired = []
    timer = Timer(1)

    timer.deinit()
    timer.init(period=10_000, mode=Timer.PERIODIC, callback=lambda _: fired.append(board.clock.now_ms()))
    board.clock.sleep_us(10_000_000)
    timer.deinit()
    board.clock.sleep_us(30_000_000)

    assert fired == [10_000]


def test_one_shot_timer_fires_once():
    board = use_fresh_board()
    fired = []
    timer = Timer(1)

    timer.init(period=10_000, mode=Timer.ONE_SHOT, callback=lambda _: fired.append(board.clock.now_ms()))
    board.clock.sleep_us(30_000_000)

    assert fired == [10_000]


def test_timers_with_different_ids_are_independent():
    board = use_fresh_board()
    fired = []
    timer_1 = Timer(1)
    timer_2 = Timer(2)

    timer_1.init(period=10_000, mode=Timer.PERIODIC, callback=lambda _: fired.append(("one", board.clock.now_ms())))
    timer_2.init(period=25_000, mode=Timer.PERIODIC, callback=lambda _: fired.append(("two", board.clock.now_ms())))
    board.clock.sleep_us(50_000_000)

    assert [event for event in fired if event[0] == "one"] == [
        ("one", 10_000),
        ("one", 20_000),
        ("one", 30_000),
        ("one", 40_000),
        ("one", 50_000),
    ]
    assert [event for event in fired if event[0] == "two"] == [
        ("two", 25_000),
        ("two", 50_000),
    ]


def test_unique_id_comes_from_active_board_and_is_configurable():
    board = use_fresh_board(unique_id=b"\xde\xad\xbe\xef")

    assert unique_id() == b"\xde\xad\xbe\xef"

    board.set_unique_id(b"\x12\x34\x56\x78")
    assert unique_id() == b"\x12\x34\x56\x78"


def test_reset_raises_device_reset_signal():
    use_fresh_board()

    with pytest.raises(DeviceReset):
        reset()
