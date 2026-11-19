# The one-click seam: what a rig supplies

`sim2real.RobotTwin(...).calibrate(on="sim", truth="sealed")` (e.g. `sim2real.examples.ur_wrist_test_rig()`) runs a rig's whole calibration sequence against a sealed hidden truth and
returns a new, fitted twin; `.eval()` scores it on held-out runs over the sim's own repeat floor; `.result().display()` shows it.
Zach, 2026-11-11: *"my goal is to just export then have the one click .calibrate() and then just see the results. So get that fully
working in sim first, and once you can prove that the entire routine recovers perfectly (and you stress test it with different levels of
noise) then we run that routine in reality."* His rule: a routine recovers the hidden values to within a tolerance.

- Code: `src/sim2real/rig.py` (`SEAM = "sim2real.rig/1"`), wired into `src/sim2real/twin.py`.
- Frozen by: `tests/test_one_click_seam.py` (a toy rig, numpy only: change the contract and these go red).
- First rig: the UR wrist, `sysid/examples/ur_wrist_test_rig/` (`tests/test_ur_wrist_one_click.py`). The five-bar is next.

## What a rig ships

One folder, `sysid/examples/<name>/`, in the existing description format:

| file | what |
|---|---|
| `description.json` | `sysid.description/1`: the model file, the typed components (each a sim2real type through its word: `moteus_servo`, `motor`, `gearbox`, `driver`, `encoder`, `arm_subassembly`, `tool`, `deployment`), and every parameter `<instance>.<name>` with its unit and where its nominal value comes from. `sim2real.examples` reads it unchanged (`twin.describe`, the internal adapter). |
| `world.json` | `sysid.world/1`: the hidden truth, `{"truth": {key: value}}` with a source for every value. Only the runner reads it, outside the seal. A key it leaves out plays at its nominal. |
| `rig.py` | `rig() -> RigBackend`. Its presence is the opt-in: a `RobotTwin` named for the folder uses `RigRunner` when it exists, else the pendulum tracer's `SimRunner`. |
| `routines.py` | (the tracer, `SimRunner`; 2026-11-17) `schedule()`: the planner's half of a RigBackend, `name`, `parameters()` and `routines()`, each routine a step of the example's `pipeline.py`. `plan(twin)` shows these routines and `calibrate()` plays exactly them over the pipeline's own measurement of the schedule; each fit's third argument is `twin.PipelineHandle` (the pipeline, its sysid description, the twin's `workers`, the rung it runs). First: `pendulum_can11` (`servo.backlash_reversals_camera`, then `servo.dynamics_regression`). |

## The RigBackend (all a rig implements)

```python
class RigBackend(Protocol):
    name: str
    def parameters(self) -> Sequence[Parameter]: ...       # every parameter the description carries
    def noise(self) -> NoiseModel: ...                     # the 1x noise, measured on the real rig, a source per term
    def routines(self) -> Sequence[Routine]: ...           # the calibration sequence, in order
    def held_out(self, values) -> Sequence[Run]: ...       # the held-out runs (never fitted), built in the frame `values` say
    def measure(self, runs, values, noise, stream, *, workers) -> Mapping[run_id, recording]   # the rig's MuJoCo twin at `values`, noise drawn
    def predict(self, measured, values, *, workers) -> Mapping[run_id, recording]              # the twin at `values` replaying each recording's own commands and clock, noise-free
    def score(self, predicted, measured) -> Score: ...     # per-joint RMS (rad), per run; the tool at stops (m) when the rig has a tool point
    # optional: derived(values) -> {key: value}  (a value computed from others, e.g. a joint's gravity from the chain's masses)
    # optional: result(description, calibration, report, state) -> sim2real.result.CalibrationResult  (the page)

class Routine(Protocol):
    id: str                                                # a cards.calibration ROUTINES id (registered, else refused)
    identifies: tuple[str, ...]                            # the parameter keys its fit returns as found (held to the truth)
    adjusts: tuple[str, ...] = ()                          # optional: keys it SETS for the twin without claiming them (a chain's
                                                           # masses on their visible subspace); their rows stay "not identified"
    commands_read: tuple[str, ...]                         # optional: the keys its runs' commands are made from (default: the
                                                           # keys it requires); the schedule shows it made after their finders
    def runs(self, values) -> Sequence[Run]: ...           # its excitation, given what the earlier routines found (a frame, a pose);
                                                           # the same runs for the same values (the schedule is static)
    def fit(self, measured, values, twin: TwinHandle) -> Mapping[key, Estimate]: ...   # runs SEALED; may only twin.predict(...)
```

Records: `Parameter(key, unit, tolerance=("rel"|"abs", SI value), tolerance_source, routine, why_not, display, title)`,
`Estimate(value, ci95, method)`, `Run(id, split, spec=None, seconds=None, command=None)` (the runner reads `id`, `split` and `command`:
a robot_msgs `JointTrajectory` or `JointCommandSequence`, or none; `robot_seconds()` is its robot time; `to_dict()` / `from_dict()`),
`Score(joints, runs, tool_stop_m)`.

## The rules the runner enforces (and the rig therefore must not)

1. **The truth is sealed.** The runner reads `world.json` once, outside the seal, and hands it to `measure` only. Every `fit` runs inside
   `sysid.world.sealed()`: a fit that reaches for the truth raises `SealedWorld`. A fit plays the twin through `TwinHandle.predict` only.
   A rig's `measure` must keep world-only channels (the true output angle) out of the routine streams (`stream` starts `"routine:"`).
2. **Every parameter is a row.** Identified ones name the routine that identifies them and a tolerance with its source (`"proposed: ..."`
   when no use or routine states one); the rest say `why_not` (no excitation, no equipment, below the noise, held). The runner refuses a
   silent parameter, an unregistered routine, and a routine that returns a key it did not declare. Nothing unidentified is reported as found:
   a key a routine only `adjusts` reaches the twin, and its row carries `set_for_twin` with no verdict.
3. **The ruler is world.json's.** Rows hold each recovered value to `ruler(truth, nominal, noise)`: the committed truth, moved toward nominal
   by `noise.truth_offset` (1: as committed). `move_truth={key: value}` moves the world only, so the row turns red: the mutation test.
   A derived value is held to what the ruled values give, and cannot be moved on its own.
4. **One play per run.** A run two routines both read is measured once and shared (the dynamics fit's chirps are the delay scan's); one
   run id is one command, so a second routine that plays the id with another command is refused.
5. **The schedule is what plays** (2026-11-18). `plan(twin)` binds each routine's runs at the priors and shows which are known now and
   which are made after an earlier step (docs/CALIBRATE.md, "The schedule"); `calibrate()` refuses, before it plays, a known-now routine
   whose runs differ from the ones shown.
6. **Held out is held out.** `eval` refuses a run any routine measured or not split `held_out`. Its floor is the sim's own repeat
   spread: every held-out run measured twice under the same noise (streams `held_out` and `repeat`), scored against each other.
7. **Gates:** `twinned` (the fitted twin's held-out error / floor at most `TWINNED_LIMIT`, 1.5x, worst joint), `recovery` (every identified
   value within tolerance), and `tool_at_stops` (p95 at most 1 mm, Zach 2026-11-11) when the rig scores a tool.

## The noise model (the stress lane's knobs)

```python
noise = twin.noise()                       # the rig's measured 1x, NoiseModel(...), .sources says where each number comes from
twin.calibrate(noise=3.0)                  # every term x3; 0 = noise-free
twin.calibrate(noise=noise.at(0.5))        # the same
twin.calibrate(noise=noise.with_terms(torque_noise_nm=0.05))   # one term's 1x value replaced (a single-term sweep), the rest kept
twin.calibrate(noise=noise.with_terms(truth_offset=2.0))       # the hidden truth twice as far from nominal (the ruler follows)
twin.calibrate(noise=noise.with_terms(seed=7))                 # another draw
```

Terms (`NoiseModel.TERMS`, each scaled by `level`): `encoder_quantum_rad` (the reported position's step), `encoder_noise_rad`,
`velocity_noise_rad_s`, `torque_noise_nm` (the reported torque), `torque_disturbance_nm` (white noise on the torque a driving board
applies, held per host period: process noise), `period_overrun_s` (the host loop's mean overrun past its tick, drawn exponential per tick),
`latency_jitter_s` (each command's extra latency, uniform). A rig anchors its 1x to the real rig: the UR wrist's to its measured repeat
floors (`WristRig.floor_check`, the real lane's 5 same-input repeats). Not scaled by level: `truth_offset`, `seed`. Streams are
seeded by `(seed, crc32(stream), crc32(run id))`, so the same call draws the same numbers.

## What the five-bar lane supplies

`sysid/examples/<fivebar>/{description.json, world.json, rig.py}`: its parameters (each joint a servo, the chain's closure), its 1x noise
from its real runs, its sequence (homing, backlash, mass ID, dynamics, delay: each a registered routine, registered additively in
`src/sim2real/cards/calibration.py` if new), `measure` / `predict` on its own plant, and `score`. Nothing in `sim2real.rig` changes; if it
must, change `tests/test_one_click_seam.py` first and say why.

The parts already built for it (the mount lane, bam_ws `claude/fivebar-test-rig-model` @ b6f8bfce3, not yet on main), and where each goes:

| Seam slot | The five-bar's part | Note |
|---|---|---|
| `RigBackend.measure` / `predict` (the plant) | `rig = bench_rig(load_bundle()); CadPlant(rig.bundle, rest_poses(rig)["bowl"], rig=rig)` (`bam_fb_test_rig.rig`, `.homing`) | the real RACK_MOUNT; the CAD is ~1.12x too light, which mass ID must recover |
| world.json's hidden backlash | `bam_fb_test_rig.backlash.hidden_specs()` (J1 3.5', J2 2.5', C1 4.0' around the AD064's 3') | the same gear_backlash `BacklashModel` double joint the wrist's world uses |
| a backlash routine | `bam_fb_test_rig.backlash.measure(SimDrive(...), mesh_stiffness_nm_per_rad=...)` after `find_balance(drive)`; `dead_band(position, torque)` reads the trace | recovers 2.501' / 4.000' / 3.501'; measured where the load crosses zero, not at the gravity-loaded stops |
| a breakaway routine | `sysid/examples/ur_wrist_test_rig/rig.py` `breakaway(drive, direction, ...)`: any `ProbeDrive` | written against the same five calls, so it runs on `SimDrive` unchanged |

What the wrist learned that the five-bar should know (measured 2026-11-11 on the wrist's world at 1x): `measure`'s torque probe does not
transfer to a light output. It lets the rotor cross the gap as a free mass, and the far flank's impact breaks a ~0.2 N.m output loose; the
probe's torque, above the output's ~0.05 N.m sliding level, then drags it 2 deg ("not observable here: the link left" on all three joints).
The wrist therefore drives its reversal under the position loop (the motor crosses at the target's 0.5 deg/s) and reads the trace with the
same `dead_band`; its breakaway ramps the command's torque cap with the target 5 deg ahead, for the same reason. On the five-bar's 0.74 N.m
outputs the probe works as built.
