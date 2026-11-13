"""The wrist's real rung, prepared: the UR wrist test rig (CAN 14 / 15 / 16 on fdcanusb 272813EF) behind the homing seam, as the five-bar's
RealRigPlant runs the five-bar - the same procedure bytes the MuJoCo rung ran, tick by tick on robot_msgs' JointCommandSequenceController.

Four parts:

* :class:`RealWristPlant` - the ``HomingPlant`` seam over any bus with the rack plant's calls (``read`` / ``send`` / ``step``, and the
  controlled stop's ``hold_here`` / ``holding`` / ``braked`` / ``take_over``): bam_rack_twin's WristBusPlant on the boards, or
  :class:`WristTwinBus` (bam_ur_wrist's KarnoppPlant, the MuJoCo rung's own twin) for the dry run. Frames are host-side (``board + frame``,
  every wrist board's sign +1, records/ur-wrist-test-rig servo_map): a define writes nothing to a board. Time is the tick clock.
* :class:`SelfContactGuard` - the CAD self-contact detector LIVE (``wrist.link_stall_faults`` at every define, not only after the run):
  a define is refused, before it is applied, when the stall it is taken on claims a pose with two links touching on the rig's own CAD
  (``wrist.SelfContactMap``) - the joint pressed a link, not its stop. A working define (single_touch_park's CAN 15 park touch, which the
  procedure replaces) sets no keeping frame and is never itself refused; every keeping stall is checked as soon as every joint has a
  keeping frame - for single_touch_park that is CAN 15's last, defining touch, and the define is refused there. The procedure's own
  ``_checked`` runs the same detector again in ``observe``.
* the wrist's home button - :func:`recovery_sequence`: a robot_msgs JointCommandSequence (run by the JointCommandSequenceController,
  through :func:`real_plant.run_phase_real` like every homing sequence) from any rest to ``READY`` (recover_home_plan.json's targets in
  CAD: CAN 14 on its 86 deg gravity rest, CAN 15 and CAN 16 at 0), one joint at a time, CAN 14 fed with its gravity and walked in 4 deg
  waypoints, in the first joint order whose path the CAD self-contact map clears (recover_home_plan's own order, CAN 15 first, when it
  does). It needs where the wrist IS: a frame of record (the board -> CAD offsets of the last homing, carried by the boards while powered;
  on the twin, its truth). At READY every drive may be let go: CAN 14 rests on its gravity bottom.
* :func:`run_wrist_homing` - per start: the twin placed at the start (a real start is the rest the boards report, or a walk there by
  the home button's sequence, then released); the procedure's sequence through ``run_phase_real`` with the guard and the 86 deg/s runaway
  stop; ``observe``; a stop, a refusal or a trip -> the home button, then the next start.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra homing --extra sim python -m sim2real.sim.homing.wrist_real dryrun --out /home/bam/sim2real/src/sim2real/data/homing_wrist_twin_dryrun_2026-11-13.json
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
from robot_msgs.control import Elapsed, JointCommand, JointCommandSequence, JointCommandStep, Reached, ServoCommand
from robot_msgs.sensor import JointState
from robot_msgs.std import Header

DT = 0.01
TAU = 2.0 * math.pi
JOINTS = ("revolute_11", "revolute_14", "revolute_17")  # wrist.CAN_IDS order: CAN 14, 15, 16 (pinned against WristRig by the tests)
CAN_IDS = (14, 15, 16)
ROLE = {j: f"CAN {c}" for j, c in zip(JOINTS, CAN_IDS, strict=True)}
CAN_OF = dict(zip(JOINTS, CAN_IDS, strict=True))
# recover_home_plan.json's targets (bam_rack_twin scripts/ur_wrist) in CAD: CAN 15 to its origin first (revolute_14 in, out of the
# keep-out pair), CAN 14 to its gravity rest (board 82.26 = CAD 86.0 on the frame of record: revolute_11 = board + 3.74), CAN 16 to its origin
READY_DEG = {"revolute_11": 86.0, "revolute_14": 0.0, "revolute_17": 0.0}
RECOVERY_ORDERS = ((15, 14, 16), (14, 15, 16), (16, 15, 14), (16, 14, 15), (15, 16, 14), (14, 16, 15))
PATH_SAMPLE_DEG = 1.0
TOUCHING_START_SKIP_DEG = 3.0  # a rest ON the self-contact boundary (the band): the first degrees leave it
RECOVERY_SPEED = 0.1 * TAU  # home_tview's v0.1 (36 deg/s)
RECOVERY_CAP_NM = 1.0  # the wrist's every hold and move (wrist.HOLD_CAP_NM)
RECOVERY_REACH_RAD = math.radians(1.5)
STEP_TIMEOUT_S = 40.0
MAX_EPISODE_S = 600.0


def wrist_role() -> dict:
    return dict(ROLE)


# ---------------------------------------------------------------------------------------------------------------- the plant


class RealWristPlant:
    """The wrist as a ``HomingPlant`` (module docstring). ``bus``: the rack plant's calls. ``make_command(position_rad, feedforward_nm,
    cap_nm)``: one drive's board command. ``setup(start)``: puts the wrist at the start and returns a record of it (None: where it is)."""

    joint_names = JOINTS
    drive_joints = JOINTS
    role = ROLE

    def __init__(self, bus, *, make_command: Callable[[float, float, float], Any], setup: Callable[[Any], dict] | None = None,
                 dt: float = DT, wall: Callable[[], float] = time.monotonic):
        self.bus = bus
        self.make_command = make_command
        self.setup = setup
        self.dt = float(dt)
        self.wall = wall
        self.ticks = 0
        self.time = 0.0
        self.frame = {j: 0.0 for j in JOINTS}
        self.reading = None
        self.start_record: dict = {}
        self.log: dict[str, list] = {}

    def reset(self, start=None) -> JointState:
        self.start_record = {"name": None if start is None else getattr(start, "name", str(start))}
        if self.setup is not None and start is not None:
            self.start_record["setup"] = self.setup(start)
        self.ticks, self.time = 0, 0.0
        self.frame = {j: 0.0 for j in JOINTS}
        self.reading = self.bus.read()
        self.start_record.update(board_rad=[float(x) for x in self.reading.position_rad],
                                 mode=[int(m) for m in getattr(self.reading, "mode", (-1, -1, -1))])
        self.log = {"tick": [], "wall": [], "board_rad": [], "velocity_rad_s": [], "torque_nm": [], "setpoint_board_rad": [], "cap_nm": [],
                    "feedforward_nm": [], "mode": []}
        self._record(None)
        return self.state()

    def raw(self, joint: str) -> float:
        return float(self.reading.position_rad[JOINTS.index(joint)])

    def board_deg(self, joint: str) -> float:
        return math.degrees(self.raw(joint))

    def tick(self, command: ServoCommand, dt: float, defines: Mapping[str, float] | None = None) -> JointState:
        if abs(float(dt) - self.dt) > 1e-9:
            raise ValueError(f"the bus steps every {self.dt} s; the controller ticked {dt}")
        for joint, value in (defines or {}).items():
            self.frame[joint] = float(value) - self.raw(joint)
        index = {name: i for i, name in enumerate(command.name)}
        size = len(command.name)
        cap = np.zeros(size) if command.max_effort is None else np.asarray(command.max_effort, dtype=float)
        feedforward = np.zeros(size) if command.feedforward_effort is None else np.asarray(command.feedforward_effort, dtype=float)
        out, sent = [], []
        for joint in JOINTS:
            i = index.get(joint)
            position = math.nan if i is None else float(command.position[i])
            if i is None or cap[i] <= 0.0 or not math.isfinite(position):
                out.append(None)  # limp: the board STOPped
                sent.append((math.nan, 0.0, 0.0))
                continue
            board = position - self.frame[joint]
            out.append(self.make_command(board, float(feedforward[i]), float(cap[i])))
            sent.append((board, float(cap[i]), float(feedforward[i])))
        self.bus.send(out)
        self.reading = self.bus.step()
        self.ticks += 1
        self.time = self.ticks * self.dt
        self._record(sent)
        return self.state()

    def state(self) -> JointState:
        r = self.reading

        def finite(values):
            return [0.0 if not math.isfinite(float(v)) else float(v) for v in values]

        position = finite([self.raw(j) + self.frame[j] for j in JOINTS])
        return JointState(name=JOINTS, position=np.array(position), velocity=np.array(finite(r.velocity_rad_s)),
                          effort=np.array(finite(r.torque_nm)), header=Header(stamp=self.time))

    def truth(self) -> dict:
        out = {"rung": "real", "time_s": self.time, "ticks": self.ticks, "start": dict(self.start_record),
               "board_rad": [float(x) for x in self.reading.position_rad], "frame_rad": dict(self.frame), "true_offset_rad": None,
               "why_no_truth": "the real wrist: the encoders are all there is; the self-contact guard judges each stall"}
        twin = getattr(self.bus, "truth", None)
        if callable(twin):  # the dry run's twin: its hidden offsets, for scoring against the MuJoCo rung (never seen by a procedure)
            out.update(twin())
            out["rung"] = "twin"
        return out

    def _record(self, sent) -> None:
        r = self.reading
        self.log["tick"].append(self.ticks)
        self.log["wall"].append(float(self.wall()))
        self.log["board_rad"].append([float(x) for x in r.position_rad])
        self.log["velocity_rad_s"].append([float(x) for x in r.velocity_rad_s])
        self.log["torque_nm"].append([float(x) for x in r.torque_nm])
        self.log["setpoint_board_rad"].append([s[0] for s in sent] if sent else [math.nan] * 3)
        self.log["cap_nm"].append([s[1] for s in sent] if sent else [0.0] * 3)
        self.log["feedforward_nm"].append([s[2] for s in sent] if sent else [0.0] * 3)
        self.log["mode"].append([int(m) for m in getattr(r, "mode", (-1, -1, -1))])


