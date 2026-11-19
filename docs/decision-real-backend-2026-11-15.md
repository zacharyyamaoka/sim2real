# Decision: calibrate(on="real") plays the schedule through a transport, reads runs at the one door, fits with the sim's own identify (2026-11-15)

**Status:** accepted (the dispatcher's brief, 2026-11-15: wire `RobotTwin.calibrate(on="real")` for one pendulum station, proved in sim
only). Code: `src/sim2real/real.py`; acceptance: `tests/test_real_backend.py`; how to use it: `docs/CALIBRATE.md`, "on='real'".

## Context

`calibrate(on="real")` raised `NotImplementedError` naming the rack path: CAN 11 plays the same schedule on the One Dof Test Rack through
bam_rack_twin's runner, its runs come back through `tools/run_files.py` as robot_msgs `JointTrajectory`, the same identify fits them, and
the held-out score is against the rack's own floor (T1). The pendulum tracer's pipeline (sysid/examples/pendulum_can11) was proven on a
sealed hidden truth, in process: `RealWorld.measure` handed `identify()` its runs as objects, never as the files a session writes.
The rack itself is shared (the 1-DOF campaign owns it tonight; bam_ws main's record still retires CAN 11 on the full arm's adapter).

## Decision

- **The backend never plays; a transport does.** `sim2real.real` plans (the sim's own plan plus the schedule's five floor repeats), emits a
  **Submission** folder (`sim2real.real.submission/1`: every planned run with its purpose, `schedule.json`, and the rack runner's own
  session plans from `bam_rack_twin.schedule.session_plans`, each step stamped with its schedule run), and asks a **Transport**
  (`folder()`, `play(submission) -> Recording`, `ruler()`) for the runs. Two transports: `TwinTransport` (the rack twin at the sealed hidden
  truth) and `RackTransport` (the rack's session runner; a dry run that raises `RunsPending` unless `execute=True`, which is refused
  unless the record names the adapter, does not retire the station, the tree has the per-adapter bus lock and `BAM_RACK_BUS_LOCK` is set).
- **The run-file contract is the rack runner's own.** A transport returns session folders of `runs/<name>.npz` + `.json`
  (`bam_rack_twin.hardware.board.save`, the `schedule` stamp in the meta) plus `runs/link_camera/<name>.npz` (the link angle a camera saw, a
  robot_msgs JointTrajectory on the wall clock). The backend reads every run through `tools/run_files.py` and turns it into the pipeline's
  input with the producer's own rules (`bam_rack_twin.evidence`: judge, command_semantics, to_output_frame). The twin writes with the same
  writer, so the ingest under test is the one a rack session's runs go through. A run the producer's judge refuses is kept out of the fit
  and eval and named, never fatal (its convention: "a problem keeps it out of every fit and replay"); a planned run that never came back,
  or a fit run without a usable link camera, refuses the fit unless it is asked to be partial.
- **The fit is the sim's, unchanged.** `identify()` runs inside `sysid.world.sealed()` on the train runs only; the ruler is the transport's
  and is asked for only after the fit (a simulator has one; hardware returns None and the record's rows stay ungraded). Its only change is
  a `workers` keyword (default 8, as before) so a lane beside the powered rack can cap the polish's replay pool at 2.
- **Real eval replays each recorded run's own commands** and judges on the motor encoder: `floor` (T1: the floor tape's five repeats,
  same-input, tick for tick when the runs carry the plan tick), `twinned` (T2: held-out error over that floor), `held_out_fidelity`
  (nominal over calibrated, acceptance.json's factor). The link camera's ratio over its own floor is a flag beside them (Zach, 2026-11-11:
  gates from the joint readings, the camera a secondary measurement).

## Consequences

- On the twin, the runs that come back through the files equal the oracle's in-memory measurement bit for bit, so `on="real"` over the twin
  fits exactly what `on="sim"` fits; the same tolerances grade it, and a truth moved 10 % turns the record red.
- On the twin's world `twinned` cannot pass: eval starts each replay at the run's measured position (20 µrad of encoder noise off the
  command), CAN 11's stick-slip under ki 16000 amplifies that, and the world's floor repeats all start exactly on the command, so its floor
  is the encoder's noise alone. On the rack the repeats start where the joint really rests, so T1 carries that spread.
- What a real run still needs is named, not papered over: the link-camera file for every train and held-out run (nothing turns the
  session's clips into it yet), a tree whose record and twin of record match CAN 11's live board, and the rack owner's time.
- A rig on the one-click seam (`sim2real.rig`) has no transport yet; `on="real"` refuses it by name.

## Amendment, 2026-11-18: the fit is the schedule's routines, through the sim's own loop (gap F-real)

**Status:** accepted (the sim2real calibrate-gaps plan, lane L2; ruler `tests/test_real_plays_schedule.py`, and the One-click session's
agreed change to `tests/test_real_backend.py`'s slow green test).

- **What changed.** `calibrate(on="real")` no longer calls `identify()` in one shot and records a sysid plan of model rungs. It plans
  `plan(twin)` (CAN 11: `servo.backlash_reversals_camera`, then `servo.dynamics_regression`) and plays exactly those routines over the train
  runs the transport sent back, through `sim2real.twin._play_routines`, the loop `calibrate(on="sim")` plays. The gap step's finding is
  handed to the regression (`identify(..., gap=)`), and the backlash row keeps that step's value, interval, method and routine. The fitted
  twin's `plan_` is that plan and its record is written by `CalibrationRecord.from_schedule` (plan source `"planner"`);
  `CalibrationRecord.from_sysid`, `sysid_plan` and `sysid_step_id` are deleted, and records written before today (source `"sysid"`) still
  load through `from_dict`. `RealRunner.schedule()` lets a twin fitted on real plan the same schedule.
- **WHY.** Zach, 2026-11-17: `robottwin.calibrate()` "does .generate_schedule() -> CalibrationSchedule and then you can pass that to
  something thats gonna like dispatch/execute it". One schedule is shown, and it is the one both backends fit by. One executor means the
  guards (a run nobody measured, a value a routine does not declare, the seal) cannot drift between sim and real.
- **Robot time is earned.** Before emit, every planned run a routine names at the priors must be one the submission fills
  (`twin.PLAYED_SPLITS`: today `train`), or `CalibrationPlanError` is raised and nothing is written or played.
- **What did not change.** The submission (its 80 runs), emit, play, ingest, the transports, eval and the frozen `sim2real.calibration/1`
  keys. What the rack plays is still the pipeline's run schedule; collecting each routine's own runs is the next leg.
- **Side effects.** On a real record `plan.totals` are the planner's estimates (the rack's own time is the submission's `minutes`) and
  `plan.level` is the planner's noise level (`"1x"`), not `"real"`.
- **Undo.** `git revert` of the lane's code commit restores the one-shot `identify()` and the sysid plan (the ruler commits then go with it).
