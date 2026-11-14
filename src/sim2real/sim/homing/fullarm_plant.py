"""The full arm (bam_fb_v2: five-bar + UR wrist + crab claw) behind the homing seam - every joint on its board, sim only, 2026-11-13.

``fullarm_home.FullArmPlant`` drives only the five-bar (bam_fivebar's two-drive ``Plant`` seam) and lets the wrist hold, go limp or brake;
a full-arm HOMING needs every joint commandable from one robot_msgs ``JointCommandSequence``. This plant is robot_models' ``HomingPlant``
(``reset`` / ``tick`` / ``truth``, PEP 0002) over the same twin, for seven joints:

=====  ===========  =======  ===============================================================================================
name   URDF joint   CAN      board here
=====  ===========  =======  ===============================================================================================
J1     revolute_3   11       the real record (mujoco_plant.REAL_BOARD_RECORD), JMC cogging off (J1 is held, never homed: real form)
J2     revolute_6   12       the real record + the JMC cogging (mujoco_plant.cogging_terms), as the homing rung's
C1     revolute_7   13       the same
W1-W3  revolute_11  14-16    GIM4305-10 on moteus c1: kp 15 N.m/rev, kd 0.15 (the rack's config read), 1.02 N.m (2 A x 0.5087)
CLAW   revolute_5   17       MG4005-10: a PD at the physics rate (no board record exists: an assumption, KP/KD below)
=====  ===========  =======  ===============================================================================================

**What the bus reads (the hidden power-on frame).** A board boots reading its rotor encoder divided by the gear ratio: the output is
known only modulo one rotor turn (36 deg at 10:1, self_collision's "known only mod 36 deg"). So each wrist/claw joint reads
``raw = wrap36(q_motor + phase)`` at power-on, ``phase`` its encoder's fixed sub-turn offset (``ROTOR_PHASE_DEG``: hidden truths here,
calibrated once on the real arm; a procedure may know them through ``ArmPrior.rotor_phase``), and counts continuously after. The five-bar's
drives read the homing rung's arbitrary power-up offsets (gff_rung.HIDDEN_OFFSETS). ``truth()["true_offset_rad"]`` is what a perfect home
returns: ``q_joint = raw + offset``.

**Self-contact is physical here, not only checked.** The stripped scene ``fullarm_home`` builds keeps only the stops' and the loop's
contact shapes; this plant's scene (``contact_scene``) also keeps the bundle's per-component primitives (cad2robot ``collision.json``
channel ``primitive``, MJCF group 3) on every arm body, colliding with each other (contype/conaffinity bit 2) except across the five-bar's
own bodies (their contacts are the exporter's loop pairs). So a wrist sweep into the forearm STALLS on the forearm here, as it would on the
arm - a false stop a procedure must not take for its hard stop. Each tick logs every such contact (``self_contact``) for the harness.
WHY primitives and not the visual meshes: the 1988 visual meshes are 3.8x slower (fullarm_home.stripped_scene) and MuJoCo collides mesh
hulls, not meshes; the primitives are per-component boxes. They are LEANER than the meshes: gripper/forearm first touch at |W1|, |W2| ~ 130-
150 deg on the primitives vs 104.91 on the meshes (self_collision_wrist.json) - so the harness also runs ``bam_cad_descriptions``'
``check_pose`` on every tick, and a run is judged on both (``fullarm_check``).

Every angle shown is in degrees; everything stored is SI.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from robot_models.homing.protocols import Prior
from robot_models.homing.types import BacklashModel, StopMap, StopSide
from robot_msgs.control import ServoCommand
from robot_msgs.sensor import JointState
from robot_msgs.std import Header

from . import fullarm_home as fh
from .mujoco_plant import BAM_WS_SRC, bam_ws_path, cogging_terms, real_boards
from .plant import PlantTrip

# -- J1 as the rack runs it (2026-11-14, the Sim to Real Agent's real J1 homes) -----------------------------------------------------------
# WHY read from bam_rack_twin.hardware.j1_gains, never a number of ours (the dispatcher, 2026-11-14: "use those gains, not your own"): every
# tool on the rack that holds or moves J1 sends kp x14 / kd x16.8 and the gravity feed-forward that module computes - one place
J1_GAINS_PY = BAM_WS_SRC / "dev" / "bam_rack_twin" / "bam_rack_twin" / "hardware" / "j1_gains.py"
J1_RACK_ZERO_BOARD_RAD = 0.25439  # latest.json revolute_3 since the real top-stop homes (05:41Z / 05:56Z): board = URDF J1 + this
# WHY the twin's J1 feels the rack's measured READY curve (j1_gains.j1_gravity_nm: 5.32 sin(board - 0.075), the 34 holds of j1gsweep_062149
# within their 0.3 N.m friction band, -5.2 N.m at the stop) instead of the CAD's: the CAD puts the shoulder's COM 32 mm on the wrong side
# of J1's axis (pid_tuna_full_arm/j1_gravity/j1_pose_fit.json: the CAD alone misses the holds by 1.97 N.m RMS; at READY the twin's CAD
# rests J1 at +24 deg where the arm hangs at -10 deg). The pose-aware fit there (1.592 x the CAD's hanging moment + a refit shoulder sine)
# is not used: on the twin's own READY wrist (TD4) its hanging term reads ~1.1 N.m under the rack's sweep pose and puts the stop's load at
# 3.2 N.m, not the measured 5.5. Pose-blind like the rack's own feed-forward, so J1's load at other five-bar poses is the READY one.


def j1_rack_gains():
    """The rack's J1 module (kp / kd scales, ``j1_gravity_nm``), loaded from its file: no bam_rack_twin package import."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("bam_rack_twin_j1_gains", J1_GAINS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

TAU = 2.0 * math.pi
CONTROL_DT = 0.01

J1, J2, C1 = "revolute_3", "revolute_6", "revolute_7"
W1, W2, W3 = "revolute_11", "revolute_14", "revolute_17"
CLAW = "revolute_5"
FIVEBAR = (J1, J2, C1)
WRIST = (W1, W2, W3)
JOINTS = (J1, J2, C1, W1, W2, W3, CLAW)
ROLE = {J1: "J1", J2: "J2", C1: "C1", W1: "W1", W2: "W2", W3: "W3", CLAW: "CLAW"}
CAN = {J1: 11, J2: 12, C1: 13, W1: 14, W2: 15, W3: 16, CLAW: 17}

