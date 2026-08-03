"""D010: D-PORT -- sensor port / analog-I2C toggle probe.

What the analog/I2C toggle (`!`) does electrically is still an open question
(HANDOFF.md: "Disconnect the I2C lines from the port, re-route pin 5, change
pull-ups?"). This check deliberately doesn't assert a mechanism -- it proves
the one thing that's testable without knowing the answer: toggling the
switch measurably changes the port's electrical state. It reuses sensors.py's
own selectsensor() technique (drive pin 5 digital low, read back via ADC;
then digital high, read again) to get the raw (low, high) pair, rather than
reinventing a probe.

Classification is by SPREAD (high - low), not sensors.py's own
`low < 200 and high > 4000` formula. A live run against real hardware
(bad-unit-1, 2026-08-03) showed why that formula is unreliable here: the
floating-pin state's `high` reading topped out around 3700-3998, never
crossing sensors.py's 4000 threshold, so reusing that exact formula reports
"attached" for an entire run despite a clear, real regime change (spread
~3670-3970 in one state, spread within +/-660 of zero in the other -- a clean
gap around 2000 with no real data anywhere near it). sensors.py's own
threshold may itself be marginal on real hardware; this check works around
that rather than assuming it's reliable, and isn't proposing sensors.py be
changed (that's a separate, deliberate decision -- see EMULATOR_TASKS.md R1).
"""

import os
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

DEFAULT_DURATION_S = 6

# GUESS: needs bench data across more units. Measured 2026-08-03 on
# bad-unit-1: one state clusters at spread ~3670-3970, the other within +/-660
# of zero -- a wide, clean gap with no real data anywhere near this midpoint.
DEFAULT_SPREAD_THRESHOLD = 2000

_SNIPPET = """
from machine import Pin, ADC
import time

def probe():
    p_digital = Pin(5, Pin.OUT)
    p_digital.value(0)
    p_analog = ADC(Pin(5))
    p_analog.atten(ADC.ATTN_11DB)
    low = p_analog.read()
    p_digital = Pin(5, Pin.OUT)
    p_digital.value(1)
    p_analog = ADC(Pin(5))
    p_analog.atten(ADC.ATTN_11DB)
    high = p_analog.read()
    return low, high

t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < %d:
    low, high = probe()
    print('PORT', low, high)
    time.sleep_ms(150)
"""


def real_port_samples(port, duration_s):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", _SNIPPET % (duration_s * 1000)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_s + 15)
    if out.returncode != 0:
        raise RuntimeError("mpremote failed:\n" + (out.stderr or out.stdout))
    samples = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "PORT":
            samples.append((int(parts[1]), int(parts[2])))
    if not samples:
        raise RuntimeError(f"no port samples returned:\n{out.stdout}")
    return samples


def prompt_toggle():
    input(
        "\nGet ready to flip the analog/I2C toggle switch at least once (either "
        "direction) over the next 6 seconds. Press Enter to start."
    )


def check_d_port(
    port,
    identity,
    sample_fn=None,
    prompt_fn=None,
    duration_s=DEFAULT_DURATION_S,
    spread_threshold=DEFAULT_SPREAD_THRESHOLD,
):
    sample_fn = sample_fn or real_port_samples
    prompt_fn = prompt_fn if prompt_fn is not None else prompt_toggle

    prompt_fn()
    samples = sample_fn(port, duration_s)

    states = [(high - low) > spread_threshold for low, high in samples]
    transitions = sum(1 for a, b in zip(states, states[1:]) if a != b)
    detail = {"transitions": transitions, "final_state": states[-1], "n_samples": len(samples)}

    if transitions == 0:
        return CheckResult(
            id="D-PORT",
            status="fail",
            summary=f"no change in electrical state across {len(samples)} samples -- toggle had no observable effect",
            detail=detail,
        )
    return CheckResult(
        id="D-PORT",
        status="pass",
        summary=f"electrical state changed {transitions} time(s) during the window",
        detail=detail,
    )
