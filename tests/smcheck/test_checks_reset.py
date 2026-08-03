"""D004: D-RST check. Written before smcheck/checks/reset.py exists.

Scoped down from DEVICE_HEALTH_DESIGN.md's "reset_cause() + persisted boot
counter": a boot counter needs code added to boot.py, which is a fleet-wide
firmware change that shouldn't happen without the user signing off (same
spirit as EMULATOR_TASKS.md's R1). This check reads the current reset_cause
only; cross-run boot history comes from the fleet store's own timestamped
reports (D001), with no device-side changes needed.

Confirmed on real hardware which causes this firmware build exposes:
PWRON_RESET=1, HARD_RESET=2, WDT_RESET=3, DEEPSLEEP_RESET=4, SOFT_RESET=5.
No separate BROWNOUT_RESET constant exists on this build.
"""

from smcheck.checks.reset import check_d_rst


def test_pwron_reset_passes():
    result = check_d_rst(port=None, identity={}, reset_cause_fn=lambda port: (1, "PWRON_RESET"))
    assert result.status == "pass"
    assert "PWRON_RESET" in result.summary


def test_soft_reset_passes():
    # what mpremote itself triggers -- must not look like a fault.
    result = check_d_rst(port=None, identity={}, reset_cause_fn=lambda port: (5, "SOFT_RESET"))
    assert result.status == "pass"


def test_hard_reset_warns():
    result = check_d_rst(port=None, identity={}, reset_cause_fn=lambda port: (2, "HARD_RESET"))
    assert result.status == "warn"
    assert "HARD_RESET" in result.summary


def test_watchdog_reset_warns():
    result = check_d_rst(port=None, identity={}, reset_cause_fn=lambda port: (3, "WDT_RESET"))
    assert result.status == "warn"


def test_deepsleep_reset_warns_since_this_project_never_sleeps():
    result = check_d_rst(port=None, identity={}, reset_cause_fn=lambda port: (4, "DEEPSLEEP_RESET"))
    assert result.status == "warn"


def test_detail_carries_numeric_and_name():
    result = check_d_rst(port=None, identity={}, reset_cause_fn=lambda port: (5, "SOFT_RESET"))
    assert result.detail == {"cause_code": 5, "cause_name": "SOFT_RESET"}
