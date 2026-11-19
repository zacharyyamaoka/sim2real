# sim2real public API

A `RobotTwin` is a digital twin for an electromechanical device. You build one, simulate it, calibrate it and evaluate it. The calibrated values come back on a new twin.

```python
import sim2real

twin = sim2real.RobotTwin.from_robot_description(rd)   # or the fixture: sim2real.examples.pendulum_can11()
twin.simulate()
fitted = twin.calibrate(on="sim")
print(fitted.evaluate().summary())                     # eval() is its alias
fitted.parameters                                      # the calibrated Values; writing them into a description is not built yet
```

- **Every line runs today.** `rd` is a robot's description; the first is `bam_rack_twin.description.station_description(11)` (CAN 11's pendulum: its record, its twin of record, its robotparts parts), whose twin equals `pendulum_can11()` value for value (`tests/test_from_robot_description.py`). `docs/api_example.py` runs the fixture's lines; `reports/sim2real-api-2026-11-11.html` shows their real output.
- **Run it from a REPL or notebook, or inside `if __name__ == "__main__":` in a script.** `calibrate()` replays runs in a process pool whose workers re-import your main module. A bare script would run again inside every worker, and Python refuses that with a `RuntimeError`.
- **The slow call** is `calibrate(on="sim")`: about 15–27 min on the CAN 11 oracle, because the rack twin replays at 30 kHz.

## The design principle: every robot description comes with a twin

```
robot_msgs  →  robot_models  →  robot_parts  →  robot_descriptions        sim2real (outside all of it)
 (Value …)     (types, rungs)   (one SKU, its    (composition: parts,     RobotTwin.from_robot_description(rd),
                                 nominal values)  units, fitted values)    calibrate(), evaluate()
```

- **The order since 2026-11-16** (Zach; the 2026-11-12 ruling put sim2real on top, "it really depends on kinda everything"). The 2026-11-11 order, robot_msgs ← sim2real ← robot_description, is superseded (`docs/decision-types-seam-2026-11-11.md`, addenda 2 and 3, kept as history). Every robot description should still come with a twin: Zach, 2026-11-11, "the whole point of robotics is to like actually do something in reality! We are making this first class".
- **The twin is built from the description: `RobotTwin.from_robot_description(rd)` (2026-11-17).** Its public noun is still `RobotTwin`. The 2026-11-11 plan was the other way round, `description.to_robot_twin()`, because sim2real then sat below robot_description and could not import it; since the 2026-11-12 and 2026-11-16 rulings sim2real sits on top of everything, so the twin owns the conversion. It still imports no description package: it reads `rd` by attribute (`name`, `title`, `model`, `source`, `record` = the unit, `components` with `id`, `title`, `type`, `parent`, `parameters`, `binds`, `part`) and binds the calibration world by the unit. A design-only `RobotDescription` (bam_robot_descriptions: geometry, no unit, no typed priors) is refused by name. The description stays bare-bones: it only holds the information.
- **MuJoCo is the `sim` extra** (`sim2real[sim]`), purely for install size.
- **No cycle.** sim2real reads a description by attribute and imports neither a description package nor robotparts.

## Concepts

