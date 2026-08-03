"""D001: the fleet store -- persisted DeviceReports, keyed by unique_id.

One JSONL file, one report per line, append-only. Deliberately simple: a
class set is tens of devices and a handful of runs a day, not a scale that
needs a real database.
"""

import json
from pathlib import Path

from smcheck.report import DeviceReport


class FleetStore:
    def __init__(self, path):
        self.path = Path(path)

    def append(self, report):
        with open(self.path, "a") as f:
            f.write(json.dumps(report.to_dict()) + "\n")

    def _all(self):
        if not self.path.exists():
            return []
        reports = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    reports.append(DeviceReport.from_dict(json.loads(line)))
        return reports

    def history(self, uid):
        matching = [r for r in self._all() if r.uid == uid]
        return sorted(matching, key=lambda r: r.timestamp)

    def latest(self, uid):
        history = self.history(uid)
        return history[-1] if history else None

    def all_latest(self):
        latest_by_uid = {}
        for report in self._all():
            existing = latest_by_uid.get(report.uid)
            if existing is None or report.timestamp > existing.timestamp:
                latest_by_uid[report.uid] = report
        return latest_by_uid
