"""``+gff`` for the wrist rung: a wrist homing procedure with CAN 14's gravity feed-forward on every hold and move whose pose the plan knows.

The wrist rig lies on its side, so revolute_11 (CAN 14) carries the distal links as a pendulum; CAN 15 / 16 carry next to nothing
(bam_rack_twin scripts/ur_wrist/home_tview.GRAVITY_MAX_NM: 0.0116 / 0.0022 N.m with the twin's masses +25 %, under their 0.04-0.08 N.m
sliding friction), so only CAN 14 is fed. The comp is the wrist's winning controller's (bam_rack_twin scripts/ur_wrist/
winning_controller_plans.py, gate 3 at every pose on the held-out dwell tape 2026-11-12): ``G sin(q - bottom)``, G 0.26 N.m (CAN 14's
measured gravity amplitude), the bottom at revolute_11's 86 deg CAD gravity rest - in the plans' board frame 86 - 3.74 deg, revolute_11 =
board + 3.74 on that power cycle (records/ur-wrist-test-rig servo_map). The same sign as the twin's own ``WristModel.gravity_torque``
(the torque that holds): the it5 twin's pending masses fit 0.227 N.m, bottom 86.85 deg, exactly a sinusoid; so on the MuJoCo rung the
comp is 15 % heavy and 0.85 deg off the twin - a model error, kept on purpose (the real arm is ~25 % over the twin, run_b).

The feed is the five-bar's rule (gravity_ff, pass 6), on the wrist's one fed joint:

* the poses are the plan's, in CAD, only where the plan KNOWS them (``gravity_ff.step_end_pose``): CAN 14's angle is known only once a
  define has given its frame. Before that - single_touch / single_touch_park's CAN 16 and CAN 15 (park) steps and CAN 14's own seek -
  CAN 14 holds UN-FED at an angle no reading tells (its power-up reading is within 18 deg of 0 whatever the angle,
  bam_ur_wrist.plant.latch_offset). The note lists those steps. On the wrist that hold sags at most G / kp = 0.26 / 11.9 = 1.25 deg (the
  five-bar's un-fed holds ran away because its gravity was 6.6 N.m against a 10 N.m cap; CAN 14's is a quarter of its cap);
* every powered CAN 14 command after that carries the mean of the gravity at the pose its step starts at and the pose it ends at; a move
  of CAN 14 longer than ``WAYPOINT_DEG`` is walked in waypoints that far apart, each fed from its own two ends (a 166 deg walk home from
  the stop crosses the pendulum's whole swing);
* a feed-forward is never more than its command's cap; the seek caps are NOT lifted over gravity (the five-bar's "different cap"): the
  board gives 1.017 N.m (2 A x 0.509 N.m/A) and the seek already asks 1.0.

``observe`` is the inner procedure's: the steps' names, stalls, defines and the detector (``wrist.link_stall_faults``) are unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from robot_models.homing.protocols import Phase, Prior
from robot_models.homing.types import HomingResult
from robot_msgs.control import JointCommandSequence, JointCommandStep, Reached

from .gravity_ff import GFF_SUFFIX, feedforward_for, step_end_pose

CAN14 = "revolute_11"  # wrist.WristRig: CAN 14 = revolute_11 (the bundle names it so; no import, so the rack's venv plans without MuJoCo)
# The winning controller's comp (winning_controller_plans.GRAVITY_NM / GRAVITY_BOTTOM_RAD, CAD frame): module docstring
GRAVITY_NM = 0.26
GRAVITY_BOTTOM_DEG = 86.0
WAYPOINT_DEG = 4.0  # the five-bar's home walk's spacing (gravity_ff.WAYPOINT_DEG)
WAYPOINT_REACH_RAD = 0.06  # the home walk's reach (HomeTuning.reach): 3.4 deg, a waypoint is a hand-off, not a stop


@dataclass(frozen=True)
class WristGravityComp:
    """CAN 14's gravity as the wrist's winning controller sends it: ``torque(pose)`` -> {joint: N.m} (CAN 14 only; the others 0), or
    None where CAN 14's angle is not known. ``scale`` is a model error a pass assumes, never a fit."""

    amplitude_nm: float = GRAVITY_NM
    bottom_deg: float = GRAVITY_BOTTOM_DEG
    scale: float = 1.0
    joint: str = CAN14

    @property
    def comp(self) -> str:
        base = f"winning controller: {self.amplitude_nm:g} N.m sin(q - {self.bottom_deg:g} deg) on CAN 14"
        return base if self.scale == 1.0 else f"{base} x{self.scale:g}"

    def at(self, q_rad: float) -> float:
        return self.scale * self.amplitude_nm * math.sin(float(q_rad) - math.radians(self.bottom_deg))

    def torque(self, pose: dict) -> dict | None:
        q = pose.get(self.joint)
        if q is None:
            return None
        return {j: (self.at(q) if j == self.joint else 0.0) for j in pose}


def _fed(command, feedforward: float | None):
    if feedforward is None or command.mode == "limp":
        return command
    cap = float(command.max_effort)
    return replace(command, feedforward_effort=max(-cap, min(cap, float(feedforward))))


