# SmartMotor Emulator — Design Doc

Status: **proposal / for discussion.** Nothing here is built yet.
Author: drafted with Claude, Aug 2026, from the code in this repo.

Implementation breakdown: **`EMULATOR_TASKS.md`** — 38 tasks and 2 spikes, each
sized for one session, with interfaces, tests-first specs, and done-checks.

---

## 0. Is this plausible?

Yes, and the hard parts are not the ones that look hard.

**Cheap, because of how this code is already written:**

- The OLED path already goes through real driver bytes. `icons.SSD1306_SMART`
  subclasses `ssd1306.SSD1306_I2C`, which subclasses `framebuf.FrameBuffer` and
  pushes 1024 bytes + commands over I2C. If we emulate the SSD1306 at the
  command level (~12 commands actually used), we get **pixel-exact** screens for
  free, including the real font, `graph()`, and the icon frames. No stubbing of
  the display API, no drift between fake and real.
- The color sensor is already driven at the register level (`VEML6040` in
  `myfavcolor.py`: CONF at `0x00`, R/G/B/W at `0x08`–`0x0B`, 16-bit LE). A
  sensor plug-in is therefore a *register-and-physics* model, which is exactly
  the level at which "make it behave like the real part" is meaningful.
- The board is small: 3 buttons, 1 pot, 1 battery ADC, 1 servo PWM, 1 shared
  sensor pin, 2 fixed I2C peripherals, 1 pluggable port. That's a completely
  tractable device model.
- `tests/fakes/` already proves the seam exists; this project is largely
  "replace the fakes with something that has physics, a clock, and a screen."

**Genuinely hard, in rough order:**

1. **Timing fidelity** (§4). Achievable *for I/O and peripherals* — which is
   where nearly all the felt latency lives — but CPU-instruction timing is not
   achievable without full CPU emulation. This needs an explicit, honest
   fidelity contract.
2. **`mpremote`/`esptool` compatibility** (§10). Making a real, unmodified
   `mpremote cp` work against the emulator is the single riskiest item and
   deserves a spike before anything else is committed to.
3. **Sensor realism** (§6). Not hard to build, but the models are only as good
   as the bench measurements we feed them. Budget lab time, not code time.
4. **Test-API ergonomics** (§8). Playwright-shaped is right, and the auto-wait
   semantics are the part to get right early, because rewriting the tests twice
   is the expensive failure mode.

The recommended shape is a **layered emulator with a swappable execution
backend**, so that fidelity can be bought incrementally without rewriting the
UI, the sensor plug-ins, or the tests.

---

## 1. Goals

- **G1 — Visible device.** A local web page showing a SmartMotor: arm/LEGO beam
  at the true servo angle with a numeric readout, the OLED rendered
  pixel-faithfully, buttons/switches, battery, attached sensor.
- **G2 — Keyboard control.** `↑`/`↓` side buttons, `Space` SELECT, `←`/`→`
  potentiometer, `~` power toggle, `!` analog/I2C toggle, mouse-drag 3D tilt for
  the accelerometer.
- **G3 — Selectable screen.** The OLED content is copyable text, not just
  pixels — and the same extraction feeds test assertions.
- **G4 — Faithful timing** for peripheral and I/O latency, with a documented
  fidelity contract and a deterministic fast mode for tests.
- **G5 — Sensor plug-ins**, modelled on specific real parts, added without
  touching emulator core. First three: slide potentiometer (analog), light
  sensor (analog), Grove color sensor v3 / VEML6040 (I2C).
- **G6 — Playwright-shaped test API**, with the existing `tests/` suite
  refactored onto it.
- **G7 — Deploy like hardware.** "FLASH" and file upload through the same
  workflow as a USB-connected board (`deploy.sh` should work against a virtual
  port).

## 2. Non-goals (v1)

