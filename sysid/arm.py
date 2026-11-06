"""The UR5e examples' machinery (bare arm, arm + 2F-85): the "real" arm at a hidden truth in MuJoCo, the schedule, and the fits.

The arm is Menagerie's MJCF driven by Menagerie's own position servos (kp 2000 / 500, kv 400 / 100, torque limits 150 / 28): the
real loop, not a teleport (bam_arm.cell's arm). A joint zero error is where the servo's encoder zero sits against the link: the
servo holds the ENCODER at its command, so the link sits at command + offset and the encoder reads link - offset.

Identification, in calibration order (a later step uses an earlier step's result, never the truth):

1. kinematics: the joint zero offsets (and, carrying a gripper, the TCP) by least squares of FK(q_encoder + offset) on the
   tracker's flange pose (and the TCP marker) at static poses;
2. joint servo dynamics: measured joint torque minus MuJoCo's rigid-body inverse dynamics (mj_inverse with armature, damping and
   friction zeroed) regressed on qdd, qd and sgn(qd) per joint, plus the tool's mass and centre of mass as regressor columns
   (finite differences of the inverse dynamics, re-linearised twice); joint speed below 0.02 rad/s is sticking and not regressed;
3. the gripper's drive: its force per count and damping by least squares of simulated finger traces on measured ones.

Held-out (black box, command in, measurement out): the tool position the twin predicts for a commanded pose against the tracker's,
and the joint torque the twin needs to follow the held-out excitation against the measured one.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field

import numpy as np

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3")
# WHY these ranges: inside Menagerie's limits and away from the base (shoulder lift above horizontal-down, elbow folded either way)
POSE_RANGES = ((-3.0, 3.0), (-2.6, -0.5), (-2.5, 2.5), (-3.0, 3.0), (-3.0, 3.0), (-3.0, 3.0))
EXCITATION_AMPLITUDE = (0.7, 0.5, 0.6, 0.9, 0.9, 1.0)
EXCITATION_CENTRE = (0.0, -1.4, 1.5, -1.6, -1.57, 0.0)
EXCITATION_PEAK_SPEED = 1.2  # rad/s
MOVING = 0.02  # rad/s
DT = 0.002
SETTLE_S = 1.5
TRACKER_EVERY = 10  # the tracker samples at 50 Hz during an excitation
HARD_FRICTION_SOLREF = (0.0004, 1.0)  # bam_rack_twin.twin.HARD_FRICTION_SOLREF (MuJoCo clamps the time constant to 2 steps)
HARD_FRICTION_SOLIMP = (0.99, 0.99, 0.001, 0.5, 2.0)  # bam_rack_twin.twin.HARD_FRICTION_SOLIMP
BOOTSTRAP = 200
SMOOTHER = 41  # samples (82 ms at 500 Hz): one Savitzky-Golay cubic on every channel the regression reads


def rng_for(seed: int, *names) -> np.random.Generator:
    return np.random.default_rng([seed, *(zlib.crc32(str(n).encode()) for n in names)])


# --- the model ----------------------------------------------------------------------------------------------------------------------

@dataclass
class ArmModel:
    """A compiled arm (+ gripper) with the indices every step needs."""
    model: object
    joint_ids: list
    qpos: np.ndarray
    dof: np.ndarray
    actuators: np.ndarray
    flange_site: int
    gripper: dict | None = None

    @classmethod
    def build(cls, description, prefix: str = ""):
        import mujoco  # noqa: PLC0415

        model = description.spec().compile()
        model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_CONTACT)
        joint_ids = [model.joint(f"{prefix}{j}_joint").id for j in JOINTS]
        gripper = None
        try:
            gripper = {"actuator": model.actuator(f"{prefix}grip_fingers_actuator").id, "driver": model.joint(f"{prefix}grip_right_driver_joint").id,
                       "body": model.body(f"{prefix}grip_base").id, "pinch": model.site(f"{prefix}grip_pinch").id}
        except KeyError:
            pass
        dof = model.jnt_dofadr[joint_ids].copy()
        # WHY a hard friction constraint on every arm joint, truth and twin alike (bam_rack_twin.twin's HARD_FRICTION_SOLREF / _SOLIMP):
        # MuJoCo's frictionloss is a soft constraint whose regularisation grows as the joint's inertia shrinks, so on the wrists a
        # "Coulomb" level acts as a viscous ramp (measured 2026-11-05: wrist frictionloss read 10-18 % low, damping 40-90 % high).
        # Hard, the parameter is the Coulomb level the data shows, which is what a description's friction means.
        model.dof_solref[dof] = HARD_FRICTION_SOLREF
        model.dof_solimp[dof] = HARD_FRICTION_SOLIMP
        return cls(model, joint_ids, model.jnt_qposadr[joint_ids].copy(), dof,
                   np.array([model.actuator(f"{prefix}{j}").id for j in JOINTS]), model.site(f"{prefix}attachment_site").id, gripper)

    def set_values(self, values: dict) -> None:
        """Write identified (or true) values into the compiled model: per-joint armature / damping / frictionloss, the tool's mass,
        centre of mass and TCP, the gripper's gain and damping. Keys without a prefix: "<joint>.<name>", "tool.<name>", "gripper.<name>"."""
        import mujoco  # noqa: PLC0415

        m = self.model
        for j, jid, dof in zip(JOINTS, self.joint_ids, self.dof):
            for name, array in (("armature_kg_m2", m.dof_armature), ("damping_nm_s_rad", m.dof_damping), ("frictionloss_nm", m.dof_frictionloss)):
                if f"{j}.{name}" in values:
                    array[dof] = max(0.0, float(values[f"{j}.{name}"]))
        g = self.gripper
        if g:
            if "tool.mass_kg" in values:
                m.body_mass[g["body"]] = float(values["tool.mass_kg"])
            if "tool.com_z_m" in values:
                m.body_ipos[g["body"], 2] = float(values["tool.com_z_m"])
            if "tool.tcp_x_m" in values:
                m.site_pos[g["pinch"], 0] = float(values["tool.tcp_x_m"])
            if "tool.tcp_y_m" in values:
                m.site_pos[g["pinch"], 1] = float(values["tool.tcp_y_m"])
            if "tool.tcp_z_m" in values:
                m.site_pos[g["pinch"], 2] = float(values["tool.tcp_z_m"])
            if "gripper.actuator_gain" in values:
                m.actuator_gainprm[g["actuator"], 0] = float(values["gripper.actuator_gain"])
            if "gripper.damping" in values:
                m.actuator_biasprm[g["actuator"], 2] = -float(values["gripper.damping"])
        mujoco.mj_setConst(m, mujoco.MjData(m))

    def offsets(self, values: dict) -> np.ndarray:
        return np.array([float(values.get(f"{j}.zero_offset_rad", 0.0)) for j in JOINTS])


# --- the schedule --------------------------------------------------------------------------------------------------------------

