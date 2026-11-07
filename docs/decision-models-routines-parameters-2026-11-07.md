# Decision: the models by generic type, the routines both ways, the parameters view in data-ui (2026-11-07)

- **Status:** accepted on merge (the models lane, `claude/w2c-models`): `site/models_pages.py`, `site/static/models.css`, the rack's model labels in
  `type_cards/deployments/one_dof_test_rack.py` (`dm.ModelLabel`, `inst.label_model`, landed first, alone, as sim2real 7bed016), data-ui CONTRACT §49
  (data-ui `main` @ `998a2d93`) and the kit sim2real vendors (data-ui branch `vendor/sim2real-d5ede93-s49` @ `190eba14`). Decided for Zach by the lane; his to overrule.
- **Asked by:** Zach, `PROJECT - Sim2Real`, 2026-11-06 (his images 20261106185110, 185314, 185842, 190132): "We organize all of the models related to a
  particular part type into a ladder. of icnreasing paramters ... the type here is more generic ... MO.kinematics.X MO.dynamics.X"; "a table of
  calibration routines in the first column and then the parameters that they identify. Another way to see it is with the parameters in the first
  column and all the ROUTINES that can idneity it"; "in the parameter view. lets use DATA-UI ... all of the paramteres ... the Winning model(s) ...
  at least some model run and rpocuded datata ... each model ... its own Recovered error toerlance colum ... under a subheader of the model ... just
  so the error so its easy to compare. And you can color the models by row based on what has the lowest error ... filter what model results we are
  showing". Built on `type_cards/CONTRACT.md` "Domain model v3".

## What was decided

1. **Every rack label is the servo's `M4.dynamics.twin`.** The producer's words ("twin of record", "twin A · deployed", "twin D · LuGre", "refit R1",
   "twin · full", ten in all) each name a bam_rack_twin `TwinParameters` hinge. Rebuilt read-only in the producer's venv (`calibration_round.twins_of`,
   `followup_1029.twins_can1/11`, `presliding_study.deployed`) or read from the dataset study's budget, every one holds the drive's terms (torque
   scale, current loop, command delay) and on some stations the rotor-angle map or the gear gap: the ladder's M4 layer, "Rack twin". The map is a
   record on the deployment (`PhysicalDeployment.models`, one `ModelLabel` each: the model, what fit its values, its friction law, where it departs
   from the model, where it is built), looked up by the exact words; a label nobody mapped maps to nothing, and `tests/test_instances.py` fails on a
   label `run_gates.json` writes that has no entry.
