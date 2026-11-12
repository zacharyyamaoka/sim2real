"""Sag-proof completion for a homing ``JointCommandSequence``: what recover_first wraps every sequence in on a plant with gravity.

The MuJoCo rung (2026-11-12, real board record) showed two ways a sequence written for a stiff, weightless plant hangs or lies under
gravity on PD boards (ilimit_scale 0, no gravity feed-forward), neither of them a homing gate:

1. **A ``Reached`` move that gravity carries past its target never completes.** blind_recovery's step 3 ("J2 - 15 deg, lift L1 off") ends
   with J2 5.75 deg beyond its target, held there by the PD against L1's weight (3.24 N.m on 31.8 N.m/rad; 8.1 deg on CAN 12's real
   22.9). ``Reached`` (0.06 rad) is not met, and its ``Stall`` alternative cannot be: the setpoint does not lead the joint in the direction
   of motion, it trails it. So every such step gets one more alternative: :func:`still_at_target` - the setpoint has arrived and the
   joint has been still (``STILL_SPEED_RAD_S`` for ``STILL_DWELL_S``) within what its PD can sag under the step's own cap
   (``cap / kp`` of that drive plus the step's tolerance). The original ``Reached`` is kept and fires first wherever it can (its dwell is
   shorter), so a stiff plant runs exactly as before; the end pose the joint actually settled at is recorded by the bench
   (``mujoco_bench.step_ends``), never assumed to be the target.
2. **A seek's ``Stall`` fires falsely when it starts from a pose gravity is pulling on.** blind_recovery's step 4 turns the crank until it
   stalls with J2 holding; the hub pushes L1 down off J2's hold (13.9 deg on the bowl start, real boards). Step 5 then makes the crank
   limp and seeks J2 from the pushed pose: the crank falls through the loop, carries J2 down further, and J2 sits still with its setpoint
   leading by more than ``Stall.lead`` for 0.2 s - a stall 44 deg short of its stop, which step 6 then defines as the stop. The same
   happens to every procedure's first seek behind the prefix (each starts with "J1 holds", J2 and C1 limp for 0.3 s: L1 falls 70 deg,
   and the seek "stalls" at 55 deg as J2 bottoms out). Two parts, applied to every seek that BEGINS at a step (its joint was held, limp
   or moved otherwise the step before; a seek continuing the previous step's seek is left alone):

   * :func:`rehold_step` first: the seeking joints re-hold (a hold after a hold keeps its setpoint: robot_msgs
     ``JointCommandSequenceController._begin``; after a limp or a move it anchors where the joint is), the seek step's limp joints limp,
     every other joint holds, until all of them are still - the home button's own "J2 holds, the crank comes to rest"
     (bam_fivebar_recovery.home.settle_sequence, proven on the real arm: its speed and dwell, ``HOME_STILL_SPEED_RAD_S`` /
     ``HOME_STILL_DWELL_S``). The seek then starts from rest.
   * :func:`sag_aware_stall` on that seek: the re-hold alone is not enough (measured on the bowl start): J2 re-held rests 10.8 deg under
     its setpoint (4.31 N.m of L1's weight on CAN 12's 22.9 N.m/rad), the seek starts its setpoint from that measured pose, so the PD's
     lift drops to nothing, J2 falls 9 deg and sticks on its Coulomb friction while the setpoint climbs back - 0.16-0.22 rad of lead
     with J2 still, past ``Stall.lead`` (0.06 rad, chosen as "well past a PD's sag under homing caps" on the weightless twin). So the
     seek's ``Stall`` leads by what its PD can sag under the seek's own cap as well (0.06 + 8 / 22.9 = 0.41 rad for J2's recovery seek,
     0.06 + 7 / 31.8 = 0.28 rad for C1's procedure seeks). At a real stop the lead passes that once the drive presses at its cap, so a
     seek still ends on its stop - pressing at the cap the procedures' own press steps then apply; a stall reference (blind_recovery's
     C1 contact, "the crank pressing at its cap"; tview's set-output) is taken at that press.

Nothing here touches a ``define_position``, a press, an ``Elapsed`` or a gate: the procedures' zero and backlash arithmetic and the bench's
scoring are exactly as written. What changes is when a seek may call itself stalled (never before its drive is at its cap) and that a
move may end still short of a target gravity will not let it reach (its actual pose recorded).

The drives' kp are the real boards' (``mujoco_plant.REAL_BOARD_RECORD``, N.m per output rev / 2 pi = N.m/rad).
"""

from __future__ import annotations

import math
from dataclasses import replace

from robot_msgs.control import JointCommand, JointCommandSequence, JointCommandStep, Reached, Settled, Stall

from .geometry import C1, J1, J2
from .mujoco_plant import REAL_BOARD_RECORD

KP_NM_PER_RAD = {joint: REAL_BOARD_RECORD[role]["kp"] / (2.0 * math.pi) for joint, role in ((J1, "J1"), (J2, "J2"), (C1, "C1"))}
STILL_SPEED_RAD_S = 0.02  # the home button's still_speed (bam_fivebar_recovery.home.HomeTuning)
STILL_DWELL_S = 0.5  # 50 control ticks: past stick-slip (Stall's 0.2 s) and 10x Reached's default dwell, so a reach still wins first
HOME_STILL_SPEED_RAD_S = 0.02  # HomeTuning.still_speed
HOME_STILL_DWELL_S = 1.0  # HomeTuning.still_dwell
REHOLD_TIMEOUT_S = 60.0  # HomeTuning.settle_timeout
REHOLD_PREFIX = "re-hold "


