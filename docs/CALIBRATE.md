# What calibrate() does and what it returns

`twin.calibrate()` finds a twin's parameters. You pick a model for each part. The model gives the parameters. The catalog's routines that
identify those parameters are picked by how well they recover a hidden truth. They run in the order their own declarations give. A
`CalibrationConfig` steers the whole run, and the run comes back as one stable record, `sim2real.calibration/1`.

```python
import sim2real
from sim2real.calibration import CalibrationConfig, collect, plan

twin = sim2real.examples.ur_wrist_test_rig()
plan(twin).summary()                                   # what would run, in what order, and why; nothing runs
fitted = twin.calibrate(on="sim")                      # runs the plan; a NEW, fitted twin
fitted.plan_                                           # the CalibrationPlan that ran
fitted.record_.to_dict()                               # the sim2real.calibration/1 record (below)
fitted.record_.with_evaluation(fitted.eval().to_dict())   # the same record with eval()'s gates
```

Spec: `docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md`. Code: `src/sim2real/calibration/`.

## The routine kinds: configure → fit → tune → measure

Every routine writes values onto a model. They come in four kinds, and when nothing declared orders two routines they run in this order:

1. **configure** sets a value on the device, such as a joint zero or an exposure lock. It writes settings, not model parameters.
2. **fit** matches a model to reality, such as friction or mass. The catalog's word for it is `identify`; pages print "fit".
3. **tune** optimizes a metric where there is no real reference to match, such as PID gains, or a camera's exposure, gain and frame
   rate for ArUco corner accuracy. Like configure, it writes the settings it picks.
4. **measure** is a gauge. It reads a metric or a calibration constant.

A fifth kind, `use`, consumes a calibration at run time and identifies nothing. It runs last.

## The order: `requires`, `uses`, `refines`

Each catalog routine (`src/sim2real/cards/calibration.py`) declares what it needs, by parameter or setting **name**. A name matches
every instance that carries it.

| field | meaning | edge |
|---|---|---|
| `requires` | must be identified or configured before this routine runs | hard: a cycle is refused |
| `uses` | read if an earlier routine found it, else the prior serves | soft: it only breaks ties, and it is ignored where it contradicts a hard edge |
| `refines` | another routine sets it provisionally (its `adjusts`, or a configure that writes it), and this one finds it | hard: after every routine that sets it |

The planner (`sim2real.calibration.order`) builds the hard graph from `requires` and `refines` and sorts it with Python's
`graphlib`. Among the routines that are ready at each step it takes the first by:

1. no soft predecessor (`uses`) still unplaced;
2. then its kind's stage (configure, fit, tune, measure, use);
3. then wall time;
4. then id.

A declared `requires` always beats the stage. So the camera's ArUco tuning (a tune) runs before the bundle adjustment (a fit) that
requires its exposure.

A cycle raises `CalibrationCycleError` (a `ValueError`). Its message names every routine on the cycle and the name on each edge, and
`.cycle` holds the ids. The fix is usually to make one name a `uses`: a value the routine can read at its prior.

**Why three edges.** With one "reads" edge the UR wrist is a cycle: the backlash reversal reads the breakaway prior for its cap, and the
breakaway reads the backlash. The ruler is the wrist's hand order as it ran, backlash reversal → breakaway → homing → dynamics → gravity
direction → delay scan. The planner reproduces it from the declarations in all 720 input orders.

A requirement no planned routine provides is listed in the plan's `assumed`, held at its prior. It is never silently skipped.

## Picking: models → parameters → routines

- **Each type offers options** (`sim2real.calibration.options(type)`): its models with today's first, the routines that identify its
  parameters with the preferred first, and the configure or tune routines it always wants first (`setup`). A camera's setup is
  `camera.exposure_lock`. An ArUco marker's is `camera.exposure_for_aruco`.
- **Pick a model per part** with `select({instance: (type, model id)})`, or with `CalibrationConfig(models={instance: model id})`. A
  model holds every parameter of its family up to its rung.
- **The routines are a minimal cover:** drop any one, and something only it covered goes uncovered. Setup routines are never part of
  the cover.
- **Between alternatives, the metric is:**
  1. recovery at the configured noise level: passing first, then not graded, then failing, each by its worst error ÷ tolerance;
  2. then wall time plus operator time;
  3. then equipment $;
  4. then where it runs: a routine that runs at both first, then the budget's order of bench and deployed.
- **Recovery is read only through `sim2real.calibration.recovery`.** That is the same reader the docs site's tables use.
- **An unimplemented routine is never picked.** It shows up in `dropped` with "not implemented".

`select()` also says what it left out. `dropped` gives each routine with its reason: not implemented, excluded, outside the budget
(its setting, wall time or equipment $), known, or not needed because another routine covers it. `uncovered` gives each parameter
nothing picked identifies, with why.

On a rig twin (one that ships `rig.py` on the one-click seam), the candidates are the rig's own routines: its designer already chose them.
The config can still drop them (known, excluded, budget), substitute them (`custom`) or reorder them (`order`).

## CalibrationConfig

A frozen dataclass with a JSON round trip (`to_dict()` / `from_dict()`). Pass it to `calibrate(config=)`, `plan()`, `select()` or
`collect()`.