# ---------------------------------------------------------------------------------------------------------------- the live detector


@dataclass
class SelfContactGuard:
    """``wrist.link_stall_faults`` live, at every define (module docstring). ``contact_map``: anything with ``pairs(q_rad) -> str`` (the
    rig's ``wrist.SelfContactMap``). ``working``: step-name markers of a define that sets a working frame (replaced later by the
    procedure, so never kept and never itself judged)."""

    contact_map: Any = None
    working: tuple[str, ...] = (" park ",)
    checks: list = field(default_factory=list)
    frames: dict = field(default_factory=dict)
    stalls: list = field(default_factory=list)

    def _map(self):
        if self.contact_map is None:
            from .wrist import SelfContactMap  # noqa: PLC0415

            self.contact_map = SelfContactMap.get()
        return self.contact_map

    def check(self, plant, defines: Mapping[str, float], step_name: str) -> str | None:
        raw = {j: plant.raw(j) for j in plant.drive_joints}
        working = any(marker in f" {step_name} " for marker in self.working)
        for joint, value in defines.items():
            if working:
                self.frames.pop(joint, None)  # the joint's keeping frame is gone until a keeping define gives it again
            else:
                self.frames[joint] = float(value) - raw[joint]
                self.stalls.append((joint, dict(raw), step_name))
        entry: dict[str, Any] = {"step": step_name, "defines": {ROLE.get(j, j): math.degrees(v) for j, v in defines.items()},
                                 "working": working, "tick": getattr(plant, "ticks", None)}
        faults = []
        if not working and all(j in self.frames for j in plant.drive_joints):
            started = time.monotonic()
            for joint, stall_raw, name in self.stalls:
                pose = {j: stall_raw[j] + self.frames[j] for j in plant.drive_joints}
                pair = self._map().pairs(pose)
                if pair:
                    where = ", ".join(f"{ROLE.get(j, j)} {math.degrees(v):.1f}" for j, v in pose.items())
                    faults.append(f"{ROLE.get(joint, joint)}'s stall in {name!r} claims a pose with {pair} touching ({where} deg): it "
                                  "pressed a link, not its stop")
            entry["judged"] = len(self.stalls)
            entry["map_s"] = round(time.monotonic() - started, 4)
        entry["pass"] = not faults
        self.checks.append(entry)
        if faults:
            return "self-contact guard: " + "; ".join(faults)
        return None


