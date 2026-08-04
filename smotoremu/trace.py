"""Parses guided_log.txt (from spikes/S7_guided/guided_test_device.py) into
one global, chronologically-ordered event timeline for replay.

Each boot's own time.ticks_ms() resets near zero on reboot, so raw device
timestamps are not comparable across a reset. Timestamps here are offset per
boot so the whole session is one increasing timeline -- real elapsed time
across a reboot (especially the OFF/ON stage, where a human took some
unknown real-world time to flip the switch) isn't known, so a fixed gap is
inserted rather than claimed as measured.
"""

import base64
import math
import re

from smotoremu.device_env import load_real_ssd1306
from smotoremu.machine_shim import Pin, SoftI2C

BOOT_GAP_MS = 2000  # inserted between boots; not a measurement, just visual separation
ON_USB_CHARGING_THRESHOLD = 2850  # matches sensors.readbattery()'s 'charging' bucket


def orientation_from_accel(accel):
    if accel is None:
        return None
    x, y, z = accel
    roll = math.atan2(y, z) * 57.3
    pitch = math.atan2(-x, math.sqrt(y * y + z * z)) * 57.3
    return {"roll": round(roll, 1), "pitch": round(pitch, 1)}


def _parse_sample_line(line, event_type, boot_offset):
    m = re.search(
        r"t=(\d+) pot=(\d+) batt_raw=(\d+) batt_uv=(\d+) "
        r"accel=([\-\d]+|None),([\-\d]+|None),([\-\d]+|None)",
        line,
    )
    if not m:
        return None
    batt_raw = int(m.group(3))
    accel = None if m.group(5) == "None" else (
        int(m.group(5)), int(m.group(6)), int(m.group(7))
    )
    batt_uv = int(m.group(4))
    return {
        "type": event_type,
        "t": boot_offset + int(m.group(1)),
        "pot": int(m.group(2)),
        "batt_raw": batt_raw,
        "batt_uv": batt_uv,
        "battery_v": batt_uv / 1e6,
        "accel": accel,
        "orientation": orientation_from_accel(accel),
        "on_usb": batt_raw > ON_USB_CHARGING_THRESHOLD,
    }


def _parse_accel_sample(line, boot_offset):
    m = re.search(r"stage=(\w+) t=(\d+) accel=([\-\d]+),([\-\d]+),([\-\d]+) mag=(\d+)", line)
    if not m:
        return None
    accel = (int(m.group(3)), int(m.group(4)), int(m.group(5)))
    return {
        "type": "ACCEL_SAMPLE",
        "t": boot_offset + int(m.group(2)),
        "stage": m.group(1),
        "accel": accel,
        "magnitude": int(m.group(6)),
        "orientation": orientation_from_accel(accel),
    }


def _parse_accel_summary(line, boot_offset, last_t_in_boot):
    m = re.search(
        r"stage=(\w+) status=(\w+) n=(\d+) span=([\-\d]+) mag=([\d.]+) summary=(.*)",
        line,
    )
    if not m:
        return None
    return {
        "type": "ACCEL_SUMMARY",
        "t": boot_offset + last_t_in_boot,
        "stage": m.group(1),
        "status": m.group(2),
        "n_samples": int(m.group(3)),
        "max_axis_span": int(m.group(4)),
        "median_magnitude": float(m.group(5)),
        "summary": m.group(6),
    }


def _parse_color_white_sample(line, boot_offset):
    m = re.search(r"t=(\d+) r=(\d+) g=(\d+) b=(\d+) w=(\d+)", line)
    if not m:
        return None
    return {
        "type": "COLOR_WHITE_SAMPLE",
        "t": boot_offset + int(m.group(1)),
        "rgbw": (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))),
    }


def _parse_color_white_summary(line, boot_offset, last_t_in_boot):
    m = re.search(
        r"n=(\d+) r=(\d+) g=(\d+) b=(\d+) w=(\d+) wb_milli=(\d+),(\d+),(\d+)",
        line,
    )
    if not m:
        return None
    return {
        "type": "COLOR_WHITE_SUMMARY",
        "t": boot_offset + last_t_in_boot,
        "n_samples": int(m.group(1)),
        "rgbw": (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))),
        "white_balance_milli": (int(m.group(6)), int(m.group(7)), int(m.group(8))),
    }


