"""D006: D-OLED -- test patterns + human confirm.

No electrical check can tell you whether a display actually renders
correctly. D-I2C (D005) proved that directly: unit-3 passes its bus scan
cleanly despite a real display defect (a static pattern of alternating rows
missing across roughly the top third of the screen -- not time-varying
flicker, confirmed against this check's own border/crosshair pattern). Runs
two patterns in sequence: a border/crosshair/corners pattern for geometry and
alignment, and a full-white fill so every pixel actually gets exercised --
the border pattern alone left most of the screen untested, which is exactly
what a first live run against unit-3 turned up.

Human-assisted (FULL_ONLY_CHECKS), so `smcheck --full` is what runs this, not
`--quick`.
"""

import os
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

_SETUP = """
from machine import Pin, SoftI2C
import ssd1306
i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
d = ssd1306.SSD1306_I2C(128, 64, i2c)
"""

_PATTERN_SNIPPETS = {
    "border-crosshair": _SETUP
    + """
d.fill(0)
d.rect(0, 0, 128, 64, 1)
d.hline(0, 32, 128, 1)
d.vline(64, 0, 64, 1)
d.fill_rect(2, 2, 10, 10, 1)
d.fill_rect(116, 2, 10, 10, 1)
d.fill_rect(2, 52, 10, 10, 1)
d.fill_rect(116, 52, 10, 10, 1)
d.text('D-OLED', 34, 28, 1)
d.show()
print('PUSHED')
""",
    "full-white": _SETUP
    + """
d.fill(1)
d.show()
print('PUSHED')
""",
}

# Order matters: geometry/alignment first, then the full-pixel exercise.
PATTERN_NAMES = ["border-crosshair", "full-white"]

_PROMPTS = {
    "border-crosshair": (
        "You should see: a full border, a horizontal and vertical midline, a "
        "filled square in each corner, and 'D-OLED' centered."
    ),
    "full-white": "The entire screen should be solid white, edge to edge, no dim or dark patches.",
}


def real_push_pattern(port, name):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", _PATTERN_SNIPPETS[name]]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if out.returncode != 0 or "PUSHED" not in out.stdout:
        raise RuntimeError("could not draw to display (0x3c): " + (out.stderr or out.stdout))


def prompt_human(name):
    print(f"\n[{name}] {_PROMPTS[name]}")
    answer = input("Does it look correct? [y/n]: ").strip().lower()
    if answer.startswith("y"):
        return True, ""
    note = input("What's wrong? (brief description): ").strip()
    return False, note


def check_d_oled(port, identity, push_pattern_fn=None, confirm_fn=None, pattern_names=None):
    push_pattern_fn = push_pattern_fn or real_push_pattern
    confirm_fn = confirm_fn or prompt_human
    pattern_names = pattern_names if pattern_names is not None else PATTERN_NAMES

    for name in pattern_names:
        try:
            push_pattern_fn(port, name)
        except Exception as e:
            return CheckResult(id="D-OLED", status="fail", summary=f"[{name}] {e}")

        ok, note = confirm_fn(name)
        if not ok:
            return CheckResult(
                id="D-OLED", status="fail", summary=f"[{name}] {note or 'human reported a display problem'}"
            )

    return CheckResult(id="D-OLED", status="pass", summary=f"human confirmed all patterns ({', '.join(pattern_names)})")
