"""D001: minimal device identity, enough to key a report before D002 exists.

Not a health check itself -- D002 (D-ID / D-FW) adds the actual pass/warn/fail
verdict. This just gets the unique_id so the fleet store has something to key
reports on. Same subprocess-over-mpremote pattern as
spikes/S5_battery/probe_battery.py.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MPREMOTE = os.path.join(HERE, "..", ".venv", "bin", "mpremote")

IDENTITY_SNIPPET = """
import machine, sys
print('UID', ''.join('%02x' % b for b in machine.unique_id()))
print('IMPL', sys.implementation.version, sys.implementation._machine)
print('FREQ', machine.freq())
"""


def get_identity(port=None, timeout=30):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", IDENTITY_SNIPPET]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(
            "mpremote failed:\n" + (out.stderr or out.stdout)
            + "\nIs the device plugged in and not busy running its main loop?"
        )
    fields = {}
    for line in out.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            fields[parts[0]] = parts[1]
    if "UID" not in fields:
        raise RuntimeError(f"unexpected device output:\n{out.stdout}")
    return {
        "uid": fields["UID"],
        "implementation": fields.get("IMPL", ""),
        "freq": fields.get("FREQ", ""),
    }