def _parse_light_summary(line, boot_offset, last_t_in_boot):
    m = re.search(r"stage=(\w+) n=(\d+) min=(\d+|None) max=(\d+|None) mean=(\d+|None)", line)
    if not m:
        return None

    def maybe_int(value):
        return None if value == "None" else int(value)

    return {
        "type": "LIGHT_SUMMARY",
        "t": boot_offset + last_t_in_boot,
        "stage": m.group(1),
        "n_samples": int(m.group(2)),
        "min": maybe_int(m.group(3)),
        "max": maybe_int(m.group(4)),
        "mean": maybe_int(m.group(5)),
    }


def parse_guided_log(text):
    events = []
    boot_offset = 0
    last_t_in_boot = 0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("BOOT "):
            m = re.search(r"boot_num=(\d+) reset_cause=(\d+)\((\w+)\) resume_stage=(\d+)", line)
            if not m:
                continue
            if events:  # not the first boot -- advance the global offset
                boot_offset += last_t_in_boot + BOOT_GAP_MS
                last_t_in_boot = 0
            events.append({
                "type": "BOOT",
                "t": boot_offset,
                "boot_num": int(m.group(1)),
                "reset_cause": int(m.group(2)),
                "reset_cause_name": m.group(3),
                "resume_stage": int(m.group(4)),
            })

        elif line.startswith("SCREEN "):
            m = re.search(r"t=(\d+) lines=(.*)", line)
            if m:
                t = int(m.group(1))
                last_t_in_boot = max(last_t_in_boot, t)
                events.append({"type": "SCREEN", "t": boot_offset + t, "lines": m.group(2).split("|")})

        elif line.startswith("SERVO "):
            m = re.search(r"t=(\d+) angle=(\d+)", line)
            if m:
                t = int(m.group(1))
                last_t_in_boot = max(last_t_in_boot, t)
                events.append({"type": "SERVO", "t": boot_offset + t, "angle": int(m.group(2))})

        elif line.startswith("START_SAMPLE ") or line.startswith("SUSTAIN_SAMPLE "):
            event_type = "START_SAMPLE" if line.startswith("START_SAMPLE ") else "SUSTAIN_SAMPLE"
            event = _parse_sample_line(line, event_type, boot_offset)
            if event is not None:
                t = event["t"] - boot_offset
                last_t_in_boot = max(last_t_in_boot, t)
                events.append(event)

        elif line.startswith("ACCEL_SAMPLE "):
            event = _parse_accel_sample(line, boot_offset)
            if event is not None:
                last_t_in_boot = max(last_t_in_boot, event["t"] - boot_offset)
                events.append(event)

        elif line.startswith("ACCEL_SUMMARY "):
            event = _parse_accel_summary(line, boot_offset, last_t_in_boot)
            if event is not None:
                events.append(event)

        elif line.startswith("COLOR_WHITE_SAMPLE "):
            event = _parse_color_white_sample(line, boot_offset)
            if event is not None:
                last_t_in_boot = max(last_t_in_boot, event["t"] - boot_offset)
                events.append(event)

        elif line.startswith("COLOR_WHITE_SUMMARY "):
            event = _parse_color_white_summary(line, boot_offset, last_t_in_boot)
            if event is not None:
                events.append(event)

        elif line.startswith("LIGHT_SUMMARY "):
            event = _parse_light_summary(line, boot_offset, last_t_in_boot)
            if event is not None:
                events.append(event)

        elif line.startswith("REP "):
            m = re.search(r"stage=(\w+)", line)
            if m:
                events.append({"type": "REP", "t": boot_offset + last_t_in_boot, "stage": m.group(1)})

        elif line.startswith("STAGE_DONE "):
            m = re.search(r"stage=(\w+)", line)
            if m:
                events.append({"type": "STAGE_DONE", "t": boot_offset + last_t_in_boot, "stage": m.group(1)})

        elif line.startswith("TIMEOUT "):
            m = re.search(r"stage=(\w+)", line)
            if m:
                events.append({"type": "TIMEOUT", "t": boot_offset + last_t_in_boot, "stage": m.group(1)})

    return events


def render_screens(events):
    """Adds a base64-encoded 128x64 MONO_VLSB buffer to each SCREEN event,
    drawn through the real ssd1306.py driver -- same layout as
    spikes/S7_guided/guided_test_device.py's Display.show()."""
    ssd1306 = load_real_ssd1306()
    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    display = ssd1306.SSD1306_I2C(128, 64, i2c)

    rendered = []
    for event in events:
        if event["type"] != "SCREEN":
            rendered.append(event)
            continue
        display.fill(0)
        for row, text in enumerate(event["lines"]):
            display.text(text, 4, 8 + row * 12, 1)
        display.show()
        new_event = dict(event)
        new_event["screen_buffer_b64"] = base64.b64encode(bytes(display.buffer)).decode()
        rendered.append(new_event)
    return rendered
