"""``+gff``: a homing procedure with the real home button's gravity feed-forward - a NEW leaderboard row beside the original.

The MuJoCo rung (2026-11-12, pass 3) showed why repeat_checked_seek, two_level_touch and press_reverse home on 2 of 16 starts: their
half-cap touches (J2 5 N.m, C1 3.5 N.m) cannot lift the arm onto the upper stops, where holding it takes J2 5.7 N.m and C1 4.2 N.m on the
twin (6.6 / 4.6 by the home button's identified comp), so the first touch is a stall short of the stop and the frame is defined there.
The two starts that home are the ones with J1 on a stop at +-90 deg, where the five-bar's plane is level and gravity on J2 / C1 is nil
(the twin's holding torque scales with cos J1 exactly: 5.72 / 4.04 / 0.00 N.m at J1 0 / 45 / 90 deg).

The coordinator's decision (2026-11-12): a candidate may become gravity-aware - a parameter of the benchmark candidate, not Zach's spec -
by reusing the home button's approach (``bam_fivebar_recovery.home.walk_home_sequence``), not by raising caps blindly; a design that
genuinely needs a different cap is a new named variant. So ``<name>+gff`` is ``<name>`` with:

* **the home button's feed-forward, on every hold and move** (pass 6, 2026-11-13): every powered J2 / C1 command carries the static gravity
  torque from the home button's own comp (``bam_fivebar.dynamics.ControllerModel.gravity_at_motors`` on ``in_mode(real_assembly(BENCH),
  "vertical")``, the identified lumped model it has run since bam_ws 2ec4dd02a: ``home_button.bench_and_comp``), in each drive's Craig
  angle (``CraigMap``: Craig = URDF + offset) and scaled by cos J1 (the comp is J1-vertical), planned from BOTH the pose the step starts at
  and the pose it ends at - their mean, a move first split into waypoints so each piece spans at most ``WAYPOINT_DEG`` (the step's own
  interpolation); a joint that does not move in its step (a hold, a pin, a press on its stop) carries the gravity at its pose. The poses
  are the plan's, in CAD, and only where the plan KNOWS them (``step_end_pose``): a seek ends on its stop only when its stall is the one
  way the step can end, a position is known only once the sequence has defined that joint, Zach's tview frame is taken back to CAD
  (``procedure_frame``), and with either drive limp the comp (the closed chain held by both) is not what the other carries. Where the
  pose is not known - every procedure's first seek, from wherever the arm rests - the command runs un-fed (the note lists it): pass 5's
  rule (a seek fed for the stop it seeks) lunged J2 to 3.4 rad/s from the hanging rest. A feed-forward is never more than its command's
  cap (near the loop's toggle the comp asks for tens of N.m; the note lists those steps). J1 itself gets none.
  WHY every hold (the real rung, pass 5): all 16 real episodes tripped 0.1-0.2 s after their zero, at the first un-fed hold, J2 falling
  past the 86 deg/s runaway ceiling with the end group 22 % over CAD.
* **the home button's waypoints**: a move longer than ``WAYPOINT_DEG`` is walked in waypoints that far apart, each with the gravity at
  its own two ends (above) and the home walk's reach (0.06 rad); the last waypoint is the original step, its name and its done-when. WHY: one
  feed-forward over a 210 deg walk (press_reverse's far corner) is the wrong sign for half of it.
* **the push levels lifted over gravity (the different cap)**: a seek's cap becomes its push plus the gravity it must lift
  at the pose it ends on (``max(0, side * gravity)``), so a half-cap touch presses the stop with half the push, not with nothing. The board gives 12 N.m at
  most (``BOARD_MAX_NM``, RACK_BOARD), so where the full push and the gravity do not fit (J2 on its upper stop: 10 + 6.6) both levels
  shrink together - full = what fits, half = half of that - keeping the procedure's two-level ratio.

Nothing else changes: the procedure's steps, names, presses, defines, ``observe`` and its zero/backlash arithmetic are the original's.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache

from robot_models.homing.protocols import Phase, Prior
from robot_models.homing.types import HomingResult
from robot_msgs.control import JointCommand, JointCommandSequence, JointCommandStep, Reached, Stall

from .geometry import C1, DRIVES, J1, J2, ROLE
from .procedures import PROCEDURES, SEEK_CAP_NM, SEEK_DISTANCE, Procedure

GFF_SUFFIX = "+gff"
# the home button's comp since bam_ws 2ec4dd02a (the run home_real_after_gate1_085634): bam_rack_twin records/fivebar-bench
COMP = "gravity_params_massid_real_093852.json"
WAYPOINT_DEG = 4.0  # bam_fivebar_recovery.home.HomeTuning.waypoint_deg
WAYPOINT_REACH_RAD = 0.06  # HomeTuning.reach
BOARD_MAX_NM = 12.0  # bam_fb_test_rig.homing.RACK_BOARD.max_torque_nm: 17.5 A on the 60ASM200 + 10:1
STILL_RAD = math.radians(0.1)
OVER_CAP: list = []  # (step, joints) whose planned gravity exceeded the command's cap: filled per with_gravity_ff call (its note)


class GravityComp:
    """The home button's gravity comp on the bench's drives: ``torque(pose)`` -> {joint: N.m} in the URDF joint frame, or None where
    the comp's loop does not close. ``scale`` multiplies every torque: the feed-forward model error a pass assumes (pass 6: x0.75 / x1.25,
    the comp 25 % light or heavy), never a fit."""

    def __init__(self, comp: str = COMP, scale: float = 1.0):
        from .home_button import bench_and_comp  # noqa: PLC0415
        from .mujoco_plant import RigCache, bam_ws_path  # noqa: PLC0415

        bam_ws_path()
        from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415

        self.comp = comp if scale == 1.0 else f"{comp} x{scale:g}"
        self.scale = float(scale)
        self.bench, self.model = bench_and_comp(comp)
        craig = CraigMap(RigCache.get("B0"))
        for role in ("J2", "C1"):
            if craig.sign[role] != 1.0:
                raise ValueError(f"CraigMap gives {role} sign {craig.sign[role]}: the comp's torques assume Craig = URDF + offset")
        self.offset = {J2: float(craig.offset["J2"]), C1: float(craig.offset["C1"])}

    def torque(self, pose: dict) -> dict | None:
        if pose.get(J2) is None or pose.get(C1) is None:
            return None
        gravity = self.model.gravity_at_motors(pose[J2] + self.offset[J2], pose[C1] + self.offset[C1])
        if gravity is None:
            return None
        tilt = math.cos(pose[J1]) if pose.get(J1) is not None else 1.0
        return {J1: 0.0, J2: float(gravity[0]) * tilt * self.scale, C1: float(gravity[1]) * tilt * self.scale}


@lru_cache(maxsize=8)
def default_comp(comp: str = COMP, scale: float = 1.0) -> GravityComp:
    return GravityComp(comp, scale)


def _is_seek(command: JointCommand) -> bool:
    return command.mode == "move_by" and abs(float(command.distance)) >= 0.99 * SEEK_DISTANCE


def _side(command: JointCommand) -> int:
    return 1 if float(command.distance) > 0 else -1


def _clamp(prior: Prior, joint: str, q: float) -> float:
    """``q`` inside the joint's CAD stops (a move or pin planned past a stop ends on it)."""
    lo, hi = prior.stops.get(joint, -1), prior.stops.get(joint, +1)
    if hi is not None and q > hi.q_rad:
        return float(hi.q_rad)
    if lo is not None and q < lo.q_rad:
        return float(lo.q_rad)
    return float(q)


