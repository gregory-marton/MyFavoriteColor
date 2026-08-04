"""
S7 guided hardware test -- DEVICE side.

Co-authored-by: GPT-5, Aug 2026

Runs the D-POT/D-BTN/D-PORT/D-PWR human-assisted checks as one on-device
guided sequence: the OLED itself tells you what to do and counts down
repetitions as it detects them ("POT x3" -> "POT x2" -> "POT x1" -> next
stage), instead of a terminal prompt with no feedback. That's the fix for
the earlier problem where a blind "press buttons now" gave no indication
whether anything was actually detected.

Sequence: sweep the pot fully back and forth 3 times, press SELECT 3 times,
press UP 3 times, press DOWN 3 times, flip the analog/I2C toggle 3 times -- then a disconnect
step that refuses to proceed (shaking the servo head side to side, "no")
while the battery ADC still reads in the charging range -- no dedicated
VBUS-sense pin exists on this board, so that reading is a proxy for "still
on USB," not a direct measurement, but it's a reliable one right after a
USB-connected phase -- then repeats all four (touching a button while on USB
proves little about the battery, since USB power dominates), then a 90s
sustained passive-logging period on battery alone to give a slow sag or
intermittent fault time to show up, then a power-cycle (OFF then ON), then
plug in an I2C sensor.

The OFF/ON stage is inherently different: a power cycle stops this script
entirely, so there is nothing to detect in the moment. Progress is persisted
to guided_stage.txt before that stage begins; the *next* boot recognizes it
was waiting for a cycle and treats its own existence as confirmation, then
continues from there. This is the same "flash survives a reset" trick as
power_log_device.py's flight recorder.

------------------------------------------------------------------------------
HOW TO RUN

    .venv/bin/mpremote cp main.py :main_real_backup.py
    .venv/bin/mpremote cp spikes/S7_guided/guided_test_device.py :main.py
    .venv/bin/mpremote reset
    # watch the OLED and do what it says. When it finishes (or after the
    # OFF/ON step's reset), reconnect/reset, then:
    .venv/bin/mpremote fs cp :guided_log.txt spikes/S7_guided/
    ./spikes/S7_guided/read_guided_log.py spikes/S7_guided/guided_log.txt
    # afterwards, restore the original firmware:
    .venv/bin/mpremote cp main_real_backup.py :main.py
    .venv/bin/mpremote reset
    .venv/bin/mpremote fs rm :guided_log.txt
    .venv/bin/mpremote fs rm :guided_stage.txt
    .venv/bin/mpremote fs rm :main_real_backup.py

------------------------------------------------------------------------------
SAFETY NOTE

Each stage has a timeout (see STAGE_TIMEOUT_MS) so a broken button/pot/toggle
can't hang the sequence forever -- it logs "TIMEOUT" for that stage and moves
on. Writes nothing to flash beyond guided_log.txt and the one-line
guided_stage.txt progress marker.
"""

import time
import machine
from machine import Pin, ADC, SoftI2C
import ssd1306
import servo

try:
    from guided_logic import (
        BUTTON_NAMES,
        accel_magnitude,
        compute_white_balance_milli,
        detect_button_press,
        evaluate_accel_motion,
        evaluate_button_prompt,
        summarize_scalar_samples,
    )
except ImportError:
    BUTTON_NAMES = ("UP", "DOWN", "SELECT")

    def detect_button_press(previous, current, names=BUTTON_NAMES):
        for name, before, after in zip(names, previous, current):
            if before == 1 and after == 0:
                return name
        return None

    def evaluate_button_prompt(expected, observed):
        return {
            "status": "match" if observed == expected else "mismatch",
            "expected": expected,
            "observed": observed,
        }

    def accel_magnitude(sample):
        x, y, z = sample
        return (x * x + y * y + z * z) ** 0.5

    def evaluate_accel_motion(samples, mode):
        if not samples:
            return {"status": "fail", "summary": "no accelerometer samples", "detail": {}}
        ranges = [max(axis) - min(axis) for axis in zip(*samples)]
        span = max(ranges)
        if mode == "figure8" and span < 80:
            return {"status": "warn", "summary": "figure-8 motion was too small", "detail": {"max_axis_span": span}}
        return {"status": "pass", "summary": "accelerometer samples captured", "detail": {"max_axis_span": span}}

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

LOG_PATH = "guided_log.txt"
STAGE_PATH = "guided_stage.txt"

