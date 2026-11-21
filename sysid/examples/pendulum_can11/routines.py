"""CAN 11's calibration routines, the schedule plan(twin) shows and calibrate() plays (gap F, Zach 2026-11-17: "robottwin.calibrate()
internall mabye that does .generate_schedule() -> CalibrationSchedule ... a static description of the routines that will be run").

    import sim2real
    from sim2real.calibration import plan
    twin = sim2real.examples.pendulum_can11()        # or RobotTwin.from_robot_description(station_description(11))
    plan(twin).summary()                             # 1. servo.backlash_reversals_camera  2. servo.dynamics_regression  3. pid.pidtuna
    fitted = twin.calibrate(on="sim")                # plays exactly those steps, in that order; fitted.plan_ is that plan

The steps, each a registered catalog routine (src/sim2real/cards/calibration.py), each the pipeline's own code (pipeline.py), never
re-derived here:

1. servo.backlash_reversals_camera   the gear gap from (motor encoder - link camera) over every train row (pipeline.gear_gap)
2. servo.dynamics_regression         one inverse-dynamics regression over every train run, every rung of the servo card's ladder (M0, M2,
                                     M3, M4), M4 on the rows where the gear is in contact at step 1's gap (pipeline.identify)
3. pid.pidtuna                       PID tuna on the fitted twin, no robot time (sim2real.calibration.PidTune, gap C): the board's kp and kd
                                     as settings (fitted.settings_), never model values; dropped by name where pidtuna cannot be imported

WHY the planning half of the one-click seam and not a rig.py (2026-11-17): sim2real.rig.load_rig() turns a rig.py into a RigRunner, and the
pendulum's proven path is twin.SimRunner (the real backend, sim2real.real, plays the same pipeline on the rack; its eval grades the rung
ladder against the held-out link camera; models= picks a rung). So the pendulum ships what the planner reads from a RigBackend (name,
parameters(), routines()), and SimRunner plays these routines over the pipeline's own measurement of the schedule.

WHY both steps read the same runs: on CAN 11 the gear crosses its gap at every load reversal the schedule's train runs already make, so the
camera sees the gap in the very runs the regression fits (the catalog's "the same schedule's runs"); the world plays the schedule once.

The third argument of each fit is the runner's handle (twin.PipelineHandle): `module` (the pipeline the runner plays), `description` (its
sysid description), `workers` (the twin's cap on every pool) and `rung` (the rung the twin runs). Never the truth.
"""

from __future__ import annotations

import json
import warnings

from sim2real import paths
from sim2real import rig as seam
from sim2real.calibration.pid_tune import PidTune
from sysid import RESULTS_DIR

EXAMPLE = "pendulum_can11"
SERVO = "can11"
GAP = f"{SERVO}.backlash_rad"
DYNAMICS = tuple(f"{SERVO}.{name}" for name in ("gravity_nm", "gravity_bottom_rad", "armature_kg_m2", "frictionloss_nm", "damping_nm_s_rad",
                                                "friction_stribeck_drop_nm", "friction_stribeck_speed_rad_s"))


def _train_seconds() -> float | None:
    """The train split's robot time as the committed result states it (sysid/results/pendulum_can11.json, schedule.train.seconds: 771.8 s
    on 2026-11-18), read and never re-derived; None (unknown) with a warning when the file or the field is missing."""
    path = RESULTS_DIR / f"{EXAMPLE}.json"
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["schedule"]["train"]["seconds"])
    except (OSError, KeyError, TypeError, ValueError) as caught:
        warnings.warn(f"{EXAMPLE}: the train run's length is unknown ({path}: {caught!r}); the schedule shows it as unknown", stacklevel=2)
        return None


# one session: every FB run of the schedule's train split (pipeline.plan), which the rack plays (the world, in sim) and both steps read.
# WHY no command and never labelled recorded data: the rack plays these runs (sysid's schedule, typed collection is a later lane), so the
# run carries its real length and the spec says what it is
TRAIN = seam.Run("train", "train", "every FB run of the train split of CAN 11's schedule (pipeline.plan)", seconds=_train_seconds())


class Ladder(dict):
    """A step's estimates ({key: sim2real.rig.Estimate}, the twin's rung) and the whole ladder fit they came from (`fit`: pipeline.Fit, every
    rung), which the runner keeps: eval scores every rung against the floor and the selection rule picks one."""

    def __init__(self, estimates, fit) -> None:
        super().__init__(estimates)
        self.fit = fit


class GapFromReversals:
    """servo.backlash_reversals_camera: the gear gap from the load reversals in the train runs, seen by the link camera."""
    id = "servo.backlash_reversals_camera"
    identifies = (GAP,)

    def runs(self, values):
        return (TRAIN,)

    def fit(self, measured, values, twin):
        if not measured:
            return {}  # no train rows: nothing to find the gap from, the prior serves
        gap = twin.module.gear_gap(measured)
        return {GAP: seam.Estimate(gap.rad, gap.ci95, twin.module.GAP_METHOD)}


