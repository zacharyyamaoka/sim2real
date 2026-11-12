"""The wrist's twin with gear backlash: bam_ur_wrist's KarnoppPlant (the coverage lane's twin of record it5: Karnopp stick-slip, the
moteus PID per drive at 0.2 ms behind its current loop, the command delay, the 2 A clip) on a model whose geared joints gear_backlash's
BacklashModel splits into a motor hinge and a gap hinge, plus the noise a real board adds. Used for the world (the hidden truth) and for
every twin a fit plays, so the oracle compares one plant with itself.

What is stock and imported in place (bam_ws main, 2080b12ee for these packages): the board seam and its PID loop (bam_ur_wrist.plant.SimPlant,
KarnoppPlant), the moteus controller (moteus_servo), the masses (bam_ur_wrist.mass_prior / model), the double joint and its tuned gear stop
(gear_backlash.wrap.BacklashModel, tune_limit), the bundle (bam_ur_wrist.bundle, cad2robot 3f7ef84 as the coverage lane loads it).

What is added here, each with its WHY below: the model is built through BacklashModel (WristModel asserts three hinges); the friction and
the hard stops of a geared joint act on its OUTPUT (the link tendon BacklashModel makes); the plant keeps a session frame; and the noise
model's terms are applied where a real board and host add them.
"""

from __future__ import annotations

import copy
import functools
import math
import sys
from pathlib import Path

import numpy as np

BAM_WS = Path("/home/bam/bam_ws")
# WHY these source trees on the path and not installed (sysid's rule, sysid/__init__.py): bam_ws main's packages used in place, never copied;
# bam_rack_twin's venv (sysid's runtime) already carries their dependencies (moteus_servo, cad2robot_payload, MuJoCo 3.11)
SOURCES = (BAM_WS / "src/dev/bam_ur_wrist", BAM_WS / "src/dev/bam_ur_wrist_coverage", BAM_WS / "src/core/mdp/agent/actuators/gear_backlash/src",
           BAM_WS / "src/core/mdp/setup/bam_homing/src")
for _path in SOURCES:
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.append(str(_path))

PHYSICS_DT_S = 0.0002   # bam_ur_wrist.model.PHYSICS_DT_S
CAN_IDS = (14, 15, 16)
# WHY 10x KarnoppPlant's 200 N.m.s/rad on a geared joint's stuck output (measured 2026-11-11): with the stock damper a held output crept
# 0.2 mrad/s under the motor's push and CAN 15's own gravity (MuJoCo's frictionloss is soft; the damper is what holds), a quarter of an
# arcmin a second that a held reversal reads as gap; at 2000 it creeps 0.02 mrad/s. WHY not more: at 20000 the damper, switched on in one
# 0.2 ms step, kicked the motor across its gap at 9 rad/s and tripped tview's speed guard (the stick test reads the previous step's qacc)
GEARED_STUCK_DAMPING_NM_S_RAD = 2000.0


@functools.lru_cache(maxsize=1)
def bundle():
    """The bundle the coverage lane's rig loads (bam_ur_wrist_coverage.rig.load_bundle: cad2robot 3f7ef84), once per process."""
    from bam_ur_wrist_coverage import rig  # noqa: PLC0415

    return rig.load_bundle()


@functools.lru_cache(maxsize=1)
def stripped_bundle():
    """The bundle with its MJCF as the physics sees it: every geom and mesh taken out (_compiled's WHY), written once to the cache. WHY a
    bundle and not only a model: the wrist lane's fits and kinematics build their own WristModel from bundle.mjcf_path; on this file each
    build takes 0.05 s and 6 MB instead of ~1 s and 118 MB (measured 2026-11-11, with the machine's memory full and the OOM killer active)."""
    import dataclasses  # noqa: PLC0415
    import os  # noqa: PLC0415

    import mujoco  # noqa: PLC0415

    b = bundle()
    path = Path.home() / ".cache" / "sim2real" / "ur_wrist_test_rig" / f"{b.sha}-no-meshes" / "scene.xml"
    if not path.exists():
        spec = mujoco.MjSpec.from_file(str(b.mjcf_path))
        for geom in list(spec.geoms):
            spec.delete(geom)
        for mesh in list(spec.meshes):
            spec.delete(mesh)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(f".{os.getpid()}.tmp")
        partial.write_text(spec.to_xml())
        partial.replace(path)
    return dataclasses.replace(b, mjcf_path=path)


