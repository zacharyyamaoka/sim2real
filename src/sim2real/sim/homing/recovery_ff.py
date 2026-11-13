"""``recover_first(fed)+<row>``: the blind recovery in front of a +gff row with EVERY powered hold and move fed, recovery included.

Why (pass 7, 2026-11-13): single_touch+gff and tview_v2+gff home the real five-bar 8/8 from near-home starts because every hold and move
after the zero carries the home button's gravity feed-forward (gravity_ff). "Any start" still rests on the blind recovery in front of them
(recover_first), and its holds carry none: on the real arm its re-hold after the first J2 seek ran away at 91-93 deg/s, every start, and the
MuJoCo plant with the end group +22 % and the runaway check trips in the same place ('recover: J2 - 15 deg (lift L1 off), crank limp',
86-87 deg/s, bowl and flipped_crank, B0). This module feeds that prefix at the sim2real seam, without touching the blind routine's proof
files (bam_fivebar_recovery routine.py / steps.py / _executor.py / proof.py / backend.py, nor the exported sequence): one more rewrite of
the planned sequence, the LAST one (after sag_proof's re-holds, hold_j1 and keep_j2_powered), so every step the arm is told is fed.

What it feeds, and from what:

* **Only what is un-fed.** A powered J2 / C1 command that already carries a feed-forward (gravity_ff planned it) is left exactly as it
  is; caps are never changed (the recovery's caps are its tuning, the procedures' lifted caps gravity_ff's). J1 gets none (held).
* **A seek with the gravity at the pose it starts from** - only where the plan knows that pose, else un-fed (the recovery's first J2 seek
  from the hanging rest, every bare procedure's first seek: pass 5's lunge came from feeding a seek for a pose it was not at). WHY a seek
  at all (the second smoke run, 2026-11-13): with its holds fed and seeks not, the recovery tripped where a fed hold handed over to an
  un-fed seek - "J2 + onto its stop" dropped J2's 7.0 N.m at once and J2 fell at 87-88 deg/s (bowl, flipped_crank; B0, end group +22 %).
  The start pose's gravity, not the mean with its end: the hand-off is where a step in the feed-forward lunges, and over the seek the
  setpoint moves at 9-17 deg/s, slowly enough for the PD to carry the change; on its stop the seek presses at its cap either way.
  Holds, pins, presses on a stop and moves are fed as below.
* **From the pose the plan knows**, tracked through the WHOLE sequence (one track, prefix into procedure - the procedure's own +gff
  planned from "unknown" at its start, so its first holds after the recovery were un-fed too):

  - a seek ends on its stop only when its stall is the one way the step can end (gravity_ff's rule); else unknown;
  - a ``move_by`` from a known pose ends there plus its distance, inside the CAD stops; a position is known once its joint is defined;
  - **a limp crank rests at its gravity equilibrium.** With C1 limp and J2 powered at a known angle, C1 comes to the stable zero of its own
    holding torque (:func:`limp_rest`, the comp's ``gravity_at_motors`` with C1's component = 0, rising through zero). Checked against the
    twin before it was used: J2 on its stop (124.71 deg), the comp puts the limp crank at 152 deg, MuJoCo's recovery landed it at 151.94.
    Where the comp has more than one stable rest the one nearest the crank's last known angle is taken, and with none known, none.
* **The torque:** both drives powered and the pose known - gravity_ff's own ``feedforward_for`` (the mean of the start and end pose's
  gravity, the one known end for a joint that does not move); J2 powered with the crank limp - J2's static torque with the crank at its
  rest, :func:`limp_crank_torque` (4.2 N.m at J2's stop, 4.8 at 110 deg: the recovery's "J2 holds, crank limp" steps). Clipped to the
  command's cap, as gravity_ff clips.

**And the crank is never let go once powered** (``c1_seek.keep_c1_powered``, the crank's twin of ``real_plant.keep_j2_powered``): fed
alone, the recovery got past its first trip and tripped at the next one - its re-hold before "J2 + onto its stop, crank limp" releases the
crank from its upper stop (197.77 deg), the crank swings down at 183 deg/s and drags J2 past the ceiling (91-92 deg/s; bowl and other, B0,
end group +22 %, ff nominal). Kept powered there the crank stays on its stop while J2 rises to its own (the loop closes the whole way:
comp at J2 110-125 / C1 197.77), and the recovery's C1 define ("the hub meets L1's plate", labelled 197.77) is then taken ON that stop -
limp, the crank had fallen to its rest and come back only to the hub, 167.6 deg on the twin (pass 4), 30 deg from its label. The
recovery's first steps from the hanging rest keep their limp crank (it has never been powered there): that is how it finds the assembly.

Steps before the first J2 stall stay un-fed: the arm hangs where it fell, a pose no plan knows, and at a hanging rest the gravity on each
drive is ~0 by definition (a rest is an equilibrium).

**Status - falsified for "any start" (pass 7 smoke sweep, 2026-11-13, sim2real d308187, B0, CAD mass, ff nominal, 16 recovery starts):**
14 / 16 home; lower_corner and sobol-04 trip (J2 91 deg/s in "J2 + onto its stop", C1 93 deg/s in "C1 + until it stalls"). The un-fed
recovery homes all 16 there. Two causes, both in what the plan claims to know, neither fixable by feeding alone:

* **The first J2 stall is not always J2's stop.** From a crank-below start (C1 -80 .. -113 deg) the limp crank's first J2 seek stalls on
  a loop contact at J2 -10.75 / C1 -79.77 deg (both starts, to 0.01 deg), 135 deg short of the stop the plan assumes (124.71). The gravity
  on J2 there is -0.14 N.m, not the 4.14 fed; every later feed is for the stop's track (4.5-7.0 N.m too much on J2). Tried and rejected on
  the twin (B0, 5 starts x end+22 % at ff 0.75 / 1 / 1.25 + CAD): half the stop track's feed until the define (the minimax of "on the
  stop" vs "near the hanging rest", where gravity is ~0) - passes CAD and ff 0.75, sobol-04 still trips in its C1 seek at ff 1 / 1.25;
  converging both drives onto their stops before feeding (C1 up with J2 creeping, J2 up with C1 held, C1 onto its stop) - the stop
  starts then trip in "J2 up, C1 held" (86-90 deg/s, bowl and flipped_crank, every mass).
* **J1's tilt is unknown to the plan.** The comp scales J2 / C1 gravity by cos(J1) and the recovery holds J1 wherever it fell, unread
  (J1 settles at its stops, -90 / +90 deg, from lower_corner and on_seek_stops). There the gravity the feed assumes is ~0, and at ff +25 %
  the procedure's own "J2 + C1 home" trips after the recovery (J2 88-89 deg/s, both starts).

The pass-7 run (``data/homing_fivebar_mujoco_pass7_2026-11-13.json``, B0, the 16 recovery starts) confirms it and adds a third:
with the real mass at ff nominal the stop starts themselves trip at 86-88 deg/s in the recovery's define step ("C1 + until the hub
meets L1's plate") - 31.2 % reliable; CAD 87.5 %, ff -25 % 93.8 %, ff +25 % 81.2 %. Not ready.

On the real arm the any-start path is the home button (bam_rack_twin ``fivebar_home -f``): it reads the pose from the boards and feeds
every waypoint with the gravity at that pose, so neither cause applies; recover_first stays the lost-zero fallback.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace

from robot_msgs.control import JointCommand, JointCommandSequence, JointCommandStep, Stall

from .geometry import C1, J1, J2, ROLE
from .gravity_ff import _clamp, _stall_only, feedforward_for

FED_RECOVER_PREFIX = "recover_first(fed)+"
UNFED_EPS = 1e-12  # a feed-forward smaller than this is "none" (gravity_ff writes 0.0 where it lifts a cap but knows no pose)
REST_GRID_DEG = 1.0  # the crank's rest is bracketed on a 1 deg grid, then bisected
REST_TOL_RAD = 1e-6


def _span(prior, joint: str) -> float | None:
    lo, hi = prior.stops.get(joint, -1), prior.stops.get(joint, +1)
    if lo is None or hi is None or lo.q_rad is None or hi.q_rad is None:
        return None
    return float(hi.q_rad - lo.q_rad)


def seek_side(command: JointCommand, step: JointCommandStep, prior) -> int | None:
    """+1 / -1 when ``command`` is a seek - a ``move_by`` longer than its joint's whole CAD span that ``step`` ends on a ``Stall`` of - else
    None. WHY by span and not gravity_ff's 2.5-turn ``SEEK_DISTANCE``: the recovery's seeks are 330 and 400 deg (one turn), and must be
    seen as seeks too; the longest non-seek ``move_by`` (a press, a back-off, a pin) is 25 deg."""
    if command.mode != "move_by" or command.distance is None:
        return None
    span = _span(prior, command.joint)
    stalls = any(isinstance(c, Stall) and c.joint == command.joint for c in step.done_when)
    if span is None or not stalls or abs(float(command.distance)) < span:
        return None
    return 1 if float(command.distance) > 0 else -1


def limp_rest(comp, pose: dict, *, near: float | None = None) -> float | None:
    """The angle a limp C1 comes to rest at with J2 at ``pose[J2]``: a stable zero of C1's holding torque (rising through zero, so a
    push either way is pushed back), the one nearest ``near`` when the comp has several, None when it has none or several and no ``near``."""
    if pose.get(J2) is None:
        return None
    rests = []
    previous = None
    for k in range(int(360 / REST_GRID_DEG) + 1):
        c1 = math.radians(-180.0 + k * REST_GRID_DEG)
        torque = comp.torque({J1: pose.get(J1), J2: pose[J2], C1: c1})
        value = None if torque is None else torque[C1]
        if previous is not None and value is not None and previous[1] is not None and previous[1] < 0.0 <= value:
            lo, hi = previous[0], c1
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                t = comp.torque({J1: pose.get(J1), J2: pose[J2], C1: mid})
                if t is None:
                    break
                lo, hi = (mid, hi) if t[C1] < 0.0 else (lo, mid)
                if hi - lo < REST_TOL_RAD:
                    break
            rests.append(0.5 * (lo + hi))
        previous = (c1, value)
    if not rests:
        return None
    if len(rests) == 1 and near is None:
        return float(rests[0])
    if near is None:
        return None
    wrap = lambda a: (a + math.pi) % (2.0 * math.pi) - math.pi  # noqa: E731
    return float(min(rests, key=lambda r: abs(wrap(r - near))))


def limp_crank_torque(comp, j2: float | None, *, near: float | None = None) -> float | None:
    """J2's static torque with the crank limp at its rest (:func:`limp_rest`); None where the rest is not known."""
    if j2 is None:
        return None
    rest = limp_rest(comp, {J2: j2}, near=near)
    if rest is None:
        return None
    torque = comp.torque({J2: j2, C1: rest})
    return None if torque is None else float(torque[J2])


