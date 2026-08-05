"""Tests for physical mirror acceptance reporting.

Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

from smotoremu import mirror_check


def test_summarize_states_tracks_each_physical_control():
    states = [
        {
            "roll": 1.0,
            "pitch": 2.0,
            "pot": 1000,
            "angle": 30.0,
            "buttons": {"up": False, "down": False, "select": False},
        },
        {
            "roll": 5.0,
            "pitch": -3.0,
            "pot": 2200,
            "angle": 75.0,
            "buttons": {"up": True, "down": False, "select": False},
        },
    ]

    summary = mirror_check.summarize_states(states)

    assert summary["orientations"] == [(1.0, 2.0), (5.0, -3.0)]
    assert summary["pots"] == [1000, 2200]
    assert summary["angles"] == [30.0, 75.0]
    assert summary["buttons"] == [
        ("down", False),
        ("select", False),
        ("up", False),
        ("down", False),
        ("select", False),
        ("up", True),
    ]
