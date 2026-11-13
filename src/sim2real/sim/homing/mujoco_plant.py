"""MujocoRigPlant: the homing bench's MuJoCo rung - bam_fb_test_rig's v11 twin (``RigSim`` on ``bench_rig``) behind the same
``HomingPlant`` seam as the kinematic rung (``reset`` / ``tick`` / ``state`` / ``truth`` and the flank-contact log).

What MuJoCo adds over ``KinematicStopPlant`` (the decision report: "kinematic proves geometry, MuJoCo proves dynamics"):

* gravity, with the arm hung as on the rack (``model.RACK_MOUNT``), the drives' reflected inertia (the bundle's 60ASM400 armature) and
  their stiff Coulomb friction (0.74 N.m, bam_fivebar's JMC record);
* the stops as the exporter's contact pairs and the loop closed by its ``connect``, so a start on the mirrored assembly can be carried
  across the toggle by gravity (or not) - the thing the kinematic rung cannot judge (the coordinator's 2026-11-12 ruling);
* the hidden backlash as gear_backlash's double joint, J1 3.5' / J2 2.5' / C1 4.0' (``bam_fb_test_rig.backlash.HIDDEN_ARCMIN``): B0 none,
  B1 ``method="deadzone"`` (the ElastoBacklash torque, an explicit spring: its timestep is divided until the mesh mode is resolved,
  ``resolve_mesh_mode``, 62.5 us), B2 ``method="passive_joint"`` (a limited hinge tuned to the mesh's 13 N.m/arcmin);
* the boards: one ``moteus_servo`` position loop per drive at the real arm's record (``REAL_BOARD_RECORD``: J1 / C1 kp 200, kd 4; J2 kp 144,
  kd 8 per output rev - what CAN 11/12/13 ran when the home button recovered the arm), fed every 10 ms;
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
from .plant import HIDDEN_GAP_ARCMIN, PlantTrip, Start, hidden_backlash
from .real_plant import DRIVE_JOINTS, RUNAWAY_RAD_S

BAM_WS_SRC = Path(os.environ.get("SIM2REAL_BAM_WS_SRC", "/home/bam/bam_ws/src"))
BAM_WS_PATHS = (
    "dev/bam_fb_test_rig",
    "dev/bam_fivebar",
    "core/mdp/agent/actuators/moteus_servo/src",
    "core/mdp/agent/actuators/gear_backlash/src",
    "core/mdp/env/cad2robot_payload",
)
ROLE_OF = {J1: "J1", J2: "J2", C1: "C1"}
# The real arm's boards when the home button ran (2026-11-11 22:27Z and 2026-11-12 01:20Z / 08:56Z): each run's own config check against
# records/fivebar-bench/deployment.json, in its log beside the receipt (/archive/datasets/bam_rig/rack_2026-11-10/fivebar_real/
# home_real_222746_t1.log, home_real_repeatfloor_012056.log, home_real_after_gate1_085634.log): CAN 11 (J1) kp 200 / ki 16000 / kd 4 /
# ilimit 0.5, CAN 12 (J2) kp 144 / ki 16000 / kd 8 / ilimit 0.8, CAN 13 (C1) kp 200 / ki 16000 / kd 4 / ilimit 0.8 (N.m per output rev,
# moteus native). WHY J2 is not RACK_BOARD's 200 / 4: CAN 12 was retuned on the five-bar (bam_fivebar pid_tuna 2026-11-10) - softer and
# twice the damping. The integrator is off either way: the rack runner sends ilimit_scale 0 (PlantBackend), so ki and ilimit never act.
REAL_BOARD_RECORD = {"J1": {"kp": 200.0, "ki": 16000.0, "kd": 4.0, "ilimit": 0.5},
                     "J2": {"kp": 144.0, "ki": 16000.0, "kd": 8.0, "ilimit": 0.8},
                     "C1": {"kp": 200.0, "ki": 16000.0, "kd": 4.0, "ilimit": 0.8}}


def real_boards() -> dict:
    """``REAL_BOARD_RECORD`` as bam_fb_test_rig ``BoardConfig`` s (max torque as RACK_BOARD's: 17.5 A on the 60ASM200 + 10:1)."""
    bam_ws_path()
    from bam_fb_test_rig.homing import RACK_BOARD  # noqa: PLC0415
    from bam_fb_test_rig.sim import BoardConfig  # noqa: PLC0415

    return {role: BoardConfig(max_torque_nm=RACK_BOARD.max_torque_nm, **gains) for role, gains in REAL_BOARD_RECORD.items()}

BACKLASH_METHOD = {"B0": None, "B1": "deadzone", "B2": "passive_joint"}
SETTLE_S = 2.0
CONTROL_DT = 0.01

# The real arm's end group is heavier than CAD (2026-11-13, homing pass 6). The home button's comp since bam_ws 2ec4dd02a, mass-ID run
# massid_real_093852 (bam_rack_twin records/fivebar-bench/gravity_params_massid_real_093852.json, group "l2" = l2_link + elbow_link +
# wrist_1_servo + payload + l2_aruco_board): identified 2.0629 kg against CAD's 1.6842 kg, x1.2249; the run before it (massid_real_092506)
# gave 2.0537 kg, x1.2194 - "the end group weighs 22 % over CAD" (bam_rack_twin tview_run). The twin carries that whole group as one
# body, "l2" (1.6595 kg). WHY scale mass and inertia at the body's own COM: it is the conservative reading - the identified first moment
# of the group is only 2.8 % over CAD's (its COM sits 45 mm further in), so the gravity torque grows 2.8-22.5 % depending on which of the
# fit's numbers is believed; x1.2249 on the mass at a fixed COM is the upper end, the case a feed-forward must survive.
END_GROUP_BODY = "l2"
END_GROUP_MASS_SCALE = 2.0628530325950996 / 1.6841719999999998
# The real rung's runaway ceiling, one number for both rungs (real_plant.RUNAWAY_RAD_S: the bus plant's fivebar_plant.PlantLimits.
# runaway_ceiling_rad_s, 1.5 rad/s = 86 deg/s), applied to every POWERED J2 / C1 command as run_phase_real applies it to the homing
# sequences' plain position commands. WHY only J2 / C1: the real runner watches the bus's two drives (real_plant.DRIVE_JOINTS); J1 is held
# on the real rung and not watched there either.
RUNAWAY_JOINTS = DRIVE_JOINTS


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
    def get(cls, kind: str, end_mass_scale: float = 1.0, *, end_payload_kg: float | None = None):
        key = kind if end_mass_scale == 1.0 else (kind, float(end_mass_scale))
        if end_payload_kg is not None:  # WHY its own key: a claw-on twin must never be handed to a plate-on caller from the cache
            key = (kind, float(end_mass_scale), "end_payload_kg", float(end_payload_kg))
        if key not in cls._rigs:
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
            if end_payload_kg is not None:  # first the claw for the plate, then the end group's scale (END_PAYLOAD_WHY)
                swap_end_payload(rig, end_payload_kg)
            if end_mass_scale != 1.0:
                scale_body_mass(rig, END_GROUP_BODY, end_mass_scale)
            resolve_mesh_mode(rig)
            cls._rigs[key] = rig
        return cls._rigs[key]


def scale_body_mass(rig, body: str, scale: float) -> dict:
    """Scale one body's mass and rotational inertia by ``scale`` at its own COM (``END_GROUP_MASS_SCALE``'s WHY), then recompute MuJoCo's
    mass-derived constants (``mj_setConst``). Returns the before / after masses (kg)."""
    import mujoco  # noqa: PLC0415

    model = rig.model
    index = model.body(body).id
    before = float(model.body_mass[index])
    model.body_mass[index] = before * scale
    model.body_inertia[index] = model.body_inertia[index] * scale
    mujoco.mj_setConst(model, mujoco.MjData(model))
    return {"body": body, "mass_kg": before, "scaled_kg": float(model.body_mass[index]), "scale": float(scale)}


# END_PAYLOAD_WHY (2026-11-13, the crab claw on the five-bar): Zach mounts the crab claw in place of the 2.5 lb test plate. The twin's end
# group "l2" carries the plate and its mount, both centred on J4's axis (their geoms' centres in the l2 frame: x 0, z = L2's 0.2997 m, y
# along the axis); their masses are the Fusion export's own (the bundle's fusion360_data.json occurrences, ``END_PAYLOAD_PARTS``). The
# claw hangs on the unpowered J4, so for J2 / C1 it is a point mass on that axis at every pose (bam_ws docs/pick_tracking/claw_payload.py);
# it goes where the plate's centre was, with a 60 mm x 13 mm disc's own inertia about J4's axis (the hanging claw's own spin, ~1.7e-4
# kg.m^2 at 0.37 kg, not the plate's 2.8e-3). The plate's collision shells stay (the stops are not the plate's: J2 = L1's hardstop vs the
# shoulder plate, C1 = C1 vs L1's spacer, hardstops.json). Applied BEFORE the end-group scale, so "claw +22 %" scales the claw-on group.
END_PAYLOAD_PARTS = {"plate": ("2.5 lbs Weight:1", "2.5_lbs_Weight_1__0"),
                     "mount": ("Weight To Servo Mount v2:1", "Weight_To_Servo_Mount_v2_1__")}
PLATE_DISC_M = (0.140, 0.013)  # the plate's diameter and thickness (bam_robot_descriptions DiscPayloadParams, Zach's)
CLAW_DISC_M = (0.060, 0.013)


def _disc_inertia(mass: float, size: tuple[float, float], axis: int) -> np.ndarray:
    """A uniform disc's inertia about its centre, its axis along body axis ``axis`` (the l2 frame's y = J4's axis)."""
    radius, thickness = size[0] / 2.0, size[1]
    inertia = np.full(3, mass * (3.0 * radius**2 + thickness**2) / 12.0)
    inertia[axis] = mass * radius**2 / 2.0
    return np.diag(inertia)


def end_payload_parts(rig) -> dict:
    """``{"plate" | "mount": {"mass_kg", "com_l2_m"}}``: each part's Fusion mass and its centre in the end group's frame (its geoms' mean
    centre: MuJoCo puts a mesh geom at the mesh's centroid)."""
    import json as _json  # noqa: PLC0415

    model = rig.model
    body = model.body(END_GROUP_BODY).id
    occurrences = {o.get("name"): o for o in _json.loads((Path(rig.bundle.root) / "fusion360_data.json").read_text())["occurrences"]}
    names = [model.geom(g).name or "" for g in range(model.ngeom)]
    meshes = {g: (model.mesh(model.geom_dataid[g]).name if model.geom_dataid[g] >= 0 else "") for g in range(model.ngeom)}
    out = {}
    for part, (occurrence, mesh_prefix) in END_PAYLOAD_PARTS.items():
        geoms = [g for g in range(model.ngeom) if model.geom_bodyid[g] == body and not names[g].startswith("stop_")
                 and (meshes[g].startswith(mesh_prefix) or names[g].startswith(mesh_prefix))]
        if not geoms or occurrence not in occurrences:
            raise ValueError(f"the bundle has no {part} ({occurrence!r} / {mesh_prefix!r}) on {END_GROUP_BODY}")
        out[part] = {"mass_kg": float(occurrences[occurrence]["mass_kg"]),
                     "com_l2_m": np.mean([model.geom_pos[g] for g in geoms], axis=0).tolist()}
    return out


def swap_end_payload(rig, payload_kg: float) -> dict:
    """The end group with the plate and its mount out and a ``payload_kg`` point on J4's axis at the plate's centre (END_PAYLOAD_WHY):
    mass, centre and the full inertia tensor recomposed about the new centre and re-diagonalised, then ``mj_setConst``."""
    import mujoco  # noqa: PLC0415

    if not payload_kg > 0.0:
        raise ValueError(f"the end payload must be a positive mass, not {payload_kg!r} kg")
    model = rig.model
    body = model.body(END_GROUP_BODY).id
    parts = end_payload_parts(rig)
    axis = 1  # J4's axis is the l2 frame's y (the plate geom's thin direction)

    def about_origin(mass, com, inertia_com):
        com = np.asarray(com, dtype=float)
        return inertia_com + mass * (com @ com * np.eye(3) - np.outer(com, com))

    mass, com = float(model.body_mass[body]), np.asarray(model.body_ipos[body], dtype=float)
    rotation = np.zeros(9)
    mujoco.mju_quat2Mat(rotation, model.body_iquat[body])
    rotation = rotation.reshape(3, 3)
    total = about_origin(mass, com, rotation @ np.diag(model.body_inertia[body]) @ rotation.T)
    moment = mass * com
    plate, mount = parts["plate"], parts["mount"]
    for part, own in ((plate, _disc_inertia(plate["mass_kg"], PLATE_DISC_M, axis)), (mount, np.zeros((3, 3)))):
        total = total - about_origin(part["mass_kg"], part["com_l2_m"], own)
        moment = moment - part["mass_kg"] * np.asarray(part["com_l2_m"])
        mass -= part["mass_kg"]
    centre = np.asarray(plate["com_l2_m"], dtype=float)
    total = total + about_origin(payload_kg, centre, _disc_inertia(payload_kg, CLAW_DISC_M, axis))
    moment = moment + payload_kg * centre
    mass += payload_kg
    new_com = moment / mass
    inertia_com = total - mass * (new_com @ new_com * np.eye(3) - np.outer(new_com, new_com))
    values, vectors = np.linalg.eigh(0.5 * (inertia_com + inertia_com.T))
    if np.linalg.det(vectors) < 0.0:
        vectors[:, 0] = -vectors[:, 0]
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, vectors.reshape(-1))
    before = float(model.body_mass[body])
    model.body_mass[body] = mass
    model.body_ipos[body] = new_com
    model.body_inertia[body] = values
    model.body_iquat[body] = quat
    mujoco.mj_setConst(model, mujoco.MjData(model))
    return {"body": END_GROUP_BODY, "mass_kg": before, "swapped_kg": mass, "payload_kg": float(payload_kg),
            "removed": {k: v["mass_kg"] for k, v in parts.items()}}


