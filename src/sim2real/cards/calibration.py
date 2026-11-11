"""Zach's calibration packages (PROJECT - Sim2Real, Nov 5 2026): "all of these calibration things are ultimately very related ...
but we can focus as separate packages ... Each of these basically can be looked at separately and require their own algorithms".

One entry per package: the type cards it serves and where its code lives today. Every CodeHome path was found by reading the
repos on 2026-11-05 and is checked to exist at its ref by tests/test_ladders.py; `unknown` means nobody found code, never a guess.

Since 2026-11-07 each package also has its ROUTINES, Calibration Routines, the ways to run it (Zach, via the coordinator: "Any error is caused by errors in
our model: the fidelity of the models and the accuracy of the parameters ... what are the methods we have to calibrate those
parameters"; his Nov 6 note: "enumerate some different like calibration schemes ... dynameter could be one ... Some of these we can run
on a bench some we can run when the robot is deployed ... check these vs an orcale in simulation"). A routine names the (card, rung,
parameter) it identifies, where it runs, its time and equipment cost (a source or "estimate" on every number), its excitation, coverage
and repeats, its code, and the sysid noise-ladder checks that grade it against a hidden truth (sysid/noise_ladder.json). Every code
path was read on 2026-11-07 and is checked by tests/test_routines.py; "not implemented" means nobody found code, and then no oracle
number exists for it. EQUIPMENT holds what a routine needs beyond the robot's own sensors, each with a cost and its source.
"""

from __future__ import annotations

from . import references as refs
from .schema import ESTIMATE, CalibrationPackage, CalibrationRoutine, CodeHome, Configures, Equipment, Identifies, Quantity

BAM_WS = "/home/bam/bam_ws"
IO_DX = "/home/bam/io-diagnostics"
ROBOTPARTS = "/home/bam/robotparts"
PIDTUNA = "/home/bam/pidtuna"
TWIN = "src/dev/bam_rack_twin/bam_rack_twin"
KINCAL_BRANCH = "claude/kinematic-calibration-multi-arm-4645cc"
PID_BRANCH = "claude/pid-auto-tuner-stack-e956da"
BACKLASH_BRANCH = "claude/backlash-simulation-7673dc"
# This repo, by its canonical path (tests/test_routines.py resolves it to the checkout under test, a worktree included).
SIM2REAL = "/home/bam/sim2real"
GEAR_BACKLASH = "src/core/mdp/agent/actuators/gear_backlash/src/gear_backlash"
KINCAL = "src/core/mdp/setup/bam_calibration/src/bam_calibration"

PACKAGES = (
    CalibrationPackage(
        "hand_eye", "Hand Eye", "Hand-eye calibration", ("camera_rgb", "camera_rgbd", "arm_6dof", "arm_6dof_gripper"),
        (CodeHome(BAM_WS, "src/core/mdp/setup/bam_calibration/docs/ref/bam_calibration/dev/camera_calibration/hand_eye_calibration.py",
                  note="a 2024-era ROS 2 node chaining ChArUco transforms, kept as reference (docs/ref); no AX = XB solver"),
         CodeHome(BAM_WS, f"{TWIN}/calib.py", note="the rack: camera and joints against the CAD by bundle adjustment over ArUco corners"),
         CodeHome(BAM_WS, "src/core/mdp/agent/world_model/bam_scan_tunnel/README.md",
                  note="its question 3 (ChArUco + multi-AprilTag + hand-eye solver agreement) is planned, not built")),
        "partial", note="the rack's camera-to-joint calibration exists (calib.py); a general arm hand-eye (AX = XB) package does not",
        references=(refs.TSAI_1989, refs.PARK_1994, refs.DANIILIDIS_1999)),
    CalibrationPackage(
        "kinematic_length", "Kinematic Length", "Kinematic length calibration (link lengths, joint zeros, mounts)",
        ("arm_6dof", "arm_subassembly", "arm_6dof_gripper"),
        (CodeHome(BAM_WS, "src/core/mdp/setup/bam_calibration/src/bam_calibration/calibrate.py",
                  note="UR-style dual-arm closed-chain calibration: joint encoders only, the partner arm is the instrument"),
         CodeHome(BAM_WS, "src/core/mdp/setup/bam_calibration/src/bam_calibration/canonical.py", ref=KINCAL_BRANCH,
                  note="the multi-arm study (58-parameter chain, rungs R0-R4), not merged")),
        "partial", note="Zach, Nov 5: he will do this in a separate UR kinematic calibration package; bam_calibration (bam_ws) is "
                        "today's code and its study branch the evidence",
        references=(refs.HOLLERBACH_WAMPLER_1996, refs.HAYATI_1983, refs.OKAMURA_1996, refs.HOLLERBACH_2016)),
    CalibrationPackage(
        "servo_dynamic.actuator", "Servo Dynamic", "Servo dynamic calibration, actuator level", ("servo", "gearbox", "motor", "driver", "conveyor"),
        (CodeHome(BAM_WS, f"{TWIN}/identify.py", note="gravity, friction and inertia from the training runs, each with a 95 % CI"),
         CodeHome(BAM_WS, f"{TWIN}/backlash.py", note="backlash from staircase holds (camera on the output)"),
         CodeHome(BAM_WS, f"{TWIN}/live_reid.py", note="T10: recursive least squares with forgetting, while the joint works"),
         CodeHome(BAM_WS, f"{TWIN}/schedule.py", note="the test schedule and its coverage before anything runs"),
         CodeHome(ROBOTPARTS, "tools/models/twin_fits.py", note="publishes the fits as robotparts M1.datasheet ... M4.twin.backlash"),
         CodeHome(PIDTUNA, "src/pidtuna/identify.py", note="the same regressor from any motion, batch and recursive")),
        "exists", level="actuator",
        references=(refs.ARMSTRONG_1994, refs.SWEVERS_1997, refs.HOLLERBACH_2016)),
    CalibrationPackage(
        "servo_dynamic.arm", "Servo Dynamic", "Servo dynamic calibration, arm level", ("arm_6dof", "arm_subassembly", "arm_6dof_gripper"),
        (CodeHome(PIDTUNA, "src/pidtuna/arm.py", note="every joint tuned as a box with the robot model's gravity, inertia and coupling as feed-forward"),
         CodeHome(PIDTUNA, "src/pidtuna/plants/mujoco_arm.py", note="the arm plant it identifies against (a MuJoCo arm)")),
        "partial", level="arm",
        note="per-joint identification inside the arm exists (pidtuna); an arm-level base-parameter fit (excitation trajectories, "
             "the minimal inertial set) was not found",
        references=(refs.GAUTIER_1990, refs.SWEVERS_1997, refs.ATKESON_1986)),
    CalibrationPackage(
        "camera.rgb", "Camera", "Camera calibration, RGB (intrinsics, distortion, extrinsics)", ("camera_rgb",),
        (CodeHome(BAM_WS, f"{TWIN}/calib.py", note="bundle adjustment of camera poses and intrinsics against the rack's CAD"),
         CodeHome(BAM_WS, "src/core/mdp/setup/bam_calibration/docs/ref/bam_calibration/dev/camera_calibration/camera_calibration_v2.py",
                  note="older ChArUco intrinsics script, kept as reference"),
         CodeHome(IO_DX, "robotdx/diagnostics/stock/camera.py", note="RobotDx's reprojection_error and marker_drift: the checks that say when to recalibrate")),
        "partial", references=(refs.ZHANG_2000, refs.HEIKKILA_1997, refs.BROWN_1966)),
    CalibrationPackage(
        "camera.rgbd", "Camera", "Camera calibration, RGBD (depth scale, depth-to-colour, depth bias)", ("camera_rgbd",),
        (CodeHome(BAM_WS, "src/core/mdp/agent/sensors/intel_rgbd/src/intel_rgbd/real.py", note="the D405 / D435 driver: factory intrinsics and depth scale per frame"),
         CodeHome(BAM_WS, "src/core/mdp/agent/sensors/intel_rgbd/src/intel_rgbd/twin.py", note="the depth twin the cloud is compared with"),
         CodeHome(IO_DX, "robotdx/diagnostics/stock/camera.py", note="depth_plane (Z accuracy, plane RMS, fill rate, temporal noise)")),
        "partial", note="factory calibration is read, not re-estimated; on-chip self-calibration is RobotDx's proposed depth.health_check",
        references=(refs.KHOSHELHAM_2012, refs.HERRERA_2012)),
    CalibrationPackage(
        "camera.hsi", "Camera", "Camera calibration, hyperspectral (dark / white references, band centres, smile and keystone)", ("camera_hsi",),
        (), "unknown", note="bam_ws src/core/mdp/agent/world_model/bam_hyper holds docs only; the camera's driver is Windows-only",
        references=(refs.BURGER_2011, refs.MOUROULIS_2000)),
    CalibrationPackage(
        "camera.line_area_scan", "Camera", "Camera calibration, line / area scan (line geometry against the belt)", ("camera_hsi", "camera_rgb", "conveyor"),
        (CodeHome(BAM_WS, "src/core/mdp/agent/world_model/bam_scan_tunnel/src/bam_scan_tunnel/camera_geometry.py",
                  note="pinhole math the scan tunnel projects belt-fixed boxes with"),
         CodeHome(BAM_WS, "src/core/mdp/agent/world_model/bam_scan_tunnel/src/bam_scan_tunnel/belt.py", note="the belt clock the lines are stamped on")),
        "partial", note="geometry and the belt clock exist; no line-scan calibration routine", references=(refs.GUPTA_1997,)),
    CalibrationPackage(
        "pid", "PID", "PID calibration (gains from the identified model, then measured tuning)", ("servo", "driver", "arm_6dof", "arm_subassembly", "conveyor"),
        (CodeHome(PIDTUNA, "src/pidtuna/tune.py", note="pidtuna: analytic start, bandwidth search, gates; proposes, never writes a board"),
         CodeHome(BAM_WS, "src/core/mdp/setup/bam_pid_tunning/src/bam_pid_tunning/finetune.py", ref=PID_BRANCH,
                  note="the auto-tuner on the rack, not merged (virtual-only per Zach, 2026-10-25)")),
        "exists", references=(refs.HOLLERBACH_2016,)),
    CalibrationPackage(
        "hardstop_homing", "Hardstop / Homing / Rezeroing", "Hardstop, homing and rezeroing", ("servo", "arm_subassembly", "arm_6dof", "encoder"),
        (CodeHome(BAM_WS, "src/core/mdp/setup/bam_homing/src/bam_homing/hardstop_seek.py", note="seek a hard stop, latch the datum"),
         CodeHome(BAM_WS, "src/core/mdp/setup/bam_homing/src/bam_homing/controller.py", note="the HomingController the rack and the sim both run"),
         CodeHome(BAM_WS, f"{TWIN}/hardstop.py", note="hardstop metrics from a hardstop run, and the CAD twin's datum"),
         CodeHome(BAM_WS, f"{TWIN}/homing_sim.py", note="homing one payload joint in MuJoCo with the unchanged controller")),
        "exists", references=(refs.HOLLERBACH_WAMPLER_1996,)),
)


