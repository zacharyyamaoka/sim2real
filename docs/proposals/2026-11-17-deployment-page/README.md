# Deployment page · five proposals (babble round, 2026-11-17)

Zach's ask (Daily Note Nov 17, "# What is required for me to actually get this working?"): Sim2Real opens on
**Deployments**; a deployment brings up its **3D** and its **typed component tree**; clicking any node shows **the current
value of its metrics and gates**; a **nested table** like RobotDx's; "run the pendulum as it currently is" before any fit;
and "what is going on in the backend?" (where the metrics live). Five runnable answers, each with its own backend.

- **Gallery (compare, splice, the AI's view):** `/home/bam/sim2real/reports/deployment-page-proposals-2026-11-17.html`
  (stills and clips in the gitignored `reports/media/deployment-page-proposals-2026-11-17/`).
- **Criteria, frozen before building:** [CRITERIA.md](CRITERIA.md). Scores and evidence: [gallery-spec.json](gallery-spec.json).
- **Fixture (shared, real):** `fixture/fixture.js`, built read-only by `fixture/build_fixture.py` from the pendulum
  campaign's `round0.json` (as found, 2026-11-15) and `latest_real.json` (round 8, 2026-11-17). It re-states
  `pendulum_goal.cell_gates` and is held to the scorecards' own 82 and 151 gates passed.

| | name | the page is | before vs now | metrics defined in | score |
|---|---|---|---|---|---|
| [V1](v1/BACKEND.md) | Workbench | RobotDx's frame: tree + entity page with tabs + Table view | round switch, "was" beside every value | robot_models, nested: `IntegratedServo.metrics` | 86 |
| [V2](v2/BACKEND.md) | Sheet | the nested table, both rounds as columns, 3D + inspector docked | Round 0 · Now · Δ columns | `robot_models/metrics/<type>.py` records + values ledger | 83 |
| [V3](v3/BACKEND.md) | Scene | the 3D; servo parts pull apart; table as a bottom sheet | time bar under the scene | robotparts type: `.models` `.metrics` `.dx` | 81 |
| [V4](v4/BACKEND.md) | Questions | the question matrix (typed tree × Floor → Data → Routines → Twin → Job) | Now · As found · What changed | sim2real: `verdicts.py` once + `cards/<type>.py` | **88** |
| [V5](v5/BACKEND.md) | Ladder | KPIs, a stations × speed-rungs grid, speed-ladder plots | round 0 drawn underneath | a `robot_metrics` package of functions | 77 |

**AI pick: V4 Questions (88), V1 Workbench (86) a fragile co-leader.** Hinge: move 5 points from backend fit to RobotDx
familiarity and V1 wins. **Suggested splice:** V1's Workbench frame (tree, entity page, Table view, health apart) with
V4's "one thing stops the goal" banner and question columns + What-changed mode in its Table view, V2's
Round 0 · Now · Δ columns, V3's exploded servo for part-level picks, V5's speed-ladder plots as the station's tab.

**Backend recommendation:** keep the verdict where the settled thinking puts it, in sim2real: the five questions once in
`verdicts.py`, each type's own metrics and gate numbers as a card in `cards/<type>.py` (lifting `pendulum_goal.py` beside
the existing `cards/servo_gates.py`), the page reading one values file per round. If `.metrics` beside `.models` matters
to you, the model-free metric functions can start in a `robot_models/metrics/` folder (your "folder called metrics") that
the cards call, the only part that has to sit at or below robot_models for that spelling to exist.

## Open them

Every variant opens from `file://` (no server, no build):

    /home/bam/.local/bin/open /home/bam/sim2real/docs/proposals/2026-11-17-deployment-page/index.html

or served (the same pages over http):

    python3 -m http.server 8790 --bind 127.0.0.1 --directory /home/bam/sim2real

then `http://127.0.0.1:8790/docs/proposals/2026-11-17-deployment-page/`.

## Rebuild and re-check

    python3 -I /home/bam/sim2real/docs/proposals/2026-11-17-deployment-page/fixture/build_fixture.py
    env -u VIRTUAL_ENV taskset -c 2-5,16,17 uv run --isolated --no-project --with playwright python /home/bam/sim2real/docs/proposals/2026-11-17-deployment-page/tools/verify.py
    env -u VIRTUAL_ENV taskset -c 2-5,16,17 uv run --isolated --no-project --with playwright python /home/bam/sim2real/docs/proposals/2026-11-17-deployment-page/tools/capture.py
    python3 -I /home/bam/sim2real/docs/proposals/2026-11-17-deployment-page/tools/build_gallery.py

`tools/verify.py` measures, per variant: a row click selects the node; a click on a 3D station **mesh** selects it; the
ViewCube moves the camera; the CAD-render toggle; the main panel boundary drags +70 px, survives a reload, resets on
double-click; the inspector folds; the before/after control changes the round; 0 console errors. All five pass
(`tools/verify.json`).

## What is simulated, and what is not verified

- **3D geometry is schematic** (each station's real tip length, motor family and load; plates laid out by hand), labelled
  "schematic geometry · simulated"; "CAD render" shows the real MuJoCo render of the rack's cad2robot payload, a still.
  Not the house viser viewer: a live viser per proposal was too heavy for a five-way round.
- **Values are precomputed** by the fixture builder from the scorecards (what a backend would compute); no backend is
  implemented; each `BACKEND.md` is a sketch. Not wired into sim2real's site or `src/`.
- **Health is not in the fixture:** RobotDx's live unit health (faults, temperature, last heard) is named, not shown;
  only the round's per-run faults and missing plays are.
- **T3 (current fidelity)** is the 11-07 value carried in both scorecards, from before the 24 V re-commissioning.
- **Routines** comes from sim2real's sysid oracle index (only CAN 11 has an example), the same in both rounds.
