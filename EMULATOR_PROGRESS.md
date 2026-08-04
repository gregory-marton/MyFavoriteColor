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

## 2026-08-04 -- T011 buttons, potentiometer, and battery

Files touched:

- `smotoremu/peripherals/inputs.py`
- `smotoremu/machine_shim.py`
- `smotoremu/device_env.py`
- `tests/emulator/test_inputs.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_inputs.py -v
ImportError: cannot import name 'load_real_sensors' from 'smotoremu.device_env'
```

Green output:

```text
python3 -m pytest tests/emulator/test_inputs.py -v
6 passed in 0.02s

python3 -m pytest tests/ -q
167 passed, 1 skipped in 0.38s
```

Decisions:

- Added active-low `Buttons` with `press`, `release`, `click`, and `held`.
- `click()` schedules release on the virtual scheduler; optional bounce support
  is present but off by default for deterministic tests.
- Added `Potentiometer` with raw and angle setters. `set_angle()` preserves the
  inverted pot-to-angle mapping used by `myfavcolor.update_motor_with_pot()`.
- Pot noise is per ADC read, clamped to 0-4095, and injectable via a seeded RNG
  for deterministic tests.
- Added board-level ADC noise callbacks so noisy peripherals do not have to
  mutate stored raw values.
- Added `Battery` state helpers using raw values unambiguously inside the real
  `sensors.readbattery()` bands, while keeping `set_raw()` for edge cases.
- Added `load_real_sensors()` so emulator tests can verify battery behavior
  through the repo's real `sensors.SENSORS` implementation.

## 2026-08-04 -- T012 ADXL345 accelerometer peripheral

Files touched:

- `smotoremu/peripherals/adxl345.py`
- `smotoremu/device_env.py`
- `tests/emulator/test_adxl.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_adxl.py -v
ImportError: cannot import name 'load_real_adxl345' from 'smotoremu.device_env'
```

Green output:

```text
python3 -m pytest tests/emulator/test_adxl.py -v
5 passed in 0.01s

python3 -m pytest tests/ -q
172 passed, 1 skipped in 0.38s
```

Decisions:

- Added `ADXL345Device` as an I2C device at the protocol level.
- The device accepts the real driver's power-control init writes to register
  `0x2D` and records that sequence for tests.
- Register `0x32` reads now return six bytes of little-endian signed x/y/z
  data at 256 LSB/g.
- Flat level defaults to `(0, 0, 256)`.
- `set_orientation(roll, pitch)` uses the inverse of the repo driver's
  `RP_calculate()` formula, proving the UI-facing roll/pitch contract.
- `set_gravity(x, y, z)` accepts direct g-units for world-model integration.
- Noise is bounded per axis and generated per read from an injectable RNG.
- Added `load_real_adxl345()` so emulator tests exercise the real driver.

## 2026-08-04 -- T013 session and device-code runner

Files touched:

- `smotoremu/session.py`
- `smotoremu/backends/__init__.py`
- `smotoremu/backends/cpython_shim/__init__.py`
- `smotoremu/backends/cpython_shim/machine.py`
- `smotoremu/backends/cpython_shim/framebuf.py`
- `smotoremu/backends/cpython_shim/micropython.py`
- `tests/emulator/test_session.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_session.py -v
ModuleNotFoundError: No module named 'smotoremu.session'
```

Green output:

```text
python3 -m pytest tests/emulator/test_session.py -v
6 passed in 0.03s

python3 -m pytest tests/ -q
178 passed, 1 skipped in 0.40s
```

Decisions:

- Added a `Session` object that owns a `Board`, virtual clock, I2C bus, seeded
  RNG, display, servo, buttons, potentiometer, battery, optional ADXL345, and
  placeholder port.
- `boot(entry)` runs device code in a daemon thread and calls `main()` when the
  imported entry module defines it.
- `run_until_idle()` joins the device thread with a timeout; exceptions are
  captured in `session.error` instead of raised on the controller thread.
- `SystemExit` is treated as a clean device-code exit and sets
  `session.exited`.
- Added CPython shim modules for `machine`, `framebuf`, and `micropython`, with
  active session state held in a `ContextVar`.
- Session boot purges an explicit list of device modules before import and
  restores prior `sys.modules`, `sys.path`, and time functions afterward.
