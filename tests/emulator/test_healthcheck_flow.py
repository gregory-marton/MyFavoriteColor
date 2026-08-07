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


def test_resume_after_offon_shows_verdict_then_clears_marker_and_resets(tmp_path, monkeypatch):
    """A field-completed run (three-finger salute, no laptop) must not sit
    stuck waiting to be plugged in: it shows the verdict briefly, clears its
    own marker, and resets back to normal operation on its own. The log
    stays on flash either way for healthcheck_host.py to retrieve later."""
    write_module(
        tmp_path,
        "healthcheck_resume_program",
        "def main():\n"
        "    with open('healthcheck_state.txt', 'w') as f:\n"
        "        f.write('14|2079000|1900000')\n"  # stage_idx==14 -- past OFFON
        "    import healthcheck\n"
        "    healthcheck.VERDICT_DISPLAY_MS = 100\n"
        "    healthcheck.main()\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("healthcheck_resume_program")
    session.run_until_idle(timeout_ms=15000)

    from smotoremu.machine_shim import DeviceReset
    assert isinstance(session.error, DeviceReset), (
        "expected healthcheck.py to self-trigger machine.reset() after showing the verdict"
    )

    log = read_vfs_file(session, "healthcheck_log.txt")
    assert "VERDICT " in log
    assert "SEQUENCE_COMPLETE" in log

    assert not os.path.exists(os.path.join(session.vfs_dir, "healthcheck_state.txt")), (
        "the marker must be cleared so the next real boot returns to normal dispatch"
    )


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
