# Device Health & Battery — design

**Goal:** hand a teacher one command that says, for each SmartMotor in a class
set, *"ready / needs a battery / needs repair / retire"* — with enough evidence
behind each verdict to act on it, and without an overnight charge cycle.

Companion docs: `SENSOR_QA_DESIGN.md` (plug-in sensor conformance — this doc
delegates all sensor-specific checks there), `EMULATOR_DESIGN.md` /
`EMULATOR_TASKS.md` (the emulator this feeds a power model into),
`HOSTLINK_DESIGN.md` (the USB transport these checks run over).

Task IDs here: **B###** battery, **D###** the general health harness.

---

## 0. Verdict up front

Both asks are achievable, and the battery one is more tractable than expected.

- **"Is this battery worn out?" does not require a charge cycle.** Capacity fade
  and internal-resistance rise travel together in lithium cells. Internal
  resistance is measurable in *seconds* with a load step — and the board already
  carries a large, software-controllable load: the servo. A charge cycle
  measures the symptom; a load step measures the cause.
- **The general health check is mostly about making existing signals legible.**
  Almost every check below reads something the hardware already exposes. The
  work is in the harness, the pass/fail criteria, and the fleet bookkeeping —
  not in new measurement techniques.
- **One likely root cause of your reported symptom is already visible in the
  code**, before any bench work. See §2, defect 5: battery thresholds are
  written in *raw ADC counts*, which are chip-specific. The same battery voltage
  reads differently on different boards. That alone can explain "some units
  never show full, no matter how long they charge."

---

## 1. Measured baseline — the known-good unit

Recorded 2026-08-03 from the board on the bench, which you confirm has good
battery health. **This is now the golden reference unit**; keep it identifiable
and don't reflash it casually.

| | |
| --- | --- |
| `unique_id` | `ac 27 6e 7c b6 98` |
| Firmware | MicroPython 1.25.0, `ESP32_GENERIC_C3` |
| CPU | 160 MHz |
| Battery ADC (Pin 4, ATTN_11DB) raw | 2894–2904 over 5 samples |
| Battery ADC calibrated (`read_uv`) | 2.081–2.087 V at the pin |
| State at measurement | plugged into USB, `readbattery()` → `'charging'` |

**Two things fall out of this immediately:**

**`ADC.read_uv()` works on this firmware.** It applies the per-chip eFuse
calibration and returns real microvolts. Nothing in the device code uses it —
`readbattery()` uses raw `read()`. This is the single highest-value fix
available (§2, defect 5).

**The divider ratio is almost certainly 2.0.** 2.084 V at the pin × 2 = 4.17 V,
which is exactly where a healthy, fully-charged single-cell LiPo on USB sits.
Under that assumption the existing thresholds translate to sensible cell
voltages, which is strong corroboration:

| `readbattery()` threshold (counts) | ≈ pin volts | ≈ cell volts | Meaning |
| --- | --- | --- | --- |
| 2850 | 2.05 | **4.10** | → `'charging'` above this |
| 2700 | 1.94 | **3.89** | → `'full'` above this |
| 2500 | 1.80 | **3.60** | → `'half'` above this; `'low'` below |

Those are recognisable LiPo landmarks, which is reassuring — but **the ratio is
inferred, not measured.** Confirming it with a multimeter is bench ask #1 and
everything quantitative downstream depends on it.

---

## 2. What the existing code gets wrong

`sensors.readbattery()` is 15 lines and has six distinct defects. Listing them
precisely matters because several are candidate explanations for your symptom.

| # | Defect | Consequence |
| --- | --- | --- |
| 1 | **Single ADC sample.** One `read()`, no averaging. Measured spread on the good unit is ~10 counts ≈ 14 mV at the cell. | Classification flickers when the voltage sits near a threshold. Note `readpoint()` averages 100 samples — the battery path just never got the same treatment. |
| 2 | **Gaps at exact boundaries.** `>2500 and <2700` / `>2700 and <2875` leave 2500 and 2700 unhandled → falls through to `pass` → returns `""`. `showbattery("")` hits its own `else: pass` and draws nothing. | The previous icon stays on screen. A rare stale-display bug, invisible until you look for it. |
| 3 | **Dead upper bound.** `'full'`'s `<2875` can never matter; `>2850` already returned `'charging'`. | Harmless, but it signals the thresholds were edited without re-deriving the ranges. |
| 4 | **`'charging'` is inferred from voltage alone.** There is no VBUS sense line in the code. | A full battery *off* USB is indistinguishable from one *on* USB. Worse: a genuinely charging but depleted cell reads `'low'`, so the display disagrees with reality exactly when a student would want to trust it. |
| 5 | **Thresholds are in raw counts, which are chip-specific.** ESP32-C3 ADCs have meaningful per-chip gain/offset variation, corrected by eFuse data that `read()` ignores and `read_uv()` applies. | **The same cell voltage reads different counts on different boards.** A board whose ADC reads a few percent low will sit under 2700 at a genuinely full 4.1 V and report `'half'` forever. This is my leading hypothesis for "charges overnight and still won't show full." It is cheap to test — see B002. |
| 6 | **`icons.MAX_BATTERY=2900` / `MIN_BATTERY=2600` are dead constants** inconsistent with the thresholds in `sensors.py`. | Nothing reads them. They will mislead the next person. |

