# Emulator Progress

Co-authored-by: GPT-5, Aug 2026
Co-authored-by: GPT-5.6-Sol-high, Aug 2026

## 2026-08-05 -- Standalone minimal mirror firmware

The physical mirror is now deliberately separated from every normal activity.
Deployment installs `mirror.py`, a no-op device `main.py`, and only the small
hardware drivers it needs. The regular activity cannot compete for the OLED,
servo, buttons, ADC, I2C bus, or serial stream.

Red output:

```text
ModuleNotFoundError: No module named 'mirror'
AttributeError: mirror.port_mode / mirror.short_number / mirror.I2CSensor
KeyError: status power, sensor_rgbw, and full sensor fields were not parsed
```

Green output:

```text
.venv/bin/python -m pytest tests/ -q
316 passed, 1 skipped in 30.52s
```

Decisions:

- `boot.py` runs only `mirror.run()`. Ctrl-C is caught as a clean return to the
  REPL, and deployed `main.py` is intentionally empty so the normal dispatcher
  cannot start afterward.
- The mirror loop sleeps 250 ms every iteration to yield to MicroPython and
  make reconnection practical.
- The OLED reports power/USB state, `mode i2c` or `mode alg`, sensor summary,
  pot and servo angle, active UP/DOWN/SLCT labels, and directional delta glyphs
  (`v`, `^`, `<`, `>`, `J`, `L`) for accelerometer changes.
- OLED numeric values use two significant digits. Serial telemetry and the
  desktop mirror retain full pot, angle, analog ADC, and VEML6040 RGBW values.
- The sensor-port mode is classified from the measured electrical spread; the
  high-spread/floating position is `i2c`, and the low-spread position is `alg`.
- Analog mode reports the GPIO 5 ADC reading. I2C mode performs a minimal
  VEML6040 read at address `0x10` and reports raw `R,G,B,W` words.

The remaining physical step is a brief USB disconnect/reconnect so the new
`boot.py`, `mirror.py`, and no-op `main.py` can be uploaded before the device
starts the mirror loop.

## 2026-08-04 -- Continuous multi-client physical mirror

Commit: `3a4c242` (`Keep physical mirror telemetry live`)

The physical mirror previously delivered a useful initial snapshot, but browser
clients competed to read the same serial stream and most controls never applied
incoming physical state to their widgets. A second client, including the
acceptance checker, could therefore make the browser appear frozen.

Red output:

```text
AttributeError: module 'smirror' has no attribute 'emit_inputs'
AssertionError: concurrent hardware serial reads overlapped
AssertionError: mirror state contained no physical pot/button states
TimeoutError: physical pot/button and orientation widgets did not update
```

Green output:

```text
.venv/bin/python -m pytest tests/test_smirror.py tests/emulator/test_adxl.py \
  tests/emulator/test_hardware_bridge.py tests/emulator/test_protocol.py \
  tests/emulator/test_web_inputs.py tests/emulator/test_web_tilt.py -q
53 passed in 5.86s
```

Decisions and verified behavior:

- Serialize access to the shared physical serial stream and retain the latest
  parsed state, so all connected browser/checker sessions receive the same
  ongoing mirror instead of dividing or corrupting telemetry records.
- Sample and emit the physical potentiometer and all three active-low buttons
  at 10 Hz from the existing activity loop.
- Apply physical pot/button values to the controls panel and physical roll/pitch
  values to the tilt widget on every state message.
- Keep servo angle observational: it reports calls to `Servo.write_angle`; the
  SmartMotor has no implemented mechanical arm-position feedback, so manually
  moving the arm cannot currently change that value.
- Redeployed `smirror.py` and `sensors.py` to the connected SmartMotor using the
  reconnect watcher, then restarted the host bridge on `/dev/cu.usbmodem1101`.
- An eight-second checker run alongside the browser received 26 changing
  orientation samples, proving that a second client no longer starves the UI.
- A subsequent ten-second full-control sample received 32 state samples:

```text
roll range: 120.3..147.9
pitch range: -37.0..67.6
pot range: 1339..4095
arm angle range: 58.0..58.0
button samples: 96
buttons seen pressed: <none>
PASS: live physical OLED and motion are both mirrored
```

