"""Static/WebSocket server for the SmartMotor emulator.

Co-authored-by: GPT-5, Aug 2026
"""

import argparse
import asyncio
import mimetypes
import os

import smotor
from smotoremu import protocol
from smotoremu.sensors import get_sensor
from smotoremu.world import World

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_ROOT = os.path.join(REPO_ROOT, "web")


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


async def serve(host="127.0.0.1", port=8765):
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets is required for smotoremu.server") from exc

    async def handler(websocket):
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

    async with websockets.serve(handler, host, port, process_request=websocket_process_request):
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
    if request.path == "/ws":
        return None
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    status, headers, body = static_response(request.path)
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