- **RobotTwin.** A digital twin for an electromechanical device. It holds typed instances, the model rung each one runs, and each parameter as a robot_msgs `Value`. Its verbs are `simulate`, `calibrate` and `eval`. A fitted twin is a new object; the twin you started from never changes.
- **Instance** (`sim2real.twin.Instance`). One component of the twin: an id, a sim2real type id (or none, for a structural node like a deployment), a parent, and `parameters: {name: Value}`. `on_type` says, for each parameter, whether the type's contract names it. A parameter the contract lacks is carried and flagged, never dropped.
- **Type** (`sim2real.cards`). sim2real's generic kinds of part: `integrated_servo`, `gearbox`, `bldc_motor`, `encoder`, `depth_camera` and the rest. Each card lists the type's parameters and units, its model ladder (`M0` ideal … `M7`), its calibration routines and its gates. No manufacturer appears here; robotparts maps a part to a type.
- **Value** (`robot_msgs.space.Value`). A float that remembers where it came from: `unit`, `low`/`high`, `basis` (`assumed`, `datasheet`, `measured` …), `source`, `measured_by` and `notes`. Priors are `assumed`. A calibrated value is `measured`, its 95 % interval is in `low`/`high`, and its source reads `sim2real calibrate · on=sim · <rung> · <date>`. An interval that doesn't bracket the fitted value stays in `notes`, because `Value` refuses such a `low`/`high`. On CAN 11 that's the two friction values polished by output error after the regression that gave their interval.
- **Runner** (`twin.runner`). The level below the verbs, and the one to drop to. `SimRunner` is the pendulum tracer: plan → measure → its routines in the planned order (each sealed from the truth) → score. `RigRunner` (`sim2real.rig`) runs a rig's routine sequence. A rig opts in by shipping `rig.py`. The guards (sealed truth, held-out only) live in the runner, never in a callback.
- **Calibration** (`fitted.calibration_`). What the fit found: each parameter's nominal, hidden truth (sim only), recovered value, interval, tolerance and verdict. `.summary()`, `.passed`, `.failing`, `.to_dict()`.
- **Report** (`fitted.evaluate()`). Held-out fidelity: each model's error ÷ the floor (the run-to-run spread you can't beat) and the gates. `TwinReport` for the tracer, `RigReport` for a rig. Both have `.summary()`, `.passed`, `.gates` and `.to_dict()`.
- **Gate** (`sim2real.twin.Gate`). One pass/fail rule on a report: `id`, `title`, `value`, `rule`, `passed`, `source` (where the limit comes from) and `violations`. Examples: `twinned` (error ≤ 1.5× floor), `held_out_link_fidelity` and `recovery` (every hidden value within tolerance; sim only).

## Calls

### `sim2real.examples.pendulum_can11(*, models=None, workers=6) -> RobotTwin`

- **What it is:** CAN 11 on the One Dof Test Rack, swung as a pendulum. It has seven typed instances, and the servo's eight parameters are priors set apart from a hidden truth (`sysid/examples/pendulum_can11/world.json`).
- **`models`:** picks the servo's rung, for example `{"can11": "M3.dynamics.stribeck"}`. The default is the type's current model, `M4.dynamics.twin`.
- **`workers`:** the size of the replay pool.
- **Never:** writes anything or touches hardware.
- **Raises:** nothing of its own. A missing manifest surfaces as the adapter's error.

### `sim2real.examples.ur_wrist_test_rig(*, workers=6) -> RobotTwin`

- **What it is:** the UR wrist test rig on the one-click seam. Its rig.py supplies three servos, a routine sequence and the rig's measured noise (`docs/one-click-seam.md`).

The examples are fixtures, not a registry. sim2real can't load a robot from a name string.

### `sim2real.RobotTwin(instances, *, name, model_file=None, models=None, title="", source="", workers=6)`

- **What it does:** builds a twin directly from its `Instance`s.
- **`name`:** binds the runner. `calibrate()` plays the `sysid/examples/<name>` world, through its `rig.py` when it ships one.
- **`model_file`:** the MJCF that `simulate()` opens.
- **`models`:** `{instance_id: model_id}`. An instance it leaves out runs its type's current model.
- **Never:** writes anything or touches hardware.
- **Raises:**
  - `NotImplementedError` when `models=` is given for a rig, since the rig's twin is its own rig.py's;
  - `NotImplementedError` when a non-rig twin doesn't have exactly one `integrated_servo` (the tracer calibrates one servo).

### `twin.parameters -> {instance: {name: Value | None}}`

- **What it is:** every instance's parameter Values.
- **On a loaded twin:** the priors.
- **On a fitted twin:** the calibrated values, plus the priors (with their own source) for whatever nothing fitted.
- **Each call returns a new dict,** so editing it changes nothing. Use `with_values` instead.
- **`None`** means the description states no prior. It is never a made-up number.

