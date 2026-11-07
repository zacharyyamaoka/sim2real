# Decision: domain model v3, one contract before the pages (2026-11-07)

**Status:** accepted on merge (sim2real main: `type_cards/domain.py`, `instances.py`, `selection.py`, `report.py`, `deployments/`,
`frozen_reports/`, `domain_v3.json`; `site/deploy_tree.py` and `site/build.py` write the projections). Decided for Zach by the domain-v3
lane (the barrier the page lanes build against); his to overrule. Contract: `type_cards/CONTRACT.md`, "Domain model v3".

## Context

Zach's feedback of 2026-11-06 (`PROJECT - Sim2Real`, "Feedback on how it is right now") names a domain model: DEPLOYMENTS ("The orcale
examples are also deployments its just they are 'Virtual'"; "Each sub componet of the deployment could basically be its own deployment";
filtered by tags such as "orcale example" or "use a camera"), RUNS ("all runs should be tagged with the current configuration values and also
like if its just natural response or driven"), a MODEL ladder per type ("the 6 DOF robot arm is not a type.. the type here is more generic";
"MO.kinematics.X MO.dynamics.X ... definetily you can use a robot arm without a dynamics model"), ROUTINES both ways, a parameter view in
data-ui with presets and a column group per model, METRICS with the important ones pinned, DIAGNOSTICS ("metrics + gate that reports
warning or error"), per run and "accross all the runs", COVERAGE for "the currently selected runs or run", and REPORTS ("so even as you add
more data etc.. the Reports is a great way to just see an overview fixed").

Several page lanes come next (deployments index, deployment page, run page with an entity tree, models, parameters, metrics, reports).
Built in parallel against a moving model they would each be right and jointly wrong, so one lane freezes the contract first.

What was there: the v2 type cards (`reg.CARDS`, twelve cards whose ids mix types and instances: `arm_6dof`, `arm_6dof_gripper`), the rack's
tree and run tags (`site/deploy_tree.py`), the six oracle examples (`sysid/results`), the routines (`calibration_routines.json`), and no
deployment record for the virtual ones, no families, no pins, no selection computation, no reports.

## Criteria, and the one real fork

How v3 comes into being, scored (weights: high = must, medium = should):

| criterion (weight) | **v3 built from v2 by an explicit map (chosen)** | rewrite the cards as types in place | author v3 beside v2 |
|---|---|---|---|
| nothing that reads v2 breaks: sysid's committed results, the type pages, the site test (high) | yes: v2 untouched | no: card ids sit inside committed oracle results and pages | yes |
| one source of truth per fact (high) | yes: every equation, reference and number is v2's object, carried | yes | no: two ladders drift |
| a reviewer reads what moved in one place (medium) | yes: `CARD_TYPE`, `RUNG_MODELS`, `PARAMETER_MAP`, ... and a test that no parameter is lost | spread over every consumer's diff | no map at all |
| Zach's asks met now (high) | yes | yes, later | yes |

The cost of the chosen option: authoring still happens on the v2 cards and v3 is derived. A later lane can flip authoring to the types
without changing the v3 contract (the map is then the history).

## Decision

1. **Deployment kind: `virtual` | `physical`.** Zach's own words ("virtual or like actuall physical") and the digital-twin literature's
   pair (Grieves: a physical product in real space and its virtual twin). "real" and "sim" were not free: a run's `environment` already
   says `real` (a segment of live deployed data) and its `basis` says `sim`, so either word would mean two things.
2. **Every node of a deployment's tree is a deployment of its own.** No separate sub-deployment record: a node's subtree and runs are its
   page; its children are its sub-deployments; tags are per node (its deployment's declared ones, and those derived from the types in its
   own subtree), so the index filters a sub-deployment the same way. The six oracle examples are virtual deployments (their sysid trees,
   node for node); the registry's are physical (deployment -> fdcanusb adapter -> station -> the station's parts, and the cameras its v3
   record declares, each with the stations it sees).
3. **Eleven generic entity types.** `arm_6dof` and `arm_subassembly` are one `rigid_body_chain` (the sub-assembly's link lengths are the
   chain's `link_geometry`, its offsets the chain's zeros); `arm_6dof_gripper` is a `gripper` (its model was the gripper's: TCP, width,
   force, friction), and an arm-with-gripper node is a structural `assembly`; `driver` is Zach's `foc_controller`. The three cameras stay
   three types (`camera`, `depth_camera`, `hyperspectral_camera`): a pinhole, a stereo depth and a line-scan spectral model are different
   measurement models, and RobotDx's part types are the same three. No type id names an instance.
4. **Model ids `M<k>.<family>.<name>`, families `kinematics`, `dynamics`, `measurement`, k counted per family.** A family is the part of a
   type's model one can use without the rest. Only the types whose v2 rungs mixed families split (the chain, the conveyor, the gripper):
   the chain's kinematics run M0 nominal, M1 zero offsets, M2 geometric with no dynamics term in them. Single-family types keep v2's layer
   numbers, so robotparts' actuator layers still mean the same model here (decision-rung-keys). M6 is always the residual and M7 the
   network. A v2 rung is a combination (one model per family), so `RUNG_MODELS` maps a key to a tuple.
5. **Runs are tagged** `excitation` (driven, free response, mixed, unknown), `closed_loop` and `offline_scope`, from the run's kind as the
   producer's own code says (`RUN_KINDS`, each cited): a swing is driven then released to coast; a heating run holds a fixed current with no
   position loop, then cools with the bridge off. The configuration snapshot is the existing `config_sha256` (and the gains as run).
   `offline_scope` is Zach's caveat as data: judge a model on a closed-loop run only by replaying that run's own config.