# ---------------------------------------------------------------------------------------------------------------- the twin bus


@dataclass
class TwinReading:
    position_rad: np.ndarray
    velocity_rad_s: np.ndarray
    torque_nm: np.ndarray
    mode: tuple
    t_s: float = 0.0


class WristTwinBus:
    """bam_ur_wrist's KarnoppPlant (``wrist.WristPlant``'s, the MuJoCo rung's own twin) behind the rack plant's calls: board frame, one
    command per drive (``moteus_servo.MoteusCommand`` or None = STOP), the controlled stop (``hold_here`` latches every powered drive where
    it is; ``take_over`` lifts it), ``release`` (STOP everything, read back), ``truth`` (its hidden offsets and link angles)."""

    control_period_s = DT

    def __init__(self, start, *, gravity: bool = True):
        from .wrist import WristPlant  # noqa: PLC0415

        self.twin = WristPlant(gravity=gravity)
        self.twin.reset(start)
        self._pending: list = [None, None, None]
        self._modes = [0, 0, 0]
        self.held: dict | None = None
        self.held_stops: list = []
        self.release_record: dict | None = None

    @property
    def holding(self) -> bool:
        return self.held is not None

    @property
    def braked(self) -> bool:
        return False

    def _reading(self) -> TwinReading:
        r = self.twin.reading
        return TwinReading(np.asarray(r.position_rad, dtype=float).copy(), np.asarray(r.velocity_rad_s, dtype=float).copy(),
                           np.asarray(r.torque_nm, dtype=float).copy(), tuple(self._modes), self.twin.time)

    def read(self) -> TwinReading:
        return self._reading()

    def send(self, commands) -> None:
        if len(commands) != 3:
            raise ValueError("one command per wrist drive (CAN 14, 15, 16)")
        if self.held is not None and any(c is not None for c in commands):
            raise RuntimeError(f"REFUSED: the wrist holds where the controlled stop found it ({self.held['reason']}); take_over() first")
        self._pending = list(commands)

    def hold_here(self, reason: str) -> None:
        from moteus_servo import MoteusCommand  # noqa: PLC0415

        reading = self._reading()
        drives = []
        for i, last in enumerate(self._pending):
            drives.append(None if last is None else MoteusCommand(position_rad=float(reading.position_rad[i]),
                                                                  feedforward_torque_nm=float(last.feedforward_torque_nm),
                                                                  ilimit_scale=0.0, maximum_torque_nm=last.maximum_torque_nm))
        self.held = {"reason": reason, "drives": drives}
        self.held_stops.append({"t_s": self.twin.time, "reason": reason, "board_rad": reading.position_rad.tolist()})
        self._pending = drives

    def take_over(self) -> list:
        drives = list(self.held["drives"]) if self.held else []
        self.held = None
        return drives

    def step(self) -> TwinReading:
        pending = self.held["drives"] if self.held is not None else self._pending
        plant = self.twin.plant
        sends = []
        for i, command in enumerate(pending):
            if command is None:
                sends.append(None)
                continue
            cap = command.maximum_torque_nm
            cap = plant.torque_cap_nm[i] if cap is None else min(float(cap), float(plant.torque_cap_nm[i]))
            sends.append(replace(command, maximum_torque_nm=cap))
        self._modes = [0 if c is None else 10 for c in pending]
        plant.send(sends)
        self.twin.reading = plant.step()
        self.twin.time += DT
        targets = {j: (None if c is None else float(c.position_rad)) for j, c in zip(JOINTS, pending, strict=True)}
        self.twin._record(targets)
        return self._reading()

    def release(self, ticks: int = 30) -> dict:
        """STOP every drive and read it back (the bus plant's close: ``release_record``)."""
        self.held = None
        self._pending = [None, None, None]
        for _ in range(ticks):
            self.step()
        self.release_record = {"released": all(m == 0 for m in self._modes), "modes": dict(zip(CAN_IDS, self._modes, strict=True)),
                               "why": "the twin: every drive STOPped and read back mode 0"}
        return self.release_record

    def truth(self) -> dict:
        t = self.twin.truth()
        return {"true_offset_rad": t["true_offset_rad"], "link_rad": t["link_rad"], "latched_turns": t["latched_turns"]}

    def self_contact_log(self) -> list:
        return list(self.twin.log["self_contact"])


