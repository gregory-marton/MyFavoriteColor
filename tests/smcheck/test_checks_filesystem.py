"""D003: D-FS check. Written before smcheck/checks/filesystem.py exists.

Two independent failure modes in one check, per DEVICE_HEALTH_DESIGN.md
section 5: no space, or prefs.py won't actually persist a write. Device I/O
is injected so these run with no hardware.
"""

from smcheck.checks.filesystem import check_d_fs, DEFAULT_MIN_FREE_BYTES


def test_passes_with_ample_space_and_good_roundtrip():
    result = check_d_fs(
        port=None,
        identity={},
        statvfs_fn=lambda port: {"free_bytes": 2_000_000, "total_bytes": 2_097_152},
        prefs_roundtrip_fn=lambda port: (True, "restored ok"),
    )
    assert result.status == "pass"


def test_fails_when_free_space_below_threshold():
    result = check_d_fs(
        port=None,
        identity={},
        statvfs_fn=lambda port: {"free_bytes": 100, "total_bytes": 2_097_152},
        prefs_roundtrip_fn=lambda port: (True, "restored ok"),
        min_free_bytes=1000,
    )
    assert result.status == "fail"
    assert "space" in result.summary.lower()


def test_fails_when_prefs_roundtrip_fails():
    result = check_d_fs(
        port=None,
        identity={},
        statvfs_fn=lambda port: {"free_bytes": 2_000_000, "total_bytes": 2_097_152},
        prefs_roundtrip_fn=lambda port: (False, "readback did not match what was written"),
    )
    assert result.status == "fail"
    assert "prefs" in result.summary.lower() or "readback" in result.summary.lower()


def test_reports_both_failures_together():
    result = check_d_fs(
        port=None,
        identity={},
        statvfs_fn=lambda port: {"free_bytes": 0, "total_bytes": 2_097_152},
        prefs_roundtrip_fn=lambda port: (False, "write failed"),
        min_free_bytes=1000,
    )
    assert result.status == "fail"
    assert result.detail["free_bytes"] == 0
    assert result.detail["roundtrip_ok"] is False


def test_default_threshold_is_used_when_not_specified():
    # Sanity: the module exports a real default, not just accepting any kwarg.
    assert DEFAULT_MIN_FREE_BYTES > 0
