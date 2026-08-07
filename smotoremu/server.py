"""Static/WebSocket server for the SmartMotor emulator.

Co-authored-by: GPT-5, Aug 2026
"""

import argparse
import asyncio
import json
import mimetypes
import os

import smotor
from smotoremu import protocol
from smotoremu.sensors import get_sensor
from smotoremu.world import World

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_ROOT = os.path.join(REPO_ROOT, "web")
RECORDINGS_ROOT = os.path.join(REPO_ROOT, "recordings")


class ServerSession:
    def __init__(self):
        self.sm = smotor.launch()
        self.seq = 0

    def handle(self, raw):
        message = protocol.decode_client(raw)
        if message["type"] == "error":
            return [message]
        try:
            self._apply(message)
        except Exception as exc:
            return [protocol.error_message("command_failed", str(exc))]
        return [self.state_message()]

    def state_message(self):
        attached = None
        if self.sm.sensor is not None:
            attached = getattr(self.sm.sensor, "display_name", type(self.sm.sensor).__name__)
        commanded_angle = self.sm.arm.angle
        if getattr(self.sm.session.board, "servo_model", None) is not None:
            commanded_angle = self.sm.session.board.servo_model.commanded_angle
        world = self.sm.world.to_dict() if self.sm.world is not None else None
        return protocol.state_message(
            angle=self.sm.arm.angle,
            pot=self.sm.pot.raw,
            battery=self.sm.battery.raw,
            attached=attached,
            clock_ms=self.sm.session.clock.now_ms(),
            commanded_angle=commanded_angle,
            world=world,
        )

    def frame_message(self):
        self.seq += 1
        return protocol.frame_message(self.seq, self.sm.screen.png(), self.sm.screen.lines())

    def close(self):
        self.sm.close()

    def _apply(self, message):
        message_type = message["type"]
        if message_type == "press":
            self.sm.press(message["button"])
        elif message_type == "release":
            self.sm.release(message["button"])
        elif message_type == "set_pot":
            self.sm.pot.set_raw(message["raw"])
        elif message_type == "set_tilt":
            self.sm.tilt(message["roll"], message["pitch"])
        elif message_type == "set_world":
            self.sm.world = World(**message["world"])
            self.sm.session.world = self.sm.world
            if self.sm.sensor is not None:
                self.sm.sensor.world = self.sm.world
        elif message_type == "clock":
            self.sm.session.clock.set_mode(message["mode"], message.get("speed", 1.0))
        elif message_type == "attach":
            self._attach(message["part"])
        elif message_type == "detach":
            self.sm.session.port.detach()
            self.sm.sensor = None
        elif message_type == "boot":
            self.sm.boot()
        elif message_type == "reset":
            self._reset()
        elif message_type == "power":
            if not message["on"]:
                self.sm.close()
            elif self.sm._closed:
                self._reset()

    def _attach(self, part):
        sensor = get_sensor(part)(rng=self.sm.session.rng)
        sensor.attach(self.sm.session.port, self.sm.world, self.sm.session.clock)
        self.sm.sensor = sensor

    def _reset(self):
        self.sm.close()
        self.sm = smotor.launch()
        self.seq = 0


def list_recordings(root=None):
    """Relative paths of every retrievable healthcheck log under
    ./recordings, newest first -- what the web UI's recordings browser
    populates from. healthcheck_host.py is what actually fills this
    directory; this just reads it back."""
    root = root or RECORDINGS_ROOT
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name == "healthcheck_log.txt":
                full = os.path.join(dirpath, name)
                found.append(os.path.relpath(full, root))
    return sorted(found, reverse=True)


def _safe_join(root, relative):
    """Same traversal guard as static_response, rooted at `root` instead of
    WEB_ROOT."""
    root_abs = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(root_abs, relative))
    if not candidate.startswith(root_abs + os.sep):
        return None
    return candidate


def load_recording_events(rel_path, root=None):
    """Parse a retrieved healthcheck_log.txt into the same typed, screen-
    rendered event list smotoremu/trace.py already produces for the old
    trace-render tests -- reused here, not reimplemented."""
    from smotoremu.trace import parse_guided_log, render_screens

    root = root or RECORDINGS_ROOT
    candidate = _safe_join(root, rel_path)
    if candidate is None or not os.path.isfile(candidate):
        raise FileNotFoundError(rel_path)
    with open(candidate) as f:
        text = f.read()
    return render_screens(parse_guided_log(text))