def _modes(step: JointCommandStep) -> dict:
    return {c.joint: c.mode for c in step.commands}


def end_pose(step: JointCommandStep, before: dict, prior, comp, *, defined: set, frame: dict | None = None) -> dict:
    """The CAD pose ``step`` ends at where the plan knows it (module docstring), else None per joint."""
    frame = frame or {}
    end = dict(before)
    only = _stall_only(step)
    modes = _modes(step)
    for command in step.commands:
        joint = command.joint
        if joint == J1:
            continue
        side = seek_side(command, step, prior)
        if command.mode == "limp":
            end[joint] = None
        elif command.mode == "hold":
            continue
        elif side is not None:
            stop = prior.stops.q_rad(joint, side)
            already = before.get(joint) is not None and abs(before[joint] - stop) < 1e-9
            # WHY C1's stop is taken as fixed whatever J2 is (2026-11-13): the CAD's C1 stops are frame stops - FivebarGeometry.stop(C1, +-1,
            # q6) reads 197.77 / -112.69 deg at every J2 from 0 to 125 - and the twin agrees (pass 4: the recovery's C1 seek with J2 held
            # at 78 deg stalled at 197.772, touching C1's upper stop, every start)
            known = already or only == joint
            end[joint] = float(stop) if known else None
        elif command.mode == "move_by":
            end[joint] = None if before.get(joint) is None else _clamp(prior, joint, before[joint] + float(command.distance))
        elif command.mode == "position":
            end[joint] = _clamp(prior, joint, float(command.position) - frame.get(joint, 0.0)) if joint in defined else None
    for joint, value in step.define_position.items():
        end[joint] = float(value) - frame.get(joint, 0.0)
    if modes.get(C1) == "limp" and modes.get(J2, "limp") != "limp" and end.get(J2) is not None:
        end[C1] = limp_rest(comp, end, near=before.get(C1))
    return end