| field | what it does |
|---|---|
| `models` | `{instance: model id}`: a rung per part |
| `known` | `{key: value}`: fixed. A routine that would only find known values is dropped as "known", and every routine sees the value |
| `exclude`, `include` | routine ids kept out or brought in. An included configure or tune routine joins the setup |
| `order` | an explicit order of routine ids. It is refused if it runs a routine before one it `requires` or `refines` after, naming the key |
| `level` | which noise level (`0x`, `1x`, `3x`, `10x`) the metric reads; default `1x` |
| `noise` | a number (every term at that level) or a NoiseModel's dict. Passing it here and in `calibrate(noise=)` is refused |
| `budget` | `Budget(settings, max_wall_time_s, max_equipment_usd)`. Over budget, the lowest-ranked routines are dropped |
| `strict` | over budget → refuse with `CalibrationPlanError` instead of dropping |
| `seed` | the noise model's seed for this run |
| `routines` | per-routine options, set with `config.with_routine(id, **options)`. They reach a **copy** of the routine. An option the routine does not have raises `KeyError` |
| `custom` | injected routine objects. Each replaces the rig's implementation of a registered id. An id that is not in `cards/calibration.py` is refused |

## collect vs fit

Each routine is two halves: `runs(values)` says what to record, and `fit(measured, values, twin)` says what to compute. You can run
them apart. This is the deployment path: log in the field, fit anywhere.

```python
data = collect(twin)                 # plans, then plays every planned routine's runs once
fitted = twin.calibrate(data=data)   # fits the recorded runs; the backend's measure is never called
```

- `collect()` plans each routine's runs from the priors (plus `known`), because nothing has been fitted yet when the data is logged.
- A run that two routines share is played once.
- If a fit then asks for a run the data does not hold, it raises `CalibrationPlanError` naming the run.

## The record: `sim2real.calibration/1`

`fitted.record_.to_dict()`. The frozen example is `tests/fixtures/calibration_record_v1.json`: the UR wrist's real run in this shape.

| key | what it holds |
|---|---|
| `schema` | `"sim2real.calibration/1"` |
| `twin` | the twin's (rig's) name |
| `backend` | `"sim"` or `"real"` |
| `model` | the model the fitted twin runs, in words |
| `written` | the day the record was written (ISO date) |
| `seconds` | how long the run took |
| `noise` | the noise model it was played at (each term, its level, seed and sources) |
| `plan` | the plan that ran: `twin`, `source` (`"planner"` or `"config.order"`), `level`, `steps`, `dropped`, `uncovered`, `assumed`, `totals` |
| `parameters` | one row per parameter (below) |
| `routines` | one row per routine as it ran (below) |
| `passed` | every graded value within its tolerance, and at least one graded |
| `failing` | the keys outside their tolerance |
| `evaluation` | eval()'s gates (`gates`, `passed`, `summary`), or null before eval |

### Per parameter

| key | what it holds |
|---|---|
| `key` | `<instance>.<name>` |
| `instance` | the instance id |
| `name` | the parameter's name on its type |
| `unit` | SI unit |
| `nominal` | the prior the run started from |
| `value` | what the run found, or null |
| `ci95` | its 95 % interval `[low, high]`, or null |
| `true` | the hidden truth (sim only; the ruler), or null |
| `error` | `value - true` |
| `tolerance` | `{kind: "rel" or "abs", value, source}`, or null |
| `pass` | true / false against the tolerance; null when not graded (not identified, known, or its routine was not in the plan) |
| `routine` | the routine that identifies it, or null |
| `method` | how the routine found it |
| `why_not` | why it is not identified or not graded, else "" |

### Per routine run

| key | what it holds |
|---|---|
| `routine` | the routine id |
| `identifies` | the keys it claims |
| `runs` | how many runs it played |
| `seconds` | its wall time in this run |
| `found` | `{key: value}`, everything it set, including values it set for the twin without claiming them (its adjusts) |

### Per plan step

| key | what it holds |
|---|---|
| `routine` | the routine id |
| `title` | its title in the catalog |
| `kind` | configure, identify (fit), tune, measure or use |
| `setting` | where it runs: bench, deployed or both |
| `identifies` | the keys it writes (for a configure or tune routine, the settings) |
| `requires` | its hard needs, as the keys that carry them |
| `uses` | its soft needs, as keys |
| `refines` | the keys it finds that another routine set first |
| `after` | the routines it must run after (its hard predecessors) |
| `why_here` | why it sits at this place in the order |
| `wall_time_s` | its wall time in the catalog, set-up included |
| `operator_time_s` | a person's hands-on share of it |
| `equipment_usd` | the cost of the equipment it needs |
| `recovery` | `{level, pass, worst_error_over_tolerance}` at the plan's level, or null when nobody graded it |
| `source` | `"rig"` (the rig's implementation), `"custom"` (injected through the config) or `"catalog"` (planned for picked models; no implementation here) |

`CalibrationRecord.from_rig(calibration, report=, description=)` turns a rig's `RigCalibration.to_dict()` into this record without losing
a row, and `CalibrationRecord.from_dict(record.to_dict())` gives back the same record.

## Errors

- `CalibrationCycleError` (a `ValueError`): the declarations' hard edges form a cycle.
- `CalibrationPlanError` (a `ValueError`): an unregistered custom routine, an explicit order that breaks a requirement, a strict budget
  exceeded, or recorded data missing a planned run.
- `KeyError`: an option a routine does not have.
- `ValueError`: noise given both to `calibrate(noise=)` and in `CalibrationConfig.noise`.
- `NotImplementedError`: `config=` or `data=` on the pendulum tracer, which runs sysid's pipeline rather than planned routines.
