# Decision: the bench feedforward routine `arm.feedforward_bench` (2026-11-18)

**Decided:** sim2real gets a routine that fits an arm's feedforward, gravity and friction, from paired out-and-back transfers made with the
trajectory library: `sim2real.calibration.FeedforwardBench` (runs, commanded feedforward, fit), `sim2real.fit.feedforward.fit` (the
estimator), `sim2real.metrics.actuator.feedback_share` (the performance metric) and the catalog row `arm.feedforward_bench`. Lane L4
(gap FF-1) of the sim2real calibrate plan of 2026-11-18; ruler `tests/test_feedforward_bench.py` with the toy arm `tests/feedforward_toy.py`.
Its rounds (collect, fit, come back for what is missing) are part 2, lane L8 (`tests/test_feedforward_rounds.py`).

Zach, Daily Note 2026-11-18 ("Feedforward CAlibration"):

> I basically just want to do .calibrate() and then for the feedforward model to be fit as accurately as possible.

and on the motions: "that calibration routine basically can use the trajectory lib to just generate the things that its needs".

## Why a routine at all

The arm already runs a lot of feedforward (measured-mass gravity on J2/C1 and the wrist, J1's sine law, Coulomb friction while moving, an
inertial term from the CAD, the gated hold pushes), and none of it came from a routine: one-off scripts in bam_ws
`src/core/mdp/setup/bam_pid_tunning/docs/` (`mass_refit`, `j2_ff_refit`) fitted it over runs harvested from picks and experiments, each
checked on held-out runs and installed by a pin move. The fits are good; the process is not repeatable and has no stop rule. This routine
is that estimator, made repeatable, graded against a hidden truth first.

## What was decided, each with its undo

| call | why | undo |
|---|---|---|
| a new catalog row `arm.feedforward_bench` (bench, identify, implemented, no equipment) that **identifies** `link_inertials` on `arm_subassembly` M2 and `arm_6dof` M3 | the masses are what the gravity regressor's theta stands for; nothing on the bench is bought (the board's torque and the encoders) | delete the row and the two name-backs |
| it **refines** the drives' `frictionloss_nm` and `damping_nm_s_rad`, never identifies them | an integrated-servo-only pick must never get an arm routine in its cover and keeps `servo.dynamics_regression` (`tests/test_calibration_backend.py`); on an arm it runs after that routine and refits the friction as one curve with gravity | move them to `identifies` |
| alternatives: `arm.dynamics_excitation` and `servo.dynamics_regression`, which name it back | they find the same masses (the arm's excitation) and the same friction (the servo's regression) another way; a comparison is never one-sided (`type_cards/tests/test_routines.py`) | drop the three names |
| friction is ONE curve, Coulomb plus a NET viscous term (`damping_nm_s_rad`, negative where friction weakens with speed) | sign(v)(Fc − w\|v\|) is Fc sign(v) − w v, the same column as b v: a separate weakening term could never be told apart from it, and the servo card already names these two | a weakening key beside the damping |
| each run is ONE `robot_trajectories.trapezoidal_velocity(space, target, start=, velocity_fraction=, dwell_s=, back_to_start=True)` call | Zach's "use the trajectory lib"; the library's paired out-and-back move retraces its path, which is what cancels friction; the recipe the trajectory carries says which kind made it. `velocity_plateaus` and `friction_id` are single-joint; `quasi_static_pose_holds` is excluded because holds never enter the fit | another kind in `FeedforwardBench._motion` |
| holds never enter the fit; a run that goes one way, or comes back along another path, is refused by name ("both directions") | 15c's lesson: a hold rests anywhere inside static friction, so it bounds gravity and never equals it; without the way back over the same poses nothing cancels the friction | — |
| the held-out residual leaves out one **cell** (an edge at one speed) at a time, and is systematic (block means of >= 25 moving rows) | leaving out one run of a pair leaks; block means let torque noise average out while model error stays | — |
| the prior is the snapshot of the values `runs()` was handed; the ridge (`prior_sigma`) is off unless given | a later round must not count the prior twice | — |
| `robot_trajectories` is the optional `trajectories` extra, imported only when runs are made | the library has no remote yet (a first push makes it public: Zach's call); sim2real still imports without it, and a cloud cut carries it | — |
| the grader lives in the ruler, never in the code under test | a routine that grades itself can pass itself | — |

## Left for later

- Rounds and the stop rule (empty or over-tolerance cells first; converged, no improvement, or the cap): FF-2, lane L8.
- FF-3: hook it to the CAN 11 pendulum (the seam and the real path exist), then build the `bam_fb_v2` rig on the one-click seam, twin first.
- What still blocks a real-arm run: the `bam_fb_v2` rig on the seam, the friction twin's 20ad gate (it fails today), and Kt, which nothing
  measures and which reads exactly like a mass scale.

Prior art: Atkeson, An and Hollerbach (1986) and Gautier and Khalil (1990) for gravity and inertia linear in a regressor's base parameters;
Armstrong-Hélouvry, Dupont and Canudas de Wit (1994) for Coulomb plus viscous friction and why it is odd in speed. The out-and-back pairing
is the classic friction-cancelling quasi-static sweep, here over a workspace graph instead of one joint.