def _stall_only(step: JointCommandStep) -> str | None:
    """The joint whose stall is the ONLY way ``step`` can end (every done-when a ``Stall`` on it), else None."""
    joints = {c.joint for c in step.done_when if isinstance(c, Stall)}
    if len(joints) == 1 and all(isinstance(c, Stall) for c in step.done_when):
        return joints.pop()
    return None


def step_end_pose(step: JointCommandStep, before: dict, prior: Prior, *, defined: frozenset | set = frozenset(),
                  frame: dict | None = None) -> dict:
    """The CAD pose ``step`` is planned to end at, from the one it starts at: a value only where the plan KNOWS it, else None.

    * a limp joint: unknown; a hold: where it was;
    * a seek: on the CAD stop it seeks only when it was already pressing that stop, or when its stall is the only way the step can end
      (a step ends on ANY of its done-whens: a joint still seeking when another's stall ends the step is anywhere on its way);
    * a move_by (a pin, a back-off): where it was plus the distance, inside the CAD stops;
    * a position: the target, but only for a joint the sequence has defined (before that the position is the power-up frame's, which
      no plan knows), less the procedure's ``frame`` offset (Zach's tview frame is C1 41.08 deg off CAD: ``procedures.frame_offsets``);
    * a define: the value it labels, less the frame offset.

    WHY so strict (2026-11-13, pass 6): the pass-3 rule took every seek's end as its stop and every position as known, so a seek from the
    hanging rest carried the upper stop's 6.6 N.m and lunged (two_level_touch+gff on MuJoCo, 3.4 rad/s); a feed-forward planned for a pose
    the arm is not at is worse than none."""
    frame = frame or {}
    end = dict(before)
    only = _stall_only(step)
    for command in step.commands:
        joint = command.joint
        if command.mode == "limp":
            end[joint] = None
        elif command.mode == "hold":
            continue
        elif _is_seek(command):
            stop = prior.stops.q_rad(joint, _side(command))
            already = before.get(joint) is not None and abs(before[joint] - stop) < 1e-9
            end[joint] = float(stop) if (already or only == joint) else None
        elif command.mode == "move_by":
            end[joint] = None if before.get(joint) is None else _clamp(prior, joint, before[joint] + float(command.distance))
        elif command.mode == "position":
            end[joint] = _clamp(prior, joint, float(command.position) - frame.get(joint, 0.0)) if joint in defined else None
    for joint, value in step.define_position.items():
        end[joint] = float(value) - frame.get(joint, 0.0)
    return end


