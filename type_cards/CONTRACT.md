# type_cards contract — `sim2real.type_cards/2`

The API the type cards promise to every other lane. Spec: Zach's "Proposed Work Flow Nov 5 2026" in `PROJECT - Sim2Real`
(types, model rungs, black-box metrics → diagnostics → gates, test types, coverage, calibration packages), plus his two additions
of the same day (wear; learned rungs at the top of each ladder). Held by `type_cards/tests/test_contract.py` (the API) and
`type_cards/tests/test_ladders.py` (the content).

## Rules of the road

- **One import.** `sys.path` holds the repo root; then `from type_cards import registry as reg`. Everything below is a name on `reg`
  (the v2 classes live in `type_cards/schema.py` and are re-exported: `reg.Rung is reg.schema.Rung`). Stdlib only.
- **Additive only.** No name, field or field order of v1 or v2 is ever renamed or removed; new fields always get defaults. A
  breaking change would bump `reg.SCHEMA` (none is planned).
- **Never parse a rung key.** Order by the `rungs` tuple; find a rung with `reg.rung(card, key)`. Keys can skip numbers (below).
- **Write set of this lane** (ask through the coordinator before editing): `type_cards/**`, `site/types_pages.py`, the `TYPE` kind in
  `site/catalog.py`, `types_checks` in `site/tests/test_site_flow.py`, `docs/build_report_type_cards*.py`.

## The data

```
Card                       v1: id title group zach robotdx_part robotdx_gap inputs outputs metrics floor model coverage view
                               observability procedure members error_budget
                           v2: rungs: tuple[Rung]  diagnostics: tuple[Diagnostic]  gates: tuple[Gate]  tests: tuple[TestType]
Parameter                  v1: name unit nominal source identified_by observable(yes|partial|no) note
                           v2: wear: Wear | None   role: model | driver | assembly | config   (reg.ROLES)
Rung                       key name parameters references equation kind(physics|residual|learned) architecture base needs
                           robotparts implemented current note
                           .n_parameters (= named + a net's weights)  .n_named  .parameter_names  .wear_parameters
Reference                  title url doi kind note              (every DOI checked against Crossref, every URL fetched: see below)
Wear                       usage unit law(linear|sqrt|archard) rate(the rate parameter's name, in the same rung) note
Architecture               family inputs output history history_dt_s hidden activation n_outputs n_weights
                           .n_inputs (= len(inputs) × history)  .weights (an MLP's computed; others state n_weights)
CoverageNeed               min_pct min_samples extrapolates deployment_weighted_pct note
Metric                     v1 unchanged: family is performance (real vs target) | fidelity (twin vs real); black box, outputs only
Limit                      op(<=|>=) value unit note           .ok(x, value=None)  .text()   value None = set per unit
Diagnostic                 id metric threshold level message kind(threshold|drift) baseline settable forecast robotdx note
Gate                       id diagnostic target acceptance note
Forecast                   usage unit law parameters method
TestType                   id title setting(bench|deployed) identifies how needs recalibration exists duration
CalibrationPackage         id group title serves code status(exists|partial|proposed|unknown) level note references
CodeHome                   repo path ref note
Axis (coverage)            v1: name unit binning   v2: bin_size (constant cell width, else None)  marginal
Coverage                   v1: axes rule measure robotdx plan_source   v2: gate_pct (the coverage gate, % of reachable cells)
                           v3: reachable_mask (the committed mask the measure counts over by default, or None)
CalibrationRoutine         id title package identifies setting wall_time operator_time equipment excitation coverage repeats how
                           kind(identify|measure|use) tests code status(implemented|partial|not implemented) oracle oracle_note
                           alternatives references note   .identifies_parameter(card, name)   (2026-11-07; "Calibration routines")
Identifies                 card rung parameters              (each a parameter of that card's rung, by name)
Quantity                   value unit source note            .estimated   (source: a citation, or ESTIMATE = "estimate")
Equipment                  id title cost(Quantity, USD) note
```

