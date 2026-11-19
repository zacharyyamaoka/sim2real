# What calibrate() does and what it returns

`twin.calibrate()` finds a twin's parameters. You pick a model for each part. The model gives the parameters. The catalog's routines that
identify those parameters are picked by how well they recover a hidden truth. They run in the order their own declarations give. A
`CalibrationConfig` steers the whole run, and the run comes back as one stable record, `sim2real.calibration/1`.

```python
import sim2real
from sim2real.calibration import CalibrationConfig, collect, plan

twin = sim2real.examples.ur_wrist_test_rig()
plan(twin).summary()                                   # what would run, in what order, and why; nothing runs
twin.generate_schedule()                               # the same CalibrationSchedule: each step's runs, known now or made after
fitted = twin.calibrate(on="sim")                      # runs the plan; a NEW, fitted twin
fitted.plan_                                           # the CalibrationSchedule that ran (CalibrationPlan is its old name, kept)
fitted.record_.to_dict()                               # the sim2real.calibration/1 record (below)
fitted.record_.with_evaluation(fitted.eval().to_dict())   # the same record with eval()'s gates
```

From a robot's description (2026-11-17; CAN 11's pendulum, under bam_rack_twin's venv; its twin is `pendulum_can11()` value for value):

```python
from bam_rack_twin.description import station_description
twin = sim2real.RobotTwin.from_robot_description(station_description(11))
plan(twin).summary()                                   # 1. servo.backlash_reversals_camera  2. servo.dynamics_regression
fitted = twin.calibrate()                              # on="sim", sealed truth: plays exactly that plan; ~15-27 min on the CAN 11 oracle
fitted.plan_.ids == plan(twin).ids                     # True: the schedule shown is the schedule that ran
fitted.evaluate().summary()                            # held-out runs only; eval() is its alias
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
- **Gates first, then rank** (gap B, 2026-11-18). Each routine passes these gates, in this order, before it is ranked; the first
  that drops it is its reason in `dropped`, and what only it would have found is `uncovered` with that reason:
  1. not excluded (`CalibrationConfig.exclude`);
  2. implemented (the catalog's status);
  3. runs where the budget allows (`Budget.settings`);
  4. needs only equipment you have or can use (`Budget.equipment`; Zach, Daily Note 2026-11-17: "you can define what equipment you
     have, etc. etc.."): "needs output_clamp ($150), which Budget.equipment does not list". With no inventory (`equipment=None`, the
     default) every item counts as available;
  5. a fit (kind `identify`) graded failing at `CalibrationConfig.level` is never planned: "recovery at 1x fails (worst error 2.4 x
     tolerance)". A routine nobody graded is still planned (it is "not graded": unknown stays unknown) and ranks after every passing
     alternative;
  6. not known (every parameter it finds is in `CalibrationConfig.known`).

  Setup routines pass the same gates except recovery: a configure or tune routine is judged on what it sets, never on a recovery
  ladder. Including a routine a gate drops is refused with `CalibrationPlanError`, naming the gate: `include` brings a routine in, it
  never overrides a gate. The gate list is this session's default (decided 2026-11-18, not Zach's ruling); undo by reverting gap B's
  commit.
- **The routines are a minimal cover** of what passed the gates: drop any one, and something only it covered goes uncovered. Setup
  routines are never part of the cover. A `why` says "ranked ahead of" only the alternatives that rank worse; a better-ranked
  alternative the cover did not need is named in its own clause ("… ranks higher, but the minimal cover (the fewest routines) keeps
  this one: it is the only planned routine for …").
- **Between alternatives, the metric is:**
  1. recovery at the configured noise level: passing first, then not graded, then failing, each by its worst error ÷ tolerance;
  2. then wall time plus operator time;
  3. then equipment $;
  4. then where it runs: a routine that runs at both first, then the budget's order of bench and deployed.
- **Recovery is read only through `sim2real.calibration.recovery`.** That is the same reader the docs site's tables use.
- **An unimplemented routine is never picked.** It shows up in `dropped` with "not implemented".

`select()` also says what it left out. `dropped` gives each routine with its reason: excluded, not implemented, outside the budget
(its setting, wall time or equipment $ still to buy), equipment `Budget.equipment` does not list, recovery at the level fails, known,
or not needed because another routine covers it. `uncovered` gives each parameter nothing picked identifies, with why.

On a rig twin (one that ships `rig.py` on the one-click seam, or the pendulum's `routines.py`), the candidates are the rig's own
routines: its designer already chose them. The config can still drop them (known, excluded, budget, and the equipment gate, which reads
the catalog's equipment for the routine's id), substitute them (`custom`) or reorder them (`order`). The status gate and the recovery
gate do not apply there: a rig's routine is its implementation, and the grade on its id was measured on another implementation (Zach,
2026-11-11: "In the spirit of black-box design, it's up to the designer of the part to provide ... the calibration options for its
part"). The CAN 11 pendulum with `Budget(equipment=("camera_tags",))` keeps both steps; with `Budget(equipment=())` it drops
`servo.backlash_reversals_camera` ("needs camera_tags ($325), …") and `can11.backlash_rad` is uncovered, held at its prior.

## CalibrationConfig

A frozen dataclass with a JSON round trip (`to_dict()` / `from_dict()`). Pass it to `calibrate(config=)`, `plan()`, `select()` or
`collect()`.

| field | what it does |
|---|---|
| `models` | `{instance: model id}`: a rung per part |
| `known` | `{key: value}`: fixed. A routine that would only find known values is dropped as "known", and every routine sees the value |
| `exclude`, `include` | routine ids kept out or brought in. An included configure or tune routine joins the setup |
| `order` | an explicit order of routine ids. It is refused if it runs a routine before one it `requires` or `refines` after, naming the key |
| `level` | which noise level (`0x`, `1x`, `3x`, `10x`) the metric reads, and the recovery gate: a catalog fit graded failing at it is never planned; default `1x` |
| `noise` | a number (every term at that level) or a NoiseModel's dict. Passing it here and in `calibrate(noise=)` is refused |
| `budget` | `Budget(settings, max_wall_time_s, max_equipment_usd, equipment)`. Over budget, the lowest-ranked routines are dropped. `max_wall_time_s` is held to the plan's counted-once wall time (see "The schedule": a run two routines share is counted once). Budget `equipment` is the equipment you have or can use (borrowed counts), as ids of `cards/calibration.py` EQUIPMENT: `None` (the default) = no inventory, every item available and costed; `()` = none. An id the catalog does not hold is refused. `max_equipment_usd` caps what is still to buy: the plan's `totals["equipment_to_buy_usd"]` leaves out what `equipment` lists, while `totals["equipment_usd"]` stays everything the plan needs. `budget.missing(items)` gives the items you lack |
| `strict` | over budget (time, or equipment still to buy) → refuse with `CalibrationPlanError` instead of dropping. The setting and equipment gates always drop and say so |
| `seed` | the noise model's seed for this run |
| `routines` | per-routine options, set with `config.with_routine(id, **options)`. They reach a **copy** of the routine. An option the routine does not have raises `KeyError` |
| `custom` | injected routine objects. Each replaces the rig's implementation of a registered id. An id that is not in `cards/calibration.py` is refused |

## The schedule: `CalibrationSchedule`

`plan(twin)`, `generate_schedule(twin)` and `twin.generate_schedule()` all return one `CalibrationSchedule`: what calibrate() will play,
as a static object you can look at before anything runs (Zach, Daily Note 2026-11-17: "the first output I think should be like A
CalibrationSchedule ... a static description of the routines that will be run"). `CalibrationPlan` and `plan` stay as aliases. On a twin
that ships its routines (a rig on the one-click seam, or the pendulum's `routines.py`), each step also holds its runs:

| on the step | what it holds |
|---|---|
| `runs` | its runs bound at the priors (the description's values, `known` on top), each a `sim2real.rig.Run`; `()` = it plays nothing; `None` = no preview (its `runs()` needs a value no prior states) |
| `status` | `"known now"` (its commands are what it shows, whatever earlier steps find), `"made after"` (its commands are made from what an earlier step finds), `"fit only"` (no runs of its own) |
| `commands_after` | the earlier steps whose found values its commands are made from |

- **Typed commands.** A `Run(id, split, spec=None, seconds=None, command=None)` carries a robot_msgs `JointTrajectory` (an open-loop
  tape) or `JointCommandSequence` (closed-loop steps), or no command; anything else is a `TypeError`. `run.robot_seconds()` is its robot
  time as (shortest, longest): the trajectory's duration, the sequence's bounds (each step ends by its `Elapsed` or its timeout, or at once
  when another condition holds), else `(seconds, seconds)`, else `None`. A trajectory's `seconds` must equal its duration (one run, one
  length). `to_dict()` / `from_dict()` carry id, split, spec, seconds and command; a spec that is not JSON is refused by the run's id.
- **Made after comes from the declaration, never from the order and never from a probe.** A routine may declare `commands_read` (the keys
  its commands are made from); without it, the keys it `requires` that an earlier step writes. A known value makes nothing wait.
- **calibrate() is held to it.** A known-now step must play exactly the runs shown, or calibrate() refuses it by name before it plays
  (a routine whose commands read more than it declares is caught there). `runs()` must give the same runs for the same values, a run id
  means one command, and an id with a command or a spec shared by a known-now and a made-after step is refused at plan time (a run
  with neither, a log the rig reads as is, has nothing an earlier fit could move: both steps read it, and it plays once).
- **What it costs: a shared run is counted once** (gap T, 2026-11-18). The runner plays a run two steps share once, so the totals do too:
  `totals["wall_time_s"]` is each step's own time (its declared wall time less the known length of the runs it plays, floored at 0) plus
  every distinct run's known length once, and `totals["run_time_s"]` is that run time: the runs planned at the priors, each counted once.
  A run's length is `run.robot_seconds()[1]` (the longest it can take). A step's own row (`wall_time_s`) still says what it costs alone.
  Nothing is counted short: a run of unknown length leaves its step's share in place, a step with no preview (its runs need an earlier
  fit) keeps its whole time and `summary()` says "counted whole", and a plan with no runs to read (catalog stand-ins, a record of what ran)
  keeps the per-step sum and `run_time_s` 0. One run id given two known lengths is refused by the id. `Budget.max_wall_time_s` and the
  strict refusal compare against this counted-once time. On CAN 11 the two steps read the same 771.8 s of train runs: 1972 s (771.8 + 600
  + 600 of set-up), where the per-step sum said 2744 s.
- **Seeing it.** `schedule.runs` holds the runs known now (each once), `schedule.previews` a made-after step's runs at the priors.
  `summary()` adds one line per step (`known now: ...`, `commands made after <step> runs; preview at the priors: ...`, `fit only`), and
  `to_dict()["schedule"]` one row per step (`routine`, `status`, `commands_after`, `max_rounds`, `runs`: each
  `{id, split, command, seconds, preview}`), present only when a step is bound: a catalog plan's dict is unchanged, and the record's step
  rows stay frozen.
- **The pendulum.** Both steps are known now on the one `train` run, whose length is the committed schedule's train seconds
  (`sysid/results/pendulum_can11.json`, 771.8 s), read, never re-derived; it has no command, because the rack plays sysid's schedule.

## Rounds: collect, fit, come back for more

A routine may iterate (gap A2; Zach, Daily Note 2026-11-18: "a routine should include datacollection and fitting steps, and then
iterating things that all goes into it"). Besides `runs(values)` and `fit(measured, values, twin)` it declares three optional members:

| member | what it does |
|---|---|
| `max_rounds` | its cap on rounds, an int >= 1; required once `next_runs` exists, else `plan()` refuses it ("max_rounds") |
| `next_runs(values, history)` | the next round's runs, made after the last fit (`history`: a tuple of `sim2real.rig.Round(k, runs, found)`); `()` = nothing more |
| `converged(history, values)` | its own stop rule, replacing the default: `None` = another round, a `str` = converged (the reason), `sim2real.rig.Stop(why)` = stop without claiming convergence |

- **Each round's fit sees every run so far**, sealed from the truth; each run is measured once (a later round reads the earlier ones from
  what was played). `runs()`, `next_runs()` and `converged()` run outside the seal, and what each round finds reaches the values before the
  next round's runs are made, so a tune's rounds carry the last fit in their commands (the bench feedforward's shape).
- **The stop, in order:** the routine's own `converged()` (it wins over the default); else the default, every 95 % interval inside its
  tolerance (the rig's `Parameter.tolerance`, half-width vs `tol`, or `tol x |value|` for a relative one; the interval, never the hidden
  truth, so moving the truth leaves the rounds unchanged); else `max_rounds`; else `next_runs()` returning nothing. A round with no new run
  is refused by name (`CalibrationPlanError`): it adds no data, so it would never converge.
- **Refused at plan time:** an iterating routine without an int `max_rounds` >= 1, and one the default rule cannot judge without a
  `converged()` of its own: a tune (judged on performance, it recovers no value an interval could settle), a routine that identifies
  nothing, or one none of whose identified keys has a tolerance.
- **Seeing it.** The schedule shows round 0's runs and the bound: the step's `max_rounds`, and `summary()` says "up to N rounds".
  `fitted.calibration_.routines` rows gain `rounds` (`[{k, runs: [ids], found: {key: value}}]`), `converged` (True, False, or None for a
  routine that plays one round) and `stopped` (why it stopped); `runs` counts the distinct runs over every round and `found` is the last
  fit. The record's routine rows carry the same three keys (additive; a record without them still loads).
- **Where it runs:** a rig on the one-click seam (`sim2real.rig.RigRunner`). The pendulum tracer and `on="real"` play their schedule once,
  so they refuse an iterating routine with a `NotImplementedError` naming it, before sysid is touched or anything is played.

## collect vs fit

Each routine is two halves: `runs(values)` says what to record, and `fit(measured, values, twin)` says what to compute. You can run
them apart. This is the deployment path: log in the field, fit anywhere.

```python
data = collect(twin)                 # plans, then plays every planned routine's runs once
fitted = twin.calibrate(data=data)   # fits the recorded runs; the backend's measure is never called
```

- `collect()` plans each routine's runs from the priors (plus `known`), because nothing has been fitted yet when the data is logged.
- The exception is a made-after step: `collect()` fits the steps it waits for as it goes, so it is recorded the way a replay builds it,
  and `calibrate(data=)` replays it without measuring and without a mismatch.
- A routine with rounds is fitted as it goes too (each round is made after the last fit), and so are the earlier steps whose found
  values its fit reads (`requires`, `uses`, `refines`), so its fit sees in `collect()` what a replay hands it: the data holds every
  round's runs, and `calibrate(data=)` replays the same rounds, with the same commands, by run id.
- A run that two routines share is played once, and counted once in the plan's totals (`run_time_s`; see "The schedule").
- If a fit then asks for a run the data does not hold, it raises `CalibrationPlanError` naming the run.

## The twin holds its data

Every fitted twin holds the runs it was fitted on as `fitted.data_`, a `CalibrationData` (gap D; Zach, 2026-11-17: "I think its the
RobotTwin that can kidna like hold all the dataset"). A later fit reads all of it:

```python
fitted = twin.calibrate(on="sim")                  # fitted.data_: the very recordings the fit read, each measured once
refit = fitted.calibrate(data=fitted.data_)        # the same runs, the same values; nothing measured, nothing written
grown = fitted.data_ + collect(twin, CalibrationConfig(seed=7))   # another session of the same schedule
better = fitted.calibrate(data=grown)              # fits every recording of every session
```

- **What it holds.** All of `data` when the fit was given it, else the very recordings its fit read, one key per run. `runs` are the
  runs a fit may read; `held_out` the runs kept only to judge it; `serves` {key: the run id it answers} (a rig's keys answer their own
  run ids; the pendulum's answer `"train"`, `"held_out"`, `"repeat"` or `"floor"`); `data.answering(run_id)` names every key that answers
  a run id. `meta` holds `twin`, `backend` (`"sim"` or `"real"`) and `session`; on the rack also the transport, the submission folder
  (its absolute path is the session), the schedule digest, `files` (the file each run was read from), `refused` and `missing`.
- **Refits start from the priors.** Every generation refits from the description's priors, so the same runs give the same values; a
  fitted twin's runner keeps the loaded twin's description (and a rig's world).
- **Growth is by session.** `data + more` (or `data.extend(more)`) returns a new dataset. A session already held is kept once, however
  it comes back (`(a + b) + b` is `a + b`). The same run recorded in another session is kept beside the first as `<key>@<session>`,
  answering the same run id, never overwriting it. A run no routine asks for is held and never fitted. `collect()` names its session
  from the twin, the plan's routines, the noise (its seed in it), the known values, the options `CalibrationConfig.routines` set, the
  custom routines and the values the world played (a moved truth or an injected `RigRunner(world=)` included), so the same session
  collected twice is recognised and any of these changed is another session. Two datasets that claim one session with different runs
  (compared by run name) are refused by name, never merged by dropping one.
- **The split rule.** A held-out run never becomes a training run: a dataset with a run in both `runs` and `held_out` is refused, and so
  is joining two where a run is held out on one side and trained on on the other (compared by run name, the session suffix stripped).
- **The sim/real rule.** Rack runs are never fitted on the sim (they would be graded against a hidden truth that did not make them):
  `calibrate(on="sim", data=)` refuses `backend "real"` runs, naming `on='real'`, and one dataset never mixes the sim's draws with the
  rack's recordings. Another twin's runs are refused, and so is `move_truth` with `data=` (recorded runs were drawn where they were drawn).
- **On the rack.** `calibrate(on="real", data=fitted.data_)` refits held rack runs with no transport, no emit and no play; its
  `submission_` is `None` and `eval()` judges it on the held held-out and floor runs.
- **On the pendulum tracer.** `calibrate(data=)` never plays its world; the train, held-out and repeat runs are the recordings that
  serve them, every session's. `eval()` refuses data that holds no held-out run.
- **Not built yet** (each its own leg, red tests first): saving and loading a dataset (by reference, pointing at the run files rather
  than copying them), turning the 1-DOF campaign rounds into a dataset by query, a keep-if-better rule for lifelong refits.

## Watching a calibration: callbacks, the ledger, W&B

`calibrate(callbacks=[...])` reports the run as it goes (gap E; Zach, Daily Note 2026-11-17: "As that calibration is running you will see
like the results in weights and biases, or etc. you can visually see once it has been calibrated and how it improves"). A local ledger
comes first; W&B is only ever a copy of it (house rule: W&B is a copy of a local ledger; "W&B is just a visualizer for the dat").

```python
from sim2real.calibration import Ledger
from sim2real.tracking.calibrate_wandb import WandbLogger