def _fed_step(step: JointCommandStep, start: dict, end: dict, comp: WristGravityComp) -> tuple[JointCommandStep, bool]:
    """``step`` with its powered CAN 14 command fed; returns it and whether CAN 14 was powered and left un-fed (pose unknown)."""
    g_start, g_end = comp.torque(start), comp.torque(end)
    commands, unfed = [], False
    for command in step.commands:
        if command.joint != comp.joint or command.mode == "limp":
            commands.append(command)
            continue
        feedforward = feedforward_for(command, start, end, g_start, g_end)
        unfed = unfed or feedforward is None
        commands.append(_fed(command, feedforward))
    return replace(step, commands=tuple(commands)), unfed


def _waypoints(step: JointCommandStep, start: dict, end: dict, comp: WristGravityComp) -> list[JointCommandStep] | None:
    """A CAN 14 move as waypoints at most WAYPOINT_DEG apart, each fed from its own two ends; None when short or its ends unknown. The
    last piece is the original step (its name and done-when)."""
    joint = comp.joint
    moving = [c for c in step.commands if c.joint == joint and c.mode == "position"]
    if not moving or start.get(joint) is None or end.get(joint) is None:
        return None
    span = abs(end[joint] - start[joint])
    pieces = int(math.ceil(math.degrees(span) / WAYPOINT_DEG - 1e-9))
    if pieces <= 1:
        return None
    out, previous = [], dict(start)
    for k in range(1, pieces + 1):
        pose = dict(end)
        pose[joint] = start[joint] + (end[joint] - start[joint]) * k / pieces
        positioned = tuple(replace(c, position=pose[joint]) if (c.joint == joint and c.mode == "position") else c for c in step.commands)
        piece = replace(step, commands=positioned)
        if k < pieces:
            piece = JointCommandStep(name=f"{step.name} (waypoint {k} of {pieces})", commands=positioned,
                                     done_when=(Reached(joints=(joint,), tolerance=WAYPOINT_REACH_RAD),), timeout=step.timeout)
        fed, _ = _fed_step(piece, previous, pose, comp)
        out.append(fed)
        previous = pose
    return out


def with_wrist_gravity_ff(sequence: JointCommandSequence, prior: Prior, comp: WristGravityComp) -> tuple[JointCommandSequence, dict]:
    """``sequence`` with CAN 14 fed (module docstring); returns it and a note (steps fed, waypoints added, steps CAN 14 holds un-fed)."""
    pose = {j: None for j in sequence.joint_names}
    defined: set = set()
    steps = []
    note = {"comp": comp.comp, "steps_with_ff": 0, "waypoint_steps_added": 0, "unfed_unknown_pose_steps": []}
    for step in sequence.steps:
        end = step_end_pose(step, pose, prior, defined=defined)
        split = _waypoints(step, pose, end, comp)
        if split is not None:
            steps.extend(split)
            note["waypoint_steps_added"] += len(split) - 1
            note["steps_with_ff"] += len(split)
        else:
            fed, unfed = _fed_step(step, pose, end, comp)
            powered = any(c.joint == comp.joint and c.mode != "limp" for c in step.commands)
            if unfed:
                note["unfed_unknown_pose_steps"].append(step.name)
            elif powered:
                note["steps_with_ff"] += 1
            steps.append(fed)
        defined |= set(step.define_position)
        pose = end
    return replace(sequence, steps=tuple(steps), name=f"{sequence.name} + CAN 14 gravity feed-forward"), note


@dataclass
class WristGravityFF:
    """``inner`` (a wrist procedure) with CAN 14's gravity feed-forward; ``observe`` is ``inner``'s."""

    inner: object = None
    comp: WristGravityComp = field(default_factory=WristGravityComp)
    name: str = ""
    plan_note: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.inner is None:
            raise ValueError("WristGravityFF needs an inner procedure")
        self.name = self.inner.name + GFF_SUFFIX

    @property
    def references(self):
        return self.inner.references

    @references.setter
    def references(self, value):
        self.inner.references = list(value)

    @property
    def notes(self):
        return self.inner.notes

    @notes.setter
    def notes(self, value):
        self.inner.notes = dict(value)

    @property
    def stalls(self):
        return self.inner.stalls

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        sequence = self.inner.plan(prior, so_far)
        if sequence is None:
            return None
        sequence, self.plan_note = with_wrist_gravity_ff(sequence, prior, self.comp)
        self.inner.notes["gravity_ff"] = self.plan_note
        return sequence

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        notes = dict(self.inner.notes)
        result = self.inner.observe(prior, phases)
        self.inner.notes = {**notes, **self.inner.notes}
        return result

    def observe_vs_twin(self, prior: Prior, twin: Prior, phases: Sequence[Phase]) -> HomingResult:
        return self.inner.observe_vs_twin(prior, twin, phases)


def wrist_procedure(name: str, procedures: dict, *, comp: WristGravityComp | None = None):
    """A wrist procedure by its row name, ``<name>`` or ``<name>+gff``."""
    if name.endswith(GFF_SUFFIX):
        return WristGravityFF(inner=procedures[name.removesuffix(GFF_SUFFIX)](), comp=comp or WristGravityComp())
    return procedures[name]()


__all__ = ["CAN14", "GRAVITY_BOTTOM_DEG", "GRAVITY_NM", "WAYPOINT_DEG", "WristGravityComp", "WristGravityFF", "with_wrist_gravity_ff",
           "wrist_procedure"]