**A seventh, in `selectsensor()` rather than `readbattery()`, found building D010:**
its `low < 200 and high > 4000` formula for detecting an unattached analog
port is similarly tight. A live capture on bad-unit-1 while flipping the
analog/I2C toggle showed the floating-pin state's `high` reading topping out
around 3700-3998 — never crossing 4000 — so this exact formula would report
"attached" for an entire run despite a clear, real regime change (spread
~3670-3970 in one state, within ±660 of zero in the other). Same shape of bug
as defect 5: a threshold tuned tighter than real ADC behavior supports.
`smcheck`'s D010 works around it by classifying on spread instead; `sensors.py`
itself is untouched, per R1.

### A note on fixing these

`EMULATOR_TASKS.md` ground rule **R1** says never change device code to make the
emulator work, and **R6** lists device quirks the emulator must *preserve* rather
than fix. Neither rule forbids fixing genuine device defects — but it makes the
sequencing matter:

1. The emulator must **first** reproduce the current behaviour, quirks and all
   (B007). That is what proves the emulator is faithful.
2. Only then is a device-code fix (B002) safe to make, because the emulator can
   demonstrate the before/after difference on a simulated worn battery.
3. When the device changes, R6's quirk list changes with it — deliberately, in
   the same commit.

Fixing defect 5 before the emulator can show what it fixes would be flying blind
across a whole class set.

---

## 3. Battery health without a charge cycle

### 3.1 The physics, briefly

A lithium cell ages along two coupled axes: it loses **capacity** (mAh it can
store) and gains **internal resistance** (mΩ). Capacity is what you care about;
resistance is what you can measure quickly. They correlate well enough for
triage — a cell whose resistance has tripled has lost substantial capacity, and
a cell with healthy resistance is rarely capacity-dead.

An overnight charge measures capacity directly but costs a night. Resistance
costs seconds. For "should I put this in a student's hands tomorrow?", the fast
proxy is the right instrument.

### 3.2 Test B: DC internal resistance via load step *(primary, ~30 s)*

R_int = (V_rest − V_loaded) / I_load

The board has a controllable load: **the servo**. Drive it and the cell sags in
proportion to its internal resistance.

Procedure:
1. Unplug USB. Rest 60 s (no servo, screen off if possible).
2. Sample battery ADC heavily (≥200 samples, `read_uv`) → `V_rest`.
3. Command a standardised servo exercise — a fixed sweep pattern, plus OLED
   filled white, held for ~2 s.
4. Sample continuously throughout → `V_loaded` (use a low percentile, not the
   mean; the minimum under inrush is the interesting part).
5. Release load, sample for 10 s → recovery curve.

Three numbers come out, all useful:

| Metric | What it tells you |
| --- | --- |
| **Sag** = V_rest − V_loaded | Proportional to R_int. The headline number. |
| **Recovery time constant** | Worn cells recover slowly after load release. Independent corroboration of sag. |
| **Minimum voltage under inrush** | Predicts brownouts — directly relevant to §4. |

**We don't need absolute milliohms to triage.** Same stimulus on every unit →
rank the fleet → outliers are suspect. This is the same fleet-relative strategy
`SENSOR_QA_DESIGN.md` uses for sensors, and it inherits the same blind spot: a
uniformly-bad batch looks normal. Mitigate by anchoring once — measure servo
current with a meter on the golden unit, convert its sag to real milliohms, and
compare against a datasheet expectation (a healthy small LiPo is roughly
100–300 mΩ; over ~1 Ω is worn out).

### 3.3 Test C: charge-acceptance slope *(secondary, ~10 min)*

This is the one that directly replaces the overnight cycle for your stated case.

