#!/Users/gregorymarton/Documents/GitHub/MyFavoriteColor/.venv/bin/python3
"""
S7 guided hardware test -- HOST side reader.

Parses guided_log.txt (pulled after a guided_test_device.py run) and prints
what was detected per stage, so you can sanity-check it against what you
actually did.

    .venv/bin/mpremote fs cp :guided_log.txt spikes/S7_guided/
    ./spikes/S7_guided/read_guided_log.py spikes/S7_guided/guided_log.txt
"""

import re
import sys


def summarize(path):
    boots = []
    stage_reps = {}
    stage_done = set()
    stage_timeout = set()
    sequence_complete = False
    sustain_samples = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("BOOT "):
                m = re.search(r"boot_num=(\d+) reset_cause=(\d+)\((\w+)\) resume_stage=(\d+)", line)
                if m:
                    boots.append({
                        "boot_num": int(m.group(1)), "reset_cause_name": m.group(3),
                        "resume_stage": int(m.group(4)),
                    })
            elif line.startswith("SUSTAIN_SAMPLE "):
                m = re.search(r"batt_uv=(\d+)", line)
                if m:
                    sustain_samples.append(int(m.group(1)))
            elif line.startswith("REP "):
                m = re.search(r"stage=(\w+)", line)
                if m:
                    stage_reps.setdefault(m.group(1), []).append(line)
            elif line.startswith("STAGE_DONE "):
                m = re.search(r"stage=(\w+)", line)
                if m:
                    stage_done.add(m.group(1))
            elif line.startswith("TIMEOUT "):
                m = re.search(r"stage=(\w+)", line)
                if m:
                    stage_timeout.add(m.group(1))
            elif line.startswith("SEQUENCE_COMPLETE"):
                sequence_complete = True

    print(f"Boots: {len(boots)}")
    for b in boots:
        print(f"  boot #{b['boot_num']}: reset_cause={b['reset_cause_name']}, resuming at stage {b['resume_stage']}")
    if len(boots) > 1:
        unexpected = [
            b for b in boots[1:]
            if not (b["resume_stage"] > 0)  # a resume at stage>0 after OFFON is expected
        ]
        if unexpected:
            print(f"  *** {len(unexpected)} unexpected reset(s) not explained by the OFF/ON stage ***")

    print("\nStage results:")
    for stage in (
        "POT", "SELECT", "UP", "FLIP",
        "DISCONNECT_PROMPT",
        "POT_B", "SELECT_B", "UP_B", "FLIP_B",
        "SUSTAIN",
        "OFFON", "SENSOR",
    ):
        if stage == "SUSTAIN" and sustain_samples:
            status = "DONE" if stage in stage_done else ("TIMEOUT" if stage in stage_timeout else "not reached")
            lo_v, hi_v = min(sustain_samples) / 1e6, max(sustain_samples) / 1e6
            print(f"  {stage:8s} {status:8s} ({len(sustain_samples)} samples, battery {lo_v:.3f}-{hi_v:.3f} V)")
        elif stage in stage_done:
            n_reps = len(stage_reps.get(stage, []))
            print(f"  {stage:8s} DONE   ({n_reps} rep(s) detected)")
        elif stage in stage_timeout:
            n_reps = len(stage_reps.get(stage, []))
            print(f"  {stage:8s} TIMEOUT ({n_reps} rep(s) detected before giving up)")
        else:
            print(f"  {stage:8s} not reached")

    print(f"\nSequence complete: {sequence_complete}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: read_guided_log.py <path to guided_log.txt>")
    summarize(sys.argv[1])
