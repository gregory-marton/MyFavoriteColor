# Emulator Progress

Co-authored-by: GPT-5, Aug 2026

## 2026-08-04 -- Guided button, accelerometer, replay, and sensor capture pass

Files touched:

- `spikes/S7_guided/guided_logic.py`
- `spikes/S7_guided/guided_test_device.py`
- `spikes/S7_guided/read_guided_log.py`
- `smotoremu/trace.py`
- `web/index.html`
- `web/app.js`
- `tests/spikes/test_guided_logic.py`
- `tests/emulator/test_trace_parse.py`
- `tests/emulator/test_web_replay.py`

Red output:

```text
tests/spikes/test_guided_logic.py
ModuleNotFoundError: No module named 'spikes.S7_guided.guided_logic'

tests/spikes/test_guided_logic.py
ImportError: cannot import name 'accel_magnitude'

tests/emulator/test_trace_parse.py
AssertionError: assert 'orientation' in SUSTAIN_SAMPLE
IndexError: no START_SAMPLE parsed

tests/emulator/test_web_replay.py
ModuleNotFoundError: No module named 'playwright'
```

Green output:

```text
python3 -m pytest tests/spikes/test_guided_logic.py -v
8 passed in 0.01s

python3 -m pytest tests/emulator/test_trace_parse.py -v
7 passed in 0.01s

python3 -m pytest tests/ -v
115 passed, 1 skipped in 0.16s
```

Decisions:

- The guided button flow now asks for `SELECT`, `UP`, and `DOWN` explicitly.
- During each button prompt it watches all three pins. A wrong pin transition logs `BUTTON_MISMATCH expected=... observed=...` and advances, so a swapped UP/DOWN unit is diagnosed instead of hanging.
- The disconnected portion now includes `ACCEL_FLAT1`, `ACCEL_FIG8`, and `ACCEL_FLAT2` stages.
- The guided device log now emits `START_SAMPLE` immediately after hardware init so USB-connected voltage context is present before later disconnected sampling.
- Trace parsing now adds `battery_v` and roll/pitch `orientation` for `START_SAMPLE` and `SUSTAIN_SAMPLE`.
- Replay UI now shows DOWN and estimated orientation.
- The guided sequence now records first-pass `COLOR_WHITE`, `LIGHT_DARK`, and `LIGHT_BRIGHT` sample sets. This is capture infrastructure, not the full fleet QA analysis yet.
- `tests/emulator/test_web_replay.py` now skips cleanly when Playwright is not installed in the active interpreter.

## 2026-08-04 -- Parse and replay guided calibration summaries

Files touched:

- `smotoremu/trace.py`
- `tests/emulator/test_trace_parse.py`
- `tests/emulator/test_web_replay.py`
- `web/index.html`
- `web/app.js`

Red output:

```text
python3 -m pytest tests/emulator/test_trace_parse.py -v
3 failed, 7 passed in 0.03s

Failures:
- no ACCEL_SAMPLE / ACCEL_SUMMARY event parsed
- no COLOR_WHITE_SAMPLE / COLOR_WHITE_SUMMARY event parsed
- no LIGHT_SUMMARY event parsed
```

Green output:

```text
python3 -m pytest tests/emulator/test_trace_parse.py tests/emulator/test_web_replay.py -v
10 passed, 1 skipped in 0.03s

python3 -m pytest tests/ -v
118 passed, 1 skipped in 0.10s
```

Decisions:

- The trace parser now treats guided accelerometer, color white-balance, and light-summary lines as typed replay events.
- `ACCEL_SAMPLE` events include estimated roll/pitch using the same formula as the device ADXL345 driver.
- The replay UI shows the latest white-balance factors and light dark/bright means in the side panel.
- Playwright-backed UI assertions remain skipped when Playwright is not installed.

## 2026-08-04 -- T001 package metadata smoke

Files touched:

- `pyproject.toml`
- `smotoremu/__init__.py`
- `smotoremu/version.py`
- `tests/emulator/test_smoke.py`

Red output:

```text
python3 -m pytest tests/emulator/test_smoke.py -v
2 failed in 0.03s

Failures:
- `smotoremu.__version__` missing
- `pyproject.toml` missing
```

Green output:

```text
python3 -m pytest tests/emulator/test_smoke.py -v
2 passed in 0.01s

python3 -m pytest tests/ -v
120 passed, 1 skipped in 0.10s
```

Decisions:

- Added minimal setuptools metadata for `smotoremu`.
- Exposed `smotoremu.__version__` from `smotoremu/version.py`.
- Declared Python >=3.11, matching `EMULATOR_TASKS.md` T001.

