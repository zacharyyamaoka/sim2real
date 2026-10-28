# Vendored data-ui

A built copy of data-ui, never edited here. Re-vendor it from data-ui; do not patch it in place.

- **Source:** `/home/bam/data-ui`, branch `lane/dashboard-cards` @ `dbe1bd7` (2026-10-27, "docs: the dashboards report lists
  the judge round-1 fixes"). The brief named `50932e9`; the lane had moved 8 commits on (the judge round-1 fixes, PEP
  0008's one-clock driver), so the tip was taken. **Not merged to data-ui main** at the time of vendoring.
- **How it was built:** `git -C /home/bam/data-ui archive lane/dashboard-cards | tar -x -C <scratch>`, `node_modules`
  linked read-only from `/home/bam/data-ui/.wt/dashboard-cards/node_modules`, `node build.mjs` in the scratch copy.
  Nothing in `/home/bam/data-ui` was written.
- **`dist/`:** the build's `dist/` without `site/` and without the `*.map` source maps (5.8 MB instead of 78 MB).
  `dist/manifest.json` still lists the maps' hashes; the pages never load them. `dist/LICENSES.md` names every bundled
  npm package and its licence.
- **`gallery/sim-to-real/`:** inputs `dashboards/build.py` reads for CAN 14 (data-ui's own sim-to-real case, built by its
  `source/build_replays.py` from the real rack archive): `samples.json` (the 10-23 staircase, real vs the 10-23 twins),
  `media.json` + `media/` (the real RealSense clips), `motors.json`, and its README for provenance.
- **`gallery/pid-tuning/media/ur5e_links.glb`:** Menagerie's UR5e visual meshes as one GLB (data-ui's pid-tuning case,
  `source/build_robot.py`; BSD-3-Clause meshes), used by the 3D card at the 6-DOF and full-suite scales.

To update: rebuild data-ui (or a newer lane), then replace `dist/` wholesale and record the new commit here.