The pot and accelerometer are confirmed continuously live. Button telemetry is
continuously present but still needs a run during deliberate physical presses.
The arm stayed at the device's commanded 58 degrees during this sample.

## 2026-08-04 -- Physical OLED, servo, and accelerometer mirror path

Files touched:

- `smirror.py`, `boot.py`, `EngAI_MANIFEST.txt`
- `adxl345.py`, `sensors.py`
- `smotoremu/cli.py`, `smotoremu/peripherals/ssd1306.py`
- `tests/test_smirror.py`
- `tests/emulator/test_adxl.py`, `tests/emulator/test_hardware_bridge.py`

Red output:

```text
ModuleNotFoundError: No module named 'smirror'
AttributeError: 'ADXL345' object has no attribute 'read'
KeyError: 'roll'
AssertionError: activity pot read emitted no @SMIRROR ACCEL line
TypeError: install() got an unexpected keyword argument 'display_module'
```

Green output:

```text
.venv/bin/python -m pytest tests/test_smirror.py tests/emulator/test_adxl.py \
  tests/emulator/test_hardware_bridge.py tests/emulator/test_e2e_mirror_telemetry.py \
  tests/emulator/test_recording_bridge.py -q
25 passed in 7.78s
```

Decisions:

- Physical firmware emits a line-oriented `@SMIRROR` protocol that cannot be
  mistaken for legacy `webconnect.py` JSON.
- `boot.py` installs observational hooks around the shared SSD1306 and servo
  drivers; hook failures never stop the activity being observed.
- The host converts the real 1024-byte MONO_VLSB framebuffer to PNG and extracts
  selectable text instead of manufacturing a placeholder hardware frame.
- Accelerometer reads are coherent six-byte burst reads. Existing activity pot
  reads sample the accelerometer, throttled to 10 Hz, so motion telemetry works
  in either deployed activity rather than only in web-connect mode.
- A live diagnostic against the pre-fix device returned three empty replies,
  proving the prior physical test was accepting protocol defaults rather than
  real device telemetry.
- The first ordinary `mpremote` upload could not enter raw REPL. A regression
  test showed the soft interrupt incorrectly appended Ctrl-D and rebooted the
  activity; commit `bd7fb33` leaves the device at REPL instead.
- `bin/deploy_mirror_after_reconnect` then caught a physical power-cycle and
  successfully uploaded `boot.py`, `smirror.py`, `adxl345.py`, and `sensors.py`.
- Final live acceptance while the connected unit was moving:

```text
real OLED frames: 1
orientation samples: 16
roll range: 124.0..177.2
pitch range: -12.8..9.7
PASS: live physical OLED and motion are both mirrored
```
Co-authored-by: Gemini 3.6 Flash, Aug 2026

## 2026-08-04 -- T035 `deploy.sh` emulator target

Files touched:

- `deploy.sh`
- `tests/emulator/test_deploy_script.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_deploy_script.py -v
1 failed in 8.86s
FAILED test_deploy_sh_with_port_emu
AssertionError: assert [] == ['adxl345.py', ...]
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_deploy_script.py -v
1 passed in 0.25s

.venv/bin/python -m pytest tests/ -q
282 passed in 27.50s
```

Decisions:

- Updated `deploy.sh` to check `PORT=emu` and route `mpremote` and `esptool.py` calls to `smotor` CLI commands (`flash`, file copy, `reset`).
- Kept non-emulator behavior byte-identical to existing workflow when `PORT` is unset or set to hardware ports.
- Supported `FLASH=1` environment variable alongside `FLASH` positional parameter.

## 2026-08-04 -- T034 `smotor` CLI

Files touched:

- `smotoremu/cli.py`
- `pyproject.toml`
- `tests/emulator/test_cli.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_cli.py -v
1 error during collection
ImportError: cannot import name 'cli' from 'smotoremu'
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_cli.py -v
2 passed in 0.04s

.venv/bin/python -m pytest tests/ -q
281 passed in 26.93s
```

Decisions:

- Implemented `smotoremu.cli` with `flash`, `deploy`, `ls`, `cat`, `run`, and `serve` commands.
- Configured persistent session state directory default at `~/.smotor/default/` (overridable with `--vfs-dir` or `SMOTOR_DIR`).
- Enforced manifest file size checks (`MAX_FILE_BYTES`) and missing file warnings matching `deploy.sh`.
- Registered `smotor = "smotoremu.cli:main"` console script entry point in `pyproject.toml`.

