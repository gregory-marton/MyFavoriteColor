#!/Users/gregorymarton/Documents/GitHub/MyFavoriteColor/.venv/bin/python3
"""
S6 power-combination trial -- one run of the DEVICE_HEALTH_DESIGN.md section 4
truth table (does the colour activity need USB and battery simultaneously?).

One invocation = one trial in one power configuration. Run it once per row of
the truth table; results append to power_trials.csv.

    ./spikes/S6_power/power_trial.py --config usb-plus-battery-full --port /dev/cu.usbmodem1101
    ./spikes/S6_power/power_trial.py --config battery-only-full --no-port

Two modes:
  --port <path>   USB is connected for this trial. Queries machine.reset_cause()
                   before and after the observation window, so an unexpected
                   reset is caught even if the human doesn't notice it.
  --no-port       USB is NOT connected for this trial (a battery-only
                   configuration). There is no serial link to instrument in
                   this case -- the native USB Serial/JTAG peripheral requires
                   the physical USB connection to exist at all -- so the
                   result is purely the human's own observation.

This is a THROWAWAY EXPERIMENT tool, same spirit as S4/S5. It does not modify
any device code and writes nothing to flash.
"""

import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(HERE, "power_trials.csv")
MPREMOTE = os.path.join(HERE, "..", "..", ".venv", "bin", "mpremote")

_RESET_SNIPPET = """
import machine
cause = machine.reset_cause()
names = {getattr(machine, n): n for n in dir(machine) if n.endswith('_RESET')}
print('CAUSE', cause, names.get(cause, 'UNKNOWN'))
"""


def query_reset_cause(port):
    cmd = [MPREMOTE, "connect", port, "exec", _RESET_SNIPPET]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        return None, f"could not query device: {out.stderr or out.stdout}".strip()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "CAUSE":
            return (int(parts[1]), parts[2]), None
    return None, f"unexpected output:\n{out.stdout}"


def main():
    ap = argparse.ArgumentParser(description="One power-configuration trial for the D-PWR truth table")
    ap.add_argument("--config", required=True, help="e.g. 'usb-plus-battery-full', 'battery-only-low'")
    ap.add_argument("--port", default=None, help="serial port, if USB is connected for this trial")
    ap.add_argument("--no-port", action="store_true", help="USB is NOT connected for this trial")
    ap.add_argument("--duration", type=int, default=30, help="seconds to observe the activity")
    args = ap.parse_args()

    if not args.port and not args.no_port:
        sys.exit("Specify --port <path> (USB connected) or --no-port (USB not connected) for this trial.")

    before_cause = before_err = None
    if args.port:
        before_cause, before_err = query_reset_cause(args.port)
        if before_err:
            print(f"(before) {before_err}")
        else:
            print(f"(before) reset_cause: {before_cause[1]}")

    input(
        f"\nSet up power configuration '{args.config}' now if you haven't "
        f"already, then start the colour activity. Press Enter once it's "
        f"running -- you'll then have {args.duration}s to watch it."
    )

    print(f"Watching for {args.duration}s. Note anything unusual (freeze, restart, dim screen, "
          f"servo stall) as it happens.")
    try:
        import time
        time.sleep(args.duration)
    except KeyboardInterrupt:
        pass

    completed = input("\nDid the activity run for that whole time without resetting or glitching? [y/n]: ").strip().lower()
    notes = input("Notes (anything you saw, or blank): ").strip()

    after_cause = after_err = None
    unexpected_reset = None
    if args.port:
        after_cause, after_err = query_reset_cause(args.port)
        if after_err:
            print(f"(after) {after_err}")
        elif before_cause and after_cause[0] != before_cause[0]:
            # SOFT_RESET before is expected (this script's own mpremote calls);
            # anything appearing fresh in the "after" read that wasn't already
            # true "before" is the signal -- most notably a fresh HARD_RESET,
            # WDT_RESET, or PWRON_RESET showing up where it wasn't before.
            unexpected_reset = after_cause[1]
            print(f"(after) reset_cause changed: {before_cause[1]} -> {after_cause[1]}")
        else:
            print(f"(after) reset_cause: {after_cause[1]} (unchanged)")

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": args.config,
        "usb_connected": bool(args.port),
        "duration_s": args.duration,
        "before_reset_cause": before_cause[1] if before_cause else "",
        "after_reset_cause": after_cause[1] if after_cause else "",
        "unexpected_reset": unexpected_reset or "",
        "human_reported_ok": completed.startswith("y"),
        "notes": notes,
    }
    exists = os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if not exists:
            w.writeheader()
        w.writerow(row)

    verdict = "OK" if row["human_reported_ok"] and not unexpected_reset else "PROBLEM"
    print(f"\n[{verdict}] recorded to {os.path.relpath(RESULTS_CSV)}")


if __name__ == "__main__":
    main()
