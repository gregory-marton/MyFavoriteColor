"""Command-line interface for SmartMotor emulator.

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import argparse
import os
import shutil
import sys

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
                self._ser = serial.Serial(self.port, 115200, timeout=0.1)
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
                    import json
                    parsed = json.loads(line)
                    res = {}
                    if "m" in parsed:
                        res["angle"] = float(parsed["m"])
                    if "s" in parsed:
                        res["pot"] = int(parsed["s"] * 40.95)
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


class HardwareServerSession:
    def __init__(self, bridge_inst):
        self.bridge = bridge_inst
        self.seq = 0

    def handle(self, raw):
        message = protocol.decode_client(raw)
        if message["type"] == "error":
            return [message]
        self.bridge.send_command(message)
        return [self.state_message()]

    def state_message(self):
        hw = self.bridge.poll_hardware()
        return protocol.state_message(
            angle=hw.get("angle", 0.0),
            pot=hw.get("pot", 2048),
            battery=4200,
            attached="Hardware (USB CDC)",
            clock_ms=0,
            commanded_angle=hw.get("angle", 0.0),
            world=None,
        )

    def frame_message(self):
        self.seq += 1
        return protocol.frame_message(self.seq, b"", ["Hardware Mode (CDC)"])


def bridge(port=None, host="127.0.0.1", web_port=8765):
    from smotoremu.server import websocket_process_request
    import asyncio
    import websockets

    hb = HardwareBridge(port=port)
    hb.ping()
    print(f"🔌 Hardware Bridge starting on {host}:{web_port} (connected to {hb.port or 'auto'})")

    async def handler(websocket):
        session = HardwareServerSession(hb)
        coalescer = protocol.UpdateCoalescer()
        try:
            await websocket.send(protocol.dumps(session.state_message()))
            await websocket.send(protocol.dumps(session.frame_message()))
            async for raw in websocket:
                now_ms = int(time.time() * 1000)
                for message in session.handle(raw):
                    for outbound in coalescer.push(message, now_ms=now_ms):
                        await websocket.send(protocol.dumps(outbound))
                for outbound in coalescer.drain(now_ms=now_ms):
                    await websocket.send(protocol.dumps(outbound))
        finally:
            pass

    async def heartbeat_loop():
        while True:
            hb.heartbeat()
            await asyncio.sleep(0.3)

    async def main_loop():
        asyncio.create_task(heartbeat_loop())
        async with websockets.serve(handler, host, web_port, process_request=websocket_process_request):
            await asyncio.Future()

    asyncio.run(main_loop())
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="smotor", description="SmartMotor CLI")
    subparsers = parser.add_subparsers(dest="command")

    # flash
    flash_p = subparsers.add_parser("flash", help="Erase virtual device flash")
    flash_p.add_argument("--vfs-dir", default=None, help="Custom VFS directory")

    # deploy
    deploy_p = subparsers.add_parser("deploy", help="Deploy manifest files to virtual device")
    deploy_p.add_argument("manifest", nargs="?", default="EngAI_MANIFEST.txt", help="Manifest file")
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
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