## 2026-08-04 -- T033 Web UI: clock, trace, headed tests

Files touched:

- `web/clock_trace.js`
- `web/index.html`
- `web/app.js`
- `smotoremu/testing.py`
- `tests/emulator/test_headed.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_headed.py -v
1 failed, 2 passed in 31.54s
FAILED test_clock_and_trace_ui_elements_exist
TimeoutError: Page.wait_for_selector: Timeout 30000ms exceeded waiting for locator("#clock-panel")
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_headed.py -v
3 passed in 1.45s

.venv/bin/python -m pytest tests/ -q
279 passed in 26.33s
```

Decisions:

- Created `web/clock_trace.js` module providing speed control dropdown (`instant`, `0.1×`, `1.0×`, `5.0×`, `20.0×`), pause/resume toggle, virtual clock readout, and filterable trace event timeline + `print()` log stream.
- Added `#clock-panel` and `#trace-panel` to `web/index.html` and added fidelity notice link in header pointing to `EMULATOR_DESIGN.md#4-fidelity-contract`.
- Updated `smotoremu.testing.launch()` to default `clock="scaled"` when `headed=True`.

## 2026-08-04 -- T032 Web UI: world editor

Files touched:

- `web/world.js`
- `web/index.html`
- `web/app.js`
- `tests/emulator/test_web_world.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_world.py -v
1 failed in 30.98s
FAILED test_world_editor_preset_and_emits_set_world
TimeoutError: Page.wait_for_selector: Timeout 30000ms exceeded waiting for locator("#world-editor-panel")
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_world.py -v
1 passed in 0.98s

.venv/bin/python -m pytest tests/ -q
276 passed in 25.83s
```

Decisions:

- Created `web/world.js` module providing patch editing, start/end angle controls, native `<input type="color">` pickers, patch creation/deletion, ambient lux configuration, and JSON file download/upload without server-side file writes.
- Added shipped presets for `three_patches` (red/white/blue) and `rainbow` (red/orange/yellow/green/blue/violet).
- Added `#world-editor-panel` to `web/index.html` and initialized world editor in `web/app.js` to emit `set_world` messages over WebSocket.

## 2026-08-04 -- T031 Web UI: accelerometer tilt widget

Files touched:

- `web/tilt.js`
- `web/index.html`
- `web/app.js`
- `tests/emulator/test_web_tilt.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_tilt.py -v
1 failed in 30.98s
FAILED test_tilt_widget_renders_and_emits_set_tilt
TimeoutError: Page.wait_for_selector: Timeout 30000ms exceeded waiting for locator("#tilt-panel")
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_tilt.py -v
1 passed in 0.89s

.venv/bin/python -m pytest tests/ -q
275 passed in 24.44s
```

Decisions:

- Created `web/tilt.js` featuring a hand-rolled isometric 2D board projection (no three.js dependency).
- Implemented trackball mouse drag to adjust roll and pitch, double-click to reset level, numeric readout, and 3D projected gravity vector arrow.
- Added `#tilt-panel` to `web/index.html` and initialized tilt widget in `web/app.js` to emit `set_tilt` messages over WebSocket.

## 2026-08-04 -- T030 Web UI: keyboard and switches

Files touched:

- `web/input.js`
- `web/index.html`
- `web/app.js`
- `tests/emulator/test_web_inputs.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_inputs.py -v
1 failed in 31.48s
FAILED test_keyboard_shortcuts_and_buttons
TimeoutError: Page.wait_for_selector: Timeout 30000ms exceeded waiting for locator("#controls-panel")
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_inputs.py -v
1 passed in 0.95s

.venv/bin/python -m pytest tests/ -q
274 passed in 23.96s
```

Decisions:

- Created `web/input.js` to manage keyboard shortcuts (`ArrowUp`/`ArrowDown` for UP/DOWN buttons, `Space` for SELECT, `ArrowLeft`/`ArrowRight` for potentiometer adjustments with repeat, `~` for power toggle, `!` for detach/attach).
- Added `preventDefault()` on arrow keys and space so browser scrolling does not interfere with control handling.
- Built interactive on-screen buttons (`#btn-up`, `#btn-down`, `#btn-select`), potentiometer slider, power toggle, and sticky accessibility click mode.
- Added `#controls-panel` to `web/index.html` and initialized inputs in `web/app.js`.
- Preserved scrubber selection position on incoming live frame updates so user scrubbing stays locked to the chosen frame.

## 2026-08-04 -- T029 Web UI: arm and angle

Files touched:

- `web/arm.js`
- `web/index.html`
- `web/app.js`
- `smotoremu/protocol.py`
- `smotoremu/server.py`
- `tests/emulator/test_web_arm.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_arm.py -v
1 failed, 1 error in 0.09s
FAILED test_server_session_state_message_includes_commanded_angle_and_world
TypeError: state_message() got an unexpected keyword argument 'commanded_angle'
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_arm.py -v
2 passed in 1.44s

.venv/bin/python -m pytest tests/ -q
273 passed in 23.35s
```

Decisions:

- Added `commanded_angle` and `world` optional fields to `protocol.state_message` and populated them in `ServerSession.state_message()`.
- Created `web/arm.js` module to render a 2D side view of the arm, pivot hub, LEGO beam, ghost position overlay when commanded angle differs from actual angle, world arc colored by patch data, position marker, and big numeric angle readout.
- Added `#arm-panel` to `web/index.html` and integrated `renderArm()` calls into `web/app.js` state message handling.

## 2026-08-04 -- T028 live WebSocket OLED UI

Files touched:

- `web/index.html`
- `web/style.css`
- `web/app.js`
- `web/oled.js`
- `tests/emulator/test_web_live.py`
- `tests/emulator/test_web_replay.py` (deleted)
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_live.py -v
5 passed, 1 failed
FAILED test_text_view_is_selectable_and_copy_button_uses_clipboard
NotAllowedError: Read permission denied (Playwright clipboard permission)
```

Green output:

```text
.venv/bin/python -m pytest tests/emulator/test_web_live.py -v
6 passed in 0.96s

.venv/bin/python -m pytest tests/ -q
271 passed in 22.27s
```

Decisions:

- Replaced the old trace-only replay page with a vanilla ES-module live viewer (`web/index.html`, `web/app.js`, `web/oled.js`, `web/style.css`).
- Rendered PNG OLED frames on a canvas at 4× scaling with pixel grid aesthetics.
- Added Pixels/Text/Both/Raw view modes.
- Added frame history buffer (up to 200 frames) with scrubber slider and `[` / `]` keyboard navigation.
- Added selectable text view with a Copy button, granted `clipboard-read`/`clipboard-write` Playwright permissions in tests, and locked scrubber to frame 0 during copy assertion to ensure deterministic tests under live socket updates.
- Added status indicators for reconnecting, connected, and disconnected states.
- Fixed websocket test fixture teardown to await `server.wait_closed()`, eliminating unawaited coroutine warnings.

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

## 2026-08-04 -- T022 `smotor` facade and pytest fixtures

Files touched:

- `smotor.py`
- `smotoremu/testing.py`
- `smotoremu/__init__.py`
- `pyproject.toml`
- `tests/conftest.py`
- `tests/emulator/test_facade.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_facade.py -v
ModuleNotFoundError: No module named 'smotor'
```

Test integration correction:

```text
fixture 'sm' not found
fixture 'sm_color' not found
fixture 'sm_analog' not found
```

The package entry point covers installed use, but the source-tree test run does
not install the package first. `tests/conftest.py` now loads
`smotoremu.testing` as a local pytest plugin for repo tests.

Green output:

```text
python3 -m pytest tests/emulator/test_facade.py -v
9 passed in 0.08s

python3 -m pytest tests/emulator/test_smoke.py tests/emulator/test_facade.py tests/emulator/test_session.py -q
17 passed in 0.10s

