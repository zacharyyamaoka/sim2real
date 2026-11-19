"""The toy two-drive arm the bench feedforward rulers grade against (gap FF). A ruler file like the tests beside it: written before the
code, owned by the FF session, never edited by the implementer. It needs numpy, robot_msgs, robot_trajectories and this checkout only.

The plant: gravity linear in four lumped terms (a chain's identifiable combinations; bam_fivebar.massid finds about six on the five-bar);
Coulomb friction plus a NET viscous term that is negative where friction weakens with speed (14b's 0.85 -> 0.6 N.m), the servo card's own
frictionloss_nm / damping_nm_s_rad (WHY not a separate weakening term: sign(v)(Fc - w|v|) is Fc sign(v) - w v, the same column as b v);
holds that rest on static friction, one-sided (15c's lesson: "no hold is a row").
"""

from __future__ import annotations

import math
import os
import re

import numpy as np
from robot_msgs.space import Basis, Value
from robot_msgs.trajectory import JointLimits, JointTrajectory

from sim2real import rig as seam
from sim2real.twin import Description, Instance


def _rt():
    """WHY at call time: a missing robot_trajectories turns each test that needs it red, never the whole pytest session."""
    import robot_trajectories  # noqa: PLC0415

    return robot_trajectories


SLOW = os.environ.get("SIM2REAL_SLOW") == "1"

ROUTINE = "arm.feedforward_bench"
ROUND = re.compile(r"/r(\d+)/")
DRIVES = ("j1", "j2")
GRAVITY_KEYS = ("arm.g1_cos_nm", "arm.g1_sin_nm", "arm.g2_cos_nm", "arm.g2_sin_nm")
FRICTION_KEYS = tuple(f"{d}.{name}" for d in DRIVES for name in ("frictionloss_nm", "damping_nm_s_rad"))
# The hidden truth: an end group well over CAD and a shifted centre of mass (bam_fb_v2's 14 -> 15c story), friction that weakens with speed.
TRUTH = {"arm.g1_cos_nm": 6.0, "arm.g1_sin_nm": 0.4, "arm.g2_cos_nm": 2.5, "arm.g2_sin_nm": -0.3,
         "j1.frictionloss_nm": 0.85, "j1.damping_nm_s_rad": -0.20,    # viscous 0.05 less 0.25 of weakening: net negative
         "j2.frictionloss_nm": 0.70, "j2.damping_nm_s_rad": -0.12}
NOMINAL = {"arm.g1_cos_nm": 5.0, "arm.g1_sin_nm": 0.0, "arm.g2_cos_nm": 2.0, "arm.g2_sin_nm": 0.0,
           "j1.frictionloss_nm": 0.5, "j1.damping_nm_s_rad": 0.0,
           "j2.frictionloss_nm": 0.5, "j2.damping_nm_s_rad": 0.0}
INERTIA = np.array([0.05, 0.02])        # kg.m^2 per drive, as the twin knows it
STATIC_EXTRA_NM = 0.2                   # static over kinetic friction: what a hold may rest on
GRAVITY_TOL_NM = 0.10                   # proposed (gap FF): J2's share of the 1 mm tool budget through kp x2.5 is ~0.14 N.m
FRICTION_TOL_NM = 0.05

LIMITS = JointLimits(joint_names=DRIVES, min_position=(-1.2, -1.6), max_position=(1.2, 1.6), max_velocity=(1.5, 1.5),
                     max_acceleration=(4.0, 4.0))
POSES = np.array([[0.0, 0.0], [0.9, -0.6], [-0.9, 0.8], [0.5, 1.2], [-0.6, -1.2]])
EDGES = ((0, 1), (0, 2), (1, 3), (2, 4), (3, 4), (1, 2))
BANDS = (0.3, 0.8)                      # fractions of each joint's top speed
GRID = tuple((edge, band) for band in BANDS for edge in EDGES)
FIRST = tuple((edge, BANDS[0]) for edge in EDGES)   # round 1 plays the slow band only: the fast band is an empty cell to come back for


# --- the toy arm -------------------------------------------------------------------------------------------------------------------


def space():
    return _rt().JointSpace.from_limits(LIMITS, home=(0.0, 0.0))


def regressor(q):
    """G(q) = Y(q) theta for the toy: drive 1 carries both links, drive 2 the outer one. (N, 2) positions -> (N, 2, 4)."""
    q = np.atleast_2d(np.asarray(q, float))
    outer = q[:, 0] + q[:, 1]
    y = np.zeros((len(q), 2, 4))
    y[:, 0, 0], y[:, 0, 1] = np.cos(q[:, 0]), -np.sin(q[:, 0])
    y[:, :, 2], y[:, :, 3] = np.cos(outer)[:, None], -np.sin(outer)[:, None]
    return y


