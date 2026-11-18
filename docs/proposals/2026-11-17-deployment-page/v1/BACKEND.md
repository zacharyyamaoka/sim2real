# V1 backend · metrics nested on the ModelFamily

**Thesis:** a type's metrics sit beside its models, on the same class: `IntegratedServo.metrics` next to
`IntegratedServo.m3`. Zach's lean ("they should live at the level of the robot models... that's the level at which I
describe all of the basic types") taken literally.

| concern | lives in | example |
|---|---|---|
| metric definition (what, unit, output, which question) | robot_models, nested on the family | `IntegratedServo.metrics.t3` |
| the five generic questions | robot_models `metrics.FIVE` (a base every family's `metrics` inherits) | `floor, data, routines, twin, job` |
| gate number (default target) | on the Metric; a deployment overrides in sim2real `cards/deployments/<dep>.py` | `target=at_most(1.5)` |
| current value of a node | sim2real `evaluate()` → `app/data/<dep>/values/<round>.json` | `values["can11"]["twin"]` |
| fit (does this model explain this log) | unchanged: `Model.score(log)`, `ModelFamily.select_best(held_out)` | |
| health of the physical unit | unchanged: RobotDx reads the unit | |

```python
# robot_models/actuators/servo/integrated_servo_family.py   (beside the models)
class IntegratedServo(ModelFamily, id="integrated_servo"):
    class m3: ...                                        # models, unchanged
    class metrics(Metrics, output="output angle"):       # NEW: model-free, judged at the output
        floor, data, routines, twin, job = FIVE          # generic, inherited
        t3 = Metric("× scatter", question="twin", target=at_most(2.0))     # own to this type
        t7 = Metric("%", question="twin", target=within(5.0))

# robot_models/arms/rigid_body_chain/   (Zach: "a robot arm is just a serial rigid chain"; 1 joint = the pendulum)
class RigidBodyChain(ModelFamily, id="rigid_body_chain"):
    class metrics(Metrics, output="link tip"):
        floor, data, routines, twin, job = FIVE
        tip_stop = Metric("mm", question="job", target=at_most(1.0))       # bam_rack_twin pendulum_goal.Thresholds
        speed_ladder = Metric("of top speed", question="job", target=at_least(0.9))

# sim2real: walk the deployment's typed tree, each node asks its type
values = sim2real.evaluate(deployment, round_dir=".../onedof_2026-11-15/round8")
values.write("app/data/one-dof-test-rack/values/r8.json")        # the page reads only this
```

**Read path:** the page loads `values/<round>.json` (node → metric → value, status) for the round switch.

**Fits:** Zach's lean, one place to look per type, `.models` and `.metrics` side by side. **Strains:** the 11-17
ruling "robot_models knows only ModelFamily → Model → Parameter" (a new kind of thing on the family), and robot_models
gains a metric runtime it must keep dependency-free.
