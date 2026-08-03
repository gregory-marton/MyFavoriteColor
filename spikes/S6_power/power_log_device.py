"""
S6 power-trial flight recorder -- DEVICE side.

Runs standalone with NO USB connection required, so it can instrument a
battery-only power trial that the host has no serial link to observe. Logs
to power_log.txt on flash, which survives a reset -- so if the board browns
out mid-trial, the reboot itself shows up as a new "BOOT" line appearing in
the middle of the log, with the reset_cause that caused it. That's the
signal a battery-only trial otherwise can't produce at all.

Also drives a deliberate servo sweep partway through the session (not just
passive monitoring), so the same log doubles as B003 load-step data: the
battery reading immediately before vs. during the sweep gives a real
rest-vs-loaded sag figure for free, from whatever power configuration this
trial is testing -- exactly the "does the servo drain the battery too much"
question, measured under the actual power conditions being tested rather
than only on a bench.

------------------------------------------------------------------------------
HOW TO RUN

    .venv/bin/mpremote cp main.py :main_real_backup.py         # save the real main
    .venv/bin/mpremote cp spikes/S6_power/power_log_device.py :main.py
    .venv/bin/mpremote reset
    # now disconnect USB (or whatever power config you're testing) and do the
    # activities: sweep the pot, press each button, figure-eight the board.
    # reconnect USB when done, then:
    .venv/bin/mpremote fs cp :power_log.txt spikes/S6_power/
    ./spikes/S6_power/read_power_log.py spikes/S6_power/power_log.txt
    # afterwards, restore the original firmware:
    .venv/bin/mpremote cp main_real_backup.py :main.py
    .venv/bin/mpremote reset
    .venv/bin/mpremote fs rm :power_log.txt
    .venv/bin/mpremote fs rm :main_real_backup.py

------------------------------------------------------------------------------
SAFETY NOTE

No USB connection needed or expected while this runs -- that's the point.
There is no way to send it a stop command, so it stops itself after
MAX_SAMPLES (a bounded, known log size) rather than running forever. If you
need to stop it early, press the physical reset button: nothing here writes
to flash except appending to one small log file, so a reset always leaves
the device recoverable via the restore steps above.
"""

import time
import machine
from machine import Pin, ADC, SoftI2C
import servo

LOG_PATH = "power_log.txt"
BOOT_COUNT_PATH = "power_log_boot_count.txt"
SAMPLE_PERIOD_MS = 250
MAX_SAMPLES = 200  # ~50s of logging total, across however many boots it takes
SERVO_SWEEP_AT_SAMPLE = 40  # ~10s in -- gives the human time to already be interacting


def _log(f, line):
    f.write(line + "\n")
    f.flush()


def _boot_number():
    try:
        with open(BOOT_COUNT_PATH) as f:
            n = int(f.read().strip())
    except (OSError, ValueError):
        n = 0
    n += 1
    with open(BOOT_COUNT_PATH, "w") as f:
        f.write(str(n))
    return n


def _samples_logged_so_far():
    try:
        with open(LOG_PATH) as f:
            return sum(1 for line in f if line.startswith("S "))
    except OSError:
        return 0


def main():
    boot_num = _boot_number()
    cause = machine.reset_cause()
    names = {getattr(machine, n): n for n in dir(machine) if n.endswith("_RESET")}
    cause_name = names.get(cause, "UNKNOWN")

    already_logged = _samples_logged_so_far()

    with open(LOG_PATH, "a") as f:
        _log(f, "BOOT boot_num=%d reset_cause=%d(%s) uid=%s" % (
            boot_num, cause, cause_name, "".join("%02x" % b for b in machine.unique_id())
        ))

        if already_logged >= MAX_SAMPLES:
            _log(f, "DONE already reached MAX_SAMPLES=%d across prior boots" % MAX_SAMPLES)
            return

        pot = ADC(Pin(3))
        pot.atten(ADC.ATTN_11DB)
        battery = ADC(Pin(4))
        battery.atten(ADC.ATTN_11DB)
        up = Pin(10, Pin.IN)
        down = Pin(8, Pin.IN)
        select = Pin(9, Pin.IN)

        accel = None
        try:
            i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
            import adxl345
            accel = adxl345.ADXL345(i2c)
        except Exception as e:
            _log(f, "NOTE accelerometer unavailable: %s" % e)

        s = None
        try:
            s = servo.Servo(Pin(2))
        except Exception as e:
            _log(f, "NOTE servo unavailable: %s" % e)

        n = already_logged
        while n < MAX_SAMPLES:
            if s is not None and n == SERVO_SWEEP_AT_SAMPLE:
                _log(f, "SWEEP_START rest_batt_raw=%d rest_batt_uv=%d" % (battery.read(), battery.read_uv()))
                for angle in (0, 45, 90, 135, 180, 90, 0):
                    s.write_angle(angle)
                    time.sleep_ms(200)
                    _log(f, "SWEEP_POINT angle=%d batt_raw=%d batt_uv=%d" % (angle, battery.read(), battery.read_uv()))
                s.write_us(0)  # release -- don't hold torque/current after the test
                _log(f, "SWEEP_END rest_batt_raw=%d rest_batt_uv=%d" % (battery.read(), battery.read_uv()))
            try:
                p = pot.read()
                b_raw = battery.read()
                b_uv = battery.read_uv()
                btn = (up.value(), down.value(), select.value())
                if accel is not None:
                    x, y, z = accel.xValue, accel.yValue, accel.zValue
                else:
                    x = y = z = None
                _log(f, "S n=%d t=%d pot=%d batt_raw=%d batt_uv=%d btn=%d,%d,%d accel=%s,%s,%s" % (
                    n, time.ticks_ms(), p, b_raw, b_uv, btn[0], btn[1], btn[2], x, y, z
                ))
            except Exception as e:
                _log(f, "ERROR sample %d: %s" % (n, e))
            n += 1
            time.sleep_ms(SAMPLE_PERIOD_MS)

        _log(f, "DONE reached MAX_SAMPLES=%d" % MAX_SAMPLES)


main()