# --- equipment (2026-11-07) ------------------------------------------------------------------------------------------------------

def Q(value, unit, source, note=""):
    return Quantity(None if value is None else float(value), unit, source, note)


D405_PRICE = ("camera-atlas data/cameras.json realsense-d405: USD 325, the RealSense store, accessed 2026-10-18 "
              "(/home/bam/camera-atlas); printed tags cost next to nothing")

EQUIPMENT = {e.id: e for e in (
    Equipment("camera_tags", "A calibrated camera and printed ArUco / AprilTags (on the output, a flange, a gripper or the belt)",
              Q(325, "USD", D405_PRICE), "the rack's link camera is a D405 on tags 8-12; a belt mark tracker is the same kit"),
    Equipment("laser_tracker", "A laser tracker with a 6-DOF probe on the flange (Leica AT960 / FARO Vantage class)", Q(100_000, "USD", ESTIMATE),
              "the oracle's tracker reads 0.15 mm and 0.5 mrad; a calibrated camera and a flange tag is the cheap stand-in (camera_tags)"),
    Equipment("coupling_plate", "A rigid plate coupling two arms' flanges into one closed chain (and the partner arm)", Q(200, "USD", ESTIMATE),
              "the partner arm is a robot the cell already has; the plate is the only purchase"),
    Equipment("output_clamp", "A fixture that locks a joint's output", Q(150, "USD", ESTIMATE)),
    Equipment("dynamometer", "A dynamometer: a speed-controlled load motor, an inline torque sensor, couplings and a DAQ", Q(5_000, "USD", ESTIMATE),
              "none on the rack"),
    Equipment("weighed_mass", "A weighed mass at a known radius", Q(50, "USD", ESTIMATE)),
    Equipment("thermocouple", "A thermocouple on the winding and its reader", Q(30, "USD", ESTIMATE)),
    Equipment("charuco_board", "A ChArUco board printed on a rigid flat", Q(50, "USD", ESTIMATE)),
    Equipment("dot_card", "A printed dot card with a certified step, and risers", Q(100, "USD", ESTIMATE)),
    Equipment("grey_card", "An 18 % grey card (or the white tile) under the deployment's lights", Q(30, "USD", ESTIMATE)),
    Equipment("led_blinker", "An LED switched by the host on a stamped clock, in the camera's view", Q(20, "USD", ESTIMATE)),
    Equipment("flat_target", "A flat, matte, textured board and a tape or rangefinder for its distance", Q(100, "USD", ESTIMATE)),
    Equipment("spectral_lamp", "A mercury-argon (or krypton for SWIR) pen lamp with known emission lines", Q(400, "USD", ESTIMATE)),
    Equipment("bar_target", "Spectral and spatial bar targets across the field (a slit grid and an edge)", Q(200, "USD", ESTIMATE)),
    Equipment("reflectance_refs", "White, grey and black reflectance references and a dark cap", Q(1_500, "USD", ESTIMATE),
              "Spectralon-grade; a printed card is cheaper and drifts"),
    # the conveyor belt's geometry (2026-11-11, additive)
    Equipment("belt_charuco_acm", "A 7 x 5 ChArUco board (40 / 30 mm, DICT_5X5_100) printed on 3 mm aluminium composite, flat on the belt",
              Q(23, "USD", "zach_brain Sources/Chats/Claude Code/2026-10-03 — 9c458d05 (CHAT).md: C$32 printed on 3 mm ACM"),
              "aluminium on matte black shows in RGB, depth and the hyperspectral bands alike"),
    Equipment("divot_board", "The belt ChArUco with four conical divots at its corners, for an arm's touch", Q(60, "USD", ESTIMATE)),
    Equipment("probe_ball_tip", "A 6 mm ball tip on arm 1's flange and its joint-current read-back as a load cell", Q(30, "USD", ESTIMATE)),
    Equipment("belt_load", "15 kg of sandbags spread on the belt", Q(20, "USD", ESTIMATE)),
)}


def I(card: str, rung: str, *parameters: str) -> Identifies:
    return Identifies(card, rung, tuple(parameters))


def C(card: str, *settings: str) -> Configures:
    return Configures(card, tuple(settings))


def routine(id, title, package, identifies, setting, wall_time, operator_time, equipment, excitation, coverage, repeats, how, **kw):
    return CalibrationRoutine(id, title, package, tuple(identifies), setting, wall_time, operator_time, tuple(equipment), excitation, coverage,
                              int(repeats), how, **kw)


NO_HARD_STOP = "the sysid oracle has no hard-stop scene yet"
CAN11 = "sysid/results/pendulum_can11.json"
UR5E = "sysid/results/ur5e.json"
SWEEP_S = 2 * 3.141592653589793 * 25.0 / 3.0  # gear_backlash ur/calibration.py SweepConfig: a +-25 deg sine at 3 deg/s, one period

# --- the routines (2026-11-07) ---------------------------------------------------------------------------------------------------
# Grouped by package. Times: the motion a sysid example plans is cited from its committed result; set-up and hands-on times nobody has
# measured are estimates, and say so. The oracle column names the sysid noise-ladder checks (sysid/noise_ladder.json) that run the
# routine's own code against a hidden truth; a routine whose code sysid cannot import, or that has no code, says why in oracle_note.