STAGES = [
    "POT", "SELECT", "UP", "DOWN", "FLIP",
    "DISCONNECT_PROMPT",
    "ACCEL_FLAT1", "ACCEL_FIG8", "ACCEL_FLAT2",
    "POT_B", "SELECT_B", "UP_B", "DOWN_B", "FLIP_B",
    "SUSTAIN",
    "OFFON", "SENSOR",
    "COLOR_WHITE", "LIGHT_DARK", "LIGHT_BRIGHT",
]
TARGET_REPS = {
    "POT": 3, "SELECT": 3, "UP": 3, "DOWN": 3, "FLIP": 3,
    "POT_B": 3, "SELECT_B": 3, "UP_B": 3, "DOWN_B": 3, "FLIP_B": 3,
    "ACCEL_FLAT1": 1, "ACCEL_FIG8": 1, "ACCEL_FLAT2": 1,
    "OFFON": 1, "SENSOR": 1, "COLOR_WHITE": 1, "LIGHT_DARK": 1, "LIGHT_BRIGHT": 1,
}
STAGE_TIMEOUT_MS = {
    "POT": 60000, "SELECT": 30000, "UP": 30000, "DOWN": 30000, "FLIP": 30000,
    "DISCONNECT_PROMPT": 60000,
    "POT_B": 60000, "SELECT_B": 30000, "UP_B": 30000, "DOWN_B": 30000, "FLIP_B": 30000,
    "ACCEL_FLAT1": 12000, "ACCEL_FIG8": 25000, "ACCEL_FLAT2": 12000,
    "SUSTAIN": 90000,
    "OFFON": 60000, "SENSOR": 60000,
    "COLOR_WHITE": 12000, "LIGHT_DARK": 10000, "LIGHT_BRIGHT": 10000,
}

POT_LOW_THRESH = 300
POT_HIGH_THRESH = 3800
PORT_SPREAD_THRESHOLD = 2000
KNOWN_ADDRS = {0x3C, 0x53}
SUSTAIN_SAMPLE_PERIOD_MS = 500
ACCEL_SAMPLE_PERIOD_MS = 100
VEML6040_ADDR = 0x10
VEML6040_R = 0x08
VEML6040_G = 0x09
VEML6040_B = 0x0A
VEML6040_W = 0x0B


def _log(f, line):
    f.write(line + "\n")
    f.flush()


def _read_stage():
    try:
        with open(STAGE_PATH) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def _write_stage(i):
    with open(STAGE_PATH, "w") as f:
        f.write(str(i))


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
            # "|"-joined rather than JSON -- no json/ujson dependency needed
            # on-device, and none of our own literal strings contain "|".
            _log(self.log, "SCREEN t=%d lines=%s" % (time.ticks_ms(), "|".join(lines)))


class ServoSweeper:
    """Sweeps back and forth continuously for the whole session -- a visible
    "device is alive and ready" signal, and sustained battery-under-load data
    for the whole run rather than just a momentary check."""

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


def run_pot_stage(display, pot, log, sweeper, label="POT"):
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
            # live raw-value readout so a non-responding sensor is visible
            # immediately, not just inferred from a countdown that never moves
            if last_shown_v is None or abs(v - last_shown_v) > 20:
                display.show("%s x%d  v=%d" % (label, TARGET_REPS[label] - reps, v), "sweep fully",
                             "lo:%s hi:%s" % (reached_low, reached_high))
                last_shown_v = v
        except Exception as e:
            _log(log, "ERROR stage=%s: %s" % (label, e))
        time.sleep_ms(20)
    _log(log, "STAGE_DONE stage=%s" % label)
    return True


def _base_button_label(label):
    return label[:-2] if label.endswith("_B") else label


def run_button_stage(display, label, pins, log, sweeper):
    expected = _base_button_label(label)
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


def run_flip_stage(display, log, sweeper, label="FLIP"):
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


def is_probably_on_usb(battery):
    # No dedicated VBUS-sense pin on this board, so this is a proxy, not a
    # direct measurement: the battery ADC reads distinctly higher whenever
    # USB is actively delivering charge current (see sensors.readbattery()'s
    # 'charging' bucket, and DEVICE_HEALTH_DESIGN.md section 1). Good enough
    # to gate "have you actually unplugged yet?" right after a USB-connected
    # test phase, where the reading is still fresh from active charging.
    return battery.read() > 2850


