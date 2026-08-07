#!/Users/gregorymarton/Documents/GitHub/MyFavoriteColor/.venv/bin/python3
"""Fleet manager for healthcheck.py -- the host side of the on-device health
check. Watches serial ports for a class set of SmartMotors, remote-starts
units that weren't hand-saluted, and retrieves/stores/clears recordings as
they finish, taking free-text notes per run.

NOT part of EngAI_MANIFEST.txt -- host-only, same convention as
spikes/S5_battery/probe_battery.py and smcheck/.

Polling is non-invasive: `mpremote connect list` just enumerates OS-level
serial devices, no interrupt. Only a *newly-appeared* port gets the
interrupting exec/fs sequence (mpremote always stops whatever's running on
the board first) -- this matters because healthcheck.py's WAIT_RETRIEVAL
screen is meant to keep running and logging until retrieval actually
happens; polling it every tick would otherwise kill it prematurely. A port
that disappears (unplugged) and reappears (the OFFON power cycle, or
retrieval itself) is "newly-appeared" again the next time it's seen.

    ./healthcheck_host.py watch                 # run continuously -- remote-starts
                                                 # fresh units automatically, no
                                                 # three-finger salute needed
    ./healthcheck_host.py watch --no-auto-start # only retrieve/resume; never
                                                 # start a unit that wasn't
                                                 # hand-saluted

Co-authored-by: Claude Sonnet 5, Aug 2026
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

from smcheck.device import get_identity

HERE = os.path.dirname(os.path.abspath(__file__))
MPREMOTE = os.path.join(HERE, ".venv", "bin", "mpremote")
DEFAULT_RECORDINGS_ROOT = os.path.join(HERE, "recordings")

STATE_FILENAME = "healthcheck_state.txt"
LOG_FILENAME = "healthcheck_log.txt"

# Must match len(healthcheck.STAGES) -- the sentinel a fresh run's stage
# index reaches once healthcheck.py's OFFON stage writes its marker.
NUM_STAGES = 14

STAGE_ORDER = (
    "DISCONNECT_PROMPT",
    "POT", "SELECT", "UP", "DOWN", "FLIP",
    "ACCEL_FLAT1", "ACCEL_FIG8", "ACCEL_FLAT2",
    "LIGHT_DARK", "LIGHT_BRIGHT", "COLOR_WHITE",
    "SUSTAIN",
    "OFFON",
)


# ---------------------------------------------------------------------------
# Pure logic -- no subprocess, fully unit-tested.
# ---------------------------------------------------------------------------

def parse_port_list(text):
    """`mpremote connect list` output -> ordered list of port device paths
    (first whitespace-separated token per non-blank line)."""
    ports = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        ports.append(line.split()[0])
    return ports


def classify_new_ports(known, current):
    """Ports in `current` not in `known`, in `current`'s order."""
    return [p for p in current if p not in known]


# Matches how an ESP32-C3 dev board's native USB-CDC actually enumerates
# across platforms (macOS: usbmodem*, Linux: ttyACM*, common USB-serial
# bridges: usbserial*/wchusbserial*/ttyUSB*, Windows: COM<n>). Anything else
# -- notably macOS's always-present /dev/cu.Bluetooth-Incoming-Port virtual
# serial device -- is never a SmartMotor and must not be probed as one.
_CANDIDATE_PORT_RE = re.compile(r"(usbmodem|usbserial|wchusbserial|ttyACM|ttyUSB|COM\d)", re.IGNORECASE)


def filter_candidate_ports(ports):
    return [p for p in ports if _CANDIDATE_PORT_RE.search(p)]


def parse_marker_text(text):
    """Same format healthcheck.py's _read_state()/_write_state() use:
    '<stage_idx>|<rest_uv>|<loaded_p10_uv>', missing/"None" -> None."""
    parts = text.strip().split("|")
    stage_idx = int(parts[0])
    rest_uv = int(parts[1]) if len(parts) > 1 and parts[1] != "None" else None
    loaded_p10_uv = int(parts[2]) if len(parts) > 2 and parts[2] != "None" else None
    return stage_idx, rest_uv, loaded_p10_uv


