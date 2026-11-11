"""The conveyor belt as a calibratable type: its description (every parameter a robot_msgs Value with nominal, range and source), the rig
verbs a routine needs, the calibration Steps, and the one-click front door.

    belt = ConveyorBelt(NOMINAL, rig)        # rig: BeltTwin (sim) or a real rig with the same verbs
    calibration = belt.calibrate()           # every Step in order; each is (description, rig, context) -> context
    held_out = belt.eval_twin(calibration)   # the calibrated belt predicts hand-offs it was not fitted on

    env -u VIRTUAL_ENV MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra sim --extra vision python /home/bam/sim2real/tools/conveyor_belt.py calibrate --rig sim

WHY this shape (zach_brain Projects/robot_msgs/Sim2Real Pipeline API — Prior Art (2026-11-11)): a description, a list of Steps, and
.calibrate() / .eval_twin() on top, so a step is one more entry in a list and drops down to a plain function. The routines see the rig only
through BeltRig, so the same Steps run on the MuJoCo twin (sim2real.sim.conveyor_belt) and, once its adapter exists, on the real belt.

WHY the nominal values come from a description object here and not from robot_description yet (docs/decision-types-seam-2026-11-11.md,
addendum: RobotDescription lives in robot_description below sim2real): that package has no conveyor; BeltDescription is the shape it
should take, with each value's source naming where the number comes from today.

Units: lengths in mm and angles in degrees in the description and every report; SI inside the fits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Protocol

import numpy as np
from robot_msgs.space import Value

from sim2real.fit.belt_geometry import (Plane, fit_belt_line, fit_plane, fit_time_offset, invert, kabsch, mean_transform, rotation_zyx,
                                        scan_line_on_plane)
from sim2real.fit.camera_rgb import Intrinsics
from sim2real.fit.charuco_pose import board_pose
from sim2real.metrics.camera import fidelity, jitter_floor, session_floor
from sim2real.metrics.charuco import BOARD, detect_corners

MM, DEG = 1e-3, math.pi / 180

PIDTUNA = "bam_ws bam_pid_tunning plants/conveyor_truths.py"
LAYOUT = "nominal cell layout (2026-11-11 agent default; replace with the real belt's robot description)"
D435 = "Intel RealSense D435 datasheet (colour 1280 x 720, 69 x 42 deg)"


def _v(raw: float, unit: str, low: float, high: float, source: str, notes: str = "") -> Value:
    return Value(raw, unit, low=low, high=high, source=source, notes=notes)


def _pose(xyz_mm, rpy_deg, source, lin=50.0, ang=5.0) -> tuple[Value, ...]:
    return tuple(_v(x, "mm", x - lin, x + lin, source) for x in xyz_mm) + tuple(_v(a, "deg", a - ang, a + ang, source) for a in rpy_deg)


@dataclass(frozen=True)
class BeltDescription:
    """The belt and the sensors and arms around it, at their NOMINAL values. Every field a robot_msgs Value (nominal, range, source).

    Frame: arm 1's base, x downstream along the belt, z up. A sensor pose is OpenCV's camera frame (x right, y down, z forward)."""

    drum_radius_mm: Value = _v(50.0, "mm", 20.0, 80.0, f"{PIDTUNA} DRUM_RADIUS_M")
    gear_ratio: Value = _v(10.0, "1", 1.0, 50.0, f"{PIDTUNA} GEAR")
    encoder_counts_per_rev: Value = _v(16384, "counts/rev", 1024, 1 << 20, f"{PIDTUNA} (2^14 counts)")
    belt_thickness_mm: Value = _v(2.0, "mm", 0.5, 8.0, "a PVC food belt's datasheet range; measure with calipers")
    # WHY 2 pi r / N and not 2 pi (r + t/2) / N: the description gives the bare drum; the belt's own thickness and wear are what the
    # scale routine is for
    mm_per_motor_rev: Value = _v(2 * math.pi * 50.0 / 10.0, "mm/rev", 25.0, 40.0, "2 pi drum_radius / gear_ratio")
    drum_runout_mm: Value = _v(0.0, "mm", 0.0, 0.5, "a turned drum's TIR (0 nominal)")
    slip_pct_per_kg: Value = _v(0.0, "%/kg", 0.0, 0.2, "no slip nominal")
    belt_width_mm: Value = _v(400.0, "mm", 200.0, 1200.0, LAYOUT)
    belt_length_mm: Value = _v(3000.0, "mm", 1000.0, 10000.0, LAYOUT)
    belt_height_mm: Value = _v(-300.0, "mm", -600.0, 0.0, f"{LAYOUT}: the arm mounted 300 mm above the belt")
    belt_yaw_deg: Value = _v(0.0, "deg", -5.0, 5.0, LAYOUT)
    belt_pitch_deg: Value = _v(0.0, "deg", -3.0, 3.0, LAYOUT)
    belt_roll_deg: Value = _v(0.0, "deg", -3.0, 3.0, LAYOUT)
    camera_vfov_deg: Value = _v(42.0, "deg", 30.0, 60.0, D435)
    camera_1_pose: tuple = _pose((0.0, 0.0, 350.0), (180.0, 0.0, 0.0), f"{LAYOUT}: camera 1 650 mm over the belt at arm 1")
    camera_2_pose: tuple = _pose((1200.0, 0.0, 350.0), (180.0, 0.0, 0.0), f"{LAYOUT}: camera 2 1.2 m downstream")
    arm_2_pose: tuple = _pose((1500.0, 0.0, 0.0), (0.0, 0.0, 180.0), f"{LAYOUT}: arm 2 1.5 m downstream, facing back")
    line_scan_pose: tuple = _pose((750.0, 0.0, 200.0), (180.0, 0.0, 90.0), f"{LAYOUT}: the line scanner 500 mm over the belt")
    line_hfov_deg: Value = _v(50.0, "deg", 20.0, 90.0, "a Specim FX17-class swath (assumed)")
    line_pixels: Value = _v(1024, "px", 256, 4096, "a Specim FX17-class line (assumed)")
    line_trigger_delay_ms: Value = _v(0.0, "ms", 0.0, 20.0, "0 nominal: the trigger's exposure delay is what line_scan measures")
    camera_latency_ms: Value = _v(0.0, "ms", 0.0, 150.0, "0 nominal: a USB camera's stamp is late by what time_offset measures")
    probe_tip_radius_mm: Value = _v(3.0, "mm", 0.5, 10.0, "a 6 mm ball tip on arm 1")

    def pose(self, name: str) -> np.ndarray:
        if name == "arm_1":
            return np.eye(4)
        v = [float(x) for x in getattr(self, f"{name}_pose")]
        t = np.eye(4)
        t[:3, :3] = rotation_zyx(v[5] * DEG, v[4] * DEG, v[3] * DEG)
        t[:3, 3] = np.array(v[:3]) * MM
        return t

    def parameters(self) -> dict[str, Value]:
        out: dict[str, Value] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, tuple):
                for axis, v in zip(("x_mm", "y_mm", "z_mm", "roll_deg", "pitch_deg", "yaw_deg"), value):
                    out[f"{f.name}.{axis}"] = v
            else:
                out[f.name] = value
        return out

    def belt_frame(self) -> np.ndarray:
        t = np.eye(4)
        t[:3, :3] = rotation_zyx(float(self.belt_yaw_deg) * DEG, float(self.belt_pitch_deg) * DEG, float(self.belt_roll_deg) * DEG)
        t[:3, 3] = (0.0, 0.0, float(self.belt_height_mm) * MM)
        return t

    def line_k(self) -> np.ndarray:
        w = float(self.line_pixels)
        f = (w / 2) / math.tan(float(self.line_hfov_deg) * DEG / 2)
        return np.array([[f, 0, w / 2], [0, f, 4.0], [0, 0, 1.0]])


NOMINAL = BeltDescription()


class BeltRig(Protocol):
    """What a routine may ask of the belt. The sim twin implements it; a real rig wraps the drive, the cameras and the arms."""

    def encoder_revs(self) -> float: ...
    def move_belt(self, delta_revs: float, speed_m_s: float = 0.1) -> None: ...
    def set_load(self, kg: float) -> None: ...                                   # real: the operator loads the belt, then confirms
    def place_board(self, near: str, along_m: float = 0.0, lateral_m: float = 0.0, yaw_deg: float = 90.0) -> None: ...
    def clear_belt(self) -> None: ...
    def intrinsics(self, camera: str) -> Intrinsics: ...
    def hand_eye(self, camera: str) -> np.ndarray: ...
    def capture(self, camera: str, depth: bool = False) -> dict: ...
    def stream(self, camera: str, profile, fps: float = 30.0): ...
    def line_scan(self, speed_m_s: float, line_pitch_revs: float, n_lines: int): ...
    def touch(self, arm: str) -> np.ndarray: ...
    # stop_force_n is press ABOVE the moving baseline (damping and friction read while descending); a real arm's adapter tares on the move,
    # not at rest, or a geared joint's friction alone could end the descent before contact (found 2026-11-11, see contact_height)
    def probe(self, arm: str, x_m: float, y_m: float, start_z_m: float, speed_m_s: float = 0.005, stop_force_n: float = 6.0,
              max_travel_m: float = 0.03) -> dict: ...


class CalibrationError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------------------------------------------
# helpers shared by the steps


def _station(d: BeltDescription, name: str) -> float:
    return float(d.pose(name)[0, 3])


def travel_m(ctx: dict, revs) -> np.ndarray:
    """Belt surface travel for encoder revs, by the calibrated scale and drum runout (the nominal scale before the scale step runs)."""

    s = ctx.get("scale")
    d = ctx["description"]
    revs = np.asarray(revs, float)
    if s is None:
        return revs * float(d.mm_per_motor_rev) * MM
    phase = 2 * np.pi * revs / float(d.gear_ratio)
    return s["m_per_rev"] * revs + s["runout_m"] * (np.sin(phase + s["runout_phase_rad"]) - math.sin(s["runout_phase_rad"]))


def _whole_turns(d: BeltDescription, distance_m: float) -> float:
    """Revs for a carry of about distance_m that is a whole number of drum turns. WHY: the drum's runout then cancels exactly."""

    per_turn = float(d.mm_per_motor_rev) * MM * float(d.gear_ratio)
    return max(1, round(distance_m / per_turn)) * float(d.gear_ratio)