6. **Parameters**: values per deployment (true for virtual only, nominal, recovered), one column group per (routine, model) at the oracle's
   own noise, presets all / winning model / with results / errors only. A recovered value is a single `Estimate` (mean, 95 % interval, how);
   configuration-dependent and learned forms are named and refused, so they have a place when they come. Tolerance is per column.
7. **Pinned metrics**: the type's headline performance metric (what the robot's job needs) and its twin-fidelity metric (the README's ruler).
8. **Diagnostics are a metric plus warn and error limits**, RobotDx's diagnostic row; acceptance gates (pass / fail against a target) stay
   their own records.
9. **Selections**: one pure function over any run ids; cross-run values are data-ui's own summaries (median by default) so the browser gets
   the same number; coverage is the type card's own function, and a run x cell table gives the browser the identical count.
10. **Reports**: a Python record (its rows by id) and a snapshot written once with a digest over everything; a page reads the snapshot.
11. **Physical deployments' v3 fields are Python** (`type_cards/deployments/<id>.py`), beside app/registry.json, which keeps the producer
    fields the producer lanes edit; a test holds the two to one set of ids.

## The drift threshold (asked of this lane)

The calibration-routines lane found that the servo's drift alarm, live fidelity ÷ the camera's floor, goes deaf as the camera's noise
grows (CAN 11's gap check: at 1x it alarms at hour 204; at 3x the same wear forecasts its crossing at hour 605 and never alarms inside
480 h). **Decided: yes, the threshold belongs in the gap's own units.** The gap estimate's error grows with the noise but not its mean, so
an alarm on the gap's growth fires at the same gap whatever the camera.

- **Landed here (contained, test first):** `servo.gap_drift`, a drift diagnostic in rad on `backlash_rad` (`units: "parameter"`), and
  `dm.parameter_drift(...)`, its check; the test holds that the same gaps give the same levels whatever the floor, where the ratio form
  stops alarming.
- **Not landed (not contained):** sysid's drift demo alarming on it. It changes the detector the committed drift demo, the noise ladder's
  gap-check rows and the landing page are computed with, needs CAN 11's 30 kHz replays re-run, and needs an allowance per station.
  The allowance should come from the commissioned twin alone, noise-free: the gap at which the twin's replayed link error (no camera noise
  in either replay) grows by the drift threshold over its own commissioned error. Owner: the lane that owns `sysid/drift.py` and the ladder.
- **Estimate, from committed numbers (not run):** the ladder's gap RMS error is 0.019 mrad at 1x and 0.059 mrad at 3x
  (`noise_ladder.json`, `held_out.gap_rms_mrad`), against 0.37 mrad of growth from the commissioned gap to the threshold gap (1.991 to
  2.358 mrad, `drift_backlash_wear.json`) at 1.8 µrad/h; so at 3x a gap alarm would fall within about 33 h (three checks) of the 1x one.
- **Landed since (2026-11-07):** sysid's drift demo and the ladder's gap check now alarm on it, with T5's 2 arcmin as CAN 11's
  allowance rather than the twin-derived one above, and the estimate measured: `docs/decision-calibration-routines-2026-11-07.md`,
  "Addendum".

## Consequences

- The page lanes read `domain_v3.json` and `<site>/data/domain/*` and write only `site/`; a missing field is an additive change in
  `type_cards/`, test first.
- `python3 -m type_cards.domain --write` after any card change (the test fails on a stale projection); `python3 -m type_cards.report freeze
  <id>` only on purpose.
- Today a selection can compute three metrics (tracking, twin fidelity per model, the board's rate) and the servo's coverage; every other
  metric says why not. Recorded coverage reads lower than a plan's own number: the coverage table is ~4 Hz and real motion is not its
  targets (CAN 11's frozen schedule 2f32ddbc: 57.98 % over its 104 recorded runs; the plan's targets visit 71.35 % over all its runs,
  66.15 % over its train split).
- A selection's gate verdict is the gate's target on the selection's median, not bam_rack_twin's acceptance statistic (CAN 11's twin of
  record: 2.44x floor over the frozen schedule's runs here; T2 pools its held-out set its own way and reads 1.39x overall). The acceptance
  verdicts stay gates.json's.

## Alternatives not taken

- **One `Camera` type with three families** (projection, depth, spectral). Closer to a one-word type list, but the families would be
  sensor kinds, not parts one uses without the others; the map makes the fold a local change if Zach wants it.
- **k global across a type's families** (the chain's compliance as M3.dynamics). Keeps v2's numbers, but Zach's own example has an
  M0 in each family.
- **A sub-deployment record** (declared parents). Every node already is one; a second record would be a second tree to keep in step.
- **Cross-run p90 or pooled RMS.** Exact from per-run values only for some metrics, and not a data-ui summary, so the browser could not
  match it live; the median is RobotDx's own cross-run rule for tracking.
- **Moving app/registry.json into Python now.** It is where the producer lanes add archive days; moving it is its own lane.

## What would change this

- Zach wants one Camera type, or a different word than virtual / physical: local edits to `META` / `DEPLOYMENT_KINDS` and the map.
- A page needs per-run arrays in a selection, or a metric no producer writes per run: additive fields and a producer.
- Recovered values for physical deployments (the rack's twins of record): a producer writing them into the same result columns.

## Undo

`git revert` the merge commit. v2 and every v2 consumer are untouched; the site's runs.json loses three columns and OUT/data/domain/.
