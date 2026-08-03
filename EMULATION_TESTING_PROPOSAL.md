# Proposal: Device-Free Emulation and Testing

## Purpose

This repository now deploys both activity paths at the same time. That is the real operating model:

- `main.py` selects web-connect mode from `prefs.mode`.
- In standalone mode, `main.py` probes I2C and selects the favorite-color activity when a color sensor is present.
- Otherwise, it selects the analog / accelerometer activity.
- `deploy.sh` and `EngAI_MANIFEST.txt` copy both activities and their shared drivers to the ESP32.

The desktop emulator and tests should match that reality. The goal is not to replace hardware testing. The goal is to catch logic, dispatch, state-machine, protocol, and regression failures before an ESP32 is connected.

## Current Repository Shape

The repository contains three runtime entry paths:

- `main.py`: boot dispatcher. It reads persisted mode, handles the startup mode toggle, probes hardware, and selects the activity.
- `myfavcolor.py`: favorite-color reinforcement-learning activity using the color sensor, servo, OLED display, buttons, preferences, and timing.
- `standalone.py`: analog / accelerometer activity using the potentiometer, accelerometer, servo, OLED display, buttons, saved training data, and k-nearest-neighbor style behavior.
- `webconnect.py`: serial / JSON activity for web-connected explore, train, play, and load workflows.

Supporting modules include:

- Hardware and driver code: `sensors.py`, `servo.py`, `adxl345.py`, `ssd1306.py`, `icons.py`, `swv.py`.
- Device persistence and configuration: `files.py`, `prefs.py`, `data.py`, `trainData.txt`.
- Deployment metadata: `deploy.sh`, `EngAI_MANIFEST.txt`, firmware binary.
- Desktop tests and fakes: `tests/`, `tests/fakes/`.

The current tests already contain useful seeds for desktop execution:

- `tests/fakes/machine.py` provides fake pins, ADC, PWM, timers, I2C devices, and I2C memory.
- `tests/fakes/icons.py` records display operations.
- `tests/conftest.py` inserts fakes before real MicroPython modules and patches basic MicroPython time functions.

The main gap is that the tests and README still describe an older single-activity model. They do not yet model the deployed system: both activities copied together, selected at boot by mode and detected devices.

## Problems To Solve

1. Imports are not consistently side-effect free.

   A desktop test should be able to import a module without starting an infinite loop, constructing real hardware, or entering calibration. Today, the runtime modules mix import, construction, and execution. That makes tests brittle and makes emulation harder than necessary.

2. The dispatcher is not directly testable.

   `main.py` currently performs its work at module import time. The important behavior, choosing web-connect, favorite-color, or analog activity, should be testable as ordinary logic with fake preferences and fake I2C devices.

3. The emulator is module-level rather than scenario-level.

   The fake `machine` module is useful, but tests still need a higher-level way to describe a user session: connected devices, button presses, potentiometer movement, color readings, acceleration readings, serial messages, and expected display or servo outputs.

4. Long-running activity loops do not have a desktop safety boundary.

   Hardware loops are natural on the ESP32. On a desktop, every emulated run needs a maximum tick count, maximum simulated time, and clear failure when scripted input is exhausted.

5. Tests are drifting from the deployed behavior.

   The README mentions test files and source-of-truth assumptions that no longer match the repo. Tests that exercise only one activity path cannot catch regressions in simultaneous deployment, boot selection, shared fake state, or shared driver contracts.

## Proposed Architecture

### 1. Split Import, Construction, and Execution

Each runtime path should expose a callable startup function and avoid running the full activity during import.

Target shape:

- `main.py` exposes a dispatch function and a `main()` entrypoint.
- `myfavcolor.py` exposes `main()` but does not construct hardware until `main()` or an explicit factory is called.
- `standalone.py` exposes `main()` and does not enter the activity loop during import.
- `webconnect.py` exposes `main()` or an explicit protocol loop entrypoint.

This preserves MicroPython behavior while making desktop tests reliable. On-device execution can still call `main()` from the boot path.

### 2. Define a Small Hardware Boundary

Introduce a narrow interface, even if it is implemented with simple objects rather than a large framework.

The boundary should cover:

- Device discovery: I2C scan and device identity.
- Inputs: button state, potentiometer ADC, color readings, acceleration readings, serial input.
- Outputs: servo angle, display text/draw calls, serial output, saved files/preferences.
- Time: sleep, ticks, elapsed-time math, timers, and timer callbacks.
- Randomness: seedable random numbers for deterministic learning tests.

The important rule is that activity logic should receive these capabilities from construction or startup, not discover all of them globally at import time.

### 3. Add Real and Simulated Hardware Implementations

The real implementation wraps existing MicroPython modules:

- `machine.Pin`
- `machine.ADC`
- `machine.PWM`
- `machine.Timer`
- `machine.SoftI2C`
- OLED and sensor drivers
- real time functions
- real file persistence

The simulated implementation uses deterministic desktop state:

- Scripted button events.
- Scripted ADC values.
- Scripted color readings.
- Scripted acceleration readings.
- Virtual I2C device lists.
- Virtual I2C registers for driver-level tests.
- Virtual clock and timers.
- Captured display, servo, serial, and file outputs.

This can be built incrementally on top of the existing `tests/fakes` modules. A full rewrite is not required.

### 4. Make Boot Selection a Pure Decision

The boot selection behavior should be expressible as a pure decision:

```python
choose_activity(mode, i2c_devices) -> "webconnect" | "favorite_color" | "analog"
```

Expected behavior:

- `mode == 1` selects web-connect mode.
- `mode == 0` and I2C scan includes `0x10` selects favorite-color mode.
- `mode == 0` and I2C scan does not include `0x10` selects analog / accelerometer mode.

The actual boot path can still perform hardware setup, display messages, and imports. The decision itself should have direct unit coverage.

### 5. Convert Interactive Flows To Tickable State Machines

The activity loops should be testable one step at a time.

Target pattern:

```python
activity = FavoriteColorActivity(hardware, config)
activity.start()
while not activity.done:
    activity.tick()
```

The implementation can remain compact for MicroPython, but the concept matters:

- One tick reads inputs.
- One tick updates state.
- One tick records outputs.
- Tests advance fake time and inspect results.

This makes calibration, confirmation, training, and play behavior testable without background threads or real sleeping.

## Emulator Scenario Format

Add a scenario object or plain dictionary for desktop tests. It should describe the whole emulated session.

Suggested fields:

```python
scenario = {
    "mode": 0,
    "i2c_devices": [0x10, 0x3c],
    "buttons": [
        {"at_ms": 100, "select": 0},
        {"at_ms": 180, "select": 1},
    ],
    "adc": [
        {"at_ms": 0, "value": 1200},
        {"at_ms": 500, "value": 2500},
    ],
    "colors": [
        {"at_ms": 0, "rgb": (113, 113, 113)},
        {"at_ms": 700, "rgb": (22, 21, 41)},
    ],
    "acceleration": [
        {"at_ms": 0, "xyz": (0.0, 0.0, 1.0)},
    ],
    "serial_in": [],
    "random_seed": 1,
    "max_ticks": 1000,
    "max_ms": 30000,
}
```

The emulator should record:

- Display messages and draw calls.
- Servo angle commands.
- I2C reads and writes.
- Serial output.
- File writes.
- Preference writes.
- Timer registrations and firings.
- Exceptions or timeout reason.

## Emulator Failure Modes

Desktop emulation should fail loudly when the scenario is incomplete or the activity does not make progress.

Recommended failures:

- `ScenarioExhausted`: the activity waited for input that the scenario never provides.
- `SimulationTimeout`: the activity exceeded `max_ticks` or `max_ms`.
- `InvalidHardwareUse`: code requested an impossible timer, pin, PWM duty, servo angle, or I2C address.
- `UnexpectedOutput`: test assertions detected an unexpected display message, serial message, saved file, or servo command.

These failures are better than a hanging test process. A test that hangs is not a useful signal.

## Testing Plan

### Unit Tests

Keep small logic tests for deterministic functions:

- Color distance functions.
- Reward normalization.
- Q-learning update math.
- Servo angle mapping.
- Potentiometer-to-position mapping.
- kNN nearest-neighbor selection.
- Web-connect JSON parsing and command routing.
- File and preference serialization.

These tests should not instantiate display, I2C, timers, or infinite loops.

### Hardware Contract Tests

Exercise the fake hardware against the assumptions the application makes:

- `Pin.value()` supports queued input and output inspection.
- `ADC.read()` can return scripted values.
- `PWM` records duty/frequency/deinit.
- `Timer` supports init/deinit and deterministic callback firing.
- `SoftI2C.scan()` returns configured devices.
- `SoftI2C.readfrom_mem()` and `writeto_mem()` support sensor-driver tests.

This protects the emulator itself from silently diverging from MicroPython behavior.

### Dispatcher Tests

Cover deployed boot selection:

- `prefs.mode == 1` selects web-connect without probing activity hardware unnecessarily.
- `prefs.mode == 0` plus color sensor address `0x10` selects favorite-color.
- `prefs.mode == 0` without color sensor selects analog.
- Startup button chord toggles persisted mode and shows the expected mode message.
- Missing OLED or missing sensor fails with a clear diagnostic rather than an import-time hang.