@dataclass
class ArmPlan:
    poses_train: np.ndarray
    poses_held_out: np.ndarray
    excitations_train: list[np.ndarray]   # (samples, 6) commanded encoder angles at DT
    excitations_held_out: list[np.ndarray]
    gripper_train: np.ndarray | None = None  # (samples,) commanded counts at DT
    gripper_held_out: np.ndarray | None = None
    hold: np.ndarray = field(default_factory=lambda: np.array([0.0, -1.2, 1.4, -1.77, -1.5708, 0.0]))
    coverage: dict = field(default_factory=dict)
    sweep_train: list[np.ndarray] = field(default_factory=list)  # the coverage sweep: (samples, 6) commanded encoder angles at DT
    sweep_held_out: list[np.ndarray] = field(default_factory=list)
    sweep: dict = field(default_factory=dict)  # how the sweep was built (waypoints, limits, seconds)
    mount: str = "ur5e_floor"  # the arm card's reachable mask the coverage counts over (type_cards.coverage.ARM_MOUNTS)

    def trajectories(self, split: str) -> list[np.ndarray]:
        """Every commanded trajectory of a split the dynamics fit and the coverage read: the excitations, then the sweep."""
        return list(getattr(self, f"excitations_{split}")) + list(getattr(self, f"sweep_{split}"))


def fourier_excitation(rng, duration_s: float = 10.0, base_hz: float = 0.2, harmonics: int = 5) -> np.ndarray:
    """Swevers et al. (1997)'s periodic excitation per joint, scaled to its amplitude and the peak speed, faded in and out (0.6 s).

    WHY a 0.2 Hz base (harmonics to 1 Hz; the first schedule had 0.1 Hz, measured 2026-11-05): at the same peak speed the
    accelerations double, and with them the share of each joint's torque its reflected inertia carries. At 0.1 Hz, under the
    gripper, the shoulder lift's inertia read 7 % low on every noise seed (the speed noise in qdd times the joint's whole inertia)
    and the elbow's scattered +-7 %; excitation design is exactly the knob Swevers et al. optimise."""
    t = np.arange(0.0, duration_s, DT)
    w = 2 * math.pi * base_hz
    out = np.zeros((t.size, len(JOINTS)))
    fade = np.clip(np.minimum(t, duration_s - t) / 0.6, 0.0, 1.0)
    fade = 0.5 - 0.5 * np.cos(math.pi * fade)
    for i, (centre, amplitude) in enumerate(zip(EXCITATION_CENTRE, EXCITATION_AMPLITUDE)):
        a, b = rng.normal(size=harmonics), rng.normal(size=harmonics)
        shape = sum(a[l] / (w * (l + 1)) * np.sin(w * (l + 1) * t) - b[l] / (w * (l + 1)) * np.cos(w * (l + 1) * t) for l in range(harmonics))
        shape = (shape - shape.mean()) * fade
        shape *= amplitude / max(1e-9, np.abs(shape).max())
        speed = np.abs(np.gradient(shape, DT)).max()
        if speed > EXCITATION_PEAK_SPEED:
            shape *= EXCITATION_PEAK_SPEED / speed
        out[:, i] = centre + shape
    return out


def gripper_steps(levels, dwell_s: float = 0.8) -> np.ndarray:
    return np.concatenate([np.full(int(round(dwell_s / DT)), float(level)) for level in levels])


def plan(description, *, gripper: bool = False) -> ArmPlan:
    """The schedule: static poses and Fourier excitations (both re-drawn until the arm clears the floor and itself), then the
    coverage sweep that takes the train split to the arm card's coverage gate."""
    s = description.schedule
    clear = Clearance(description)
    rng = rng_for(s["seed"], "plan")
    lo, hi = np.array(POSE_RANGES).T
    # WHY drawn until clear (2026-11-05, arm-coverage lane): uniform draws over POSE_RANGES put 8 of the bare arm's 40 train poses
    # in the floor or in the arm itself; MuJoCo's contacts are off, so the "real" arm went there, a real one cannot
    poses = []
    while len(poses) < s["poses_train"] + s["poses_held_out"]:
        q = rng.uniform(lo, hi)
        if clear(q):
            poses.append(q)
    poses = np.array(poses)
    excitations = [clear_excitation(clear, s["seed"], k) for k in range(s["excitations_train"] + s["excitations_held_out"])]
    p = ArmPlan(poses[: s["poses_train"]], poses[s["poses_train"]:], excitations[: s["excitations_train"]], excitations[s["excitations_train"]:])
    if gripper:
        p.gripper_train = np.concatenate([gripper_steps((0, 64, 128, 192, 255, 192, 128, 64, 0, 255)), gripper_steps((0, 255, 0, 128, 0))])
        p.gripper_held_out = gripper_steps((0, 40, 100, 170, 230, 100, 0))
        p.mount = "ur5e_2f85_floor"  # the arm carries the 2F-85: its reachable cells are the arm-with-gripper's
    sweep = s.get("sweep")
    if sweep:
        start = [{"joint space": tuple(q)} for q in coverage_points(p.poses_train, p.excitations_train)]
        p.sweep_train, p.sweep = coverage_sweep(clear, sweep, p.hold, start, mount=p.mount)
    p.coverage = arm_coverage(p)
    return p


def clear_excitation(clear, seed: int, k: int) -> np.ndarray:
    """Excitation k: the first of its draws whose every 10 ms sample clears the floor and the arm (draw 0 is the original one)."""
    for attempt in range(50):
        names = ("excitation", k) if attempt == 0 else ("excitation", k, attempt)
        e = fourier_excitation(rng_for(seed, *names))
        if all(clear(q) for q in e[::5]):
            return e
    raise RuntimeError(f"no collision-free excitation {k} in 50 draws")


# --- coverage: the arm card's joint cube, and the sweep that fills it -----------------------------------------------------------

COVERAGE_EVERY = 25  # the coverage rule reads every 25th commanded sample (50 ms)


def coverage_points(poses, trajectories) -> list:
    return [*(tuple(q) for q in poses), *(tuple(q) for e in trajectories for q in e[::COVERAGE_EVERY])]


