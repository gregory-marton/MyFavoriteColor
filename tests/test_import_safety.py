"""Import and bounded-run safety tests on the emulator shim path.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.session import Session


def write_module(tmp_path, name, source):
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    return path


def test_runtime_modules_import_without_starting_activity_loops(tmp_path, monkeypatch):
    write_module(
        tmp_path,
        "import_safety_program",
        "def main():\n"
        "    import main, myfavcolor, standalone, webconnect\n"
        "    assert main.choose_activity(0, []) == 'standalone'\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("import_safety_program")
    session.run_until_idle()

    assert session.error is None
    assert session.board.timer_handles == {}


def test_standalone_main_can_run_bounded(tmp_path, monkeypatch):
    write_module(
        tmp_path,
        "standalone_bounded_program",
        "def main():\n"
        "    import standalone\n"
        "    standalone.readfile = lambda: []\n"
        "    standalone.savetofile = lambda points: None\n"
        "    standalone.cleardatafile = lambda: None\n"
        "    standalone.main(max_iterations=1)\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("standalone_bounded_program")
    session.run_until_idle()

    assert session.error is None
    assert 0 in session.board.timer_handles
    assert 1 in session.board.timer_handles


def test_webconnect_main_can_run_bounded(tmp_path, monkeypatch):
    write_module(
        tmp_path,
        "webconnect_bounded_program",
        "def main():\n"
        "    open('trainData.txt', 'w').close()\n"
        "    import webconnect\n"
        "    webconnect.main(max_iterations=1)\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("webconnect_bounded_program")
    session.run_until_idle()

    assert session.error is None
    assert 0 in session.board.timer_handles
