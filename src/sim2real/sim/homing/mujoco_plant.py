"""MujocoRigPlant: the homing bench's MuJoCo rung - bam_fb_test_rig's v11 twin (``RigSim`` on ``bench_rig``) behind the same
``HomingPlant`` seam as the kinematic rung (``reset`` / ``tick`` / ``state`` / ``truth`` and the flank-contact log).

What MuJoCo adds over ``KinematicStopPlant`` (the decision report: "kinematic proves geometry, MuJoCo proves dynamics"):

* gravity, with the arm hung as on the rack (``model.RACK_MOUNT``), the drives' reflected inertia (the bundle's 60ASM400 armature) and
  their stiff Coulomb friction (0.74 N.m, bam_fivebar's JMC record);
* the stops as the exporter's contact pairs and the loop closed by its ``connect``, so a start on the mirrored assembly can be carried
  across the toggle by gravity (or not) - the thing the kinematic rung cannot judge (the coordinator's 2026-11-12 ruling);
* the hidden backlash as gear_backlash's double joint, J1 3.5' / J2 2.5' / C1 4.0' (``bam_fb_test_rig.backlash.HIDDEN_ARCMIN``): B0 none,
  B1 ``method="deadzone"`` (the ElastoBacklash torque), B2 ``method="passive_joint"`` (a limited hinge tuned to the mesh's 13 N.m/arcmin);
* the boards: one ``moteus_servo`` position loop per drive at the rack record's gains (kp 200, kd 4 per output rev), fed every 10 ms;
* JMC cogging on J2 and C1 (``bam_fivebar.plant.JMC_COGGING``, sim2real bldc_motor M4.dynamics.cogging, fitted 2026-11-12 on the real
  arm's board torque) in each drive's Craig frame (``bam_fb_test_rig.gravity.CraigMap``: the fit's phase is in Craig, and Craig = URDF +
  90.00 / 137.46 deg shifts a 50 / rev ripple by half a period). J1 has no fitted cogging (its CAN 11 drive was never in the fit), so it
  runs without: the results say so.

The command a sequence step sends is turned into the board's command exactly as bam_fivebar_recovery's ``PlantBackend`` (the rack
runner's adapter) does: a limp joint (NaN position or cap 0) is a stopped board; any other is a position setpoint with its feed-forward
and cap, ``ilimit_scale`` 0 (the rack runner's default: the boards run as PDs), no velocity target.

Frames: the board reads ``sign * motor`` (the drive's hinge = the MOTOR side of the gap); what the controller sees is
``position = (motor - hidden_offset) + frame``, the same encoder convention as the kinematic plant, so a procedure's ``offset_rad`` is
scored against ``hidden_offset``. ``truth()`` reads the links (motor + twist) and the stop contacts; no procedure may read it.

Starts are placed, then settled UNPOWERED under gravity (``SETTLE_S``): the real arm powers up where gravity and its friction left it,
so a start is the pose it settles to, and the bench records that pose. WHY not hold the start pose: every procedure here runs behind
``recover_first``, whose first step is limp anyway; settling first makes the recorded start the one the boards powered up on.

The twin is bam_ws code (bam_fb_test_rig, moteus_servo, gear_backlash, cad2robot_payload; bam_fivebar for the cogging), loaded by path
(``bam_ws_path``): those packages are pure Python over numpy + MuJoCo 3.11.0, which sim2real's ``sim`` extra pins at the same version,
and sim2real must not take bam_fb_test_rig's whole environment (bam_fivebar's ruckig, opencv-contrib) as a dependency. Same reason the
W&B side loads bam_trackio.bbo by file (``tracking.rigs.load_bbo``).
"""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Mapping
from pathlib import Path

import numpy as np
from robot_msgs.control import ServoCommand
from robot_msgs.sensor import JointState
from robot_msgs.std import Header

from .geometry import C1, DRIVES, EXPORT, J1, J2, MIRROR
from .plant import HIDDEN_GAP_ARCMIN, Start, hidden_backlash

BAM_WS_SRC = Path(os.environ.get("SIM2REAL_BAM_WS_SRC", "/home/bam/bam_ws/src"))
BAM_WS_PATHS = (
    "dev/bam_fb_test_rig",
    "dev/bam_fivebar",
    "core/mdp/agent/actuators/moteus_servo/src",
    "core/mdp/agent/actuators/gear_backlash/src",
    "core/mdp/env/cad2robot_payload",
)
ROLE_OF = {J1: "J1", J2: "J2", C1: "C1"}
BACKLASH_METHOD = {"B0": None, "B1": "deadzone", "B2": "passive_joint"}
SETTLE_S = 2.0
CONTROL_DT = 0.01


