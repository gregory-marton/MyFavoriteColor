"""SmartMotor on-device health check.

Graduated from spikes/S7_guided/guided_test_device.py. The OLED walks you
through exercising every control and logs what it sees, so a fleet of
devices can be triaged without a bench full of equipment.

Reachable two ways, both through the same marker file (STATE_PATH): the
three-finger salute (UP+DOWN+SELECT) at boot (main.py), or
healthcheck_host.py remote-starting a unit by writing the marker and
resetting the board.

Two deliberate reboots: REBOOT_FOR_SENSOR_SWAP (mid-sequence, to swap the
light sensor for the color sensor) and OFFON (final, D-RST + battery sag
check). Each persists progress to STATE_PATH and returns; the next boot
resumes. After OFFON, run_wait_retrieval() shows the verdict + a live
readout indefinitely -- ends only via retrieval (healthcheck_host.py) or
losing power, never self-resets (an earlier bounded/self-resetting version
was confirmed on the bench as an unwanted, unexplained reboot).

Every control-exercise stage has a timeout (STAGE_TIMEOUT_MS) so a broken
control can't hang the sequence forever. run_wait_retrieval() is the
deliberate exception -- see its docstring.

Co-authored-by: GPT-5, Aug 2026
Co-authored-by: Claude Sonnet 5, Aug 2026
"""

import collections
import time
import machine
from machine import Pin, ADC, SoftI2C
import ssd1306
import servo
import mirror

from healthcheck_logic import (
    BUTTON_NAMES,
    STAGES,
    compute_battery_verdict,
    compute_white_balance_milli,
    detect_button_press,
    evaluate_accel_motion,
    format_full_sample_line,
    percentile,
)

LOG_PATH = "healthcheck_log.txt"
STATE_PATH = "healthcheck_state.txt"

# Only SELECT/UP/DOWN still count discrete reps automatically -- they're
# the raw hardware ground-truth check. POT/FLIP/LIGHT switched to
# human-confirmed stages (SELECT="done"/UP-DOWN="can't"), since automatic
# threshold detection proved unreliable on the bench; "at least 3x" for
# those is now an instruction in the prompt text, not an enforced count.
TARGET_REPS = {
    "SELECT": 3, "UP": 3, "DOWN": 3,
    "OFFON": 1,
}
STAGE_TIMEOUT_MS = {
    # Generous, not rushed -- a broken control still gets caught, it's just not timed out on.
    "SCREEN_CHECK": 60000,
    "DISCONNECT_PROMPT": 180000,
    "ENSURE_ANALOG": 60000,
    "POT": 180000, "SELECT": 90000, "UP": 90000, "DOWN": 90000,
    "SERVO_CHECK": 60000,
    "ACCEL_FLAT1": 20000, "ACCEL_FIG8": 40000, "ACCEL_FLAT2": 20000,
    "LIGHT": 90000,
    "FLIP": 180000,
    "COLOR_WHITE": 60000,
    "SUSTAIN": 90000,
    "OFFON": 60000,
}

# Which physical pin is "up" vs "down" disagrees across this codebase
# itself (main.py/standalone.py/myfavcolor.py use one mapping,
# webconnect.py/smcheck/this file use the other) -- not settled, so this
# isn't a "fix", just the raw pin per button, logged with every observed
# press for a future calibration pass.
ButtonPins = collections.namedtuple("ButtonPins", ("UP", "DN", "SL"))
BUTTON_PIN_NUMBERS = ButtonPins(10, 8, 9)

FULL_SAMPLE_PERIOD_MS = 500
# run_wait_retrieval's screen alternates verdict/telemetry, weighted mostly
# telemetry (~10% verdict) per bench feedback that 50/50 felt too verdict-heavy.
VERDICT_DWELL_MS = 1500
TELEMETRY_DWELL_MS = 13500
VEML6040_ADDR = 0x10
VEML6040_R = 0x08
VEML6040_G = 0x09
VEML6040_B = 0x0A
VEML6040_W = 0x0B

# LIGHT stage: adaptive light<->dark<->light detection -- a "low"/"high"
# extreme is within this margin of the min/max seen so far this stage
# (no fixed absolute threshold, since ambient light varies bench to bench).
LIGHT_MARGIN_MIN = 50
LIGHT_MARGIN_FRAC = 0.15
LIGHT_MIN_USEFUL_SPAN = 200
LIGHT_TARGET_REPS = 3

