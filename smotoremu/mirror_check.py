"""End-to-end diagnostic for a running physical SmartMotor mirror.

Co-authored-by: GPT-5, Aug 2026
"""

import argparse
import asyncio
import json


async def collect(url, duration):
    import websockets

    frames = []
    orientations = []
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
                roll = message.get("roll")
                pitch = message.get("pitch")
                if roll is not None and pitch is not None:
                    orientations.append((float(roll), float(pitch)))
    return frames, orientations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--duration", type=float, default=5.0)
    args = parser.parse_args(argv)

    frames, orientations = asyncio.run(collect(args.url, args.duration))
    print(f"real OLED frames: {len(frames)}")
    if frames:
        print("latest OLED text:", " | ".join(frames[-1].get("lines", [])) or "<graphics only>")
    print(f"orientation samples: {len(orientations)}")
    if orientations:
        rolls = [sample[0] for sample in orientations]
        pitches = [sample[1] for sample in orientations]
        print(f"roll range: {min(rolls):.1f}..{max(rolls):.1f}")
        print(f"pitch range: {min(pitches):.1f}..{max(pitches):.1f}")

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