### `twin.with_values({instance: {name: Value}}) -> RobotTwin`

- **What it does:** a functional update. It returns a new, unfitted twin with those parameters replaced and everything else carried over. The original twin is unchanged.
- **Raises:** `KeyError` for a parameter or instance the twin doesn't carry. It never adds one.
- **Note:** the tracer's sim pipeline reads its priors from the manifest, so `calibrate()` on a twin with edited priors raises `NotImplementedError` and names the edited keys, rather than fitting a twin nobody asked for.

### `twin.simulate(*, seconds=2.0, offset_rad=0.3, rate_hz=200.0, viewer=False) -> Simulation`

- **What it does:** runs the model in MuJoCo, headless unless `viewer=True`. The joint is released `offset_rad` off its gravity bottom with no command.
- **Returns:** `.trajectory`, a robot_msgs `JointTrajectory`, and `.summary()`.
- **Needs:** the `sim` extra.
- **Never:** writes anything or touches hardware.
- **Not built yet:** a rig's twin (`RigRunner` has no `simulate`).

### `twin.generate_schedule(config=None) -> CalibrationSchedule`

- **What it does:** the schedule `calibrate()` will play, without running anything (`sim2real.calibration.plan(twin, config)`; its
  aliases `generate_schedule(twin)` and the old class name `CalibrationPlan` stay). Zach, Daily Note 2026-11-17: "internall mabye that
  does .generate_schedule() -> CalibrationSchedule".
- **What it holds:** the steps in run order, and on a twin that ships its routines each step's runs at the priors (each a
  `sim2real.rig.Run` with a typed robot_msgs command, `JointTrajectory` or `JointCommandSequence`, or none) and whether its commands are
  known now, made after an earlier step runs, or it is fit only. `.runs` (known now), `.previews` (made after), `.summary()`,
  `.to_dict()["schedule"]`. See docs/CALIBRATE.md, "The schedule".
- **Never:** plays anything. It calls each routine's `runs()` twice at the priors (to bind, and to check it is static).
- **Raises:** `CalibrationPlanError` for `runs()` that change between two calls, one run id bound to two different runs or given two
  known lengths, or a run id with a command or a spec that a known-now and a made-after step share.
- **Totals:** `totals["wall_time_s"]` counts a run its steps share once (each step's own time plus each run's known length once) and
  `totals["run_time_s"]` is that run time; the budget compares against it. See docs/CALIBRATE.md, "The schedule".

### `twin.calibrate(on="sim", *, truth="sealed", move_truth=None, noise=None, config=None, data=None, transport=None, callbacks=None) -> RobotTwin`

