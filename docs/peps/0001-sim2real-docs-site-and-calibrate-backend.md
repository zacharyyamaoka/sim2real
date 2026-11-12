# PEP 0001 — sim2real docs site and the calibrate() back end

- **Status:** accepted (designer, 2026-11-12), building in three lanes
- **Base:** branch `claude/docs-site-base` on sim2real `main` @ 63789ed
- **Asked by:** Zach, 2026-11-11 (docs site like robotmsgs.com, auto-ordered `calibrate()`, `CalibrationConfig`, an ArUco Marker type,
  the camera tuned for ArUco) and 2026-11-12 (reply 2: the routine kinds, collect vs fit, sim2real as the outer layer)
- **Frozen contract:** `tests/test_calibration_contract.py` (green on the base), plus the red acceptance tests each lane must turn green:
  `tests/test_calibration_backend.py`, `tests/test_aruco_marker.py`, `tests/test_docs_site.py`, and the merge gate
  `tests/test_docs_site_merged.py`. No builder edits any of them.

## Verdict

`twin.calibrate()` stops running a hand-written routine tuple. It picks models per part, gets their parameters, chooses the catalog
routines that identify those parameters (a minimal cover, picked by measured recovery at the deployment's noise level, then time and
equipment cost), and orders them from what each routine declares it needs: `requires`, `uses` and `refines`. A frozen
`CalibrationConfig` steers the whole run, and the run returns one stable record (`sim2real.calibration/1`). The ArUco Marker becomes a
generic type with three routines of its own, plus one new camera routine that tunes exposure, gain and FPS for corner accuracy. A docs
site in robotmsgs.com's shape documents all of it from the same registries. It keeps the two tables Zach liked.

## 1. Layering (Zach, 2026-11-12, reply 2)

> "sim2real should really be like at the outer stack ... a nice API that sits on top of everything below it ... That makes it very easy
> to do the 1 click .calibrate()"

- **The planner lives in sim2real** (`src/sim2real/calibration/`), on the outer side of the layer rule: like `twin.py` and `rig.py`, no
  layer folder imports it. It may call anything below it later, such as the PID tuner, so one-click `calibrate()` can run a tune
  routine that needs a controller.
- **Model and parameter declarations stay low and routine-free.** The new marker model module (`models/aruco_marker.py`) imports no
  routine code and nothing from `cards`, per `tests/test_layers.py`. So when Zach's RobotModels / RobotTwin package
  (`robot_msgs -> robot_models -> robot_descriptions -> robot_parts`) is extracted, the types, models and parameters lift out unchanged.
  Routines that need controllers stay in sim2real.
- **The extraction itself is NOT this PEP.** It moves package boundaries that three live peer lanes import from. It gets its own PEP once
  this lands.

## 2. Routine kinds: configure → fit → tune → measure

`cards/schema.py` (frozen by the contract test):

- `ROUTINE_KINDS` gains `"tune"`. A tune routine optimizes a metric where there is no real reference to match, such as PID gains, or a
  camera's exposure, gain and FPS for ArUco accuracy. It writes the settings it picks in `configures`.
- `KIND_STAGE = ("configure", "identify", "tune", "measure", "use")`. This is the order two routines run in when nothing declared
  orders them. `"identify"` is the catalog's existing word for **fit**, kept so that no id and no export changes.
  `KIND_WORDS["identify"] == "fit"` is what pages print.
- **A declared `requires` always beats the stage.** Example: the camera's ArUco tuning (a tune routine) runs before the bundle
  adjustment (a fit) that requires its exposure.
- Follow-up, not done here: re-kind `pid.pidtuna` (`use`) and `camera.exposure_for_task` (`configure`) as `tune`. Changing an existing
  value needs its own decision (cards/CONTRACT.md: additive only).

## 3. A routine is collect + fit

> "for deployment stuff to separate the data collection routine and then fitting which just works on any type of data"

The seam already splits each routine into `runs(values)`, which says what to record, and `fit(measured, values, twin)`, which says what
to compute. This PEP makes the split usable on its own:

- `sim2real.calibration.collect(twin, config=None) -> CalibrationData`. It plans, then plays every planned routine's runs once through
  the backend's `measure`. It returns `{run_id: measured}` plus the plan.
- `twin.calibrate(data=CalibrationData)` fits from recorded data and never calls `measure`.
  - A planned run missing from `data` is refused, naming the run.
  - This is the deployment path: log in the field, fit anywhere.

