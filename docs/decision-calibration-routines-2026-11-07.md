# Decision: Calibration Routines are first-class records, graded by a noise ladder (2026-11-07)

**Status:** accepted on merge (sim2real main: `type_cards/calibration.py` ROUTINES, `sysid/noise_ladder.json`, `sysid/ladder.py`,
`sysid/results/calibration_routines.json`). Decided for Zach by the calibration-routines lane; his to overrule (undo: `git revert` the merge
commit named in the handoff). Called "procedures" until Zach named them Calibration Routines ("Routine") the same day.

## Context

Zach, 2026-11-07 (via the coordinator): "We have the real thing and we have the twin. Any error is caused by errors in our model: the
fidelity of the models and the accuracy of the parameters ... what are the parameters and what are the methods we have to calibrate those
parameters." His Nov 6 note asks to "enumerate some different like calibration schemes ... dynameter could be one ... Some of these we
can run on a bench some we can run when the robot is deployed ... check these vs an orcale in simulation", and for kinematic calibration
"see if you can recover the perfect values... (you can change the amount of noise you add to the sensor measurements...)".

The frame, checked against the oracle, needs one term added. Twin error is model structure plus parameter values, but a parameter's
accuracy is set by the **routine** that measured it: its excitation, its instrument and that instrument's timing, as much as by noise.
The ladder shows it directly: one frame (10 ms) of tracker latency costs the conveyor's drum radius 0.72 of its tolerance, against 0.066
for ten times the tracker's noise; whole-pixel dot detections fail the line camera's geometry at 1x noise. And a model a routine fits can
be wrong in a way no noise level fixes (T10's tanh Coulomb against a Stribeck truth; the stock gravity sweeps under CAN 11's limit cycle;
gear_backlash's UR sweep, biased with no noise at all). So the thing to track is the routine, graded on the same truth.

## Decision

1. **A Calibration Routine is a typed record in type_cards** (`schema.CalibrationRoutine`, `reg.ROUTINES`), one way to run one of Zach's
   packages (`CALIBRATION_PACKAGES` is unchanged and stays his grouping). It names the (card, rung, parameter) it identifies; where it runs
   (`bench`, `deployed`, `both`); wall time, operator time and equipment cost (every number a `Quantity` whose source is a citation or the
   word "estimate"); its equipment (`reg.EQUIPMENT`, costed once); excitation, coverage and repeats; the test types whose data it uses;
   its code (checked to exist at its ref; `not implemented` means none); the oracle checks that grade it; and its alternatives, which name
   it back. 33 routines, 10 equipment items.
2. **Both directions.** Routine to parameters is the record's `identifies`; parameter to routines is `reg.routines_identifying(card,
   parameter)` and `reg.parameter_routines()`, tested to be each other's inverse. The table carries both: a row per routine, and an entry
   per graded parameter naming every routine that can identify it.
3. **Per parameter, per model.** For every graded parameter at every level the ladder keeps the true and nominal values, the tolerance
   and, for every model the routine fitted it with, the recovered mean, the routine's own 95 % interval (and how it was made, or why there
   is none), the error and the error in tolerances. CAN 11's regression fits four models (M0, M2, M3, M4); every other routine one. A site
   can draw one recovered / error column group per model.
4. **The oracle's numbers live in sysid, never in type_cards.** A record names its checks (`"<example>:<routine>"`); the verdicts are
   `sysid/results/noise_ladder.json`, joined in `sysid/results/calibration_routines.json` (shape in type_cards/CONTRACT.md). WHY:
   type_cards is the stdlib spec; a computed number belongs where a test holds it to the code that computes it.
5. **The noise ladder** (`sysid/noise_ladder.json`, pinned by sha256, committed before the first ladder result, a test checks the order):
   0, 1x, 3x and 10x every channel of a world's noise block, one draw, the same seeds scaled, so a level differs from the next only in
   the noise's size; plus 1x with one realistic perturbation where it matters (a late camera, tracker or torque channel; an encoder at its
   quantum; whole-pixel detections). Bounds: 0x a tenth of the tolerance (nearly exact); kx, k tolerances, never wider than not
   calibrating; variants, the tolerance. Tolerances are acceptance.json's, unchanged; the ladder adds three (2 arcmin on a UR gap, the rack's
   T5 gate; CAN 11's sliding Coulomb level; the drift demos' gates).
6. **Failures are findings, not test failures.** `sysid/tests/test_noise_ladder.py` fails on a verdict that is not the ruler's arithmetic,
   a number that is not the code's (fast checks re-run every time; CAN 11 and the arms with `SYSID_LADDER_SLOW=1`), a 1x row that is not
   the committed oracle result, or a row the ruler asked for that nobody ran. A routine that raises is a failed row with its message.
7. **Backlash is graded on every geared joint the oracle has.** CAN 11's gap was already hidden; the UR's joints get a ladder-only
   scenario, `sysid/examples/ur5e_backlash` (a hidden 10 arcmin gap on gear_backlash's UR plant, found by gear_backlash's own gravity
   sweep, both bam_ws main, imported in place). WHY not inside the ur5e examples: that would move every committed ur5e number and the
   site's pages; folding a gap into the arm examples is the next step once a routine recovers all six joints.
8. **Code the oracle cannot import is cited, not graded.** sysid imports bam_ws main only (decision-sysid-oracle-2026-11-05), so the
   clamp test (unmerged gear_backlash branch), the kinematic calibration lane's DH, general transform and IK fine-tune (unmerged
   bam_calibration branch, graded by that lane's own study) and bam_homing's seek (its own environment) carry an `oracle_note` saying so.

## What the ladder found (sysid/results/noise_ladder.json)

Worst |error| over its tolerance among the parameters a routine returned, at each level (✓ within the ladder's bound, ✗ not):

| check | owner | 0x | 1x | 3x | 10x | 1x + perturbation |
|---|---|---|---|---|---|---|
| `pendulum_can11:servo.dynamics_regression` | sysid, matches | 0.165 ✗ | 0.195 ✓ | 0.439 ✓ | raised ✗ | camera_late 0.909 ✓; encoder_quantised 0.203 ✓ |
| `pendulum_can11:servo.backlash_reversals_camera` | sysid, matches | 0.0138 ✓ | 0.215 ✓ | 0.368 ✓ | 13.4 ✗ | camera_late 3.41 ✗; encoder_quantised 0.217 ✓ |
| `pendulum_can11:servo.stock_quasistatic` | bam_ws, mismatch | 12.5 ✗ | 12.5 ✗ | 12.3 ✗ | 12.7 ✗ | camera_late 12.5 ✗; encoder_quantised 12.5 ✗ |
| `pendulum_can11:servo.live_reid_t10` | bam_ws, mismatch | 2.41 ✗ | 2.4 ✗ | 2.43 ✓ | 2.49 ✓ | camera_late 2.4 ✗; encoder_quantised 2.38 ✗ |
| `pendulum_can11:servo.gap_check_forecast` | sysid, matches | n/a | 0.442 ✓ | 1.58 ✓ | raised ✗ | — |
| `ur5e:kinematics.zero_offsets_tracker` | sysid, matches | 2.8e-04 ✓ | 0.27 ✓ | 0.809 ✓ | 2.7 ✓ | torque_late 0.27 ✓ |
| `ur5e:arm.dynamics_excitation` | sysid, matches | 0.0155 ✓ | 0.0448 ✓ | 0.225 ✓ | 3.37 ✗ | torque_late 0.425 ✓ |
| `ur5e_2f85:kinematics.zero_offsets_tracker` | sysid, matches | 3.6e-04 ✓ | 0.0947 ✓ | 0.284 ✓ | 0.947 ✓ | torque_late 0.0947 ✓ |
| `ur5e_2f85:arm.dynamics_excitation` | sysid, matches | 0.0191 ✓ | 0.0421 ✓ | 0.388 ✓ | 4.39 ✗ | torque_late 0.421 ✓ |
| `ur5e_2f85:gripper.drive_traces` | sysid, matches | 9.3e-08 ✓ | 8.6e-05 ✓ | 2.6e-04 ✓ | 8.4e-04 ✓ | torque_late 8.9e-05 ✓ |
| `conveyor:conveyor.radius_tracker` | sysid, matches | 2.8e-04 ✓ | 0.00633 ✓ | 0.0195 ✓ | 0.0658 ✓ | tracker_late 0.725 ✓ |
| `conveyor:conveyor.dynamics_profiles` | sysid, matches | 5.7e-06 ✓ | 8.6e-04 ✓ | 0.00258 ✓ | 0.00859 ✓ | tracker_late 0.0147 ✓ |
| `dual_arm_cell:cell.tags_bundle_adjustment` | sysid, matches | 7.1e-14 ✓ | 0.824 ✓ | 2.48 ✓ | 8.41 ✗ | pixel_integer 0.921 ✓ |
| `dual_arm_cell:camera.pose_recal_belt_tags` | sysid, matches | n/a | 0.148 ✓ | 0.444 ✓ | 1.49 ✗ | pixel_integer 0.38 ✓ |
| `linescan_cell:linescan.geometry_dot_card` | sysid, matches | 3.3e-13 ✓ | 0.869 ✓ | 2.59 ✓ | 8.43 ✗ | pixel_integer 1.6 ✗ |
| `linescan_cell:linescan.radiometry_refs` | sysid, matches | 2.6e-13 ✓ | 0.521 ✓ | 1.56 ✓ | 5.21 ✓ | pixel_integer 0.521 ✓ |
| `linescan_cell:rgbd.dot_card` | sysid, matches | 1.7e-13 ✓ | 0.436 ✓ | 1.36 ✓ | 5.14 ✗ | pixel_integer 0.301 ✓ |
| `ur5e_backlash:arm.backlash_gravity_sweep` | bam_ws, matches | 1.03 ✗ (+2 missing) | 1.23 ✗ (+2 missing) | 1.88 ✗ (+2 missing) | 7.48 ✗ (+2 missing) | encoder_14bit_9to1 1.23 ✗ (+2 missing) |

"n/a": not run at that level, by the ruler (`not_at`, with its reason). "raised": the routine threw; its row records the message.
"+N missing": parameters the routine claims but did not return, which fail the row.

- **A model that lacks a term misses by the same amount at every level.** The stock quasi-static sweeps: CAN 11's damping 12.5
  tolerances off at 0x and at 10x (a negative viscous term, the Stribeck dip their model lacks, fitted under the ki 16000 limit
  cycle). T10's live re-identification: armature 2.4 tolerances at every level (tanh Coulomb against a Stribeck truth). T10's 3x and
  10x passes are the ladder's cap at work: a bound is never wider than not calibrating, and T10 is a little better than the
  nominal's 2.58.
- **A matched model can still be a biased routine.** gear_backlash's UR gravity sweep fits the truth's own gap, yet reads the
  elbow's 10 arcmin as 12.1 with no noise (1.03 tolerances; shoulder lift 0.33) and grows from there (7.5 at 10x); wrist 1 and wrist
  2 are never swept (no pose where gravity beats friction 2.5x: best 0.3x and 2.2x), and the pan and wrist 3 cannot be loaded by
  gravity at all. All six UR gaps need a reversal or clamp routine; both are recorded, neither is in the oracle. CAN 11's regression
  likewise carries 0.165 tolerances on gravity (0.33 %) with no noise, so it misses the 0x bar and passes 1x and 3x.
- **Timing beats noise.** One late sample costs more than three or ten times the noise: the tracker 10 ms late puts the drum radius
  at 0.72 tolerances (10x noise: 0.066); the link camera 10 ms late puts CAN 11's gap at 3.4, a fail (3x noise: 0.37); torque 2 ms
  late puts the UR armature at 0.42 (1x: 0.045). Whole-pixel dot detections fail the line camera's principal point (1.6) at 1x noise.
  The encoders' real quanta cost nothing measurable (AS5047P through CAN 11's 10:1: 0.203 against 0.195; 14 bit through 9:1 on the
  UR sweep: 1.233 against 1.232).
- **Every other routine is exact without noise, then grows with it.** Within 0.02 tolerances at 0x (the camera and tag fits to
  1e-13). The camera and tag fits grow in step with the noise (cell bundle adjustment 0.82, 2.48, 8.41) and sit near one tolerance
  at 1x (bundle adjustment 0.82, line-scan geometry 0.87), so about 1.2x the committed noise breaks them. The UR dynamics grow faster
  than the noise (ur5e's worst 0.045, 0.23, 3.4: x5 at 3x, x75 at 10x): the speed noise sits in the regressor's qdd column, and least squares on a
  noisy regressor is biased by the noise's variance (errors in variables). At 10x those and the cell's camera re-calibration (1.5),
  the RGBD dot card (5.1) and CAN 11's gap (13.4) fail; the conveyor (0.066, 0.0086), the gripper (8e-4), the UR zero offsets (2.7 and
  0.95, inside their 10x bound) and the radiometry (5.2) hold.
- **CAN 11 at 10x raises.** The regression's fitted Stribeck curve is steep enough (55.9 N.m.s/rad) that bam_rack_twin refuses the
  twin (dt x slope / I = 3.8; 1 or more is unstable), so the regression and the gap forecast commissioned from it are failed rows.
- **A drift alarm scaled to the noise floor goes deaf as the noise grows.** The gap forecast recovers the wear rate at 1x (0.44
  tolerances; crossing forecast at 201.6 h against 197.3 h, 77 h ahead) and 3x (1.58), but the servo card's drift ratio is the link
  error over the camera's floor, so at 3x the same wear forecasts its crossing at 605 h and never alarms inside the 480 h horizon.
  A deployed check's sensitivity is then its sensor's noise; a threshold in the gap's own units would not move with it. Not changed
  here.

## How real 1x is

1x is each world.json's noise as committed, not a measured level. Where the rack measured its sensor, the oracle is quieter: CAN 11's link
camera is 0.3 mrad of white noise on every 10 ms sample (0.042 mrad/sqrt(Hz)); bam_rack_twin's stop_camera.py reads one D405 frame of a
station tag at 2 to 11 mrad, at the recorder's 30 fps (0.5 to 2.8 mrad/sqrt(Hz)), so even 10x here is quieter than the rack's camera.
Read a routine's 3x and 10x rows before trusting it on that sensor.

## Consequences

- The site lane renders `/data/sysid/calibration_routines.json` (the site build copies every `sysid/results/*.json`); nothing in `site/`
  changed here.
- `python -m sysid ladder --write` re-runs the ladder (CAN 11 several minutes a level, levels can run in separate processes; the rows
  merge); `python -m sysid routines --write` rebuilds the table. A change to an example's pipeline makes the ladder's 1x rows disagree with
  the oracle's results until both are re-run, by design.
- The pipelines carry perturbation hooks that are off outside the ladder; their committed numbers did not move (sysid/tests/test_oracle.py).

## Alternatives not taken

- **Routines as fields on TestType.** A test type is a capture; several routines read one capture (the same pose set feeds a zero-offset
  fit, a DH fit or a general transform), and cost, equipment and a verdict belong to the method, not the data.
- **Oracle numbers typed into the records.** Stale the moment the code moves; the join is recomputed and tested instead.
- **N seeds per level.** A spread per level, at N times the compute; one draw scaled makes the levels exactly comparable, and each fit's
  own 95 % interval, now kept per model, gives the spread at a level. Worth adding for the routines near a bound.
- **One channel at a time.** Says which sensor limits a routine (the variants do this for timing and quantisation); the scaled-together
  ladder is the like-for-like comparison the brief asked for.
- **A test that every routine passes 0x.** It would forbid recording a biased routine, which is half the point.
- **Building the missing routines here** (single-touch and averaged homing, a dynamometer, AX = XB hand-eye, the clamp and a UR reversal
  test in the oracle). Each is its own lane; each is recorded as "not implemented" or "not graded", with what would bring it in.

## Undo

`git revert` the merge commit. The records, the ruler, the runner, the scenario and the results are additive; the pipelines' hooks are
no-ops outside the ladder.

## Addendum (2026-11-07): the servo's drift alarm in the gap's own units

**Status:** landed on sim2real main (branch `claude/drift-gap-units`). This adopts in sysid the domain-v3 decision
(docs/decision-domain-model-v3-2026-11-07.md, "The drift threshold") and closes this record's last finding ("goes deaf as the noise
grows ... Not changed here"). It goes through the contract slot that landed for it, `servo.gap_drift` / `dm.parameter_drift`, which is
unchanged.

**What changed.**
- `sysid/drift.py` warns when a check's gap, less the commissioned gap, passes the station's allowance (`description.json`
  `monitoring.gap_allowance`). The commissioned gap is M4's, measured by the routine every check runs.
- The forecast is the wear line solved for the commissioned gap plus the allowance. The gap-to-ratio curve (45 twin replays) is gone.
- The fidelity ratio is still computed on every check (`ratio`, `ratio_alarm_h`) but is never the alarm. (Superseded the same day: see **Update** below, the alarm warns on either check.)
- The check needs no twin. At 10x, where the regression raises, the ladder now runs it on the reversals routine's gap.
- The `servo.gap_check_forecast` routine record says how it warns now.

**The allowance: T5's 2 arcmin (0.582 mrad) on a geared station, none on a direct drive.**

| criterion (weight) | **T5, 2 arcmin (chosen)** | the oracle's 10 % (0.20 mrad) | twin-derived (domain-v3's suggestion) |
|---|---|---|---|
| does not move with the camera (must) | yes | yes | no: it scales the commissioned twin's own error (held-out link error 0.57 mrad at 1x, 1.51 at 3x) |
| an acceptance the gap already has (must) | yes: bam_rack_twin `GAP_CI_HALF_ARCMIN`, the UR gaps' ladder tolerance | yes: acceptance.json | no: a new computed number |
| the drift gates still met at 1x (should) | yes, below | no: it crosses at 86 h, and the 48 h forecast misses by 13.7 % (bound 5 %) | yes |

T5 is the rack's unit gate on a geared joint's gap: the gap's 95 % half-width must be at most 2 arcmin. type_cards puts it on the gearbox
card, not the servo card. The twin carries the commissioned gap. Once wear moves the true gap 2 arcmin past that value, the twin's gap is
off by more than the unit was accepted with. `drift.t5_gap_allowance_rad(station)` is the rule. test_drift_gap.py holds the
description's value to the rule, against the live station record and the live constant.

**Measured.** Before is the fidelity ratio's alarm, after is the gap check's, both on the same checks (`ladder pendulum_can11 --levels
1x|3x|10x`, `drift backlash_wear`):

| noise | before: alarm | after: alarm | hidden gap crossed | forecast at 168 h | wear rate (true 1.8e-6 rad/h) |
|---|---|---|---|---|---|
| 1x | 204 h (ratio crossed 197.3) | **300 h** | 292.4 h | 298.4 h (+2.0 %, +6.0 h), plan by 280.4 h | 1.876e-6 (+4.2 %) |
| 3x | never inside 480 h (forecast 605 h) | **360 h** | 359.2 h | 360.3 h (+0.3 %) | 1.516e-6 (−15.8 %), unchanged |
| 10x | not run (the regression raised) | never inside 480 h | never | 878 h | 7.0e-7: 6.1 tolerances, a pass only by the ladder's cap |

- **The forecast check is kept and passes.** At 1x it is +2.0 % against bounds of 5 % and 15 %, and 6.0 h against the one-check
  interval the 5 % was chosen for (now asserted beside it). Lead time is 124 h (gate 48 h).
- **The alarm fires on time at both levels.** At 1x it fires 7.6 h after the hidden crossing, at 3x 0.8 h after (gate: within one
  check). At the alarm the true gap is 0.610 and 0.584 mrad past the commissioned gap, against 0.582. Recalibrated ratio: 0.970 at 1x,
  0.973 at 3x.
- **The expected outcome, "at 3x within about 33 h of the 1x alarm": FAIL.** The 3x alarm is **60 h** after the 1x one (300 h to
  360 h). The check is not the cause. The commissioned gap it counts from is: the reversals routine reads the same 2.000 mrad gap as
  1.957 at 1x (−0.043) and 2.074 at 3x (+0.074). That 0.117 mrad difference is 64.7 h of wear. The 33 h estimate counted only the
  checks' scatter (0.059 mrad rms), not commissioning's error.
- **10x is deaf because its routine is.** The reversals routine reads 4.68 mrad on a 2.0 mrad gap, and the checks follow only 39 % of
  the true growth.
- **At 1x the alarm comes 96 h later than the ratio's did.** The ratio fired at a 0.40 mrad growth (1.4 arcmin), tighter than T5. By
  then the twin is 1.46x its hour-0 fidelity, against the ratio's 1.25.

**Not changed:** acceptance.json's drift gates; the ladder's ruler (its 0x `not_at` reason still names the ratio, though the gap check
could now run at 0x); the site's wear chart. `site/landing.py` `wear_svg` still draws the ratio against 1.25x while its dots take the gap
check's status. A site lane can redraw it as `checks[].gap_growth_rad` against `allowance_rad`.

**What would change this:**
- To make the alarm hour independent of the camera too, count wear from the first deployed check rather than from the twin's gap. That
  alarms on "the gear has worn 2 arcmin", not "the twin's gap is 2 arcmin off".
- To keep the 1x warning at 204 h, warn on either check. The ratio is already computed every check.

**Undo:** `git revert -m 1` the merge commit. That restores the ratio alarm, the curve forecast and the earlier results together.

**Update (2026-11-07, `claude/cleanup-1107`): the servo's alarm warns on either check.** Decided because at 1x the gap check alone comes
96 h after the ratio's. `drift.servo_verdict` warns when the gap check or the fidelity ratio does, and `first_alarm` is the first such
check; each check carries `gap_status`, `ratio_status`, `status` (either) and `warned_by`, the run `detector_alarm_h` (either),
`gap_alarm_h`, `ratio_alarm_h` and `alarm_by`. The forecast, its target (the commissioned gap plus the allowance) and the recalibration's
rule are unchanged; the recalibration now runs at whichever alarm comes first.

| noise | alarm (either) | fired by | gap check alone | ratio alone | hidden gap crossed | recalibrated ratio |
|---|---|---|---|---|---|---|
| 1x | **204 h** | ratio | 300 h | 204 h | 292.4 h | 0.934 |
| 3x | **360 h** | gap | 360 h | never inside 480 h | 359.2 h | 0.973 |
| 10x | never inside 480 h | (no twin, no ratio) | never | not run | never | not run |

- The gap check's own timing check is kept as it was (it warns within one check of the hidden crossing: 7.6 h after at 1x), on
  `gap_alarm_h`. Beside it a separate assertion holds the either-alarm: its hour is the earlier of the two and never later than the gap
  check's. The old assertion could not hold the either-alarm itself: at 1x the alarm now comes 88 h *before* the hidden crossing.
- The forecast checks (+2.0 % at 1x, one check, lead 124 h) and the alarm hours at 3x and 10x are unchanged.
- The site's wear chart plots each check's gap growth against the allowance, with the ratio as the secondary series (its threshold on
  the allowance line) and each dot carrying the alarm status and which check fired it.
- The 0x `not_at` reason names both checks now (the ratio's denominator, the camera's floor, is zero without noise, so the alarm as
  deployed is undefined at 0x). The ruler's digest is re-pinned in test_noise_ladder.py for that text; no bound moved.

**Undo (the update):** `git revert -m 1` its merge commit. That restores the gap-only alarm, the results and the chart together.
