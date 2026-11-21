# Deployed: lifetime calibration and monitoring (designed, not built)

On the bench, calibration is a schedule you run once: the twin plans its routines, you run them, it fits and scores itself. Once a robot
is at work, calibration is mostly watching the fit. Its own work, every pick, is data. The twin replays recent runs; when the fit drifts
it refits a challenger on recent sessions, scores it against the twin in service on the same held-out runs, and keeps it only if it wins.
Nothing is installed on its own.

This page is the design. The parts that exist today are named as such; everything else is **designed, not built**. The landing page's
"Bench today, deployed next" section shows the sim studies' numbers, each linked to its file.

## What a deployed routine is

A routine whose `setting` is `deployed` (it runs on a robot at work) or `both` (it runs anywhere). `Budget(settings=("deployed",))`
plans only those. A deployed routine either reads data the robot makes anyway (picks, holds, camera frames of the belt) or asks for a
short excursion the cell can afford between jobs (a gap check). It never needs a fixture, a tracker or a person at the robot.

Deployed routines in the catalog today, each with its page under Routines:

- `servo.live_reid_t10`: live re-identification while the joint works.
- `servo.gap_check_forecast`: a periodic gap check with a wear forecast.
- `camera.pose_recal_belt_tags`: the camera's pose refit from the belt's tags.
- `cell.tags_bundle_adjustment`: the cell's tags bundle-adjusted.

## The loop

monitor → trigger → refit a challenger → shadow-compare → keep if it wins → new record

| Stage | What it does | There today | Designed |
|---|---|---|---|
| monitor | Fidelity: held-out error ÷ the device's own floor, against `TWINNED_LIMIT` (`cards/schema.py`, 1.5). Drift: live fidelity ÷ calibrated fidelity, against `DRIFT_THRESHOLD` (`cards/schema.py`, 1.25, settable per card and per call). A CUSUM on the per-run residuals catches a slow walk the ratio misses. Parameter drift with its forecast, performance against the gates, and coverage (which parts of the workspace recent work exercised). | `servo.gap_check_forecast` and `servo.live_reid_t10` as routines; the two constants | `fitted.monitor()` |
| trigger | A monitor crossing, a validity window running out, or an event the cell reports (a knock, a part swap). | the drift studies' alarm rules | `fitted.monitor().due` |
| refit a challenger | Refit from the priors over a window of recent sessions, never from the last fit (a refit of a refit walks). | `calibrate(data=…)` refits on runs the twin holds | `sim2real.calibration.production()` turns pick sessions into `CalibrationData`, the newest sessions held out |
| shadow-compare | Score the challenger and the twin in service on the same held-out runs. | `evaluate()` | `fitted.recalibrate()` |
| keep if it wins | Keep the challenger only if it wins on those runs and passes `preflight()`. Nothing is installed on the robot by itself. | `sim2real.preflight()` | the comparison rule in `recalibrate()` |
| new record | Write the record and its ledger, with a W&B copy, and a validity window on it. | `Ledger`, the W&B copy | `valid_until` on the record |

## Where it runs

On the robot's own host, beside the work: the monitor reads the work's own logs; a refit runs off the real-time cores (the same rule
as every heavy job while an arm is powered). A challenger is a file until someone keeps it.

## Decided (each reversible)

- **Refit from priors over a session window**, not from the previous fit: a chain of refits drifts with its own errors.
- **A challenger is never installed automatically.** `recalibrate()` returns it with its comparison; keeping it is a call you make.
- **The description is written only when you say so**: `fitted.save_description()`.
- **Real arms run PD and feed-forward only.** A refit changes feed-forward and, through a tune step, PD gains; never an integrator.

## Build order

1. `sim2real.calibration.production()`: pick sessions in, `CalibrationData` out, the newest sessions held out.
2. `fitted.monitor()`: fidelity, parameter drift with its forecast, performance, coverage, and what is due.
3. `fitted.recalibrate()`: a challenger refit on recent sessions, kept only if it wins on the same held-out runs.
4. `valid_until`: a validity window on the record.
5. `fitted.save_description()`: the description is written only when you say so.

## The sketch

```python
# designed, not built: production, monitor, recalibrate and save_description do not exist yet
import sim2real
from sim2real.calibration import production

data = production(sessions, hold_out="newest")      # pick sessions in, CalibrationData out
health = fitted.monitor()                            # fidelity, drift and its forecast, performance, coverage, what is due
if health.due:
    challenger = fitted.recalibrate(data=data)       # refit from the priors on recent sessions
    if challenger.wins:                              # scored against the twin in service on the same held-out runs
        sim2real.preflight(challenger)               # exists today
        challenger.save_description(path)            # only when you say so
```

## Prior art

Cited from knowledge, not re-fetched.

- **Champion and challenger.** A model in service (the champion) is replaced only by a challenger that beats it on the same holdout:
  standard model-governance practice in credit scoring (Siddiqi, *Credit Risk Scorecards*, Wiley, 2006).
- **Data drift and concept drift.** The inputs moving versus the mapping moving; a twin's parameters drifting is the second kind
  (Gama et al., [A survey on concept drift adaptation](https://doi.org/10.1145/2523813), ACM Computing Surveys, 2014).
- **CUSUM.** A cumulative sum of residuals flags a small persistent shift sooner than a threshold on each sample
  ([Page, Continuous inspection schemes](https://doi.org/10.1093/biomet/41.1-2.100), Biometrika, 1954).
