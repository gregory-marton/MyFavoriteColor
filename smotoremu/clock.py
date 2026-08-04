"""Virtual time and scheduled events for the SmartMotor emulator.

Co-authored-by: GPT-5, Aug 2026
"""

from dataclasses import dataclass
import heapq
import itertools
import time


class ClockStuckError(RuntimeError):
    pass


@dataclass
class Handle:
    t_us: int
    sequence: int
    callback: object
    args: tuple
    period_us: int | None = None
    cancelled: bool = False


class VirtualClock:
    def __init__(self, mode: str = "instant", speed: float = 1.0):
        self._now_us = 0
        self._schedulers = []
        self.set_mode(mode, speed)

    @property
    def now_us(self) -> int:
        return self._now_us

    def now_ms(self) -> int:
        return self._now_us // 1000

    def sleep_us(self, us: int) -> None:
        if us < 0:
            raise ValueError("sleep_us requires a non-negative duration")
        target = self._now_us + us
        if self.mode == "instant":
            self.advance_to(target)
            return

        wall_sleep = us / 1_000_000
        if self.mode == "scaled":
            wall_sleep = wall_sleep / self.speed
        time.sleep(wall_sleep)
        self.advance_to(target)

    def advance_to(self, t_us: int) -> None:
        if t_us < self._now_us:
            raise ValueError("cannot move virtual time backwards")
        for scheduler in self._schedulers:
            scheduler.run_until(t_us)
        self._now_us = t_us
        for scheduler in self._schedulers:
            scheduler.run_until(t_us)

    def set_mode(self, mode: str, speed: float = 1.0) -> None:
        if mode not in {"instant", "realtime", "scaled"}:
            raise ValueError("mode must be instant, realtime, or scaled")
        if speed <= 0:
            raise ValueError("speed must be positive")
        self.mode = mode
        self.speed = speed

    def _register_scheduler(self, scheduler) -> None:
        self._schedulers.append(scheduler)


class EventScheduler:
    MAX_EVENTS_AT_ONE_INSTANT = 100_000

    def __init__(self, clock: VirtualClock):
        self.clock = clock
        self._queue = []
        self._sequence = itertools.count()
        self.clock._register_scheduler(self)

    def at(self, t_us: int, callback, *args) -> Handle:
        if t_us < self.clock.now_us:
            raise ValueError("cannot schedule an event in the past")
        return self._push(t_us, callback, args, period_us=None)

    def after(self, delay_us: int, callback, *args) -> Handle:
        if delay_us < 0:
            raise ValueError("delay_us must be non-negative")
        return self.at(self.clock.now_us + delay_us, callback, *args)

    def every(self, period_us: int, callback, *args) -> Handle:
        if period_us <= 0:
            raise ValueError("period_us must be positive")
        return self._push(self.clock.now_us + period_us, callback, args, period_us=period_us)

    def cancel(self, handle: Handle) -> None:
        handle.cancelled = True

    def next_event_time(self) -> int | None:
        self._discard_cancelled()
        if not self._queue:
            return None
        return self._queue[0][0]

    def run_until(self, t_us: int) -> None:
        events_at_current_time = 0
        last_event_time = None
        while True:
            self._discard_cancelled()
            if not self._queue or self._queue[0][0] > t_us:
                break
            event_time, _, handle = heapq.heappop(self._queue)
            if handle.cancelled:
                continue
            if event_time == last_event_time:
                events_at_current_time += 1
            else:
                last_event_time = event_time
                events_at_current_time = 1
            if events_at_current_time > self.MAX_EVENTS_AT_ONE_INSTANT:
                raise ClockStuckError(f"too many events scheduled at {event_time} us")

            self.clock._now_us = event_time
            handle.callback(*handle.args)
            if handle.period_us is not None and not handle.cancelled:
                handle.t_us = event_time + handle.period_us
                handle.sequence = next(self._sequence)
                heapq.heappush(self._queue, (handle.t_us, handle.sequence, handle))

    def _push(self, t_us, callback, args, period_us):
        handle = Handle(
            t_us=t_us,
            sequence=next(self._sequence),
            callback=callback,
            args=args,
            period_us=period_us,
        )
        heapq.heappush(self._queue, (handle.t_us, handle.sequence, handle))
        return handle

    def _discard_cancelled(self):
        while self._queue and self._queue[0][2].cancelled:
            heapq.heappop(self._queue)
