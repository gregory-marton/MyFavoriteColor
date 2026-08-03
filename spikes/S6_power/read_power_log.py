#!/Users/gregorymarton/Documents/GitHub/MyFavoriteColor/.venv/bin/python3
"""
S6 power-trial flight recorder -- HOST side reader.

Parses power_log.txt (pulled from the device after a power_log_device.py
trial), summarizes what happened, and asks the person to confirm it matches
what they actually did and observed -- a sanity check against the log rather
than blind trust in it.

    .venv/bin/mpremote fs cp :power_log.txt spikes/S6_power/
    ./spikes/S6_power/read_power_log.py spikes/S6_power/power_log.txt --config battery-only-full
"""

import argparse
import csv
import os
import re
import statistics
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(HERE, "power_trials.csv")


def parse_log(path):
    boots, samples, sweep_points = [], [], []
    sweep_start = sweep_end = None
    notes, errors = [], []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("BOOT "):
                m = re.search(r"boot_num=(\d+) reset_cause=(\d+)\((\w+)\) uid=(\w+)", line)
                if m:
                    boots.append({
                        "boot_num": int(m.group(1)),
                        "reset_cause": int(m.group(2)),
                        "reset_cause_name": m.group(3),
                        "uid": m.group(4),
                    })
            elif line.startswith("S "):
                m = re.search(
                    r"n=(\d+) t=(\d+) pot=(\d+) batt_raw=(\d+) batt_uv=(\d+) btn=(\d),(\d),(\d) "
                    r"accel=([\-\d]+|None),([\-\d]+|None),([\-\d]+|None)",
                    line,
                )
                if m:
                    samples.append({
                        "n": int(m.group(1)), "t": int(m.group(2)), "pot": int(m.group(3)),
                        "batt_raw": int(m.group(4)), "batt_uv": int(m.group(5)),
                        "btn": (int(m.group(6)), int(m.group(7)), int(m.group(8))),
                        "accel": None if m.group(9) == "None" else
                                 (int(m.group(9)), int(m.group(10)), int(m.group(11))),
                    })
            elif line.startswith("SWEEP_START "):
                m = re.search(r"rest_batt_raw=(\d+) rest_batt_uv=(\d+)", line)
                if m:
                    sweep_start = {"batt_raw": int(m.group(1)), "batt_uv": int(m.group(2))}
            elif line.startswith("SWEEP_POINT "):
                m = re.search(r"angle=(\d+) batt_raw=(\d+) batt_uv=(\d+)", line)
                if m:
                    sweep_points.append({
                        "angle": int(m.group(1)), "batt_raw": int(m.group(2)), "batt_uv": int(m.group(3))
                    })
            elif line.startswith("SWEEP_END "):
                m = re.search(r"rest_batt_raw=(\d+) rest_batt_uv=(\d+)", line)
                if m:
                    sweep_end = {"batt_raw": int(m.group(1)), "batt_uv": int(m.group(2))}
            elif line.startswith("NOTE "):
                notes.append(line[len("NOTE "):])
            elif line.startswith("ERROR "):
                errors.append(line[len("ERROR "):])

    return {
        "boots": boots, "samples": samples, "sweep_start": sweep_start,
        "sweep_end": sweep_end, "sweep_points": sweep_points, "notes": notes, "errors": errors,
    }


def summarize(parsed):
    lines = []
    boots = parsed["boots"]
    lines.append(f"Boots recorded: {len(boots)}")
    for b in boots:
        lines.append(f"  boot #{b['boot_num']}: reset_cause={b['reset_cause_name']}")
    if len(boots) > 1:
        unexpected = [b for b in boots[1:] if b["reset_cause_name"] not in ("PWRON_RESET",)]
        lines.append(
            f"  *** {len(boots) - 1} reset(s) occurred DURING the trial "
            f"(the device rebooted mid-session) ***"
        )
        if unexpected:
            lines.append(f"      including {len(unexpected)} non-power-on cause(s) -- worth a closer look")

    samples = parsed["samples"]
    if samples:
        pots = [s["pot"] for s in samples]
        lines.append(f"Samples logged: {len(samples)}  (pot range [{min(pots)}, {max(pots)}])")

        any_button = any(any(b == 0 for b in s["btn"]) for s in samples)
        lines.append(f"Any button press detected: {any_button}")

        accels = [s["accel"] for s in samples if s["accel"] is not None]
        if accels:
            mags = [(x * x + y * y + z * z) ** 0.5 for x, y, z in accels]
            spread = max(mags) - min(mags)
            lines.append(
                f"Accelerometer magnitude spread: {spread:.0f} "
                f"({'movement detected' if spread > 30 else 'looks mostly still'})"
            )

        battery_uvs = [s["batt_uv"] for s in samples]
        lines.append(f"Battery (passive, uV): min {min(battery_uvs)}, max {max(battery_uvs)}")

    if parsed["sweep_start"] and parsed["sweep_end"] and parsed["sweep_points"]:
        rest_uv = parsed["sweep_start"]["batt_uv"]
        loaded_uvs = [p["batt_uv"] for p in parsed["sweep_points"]]
        min_loaded = min(loaded_uvs)
        sag_uv = rest_uv - min_loaded
        recovered_uv = parsed["sweep_end"]["batt_uv"]
        lines.append(
            f"Servo load-step: rest {rest_uv/1e6:.3f} V -> min under load {min_loaded/1e6:.3f} V "
            f"(sag {sag_uv/1e6:.3f} V) -> recovered to {recovered_uv/1e6:.3f} V"
        )

    if parsed["notes"]:
        lines.append("Device notes: " + "; ".join(parsed["notes"]))
    if parsed["errors"]:
        lines.append("Device errors: " + "; ".join(parsed["errors"]))

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Summarize an S6 power_log.txt and confirm it with the human")
    ap.add_argument("log_path")
    ap.add_argument("--config", default="", help="label for this trial, e.g. 'battery-only-full'")
    args = ap.parse_args()

    parsed = parse_log(args.log_path)
    summary = summarize(parsed)
    print("\n" + summary + "\n")

    confirm = input(
        "Does this match what you actually did and observed during the trial? [y/n]: "
    ).strip().lower()
    notes = input("Anything to add (what you saw that isn't captured above, or blank): ").strip()

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": args.config,
        "log_path": args.log_path,
        "boots": len(parsed["boots"]),
        "unexpected_resets": max(0, len(parsed["boots"]) - 1),
        "human_confirmed_match": confirm.startswith("y"),
        "notes": notes,
    }
    exists = os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if not exists:
            w.writeheader()
        w.writerow(row)
    print(f"\nRecorded to {os.path.relpath(RESULTS_CSV)}")


if __name__ == "__main__":
    main()