# Same three patterns as smcheck/checks/oled.py's D-OLED (border-crosshair
# caught a real display defect on unit-3 a bus scan missed entirely).
SCREEN_CHECK_PATTERNS = ("full-white", "full-dark", "border-crosshair")


def _log(f, line):
    f.write(line + "\n")
    f.flush()


def _read_state():
    """Returns (stage_idx, rest_uv, loaded_p10_uv). Missing/corrupt -> fresh start."""
    try:
        with open(STATE_PATH) as f:
            parts = f.read().strip().split("|")
        stage_idx = int(parts[0])
        rest_uv = int(parts[1]) if len(parts) > 1 and parts[1] != "None" else None
        loaded_p10_uv = int(parts[2]) if len(parts) > 2 and parts[2] != "None" else None
        return stage_idx, rest_uv, loaded_p10_uv
    except (OSError, ValueError, IndexError):
        return 0, None, None


def _write_state(stage_idx, rest_uv=None, loaded_p10_uv=None):
    with open(STATE_PATH, "w") as f:
        f.write("%d|%s|%s" % (stage_idx, rest_uv, loaded_p10_uv))


def _state_exists():
    try:
        open(STATE_PATH).close()
        return True
    except OSError:
        return False


class Display:
    def __init__(self, i2c, log=None):
        self.d = ssd1306.SSD1306_I2C(128, 64, i2c)
        self.log = log

    def show(self, *lines):
        # 12px/row is normal (5 lines fit); tighten only past that so a
        # 6-line screen still fits instead of running off the bottom.
        row_height = min(12, 64 // max(1, len(lines)))
        self.d.fill(0)
        for row, text in enumerate(lines):
            self.d.text(text, 4, 8 + row * row_height, 1)
        self.d.show()
        if self.log is not None:
            _log(self.log, "SCREEN t=%d lines=%s" % (time.ticks_ms(), "|".join(lines)))


class ServoSweeper:
    """Sweeps back and forth continuously once started -- visible "device
    alive" signal + sustained battery-under-load data."""

    def __init__(self, s, log=None, period_ms=1000):
        self.s = s
        self.log = log
        self.period_ms = period_ms
        self.angle = 0
        self.t0 = time.ticks_ms()
        self.s.write_angle(self.angle)
        if log is not None:
            _log(log, "SERVO t=%d angle=%d" % (self.t0, self.angle))

    def step(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.t0) > self.period_ms:
            self.angle = 180 if self.angle == 0 else 0
            self.s.write_angle(self.angle)
            self.t0 = now
            if self.log is not None:
                _log(self.log, "SERVO t=%d angle=%d" % (now, self.angle))


def _draw_screen_pattern(display, name):
    d = display.d
    if name == "full-white":
        d.fill(1)
    elif name == "full-dark":
        d.fill(0)
    elif name == "border-crosshair":
        d.fill(0)
        d.rect(0, 0, 128, 64, 1)
        d.hline(0, 32, 128, 1)
        d.vline(64, 0, 64, 1)
        d.fill_rect(2, 2, 10, 10, 1)
        d.fill_rect(116, 2, 10, 10, 1)
        d.fill_rect(2, 52, 10, 10, 1)
        d.fill_rect(116, 52, 10, 10, 1)
    d.show()


def run_screen_check_stage(display, button_pins, log):
    """Before DISCONNECT_PROMPT/the sweeper exist -- no servo motion here.
    SELECT=looks right, UP/DOWN=problem (logged, not fatal)."""
    label = "SCREEN_CHECK"
    prev = tuple(pin.value() for pin in button_pins)
    for name in SCREEN_CHECK_PATTERNS:
        _draw_screen_pattern(display, name)
        _log(log, "SCREEN_PATTERN stage=%s pattern=%s" % (label, name))
        t0 = time.ticks_ms()
        outcome = "timeout"
        while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
            values = tuple(pin.value() for pin in button_pins)
            observed = detect_button_press(prev, values)
            prev = values
            if observed == "SELECT":
                outcome = "ok"
                break
            if observed in ("UP", "DOWN"):
                outcome = "problem"
                break
            time.sleep_ms(20)
        if outcome == "ok":
            _log(log, "SCREEN_OK stage=%s pattern=%s" % (label, name))
        elif outcome == "problem":
            _log(log, "SCREEN_PROBLEM stage=%s pattern=%s" % (label, name))
        else:
            _log(log, "TIMEOUT stage=%s pattern=%s" % (label, name))
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


# ESP32-C3 USB Serial/JTAG SOF frame number register.
_USB_SOF_REG = 0x60043024

def is_usb_connected():
    """Direct USB detection via the SOF (Start of Frame) register.
    The USB host sends a SOF packet every 1 ms while connected; reading
    the frame counter twice 5 ms apart and comparing tells us whether a
    host is actively present.  No battery-voltage proxy, no charge-state
    ambiguity."""
    a = machine.mem32[_USB_SOF_REG] & 0x7FF
    time.sleep_ms(5)
    b = machine.mem32[_USB_SOF_REG] & 0x7FF
    return a != b


def shake_head(s):
    """A distinct 'no' gesture -- quick side-to-side -- so 'still on USB'
    reads as a physical refusal to proceed, not just on-screen text."""
    s.write_angle(70)
    time.sleep_ms(150)
    s.write_angle(110)
    time.sleep_ms(150)


def run_disconnect_prompt(display, battery, log):
    """Returns calibrated V_rest either way. No continuous sweeper yet --
    shake_head is a momentary gesture, not sustained load.

    No software way to read the physical battery-power switch (~) -- can
    only remind, not detect. Disconnect itself uses is_usb_connected()."""
    from servo import Servo
    s = Servo(Pin(2))
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["DISCONNECT_PROMPT"]:
        if is_usb_connected():
            display.show("power switch ON?", "still on USB --", "then unplug")
            shake_head(s)
        else:
            display.show("thanks! continuing", "in a moment...")
            time.sleep_ms(1500)
            # confirm it's not just a momentary dip
            if not is_usb_connected():
                rest_uv = battery.read_uv()
                _log(log, "REST_SAMPLE t=%d batt_uv=%d confirmed=1" % (time.ticks_ms(), rest_uv))
                _log(log, "STAGE_DONE stage=DISCONNECT_PROMPT")
                return rest_uv
    rest_uv = battery.read_uv()
    _log(log, "REST_SAMPLE t=%d batt_uv=%d confirmed=0" % (time.ticks_ms(), rest_uv))
    _log(log, "TIMEOUT stage=DISCONNECT_PROMPT")
    return rest_uv


def run_confirm_stage(display, label, button_pins, log, sweeper, sample_fn, format_lines_fn, timeout_ms,
                       finish_check_fn=None, not_ready_lines_fn=None):
    """Live sensor readout; human confirms via SELECT="done"/UP-DOWN="can't"
    rather than an auto-threshold (the i2c toggle's proved unreliable on
    the bench). finish_check_fn(last_value), if given, can veto a SELECT
    (e.g. FLIP must actually end in i2c mode); not_ready_lines_fn explains
    what's still needed and the wait continues."""
    prev = tuple(pin.value() for pin in button_pins)
    t0 = time.ticks_ms()
    last_sample = time.ticks_ms() - 200
    last_value = None
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= 200:
            try:
                last_value = sample_fn()
                display.show(*format_lines_fn(last_value))
                _log(log, "LIVE_VALUE stage=%s t=%d value=%s" % (label, now, last_value))
            except Exception as e:
                _log(log, "ERROR stage=%s: %s" % (label, e))
            last_sample = now
        values = tuple(pin.value() for pin in button_pins)
        observed = detect_button_press(prev, values)
        prev = values
        if observed == "SELECT":
            if finish_check_fn is not None and last_value is not None and not finish_check_fn(last_value):
                _log(log, "NOT_READY stage=%s value=%s" % (label, last_value))
                if not_ready_lines_fn is not None:
                    display.show(*not_ready_lines_fn(last_value))
                    time.sleep_ms(800)
            else:
                _log(log, "STAGE_DONE stage=%s reason=user_confirmed_done" % label)
                return True
        elif observed in ("UP", "DOWN"):
            _log(log, "SKIP stage=%s reason=user_cant_do_it button=%s" % (label, observed))
            return False
        time.sleep_ms(20)
    _log(log, "TIMEOUT stage=%s" % label)
    return False


def run_pot_stage(display, pot, button_pins, log, sweeper):
    label = "POT"
    return run_confirm_stage(
        display, label, button_pins, log, sweeper,
        sample_fn=pot.read,
        format_lines_fn=lambda v: ("POT v=%d" % v, "sweep fully >=3x", "SELECT=done UP/DN=can't"),
        timeout_ms=STAGE_TIMEOUT_MS[label],
    )


def run_servo_check_stage(display, button_pins, log, sweeper):
    """Human check on the sweep -- wear/binding is obvious to look at but
    not verifiable in code (open-loop, no position feedback)."""
    label = "SERVO_CHECK"
    display.show(label, "servo doing", "full 180s?", "SELECT=yes UP/DN=no")
    prev = tuple(pin.value() for pin in button_pins)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
        sweeper.step()
        values = tuple(pin.value() for pin in button_pins)
        observed = detect_button_press(prev, values)
        prev = values
        if observed == "SELECT":
            _log(log, "SERVO_OK stage=%s" % label)
            _log(log, "STAGE_DONE stage=%s" % label)
            return True
        if observed in ("UP", "DOWN"):
            _log(log, "SERVO_PROBLEM stage=%s" % label)
            return False
        time.sleep_ms(20)
    _log(log, "TIMEOUT stage=%s" % label)
    return False


def run_button_stage(display, label, pins, log, sweeper=None, pin_numbers=BUTTON_PIN_NUMBERS):
    """Counts any button edge as a rep regardless of which physical button
    fired (see BUTTON_PIN_NUMBERS -- no settled "correct" mapping); logs
    both the name and raw pin as ground truth for a future calibration
    pass. sweeper is optional: SELECT/UP/DOWN run before DISCONNECT_PROMPT
    starts the continuous sweep."""
    expected = label
    prev = tuple(pin.value() for pin in pins)
    reps = 0
    display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "press %s" % expected)
    t0 = time.ticks_ms()
    while reps < TARGET_REPS[label]:
        if sweeper is not None:
            sweeper.step()
        if time.ticks_diff(time.ticks_ms(), t0) > STAGE_TIMEOUT_MS[label]:
            _log(log, "TIMEOUT stage=%s reps=%d" % (label, reps))
            return False
        values = tuple(pin.value() for pin in pins)
        observed = detect_button_press(prev, values)
        if observed is not None:
            reps += 1
            observed_pin = pin_numbers[BUTTON_NAMES.index(observed)]
            _log(log, "REP stage=%s rep=%d expected=%s observed_name=%s observed_pin=%d" % (
                label, reps, expected, observed, observed_pin
            ))
            display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "press %s" % expected)
        prev = values
        time.sleep_ms(20)
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