def _both_powered(step: JointCommandStep) -> bool:
    """The comp is the closed chain held by BOTH drives: with either limp its torques are not what the other carries."""
    modes = {c.joint: c.mode for c in step.commands}
    return modes.get(J2, "limp") != "limp" and modes.get(C1, "limp") != "limp"


def feedforward_for(command: JointCommand, start: dict, end: dict, g_start: dict | None, g_end: dict | None) -> float | None:
    """The feed-forward ``command`` carries over its step: the mean of the gravity at the pose the step starts at and the pose it ends at
    (the step's own interpolation: a move is split into waypoints first, so each piece is at most ``WAYPOINT_DEG``); for a joint that
    does not move in the step (a hold, a pin, a press continuing on its stop) the one end the plan knows. None when neither is known, or
    when the joint moves from a pose no plan knows."""
    joint = command.joint
    if g_start is not None and g_end is not None:
        return 0.5 * (g_start[joint] + g_end[joint])
    # STILL_RAD: a define relabels the pose it is taken at to the typed precision (tview's 0.34722 rev is 124.999 deg, CAD 125.000)
    still = command.mode == "hold" or (start.get(joint) is not None and end.get(joint) is not None
                                       and abs(end[joint] - start[joint]) < STILL_RAD)
    known = g_start if g_start is not None else g_end
    return known[joint] if (still and known is not None) else None


