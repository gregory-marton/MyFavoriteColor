# SmartMotor Emulator — Implementation Tasks

Companion to `EMULATOR_DESIGN.md`. That doc says *what and why*; this one says
*what to type, in what order, and how to know it worked*.

Each task is sized for one focused session: 1–3 files, an explicit interface, a
test written **before** the implementation, and a mechanical done-check. Tasks
name their dependencies; anything with no unmet dependency can be picked up.

---

## Ground rules (read before starting any task)

**R1. Never modify device code to make the emulator work.**
`main.py`, `myfavcolor.py`, `standalone.py`, `webconnect.py`, `sensors.py`,
`servo.py`, `adxl345.py`, `icons.py`, `ssd1306.py`, `files.py`, `boot.py` are the
system under test. If one of them "has a bug" (and several do — see R6), the
emulator reproduces the hardware faithfully and lets the bug happen. Fixing
device code is a separate, deliberate change with its own red-green cycle.

**R2. Red-green, always.** Per the repo's testing discipline: write the test,
run it, *watch it fail for the right reason*, then implement, then watch it pass.
Paste both outputs in the task's completion note. A test that has never failed
has proven nothing.

**R3. Determinism is a feature.** No wall-clock reads, no unseeded RNG, no
iteration over unordered sets in anything that affects output. All randomness
comes from `session.rng` (a `random.Random` seeded per session, seed recorded).

**R4. No new third-party dependencies** without asking. Standard library plus
`pytest` (already present) and `websockets` (approved, T027 only). No frontend
build step, no `node_modules`, no CDN links — see `EMULATOR_DESIGN.md` §11.

**R5. Every physical constant is named, sourced, and commented.** Write
`# 400 kHz: MicroPython SoftI2C default (sensors.py constructs with no freq=)`,
not `0.0000225`. If a number came from a datasheet, cite the part and section.
If it's a guess awaiting bench measurement, mark it `# GUESS: needs bench data`
and add it to the list in T036.

**R6. Known device-code quirks to preserve, not fix.** These exist today and
tests may depend on reproducing them:
- `sensors.map_angle_to_range()` falls off the end without returning for
  `0 <= angle < 90` — returns `None`. (Falls into the `else: return 0` branch
  only for angles outside the listed ranges; trace it carefully.)
- `readbattery()` thresholds overlap (2850–2875 is both "charging" and "full")
  and have gaps (exactly 2700 and exactly 2500 return `""`).
- `servo.write_angle()` does `degrees % 360`, so 200° maps past `max_us` and
  clamps to 180° rather than erroring.

**R7. Layout.** Emulator code in `smotoremu/`, its tests in `tests/emulator/`,
frontend in `web/`. Do not touch `tests/fakes/` until T026 deletes it.

**R8. Task completion note.** Append to `EMULATOR_PROGRESS.md`: task ID, files
touched, the red output, the green output, and any decision you made that the
task spec didn't cover.

---

## Dependency graph

```
T001 ─┬─ T002 ──────────────────────────────┬─ T013 ─ T014 ─ T015
      ├─ T003 ─ T004 ─ T005                 │
      ├─ T006 ─┬─ T007 ─┬─ T009 ────────────┤
      │        │        ├─ T012             │
      │        │        └─ T017 ─ T018 ─┬─ T019
      │        ├─ T008                  ├─ T020
      │        ├─ T010                  └─ T021
      │        └─ T011                       │
      └─ T016 ──────────────────────────────┘
                                             │
        T013 ─ T022 ─ T023 ─ T024 ─ T025 ─ T026
        T022 ─ T027 ─┬─ T028 ─ T029 ─ T030 ─ T031 ─ T032 ─ T033
        T014 ─ T034 ─ T035

Spikes (do first, independently): S1, S3.  S2 is folded into T005.
```

---

# Spikes

### S1 — `mpremote` against a virtual serial port
**Size:** 1 day. **Blocks:** the promise in T034/T035, nothing else.

Determine whether unmodified `mpremote connect <pty> cp file :` can work against
an emulated device. Steps: open a PTY pair with `pty.openpty()`; on the device
side implement enough of the MicroPython raw REPL (Ctrl-A to enter raw mode,
`>` prompt, Ctrl-D to execute, `OK`/output/`\x04`/error/`\x04` framing) to echo a
trivial `print()`; then try `mpremote connect /dev/ttys00N exec "print(1)"`, then
`cp`. `mpremote` is at `.venv/bin/mpremote`.

**Deliverable:** `spikes/S1_mpremote/` containing the throwaway script and a
`FINDINGS.md` with a yes/no and, if no, exactly which protocol step failed.
**If no:** T034 ships the native CLI only, and `EMULATOR_DESIGN.md` §10 level 3
is struck. Do not spend more than a day proving a negative.

### S3 — MicroPython Unix port with a proxy `machine`
**Size:** 2 days. **Blocks:** T037 (backend B2) only. Not on the v1 critical path.

Build the Unix port; add a `machine` module (frozen Python is fine to start)
that proxies calls over a Unix socket to a Python stub server. Prove
`import machine; machine.Pin(8).value()` round-trips.
**Deliverable:** `spikes/S3_micropython/FINDINGS.md` + build script. Records
build time, binary size, and whether `framebuf` and `struct` are available in
the default Unix build (they may need enabling in `mpconfigport.h`).

---

# Phase 0 — Foundations

### T001 — Package skeleton
**Deps:** none. **Size:** S.

**Files:** `smotoremu/__init__.py`, `smotoremu/version.py`, `pyproject.toml`,
`tests/emulator/__init__.py`, `tests/emulator/conftest.py`, `EMULATOR_PROGRESS.md`.

**Spec:** Installable with `pip install -e .` into the existing `.venv`. Package
requires Python ≥ 3.11. `smotoremu.__version__` exists.
`tests/emulator/conftest.py` must be independent of `tests/conftest.py` — in
particular it must **not** monkeypatch `time` globally (that hack goes away with
the fakes). Confirm the two suites coexist: `pytest tests/ -v` still passes
unchanged.

**Test first:** `tests/emulator/test_smoke.py::test_package_imports`.
**Done when:** both suites pass; `pip install -e .` succeeds.

---

### T002 — Virtual clock and event scheduler
**Deps:** T001. **Size:** M. **This is the spine of the whole emulator.**

**Files:** `smotoremu/clock.py`, `tests/emulator/test_clock.py`.

**Spec:**

```python
class VirtualClock:
    def __init__(self, mode: str = "instant", speed: float = 1.0): ...
    @property
    def now_us(self) -> int: ...          # virtual microseconds since boot
    def now_ms(self) -> int: ...
    def sleep_us(self, us: int) -> None:  # advances virtual time; blocks in realtime mode
    def advance_to(self, t_us: int) -> None: ...
    def set_mode(self, mode: str, speed: float = 1.0) -> None: ...
    # mode in {"instant", "realtime", "scaled"}

class EventScheduler:
    def at(self, t_us: int, callback, *args) -> Handle: ...
    def after(self, delay_us: int, callback, *args) -> Handle: ...
    def every(self, period_us: int, callback, *args) -> Handle: ...   # for Timer
    def cancel(self, handle: Handle) -> None: ...
    def next_event_time(self) -> int | None: ...
    def run_until(self, t_us: int) -> None: ...   # fire all events with t <= target
```

Ordering: events at equal timestamps fire in insertion order (use a monotonic
sequence counter as the heap tiebreaker — never compare callbacks). A callback
that schedules a new event at the current time must not livelock `run_until`;
cap iterations and raise `ClockStuckError` after 100_000 events at one instant.