def decide_action(marker_text, log_exists=False, num_stages=NUM_STAGES):
    """What to do with a newly-appeared port, given its healthcheck_state.txt
    contents (None if missing) and whether healthcheck_log.txt exists.

    - No marker, no log -> "start": a fresh, never-touched unit.
    - No marker, log exists -> "retrieve": the common case now. A field run
      (three-finger salute, no laptop) shows its verdict briefly, clears
      its own marker, and returns to normal operation on its own -- see
      healthcheck.py's show_verdict_and_finish(). The log is what's left
      waiting to be picked up, whenever that turns out to be.
    - Marker present, stage_idx hasn't reached the OFFON sentinel ->
      "resume": our own probe just interrupted an in-progress run (mpremote
      always stops whatever's running); the safest recovery is to reset and
      let healthcheck.py's own _read_state() pick up where it left off.
    - Marker present, stage_idx >= num_stages -> "retrieve": a rare race
      where a host was already connected right as the device resumed after
      OFFON, before its own internal reset had a chance to clear the
      marker. Handled the same as the field case.
    - Unparseable marker -> "resume", for the same reason as a corrupt read
      on-device: don't guess, just let the device's defensive fallback
      (stage 0) sort it out.
    """
    if marker_text is None:
        return "retrieve" if log_exists else "start"
    try:
        stage_idx, _rest_uv, _loaded_p10_uv = parse_marker_text(marker_text)
    except (ValueError, IndexError):
        return "resume"
    return "retrieve" if stage_idx >= num_stages else "resume"


def parse_verdict_line(log_text):
    """Pulls the "VERDICT {...}" line healthcheck.py logs right after
    computing it -- the exact verdict the device itself displayed, not a
    host-side recomputation. ast.literal_eval is safe here: the line is a
    Python dict repr of str/int/float/bool/None values, nothing else."""
    for line in log_text.splitlines():
        if line.startswith("VERDICT "):
            try:
                return ast.literal_eval(line[len("VERDICT "):])
            except (ValueError, SyntaxError):
                return None
    return None


def build_recording_meta(identity, notes, verdict, timestamp, source_log):
    return {
        "uid": identity.get("uid"),
        "implementation": identity.get("implementation", ""),
        "freq": identity.get("freq", ""),
        "timestamp": timestamp,
        "notes": notes,
        "verdict": verdict,
        "source_log": source_log,
    }


def summarize_log(text):
    """Per-stage rollup of a retrieved healthcheck_log.txt -- boots, reps,
    timeouts, done stages. Ported from the old
    spikes/S7_guided/read_guided_log.py, adapted to the new stage list and
    returning data instead of printing."""
    boots = []
    stage_reps = {}
    button_mismatches = []
    stage_done = set()
    stage_timeout = set()
    sequence_complete = False

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("BOOT "):
            m = re.search(r"boot_num=(\d+) reset_cause=(\d+)\((\w+)\) resume_stage=(\d+)", line)
            if m:
                boots.append({
                    "boot_num": int(m.group(1)), "reset_cause_name": m.group(3),
                    "resume_stage": int(m.group(4)),
                })
        elif line.startswith("REP "):
            m = re.search(r"stage=(\w+)", line)
            if m:
                stage_reps.setdefault(m.group(1), []).append(line)
        elif line.startswith("BUTTON_MISMATCH "):
            button_mismatches.append(line)
        elif line.startswith("STAGE_DONE "):
            m = re.search(r"stage=(\w+)", line)
            if m:
                stage_done.add(m.group(1))
        elif line.startswith("TIMEOUT "):
            m = re.search(r"stage=(\w+)", line)
            if m:
                stage_timeout.add(m.group(1))
        elif line.startswith("SEQUENCE_COMPLETE") or line.startswith("WAITING_FOR_REBOOT"):
            sequence_complete = True

    return {
        "boots": boots,
        "stage_reps": stage_reps,
        "button_mismatches": button_mismatches,
        "stage_done": stage_done,
        "stage_timeout": stage_timeout,
        "sequence_complete": sequence_complete,
    }


