"""D001: report format tests. Written before smcheck/report.py exists."""

import pytest

from smcheck.report import CheckResult, DeviceReport


def test_check_result_holds_id_status_summary():
    c = CheckResult(id="D-ID", status="pass", summary="uid ac276e7cb698")
    assert c.id == "D-ID"
    assert c.status == "pass"
    assert c.summary == "uid ac276e7cb698"
    assert c.detail == {}  # default, no detail supplied


def test_check_result_rejects_unknown_status():
    with pytest.raises(ValueError):
        CheckResult(id="D-ID", status="excellent", summary="nope")


def test_report_overall_status_is_worst_of_its_checks():
    checks = [
        CheckResult(id="D-ID", status="pass", summary="ok"),
        CheckResult(id="D-FS", status="warn", summary="low on space"),
    ]
    report = DeviceReport(uid="abc123", checks=checks)
    assert report.overall_status == "warn"


def test_report_overall_status_fail_beats_warn():
    checks = [
        CheckResult(id="D-ID", status="warn", summary="..."),
        CheckResult(id="D-I2C", status="fail", summary="OLED not on bus"),
    ]
    report = DeviceReport(uid="abc123", checks=checks)
    assert report.overall_status == "fail"


def test_report_overall_status_pass_when_all_pass():
    checks = [CheckResult(id="D-ID", status="pass", summary="ok")]
    report = DeviceReport(uid="abc123", checks=checks)
    assert report.overall_status == "pass"


def test_report_overall_status_skip_when_all_skipped():
    checks = [CheckResult(id="D-ID", status="skip", summary="not run")]
    report = DeviceReport(uid="abc123", checks=checks)
    assert report.overall_status == "skip"


def test_report_overall_status_pass_with_empty_checks():
    # D001's own skeleton case: no checks registered yet.
    report = DeviceReport(uid="abc123", checks=[])
    assert report.overall_status == "skip"


def test_report_round_trips_through_json():
    checks = [CheckResult(id="D-ID", status="pass", summary="ok", detail={"freq": 160000000})]
    report = DeviceReport(uid="abc123", label="bad-unit-1", checks=checks)

    restored = DeviceReport.from_dict(report.to_dict())

    assert restored.uid == report.uid
    assert restored.label == report.label
    assert restored.timestamp == report.timestamp
    assert len(restored.checks) == 1
    assert restored.checks[0].id == "D-ID"
    assert restored.checks[0].detail == {"freq": 160000000}


def test_report_timestamp_defaults_to_now_utc_iso8601():
    report = DeviceReport(uid="abc123", checks=[])
    # ISO 8601 with an explicit UTC offset, e.g. 2026-08-03T12:34:56+00:00
    assert "T" in report.timestamp
    assert report.timestamp.endswith("+00:00") or report.timestamp.endswith("Z")


def test_render_text_includes_uid_and_each_check():
    checks = [
        CheckResult(id="D-ID", status="pass", summary="uid abc123"),
        CheckResult(id="D-FS", status="fail", summary="disk full"),
    ]
    report = DeviceReport(uid="abc123", label="suspect-1", checks=checks)
    text = report.render_text()
    assert "suspect-1" in text
    assert "abc123" in text
    assert "D-ID" in text and "pass" in text
    assert "D-FS" in text and "fail" in text
    assert "disk full" in text
