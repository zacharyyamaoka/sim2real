# Decision: the run page is one page per run, its entity tree in the left column and every level's dashboard in it (2026-11-07)

- **Status:** accepted on merge (sim2real main: `site/run_pages.py`, `site/ui_shared.py` `status_tree` and `record_page`, `site/views.py`
  `levels/<type>.base`, `static/ui-shared.js`, `static/run-page.css`). Decided for Zach by the run-page lane (w2b); his to overrule.
- **Asked by:** Zach, PROJECT - Sim2Real, 2026-11-06: "if I click on any run I should be able to view the data for that run. On the left
  should be like an entity tree. so you can see basically the results at different levels. and then on the page what shows is the
  standard dashboard for that level with the data that was capture from the run" (his RobotDx device tree as the picture); "in these
  dashboards we are seeing like the metrics and diagonistics that are indepdent of the models". Contract: `type_cards/CONTRACT.md`, "The run
  page: entity tree and the standard dashboard per level".

## Criteria, and how the options scored

Weights: high = must, medium = should.

| criterion (weight) | **one page, levels in place, `?entity=` (chosen)** | a page per level (`/runs/<run>/<node>/`) | levels as more tabs |
|---|---|---|---|
| the tree beside every level, as RobotDx keeps it (high) | yes | yes, one page load per click | no: tabs sit under the header |
| a level is a link (high: the brief's deep links) | yes: `?entity=<node id>`, Back returns | yes | partly: `#tab` names a tab, not a node |
| the run's existing checks and links keep working: `#t=` lands on the Playback, every run page's tests (high) | yes: the station's level is the old page | no: links into the run would need a level | no: the tab list is a tested contract |
| site size and build time (medium) | +44 KB a page, 21 s builds (was 7.8 s) | about ×8 pages (9 levels a run) | as chosen |
| works without JavaScript (medium) | yes: every level shows, stacked; every node a link | yes | yes |

| layout (weight as above) | **the workbench's two panes, the record on the right (chosen)** | the flow page with the tree placed by CSS grid | the tree above the tabs |
|---|---|---|---|
| tree left of everything, scrolling on its own (high) | yes (McMaster's panes, Zach 2026-10-25) | needs `display: contents` and a row span | no |
| boundary dragged and remembered (high) | yes: data-ui's resize on the column, its own key | yes | no boundary |
| the workbench unedited (high: the site test checks it) | yes: `shell.page(aside=)` and `record_body`, the same call the record writer makes | yes | yes |
| one left column for both page lanes (medium) | yes: the deployments lane uses the same panes | no | no |

The cost of the chosen layout: run pages are written by the site (`catalog.site_pages` -> `run_pages.pages_of`) and `RUN` is not in
`CATALOG.kinds`, because the workbench's record writer has no left column. The record itself (header, tabs, panels) is still the workbench's.

## Decision

1. **The tree is the contract's**: the run's deployment's nodes at the run's device (its station and its parts), every ancestor, and the
   cameras whose `sees` holds the station. Other stations are left out and counted under the tree ("Not in this run: 7 other stations").
2. **A node's dot is its level in this run**: a typed node's worst model-independent diagnostic by `domain.LEVEL_RANK` (unknown when none
   has a value), a structural node the worst under it, a camera unknown (which run a camera filmed is its session's, not `runs.json`'s).
   Today almost every dot is a hollow ring: the contract's diagnostics have values only for twin fidelity (per model) and the board's rate
   (its limit is per unit). The dots light as producers write per-run metrics; the one-line summaries carry the numbers that exist.
3. **A level's dashboard**, top to bottom: its pinned metrics, then its other model-independent metrics, its diagnostics with their levels,
   its coverage for this run (all `sel.compute([run])`), then what was captured at that level: the station's is the Playback tab (the
   `joint-3d` component, and `camera-clip` beside `joint-render` where the session filmed it), a camera's its clip (`camera-clip`, scoped to
   it), a part's a data-ui dashboard of its channels in this run's samples (`views/levels/<type>.base`, each a component on its own clock),
   the deployment's a roll-up of every entity of the run, an adapter's its boards. Only columns the run recorded are drawn.
4. **Models are their own section**, labelled, never mixed into the numbers above: each model's fidelity (its error ÷ the station's T1
   floor), that value's level, T2's gate, and RobotDx's own check of the run.
5. **The run's tags and Zach's caveat** head every level: excitation, closed loop, offline scope, the config snapshot, and "Offline
   evaluation is valid for models, not for online tracking under changed feedback", worded per offline scope.

## Found and fixed on the way (type_cards, test first, with the coordinator's go)

- `selection.load_tables` read a station's floor as any gate starting "T1", so T10's value was 7 of 8 stations' floor (CAN 12: 1.992 for
  its 0.7459 mrad). Now the gate's id word. CAN 11's T10 is null, so the frozen CAN 11 report recomputes unchanged.
- `coverage.binned` rebuilt the same 2016-cell reachable set on every call: 19 s of a 35 s build once each run computes its selection.
  `coverage.reachable_cells` keeps it per joint description (bounded, keyed on the whole description); every number is unchanged.

## What would change this

- Zach wants a level's own URL path (to share a part's page without the run's), or levels for runs of virtual deployments: a page per
  level is the next step, the sections become pages, and `?entity=` links redirect.
- A third page lane needs a left column: `ui_shared.record_page` is the one call; making `entity_tree` and `status_tree` one component is a
  listed follow-up.

## Undo

`git revert` the merge commit: the run pages go back to the workbench's record writer and the old header (`pages.run_header`); the
`type_cards` fixes are their own commits, kept or reverted on their own.