- Cycle-accurate CPU timing, or matching MicroPython bytecode execution speed.
- Emulating Wi-Fi, BLE, deep sleep, or the ESP32-C3 boot ROM.
- Byte-level `esptool` flash-image emulation (we emulate the *workflow*, §10).
- Analog electrical simulation (SPICE-style). Sensor models are behavioural.
- Replacing hardware validation. This is the *second* gate; hardware is still
  the last one, exactly as `README.md` says today.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Clients (all speak the same protocol, §7)                       │
│                                                                  │
│   Browser UI (headed)        pytest / smotor test API (headless) │
│         │                              │                         │
└─────────┼──────────────────────────────┼─────────────────────────┘
          │        WebSocket / in-process channel                  
┌─────────▼──────────────────────────────▼─────────────────────────┐
│  Emulator core  (Python package `smotoremu/`)                    │
│                                                                  │
│   Session ── VirtualClock ── EventScheduler                      │
│      │                                                           │
│      ├── Board model: pins, ADC, PWM, timers, I2C bus            │
│      ├── Peripherals: SSD1306(0x3C), ADXL345(0x53), servo,       │
│      │                battery, pot, 3 buttons, 2 switches        │
│      ├── Port model (pin 5 + I2C + analog/I2C switch)            │
│      │      └── Sensor plug-in registry  (§6)                    │
│      ├── World model: the sheet of paper under the arm (§5)      │
│      ├── VFS: virtual flash filesystem + firmware slot (§10)     │
│      └── Trace recorder: every I/O event, timestamped            │
└─────────▲────────────────────────────────────────────────────────┘
          │  Device-facing shim API (the ONLY thing device code sees)
