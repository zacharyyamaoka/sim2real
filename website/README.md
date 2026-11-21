# sim2real docs site

robotmsgs.com's shape over sim2real's registries (PEP 0001, `docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md`, sections 10-11):
Types -> model rungs -> parameters -> calibration routines -> examples -> API reference -> guides.

Build (seconds; reads the registries, never runs a calibration, never writes a tracked file), then serve:

    cd ~/sim2real && env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python website/build/build.py
    cd ~/sim2real && python3 website/build/serve.py 4731

Test (`tests/test_docs_site.py`, the acceptance tests the builder may not edit):

    cd ~/sim2real && env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q tests/test_docs_site.py

Re-record an example's real output (heavy: the pendulum about 15-27 min, the wrist tens of minutes; it needs bam_rack_twin's venv):

    cd ~/sim2real && systemd-run --user --scope -p MemoryMax=16G -p OOMPolicy=continue -- env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src:/home/bam/sim2real /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python website/build/record_examples.py pendulum_can11

## The landing page (`/`)

The home page is the landing (Zach, Daily Note 2026-11-20): his three metrics (Sim / Sim on Real / Sim on Real (tuned)) on each row of
the pendulum, the UR arm and the BAM arm, each cell led by its tool error at a stop and its gate verdict; the three modes; how it works; the API on one screen; bench vs deployed (lifetime calibration and
monitoring, designed, not built; the design is `docs/DEPLOYED.md`); and where every number comes from.

- **Every number comes from a file.** `build/landing_picks.py` names each number's file and key (and holds the page's claims as
  templates); `build/export_landing.py` reads the numbers out of those files into `data/landing.json`, which the build only reads. A
  number nobody measured is a status ("not measured yet") with its reason, never a typed value.
- **Lab files are cited from snapshots**, copied byte for byte once to `/archive/datasets/sim2real_landing/<date>/` (`--snapshot`);
  `landing.json` carries logical names only (`lab:`, `amb:`, `rackq:`, `snap:`), since the repo is public.
- **Pictures** are cut from real recordings into `site/media/` (`--media --sheets DIR`), WebP and JPEG only (the cloud cut drops video),
  and each one's frames are looked at before it is recorded as checked (`--frames-checked-by WHO`).
- The ruler is `tests/test_landing_page.py` (never run on the workstation while an arm is powered: bam_ws `tools/cloud`).

Re-export after a source moves (light: JSON reads only), then check it with the ruler's own `recheck()`:

    cd ~/sim2real && env -u VIRTUAL_ENV nice -n 19 ionice -c3 taskset -c 2-5,16,17 /home/bam/sim2real/.venv/bin/python website/build/export_landing.py --snapshot
    cd ~/sim2real && env -u VIRTUAL_ENV nice -n 19 ionice -c3 taskset -c 2-5,16,17 /home/bam/sim2real/.venv/bin/python website/build/export_landing.py --check

A source snapshot is never rewritten: a lab file that moved keeps its old snapshot until `landing_picks.SNAPSHOT_DATE` moves to a new
folder. The build prints `STALE landing source` when an in-repo source changed since the export.

## Where everything comes from

| page | source |
|---|---|
| `/types/<type>/` (the model-rung table and the routines table) | `sim2real.cards.domain` (TYPE_ORDER, entity_type, routines_identifying), `cards/calibration.py` ROUTINES |
| `/models/<type>/<model>/`, `/parameters/<type>/<name>/` | `cards/domain.py` |
| `/routines/`, `/routines/<id>/` (recovery at 0x / 1x / 3x / 10x) | `cards/calibration.py`, `schema.equipment_cost`, `sim2real.calibration.recovery` (the one reader) |
| `/examples/<name>/` | `website/examples/<name>.py` verbatim and `<name>.out.json` (its real output, stamped with the snippet's sha256) |
| `/api/` | docstrings of `sim2real.RobotTwin` and every name in `sim2real.calibration.__all__` |
| `/` (the landing) | `data/landing.json` (from `build/landing_picks.py` via `build/export_landing.py`), the registries' counts |
| `/docs/guide/`, `/docs/calibrate/`, `/docs/deployed/` | `docs/API.md`, `docs/CALIBRATE.md`, `docs/DEPLOYED.md` |

- **Shared with robotmsgs.com:** `site/site.css` and `site/site.js` are robot_msgs commit b4c8d36's, byte for byte (`site/PINNED.json`);
  `build/highlight.py` and `build/serve.py` are copied as is; `pages.py`'s shell, sidebar and code block are robotmsgs' with brand, nav
  and footer parameters. `site/sim2real.css` holds the accent (BAM green) and the calibration tables.
- **New registries go in the registries, never here:** a new type, model, routine or recovery ladder appears on the next build with no
  edit to this folder.
- **Not deployed yet.** `wrangler.jsonc` is a static-assets Worker like robotmsgs.com's, with a preview only:
  `pnpm --dir /home/bam/sim2real/website run deploy:preview` builds with `--noindex` (robots `Disallow: /`, a noindex meta on every
  page) and uploads to `sim2real-docs-preview.<account>.workers.dev`; `wrangler delete --env preview` undoes it. The production domain is
  Zach's pick; a prod deploy passes `--origin https://<domain>`. `sitemap.xml` uses the placeholder origin `https://sim2real.example`
  until then.
- The old catalog app (`site/` at the repo root) is separate and left alone.
