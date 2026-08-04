"""T023 auto-waiting expectation tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pytest

import smotor
from smotoremu.expect import wait_for


def test_wait_for_true_predicate_returns_without_clock_advance():
    sm = smotor.launch()
    try:
        wait_for(lambda: True, session=sm.session, timeout_ms=1000)
        assert sm.session.clock.now_ms() == 0
    finally:
        sm.close()


def test_wait_for_becomes_true_after_virtual_time_advance():
    sm = smotor.launch()
    try:
        state = {"ready": False}
        sm.session.board.scheduler.after(500_000, lambda: state.update(ready=True))

        wait_for(lambda: state["ready"], session=sm.session, timeout_ms=1000, poll_ms=10)

        assert sm.session.clock.now_ms() == 500
    finally:
        sm.close()


def test_wait_for_timeout_uses_exact_virtual_timeout():
    sm = smotor.launch()
    try:
        with pytest.raises(TimeoutError):
            wait_for(lambda: False, session=sm.session, timeout_ms=120, poll_ms=10)

        assert sm.session.clock.now_ms() == 120
    finally:
        sm.close()


def test_failure_message_contains_actual_elapsed_and_screen_text():
    sm = smotor.launch()
    try:
        sm.session.display._gddram[:] = bytes(1024)
        _draw_screen_text(sm, "Still waiting")

        with pytest.raises(TimeoutError) as exc:
            smotor.expect(lambda: "actual value", session=sm.session).to_be(
                "expected value", timeout_ms=20
            )

        message = str(exc.value)
        assert "expected value" in message
        assert "actual value" in message
        assert "20 ms" in message
        assert "Still waiting" in message
    finally:
        sm.close()


def test_crashed_device_thread_fails_fast_not_at_timeout(tmp_path, monkeypatch):
    (tmp_path / "crash_program.py").write_text("def main():\n    raise RuntimeError('boom')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    sm = smotor.launch()
    try:
        sm.boot("crash_program")
        sm.session.run_until_idle()

        with pytest.raises(RuntimeError, match="boom"):
            smotor.expect(lambda: False, session=sm.session).to_be(True, timeout_ms=1000)

        assert sm.session.clock.now_ms() == 0
    finally:
        sm.close()


def test_expect_lambda_can_infer_session_from_closure():
    sm = smotor.launch()
    try:
        sm.session.board.scheduler.after(30_000, lambda: setattr(sm.session.servo, "_actual_angle", 90))

        smotor.expect(lambda: sm.arm.angle).to_be_close(90, 0.1, timeout_ms=100)

        assert sm.session.clock.now_ms() == 30
    finally:
        sm.close()


def test_screen_expectation_to_have_text():
    sm = smotor.launch()
    try:
        sm.session.board.scheduler.after(20_000, lambda: _draw_screen_text(sm, "Point at WHITE"))

        smotor.expect(sm.screen).to_have_text("Point at WHITE", timeout_ms=100)
    finally:
        sm.close()


def _draw_screen_text(sm, text):
    from smotoremu.device_env import load_real_ssd1306
    from smotoremu.i2c import I2CDevice
    from smotoremu.machine_shim import Pin, SoftI2C

    sm.session.bus.register(0x3C, sm.session.display)
    ssd1306 = load_real_ssd1306()
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    display = ssd1306.SSD1306_I2C(128, 64, i2c)
    display.fill(0)
    display.text(text, 0, 0, 1)
    display.show()
