"""D003: D-FS -- free flash space and a prefs.py write/read/restore round-trip.

Two independent failure modes: the filesystem might be nearly full (flash
wear, leftover files from a benchmark spike), or writes might silently not
persist. The round-trip writes a marker into prefs.py, reads it back, then
restores the original content exactly -- verified on real hardware
(unit-3, 2026-08-03) to leave the file byte-identical afterward.
"""

import os
import subprocess

from smcheck.report import CheckResult

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
MPREMOTE = os.path.join(REPO_ROOT, ".venv", "bin", "mpremote")

# A class set doing normal work fits comfortably well under this; it's meant
# to catch "nearly out of space", not to be a precise capacity model.
DEFAULT_MIN_FREE_BYTES = 50_000

_STATVFS_SNIPPET = "import os; s = os.statvfs('/'); print('STATVFS', s[0] * s[3], s[0] * s[2])"

_ROUNDTRIP_SNIPPET = """
try:
    with open('prefs.py') as f:
        original = f.read()
except OSError:
    original = None
marker = '# smcheck-roundtrip-test\\n'
test_content = (original + marker) if original is not None else marker
ok = True
try:
    with open('prefs.py', 'w') as f:
        f.write(test_content)
    with open('prefs.py') as f:
        readback = f.read()
    ok = (readback == test_content)
finally:
    if original is not None:
        with open('prefs.py', 'w') as f:
            f.write(original)
    else:
        import os
        try:
            os.remove('prefs.py')
        except OSError:
            pass
print('ROUNDTRIP', 'OK' if ok else 'FAIL')
"""


def _run(port, snippet):
    cmd = [MPREMOTE]
    if port:
        cmd += ["connect", port]
    cmd += ["exec", snippet]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError("mpremote failed:\n" + (out.stderr or out.stdout))
    return out.stdout


def real_statvfs(port):
    out = _run(port, _STATVFS_SNIPPET)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "STATVFS":
            return {"free_bytes": int(parts[1]), "total_bytes": int(parts[2])}
    raise RuntimeError(f"unexpected statvfs output:\n{out}")


def real_prefs_roundtrip(port):
    out = _run(port, _ROUNDTRIP_SNIPPET)
    ok = "ROUNDTRIP OK" in out
    detail = "restored ok" if ok else f"unexpected output:\n{out}"
    return ok, detail


def check_d_fs(port, identity, statvfs_fn=None, prefs_roundtrip_fn=None, min_free_bytes=DEFAULT_MIN_FREE_BYTES):
    statvfs_fn = statvfs_fn or real_statvfs
    prefs_roundtrip_fn = prefs_roundtrip_fn or real_prefs_roundtrip

    space = statvfs_fn(port)
    roundtrip_ok, roundtrip_detail = prefs_roundtrip_fn(port)

    problems = []
    if space["free_bytes"] < min_free_bytes:
        problems.append(f"low space ({space['free_bytes']} bytes free)")
    if not roundtrip_ok:
        problems.append(f"prefs.py readback failed ({roundtrip_detail})")

    detail = {
        "free_bytes": space["free_bytes"],
        "total_bytes": space["total_bytes"],
        "roundtrip_ok": roundtrip_ok,
    }

    if problems:
        return CheckResult(id="D-FS", status="fail", summary="; ".join(problems), detail=detail)
    return CheckResult(
        id="D-FS",
        status="pass",
        summary=f"{space['free_bytes']} / {space['total_bytes']} bytes free, prefs.py round-trip ok",
        detail=detail,
    )