def theta(values):
    return np.array([float(values[k]) for k in GRAVITY_KEYS])


def true_gravity(q):
    return regressor(q) @ theta(TRUTH)


def true_friction(drive, v, values=TRUTH):
    name = DRIVES[drive]
    v = np.asarray(v, float)
    return np.sign(v) * float(values[f"{name}.frictionloss_nm"]) + float(values[f"{name}.damping_nm_s_rad"]) * v


def inertial(q, qd, qdd):
    """What the twin says the inertia takes, besides gravity and friction."""
    return np.asarray(qdd, float) * INERTIA


def held_out_poses(n=200):
    rng = np.random.default_rng(20261118)
    return np.column_stack([rng.uniform(-1.0, 1.0, n), rng.uniform(-1.4, 1.4, n)])


def derivatives(trajectory):
    if trajectory.velocities is not None and trajectory.accelerations is not None:
        return trajectory
    return trajectory.with_derivatives()


def rows(run, index):
    """The same measurement, only these samples."""
    return JointTrajectory(t=run.t[index], joint_names=run.joint_names, positions=run.positions[index], velocities=run.velocities[index],
                           accelerations=None if run.accelerations is None else run.accelerations[index], effort=run.effort[index])


def quasi_static(command, values, sigma, rng):
    """The fast tier's plant: each drive follows its command exactly. Its torque is what that takes (gravity at the truth, Coulomb weakening
    with speed, the inertia's share) plus white noise. At rest a drive holds anywhere inside static friction; here it sags until friction
    carries part of the gravity, so its hold reads heavy (a hold bounds gravity and never equals it)."""
    c = derivatives(command)
    q, qd, qdd = c.positions, c.velocities, c.accelerations
    gravity = regressor(q) @ theta(values)
    moving = np.abs(qd) > 1e-9
    kinetic = np.column_stack([true_friction(j, qd[:, j], values) for j in range(2)])
    static = np.array([float(values[f"{d}.frictionloss_nm"]) for d in DRIVES]) + STATIC_EXTRA_NM
    tau = gravity + qdd * INERTIA + np.where(moving, kinetic, 0.6 * static * np.sign(gravity))
    tau = tau + rng.normal(0.0, sigma, tau.shape)
    return JointTrajectory(t=c.t, joint_names=c.joint_names, positions=q, velocities=qd, accelerations=qdd, effort=tau)


def collect(cells, *, sigma=0.05, seed=3, dwell_s=0.3, values=TRUTH):
    """The routine's own round-1 runs over `cells`, played on the quasi-static plant: {run id: measurement}, and {run id: cell}."""
    rng = np.random.default_rng(seed)
    runs = list(make_routine(first=tuple(cells), dwell_s=dwell_s).runs(dict(NOMINAL)))
    return {r.id: quasi_static(r.command, values, sigma, rng) for r in runs}, {r.id: tuple(r.spec["cell"]) for r in runs}


