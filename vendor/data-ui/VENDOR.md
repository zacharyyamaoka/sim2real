# Vendored data-ui

A built copy of data-ui, never edited here. Re-vendor it from data-ui; do not patch it in place.

- **Source:** `/home/bam/data-ui` branch `vendor/sim2real-d5ede93-s49` @ `190eba14` (2026-11-07): `main` @ `d5ede93` (the kit before, below) plus CONTRACT §49 backported (a table's `best`, column groups shown or hidden whole in Property visibility, `emptyGroups: hide`; on data-ui `main` as `69e6d5c4` + `14883a0f`, merged at `998a2d93`). Before: `main` @ `d5ede93` (2026-10-30, "test(perf oracle)": `integrate/packet` merged, the table `digits` fix cd5efe5, CONTRACT §36).
- **Built green:** `node bin/data-ui.mjs vendor 190eba14 --kit-dir dist --without site/ --also …` (data-ui's own vendor tool: a clean archive of the commit, built, every file checked against the build's manifest); on the branch, unit 764 tests, 761 pass, 3 skipped, 0 fail; `tests/browser/table_best_checks.py` 19/19; `table_oracle_checks.py` 111/111. The rebuilt d5ede93 code is byte for byte the kit before except §49's three files (`data-ui.js`, `data-ui.css`, `views/table.js`); lazy chunks differ in their hashed names only.
- **How it was built:** in 2026-10-30's vendoring, `git -C /home/bam/data-ui archive d5ede93 | tar -x -C <scratch>`, `node_modules` linked read-only, `node build.mjs`; since 2026-11-07, data-ui's vendor tool (`VENDOR.json` beside this file records the commit and every file's sha256).
- **`dist/`:** the build's `dist/` without `site/` and the `*.map` source maps (13 MB, 142 files). `dist/manifest.json` still lists the maps' hashes; the pages never load them. `dist/LICENSES.md` names every bundled npm package and its licence.
- **`gallery/sim-to-real/`:** from `gallery/examples/sim-to-real/` at the same sha: `samples.json`, `media.json` + `media/`, `motors.json`, README.
- **`gallery/robotics/`:** the producer-facing contract at the same sha: `CONTRACT.md`, `schemas/`, `fixture.py` and `fixtures/difference/`.
- **`gallery/pid-tuning/media/ur5e_links.glb`:** from `gallery/examples/pid-tuning/media/` (Menagerie's UR5e meshes, BSD-3-Clause).

To update: rebuild data-ui (or a newer branch), then replace `dist/` and `gallery/` wholesale, record the new commit here and re-pin the site (`python3 site/build.py --repin`).

## Why a backport and not data-ui main (2026-11-07, the models/routines/parameters lane)

sim2real's parameters view needed three things data-ui lacked (Zach, 2026-11-06: one column group per model, "color the models by row based on
what has the lowest error", "filter what model results we are showing"). They are CONTRACT §49, landed on data-ui `main`. Vendoring `main` itself
would also bring the 327 commits since d5ede93, and §47 among them changes a default: the one-row chrome folds a panel's tabs into a chip at
390 px and draws the rail's facet headings differently, and sim2real's site test reaches the old chrome (measured on 2026-11-07: with main's kit
the full site test failed "the filter bar sits left of the cards, by kind and by tags" and could not find the Why it fails panel by its tab at 390
px). So this kit is d5ede93 with §49 alone; moving sim2real to data-ui `main` is its own lane (the site test's chrome locators, its pages' toolbars,
the old app's flow test). Undo: re-vendor `d5ede93` and re-pin.

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
