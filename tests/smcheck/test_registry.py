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


def test_run_checks_survives_one_check_raising():
    # A flaky mpremote call in one check must not kill the whole batch --
    # this is what makes `smcheck --full` safe to run unattended on a class set.
    def raising_check(port, identity):
        raise RuntimeError("mpremote timed out")

    def b(port, identity):
        return CheckResult(id="B", status="pass", summary="ok")

    results = run_checks([raising_check, b], port=None, identity={})

    assert len(results) == 2
    assert results[0].status == "fail"
    assert "mpremote timed out" in results[0].summary
    assert results[1].id == "B"
    assert results[1].status == "pass"


def test_run_checks_uses_function_name_as_id_when_a_check_raises():
    def check_d_something_broken(port, identity):
        raise RuntimeError("boom")

    results = run_checks([check_d_something_broken], port=None, identity={})

    assert results[0].id == "check_d_something_broken"