def bam_ws_path(src: Path = BAM_WS_SRC) -> None:
    """Make the twin's bam_ws packages importable (module docstring). A no-op when they already are."""
    for relative in BAM_WS_PATHS:
        path = str(src / relative)
        if path not in sys.path:
            sys.path.append(path)


def available(src: Path = BAM_WS_SRC) -> bool:
    return all((src / relative).is_dir() for relative in BAM_WS_PATHS)


def loop_maps(loops: dict) -> dict:
    """The exporter's (J2, C1) maps per assembly, as the kinematic rung reads them (geometry.LoopMap)."""
    from .geometry import LoopMap  # noqa: PLC0415

    grid = loops["grid"]["status_rows"]
    values = np.array(grid["values_deg"], float)
    out = {EXPORT: LoopMap(EXPORT, values, values, tuple(grid["rows"]), float(loops["grid"]["step_deg"]))}
    if loops.get("mirror_grids"):
        mirror = loops["mirror_grids"][0]
        rows = mirror["status_rows"]
        out[MIRROR] = LoopMap(MIRROR, np.array(rows["row_values_deg"], float), np.array(rows["col_values_deg"], float),
                              tuple(rows["rows"]), float(mirror["step_deg"]))
    return out


def map_path(loop_map, frm_deg: tuple[float, float], to_deg: tuple[float, float]) -> list[tuple[float, float]] | None:
    """Cell centres (J2, C1 deg) from ``frm_deg``'s cell to ``to_deg``'s through closable cells ('.' free, '#' contact; 8-connected,
    breadth first), or None. The end cells themselves may be any status the map gives them (a start sits on a stop)."""
    from collections import deque  # noqa: PLC0415

    a, b = loop_map.node(*frm_deg), loop_map.node(*to_deg)
    if a is None or b is None:
        return None
    rows, n, m = loop_map.rows, len(loop_map.rows_deg), len(loop_map.cols_deg)
    ok = lambda i, k: rows[i][k] in ".#" or (i, k) in (a, b)  # noqa: E731
    previous = {a: None}
    queue = deque([a])
    while queue:
        cell = queue.popleft()
        if cell == b:
            break
        for di in (-1, 0, 1):
            for dk in (-1, 0, 1):
                nxt = (cell[0] + di, cell[1] + dk)
                if nxt not in previous and 0 <= nxt[0] < n and 0 <= nxt[1] < m and ok(*nxt):
                    previous[nxt] = cell
                    queue.append(nxt)
    if b not in previous:
        return None
    out, cell = [], b
    while cell is not None:
        out.append((float(loop_map.rows_deg[cell[0]]), float(loop_map.cols_deg[cell[1]])))
        cell = previous[cell]
    return out[::-1]


class RigCache:
    """One compiled twin per backlash model per process (building one takes ~1.5 s)."""

    _rigs: dict = {}

    @classmethod
    def get(cls, kind: str):
        if kind not in cls._rigs:
            bam_ws_path()
            from bam_fb_test_rig.backlash import HIDDEN_ARCMIN, hidden_specs  # noqa: PLC0415
            from bam_fb_test_rig.bundle import load_bundle  # noqa: PLC0415
            from bam_fb_test_rig.rig import bench_rig  # noqa: PLC0415

            ours = {ROLE_OF[j]: v for j, v in HIDDEN_GAP_ARCMIN.items()}
            if ours != dict(HIDDEN_ARCMIN):  # one truth: the twin's hidden gaps are the ones the bench scores against
                raise ValueError(f"hidden gaps differ: sim2real {ours} vs bam_fb_test_rig {dict(HIDDEN_ARCMIN)}")
            bundle = load_bundle()
            method = BACKLASH_METHOD[kind]
            if method is None:
                rig = bench_rig(bundle, backlash=None)
            else:
                rig = bench_rig(bundle, backlash=hidden_specs(), backlash_method=method)
            cls._rigs[kind] = rig
        return cls._rigs[kind]


def cogging_terms(rig) -> dict:
    """``{role: (DriveRipple, craig_sign, craig_offset_rad)}`` for the drives with a fitted cogging (J2, C1)."""
    bam_ws_path()
    from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415
    from bam_fivebar.plant import JMC_COGGING  # noqa: PLC0415

    craig = CraigMap(rig)
    return {role: (ripple, craig.sign[role], craig.offset[role]) for role, ripple in zip(("J2", "C1"), JMC_COGGING, strict=True)}