def arm_coverage(p: ArmPlan) -> dict:
    from type_cards import coverage as cov  # noqa: PLC0415

    out = {}
    for split in ("train", "held_out"):
        trajectories = p.trajectories(split)
        poses = getattr(p, f"poses_{split}")
        c = cov.arm_coverage([{"joint space": q} for q in coverage_points(poses, trajectories)], mount=p.mount)
        sweep_s = sum(e.shape[0] for e in getattr(p, f"sweep_{split}")) * DT
        motion_s = sum(e.shape[0] for e in trajectories) * DT
        base = cov.arm_coverage([{"joint space": q} for q in coverage_points(poses, getattr(p, f"excitations_{split}"))], mount=p.mount)
        # visited cells per joint and bin: where the cube is filled, and the shoulder lift's cell 3 (unreachable from home) shown empty
        per_bin = [[sum(1 for cell in c.cells if cell[j] == b) for b in range(cov.JOINT_BINS)] for j in range(len(JOINTS))]
        out[split] = {"pct": c.pct, "visited": c.visited, "reachable": c.reachable, "samples": c.samples, "axes": c.axes, "unplanned": list(c.unplanned),
                      "motion_s": round(motion_s, 1), "sweep_s": round(sweep_s, 1), "settle_s": round(len(poses) * SETTLE_S, 1),
                      "without_sweep_pct": base.pct, "visited_by_joint_bin": per_bin}
    out["function"] = (f"type_cards.coverage.arm_coverage over {p.mount}'s reachable cells (4 cells per joint inside the limits: the 4096-cell joint cube, "
                       f"{len(cov.arm_reachable_cells(p.mount)):,} of them reachable)")
    out["reachable_mask"] = p.mount
    out["rule"] = ("share of the joint cube's reachable cells the static poses, the excitations and the coverage sweep (every 50 ms) visit; "
                   "tool voxels need FK (a marginal, not planned here)")
    if p.sweep:
        out["sweep"] = p.sweep
    return out


class Clearance:
    """q -> True when the arm (and its gripper) clears the floor by `floor_m` and itself by `self_m`: MuJoCo's own collision
    detection on the description's collision geoms (Menagerie's capsules, the 2F-85's meshes) plus a floor plane at the base's
    mounting plane. The simulator that plays the real arm runs with contacts off, so this is the only thing keeping a schedule
    one a real arm on a floor could run. The 2F-85's linkage touching itself is by design and ignored."""

    def __init__(self, description, floor_m: float = 0.05, self_m: float = 0.01):
        import mujoco  # noqa: PLC0415

        spec = description.spec()
        floor = spec.worldbody.add_geom()
        floor.name, floor.type, floor.size = "clearance_floor", mujoco.mjtGeom.mjGEOM_PLANE, [5.0, 5.0, 0.1]
        m = spec.compile()
        self.model, self.data = m, mujoco.MjData(m)
        self.floor = m.geom("clearance_floor").id
        m.geom_margin[:] = self_m
        m.geom_margin[self.floor] = floor_m
        self.floor_m, self.self_m = floor_m, self_m
        self.qadr = m.jnt_qposadr[[m.joint(f"{j}_joint").id for j in JOINTS]]
        self.gripper = {b for b in range(m.nbody) if m.body(b).name.startswith("grip_")}
        # the shoulder link only turns about the base's vertical axis: its capsule sits 3 mm over the mounting plane at any pan
        self.fixed_height = {m.body("shoulder_link").id}
        self.rest = self.data.qpos.copy()
        self.calls = 0

    def __call__(self, q) -> bool:
        import mujoco  # noqa: PLC0415

        m, d = self.model, self.data
        self.calls += 1
        d.qpos[:] = self.rest
        d.qpos[self.qadr] = q
        mujoco.mj_kinematics(m, d)
        mujoco.mj_collision(m, d)
        for c in d.contact[: d.ncon]:
            b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
            if self.floor in (c.geom1, c.geom2):
                if c.dist < self.floor_m and not ({b1, b2} & self.fixed_height):
                    return False
            elif not (b1 in self.gripper and b2 in self.gripper) and c.dist < self.self_m:
                return False
        return True


def min_jerk(q0: np.ndarray, q1: np.ndarray, speed: float, accel: float, quantum: int = COVERAGE_EVERY) -> np.ndarray:
    """Rest-to-rest minimum-jerk move (s = 10t^3 - 15t^4 + 6t^5), every joint arriving together, its time the shortest that keeps
    the moving-most joint under `speed` (peak 15/8 D/T) and `accel` (peak 10/sqrt(3) D/T^2), rounded up to whole `quantum`s of
    samples (so every segment starts on the coverage rule's 50 ms stride). Samples at DT, q0 excluded, q1 included."""
    span = float(np.abs(q1 - q0).max())
    seconds = max(15.0 / 8.0 * span / speed, math.sqrt(10.0 / math.sqrt(3.0) * span / accel), DT * quantum)
    n = int(math.ceil(seconds / DT / quantum)) * quantum
    t = np.arange(1, n + 1) / n
    s = 10 * t ** 3 - 15 * t ** 4 + 6 * t ** 5
    return q0 + s[:, None] * (q1 - q0)


def cell_of(q: np.ndarray, edges: np.ndarray) -> int:
    """The card's joint cube cell (numpy.histogramdd's [lo, hi) bins, the last closed) as one integer, base JOINT_BINS."""
    bins = edges.shape[1] - 1
    i = np.clip(np.array([np.searchsorted(edges[j], q[..., j], side="right") - 1 for j in range(q.shape[-1])]), 0, bins - 1)
    return (np.moveaxis(i, 0, -1) * bins ** np.arange(q.shape[-1])).sum(-1)