def polyline_gap(points, line):
    """The largest distance from a point of `points` to the polyline `line` (sampled: 200 points at most)."""
    start, step = line[:-1], line[1:] - line[:-1]
    length2 = np.maximum((step ** 2).sum(axis=1), 1e-300)
    worst = 0.0
    for p in points[:: max(1, len(points) // 200)]:
        s = np.clip(((p - start) * step).sum(axis=1) / length2, 0.0, 1.0)
        worst = max(worst, float(np.linalg.norm(start + s[:, None] * step - p, axis=1).min()))
    return worst


def make_routine(**overrides):
    from sim2real.calibration import FeedforwardBench  # noqa: PLC0415

    options = dict(space=space(), poses=POSES, grid=GRID, first=FIRST, drives=DRIVES, gravity_keys=GRAVITY_KEYS, regressor=regressor,
                   inertial=inertial, tolerance_nm=GRAVITY_TOL_NM, delta_nm=0.05, max_rounds=4)
    options.update(overrides)
    return FeedforwardBench(**options)


def description() -> Description:
    def values(instance):
        return {key.split(".", 1)[1]: Value(v, "N·m·s/rad" if "damping" in key else "N·m", basis=Basis.ASSUMED, source="the toy's CAD")
                for key, v in NOMINAL.items() if key.split(".", 1)[0] == instance}

    arm, j1, j2 = values("arm"), values("j1"), values("j2")
    return Description("toy_arm", "Toy two-drive arm", model=None, source="tests", instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("arm", "Toy arm", "rigid_body_chain", "cell", arm, {k: False for k in arm}),
        Instance("j1", "Drive 1", "integrated_servo", "arm", j1, {k: True for k in j1}),
        Instance("j2", "Drive 2", "integrated_servo", "arm", j2, {k: True for k in j2})))


def world_doc() -> dict:
    """The toy's world.json, read through the seal sysid.world uses: inside sealed() it raises."""
    from sysid import world as hidden  # noqa: PLC0415

    if hidden.is_sealed():
        raise hidden.SealedWorld("the toy arm's world is sealed while identification runs")
    return {"truth": dict(TRUTH), "seed": 18}


class ToyArm:
    """A RigBackend over the toy arm. It plays each run's command (run.command, the feedforward channel included; run.spec["cell"] names
    the cell) at the world's values, and logs what it was asked to play. A test reads the rounds off the rig, never off
    the routine's own account."""
    name = "toy_arm"

    def __init__(self, routine, *, closed_loop=False):
        self.routine, self.closed_loop = routine, closed_loop
        self.played: list[tuple[str, tuple]] = []
        self.asked: list[tuple[str, dict]] = []   # (stream, values) of every play: only the runner, at the world's values, may play
        self.commands: dict[str, JointTrajectory] = {}

    def parameters(self):
        fitted = set(self.routine.identifies)

        def named(key):   # WHY: a key the routine under test leaves out of its model (the blind model's sin terms) names no routine
            return (ROUTINE, "") if key in fitted else (None, "the routine under test leaves it out of its model")

        out = [seam.Parameter(k, "N·m", ("abs", 0.05), "proposed (gap FF): half the fit's gravity tolerance", *named(k)) for k in GRAVITY_KEYS]
        for d in DRIVES:
            out.append(seam.Parameter(f"{d}.frictionloss_nm", "N·m", ("abs", 0.03), "proposed (gap FF)", *named(f"{d}.frictionloss_nm")))
            out.append(seam.Parameter(f"{d}.damping_nm_s_rad", "N·m·s/rad", ("abs", 0.05), "proposed (gap FF)",
                                      *named(f"{d}.damping_nm_s_rad")))
        return tuple(out)

    def noise(self):
        source = {"torque_noise_nm": "assumed: a board's q-current x Kt noise"}
        if self.closed_loop:
            return seam.NoiseModel(encoder_quantum_rad=2 * math.pi / 163840, velocity_noise_rad_s=0.005, torque_noise_nm=0.05,
                                   torque_disturbance_nm=0.02, sources=source)
        return seam.NoiseModel(torque_noise_nm=0.05, sources=source)

    def routines(self):
        return (self.routine,)

    def held_out(self, values=None):
        return []

    def measure(self, runs, values, noise, stream, *, workers=1):
        out = {}
        for run in runs:
            cell = tuple(run.spec["cell"])
            self.played.append((run.id, cell))
            self.asked.append((stream, dict(values)))
            self.commands[run.id] = run.command
            rng = noise.rng(stream, run.id)
            if self.closed_loop:
                out[run.id] = closed_loop(run.command, values, noise, rng, warm=len(self.played))
            else:
                out[run.id] = quasi_static(run.command, values, noise.effective()["torque_noise_nm"], rng)
        return out

    def predict(self, measured, values, *, workers=1):
        return {}

    def score(self, predicted, measured):
        return seam.Score({d: 0.0 for d in DRIVES})


def runner(rig) -> seam.RigRunner:
    return seam.RigRunner(description(), rig, workers=1, world=world_doc)   # WHY 1: any pool stays <= 2 while the arm is powered




# --- the closed-loop plant (the SIM2REAL_SLOW tier) ----------------------------------------------------------------------------------------

DT, HOST = 1e-3, 10            # a 1 kHz board under a 100 Hz host: each command (target and feedforward) held 10 ms, one tick late
KP, KD, TAU_MAX = np.array([30.0, 20.0]), np.array([1.0, 0.6]), 12.0
TRUE_INERTIA = 1.1 * INERTIA   # the twin's inertia is a CAD value 10 % light: nothing calibrates it today
RIPPLE_NM, RIPPLE_PER_RAD = 0.04, 50.0   # a cogging line whose phase is re-drawn at every enable (memory can11-ripple-redrawn-per-enable)


def closed_loop(command, values, noise, rng, *, warm=0, gains=None):
    """The slow tier's plant. PD plus the command's feedforward channel runs on a 1 kHz board; the host's command is held over each tick and
    arrives one tick late. Friction is Karnopp stiction (static = kinetic + 0.2 N.m) and Coulomb that weakens with speed and warms over the
    session; a ripple is re-drawn per run; a disturbance is held over each host tick. The log is at the host rate, with the encoder's step,
    speed noise and the board's torque noise; it carries the feedforward sent and the target the board chased."""
    c = command if command.velocities is not None else command.with_derivatives()
    e = noise.effective()
    t = c.t[0] + np.arange(int((c.t[-1] - c.t[0]) / DT) + 1) * DT
    ref_q = np.column_stack([np.interp(t, c.t, c.positions[:, j]) for j in range(2)])
    ref_qd = np.column_stack([np.interp(t, c.t, c.velocities[:, j]) for j in range(2)])
    sent = np.asarray(c.channels["feedforward_effort"], float) if "feedforward_effort" in c.channels else np.zeros_like(c.positions)
    ref_ff = np.column_stack([np.interp(t, c.t, sent[:, j]) for j in range(2)])
    held = np.maximum((np.arange(len(t)) // HOST - 1) * HOST, 0)
    kp, kd = (KP, KD) if gains is None else (np.asarray(gains[0], float), np.asarray(gains[1], float))
    fc = np.array([float(values[f"{d}.frictionloss_nm"]) for d in DRIVES]) * (1.0 + 5e-4 * warm)
    b = np.array([float(values[f"{d}.damping_nm_s_rad"]) for d in DRIVES])
    fs, gravity_terms, phase = fc + STATIC_EXTRA_NM, theta(values), rng.uniform(0.0, 2 * math.pi, 2)
    q, qd, push = ref_q[0].copy(), np.zeros(2), np.zeros(2)
    log_q, log_qd, log_tau, log_ff = (np.empty((len(t), 2)) for _ in range(4))
    for i, k in enumerate(held):
        if i % HOST == 0:
            push = rng.normal(0.0, e["torque_disturbance_nm"], 2)
        tau = np.clip(kp * (ref_q[k] - q) + kd * (ref_qd[k] - qd) + ref_ff[k], -TAU_MAX, TAU_MAX)
        net = tau + push - regressor(q)[0] @ gravity_terms - RIPPLE_NM * np.sin(RIPPLE_PER_RAD * q + phase)
        moving = np.abs(qd) > 0.01
        stuck = ~moving & (np.abs(net) <= fs)
        friction = np.where(moving, np.sign(qd) * fc + b * qd, np.where(stuck, net, np.sign(net) * fc))
        qd = np.where(stuck, 0.0, qd + (net - friction) / TRUE_INERTIA * DT)
        q = q + qd * DT
        log_q[i], log_qd[i], log_tau[i], log_ff[i] = q, qd, tau, ref_ff[k]
    keep = np.arange(0, len(t), HOST)
    # WHY the board's torque averaged over each host period, not its first tick: the target is held for the period while q moves on, so the
    # first tick sits kp x v x 4.5 ms over what the plant feels on average, an apparent viscous term (+0.135 / +0.090 N.m.s/rad) no fit over
    # (q, qd, effort) can tell from friction (FF-2 fix round 1, cloud d07280523: at HOST=1 friction recovers within 0.005 N.m)
    effort = np.add.reduceat(log_tau, keep, axis=0) / np.diff(np.append(keep, len(t)))[:, None]
    position = log_q[keep] + rng.normal(0.0, e["encoder_noise_rad"], (len(keep), 2))
    if e["encoder_quantum_rad"] > 0:
        position = np.round(position / e["encoder_quantum_rad"]) * e["encoder_quantum_rad"]
    return JointTrajectory(t=t[keep], joint_names=DRIVES, positions=position,
                           velocities=log_qd[keep] + rng.normal(0.0, e["velocity_noise_rad_s"], (len(keep), 2)),
                           effort=effort + rng.normal(0.0, e["torque_noise_nm"], (len(keep), 2)),
                           channels={"feedforward_effort": log_ff[keep], "target_positions": ref_q[held[keep]]})


def share_and_tracking(run):
    """This file's own ruler: the feedback torque's share of the command, and the error to the target the board chased, on moving rows."""
    moving = np.abs(run.velocities).max(axis=1) > 0.05
    effort, sent = run.effort[moving], np.asarray(run.channels["feedforward_effort"])[moving]
    share = math.sqrt(np.mean((effort - sent) ** 2)) / math.sqrt(np.mean(effort ** 2))
    tracking = math.sqrt(np.mean((run.positions[moving] - np.asarray(run.channels["target_positions"])[moving]) ** 2))
    return share, tracking



def bare(command):
    """The same motion with no feedforward channel: what the board's PD alone is handed."""
    c = derivatives(command)
    return JointTrajectory(t=c.t, joint_names=c.joint_names, positions=c.positions, velocities=c.velocities, accelerations=c.accelerations)