┌─────────┴────────────────────────────────────────────────────────┐
│  Execution backend (swappable, §4)                               │
│   B1 cpython-shim   B2 micropython-unix   B3 qemu-esp32c3        │
│                                                                  │
│   Runs main.py / myfavcolor.py / standalone.py / webconnect.py   │
└──────────────────────────────────────────────────────────────────┘
```

The load-bearing idea: **the browser UI and the test client are the same kind of
client.** A test can run headless in CI, or headed with a human watching the
identical session in the browser. That single decision buys the classroom demo,
the debugging story, and CI from one implementation.

---

## 4. Execution backends and the fidelity ladder

The device code has to actually run somewhere. Three options, and the
recommendation is to build the boundary so all three can plug in.

### B1 — `cpython-shim` (start here)

CPython 3.12 with `machine`, `framebuf`, `ubinascii`, `urandom`, `uselect`,
`time` shims that call into the emulator core. This is today's `tests/fakes/`
with physics and a clock behind it.

- **Pro:** fastest to build, fastest to run, trivial debugging (`pdb`,
  coverage), no external binaries. Great for CI.
- **Con:** CPython ≠ MicroPython. Won't catch `const()` misuse, missing
  `ustruct`, memory exhaustion, heap fragmentation, integer/float differences,
  or MicroPython-specific import behaviour. `README.md` already leans on
  "import safety" tests that this backend cannot fully honour.

### B2 — `micropython-unix` (the target for v1.0)

The MicroPython Unix port, built with a custom `machine` module (a C or
frozen-Python module) that proxies to the emulator core over a socket or pipe.

- **Pro:** *real* MicroPython semantics, real VFS, real REPL, real `const`,
  real error messages. Catches the class of bug that CPython silently forgives.
  Enables the `mpremote` story (§10) if the raw-REPL spike succeeds.
- **Con:** requires building MicroPython (a vendored build script + CI cache);
  not currently installed on this machine; Unix-port heap/timing still differ
  from the ESP32-C3.

### B3 — `qemu-esp32c3` (optional, later)

Espressif's QEMU fork runs ESP32-C3 images; the actual
`ESP32_GENERIC_C3-20250415-v1.25.0.bin` in this repo boots, and peripherals are
bridged to the emulator core. Wokwi's simulator is the same idea, hosted.

- **Pro:** maximum fidelity, including real flash, real `esptool` writes, and
  approximate CPU timing.
- **Con:** heavy, slow, brittle, and 10× the integration work. Only worth it if
  we hit a class of bug the other two can't see.

**Recommendation:** ship B1 first (it makes the UI and the test API real within
days), define the shim boundary strictly enough that B2 drops in behind it, and
treat B3 as a research option. Tests declare the backend they need:

```python
pytestmark = smotor.requires_backend("micropython")   # opt-in per test file
```

### The fidelity contract (write this down, publish it in the UI)

| Aspect | v1 fidelity |
| --- | --- |
| I2C transaction latency | Modelled: `bytes × 9 / freq` + start/stop overhead |
| SSD1306 full refresh | Modelled: ~23 ms at 400 kHz (1025 bytes) |
| VEML6040 integration delay | Modelled: reads return the last *completed* conversion |
| ADC read | Modelled: fixed per-sample cost + noise |
| Servo motion | Modelled: slew rate + settling, not torque or load |
| Timer callbacks | Modelled: scheduled, with ISR-context restrictions noted |
| `time.sleep` / `ticks_ms` | Exact, against the virtual clock |
| Python execution speed | **Not modelled** (B1/B2). Code runs "infinitely fast" between I/O events |
| Memory limits / GC pauses | Not modelled (B1); partial (B2); real (B3) |

That last-but-one row is the important disclosure: a tight compute loop that
would take 400 ms on the C3 takes ~0 virtual ms here. Mitigation if it bites: a
calibrated bytecode-count budget in B2 (count VM instructions, charge virtual
time at a measured ns/instruction). Cheap to add later; don't build it in v1.

---

## 5. Virtual clock, timing, and the world

### Clock

A single `VirtualClock` owns time; nothing calls `time.time()` directly. An
`EventScheduler` holds a priority queue of `(virtual_t, callback)` — servo
arrival, VEML6040 conversion complete, battery `Timer(1)` period, I2C
transaction completion, button auto-release.

Three modes:

- `realtime` — virtual clock slaved to wall clock, `speed=1.0`. Interactive use.
- `scaled` — `speed=0.1 … 20`. Slow-mo for classroom explanation, fast-forward
  through `EPISODES × TIMESTEPS`. (`myfavcolor.learn()` with the default 5×20
  and `MOTOR_SETTLE_TIME=1` is minutes of real waiting; this is a feature
  students will use constantly.)
- `instant` — the clock jumps to the next scheduled event; sleeps cost nothing.
  Deterministic, and the default for tests. This is Playwright's `page.clock`
  idea, and it makes a 5-episode training run finish in milliseconds.

Determinism: seed all noise from a per-session PRNG seed, recorded in the trace.
A failing test replays exactly.

### World model

Sensors are meaningless without something to sense. The `World` is the sheet of
paper under the arm:

```yaml
world:
  ambient_lux: 300
  surface:                      # angle ranges → what's there
    - {from: 0,   to: 25,  color: "#e02020", name: "red patch"}
    - {from: 25,  to: 50,  color: "#f0f0f0", name: "white"}
    - {from: 50,  to: 75,  color: "#2050e0", name: "blue patch"}
  default_color: "#ffffff"
