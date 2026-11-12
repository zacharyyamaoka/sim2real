"""``+gff``: a homing procedure with the real home button's gravity feed-forward - a NEW leaderboard row beside the original.

The MuJoCo rung (2026-11-12, pass 3) showed why repeat_checked_seek, two_level_touch and press_reverse home on 2 of 16 starts: their
half-cap touches (J2 5 N.m, C1 3.5 N.m) cannot lift the arm onto the upper stops, where holding it takes J2 5.7 N.m and C1 4.2 N.m on the
twin (6.6 / 4.6 by the home button's identified comp), so the first touch is a stall short of the stop and the frame is defined there.
The two starts that home are the ones with J1 on a stop at +-90 deg, where the five-bar's plane is level and gravity on J2 / C1 is nil
(the twin's holding torque scales with cos J1 exactly: 5.72 / 4.04 / 0.00 N.m at J1 0 / 45 / 90 deg).

The coordinator's decision (2026-11-12): a candidate may become gravity-aware - a parameter of the benchmark candidate, not Zach's spec -
by reusing the home button's approach (``bam_fivebar_recovery.home.walk_home_sequence``), not by raising caps blindly; a design that
genuinely needs a different cap is a new named variant. So ``<name>+gff`` is ``<name>`` with:

* **the home button's feed-forward**: every powered command carries the static gravity torque at the pose its step is meant to end
  at, from the home button's own comp (``bam_fivebar.dynamics.ControllerModel.gravity_at_motors`` on ``in_mode(real_assembly(BENCH),
  "vertical")``, the identified lumped model it has run since bam_ws 2ec4dd02a: ``home_button.bench_and_comp``), in each drive's Craig
  angle (``CraigMap``: Craig = URDF + offset) and scaled by cos J1 (the comp is J1-vertical; the twin's own cos law above). The pose is
  the plan's nominal one - the homed map's frame: a seek ends on the CAD stop it seeks (C1's at the J2 it is planned with), a move at
  its target, a define at its CAD value, a hold where it was; a joint the plan leaves limp is unknown, and a pose with an unknown J2 or
  C1 gets no feed-forward. J1 before its own define is taken at home (0 rad, vertical): its true tilt is not known yet. J1 itself gets
  none (the comp is the five-bar's two drives).
* **the home button's waypoints**: a move longer than ``WAYPOINT_DEG`` is walked in waypoints that far apart, each with the gravity at
  its own pose and the home walk's reach (0.06 rad); the last waypoint is the original step, its name and its done-when. WHY: one
  feed-forward over a 210 deg walk (press_reverse's far corner) is the wrong sign for half of it.
* **the push levels lifted over gravity (the different cap)**: a seek's cap becomes its push plus the gravity it must lift
  (``max(0, side * gravity)``), so a half-cap touch presses the stop with half the push, not with nothing. The board gives 12 N.m at
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
from robot_msgs.control import JointCommand, JointCommandSequence, JointCommandStep, Reached

from .geometry import C1, DRIVES, J1, J2
from .procedures import PROCEDURES, SEEK_CAP_NM, SEEK_DISTANCE, Procedure

GFF_SUFFIX = "+gff"
# the home button's comp since bam_ws 2ec4dd02a (the run home_real_after_gate1_085634): bam_rack_twin records/fivebar-bench
COMP = "gravity_params_massid_real_093852.json"
WAYPOINT_DEG = 4.0  # bam_fivebar_recovery.home.HomeTuning.waypoint_deg
WAYPOINT_REACH_RAD = 0.06  # HomeTuning.reach
BOARD_MAX_NM = 12.0  # bam_fb_test_rig.homing.RACK_BOARD.max_torque_nm: 17.5 A on the 60ASM200 + 10:1


class GravityComp:
    """The home button's gravity comp on the bench's drives: ``torque(pose)`` -> {joint: N.m} in the URDF joint frame, or None where
    the comp's loop does not close."""

    def __init__(self, comp: str = COMP):
        from .home_button import bench_and_comp  # noqa: PLC0415
        from .mujoco_plant import RigCache, bam_ws_path  # noqa: PLC0415

        bam_ws_path()
        from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415

        self.comp = comp
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
        return {J1: 0.0, J2: float(gravity[0]) * tilt, C1: float(gravity[1]) * tilt}


@lru_cache(maxsize=2)
def default_comp(comp: str = COMP) -> GravityComp:
    return GravityComp(comp)


def _is_seek(command: JointCommand) -> bool:
    return command.mode == "move_by" and abs(float(command.distance)) >= 0.99 * SEEK_DISTANCE


def step_end_pose(step: JointCommandStep, before: dict, prior: Prior) -> dict:
    """The nominal (CAD) pose ``step`` is meant to end at, from the one before it (module docstring)."""
    end = dict(before)
    for command in step.commands:
        joint = command.joint
        if command.mode == "limp":
            end[joint] = None
        elif _is_seek(command):
            end[joint] = prior.stops.q_rad(joint, 1 if float(command.distance) > 0 else -1)
        elif command.mode == "move_by":
            end[joint] = None if end.get(joint) is None else end[joint] + float(command.distance)
        elif command.mode == "position":
            end[joint] = float(command.position)
    for joint, value in step.define_position.items():
        end[joint] = float(value)
    return end