def twin_command(position_rad: float, feedforward_nm: float, cap_nm: float):
    """The dry run's board command: what wrist.WristPlant.tick sends (a PD: ilimit_scale 0, no velocity target)."""
    from moteus_servo import MoteusCommand  # noqa: PLC0415

    return MoteusCommand(position_rad=float(position_rad), feedforward_torque_nm=float(feedforward_nm), ilimit_scale=0.0,
                         maximum_torque_nm=float(cap_nm))


# ---------------------------------------------------------------------------------------------------------------- the home button


def path_contacts(rest: Mapping[str, float], ready: Mapping[str, float], order: tuple[int, ...], contact_map) -> list[str]:
    """Where moving one joint at a time in ``order`` from ``rest`` to ``ready`` (CAD rad) touches on the CAD self-contact map, sampled every
    PATH_SAMPLE_DEG; a rest already touching (on the band's edge) may leave it within TOUCHING_START_SKIP_DEG of its start. [] = clear."""
    pose = dict(rest)
    touching_at_rest = bool(contact_map.pairs(pose))
    out, first = [], True
    for can in order:
        joint = JOINTS[CAN_IDS.index(can)]
        span = ready[joint] - pose[joint]
        steps = int(math.ceil(abs(math.degrees(span)) / PATH_SAMPLE_DEG))
        for k in range(1, steps + 1):
            sample = dict(pose)
            sample[joint] = pose[joint] + span * k / steps
            if first and touching_at_rest and abs(math.degrees(span * k / steps)) <= TOUCHING_START_SKIP_DEG:
                continue
            pair = contact_map.pairs(sample)
            if pair:
                out.append(f"CAN {can} at {math.degrees(sample[joint]):.1f} deg: {pair}")
                break
        pose[joint] = ready[joint]
        first = False
    return out


def recovery_order(rest: Mapping[str, float], ready: Mapping[str, float], contact_map) -> tuple[tuple[int, ...] | None, dict]:
    """The first of RECOVERY_ORDERS whose one-joint-at-a-time path the CAD map clears; (None, why) when none does."""
    rejected = {}
    for order in RECOVERY_ORDERS:
        hits = path_contacts(rest, ready, order, contact_map)
        if not hits:
            return order, rejected
        rejected[",".join(map(str, order))] = hits[0]
    return None, rejected


