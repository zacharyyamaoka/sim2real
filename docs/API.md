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
- **Raises:** `CalibrationPlanError` for `runs()` that change between two calls, one run id bound to two different runs, or a run id a
  known-now and a made-after step share.

### `twin.calibrate(on="sim", *, truth="sealed", move_truth=None, noise=None, config=None, data=None, transport=None) -> RobotTwin`

- **What it does:** returns a NEW, fitted twin. It plays the routines on the simulator against a hidden truth that the fit never sees, in the order their declarations give (`sim2real.calibration.plan`; docs/CALIBRATE.md).
- **The learned values end in `_`** (scikit-learn's convention): `values_`, `intervals_`, `rungs_` and `calibration_`. `fitted.parameters` carries them as Values.
- **`plan_` and `record_`**: `plan_` is the `CalibrationSchedule` that ran (the one `twin.generate_schedule()` and `plan(twin)` show; a known-now step that plays other runs than it showed is refused by name), and `record_` is the run as one `sim2real.calibration/1` record (`record_.to_dict()`; add eval's gates with `record_.with_evaluation(fitted.eval().to_dict())`). The pendulum tracer plays the routines its example ships (`sysid/examples/pendulum_can11/routines.py`: `servo.backlash_reversals_camera`, then `servo.dynamics_regression`, each a step of its pipeline) since 2026-11-17.
- **`config=CalibrationConfig(...)`:** steers the run: models per part, known values, excluded or included routines, an explicit order, the noise level the metric reads, the budget, per-routine options and injected routines. On the pendulum tracer it picks, orders and excludes routines; `known`, `models`, `noise` and `seed` are refused there for now. See docs/CALIBRATE.md.
- **`data=collect(twin)`:** fits recorded runs and never calls the backend's measure. This is the deployment path: collect in the field, fit anywhere.
- **`move_truth={key: value}`:** moves hidden values for one run while the ruler stays put. It's the mutation test: a moved truth must turn red.
- **`noise`:** rigs only. `None` is the rig's measured 1×, a number scales every term, or pass a `sim2real.rig.NoiseModel`.
- **`on="real", transport=...`** (the pendulum tracer, `sim2real.real`): plans the same schedule plus its five floor repeats, writes them as a rack submission, lets the transport play it, reads the runs back through `tools/run_files.py` and fits them with the same `identify()`, sealed. `RackTransport(out)` is a dry run that raises `RunsPending` with the session command; `RackTransport(out, execute=True, adapter=...)` starts the rack's session runner only when every refusal check passes; `TwinTransport()` plays it on the rack twin at the sealed hidden truth. The record is `backend: "real"`; on hardware its rows are ungraded and eval's gates (T1 floor, T2 twinned, held-out fidelity) judge the twin. See docs/CALIBRATE.md, "on='real'".
- **Never:** writes anything on `on="sim"`. On `on="real"` it writes only the submission its transport is given a folder for, and it never touches hardware itself: a transport plays (`RackTransport` hands the plan to the rack's own session runner, and only with `execute=True`).
- **Raises:**
  - `ValueError` for an unknown `on` or for `truth` other than `"sealed"`;
  - `TypeError` for `on="real"` without a transport (it names `RackTransport` and `TwinTransport`); `RunsPending`, `RackRefused` and `IngestError` from `sim2real.real` on the rack path;
  - `NotImplementedError` for `noise=` on the tracer;
  - `KeyError` for a `move_truth` key the world doesn't have;
  - `ValueError` for noise given both as `noise=` and in `config.noise`;
  - `KeyError` for a per-routine option the routine doesn't have;
  - `CalibrationPlanError` for an unregistered custom routine, an explicit order that breaks a requirement, a strict budget exceeded, or `data` missing a planned run;
  - `CalibrationCycleError` when the routines' declared needs form a cycle;
  - `NotImplementedError` for `config=` or `data=` on the tracer.

### `RobotTwin.from_robot_description(rd, *, models=None, workers=6) -> RobotTwin`

- **What it does:** builds the twin from a robot's description: its typed components with their priors (robot_msgs Values), its model file and its unit. The calibration world is the one built for that unit (the sysid example whose manifest `record` names the same deployment file and component).
- **First description:** `bam_rack_twin.description.station_description(11)`; its twin is `pendulum_can11()` value for value.
- **Raises:**
  - `TypeError` for a design-only `RobotDescription` (it names no unit and no typed priors), and for a prior that is a bare number instead of a Value;
  - `ValueError` for a type that is no sim2real type, repeated component ids, or a parent that is no component;
  - `LookupError` when no calibration world was built for the unit.

### `fitted.evaluate() -> TwinReport | RigReport` (alias `fitted.eval()`)

- **What it does:** scores the fitted twin on held-out runs only and returns error ÷ floor and the gates.
- **Never:** writes anything or touches hardware.
- **Raises:**
  - `RuntimeError` on an unfitted twin;
  - `ValueError` when a run it would score was used for training. It refuses rather than filtering it out.
- **Renamed:** this was `eval_twin()` until 2026-11-11, and `eval()` until 2026-11-17 (Zach's sketch `twin.evaluate()`; Keras' `model.evaluate()`; PyTorch's `.eval()` means inference mode). `eval()` stays as its alias.

### Also on a twin

- **`twin.fitted`:** a bool.
- **`twin.instances`:** a tuple of `Instance`.
- **`twin.summary()`:** the calibration's table on a fitted twin, the instances otherwise.
- **`twin.noise()`:** a rig's 1× `NoiseModel`. `.at(level)` and `.with_terms(...)` build a stress sweep.
- **`fitted.result()`:** a rig's calibration as one page, `sim2real.result.CalibrationResult`.

## Not built yet

- **A real `calibrate(on="real")` run.** The backend is built (`f4d84c8`, `sim2real.real`, docs/CALIBRATE.md "on='real'"): CAN 11's schedule goes out as a rack submission and the runs come back as robot_msgs `JointTrajectory` for the same identify, scored against the rack's own floor (gate T1). It is proved on the rack twin only (`TwinTransport`); no run has executed on the rack yet.
- **The description's side, past CAN 11.** Built: `bam_rack_twin.description.station_description(11)`, the shape `from_robot_description` reads. Not built:
  - a description for any other unit (each needs a calibration world: a sysid example whose manifest `record` names it);
  - one from a Cad2Robot bundle (CAN 11's `cad_joint` is null in the rack record: the Oct 9 export predates the station);
  - the write-back: a new description from `fitted.parameters`, and its own explicit save.
- **The fixtures** (`sim2real.examples`) still build from the sysid manifests through `sim2real.twin.describe`, which is internal and not public API; they are the oracle a description's twin is held to.
- **`simulate()` on a rig.**
