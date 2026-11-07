# Decision: metrics, diagnostics and coverage over any selection, computed in the browser by the contract's rule; reports frozen from a selection (2026-11-07)

- **Status:** accepted on merge (the metrics lane, `claude/w2d-metrics-reports`): `tools/run_metrics.py`; `type_cards` `domain.py` (RunSource
  `run_metrics`, `UnitLimit`, `PhysicalDeployment.limits`, `WHY_NOT`), `selection.py` (`metric_values`, `metrics_from_values`, the unit's limits,
  the coverage grid), `report.py` (freeze from a selection, `inputs.rows`), `deployments/one_dof_test_rack.py` (`limits`),
  `frozen_reports/ident_sessions_1106.py`, `otherday_sessions_1107.py`; `site/metrics_pages.py`, `site/reports_pages.py`, `static/metrics.js`,
  `static/metrics.css`. Decided for Zach by the lane; his to overrule.
- **Asked by:** Zach, `PROJECT - Sim2Real`, 2026-11-06: "Each entity type has Metrics ... the most improtant ones we kinda pin to the top ...
  DIAGONISTICS ... metrics + gate that reports warning or error. Generally I think we can calculate these metrics on a per run basis... but also
  accross all the runs ... its just the row model you can basically like include or not what runs will be included"; "As a model can be good
  BUT only in a certain area ... visualize quickly like the currently selected runs or run what is its coverage ... we certaintly need the
  ability to do the computation"; "Reports ... a set number of rows ... 'freeze it' and see the ful lbreak down. So even as you add more data".
  Built on the frozen contract: `type_cards/CONTRACT.md`, "Domain model v3" (selection.py, report.py).

## What was decided

1. **The per-run model-independent metrics are RobotDx's own catalog entries, run on each run's npz** (`tools/run_metrics.py`, to
   `app/data/<dep>/run_metrics.json`): `servo.stop_error` (the p90 at every dwell; the dwell scan and the rack loader bam_rack_twin's T4 uses)
   and `driver.saturation` (the share of rows the board reports on its torque cap, code 102). A metric's `robotdx` names the entry; its default
   config is the definition. A value says which side measured it (the stop error's title says "at the output"; the producer's is the encoder
   side, which T4 calls partial), on every page that shows it. `tools/build_app.py` writes the table again last (it clears each deployment's
   folder first). The other
   model-independent metrics of the rack's parts say what their runs lack (`domain.WHY_NOT`): no commanded current, no output angle apart from
   the rotor's, no load cell, no dyno, no tag angle per run.
2. **A unit's own limits sit on its deployment's record** (`UnitLimit` in `PhysicalDeployment.limits`): the stop allocation (warn and T4's
   target) and the loop rate's warn, copied from bam_rack_twin with their source and held to it by a test that reads the producer's constants.
   deployments.json carries them on the node they bind, as an array (the house table has no object type). Unknown stays unknown where none is set.
3. **The browser computes, data-ui's reducers do the arithmetic and data-ui draws.** `static/metrics.js` takes the runs in play (the runs
   table's ticked rows, else every row its filters leave), aggregates each metric with data-ui's exported `summarize` (Median, Min, Max; Unique
   for the distinct cells), sets each level by `domain.level`'s rule with the unit's limits (data-ui computes no verdict, its CONTRACT §35), and
   feeds data-ui tables and data-ui's chart (the robotics template's phase-space view: q x qd, shaded by the qdd bands visited). No re-vendor:
   the vendored kit already had every reducer and the selection API (`selectable`, `data-views-select`, `selection`, `model.rows`).
