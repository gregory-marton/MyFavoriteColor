"""T027 WebSocket protocol tests.

Co-authored-by: GPT-5, Aug 2026
"""

import base64
import asyncio
import json

import pytest

from smotoremu import protocol
from types import SimpleNamespace

from smotoremu.server import ServerSession, static_response, websocket_process_request


CLIENT_MESSAGES = [
    {"type": "press", "button": "up"},
    {"type": "release", "button": "select"},
    {"type": "set_pot", "raw": 1234},
    {"type": "set_tilt", "roll": 10, "pitch": -5},
    {"type": "set_world", "world": {"patches": []}},
    {"type": "clock", "mode": "scaled", "speed": 5},
    {"type": "attach", "part": "VEML6040"},
    {"type": "detach"},
    {"type": "boot"},
    {"type": "reset"},
    {"type": "power", "on": True},
]


@pytest.mark.parametrize("message", CLIENT_MESSAGES)
def test_client_messages_round_trip_with_version(message):
    raw = protocol.dumps(message)

    decoded = protocol.decode_client(raw)

    assert decoded == {"v": 1, **message}


def test_unknown_client_message_returns_error_reply():
    reply = protocol.decode_client(json.dumps({"v": 1, "type": "bogus"}))

    assert reply == {
        "v": 1,
        "type": "error",
        "code": "unknown_type",
        "message": "unknown client message type: bogus",
    }


def test_invalid_json_returns_error_reply():
    reply = protocol.decode_client("{")

    assert reply["type"] == "error"
    assert reply["code"] == "invalid_json"


def test_frame_message_encodes_png_bytes_and_lines():
    msg = protocol.frame_message(seq=7, png=b"\x89PNG", lines=["READY"])

    assert msg == {
        "v": 1,
        "type": "frame",
        "seq": 7,
        "png": base64.b64encode(b"\x89PNG").decode("ascii"),
        "lines": ["READY"],
    }


def test_state_log_trace_and_exited_messages_are_versioned():
    assert protocol.state_message(
        angle=90,
        pot=2048,
        battery=2750,
        attached="VEML6040",
        clock_ms=123,
    ) == {
        "v": 1,
        "type": "state",
        "angle": 90,
        "pot": 2048,
        "battery": 2750,
        "attached": "VEML6040",
        "clock_ms": 123,
    }
    assert protocol.log_message(t_us=5000, text="hello") == {
        "v": 1,
        "type": "log",
        "t": 5000,
        "text": "hello",
    }
    assert protocol.trace_message([{"kind": "button"}]) == {
        "v": 1,
        "type": "trace",
        "events": [{"kind": "button"}],
    }
    assert protocol.exited_message(RuntimeError("boom")) == {
        "v": 1,
        "type": "exited",
        "error": "boom",
    }


def test_frame_and_state_updates_coalesce_to_latest_at_30hz():
    coalescer = protocol.UpdateCoalescer(max_hz=30)
    first = protocol.frame_message(seq=1, png=b"first", lines=["first"])
    second = protocol.frame_message(seq=2, png=b"second", lines=["second"])
    state = protocol.state_message(angle=1, pot=2, battery=3, attached=None, clock_ms=4)

    assert coalescer.push(first, now_ms=0) == [first]
    assert coalescer.push(second, now_ms=10) == []
    assert coalescer.push(state, now_ms=15) == []

    assert coalescer.drain(now_ms=34) == [second, state]


def test_non_frame_state_messages_are_not_coalesced():
    coalescer = protocol.UpdateCoalescer(max_hz=30)
    msg = protocol.log_message(t_us=1, text="now")

    assert coalescer.push(msg, now_ms=1) == [msg]


def test_server_session_applies_button_pot_tilt_attach_detach_and_world_commands():
    server_session = ServerSession()
    try:
        server_session.handle(protocol.dumps({"type": "press", "button": "up"}))
        assert server_session.sm.session.buttons.held() == {"up"}

        server_session.handle(protocol.dumps({"type": "release", "button": "up"}))
        assert server_session.sm.session.buttons.held() == set()

        server_session.handle(protocol.dumps({"type": "set_pot", "raw": 1234}))
        assert server_session.sm.pot.raw == 1234

        server_session.handle(protocol.dumps({"type": "set_tilt", "roll": 10, "pitch": -5}))
        assert server_session.sm.session.accel is not None

        server_session.handle(protocol.dumps({"type": "set_world", "world": {"patches": [
            {"from": 0, "to": 180, "color": "#ff0000", "name": "red"}
        ]}}))
        assert server_session.sm.world.patch_at(90).name == "red"

        server_session.handle(protocol.dumps({"type": "attach", "part": "VEML6040"}))
        assert server_session.sm.sensor.display_name == "VEML6040 Colour Sensor"
        assert server_session.sm.session.port.attached is server_session.sm.sensor

        server_session.handle(protocol.dumps({"type": "detach"}))
        assert server_session.sm.sensor is None
        assert server_session.sm.session.port.attached is None
    finally:
        server_session.close()


def test_server_session_unknown_message_returns_error_without_crash():
    server_session = ServerSession()
    try:
        replies = server_session.handle('{"v": 1, "type": "bogus"}')

        assert replies == [{
            "v": 1,
            "type": "error",
            "code": "unknown_type",
            "message": "unknown client message type: bogus",
        }]
    finally:
        server_session.close()


def test_static_response_serves_web_index_and_app_js():
    index_status, index_headers, index_body = static_response("/")
    app_status, app_headers, app_body = static_response("/app.js")

    assert index_status == 200
    assert ("Content-Type", "text/html; charset=utf-8") in index_headers
    assert b"SmartMotor" in index_body
    assert app_status == 200
    assert ("Content-Type", "text/javascript; charset=utf-8") in app_headers
    assert b"SmartMotor" in app_body


def test_static_response_rejects_missing_or_escaping_paths():
    missing_status, _, _ = static_response("/missing.js")
    escaping_status, _, _ = static_response("/../README.md")

    assert missing_status == 404
    assert escaping_status == 404


def test_websocket_process_request_adapts_static_files_to_websockets_response():
    assert websocket_process_request(None, SimpleNamespace(path="/ws")) is None

    response = websocket_process_request(None, SimpleNamespace(path="/"))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert b"SmartMotor" in response.body


def test_websocket_round_trip_with_real_socket():
    try:
        reply = asyncio.run(_websocket_round_trip())
    except PermissionError as exc:
        pytest.skip(f"local socket bind not permitted in this sandbox: {exc}")

    assert reply["v"] == 1
    assert reply["type"] == "state"
    assert reply["pot"] == 2048


async def _websocket_round_trip():
    import websockets

    async def handler(websocket):
        server_session = ServerSession()
        try:
            async for raw in websocket:
                for reply in server_session.handle(raw):
                    await websocket.send(protocol.dumps(reply))
        finally:
            server_session.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with websockets.connect(f"ws://127.0.0.1:{port}") as websocket:
            await websocket.send(protocol.dumps({"type": "press", "button": "select"}))
            return protocol.loads(await websocket.recv())