def recovery_sequence(rest: Mapping[str, float], target: Mapping[str, float], offset: Mapping[str, float], order: tuple[int, ...], *,
                      comp=None, name: str = "wrist home button") -> JointCommandSequence:
    """The wrist's home button: from ``rest`` to ``target`` (CAD rad), one joint at a time in ``order``, every target written in the
    board frame (CAD = board + ``offset``, the frame of record), every hold and move of CAN 14 fed with its gravity (``comp``: wrist_gff's
    WristGravityComp) at the mean of its step's two ends, CAN 14 walked in WAYPOINT_DEG waypoints. Ends holding everything at ``target``."""
    from .wrist_gff import WAYPOINT_DEG, WAYPOINT_REACH_RAD, WristGravityComp  # noqa: PLC0415

    comp = comp or WristGravityComp()
    can14 = JOINTS[0]
    pose = dict(rest)

    def board(joint, q):
        return float(q) - float(offset[joint])

    def ff(q_start, q_end):
        return 0.5 * (comp.at(q_start) + comp.at(q_end))

    def holds(skip=None, *, q14_end=None):
        out = []
        for joint in JOINTS:
            if joint == skip:
                continue
            feed = ff(pose[can14], pose[can14] if q14_end is None else q14_end) if joint == can14 else 0.0
            out.append(JointCommand.hold(joint, max_effort=RECOVERY_CAP_NM, feedforward_effort=feed))
        return out

    steps = [JointCommandStep(name="recover: hold where it rests", commands=tuple(holds()), done_when=(Elapsed(duration=0.3),), timeout=1.0)]
    for can in order:
        joint = JOINTS[CAN_IDS.index(can)]
        goal = float(target[joint])
        if abs(goal - pose[joint]) < math.radians(0.5):
            continue
        pieces = max(1, int(math.ceil(abs(math.degrees(goal - pose[joint])) / WAYPOINT_DEG - 1e-9))) if joint == can14 else 1
        start = pose[joint]
        for k in range(1, pieces + 1):
            q = start + (goal - start) * k / pieces
            feed = ff(pose[joint], q) if joint == can14 else 0.0
            move = JointCommand.to(joint, board(joint, q), speed=RECOVERY_SPEED, max_effort=RECOVERY_CAP_NM, feedforward_effort=feed)
            last = k == pieces
            done = ((Reached(joints=(joint,), tolerance=RECOVERY_REACH_RAD),
                     Reached(joints=(joint,), tolerance=RECOVERY_REACH_RAD + RECOVERY_CAP_NM / (75.0 / TAU), speed=0.02, dwell=0.5))
                    if last else (Reached(joints=(joint,), tolerance=WAYPOINT_REACH_RAD),))
            label = f"recover: CAN {can} to {math.degrees(goal):.1f} deg" + ("" if last else f" (waypoint {k} of {pieces})")
            steps.append(JointCommandStep(name=label, commands=tuple(holds(joint)) + (move,), done_when=done, timeout=STEP_TIMEOUT_S))
            pose[joint] = q
    steps.append(JointCommandStep(name="recover: hold at the target", commands=tuple(holds()), done_when=(Elapsed(duration=0.5),), timeout=1.0))
    return JointCommandSequence(joint_names=JOINTS, steps=tuple(steps), name=f"{name} (order {', '.join(f'CAN {c}' for c in order)})")


def run_recovery(plant: RealWristPlant, offset: Mapping[str, float], *, target: Mapping[str, float] | None = None, contact_map=None,
                 comp=None, label: str = "home button", is_trip: Callable[[BaseException], bool] = lambda error: False) -> dict:
    """The home button on ``plant``: read where the wrist is (board + ``offset``), pick the order, run the sequence through
    ``run_phase_real`` (runaway stop on), then let every drive go (the bus's ``release`` when it has one, else STOP). Returns its record."""
    from .real_plant import SequenceStopped, run_phase_real  # noqa: PLC0415

    if contact_map is None:
        from .wrist import SelfContactMap  # noqa: PLC0415

        contact_map = SelfContactMap.get()
    target = dict(target or {j: math.radians(v) for j, v in READY_DEG.items()})
    if getattr(plant.bus, "braked", False):
        # WHY refused (the five-bar's rule, fivebar_plant.take_over): a lost bus or a board fault braked the wrist - nothing takes over a
        # brake; a human looks first. The bus plant's close lifts the brake once the drives are still.
        return {"label": label, "result": "refused", "why": "the bus plant braked the wrist (a lost bus or a board fault)",
                "release": {"released": False, "why": "braked by the bus plant: its close releases it once still"}}
    if getattr(plant.bus, "holding", False):
        plant.bus.take_over()
    reading = plant.bus.read()
    rest = {j: float(reading.position_rad[i]) + float(offset[j]) for i, j in enumerate(JOINTS)}
    order, rejected = recovery_order(rest, target, contact_map)
    record: dict[str, Any] = {"label": label, "rest_deg": {ROLE[j]: round(math.degrees(v), 3) for j, v in rest.items()},
                              "target_deg": {ROLE[j]: round(math.degrees(v), 3) for j, v in target.items()},
                              "rest_touching": contact_map.pairs(rest), "orders_rejected": rejected}
    if order is None:
        record.update(result="refused", why="no joint order clears the CAD self-contact map from this rest: a human looks first")
        return record
    record["order"] = list(order)
    sequence = recovery_sequence(rest, target, offset, order, comp=comp)
    plant.frame = {j: 0.0 for j in JOINTS}  # the sequence is written in the board frame
    peaks: dict = {}
    try:
        phase = run_phase_real(plant, sequence, guard=None, dt=plant.dt, peaks=peaks, is_trip=is_trip)
        record.update(result=phase.status if phase.status != "done" else "at target", message=phase.message)
    except SequenceStopped as stop:
        record.update(result=f"stopped ({stop.kind})", message=str(stop))
    record["peak_powered_deg_s"] = _peaks(peaks)
    end = plant.bus.read()
    record["end_deg"] = {ROLE[j]: round(math.degrees(float(end.position_rad[i]) + float(offset[j])), 3) for i, j in enumerate(JOINTS)}
    record["end_off_target_deg"] = {ROLE[j]: round(math.degrees(float(end.position_rad[i]) + float(offset[j]) - target[j]), 3)
                                    for i, j in enumerate(JOINTS)}
    if getattr(plant.bus, "holding", False) and not getattr(plant.bus, "braked", False):
        plant.bus.take_over()
    release = getattr(plant.bus, "release", None)
    if getattr(plant.bus, "braked", False):
        # a lost bus or a board fault braked the wrist: nothing takes over and nothing is sent (the bus plant's close decides when
        # the brake may be lifted); recorded as such
        record["release"] = {"released": False, "why": "braked by the bus plant: its close releases it once still"}
        return record
    if callable(release):
        record["release"] = release()
    else:
        plant.bus.send([None, None, None])
        plant.bus.step()
        record["release"] = {"released": None, "why": "STOP sent; the bus plant's close reads it back"}
    settled = plant.bus.read()
    record["released_rest_deg"] = {ROLE[j]: round(math.degrees(float(settled.position_rad[i]) + float(offset[j])), 3)
                                   for i, j in enumerate(JOINTS)}
    return record


