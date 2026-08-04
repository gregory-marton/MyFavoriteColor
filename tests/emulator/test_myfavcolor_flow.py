"""End-to-end My Favorite Color flow tests on the SmartMotor emulator.

Co-authored-by: GPT-5, Aug 2026
"""

import smotor
from smotoremu.expect import wait_for

NUM_STATES = 7


def test_favorite_color_walkthrough(sm_color):
    sm_color.boot()
    sm_color.screen.expect_text("Starting in 2s")
    sm_color.screen.expect_text("Point at WHITE")
    sm_color.pot.set_angle(45)
    sm_color.click("select")
    sm_color.screen.expect_text("White Balance")
    sm_color.screen.expect_text("Set FAV color")
    sm_color.pot.set_angle(10)
    sm_color.click("select")
    for state in range(NUM_STATES):
        sm_color.screen.expect_text(f"state={state}")
        sm_color.click("select")
    sm_color.screen.expect_text("Press to start")
    sm_color.click("select")
    sm_color.screen.expect_text("E=0", timeout_ms=60_000)


def test_main_without_color_sensor_dispatches_to_standalone_not_myfavcolor():
    sm = smotor.launch()
    try:
        sm.boot()
        wait_for(
            lambda: "standalone" in sm.session.imported_modules
            or "myfavcolor" in sm.session.imported_modules,
            session=sm.session,
            timeout_ms=2500,
        )
        assert "standalone" in sm.session.imported_modules
        assert "myfavcolor" not in sm.session.imported_modules
    finally:
        sm.close()