- MicroPython-style `time.sleep*` and `ticks*` functions advance/read the
  session virtual clock while device code runs.
- This checkpoint documents but does not yet fully implement the future
  condition-variable handoff invariant for interactive controller/device
  concurrency.

## 2026-08-04 -- T014 virtual filesystem

Files touched:

- `smotoremu/vfs.py`
- `smotoremu/session.py`
- `smotoremu/backends/cpython_shim/os_shim.py`
- `tests/emulator/test_vfs.py`
- `tests/emulator/test_session.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_vfs.py -v
ModuleNotFoundError: No module named 'smotoremu.vfs'
```

Green output:

```text
python3 -m pytest tests/emulator/test_vfs.py -v
5 passed in 0.04s

python3 -m pytest tests/emulator/test_session.py -v
6 passed in 0.03s

python3 -m pytest tests/ -q
183 passed, 1 skipped in 0.44s
```

Decisions:

- Added `VFS` with `put`, `get`, `listdir`, `wipe`, and `load_manifest`.
- `VFS.MAX_FILE_BYTES` is read from `tests/test_filesize.py` so emulator flash
  limits stay aligned with the existing manifest-size gate.
- `put()` raises `FileTooLargeError` above the manifest threshold.
- `Session` now creates a temp-backed flash directory by default, or uses the
  caller-provided `vfs_dir`.
- During device execution the session changes cwd to the VFS root, prepends the
  VFS root to `sys.path`, and restores cwd/sys.path afterward.
- Device-thread `open`, `os.listdir`, and `os.remove` reject absolute host
  paths, matching the documented non-parallel chroot-style limitation.
- Real `files.py` now round-trips `savetofile()`/`readfile()` and
  `resetprefs()`/`import prefs` inside session flash.
- Added `os_shim.py` as the documented upgrade point if path-rewriting shims
  later replace the cwd-based approach.

## 2026-08-04 -- T015 trace recorder

Files touched:

- `smotoremu/trace.py`
- `smotoremu/session.py`
- `smotoremu/machine_shim.py`
- `smotoremu/i2c.py`
- `smotoremu/peripherals/inputs.py`
- `smotoremu/peripherals/servo.py`
- `tests/emulator/test_trace.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_trace.py -v
ImportError: cannot import name 'TraceRecorder' from 'smotoremu.trace'
```

Green output:

```text
python3 -m pytest tests/emulator/test_trace.py -v
5 passed in 0.03s

python3 -m pytest tests/emulator/test_i2c.py tests/emulator/test_machine_shim.py tests/emulator/test_inputs.py tests/emulator/test_servo.py tests/emulator/test_display.py tests/emulator/test_session.py -q
41 passed in 0.12s

python3 -m pytest tests/ -q
188 passed, 1 skipped in 0.44s
```

Decisions:

- Added `TraceRecorder` to `smotoremu.trace` without disturbing the existing
  guided-log parser functions.
- Trace events are dictionaries with `t_us`, `kind`, and `detail`.
- Ring-buffer retention drops oldest events after `max_events`.
- `to_jsonl()` and `from_jsonl()` round-trip trace metadata and events.
- Session traces start with a header event recording seed and configuration.
- Board-level pin, ADC, PWM, and timer events now record through the session
  trace when present.
- I2C bus operations record scan/read/write metadata after virtual timing is
  charged.
- Button, servo, display frame, and device `print()` output now emit `button`,
  `servo`, `frame`, and `log` trace events.

## 2026-08-04 -- T016 world model

Files touched:

- `smotoremu/world.py`
- `smotoremu/worlds/three_patches.json`
- `tests/emulator/test_world.py`
- `EMULATOR_DESIGN.md`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_world.py -v
ModuleNotFoundError: No module named 'smotoremu.world'
```

Green output:

```text
python3 -m pytest tests/emulator/test_world.py -v
5 passed in 0.02s

