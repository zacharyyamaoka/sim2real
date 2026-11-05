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
    s = description.schedule
    rng = rng_for(s["seed"], "plan")
    lo, hi = np.array(POSE_RANGES).T
    poses = rng.uniform(lo, hi, size=(s["poses_train"] + s["poses_held_out"], len(JOINTS)))
    excitations = [fourier_excitation(rng_for(s["seed"], "excitation", k)) for k in range(s["excitations_train"] + s["excitations_held_out"])]
    p = ArmPlan(poses[: s["poses_train"]], poses[s["poses_train"]:], excitations[: s["excitations_train"]], excitations[s["excitations_train"]:])
    if gripper:
        p.gripper_train = np.concatenate([gripper_steps((0, 64, 128, 192, 255, 192, 128, 64, 0, 255)), gripper_steps((0, 255, 0, 128, 0))])
        p.gripper_held_out = gripper_steps((0, 40, 100, 170, 230, 100, 0))
    p.coverage = arm_coverage(p)
    return p


def arm_coverage(p: ArmPlan) -> dict:
    from type_cards import coverage as cov  # noqa: PLC0415

    def points(poses, excitations):
        pts = [{"joint space": tuple(q)} for q in poses]
        for e in excitations:
            pts.extend({"joint space": tuple(q)} for q in e[::25])
        return pts

    out = {}
    for split, (poses, exc) in {"train": (p.poses_train, p.excitations_train), "held_out": (p.poses_held_out, p.excitations_held_out)}.items():
        c = cov.arm_coverage(points(poses, exc))
        out[split] = {"pct": c.pct, "visited": c.visited, "reachable": c.reachable, "samples": c.samples, "axes": c.axes, "unplanned": list(c.unplanned)}
    out["function"] = "type_cards.coverage.arm_coverage (4 cells per joint inside the limits: the 4096-cell joint cube)"
    out["rule"] = "share of the joint cube's cells the static poses and the excitations (every 50 ms) visit; tool voxels need FK (a marginal, not planned here)"
    return out


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
    train = measure(model, truth, noise, seed, plan_.poses_train, plan_.excitations_train,
                    plan_.gripper_train if gripper else None, plan_.hold, label="train")
    held = measure(model, truth, noise, seed, plan_.poses_held_out, plan_.excitations_held_out,
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
                           f"{dyn['_rows']:,} moving rows of {len(train.excitations)} excitations (95 % from the covariance)"}
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
    labels = {"M0": nominal, "M1": {**nominal, **kinematic}, "M2": {**nominal, **fit.values}}
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
        rung = "M1" if key.endswith("zero_offset_rad") or key.startswith("tool.tcp") else "M2"
        if key.startswith("gripper."):
            rung = "M1 (gripper)"
        elif key.startswith("tool."):
            rung = "M1 (tool)"
        recovered[key] = {"value": value, "ci95": fit.ci95.get(key), "rung": rung,
                          "method": fit.methods["kinematics" if rung == "M1" or key.startswith("tool.tcp") else "gripper" if key.startswith("gripper.") else "dynamics"]}
    parameters = result.parameter_rows(example, description, truth, recovered)
    m = scores["models"]
    tool_id = "held_out_tcp_position_mm" if gripper else "held_out_tool_position_mm"
    metrics = [result.metric(example, tool_id, "TCP position, twin vs tracker (held-out poses)" if gripper else "Flange position, twin vs tracker (held-out poses)",
                             "mm", m["M0"]["tool_mm"], m["M2"]["tool_mm"], after_model="M2",
                             note=f"{len(plan_.poses_held_out)} held-out poses; the twin settles its own servo loop at each command, then FK"),
               result.metric(example, "held_out_torque_rms_nm", "Joint torque, twin vs real (held-out excitations)", "N·m", m["M0"]["torque_nm"], m["M2"]["torque_nm"],
                             after_model="M2", note=f"{len(plan_.excitations_held_out)} held-out Fourier excitations, all six joints pooled")]
    if gripper:
        metrics.append(result.metric(example, "held_out_finger_rms_mrad", "Finger drive angle, twin vs real (held-out command)", "mrad",
                                     m["M0"]["finger_mrad"], m["M2"]["finger_mrad"], after_model="M2 + gripper M1"))
    ladder, source = cards.ladder("arm_6dof")
    rungs = []
    for r in ladder:
        row = cards.rung_row(r)
        if r.key in m:
            row.update({"tool_mm": m[r.key]["tool_mm"], "torque_nm": m[r.key]["torque_nm"]})
        rungs.append(row)
    extra = []
    if gripper:
        for card_id in ("tool", "gripper"):
            lad, _ = cards.ladder(card_id)
            extra.extend({**cards.rung_row(r), "card": card_id} for r in lad)
    m_desc = description.manifest["model"]
    return {
        "title": description.manifest["title"], "subtitle": description.manifest.get("subtitle", ""), "summary": description.manifest.get("summary", ""),
        "description": {"manifest": f"sysid/examples/{example}/description.json", "model": {k: m_desc.get(k) for k in ("format", "path", "source")},
                        "attach": m_desc.get("attach", []), "sensors": description.manifest.get("sensors", []), "known": description.known,
                        "components": len(description.components)},
        "tree": description.tree(),
        "schedule": {"train": {"poses": len(plan_.poses_train), "excitations": len(plan_.excitations_train), "seconds": round(sum(e.shape[0] for e in plan_.excitations_train) * DT, 1)},
                     "held_out": {"poses": len(plan_.poses_held_out), "excitations": len(plan_.excitations_held_out), "seconds": round(sum(e.shape[0] for e in plan_.excitations_held_out) * DT, 1)},
                     "gripper": {"train_s": round(plan_.gripper_train.size * DT, 1), "held_out_s": round(plan_.gripper_held_out.size * DT, 1)} if gripper else None,
                     "excitation": description.schedule.get("excitation"), "coverage": plan_.coverage},
        "parameters": parameters, "metrics": metrics, "rungs": rungs, "ladder_source": source, "other_ladders": extra,
        "selected_rung": None, "fit": fit.stats,
        "notes": ["The tracker sees the flange through a calibrated external camera: its frame is the arm's base frame (hand-eye is the dual-arm cell's job).",
                  "Contacts are off: no example here calibrates contact (the gripper card's grip force and contact friction stay unidentified)."]
                 + (["The 2F-85's grip force map and contact friction (arm_6dof_gripper's parameters) need a force gauge and pull-out tests; not simulated."] if gripper else []),
    }
