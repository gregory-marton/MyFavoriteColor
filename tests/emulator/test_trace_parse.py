"""Trace parsing: turns a guided_log.txt into an ordered, timestamp-offset
list of typed events, one global timeline across reboots. Written before
smotoremu/trace.py exists.

Battery-charging-range heuristic (raw > 2850) matches
guided_test_device.py's is_probably_on_usb() and sensors.readbattery()'s
'charging' bucket -- see DEVICE_HEALTH_DESIGN.md section 1.
"""

from smotoremu.trace import parse_guided_log


def test_parses_boot_lines():
    log = "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
    events = parse_guided_log(log)
    assert events[0]["type"] == "BOOT"
    assert events[0]["boot_num"] == 1
    assert events[0]["reset_cause_name"] == "PWRON_RESET"


def test_parses_screen_lines_with_pipe_joined_text():
    log = "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\nSCREEN t=100 lines=POT x3|sweep fully\n"
    events = parse_guided_log(log)
    screen = [e for e in events if e["type"] == "SCREEN"][0]
    assert screen["lines"] == ["POT x3", "sweep fully"]


def test_parses_servo_lines():
    log = "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\nSERVO t=50 angle=180\n"
    events = parse_guided_log(log)
    servo = [e for e in events if e["type"] == "SERVO"][0]
    assert servo["angle"] == 180


def test_parses_sustain_sample_and_flags_on_usb():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "SUSTAIN_SAMPLE t=10 pot=100 batt_raw=2900 batt_uv=2100000 accel=-9,1,-253\n"
        "SUSTAIN_SAMPLE t=20 pot=100 batt_raw=1900 batt_uv=1400000 accel=-9,1,-253\n"
    )
    events = parse_guided_log(log)
    samples = [e for e in events if e["type"] == "SUSTAIN_SAMPLE"]
    assert samples[0]["on_usb"] is True   # 2900 > 2850 charging threshold
    assert samples[1]["on_usb"] is False  # 1900 well below it
    assert samples[0]["accel"] == (-9, 1, -253)
    assert "orientation" in samples[0]
    assert "roll" in samples[0]["orientation"]
    assert "pitch" in samples[0]["orientation"]


def test_parses_start_sample_for_initial_usb_voltage_context():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "START_SAMPLE t=25 pot=2048 batt_raw=2900 batt_uv=2100000 accel=-9,1,-253\n"
    )
    events = parse_guided_log(log)
    sample = [e for e in events if e["type"] == "START_SAMPLE"][0]

    assert sample["battery_v"] == 2.1
    assert sample["on_usb"] is True


def test_timestamps_are_offset_to_a_single_global_timeline_across_boots():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "SERVO t=100 angle=0\n"
        "SERVO t=900 angle=180\n"
        "BOOT boot_num=2 reset_cause=1(PWRON_RESET) resume_stage=5\n"
        "SERVO t=50 angle=0\n"
    )
    events = parse_guided_log(log)
    servo_events = [e for e in events if e["type"] == "SERVO"]
    # times must be strictly increasing across the reboot, even though the
    # device's own ticks_ms() reset to near-zero on the second boot.
    ts = [e["t"] for e in servo_events]
    assert ts == sorted(ts)
    assert ts[2] > ts[1]


def test_parses_rep_stage_done_and_timeout():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "REP stage=POT rep=1\n"
        "STAGE_DONE stage=POT\n"
        "TIMEOUT stage=FLIP reps=0\n"
    )
    events = parse_guided_log(log)
    types = [e["type"] for e in events]
    assert "REP" in types and "STAGE_DONE" in types and "TIMEOUT" in types


def test_parses_accel_calibration_samples_and_summary():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "ACCEL_SAMPLE stage=ACCEL_FLAT1 t=100 accel=-9,1,-253 mag=253\n"
        "ACCEL_SUMMARY stage=ACCEL_FLAT1 status=pass n=12 span=4 mag=253.2 summary=flat reading is stable and near 1g\n"
    )
    events = parse_guided_log(log)
    sample = [e for e in events if e["type"] == "ACCEL_SAMPLE"][0]
    summary = [e for e in events if e["type"] == "ACCEL_SUMMARY"][0]

    assert sample["stage"] == "ACCEL_FLAT1"
    assert sample["orientation"]["pitch"] == 2.0
    assert summary["status"] == "pass"
    assert summary["max_axis_span"] == 4


def test_parses_color_white_samples_and_summary():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "COLOR_WHITE_SAMPLE t=200 r=1024 g=512 b=256 w=1200\n"
        "COLOR_WHITE_SUMMARY n=8 r=1000 g=500 b=250 w=1100 wb_milli=1000,2000,4000\n"
    )
    events = parse_guided_log(log)
    sample = [e for e in events if e["type"] == "COLOR_WHITE_SAMPLE"][0]
    summary = [e for e in events if e["type"] == "COLOR_WHITE_SUMMARY"][0]

    assert sample["rgbw"] == (1024, 512, 256, 1200)
    assert summary["white_balance_milli"] == (1000, 2000, 4000)


def test_parses_light_summary():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "LIGHT_SUMMARY stage=LIGHT_DARK n=50 min=12 max=20 mean=16\n"
    )
    events = parse_guided_log(log)
    summary = [e for e in events if e["type"] == "LIGHT_SUMMARY"][0]

    assert summary["stage"] == "LIGHT_DARK"
    assert summary["mean"] == 16


def test_parses_full_sample_line_from_healthcheck():
    # healthcheck.py's FULL_SAMPLE line -- superset of SUSTAIN_SAMPLE, plus
    # port mode, attached-sensor value, buttons, and servo angle. See
    # healthcheck_logic.format_full_sample_line().
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "FULL_SAMPLE t=30 pot=2048 batt_raw=2894 batt_uv=2079000 accel=-9,1,-253 "
        "port=alg sensor_attached=1 sensor=1500 btn=1,1,0 angle=90\n"
    )
    events = parse_guided_log(log)
    sample = [e for e in events if e["type"] == "FULL_SAMPLE"][0]

    assert sample["pot"] == 2048
    assert sample["batt_raw"] == 2894
    assert sample["battery_v"] == 2.079
    assert sample["accel"] == (-9, 1, -253)
    assert "orientation" in sample
    assert sample["on_usb"] is True  # 2894 > 2850 charging threshold
    assert sample["port_mode"] == "alg"
    assert sample["sensor_attached"] is True
    assert sample["sensor_value"] == 1500
    assert sample["buttons"] == (1, 1, 0)
    assert sample["angle"] == 90


def test_parses_full_sample_line_with_no_sensor_or_accel():
    log = (
        "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
        "FULL_SAMPLE t=1 pot=0 batt_raw=0 batt_uv=0 accel=None,None,None "
        "port=i2c sensor_attached=0 sensor=None btn=1,1,1 angle=0\n"
    )
    events = parse_guided_log(log)
    sample = [e for e in events if e["type"] == "FULL_SAMPLE"][0]

    assert sample["accel"] is None
    assert sample["orientation"] is None
    assert sample["sensor_attached"] is False
    assert sample["sensor_value"] is None
