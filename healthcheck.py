"""SmartMotor on-device health check.

Graduated from spikes/S7_guided/guided_test_device.py. The OLED walks you
through exercising every control and logs what it sees, so a fleet of
devices can be triaged without a bench full of equipment.

Reachable two ways, both through the same marker file (HEALTHCHECK_STATE_PATH):
  - the three-finger salute (UP+DOWN+SELECT) at boot, handled by main.py.
  - healthcheck_host.py remote-starting a unit that wasn't hand-saluted, by
    writing the marker file itself and resetting the board.

Sequence: ask you to unplug USB/power first (nothing below is useful data
while USB is dominating the rail); once confirmed off power, start the servo
sweeping continuously for the rest of the run -- both a visible "still
running" signal and sustained-load battery data; then ask you to exercise
the pot, each button, and the analog/i2c toggle at least 3x each, swivel the
board for the accelerometer, and (skippable, since not every unit has one)
read a light sensor or lock a color-sensor white balance; then a 90s
passive/loaded logging window; then a deliberate power cycle.

The OFF/ON stage is inherently different: a power cycle stops this script
entirely, so there's nothing to detect in the moment. Progress -- and the
battery numbers needed for a verdict -- are persisted to
HEALTHCHECK_STATE_PATH before that stage begins; the *next* boot recognizes
it was waiting for a cycle, computes the verdict, and shows it briefly
(alongside a live mirror-style readout) -- then clears the marker and
resets back into *normal* operation on its own. Deliberately not an
indefinite wait: a unit run via the three-finger salute in the field, with
no laptop present, must not sit stuck on a screen forever. The recording
(healthcheck_log.txt) stays on flash regardless, so healthcheck_host.py can
retrieve it from any later connection -- live in the room, or picked up
whenever that device is next plugged in.

------------------------------------------------------------------------------
SAFETY NOTE

Each control-exercise stage has a timeout (STAGE_TIMEOUT_MS) so a broken
button/pot/toggle can't hang the sequence forever -- it logs "TIMEOUT" for
that stage and moves on. The post-OFFON verdict screen is bounded too
(VERDICT_DISPLAY_MS), not an indefinite wait.

Co-authored-by: GPT-5, Aug 2026
Co-authored-by: Claude Sonnet 5, Aug 2026
"""

import time
import machine
from machine import Pin, ADC, SoftI2C
import ssd1306
import servo
import mirror

from healthcheck_logic import (
    compute_battery_verdict,
    compute_white_balance_milli,
    detect_button_press,
    evaluate_accel_motion,
    evaluate_button_prompt,
    format_full_sample_line,
    percentile,
    summarize_scalar_samples,
)

LOG_PATH = "healthcheck_log.txt"
STATE_PATH = "healthcheck_state.txt"

STAGES = [
    "DISCONNECT_PROMPT",
    "POT", "SELECT", "UP", "DOWN", "FLIP",
    "ACCEL_FLAT1", "ACCEL_FIG8", "ACCEL_FLAT2",
    "LIGHT_DARK", "LIGHT_BRIGHT", "COLOR_WHITE",
    "SUSTAIN",
    "OFFON",
]
TARGET_REPS = {
    "POT": 3, "SELECT": 3, "UP": 3, "DOWN": 3, "FLIP": 3,
    "ACCEL_FLAT1": 1, "ACCEL_FIG8": 1, "ACCEL_FLAT2": 1,
    "LIGHT_DARK": 1, "LIGHT_BRIGHT": 1, "COLOR_WHITE": 1,
    "OFFON": 1,
}
STAGE_TIMEOUT_MS = {
    "DISCONNECT_PROMPT": 60000,
    "POT": 60000, "SELECT": 30000, "UP": 30000, "DOWN": 30000, "FLIP": 30000,
    "ACCEL_FLAT1": 12000, "ACCEL_FIG8": 25000, "ACCEL_FLAT2": 12000,
    "LIGHT_DARK": 10000, "LIGHT_BRIGHT": 10000, "COLOR_WHITE": 12000,
    "SUSTAIN": 90000,
    "OFFON": 60000,
}