class MujocoRigPlant:
    """The v11 five-bar twin in MuJoCo behind the homing seam (module docstring). One instance per environment; ``reset`` per episode."""

    joint_names = DRIVES

    def __init__(self, kind: str, *, cogging: bool = True, settle_s: float = SETTLE_S, log_every: int = 1):
        if kind not in BACKLASH_METHOD:
            raise ValueError(f"backlash kind must be B0, B1 or B2, not {kind!r}")
        bam_ws_path()
        from bam_fb_test_rig.homing import RACK_BOARD  # noqa: PLC0415
        from bam_fb_test_rig.rig import board_signs  # noqa: PLC0415

        self.kind = kind
        self.rig = RigCache.get(kind)
        self.signs = board_signs(self.rig.bundle, self.rig)
        self.board = RACK_BOARD
        self.backlash = hidden_backlash(kind)  # the truth the metrics score (same gaps as the twin's, RigCache checks)
        self.cogging = cogging_terms(self.rig) if cogging else {}
        self.settle_s = float(settle_s)
        self.log_every = int(log_every)
        self.time = 0.0
        self.branch = EXPORT
        self.sim = None
        self.hidden: dict[str, float] = {}
        self.frame: dict[str, float] = {}
        self.log: dict[str, list] = {}
        self.start_settled: dict = {}

    # -- placing a start --------------------------------------------------------------------------------------------------

    def _assembly_sign(self, q: np.ndarray) -> float:
        """Which assembly a closed pose is on: the orientation (about C1's axis) of the passive dyad's triangle - the two passive hinges'
        anchors and the loop's connect point. With both drives set, the loop closes in exactly these two ways."""
        import mujoco  # noqa: PLC0415

        from bam_fb_test_rig.closure import closure_points, passive_joints  # noqa: PLC0415

        model, data = self.rig.model, self._pose_data
        data.qpos[:] = q
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        a, b = (data.xanchor[model.joint(name).id].copy() for name in passive_joints(self.rig))
        (far, _), _ = closure_points(self.rig, data, self.rig.closures[0])
        axis = data.xaxis[model.joint(self.rig.bundle.joint("C1").name).id]
        return float(np.sign(axis @ np.cross(b - a, far - a)))

    def assembly(self, q: np.ndarray) -> str:
        """``export`` or ``mirror`` for a closed pose of the wrapped model (the dyad's orientation against the export pose's)."""
        import mujoco  # noqa: PLC0415

        if getattr(self, "_export_sign", None) is None:
            self._pose_data = mujoco.MjData(self.rig.model)
            self._export_sign = self._assembly_sign(self.rig.model.qpos0.copy())
        return EXPORT if self._assembly_sign(np.asarray(q, dtype=float)) == self._export_sign else MIRROR

    def _continue(self, q: np.ndarray, drives: dict, steps: int = 8):
        """Walk the drives from ``q`` to ``drives`` in small steps, re-closing the loop at each (stays on ``q``'s assembly);
        ``None`` if the loop cannot close somewhere on the way."""
        from bam_fb_test_rig.closure import solve_closure  # noqa: PLC0415

        q = np.array(q, dtype=float)
        start = {role: float(q[self.rig.qpos_adr(role)]) for role in drives}
        for k in range(1, steps + 1):
            for role, value in drives.items():
                q[self.rig.qpos_adr(role)] = start[role] + (value - start[role]) * k / steps
            q, residual = solve_closure(self.rig, q)
            if residual > 1e-6:
                return None
        return q

    def _closed_pose(self, start: Start) -> np.ndarray:
        """The start's drives closed on the assembly it names, reached by walking the exporter's own loop map (loops.json) from a
        pose known to be on that assembly: the export pose (``export``), or the mirror grid's seed (``mirror``: the cell where the
        exporter crossed the J2 toggle, with its mirror passive angles), along closable cells only ('.' or '#'), re-closing the loop
        every step. WHY walked: Gauss-Newton from the export pose straight to a far pose does not converge (478 mm residual from the
        bowl), and a straight walk can cross cells where the loop cannot close; the map knows which cells close on which assembly."""
        import json  # noqa: PLC0415

        import mujoco  # noqa: PLC0415

        bam_ws_path()
        from bam_fb_test_rig.closure import solve_closure  # noqa: PLC0415

        self._pose_data = mujoco.MjData(self.rig.model)
        loops = json.loads((Path(self.rig.bundle.root) / "loops.json").read_text())
        maps = loop_maps(loops)
        home = self.rig.model.qpos0.copy()
        export_sign = self._assembly_sign(home)
        if start.branch == MIRROR:
            seed = loops["mirror_grids"][0]["seed"]
            origin = home.copy()
            origin[self.rig.qpos_adr("J2")], origin[self.rig.qpos_adr("C1")] = (math.radians(v) for v in seed["cell_deg"])
            for name, value in seed["mirror_passive_deg"].items():
                origin[self.rig.model.jnt_qposadr[self.rig.model.joint(name).id]] = math.radians(value)
            origin, _ = solve_closure(self.rig, origin)
            frm = tuple(seed["cell_deg"])
        else:
            origin, frm = home, (0.0, 0.0)
        target = (math.degrees(start.link_rad[J2]), math.degrees(start.link_rad[C1]))
        path = map_path(maps[start.branch], frm, target)
        if path is None:
            raise ValueError(f"start {start.name!r}: no closable path on the {start.branch} map from {frm} to {target}")
        q = origin.copy()
        q[self.rig.qpos_adr("J1")] = float(start.link_rad[J1])
        for q6, q7 in path[1:] + [target]:
            q = self._continue(q, {"J2": math.radians(q6), "C1": math.radians(q7)})
            if q is None:
                raise ValueError(f"start {start.name!r}: the loop does not close at ({q6:.2f}, {q7:.2f}) deg on its walk")
        sign = self._assembly_sign(q)
        if (sign == export_sign) != (start.branch == EXPORT):
            raise ValueError(f"start {start.name!r}: walked to the wrong assembly (sign {sign:+.0f}, export {export_sign:+.0f})")
        return q

    def reset(self, start: Start) -> JointState:
        import mujoco  # noqa: PLC0415

        bam_ws_path()
        from bam_fb_test_rig.sim import Drive, RigSim  # noqa: PLC0415

        self.branch = start.branch
        q = self._closed_pose(start)
        sim = RigSim(self.rig, tuple(Drive(ROLE_OF[j], self.signs[ROLE_OF[j]], self.board) for j in DRIVES), log_hz=1e-6)
        sim.data.qpos[:] = q
        if self.rig.backlash is not None:
            wrapped = self.rig.backlash
            link = wrapped.link_qpos(sim.data)  # the closed pose has every twist 0: its drive hinges are the links
            # where each motor sits in its gap: twist = link - motor = fraction x gap/2 (the kinematic plant's convention)
            twist = {j: float(start.gap_fraction.get(j, 0.0)) * 0.5 * wrapped.joints[j].spec.total_gap_rad for j in DRIVES}
            wrapped.set_state(sim.data, link, None, twist)
        sim.data.qvel[:] = 0.0
        mujoco.mj_forward(self.rig.model, sim.data)
        if self.cogging:
            sim.pre_step = self._cog
        # the boards read sign * motor (offset 0); the procedures' frame is ours, below
        sim.power_up({ROLE_OF[j]: self.signs[ROLE_OF[j]] * sim.joint_rad(ROLE_OF[j]) for j in DRIVES})
        before = {ROLE_OF[j]: math.degrees(sim.link_rad(ROLE_OF[j])) for j in DRIVES}
        if self.settle_s > 0:
            sim.step(self.settle_s)  # unpowered: gravity, friction, the stops
        sim.data.time = 0.0
        self.sim = sim
        self.time = 0.0
        self.hidden = {j: float(start.hidden_offset_rad.get(j, 0.0)) for j in DRIVES}
        self.frame = {j: 0.0 for j in DRIVES}
        self.start_settled = {"placed_link_deg": before,
                              "settled_link_deg": {ROLE_OF[j]: math.degrees(sim.link_rad(ROLE_OF[j])) for j in DRIVES},
                              "settled_assembly": self.assembly(sim.data.qpos)}
        self.log = {"t": [], "link": [], "motor": [], "position": [], "effort": [], "touching": [], "setpoint": []}
        self._velocity = {j: 0.0 for j in DRIVES}
        self._record(None)
        return self.state()

    def _cog(self, data) -> None:
        for role, (ripple, sign, offset) in self.cogging.items():
            q = float(data.qpos[self.rig.qpos_adr(role)])  # the motor side: the rotor turns with it
            craig = sign * q + offset
            # DriveRipple: the plant feels -torque_nm(q) in Craig; back to the URDF joint by the Craig sign
            data.qfrc_applied[self.rig.dof_adr(role)] -= sign * float(ripple.torque_nm(craig))

    # -- the seam ---------------------------------------------------------------------------------------------------------

    def _motor(self, joint: str) -> float:
        return self.sim.joint_rad(ROLE_OF[joint])

    def tick(self, command: ServoCommand, dt: float, defines: Mapping[str, float] | None = None) -> JointState:
        from moteus_servo import MoteusCommand  # noqa: PLC0415

        for joint, value in (defines or {}).items():
            self.frame[joint] = float(value) - (self._motor(joint) - self.hidden[joint])
        index = {name: i for i, name in enumerate(command.name)}
        size = len(command.name)
        cap = np.zeros(size) if command.max_effort is None else np.asarray(command.max_effort, dtype=float)
        feedforward = np.zeros(size) if command.feedforward_effort is None else np.asarray(command.feedforward_effort, dtype=float)
        targets = {}
        before = {j: self._motor(j) for j in DRIVES}
        for joint in DRIVES:
            role = ROLE_OF[joint]
            i = index.get(joint)
            position = math.nan if i is None else float(command.position[i])
            if i is None or cap[i] <= 0.0 or not math.isfinite(position):
                self.sim.stop(role)
                targets[joint] = None
                continue
            target = position - self.frame[joint] + self.hidden[joint]  # true motor angle (URDF)
            targets[joint] = target
            sign = self.signs[role]
            self.sim.states[role].ramp_target_rad = None
            # WHY this command (bam_fivebar_recovery.backend.PlantBackend.write, the rack runner's adapter): ilimit_scale 0 and no
            # velocity target - the boards run as PDs, which is what the sequences' caps and stall thresholds were tuned against
            self.sim._send(role, MoteusCommand(position_rad=sign * target, feedforward_torque_nm=sign * float(feedforward[i]),
                                               ilimit_scale=0.0, maximum_torque_nm=float(cap[i])))
        self.sim.step(dt)
        self.time += dt
        for joint in DRIVES:
            self._velocity[joint] = (self._motor(joint) - before[joint]) / dt
        self._record(targets)
        return self.state()

    def state(self) -> JointState:
        return JointState(
            name=DRIVES,
            position=np.array([self._motor(j) - self.hidden[j] + self.frame[j] for j in DRIVES]),
            velocity=np.array([self._velocity[j] for j in DRIVES]),
            effort=np.array([self.signs[ROLE_OF[j]] * self.sim.states[ROLE_OF[j]].torque_nm for j in DRIVES]),
            header=Header(stamp=self.time),
        )

    def truth(self) -> dict:
        return {
            "time_s": self.time,
            "branch": self.branch,
            "link_rad": {j: self.sim.link_rad(ROLE_OF[j]) for j in DRIVES},
            "motor_rad": {j: self._motor(j) for j in DRIVES},
            "true_offset_rad": dict(self.hidden),
            "frame_rad": dict(self.frame),
            "touching": dict(zip(DRIVES, self.log["touching"][-1], strict=True)),
            "backlash": dict(self.backlash),
            "start": dict(self.start_settled),
        }

    def _touching(self) -> list[str]:
        """Which drive stop each drive's link presses now (``upper`` / ``lower`` from the exporter's pairs), else ''."""
        contacts = self.rig.stop_contacts(self.sim.data)
        out = []
        for joint in DRIVES:
            sides = [key.removeprefix(joint + "_") for key, force in contacts.items() if force > 0.0 and key.startswith(joint + "_")]
            out.append(sides[0] if sides else "")
        return out

    def _record(self, targets) -> None:
        self.log["t"].append(self.time)
        self.log["link"].append([self.sim.link_rad(ROLE_OF[j]) for j in DRIVES])
        self.log["motor"].append([self._motor(j) for j in DRIVES])
        self.log["position"].append([self._motor(j) - self.hidden[j] + self.frame[j] for j in DRIVES])
        self.log["effort"].append([self.signs[ROLE_OF[j]] * self.sim.states[ROLE_OF[j]].torque_nm for j in DRIVES])
        self.log["touching"].append(self._touching())
        self.log["setpoint"].append([math.nan if not targets or targets.get(j) is None else targets[j] for j in DRIVES])


__all__ = ["BACKLASH_METHOD", "MujocoRigPlant", "RigCache", "available", "bam_ws_path", "cogging_terms"]
