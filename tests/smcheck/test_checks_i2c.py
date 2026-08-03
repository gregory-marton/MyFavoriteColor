"""D005: D-I2C check. Written before smcheck/checks/i2c.py exists.

Confirmed on real hardware (unit-3): scan returns [0x3c, 0x53] -- OLED and
ADXL345, no color sensor attached. OLED absence is a hard fail (the display
is definitely broken); ADXL345 absence is only a warn, because HANDOFF.md
still lists "is the ADXL345 fitted on every board?" as an open question --
sensors.py itself tolerates its absence. A scan that raises (bus stuck low)
is also a hard fail, distinct from a clean scan with missing addresses.
"""

from smcheck.checks.i2c import check_d_i2c


def test_passes_when_oled_and_accel_both_present():
    result = check_d_i2c(port=None, identity={}, scan_fn=lambda port: [0x3C, 0x53])
    assert result.status == "pass"


def test_fails_when_oled_missing():
    result = check_d_i2c(port=None, identity={}, scan_fn=lambda port: [0x53])
    assert result.status == "fail"
    assert "0x3c" in result.summary.lower() or "oled" in result.summary.lower()


def test_warns_when_accel_missing_but_oled_present():
    result = check_d_i2c(port=None, identity={}, scan_fn=lambda port: [0x3C])
    assert result.status == "warn"


def test_extra_address_is_a_warn_not_a_fail():
    # e.g. a color sensor plugged into the I2C port -- not a fault.
    result = check_d_i2c(port=None, identity={}, scan_fn=lambda port: [0x3C, 0x53, 0x10])
    assert result.status == "warn"
    assert result.detail["unexpected"] == [0x10]


def test_scan_exception_is_a_hard_fail():
    def raising_scan(port):
        raise RuntimeError("bus stuck low")

    result = check_d_i2c(port=None, identity={}, scan_fn=raising_scan)
    assert result.status == "fail"
    assert "stuck" in result.summary.lower() or "bus" in result.summary.lower()


def test_detail_lists_found_missing_and_unexpected():
    result = check_d_i2c(port=None, identity={}, scan_fn=lambda port: [0x3C, 0x10])
    assert result.detail["found"] == [0x3C, 0x10]
    assert result.detail["missing"] == [0x53]
    assert result.detail["unexpected"] == [0x10]