# -- the boards ------------------------------------------------------------------------------------------------------------------------
# WHY 15 / 0.15 and not bam_ur_wrist's RAM 75: the real boards' config as read by wrist_home_v1 on the rack (2026-11-13,
# /archive/datasets/bam_rig/rack_2026-11-13/wrist_home_v1/wrist_home_v1_172448.json: servo.pid_position.kp 15.0, kd 0.15 on CAN 14-16);
# at kp 15 the real wrist rested -8.6 / +5.3 / +14.4 deg off "0" under gravity, which the twin must reproduce (fullarm_check)
WRIST_KP_NM_PER_REV = 15.0
WRIST_KD_NM_PER_REV_S = 0.15
AS_FOUND_1024 = (WRIST_KP_NM_PER_REV, WRIST_KD_NM_PER_REV_S)  # what wrist_home_v1 read at 10:24 (the replay's gains)
# WHY the default moved to 75 / 0.75 (the Sim to Real Agent, 2026-11-13 ~11:30): the rack's wrist and claw boards now run kp 75 / kd 0.75
# in RAM (re-homed 11:24, /archive/datasets/bam_rig/full_arm/homed/latest.json); the 10:24 replay keeps the gains that run had
WRIST_GAINS_NOW = (75.0, 0.75)
WRIST_MAX_NM = fh.WRIST_MAX_NM  # 2 A x 0.5087 N.m/A
WRIST_KT_NM_PER_A = 0.5087
FIVEBAR_KT_NM_PER_A = 0.64  # 60ASM400 + 10:1 at the output (fullarm_home.FIVEBAR_BRAKE_NM_S's WHY)
# The claw (MG4005-10 on CAN 17): no board record exists in bam_ws. A soft PD at the output; the commands cap it (claw_jog's 0.3 N.m).
CLAW_KP_NM_PER_RAD = 6.0
CLAW_KD_NM_S = 0.05
CLAW_MAX_NM = 0.5
CLAW_BRAKE_NM_S = 0.02  # the claw board's shorted-phase drag (MG4005-10: assumption, Kt_out^2 / R ~ 1^2 / 50 at the output)
CLAW_KT_NM_PER_A = 0.1  # display only: current = torque / Kt (an MG4005-10's ~0.1 N.m/A at the output: assumption)
KT_NM_PER_A = {J1: FIVEBAR_KT_NM_PER_A, J2: FIVEBAR_KT_NM_PER_A, C1: FIVEBAR_KT_NM_PER_A, W1: WRIST_KT_NM_PER_A,
               W2: WRIST_KT_NM_PER_A, W3: WRIST_KT_NM_PER_A, CLAW: CLAW_KT_NM_PER_A}
BOARD_MAX_NM = {J1: 12.0, J2: 12.0, C1: 12.0, W1: WRIST_MAX_NM, W2: WRIST_MAX_NM, W3: WRIST_MAX_NM, CLAW: CLAW_MAX_NM}
# the runaway stop (real_plant.RUNAWAY_RAD_S, 86 deg/s) on the powered five-bar drives, as the real runner trips (mujoco_plant.RUNAWAY_JOINTS).
# WHY not on the wrist: a held wrist on a swinging L2 moves relative to it (100 deg/s at kp 15 during C1's seek, sim) without its board
# running away, and the rack runner has no wrist trip; the harness REPORTS every joint's powered peak against WRIST_SPEED_CEILING instead.
RUNAWAY_RAD_S = 1.5
RUNAWAY_JOINTS = (J1, J2, C1)
WRIST_SPEED_CEILING_RAD_S = 1.5

# -- the hidden truths -----------------------------------------------------------------------------------------------------------------
GEAR_RATIO = {W1: 10.0, W2: 10.0, W3: 10.0, CLAW: 10.0}  # GIM4305-10, MG4005-10 (the claw's 10:1 is the part name's)
TURN_RAD = {j: TAU / r for j, r in GEAR_RATIO.items()}  # one rotor turn at the output: 36 deg
ROTOR_PHASE_DEG = {W1: 7.3, W2: -11.1, W3: 3.9, CLAW: -5.2}  # each encoder's sub-turn offset: hidden truths (any values do)
FIVEBAR_HIDDEN_RAD = {J1: 0.31, J2: -1.7, C1: 2.6}  # gff_rung.HIDDEN_OFFSETS: nothing may assume the encoder reads the joint
# Hidden gear gaps (arcmin). The five-bar's are the homing rung's (plant.HIDDEN_GAP_ARCMIN, one truth with bam_fb_test_rig). The wrist's
# are an ASSUMPTION (no GIM4305-10 measurement in bam_ws): 12-18 arcmin, a small planetary's datasheet class. The claw carries none: its
# datum is the closed fingers, a single side, so no gap is observable there (PEP 0003).
WRIST_GAP_ARCMIN = {W1: 15.0, W2: 18.0, W3: 12.0}
WRIST_MESH_NM_PER_ARCMIN = 0.05  # a small planetary's torsional stiffness class (assumption): 1 N.m winds ~20 arcmin
BACKLASH_KINDS = ("B0", "B1", "B2")
BACKLASH_METHOD = {"B0": None, "B1": "deadzone", "B2": "passive_joint"}

# -- self-contact ----------------------------------------------------------------------------------------------------------------------
ARM_BODIES = ("base_link", "shoulder", "l1", "l2", "c1", "c2", "hard_stop", "hard_stop_2", "hard_stop_3", "moving_finger")
FIVEBAR_BODIES = ("base_link", "shoulder", "l1", "l2", "c1", "c2")
SELF_CONTACT_BIT = 2
SCENE_NAME = "sim2real_fullarm_contact_belt2"
# The belt (bam_fb_test_rig.model.Conveyor: top face at world z = 0, base_link 615 mm above it), here as a CONTACT for the arm's primitives:
# on the rack the claw rests on it when the arm hangs (the Sim to Real Agent, 2026-11-13 15:50), so a home must be judged with it there
BELT_CENTRE_M = (0.35, 0.04)
BELT_HALF_M = (0.225, 0.80, 0.25)  # WHY 0.5 m deep: a thin slab raised for the prop let the arm pass under it
BELT = "belt"
START_PENETRATION_M = 0.005  # a start may rest on the belt (contact), never sit 5 mm into it
# WHY a stiffer belt when asked (``belt_solref``; the homing routine's start grid, 2026-11-13): on MuJoCo's default soft contact (0.02 s) the
# limp arm crept ~0.6 deg/s along the belt and never came to rest in 10 s of settling - a rubber belt's static friction holds it. 2 ms (the
# stops' class, 8 physics steps) with the stops' solimp holds it still within 0.3 s.
BELT_STIFF_SOLREF = (0.002, 1.0)
BELT_STIFF_SOLIMP = (0.99, 0.999, 0.0001, 0.5, 2.0)  # bam_fb_test_rig STIFF.stop_solimp
BELT_AWAY_M = -10.0  # the belt's top when a plant is built without one