Constants: `SCHEMA`, `KINDS`, `SETTINGS` (`bench`, `deployed`), `ROLES`, `WEAR_LAWS`, `DRIFT_MESSAGE` ("model drift detected —
recalibration required"), `DRIFT_THRESHOLD` (1.25), `OUT_OF_COVERAGE` ("out of coverage"), `TWINNED_LIMIT` (1.5), `SELECTION_RULE`,
`CALIBRATION_PACKAGES`, `WEAR_LAW_REFERENCES`, `STEPS`, `CARDS`, `ORDER`; since 2026-11-07 `ROUTINES`, `EQUIPMENT`, `ROUTINE_SETTINGS`
(`bench`, `deployed`, `both`), `ROUTINE_KINDS`, `ROUTINE_STATUS`, `ESTIMATE`.

## Rung keys — a durable decision

The decision record: `docs/decision-rung-keys-2026-11-05.md` (context, alternatives not taken, undo).

A physics rung's key is `M<k>`, **k = the highest layer of terms it holds** (robotparts' naming spec, PEP 0001: "the rung is the
highest layer captured"). For the actuator types the layers are robotparts' published actuator ladder, so a key means the same
model here and on robotparts.dev: `M0` ideal, `M2` Coulomb + viscous, `M3` Stribeck / LuGre / load-dependent, `M4` ripple +
backlash, `M5` DC-motor electrics. robotparts' `M1` is "the datasheet": M2's terms at their stated values, which here is every
parameter's `nominal` column, so **no actuator ladder has an M1**. The other types number their own layers from `M0` (the nominal
model a robot description gives, nothing fitted). A wear variant is `<key>.wear`. Exactly one rung per card has `current=True`:
it equals the card's `model` (today's single model), parameter for parameter.

What a key means, on every card (the coordinator, 2026-11-05: a reader who learns "M6 = residual" on the servo must not misread
the arm):

- **M0–M5 are physics.** On the actuator cards whose layers robotparts publishes (servo, motor, gearbox, conveyor) they follow
  robotparts' ladder; every other card defines its own M0–M5 (the camera's M1 is Brown-Conrady distortion, the arm's M2 its DH
  errors). Gaps are allowed (the servo has no M1).
- **M6 is always the grey-box residual** (a physics rung plus a small net on what it misses).
- **M7 is always the black-box net** (an actuator network, no named parameters).

`tests/test_ladders.py::test_m6_and_m7_mean_the_same_on_every_card` pins it.

WHY (2026-11-05): bam_rack_twin already calls load-dependent Coulomb "BAM's M3 term" and robotparts' fits are named `M2.twin` …
`M4.twin.backlash`; numbering the sim2real ladder 1, 2, 3 from scratch would make "M3" mean two models across the two catalogs.

## The cards

`reg.ORDER`: gearbox, driver, motor, servo, arm_subassembly, arm_6dof, arm_6dof_gripper, conveyor (actuators); camera_rgb,
camera_rgbd, camera_hsi, encoder (sensors). The conveyor (new, 2026-11-05) is pidtuna's conveyor plant as a card. `reg.V1_CARDS`
holds the cards before their v2 content; `reg.CARDS` (and `reg.SERVO` etc.) are the v2 cards.

## Physics, residual, learned

- **physics**: named parameters; nested (each rung's parameter names contain the rung below's); `n_parameters = len(parameters)`.
- **residual** (grey box): `base` = the physics rung it corrects; its `parameters` are that rung's, plus a small net (`architecture`)
  predicting what it misses (torque or position error) from recent state and command history. `n_parameters` = named + weights.