def _with_ff(command: JointCommand, gravity: dict | None) -> JointCommand:
    """``command`` carrying the gravity at its step's pose; a seek's cap lifted over the gravity it pushes against (module docstring)."""
    if command.mode == "limp" or gravity is None or command.joint == J1:
        return command
    g = gravity[command.joint]
    cap = float(command.max_effort)
    if _is_seek(command):
        side = 1.0 if float(command.distance) > 0 else -1.0
        lift = max(0.0, side * g)
        full = min(SEEK_CAP_NM[command.joint], BOARD_MAX_NM - lift)
        cap = cap / SEEK_CAP_NM[command.joint] * full + lift
    return replace(command, max_effort=cap, feedforward_effort=g)


def _waypoints(step: JointCommandStep, start: dict, end: dict, comp: GravityComp) -> list[JointCommandStep] | None:
    """``step`` (a move) as the home walk's waypoints, or None when it is short or its start is unknown."""
    moving = [c.joint for c in step.commands if c.mode == "position"]
    if not moving or any(start.get(j) is None for j in moving):
        return None
    span = max(abs(end[j] - start[j]) for j in moving)
    pieces = int(math.ceil(math.degrees(span) / WAYPOINT_DEG - 1e-9))
    if pieces <= 1:
        return None
    out = []
    for k in range(1, pieces + 1):
        pose = dict(end)
        pose.update({j: start[j] + (end[j] - start[j]) * k / pieces for j in moving})
        gravity = comp.torque(pose)
        commands = tuple(_with_ff(replace(c, position=pose[c.joint]) if c.mode == "position" else c, gravity) for c in step.commands)
        if k < pieces:
            out.append(JointCommandStep(name=f"{step.name} (waypoint {k} of {pieces})", commands=commands,
                                        done_when=(Reached(joints=tuple(moving), tolerance=WAYPOINT_REACH_RAD),), timeout=step.timeout))
        else:
            out.append(replace(step, commands=commands))
    return out


def with_gravity_ff(sequence: JointCommandSequence, prior: Prior, comp: GravityComp) -> tuple[JointCommandSequence, dict]:
    """``sequence`` made gravity-aware (module docstring); returns it and a note (steps given feed-forward, waypoints added, poses the
    comp could not close)."""
    pose = {j: None for j in DRIVES}
    steps, note = [], {"comp": comp.comp, "steps_with_ff": 0, "waypoint_steps_added": 0, "no_comp_steps": []}
    for step in sequence.steps:
        end = step_end_pose(step, pose, prior)
        split = _waypoints(step, pose, end, comp)
        if split is not None:
            steps.extend(split)
            note["waypoint_steps_added"] += len(split) - 1
            note["steps_with_ff"] += len(split)
        else:
            gravity = comp.torque(end)
            if gravity is None and any(c.mode != "limp" and c.joint != J1 for c in step.commands):
                note["no_comp_steps"].append(step.name)
            elif gravity is not None:
                note["steps_with_ff"] += 1
            steps.append(replace(step, commands=tuple(_with_ff(c, gravity) for c in step.commands)))
        pose = end
    return replace(sequence, steps=tuple(steps), name=f"{sequence.name} + gravity feed-forward"), note


@dataclass
class GravityFF(Procedure):
    """``inner`` with the home button's gravity feed-forward (module docstring); ``observe`` is ``inner``'s."""

    inner: Procedure = None
    comp_name: str = COMP
    plan_note: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.inner is None:
            raise ValueError("GravityFF needs an inner procedure")
        self.name = self.inner.name + GFF_SUFFIX

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        sequence = self.inner.plan(prior, so_far)
        if sequence is None:
            return None
        sequence, self.plan_note = with_gravity_ff(sequence, prior, default_comp(self.comp_name))
        self.notes["gravity_ff"] = self.plan_note
        return sequence

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        result = self.inner.observe(prior, phases)
        self.references = self.inner.references
        self.notes.update(self.inner.notes)
        return result

    def observe_vs_twin(self, prior: Prior, twin: Prior, phases: Sequence[Phase]) -> HomingResult:
        return self.inner.observe_vs_twin(prior, twin, phases)


def procedure(name: str) -> Procedure:
    """A procedure by its leaderboard name, ``<name>`` or ``<name>+gff``."""
    if name.endswith(GFF_SUFFIX):
        return GravityFF(inner=PROCEDURES[name.removesuffix(GFF_SUFFIX)]())
    return PROCEDURES[name]()


GFF_VARIANTS = tuple(name + GFF_SUFFIX for name in ("repeat_checked_seek", "two_level_touch", "press_reverse"))

__all__ = ["BOARD_MAX_NM", "COMP", "GFF_SUFFIX", "GFF_VARIANTS", "GravityComp", "GravityFF", "default_comp", "procedure",
           "step_end_pose", "with_gravity_ff"]