2. **A page per generic type at `/models/<type>/`**, beside the v2 type cards (`/types/<card>/`, unchanged): the type's ladder, one table per family
   (`M<k>.kinematics.*`, `M<k>.dynamics.*`, `M<k>.measurement.*`), with Zach's columns rung · model · parameters · adds · identified here, plus
   **used on**. *Identified here* is every graded value of a parameter the model adds (the parameters table's rows with a result). *Used on* is where
   the model runs: an oracle example whose fit or selection holds it (the deployments pages' own rule, `deployments_pages.fitted`) and a station
   whose runs a producer's model replayed (its label through the map, with the run count). Each row is anchored by its model id, and every
   deployment page's "models used here" links to it (the rack's labels name their ladder model).
3. **The routines, both ways, at `/routines/`:** two tabs, each a data-ui table: a routine per row (where it runs, time and hands-on time, the
   equipment and its cost, what it identifies, its recovery at 1x and 3x noise from sysid's noise ladder, its status), and a parameter of every type
   per row with every routine that can identify it. The rows are `reg.ROUTINES` with `dm.routine_parameters` and `dm.parameter_routines()`, the
   contract's two directions, tested to be each other's inverse.
4. **The parameters view at `/parameters/`, in data-ui:** the contract's parameters table, row for row, data-ui's rail on the left (deployment, type,
   family, models with a result, winning, has a result) and four presets: *All parameters*, *Winning model* (`winning == true`), *With results*
   (`has_results == true`) and *Errors only*. A model's results are one column group, its sub-header the model and the routine that fitted it:
   recovered with its 95 % interval, error, tolerance and ✓ (Zach's 185842 columns). All and Winning show the oracle's own fit; With results and
   Errors only show every (routine, model) and leave out a group no shown row holds a value of, so a rail pick draws exactly the models that graded
   those rows; Errors only marks each row's least |error|, which equals the contract's `best` column. Properties (promoted to the bar) shows or hides a
   model's whole group. Values are the contract's, in one display unit per row (mrad for rad, mm for m), so a row's errors compare.
5. **data-ui grew what it lacked (CONTRACT §49), in data-ui:** a table's `best: {among, by: min | max | absmin}`, column groups shown or hidden whole
   in Property visibility, and `emptyGroups: hide`. Tested there (unit, and `tests/browser/table_best_checks.py` against an oracle over its own JSON,
   mutation-checked).
6. **sim2real vendors d5ede93 + §49, not data-ui main.** §49 is on data-ui `main`; sim2real's kit is a branch of the commit it already vendored with
   §49 backported. Vendoring `main` would also bring 327 commits, and §47 among them changes a default (the one-row chrome: every page's toolbar
   becomes the bar, and a panel's presets fold into a chip when they do not fit) that sim2real's site test reaches: measured with main's kit, the Why
   it fails panel can no longer be found by its tab at 390 px, and the run stops there. The backport's code is byte for byte the old kit's except
   §49's three files.

## Criteria, and how the options scored

The rack labels (weights: must, should):

| criterion | **M4.dynamics.twin, departures recorded (chosen)** | M5.dynamics.electrics (the highest layer any term reaches) | no map; pages keep the labels |
|---|---|---|---|
| names what the twin is, by the ladder's own text (must) | yes: M4 is "Rack twin", implemented by `TwinParameters`, and the servo card's today's model is written around CAN 11's twin of record | partly: the current ceiling is M5's, but the twins hold no motor electrics and no heat | no |
| never claims more than the twin holds (must) | yes: `differs` says LuGre in place of M3's form, the current ceiling, no heat, the gap only on CAN 14's C | no: "+ motor electrics" overstates | yes |
| the coordinator's call ("Twin of record is the M4.dynamics twin") (should) | yes | no | no |
| one model's page can say where it is used (must) | yes | yes | no |

The kit (weights: must, should):

| criterion | **d5ede93 + §49 (chosen)** | data-ui main |
|---|---|---|
| this lane lands with the full site test green and no existing assertion changed (must) | yes | no: the Why it fails panel is not found at 390 px |
| nothing else on the site moves (must) | yes: three files differ | no: §47's chrome on every page, the old app included |
| sim2real converges on the shared library (should) | no change (it was 327 commits behind; still is) | yes |
| §49 lives in the shared library (must) | yes: data-ui main | yes |

## What would change this

- **The labels:** Zach wants a label's model by the highest layer any of its terms reaches (then most are M5, "+ drive ceilings"), or wants the
  ladder's M4 rewritten to hold LuGre and the board's current ceiling (then `differs` shrinks). Either is an edit of the record and its tests.
- **The kit:** the lane that moves sim2real to data-ui main (its chrome locators in the site test, the pages' toolbars, the old app's flow test)
  re-vendors main and drops the backport branch.
- **The parameters view:** Zach wants every model's group in All parameters too, or one preset per model: a `.base` edit in `site/models_pages.py`.

## Undo

`git revert` the lane's merge commit (the pages, the links, the nav, the decision) and re-vendor data-ui `d5ede93` into `vendor/data-ui` (VENDOR.md's
recipe) with `python3 site/build.py --repin`; the old kit's files are also kept at `~/.cache/sim2real/vendor-backups/`. The label map landed alone
(sim2real 7bed016): `git revert -m 1 7bed016`. On data-ui, `git -C /home/bam/data-ui revert -m 1 998a2d93`.