def sag_rad(command: JointCommand) -> float:
    """The most a drive's PD can sag under this command's own cap: ``cap / kp`` (rad)."""
    cap = 0.0 if command.max_effort is None else float(command.max_effort)
    return cap / KP_NM_PER_RAD[command.joint]


def still_at_target(step: JointCommandStep, reached: Reached) -> Reached:
    """``reached``'s joints, done once their setpoints have arrived and they have been still ``STILL_DWELL_S`` within the reach plus what
    each PD can sag under its cap in this step (the largest of the joints listed: robot_msgs' ``Reached`` takes one tolerance)."""
    commands = {command.joint: command for command in step.commands}
    sag = max(sag_rad(commands[joint]) for joint in reached.joints)
    return Reached(joints=reached.joints, tolerance=float(reached.tolerance) + sag, speed=STILL_SPEED_RAD_S, dwell=STILL_DWELL_S)


def with_still_at_target(step: JointCommandStep) -> JointCommandStep:
    extra = tuple(still_at_target(step, condition) for condition in step.done_when
                  if isinstance(condition, Reached) and all(c.mode in ("move_by", "position", "hold") for c in step.commands
                                                            if c.joint in condition.joints))
    return step if not extra else replace(step, done_when=tuple(step.done_when) + extra)


def needs_rehold(previous: JointCommandStep, step: JointCommandStep) -> list[str]:
    """The joints ``step`` checks for a stall whose seek BEGINS at ``step``: in ``previous`` the joint was not already seeking the same way
    (a move_by of the same sign), so it starts from a pose gravity may be pulling on (held off by another joint's push, falling limp, or
    sagged under a hold)."""
    before = {command.joint: command for command in previous.commands}
    now = {command.joint: command for command in step.commands}
    out = []
    for condition in step.done_when:
        if not isinstance(condition, Stall) or now[condition.joint].mode != "move_by":
            continue
        last = before.get(condition.joint)
        continuing = (last is not None and last.mode == "move_by"
                      and math.copysign(1.0, float(last.distance)) == math.copysign(1.0, float(now[condition.joint].distance)))
        if not continuing and condition.joint not in out:
            out.append(condition.joint)
    return out


def rehold_step(previous: JointCommandStep, step: JointCommandStep, joints: list[str]) -> JointCommandStep:
    """The seeking joints re-hold (a hold after a hold keeps its setpoint; otherwise it anchors where the joint is), ``step``'s limp joints
    stay limp, every other joint holds; done when the re-held and the limp joints are all still (the home button's settle). Each hold's
    cap is the joint's cap in ``previous`` when it was powered there, else its cap in ``step``."""
    powered = {command.joint: command for command in previous.commands if command.mode != "limp"}
    commands, watched = [], list(joints)
    for command in step.commands:
        before = powered.get(command.joint)
        cap = (before.max_effort if before is not None else None) or command.max_effort
        # WHY the feed-forward travels with the cap (2026-11-12, the +gff rows): a hold that dropped a gravity feed-forward the joint
        # was carrying would let it sag gravity / kp (J2: 6.6 N.m on 22.9 N.m/rad = 17 deg) before its seek. After a limp the joint
        # rests wherever it fell, a pose no plan names, so it gets none. 0 on every original row (and in the blind recovery).
        feedforward = float(before.feedforward_effort or 0.0) if before is not None else 0.0
        if command.joint in joints:
            commands.append(JointCommand.hold(command.joint, max_effort=float(cap), feedforward_effort=feedforward))
        elif command.mode == "limp":
            commands.append(command)
            watched.append(command.joint)
        else:
            commands.append(JointCommand.hold(command.joint, max_effort=float(cap), feedforward_effort=feedforward))
    names = ", ".join(joints)
    return JointCommandStep(name=f"{REHOLD_PREFIX}{names} before: {step.name}", commands=tuple(commands),
                            done_when=(Settled(joints=tuple(watched), speed=HOME_STILL_SPEED_RAD_S, dwell=HOME_STILL_DWELL_S),),
                            timeout=REHOLD_TIMEOUT_S)


def sag_aware_stall(step: JointCommandStep, joints: list[str]) -> JointCommandStep:
    """``step`` with each of ``joints``' ``Stall`` leading by more than its PD can sag under the step's cap (``lead + cap / kp``), its
    speed and dwell unchanged. Only ever applied to a seek that begins after a re-hold (:func:`sag_proof`)."""
    commands = {command.joint: command for command in step.commands}
    done = tuple(Stall(joint=condition.joint, lead=float(condition.lead) + sag_rad(commands[condition.joint]), speed=condition.speed,
                       dwell=condition.dwell)
                 if isinstance(condition, Stall) and condition.joint in joints else condition for condition in step.done_when)
    return replace(step, done_when=done)


def sag_proof(sequence: JointCommandSequence) -> JointCommandSequence:
    """``sequence`` with both fixes (module docstring); every original step kept, in order, under its own name."""
    steps: list[JointCommandStep] = []
    for index, step in enumerate(sequence.steps):
        if index:
            joints = needs_rehold(sequence.steps[index - 1], step)
            if joints:
                steps.append(rehold_step(sequence.steps[index - 1], step, joints))
                step = sag_aware_stall(step, joints)
        steps.append(with_still_at_target(step))
    return replace(sequence, steps=tuple(steps))


__all__ = ["KP_NM_PER_RAD", "REHOLD_PREFIX", "rehold_step", "sag_aware_stall", "sag_proof", "sag_rad", "still_at_target",
           "with_still_at_target"]
