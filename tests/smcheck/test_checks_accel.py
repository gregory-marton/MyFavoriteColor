"""D007: D-ACC check. Written before smcheck/checks/accel.py exists.

Gravity's magnitude is ~1g in ANY orientation, so this needs no known
orientation and no human cooperation -- the cheapest strong check in the
catalogue. Confirmed on real hardware (unit-3): resting magnitude ~254 LSB,
matching the ADXL345's documented ~256 LSB/g at its default +/-2g, 10-bit
range. A second failure mode: a stuck I2C read (or a halted sensor) can
report a plausible-looking constant forever -- caught by requiring some
sample-to-sample variance, not just a magnitude in range.
"""

from smcheck.checks.accel import check_d_acc


def test_passes_near_1g_with_normal_sensor_noise():
    samples = [(-9, 1, -253), (-9, 1, -255), (-9, 0, -254), (-9, 2, -254), (-10, 1, -255)]
    result = check_d_acc(port=None, identity={}, read_samples_fn=lambda port, n: samples)
    assert result.status == "pass"


def test_fails_when_magnitude_far_from_1g():
    # e.g. a badly miscalibrated or damaged sensor -- half the expected magnitude,
    # with realistic sample-to-sample noise (not the "stuck" case).
    samples = [(-4, 0, -127), (-4, 1, -126), (-3, 0, -128), (-4, 0, -125), (-5, 1, -127)]
    result = check_d_acc(
        port=None, identity={}, read_samples_fn=lambda port, n: samples, expected_magnitude=254
    )
    assert result.status == "fail"
    assert "magnitude" in result.summary.lower()


def test_fails_when_all_samples_are_byte_identical():
    # a stuck read reports a plausible-looking constant forever.
    samples = [(-9, 1, -254)] * 5
    result = check_d_acc(port=None, identity={}, read_samples_fn=lambda port, n: samples, expected_magnitude=254)
    assert result.status == "fail"
    assert "stuck" in result.summary.lower()


def test_detail_carries_median_magnitude_and_sample_count():
    samples = [(-9, 1, -253), (-9, 1, -255), (-9, 0, -254)]
    result = check_d_acc(port=None, identity={}, read_samples_fn=lambda port, n: samples)
    assert result.detail["n_samples"] == 3
    assert 250 < result.detail["median_magnitude"] < 260
