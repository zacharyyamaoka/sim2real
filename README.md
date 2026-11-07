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

    /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/tools/twin_replays.py
    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/build_app.py
    python3 -I /home/bam/sim2real/tools/build_pages.py
    uv run --no-project --with playwright python /home/bam/sim2real/app/tests/test_app_flow.py
    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/app/tests/test_trajectory_contract.py --data --robotdx

Then the media (about 9 minutes the first time on a quiet machine, then only what changed; a cache folder, never git), and the site:

    env -u VIRTUAL_ENV MUJOCO_GL=egl /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -I /home/bam/sim2real/tools/build_media.py
    python3 /home/bam/sim2real/site/build.py

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
run page's next redesign: an entity tree on the left, the selected level's dashboard on the right). Each is also a dashboard of its own,
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

## Diagnostics

The stock diagnostics library is `robotdx.diagnostics` in `/home/bam/io-diagnostics` (lifted from `diagnostics_ref` at
1f0eb75; on io-diagnostics main since 8c89965; numpy via the `io-diagnostics[diagnostics]` extra). `diagnostics_ref/` is frozen
and superseded. This repo keeps the producer that runs the library on the real rack and writes the report's data:

    env -u VIRTUAL_ENV uv run --isolated --with "/home/bam/io-diagnostics[diagnostics]" python /home/bam/sim2real/tools/diagnostics_run_rack.py