python3 -m pytest tests/ -q
228 passed, 1 skipped in 0.52s
```

Decisions:

- Added top-level `smotor.launch(...)` facade.
- Added `smotoremu.testing.launch()` returning a thin `SmartMotor` wrapper over
  `Session`.
- `launch()` supports `sensor`, `world`, `clock`, `seed`, and `headed`
  arguments.
- Relative world paths such as `worlds/three_patches.json` resolve against the
  `smotoremu` package.
- Sensor names go through the plug-in registry, so unknown sensors produce the
  existing helpful available-parts error.
- Convenience methods expose `press`, `release`, `click`, `pot`, `arm.angle`,
  `screen.lines()`, `screen.png()`, `tilt`, `battery`, `world`, and `trace`.
- `close()` is idempotent.
- Added pytest fixtures `sm`, `sm_color`, and `sm_analog`.
- Updated packaging metadata to include `smotoremu*`, `smcheck*`, top-level
  `smotor`, and the `pytest11` plugin entry point.

## 2026-08-04 -- T023 auto-waiting expectations

Files touched:

- `smotoremu/expect.py`
- `smotor.py`
- `smotoremu/__init__.py`
- `tests/emulator/test_expect.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_expect.py -v
ModuleNotFoundError: No module named 'smotoremu.expect'
```

Green output:

```text
python3 -m pytest tests/emulator/test_expect.py -v
7 passed in 0.34s

python3 -m pytest tests/emulator/test_expect.py tests/emulator/test_facade.py tests/emulator/test_session.py tests/emulator/test_display.py -q
28 passed in 0.48s

python3 -m pytest tests/ -q
235 passed, 1 skipped in 0.83s
```

Decisions:

- Added `wait_for(predicate, session=..., timeout_ms=..., poll_ms=...)`.
- Added Playwright-shaped `expect(target)` with `to_be`, `to_be_close`,
  `to_contain`, `to_have_text`, and `not_`.
- Waiting advances virtual time by polling intervals and never uses wall-clock
  sleeps.
- Already-true predicates return without advancing virtual time.
- Timeouts occur at the exact requested virtual timeout.
- Failure messages include expected condition, actual value, elapsed virtual
  time, and the last 8 screen lines.
- Expectations fail fast with `session.error` instead of spinning when the
  device thread has crashed.
- `expect(lambda: sm.arm.angle)` can infer the session from a facade object in
  the lambda closure; facade objects such as `sm.screen` expose `session`
  directly.
- Exported `expect` and `wait_for` from both `smotor` and `smotoremu`.

## 2026-08-04 -- T024 screen locators and snapshots

Files touched:

- `smotoremu/screen.py`
- `smotoremu/expect.py`
- `smotoremu/peripherals/ssd1306.py`
- `smotoremu/testing.py`
- `tests/emulator/test_screen_api.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_screen_api.py -v
AttributeError: 'ScreenFacade' object has no attribute 'expect_text'
AttributeError: 'ScreenFacade' object has no attribute 'expect_lines'
AttributeError: 'ScreenFacade' object has no attribute 'assert_snapshot'
AttributeError: 'ScreenFacade' object has no attribute 'text'
```

Green output:

```text
python3 -m pytest tests/emulator/test_screen_api.py -v
5 passed in 3.85s

python3 -m pytest tests/emulator/test_screen_api.py tests/emulator/test_expect.py tests/emulator/test_facade.py tests/emulator/test_display.py -q
27 passed in 4.89s

python3 -m pytest tests/ -q
240 passed, 1 skipped in 5.18s
```

Decisions:

- Replaced the minimal `ScreenFacade` with `smotoremu.screen.Screen`.
- Added `sm.screen.lines()`, `text()`, `contains()`, `expect_text()`,
  `expect_lines()`, `png()`, `frames()`, and `assert_snapshot()`.
- Screen expectations reuse the virtual-time `wait_for()` helper, so tests do
  not sleep on wall-clock time.
- `expect_lines()` reports a readable line diff on mismatch.
- `assert_snapshot(name)` stores text snapshots under
  `tests/emulator/__snapshots__/`, creates missing snapshots loudly, compares
  existing snapshots, and updates when `SMOTOR_UPDATE_SNAPSHOTS=1`.
- The SSD1306 model now records text extracted from each full-frame write, so
  tests can inspect screen-frame history.
- `wait_for()` now accepts a callable `message`, allowing timeout details to
  reflect the final observed screen state.

## 2026-08-04 -- T025 emulator-backed favorite-color flow

Files touched:

- `tests/emulator/test_myfavcolor_flow.py`
- `tests/test_flow.py`
- `smotoremu/session.py`
- `smotoremu/clock.py`
- `smotoremu/expect.py`
- `smotoremu/screen.py`
- `smotoremu/screen_text.py`
- `smotoremu/peripherals/ssd1306.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/emulator/test_myfavcolor_flow.py tests/test_flow.py -v
FAILED tests/emulator/test_myfavcolor_flow.py::test_favorite_color_walkthrough
FAILED tests/emulator/test_myfavcolor_flow.py::test_main_without_color_sensor_dispatches_to_standalone_not_myfavcolor
ERROR tests/test_flow.py::test_favorite_color_walkthrough - ValueError: device code may not open absolute host paths
```

Intermediate failures found real emulator gaps:

```text
TimeoutError: expected screen to contain 'Starting in 2s'
display frame_count=0; bus devices=[16, 60, 83]; i2c counts={83: 6, None: 2, 16: 40211}

