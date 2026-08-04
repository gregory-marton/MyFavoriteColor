"""T013 session and device-code runner tests.

Co-authored-by: GPT-5, Aug 2026
"""

import builtins

from smotoremu.i2c import I2CDevice
from smotoremu.session import Session


def write_module(tmp_path, name, source):
    path = tmp_path / f"{name}.py"
    path.write_text(source)
    return path


def test_trivial_injected_module_sets_pin_and_completes(tmp_path, monkeypatch):
    write_module(
        tmp_path,
        "pin_program",
        "from machine import Pin\n"
        "def main():\n"
        "    Pin(5, Pin.OUT).value(1)\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("pin_program")
    session.run_until_idle()

    assert session.exited
    assert session.error is None
    assert session.board.pin_value(5) == 1


def test_boot_main_without_color_sensor_dispatches_to_standalone(tmp_path, monkeypatch):
    builtins.SESSION_MARKERS = []
    write_module(tmp_path, "standalone", "import builtins\ndef main():\n    builtins.SESSION_MARKERS.append('standalone')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("main")
    session.run_until_idle()

    assert builtins.SESSION_MARKERS == ["standalone"]
    assert session.error is None


def test_boot_main_with_color_sensor_dispatches_to_myfavcolor(tmp_path, monkeypatch):
    builtins.SESSION_MARKERS = []
    write_module(tmp_path, "myfavcolor", "import builtins\ndef main():\n    builtins.SESSION_MARKERS.append('myfavcolor')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()
    session.bus.register(0x10, I2CDevice())

    session.boot("main")
    session.run_until_idle()

    assert builtins.SESSION_MARKERS == ["myfavcolor"]
    assert session.error is None


def test_exception_in_device_code_is_captured_not_raised(tmp_path, monkeypatch):
    write_module(tmp_path, "bad_program", "def main():\n    raise RuntimeError('boom')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("bad_program")
    session.run_until_idle()

    assert isinstance(session.error, RuntimeError)
    assert str(session.error) == "boom"


def test_sys_exit_in_device_code_sets_exited_cleanly(tmp_path, monkeypatch):
    write_module(tmp_path, "exit_program", "import sys\ndef main():\n    sys.exit(7)\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("exit_program")
    session.run_until_idle()

    assert session.exited
    assert session.error is None


def test_two_sessions_do_not_leak_main_or_activity_modules(tmp_path, monkeypatch):
    builtins.SESSION_MARKERS = []
    write_module(tmp_path, "standalone", "import builtins\ndef main():\n    builtins.SESSION_MARKERS.append('standalone')\n")
    write_module(tmp_path, "myfavcolor", "import builtins\ndef main():\n    builtins.SESSION_MARKERS.append('myfavcolor')\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    first = Session()
    first.boot("main")
    first.run_until_idle()

    second = Session()
    second.bus.register(0x10, I2CDevice())
    second.boot("main")
    second.run_until_idle()

    assert builtins.SESSION_MARKERS == ["standalone", "myfavcolor"]
    assert first.error is None
    assert second.error is None