Start from a partially-depleted cell, plug in USB, and log voltage for 10
minutes. A healthy cell in constant-current charge climbs steadily. **A
capacity-dead cell shoots to termination voltage almost immediately** — it has
little to fill. So:

> Reaching ~4.1 V within a few minutes of charging from a genuinely depleted
> start is *evidence of a bad battery*, not a good one.

That inverts the intuition behind the current display, and it's exactly the
discrimination you asked for. It needs a depleted starting point, so it isn't
instant — but 10 minutes is not overnight.

### 3.4 Test D: open-circuit voltage after rest *(context, 5 min)*

OCV after ≥5 minutes of true rest estimates state of charge. Necessary context
for interpreting B and C (sag depends on SoC), but weak on its own: the LiPo OCV
curve is famously flat between roughly 3.7 and 3.9 V, so mid-range OCV barely
constrains SoC. Useful near the ends, unreliable in the middle. Recording it
honestly and not over-reading it is the whole discipline here.

### 3.5 Test E: physical inspection *(human, 10 s, highest priority)*

**Any swelling, puffiness, deformation, heat at rest, or smell → retire the cell
immediately.** No electrical test overrides this, and a swollen pouch cell in a
classroom is a genuine safety issue, not a performance one. This belongs first
in the runbook even though it's the least sophisticated check here.

### 3.6 Recommended combination

| Question | Test | Time |
| --- | --- | --- |
| Is it dangerous? | E (visual) | 10 s |
| Is it worn out? | B (load step), ranked against fleet | 30 s |
| Confirm a B failure | C (charge slope) | 10 min |
| Interpretation context | D (rested OCV) | 5 min |

`smcheck --quick` runs E-prompt + B + D. C is opt-in for units B flags.

### 3.7 Safety rails for the tooling

- Abort any load test if the cell drops below ~3.3 V; never deliberately deep-
  discharge to find capacity.
- Cap total servo-load duration per run (the existing code already has a motor
  guard for long runs — reuse that thinking).
- Never run an unattended charge test on a cell that failed the visual check.

---

## 4. The dual-power question (USB **and** battery)

Your observation — the colour activity needs both simultaneously — is a real
constraint and worth pinning down, because it's confusing in a classroom and it
must be modelled in the emulator.

**Three hypotheses, in order of likelihood:**

1. **Servo inrush exceeds the USB path's delivery.** A servo's stall/startup
   current spike is large and fast. The battery is a low-impedance buffer that
   swallows it; without one, the rail sags and the chip browns out. This would
   also explain why the symptom shows up in the *colour* activity specifically
   if that activity moves the servo while the sensor and OLED are both active.
2. **The charge-management IC current-limits the system rail when no battery is
   present**, which is common behaviour for such parts.
3. **Constant extra draw from the colour sensor's illuminator LED** pushes an
   already-marginal USB-only budget over the edge.

**They're distinguishable by experiment.** Run the colour activity in each power
configuration, N cycles each, logging resets:

| USB | Battery | Result to record |
| --- | --- | --- |
| ✓ | ✗ / removed | completes? resets? at which step? |
| ✗ | ✓ full | |
| ✗ | ✓ half | |
| ✗ | ✓ low | |
| ✓ | ✓ full | (the known-working case) |
| ✓ | ✓ low | |

Instrumentation: `machine.reset_cause()` plus a boot counter persisted to
`prefs.py`, so an unattended run leaves evidence. Confirmed on the bench unit:
`reset_cause()` works (returned 5 = soft reset, expected under `mpremote`).
Whether the ESP32-C3 surfaces brownout distinctly through MicroPython's mapping
needs checking — if it doesn't, the boot counter still catches it, since an
unexplained boot *is* the signal.