`instant` mode: `sleep_us` jumps the clock, firing scheduled events in order as
it passes them. `realtime`/`scaled`: sleep against the wall clock, scaled by
`speed`, but *still* fire scheduled events in order.

**Test first (`test_clock.py`), all in instant mode:**
1. `now_us` starts at 0; `sleep_us(1000)` → 1000.
2. Events fire in timestamp order across a `sleep_us` that spans several.
3. Equal timestamps fire in insertion order.
4. `cancel()` prevents firing.
5. `every()` re-fires at the right cadence and can be cancelled from inside its
   own callback.
6. A callback that schedules at `now` raises `ClockStuckError` rather than hanging.
7. `sleep_us(0)` still fires events already due at `now`.

**Done when:** all seven pass. Realtime mode gets one loose timing test
(`sleep_us(50_000)` takes 30–200 ms of wall time) marked `@pytest.mark.slow`.

---

### T003 — `framebuf` shim: geometry primitives
**Deps:** T001. **Size:** M.

**Files:** `smotoremu/backends/cpython_shim/framebuf.py`,
`smotoremu/backends/cpython_shim/micropython.py`,
`tests/emulator/test_framebuf.py`.

**Spec:** Pure-Python `framebuf.FrameBuffer` matching MicroPython's semantics for
the two formats this repo uses:

- `MONO_VLSB = 0`: byte index `(y // 8) * width + x`, bit `y % 8` (LSB = topmost
  of the 8-pixel column). Used by `ssd1306.SSD1306` for the display buffer.
- `MONO_HLSB = 1`: byte index `y * ((width + 7) // 8) + (x // 8)`, bit
  `7 - (x % 8)`. Used by every icon in `icons.py`.

```python
class FrameBuffer:
    def __init__(self, buffer: bytearray, width: int, height: int, format: int, stride: int | None = None)
    def fill(self, c: int) -> None
    def pixel(self, x: int, y: int, c: int | None = None) -> int | None
    def hline(self, x, y, w, c); def vline(self, x, y, h, c)
    def line(self, x1, y1, x2, y2, c)          # Bresenham
    def rect(self, x, y, w, h, c)              # outline
    def fill_rect(self, x, y, w, h, c)
    def blit(self, fbuf, x, y, key=-1)         # key = transparent colour, -1 = none
    def scroll(self, xstep, ystep)
```

Clipping: all primitives clip silently to bounds — MicroPython does not raise on
out-of-range coordinates, and `icons.graph()` draws at coordinates that go
outside the 128×64 buffer. Getting this wrong turns into an `IndexError` deep
inside device code.

`blit(fbuf, x, y, 0)` — the form `icons.py` uses everywhere — means colour 0 is
transparent. Implement `key` properly; do not treat it as a boolean.

`micropython.py` shim: `const = lambda x: x`, plus a no-op `native`/`viper`
decorator pair.