4. **One projection per input**: `metric_values/<dep>.json` (the run x metric table) beside `coverage_cells/<dep>.json` (the run x cell table, now
   with each device's grid), so the page reads one table whatever produced a value; `selection.metrics_from_values` is the rule in Python,
   tested equal to `compute` for every subset of a fixture, and the site test holds the page's numbers to `compute` for three selections made in
   headless Chrome (a rail pick, rows ticked across stations, a preset) and to the build's precomputed preset.
5. **A page per physical deployment, `/metrics/<dep>/`**, beside the deployments pages (a node's page stays about the node over all its runs;
   this page is about a selection), linked from every node page with runs, its stations picked in the rail. Presets are the build's
   `selection.presets` as rail filters; the "all" preset is the page's answer without script. A fidelity metric shows every model that replayed
   the runs, the headline the one with the most runs, each producer label beside the ladder model `inst.label_model` maps it to (every rack twin
   is the servo's `M4.dynamics.twin`), linked to its row on `/models/<type>/`.
6. **Reports are made from a selection by the CLI** (`python3 -m type_cards.report freeze --id ... --runs | --select | --preset`): it writes the
   Python definition, then freezes; it never overwrites a report. A snapshot keeps the rows it froze (`inputs.rows`). `/reports/<id>/` reads the
   snapshot and never recomputes; `?report=<id>` on the metrics page ticks its runs, so the frozen numbers and today's sit one click apart.
   Since the v3 audit (2026-11-07, finding 7) a snapshot also keeps what its page names beside the numbers (`annotations`: the parts' titles,
   the ladder model each label named); the three frozen before it are labelled, not re-frozen: their pages say those are today's and claim
   to stay as they are only for what they froze (re-freezing would recompute their numbers on today's data, a new decision).

## Criteria, and how the options scored

| criterion (weight) | **host computes with data-ui's reducers, data-ui draws (chosen)** | a data-ui dashboard: linked datasets, roll-up panels | build-time presets only |
|---|---|---|---|
| Zach's row model live: tick or filter, the numbers follow (high) | yes | yes for the medians | no |
| the browser's numbers are `compute`'s, provably (high) | yes: one rule, read back from the page | the medians yes; levels and the coverage % need a host anyway, read out of a panel's internals | yes, but only the presets |
| data-ui's own computations, no second implementation (high) | yes: its `summarize` | yes | n/a |
| no re-vendor of the shared kit (medium: every lane builds from it) | yes | yes | yes |
| calm: one answer per station first, detail on demand (medium) | yes | panels of tables | yes |

| the per-run producer (weight as above) | **RobotDx's catalog entries on the npz (chosen)** | RobotDx's rows added to run_gates.json by build_app | computed in Python from samples.json |
|---|---|---|---|
| one definition of a stop (T4's, RobotDx's) (high) | yes | yes | no: a second dwell scan |
| additive: no app-data rebuild, nothing peers read changes (high) | yes: a new file | no: rebuilds app/data and changes a table the run page reads | yes |
| fast enough to rerun on its own (medium) | 6 s for 2,239 runs | 20 s + the replays | minutes (4 GB of JSON) |

## What was found with it

- The run pages' dots are real now where a run gives a value: the driver's on every run (its loop rate and its torque-cap share), the station's
  wherever the run has a stop (1,355 of 2,239; a sine has none and stays unknown, saying why).
- Most runs' stop error is over the joint's allocation (CAN 11: 141 of 223; CAN 12: 241 of 364); the acceptance's T4 cells are the tuned
  configurations. Over the identification sessions (ident-sessions-1106) all three stations stop within it (CAN 11 0.80, CAN 12 0.71, CAN 21
  0.51 mrad), and so on the other day (2.67, 0.56, 0.71 mrad).
- The twin of record over the same-day sessions: CAN 11 1.42x floor (ok), CAN 12 3.09x, CAN 21 2.53x (warning); on the other day 1.35x, 2.78x,
  2.39x: not worse by its median. Coverage of the other-day sessions is 13-18 % of each joint's reachable cells against 39-42 % same-day, so
  the other-day numbers hold over less of where the joint can go.

## Asked of this lane, and not done

- **The deployments pages' splitter:** checked with the pane scrolled on the index, the rack, a station and a part: no data-ui splitter outside
  the left column shows over the trail (their dashboards have no rail), so the run page's fix was not applied to them. The metrics and reports
  pages carry it from the start.
- **`entity_tree` and `status_tree` as one component:** not contained. Both pages' markup, styles and site checks read them by their own
  classes, and the models lane's pages call `entity_tree` too; merging them is its own change across three lanes' pages. Left as is.

## What would change this

- Zach wants the selection page on each deployment's own page: the runs section there becomes this page's runs table and results (one module).
- A producer writes more per-run values (a commanded current, a tag angle per filmed run, a load cell): a row in `run_metrics.json` or another
  RunSource, and `WHY_NOT` loses its line; the page needs no change.
- data-ui gains verdicts or a per-group distinct count over a selection: the host's level and % move into a view.

## Undo

`git revert` the lane's merge commit: the site loses `/metrics/` and `/reports/` and the nav's two entries; type_cards loses the run_metrics
source, the unit limits (the dots go back to unknown) and the CLI's create form; the two new reports go with it. `app/data/<dep>/run_metrics.json`
stays until the next `tools/build_app.py` (harmless: nothing reads it without this lane).
