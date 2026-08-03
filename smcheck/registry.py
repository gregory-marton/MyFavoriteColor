"""D001: the check registry that D002-D011 plug into.

Each check is a callable (port, identity) -> CheckResult. Registering here is
the only thing a new D0## task needs to do to show up in `smcheck --quick` /
`--full`. Empty for now -- D002 adds the first entries (D-ID, D-FW).
"""

QUICK_CHECKS = []  # populated by D002-D007, D009 (fully automated)
FULL_ONLY_CHECKS = []  # populated by D006, D008 (need a human)


def run_checks(checks, port, identity):
    return [check(port, identity) for check in checks]