def _pose_at(rig: BeltRig, camera: str, k: np.ndarray, n: int = 3) -> np.ndarray:
    poses = []
    for _ in range(n):
        p = board_pose(rig.capture(camera)["grey"], BOARD, k)
        if p is not None:
            poses.append(p.camera_from_board)
    if not poses:
        raise CalibrationError(f"no ChArUco board in {camera}'s view")
    return mean_transform(poses)


def _centre(t: np.ndarray) -> np.ndarray:
    return t[:3, :3] @ BOARD.centre_m + t[:3, 3]


def _sweep(rig: BeltRig, d: BeltDescription, span_m: float, stops: int, passes: int) -> tuple[np.ndarray, np.ndarray]:
    """Step the belt back and forth under camera 1, a ChArUco pose at every stop: (encoder revs, board centre in camera 1)."""

    k = rig.intrinsics("camera_1")
    step = span_m / stops / (float(d.mm_per_motor_rev) * MM)
    revs, centres = [], []
    for p in range(passes):
        sign = 1 if p % 2 == 0 else -1
        for i in range(stops + 1):
            pose = board_pose(rig.capture("camera_1")["grey"], BOARD, k)
            if pose is not None:
                revs.append(rig.encoder_revs())
                centres.append(pose.centre_m)
            if i < stops:
                rig.move_belt(sign * step)
    if len(revs) < stops:
        raise CalibrationError(f"the board was seen at only {len(revs)} stops")
    return np.array(revs), np.array(centres)


