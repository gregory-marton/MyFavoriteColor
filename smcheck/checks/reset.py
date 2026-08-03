"""D004: D-RST -- reset cause.

Deliberately scoped down from a persisted boot counter (see the test file's
docstring): that would need boot.py changes pushed to every board, which is a
fleet-wide firmware decision, not something to do silently from a health
check. Cross-run history instead comes from the fleet store itself (D001) --
each smcheck run's reset_cause becomes one more data point in that unit's
timestamped history.

PWRON_RESET and SOFT_RESET are expected (power-on, and what mpremote itself
triggers). HARD_RESET, WDT_RESET, and DEEPSLEEP_RESET are all "warn" -- this
project's activities never deep-sleep, so seeing DEEPSLEEP_RESET is as
suspicious as a watchdog firing. None of these are hard failures on their own;
a single reset is not proof of a problem, just something worth watching across
repeated runs.
"""

import os
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

# Confirmed on real hardware 2026-08-03 (ESP32_GENERIC_C3, MicroPython 1.25.0).
# No separate BROWNOUT_RESET constant on this build -- a brownout surfaces as
# one of these instead, most likely HARD_RESET.
BENIGN_CAUSES = {"PWRON_RESET", "SOFT_RESET"}

_SNIPPET = """
import machine
cause = machine.reset_cause()
names = {getattr(machine, n): n for n in dir(machine) if n.endswith('_RESET')}
print('CAUSE', cause, names.get(cause, 'UNKNOWN'))
"""


def real_reset_cause(port):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", _SNIPPET]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise RuntimeError("mpremote failed:\n" + (out.stderr or out.stdout))
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "CAUSE":
            return int(parts[1]), parts[2]
    raise RuntimeError(f"unexpected reset_cause output:\n{out.stdout}")


def check_d_rst(port, identity, reset_cause_fn=None):
    reset_cause_fn = reset_cause_fn or real_reset_cause
    cause_code, cause_name = reset_cause_fn(port)

    detail = {"cause_code": cause_code, "cause_name": cause_name}
    if cause_name in BENIGN_CAUSES:
        return CheckResult(id="D-RST", status="pass", summary=f"last reset: {cause_name}", detail=detail)
    return CheckResult(
        id="D-RST",
        status="warn",
        summary=f"last reset: {cause_name} -- watch for repeats across runs",
        detail=detail,
    )