def _flip_state():
    low, high = _probe_port_levels()
    return {"low": low, "high": high, "mode": mirror.port_mode(low, high)}


def run_ensure_analog_stage(display, log, sweeper):
    """Confirms the switch starts in analog mode -- LIGHT needs it, and
    FLIP's "end in i2c" is only well-defined from a known start."""
    label = "ENSURE_ANALOG"
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
        sweeper.step()
        state = _flip_state()
        if state["mode"] == "anlg":
            _log(log, "STAGE_DONE stage=%s" % label)
            return True
        display.show(label, "flip switch to", "analog mode")
        time.sleep_ms(150)
    _log(log, "TIMEOUT stage=%s" % label)
    return False


def run_flip_stage(display, button_pins, log, sweeper):
    """Ends specifically in i2c mode -- REBOOT_FOR_SENSOR_SWAP (next) needs
    it there to swap in the color sensor while the board's off."""
    label = "FLIP"
    return run_confirm_stage(
        display, label, button_pins, log, sweeper,
        sample_fn=_flip_state,
        format_lines_fn=lambda s: (
            "FLIP mode=%s" % s["mode"], "lo=%d hi=%d" % (s["low"], s["high"]),
            "toggle >=3x, end i2c", "SELECT=done UP/DN=can't",
        ),
        timeout_ms=STAGE_TIMEOUT_MS[label],
        finish_check_fn=lambda s: s["mode"] == "i2c ",
        not_ready_lines_fn=lambda s: (
            "FLIP mode=%s" % s["mode"], "one more flip", "to reach i2c mode",
        ),
    )