# ------------------------------------------------------------------------------------------------------------------------------------
# the steps: each (description, rig, context) -> context


class Step:
    name = "step"
    routine = ""

    def __call__(self, d: BeltDescription, rig: BeltRig, ctx: dict) -> dict:
        raise NotImplementedError


class ScaleStep(Step):
    """Zach's point 1: the board stepped back and forth under camera 1; camera travel vs motor revs gives mm per rev, plus drum runout."""

    name, routine = "scale", "conveyor_belt.scale"
    span_m, stops, passes = 0.56, 40, 3

    def __call__(self, d, rig, ctx):
        rig.set_load(0.0)
        rig.place_board("camera_1", along_m=-self.span_m / 2, yaw_deg=90.0)
        revs, centres = _sweep(rig, d, self.span_m, self.stops, self.passes)
        line = fit_belt_line(revs, centres, float(d.gear_ratio))
        ctx["scale"] = {"m_per_rev": line.m_per_rev, "runout_m": line.runout_m, "runout_phase_rad": line.runout_phase_rad,
                        "line": line, "revs": revs, "centres_c1": centres, "residual_mm": line.residual_rms_m / MM}
        return ctx


class DirectionStep(Step):
    """Zach's point 2: the same data's line, the belt direction in camera 1's frame; into arm 1's frame through the hand-eye."""

    name, routine = "direction", "conveyor_belt.direction"

    def __call__(self, d, rig, ctx):
        line = ctx["scale"]["line"]
        ctx["direction"] = {"direction_c1": line.direction, "direction_a1_via_hand_eye": rig.hand_eye("camera_1")[:3, :3] @ line.direction,
                            "wander_mm": line.wander_rms_m / MM}
        return ctx


