"""healthcheck_host.py -- pure logic tested with the mpremote subprocess
boundary mocked out, same pattern as smcheck/checks/pot_btn.py's
sample_fn/prompt_fn injection.

Co-authored-by: Claude Sonnet 5, Aug 2026
"""

import json
import os

import healthcheck_host as hh


def test_parse_port_list_extracts_device_paths():
    text = (
        "/dev/cu.usbmodem1101 None 303a:1001 Espressif MicroPython Board\n"
        "/dev/cu.Bluetooth-Incoming-Port None None None None\n"
    )
    assert hh.parse_port_list(text) == ["/dev/cu.usbmodem1101", "/dev/cu.Bluetooth-Incoming-Port"]


def test_parse_port_list_ignores_blank_lines():
    assert hh.parse_port_list("\n  \n/dev/cu.usbmodem2101 foo\n") == ["/dev/cu.usbmodem2101"]


def test_classify_new_ports_finds_only_unseen_ports():
    newly = hh.classify_new_ports(known={"/dev/a"}, current=["/dev/a", "/dev/b"])
    assert newly == ["/dev/b"]


def test_classify_new_ports_forgets_disconnected_ports():
    # A port that disappears and later reappears (e.g. the OFFON power
    # cycle) must be treated as newly-appeared again -- exercised via the
    # host loop's own known-set bookkeeping, not this pure function, but the
    # function itself must not need "history" beyond the current snapshot.
    newly = hh.classify_new_ports(known={"/dev/a", "/dev/gone"}, current=["/dev/a"])
    assert newly == []


def test_parse_marker_text_reads_stage_and_battery_fields():
    stage_idx, rest_uv, loaded_p10_uv = hh.parse_marker_text("14|2079000|1900000")
    assert stage_idx == 14
    assert rest_uv == 2079000
    assert loaded_p10_uv == 1900000


def test_parse_marker_text_handles_missing_battery_fields():
    stage_idx, rest_uv, loaded_p10_uv = hh.parse_marker_text("0|None|None")
    assert stage_idx == 0
    assert rest_uv is None
    assert loaded_p10_uv is None


def test_decide_action_starts_a_unit_with_no_marker_and_no_log():
    assert hh.decide_action(None, log_exists=False) == "start"


def test_decide_action_retrieves_a_field_completed_run():
    # The common case: a three-finger-salute run with no laptop present
    # clears its own marker and returns to normal operation on its own
    # (healthcheck.py's show_verdict_and_finish()) -- only the log is left.
    assert hh.decide_action(None, log_exists=True) == "retrieve"


def test_decide_action_retrieves_a_unit_that_reached_offon_with_marker_still_present():
    # Rare race: a host was already connected right as the device resumed
    # after OFFON, before its own post-verdict reset cleared the marker.
    marker = "%d|2079000|1900000" % hh.NUM_STAGES
    assert hh.decide_action(marker, log_exists=True) == "retrieve"


def test_decide_action_resumes_a_unit_interrupted_mid_run():
    assert hh.decide_action("3|None|None") == "resume"


def test_decide_action_resumes_on_unparseable_marker():
    # Corrupt/truncated marker -- safest is to let the device's own
    # defensive _read_state() (falls back to stage 0) sort it out on reset,
    # not guess here.
    assert hh.decide_action("not a marker") == "resume"


def test_build_recording_meta_carries_identity_notes_and_verdict():
    meta = hh.build_recording_meta(
        identity={"uid": "abc123", "implementation": "(1, 25, 0)", "freq": "160000000"},
        notes="visibly cracked screen",
        verdict={"verdict": "likely healthy", "sag_cell_mv": 40.0, "provisional": True},
        timestamp="2026-08-07T12:00:00+00:00",
        source_log="abc123/2026-08-07T12-00-00/healthcheck_log.txt",
    )
    assert meta["uid"] == "abc123"
    assert meta["notes"] == "visibly cracked screen"
    assert meta["verdict"]["verdict"] == "likely healthy"
    assert meta["source_log"] == "abc123/2026-08-07T12-00-00/healthcheck_log.txt"
    json.dumps(meta)  # must be JSON-serializable as-is