KeyboardInterrupt
smotoremu/screen_text.py:123

AssertionError: main dispatched to myfavcolor without a color sensor
```

Green output:

```text
python3 -m pytest tests/emulator/test_myfavcolor_flow.py -v
2 passed in 0.59s

python3 -m pytest tests/emulator/test_myfavcolor_flow.py tests/test_flow.py tests/emulator/test_screen_api.py tests/emulator/test_expect.py tests/emulator/test_session.py tests/emulator/test_facade.py -q
29 passed in 4.13s

python3 -m pytest tests/ -q
241 passed, 1 skipped in 4.69s
```

Decisions:

- Replaced the old mock-based `tests/test_flow.py` coverage with the real
  emulator walkthrough in `tests/emulator/test_myfavcolor_flow.py`.
- Kept `tests/test_flow.py` as a non-collecting compatibility note so the old
  shallow MagicMock test does not run.
- The walkthrough boots the real `main` dispatch, drives the VEML6040 color
  sensor world, white balance, favorite color capture, all seven state
  calibrations, and starts training until `E=0` appears.
- The negative path boots with no color sensor and asserts the real import
  trace reaches `standalone` and not `myfavcolor`.
- Session import ordering now keeps injected test modules ahead of the repo but
  moves the repo's real device modules ahead of `tests/fakes`, preventing the
  old fake `ssd1306` from bypassing display I2C writes.
- Added a device import trace to `Session` for dispatch assertions without
  replacing activity modules.
- Live-device expectations yield to the device thread instead of racing virtual
  time ahead from the controller.
- `Session.stop()` is now cooperative through both MicroPython sleep shims and
  I2C-driven virtual sleeps, preventing stuck interactive tests from leaving
  global shims installed.
- Screen expectations use direct rendered-glyph search over current and stored
  frame buffers, with permissive foreground matching so text embedded near
  graphics or wrapped lines can still be located quickly.

## 2026-08-04 -- T026 migrate remaining tests and delete fakes

Files touched:

- `tests/test_import_safety.py`
- `tests/test_dispatch.py`
- `tests/test_distance_math.py`
- `tests/test_qlearning.py`
- `tests/conftest.py`
- `tests/fakes/` (deleted)
- `README.md`
- `smotoremu/backends/cpython_shim/ubinascii.py`
- `smotoremu/backends/cpython_shim/urandom.py`
- `smotoremu/backends/cpython_shim/uselect.py`
- `smotoremu/device_env.py`
- `smotoremu/session.py`
- `smotoremu/framebuf_shim.py`
- `smotoremu/machine_shim.py`
- `tests/emulator/test_framebuf.py`
- `tests/emulator/test_machine_shim.py`
- `tests/emulator/test_ssd1306_peripheral.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
python3 -m pytest tests/test_import_safety.py tests/test_dispatch.py tests/test_distance_math.py tests/test_qlearning.py -v
ERROR tests/test_distance_math.py
ERROR tests/test_qlearning.py
ModuleNotFoundError: No module named 'machine'
```

Intermediate failure found a real shim gap:

```text
python3 -m pytest tests/emulator/test_framebuf.py tests/test_import_safety.py tests/test_dispatch.py tests/test_distance_math.py tests/test_qlearning.py -v
FAILED tests/test_import_safety.py::test_standalone_main_can_run_bounded
AttributeError("'SSD1306_SMART' object has no attribute 'line'")
```

Green output:

```text
python3 -m pytest tests/emulator/test_framebuf.py tests/test_import_safety.py tests/test_dispatch.py tests/test_distance_math.py tests/test_qlearning.py -v
18 passed in 3.72s