def coverage_sweep(clear: Clearance, cfg: dict, start_q: np.ndarray, already: list, mount: str = "ur5e_floor") -> tuple[list, dict]:
    """A collision-free tour that takes the joint cube's coverage (with what the poses and excitations already visit) to
    cfg["target_pct"] of the mount's reachable cells (type_cards.coverage.arm_reachable_cells).

    1. Waypoints: a scrambled Sobol sequence (scipy.stats.qmc) of 2^m points over the card's joint box, the shoulder lift held to
       the span a floor-mounted arm reaches from its home posture (lift_span_rad), each kept only where the arm clears the floor
       and itself; each cell's waypoint is its first clear point in the sequence.
    2. Order: from the hold posture, the next waypoint is the one whose straight joint-space minimum-jerk move visits the most
       new cells per second, among the `candidates` unvisited waypoints nearest in move time, and whose every 10 ms sample is clear.
    3. Cut into trajectories of at most chunk_s seconds at rest points (each one starts where the last stopped).

    WHY a sweep and not wider Fourier excitations (2026-11-05): the card's cube has 4 cells per joint over +-2 pi (the elbow +-pi),
    so a cell is pi rad wide on five joints; an excitation around one centre visits tens of cells (32 of 4096 here), and 40 %
    needs 1,024 of the mounted arm's 2,560 reachable cells (it was 1,639 of the box before 2026-11-05). WHY the shoulder lift's span: its cells 1 and 3 are the same physical posture 2 pi
    apart, and the move from one to the other swings the upper arm through the floor, so a schedule on a real arm covers one."""
    from scipy.stats import qmc  # noqa: PLC0415
    from type_cards import coverage as cov  # noqa: PLC0415

    limits = np.array(cov.UR5E_LIMITS)
    bins = cov.JOINT_BINS
    edges = np.array([np.linspace(lo, hi, bins + 1) for lo, hi in limits])
    margin = cfg["limit_margin_rad"]
    box_lo, box_hi = limits[:, 0] + margin, limits[:, 1] - margin
    box_lo[1], box_hi[1] = cfg["lift_span_rad"]
    sobol = qmc.Sobol(d=len(JOINTS), scramble=True, seed=cfg["seed"])
    pool = qmc.scale(sobol.random_base2(cfg["sobol_log2"]), box_lo, box_hi)
    cells = cell_of(pool, edges)
    waypoints: dict[int, np.ndarray] = {}
    for q, c in zip(pool, cells):
        if int(c) not in waypoints and clear(q):
            waypoints[int(c)] = q
    visited = {int(c) for c in cell_of(np.array([p["joint space"] for p in already]), edges)} if already else set()
    # WHY the target over the mount's reachable cells (2026-11-05, sweep-trim lane; was ceil(42 % of the 4,096-cell box) = 1,721
    # cells): the card's gate is a share of the reachable cells (docs/decision-arm-reachable-coverage-2026-11-05.md), so the sweep
    # runs to target_pct of them, a stated margin above the gate, and only cells inside the mask count towards it
    reach = {sum(i * bins ** j for j, i in enumerate(cell)) for cell in cov.arm_reachable_cells(mount)}
    reachable = len(reach)
    target = math.ceil(cfg["target_pct"] / 100.0 * reachable)
    speed, accel, check = cfg["speed_rad_s"], cfg["accel_rad_s2"], 5
    open_cells = [c for c in waypoints if c not in visited]
    q = np.asarray(start_q, float)
    segments, rejected = [], 0
    def counted() -> int:
        return len(visited & reach)

    elapsed, curve = 0.0, [(0.0, round(100.0 * counted() / reachable, 2))]
    while counted() < target and open_cells:
        targets = np.array([waypoints[c] for c in open_cells])
        span = np.abs(targets - q).max(axis=1)
        nearest = np.argsort(span)[: cfg["candidates"]]
        scored = []
        for i in nearest:
            move = min_jerk(q, targets[i], speed, accel)
            new = {int(c) for c in cell_of(move[::COVERAGE_EVERY], edges)} - visited  # the samples the coverage rule reads
            scored.append((len(new) / (move.shape[0] * DT), i, move, new))
        scored.sort(key=lambda row: -row[0])
        for _, i, move, new in scored:
            if all(clear(x) for x in move[check - 1::check]):
                break
            rejected += 1
        else:  # no near waypoint is reachable in a straight move from here: drop the nearest, try again
            open_cells.pop(int(nearest[0]))
            continue
        segments.append(move)
        visited |= new
        elapsed += move.shape[0] * DT
        if elapsed - curve[-1][0] >= 15.0:
            curve.append((round(elapsed, 1), round(100.0 * counted() / reachable, 2)))
        q = move[-1]
        open_cells = [c for c in open_cells if c not in visited]
    if counted() < target:
        raise RuntimeError(f"the sweep reached {counted()} of {target} reachable cells: no reachable waypoint left")
    home = min_jerk(q, np.asarray(start_q, float), speed, accel)
    if all(clear(x) for x in home[check - 1::check]):
        segments.append(home)
    chunks, current, length = [], [], 0
    limit = int(round(cfg["chunk_s"] / DT))
    for seg in segments:
        if current and length + seg.shape[0] > limit:
            chunks.append(current)
            current, length = [], 0
        current.append(seg)
        length += seg.shape[0]
    chunks.append(current)
    # each chunk opens with 50 ms at rest where its first move starts (the hold posture, then the last chunk's end): the arm
    # settles there, and every move still starts on the coverage rule's stride
    out, q0 = [], np.asarray(start_q, float)
    for chunk in chunks:
        out.append(np.vstack([np.repeat(q0[None, :], COVERAGE_EVERY, 0)] + chunk))
        q0 = chunk[-1][-1]
    seconds = sum(t.shape[0] for t in out) * DT
    info = {"waypoints": len(segments), "candidate_cells": len(waypoints), "sobol_points": int(pool.shape[0]), "rejected_moves": rejected,
            "seconds": round(seconds, 1), "trajectories": len(out), "speed_rad_s": speed, "accel_rad_s2": accel,
            "lift_span_rad": list(cfg["lift_span_rad"]), "floor_clearance_m": clear.floor_m, "self_clearance_m": clear.self_m,
            "target_pct": cfg["target_pct"], "target_cells": target, "target_of": "reachable cells", "reachable_mask": mount, "reachable_cells": reachable, "curve_of": "reachable cells",
            "seed": cfg["seed"], "curve": curve + [(round(elapsed, 1), round(100.0 * counted() / reachable, 2))],
            "rule": "scrambled Sobol waypoints (one per joint-cube cell, collision-free), toured greedily by new cells per second, "
                    "straight joint-space minimum-jerk moves, every 10 ms sample clear of the floor and the arm"}
    return out, info


# --- the real arm ----------------------------------------------------------------------------------------------------------------

def settle(arm: ArmModel, data, ctrl: np.ndarray, link_start: np.ndarray, seconds: float = SETTLE_S, gripper_ctrl: float | None = None):
    import mujoco  # noqa: PLC0415

    mujoco.mj_resetData(arm.model, data)
    data.qpos[arm.qpos] = link_start
    data.ctrl[arm.actuators] = ctrl
    if arm.gripper and gripper_ctrl is not None:
        data.ctrl[arm.gripper["actuator"]] = gripper_ctrl
    mujoco.mj_forward(arm.model, data)
    for _ in range(int(round(seconds / DT))):
        mujoco.mj_step(arm.model, data)


def site_pose(model, data, site: int) -> tuple[np.ndarray, np.ndarray]:
    return data.site_xpos[site].copy(), data.site_xmat[site].reshape(3, 3).copy()


def run_excitation(arm: ArmModel, command: np.ndarray, offsets: np.ndarray, gripper_ctrl: float = 0.0):
    """Follow `command` (encoder angles) from rest: (link q, qd, joint torque, flange poses every TRACKER_EVERY, TCP positions)."""
    import mujoco  # noqa: PLC0415

    model = arm.model
    data = mujoco.MjData(model)
    settle(arm, data, command[0] + offsets, command[0] + offsets, seconds=0.5, gripper_ctrl=gripper_ctrl)
    n = command.shape[0]
    q, qd, tau = np.zeros((n, 6)), np.zeros((n, 6)), np.zeros((n, 6))
    poses, tcp = [], []
    # WHY the torque less kv (v_end - v_start) (measured 2026-11-05): Menagerie's servos run under implicitfast, which applies each
    # servo's damping at the END-of-step velocity, so the torque the joint actually received over a step is actuator_force (computed
    # at the start) - kv dv; regressing on actuator_force itself read h kv (0.8 kg.m^2 on the big joints) as reflected inertia, and
    # data.qacc is the explicit acceleration, not the step's dv / h (using it over-corrected to -0.5 kg.m^2). A torque sensor reads
    # the applied torque. The angle is the step's start (where the forces were computed), the speed its end (what the damping used).
    kv = -model.actuator_biasprm[arm.actuators, 2]
    for k in range(n):
        data.ctrl[arm.actuators] = command[k] + offsets
        q[k] = data.qpos[arm.qpos]
        v_start = data.qvel[arm.dof].copy()
        mujoco.mj_step(model, data)
        qd[k] = data.qvel[arm.dof]
        tau[k] = data.actuator_force[arm.actuators] - kv * (qd[k] - v_start)
        if k % TRACKER_EVERY == 0:
            poses.append(site_pose(model, data, arm.flange_site))
            if arm.gripper:
                tcp.append(data.site_xpos[arm.gripper["pinch"]].copy())
    return q, qd, tau, poses, tcp


