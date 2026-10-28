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
