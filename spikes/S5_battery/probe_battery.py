#!/Users/gregorymarton/Documents/GitHub/MyFavoriteColor/.venv/bin/python3
"""
S5 battery probe -- one unit, ~10 seconds, no bench equipment.

Answers the decisive question behind "charges overnight and still shows low":
is the BATTERY weak, or is the ADC CALIBRATION making a healthy battery look
weak? (DEVICE_HEALTH_DESIGN.md section 2, defect 5.)

The discriminator is that read_uv() applies each chip's eFuse calibration and
read() does not. So for a unit that misreports after a full charge:

  raw < 2700 BUT read_uv ~= 2.05 V  ->  battery is fine, the THRESHOLDS are
                                        wrong for this chip. Software fix.
  raw < 2700 AND read_uv well below ->  battery genuinely will not hold charge.
                                        Replace the cell.

Run it on the known-good unit first to establish the reference, then on each
suspect unit. Results append to fleet.csv, keyed by unique_id -- the seed of
the fleet store in task D001.

    ./spikes/S5_battery/probe_battery.py --label good-unit
    ./spikes/S5_battery/probe_battery.py --label suspect-1

Read-only: reads ADC and machine identity. Writes nothing to the device.
"""

import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET_CSV = os.path.join(HERE, "fleet.csv")
MPREMOTE = os.path.join(HERE, "..", "..", ".venv", "bin", "mpremote")

# Assumed resistor divider between the cell and ADC Pin 4.
# GUESS: needs bench data -- inferred from 2.084 V at the pin on a
# known-good, fully-charged unit (2.084 * 2 = 4.17 V, a healthy 1S LiPo).
# Task B001 replaces this with a multimeter measurement.
DIVIDER_RATIO = 2.0

# Thresholds as sensors.readbattery() applies them today, in RAW COUNTS.
THRESHOLDS = [(2850, "charging"), (2700, "full"), (2500, "half")]

DEVICE_SNIPPET = """
import machine, time
from machine import Pin, ADC
a = ADC(Pin(4)); a.atten(ADC.ATTN_11DB)
raw = [a.read() for _ in range(200)]
uv = [a.read_uv() for _ in range(200)]
raw.sort(); uv.sort()
print('UID', ''.join('%02x' % b for b in machine.unique_id()))
print('RAW_MED', raw[len(raw)//2], 'RAW_MIN', raw[0], 'RAW_MAX', raw[-1])
print('UV_MED', uv[len(uv)//2], 'UV_MIN', uv[0], 'UV_MAX', uv[-1])
"""


def classify(raw):
    """Reproduce sensors.readbattery()'s verdict, including its gaps."""
    if raw > 2850:
        return "charging"
    elif raw > 2700 and raw < 2875:
        return "full"
    elif raw > 2500 and raw < 2700:
        return "half"
    elif raw < 2500:
        return "low"
    return ""  # the boundary gap: exactly 2500 or exactly 2700


def probe(port=None):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", DEVICE_SNIPPET]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        sys.exit(
            "mpremote failed:\n" + (out.stderr or out.stdout)
            + "\nIs the device plugged in and not busy running its main loop?"
        )
    fields = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "UID":
            fields["uid"] = parts[1]
        elif parts and parts[0] in ("RAW_MED", "UV_MED"):
            for i in range(0, len(parts), 2):
                fields[parts[i].lower()] = int(parts[i + 1])
    missing = {"uid", "raw_med", "uv_med"} - set(fields)
    if missing:
        sys.exit(f"unexpected device output (missing {missing}):\n{out.stdout}")
    return fields


def main():
    ap = argparse.ArgumentParser(description="SmartMotor battery probe")
    ap.add_argument("--label", required=True, help="e.g. 'good-unit', 'suspect-1'")
    ap.add_argument("--port", default=None)
    ap.add_argument("--state", default="unknown",
                    help="usb / battery / just-charged -- context for the reading")
    args = ap.parse_args()

    f = probe(args.port)
    pin_v = f["uv_med"] / 1e6
    cell_v = pin_v * DIVIDER_RATIO
    verdict = classify(f["raw_med"])

    print(f"\nUnit {args.label}  (uid {f['uid']})")
    print(f"  raw ADC        {f['raw_med']}  (spread {f['raw_min']}-{f['raw_max']})")
    print(f"  calibrated     {pin_v:.3f} V at pin  ->  ~{cell_v:.2f} V at cell"
          f"   [divider {DIVIDER_RATIO}, UNCONFIRMED]")
    print(f"  device says    '{verdict}'" + ("   <-- note: empty, the threshold gap"
                                             if verdict == "" else ""))

    # The discriminator.
    if f["raw_med"] < 2700 and pin_v > 2.0:
        print("\n  >> DISAGREEMENT: raw counts say low/half, calibrated volts say")
        print("     the cell is near full. Consistent with defect 5 -- this chip's")
        print("     ADC reads low and the raw thresholds misjudge it.")
        print("     A software fix (B002) would likely recover this unit.")
    elif f["raw_med"] < 2700:
        print("\n  >> Raw and calibrated AGREE the cell is low. If this unit was")
        print("     just fully charged, that points at the battery itself.")

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": args.label,
        "uid": f["uid"],
        "state": args.state,
        "raw_med": f["raw_med"],
        "raw_min": f["raw_min"],
        "raw_max": f["raw_max"],
        "uv_med": f["uv_med"],
        "pin_v": round(pin_v, 4),
        "cell_v_est": round(cell_v, 3),
        "device_verdict": verdict,
    }
    exists = os.path.exists(FLEET_CSV)
    with open(FLEET_CSV, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if not exists:
            w.writeheader()
        w.writerow(row)
    print(f"\n  appended to {os.path.relpath(FLEET_CSV)}")


if __name__ == "__main__":
    main()
