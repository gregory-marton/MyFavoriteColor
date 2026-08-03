"""D006: D-OLED check. Written before smcheck/checks/oled.py exists.

Human-assisted: no scan or register readback can tell you whether a display
actually renders correctly (unit-3 proved that -- it passes D-I2C cleanly
despite a real display defect). Runs a short sequence of patterns rather than
one: a border/crosshair/corners pattern catches geometry and alignment
problems, and a full-white fill exercises every pixel (a border-only pattern
leaves most of the screen untested, per unit-3's own field trial, which
surfaced a static alternating-row defect across the whole screen that a
sparser pattern would have made harder to characterize precisely).

push_pattern_fn(port, name) and confirm_fn(name) are injected so the plumbing
is testable without a real display or a real human.
"""

from smcheck.checks.oled import check_d_oled


def test_passes_when_human_confirms_every_pattern():
    pushed = []
    result = check_d_oled(
        port=None,
        identity={},
        push_pattern_fn=lambda port, name: pushed.append((port, name)),
        confirm_fn=lambda name: (True, ""),
    )
    assert result.status == "pass"
    assert len(pushed) >= 2  # border/crosshair AND full-white, at minimum


def test_fails_on_first_pattern_human_reports_a_problem_with():
    seen = []

    def confirm(name):
        seen.append(name)
        return (False, "alternating rows missing")

    result = check_d_oled(
        port=None, identity={}, push_pattern_fn=lambda port, name: None, confirm_fn=confirm
    )

    assert result.status == "fail"
    assert "alternating rows missing" in result.summary
    assert seen == [seen[0]]  # stops after the first failure, doesn't push every pattern regardless


def test_fails_when_a_pattern_cannot_be_pushed():
    def failing_push(port, name):
        raise RuntimeError("I2C write to 0x3c failed")

    result = check_d_oled(
        port=None, identity={}, push_pattern_fn=failing_push, confirm_fn=lambda name: (True, "")
    )
    assert result.status == "fail"
    assert "0x3c" in result.summary


def test_summary_names_which_pattern_failed():
    def confirm(name):
        if name == "full-white":
            return (False, "dim patch in one corner")
        return (True, "")

    result = check_d_oled(
        port=None, identity={}, push_pattern_fn=lambda port, name: None, confirm_fn=confirm
    )

    assert result.status == "fail"
    assert "full-white" in result.summary