def run_gripper(arm: ArmModel, counts: np.ndarray, hold: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    import mujoco  # noqa: PLC0415

    data = mujoco.MjData(arm.model)
    settle(arm, data, hold + offsets, hold + offsets, seconds=0.5, gripper_ctrl=float(counts[0]))
    out = np.zeros(counts.size)
    driver = arm.model.jnt_qposadr[arm.gripper["driver"]]
    for k, c in enumerate(counts):
        data.ctrl[arm.gripper["actuator"]] = c
        mujoco.mj_step(arm.model, data)
        out[k] = data.qpos[driver]
    return out


@dataclass
class ArmMeasured:
    poses: list[dict]          # static: commanded, encoder q, flange (p, R), TCP p
    excitations: list[dict]    # encoder q, qd, torque, command, flange poses
    gripper: dict | None = None


def measure(arm: ArmModel, values: dict, noise: dict, seed: int, poses: np.ndarray, excitations: list, gripper_counts=None, hold=None,
            label: str = "") -> ArmMeasured:
    """The arm at `values` (the hidden truth) through the description's sensors, each with its noise."""
    import mujoco  # noqa: PLC0415
    from scipy.spatial.transform import Rotation  # noqa: PLC0415

    arm.set_values(values)
    offsets = arm.offsets(values)
    data = mujoco.MjData(arm.model)
    big = np.array([noise["torque_large_nm"]] * 3 + [noise["torque_small_nm"]] * 3)
    static = []
    for k, command in enumerate(poses):
        rng = rng_for(seed, label, "pose", k)
        settle(arm, data, command + offsets, command + offsets)
        p, R = site_pose(arm.model, data, arm.flange_site)
        row = {"command": command.copy(), "q": data.qpos[arm.qpos] - offsets + rng.normal(0, noise["encoder_rad"], 6),
               "p": p + rng.normal(0, noise["tracker_position_m"], 3),
               "R": Rotation.from_rotvec(rng.normal(0, noise["tracker_orientation_rad"], 3)).as_matrix() @ R}
        if arm.gripper:
            row["tcp"] = data.site_xpos[arm.gripper["pinch"]].copy() + rng.normal(0, noise["tcp_tracker_m"], 3)
        static.append(row)
    dynamic = []
    for k, command in enumerate(excitations):
        rng = rng_for(seed, label, "excitation", k)
        q, qd, tau, flange, tcp = run_excitation(arm, command, offsets)
        dynamic.append({"command": command, "q": q - offsets + rng.normal(0, noise["encoder_rad"], q.shape),
                        "qd": qd + rng.normal(0, noise["speed_rad_s"], qd.shape), "tau": tau + rng.normal(0, 1.0, tau.shape) * big,
                        "flange_p": np.array([p for p, _ in flange]) + rng.normal(0, noise["tracker_position_m"], (len(flange), 3)),
                        "tcp_p": np.array(tcp) + rng.normal(0, noise.get("tcp_tracker_m", 0.0), (len(tcp), 3)) if tcp else None})
    grip = None
    if gripper_counts is not None:
        rng = rng_for(seed, label, "gripper")
        trace = run_gripper(arm, gripper_counts, hold, offsets)
        grip = {"counts": gripper_counts, "driver": trace + rng.normal(0, noise["gripper_rad"], trace.size), "hold": hold}
    return ArmMeasured(static, dynamic, grip)


# --- identification --------------------------------------------------------------------------------------------------------------

def fit_kinematics(arm: ArmModel, poses: list[dict], *, tcp: bool) -> dict:
    """Joint zero offsets (and the TCP in the gripper body's frame) by least squares of FK(q_encoder + offset) on the tracker."""
    import mujoco  # noqa: PLC0415
    from scipy.optimize import least_squares  # noqa: PLC0415
    from scipy.spatial.transform import Rotation  # noqa: PLC0415

    model = arm.model
    data = mujoco.MjData(model)
    g = arm.gripper
    tcp0 = model.site_pos[g["pinch"]].copy() if tcp else None
    scale_p, scale_r, scale_t = 1e-4, 5e-4, 1e-4  # residuals in units of a typical tracker noise (only the conditioning depends on them)

    def residual(x):
        out = []
        for row in poses:
            data.qpos[arm.qpos] = row["q"] + x[:6]
            mujoco.mj_kinematics(model, data)
            p, R = site_pose(model, data, arm.flange_site)
            out.extend((p - row["p"]) / scale_p)
            out.extend(Rotation.from_matrix(row["R"] @ R.T).as_rotvec() / scale_r)
            if tcp:
                body_p, body_R = data.xpos[g["body"]], data.xmat[g["body"]].reshape(3, 3)
                out.extend((body_p + body_R @ x[6:9] - row["tcp"]) / scale_t)
        return np.asarray(out)

    x0 = np.zeros(6) if not tcp else np.concatenate([np.zeros(6), tcp0])
    fit = least_squares(residual, x0, method="lm", x_scale="jac")
    dof = max(1, fit.fun.size - x0.size)
    cov = np.linalg.pinv(fit.jac.T @ fit.jac) * float(fit.fun @ fit.fun) / dof
    half = 1.96 * np.sqrt(np.diag(cov))
    out = {f"{j}.zero_offset_rad": (float(fit.x[i]), (float(fit.x[i] - half[i]), float(fit.x[i] + half[i]))) for i, j in enumerate(JOINTS)}
    if tcp:
        for i, axis in enumerate("xyz"):
            v = float(fit.x[6 + i])
            out[f"tool.tcp_{axis}_m"] = (v, (v - half[6 + i], v + half[6 + i]))
    out["_rms_position_mm"] = float(np.sqrt(np.mean((fit.fun.reshape(len(poses), -1)[:, :3] * scale_p) ** 2)) * 1e3)
    return out


def savgol_derivatives(q: np.ndarray, window: int = 41, order: int = 3) -> tuple[np.ndarray, np.ndarray]:
    from scipy.signal import savgol_filter  # noqa: PLC0415

    return (savgol_filter(q, window, order, deriv=1, delta=DT, axis=0), savgol_filter(q, window, order, deriv=2, delta=DT, axis=0))


def rigid_inverse(arm: ArmModel, q: np.ndarray, qd: np.ndarray, qdd: np.ndarray, *, tool_mass=None, tool_com_z=None, stride: int = 2) -> np.ndarray:
    """MuJoCo's rigid-body inverse dynamics on the arm's DOFs, with armature, damping, friction, limits and equalities off (the
    gripper's own joints held at rest in its open configuration)."""
    import mujoco  # noqa: PLC0415

    model = arm.model
    saved = (model.dof_armature.copy(), model.dof_damping.copy(), model.dof_frictionloss.copy(), model.opt.disableflags)
    g = arm.gripper
    saved_tool = (float(model.body_mass[g["body"]]), float(model.body_ipos[g["body"], 2])) if g else None
    try:
        model.dof_armature[arm.dof] = 0.0
        model.dof_damping[arm.dof] = 0.0
        model.dof_frictionloss[arm.dof] = 0.0
        model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_EQUALITY | mujoco.mjtDisableBit.mjDSBL_LIMIT | mujoco.mjtDisableBit.mjDSBL_FRICTIONLOSS
                                      | mujoco.mjtDisableBit.mjDSBL_CONTACT)
        if g and tool_mass is not None:
            model.body_mass[g["body"]] = tool_mass
        if g and tool_com_z is not None:
            model.body_ipos[g["body"], 2] = tool_com_z
        data = mujoco.MjData(model)
        rest = data.qpos.copy()
        out = np.zeros((len(range(0, q.shape[0], stride)), 6))
        for row, k in enumerate(range(0, q.shape[0], stride)):
            data.qpos[:] = rest
            data.qvel[:] = 0.0
            data.qacc[:] = 0.0
            data.qpos[arm.qpos], data.qvel[arm.dof], data.qacc[arm.dof] = q[k], qd[k], qdd[k]
            mujoco.mj_inverse(model, data)
            out[row] = data.qfrc_inverse[arm.dof]
        return out
    finally:
        model.dof_armature[:], model.dof_damping[:], model.dof_frictionloss[:] = saved[0], saved[1], saved[2]
        model.opt.disableflags = saved[3]
        if g:
            model.body_mass[g["body"]], model.body_ipos[g["body"], 2] = saved_tool


