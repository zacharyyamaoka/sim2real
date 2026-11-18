# V4 backend · sim2real owns the verdict: the five questions once, a card per type

**Thesis:** the verdict lives on a composition (settled, MOC Nov 15), so sim2real owns it. The five questions are
generic code, written once; each type contributes only its card: the output it is judged at, its own metrics and its
gate numbers. robot_models stays "ModelFamily → Model → Parameter only". The pendulum contract is lifted, not
rewritten: `bam_rack_twin/pendulum_goal.py` becomes the 1-DOF arm's card.

| concern | lives in | example |
|---|---|---|
| the five questions | `sim2real/verdicts.py`, once for every type | `five_questions(node, runs)` |
| a type's own metrics + gate numbers | `sim2real/cards/<type>.py` (servo_gates.py is already one) | `cards/pendulum_arm.py` |
| the parent rule | the card: `children=…, gating_children=False` (MOC decision 1 default) | |
| current value | `CalibrationResult.verdicts()` → the site's `data/domain/metric_values/<dep>.json` (exists today) | |
| fit / health | unchanged: `Model.score` / RobotDx | |

```python
# sim2real/cards/pendulum_arm.py   (pendulum_goal.py's Thresholds + cell_gates, moved byte for byte)
CARD = Card(type="rigid_body_chain", joints=1, output="link tip",
            own=[TipStop(at_most(1.0, "mm"), settle=at_most(0.3, "s")),       # Zach's 1 mm
                 SpeedLadder(rungs=(0.2, 0.4, 0.6, 0.8, 0.9, 1.0), goal=0.9),
                 SimPredicts(rel=0.2, abs_deg=0.05)],
            children=("integrated_servo", "rigid_link"), gating_children=False)

# sim2real/verdicts.py
def five_questions(node, runs) -> dict[str, Verdict]:
    """Floor → Data → Routines → Twin → Job at the node's OWN output; a parent passes only with its children."""

result = twin.evaluate()                       # or a scored round
result.verdicts()["can11"]["twin"]             # Verdict(fail, Value(2.14, "× floor"), first=True)
```

**Read path:** the matrix is `verdicts()` as it is: rows = nodes, columns = questions, a cell = one Verdict.

**Fits:** every settled ruling (fit on the Model, health on the unit, verdict on the composition; robot_models only
models); the T-gates already live in `cards/servo_gates.py`; additive. **Strains:** a type's metrics are not found
"on the type" in robot_models, which is where Zach leaned; two places to look (family for models, card for metrics).