def contact_scene(scene: str = "scene.xml") -> Path:
    """The bundle's ``scene`` with the visual meshes out and the per-component primitives IN, colliding (module docstring). Written once
    beside the cache, never into the bundle."""
    import mujoco  # noqa: PLC0415

    root = fh.v2_root()
    out = fh.V2_CACHE / fh.V2_REF / SCENE_NAME / scene
    if not out.exists():
        spec = mujoco.MjSpec.from_file(str(root / "mjcf" / scene))
        named = {name for pair in spec.pairs for name in (pair.geomname1, pair.geomname2)}
        for geom in list(spec.geoms):
            if geom.name in named:
                continue
            if geom.group == 3 and geom.parent.name in ARM_BODIES:
                geom.contype, geom.conaffinity = SELF_CONTACT_BIT, SELF_CONTACT_BIT
                continue
            if geom.contype == 0 and geom.conaffinity == 0 and geom.parent.name != "world":
                spec.delete(geom)
        used = {geom.meshname for geom in spec.geoms if geom.meshname}
        for mesh in list(spec.meshes):
            if mesh.name not in used:
                spec.delete(mesh)
        spec.worldbody.add_geom(name=BELT, type=mujoco.mjtGeom.mjGEOM_BOX, size=BELT_HALF_M,
                                pos=(BELT_CENTRE_M[0], BELT_CENTRE_M[1], -BELT_HALF_M[2]), contype=SELF_CONTACT_BIT,
                                conaffinity=SELF_CONTACT_BIT, group=3, rgba=(0.16, 0.17, 0.18, 1.0))
        for a, b in itertools.combinations(FIVEBAR_BODIES, 2):
            exclude = spec.add_exclude()
            exclude.bodyname1, exclude.bodyname2 = a, b
        spec.meshdir = str(root / "urdf")
        spec.texturedir = str(root / "urdf")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(spec.to_xml())
    return out


def hidden_specs(kind: str) -> dict | None:
    """role -> gear_backlash BacklashSpec for ``kind`` (None for B0): the five-bar's and the wrist's hidden gaps."""
    if BACKLASH_METHOD[kind] is None:
        return None
    bam_ws_path()
    from bam_fb_test_rig.backlash import hidden_specs as fivebar_specs  # noqa: PLC0415

    specs = dict(fivebar_specs())
    specs.update(fivebar_specs({ROLE[j]: v for j, v in WRIST_GAP_ARCMIN.items()}, mesh_nm_per_arcmin=WRIST_MESH_NM_PER_ARCMIN))
    return specs


def hidden_backlash(kind: str) -> dict:
    """joint -> robot_models BacklashModel: the truth the metrics score. The five-bar's are the homing rung's (``plant.hidden_backlash``);
    the wrist's the same law on ``WRIST_GAP_ARCMIN`` / ``WRIST_MESH_NM_PER_ARCMIN``; the claw none."""
    from .plant import hidden_backlash as fivebar_backlash  # noqa: PLC0415

    out = dict(fivebar_backlash(kind))
    out.update(_wrist_backlash(kind))  # WHY not plant.hidden_backlash: it loops over the five-bar's DRIVES only
    out[CLAW] = BacklashModel("B0")
    return out


def _wrist_backlash(kind: str) -> dict:
    arcmin = math.radians(1.0 / 60.0)
    out = {}
    for joint in WRIST:
        gap = WRIST_GAP_ARCMIN[joint] * arcmin
        out[joint] = {"B0": BacklashModel("B0"), "B1": BacklashModel("B1", gap),
                      "B2": BacklashModel("B2", gap, 1.0 / (WRIST_MESH_NM_PER_ARCMIN / arcmin))}[kind]
    return out


_RIGS: dict = {}


def build_rig(kind: str = "B0", truth: str = "cad", *, wrist_friction: str = "sliding"):
    """The bam_fb_v2 twin with self-contact (``contact_scene``), the hidden gaps of ``kind`` and the masses of ``truth``
    (``fullarm_home.TRUTHS``). Cached per process."""
    key = (kind, truth, wrist_friction)
    if key not in _RIGS:
        bam_ws_path()
        from bam_fb_test_rig.model import STIFF, build_model  # noqa: PLC0415
        from bam_fb_test_rig.rig import DRIVE_FRICTIONLOSS_NM  # noqa: PLC0415

        if kind not in BACKLASH_KINDS:
            raise ValueError(f"kind must be one of {BACKLASH_KINDS}, not {kind!r}")
        wrist = fh.WRIST_COULOMB_NM if wrist_friction == "sliding" else fh.WRIST_BREAKAWAY_NM
        friction = {"J1": DRIVE_FRICTIONLOSS_NM, "J2": DRIVE_FRICTIONLOSS_NM, "C1": DRIVE_FRICTIONLOSS_NM, **wrist}
        bundle = replace(fh.load_v2_bundle(), mjcf_path=contact_scene())
        specs = hidden_specs(kind)
        kwargs = {} if specs is None else {"backlash": specs, "backlash_method": BACKLASH_METHOD[kind]}
        if specs is None:
            kwargs["backlash"] = None
        rig = build_model(bundle, STIFF, mount=fh.v2_mount(), conveyor=None, frictionloss=friction, **kwargs)
        claw = rig.model.joint(CLAW)
        rig.model.dof_frictionloss[rig.model.jnt_dofadr[claw.id]] = fh.CLAW_FRICTION_NM
        rig.truth = fh.apply_truth(rig, truth)
        _RIGS[key] = rig
    return _RIGS[key]