def test_summarize_log_reports_stage_and_reps_and_boots():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "REP stage=POT rep=1\n"
        "REP stage=POT rep=2\n"
        "REP stage=POT rep=3\n"
        "STAGE_DONE stage=POT\n"
        "TIMEOUT stage=SELECT reps=1\n"
        "BOOT boot_num=2 reset_cause=2(HARD_RESET) resume_stage=14\n"
        "SEQUENCE_COMPLETE\n"
    )
    summary = hh.summarize_log(log)

    assert summary["boots"][0]["boot_num"] == 1
    assert summary["boots"][1]["resume_stage"] == 14
    assert summary["stage_done"] == {"POT"}
    assert summary["stage_timeout"] == {"SELECT"}
    assert len(summary["stage_reps"]["POT"]) == 3


def test_render_summary_produces_readable_text():
    summary = hh.summarize_log(
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "REP stage=POT rep=1\n"
        "STAGE_DONE stage=POT\n"
    )
    text = hh.render_summary(summary)
    assert "POT" in text
    assert "boot #1" in text


class FakeMPRemote:
    def __init__(self, ports=(), files=None):
        self._ports = list(ports)
        self.files = files or {}  # port -> {filename: contents}
        self.calls = []
        self.resets = []

    def list_ports(self):
        self.calls.append(("list_ports",))
        return list(self._ports)

    def read_file(self, port, filename):
        self.calls.append(("read_file", port, filename))
        return self.files.get(port, {}).get(filename)

    def write_file(self, port, filename, content):
        self.calls.append(("write_file", port, filename, content))
        self.files.setdefault(port, {})[filename] = content

    def remove_file(self, port, filename):
        self.calls.append(("remove_file", port, filename))
        self.files.get(port, {}).pop(filename, None)

    def reset(self, port):
        self.calls.append(("reset", port))
        self.resets.append(port)

    def reset_with_message(self, port, lines):
        self.calls.append(("reset_with_message", port, lines))
        self.resets.append(port)

    def get_identity(self, port):
        self.calls.append(("get_identity", port))
        return {"uid": "deadbeef0001", "implementation": "", "freq": ""}

    def deploy_and_start(self, port):
        self.calls.append(("deploy_and_start", port))
        # deploy.sh healthcheck's real effect: manifest files land (not
        # modeled here) and the marker gets written.
        self.files.setdefault(port, {})["healthcheck_state.txt"] = "0|None|None"


def test_handle_new_port_starts_a_fresh_unit(tmp_path):
    mp = FakeMPRemote(ports=["/dev/a"])
    result = hh.handle_new_port(mp, "/dev/a", recordings_root=str(tmp_path), notes_fn=lambda: "")

    assert result["action"] == "start"
    assert mp.files["/dev/a"]["healthcheck_state.txt"] == "0|None|None"
    assert mp.resets == ["/dev/a"]


def test_handle_new_port_resumes_a_mid_run_unit(tmp_path):
    mp = FakeMPRemote(ports=["/dev/a"], files={"/dev/a": {"healthcheck_state.txt": "3|None|None"}})
    result = hh.handle_new_port(mp, "/dev/a", recordings_root=str(tmp_path), notes_fn=lambda: "")

    assert result["action"] == "resume"
    assert mp.resets == ["/dev/a"]
    # untouched -- healthcheck.py's own resume logic reads this on next boot
    assert mp.files["/dev/a"]["healthcheck_state.txt"] == "3|None|None"