def _probe_port_levels():
    p_digital = Pin(5, Pin.OUT)
    p_digital.value(0)
    p_analog = ADC(Pin(5))
    p_analog.atten(ADC.ATTN_11DB)
    low = p_analog.read()
    p_digital = Pin(5, Pin.OUT)
    p_digital.value(1)
    p_analog = ADC(Pin(5))
    p_analog.atten(ADC.ATTN_11DB)
    high = p_analog.read()
    return low, high


def _read_accel_tuple(accel):
    if accel is None:
        return None
    return accel.xValue, accel.yValue, accel.zValue


def run_accel_stage(display, accel, log, sweeper, label):
    if accel is None:
        display.show(label, "no accel found")
        _log(log, "SKIP stage=%s reason=no_accelerometer" % label)
        time.sleep_ms(1000)
        return False

    mode = "figure8" if label == "ACCEL_FIG8" else "flat"
    if mode == "flat":
        display.show(label, "set board flat", "and leave still")
    else:
        display.show(label, "gentle figure-8", "then set on table")

    samples = []
    t0 = time.ticks_ms()
    last_sample = time.ticks_ms() - 100
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= 100:
            try:
                sample = _read_accel_tuple(accel)
                if sample is not None:
                    samples.append(sample)
                    _log(log, "ACCEL_SAMPLE stage=%s t=%d accel=%d,%d,%d mag=%d" % (
                        label, now, sample[0], sample[1], sample[2],
                        int((sample[0] ** 2 + sample[1] ** 2 + sample[2] ** 2) ** 0.5),
                    ))
            except Exception as e:
                _log(log, "ERROR stage=%s: %s" % (label, e))
            last_sample = now
        time.sleep_ms(20)

    result = evaluate_accel_motion(samples, mode)
    detail = result.get("detail", {})
    _log(log, "ACCEL_SUMMARY stage=%s status=%s n=%d span=%s mag=%s summary=%s" % (
        label, result["status"], detail.get("n_samples", len(samples)),
        detail.get("max_axis_span", ""), detail.get("median_magnitude", ""), result["summary"],
    ))
    display.show(label, result["status"], result["summary"][:16])
    time.sleep_ms(1000)
    _log(log, "STAGE_DONE stage=%s" % label)
    return result["status"] == "pass"


