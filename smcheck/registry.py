"""The check registry that D002-D011 plug into.

Each check is a callable (port, identity) -> CheckResult. Registering here is
the only thing a new D0## task needs to do to show up in `smcheck --quick` /
`--full`.
"""

from smcheck.checks.filesystem import check_d_fs
from smcheck.checks.i2c import check_d_i2c
from smcheck.checks.identity import check_d_fw, check_d_id
from smcheck.checks.oled import check_d_oled
from smcheck.checks.reset import check_d_rst

QUICK_CHECKS = [check_d_id, check_d_fw, check_d_fs, check_d_rst, check_d_i2c]  # D002-D005. D007, D009 still to come.
FULL_ONLY_CHECKS = [check_d_oled]  # D006. D008 (D-POT/D-BTN) still to come.


def run_checks(checks, port, identity):
    return [check(port, identity) for check in checks]