def fit_dynamics(arm: ArmModel, excitations: list[dict], offsets: np.ndarray, *, tool: dict | None = None, stride: int = 2) -> dict:
    """Per joint armature, damping and Coulomb (and the tool's mass and centre-of-mass height) by weighted least squares of the
    measured torque on MuJoCo's rigid inverse dynamics; weights from each joint's residual of a first pass; intervals from the
    weighted fit's covariance."""
    from scipy.signal import savgol_filter  # noqa: PLC0415

    # WHY one smoother on every channel (bam_rack_twin.identify.filtered's rule): tau = J qdd survives a filter only if both sides pass
    # through the same one; the sign is taken before the smoother and smoothed like the torque.
    # WHY qdd from the measured speed's step difference (measured 2026-11-05: a Savitzky-Golay DERIVATIVE of q beside the SMOOTHED
    # torque read wrist 3's inertia +13 %; with the simulator's exact accelerations the same regression returns every joint to four
    # digits), and WHY the inverse dynamics on the RAW samples, smoothed after: the rigid-body torque is nonlinear in q and qd, so
    # L[ID(x)] is what L[tau] equals, not ID(L[x]) (that read the elbow's inertia -12 % under a gripper).
    lengths = [e["q"].shape[0] for e in excitations]
    cuts = np.cumsum(lengths)[:-1]
    smooth = lambda x: np.concatenate([savgol_filter(part, SMOOTHER, 3, axis=0) for part in np.split(x, cuts)])  # noqa: E731
    q_raw = np.concatenate([e["q"] + offsets for e in excitations])
    qd_raw = np.concatenate([e["qd"] for e in excitations])
    qdd_raw = np.concatenate([np.vstack([np.zeros((1, 6)), np.diff(e["qd"], axis=0)]) / DT for e in excitations])
    tau = smooth(np.concatenate([e["tau"] for e in excitations]))
    qd, qdd, sgn = smooth(qd_raw), smooth(qdd_raw), smooth(np.sign(qd_raw))
    # WHY rows a half window from any stuck sample are dropped too: inside the smoother's window a stuck joint's friction (anywhere in
    # [-F, F]) leaks into the moving rows' smoothed torque, which no sgn(qd) column describes
    stuck = (np.abs(qd_raw) < MOVING).astype(float)
    near_stuck = np.apply_along_axis(lambda c: np.convolve(c, np.ones(SMOOTHER), mode="same"), 0, stuck) > 0
    keep = np.concatenate([_interior(n) for n in lengths])
    samples = np.nonzero(keep)[0][::stride]
    qd, qdd, sgn, tau, near_stuck = qd[samples], qdd[samples], sgn[samples], tau[samples], near_stuck[samples]

    def inverse(mass_, com_):
        return smooth(rigid_inverse(arm, q_raw, qd_raw, qdd_raw, tool_mass=mass_, tool_com_z=com_, stride=1))[samples]

    mass = tool["mass_kg"] if tool else None
    com = tool["com_z_m"] if tool else None
    n_tool = 2 if tool else 0
    weights = np.ones(6)
    for _ in range(3 if tool else 1):
        base = inverse(mass, com)
        columns_tool = []
        if tool:
            dm, dc = 0.05, 0.002
            columns_tool = [(inverse(mass + dm, com) - base) / dm, (inverse(mass, com + dc) - base) / dc]
        rows, rhs, row_w = [], [], []
        for i in range(6):
            moving = (np.abs(qd[:, i]) > MOVING) & ~near_stuck[:, i]
            block = np.zeros((int(moving.sum()), 18 + n_tool))
            block[:, 3 * i] = qdd[moving, i]
            block[:, 3 * i + 1] = qd[moving, i]
            block[:, 3 * i + 2] = sgn[moving, i]
            for c, col in enumerate(columns_tool):
                block[:, 18 + c] = col[moving, i]
            rows.append(block)
            rhs.append(tau[moving, i] - base[moving, i])
            row_w.append(np.full(int(moving.sum()), 1.0 / weights[i]))
        A, b, w = np.vstack(rows), np.concatenate(rhs), np.concatenate(row_w)
        x, *_ = np.linalg.lstsq(A * w[:, None], b * w, rcond=None)
        residual = b - A @ x
        offsets_rows = np.cumsum([0] + [r.shape[0] for r in rows])
        weights = np.array([max(1e-6, float(np.std(residual[offsets_rows[i]:offsets_rows[i + 1]]))) for i in range(6)])
        if tool:
            mass, com = mass + x[18], com + x[19]
    # 95 % intervals by a moving-block bootstrap at the last linearisation (0.5 s blocks of time, every joint's rows of a block kept
    # together). WHY not the least-squares covariance: the smoothed torque noise is correlated over the smoother's window, so a
    # white-noise covariance understated the scatter several times (measured 2026-11-05: an elbow 4.5 of its "sigma" off was one
    # noise seed's draw; four other seeds put it on the truth).
    w = np.concatenate([np.full(r.shape[0], 1.0 / weights[i]) for i, r in enumerate(rows)])
    time_of = np.concatenate([np.nonzero((np.abs(qd[:, i]) > MOVING) & ~near_stuck[:, i])[0] for i in range(6)])
    block = int(round(0.5 / (DT * stride)))
    blocks = time_of // block
    members = [np.nonzero(blocks == b_)[0] for b_ in np.unique(blocks)]
    rng = np.random.default_rng(20261105)
    boot = []
    for _ in range(BOOTSTRAP):
        pick = np.concatenate([members[i] for i in rng.integers(0, len(members), len(members))])
        xb, *_ = np.linalg.lstsq(A[pick] * w[pick, None], b[pick] * w[pick], rcond=None)
        boot.append(xb)
    boot = np.asarray(boot)
    shift = np.zeros(A.shape[1]) if not tool else np.concatenate([np.zeros(18), [mass - x[18], com - x[19]]])
    lo, hi = np.percentile(boot + shift, (2.5, 97.5), axis=0)
    out = {}
    for i, j in enumerate(JOINTS):
        for k, name in enumerate(("armature_kg_m2", "damping_nm_s_rad", "frictionloss_nm")):
            c = 3 * i + k
            out[f"{j}.{name}"] = (float(x[c]), (float(lo[c]), float(hi[c])))
    if tool:
        out["tool.mass_kg"] = (float(mass), (float(lo[18]), float(hi[18])))
        out["tool.com_z_m"] = (float(com), (float(lo[19]), float(hi[19])))
    out["_rows"] = int(A.shape[0])
    out["_residual_nm"] = weights.tolist()
    return out


