"""T002 virtual clock and event scheduler tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pytest

from smotoremu.clock import ClockStuckError, EventScheduler, VirtualClock


def test_clock_starts_at_zero_and_sleep_advances_time():
    clock = VirtualClock()

    assert clock.now_us == 0
    clock.sleep_us(1000)
    assert clock.now_us == 1000
    assert clock.now_ms() == 1


def test_events_fire_in_timestamp_order_across_sleep():
    clock = VirtualClock()
    scheduler = EventScheduler(clock)
    seen = []

    scheduler.after(300, seen.append, "late")
    scheduler.after(100, seen.append, "early")

    clock.sleep_us(500)

    assert seen == ["early", "late"]


def test_equal_timestamps_fire_in_insertion_order():
    clock = VirtualClock()
    scheduler = EventScheduler(clock)
    seen = []

    scheduler.at(100, seen.append, "a")
    scheduler.at(100, seen.append, "b")
    scheduler.at(100, seen.append, "c")

    clock.sleep_us(100)

    assert seen == ["a", "b", "c"]


def test_cancel_prevents_event_from_firing():
    clock = VirtualClock()
    scheduler = EventScheduler(clock)
    seen = []

    handle = scheduler.after(100, seen.append, "cancelled")
    scheduler.cancel(handle)
    clock.sleep_us(100)

    assert seen == []


def test_every_refires_and_can_cancel_itself():
    clock = VirtualClock()
    scheduler = EventScheduler(clock)
    seen = []
    handle_box = {}

    def tick():
        seen.append(clock.now_us)
        if len(seen) == 3:
            scheduler.cancel(handle_box["handle"])

    handle_box["handle"] = scheduler.every(100, tick)

    clock.sleep_us(500)

    assert seen == [100, 200, 300]


def test_scheduling_at_now_repeatedly_raises_clock_stuck_error():
    clock = VirtualClock()
    scheduler = EventScheduler(clock)

    def reschedule():
        scheduler.at(clock.now_us, reschedule)

    scheduler.at(0, reschedule)

    with pytest.raises(ClockStuckError):
        clock.sleep_us(0)


def test_sleep_zero_fires_events_due_now():
    clock = VirtualClock()
    scheduler = EventScheduler(clock)
    seen = []

    scheduler.at(0, seen.append, "now")
    clock.sleep_us(0)

    assert seen == ["now"]


def test_next_event_time_reports_earliest_uncancelled_event():
    clock = VirtualClock()
    scheduler = EventScheduler(clock)
    early = scheduler.at(50, lambda: None)
    scheduler.at(100, lambda: None)

    assert scheduler.next_event_time() == 50
    scheduler.cancel(early)
    assert scheduler.next_event_time() == 100