## 2026-08-04 -- T002 virtual clock and event scheduler

Files touched:

- `smotoremu/clock.py`
- `tests/emulator/test_clock.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_clock.py -v
ModuleNotFoundError: No module named 'smotoremu.clock'
```

Green output:

```text
python3 -m pytest tests/emulator/test_clock.py -v
8 passed in 0.08s

python3 -m pytest tests/ -v
128 passed, 1 skipped in 0.18s
```

Decisions:

- Implemented deterministic `instant` virtual time first.
- Added `realtime` and `scaled` mode hooks, but kept tests focused on instant mode per T002.
- Event ordering at equal timestamps uses a monotonic sequence counter.
- Periodic events can cancel themselves from inside their callback.
- Repeated scheduling at one timestamp raises `ClockStuckError` instead of hanging.

## 2026-08-04 -- T006 board-backed Pin/ADC/PWM

Files touched:

- `smotoremu/machine_shim.py`
- `smotoremu/pinmap.py`
- `tests/emulator/test_machine_shim.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_machine_shim.py -v
ImportError: cannot import name 'Board' from 'smotoremu.machine_shim'
```

Green output:

```text
python3 -m pytest tests/emulator/test_machine_shim.py -v
12 passed in 0.01s

python3 -m pytest tests/ -v
133 passed, 1 skipped in 0.18s
```

Decisions:

- Added `smotoremu.pinmap` with named SmartMotor pin constants from `EMULATOR_TASKS.md` T006.
- Added a shared `Board` model behind `Pin`, `ADC`, and `PWM`.
- Buttons are active-low and can be driven through `board.press()` / `board.release()`.
- Pin 5 can be driven as digital output and read back through an injected port ADC stub, preserving the analog/I2C toggle probe shape.
- `ADC.read()` advances the virtual clock by 20 us per sample, marked as a bench-data guess.
- `PWM` changes notify board callbacks so the servo model can subscribe later.

## 2026-08-04 -- T007 I2C bus and SoftI2C delegation

Files touched:

- `smotoremu/i2c.py`
- `smotoremu/machine_shim.py`
- `smotoremu/trace.py`
- `tests/emulator/test_i2c.py`
- `tests/emulator/test_machine_shim.py`
- `tests/emulator/test_ssd1306_peripheral.py`
- `tests/emulator/test_trace_render.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_i2c.py -v
ModuleNotFoundError: No module named 'smotoremu.i2c'
```

Integration fallout:

```text
python3 -m pytest tests/ -q
7 failed, 131 passed, 1 skipped in 0.28s

Failures:
- real SSD1306 driver writes to 0x3C now raised OSError(19) when no display
  device was registered
```

Green output:

```text
python3 -m pytest tests/emulator/test_i2c.py tests/emulator/test_machine_shim.py -v
17 passed in 0.03s

python3 -m pytest tests/ -q
138 passed, 1 skipped in 0.22s
```

Decisions:

- Added an `I2CBus` with explicit device registration, sorted `scan()`, and
  `OSError(19)` for unregistered addresses.
- `SoftI2C` now delegates `scan`, `writeto`, `writevto`, `readfrom`,
  `writeto_mem`, and `readfrom_mem` through the board-owned bus.
- `writevto` combines vector payloads into one transaction, matching the real
  SSD1306 driver's display-buffer write path.
- I2C transactions advance the virtual clock using 9 bus bits per byte plus a
  small guessed start/stop overhead; this is marked for future bench data.
- Existing SSD1306 render tests now register a generic device at `0x3C`.
  A command-level SSD1306 peripheral remains T009; T007 only owns transport.

## 2026-08-04 -- T008 Timer, unique_id, and reset

Files touched:

- `smotoremu/machine_shim.py`
- `tests/emulator/test_timer.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_timer.py -v
ImportError: cannot import name 'DeviceReset' from 'smotoremu.machine_shim'
```

Test correction:

```text
tests/emulator/test_timer.py::test_timers_with_different_ids_are_independent
AssertionError: At index 5 diff: ('two', 50000) != ('one', 50000)
```

That assertion over-specified ordering for two callbacks scheduled at the same
virtual timestamp. The scheduler orders equal timestamps by insertion sequence,
so the test now asserts each timer's independent firing series instead.

Green output:

```text
python3 -m pytest tests/emulator/test_timer.py -v
6 passed in 0.01s

python3 -m pytest tests/ -q
144 passed, 1 skipped in 0.20s
```

Decisions:

- Added `Timer.ONE_SHOT`, `Timer.PERIODIC`, `init()`, and `deinit()` backed by
  the board's `EventScheduler`.
