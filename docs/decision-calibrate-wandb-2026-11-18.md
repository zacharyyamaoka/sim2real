# Decision: watching a calibration live, a local ledger first and W&B its copy (2026-11-18)

**Decided:** `RobotTwin.calibrate(callbacks=[...])` reports the schedule, each step as its fit finishes, the fitted twin and evaluate()'s
gates to its callbacks. `sim2real.calibration.Ledger` writes them to a local folder; `sim2real.tracking.calibrate_wandb.WandbLogger`
copies that ledger to W&B, live, and `--follow` / `--sync` copy it from another process or afterwards. Lane L9 (gap E) of the sim2real
calibrate plan of 2026-11-18; ruler `tests/test_calibrate_tracking.py`, plus R3 (`tests/conftest.py` forces `SIM2REAL_TRACK=off`).

Zach, in his own words:

> As that calibration is running you will see like the results in weights and biases, or etc. you can visually see once it has been
> calibrated and how it improves. (2026-11-17)

> I decied I would have a weights and bias account for each deployment. (2026-11-17)

> W&B is just a visualizer for the dat (2026-11-17)

> have the results like show up in weights and biases should be all automated (2026-11-11)

## What was decided, each with its undo

| call | why | undo |
|---|---|---|
| callbacks on `calibrate()` (Keras's `fit(callbacks=)`), never on `CalibrationConfig` | a config steers what is calibrated and lands in the record and the session id; an observer changes nothing about the fit | move the keyword |
| duck-typed hooks (`on_calibrate_begin`, `on_step_end`, `on_calibrate_end`, `on_calibrate_error`, `on_evaluate_end`, plus `on_collect_end`, `on_submission`, `on_callback_error`); `Callback` is optional | a callback implements only what it needs; one event dict per kind, built once, so every callback sees the same values | — |
| a hook that raises is detached with one `RuntimeWarning` and a `callback_error` line; the error event catches `BaseException` | observers never guard (twin.py: "guards live in the runner, never in callbacks"); a Ctrl-C mid-schedule still ends the ledger saying where | — |
| every event carries its calibration's id; one `Ledger` opens one folder per calibration | a reused ledger never writes one calibration's events (a later `evaluate()`) into another's folder | — |
| default: a sim calibration writes nothing; a fresh rack calibration keeps a ledger beside its submission (`<submission>/calibrate/<stamp>/`); a refit from held rack runs (`on="real", data=`) defaults as the sim, and an asked-for ledger opens under its own root, never inside the held submission | sweeps and stress lanes call the sim's calibrate() hundreds of times (a folder or a W&B run each would flood the disk and the free plan's 5 GB, 76 % used on 11-17); a rack calibration spends robot time and its trail belongs beside its runs; a refit spends none and plays nothing (lane D: a refit writes no submission), and `--all` would otherwise push it as a rack calibration | `SIM2REAL_TRACK=ledger` (or `off`) per shell; or change `resolve_callbacks`' default |
| `SIM2REAL_TRACK=off|ledger|wandb` overrides the default; `callbacks=[]` wins over everything; an unknown value is refused naming the three | turn it on without code; a typo never silently turns logging off | — |
| W&B by default: off (only `SIM2REAL_TRACK=wandb`, a `WandbLogger`, `--follow` or `--sync`) | live wandb-core beside the powered arm is unmeasured; the ledger is the trail, the copy can follow | recommendation: switch W&B on by default for rack runs once the follower is proven on the rig's host |
| the project is the deployment's own (app/registry.json: CAN 11 -> "Sim2Real · 1-DOF rack", `job_type` `calibrate`), else the rig's (`tracking.rigs.RIGS`), else none | Zach's 11-17 decision (a W&B project per deployment); a toy or test twin is not a deployment, so it logs nowhere unless a project is given | a family project is one constant away (`project_for`) |
| the run's id is `run_id("calibrate", <calibration id>)`, rebuilt from the ledger alone by one pure `row()` shared by the live copy, the follower and the replay | the live run and a replay are the same run; a moved ledger rebuilds the same rows | — |
| angles in degrees in the W&B copy only (`_rad` and `_mrad` -> `_deg`, `_rad_s` -> `_deg_s`, a rad key gains `_deg`); the ledger stays SI. Evaluate's before/after keys use wandb_log's trend vocabulary: `eval/<metric>_before_deg` beside `eval/<metric>_after_deg` (`_floor`, `_factor`), so `held_out_motor_mrad` logs as `eval/held_out_motor_before_deg` | Zach, 2026-11-11: angles shown to him in degrees, never rad; data stays SI; the deployment project's before/after panels already read `Twin/sim_real_before_deg` | — |
| `WandbLogger` requires a Ledger and opens it first; listed without that ledger, `calibrate()` adds it right before the logger; a W&B that will not start costs one warning, never a retry loop | W&B is a copy of a local ledger (house rule): W&B never holds a row no local file has; the ledger stays whole and `--sync` copies it later | refuse instead (a TypeError naming `callbacks=[ledger, WandbLogger(ledger)]`) |
| `--sync`: a run W&B lacks is written whole; one W&B holds short (a live copy that died) is replayed under `run_id("calibrate", <id>, "replay")` and the partial run marked superseded, never deleted | `wandb_log.push` patches only a run's last step, which would leave the middle steps missing | — |
| on the rack the schedule is on disk before emit (an explicit ledger) or the moment emit names the folder (the default beside-submission ledger), always before the rack plays; `RunsPending` ends the ledger `pending`, naming the submission | the trail of what was asked of the robot exists before the robot moves; a run still to be played is not an error | — |
| `real.calibrate(..., on_plan, on_step, on_collect, on_submission, on_pending)` receive the hooks only when there are callbacks | `tests/test_real_backend.py` pins real.calibrate's call without them | — |
| the follower runs as `systemd-run --user --scope -p MemoryMax=1G nice -n 19 taskset -c 2-5,16,17 python -m sim2real.tracking.calibrate_wandb --follow FOLDER` | the powered rig's host is real-time: wandb-core stays out of the calibration's process, capped, off the arm's CPUs | — |
| `_json_default` moved out of real.py into `sim2real/_json.py` (real.py imports it under its old name) | the rack's files and the ledger write the same values by one rule; the ledger alone falls back to a value's text so an observer never loses an event | move it back |

## Not built in this leg

- A saved W&B view filtered on `JobType = calibrate` in "Sim2Real · 1-DOF rack" (one `wandb-workspaces` call; first real run first).
- The first real calibrate run copied to W&B (`SIM2REAL_TRACK=ledger` on the rack, then one `--sync`), read back through `wandb.Api`.
- Measuring wandb-core's memory and CPU beside the powered arm, which decides whether rack runs get the live copy by default.