- **learned** (black box): no named parameters; `architecture` says the family, inputs, history length and size (Hwangbo et al.
  2019's ANYmal actuator net: an MLP over position error and velocity at t, t − 10 ms, t − 20 ms, 3 × 32 softsign, 2,369 weights).
- **Coverage per rung** (`needs`): physics rungs extrapolate and need the type's coverage gate; residual and learned rungs need far
  more data per cell and do **not** extrapolate: they are judged only on held-out data inside their covered cells, and
  `reg.coverage_flag(rung, cell, trained_cells)` returns `OUT_OF_COVERAGE` outside them.

## The selection rule

`reg.select_rung(card | card_id | ladder, held_out, limit=TWINNED_LIMIT) -> Rung | None`: **pick the lowest rung, in ladder order,
whose held-out fidelity reaches the floor** (held-out twin error ÷ the device's own floor ≤ 1.5×, the README's ruler). `held_out`
maps a rung key to a number (× floor) or a `RungScore(ratio, in_coverage, out_of_coverage)`. A residual or learned rung must come as
a `RungScore` judged inside its covered cells (a bare number is refused: `ValueError`); `in_coverage=False` never selects it.

## Wear

A worn parameter carries `Parameter.wear = Wear(usage, unit, law, rate)`: p(u) = p0 + k·u (linear), p0 + k·√u (sqrt), or
p0 + k·Σ(load·distance) (archard). `rate` names the rate parameter, itself a parameter of the same rung. Every actuator type has a
wear rung (`<top physics key>.wear`). `reg.wear_value(p0, rate, usage, law)`, `reg.wear_usage_at(p0, rate, limit, law)`;
`reg.WEAR_LAWS[law]` is the formula and `reg.WEAR_LAW_REFERENCES[law]` its references.

## Metrics, diagnostics, gates

- **Metric**: black box, reads only inputs and outputs (never a model parameter). `performance` = real vs target; `fidelity` = twin vs
  real on the same input. Each is divided by the device's own repeatability floor where one is measurable.
- **Diagnostic** = a metric + a threshold (`Diagnostic.threshold`: the fine side; crossing it raises `level` with `message`).
- **Gate** = a diagnostic + a target (`Gate.target`); `acceptance` names the bam_rack_twin gate (T1-T11) where it is one.
  `reg.gate_status(gate, value, limit=None)` → `pass` | `fail` | `not_run`. A metric no gate reads is **observed**:
  `reg.metric_status(card, metric_id)` → `gated` | `observed`.
- **Model drift**: every card has one `kind="drift"` diagnostic: live fidelity ÷ its calibrated value (the held-out fidelity at
  calibration), threshold `DRIFT_THRESHOLD` (1.25×, settable), message `DRIFT_MESSAGE`. `reg.check_drift(card, live, calibrated,
  threshold=None, history=None) -> DriftResult(status, ratio, threshold, message, remaining, unit)`. With a wear model the
  diagnostic has a `forecast` (usage variable, law, the wear parameters behind it): pass `history=[(usage, ratio), ...]` and
  `remaining` is the usage left (hours, revolutions, …) until the threshold is crossed (`reg.usage_remaining`).

## Test types and settings

`card.tests` / `reg.tests_for(card, setting=None)`: each `TestType` runs in one setting, `bench` (office: the rack or a bench rig) or
`deployed` (in the facility: live data or a short maintenance routine), and lists the parameter names it identifies (each a
parameter of one of the card's rungs). `recalibration=True` marks a method that re-identifies after drift; every type has one per
setting. A run is tagged with its setting (`reg.SETTINGS` keys) and, when it ran one, its test type's `id`.

## Coverage

Each axis has a bin size (`Axis.bin_size`, or `binning` saying why the cells are not uniform) and may be a `marginal`. The coverage
gate is `Coverage.gate_pct`: a plan passes when it visits ≥ that % of the reachable headline cells (`reg.coverage_gate(card, result)`
→ `pass` | `fail` | `observed`). It is a histogram over the binned space; `cov.random_plan(axes, n, seed)` samples the full continuous
space. `cov.servo_coverage` stays byte for byte what main 61a9de7 computes (CAN 11 train 66.15 %, digest pinned in the tests).

**Reachable cells** (the denominator) are per type: the servo's are computed (`cov.joint_reachable`: the joint can hold the cell's
centre and brake before its range ends); the cameras', driver's and conveyor's are every cell; the arm's are a committed mask per
mount, `type_cards/arm_reachable/<mount>.json` (`cov.ARM_MOUNTS`: `ur5e_floor`, `ur5e_2f85_floor`; `cov.arm_reachable_cells(mount)`
→ a frozenset of cell index tuples). A joint-cube cell is reachable when a collision-free configuration of the mounted arm lies
in it (MuJoCo's collision check on the description's collision geoms, 5 cm over a floor at the base, 1 cm clear of itself) with
the shoulder lift in the span connected to home; `tools/arm_reachable.py` writes it from a fixed per-cell Sobol probe and
`sysid/tests/test_arm_reachable_mask.py` holds the file to a fresh run. Both UR5e mounts hold **2,560 of 4,096** cells. The
arm_6dof card's measure is `cov.arm_6dof_coverage(points, mount="ur5e_floor")`, the gripper card's `cov.arm_gripper_coverage`
(`ur5e_2f85_floor`); `cov.arm_coverage(points, limits, mount=None)` without a mount still counts every cell of the box (the
sub-assembly's). The gate stays 40 % on every card: on the arm that is 1,024 reachable cells (it was 1,639 of the box, 64 % of
what a floor-mounted arm can reach). Decision record: `docs/decision-arm-reachable-coverage-2026-11-05.md`.

## Calibration packages

`reg.CALIBRATION_PACKAGES` (filled by `type_cards/calibration.py`) / `reg.packages_for(card)`: Zach's packages (hand-eye, kinematic
length, servo dynamic at arm and actuator level, camera RGB / RGBD / HSI / line-area scan, PID, hardstop / homing / rezeroing), each
with the cards it serves and where its code lives today (`CodeHome`, every path checked to exist at its ref), or `unknown`.

