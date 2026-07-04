# Running the tests

**Development flow:**
* `standalone.py` — the documented source of truth, with comments and docstrings. This is what actually gets uploaded directly to the device. We keep this code parsimonious to ensure it stays below the documented **36KB upload limit** of the CEEO RS232 web tool.

These tests exercise `standalone.py`s logic on a desktop — no ESP32 needed.

## Setup (one time)

```bash
pip install pytest --break-system-packages   # or use a venv, your call
```

## Run everything

```bash
cd smartmotor
python3 -m pytest tests/ -v
```

Should show all tests passed in a few seconds, every time (fully
deterministic, no flaky timing).

## Run just one file

```bash
python3 -m pytest tests/test_reward_math.py -v       # color distance + reward math
python3 -m pytest tests/test_confirm_screen.py -v     # confirm/recalibrate screen
```

## How it works

- `tests/fakes/` contains lightweight stand-ins for `machine`, `servo`,
  `sensors`, `icons`, `ssd1306`, `adxl345`, `files`, `ubinascii`, `urandom`
  — the MicroPython / hardware-driver modules `standalone.py` imports.
  These go on `sys.path` ahead of everything else, so importing
  `standalone.py` on a desktop just works against fake hardware instead
  of erroring out.
- `standalone.py` itself is untouched except for one guard at the very
  bottom (`if __name__ == "__main__": main()`) so importing it for tests
  doesn't immediately launch the full interactive calibration/training
  flow. On the real ESP32 this changes nothing — MicroPython always runs
  the script as `__main__`.
- `tests/test_confirm_screen.py` drives the confirm/recalibrate screen
  (and a `main()` recalibration-loop integration test) deterministically
  by hooking `time.sleep()` (which the screen's loop calls once per
  iteration) to inject scripted button presses — no real threading
  races, same result every run.

## Before flashing to the device

Run the tests after any change to `standalone.py`'s confirm screen, reward
math, or calibration logic. They won't catch everything (they can't test
real I2C timing, real servo behavior, or the physical feel of the pot),
but they will catch logic regressions in the state machine, which is
exactly the kind of thing that's easy to break by hand-verifying on
hardware alone.

# Design rationale

`standalone.py` on the device (and in this repo) is our documented source of truth. Rather than playing minification/stripping shenanigans, we keep the codebase clean and parsimonious to ensure it stays well under the ~36KB upload limit (see "Upload size limit" below).

## Upload size limit (empirical)

Uploads through the CEEO RS232 web tool hung at ~36.4KB regardless of
file size (69.73% of a 52KB file and 92% of a 39KB file are both ~36.4KB
absolute), suggesting a fixed buffer limit in the transfer path. Getting
well under that limit was necessary but not sufficient — smaller files
(18–26KB) still failed outright (a different failure mode: immediate
"failed to upload" rather than a stall) until the board was power-cycled
first. **A failed or hung upload attempt appears to leave the board's
serial/REPL session in a bad state; subsequent attempts fail against
that stale state regardless of file size until the board is reset.**

**Practical upload recipe:** reset the board, *then* upload. If an
upload hangs or fails, reset the board again before retrying — don't
just retry into the same session.

Removing the entire on-device settings menu (see below) in favor of
top-of-file constants brought the stripped file down to ~18KB, with
substantial margin under the ~36KB hang point. Combined with resetting
the board before each attempt, uploads succeeded reliably.

## Code removed in the July 2026 leaning pass (vs. the original)

All verified dead in the new flow (written but never read, or never
called), removed from `standalone_full.py` itself:

- **Icon-menu machinery** (`check_switch` timer, `uppressed`/
  `downpressed`/`selectpressed`/`displayselect`/`resettohome`,
  `flags`, `highlightedIcon`, `screenID`, etc.) — the original icon UI;
  the new flow polls buttons directly. `flags` was set but never read,
  and `displayselect` could draw icon-selector artifacts over episode
  screens.
- **`setloggingmode()` + `LOGGING` + `from files import *`** — the new
  code never writes data logs; `LOGGING` was assigned and never read.
- **`ID`** (hexlified `machine.unique_id()`) — never used.
- **Debug print verbosity** — the 14-line per-timestep dump is now one
  line; per-episode summaries condensed.
