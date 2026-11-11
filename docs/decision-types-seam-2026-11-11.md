# Decision: sim2real owns the generic types; robotparts depends on sim2real through them (2026-11-11)

**Status:** accepted. Zach decided this in chat on 2026-11-11, after reading three seam proposals (vault: `Sim2Real and Robot Parts — Seams and
1-Click API (2026-11-11)`). His words: "it just about like 'types' and Sim2real actually can just define and group things under its own types.
we don't actually need to think about particular manufacturers... That is actually much better and smarter. Ok so I think we can continue
working just in sim2real then.. Robot parts will depend on sim2real. The seam will be via those types."

## Context

- Both repos claimed the same two things: the servo model rungs (robotparts `models.json`; sim2real `models/`, `/models/<type>/`) and per-type
  gates (robotparts levels and checks; sim2real `cards/`).
- Robot Parts had grown too much: accounts, lists, prices, scrapers, a Notion-grade table library. Zach moved to sim2real to focus on the twin
  work, and every model still belongs to a *kind* of part.
- The proposal had recommended the opposite direction ("each part ships its own twin"). Zach overruled it, and the reason holds: a model ladder,
  a calibration routine and a gate are properties of a **generic type** (servo, gearbox, camera, serial chain), not of a manufacturer's SKU.

## Decision

- **sim2real defines the types:** for each generic type, its parameters, model ladder (`M<k>.kinematics|dynamics|measurement.*`), calibration
  routines, metrics and gates. These are the eleven types `/models/` already lists (`src/sim2real/cards`, `models`). No manufacturer appears in
  sim2real.
- **robotparts depends on sim2real**, never the reverse. A robotparts record names its sim2real type, and its datasheet values fill that
  type's parameters as priors (the evidence ladder decides which value wins). Fitted values from a rig flow back to the part as measurements.
- **The seam is the type contract:** the type ids and each type's parameter names and units, in `sim2real.cards` (schema `sim2real.type_cards/2`,
  additive-only per `cards/CONTRACT.md`). Changing that contract is a barrier. It lands alone, before any robotparts change that reads it.
- **Work continues in sim2real.** The one-click API (`RobotDescription.load(...)`, then `.simulate()`, `.calibrate()` and `.eval_twin()`) is
  written over types. A description is a composition of typed instances with parameter values. Where those values came from (a robotparts part,
  a CAD export or a guess) is the caller's concern.

## Consequences

- Nothing moves out of sim2real. `models/` and `cards/` stay, which reverses the proposal's seam B.
- robotparts' own model definitions (`models.json` M0…M5) become a projection of sim2real's ladder for the type, to be migrated in robotparts
  when it next needs them. robotparts stays stdlib-only at runtime by reading a generated JSON of the type contract, not by importing numpy code.
- What robotparts keeps: the catalog (identity, sourced specs, offers, files), and the mapping from a part to its type.
