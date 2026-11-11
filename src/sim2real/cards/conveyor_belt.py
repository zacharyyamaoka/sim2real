"""The conveyor belt's calibration card: which routines it has, what each identifies, the metrics it reports and the gate each must pass.

Data only (cards/ churns most; decision-package-layers-2026-11-10). The parameters themselves, with nominal values, ranges and sources,
live in sim2real.models.conveyor_belt (the description gives the nominals); this card holds the tolerances as robot_msgs Values whose
range is the rule, read by sim2real.metrics.gate.gate.

WHY a second module beside registry.CONVEYOR (2026-11-11, Zach's Daily Note "# Conveyor belt calibration"): the registry's conveyor card
is the belt as an ACTUATOR (drum radius, mass, drag; routines conveyor.radius_tracker / dynamics_profiles). This one is the belt as a
GEOMETRIC carrier: its scale, direction and plane in the robot's frame, and the transforms it carries a board between. Additive
(CONTRACT.md): a new module; no v1 / v2 name or field changed. A peer lane owns the camera types; this card names camera noise only as
what limits a routine, never as its own parameter.

Units: linear values in mm, angles in degrees, times in ms (Zach's report rule).
"""

from __future__ import annotations

from dataclasses import dataclass

from sim2real.metrics.gate import at_most

NOTE = "zach_brain Sources/Daily Notes/Daily Note - Nov 11 2026.md, # Conveyor belt calibration"
RESEARCH = "zach_brain Projects/BAM Robotics/Notes/Conveyor Belt Calibration — Prior Art and Ladder (2026-11-11).md"
PICK_GATE = "the arm's 5 mm tool gate (sim2real servo card, T4 allocation)"

# What bounds a routine's accuracy: the camera's pose noise and depth bias, the arm probe's contact detection, the arm's touch of a
# divot, or the motor encoder alone
LIMITS = ("camera", "contact", "touch", "encoder")


@dataclass(frozen=True)
class BeltRoutine:
    id: str
    title: str
    zach: str                      # his point in the brief, or "proposed" for an agent's addition
    identifies: tuple[str, ...]    # parameter names in sim2real.models.conveyor_belt.BeltDescription
    quantities: tuple[str, ...]    # keys into TOLERANCES; the twin scores each against its hidden truth
    limited_by: str                # one of LIMITS
    sub_mm: bool                   # does it reach Zach's < 1 mm on the belt plane / hand-off?
    equipment: tuple[str, ...]
    how: str
    operator_s: float              # hands-on time, an estimate
    wall_s: float                  # wall time on the real belt, an estimate
    note: str = ""


@dataclass(frozen=True)
class BeltMetric:
    id: str
    family: str                    # calibration (estimate vs hidden truth in sim) | fidelity (held-out prediction vs observation)
    title: str
    unit: str


BOARD = "an aluminium-composite ChArUco board, 7 x 5 squares of 40 mm, DICT_5X5_100 (C$32 printed on 3 mm ACM)"
DIVOT_BOARD = "the same board with four conical divots at its corners, for the arm's touch"

