# sim2real dashboards: five proposals, and the pick (2026-10-27)

- **Asked by:** Zach, 2026-10-27: "make 5 orthogonal dashboard proposals using data-ui for doing Sim to real ... the 1 dof
  case, a full 6 dof robot case, and even one with like cameras and full sensor suite".
- **Code:** `dashboards/build.py` (stdlib) writes `dashboards/<rack|arm|suite>/` (datasets + one `.base` per proposal);
  `dashboards/source/rack_replays.py` (real rack runs vs their station twins, via bam_rack_twin) and
  `dashboards/source/arm_suite_sim.py` (the MuJoCo UR5e stand-in) are the producers; `serve.py` serves it.
- **Review report:** `reports/media/dashboards-2026-10-27/report.html` (gitignored media; screenshots, hero video).

## Criteria (from his words), weight

| # | Criterion | Weight |
|---|---|---|
| C1 | At a glance: calibrated or not ("at a glance you can quickly see if its calibrated or not") | 20 |
| C2 | Sliced by sensor/actuator ("the right way to slice this is by sensor/actuator") | 15 |
| C3 | Derived quantities one level up ("dervied or higher order things ... like eef position") | 10 |
| C4 | A standard dashboard per type ("a standard 'dashboard' for each type") | 15 |
| C5 | Same page from 1-DOF to 6-DOF to cameras + full suite | 10 |
| C6 | Visual: 3D + camera streams, wipe sim vs real ("the 3D view ... camera streams ... wipe any of them") | 15 |
| C7 | A tree of runs, then the dashboard ("a tree to see the different files or runs and then like a dashboard") | 10 |
| C8 | 100% data-ui, reusable as a block | 5 |

## Scores (1-5, weighted to 100)

| Proposal (primary axis) | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | Total |
|---|---|---|---|---|---|---|---|---|---|
| 1 Visual home (space) | 5 | 4 | 3 | 2 | 4 | 5 | 1 | 4 | **73** |
| 2 Type catalog (device type) | 3 | 5 | 4 | 5 | 5 | 3 | 1 | 5 | **76** |
| 3 Gate matrix (acceptance) | 4 | 4 | 3 | 3 | 4 | 1 | 2 | 5 | 63 |
| 4 Run inspector (time) | 2 | 4 | 3 | 2 | 3 | 4 | 5 | 4 | 64 |
| 5 Error budget (consequence) | 3 | 3 | 5 | 2 | 4 | 1 | 1 | 5 | 55 |

## Decision

**Visual home is the landing page; each device's badge opens that device type's standard block (proposal 2).** The two
top scorers are not rivals: one answers "is it calibrated?" in a glance, the other is the per-type page a badge leads to.
Gates (3), runs (4) and the budget (5) become tabs behind them. The review switcher opens Visual home on the rack.

## What the pages surfaced

- **Two rulers disagree on the rack.** By the floor ratio (acceptance.py T2) none of the 8 motors is twinned. Carried to a
  tool through a virtual arm (the best-twinned motor per class, acceptance.py's lever arms) the twin's error is 3.83 mm,
  inside the 5 mm grasp number. Which one "calibrated" means is Zach's call.
- **CAN 4 reads 1.37x but fails T2** (its worst dataset class is 3.14x, over the 2x class limit), so the badges show the
  binding clause ("share of the gate used"), not the bare ratio.
- **Derived devices catch encoder-blind errors** (stand-in only): J4's encoder agrees with the twin to 0.38 mrad while the
  joint is truly 3.6 mrad off; only the tool and the wrist camera see it.

## Gaps handed to data-ui (not patched here)

The list is in the report's "data-ui gaps" section: clock span ignores filters, no wipe over a 3D card, no camera-frame
overlay of a 3D twin, per-property rule lines, preset selections in the `.base`, one-way links, tone-mapped text badges,
tracker column labels, a no-headline grouped KPI, `src` set after upgrade ignored.
