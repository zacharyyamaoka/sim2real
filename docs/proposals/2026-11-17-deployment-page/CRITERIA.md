# Deployment page: five proposals. Criteria, frozen before building (2026-11-17)

Written before any variant existed (babble skill, phase 1). The scores in `round.json` are judged against this file,
unchanged. Weights are the AI's reading of what Zach asked for (Daily Note Nov 17, "# What is required for me to actually
get this working?"); the inferred ones are marked.

## The ask, in his words

- "Sim2Real at the top level we seperate it into DEPLOYMENTS. When I click into each deployment I should bring up the 3D
  viewer of that deployment AND the tree should be the typed component tree. then If I click on any of the things in that
  tree than I can see the data relevant to that level."
- "on the part page I want to see basically the current value of its metrics and gates."
- "Even before I fit any data. let me run the pendulum As it currently it as understand the performance."
- "Its a bit like robot dx ... BUT now the tree is not just actualy hardware but instead like RobotParts"; "A table like this
  I think is cool ... nested table you get nesting and information" (RobotDx's Table view, sim2real's Typed tree).
- "this is presentation though. what is going on in the backend? ... each RobotPart just like it has .models has these
  performance metrics".

## Weighted functional requirements (sum 100)

| id | requirement | weight | why it matters here | pass condition |
|---|---|---|---|---|
| fr1 | **One answer first on every node** | 25 | His ask is "the current value of its metrics and gates"; calm UI (one answer, detail on demand) is a standing rule. The deployment has 6 stations × 5 levels: he must not read a table to learn "CAN 11's twin is the one red". | On the deployment and on any node, the verdict, the first failing question and the metric behind it (value vs gate) are readable without a click or scroll. |
| fr2 | **Typed tree you already know how to drive** | 20 | Reference apps: RobotDx's device tree + Table view and sim2real's Typed tree (zero relearning). Clicking any node shows that level. | Tree on the left, click/keyboard/search, the picked level on the right; a nested table (tree + columns) of the same typed tree. |
| fr3 | **Before fit vs now, legible** | 15 | "run the pendulum as it currently is" = round 0 (as found, 2026-11-15) against round 8 (2026-11-17). Must not lose your place to compare. | The same metric's round 0 and round 8 values readable together at the node you are on, with direction of change, and the ladder caveat (CAN 11's top speed 2.5 → 5.0 rad/s) visible. |
| fr4 | **Stacking and observability told truthfully** | 15 | Settled (MOC Nov 15): five questions in order (Floor → Data → Routines → Twin → Job); a parent passes at its own output and with its children; on this rack motor and gearbox cannot be seen apart from the servo. | Every node shows the five questions in order; "not observable here" never reads as a fail; children shown as not gating where the contract says so (decision 1 default). |
| fr5 | **Backend shape concrete and on the settled layering** (inferred weight) | 15 | His follow-up question. Fit lives on the Model, health on the unit, the verdict on a composition; robot_models knows ModelFamily → Model → Parameter; he leans to robot_models and "a folder called metrics ... I will move it around later". | A short code sketch says where metric and gate definitions live, the API (`IntegratedServo.metrics`-style), how a node's values are computed and read by the page; additive; does not break a ruling. |
| fr6 | **3D grounds the tree** (inferred weight) | 10 | "bring up the 3D viewer of that deployment". House viewer taste: inline, no logo, Fusion-style ViewCube. | A 3D view of the deployment on its page, selection synced both ways with the tree, honest about what is simulated geometry. |

### Anchors (1 / 3 / 5)

- **fr1**: 1 the verdict needs reading a table or several clicks · 3 the verdict is up top but the cause (which question, which metric) needs a click · 5 verdict, first failing question and its metric vs gate in one line at the top of every node.
- **fr2**: 1 a new navigation model to learn; nested table missing · 3 a tree and a table, but they differ from RobotDx/Typed tree conventions or lose the selection between them · 5 RobotDx's tree and Table conventions (dot per node, twisty, search, keyboard), one selection shared by tree, table and 3D.
- **fr3**: 1 only one round visible at a time with no anchor · 3 a round switch that keeps your place; change visible by flipping · 5 both rounds' values together at the node, the direction of change marked, the ladder caveat stated where it matters.
- **fr4**: 1 one blended status; unobservable reads as failure · 3 five questions shown, but the roll-up or observability rule is implicit · 5 five questions in order on every level, the roll-up rule visible, "not observable here" and "shown, not gating" distinct from fail.
- **fr5**: 1 hand-waved ("a metrics layer") · 3 a location and an API, but it collides with a ruling (robot_models = models only; health on the unit) or needs a new package for no reason · 5 one concrete home per concern (definition, gate number, value), additive, the page's read path named, the pendulum's `pendulum_goal.py` lifted not rewritten.
- **fr6**: 1 a static picture with no link to the tree · 3 a 3D view, but selection one-way or geometry unexplained · 5 inline 3D, ViewCube, click a station ↔ tree selection both ways, status on the geometry, "simulated geometry" labelled.

## Hard gates (pass/fail, separate from the score)

- **g1 Real fixture only.** Every number comes from `round0.json` / `latest_real.json` (onedof_2026-11-15 scorecards) or sim2real's `sysid/results/index.json`; anything simulated or assumed is labelled.
- **g2 No dead controls.** Every visible control does something; what is not wired is hidden.
- **g3 Panels resize and remember.** Every panel boundary drags, its width persists (localStorage, try/catch), an inspector folds.
- **g4 Degrees and plain names.** Angles in degrees, never rad/mrad; no bare code (T2, CAN 11) without its plain name beside it.
- **g5 Read-only and isolated.** No hardware, bus, camera or network access; nothing outside this folder, `reports/` and its media is written.

## Comparison contract

- **Outcome all variants serve:** open sim2real → Deployments → the One Dof Test Rack → its 3D + typed component tree → any node's current metrics and gates (the five questions) → the nested table → round 0 (as found) vs round 8 (now).
- **Invariants:** same fixture, same 1440 × 900 viewport, sim2real's tokens (sim2real.css: blue = real, orange = sim, green/red = pass/fail only), dark theme first (his screenshots), every variant runnable from `file://` and over http.
- **Shared fixture:** `fixture/fixture.js`, built by `fixture/build_fixture.py` from the two scorecards (read-only).
- **Stop line:** front-end slices over the real fixture. The values a production backend would compute are precomputed by the fixture builder from the scorecards; the backend shape is a sketch per variant (`v*/BACKEND.md`), not implemented in any library.
- **Load-bearing axes:** mental model (workbench, table, scene, question matrix, measurement ladder) · primary object (node, whole tree, physical station, question, speed rung) · before/after treatment · where metric definitions live.
