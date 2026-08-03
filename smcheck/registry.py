"""The check registry that D002-D011 plug into.

Each check is a callable (port, identity) -> CheckResult. Registering here is
the only thing a new D0## task needs to do to show up in `smcheck --quick` /
`--full`.
"""

from smcheck.checks.filesystem import check_d_fs
from smcheck.checks.identity import check_d_fw, check_d_id

QUICK_CHECKS = [check_d_id, check_d_fw, check_d_fs]  # D002, D003. D004-D007, D009 still to come.
FULL_ONLY_CHECKS = []  # populated by D006, D008 (need a human)


def run_checks(checks, port, identity):
    return [check(port, identity) for check in checks]