Deliverable: a truth table that becomes both classroom documentation ("plug in
for the colour activity") and the emulator's brownout model.

---

## 5. The general health check — `smcheck`

### 5.1 Shape

One command per device, run from the laptop over USB. Two depths:

- **`--quick` (~30 s, fully automated).** Everything requiring no human hands.
  This is what you run across 30 devices the afternoon before class.
- **`--full` (~3 min, prompts you).** Adds checks needing someone to press a
  button, twist a knob, or look at the screen. Run on units that warn.

Output: a per-device report card (human-readable + JSON), appended to a fleet
store keyed by `unique_id`. The store is what makes drift visible — a unit whose
battery sag has doubled since September is a different signal from one that was
always mediocre.

### 5.2 Check catalogue

| ID | Check | Method | Auto | Fails when | Meaning |
| --- | --- | --- | --- | --- | --- |
| D-ID | Identity | `unique_id`, firmware version, CPU freq | ✓ | — | Fleet bookkeeping key |
| D-FW | **Firmware drift** | Hash every on-device file, compare to expected manifest | ✓ | Any mismatch | *See §7 — this is not hypothetical* |
| D-FS | Filesystem | Free bytes; `prefs.py` write/read/restore round-trip | ✓ | No space; prefs won't persist | Flash wear, full disk |
| D-RST | Reset history | `reset_cause()` + persisted boot counter | ✓ | Unexplained boots | Brownouts, instability |
| D-I2C | Bus scan | Scan; expect 0x3C (OLED), 0x53 (ADXL345), 0x10 (VEML6040 when fitted) | ✓ | Missing/extra address; SDA or SCL stuck low | Broken solder joint, dead peripheral, bus contention |
| D-OLED | Display | Render a known pattern; human confirms | — | Missing rows/columns, no image | Dead panel or ribbon |
| D-ACC | Accelerometer | **‖(x,y,z)‖ ≈ 1 g in any orientation** | ✓ | Magnitude off; zero variance across samples | Reference-free invariant — catches a stuck or lying sensor without a known orientation |
| D-POT | On-board pot | Human sweeps end to end | — | Range short of 0/4095, non-monotonic, dead zones, excess noise | Worn wiper |
| D-BTN | Buttons | Human presses each | — | No detection; excessive bounce | Failing switch |
| D-SRV | Servo | Commanded sweep, **confirmed via battery sag** | ~ | No current draw → not connected/not moving | Sag doubles as a servo-presence probe, since the servo is open-loop with no position feedback |
| D-PORT | Sensor port + analog/I2C toggle | `selectsensor()` probe in both switch positions | ~ | Same result in both positions | Broken toggle or port |
| D-SNS | Attached sensor | Delegate to `SENSOR_QA_DESIGN.md` invariants I1–I5 | ✓ | Per that doc | Scratched/damaged sensor returning plausible values |
| D-BAT | Battery | §3 tests B, D (+E prompt) | ~ | Sag outside fleet envelope | Worn cell |
| D-PWR | Power combinations | §4 truth table | — | Deviates from golden unit | Marginal power path |

D-ACC deserves emphasis: gravity's magnitude is constant regardless of how the
device is held, so a single sample validates the sensor with no fixture, no
known orientation, and no cooperation from the person holding it. Combined with
a variance check (a stuck sensor reports a *plausible* constant), it's a strong
automated check for near-zero cost.

### 5.3 Triage workflow for a class set

1. `smcheck --quick` on every unit — target under a minute each including
   plugging/unplugging.
2. Sort into **ready / warn / fail**.
3. `smcheck --full` on warns only.
4. Bucket: **ready** · **needs battery** · **needs repair** · **retire**.
5. Keep 10–15% spares — a mid-class failure costs far more than a spare device.
6. **Archive, don't discard, confirmed-bad units.** Per `SENSOR_QA_DESIGN.md`,
   a known-bad unit is the only true positive available for validating that
   these checks actually detect anything. Same argument applies to a worn
   battery: it's the calibration standard for §3.

---

## 6. Emulator integration

The power model the emulator needs, once §3 and §4 produce numbers:

```yaml
power:
  usb: true
  battery:
    soc: 0.4              # state of charge, 0..1
    capacity_mah: 500     # nameplate
    r_int_mohm: 400       # the health knob — raise to simulate a worn cell
    ocv_curve: lipo_1s    # named curve, fitted from fleet data
```

Load model: servo duty × current profile, OLED on/off, sensor draw. Terminal
voltage = OCV(soc) − I·R_int. Below a brownout threshold → emulated reset with
the right `reset_cause`.

What this buys, concretely:

- **Test the activity at low battery without waiting for a low battery.** Set
  `soc: 0.1` and watch what students would see.
- **Reproduce the quirks** of §2 (the `""` gap, the charging misclassification)
  so they're pinned by tests before anyone fixes them — this is R6 applied to
  the battery path.
- **Verify the defect-5 fix** across simulated per-chip ADC variation, which is
  precisely the variation that's invisible on a single bench device and only
  shows up across a class set.

That last point is the argument for doing the emulator work before the fleet
fix, not after.

---

## 6.5 Field notes — real units probed 2026-08-03

Raw log in `spikes/S5_battery/fleet.csv`. Two cases worth recording because they
show two *different* failure signatures, not one generic "bad battery":

**bad-unit-1** (`uid 1cdbd4eba680`) — clean, single-mechanism story. Plugged in
showing raw 2558 (~3.70 V, device said `'half'`); after 10 minutes on USB charge,
raw 2878 (~4.16 V, device said `'charging'`) — a ~0.46 V climb in 10 minutes,
converging on almost exactly the golden unit's fully-charged voltage. That's
fast: a healthy cell with real capacity takes much longer to climb through that
range. This is the §3.3 signature — reaching near-termination voltage quickly
from a depleted start is evidence of *low remaining capacity*, not health. Good
candidate for the archived known-bad-battery reference unit (§7 ask 3).

**unit-3** (`uid ac276e7c1860`) — two separate findings, now that D-OLED (§8,
D006) exists and was run against it directly with real test patterns, photo
evidence attached in this session.

*Display:* **not flicker.** Against a border/crosshair pattern, the top border
edge is missing entirely, the two top corner squares render as thin horizontal
stripes instead of solid 10×10 blocks, and the top half of the vertical
midline is dotted rather than solid — while everything below the horizontal
midline (bottom border, bottom corners, centered text, lower half of the
vertical line) is pixel-perfect. A full-white fill confirmed the same
signature: a clean, static horizontal band of thin stripes confined to
roughly the top quarter of the screen, solid white everywhere below it. That's
a **static defect confined to a specific vertical band, not a time-varying
one**, and the sharp boundary at the midline points at a fault isolated to the
first page or two of the SSD1306's GDDRAM (the controller addresses its 64
rows as 8 pages of 8 rows each) — a controller/RAM or connector-address-line
fault, not obviously a power-supply symptom.