POT_LOW_THRESH = 300
POT_HIGH_THRESH = 3800
PORT_SPREAD_THRESHOLD = 2000
SKIP_WINDOW_MS = 2500  # how long a LIGHT/COLOR_WHITE stage listens for a skip press
FULL_SAMPLE_PERIOD_MS = 500
VERDICT_DISPLAY_MS = 4000  # bounded -- see show_verdict_and_finish()
VEML6040_ADDR = 0x10
VEML6040_R = 0x08
VEML6040_G = 0x09
VEML6040_B = 0x0A
VEML6040_W = 0x0B


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


def _clear_state():
    """Removes only the marker (main.py's healthcheck_pending() check) --
    healthcheck_log.txt is deliberately left on flash. That's "the saved
    recording" for a field run with no laptop present: healthcheck_host.py
    can retrieve it from any later connection, live or days from now."""
    try:
        import os
        os.remove(STATE_PATH)
    except OSError:
        pass


class Display:
    def __init__(self, i2c, log=None):
        self.d = ssd1306.SSD1306_I2C(128, 64, i2c)
        self.log = log

    def show(self, *lines):
        self.d.fill(0)
        for row, text in enumerate(lines):
            self.d.text(text, 4, 8 + row * 12, 1)
        self.d.show()
        if self.log is not None:
            _log(self.log, "SCREEN t=%d lines=%s" % (time.ticks_ms(), "|".join(lines)))


class ServoSweeper:
    """Sweeps back and forth continuously once started -- a visible
    "device is alive and ready" signal, and sustained battery-under-load
    data for the rest of the run rather than just a momentary check."""

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


def is_probably_on_usb(battery):
    # No dedicated VBUS-sense pin on this board, so this is a proxy, not a
    # direct measurement: the battery ADC reads distinctly higher whenever
    # USB is actively delivering charge current (see sensors.readbattery()'s
    # 'charging' bucket, and DEVICE_HEALTH_DESIGN.md section 1).
    return battery.read() > 2850


def shake_head(s):
    """A distinct 'no' gesture -- quick side-to-side -- so 'still on USB'
    reads as a physical refusal to proceed, not just on-screen text."""
    s.write_angle(70)
    time.sleep_ms(150)
    s.write_angle(110)
    time.sleep_ms(150)


def run_disconnect_prompt(display, battery, log):
    """Returns calibrated V_rest (microvolts) once disconnect is confirmed,
    or None on timeout. No continuous sweeper yet -- shake_head uses the
    servo directly, a momentary gesture, not sustained load."""
    from servo import Servo
    s = Servo(Pin(2))
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["DISCONNECT_PROMPT"]:
        if is_probably_on_usb(battery):
            display.show("still on USB --", "unplug it now")
            shake_head(s)
        else:
            display.show("thanks! continuing", "in a moment...")
            time.sleep_ms(1500)
            # confirm it's not just a momentary dip
            if not is_probably_on_usb(battery):
                rest_uv = battery.read_uv()
                _log(log, "REST_SAMPLE t=%d batt_uv=%d" % (time.ticks_ms(), rest_uv))
                _log(log, "STAGE_DONE stage=DISCONNECT_PROMPT")
                return rest_uv
    _log(log, "TIMEOUT stage=DISCONNECT_PROMPT")
    return None


def run_pot_stage(display, pot, log, sweeper):
    label = "POT"
    reached_low = reached_high = False
    reps = 0
    t0 = time.ticks_ms()
    last_shown_v = None
    while reps < TARGET_REPS[label]:
        sweeper.step()
        if time.ticks_diff(time.ticks_ms(), t0) > STAGE_TIMEOUT_MS[label]:
            _log(log, "TIMEOUT stage=%s reps=%d" % (label, reps))
            return False
        try:
            v = pot.read()
            if v <= POT_LOW_THRESH:
                reached_low = True
            if v >= POT_HIGH_THRESH:
                reached_high = True
            if reached_low and reached_high:
                reps += 1
                reached_low = reached_high = False
                _log(log, "REP stage=%s rep=%d" % (label, reps))
            if last_shown_v is None or abs(v - last_shown_v) > 20:
                display.show("%s x%d  v=%d" % (label, TARGET_REPS[label] - reps, v), "sweep fully",
                             "lo:%s hi:%s" % (reached_low, reached_high))
                last_shown_v = v
        except Exception as e:
            _log(log, "ERROR stage=%s: %s" % (label, e))
        time.sleep_ms(20)
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