@functools.lru_cache(maxsize=4)
def _compiled(gaps: tuple[float, float, float], stiffness_nm_per_rad: float):
    """(model, gap info) for one set of gaps, compiled once per process and copied per plant. WHY cached: a BacklashModel compiles the
    1030-mesh bundle three times (~1-2 s); a calibration plays a few hundred runs."""
    import mujoco  # noqa: PLC0415
    from gear_backlash.spec import BacklashSpec  # noqa: PLC0415
    from gear_backlash.wrap import BacklashModel  # noqa: PLC0415

    b = bundle()
    # WHY the bundle's own MJCF with its geoms and meshes taken out (measured 2026-11-11, at load ~400 with the machine's memory full): its
    # 1031 mesh geoms carry no contact (contype 0; bam_ur_wrist.self_contact's 948 pairs are WristModel's, and the oracle's tapes are the
    # collision-checked coverage plans) and every body has its own inertial, so the dynamics are the same to the last bit (body masses,
    # inertias, frames, joints compared equal); the model drops from 118 MB to 6 MB and mj_step from 101 us (with the pairs) to 7 us.
    # plant_check holds a run equal to KarnoppPlant's on the full model.
    spec = mujoco.MjSpec.from_file(str(b.mjcf_path))
    for geom in list(spec.geoms):
        spec.delete(geom)
    for mesh in list(spec.meshes):
        spec.delete(mesh)
    wrapped = {name: BacklashSpec(total_gap_rad=float(g), mesh_stiffness_nm_per_rad=stiffness_nm_per_rad) for name, g in zip(b.names, gaps) if g > 0.0}
    # WHY zero "center": the joint's zero is the middle of its gap (what homing corrected by half the gap recovers)
    wrapper = BacklashModel(spec, wrapped, method="passive_joint", zero="center", output_friction=True)
    tendons: dict[str, int] = {}
    if wrapped:
        # WHY the stop on the OUTPUT: a hard stop is a part the link hits, so the motor reaches it through the gear's gap; homing's stall
        # then reads the motor half a gap past the stop, as on the real wrist. BacklashModel keeps the limit on the motor hinge; it moves here
        s = wrapper.spec
        for name in wrapped:
            joint, tendon = s.joint(name), s.tendon(name + "__link")
            tendon.limited = mujoco.mjtLimited.mjLIMITED_TRUE
            tendon.range = list(joint.range)
            tendon.solref_limit = list(joint.solref_limit)
            tendon.solimp_limit = list(joint.solimp_limit)
            joint.limited = mujoco.mjtLimited.mjLIMITED_FALSE
        # WHY implicitfast where a joint is geared (measured 2026-11-11: Euler blew up 4 steps in): KarnoppPlant holds a stuck joint with a
        # 200 N.m.s/rad damper, which Euler integrates implicitly on a dof but explicitly on a tendon (b dt / I ~ 40 on these links);
        # implicitfast takes the tendon's damping implicitly too. An ungeared model keeps the bundle's Euler, so plant_check stays exact
        s.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
        model = s.compile()
        tendons = {name: model.tendon(name + "__link").id for name in wrapped}
    else:
        model = wrapper.model
    model.opt.timestep = PHYSICS_DT_S
    info = {name: {"gap_qpos": j.gap_qpos, "gap_dof": j.gap_dof, "tendon": tendons[name], "twist": (j.twist_low, j.twist_high),
                   "stop_timeconst_s": None if j.tuning is None else j.tuning.timeconst_s} for name, j in wrapper.joints.items()}
    return model, info