```

The arm angle selects the patch; the sensor plug-in converts patch colour +
ambient light + its own physics into register values. This is what makes
`myfavcolor`'s calibrate → capture-favourite → train loop actually *mean*
something in a test, and it is directly usable in class ("here's the paper, drag
the patches around").

The UI renders the world as an arc under the arm, editable by drag.

---

## 6. Sensor plug-in architecture

### The port

The SmartMotor's sensor port carries pin 5 (analog or digital) **and** the I2C
bus (SDA 6 / SCL 7), with a physical analog/I2C toggle. Two behaviours must be
reproduced faithfully:

1. **Attachment detection.** `sensors.SENSORS.selectsensor()` drives pin 5 low,
   reads it, drives it high, reads it, and concludes *not attached* when
   `low < 200 and high > 4000` — i.e. when nothing is loading the pin, it simply
   follows the drive. An attached analog sensor holds the pin at its own output
   level. The port model must reproduce both cases, because this branch decides
   whether `standalone.py` reads light or falls back to the accelerometer.
2. **The analog/I2C switch** changes what the port presents. *(Open question:
   the exact electrical effect isn't visible in this repo's code — see §12.)*

### Plug-in contract

```python
class SensorModel:
    """Base class for a plug-in sensor. One subclass per real part."""

    part_number: str          # "VEML6040", "Grove-LS06-S", ...
    display_name: str
    interface: str            # "analog" | "i2c"
    i2c_addresses: set[int]   # for interface == "i2c"

    def attach(self, port: Port, world: World, clock: VirtualClock) -> None: ...
    def detach(self) -> None: ...

    # --- analog parts ---
    def pin_voltage(self, driven: float | None) -> float:
        """Voltage the part presents on pin 5. `driven` is the MCU's drive
        level during attachment probing, or None when the pin is an input."""

    # --- I2C parts ---
    def i2c_write(self, addr: int, mem: int | None, data: bytes) -> None: ...
    def i2c_read(self, addr: int, mem: int | None, n: int) -> bytes: ...

    # --- UI ---
    def ui_schema(self) -> dict:
        """Controls and readouts the browser should render for this part."""
