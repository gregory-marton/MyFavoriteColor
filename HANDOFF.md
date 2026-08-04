# Handoff Status — who does what next

Living document. Update as tasks land.
Design docs: `EMULATOR_DESIGN.md`, `EMULATOR_TASKS.md`, `HOSTLINK_DESIGN.md`,
`SENSOR_QA_DESIGN.md`, `DEVICE_HEALTH_DESIGN.md`.

## Current execution checkpoint — 2026-08-04

The emulator implementation is through T027 and is installed editable in the
repo-local `.venv`. The latest committed baseline is:

```text
3bc8eed Add emulator websocket protocol
```

At that point the complete suite was green: `.venv/bin/python -m pytest tests/ -q`
reported `276 passed in 23.95s`.

T028 is staged in the working tree but intentionally not committed yet. It is
the live browser OLED shell (`web/index.html`, `web/style.css`, `web/app.js`,
`web/oled.js`) plus `tests/emulator/test_web_live.py`; the former replay test is
being replaced. The first live run reached `5 passed, 1 failed`: the only
assertion failure is Playwright clipboard read permission, and teardown warns
that the websocket server close coroutine is not awaited. Fix those two
fixture issues, rerun focused and full suites, append green output to
`EMULATOR_PROGRESS.md`, and commit with a message such as `Add live websocket
OLED UI`.

Use the repo interpreter for validation:

```bash
.venv/bin/python -m pytest tests/emulator/test_web_live.py -v
.venv/bin/python -m pytest tests/emulator/test_web_live.py tests/emulator/test_protocol.py -q
.venv/bin/python -m pytest tests/ -q
```

Do not stage unrelated local artifacts: `.dev_log_redactor_state.json`,
`dev.log`, or `device_backup_2026-08-03/`. After T028, continue from the
dependency graph in `EMULATOR_TASKS.md` (T029 onward), preserving red-green
discipline and recording each task's evidence in both durable progress docs.

---

## Ready for Sonnet right now (no hardware, no decisions needed)

These are fully specified and unblocked. Hand them over in this order; each is
one focused session.

| Task | What | Why it's safe to start |
| --- | --- | --- |
| **T001** | Package skeleton, pytest wiring | Pure scaffolding |
| **T002** | Virtual clock + event scheduler | Self-contained; 7 named tests |
| **T003** | `framebuf` shim, geometry primitives | Bit layouts fully specified in the task |
| **T004** | 8×8 font + `text()` | ⚠️ needs network to fetch the font (see below) |
| **T005** | Glyph reverse map | The alignment-search wrinkle is specified |
| **T006** | `machine` Pin/ADC/PWM | Pin map is in the task, sourced from this repo |
| **T007** | I2C bus | All six required methods listed with their callers |
| **T009** | SSD1306 peripheral | The "it's alive" milestone |

**Suggested first handoff: T001 + T002 together.** They're small, and T002's
test list is explicit enough to be a good calibration of whether the task specs
are at the right altitude. Adjust the rest based on how that goes.

**Checkpoint after T009.** That's where the real `icons.SSD1306_SMART` should
render real text through the real driver. If it works, the display, font, and
text-extraction chain are all proven at once and the rest of Phase 1 is
mechanical.

### One snag in T004

The task needs MicroPython's `font_petme128_8x8.h` fetched from GitHub. If
Sonnet's environment has no network, it must **stop and ask** rather than
hand-draw a substitute — every downstream text assertion depends on the font
being byte-exact. If that blocks, fetch it yourself once and drop it in
`smotoremu/assets/`, or reorder to do T006/T007 first.

---

## Needs you at the bench (roughly in priority order)

### 1. ~~Run the S4 host-link benchmark~~ — DONE 2026-08-03

Results in `spikes/S4_hostlink/FINDINGS.md`, raw data in `run1.json`. Headline:
small frequent messages stream cleanly at **500 Hz with zero drops**, so the
games/accelerometer use case has plenty of headroom. One design-doc assumption
died: the link behaves like a real ~115200-baud serial port (**~11 kB/s**), not
the ceiling-free full-speed USB `HOSTLINK_DESIGN.md` §0 assumed — bulk transfers
are bandwidth-bound. A 5-minute follow-up (reopen the port at 921600 and re-run
throughput) would tell us whether that ceiling is real or an artifact.

