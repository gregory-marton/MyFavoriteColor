"""Boot dispatch tests.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.session import Session


def write_module(tmp_path, name, source):
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    return path


def test_choose_activity_web_mode_ignores_i2c_devices(tmp_path, monkeypatch):
    results = _run_dispatch_program(
        tmp_path,
        monkeypatch,
        "assert main.choose_activity(1, [0x10]) == 'webconnect'\n",
    )

    assert results == ["ok"]


def test_choose_activity_favorite_color_when_color_sensor_present(tmp_path, monkeypatch):
    results = _run_dispatch_program(
        tmp_path,
        monkeypatch,
        "assert main.choose_activity(0, [0x10, 0x3c]) == 'myfavcolor'\n",
    )

    assert results == ["ok"]


def test_choose_activity_standalone_when_color_sensor_absent(tmp_path, monkeypatch):
    results = _run_dispatch_program(
        tmp_path,
        monkeypatch,
        "assert main.choose_activity(0, [0x3c]) == 'standalone'\n",
    )

    assert results == ["ok"]


def test_startup_chord_toggles_mode_to_web(tmp_path, monkeypatch):
    results = _run_dispatch_program(
        tmp_path,
        monkeypatch,
        "main.switch_down.value(0)\n"
        "main.switch_select.value(1)\n"
        "main.switch_up.value(0)\n"
        "main.prefs.mode = 0\n"
        "writes = []\n"
        "main.resetprefs = lambda mode: writes.append(mode)\n"
        "assert main.setmode() == 1\n"
        "assert writes == [1]\n",
    )

    assert results == ["ok"]


def _run_dispatch_program(tmp_path, monkeypatch, body):
    write_module(
        tmp_path,
        "dispatch_program",
        "import builtins\n"
        "def main():\n"
        "    import main\n"
        + "".join(f"    {line}" for line in body.splitlines(keepends=True))
        + "    builtins.DISPATCH_RESULTS.append('ok')\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    import builtins

    builtins.DISPATCH_RESULTS = []
    session = Session()
    session.boot("dispatch_program")
    session.run_until_idle()

    assert session.error is None
    return builtins.DISPATCH_RESULTS
