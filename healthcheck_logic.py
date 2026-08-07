"""Pure helper logic for healthcheck.py -- no hardware imports, importable
on the host (for tests) and on-device (MicroPython, no stdlib beyond what
ships in the firmware).

Graduated from spikes/S7_guided/guided_logic.py.

Co-authored-by: GPT-5, Aug 2026
Co-authored-by: Claude Sonnet 5, Aug 2026
"""

BUTTON_NAMES = ("UP", "DOWN", "SELECT")
EXPECTED_1G_LSB = 256

# Assumed resistor divider between the cell and the battery ADC pin.
# GUESS: needs bench data (DEVICE_HEALTH_DESIGN.md B001) -- inferred from
# 2.084 V at the pin on a known-good, fully-charged unit (2.084 * 2 = 4.17 V,
# a healthy 1S LiPo). Matches spikes/S5_battery/probe_battery.py.
DIVIDER_RATIO = 2.0

# DEVICE_HEALTH_DESIGN.md sec 1's translation table (raw ADC -> pin volts ->
# cell volts), applied here in calibrated cell volts rather than raw counts
# -- that substitution is the whole point of defect 5 / B002.
REST_CELL_LOW_V = 3.60  # 'half'/'low' boundary
REST_CELL_BORDERLINE_V = 3.89  # 'full' boundary

# Sag under the healthcheck's sustained servo-sweep load. Not milliohms --
# no current measurement exists yet (B001/B003 unresolved) -- just a
# provisional voltage-drop flag for human triage, per sec 3.2/3.6.
# GUESS: needs bench data across a fleet (B005) to become a real threshold.
SAG_CELL_BORDERLINE_MV = 150
SAG_CELL_HIGH_MV = 400


def detect_button_press(previous, current, names=BUTTON_NAMES):
    """Return the button name for the first active-low press edge."""
    for name, before, after in zip(names, previous, current):
        if before == 1 and after == 0:
            return name
    return None


def evaluate_button_prompt(expected, observed):
    if observed == expected:
        status = "match"
    else:
        status = "mismatch"
    return {"status": status, "expected": expected, "observed": observed}


def accel_magnitude(sample):
    x, y, z = sample
    return (x * x + y * y + z * z) ** 0.5


def evaluate_accel_motion(samples, mode, expected_1g=EXPECTED_1G_LSB):
    if not samples:
        return {"status": "fail", "summary": "no accelerometer samples"}

    mags = [accel_magnitude(s) for s in samples]
    median_mag = sorted(mags)[len(mags) // 2]
    ranges = [max(axis) - min(axis) for axis in zip(*samples)]
    span = max(ranges)
    detail = {
        "n_samples": len(samples),
        "median_magnitude": round(median_mag, 1),
        "max_axis_span": span,
    }

    low = expected_1g * 0.75
    high = expected_1g * 1.35
    if mode == "flat":
        if not (low <= median_mag <= high):
            return {"status": "warn", "summary": "flat reading is not near 1g", "detail": detail}
        if span > 80:
            return {"status": "warn", "summary": "flat surface still shows large motion", "detail": detail}
        return {"status": "pass", "summary": "flat reading is stable and near 1g", "detail": detail}

    if mode == "figure8":
        if span < 80:
            return {"status": "warn", "summary": "figure-8 motion was too small to calibrate", "detail": detail}
        return {"status": "pass", "summary": "figure-8 motion covered multiple axes", "detail": detail}

    return {"status": "fail", "summary": "unknown accelerometer mode", "detail": detail}


def compute_white_balance_milli(rgb):
    reference = max(1, max(rgb))
    return tuple(int(round(reference * 1000 / max(1, channel))) for channel in rgb)


def summarize_scalar_samples(samples):
    if not samples:
        return {"n_samples": 0, "min": None, "max": None, "mean": None}
    return {
        "n_samples": len(samples),
        "min": min(samples),
        "max": max(samples),
        "mean": int(round(sum(samples) / len(samples))),
    }


def percentile(values, pct):
    """Nearest-rank percentile, no numpy (must run on-device too)."""
    if not values:
        return None
    ordered = sorted(values)
    index = int(pct * (len(ordered) - 1))
    return ordered[index]


def compute_battery_verdict(rest_uv, loaded_samples_uv, divider_ratio=DIVIDER_RATIO):
    """Provisional battery triage from one healthcheck run.

    rest_uv: calibrated microvolts at the ADC pin, sampled right after the
    disconnect prompt confirms USB is off (DISCONNECT_PROMPT stage).
    loaded_samples_uv: calibrated microvolt samples collected during the
    SUSTAIN stage, while the servo sweeps continuously -- the sustained-load
    analogue of DEVICE_HEALTH_DESIGN.md sec 3.2's load step.

    Deliberately not a calibrated instrument: the divider ratio (B001) and
    fleet sag envelope (B005) are both still unconfirmed per that doc, so
    every verdict carries `provisional: True` and its raw evidence.
    """
    if rest_uv is None or not loaded_samples_uv:
        return {"verdict": "insufficient data", "provisional": True}

    rest_cell_v = (rest_uv / 1e6) * divider_ratio
    loaded_p10_uv = percentile(loaded_samples_uv, 0.10)
    loaded_p10_cell_v = (loaded_p10_uv / 1e6) * divider_ratio
    sag_cell_mv = (rest_cell_v - loaded_p10_cell_v) * 1000

    if rest_cell_v < REST_CELL_LOW_V:
        verdict = "check battery -- low rest voltage"
    elif sag_cell_mv > SAG_CELL_HIGH_MV:
        verdict = "check battery -- high sag under sustained load"
    elif rest_cell_v < REST_CELL_BORDERLINE_V or sag_cell_mv > SAG_CELL_BORDERLINE_MV:
        verdict = "borderline -- worth a second look"
    else:
        verdict = "likely healthy"

    return {
        "verdict": verdict,
        "rest_cell_v": round(rest_cell_v, 3),
        "loaded_p10_cell_v": round(loaded_p10_cell_v, 3),
        "sag_cell_mv": round(sag_cell_mv, 1),
        "divider_ratio": divider_ratio,
        "provisional": True,
    }


def format_full_sample_line(t_ms, pot, batt_raw, batt_uv, accel, port_mode,
                             sensor_attached, sensor_value, buttons, servo_angle):
    """One line, every control/sensor/servo/voltage reading at this tick.

    Superset of the old SUSTAIN_SAMPLE line (pot, battery, accel) plus port
    mode, the attached sensor's value, button states, and servo angle --
    the full-state capture DEVICE_HEALTH_DESIGN.md sec 6 needs to feed a
    replay/distribution pipeline later. Plain-text, greppable, in the same
    style as every other healthcheck.py log line.
    """
    ax, ay, az = accel if accel is not None else (None, None, None)
    bu, bd, bs = buttons if buttons is not None else (None, None, None)
    return (
        "FULL_SAMPLE t=%d pot=%d batt_raw=%d batt_uv=%d accel=%s,%s,%s "
        "port=%s sensor_attached=%d sensor=%s btn=%s,%s,%s angle=%d"
        % (
            t_ms, pot, batt_raw, batt_uv, ax, ay, az,
            port_mode, int(sensor_attached), sensor_value,
            bu, bd, bs, servo_angle,
        )
    )
