"""Health-check prompt/verdict logic — pure, no hardware imports.

Ported from tests/spikes/test_guided_logic.py as part of graduating
spikes/S7_guided into ./healthcheck.py.

Co-authored-by: Claude Sonnet 5, Aug 2026
"""

from healthcheck_logic import (
    accel_magnitude,
    compute_battery_verdict,
    compute_white_balance_milli,
    detect_button_press,
    evaluate_accel_motion,
    evaluate_button_prompt,
    format_full_sample_line,
    percentile,
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


def test_percentile_of_empty_is_none():
    assert percentile([], 0.10) is None


def test_percentile_ten_picks_near_the_low_end():
    # nearest-rank on a sorted 0..9 list at the 10th percentile
    assert percentile(list(range(10)), 0.10) == 0


def test_percentile_does_not_require_presorted_input():
    assert percentile([30, 10, 20], 0.0) == 10
    assert percentile([30, 10, 20], 1.0) == 30


def test_battery_verdict_reports_insufficient_data_with_no_loaded_samples():
    result = compute_battery_verdict(rest_uv=2_100_000, loaded_samples_uv=[])

    assert result["verdict"] == "insufficient data"


def test_battery_verdict_flags_low_rest_voltage():
    # 1.70 V at the pin * the assumed x2 divider = 3.40 V at the cell,
    # below DEVICE_HEALTH_DESIGN.md's 'half'/'low' boundary.
    result = compute_battery_verdict(
        rest_uv=1_700_000,
        loaded_samples_uv=[1_650_000] * 20,
    )

    assert result["verdict"] == "check battery -- low rest voltage"
    assert result["provisional"] is True


def test_battery_verdict_flags_high_sag_under_sustained_load():
    # Healthy-looking rest voltage but the loaded 10th percentile has
    # dropped hundreds of mV -- consistent with a worn cell under load
    # (DEVICE_HEALTH_DESIGN.md sec 3.2).
    rest_uv = 2_080_000  # ~4.16 V at the cell, matches the golden-unit baseline
    loaded = [rest_uv - 250_000] * 18 + [rest_uv] * 2  # p10 stays near the sagged value
    result = compute_battery_verdict(rest_uv=rest_uv, loaded_samples_uv=loaded)

    assert result["verdict"] == "check battery -- high sag under sustained load"
    assert result["sag_cell_mv"] > 400


def test_battery_verdict_reports_likely_healthy_for_golden_unit_like_readings():
    # Modeled on DEVICE_HEALTH_DESIGN.md sec 1's golden-unit reading: ~2.084 V
    # at the pin, tiny sample-to-sample spread, negligible sag under load.
    rest_uv = 2_084_000
    loaded = [rest_uv - 20_000, rest_uv - 15_000, rest_uv - 10_000] * 5
    result = compute_battery_verdict(rest_uv=rest_uv, loaded_samples_uv=loaded)

    assert result["verdict"] == "likely healthy"
    assert result["sag_cell_mv"] < 150


def test_format_full_sample_line_is_stable_and_greppable():
    line = format_full_sample_line(
        t_ms=1234,
        pot=2048,
        batt_raw=2894,
        batt_uv=2079000,
        accel=(-9, 1, -253),
        port_mode="alg",
        sensor_attached=True,
        sensor_value=1500,
        buttons=(1, 1, 0),
        servo_angle=90,
    )

    assert line.startswith("FULL_SAMPLE t=1234 ")
    assert "pot=2048" in line
    assert "batt_raw=2894" in line
    assert "batt_uv=2079000" in line
    assert "accel=-9,1,-253" in line
    assert "port=alg" in line
    assert "sensor_attached=1" in line
    assert "sensor=1500" in line
    assert "btn=1,1,0" in line
    assert "angle=90" in line


def test_format_full_sample_line_handles_missing_accel_and_sensor():
    line = format_full_sample_line(
        t_ms=1,
        pot=0,
        batt_raw=0,
        batt_uv=0,
        accel=None,
        port_mode="i2c",
        sensor_attached=False,
        sensor_value=None,
        buttons=(1, 1, 1),
        servo_angle=0,
    )

    assert "accel=None,None,None" in line
    assert "sensor_attached=0" in line
    assert "sensor=None" in line
