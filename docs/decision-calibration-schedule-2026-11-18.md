# Decision: the CalibrationSchedule, a static view with typed commands (2026-11-18)

**Decided:** `plan(twin)` returns a `CalibrationSchedule` that binds each step's runs at the priors, types each run's command, and says
whether its commands are known now, made after an earlier step runs, or the step is fit only. `calibrate()` is held to it. Lane L1 (gap A1)
of the sim2real calibrate plan of 2026-11-18; ruler `tests/test_calibration_schedule.py`.

Zach, Daily Note 2026-11-17 ("One click sim to real how does that tie in?"):

> And then the first output I think should be like A CalibrationSchedule. Its almost like a JointTrajecotry though I think in that its a
> static description of the routines that will be run... so its nice to be able to kinda like see it as a static object. could a routine
> just be described as as long joint traecjtory? or how about like ServoCommandSequence.. internall mabye that does .generate_schedule()
> -> CalibrationSchedule

and: "routines can almost like declare depencies on what they require to run ahead of time so you can ... atuomaticaly generate the
schedule".

## What was decided, each with its undo

| call | why | undo |
|---|---|---|
| `CalibrationSchedule` is the class; `CalibrationPlan = CalibrationSchedule`; `generate_schedule = plan`; `RobotTwin.generate_schedule(config)` | Zach's name is the class's own; every import, `isinstance` and the docs site's `api-CalibrationPlan` anchor keep working (the site renders an alias as one line) | rename back; the aliases make it one commit |
| `Run(id, split, spec=None, seconds=None, command=None)`: a command is a robot_msgs `JointTrajectory` or `JointCommandSequence`, or none; anything else is a `TypeError` | robot_msgs is sim2real's one runtime dependency and already has both shapes Zach named; refusing anything else keeps a spec from passing as a command | drop the field; positional `Run(id, split, spec)` never changed |
| `robot_seconds()`: the command's bounds, else `(seconds, seconds)`, else None; a trajectory's `seconds` must equal its duration | one source for a run's length (the totals lane, T, counts it); unknown stays unknown | — |
| made after comes from the declaration (`commands_read`, else the keys it requires that an earlier step writes), never probed | Zach's "declare depencies ... ahead of time". The first design probed (moved each earlier-written value and called `runs()` again); the review ruled that against his declaration pattern, and a probe misses a read that survives the move (a rounded or clamped value) while calling `runs()` once per key. A routine whose commands read more than it declares is caught at play time instead, by name | — |
| `runs()` is called twice at plan time and must agree; one run id is one command; an id a known-now and a made-after step share is refused | a schedule is static, and a shared id must mean one physical run | — |
| `collect()` fits online the steps a made-after step waits for (and the earlier steps those fits read) | so a made-after step is recorded the way a replay builds it, and `calibrate(data=)` replays without a mismatch; every other step still records only | `_Recorder(fits=False)` everywhere |
| the plan's dict gains `schedule` rows only when a step is bound; `PlanStep.to_dict()` is unchanged | a catalog plan's dict and the record's frozen step rows (`sim2real.calibration/1`) stay as they were | — |
| the pendulum's `TRAIN` keeps no command and carries `seconds` = `sysid/results/pendulum_can11.json` `schedule.train.seconds` (771.8 s) | the rack plays these runs (sysid's schedule), so they are never labelled recorded data; the length is read, never re-derived | `seconds=None` |

## Left for later lanes

- Rounds (collect, fit, come back): `tests/test_calibration_rounds.py`, lane A2.
- Totals that count a shared run once from `robot_seconds()`: lane T.
- The UR wrist's typed commands and its schedule test (A3): its runs still carry only specs, so its steps show their runs without commands.
- The pendulum's typed collection (the rack playing typed commands): A3 / FF-3.

Prior art: a JointTrajectory is ROS's static command message; the schedule plays the role of a static execution plan you inspect before
running, as in a build system's dry run (`make -n`) or a query planner's `EXPLAIN`.
