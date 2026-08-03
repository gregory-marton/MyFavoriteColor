"""The check registry that D002-D011 plug into.

Each check is a callable (port, identity) -> CheckResult. Registering here is
the only thing a new D0## task needs to do to show up in `smcheck --quick` /
`--full`.
"""

from smcheck.checks.accel import check_d_acc
from smcheck.checks.filesystem import check_d_fs
from smcheck.checks.i2c import check_d_i2c
from smcheck.checks.identity import check_d_fw, check_d_id
from smcheck.checks.oled import check_d_oled
from smcheck.checks.pot_btn import check_d_btn, check_d_pot
from smcheck.checks.reset import check_d_rst
from smcheck.report import CheckResult

QUICK_CHECKS = [check_d_id, check_d_fw, check_d_fs, check_d_rst, check_d_i2c, check_d_acc]  # D002-D005, D007. D009 to come.
FULL_ONLY_CHECKS = [check_d_oled, check_d_pot, check_d_btn]  # D006, D008.


def run_checks(checks, port, identity):
    """One flaky check (a timed-out mpremote call, a device hiccup) must not
    abort the whole batch -- that's what makes `smcheck --full` safe to run
    unattended across a class set."""
    results = []
    for check in checks:
        try:
            results.append(check(port, identity))
        except Exception as e:
            results.append(CheckResult(id=check.__name__, status="fail", summary=f"check raised: {e}"))
    return results