ledger = Ledger()                                              # one folder per calibration under $SIM2REAL_CALIBRATIONS
fitted = twin.calibrate(on="sim", callbacks=[ledger])           # ledger.folder fills line by line while it runs
fitted.evaluate()                                               # its gates land in the same folder (fitted.callbacks_)
fitted = twin.calibrate(callbacks=[ledger, WandbLogger(ledger)])   # plus the live W&B copy (an unpowered host or a cloud VM)
```

- **The hooks** (duck-typed: a callback implements only the ones it wants; `sim2real.calibration.Callback` lists them as no-ops):
  `on_calibrate_begin(event, *, schedule, twin)`, `on_collect_end(event)`, `on_step_end(event)`, `on_calibrate_end(event, *, fitted)`,
  `on_calibrate_error(event)` (kind `error` or `pending`), `on_evaluate_end(event, *, report, fitted)`, `on_callback_error(event)`, and
  `on_submission(event)` (the rack's submission folder, before it plays; never a ledger line).
- **The events** (`sim2real.calibration-events/1`; every one carries `schema`, `kind`, `calibration` (its id), `twin`, `utc` and `t`,
  seconds since the calibration began):
  - `schedule`: the schedule about to run (`schedule.to_dict()`), the backend, the model, the config and the sim2real commit (`code`);
  - `collect` (the tracer and the rack): what was played up front, before the first fit (the tracer's world measures every run at once;
    the rack's ingest says what came back, missing and refused). `seconds` on the tracer is labelled "world measure": it includes the
    held-out and repeat draws;
  - `step`, one per planned routine, sent as its fit finishes (`live: true`): `index` (its place in the schedule), `routine`, `runs`
    (the run ids it read), `played` (a rig: the ones it measured or read fresh; a run two steps share is played once, by the first),
    `collected` (`measured`, or `recorded` on `calibrate(data=)`), `collect_s` and `fit_s` (unrounded), `seconds`, `found`
    {key: {value, ci95, method, unit}} in SI, and `round` (a routine with rounds also carries `rounds`, `converged`, `stopped`);
  - `done`: `passed`, `failing`, `seconds` and the parameter rows (key, unit, nominal, true, recovered, ci95, error, tolerance, pass);
  - `evaluate`: `passed`, the gates (id, title, value, rule, passed, source) and `compare`, before -> after per metric;
  - `error` (the calibration raised), `pending` (the rack has runs still to play; it names the submission), `callback_error` (a hook
    raised: the callback is detached with one `RuntimeWarning` and the calibration goes on unchanged).
- **The ledger's folder** (`<UTC stamp>-<twin id>`): `events.jsonl` (each event appended, flushed and fsynced as it happens),
  `schedule.json`, `calibration.json` (the `sim2real.calibration/1` record, rewritten with eval's gates) and `eval.json`. Values stay SI.
  One `Ledger` used for several calibrations opens a folder each, and each event lands in its own calibration's folder.
- **Defaults.** A sim calibration writes nothing unless asked (sweeps call it hundreds of times). A rack calibration (`on="real"`, and
  `python -m sim2real.real`) keeps a ledger beside its submission, `<submission>/calibrate/<stamp>/`: the schedule is on disk before
  the rack plays, each step lands as its fit finishes, and runs still to be played end it `pending`. `SIM2REAL_TRACK` overrides both:
  `off` (no ledger), `ledger`, `wandb` (a ledger and its live W&B copy); any other value is refused by name. `callbacks=[]` wins over
  everything. `SIM2REAL_CALIBRATIONS` is where a sim ledger goes (default `~/.local/share/sim2real/calibrations`). The test suite runs
  with `SIM2REAL_TRACK=off` (tests/conftest.py).
- **Observers never guard.** A callback that raises is detached (one warning, one `callback_error` line) and never changes the fit; a
  calibration that fails still raises, after its ledger ends `error`; a fitted twin built without callbacks still evaluates.
- **The W&B copy** (`sim2real.tracking.calibrate_wandb`): one run per calibration, id `run_id("calibrate", <calibration id>)`,
  `job_type` `calibrate`, group `calibrate · <twin>`, in the twin's deployment's project (app/registry.json: CAN 11 goes to
  "Sim2Real · 1-DOF rack") or its rig's (`sim2real.tracking.rigs.RIGS`); a twin with neither logs nowhere unless a project is given.
  History rows: the schedule, one per step (`found/<instance>/<name>` with `/ci95_lo` and `/ci95_hi`), the outcome
  (`calibration/passed`, `recovery/<instance>/<name>/{pass,error}`), the evaluation (`eval/passed`, `gate/<id>/passed` beside
  `gate/<id>/value`, `eval/<metric>/{before,after,factor}`). Angles are shown in degrees there and only there (Zach, 2026-11-11): a key
  in rad is logged as `<name>_deg` (`_rad` becomes `_deg`, `_rad_s` becomes `_deg_s`). A W&B that will not start costs one warning
  and no retry; the ledger stays whole.
- **On the powered rig's host** keep wandb-core out of the calibration: run with the default ledger (or `SIM2REAL_TRACK=ledger`) and follow
  it from a capped, low-priority process, or sync it afterwards:

```bash
systemd-run --user --scope -p MemoryMax=1G nice -n 19 taskset -c 2-5,16,17 python -m sim2real.tracking.calibrate_wandb --follow FOLDER
python -m sim2real.tracking.calibrate_wandb --sync FOLDER     # or --all; --dry-run says what it would push
```

  The live copy, the follower and `--sync` log exactly the rows `records(folder)` rebuilds from the files alone. `--sync` writes a run
  W&B lacks; a run W&B holds short of its ledger (a live copy that died) is replayed whole under a fresh id and the partial run marked
  superseded, never deleted. Decision record: docs/decision-calibrate-wandb-2026-11-18.md.

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
| `plan` | the plan that ran: `twin`, `source` (`"planner"` or `"config.order"`; `"sysid"` marks a pendulum on='real' record written before 2026-11-18, whose plan listed the model rungs sysid's `identify()` fitted), `level`, `steps`, `dropped`, `uncovered`, `assumed`, `totals` (`wall_time_s` with each shared run counted once, `run_time_s`, `operator_time_s`, `equipment_usd`, `equipment_to_buy_usd` (what `Budget.equipment` did not list; equal to `equipment_usd` with no inventory); records written before 2026-11-18 carry no `run_time_s` or `equipment_to_buy_usd`), and `schedule` (the schedule's rows, above) when a step was bound. On a real record `totals` are the planner's estimates (the rack's own time is the submission's `minutes`) and `level` is the planner's noise level, not the hardware's |
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
| `rounds`, `converged`, `stopped` | optional (a rig's run carries them, gap A2): each round `{k, runs, found}`, whether it converged (None: one round), why it stopped; see "Rounds" |

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
| `source` | `"rig"` (the rig's implementation), `"custom"` (injected through the config), `"catalog"` (planned for picked models; no implementation here) or `"sysid"` (records written before 2026-11-18 only: a model rung a sysid pipeline fitted, id `sysid.<example>.<rung>`; its `wall_time_s` is null because `identify()` times no rung apart) |

`CalibrationRecord.from_rig(calibration, report=, description=)` turns a rig's `RigCalibration.to_dict()` into this record without losing
a row, and `CalibrationRecord.from_dict(record.to_dict())` gives back the same record. The pendulum tracer's sim backend plays planned
routines since 2026-11-17: its example ships them (`sysid/examples/pendulum_can11/routines.py`: `servo.backlash_reversals_camera`, the
gap from the train runs' load reversals, then `servo.dynamics_regression`, the regression over every rung at that gap, each a step of the
pipeline), `plan(twin)` shows them, `calibrate()` plays exactly those, and `CalibrationRecord.from_schedule(...)` records the steps as they
ran. Its `CalibrationConfig` picks, orders and excludes routines; `known`, `models`, `noise` and `seed` do not reach it yet (its rung is
`RobotTwin(models=...)`, its noise sysid's ladder). Since 2026-11-18 the on='real' path plays the same `plan(twin)` routines through
the same loop (`sim2real.twin._play_routines`) over the train runs the rack sent back, and `CalibrationRecord.from_schedule(...)` records
it with plan source `"planner"`; records written before that (`from_sysid`, plan source `"sysid"`, one step per model rung) still load
through `from_dict`.

## on='real': the rack path

`calibrate(on="real", transport=...)` plays the same schedule on hardware through a transport, reads the runs back as robot_msgs
`JointTrajectory` through `tools/run_files.py` (the one door to the rack's run files) and fits them through the schedule `plan(twin)`
shows, the same routines in the same loop the sim backend plays (`sim2real.twin._play_routines`), each sealed. On CAN 11 that is
`servo.backlash_reversals_camera` (the gear gap from the train runs' load reversals), then `servo.dynamics_regression` handed that gap; both
read the one submission's train runs, so the rack plays once. A planned run the submission cannot fill is refused before emit
(`CalibrationPlanError`), so the rack never spends its minutes on a schedule that cannot be fitted. What the rack plays is still the
pipeline's run schedule (its train and held-out splits plus the floor repeats); typed collection from each routine's own runs is next.
First station: CAN 11 on the One Dof Test Rack, the pendulum tracer (`sim2real.examples.pendulum_can11()`). Code: `src/sim2real/real.py`;
acceptance: `tests/test_real_backend.py` and `tests/test_real_plays_schedule.py`.

```python
import sim2real
from sim2real.real import RackTransport, TwinTransport
twin = sim2real.examples.pendulum_can11(workers=2)
fitted = twin.calibrate(on="real", transport=TwinTransport())        # the rack twin at a sealed hidden truth: no hardware anywhere
fitted.record_.to_dict()                                              # sim2real.calibration/1, backend "real"
fitted.eval().summary()                                               # held-out runs replayed on their own commands, over T1's floor
twin.calibrate(on="real", transport=RackTransport(out))              # the rack: writes the submission, dry-runs it, raises RunsPending
```

The four steps, each a function in `sim2real.real`:

| step | what | from |
|---|---|---|
| plan | the sim backend's own plan (every FB run of the train and held-out splits) plus the schedule's five floor repeats (T1) | `sysid/examples/pendulum_can11/pipeline.py` `plan()` |
| emit | `submission.json` (`sim2real.real.submission/1`), `schedule.json`, `plans/<station>_<mode>.json`: the rack runner's session plans over exactly the planned runs, each step stamped with its schedule run | `bam_rack_twin.schedule.session_plans` |
| play | `transport.play(submission)` returns a `Recording` (session folders), or raises `RunsPending` | the transport |
| ingest + fit | each `runs/<name>.npz` + `.json` read as a JointTrajectory, keyed by its schedule stamp, judged and put in the output frame, paired with its link angle; then the schedule's routines, each inside `sysid.world.sealed()` | `tools/run_files.py`, `bam_rack_twin.evidence`, `sim2real.twin._play_routines` |

**What a transport returns.** A session folder in the rack runner's own files: `runs/<name>.npz` + `runs/<name>.json`
(`bam_rack_twin.hardware.board.save`: its FIELDS, the run meta with its `schedule` stamp {digest, run, split, mode}) and, per run,
`runs/link_camera/<name>.npz`: the link angle a camera saw (a robot_msgs JointTrajectory, output frame, on the wall clock), which the gap step
(`servo.backlash_reversals_camera`, `gear_gap()`) reads for the gear gap and the regression for the rows where the gear is in contact
(M4). A run the producer's rules refuse (`bam_rack_twin.evidence.judge`: an abort, a latched watchdog, a hard fault, a setpoint not
followed) came back, so it is kept out of the fit and eval and named on `fitted.runs_.refused`, never fatal: bam_rack_twin's own convention, and a re-run meets the same physics (on the twin's world CAN 11's
multisine at kp × 0.25 sticks in its stiction band, 5 mrad of a 100 mrad command, so 45 of the 46 train runs fit). A real fault still shows,
as the runs the session then skipped. A planned run that did not come back and a train or held-out run without a usable link camera are
named in an `IngestError`; `calibrate(..., strict=False)` (`sim2real.real.calibrate`, the CLI's `--partial`) fits what came back, keeping
those out. A run recorded twice, or logged by another board, is always refused.

**The transports.**

- `TwinTransport(root=, move_truth=, workers=2)` plays every step of every session plan as the oracle plays a schedule run (the run's
  sampled target, position mode, the twin of record at world.json's truth) and measures it with the oracle's own noise model and seeded
  streams, then writes each run with `board.save` (ticked: row k is the tape's sample k) and its link angle. The runs read back are the
  oracle's in-memory measurement bit for bit (`tests/test_real_backend.py`), so `on="real"` over the twin fits exactly what `on="sim"`
  fits. `move_truth` moves the world for the ruler's red run; `ruler()` stays world.json's and is asked for only after the fit.
- `RackTransport(out, execute=False, adapter=None)` hands the submission to the rack's own session runner. Without `execute` it writes the
  submission and `dry_run.json` (the rack runner's offline checks: every step's limits and the proven window, nothing opened) and raises
  `RunsPending` with one command per session; once the sessions' runs are in `out/sessions/`, the same call fits them. With `execute=True`
  it starts `python -m bam_rack_twin.hardware session --plan P --out O` (the interpreter running it, so plan, session and fit are one
  bam_rack_twin tree) in a `systemd-run --user --scope -p CPUWeight=2000` scope, and only when none of these refusals holds: a device-free
  lane (`BAM_LANE_NO_DEVICES`), no `adapter`, the record putting the station on another adapter, the record retiring the station, a tree
  without the rack's own bus lock, or `BAM_RACK_BUS_LOCK` not set to `rack_bus_lock(adapter)`. On bam_ws main's record (2026-11-15) CAN 11
  is retired on 0607623A, the full arm's adapter, where CAN 11 is the five-bar's J1 board, so an execute from main's tree is refused.

**The record on hardware.** No hidden truth, so no parameter is graded: each row's `pass` is null with its `why_not`, `true` null, and
`passed` is false (nothing graded; `failing` stays empty). The verdict is eval's: `floor` (T1, the floor tape's five identical repeats
agree as the same input, motor encoder), `twinned` (T2, the twin's held-out motor-encoder error over that floor, at most
`cards.servo_gates.FIDELITY_TAPES`) and `held_out_fidelity` (nominal over calibrated held-out error, at least acceptance.json's factor). The
link camera's ratio over its own floor is reported beside them as a flag, never a gate (Zach, 2026-11-11: gates from the joint readings).
Eval replays each recorded run from its measured start, the board's real commands on the board's real stamps. On the twin's world that
makes `twinned` unpassable by construction (a twin at the exact truth read 11x on the shortest held-out run): the measured start is 20 µrad of encoder noise off the
command, CAN 11's stick-slip under ki 16000 amplifies it, and the world's floor repeats all start exactly on the command, so its floor is
the encoder's noise alone. The rack's repeats start where the joint really rests, so its T1 floor carries that spread and T2 is its gate.
Measured on the twin (2026-11-15, `tests/test_real_backend.py` green): floor 0.0276 mrad from the floor tape's 5 repeats, the fitted M4
18.8x it (FAIL, as above), held-out fidelity 13.9x (pass, >= 4x), and the link camera's flag 1.39x its own 0.435 mrad floor (the sim
oracle's link gate read 1.34x).

**One command.** `python -m sim2real.real` (dry run unless `--execute`; `--transport twin` plays the whole path on the twin). It runs
under bam_rack_twin's venv, the pendulum's runtime: sim2real's own env cannot carry bam_rack_twin, which depends on sim2real, and
`pendulum_can11()` there says so with this command.

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m sim2real.real --transport twin --out /tmp/pendulum-real-twin

**Queued for the rack owner (2026-11-15; not run).** From the 1-DOF campaign's tree, whose record puts CAN 11 on 272813EF and whose board
module has the per-adapter `BAM_RACK_BUS_LOCK` (bam_ws `claude/1dof-rack-sim-to-real-435fc0`, not on main yet). A dry run as written; the
same line with `--execute` plays the 80 runs (about 25 min), and the same line again afterwards fits them and writes `calibration.json`
and `eval.json` into `--out`:

    env -u VIRTUAL_ENV BAM_RACK_BUS_LOCK=/home/bam/.cache/rack-commissioning/bus.272813EF.lock /home/bam/bam_ws/.claude/worktrees/1dof-rack-sim-to-real-435fc0/src/dev/bam_rack_twin/.venv/bin/python -m sim2real.real --adapter 272813EF --out /archive/datasets/bam_rig/sim2real_real/pendulum_can11-20261116

Before `--execute`, three things the dry run cannot settle: the fit needs `runs/link_camera/<name>.npz` for every train and held-out run
(the link angle on tags 8-12; the rack's session records the D405 clips, nothing turns them into this file yet); the schedule and the twin
of record are built from that tree's record, so its board knobs must be CAN 11's live ones (the campaign raised max_current to 19.4 A and
recorded kp 400 / kd 8 on 11-15); and the session's own config and frame checks still run before anything moves.

## Feedforward, bench: `arm.feedforward_bench`

A routine that fits an arm's feedforward, gravity and friction, the way Zach asked for it (Daily Note 2026-11-18: "I basically just want
to do .calibrate() and then for the feedforward model to be fit as accurately as possible"). A rig hands it to its runner like any other
routine; `calibrate()` plays its runs and its fit. Decision: `docs/decision-feedforward-bench-2026-11-18.md`. The flow, in one picture:
`docs/feedforward-flow.svg`.

```python
from sim2real.calibration import FeedforwardBench
from sim2real.fit import feedforward
from sim2real.metrics.actuator import feedback_share

