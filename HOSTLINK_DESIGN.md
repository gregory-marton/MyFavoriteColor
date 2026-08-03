# SmartMotor Host Link + Sensor Calibration — Design Doc

Status: **proposal / for discussion.** The measurement spike (§2) is written and
ready to run; nothing else is built.
Companion docs: `EMULATOR_DESIGN.md`, `EMULATOR_TASKS.md`.

Two connected questions:

1. Can a USB-connected SmartMotor act as live sensors and actuators for
   on-laptop compute — torch training at one end, an accelerometer-driven
   pinball game at the other?
2. Can that same link be used to *characterise a new sensor*, so its real
   behaviour can be turned into an emulator plug-in?

---

## 0. Verdict

**Question 1: yes, and it already works today.** `webconnect.py` is a working
existence proof sitting in this repo. It reads JSON from `sys.stdin` (polled via
`uselect`) and writes JSON to `sys.stdout`, over the USB serial connection, in a
loop — a browser already drives the motor and reads the sensor through it. The
question was never *whether*; it is *how fast*, and that is measurable rather
than arguable.

The hardware is favourable. The board enumerates as VID `0x303A`, PID `0x1001`,
"USB JTAG/serial debug unit" — the ESP32-C3's **native USB Serial/JTAG
peripheral**, not a UART bridge. There is no 115200-baud ceiling; the `baudrate`
argument is ignored by the CDC stack. Full-speed USB gives 1 ms frames, so the
latency floor is a couple of milliseconds, not tens.

For calibration, that is more than enough: calibration is throughput- and
*timestamp*-bound, not latency-bound, and the device can timestamp its own
samples. For a pinball game you need tilt at ~60 Hz with under ~30 ms of
lag — a low bar if the link behaves as expected.

**Question 2: yes for analog parts and for documented I2C parts; partially for
undocumented I2C parts.** Fitting a response curve, a noise model, and a time
constant from swept measurements is routine. Blind reverse-engineering of an
undocumented I2C register map is a research exercise with real failure modes
(§9) — the honest workflow is datasheet-first, measurement-second, with probing
to fill gaps.

**The interesting part** is that the two projects close a loop:

```
   emulator  ──(test bed, no hardware needed)──>  host library
       ^                                               │
       │                                               v
   calibration JSON  <──(fit real measurements)── calibration harness
                                                       │
                              (validate model vs held-out real data)
```

The emulator lets you develop and CI the host library without a board; the host
library lets you calibrate real sensors; the calibration output makes the
emulator faithful. Each project makes the other cheaper. That argues for
interleaving them rather than finishing one first (§7, §12).

---

## 1. What `webconnect.py` proves, and why it isn't the answer

**Proves:** bidirectional JSON over USB serial works, the browser can drive the
motor, the device can stream sensor readings back, and the whole thing survives a
classroom.

**Why it can't be the real-time library**, in descending order of cost:

1. **`readSensor()` takes 1000 ADC samples, sorts them, and takes the middle
   300 — on every single message.** In MicroPython, a 1000-element sort plus
   1000 ADC reads is likely tens of milliseconds. This is almost certainly the
   dominant latency in the whole system, and it is nothing to do with USB. The
   spike measures it directly (`A` command), because if this is 40 ms then no
   amount of protocol tuning matters.
2. **Byte-at-a-time reads.** `readSerial()` does one `poll()` + one
   `sys.stdin.read(1)` per character, and `main()` reassembles JSON by watching
   for `{` and `}`. Each character costs a Python-level loop iteration. A single
   C-level `sys.stdin.readline()` should be far cheaper — the spike measures
   both (`M readline` / `M bytewise`) so the difference is a number, not a
   belief.
3. **The brace counter is not a parser.** `append` is set False on the *first*
   `}`, so any nested JSON object truncates the message. The protocol is
   accidentally limited to flat dictionaries.
4. **Strictly request/response.** The host must poll for every sample. There is
   no free-running stream, so the sample rate is capped at the round-trip rate
   and every sample carries a full RTT of lag.
5. **No timestamps.** Samples arrive with no device-side time, so you cannot
   tell a 10 ms gap from a 40 ms gap, and you cannot recover true intervals from
   arrival times because USB batches. This alone disqualifies it for
   calibration, where knowing *when* a sample was taken is the whole point.