def run_light_stage(display, button_pins, log, sweeper):
    """Wave the sensor light<->dark<->light >=3x, auto-counted via the
    adaptive min/max in LIGHT_MARGIN_*/LIGHT_MIN_USEFUL_SPAN. SELECT still
    ends it early, UP/DOWN skips (no sensor/can't do it)."""
    label = "LIGHT"
    light = ADC(Pin(5))
    light.atten(ADC.ATTN_11DB)
    reached_low = reached_high = False
    min_seen = max_seen = None
    reps = 0
    prev = tuple(pin.value() for pin in button_pins)
    t0 = time.ticks_ms()
    last_shown_v = None
    while reps < LIGHT_TARGET_REPS:
        sweeper.step()
        if time.ticks_diff(time.ticks_ms(), t0) > STAGE_TIMEOUT_MS[label]:
            _log(log, "TIMEOUT stage=%s reps=%d" % (label, reps))
            return False
        values = tuple(pin.value() for pin in button_pins)
        observed = detect_button_press(prev, values)
        prev = values
        if observed == "SELECT":
            _log(log, "STAGE_DONE stage=%s reason=user_confirmed_done reps=%d" % (label, reps))
            return True
        if observed in ("UP", "DOWN"):
            _log(log, "SKIP stage=%s reason=user_cant_do_it button=%s" % (label, observed))
            return False
        try:
            v = light.read()
            _log(log, "LIGHT_SAMPLE stage=%s t=%d raw=%d" % (label, time.ticks_ms(), v))
            if min_seen is None:
                min_seen = max_seen = v
            min_seen = min(min_seen, v)
            max_seen = max(max_seen, v)
            span = max_seen - min_seen
            margin = max(LIGHT_MARGIN_MIN, span * LIGHT_MARGIN_FRAC)
            if v <= min_seen + margin:
                reached_low = True
            if v >= max_seen - margin:
                reached_high = True
            if reached_low and reached_high and span >= LIGHT_MIN_USEFUL_SPAN:
                reps += 1
                reached_low = reached_high = False
                _log(log, "REP stage=%s rep=%d" % (label, reps))
            if last_shown_v is None or abs(v - last_shown_v) > 20:
                display.show(
                    "%s x%d v=%d" % (label, LIGHT_TARGET_REPS - reps, v),
                    "wave light<->dark", "SELECT=done UP/DN=can't",
                )
                last_shown_v = v
        except Exception as e:
            _log(log, "ERROR stage=%s: %s" % (label, e))
        time.sleep_ms(20)
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


def _read_word_le(i2c, addr, reg):
    data = i2c.readfrom_mem(addr, reg, 2)
    return data[0] | (data[1] << 8)


