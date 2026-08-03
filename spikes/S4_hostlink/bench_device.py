"""
S4 host-link benchmark -- DEVICE side.

Answers: how fast can a USB-connected SmartMotor exchange data with a laptop?
Measures round-trip latency, sustained streaming rate, raw throughput, and the
cost of the ADC-sampling pattern webconnect.py uses today.

This file is a THROWAWAY EXPERIMENT. It is not part of the deployed activity
and is not in EngAI_MANIFEST.txt.

------------------------------------------------------------------------------
HOW TO RUN

    .venv/bin/mpremote cp spikes/S4_hostlink/bench_device.py :
    .venv/bin/mpremote exec --no-follow "import bench_device"
    .venv/bin/python3 spikes/S4_hostlink/bench_host.py

If the device stops the moment mpremote disconnects, fall back to:

    .venv/bin/mpremote cp main.py :main_real.py      # back up the real main
    .venv/bin/mpremote cp spikes/S4_hostlink/bench_device.py :main.py
    # ... run the host script, then RESTORE:
    .venv/bin/mpremote cp main_real.py :main.py

------------------------------------------------------------------------------
SAFETY NOTE

This script calls micropython.kbd_intr(-1), which DISABLES Ctrl-C on the serial
port -- otherwise a 0x03 byte in binary data would kill the program. While it is
running you cannot interrupt it from the REPL. Two escapes are provided:

  1. The host sends "Q\n", which restores Ctrl-C and exits.
  2. A watchdog exits automatically after WATCHDOG_MS (default 3 minutes).

If both fail, press the physical reset button on the board. Nothing here writes
to flash, so a reset always leaves the device in a clean state.
"""

import sys
import time
import micropython
import uselect
from machine import Pin, ADC

WATCHDOG_MS = 300_000  # auto-exit so a wedged bench can't lock the board.
# Note: kbd_intr(-1) means mpremote cannot interrupt us while this loop owns
# stdin, so the watchdog is the only software recovery. Keep it short enough
# that a wedge is an annoyance, not a brick.


def _log(*parts):
    """Diagnostics go out as '# ...' lines so the host can skip them."""
    sys.stdout.write("# " + " ".join(str(p) for p in parts) + "\n")


class Bench:
    def __init__(self):
        self.poll = uselect.poll()
        self.poll.register(sys.stdin, uselect.POLLIN)
        self.pot = ADC(Pin(3))  # on-board potentiometer; always present
        self.pot.atten(ADC.ATTN_11DB)
        self.read_mode = "readline"
        self.started_ms = time.ticks_ms()

    # -- command reading -----------------------------------------------------
    # Two strategies, so we can measure what webconnect.py's byte-at-a-time
    # approach actually costs versus a single C-level readline().

    def read_command(self, timeout_ms=100):
        if not self.poll.poll(timeout_ms):
            return None
        if self.read_mode == "readline":
            return sys.stdin.readline()
        # bytewise: what webconnect.py does today -- one poll+read per character
        buf = []
        while True:
            ch = sys.stdin.read(1)
            if ch is None or ch == "\n":
                break
            buf.append(ch)
            if not self.poll.poll(50):  # sender stalled mid-line
                break
        return "".join(buf) + "\n"

    # -- individual benchmarks ----------------------------------------------

    def cmd_echo(self, arg):
        """RTT probe: bounce the payload straight back."""
        sys.stdout.write("E " + arg + "\n")

    def cmd_stream(self, count, period_us):
        """Free-running stream at a fixed cadence.

        Reports how late it ran, which is the number that matters: if the USB
        write blocks, `max_late` grows and the cadence is not real.
        """
        seq = 0
        max_late = 0
        next_t = time.ticks_us()
        t0 = next_t
        while seq < count:
            now = time.ticks_us()
            late = time.ticks_diff(now, next_t)
            if late < 0:
                continue  # busy-wait to the deadline; sleep_us is too coarse
            if late > max_late:
                max_late = late
            sys.stdout.write("S %d %d %d\n" % (seq, now, self.pot.read()))
            seq += 1
            next_t = time.ticks_add(next_t, period_us)
        elapsed = time.ticks_diff(time.ticks_us(), t0)
        sys.stdout.write("SDONE %d %d %d\n" % (count, elapsed, max_late))

    def cmd_throughput(self, count):
        """Push lines as fast as the link allows -- the raw ceiling."""
        t0 = time.ticks_us()
        payload = "T %d 0123456789012345678901234567890123456789\n"
        for i in range(count):
            sys.stdout.write(payload % i)
        elapsed = time.ticks_diff(time.ticks_us(), t0)
        sys.stdout.write("TDONE %d %d %d\n" % (count, elapsed, len(payload)))

    def cmd_adc(self, count):
        """Cost of N ADC reads.

        webconnect.readSensor() does 1000 reads + a sort on EVERY message, and
        sensors.readpoint() does 200. If this number is large, that -- not the
        USB link -- is the real latency budget.
        """
        t0 = time.ticks_us()
        acc = 0
        for _ in range(count):
            acc += self.pot.read()
        read_us = time.ticks_diff(time.ticks_us(), t0)

        t1 = time.ticks_us()
        samples = [self.pot.read() for _ in range(count)]
        samples.sort()
        full_us = time.ticks_diff(time.ticks_us(), t1)

        sys.stdout.write("ADONE %d %d %d %d\n" % (count, read_us, full_us, acc // count))

    def cmd_ticks(self):
        """Resolution and overhead of the device clock itself."""
        t0 = time.ticks_us()
        for _ in range(1000):
            time.ticks_us()
        overhead = time.ticks_diff(time.ticks_us(), t0)
        sys.stdout.write("RDONE %d\n" % overhead)

    # -- main loop -----------------------------------------------------------

    def run(self):
        _log("bench_device ready; watchdog", WATCHDOG_MS, "ms")
        while True:
            if time.ticks_diff(time.ticks_ms(), self.started_ms) > WATCHDOG_MS:
                _log("watchdog expired")
                return

            line = self.read_command()
            if not line:
                continue
            line = line.strip()
            if not line:
                continue

            parts = line.split()
            cmd = parts[0]
            try:
                if cmd == "E":
                    self.cmd_echo(line[2:] if len(line) > 2 else "")
                elif cmd == "S":
                    self.cmd_stream(int(parts[1]), int(parts[2]))
                elif cmd == "T":
                    self.cmd_throughput(int(parts[1]))
                elif cmd == "A":
                    self.cmd_adc(int(parts[1]))
                elif cmd == "R":
                    self.cmd_ticks()
                elif cmd == "M":
                    self.read_mode = parts[1]
                    sys.stdout.write("MDONE %s\n" % self.read_mode)
                elif cmd == "P":  # keepalive / watchdog kick
                    self.started_ms = time.ticks_ms()
                    sys.stdout.write("PDONE\n")
                elif cmd == "Q":
                    sys.stdout.write("QDONE\n")
                    return
                else:
                    _log("unknown command", cmd)
            except Exception as e:  # never die mid-bench
                _log("error in", cmd, repr(e))


def main():
    try:
        micropython.kbd_intr(-1)  # 0x03 in the stream must not kill us
    except AttributeError:
        _log("kbd_intr unavailable; binary payloads containing 0x03 will break")
    try:
        Bench().run()
    finally:
        try:
            micropython.kbd_intr(3)  # always hand Ctrl-C back
        except AttributeError:
            pass
        _log("bench_device exited")


main()
