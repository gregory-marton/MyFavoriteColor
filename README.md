# MyFavoriteColor

This repository contains the MicroPython code deployed to the Smart Motor ESP32 for the Engineering with Artificial Intelligence activity.

The current deployment includes both standalone activities at the same time:

- `myfavcolor.py`: favorite-color reinforcement-learning activity using the Grove I2C color sensor.
- `standalone.py`: analog / accelerometer activity using the older light-or-accelerometer training flow.
- `webconnect.py`: serial / JSON web-connect mode.
- `main.py`: boot dispatcher that selects the active path.

## Boot Selection

`main.py` is the runtime entrypoint.

On startup it:

1. Reads `prefs.mode`.
2. Allows a startup button chord to toggle between standalone and web-connect mode.
3. In standalone mode, scans I2C devices.
4. Selects `myfavcolor.py` when device address `0x10` is present.
5. Selects `standalone.py` when the color sensor is absent.
6. Selects `webconnect.py` when `prefs.mode == 1`.

The pure selection rule is covered by desktop tests:

```python
choose_activity(mode, i2c_devices)
```

## Desktop Testing

The tests run without an ESP32 connected.

```bash
python3 -m pytest tests/ -v
```

The current desktop suite covers:

- Boot dispatch for web-connect, favorite-color, and analog activity paths.
- Startup mode-toggle behavior.
- Import safety for `main.py`, `myfavcolor.py`, `standalone.py`, and `webconnect.py`.
- Bounded smoke runs for `standalone.main()` and `webconnect.main()`.
- Favorite-color startup handoff without entering the unbounded training loop.
- Color distance math.
- Dynamic reward computation and Q-learning environment stepping.
- Manifest file-size checks.

## SmartMotor Emulator

`smotoremu/` contains the desktop SmartMotor emulator used by tests and tooling
when no ESP32 is connected. It runs the real device modules against maintained
MicroPython shims for `machine`, `framebuf`, `ubinascii`, `urandom`, `uselect`,
I2C peripherals, virtual time, a virtual filesystem, the OLED framebuffer, the
servo, buttons, battery, potentiometer, accelerometer, and attachable sensor
models.

Tests use the public facade through `smotor.launch(...)` and pytest fixtures
from `smotoremu.testing`. The emulator can boot `main.py`, exercise real boot
dispatch, attach a VEML6040 color sensor world, inspect OLED text and PNG
frames, drive buttons and potentiometer input, and run auto-waiting assertions
without wall-clock sleeps.

The emulator is meant to catch Python logic, dispatch drift, unbounded import
behavior, screen regressions, and basic hardware-contract mistakes before
hardware is connected. It still does not replace hardware validation for
physical button feel, servo behavior under load, or target upload reliability.

## Runtime Entry Boundaries

Runtime modules are now safe to import in desktop tests:

- `main.py` exposes `main()` and `choose_activity(...)`.
- `myfavcolor.py` exposes `main()` and defers hardware construction until startup.
- `standalone.py` exposes `main(max_iterations=None)`.
- `webconnect.py` exposes `main(max_iterations=None)`.

The optional `max_iterations` arguments are for emulator and smoke-test use. On the ESP32, the default remains an unbounded hardware loop.

## Deployment

`EngAI_MANIFEST.txt` lists the files copied to the device. It includes both activity files, shared drivers, preferences, and training data.

The file-size test verifies manifest entries remain below the known upload threshold:

```bash
python3 -m pytest tests/test_filesize.py -v
```

If an upload through the CEEO RS232 web tool hangs or fails, reset the board before retrying. Earlier hardware testing showed that a failed serial upload can leave the board session in a bad state until reset.

## What Still Requires Hardware

Run on the ESP32 before relying on a classroom build for:

- Button feel and debounce behavior.
- Servo direction, range, and settling behavior.
- Serial connection behavior with the actual web UI.
- Upload reliability through the target flashing workflow.
- Color-sensor readings under actual classroom lighting and sensor-to-sensor
  variation.
- White-balance behavior under actual classroom lighting.

Desktop tests are the first gate. Hardware validation is still the final gate.

## Proposal Document

The implementation plan and rationale are captured in:

- `EMULATION_TESTING_PROPOSAL.md`