def render_summary(summary):
    lines = [f"Boots: {len(summary['boots'])}"]
    for b in summary["boots"]:
        lines.append(f"  boot #{b['boot_num']}: reset_cause={b['reset_cause_name']}, "
                     f"resuming at stage {b['resume_stage']}")
    lines.append("\nStage results:")
    for stage in STAGE_ORDER:
        n_reps = len(summary["stage_reps"].get(stage, []))
        if stage in summary["stage_done"]:
            lines.append(f"  {stage:14s} DONE    ({n_reps} rep(s) detected)")
        elif stage in summary["stage_timeout"]:
            lines.append(f"  {stage:14s} TIMEOUT ({n_reps} rep(s) detected before giving up)")
        else:
            lines.append(f"  {stage:14s} not reached")
    if summary["button_mismatches"]:
        lines.append("\nButton mismatches:")
        lines.extend(f"  {m}" for m in summary["button_mismatches"])
    lines.append(f"\nSequence complete: {summary['sequence_complete']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# One newly-appeared port -> start / resume / retrieve. Takes an mpremote-
# shaped object (duck-typed, see MPRemote below and FakeMPRemote in tests)
# so this is fully testable without a real board.
# ---------------------------------------------------------------------------

def handle_new_port(mpremote, port, recordings_root=DEFAULT_RECORDINGS_ROOT,
                     notes_fn=input, auto_start=True, verbose=print):
    marker_text = mpremote.read_file(port, STATE_FILENAME)
    log_text_probe = mpremote.read_file(port, LOG_FILENAME)
    action = decide_action(marker_text, log_exists=log_text_probe is not None)

    if action == "start":
        if not auto_start:
            verbose(f"{port}: fresh unit, no marker -- not starting (auto_start=False)")
            return {"action": "skipped_start", "port": port}
        mpremote.write_file(port, STATE_FILENAME, "0|None|None")
        mpremote.reset(port)
        verbose(f"{port}: remote-started a fresh healthcheck run")
        return {"action": "start", "port": port}

    if action == "resume":
        mpremote.reset(port)
        verbose(f"{port}: unit was mid-run (marker={marker_text!r}) -- reset to resume from where it left off")
        return {"action": "resume", "port": port}

    # action == "retrieve"
    identity = mpremote.get_identity(port)
    log_text = log_text_probe or ""

    # Prefer the exact verdict the device itself computed and displayed
    # (parsed straight from its VERDICT log line -- the common case, since
    # a field-completed run has already cleared its own marker). Fall back
    # to recomputing from the marker only for the rare race where a host
    # caught the device before its own post-verdict reset ran.
    verdict = parse_verdict_line(log_text)
    if verdict is None:
        if marker_text is not None:
            _stage_idx, rest_uv, loaded_p10_uv = parse_marker_text(marker_text)
            from healthcheck_logic import compute_battery_verdict
            verdict = compute_battery_verdict(
                rest_uv, [loaded_p10_uv] if loaded_p10_uv is not None else []
            )
        else:
            verdict = {"verdict": "unknown -- no VERDICT line in log", "provisional": True}

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = timestamp.replace(":", "-")
    uid = identity.get("uid", "unknown")
    run_dir = os.path.join(recordings_root, uid, run_id)
    os.makedirs(run_dir, exist_ok=True)

    with open(os.path.join(run_dir, LOG_FILENAME), "w") as f:
        f.write(log_text)

    notes = notes_fn()
    meta = build_recording_meta(
        identity, notes, verdict, timestamp,
        source_log=os.path.join(uid, run_id, LOG_FILENAME),
    )
    with open(os.path.join(run_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    mpremote.remove_file(port, LOG_FILENAME)
    mpremote.remove_file(port, STATE_FILENAME)
    mpremote.reset(port)

    verbose(f"{port}: retrieved run for uid={uid} -> {run_dir}")
    verbose(render_summary(summarize_log(log_text)))
    verbose(f"battery verdict: {verdict}")

    return {"action": "retrieve", "port": port, "uid": uid, "run_id": run_id, "run_dir": run_dir}


# ---------------------------------------------------------------------------
# Effectful mpremote wrapper.
# ---------------------------------------------------------------------------

class MPRemote:
    def __init__(self, timeout=30):
        self.timeout = timeout

    def _run(self, args, port=None, timeout=None):
        cmd = [MPREMOTE]
        if port:
            cmd += ["connect", port]
        cmd += args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout or self.timeout)

    def list_ports(self):
        out = self._run(["connect", "list"])
        return parse_port_list(out.stdout)

    def get_identity(self, port):
        return get_identity(port)

    def read_file(self, port, filename):
        snippet = (
            "try:\n"
            f"    print(open('{filename}').read())\n"
            "except OSError:\n"
            "    print('__HEALTHCHECK_HOST_MISSING__')\n"
        )
        out = self._run(["exec", snippet], port=port)
        if out.returncode != 0:
            return None
        text = out.stdout
        if text.strip() == "__HEALTHCHECK_HOST_MISSING__":
            return None
        return text[:-1] if text.endswith("\n") else text

    def write_file(self, port, filename, content):
        # Explicit close() matters: the very next call is `mpremote reset`,
        # which power-cycles the board. An unclosed file handle's write can
        # still be sitting in a buffer rather than committed to flash when
        # that happens, silently losing the marker -- main.py then finds no
        # healthcheck_state.txt and boots into standalone as if nothing had
        # been requested at all.
        snippet = f"f = open('{filename}', 'w')\nf.write({content!r})\nf.close()\n"
        self._run(["exec", snippet], port=port)

    def remove_file(self, port, filename):
        snippet = f"import os\ntry:\n    os.remove('{filename}')\nexcept OSError:\n    pass\n"
        self._run(["exec", snippet], port=port)

    def reset(self, port):
        self._run(["reset"], port=port)


# ---------------------------------------------------------------------------
# Watch loop.
# ---------------------------------------------------------------------------

def watch(mpremote, recordings_root=DEFAULT_RECORDINGS_ROOT, poll_interval_s=3.0,
          auto_start=True, notes_fn=input, max_iterations=None, verbose=print):
    known = set()
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        current = filter_candidate_ports(mpremote.list_ports())
        for port in classify_new_ports(known, current):
            try:
                handle_new_port(mpremote, port, recordings_root=recordings_root,
                                 notes_fn=notes_fn, auto_start=auto_start, verbose=verbose)
            except Exception as exc:
                verbose(f"{port}: error handling newly-appeared port: {exc}")
        known = set(current)
        if max_iterations is None or iterations < max_iterations:
            time.sleep(poll_interval_s)


def main(argv=None):
    ap = argparse.ArgumentParser(description="SmartMotor healthcheck fleet manager")
    sub = ap.add_subparsers(dest="command", required=True)

    watch_p = sub.add_parser("watch", help="Watch serial ports; remote-start and retrieve as they appear")
    watch_p.add_argument("--recordings", default=DEFAULT_RECORDINGS_ROOT)
    watch_p.add_argument("--poll-interval", type=float, default=3.0)
    watch_p.add_argument("--auto-start", action="store_true", default=True)
    watch_p.add_argument("--no-auto-start", dest="auto_start", action="store_false")

    args = ap.parse_args(argv)
    if args.command == "watch":
        print(f"watching for SmartMotors -- recordings -> {args.recordings}")
        watch(MPRemote(), recordings_root=args.recordings, poll_interval_s=args.poll_interval,
              auto_start=args.auto_start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
