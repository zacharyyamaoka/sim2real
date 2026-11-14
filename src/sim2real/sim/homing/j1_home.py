"""J1's home, ONE definition for the twin and the rack: the two steps the full arm's routine runs (fullarm_routine's J1 rows) and the rack
entry point runs on the real arm (``j1_rack``), so the bytes the twin was scored on are the bytes the boards get.

Light on purpose (robot_msgs only): the rack's deployment venv (~/bam_ws-armhold/src/dev/bam_rack_twin/.venv) has robot_msgs and sim2real but no
robot_models or MuJoCo model, and a powered process must not build one. WHY each number is in its comment; PEP 0047 addendum 3 is the record.
"""

from __future__ import annotations

import math

from robot_msgs.control import EffortStall, JointCommand, JointCommandSequence, JointCommandStep, Reached

TAU = 2.0 * math.pi
J1 = "revolute_3"  # fullarm_plant.J1 / geometry.J1 (the URDF name): J1 rolls the five-bar plane about the arm's spine

# -- J1's home (Zach, 2026-11-13 night: "J2/C1 -> READY -> tilt J1 UPWARD to its top hard stop (stall seek) -> then the wrists"; matched to the
# rack's real J1 homes of 2026-11-14 05:41Z / 05:56Z: two stalls at board -1.31529 / -1.31654, 0.07 deg apart, mapped to the CAD's -89.972) -----
# WHY side -1 - the real arm's top stop: the Sim to Real Agent homed J1 there (zero_board 0.25439, sign +1, the hand-eye's independent -11.0 deg
# agreeing). J1 rolls the five-bar plane about the arm's spine; at READY the arm hangs and both stops lift its lower end to horizontal, and the
# -89.972 side swings it away from the D435 (deployment.json can11, Zach's 2026-11-10 "horizontal").
J1_STOP_SIDE = -1
J1_STOP_DEG = -89.972  # stops.json revolute_3 side -1 (the twin reads it from its prior; tests pin the two equal)
# WHY these caps (the dispatcher from the Sim to Real Agent, 2026-11-14): the joint's cap is the datasheet's (torque_caps: JMC 60ASM400 peak
# 3.8 N.m x 10 through the AD60-G10-D14 gearbox, which allows 18 N.m: 17.98) - never hand-set; the seek ran on the rack at 11 N.m
J1_JOINT_CAP_NM = 17.98
J1_SEEK_CAP_NM = 11.0
# WHY an effort stall at 9 N.m, not a lead or a cap stall (the rack's 22:54 trap: a stall at board -1.282, 2 deg short, was gravity at a 7 N.m
# cap with no feed-forward): J1's gravity on the sweep peaks at the stop (the rack's measured 5.2 N.m) and friction adds <= 1.5 N.m, so only
# pressing the stop drives the effort past 9 while J1 stands still - with the feed-forward off or the cap under 9 the seek times out instead
# of recording a stop (robot_msgs EffortStall). Margins: 9 - 5.22 - 1.5 = 2.3 N.m over gravity and friction; 11 - 9 = 2 N.m of cap over the
# rule; the seek presses <= 11 N.m, 7 N.m inside the joint's 17.98.
J1_STALL_EFFORT_NM = 9.0
J1_GRAVITY_WORST_NM = 5.22  # j1_gains.j1_gravity_nm at the stop (the rack's measured READY curve; the twin's CAD said 3.9)
# WHY 1.5: the JMC drive's breakaway, upper bound (0.74 N.m identified on CAN 12; the rack's J1 friction band 0.3-0.7 N.m)
J1_FRICTION_MAX_NM = 1.5
J1_KP_NM_PER_RAD = 14.0 * 200.0 / TAU  # the rack's kp x14 on the board's 200 N.m/rev (bam_rack_twin.hardware.j1_gains)
J1_SEEK_SPEED = 0.02 * TAU  # 7.2 deg/s (the rack's seeks: 77.7 deg in 12.4 s)
J1_RETURN_SPEED = 0.03 * TAU
# WHY READY's J1 is -12.7 deg, not 0 (2026-11-14 07:11Z): at READY J1 = 0 is blocked - contact at homed -7 deg in the side-table clutter
# (full_arm/obstacles/j1_contact_20261114T0711Z.json, envelope J1 <= -9 deg); READY is the board record with J1 at -12.7
# (full_arm/ready_20261114T073916Z). J1 goes back there before the wrist homes.
J1_READY_RAD = math.radians(-12.7)
J1_ENVELOPE_MAX_RAD = math.radians(-9.0)
# WHY one seek from wherever J1 hangs, relative: before its stall J1 reads only its board's frame. 110 deg covers the grid's highest start
# (+6 deg, a few sagged) to the stop with room for the stall to build
J1_SEEK_TRAVEL_RAD = math.radians(110.0)
STEP_TIMEOUT_S = 40.0  # fullarm_procedures.STEP_TIMEOUT_S: every step of the routine
J1_HOME_STEPS = ("J1 seeks its stop", "J1 back to READY's angle")  # routine_check.J1_HOME_STEPS: where a lost start was lost


