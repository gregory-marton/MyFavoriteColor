"""D001: the smcheck report format.

One DeviceReport per run of smcheck against one board, holding one
CheckResult per health check (D-ID, D-FS, D-BAT, ...). See
DEVICE_HEALTH_DESIGN.md section 5 for the check catalogue this is built to
hold, and section 8 for the task breakdown.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

STATUSES = ("pass", "warn", "fail", "skip")

# Worst-first, so max() over a report's checks gives the overall verdict.
_SEVERITY = {"skip": 0, "pass": 1, "warn": 2, "fail": 3}


@dataclass
class CheckResult:
    id: str
    status: str
    summary: str
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}; must be one of {STATUSES}")

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "summary": self.summary,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], status=d["status"], summary=d["summary"], detail=d.get("detail", {}))


@dataclass
class DeviceReport:
    uid: str
    checks: list
    label: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    @property
    def overall_status(self):
        if not self.checks:
            return "skip"
        non_skipped = [c for c in self.checks if c.status != "skip"]
        if not non_skipped:
            return "skip"
        return max((c.status for c in non_skipped), key=_SEVERITY.get)

    def to_dict(self):
        return {
            "uid": self.uid,
            "label": self.label,
            "timestamp": self.timestamp,
            "checks": [c.to_dict() for c in self.checks],
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            uid=d["uid"],
            label=d.get("label", ""),
            timestamp=d["timestamp"],
            checks=[CheckResult.from_dict(c) for c in d["checks"]],
        )

    def render_text(self):
        title = f"{self.label or self.uid}  (uid {self.uid})  [{self.overall_status}]"
        lines = [title, "-" * len(title)]
        if not self.checks:
            lines.append("  (no checks run)")
        for c in self.checks:
            lines.append(f"  {c.id:8s} {c.status:5s}  {c.summary}")
        return "\n".join(lines)