6. **Latency is untracked and unbounded.** `motor.write_angle()` is called on
   every message even when the angle hasn't changed.

None of this is a criticism of `webconnect.py`, which does its job. It is a
different job. **Leave `webconnect.py` untouched** — the existing web UI depends
on it, and it stays the compatibility path.

---

## 2. How to find out: the S4 spike — **run 2026-08-03, see `spikes/S4_hostlink/FINDINGS.md`**

Written and in the repo:

- `spikes/S4_hostlink/bench_device.py` — device side
- `spikes/S4_hostlink/bench_host.py` — host side, uses the pyserial already in
  `.venv` via esptool

```bash
.venv/bin/mpremote cp main.py :main_real_backup.py         # save the real main
.venv/bin/mpremote cp spikes/S4_hostlink/bench_device.py :main.py
.venv/bin/mpremote reset
./spikes/S4_hostlink/bench_host.py --json findings.json
# afterwards: .venv/bin/mpremote cp main_real_backup.py :main.py && .venv/bin/mpremote reset
```

`exec --no-follow "import bench_device"` looks appealing but does not reliably
work in practice — the device kept running its existing `main.py` loop
underneath rather than handing off. The swap-`main.py`-and-reset approach above
is what actually ran. `mpremote` and the host script cannot hold the port at
the same time. The device script disables Ctrl-C (`kbd_intr(-1)`, needed so
binary payloads can't kill the program), so it carries a 5-minute watchdog and
a `Q` quit command; the physical reset button is the backstop. It writes
nothing to flash beyond the temporary `main.py` swap, reversed at the end.

Results: small, frequent messages (the games/sensor-streaming case) sustained
500 Hz with zero drops and ~15µs device-side lateness — comfortably past the
thresholds below. One assumption here needs revising: the link measured out at
~11 kB/s, matching real ~115200-baud serial timing, not a baud-ceiling-free
full-speed USB link. Doesn't change the verdict for control/streaming, but bulk
batch transfers are bandwidth-bound at that rate, not just latency-bound.

### What each measurement decides

| Measurement | Decides |
| --- | --- |
| **ADC cost** at 1/100/200/1000 samples | Whether the bottleneck is USB at all. If 1000 reads ≫ 10 ms, the fix is in the sampling strategy, not the protocol. |
| **RTT**, readline vs bytewise, 8/64/256 B | The floor for closed-loop control, and what byte-at-a-time reading actually costs. |
| **Throughput** (lines/s, kB/s) | The ceiling on streaming rate × payload size. |
| **Streaming** at 50/100/200/500 Hz — drops, device lateness, host gap jitter | The real answer for games and control. `max_late_us` exceeding the period means the *device* couldn't keep up; drops with the device on time mean the *link or host* couldn't. |

### Decision thresholds

Set these before looking at the numbers, so the result isn't rationalised:

- **RTT median < 10 ms, p95 < 20 ms** → closed-loop control at 50 Hz is
  comfortable; proceed with the full design.
- **Sustained 100 Hz streaming with zero drops** → accelerometer games are
  comfortable; a pinball demo is realistic.
- **RTT median 10–30 ms** → streaming-only design; drop synchronous RPC from the
  student-facing API for anything time-critical, and say so plainly.
- **RTT median > 30 ms, or 50 Hz streaming drops** → stop and reconsider.
  Investigate whether MicroPython's USB CDC write path is the blocker before
  concluding it's impossible; consider batch-capture-then-dump (§5) as the
  fallback, which is enough for calibration even if it is not enough for games.

Record results in `spikes/S4_hostlink/FINDINGS.md`, including the MicroPython
version (`v1.25.0` per the firmware binary in this repo), host OS, and whether a
USB hub was in the path. **Re-run on a student laptop**, not only on the
development machine — USB stacks and CPU scheduling differ, and the classroom
case is the one that matters.

---

## 3. Architecture

```
   Laptop                                        SmartMotor (ESP32-C3)
   ┌──────────────────────────────┐              ┌────────────────────────┐
   │ student code                 │              │ hostlink.py            │
   │   pinball.py / train.py      │              │  ├ sampler (Timer)     │
   │        │                     │              │  ├ actuator queue      │
   │ smartmotor (host library)    │   USB CDC    │  ├ frame codec         │
   │   ├ SmartMotor facade        │<────────────>│  └ command dispatch    │
   │   ├ channels (accel/pot/...) │  binary +    │                        │
   │   ├ Recorder / stream()      │  JSON ctrl   │ shares drivers with    │
   │   ├ clock sync               │              │ sensors.py, servo.py   │
   │   └ Transport                │              └────────────────────────┘
   │       ├ SerialTransport      │
   │       └ EmulatorTransport ───┼──> the emulator (EMULATOR_DESIGN.md)
   └──────────────────────────────┘
```

**Device side — `hostlink.py`** (new; a fourth activity alongside `myfavcolor`,
`standalone`, `webconnect`). Selected by `main.choose_activity` under a new
`prefs.mode == 2`, or by a startup button chord. It:

- runs a periodic sampler (a `machine.Timer`) that reads the enabled channels
  and stamps each sample with `time.ticks_us()`;
- streams sample frames to the host without being asked;
- accepts command frames (set motor angle, set channel mask and rate, write to
  the screen, ping);
- **owns stdout exclusively.** Anything else printing to stdout corrupts the
  stream — and `myfavcolor.screen()` prints every changed screen. Hostlink mode
  must therefore be exclusive, and `hostlink.py` should install a guard that
  redirects or drops stray prints.

**Host side — `smartmotor`** (new Python package, installable with `pip install
smartmotor`, stdlib-only core). Two layers: a friendly facade for students, and
a `Transport` seam underneath so the same code runs against real hardware or
against the emulator.

---

## 4. Protocol

Line-delimited JSON is wonderful for debugging and too slow for 200 Hz of
multi-channel data. Use both, deliberately:

**Control channel — JSON lines.** Commands and replies, human-readable, one
object per line, `\n`-terminated. Nested objects are fine (we will parse
properly, unlike the brace counter). Low rate, so the cost doesn't matter, and a
student can watch it in a terminal.

**Data channel — binary frames.** For sample streams:

```
  0xA5  type:u8  len:u16le  payload[len]  crc8
```

Resync by scanning for the magic byte and validating length + CRC. No escaping
needed since the length is explicit. Frame types: `SAMPLE`, `BATCH`, `LOG`,
`REPLY`, `EVENT`. `LOG` carries device text, so device diagnostics survive
inside the binary stream instead of corrupting it.

Sample payload: `seq:u32, t_us:u32, then one value per enabled channel` in a
layout the host learns from a `describe` reply at connect time. Channels declare
their own dtype (`u12` for ADC, `i16` for accel axes, `u16` for colour counts),
so a 3-axis accel + pot sample is 8 bytes of data + 8 of header + 4 of framing
rather than ~60 bytes of JSON.

**Requires `micropython.kbd_intr(-1)`** so a `0x03` byte in the data doesn't
raise KeyboardInterrupt. That means Ctrl-C no longer stops the device: provide
an explicit `reset` command, a watchdog, and document the physical reset button.
The host library should re-enable it on clean disconnect.

**Debug mode:** `SmartMotor.connect(debug=True)` forces all-JSON, so a student
who wants to see the traffic can. Slower, obviously; that's the trade.

---

## 5. Timing, clock sync, and three transfer modes

The device timestamps every sample with `time.ticks_us()`. **MicroPython's
`ticks_us` wraps** (typically at 2³⁰ µs ≈ 17.9 minutes) — the host must
accumulate with wrap detection and never subtract raw values. This is a classic
source of "the data looks fine for 18 minutes" bugs.

**Clock sync** (NTP-style, needed for calibration to be meaningful): host sends
`ping` at host-time `t1`; device replies with its `ticks_us` as `t2`; host
receives at `t3`. Offset ≈ `t2 − (t1+t3)/2`, uncertainty ≈ `(t3−t1)/2`. Repeat
periodically and fit a line to get both offset and **drift** — the ESP32's clock
and the laptop's differ by tens of ppm, which is minutes-scale-visible.

**Three transfer modes**, matched to three jobs:

| Mode | Shape | For |
| --- | --- | --- |
| **RPC** | request → reply | setup, one-off reads, `sm.motor.angle = 90` |
| **Stream** | device free-runs at a set rate, host reads latest | games, closed-loop control, live plots |
| **Batch** | device captures N samples into RAM at exact intervals, then dumps | **calibration** — removes host and USB jitter entirely |

Batch mode is the one that makes calibration trustworthy. Sampling into a
preallocated `bytearray` at a Timer-driven cadence and dumping afterwards means
the intervals are as good as the device's clock, with no USB scheduling in the
path. RAM caps it (an ESP32-C3 has a few hundred KB; budget ~10k samples), which
is plenty for a calibration sweep.

---

## 6. Student-facing API

The design target: a student who can write a `while` loop can drive a motor from
an accelerometer. Boring, obvious, hard to misuse.

```python
from smartmotor import SmartMotor

sm = SmartMotor.connect()          # auto-detect port; connect("emu") for emulator

sm.motor.angle = 90                # actuator, degrees
print(sm.pot.value)                # 0.0 - 1.0
print(sm.accel.roll, sm.accel.pitch)
sm.screen.text("Hello!")
```

Pinball — the motivating case:

```python
sm = SmartMotor.connect()
sm.stream(rate=100, channels=["accel"])     # device free-runs

while game.running:
    tilt = sm.accel.roll                    # always the freshest sample
    ball.vx += tilt * 0.4
    game.tick()
```

`sm.accel.roll` inside a stream returns the most recent sample without blocking;
a background reader thread keeps it current. Students never see frames, threads,
or sequence numbers.

Torch, both patterns:

```python
# (a) collect a dataset
with sm.record(rate=200, channels=["accel", "pot"]) as rec:
    input("Wave it around, then press Enter...")
data = rec.to_numpy()                        # (N, 5): t, ax, ay, az, pot

# (b) closed-loop: model in the middle of the control loop
for sample in sm.stream(rate=50, channels=["accel"]):
    with torch.no_grad():
        angle = model(torch.tensor(sample.accel)).item()
    sm.motor.angle = angle
```

`stream()` as a generator is the right shape for control loops; `record()` as a
context manager is the right shape for datasets. numpy/torch are **optional
extras** — the core library imports neither, so a student without them installed
can still play pinball.

Errors must be blunt and actionable: "No SmartMotor found. Is it plugged in?
Ports I can see: ..." and "The device is running myfavcolor, not hostlink. Hold
UP+DOWN at startup, or run `smartmotor flash-hostlink`."

---

## 7. Emulator interoperation (the interleave)

The `Transport` seam is what ties the two projects together, and it pays off in
three directions:

1. **Develop the host library with no hardware.** `SmartMotor.connect("emu")`
   talks to the emulator instead of a serial port. Students can write and debug
   a pinball game on the bus, then plug in a board and change nothing. This also
   makes the host library CI-testable, which a hardware-only library never is.
2. **Dry-run calibration procedures.** A calibration procedure is a script that
   asks a human to do things. Debugging it against a real human and a real
   sensor is slow and annoying. Run it against the emulator first, where every
   step is instant, and only then take it to the bench.
3. **Validate the fitting code against ground truth.** Set an emulator sensor's
   parameters to known values, run the whole calibration procedure against the
   emulator, and assert the fit *recovers those values*. This tests the
   estimator itself — otherwise a bug in the curve fit silently becomes a
   "measurement" of the real sensor. This is the single highest-value test in
   the calibration project, and it is only possible because the emulator exists.

Ordering implication: **the emulator's Phase 1–3 (through T019) should land
before the calibration harness**, but the host library can start as soon as
the S4 spike reports. Concretely: run S4 now, build `hostlink.py` + the host
library in parallel with emulator Phase 1–2, and start calibration once both the
emulator's sensor plug-ins and the host library's batch mode exist.

---

## 8. The calibration harness

Goal: turn a physical sensor plus a cooperative human into a
`smotoremu/sensors/data/<part>.json` calibration file and a plug-in skeleton,
with an honest error bar.

### Shape

A **procedure** is a declarative JSON document — a sequence of steps, each
either a human instruction, an automated capture, or a fit. The harness runs it,
prompting the human and driving the device.

```json
{
  "part_number": "Grove-LS06-S",
  "interface": "analog",
  "reference": "phone lux meter app, held at the sensor face",
  "steps": [
    {"type": "prompt",  "text": "Cover the sensor completely, then press Enter."},
    {"type": "capture", "name": "dark", "rate": 500, "n": 2000},
    {"type": "prompt",  "text": "Uncover. Set the lamp to its lowest setting.",
                        "ask": {"lux": "float"}},
    {"type": "capture", "name": "point", "rate": 500, "n": 2000, "repeat_until_done": true},
    {"type": "sweep",   "name": "gradient", "motor_from": 0, "motor_to": 180,
                        "step_deg": 2, "settle_ms": 300, "n_per_step": 200},
    {"type": "fit",     "model": "monotone_piecewise", "x": "lux", "y": "raw"},
    {"type": "fit",     "model": "noise", "from": "dark"},
    {"type": "fit",     "model": "step_response", "from": "gradient"}
  ]
}
```

### What gets measured, and the tricks that make it work

- **Static response curve.** Several human-set stimulus levels, each with a
  reference reading the human types in. Batch-captured, so the intervals are
  exact. Fit a monotone piecewise-linear curve — not a polynomial, which will
  ring and produce non-physical non-monotonicity between points.
- **Noise.** Capture at rest at high rate. Report σ, the autocorrelation, and
  **the spectrum**. Expect to find 100/120 Hz ripple on any light sensor under a
  mains-powered lamp — that is a real effect, it is exactly what
  `readpoint()`'s 100-sample median exists to suppress, and an emulator whose
  noise is white will not reproduce the behaviour that motivated that code. This
  is the kind of finding that justifies the whole exercise.
- **Dynamics (time constant).** Here is the trick that makes this practical:
  **use the servo as the stimulus generator.** Swing the arm from a bright patch
  to a dark one at a known moment, sample at high rate through the transition,
  and fit the exponential. The stimulus is repeatable and machine-timed — no
  human trying to cover a sensor at an exact millisecond. The same trick works
  for the colour sensor's integration-time behaviour: sweep across a hard colour
  boundary and watch how long the reading lags.
- **Cross-sensitivity.** For the colour sensor, sweep across a printed chart of
  known patches and fit a 3×3 (or diagonal, if that fits as well) sensitivity
  matrix. Validate against the repo's `WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)`,
  which is an existing measurement of exactly this.
- **ADC non-linearity.** Sweep the slide potentiometer across its travel with a
  reference position, or feed known voltages if a bench supply is available.
  Separates the *sensor's* curve from the *ESP32-C3 ADC's* curve — worth doing
  once and reusing for every analog part, since the ADC's non-linearity is a
  property of the board, not the sensor.

### Human-in-the-loop design

The harness runs a terminal (or browser) wizard: it says what to do, waits, does
its own part automatically, shows a live plot of what it is receiving, and lets
the human redo a step that went wrong. Every step records what the human typed
and when, so a procedure run is fully auditable. Runs are resumable — a
20-minute procedure that dies at step 9 must not start over.

**Ground truth is the weak link, and the doc should say so.** A phone lux meter
is ±20% at best; printed colour swatches are only as good as the printer and the
lighting. Options in ascending cost: phone app (free, rough), a printed
ColorChecker-style chart with measured values (cheap, decent for colour), a
borrowed lab lux meter (good), a calibrated reference sensor (best). Record which
was used in the calibration file's provenance field, and **propagate that
uncertainty into the emulator's tolerance**, rather than pretending the fit is
exact.

### Wear

Sweeps mean servo cycles, and this repo already has a motor guard for long runs.
Cap total sweep count per procedure, prefer coarse-then-refine over dense
uniform sweeps, and report the cycle count at the end.

---

## 9. Reverse-engineering an unfamiliar sensor

Realistic tiers, from safe to speculative:

**Analog parts — straightforward.** Read the resting voltage; measure the
response to a known stimulus; measure the output impedance by comparing the pin
driven high versus driven low (which is precisely what `sensors.selectsensor()`
already does, and the emulator's port model must reproduce). Between those you
can characterise nearly any analog Grove part well enough to model it.

**Documented I2C parts — straightforward.** `bus.scan()` to find the address,
then implement the datasheet, then calibrate the physics with the same sweeps as
above. This is what T019 does for the VEML6040. This is the expected path for
new sensors and should be the documented default.

**Undocumented I2C parts — proceed carefully.**

Read-only reconnaissance first: scan; read registers `0x00`–`0x7F` twice while
the environment is still (constant registers are likely IDs/config; changing ones
are likely data); then have the human change the environment dramatically and
re-read (registers that track the change are the data registers); then look for
adjacent pairs that behave like 16-bit values, testing both endiannesses by
checking which yields a smooth signal across a slow sweep.

Three hazards to state plainly:

1. **Some registers are clear-on-read or have side effects.** Reading a map
   blindly can change device state or lose data.
2. **Many parts return nothing useful until enabled** (the VEML6040 needs its
   shutdown bit cleared — see `enable_sensor()`). Read-only probing of a
   powered-down part finds only zeros, and you cannot resolve that without
   writing.
3. **Writing to unknown registers can brick or misconfigure a part.** If it
   comes to that: write only to registers that read as non-zero-default, change
   one bit at a time, record everything, and use a sacrificial unit.

Honest recommendation: **budget for the datasheet.** Grove parts are almost all
documented, and Seeed publishes the part numbers. Blind reverse-engineering is a
fun exercise and a bad default. Where it is genuinely needed, the harness should
produce a *register report* for a human to interpret — not an automatic model.

---

## 10. Closing the loop: validating the emulator against reality

Every calibration run **holds out** part of its data. After fitting, replay the
held-out conditions through the emulator's plug-in and compare predicted to
measured:

```
$ smcal validate veml6040 --run 2026-08-14-classroom
  Held-out points: 24
  R channel:  RMS error  3.1%   max  7.4%
  G channel:  RMS error  2.8%   max  6.1%
  B channel:  RMS error  9.7%   max 21.3%   <-- weak channel, high relative error
  Integration-time lag: predicted 640 ms, measured 651 +- 12 ms   PASS
  VERDICT: within tolerance for R,G; B exceeds 5% target
```

This turns "the emulator feels about right" into a number that can regress in
CI. It also gives the emulator's fidelity contract (`EMULATOR_DESIGN.md` §4) a
measured row instead of a promise, and it tells a student how much to trust a
result they got in emulation.

Store each run under `calibration/runs/<date>-<part>/` with raw captures, the
procedure, the human's inputs, the fit, and the validation report. Raw data is
cheap and re-fittable; a lost afternoon of bench time is not.

---

## 11. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| USB CDC write blocks when the host isn't reading | Stream stalls, device runs late | S4 measures `max_late_us` directly; if real, use batch mode and bounded queues with explicit drop counting |
| MicroPython overhead caps the sample rate below what games need | Pinball is sluggish | Measure first; move sampling into a Timer with a preallocated buffer; drop JSON for binary |
| `kbd_intr(-1)` makes a wedged device un-interruptible | Frustrating in class | Watchdog + explicit reset command + document the physical button; host re-enables on disconnect |
| Port contention with `mpremote` | Confusing "device busy" errors | Detect and give a specific error naming the conflicting process |
| Students on Windows | Serial enumeration differs entirely | Test early; VID/PID detection is portable, `/dev/cu.*` guessing is not |
| Ground-truth references are poor | Calibration is confidently wrong | Record provenance; propagate uncertainty; validate against the known `WHITE_BALANCE_RGB` |
| Calibration fitting bugs masquerade as measurements | Emulator is wrong in a way nobody notices | The emulator round-trip test (§7.3) — recover known synthetic parameters before trusting real ones |
| `ticks_us` wraps at ~17.9 min | Long runs corrupt silently | Wrap-aware accumulation on the host, with a test that fakes a wrap |
| Scope creep into "a full robotics framework" | Never ships | Two named demos define done: a pinball game and a torch closed-loop notebook |

---

## 12. Task breakdown

Same conventions as `EMULATOR_TASKS.md`: small, test-first, explicit done-checks.
`H` = host link, `C` = calibration.

### Phase A — Measure and decide

- **H001 — Run the S4 spike.** Both scripts exist. Run on the dev machine and on
  a student laptop; write `spikes/S4_hostlink/FINDINGS.md` against the §2
  thresholds. **Blocks everything else. Do this first — it is an afternoon.**
- **H002 — Decide and record.** Update this doc's §0 with measured numbers and
  the chosen mode set. If the numbers are bad, this is where the design changes
  shape.

### Phase B — Device firmware

- **H003 — `hostlink.py` skeleton:** frame codec (encode/decode, CRC, resync),
  JSON control channel, `describe`/`ping`/`reset` commands. Testable on the
  desktop against the emulator's shims — no board needed for the codec.
- **H004 — Sampler:** Timer-driven channel sampling into a preallocated buffer,
  `ticks_us` stamping, channel mask and rate commands. Channels: `pot`,
  `light`, `accel`, `battery`, `color`, `angle`.
- **H005 — Stream mode:** free-running push, bounded queue, explicit drop
  counting (never silently lose samples — report the count).
- **H006 — Batch mode:** capture N samples at exact intervals, then dump. The
  calibration workhorse.
- **H007 — Actuators:** motor angle, screen text, with change suppression.
- **H008 — Dispatch integration:** `prefs.mode == 2` plus a startup chord in
  `main.py`; stdout guard so stray prints can't corrupt the stream. Extend
  `choose_activity` and its existing tests.

### Phase C — Host library

- **H009 — `Transport` seam:** `SerialTransport` (VID/PID detection, port
  contention errors) + a loopback transport for tests.
- **H010 — Codec + reader thread:** wrap-aware timestamps, resync on corruption,
  a test that fakes a `ticks_us` wrap.
- **H011 — Clock sync:** offset and drift estimation, with a synthetic-drift test.
- **H012 — `SmartMotor` facade:** channels, `motor`, `screen`, RPC.
- **H013 — `stream()` and `record()`:** generator and context manager; optional
  numpy export behind a lazy import.
- **H014 — `EmulatorTransport`:** `connect("emu")` against the emulator.
  Depends on emulator T027.
- **H015 — Errors and diagnostics:** `smartmotor doctor` — finds the board,
  identifies which activity is running, checks the firmware version, reports
  measured RTT. Most support questions should be answerable by running it.

### Phase D — Demos (these define "done")

- **H016 — Pinball demo.** Tilt-driven, `pygame` or a canvas over a local
  socket. Must be playable by a student who has read only the README.
- **H017 — Torch demo.** A notebook: record a dataset, train a small model,
  close the loop. Runs against the emulator when no board is present.

### Phase E — Calibration

- **C001 — Procedure runner:** parse the JSON procedure, prompt, capture,
  resume after failure, record human inputs with timestamps.
- **C002 — Capture storage:** `calibration/runs/<date>-<part>/`, raw + metadata
  + provenance.
- **C003 — Fitters:** monotone piecewise-linear, noise (σ, autocorrelation,
  spectrum), exponential step response. **Test each against synthetic data with
  known parameters before any real data touches them.**
- **C004 — Servo-driven step-response procedure** (the stimulus trick, §8).
- **C005 — Emulator round-trip validation:** set known emulator parameters, run
  the procedure against the emulator, assert recovery. **The highest-value test
  in this phase — do it before C006.**
- **C006 — Procedures for the three known parts:** slide pot, light sensor,
  VEML6040. Output: the `data/*.json` files the emulator's T019–T021 need.
- **C007 — `smcal validate`:** held-out comparison and the fidelity report (§10).
- **C008 — I2C reconnaissance tool:** read-only register report with the §9
  hazards documented in its own output.
- **C009 — Plug-in scaffolding:** generate a `smotoremu/sensors/<part>.py`
  skeleton plus its calibration JSON from a completed run.
- **C010 — `docs/adding-a-sensor.md`:** the end-to-end walkthrough — buy a
  sensor, calibrate it, get an emulator plug-in. This is the deliverable that
  makes the whole thing usable by someone other than its author.

---

## 13. Open questions

- **Does the classroom want hostlink as a fourth mode, or a separate firmware
  build?** A fourth mode keeps one deployment, but adds a mode students can get
  stuck in. A chord to enter and a clear on-screen "HOST LINK — connected /
  waiting" indicator probably resolves it.
- **Which sensors are actually on the shopping list** beyond the three named?
  The plug-in mechanism generalises, but calibration effort is per-part and real.
- **What reference instruments are available** — is there a lux meter or a
  colour chart in the lab, or is this phone-app territory? This sets the
  achievable accuracy and belongs in §8's provenance field.
- **Windows and Linux support in scope for v1?** Affects H009's port detection
  and how much of H015 is needed.
- **Is `webconnect.py`'s existing browser UI staying?** If the host library's
  transport could serve it too, that would remove a duplicate path — but only if
  the UI is under your control.
- **How much RAM is actually free** on the board with `hostlink.py` loaded? Sets
  the batch-mode ceiling (H006). Measure with `gc.mem_free()` early — it is a
  one-line answer that constrains the design.
