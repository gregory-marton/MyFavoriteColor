"""Unit tests for smotor CLI commands (T034).

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import os
import pytest

from smotoremu import cli


def test_cli_flash_and_deploy(tmp_path):
    vfs_dir = tmp_path / "vfs"
    vfs_dir.mkdir()

    # Create dummy manifest and test files
    manifest_path = tmp_path / "EngAI_MANIFEST.txt"
    file1 = tmp_path / "test1.py"
    file1.write_text("print('hello')")
    file2 = tmp_path / "test2.py"
    file2.write_text("x = 42")
    manifest_path.write_text("test1.py\ntest2.py\nmissing.py\n")

    # Run CLI flash
    cli.main(["flash", "--vfs-dir", str(vfs_dir)])

    # Run CLI deploy
    exit_code = cli.main(["deploy", str(manifest_path), "--vfs-dir", str(vfs_dir)])
    assert exit_code == 0

    # Run CLI ls
    files = cli.list_vfs(str(vfs_dir))
    assert "test1.py" in files
    assert "test2.py" in files
    assert "missing.py" not in files

    # Run CLI cat
    content = cli.read_vfs_file("test1.py", str(vfs_dir))
    assert content == "print('hello')"


def test_cli_deploy_file_too_large_fails(tmp_path):
    vfs_dir = tmp_path / "vfs"
    vfs_dir.mkdir()

    manifest_path = tmp_path / "EngAI_MANIFEST.txt"
    huge_file = tmp_path / "huge.py"
    huge_file.write_bytes(b"A" * 60000)
    manifest_path.write_text("huge.py\n")

    exit_code = cli.main(["deploy", str(manifest_path), "--vfs-dir", str(vfs_dir)])
    assert exit_code != 0
