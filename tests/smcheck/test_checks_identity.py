"""D002: D-ID and D-FW checks. Written before smcheck/checks/identity.py exists.

D-ID is pure bookkeeping (always pass -- it's the fleet key, not a verdict).
D-FW is the real one: compares on-device file hashes against the manifest's
local files, and fails on any mismatch or missing/extra file. This is the
check motivated by finding, this session, that a real board's on-device code
did not match the working tree or any recent commit.
"""

from smcheck.checks.identity import check_d_fw, check_d_id


def test_d_id_always_passes_and_carries_identity_detail():
    identity = {"uid": "abc123", "implementation": "(1, 25, 0)", "freq": "160000000"}

    result = check_d_id(port=None, identity=identity)

    assert result.id == "D-ID"
    assert result.status == "pass"
    assert "abc123" in result.summary
    assert result.detail["uid"] == "abc123"


def test_d_fw_passes_when_hashes_match_manifest(tmp_path):
    local_files = {"main.py": "print('hi')\n"}
    device_hashes = {"main.py": _sha256_hex(local_files["main.py"])}

    result = check_d_fw(
        port=None,
        identity={},
        manifest=["main.py"],
        local_dir=_write_files(tmp_path, local_files),
        device_hashes_fn=lambda port, manifest: device_hashes,
    )

    assert result.status == "pass"


def test_d_fw_fails_on_hash_mismatch(tmp_path):
    local_files = {"main.py": "print('hi')\n"}
    device_hashes = {"main.py": "0000000000000000000000000000000000000000000000000000000000000"}

    result = check_d_fw(
        port=None,
        identity={},
        manifest=["main.py"],
        local_dir=_write_files(tmp_path, local_files),
        device_hashes_fn=lambda port, manifest: device_hashes,
    )

    assert result.status == "fail"
    assert "main.py" in result.summary
    assert result.detail["mismatched"] == ["main.py"]


def test_d_fw_fails_on_missing_device_file(tmp_path):
    local_files = {"main.py": "print('hi')\n", "sensors.py": "x = 1\n"}
    device_hashes = {"main.py": _sha256_hex(local_files["main.py"])}  # sensors.py absent

    result = check_d_fw(
        port=None,
        identity={},
        manifest=["main.py", "sensors.py"],
        local_dir=_write_files(tmp_path, local_files),
        device_hashes_fn=lambda port, manifest: device_hashes,
    )

    assert result.status == "fail"
    assert result.detail["missing"] == ["sensors.py"]


def test_d_fw_passes_with_no_mismatches_and_no_missing(tmp_path):
    local_files = {"a.py": "1\n", "b.py": "2\n"}
    device_hashes = {k: _sha256_hex(v) for k, v in local_files.items()}

    result = check_d_fw(
        port=None,
        identity={},
        manifest=["a.py", "b.py"],
        local_dir=_write_files(tmp_path, local_files),
        device_hashes_fn=lambda port, manifest: device_hashes,
    )

    assert result.status == "pass"
    assert result.detail["mismatched"] == []
    assert result.detail["missing"] == []


def _sha256_hex(text):
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def _write_files(tmp_path, files):
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    return tmp_path
