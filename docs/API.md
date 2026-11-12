# sim2real public API

A `RobotTwin` is a digital twin for an electromechanical device. You build one, simulate it, calibrate it and evaluate it. The calibrated values come back on a new twin.

```python
import sim2real

twin = sim2real.examples.pendulum_can11()        # or: description.to_robot_twin()
twin.simulate()
fitted = twin.calibrate(on="sim")
print(fitted.eval().summary())
description = description.from_robot_twin(fitted)   # robot_description side (not built yet)
```

- **Lines 3–6 run today.** `docs/api_example.py` is the same lines with the last one swapped for `parameters = fitted.parameters`, the values `from_robot_twin` will take. `reports/sim2real-api-2026-11-11.html` shows its real output.
- **Run it from a REPL or notebook, or inside `if __name__ == "__main__":` in a script.** `calibrate()` replays runs in a process pool whose workers re-import your main module. A bare script would run again inside every worker, and Python refuses that with a `RuntimeError`.
- **The slow call** is `calibrate(on="sim")`: about 15–27 min on the CAN 11 oracle, because the rack twin replays at 30 kHz.

## The design principle: every robot description comes with a twin

```
robot_msgs  ←  sim2real  ←  robot_description  ←  robotparts, cad2robot, five_bar, scripts
 (Value …)     (types, models,    (one robot: topology + typed instances
               RobotTwin, fit)     holding parameter Values)
```

- **sim2real sits right above robot_msgs on purpose.** Every robot description should come with a twin, so robot_description depends on sim2real. That's the point, not a cost. Zach, 2026-11-11: "the whole point of robotics is to like actually do something in reality! We are making this first class" (`docs/decision-types-seam-2026-11-11.md`, addenda 2 and 3).
- **sim2real knows nothing about RobotDescription.** Its public noun is `RobotTwin`. robot_description builds one with `description.to_robot_twin()` and takes the calibrated values back with `description.from_robot_twin(fitted)`. RobotDescription stays bare-bones: it only holds the information.
- **robot_description imports only sim2real's light core:** the types, the models and `RobotTwin`, on robot_msgs and numpy. MuJoCo is the `sim` extra (`sim2real[sim]`) purely for install size. A package that only describes robots never installs a simulator.
- **Arrows are imports, and there is no cycle.** sim2real imports neither robot_description nor robotparts.

## Concepts

- **RobotTwin.** A digital twin for an electromechanical device. It holds typed instances, the model rung each one runs, and each parameter as a robot_msgs `Value`. Its verbs are `simulate`, `calibrate` and `eval`. A fitted twin is a new object; the twin you started from never changes.
- **Instance** (`sim2real.twin.Instance`). One component of the twin: an id, a sim2real type id (or none, for a structural node like a deployment), a parent, and `parameters: {name: Value}`. `on_type` says, for each parameter, whether the type's contract names it. A parameter the contract lacks is carried and flagged, never dropped.
- **Type** (`sim2real.cards`). sim2real's generic kinds of part: `integrated_servo`, `gearbox`, `bldc_motor`, `encoder`, `depth_camera` and the rest. Each card lists the type's parameters and units, its model ladder (`M0` ideal … `M7`), its calibration routines and its gates. No manufacturer appears here; robotparts maps a part to a type.
- **Value** (`robot_msgs.space.Value`). A float that remembers where it came from: `unit`, `low`/`high`, `basis` (`assumed`, `datasheet`, `measured` …), `source`, `measured_by` and `notes`. Priors are `assumed`. A calibrated value is `measured`, its 95 % interval is in `low`/`high`, and its source reads `sim2real calibrate · on=sim · <rung> · <date>`. An interval that doesn't bracket the fitted value stays in `notes`, because `Value` refuses such a `low`/`high`. On CAN 11 that's the two friction values polished by output error after the regression that gave their interval.
- **Runner** (`twin.runner`). The level below the verbs, and the one to drop to. `SimRunner` is the pendulum tracer: plan → measure → identify (sealed from the truth) → score. `RigRunner` (`sim2real.rig`) runs a rig's routine sequence. A rig opts in by shipping `rig.py`. The guards (sealed truth, held-out only) live in the runner, never in a callback.
- **Calibration** (`fitted.calibration_`). What the fit found: each parameter's nominal, hidden truth (sim only), recovered value, interval, tolerance and verdict. `.summary()`, `.passed`, `.failing`, `.to_dict()`.
- **Report** (`fitted.eval()`). Held-out fidelity: each model's error ÷ the floor (the run-to-run spread you can't beat) and the gates. `TwinReport` for the tracer, `RigReport` for a rig. Both have `.summary()`, `.passed`, `.gates` and `.to_dict()`.
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

