"""D001: fleet store tests. Written before smcheck/fleet.py exists."""

from smcheck.fleet import FleetStore
from smcheck.report import CheckResult, DeviceReport


def make_report(uid, timestamp, status="pass"):
    return DeviceReport(
        uid=uid,
        timestamp=timestamp,
        checks=[CheckResult(id="D-ID", status=status, summary="ok")],
    )


def test_append_then_history_returns_it(tmp_path):
    store = FleetStore(tmp_path / "fleet.jsonl")
    report = make_report("uid1", "2026-08-03T10:00:00+00:00")

    store.append(report)

    history = store.history("uid1")
    assert len(history) == 1
    assert history[0].uid == "uid1"
    assert history[0].checks[0].status == "pass"


def test_history_for_unknown_uid_is_empty(tmp_path):
    store = FleetStore(tmp_path / "fleet.jsonl")
    assert store.history("never-seen") == []


def test_history_is_ordered_oldest_first(tmp_path):
    store = FleetStore(tmp_path / "fleet.jsonl")
    store.append(make_report("uid1", "2026-08-03T12:00:00+00:00"))
    store.append(make_report("uid1", "2026-08-03T10:00:00+00:00"))

    history = store.history("uid1")

    assert [r.timestamp for r in history] == [
        "2026-08-03T10:00:00+00:00",
        "2026-08-03T12:00:00+00:00",
    ]


def test_latest_returns_most_recent_report(tmp_path):
    store = FleetStore(tmp_path / "fleet.jsonl")
    store.append(make_report("uid1", "2026-08-03T10:00:00+00:00", status="pass"))
    store.append(make_report("uid1", "2026-08-03T12:00:00+00:00", status="fail"))

    latest = store.latest("uid1")

    assert latest.timestamp == "2026-08-03T12:00:00+00:00"
    assert latest.checks[0].status == "fail"


def test_latest_for_unknown_uid_is_none(tmp_path):
    store = FleetStore(tmp_path / "fleet.jsonl")
    assert store.latest("never-seen") is None


def test_store_persists_across_instances(tmp_path):
    path = tmp_path / "fleet.jsonl"
    FleetStore(path).append(make_report("uid1", "2026-08-03T10:00:00+00:00"))

    reopened = FleetStore(path)

    assert len(reopened.history("uid1")) == 1


def test_all_latest_returns_one_report_per_uid(tmp_path):
    store = FleetStore(tmp_path / "fleet.jsonl")
    store.append(make_report("uid1", "2026-08-03T10:00:00+00:00", status="pass"))
    store.append(make_report("uid2", "2026-08-03T11:00:00+00:00", status="fail"))
    store.append(make_report("uid1", "2026-08-03T12:00:00+00:00", status="warn"))

    latest = store.all_latest()

    assert set(latest) == {"uid1", "uid2"}
    assert latest["uid1"].checks[0].status == "warn"
    assert latest["uid2"].checks[0].status == "fail"


def test_uses_jsonl_one_report_per_line(tmp_path):
    path = tmp_path / "fleet.jsonl"
    store = FleetStore(path)
    store.append(make_report("uid1", "2026-08-03T10:00:00+00:00"))
    store.append(make_report("uid2", "2026-08-03T11:00:00+00:00"))

    lines = path.read_text().splitlines()

    assert len(lines) == 2
