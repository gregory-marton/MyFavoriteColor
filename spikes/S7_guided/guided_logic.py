"""Pure helper logic for the S7 guided hardware test.

Co-authored-by: GPT-5, Aug 2026
"""

BUTTON_NAMES = ("UP", "DOWN", "SELECT")
EXPECTED_1G_LSB = 256


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
