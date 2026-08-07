"""smotoremu/server.py's recordings API + /replay endpoint -- lets the web
UI browse ./recordings and watch a stored healthcheck run play back, so a
captured recording's jitter is actually visible rather than just parseable.

Direct-call pattern (no real socket) mirrors tests/emulator/test_protocol.py.

Co-authored-by: Claude Sonnet 5, Aug 2026
"""

import json
import os
from types import SimpleNamespace

import pytest

from smotoremu import protocol
from smotoremu.server import (
    list_recordings,
    load_recording_events,
    websocket_process_request,
    _replay_handler,
    _safe_join,
    _state_message_from_event,
)


def _write_log(root, uid, run_id, text):
    run_dir = os.path.join(root, uid, run_id)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "healthcheck_log.txt"), "w") as f:
        f.write(text)
    return run_dir


SAMPLE_LOG = (
    "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
    "SCREEN t=0 lines=hello|world\n"
    "FULL_SAMPLE t=10 pot=2048 batt_raw=2894 batt_uv=2079000 accel=-9,1,-253 "
    "port=alg sensor_attached=1 sensor=1500 btn=1,1,0 angle=90\n"
    "FULL_SAMPLE t=510 pot=2050 batt_raw=2890 batt_uv=2076000 accel=-8,2,-251 "
    "port=alg sensor_attached=1 sensor=1498 btn=1,1,0 angle=90\n"
)


def test_list_recordings_finds_logs_under_uid_and_run_id(tmp_path):
    _write_log(str(tmp_path), "deadbeef0001", "2026-08-07T12-00-00", SAMPLE_LOG)
    _write_log(str(tmp_path), "deadbeef0002", "2026-08-07T13-00-00", SAMPLE_LOG)

    found = list_recordings(root=str(tmp_path))

    assert "deadbeef0001/2026-08-07T12-00-00/healthcheck_log.txt" in found
    assert "deadbeef0002/2026-08-07T13-00-00/healthcheck_log.txt" in found


def test_list_recordings_empty_when_directory_missing(tmp_path):
    assert list_recordings(root=str(tmp_path / "nope")) == []


def test_safe_join_rejects_escaping_paths(tmp_path):
    assert _safe_join(str(tmp_path), "../../etc/passwd") is None
    assert _safe_join(str(tmp_path), "a/b/healthcheck_log.txt") is not None


def test_load_recording_events_parses_and_renders_screens(tmp_path):
    _write_log(str(tmp_path), "uid1", "run1", SAMPLE_LOG)

    events = load_recording_events("uid1/run1/healthcheck_log.txt", root=str(tmp_path))

    kinds = [e["type"] for e in events]
    assert "FULL_SAMPLE" in kinds
    screen = [e for e in events if e["type"] == "SCREEN"][0]
    assert "screen_buffer_b64" in screen  # render_screens ran


def test_load_recording_events_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_recording_events("nope/nope/healthcheck_log.txt", root=str(tmp_path))


def test_state_message_from_full_sample_carries_pot_battery_and_sensor():
    event = {
        "type": "FULL_SAMPLE", "t": 10, "pot": 2048, "batt_raw": 2894,
        "accel": (-9, 1, -253), "port_mode": "alg", "sensor_attached": True,
        "sensor_value": 1500, "angle": 90, "on_usb": True,
    }
    msg = _state_message_from_event(event)

    assert msg["pot"] == 2048
    assert msg["battery"] == 2894
    assert msg["sensor_value"] == 1500
    assert msg["angle"] == 90


def test_state_message_from_non_sample_event_is_none():
    assert _state_message_from_event({"type": "SCREEN", "t": 0}) is None


def test_websocket_process_request_lets_replay_and_api_paths_through_or_serve_json():
    assert websocket_process_request(None, SimpleNamespace(path="/replay?path=a/b")) is None

    response = websocket_process_request(None, SimpleNamespace(path="/api/recordings"))
    assert response.status_code == 200
    assert json.loads(response.body) == []


class _FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


async def _run_replay(tmp_path, rel_path, speed=1000.0):
    ws = _FakeWebSocket()
    from smotoremu import server as server_module
    server_module.RECORDINGS_ROOT = str(tmp_path)
    await _replay_handler(ws, rel_path, speed=speed)
    return ws.sent


def test_replay_handler_streams_trace_and_state_then_exits(tmp_path):
    import asyncio

    _write_log(str(tmp_path), "uid1", "run1", SAMPLE_LOG)
    sent = asyncio.run(_run_replay(tmp_path, "uid1/run1/healthcheck_log.txt"))

    trace_messages = [m for m in sent if m["type"] == "trace"]
    state_messages = [m for m in sent if m["type"] == "state"]
    exited = [m for m in sent if m["type"] == "exited"]

    assert len(trace_messages) >= 3  # BOOT-derived events + SCREEN + 2x FULL_SAMPLE
    assert len(state_messages) == 2  # one per FULL_SAMPLE
    assert state_messages[0]["pot"] == 2048
    assert state_messages[1]["pot"] == 2050
    assert len(exited) == 1
    assert exited[0]["error"] is None


def test_replay_handler_reports_error_for_missing_recording(tmp_path):
    import asyncio

    sent = asyncio.run(_run_replay(tmp_path, "nope/nope/healthcheck_log.txt"))

    assert sent[0]["type"] == "error"