- **Timer renumbering (real bug fix):** ESP32-C3 has only two hardware
  timers (ids 0 and 1). The code previously created `Timer(2)` for the
  live-reward readout, which likely fails on real C3 hardware (desktop
  fakes couldn't catch it). Removing the vestigial `check_switch` timer
  freed an id: battery is now `Timer(0)`, live reward `Timer(1)`.
- **The entire on-device settings menu** (screen navigation, pot preview/
  commit/discard, deadzone, relative/absolute tracking, wraparound) —
  replaced with top-of-file constants and a two-line confirm screen. See
  "Settings are top-of-file constants" below for what replaced it and
  why, and for where the removed design (still legitimate, just no
  longer needed) is documented in case it's useful again later.
- **Interactive early-finish during calibration** — calibration used to
  let you stop early via UP once you had 2+ states. `NUM_STATES` is now
  a pure constant with no in-flow override; UP inside calibration is
  used exclusively to toggle pot-drag vs. step mode.

## Favorite-color RL activity, overall flow

1. **Favorite color capture** — point the sensor at a real object (e.g.
   a mark on paper the device is mounted over) and press SELECT to lock
   in its RGB as `favorite_color`. The pot drives the servo live here, so
   you can aim the arm before locking in.
2. **State calibration** — move the arm to each of `NUM_STATES` positions
   (pot-drag or 20°-increment stepping, UP toggles between the two) and
   press SELECT to save each one. No manual reward entry — reward is
   derived automatically afterward from each state's color distance to
   `favorite_color`. Calibration always walks exactly `NUM_STATES`
   positions — there's no in-flow early-finish or count adjustment
   (change the constant and re-upload instead; see below).
3. **Confirm screen** — shows a summary (state count, episode length,
   distance metric, which calibrated state is closest to the favorite
   color). SELECT starts training; UP redoes favorite color + all states
   from scratch and returns here.
4. **Q-learning training** — fixed-length episodes so a student can build
   a reward "valley" physically in the environment (e.g. drawing
   progressively-less-similar colors between the start position and the
   best-reward position) and observe whether the agent finds it worth
   crossing, especially as episode length is shortened.

## Reward computation (`compute_state_rewards`)

Reward is self-normalizing: `reward = max_reward * (1 - distance /
max_observed_distance)`, where `max_observed_distance` is the largest
distance seen among the calibrated states relative to the favorite
color. This means it adapts automatically to whatever raw value range a
given color sensor produces — no sensor-specific constants baked into
the reward math. If you swap in a different color sensor, its driver
just needs to expose `.rgb` as a roughly-0-255 tuple (see `VEML6040.rgb`
for the reference normalization) and nothing else needs to change.

## Distance metrics

Two are built in: `dist_euclidean` (plain) and `dist_perceptual`
(ITU-R BT.601-style luma weights: R=0.30, G=0.59, B=0.11, so a green
shift registers as a bigger distance than an equal-magnitude red or blue
shift). To add a true perceptual metric (e.g. CIE Lab / delta-E), write
a function with the same `(c1, c2) -> float` signature and add it to
`DISTANCE_FUNCS` — nothing else in the program needs to change.

## Color sensor: integration time and white balance

Early hardware testing showed two issues, both fixed via student-visible
constants near the top of the file rather than inside the driver:

- **Readings too dark** (e.g. a max-brightness laptop screen viewed
  close-up read as low as (34, 34, 17) at the sensor's default 160ms
  integration time). `COLOR_INTEGRATION_TIME` controls how long the
  sensor exposes per internal measurement cycle; raised to `IT_640MS`
  (4x longer, roughly 4x brighter readings for the same light) as a
  reasonable default. If still too dark, `IT_1280MS` is available, but
  raise `SETTLE_TIME` to stay above whatever integration time you pick,
  so a reading is never taken before a fresh measurement cycle finishes.
- **Blue channel under-reporting.** At the corrected integration time, a
  neutral white surface read (113, 106, 58) — blue at roughly half of
  red/green — and a piece of blue paper read (22, 20, 21), barely
  blue-dominant at all despite being visibly blue. This is a real
  characteristic of the VEML6040 (its blue photodiode is less sensitive
  than red/green for the same light), not a wiring or calibration
  mistake. Fixed with a white-balance correction: `WHITE_BALANCE_RGB`
  holds a per-channel gain, applied inside `VEML6040.rgb` after the
  existing 0-255 normalization, derived so a known-neutral surface
  reads as equal R=G=B. With the derived gains `(1.0, 1.066, 1.948)`,
  the same white reads (113, 113, 113) and the blue paper reads
  (22, 21, 41) — now clearly blue-dominant. Re-derive for a different
  sensor unit or lighting setup by pointing at something neutral,
  reading the raw (r, g, b) via the live readout during calibration,
  and setting each gain to `max(r, g, b) / that channel's value`.

## Settings are top-of-file constants, not an on-device menu

An earlier version of this activity had a full on-device settings menu
(navigate screens with UP/DOWN, preview values live with the
potentiometer, commit with SELECT) sitting between calibration and
training. It worked, but it was the single largest chunk of the file —
removing it was the main lever for getting upload size down — and
arguably it was also less transparent pedagogically than just seeing
every knob at once as a documented constant at the top of the file.

`NUM_STATES`, `EPISODES`, `TIMESTEPS`, `COLOR_INTEGRATION_TIME`, and `WHITE_BALANCE_RGB` are now plain module-level constants with explanatory comments right above the definitions. To change any of them: edit them in `standalone.py` and upload. There's no in-flow validation of these values beyond what Python itself enforces.

If a future need justifies bringing back some on-device adjustment (e.g.
letting students A/B distance metrics without re-uploading), the git
history / earlier README revisions in this conversation cover the pot
deadzone/relative-tracking/wraparound design that made that usable —
it's a legitimate approach, just more code than the activity currently
needs.

## Recalibration

The confirm screen's UP action always runs a full recalibration
(favorite color + all `NUM_STATES` states) unconditionally — it's the
"redo it, lighting changed" action, and `main()` loops back to the
confirm screen afterward rather than proceeding straight to training.

## Live reward / RGB readouts

A low-priority timer (`live_reward_tick`, ~300ms period) shows the
reward the arm would currently receive, but only while the servo isn't
mid-move (`motor_moving` flag) — this avoids I2C contention with the
button-check timer and avoids showing meaningless in-transit readings.
During calibration (pot-drag and 20°-increment modes) and immediately
after saving a state, the screen also shows live/just-read RGB values,
purely so a student can see the sensor is actually responding as they
aim the arm, before committing to a state.

## Future work

### Auto-dispatch between activities based on switch position

The device currently hosts two activities: this RL one (switch in I2C
mode) and a kNN one (switch in analog mode). Right now each requires
re-flashing `standalone.py` between them.

A `main.py` dispatcher could eliminate that: probe the I2C bus at boot,
and if the VEML6040 color sensor answers at address `0x10` (switch in
I2C mode) run `qrl.py`; otherwise run `knn.py`. Students would just flip
the switch — no re-flashing. Each file stays under the 36KB upload limit
individually; the one-time setup cost is uploading three files instead of
one.

