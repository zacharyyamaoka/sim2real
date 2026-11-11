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

**Desktop app (Stable / Preview).** `stable-preview.json` adopts Zach's shared package (`/home/bam/stable_preview_switcher`, skill `stable-preview-switcher`); the dock icon is **sim2real** (click = Stable on :4820; right-click: Open Preview, Make Preview Stable, Roll Stable Back). Preview (:4821) rebuilds `site/build.py` into `dist/site` whenever `site/`, `type_cards/`, `sysid/`, `brand/`, `tools/` or `app/registry.json` change; Stable builds the same site from the pinned commit. Neither touches `~/.cache/sim2real/site` or the hand-started `serve.py`. WHY the data prefixes are proxied: the built site symlinks its 3.8 GB of run folders (`data/source`, `runs`, `why`, `dx`, `coverage.json`) into the main checkout's `app/data`, and the runtime refuses a file that resolves outside the site, so a small `http.server` process (:4822 Stable, :4823 Preview) answers those prefixes from `app/data`; the media (`/media/`, `tools/build_media.py`'s cache folder, linked the same way) have their own (:4824 Stable, :4825 Preview) over `~/.cache/sim2real`. Stable is therefore pinned in code and pages but reads the live `app/data`. Not in the channels: the old app at `/app/` and `/dashboards/` (run `serve.py` for those).

    python3 /home/bam/.local/share/stable-preview-switcher/runtime/sps.py --root /home/bam/sim2real open
    python3 /home/bam/.local/share/stable-preview-switcher/runtime/sps.py --root /home/bam/sim2real open --preview

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

    /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/tools/twin_replays.py
    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" --with-editable /home/bam/robot_msgs python /home/bam/sim2real/tools/build_app.py
    python3 -I /home/bam/sim2real/tools/build_pages.py
    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --with playwright python /home/bam/sim2real/app/tests/test_app_flow.py
    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/app/tests/test_trajectory_contract.py --data --robotdx

Every recorded run is read as robot_msgs' `JointTrajectory` (`/home/bam/robot_msgs`; Zach, 2026-11-10: every package depends on robot_msgs)
through one door, `tools/run_files.py`: q / qd / tau as positions / velocities / effort, every other column a channel, built exactly as the
producer's own `bam_rack_twin.msgs.run_trajectory` (held equal to its `runs/joint_trajectory/` files in `tools/tests/test_run_files.py`).
sim2real has no pyproject: `build_app.py`'s command carries robot_msgs as `--with-editable`, and sysid's runtime (bam_rack_twin's venv) has
it as bam_rack_twin's own editable dependency. Coverage's binning rule is `robot_msgs.coverage` too (`type_cards.coverage` re-exports it and
keeps every type's axes and gates), so the type cards, the site build and their tests all run with `--with-editable /home/bam/robot_msgs`. The oracle's simulated arm excitations and belt runs are robot_msgs trajectories too.

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" --with-editable /home/bam/robot_msgs --with pytest pytest -q /home/bam/sim2real/tools/tests/test_run_files.py

Then the media (about 9 minutes the first time on a quiet machine, then only what changed; a cache folder, never git), and the site:

    env -u VIRTUAL_ENV MUJOCO_GL=egl /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/tools/build_media.py
    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs python /home/bam/sim2real/site/build.py

`tools/build_media.py` writes `~/.cache/sim2real/media` (or `$SIM2REAL_MEDIA`), which the site serves at `/media/` (Zach, 2026-11-07: "a
bit more media rich ... we can basically always have a 3D view ... in these cards I was hoping to see an image of the actual deployment"):

| media | what | from |
|---|---|---|
| `scenes/<id>.jpg` | a MuJoCo render on top of each oracle card and each deployment | each sysid example's MJCF (`sysid.describe` composes it), the rack's cad2robot payload |
| `<dep>/stations/<station>.glb` | the station's output link for the run page's 3D card | drawn from its twin's MJCF: the disc, the 100 mm marker, the twin's gravity load |
| `<dep>/runs/<run>/links.json` | the link's pose per series at each t (data-ui's robotics `links` table) | the run's samples: a turn about the joint axis by each series' q |
| `<dep>/runs/<run>/media.json`, `real_<serial>.mp4`, `sim.mp4` | where the session filmed the station: the camera cut onto the run's clock, beside MuJoCo's render of the link on the same frames | the session's D405 recording (`cameras/cam_<serial>.mp4` + its stamps), bam_rack_twin's camera map |

A run with clips plays them on its Playback (`views/run-media.base`) above the 3D card; every run page says what you are looking at
and, for each model it plays, what the model is and its parameters (its own MJCF, or the identification file's points). Built without
the media, the site shows every page as before.

The 3D view, the clips and the "what you're looking at" words are components scoped to an entity (`site/components.py`: `joint_3d` for a
joint, `camera_clip` for a camera, `joint_render` for a joint; `what_joint` / `what_camera`), so a page drops them in per entity level (the
run page does: its station's level has the joint's, a camera's level that camera's clip). Each is also a dashboard of its own,
`views/components/<name>.base`, its entity in the URL's query (`?deployment=…&run=…&station=…&device=…&glb=…` or `&camera=…`);
`/components/` mounts each one for a real entity. The run page is composed of the same views (`components.compose`).

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
| `src/sim2real/` | the library (`pyproject.toml`): `metrics/ schedule/ fit/ sim/ models/ cards/`, each importing only the folders to its left (`tests/test_layers.py`; `docs/decision-package-layers-2026-11-10.md`). `cards/` is the type cards, moved from `type_cards/` unchanged. Since step 4: `metrics/` holds the actuator verbs and the servo gates T1-T11 (RobotDx's stock checks and bam_rack_twin's acceptance call them), `schedule/joint.py` the 1-DOF test schedule generator (bam_rack_twin plays it), `cards/servo_gates.py` their targets as data (`docs/decision-actuator-verbs-2026-11-10.md`) |
| `type_cards/` | a shim: `type_cards.<name>` is `sim2real.cards.<name>`, `python -m type_cards.report` still runs, its data paths link to the moved files, and `type_cards/tests` stays here as the ruler that held the move |

## Deployment tree, run tags, config snapshots

`site/deploy_tree.py` (run by `site/build.py`) gives each deployment a tree in RobotDx's shape: the deployment, each fdcanusb
adapter its bam_rack_twin record wires its boards to (`adapter_serial`), each station. Every node carries the gate cells under it
(passing of cells, the worst). Each run gains, in the site's `runs.json` and `/runs/`:

| column | what |
|---|---|
| `node_0` … `node_k` | the run's station and its ancestors as path ids (`one-dof-test-rack/fdcanusb-0607623A/can11`); the rail's tree facet reads them, each level labelled with its node's gate cells passing |
| `environment` | `sim` (no hardware moved), `bench` (a test run on real hardware), `real` (a segment of live deployed data), else `unknown`: the registry's declared tag, only for a run whose basis fits and whose recording lies in the deployment's archive days |
| `setting` | `type_cards` SETTINGS: `bench` (in the office) or `deployed` (in a customer's facility), else `unknown`, by the same rule |
| `test_type` | the type_cards `TestType.id` a run recorded; none is recorded today |
| `config` | `full` when the run's session recorded its board's whole config (bam_rack_twin.hardware session.json `board_configs`, the `.cfg` file's key lines hashing to its sha256), else `not recorded`; `config_detail` says what is recorded |
| `excitation`, `closed_loop`, `offline_scope` | the v3 run tags (type_cards `domain.run_tags`, from the run's kind as bam_rack_twin.hardware's code says, cited per kind): `driven`, `free response`, `mixed` (a swing released to coast; a heating run, then its cool-down) or `unknown`; whether the board's feedback acted; and which configs a model may be judged on the run under (`its own config` for a closed-loop run, `any config` for a free response) |

## Domain model v3

`type_cards/CONTRACT.md`, "Domain model v3" (decision: `docs/decision-domain-model-v3-2026-11-07.md`) is the contract the pages build
against: deployments (`virtual`: the six oracle examples and the noise ladder's scenario `ur5e_backlash`; `physical`: the rack), every node of
their trees a deployment of its own, eleven
generic entity types with one model ladder each in families (`M2.kinematics.geometric`, `M4.dynamics.twin`), pinned metrics, diagnostics,
coverage over any selection of runs (`type_cards/selection.py`), the parameters table with a column group per routine and model, and
frozen reports (`type_cards/frozen_reports/`). The type level is committed (`type_cards/domain_v3.json`, `python3 -m type_cards.domain
--write`); the site build writes the rest to `OUT/data/domain/` (`deployments.json`, `parameters.json`, `selections/<dep>.json`,
`coverage_cells/<dep>.json`, `metric_values/<dep>.json`, `reports/<id>.json`). The deployments pages, the run page and the metrics page read them
(below).

**Deployments pages** (`site/deployments_pages.py`, decision: `docs/decision-deployments-pages-2026-11-07.md`): `/deployments/` is the index,
a left filter bar (kind, tags; data-ui's rail) over data-ui cards of the eight deployments, each with its render; every node of every tree has
its page at `/deployments/<node id>/`: its tree on the left (`site/ui_shared.py` `entity_tree`; the run page's is `status_tree`, beside it), its
sub-deployments, its runs, the models per entity type, and its pinned metrics and coverage over all of its runs (`sel.compute`). The rack's
record page (`/one-dof-test-rack/`: gates, why it fails, evidence) and each oracle example's page (`/sysid/<id>/`) stay, linked both ways.

**The run page** (`site/run_pages.py`; decision `docs/decision-run-page-2026-11-07.md`): the run's entity tree in the left column (the
contract's tree: deployment, adapter, station, the station's parts, the cameras that see it; RobotDx's device tree, `ui_shared.status_tree`:
a dot per node at its level in this run, search, collapse and expand, its width dragged and remembered) and on the right the picked level's
dashboard: pinned and other model-independent metrics, diagnostics with their levels, coverage for this run (`sel.compute([run])`), then what
that level captured (the station's Playback tabs, a camera's clip, a part's channels as `views/levels/<type>.base`), and the models in their
own section. Every level heads with the run's tags and Zach's caveat (offline evaluation judges models, not tracking under changed feedback).
A level is a link: `/<deployment>/runs/<run>/?entity=<node id>`.

## Models, routines, parameters

**The home opens on the types** (Zach, 2026-11-11; `docs/decision-types-seam-2026-11-11.md`): a Types section first, one tile per generic type
in `cards.domain.TYPE_ORDER` (icon, name, group, today's model, parameters, where it is used) opening `/models/<type>/`; Models · Routines ·
Parameters lead the Choose column and are the header's links (Why it fails and Analysis moved to the Account menu: five links overlapped the search).

`site/models_pages.py` (decision: `docs/decision-models-routines-parameters-2026-11-07.md`): `/models/` lists the eleven generic types, and
`/models/<type>/` is a type's model ladder, one table per family, with Zach's columns (rung, model, parameters, adds, identified here) and where each
model is used (the oracle examples' fits, and the rack's stations by the producer's model labels, which `type_cards/deployments/one_dof_test_rack.py`
maps to the ladder: every one is the servo's `M4.dynamics.twin`); every deployment page's models link to their ladder rows. `/routines/` is every
calibration routine both ways (routine -> parameters, parameter -> routines), each routine's setting, time, cost, equipment, its recovery and verdict
at every level of the noise ladder (0x, 1x, 3x, 10x: pass, fail, or not run and why) and status. `/parameters/` is the contract's parameters table in
data-ui: four presets (all, winning model, with results, errors only; each a set of rows showing every model's column group, the example's own fit
first in all and winning model), a column group per (routine, model), each row's least error marked, a model's group shown or hidden from
Properties (data-ui CONTRACT §49, vendored as a backport onto d5ede93: `vendor/data-ui/VENDOR.md`).

## Metrics over a selection, and reports

Decision: `docs/decision-metrics-reports-2026-11-07.md`. Zach (2026-11-06): "its just the row model you can basically like include or not what
runs will be included in the metrics/diagonistics etc"; "Reports ... freeze it ... even as you add more data".

**`/metrics/<dep>/`** (`site/metrics_pages.py`, `static/metrics.js`): the runs table (data-ui, selectable; its rail in the left column, presets
above it: every run, each station, each day, each split) and beside it what the runs in play give: each station's pinned metrics (the median,
min to max, the count; every model of a fidelity metric), its diagnostics' levels, its parts' metrics and its coverage against the gate; every
diagnostic and metric in data-ui tables; the coverage heatmap (q x qd, each cell shaded by the share of its qdd bands visited; blank where the
joint cannot reach); the command that freezes the selection. The runs in play are the ticked rows, else every row the filters leave. The page
computes them by the contract's browser rule (`type_cards/CONTRACT.md`, "Domain model v3"), with data-ui's own `summarize`; the site test holds
every number to `selection.compute` for three selections made in headless Chrome. `?report=<id>` ticks a report's runs; every deployment page with
runs links its metrics page with its stations picked.

**`/reports/`** (`site/reports_pages.py`): every frozen report and its page, read from its snapshot (metrics, diagnostics with their levels,
gates, coverage, models, parameter rows, its rows, and since 2026-11-07 its parts' titles and the ladder model each label named), never
recomputed; the three reports frozen before snapshots kept titles and labels say on their page that those are today's. Make one from a selection (it writes `type_cards/frozen_reports/<id>.py` and
`<id>.json`; commit both):

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --directory /home/bam/sim2real python -m type_cards.report freeze --id my-report --title "…" --question "…" --deployment one-dof-test-rack --select "device=CAN 11" --select "split=held_out"

**The per-run model-independent metrics** (`tools/run_metrics.py`, written last by `tools/build_app.py`, or alone in about 6 s): RobotDx's catalog
entries `servo.stop_error` (p90 at every dwell, T4's scan) and `driver.saturation` (rows on the torque cap) on each run's npz, to
`app/data/<dep>/run_metrics.json`. With each station's limits in `type_cards/deployments/one_dof_test_rack.py` (its stop allocation and loop rate,
from bam_rack_twin), the run pages' station and driver dots show real levels.

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/run_metrics.py
    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" --with pytest pytest -q /home/bam/sim2real/tools/tests/test_run_metrics.py

## Diagnostics

The stock diagnostics library is `robotdx.diagnostics` in `/home/bam/io-diagnostics` (lifted from `diagnostics_ref` at
1f0eb75; on io-diagnostics main since 8c89965; numpy via the `io-diagnostics[diagnostics]` extra). `diagnostics_ref/` is frozen
and superseded. This repo keeps the producer that runs the library on the real rack and writes the report's data:

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/diagnostics_run_rack.py