## 4. Dependencies and the automatic order

`CalibrationRoutine` gains three additive fields, all tuples of parameter or setting **names**. Each name is resolved over the
instances the routine runs on.

| field | meaning | edge |
|---|---|---|
| `requires` | must be identified or configured before this routine runs | hard; a cycle is refused |
| `uses` | read if an earlier routine found it, else the prior serves | soft; tie-break only, ignored where it contradicts a hard edge |
| `refines` | another routine sets it provisionally (`adjusts`, or a configure that writes it); this one finds it | hard: after every routine that sets it |

**Why three kinds and not one.** This was measured on the UR wrist's six routines. With a single "reads" edge the wrist is a cycle: the
backlash reversal reads the breakaway prior for its cap, and the breakaway reads the backlash. What the code needs is a hard edge, a soft
edge and a refinement.

**Order algorithm** (`sim2real.calibration.order`):
1. Build the hard graph from `requires` and `refines`, using stdlib `graphlib.TopologicalSorter`.
2. Among the routines that are ready at each step, take the one ranked first by this key:
   - no unplaced soft predecessor (a `uses` edge);
   - then its `KIND_STAGE` index;
   - then wall time;
   - then id.
3. If the hard graph has a cycle, raise `CalibrationCycleError(ValueError)`. The message names every routine on the cycle and the key on
   each edge.

Declarations come from the catalog by routine id. An object's own `requires`, `uses` and `refines` attributes override them, for custom
routines.

**The ruler.** The wrist's hand order as it actually ran is backlash reversal → breakaway → homing → dynamics → gravity direction →
delay scan (`src/sim2real/data/ur_wrist_one_click_2026-11-11.json`). The order must reproduce it from the declarations already
committed on the base (`cards/calibration.py`), in all 720 input orders. Requirements outside the plan are listed in `plan.assumed` at
their prior, never silently.

## 5. Selection: models → parameters → routines

