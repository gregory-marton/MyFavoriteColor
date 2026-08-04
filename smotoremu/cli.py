"""Command-line interface for SmartMotor emulator.

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import argparse
import os
import shutil
import sys

from smotoremu.vfs import VFS, FileTooLargeError

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
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