def _peaks(peaks: dict) -> dict:
    out: dict = {}
    for (step, role, kind), speed in peaks.items():
        if kind == "powered":
            out[role] = max(out.get(role, 0.0), round(math.degrees(speed), 2))
    return out


# ---------------------------------------------------------------------------------------------------------------- the runner


def prepare_wrist(name: str) -> dict:
    """Before any bus opens: the CAD prior, the procedure and its planned sequence, and the self-contact map (MuJoCo, built here so no
    powered tick waits on it)."""
    from .wrist import SelfContactMap, WristRig, make, prior_for  # noqa: PLC0415

    rig = WristRig.get()
    if tuple(rig.joints) != JOINTS or tuple(rig.can[j] for j in rig.joints) != CAN_IDS:
        raise RuntimeError(f"the wrist bundle names {rig.joints}: the real rung's JOINTS are {JOINTS}")
    prior = prior_for(rig)
    procedure = make(name)
    sequence = procedure.plan(prior, [])
    contact_map = SelfContactMap.get()
    contact_map.pairs({j: 0.0 for j in JOINTS})  # warm
    return {"name": name, "rig": rig, "prior": prior, "procedure": procedure, "sequence": sequence, "contact_map": contact_map,
            "steps": len(sequence.steps), "max_cap_nm": {ROLE[j]: max(float(c.max_effort or 0.0) for s in sequence.steps for c in s.commands
                                                                        if c.joint == j) for j in JOINTS}}


def run_episode_on(plant: RealWristPlant, prepared: dict, *, start=None, runaway_rad_s: float | None = None,
                   is_trip: Callable[[BaseException], bool] = lambda error: False) -> tuple[dict, Any, Any]:
    """One homing episode on ``plant`` (reset at ``start``): the sequence with the live guard and the runaway stop, then ``observe``.
    Returns (record, phase, result)."""
    from .procedures import HomingRefused  # noqa: PLC0415
    from .real_plant import RUNAWAY_RAD_S, SequenceStopped, run_phase_real  # noqa: PLC0415

    procedure, prior, sequence = prepared["procedure"], prepared["prior"], prepared["sequence"]
    procedure.references, procedure.notes = [], {}
    guard = SelfContactGuard(prepared["contact_map"])
    record: dict[str, Any] = {"procedure": prepared["name"], "start": getattr(start, "name", None)}
    plant.reset(start)
    record["start_record"] = plant.start_record
    peaks: dict = {}
    phase, result, incident = None, None, None
    try:
        phase = run_phase_real(plant, sequence, guard=guard, dt=plant.dt, limit_s=MAX_EPISODE_S,
                               runaway_rad_s=RUNAWAY_RAD_S if runaway_rad_s is None else runaway_rad_s, peaks=peaks, is_trip=is_trip)
        record["status"], record["message"] = phase.status, phase.message
        if phase.status == "done":
            try:
                result = procedure.observe(prior, [phase])
            except HomingRefused as error:
                record["refused"] = f"HomingRefused: {error}"
    except SequenceStopped as stop:
        phase = stop.phase
        incident = {"kind": stop.kind, "message": str(stop), "tick": plant.ticks, "time_s": plant.time}
        record["status"], record["message"] = "stopped", str(stop)
    record["incident"] = incident
    record["guard_checks"] = guard.checks
    record["peak_powered_deg_s"] = _peaks(peaks)
    record["time_s"] = plant.time if (phase is not None and phase.status == "done") else None
    if phase is not None:
        record["events"] = [(e.index, e.name, e.outcome, round(e.finished, 2)) for e in phase.events][-4:]
    record["notes"] = json.loads(json.dumps(procedure.notes, default=str))
    if result is not None:
        record["zeros_deg"] = {ROLE[z.joint]: math.degrees(z.offset_rad) for z in result.zeros}
        record["evidence"] = [{"joint": ROLE[e.joint], "side": e.side, "torque_nm": e.torque_nm, "raw_deg": math.degrees(e.motor_raw_rad)}
                              for e in result.evidence]
    record["finished"] = bool(result is not None and incident is None and "refused" not in record)
    return record, phase, result