# WHY 0.3 (2026-11-12, homing MuJoCo rung pass 4): gear_backlash's dead zone is an explicit spring ("dt must resolve the mesh mode",
# gear_backlash.wrap), and its own bound (omega dt < 2, ArmRig.explicit_spring_dt_limit_s) is the linear spring's, not the impacting
# one's. At the twin's 0.25 ms C1's mesh mode (13 N.m/arcmin on 0.0020 kg.m^2) has omega dt = 1.19: under the bound, yet every flank
# impact gained energy - 814 N.m of mesh torque and the 3 rad/s speed guard tripped in recover_first+tview_v2 from the bowl, 5800 N.m and
# 70 rad/s pressing both stops for 8 s. Measured on that episode (data/homing_fivebar_b1_timestep_2026-11-12.json, tools/
# homing_b1_timestep.py): dt/2 completes, its zeros within 0.001 deg of dt/8's but its peak mesh torque 116 N.m; dt/4 (omega dt 0.30) and
# dt/8 agree on both (138.5 vs 138.8 N.m, zeros within 0.0002 deg). The passive joint (B2) is MuJoCo's own implicit limit and needs none.
MESH_MODE_OMEGA_DT = 0.3


def resolve_mesh_mode(rig) -> int:
    """Divide ``rig``'s timestep so the stiffest dead-zone mesh mode has ``omega dt <= MESH_MODE_OMEGA_DT`` (module WHY); returns the
    divisor (1: no dead zone, nothing changed). ``omega = sqrt(mesh stiffness / the wrapped joint's effective inertia)``."""
    wrapped = getattr(rig, "backlash", None)
    if wrapped is None or getattr(wrapped, "method", None) != "deadzone" or not wrapped.joints:
        return 1
    omega = max(math.sqrt(joint.spec.mesh_stiffness_nm_per_rad / joint.effective_inertia_kg_m2) for joint in wrapped.joints.values())
    divisor = max(1, math.ceil(omega * float(rig.model.opt.timestep) / MESH_MODE_OMEGA_DT - 1e-9))
    rig.model.opt.timestep = float(rig.model.opt.timestep) / divisor
    return divisor


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

    def __init__(self, kind: str, *, cogging: bool = True, settle_s: float = SETTLE_S, log_every: int = 1, boards: Mapping | None = None,
                 end_mass_scale: float = 1.0, runaway_rad_s: float | None = None, end_payload_kg: float | None = None):
        if kind not in BACKLASH_METHOD:
            raise ValueError(f"backlash kind must be B0, B1 or B2, not {kind!r}")
        bam_ws_path()
        from bam_fb_test_rig.homing import RACK_BOARD  # noqa: PLC0415
        from bam_fb_test_rig.rig import board_signs  # noqa: PLC0415

        self.kind = kind
        self.end_mass_scale = float(end_mass_scale)
        # WHY off unless asked (pass 6): the pass 3-5 results were run without it and stand as run; the pass-6 rung passes RUNAWAY_RAD_S
        self.runaway_rad_s = None if runaway_rad_s is None else float(runaway_rad_s)
        self.peak_powered_rad_s: dict[str, float] = {}
        # WHY None by default (2026-11-13): every earlier pass ran the plate; a claw-on twin is asked for by its mass (END_PAYLOAD_WHY)
        self.end_payload_kg = None if end_payload_kg is None else float(end_payload_kg)
        self.rig = RigCache.get(kind, self.end_mass_scale, end_payload_kg=self.end_payload_kg)
        self.signs = board_signs(self.rig.bundle, self.rig)
        self.board = RACK_BOARD
        # WHY the real record by default (2026-11-12, the home button's ground truth): the boards the real arm ran on, cited above
        boards = real_boards() if boards is None else boards
        self.boards = {ROLE_OF[j]: boards[ROLE_OF[j]] for j in DRIVES}
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
        sim = RigSim(self.rig, tuple(Drive(ROLE_OF[j], self.signs[ROLE_OF[j]], self.boards[ROLE_OF[j]]) for j in DRIVES), log_hz=1e-6)
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
        self.peak_powered_rad_s = {ROLE_OF[j]: 0.0 for j in RUNAWAY_JOINTS}
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
        self._check_runaway(targets)
        return self.state()

    def _check_runaway(self, targets: Mapping[str, float | None]) -> None:
        """The real rung's runaway stop (``RUNAWAY_RAD_S``'s WHY): a POWERED J2 / C1 faster than the ceiling ends the episode
        (:class:`PlantTrip`), as ``real_plant.run_phase_real`` holds the bus and stops the sequence. The board velocity it watches is the
        drive's own (the motor side), measured over the control tick as the plant reports it."""
        for joint in RUNAWAY_JOINTS:
            if targets.get(joint) is None:
                continue
            speed = abs(self._velocity[joint])
            role = ROLE_OF[joint]
            self.peak_powered_rad_s[role] = max(self.peak_powered_rad_s.get(role, 0.0), speed)
            if self.runaway_rad_s is not None and speed > self.runaway_rad_s:
                raise PlantTrip(f"runaway: {role} at {math.degrees(speed):.0f} deg/s powered, over {math.degrees(self.runaway_rad_s):.0f} "
                                f"deg/s at t {self.time:.2f} s", kind="runaway", joint=role, speed_rad_s=speed, time_s=self.time)

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


