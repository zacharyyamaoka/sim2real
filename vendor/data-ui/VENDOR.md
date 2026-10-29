# Vendored data-ui

A built copy of data-ui, never edited here. Re-vendor it from data-ui; do not patch it in place.

- **Source:** `/home/bam/data-ui` `integrate/packet` @ `a0b229b` (2026-10-29, "merge lane/p1b-scene3d @ 47785cb": PEP 0010 P1b,
  scene3d primitives and stage plus the trajectory3d viewer, CONTRACT §32), on top of 6f4a72e (P1a, the robotics contract) and
  dd53748 (main 56e08be + dashboard-cards + legend-toggle + live + P0). **A trial: not merged to data-ui main** (main is still
  56e08be on 2026-10-29). Built green: `node build.mjs`; unit tests 505 of 506 pass, 0 fail (`node --test tests/unit/*.test.mjs
  tools/facets.test.mjs`); `tools/test_robotics_fixture.py` and `tools/test_check_robotics.py` (with jsonschema, pyyaml) OK.
  The robotics contract files are byte-identical to 6f4a72e's. Before: 6f4a72e, dd53748, `lane/dashboard-cards` @ `dbe1bd7`.
- **How it was built:** `git -C /home/bam/data-ui archive dd53748 | tar -x -C <scratch>`, `node_modules` linked read-only from
  `/home/bam/data-ui/.wt/p1a-contract/node_modules` (the same package-lock.json), `node build.mjs` in the scratch copy. Nothing in
  `/home/bam/data-ui` was written.
- **`dist/`:** the build's `dist/` without `site/` and the `*.map` source maps (13 MB). `dist/manifest.json` still lists the maps'
  hashes; the pages never load them. `dist/LICENSES.md` names every bundled npm package and its licence.
- **`gallery/sim-to-real/`:** from `gallery/examples/sim-to-real/` at the same sha: `samples.json`, `media.json` + `media/`,
  `motors.json`, README (CAN 14's 10-23 staircase and its real RealSense clip, read by `dashboards/build.py`).
- **`gallery/robotics/`:** the producer-facing contract at the same sha: `CONTRACT.md`, the 13 `schemas/*.schema.json` +
  `channels.json`, `fixture.py` and `fixtures/difference/` (seed 20261029). `tools/trajectory.py` validates every table the app
  writes against these schemas and `app/tests/test_trajectory_contract.py` runs the fixture.
- **`gallery/pid-tuning/media/ur5e_links.glb`:** from `gallery/examples/pid-tuning/media/` (Menagerie's UR5e meshes, BSD-3-Clause).

To update: rebuild data-ui (or a newer branch), then replace `dist/` and `gallery/` wholesale and record the new commit here.

## What this vendor let sim2real drop (2026-10-29)

- `dashboards/host.js` no longer creates `<data-dashboard>` with its src already set: it sets src after connecting (P0 #13).
- `dashboards/build.py`'s Visual home (rack) is no longer pinned to one run set: a Run set picker on the 3D rows, and the clock
  spans the picked set (4.48 s for the 8 motors, 35.99 s for CAN 14's staircase; P0 #1).
- `app/app.js` switches the gates layer by setting the dashboard's src in place (no page reload; P0 #13).
- Legends toggle (legend-toggle): app/tests/test_app_flow.py checks a click hides a series and a second click shows it.

Unchanged and re-checked: the host's colour-slot resolution (`resolveTokens` + `toRgb`, quoted hex) and the rail-on-the-right CSS
(`.dd-body.dd-has-rail` / `.dd-rail` are the same classes).