class _BacklashWrist:
    """Duck-types bam_ur_wrist.model.WristModel for SimPlant: the same masses, armature, stops and friction set-up, on the double-joint
    model. WHY not WristModel: it asserts exactly three hinges (nq == 3); a geared joint here is two."""

    def __init__(self, gaps, stiffness_nm_per_rad: float, *, masses=None, truth=None, coulomb_nm=None, armature_kg_m2=None,
                 stop_rad: float | None = None) -> None:
        import mujoco  # noqa: PLC0415
        from bam_ur_wrist.model import nominal_masses  # noqa: PLC0415

        b = bundle()
        self.bundle = b
        base, info = _compiled(tuple(float(g) for g in gaps), float(stiffness_nm_per_rad))
        self.model = copy.copy(base)
        self.gaps = info
        self.joint_ids = np.array([self.model.joint(name).id for name in b.names])
        self.qpos_adr = self.model.jnt_qposadr[self.joint_ids]
        self.dof_adr = self.model.jnt_dofadr[self.joint_ids]
        self.link_bodies = self.model.jnt_bodyid[self.joint_ids]
        self.gap_qpos = np.array([info[n]["gap_qpos"] if n in info else -1 for n in b.names])
        self.gap_dof = np.array([info[n]["gap_dof"] if n in info else -1 for n in b.names])
        self.tendon = np.array([info[n]["tendon"] if n in info else -1 for n in b.names])
        self.wrapped = self.tendon >= 0
        mass_model = masses if masses is not None else (truth.base if truth is not None and truth.base is not None else nominal_masses(b))
        self.masses = mass_model
        # WristModel's own set-up, in its order (bam_ur_wrist.model.WristModel.__init__)
        for index, body in enumerate(self.link_bodies):
            link = mass_model.links[index]
            self.model.body_mass[body] = link.mass_kg
            self.model.body_ipos[body] = link.com_m
            self.model.body_inertia[body] = self.model.body_inertia[body] * link.inertia_scale
        if stop_rad is not None:
            # the PHYSICAL stops of a twin when they differ from the CAD's (WristModel's stop_rad: the fatter hard stop, 165 deg), on the output
            for axis in range(3):
                if self.wrapped[axis]:
                    self.model.tendon_range[self.tendon[axis]] = (-stop_rad, stop_rad)
                else:
                    self.model.jnt_range[self.joint_ids[axis]] = (-stop_rad, stop_rad)
        if armature_kg_m2 is not None:
            self.model.dof_armature[self.dof_adr] = np.asarray(armature_kg_m2, dtype=float)
        if truth is not None:
            for index, body in enumerate(self.link_bodies):
                scale = float(truth.mass_scale[index])
                self.model.body_mass[body] *= scale
                self.model.body_inertia[body] *= scale
                self.model.body_ipos[body] += truth.com_offset_m[index]
        if coulomb_nm is not None:
            plain = ~self.wrapped
            self.model.dof_frictionloss[self.dof_adr[plain]] = np.asarray(coulomb_nm, dtype=float)[plain]
            self.model.dof_solref[self.dof_adr[plain]] = (0.002, 1.0)
            for axis in np.flatnonzero(self.wrapped):
                # WHY on the tendon: the output's friction acts on the link (motor + gap), gear_backlash's output_friction rule
                self.model.tendon_frictionloss[self.tendon[axis]] = float(np.asarray(coulomb_nm, dtype=float)[axis])
                self.model.tendon_solref_fri[self.tendon[axis]] = (0.002, 1.0)
        self.data = mujoco.MjData(self.model)
        mujoco.mj_setConst(self.model, self.data)

    def tune_gaps(self, data, stiffness_nm_per_rad: float) -> dict[str, float]:
        """Each gap stop's time constant solved again (gear_backlash.mjcf.tune_limit) for the inertia it pushes on HERE: these masses and
        armature, this pose. WHY (measured 2026-11-11): BacklashModel tunes at compile, on the bundle's Fusion-Steel masses and its 0.001
        armature; on the twin's own (lighter) masses CAN 16's stop came out 50x softer than its gear (140 vs 6876 N.m/rad), and the reversal
        read a quarter of its push as gap. Returns the time constant per geared joint (s)."""
        import mujoco  # noqa: PLC0415
        from gear_backlash.mjcf import tune_limit  # noqa: PLC0415
        from gear_backlash.spec import BacklashSpec  # noqa: PLC0415

        mujoco.mj_forward(self.model, data)
        out = {}
        for axis, name in enumerate(self.bundle.names):
            if not self.wrapped[axis]:
                continue
            dof = int(self.gap_dof[axis])
            unit = np.zeros(self.model.nv)
            unit[dof] = 1.0
            solved = np.zeros(self.model.nv)
            mujoco.mj_solveM(self.model, data, solved.reshape(1, -1), unit.reshape(1, -1))
            low, high = self.gaps[name]["twist"]
            spec = BacklashSpec(total_gap_rad=float(high - low), mesh_stiffness_nm_per_rad=float(stiffness_nm_per_rad))
            tuning = tune_limit(spec, 1.0 / float(solved[dof]), self.model.opt.timestep)
            self.model.jnt_solref[self.model.joint(name + "__backlash").id] = (tuning.timeconst_s, tuning.damping_ratio)
            out[name] = tuning.timeconst_s
        return out

    def link_q(self, data) -> np.ndarray:
        """The OUTPUT angles: motor + gap where a joint is geared."""
        q = data.qpos[self.qpos_adr].copy()
        q[self.wrapped] += data.qpos[self.gap_qpos[self.wrapped]]
        return q

    def link_qd(self, data) -> np.ndarray:
        qd = data.qvel[self.dof_adr].copy()
        qd[self.wrapped] += data.qvel[self.gap_dof[self.wrapped]]
        return qd


