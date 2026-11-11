# Decision: the sim2real package's folders, ordered by stability (2026-11-10)

**Status:** accepted. Zach picked it in chat on 2026-11-10 ("Sim2Real as a Pure Library on robot_msgs — 3 Proposals", his picks:
proposal 2, folders by stability). The package skeleton and the type cards' move landed alone, as a contract barrier.

## Context

Proposal 2 splits the work in two. robot_msgs holds the nouns and any numpy-only math with a textbook definition; `robot_msgs.compare`
and, since today, `robot_msgs.coverage` are already there. A second package holds the verbs: fitting, schedules, thresholds, choosing a
model. Zach: the second package *is* sim2real, importable as `sim2real` from `src/sim2real/` in this repo. The site, dashboards and
catalog stay app folders beside it, outside the package.

What changes how fast is the question. Zach: the evaluation is stable, the models churn, the fitting methods are fairly standard, and
the simulators are a step up from those.

## Decision

```
src/sim2real/
  metrics/    data in, numbers out, per modality; coverage; floor ratio; gate(value, target)   most stable · robot_msgs + numpy
  schedule/   description -> test schedule, with coverage known before running
  fit/        standard methods: least squares, rung-ladder selection, hidden-truth oracle; defines the Model protocol
  sim/        evaluation environments: MuJoCo plant, replayer                                    extra: mujoco
  models/     the rungs per type (servo M0…M7, camera, SerialChain, ParallelChain); implement fit's protocol   churns
  cards/      data only: which metrics, gates and coverage each type uses; gate targets          churns most
```

- **Each folder imports only the folders to its left.** Nothing stable may import something that churns, so a new servo model lands
  in `models/` without touching `metrics/`, and a changed gate target is a `cards/` data edit.
- **The rule is a test**, `tests/test_layers.py`: it reads every module's imports (absolute and relative) and fails on a rightward one.
  It is held red on planted violations, so a checker that passes everything cannot pass. A layer's own `tests/` may reach anything.
- **`sim2real/__init__.py` imports no layer**, so importing `sim2real.metrics` never loads `cards`.
- **`cards/` is `type_cards` moved unchanged:** schema `sim2real.type_cards/2`, the additive-only contract (`cards/CONTRACT.md`) and
  every module. Its imports now name `sim2real.cards`, and its repo paths count from the new depth. It defines no parameter or range
  type of its own: datasheet values are `robot_msgs.space.Value`, and range checks are `Space(msg).contains` / `.violations`.
- **`type_cards` stays importable as a shim** (`type_cards/__init__.py`): `type_cards.<name>` is the same module object as
  `sim2real.cards.<name>`, and `python -m type_cards.report` still runs. type_cards' data paths (`arm_reachable/`, `frozen_reports/`,
  `references_checked.json`, `CONTRACT.md`) are symlinks to the moved files. `type_cards/tests` stays where it was, byte for byte, and
  is the ruler that held the move.
- **pyproject:** robot_msgs is an editable path dependency, and mujoco (`==3.11.0`, bam_rack_twin's pin) is the `sim` extra.

## Consequences

- Steps 4 to 6 fill the empty folders: the actuator gates T1-T11 and `schedule.py` out of bam_rack_twin into `metrics/` and `schedule/`,
  then `SerialChain` / `ParallelChain` in `models/` and `cards/`, then the camera verbs.
- `cards/coverage.py` holds each type's axes, edges and reachable rule (policy) and re-exports `robot_msgs.coverage`. When step 4 moves
  the per-modality coverage verbs into `metrics/`, the type's axes stay in `cards/` as data.
- Old commands keep working through the shim; new code imports `sim2real.cards`.
