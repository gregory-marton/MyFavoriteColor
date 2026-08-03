"""D005: D-I2C -- bus scan and stuck-line detection.

Same bus setup as sensors.py: SoftI2C(scl=Pin(7), sda=Pin(6)). OLED at 0x3C
is a hard requirement -- its absence means the display is definitely broken.
ADXL345 at 0x53 is only a warn: HANDOFF.md still lists "is the ADXL345 fitted
on every board?" as an open question, and sensors.py itself tolerates its
absence (wraps the constructor in try/except OSError). Any other address
found (e.g. a color sensor at 0x10) is informative, not a fault, so it's a
warn rather than a fail. A scan that raises at all (rather than returning a
list) means the bus itself is wedged -- SDA or SCL stuck low -- which is a
hard fail distinct from a clean scan that's simply missing an address.
"""

import os
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

OLED_ADDR = 0x3C
ACCEL_ADDR = 0x53
EXPECTED = {OLED_ADDR, ACCEL_ADDR}

_SNIPPET = """
from machine import Pin, SoftI2C
i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
print('SCAN', i2c.scan())
"""


def real_scan(port):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", _SNIPPET]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise RuntimeError("bus scan failed (possibly stuck): " + (out.stderr or out.stdout))
    for line in out.stdout.splitlines():
        if line.startswith("SCAN"):
            raw = line[len("SCAN "):].strip().strip("[]")
            return [int(x) for x in raw.split(",") if x.strip()]
    raise RuntimeError(f"unexpected scan output:\n{out.stdout}")


def check_d_i2c(port, identity, scan_fn=None):
    scan_fn = scan_fn or real_scan

    try:
        found = scan_fn(port)
    except Exception as e:
        return CheckResult(id="D-I2C", status="fail", summary=f"bus scan failed, possibly stuck: {e}")

    found_set = set(found)
    missing = sorted(EXPECTED - found_set)
    unexpected = sorted(found_set - EXPECTED)
    detail = {"found": list(found), "missing": missing, "unexpected": unexpected}

    if OLED_ADDR in missing:
        return CheckResult(
            id="D-I2C", status="fail", summary=f"OLED (0x3c) not found on bus; found {found}", detail=detail
        )
    if ACCEL_ADDR in missing:
        return CheckResult(
            id="D-I2C",
            status="warn",
            summary=f"ADXL345 (0x53) not found -- may not be fitted on this board; found {found}",
            detail=detail,
        )
    if unexpected:
        return CheckResult(
            id="D-I2C",
            status="warn",
            summary=f"unexpected address(es) on bus: {[hex(a) for a in unexpected]}",
            detail=detail,
        )
    return CheckResult(id="D-I2C", status="pass", summary=f"OLED and ADXL345 both present: {found}", detail=detail)