def run_button_stage(display, label, pins, log, sweeper):
    expected = label
    prev = tuple(pin.value() for pin in pins)
    reps = 0
    display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "press %s" % expected)
    t0 = time.ticks_ms()
    while reps < TARGET_REPS[label]:
        sweeper.step()
        if time.ticks_diff(time.ticks_ms(), t0) > STAGE_TIMEOUT_MS[label]:
            _log(log, "TIMEOUT stage=%s reps=%d" % (label, reps))
            return False
        values = tuple(pin.value() for pin in pins)
        observed = detect_button_press(prev, values)
        if observed is not None:
            event = evaluate_button_prompt(expected, observed)
            reps += 1
            if event["status"] == "match":
                _log(log, "REP stage=%s rep=%d observed=%s" % (label, reps, observed))
                display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "press %s" % expected)
            else:
                _log(log, "BUTTON_MISMATCH stage=%s rep=%d expected=%s observed=%s" % (
                    label, reps, expected, observed
                ))
                display.show("expected %s" % expected, "saw %s" % observed, "%s x%d" % (label, TARGET_REPS[label] - reps))
                time.sleep_ms(500)
        prev = values
        time.sleep_ms(20)
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


def run_flip_stage(display, log, sweeper):
    label = "FLIP"
    reps = 0
    prev_state = None
    display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "toggle the", "analog/i2c switch")
    t0 = time.ticks_ms()
    while reps < TARGET_REPS[label]:
        sweeper.step()
        if time.ticks_diff(time.ticks_ms(), t0) > STAGE_TIMEOUT_MS[label]:
            _log(log, "TIMEOUT stage=%s reps=%d" % (label, reps))
            return False
        try:
            low, high = _probe_port_levels()
            state = (high - low) > PORT_SPREAD_THRESHOLD
            if prev_state is not None and state != prev_state:
                reps += 1
                _log(log, "REP stage=%s rep=%d" % (label, reps))
                display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "toggle the", "analog/i2c switch")
            prev_state = state
        except Exception as e:
            _log(log, "ERROR stage=%s: %s" % (label, e))
        time.sleep_ms(150)
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


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
        display.show(label, "gentle figure-8", "then keep going")

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


def _wait_for_skip(display, log, label, pins, skip_names, prompt_lines):
    """Watches for a press on any of skip_names for SKIP_WINDOW_MS. Returns
    True if skipped (already logged), False if the window elapsed clean."""
    display.show(*prompt_lines)
    prev = tuple(pin.value() for pin in pins)
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < SKIP_WINDOW_MS:
        values = tuple(pin.value() for pin in pins)
        observed = detect_button_press(prev, values)
        if observed in skip_names:
            _log(log, "SKIP stage=%s reason=user_skip button=%s" % (label, observed))
            return True
        prev = values
        time.sleep_ms(20)
    return False


def run_light_stage(display, log, sweeper, label, prompt, button_pins):
    if _wait_for_skip(display, log, label, button_pins, ("UP", "DOWN"),
                       (label, prompt, "UP/DOWN to skip")):
        time.sleep_ms(300)
        return False

    light = ADC(Pin(5))
    light.atten(ADC.ATTN_11DB)
    display.show(label, prompt, "hold still")
    samples = []
    t0 = time.ticks_ms()
    last_sample = time.ticks_ms() - 200
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= 200:
            try:
                value = light.read()
                samples.append(value)
                _log(log, "LIGHT_SAMPLE stage=%s t=%d raw=%d" % (label, now, value))
            except Exception as e:
                _log(log, "ERROR stage=%s: %s" % (label, e))
            last_sample = now
        time.sleep_ms(20)
    summary = summarize_scalar_samples(samples)
    _log(log, "LIGHT_SUMMARY stage=%s n=%d min=%s max=%s mean=%s" % (
        label, summary["n_samples"], summary["min"], summary["max"], summary["mean"]
    ))
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

    display.show(label, "point at white", "SELECT=lock UP=skip")
    prev = tuple(pin.value() for pin in button_pins)
    t0 = time.ticks_ms()
    locked = False
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
        sweeper.step()
        values = tuple(pin.value() for pin in button_pins)
        observed = detect_button_press(prev, values)
        prev = values
        if observed == "UP":
            _log(log, "SKIP stage=%s reason=user_skip button=UP" % label)
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
    """Every control/sensor/servo/voltage reading, one tick. Shared by
    SUSTAIN and WAIT_RETRIEVAL -- the main source of replay/distribution
    data (DEVICE_HEALTH_DESIGN.md sec 6)."""
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