```

Discovery: entry-point style, `smotoremu.sensors` package, one module per part,
auto-registered by a decorator. Adding a part = one file + one YAML calibration
block + one test. No core changes. That's the requirement.

### Initial three

**1. Grove slide potentiometer (analog).** 10 kΩ linear track, wiper → pin 5,
0–3.3 V. Model: linear position → voltage; add ESP32-C3 ADC realities —
12-bit with `ATTN_11DB`, the well-known non-linearity near the rails, and
~±10 LSB noise. UI: a draggable slider.

**2. Grove light sensor (analog).** Phototransistor/op-amp part; response is
non-linear and saturates. Model: `lux → voltage` from a measured curve
(log-ish, clamped), plus ambient coupling to the world's `ambient_lux`, plus
noise. UI: a lux slider and a "what the sensor sees" readout. This is the part
`standalone.py`'s `readpoint()` medians 100 samples of — the noise model is what
makes that code path meaningful to test.

**3. Grove color sensor v3 / VEML6040 (I2C 0x10).** Register-accurate against
the driver already in `myfavcolor.py`:

- CONF `0x00`: honour `SD` (shutdown), `AF` (auto/manual), `TRIG`, and the
  `IT` field. **Integration time must gate data availability** — at
  `IT_640MS` a read returns the last completed conversion, so a read issued
  100 ms after a servo move still returns the *old* colour. Reproducing this
  is the single highest-value timing behaviour in the whole emulator: it is
  precisely the bug class this activity keeps running into.
- R/G/B/W at `0x08`–`0x0B`, 16-bit little-endian counts scaling with
  integration time and illumination.
- Per-channel spectral sensitivity calibrated so that the blue channel is
  weak — the repo's `WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)` is a direct
  measurement of this and should be reproduced *as an emergent property*, not
  hardcoded. If a student's white-balance step produces roughly those factors
  in the emulator, the model is right.
- Saturation clipping, dark counts, and shot noise.

Calibration data lives in `smotoremu/sensors/data/*.yaml` with provenance
comments ("measured on board #3, 2026-08-xx, under classroom fluorescents"), so
the models can be improved from bench readings without code changes.

### Built-in peripherals (not plug-ins)

| Peripheral | Where | Model |
| --- | --- | --- |
| SSD1306 128×64 | I2C `0x3C` | Command-level; real framebuffer (§7) |
| ADXL345 | I2C `0x53` | Registers `0x2D`, `0x32`+6; orientation from UI drag → x/y/z counts + noise; `RP_calculate` must produce sane roll/pitch |
| Servo | PWM pin 2, 50 Hz, 600–2400 µs | Duty → target angle; slew rate ~0.15 s/60°; settling; the "very long run" motor guard should be observable |
| Potentiometer | ADC pin 3 | 0–4095, `←`/`→` keys, noise (so `POT_THRESHOLD=50` debouncing is exercised) |
| Battery | ADC pin 4 | Settable level mapping to `charging`/`full`/`half`/`low` per `readbattery()` thresholds |
| Buttons | Pins 8 (down), 9 (select), 10 (up) | Active-low, with configurable bounce |

Note the ADXL345 is constructed from the same bus in `sensors.py` and tolerates
`OSError` — so "board without accelerometer" must be a supported configuration.

---

## 7. Display: pixel-faithful *and* selectable

The device writes real SSD1306 commands and 1024 bytes of GDDRAM. The emulator:

1. Implements the SSD1306 command subset `ssd1306.py` actually uses (addressing
   mode, column/page ranges, contrast, invert, display on/off, charge pump).
2. Maintains the 128×64 bit framebuffer.
3. Streams it to the browser, rendered on a canvas with the real OLED look
   (blue-on-black, pixel grid, optional glow) — zoomable.

**The selectable text layer** is the neat part. `framebuf.text()` uses
MicroPython's fixed 8×8 `petme128` font. We build a reverse map from each glyph's
8-byte bitmap to its character, then scan the framebuffer on an 8×8 grid and
recover the text exactly — no OCR, no hooking of the application's code, works
identically under every backend. Cells that don't match a glyph (graph lines,
icons, overlapping draws) become `·` in the text layer and are flagged.

That single mechanism serves:

- the copyable text panel in the UI ("shows what's on-screen in a faithful and
  selectable way"),
- `sm.screen.text()` and `expect_text()` in tests,
- text-diff-based screen snapshots in CI, which are readable in a PR — far
  better than image diffs.

The UI offers **selectable views**: `Pixels` / `Text` / `Both` / `Raw I2C
traffic`, plus a screen-history scrubber (every `show()` is a frame; step back
through them). Given `myfavcolor.screen()` already prints changed screens to
stdout, the history view will match the console log students already see.

---

## 8. Test API — Playwright-shaped

### Shape

```python
import smotor

def test_favorite_color_training_converges(sm):
    sm.port.attach("VEML6040")
    sm.world.load("worlds/three_patches.yaml")
    sm.boot()                                    # runs main.py

    sm.screen.expect_text("Point at WHITE")      # auto-waits, virtual clock
    sm.pot.set_angle(45)                         # over the white patch
    sm.press("select")

    sm.screen.expect_text("White Balance")
    sm.screen.expect_text("Set FAV color")
    sm.pot.set_angle(10)                         # over the red patch
    sm.press("select")

    for _ in range(smotor.NUM_STATES):
        sm.press("select")

    sm.screen.expect_text("Press to start")
    sm.press("select")

    sm.screen.expect_text("End!", timeout=30_000)   # virtual ms
    assert sm.arm.angle == pytest.approx(10, abs=5) # parks on the favourite
```

Deliberate Playwright parallels:

| Playwright | SmartMotor emulator |
| --- | --- |
| `browser.new_page()` | `smotor.launch()` → `Session` |
| Locators + auto-waiting | `sm.screen.expect_text()`, `sm.arm.expect_angle()` — poll while advancing the virtual clock until timeout |
| `page.clock` | `sm.clock.set_mode("instant" \| "realtime" \| speed) `, `sm.clock.advance(ms)` |
| `page.screenshot()` | `sm.screen.png()` / `sm.screen.text()` |
| Trace viewer | Recorded I/O timeline (every pin, ADC, I2C, PWM event) rendered in the browser |
| Headed vs headless | `smotor.launch(headed=True)` opens the browser on the same session |
| Fixtures | pytest fixtures `sm`, `sm_with_color_sensor`, `sm_no_sensor` |
| `expect(...).to_have_text()` | `smotor.expect(sm.screen).to_have_text(...)` |

Auto-waiting semantics are the thing to nail early: in `instant` mode, an
`expect_*` call advances the clock event-by-event until the predicate holds or
the *virtual* timeout expires. That is what makes a 5-episode training run
assertable in milliseconds and keeps CI deterministic.

### Migrating the existing suite

| Today | After |
| --- | --- |
| `test_dispatch.py` — `choose_activity()` purity | Keep as-is. It's a pure function; don't drag an emulator into it. |
| `test_distance_math.py`, `test_qlearning.py` | Keep as-is. Pure math and a mocked env. |
| `test_filesize.py` | Keep, and extend: the emulator VFS enforces the same upload threshold (§10). |
| `test_import_safety.py` | Move to the `micropython` backend (B2), where it actually means something. |
| `test_flow.py` | **Rewrite.** Today it `MagicMock`s `sensor`, `sens`, `switch_up`, patches `Environment.__init__` and `learn`, and asserts on a list of strings — it tests that `main()` calls two things. On the emulator it becomes a real boot-to-training-screen assertion with no mocks. This test is the poster child for the whole project. |
| `tests/fakes/*` | Replaced by the emulator; `conftest.py`'s `sys.path` and time-patching hacks go away. |

Migration is incremental: the emulator ships alongside `tests/fakes/`, tests move
over one file at a time, and the fakes are deleted when the last one moves.

---

## 9. UI and controls

Single page, no build step (see §11). Layout:

```
┌─────────────────────────────────────────────────────────────┐
│ [~ power] [! analog/i2c]   backend: cpython  speed: [1x ▾]  │
├──────────────────────┬──────────────────────────────────────┤
│                      │  OLED   (Pixels | Text | Both | I2C) │
│    arm / LEGO beam   │  ┌────────────────────────────────┐  │
│      side view       │  │ E=0 T=3 e=0.90                 │  │
│      angle: 137°     │  │ S=2 R=41                       │  │
│                      │  └────────────────────────────────┘  │
│   ┌── world arc ──┐  │  [copy text]  ◀ frame 42/117 ▶       │
│   │ red white blue│  ├──────────────────────────────────────┤
│   └───────────────┘  │  Port: [VEML6040 ▾]  R 120 G 30 B 28 │
├──────────────────────┤  Pot 2048  Batt full  Tilt (drag)    │
│ ▲ UP  ▼ DOWN  ␣ SEL  ├──────────────────────────────────────┤
│ ← → pot              │  Trace / console                     │
└──────────────────────┴──────────────────────────────────────┘
```

- **Arm:** 2D side view is clearer than 3D for reading motor position, and it
  makes the LEGO beam and its angle unambiguous. Big numeric readout.
- **Tilt:** trackball drag on an isometric board widget sets the gravity vector →
  ADXL345 x/y/z. This is where 3D is genuinely needed.
- **Keys:** `↑`/`↓` side buttons, `Space` SELECT, `←`/`→` pot, `~` power,
  `!` analog/I2C — held keys mean held buttons (`waitforbutton()`'s
  press-then-release debounce must be exercisable), with a "sticky" click
  alternative for accessibility.
- **Power (`~`)** is a real reset: clears RAM, re-runs `boot.py` then `main.py`,
  keeps the VFS. This makes the "reset the board after a failed upload" advice
  in `README.md` reproducible.
- Fidelity contract (§4) is linked from the header, so nobody mistakes the
  emulator for the board.

---

## 10. FLASH and upload

Three levels; recommend building 1 and 2, and treating 3 as the spike.

**Level 1 — native CLI (certain).**

```bash
smotor flash                       # wipe VFS, set firmware slot
smotor deploy EngAI_MANIFEST.txt   # upload listed files, enforce size limits
smotor repl                        # interactive REPL against the session
```

The VFS is a real directory per session. `os.listdir()`, `open("data.py","w")`,
and the `files.py` read/write cycle work unchanged — which matters, because
`savetofile()`/`resetprefs()` mutate `data.py` and `prefs.py` and then re-import
them. Enforce the same per-file size threshold `test_filesize.py` checks, so an
oversized file fails *in the emulator* the way it fails on the CEEO uploader.

**Level 2 — `deploy.sh` compatibility (high confidence).** Give `deploy.sh` a
port variable:

```bash
./deploy.sh              # real board, unchanged
PORT=emu ./deploy.sh     # same script, emulator target
FLASH PORT=emu ./deploy.sh
```

With `PORT=emu`, `mpremote`/`esptool.py` calls route to `smotor` equivalents. One
script, one mental model for students, no drift between the two paths.

**Level 3 — a real virtual serial port (spike required).** Expose a PTY that
speaks the MicroPython raw REPL protocol, so genuinely unmodified
`mpremote connect /dev/ttys004 cp main.py :` works. Under backend B2 this is
plausible — the Unix port has a REPL and raw mode — but "plausible" is not
"verified," and the raw-paste protocol details are fiddly. **Spike it in a day
before promising it.** `esptool erase-flash`/`write-flash` would be intercepted
and mapped onto VFS wipe + firmware-slot assignment; genuine flash-image parsing
is out of scope unless B3 happens.

---

## 11. Tech stack and layout

Constraint: this is a **classroom repo that must stay hackable**. No build step,
no `node_modules`, no framework. A student or instructor should be able to open
the JS and change it.

- Backend: Python 3.12 (already the repo's runtime), stdlib `asyncio` +
  `websockets`. FastAPI only if it earns its keep — for two endpoints and a
  socket, it doesn't.
- Frontend: vanilla ES modules, Canvas 2D for the OLED and the arm. No
  three.js in v1 — the tilt widget is a hand-rolled isometric box, ~100 lines.
  Vendor a single-file 3D lib later only if the LEGO rendering demands it.
- Protocol: JSON messages over one WebSocket, versioned.
  `client → emu`: `{press, release, set_pot, set_tilt, set_world, clock, attach,
  boot, reset}`. `emu → client`: `{frame, state, trace, log, exit}`.
  Batched at ~30 Hz, coalescing framebuffer updates.
- Packaging: `pip install -e .` inside the existing `.venv`.

```
smotoremu/
  __init__.py          # smotor.launch(), expect()
  clock.py             # VirtualClock, EventScheduler
  board.py             # pins, ADC, PWM, timers, power/reset
  i2c.py               # bus arbitration + transaction timing
  vfs.py               # virtual flash filesystem, size limits
  session.py           # lifecycle, trace recording, seeding
  peripherals/
    ssd1306.py  adxl345.py  servo.py  battery.py  buttons.py  pot.py
  sensors/
    __init__.py        # registry + @register decorator
    base.py            # SensorModel
    veml6040.py  grove_slide_pot.py  grove_light.py
    data/*.yaml        # calibration, with provenance
  world.py             # the paper under the arm
  backends/
    cpython_shim/      # machine, framebuf, urandom, uselect, ubinascii
    micropython_unix/  # build script + proxy module
  screen_text.py       # glyph → char reverse map
  server.py            # websocket + static file server
  cli.py               # smotor flash / deploy / repl / run
  testing.py           # pytest fixtures, expect(), auto-wait
web/
  index.html  app.js  oled.js  arm.js  tilt.js  world.js  style.css
tests/emulator/        # tests OF the emulator itself
```

Note: `tests/emulator/` — the emulator needs its own tests, held to the same
red-green discipline. An emulator you don't trust is worse than fakes you know
are fake.

---

## 12. Risks, spikes, open questions

**Spike first (before committing to the plan):**

1. **`mpremote` against a PTY REPL** (§10 level 3). One day. If it fails, level 2
   still delivers the workflow; the promise just gets scoped down.
2. **Glyph reverse-mapping** (§7). Half a day. Extract `petme128`, verify the
   8-byte → char map is injective, render a known screen and round-trip it. Low
   risk, high value, and it de-risks the whole test-assertion strategy.
3. **MicroPython Unix port with a proxy `machine`** (§4 B2). Two days. Determines
   whether B2 is a v1.0 target or a stretch goal.

**Open questions for you:**

- **The analog/I2C toggle (`!`):** what does it switch, electrically? Does it
  disconnect the I2C lines from the port, re-route pin 5, or change pull-ups?
  The behaviour isn't inferable from this repo, and `selectsensor()`'s probe
  thresholds depend on it.
- **The power switch (`~`):** full power cycle, or a reset line? Does the VFS or
  `prefs.py` survive? (I've assumed: full cycle, VFS survives.)
- **Which board revision** is canonical for calibration, and can we get bench
  measurements — VEML6040 counts under a few known colours and integration
  times, light-sensor voltage at a few lux, ADC endpoints? The sensor models are
  bounded by this data, not by code.
- **Is the ADXL345 always present**, or only on some units? `sensors.py`
  tolerates its absence, so I've made it configurable.
- **`README.md` references `EMULATION_TESTING_PROPOSAL.md`, which isn't in the
  repo.** Should this document supersede that reference, or is that a separate
  doc that went missing?

**Future work, noted 2026-08-03 while building the S7 guided-test replay
viewer (a trace player, not this):** a **mirror mode** where the web UI
shows a currently-connected real device live (not a captured-log replay),
with a device picker so a user can choose among multiple simultaneously
connected boards and watch two of them side by side in separate browser
windows/tabs. This is a natural extension of the replay work — the same
OLED/servo/battery/USB rendering pipeline, fed from a live host-link stream
(see `HOSTLINK_DESIGN.md`) instead of a parsed log file — but it's new
scope, not part of the replay viewer just built.

**Known limitations to state loudly, in the UI and the README:**

- No CPU timing → compute-bound code appears instantaneous (§4).
- Sensor models are behavioural approximations of specific parts under specific
  lighting; they will disagree with the bench at the edges.
- Button *feel*, servo torque under load, real serial reliability, and OLED
  legibility in a bright classroom remain hardware-only concerns — the same list
  `README.md` carries today, minus the items the emulator legitimately covers.

---

## 13. Milestones

| # | Deliverable | Proves |
| --- | --- | --- |
| **M0** | Three spikes (§12) | The risky assumptions hold |
| **M1** | Core + clock + board + SSD1306 + browser UI showing a real boot screen, keyboard input working | The visible device (G1, G2) |
| **M2** | Servo + arm view + pot + buttons + battery; `myfavcolor.main()` driven by hand to the training screen | The device is *operable* |
| **M3** | Sensor plug-in framework + VEML6040 + world model; full favourite-colour flow end to end | The hard sensor case (G5) |
| **M4** | Test API + auto-wait + `instant` clock; `test_flow.py` rewritten with no mocks | The Playwright story (G6) |
| **M5** | Text layer, snapshots, trace viewer; remaining tests migrated; `tests/fakes/` deleted | Selectable screen (G3), suite converted |
| **M6** | VFS + `smotor flash/deploy` + `PORT=emu ./deploy.sh` | Deploy like hardware (G7) |
| **M7** | Slide pot + light sensor plug-ins; `standalone.py` runs end to end | Plug-in framework generalises |
| **M8** | MicroPython Unix backend (B2); `import_safety` tests moved onto it | Real MicroPython semantics |

M1–M2 is where this stops being a proposal and starts being useful in class:
even with no sensors modelled, a visible, keyboard-driven SmartMotor that shows
the real OLED is worth having.