- **What it does:** returns a NEW, fitted twin. It plays the routines on the simulator against a hidden truth that the fit never sees, in the order their declarations give (`sim2real.calibration.plan`; docs/CALIBRATE.md).
- **The learned values end in `_`** (scikit-learn's convention): `values_`, `intervals_`, `rungs_` and `calibration_`. `fitted.parameters` carries them as Values.
- **`plan_` and `record_`**: `plan_` is the `CalibrationSchedule` that ran (the one `twin.generate_schedule()` and `plan(twin)` show; a known-now step that plays other runs than it showed is refused by name), and `record_` is the run as one `sim2real.calibration/1` record (`record_.to_dict()`; add eval's gates with `record_.with_evaluation(fitted.eval().to_dict())`). The pendulum tracer plays the routines its example ships (`sysid/examples/pendulum_can11/routines.py`: `servo.backlash_reversals_camera`, then `servo.dynamics_regression`, each a step of its pipeline) since 2026-11-17.
- **`config=CalibrationConfig(...)`:** steers the run: models per part, known values, excluded or included routines, an explicit order, the noise level the metric reads, the budget, per-routine options and injected routines. On the pendulum tracer it picks, orders and excludes routines; `known`, `models`, `noise` and `seed` are refused there for now. `Budget(equipment=(...))` is the equipment you have or can use (borrowed counts): a routine needing an item it does not list is dropped, naming the item and its $ (on a rig's own routines too), an id `cards/calibration.py` EQUIPMENT does not hold is refused, and `max_equipment_usd` caps only what is still to buy (`plan_.totals["equipment_to_buy_usd"]`). On the catalog path a fit graded failing at `config.level` is never planned ("recovery at <level> fails"); a rig's own routines are not gated on another implementation's grade. Including a routine a gate drops is refused. See docs/CALIBRATE.md, "Picking".
- **`data=collect(twin)`:** fits recorded runs and never calls the backend's measure. This is the deployment path: collect in the field, fit anywhere.
- **`data_`** (gap D): every fitted twin holds the runs it was fitted on, a `CalibrationData`: all of `data` when it was given, else the very recordings its fit read, one key per run (`data_.answering(run_id)` names the keys that answer a run id). On the pendulum tracer the held-out runs and their repeat draws are held apart (`data_.held_out`); on `on="real"` the held-out and floor runs are, and `data_.meta["files"]` names the file each run was read from. A runner that hands back no measurements leaves it `None`.
- **Refit and grow:** `fitted.calibrate(data=fitted.data_)` refits without measuring and gets the same values: every generation starts from the description's priors. Datasets grow by session, `fitted.data_ + more` (or `.extend(more)`): a session already held is kept once, a run recorded again on another day is kept beside the first as `<key>@<session>`, answering the same run id, and two datasets that claim one session with different runs are refused. `calibrate(data=)` works on a rig and on the pendulum tracer's sim path (its world is never played), and `on="real", data=` refits held rack runs with no transport, emit or play.
- **`move_truth={key: value}`:** moves hidden values for one run while the ruler stays put. It's the mutation test: a moved truth must turn red.
- **`noise`:** rigs only. `None` is the rig's measured 1×, a number scales every term, or pass a `sim2real.rig.NoiseModel`.
- **`on="real", transport=...`** (the pendulum tracer, `sim2real.real`): plans the same schedule plus its five floor repeats, writes them as a rack submission, lets the transport play it, reads the runs back through `tools/run_files.py` and fits them through the routines `plan(twin)` shows, in the same loop the sim plays, each sealed (a planned run the submission cannot fill is refused before emit). `fitted.plan_` is that plan and the record's plan source is `"planner"`. `RackTransport(out)` is a dry run that raises `RunsPending` with the session command; `RackTransport(out, execute=True, adapter=...)` starts the rack's session runner only when every refusal check passes; `TwinTransport()` plays it on the rack twin at the sealed hidden truth. The record is `backend: "real"`; on hardware its rows are ungraded and eval's gates (T1 floor, T2 twinned, held-out fidelity) judge the twin. See docs/CALIBRATE.md, "on='real'".
- **`callbacks=[...]`** (gap E, since 2026-11-18; Keras's `fit(callbacks=)`): told the schedule, each step as its fit finishes, the fitted twin and, through `fitted.callbacks_`, `evaluate()`'s gates. `sim2real.calibration.Ledger()` keeps a local ledger (events.jsonl, schedule.json, calibration.json, eval.json; one folder per calibration); `sim2real.tracking.calibrate_wandb.WandbLogger(ledger)` copies it to W&B, live. `None` reads `SIM2REAL_TRACK` (`off` | `ledger` | `wandb`; unset: nothing on the sim or on a refit from held rack runs, a ledger beside the submission on a fresh rack calibration); `callbacks=[]` wins over everything. A callback never changes or stops the fit: one that raises is detached with a `RuntimeWarning`. See docs/CALIBRATE.md, "Watching a calibration".
- **Never:** writes anything on `on="sim"` unless given a callback (or `SIM2REAL_TRACK=ledger|wandb`). On `on="real"` it writes the submission its transport is given a folder for and, by default, the calibration's ledger beside it (`<submission>/calibrate/<stamp>/`; `SIM2REAL_TRACK=off` writes none), and it never touches hardware itself: a transport plays (`RackTransport` hands the plan to the rack's own session runner, and only with `execute=True`).
- **Raises:**
  - `ValueError` for an unknown `on` or for `truth` other than `"sealed"`, and for a `SIM2REAL_TRACK` other than `off`, `ledger` or `wandb` (it names the three); `TypeError` for `callbacks` that is not a list or tuple;
  - `TypeError` for `on="real"` without a transport (it names `RackTransport` and `TwinTransport`); `RunsPending`, `RackRefused` and `IngestError` from `sim2real.real` on the rack path;
  - `NotImplementedError` for `noise=` on the tracer;
  - `KeyError` for a `move_truth` key the world doesn't have;
  - `ValueError` for noise given both as `noise=` and in `config.noise`;
  - `KeyError` for a per-routine option the routine doesn't have;
  - `CalibrationPlanError` for an unregistered custom routine, an explicit order that breaks a requirement, a strict budget exceeded, or `data` missing a planned run;
  - `CalibrationCycleError` when the routines' declared needs form a cycle;
  - `NotImplementedError` for a `CalibrationConfig` with `known`, `models`, `noise` or `seed` on the tracer;
  - for `data=`: `TypeError` for anything but a `CalibrationData`; `ValueError` for another twin's runs, for rack runs on `on="sim"` (it names `on='real'`) or sim draws on `on="real"`, for `move_truth` with `data=`, and for `transport=` with `data=`.

### `RobotTwin.from_robot_description(rd, *, models=None, workers=6) -> RobotTwin`

- **What it does:** builds the twin from a robot's description: its typed components with their priors (robot_msgs Values), its model file and its unit. The calibration world is the one built for that unit (the sysid example whose manifest `record` names the same deployment file and component).
- **First description:** `bam_rack_twin.description.station_description(11)`; its twin is `pendulum_can11()` value for value.
- **Raises:**
  - `TypeError` for a design-only `RobotDescription` (it names no unit and no typed priors), and for a prior that is a bare number instead of a Value;
  - `ValueError` for a type that is no sim2real type, repeated component ids, or a parent that is no component;
  - `LookupError` when no calibration world was built for the unit.

### `fitted.evaluate() -> TwinReport | RigReport` (alias `fitted.eval()`)

- **What it does:** scores the fitted twin on held-out runs only and returns error ÷ floor and the gates.
- **Reports** to the callbacks its calibration kept (`fitted.callbacks_`, `()` by default): a `Ledger` appends an `evaluate` line and writes eval.json in that calibration's folder. A twin built without `callbacks_` reports to none.
- **Never:** touches hardware, or writes anything but its callbacks' ledger.
- **Raises:**
  - `RuntimeError` on an unfitted twin;
  - `ValueError` when a run it would score was used for training. It refuses rather than filtering it out.
- **Renamed:** this was `eval_twin()` until 2026-11-11, and `eval()` until 2026-11-17 (Zach's sketch `twin.evaluate()`; Keras' `model.evaluate()`; PyTorch's `.eval()` means inference mode). `eval()` stays as its alias.

### `sim2real.preflight(fitted, *, soak_s=6.0, workers=1) -> Preflight`

- **What it does:** step 8 of Zach's 2026-11-19 pipeline, "preflight / wear-in before shipping". It checks a fitted twin before its values ship, in sim only. It returns a frozen `Preflight`: `.checks`, each a `Check(id, title, passed, value, limit, unit, why)`; `.passed`, true when every blocking check is `True`; `.summary()`; and `.to_dict()`, which is JSON-ready. A check's `passed` is `None` when it could not be checked, and `why` says why. `None` never counts as a pass.
- **The checks:**
  - `record_matches_description`: every value carries a unit and a source; every key the schedule (`plan_`) identifies has a fitted value in the record (`record_`); and the record names this twin, with the description's units.
  - `gains_within_board_limits`: the kp, kd and ki the twin would ship. These come from a tune step's `settings_` and `proposals_` if one ran. Otherwise they come from the description's kp/kd priors, and failing those from the board as it runs today (the description's joint plus the unit's deployment record). The gains must lie inside the board's as-found gains × pidtuna's admissible range (`pidtuna.types.Envelope`, 0.25–2×). The loop must be PD only: ki 0, or ilimit 0.
  - `torque_margin`: the peak torque over the soak, and over the fit's recorded runs when it holds them, must stay under the motor's datasheet peak × the gear ratio × 0.97. These come from the twin's robotparts parts (`dist/site/v2/parts/<id>.json`). A gearbox whose own peak is lower sets the cap instead. The check reports the margin in %.
  - `sim_soak`: a `robot_trajectories.burn_in_wiggle`, then a 1.5 s hold, played on the rack twin at the fitted values, under the gains it would ship and the fitted feed-forward. It fails on NaN, on a runner guard trip (travel, overspeed, the proven window), or if the joint has not settled by the end of the hold. It also fails if the stop error exceeds the unit's `servo.stop_error.dx` gate (cards deployments), or on a torque-cap hit (the house cap, or the board's current ceiling).
  - `schedule_complete` (informational, never blocks): passes when nothing the record needed was dropped, left uncovered or assumed by `plan_`. When a routine was dropped only because `Budget.equipment` lacks its kit, the result is `None` and names the missing items.
- **Runs:** in bam_rack_twin's venv, like `pendulum_can11()`. `workers` caps the soak's replay pool. CAN 11 takes about 3 s.
- **Never:** touches hardware, or writes anything except the rack twin's scene cache.
- **Raises:** `RuntimeError` on an unfitted twin, with the same wording `evaluate()` uses.
- **Today on CAN 11:** a fit with no tune step ships the board's as-found gains, ki 16000 with ilimit 0.5. That integrator fails both the gains check and the soak: stop error 0.51°, and 3.4 N·m against the board's 2.93 N·m ceiling. A tune's PD passes every blocking check (`tests/test_preflight.py`). The tune lands with gap C (`claude/l10-c`).

### `sim2real.calibration.Ledger(root=None, *, beside_submission=False)`

- **What it is:** a calibration's local ledger, a callback (gap E). Each calibration it hears opens a new folder under `root`
  (`<UTC stamp>-<twin id>`; `root` None: `$SIM2REAL_CALIBRATIONS`, else `~/.local/share/sim2real/calibrations`, read when the calibration
  begins): `events.jsonl` (every event, appended and fsynced as it happens), `schedule.json`, `calibration.json` (the record, rewritten
  with eval's gates) and `eval.json`. SI throughout. `beside_submission` (a rack calibration's default) opens it under
  `<submission>/calibrate/` once emit has written the submission. `ledger.folder` is the latest calibration's folder,
  `ledger.folder_of(calibration_id)` any one's.
- **Events:** `sim2real.calibration.EVENTS_SCHEMA` (`sim2real.calibration-events/1`), kinds `schedule`, `collect`, `step`, `done`,
  `evaluate`, `error`, `pending`, `callback_error`. See docs/CALIBRATE.md, "Watching a calibration".
- **`sim2real.calibration.Callback`:** the hooks as no-ops (subclassing is optional: hooks are looked up by name).
- **`sim2real.calibration.resolve_callbacks(callbacks, *, backend="sim")`:** what `calibrate()` reports to: a list as given, else
  `SIM2REAL_TRACK`'s. Writes nothing and never imports wandb.

### `sim2real.tracking.calibrate_wandb.WandbLogger(ledger, *, project=None, entity=..., wandb_dir=None)`

- **What it is:** the live W&B copy of a `Ledger` (gap E): one run per calibration (`job_type` `calibrate`), the rows `records(folder)`
  rebuilds from the ledger alone, angles in degrees. It requires the ledger it copies; listed without it (or before it), `calibrate()` puts that ledger right before it; its run opens once the ledger holds the calibration's folder, and a ledger that raises is detached together with it, so W&B never holds a row no local file has. `project` None: the twin's deployment's
  (app/registry.json) or rig's (`tracking.rigs.RIGS`) project; a twin with neither logs nowhere. A W&B that will not start costs one
  warning (the calibration detaches it) and no retry.
- **Also there:** `records(folder)` (the run, rebuilt from the files), `row(event)` (one history row, pure), `project_for(twin_id)`,
  `follow(folder, *, project=None, idle_s=600, poll_s=2)` and the CLI `python -m sim2real.tracking.calibrate_wandb --follow FOLDER |
  --sync FOLDER... | --all [--dry-run] | --show FOLDER`.
- **Needs:** the `tracking` extra (wandb), imported only when it talks to W&B.

### `sim2real.calibration.FeedforwardBench(*, space, poses, grid, drives, gravity_keys, regressor, first=None, inertial=None, prior_sigma=None, tolerance_nm=0.10, delta_nm=0.05, max_rounds=4, per_round=None, dwell_s=0.3, moving_rad_s=0.1, pair_tol_rad=0.05, patience=2, min_improvement=0.10)`

- **What it is:** the routine `arm.feedforward_bench` (since 2026-11-18): a rig hands it to its runner, and `calibrate()` plays its runs and
  its fit. It fits an arm's gravity (theta, linear in the twin's `regressor(q) -> (N, J, P)`) and each drive's Coulomb (`frictionloss_nm`)
  and net viscous (`damping_nm_s_rad`) friction. `identifies` is `gravity_keys` plus those two keys per drive, and so is `commands_read`:
  its feedforward channel is made from them, so the schedule shows its commands made after any earlier step that finds one of them.
- **`runs(values)`:** round 1: one run `…/r1/e{i}-{j}/v{f}` per cell of `first` (an edge of the `poses` graph at a speed fraction), each ONE
  `robot_trajectories.trapezoidal_velocity(..., back_to_start=True)` call in `Run.command`, its cell in `Run.spec["cell"]`, its
  `channels["feedforward_effort"]` made from `values`.
- **`fit(measured, values, twin)`:** `{key: Estimate}` from `sim2real.fit.feedforward.fit` (below); each fit is kept in `fits_`.
  `measured` is keyed by recording: a run a grown dataset holds twice, `X` and `X@<session>`, is read as run `X` both times, in X's cell
  (held out together).
- **`with_feedforward(command, values)`:** the command with its feedforward channel at `values`: gravity + Coulomb (smoothed at most
  tanh(v / 0.05)) + net viscous + the twin's `inertial(q, qd, qdd)`, the one curve the fit installs.
- **Needs:** the `trajectories` extra (`robot_trajectories`, imported only when runs are made).
- **Rounds** (since 2026-11-19, gap FF-2, on gap A2's protocol; `RigRunner` plays them, docs/CALIBRATE.md "Feedforward, bench" step 4):
  - **`max_rounds`** (4): the runner's cap on rounds.
  - **`next_runs(values, history)`:** round k >= 2. The grid's cells never collected, in grid order, then the collected cells whose
    held-out residual (the last fit's, that cell left out) is over `tolerance_nm` (N·m), worst first, at most `per_round` of them (None:
    no cap). Each is a fresh run `…/r{k}/…` whose feedforward is made from `values`, the values after the last fit. When no cell is
    empty or over tolerance but `converged` still waits (one fit so far, or ΔG at or over `delta_nm`), the collected cells again, worst
    held-out residual first, at most `per_round`, so the next round reads ΔG. `()` only once `converged` has an answer.
  - **`converged(history, values)`:** its own stop, in place of the runner's default (every 95 % interval inside its tolerance). It
    returns one of:
    - `"converged: ΔG … N·m < delta_nm …"`, after two rounds or more, when the gravity of the last two fits differs by less than
      `delta_nm` on the pose graph's edges (ΔG), the worst held-out cell residual is within `tolerance_nm` and no cell is empty;
    - `Stop("no improvement in {patience} rounds: …")`, not converged, when every cell is collected, that residual is still over
      `tolerance_nm` and none of the last `patience` rounds cut it by `min_improvement` (relative, 10 %), each cut read over the cells
      both fits held. The residual has stopped falling, at the bench's noise floor (where the fit may still be right: the ladder's 3x
      and 10x) or because the model cannot explain the data; `tolerance_nm` must sit above that floor for the step to converge;
    - `None`: the next round.
  - **The runner's own stop**, not converged: "max_rounds {max_rounds} reached: it did not converge" (its other, "next_runs() asked for
    nothing more", no longer comes: `next_runs` re-collects while `converged` waits).
  - **`first`:** a bench sets it to the slow band, so round 1 on the prior costs less arm time. With the default `first=None` (the whole
    grid) a fit within `tolerance_nm` everywhere still converges: round 2 re-collects the worst cells for the second fit `converged`
    needs to read ΔG (since 2026-11-19; before, the step stopped after ONE round, "did not converge").
- **Row rules:** the routine fits with the bench's defaults, `moving_rad_s=0.1` (5.7°/s) and `pair_tol_rad=0.05` (2.9°), not `fit()`'s
  own 0.02 / 0.02 (1.1°/s, 1.1°) below. On a board's PD, speed noise reads a hold as moving, and the two legs part by the tracking
  error. Why, measured: docs/CALIBRATE.md "Feedforward, bench" step 4.

### `sim2real.fit.feedforward.fit(measured, regressor, *, inertial=None, prior=None, prior_sigma=None, moving_rad_s=0.02, groups=None, pair_tol_rad=0.02) -> FeedforwardFit`

- **What it does:** least squares of the board's torque less `inertial` on `[Y(q) | per drive sign(qd), qd]` over moving rows only (holds
  never enter), with a ridge toward `prior` when `prior_sigma` is given.
- **Returns:** `FeedforwardFit(theta, theta_ci95, coulomb, damping, residual_nm, residual_by_group, rows, runs)` with `gravity(regressor,
  q)`, `friction_torque(qd)` and `torque(regressor, q, qd, qdd, inertial=)`. The residual is held out one `groups` entry (a cell) at a time.
- **Raises:** `ValueError` naming the run and "both directions" when a run does not go out and come back over the same poses.

### `sim2real.metrics.actuator.feedback_share(effort, feedforward, moving) -> float`

- RMS(effort − feedforward) / RMS(effort) on the `moving` rows, pooled over drives: the feedback torque's share of the command (0 = all
  feedforward).