def _with_ff(command: JointCommand, feedforward: float | None, lift_gravity: float | None) -> JointCommand:
    """``command`` carrying ``feedforward``, never more than its own cap; a seek's cap lifted over the gravity it presses against at its
    stop (module docstring).

    WHY the clip at the cap (pass 6): near the loop's toggle the static torque a drive needs grows without bound (tview's first
    waypoint (0.25, 0.4) asks the comp for 96 N.m on J2), and the board clamps the whole command at the cap anyway; a feed-forward past
    it only hides that the pose is out of the drive's reach, which the note records instead (``ff_over_cap_steps``)."""
    if command.mode == "limp" or command.joint == J1:
        return command
    cap = float(command.max_effort)
    if _is_seek(command) and lift_gravity is not None:
        lift = max(0.0, _side(command) * lift_gravity)
        full = min(SEEK_CAP_NM[command.joint], BOARD_MAX_NM - lift)
        cap = cap / SEEK_CAP_NM[command.joint] * full + lift
    if feedforward is None and cap == float(command.max_effort):
        return command
    feedforward = 0.0 if feedforward is None else max(-cap, min(cap, float(feedforward)))
    return replace(command, max_effort=cap, feedforward_effort=feedforward)


def _fed_step(step: JointCommandStep, start: dict, end: dict, comp) -> tuple[JointCommandStep, list[str], str | None]:
    """``step`` with every powered J2 / C1 command fed (:func:`feedforward_for`); returns it, the joints left un-fed and why (``a drive
    limp`` / ``the pose is not known`` / ``the comp's loop does not close``)."""
    powered = _both_powered(step)
    g_start = comp.torque(start) if powered else None
    g_end = comp.torque(end) if powered else None
    commands, unfed, over_cap = [], [], []
    for command in step.commands:
        if command.mode == "limp" or command.joint == J1:
            commands.append(command)
            continue
        feedforward = feedforward_for(command, start, end, g_start, g_end) if powered else None
        if feedforward is None:
            unfed.append(command.joint)
        lift = None if g_end is None else g_end[command.joint]
        fed = _with_ff(command, feedforward, lift)
        if feedforward is not None and abs(feedforward) > float(fed.max_effort) + 1e-12:
            over_cap.append(command.joint)
        commands.append(fed)
    why = None
    if unfed:
        known = [pose for pose in (start, end) if pose.get(J2) is not None and pose.get(C1) is not None]
        why = ("a drive limp" if not powered else
               "the comp's loop does not close" if known and all(comp.torque(pose) is None for pose in known) else "the pose is not known")
    if over_cap:
        OVER_CAP.append((step.name, [ROLE[j] for j in over_cap]))
    return replace(step, commands=tuple(commands)), unfed, why


def _waypoints(step: JointCommandStep, start: dict, end: dict, comp, frame: dict) -> list[JointCommandStep] | None:
    """``step`` (a move) as the home walk's waypoints, each fed from its own two ends, or None when it is short or its start unknown."""
    moving = [c.joint for c in step.commands if c.mode == "position"]
    if not moving or any(start.get(j) is None or end.get(j) is None for j in moving):
        return None
    span = max(abs(end[j] - start[j]) for j in moving)
    pieces = int(math.ceil(math.degrees(span) / WAYPOINT_DEG - 1e-9))
    if pieces <= 1:
        return None
    out, previous = [], dict(start)
    for k in range(1, pieces + 1):
        pose = dict(end)
        pose.update({j: start[j] + (end[j] - start[j]) * k / pieces for j in moving})
        positioned = tuple(replace(c, position=pose[c.joint] + frame.get(c.joint, 0.0)) if c.mode == "position" else c for c in step.commands)
        piece = replace(step, commands=positioned)
        if k < pieces:
            piece = JointCommandStep(name=f"{step.name} (waypoint {k} of {pieces})", commands=positioned,
                                     done_when=(Reached(joints=tuple(moving), tolerance=WAYPOINT_REACH_RAD),), timeout=step.timeout)
        fed, _, _ = _fed_step(piece, previous, pose, comp)
        out.append(fed)
        previous = pose
    return out


def procedure_frame(procedure, prior: Prior) -> dict:
    """The frame a procedure's defines and targets are written in, minus CAD (``procedures.frame_offsets`` for Zach's tview, else 0),
    found through any wrappers (``.inner``)."""
    from .procedures import TviewV2, frame_offsets  # noqa: PLC0415

    seen = procedure
    while seen is not None:
        if isinstance(seen, TviewV2):
            return frame_offsets(prior)
        seen = getattr(seen, "inner", None)
    return {j: 0.0 for j in DRIVES}