Still worth repeating on a student laptop — that's the case that matters.

**Also discovered:** the board on the bench was running code matching neither the
working tree nor any recent commit — older, pre-refactor `main.py`. All 15 files
backed up to `device_backup_2026-08-03/`; original restored and diff-verified.
**Worth checking whether other units have drifted too** — that's health check
D-FW, and it is no longer hypothetical.

### 1b. Probe the known-bad units — ~10 s each, highest value per minute

You mentioned having bad ones to hand. This needs no bench equipment:

```bash
./spikes/S5_battery/probe_battery.py --label suspect-1 --state just-charged
```

It distinguishes "worn cell" from "healthy cell, miscalibrated ADC" in one
reading — see `DEVICE_HEALTH_DESIGN.md` §7 ask 3. If any retired unit turns out
to be healthy, that reframes the whole battery workstream.

### 2. Answer three hardware questions — no bench time, just knowledge

- **What does the analog/I2C toggle (`!`) do electrically?** Disconnect the I2C
  lines from the port, re-route pin 5, change pull-ups? Emulator task T017
  currently ships an assumption, isolated to one function so it's a one-line fix.
- **What does the power switch (`~`) do** — full power cycle or a reset line?
  Does `prefs.py` survive? (Assumed: full cycle, VFS survives.)
- **Is the ADXL345 fitted on every board?** `sensors.py` tolerates its absence,
  so the emulator makes it configurable, but the default should match reality.

### 3. Inventory for the QA work — whenever convenient

- How many colour sensors are available to survey? (Sets N; under ~8 the survey
  is indicative rather than conclusive.)
- **Any known-broken sensors? Please don't throw them away.** A confirmed
  damaged unit is the only true positive available for validating the health
  checks — it's the most valuable single object in this whole project.
- Is a DC lamp available (phone flashlight counts), or is it all mains
  fluorescent?
- Any reference instruments — lux meter, colour chart?

### 4. One repo question

`README.md` references `EMULATION_TESTING_PROPOSAL.md`, which isn't in the repo.
Should `EMULATOR_DESIGN.md` supersede that reference, or is there a missing doc?

---

## Blocked, and on what

| Work | Blocked on |
| --- | --- |
| Host-link firmware + library (H003+) | ~~S4 results~~ **unblocked** — see §1 |
| Battery quantitative work (B003+) | B001 divider measurement (5 min, multimeter) |
| `smcheck` harness (D002+) | D001 skeleton only — no hardware needed |
| Emulator T019 (VEML6040) | Nothing technically, but calibration data (C006) makes it real |
| Calibration harness (C001+) | Emulator through T019, plus host-link batch mode (H006) |
| **Q001 — activity-derived tolerances** | Emulator T019 only. **No hardware.** Sets every QA threshold, so schedule it early |
| Fleet survey (Q008) | Q005 tooling + your sensor inventory |
| `mpremote`-compatible virtual serial (T034 level 3) | Spike S1 |

---

## Notes for whoever briefs Sonnet

`EMULATOR_TASKS.md` has a "Ground rules" section that matters more than any
individual task. The two that will actually bite:

- **R1: never modify device code to make the emulator work.** `myfavcolor.py`
  and friends are the system under test.
- **R6: a list of real quirks in the device code that must be preserved, not
  fixed** — overlapping battery thresholds, a function that falls off the end
  and returns `None`, `write_angle`'s `% 360`. Without this, an agent will
  "helpfully" fix them and the emulator will stop reproducing the hardware.

Point Sonnet at `EMULATOR_TASKS.md` and the task ID; the task specs are written
to be self-contained, including the interfaces and the tests to write first.
Each task ends with a done-check, and R8 asks for a note in
`EMULATOR_PROGRESS.md` recording the red and green test output.