def _fill(command: JointCommand, value: float | None) -> JointCommand:
    if value is None:
        return command
    cap = float(command.max_effort)
    return replace(command, feedforward_effort=max(-cap, min(cap, float(value))))


def fill_feed(sequence: JointCommandSequence, prior, comp, *, frame: dict | None = None) -> tuple[JointCommandSequence, dict]:
    """``sequence`` with every un-fed powered hold / pin / press / move on J2 and C1 fed where the plan knows the pose (module docstring).
    Returns it and a note: the steps filled, and the powered non-seek commands still un-fed (and why)."""
    frame = frame or {}
    pose = {J1: None, J2: None, C1: None}
    defined: set = set()
    steps, filled, unfed, unfed_seeks = [], [], [], []
    # WHY the procedure's frame only on its own steps (smoke run 3, 2026-11-13): the recovery's defines and targets are CAD's; read in
    # tview's crank frame (C1 41.08 deg off CAD) its C1 define put the crank 41 deg from where it was and J2 ran away in the define step
    # at ff +25 % (bowl / other, B0 / B2)
    prefix = {s.name for s in prefix_steps(sequence)}
    for step in sequence.steps:
        end = end_pose(step, pose, prior, comp, defined=defined, frame={} if step.name in prefix else frame)
        modes = _modes(step)
        both = modes.get(J2, "limp") != "limp" and modes.get(C1, "limp") != "limp"
        g_start = comp.torque(pose) if both else None
        g_end = comp.torque(end) if both else None
        commands, joints = [], []
        for command in step.commands:
            if command.joint == J1 or command.mode == "limp" or abs(float(command.feedforward_effort or 0.0)) > UNFED_EPS:
                commands.append(command)
                continue
            if seek_side(command, step, prior) is not None:
                # a seek carries the gravity at the pose it STARTS from, when the plan knows it (module docstring)
                value = None
                if both and g_start is not None:
                    value = g_start[command.joint]
                elif command.joint == J2 and modes.get(C1) == "limp":
                    value = limp_crank_torque(comp, pose.get(J2), near=pose.get(C1))
                if value is None:
                    unfed_seeks.append({"step": step.name, "joint": ROLE[command.joint]})
                    commands.append(command)
                else:
                    commands.append(_fill(command, value))
                    joints.append(ROLE[command.joint])
                continue
            value = None
            if both:
                value = feedforward_for(command, pose, end, g_start, g_end)
            elif command.joint == J2 and modes.get(C1) == "limp":
                start_t = limp_crank_torque(comp, pose.get(J2), near=pose.get(C1))
                end_t = limp_crank_torque(comp, end.get(J2), near=end.get(C1))
                if start_t is not None and end_t is not None:
                    value = 0.5 * (start_t + end_t)
                elif command.mode == "hold":
                    value = start_t if start_t is not None else end_t
            if value is None:
                unfed.append({"step": step.name, "joint": ROLE[command.joint], "mode": command.mode})
                commands.append(command)
            else:
                commands.append(_fill(command, value))
                joints.append(ROLE[command.joint])
        if joints:
            filled.append({"step": step.name, "joints": joints})
        steps.append(replace(step, commands=tuple(commands)))
        defined |= set(step.define_position)
        pose = end
    note = {"comp": getattr(comp, "comp", None), "filled_steps": filled, "unfed_non_seek": unfed, "unfed_seeks": unfed_seeks}
    return replace(sequence, steps=tuple(steps)), note


def prefix_steps(sequence: JointCommandSequence) -> Sequence[JointCommandStep]:
    """The recovery prefix's steps (``recover: `` and the re-holds sag_proof put in front of them)."""
    from .recover import PREFIX  # noqa: PLC0415

    return [s for s in sequence.steps if s.name.startswith(PREFIX) or s.name.split(" before: ", 1)[-1].startswith(PREFIX)]


__all__ = ["FED_RECOVER_PREFIX", "end_pose", "fill_feed", "limp_crank_torque", "limp_rest", "prefix_steps", "seek_side"]
