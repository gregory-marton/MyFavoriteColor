"""Versioned JSON protocol for SmartMotor emulator clients.

Co-authored-by: GPT-5, Aug 2026
Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import base64
import json

PROTOCOL_VERSION = 1
COALESCED_TYPES = {"frame", "state"}

CLIENT_SCHEMAS = {
    "press": {"button"},
    "release": {"button"},
    "set_pot": {"raw"},
    "set_tilt": {"roll", "pitch"},
    "set_world": {"world"},
    "clock": {"mode", "speed"},
    "attach": {"part"},
    "detach": set(),
    "boot": set(),
    "reset": set(),
    "power": {"on"},
    "record": {"recording"},
}


def dumps(message) -> str:
    return json.dumps(_versioned(message), sort_keys=True)


def loads(raw):
    return json.loads(raw)


def decode_client(raw):
    if isinstance(raw, str):
        try:
            message = json.loads(raw)
        except Exception:
            return error_message("invalid_json", "failed to parse client message as JSON")
    else:
        message = raw

    if not isinstance(message, dict):
        return error_message("invalid_message", "client message must be a JSON object")

    version = message.get("v", PROTOCOL_VERSION)
    if version != PROTOCOL_VERSION:
        return error_message("unsupported_version", f"unsupported protocol version: {version}")

    message_type = message.get("type")
    if message_type not in CLIENT_SCHEMAS:
        return error_message("unknown_type", f"unknown client message type: {message_type}")

    missing = sorted(CLIENT_SCHEMAS[message_type] - set(message))
    if missing:
        return error_message("missing_field", f"missing field(s): {', '.join(missing)}")

    return {"v": PROTOCOL_VERSION, **{key: value for key, value in message.items() if key != "v"}}


def error_message(code, message):
    return {"v": PROTOCOL_VERSION, "type": "error", "code": code, "message": message}


def frame_message(seq, png, lines):
    return {
        "v": PROTOCOL_VERSION,
        "type": "frame",
        "seq": seq,
        "png": base64.b64encode(png).decode("ascii"),
        "lines": list(lines),
    }


def state_message(*, angle, pot, battery, attached, clock_ms, commanded_angle=None, world=None, is_recording=None, button=None, buttons=None, roll=None, pitch=None, power=None, usb=None, mode=None, sensor_attached=None, sensor_value=None, sensor_rgbw=None, delta=None):
    msg = {
        "v": PROTOCOL_VERSION,
        "type": "state",
        "angle": angle,
        "pot": pot,
        "battery": battery,
        "attached": attached,
        "clock_ms": clock_ms,
    }
    if commanded_angle is not None:
        msg["commanded_angle"] = commanded_angle
    if world is not None:
        msg["world"] = world
    if is_recording is not None:
        msg["is_recording"] = is_recording
    if button is not None:
        msg["button"] = button
    if buttons is not None:
        msg["buttons"] = dict(buttons)
    if roll is not None:
        msg["roll"] = roll
    if pitch is not None:
        msg["pitch"] = pitch
    if power is not None:
        msg["power"] = bool(power)
    if usb is not None:
        msg["usb"] = bool(usb)
    if mode is not None:
        msg["mode"] = mode
    if sensor_attached is not None:
        msg["sensor_attached"] = bool(sensor_attached)
    if sensor_value is not None:
        msg["sensor_value"] = sensor_value
    if sensor_rgbw is not None:
        msg["sensor_rgbw"] = list(sensor_rgbw)
    if delta is not None:
        msg["delta"] = delta
    return msg


def log_message(t_us, text):
    return {"v": PROTOCOL_VERSION, "type": "log", "t": t_us, "text": text}


def trace_message(events):
    return {"v": PROTOCOL_VERSION, "type": "trace", "events": list(events)}


def exited_message(error):
    return {
        "v": PROTOCOL_VERSION,
        "type": "exited",
        "error": None if error is None else str(error),
    }


class UpdateCoalescer:
    def __init__(self, max_hz=30):
        self.min_interval_ms = int(round(1000 / max_hz))
        self.last_emit_ms = None
        self.pending = {}

    def push(self, message, *, now_ms):
        message = _versioned(message)
        message_type = message["type"]
        if message_type not in COALESCED_TYPES:
            return [message]
        if self.last_emit_ms is None or now_ms - self.last_emit_ms >= self.min_interval_ms:
            self.last_emit_ms = now_ms
            return [message]
        self.pending[message_type] = message
        return []

    def drain(self, *, now_ms):
        if self.last_emit_ms is not None and now_ms - self.last_emit_ms < self.min_interval_ms:
            return []
        emitted = []
        for message_type in ("frame", "state"):
            message = self.pending.get(message_type)
            if message is None:
                continue
            emitted.append(message)
            self.pending.pop(message_type, None)
        if emitted:
            self.last_emit_ms = now_ms
        return emitted


def _versioned(message):
    if message.get("v") == PROTOCOL_VERSION:
        return dict(message)
    return {"v": PROTOCOL_VERSION, **message}