class SlipStep(Step):
    """Proposed: the encoder-to-surface ratio under a known load (slip), the scale routine again with 15 kg on the belt."""

    name, routine = "slip", "conveyor_belt.slip"
    load_kg = 15.0

    def __call__(self, d, rig, ctx):
        rig.set_load(self.load_kg)
        try:
            rig.place_board("camera_1", along_m=-0.28, yaw_deg=90.0)
            revs, centres = _sweep(rig, d, 0.56, 40, 3)
        finally:
            rig.set_load(0.0)
        loaded = fit_belt_line(revs, centres, float(d.gear_ratio)).m_per_rev
        ctx["slip"] = {"load_kg": self.load_kg, "m_per_rev_loaded": loaded, "slip": 1 - loaded / ctx["scale"]["m_per_rev"]}
        return ctx


class PlaneDepthStep(Step):
    """Zach's point 3 v1: the empty belt averaged in camera 1's depth (also the background model), a plane, into arm 1's frame."""

    name, routine = "plane_depth", "conveyor_belt.plane_depth"
    frames = 30

    def __call__(self, d, rig, ctx):
        rig.clear_belt()
        stack = np.array([rig.capture("camera_1", depth=True)["depth_m"] for _ in range(self.frames)])
        mean, std = stack.mean(axis=0), stack.std(axis=0)
        k = rig.intrinsics("camera_1")
        h, w = mean.shape
        # the belt fills the middle of the image across; keep its central band, away from the side rails
        v, u = np.mgrid[int(h * 0.2):int(h * 0.8):4, int(w * 0.08):int(w * 0.92):4]
        z = mean[v, u]
        pts = np.column_stack([((u - k.cx) / k.fx * z).ravel(), ((v - k.cy) / k.fy * z).ravel(), z.ravel()])
        plane_c1 = fit_plane(pts[np.isfinite(pts).all(axis=1)])
        ctx["plane_depth"] = {"plane_c1": plane_c1, "plane_world": plane_c1.transformed(rig.hand_eye("camera_1")),
                              "background": {"mean_m": mean, "std_m": std}, "frames": self.frames}
        return ctx


