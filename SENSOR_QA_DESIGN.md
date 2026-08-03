# Sensor QA — Health Checks, Conformance, and Fleet Surveys

Status: **proposal / for discussion.**
Companion to `HOSTLINK_DESIGN.md` (which provides the link and the capture
machinery) and `EMULATOR_DESIGN.md` (which consumes the results).

---

## 0. Three different questions

`HOSTLINK_DESIGN.md` §8 treats calibration as *characterisation*: measure one
sensor, fit a model, feed the emulator. That is one of three jobs, and the other
two need different experiment designs and different statistics. Conflating them
is the main way this kind of tooling goes wrong.

| | Question | Unit of analysis | Needs |
| --- | --- | --- | --- |
| **Characterise** | What does this part do? | one sensor, many conditions | a reference standard |
| **Conform** | Is *this* unit healthy? | one sensor vs an envelope | invariants + an envelope |
| **Survey** | How much do units and settings vary? | many sensors, factorial | variance decomposition |

Your two questions are the second and third:

- *"Is this sensor scratched and quietly returning plausible garbage?"* →
  **conformance**.
- *"Is white balance stable enough across sensors and settings to ship a
  default?"* → **survey**.

They share capture machinery with characterisation and almost nothing else.

---

## 1. The key idea: reference-free invariants

A damaged sensor returning values *in the plausible range* is the hard case, and
range checks cannot catch it. What catches it is a **physical relationship that
must hold for a healthy part regardless of what it is pointed at** — so the
sensor is its own reference, and no lux meter, colour chart, or controlled
lighting is required.

For the VEML6040 there are at least five:

**I1 — Integration-time linearity.** Counts must scale linearly with integration
time. The settings span 40 ms → 1280 ms, a 32× range, already enumerated in
`myfavcolor.py`. Sweep them at fixed illumination and fit `counts = a·IT + b`
per channel. A healthy part gives R² > 0.999. The intercept `b` *is* the dark
offset, free. **This is the single best test in the battery**: it needs no
external anything, it exercises the full dynamic range, and both scratches
(reduced `a`) and leakage damage (raised `b`) show up in it.

**I2 — Photon transfer curve.** Shot noise means variance is proportional to
mean: `σ² = g·μ`. Capture many samples at each of several light levels, plot
`σ²` against `μ`, fit a line. The slope is the system gain and should be stable
across units of the same part; a flat or wildly non-linear curve means the noise
is electrical rather than photonic — i.e. something is wrong. This is the
standard image-sensor characterisation technique and it transfers directly.

**I3 — Channel-ratio fingerprint.** Under any *fixed* illuminant, the R:G:B:W
ratios are a property of the filters. They vary with the illuminant, so they are
not an absolute test — but they are a superb *relative* one: compare a unit
against the fleet median under the same lamp. A scratched or contaminated filter
over one channel shifts exactly one ratio, which is a very distinctive
signature.

**I4 — White-channel consistency.** W is unfiltered, so it should track total
illumination and exceed every filtered channel. The precise relation to R+G+B
depends on the source spectrum, so use `W / (R+G+B)` as a *stability* check —
constant across brightness for a given lamp — rather than as a fixed law.

**I5 — Dark floor.** Covered, counts should sit near zero at every integration
time. An elevated or IT-dependent dark reading indicates leakage or damage. Ask
the human to cover the sensor for ten seconds; that is the entire protocol.

For analog parts (light sensor, slide pot) the equivalents are:

- **Output-impedance probe** — drive pin 5 high, then low, and see how much the
  reading moves. This is exactly what `sensors.selectsensor()` already does for
  attachment detection, repurposed as a health metric: a healthy part holds the
  pin; a damaged output stage lets it drift toward the drive.
- **Monotonicity and hysteresis** across a servo sweep, forward then backward.
  Divergence between the two directions means mechanical or thermal trouble.
- **Noise σ and its spectrum** at rest.
- **Step-response time constant** via the servo-swing stimulus
  (`HOSTLINK_DESIGN.md` §8).
- **Rail behaviour** — does it actually reach both ends of its range?

**Design consequence for `HOSTLINK_DESIGN.md` §8:** the reference-instrument
problem I flagged as the weak link applies only to *characterisation*.
Conformance and survey work can run entirely on invariants, which makes them
cheap, repeatable, and immune to a bad lux meter. Do those first.

---

## 2. Health check: `smcal check`

One command, five minutes, one verdict.

```
$ smcal check veml6040
  Cover the sensor completely and press Enter.        [human]
    dark floor          R 2  G 1  B 2  W 3            PASS  (envelope <= 12)
  Uncover and point at any bright, unchanging surface. [human]
    IT linearity        R 0.99997  G 0.99994  B 0.99991    PASS  (>= 0.999)
    dark intercept      R 1.8  G 1.2  B 2.1            PASS
    photon transfer     gain 0.0417 (fleet 0.0409 +- 0.0021)   PASS
    channel ratios      R/G 0.94  B/G 0.51  W/G 2.31   PASS
    saturation          clips cleanly at 65535          PASS
    repeatability       sigma/mu 0.4%                   PASS

  VERDICT: HEALTHY   (7/7, fleet envelope 2026-08 n=14)
```