def wrap_turn(value: float, turn: float) -> float:
    """``value`` into [-turn/2, turn/2): what a board reads at power-on, one rotor turn's worth."""
    return (value + 0.5 * turn) % turn - 0.5 * turn


# -- the prior ------------------------------------------------------------------------------------------------------------------------

STOP_MARGIN_RAD = math.radians(0.5)


def cad_stops() -> StopMap:
    """Every stop side bam_fb_v2's stops.json gives (CAD, own-frame and interference), for the seven joints."""
    import json  # noqa: PLC0415

    document = json.loads((fh.v2_root() / "stops.json").read_text())
    sides = [StopSide(s["joint"], int(s["side"]), float(s["q_rad"]), "cad", f"bam_fb_v2 stops.json @ cad-exporter {fh.V2_REF}",
                      (s["moving_link"], s["fixed_link"])) for s in document["stops"] if s["joint"] in JOINTS]
    return StopMap(tuple(sides), source=f"bam_fb_v2 stops.json @ {fh.V2_REF}")


@dataclass(frozen=True)
class ArmPrior(Prior):
    """PEP 0002's ``Prior`` plus what a full-arm procedure may know about the encoders: each wrist/claw board's sub-turn ``rotor_phase``
    (rad; the calibration's, never the plant's) and its rotor turn at the output (``turn``). With them a stall's reading says whether
    the joint can be on the stop it seeks (``witness``)."""

    rotor_phase: Mapping[str, float] = field(default_factory=dict)
    turn: Mapping[str, float] = field(default_factory=dict)


def arm_prior(table=None, *, phase_error_deg: float = 0.0, rotor_phase_deg: Mapping[str, float] | None = None) -> ArmPrior:
    """The procedures' prior: CAD stops, every joint, the rotor phases as calibrated (``phase_error_deg`` adds a calibration error;
    ``rotor_phase_deg`` is the calibration of a plant given other phases than ``ROTOR_PHASE_DEG``)."""
    phases = ROTOR_PHASE_DEG if rotor_phase_deg is None else rotor_phase_deg
    return ArmPrior(stops=cad_stops(), joints=JOINTS, seek_side={J1: +1, J2: +1, C1: +1, W1: +1, W2: -1, W3: +1, CLAW: -1},
                    table=table, caps_nm=dict(BOARD_MAX_NM),
                    rotor_phase={j: math.radians(v + phase_error_deg) for j, v in phases.items()}, turn=dict(TURN_RAD))


# -- starts ---------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmStart:
    """Where an episode begins: the five-bar at Craig (j2, c1) on knee ``knee``, J1 at ``j1_deg``, the wrist at ``wrist_deg`` (W1, W2,
    W3) and the claw at ``claw_deg``; ``gap_fraction`` places each motor in its gear gap (-1..1). ``family`` groups starts on a page."""

    name: str
    j2_deg: float
    c1_deg: float
    wrist_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    claw_deg: float = 30.0
    knee: int = -1
    j1_deg: float = 0.0
    family: str = "grid"
    gap_fraction: Mapping[str, float] = field(default_factory=dict)


def hanging_start(plant: "FullArmHomingPlant", name: str = "hanging on the belt", *, wrist_deg=(0.0, 0.0, 0.0), claw_deg: float = 5.0,
                  family: str = "hanging") -> ArmStart:
    """The rack's power-up rest (the Sim to Real Agent, 15:50): the five-bar hanging straight down, the claw resting on the belt (or the
    prop, ``plant.belt_top_m``). Found as the closest five-bar pose to the homed map's home whose arm clears the belt (Craig J2 stepped
    0.5 deg at a time, both ways), which ``reset`` then lets fall onto it unpowered."""
    home = (91.01, -126.438)
    model = plant.rig.model
    model.geom_pos[model.geom(BELT).id][2] = plant.belt_top_m - BELT_HALF_M[2]
    for step in range(0, 241):
        for sign in (+1, -1):
            start = ArmStart(name, home[0] + sign * 0.5 * step, home[1], tuple(wrist_deg), claw_deg, family=family)
            try:
                plant.place(start)
            except StartRefused:
                continue
            return start
    raise StartRefused(f"{name}: no five-bar pose within 120 deg of home clears the belt")


class StartRefused(ValueError):
    """A start the twin cannot hold (the loop does not close, a joint past its stop, or the arm already in self-contact)."""


# -- the plant ------------------------------------------------------------------------------------------------------------------------


