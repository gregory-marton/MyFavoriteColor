import importlib

import machine


def test_runtime_modules_import_without_starting_activity_loops():
    for module_name in ("main", "myfavcolor", "standalone", "webconnect"):
        importlib.import_module(module_name)

    assert machine.state.timers == {}


def test_standalone_main_can_run_bounded(monkeypatch):
    standalone = importlib.import_module("standalone")

    monkeypatch.setattr(standalone, "readfile", lambda: [])
    monkeypatch.setattr(standalone, "savetofile", lambda points: None)
    monkeypatch.setattr(standalone, "cleardatafile", lambda: None)

    standalone.main(max_iterations=1)

    assert 0 in machine.state.timers
    assert 1 in machine.state.timers


def test_webconnect_main_can_run_bounded():
    webconnect = importlib.import_module("webconnect")

    webconnect.main(max_iterations=1)

    assert 0 in machine.state.timers