### Also on a twin

- **`twin.fitted`:** a bool.
- **`twin.instances`:** a tuple of `Instance`.
- **`twin.summary()`:** the calibration's table on a fitted twin, the instances otherwise.
- **`twin.noise()`:** a rig's 1× `NoiseModel`. `.at(level)` and `.with_terms(...)` build a stress sweep.
- **`fitted.result()`:** a rig's calibration as one page, `sim2real.result.CalibrationResult`.

## Not built yet

- **A real `calibrate(on="real")` run.** The backend is built (`f4d84c8`, `sim2real.real`, docs/CALIBRATE.md "on='real'"): CAN 11's schedule goes out as a rack submission and the runs come back as robot_msgs `JointTrajectory` for the same routines `plan(twin)` shows (since 2026-11-18), scored against the rack's own floor (gate T1). It is proved on the rack twin only (`TwinTransport`); no run has executed on the rack yet.
- **The description's side, past CAN 11.** Built: `bam_rack_twin.description.station_description(11)`, the shape `from_robot_description` reads. Not built:
  - a description for any other unit (each needs a calibration world: a sysid example whose manifest `record` names it);
  - one from a Cad2Robot bundle (CAN 11's `cad_joint` is null in the rack record: the Oct 9 export predates the station);
  - the write-back: a new description from `fitted.parameters`, and its own explicit save.
- **The fixtures** (`sim2real.examples`) still build from the sysid manifests through `sim2real.twin.describe`, which is internal and not public API; they are the oracle a description's twin is held to.
- **`simulate()` on a rig.**
