# V3 backend · the RobotPart type carries `.models`, `.metrics` and `.dx`

**Thesis:** Zach's own sentence, "each RobotPart, just like it has .models, has these performance metrics". The type
that joins a datasheet to its models already lives in robotparts (PEP 0004 amendment 2), so the metrics join it there,
and the health diagnostics come from the same metrics plus a threshold ("diagnostics build on top of metrics, just
adding a threshold").

| concern | lives in | example |
|---|---|---|
| metric definition | robotparts, on the part TYPE (never per SKU) | `robotparts.types.IntegratedServo.metrics` |
| models | robot_models, referenced by the type | `IntegratedServo.models = robot_models.IntegratedServo` |
| gate number | the type card's default, a deployment's override | |
| health | `dx = Diagnostics.from_metrics(metrics, warn_at=1.25)`, read live on the unit (RobotDx) | `unit("moteus-r4.11 · CAN 11").dx` |
| current value | sim2real composes: each tree node points at its part type, `type.metrics.evaluate(node.runs)` | |

```python
# robotparts/types/integrated_servo.py
class IntegratedServo(PartType, id="integrated_servo"):
    datasheet = IntegratedServoDatasheet
    models = robot_models.IntegratedServo                    # fit lives on the Model
    metrics = Metrics(FIVE, output="output angle",           # NEW, beside .models
                      own=[T3_current_fidelity, T7_envelope, limiter_share])
    dx = Diagnostics.from_metrics(metrics, warn_at=1.25)     # health = a metric + a threshold, read on the UNIT

part = robotparts.part("jmc-60asm200-ad60g10")               # a SKU: its datasheet values, never its own metrics
unit = robotparts.unit("moteus-r4.11 · CAN 11")              # a physical unit: unit.dx is RobotDx's live health
```

**Read path:** sim2real's deployment tree names each node's part type; the page shows `type.metrics` values per node and
`unit.dx` beside them (health apart from state).

**Fits:** his words exactly, and one object answers "what is this part, how do I model it, how is it judged". **Strains:**
robotparts is the catalog (McMaster-style site); judging a composition (a pendulum arm, a cell) is not a part, so the
composite types' metrics need a home outside robotparts anyway, and he said robot_parts "shouldn't be specific to
each part".
