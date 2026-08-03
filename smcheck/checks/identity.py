"""D002: D-ID and D-FW.

D-ID is bookkeeping, not a verdict -- it always passes and just carries the
identity fields into the report so the fleet store has something to key on.

D-FW is the real check: this session found a real board running firmware that
matched neither the working tree nor any recent commit. It hashes each file in
EngAI_MANIFEST.txt on-device (sha256, computed on-device so we never need to
pull full file contents over the ~11 kB/s link measured in
spikes/S4_hostlink/FINDINGS.md) and compares against the same files' hashes in
the local working tree -- the same "expected" that `deploy.sh` uses.
"""

import hashlib
import os
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MANIFEST_PATH = os.path.join(REPO_ROOT, "EngAI_MANIFEST.txt")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

_HASH_SNIPPET_TEMPLATE = """
import uhashlib, ubinascii
files = %r
for f in files:
    try:
        h = uhashlib.sha256()
        with open(f, 'rb') as fh:
            while True:
                chunk = fh.read(512)
                if not chunk:
                    break
                h.update(chunk)
        print('HASH', f, ubinascii.hexlify(h.digest()).decode())
    except OSError:
        print('MISSING', f)
"""


def check_d_id(port, identity):
    summary = f"uid {identity.get('uid', '?')}  freq {identity.get('freq', '?')}"
    return CheckResult(id="D-ID", status="pass", summary=summary, detail=dict(identity))


def default_manifest():
    with open(MANIFEST_PATH) as f:
        return [line.strip() for line in f if line.strip()]


def fetch_device_hashes(port, manifest):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", _HASH_SNIPPET_TEMPLATE % (manifest,)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("mpremote failed:\n" + (out.stderr or out.stdout))
    hashes = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "HASH":
            hashes[parts[1]] = parts[2]
    return hashes


def _local_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def check_d_fw(port, identity, manifest=None, local_dir=None, device_hashes_fn=None):
    manifest = manifest if manifest is not None else default_manifest()
    local_dir = local_dir if local_dir is not None else REPO_ROOT
    device_hashes_fn = device_hashes_fn or fetch_device_hashes

    device_hashes = device_hashes_fn(port, manifest)

    missing = []
    mismatched = []
    for name in manifest:
        local_path = os.path.join(str(local_dir), name)
        if not os.path.exists(local_path):
            continue  # not our problem to report -- deploy.sh already warns about this
        local_hash = _local_sha256(local_path)
        device_hash = device_hashes.get(name)
        if device_hash is None:
            missing.append(name)
        elif device_hash != local_hash:
            mismatched.append(name)

    detail = {"missing": missing, "mismatched": mismatched}
    if missing or mismatched:
        parts = []
        if mismatched:
            parts.append(f"mismatched: {', '.join(mismatched)}")
        if missing:
            parts.append(f"missing on device: {', '.join(missing)}")
        return CheckResult(id="D-FW", status="fail", summary="; ".join(parts), detail=detail)
    return CheckResult(id="D-FW", status="pass", summary="device files match the manifest", detail=detail)