test ! -e tests/fakes

python3 -m pytest tests/ -q
242 passed, 1 skipped in 21.14s
```

Decisions:

- Deleted the tracked `tests/fakes/` modules and removed the generated
  `tests/fakes/__pycache__` directory so the path is absent on disk.
- Stripped `tests/conftest.py` back to the repo-root path insert; it no longer
  patches global time or resets fake machine state.
- Added maintained emulator shims for `ubinascii`, `urandom`, and `uselect`.
- Extended `smotoremu.device_env` so direct real-device module loads get the
  same MicroPython compatibility shims.
- Moved import-safety and bounded runtime smoke tests onto `Session`, using
  injected entry modules instead of host-side fake imports.
- Moved dispatch tests onto `Session` while keeping the same boot-selection and
  startup-chord assertions.
- Loaded `myfavcolor.py` through `device_env` in the pure distance and
  q-learning tests so those tests no longer depend on deleted fake modules.
- Added `FrameBuffer.line()` and a regression test because the emulator-backed
  bounded standalone run now exercises real `icons.SSD1306_SMART` drawing.
- Updated README to describe `smotoremu` instead of the deleted fake module
  directory and narrowed the hardware-only list: OLED layout and emulated color
  readings are covered before hardware, while physical button feel, servo load
  behavior, upload reliability, and real classroom lighting variation still
  require the ESP32.

## 2026-08-04 -- T027 WebSocket server and protocol

Files touched:

- `smotoremu/protocol.py`
- `smotoremu/server.py`
- `tests/emulator/test_protocol.py`
- `pyproject.toml`
- `tests/conftest.py`
- `EMULATOR_PROGRESS.md`

Red output:

```text
.venv/bin/python -m pytest tests/emulator/test_protocol.py -v
ImportError: cannot import name 'protocol' from 'smotoremu'

.venv/bin/python -m pytest tests/emulator/test_protocol.py -v
ModuleNotFoundError: No module named 'smotoremu.server'
```

Intermediate failures:

```text
.venv/bin/python -m pytest tests/emulator/test_protocol.py -v
FAILED test_frame_and_state_updates_coalesce_to_latest_at_30hz

.venv/bin/python -m pytest tests/emulator/test_protocol.py::test_websocket_round_trip_with_real_socket -v
PermissionError: [Errno 1] error while attempting to bind on address ('127.0.0.1', 0): operation not permitted
```

Green output:

```text
.venv/bin/python -m pip install -e . --no-build-isolation
Successfully installed smotoremu-0.1.0

.venv/bin/python -m pytest tests/emulator/test_protocol.py -v
23 passed in 0.08s

.venv/bin/python -m pytest tests/emulator/test_protocol.py::test_websocket_round_trip_with_real_socket -v
1 passed in 0.07s

.venv/bin/python -m pytest tests/ -q
276 passed in 23.95s
```

Decisions:

- Added `websockets>=12` as the T027 runtime dependency and verified the
  package installs editable into the repo-local `.venv`.
- Removed the now-redundant `pytest_plugins = ["smotoremu.testing"]` from
  `tests/conftest.py`; installed test runs load the plug-in through the
  package entry point, avoiding duplicate registration.
- Added `smotoremu.protocol` with versioned JSON encode/decode helpers,
  validation for all client command types, versioned server messages, error
  replies for malformed/unknown input, and a 30 Hz frame/state coalescer.
- Added `smotoremu.server.ServerSession` as the testable one-session command
  application layer for press/release, pot, tilt, world, clock, attach/detach,
  boot/reset, and power commands.
- Added static `web/` file response helpers and a `websockets` 17-compatible
  `process_request` adapter for serving `/` and `/app.js` while leaving `/ws`
  for WebSocket upgrade.
- Added a thin real-socket WebSocket round-trip test. It skips when sandbox
  socket bind is denied, and passes when run with local socket permission.
