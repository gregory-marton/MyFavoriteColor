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
import re

from smotoremu.device_env import load_real_ssd1306
from smotoremu.machine_shim import Pin, SoftI2C

BOOT_GAP_MS = 2000  # inserted between boots; not a measurement, just visual separation
ON_USB_CHARGING_THRESHOLD = 2850  # matches sensors.readbattery()'s 'charging' bucket


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

        elif line.startswith("SUSTAIN_SAMPLE "):
            m = re.search(
                r"t=(\d+) pot=(\d+) batt_raw=(\d+) batt_uv=(\d+) "
                r"accel=([\-\d]+|None),([\-\d]+|None),([\-\d]+|None)",
                line,
            )
            if m:
                t = int(m.group(1))
                last_t_in_boot = max(last_t_in_boot, t)
                batt_raw = int(m.group(3))
                accel = None if m.group(5) == "None" else (
                    int(m.group(5)), int(m.group(6)), int(m.group(7))
                )
                events.append({
                    "type": "SUSTAIN_SAMPLE",
                    "t": boot_offset + t,
                    "pot": int(m.group(2)),
                    "batt_raw": batt_raw,
                    "batt_uv": int(m.group(4)),
                    "accel": accel,
                    "on_usb": batt_raw > ON_USB_CHARGING_THRESHOLD,
                })

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