def _interior(n: int, trim: int = 300) -> np.ndarray:
    keep = np.zeros(n, bool)
    keep[trim:n - trim] = True
    return keep


def fit_gripper(arm: ArmModel, grip: dict, nominal: dict, offsets: np.ndarray) -> dict:
    """The 2F-85 drive's force per count and damping: least squares of the simulated driver angle on the measured one."""
    from scipy.optimize import least_squares  # noqa: PLC0415

    def residual(x):
        arm.set_values({"gripper.actuator_gain": x[0], "gripper.damping": x[1]})
        return (run_gripper(arm, grip["counts"], grip["hold"], offsets) - grip["driver"]) / 2e-4

    x0 = np.array([nominal["gripper.actuator_gain"], nominal["gripper.damping"]])
    fit = least_squares(residual, x0, x_scale=x0, diff_step=1e-3, bounds=([1e-3, 0.1], [2.0, 200.0]))
    dof = max(1, fit.fun.size - 2)
    cov = np.linalg.pinv(fit.jac.T @ fit.jac) * float(fit.fun @ fit.fun) / dof
    half = 1.96 * np.sqrt(np.diag(cov))
    arm.set_values({"gripper.actuator_gain": fit.x[0], "gripper.damping": fit.x[1]})
    return {"gripper.actuator_gain": (float(fit.x[0]), (float(fit.x[0] - half[0]), float(fit.x[0] + half[0]))),
            "gripper.damping": (float(fit.x[1]), (float(fit.x[1] - half[1]), float(fit.x[1] + half[1]))), "_evaluations": int(fit.nfev)}


# --- held-out score ------------------------------------------------------------------------------------------------------------

def predict_static(arm: ArmModel, values: dict, commands: np.ndarray, *, tcp: bool) -> np.ndarray:
    """The twin's tool (flange, or TCP) position for each commanded pose: settle its own servo loop, then FK."""
    import mujoco  # noqa: PLC0415

    arm.set_values(values)
    offsets = arm.offsets(values)
    data = mujoco.MjData(arm.model)
    out = []
    for command in commands:
        settle(arm, data, command + offsets, command + offsets)
        out.append(data.site_xpos[arm.gripper["pinch"]].copy() if tcp else data.site_xpos[arm.flange_site].copy())
    return np.array(out)


def predict_torque(arm: ArmModel, values: dict, excitations: list[dict]) -> list[np.ndarray]:
    arm.set_values(values)
    offsets = arm.offsets(values)
    return [run_excitation(arm, e["command"], offsets)[2] for e in excitations]


# --- one example, end to end (the two UR5e pipelines are this with gripper off or on) -----------------------------------------

@dataclass
class Measured:
    train: ArmMeasured
    held_out: ArmMeasured


def measure_example(description, plan_: ArmPlan, truth: dict, noise: dict, seed: int, *, gripper: bool) -> Measured:
    model = ArmModel.build(description)
    train = measure(model, truth, noise, seed, plan_.poses_train, plan_.trajectories("train"),
                    plan_.gripper_train if gripper else None, plan_.hold, label="train")
    held = measure(model, truth, noise, seed, plan_.poses_held_out, plan_.trajectories("held_out"),
                   plan_.gripper_held_out if gripper else None, plan_.hold, label="held_out")
    return Measured(train, held)


@dataclass
class ArmFit:
    values: dict
    ci95: dict
    methods: dict
    stats: dict


def identify_example(description, train: ArmMeasured, *, gripper: bool) -> ArmFit:
    """Kinematics first, then the joint dynamics (and the tool) at the fitted zeros, then the gripper's drive; each step reads the
    train measurements and the description's nominal values only."""
    nominal = {key: entry.value for key, entry in description.nominal.items()}
    model = ArmModel.build(description)
    kin = fit_kinematics(model, train.poses, tcp=gripper)
    offsets = np.array([kin[f"{j}.zero_offset_rad"][0] for j in JOINTS])
    tool = {"mass_kg": nominal["tool.mass_kg"], "com_z_m": nominal["tool.com_z_m"]} if gripper else None
    dyn = fit_dynamics(model, train.excitations, offsets, tool=tool)
    found = {**{k: v for k, v in kin.items() if not k.startswith("_")}, **{k: v for k, v in dyn.items() if not k.startswith("_")}}
    methods = {"kinematics": f"least squares of FK(q_encoder + offset) on the tracker's flange pose{' and the TCP marker' if gripper else ''} at "
                             f"{len(train.poses)} static poses (Levenberg-Marquardt; 95 % from the Jacobian)",
               "dynamics": f"weighted least squares of joint torque - mj_inverse(rigid) on qdd, qd, sgn(qd) per joint{' + the tool mass and centre of mass' if gripper else ''}, "
                           f"{dyn['_rows']:,} moving rows of {len(train.excitations)} trajectories (the Fourier excitations and the coverage sweep; 95 % from a moving-block bootstrap)"}
    stats = {"kinematic_rms_mm": kin["_rms_position_mm"], "dynamic_rows": dyn["_rows"], "torque_residual_nm": dyn["_residual_nm"]}
    if gripper:
        model.set_values({k: v[0] for k, v in found.items()})
        grip = fit_gripper(model, train.gripper, nominal, offsets)
        found.update({k: v for k, v in grip.items() if not k.startswith("_")})
        methods["gripper"] = f"least squares of the simulated driver angle on the measured one ({grip['_evaluations']} simulations of the {train.gripper['counts'].size * DT:.1f} s train command)"
    values = {k: v[0] for k, v in found.items()}
    return ArmFit(values, {k: v[1] for k, v in found.items()}, methods, stats)


