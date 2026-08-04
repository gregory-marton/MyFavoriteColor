"""Integration tests for deploy.sh with PORT=emu (T035).

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import os
import subprocess
import pytest

from smotoremu import cli

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_deploy_sh_with_port_emu(tmp_path):
    vfs_dir = tmp_path / "vfs"
    vfs_dir.mkdir()

    env = dict(os.environ)
    env["PORT"] = "emu"
    env["SMOTOR_DIR"] = str(vfs_dir)

    script_path = os.path.join(REPO_ROOT, "deploy.sh")
    result = subprocess.run(["bash", script_path], cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0

    files = cli.list_vfs(str(vfs_dir))
    with open(os.path.join(REPO_ROOT, "EngAI_MANIFEST.txt"), "r") as h:
        manifest_files = sorted([line.strip() for line in h if line.strip()])

    assert files == manifest_files