def with_gravity_ff(sequence: JointCommandSequence, prior: Prior, comp, *, frame: dict | None = None) -> tuple[JointCommandSequence, dict]:
    """``sequence`` made gravity-aware (module docstring); returns it and a note (steps given feed-forward, waypoints added, poses the
    comp could not close, and the steps a powered J2 / C1 runs un-fed because the plan does not know where the arm is)."""
    frame = frame or {}
    pose = {j: None for j in DRIVES}
    defined: set = set()
    steps = []
    note = {"comp": comp.comp, "steps_with_ff": 0, "waypoint_steps_added": 0, "no_comp_steps": [], "unfed_unknown_pose_steps": []}
    OVER_CAP.clear()
    for step in sequence.steps:
        end = step_end_pose(step, pose, prior, defined=defined, frame=frame)
        split = _waypoints(step, pose, end, comp, frame) if _both_powered(step) else None
        if split is not None:
            steps.extend(split)
            note["waypoint_steps_added"] += len(split) - 1
            note["steps_with_ff"] += len(split)
        else:
            fed, unfed, why = _fed_step(step, pose, end, comp)
            if why == "the comp's loop does not close":
                note["no_comp_steps"].append(step.name)
            elif unfed:
                note["unfed_unknown_pose_steps"].append({"step": step.name, "joints": [ROLE[j] for j in unfed], "why": why})
            if len(unfed) < sum(1 for c in step.commands if c.mode != "limp" and c.joint != J1):
                note["steps_with_ff"] += 1
            steps.append(fed)
        defined |= set(step.define_position)
        pose = end
    note["ff_over_cap_steps"] = [{"step": name, "joints": joints} for name, joints in OVER_CAP]
    return replace(sequence, steps=tuple(steps), name=f"{sequence.name} + gravity feed-forward"), note


@dataclass
class GravityFF(Procedure):
    """``inner`` with the home button's gravity feed-forward (module docstring); ``observe`` is ``inner``'s. ``ff_scale``: the comp's
    assumed model error (``GravityComp.scale``)."""

    inner: Procedure = None
    comp_name: str = COMP
    ff_scale: float = 1.0
    plan_note: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.inner is None:
            raise ValueError("GravityFF needs an inner procedure")
        self.name = self.inner.name + GFF_SUFFIX

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        sequence = self.inner.plan(prior, so_far)
        if sequence is None:
            return None
        sequence, self.plan_note = with_gravity_ff(sequence, prior, default_comp(self.comp_name, self.ff_scale),
                                                   frame=procedure_frame(self.inner, prior))
        self.notes["gravity_ff"] = self.plan_note
        return sequence

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        result = self.inner.observe(prior, phases)
        self.references = self.inner.references
        self.notes.update(self.inner.notes)
        return result

    def observe_vs_twin(self, prior: Prior, twin: Prior, phases: Sequence[Phase]) -> HomingResult:
        return self.inner.observe_vs_twin(prior, twin, phases)


def procedure(name: str, *, ff_scale: float = 1.0) -> Procedure:
    """A procedure by its leaderboard name, ``<name>`` or ``<name>+gff`` (``ff_scale``: the comp's assumed error, +gff only)."""
    if name.endswith(GFF_SUFFIX):
        return GravityFF(inner=PROCEDURES[name.removesuffix(GFF_SUFFIX)](), ff_scale=ff_scale)
    return PROCEDURES[name]()


# WHY single_touch and tview_v2 now too (pass 6): the real rung showed their un-fed holds after the zero drop the real arm
GFF_VARIANTS = tuple(name + GFF_SUFFIX for name in ("repeat_checked_seek", "two_level_touch", "press_reverse", "single_touch", "tview_v2"))

__all__ = ["BOARD_MAX_NM", "COMP", "GFF_SUFFIX", "GFF_VARIANTS", "GravityComp", "GravityFF", "default_comp", "feedforward_for",
           "procedure", "procedure_frame", "step_end_pose", "with_gravity_ff"]