A failing unit should be told *what* is wrong, not just that it failed:

```
    channel ratios      R/G 0.94  B/G 0.19  W/G 2.28   FAIL
      B/G is 0.19; fleet envelope is 0.51 +- 0.06.
      Red and green look normal, so this is not a lighting difference --
      a lighting change moves all three ratios together.
      Consistent with damage or contamination over the BLUE filter.
      Suggest: inspect the sensor window under magnification.
```

That diagnostic reasoning — *which* invariants broke together, and what that
pattern implies — is the whole value of the tool. Encode it as a small rule
table from failure-pattern to likely cause, and keep it honest: "consistent
with", never "the cause is".

**Two things it must never do:** claim a unit is healthy when it has only been
compared against a fleet that might be uniformly bad (§4), and silently pass a
unit whose readings are stable but whose *absolute* sensitivity has halved. Both
need an absolute anchor, which is why one archived known-good unit matters.

---

## 3. Fleet survey: is a default white balance defensible?

This is an experiment-design question, and it needs a factorial capture followed
by a variance decomposition. The observed white-balance factor for any single
measurement is a sum of contributions:

```
  WB_observed  =  fleet mean
                + unit effect          (does this sensor differ from others?)
                + illuminant effect    (does the classroom's lighting differ?)
                + setting effect       (does integration time matter?)
                + measurement noise    (how repeatable is one measurement?)
```

Ship a default only if the *unit* and *setting* terms are small. If the
*illuminant* term dominates, no per-unit calibration helps either — what you
need is per-room, or per-session, calibration. **That distinction changes the
pedagogy**, so it is worth measuring properly rather than guessing.

### Capture design

Nested factorial: **N units × M illuminants × K integration times × R repeats**.
Suggested first pass: N = 10–15 sensors, M = 3 lighting conditions (classroom
fluorescent, a DC LED lamp, daylight by a window), K = 3 (`IT_160MS`,
`IT_640MS`, `IT_1280MS`), R = 5 repeats. That is 450–675 measurements, each a
few seconds — about an hour of bench time, most of it swapping sensors.

Randomise the order of units within each illuminant so drift (lamp warm-up,
daylight changing) doesn't alias onto unit identity. Re-measure one designated
"control" sensor at the start, middle, and end of every block: if the control
moves, conditions drifted, and the block is suspect. This one habit will save
more grief than any amount of statistical cleverness.

### Analysis

Variance components per channel (a nested random-effects model, or a
Monte-Carlo bootstrap of nested means if that is easier to explain to students
and to trust). The output is the table that answers the question:

```
  Blue-channel white balance factor, n=14 units x 3 illuminants x 3 ITs x 5 reps

    source          variance   sd     % of total
    unit             0.0021    0.046      11%
    illuminant       0.0142    0.119      74%
    integration      0.0009    0.030       5%
    residual         0.0019    0.044      10%

    grand mean B factor: 1.94   (repo default: 1.948)
```

A result shaped like that would say: **the shipped default is fine, per-unit
calibration is not the issue, but lighting dominates — so the white-balance step
must stay in the activity, and it is really a per-room step, not a per-sensor
one.** That is a concrete, actionable, teachable finding.

The opposite shape — unit variance dominating — would say per-unit calibration
is mandatory and a shipped default is actively misleading.

Either way it should be reported with the repo's existing
`WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)` as an overlay, since that triple is
one prior measurement of this same quantity.

---

## 4. Where "compare against the fleet" fails

Fleet-relative testing cannot detect a uniformly bad batch — if every unit has
the same defect, the envelope centres on the defect and every unit passes. Three
mitigations, in order of cost:

1. **Datasheet anchors.** A handful of absolute checks that do not depend on the
   fleet: IT linearity (a physical law, not a population statistic), saturation
   at the 16-bit ceiling, dark floor near zero. **I1 and I5 are anchors, not
   comparisons** — which is another reason to weight them heavily.
2. **An archived golden unit.** Keep one known-good sensor, never issued to
   students, measured at the start of every survey. Cheap and effective.
3. **Cross-part corroboration.** Point the colour sensor and a separate light
   sensor at the same target; gross disagreement in *total* light implies one of
   them is wrong even when both look individually plausible.

State the limitation in the tool's output. A QA tool that overstates its
confidence is worse than none, because it converts "I'm not sure about this
sensor" into false certainty.

---

## 5. What counts as "close enough": derive tolerance from the activity

"Is 8% white-balance error acceptable?" is unanswerable from a datasheet. It is
answerable from the activity, **using the emulator**:

1. Take a calibrated emulator VEML6040 model and a realistic world (the printed
   patches the activity actually uses).
2. Perturb the white-balance factors by ε and re-run
   `Environment.compute_rewards()`.