python3 -m pytest tests/ -q
193 passed, 1 skipped in 0.45s
```

Decisions:

- Added `World` and `Patch` for angle-indexed virtual paper under the arm.
- World files use JSON, matching T016's recommendation and avoiding PyYAML.
- Added shipped `smotoremu/worlds/three_patches.json` with red, white, and blue
  regions.
- `color_at()` returns patch color inside a patch and `default_color` in gaps.
- `patch_at()` returns the selected patch or `None`.
- `lux_at()` derives a simple luminance-scaled lux from color and ambient light.
- Adjacent patch boundaries can blur over `blur_deg`; default is the documented
  `3 deg` bench-data guess.
- Overlapping patch ranges raise at load.
- Updated `EMULATOR_DESIGN.md`'s world example from YAML to JSON so the design
  doc matches the implemented format.

## 2026-08-04 -- T017 sensor port and attachment probing

Files touched:

- `smotoremu/port.py`
- `smotoremu/session.py`
- `smotoremu/machine_shim.py`
- `tests/emulator/test_port.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_port.py -v
ModuleNotFoundError: No module named 'smotoremu.port'
```

Green output:

```text
python3 -m pytest tests/emulator/test_port.py -v
4 passed in 0.01s

python3 -m pytest tests/emulator/test_port.py tests/emulator/test_trace.py tests/emulator/test_session.py tests/emulator/test_inputs.py -q
21 passed in 0.05s

python3 -m pytest tests/ -q
197 passed, 1 skipped in 0.44s
```

Decisions:

- Added `Port` carrying pin 5 and the I2C bus.
- With no attached sensor, pin 5 ADC follows the driven digital level: low maps
  to `0`, high maps to `4095`, so the real `sensors.selectsensor()` reports no
  sensor attached.
- Analog sensors can provide `output_raw()` or `pin5_adc()`; the output ignores
  the driven level, so a mid-scale analog sensor is detected as attached by the
  real selection probe.
- I2C sensors are modeled as objects with `i2c_address` and `device`.
- `mode="analog"` unregisters attached I2C sensors from the bus, and
  `mode="i2c"` restores them.
- I2C-mode analog reads float near mid-scale. This is marked in code as
  `ASSUMPTION: awaiting confirmation` because the analog/I2C toggle wiring is
  still an open hardware question.
- `Session.port` now uses the real `Port` model instead of a placeholder.
- Port-backed pin 5 ADC reads now record `adc` trace events like other ADC
  reads.

## 2026-08-04 -- T018 sensor plug-in registry

Files touched:

- `smotoremu/sensors/__init__.py`
- `smotoremu/sensors/base.py`
- `smotoremu/sensors/veml6040.py`
- `smotoremu/sensors/data/veml6040.json`
- `tests/emulator/test_sensor_registry.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_sensor_registry.py -v
ModuleNotFoundError: No module named 'smotoremu.sensors'
```

Green output:

```text
python3 -m pytest tests/emulator/test_sensor_registry.py -v
6 passed in 0.01s

python3 -m pytest tests/ -q
203 passed, 1 skipped in 0.46s
```

Decisions:

- Added `SensorModel` base class with `attach()`, `ui_schema()`, and
  data-backed `calibration()`.
- Added `register(part_number)`, `get_sensor(part_number)`, and
  `list_sensors()`.
- Duplicate registrations raise a helpful `ValueError`.
- Missing sensors raise a `KeyError` naming the available part numbers.
- The `smotoremu.sensors` package auto-imports plug-in modules so decorators run
  on package import.
- Added a discoverable VEML6040 placeholder and JSON calibration data. T019
  owns the actual register-accurate VEML6040 model.

## 2026-08-04 -- T019 VEML6040 colour sensor plug-in

Files touched:

- `smotoremu/sensors/veml6040.py`
- `smotoremu/sensors/data/veml6040.json`
- `tests/emulator/test_veml6040.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_veml6040.py -v
6 failed

Failures:
- real `myfavcolor.VEML6040` construction did not see `0x10` in `scan()`
- later tests could not reach CONF, shutdown, conversion-gating, white-balance,
  or saturation behavior because the placeholder plug-in had no I2C device
```

Test correction:

```text
tests/emulator/test_veml6040.py::test_real_white_balance_calibration_matches_measured_factors
KeyboardInterrupt
```

The test stub held SELECT forever. The real calibration routine saves white
balance, then waits for SELECT release, so the stub now returns pressed once and
released thereafter.

Green output:

```text
python3 -m pytest tests/emulator/test_veml6040.py -v
6 passed in 0.03s

python3 -m pytest tests/emulator/test_sensor_registry.py tests/emulator/test_port.py tests/emulator/test_session.py tests/emulator/test_veml6040.py -q
22 passed in 0.05s

