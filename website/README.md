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

## Where everything comes from

| page | source |
|---|---|
| `/types/<type>/` (the model-rung table and the routines table) | `sim2real.cards.domain` (TYPE_ORDER, entity_type, routines_identifying), `cards/calibration.py` ROUTINES |
| `/models/<type>/<model>/`, `/parameters/<type>/<name>/` | `cards/domain.py` |
| `/routines/`, `/routines/<id>/` (recovery at 0x / 1x / 3x / 10x) | `cards/calibration.py`, `schema.equipment_cost`, `sim2real.calibration.recovery` (the one reader) |
| `/examples/<name>/` | `website/examples/<name>.py` verbatim and `<name>.out.json` (its real output, stamped with the snippet's sha256) |
| `/api/` | docstrings of `sim2real.RobotTwin` and every name in `sim2real.calibration.__all__` |
| `/docs/guide/`, `/docs/calibrate/` | `docs/API.md`, `docs/CALIBRATE.md` (when it exists) |

- **Shared with robotmsgs.com:** `site/site.css` and `site/site.js` are robot_msgs commit b4c8d36's, byte for byte (`site/PINNED.json`);
  `build/highlight.py` and `build/serve.py` are copied as is; `pages.py`'s shell, sidebar and code block are robotmsgs' with brand, nav
  and footer parameters. `site/sim2real.css` holds the accent (BAM green) and the calibration tables.
- **New registries go in the registries, never here:** a new type, model, routine or recovery ladder appears on the next build with no
  edit to this folder.
- **Not deployed.** A Cloudflare Worker like robotmsgs.com's is a follow-up: the domain is Zach's pick. `sitemap.xml` uses the placeholder
  origin `https://sim2real.example` until then (`build.py --origin`).
- The old catalog app (`site/` at the repo root) is separate and left alone.
