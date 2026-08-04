"""Guided hardware-test prompt logic.

Co-authored-by: GPT-5, Aug 2026
"""

from spikes.S7_guided.guided_logic import (
    accel_magnitude,
    compute_white_balance_milli,
    detect_button_press,
    evaluate_accel_motion,
    evaluate_button_prompt,
    summarize_scalar_samples,
)


def test_detect_button_press_names_the_active_low_edge():
    assert detect_button_press((1, 1, 1), (1, 0, 1)) == "DOWN"


def test_up_prompt_does_not_treat_down_as_a_clean_up_press():
    result = evaluate_button_prompt("UP", "DOWN")

    assert result["status"] == "mismatch"
    assert result["expected"] == "UP"
    assert result["observed"] == "DOWN"


def test_down_prompt_can_be_checked_explicitly():
    result = evaluate_button_prompt("DOWN", "DOWN")

    assert result["status"] == "match"
    assert result["expected"] == "DOWN"
    assert result["observed"] == "DOWN"


def test_accel_magnitude_reports_lsb_gravity_size():
    assert round(accel_magnitude((-9, 1, -253)), 1) == 253.2


def test_flat_accel_window_passes_near_1g_with_low_motion():
    samples = [(-9, 1, -253), (-10, 2, -254), (-8, 1, -252)]
    result = evaluate_accel_motion(samples, mode="flat")

    assert result["status"] == "pass"


def test_figure8_accel_window_warns_when_motion_is_too_small():
    samples = [(-9, 1, -253), (-10, 2, -254), (-8, 1, -252)]
    result = evaluate_accel_motion(samples, mode="figure8")

    assert result["status"] == "warn"
    assert "motion" in result["summary"].lower()


def test_white_balance_milli_uses_brightest_channel_as_reference():
    assert compute_white_balance_milli((100, 50, 25)) == (1000, 2000, 4000)


def test_scalar_sample_summary_records_min_max_and_mean():
    summary = summarize_scalar_samples([10, 20, 30])

    assert summary == {"n_samples": 3, "min": 10, "max": 30, "mean": 20}
