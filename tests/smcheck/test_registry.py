"""D001: check registry plumbing tests. Written before smcheck/registry.py exists."""

from smcheck.registry import run_checks
from smcheck.report import CheckResult


def test_run_checks_calls_each_check_with_port_and_identity():
    seen = []

    def fake_check(port, identity):
        seen.append((port, identity))
        return CheckResult(id="FAKE", status="pass", summary="ok")

    identity = {"uid": "abc123"}
    results = run_checks([fake_check], port="/dev/fake", identity=identity)

    assert seen == [("/dev/fake", identity)]
    assert len(results) == 1
    assert results[0].id == "FAKE"


def test_run_checks_with_empty_list_returns_empty():
    assert run_checks([], port=None, identity={}) == []


def test_run_checks_preserves_order():
    def a(port, identity):
        return CheckResult(id="A", status="pass", summary="")

    def b(port, identity):
        return CheckResult(id="B", status="fail", summary="")

    results = run_checks([a, b], port=None, identity={})

    assert [r.id for r in results] == ["A", "B"]