3. Find the ε at which the *ranking* of state rewards changes — i.e. the point
   where the activity would pick a different favourite colour, or where the
   Q-learner's optimal policy flips.

That gives a tolerance in the units that matter: **"white balance can be off by
up to 14% before the activity's answer changes."** Every threshold in
`smcal check` should be justified against a number like that rather than against
a round percentage someone liked.

This is only possible because the emulator exists and the reward computation is
already a pure function of colours (`compute_rewards`, `distance`,
`DISTANCE_FUNCS` in `myfavcolor.py` are all side-effect free). It is a cheap
experiment — pure host-side compute, no hardware, no board — and it should
happen **early**, because it sets every threshold downstream.

---

## 6. What we need from the hardware (human protocol)

Each procedure is written so the human's part is short, unambiguous, and
uninterruptible-by-mistake. Estimated bench time:

| Procedure | Human does | Time |
| --- | --- | --- |
| **Health check, one sensor** | Cover it; uncover; point at a plain bright surface | ~5 min |
| **Fleet survey** | Swap sensors, change lamp between blocks, keep geometry fixed | ~1 hr for 12 units |
| **Characterisation** (per new part) | Set stimulus levels, read a reference instrument, type values | ~30 min |
| **Golden-unit archive** | Set one sensor aside permanently | 1 min |

**The rig.** Repeatability comes from geometry, so fix it: mount the SmartMotor
over a card at a fixed height, with a shroud (a cardboard box works) to exclude
room light, and a **DC-powered** LED for illumination. DC matters — a
mains-powered lamp flickers at 100/120 Hz, which will show up in I2's noise
measurements and confound them. A phone flashlight is DC and perfectly
acceptable. Take a dark reading immediately before each measurement and subtract
it, so residual ambient cancels.

**A caution on sample size.** With 10–15 units, the fleet envelope is loose and
the survey's variance components have wide confidence intervals. That is fine —
report the intervals rather than hiding them, and treat the first survey as a
baseline to be tightened as more units are measured. Do not let a small-n survey
produce a confident-sounding threshold.

---

## 7. Tasks

Extends `HOSTLINK_DESIGN.md` §12 Phase E. `Q` = QA.

- **Q001 — Activity-derived tolerances.** The §5 perturbation study, pure
  host-side compute against the emulator. **No hardware. Do this first — it sets
  every threshold in the rest of the phase.** Depends on emulator T019.
- **Q002 — Invariant library.** I1–I5 plus the analog equivalents, each as a
  function from a capture to a metric with a pass/fail envelope. Test each
  against synthetic captures with *deliberately injected* faults — a simulated
  scratch (one channel's sensitivity scaled by 0.4), simulated leakage (raised
  dark), simulated excess noise. **Prove each invariant catches the fault it
  claims to catch before it ever sees a real sensor.**
- **Q003 — `smcal check`.** Runs the invariant battery, prints a verdict, writes
  a JSON report. Includes the failure-pattern → likely-cause rule table from §2.
- **Q004 — Fault-injection tests via the emulator.** Add a `faults` block to the
  emulator's sensor models (channel gain scaling, dark offset, excess noise,
  stuck bits, dead channel). Then `smcal check` run against a deliberately
  faulted emulator sensor must report the right diagnosis. This is the
  end-to-end test of the QA tool, and it needs no hardware at all.
- **Q005 — Survey capture.** Factorial runner with randomised ordering, control
  re-measurement, and resumability. A survey that cannot resume after an
  interruption will not survive contact with a real afternoon.
- **Q006 — Variance decomposition + report.** The §3 table, with confidence
  intervals and an SVG plot, overlaid with the repo's existing
  `WHITE_BALANCE_RGB`.
- **Q007 — Fleet envelope store.** `calibration/fleet/<part>-<date>.json`:
  robust medians and MADs per metric, unit count, conditions, and the golden
  unit's reading. This is what `smcal check` compares against.
- **Q008 — Run the survey** (hardware, with you) and write up the answer to the
  white-balance question.
- **Q009 — Student-facing health check.** A one-command "is my sensor OK?" that
  a student can run at the start of an activity. Depends on Q003 and on the
  envelope from Q008. This is arguably the highest classroom value in the whole
  QA phase: it converts a mystifying "my robot is behaving weirdly" into "sensor
  3 is damaged, swap it."

---

## 8. Open questions

- **How many colour sensors are available** for a survey? This sets N and
  therefore how tight the envelope can be. Fewer than ~8 and the survey becomes
  indicative rather than conclusive — still worth doing, but label it that way.
- **Are there any known-bad units?** A confirmed damaged sensor is enormously
  valuable — it is the only true positive available for validating the whole
  battery. Do not discard broken sensors; archive them.
- **Is there a DC lamp available**, or is everything mains-powered fluorescent?
  Affects whether I2 is measurable in the classroom or only in a prepared rig.
- **How many *sessions* of drift matter?** If sensors are stored in a drawer for
  a year between programmes, a repeat survey answers whether ageing is a factor.
  Worth capturing the baseline now even if the question is a year away.
