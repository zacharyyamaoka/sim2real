# Decision: Zach's kinematic-calibration simulation results on W&B, project "Kinematic Calibration" (2026-11-12)

**Status:** accepted; settled in the brief, built as specified. Code: `src/sim2real/tracking/kincal.py`; test:
`tests/test_kincal_tracking.py`.

## Context

bam_calibration (bam_ws, `src/core/mdp/setup/bam_calibration`) holds two simulation ledgers: v1 (`kincal-run/1`, 348 rows, 52 cells, questions
Q0-Q9) and v2 (`kincal-run/2`, UR's own dual-arm method rebuilt from patent US 9,248,573 on two UR5e arms on UR's calibration "horse", 116 rows,
several batches re-running the same (cell, seed)). Zach wants them where he reads trained-model results: W&B, as a project of its own.

## Decision

- **One project, "Kinematic Calibration"**, entity `zach-yamaoka-independent`, written with the same helpers as the Homing project
  (`wandb_log.push`, `retire`, `run_id`, `browser_url`) and the house black-box template (`bam_trackio.bbo`, loaded by file via `rigs.load_bbo`).
- **v2: one run per (cell, algorithm)**, group = cell, summary = K4d position mean of the worst arm over seeds (median, min, max), the p95,
  `before`, the floor, the paired ratio vs A0, wins vs A0, converged and UR-accept rates, runtime; a `seeds` table. **v1: one run per cell**,
  group = question. **One Weave leaderboard, v2 only**: rows the algorithms, columns cell x metric (a Weave leaderboard compares only within
  one project, so the algorithms of every cell share it).
- **The ledgers are extracted once into a compact JSON** (`src/sim2real/data/kincal_ledger_2026-11-12.json`, per-seed numbers, the source paths,
  row counts and git shas). WHY committed: the raw ledgers sit in a gitignored bam_ws worktree that a disk sweep can delete. `extract --v2` is
  repeatable (ledgers are unioned), so a later BAM cell logged from another ledger joins without a code change.
- **The newest ok row per (cell_id, seed_index) wins** (compared as instants, not strings). Re-runs of the same cell and seed are not extra seeds.
- **The paired ratio is the median of per-seed ratios alg/A0**, not a ratio of medians: all algorithms of a cell see the same dataset per seed.
  A seed whose A0 is zero has no ratio.
- **The worst arm's p95 is the p95 of the arm that is worst by K4d mean** (`kpi.worst_arm.arm`), per algorithm and seed.
- **Nothing is deleted.** bbo's `delete_unended` and `prune_superseded` are switched off exactly as in homing.py; a changed number is a new
  evaluation (content digest of the per-seed numbers, the baseline's and the code shas; timings and timestamps excluded), the older runs are
  marked `superseded` by `retire`, and the same numbers map to the same run ids.

## Consequences and limits

- A cell need not run every algorithm: BAM cells will lack the UR-only ones; runs, ratios and leaderboard rows exist only where the algorithm ran.
  Run tags carry the arm from the row's `setup.arm` (UR5e rows: `ur5e`).
- A row's per-parameter recovery block, when present on an algorithm record (key `parameter_recovery`, `recovery` or `parameters_recovery`;
  a list of dicts or `{parameter: number | {field: number}}`), becomes a `parameters` table on that run. The key is a guess made before any such
  row exists; check it against the first BAM ledger.
- The R0 cells (exact data, zero budget) have K4d errors of order 1e-13 mm; their ratios vs A0 are floating-point noise, shown as logged.
- Units keep the source names (`_mm`, `_mrad`); no angle is converted.
- No decision record is needed beyond this page: nothing here is an architecture fork, it is a logger over existing results.