def run_color_white_stage(display, i2c, log, sweeper, button_pins):
    label = "COLOR_WHITE"
    if VEML6040_ADDR not in i2c.scan():
        display.show(label, "no color sensor")
        _log(log, "SKIP stage=%s reason=no_veml6040" % label)
        time.sleep_ms(1000)
        return False

    display.show(label, "point at white", "SELECT=lock", "UP/DN=can't")
    prev = tuple(pin.value() for pin in button_pins)
    t0 = time.ticks_ms()
    locked = False
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
        sweeper.step()
        values = tuple(pin.value() for pin in button_pins)
        observed = detect_button_press(prev, values)
        prev = values
        if observed in ("UP", "DOWN"):
            _log(log, "SKIP stage=%s reason=user_cant_do_it button=%s" % (label, observed))
            return False
        if observed == "SELECT":
            locked = True
            break
        time.sleep_ms(20)
    if not locked:
        _log(log, "TIMEOUT stage=%s" % label)
        return False

    display.show(label, "hold still...")
    samples = []
    t0 = time.ticks_ms()
    last_sample = time.ticks_ms() - 500
    lock_window_ms = 2000
    while time.ticks_diff(time.ticks_ms(), t0) < lock_window_ms:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= 500:
            try:
                r = _read_word_le(i2c, VEML6040_ADDR, VEML6040_R)
                g = _read_word_le(i2c, VEML6040_ADDR, VEML6040_G)
                b = _read_word_le(i2c, VEML6040_ADDR, VEML6040_B)
                w = _read_word_le(i2c, VEML6040_ADDR, VEML6040_W)
                samples.append((r, g, b, w))
                _log(log, "COLOR_WHITE_SAMPLE t=%d r=%d g=%d b=%d w=%d" % (now, r, g, b, w))
            except Exception as e:
                _log(log, "ERROR stage=%s: %s" % (label, e))
            last_sample = now
        time.sleep_ms(20)

    if samples:
        avg = tuple(int(round(sum(s[i] for s in samples) / len(samples))) for i in range(4))
        gains = compute_white_balance_milli(avg[:3])
        _log(log, "COLOR_WHITE_SUMMARY n=%d r=%d g=%d b=%d w=%d wb_milli=%d,%d,%d" % (
            len(samples), avg[0], avg[1], avg[2], avg[3], gains[0], gains[1], gains[2]
        ))
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


def _sample_full_state(pot, battery, accel, i2c, i2c_sensor, button_pins, sweeper):
    """Every control/sensor/servo/voltage reading, one tick -- the main
    replay/distribution data source (DEVICE_HEALTH_DESIGN.md sec 6)."""
    pot_v = pot.read()
    batt_raw = battery.read()
    batt_uv = battery.read_uv()
    accel_sample = _read_accel_tuple(accel)
    low, high = _probe_port_levels()
    port_mode = mirror.port_mode(low, high)
    sensor_attached = mirror.sensor_attached(low, high) or i2c_sensor is not None
    if i2c_sensor is not None:
        rgbw = i2c_sensor.read_rgbw()
        sensor_value = rgbw[3]
    elif sensor_attached:
        try:
            sensor_value = ADC(Pin(5)).read()
        except Exception:
            sensor_value = None
    else:
        sensor_value = None
    buttons = tuple(pin.value() for pin in button_pins)
    return {
        "pot": pot_v,
        "batt_raw": batt_raw,
        "batt_uv": batt_uv,
        "accel": accel_sample,
        "port_mode": port_mode,
        "sensor_attached": sensor_attached,
        "sensor_value": sensor_value,
        "buttons": buttons,
        "angle": sweeper.angle,
    }


def run_sustain_stage(display, pot, battery, accel, i2c, i2c_sensor, button_pins, log, sweeper):
    display.show("sustained check", "battery-only,", "just wait...")
    loaded_uv = []
    t0 = time.ticks_ms()
    last_sample = time.ticks_ms() - FULL_SAMPLE_PERIOD_MS
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["SUSTAIN"]:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= FULL_SAMPLE_PERIOD_MS:
            try:
                state = _sample_full_state(pot, battery, accel, i2c, i2c_sensor, button_pins, sweeper)
                loaded_uv.append(state["batt_uv"])
                _log(log, format_full_sample_line(
                    now, state["pot"], state["batt_raw"], state["batt_uv"], state["accel"],
                    state["port_mode"], state["sensor_attached"], state["sensor_value"],
                    state["buttons"], state["angle"],
                ))
            except Exception as e:
                _log(log, "ERROR stage=SUSTAIN: %s" % e)
            last_sample = now
        time.sleep_ms(20)
    _log(log, "STAGE_DONE stage=SUSTAIN")
    return loaded_uv