class DynamicsRegression:
    """servo.dynamics_regression: the excitation regression over every train run (pipeline.identify), at the gap step 1 found."""
    id = "servo.dynamics_regression"
    identifies = DYNAMICS
    # WHY its own needs, not the catalog's (requires zero_offset_rad, static_friction_nm: the UR wrist's homed frame and breakaway): CAN 11
    # is not homed by a routine (its schedule is planned in the station's own frame) and the regression fits its own static level; it reads
    # the gap (M4 regresses where the gear is in contact), and with no gap found the description's prior serves: a soft edge
    requires = ()
    uses = ("backlash_rad",)

    def runs(self, values):
        return (TRAIN,)

    def fit(self, measured, values, twin):
        # WHY workers= (bdfed7d, tests/test_workers_cap.py): without it identify()'s friction polish opens its default 8-worker pool beside
        # the powered arm; the twin's cap reaches every pool
        fit = twin.module.identify(twin.description, measured, workers=twin.workers, gap=values.get(GAP))
        rung = twin.rung
        # only what the twin's rung estimated (the values with a bootstrap interval; the rest are the rung's structural constants)
        found = {f"{SERVO}.{name}": seam.Estimate(fit.values[rung][name], fit.ci95[rung][name], fit.methods[rung])
                 for name in fit.values[rung] if f"{SERVO}.{name}" in DYNAMICS and name in fit.ci95.get(rung, {})}
        return Ladder(found, fit)


# CAN 11's board as the rack runs it, for PID tuna (step 3). WHY these numbers: the envelope a tune may move the pendulum in and the torque
# limit are bam_ws bam_pid_tunning's CAN 11 rung (src/core/mdp/setup/bam_pid_tunning/src/bam_pid_tunning/plants/rack_truths.py: travel 0.3
# rad about its -0.35 rad origin, 2 rad/s, 2.85 N.m; 0.7135 N.m/A x 4 A); the gains are read from the deployment record when it runs
RECORD = ("records", "one-dof-test-rack", "deployment.json")
CAN_ID = 11
ENVELOPE = {"travel_rad": 0.3, "max_speed_rad_s": 2.0, "max_torque_nm": 2.85, "origin_rad": -0.35}
TORQUE_LIMIT_NM = 2.854
COMMAND_RATE_HZ = 100.0


def board_servo():
    """CAN 11 as its board runs today, a pidtuna Servo: the deployment record's gains (kp 200, kd 4 N.m/rev, ki 16000, ilimit 0.5 on
    2026-10-29) in the rack's envelope. Built when step 3 runs, so planning never imports pidtuna."""
    from pidtuna import config, types  # noqa: PLC0415  (PidTune.fit has put pidtuna on the path)

    component = config.load_component(paths.RACK_TWIN.joinpath(*RECORD), CAN_ID)
    return config.servo_from_component(component, envelope=types.Envelope(**ENVELOPE), torque_limit_nm=TORQUE_LIMIT_NM,
                                       command_rate_hz=COMMAND_RATE_HZ)


DEPLOYMENT = "one-dof-test-rack"
# WHY 2 ms: the twin of record's command delay (bam_rack_twin.schedule.record_twin(11), "twin of record (followup C)", a replay fit in
# bam_ws docs/followup_1029.py; the one pipeline.twin plays and preflight reads), held equal to it by tests/test_pid_tune_stated_loop.py so
# the loop builds where no pipeline is at hand. NOT description.json known.board_knobs' "command_delay_s 0.001": that text is stale
COMMAND_DELAY_S = 0.002


def board_loop(values, twin=None):
    """CAN 11's board loop as the twin states it, a pidtuna analytic.LoopModel for PID tuna's analytic ceiling (or None when a piece is
    unstated): the board's recorded current loop, PLL band and one encoder count (sim2real/data/board_configs.json, a copy of its moteus
    dump), its driver's datasheet control rate (robotparts, the low end), and the command delay the fit found, else the twin of record's
    (COMMAND_DELAY_S). `twin`, the step's handle, is not read: the loop builds with no pipeline in hand. WHY (pidtuna CONTRACT amendment
    3): with no relative gain range the climb is held by the analytic bounds on the stated loop, which pidtuna applies only where
    Servo.loop is stated; sim2real.preflight reads the same pieces."""
    from pidtuna import analytic  # noqa: PLC0415  (PidTune.fit has put pidtuna on the path)

    from sim2real.calibration import board_loop as bl  # noqa: PLC0415

    entry = bl.board(DEPLOYMENT, CAN_ID)
    found = values.get(f"{SERVO}.command_delay_s")
    delay = ((float(found), f"the fitted {SERVO}.command_delay_s") if found is not None else
             (COMMAND_DELAY_S, "the twin of record's command_delay_s (bam_rack_twin.schedule.record_twin(11), a replay fit)"))
    pieces = {"loop_hz": bl.control_rate(None if entry is None else entry.get("driver_part")), "delay_s": delay,
              "torque_bandwidth_hz": bl.current_loop(entry), "velocity_filter_hz": bl.velocity_filter(entry),
              "encoder_quantum_rad": bl.encoder_count(entry)}
    return bl.loop_model(analytic, pieces)


class Routines:
    """What the planner reads from a RigBackend (sim2real.rig): `name`, `parameters()` (each key with the routine that identifies it and its
    tolerance from sysid/acceptance.json) and `routines()`."""
    name = EXAMPLE

    def parameters(self) -> tuple[seam.Parameter, ...]:
        from sysid import describe, result  # noqa: PLC0415

        nominal = describe.load(EXAMPLE).nominal
        owner = {GAP: GapFromReversals.id, **{key: DynamicsRegression.id for key in DYNAMICS}}
        return tuple(seam.Parameter(key, nominal[key].unit, result.tolerance(EXAMPLE, key), "sysid/acceptance.json", routine,
                                    title=key.split(".", 1)[1]) for key, routine in owner.items())

    def routines(self) -> tuple:
        return (GapFromReversals(), DynamicsRegression(), PidTune(SERVO, servo=board_servo, can_id=CAN_ID, loop=board_loop))


def schedule() -> Routines:
    """The pendulum's routines as the planner reads them (twin.SimRunner.schedule())."""
    return Routines()
