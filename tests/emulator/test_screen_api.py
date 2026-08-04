"""T024 screen locator and snapshot API tests.

Co-authored-by: GPT-5, Aug 2026
"""

import os

import pytest

import smotor


def test_expect_text_finds_text_that_appears_three_frames_later():
    sm = smotor.launch()
    try:
        for index, text in enumerate(("one", "two", "READY"), start=1):
            sm.session.board.scheduler.after(index * 100_000, _draw_screen_text, sm, text)

        sm.screen.expect_text("READY", timeout_ms=500)

        assert sm.session.clock.now_ms() >= 300
    finally:
        sm.close()


def test_expect_lines_near_miss_has_readable_diff():
    sm = smotor.launch()
    try:
        _draw_screen_text(sm, "HELLO")

        with pytest.raises(TimeoutError) as exc:
            sm.screen.expect_lines(["HALLO"], timeout_ms=10)

        message = str(exc.value)
        assert "- HALLO" in message
        assert "+ HELLO" in message
    finally:
        sm.close()


def test_snapshot_creates_matches_then_detects_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sm = smotor.launch()
    try:
        _draw_screen_text(sm, "SNAP")

        path = sm.screen.assert_snapshot("screen_one")
        assert path.endswith("tests/emulator/__snapshots__/screen_one.txt")
        assert os.path.exists(path)

        sm.screen.assert_snapshot("screen_one")

        _draw_screen_text(sm, "CHANGED")
        with pytest.raises(AssertionError, match="screen snapshot mismatch"):
            sm.screen.assert_snapshot("screen_one")
    finally:
        sm.close()


def test_png_differs_between_two_different_screens():
    sm = smotor.launch()
    try:
        _draw_screen_text(sm, "A")
        first = sm.screen.png()
        _draw_screen_text(sm, "B")
        second = sm.screen.png()

        assert first != second
    finally:
        sm.close()


def test_screen_text_contains_and_frames():
    sm = smotor.launch()
    try:
        _draw_screen_text(sm, "FIRST")
        _draw_screen_text(sm, "SECOND")

        assert sm.screen.lines() == ["SECOND"]
        assert sm.screen.text() == "SECOND"
        assert sm.screen.contains("CON")
        assert "FIRST" in sm.screen.frames()
        assert sm.screen.frames()[-1] == "SECOND"
    finally:
        sm.close()


def _draw_screen_text(sm, text):
    from smotoremu.device_env import load_real_ssd1306
    from smotoremu.machine_shim import Pin, SoftI2C

    ssd1306 = load_real_ssd1306()
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    display = ssd1306.SSD1306_I2C(128, 64, i2c)
    display.fill(0)
    display.text(text, 0, 0, 1)
    display.show()