routine = FeedforwardBench(space=space, poses=poses, grid=grid, first=first, drives=("j2", "c1"), gravity_keys=keys,
                           regressor=regressor, inertial=inertial)        # space: a robot_trajectories JointSpace over the drives
runs = routine.runs(values)            # one robot_trajectories.trapezoidal_velocity(..., back_to_start=True) per cell, feedforward attached
found = routine.fit(measured, values, twin)    # {key: Estimate}: theta, and each drive's frictionloss_nm / damping_nm_s_rad
routine.fits_[-1].residual_by_group    # the held-out residual, one cell left out at a time
feedback_share(effort, fed, moving)    # RMS(effort - feedforward) / RMS(effort) on moving rows: low = the feedforward carries the motion
```

**The loop** (collect → fit → check → iterate → grade):

1. **Collect.** A cell is an edge of a workspace pose graph at one speed band. Each run is ONE trajectory-library call,
   `trapezoidal_velocity(space, target, start=, velocity_fraction=, dwell_s=, back_to_start=True)`: out along the edge and back over the
   same poses. Its command carries `channels["feedforward_effort"]`, the feedforward at the values the round was handed
   (`with_feedforward`), so the board runs the current model while collecting.
2. **Fit** (`sim2real.fit.feedforward.fit`). Rows are moving samples only (|qd| >= 0.02 rad/s on that drive): a hold rests anywhere inside
   static friction, so it bounds gravity and never equals it. The target is the board's torque less the twin's inertial term; the columns
   are the twin's gravity regressor Y(q) and, per drive, sign(qd) and qd. The way back cancels the friction. Friction is one curve,
   Coulomb (`frictionloss_nm`) plus a NET viscous term (`damping_nm_s_rad`, negative where friction weakens with speed). A ridge pulls
   toward the prior the round was handed when `prior_sigma` is given; 95 % intervals come from the covariance.
3. **Check.** The residual is held out one cell at a time (never one run of a pair) and is systematic: per drive, the RMS of the held-out
   residual's means over blocks of 25 moving rows, so torque noise averages out and model error does not. A run that goes one way, or
   comes back along another path, is refused by name ("needs both directions over the same poses").
4. **Iterate** (part 2, `tests/test_feedforward_rounds.py`). Each later round collects only empty or over-tolerance cells, with commands
   made from the last fit, and stops when the fit stops changing, stops improving, or reaches its cap, saying which.
5. **Grade, twice.** Recovery of a sealed hidden truth in sim (the toy arm `tests/feedforward_toy.py`; the CAD prior fails the same
   ruler), then performance: the fitted feedforward must at least halve the feedback share and the tracking error of the CAD feedforward,
   with FB only and FF only reported beside them (part 2's closed loop).

**Where the arm's feedforward stands today** (as the gap FF review found it, 2026-11-18). Every term below was calibrated by one-off
scripts in bam_ws `src/core/mdp/setup/bam_pid_tunning/docs/` over runs harvested from picks and experiments, checked on held-out runs and
installed by a pin move; none came from a routine, and none has a stop rule.

| term | where it runs | what calibrates it in sim2real |
|---|---|---|
| measured-mass gravity, J2 / C1 and the wrist | the 15c mass file (re-pick), the lumped five-bar compensation (arm-hold, stops) | `arm.feedforward_bench` (this), on the `bam_fb_v2` rig: FF-3 |
| J1's gravity law, A sin(q − hang) | two laws live, within 0.19 N·m of each other | the same fit, once the rig's regressor carries J1 (FF-3) |
| J2 / C1 Coulomb, 0.70 / 0.78 N·m | a bench constant, never refit on `bam_fb_v2` | `arm.feedforward_bench` refines it (one curve with gravity) |
| the inertial term | the trajectory, from the CAD masses | nothing yet: the fit takes the twin's inertial term as given |
| the gated hold pushes, J2 / C1 | arm-hold | nothing: holds never enter this fit |

- **Bench vs deployed.** Bench is this routine, submitted through rackq once the twin passes. Deployed is the same fit over the
  production runs the twin holds (`calibrate(data=)`), with PID tuna's learned feedforward as a drift canary.
- **What lands now (FF-1):** the routine, its fit, its catalog row and its sim proof on the toy arm. **Next:** rounds (FF-2), then the CAN 11
  pendulum and the `bam_fb_v2` rig on the one-click seam, twin first (FF-3). **Still blocking a real-arm run:** the `bam_fb_v2` rig on the
  seam, the friction twin's 20ad gate (it fails today), and Kt, which nothing measures and which reads exactly like a mass scale.
- **The catalog row** identifies `link_inertials` (`arm_subassembly` M2, `arm_6dof` M3) and refines the drives' friction, so an
  integrated-servo pick never gets it in its cover; `arm.dynamics_excitation` and `servo.dynamics_regression` are its alternatives.
- **Install:** `robot_trajectories` is the `trajectories` extra (`uv sync --extra trajectories`); it has no remote yet, so the extra
  resolves on the workstation and in a cloud cut that carries it.

## Errors

- `CalibrationCycleError` (a `ValueError`): the declarations' hard edges form a cycle.
- `CalibrationPlanError` (a `ValueError`): an unregistered custom routine, an explicit order that breaks a requirement, a strict budget
  exceeded, recorded data missing a planned run, an iterating routine without `max_rounds` (or without `converged()` where the default
  stop cannot judge it), or a round that plays no new run.
- `KeyError`: an option a routine does not have.
- `ValueError`: noise given both to `calibrate(noise=)` and in `CalibrationConfig.noise`.
- `NotImplementedError`: a `CalibrationConfig` with `known`, `models`, `noise` or `seed` on the pendulum tracer (its config picks,
  orders and excludes its routines only); a routine with rounds on the pendulum tracer or `on="real"`.
- `TypeError` / `ValueError` for `data=` (see "The twin holds its data"): not a `CalibrationData`; another twin's runs; rack runs on the
  sim or sim draws on the rack; `move_truth` or `transport=` with `data=`; a held-out run turned training run.
- `TypeError`: `calibrate(on="real")` without a transport (it names `RackTransport` and `TwinTransport`).
- `RunsPending` (`sim2real.real`): the submission is written and dry-run, nothing has come back to fit; it carries the session commands.
- `RackRefused` (`sim2real.real`): `RackTransport(execute=True)` refused before starting anything; `.refusals` says why.
- `IngestError` (a `ValueError`, `sim2real.real`): the runs that came back cannot be fitted as planned, each problem named.