def _twin_contacts_from(mujoco: dict) -> dict:
    roles = {f"CAN {c}": j for j, c in zip(JOINTS, CAN_IDS, strict=True)}
    return {(roles[role], +1 if side == "upper" else -1): math.radians(entry["twin"])
            for role, sides in mujoco["twin_contacts_deg"].items() for side, entry in sides.items()}


def run_twin_homing(name: str, start_names: list[str] | None = None, *, mujoco_json: Path | None = None, out_dir: Path | None = None,
                    recover_after: bool = True) -> dict:
    """The dry run (``--twin``): every start on a fresh twin through the real runner path (RealWristPlant, ``run_phase_real``, the live
    guard, the runaway stop, the home button after any stop and at the end), scored against the twin's truth and against the MuJoCo rung's
    episode from the same start."""
    from .wrist import WristRig, prior_for, starts as wrist_starts, twin_stops  # noqa: PLC0415

    prepared = prepare_wrist(name)
    rig = WristRig.get()
    by_name = {s.name: s for s in wrist_starts(rig)}
    chosen = [by_name[n] for n in (start_names or list(by_name))]
    mujoco = json.loads(Path(mujoco_json).read_text()) if mujoco_json else None
    twin_prior = prior_for(rig, twin_stops(rig, _twin_contacts_from(mujoco))) if mujoco else None
    reference_name = name.removesuffix("+gff")
    episodes = []
    for start in chosen:
        bus = WristTwinBus(start)
        plant = RealWristPlant(bus, make_command=twin_command)
        began = time.monotonic()
        record, phase, result = run_episode_on(plant, prepared, start=start)
        record["wall_s"] = round(time.monotonic() - began, 1)
        truth = bus.truth()
        record["truth_offset_deg"] = {ROLE[j]: math.degrees(v) for j, v in truth["true_offset_rad"].items()}
        if result is not None:
            record["zero_error_deg"] = {ROLE[z.joint]: math.degrees(z.offset_rad - truth["true_offset_rad"][z.joint]) for z in result.zeros}
            if twin_prior is not None:
                twin_result = prepared["procedure"].observe_vs_twin(prepared["prior"], twin_prior, [phase])
                record["zero_error_vs_twin_deg"] = {ROLE[z.joint]: math.degrees(z.offset_rad - truth["true_offset_rad"][z.joint])
                                                    for z in twin_result.zeros}
        contacts = [pair for pair in bus.self_contact_log() if pair]
        record["self_contact_ticks"] = len(contacts)
        if mujoco is not None:
            rows = {r[0]: r for r in mujoco["episodes"]["B0"].get(reference_name, [])}
            twin_rows = {r[0]: r for r in mujoco["episodes_vs_twin"]["B0"].get(reference_name, [])}
            ref = rows.get(start.name)
            if ref is not None:
                ref_twin = twin_rows[start.name]
                record["mujoco"] = {"row": reference_name, "finished": ref[1], "outcome": ref[2], "time_s": ref[3],
                                    "zero_error_deg": {ROLE[j[0]]: j[1] for j in ref[5]},
                                    "zero_error_vs_twin_deg": {ROLE[j[0]]: j[1] for j in ref_twin[5]}}
                if record.get("zero_error_deg"):
                    record["dryrun_minus_mujoco_deg"] = {role: record["zero_error_deg"][role] - v for role, v in
                                                         record["mujoco"]["zero_error_deg"].items() if v is not None}
        if recover_after:
            offset = truth["true_offset_rad"]  # the twin's frame of record: its truth (the real arm's is the last homing, carried)
            record["home_button"] = run_recovery(plant, offset, contact_map=prepared["contact_map"], label="end of episode")
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(out_dir / f"{start.name}.npz", **{f"plant_{k}": np.asarray(v, dtype=float) for k, v in plant.log.items()})
        episodes.append(record)
        print(json.dumps({k: record.get(k) for k in ("start", "finished", "status", "zero_error_vs_twin_deg", "dryrun_minus_mujoco_deg",
                                                     "peak_powered_deg_s")}, default=float), flush=True)
    return {"procedure": name, "plan": {"steps": prepared["steps"], "max_cap_nm": prepared["max_cap_nm"],
                                        "gravity_ff": prepared["procedure"].notes.get("gravity_ff")}, "episodes": episodes}


# ---------------------------------------------------------------------------------------------------------------- recovery proof