ROUTINES = (
    BeltRoutine("conveyor_belt.scale", "Belt distance scale: camera board travel vs motor encoder revs", "1",
                ("mm_per_motor_rev", "drum_runout_mm"), ("scale.mm_per_rev_pct", "scale.runout_mm"), "camera", False, (BOARD, "camera 1 (RGBD)"),
                "board flat on the belt; belt steps back and forth over 2 drum turns, 3 passes; ChArUco pose per stop; least squares of travel "
                "on revs with a once-per-drum-turn sine for runout", 120, 180,
                "lateral displacement is first-order immune to a focal-length error (PnP trades it into depth), so the scale is limited by pose "
                "noise and board flatness, not by intrinsics"),
    BeltRoutine("conveyor_belt.slip", "Encoder-to-surface ratio under load (slip)", "proposed",
                ("slip_pct_per_kg",), ("slip.slip_pct",), "camera", False, (BOARD, "a known load on the belt (sandbags)"),
                "the scale routine again with 15 kg on the belt; slip = 1 - loaded / unloaded scale", 300, 240),
    BeltRoutine("conveyor_belt.direction", "Belt direction in the camera frame", "2",
                ("belt_yaw_deg", "belt_pitch_deg"), ("direction.angle_deg",), "camera", False, (BOARD,),
                "the scale routine's data: the fitted line's unit vector in camera 1's frame; the perpendicular residual is the tracking wander",
                0, 0, "into the robot frame only through the camera's hand-eye; robot_to_robot measures it in the arm's own frame"),
    BeltRoutine("conveyor_belt.plane_depth", "Belt plane from the depth camera (v1), plus the background model", "3 v1",
                ("belt_height_mm", "belt_roll_deg", "belt_pitch_deg"), ("plane_depth.height_mm", "plane_depth.tilt_deg"), "camera", False,
                ("camera 1 (RGBD)",), "empty belt; 30 depth frames averaged per pixel (mean and std kept as the background model); plane fit; "
                "into the robot frame through the hand-eye", 0, 10,
                "camera-limited: the D435's depth bias (~0.4 % of range) and the hand-eye's error do not average out"),
    BeltRoutine("conveyor_belt.plane_probe", "Belt plane from the arm's touch, Prusa-style (v2)", "3 v2",
                ("belt_height_mm", "belt_roll_deg", "belt_pitch_deg"), ("plane_probe.height_mm", "plane_probe.tilt_deg"), "contact", True,
                ("arm 1 with a 6 mm ball tip",), "a 4 x 4 grid over the arm's reach; each point descends at 5 mm/s until the joint current "
                "(a load cell) rises 1 N over its tare, presses to 6 N, and the contact height is the zero-force intercept of force vs z; "
                "plane least squares", 60, 120,
                "WHY the intercept, not the threshold crossing: the crossing sits threshold / stiffness below the surface and moves with belt "
                "stiffness; the intercept does not"),
    BeltRoutine("conveyor_belt.camera_to_camera", "Camera-to-camera transform, the board carried by the belt", "4",
                ("camera_2_pose",), ("camera_to_camera.translation_mm", "camera_to_camera.rotation_deg"), "camera", False, (BOARD, "camera 2"),
                "board seen by camera 1, carried a whole number of drum turns by the calibrated scale and direction, seen by camera 2; "
                "T_c1_c2 = carry(T_c1_board) * inv(T_c2_board), averaged over 3 placements", 120, 120),
    BeltRoutine("conveyor_belt.robot_to_robot", "Arm-to-arm transform and belt direction in the arm's frame, by touching a carried board", "4",
                ("arm_2_pose", "belt_yaw_deg"), ("robot_to_robot.translation_mm", "robot_to_robot.rotation_deg", "robot_to_robot.direction_deg"),
                "touch", False, (DIVOT_BOARD, "arm 1", "arm 2"),
                "arm 1 touches the four divots, the belt moves 2 drum turns, arm 1 touches again (the belt's vector in arm 1's frame, ABB's "
                "4-point conveyor calibration), the belt carries the board to arm 2, which touches; Kabsch over 3 placements", 600, 600,
                "about 1 mm: the right order for the belt (Zach: not 0.1 mm, not 1 cm)"),
    BeltRoutine("conveyor_belt.time_offset", "Camera-to-encoder time offset (transport delay)", "proposed",
                ("camera_latency_ms",), ("time_offset.latency_ms",), "camera", False, (BOARD,),
                "belt at +-0.1 and +-0.2 m/s while camera 1 streams; latency = the shift of the encoder log that best explains the camera "
                "track at every speed (a sign flip separates it from a position offset)", 0, 30),
    BeltRoutine("conveyor_belt.line_scan", "Line-scanner registration and trigger timing on the belt", "5 + proposed",
                ("line_scan_pose", "line_trigger_delay_ms", "line_mm_per_px"),
                ("line_scan.offset_mm", "line_scan.yaw_deg", "line_scan.trigger_delay_ms", "line_scan.mm_per_px_pct"), "camera", False,
                (BOARD, "the line scanner, encoder-triggered every 0.5 mm"),
                "board seen by camera 1, carried under the line scanner at 0.1 and 0.4 m/s; ChArUco detected in the encoder-stitched "
                "image; each corner's belt position gives where the scan line lies on the belt (camera 1 frame), its yaw, its mm per pixel, "
                "and the trigger delay from the shift between the two speeds", 120, 60,
                "Wendel & Underwood 2017's pattern-through-the-line method, on the belt's own clock"),
)

