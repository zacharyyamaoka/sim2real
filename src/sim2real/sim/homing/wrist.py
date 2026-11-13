"""The homing bench's wrist rung: the UR wrist test rig (CAN 14, 15, 16) in MuJoCo, single_touch and press_reverse as robot_msgs
JointCommandSequences, scored by robot_models' five metrics against CAD and against the twin's own stop contacts.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra homing --extra sim python -m sim2real.sim.homing.wrist --out /home/bam/sim2real/src/sim2real/data/homing_wrist_mujoco_2026-11-12.json --workers 3

The plant is bam_ur_wrist's own twin of record, reused, not rewritten (``homing_tview_sim.make_plant``'s recipe): ``KarnoppPlant`` (stick-
slip at the physics rate) on it5's friction and armature (``homing_tview_sim.IT5``), the 583ee39 pending masses, the stops as REAL contacts
between hardstops.json's teeth (``contact_stops``), and gravity as the rig has it - lying on its side (``model.REAL_GRAVITY_BASE_M_S2``: CAN
14 carries ~0.23 N.m). The boards are its moteus loops (kp 75 N.m/rev, the RAM gains), 1.017 N.m cap (2 A), 0.6 ms command delay; the
power-up latches each output inside half a rotor turn (36 deg) of a hidden sub-turn offset - nothing here may assume the encoder reads
the joint.

The two procedures are the five-bar's, re-addressed to three serial drives (the logic is the procedures module's; the joints, caps and
order are the wrist's):

* ``single_touch``: per joint, tip first (bam_ur_wrist.homing.HOME_ORDER: CAN 16, 15, 14 - each seek moves the least mass it can): hold
  the others, seek the homing side (every drive's ``homing_dir`` is -1) at 0.1 rev/s under 1.0 N.m (home_tview's seek), define the CAD
  stop, move home (0); the zero is the stall minus the CAD stop, corrected by the stored table (none here: the plant has no gear model).
* ``press_reverse``: per joint, two levels (half, full cap) on the homing side, define, walk to 3 deg short of the other stop, two levels
  there, home; ``fit`` identifies the gap from the stop span against CAD and zeroes in one run.

What this rung does NOT have (and says so in its results): hidden backlash. bam_ur_wrist's plant is a 3-dof model (``WristModel`` refuses
any other nq) whose Karnopp friction, drive torques and sensing are indexed by those three dofs; gear_backlash's double joints would make it
6. So B0 only: the GIM4305's 0.2 deg backlash (actuator.GIM4305.backlash_rad) is not in this twin, and the B1 / B2 rows are not run.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from robot_models.homing.fit import fit
from robot_models.homing.metrics import EpisodeRecord, JointOutcome, StallCheck, scorecard
from robot_models.homing.types import BacklashModel, BacklashTable, HomingResult, JointBacklash, StallEvidence, StopMap, StopSide
from robot_msgs.control import (
    Elapsed,
    JointCommand,
    JointCommandSequence,
    JointCommandStep,
    Reached,
    Stall,
)
from robot_msgs.sensor import JointState
from robot_msgs.std import Header

from .bench import compact, expand, git_sha, run_phase
from .mujoco_plant import BAM_WS_SRC, bam_ws_path

TAU = 2.0 * math.pi
WRIST_PATHS = ("dev/bam_ur_wrist", "core/bam_robot_descriptions/src")
CAN_IDS = (14, 15, 16)
HOME_ORDER = (16, 15, 14)  # bam_ur_wrist.homing.HOME_ORDER
SEEK_SPEED = 0.1 * TAU  # home_tview: 0.1 rev/s
SEEK_DISTANCE = 1.2 * TAU  # past any stop from any start: a sanity bound, not a travel bound
SEEK_CAP_NM = 1.0  # home_tview's seek "under 1 N.m" (the board gives 1.017)
HOLD_CAP_NM = 1.0
MOVE_SPEED = 0.1 * TAU
REACH_RAD = math.radians(0.5)
PRESS_S = 0.8
STEP_TIMEOUT_S = 40.0
KP_NM_PER_RAD = 75.0 / TAU  # bam_ur_wrist.actuator.RAM_GAINS: kp 75 N.m/rev on every wrist board
EASE_DEG = 3.0
CONTROL_DT = 0.01
GATE_DEG = 0.1  # the MuJoCo rung's zero gate (homing decision report, section 5); there is no kinematic wrist rung to compare with
RUNG = "mujoco"
SOBOL_SEED = 20261112
EDGE_DEG = 2.0


def wrist_path(src: Path = BAM_WS_SRC) -> None:
    bam_ws_path(src)
    for relative in WRIST_PATHS:
        path = str(src / relative)
        if path not in sys.path:
            sys.path.append(path)


def available(src: Path = BAM_WS_SRC) -> bool:
    return all((src / relative).is_dir() for relative in WRIST_PATHS)


# ---------------------------------------------------------------------------------------------------------------- the rig


class WristRig:
    """The bundle, its joint names per CAN id, and the CAD stop map (hardstops.json: each tooth pair's exact first contact)."""

    _cache: dict = {}

    def __init__(self):
        wrist_path()
        from bam_ur_wrist.bundle import default_root, load_bundle  # noqa: PLC0415
        from bam_ur_wrist.stops import hardstop_table  # noqa: PLC0415

        self.root = Path(default_root())
        self.bundle = load_bundle(self.root)
        by_can = {joint.can_id: joint for joint in self.bundle.joints}
        self.joints = tuple(by_can[c].name for c in CAN_IDS)
        self.can = dict(zip(self.joints, CAN_IDS, strict=True))
        self.home = {by_can[c].name: float(by_can[c].home_rad) for c in CAN_IDS}
        self.side = {by_can[c].name: int(by_can[c].homing_dir) for c in CAN_IDS}
        table = hardstop_table(self.bundle)
        sides = []
        for c in CAN_IDS:
            for side, key in ((-1, "lower_deg"), (+1, "upper_deg")):
                sides.append(StopSide(by_can[c].name, side, math.radians(float(table[c][key])), basis="cad",
                                      source="hardstops.json (bam_ur_wrist.stops.hardstop_table)"))
        self.cad = StopMap(tuple(sides), source=f"wrist bundle {self.root}")

    @classmethod
    def get(cls) -> WristRig:
        if "rig" not in cls._cache:
            cls._cache["rig"] = cls()
        return cls._cache["rig"]


@dataclass(frozen=True)
class WristStart:
    """Where the wrist rests at power-up (joint angles, rad, per joint name) and the hidden sub-turn offset each board latches near."""

    name: str
    q_rad: dict
    sub_turn_rad: dict
    branch: str = "export"  # the scorecards' scope field: a serial wrist has one assembly


def starts(rig: WristRig, n_sobol: int = 15) -> list[WristStart]:
    """The real power-up (homing_tview_sim.POWER_UP_DEG: CAN 14 81 deg, CAN 15 -38.6, CAN 16 0) and Sobol draws inside the CAD stops
    (``EDGE_DEG`` in), each with its own hidden sub-turn offsets."""
    from scipy.stats import qmc  # noqa: PLC0415

    lo = {j: rig.cad.q_rad(j, -1) + math.radians(EDGE_DEG) for j in rig.joints}
    hi = {j: rig.cad.q_rad(j, +1) - math.radians(EDGE_DEG) for j in rig.joints}
    sampler = qmc.Sobol(d=6, scramble=True, seed=SOBOL_SEED)
    out = [WristStart("real_power_up", dict(zip(rig.joints, np.radians([81.0, -38.6, 0.0]), strict=True)),
                      dict(zip(rig.joints, (0.11, -0.07, 0.05), strict=True)))]
    # WHY skip a draw whose links interpenetrate (2026-11-12): a start is where the wrist RESTS at power-up; draw 14 put the tip's ArUco
    # holder 6 mm into the base's marker plate and the first tick ejected CAN 15 at 7 rad/s. Draws keep their index as their name, so a
    # name means the same pose in every result; a skipped draw is simply absent.
    k = 0
    while len(out) < n_sobol + 1:
        row = sampler.random(1)[0]
        start = WristStart(f"sobol-{k:02d}", {j: lo[j] + row[i] * (hi[j] - lo[j]) for i, j in enumerate(rig.joints)},
                           {j: (row[3 + i] - 0.5) * math.radians(36.0) for i, j in enumerate(rig.joints)})
        k += 1
        if at_rest(start):
            out.append(start)
        if k > 20 * (n_sobol + 1):
            raise RuntimeError(f"fewer than {n_sobol} collision-free wrist starts in {k} Sobol draws")
    return out


def at_rest(start: WristStart) -> bool:
    """No contact (stop teeth or the self-contact pairs bam_ur_wrist.self_contact adds) at the start pose."""
    import mujoco  # noqa: PLC0415

    plant = WristPlant(gravity=False)
    plant.reset(start)
    mujoco.mj_forward(plant.plant.model, plant.plant.data)
    return int(plant.plant.data.ncon) == 0


# ---------------------------------------------------------------------------------------------------------------- the plant


class WristPlant:
    """bam_ur_wrist's KarnoppPlant behind the homing seam (reset / tick / state / truth, and the log the bench reads). Positions are the
    board's output reading plus the frame the sequence defined; ``truth`` reads the joints and the stop teeth, never seen by a procedure."""

    def __init__(self, kind: str = "B0", *, gravity: bool = True):
        if kind != "B0":
            raise ValueError("the wrist twin has no gear model: B0 only (module docstring)")
        self.kind = kind
        self.rig = WristRig.get()
        self.joint_names = self.rig.joints
        self.gravity = gravity
        self.backlash = {j: BacklashModel("B0") for j in self.joint_names}
        self.plant = None
        self.frame: dict = {}
        self.time = 0.0
        self.log: dict = {}

    def _build(self, start: WristStart):
        wrist_path()
        from bam_ur_wrist.homing_tview_sim import IT5  # noqa: PLC0415
        from bam_ur_wrist.mass_prior import pending_masses  # noqa: PLC0415
        from bam_ur_wrist.model import REAL_GRAVITY_BASE_M_S2, MassTruth  # noqa: PLC0415
        from bam_ur_wrist.plant import KarnoppPlant, PlantTruth  # noqa: PLC0415

        truth = PlantTruth(mass=MassTruth(base=pending_masses(self.rig.bundle)), contact_stops=True, stop_rad=None,
                           sub_turn_offset_rad=tuple(float(start.sub_turn_rad[j]) for j in self.joint_names), **IT5)
        plant = KarnoppPlant(self.rig.bundle, truth, np.array([start.q_rad[j] for j in self.joint_names]),
                             control_period_s=CONTROL_DT)
        if self.gravity:
            plant.model.opt.gravity[:] = np.asarray(REAL_GRAVITY_BASE_M_S2, dtype=float)
        if any(s != 1.0 for s in plant.known_signs):
            raise ValueError("the wrist boards' signs are +1 (the record's servo_map); this adapter assumes it")
        return plant

    def reset(self, start: WristStart) -> JointState:
        self.plant = self._build(start)
        self.reading = self.plant.read()
        self.frame = {j: 0.0 for j in self.joint_names}
        self.time = 0.0
        self.start = start
        self.log = {"t": [], "link": [], "position": [], "effort": [], "touching": [], "setpoint": [], "self_contact": []}
        self._stop_geoms = {g for pair in self.plant.wrist.stop_pairs.values() for side in pair for g in side}
        self._record(None)
        return self.state()

    def _raw(self) -> np.ndarray:
        return np.asarray(self.reading.position_rad, dtype=float)

    def tick(self, command, dt: float, defines=None) -> JointState:
        from moteus_servo import MoteusCommand  # noqa: PLC0415

        if abs(dt - CONTROL_DT) > 1e-12:
            raise ValueError(f"the wrist plant steps {CONTROL_DT} s per tick")
        raw = dict(zip(self.joint_names, self._raw(), strict=True))
        for joint, value in (defines or {}).items():
            self.frame[joint] = float(value) - raw[joint]
        index = {name: i for i, name in enumerate(command.name)}
        cap = np.zeros(len(command.name)) if command.max_effort is None else np.asarray(command.max_effort, dtype=float)
        feedforward = np.zeros(len(command.name)) if command.feedforward_effort is None else np.asarray(command.feedforward_effort, float)
        sends, targets = [], {}
        for joint in self.joint_names:
            i = index.get(joint)
            position = math.nan if i is None else float(command.position[i])
            if i is None or cap[i] <= 0.0 or not math.isfinite(position):
                sends.append(None)
                targets[joint] = None
                continue
            board = position - self.frame[joint]  # the board's own output frame (sign +1)
            targets[joint] = board
            sends.append(MoteusCommand(position_rad=board, feedforward_torque_nm=float(feedforward[i]), ilimit_scale=0.0,
                                       maximum_torque_nm=float(min(cap[i], self.plant.torque_cap_nm[self.joint_names.index(joint)]))))
        self.plant.send(sends)
        self.reading = self.plant.step()
        self.time += dt
        self._record(targets)
        return self.state()

    def state(self) -> JointState:
        raw = self._raw()
        return JointState(name=self.joint_names, position=np.array([raw[i] + self.frame[j] for i, j in enumerate(self.joint_names)]),
                          velocity=np.asarray(self.reading.velocity_rad_s, dtype=float),
                          effort=np.asarray(self.reading.torque_nm, dtype=float), header=Header(stamp=self.time))

    def _touching(self) -> list[str]:
        from bam_ur_wrist.stops import stop_contact  # noqa: PLC0415

        out = []
        q = self.plant.true_q()
        for i, joint in enumerate(self.joint_names):
            pair = self.plant.wrist.stop_pairs.get(self.rig.can[joint])
            on = pair is not None and stop_contact(self.plant.model, self.plant.data, pair)[0]
            out.append(("upper" if q[i] > 0 else "lower") if on else "")
        return out

    def _self_contact(self) -> str:
        """Truth only (never seen by a procedure): the body pairs in contact other than the stop teeth, e.g. the tip's ArUco holder on
        the base's marker plate (bam_ur_wrist.self_contact) - "" when none."""
        model, data = self.plant.model, self.plant.data
        pairs = set()
        for i in range(data.ncon):
            contact = data.contact[i]
            if contact.geom1 in self._stop_geoms or contact.geom2 in self._stop_geoms:
                continue
            pairs.add("|".join(sorted((model.body(model.geom_bodyid[contact.geom1]).name, model.body(model.geom_bodyid[contact.geom2]).name))))
        return ",".join(sorted(pairs))

    def _record(self, targets) -> None:
        raw = self._raw()
        self.log["t"].append(self.time)
        self.log["link"].append(self.plant.true_q().tolist())
        self.log["position"].append([raw[i] + self.frame[j] for i, j in enumerate(self.joint_names)])
        self.log["effort"].append(list(np.asarray(self.reading.torque_nm, dtype=float)))
        self.log["touching"].append(self._touching())
        self.log["self_contact"].append(self._self_contact())
        self.log["setpoint"].append([math.nan if not targets or targets.get(j) is None else targets[j] for j in self.joint_names])

    def truth(self) -> dict:
        servo = self.plant.servo_map_truth
        return {"time_s": self.time, "link_rad": dict(zip(self.joint_names, self.plant.true_q(), strict=True)),
                # q_joint = board + offset (sign +1): the offset a procedure's zero estimates
                "true_offset_rad": dict(zip(self.joint_names, servo.offset_rad, strict=True)),
                "latched_turns": list(self.plant.latched_turns), "frame_rad": dict(self.frame)}


def twin_contacts(*, push_nm: tuple[float, float] = (0.4, 0.8), press_s: float = 1.5) -> dict:
    """``{(joint, side): rad}``: where each wrist joint meets its stop in the twin (the teeth contacts), each pushed alone at two light
    torques from 2 deg inside, gravity off, extrapolated to zero push (the five-bar's mujoco_plant.twin_contacts method)."""
    from robot_msgs.control import ServoCommand  # noqa: PLC0415

    rig = WristRig.get()
    out = {}
    for joint in rig.joints:
        for side in (-1, +1):
            links = []
            for push in push_nm:
                q = {j: 0.0 for j in rig.joints}
                q[joint] = rig.cad.q_rad(joint, side) - side * math.radians(2.0)
                plant = WristPlant(gravity=False)
                state = plant.reset(WristStart("contact", q, {j: 0.0 for j in rig.joints}))
                rest = dict(zip(state.name, state.position, strict=True))
                position = np.array([rest[j] + (side * 0.3 if j == joint else 0.0) for j in rig.joints])
                cap = np.array([push if j == joint else HOLD_CAP_NM for j in rig.joints])
                for _ in range(int(round(press_s / CONTROL_DT))):
                    plant.tick(ServoCommand(name=rig.joints, position=position, max_effort=cap), CONTROL_DT)
                touching = plant.log["touching"][-1][rig.joints.index(joint)]
                if touching != ("upper" if side > 0 else "lower"):
                    raise RuntimeError(f"{joint} pushed {side:+d} at {push} N.m is touching {touching!r}, not its stop")
                links.append(float(plant.plant.true_q()[rig.joints.index(joint)]))
            (p1, p2), (l1, l2) = push_nm, links
            out[(joint, side)] = l1 - (l2 - l1) * p1 / (p2 - p1)
    return out


# ---------------------------------------------------------------------------------------------------------------- the procedures


def _limp(joint):
    return JointCommand.limp(joint)


def _hold(joint):
    return JointCommand.hold(joint, max_effort=HOLD_CAP_NM)


def _seek(joint, side, cap):
    return JointCommand.move_by(joint, side * SEEK_DISTANCE, speed=SEEK_SPEED, max_effort=cap)


def _stall(joint, cap):
    # WHY the lead past the PD's sag under its cap (sag_proof's rule): at kp 11.9 N.m/rad a 1 N.m push needs 0.084 rad of lead, past
    # Stall's default 0.06 - a stall must mean the drive is pressing at its cap, not climbing friction and gravity on the way
    return Stall(joint=joint, lead=0.06 + cap / KP_NM_PER_RAD)


def _step(joints, name, commands, done, *, timeout=STEP_TIMEOUT_S, define=None):
    named = {c.joint for c in commands}
    full = list(commands) + [_limp(j) for j in joints if j not in named]
    return JointCommandStep(name=name, commands=tuple(full), done_when=tuple(done), timeout=timeout, define_position=define or {})


def _reached(joint) -> list:
    """A move's done-when: within 0.5 deg, or - sag_proof's still_at_target, as every five-bar move on this rung - its setpoint arrived
    and the joint still (0.02 rad/s for 0.5 s) within what its PD can sag under its cap. WHY: CAN 14 holds ~0.23 N.m of gravity and up to
    0.175 N.m of static friction on an 11.9 N.m/rad loop - it rests 1-2 deg off any target, which a 0.5 deg reach never accepts."""
    return [Reached(joints=(joint,), tolerance=REACH_RAD),
            Reached(joints=(joint,), tolerance=REACH_RAD + HOLD_CAP_NM / KP_NM_PER_RAD, speed=0.02, dwell=0.5)]


def _to(joint, target, speed=MOVE_SPEED):
    return JointCommand.to(joint, target, speed=speed, max_effort=HOLD_CAP_NM)


def _sequence(joints, name, steps):
    return JointCommandSequence(joint_names=joints, steps=tuple(steps), name=name)


@dataclass
class Reading:
    tick: int
    raw: dict
    effort: dict


def step_ends(phase, joints) -> dict:
    """Step name -> the reading the controller saw when that step's done-when held, in the power-up encoder frame."""
    log = phase.log
    shift = {j: 0.0 for j in joints}
    out, names, previous = {}, [s.name for s in phase.sequence.steps], 0
    for k in range(len(log["t"])):
        seen = dict(zip(joints, log["position"][k], strict=True))
        reading = Reading(k, {j: seen[j] - shift[j] for j in joints}, dict(zip(joints, log["effort"][k], strict=True)))
        count = log["events"][k]
        if count > previous:
            out[names[count - 1]] = reading
            previous = count
        for joint, value in log["defines"][k].items():
            shift[joint] += value - seen[joint]
    return out


@dataclass
class WristProcedure:
    name: str = ""
    references: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def _evidence(self, reading, joint, side) -> StallEvidence:
        self.references.append((0, reading.tick, joint, side))
        return StallEvidence(joint, side, abs(reading.effort[joint]), reading.raw[joint])


@dataclass
class WristSingleTouch(WristProcedure):
    name: str = "single_touch"

    def plan(self, prior, so_far):
        if so_far:
            return None
        rig = WristRig.get()
        joints = rig.joints
        steps = []
        for can in HOME_ORDER:
            joint = joints[CAN_IDS.index(can)]
            side = rig.side[joint]
            others = [_hold(o) for o in joints if o != joint]
            steps.append(_step(joints, f"CAN {can} holds still", [_hold(j) for j in joints], [Elapsed(duration=0.3)], timeout=1.0))
            steps.append(_step(joints, f"CAN {can} seeks", others + [_seek(joint, side, SEEK_CAP_NM)], [_stall(joint, SEEK_CAP_NM)],
                               define={joint: prior.stops.q_rad(joint, side)}))
            steps.append(_step(joints, f"CAN {can} home", others + [_to(joint, rig.home[joint])],
                               _reached(joint)))
        return _sequence(joints, "wrist single touch (tip first)", steps)

    def observe(self, prior, phases) -> HomingResult:
        self.references = []
        rig = WristRig.get()
        ends = step_ends(phases[0], rig.joints)
        evidence = [self._evidence(ends[f"CAN {rig.can[j]} seeks"], j, rig.side[j]) for j in rig.joints]
        stored = prior.table or BacklashTable(tuple(JointBacklash(j, BacklashModel("B0"), source="no stored table") for j in rig.joints))
        result = fit(evidence, prior.stops, table=stored)
        return HomingResult(result.zeros, stored, prior.stops, tuple(evidence), "mujoco")

    def observe_vs_twin(self, prior, twin, phases) -> HomingResult:
        references, notes = list(self.references), dict(self.notes)
        try:
            return self.observe(twin, phases)
        finally:
            self.references, self.notes = references, notes


@dataclass
class WristPressReverse(WristProcedure):
    name: str = "press_reverse"

    def _levels(self, joints, joint, side, tag):
        others = [_hold(o) for o in joints if o != joint]
        return [_step(joints, f"{tag} seek", others + [_seek(joint, side, 0.5 * SEEK_CAP_NM)], [_stall(joint, 0.5 * SEEK_CAP_NM)]),
                _step(joints, f"{tag} press half", others + [_seek(joint, side, 0.5 * SEEK_CAP_NM)], [Elapsed(duration=PRESS_S)]),
                _step(joints, f"{tag} press full", others + [_seek(joint, side, SEEK_CAP_NM)], [Elapsed(duration=PRESS_S)])]

    def plan(self, prior, so_far):
        if so_far:
            return None
        rig = WristRig.get()
        joints = rig.joints
        steps = []
        for can in HOME_ORDER:
            joint = joints[CAN_IDS.index(can)]
            side = rig.side[joint]
            others = [_hold(o) for o in joints if o != joint]
            near, far = prior.stops.q_rad(joint, side), prior.stops.q_rad(joint, -side)
            steps.append(_step(joints, f"CAN {can} holds still", [_hold(j) for j in joints], [Elapsed(duration=0.3)], timeout=1.0))
            steps += self._levels(joints, joint, side, f"CAN {can} near")
            steps.append(_step(joints, f"CAN {can} define", [_hold(j) for j in joints], [Elapsed(duration=0.05)], define={joint: near}))
            steps.append(_step(joints, f"CAN {can} walks across", others + [_to(joint, far + side * math.radians(EASE_DEG))],
                               _reached(joint), timeout=STEP_TIMEOUT_S))
            steps += self._levels(joints, joint, -side, f"CAN {can} far")
            steps.append(_step(joints, f"CAN {can} home", others + [_to(joint, rig.home[joint])],
                               _reached(joint)))
        return _sequence(joints, "wrist press-reverse (tip first)", steps)

    def observe(self, prior, phases) -> HomingResult:
        self.references = []
        rig = WristRig.get()
        ends = step_ends(phases[0], rig.joints)
        evidence = []
        for joint in rig.joints:
            can, side = rig.can[joint], rig.side[joint]
            for tag, s in (("near", side), ("far", -side)):
                evidence.append(self._evidence(ends[f"CAN {can} {tag} press half"], joint, s))
                evidence.append(self._evidence(ends[f"CAN {can} {tag} press full"], joint, s))
        return fit(evidence, prior.stops, identify="B2", rung="mujoco")

    observe_vs_twin = WristSingleTouch.observe_vs_twin


PROCEDURES = {"single_touch": WristSingleTouch, "press_reverse": WristPressReverse}


# ---------------------------------------------------------------------------------------------------------------- the bench


def prior_for(rig: WristRig, stops: StopMap | None = None):
    from robot_models.homing.protocols import Prior  # noqa: PLC0415

    return Prior(stops=stops or rig.cad, joints=rig.joints, seek_side=dict(rig.side), caps_nm={j: SEEK_CAP_NM for j in rig.joints})


def twin_stops(rig: WristRig, contacts: dict) -> StopMap:
    from dataclasses import replace  # noqa: PLC0415

    return StopMap(tuple(replace(s, q_rad=contacts[(s.joint, s.side)], basis="measured", source="the twin's own contact (wrist.twin_contacts)")
                         for s in rig.cad.sides), source="twin contacts")


def run_episode(name: str, start: WristStart, contacts: dict | None) -> tuple[dict, dict]:
    rig = WristRig.get()
    plant = WristPlant()
    prior = prior_for(rig)
    procedure = PROCEDURES[name]()
    plant.reset(start)
    phase = run_phase(plant, procedure.plan(prior, []))
    outcome = "done" if phase.status == "done" else f"{phase.status}: {phase.message}"
    finished = outcome == "done"
    result = procedure.observe(prior, [phase]) if finished else None
    truth = plant.truth()
    stalls, stalled_on_self = [], {}
    for _, tick, joint, side in procedure.references if finished else []:
        row = phase.log["plant_offset"] + tick
        link = plant.log["link"][row][rig.joints.index(joint)]
        stalls.append(StallCheck(joint, side, math.degrees(link), math.degrees(prior.stops.q_rad(joint, side))))
        if plant.log["self_contact"][row]:  # the stall was a link hitting a link, not the drive's stop (truth, for the report)
            stalled_on_self[rig.can[joint]] = plant.log["self_contact"][row]
    joints, twin = [], {}
    twin_result = None
    if result is not None and contacts is not None:
        twin_result = procedure.observe_vs_twin(prior, prior_for(rig, twin_stops(rig, contacts)), [phase])
    for joint in rig.joints:
        error = gap = None
        if result is not None and result.zero(joint) is not None:
            error = math.degrees(result.zero(joint).offset_rad - truth["true_offset_rad"][joint])
            entry = result.backlash.get(joint)
            if entry is not None and entry.gap_observable:
                gap = math.degrees(entry.model.gap_rad)
        if twin_result is not None and twin_result.zero(joint) is not None:
            twin[joint] = math.degrees(twin_result.zero(joint).offset_rad - truth["true_offset_rad"][joint])
        joints.append(JointOutcome(joint, error, gap, 0.0))
    record = EpisodeRecord(name, f"{RUNG} · B0", start.name, finished, outcome, plant.time if finished else None, tuple(stalls), tuple(joints))
    note = {"zero_error_vs_twin_deg": twin, "latched_turns": truth["latched_turns"],
            "start_deg": {rig.can[j]: math.degrees(v) for j, v in start.q_rad.items()},
            "events": [(e.index, e.name, e.outcome, round(e.finished, 2)) for e in phase.events][-4:]}
    if stalled_on_self:
        note["stalled_on_self_contact"] = stalled_on_self
    first = next((k for k, pair in enumerate(plant.log["self_contact"]) if pair), None)
    if first is not None:  # any link-on-link contact in the episode (an aborted run's stall is not a reference, so look at the whole log)
        note["first_self_contact"] = {"t_s": round(plant.log["t"][first], 2), "pair": plant.log["self_contact"][first],
                                      "link_deg": {rig.can[j]: round(math.degrees(v), 2) for j, v in zip(rig.joints, plant.log["link"][first], strict=True)}}
    if not finished:
        note["self_contact_at_end"] = plant.log["self_contact"][-1]
        note["ended_at_deg"] = {rig.can[j]: round(math.degrees(v), 3) for j, v in truth["link_rad"].items()}
    return record.to_dict(), note


def _job(args):
    name, start, contacts = args
    t0 = time.time()
    try:
        record, note = run_episode(name, start, contacts)
    except Exception as error:  # a crash is an outcome, recorded
        rig = WristRig.get()
        record = EpisodeRecord(name, f"{RUNG} · B0", start.name, False, f"crashed: {type(error).__name__}: {error}", None, (),
                               tuple(JointOutcome(j, None, None, 0.0) for j in rig.joints)).to_dict()
        note = {"crash": repr(error)}
    return name, start.name, record, note, time.time() - t0


def run_bench(*, procedures=tuple(PROCEDURES), n_sobol: int = 15, workers: int = 3) -> dict:
    import hashlib  # noqa: PLC0415

    t0 = time.time()
    rig = WristRig.get()
    contacts = twin_contacts()
    all_starts = starts(rig, n_sobol)
    jobs = [(name, start, contacts) for name in procedures for start in all_starts]
    if workers > 1:
        import multiprocessing  # noqa: PLC0415

        with multiprocessing.get_context("fork").Pool(min(workers, 3)) as pool:
            outputs = pool.map(_job, jobs, chunksize=1)
    else:
        outputs = [_job(job) for job in jobs]
    episodes, twin_rows, notes, wall = {}, {}, {}, {}
    role = {j: f"CAN {c}" for j, c in rig.can.items()}
    for name, start, record, note, seconds in outputs:
        episodes.setdefault(name, []).append(compact(record))
        twin = {role[j]: v for j, v in (note.get("zero_error_vs_twin_deg") or {}).items()}
        joints = [dict(j, zero_error_deg=(twin.get(role[j["joint"]]) if j["zero_error_deg"] is not None else None)) for j in record["joints"]]
        twin_rows.setdefault(name, []).append(compact(dict(record, joints=joints)))
        notes.setdefault(name, {})[start] = note
        wall.setdefault(name, []).append(round(seconds, 1))
    cards = {"B0": {n: scorecard([expand(r, n, f"{RUNG} · B0") for r in rows], gate_deg=GATE_DEG) for n, rows in episodes.items()}}
    cards_twin = {"B0": {n: scorecard([expand(r, n, f"{RUNG} · B0") for r in rows], gate_deg=GATE_DEG) for n, rows in twin_rows.items()}}
    verdicts = {"B0": {}}
    for name in episodes:
        card, twin = cards["B0"][name], cards_twin["B0"][name]
        reliable = card["reliability_pct"] == 100.0
        ok = lambda c: c.get("joint_angle_error_deg") is not None and c["joint_angle_error_deg"] <= GATE_DEG  # noqa: E731
        verdicts["B0"][name] = {"reliability_pct": card["reliability_pct"], "reliability_gate_pass": reliable,
                                "zero_p95_deg": card.get("joint_angle_error_deg"), "zero_p95_vs_twin_deg": twin.get("joint_angle_error_deg"),
                                "gate_deg": GATE_DEG, "pass_vs_cad": bool(reliable and ok(card)), "pass": bool(reliable and ok(twin))}
    return {
        "schema": "sim2real_homing_bench/1", "rig": "ur-wrist", "rung": RUNG, "bundle_sha": rig.root.parts[-4], "bundle_root": str(rig.root),
        "hardstops_sha256": hashlib.sha256((rig.root / "hardstops.json").read_bytes()).hexdigest(),
        "sim2real_sha": git_sha(Path(__file__).resolve().parents[4]), "robot_models_sha": git_sha(Path("/home/bam/robot_models")),
        "bam_ws_sha": git_sha(BAM_WS_SRC.parent), "dt_s": CONTROL_DT, "gate_deg": GATE_DEG, "hidden_gap_arcmin": {j: 0.0 for j in rig.joints},
        "plant": {"class": "bam_ur_wrist.plant.KarnoppPlant", "friction_armature": "homing_tview_sim.IT5 (it5)", "masses": "mass_prior.pending_masses",
                  "stops": "contact_stops: hardstops.json teeth as contacts", "gravity": "model.REAL_GRAVITY_BASE_M_S2 (the rig on its side)",
                  "backlash": "none: the 3-dof wrist model has no gear model (module docstring); B1 / B2 not run"},
        "joints": {role[j]: j for j in rig.joints}, "models": ["B0"], "procedures": list(episodes),
        "starts": [{"name": s.name, "branch": s.branch, "link_deg": {j: math.degrees(v) for j, v in s.q_rad.items()},
                    "why": "the real power-up (homing_tview_sim.POWER_UP_DEG)" if s.name == "real_power_up" else "Sobol"} for s in all_starts],
        "twin_contacts_deg": {role[j]: {("upper" if side > 0 else "lower"): {"twin": math.degrees(contacts[(j, side)]),
                                                                          "cad": math.degrees(rig.cad.q_rad(j, side)),
                                                                          "cad_minus_twin": math.degrees(rig.cad.q_rad(j, side) - contacts[(j, side)])}
                                         for side in (+1, -1)} for j in rig.joints},
        "scorecards": cards, "scorecards_vs_twin": cards_twin, "verdicts": verdicts,
        "episode_columns": ["start", "finished", "outcome", "time_s", "stalls [joint, side, link_deg, cad_deg]",
                            "joints [joint, zero_error_deg, gap_identified_deg, gap_truth_deg]"],
        "episodes": {"B0": episodes}, "episodes_vs_twin": {"B0": twin_rows}, "notes": {"B0": notes}, "wall_s": {"B0": wall},
        "seconds": time.time() - t0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--sobol", type=int, default=15)
    parser.add_argument("--procedures", nargs="*", default=list(PROCEDURES))
    args = parser.parse_args(argv)
    results = run_bench(procedures=tuple(args.procedures), n_sobol=args.sobol, workers=min(args.workers, 3))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results))
    for name, v in results["verdicts"]["B0"].items():
        print(f"B0 {name:16s} rel {v['reliability_pct']:6.1f}%  zero p95 vs CAD {v['zero_p95_deg']}  vs twin {v['zero_p95_vs_twin_deg']}  "
              f"{'PASS' if v['pass'] else 'FAIL'}")
    print(f"{results['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PROCEDURES", "WristPlant", "WristPressReverse", "WristRig", "WristSingleTouch", "run_bench", "starts", "twin_contacts"]
