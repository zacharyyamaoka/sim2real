# Vendored data-ui

A built copy of data-ui, never edited here. Re-vendor it from data-ui; do not patch it in place.

- **Source:** `/home/bam/data-ui` `integrate/packet` @ `006e9d5` (2026-10-29, "test(p5): load_table follows a descriptor's path": PEP 0010 P3 navigation, CONTRACT §33 / PEP 0013; Add to dashboard, §34; P5 diagnostics and gates, §35; on top of P1b scene3d, P2 coverage, P4 parts and the kit gaps). **A trial: not merged to data-ui main.** Before: `a0b229b` (P1b), linked from the main checkout.
- **Built green:** `node build.mjs` (4.3 s); unit tests 652, 651 pass, 1 skipped, 0 fail (`node --test tests/unit/*.test.mjs tools/facets.test.mjs`); `tools/test_robotics_fixture.py` (5), `tools/test_check_robotics.py` (5), `tools/test_check_p3.py` (8), `tools/test_check_p5.py` (6) OK (with jsonschema, pyyaml).
- **How it was built:** `git -C /home/bam/data-ui archive 006e9d5 | tar -x -C <scratch>`, `node_modules` linked read-only from `/home/bam/data-ui/.wt/p1a-contract/node_modules` (the same package-lock.json as 006e9d5), `node build.mjs` in the scratch copy. Nothing in `/home/bam/data-ui` was written.
- **`dist/`:** the build's `dist/` without `site/` and the `*.map` source maps (13 MB, 142 files). `dist/manifest.json` still lists the maps' hashes; the pages never load them. `dist/LICENSES.md` names every bundled npm package and its licence.
- **`gallery/sim-to-real/`:** from `gallery/examples/sim-to-real/` at the same sha: `samples.json`, `media.json` + `media/`, `motors.json`, README.
- **`gallery/robotics/`:** the producer-facing contract at the same sha: `CONTRACT.md`, `schemas/`, `fixture.py` and `fixtures/difference/`.
- **`gallery/pid-tuning/media/ur5e_links.glb`:** from `gallery/examples/pid-tuning/media/` (Menagerie's UR5e meshes, BSD-3-Clause).

To update: rebuild data-ui (or a newer branch), then replace `dist/` and `gallery/` wholesale, record the new commit here and re-pin the site (`python3 site/build.py --repin`).

## What changed since a0b229b, and what the catalog-workbench site adopts (2026-10-29)

- **P3 navigation (§33):** a dataset whose `data:` names a placeholder (`runs/{run}/samples.json`) is read per pick; one-way links;
  `selected:` presets; a pick is a history entry, so Back / Forward restore it and t. The site's Runs tabs play the picked run below
  the runs table (the samples of one run fetched on a row click) instead of every run's.
- **P5 gate views (§35):** `tracker.column` (the gate matrix), `display: status` with one status vocabulary (RobotDx's order),
  `limits` on timeseries / plot (threshold bands), `kpi.target` from a property, roll-ups over a `tree:` with `display: status`, the
  peek's `record.sections[].view` and `display: link` (evidence), `trajectory3d.color` / `tolerance`, `voxels.scale: verdict`.
- **§34 Add to dashboard:** every panel's ⋯ menu gains "Add to dashboard…"; the site gives no `dashboards()` hook, so it copies
  the `.base` text to the clipboard.

Unchanged and re-checked on the site: the host's colour-slot resolution (`resolveTokens` + `toRgb`), the left filter rail
(`.dd-body.dd-has-rail` / `.dd-rail`), the `{deployment}` / `{run}` / `{station}` / `{device}` fill of the `.base` text.