# Every tolerance a robot_msgs Value whose range is the rule (sim2real.metrics.gate). WHY each number: the physics of the sensor that
# limits it, set before the routines existed (tests/test_conveyor_belt.py) and never loosened to pass.
_SRC = f"{NOTE}; set 2026-11-11 before the code"
TOLERANCES = {
    # 0.1 % = 1 mm per metre of travel, the order that keeps a 1.5 m hand-off inside the arm's 5 mm gate
    "scale.mm_per_rev_pct": at_most(0.1, "%", source=f"{_SRC}: 1 mm per m of travel"),
    "scale.runout_mm": at_most(0.08, "mm", source=f"{_SRC}: half a 0.15 mm drum eccentricity"),
    "slip.slip_pct": at_most(0.1, "%", source=f"{_SRC}: the scale's own tolerance"),
    "direction.angle_deg": at_most(0.1, "deg", source=f"{_SRC}: 2.6 mm across a 1.5 m hand-off"),
    # camera-limited: a D435 at 0.65 m has a few mm of depth bias that averaging cannot remove
    "plane_depth.height_mm": at_most(4.0, "mm", source=f"{_SRC}: D435 depth bias ~0.4 % at 0.65 m plus hand-eye"),
    "plane_depth.tilt_deg": at_most(0.5, "deg", source=f"{_SRC}: hand-eye rotation plus depth-scale gradient"),
    # Zach's < 1 mm target, with half of it left for the arm's own kinematic error
    "plane_probe.height_mm": at_most(0.5, "mm", source=f"{NOTE}: < 1 mm, half kept for the arm's own error"),
    "plane_probe.tilt_deg": at_most(0.05, "deg", source=f"{_SRC}: 0.35 mm across a 0.4 m belt"),
    "camera_to_camera.translation_mm": at_most(5.0, "mm", source=f"{_SRC}: direction 0.1 deg over 1.2 m plus PnP depth"),
    "camera_to_camera.rotation_deg": at_most(0.3, "deg", source=f"{_SRC}: two PnP rotations"),
    "robot_to_robot.translation_mm": at_most(2.0, "mm", source=f"{NOTE}: the belt's order, not 0.1 mm, not 1 cm"),
    "robot_to_robot.rotation_deg": at_most(0.15, "deg", source=f"{_SRC}: four divots 0.3 m apart touched to 0.3 mm"),
    "robot_to_robot.direction_deg": at_most(0.1, "deg", source=f"{_SRC}: the direction's own tolerance"),
    "time_offset.latency_ms": at_most(3.0, "ms", source=f"{_SRC}: 0.6 mm at 0.2 m/s"),
    "line_scan.offset_mm": at_most(2.0, "mm", source=f"{_SRC}: four lines at 0.5 mm"),
    "line_scan.yaw_deg": at_most(0.3, "deg", source=f"{_SRC}: one pixel across the swath"),
    "line_scan.trigger_delay_ms": at_most(2.0, "ms", source=f"{_SRC}: 0.5 mm at 0.25 m/s"),
    "line_scan.mm_per_px_pct": at_most(0.5, "%", source=f"{_SRC}: 2 mm across a 400 mm swath"),
}

# eval_twin: the calibrated belt predicts held-out hand-offs it was not fitted on
EVAL_TOLERANCES = {
    "camera_2_handoff_mm": at_most(6.0, "mm", source=f"{_SRC}: camera_to_camera's tolerance plus a held-out placement"),
    "arm_2_handoff_mm": at_most(2.5, "mm", source=f"{_SRC}: robot_to_robot's tolerance plus touch noise"),
    "probe_holdout_mm": at_most(0.5, "mm", source=f"{_SRC}: plane_probe's tolerance at points off the grid"),
}

GATES = {**{f"conveyor_belt.{k}": v for k, v in TOLERANCES.items()}, **{f"conveyor_belt.eval.{k}": v for k, v in EVAL_TOLERANCES.items()}}

_UNIT = {"pct": "%", "mm": "mm", "deg": "deg", "ms": "ms"}
METRICS = tuple(BeltMetric(f"conveyor_belt.{q}", "calibration", q.replace(".", ": ").replace("_", " "), _UNIT[q.rsplit("_", 1)[1]])
                for q in TOLERANCES) + tuple(
    BeltMetric(f"conveyor_belt.eval.{k}", "fidelity", k.replace("_", " "), "mm") for k in EVAL_TOLERANCES)

# Other calibrations a belt needs, proposed (Zach: "There may be other things we want to calibrate... you can let me know"), with where each
# lives: an existing routine, this card, or not yet built
PROPOSED = (
    ("speed tracking and ripple", "registry.CONVEYOR conveyor.dynamics_profiles + conveyor.speed_tracking; runout here", "exists"),
    ("start / stop dynamics (mass, drag, stretch)", "registry.CONVEYOR conveyor.dynamics_profiles", "exists"),
    ("slip under load (encoder-to-surface ratio)", "conveyor_belt.slip", "built here"),
    ("transport delay / camera-encoder time offset", "conveyor_belt.time_offset", "built here"),
    ("line-scanner trigger timing", "conveyor_belt.line_scan", "built here"),
    ("sideways tracking wander", "the direction routine's perpendicular residual (reported, not gated)", "built here"),
    ("belt length and splice (once-per-belt-loop ripple)", "the scale routine run over a full loop; a mark on the splice", "proposed"),
    ("thermal / wear drift of the scale", "re-run conveyor_belt.scale weekly; drift beyond tolerance flags recalibration", "proposed"),
)