def test_handle_new_port_retrieves_and_stores_a_completed_run(tmp_path):
    marker = "%d|2079000|1900000" % hh.NUM_STAGES
    log_text = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "STAGE_DONE stage=POT\n"
        "WAITING_FOR_REBOOT stage=OFFON\n"
    )
    mp = FakeMPRemote(
        ports=["/dev/a"],
        files={"/dev/a": {"healthcheck_state.txt": marker, "healthcheck_log.txt": log_text}},
    )
    result = hh.handle_new_port(
        mp, "/dev/a", recordings_root=str(tmp_path), notes_fn=lambda: "battery ran hot"
    )

    assert result["action"] == "retrieve"
    # cleared from the device and rebooted back to normal
    assert "healthcheck_state.txt" not in mp.files["/dev/a"]
    assert "healthcheck_log.txt" not in mp.files["/dev/a"]
    assert mp.resets == ["/dev/a"]

    run_dir = os.path.join(str(tmp_path), "deadbeef0001", result["run_id"])
    assert os.path.isfile(os.path.join(run_dir, "healthcheck_log.txt"))
    with open(os.path.join(run_dir, "meta.json")) as f:
        meta = json.load(f)
    assert meta["notes"] == "battery ran hot"
    assert meta["uid"] == "deadbeef0001"
    assert meta["verdict"]["verdict"] in {
        "likely healthy", "borderline -- worth a second look",
        "check battery -- low rest voltage", "check battery -- high sag under sustained load",
    }


def test_parse_verdict_line_reads_the_devices_own_computed_verdict():
    log_text = (
        "BOOT boot_num=2 reset_cause=1(PWRON_RESET) resume_stage=14\n"
        "REP stage=OFFON rep=1 (confirmed by this reboot)\n"
        "STAGE_DONE stage=OFFON\n"
        "VERDICT {'verdict': 'likely healthy', 'rest_cell_v': 4.16, "
        "'loaded_p10_cell_v': 4.1, 'sag_cell_mv': 60.0, 'divider_ratio': 2.0, "
        "'provisional': True}\n"
        "SEQUENCE_COMPLETE\n"
    )
    verdict = hh.parse_verdict_line(log_text)
    assert verdict["verdict"] == "likely healthy"
    assert verdict["sag_cell_mv"] == 60.0


def test_parse_verdict_line_missing_returns_none():
    assert hh.parse_verdict_line("BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n") is None


def test_handle_new_port_retrieves_a_field_completed_run_with_no_marker(tmp_path):
    # healthcheck.py's show_verdict_and_finish() has already cleared the
    # marker and returned to normal operation on its own -- only the log
    # (with its VERDICT line) is left to retrieve.
    log_text = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "STAGE_DONE stage=POT\n"
        "BOOT boot_num=2 reset_cause=1(PWRON_RESET) resume_stage=14\n"
        "VERDICT {'verdict': 'likely healthy', 'rest_cell_v': 4.16, "
        "'loaded_p10_cell_v': 4.1, 'sag_cell_mv': 60.0, 'divider_ratio': 2.0, "
        "'provisional': True}\n"
        "SEQUENCE_COMPLETE\n"
    )
    mp = FakeMPRemote(ports=["/dev/a"], files={"/dev/a": {"healthcheck_log.txt": log_text}})

    result = hh.handle_new_port(mp, "/dev/a", recordings_root=str(tmp_path), notes_fn=lambda: "")

    assert result["action"] == "retrieve"
    assert "healthcheck_log.txt" not in mp.files["/dev/a"]

    run_dir = os.path.join(str(tmp_path), "deadbeef0001", result["run_id"])
    with open(os.path.join(run_dir, "meta.json")) as f:
        meta = json.load(f)
    assert meta["verdict"]["verdict"] == "likely healthy"
    assert meta["verdict"]["sag_cell_mv"] == 60.0


def test_mpremote_write_file_snippet_closes_the_handle_before_reset():
    # Regression: an unclosed file handle's write can still be buffered
    # rather than committed to flash when the very next call (mpremote
    # reset) power-cycles the board -- silently losing the marker.
    calls = []
    mp = hh.MPRemote()
    mp._run = lambda args, port=None, timeout=None: calls.append(args)

    mp.write_file("/dev/a", "healthcheck_state.txt", "0|None|None")

    snippet = calls[0][1]
    assert ".close()" in snippet
    assert "0|None|None" in snippet


def test_filter_candidate_ports_drops_macos_bluetooth_virtual_port():
    ports = ["/dev/cu.usbmodem1101", "/dev/cu.Bluetooth-Incoming-Port"]
    assert hh.filter_candidate_ports(ports) == ["/dev/cu.usbmodem1101"]


