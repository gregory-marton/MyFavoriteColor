"""End-to-end diagnostic for a running physical SmartMotor mirror.

Co-authored-by: GPT-5, Aug 2026
Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import argparse
import asyncio
import json


async def collect(url, duration):
    import websockets

    frames = []
    states = []
    async with websockets.connect(url) as websocket:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + duration
        while loop.time() < deadline:
            try:
                raw = await asyncio.wait_for(websocket.recv(), deadline - loop.time())
            except asyncio.TimeoutError:
                break
            message = json.loads(raw)
            if message.get("type") == "frame" and message.get("png"):
                frames.append(message)
            if message.get("type") == "state":
                states.append(message)
    return frames, states


def summarize_states(states):
    orientations = []
    pots = []
    angles = []
    buttons = []
    for state in states:
        roll = state.get("roll")
        pitch = state.get("pitch")
        if roll is not None and pitch is not None:
            orientations.append((float(roll), float(pitch)))
        if state.get("pot") is not None:
            pots.append(int(state["pot"]))
        if state.get("angle") is not None:
            angles.append(float(state["angle"]))
        for name, pressed in sorted(state.get("buttons", {}).items()):
            buttons.append((name, bool(pressed)))
    return {
        "orientations": orientations,
        "pots": pots,
        "angles": angles,
        "buttons": buttons,
        "modes": [state["mode"] for state in states if state.get("mode")],
        "sensor_values": [
            int(state["sensor_value"])
            for state in states
            if state.get("sensor_value") is not None and int(state["sensor_value"]) >= 0
        ],
        "sensor_rgbw": [
            list(state["sensor_rgbw"])
            for state in states
            if state.get("sensor_rgbw") is not None
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--duration", type=float, default=5.0)
    args = parser.parse_args(argv)

    frames, states = asyncio.run(collect(args.url, args.duration))
    summary = summarize_states(states)
    orientations = summary["orientations"]
    print(f"real OLED frames: {len(frames)}")
    if frames:
        print("latest OLED text:", " | ".join(frames[-1].get("lines", [])) or "<graphics only>")
    print(f"orientation samples: {len(orientations)}")
    if orientations:
        rolls = [sample[0] for sample in orientations]
        pitches = [sample[1] for sample in orientations]
        print(f"roll range: {min(rolls):.1f}..{max(rolls):.1f}")
        print(f"pitch range: {min(pitches):.1f}..{max(pitches):.1f}")

    pots = summary["pots"]
    print(f"pot samples: {len(pots)}")
    if pots:
        print(f"pot range: {min(pots)}..{max(pots)}")

    angles = summary["angles"]
    print(f"arm angle samples: {len(angles)}")
    if angles:
        print(f"arm angle range: {min(angles):.1f}..{max(angles):.1f}")

    button_samples = summary["buttons"]
    pressed = sorted({name for name, is_pressed in button_samples if is_pressed})
    print(f"button samples: {len(button_samples)}")
    print("buttons seen pressed:", ", ".join(pressed) if pressed else "<none>")

    modes = sorted(set(summary["modes"]))
    print("sensor port modes:", ", ".join(modes) if modes else "<none>")
    sensor_values = summary["sensor_values"]
    print(f"sensor value samples: {len(sensor_values)}")
    if sensor_values:
        print(f"sensor value range: {min(sensor_values)}..{max(sensor_values)}")
    if summary["sensor_rgbw"]:
        print("latest sensor RGBW:", ", ".join(str(v) for v in summary["sensor_rgbw"][-1]))

    moved = len({(round(roll, 1), round(pitch, 1)) for roll, pitch in orientations}) >= 2
    if not frames:
        print("FAIL: no physical OLED framebuffer received")
        return 1
    if not moved:
        print("FAIL: no changing accelerometer orientation received")
        return 1
    print("PASS: live physical OLED and motion are both mirrored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
