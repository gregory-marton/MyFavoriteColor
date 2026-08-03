"""D001: smcheck CLI skeleton.

Runs the registered checks against one board, prints a report card, and
appends it to the fleet store keyed by unique_id. No checks are registered
yet (see smcheck/registry.py) -- D002 onward add them. Running this today
against a real board proves the identity/report/fleet plumbing works, and
produces a `skip`-status report.
"""

import argparse
import os
import sys

from smcheck.device import get_identity
from smcheck.fleet import FleetStore
from smcheck.registry import FULL_ONLY_CHECKS, QUICK_CHECKS, run_checks
from smcheck.report import DeviceReport

DEFAULT_FLEET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fleet.jsonl")


def main(argv=None):
    ap = argparse.ArgumentParser(description="SmartMotor fleet health check")
    ap.add_argument("--port", default=None)
    ap.add_argument("--label", default="", help="e.g. 'unit-3' -- shown in the report, not required")
    ap.add_argument("--full", action="store_true", help="include human-assisted checks")
    ap.add_argument("--fleet", default=DEFAULT_FLEET_PATH, help="path to the fleet store JSONL file")
    args = ap.parse_args(argv)

    try:
        identity = get_identity(args.port)
    except RuntimeError as e:
        sys.exit(str(e))

    checks = QUICK_CHECKS + FULL_ONLY_CHECKS if args.full else QUICK_CHECKS
    results = run_checks(checks, args.port, identity)

    report = DeviceReport(uid=identity["uid"], label=args.label, checks=results)
    print(report.render_text())

    store = FleetStore(args.fleet)
    store.append(report)
    print(f"\nappended to {args.fleet}")


if __name__ == "__main__":
    main()