class FullArmHomingPlant:
    """robot_models ``HomingPlant`` for the whole bam_fb_v2 arm (module docstring). One instance per environment, ``reset`` per episode."""

    joint_names = JOINTS

    def __init__(self, kind: str = "B0", truth: str = "cad", *, cogging: bool = True, settle_s: float = 0.5,
                 runaway_rad_s: float | None = RUNAWAY_RAD_S, wrist_friction: str = "sliding", check_every: int = 1,
                 limp_brakes: bool = True, wrist_gains: tuple[float, float] = WRIST_GAINS_NOW, belt_top_m: float | None = None,
                 contact_timeconst_s: float | None = None, settle_all: bool = False, belt_solref: tuple[float, float] | None = None,
                 rotor_phase_deg: Mapping[str, float] | None = None, contact_timeconst_scope: str = "all", log_qpos: bool = True,
                 j1_rack: bool = False, j1_ff: bool = True):
        bam_ws_path()
        from bam_fb_test_rig.rig import board_signs  # noqa: PLC0415

        self.kind, self.truth_name = kind, truth
        self.rig = build_rig(kind, truth, wrist_friction=wrist_friction)
        self.signs = {**{r: board_signs(self.rig.bundle, self.rig)[r] for r in ("J1", "J2", "C1")}, "W1": 1.0, "W2": 1.0, "W3": 1.0}
        self.backlash = hidden_backlash(kind)
        self.cogging_on = cogging
        self.settle_s = float(settle_s)
        self.runaway_rad_s = None if runaway_rad_s is None else float(runaway_rad_s)
        self.check_every = int(check_every)
        # WHY a limp wrist / claw is BRAKED by default: a board the host is not commanding times out into its record's timeout mode 15
        # (phases shorted: a viscous drag, fullarm_home.WRIST_BRAKE_NM_S) - what the wrist does while a five-bar runner that never talks to
        # it homes the shoulder; on the bus a "limp" wrist step is sent as moteus `d brake` (PEP 0047). False: `d stop` (mode 0, free).
        self.limp_brakes = bool(limp_brakes)
        self.wrist_gains = (float(wrist_gains[0]), float(wrist_gains[1]))  # kp N.m/rev, kd N.m/(rev/s)
        # the belt's top face (world z, m): 0 is the rack's belt; +0.10 stands in for the claw propped 10 cm off it (a prop under it the
        # whole run - Zach's prop, 2026-11-13). None (the default): no belt within reach - every sweep before 2026-11-13 16:00 ran so
        self.belt_top_m = BELT_AWAY_M if belt_top_m is None else float(belt_top_m)
        # WHY a knob (sim 2026-11-13 evening): with the exporter's 2 ms stop / loop pairs the five-bar kicks J2 to 142-324 deg/s leaving its
        # upper stops on some starts; at 10 ms it does not. None keeps the bundle's (every run before then).
        self.contact_timeconst_s = contact_timeconst_s
        # WHY a scope (the homing routine, 2026-11-13): the 10 ms that removes the five-bar's kick, applied to EVERY pair, also softens the
        # wrist's and the claw's stops - at 1 N.m a wrist stall then reads 0.06 deg past its stop (2 ms: 0.003) on B0. "fivebar" softens
        # only the pairs between five-bar bodies (its stops and its loop); "all" (the default) is every run before.
        if contact_timeconst_scope not in ("all", "fivebar"):
            raise ValueError(f"contact_timeconst_scope must be all or fivebar, not {contact_timeconst_scope!r}")
        self.contact_timeconst_scope = contact_timeconst_scope
        # WHY a switch (the homing routine's grid, 2026-11-13, a loaded machine): the whole pose every tick is only for a video; a sweep
        # without one keeps its workers ~1 GB lighter over a 100 s episode and its deep copies small
        self.log_qpos = bool(log_qpos)
        # WHY the rack's J1 (2026-11-14): J1's own board gains (kp 200) and the CAD's gravity were neither the arm's. ``j1_rack``: J1 runs
        # the rack's kp x14 / kd x16.8 with no integrator, its gravity feed-forward computed every tick from the angle (as arm_hold and
        # every J1 tool send it, from power-up), and the twin's J1 feels the measured READY gravity instead of the CAD's (module WHY).
        # ``j1_ff`` False: that feed-forward off (the adversarial seed of a seek run without it - the rack's 22:54 gravity stall).
        self.j1_rack, self.j1_ff = bool(j1_rack), bool(j1_ff)
        # WHY the function and the two scales, not the module: the plant is deep-copied after phase 0 (routine_check's branching), and a
        # module object does not copy
        gains = j1_rack_gains() if self.j1_rack else None
        self._j1_gravity = gains.j1_gravity_nm if gains else None
        self._j1_scales = (float(gains.J1_KP_SCALE), float(gains.J1_KD_SCALE)) if gains else (1.0, 1.0)
        # WHY settle_all (the homing routine's start grid, 2026-11-13): a start is where the arm was when the power went; the WHOLE arm then
        # falls (onto the belt, its stops or itself) before power-on - the five-bar's drives are unpowered too - so power-on waits until every
        # joint is still, not only the wrist. False: the wrist's stillness only (every sweep before then).
        self.settle_all = bool(settle_all)
        self.belt_solref = None if belt_solref is None else (float(belt_solref[0]), float(belt_solref[1]))
        # the boards' sub-turn offsets (hidden truths): ROTOR_PHASE_DEG unless a perturbation draws another power-up frame
        self.rotor_phase_deg = dict(ROTOR_PHASE_DEG if rotor_phase_deg is None else rotor_phase_deg)
        model = self.rig.model
        self.claw_qadr = int(model.jnt_qposadr[model.joint(CLAW).id])
        self.claw_dof = int(model.jnt_dofadr[model.joint(CLAW).id])
        self.self_geoms = np.flatnonzero(model.geom_contype == SELF_CONTACT_BIT)
        self._is_self = np.zeros(model.ngeom, dtype=bool)
        self._is_self[self.self_geoms] = True
        self.sim = None
        self.time = 0.0
        self.log: dict = {}

    # -- frames ---------------------------------------------------------------------------------------------------------------------

    def _motor(self, joint: str) -> float:
        """The motor side, output referred, URDF frame (truth)."""
        if joint == CLAW:
            return float(self.sim.data.qpos[self.claw_qadr])
        return self.sim.joint_rad(ROLE[joint])

    def _link(self, joint: str) -> float:
        if joint == CLAW:
            return float(self.sim.data.qpos[self.claw_qadr])
        return self.sim.link_rad(ROLE[joint])

    def _motor_vel(self, joint: str) -> float:
        if joint == CLAW:
            return float(self.sim.data.qvel[self.claw_dof])
        return self.sim.joint_vel(ROLE[joint])

    def _torque(self, joint: str) -> float:
        """Output torque in the URDF joint frame."""
        if joint == CLAW:
            return self._claw_torque
        return self.signs[ROLE[joint]] * self.sim.states[ROLE[joint]].torque_nm

    # -- placing a start ------------------------------------------------------------------------------------------------------------

    def place(self, start: ArmStart) -> np.ndarray:
        """``start``'s closed pose on this twin (``fullarm_home.place`` for the five-bar), refused where the arm would sit in self-contact."""
        import mujoco  # noqa: PLC0415

        # WHY here too, not only in reset (2026-11-13): the model is cached per process and shared by every plant on the same rig, so the
        # belt's height is this plant's state - a place() before this plant's first reset read whatever the last plant left there
        self.rig.model.geom_pos[self.rig.model.geom(BELT).id][2] = self.belt_top_m - BELT_HALF_M[2]

        five = fh.FullStart(start.name, start.j2_deg, start.c1_deg, start.knee, start.wrist_deg, False, start.family, start.j1_deg)
        try:
            q, depth = fh.place(self.rig, five)
        except ValueError as error:
            raise StartRefused(str(error)) from error
        q = np.array(q, dtype=float)
        q[self.claw_qadr] = math.radians(start.claw_deg)
        for joint, value in zip(WRIST, start.wrist_deg, strict=True):
            low, high = self.rig.model.jnt_range[self.rig.model.joint(joint).id]
            if not low + STOP_MARGIN_RAD <= math.radians(value) <= high - STOP_MARGIN_RAD:
                raise StartRefused(f"{start.name}: {ROLE[joint]} at {value:.1f} deg is past its stop")
        data = mujoco.MjData(self.rig.model)
        data.qpos[:] = q
        mujoco.mj_forward(self.rig.model, data)
        touching = self.self_contacts(data)
        if touching:
            raise StartRefused(f"{start.name}: the arm would start in self-contact ({', '.join(touching)})")
        into = [c for c in self.contacts(data, deeper_than_m=START_PENETRATION_M) if c.startswith(BELT + "/")]
        if into:
            raise StartRefused(f"{start.name}: the arm would start more than {START_PENETRATION_M * 1e3:.0f} mm into the belt ({', '.join(into)})")
        return q

    def contacts(self, data=None, *, deeper_than_m: float = 0.0) -> list[str]:
        """Every contact between two arm bodies' primitives, or an arm body and the belt, in ``data``: 'body/body' or 'belt/body'
        (sorted, unique), counting only those deeper than ``deeper_than_m``."""
        data = self.sim.data if data is None else data
        model = self.rig.model
        out = set()
        for i in range(data.ncon):
            contact = data.contact[i]
            if self._is_self[contact.geom1] and self._is_self[contact.geom2] and contact.dist < -deeper_than_m:
                names = []
                for geom in (contact.geom1, contact.geom2):
                    body = model.body(model.geom_bodyid[geom]).name
                    names.append(BELT if body == "world" else body)
                out.add("/".join(sorted(names, key=lambda n: (n != BELT, n))))
        return sorted(out)

    def self_contacts(self, data=None) -> list[str]:
        """Arm-on-arm contacts only (the belt's are ``belt_contacts``)."""
        return [c for c in self.contacts(data) if not c.startswith(BELT + "/")]

    def belt_contacts(self, data=None) -> list[str]:
        return [c for c in self.contacts(data) if c.startswith(BELT + "/")]

    def reset(self, start: ArmStart) -> JointState:
        import mujoco  # noqa: PLC0415

        bam_ws_path()
        from bam_fb_test_rig.sim import BoardConfig, Drive, RigSim  # noqa: PLC0415

        model = self.rig.model
        model.geom_pos[model.geom(BELT).id][2] = self.belt_top_m - BELT_HALF_M[2]  # the model is cached per process: set every reset
        belt = model.geom(BELT).id
        if not hasattr(self.rig, "_belt_sol0"):
            self.rig._belt_sol0 = (model.geom_solref[belt].copy(), model.geom_solimp[belt].copy())
        model.geom_solref[belt], model.geom_solimp[belt] = self.rig._belt_sol0
        if self.belt_solref is not None:
            model.geom_solref[belt] = self.belt_solref
            model.geom_solimp[belt] = BELT_STIFF_SOLIMP
        # WHY the originals on the rig, not the plant (2026-11-13): the model is cached per process and shared by every plant on the same
        # rig, so a second plant would have kept the first plant's edited contacts as "the bundle's" and never put them back
        if not hasattr(self.rig, "_pair_solref0"):
            self.rig._pair_solref0 = model.pair_solref.copy()
        model.pair_solref[:] = self.rig._pair_solref0
        if self.contact_timeconst_s is not None:
            if self.contact_timeconst_scope == "all":
                model.pair_solref[:, 0] = self.contact_timeconst_s
            else:
                fivebar = {model.body(b).id for b in FIVEBAR_BODIES}
                for k in range(model.npair):
                    bodies = {int(model.geom_bodyid[model.pair_geom1[k]]), int(model.geom_bodyid[model.pair_geom2[k]])}
                    if bodies <= fivebar | {0}:
                        model.pair_solref[k, 0] = self.contact_timeconst_s
        q = self.place(start)
        boards = real_boards()
        if self.j1_rack:
            kp_scale, kd_scale = self._j1_scales
            boards["J1"] = replace(boards["J1"], kp=boards["J1"].kp * kp_scale, kd=boards["J1"].kd * kd_scale, ki=0.0, ilimit=0.0)
        wrist_board = BoardConfig(kp=self.wrist_gains[0], ki=0.0, kd=self.wrist_gains[1], ilimit=0.0, max_torque_nm=WRIST_MAX_NM)
        drives = [Drive(r, self.signs[r], boards[r]) for r in ("J1", "J2", "C1")] + [Drive(r, 1.0, wrist_board) for r in ("W1", "W2", "W3")]
        sim = RigSim(self.rig, tuple(drives), log_hz=1e-6)
        if self.rig.backlash is not None:
            wrapped = self.rig.backlash
            sim.data.qpos[:] = q  # fullarm_home.place closes the loop on this (wrapped) twin: its layout already
            link = wrapped.link_qpos(sim.data)
            twist = {name: float(start.gap_fraction.get(name, 0.0)) * 0.5 * wrapped.joints[name].spec.total_gap_rad
                     for name in wrapped.joints}
            wrapped.set_state(sim.data, link, None, twist)
        else:
            sim.data.qpos[:] = q
        sim.data.qvel[:] = 0.0
        mujoco.mj_forward(self.rig.model, sim.data)
        self.sim = sim
        self.cogging = {r: v for r, v in cogging_terms(self.rig).items() if r in ("J2", "C1")} if self.cogging_on else {}
        self.claw_command: dict | None = None
        self._claw_torque = 0.0
        self._claw_ramp: float | None = None
        sim.pre_step = self._pre_step
        sim.power_up({r: self.signs[r] * sim.joint_rad(r) for r in self.signs})  # boards read sign x motor; our frame is below
        # The arm at power-on is AT REST where it was left: the five-bar unpowered (J1 held: hold_j1), the wrist braked (its record's
        # timeout mode) on its BREAKAWAY friction (0.14-0.19 N.m: static friction holds a wrist whose gravity is under it), stepped until
        # the wrist and the claw have been still 0.3 s (at most ``settle_s`` + 5 s). WHY until still: a wrist placed where its gravity beats
        # its static friction is not a power-on rest; it sags (to its stop, or to where friction holds) before any board is powered - a
        # start must be a pose the real arm can be found in (the first powered tick of a sagging wrist read 110 deg/s, a false runaway).
        self._brake = {r: fh.WRIST_BRAKE_NM_S for r in ("W1", "W2", "W3")}
        wrist_dofs = [self.rig.dof_adr(r) for r in ("W1", "W2", "W3")] + [self.claw_dof]
        sliding = model.dof_frictionloss[wrist_dofs].copy()
        model.dof_frictionloss[[self.rig.dof_adr(r) for r in ("W1", "W2", "W3")]] = [fh.WRIST_BREAKAWAY_NM[r] for r in ("W1", "W2", "W3")]
        sim.hold("J1", fh.J1_HOLD_CAP_NM)  # hold_j1: J1 is held from power-on in the real form, never homed
        try:
            if self.settle_s > 0:
                sim.step(self.settle_s)
                still, waited = 0.0, 0.0
                watched = slice(None) if self.settle_all else wrist_dofs
                limit = 10.0 if self.settle_all else 5.0
                while still < 0.3 and waited < limit:
                    sim.step(0.05)
                    waited += 0.05
                    still = still + 0.05 if float(np.max(np.abs(sim.data.qvel[watched]))) < 0.01 else 0.0
                self.settle_waited_s = waited
        finally:
            model.dof_frictionloss[wrist_dofs] = sliding
        sim.stop("J1")
        self._brake = {}
        sim.data.time = 0.0
        self.time = 0.0
        self.hidden = {}
        for joint in JOINTS:
            motor = self._motor(joint)
            if joint in FIVEBAR:
                self.hidden[joint] = FIVEBAR_HIDDEN_RAD[joint]
            else:
                raw = wrap_turn(motor + math.radians(self.rotor_phase_deg[joint]), TURN_RAD[joint])
                self.hidden[joint] = motor - raw  # raw = motor - hidden
        self.frame = {j: 0.0 for j in JOINTS}
        self.start = start
        self.start_settled_deg = {ROLE[j]: round(math.degrees(self._link(j)), 3) for j in JOINTS}
        self.start_belt = self.belt_contacts()  # what rests on the belt at power-on
        self._velocity = {j: 0.0 for j in JOINTS}
        self.peak_powered_rad_s = {j: 0.0 for j in JOINTS}
        self.peak_torque_nm = {j: 0.0 for j in JOINTS}
        self.log = {"t": [], "link": [], "motor": [], "position": [], "effort": [], "setpoint": [], "self_contact": [], "belt_contact": [],
                    "qpos": []}
        self._record(None)
        return self.state()

    def _expand(self, q: np.ndarray) -> np.ndarray:
        """A B0 pose (the unwrapped joint layout) into the wrapped model's qpos (gear joints at zero twist): by joint name."""
        model = self.rig.model
        b0 = build_rig("B0", self.truth_name).model
        out = model.qpos0.copy()
        for j in range(b0.njnt):
            name = b0.joint(j).name
            out[model.jnt_qposadr[model.joint(name).id]] = q[b0.jnt_qposadr[j]]
        return out

    # -- physics hooks --------------------------------------------------------------------------------------------------------------

    def j1_gravity_hold_nm(self, data, *, shoulder_only: bool = False) -> float:
        """J1's gravity hold torque on the twin's CAD masses (N.m, URDF frame, MuJoCo's qfrc_bias convention at rest): from the subtree
        J1 carries, or only the shoulder body's own mass."""
        model = self.rig.model
        shoulder = model.body("shoulder").id
        joint = model.joint(J1).id
        if shoulder_only:
            mass, com = float(model.body_mass[shoulder]), data.xipos[shoulder]
        else:
            mass, com = float(model.body_subtreemass[shoulder]), data.subtree_com[shoulder]
        lever = np.asarray(com) - np.asarray(data.xanchor[joint])
        return -float(np.dot(data.xaxis[joint], np.cross(lever, mass * np.asarray(model.opt.gravity))))

    def j1_measured_gravity_nm(self, data) -> float:
        """J1's hold torque as the rack measured it at READY (j1_gains.j1_gravity_nm on the rack's board frame), at the twin's J1."""
        q1 = float(data.qpos[self.rig.qpos_adr("J1")])
        return float(self._j1_gravity(q1 + J1_RACK_ZERO_BOARD_RAD))

    def _pre_step(self, data) -> None:
        if self.j1_rack:
            # the measured gravity in place of the CAD's: a joint torque that makes J1's hold torque J1_POSE_FIT's
            data.qfrc_applied[self.rig.dof_adr("J1")] += self.j1_gravity_hold_nm(data) - self.j1_measured_gravity_nm(data)
        for role, (ripple, sign, offset) in self.cogging.items():
            q = float(data.qpos[self.rig.qpos_adr(role)])
            data.qfrc_applied[self.rig.dof_adr(role)] -= sign * float(ripple.torque_nm(sign * q + offset))
        for role, drag in self._brake.items():
            dof = self.claw_dof if role == "CLAW" else self.rig.dof_adr(role)
            data.qfrc_applied[dof] -= drag * float(data.qvel[dof])
        # the claw's board: a PD on its target (ramped at the command's speed), capped
        command = self.claw_command
        if command is None:
            self._claw_torque = 0.0
            return
        dt = self.rig.model.opt.timestep
        if self._claw_ramp is None:
            self._claw_ramp = float(data.qpos[self.claw_qadr])
        error = command["target"] - self._claw_ramp
        self._claw_ramp += math.copysign(min(abs(error), command["speed"] * dt), error)
        torque = CLAW_KP_NM_PER_RAD * (self._claw_ramp - float(data.qpos[self.claw_qadr])) - CLAW_KD_NM_S * float(data.qvel[self.claw_dof])
        torque += command["feedforward"]
        cap = min(command["cap"], CLAW_MAX_NM)
        self._claw_torque = float(np.clip(torque, -cap, cap))
        data.qfrc_applied[self.claw_dof] += self._claw_torque

    # -- the seam -------------------------------------------------------------------------------------------------------------------

    def raw(self, joint: str) -> float:
        return self._motor(joint) - self.hidden[joint]

    def tick(self, command: ServoCommand, dt: float, defines: Mapping[str, float] | None = None) -> JointState:
        from moteus_servo import MoteusCommand  # noqa: PLC0415

        if abs(dt - CONTROL_DT) > 1e-12:
            raise ValueError(f"this plant steps {CONTROL_DT} s per tick")
        for joint, value in (defines or {}).items():
            self.frame[joint] = float(value) - self.raw(joint)
        index = {name: i for i, name in enumerate(command.name)}
        size = len(command.name)
        cap = np.zeros(size) if command.max_effort is None else np.asarray(command.max_effort, dtype=float)
        feedforward = np.zeros(size) if command.feedforward_effort is None else np.asarray(command.feedforward_effort, dtype=float)
        velocity = np.zeros(size) if command.velocity is None else np.asarray(command.velocity, dtype=float)
        targets: dict = {}
        before = {j: self._motor(j) for j in JOINTS}
        for joint in JOINTS:
            i = index.get(joint)
            position = math.nan if i is None else float(command.position[i])
            powered = i is not None and cap[i] > 0.0 and math.isfinite(position)
            target = position - self.frame[joint] + self.hidden[joint] if powered else None  # the true motor angle (URDF)
            targets[joint] = target
            if joint in WRIST or joint == CLAW:
                role = ROLE[joint]
                if not powered and self.limp_brakes:
                    self._brake[role] = CLAW_BRAKE_NM_S if joint == CLAW else fh.WRIST_BRAKE_NM_S
                else:
                    self._brake.pop(role, None)
            if joint == CLAW:
                if not powered:
                    self.claw_command, self._claw_ramp = None, None
                else:
                    # WHY no ramp of our own beyond one tick: the sequence controller already ramps the setpoint at the step's speed
                    self.claw_command = {"target": target, "speed": max(abs(float(velocity[i])) * 2.0, 0.5), "cap": float(cap[i]),
                                         "feedforward": float(feedforward[i])}
                continue
            role = ROLE[joint]
            if not powered:
                self.sim.stop(role)
                continue
            sign = self.signs[role]
            self.sim.states[role].ramp_target_rad = None
            # WHY ilimit_scale 0 and no velocity target (mujoco_plant.MujocoRigPlant.tick): the boards run as PDs on the setpoint the
            # sequence controller ramps, as the rack runner's adapter sends them
            ff = float(feedforward[i])
            if self.j1_rack and joint == J1:
                # the rack's J1 feed-forward, every tick from J1's angle (arm_hold and every J1 tool), or none (the adversarial seed)
                ff = float(self._j1_gravity(self._link(J1) + J1_RACK_ZERO_BOARD_RAD)) if self.j1_ff else 0.0
            self.sim._send(role, MoteusCommand(position_rad=sign * target, feedforward_torque_nm=sign * ff,
                                               ilimit_scale=0.0, maximum_torque_nm=float(min(cap[i], BOARD_MAX_NM[joint]))))
        self.sim.step(dt)
        self.time += dt
        for joint in JOINTS:
            self._velocity[joint] = (self._motor(joint) - before[joint]) / dt
        self._record(targets)
        self._check_runaway(targets)
        return self.state()

    def _check_runaway(self, targets: Mapping[str, float | None]) -> None:
        for joint in JOINTS:
            if targets.get(joint) is None:
                continue
            speed = abs(self._velocity[joint])
            self.peak_powered_rad_s[joint] = max(self.peak_powered_rad_s[joint], speed)
            if joint in RUNAWAY_JOINTS and self.runaway_rad_s is not None and speed > self.runaway_rad_s:
                raise PlantTrip(f"runaway: {ROLE[joint]} at {math.degrees(speed):.0f} deg/s powered, over "
                                f"{math.degrees(self.runaway_rad_s):.0f} deg/s at t {self.time:.2f} s", kind="runaway", joint=ROLE[joint],
                                speed_rad_s=speed, time_s=self.time)

    def state(self) -> JointState:
        return JointState(name=JOINTS, position=np.array([self.raw(j) + self.frame[j] for j in JOINTS]),
                          velocity=np.array([self._velocity[j] for j in JOINTS]),
                          effort=np.array([self._torque(j) for j in JOINTS]), header=Header(stamp=self.time))

    def truth(self) -> dict:
        return {"time_s": self.time, "link_rad": {j: self._link(j) for j in JOINTS}, "motor_rad": {j: self._motor(j) for j in JOINTS},
                "true_offset_rad": dict(self.hidden), "frame_rad": dict(self.frame), "backlash": dict(self.backlash),
                "start_settled_deg": dict(self.start_settled_deg), "kind": self.kind, "truth": self.truth_name,
                "start_belt": list(getattr(self, "start_belt", [])), "settle_waited_s": getattr(self, "settle_waited_s", None)}

    def _stops_touching(self) -> list[str]:
        contacts = self.rig.stop_contacts(self.sim.data)
        return sorted(key for key, force in contacts.items() if force > 0.0)

    def _record(self, targets) -> None:
        for joint in JOINTS:
            self.peak_torque_nm[joint] = max(self.peak_torque_nm[joint], abs(self._torque(joint)))
        log = self.log
        log["t"].append(self.time)
        log["link"].append([self._link(j) for j in JOINTS])
        log["motor"].append([self._motor(j) for j in JOINTS])
        log["position"].append([self.raw(j) + self.frame[j] for j in JOINTS])
        log["effort"].append([self._torque(j) for j in JOINTS])
        log["setpoint"].append([math.nan if not targets or targets.get(j) is None else targets[j] for j in JOINTS])
        if self.log_qpos:
            log["qpos"].append(self.sim.data.qpos.copy())  # the whole pose, for a video of the run (fullarm_check.trace_of)
        tick = len(log["t"]) - 1
        every = self.contacts() if tick % self.check_every == 0 else []
        log["self_contact"].append([c for c in every if not c.startswith(BELT + "/")])
        log["belt_contact"].append([c for c in every if c.startswith(BELT + "/")])


__all__ = ["ARM_BODIES", "CAN", "CLAW", "C1", "FIVEBAR", "J1", "J2", "JOINTS", "ROLE", "ROTOR_PHASE_DEG", "TURN_RAD", "W1", "W2", "W3",
           "WRIST", "ArmPrior", "ArmStart", "FullArmHomingPlant", "StartRefused", "arm_prior", "build_rig", "cad_stops", "contact_scene",
           "hanging_start", "hidden_backlash", "wrap_turn"]
