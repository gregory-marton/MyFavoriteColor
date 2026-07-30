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

## Emulator Fakes

`tests/fakes/` contains lightweight desktop replacements for MicroPython-only modules:

- `machine.py`: fake pins, ADC, PWM, timers, I2C devices, and I2C memory.
- `icons.py`: fake Smart Motor OLED UI that records display calls.
- `ssd1306.py`: fake web-connect OLED display.
- `uselect.py`: fake polling interface for serial input.
- `ubinascii.py` and `urandom.py`: desktop-compatible replacements used by runtime modules.

`tests/conftest.py` puts `tests/fakes/` first on `sys.path`, patches MicroPython time helpers, and resets fake machine state between tests.

The emulator is intentionally simple. It is meant to catch Python logic, dispatch drift, unbounded import behavior, and basic hardware-contract mistakes before hardware is connected. It does not simulate physical I2C timing, real servo motion, analog noise, OLED pixels, or the feel of the buttons.

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

- Real color-sensor detection and VEML6040 readings.
- White-balance behavior under actual lighting.
- OLED visual layout.
- Servo direction, range, and settling behavior.
- Button feel and debounce behavior.
- Serial connection behavior with the actual web UI.
- Upload reliability through the target flashing workflow.

Desktop tests are the first gate. Hardware validation is still the final gate.

## Proposal Document

The implementation plan and rationale are captured in:

- `EMULATION_TESTING_PROPOSAL.md`
