# V2 backend · a flat `robot_models/metrics/` folder and a values ledger

**Thesis:** Zach's "for now I can just have a folder called metrics where I put this information... I will move it
around later". Records, not classes: one module per type id, no family imports it, so moving it later is a `git mv`.
The values are a ledger the table reads row for row.

| concern | lives in | example |
|---|---|---|
| metric definition | `robot_models/metrics/<type_id>.py`, plain `MetricSpec` records | `MetricSpec("T3", unit="× scatter", question="twin")` |
| the five generic questions | `robot_models/metrics/__init__.py` `FIVE_QUESTIONS` | |
| gate number | on the record (`target="<= 2.0"`); a deployment overrides in sim2real `registry.json` | |
| current value | `app/data/<dep>/values.jsonl`, one row per node × metric × round | |
| fit / health | unchanged (Model / RobotDx) | |

```python
# robot_models/metrics/integrated_servo.py
from robot_models.metrics import MetricSpec, FIVE_QUESTIONS
METRICS = FIVE_QUESTIONS.at(output="output angle") + (
    MetricSpec("T3", "current fidelity", unit="× scatter", question="twin", target="<= 2.0", fn="current_over_scatter"),
    MetricSpec("T7", "envelope: top speed", unit="%", question="twin", target="|x| <= 5", fn="top_speed_error"),
)
# robot_models/metrics/__init__.py
def for_type(type_id: str) -> tuple[MetricSpec, ...]: ...      # the registry; nothing else imports these modules

# sim2real writes the ledger; the page's table reads it as is
for node in deployment.tree:
    for spec in metrics.for_type(node.type):
        ledger.append(round=8, node=node.id, metric=spec.id, value=spec.compute(node.runs), status=spec.judge(value))
# {"round": 8, "node": "can11", "type": "pendulum_arm_1dof", "metric": "twin_over_floor", "value": 2.139, "status": "fail"}
```

**Read path:** the sheet is a pivot of `values.jsonl` (rounds become columns); the inspector shows the node's raw rows.

**Fits:** his "folder called metrics" today, and "move it around later" is cheap; the ledger is the same shape as
robot_controllers' `results.json` and W&B rows. **Strains:** a folder of loose records can drift from the families it
describes (no import ties them), and `robot_models/metrics/` still puts non-models in robot_models.
