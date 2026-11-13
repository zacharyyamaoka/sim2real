"""The five-bar's home button with the FULL ARM on it (bam_fb_v2: five-bar + UR wrist + crab claw), on the MuJoCo rung - sim only, 2026-11-13.

Two questions, for Zach's next powered home (the coordinator's brief):

1. **Which gravity comp.** ``fivebar_home -f`` feeds every walk-home waypoint and every hold the static gravity of the mass ID's lumped model
   (bam_rack_twin ``DEFAULT_COMP``, massid_real_093852: the 2.5 lb plate on L2). With the UR wrist and the claw on L2 instead, is that comp,
   ``--nominal-comp`` (bam_fivebar's bench: the plate again, at CAD), or a comp from the bam_fb_v2 masses the one that gets home?
2. **What the wrist's boards do meanwhile** (CAN 14/15/16, GIM4305-10 on moteus c1): hold where they are at a low kp, go limp, or be left
   untouched (at power-on a moteus board is mode 0, stopped: limp; after a host that commanded it dies it is the record's timeout mode 15,
   brake). A limp wrist is a pendulum on the end of L2: W1's axis is parallel to the five-bar's, so it swings in the plane as L2 turns.

**The twin is the bam_fb_v2 bundle itself** (cad-exporter 09374d7, Fusion "BAM Five Bar Arm w/ Crab Claw (Test Rig Nov 13 2026)" v4, 10 links
15.304 kg), through bam_fb_test_rig's ``build_model``: the loop as the exporter's ``connect``, every stop and loop contact as the exporter's
own pairs (``mjcf/scene.xml``: 14 stop primitives + the five-bar's 59 loop-contact pairs), on the rack (``V2_MOUNT``). The five-bar's
drives are the homing rung's (``mujoco_plant``: the real board record, JMC cogging on J2 / C1, 0.74 N.m Coulomb, the CAD's 60ASM400
armature, J1 held at 7 N.m as ``hold_j1``); the wrist's three joints are the real wrist's (``WRIST_*``: 2 A = 1.02 N.m, the refit twin's
sliding Coulomb, the record's timeout brake). The claw's finger (revolute_5, CAN 17's MG4005) is passive with a small friction.

**The home button that runs is bam_ws's own code** - ``bam_fivebar_recovery.home.return_home`` over ``PlantBackend`` on bam_rack_twin's
``bench_real`` with the homed map's home, as ``fivebar_homed.run_home`` runs it (a stop on the way held and the home re-run, up to its
``HOME_ATTEMPTS``), then the release at home (``tview_run._release``: brake until still, then stop) - only the plant is this twin.

**Hidden truths** (``TRUTHS``; nothing the comp or the procedure reads): the CAD masses as exported; the claw assembly at the brief's
nominal 0.371 kg / high 0.50 kg (the export's L Gripper Plate v1.2 + Crab Claw Gripper v2.1 is 0.313 kg; the difference goes on the
gripper body at its centre of mass); the whole end group (L2 = the UR forearm, the wrist, the claw) x1.2249, the mass ID's CAD -> real
ratio on the plate rig's end group (mujoco_plant.END_GROUP_MASS_SCALE's WHY: the upper end, the case a feed-forward must survive).

**Comps** (``COMP_NAMES``): ``plate`` = DEFAULT_COMP (today's ``fivebar_home -f``), ``nominal`` = ``--nominal-comp``, ``bam_fb_v2`` = bam_ws
``records/fivebar-bench/gravity_params_bam_fb_v2.json`` (bam_rack_twin.fullarm_comp: the mass ID's comp with the end group swapped plate ->
bam_fb_v2, claw nominal, the hanging wrist a point mass on W1's axis), ``bam_fb_v2_cad`` = the same swap on the CAD bench (no mass-ID
corrections).

Run (the sweep the results file holds; MemoryMax keeps MemAvailable >= 8 GB on this machine):

    systemd-run --user --scope -q -p MemoryMax=12G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl SIM2REAL_BAM_WS_SRC=/home/bam/bam_ws/src /home/bam/sim2real/.venv/bin/python -m sim2real.sim.homing.fullarm_home --out /home/bam/sim2real/src/sim2real/data/fullarm_home_2026-11-13.json --workers 6

Every angle shown is in degrees; the arrays inside are SI.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .home_button import CONTROL_DT, Reading
from .mujoco_plant import BAM_WS_SRC, END_GROUP_MASS_SCALE, bam_ws_path, cogging_terms, real_boards

# ---------------------------------------------------------------------------------------------------------------------- the bundle

CAD_EXPORTER = Path("/home/bam/cad-exporter")
V2_REF = "09374d7"  # cad-exporter origin/claude/bam-fb-v2: "fixtures: bam_fb_v2, the full arm ..., stops.json all-pass"
V2_SUBDIR = "fixtures/cad2robot/bam_fb_v2"
V2_CACHE = Path.home() / ".cache" / "cad2robot-build" / "bundles"
# CAN id -> role. The five-bar's are bam_fb_test_rig's (PEP 0019); the wrist's are the bundle's own (revolute_11 / 14 / 17 = CAN 14 / 15 / 16).
# The claw's finger (revolute_5) has no CAN id in the bundle (CAN 17 is the working assumption, power_on_check.EXPECTED): it stays passive.
ROLES = {11: "J1", 12: "J2", 13: "C1", 14: "W1", 15: "W2", 16: "W3"}
WRISTS = ("W1", "W2", "W3")
CLAW_JOINT = "revolute_5"
# The end group: every body L2 carries (bam_fb_v2's l2 is the UR forearm welded to the five-bar's elbow link; the wrist and the claw beyond).
END_BODIES = ("l2", "hard_stop", "hard_stop_2", "hard_stop_3", "moving_finger")
GRIPPER_BODY = "hard_stop_3"  # wrist 3's output: the L Gripper Plate v1.2 (with the claw's motor) + Crab Claw Gripper v2.1's fixed finger


def v2_root() -> Path:
    """The bam_fb_v2 bundle, git-archived from the cad-exporter clone into the cache once (never a checkout, never a merge)."""
    root = V2_CACHE / V2_REF / V2_SUBDIR
    if not (root / "robot.json").exists():
        target = V2_CACHE / V2_REF
        target.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "-C", str(CAD_EXPORTER), "archive", V2_REF, V2_SUBDIR], check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout, check=True)
    return root


def v2_mount():
    """bam_fb_v2 on the rack. WHY this mount and not bam_fb_test_rig's RACK_MOUNT: the full arm's export frame is v11's turned -90 deg
    about y (the spine is -x, L1 hangs along -z at the export pose; every five-bar body offset is v11's rotated), so v11's rack rotation
    composed with +90 deg about y is a half turn about world z; the position puts the shoulder where v11's sits (0.019, 0, 0.615).
    ``tests/test_homing_fullarm.py`` holds l1 / l2 / c1 / c2 at v11's world positions and the Craig map equal to v11's."""
    bam_ws_path()
    from bam_fb_test_rig.model import Mount  # noqa: PLC0415

    return Mount(quat_wxyz=(0.0, 0.0, 0.0, 1.0), pos_m=(0.003, -0.11, 0.6505),
                 why="the real rack (bam_fb_test_rig RACK_MOUNT) for the bam_fb_v2 export frame: J1 level along world +x, the arm hanging "
                     "toward world -z, the five-bar's bodies where v11's are")


def stripped_scene(root: Path, scene: str = "scene.xml") -> Path:
    """The bundle's ``scene`` without its visual-only geoms (written once beside the cache, never into the bundle): every geom no ``<pair>``
    names and that collides with nothing goes, with the meshes no geom uses. WHY: the full arm's 2073 geoms are 1988 visual meshes; MuJoCo
    poses every geom every step, and the 85 left (the stops' and the loop's contact shapes) step 3.8x faster with the masses, inertias and
    contact pairs unchanged (bodies carry explicit inertials; ``tests/test_homing_fullarm.py`` holds them equal)."""
    import mujoco  # noqa: PLC0415

    out = V2_CACHE / V2_REF / "sim2real_stripped" / scene
    if not out.exists():
        spec = mujoco.MjSpec.from_file(str(root / "mjcf" / scene))
        named = {name for pair in spec.pairs for name in (pair.geomname1, pair.geomname2)}
        for geom in list(spec.geoms):
            if geom.name not in named and geom.contype == 0 and geom.conaffinity == 0 and geom.parent.name != "world":
                spec.delete(geom)
        used = {geom.meshname for geom in spec.geoms if geom.meshname}
        for mesh in list(spec.meshes):
            if mesh.name not in used:
                spec.delete(mesh)
        spec.meshdir = str(root / "urdf")
        spec.texturedir = str(root / "urdf")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(spec.to_xml())
    return out


def load_v2_bundle(scene: str = "scene.xml", *, strip: bool = True):
    bam_ws_path()
    from bam_fb_test_rig.bundle import load_bundle  # noqa: PLC0415

    root = v2_root()
    return replace(load_bundle(root, roles=ROLES), mjcf_path=stripped_scene(root, scene) if strip else root / "mjcf" / scene)


# ---------------------------------------------------------------------------------------------------------------------- the wrist

# The wrist's actuator (bam_ur_wrist.actuator.GIM4305 and the board record, bam_rack_twin records/ur-wrist-test-rig): 2 A flashed x 0.5087
# N.m/A at the output; the power-on check of 2026-11-13 15:40Z read servo.max_current_A 2.0 on CAN 14/15/16.
WRIST_MAX_NM = 1.02
# Sliding Coulomb per joint, N.m at the output (bam_ur_wrist coverage.REFIT_TWIN, the refit of record: CAN 14 the rack's card, CAN 15 / 16
# fitted). WHY sliding and not the breakaway (0.175 / 0.140 / 0.186, ``WRIST_BREAKAWAY_NM``): MuJoCo's frictionloss has one level, and the
# sliding level is the floppier limp wrist - the case the question is about. The breakaway is the sensitivity case (``wrist_friction``).
WRIST_COULOMB_NM = {"W1": 0.0413, "W2": 0.06565, "W3": 0.06113}
WRIST_BREAKAWAY_NM = {"W1": 0.175, "W2": 0.14015, "W3": 0.1858}
CLAW_FRICTION_NM = 0.05  # the claw's MG4005-10 back-driven (no measurement: an assumption, small against its 0.036 kg finger)
# The record's timeout mode 15 (brake: phases shorted) as a viscous drag at the output: Kt_out^2 / R = 0.5087^2 / 0.630 ohm (the record's
# resistance_ohm). WHY modelled at all: an "untouched" wrist whose last host died is braked, not limp.
WRIST_BRAKE_NM_S = 0.5087**2 / 0.630
FIVEBAR_BRAKE_NM_S = 0.64**2 / 0.0871  # the 60ASM400 + 10:1 shorted (0.64 N.m/A at the output, 0.0871 ohm): tview_run._release's brake


@dataclass(frozen=True)
class WristHold:
    """A wrist hold: moteus ``d pos nan 0 <cap>`` (hold where it is) at these gains, never a target of its own.

    WHY these numbers: kp 30 N.m/rev is a fifth of the board's flashed 145.1 (records/ur-wrist-test-rig) and 0.4 x the 75 the real wrist's
    homing and sways ran in RAM - soft, so a wrist that meets something yields at its cap - yet it holds the wrist's worst static gravity
    (0.42 N.m on W1, measured on this twin) to ~5 deg; kd 1.0 N.m/(rev/s) is the RAM gain CAN 15 / 16 run; the cap is the wrist bus
    plant's CEILING_NM (1.0 N.m, under the flashed 2 A)."""

    kp: float = 30.0
    kd: float = 1.0
    cap_nm: float = 1.0


WRIST_HOLD = WristHold()
WRIST_MODES = ("limp", "hold", "brake")
# The CAD's self-contact regions (the bundle's self_collision_wrist.json, its pairs_in_contact): the gripper body through the forearm
# (l2 / hard_stop_3) where |revolute_11| > 105 AND |revolute_14| > 105 deg, at every corner; the claw finger on wrist plate 1
# (hard_stop / moving_finger) where |rev14| > 130, |rev17| > 50 and |rev5| > 67 deg. Proven clear while |rev14| <= 95 (one joint at a time).
REGION_A_DEG = 105.0
REGION_B_DEG = (130.0, 50.0, 67.0)
WRIST_STOP_DEG = 169.851  # stops.json: every wrist joint's stop, both sides


def in_region_a(w1_deg: float, w2_deg: float) -> bool:
    return abs(w1_deg) > REGION_A_DEG and abs(w2_deg) > REGION_A_DEG


def in_region_b(w2_deg: float, w3_deg: float, claw_deg: float) -> bool:
    return abs(w2_deg) > REGION_B_DEG[0] and abs(w3_deg) > REGION_B_DEG[1] and abs(claw_deg) > REGION_B_DEG[2]


# ---------------------------------------------------------------------------------------------------------------------- the truths

CLAW_CAD_KG = 0.2454 + 0.0655 + 0.0018  # the export's L Gripper Plate v1.2 + Crab Claw Gripper v2.1 + the GIM43 circle marker (fusion360_data)
CLAW_BRACKET_KG = {"nominal": 0.371, "high": 0.50}  # the brief's (docs/pick_tracking/claw_payload.py CASES: CAD x 1.2249; + a bracket and slack)
TRUTHS = ("cad", "claw_nominal", "claw_high", "end+22%")
TRUTH_WHY = {
    "cad": "bam_fb_v2's masses as exported (end group 1.389 kg, the wrist + claw 0.924 kg beyond W1)",
    "claw_nominal": f"the claw assembly at 0.371 kg (CAD {CLAW_CAD_KG:.3f} kg): +{0.371 - CLAW_CAD_KG:.3f} kg on the gripper body",
    "claw_high": f"the claw assembly at 0.50 kg: +{0.50 - CLAW_CAD_KG:.3f} kg on the gripper body",
    "end+22%": "every end body (UR forearm, wrist, claw) x1.2249 at its own CoM: the plate rig's mass-ID CAD -> real ratio",
}


def _scale_body(model, body: str, scale: float) -> None:
    index = model.body(body).id
    model.body_mass[index] *= scale
    model.body_inertia[index] = model.body_inertia[index] * scale


def apply_truth(rig, truth: str) -> dict:
    """Edit the compiled twin's masses for ``truth`` (``TRUTH_WHY``) at each body's own CoM, then MuJoCo's mass constants. Returns the end
    group's mass before / after (kg)."""
    import mujoco  # noqa: PLC0415

    model = rig.model
    before = float(sum(model.body_mass[model.body(b).id] for b in END_BODIES))
    if truth in ("claw_nominal", "claw_high"):
        added = CLAW_BRACKET_KG[truth.removeprefix("claw_")] - CLAW_CAD_KG
        gripper = model.body(GRIPPER_BODY).id
        _scale_body(model, GRIPPER_BODY, (float(model.body_mass[gripper]) + added) / float(model.body_mass[gripper]))
    elif truth == "end+22%":
        for body in END_BODIES:
            _scale_body(model, body, END_GROUP_MASS_SCALE)
    elif truth != "cad":
        raise ValueError(f"truth must be one of {TRUTHS}, not {truth!r}")
    mujoco.mj_setConst(model, mujoco.MjData(model))
    return {"truth": truth, "end_group_kg": before, "end_group_truth_kg": float(sum(model.body_mass[model.body(b).id] for b in END_BODIES))}


_RIGS: dict = {}
V11_SHA = "8957130"  # bam_fb_test_rig.bundle.REAL_BUNDLE_SHA: the plate rig the home button ran on, the baseline twin
BASELINE_TRUTHS = ("plate", "plate+22%")


def build_baseline_rig(truth: str = "plate"):
    """The plate rig's v11 twin (bam_fb_test_rig ``bench_rig``, no hidden backlash), ``plate+22%`` = its end group x1.2249 (the mass ID's
    reading of the real plate arm, mujoco_plant.END_GROUP_MASS_SCALE): the home button's baseline on the starts the full arm runs."""
    key = ("v11", truth)
    if key not in _RIGS:
        bam_ws_path()
        from bam_fb_test_rig.bundle import bundle_dir, load_bundle  # noqa: PLC0415
        from bam_fb_test_rig.rig import bench_rig  # noqa: PLC0415

        from .mujoco_plant import scale_body_mass  # noqa: PLC0415

        rig = bench_rig(load_bundle(bundle_dir(V11_SHA)), backlash=None)
        if truth == "plate+22%":
            scale_body_mass(rig, "l2", END_GROUP_MASS_SCALE)
        elif truth != "plate":
            raise ValueError(f"baseline truth must be one of {BASELINE_TRUTHS}, not {truth!r}")
        rig.truth = {"truth": truth}
        _RIGS[key] = rig
    return _RIGS[key]


def build_rig(truth: str = "cad", *, wrist_friction: str = "sliding", scene: str = "scene.xml"):
    """The bam_fb_v2 twin for ``truth`` (cached per process: building one takes ~1-2 s). No hidden backlash (B0): the five-bar's gaps were
    the homing rung's question, not this one's; the friction and the stops are the parts a home's outcome turns on."""
    key = (truth, wrist_friction, scene)
    if key not in _RIGS:
        bam_ws_path()
        from bam_fb_test_rig.model import STIFF, build_model  # noqa: PLC0415
        from bam_fb_test_rig.rig import DRIVE_FRICTIONLOSS_NM  # noqa: PLC0415

        wrist = WRIST_COULOMB_NM if wrist_friction == "sliding" else WRIST_BREAKAWAY_NM
        friction = {"J1": DRIVE_FRICTIONLOSS_NM, "J2": DRIVE_FRICTIONLOSS_NM, "C1": DRIVE_FRICTIONLOSS_NM, **wrist}
        rig = build_model(load_v2_bundle(scene), STIFF, mount=v2_mount(), conveyor=None, frictionloss=friction, backlash=None)
        claw = rig.model.joint(CLAW_JOINT)
        rig.model.dof_frictionloss[rig.model.jnt_dofadr[claw.id]] = CLAW_FRICTION_NM
        rig.truth = apply_truth(rig, truth)
        _RIGS[key] = rig
    return _RIGS[key]


# ---------------------------------------------------------------------------------------------------------------------- the comps

COMP_NAMES = ("plate", "nominal", "v2_identified", "v2_cad")
COMP_FILES = {"plate": "gravity_params_massid_real_093852.json"}
COMP_WHY = {"plate": "fivebar_homed.DEFAULT_COMP: the mass ID with the plate on (what `fivebar_home -f` runs today)",
            "nominal": "--nominal-comp: bam_fivebar's nominal bench (the plate again, at CAD)",
            "v2_identified": "bam_rack_twin.fullarm_comp v2_parameters(base='identified'): the plate mass ID with its L2 group swapped to bam_fb_v2's",
            "v2_cad": "bam_rack_twin.fullarm_comp v2_parameters(base='cad'): the nominal bench with its L2 group swapped to bam_fb_v2's"}


def comp_dir(src: Path = BAM_WS_SRC) -> Path:
    return src / "dev" / "bam_rack_twin" / "records" / "fivebar-bench"


def home_paths(src: Path = BAM_WS_SRC) -> None:
    from .home_button import home_button_path  # noqa: PLC0415

    home_button_path(src)
    path = str(src / "dev" / "bam_rack_twin")
    if path not in sys.path:
        sys.path.append(path)


def bench_real():
    """bam_rack_twin's ``fivebar_run.bench_real``: ``in_mode(real_assembly(BENCH), "vertical")`` (the home button's bench)."""
    home_paths()
    from bam_fivebar.bench import BENCH  # noqa: PLC0415
    from bam_fivebar.gains_check import in_mode, real_assembly  # noqa: PLC0415

    return in_mode(real_assembly(BENCH), "vertical")


_COMPS: dict = {}


def comp_model(name: str, bench=None):
    """The ``ControllerModel`` the home button's feed-forward runs for comp ``name`` (module docstring); one per process (a ControllerModel
    compiles a MuJoCo model of the bench)."""
    if bench is None and name in _COMPS:
        return _COMPS[name]
    model = _comp_model(name, bench)
    if bench is None:
        _COMPS[name] = model
    return model


def _comp_model(name: str, bench=None):
    home_paths()
    from bam_fivebar import massid  # noqa: PLC0415
    from bam_fivebar.dynamics import ControllerModel  # noqa: PLC0415

    bench = bench_real() if bench is None else bench
    if name == "nominal":
        return ControllerModel.for_bench(bench)
    if name in ("v2_identified", "v2_cad"):
        from bam_rack_twin.fullarm_comp import v2_parameters  # noqa: PLC0415

        return massid.identified_model(bench, v2_parameters("nominal", base=name.removeprefix("v2_")))
    if name not in COMP_FILES:
        raise ValueError(f"comp must be one of {COMP_NAMES}, not {name!r}")
    return massid.identified_model(bench, massid.load_gravity_parameters(comp_dir() / COMP_FILES[name]))


# ---------------------------------------------------------------------------------------------------------------------- the plant

HOME_DEG = (91.01, -126.438)  # homed_083647's home_joint_rad, Craig (j2, c1): fivebar_home's homed map of record
J1_HOLD_CAP_NM = 7.0  # tview_run.J1_HOLD_NM: hold_j1's "11>d pos nan 0 nan" at the runner's J1 cap


class FullArmPlant:
    """bam_fivebar's ``Plant`` seam (``read`` / ``send([j2, c1])`` / ``step``; Craig rad, the drives' motor side) over the bam_fb_v2 twin.

    J1 holds where it starts (``d pos nan 0 7``). The wrist per ``wrist``: ``limp`` (mode 0, stopped: no torque, its friction only),
    ``hold`` (``d pos nan 0 cap`` at ``WristHold``'s gains from the first tick: where it is, never a target of its own; ``release_wrist``
    lets go one joint at a time) or ``brake`` (mode 15: the shorted phases' drag). The five-bar's commands are turned into board commands
    as ``mujoco_plant.MujocoRigPlant.tick`` does (ilimit_scale 0, no velocity target)."""

    control_period_s = CONTROL_DT

    def __init__(self, rig, qpos, *, wrist: str = "limp", hold: WristHold = WRIST_HOLD, cogging: bool = True):
        import mujoco  # noqa: PLC0415

        bam_ws_path()
        from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415
        from bam_fb_test_rig.rig import board_signs  # noqa: PLC0415
        from bam_fb_test_rig.sim import BoardConfig, Drive, RigSim  # noqa: PLC0415

        if wrist not in WRIST_MODES:
            raise ValueError(f"wrist must be one of {WRIST_MODES}, not {wrist!r}")
        self.rig, self.wrist, self.hold = rig, wrist, hold
        self.signs = board_signs(rig.bundle, rig)
        boards = real_boards()
        drives = [Drive(role, self.signs[role], boards[role]) for role in ("J1", "J2", "C1")]
        if wrist == "hold":
            drives += [Drive(role, 1.0, BoardConfig(kp=hold.kp, ki=0.0, kd=hold.kd, ilimit=0.0, max_torque_nm=WRIST_MAX_NM)) for role in WRISTS]
        self.sim = RigSim(rig, tuple(drives), log_hz=1e-6)
        self.sim.data.qpos[:] = qpos
        self.sim.data.qvel[:] = 0.0
        mujoco.mj_forward(rig.model, self.sim.data)
        self.cogging = cogging_terms(rig) if cogging else {}
        self.braked: dict[str, float] = {role: WRIST_BRAKE_NM_S for role in WRISTS} if wrist == "brake" else {}
        self.sim.pre_step = self._pre_step
        self.sim.power_up({role: (self.signs.get(role, 1.0) * self.sim.joint_rad(role)) for role in self.sim.states})
        craig = CraigMap(rig)
        if (craig.sign["J2"], craig.sign["C1"]) != (1.0, 1.0):
            raise ValueError(f"the Craig map's signs are {craig.sign}: this plant assumes Craig = URDF + offset")
        self.offset = {"J2": float(craig.offset["J2"]), "C1": float(craig.offset["C1"])}
        self.sim.hold("J1", J1_HOLD_CAP_NM)
        if wrist == "hold":
            for role in WRISTS:
                self.sim.hold(role, hold.cap_nm)
        self.commands = [None, None]
        self.time = 0.0
        self._previous = self._motors()
        self.velocity = np.zeros(2)
        self.log: list[list[float]] = []
        roles = {joint.role for joint in rig.bundle.joints}
        # WHY optional: the same plant runs the plate rig's v11 twin (no wrist, no claw) as the baseline (``baseline`` sweep)
        self.wrist_adr = {role: rig.qpos_adr(role) for role in WRISTS if role in roles}
        self.wrist_dof = {role: rig.dof_adr(role) for role in WRISTS if role in roles}
        names = {rig.model.joint(j).name for j in range(rig.model.njnt)}
        self.claw_adr = int(rig.model.jnt_qposadr[rig.model.joint(CLAW_JOINT).id]) if CLAW_JOINT in names else None
        self._record()

    # -- physics hooks
    def _pre_step(self, data) -> None:
        for role, (ripple, sign, offset) in self.cogging.items():
            q = float(data.qpos[self.rig.qpos_adr(role)])
            data.qfrc_applied[self.rig.dof_adr(role)] -= sign * float(ripple.torque_nm(sign * q + offset))
        for role, drag in self.braked.items():
            dof = self.rig.dof_adr(role)
            data.qfrc_applied[dof] -= drag * float(data.qvel[dof])

    def _motors(self) -> np.ndarray:
        return np.array([self.sim.joint_rad("J2"), self.sim.joint_rad("C1")])

    # -- the seam
    def read(self) -> Reading:
        q = self._motors()
        torque = np.array([self.signs[r] * self.sim.states[r].torque_nm for r in ("J2", "C1")])
        return Reading(t_s=self.time, position_rad=q + np.array([self.offset["J2"], self.offset["C1"]]), velocity_rad_s=self.velocity.copy(),
                       torque_nm=torque, j1_rad=float(self.sim.joint_rad("J1")))

    def send(self, commands) -> None:
        if len(commands) != 2:
            raise ValueError("one command per drive (j2, c1)")
        self.commands = list(commands)

    def step(self) -> Reading:
        from moteus_servo import MoteusCommand  # noqa: PLC0415

        for role, command in zip(("J2", "C1"), self.commands, strict=True):
            if isinstance(command, str):  # BRAKE
                self.sim.stop(role)
                self.braked[role] = FIVEBAR_BRAKE_NM_S
                continue
            self.braked.pop(role, None)
            if command is None or float(command.maximum_torque_nm) <= 0.0 or not math.isfinite(float(command.position_rad)):
                self.sim.stop(role)
                continue
            if (float(command.ilimit_scale), float(command.velocity_rad_s), float(command.kp_scale), float(command.kd_scale)) != (0.0, 0.0, 1.0, 1.0):
                raise ValueError("the home button's backend sends ilimit_scale 0, velocity 0 and unit gain scales; this plant carries only that")
            sign = self.signs[role]
            target = float(command.position_rad) - self.offset[role]
            self.sim.states[role].ramp_target_rad = None
            self.sim._send(role, MoteusCommand(position_rad=sign * target, feedforward_torque_nm=sign * float(command.feedforward_torque_nm),
                                               ilimit_scale=0.0, maximum_torque_nm=float(command.maximum_torque_nm)))
        self.sim.step(self.control_period_s)
        self.time += self.control_period_s
        now = self._motors()
        self.velocity = (now - self._previous) / self.control_period_s
        self._previous = now
        self._record()
        return self.read()

    # -- the release (tview_run._release) and the wrist's
    def brake_j1(self) -> None:
        self.sim.stop("J1")
        self.braked["J1"] = FIVEBAR_BRAKE_NM_S

    def stop_j1(self) -> None:
        self.sim.stop("J1")
        self.braked.pop("J1", None)

    def release_wrist(self, order=WRISTS, *, via: str = "brake", still_rad_s: float = 0.02, still_s: float = 0.5,
                      timeout_s: float = 10.0) -> list[dict]:
        """Let the wrist go, one joint at a time in ``order``, each once the one before it has been still ``still_s``: ``via="brake"``
        brakes the joint (mode 15: the wrist sags to its gravity rest at the drag's pace) and stops it (mode 0) once still; ``via="stop"``
        stops it at once. The five-bar keeps whatever it was last sent (its hold at home). Returns, per joint, how far and how fast the
        wrist moved after that joint's release (deg, deg/s)."""
        out = []
        for role in (r for r in order if r in self.wrist_dof):
            if role in self.sim.states:
                self.sim.stop(role)
            if via == "brake":
                self.braked[role] = WRIST_BRAKE_NM_S
            else:
                self.braked.pop(role, None)
            start = len(self.log)
            began, since = self.time, None
            while self.time - began < timeout_s:
                self.step()
                moving = max(abs(float(self.sim.data.qvel[dof])) for dof in self.wrist_dof.values())
                since = (since or self.time) if moving < still_rad_s else None
                if since is not None and self.time - since >= still_s:
                    break
            self.braked.pop(role, None)  # mode 0 once still
            rows = np.asarray(self.log[start:], dtype=float)
            out.append({"joint": role, "via": via, "seconds": round(self.time - began, 2),
                        "swing_deg": np.round(rows[:, 7:10].max(axis=0) - rows[:, 7:10].min(axis=0), 2).tolist() if len(rows) else None,
                        "peak_deg_s": np.round(np.max(np.abs(rows[:, 12:15]), axis=0), 1).tolist() if len(rows) else None})
        return out

    # -- the log: t, j2, c1 (Craig, motor), v_j2, v_c1, tau_j2, tau_c1, w1, w2, w3 (deg), claw (deg), j1 (deg), wrist speeds (deg/s),
    # j1 torque, wrist torques
    def _record(self) -> None:
        data = self.sim.data
        q = self._motors()
        self.log.append([self.time, math.degrees(q[0] + self.offset["J2"]), math.degrees(q[1] + self.offset["C1"]),
                         math.degrees(self.velocity[0]), math.degrees(self.velocity[1]),
                         self.signs["J2"] * self.sim.states["J2"].torque_nm, self.signs["C1"] * self.sim.states["C1"].torque_nm,
                         *(math.degrees(float(data.qpos[self.wrist_adr[w]])) if w in self.wrist_adr else 0.0 for w in WRISTS),
                         math.degrees(float(data.qpos[self.claw_adr])) if self.claw_adr is not None else 0.0,
                         math.degrees(self.sim.joint_rad("J1")),
                         *(math.degrees(float(data.qvel[self.wrist_dof[w]])) if w in self.wrist_dof else 0.0 for w in WRISTS),
                         self.signs["J1"] * self.sim.states["J1"].torque_nm,
                         *((self.sim.states[w].torque_nm if w in self.sim.states else 0.0) for w in WRISTS)])

    def truth_craig_deg(self) -> np.ndarray:
        return np.degrees(self._motors() + np.array([self.offset["J2"], self.offset["C1"]]))


LOG_COLUMNS = ("t", "j2_deg", "c1_deg", "v_j2_deg_s", "v_c1_deg_s", "tau_j2_nm", "tau_c1_nm", "w1_deg", "w2_deg", "w3_deg", "claw_deg",
               "j1_deg", "v_w1_deg_s", "v_w2_deg_s", "v_w3_deg_s", "tau_j1_nm", "tau_w1_nm", "tau_w2_nm", "tau_w3_nm")


# ---------------------------------------------------------------------------------------------------------------------- the starts


@dataclass(frozen=True)
class FullStart:
    """Where an episode begins: the five-bar at Craig (j2, c1) on the bench's knee ``knee`` (-1 the bench's, +1 flipped), the wrist at
    ``wrist_deg`` (W1, W2, W3) or at its gravity rest (None: settled limp with the five-bar held), and ``rest`` - the whole arm first
    settled unpowered (an any-rest start: where a power-up finds it) - else the five-bar starts where the boards held it."""

    name: str
    j2_deg: float
    c1_deg: float
    knee: int = -1
    wrist_deg: tuple[float, float, float] | None = None
    rest: bool = False
    family: str = "grid"
    j1_deg: float = 0.0  # the plane's tilt the press finds (J1 held there throughout, as hold_j1 holds it)


REAL_STARTS = (FullStart("real fold rest (camera look j2 62.0 / j3 +19.6, crank -174.25)", 62.0, -174.25, -1, family="real"),
               FullStart("real after_gate1 (99.91, -106.00)", 99.9115, -106.0018, -1, family="real"),
               FullStart("home", HOME_DEG[0], HOME_DEG[1], -1, family="real"))


STOP_MARGIN_RAD = math.radians(2.0)


def place(rig, start: FullStart):
    """The closed twin pose for ``start``'s five-bar (the Craig map's closed pose on the branch nearest the bench's j3), its wrist at
    ``start.wrist_deg`` (zeros when None: the gravity rest is found later), and that pose's worst stop / loop penetration (m). Raises
    ValueError when the loop does not close there on the twin."""
    import mujoco  # noqa: PLC0415

    bam_ws_path()
    home_paths()
    from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415
    from bam_fivebar.kinematics import forward_pose  # noqa: PLC0415
    from bam_fivebar.recovery import assembly  # noqa: PLC0415

    bench = bench_real()
    j2, c1 = math.radians(start.j2_deg), math.radians(start.c1_deg)
    pose = forward_pose(assembly(bench, start.knee), j2, c1)
    # a rest ON the closure fold (the real t1 start reads (65.35, -174.25), which closes on neither assembly): the nearest crank angle
    # that closes, on the start's knee first
    for nudge in np.radians(np.arange(0.25, 10.01, 0.25)):
        if pose is not None:
            break
        for knee in (start.knee, -start.knee):
            pose = forward_pose(assembly(bench, knee), j2, c1 + nudge) or forward_pose(assembly(bench, knee), j2, c1 - nudge)
            if pose is not None:
                break
    if pose is None:
        raise ValueError(f"{start.name}: the bench's loop does not close within 10 deg of ({start.j2_deg}, {start.c1_deg})")
    craig = CraigMap(rig)
    for role, value in (("J2", pose.j2), ("C1", pose.c1)):
        # WHY refused (the full-arm pilot, 2026-11-13): bam_fivebar's reachable map has cells past the CAD's own stops (Craig j2 < 0 is L1
        # through its lower hardstop); placed there the twin starts INSIDE its stop and no home is meaningful
        low, high = rig.model.jnt_range[rig.model.joint(rig.bundle.joint(role).name).id]
        urdf = (craig.cad(role, value) + math.pi) % (2.0 * math.pi) - math.pi if role == "C1" else craig.cad(role, value)
        if not low + STOP_MARGIN_RAD <= urdf <= high - STOP_MARGIN_RAD:
            raise ValueError(f"{start.name}: {role} at {math.degrees(urdf):.1f} deg (URDF) is outside the CAD's stops "
                             f"[{math.degrees(low):.1f}, {math.degrees(high):.1f}]")
    q, residual = craig.closed_pose(pose.j2, pose.j3, pose.c1)
    if residual > 1e-6:
        raise ValueError(f"{start.name}: the twin's loop does not close there (residual {residual * 1e3:.3f} mm)")
    roles = {joint.role for joint in rig.bundle.joints}
    for role, value in zip(WRISTS, start.wrist_deg or (0.0, 0.0, 0.0), strict=True):
        if role in roles:
            q[rig.qpos_adr(role)] = math.radians(value)
    q[rig.qpos_adr("J1")] = math.radians(start.j1_deg)
    data = mujoco.MjData(rig.model)
    data.qpos[:] = q
    mujoco.mj_forward(rig.model, data)
    depth = max([-float(data.contact[i].dist) for i in range(data.ncon)], default=0.0)
    return q, depth


def settle_wrist(rig, q, *, max_seconds: float = 20.0, still_rad_s: float = 0.01, still_s: float = 0.5):
    """The limp wrist's gravity rest with the five-bar held still at ``q``: the wrist (and the claw's finger) swing under gravity and
    their friction until still (or ``max_seconds``), the five-bar's joints put back each physics step. WHY kinematic and not a stiff
    damper on the drives (the first try, 2026-11-13): a 1e6 damping against the loop's stiff connect sent MuJoCo's accelerations to NaN."""
    import mujoco  # noqa: PLC0415

    model = rig.model
    data = mujoco.MjData(model)
    data.qpos[:] = q
    data.qvel[:] = 0.0
    roles = {joint.role for joint in rig.bundle.joints}
    names = {model.joint(j).name for j in range(model.njnt)}
    loose = {rig.dof_adr(r) for r in WRISTS if r in roles} | ({int(model.jnt_dofadr[model.joint(CLAW_JOINT).id])} if CLAW_JOINT in names else set())
    if not loose:
        return np.array(q, dtype=float)
    held_q = [i for j in range(model.njnt) if int(model.jnt_dofadr[j]) not in loose for i in [int(model.jnt_qposadr[j])]]
    held_v = [int(model.jnt_dofadr[j]) for j in range(model.njnt) if int(model.jnt_dofadr[j]) not in loose]
    fixed = np.asarray(q, dtype=float)[held_q]
    since, steps = None, int(round(max_seconds / model.opt.timestep))
    for step in range(steps):
        mujoco.mj_step(model, data)
        data.qpos[held_q] = fixed
        data.qvel[held_v] = 0.0
        moving = float(np.max(np.abs(data.qvel[sorted(loose)])))
        now = step * model.opt.timestep
        since = (since if since is not None else now) if moving < still_rad_s else None
        if since is not None and now - since >= still_s:
            break
    if data.warning[mujoco.mjtWarning.mjWARN_BADQACC].number:
        raise ValueError("the wrist's settle went unstable")
    out = np.array(q, dtype=float)
    for adr in (rig.qpos_adr(r) for r in WRISTS if r in roles):
        out[adr] = data.qpos[adr]
    if CLAW_JOINT in names:
        claw = int(model.jnt_qposadr[model.joint(CLAW_JOINT).id])
        out[claw] = data.qpos[claw]
    return out


def settle_unpowered(rig, q, seconds: float = 4.0):
    """The whole arm's unpowered rest from ``q`` (J1 held, every other joint limp, its friction and the stops): a power-up's start."""
    plant = FullArmPlant(rig, q, wrist="limp", cogging=True)
    for _ in range(int(round(seconds / CONTROL_DT))):
        plant.step()
    return plant.sim.data.qpos.copy()


def grid_starts(step_j2: float = 15.0, step_c1: float = 30.0, flipped: int = 8) -> list[FullStart]:
    """The home sweep's start set, thinned: bam_fivebar_recovery.proof's reachable cells (the bench's knee and the flipped knee, the
    contact twin's own map) on a ``step_j2`` x ``step_c1`` deg lattice. WHY thinned: one full-arm episode costs ~30-90 s of CPU; the
    3 deg sweep's 2552 cells were the bench twin's."""
    home_paths()
    from bam_fivebar.recovery import physical_map  # noqa: PLC0415

    bench = bench_real()
    physical = physical_map(bench)
    axis = np.degrees(physical.axis_rad)
    out = []
    for i, j in np.argwhere(physical.reachable[0]):
        j2, c1 = float(axis[i]), float(axis[j])
        if abs((j2 / step_j2) - round(j2 / step_j2)) > 1e-6 or abs((c1 / step_c1) - round(c1 / step_c1)) > 1e-6:
            continue
        out.append(FullStart(f"cell ({j2:.0f}, {c1:.0f})", j2, c1, -1, family="grid"))
    # the flipped knee's pocket is small (no lattice point lands in it): ``flipped`` of its cells, evenly spread over the pocket
    pocket = np.argwhere(physical.reachable[1])
    for i, j in pocket[np.linspace(0, len(pocket) - 1, min(flipped, len(pocket))).round().astype(int)] if len(pocket) else []:
        j2, c1 = float(axis[i]), float(axis[j])
        out.append(FullStart(f"cell knee flipped ({j2:.0f}, {c1:.0f})", j2, c1, 1, family="knee flipped"))
    return out


# ---------------------------------------------------------------------------------------------------------------------- an episode


def truth_gravity(rig, qpos) -> np.ndarray:
    """The twin's own static holding torque (J2, C1; N.m, joint = Craig sign) at ``qpos``, the wrist where it is: bam_fb_test_rig's virtual
    work on the closed chain under the truth's masses (gravity.holding_torque)."""
    bam_ws_path()
    from bam_fb_test_rig.gravity import holding_torque  # noqa: PLC0415

    return np.asarray(holding_torque(rig, np.asarray(qpos, dtype=float)), dtype=float)


def comp_error(rig, qpos, model, craig_rad) -> list[float] | None:
    """The comp's static gravity minus the truth's at a pose (N.m, J2 / C1): positive on J2 = the comp feeds more than holds the arm."""
    try:
        comp = model.gravity_at_motors(float(craig_rad[0]), float(craig_rad[1]))
        if comp is None:
            return None
        return np.round(np.asarray(comp, dtype=float) - truth_gravity(rig, qpos), 3).tolist()
    except Exception:  # noqa: BLE001 - a pose the closure cannot solve has no number, not a crash
        return None


HOME_ATTEMPTS = 3  # fivebar_homed.HOME_ATTEMPTS
REACH_DEG = math.degrees(0.06)  # bam_fivebar_recovery HomeTuning.reach: the walk home's own done-when (3.44 deg)
AT_HOME_DEG = 5.0  # home_sweep.AT_HOME_DEG: done but further than this from home is a silent wrong
# fivebar_homed.J1_START_MAX_RAD: a homed stage (the home button included) refuses to start with |J1| over this. WHY scored: the release at
# home (tview_run._release) brakes J1 and then lets it go, and the arm's weight off J1's axis tilts the plane until J1's friction holds it
J1_START_MAX_DEG = 8.0
RUNAWAY_DEG_S = math.degrees(1.5)  # fivebar_plant.PlantLimits.runaway_ceiling_rad_s (86 deg/s)
CURRENT_CAP_A = 17.5  # CAN 12 / 13 servo.max_current_A (records/fivebar-bench, docs/power_budget)
POWER_CAP_W = 72.0  # docs/power_budget: J2 72 W kept, C1 288 -> 72 W proposed
OUTPUT_NM_PER_A = 0.64
PHASE_OHM = 0.0871  # the 60ASM400's (bam_rack_twin tests/test_live_record: 1.5 x 17.5^2 x 0.0871 = 40 W)


@dataclass
class EpisodeConfig:
    start: FullStart
    comp: str = "v2_cad"
    truth: str = "cad"
    wrist: str = "limp"
    wrist_friction: str = "sliding"
    hold: WristHold = field(default_factory=WristHold)
    release: str = "brake"  # a held wrist's release: "brake" (mode 15 until still, then 0) or "stop" (mode 0 at once)
    trace: bool = False


def _phase_peaks(rows: np.ndarray, powered: np.ndarray) -> dict:
    """Peaks over ``rows`` (LOG_COLUMNS), J2 / C1 split into powered and limp ticks by ``powered`` (n, 2)."""
    speeds = np.abs(rows[:, 3:5])
    torque = np.abs(rows[:, 5:7])
    current = torque / OUTPUT_NM_PER_A
    power = 1.5 * PHASE_OHM * current**2 + np.abs(rows[:, 5:7] * np.radians(rows[:, 3:5]))

    def peak(values, mask):
        return [round(float(values[mask[:, k], k].max()), 2) if np.any(mask[:, k]) else 0.0 for k in range(2)]

    return {"peak_powered_deg_s": peak(speeds, powered), "peak_limp_deg_s": peak(speeds, ~powered),
            "peak_current_a": peak(current, np.ones_like(powered)), "peak_power_w": peak(power, np.ones_like(powered))}


def run_episode(config: EpisodeConfig) -> dict:
    """One press of the home button on the full-arm twin (module docstring), scored against the truth. Never raises."""
    home_paths()
    from bam_fivebar_recovery.backend import PlantBackend  # noqa: PLC0415
    from bam_fivebar_recovery.home import return_home  # noqa: PLC0415

    started = time.monotonic()
    start = config.start
    out: dict = {"start": start.name, "family": start.family, "rest": start.rest, "comp": config.comp, "truth": config.truth,
                 "wrist": config.wrist, "wrist_friction": config.wrist_friction, "release": config.release if config.wrist == "hold" else None,
                 "j1_start_tilt_deg": start.j1_deg}
    try:
        rig = build_baseline_rig(config.truth) if config.truth in BASELINE_TRUTHS else build_rig(config.truth, wrist_friction=config.wrist_friction)
        q, depth = place(rig, start)
        out["placed_penetration_mm"] = round(depth * 1e3, 3)
        if start.wrist_deg is None:
            q = settle_wrist(rig, q)
        if start.rest:
            q = settle_unpowered(rig, q)
        bench = bench_real()
        model = comp_model(config.comp)
        plant = FullArmPlant(rig, q, wrist=config.wrist, hold=config.hold)
    except Exception as error:  # noqa: BLE001 - a start that cannot be placed is recorded, never dropped
        out.update(status="not placed", message=f"{type(error).__name__}: {error}"[:300], wall_s=round(time.monotonic() - started, 1))
        return out
    first = plant.read()
    out["start_craig_deg"] = np.degrees(first.position_rad).round(3).tolist()
    out["comp_error_start_nm"] = comp_error(rig, plant.sim.data.qpos, model, first.position_rad)
    out["start_wrist_deg"] = np.round(plant.log[0][7:11], 2).tolist()
    home = np.radians(HOME_DEG)
    powered: list[list[bool]] = []

    class Seam:  # PlantBackend over the plant, recording which drives each tick commanded
        control_period_s = plant.control_period_s

        @staticmethod
        def read():
            return plant.read()

        @staticmethod
        def send(commands):
            powered.append([command is not None for command in commands])
            plant.send(commands)

        @staticmethod
        def step():
            return plant.step()

    attempts = []
    status, message = "raised", ""
    for attempt in range(1, HOME_ATTEMPTS + 1):
        backend = PlantBackend(Seam, signs=(1.0, 1.0))
        try:
            record = return_home(backend, bench, model, home)
            attempts.append({"attempt": attempt, "start": record["start"]["kind"], "settles": len(record.get("settled", [])),
                             "path": record.get("path"), "steps": [step for seq in record["sequences"] for step in seq["steps"]]})
            status, message = "done", ""
            break
        except Exception as error:  # noqa: BLE001 - an abort is the run's outcome; the real runner holds and runs the home again
            message = f"{type(error).__name__}: {error}"[:300]
            attempts.append({"attempt": attempt, "error": message})
            # the controlled stop's hold: each drive held where it is for 1 s at the hold caps with the comp's gravity there
            from moteus_servo import MoteusCommand  # noqa: PLC0415

            here = plant.read().position_rad
            gravity = model.gravity_at_motors(float(here[0]), float(here[1]))
            gravity = np.zeros(2) if gravity is None else np.asarray(gravity, dtype=float)
            hold = [MoteusCommand(position_rad=float(here[k]), feedforward_torque_nm=float(gravity[k]), ilimit_scale=0.0,
                                  maximum_torque_nm=(10.0, 7.0)[k]) for k in range(2)]
            for _ in range(int(round(1.0 / CONTROL_DT))):
                powered.append([True, True])
                plant.send(hold)
                plant.step()
    done_s = plant.time
    sequence_rows = len(plant.log)
    out["comp_error_end_nm"] = comp_error(rig, plant.sim.data.qpos, model, plant.read().position_rad)
    # the wrist's release first, the five-bar still holding home (WHY first, 2026-11-13: released after the five-bar, the wrist's swing
    # knocked the limp arm 6-9 deg off home); a held wrist via its brake, a braked wrist stopped, one joint at a time
    released = []
    if config.wrist == "hold":
        released = plant.release_wrist(via=config.release)
        powered.extend([[True, True]] * (len(plant.log) - len(powered) - 1))
    # the release at home (tview_run._release): brake all three until still (<= 10 s), then stop
    plant.brake_j1()
    plant.send(["brake", "brake"])
    since = None
    began = plant.time
    while plant.time - began < 10.0:
        powered.append([False, False])
        reading = plant.step()
        since = (since or plant.time) if float(np.max(np.abs(reading.velocity_rad_s))) < 0.01 else None
        if since is not None and plant.time - since > 1.0:
            break
    plant.stop_j1()
    plant.send([None, None])
    if config.wrist == "brake":
        # the real order (bam_rack_twin fivebar_home --wrist brake): wrist_brake.release once fivebar_homed has released the arm at home
        released = plant.release_wrist(via="stop")
    fivebar_rows = sequence_rows
    for _ in range(int(round(2.0 / CONTROL_DT))):  # everything let go: where it comes to rest
        powered.append([False, False])
        plant.send([None, None])
        plant.step()
    rows = np.asarray(plant.log, dtype=float)
    mask = np.vstack([[[True, True]], np.asarray(powered, dtype=bool)])[: len(rows)]
    import mujoco  # noqa: PLC0415

    unstable = int(plant.sim.data.warning[mujoco.mjtWarning.mjWARN_BADQACC].number)
    if unstable:  # MuJoCo reset the state mid-episode: nothing after it is physics (counted, never scored)
        status, message = "unstable", f"MuJoCo bad QACC x{unstable}"
    final = plant.truth_craig_deg()
    off = final - np.asarray(HOME_DEG)
    off[1] = (off[1] + 180.0) % 360.0 - 180.0
    wrist = rows[:, 7:10]
    region_a = [bool(in_region_a(r[7], r[8])) for r in rows]
    region_b = [bool(in_region_b(r[8], r[9], r[10])) for r in rows]
    home_rows = rows[:fivebar_rows]
    out.update(
        status=status, message=message, attempts=len(attempts), attempt_log=attempts,
        done_s=round(done_s, 2), total_s=round(plant.time, 2),
        end_craig_deg=final.round(3).tolist(), off_home_deg=off.round(3).tolist(),
        reached=bool(status == "done" and np.all(np.abs(off) <= REACH_DEG)),
        silent_wrong=bool(status == "done" and not np.all(np.abs(off) <= AT_HOME_DEG)),
        **_phase_peaks(home_rows, mask[:fivebar_rows]),
        runaway_flag=bool(np.max(np.abs(home_rows[:, 3:5])) > RUNAWAY_DEG_S),
        j1_peak_dev_deg=round(float(np.max(np.abs(rows[:sequence_rows, 11] - rows[0, 11]))), 3),
        j1_peak_torque_nm=round(float(np.max(np.abs(rows[:sequence_rows, 15]))), 3),
        j1_start_deg=round(float(rows[0, 11]), 3), j1_end_deg=round(float(rows[-1, 11]), 3),
        j1_next_press_refused=bool(abs(float(rows[-1, 11])) > J1_START_MAX_DEG),
        wrist_excursion_deg=np.round(wrist[:fivebar_rows].max(axis=0) - wrist[:fivebar_rows].min(axis=0), 2).tolist(),
        wrist_peak_abs_deg=np.round(np.max(np.abs(wrist), axis=0), 2).tolist(),
        wrist_peak_deg_s=np.round(np.max(np.abs(rows[:fivebar_rows, 12:15]), axis=0), 1).tolist(),
        wrist_peak_deg_s_release=np.round(np.max(np.abs(rows[fivebar_rows:, 12:15]), axis=0), 1).tolist() if len(rows) > fivebar_rows else None,
        wrist_on_stop_during_home=bool(np.any(np.abs(wrist[:fivebar_rows]) >= WRIST_STOP_DEG - 0.5)),
        wrist_peak_torque_nm=np.round(np.max(np.abs(rows[:, 16:19]), axis=0), 3).tolist(),
        wrist_on_stop=bool(np.any(np.abs(wrist) >= WRIST_STOP_DEG - 0.5)),
        region_a=bool(any(region_a)), region_b=bool(any(region_b)),
        region_a_during_home=bool(any(region_a[:fivebar_rows])),
        wrist_end_deg=np.round(rows[-1, 7:11], 2).tolist(), wrist_release=released,
        wall_s=round(time.monotonic() - started, 1))
    if config.trace:
        every = 5
        out["trace"] = {"columns": list(LOG_COLUMNS), "every_s": every * CONTROL_DT, "rows": np.round(rows[::every], 4).tolist(),
                        "fivebar_rows": fivebar_rows}
    return out


# ---------------------------------------------------------------------------------------------------------------------- the sweep

# A non-hanging wrist for the hold's starts (deg, W1 / W2 / W3): a wrist the home finds where a task left it, held there. Each keeps
# |W2| <= 95 (the CAD's clear condition) and stays out of both self-contact regions.
# The plane's tilt a press may find (deg): the full arm's release leaves J1 at +11.5 on this twin (J1's 0.74 N.m Coulomb against the arm's
# 2.1 N.m off its axis at home), and its unpowered rest band reaches ~+21.
J1_TILTS_DEG = (12.0, 20.0)
HELD_WRIST_POSES = {"pick ready (0, 90, 0)": (0.0, 90.0, 0.0), "W1 +90 (90, 0, 0)": (90.0, 0.0, 0.0), "W1 -100 W2 +60": (-100.0, 60.0, 30.0)}


def sweep_configs(sweep: str, *, starts=None, wrist: str = "hold") -> list[EpisodeConfig]:
    """The episodes a sweep runs. ``wrist``: every five-bar start with the wrist at its gravity rest, under each wrist mode, on the CAD
    and the +22 % truths, with the bam_fb_v2 comp; then the hold from the non-hanging wrist poses. ``comp``: every comp on every truth
    with ``wrist`` (the wrist mode the wrist sweep chose); ``rest``: the same starts first settled unpowered (where a power-up finds the
    arm), every comp, the CAD truth."""
    starts = list(REAL_STARTS) + grid_starts() if starts is None else list(starts)
    out = []
    if sweep == "wrist":
        for truth in ("cad", "end+22%"):
            for mode in WRIST_MODES:
                out += [EpisodeConfig(start=start, comp="v2_cad", truth=truth, wrist=mode) for start in starts]
        for pose_name, pose in HELD_WRIST_POSES.items():
            out += [EpisodeConfig(start=replace(start, name=f"{start.name} · wrist {pose_name}", wrist_deg=pose), comp="v2_cad",
                                  truth="cad", wrist=mode) for start in starts[::3] for mode in ("hold", "limp")]
    elif sweep == "comp":
        for truth in ("cad", "claw_high", "end+22%"):  # claw nominal sits between the CAD and the high claw (the static map has all four)
            for comp in COMP_NAMES:
                out += [EpisodeConfig(start=start, comp=comp, truth=truth, wrist=wrist) for start in starts]
    elif sweep == "j1":
        for tilt in J1_TILTS_DEG:
            out += [EpisodeConfig(start=replace(start, name=f"{start.name} · J1 {tilt:+.0f}", j1_deg=tilt), comp="v2_cad", truth=truth,
                                  wrist=wrist) for start in starts[::2] for truth in ("cad", "end+22%")]
    elif sweep == "release":
        # the wrist's treatments from the gravity rest and from the task poses a press may find, CAD truth
        poses = {"rest": None, **HELD_WRIST_POSES}
        for pose_name, pose in poses.items():
            for mode, release in (("hold", "brake"), ("hold", "stop"), ("brake", "stop"), ("limp", "stop")):
                out += [EpisodeConfig(start=replace(start, name=f"{start.name} · wrist {pose_name}", wrist_deg=pose), comp="v2_cad",
                                      truth="cad", wrist=mode, release=release) for start in starts[::3]]
    elif sweep == "final":
        # what ships (bam_rack_twin fivebar_home --comp bam_fb_v2 --wrist brake): every start on every truth, the wrist braked and let go
        # after the five-bar in the real order; the same from any-rest starts (settled unpowered first) against today's plate comp; and the
        # limp wrist at the real wrist's breakaway friction (the sliding level is the floppier case the wrist sweep ran)
        for truth in ("cad", "claw_high", "end+22%"):
            out += [EpisodeConfig(start=start, comp="v2_cad", truth=truth, wrist="brake") for start in starts]
        rested = [replace(start, name=f"{start.name} · rested", rest=True) for start in starts if start.family != "real"]
        for comp in ("v2_cad", "plate"):
            out += [EpisodeConfig(start=start, comp=comp, truth="cad", wrist="brake") for start in rested]
        poses = {"rest": None, **HELD_WRIST_POSES}
        out += [EpisodeConfig(start=replace(start, name=f"{start.name} · wrist {pose_name}", wrist_deg=pose), comp="v2_cad", truth="cad",
                              wrist="limp", wrist_friction="breakaway") for pose_name, pose in poses.items() for start in starts[::3]]
    elif sweep == "baseline":
        for truth in BASELINE_TRUTHS:
            out += [EpisodeConfig(start=start, comp="plate", truth=truth, wrist="limp") for start in starts]
        # the plate rig from the same any-rest starts (settled unpowered first): is a rest the home cannot take the full arm's doing?
        rested = [replace(start, name=f"{start.name} · rested", rest=True) for start in starts if start.family != "real"]
        out += [EpisodeConfig(start=start, comp="plate", truth="plate", wrist="limp") for start in rested]
    elif sweep == "rest":
        rested = [replace(start, name=f"{start.name} · rested", rest=True, family=f"{start.family} rest") for start in starts
                  if start.family != "real"]
        for comp in COMP_NAMES:
            out += [EpisodeConfig(start=start, comp=comp, truth="cad", wrist=wrist) for start in rested]
    else:
        raise ValueError(f"sweep must be wrist, comp or rest, not {sweep!r}")
    return out


# The walk home's stall budget per drive (N.m): a waypoint is Reached within 0.06 rad, and a PD at the record's kp (J2 144, C1 200 N.m/rev)
# with the drive's 0.74 N.m Coulomb stops short of it once the comp's error against the motion exceeds kp x 0.06 - 0.74.
STALL_BUDGET_NM = (144.0 / (2.0 * math.pi) * 0.06 - 0.74, 200.0 / (2.0 * math.pi) * 0.06 - 0.74)


def _static_job(args) -> list[dict]:
    truth, start = args
    rig = build_rig(truth)
    try:
        q, _ = place(rig, start)
    except ValueError:
        return []
    q = settle_wrist(rig, q)
    craig = CraigMap_cached(rig)
    j2, _, c1 = craig.craig(q)
    truth_nm = truth_gravity(rig, q)
    out = []
    for comp in COMP_NAMES:
        model = comp_model(comp)
        value = model.gravity_at_motors(j2, c1)
        if value is None:
            continue
        error = np.asarray(value, dtype=float) - truth_nm
        out.append({"truth": truth, "comp": comp, "start": start.name, "craig_deg": [round(math.degrees(j2), 2), round(math.degrees(c1), 2)],
                    "truth_nm": np.round(truth_nm, 3).tolist(), "comp_nm": np.round(value, 3).tolist(), "error_nm": np.round(error, 3).tolist()})
    return out


_CRAIG: dict = {}


def CraigMap_cached(rig):  # noqa: N802 - one CraigMap per rig per process
    bam_ws_path()
    from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415

    if id(rig) not in _CRAIG:
        _CRAIG[id(rig)] = CraigMap(rig)
    return _CRAIG[id(rig)]


def static_comp_map(starts, *, workers: int = 6) -> dict:
    """Every comp's static gravity against every truth's at every start pose with the wrist hanging (no dynamics): per (comp, truth) the
    worst error per drive and how many poses are over the walk's stall budget (``STALL_BUDGET_NM``)."""
    from multiprocessing import get_context  # noqa: PLC0415

    jobs = [(truth, start) for truth in TRUTHS for start in starts]
    with get_context("fork").Pool(workers) as pool:
        rows = [row for chunk in pool.imap_unordered(_static_job, jobs, chunksize=2) for row in chunk]
    cells = []
    for truth in TRUTHS:
        for comp in COMP_NAMES:
            mine = [r for r in rows if r["truth"] == truth and r["comp"] == comp]
            if not mine:
                continue
            error = np.array([r["error_nm"] for r in mine])
            cells.append({"truth": truth, "comp": comp, "poses": len(mine),
                          "j2_error_nm": {"max": round(float(error[:, 0].max()), 3), "min": round(float(error[:, 0].min()), 3),
                                          "rms": round(float(np.sqrt(np.mean(error[:, 0] ** 2))), 3)},
                          "c1_error_nm": {"max": round(float(error[:, 1].max()), 3), "min": round(float(error[:, 1].min()), 3),
                                          "rms": round(float(np.sqrt(np.mean(error[:, 1] ** 2))), 3)},
                          "over_budget_j2": int(np.sum(np.abs(error[:, 0]) > STALL_BUDGET_NM[0])),
                          "over_budget_c1": int(np.sum(np.abs(error[:, 1]) > STALL_BUDGET_NM[1]))})
    return {"stall_budget_nm": [round(v, 3) for v in STALL_BUDGET_NM], "cells": cells, "rows": rows}


def _job(config: EpisodeConfig) -> dict:
    os.environ.setdefault("MUJOCO_GL", "egl")
    try:
        return run_episode(config)
    except Exception as error:  # noqa: BLE001 - a crash is an outcome, recorded (never a silent drop from the denominator)
        return {"start": config.start.name, "family": config.start.family, "comp": config.comp, "truth": config.truth, "wrist": config.wrist,
                "status": "crashed", "message": f"{type(error).__name__}: {error}"[:300]}


def summarize(results: list[dict]) -> dict:
    """Per (sweep cell) - comp x truth x wrist - the counts and the worst peaks."""
    from collections import defaultdict  # noqa: PLC0415

    cells: dict = defaultdict(list)
    for row in results:
        kind = ("rest" if row.get("rest") else "held") + (f" J1 {row['j1_start_tilt_deg']:+.0f}" if row.get("j1_start_tilt_deg") else "")
        wrist = row.get("wrist") if not row.get("release") else f"{row.get('wrist')} (release via {row['release']})"
        wrist += "" if row.get("wrist_friction", "sliding") == "sliding" else f" ({row['wrist_friction']} friction)"
        cells[(row.get("comp"), row.get("truth"), wrist, kind)].append(row)
    out = []
    for (comp, truth, wrist, kind), rows in sorted(cells.items(), key=lambda item: tuple(map(str, item[0]))):
        placed = [r for r in rows if r.get("status") in ("done", "raised")]
        unstable = sum(r.get("status") == "unstable" for r in rows)
        done = [r for r in placed if r["status"] == "done"]

        def worst(key, index=None, rows=placed):
            values = [(r[key][index] if index is not None else r[key]) for r in rows if r.get(key) is not None]
            return round(float(max(values)), 2) if values else None

        out.append({"comp": comp, "truth": truth, "wrist": wrist, "starts": kind, "episodes": len(rows), "placed": len(placed), "unstable": unstable,
                    "done": len(done), "reached": sum(bool(r.get("reached")) for r in placed),
                    "silent_wrong": sum(bool(r.get("silent_wrong")) for r in placed),
                    "aborted_attempts": sum(max(0, int(r.get("attempts", 1)) - (1 if r["status"] == "done" else 0)) for r in placed),
                    "worst_off_home_deg": worst("off_home_abs_max"), "worst_powered_deg_s": [worst("peak_powered_deg_s", 0), worst("peak_powered_deg_s", 1)],
                    "worst_limp_c1_deg_s": worst("peak_limp_deg_s", 1), "runaway_flags": sum(bool(r.get("runaway_flag")) for r in placed),
                    "worst_current_a": [worst("peak_current_a", 0), worst("peak_current_a", 1)],
                    "worst_power_w": [worst("peak_power_w", 0), worst("peak_power_w", 1)],
                    "median_done_s": round(float(np.median([r["done_s"] for r in done])), 1) if done else None,
                    "worst_done_s": worst("done_s", rows=done),
                    "region_a": sum(bool(r.get("region_a")) for r in placed), "region_a_during_home": sum(bool(r.get("region_a_during_home")) for r in placed),
                    "region_b": sum(bool(r.get("region_b")) for r in placed), "wrist_on_stop": sum(bool(r.get("wrist_on_stop")) for r in placed),
                    "wrist_on_stop_during_home": sum(bool(r.get("wrist_on_stop_during_home")) for r in placed),
                    "worst_wrist_deg_s_release": [worst("wrist_peak_deg_s_release", k) for k in range(3)],
                    "worst_wrist_excursion_deg": [worst("wrist_excursion_deg", k) for k in range(3)],
                    "worst_wrist_deg_s": [worst("wrist_peak_deg_s", k) for k in range(3)],
                    "j1_next_press_refused": sum(bool(r.get("j1_next_press_refused")) for r in placed),
                    "worst_j1_end_abs_deg": worst("j1_end_abs_deg")})
    return {"cells": out}


def main(argv=None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sweep", choices=("wrist", "comp", "rest", "static", "baseline", "j1", "release", "final"), default="comp")
    parser.add_argument("--wrist", choices=WRIST_MODES, default="hold", help="comp / rest sweeps: the wrist's mode")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None, help="only the first N episodes (a pilot)")
    parser.add_argument("--trace-every", type=int, default=0, help="keep the tick trace of every Nth episode (0: none)")
    args = parser.parse_args(argv)
    if args.sweep == "static":
        from sim2real.provenance import code_sha, write_results  # noqa: PLC0415

        started = time.monotonic()
        static = static_comp_map(list(REAL_STARTS) + grid_starts(), workers=args.workers)
        payload = {"schema": "sim2real_fullarm_comp_map/1", "bundle": f"cad-exporter {V2_REF} {V2_SUBDIR}", "truths": TRUTH_WHY,
                   "sim2real_sha": code_sha(Path(__file__).resolve().parents[4]),
                   "bam_ws_sha": code_sha(BAM_WS_SRC.parent, scope=("src/dev/bam_rack_twin/records", "src/dev/bam_rack_twin/bam_rack_twin/fullarm_comp.py",
                                                                   "src/dev/bam_fivebar", "src/dev/bam_fb_test_rig")),
                   **static, "seconds": round(time.monotonic() - started, 1)}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_results(args.out, payload, default=float)
        for cell in payload["cells"]:
            print(json.dumps(cell))
        return 0
    configs = sweep_configs(args.sweep, wrist=args.wrist)[: args.limit]
    for index, config in enumerate(configs):
        config.trace = bool(args.trace_every) and index % args.trace_every == 0
    print(f"{len(configs)} episodes, {args.workers} workers", flush=True)
    for truth in TRUTHS:  # warm the rigs the workers fork with
        build_rig(truth)
    started, results = time.monotonic(), []
    if args.workers > 1:
        from multiprocessing import get_context  # noqa: PLC0415

        with get_context("fork").Pool(args.workers, maxtasksperchild=20) as pool:
            for index, result in enumerate(pool.imap_unordered(_job, configs, chunksize=1)):
                results.append(result)
                if (index + 1) % 10 == 0:
                    print(f"  {index + 1}/{len(configs)}  {time.monotonic() - started:.0f} s", flush=True)
    else:
        results = [_job(config) for config in configs]
    for row in results:
        if row.get("off_home_deg") is not None:
            row["off_home_abs_max"] = float(np.max(np.abs(row["off_home_deg"])))
        if row.get("j1_end_deg") is not None:
            row["j1_end_abs_deg"] = abs(float(row["j1_end_deg"]))
    from sim2real.provenance import code_sha, write_results  # noqa: PLC0415

    payload = {"schema": "sim2real_fullarm_home/1", "sweep": args.sweep, "wrist_mode": args.wrist, "bundle": f"cad-exporter {V2_REF} {V2_SUBDIR}",
               "sim2real_sha": code_sha(Path(__file__).resolve().parents[4]),
               "bam_ws_sha": code_sha(BAM_WS_SRC.parent, scope=("src/dev/bam_fivebar_recovery", "src/dev/bam_fivebar", "src/dev/bam_fb_test_rig",
                                                               "src/dev/bam_rack_twin/records", "src/dev/bam_rack_twin/bam_rack_twin/fullarm_comp.py")),
               "truths": TRUTH_WHY, "wrist_hold": WRIST_HOLD.__dict__, "home_deg": HOME_DEG, "reach_deg": REACH_DEG,
               "runaway_deg_s": RUNAWAY_DEG_S, "current_cap_a": CURRENT_CAP_A, "power_cap_w": POWER_CAP_W,
               "summary": summarize(results), "results": results, "seconds": round(time.monotonic() - started, 1)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_results(args.out, payload, default=float)
    for cell in payload["summary"]["cells"]:
        print(json.dumps(cell, default=float))
    print(f"{len(results)} episodes in {payload['seconds']} s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["COMP_NAMES", "EpisodeConfig", "FullArmPlant", "FullStart", "REAL_STARTS", "ROLES", "TRUTHS", "WRIST_HOLD", "WRIST_MODES",
           "WristHold", "apply_truth", "build_rig", "comp_model", "grid_starts", "in_region_a", "in_region_b", "load_v2_bundle", "place",
           "run_episode", "settle_unpowered", "settle_wrist", "summarize", "sweep_configs", "v2_mount", "v2_root"]