- **Per-type options, declared by the part's designer** (black-box design). `sim2real.calibration.options(type_id) -> TypeOptions(type,
  models, routines, setup)`.
  - `models[0]` is today's model, followed by the alternatives in the ladder.
  - `routines` are the catalog routines that identify the type's parameters, preferred first.
  - `setup` holds the configure and tune routines the type always wants: camera → `camera.exposure_lock`; aruco_marker →
    `camera.exposure_for_aruco`.
  - It is derived from `cards/domain.py`, with explicit per-type overrides in one dict in `options.py`. There is no second registry.
- **Picking models per part:** `CalibrationConfig.models={instance: model_id}`, or `select({instance: (type, model_id)})`. Picking a
  model yields the parameters it holds, cumulative within its family.
- **Routine set:** `select()` returns
  - `routines`, a minimal cover: drop any one and something only it covered goes uncovered;
  - `setup`, which is never part of the cover;
  - `covers`, `why`, `dropped` (with reasons: not implemented, outside the budget, known, excluded) and `uncovered`;
  - `parameters`.
- **The metric between alternatives:**
  1. recovery at `config.level` (default `1x`), read only through `sim2real.calibration.recovery`, the ONE reader shared with the site;
  2. then wall time plus operator time;
  3. then equipment $;
  4. then bench vs deployed, per `config.budget.settings`.
  - Unimplemented routines are never selected.
- **`plan(twin_or_picked, config=None) -> CalibrationPlan`** answers "what would `calibrate()` run, in what order" without running
  anything. The site and a part designer use it.

## 6. CalibrationConfig: dependency injection

A frozen dataclass with a JSON round trip, the pattern `NoiseModel` already uses:

| field | what it does |
|---|---|
| `models` | `{instance: model id}` |
| `known` | `{key: value}`: fixed; their routines are dropped with "known" |
| `exclude`, `include` | routine ids out / in |
| `order` | an explicit order; refused if it breaks a `requires` |
| `level` | which noise level the metric reads |
| `noise` | refused if also passed as `calibrate(noise=)` |
| `budget` | `Budget(settings, max_wall_time_s, max_equipment_usd)` |
| `strict` | over budget → refuse instead of dropping |
| `seed` | |
| `routines` | per-routine options, via `.with_routine(id, **options)` |
| `custom` | injected routine objects; they replace the rig's implementation of a registered id, and an unregistered id is refused |

Per-routine options reach a **copy** of the routine. Unknown option names raise `KeyError`.

## 7. What calibrate() returns: `sim2real.calibration/1`

The fixture `tests/fixtures/calibration_record_v1.json` is the schema: the wrist's real run in the new shape.

- **Record keys:** `schema, twin, backend, model, written, seconds, noise, plan, parameters, routines, passed, failing, evaluation`.
- **Per parameter:** `key, instance, name, unit, nominal, value, ci95, true, error, tolerance, pass, routine, method, why_not`.
- **Per routine run:** `routine, identifies, runs, seconds, found`.
- **Per plan step:** `routine, title, kind, setting, identifies, requires, uses, refines, after, why_here, wall_time_s, operator_time_s,
  equipment_usd, recovery, source`.

A fitted twin carries `plan_` (a `CalibrationPlan`) and `record_` (a `CalibrationRecord`) beside today's `values_`, `intervals_`,
`rungs_` and `calibration_`. `CalibrationRecord.from_rig(...)` converts today's `RigCalibration` without losing a row. `docs/CALIBRATE.md`
documents every key; the site renders it as "What calibrate() returns".

## 8. The ArUco Marker generic type

The instance is **one printed sticker** carrying one or more markers rigidly, with its layout from CAD (a five-bar strip, a plate, a
single tag). The v2 card is `aruco_marker`, group `"target"`: a thing a sensor reads, neither driven nor sensing. Its v3 type is
`aruco_marker` in the kinematics family, appended to `ORDER` / `TYPE_ORDER`.

| model | adds | identified by |
|---|---|---|
| `M0.kinematics.nominal` | dictionary, marker_ids, marker_length_m, layout_m, pose_on_link (CAD) | the CAD bundle (cad2robot) |
| `M1.kinematics.as_built` | as_built_offset (6-DOF in the sticker frame) | aruco.bundle_adjustment |
| `M2.kinematics.print_scale` ★ today's model | print_scale | aruco.caliper_size, aruco.bundle_adjustment |
| `M3.kinematics.curl` | flatness_m | nothing yet (listed uncovered) |

The routines:

| routine | kind | runs | needs first | code |
|---|---|---|---|---|
| `aruco.id_confirm`: every expected id found, flag missing / duplicate / unexpected ids and the dictionary actually printed | fit (identifies dictionary, marker_ids) | both | uses exposure | `fit/aruco.py confirm_ids` |
| `aruco.caliper_size`: an operator calipers the 100 mm ruler bar or a marker side, n readings, gives print_scale ± CI and in/out of a 0.5 % print tolerance | fit | both; new equipment `caliper` | — | `fit/aruco.py caliper_scale` |
| `aruco.bundle_adjustment`: camera + as-built sticker poses + print scale + joint offsets against the encoders, CAD as prior, robust loss, one gauge sticker held at CAD | fit | deployed | requires marker_ids, exposure; uses print_scale | `fit/aruco.py bundle_adjust` (numpy LM, `fit/least_squares.py`; the maths of bam_rack_twin `calib.py` / `fivebar_asbuilt.py`) |
| `camera.exposure_for_aruco` | tune (configures exposure, gain, fps on camera_rgb and camera_rgbd) | both | requires marker_ids; refines exposure, gain | `schedule/aruco_exposure.py tune` |

**Hidden truth, owned by the test, not the builder** (`tests/test_aruco_marker.py`):

- **Bundle adjustment.**
  - *Scene:* one fixed D435-like camera; a 2 × 4 gauge plate held at CAD; a free 2 × 3 plate; a 5-marker strip on a link turning
    ±50° over 30 views.
  - *Hidden errors:* camera 2.7 mm / 0.7°; stickers 1.5–2.0 mm and 0.5–1.2°; print scale 1.004 and 0.98493 (the L2 strip's); joint zero
    1.5°.
  - *Graded:* on corner positions in the base frame, because from one fixed camera a moving sticker and its joint zero trade exactly, and
    a static sticker's depth trades with its print scale.
  - *Tolerances:* corners 2 mm (Zach's manual-diagnosis line), camera 1.5 mm / 0.2°, print scale 0.2 %.
  - *Expected margin:* linearized at 1x (0.5 px corners, with the caliper prior), the corner 1σ is ≤ 0.7 mm. So 1x passes and 3x is
    expected to fail.
  - *Honesty check:* without the caliper, the static plate's scale must be reported prior-held, and the turning strip's scale measured.
- **Caliper.** True scale 0.98493; 5 readings of a 100 mm bar at 0.03 mm operator σ (1x). The test requires 0.05 % at 1x.
- **ID confirmation.** OpenCV-rendered tags with noise: a duplicate, a stranger and two missing ids are flagged exactly. A sheet printed
  in DICT_5X5_50 is named as such.
- **Each routine's 0x / 1x / 3x / 10x ladder** is written by its test into `sysid/results/routine_ladders/<id>.json` (written with
  `SIM2REAL_WRITE_LADDERS=1`, compared otherwise). The one recovery reader serves it to the planner and the site.

## 9. The camera tuned for ArUco accuracy

**Objective:** true corner accuracy, not mean grey (the `d435_exposure` band) and not markers read (`task.aruco_score`).

**Hidden-truth renderer** (in the test):
- a 2 × 2 DICT_4X4_50 board at 0.40 m, 320 × 240 pixels;
- photons from scene light × exposure, Poisson shot noise, 3 e⁻ read noise × gain, 8-bit clipping;
- motion blur from a constant-speed back-and-forth path.

**The oracle** scores every candidate (exposure 2–133 ms × gain 1/4/16 × 6/15/30 fps, with exposure ≤ 1/fps) by the true mean corner
error. A missed marker counts 5 px.

**What the designer's prototype measured (2026-11-12).** The prototype was a board-PnP residual + miss penalty + estimated blur length
(image speed × exposure).

| scene | best (true error) | house rule pick (markers read) | prototype pick |
|---|---|---|---|
| static dim | 33 ms / g1, 0.404 px | 2 ms / g4, 0.674 px | 33 ms, 0.414 px |
| static dark | 133 ms / g1 / 6 fps, 0.398 px | 8 ms / g4, 0.779 px | 133 ms / 6 fps, 0.398 px |
| moving bright (400 px/s) | 2 ms / g1, 0.509 px | 2 ms, 0.511 px | 4 ms, 0.544 px |
| moving dim (60 px/s) | 8 ms / g1, 0.414 px | 2 ms, 0.665 px | 8 ms, 0.551 px |

So the bar is passable:
- static picks within 1.15× + 0.02 px of the oracle;
- moving picks within 1.30× + 0.05 px;
- in both low-light scenes, at most 0.8× the house rule's error;
- in the dark, an exposure of at least 66 ms with FPS ≤ 15. This matches the rack's own 2026-11-10 finding
  (`bam_rack_twin.hardware.fivebar_run.D435_STILL_LOOK`: 6 fps).

The lock itself stays `bam_camera_calibration` (`camera.exposure_lock`); this routine runs after it and refines exposure and gain.

## 10. The docs site

**Reuse decision: copy and adapt robotmsgs.com's generator, pin its CSS and JS.**
- `robot_msgs/website/build/*` cannot be imported as a library: `pages.py` loads its own `model.py`, which imports robot_msgs.
- Its `site.css` and `site.js` are fully generic. They are pinned byte for byte to robot_msgs commit `b4c8d36` in
  `website/site/PINNED.json` (commit, path, sha256), with a small `sim2real.css` accent override.
- `highlight.py` and `serve.py` are copied as is.
- `shell` / `sidebar_html` / `code_block` / `heading` / `inline` are copied and given brand, nav and footer parameters.
- `model.py` is new, over sim2real's registries.
- The old catalog app (`site/`, about 7.1k lines) is left alone. Nothing here deletes it.

**Layout:** `website/build/{build.py, model.py, pages.py, highlight.py, serve.py}`, `website/site/`, `website/examples/`.
- Build with `website/build/build.py --out <dir>`; the default is `website/dist/`, which is gitignored.
- It never writes a tracked file, and the test holds it to that.

**Information architecture.** Every page has one h1, `main` and `nav`, and appears in the sitemap.

| path | content | from |
|---|---|---|
| `/` | what sim2real is, the `calibrate()` tour, section links; sidebar Types group in `TYPE_ORDER` | README, examples |
| `/types/<type>/` | what it is; **model-rung table(s)** `table[data-table=rungs]` per family, columns `Rung, Model, Parameters, Adds, Identified by`, rows `data-model`, `data-current` + "today's model"; **routines table** `table[data-table=routines]` | `cards/domain.py` |
| `/models/<type>/<model>/` | equation, parameters, adds, identified by | `dm.model` |
| `/parameters/<type>/<name>/` | unit (`data-field=unit`), the routines that identify it, or "no routine identifies it yet" | `dm.routines_identifying` |
| `/routines/` and `/routines/<id>/` | the whole catalog table; per routine `table[data-table=routine]` with `Identifies, Kind, Runs, Status, Time, Operator time, Equipment, Equipment $, Requires, Uses, Refines`, and `table[data-table=recovery]` with a row per level | `cards/calibration.py`, `sim2real.calibration.recovery` |
| `/examples/` and `/examples/<name>/` | the snippet `website/examples/<name>.py` verbatim, and its real output `website/examples/<name>.out.json` (stamped with the snippet's sha256; stale is red) as a parameter table | `pendulum_can11`, `ur_wrist_test_rig`; the five-bar once its rig is on the seam |
| `/api/` | RobotTwin, calibrate, eval, plan, collect, CalibrationConfig, CalibrationPlan, CalibrationRecord, generated from docstrings, anchors `api-<Name>` / `api-<Name>-<method>` | introspection (robotmsgs' `split_doc` / `render_signature`) |
| `/docs/guide/`, `/docs/calibrate/` | `docs/API.md`, `docs/CALIBRATE.md` | markdown |

The routines table columns are `Routine, Kind, Runs, Status, Time, Operator time, Equipment $, Recovery 0x, Recovery 1x, Recovery 3x,
Recovery 10x, Needs first`.
- Each recovery cell is `td[data-level]` with `data-ratio` (worst error ÷ tolerance) and `data-pass`.
- A routine nobody graded reads "not graded"; unknown stays unknown.

Deployment (a Cloudflare Worker like robotmsgs) is a follow-up. It needs Zach's pick of a domain, and publishing a private repo's
contents is his call.

## 11. Lanes

Each lane is cut from `claude/docs-site-base` into `/home/bam/sim2real-worktrees/docs-site-<lane>`. Write sets are disjoint.

| lane | branch | owns | must turn green |
|---|---|---|---|
| backend | `claude/docs-site-backend` | `src/sim2real/calibration/{plan,config,record,options,collect}.py` + exports, `docs/CALIBRATE.md`; the minimal hook in `src/sim2real/twin.py` (`calibrate(..., config=None, data=None)`, `plan_`, `record_`) and `src/sim2real/rig.py` (`RigRunner.calibrate(..., routines=None, measured=None)`) | `tests/test_calibration_backend.py` |
| aruco | `claude/docs-site-aruco` | `cards/{registry,ladders,domain,calibration}.py` + `domain_v3.json`, `models/aruco_marker.py`, `models/camera.py`, `fit/aruco.py`, `schedule/aruco_exposure.py`, `sysid/results/routine_ladders/*.json` | `tests/test_aruco_marker.py`, `type_cards/tests/test_ladders.py::test_zachs_types_plus_the_conveyor` |
| site | `claude/docs-site-site` | `website/**` | `tests/test_docs_site.py` |

- `twin.py` and `rig.py` belong to the live one-click lane. The backend lane touches only the named hook and rebases onto `main` before
  landing.
- `cards/calibration.py` belongs to aruco alone. Its `requires` / `uses` / `refines` on the wrist routines are already on the base.
- **Merge order:** backend, then aruco, then site. After all three: `tests/test_docs_site_merged.py`, and the site lane regenerates its
  example outputs as `sim2real.calibration/1` records.

## 12. Baseline

On `main` @ 7fac172 these 8 tests already fail, before this PEP, and are unchanged by it:
- `type_cards/tests/test_instances.py::test_the_racks_limits_are_the_producers_own_numbers`
- `test_ladders.py::{test_the_servos_gates_are_bam_rack_twins_acceptance_limits, test_the_servos_coverage_gate_is_schedule_pys}`
- `sysid/tests/test_noise_ladder.py::test_every_claimed_parameter_has_a_tolerance_and_a_truth` and four
  `test_the_fast_checks_are_this_code[...]`

Lanes must not add to that list.

## 13. Deliberately not done

- the RobotModels package extraction (§1);
- re-kinding existing routines (§2);
- a robotparts → sim2real code link: robotparts' `docs/sim2real-types.md` is still "pending mapping";
- deploying the site;
- any hardware run;
- a hidden-truth sim for motion blur inside the MuJoCo twin. The renderer here is the test's own.
