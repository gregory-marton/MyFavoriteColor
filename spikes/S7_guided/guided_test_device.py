"""
S7 guided hardware test -- DEVICE side.

Runs the D-POT/D-BTN/D-PORT/D-PWR human-assisted checks as one on-device
guided sequence: the OLED itself tells you what to do and counts down
repetitions as it detects them ("POT x3" -> "POT x2" -> "POT x1" -> next
stage), instead of a terminal prompt with no feedback. That's the fix for
the earlier problem where a blind "press buttons now" gave no indication
whether anything was actually detected.

Sequence: sweep the pot fully back and forth 3 times, press SELECT 3 times,
press UP 3 times, flip the analog/I2C toggle 3 times -- then a prompt to
disconnect USB and repeat all four (this is what actually exercises
battery-only power; touching a button while on USB proves little about the
battery, since USB power dominates), then a 90s sustained passive-logging
period on battery alone to give a slow sag or intermittent fault time to
show up, then a power-cycle (OFF then ON), then plug in an I2C sensor.

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

LOG_PATH = "guided_log.txt"
STAGE_PATH = "guided_stage.txt"

STAGES = [
    "POT", "SELECT", "UP", "FLIP",
    "DISCONNECT_PROMPT",
    "POT_B", "SELECT_B", "UP_B", "FLIP_B",
    "SUSTAIN",
    "OFFON", "SENSOR",
]
TARGET_REPS = {
    "POT": 3, "SELECT": 3, "UP": 3, "FLIP": 3,
    "POT_B": 3, "SELECT_B": 3, "UP_B": 3, "FLIP_B": 3,
    "OFFON": 1, "SENSOR": 1,
}
STAGE_TIMEOUT_MS = {
    "POT": 60000, "SELECT": 30000, "UP": 30000, "FLIP": 30000,
    "DISCONNECT_PROMPT": 60000,
    "POT_B": 60000, "SELECT_B": 30000, "UP_B": 30000, "FLIP_B": 30000,
    "SUSTAIN": 90000,
    "OFFON": 60000, "SENSOR": 60000,
}

POT_LOW_THRESH = 300
POT_HIGH_THRESH = 3800
PORT_SPREAD_THRESHOLD = 2000
KNOWN_ADDRS = {0x3C, 0x53}
SUSTAIN_SAMPLE_PERIOD_MS = 500


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
    def __init__(self, i2c):
        self.d = ssd1306.SSD1306_I2C(128, 64, i2c)

    def show(self, *lines):
        self.d.fill(0)
        for row, text in enumerate(lines):
            self.d.text(text, 4, 8 + row * 12, 1)
        self.d.show()


class ServoSweeper:
    """Sweeps back and forth continuously for the whole session -- a visible
    "device is alive and ready" signal, and sustained battery-under-load data
    for the whole run rather than just a momentary check."""

    def __init__(self, s, period_ms=1000):
        self.s = s
        self.period_ms = period_ms
        self.angle = 0
        self.t0 = time.ticks_ms()
        self.s.write_angle(self.angle)

    def step(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.t0) > self.period_ms:
            self.angle = 180 if self.angle == 0 else 0
            self.s.write_angle(self.angle)
            self.t0 = now


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


def run_button_stage(display, label, pin, log, sweeper):
    prev = pin.value()
    reps = 0
    display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "press %s" % label)
    t0 = time.ticks_ms()
    while reps < TARGET_REPS[label]:
        sweeper.step()
        if time.ticks_diff(time.ticks_ms(), t0) > STAGE_TIMEOUT_MS[label]:
            _log(log, "TIMEOUT stage=%s reps=%d" % (label, reps))
            return False
        v = pin.value()
        if prev == 1 and v == 0:
            reps += 1
            _log(log, "REP stage=%s rep=%d" % (label, reps))
            display.show("%s x%d" % (label, TARGET_REPS[label] - reps), "press %s" % label)
        prev = v
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


def run_disconnect_prompt(display, select, log, sweeper):
    display.show("unplug USB now,", "then press SELECT", "to continue")
    prev = select.value()
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < STAGE_TIMEOUT_MS["DISCONNECT_PROMPT"]:
        sweeper.step()
        v = select.value()
        if prev == 1 and v == 0:
            _log(log, "STAGE_DONE stage=DISCONNECT_PROMPT")
            return True
        prev = v
        time.sleep_ms(20)
    _log(log, "TIMEOUT stage=DISCONNECT_PROMPT")
    return False


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
        display = Display(i2c)
        pot = ADC(Pin(3))
        pot.atten(ADC.ATTN_11DB)
        battery = ADC(Pin(4))
        battery.atten(ADC.ATTN_11DB)
        up = Pin(10, Pin.IN)
        select = Pin(9, Pin.IN)
        sweeper = ServoSweeper(servo.Servo(Pin(2)))

        accel = None
        try:
            import adxl345
            accel = adxl345.ADXL345(i2c)
        except Exception as e:
            _log(log, "NOTE accelerometer unavailable: %s" % e)

        while stage_idx < len(STAGES):
            stage = STAGES[stage_idx]
            if stage in ("POT", "POT_B"):
                run_pot_stage(display, pot, log, sweeper, label=stage)
            elif stage in ("SELECT", "SELECT_B"):
                run_button_stage(display, stage, select, log, sweeper)
            elif stage in ("UP", "UP_B"):
                run_button_stage(display, stage, up, log, sweeper)
            elif stage in ("FLIP", "FLIP_B"):
                run_flip_stage(display, log, sweeper, label=stage)
            elif stage == "DISCONNECT_PROMPT":
                run_disconnect_prompt(display, select, log, sweeper)
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
            stage_idx += 1
            _write_stage(stage_idx)

        display.show("ALL DONE", "reconnect USB", "to read results")
        _log(log, "SEQUENCE_COMPLETE")


main()
