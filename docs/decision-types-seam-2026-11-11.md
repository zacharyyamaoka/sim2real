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

## Addendum, same day: no cycle, because RobotDescription lives below both

Zach worried this makes a cycle: "Sim2Real accepts a robotdescription… Robotparts imports sim2real… now we have like circular dependencies."
There is no cycle once RobotDescription sits where his Nov 10 order already puts it, in `robot_description`, below both
(robot_msgs ← robot_description ← everything):

```
robot_msgs  ←  robot_description  ←  sim2real (types, models, schedules, fit, eval; accepts a RobotDescription)
                                  ←  robotparts (catalog; maps a part → a sim2real type; fills parameter priors)  → imports sim2real
```

- A RobotDescription is a composition of typed instances with parameter values. It names a type by id and never imports the
  catalog, so building one needs neither sim2real's fitting code nor robotparts.
- sim2real never imports robotparts. Calibration schedules and their comparison take a RobotDescription, wherever its values came from.
- Glue that uses both (`robotparts.describe("rig-1dof")` → `sim2real.calibrate(desc)`) lives in robotparts, which already depends on
  sim2real, or in the caller's script.
- **Models stay in sim2real for now.** They aren't extracted into their own repo, and they don't go into robotparts. A standalone models package
  would be sterile, robotparts is already too big, and next to the fitting and eval pages is where the models mean something.
  Revisit this when a third package (five_bar, pid_tuna) needs the model types without sim2real's fitting. Then the type contract
  (`cards/` + the model definitions) moves down into `robot_description`, not into a new repo.

## Addendum 2, same day: sim2real sits *below* robot_description (supersedes addendum 1's order)

Zach: "robot_description should hold the parameters no? but those parameters come from the sim2real models... I almost feel like
sim2real is below robot_description... What does sim2real depend on? not much honestly... sim2real then doesn't know about
RobotDescription... The robotDescription does .to_twin or from_twin(). Sim2real just knows about the twin."

```
robot_msgs  ←  sim2real  ←  robot_description  ←  robotparts, cad2robot, five_bar, scripts
 (Value…)      (types, models,     (a robot: topology + typed instances
               Twin, fit, sim)      holding parameter Values; .to_twin() / .from_twin())
```

- **sim2real knows nothing about RobotDescription.** Its public noun is `Twin`: typed instances, a model rung chosen for each,
  and parameter `Value`s. A Twin is built directly (`Twin(instances=…)`), not loaded by a name string. sim2real has no registry
  of robots. The oracle examples become `sim2real.examples.<name>()` fixtures.
- **The models are the vocabulary.** Every type (rigid body chain, integrated servo, gearbox, camera…) and its model ladder live
  in sim2real. A kinematic chain is a model too: `rigid_body_chain`'s kinematics rungs.
- **robot_description holds the parameters** of one robot, typed by sim2real's types. `description.to_twin(models=…)` builds a
  Twin, and `description.from_twin(fitted)` returns a new description with the calibrated values (functional update; saving stays
  explicit).
- **What robot_description may import:** only sim2real's light core (types, models, `Twin`; robot_msgs + numpy). MuJoCo stays the
  `sim` extra, so a package that only describes robots never installs a simulator. sim2real must keep that core free of its app,
  site and heavy dependencies.
- **This changes Zach's Nov 10 order** (robot_msgs ← robot_description ← everything): sim2real is now the one package between them.

## Addendum 3, same day: RobotTwin, and the dependency is the point

- **The class is `RobotTwin`**, "a digital twin for an electromechanical device." RobotDescription stays bare-bones: it holds the
  information, and `description.to_robot_twin()` / `description.from_robot_twin(fitted)` cross the seam (snake_case for
  Zach's `to_RobotTwin()`, per PEP 8).
- **Depending on sim2real is intended, not a cost.** Zach: "yes 100% actually all robot descriptions we want sim2real. the whole
  point of robotics is to like actually do something in reality! We are making this first class. Right above the robot_msgs so
  basically its baked into the very nature of this entire software." So addendum 2's "light core only" condition is about install
  size, not principle: MuJoCo stays the `sim` extra so a headless box needn't install a simulator, and sim2real's app and site stay
  out of the package.
