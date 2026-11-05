# Decision: what a model rung's key means (2026-11-05)

**Status:** accepted on merge (sim2real main, type_cards v2). Decided for Zach by the type-cards lane; his to overrule.

## Context

Zach's Nov 5 workflow (PROJECT - Sim2Real, "Proposed Work Flow Nov 5 2026") asks for "multiple rungs of models … M1, M2, etc.,
each one generally with increasing number of parameters". The dispatcher's brief gave a servo example numbered from scratch: M1
ideal inertia + viscous, M2 + Coulomb + Stribeck, M3 + cogging, delay and backlash.

BAM already numbers actuator models. robotparts publishes an actuator ladder (`models/actuator/*/model.json`, PEP 0001's naming
spec, "the rung is the highest layer captured"): M0 ideal, M1 the datasheet, M2 Coulomb + viscous, M3 Stribeck / LuGre /
load-dependent, M4 ripple (+ backlash as a variant), M5 DC-motor electrics. bam_rack_twin calls load-dependent Coulomb "BAM's M3
term", and robotparts' published fits are named `M2.twin` … `M4.twin.backlash`. sim2real is the drill-down of those fits.

## Decision

- **M0–M5 are physics.** On the cards whose layers robotparts publishes (servo, motor, gearbox, conveyor) the number is
  robotparts' layer, so "M3" means the same model on robotparts.dev, in bam_rack_twin and here. robotparts' M1 is the datasheet's
  values of M2's terms, which here is every parameter's Nominal column, so those ladders have no M1. Every other card defines
  its own M0–M5 from M0, the nominal model a robot description gives.
- **`<key>.wear`** is a physics rung's wear variant (usage as an input).
- **M6 is always the grey-box residual and M7 always the black-box net**, on every card (the coordinator's fix, same day).
- Consumers never parse keys: they order by `card.rungs`.

## Consequences

- The servo reads M0 · M2 · M3 · M4 (today's twin) · M5 · M5.wear · M6 · M7: a gap at M1, explained on the page.
- Pinned by `type_cards/tests/test_ladders.py`: `test_actuator_keys_are_robotparts_rungs` (a cited robotparts model's own
  `rung` equals the key) and `test_m6_and_m7_mean_the_same_on_every_card`.
- `type_cards/CONTRACT.md` ("Rung keys") is the reference lanes code against.

## Alternatives not taken

- **The brief's 1-2-3 numbering per type.** Contiguous and simple, but "M3" would mean cogging + delay + backlash here and
  Stribeck friction on robotparts.dev, at the exact seam where sim2real drills into robotparts' fits.
- **Contiguous per-type numbers with a robotparts column.** Honest, but every reader would have to translate between two
  numberings forever.
- **Separate letters for learned rungs (R1, N1).** Clearer kinds, but they are rungs of one ladder that the selection rule
  climbs in order; M6/M7 keep one sequence.

## Undo

Rekey in `type_cards/ladders.py` and change the two tests above; no consumer parses keys (lanes B and C order by `card.rungs`).
