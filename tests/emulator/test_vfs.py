"""T014 virtual filesystem tests.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.session import Session
from smotoremu.vfs import FileTooLargeError, VFS


def write_module(tmp_path, name, source):
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    return path


def test_vfs_put_get_listdir_and_wipe(tmp_path):
    vfs = VFS(tmp_path / "flash")

    vfs.put("hello.txt", "hello")

    assert vfs.get("hello.txt") == b"hello"
    assert vfs.listdir() == ["hello.txt"]

    vfs.wipe()
    assert vfs.listdir() == []


def test_vfs_rejects_oversized_file(tmp_path):
    vfs = VFS(tmp_path / "flash")

    try:
        vfs.put("too_big.py", b"x" * (vfs.MAX_FILE_BYTES + 1))
    except FileTooLargeError as exc:
        assert "too_big.py" in str(exc)
    else:
        raise AssertionError("expected FileTooLargeError")


def test_session_vfs_supports_real_files_savetofile_and_readfile(tmp_path, monkeypatch):
    flash = tmp_path / "flash"
    write_module(
        tmp_path,
        "write_data_program",
        "from files import savetofile, readfile\n"
        "def main():\n"
        "    savetofile([[1, 2]])\n"
        "    assert readfile() == [[[1, 2]]]\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session(vfs_dir=flash)

    session.boot("write_data_program")
    session.run_until_idle()

    assert session.error is None
    assert session.vfs.get("data.py") == b"points=[[[1, 2]]]\r\n"


def test_session_vfs_resetprefs_reimport_sees_new_mode(tmp_path, monkeypatch):
    flash = tmp_path / "flash"
    write_module(
        tmp_path,
        "prefs_program",
        "from files import resetprefs\n"
        "def main():\n"
        "    resetprefs(1)\n"
        "    import prefs\n"
        "    assert prefs.mode == 1\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session(vfs_dir=flash)

    session.boot("prefs_program")
    session.run_until_idle()

    assert session.error is None
    assert session.vfs.get("prefs.py") == b"mode=1\r\n"


def test_session_vfs_chroots_device_listdir(tmp_path, monkeypatch):
    flash = tmp_path / "flash"
    sentinel = tmp_path / "host_sentinel.txt"
    sentinel.write_text("host")
    write_module(
        tmp_path,
        "listdir_program",
        "import os\n"
        "def main():\n"
        "    open('seen.txt', 'w').write(str(os.listdir()))\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session(vfs_dir=flash)
    session.vfs.put("flash_file.txt", "flash")

    session.boot("listdir_program")
    session.run_until_idle()

    assert session.error is None
    seen = session.vfs.get("seen.txt").decode()
    assert "flash_file.txt" in seen
    assert "host_sentinel.txt" not in seen