These tests directly address the simultaneous-deployment drift.

### Favorite-Color Activity Scenarios

Add scenario tests for:

- White-balance calibration completes using scripted color readings.
- Favorite color capture responds to SELECT.
- State calibration records exactly `NUM_STATES` states.
- Confirmation screen starts training on SELECT.
- Confirmation screen recalibrates on UP.
- Training advances through fixed-length episodes.
- Servo commands stay within allowed bounds.
- Rewards prefer the calibrated state closest to the favorite color.
- Scenario timeout catches a missing SELECT press.

### Analog / Accelerometer Activity Scenarios

Add scenario tests for:

- Importing `standalone.py` does not start the loop.
- `standalone.main()` can be run under a bounded emulator.
- Training data can be loaded from `trainData.txt` or simulated file storage.
- Button and potentiometer input drive the expected UI states.
- Acceleration readings classify to the expected motor position.
- Servo commands stay within allowed bounds.
- Missing or malformed training data produces a controlled failure.

### Web-Connect Scenarios

Add protocol-level tests for:

- Explore command returns current sensor state.
- Train command records labeled examples.
- Play command emits predicted or selected action.
- Onload command restores expected state.
- Invalid JSON returns a controlled error.
- Unknown command returns a controlled error.
- Serial input exhaustion fails with `ScenarioExhausted`, not a hang.

### Deployment and Size Tests

Keep or extend the file-size guard, but align it with the deployed manifest:

- Verify every file in `EngAI_MANIFEST.txt` exists.
- Verify both activities are included.
- Verify per-file size stays below the known upload threshold where relevant.
- Verify deployment does not depend on README-only assumptions.

### Smoke Test Matrix

The minimum useful desktop smoke suite should cover:

| Test | Mode | I2C Devices | Expected Path |
| --- | --- | --- | --- |
| Web mode | `1` | any | `webconnect` |
| Favorite-color mode | `0` | includes `0x10` | `myfavcolor` |
| Analog mode | `0` | excludes `0x10` | `standalone` |
| Startup toggle | chord pressed | any | persisted mode flips |

## Documentation Plan

Update the README after the emulator work begins. The README should stop claiming that `standalone.py` is the only source of truth.

Recommended README sections:

- Current deployed architecture.
- How boot selection works.
- How to run desktop tests.
- What the emulator covers.
- What still requires ESP32 hardware.
- How to add a new scenario.
- How to deploy both activities.
- Known upload-size and reset behavior.

The old historical notes can stay if useful, but they should be labeled as history rather than current architecture.

## Delivery Sequence

1. Create explicit startup boundaries.

   Add or adjust `main()` entrypoints so imports are safe. Do not change observable device behavior.

2. Extract boot selection logic.

   Make activity selection testable without importing the selected activity module.

3. Stabilize fake hardware.

   Add reset hooks, deterministic timers, and clear failure behavior for exhausted scripts.

4. Add dispatcher tests.

   Lock in the deployed simultaneous-activity behavior first.

5. Add favorite-color scenario tests.

   Cover calibration, confirmation, reward, and bounded training.

6. Add analog scenario tests.

   Cover import safety, training data, classification, and servo output.

7. Add web-connect protocol tests.

   Cover valid commands, invalid commands, and bounded serial input.

8. Rewrite README testing sections.

   Make the documentation match the actual deployment and emulator coverage.

## Acceptance Criteria

The work is complete when:

- `python3 -m pytest tests/ -v` finishes without hanging when no ESP32 is connected.
- Importing `main.py`, `myfavcolor.py`, `standalone.py`, and `webconnect.py` in desktop tests does not start unbounded hardware loops.
- Tests cover all three boot-selected paths: web-connect, favorite-color, and analog.
- Scenario tests can run with only fake hardware.
- Emulator failures produce actionable exceptions instead of indefinite waits.
- `EngAI_MANIFEST.txt` and tests agree that both activities are deployed.
- README instructions match the repository's current behavior.

## Non-Goals

This proposal does not require:

- Replacing real ESP32 validation.
- Simulating analog electrical behavior in high fidelity.
- Simulating OLED pixel output perfectly.
- Rewriting every driver.
- Introducing a large external test framework.
- Changing the educational behavior of either activity.

The emulator should be strict where software contracts matter and simple where physical fidelity would not improve regression detection.

## Main Risk

The highest-risk part is import safety. It touches the boundary between MicroPython execution style and desktop testability. The implementation should make the smallest possible changes:

- Preserve current on-device entry behavior.
- Move execution under explicit startup calls.
- Keep hardware wiring names and constants recognizable.
- Add tests before deeper refactors.

That approach gives immediate protection against hangs and dispatch drift while leaving the activity code recognizable for classroom use.
