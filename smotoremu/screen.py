"""Screen locator and snapshot API for SmartMotor tests.

Co-authored-by: GPT-5, Aug 2026
"""

import difflib
import os

from smotoremu.expect import wait_for
from smotoremu.screen_text import contains_rendered_text, extract_line_candidates

SNAPSHOT_DIR = os.path.join("tests", "emulator", "__snapshots__")


class Screen:
    def __init__(self, session):
        self.session = session
        self._current_candidate_frame_count = -1
        self._current_candidate_text = ""

    def lines(self) -> list[str]:
        return self.session.display.text_lines()

    def text(self) -> str:
        return "\n".join(self.lines())

    def contains(self, text) -> bool:
        return text in self.text() or self.session.display.contains_rendered_text(text)

    def expect_text(self, text, timeout_ms=5000):
        wait_for(
            lambda: self.session.display.contains_rendered_text(text)
            or self._current_candidates_contain(text)
            or self._history_contains_rendered_text(text),
            session=self.session,
            timeout_ms=timeout_ms,
            message=lambda: _text_timeout_message(text, self),
        )

    def expect_lines(self, lines, timeout_ms=5000):
        expected = list(lines)

        def matches():
            return self.lines() == expected

        wait_for(
            matches,
            session=self.session,
            timeout_ms=timeout_ms,
            message=lambda: _lines_diff_message(expected, self.lines()),
        )

    def png(self, scale=4) -> bytes:
        return self.session.display.to_png(scale=scale)

    def frames(self) -> list[str]:
        return list(self.session.display.frame_texts)

    def _history_contains_rendered_text(self, text):
        display = self.session.display
        for frame in reversed(display.frame_buffers):
            if contains_rendered_text(frame, text, width=display.width, height=display.height):
                return True
        return False

    def _current_candidates_contain(self, text):
        display = self.session.display
        if self._current_candidate_frame_count != display.frame_count:
            candidates = extract_line_candidates(display.gddram, width=display.width, height=display.height)
            self._current_candidate_text = "\n".join(candidates)
            self._current_candidate_frame_count = display.frame_count
        return text in self._current_candidate_text

    def assert_snapshot(self, name):
        path = os.path.join(SNAPSHOT_DIR, f"{name}.txt")
        actual = self.text() + ("\n" if self.text() else "")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path) or os.environ.get("SMOTOR_UPDATE_SNAPSHOTS") == "1":
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(actual)
            print(f"wrote screen snapshot {path}")
            return path
        with open(path, "r", encoding="utf-8") as handle:
            expected = handle.read()
        if actual != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    fromfile=path,
                    tofile="current screen",
                )
            )
            raise AssertionError(f"screen snapshot mismatch for {name}\n{diff}")
        return path


def _lines_diff_message(expected, actual):
    diff = "\n".join(difflib.ndiff(expected, actual))
    return f"expected screen lines to match\n{diff}"


def _text_timeout_message(expected, screen):
    frames = screen.frames()[-5:]
    if frames:
        history = "\n---\n".join(frame or "<blank>" for frame in frames)
    else:
        history = "<no frames>"
    current = screen.text() or "<blank>"
    display = screen.session.display
    bus_display = screen.session.bus.devices.get(0x3C)
    i2c_addrs = [
        event["detail"].get("addr")
        for event in screen.session.trace.events[-20:]
        if event["kind"] == "i2c"
    ]
    i2c_counts = {}
    for event in screen.session.trace.events:
        if event["kind"] == "i2c":
            addr = event["detail"].get("addr")
            i2c_counts[addr] = i2c_counts.get(addr, 0) + 1
    return (
        f"expected screen to contain {expected!r}\n"
        f"current:\n{current}\n"
        f"recent frames:\n{history}\n"
        f"display frame_count={display.frame_count}; "
        f"bus[0x3c]={type(bus_display).__name__}; same_display={bus_display is display}; "
        f"bus devices={sorted(screen.session.bus.devices)}; "
        f"i2c counts={i2c_counts}; recent i2c addrs={i2c_addrs}"
    )
