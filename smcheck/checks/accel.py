"""D007: D-ACC -- gravity-magnitude invariant.

The cheapest strong check available: gravity's magnitude is ~1g in ANY
orientation, so this needs no known orientation and no human cooperation,
unlike D-POT/D-BTN. Two independent failure modes:

  - magnitude far from 1g -> a miscalibrated or damaged sensor.
  - zero variance across samples -> a stuck read reporting a plausible-
    looking constant forever (a bus fault or a halted sensor), which a
    magnitude check alone would not catch.

Confirmed on real hardware (unit-3, ADXL345 default +/-2g 10-bit range):
resting magnitude ~254 LSB, matching the datasheet's ~256 LSB/g. Tolerance is
wide (+/-20%) because this default is a nominal datasheet value, not a
per-unit factory calibration -- see DEVICE_HEALTH_DESIGN.md section 7 for the
open question on per-chip variation.
"""

import os
import statistics
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

# GUESS: needs bench data across more units. Measured 2026-08-03 on unit-3
# (~254 LSB at rest), matching the ADXL345 datasheet's nominal ~256 LSB/g at
# its default +/-2g, 10-bit-resolution power-on configuration.
DEFAULT_EXPECTED_MAGNITUDE = 256
DEFAULT_TOLERANCE_FRAC = 0.20
DEFAULT_N_SAMPLES = 10

_SNIPPET = """
from machine import Pin, SoftI2C
import adxl345, time
i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
a = adxl345.ADXL345(i2c)
for _ in range(%d):
    print('XYZ', a.xValue, a.yValue, a.zValue)
    time.sleep_ms(50)
"""


def real_read_samples(port, n):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", _SNIPPET % n]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise RuntimeError("mpremote failed:\n" + (out.stderr or out.stdout))
    samples = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "XYZ":
            samples.append(tuple(int(p) for p in parts[1:]))
    if not samples:
        raise RuntimeError(f"no accelerometer samples returned:\n{out.stdout}")
    return samples


def check_d_acc(
    port,
    identity,
    read_samples_fn=None,
    expected_magnitude=DEFAULT_EXPECTED_MAGNITUDE,
    tolerance_frac=DEFAULT_TOLERANCE_FRAC,
    n_samples=DEFAULT_N_SAMPLES,
):
    read_samples_fn = read_samples_fn or real_read_samples
    samples = read_samples_fn(port, n_samples)

    magnitudes = [(x * x + y * y + z * z) ** 0.5 for x, y, z in samples]
    median_magnitude = statistics.median(magnitudes)
    detail = {"n_samples": len(samples), "median_magnitude": round(median_magnitude, 1)}

    if len(set(samples)) == 1 and len(samples) > 1:
        return CheckResult(
            id="D-ACC",
            status="fail",
            summary=f"reading stuck at a constant value across {len(samples)} samples: {samples[0]}",
            detail=detail,
        )

    low = expected_magnitude * (1 - tolerance_frac)
    high = expected_magnitude * (1 + tolerance_frac)
    if not (low <= median_magnitude <= high):
        return CheckResult(
            id="D-ACC",
            status="fail",
            summary=f"magnitude {median_magnitude:.1f} outside expected 1g range [{low:.0f}, {high:.0f}]",
            detail=detail,
        )

    return CheckResult(id="D-ACC", status="pass", summary=f"magnitude {median_magnitude:.1f} ~= 1g", detail=detail)
