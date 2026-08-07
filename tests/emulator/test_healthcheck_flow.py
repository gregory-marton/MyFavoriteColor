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

    # SELECT/UP/DOWN run before SCREEN_CHECK/DISCONNECT_PROMPT -- everything
    # confirm-based (including SCREEN_CHECK) depends on them.
    select_idx = log.index("stage=SELECT")
    assert select_idx < disconnect_done_idx

    # Ran every control-exercise stage through the first deliberate reboot
    # point (REBOOT_FOR_SENSOR_SWAP) -- COLOR_WHITE/SUSTAIN/OFFON are on the
    # far side of that reboot, covered by the second-boot test below.
    for stage in ("SELECT", "UP", "DOWN", "SCREEN_CHECK", "POT", "FLIP"):
        assert ("stage=%s" % stage) in log
    assert "WAITING_FOR_REBOOT stage=REBOOT_FOR_SENSOR_SWAP" in log

    state = read_vfs_file(session, "healthcheck_state.txt")
    stage_idx = int(state.split("|")[0])
    assert stage_idx == healthcheck_module_stages_index(tmp_path, "REBOOT_FOR_SENSOR_SWAP") + 1


def healthcheck_module_stages_index(tmp_path, stage_name):
    """Reads healthcheck.py's own STAGES list back out (text scan, not an
    import -- it needs real hardware shims to import) so this test doesn't
    hardcode a second copy of the stage order that could silently drift
    from the source of truth."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(repo_root, "healthcheck.py")) as f:
        text = f.read()
    start = text.index("STAGES = [") + len("STAGES = [")
    end = text.index("\n]", start)
    # Strip comments line-by-line *before* splitting on commas -- a
    # comment can itself contain commas (several here do), which would
    # otherwise corrupt the split.
    body = "\n".join(line.split("#", 1)[0] for line in text[start:end].splitlines())
    names = [tok.strip().strip('"') for tok in body.split(",") if tok.strip()]
    return names.index(stage_name)


def test_resume_after_sensor_swap_reboot_reaches_offon(tmp_path, monkeypatch):
    """The second of the two deliberate reboots: resuming past
    REBOOT_FOR_SENSOR_SWAP must not need DISCONNECT_PROMPT to run again
    (it's already behind us) and must still have a working continuous
    sweeper (see main()'s "recreate it up front" fix) for COLOR_WHITE/
    SUSTAIN, which call sweeper.step()."""
    reboot_idx = healthcheck_module_stages_index(tmp_path, "REBOOT_FOR_SENSOR_SWAP")
    write_module(
        tmp_path,
        "healthcheck_post_swap_program",
        "def main():\n"
        "    with open('healthcheck_state.txt', 'w') as f:\n"
        f"        f.write('{reboot_idx + 1}|2084000|None')\n"
        "    import healthcheck\n"
        "    for k in healthcheck.STAGE_TIMEOUT_MS:\n"
        "        healthcheck.STAGE_TIMEOUT_MS[k] = 100\n"
        "    healthcheck.main()\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("healthcheck_post_swap_program")
    session.run_until_idle(timeout_ms=15000)

    assert session.error is None
    log = read_vfs_file(session, "healthcheck_log.txt")
    assert "DISCONNECT_PROMPT" not in log  # already behind us, must not re-run
    assert "stage=SUSTAIN" in log
    assert "WAITING_FOR_REBOOT stage=OFFON" in log


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
    offon_idx = healthcheck_module_stages_index(tmp_path, "OFFON")
    write_module(
        tmp_path,
        "healthcheck_resume_program",
        "def main():\n"
        "    with open('healthcheck_state.txt', 'w') as f:\n"
        f"        f.write('{offon_idx + 1}|2084000|2064000')\n"  # past OFFON; small sag -> healthy
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