def score_example(description, plan_: ArmPlan, fit: ArmFit, measured: Measured, *, gripper: bool) -> dict:
    """Each rung of the arm's ladder predicts the held-out measurements from the held-out commands: the tool (TCP) position at the
    static poses, the joint torque along the excitations, the finger angle along the gripper's held-out command."""
    nominal = {key: entry.value for key, entry in description.nominal.items()}
    tcp_keys = ("tool.tcp_x_m", "tool.tcp_y_m", "tool.tcp_z_m")
    kinematic = {k: v for k, v in fit.values.items() if k.endswith("zero_offset_rad") or k in tcp_keys}
    # model labels, not rung keys: the fitted model spans two cards (arm_6dof M1 for the zeros, each joint's servo M2 for its dynamics)
    labels = {"nominal": nominal, "kinematics": {**nominal, **kinematic}, "fitted": {**nominal, **fit.values}}
    held = measured.held_out
    measured_tool = np.array([row["tcp"] if gripper else row["p"] for row in held.poses])
    out = {"models": {}}
    for label, values in labels.items():
        model = ArmModel.build(description)
        pred = predict_static(model, values, plan_.poses_held_out, tcp=gripper)
        tool_mm = 1e3 * float(np.sqrt(np.mean(np.sum((pred - measured_tool) ** 2, axis=1))))
        torques = predict_torque(model, values, held.excitations)
        torque = float(np.sqrt(np.mean(np.concatenate([(p - e["tau"]).ravel() for p, e in zip(torques, held.excitations)]) ** 2)))
        row = {"tool_mm": tool_mm, "torque_nm": torque}
        if gripper:
            trace = run_gripper(model, held.gripper["counts"], held.gripper["hold"], model.offsets(values))
            row["finger_mrad"] = 1e3 * float(np.sqrt(np.mean((trace - held.gripper["driver"]) ** 2)))
        out["models"][label] = row
    return out


def assemble_example(example: str, description, plan_: ArmPlan, fit: ArmFit, scores: dict, truth: dict, *, gripper: bool) -> dict:
    from sysid import cards, result  # noqa: PLC0415

    recovered = {}
    for key, value in fit.values.items():
        step = "kinematics" if key.endswith("zero_offset_rad") or key.startswith("tool.tcp") else "gripper" if key.startswith("gripper.") else "dynamics"
        recovered[key] = {"value": value, "ci95": fit.ci95.get(key), "rung": step, "method": fit.methods[step]}
    parameters = result.parameter_rows(example, description, truth, recovered)
    m = scores["models"]
    tool_id = "held_out_tcp_position_mm" if gripper else "held_out_tool_position_mm"
    metrics = [result.metric(example, tool_id, "TCP position, twin vs tracker (held-out poses)" if gripper else "Flange position, twin vs tracker (held-out poses)",
                             "mm", m["nominal"]["tool_mm"], m["fitted"]["tool_mm"], after_model="fitted",
                             note=f"{len(plan_.poses_held_out)} held-out poses; the twin settles its own servo loop at each command, then FK"),
               result.metric(example, "held_out_torque_rms_nm", "Joint torque, twin vs real (held-out excitations)", "N·m", m["nominal"]["torque_nm"], m["fitted"]["torque_nm"],
                             after_model="fitted", note=f"{len(plan_.excitations_held_out)} held-out Fourier excitations, all six joints pooled")]
    if gripper:
        metrics.append(result.metric(example, "held_out_finger_rms_mrad", "Finger drive angle, twin vs real (held-out command)", "mrad",
                                     m["nominal"]["finger_mrad"], m["fitted"]["finger_mrad"], after_model="fitted"))
    models = [{"model": label, "what": {"nominal": "the description as given", "kinematics": "+ the joint zeros (arm_6dof M1)",
                                        "fitted": "+ every joint servo's M2 dynamics" + (", the tool (arm_6dof M3) and the TCP and drive (arm_6dof_gripper M0-M1)" if gripper else "")}[label],
               **row} for label, row in m.items()]
    m_desc = description.manifest["model"]
    return {
        "title": description.manifest["title"], "subtitle": description.manifest.get("subtitle", ""), "summary": description.manifest.get("summary", ""),
        "description": {"manifest": f"sysid/examples/{example}/description.json", "model": {k: m_desc.get(k) for k in ("format", "path", "source")},
                        "attach": m_desc.get("attach", []), "sensors": description.manifest.get("sensors", []), "known": description.known,
                        "components": len(description.components)},
        "tree": description.tree(),
        "schedule": {split: {"poses": len(getattr(plan_, f"poses_{split}")), "excitations": len(getattr(plan_, f"excitations_{split}")),
                             "excitation_s": round(sum(e.shape[0] for e in getattr(plan_, f"excitations_{split}")) * DT, 1),
                             "sweep_trajectories": len(getattr(plan_, f"sweep_{split}")), "sweep_s": plan_.coverage[split]["sweep_s"],
                             "seconds": plan_.coverage[split]["motion_s"], "settle_s": plan_.coverage[split]["settle_s"]} for split in ("train", "held_out")}
                    | {
                     "gripper": {"train_s": round(plan_.gripper_train.size * DT, 1), "held_out_s": round(plan_.gripper_held_out.size * DT, 1)} if gripper else None,
                     "excitation": description.schedule.get("excitation"), "sweep": plan_.sweep or None, "coverage": plan_.coverage},
        "parameters": parameters, "metrics": metrics, "models": models, "card_ladders": cards.card_ladders(example, fit.values),
        "selected_rung": None, "fit": fit.stats,
        "notes": ["The tracker sees the flange through a calibrated external camera: its frame is the arm's base frame (hand-eye is the dual-arm cell's job).",
                  "Contacts are off: no example here calibrates contact (the gripper card's grip force and contact friction stay unidentified)."]
                 + (["The 2F-85's grip force map and contact friction (arm_6dof_gripper's parameters) need a force gauge and pull-out tests; not simulated."] if gripper else []),
    }