def test_filter_candidate_ports_keeps_common_usb_serial_patterns():
    ports = [
        "/dev/cu.usbmodem1101",
        "/dev/cu.usbserial-0001",
        "/dev/cu.wchusbserial1420",
        "/dev/ttyACM0",
        "/dev/ttyUSB0",
        "COM3",
    ]
    assert hh.filter_candidate_ports(ports) == ports


def test_filter_candidate_ports_drops_everything_else():
    ports = ["/dev/cu.debug-console", "/dev/cu.wlan-debug"]
    assert hh.filter_candidate_ports(ports) == []


def test_watch_never_probes_a_filtered_out_port(tmp_path):
    mp = FakeMPRemote(ports=["/dev/cu.Bluetooth-Incoming-Port"])
    hh.watch(mp, recordings_root=str(tmp_path), poll_interval_s=0, auto_start=True,
             notes_fn=lambda: "", max_iterations=1, verbose=lambda *a: None)

    assert ("read_file", "/dev/cu.Bluetooth-Incoming-Port", hh.STATE_FILENAME) not in mp.calls


def test_handle_new_port_shows_ready_to_reboot_on_the_device_after_clearing(tmp_path):
    marker = "%d|2079000|1900000" % hh.NUM_STAGES
    log_text = "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\nWAITING_FOR_REBOOT stage=OFFON\n"
    mp = FakeMPRemote(
        ports=["/dev/a"],
        files={"/dev/a": {"healthcheck_state.txt": marker, "healthcheck_log.txt": log_text}},
    )
    hh.handle_new_port(mp, "/dev/a", recordings_root=str(tmp_path), notes_fn=lambda: "")

    reset_calls = [c for c in mp.calls if c[0] == "reset_with_message"]
    assert len(reset_calls) == 1
    _, port, lines = reset_calls[0]
    assert port == "/dev/a"
    assert any("ready to reboot" in line for line in lines)


def test_mpremote_reset_with_message_snippet_shows_lines_and_resets():
    calls = []
    mp = hh.MPRemote()
    mp._run = lambda args, port=None, timeout=None: calls.append(args)

    mp.reset_with_message("/dev/a", ("retrieved!", "ready to reboot"))

    snippet = calls[0][1]
    assert "retrieved!" in snippet
    assert "ready to reboot" in snippet
    assert "machine.reset()" in snippet


def test_handle_new_port_deploys_before_starting_when_deploy_first(tmp_path):
    mp = FakeMPRemote(ports=["/dev/a"])
    result = hh.handle_new_port(
        mp, "/dev/a", recordings_root=str(tmp_path), notes_fn=lambda: "", deploy_first=True
    )

    assert result["action"] == "start"
    assert ("deploy_and_start", "/dev/a") in mp.calls
    assert mp.files["/dev/a"]["healthcheck_state.txt"] == "0|None|None"
    # deploy_and_start already resets as part of deploy.sh healthcheck --
    # no separate write_file/reset call on top of it
    assert ("write_file", "/dev/a", hh.STATE_FILENAME, "0|None|None") not in mp.calls


def test_handle_new_port_skips_deploy_when_marker_already_present(tmp_path):
    mp = FakeMPRemote(ports=["/dev/a"], files={"/dev/a": {"healthcheck_state.txt": "3|None|None"}})
    hh.handle_new_port(mp, "/dev/a", recordings_root=str(tmp_path), notes_fn=lambda: "", deploy_first=True)

    assert not any(c[0] == "deploy_and_start" for c in mp.calls)


def test_mpremote_deploy_and_start_runs_deploy_sh_with_port_env():
    calls = []
    mp = hh.MPRemote()
    mp._subprocess_run = None  # not used; deploy_and_start calls subprocess.run directly

    import subprocess as subprocess_module
    original_run = subprocess_module.run

    def fake_run(args, cwd=None, env=None, capture_output=None, text=None, timeout=None):
        calls.append((args, env.get("PORT") if env else None))

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    subprocess_module.run = fake_run
    try:
        mp.deploy_and_start("/dev/cu.usbmodem1101")
    finally:
        subprocess_module.run = original_run

    args, port_env = calls[0]
    assert args == ["bash", hh.DEPLOY_SH, "healthcheck"]
    assert port_env == "/dev/cu.usbmodem1101"