def shake_head(s):
    """A distinct 'no' gesture -- quick side-to-side -- so 'still on USB'
    reads as a physical refusal to proceed, not just on-screen text."""
    s.write_angle(70)
    time.sleep_ms(150)
    s.write_angle(110)
    time.sleep_ms(150)


def run_disconnect_prompt(display, battery, log, sweeper):
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["DISCONNECT_PROMPT"]:
        if is_probably_on_usb(battery):
            display.show("still on USB --", "unplug it now")
            shake_head(sweeper.s)
        else:
            display.show("thanks! continuing", "in a moment...")
            time.sleep_ms(1500)
            # confirm it's not just a momentary dip -- require it to still
            # read as off-USB after the pause before actually proceeding
            if not is_probably_on_usb(battery):
                _log(log, "STAGE_DONE stage=DISCONNECT_PROMPT")
                return True
    _log(log, "TIMEOUT stage=DISCONNECT_PROMPT")
    return False


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
    last_sample = time.ticks_ms() - ACCEL_SAMPLE_PERIOD_MS
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS[label]:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= ACCEL_SAMPLE_PERIOD_MS:
            try:
                sample = _read_accel_tuple(accel)
                if sample is not None:
                    samples.append(sample)
                    mag = accel_magnitude(sample)
                    _log(log, "ACCEL_SAMPLE stage=%s t=%d accel=%d,%d,%d mag=%d" % (
                        label, now, sample[0], sample[1], sample[2], int(mag)
                    ))
            except Exception as e:
                _log(log, "ERROR stage=%s: %s" % (label, e))
            last_sample = now
        time.sleep_ms(20)

    result = evaluate_accel_motion(samples, mode)
    detail = result.get("detail", {})
    _log(log, "ACCEL_SUMMARY stage=%s status=%s n=%d span=%s mag=%s summary=%s" % (
        label,
        result["status"],
        detail.get("n_samples", len(samples)),
        detail.get("max_axis_span", ""),
        detail.get("median_magnitude", ""),
        result["summary"],
    ))
    display.show(label, result["status"], result["summary"][:16])
    time.sleep_ms(1000)
    _log(log, "STAGE_DONE stage=%s" % label)
    return result["status"] == "pass"


def run_sustain_stage(display, pot, battery, accel, log, sweeper):
    display.show("sustained check", "battery-only,", "just wait...")
    t0 = time.ticks_ms()
    last_sample = time.ticks_ms() - SUSTAIN_SAMPLE_PERIOD_MS
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["SUSTAIN"]:
        sweeper.step()
        now = time.ticks_ms()
        if time.ticks_diff(now, last_sample) >= SUSTAIN_SAMPLE_PERIOD_MS:
            try:
                p = pot.read()
                b_raw = battery.read()
                b_uv = battery.read_uv()
                if accel is not None:
                    x, y, z = accel.xValue, accel.yValue, accel.zValue
                else:
                    x = y = z = None
                _log(log, "SUSTAIN_SAMPLE t=%d pot=%d batt_raw=%d batt_uv=%d accel=%s,%s,%s" % (
                    now, p, b_raw, b_uv, x, y, z
                ))
            except Exception as e:
                _log(log, "ERROR stage=SUSTAIN: %s" % e)
            last_sample = now
        time.sleep_ms(20)
    _log(log, "STAGE_DONE stage=SUSTAIN")
    return True


def log_start_sample(pot, battery, accel, log):
    try:
        p = pot.read()
        b_raw = battery.read()
        b_uv = battery.read_uv()
        sample = _read_accel_tuple(accel)
        if sample is None:
            x = y = z = None
        else:
            x, y, z = sample
        _log(log, "START_SAMPLE t=%d pot=%d batt_raw=%d batt_uv=%d accel=%s,%s,%s" % (
            time.ticks_ms(), p, b_raw, b_uv, x, y, z
        ))
    except Exception as e:
        _log(log, "ERROR stage=START_SAMPLE: %s" % e)


def run_sensor_stage(display, i2c, log, sweeper):
    display.show("plug in a", "sensor now")
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["SENSOR"]:
        sweeper.step()
        found = set(i2c.scan())
        new_addrs = found - KNOWN_ADDRS
        if new_addrs:
            addr = sorted(new_addrs)[0]
            _log(log, "REP stage=SENSOR addr=0x%02x" % addr)
            _log(log, "STAGE_DONE stage=SENSOR")
            display.show("sensor found:", "0x%02x" % addr)
            return True
        time.sleep_ms(300)
    _log(log, "TIMEOUT stage=SENSOR")
    return False