- Timer callbacks receive the timer instance, matching the MicroPython call
  shape used by `myfavcolor.displaybatt(p)`.
- `deinit()` is safe before `init()` and cancels a scheduled callback after
  `init()`.
- `Board(unique_id=...)` and `board.set_unique_id(...)` configure the active
  emulated machine identity; global `unique_id()` reads from `Pin._board`.
- `reset()` now raises `DeviceReset`, ready for the future session runner to
  catch.
- The shim docstring now explicitly states that timer callbacks are scheduler
  callbacks, not truly pre-emptive ISR execution.

## 2026-08-04 -- T005 glyph reverse map and aligned text extraction

Files touched:

- `smotoremu/screen_text.py`
- `tests/emulator/test_screen_text.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_screen_text.py -v
ModuleNotFoundError: No module named 'smotoremu.screen_text'
```

Green output:

```text
python3 -m pytest tests/emulator/test_screen_text.py -v
5 passed in 0.13s

python3 -m pytest tests/ -q
149 passed, 1 skipped in 0.30s
```

Decisions:

- Added `build_glyph_map()` from the byte-exact emulator font data.
- Duplicate non-blank glyph bitmaps raise immediately; the blank bitmap is
  treated explicitly as space.
- Added `extract_text()` with optional forced `origin=(x, y)`.
- Added automatic origin search across all 8x8 offsets, scored by non-space
  glyph matches so blank display area does not dominate alignment.
- Added `extract_lines()` for right-stripped, blank-row-dropped screen text.

## 2026-08-04 -- T009 SSD1306 command-level peripheral

Files touched:

- `smotoremu/peripherals/__init__.py`
- `smotoremu/peripherals/ssd1306.py`
- `smotoremu/device_env.py`
- `smotoremu/framebuf_shim.py`
- `tests/emulator/test_display.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_display.py -v
ImportError: cannot import name 'load_real_icons' from 'smotoremu.device_env'
```

Test correction:

```text
tests/emulator/test_display.py::test_invert_affects_pixels_but_not_gddram
assert 0 == 1
```

The test was reading rendered pixels before sending display-on (`0xAF`).
`pixels()` correctly returns black when the controller is off, so the test now
turns the display on before checking inversion.

Integration fallout:

```text
python3 -m pytest tests/ -q
4 failed, 151 passed, 1 skipped in 0.39s

Failures:
- `load_real_icons()` left the emulator `machine` module in `sys.modules`,
  causing later legacy runtime imports to use the wrong machine fake
```

Green output:

```text
python3 -m pytest tests/emulator/test_display.py -v
6 passed in 0.08s

python3 -m pytest tests/ -q
155 passed, 1 skipped in 0.37s
```

Decisions:

- Added `SSD1306Device` at the I2C-device protocol level.
- Implemented the command subset emitted by the repo's real `ssd1306.py`,
  including multi-byte command parameter state.
- Data writes now fill emulated GDDRAM in horizontal addressing mode and count
  full-frame writes.
- `pixels()` honors display on/off and inversion without mutating GDDRAM.
- `to_png()` emits dependency-free grayscale PNG bytes via `struct` and `zlib`.
- `text_lines()` uses the T005 reverse-map path, proving rendered text can be
  recovered from actual display bytes.
- Added `load_real_icons()` and restored temporary `machine`/`ssd1306`
  `sys.modules` overrides after loading to avoid contaminating legacy tests.
- Added minimal `MONO_HLSB` support to the framebuf shim so `icons.py` can load
  its icon framebuffers.

## 2026-08-04 -- T010 servo model

Files touched:

- `smotoremu/peripherals/servo.py`
- `smotoremu/device_env.py`
- `tests/emulator/test_servo.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_servo.py -v
ImportError: cannot import name 'load_real_servo' from 'smotoremu.device_env'
```

Green output:

```text
python3 -m pytest tests/emulator/test_servo.py -v
6 passed in 0.01s

python3 -m pytest tests/ -q
161 passed, 1 skipped in 0.38s
```

Decisions:

- Added `ServoModel` subscribed to board PWM changes on the configured pin.
- The model decodes PWM duty back to pulse width and angle, preserving the
  real 10-bit duty quantization from `servo.Servo.write_us()`.
- `duty=0` disables the signal and holds the current model position.
- `commanded_angle` jumps immediately; `actual_angle` slews at a guessed
  `400 deg/s` and settles through the virtual scheduler.
- `is_moving` updates from virtual time, so tests and future UI code can wait
  for the servo to settle without wall-clock sleeps.
- Added `load_real_servo()` with temporary `machine` shim installation so tests
  exercise the repo's real servo driver without contaminating later imports.