def show_verdict_and_finish(display, pot, battery, accel, i2c, i2c_sensor, button_pins, log,
                             sweeper, verdict, duration_ms=VERDICT_DISPLAY_MS):
    """Shows the battery verdict, alternating with a live mirror-style
    readout, for a bounded window -- then returns so main() can hand control
    straight back to normal operation. Deliberately NOT an indefinite wait:
    a field-deployed unit (three-finger salute, no laptop present) needs to
    keep working, not sit stuck on this screen until someone eventually
    plugs it in. The recording (healthcheck_log.txt) stays on flash either
    way, so healthcheck_host.py can retrieve it whenever it next connects --
    live in the room or days later, it doesn't matter which."""
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

    while time.ticks_diff(time.ticks_ms(), t0) < duration_ms:
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
                if time.ticks_diff(now, last_screen_flip) >= 2000:
                    showing_verdict = not showing_verdict
                    last_screen_flip = now
                if showing_verdict:
                    display.show(*verdict_lines)
                else:
                    buttons = {"up": state["buttons"][0], "down": state["buttons"][1], "select": state["buttons"][2]}
                    lines = mirror.screen_lines(
                        True, False, state["port_mode"], state["sensor_attached"],
                        state["sensor_value"] if state["sensor_value"] is not None else -1,
                        state["pot"], state["angle"], buttons, delta,
                    )
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
            # resuming after the deliberate power cycle -- nothing left to
            # detect. Show the verdict briefly, then hand back to normal
            # operation on our own: a field-run unit (three-finger salute,
            # no laptop) must not sit stuck waiting to be plugged in. The
            # log itself stays on flash for whenever a host next connects.
            _log(log, "REP stage=OFFON rep=1 (confirmed by this reboot)")
            _log(log, "STAGE_DONE stage=OFFON")
            verdict = compute_battery_verdict(rest_uv, [loaded_p10_uv] if loaded_p10_uv is not None else [])
            _log(log, "VERDICT %s" % verdict)
            show_verdict_and_finish(display, pot, battery, accel, i2c, i2c_sensor, button_pins, log,
                                     ServoSweeper(servo.Servo(Pin(2)), log=log), verdict)
            _log(log, "SEQUENCE_COMPLETE")
            _clear_state()
            machine.reset()
            return

        sweeper = None
        loaded_uv = []
        while stage_idx < len(STAGES):
            stage = STAGES[stage_idx]
            if stage == "DISCONNECT_PROMPT":
                rest_uv = run_disconnect_prompt(display, battery, log)
                sweeper = ServoSweeper(servo.Servo(Pin(2)), log=log)
            elif stage == "POT":
                run_pot_stage(display, pot, log, sweeper)
            elif stage in ("SELECT", "UP", "DOWN"):
                run_button_stage(display, stage, button_pins, log, sweeper)
            elif stage == "FLIP":
                run_flip_stage(display, log, sweeper)
            elif stage in ("ACCEL_FLAT1", "ACCEL_FIG8", "ACCEL_FLAT2"):
                run_accel_stage(display, accel, log, sweeper, stage)
            elif stage == "LIGHT_DARK":
                run_light_stage(display, log, sweeper, stage, "cover light", button_pins)
            elif stage == "LIGHT_BRIGHT":
                run_light_stage(display, log, sweeper, stage, "point at light", button_pins)
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