def _read_word_le(i2c, addr, reg):
    data = i2c.readfrom_mem(addr, reg, 2)
    return data[0] | (data[1] << 8)


def run_color_white_stage(display, i2c, log, sweeper):
    if VEML6040_ADDR not in i2c.scan():
        display.show("COLOR_WHITE", "no color sensor")
        _log(log, "SKIP stage=COLOR_WHITE reason=no_veml6040")
        time.sleep_ms(1000)
        return False

    display.show("COLOR_WHITE", "point at white", "hold still")
    samples = []
    t0 = time.ticks_ms()
    last_sample = time.ticks_ms() - 500
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["COLOR_WHITE"]:
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
                _log(log, "ERROR stage=COLOR_WHITE: %s" % e)
            last_sample = now
        time.sleep_ms(20)

    if samples:
        avg = tuple(int(round(sum(s[i] for s in samples) / len(samples))) for i in range(4))
        gains = compute_white_balance_milli(avg[:3])
        _log(log, "COLOR_WHITE_SUMMARY n=%d r=%d g=%d b=%d w=%d wb_milli=%d,%d,%d" % (
            len(samples), avg[0], avg[1], avg[2], avg[3], gains[0], gains[1], gains[2]
        ))
    _log(log, "STAGE_DONE stage=COLOR_WHITE")
    return True


def run_light_stage(display, log, sweeper, label, prompt):
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


def main():
    boot_num_path = "guided_boot_count.txt"
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

    stage_idx = _read_stage()

    with open(LOG_PATH, "a") as log:
        _log(log, "BOOT boot_num=%d reset_cause=%d(%s) resume_stage=%d" % (
            boot_num, cause, cause_name, stage_idx
        ))

        if stage_idx > 0 and STAGES[stage_idx - 1] == "OFFON":
            # we were waiting for a power cycle when this boot happened --
            # that reset IS the confirmation. Nothing else to detect.
            _log(log, "REP stage=OFFON rep=1 (confirmed by this reboot)")
            _log(log, "STAGE_DONE stage=OFFON")

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
        sweeper = ServoSweeper(servo.Servo(Pin(2)), log=log)

        accel = None
        try:
            import adxl345
            accel = adxl345.ADXL345(i2c)
        except Exception as e:
            _log(log, "NOTE accelerometer unavailable: %s" % e)

        log_start_sample(pot, battery, accel, log)

        while stage_idx < len(STAGES):
            stage = STAGES[stage_idx]
            if stage in ("POT", "POT_B"):
                run_pot_stage(display, pot, log, sweeper, label=stage)
            elif stage in ("SELECT", "SELECT_B", "UP", "UP_B", "DOWN", "DOWN_B"):
                run_button_stage(display, stage, button_pins, log, sweeper)
            elif stage in ("FLIP", "FLIP_B"):
                run_flip_stage(display, log, sweeper, label=stage)
            elif stage == "DISCONNECT_PROMPT":
                run_disconnect_prompt(display, battery, log, sweeper)
            elif stage in ("ACCEL_FLAT1", "ACCEL_FIG8", "ACCEL_FLAT2"):
                run_accel_stage(display, accel, log, sweeper, stage)
            elif stage == "SUSTAIN":
                run_sustain_stage(display, pot, battery, accel, log, sweeper)
            elif stage == "OFFON":
                display.show("power cycle", "the board now", "(OFF then ON)")
                stage_idx += 1
                _write_stage(stage_idx)
                _log(log, "WAITING_FOR_REBOOT stage=OFFON")
                return  # nothing more to do this boot -- resumes on next boot
            elif stage == "SENSOR":
                run_sensor_stage(display, i2c, log, sweeper)
            elif stage == "COLOR_WHITE":
                run_color_white_stage(display, i2c, log, sweeper)
            elif stage == "LIGHT_DARK":
                run_light_stage(display, log, sweeper, stage, "cover light")
            elif stage == "LIGHT_BRIGHT":
                run_light_stage(display, log, sweeper, stage, "point at light")
            stage_idx += 1
            _write_stage(stage_idx)

        display.show("ALL DONE", "reconnect USB", "to read results")
        _log(log, "SEQUENCE_COMPLETE")


main()
