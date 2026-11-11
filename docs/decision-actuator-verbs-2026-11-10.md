# Decision: the actuator verbs move into sim2real, and RobotDx and bam_rack_twin call them (2026-11-10)

**Status:** accepted (proposal 2, step 4; Zach's picks in "Sim2Real as a Pure Library on robot_msgs — 3 Proposals (2026-11-10)").

## Context

The servo acceptance gates T1-T11 lived in bam_rack_twin (`acceptance.py`), and the formulas they read lived in RobotDx's stock checks
(`robotdx/diagnostics/stock/tracking.py`, `fidelity.py`, `data.py`), which bam_rack_twin's `metrics.py` already called. The test schedule
lived in `bam_rack_twin/schedule.py`. The gate targets sat twice: as acceptance constants and as literals on the servo card's own gates.

## Decision

- **`sim2real.metrics`** holds the formulas once: `series` (RMS from robot_msgs.compare, the median, the common clock, pairwise RMS),
  `actuator` (tracking, stops, the floor, fidelity ratios, T2's move / hold split and rest offsets), `coverage` (rows per cell, robot_msgs
  .coverage's binning), `gate` (a robot_msgs Value's range through `Space(msg).violations`), and `servo_gates.evaluate(facts, targets,
  allocation_mrad=)`, the T1-T11 verdicts. Plain arrays and dicts in, numbers out; no Trajectory, no Result, no rack.
- **The targets are cards data** (`sim2real.cards.servo_gates`): every T1-T11 target a robot_msgs Value with its range and source, the rule
  text, the stations' stop allocations, the type / unit gate sets, the schedule's coverage gate and the note's targets. The servo card's
  gates (`ladders.servo`) read the same Values.
- **`sim2real.schedule.joint`** holds the generator: the description, the build loop and split rule, sampling and limits, coverage before
  running. What plays the schedule is a `Player` argument (its families, modes, how its steps sample, the step a trajectory carries, run
  time); the rack's families stay in bam_rack_twin, written in its runner's step kinds.
- **RobotDx depends on sim2real** (its `diagnostics` extra, beside numpy) and keeps its Trajectory, row masks, configs and Result; its stock
  checks call `sim2real.metrics`. **bam_rack_twin** keeps thin wrappers with every old name and signature (a path dependency through
  `src/external/sim2real`), plus everything rack-specific: collecting facts from the archive, the pick and refit rules, the runner, plans.

## Consequences

- One formula per check: the same floor, stop error and fidelity ratio serve RobotDx's live checks and the rack's gates.
- A changed gate target is a cards edit. One behaviour moved with it: T2's split is judged by the target, not by the `passes` flag the
  fact collector wrote (all 1,053 recorded splits agree, so no recorded verdict changes).
- Kept out of this step: the pick / refit / other-day rules (selection policy, `fit/` later), the RobotDx coverage check's own config and
  every other stock check (camera, health) beyond the shared rulers.
- Gap reported, not fixed (robot_msgs untouched in this step): robot_msgs.coverage has no dense, vectorised occupancy for ~10^5 samples, so
  `schedule.joint.occupancy` stays numpy, tested equal to robot_msgs.coverage.occupancy cell by cell.