def reached_j1() -> list:
    """J1's move done-when: within 0.5 deg, or arrived and still within what friction can sag its kp x14 PD (0.2 deg)."""
    return [Reached(joints=(J1,), tolerance=math.radians(0.5)),
            Reached(joints=(J1,), tolerance=math.radians(0.5) + J1_FRICTION_MAX_NM / J1_KP_NM_PER_RAD, speed=0.02, dwell=0.3)]


def seek_command(cap_nm: float = J1_SEEK_CAP_NM, feedforward_nm: float = 0.0) -> JointCommand:
    """J1's one seek: relative, toward stops.json's side -1, at the rack's seek speed under ``cap_nm``."""
    return JointCommand.move_by(J1, J1_STOP_SIDE * J1_SEEK_TRAVEL_RAD, speed=J1_SEEK_SPEED, max_effort=cap_nm, feedforward_effort=feedforward_nm)


def effort_stall() -> EffortStall:
    """The stop: J1 still while its effort pushes the way it seeks past J1_STALL_EFFORT_NM (module WHY)."""
    return EffortStall(joint=J1, effort=J1_STALL_EFFORT_NM)


def back_command(feedforward_nm: float = 0.0) -> JointCommand:
    """J1 back to READY's angle (in the frame the seek's define gave) under the joint's cap."""
    return JointCommand.to(J1, J1_READY_RAD, speed=J1_RETURN_SPEED, max_effort=J1_JOINT_CAP_NM, feedforward_effort=feedforward_nm)


def j1_home_sequence(stop_rad: float = math.radians(J1_STOP_DEG), *, feedforward_nm: float = 0.0, max_speed: float | None = None,
                     timeout_s: float = STEP_TIMEOUT_S) -> JointCommandSequence:
    """The routine's two J1 steps over J1 alone (the twin's full steps hold every other joint; on the rack the bus holds them): the seek done on
    the effort stall and defining J1 = ``stop_rad`` there, then J1 back to READY's angle. ``feedforward_nm`` is the commands' (the twin plans
    J1's gravity at the sweep's middle; both the twin's plant and the rack replace it every tick with J1's gravity at the measured angle)."""
    steps = (JointCommandStep(name=J1_HOME_STEPS[0], commands=(seek_command(J1_SEEK_CAP_NM, feedforward_nm),), done_when=(effort_stall(),),
                              timeout=timeout_s, define_position={J1: float(stop_rad)}),
             JointCommandStep(name=J1_HOME_STEPS[1], commands=(back_command(feedforward_nm),), done_when=tuple(reached_j1()),
                              timeout=timeout_s, define_position={}))
    extra = {} if max_speed is None else {"max_speed": float(max_speed)}
    return JointCommandSequence(joint_names=(J1,), steps=steps, name="J1 home", **extra)