# The twin's own stops, measured (2026-11-12 pass 4, the coordinator: report homing error vs CAD AND vs the twin's own contact, so a
# procedure's error is separable from the exporter's geometry - its J2 pair is 0.285 deg short of CAD). WHY measured by pressing and not
# by bam_fb_test_rig.model.stop_sweep: the exporter's pairs between two links include hulls that touch far from the stop (the sweep reports
# J2's upper at 10.4 deg), so only the contact a drive actually presses on is the stop. Two light pushes, gravity off, extrapolated to zero.
TWIN_CONTACT_PUSH_NM = (2.0, 4.0)
TWIN_CONTACT_PRESS_S = 1.5


def twin_contacts(starts: Mapping, *, kind: str = "B0", push_nm: tuple[float, float] = TWIN_CONTACT_PUSH_NM,
                  press_s: float = TWIN_CONTACT_PRESS_S) -> dict:
    """``{(joint, side): rad}``: where each drive's link meets its stop in the twin, independent of any homing procedure. From
    ``starts[+1]`` (every drive just inside its upper stop) and ``starts[-1]`` (just inside its lower), with gravity switched off and no
    cogging, each drive in turn is pushed onto that side's stop at each of ``push_nm`` (position far past the stop, the push as its cap),
    the others holding where they rest; its link angle after ``press_s`` is extrapolated linearly to zero push. Raises if a press is
    not on the stop it names (the plant's contact log)."""
    from robot_msgs.control import ServoCommand  # noqa: PLC0415

    plant = MujocoRigPlant(kind, cogging=False, settle_s=0.0)
    gravity = plant.rig.model.opt.gravity.copy()
    out = {}
    try:
        plant.rig.model.opt.gravity[:] = 0.0
        for side in (+1, -1):
            for pushed in DRIVES:
                links = []
                for push in push_nm:
                    state = plant.reset(starts[side])
                    rest = dict(zip(state.name, state.position, strict=True))
                    position = np.array([rest[j] + (side * 0.5 if j == pushed else 0.0) for j in DRIVES])
                    cap = np.array([push if j == pushed else 10.0 for j in DRIVES])
                    for _ in range(int(round(press_s / CONTROL_DT))):
                        plant.tick(ServoCommand(name=DRIVES, position=position, max_effort=cap), CONTROL_DT)
                    touching = plant.log["touching"][-1][DRIVES.index(pushed)]
                    if touching != ("upper" if side > 0 else "lower"):
                        raise RuntimeError(f"{pushed} pushed {side:+d} at {push} N.m is touching {touching!r}, not its stop")
                    links.append(plant.sim.link_rad(ROLE_OF[pushed]))
                (p1, p2), (l1, l2) = push_nm, links
                out[(pushed, side)] = float(l1 - (l2 - l1) * p1 / (p2 - p1))
    finally:
        plant.rig.model.opt.gravity[:] = gravity
    return out


__all__ = ["BACKLASH_METHOD", "END_GROUP_BODY", "END_GROUP_MASS_SCALE", "END_PAYLOAD_PARTS", "MESH_MODE_OMEGA_DT", "RUNAWAY_RAD_S", "MujocoRigPlant",
           "RigCache", "available", "bam_ws_path", "cogging_terms", "resolve_mesh_mode", "scale_body_mass", "end_payload_parts", "swap_end_payload", "twin_contacts"]
