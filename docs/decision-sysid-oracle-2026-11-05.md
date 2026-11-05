# Decision: how the system-ID oracle keeps itself honest (2026-11-05)

**Status:** accepted on merge (sim2real main, sysid/). Decided for Zach by the oracle lane; his to overrule.

## Context

Zach's Nov 5 workflow (PROJECT - Sim2Real, "What does success look like to me?") makes the simulator the first "real" hardware:
"if we assumed the simulator data was real, we should check that our system ID can match the real values ... the base oracle check
for all of this". An oracle is only worth having if it can fail, and three easy shortcuts make one that cannot: a fit that peeks at
the truth, a tolerance the description's own nominal already meets, and a landing page that shows numbers no test holds.

## Decision

- **The truth is sealed.** Each example's hidden values live in `sysid/examples/<id>/world.json`, read only through
  `sysid.world.load`, which raises inside `world.sealed()`; `sysid.oracle.run` seals it around every `identify`, and identify only
  ever receives the train split's measurements. The acceptance test also reads every identify function's source for the words.
- **The ruler is data, pinned, and can fail.** `sysid/acceptance.json` (tolerances from what the use needs, held-out factors, the
  drift gates) was committed before any identification code; `sysid/tests/test_oracle.py` pins its sha256, requires every hidden
  value to be gated exactly once, and requires every gated parameter's NOMINAL value to fail its own tolerance. A world can be
  wrong (the HSI gains were, and moved); a tolerance is not loosened to pass.
- **Results are committed data; the site is stdlib.** `python -m sysid all --write` writes `sysid/results/*.json`; `site/landing.py`
  renders only those files (no MuJoCo, no scipy at site build time), and the test re-runs every example and requires the committed
  numbers to equal this code's to 1e-9.
- **bam_ws is imported in place, at its main.** The CAN 11 example runs bam_rack_twin's own schedule, twin, replayer, smoother and
  bootstrap from `/home/bam/bam_ws/src/dev/bam_rack_twin` (its venv runs the pipelines); nothing is vendored. The result records the
  bam_rack_twin commit; the freshness test is the tripwire when a peer changes it.

## Consequences

- A change to bam_rack_twin's twin of record (or to Menagerie at the cached checkout) makes `test_the_committed_result_is_this_code`
  red until `python -m sysid all --write` is re-run and the new numbers are reviewed: intended.
- The CAN 11 example and its drift demo take minutes (30 kHz replays); the acceptance test takes about 12 minutes in all.
- Card placement, adapter types and the drift threshold choice live in `sysid/cards.py`, never in `type_cards/` (lane A's).

## Alternatives not taken

- **Compute the oracle at site build time.** One less file set, but the site would need MuJoCo and minutes per build, and the
  pages would show numbers no reviewer has seen.
- **Vendor or pin bam_rack_twin.** Reproducible forever, but it would freeze the oracle on a twin the rack has moved past; the rack
  twin is the thing under test.
- **Tolerances tuned to what the methods reach.** Every example would pass by construction; the tolerances say what feed-forward,
  a pick on a moving belt and a 5 mm tool budget need.