python3 -m pytest tests/ -q
209 passed, 1 skipped in 0.46s
```

Decisions:

- Replaced the T018 VEML6040 placeholder with a register-accurate I2C device
  model at `0x10`.
- The plug-in object is its own I2C device (`device = self`) so it attaches
  cleanly through the existing `Port` gate.
- Implemented `0x00` CONF as 16-bit little-endian, including shutdown and
  integration-time bits.
- Implemented RGBW data registers `0x08`-`0x0B` as 16-bit little-endian counts.
- Conversion timing is gated by virtual time: reads return the last latched
  counts until the selected integration time has elapsed.
- Shutdown freezes latched counts.
- Counts are emergent from world color, world luminance, integration time,
  per-channel sensitivity, dark counts, and optional shot noise.
- Calibration data now carries per-channel sensitivity. White-patch calibration
  through the real `Environment.calibrate_white_balance()` produces normalized
  factors within 15% of measured `WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)`.
- Extremely bright worlds saturate raw counts at `65535` and the real driver's
  `rgb` path clamps scaled values to `255`.

## 2026-08-04 -- T020 Grove slide potentiometer plug-in

Files touched:

- `smotoremu/sensors/grove_slide_pot.py`
- `smotoremu/sensors/data/grove_slide_pot.json`
- `tests/emulator/test_slide_pot.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_slide_pot.py -v
KeyError: "unknown sensor 'GROVE_SLIDE_POT'; available: VEML6040"
```

Green output:

```text
python3 -m pytest tests/emulator/test_slide_pot.py -v
5 passed in 0.02s

python3 -m pytest tests/emulator/test_slide_pot.py tests/emulator/test_sensor_registry.py tests/emulator/test_port.py -q
15 passed in 0.02s

python3 -m pytest tests/ -q
214 passed, 1 skipped in 0.47s
```

Decisions:

- Added a registered `GROVE_SLIDE_POT` analog sensor plug-in.
- `position` maps linearly from `0.0..1.0` to ADC raw `0..4095`.
- ADC non-linearity is data-backed through a piecewise-linear table; default
  data is identity and marked as a bench-data guess.
- Per-read Gaussian noise is supported with injectable RNG.
- `attach()` uses the existing `Port` analog path.
- The real `sensors.selectsensor()` probe reports attached at rail and
  mid-scale positions. The `position=0.0` truth table is explicit: both low and
  high reads stay near zero, so it does not satisfy the no-sensor
  `low < 200 and high > 4000` condition.
- `ui_schema()` exposes a slider field for future UI controls.

## 2026-08-04 -- T021 Grove light sensor plug-in

Files touched:

- `smotoremu/sensors/grove_light.py`
- `smotoremu/sensors/data/grove_light.json`
- `smotoremu/session.py`
- `tests/emulator/test_light_sensor.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_light_sensor.py -v
KeyError: "unknown sensor 'GROVE_LIGHT'; available: GROVE_SLIDE_POT, VEML6040"
```

Green output:

```text
python3 -m pytest tests/emulator/test_light_sensor.py -v
5 passed in 0.02s

python3 -m pytest tests/emulator/test_light_sensor.py tests/emulator/test_sensor_registry.py tests/emulator/test_port.py tests/emulator/test_session.py -q
21 passed in 0.05s

python3 -m pytest tests/ -q
219 passed, 1 skipped in 0.46s
```

Decisions:

- Added a registered `GROVE_LIGHT` analog sensor plug-in.
- Light response is data-backed by a lux-to-voltage calibration table.
- Interpolation is log-lux based and clamps at the table endpoints.
- Raw output maps voltage to 12-bit ADC units and saturates at 4095.
- Sensed lux combines `world.lux_at(angle)` with `world.ambient_lux`.
- If the active board exposes `servo_model`, the light sensor samples at
  `servo.actual_angle`; otherwise it falls back to angle 0.
- Per-read Gaussian noise is supported with injectable RNG.
- The real `sensors.readpoint()` path is now covered: repeated reads against a
  stable noisy world stay close after the median slice, and increasing world
  lux moves the light coordinate upward.
- `Session` stores its servo model on the board so world-coupled analog sensors
  can sample at the current arm angle.
