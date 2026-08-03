"""D008: D-POT and D-BTN -- human-assisted, real-time sampling.

Both need a person moving something while the device streams samples in the
background: sweeping the on-board potentiometer end to end, or pressing each
button. Buttons are active-low, per myfavcolor.py (`if not switch_up.value():
...`), so a sampled value of 0 means pressed.

D-POT's plateau detection is deliberately a warn, not a fail: human sweep
speed varies a lot, and a slow patch at the start or end of an honest sweep
would look identical to a real dead zone in the middle. Treat a warn here as
"worth a second, more careful sweep," not a verdict.
"""

import os
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

DEFAULT_LOW_THRESH = 100
DEFAULT_HIGH_THRESH = 3995
DEFAULT_MIN_DISTINCT = 8
DEFAULT_PLATEAU_FRAC = 0.35
DEFAULT_POT_DURATION_S = 4
DEFAULT_BTN_DURATION_S = 6

_POT_SNIPPET = """
from machine import Pin, ADC
import time
pot = ADC(Pin(3))
pot.atten(ADC.ATTN_11DB)
t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < %d:
    print('POT', pot.read())
    time.sleep_ms(20)
"""

_BTN_SNIPPET = """
from machine import Pin
import time
up = Pin(10, Pin.IN)
down = Pin(8, Pin.IN)
select = Pin(9, Pin.IN)
t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < %d:
    print('BTN', up.value(), down.value(), select.value())
    time.sleep_ms(20)
"""


def _run(port, snippet, timeout):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", snippet]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError("mpremote failed:\n" + (out.stderr or out.stdout))
    return out.stdout


def real_pot_samples(port, duration_s):
    out = _run(port, _POT_SNIPPET % (duration_s * 1000), timeout=duration_s + 15)
    samples = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "POT":
            samples.append(int(parts[1]))
    if not samples:
        raise RuntimeError(f"no pot samples returned:\n{out}")
    return samples


def real_btn_samples(port, duration_s):
    out = _run(port, _BTN_SNIPPET % (duration_s * 1000), timeout=duration_s + 15)
    samples = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "BTN":
            samples.append(tuple(int(p) for p in parts[1:]))
    if not samples:
        raise RuntimeError(f"no button samples returned:\n{out}")
    return samples


def prompt_pot_sweep():
    input(
        "\nGet ready to sweep the on-board potentiometer smoothly from one end "
        "to the other and back, over about 4 seconds. Press Enter to start, "
        "then sweep immediately."
    )


def prompt_button_presses():
    input(
        "\nGet ready to press each of the three buttons (UP, DOWN, SELECT) at "
        "least once over the next 6 seconds. Press Enter to start."
    )


def _longest_plateau_frac(samples, band=4):
    if len(samples) < 2:
        return 0.0
    longest = 1
    current = 1
    for a, b in zip(samples, samples[1:]):
        if abs(a - b) <= band:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest / len(samples)


def check_d_pot(
    port,
    identity,
    sample_fn=None,
    prompt_fn=None,
    low_thresh=DEFAULT_LOW_THRESH,
    high_thresh=DEFAULT_HIGH_THRESH,
    min_distinct=DEFAULT_MIN_DISTINCT,
    plateau_frac_threshold=DEFAULT_PLATEAU_FRAC,
    duration_s=DEFAULT_POT_DURATION_S,
):
    sample_fn = sample_fn or real_pot_samples
    prompt_fn = prompt_fn if prompt_fn is not None else prompt_pot_sweep

    prompt_fn()
    samples = sample_fn(port, duration_s)

    lo, hi = min(samples), max(samples)
    distinct = len(set(samples))
    detail = {"min": lo, "max": hi, "distinct_values": distinct, "n_samples": len(samples)}

    if distinct < min_distinct:
        return CheckResult(
            id="D-POT", status="fail", summary=f"reading barely changed ({distinct} distinct values) -- not responding to movement", detail=detail
        )
    if lo > low_thresh or hi < high_thresh:
        return CheckResult(
            id="D-POT",
            status="fail",
            summary=f"range [{lo}, {hi}] falls short of full travel [0, 4095]",
            detail=detail,
        )

    plateau_frac = _longest_plateau_frac(samples)
    detail["longest_plateau_frac"] = round(plateau_frac, 2)
    if plateau_frac > plateau_frac_threshold:
        return CheckResult(
            id="D-POT",
            status="warn",
            summary=f"long flat stretch during the sweep ({plateau_frac:.0%} of samples) -- possible dead zone, worth a slower re-sweep",
            detail=detail,
        )

    return CheckResult(id="D-POT", status="pass", summary=f"full range covered [{lo}, {hi}]", detail=detail)


def check_d_btn(port, identity, sample_fn=None, prompt_fn=None, duration_s=DEFAULT_BTN_DURATION_S):
    sample_fn = sample_fn or real_btn_samples
    prompt_fn = prompt_fn if prompt_fn is not None else prompt_button_presses

    prompt_fn()
    samples = sample_fn(port, duration_s)

    names = ["up", "down", "select"]
    press_counts = {name: 0 for name in names}
    prev = None
    for sample in samples:
        if prev is not None:
            for i, name in enumerate(names):
                if prev[i] == 1 and sample[i] == 0:
                    press_counts[name] += 1
        prev = sample

    detail = {"press_counts": press_counts, "n_samples": len(samples)}
    never_pressed = [name for name, count in press_counts.items() if count == 0]
    if never_pressed:
        return CheckResult(
            id="D-BTN",
            status="fail",
            summary=f"never detected a press on: {', '.join(never_pressed)}",
            detail=detail,
        )
    return CheckResult(
        id="D-BTN", status="pass", summary=f"all buttons pressed ({press_counts})", detail=detail
    )