*Battery:* on USB, `'full'` (raw 2798, ~4.17 V) one moment; unplugging showed
the on-screen level jump *instantly* to one bar; replugging and re-probing
minutes later gave raw 2427 (~3.63 V, `'low'`) — a 0.54 V swing on USB power
with no deliberate load applied. Still real and still unexplained, but **the
earlier theory tying this directly to the display fault is now weaker**: a
static GDDRAM/page-addressing defect isn't an obvious source of the kind of
erratic current draw that would explain a battery voltage swing. Treat these
as two independent faults on the same unit unless further evidence links them
directly, and don't assume fixing one explains the other.

The practical lesson for `smcheck`: **D-OLED with more than one pattern earns
its keep.** A border-only pattern would have left most of the screen untested
and produced a vaguer verdict; running a full-white fill alongside it is what
pinned the defect to a specific vertical band instead of a generic "top of
screen looks wrong."

---

## 7. What I need from you at the bench

Roughly in priority order. Nothing here needs more than a multimeter.

**1. Confirm the divider ratio (5 min, unblocks all quantitative battery work).**
Measure cell voltage at the battery terminals with a meter, and simultaneously
read the ADC. Two points at different charge levels is ideal; one is enough to
confirm the ×2 inference. Everything in §1's translation table rests on this.

**2. Measure servo current once on the golden unit (10 min, optional but
valuable).** A meter in series during a sweep converts fleet-relative sag into
real milliohms and lets us compare against datasheet expectations instead of
only against each other.

**3. ~~A known-bad battery~~ — you have some, and they're the fastest win here.**
This moves to the front of the queue. `spikes/S5_battery/probe_battery.py` needs
no bench equipment and takes ~10 seconds per unit:

```bash
./spikes/S5_battery/probe_battery.py --label suspect-1 --state just-charged
```

It reads raw counts and calibrated volts together, which **discriminates the two
competing explanations in one shot** (§2 defect 5 vs. a genuinely worn cell):

| Reading | Conclusion |
| --- | --- |
| raw < 2700 but calibrated ≈ 2.05 V | Battery is fine; this chip's ADC reads low and the raw thresholds misjudge it. **A software fix recovers the unit.** |
| raw < 2700 *and* calibrated well below | Cell genuinely won't hold charge. Replace it. |

If the first case shows up on even one unit, B002 stops being a tidy-up and
becomes the highest-value change in this document — it would mean some retired
devices are healthy and were retired by a measurement bug.

Reference reading already captured from the golden unit (2026-08-03, on USB):
raw 2894, 2.079 V at pin, ≈4.16 V at cell, reports `'charging'`. Results append
to `spikes/S5_battery/fleet.csv`.

**4. The §4 power truth table (~30 min).** Needs someone to physically toggle
USB and the battery switch between runs. Can wait until D-PWR tooling exists,
which will do the logging.

