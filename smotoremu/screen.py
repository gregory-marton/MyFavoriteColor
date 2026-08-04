"""Screen locator and snapshot API for SmartMotor tests.

Co-authored-by: GPT-5, Aug 2026
"""

import difflib
import os

from smotoremu.expect import wait_for

SNAPSHOT_DIR = os.path.join("tests", "emulator", "__snapshots__")


class Screen:
    def __init__(self, session):
        self.session = session

    def lines(self) -> list[str]:
        return self.session.display.text_lines()

    def text(self) -> str:
        return "\n".join(self.lines())

    def contains(self, text) -> bool:
        return text in self.text()

    def expect_text(self, text, timeout_ms=5000):
        wait_for(
            lambda: self.contains(text),
            session=self.session,
            timeout_ms=timeout_ms,
            message=lambda: f"expected screen to contain {text!r}\n{self.text()}",
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
