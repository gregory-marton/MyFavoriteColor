"""Auto-waiting expectations against virtual emulator time.

Co-authored-by: GPT-5, Aug 2026
"""


def wait_for(predicate, *, session=None, timeout_ms=5000, poll_ms=10, message=None):
    session = session or _infer_session(predicate)
    start_ms = session.clock.now_ms()
    timeout_at = start_ms + timeout_ms
    while True:
        _fail_fast_if_device_stopped(session)
        if predicate():
            return
        now_ms = session.clock.now_ms()
        if now_ms >= timeout_at:
            raise TimeoutError(message or _timeout_message("predicate to become true", False, session, now_ms - start_ms))
        step_ms = min(poll_ms, timeout_at - now_ms)
        session.clock.sleep_us(step_ms * 1000)
        session.run_until_idle(timeout_ms=0)


def expect(target, *, session=None):
    return Expectation(target, session=session)


class Expectation:
    def __init__(self, target, *, session=None, negated=False):
        self.target = target
        self.session = session or _infer_session(target)
        self.negated = negated

    def to_be(self, value, *, timeout_ms=5000):
        return self._wait(
            lambda actual: actual == value,
            f"to be {value!r}",
            timeout_ms=timeout_ms,
        )

    def to_be_close(self, value, abs_tol, *, timeout_ms=5000):
        return self._wait(
            lambda actual: abs(actual - value) <= abs_tol,
            f"to be close to {value!r} ± {abs_tol!r}",
            timeout_ms=timeout_ms,
        )

    def to_contain(self, substring, *, timeout_ms=5000):
        return self._wait(
            lambda actual: substring in actual,
            f"to contain {substring!r}",
            timeout_ms=timeout_ms,
        )

    def to_have_text(self, text, *, timeout_ms=5000):
        return self._wait(
            lambda actual: text in "\n".join(actual.lines()),
            f"to have text {text!r}",
            timeout_ms=timeout_ms,
        )

    def not_(self) -> "Expectation":
        return Expectation(self.target, session=self.session, negated=not self.negated)

    def _wait(self, matcher, expected, *, timeout_ms):
        start_ms = self.session.clock.now_ms()
        timeout_at = start_ms + timeout_ms
        actual = self._actual()
        while True:
            _fail_fast_if_device_stopped(self.session)
            matched = matcher(actual)
            if matched != self.negated:
                return
            now_ms = self.session.clock.now_ms()
            if now_ms >= timeout_at:
                if self.negated:
                    expected = f"not {expected}"
                raise TimeoutError(_timeout_message(expected, actual, self.session, now_ms - start_ms))
            step_ms = min(10, timeout_at - now_ms)
            self.session.clock.sleep_us(step_ms * 1000)
            self.session.run_until_idle(timeout_ms=0)
            actual = self._actual()

    def _actual(self):
        if callable(self.target):
            return self.target()
        return self.target


def _fail_fast_if_device_stopped(session):
    if session.error is not None:
        raise session.error
    if session.exited:
        raise RuntimeError("device thread exited before expectation was satisfied")


def _timeout_message(expected, actual, session, elapsed_ms):
    lines = _screen_lines(session)[-8:]
    screen = "\n".join(lines) if lines else "<blank>"
    return (
        f"Expected {expected}; actual {actual!r}; elapsed {elapsed_ms} ms virtual time; "
        f"last screen lines:\n{screen}"
    )


def _screen_lines(session):
    display = getattr(session, "display", None)
    if display is None:
        return []
    try:
        return display.text_lines()
    except Exception:
        return []


def _infer_session(target):
    if hasattr(target, "session"):
        return target.session
    closure = getattr(target, "__closure__", None)
    if closure:
        for cell in closure:
            value = cell.cell_contents
            if hasattr(value, "session"):
                return value.session
            if hasattr(value, "clock") and hasattr(value, "trace"):
                return value
    raise ValueError("session is required when it cannot be inferred")