def run_wait_retrieval(display, pot, battery, accel, i2c, i2c_sensor, button_pins, log, sweeper, verdict):
    """Verdict + live readout, looping indefinitely -- ends only via
    retrieval (mpremote interrupting it) or losing power. Deliberately not
    self-terminating (a bounded/self-resetting earlier version was an
    unrequested reboot, confirmed on the bench). Log + marker stay
    untouched until an actual retrieval clears them, so a manual
    power-cycle just resumes this same screen next boot."""
    if verdict.get("verdict") == "insufficient data":
        verdict_lines = ("BATTERY", "insufficient data", "see", LOG_PATH)
    else:
        verdict_lines = (
            "BATTERY",
            verdict["verdict"][:16],
            "rest %.2fV" % verdict["rest_cell_v"],
            "sag %dmV" % verdict["sag_cell_mv"],
        )

    last_sample = time.ticks_ms() - FULL_SAMPLE_PERIOD_MS
    last_screen_flip = time.ticks_ms()
    showing_verdict = True
    delta_states = (" ", " ", " ")
    previous_accel = None
    t0 = time.ticks_ms()

    while True:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= FULL_SAMPLE_PERIOD_MS:
            try:
                state = _sample_full_state(pot, battery, accel, i2c, i2c_sensor, button_pins, sweeper)
                _log(log, format_full_sample_line(
                    now, state["pot"], state["batt_raw"], state["batt_uv"], state["accel"],
                    state["port_mode"], state["sensor_attached"], state["sensor_value"],
                    state["buttons"], state["angle"],
                ))
                delta, delta_states = mirror.delta_display(previous_accel, state["accel"], delta_states)
                if state["accel"] is not None:
                    previous_accel = state["accel"]
                dwell = VERDICT_DWELL_MS if showing_verdict else TELEMETRY_DWELL_MS
                if time.ticks_diff(now, last_screen_flip) >= dwell:
                    showing_verdict = not showing_verdict
                    last_screen_flip = now
                if showing_verdict:
                    display.show(*verdict_lines)
                else:
                    buttons = {"up": state["buttons"][0], "down": state["buttons"][1], "select": state["buttons"][2]}
                    lines = mirror.screen_lines(
                        state["batt_uv"] / 1e6, False, state["port_mode"], state["sensor_attached"],
                        state["sensor_value"] if state["sensor_value"] is not None else -1,
                        state["pot"], state["angle"], buttons, delta,
                    )
                    elapsed_s = time.ticks_diff(now, t0) // 1000
                    # No RTC/wall clock on this board -- this is elapsed
                    # time in *this* run, not a real time-of-day, labeled
                    # as such rather than pretending otherwise.
                    lines = lines + ("rec %02d:%02d" % (elapsed_s // 60, elapsed_s % 60),)
                    display.show(*lines)
            except Exception as e:
                _log(log, "ERROR stage=VERDICT: %s" % e)
            last_sample = now
        time.sleep_ms(20)


def main():
    boot_num_path = "healthcheck_boot_count.txt"
    try:
        with open(boot_num_path) as f:
            boot_num = int(f.read().strip()) + 1
    except (OSError, ValueError):
        boot_num = 1
    with open(boot_num_path, "w") as f:
        f.write(str(boot_num))

    cause = machine.reset_cause()
    names = {getattr(machine, n): n for n in dir(machine) if n.endswith("_RESET")}
    cause_name = names.get(cause, "UNKNOWN")

    is_resume = _state_exists()
    stage_idx, rest_uv, loaded_p10_uv = _read_state()
    if not is_resume:
        _write_state(0)  # fresh manual start -- claim the marker immediately

    with open(LOG_PATH, "a") as log:
        _log(log, "BOOT boot_num=%d reset_cause=%d(%s) resume_stage=%d" % (
            boot_num, cause, cause_name, stage_idx
        ))

        i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
        display = Display(i2c, log=log)
        pot = ADC(Pin(3))
        pot.atten(ADC.ATTN_11DB)
        battery = ADC(Pin(4))
        battery.atten(ADC.ATTN_11DB)
        up = Pin(10, Pin.IN)
        down = Pin(8, Pin.IN)
        select = Pin(9, Pin.IN)
        button_pins = (up, down, select)

        accel = None
        try:
            import adxl345
            accel = adxl345.ADXL345(i2c)
        except Exception as e:
            _log(log, "NOTE accelerometer unavailable: %s" % e)

        i2c_sensor = None
        if VEML6040_ADDR in i2c.scan():
            i2c_sensor = mirror.I2CSensor(i2c)

        if stage_idx > 0 and STAGES[stage_idx - 1] == "OFFON":
            # After the deliberate power cycle: verdict + wait indefinitely
            # (see run_wait_retrieval()'s docstring).
            _log(log, "REP stage=OFFON rep=1 (confirmed by this reboot)")
            _log(log, "STAGE_DONE stage=OFFON")
            verdict = compute_battery_verdict(rest_uv, [loaded_p10_uv] if loaded_p10_uv is not None else [])
            _log(log, "VERDICT %s" % verdict)
            run_wait_retrieval(display, pot, battery, accel, i2c, i2c_sensor, button_pins, log,
                                ServoSweeper(servo.Servo(Pin(2)), log=log), verdict)
            return

        sweeper = None
        # Resuming past DISCONNECT_PROMPT (e.g. after REBOOT_FOR_SENSOR_SWAP)
        # means it won't re-run this boot, so recreate the sweeper up front.
        if stage_idx > STAGES.index("DISCONNECT_PROMPT"):
            sweeper = ServoSweeper(servo.Servo(Pin(2)), log=log)
        loaded_uv = []
        while stage_idx < len(STAGES):
            stage = STAGES[stage_idx]
            if stage == "SCREEN_CHECK":
                # before DISCONNECT_PROMPT/the continuous sweeper -- no
                # point walking through the unplug dance on a unit whose
                # screen can't even show the instructions.
                run_screen_check_stage(display, button_pins, log)
            elif stage == "DISCONNECT_PROMPT":
                rest_uv = run_disconnect_prompt(display, battery, log)
                sweeper = ServoSweeper(servo.Servo(Pin(2)), log=log)
            elif stage == "ENSURE_ANALOG":
                run_ensure_analog_stage(display, log, sweeper)
            elif stage == "POT":
                run_pot_stage(display, pot, button_pins, log, sweeper)
            elif stage == "SERVO_CHECK":
                run_servo_check_stage(display, button_pins, log, sweeper)
            elif stage in ("SELECT", "UP", "DOWN"):
                run_button_stage(display, stage, button_pins, log, sweeper)
            elif stage in ("ACCEL_FLAT1", "ACCEL_FIG8", "ACCEL_FLAT2"):
                run_accel_stage(display, accel, log, sweeper, stage)
            elif stage == "LIGHT":
                run_light_stage(display, button_pins, log, sweeper)
            elif stage == "FLIP":
                run_flip_stage(display, button_pins, log, sweeper)
            elif stage == "REBOOT_FOR_SENSOR_SWAP":
                # Second, mid-sequence reboot: window to swap light->color
                # sensor while off. Next boot just continues the normal
                # loop (only OFFON gets special resume handling).
                display.show("power OFF now,", "swap light->color", "sensor, power ON")
                stage_idx += 1
                _write_state(stage_idx, rest_uv, percentile(loaded_uv, 0.10) if loaded_uv else None)
                _log(log, "WAITING_FOR_REBOOT stage=REBOOT_FOR_SENSOR_SWAP")
                return  # nothing more to do this boot -- resumes on next boot
            elif stage == "COLOR_WHITE":
                run_color_white_stage(display, i2c, log, sweeper, button_pins)
            elif stage == "SUSTAIN":
                loaded_uv = run_sustain_stage(display, pot, battery, accel, i2c, i2c_sensor, button_pins, log, sweeper)
            elif stage == "OFFON":
                display.show("power cycle", "the board now", "(OFF then ON)")
                stage_idx += 1
                loaded_p10_uv = percentile(loaded_uv, 0.10)
                _write_state(stage_idx, rest_uv, loaded_p10_uv)
                _log(log, "WAITING_FOR_REBOOT stage=OFFON")
                return  # nothing more to do this boot -- resumes on next boot
            stage_idx += 1
            _write_state(stage_idx, rest_uv, percentile(loaded_uv, 0.10) if loaded_uv else None)


if __name__ == "__main__":
    main()