## Calibration routines

Zach, 2026-11-07 (via the coordinator): "Any error is caused by errors in our model: the fidelity of the models and the accuracy of the
parameters ... what are the methods we have to calibrate those parameters". A package (`CALIBRATION_PACKAGES`) is his grouping; a
**Calibration Routine** ("Routine", his name the same day) is one way to run one (`reg.ROUTINES`, filled by `type_cards/calibration.py`),
the record two ways to find the same parameter are compared by. Decision record: `docs/decision-calibration-routines-2026-11-07.md`.

- **What it identifies**: `identifies`, a tuple of `Identifies(card, rung, parameters)`, each name a parameter of that rung (`kind="use"`
  routines, the IK fine-tune and PID tuning, identify nothing; `kind="measure"` is a gauge, the rack's camera dwell stop ruler).
- **Both directions**: routine -> parameters is `routine.identifies` (`routine.identifies_parameter(card, name)`); parameter -> routines
  is `reg.routines_identifying(card, parameter)`, and `reg.parameter_routines()` is the whole index, `{card: {parameter: [routine ids]}}`
  over every parameter of every ladder (`[]` where nothing reaches it yet).
- **Where, how long, what it costs**: `setting` is `bench`, `deployed` or `both`; `wall_time` (the whole routine, set-up included) and
  `operator_time` (a person's hands-on share) are `Quantity(value, "s", source)`; `equipment` names `reg.EQUIPMENT` ids, each item a cost in
  USD with its source; `reg.equipment_cost(routine)` is their sum, its source naming each item's. Every number's `source` is a citation (a
  file, a datasheet, a committed result) or the literal `"estimate"`.
- **What it needs**: `excitation`, `coverage`, `repeats` (how many times its measurement is taken, averaged or checked), and `tests` (the
  `TestType` ids whose data it uses).
- **Where it lives**: `code` (`CodeHome`s, checked to exist at their ref; `/home/bam/sim2real` means this repo) and `status`:
  `implemented` (the code exists, on a main or at the `ref` an unmerged branch names), `partial` (it exists for another robot or without
  its last step) or `not implemented` (no code at all).
- **Its oracle verdict**: `oracle` names the sysid noise-ladder checks that run its code against a hidden truth (`"<example>:<routine>"`,
  declared in `sysid/noise_ladder.json`); `oracle_note` says why there is none. The numbers are sysid's, never typed here (below).
- **Alternatives**: `alternatives` names the routines that find the same parameters another way; they name it back.
- `reg.routine(id)`, `reg.routines_for(card | card_id | package_id)`; `reg.export()` adds `routines` (each with its `equipment_cost`),
  `equipment`, `parameter_routines`, `routine_settings`, `routine_kinds`, `routine_status`.

### The table the site reads: `sysid/results/calibration_routines.json`

Written by `python -m sysid routines --write` (`sysid/routines.py`: a pure join of `reg.ROUTINES` with the committed ladder) and held to
that join by `sysid/tests/test_noise_ladder.py`; the site build serves it at `/data/sysid/calibration_routines.json` (it copies every
`sysid/results/*.json` byte for byte). Schema `sysid.calibration_routines/1`, both directions:

```
{schema, generated_from{records, ladder, ruler{path, sha256}}, levels["0x","1x","3x","10x"], variants{...}, summary_levels["1x","3x"],
 columns[{key, what}],
 rows[ routine -> parameters, one per routine, in reg.ROUTINES order:
   routine title package kind setting status
   wall_time{value unit source note}  operator_time{...}  equipment_cost{value unit source note}
   equipment[{id title cost{value unit source note}}]
   identifies[{card rung parameters[]}]  parameters_covered (the count)
   excitation coverage repeats how tests[] code[{repo path ref note}] alternatives[] references[titles] note
   recovery{ "1x"|"3x": {pass usable worst_error_over_tolerance missing parameters} }   (over every check; absent when not checked)
   oracle{ status: "checked"|"not checked", note,
           checks[{ id example owner(sysid|bam_ws) structure(matches|mismatch: why) parameters[keys] unclaimed{key: why} not_at{level: why}
                    realism verdict(one line)
                    levels{ "0x"|"1x"|"3x"|"10x"|"1x+<variant>": {pass usable worst_error_over_tolerance within_tolerance("k/n")
                                                                parameters failing[keys] missing[keys] held_out{name: value}
                                                                notes[text]} } }] } ],
 parameters[ parameter -> routines and models, one per (example, key) the ladder grades:
   example key unit true nominal tolerance{kind value}
   card rung card_parameter            (the type card's parameter it is)
   routines[ids]                       (reg.routines_identifying(card, card_parameter): every routine that can identify it)
   checks[ids]                         (the ladder checks that graded it)
   models[ one column group per model: { model ("<routine> · <fit>"), routine, check, fit ("fit", or CAN 11's rung "M0".."M4"),
             rung, graded (the routine's own claim),
             levels{ "<level>"|"1x+<variant>": { recovered{mean ci95[lo, hi]|null interval(how, or why none)} error error_over_tolerance
                                                 within_tolerance pass bound } } } ] ],
 parameter_routines{card: {parameter: [routine ids]}} }
```

`worst_error_over_tolerance` is the worst |recovered − true| ÷ the tolerance over the parameters the routine returned (1.0 = at the
use's limit), `missing` the claimed parameters it returned nothing for (each fails; a routine that raised has every one missing and its
message in `notes`); `pass` is the ruler's level bound (a tenth of the tolerance at 0x, k × it at kx, never wider than not calibrating),
`usable` the tolerance itself. `recovered.mean` is the routine's estimate (its fit) and `ci95` the routine's own 95 % interval (a bootstrap
or the fit's Jacobian; `interval` says which, or why there is none). The rows behind every cell, per parameter, are
`sysid/results/noise_ladder.json` (schema `sysid.noise_ladder_result/1`: `checks[{id example routine owner structure parameters unclaimed
not_at realism provenance rows[{level scale variant pass usable worst_error_over_tolerance graded_model models held_out notes provenance
parameters[{key card rung card_parameter unit true nominal tolerance{kind value} bound recovered ci95 error error_over_tolerance pass
within_tolerance models[{model rung graded recovered{mean ci95 interval} error error_over_tolerance within_tolerance pass}]}]}]}]`); a
row's own `worst_error_over_tolerance` is None when any claimed value is missing.

## Lookups and export

- `reg.card_for(word)`: the card a robot description's word names (card id, title, Zach's word, RobotDx part type, or an alias).
- `reg.rungs(card)`, `reg.rung(card, key)`, `reg.current_rung(card)`, `reg.added(card, key)` (what a rung adds over the one below).
- `reg.export()`: the whole registry as JSON (`schema`, `settings`, `kinds`, `roles`, `wear_laws`, `drift_message`,
  `drift_threshold`, `out_of_coverage`, `twinned_limit`, `selection_rule`, `steps`, `cards`, `calibration_packages`); a card adds
  `metric_status`; a rung adds `n_parameters`, `n_named`, `parameter_names`; an architecture adds `n_inputs`, `weights`.

## References

Every `Reference` is real. `type_cards/check_references.py` resolves each DOI at Crossref (the title must match) and fetches each
URL (it must answer 2xx/3xx after redirects); the results are committed in `type_cards/references_checked.json` and the offline
test holds every reference to them. A work with no stable URL is cited without one.

## For lane B (system-ID oracle examples)

Robot description in, better model out: `card_for` each part, take its ladder, simulate data from a high rung at known parameter
values (the "truth"), fit each lower rung, and score held-out fidelity per rung; `select_rung` names the winner and
`check_drift` the deployed check. Wear rungs take a usage input (`Wear.usage`), so a simulated backlash or friction growth can be
recovered and forecast (`usage_remaining`).

## For lane C (deployment tree and run tags)

Type a tree node with `card_for`; tag a run with its `setting` and test type `id`; on deployed runs, `check_drift(card, live,
calibrated)` gives the warning in Zach's words, and with a usage history the usage remaining.