def band_starts(contact_map, *, clear_deg: float = 0.3) -> list:
    """Rests on the edge of the self-contact band: for CAN 14 at +-110 / 125 / 150 deg (CAN 16 0), CAN 15 walked out from 0 until the
    holder meets the plate, and stopped ``clear_deg`` short (the twin's gravity then lays it on the plate)."""
    from .wrist import WristStart  # noqa: PLC0415

    out = []
    for q14 in (110.0, 125.0, 150.0, -110.0, -125.0, -150.0):
        for direction in (-1, +1):
            q15 = 0.0
            while abs(q15) < 168.0:
                trial = q15 + direction * 0.25
                pose = {JOINTS[0]: math.radians(q14), JOINTS[1]: math.radians(trial), JOINTS[2]: 0.0}
                if contact_map.pairs(pose):
                    break
                q15 = trial
            if abs(q15) >= 168.0:
                continue
            q15 -= direction * clear_deg
            out.append(WristStart(f"band {q14:+.0f}/{q15:+.1f}", {JOINTS[0]: math.radians(q14), JOINTS[1]: math.radians(q15), JOINTS[2]: 0.0},
                                  {j: 0.0 for j in JOINTS}))
    return out


def prove_recovery(start_names: list[str] | None = None, *, include_band: bool = True) -> dict:
    """The home button on the twin from the wrist rung's starts (and the band's edge): every one must end at READY, within the reach,
    released, with no self-contact on the way (truth) and no runaway."""
    from .wrist import SelfContactMap, WristRig, starts as wrist_starts  # noqa: PLC0415

    rig = WristRig.get()
    contact_map = SelfContactMap.get()
    starts = [s for s in wrist_starts(rig) if start_names is None or s.name in start_names]
    if include_band:
        starts += band_starts(contact_map)
    rows = []
    for start in starts:
        bus = WristTwinBus(start)
        plant = RealWristPlant(bus, make_command=twin_command)
        plant.reset(None)
        offset = bus.truth()["true_offset_rad"]
        began = time.monotonic()
        record = run_recovery(plant, offset, contact_map=contact_map, label=f"from {start.name}")
        record["start"] = start.name
        record["start_deg"] = {ROLE[j]: round(math.degrees(v), 2) for j, v in start.q_rad.items()}
        log = bus.self_contact_log()
        record["self_contact_ticks"] = sum(1 for pair in log if pair)
        record["self_contact_after_first_s"] = sum(1 for pair in log[50:] if pair)
        off = record.get("end_off_target_deg") or {}
        record["pass"] = bool(record.get("result") == "at target" and off and max(abs(v) for v in off.values()) <= math.degrees(
            RECOVERY_REACH_RAD + RECOVERY_CAP_NM / (75.0 / TAU)) and (record.get("release") or {}).get("released"))
        record["wall_s"] = round(time.monotonic() - began, 1)
        rows.append(record)
        print(json.dumps({k: record.get(k) for k in ("start", "order", "result", "end_off_target_deg", "peak_powered_deg_s", "pass",
                                                     "self_contact_after_first_s")}, default=float), flush=True)
    return {"ready_deg": READY_DEG, "reach_deg": math.degrees(RECOVERY_REACH_RAD), "rows": rows,
            "passed": sum(1 for r in rows if r["pass"]), "total": len(rows)}


def main(argv=None) -> int:
    from sim2real.provenance import write_results  # noqa: PLC0415

    from .bench import git_sha  # noqa: PLC0415
    from .mujoco_plant import BAM_WS_SRC  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("dryrun", help="the twin dry run through the real runner path, scored against the MuJoCo rung")
    d.add_argument("--procedure", default="single_touch_park+gff")
    d.add_argument("--starts", default="real_power_up,sobol-01,sobol-03,sobol-12")
    d.add_argument("--mujoco-json", type=Path, default=Path(__file__).resolve().parents[2] / "data" / "homing_wrist_mujoco_pass5_2026-11-12.json")
    d.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("recover", help="the home button on the twin from the wrist rung's starts and the band's edge")
    r.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    t0 = time.time()
    stamps = {"sim2real_sha": git_sha(Path(__file__).resolve().parents[4]), "robot_models_sha": git_sha(Path("/home/bam/robot_models")),
              "bam_ws_sha": git_sha(BAM_WS_SRC.parent)}
    if args.command == "dryrun":
        body = run_twin_homing(args.procedure, [s for s in args.starts.split(",") if s], mujoco_json=args.mujoco_json)
        body["mujoco_json"] = str(args.mujoco_json)
        schema = "sim2real_homing_wrist_dryrun/1"
    else:
        body = prove_recovery()
        schema = "sim2real_homing_wrist_recovery/1"
    results = {"schema": schema, "rig": "ur-wrist", **stamps, **body, "seconds": time.time() - t0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_results(args.out, results, indent=1, default=float, newline=True)
    print(f"wrote {args.out} in {results['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CAN_IDS", "JOINTS", "READY_DEG", "ROLE", "RealWristPlant", "SelfContactGuard", "WristTwinBus", "band_starts", "path_contacts",
           "prepare_wrist", "prove_recovery", "recovery_order", "recovery_sequence", "run_episode_on", "run_recovery", "run_twin_homing",
           "twin_command"]
