"""The nominal world: the twin of ANY exported robot description, its sim plant the description's own MJCF at the description's own
nominal Values (step 7 of Zach's 2026-11-19 pipeline, "RobotDescription -> RobotTwin -> .calibrate()", for any exported robot).

    twin = sim2real.RobotTwin.from_robot_description(rd)                   # rd.record None (a CAD export names no unit yet): nominal world
    twin = sim2real.RobotTwin.from_robot_description(rd, world="nominal")  # the same, even when rd names a unit no sysid world was built for
    sim2real.calibration.plan(twin).summary()                              # 1. servo.dynamics_regression: every servo joint, typed tapes
    fitted = twin.calibrate(on="sim", move_truth={"can11.gravity_nm": 5.2}) # the world plays the moved value; the fit recovers it, sealed

What the world is. Each integrated_servo instance bound to an MJCF hinge (binds["joint"]) is a joint the world drives, through the servo's
own board loop: a PD on the joint (kp, kd: the description's kp_nm_rad / kd_nm_s_rad when it states them, else a 5 Hz, damping-ratio-1
loop on the joint's nominal inertia), its command a typed robot_msgs JointTrajectory (a multi-sine tape per run), at 1 kHz with the torque
held between ticks. The description's Values reach the MJCF where MuJoCo has the attribute:

    armature_kg_m2     the joint's armature (MuJoCo's reflected rotor inertia; sysid's ur5e manifest maps it the same, mjcf:joint:<j>:armature)
    damping_nm_s_rad   the joint's damping
    frictionloss_nm    the joint's frictionloss
    a lone hinge's lumped load (the pendulum's convention, bam_rack_twin TwinParameters): gravity_nm and gravity_bottom_rad place the link's
                       centre of mass (its mass kept, G = m g r at the stated bottom), and armature_kg_m2 is then the TOTAL inertia about the
                       hinge, the link's own share subtracted into the joint's armature (CAN 11 at nominal: 0.0610 + 0.0610, the twin of
                       record's own split)

Every other parameter is carried and said ("not identified", with why), never dropped. The world's hidden truth is the description's own
nominal values (RigRunner(world=...)); move_truth moves it for one run, and the rows stay held to the nominal (the seam's mutation test).

WHY sim2real.rig.RigRunner and no new runner (the brief: reuse the machinery that already plays routines on an MJCF): the one-click seam
already plays a schedule against a hidden truth with every guard (the seal, the ruler, held-out eval, rounds, data_, callbacks), and it
takes its world as an argument. What a description lacks is a rig.py, so this module IS that rig for any description: a RigBackend
(parameters, noise, routines, held_out, measure, predict, score) built from the description instead of a hand-written file.

WHY output error through the twin (predict) and not an equation-error regression: the world and the fit play the very same simulator, so
the only thing between them is the drawn noise, and MuJoCo's soft frictionloss constraint, which a sign(qd) regressor only approximates,
is fitted exactly. The fit is scipy's least_squares over the identified keys, residuals the reported torque and position against the
twin's replay of each run's own command, scaled by the noise model; its 95 % interval is the Gauss-Newton covariance at the optimum.

WHY one worker always (the rack host rule, 2026-11-14: the arm is real-time while powered): the replays run one after another in this
process; `workers` is accepted for the seam and never opens a pool.

The noise is CAN 11's measured block (sysid/examples/pendulum_can11/world.json "noise") as a stand-in until this unit's own is measured;
every term says so in NoiseModel.sources.

Layer: like twin.py and rig.py, right of every folder (tests/test_layers.py); imports mujoco, numpy and scipy lazily.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import rig as seam

ROUTINE = "servo.dynamics_regression"
BOARD_HZ = 1000.0          # the board loop's tick: PD torque computed and held per tick
LOOP_HZ = 5.0              # the PD bandwidth when the description states no gains
LOOP_ZETA = 1.0
TRAIN_SECONDS = 8.0
RAMP_S = 0.5               # each tape fades in and out over this, so every run starts and ends at rest on its start pose
RESIDUAL_EVERY = 5         # one residual per this many board ticks (200 Hz): what the fit compares
TOL_REL = 0.05             # proposed: 5 % of the nominal, the nominal world's own rule until the routine's tolerance is stated
TOL_ANGLE_RAD = 0.005      # proposed: 0.29 deg for an angle
TOL_FLOOR = {"kg·m²": 1e-6, "N·m": 2e-3, "N·m·s/rad": 2e-3}   # proposed: the smallest tolerance per unit (a nominal of 0 still has one)
SCALE_FLOOR = {"kg·m²": 1e-5, "N·m": 1e-2, "N·m·s/rad": 1e-3, "rad": 0.1}  # the fit's finite-difference size per unit
MAX_REPLAYS = 150         # the fit's cap on least_squares steps (the UR wrist's nine keys took 43-52 on 2026-11-19; 40 stopped short)
NONNEG = ("armature_kg_m2", "damping_nm_s_rad", "frictionloss_nm", "gravity_nm")
JOINT_FIELDS = {"armature_kg_m2": "dof_armature", "damping_nm_s_rad": "dof_damping", "frictionloss_nm": "dof_frictionloss"}
LUMPED = ("gravity_nm", "gravity_bottom_rad")
WORLD_NOISE = "sysid/examples/pendulum_can11/world.json noise block (CAN 11's measured terms), a stand-in until this unit's noise is measured"


def nominal_twin(cls, instances, rd, *, models=None, workers: int = 6):
    """The RobotTwin of `rd` on a nominal world (twin.RobotTwin.from_robot_description's way when no sysid world binds). `instances` are the
    twin's typed instances, already checked by from_robot_description. Refused by name: no model file, no integrated_servo bound to an MJCF
    hinge, models= (the rig's twin is its own model)."""
    from .twin import Description  # noqa: PLC0415

    model_file = getattr(rd, "model", None)
    if model_file is None or not Path(model_file).exists():
        raise ValueError(f"{rd.name}: a nominal world plays the description's own MJCF, and rd.model is {model_file!r} (no file there)")
    if models:
        raise NotImplementedError(f"{rd.name}'s nominal world is its own model (the description's MJCF at its Values); models= picks a rung "
                                  "on the pendulum tracer only")
    description = Description(str(rd.name), str(getattr(rd, "title", "") or rd.name), Path(model_file), tuple(instances),
                              str(getattr(rd, "source", "") or ""))
    rig = NominalRig(description)
    truth = rig.truth()
    twin = cls.__new__(cls)
    twin.description = description
    twin.models = {}
    # WHY the world a callable over the description's own values (RigRunner(world=)): the hidden truth IS the nominal; move_truth moves it
    twin.runner = seam.RigRunner(description, rig, workers=workers, world=lambda: {"truth": dict(truth)})
    twin.model = twin.runner.default_model()
    return twin


# --- the servos the world drives -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Servo:
    instance: str
    joint: str
    qpos: int                     # the joint's qpos address
    dof: int                      # its dof address
    lumped: bool                  # a lone hinge whose description states its gravity load
    kp: float
    kd: float
    q0: float                     # the start pose every tape runs about
    amplitude: float              # the tape's peak excursion from q0


@dataclass(frozen=True)
class Recording:
    """One run as the world reports it (or the twin replays it): board ticks t (s), per joint position q and speed qd (rad, rad/s) and the
    torque the board reports tau (N·m), joints in the rig's servo order; `spec` the run's own tape, which a replay plays again."""
    run: str
    t: Any
    q: Any
    qd: Any
    tau: Any
    spec: Mapping[str, Any]


def _tape(spec: Mapping[str, Any], t):
    """A run's reference (q, qd) at times t, per joint: q0 + w(t) sum A sin(2 pi f t + phi), w a sin^2 fade over RAMP_S at both ends."""
    import numpy as np  # noqa: PLC0415

    t = np.asarray(t, dtype=float)
    seconds, ramp = float(spec["seconds"]), float(spec["ramp_s"])
    up = np.clip(t / ramp, 0.0, 1.0)
    down = np.clip((seconds - t) / ramp, 0.0, 1.0)
    w = np.sin(0.5 * np.pi * up) ** 2 * np.sin(0.5 * np.pi * down) ** 2
    dw = (np.where((t > 0) & (t < ramp), np.pi / ramp * np.sin(np.pi * up) * np.sin(0.5 * np.pi * down) ** 2, 0.0)
          - np.where((t > seconds - ramp) & (t < seconds), np.pi / ramp * np.sin(np.pi * down) * np.sin(0.5 * np.pi * up) ** 2, 0.0))
    q, qd = [], []
    for q0, sines in zip(spec["q0"], spec["sines"]):
        s = sum(a * np.sin(2 * np.pi * f * t + p) for a, f, p in sines)
        ds = sum(a * 2 * np.pi * f * np.cos(2 * np.pi * f * t + p) for a, f, p in sines)
        q.append(q0 + w * s)
        qd.append(dw * s + w * ds)
    return np.stack(q, axis=1), np.stack(qd, axis=1)


class NominalRig:
    """A RigBackend (sim2real.rig) built from a description: its MJCF at given values, driven joint by joint by the servos' board loops.
    `model_at(values)` is the world's MjModel at those values (what measure and predict play)."""

    def __init__(self, description) -> None:
        import mujoco  # noqa: PLC0415

        self.description = description
        self.name = description.id
        self.model = f"nominal world: {Path(description.model).name} at the description's Values"
        self._base = mujoco.MjModel.from_xml_path(str(description.model))
        # WHY actuation off: the board loop is the servo's drive here (PD torque on the joint); an MJCF's own actuators (a position servo,
        # the pendulum scene's LuGre friction motor) are the model of record's drive and would act twice
        self._base.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
        self._substeps = max(1, round(1.0 / (BOARD_HZ * self._base.opt.timestep)))
        self._nominal = {k: (None if v is None else float(v)) for k, v in description.values().items()}
        self._params, self._identified, self._servos = self._table()
        if not self._servos:
            raise ValueError(f"{description.id}: a nominal world drives integrated_servo instances bound to an MJCF hinge (binds['joint']); "
                             f"this description has none ({Path(description.model).name})")
        self._train = self._runs("train", seeds=(1, 2, 3))
        self._held = self._runs("held_out", seeds=(101, 102))

    # ---- the table

    def _table(self):
        import mujoco  # noqa: PLC0415

        params, identified, servos = [], [], []
        model = self._base
        for i in self.description.instances:
            joint_name = i.binds.get("joint") if i.type == "integrated_servo" else None
            joint = None
            if joint_name is not None:
                try:
                    joint = model.joint(joint_name)
                except KeyError:
                    raise ValueError(f"{self.description.id}: {i.id} binds joint {joint_name!r}, which "
                                     f"{Path(self.description.model).name} has no joint of") from None
                if int(joint.type[0]) != int(mujoco.mjtJoint.mjJNT_HINGE):
                    joint = None
            lumped = joint is not None and self._lumped(i, joint)
            for name, value in i.parameters.items():
                key = f"{i.id}.{name}"
                unit = getattr(value, "unit", "") or ""
                why = self._why_not(i, name, value, joint, lumped, joint_name)
                tol = None if why else (("abs", TOL_ANGLE_RAD) if unit == "rad" else
                                        ("abs", max(TOL_REL * abs(float(value)), TOL_FLOOR.get(unit, 0.0))))
                params.append(seam.Parameter(key, unit, tol, "" if why else f"proposed: max({TOL_REL:.0%} of the nominal, the unit's floor), "
                                             "the nominal world's own rule (sim2real.nominal)", None if why else ROUTINE, why,
                                             "deg" if unit == "rad" else "", name))
                if not why:
                    identified.append(key)
            if joint is not None:
                servos.append((i, joint, lumped))
        # the joints the world drives, before their gains exist (model_at reads these; _servo needs model_at for the nominal inertia)
        self._drive = tuple(_Servo(i.id, joint.name, int(joint.qposadr[0]), int(joint.dofadr[0]), lumped, 0.0, 0.0, 0.0, 0.0)
                            for i, joint, lumped in servos)
        built = [self._servo(i, joint, lumped) for i, joint, lumped in servos]
        return {p.key: p for p in params}, tuple(identified), tuple(built)

    def _lumped(self, instance, joint) -> bool:
        """A lone hinge (the model's only dof, its body carrying no child body) whose description states its gravity load."""
        g = instance.parameters.get("gravity_nm")
        if g is None or self._base.nv != 1:
            return False
        body = int(joint.bodyid[0])
        return not any(int(self._base.body_parentid[b]) == body for b in range(self._base.nbody) if b != body)

    def _why_not(self, instance, name, value, joint, lumped, joint_name) -> str:
        if value is None:
            return "the description states no value for it: nothing for the nominal world to play"
        if instance.type != "integrated_servo":
            return (f"a {instance.type or instance.structural} instance: the nominal world drives the integrated_servo joints, and "
                    f"{name} reaches none of them")
        if joint_name is None:
            return "its servo binds no MJCF joint (binds['joint']): the nominal world cannot drive it"
        if joint is None:
            return f"its joint {joint_name!r} is not a hinge: the nominal world drives hinges only"
        if name in LUMPED:
            return ("" if lumped else
                    f"{name} is a lone hinge's lumped load; this joint is on a chain (or its link carries others), whose links' masses in "
                    "the MJCF carry its gravity")
        if name in JOINT_FIELDS:
            return ""
        return (f"the nominal world plays MuJoCo's joint armature, damping and frictionloss (and a lone hinge's gravity load); {name} is "
                "none of them")

    def _servo(self, instance, joint, lumped) -> _Servo:
        import mujoco  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        qadr, dadr = int(joint.qposadr[0]), int(joint.dofadr[0])
        if lumped and self._nominal.get(f"{instance.id}.gravity_bottom_rad") is not None:
            q0 = float(self._nominal[f"{instance.id}.gravity_bottom_rad"])
        else:
            q0 = float(self._base.qpos0[qadr])
        amplitude = 0.8
        if bool(joint.limited[0]):
            lo, hi = (float(x) for x in joint.range)
            margin = 0.1 * (hi - lo)
            q0 = min(max(q0, lo + margin), hi - margin)
            amplitude = min(amplitude, 0.6 * min(q0 - lo, hi - q0))
        kp = instance.parameters.get("kp_nm_rad")
        kd = instance.parameters.get("kd_nm_s_rad")
        if kp is None or kd is None:
            model = self.model_at({k: v for k, v in self._nominal.items() if v is not None})
            data = mujoco.MjData(model)
            data.qpos[:] = model.qpos0
            data.qpos[qadr] = q0
            mujoco.mj_forward(model, data)
            dense = np.zeros((model.nv, model.nv))
            mujoco.mj_fullM(model, data, dense)
            inertia = float(dense[dadr, dadr])
            omega = 2 * math.pi * LOOP_HZ
            # WHY from the joint's nominal inertia when the description states no gains: a loop that tracks the tape without saturating;
            # the gains are the board's config, so they stay fixed at whatever values the world or the twin plays
            kp, kd = (kp if kp is not None else inertia * omega ** 2), (kd if kd is not None else 2 * LOOP_ZETA * inertia * omega)
        return _Servo(instance.id, joint.name, qadr, dadr, lumped, float(kp), float(kd), q0, float(amplitude))

    def _runs(self, split: str, seeds: Sequence[int]) -> tuple[seam.Run, ...]:
        import numpy as np  # noqa: PLC0415
        from robot_msgs.trajectory import JointTrajectory  # noqa: PLC0415

        runs = []
        for seed in seeds:
            rng = np.random.default_rng([20261119, seed])
            sines = []
            for k, s in enumerate(self._servos):
                freqs = np.sort(rng.uniform(0.2, 1.6, size=3)) * (1.0 + 0.07 * k)
                share = np.array([0.5, 0.3, 0.2])
                sines.append([[float(s.amplitude * a), float(f), float(p)] for a, f, p in zip(share, freqs, rng.uniform(0, 2 * np.pi, 3))])
            spec = {"joints": [s.joint for s in self._servos], "q0": [s.q0 for s in self._servos], "seconds": TRAIN_SECONDS,
                    "ramp_s": RAMP_S, "sines": sines, "board_hz": BOARD_HZ}
            t = np.linspace(0.0, TRAIN_SECONDS, int(TRAIN_SECONDS * 100) + 1)
            q, qd = _tape(spec, t)
            command = JointTrajectory(t=t, joint_names=tuple(spec["joints"]), positions=q, velocities=qd)
            runs.append(seam.Run(f"{split}_{seed}", split, spec, command=command))
        return tuple(runs)

    # ---- the world at given values

    def model_at(self, values: Mapping[str, float]):
        """The MJCF at `values` (keys <instance>.<parameter>; an identified key it lacks keeps the description's nominal): each servo
        joint's armature, damping and frictionloss and, for a lone hinge, its lumped gravity load and total inertia."""
        import copy  # noqa: PLC0415

        import mujoco  # noqa: PLC0415

        model = copy.deepcopy(self._base)
        full = {**{k: v for k, v in self._nominal.items() if v is not None}, **{k: float(v) for k, v in values.items() if v is not None}}
        for s in self._drive:
            for name, attribute in JOINT_FIELDS.items():
                key = f"{s.instance}.{name}"
                if key in full and not (s.lumped and name == "armature_kg_m2"):
                    getattr(model, attribute)[s.dof] = full[key]
            if s.lumped:
                self._place_load(model, s, full)
        mujoco.mj_setConst(model, mujoco.MjData(model))
        return model

    def _place_load(self, model, s: _Servo, full: Mapping[str, float]) -> None:
        """A lone hinge's lumped load: the link's centre of mass placed so that holding it at q takes G sin(q - bottom) (its mass kept, its
        axial offset kept), then the joint's armature set so the total inertia about the hinge is the description's armature_kg_m2."""
        import mujoco  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        g_nm, bottom = full[f"{s.instance}.gravity_nm"], full.get(f"{s.instance}.gravity_bottom_rad", 0.0)
        body = int(model.jnt_bodyid[model.joint(s.joint).id])
        mass = float(model.body_mass[body])
        data = mujoco.MjData(model)
        data.qpos[:] = 0.0
        mujoco.mj_forward(model, data)
        jid = model.joint(s.joint).id
        axis, anchor = data.xaxis[jid].copy(), data.xanchor[jid].copy()
        gravity = np.asarray(model.opt.gravity, dtype=float)
        across = gravity - gravity.dot(axis) * axis
        if mass <= 0 or np.linalg.norm(across) == 0:
            raise ValueError(f"{s.instance}: a lumped gravity load needs a link with mass on a hinge not parallel to gravity")
        down = across / np.linalg.norm(across)
        radius = g_nm / (mass * np.linalg.norm(across))
        # at q = bottom the centre of mass hangs along gravity, so at q = 0 it sits rotated back by -bottom about the axis (Rodrigues)
        c, sn = math.cos(-bottom), math.sin(-bottom)
        hang = down * c + np.cross(axis, down) * sn + axis * axis.dot(down) * (1 - c)
        com = data.xipos[body]
        target = anchor + axis * (com - anchor).dot(axis) + radius * hang
        model.body_ipos[body] = data.xmat[body].reshape(3, 3).T @ (target - data.xpos[body])
        model.dof_armature[s.dof] = 0.0
        mujoco.mj_setConst(model, data)
        data = mujoco.MjData(model)
        data.qpos[:] = 0.0
        mujoco.mj_forward(model, data)
        dense = np.zeros((model.nv, model.nv))
        mujoco.mj_fullM(model, data, dense)
        total = full.get(f"{s.instance}.armature_kg_m2")
        if total is not None:
            link = float(dense[s.dof, s.dof])
            if total < link:
                raise ValueError(f"{s.instance}: the description's lumped inertia {total:.6g} kg·m² is below the link's own inertia about the "
                                 f"hinge, {link:.6g} kg·m², with its centre of mass where gravity_nm puts it")
            model.dof_armature[s.dof] = total - link

    # ---- read-only accessors (sim2real.preflight reads the world through these)

    @property
    def servos(self) -> tuple[_Servo, ...]:
        """The joints the world drives, in its order: instance, MJCF joint, addresses, the board loop's kp / kd, the tapes' start pose."""
        return self._servos

    @property
    def substeps(self) -> int:
        """MuJoCo steps per board tick (1 / (BOARD_HZ x the MJCF's timestep))."""
        return self._substeps

    def gains_source(self, instance: str) -> str:
        """Where the board loop's kp / kd for `instance` come from: the description's stated kp_nm_rad / kd_nm_s_rad, or the default loop."""
        params = self.description.instance(instance).parameters
        stated = [n for n in ("kp_nm_rad", "kd_nm_s_rad") if params.get(n) is not None]
        if len(stated) == 2:
            return f"the description's stated {instance}.kp_nm_rad / kd_nm_s_rad (the nominal world's board loop)"
        default = (f"the nominal world's default board loop ({LOOP_HZ:g} Hz, damping ratio {LOOP_ZETA:g} on the joint's nominal inertia; "
                   f"sim2real.nominal LOOP_HZ)")
        return default if not stated else f"{instance}.{stated[0]} as stated, the other from {default}"

    def tape_envelope(self) -> tuple[dict[str, float], ...]:
        """Per servo (the world's order), the envelope its train tapes span: position low / high (rad), peak |speed| (rad/s) and peak
        |acceleration| (rad/s², a finite difference at the board rate): the motion the fit identified the twin over."""
        import numpy as np  # noqa: PLC0415

        lows, highs, speeds, accels = [], [], [], []
        for run in self._train:
            t = np.arange(int(round(float(run.spec["seconds"]) * BOARD_HZ))) / BOARD_HZ
            q, qd = _tape(run.spec, t)
            lows.append(q.min(axis=0))
            highs.append(q.max(axis=0))
            speeds.append(np.abs(qd).max(axis=0))
            accels.append(np.abs(np.gradient(qd, t, axis=0)).max(axis=0))
        low, high, speed, accel = (np.min(lows, axis=0), np.max(highs, axis=0), np.max(speeds, axis=0), np.max(accels, axis=0))
        return tuple({"low_rad": float(low[k]), "high_rad": float(high[k]), "speed_rad_s": float(speed[k]), "accel_rad_s2": float(accel[k])}
                     for k in range(len(self._servos)))

    def truth(self) -> dict[str, float]:
        """The world's hidden truth: the description's nominal value of every identified key."""
        return {k: float(self._nominal[k]) for k in self._identified}

    # ---- the RigBackend

    def parameters(self) -> tuple[seam.Parameter, ...]:
        return tuple(self._params.values())

    def noise(self) -> seam.NoiseModel:
        return seam.NoiseModel(encoder_noise_rad=2e-5, velocity_noise_rad_s=0.002, torque_noise_nm=0.02,
                               sources={"encoder_noise_rad": WORLD_NOISE + " (encoder_rad)", "velocity_noise_rad_s": WORLD_NOISE + " (speed_rad_s)",
                                        "torque_noise_nm": WORLD_NOISE + " (torque_nm)", "others": "0: not modelled by the nominal world"})

    def routines(self) -> tuple:
        units = {k: self._params[k].unit for k in self._identified}
        return (_DynamicsRegression(self._identified, units, self._train),) if self._identified else ()

    def held_out(self, values: Mapping[str, float] | None = None) -> tuple[seam.Run, ...]:
        return self._held

    def measure(self, runs: Sequence[seam.Run], values: Mapping[str, float], noise: seam.NoiseModel, stream: str, *,
                workers: int = 1) -> dict[str, Recording]:
        model = self.model_at(values)
        return {run.id: self._play(model, run.id, run.spec, noise=noise, rng=noise.rng(stream, run.id)) for run in runs}

    def predict(self, measured: Mapping[str, Recording], values: Mapping[str, float], *, workers: int = 1) -> dict[str, Recording]:
        model = self.model_at(values)
        return {key: self._play(model, rec.run, rec.spec) for key, rec in measured.items()}

    def score(self, predicted: Mapping[str, Recording], measured: Mapping[str, Recording]) -> seam.Score:
        import numpy as np  # noqa: PLC0415

        runs, pooled = {}, {s.instance: [] for s in self._servos}
        for key, rec in measured.items():
            error = predicted[key].q - rec.q
            runs[key] = {s.instance: float(np.sqrt(np.mean(error[:, k] ** 2))) for k, s in enumerate(self._servos)}
            for k, s in enumerate(self._servos):
                pooled[s.instance].append(error[:, k])
        return seam.Score({j: float(np.sqrt(np.mean(np.concatenate(e) ** 2))) for j, e in pooled.items()}, runs)

    def _play(self, model, run_id: str, spec: Mapping[str, Any], *, noise: seam.NoiseModel | None = None, rng=None) -> Recording:
        """One tape through the board loops: per tick, each servo's PD on the (noisy, when `noise`) encoder reading, the torque held over the
        tick (plus the drawn disturbance), MuJoCo stepped `substeps` times. Noise-free without `noise`: the twin's replay."""
        import mujoco  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        data = mujoco.MjData(model)
        data.qpos[:] = model.qpos0
        qadr = np.array([s.qpos for s in self._servos])
        dadr = np.array([s.dof for s in self._servos])
        kp = np.array([s.kp for s in self._servos])
        kd = np.array([s.kd for s in self._servos])
        data.qpos[qadr] = spec["q0"]
        mujoco.mj_forward(model, data)
        ticks = int(round(float(spec["seconds"]) * BOARD_HZ))
        t = np.arange(ticks) / BOARD_HZ
        q_ref, qd_ref = _tape(spec, t)
        n = len(self._servos)
        q = np.empty((ticks, n))
        qd = np.empty((ticks, n))
        tau = np.empty((ticks, n))
        if noise is not None:
            e = noise.effective()
            enc = rng.normal(0.0, e["encoder_noise_rad"], (ticks, n)) if e["encoder_noise_rad"] else np.zeros((ticks, n))
            vel = rng.normal(0.0, e["velocity_noise_rad_s"], (ticks, n)) if e["velocity_noise_rad_s"] else np.zeros((ticks, n))
            rep = rng.normal(0.0, e["torque_noise_nm"], (ticks, n)) if e["torque_noise_nm"] else np.zeros((ticks, n))
            dist = rng.normal(0.0, e["torque_disturbance_nm"], (ticks, n)) if e["torque_disturbance_nm"] else np.zeros((ticks, n))
            quantum = e["encoder_quantum_rad"]
        else:
            enc = vel = rep = dist = None
            quantum = 0.0
        applied = data.qfrc_applied
        for k in range(ticks):
            qk = data.qpos[qadr]
            vk = data.qvel[dadr]
            if enc is not None:
                qk = qk + enc[k]
                if quantum:
                    qk = np.round(qk / quantum) * quantum
                vk = vk + vel[k]
            command = kp * (q_ref[k] - qk) + kd * (qd_ref[k] - vk)
            q[k], qd[k] = qk, vk
            tau[k] = command if rep is None else command + rep[k]
            applied[dadr] = command if dist is None else command + dist[k]
            mujoco.mj_step(model, data, nstep=self._substeps)
        return Recording(run_id, t, q, qd, tau, dict(spec))


class _DynamicsRegression:
    """servo.dynamics_regression on the nominal world: every identified key of every servo joint at once (a chain's joints are coupled),
    fitted by output error: the twin's replay of each train run's own tape against what the world reported (torque and position), from
    the description's priors, by scipy's least_squares."""
    id = ROUTINE
    # WHY its own needs, not the catalog's (requires zero_offset_rad, static_friction_nm: the UR wrist's homed frame and breakaway): the
    # nominal world's tapes run in the description's own joint frame and the fit finds its own friction level, as CAN 11's routine does
    requires = ()
    uses = ()
    # WHY zero and not the catalog's (1348 s wall, 600 s hands-on: CAN 11's rack session): the tapes state their own robot time, and a
    # nominal world has nothing to attach or read by hand
    wall_time_s = 0.0
    operator_time_s = 0.0

    def __init__(self, keys: Sequence[str], units: Mapping[str, str], runs: Sequence[seam.Run]) -> None:
        self.identifies = tuple(keys)
        self._units = dict(units)
        self._runs = tuple(runs)

    def runs(self, values: Mapping[str, float]) -> tuple[seam.Run, ...]:
        return self._runs   # made at the priors (the start poses, the gains), so the schedule shows them known now

    def fit(self, measured: Mapping[str, Recording], values: Mapping[str, float], twin) -> dict[str, seam.Estimate]:
        import numpy as np  # noqa: PLC0415
        from scipy.optimize import least_squares  # noqa: PLC0415

        if not measured:
            return {}
        keys = self.identifies
        prior = np.array([float(values[k]) for k in keys])
        units = [self._units.get(k, "") for k in keys]
        scale = np.array([max(abs(p), SCALE_FLOOR.get(u, 1e-3)) for p, u in zip(prior, units)])
        low = np.array([(-p / s) if k.split(".", 1)[1] in NONNEG else -np.inf for k, p, s in zip(keys, prior, scale)])
        records = dict(measured)
        q_meas = np.concatenate([r.q[::RESIDUAL_EVERY] for r in records.values()])
        tau_meas = np.concatenate([r.tau[::RESIDUAL_EVERY] for r in records.values()])
        # each signal weighed by its own spread in the measurement: the torque's and the position's step-to-step
        # roughness (a median of absolute second differences), never the truth
        sigma_tau = np.maximum(_roughness(tau_meas), 1e-3)
        sigma_q = np.maximum(_roughness(q_meas), 1e-6)

        def at(z):
            return {**values, **{k: float(p + zi * s) for k, p, zi, s in zip(keys, prior, z, scale)}}

        def residual(z):
            predicted = twin.predict(records, at(z))
            q = np.concatenate([predicted[k].q[::RESIDUAL_EVERY] for k in records])
            tau = np.concatenate([predicted[k].tau[::RESIDUAL_EVERY] for k in records])
            return np.concatenate([((tau - tau_meas) / sigma_tau).ravel(), ((q - q_meas) / sigma_q).ravel()])

        solved = least_squares(residual, np.zeros(len(keys)), bounds=(low, np.full(len(keys), np.inf)), diff_step=1e-3,
                               # WHY x_scale="jac": the keys' sensitivities span six decades (the UR wrist's base damping vs its tip
                               # armature), and a unit scaling left the poorly scaled ones at their priors
                               x_scale="jac", ftol=1e-10, xtol=1e-10, gtol=1e-10, max_nfev=MAX_REPLAYS)
        theta = prior + solved.x * scale
        dof = max(1, solved.fun.size - len(keys))
        try:
            cov = np.linalg.inv(solved.jac.T @ solved.jac) * float(solved.fun @ solved.fun) / dof
            half = 1.96 * np.sqrt(np.clip(np.diag(cov), 0.0, None)) * scale
        except np.linalg.LinAlgError:
            half = np.full(len(keys), np.nan)
        method = (f"output error on the nominal world: least_squares over {len(records)} train tapes' reported torque and position, "
                  f"{solved.nfev} replays ({solved.message})")
        return {k: seam.Estimate(float(v), None if not math.isfinite(h) else (float(v - h), float(v + h)), method)
                for k, v, h in zip(keys, theta, half)}


def _roughness(signal):
    """Per column, the noise level a signal carries: the median absolute second difference / sqrt(6) x 1.4826 (white noise's sigma)."""
    import numpy as np  # noqa: PLC0415

    second = np.diff(signal, n=2, axis=0)
    return 1.4826 * np.median(np.abs(second - np.median(second, axis=0)), axis=0) / math.sqrt(6.0)

