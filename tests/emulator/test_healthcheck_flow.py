"""Emulator-level bounded run of healthcheck.py -- confirms stage order and
the marker-file resume/skip-salute routing, not just the pure logic pieces
already covered by tests/test_healthcheck_logic.py.

Default emulated battery.raw (2750, see smotoremu/peripherals/inputs.py) is
already below the "on USB" threshold, and the instant clock advances every
sleep with no real wall-clock delay, so a full run through every
control-exercise stage to OFFON completes in a fraction of a real second --
safe to run to completion here. WAIT_RETRIEVAL (the true never-return loop
after a resume boot) is NOT run in this test; that path is exercised only by
its pure logic in tests/test_healthcheck_logic.py, since it has no timeout by
design (see healthcheck.py's SAFETY NOTE).

Co-authored-by: Claude Sonnet 5, Aug 2026
"""

import os

from smotoremu.session import Session


def write_module(tmp_path, name, source):
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    return path


def read_vfs_file(session, name):
    with open(os.path.join(session.vfs_dir, name)) as f:
        return f.read()


def test_fresh_run_defers_servo_sweep_until_disconnect_confirmed(tmp_path, monkeypatch):
    write_module(
        tmp_path,
        "healthcheck_fresh_program",
        "def main():\n"
        "    import healthcheck\n"
        # Every control-exercise stage times out with no input (nothing
        # presses a button or moves the pot in this test). The instant
        # clock skips real *sleep* time, but each stage loop still runs one
        # Python iteration per tick of virtual time -- shrinking the
        # timeouts keeps this a fast unit test without changing what's
        # being verified (stage order and the disconnect/sweeper gate, not
        # exact timeout durations, which are just named constants).\n"
        "    for k in healthcheck.STAGE_TIMEOUT_MS:\n"
        "        healthcheck.STAGE_TIMEOUT_MS[k] = 100\n"
        "    healthcheck.SKIP_WINDOW_MS = 40\n"
        "    healthcheck.main()\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("healthcheck_fresh_program")
    session.run_until_idle(timeout_ms=15000)

    assert session.error is None
    log = read_vfs_file(session, "healthcheck_log.txt")

    disconnect_done_idx = log.index("STAGE_DONE stage=DISCONNECT_PROMPT")
    first_servo_sweep_idx = log.index("SERVO t=")
    assert first_servo_sweep_idx > disconnect_done_idx, (
        "the continuous servo sweep must not start before disconnect is confirmed"
    )

    # Ran every control-exercise stage through the deliberate reboot point.
    for stage in ("POT", "SELECT", "UP", "DOWN", "FLIP", "SUSTAIN"):
        assert ("stage=%s" % stage) in log
    assert "WAITING_FOR_REBOOT stage=OFFON" in log

    state = read_vfs_file(session, "healthcheck_state.txt")
    stage_idx = int(state.split("|")[0])
    # STAGES = DISCONNECT_PROMPT, POT, SELECT, UP, DOWN, FLIP, ACCEL_FLAT1,
    # ACCEL_FIG8, ACCEL_FLAT2, LIGHT_DARK, LIGHT_BRIGHT, COLOR_WHITE,
    # SUSTAIN, OFFON -- a fresh run should reach the end (past OFFON).
    assert stage_idx == 14


def test_pending_marker_forces_healthcheck_regardless_of_buttons(tmp_path, monkeypatch):
    write_module(
        tmp_path,
        "healthcheck_resume_routing_program",
        "def main():\n"
        "    with open('healthcheck_state.txt', 'w') as f:\n"
        "        f.write('99|2080000|1900000')\n"
        "    import main\n"
        "    assert main.choose_activity([]) == 'healthcheck'\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("healthcheck_resume_routing_program")
    session.run_until_idle(timeout_ms=5000)

    assert session.error is None


def test_resume_after_offon_computes_verdict_then_waits_indefinitely(tmp_path, monkeypatch):
    """A completed run (reached OFFON, rebooted) computes and logs its
    verdict, then hands off to run_wait_retrieval() -- which loops forever
    by design (see its docstring: an earlier self-terminating version was
    confirmed on the bench as an unrequested reboot). Since that loop has
    no natural exit, this test stubs it out to verify the routing and
    verdict computation without actually entering an infinite loop under
    the emulator's instant clock. The marker and log are untouched here --
    only healthcheck_host.py's retrieval clears them now."""
    write_module(
        tmp_path,
        "healthcheck_resume_program",
        "def main():\n"
        "    with open('healthcheck_state.txt', 'w') as f:\n"
        "        f.write('14|2084000|2064000')\n"  # stage_idx==14 -- past OFFON; small sag -> healthy
        "    import healthcheck\n"
        "    calls = []\n"
        "    healthcheck.run_wait_retrieval = lambda *a, **kw: calls.append((a, kw))\n"
        "    healthcheck.main()\n"
        "    assert len(calls) == 1, calls\n"
        "    verdict = calls[0][0][-1]\n"
        "    assert verdict['verdict'] == 'likely healthy', verdict\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("healthcheck_resume_program")
    session.run_until_idle(timeout_ms=5000)

    assert session.error is None

    log = read_vfs_file(session, "healthcheck_log.txt")
    assert "VERDICT " in log
    assert "REP stage=OFFON rep=1" in log

    # untouched -- only a real retrieval (healthcheck_host.py) clears these
    assert os.path.exists(os.path.join(session.vfs_dir, "healthcheck_state.txt"))


def test_no_marker_and_no_salute_falls_back_to_standalone(tmp_path, monkeypatch):
    write_module(
        tmp_path,
        "healthcheck_no_marker_program",
        "def main():\n"
        "    import main\n"
        "    assert main.choose_activity([]) == 'standalone'\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("healthcheck_no_marker_program")
    session.run_until_idle(timeout_ms=5000)

    assert session.error is None
