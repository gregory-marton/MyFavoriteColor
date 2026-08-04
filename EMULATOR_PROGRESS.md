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