**Test first:** for each format, round-trip `pixel()` set/get at the four
corners and at a byte boundary; a known 8×8 `MONO_HLSB` pattern produces the
expected bytes; `fill_rect` clipped at each edge; `blit` with `key=0` leaves the
destination intact where the source is 0 and overwrites where it is 1;
`line()` matches Bresenham on a 45° and a shallow case. Also: constructing
every `FrameBuffer` in `icons.py` succeeds (`import icons` is the real target,
but that needs T004's `text()` — assert only construction here).

**Done when:** tests pass. **Do not implement `text()` here** — that's T004.

---

### T004 — 8×8 font and `FrameBuffer.text()`
**Deps:** T003. **Size:** S–M.

**Files:** `smotoremu/assets/font_petme128_8x8.py`,
`smotoremu/backends/cpython_shim/framebuf.py` (extend),
`tests/emulator/test_framebuf_text.py`.

**Spec:** Vendor MicroPython's `extmod/font_petme128_8x8.h` as a Python
`bytes` object with the MIT licence header preserved and the source URL in a
comment. Layout: 8 bytes per glyph, glyphs for ASCII 32–126 in order; **each
byte is a column**, bit 0 = topmost pixel. Render exactly as `framebuf.c` does:

```python
def text(self, s, x, y, c=1):
    for ch in s:
        code = ord(ch)
        if code < 32 or code > 126:
            code = 127          # MicroPython clamps out-of-range to a block glyph
        # 8 columns, LSB-first rows, drawn at (x + col, y + bit)
```

Characters are drawn 8 px apart with no spacing; off-screen characters clip.

**Getting the font:** fetch from
`https://raw.githubusercontent.com/micropython/micropython/master/extmod/font_petme128_8x8.h`.
If there is no network access, stop and ask — do **not** hand-draw a
substitute font. Every downstream text assertion and the entire glyph
reverse-map (T005) depend on it being byte-exact.

**Test first:** `text("A", 0, 0)` sets exactly the pixels of the known 'A'
bitmap; `text("AB", 0, 0)` places 'B' at x=8; text at `y=60` clips to the buffer
without error; a non-ASCII char renders the fallback glyph rather than raising.
**Then:** `import icons` succeeds under the shim — this is the real acceptance
gate, since `icons.py` builds 20 FrameBuffers at import time.

**Done when:** the above pass and `python -c "import icons"` works with the shim
on `sys.path`.

---

### T005 — Glyph reverse map (selectable screen text)
**Deps:** T004. **Size:** S. **(This is spike S2, promoted to a task — the
mechanism is straightforward once T004 is byte-exact.)**

**Files:** `smotoremu/screen_text.py`, `tests/emulator/test_screen_text.py`.

**Spec:**

```python
GLYPHS: dict[bytes, str]        # 8-byte column bitmap -> character
def build_glyph_map() -> dict[bytes, str]: ...
def extract_text(buffer: bytes, width: int = 128, height: int = 64,
                 unknown: str = "·") -> list[str]:
    """Read the MONO_VLSB framebuffer on an 8x8 grid, returning 8 rows of
    16 characters. Cells matching no glyph become `unknown`."""
def extract_lines(buffer, **kw) -> list[str]:
    """As extract_text but right-stripped, with blank rows dropped."""
```

First assert the map is **injective** — if two glyphs share a bitmap, the design
is unsound and you must stop and report it. (Space and any all-zero glyph will
collide; treat all-zero as `" "` explicitly and exclude it from the injectivity
check.)

Text drawn at a non-multiple-of-8 origin will not land on the grid.
`myfavcolor.screen()` draws at `x=5` and `x=20`, `y=15,25,...` — **none of which
are multiples of 8.** So the naive grid scan will fail on the real screens.
Handle this: scan at every `(dx, dy)` offset in `0..7 × 0..7`, score each
alignment by how many cells match a known glyph, and use the best-scoring
alignment (recorded in the result). Add `extract_text(..., origin=(x, y))` to
force one.

**Test first:** injectivity (excluding the blank glyph); render `"HELLO"` at
(0,0) into a real buffer via T004 and recover exactly `"HELLO"`; render at
(5,15) and recover it via alignment search; a buffer with a diagonal line
through a glyph yields `unknown` for that cell and still recovers its
neighbours; an empty buffer yields no lines from `extract_lines`.

**Done when:** the (5,15) case passes — that is the real-world case.

---

# Phase 1 — Board and peripherals

### T006 — `machine` shim: Pin, ADC, PWM
**Deps:** T002. **Size:** M.

**Files:** `smotoremu/board.py`, `smotoremu/backends/cpython_shim/machine.py`,
`tests/emulator/test_board_pins.py`.

**Spec:** `Board` owns pin state; the `machine` shim is a thin adapter that
finds the current `Board` via a module-level session context.

```python
class Board:
    def __init__(self, clock, scheduler, rng): ...
    def digital_read(self, pin_id: int) -> int
    def digital_write(self, pin_id: int, value: int) -> None
    def set_pin_mode(self, pin_id: int, mode: str) -> None   # "IN" | "OUT"
    def adc_read(self, pin_id: int) -> int                   # 0..4095
    def pwm_set(self, pin_id: int, freq: int, duty: int) -> None
    def on_pwm_change(self, pin_id, callback)                # servo subscribes
```

Pin map (from this repo — put it in `smotoremu/pinmap.py` as named constants):

| Pin | Role | Source |
| --- | --- | --- |
| 2 | Servo PWM | `myfavcolor.init_hardware`: `servo.Servo(Pin(2))` |
| 3 | Potentiometer ADC | `sensors.SENSORS.__init__` |
| 4 | Battery ADC | `sensors.SENSORS.__init__` |
| 5 | Sensor port, analog **or** digital | `sensors.selectsensor()` |
| 6 | I2C SDA | `sensors.i2c` |
| 7 | I2C SCL | `sensors.i2c` |
| 8 | Button DOWN (active low) | `main.py`, `myfavcolor.py` |
| 9 | Button SELECT (active low) | ditto |
| 10 | Button UP (active low) | ditto |

Buttons default to 1 (released) — they are active-low with external pull-ups.
`ADC.atten()` is accepted and recorded but changes nothing in v1 (everything in
this repo uses `ATTN_11DB`). `ADC.read()` returns 0–4095. Pin 5 is special: it
can be re-created as `Pin(5, Pin.OUT)` and as `ADC(Pin(5))` alternately within
one function (`selectsensor()` does exactly that) — the board must track the
most recent mode and let T017's port model decide the resulting reading.

Each `ADC.read()` costs virtual time: `# ESP32-C3 SAR ADC, ~20 us/sample`
(GUESS: needs bench data). This matters — `sensors.readpoint()` takes 200
samples in a loop.

**Test first:** buttons read 1 by default and 0 when `board.press("up")`;
`Pin(5, Pin.OUT).value(1)` then `ADC(Pin(5)).read()` reflects the port model
stub; `PWM(Pin(2), freq=50, duty=61)` fires the `on_pwm_change` callback;
`adc_read` advances the clock by the sample cost; unknown pin ids raise.

---

### T007 — I2C bus
**Deps:** T006. **Size:** M. **Read the spec carefully — the method set is
dictated by `ssd1306.py`, not by convention.**

**Files:** `smotoremu/i2c.py`, `smotoremu/backends/cpython_shim/machine.py`
(extend), `tests/emulator/test_i2c.py`.

**Spec:** `SoftI2C`/`I2C` must implement **all six** methods this repo calls:

| Method | Called by |
| --- | --- |
| `scan()` | `main.main()`, `VEML6040.__init__` |
| `writeto(addr, buf)` | `ssd1306.SSD1306_I2C.write_cmd` |
| `writevto(addr, list_of_buffers)` | `ssd1306.SSD1306_I2C.write_data` ← **easy to miss** |
| `readfrom_mem(addr, memaddr, n)` | `adxl345`, `VEML6040._read_word` |
| `writeto_mem(addr, memaddr, buf)` | `adxl345`, `VEML6040._write_word` |
| `readfrom(addr, n)` | not currently used; implement anyway |

```python
class I2CBus:
    def register(self, addr: int, device: I2CDevice) -> None
    def unregister(self, addr: int) -> None
    def scan(self) -> list[int]        # sorted
```

Device protocol: `on_write(data: bytes, is_continuation: bool)`,
`on_read(n: int) -> bytes`. `readfrom_mem`/`writeto_mem` are implemented on top
(write the mem address, then read/write) so a device only implements the two
primitives, matching real bus behaviour.

Timing: charge `(len(data) + 1) * 9 / freq` seconds per transaction plus a
`# ~10 us start/stop overhead` constant. Default `freq=400_000` —
`# MicroPython SoftI2C default; sensors.py constructs with no freq=`.

Addressing an unregistered device raises `OSError(19)` (ENODEV) — this is
load-bearing: `sensors.SENSORS.__init__` catches `OSError` to handle a missing
ADXL345, and `VEML6040.__init__` raises `RuntimeError` when 0x10 is absent,
which is what makes `main.choose_activity` fall through to `standalone`.

**Test first:** `scan()` returns registered addresses sorted; `writevto` with
`[b"@", bytearray(1024)]` delivers 1025 bytes as one transaction to the device;
a 1025-byte write advances the clock by ~23 ms (assert 20–27 ms);
`readfrom_mem` on an unregistered address raises `OSError`;
`writeto_mem`/`readfrom_mem` round-trip against a trivial memory device.

---

### T008 — `machine.Timer`, `unique_id`, `reset`
**Deps:** T006, T002. **Size:** S.

**Files:** `smotoremu/backends/cpython_shim/machine.py` (extend),
`tests/emulator/test_timer.py`.

**Spec:** `Timer(id)` with `init(period=, mode=, callback=)` and `deinit()`,
backed by `EventScheduler.every`. `period` is in **milliseconds**.
`Timer.PERIODIC = 1`, `Timer.ONE_SHOT = 0`. The callback receives the timer
object as its one argument (`myfavcolor.displaybatt(p)` relies on this).
`deinit()` on a never-initialised timer is a no-op (`myfavcolor.main()` calls
`batt.deinit()` before `batt.init()`).

`unique_id()` returns a fixed 4-byte value, session-configurable.
`machine.reset()` raises `DeviceReset`, caught by the session runner (T013).

Callbacks run on the scheduler, i.e. between device-code I/O operations, not
truly pre-emptively. Document this limitation in the module docstring: real ISR
re-entrancy bugs will not reproduce.

**Test first:** a periodic 10 s timer fires 5 times across 50 virtual seconds;
`deinit()` stops it; the callback receives the timer instance; `deinit()` before
`init()` doesn't raise; `Timer(1)` and `Timer(2)` are independent.

---

### T009 — SSD1306 display peripheral
**Deps:** T007, T003, T005. **Size:** L. **The highest-value task in Phase 1.**

**Files:** `smotoremu/peripherals/ssd1306.py`, `tests/emulator/test_display.py`.

**Spec:** An `I2CDevice` at `0x3C` that interprets the real command stream.
Control-byte protocol: the first byte of each transaction is `0x80` (Co=1,
D/C#=0 → single command follows) or `0x40`/`b"@"` (D/C#=1 → data follows).
`ssd1306.py` sends commands one at a time via `write_cmd` and the whole 1024-byte
buffer via `writevto(addr, [b"@", buf])`.

Commands to implement (all of these are actually sent by `init_display()` and
`show()`):

| Cmd | Meaning | Behaviour |
| --- | --- | --- |
| `0xAE`/`0xAF` | display off/on | track `on` |
| `0x20` +1 byte | memory addressing mode | only `0x00` (horizontal) needed |
| `0x21` +2 | column address range | set `col_start`, `col_end` |
| `0x22` +2 | page address range | set `page_start`, `page_end` |
| `0x40..0x7F` | display start line | track |
| `0xA0`/`0xA1` | segment remap | track (`0xA1` is sent) |
| `0xA8` +1 | mux ratio | track |
| `0xC0`/`0xC8` | COM scan direction | track (`0xC8` is sent) |
| `0xD3` +1 | display offset | track |
| `0xDA` +1 | COM pin config | track |
| `0xD5` +1 | clock divide | track |
| `0xD9` +1 | precharge | track |
| `0xDB` +1 | VCOM deselect | track |
| `0x81` +1 | contrast | track |
| `0xA4`/`0xA5` | entire-display-on | track |
| `0xA6`/`0xA7` | normal/inverted | affects rendering |
| `0x8D` +1 | charge pump | track |

Multi-byte commands: `ssd1306.py` sends each parameter as its own `write_cmd`
transaction, so the device needs a small state machine holding "expecting N more
parameter bytes for command X".

Data writes fill GDDRAM in horizontal addressing mode: advance the column, wrap
to the next page at `col_end`, wrap to `page_start` after `page_end`.

```python
class SSD1306Device(I2CDevice):
    @property
    def gddram(self) -> bytes           # 1024 bytes, MONO_VLSB layout
    def pixels(self) -> list[list[int]] # 64 rows x 128, honouring invert + on/off
    def to_png(self, scale: int = 4) -> bytes
    def text_lines(self) -> list[str]   # via screen_text.extract_lines
    frame_count: int                    # incremented on each full-buffer write
    on_frame: callback                  # UI + trace subscribe
```

PNG encoding: hand-rolled with `zlib` + `struct` — a greyscale PNG is ~40 lines
and avoids a Pillow dependency (R4).

**Test first:**
1. Feed the exact `init_display()` command sequence → device reports on, not
   inverted, horizontal addressing.
2. Write a known 1024-byte buffer via `writevto` → `gddram` matches byte-for-byte.
3. A partial write (col range 0–7) lands only in those columns.
4. `0xA7` inverts `pixels()` but leaves `gddram` unchanged.
5. **Integration:** construct the *real* `icons.SSD1306_SMART(128, 64, bus,
   switch_up)`, call `.text("HELLO", 5, 15)` and `.show()`, and assert
   `text_lines() == ["HELLO"]`. This is the end-to-end proof of the whole
   display + font + reverse-map chain — if it passes, the screen story is done.
6. `to_png()` output starts with the PNG magic and decodes to the right size.

---

### T010 — Servo model
**Deps:** T006. **Size:** M.

**Files:** `smotoremu/peripherals/servo.py`, `tests/emulator/test_servo.py`.

**Spec:** Subscribe to PWM changes on pin 2. Decode duty → pulse width → angle,
inverting `servo.Servo.write_us`:

```
us    = duty * 1_000_000 / (1024 * freq)      # freq = 50, duty is 10-bit
angle = (us - 600) * 180 / (2400 - 600)       # min_us=600, max_us=2400
```

**Reproduce the quantization.** `duty()` is 10-bit, so one duty step is
`1e6/(1024*50) = 19.53 us = 1.95 degrees`. The commanded angle is therefore
quantized to ~2° and a requested 90° does not land on exactly 90°. This is real
hardware behaviour, it explains why `myfavcolor.POT_THRESHOLD = 50`
(≈2.2° of pot travel) was chosen, and tests must be written against the
quantized value. Do not round it away.

`duty=0` means "signal disabled" — hold the current angle, don't move to 0.

Motion model: `commanded_angle` jumps immediately; `actual_angle` slews at
`SLEW_DEG_PER_SEC = 400` (`# GUESS: ~0.15 s/60deg hobby servo; needs bench data`)
via a scheduled event, then settles. `angle` reported to the UI and tests is
`actual_angle`. Provide `expect_settled()` support: `is_moving` property.

```python
class ServoModel:
    commanded_angle: float    # from PWM, quantized
    actual_angle: float       # slewed
    is_moving: bool
    on_change: callback
```

**Test first:** `write_angle(0)` → 0.0°; `write_angle(180)` → within one
quantum of 180; `write_angle(90)` → the quantized neighbour of 90 (assert the
exact expected value, computed by hand in the test); `write_angle(200)` clamps
to ≤180 (via the `% 360` path, R6); `duty(0)` holds position; a 0→180 move takes
~450 ms of virtual time and `is_moving` is True in the middle and False after.

---

### T011 — Buttons, potentiometer, battery
**Deps:** T006. **Size:** S–M.

**Files:** `smotoremu/peripherals/inputs.py`, `tests/emulator/test_inputs.py`.

**Spec:**

```python
class Buttons:
    def press(self, name: str) -> None      # "up" | "down" | "select"
    def release(self, name: str) -> None
    def click(self, name: str, hold_ms: int = 120) -> None   # schedules the release
    def held(self) -> set[str]
```
Active-low on pins 10/8/9. Optional contact bounce: `bounce_ms = 0` by default;
when non-zero, the pin toggles a few times over that window. Leave bounce off by
default so tests are clean, but implement it — `waitforbutton()`'s
press-then-wait-for-release loop is exactly the code bounce would break.

```python
class Potentiometer:
    def set_raw(self, raw: int) -> None          # 0..4095
    def set_angle(self, degrees: float) -> None  # convenience, see below
    noise_lsb: int = 8    # GUESS: needs bench data
```
`set_angle` inverts `myfavcolor.update_motor_with_pot`:
`new_angle = int((1 - pot/4095) * 180)`, so `raw = int(4095 * (1 - deg/180))`.
Note the inversion — turning the pot up lowers the angle. Noise is
`rng.gauss(0, noise_lsb)` clamped to 0–4095, applied per `read()`. Noise is
what makes `POT_THRESHOLD` and `readpoint()`'s 100-sample median meaningful, so
it must be per-read, not per-set.

```python
class Battery:
    def set_raw(self, raw: int) -> None
    def set_state(self, state: str) -> None   # "charging"|"full"|"half"|"low"
```
`set_state` picks a raw value **unambiguously inside** each band per
`sensors.readbattery()`: charging ≥2900, full 2750, half 2600, low 2400. Note
in the docstring that 2850–2875 is ambiguous and 2500/2700 exactly are dead
zones (R6) — and provide `set_raw` so tests can target those quirks deliberately.

**Test first:** press/release changes the pin; `click()` auto-releases after the
hold; `set_angle(90)` → a raw that maps back to ~90 through the device formula
(assert the round-trip through `myfavcolor.update_motor_with_pot`'s arithmetic);
noise stays in range and varies between reads; each `set_state` produces the
matching `readbattery()` string when run through the real function.

---

### T012 — ADXL345 accelerometer
**Deps:** T007. **Size:** S–M.

**Files:** `smotoremu/peripherals/adxl345.py`, `tests/emulator/test_adxl.py`.

**Spec:** `I2CDevice` at `0x53`. Accept writes to `0x2D` (power control — the
driver writes 0, 16, 8 in sequence at init) and serve 6 bytes at `0x32`:
x, y, z as little-endian signed 16-bit.

Scale: `# ADXL345 default +-2g, 10-bit right-justified, 3.9 mg/LSB -> 256 LSB/g`.
Flat and level = `(0, 0, 256)`.

```python
class ADXL345Device(I2CDevice):
    def set_orientation(self, roll_deg: float, pitch_deg: float) -> None
    def set_gravity(self, x: float, y: float, z: float) -> None   # in g
    noise_lsb: int = 2
```

Round-trip requirement: `set_orientation(r, p)` followed by the real
`adxl345.ADXL345.RP_calculate()` must return approximately `(r, p)`. Derive the
inverse of `roll = atan2(y, z)`, `pitch = atan2(-x, sqrt(y²+z²))` and prove it
in the test — this is the contract the UI's drag widget depends on.

Also support "no accelerometer fitted": when absent from the bus, the real
`sensors.SENSORS.__init__` catches `OSError` and sets `self.adx = None`.

**Test first:** flat → `(0, 0, 256)`; `set_orientation(30, -20)` → `RP_calculate`
returns (30, −20) within 1°; the init write sequence is accepted; noise stays
bounded; with the device unregistered, `sensors.SENSORS()` constructs with
`adx is None`.

---

# Phase 2 — Session and runtime

### T013 — Session and device-code runner
**Deps:** T002, T006–T012. **Size:** L. **The integration point.**

**Files:** `smotoremu/session.py`, `smotoremu/backends/cpython_shim/__init__.py`,
`tests/emulator/test_session.py`.

**Spec:**

```python
class Session:
    def __init__(self, *, seed=0, clock_mode="instant", world=None,
                 vfs_dir=None, board_config=None): ...
    board: Board;  clock: VirtualClock;  bus: I2CBus;  rng: random.Random
    display: SSD1306Device;  servo: ServoModel;  buttons: Buttons
    pot: Potentiometer;  battery: Battery;  accel: ADXL345Device | None
    port: Port

    def boot(self, entry: str = "main") -> None    # start device code
    def run_until_idle(self, timeout_ms: int = 5000) -> None
    def stop(self) -> None
    @property
    def exited(self) -> bool
    @property
    def error(self) -> BaseException | None
```

Concurrency: device code runs in a **daemon thread**; the controlling thread
(test or websocket server) drives the virtual clock. Use a strict handoff: the
device thread blocks on a condition variable whenever it calls `sleep` or does
I/O in instant mode, and the controller advances the clock. **Only one thread
runs at a time** — never both. Document the handoff invariant at the top of the
module; every later concurrency bug will trace back to it.

Module injection: put `smotoremu/backends/cpython_shim/` first on `sys.path` so
`import machine`, `import framebuf`, `import micropython` resolve to shims. The
shims find the active session through a `contextvars.ContextVar`. Purge
`sys.modules` of device modules between sessions — `myfavcolor` holds
module-level globals (`sens`, `display`, `sensor`, `last_servo_angle`) and
`files.py` does `del sys.modules["data"]` tricks, so stale state across sessions
is a real hazard. Write the purge as an explicit, tested list.

`sys.exit()` inside device code (`myfavcolor.main()` calls it on the REPL escape
hatch) must be caught and surfaced as `session.exited`, not crash the runner.

**Test first:**
1. A trivial injected module that sets a pin runs and completes.
2. `boot("main")` with no I2C devices dispatches to `standalone` (assert via a
   monkeypatched marker, not by running the whole activity).
3. `boot("main")` with `0x10` registered dispatches to `myfavcolor`.
4. An exception in device code is captured in `session.error`, not raised in the
   controller thread.
5. `sys.exit()` in device code sets `exited` cleanly.
6. Two sessions in one process don't leak module state (run test 2 then 3 and
   assert both).

---

### T014 — Virtual filesystem
**Deps:** T013. **Size:** M.

**Files:** `smotoremu/vfs.py`, `smotoremu/backends/cpython_shim/os_shim.py`,
`tests/emulator/test_vfs.py`.

**Spec:** Each session gets a real temp directory as its flash. Device code's
`open()`, `os.listdir()`, `os.remove()` are chrooted to it. The simplest correct
approach: `os.chdir()` into the session dir on the device thread and forbid
absolute paths — document the limitation (it makes sessions non-parallel within
a process; if that bites, upgrade to a path-rewriting `open` shim).

```python
class VFS:
    def put(self, name: str, content: bytes | str) -> None
    def get(self, name: str) -> bytes
    def listdir(self) -> list[str]
    def wipe(self) -> None
    def load_manifest(self, manifest_path: str, source_dir: str) -> None
    MAX_FILE_BYTES: int          # same threshold as tests/test_filesize.py
```

`put` raises `FileTooLargeError` above the threshold — the emulator should fail
where the real CEEO uploader fails. Read the current threshold out of
`tests/test_filesize.py` rather than re-deriving it.

Must support the `files.py` pattern end to end: write `data.py`, `import data`,
`del sys.modules["data"]`, re-import, see new contents.

**Test first:** `savetofile([[1,2]])` from the real `files.py` creates `data.py`
in the VFS and `readfile()` returns it; `resetprefs(1)` writes `mode=1` and a
re-import sees it; an oversized `put` raises; `wipe()` empties it; the host
filesystem outside the session dir is untouched (assert a sentinel file in cwd
is not visible to `os.listdir()`).

---

### T015 — Trace recorder
**Deps:** T013. **Size:** S–M.

**Files:** `smotoremu/trace.py`, `tests/emulator/test_trace.py`.

**Spec:** Every I/O event as `(t_us, kind, detail)` with
`kind ∈ {pin, adc, pwm, i2c, timer, frame, log, servo, button}`. Ring buffer,
default 100k events, `to_jsonl()` / `from_jsonl()`. Session records its seed and
config in the header record so a trace fully identifies a run.

Also capture device `print()` output (`myfavcolor.screen()` prints every changed
screen) as `log` events — that stream is genuinely useful in the UI.

**Test first:** a session that presses a button and reads an ADC produces events
in timestamp order with the right kinds; the ring buffer drops oldest;
`to_jsonl`/`from_jsonl` round-trips; the header records the seed.

---

# Phase 3 — World and sensors

### T016 — World model
**Deps:** T001. **Size:** S–M.

**Files:** `smotoremu/world.py`, `smotoremu/worlds/three_patches.yaml`,
`tests/emulator/test_world.py`.

**Spec:** What the arm is pointing at.

```python
class World:
    ambient_lux: float
    def color_at(self, angle_deg: float) -> tuple[int, int, int]   # sRGB 0-255
    def lux_at(self, angle_deg: float) -> float
    def patch_at(self, angle_deg: float) -> Patch | None
    @classmethod
    def load(cls, path: str) -> "World"
    def to_dict(self) -> dict                # for the UI
```

Format per `EMULATOR_DESIGN.md` §5. **No PyYAML** (R4) — use JSON, or a
20-line parser for the trivial subset. Recommend JSON (`.json`) and update the
design doc's example accordingly; the UI will be editing these anyway.

Patches are angle ranges with a colour; overlapping ranges are an error at load;
gaps fall back to `default_color`. Add an optional `blur_deg` so patch edges
ramp rather than step — the real sensor has a finite spot size, and a hard step
makes calibration tests unrealistically clean. Default `blur_deg = 3`
(`# GUESS: sensor spot size; needs bench data`).

**Test first:** `color_at` inside a patch returns its colour; between patches
returns the default; a blurred boundary interpolates monotonically; overlapping
patches raise at load; the shipped `three_patches.json` loads and has red/white/
blue regions.

---

### T017 — Sensor port and attachment probing
**Deps:** T006, T007. **Size:** M. **Subtle — read `sensors.selectsensor()` line
by line before starting.**

**Files:** `smotoremu/port.py`, `tests/emulator/test_port.py`.

**Spec:** The port carries pin 5 plus the I2C bus, with the analog/I2C toggle.

`sensors.selectsensor()` probes like this: drive pin 5 low, read it as ADC
(`low`); drive it high, read it as ADC (`high`); conclude **not attached** iff
`low < 200 and high > 4000`. The logic is "if the pin just follows whatever I
drive it to, nothing is loading it."

```python
class Port:
    def attach(self, sensor: SensorModel) -> None
    def detach(self) -> None
    attached: SensorModel | None
    mode: str                    # "analog" | "i2c" -- the "!" toggle
    def pin5_adc(self) -> int    # what ADC(Pin(5)).read() returns right now
```

`pin5_adc()` resolution order:
1. Nothing attached → return the driven level (0 or 4095, plus noise), which
   makes `selectsensor()` say "not attached". ✔
2. Analog sensor attached → return the sensor's output voltage scaled to
   0–4095, **ignoring** the drive level (the sensor's output stage wins). This
   makes `selectsensor()` say "attached" as long as the sensor's output isn't
   coincidentally at a rail.
3. I2C sensor attached (mode `"i2c"`) → the port model decides; assume the pin
   floats near mid-scale, so `selectsensor()` reports attached.

**Flag for the user (open question in `EMULATOR_DESIGN.md` §12):** what the
analog/I2C toggle does electrically is unknown. Implement `mode` as a simple
gate — in `"analog"` mode, I2C sensors on the port are unregistered from the
bus; in `"i2c"` mode, analog readings on pin 5 return the floating value. Mark
this `# ASSUMPTION: awaiting confirmation` and keep the logic in one place so
it's a one-line change later.

**Test first:** with nothing attached, the real `sensors.SENSORS().attached` is
False; with a stub analog sensor outputting mid-scale, it's True; toggling to
`"analog"` mode removes an attached I2C sensor from `bus.scan()`; toggling back
restores it.

---

### T018 — Sensor plug-in base and registry
**Deps:** T017. **Size:** S.

**Files:** `smotoremu/sensors/__init__.py`, `smotoremu/sensors/base.py`,
`tests/emulator/test_sensor_registry.py`.

**Spec:** The `SensorModel` ABC and `ui_schema()` from `EMULATOR_DESIGN.md` §6,
plus:

```python
@register("VEML6040")
class VEML6040Model(SensorModel): ...

def get_sensor(part_number: str) -> type[SensorModel]
def list_sensors() -> list[dict]        # part_number, display_name, interface
```

Auto-import every module in `smotoremu/sensors/` on package import so the
decorators run. Calibration constants load from
`smotoremu/sensors/data/<part>.json` via a `calibration()` classmethod, so bench
data can be updated without touching code (R5).

**Test first:** a dummy sensor registered via the decorator is discoverable by
name; registering a duplicate name raises; `list_sensors()` includes it;
`get_sensor("nope")` raises a helpful error naming the available parts.

---

### T019 — VEML6040 colour sensor plug-in
**Deps:** T018, T016. **Size:** L. **The flagship sensor.**

**Files:** `smotoremu/sensors/veml6040.py`,
`smotoremu/sensors/data/veml6040.json`, `tests/emulator/test_veml6040.py`.

**Spec:** I2C device at `0x10`, register-accurate against the driver in
`myfavcolor.py`:

- `0x00` CONF, 16-bit little-endian. Bits: `SD` (0x01, shutdown), `AF` (0x02,
  auto/manual force), `TRIG` (0x04), `IT` (0x70 mask, value `n << 4` selects
  `40 ms << n`, so n=0→40 ms … n=5→1280 ms).
- `0x08` R, `0x09` G, `0x0A` B, `0x0B` W — 16-bit little-endian counts.

**Integration-time gating is the point of this task.** Model a conversion cycle:
when enabled, a conversion starts, takes `IT` milliseconds, and on completion
latches new counts. A read returns the **last latched** values. So a read issued
100 ms after a servo move, with `IT_640MS` configured (the repo's default), still
returns the colour from *before* the move. Reproducing this is the single most
valuable behaviour in the emulator — it is the bug class this activity keeps
hitting on real hardware.

Counts model:

```
counts_ch = clamp(0, 65535,
    sensitivity_ch * reflectance_ch(world_color) * illumination * (IT_ms / 40)
    + dark_counts_ch + shot_noise)
```

Calibrate `sensitivity_ch` so that the blue channel is weak: the repo's
`WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)` is a real measurement from this
hardware. **Target: pointing at white and running `myfavcolor`'s white-balance
step should produce factors within ~15% of those.** That is the acceptance
criterion for the model being right, and it must be *emergent* from per-channel
sensitivity — do not hardcode the triple.

Also match the driver's `rgb` property path: raw counts `>> 6`, clamped to 255.
At `IT_640MS` pointed at white, counts should land high enough that `>> 6` gives
a useful 0–255 range without saturating — the code comment says values are much
smaller than 255 at ≤320 ms, so scale with IT accordingly.

**Test first:**
1. `scan()` includes `0x10`; the real `VEML6040.__init__` constructs without
   raising.
2. Writing CONF with `IT_640MS` then reading it back returns the same value.
3. With `SD` set (shutdown), counts freeze.
4. **Integration-time gating:** set world to red, read → red; change world to
   blue, read immediately → *still red*; advance 640 ms, read → blue. This test
   is the whole point; write it first and make sure it fails informatively.
5. White balance: run the real `Environment.calibrate_white_balance()` against a
   white patch and assert the resulting factors are within 15% of
   `(1.0, 1.066, 1.948)` after normalising the red channel to 1.0.
6. Saturation: an extremely bright world clips at 65535 raw / 255 scaled.

---

### T020 — Grove slide potentiometer plug-in
**Deps:** T018. **Size:** S.

**Files:** `smotoremu/sensors/grove_slide_pot.py`,
`smotoremu/sensors/data/grove_slide_pot.json`,
`tests/emulator/test_slide_pot.py`.

**Spec:** Analog, 10 kΩ linear track. `position` 0.0–1.0 → 0–3.3 V → 0–4095.
ADC non-linearity as a piecewise-linear table in the JSON (identity by default,
`# GUESS: ESP32-C3 ADC is notably non-linear near the rails; needs bench data`),
plus per-read Gaussian noise. `ui_schema()` exposes a slider.

Must satisfy T017's attachment probe: a mid-scale position reads as attached.
Edge case worth testing: position 0.0 outputs ~0, which is *below* the probe's
`low < 200` threshold — combined with `high > 4000`, does that make it read as
unattached? Work out the truth-table by hand, encode it in the test, and note
the result. (It shouldn't — `high` will also read ~0 — but prove it.)

**Test first:** position → raw mapping at 0.0/0.5/1.0; noise bounded and
varying; attachment probe reports True at 0.0, 0.5, and 1.0; `ui_schema()` is
well-formed.

---

### T021 — Grove light sensor plug-in
**Deps:** T018, T016. **Size:** S–M.

**Files:** `smotoremu/sensors/grove_light.py`,
`smotoremu/sensors/data/grove_light.json`,
`tests/emulator/test_light_sensor.py`.

**Spec:** Phototransistor + op-amp; response is non-linear in lux and saturates.
Model as a log-ish curve from a calibration table (`lux → volts`), clamped,
coupled to `world.lux_at(servo.actual_angle)` plus `world.ambient_lux`, plus
noise.

The consumer is `sensors.readpoint()`, which takes 100 samples, sorts, and takes
the middle 30 — so per-read noise must be independent, or that median does
nothing and a real behaviour goes untested.

**Test first:** monotonic increasing in lux; saturates at high lux; the real
`sensors.readpoint()` against a stable world returns a stable value across
repeated calls (median suppresses the noise); increasing world lux moves it up.

---

# Phase 4 — Test API

### T022 — `smotor` facade and pytest fixtures
**Deps:** T013. **Size:** M.

**Files:** `smotoremu/testing.py`, `smotoremu/__init__.py` (extend),
`tests/emulator/test_facade.py`.

**Spec:**

```python
import smotor
sm = smotor.launch(sensor="VEML6040", world="worlds/three_patches.json",
                   clock="instant", seed=0, headed=False)
sm.boot()          # runs main.py
sm.close()
```

Fixtures in `smotoremu.testing` (exported as a pytest plugin via
`pyproject.toml` entry point so `tests/` can use them without path games):
`sm` (bare board, no sensor), `sm_color` (VEML6040 + three-patch world),
`sm_analog` (light sensor). All default to `clock="instant"`, `seed=0`, and
auto-close.

Convenience surface, thin wrappers over Phase 1–3 objects:
`sm.press(name)`, `sm.release(name)`, `sm.click(name)`,
`sm.pot.set_angle(deg)`, `sm.arm.angle`, `sm.screen.lines()`,
`sm.screen.png()`, `sm.tilt(roll, pitch)`, `sm.battery.set_state(s)`,
`sm.world`, `sm.trace`.

**Test first:** each fixture yields a working session; `launch()` with an
unknown sensor name raises a helpful error; `close()` is idempotent; two
sequential sessions in one test are independent.

---

### T023 — Auto-waiting `expect`
**Deps:** T022. **Size:** M. **Get the semantics right; everything downstream
depends on them.**

**Files:** `smotoremu/expect.py`, `tests/emulator/test_expect.py`.

**Spec:** Playwright-shaped polling assertions against the **virtual** clock.

```python
def wait_for(predicate, *, timeout_ms=5000, poll_ms=10, message=None): ...

class Expectation:
    def to_be(self, value, *, timeout_ms=5000)
    def to_be_close(self, value, abs_tol, *, timeout_ms=5000)
    def to_contain(self, substring, *, timeout_ms=5000)
    def not_(self) -> "Expectation"

smotor.expect(sm.screen).to_have_text("Point at WHITE")
smotor.expect(lambda: sm.arm.angle).to_be_close(90, 3)
```

Waiting works by letting the device thread run and advancing the virtual clock
by `poll_ms` per iteration, re-checking between steps. Timeout is in **virtual**
milliseconds. On failure the message must include: what was expected, the actual
value at timeout, virtual elapsed time, and the last 8 screen lines — debugging
a headless emulator with a bare `assert False` is miserable.

Guard against the device thread having exited: if `session.exited` or
`session.error` is set, fail immediately with that error rather than spinning to
timeout.

**Test first:** a predicate already true returns immediately with no clock
advance; one that becomes true after 500 virtual ms passes and reports ~500 ms
elapsed; one that never becomes true raises `TimeoutError` after exactly the
virtual timeout; the failure message contains the actual value and screen text;
a crashed device thread fails fast rather than at timeout.

---

### T024 — Screen locators and snapshots
**Deps:** T023, T009. **Size:** S–M.

**Files:** `smotoremu/screen.py`, `tests/emulator/test_screen_api.py`.

**Spec:**

```python
sm.screen.lines() -> list[str]
sm.screen.text() -> str                  # lines joined with "\n"
sm.screen.contains(s) -> bool
sm.screen.expect_text(s, timeout_ms=5000)     # auto-waits
sm.screen.expect_lines([...])                 # exact match, auto-waits
sm.screen.png(scale=4) -> bytes
sm.screen.frames() -> list[str]               # text of every frame so far
sm.screen.assert_snapshot(name)               # text snapshot in tests/emulator/__snapshots__/
```

`assert_snapshot` writes the file on first run (and says so loudly), compares
thereafter, with `SMOTOR_UPDATE_SNAPSHOTS=1` to re-record. **Text** snapshots,
not images — they diff readably in a PR.

**Test first:** `expect_text` finds text that appears three frames later;
`expect_lines` fails on a near-miss with a readable diff; snapshot creates then
matches then detects a change; `png()` differs between two different screens.

---

### T025 — Rewrite `test_flow.py` on the emulator
**Deps:** T024, T019. **Size:** M. **The milestone that proves the project.**

**Files:** `tests/test_flow.py` (rewrite),
`tests/emulator/test_myfavcolor_flow.py` (new home).

**Spec:** The current test MagicMocks `sensor`, `sens`, `switch_up`, patches
`Environment.__init__` and `learn` and `time`, then asserts a list of two
strings — it proves `main()` calls two functions. Replace it with a real run:

```python
def test_favorite_color_walkthrough(sm_color):
    sm_color.boot()
    sm_color.screen.expect_text("Starting in 2s")
    sm_color.screen.expect_text("Point at WHITE")
    sm_color.pot.set_angle(45)                 # white patch
    sm_color.click("select")
    sm_color.screen.expect_text("White Balance")
    sm_color.screen.expect_text("Set FAV color")
    sm_color.pot.set_angle(10)                 # red patch
    sm_color.click("select")
    for _ in range(myfavcolor.NUM_STATES):     # calibrate each state
        sm_color.click("select")
    sm_color.screen.expect_text("Press to start")
    sm_color.click("select")
    sm_color.screen.expect_text("E=0", timeout_ms=60_000)
```

**No mocks. No monkeypatching of device code.** If something can't be driven
without a mock, that's an emulator gap — file it and fix the emulator.

Expect this to shake out real bugs in the emulator (button debounce timing
against `waitforbutton()`, integration-time stalls, servo settle waits). That's
the point. Budget time for it.

Also add a negative-path test: boot with no colour sensor attached and assert
dispatch reaches `standalone`, not `myfavcolor`.

**Done when:** the walkthrough passes with zero mocks and runs in under 2
seconds of wall time in instant mode.

---

### T026 — Migrate the rest and delete the fakes
**Deps:** T025. **Size:** M.

**Files:** `tests/test_import_safety.py`, `tests/conftest.py`,
`tests/fakes/` (delete), `README.md` (update).

**Spec:** Per `EMULATOR_DESIGN.md` §8: `test_dispatch.py`,
`test_distance_math.py`, `test_qlearning.py`, `test_filesize.py` stay as they
are — pure functions don't need an emulator, and dragging one in would make them
slower and more fragile for no gain. `test_import_safety.py` moves onto the
emulator's shim path (and later onto the MicroPython backend, T037).

Delete `tests/fakes/` and strip `tests/conftest.py` back to nothing but the
`sys.path` root insert — the global `time.sleep` monkeypatch and the
`reset_mock_state` fixture both go away.

Update `README.md`'s "Emulator Fakes" section to describe the emulator, and
adjust the "What Still Requires Hardware" list: colour-sensor *readings* and
OLED *layout* are now covered in emulation; button *feel*, servo behaviour under
load, and upload reliability are not.

**Done when:** `pytest tests/ -v` passes with `tests/fakes/` deleted, and the
count of passing tests is ≥ what it was before.

---

# Phase 5 — Server and UI

### T027 — WebSocket server and protocol
**Deps:** T022. **Size:** M.

**Files:** `smotoremu/server.py`, `smotoremu/protocol.py`,
`tests/emulator/test_protocol.py`.

**Spec:** `python -m smotoremu.server --port 8765` serves `web/` statically and
one WebSocket. One session per connection (v1).

Client → server: `{"type": "press"|"release", "button": ...}`,
`{"type":"set_pot","raw":…}`, `{"type":"set_tilt","roll":…,"pitch":…}`,
`{"type":"set_world","world":{…}}`, `{"type":"clock","mode":…,"speed":…}`,
`{"type":"attach","part":…}`, `{"type":"detach"}`,
`{"type":"boot"}`, `{"type":"reset"}`, `{"type":"power","on":bool}`.

Server → client: `{"type":"frame","seq":n,"png":"<base64>","lines":[…]}`,
`{"type":"state","angle":…,"pot":…,"battery":…,"attached":…,"clock_ms":…}`,
`{"type":"log","t":…,"text":…}`, `{"type":"trace","events":[…]}`,
`{"type":"exited","error":…}`.

Every message carries `"v": 1`. Coalesce frame and state updates to ~30 Hz.

**Test first:** protocol encode/decode round-trips for every message type
(pure functions in `protocol.py`, testable without a socket); unknown message
type produces an error reply, not a crash; frames coalesce under rapid updates.
Socket-level tests are one thin integration test, not the bulk.

---

### T028 — Web UI: shell and OLED
**Deps:** T027. **Size:** M.

**Files:** `web/index.html`, `web/style.css`, `web/app.js`, `web/oled.js`.

**Spec:** Vanilla ES modules, no build step. Connect, render frames on a canvas
at 4× with the OLED look (blue-on-black, subtle pixel grid). View toggle:
Pixels / Text / Both / Raw. Text view renders `lines` in a `<pre>` — genuinely
selectable and copyable, with a Copy button. Frame scrubber: keep the last 200
frames, step back and forth with `[` and `]`.

Reconnect with backoff if the socket drops. Show connection state honestly —
a frozen UI that looks live is worse than one that says "disconnected".

**Done when:** booting `myfavcolor` shows the real "Starting in 2s..." screen in
the browser, and its text can be selected and copied.

---

### T029 — Web UI: arm and angle
**Deps:** T028. **Size:** S–M.

**Files:** `web/arm.js`.

**Spec:** 2D side view: body, hub, LEGO beam at `actual_angle`, big numeric
readout in degrees. Show commanded vs actual as a ghost when they differ — the
~2° servo quantization (T010) and the slew both become visible, which is worth
seeing. Draw the world arc beneath the arm with patch colours, and a marker at
the current angle.

---

### T030 — Web UI: keyboard and switches
**Deps:** T029. **Size:** S–M.

**Files:** `web/input.js`.

**Spec:** Exactly the bindings from the brief:

| Key | Action |
| --- | --- |
| `↑` / `↓` | UP / DOWN side buttons (keydown = press, keyup = release) |
| `Space` | SELECT |
| `←` / `→` | potentiometer, 40 raw units per press, held = repeat |
| `~` | power toggle |
| `!` | analog/I2C toggle |

Held keys mean held buttons — `waitforbutton()`'s press/release cycle must be
drivable by holding and releasing a key. Add clickable on-screen equivalents
with the same behaviour (mousedown/mouseup), and a "sticky" click mode for
accessibility. Show pressed state visually. `preventDefault` on arrows and
space so the page doesn't scroll.

Power off/on is a real reset: clear RAM, re-run `boot.py` then `main.py`, keep
the VFS.

---

### T031 — Web UI: accelerometer tilt widget
**Deps:** T029. **Size:** M.

**Files:** `web/tilt.js`.

**Spec:** Hand-rolled isometric board (no three.js, R4): draw the board as a
projected rectangular prism, drag to rotate (trackball mapping), emit
`set_tilt`. Show roll/pitch numerically and a gravity-vector arrow. Double-click
resets to level. ~150 lines of canvas 2D.

Validate against T012's round-trip: dragging to 30° roll must make device code's
`RP_calculate()` report ~30°.

---

### T032 — Web UI: world editor
**Deps:** T029. **Size:** M.

**Files:** `web/world.js`.

**Spec:** Edit the arc under the arm: drag patch boundaries, click a patch to
recolour it (native `<input type="color">`), add/remove patches, set ambient
lux. Save/load `.json` via download/upload — no server-side file writing.
Ship two presets: `three_patches` and `rainbow`.

---

### T033 — Web UI: clock, trace, headed tests
**Deps:** T028, T015. **Size:** M.

**Spec:** Speed control (`instant` / `0.1×` / `1×` / `5×` / `20×`), pause/step,
virtual-clock readout. Trace panel: filterable event timeline plus the device
`print()` stream. Fidelity-contract link in the header (`EMULATOR_DESIGN.md` §4)
so nobody mistakes this for hardware.

Then wire `smotor.launch(headed=True)`: start the server, open a browser, attach
to the same session, and default the clock to `1×` so a human can watch a test
run. This is the payoff for making the UI and the test client the same kind of
client — verify it end to end with T025's walkthrough.

---

# Phase 6 — Deployment

### T034 — `smotor` CLI
**Deps:** T014, S1. **Size:** M.

**Files:** `smotoremu/cli.py`, `tests/emulator/test_cli.py`.

**Spec:** `smotor flash` (wipe VFS, record firmware), `smotor deploy
[MANIFEST]` (default `EngAI_MANIFEST.txt`, enforcing `MAX_FILE_BYTES`),
`smotor run [entry]`, `smotor serve`, `smotor ls`, `smotor cat FILE`,
`smotor repl` if S1 succeeded.

Session state persists in `~/.smotor/default/` so `deploy` then `run` are
separate invocations against the same virtual device, mirroring a real board.

**Test first:** `deploy` copies exactly the manifest's files; an oversized file
fails with a clear message naming the file and the limit; `flash` empties the
VFS; `deploy` warns (not fails) on a manifest entry missing from disk, matching
`deploy.sh`'s behaviour.

---

### T035 — `deploy.sh` emulator target
**Deps:** T034. **Size:** S.

**Files:** `deploy.sh`.

**Spec:** `PORT=emu ./deploy.sh` routes `mpremote`/`esptool.py` calls to
`smotor` equivalents; unset or any other value keeps today's behaviour byte for
byte. Keep the change small and obvious — a `PORT` check at the top setting two
shell functions. Students should see one script, not two workflows.

**Done when:** `PORT=emu FLASH=1 ./deploy.sh` produces a virtual device whose
`smotor ls` matches `EngAI_MANIFEST.txt`, and the real-hardware path is
byte-identical to today (`git diff` shows only the additions).

---

# Phase 7 — Follow-on (not v1)

### T036 — Bench calibration pass
Collect every `# GUESS: needs bench data` marker (R5) into a measurement
worksheet: VEML6040 counts for known colours at 2–3 integration times, light
sensor volts at several lux, ADC endpoints and mid-scale, servo slew time,
battery raw at known charge states. Take the measurements on real hardware,
update the JSON calibration files, and confirm the T019 white-balance test still
passes with tighter tolerance.

### T037 — MicroPython Unix backend
Depends on S3. Implement `smotoremu/backends/micropython_unix/`, move
`test_import_safety.py` onto it, and add `smotor.requires_backend(...)`.

### T038 — Sensor plug-in authoring guide
`docs/adding-a-sensor.md`: walk through adding a new part end to end using
T020 as the worked example. The plug-in mechanism only pays off if someone other
than its author can use it.

---

## Suggested order

1. **S1, S3** (spikes, parallel with T001–T005).
2. **T001 → T002 → T003 → T004 → T005.** Foundations. T005 proves the screen
   story before anything depends on it.
3. **T006 → T007 → T009.** Stop and look: `icons.SSD1306_SMART` should render
   real text through the real driver. This is the "it's alive" moment.
4. **T008, T010, T011, T012** (independent, any order).
5. **T013 → T014 → T015.** Now device code actually runs.
6. **T016 → T017 → T018 → T019.** The favourite-colour activity becomes
   meaningful.
7. **T022 → T023 → T024 → T025.** T025 is the proof.
8. **T027 → T028 → T029 → T030.** A visible, operable device.
9. **T031, T032, T033, T020, T021, T026, T034, T035** as priorities dictate.

Checkpoint after T009 and again after T025 — those are the two points where the
design's assumptions get tested against reality, and where a course correction is
cheap.
