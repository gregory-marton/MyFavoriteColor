"""Command-line interface for SmartMotor emulator.

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import argparse
import json
import os
import shutil
import sys
import time

from smotoremu.vfs import VFS, FileTooLargeError
from smotoremu import protocol

DEFAULT_SMOTOR_DIR = os.path.expanduser("~/.smotor/default")


def get_vfs_dir(custom_dir=None):
    if custom_dir:
        return custom_dir
    return os.environ.get("SMOTOR_DIR", DEFAULT_SMOTOR_DIR)


def flash(vfs_dir=None):
    target = get_vfs_dir(vfs_dir)
    if os.path.exists(target):
        shutil.rmtree(target)
    os.makedirs(target, exist_ok=True)
    with open(os.path.join(target, ".firmware"), "w", encoding="utf-8") as h:
        h.write("ESP32_GENERIC_C3-20250415-v1.25.0\n")
    return 0


def get_max_file_bytes():
    if VFS.MAX_FILE_BYTES is None:
        from smotoremu.vfs import _read_manifest_size_limit
        VFS.MAX_FILE_BYTES = _read_manifest_size_limit()
    return VFS.MAX_FILE_BYTES


def deploy(manifest_path="EngAI_MANIFEST.txt", vfs_dir=None):
    target = get_vfs_dir(vfs_dir)
    os.makedirs(target, exist_ok=True)

    if not os.path.isfile(manifest_path):
        print(f"❌ Error: {manifest_path} not found!", file=sys.stderr)
        return 1

    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))

    with open(manifest_path, "r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]

    max_bytes = get_max_file_bytes()
    copied = 0
    for filename in lines:
        src = os.path.join(manifest_dir, filename) if not os.path.isabs(filename) else filename
        if not os.path.isfile(src):
            print(f"   ⚠️ Warning: {filename} not found locally, skipping.")
            continue

        size = os.path.getsize(src)
        if size > max_bytes:
            print(f"❌ Error: {filename} exceeds file size limit ({size} > {max_bytes} bytes)", file=sys.stderr)
            return 1

        dst = os.path.join(target, filename)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    print(f"✅ Deployment complete! Copied {copied} file(s) to virtual device.")
    return 0


def list_vfs(vfs_dir=None):
    target = get_vfs_dir(vfs_dir)
    if not os.path.exists(target):
        return []
    res = []
    for root, _, files in os.walk(target):
        for name in files:
            if name == ".firmware":
                continue
            rel = os.path.relpath(os.path.join(root, name), target)
            res.append(rel)
    return sorted(res)


def read_vfs_file(filename, vfs_dir=None):
    target = get_vfs_dir(vfs_dir)
    filepath = os.path.join(target, filename)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"file not found in virtual device: {filename}")
    with open(filepath, "r", encoding="utf-8") as handle:
        return handle.read()


def find_serial_port(custom_port=None):
    if custom_port:
        return custom_port
    import glob
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if ports:
        return ports[0]
    try:
        import serial.tools.list_ports as list_ports
        candidates = [p.device for p in list_ports.comports() if p.vid == 0x303A or "usbmodem" in p.device]
        if candidates:
            return candidates[0]
    except Exception:
        pass
    return None


class HardwareBridge:
    def __init__(self, port=None, link=None):
        self.port = find_serial_port(port)
        self.link = link
        self._ser = None
        if self.link is None and self.port:
            try:
                import serial
                self._ser = serial.Serial(self.port, 115200, timeout=0.5)
            except Exception:
                self._ser = None

    def ping(self):
        if self._ser is not None:
            self._ser.write(b'{"st":"e"}\n')
            self._ser.flush()
        elif self.link is not None and hasattr(self.link, "write"):
            self.link.write(b'{"st":"e"}\n')

    def heartbeat(self):
        self.ping()

    def poll_hardware(self):
        if self.link is not None and hasattr(self.link, "read_state"):
            return self.link.read_state()
        if self._ser is not None:
            self.ping()
            line = self._ser.readline().decode(errors="ignore").strip()
            if line.startswith("{"):
                try:
                    import json, math
                    parsed = json.loads(line)
                    res = {}
                    if "m" in parsed:
                        res["angle"] = float(parsed["m"])
                    if "pot" in parsed:
                        res["pot"] = int(parsed["pot"])
                    elif "s" in parsed:
                        res["pot"] = int(parsed["s"] * 40.95)

                    if "bat" in parsed:
                        res["battery"] = int(parsed["bat"])
                    elif "battery" in parsed:
                        res["battery"] = int(parsed["battery"])

                    if "attached" in parsed:
                        res["attached"] = parsed["attached"]
                    elif "s" in parsed:
                        res["attached"] = "GROVE_LIGHT"

                    if parsed.get("btn_u") == 0:
                        res["button"] = "up"
                    elif parsed.get("btn_d") == 0:
                        res["button"] = "down"
                    elif parsed.get("btn_s") == 0:
                        res["button"] = "select"

                    if "ax" in parsed and "ay" in parsed and "az" in parsed:
                        ax, ay, az = float(parsed["ax"]), float(parsed["ay"]), float(parsed["az"])
                        res["roll"] = math.degrees(math.atan2(ay, az)) if (ay or az) else 0.0
                        res["pitch"] = math.degrees(math.atan2(-ax, math.sqrt(ay*ay + az*az))) if (ax or ay or az) else 0.0
                    return res
                except Exception:
                    pass
        return {"angle": 0.0, "pot": 2048, "button": None}

    def send_command(self, msg):
        import json
        payload = {"st": "e"}
        if isinstance(msg, dict):
            if "angle" in msg:
                payload["m"] = int(msg["angle"])
            elif msg.get("type") in {"press", "release"}:
                payload["m"] = 90
            elif msg.get("type") == "set_pot":
                payload["m"] = int(msg.get("raw", 2048) / 40.95)

        data = (json.dumps(payload) + "\n").encode()
        if self._ser is not None:
            self._ser.write(data)
            self._ser.flush()
        elif self.link is not None:
            if hasattr(self.link, "write"):
                self.link.write(data)
            elif hasattr(self.link, "send"):
                self.link.send(data.decode())


DEFAULT_REC_STATE = os.path.expanduser("~/.smotor/recording_state.json")
DEFAULT_REC_DIR = os.path.expanduser("~/.smotor/recordings")


class HardwareServerSession:
    def __init__(self, bridge_inst, state_file=None, rec_dir=None):
        self.bridge = bridge_inst
        self.seq = 0
        self.state_file = state_file or DEFAULT_REC_STATE
        self.rec_dir = rec_dir or DEFAULT_REC_DIR
        os.makedirs(self.rec_dir, exist_ok=True)

        self.is_recording = False
        self.current_rec_path = None
        self._load_recording_state()

    def _load_recording_state(self):
        if os.path.isfile(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as h:
                    data = json.load(h)
                    self.is_recording = data.get("is_recording", False)
                    self.current_rec_path = data.get("current_rec_path", None)
            except Exception:
                pass

    def _save_recording_state(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.state_file)), exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as h:
            json.dump({
                "is_recording": self.is_recording,
                "current_rec_path": self.current_rec_path,
            }, h)

    def record_event(self, event):
        if not self.is_recording or not self.current_rec_path:
            return
        entry = {"t_ms": int(time.time() * 1000), **event}
        with open(self.current_rec_path, "a", encoding="utf-8") as h:
            h.write(json.dumps(entry) + "\n")

    def handle(self, raw):
        message = protocol.decode_client(raw)
        if message["type"] == "error":
            return [message]
        if message["type"] == "record":
            want_rec = bool(message.get("recording", False))
            if want_rec and not self.is_recording:
                import time as t_mod
                timestamp = int(t_mod.time())
                self.current_rec_path = os.path.join(self.rec_dir, f"recording_{timestamp}.jsonl")
                self.is_recording = True
                self._save_recording_state()
            elif not want_rec and self.is_recording:
                self.is_recording = False
                self.current_rec_path = None
                self._save_recording_state()
            return [self.state_message()]

        self.bridge.send_command(message)
        self.record_event({"kind": message["type"], "detail": message})
        return [self.state_message()]

    def state_message(self):
        hw = self.bridge.poll_hardware()
        if self.is_recording:
            self.record_event({"kind": "hardware_poll", "detail": hw})
        return protocol.state_message(
            angle=hw.get("angle", 0.0),
            pot=hw.get("pot", 2048),
            battery=hw.get("battery", 4200),
            attached=hw.get("attached", "Hardware (USB CDC)"),
            clock_ms=0,
            commanded_angle=hw.get("angle", 0.0),
            world=None,
            is_recording=self.is_recording,
            button=hw.get("button"),
            roll=hw.get("roll"),
            pitch=hw.get("pitch"),
        )

    def frame_message(self):
        self.seq += 1
        return protocol.frame_message(self.seq, b"", ["Hardware Mode (CDC)"])


async def bridge_handler(websocket, hb, poll_interval=0.3):
    """Handle a single WebSocket connection to the hardware bridge.

    Runs two concurrent tasks:
    - poll_loop: periodically reads hardware state and pushes to browser
    - recv_loop: reads browser messages and forwards commands to device

    Extracted as a module-level function so it can be tested without
    starting a real WebSocket server.
    """
    import asyncio

    session = HardwareServerSession(hb)
    coalescer = protocol.UpdateCoalescer()

    # Send initial state + frame
    await websocket.send(protocol.dumps(session.state_message()))
    await websocket.send(protocol.dumps(session.frame_message()))

    async def poll_loop():
        """Continuously poll hardware and push state to browser."""
        while True:
            await asyncio.sleep(poll_interval)
            now_ms = int(time.time() * 1000)
            state = session.state_message()
            for outbound in coalescer.push(state, now_ms=now_ms):
                await websocket.send(protocol.dumps(outbound))
            for outbound in coalescer.drain(now_ms=now_ms):
                await websocket.send(protocol.dumps(outbound))

    async def recv_loop():
        """Read client messages and forward commands to device."""
        async for raw in websocket:
            now_ms = int(time.time() * 1000)
            for message in session.handle(raw):
                for outbound in coalescer.push(message, now_ms=now_ms):
                    await websocket.send(protocol.dumps(outbound))
            for outbound in coalescer.drain(now_ms=now_ms):
                await websocket.send(protocol.dumps(outbound))

    poll_task = asyncio.create_task(poll_loop())
    try:
        await recv_loop()
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


def bridge(port=None, host="127.0.0.1", web_port=8765):
    from smotoremu.server import websocket_process_request
    import asyncio
    import websockets

    hb = HardwareBridge(port=port)
    hb.ping()
    print(f"🔌 Hardware Bridge starting on {host}:{web_port} (connected to {hb.port or 'auto'})")

    async def handler(websocket):
        await bridge_handler(websocket, hb)

    async def main_loop():
        async with websockets.serve(handler, host, web_port, process_request=websocket_process_request):
            await asyncio.Future()

    asyncio.run(main_loop())
    return 0

def reset_hardware(port=None):
    serial_port = find_serial_port(port)
    if not serial_port:
        print("❌ No physical serial port found.", file=sys.stderr)
        return 1
    try:
        import serial
        print(f"⚡ Deinitializing hardware timers and resetting MicroPython on {serial_port}...")
        s = serial.Serial(serial_port, 115200, timeout=0.5)
        s.write(b"\x03\x03import machine; machine.Timer(0).deinit(); machine.reset()\r\n")
        time.sleep(1.5)
        s.close()
        time.sleep(1.0)
        print("✅ Hardware reset complete.")
        return 0
    except Exception as exc:
        print(f"❌ Error resetting hardware: {exc}", file=sys.stderr)
        return 1


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="smotor", description="SmartMotor emulator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # flash
    flash_p = subparsers.add_parser("flash", help="Flash default files into virtual device")
    flash_p.add_argument("--vfs-dir", default=None, help="Custom VFS directory")

    # deploy
    deploy_p = subparsers.add_parser("deploy", help="Deploy manifest files into virtual device")
    deploy_p.add_argument("manifest", nargs="?", default="EngAI_MANIFEST.txt", help="Manifest path")
    deploy_p.add_argument("--vfs-dir", default=None, help="Custom VFS directory")

    # ls
    ls_p = subparsers.add_parser("ls", help="List files in virtual device")
    ls_p.add_argument("--vfs-dir", default=None, help="Custom VFS directory")

    # cat
    cat_p = subparsers.add_parser("cat", help="Print contents of a virtual device file")
    cat_p.add_argument("filename", help="File name to read")
    cat_p.add_argument("--vfs-dir", default=None, help="Custom VFS directory")

    # run
    run_p = subparsers.add_parser("run", help="Run entry script on virtual device")
    run_p.add_argument("entry", nargs="?", default="main", help="Entry module name")
    run_p.add_argument("--vfs-dir", default=None, help="Custom VFS directory")

    # serve
    serve_p = subparsers.add_parser("serve", help="Run WebSocket server for virtual device")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8765)

    # bridge
    bridge_p = subparsers.add_parser("bridge", help="Bridge physical SmartMotor to Web UI")
    bridge_p.add_argument("--port", default=None, help="Serial port (e.g. /dev/cu.usbmodem2101)")
    bridge_p.add_argument("--host", default="127.0.0.1")
    bridge_p.add_argument("--web-port", type=int, default=8765)

    # reset
    reset_p = subparsers.add_parser("reset", help="Reset physical SmartMotor serial connection")
    reset_p.add_argument("--port", default=None, help="Serial port (e.g. /dev/cu.usbmodem1101)")

    args = parser.parse_args(argv)

    if args.command == "flash":
        return flash(args.vfs_dir)
    elif args.command == "deploy":
        return deploy(args.manifest, args.vfs_dir)
    elif args.command == "ls":
        for f in list_vfs(args.vfs_dir):
            print(f)
        return 0
    elif args.command == "cat":
        try:
            print(read_vfs_file(args.filename, args.vfs_dir), end="")
            return 0
        except FileNotFoundError as exc:
            print(f"❌ Error: {exc}", file=sys.stderr)
            return 1
    elif args.command == "run":
        from smotoremu.session import Session
        target = get_vfs_dir(args.vfs_dir)
        session = Session(vfs_dir=target)
        session.boot(args.entry)
        session.run_until_idle(timeout_s=5)
        if session.error:
            print(f"❌ Error running {args.entry}: {session.error}", file=sys.stderr)
            return 1
        return 0
    elif args.command == "serve":
        from smotoremu.server import serve
        import asyncio
        asyncio.run(serve(host=args.host, port=args.port))
        return 0
    elif args.command == "bridge":
        return bridge(port=args.port, host=args.host, web_port=args.web_port)
    elif args.command == "reset":
        return reset_hardware(port=args.port)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