def wrist_plant_class():
    """The plant class, built on the stock KarnoppPlant once bam_ur_wrist is importable."""
    from bam_ur_wrist.plant import STUCK_DAMPING_NM_S_RAD, STUCK_FACTOR, KarnoppPlant, stribeck_friction  # noqa: PLC0415

    class WristPlant(KarnoppPlant):
        """KarnoppPlant on the double-joint model, in one session frame, with the noise model's board and host noise.

        WHY its own __init__ (SimPlant's builds a WristModel; the board seam, the latch and the PID loop are SimPlant's, inherited): only the
        model differs. WHY its own step: the Karnopp stick-slip of a geared joint must act on its output (the link tendon), where the
        friction is; an ungeared joint runs KarnoppPlant's step exactly (plant_check holds it)."""

        def __init__(self, truth, start_q, *, backlash_rad=(0.0, 0.0, 0.0), stiffness_nm_per_rad: float, viscous_nm_s_rad=None,
                     session_offset_rad=None, noise: dict | None = None, noise_seed=None, control_period_s: float = 0.01) -> None:
            from collections import deque  # noqa: PLC0415

            from moteus_servo import MoteusControllerState, MoteusPidConfig  # noqa: PLC0415

            self.bundle = bundle()
            self.truth = truth
            self.control_period_s = float(control_period_s)
            self.wrist = _BacklashWrist(backlash_rad, stiffness_nm_per_rad, truth=truth.mass, coulomb_nm=truth.coulomb_nm,
                                        armature_kg_m2=truth.armature_kg_m2, stop_rad=truth.stop_rad)
            from bam_ur_wrist.plant import SLIDE_STOP_RAD_S  # noqa: PLC0415

            self._stick_band = SLIDE_STOP_RAD_S if truth.stick_band_rad_s is None else float(truth.stick_band_rad_s)
            self.model, self.data = self.wrist.model, self.wrist.data
            if viscous_nm_s_rad is not None:
                viscous = np.asarray(viscous_nm_s_rad, dtype=float)
                self.model.dof_damping[self.wrist.dof_adr[~self.wrist.wrapped]] = viscous[~self.wrist.wrapped]
                for axis in np.flatnonzero(self.wrist.wrapped):
                    self.model.tendon_damping[self.wrist.tendon[axis]] = viscous[axis]
            dt = self.model.opt.timestep
            self._substeps = int(round(self.control_period_s / dt))
            self._pids = [MoteusPidConfig(kp=g.kp, ki=g.ki, kd=g.kd, ilimit=g.ilimit) for g in truth.gains]
            self._new_state = MoteusControllerState
            self.torque_cap_nm = np.asarray(truth.torque_cap_nm, dtype=float)
            self._lag = 1.0 - math.exp(-2.0 * math.pi * truth.current_loop_hz * dt)
            self._command_steps = int(round(truth.command_delay_s / dt))
            self._reply_steps = int(round(truth.reply_delay_s / dt))
            self._history = deque(maxlen=self._reply_steps + 1)
            self._pending = deque()
            self._physics_step = 0
            self._rng = np.random.default_rng(truth.seed)
            self.t_s = 0.0
            self.clock_s = 0.0
            self.commands_sent = 0
            self.commands_after_stop = 0
            self._stopped_by_host = False
            self._sign = np.asarray(truth.board_sign, dtype=float)
            self._offset = np.zeros(3)
            self._turns = [0, 0, 0]
            self._states = [MoteusControllerState() for _ in range(3)]
            self._stopped = [True, True, True]
            self._torque = np.zeros(3)
            noise = noise or {}
            self._noise = {k: float(v) for k, v in noise.items()}
            # WHY a second generator: SimPlant's own (truth.seed) draws the torque noise; the encoder, velocity, host loop and bus draw here
            self._noise_rng = np.random.default_rng(noise_seed if noise_seed is not None else [truth.seed, 7])
            self.set_q(start_q)
            self.gap_timeconst_s = self.wrist.tune_gaps(self.data, stiffness_nm_per_rad)
            self.power_cycle()
            if session_offset_rad is not None:
                # WHY a session frame (2026-11-11): one power-up per session, homed once; every run of the session reads the board in that
                # frame, as the real lane's runs after its tview homing
                self._offset = np.asarray(session_offset_rad, dtype=float).copy()

        # ---- ground truth

        def set_q(self, q, qd=None) -> None:
            import mujoco  # noqa: PLC0415

            mujoco.mj_resetData(self.model, self.data)
            self.data.qpos[self.wrist.qpos_adr] = q
            if qd is not None:
                self.data.qvel[self.wrist.dof_adr] = qd
            mujoco.mj_forward(self.model, self.data)

        def link_q(self) -> np.ndarray:
            return self.wrist.link_q(self.data)

        # ---- the noise a real board and host add

        def read(self):
            reading = super().read()
            quantum = self._noise.get("encoder_quantum_rad", 0.0)
            sigma = self._noise.get("encoder_noise_rad", 0.0)
            speed_sigma = self._noise.get("velocity_noise_rad_s", 0.0)
            if not (quantum or sigma or speed_sigma):
                return reading
            position = reading.position_rad + (self._noise_rng.normal(0.0, sigma, 3) if sigma else 0.0)
            if quantum:
                position = np.round(position / quantum) * quantum
            velocity = reading.velocity_rad_s + (self._noise_rng.normal(0.0, speed_sigma, 3) if speed_sigma else 0.0)
            return type(reading)(reading.t_s, position, velocity, reading.torque_nm, reading.mode, reading.fault)

        def send(self, commands) -> None:
            super().send(commands)
            jitter = self._noise.get("latency_jitter_s", 0.0)
            if jitter and self._pending:
                # WHY in order (a CAN bus delivers in order): a command latches at its own extra latency or after the one before it
                at, latched = self._pending.pop()
                extra = int(round(self._noise_rng.uniform(0.0, jitter) / self.model.opt.timestep))
                self._pending.append((at + extra, latched))

        def step(self):
            overrun = self._noise.get("period_overrun_s", 0.0)
            extra = self._noise_rng.exponential(overrun) if overrun else 0.0
            return self.advance(int(round((self.control_period_s + extra) / self.model.opt.timestep)))

        def advance(self, substeps: int):
            """``substeps`` physics steps (one host period, whatever its length), KarnoppPlant's loop with a geared joint's friction on its
            output; returns the reading at the end."""
            import mujoco  # noqa: PLC0415
            from moteus_servo import MoteusFeedback, step_moteus_controller  # noqa: PLC0415

            w = self.wrist
            dofs, geared = w.dof_adr, w.wrapped
            static = np.asarray(self.truth.static_friction_nm, dtype=float)
            if not hasattr(self, "_stuck"):
                self._stuck = np.abs(w.link_qd(self.data)) < self._stick_band
                self._sliding_damping = self.model.dof_damping[dofs].copy()
                self._sliding_tendon_damping = np.array([self.model.tendon_damping[w.tendon[a]] if geared[a] else 0.0 for a in range(3)])
            dt = self.model.opt.timestep
            applied = np.zeros(3)
            armature = self.model.dof_armature[dofs]
            disturbance_sigma = self._noise.get("torque_disturbance_nm", 0.0)
            # one draw per host period, held (a zero-order hold): the noise model's process term, on the boards that are driving
            disturbance = self._noise_rng.normal(0.0, disturbance_sigma, 3) if disturbance_sigma else np.zeros(3)
            for _ in range(int(substeps)):
                while self._pending and self._pending[0][0] <= self._physics_step:
                    self._latch(self._pending.popleft()[1])
                position, velocity = self._board_feedback()
                for axis in range(3):
                    if self._stopped[axis]:
                        requested = 0.0
                    else:
                        feedback = MoteusFeedback(position_rad=float(position[axis]), velocity_rad_s=float(velocity[axis]))
                        output, self._states[axis] = step_moteus_controller(self._states[axis], feedback, self._pids[axis], dt)
                        cap = self.torque_cap_nm[axis]
                        requested = min(cap, max(-cap, float(output.applied_torque_nm) + disturbance[axis]))
                    self._torque[axis] += self._lag * (requested - self._torque[axis])
                    applied[axis] = self._sign[axis] * self._torque[axis]
                link_speed = np.abs(w.link_qd(self.data))
                kinetic = stribeck_friction(link_speed, self.truth.coulomb_nm, static, self.truth.stribeck_rad_s)
                # the drive that would move the output: the motor's torque where the joint is rigid (KarnoppPlant's), and for a geared joint
                # the mesh force on the link, a q_motor'' = u - mesh  =>  mesh = u - a q_motor'' (the motor's own row), less gravity
                drive = np.abs(applied - self.data.qfrc_bias[dofs])
                if geared.any():
                    mesh = applied[geared] - armature[geared] * self.data.qacc[dofs[geared]]
                    drive[geared] = np.abs(mesh - self.data.qfrc_bias[w.gap_dof[geared]])
                slow = link_speed < self._stick_band
                self._stuck = np.where(self._stuck, drive <= static, slow & (drive <= static))
                plain = ~geared
                self.model.dof_frictionloss[dofs[plain]] = np.where(self._stuck[plain], STUCK_FACTOR * static[plain], kinetic[plain])
                self.model.dof_damping[dofs[plain]] = np.where(self._stuck[plain], STUCK_DAMPING_NM_S_RAD, self._sliding_damping[plain])
                for axis in np.flatnonzero(geared):
                    tendon = w.tendon[axis]
                    self.model.tendon_frictionloss[tendon] = STUCK_FACTOR * static[axis] if self._stuck[axis] else kinetic[axis]
                    self.model.tendon_damping[tendon] = GEARED_STUCK_DAMPING_NM_S_RAD if self._stuck[axis] else self._sliding_tendon_damping[axis]
                self.data.qfrc_applied[dofs] = applied
                mujoco.mj_step(self.model, self.data)
                self._physics_step += 1
                self._record()
            self.t_s += self.control_period_s
            self.clock_s += int(substeps) * dt
            return self.read()

    return WristPlant
