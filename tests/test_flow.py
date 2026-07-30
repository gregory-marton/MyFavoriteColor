import myfavcolor
from unittest.mock import MagicMock


def test_favorite_color_main_starts_bounded_training(monkeypatch):
    mock_sensor = MagicMock()
    mock_sensor.rgb = (100, 150, 200)
    monkeypatch.setattr(myfavcolor, 'sensor', mock_sensor)

    mock_sens = MagicMock()
    mock_sens.readpot.return_value = 2048
    monkeypatch.setattr(myfavcolor, 'sens', mock_sens)

    mock_switch = MagicMock()
    mock_switch.value.return_value = 1
    monkeypatch.setattr(myfavcolor, 'switch_up', mock_switch)

    started = []
    monkeypatch.setattr(myfavcolor.Environment, "__init__", lambda self, distance_metric: started.append(distance_metric))
    monkeypatch.setattr(myfavcolor, "learn", lambda env: started.append("learn"))
    monkeypatch.setattr(myfavcolor.time, "sleep", lambda x: None)
    monkeypatch.setattr(myfavcolor.time, 'ticks_ms', lambda: 0)
    monkeypatch.setattr(myfavcolor.time, 'ticks_diff', lambda a, b: 3000)

    myfavcolor.main()

    assert started == [myfavcolor.DISTANCE_METRIC, "learn"]
