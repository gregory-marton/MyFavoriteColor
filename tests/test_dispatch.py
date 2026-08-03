import importlib

import machine


def test_choose_activity_web_mode_ignores_i2c_devices():
    main = importlib.import_module("main")

    assert main.choose_activity(1, [0x10]) == "webconnect"


def test_choose_activity_favorite_color_when_color_sensor_present():
    main = importlib.import_module("main")

    assert main.choose_activity(0, [0x10, 0x3c]) == "myfavcolor"


def test_choose_activity_standalone_when_color_sensor_absent():
    main = importlib.import_module("main")

    assert main.choose_activity(0, [0x3c]) == "standalone"


def test_startup_chord_toggles_mode_to_web(monkeypatch):
    main = importlib.import_module("main")
    machine.state.pins[8] = 0
    machine.state.pins[9] = 1
    machine.state.pins[10] = 0
    monkeypatch.setattr(main.prefs, "mode", 0)
    writes = []
    monkeypatch.setattr(main, "resetprefs", lambda mode: writes.append(mode))

    assert main.setmode() == 1
    assert writes == [1]