ROUTINES = (
    # --- hardstop / homing / rezeroing -----------------------------------------------------------------------------------------
    routine("homing.single_touch", "Homing zero, single touch", "hardstop_homing",
         (I("arm_6dof", "M1", "joint_zero_offsets"), I("arm_subassembly", "M1", "joint_offsets")), "both",
         Q(20, "s", ESTIMATE, "one seek at homing speed into the stop, per joint"), Q(0, "s", ESTIMATE, "unattended"), (),
         "one slow seek into the joint's hard stop at a capped torque", "one point: the stop (no range)", 1,
         "drive the joint into its stop at a capped torque and latch the encoder when it stalls; the zero is that reading minus the stop's "
         "CAD angle",
         oracle_note=f"not implemented: no single-touch seek exists in code (bam_homing's seek presses, backs off, probes and re-presses: "
                     f"homing.repeat_checked_seek), and {NO_HARD_STOP}",
         alternatives=("homing.repeat_averaged", "homing.repeat_checked_seek"),
         note="its error: the stall detection's timing times the seek speed and one encoder noise draw (random), and the stop's and the "
              "gear's give under the seek torque, and which flank of the gap the stop leaves the gear on (bias)",
         references=(refs.HOLLERBACH_WAMPLER_1996,)),
    routine("homing.repeat_averaged", "Homing zero, N touches averaged (Prusa-style)", "hardstop_homing",
         (I("arm_6dof", "M1", "joint_zero_offsets"), I("arm_subassembly", "M1", "joint_offsets")), "both",
         Q(100, "s", ESTIMATE, "five seeks, backing off between them, per joint"), Q(0, "s", ESTIMATE, "unattended"), (),
         "N seeks into the stop at the same capped torque, backing off between them", "one point: the stop, approached N times", 5,
         "touch the stop N times, backing off between touches; the zero is the mean of the N latched readings (Zach, 2026-11-07: "
         "'Prusa-style; more time, better accuracy')",
         oracle_note=f"not implemented: nothing averages N touches today, and {NO_HARD_STOP}",
         alternatives=("homing.single_touch", "homing.repeat_checked_seek"),
         note="averaging divides the random part of single_touch's error by sqrt(N); the bias (give under the seek torque, the flank) "
              "stays where it was, so N buys accuracy only while the random part dominates",
         references=(refs.HOLLERBACH_WAMPLER_1996,)),
    routine("homing.repeat_checked_seek", "Homing zero, bam_homing's checked seek (press, probe, re-press)", "hardstop_homing",
         (I("arm_6dof", "M1", "joint_zero_offsets"), I("arm_subassembly", "M1", "joint_offsets")), "both",
         Q(30, "s", ESTIMATE, "press, back off, probe at half speed, re-press"), Q(0, "s", ESTIMATE, "unattended"), (),
         "a press at the seek cap, a back-off, a probe at half the cap and half the speed, a re-press in place",
         "one point: the stop, touched twice", 2,
         "bam_homing's four-stage group seek: the stop is declared only if its location, stiffness and repeat hold; nothing is recorded "
         "until the last barrier has passed",
         code=(CodeHome(BAM_WS, "src/core/mdp/setup/bam_homing/src/bam_homing/hardstop_seek.py", note="HardstopSeekGroup, the functional core"),
               CodeHome(BAM_WS, "src/core/mdp/setup/bam_homing/src/bam_homing/controller.py", note="HomingController")),
         status="implemented",
         oracle_note=f"not in the sysid ladder: bam_rack_twin homing_sim.py runs this controller in MuJoCo in bam_homing's own environment "
                     f"(cad2robot payloads), which sysid's process does not load; {NO_HARD_STOP}",
         alternatives=("homing.single_touch", "homing.repeat_averaged"),
         references=(refs.HOLLERBACH_WAMPLER_1996,)),

    # --- kinematic length --------------------------------------------------------------------------------------------------------
    routine("kinematics.zero_offsets_tracker", "Joint zeros (and the TCP) from a tracked flange at static poses", "kinematic_length",
         (I("arm_6dof", "M1", "joint_zero_offsets"), I("arm_6dof_gripper", "M0", "tcp_offset")), "bench",
         Q(60 + 120 + 1800, "s", f"60 s of settling at 40 poses: {UR5E} schedule.train.settle_s; 120 s of moves and 1800 s of tracker set-up: "
                                 f"{ESTIMATE}"),
         Q(1800, "s", ESTIMATE, "setting the tracker up and its target on the flange"), ("laser_tracker",),
         "static poses spread over every joint's range (40 in the oracle), each held still", "the poses spread each joint over its range", 1,
         "least squares of FK(encoder + offset) on the tracker's flange pose at each pose, the TCP marker's position beside it when the arm "
         "carries a tool; 95 % from the Jacobian (Levenberg-Marquardt)",
         tests=("arm_6dof.kinematic_calibration", "arm_6dof_gripper.tcp_tag"),
         code=(CodeHome(SIM2REAL, "sysid/arm.py", note="fit_kinematics"),), status="implemented",
         oracle=("ur5e:kinematics.zero_offsets_tracker", "ur5e_2f85:kinematics.zero_offsets_tracker"),
         alternatives=("kinematics.dh_ur_style", "kinematics.general_transform"),
         note="Zach's 'Nominal DH closed form' (Nov 6) plus the zeros: the UR examples hide only zero errors, so a link-length error would "
              "land in the zeros",
         references=(refs.HOLLERBACH_WAMPLER_1996, refs.HOLLERBACH_2016)),
    routine("kinematics.dh_ur_style", "UR-style DH calibration (two arms in a closed chain, then the UR offset correction)", "kinematic_length",
         (I("arm_6dof", "M2", "dh_errors", "joint_zero_offsets", "base_frame", "tool_frame"),), "bench",
         Q(3600, "s", ESTIMATE, "a few hundred closed-chain poses"), Q(1800, "s", ESTIMATE, "bolting the plate between the flanges"),
         ("coupling_plate",),
         "joint encoder readings at many poses of the two arms bolted flange to flange", "poses that excite every DH error's direction (the Jacobian's rank)", 1,
         "Levenberg-Marquardt on delta theta, a, d and alpha per joint (UR's calibration.conf) from the closure mismatch of the coupled chain "
         "(the UR patent's shape, as bam_calibration's calibrate.py puts it), then ur_calibration's correction that folds the large offsets of "
         "parallel axes back into URDF-shaped joint frames",
         tests=("arm_6dof.kinematic_calibration",),
         code=(CodeHome(BAM_WS, f"{KINCAL}/patent.py", ref=KINCAL_BRANCH,
                        note="the UR patent's loop model (its docstring: US 9,248,573): DH rows, the parallel axes' Psi rows, the horse and connector"),
               CodeHome(BAM_WS, f"{KINCAL}/canonical.py", ref=KINCAL_BRANCH,
                        note="a DH / Hayati link table from the joint lines alone: the part UR's offset correction plays"),
               CodeHome(BAM_WS, f"{KINCAL}/calibrate.py", note="main: the closed-chain estimator, for the bam_fb arm")),
         status="implemented",
         oracle_note="graded by its own lane, not sysid's ladder: the kinematic calibration study on its unmerged bam_ws branch (claude/kinematic-"
                     "calibration-multi-arm-4645cc, WORKORDER-2026-11-06: sim ground truth, sensor noise varied, median of >= 8 seeds; evaluation.py "
                     "scores CAL_DH, the UR-structured projection of the calibrated chain against the hidden TRUE on held-out readings), whose code "
                     "sysid cannot import from bam_ws main",
         alternatives=("kinematics.zero_offsets_tracker", "kinematics.general_transform"),
         note="Zach, Nov 6: '1. DH parameter calibration 1. based on UR algorithim 2. then we do UR offset thing so that the transforms look "
              "more reasonable... (there is reference on that on github)'",
         references=(refs.HAYATI_1983, refs.UR_DH, refs.UR_CALIBRATION, refs.HOLLERBACH_WAMPLER_1996)),
    routine("kinematics.general_transform", "General transform calibration (a 6-DOF correction on every link frame)", "kinematic_length",
         (I("arm_6dof", "M2", "dh_errors", "joint_zero_offsets", "base_frame", "tool_frame"),), "bench",
         Q(3600, "s", ESTIMATE, "a few hundred tracked poses"), Q(1800, "s", ESTIMATE, "tracker set-up"), ("laser_tracker",),
         "static poses spread over the workspace, each held still", "poses that excite every frame's six directions", 1,
         "a full 6-DOF correction on each link frame ('the general solution', Zach, Nov 6), the directions no measurement can see (along and "
         "about consecutive axes) removed by the fit's SVD; no closed-form IK survives it, so it pairs with kinematics.ik_fine_tune",
         tests=("arm_6dof.kinematic_calibration",),
         code=(CodeHome(BAM_WS, f"{KINCAL}/evaluation.py", ref=KINCAL_BRANCH, note="CAL_FULL, the calibrated full-chain rig, scored against TRUE"),
               CodeHome(BAM_WS, f"{KINCAL}/arm_model.py", note="main: the bam_fb arm's 'full' model, a 6-DOF delta on each mount frame (DELTA_FRAMES)")),
         status="implemented",
         oracle_note="graded by its own lane, not sysid's ladder: the kinematic calibration study on its unmerged bam_ws branch (claude/kinematic-"
                     "calibration-multi-arm-4645cc, WORKORDER-2026-11-06: sim ground truth, sensor noise varied, median of >= 8 seeds; evaluation.py "
                     "scores CAL_FULL, the calibrated full-chain rig against the hidden TRUE on held-out readings), whose code sysid cannot import "
                     "from bam_ws main",
         alternatives=("kinematics.zero_offsets_tracker", "kinematics.dh_ur_style"),
         references=(refs.OKAMURA_1996, refs.HOLLERBACH_2016)),
    routine("kinematics.ik_fine_tune", "IK fine-tune: the closed form's answer refined on the calibrated model", "kinematic_length", (), "both",
         Q(0.001, "s", ESTIMATE, "per solve: a few Newton steps from the closed form's seed"), Q(0, "s", ESTIMATE, "none: it runs in the planner"),
         (), "none: a target pose at run time", "every target the arm is sent to", 1,
         "the closed-form UR solution on the nominal DH (bam_arm's offset-wrist kinematics) seeds a Newton / damped least-squares solve on the "
         "calibrated model (KDL's ChainIkSolverPos_NR scheme); Zach's metrics: compute time, final accuracy, and its gain over the closed form",
         kind="use",
         code=(CodeHome(BAM_WS, f"{KINCAL}/ik.py", ref=KINCAL_BRANCH,
                        note="UR closed form on CAL_DH, then damped Newton on CAL_FULL, scored on TRUE after k = 0..K steps"),
               CodeHome(BAM_WS, "src/core/mdp/env/sim/bam_arm/bam_arm/kinematics/offset_wrist_math.py",
                        note="main: the closed-form seed (compas_fab's offset wrist, from ros-industrial ur_kin.cpp)")),
         status="implemented",
         oracle_note="graded by its own lane, not sysid's ladder: the kinematic calibration study on its unmerged bam_ws branch (claude/kinematic-"
                     "calibration-multi-arm-4645cc, WORKORDER-2026-11-06: sim ground truth, sensor noise varied, median of >= 8 seeds; evaluation.py "
                     "scores the refined IK's tool error and compute time against the hidden TRUE on held-out readings), whose code sysid cannot "
                     "import from bam_ws main",
         note="Zach, Nov 6: 'Please check if there is like a stock implementation of IK inverse J we can use ... Moveit uses KDL off the shelf'",
         references=(refs.KDL_NR,)),

    # --- servo dynamic, actuator level ---------------------------------------------------------------------------------------------
    routine("servo.dynamics_regression", "Servo dynamics from excitation: one inverse-dynamics regression over the schedule's runs",
         "servo_dynamic.actuator",
         (I("servo", "M0", "armature_kg_m2", "gravity_nm"), I("servo", "M2", "frictionloss_nm", "damping_nm_s_rad"),
          I("servo", "M3", "friction_stribeck_drop_nm")), "bench",
         Q(771.8 + 600, "s", f"771.8 s of train motion (46 runs): {CAN11} schedule.train.seconds; 600 s set-up: {ESTIMATE}"),
         Q(600, "s", ESTIMATE, "starting and watching the schedule"), (),
         "the servo schedule's train families: chirps, plateaus, gravity sweeps, multisines, pick-and-place, jogs (bam_rack_twin.schedule)",
         "the servo card's gate, 40 % of the reachable (q, qd, qdd) cells (CAN 11's train visits 66.15 %)", 1,
         "tau(t + shift) = J qdd + G sin(q - bottom) + friction(qd) over every moving train row on the stock smoother's grid (M2, M3 with the "
         "Stribeck speed profiled), the rigid terms again where the gear is in contact (M4), the static level and drop polished by output "
         "error; 95 % by the stock block bootstrap",
         tests=("servo.full_schedule", "servo.plateaus", "servo.gravity", "servo.chirp"),
         code=(CodeHome(SIM2REAL, "sysid/examples/pendulum_can11/pipeline.py", note="identify()"),), status="implemented",
         oracle=("pendulum_can11:servo.dynamics_regression",),
         alternatives=("servo.dynamometer", "servo.stock_quasistatic", "servo.live_reid_t10"),
         references=(refs.SWEVERS_1997, refs.ARMSTRONG_1994, refs.HOLLERBACH_2016)),
    routine("servo.stock_quasistatic", "Servo dynamics, quasi-static: gravity sweeps, plateaus and chirps (bam_rack_twin.identify)",
         "servo_dynamic.actuator",
         (I("servo", "M0", "armature_kg_m2", "gravity_nm"), I("servo", "M2", "frictionloss_nm", "damping_nm_s_rad")), "bench",
         Q(771.8 + 600, "s", f"the gravity, plateau and chirp runs of the same schedule (of its 771.8 s: {CAN11}); 600 s set-up: {ESTIMATE}"),
         Q(600, "s", ESTIMATE), (),
         "slow gravity sweeps both ways, velocity plateaus at 6-8 speeds each way, position chirps", "the sweeps over the range, the plateaus' speeds", 1,
         "three quasi-static fits: gravity from the slow sweeps, Coulomb + viscous from the plateaus, inertia from the chirps (each with a 95 % CI)",
         tests=("servo.gravity", "servo.plateaus", "servo.chirp"),
         code=(CodeHome(BAM_WS, f"{TWIN}/identify.py", note="identify_without_cad"),), status="implemented",
         oracle=("pendulum_can11:servo.stock_quasistatic",),
         alternatives=("servo.dynamics_regression", "servo.dynamometer", "servo.live_reid_t10"),
         references=(refs.ARMSTRONG_1994, refs.OLSSON_1998)),
    routine("servo.live_reid_t10", "Live re-identification, the rack's T10 drift routine (60 s of RLS while the joint works)", "servo_dynamic.actuator",
         (I("servo", "M0", "armature_kg_m2", "gravity_nm"), I("servo", "M2", "frictionloss_nm", "damping_nm_s_rad")), "deployed",
         Q(60, "s", "bam_rack_twin docs/round4_study.py LIVE_REID_SECONDS = 60 (acceptance.py T10: 'a 60 s live routine restores T2 after drift')"),
         Q(0, "s", "bam_rack_twin live_reid.py: the board's own q, qd and torque while the joint works; no person"), (),
         "the joint's own work for 60 s (here the deployed check's H2 operate runs; on the rack, reid_can12's sweeps, fast moves and chirp)",
         "whatever 60 s of work visits (no gate)", 1,
         "recursive least squares with forgetting 0.999 on tau = J qdd + b qd + Fc tanh(qd / 0.05) + g_s sin q + g_c cos q, rows on the reply "
         "grid with Savitzky-Golay derivatives (11 samples, cubic); G = hypot(g_s, g_c)",
         tests=("servo.live_reid",),
         code=(CodeHome(BAM_WS, f"{TWIN}/live_reid.py", note="Rls"),
               CodeHome(BAM_WS, "src/dev/bam_rack_twin/docs/round4_study.py", note="live_reid_estimates: the 60 s routine's rows")),
         status="implemented", oracle=("pendulum_can11:servo.live_reid_t10",),
         alternatives=("servo.dynamics_regression", "servo.stock_quasistatic", "servo.dynamometer")),
    routine("servo.dynamometer", "Servo dynamics on a dynamometer bench (a load motor and an inline torque sensor)", "servo_dynamic.actuator",
         (I("servo", "M0", "armature_kg_m2"), I("servo", "M2", "frictionloss_nm", "damping_nm_s_rad"), I("servo", "M3", "friction_stribeck_drop_nm"),
          I("servo", "M4", "torque_scale")), "bench",
         Q(7200, "s", ESTIMATE, "mount, a speed sweep each way, acceleration steps, unmount"), Q(3600, "s", ESTIMATE), ("dynamometer",),
         "speed plateaus each way under a speed-controlled load, acceleration steps", "the servo card's speed and torque axes, each plateau held", 3,
         "back-drive or load the servo at held speeds: the inline sensor reads the friction curve directly; acceleration steps give the inertia; "
         "the sensor against the board's reported torque gives the torque scale",
         tests=("gearbox.dyno_efficiency", "motor.dyno_map"),
         oracle_note="not implemented: no dynamometer on the rack, and none simulated in the sysid oracle",
         alternatives=("servo.dynamics_regression", "servo.stock_quasistatic", "servo.live_reid_t10", "arm.dynamics_excitation", "servo.known_mass"),
         note="Zach, Nov 6: 'dynameter could be one... but if you don't have access to that...'",
         references=(refs.ARMSTRONG_1994,)),
    routine("servo.known_mass", "Torque scale from a weighed mass (T6)", "servo_dynamic.actuator",
         (I("servo", "M4", "torque_scale"), I("servo", "M5", "kt_out_nm_a")), "bench",
         Q(900, "s", ESTIMATE), Q(600, "s", ESTIMATE, "hanging the mass at its radius"), ("weighed_mass",),
         "gravity sweeps bare and with the weighed mass at a known radius", "the joint's range, both ways", 1,
         "the extra gravity torque of a known mass at a known radius against the board's reported torque: Kt_true / Kt_board",
         tests=("servo.known_mass",),
         code=(CodeHome(BAM_WS, f"{TWIN}/drive_gain.py"),), status="implemented",
         oracle_note="not in the sysid ladder: the oracle's truth hides no torque-scale error (the board's Kt is the description's), so there is "
                     "nothing to recover yet",
         alternatives=("servo.dynamometer",)),
    routine("servo.top_speed_t7", "Drive ceilings from top-speed plateaus (T7)", "servo_dynamic.actuator",
         (I("servo", "M5", "voltage_available_v", "kt_out_nm_a"),), "bench",
         Q(900, "s", ESTIMATE), Q(300, "s", ESTIMATE), (),
         "velocity plateaus up to the speed the bus allows", "the top of the speed axis at the station's bus voltage", 1,
         "the speed each plateau tops out at against the bus voltage and the torque it carries: the voltage available and the output Kt",
         tests=("servo.top_speed",),
         code=(CodeHome(BAM_WS, f"{TWIN}/envelope.py"),), status="implemented",
         oracle_note="not in the sysid ladder: the oracle's truth holds no drive ceilings (the board's voltage and current limits are the "
                     "description's), so there is nothing hidden to recover"),
    routine("servo.heating_t8", "Winding thermal model from a heating run (T8)", "servo_dynamic.actuator",
         (I("servo", "M4", "thermal_r_c"),), "bench",
         Q(3600, "s", ESTIMATE, "a long hold at high current, then the cool-down"), Q(900, "s", ESTIMATE, "fitting the thermocouple"),
         ("thermocouple",),
         "a long hold at high current, then the cool-down", "the winding's temperature range from cold to its limit", 1,
         "the two-node thermal model's resistances and time constants fitted to the thermocouple on the winding",
         tests=("servo.heating",),
         code=(CodeHome(BAM_WS, f"{TWIN}/hardware/thermal.py"), CodeHome(BAM_WS, f"{TWIN}/thermal_model.py")), status="implemented",
         oracle_note="not in the sysid ladder: the oracle's truth has no thermal model, so there is nothing hidden to recover"),
    routine("servo.backlash_reversals_camera", "Backlash from load reversals, seen by a camera on the output", "servo_dynamic.actuator",
         (I("servo", "M4", "backlash_rad"),), "bench",
         Q(771.8 + 600, "s", f"the same schedule's runs ({CAN11}: 771.8 s); 600 s camera set-up: {ESTIMATE}"), Q(600, "s", ESTIMATE),
         ("camera_tags",),
         "load reversals in the schedule's runs: the gear crosses its gap each time the torque changes sign", "rows on both contact levels (both flanks)", 1,
         "two-means of (motor encoder - link camera) over every train row: the two contact levels, each re-taken as the median within a quarter "
         "gap of it; the gap is their distance (bootstrap over runs)",
         tests=("servo.staircase",),
         code=(CodeHome(SIM2REAL, "sysid/examples/pendulum_can11/pipeline.py", note="backlash_from_gaps"),
               CodeHome(BAM_WS, f"{TWIN}/backlash.py", note="the rack's: the gap from staircase holds")),
         status="implemented", oracle=("pendulum_can11:servo.backlash_reversals_camera",),
         alternatives=("servo.backlash_clamp", "arm.backlash_gravity_sweep", "arm.backlash_reversal_tracker"),
         references=(refs.NORDIN_2002,)),
    routine("servo.backlash_clamp", "Backlash and gear stiffness from a locked-output clamp test", "servo_dynamic.actuator",
         (I("servo", "M4", "backlash_rad", "gear_stiffness_nm_rad"), I("gearbox", "M4", "backlash_rad", "gear_stiffness_nm_rad")), "bench",
         Q(1200, "s", ESTIMATE, "fit the clamp, cycle the torque, remove"), Q(900, "s", ESTIMATE), ("output_clamp",),
         "slow torque cycles of +-0.5 N.m at the motor with the output locked", "both flanks, past the torque that opens the loop", 3,
         "lock the output and cycle the motor's torque slowly through zero: the motor encoder's travel between the two flank contacts is the "
         "gap, the branches' slopes the mesh stiffness (gear_backlash clamp_test.fit_clamp; it refuses when the loop never opens)",
         tests=("gearbox.clamp", "servo.staircase"),
         code=(CodeHome(BAM_WS, f"{GEAR_BACKLASH}/clamp_test.py", ref=BACKLASH_BRANCH, note="fit_clamp, on an unmerged branch (8e8501bd8)"),),
         status="implemented",
         oracle_note="not in the sysid ladder: the clamp test lives on an unmerged bam_ws branch (claude/backlash-simulation-7673dc, 8e8501bd8) "
                     "and sysid imports bam_ws main only; its own 648-run study (examples/clamp_test_study.py) is its oracle so far",
         alternatives=("servo.backlash_reversals_camera", "arm.backlash_gravity_sweep", "arm.backlash_reversal_tracker"),
         references=(refs.NORDIN_2002, refs.TUTTLE_1996)),
    routine("servo.gap_check_forecast", "Deployed gap check every 12 h on the daily motions, with the wear forecast", "servo_dynamic.actuator",
         (I("servo", "M4", "backlash_rad"), I("servo", "M5.wear", "backlash_wear_rad_per_nm_rev")), "deployed",
         Q(77.7, "s", "sysid/examples/pendulum_can11/description.json monitoring.check: the H2 operate runs, 77.7 s, every 12 h"),
         Q(0, "s", "the check runs on the joint's daily motions; no person"), ("camera_tags",),
         "the joint's daily motions (H2 operate: pickplace, cycle, jog, sweep)", "the motions the joint makes all day", 1,
         "each check measures the gap as commissioning does (motor encoder - link camera) and warns when it has grown past the station's "
         "allowance over the commissioned gap (servo.gap_drift, in rad; CAN 11's is T5's 2 arcmin) or when the twin's fidelity ratio passes "
         "the servo card's drift threshold (servo.drift), whichever comes first; a line on hours gives the wear rate, and "
         "the forecast solves it for the hour the gap reaches the commissioned gap plus the allowance",
         tests=("servo.wear_regression",),
         code=(CodeHome(SIM2REAL, "sysid/drift.py", note="run_backlash"),), status="implemented",
         oracle=("pendulum_can11:servo.gap_check_forecast",),
         note="WHY in the gap's own units (2026-11-07, docs/decision-calibration-routines-2026-11-07.md, addendum): the old alarm, live fidelity "
              "over the camera's floor, went deaf as the camera's noise grew (never inside 480 h at 3x); the gap's alarm does not read the "
              "camera's floor. The ratio is still computed on the same checks and the alarm warns on either one (the addendum's last line)"),
    routine("servo.camera_dwell_stop_ruler", "The rack's camera dwell stop ruler: T4 at a geared joint's output", "servo_dynamic.actuator",
         (), "bench",
         Q(600, "s", ESTIMATE, "the light check and a stop tape with 3 s dwells"), Q(300, "s", ESTIMATE, "lighting and tag checks"), ("camera_tags",),
         "T4's stop tape: dwells of 3 s at targets, both approach directions", "stops in both approach directions over the joint's range", 60,
         "each stop's output angle is the station tag's turn averaged over the dwell's still tail (2 s, never its first 150 ms), with its "
         "standard error; anchored on the train stops (a direct drive) or on all stops (geared, PEP 0011)",
         kind="measure", tests=("servo.stop_hold",),
         code=(CodeHome(BAM_WS, f"{TWIN}/stop_camera.py"),), status="implemented",
         oracle_note="not in the sysid ladder: the oracle's link camera is white noise on every 10 ms sample, not the D405's ~30 fps frames at "
                     "2-11 mrad each (stop_camera.py's own figures), so a ladder run would grade the ruler on a camera it does not have",
         note="a gauge, not a fit: it measures the output stop error (T4's metric) and the common-mode anchor; repeats = the ~60 frames of a 2 s "
              "tail at 30 fps (TAIL_S = 2.0)"),

    # --- servo dynamic, arm level --------------------------------------------------------------------------------------------------
    routine("arm.dynamics_excitation", "Joint dynamics from Fourier excitations and the coverage sweep (each joint a servo)", "servo_dynamic.arm",
         (I("servo", "M0", "armature_kg_m2"), I("servo", "M2", "frictionloss_nm", "damping_nm_s_rad"), I("arm_6dof", "M3", "link_inertials")), "bench",
         Q(488.3 + 60 + 600, "s", f"488.3 s of motion (4 Fourier excitations and the coverage sweep) and 60 s settling: {UR5E} schedule.train; "
                                  f"600 s set-up: {ESTIMATE}"),
         Q(600, "s", ESTIMATE), (),
         "Swevers et al.'s Fourier excitations (0.2 Hz base, 5 harmonics) and a collision-free Sobol coverage sweep",
         "the arm card's gate, 40 % of the mount's 2,560 reachable joint cells (the sweep runs to 42 %)", 1,
         "weighted least squares of joint torque - MuJoCo's rigid inverse dynamics on qdd, qd and sgn(qd) per joint, the tool's mass and centre of "
         "mass as columns when it carries one; 95 % by a moving-block bootstrap",
         tests=("arm_6dof.excitation",),
         code=(CodeHome(SIM2REAL, "sysid/arm.py", note="fit_dynamics"),), status="implemented",
         oracle=("ur5e:arm.dynamics_excitation", "ur5e_2f85:arm.dynamics_excitation"),
         alternatives=("servo.dynamometer",),
         references=(refs.SWEVERS_1997, refs.GAUTIER_1990, refs.ATKESON_1986)),
    routine("arm.backlash_gravity_sweep", "UR joint backlash from a gravity-crossing sweep (motor-side signals only)", "servo_dynamic.arm",
         (I("servo", "M4", "backlash_rad"),), "both",
         Q(4 * SWEEP_S + 60, "s", f"gear_backlash ur/calibration.py SweepConfig: a +-25 deg sine at 3 deg/s, {SWEEP_S:.1f} s per joint, four "
                                  f"joints; 60 s of moves: {ESTIMATE}"),
         Q(0, "s", "the sweep needs no person or fixture (calibration.py)"), (),
         "a slow +-25 deg sine of each joint through its gravity balance, every other loaded joint held on one flank",
         "a pose per joint where gravity beats friction 2.5x at both ends (calibration_pose); never the pan or wrist 3", 1,
         "hold the arm where joint j's gravity torque crosses zero and sweep j's motor through it: away from the crossing the motor torque is "
         "the known gravity curve shifted by the flank's twist; Gauss-Newton on each flank's shift with an output-friction term, the datasheet "
         "mesh stiffness removed, three passes base to tip",
         code=(CodeHome(BAM_WS, f"{GEAR_BACKLASH}/ur/calibration.py", note="identify_arm"),), status="implemented",
         oracle=("ur5e_backlash:arm.backlash_gravity_sweep",),
         alternatives=("servo.backlash_reversals_camera", "servo.backlash_clamp", "arm.backlash_reversal_tracker"),
         references=(refs.NORDIN_2002,)),
    routine("arm.backlash_reversal_tracker", "UR joint backlash from reversal moves seen by a flange tracker", "servo_dynamic.arm",
         (I("servo", "M4", "backlash_rad"),), "bench",
         Q(2700, "s", ESTIMATE, "30 min of tracker set-up, then a few reversals per joint at two or three poses"),
         Q(1800, "s", ESTIMATE, "tracker set-up"), ("laser_tracker",),
         "small slow reversals of one joint at a time, the others held", "every joint, at poses whose load on it is small and of each sign", 3,
         "reverse one joint's motor slowly and read the flange: the motor travels the gap before the flange moves, mapped through the "
         "arm's Jacobian; the output-side analogue of CAN 11's camera reversals, and the one that reaches the pan and wrist 3",
         oracle_note="not implemented: nothing reverses a UR joint against a flange tracker yet; the ladder's ur5e_backlash scenario is where "
                     "it would be graded (the gravity sweep there reaches two of six joints)",
         alternatives=("arm.backlash_gravity_sweep", "servo.backlash_clamp", "servo.backlash_reversals_camera"),
         references=(refs.NORDIN_2002,)),
    routine("gripper.drive_traces", "Gripper drive gain and damping from finger traces", "servo_dynamic.arm",
         (I("arm_6dof_gripper", "M1", "finger_width_map"),), "bench",
         Q(12.0, "s", "sysid/results/ur5e_2f85.json schedule.gripper.train_s (width steps 0-255 and back)"), Q(0, "s", ESTIMATE), (),
         "width command steps over the whole range and back", "the command range in steps", 1,
         "least squares of the simulated finger drive angle on the measured one over the train command (the 2F-85's force per count and damping)",
         tests=("arm_6dof_gripper.open_close",),
         code=(CodeHome(SIM2REAL, "sysid/arm.py", note="fit_gripper"),), status="implemented", oracle=("ur5e_2f85:gripper.drive_traces",)),

    # --- the conveyor ----------------------------------------------------------------------------------------------------------------
    routine("conveyor.radius_tracker", "Drum radius from a belt tracker against the roller encoder", "servo_dynamic.actuator",
         (I("conveyor", "M0", "drum_radius_m"),), "both",
         Q(72 + 300, "s", f"72 s of speed profiles: sysid/results/conveyor.json schedule.train.seconds; 300 s set-up: {ESTIMATE}"),
         Q(300, "s", ESTIMATE, "a mark on the belt in the camera's view"), ("camera_tags",),
         "speed profiles: dwells at the description's levels, stops and a slow reverse", "the belt speed x acceleration grid (sysid's rule)", 1,
         "least squares of the tracker's belt travel on the encoder's roller angle, one offset per profile",
         tests=("conveyor.tag_metre",),
         code=(CodeHome(SIM2REAL, "sysid/examples/conveyor/pipeline.py"),), status="implemented", oracle=("conveyor:conveyor.radius_tracker",),
         alternatives=("conveyor_belt.scale",)),
    routine("conveyor.dynamics_profiles", "Belt mass and drag from speed profiles (output error on the description's MJCF)", "servo_dynamic.actuator",
         (I("conveyor", "M0", "moving_mass_kg"), I("conveyor", "M2", "coulomb_n", "viscous_n_s_m")), "both",
         Q(72 + 300, "s", f"the same 72 s of profiles (sysid/results/conveyor.json); 300 s set-up: {ESTIMATE}"), Q(300, "s", ESTIMATE), (),
         "the same speed profiles", "the belt speed x acceleration grid (sysid's rule)", 1,
         "drag from the steady droop of each dwell (linear), mass by golden section on the transients, then least squares of the simulated roller "
         "angle on the encoder's over the train profiles",
         tests=("conveyor.speed_steps", "conveyor.plateaus"),
         code=(CodeHome(SIM2REAL, "sysid/examples/conveyor/pipeline.py"),), status="implemented", oracle=("conveyor:conveyor.dynamics_profiles",)),

    # --- hand-eye --------------------------------------------------------------------------------------------------------------------
    routine("cell.tags_bundle_adjustment", "Hand-eye and camera from tags: one bundle adjustment of the mounts, the camera's pose and K", "hand_eye",
         (I("arm_6dof", "M0", "base_frame"), I("camera_rgb", "M0", "fx_fy", "cx_cy", "extrinsics")), "deployed",
         Q(600, "s", ESTIMATE, "60 arm poses and 10 belt travels"), Q(120, "s", ESTIMATE, "sticking the tags"), ("camera_tags",),
         "arm poses that show each gripper's tag to the camera, belt travels that bring the belt's tags under it",
         "the image's 8 x 6 cells x 3 depth bands (sysid's rule)", 1,
         "Levenberg-Marquardt on every tag corner's reprojection error over both mounts' corrections, the camera's pose and its K, from the "
         "drawing; 95 % from the Jacobian",
         tests=("camera_rgb.tag_poses",),
         code=(CodeHome(SIM2REAL, "sysid/examples/dual_arm_cell/pipeline.py"),
               CodeHome(BAM_WS, f"{TWIN}/calib.py", note="the rack's: camera and joints against the CAD by bundle adjustment over ArUco corners")),
         status="implemented", oracle=("dual_arm_cell:cell.tags_bundle_adjustment",),
         alternatives=("hand_eye.ax_xb", "camera.intrinsics_charuco"),
         references=(refs.ZHANG_2000, refs.HOLLERBACH_2016)),
    routine("hand_eye.ax_xb", "Hand-eye by AX = XB (Tsai-Lenz, Park-Martin, Daniilidis)", "hand_eye",
         (I("camera_rgb", "M0", "extrinsics"), I("arm_6dof", "M0", "base_frame")), "both",
         Q(600, "s", ESTIMATE), Q(120, "s", ESTIMATE), ("camera_tags",),
         "arm poses with large rotations between them (AX = XB needs non-parallel rotation axes)", "rotation axes spread over the sphere", 1,
         "solve AX = XB from pairs of robot and camera motions; OpenCV's calibrateHandEye is the stock solver",
         oracle_note="not implemented: bam_ws keeps a 2024 ROS node chaining ChArUco transforms (docs/ref) with no AX = XB solver; the sysid cell "
                     "solves its hand-eye inside one bundle adjustment instead",
         alternatives=("cell.tags_bundle_adjustment",),
         references=(refs.TSAI_1989, refs.PARK_1994, refs.DANIILIDIS_1999, refs.OPENCV_HANDEYE)),
    routine("camera.pose_recal_belt_tags", "Deployed camera pose recalibration from the belt's and the arms' tags", "hand_eye",
         (I("camera_rgb", "M0", "extrinsics"),), "deployed",
         Q(120, "s", ESTIMATE, "10 belt travels and the arms' held-out poses"), Q(0, "s", ESTIMATE, "at the alarm, unattended"), ("camera_tags",),
         "the belt carrying its printed tags past the camera, and the arms showing their gripper tags",
         "points at more than one depth: the belt's coplanar tags alone confuse a shift with a tilt", 1,
         "at the drift alarm, the camera's six pose numbers re-fitted from the commissioned values on the new tag views",
         tests=("camera_rgb.fixed_tag",),
         code=(CodeHome(SIM2REAL, "sysid/drift.py", note="run_camera"),), status="implemented", oracle=("dual_arm_cell:camera.pose_recal_belt_tags",)),

    # --- cameras ---------------------------------------------------------------------------------------------------------------------
    routine("camera.intrinsics_charuco", "Camera intrinsics and distortion from a ChArUco board (Zhang)", "camera.rgb",
         (I("camera_rgb", "M0", "fx_fy", "cx_cy"), I("camera_rgb", "M1", "distortion")), "bench",
         Q(600, "s", ESTIMATE), Q(600, "s", ESTIMATE, "showing the board at many angles"), ("charuco_board",),
         "a ChArUco board shown at many angles and distances over the whole image", "the image's cells and depths, tilted", 1,
         "Zhang's planar calibration: homographies per view, then K and distortion by bundle adjustment",
         tests=("camera_rgb.charuco",),
         code=(CodeHome(SIM2REAL, "src/sim2real/fit/camera_rgb.py", note="calibrate_planar: Zhang's closed form, then Levenberg-Marquardt "
                        "over K, distortion and every view's pose; held to OpenCV's calibrateCamera in tests/test_camera_types.py"),
               CodeHome(BAM_WS, "src/core/mdp/setup/bam_calibration/docs/ref/bam_calibration/dev/camera_calibration/camera_calibration_v2.py",
                        note="the older ChArUco intrinsics script, kept as reference"),),
         status="implemented",
         oracle_note="not in the sysid ladder (the cell's K comes from its tags' bundle adjustment); its hidden-truth test is "
                     "tests/test_camera_types.py: a hidden lens recovered, held-out reprojection within 1.5 x the corner jitter",
         alternatives=("cell.tags_bundle_adjustment",),
         references=(refs.ZHANG_2000, refs.HEIKKILA_1997)),
    routine("linescan.geometry_dot_card", "Line camera geometry from a dot card with a step", "camera.line_area_scan",
         (I("camera_hsi", "M3", "line_geometry"),), "both",
         Q(300, "s", ESTIMATE, "six passes of the card at different across offsets"), Q(300, "s", ESTIMATE), ("dot_card",),
         "the dot card ridden through the scan line at several across offsets", "the line's 16 pixel bins x 2 heights (sysid's rule)", 1,
         "Levenberg-Marquardt of the closed-form push broom (focal, principal point, height, across offset, line position, yaw) on the dots' "
         "(pixel, belt travel) crossings",
         tests=("camera_hsi.belt_target",),
         code=(CodeHome(SIM2REAL, "sysid/examples/linescan_cell/pipeline.py"),), status="implemented",
         oracle=("linescan_cell:linescan.geometry_dot_card",), references=(refs.GUPTA_1997,)),
    routine("linescan.radiometry_refs", "Line camera radiometry from white, grey and black references and dark frames", "camera.hsi",
         (I("camera_hsi", "M0", "dark_white_refs"),), "both",
         Q(120, "s", ESTIMATE), Q(120, "s", ESTIMATE, "placing the references"), ("reflectance_refs",),
         "white, grey and black references in the line, and dark frames", "the references' reflectances across the line", 1,
         "per band, linear least squares of DN on the reference reflectance: the gain and the dark level",
         tests=("camera_hsi.references",),
         code=(CodeHome(SIM2REAL, "sysid/examples/linescan_cell/pipeline.py"),), status="implemented",
         oracle=("linescan_cell:linescan.radiometry_refs",), references=(refs.BURGER_2011,)),
    routine("rgbd.dot_card", "Depth camera K, pose, depth scale and offset from a dot card on risers", "camera.rgbd",
         (I("camera_rgb", "M0", "fx_fy", "cx_cy", "extrinsics"), I("camera_rgbd", "M0", "depth_scale"), I("camera_rgbd", "M2", "depth_bias_coeffs")),
         "both",
         Q(300, "s", ESTIMATE, "12 frames, half of them on risers"), Q(300, "s", ESTIMATE), ("dot_card",),
         "the dot card on the belt and on risers under the camera", "two depths at least: a near-planar target cannot separate focal length, "
         "standoff and depth scale", 1,
         "Levenberg-Marquardt of the dots' pixels and depths together, depth weighted by intel_rgbd's stereo law",
         tests=("camera_rgbd.flat_target",),
         code=(CodeHome(SIM2REAL, "sysid/examples/linescan_cell/pipeline.py"),), status="implemented",
         oracle=("linescan_cell:rgbd.dot_card",), alternatives=("rgbd.self_calibration", "rgbd.flat_target_noise"),
         references=(refs.KHOSHELHAM_2012, refs.HERRERA_2012)),
    routine("rgbd.self_calibration", "Depth camera on-chip self-calibration (D400)", "camera.rgbd",
         (I("camera_rgbd", "M0", "depth_scale"), I("camera_rgbd", "M2", "depth_bias_coeffs")), "both",
         Q(120, "s", ESTIMATE, "placing a flat target and the routine itself"), Q(60, "s", ESTIMATE, "a flat textured target in view"), (),
         "a flat textured surface filling the view", "the whole depth image on one plane", 1,
         "the camera's own on-chip routine re-fits its stereo calibration from a flat textured scene",
         tests=("camera_rgbd.self_calibration",),
         oracle_note="not implemented: the D400's on-chip self-calibration is RobotDx's proposed depth.health_check; nothing calls it",
         alternatives=("rgbd.dot_card", "rgbd.flat_target_noise"), references=(refs.KHOSHELHAM_2012,)),

    # --- cameras: identify (2026-11-11, the camera types built out; Zach: "a rung of models ... and the routines for identifying them") ----
    routine("camera.exposure_response_ptc", "Exposure response, black level, gain and noise from a grey-card sweep (photon transfer)", "camera.rgb",
         (I("camera_rgb", "M2", "exposure_response"),), "both",
         Q(120, "s", ESTIMATE, "a dozen exposures x two gains, 10 frames each"), Q(30, "s", ESTIMATE, "a grey card in view"), ("grey_card",),
         "exposure and gain stepped from the noise floor to saturation on a static grey card", "the response from black to clipping", 10,
         "per setting, the mean and the frame-to-frame variance of the card's pixels; least squares of mean DN on exposure x gain (black level, "
         "response, saturation), and the photon transfer curve (variance on mean) for the system gain and read noise",
         tests=("camera_rgb.grey_card",),
         code=(CodeHome(SIM2REAL, "src/sim2real/fit/camera_rgb.py", note="fit_exposure_response (EMVA 1288 photon transfer)"),), status="implemented",
         oracle_note="no sysid example films this target; the hidden-truth test is tests/test_camera_types.py (recovery, then held-out fidelity within 1.5 x the camera's floor, and the nominal model failing it)"),
    routine("camera.latency_led", "Capture latency from an LED blinked on a stamped clock", "camera.rgb",
         (I("camera_rgb", "M2", "latency_s"),), "bench",
         Q(60, "s", ESTIMATE), Q(30, "s", ESTIMATE, "the LED in view"), ("led_blinker",),
         "an LED switched on and off at random intervals on the host's clock", "on and off edges across the exposure's phase", 30,
         "each edge's first lit frame against the switch time; the latency is the median offset, its spread the stamp jitter",
         tests=("camera_rgb.led_blink",),
         code=(CodeHome(SIM2REAL, "src/sim2real/fit/camera_rgb.py", note="fit_latency"),), status="implemented",
         oracle_note="no sysid example films this target; the hidden-truth test is tests/test_camera_types.py (recovery, then held-out fidelity within 1.5 x the camera's floor, and the nominal model failing it)"),
    routine("camera.rolling_shutter_target", "Rolling-shutter line delay from a target moving at known speed", "camera.rgb",
         (I("camera_rgb", "M3", "line_delay_s"),), "bench",
         Q(120, "s", ESTIMATE), Q(60, "s", ESTIMATE), ("camera_tags",),
         "a tag carried across the rows at a known, steady speed (the belt)", "the target across the image's rows", 10,
         "the tag's apparent shear: column offset per row over speed in px/s is the delay per row (Oth 2013's model, linear)",
         tests=("camera_rgb.moving_target",),
         code=(CodeHome(SIM2REAL, "src/sim2real/fit/camera_rgb.py", note="fit_line_delay"),), status="implemented",
         oracle_note="no sysid example films this target; the hidden-truth test is tests/test_camera_types.py (recovery, then held-out fidelity within 1.5 x the camera's floor, and the nominal model failing it)",
         references=(refs.OTH_2013,)),
    routine("rgbd.flat_target_noise", "Depth noise law and depth bias from a flat target at measured distances", "camera.rgbd",
         (I("camera_rgbd", "M1", "subpixel_sigma"), I("camera_rgbd", "M2", "depth_bias_coeffs")), "bench",
         Q(600, "s", ESTIMATE, "a flat target at 6-8 distances, 40 frames each"), Q(300, "s", ESTIMATE, "moving and measuring the target"),
         ("flat_target",),
         "a flat target stepped through the working range", "distances over the working range, the target filling the view", 40,
         "per distance, the plane's fitted depth against the measured one (bias, a polynomial in z) and the per-pixel std over frames; "
         "least squares of std on z^2 / (f b) for the sub-pixel disparity noise",
         tests=("camera_rgbd.flat_target",),
         code=(CodeHome(SIM2REAL, "src/sim2real/fit/camera_rgbd.py", note="fit_flat_target"),), status="implemented",
         oracle_note="no sysid example films this target; the hidden-truth test is tests/test_camera_types.py (recovery, then held-out fidelity within 1.5 x the camera's floor, and the nominal model failing it)",
         alternatives=("rgbd.dot_card", "rgbd.self_calibration"), references=(refs.KHOSHELHAM_2012, refs.HERRERA_2012)),
    routine("hsi.lamp_lines", "Band centres and widths from a spectral lamp's known lines", "camera.hsi",
         (I("camera_hsi", "M0", "band_centres"), I("camera_hsi", "M1", "band_fwhm")), "bench",
         Q(300, "s", ESTIMATE), Q(120, "s", ESTIMATE, "the lamp over the line"), ("spectral_lamp",),
         "a lamp with known emission lines filling the slit", "lines spread over the camera's wavelength range", 20,
         "a Gaussian fitted to each line on the spectral axis: its centre pixel and FWHM; a low-order polynomial maps pixel to wavelength",
         tests=("camera_hsi.lamp_lines",),
         code=(CodeHome(SIM2REAL, "src/sim2real/fit/camera_hsi.py", note="fit_lamp_lines"),), status="implemented",
         oracle_note="no sysid example films this target; the hidden-truth test is tests/test_camera_types.py (recovery, then held-out fidelity within 1.5 x the camera's floor, and the nominal model failing it)",
         references=(refs.BURGER_2011,)),
    routine("hsi.smile_keystone_bars", "Smile and keystone from lamp lines and an edge across the field", "camera.hsi",
         (I("camera_hsi", "M2", "smile_keystone_map"),), "bench",
         Q(300, "s", ESTIMATE), Q(120, "s", ESTIMATE), ("spectral_lamp", "bar_target"),
         "the lamp's lines across the whole slit (smile) and a sharp edge seen in every band (keystone)", "the full slit length and band range", 20,
         "smile: each line's centre against the spatial pixel (a quadratic); keystone: the edge's spatial position against the band (linear)",
         tests=("camera_hsi.bar_targets",),
         code=(CodeHome(SIM2REAL, "src/sim2real/fit/camera_hsi.py", note="fit_smile, fit_keystone"),), status="implemented",
         oracle_note="no sysid example films this target; the hidden-truth test is tests/test_camera_types.py (recovery, then held-out fidelity within 1.5 x the camera's floor, and the nominal model failing it)",
         references=(refs.MOUROULIS_2000,)),

    # --- cameras: configure (kind "configure": set up, not fit; Zach, 2026-11-11: "like homing ... automatically configuring it") ---------
    routine("camera.exposure_lock", "Lock exposure, gain and white balance under the deployment's lights", "camera.rgb", (), "both",
         Q(40, "s", "bam_camera_calibration evidence.json duration_s, the rack D435 at 1920x1080@15 on 2026-11-10 (35 probes)"),
         Q(0, "s", ESTIMATE, "unattended once the lights are on"), (),
         "the camera's own auto mode once as a reference, then manual exposure, gain and white balance written and read back",
         "the metering ROI's brightness from dark to clipping, white balance over its Kelvin range", 1,
         "auto exposure and white balance as a reference; then the largest exposure (native gain first) under the target brightness without new "
         "clipping, white balance zeroing the grey pixels' red/blue, a mains-flicker snap, and every write proved by the device's per-frame echo "
         "and steady brightness",
         kind="configure", configures=(C("camera_rgb", "exposure", "gain", "white_balance_k", "auto_exposure", "auto_white_balance"),
                                       C("camera_rgbd", "exposure", "gain", "white_balance_k", "auto_exposure", "auto_white_balance")),
         code=(CodeHome(BAM_WS, "src/core/mdp/setup/bam_camera_calibration/src/bam_camera_calibration/calibrate.py",
                        note="calibrate(): the search, lock and verify over the ExposureCamera protocol; RealSense adapter beside it"),),
         status="implemented",
         oracle_note="no sysid check: configuring recovers no hidden model value; its hidden-truth tests are bam_camera_calibration's twin tests "
                     "(white balance to 3 mired of a hidden light, the same picture under different light)",
         alternatives=("camera.exposure_for_task",)),
    routine("camera.exposure_for_task", "Exposure and gain chosen by the task: the shortest exposure that still reads the markers", "camera.rgb",
         (), "both",
         Q(60, "s", "bam_camera_calibration evidence.json, the rack D435 on 2026-11-10: 24 exposure x gain probes of 5 frames"),
         Q(0, "s", ESTIMATE, "unattended, the markers in view"), ("camera_tags",),
         "an exposure x gain grid: whole flicker periods up to the frame cap, gains up to a moderate cap", "the exposures from the cap down "
         "to a sixteenth of it", 5,
         "score the task (markers read per frame) at each setting and keep the shortest exposure within 90 % of the best score, then the least "
         "gain there: less motion blur for the same reads",
         kind="configure", configures=(C("camera_rgb", "exposure", "gain"), C("camera_rgbd", "exposure", "gain")),
         code=(CodeHome(BAM_WS, "src/core/mdp/setup/bam_camera_calibration/src/bam_camera_calibration/task.py",
                        note="aruco_score; the grid is calibrate(task_score=...)"),),
         status="implemented",
         oracle_note="no sysid check: the score is the task itself, run live; bam_camera_calibration's tests hold the grid's pick on a known camera",
         alternatives=("camera.exposure_lock",)),
    routine("rgbd.depth_emitter_settings", "Depth module set-up: IR exposure, laser power and emitter for the fill rate", "camera.rgbd", (), "both",
         Q(60, "s", ESTIMATE), Q(0, "s", ESTIMATE, "unattended, the work area in view"), (),
         "IR exposure and laser power stepped with the emitter on", "the work area's depth ROI over the settings", 1,
         "the lowest laser power and IR exposure whose depth fill rate and plane noise in the ROI meet the gates, written and read back "
         "(laser power before the emitter flag: writing it re-enables the emitter)",
         kind="configure", configures=(C("camera_rgbd", "depth_exposure_us", "depth_gain", "laser_power", "emitter_enabled"),),
         oracle_note="not implemented: intel_rgbd writes these settings, nothing searches them yet"),
    routine("hsi.integration_time", "Hyperspectral integration time and line rate against a white tile", "camera.hsi", (), "both",
         Q(60, "s", ESTIMATE), Q(30, "s", ESTIMATE, "a white tile in the line"), ("reflectance_refs",),
         "integration time stepped on the white tile at the belt's line rate", "every band of the white tile below saturation", 1,
         "the line rate from belt speed / along-track pixel size; then the longest integration that fits the line period and keeps the "
         "white tile's brightest band at or below 85 % of full scale, proved on a fresh capture",
         kind="configure", configures=(C("camera_hsi", "integration_time_s", "line_rate_hz", "gain"),),
         code=(CodeHome(SIM2REAL, "src/sim2real/schedule/camera_configure.py", note="configure_integration, line_rate_for"),),
         status="implemented",
         oracle_note="no sysid check: configuring recovers no hidden model value; tests/test_camera_types.py holds it to a line camera whose "
                     "white tile it is not told (on target without clipping; line-period limited in dim light)"),
    routine("camera.focus_lock", "Focus and aperture locked on a target at the working distance", "camera.line_area_scan", (), "bench",
         Q(300, "s", ESTIMATE), Q(300, "s", ESTIMATE, "turning the lens rings by hand"), ("bar_target",),
         "the focus ring turned through best focus on a bar target at the working distance", "the line's centre and both ends", 1,
         "the edge's sharpness (MTF50) read live while the ring turns; lock at the peak, the aperture where depth of field covers the belt's "
         "object heights",
         kind="configure", configures=(C("camera_hsi", "focus", "aperture"), C("camera_rgb", "focus", "aperture")),
         oracle_note="not implemented: a C-mount line or hyperspectral camera needs it; the RealSense is fixed focus"),

    # --- PID ----------------------------------------------------------------------------------------------------------------------
    routine("pid.pidtuna", "PID gains from the identified model, then measured tuning (pidtuna)", "pid", (), "bench",
         Q(1800, "s", ESTIMATE), Q(600, "s", ESTIMATE), (),
         "the identified model, then steps and sweeps on the joint", "the closed loop's band", 1,
         "pidtuna: an analytic start from the identified plant, a bandwidth search and its gates; it proposes gains, never writes a board",
         kind="use",
         code=(CodeHome(PIDTUNA, "src/pidtuna/tune.py"),), status="implemented",
         oracle_note="not in the sysid ladder: tuning chooses gains and recovers no hidden value; its grade is the closed loop's (pidtuna's gates)"),

    # --- the conveyor belt's geometry (2026-11-11, additive; sim2real.cards.conveyor_belt holds their tolerances) -----------------------
    # WHY no sysid oracle: their hidden-truth proof is sim2real.sim.conveyor_belt's MuJoCo twin (tests/test_conveyor_belt.py, 5 seeds),
    # not a sysid example; each oracle_note says so. Code homes are this repo's.
    routine("conveyor_belt.scale", "Belt distance scale: camera board travel vs motor encoder revs (and drum runout)", "servo_dynamic.actuator",
         (I("conveyor", "M0", "drum_radius_m"),), "both",
         Q(180, "s", ESTIMATE, "three 0.56 m passes, 40 stops each"), Q(120, "s", ESTIMATE, "laying the board under camera 1"), ("belt_charuco_acm",),
         "the belt stepped back and forth 0.56 m three times under camera 1", "two drum turns of belt travel, both directions", 3,
         "least squares of the board centre's travel (ChArUco pose per stop) on motor revs, with a once-per-drum-turn sine for runout; the "
         "effective drum radius is mm per rev x gear / 2 pi, belt thickness and wear included",
         tests=("conveyor.tag_metre",), code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="ScaleStep"),), status="implemented",
         oracle_note="no sysid example: the hidden-truth twin in sim2real.sim.conveyor_belt grades it (tests/test_conveyor_belt.py; 0.004 % worst of 5 seeds)",
         alternatives=("conveyor.radius_tracker",)),
    routine("conveyor_belt.slip", "Encoder-to-surface ratio under load (slip)", "servo_dynamic.actuator", (), "both",
         Q(240, "s", ESTIMATE), Q(180, "s", ESTIMATE, "loading the belt"), ("belt_charuco_acm", "belt_load"),
         "the scale routine's sweep with 15 kg on the belt", "one load against the unloaded scale", 3,
         "slip = 1 - loaded scale / unloaded scale; a gauge on the drum-to-surface ratio, not a rung parameter yet",
         kind="measure", code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="SlipStep"),), status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it (tests/test_conveyor_belt.py; 0.003 % worst of 5 seeds)"),
    routine("conveyor_belt.direction", "Belt direction in camera 1's frame, and its sideways wander", "hand_eye", (), "both",
         Q(1, "s", ESTIMATE, "computed from the scale routine's data"), Q(0, "s", ESTIMATE), ("belt_charuco_acm",),
         "the scale routine's sweep, no motion of its own", "the same two drum turns of travel", 3,
         "the fitted line's unit vector in camera 1's frame; its perpendicular scatter is the tracking wander",
         kind="measure", code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="DirectionStep"),), status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it (tests/test_conveyor_belt.py; 0.002 deg worst of 5 seeds)"),
    routine("conveyor_belt.plane_depth", "Belt plane from the depth camera (v1), and the background model", "camera.rgbd", (), "both",
         Q(10, "s", ESTIMATE, "30 depth frames"), Q(0, "s", ESTIMATE), (),
         "the empty belt held still under camera 1", "the belt's central band across the image", 30,
         "per-pixel mean and std of 30 depth frames (kept as the background model), a plane fit, into arm 1's frame through the hand-eye; "
         "camera-limited by the depth's range bias",
         kind="measure", code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="PlaneDepthStep"),), status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it (tests/test_conveyor_belt.py; 1.8 mm worst of 5 seeds)",
         alternatives=("conveyor_belt.plane_probe",)),
    routine("conveyor_belt.plane_probe", "Belt plane from arm 1's touch, Prusa-style (v2)", "hand_eye", (), "both",
         Q(120, "s", ESTIMATE, "16 touches"), Q(60, "s", ESTIMATE, "fitting the ball tip"), ("probe_ball_tip",),
         "a 4 x 4 grid of slow descents (5 mm/s) to 6 N or a 30 mm travel guard", "a 0.3 x 0.3 m grid over arm 1's reach", 1,
         "each contact is the zero-force intercept of tip height on the tared joint-current force; a least-squares plane through the 16; "
         "the only belt-plane route under 1 mm",
         kind="measure", code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="PlaneProbeStep"),), status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it with contact simulated (tests/test_conveyor_belt.py; 0.08 mm worst of 5 seeds)",
         alternatives=("conveyor_belt.plane_depth",)),
    routine("conveyor_belt.camera_to_camera", "Camera-to-camera transform, a board carried between them by the belt", "hand_eye",
         (I("camera_rgb", "M0", "extrinsics"),), "deployed",
         Q(120, "s", ESTIMATE, "three placements, 1.3 m carries"), Q(120, "s", ESTIMATE), ("belt_charuco_acm",),
         "the board seen by camera 1, carried whole drum turns, seen by camera 2", "three placements across the belt", 3,
         "camera 1's board pose carried by the calibrated scale and direction, composed with camera 2's; chordal mean over placements",
         tests=("camera_rgb.tag_poses",), code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="CameraToCameraStep"),),
         status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it (tests/test_conveyor_belt.py; 1.4 mm worst of 5 seeds)"),
    routine("conveyor_belt.robot_to_robot", "Arm-to-arm transform by touching a board the belt carries between them", "hand_eye",
         (I("arm_6dof", "M0", "base_frame"),), "deployed",
         Q(600, "s", ESTIMATE, "3 placements x 12 touches"), Q(600, "s", ESTIMATE, "jogging both arms to the divots"), ("divot_board",),
         "arm 1 touches the divots twice two drum turns apart, the belt carries them to arm 2, which touches", "three placements across the belt", 3,
         "the belt's vector in arm 1's frame from its two touches (ABB's 4-point conveyor calibration), then Kabsch over all 12 divot pairs",
         tests=("arm_6dof.tool_tag",), code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="RobotToRobotStep"),),
         status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it (tests/test_conveyor_belt.py; 0.84 mm worst of 5 seeds)"),
    routine("conveyor_belt.time_offset", "Camera-to-encoder time offset from the belt moving both ways", "hand_eye",
         (I("camera_rgb", "M2", "latency_s"),), "both",
         Q(30, "s", ESTIMATE, "6 s of streaming plus set-up"), Q(0, "s", ESTIMATE), ("belt_charuco_acm",),
         "the belt at +-0.1 and +-0.2 m/s while camera 1 streams at 30 fps", "two speeds in both directions", 1,
         "the shift of the encoder log that best explains the camera track at every speed; a sign flip separates latency from offset",
         tests=("camera_rgb.moving_target",), code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="TimeOffsetStep"),),
         status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it, motion blur not modelled (tests/test_conveyor_belt.py; 0.005 ms worst)"),
    routine("conveyor_belt.line_scan", "Line-scanner line on the belt, yaw, mm per pixel and trigger delay", "camera.line_area_scan",
         (I("camera_hsi", "M3", "line_geometry"),), "both",
         Q(120, "s", ESTIMATE, "two encoder-triggered passes"), Q(60, "s", ESTIMATE), ("belt_charuco_acm",),
         "the board measured by camera 1, carried under the line scanner at 0.1 and 0.4 m/s", "two speeds, the board across the swath", 1,
         "ChArUco in the encoder-stitched image; each corner's belt position places the scan line in camera 1's frame; the shift between "
         "the speeds is the trigger delay (Wendel and Underwood's pattern-through-the-line, on the belt's clock)",
         tests=("camera_hsi.belt_target",), code=(CodeHome(SIM2REAL, "src/sim2real/models/conveyor_belt.py", note="LineScanStep"),),
         status="implemented",
         oracle_note="no sysid example: the hidden-truth twin grades it (tests/test_conveyor_belt.py; 1.7 mm, 0.17 ms worst of 5 seeds)"),
    routine("conveyor_belt.speed_setup", "Belt drive set-up: counts per metre, direction sign and speed limits written to the drive",
         "servo_dynamic.actuator", (), "both",
         Q(60, "s", ESTIMATE), Q(30, "s", ESTIMATE, "confirming the drive's write"), (),
         "no motion: the scale and direction routines' results written to the drive", "the drive's speed and acceleration limits", 1,
         "write counts per metre from the scale routine, the sign that makes positive commands move downstream, and the guards the "
         "calibration runs under (0.2 m/s, 0.4 m/s for the line scan), then read them back",
         kind="configure", configures=(C("conveyor", "counts_per_m", "direction_sign", "speed_limit_m_s", "accel_limit_m_s2"),),
         oracle_note="not implemented: it needs the real belt's drive (its motor and driver are not known yet)"),
)