**5. Two facts I'd otherwise guess at:**
   - Is the battery switch a true disconnect, or does it only gate the load?
     (Determines whether "USB, no battery" is even testable without opening the
     case.)
   - Battery nameplate capacity and chemistry — a photo of the cell label is
     enough.

**6. Fleet size** — how many devices in a class set, and how many spares? Sets
whether `smcheck` needs to be fast-and-parallel or whether serial-and-thorough
is fine.

---

## 8. Tasks

Ground rules R1–R8 from `EMULATOR_TASKS.md` apply. Test-first throughout: for
health checks that means **writing the fault case first** — a check nobody has
watched fail is not a check.

### Battery

| ID | Task | Needs | Notes |
| --- | --- | --- | --- |
| B001 | Divider calibration: raw/`read_uv` → cell volts, with the measurement recorded and sourced | Bench ask #1 | Per R5, the constant gets a name, a source, and a comment |
| B002 | `read_uv()` + multi-sample battery read; re-derive thresholds in volts, not counts | B001 | **The defect-5 fix.** Sequence after B007 |
| B003 | Load-step (DCIR) procedure + host tooling | B001 | Sag, recovery constant, inrush minimum |
| B004 | Charge-acceptance slope test | B001 | The overnight-cycle replacement |
| B005 | Fleet battery envelope + ranking; thresholds from data, not guesses | B003 across units | Mirrors `SENSOR_QA_DESIGN.md` Q007 |
| B006 | Emulator battery + power model (§6) | Emulator T-series | OCV curve, R_int, brownout |
| B007 | Emulator tests pinning current `readbattery()` quirks | B006 | **Before** B002 |

### Health harness

| ID | Task | Needs | Notes |
| --- | --- | --- | --- |
| D001 | `smcheck` skeleton: report card format, JSON schema, fleet store keyed by `unique_id` | — | **Start here**; everything else plugs in |
| D002 | D-ID + D-FW firmware-manifest check | D001 | See §7 motivation — real, observed problem |
| D003 | D-FS filesystem + prefs round-trip | D001 | |
| D004 | D-RST reset cause + boot counter | D001 | Also instruments §4 |
| D005 | D-I2C bus scan + stuck-line detection | D001 | |
| D006 | D-OLED test pattern + human confirm | D001 | |
| D007 | D-ACC gravity-magnitude invariant + stuck detection | D001 | Cheapest strong check |
| D008 | D-POT + D-BTN human-assisted | D001 | |
| D009 | D-SRV servo check via battery sag | B003 | Reuses the load-step machinery |
| D010 | D-PORT sensor port + toggle probe | D001 | Depends on the toggle answer in `HANDOFF.md` |
| D011 | D-PWR power-combination runner | D004 | Produces the §4 truth table |
| D012 | Fleet summary + triage report | D002–D011 | The ready/warn/fail rollup |
| D013 | Teacher runbook (§5.3 as a printable procedure) | D012 | The actual deliverable for a class set |

### Suggested order

**No hardware needed:** D001, then D002–D007. These are ordinary software with
clear interfaces and are good Sonnet tasks.

**Needs the bench:** B001 first (it gates every battery number), then B003,
then D009/D011.

**Needs the emulator:** B006/B007, after the T-series is far enough along to
host a peripheral model.

---

## 9. Open questions

- **Does the ESP32-C3 surface brownout distinctly** through MicroPython's
  `reset_cause()` mapping, or does it collapse into a generic hard reset? If the
  latter, the boot counter carries D-RST alone. *(Testable without hardware
  changes; just needs a deliberate brownout.)*
- **Is per-chip ADC variation actually large enough** to explain the
  never-shows-full symptom, or is it a second-order effect on top of genuinely
  worn cells? B001 across several units answers this, and it's worth answering
  early — it changes whether B002 is a fix or a nicety.
- **Do batteries in this fleet age uniformly?** If they were all bought and
  installed together, fleet-relative ranking degrades exactly when it's most
  needed (§3.2's blind spot). The archived known-bad unit is the mitigation.
- **How much of `smcheck` should students be able to run themselves?** A
  student-facing "is my device OK?" is a different, gentler artifact than a
  teacher's triage tool — related to `SENSOR_QA_DESIGN.md` Q009.
- **Should `smcheck` run against the emulator too?** It would make the harness
  testable in CI with injected faults, which is how D-checks get their
  fault-case tests. Probably yes, via the `Transport` seam in
  `HOSTLINK_DESIGN.md`.