### `twin.calibrate(on="sim", *, truth="sealed", move_truth=None, noise=None, config=None, data=None) -> RobotTwin`

- **What it does:** returns a NEW, fitted twin. It plays the routines on the simulator against a hidden truth that the fit never sees, in the order their declarations give (`sim2real.calibration.plan`; docs/CALIBRATE.md).
- **The learned values end in `_`** (scikit-learn's convention): `values_`, `intervals_`, `rungs_` and `calibration_`. `fitted.parameters` carries them as Values.
- **`plan_` and `record_`** (rigs on the one-click seam): `plan_` is the `CalibrationPlan` that ran, and `record_` is the run as one `sim2real.calibration/1` record (`record_.to_dict()`; add eval's gates with `record_.with_evaluation(fitted.eval().to_dict())`). On the pendulum tracer both are `None`, because it runs sysid's pipeline rather than planned routines.
- **`config=CalibrationConfig(...)`:** steers the run: models per part, known values, excluded or included routines, an explicit order, the noise level the metric reads, the budget, per-routine options and injected routines. See docs/CALIBRATE.md.
- **`data=collect(twin)`:** fits recorded runs and never calls the backend's measure. This is the deployment path: collect in the field, fit anywhere.
- **`move_truth={key: value}`:** moves hidden values for one run while the ruler stays put. It's the mutation test: a moved truth must turn red.
- **`noise`:** rigs only. `None` is the rig's measured 1×, a number scales every term, or pass a `sim2real.rig.NoiseModel`.
- **Never:** writes anything. It doesn't touch hardware unless `on="real"`, and that isn't built yet.
- **Raises:**
  - `ValueError` for an unknown `on` or for `truth` other than `"sealed"`;
  - `NotImplementedError` for `on="real"` (it names the rack path);
  - `NotImplementedError` for `noise=` on the tracer;
  - `KeyError` for a `move_truth` key the world doesn't have;
  - `ValueError` for noise given both as `noise=` and in `config.noise`;
  - `KeyError` for a per-routine option the routine doesn't have;
  - `CalibrationPlanError` for an unregistered custom routine, an explicit order that breaks a requirement, a strict budget exceeded, or `data` missing a planned run;
  - `CalibrationCycleError` when the routines' declared needs form a cycle;
  - `NotImplementedError` for `config=` or `data=` on the tracer.

### `fitted.eval() -> TwinReport | RigReport`

- **What it does:** scores the fitted twin on held-out runs only and returns error ÷ floor and the gates.
- **Never:** writes anything or touches hardware.
- **Raises:**
  - `RuntimeError` on an unfitted twin;
  - `ValueError` when a run it would score was used for training. It refuses rather than filtering it out.
- **Renamed:** this was `eval_twin()` until 2026-11-11.

### Also on a twin

- **`twin.fitted`:** a bool.
- **`twin.instances`:** a tuple of `Instance`.
- **`twin.summary()`:** the calibration's table on a fitted twin, the instances otherwise.
- **`twin.noise()`:** a rig's 1× `NoiseModel`. `.at(level)` and `.with_terms(...)` build a stress sweep.
- **`fitted.result()`:** a rig's calibration as one page, `sim2real.result.CalibrationResult`.

## Not built yet

- **`calibrate(on="real")`.** The rack path: CAN 11 plays the same schedule through bam_rack_twin.hardware, with its torque cap and stops as the runner's guards. The runs come back as robot_msgs `JointTrajectory`, and the same identify fits them. The held-out score is against the rack's own floor (gate T1).
- **robot_description's side.** RobotDescription needs:
  - a typed-instance element: a sim2real type id, a parent, binds, and `parameters: {name: Value}`;
  - `description.to_robot_twin()`;
  - `description.from_robot_twin(fitted)`, which returns a new description from `fitted.parameters`;
  - its own explicit save.
- **Until then,** the examples' instances come from the sysid manifests through `sim2real.twin.describe`, which is internal and not public API.
- **`simulate()` on a rig.**
