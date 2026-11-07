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
   recovery{ "0x"|"1x"|"3x"|"10x": {pass usable worst_error_over_tolerance missing failing parameters checks not_run{check id: why}} }
            (every level the ladder runs, over the checks that ran there; pass null where none ran; {} when not checked. Since
             2026-11-07, the v3 audit's finding 5: 1x and 3x only hid 0x's bias and 10x's breakdown; summary_levels stays the headline)
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

## Domain model v3 — `sim2real.domain/3` (2026-11-07)

Zach's feedback of 2026-11-06 (`PROJECT - Sim2Real`, "Feedback on how it is right now") as one contract: **deployments** (virtual or
physical, tagged, a tree whose every node is a deployment of its own), **runs** (raw data, tagged with their config, driven or free
response, closed loop), generic **entity types**, one **model** ladder per type in **families**, **parameters** (true / nominal /
recovered), **routines** both ways, **metrics** (some pinned), **diagnostics** (a metric plus warning / error limits), **coverage**, and
frozen **reports**. Decision record: `docs/decision-domain-model-v3-2026-11-07.md`. Held by `tests/test_domain_v3.py` (types, models,
migration, diagnostics, run tags, the committed projection), `tests/test_instances.py` (deployments, trees, the parameters table, run tags in
runs.json), `tests/test_selection.py` (metrics, diagnostics, coverage over runs; the browser's rule) and `tests/test_reports.py`.

### Rules of the road (v3)

- **Imports.** `from type_cards import domain as dm` (the type level and every record class), `instances as inst` (deployments, trees,
  the parameters table, the site's projections), `selection as sel` (any runs), `report as rep`. Stdlib only. v2 (`reg`) is unchanged and
  stays the API sysid and the type pages read; v3 is built from it.
- **Records are frozen, keyword-only dataclasses** (Zach's Python ground truth); every JSON file below is a generated projection, never
  edited. Hand-authored instances are Python, one per file: a physical deployment's v3 part in `type_cards/deployments/<id>.py`, a report
  in `type_cards/frozen_reports/<id>.py`.
- **Never parse an id.** A model's `k`, `family` and `name` are fields; order by the type's `models`. A model's global key is
  `"<type>/<model id>"` (`Model.key`): ids repeat across types (`M2.dynamics.coulomb_viscous` is the servo's and the conveyor's).
- **Additive only**, as v2: a field is never renamed or removed; new ones get defaults. A breaking change bumps `dm.SCHEMA`.
- **Unknown stays unknown**: a value nothing establishes is `null` with a `why`, never a guess (a per-unit limit with no unit value gives
  level `unknown`; a run kind nobody wrote gives excitation `unknown`).

### Vocabularies (`dm.*`, and in `domain_v3.json`)

```
DEPLOYMENT_KINDS  virtual | physical
FAMILIES          kinematics | dynamics | measurement          (a family is usable without the others: a chain with no dynamics model)
EXCITATIONS       driven | free response | mixed | unknown
OFFLINE_SCOPES    any config | any feedback gains | its own config | split | unknown
LEVELS            ok | warning | error | unknown                LEVEL_RANK ok 0 < warning 1 < unknown 2 < error 4 (RobotDx, data-ui §35)
AGGREGATES        median | mean | min | max | sum | count        (data-ui's own summaries: the browser computes the same)
TAGS              oracle example (declared) | uses camera | uses arm | uses gripper | uses conveyor | uses servo (derived: TAG_OF_TYPE)
STRUCTURAL        deployment | adapter | station | assembly | mount | tool: the levels that are not a type, each with its Dashboard
ESTIMATE_FORMS    single (in scope) | configuration_dependent | network (reserved: Estimate(form=...) raises)
RUN_KINDS         bam_rack_twin.hardware kind -> (excitation, closed_loop, why): swing and thermal are mixed; thermal is open loop
```

### Entity types, models, parameters (`type_cards/domain_v3.json`, committed; `python3 -m type_cards.domain --write`, `--check`)

`dm.TYPES` (`TYPE_ORDER`): `rigid_body_chain`, `integrated_servo`, `bldc_motor`, `gearbox`, `foc_controller`, `encoder`, `gripper`,
`conveyor`, `camera`, `depth_camera`, `hyperspectral_camera`. Generic, never an instance.

```
EntityType      id title zach group covers families models parameters metrics diagnostics gates(v2 Gate) coverage dashboard members(Part)
                legacy_cards robotdx_part note
Model           id ("M<k>.<family>.<name>") type k family name title kind(physics|residual|learned) parameters (cumulative in its family)
                adds base wear current n_parameters equation references architecture needs robotparts implemented legacy[(card, key)] note
                .key = "<type>/<id>"
ParameterSpec   type name unit family introduced_in models nominal source identified_by observable role wear legacy[(card, name)] note
MetricSpec      id type family(performance|fidelity) title unit defined_on pinned model_dependent aggregate per_run(RunSource|None) why_not
                robotdx normalised acceptance today legacy
RunSource       table(runs|run_diagnostics) column diagnostic per_model divide_by("floor"|"") note
DiagnosticSpec  id type metric title warn(Limit|None) error(Limit|None) kind(threshold|drift) units(metric|ratio|parameter) parameter
                message baseline robotdx note legacy
CoverageSpec    type dimensions[Dimension(name unit headline bin_size binning)] rule gate_pct reachable from_runs why_not
Dashboard       template panels components proposed          Part  type count role
```

`domain_v3.json`: `{schema, note, deployment_kinds, families, excitations, offline_scopes, levels, level_rank, aggregates, tags, tag_of_type,
estimate_forms, structural{word: Dashboard}, run_kinds{kind: {excitation closed_loop offline_scope why}}, entity_types[EntityType with models,
parameters, metrics, diagnostics, pinned, current as id lists], models[Model + key], parameters[ParameterSpec + key, routines[]],
metrics[MetricSpec], diagnostics[DiagnosticSpec], coverage[CoverageSpec], routines[{id title package kind setting status
identifies[{type model parameter}] legacy_identifies}], parameter_routines{type: {parameter: [routine ids]}}, migration{...below}}`.

- **Models by type**: `dm.models(type)` (ladder order: each family in turn, layers rising), `dm.model(type, id)`, `dm.current_models(type)`
  (today's model, one per family), `dm.parameter(type, name)`, `dm.entity_type(type id | v2 card id)`.
- **Families.** Single-family types keep v2's layer numbers (robotparts' actuator layers: the servo is M0, M2, M3, M4 twin, M5, M5 wear,
  M6 residual, M7 network). `rigid_body_chain`, `conveyor` and `gripper` split: the chain's kinematics M0 nominal, M1 zero offsets, M2
  geometric (+ M2 wear: zeros drifting) and dynamics M0 rigid links, M1 compliance (+ M1 wear), M6 residual, M7 network. M6 is always the
  residual and M7 the network.
- **A composite's dynamics are its members'**: a chain's joints are integrated servos with their own ladder (`EntityType.members`).

### Routines both ways

`dm.routine_parameters(routine id)` -> `((type, model, parameter), ...)` (routine -> parameters; the model is the lowest of the
parameter's family holding every parameter the routine claims there); `dm.routines_identifying(type, parameter)` -> v2 `CalibrationRoutine`s
(parameter -> routines); `dm.parameter_routines()` -> `{type: {parameter: [routine ids]}}` over every parameter, `[]` where none;
`dm.fitted_model(routine, type, family)` -> the one model a routine's single fit is. The routines themselves stay v2 records (`reg.ROUTINES`,
`sysid/results/calibration_routines.json`); in JSON: `domain_v3.json` `routines` and `parameter_routines`.

### Metrics, diagnostics, pinned

- `dm.pinned(type)`; `EntityType.metrics` lists the pinned first: the type's headline performance metric(s) and its twin-fidelity metric.
- A metric's per-run value comes from `per_run` (three today: `servo.tracking_rms` = runs.json `tracking_mrad`; `servo.twin_fidelity` =
  run_gates.json `stock.model_error` per model ÷ the station's T1 floor (gates.json); `driver.loop_rate` = runs.json `rate_hz`); every other
  metric has `why_not`. Performance metrics need no model; fidelity metrics are per model (`model` = the producer's label, e.g. "twin of record").
- **Since 2026-11-07 (additive), five:** `RunSource.table` may be `run_metrics`: the rows `tools/run_metrics.py` writes per run to
  `<dep>/run_metrics.json` (`{run device metric robotdx value unit n side why}`, keyed by the metric's own id), RobotDx's catalog entry named by
  the metric's `robotdx` run on the run's npz by RobotDx's rack loader (`servo.stop_error`: the p90 of |q - q_target| over the last 50 ms of
  every dwell of 0.25 s or more followed by motion, the prelude dropped, encoder side: T4's dwell scan; `driver.saturation`: the share of rows,
  in %, the board reports on its torque cap, moteus code 102). A run with no value says why (`why`: "no dwell ..."), and a selection with none
  carries the producer's most common why; where every valued row names one `side`, the selection's entry carries it (`side: "encoder"`: the stop
  error's title says "at the output", T4 calls an encoder-side value partial). The model-independent metrics of the rack's parts no run can give say what is missing (`WHY_NOT`).
- `dm.level(diagnostic, value, limits=None)` -> ok | warning | error | unknown (error checked first; `limits={"warn": v, "error": v}` sets a
  per-unit value). `dm.diagnostic_row(diagnostic, value, subject=...)` -> PEP 0010 §10's row (`subject diagnostic title level rank value unit
  warn_lo warn_hi error_lo error_hi kind message` + extras), which data-ui's gate and threshold views read.
- **A unit's own limits** (2026-11-07, additive): where a diagnostic's limit or a gate's target is set per unit (`Limit.value` None: the
  servo's stop error against the joint's share of the 5 mm tool gate, the board's loop rate against its expected rate less 10 %), the physical
  deployment's record sets it: `PhysicalDeployment.limits`, `UnitLimit(device, diagnostic, warn, error, target, source, note)`, each cited (the
  rack's: bam_rack_twin acceptance.py `STOP_ALLOCATION_MRAD` as warn and T4's target, experiments.py `RATE_HZ` 100 x 0.9 as warn; the test reads
  both from the producer's source). `inst.unit_limits` binds each to the typed node at its device whose type holds the diagnostic (a limit that
  binds none is refused) and deployments.json carries them on the node: `limits` = `[{diagnostic, warn?, error?, target?, source, note?}]`
  (`sel.node_limits(node)` by id, `sel.level_limits(record)` the `{"warn", "error"}` `dm.level` takes). `sel.compute` gives each diagnostic row
  its node's limits and each gate its node's target (`target_value` beside the gate's text). Unknown stays unknown where no unit sets one.
- Drift: v2's ratio checks are `units: "ratio"`. `servo.gap_drift` is `units: "parameter"` on `backlash_rad`: `dm.parameter_drift(d,
  commissioned=, measured=, allowance=)`, the gap's growth in rad against an allowance set per station (decision record, "The drift threshold").

### Deployments and their trees (`<site>/data/domain/deployments.json`, written at site build by `inst.write`)

A dataset of every node of every deployment, in the house table shape (runs.json's): `{name, title, contract, source, schema{fields[{name
type}]}, tree{parent: "parent"}, index, rows}` (types are the robotics contract's words: string, number, integer, boolean, array).

```
row  id root parent depth title kind(virtual|physical) tags[] structural entity_type entity_title card(v2) device sysid_id sees[] runs
     children page source machine where summary dashboard dashboard_panels[] components[] current_models[]
```

- **Index filtered by kind and tags**: rows with `parent == null` (seven today: the six oracle examples, virtual, and the One Dof Test
  Rack, physical); facets on `kind` (values) and `tags` (values on a list). A node's tags: its deployment's declared ones and those derived
  from the types in its own subtree, so a sub-deployment filters the same way.
- **A deployment page, with its sub-deployments**: `inst.subtree(nodes, id)` (the node first) and `inst.sub_deployments(nodes, id)` (its
  children). Every node id is a deployment address (path ids: `one-dof-test-rack/fdcanusb-0607623A/can11`, `ur5e/ur5e/shoulder_pan`).
- **Physical** (`inst.physical_nodes(data)`): app/registry.json's deployments; deployment -> fdcanusb adapter -> station (site/deploy_tree.py's
  ids) -> its parts (the integrated servo's members: motor, driver, gearbox, encoder, labelled from the bam_rack_twin record; a gearbox the
  record calls "none" is absent) and the cameras `type_cards/deployments/<id>.py` declares (each `sees` the stations its tags are on). Parts
  carry their station's `device`. `runs`: the runs whose device is under the node (a camera's: null, it is not known which it filmed).
- **Virtual** (`inst.virtual_nodes(results)`): each oracle example's sysid typed tree, node for node; a v2-typed node gets its v3 type; an
  "arm + gripper" is `structural: assembly` (a chain and a gripper composed); `runs` 0 (sysid does not persist its simulated runs).
  Since 2026-11-07 (the v3 audit's finding 5) also each noise-ladder scenario (`inst.SCENARIOS`, sysid/oracle.py's: `ur5e_backlash`), from
  its committed result (`python -m sysid run <id> --write`; sysid's test holds its values to the ladder's 1x row), tagged `noise-ladder
  scenario`, `page` null (no landing page); its parameter rows are its ladder entries, each on the node its tree gives the key.
- **Producer model labels** (2026-11-07, additive): `PhysicalDeployment.models`, a tuple of `dm.ModelLabel(label type model fit friction
  differs source)`, is which ladder model each model a producer replays is (the words before " vs real" in RobotDx's stock.model_error rows,
  `sel.model_label`). `inst.label_model(deployment, label)` -> the record or None (exact words; a label nobody mapped maps to nothing);
  `<site>/data/domain/model_labels.json` (`inst.model_labels_dataset()`, house table shape: `deployment label type model model_key model_title
  family k fit friction differs source`). Every rack label is the servo's `M4.dynamics.twin` (each a bam_rack_twin TwinParameters hinge with
  the drive's terms); `differs` says where its terms depart from the model's (LuGre in place of M3's form, the board's current ceiling, no
  heat). `tests/test_instances.py` fails on a label the rack's run_gates.json writes that has no entry.

### The run page: entity tree and the standard dashboard per level

- **Tree**: the run's deployment's nodes (`root == run.deployment`), the run's own at `device == run.device` (its station and the station's
  parts), plus every ancestor; cameras whose `sees` holds the run's station are the run's camera level.
- **Dashboard per level**: a typed node's `dashboard` (data-ui gallery template), `dashboard_panels` and `components` (site/components.py:
  `joint-3d`, `joint-render` for an integrated servo; `camera-clip` for a camera); a structural node's from `domain_v3.json structural[word]`.
- **What it shows by default is model-independent** (Zach: "in these dashboards we are seeing like the metrics and diagnostics that are
  independent of the models"): the level's performance metrics and their diagnostics, from the run's selection of one (below); fidelity
  metrics appear per model.

### Runs (tags added to runs.json by site/deploy_tree.py; one row per run, data-ui's robotics contract)

```
v3 columns   excitation(EXCITATIONS) closed_loop(true|false|null) offline_scope(OFFLINE_SCOPES)    (dm.run_tags(kind), per RUN_KINDS)
config ref   config ("full" | "not recorded"), config_sha256 (the board config's key-lines sha256 where full), config_detail, config_code,
             config_plan, kp ki kd ilimit (the gains as run)                                        (already there since 2026-11-05)
```

`offline_scope` is Zach's caveat as data: a model may be judged on a closed-loop run only by replaying it with that run's own config; a free
response under any config. Virtual deployments have no run rows yet.

### The parameters table (`<site>/data/domain/parameters.json`, `inst.parameter_table(nodes, results, routines)`)

```
{name, title, contract, level ("1x": the oracle's own noise), schema{fields}, source,
 result_columns[{id ("<routine>:<model id>"), routine, routine_title, model, entity_type, family, fit, label, properties[]}],
 column_groups{label: [properties]}                        (data-ui §16 columnGroups: "each model ... its own Recovered error tolerance")
 presets{all | winning model | with results | errors only: {filter, columns, what, color_by?}},
 rows[ id deployment node owner entity_type parameter family introduced_in unit winning winning_basis(selected|current) key element true nominal
       nominal_source tolerance_kind tolerance recovered ci95_lo ci95_hi pass method best has_results
       + per result column C: recovered@C ci95_lo@C ci95_hi@C interval@C error@C tolerance@C error_over_tolerance@C within@C ]}
```

- Rows: every value the oracle graded (`<example>/<key>`: the example's own fit in `recovered`, `ci95_*`, `pass`), the 8 only the noise
  ladder grades, and one row per parameter of every typed node no graded value binds (`<node id>#<parameter>`, values null; `nominal`
  null too, the type card's value apart in `type_nominal`: a v2 card's nominal is the instance it was written around, the servo's CAN 11's).
- **Binding is per instance** (2026-11-07, the v3 audit's finding 4: keyed by deployment and type, one measured servo hid every unmeasured
  servo's rows beside it). `node` is where the value sits (the sysid tree's node; a ladder-only value, its deployment's one node of its type,
  else the deployment); `owner` (`inst.owner`) is the typed node it belongs to: `node` when that is of the value's type, else the one node of
  the type in the smallest subtree around `node` that holds one (a joint's zero offset is its chain's `joint_zero_offsets`; the 2F-85 tool's
  mass its arm's, its TCP its gripper's), null when that subtree holds two or more or the tree none (a component that is no node: the dual-arm
  cell's mounts, the line-scan cell's depth camera's colour stream). A value binds `(owner, parameter)` only; a listed row's `owner` is its
  node. So every typed node has each parameter of its type once: values it owns, or one row saying none is recorded, never both.
- **Presets**: all = every row; winning model = `winning == true` (the parameters of the selection rule's pick where the example ran one,
  else the type's current model: `winning_basis`); with results = `has_results == true`; errors only = with results, `error_over_tolerance@*`
  columns, each row coloured by `best` (the column with the least |error over tolerance|).
- `recovered` is a single value with its 95 % interval (`dm.Estimate`); other forms are reserved. Tolerance is per column (today the
  parameter's, the same in every column). Physical deployments' recovered values arrive when a producer writes them (the same columns).

### Metrics, diagnostics and coverage over selected runs (`sel.compute`; presets in `<site>/data/domain/selections/<dep>.json`)

`sel.compute(run_ids, tables, name="")`, pure (sorted, deduplicated ids; one run is a selection of one), over `sel.Tables(nodes, runs,
run_diagnostics, coverage_points, floors, descriptions)` (`sel.load_tables(data, deployment)` reads them):

```
{schema "sim2real.domain/3#selection", name, runs, run_ids, run_ids_sha256, unknown_runs[],
 nodes[{node, device, entity_type, runs,
        metrics[{metric title unit pinned family aggregate model value low high n source why}],      (one per model for fidelity)
        diagnostics[PEP 0010 rows + metric model runs device hint],                                    (units "metric" only: a drift check
        gates[{gate diagnostic metric model verdict(pass|fail|not_run|unknown) value target acceptance statistic why}],  needs its baseline)
        coverage{pct visited reachable samples outside marginals unplanned gate_pct verdict rule why}}]}
```

- A node is in the result when a selected run's device is its own. A gate's verdict here is its target on the selection's aggregate,
  **not** bam_rack_twin's acceptance statistic (gates.json keeps those).
- Coverage is the type card's own function (`cov.actuator_coverage`) over the selected runs' coverage.json points (q made relative to the
  station's origin, degrees to rad) with the station's joint description (its live schedule's): the coverage table is ~4 Hz, so a cell
  crossed between two rows is not counted. Types other than the integrated servo: `why`.
- Presets (`sel.presets(runs)`): all, each split, each station, each day; the file drops `run_ids` (named by `run_ids_sha256` and the rule).

**The browser, live (data-ui), the same numbers:**
1. Per run: the metric's `per_run` column (runs.json) or row (run_gates.json, ÷ the station's T1 floor from gates.json; run_metrics.json since
   2026-11-07). The page reads them as one table, `<site>/data/domain/metric_values/<dep>.json` (`sel.metric_values(tables)`: one row per run,
   typed node at the run's device, metric and model with a finite value, `{run node device entity_type metric model value}`), the projection of
   exactly those sources; `sel.metrics_from_values(rows, run_ids)` is this rule in Python, tested equal to `compute` for every subset of a fixture.
2. Across the selected runs: the metric's `aggregate`, a data-ui summary (§16 `rollup` / `summaries`, median by default) over those values.
3. Level: the diagnostic's limits from `domain_v3.json` on that value, `dm.level`'s rule: error limit first, then warn; no value or no limit
   value is unknown. data-ui draws but does not compute a verdict (§35), so the page's host runs this one comparison.
4. Coverage: `<site>/data/domain/coverage_cells/<dep>.json` `{rule, reachable_cells{device: n}, rows[{run device cell reachable n}]}`: the
   distinct `cell` values of rows whose `run` is selected and `reachable` is true, per device, ÷ `reachable_cells[device]`, as a % to 2
   decimals (`sel.coverage_from_cells`, tested equal to `compute`'s). Since 2026-11-07 (additive) it also holds `grid{device: {axes[{name unit
   edges}], reachable["i,j,k"]}}`, the card's own axes and reachable cells, so a page draws where a joint can go and where a selection went.
5. The page (`/metrics/<dep>/`, `site/metrics_pages.py`, `static/metrics.js`): the runs in play are its runs table's ticked rows, else every row
   its filters leave; the aggregate is data-ui's own `summarize` of the metric's name (median: `Median`; min and max beside it), the distinct count
   `Unique`, and the % is rounded as Python's `round(x, 2)` (ties to even). `site/tests/test_site_flow.py` holds every number to `compute` for
   three selections made in headless Chrome. For `mean` and `sum` (no metric uses them today) data-ui sums in ascending order, `statistics.fmean`
   exactly, so the two may differ in the last bit.

### Reports (`type_cards/frozen_reports/<id>.py` + `<id>.json`; copied to `<site>/data/domain/reports/`)

```
Report    id title question runs[run ids] models["<type>/<model>"] parameters[parameters-table row ids] deployment note
snapshot  {schema "sim2real.domain/3#report", report{...}, frozen_at, code, inputs{runs_sha256 runs},
           results{selection (sel.compute), models[Model], parameters[rows as the table held them]},
           annotations{titles{node id: title}, model_labels{label: {type model model_title} | null}}, digest}
```

`annotations` (2026-11-07, the v3 audit's finding 7) is what the page names beside the numbers, as it was at freeze: the title of the
report's deployment and of every node it computed, and the ladder model each model label in its results named (`rep.model_label_records`:
the deployment's record, `inst.label_model`; null for a label nobody mapped). Read from today's records, renaming a station or remapping a
label changed what a verified report said. A snapshot frozen before it (the first three) has none: its page reads those from today's
records and says so where they show, and claims only what is frozen (re-freezing them would be a new decision with new numbers).

`rep.freeze(report, tables, parameter_rows=, frozen_at=, code=)` is pure; `python3 -m type_cards.report freeze <id>` writes the snapshot
once, `rep.verify(snapshot)` checks its digest (over everything but the digest). A page reads the snapshot and never recomputes it, so a
report does not change as data grows; re-freezing is a new decision and a new commit. The first: `can11-frozen-schedule-2f32ddbc`.

Since 2026-11-07 (additive): a report from a selection, `python3 -m type_cards.report freeze --id <id> --title ... --question ... --deployment
<dep> (--runs a,b | --select col=v[,v] ... | --preset "<name>") [--models ...] [--parameters ...] [--note ...] [--doc ...]`: `rep.select_runs`
names the runs one way (ids; runs.json columns, every one holding one of its values; a `sel.presets` name), refusing a column or preset that is
none and a run id the data does not hold (the whole selection, before anything is written: the v3 audit's finding 9); `rep.definition_text` writes the definition (`frozen_reports/<id with _>.py`, one keyword per line), then it freezes; a report that exists
is never overwritten. A snapshot keeps the rows it froze: `inputs.rows`, each run's `rep.ROW_FIELDS` (covered by the digest). `list` and `verify
<id>` read them. The site shows every report at `/reports/<id>/` (`site/reports_pages.py`); 2026-11-07's: `ident-sessions-1106`,
`otherday-sessions-1107`.

### Migration from v2 (`dm.CARD_TYPE`, `RUNG_MODELS`, `PARAMETER_MAP`, `METRIC_MAP`, `DIAGNOSTIC_MAP`; `domain_v3.json migration`)

| v2 card | v3 type | rung keys | notes |
|---|---|---|---|
| `servo` | `integrated_servo` | M0 ideal, M2 coulomb_viscous, M3 stribeck, M4 twin, M5 electrics, M5.wear -> M5.dynamics.wear, M6, M7 | `M<k>` -> `M<k>.dynamics.<name>` |
| `motor` | `bldc_motor` | M0 ideal, M4 cogging, M5 electrics, M5.wear, M6, M7 | dynamics |
| `gearbox` | `gearbox` | M0 ideal, M3 load_friction, M4 backlash, M4.wear, M6, M7 | dynamics |
| `driver` | `foc_controller` | M0 ideal, M1 delay_loop, M2 ceiling_heat, M2.wear, M6, M7 | dynamics |
| `encoder` | `encoder` | M0 quantiser, M1 noise_latency, M2 eccentricity, M2.wear | measurement |
| `camera_rgb` | `camera` | M0 pinhole, M1 distortion, M2 exposure_latency, M3 rolling_shutter, M3.wear, M6 | measurement |
| `camera_rgbd` | `depth_camera` | M0 stereo, M1 disparity_noise, M2 depth_bias, M2.wear, M6 | measurement |
| `camera_hsi` | `hyperspectral_camera` | M0 bands, M1 band_widths, M2 smile_keystone, M3 pushbroom, M3.wear | measurement |
| `arm_6dof` | `rigid_body_chain` | M0 -> M0.kinematics.nominal; M1 -> M1.kinematics.zero_offsets; M2 -> M2.kinematics.geometric; M3 -> M2.kinematics.geometric + M1.dynamics.compliance; M3.wear -> + M1.dynamics.wear; M6 -> + M6.dynamics.residual; M7 -> M7.dynamics.network | split in two families |
| `arm_subassembly` | `rigid_body_chain` | M0 -> M0.kinematics.nominal; M1 -> M1.kinematics.zero_offsets; M2 -> + M0.dynamics.rigid; M2.wear -> M2.kinematics.wear + M0.dynamics.rigid; M6, M7 | folded in: link_lengths -> link_geometry, joint_offsets -> joint_zero_offsets, joint_offset_drift_rad_per_sqrt_h -> joint_zero_drift_rad_per_sqrt_h; sub.* metrics and diagnostics -> arm.* |
| `arm_6dof_gripper` | `gripper` | M0 -> M0.kinematics.tcp; M1 -> + M0.dynamics.width_drive; M2 -> + M1.dynamics.contact; M2.wear -> + M1.dynamics.wear; M6; M7 | an "arm + gripper" node is an assembly |
| `conveyor` | `conveyor` | M0 -> M0.kinematics.belt + M0.dynamics.rigid_mass; M2..M4 -> M0.kinematics.belt + M<k>.dynamics.*; M4.wear; M6; M7 | split in two families |

`dm.legacy_models(card, key)` (a v2 rung is a combination, one model per family), `dm.legacy_parameter(card, name)` -> `(type, name)`,
`dm.legacy_metric`, `dm.legacy_diagnostic`, `dm.declared_extra(card, key)` (what a combination holds beyond the v2 rung, and why: the
chain's `link_geometry` and `closure_tolerance` are v3's own, ADDED_IN_V3). Metric ids, diagnostic ids and v2 routine ids are unchanged.

### Write set of the page lanes

Read everything above; write pages (`site/`), never `type_cards/` (ask through the coordinator: this is the barrier). A field a page needs
that is missing is an additive change here, with its test first.