def _state_message_from_event(event):
    """A subset of FULL_SAMPLE/SUSTAIN_SAMPLE/START_SAMPLE's fields, reusing
    protocol.state_message so the replay path updates the same header
    readout ("Sensor: ... | Pot: ... | Angle: ...") the live path does."""
    event_type = event.get("type")
    if event_type not in ("FULL_SAMPLE", "SUSTAIN_SAMPLE", "START_SAMPLE"):
        return None
    kwargs = dict(
        angle=event.get("angle", 0),
        pot=event.get("pot", 0),
        battery=event.get("batt_raw", 0),
        attached=event.get("port_mode"),
        clock_ms=event.get("t", 0),
        usb=event.get("on_usb"),
    )
    if event_type == "FULL_SAMPLE":
        kwargs["mode"] = event.get("port_mode")
        kwargs["sensor_attached"] = event.get("sensor_attached")
        kwargs["sensor_value"] = event.get("sensor_value")
    if event.get("accel") is not None:
        kwargs["accel"] = event["accel"]
    return protocol.state_message(**kwargs)


async def _replay_handler(websocket, rel_path, speed=15.0):
    """Streams a stored recording's parsed events back at a scaled pace,
    over its own /replay connection -- deliberately separate from
    ServerSession's live hardware model, since replay has no board to
    drive. The client already handles `type: "trace"` and `type: "state"`
    generically (see web/app.js's handleMessage), so no protocol addition
    was needed beyond parsing FULL_SAMPLE (smotoremu/trace.py)."""
    try:
        events = load_recording_events(rel_path)
    except FileNotFoundError:
        await websocket.send(protocol.dumps(protocol.error_message(
            "not_found", f"no recording at {rel_path!r}"
        )))
        return

    prev_t = 0
    for event in events:
        t = event.get("t", prev_t)
        dt_ms = max(0, t - prev_t)
        prev_t = t
        if dt_ms:
            # capped so one long gap (e.g. across the OFFON reboot) doesn't
            # stall the replay for real minutes
            await asyncio.sleep(min(dt_ms, 3000) / 1000.0 / speed)
        await websocket.send(protocol.dumps(protocol.trace_message([event])))
        state = _state_message_from_event(event)
        if state is not None:
            await websocket.send(protocol.dumps(state))
    await websocket.send(protocol.dumps(protocol.exited_message(None)))


async def _connection_handler(websocket):
    """One /ws (live session) or /replay (recorded playback) connection.
    Module-level so tests can drive it directly via websockets.serve without
    going through serve()'s own event loop / port-8765 default."""
    request_path = websocket.request.path
    if request_path.startswith("/replay"):
        from urllib.parse import parse_qs, urlsplit

        query = parse_qs(urlsplit(request_path).query)
        rel_path = (query.get("path") or [""])[0]
        speed = float((query.get("speed") or ["15"])[0])
        await _replay_handler(websocket, rel_path, speed=speed)
        return

    session = ServerSession()
    coalescer = protocol.UpdateCoalescer()
    try:
        await websocket.send(protocol.dumps(session.state_message()))
        await websocket.send(protocol.dumps(session.frame_message()))
        async for raw in websocket:
            for message in session.handle(raw):
                for outbound in coalescer.push(message, now_ms=session.sm.session.clock.now_ms()):
                    await websocket.send(protocol.dumps(outbound))
            for outbound in coalescer.push(session.frame_message(), now_ms=session.sm.session.clock.now_ms()):
                await websocket.send(protocol.dumps(outbound))
            for outbound in coalescer.drain(now_ms=session.sm.session.clock.now_ms()):
                await websocket.send(protocol.dumps(outbound))
            if session.sm.session.exited or session.sm.session.error is not None:
                await websocket.send(protocol.dumps(protocol.exited_message(session.sm.session.error)))
    finally:
        session.close()


async def serve(host="127.0.0.1", port=8765):
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets is required for smotoremu.server") from exc

    async with websockets.serve(_connection_handler, host, port, process_request=websocket_process_request):
        await asyncio.Future()


def static_response(path):
    if path in {"", "/"}:
        path = "/index.html"
    relative = path.lstrip("/")
    candidate = os.path.abspath(os.path.join(WEB_ROOT, relative))
    if not candidate.startswith(WEB_ROOT + os.sep):
        return 404, [("Content-Type", "text/plain; charset=utf-8")], b"not found"
    if not os.path.isfile(candidate):
        return 404, [("Content-Type", "text/plain; charset=utf-8")], b"not found"
    with open(candidate, "rb") as handle:
        body = handle.read()
    content_type = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in {"application/javascript"}:
        content_type += "; charset=utf-8"
    return 200, [("Content-Type", content_type)], body


def websocket_process_request(connection, request):
    path = request.path.split("?", 1)[0]
    if path == "/ws" or path.startswith("/replay"):
        return None
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    if path == "/api/recordings":
        body = json.dumps(list_recordings()).encode("utf-8")
        return Response(200, "OK", Headers([("Content-Type", "application/json")]), body)

    status, headers, body = static_response(path)
    reason = "OK" if status == 200 else "Not Found"
    return Response(status, reason, Headers(headers), body)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    asyncio.run(serve(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
