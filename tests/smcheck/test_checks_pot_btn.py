"""D008: D-POT and D-BTN checks. Written before smcheck/checks/pot_btn.py exists.

Both need a human moving something in real time while sampling runs, so
sample_fn/prompt_fn are injected -- these tests exercise the analysis logic
against captured sample sequences, not a live sweep.

Buttons are active-low (myfavcolor.py: `if not switch_up.value(): ...`), so a
value of 0 means pressed.
"""

from smcheck.checks.pot_btn import check_d_btn, check_d_pot


def test_pot_passes_on_a_full_clean_sweep():
    # simulate a steady ramp 0 -> 4095 -> 0, like an unhurried full sweep.
    up = list(range(0, 4096, 64))
    down = list(range(4095, -1, -64))
    samples = up + down
    result = check_d_pot(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "pass"


def test_pot_fails_when_range_falls_short_of_full_travel():
    # never gets anywhere near either end -- e.g. a broken track or a worn wiper.
    samples = [1500 + (i % 50) for i in range(100)]
    result = check_d_pot(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "fail"
    assert "range" in result.summary.lower()


def test_pot_fails_when_reading_never_changes():
    samples = [2048] * 100
    result = check_d_pot(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "fail"
    assert "stuck" in result.summary.lower() or "not respond" in result.summary.lower()


def test_pot_warns_on_a_long_flat_plateau_in_the_middle():
    # covers full range but sits dead flat for a long stretch in between --
    # a possible dead zone, but human timing variance means this is a warn,
    # not an automatic fail.
    samples = list(range(0, 2000, 100)) + [2000] * 60 + list(range(2000, 4096, 100))
    result = check_d_pot(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "warn"


def test_pot_detail_carries_min_max_and_distinct_count():
    samples = list(range(0, 4096, 100))
    result = check_d_pot(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.detail["min"] == 0
    assert result.detail["max"] == 4000
    assert result.detail["distinct_values"] == len(samples)


def test_btn_passes_when_every_button_pressed_at_least_once():
    # (up, down, select) tuples over time; 0 = pressed (active-low).
    samples = [
        (1, 1, 1),
        (0, 1, 1),  # up pressed
        (1, 1, 1),
        (1, 0, 1),  # down pressed
        (1, 1, 1),
        (1, 1, 0),  # select pressed
        (1, 1, 1),
    ]
    result = check_d_btn(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "pass"


def test_btn_fails_naming_the_button_never_pressed():
    samples = [(1, 1, 1), (0, 1, 1), (1, 1, 1), (1, 1, 0), (1, 1, 1)]  # 'down' never goes to 0
    result = check_d_btn(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.status == "fail"
    assert "down" in result.summary.lower()


def test_btn_detail_carries_press_counts_per_button():
    samples = [(1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 1, 1), (1, 1, 1), (1, 1, 0)]
    result = check_d_btn(port=None, identity={}, sample_fn=lambda port, dur: samples, prompt_fn=lambda: None)
    assert result.detail["press_counts"]["up"] == 2
    assert result.detail["press_counts"]["select"] == 1
    assert result.detail["press_counts"]["down"] == 0
