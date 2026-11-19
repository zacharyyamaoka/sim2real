# Decision: PID tuna is a calibration routine of kind "tune" (`pid.pidtuna`, 2026-11-18)

**Decided:** the catalog's `pid.pidtuna` is re-kinded from `use` (a routine the planner never schedules) to `tune`, and sim2real runs it:
`sim2real.calibration.PidTune` wraps PID tuna (`pidtuna.tune`, /home/bam/pidtuna) as a step of a schedule. Every integrated servo wants
it once it is fitted (`sim2real.calibration.options.SETUP`); it runs after the fits that find what it tunes on, proposes the board's
feedback gains as **settings**, never model values, and is graded on the performance it gains. Lane L10 (gap C) of the sim2real
calibrate plan of 2026-11-18; ruler `tests/test_pid_tune_routine.py`.

Zach, on what PID tuning is:

> PID Tuna is the backend for one of the routines certaintily.... (2026-11-17)

> calibration or like tune beacuse there is not a real to reference it off of its just like tuning for another metric... (2026-11-11)

and on PID tuna itself, it stays "its own standalone thing" (2026-11-11); ".calibrate() ... Kinematics. Dynamics, etc. PID" (2026-11-18).
On the arm: PD + feed-forward only, never an integrator (2026-11-13).

## Why a value change needs this record

`src/sim2real/cards/CONTRACT.md` is additive only: no name or value of an existing entry changes without a decision. `pid.pidtuna` keeps
its id, title and package; its `kind`, times, code homes, oracle note and dependencies change. `kinematics.ik_fine_tune`, the other
`use` routine, is untouched. The generated projections (`src/sim2real/cards/domain_v3.json`, `sysid/results/calibration_routines.json`)
are regenerated in the same change, never hand-edited.

## What was decided, each with its undo

| call | why | undo |
|---|---|---|
| kind `use` -> `tune`; identifies `()`; configures `Configures("servo", ("kp_nm_rad", "kd_nm_s_rad"))` | a tune writes settings it picks for a metric with no real value to match (cards.schema ROUTINE_KINDS); the planner schedules a tune (stage configure -> fit -> tune -> measure) and never a `use` | put `kind="use"` back and drop `configures` |
| the settings are the gains only; the feed-forward it was tuned under goes in the proposal | the feed-forward is the fitted model's (pidtuna v2: it owns only kp and kd, the feed-forward is an input held fixed); as a setting it would duplicate the model | add the feed-forward keys to `configures` |
| requires `armature_kg_m2`, `frictionloss_nm`; uses gravity, its bottom, damping, command delay, Stribeck drop | it tunes on the fitted plant: after the routines that find its inertia and friction (hard edges), reading the rest where found (soft) | drop the edges |
| operator time 0 s; wall time the tune's compute on the fitted twin, 3 s measured on a cloud VM (amended 2026-11-19 from 0 s: the ruler's owner holds every routine's wall time positive, as type_cards/tests/test_routines.py does; "no robot time" is `runs()` being empty); setting `bench` | what runs today is the SIM tier: PID tuna on a ServoSim of the fitted twin, no robot time, no hands; a deployed-only budget still drops it by name | put the BENCH tier's estimate back once its tapes play on the joint |
| `options.SETUP["integrated_servo"] = ("pid.pidtuna",)` | "always wants" is a designer's call (PEP 0001 §5): every integrated servo has a board whose gains a tune proposes | remove the entry |
| the gains stay "not identified" in `Selection.uncovered`, their reason naming the device's config receipt and the tune | a tune recovers no hidden value; the board's config receipt says what it runs now, the tune proposes the change | — |
| a tune whose required parameter nothing planned finds is dropped, naming it (catalog path) | a tune never runs on a plant nothing fitted | let it run on the priors |
| a rig routine whose back end this machine lacks says so (`unavailable()`) and the planner drops it by name | PID tuna has no remote and is imported only when it runs: a machine without it plans the schedule with this step dropped rather than failing mid-calibration | — |
| a tune's outputs are settings: the step's `found`, `state["settings"]`, `fitted.settings_`, the handle's `settings` for later routines; never the values a routine fits with, the values the twin replays at, or a parameter row's owner | the runs were made at the gains the board ran: fitting or replaying them at the proposed gains would describe a robot that never ran; a proposal is not a write | — |
| a configure step's outputs still enter the values | a configure sets the device (an exposure lock, a counts-per-metre), so what follows runs at it | — |
| a fit result's `proposal` lands in `fitted.proposals_` | the board change (pidtuna's gains document, schema `pidtuna/gains-1`, plus the feed-forward and tier) is what a person reviews and writes | — |
| the wrapper hands PID tuna the board with its integrator off: the board's ki kept, ilimit 0 (bam_ws 9de804493) | no integrator on the arm (Zach, 2026-11-13); moteus holds the integral to +-ilimit, so ilimit 0 switches it off whatever ki is, and a runner cannot change ki per command | — |
| sim2real -> pidtuna one way, imported only when the routine runs; pools capped at the twin's workers and closed when it is done (`ServoSim.close()`, a local pidtuna commit; until pidtuna main has it, servo_sim's own pool registry, the one `close()` empties) | PID tuna stays its own tool; no idle workers beside the powered arm | — |
| CAN 11's one-click schedule runs it third, after `servo.dynamics_regression` (`sysid/examples/pendulum_can11/routines.py`), on the board as the deployment record states it in the rack's envelope | every pendulum calibration then proposes gains for the joint it just fitted; `CalibrationConfig(exclude=("pid.pidtuna",))` leaves it out | remove the third step |

## The grade: performance gained, never a recovered value

A tune has no hidden truth to recover, so its ladder (`sysid/results/routine_ladders/pid.pidtuna.json`, schema
`sim2real.routine_ladder/1`) grades it on the closed loop it delivers. On a moved hidden CAN 11 (no file the routine may read: `world.json`
is refused during the fit), with handed values at 0 / 1 / 3 times the dynamics fit's acceptance tolerance and signed to mislead, the
delivered controller's cost (stop p90 and tracking RMS, each over the board's as-found controller, on held-out tapes) is compared with the
best admissible PD + feed-forward on a grid over the TRUE model: regret = cost / oracle - 1 <= 0.15 passes (bam_pid_tunning K6). The
ruler fails the board's own controller and a deliberately bad corner first, so a tune that does nothing cannot pass, and it writes the
ladder before its pass asserts with the hashes of the wrapper and itself, so a hand-written ladder cannot stand in. The "before" is what
the board runs today (its PID with integrator); the "after" is PD + feed-forward.

## Left for later

- **BENCH tier:** PID tuna's tapes played on the joint by sim2real's executor (rackq) through a transport plant; its runs cannot be
  declared up front (the sweep stops at the first ringing rung), so it waits for measure-on-demand rounds.
- **Deployed tier:** a fine-tune routine over production runs (pidtuna's finetune), its own catalog row.
- **Catalog plans:** an integrated servo's catalog plan shows `pid.pidtuna` as a stand-in that cannot run (no rig implements it there);
  swapping in the runnable `PidTune` automatically is a follow-up.
