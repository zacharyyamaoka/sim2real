# V5 backend · a tiny `robot_metrics` package of model-free functions

**Thesis:** Zach's "it's almost like robot_metrics". Metrics are model-free functions of logs (robot_msgs
trajectories), shared across types (tracking RMS is the same function for a servo and an arm, at a different output),
so they get their own small package between robot_msgs and robot_models. A type only names which ones judge it.

| concern | lives in | example |
|---|---|---|
| metric function | `robot_metrics` (depends on robot_msgs only) | `stop_error_at_tool(traj, fk, stops)` |
| which metrics judge a type | one tuple on the family | `RigidBodyChain.judged_by = (...)` |
| gate number | sim2real `cards/` targets (as today for T1-T11) | |
| current value | per run → per rung → per node, a ledger per round (`results.json`), W&B a copy | |
| fit / health | unchanged | |

```python
# robot_metrics/tracking.py      (new package; robot_msgs only, numpy optional)
@metric(question="job", unit="mm", output="tool")
def stop_error_at_tool(traj: JointTrajectory, fk, stops) -> float: ...

@metric(question="twin", unit="× floor")
def twin_over_floor(real: list[JointTrajectory], sim: list[JointTrajectory], floor: float) -> float: ...

# robot_models/arms/rigid_body_chain/__init__.py
class RigidBodyChain(ModelFamily, id="rigid_body_chain"):
    judged_by = ("floor", "coverage", "oracle_recovery", "twin_over_floor", "stop_error_at_tool", "tracking_rms")

# sim2real: a round is a ledger; the ladder grid is its per-rung rows
ledger = sim2real.score_round(deployment, ".../round8")       # pendulum_score, generalised
ledger.rows(node="can11", rung=0.4)["twin_over_floor"]        # 2.14
```

**Read path:** plots and the ladder grid read the per-rung rows directly (the measurement, not a summary of it).

**Fits:** shared functions once (the stock-diagnostics catalog already reduced 89 diagnostics to 30 functions);
model-free by construction. **Strains:** a new package to version and publish (robot-models-lib needed a PyPI name
too), and the five questions still need a home (here: sim2real).
