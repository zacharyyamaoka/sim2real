# sim2real

How close each digital twin is to its real hardware, and where it falls short. Dashboards over paired real/sim runs, sliced
by sensor and actuator, with derived quantities (end-effector pose) one level up. Built on data-ui (`/home/bam/data-ui`):
every page is a `.base` dashboard or an analysis over datasets the producers write. Nothing here measures hardware itself.

- **Asked by:** Zach, 2026-10-27: "lets just refer to this as sim2real we don't need a seperate thing for it right now...
  lets call the repo that though."
- **Ruler (every modality):** run one stimulus on the real device and on its twin, take an error metric, divide it by the
  real device's own run-to-run floor. ≤ 1.5× = twinned. Only the stimulus and metric change per sensor/actuator type.
- **Producers (they write the data, this repo only reads it):** `bam_ws` `src/dev/bam_rack_twin` (rack servos, gates
  T1-T11), pidtuna, traj_compare, Rerun recordings.
- **Catalog:** robotparts.dev holds the part, its datasheet and the published summary; this repo holds the drill-down.

## The app (home page)

`python3 /home/bam/sim2real/serve.py` serves the catalog-workbench site at `/` (build it with `python3 /home/bam/sim2real/site/build.py`) and keeps the old app at `/app/`: **deployments → one deployment
(its runs newest first, coverage) → one run (playback of real vs every model on one clock)**, each with a **Gates layer**
switch in the header that adds the diagnostics computed from the same runs. The five proposals stay at `/dashboards/`.

| path | what |
|---|---|
| `app/registry.json` | the deployments registry (start: the One Dof Test Rack, its bam_rack_twin record and archive days) |
| `app/*.base` | the pages, written by `tools/build_pages.py` (playback page, and `-gates` = the same page plus the gates layer) |
| `app/index.html`, `app.js`, `app.css` | the host: routes (`?d=` / `&run=` / `&layer=gates`), the lockup, the rail on the right |
| `app/data/` | generated, gitignored |
| `app/tests/test_app_flow.py` | Playwright click-through (deployment → rack → run → playback, colours, order, gates toggle) |

Build the data (about 20 s; the twin replays are optional and take about 1.5 min):

    /home/bam/bam_ws/.claude/worktrees/sim-to-real-motor-models-f1ee43-v5/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/tools/twin_replays.py
    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/build_app.py
    python3 -I /home/bam/sim2real/tools/build_pages.py
    uv run --no-project --with playwright python /home/bam/sim2real/app/tests/test_app_flow.py
    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/app/tests/test_trajectory_contract.py --data --robotdx

The run tables (`runs.json`, `devices.json`, and per run `samples`, `poses`, `diff_samples`, `diff_poses`) are data-ui's
robotics contract v1 tables (`vendor/data-ui/gallery/robotics/CONTRACT.md`, CONTRACT §32), checked against its 13 schemas
as they are written. `tools/trajectory.py` computes difference(a, b) and reproduces data-ui's fixture exactly.

## Layout

| path | what |
|---|---|
| `dashboards/` | the data-ui dashboard proposals and, once picked, the pages |
| `brand/icons/` | the app icon proposals |
| `reports/` | review reports (`reports/media/` is gitignored) |
| `docs/` | decisions |

## Diagnostics

The stock diagnostics library is `robotdx.diagnostics` in `/home/bam/io-diagnostics` (lifted from `diagnostics_ref` at
1f0eb75; on io-diagnostics main since 8c89965; numpy via the `io-diagnostics[diagnostics]` extra). `diagnostics_ref/` is frozen
and superseded. This repo keeps the producer that runs the library on the real rack and writes the report's data:

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/diagnostics_run_rack.py
