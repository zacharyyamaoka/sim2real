"""Zach's calibration packages (PROJECT - Sim2Real, Nov 5 2026): "all of these calibration things are ultimately very related ...
but we can focus as separate packages ... Each of these basically can be looked at separately and require their own algorithms".

One entry per package: the type cards it serves and where its code lives today. Every CodeHome path was found by reading the
repos on 2026-11-05 and is checked to exist at its ref by tests/test_ladders.py; `unknown` means nobody found code, never a guess.
"""

from __future__ import annotations

from . import references as refs
from .schema import CalibrationPackage, CodeHome

BAM_WS = "/home/bam/bam_ws"
IO_DX = "/home/bam/io-diagnostics"
ROBOTPARTS = "/home/bam/robotparts"
PIDTUNA = "/home/bam/pidtuna"
TWIN = "src/dev/bam_rack_twin/bam_rack_twin"
KINCAL_BRANCH = "claude/kinematic-calibration-multi-arm-4645cc"
PID_BRANCH = "claude/pid-auto-tuner-stack-e956da"

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