def contact_height(trace: dict, low_n: float = 1.0, high_n: float = 5.5, baseline_s: float = 0.2) -> float:
    """The tip centre's height where the press force leaves its free-motion baseline: the intercept of z on force over the loaded tail.

    WHY the intercept and not the threshold crossing: the crossing sits threshold / stiffness below the surface and moves with how soft
    the belt is over its bed; the intercept does not (a load cell's tare-and-slope, as Prusa's MK4 load-cell probe does).
    WHY a moving baseline (found 2026-11-11, held-out points 0.44 mm off): a joint-current force reads the servo's damping and the joint's
    friction while the tip descends in free air (~0.75 N on the twin, more on a geared arm), so a fixed window counts samples from above
    the belt. The baseline is the first baseline_s of the descent (median, MAD noise); the fit keeps only the contiguous tail that stays
    above baseline + max(low_n, 6 noise), and the contact is where that line meets the baseline, not zero."""

    f, z = np.asarray(trace["force_n"], float), np.asarray(trace["z_m"], float)
    if trace["stopped_by"] != "force":
        raise CalibrationError(f"probe at ({trace['x_m']:.3f}, {trace['y_m']:.3f}) m found no belt within its travel guard")
    n_free = max(20, min(int(baseline_s * 1000), len(f) // 3))
    free = f[:n_free]
    baseline = float(np.median(free))
    noise = 1.4826 * float(np.median(np.abs(free - baseline)))
    low = baseline + max(low_n, 6 * noise)
    below = np.flatnonzero(f < low)
    start = int(below[-1]) + 1 if len(below) else 0
    sel = np.zeros(len(f), bool)
    sel[start:] = True
    sel &= f <= baseline + high_n
    if sel.sum() < 5:
        raise CalibrationError("too few loaded samples in a probe trace")
    slope, intercept = np.polyfit(f[sel], z[sel], 1)
    return float(intercept + slope * baseline)


class PlaneProbeStep(Step):
    """Zach's point 3 v2: arm 1 touches the belt at a 4 x 4 grid, the joint current as a load cell; a plane through the contacts."""

    name, routine = "plane_probe", "conveyor_belt.plane_probe"
    grid = 4
    half_span_m = (0.15, 0.15)

    def __call__(self, d, rig, ctx):
        rig.clear_belt()
        r_tip = float(d.probe_tip_radius_mm) * MM
        start = float(d.belt_height_mm) * MM + r_tip + 0.012
        points, traces = [], []
        for x in np.linspace(-self.half_span_m[0], self.half_span_m[0], self.grid):
            for y in np.linspace(-self.half_span_m[1], self.half_span_m[1], self.grid):
                trace = rig.probe("arm_1", float(x), float(y), start)
                traces.append(trace)
                points.append((x, y, contact_height(trace) - r_tip))
        plane = fit_plane(np.array(points), trim_sigma=10.0)
        ctx["plane_probe"] = {"plane_world": plane, "points_m": np.array(points), "traces": traces, "flatness_mm": plane.rms / MM}
        return ctx


class CameraToCameraStep(Step):
    """Zach's point 4: the board seen by camera 1, carried whole drum turns by the calibrated belt, seen by camera 2."""

    name, routine = "camera_to_camera", "conveyor_belt.camera_to_camera"
    placements = ((-0.04, 86.0), (0.0, 90.0), (0.04, 94.0))

    def __call__(self, d, rig, ctx):
        k1, k2 = rig.intrinsics("camera_1"), rig.intrinsics("camera_2")
        direction = ctx["direction"]["direction_c1"]
        carry = _whole_turns(d, _station(d, "camera_2") - _station(d, "camera_1"))
        estimates = []
        for lateral, yaw in self.placements:
            rig.place_board("camera_1", lateral_m=lateral, yaw_deg=yaw)
            r0 = rig.encoder_revs()
            t1 = _pose_at(rig, "camera_1", k1)
            rig.move_belt(carry, speed_m_s=0.2)
            r1 = rig.encoder_revs()
            t2 = _pose_at(rig, "camera_2", k2)
            carried = t1.copy()
            carried[:3, 3] += direction * float(travel_m(ctx, r1) - travel_m(ctx, r0))
            estimates.append(carried @ invert(t2))
        ctx["camera_to_camera"] = {"T_c1_c2": mean_transform(estimates), "each": estimates, "carry_revs": carry}
        return ctx


class RobotToRobotStep(Step):
    """Zach's point 4 for arms: arm 1 touches the divot board twice 2 drum turns apart (the belt's vector in its own frame, ABB's 4-point
    conveyor calibration), the belt carries it to arm 2, which touches; Kabsch over every divot of every placement."""

    name, routine = "robot_to_robot", "conveyor_belt.robot_to_robot"
    placements = (-0.06, 0.0, 0.06)

    def __call__(self, d, rig, ctx):
        first = 2 * float(d.gear_ratio)
        pairs_a1, pairs_a2, displacement = [], [], []
        records = []
        for lateral in self.placements:
            rig.place_board("arm_1", lateral_m=lateral, yaw_deg=90.0)
            r0 = rig.encoder_revs()
            p0 = rig.touch("arm_1")
            rig.move_belt(first)
            r1 = rig.encoder_revs()
            p1 = rig.touch("arm_1")
            displacement.append((p1 - p0).mean(axis=0) / float(travel_m(ctx, r1) - travel_m(ctx, r0)))
            rest = _whole_turns(d, _station(d, "arm_2") - _station(d, "arm_1") - float(travel_m(ctx, first)))
            rig.move_belt(rest, speed_m_s=0.2)
            r2 = rig.encoder_revs()
            q = rig.touch("arm_2")
            records.append((p1, q, float(travel_m(ctx, r2) - travel_m(ctx, r1))))
        v = np.mean(displacement, axis=0)
        direction = v / np.linalg.norm(v)
        for p1, q, carried in records:
            pairs_a1.append(p1 + direction * carried)
            pairs_a2.append(q)
        t = kabsch(np.vstack(pairs_a2), np.vstack(pairs_a1))
        residual = np.vstack(pairs_a1) - (np.vstack(pairs_a2) @ t[:3, :3].T + t[:3, 3])
        ctx["robot_to_robot"] = {"T_a1_a2": t, "direction_a1": direction, "touch_scale_ratio": float(np.linalg.norm(v)),
                                 "residual_mm": float(np.sqrt(np.mean(np.sum(residual ** 2, axis=1)))) / MM}
        return ctx


class TimeOffsetStep(Step):
    """Proposed: camera 1's stamp vs the encoder clock. The belt runs both ways at two speeds while camera 1 streams; the latency is the
    shift of the encoder log that best explains the camera track (one speed alone cannot tell a latency from a position offset)."""

    name, routine = "time_offset", "conveyor_belt.time_offset"
    profile = ((0.1, 2.0), (-0.1, 2.0), (0.2, 1.0), (-0.2, 1.0))

    def __call__(self, d, rig, ctx):
        rig.place_board("camera_1", along_m=-0.10, yaw_deg=90.0)
        frames, t_log, revs_log = rig.stream("camera_1", self.profile, fps=30.0)
        k, direction = rig.intrinsics("camera_1"), ctx["direction"]["direction_c1"]
        stamps, along = [], []
        for f in frames:
            pose = board_pose(f["grey"], BOARD, k)
            if pose is not None:
                stamps.append(f["stamp"])
                along.append(float(pose.centre_m @ direction))
        latency = fit_time_offset(np.array(stamps), np.array(along), t_log, travel_m(ctx, revs_log), search_s=(-0.15, 0.15))
        ctx["time_offset"] = {"latency_s": latency, "frames": len(stamps), "stamps_s": np.array(stamps), "along_m": np.array(along),
                              "t_log_s": t_log, "travel_log_m": travel_m(ctx, revs_log)}
        return ctx


def _stitched_corners(image: np.ndarray):
    """ChArUco corners in an encoder-stitched line-scan image. WHY the flips: which way the lines stack depends on the belt's direction
    and the sensor's mounting, and a mirrored marker does not decode; the flip that decodes is the right one."""

    best = None
    for flip_rows in (False, True):
        for flip_cols in (False, True):
            img = image[::-1 if flip_rows else 1, ::-1 if flip_cols else 1]
            found = detect_corners(np.ascontiguousarray(img), BOARD)
            if found is not None and (best is None or len(found[0]) > len(best[0])):
                ids, px = found
                px = px.copy()
                if flip_rows:
                    px[:, 1] = image.shape[0] - 1 - px[:, 1]
                if flip_cols:
                    px[:, 0] = image.shape[1] - 1 - px[:, 0]
                best = (ids, px)
    return best


class LineScanStep(Step):
    """Zach's point 5 + proposed trigger timing: the board measured by camera 1, carried under the line scanner at two speeds; each
    stitched-image corner's belt position says where the scan line lies on the belt (camera 1's frame), its yaw and mm per pixel; the
    shift between the speeds is the trigger delay (Wendel & Underwood 2017, on the belt's own clock)."""

    name, routine = "line_scan", "conveyor_belt.line_scan"
    speeds = (0.1, 0.4)
    pitch_m = 0.0005

    def __call__(self, d, rig, ctx):
        k1, direction = rig.intrinsics("camera_1"), ctx["direction"]["direction_c1"]
        m_per_rev = ctx["scale"]["m_per_rev"]
        fits, all_s, all_u, normals, scans = [], [], [], [], []
        for speed in self.speeds:
            rig.place_board("camera_1", yaw_deg=90.0)
            r0 = rig.encoder_revs()
            t0 = _pose_at(rig, "camera_1", k1)
            normals.append(t0[:3, 2])
            rig.move_belt((_station(d, "line_scan") - _station(d, "camera_1") - 0.16) / m_per_rev, speed_m_s=0.2)
            image, trig = rig.line_scan(speed, self.pitch_m / m_per_rev, int(0.34 / self.pitch_m))
            found = _stitched_corners(image)
            if found is None or len(found[0]) < 8:
                raise CalibrationError(f"the line scan at {speed} m/s decoded {0 if found is None else len(found[0])} ChArUco corners")
            ids, px = found
            revs = np.interp(px[:, 1], np.arange(len(trig)), trig)
            board_pts = BOARD.object_points(ids)
            x = (t0[:3, :3] @ board_pts.T).T + t0[:3, 3] + np.outer(travel_m(ctx, revs) - travel_m(ctx, r0), direction)
            fits.append((speed, x, px[:, 0]))
            scans.append({"speed_m_s": speed, "image": image, "corners_px": px, "ids": ids})
        n = np.mean(normals, axis=0)
        n /= np.linalg.norm(n)
        e = np.cross(n, direction)
        e /= np.linalg.norm(e)
        offsets, slopes, heights = [], [], []
        for speed, x, u in fits:
            along, cross = x @ direction, x @ e
            b, a = np.polyfit(cross, along, 1)
            offsets.append(a)
            slopes.append(b)
            heights.append(float(np.mean(x @ n)))
            all_s.append(cross * math.sqrt(1 + b * b))
            all_u.append(u)
        (v1, v2), (a1, a2) = self.speeds, offsets
        delay = (a1 - a2) / (v2 - v1)            # the scanner exposes late, so it reads the board v * delay upstream of the line
        a_true = a1 + v1 * delay
        b, h = float(np.mean(slopes)), float(np.mean(heights))
        ends = [(a_true + b * c) * direction + c * e + h * n for c in (-0.13, 0.13)]
        px_per_m = np.polyfit(np.concatenate(all_s), np.concatenate(all_u), 1)[0]
        # WHY the thickness factor: the corners lie on the board's top face, 3 mm nearer the scanner than the belt it images
        range_m = float(d.pose("line_scan")[2, 3] - d.belt_height_mm * MM)
        m_per_px = abs(1 / px_per_m) * (1 + BOARD.thickness_m / range_m)
        ctx["line_scan"] = {"a": ends[0], "b": ends[1], "delay_s": delay, "m_per_px": m_per_px, "yaw_rad": math.atan(b),
                            "offsets_m": offsets, "corners": [len(f[2]) for f in fits], "scans": scans}
        return ctx


STEPS = (ScaleStep(), DirectionStep(), SlipStep(), PlaneDepthStep(), PlaneProbeStep(), CameraToCameraStep(), RobotToRobotStep(),
         TimeOffsetStep(), LineScanStep())


class ConveyorBelt:
    """The front door: a description and a rig; .calibrate() runs the Steps, .eval_twin() checks the result on held-out hand-offs."""

    def __init__(self, description: BeltDescription, rig: BeltRig):
        self.d, self.rig = description, rig

    def calibrate(self, steps=STEPS, only: tuple[str, ...] | None = None) -> dict:
        ctx: dict = {"description": self.d}
        for step in steps:
            if only and step.name not in only:
                continue
            if hasattr(self.rig, "label"):
                self.rig.label = step.name
            ctx = step(self.d, self.rig, ctx)
        return ctx

    def nominal_calibration(self) -> dict:
        """What the description alone says, in the calibration's own shape: the baseline every routine must beat."""

        d = self.d
        belt = d.belt_frame()
        c1 = d.pose("camera_1")
        plane = Plane(belt[:3, 2], float(belt[:3, 2] @ belt[:3, 3]), 0.0, 0)
        a, b, m_per_px = scan_line_on_plane(d.pose("line_scan"), d.line_k(), belt[:3, 3], belt[:3, 2])
        to_c1 = invert(c1)
        return {"description": d,
                "scale": {"m_per_rev": float(d.mm_per_motor_rev) * MM, "runout_m": 0.0, "runout_phase_rad": 0.0},
                "slip": {"slip": 0.0}, "direction": {"direction_c1": c1[:3, :3].T @ belt[:3, 0]},
                "plane_depth": {"plane_world": plane}, "plane_probe": {"plane_world": plane},
                "camera_to_camera": {"T_c1_c2": invert(c1) @ d.pose("camera_2")},
                "robot_to_robot": {"T_a1_a2": d.pose("arm_2"), "direction_a1": belt[:3, 0]},
                "time_offset": {"latency_s": float(d.camera_latency_ms) * 1e-3},
                "line_scan": {"a": (to_c1 @ np.append(a, 1))[:3], "b": (to_c1 @ np.append(b, 1))[:3],
                              "delay_s": float(d.line_trigger_delay_ms) * 1e-3, "m_per_px": m_per_px}}

    def eval_twin(self, cal: dict) -> dict:
        """Held-out: new placements the fits never saw. Camera 2 and arm 2 predicted from camera 1 / arm 1 through the calibrated belt,
        and the belt plane predicted at probe points off the calibration grid."""

        d, rig = self.d, self.rig
        if hasattr(rig, "label"):
            rig.label = "eval_twin"
        out = {}
        k1, k2 = rig.intrinsics("camera_1"), rig.intrinsics("camera_2")
        rig.place_board("camera_1", along_m=0.05, lateral_m=0.03, yaw_deg=80.0)
        r0, t1 = rig.encoder_revs(), _pose_at(rig, "camera_1", k1)
        rig.move_belt(_whole_turns(d, _station(d, "camera_2") - _station(d, "camera_1")), speed_m_s=0.2)
        r1, t2 = rig.encoder_revs(), _pose_at(rig, "camera_2", k2)
        carried = _centre(t1) + cal["direction"]["direction_c1"] * float(travel_m(cal, r1) - travel_m(cal, r0))
        predicted = (invert(cal["camera_to_camera"]["T_c1_c2"]) @ np.append(carried, 1))[:3]
        out["camera_2_handoff_mm"] = float(np.linalg.norm(predicted - _centre(t2))) / MM
        # the same hand-off as a camera-types Fidelity: the error over camera 2's own floor for this statistic (its board-centre jitter
        # over repeated frames, as a session floor: 3 calibration placements, 5 held-out frames); reported, not gated
        repeats = []
        for _ in range(5):
            p2 = board_pose(rig.capture("camera_2")["grey"], BOARD, k2)
            if p2 is not None:
                repeats.append(p2.centre_m)
        if len(repeats) >= 2:
            sigma_3d = jitter_floor(np.array(repeats)[:, None, :]) * math.sqrt(3)
            out["camera_2_handoff_fidelity"] = fidelity("conveyor_belt.eval.camera_2_handoff", out["camera_2_handoff_mm"] * MM,
                                                        session_floor(sigma_3d, 3, len(repeats)), "m", len(repeats))
        rig.place_board("arm_1", lateral_m=0.04, yaw_deg=92.0)
        r0, p = rig.encoder_revs(), rig.touch("arm_1")
        rig.move_belt(_whole_turns(d, _station(d, "arm_2") - _station(d, "arm_1")), speed_m_s=0.2)
        r1, q = rig.encoder_revs(), rig.touch("arm_2")
        rr = cal["robot_to_robot"]
        pred_a1 = p + rr["direction_a1"] * float(travel_m(cal, r1) - travel_m(cal, r0))
        pred_a2 = (invert(rr["T_a1_a2"]) @ np.column_stack([pred_a1, np.ones(len(pred_a1))]).T).T[:, :3]
        out["arm_2_handoff_mm"] = float(np.sqrt(np.mean(np.sum((pred_a2 - q) ** 2, axis=1)))) / MM
        rig.clear_belt()
        r_tip = float(d.probe_tip_radius_mm) * MM
        start = float(d.belt_height_mm) * MM + r_tip + 0.012
        plane = cal["plane_probe"]["plane_world"]
        worst = 0.0
        for x, y in ((0.07, 0.11), (-0.11, 0.07), (-0.07, -0.11), (0.11, -0.07)):
            z = contact_height(rig.probe("arm_1", x, y, start)) - r_tip
            worst = max(worst, abs(z - plane.height_at(x, y)))
        out["probe_holdout_mm"] = worst / MM
        return out
