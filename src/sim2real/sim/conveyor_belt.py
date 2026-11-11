"""The conveyor belt's MuJoCo twin with a HIDDEN truth: the oracle every belt calibration routine is proven against.

    twin = BeltTwin(description, BeltTruth.default(), seed=0)   # description: sim2real.models.conveyor_belt.NOMINAL (duck-typed)
    ...routines drive it through the BeltRig verbs below...
    twin.score(calibration)                                     # {quantity: Score(estimate, truth, error, unit)}
    twin.close()

WHY a hidden truth (feedback_sim_ground_truth_first): a routine that recovers parameters it never saw, set apart from the nominal and
under noise, is the proof; a hardware pass without it proves nothing. The routines get only what the real rig gives: rendered images
(grey, with noise), depth with a range bias, encoder revs quantised to the motor's counts, the probe's joint height and a current-like
force with friction and noise, and the arms' touched points with noise. Nothing in this module is imported by the routines (sim/ sits
left of models/, which drives it through the verbs; the description comes in duck-typed for the same reason).

The scene: a 3 m belt deck (a static box at the TRUE pose), a ChArUco board as a mocap body the belt carries (the belt surface is
kinematic: travel(revs) is the truth's scale, slip and drum runout), two RGB-D cameras, a line scanner, and a three-axis probe standing
in for arm 1's tool (a contact-simulated Prusa-style touch). Arm 2's touch is the divot's position in its frame plus noise.

WHY kinematic belt travel and not geom/surfacevel (bam_pick_worlds/belt.py uses surfacevel for carrying blocks): calibration needs the
belt's position, not its friction on a block, and a mocap board makes the hidden scale, slip and runout exact by construction.

A peer lane builds the camera types (models/camera_rgbd.py); CameraNoise is the stand-in until it lands, kept to one dataclass so the
swap is one import.
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from sim2real.fit.belt_geometry import fit_plane, invert, rotation_angle_deg, rotation_zyx, scan_line_on_plane, vector_angle_deg
from sim2real.metrics.charuco import BOARD, CharucoSpec

__all__ = ["CameraNoise", "BeltTruth", "BeltTwin", "Score", "pose_matrix"]

MM, DEG = 1e-3, math.pi / 180


def pose_matrix(xyz_m, rpy_deg) -> np.ndarray:
    t = np.eye(4)
    t[:3, :3] = rotation_zyx(rpy_deg[2] * DEG, rpy_deg[1] * DEG, rpy_deg[0] * DEG)
    t[:3, 3] = xyz_m
    return t


def _perturb(t: np.ndarray, dxyz_mm, drpy_deg) -> np.ndarray:
    out = t.copy()
    out[:3, :3] = t[:3, :3] @ rotation_zyx(drpy_deg[2] * DEG, drpy_deg[1] * DEG, drpy_deg[0] * DEG)
    out[:3, 3] = t[:3, 3] + np.asarray(dxyz_mm) * MM
    return out


@dataclass(frozen=True)
class CameraNoise:
    """A D435-like colour + depth camera's errors. WHY these numbers: Intel's D435 datasheet (depth RMS < 2 % at 2 m; ~0.2 % at 1 m with
    a 50 mm baseline and 0.08 px subpixel), and a ChArUco intrinsic calibration good to ~0.3 % in focal length."""

    grey_sigma: float = 2.0             # image noise, grey levels
    depth_sigma_at_1m_m: float = 0.002  # per-pixel depth RMS, scales with range squared
    depth_scale_bias: float = 0.004     # systematic range error (does not average out)
    focal_error: float = 0.003          # the intrinsics the routines get vs the render's true focal length
    principal_error_px: float = 1.5


@dataclass(frozen=True)
class BeltTruth:
    """What the twin hides from the routines: every value set apart from the description's nominal."""

    scale_error: float = 0.021              # belt thickness on the drum: (r + t/2) / r - 1 for a 2 mm belt on a 50 mm drum, plus wear
    yaw_deg: float = 1.2
    pitch_deg: float = 0.35                 # along travel
    roll_deg: float = -0.6                  # across the belt
    height_offset_mm: float = 6.0
    lateral_offset_mm: float = 4.0
    runout_mm: float = 0.15                 # drum eccentricity: once-per-drum-turn surface position ripple
    runout_phase_rad: float = 0.7
    slip_per_kg: float = 0.0003             # 0.45 % at 15 kg
    camera_latency_s: float = 0.023
    camera_1_error: tuple = ((4.0, -3.0, 6.0), (0.4, -0.3, 0.6))     # (mm, deg) from its nominal mount
    camera_2_error: tuple = ((12.0, -8.0, 9.0), (0.5, 0.7, 1.0))
    hand_eye_residual: tuple = ((1.0, -0.6, 0.8), (0.12, -0.1, 0.08))  # what camera 1's hand-eye calibration leaves
    arm_2_error: tuple = ((3.0, -4.0, 1.5), (0.2, -0.15, 0.8))
    line_scan_error: tuple = ((7.0, 3.0, 10.0), (0.3, -0.2, 1.5))
    line_trigger_delay_s: float = 0.004
    touch_sigma_mm: float = 0.3
    probe_z_sigma_mm: float = 0.005
    probe_force_sigma_n: float = 0.2
    probe_friction_n: float = 0.4
    belt_stiffness_n_m: float = 5.0e4       # belt over its slider bed under the probe
    camera: CameraNoise = field(default_factory=CameraNoise)

    @classmethod
    def default(cls) -> "BeltTruth":
        return cls()

    def nominal(self) -> "BeltTruth":
        """A truth equal to the description (for a self-check: every error then reads zero)."""

        zero = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        return replace(self, scale_error=0.0, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0, height_offset_mm=0.0, lateral_offset_mm=0.0,
                       runout_mm=0.0, slip_per_kg=0.0, camera_latency_s=0.0, camera_1_error=zero, camera_2_error=zero, arm_2_error=zero,
                       line_scan_error=zero, line_trigger_delay_s=0.0)


@dataclass(frozen=True)
class Score:
    estimate: float
    truth: float
    error: float
    unit: str


CAMERA_SIZE = (1280, 720)
LINE_SIZE = (1024, 8)
OVERVIEW_SIZE = (960, 540)
DIVOTS_BOARD = np.array([[-0.125, -0.085], [0.125, -0.085], [0.125, 0.085], [-0.125, 0.085]])  # in the board body's frame, m


class BeltTwin:
    """The BeltRig verbs (see sim2real.models.conveyor_belt.BeltRig) on MuJoCo, plus score() against the hidden truth."""

    def __init__(self, description, truth: BeltTruth, seed: int = 0, board: CharucoSpec = BOARD, record: bool = False):
        import mujoco

        self._mj = mujoco
        self.d, self.truth, self.spec = description, truth, board
        self.rng = np.random.default_rng(seed)
        self.record = record
        self.frames: list[dict] = []          # the recorder: overview + sensor frames per routine, for the report's videos
        self.label = ""
        d = description
        self.nominal_m_per_rev = float(d.mm_per_motor_rev) * MM
        self.true_m_per_rev = self.nominal_m_per_rev * (1 + truth.scale_error)
        self.revs_per_drum_turn = float(d.gear_ratio)
        self.counts_per_rev = int(d.encoder_counts_per_rev)
        # the belt frame at its true pose, in arm 1's frame (= world)
        self.T_belt = pose_matrix(np.array([0.0, truth.lateral_offset_mm * MM, (float(d.belt_height_mm) + truth.height_offset_mm) * MM]),
                                  (float(d.belt_roll_deg) + truth.roll_deg, float(d.belt_pitch_deg) + truth.pitch_deg,
                                   float(d.belt_yaw_deg) + truth.yaw_deg))
        self.T_cam = {"camera_1": _perturb(d.pose("camera_1"), *truth.camera_1_error),
                      "camera_2": _perturb(d.pose("camera_2"), *truth.camera_2_error),
                      "line_scan": _perturb(d.pose("line_scan"), *truth.line_scan_error)}
        self.T_arm = {"arm_1": np.eye(4), "arm_2": _perturb(d.pose("arm_2"), *truth.arm_2_error)}
        self.revs = 0.0
        self.load_kg = 0.0
        self.board_s0 = 50.0   # off the belt until placed
        self.board_l = 0.0
        self.board_yaw = 0.0
        self.time_s = 0.0
        self._tmp = tempfile.TemporaryDirectory(prefix="conveyor_twin_")
        png = Path(self._tmp.name) / "board.png"
        import cv2

        cv2.imwrite(str(png), board.image())
        self.model = mujoco.MjModel.from_xml_string(self._xml(png))
        self.data = mujoco.MjData(self.model)
        self._renderers: dict = {}
        self.board_mocap = self.model.body_mocapid[mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "board")]
        self._act = {n: mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_ACTUATOR, n) for n in ("ax", "ay", "az")}
        self._jnt = {n: self.model.jnt_qposadr[mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, n)] for n in ("px", "py", "pz")}
        self.data.ctrl[self._act["az"]] = self.data.qpos[self._jnt["pz"]] = 0.0
        self._update_board()

    # ------------------------------------------------------------------------------------------------------------------------------
    # the scene

    def _cam_xml(self, name: str, t: np.ndarray, size) -> str:
        r_mj = t[:3, :3] @ np.diag([1.0, -1.0, -1.0])      # OpenCV (x right, y down, z forward) -> MuJoCo (y up, -z forward)
        q = np.empty(4)
        self._mj.mju_mat2Quat(q, r_mj.ravel())
        fovy = self._fovy(name, size)
        p = t[:3, 3]
        return f'<camera name="{name}" pos="{p[0]} {p[1]} {p[2]}" quat="{q[0]} {q[1]} {q[2]} {q[3]}" fovy="{fovy}"/>'

    def _fovy(self, name: str, size) -> float:
        w, h = size
        if name == "line_scan":
            fx = (w / 2) / math.tan(float(self.d.line_hfov_deg) * DEG / 2)
        else:
            return float(self.d.camera_vfov_deg)
        return 2 * math.degrees(math.atan((h / 2) / fx))

    def _xml(self, png: Path) -> str:
        t = self.truth
        q = np.empty(4)
        self._mj.mju_mat2Quat(q, self.T_belt[:3, :3].ravel())
        length, width = float(self.d.belt_length_mm) * MM, float(self.d.belt_width_mm) * MM
        centre = self.T_belt[:3, :3] @ np.array([length / 2 - 0.6, 0, -0.01]) + self.T_belt[:3, 3]
        w, h = self.spec.size_m
        th = self.spec.thickness_m
        divots = "".join(f'<site name="divot_{i}" pos="{x} {y} {th / 2}" size="0.004" rgba="1 .2 .2 1"/>' for i, (x, y) in enumerate(DIVOTS_BOARD))
        ov = (self._cam_xml("camera_1", self.T_cam["camera_1"], CAMERA_SIZE) + self._cam_xml("camera_2", self.T_cam["camera_2"], CAMERA_SIZE)
              + self._cam_xml("line_scan", self.T_cam["line_scan"], LINE_SIZE))
        # dummy sensor bodies so the overview shows where each sensor and arm sits (visual only)
        props = ""
        for name, tt in self.T_cam.items():
            p = tt[:3, 3]
            size = "0.02 0.25 0.015" if name == "line_scan" else "0.05 0.015 0.015"
            props += f'<geom type="box" pos="{p[0]} {p[1]} {p[2] + 0.02}" size="{size}" rgba=".2 .5 .9 1" contype="0" conaffinity="0" group="2"/>'
        p2 = self.T_arm["arm_2"][:3, 3]
        props += f'<geom type="cylinder" pos="{p2[0]} {p2[1] + 0.32} {p2[2] - 0.15}" size="0.06 0.15" rgba=".85 .55 .15 1" contype="0" conaffinity="0" group="2"/>'
        props += '<geom type="cylinder" pos="0 0.32 -0.15" size="0.06 0.15" rgba=".85 .55 .15 1" contype="0" conaffinity="0" group="2"/>'
        k = t.belt_stiffness_n_m
        return f"""
<mujoco model="conveyor_belt_twin">
  <option timestep="0.0005" gravity="0 0 -9.81"/>
  <visual><global offwidth="1280" offheight="720"/><headlight ambient=".5 .5 .5" diffuse=".55 .55 .55" specular="0 0 0"/>
    <quality shadowsize="0"/><map znear="0.01"/></visual>
  <asset>
    <texture name="board" type="2d" file="{png}"/>
    <material name="board" texture="board" specular="0" shininess="0"/>
    <texture name="belt" type="2d" builtin="checker" rgb1=".11 .11 .12" rgb2=".14 .14 .15" width="256" height="256"/>
    <material name="belt" texture="belt" texrepeat="60 8" specular="0" shininess="0"/>
  </asset>
  <worldbody>
    <light pos="0.9 0 1.6" dir="0 0 -1" diffuse=".35 .35 .35" specular="0 0 0"/>
    <geom name="belt" type="box" pos="{centre[0]} {centre[1]} {centre[2]}" quat="{q[0]} {q[1]} {q[2]} {q[3]}" size="{length / 2} {width / 2} 0.01"
          material="belt" solref="{-k} -300" solimp="0.95 0.95 0.001"/>
    <geom type="box" pos="{centre[0]} {centre[1] + width / 2 + 0.03} {centre[2] - 0.02}" size="{length / 2} 0.02 0.04" rgba=".55 .57 .6 1" contype="0" conaffinity="0" group="2"/>
    <geom type="box" pos="{centre[0]} {centre[1] - width / 2 - 0.03} {centre[2] - 0.02}" size="{length / 2} 0.02 0.04" rgba=".55 .57 .6 1" contype="0" conaffinity="0" group="2"/>
    {props}
    <body name="board" mocap="true" pos="0 0 -5">
      <geom type="box" size="{w / 2} {h / 2} {th / 2}" material="board" contype="0" conaffinity="0"/>
      {divots}
    </body>
    <body name="probe_x">
      <joint name="px" type="slide" axis="1 0 0" damping="80"/><inertial pos="0 0 0" mass="2" diaginertia=".01 .01 .01"/>
      <body name="probe_y">
        <joint name="py" type="slide" axis="0 1 0" damping="80"/><inertial pos="0 0 0" mass="1" diaginertia=".01 .01 .01"/>
        <body name="probe_z">
          <joint name="pz" type="slide" axis="0 0 1" damping="5"/><inertial pos="0 0 0" mass="0.5" diaginertia=".001 .001 .001"/>
          <geom name="tip" type="sphere" size="{float(self.d.probe_tip_radius_mm) * MM}" rgba=".95 .45 .1 1"/>
          <geom type="cylinder" pos="0 0 0.06" size="0.008 0.055" rgba=".8 .8 .82 1" contype="0" conaffinity="0"/>
        </body>
      </body>
    </body>
    {ov}
    <camera name="overview" pos="0.75 -1.75 0.75" xyaxes="1 0 0 0 0.55 0.835" fovy="45"/>
    <camera name="probe_view" pos="0.0 -0.45 -0.12" xyaxes="1 0 0 0 0.35 0.937" fovy="40"/>
  </worldbody>
  <actuator>
    <position name="ax" joint="px" kp="20000" kv="500"/>
    <position name="ay" joint="py" kp="20000" kv="400"/>
    <position name="az" joint="pz" kp="3000" kv="70"/>
  </actuator>
</mujoco>"""

    def close(self) -> None:
        for r in self._renderers.values():
            try:
                r.close()
            except Exception:
                pass
        self._renderers.clear()
        self._tmp.cleanup()

    # ------------------------------------------------------------------------------------------------------------------------------
    # the belt (truth)

    def travel_m(self, revs: float) -> float:
        t = self.truth
        phase = 2 * math.pi * revs / self.revs_per_drum_turn
        return (self.true_m_per_rev * (1 - t.slip_per_kg * self.load_kg) * revs
                + t.runout_mm * MM * (math.sin(phase + t.runout_phase_rad) - math.sin(t.runout_phase_rad)))

    def _station_s(self, near: str) -> float:
        """Where along the belt (belt frame, m) a station sits, from the description: the operator's 'put it under camera 1'."""

        p = self.d.pose(near)[:3, 3]
        return float(p[0])

    def _board_world(self, revs: float | None = None) -> np.ndarray:
        s = self.board_s0 + self.travel_m(self.revs if revs is None else revs)
        t = np.eye(4)
        t[:3, :3] = self.T_belt[:3, :3] @ rotation_zyx(self.board_yaw * DEG, 0, 0)
        t[:3, 3] = self.T_belt[:3, :3] @ np.array([s, self.board_l, self.spec.thickness_m / 2]) + self.T_belt[:3, 3]
        return t

    def _update_board(self, revs: float | None = None) -> None:
        t = self._board_world(revs)
        q = np.empty(4)
        self._mj.mju_mat2Quat(q, t[:3, :3].ravel())
        self.data.mocap_pos[self.board_mocap] = t[:3, 3]
        self.data.mocap_quat[self.board_mocap] = q
        self._mj.mj_forward(self.model, self.data)

    # ------------------------------------------------------------------------------------------------------------------------------
    # the BeltRig verbs

    def encoder_revs(self) -> float:
        return round(self.revs * self.counts_per_rev) / self.counts_per_rev

    def move_belt(self, delta_revs: float, speed_m_s: float = 0.1) -> None:
        steps = max(2, int(abs(delta_revs) * self.nominal_m_per_rev / max(speed_m_s, 1e-3) * 10))
        start = self.revs
        for i in range(1, steps + 1):
            self.revs = start + delta_revs * i / steps
            self.time_s += abs(delta_revs) * self.nominal_m_per_rev / speed_m_s / steps
            if self.record and i % 2 == 0:
                self._update_board()
                self._record()
        self._update_board()

    def set_load(self, kg: float) -> None:
        self.load_kg = float(kg)

    def place_board(self, near: str, along_m: float = 0.0, lateral_m: float = 0.0, yaw_deg: float = 90.0) -> None:
        jitter = self.rng.normal(0, 0.003, size=2)   # the operator's hand
        self.board_s0 = self._station_s(near) + along_m + jitter[0] - self.travel_m(self.revs)
        self.board_l = lateral_m + jitter[1]
        self.board_yaw = yaw_deg + self.rng.normal(0, 1.0)
        self._update_board()
        self._record()

    def clear_belt(self) -> None:
        self.board_s0 = 50.0
        self._update_board()

    def intrinsics(self, camera: str) -> np.ndarray:
        """The camera matrix a routine gets: its own calibration, off the render's true focal length by CameraNoise."""

        k = self._true_k(camera)
        c = self.truth.camera
        k[0, 0] *= 1 + c.focal_error
        k[1, 1] *= 1 + c.focal_error
        k[0, 2] += c.principal_error_px
        k[1, 2] -= c.principal_error_px
        return k

    def _true_k(self, camera: str) -> np.ndarray:
        w, h = LINE_SIZE if camera == "line_scan" else CAMERA_SIZE
        f = (h / 2) / math.tan(self._fovy(camera, (w, h)) * DEG / 2)
        return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])

    def hand_eye(self, camera: str) -> np.ndarray:
        """Camera 1's pose in arm 1's frame as its hand-eye calibration reports it (the truth plus that routine's residual)."""

        return _perturb(self.T_cam[camera], *self.truth.hand_eye_residual)

    def _renderer(self, size):
        if size not in self._renderers:
            self._renderers[size] = self._mj.Renderer(self.model, height=size[1], width=size[0])
        return self._renderers[size]

    def _render(self, camera: str, size, depth: bool = False) -> np.ndarray:
        r = self._renderer(size)
        if depth:
            r.enable_depth_rendering()
        else:
            r.disable_depth_rendering()
        r.update_scene(self.data, camera=camera)
        out = np.asarray(r.render()).copy()
        r.disable_depth_rendering()
        return out

    def _grey(self, rgb: np.ndarray) -> np.ndarray:
        g = rgb.astype(np.float32).mean(axis=2) + self.rng.normal(0, self.truth.camera.grey_sigma, size=rgb.shape[:2])
        return np.clip(g, 0, 255).astype(np.uint8)

    def capture(self, camera: str, depth: bool = False) -> dict:
        rgb = self._render(camera, CAMERA_SIZE)
        frame = {"grey": self._grey(rgb), "stamp": self.time_s + self.truth.camera_latency_s, "revs": self.encoder_revs()}
        if depth:
            z = self._render(camera, CAMERA_SIZE, depth=True).astype(np.float64)
            c = self.truth.camera
            z = z * (1 + c.depth_scale_bias) + self.rng.normal(0, 1, size=z.shape) * c.depth_sigma_at_1m_m * z ** 2
            frame["depth_m"] = z
        self._record(camera, rgb)
        return frame

    def stream(self, camera: str, profile, fps: float = 30.0) -> tuple[list[dict], np.ndarray, np.ndarray]:
        """Run the belt through (speed m/s, seconds) segments while the camera streams; frames are stamped LATE by the camera's latency.
        Returns the frames and the encoder log (host time s, revs) at 1 kHz."""

        t_log, revs_log, frames = [], [], []
        t0 = self.time_s
        next_frame = t0
        for speed, seconds in profile:
            rate = speed / self.nominal_m_per_rev        # the drive is commanded in motor units from the description
            for _ in range(int(round(seconds * 1000))):
                self.time_s += 1e-3
                self.revs += rate * 1e-3
                t_log.append(self.time_s)
                revs_log.append(self.encoder_revs())
                if self.time_s >= next_frame:
                    self._update_board()
                    rgb = self._render(camera, CAMERA_SIZE)
                    frames.append({"grey": self._grey(rgb), "stamp": self.time_s + self.truth.camera_latency_s})
                    if len(frames) % 3 == 0:
                        self._record(camera, rgb)
                    next_frame += 1 / fps
        self._update_board()
        return frames, np.array(t_log), np.array(revs_log)

    def line_scan(self, speed_m_s: float, line_pitch_revs: float, n_lines: int) -> tuple[np.ndarray, np.ndarray]:
        """An encoder-triggered push-broom scan: one line every line_pitch_revs; the sensor exposes line_trigger_delay later, by which
        time the belt has moved on. Returns the stitched image (lines x pixels) and each line's trigger revs."""

        rate = speed_m_s / self.nominal_m_per_rev
        rows, trig = [], []
        start = self.revs
        for k in range(n_lines):
            self.revs = start + k * line_pitch_revs
            trig.append(self.encoder_revs())
            self._update_board(self.revs + rate * self.truth.line_trigger_delay_s)
            img = self._render("line_scan", LINE_SIZE)
            rows.append(img[3:5].astype(np.float32).mean(axis=(0, 2)))
            if self.record and k % 12 == 0:
                self._record()
        self.time_s += n_lines * line_pitch_revs / rate
        self._update_board()
        image = np.array(rows) + self.rng.normal(0, self.truth.camera.grey_sigma, size=(n_lines, LINE_SIZE[0]))
        return np.clip(image, 0, 255).astype(np.uint8), np.array(trig)

    def touch(self, arm: str) -> np.ndarray:
        """The four divots as the arm's tool finds them, in the arm's frame (mm-level jog-and-touch; noise per axis)."""

        self._mj.mj_forward(self.model, self.data)
        out = []
        for i in range(len(DIVOTS_BOARD)):
            sid = self._mj.mj_name2id(self.model, self._mj.mjtObj.mjOBJ_SITE, f"divot_{i}")
            p = np.append(self.data.site_xpos[sid], 1.0)
            out.append((invert(self.T_arm[arm]) @ p)[:3] + self.rng.normal(0, self.truth.touch_sigma_mm * MM, size=3))
        self._record()
        return np.array(out)

    def probe(self, arm: str, x_m: float, y_m: float, start_z_m: float, speed_m_s: float = 0.005, stop_force_n: float = 6.0,
              max_travel_m: float = 0.03) -> dict:
        """Prusa-style touch: settle above (x, y), tare the force, descend at speed until the press force reaches stop_force_n or the
        travel guard trips; returns the joint height and the current-derived force (tared, with friction and noise) at 1 kHz."""

        if arm != "arm_1":
            raise ValueError("the twin's contact probe is arm 1's tool")
        mj, m, d = self._mj, self.model, self.data
        ax, ay, az = self._act["ax"], self._act["ay"], self._act["az"]
        d.ctrl[az] = start_z_m + 0.03
        for _ in range(400):
            mj.mj_step(m, d)
        d.ctrl[ax], d.ctrl[ay] = x_m, y_m
        for _ in range(1200):
            mj.mj_step(m, d)
        d.ctrl[az] = start_z_m
        for _ in range(1200):
            mj.mj_step(m, d)
        tare_samples = []
        for _ in range(200):
            mj.mj_step(m, d)
            tare_samples.append(d.actuator_force[az])
        tare = float(np.mean(tare_samples))
        zs, fs = [], []
        sub = int(round(1e-3 / m.opt.timestep))
        command = start_z_m
        tripped = "travel"
        i = 0
        while command > start_z_m - max_travel_m:
            command -= speed_m_s * m.opt.timestep
            d.ctrl[az] = command
            mj.mj_step(m, d)
            i += 1
            if i % sub:
                continue
            press = tare - d.actuator_force[az]
            moving = 1.0 if d.qvel[self._jnt["pz"]] < -1e-4 else 0.0
            force = press + self.truth.probe_friction_n * moving + self.rng.normal(0, self.truth.probe_force_sigma_n)
            zs.append(d.qpos[self._jnt["pz"]] + self.rng.normal(0, self.truth.probe_z_sigma_mm * MM))
            fs.append(force)
            if self.record and i % (sub * 40) == 0:
                self._record("probe_view")
            if force >= stop_force_n:
                tripped = "force"
                break
        d.ctrl[az] = start_z_m + 0.03
        for _ in range(600):
            mj.mj_step(m, d)
        self.time_s += i * m.opt.timestep + 1.8
        return {"z_m": np.array(zs), "force_n": np.array(fs), "stopped_by": tripped, "x_m": x_m, "y_m": y_m}

    # ------------------------------------------------------------------------------------------------------------------------------
    # the recorder (for the report's videos)

    def _record(self, sensor: str | None = None, sensor_rgb: np.ndarray | None = None) -> None:
        if not self.record:
            return
        frame = {"label": self.label, "overview": self._render("overview", OVERVIEW_SIZE)}
        if sensor == "probe_view":
            frame["sensor"] = self._render("probe_view", OVERVIEW_SIZE)
            frame["sensor_name"] = "probe close-up"
        elif sensor is not None:
            frame["sensor"] = sensor_rgb if sensor_rgb is not None else self._render(sensor, CAMERA_SIZE)
            frame["sensor_name"] = sensor
        self.frames.append(frame)

    # ------------------------------------------------------------------------------------------------------------------------------
    # the oracle: every estimate against the hidden truth

    def truths(self) -> dict:
        t = self.truth
        T_c1 = self.T_cam["camera_1"]
        plane_normal = self.T_belt[:3, 2]
        plane = fit_plane(np.array([self.T_belt[:3, :3] @ np.array([x, y, 0]) + self.T_belt[:3, 3]
                                    for x in (-0.3, 0.0, 0.3) for y in (-0.15, 0.0, 0.15)]))
        line = self._true_scan_line_c1()
        return {
            "m_per_rev": self.true_m_per_rev, "runout_m": t.runout_mm * MM, "slip": t.slip_per_kg * 15.0,
            "direction_c1": T_c1[:3, :3].T @ self.T_belt[:3, 0], "direction_a1": self.T_belt[:3, 0],
            "plane_world": plane, "plane_normal": plane_normal,
            "T_c1_c2": invert(T_c1) @ self.T_cam["camera_2"], "T_a1_a2": self.T_arm["arm_2"],
            "latency_s": t.camera_latency_s, "line_c1": line, "line_delay_s": t.line_trigger_delay_s,
        }

    def _true_scan_line_c1(self) -> dict:
        """Where the line scanner's centre row meets the true belt surface, in camera 1's TRUE frame, and its true mm per pixel."""

        to_c1 = invert(self.T_cam["camera_1"])
        a, b, m_per_px = scan_line_on_plane(self.T_cam["line_scan"], self._true_k("line_scan"), self.T_belt[:3, 3], self.T_belt[:3, 2])
        return {"a": (to_c1 @ np.append(a, 1))[:3], "b": (to_c1 @ np.append(b, 1))[:3], "m_per_px": m_per_px}

    def score(self, cal: dict) -> dict[str, Score]:
        tr = self.truths()
        out: dict[str, Score] = {}

        def put(key, est, truth, err, unit):
            out[key] = Score(float(est), float(truth), float(err), unit)

        s = cal["scale"]
        put("scale.mm_per_rev_pct", s["m_per_rev"] / MM, tr["m_per_rev"] / MM, (s["m_per_rev"] / tr["m_per_rev"] - 1) * 100, "%")
        put("scale.runout_mm", s["runout_m"] / MM, tr["runout_m"] / MM, (s["runout_m"] - tr["runout_m"]) / MM, "mm")
        put("slip.slip_pct", cal["slip"]["slip"] * 100, tr["slip"] * 100, (cal["slip"]["slip"] - tr["slip"]) * 100, "%")
        put("direction.angle_deg", 0, 0, vector_angle_deg(cal["direction"]["direction_c1"], tr["direction_c1"]), "deg")
        for key in ("plane_depth", "plane_probe"):
            plane = cal[key]["plane_world"]
            est_h, true_h = plane.height_at(0.0, 0.0), tr["plane_world"].height_at(0.0, 0.0)
            put(f"{key}.height_mm", est_h / MM, true_h / MM, (est_h - true_h) / MM, "mm")
            put(f"{key}.tilt_deg", plane.tilt_deg, tr["plane_world"].tilt_deg, vector_angle_deg(plane.normal, tr["plane_normal"]), "deg")
        T = cal["camera_to_camera"]["T_c1_c2"]
        put("camera_to_camera.translation_mm", np.linalg.norm(T[:3, 3]) / MM, np.linalg.norm(tr["T_c1_c2"][:3, 3]) / MM,
            np.linalg.norm(T[:3, 3] - tr["T_c1_c2"][:3, 3]) / MM, "mm")
        put("camera_to_camera.rotation_deg", 0, 0, rotation_angle_deg(T, tr["T_c1_c2"]), "deg")
        T = cal["robot_to_robot"]["T_a1_a2"]
        put("robot_to_robot.translation_mm", np.linalg.norm(T[:3, 3]) / MM, np.linalg.norm(tr["T_a1_a2"][:3, 3]) / MM,
            np.linalg.norm(T[:3, 3] - tr["T_a1_a2"][:3, 3]) / MM, "mm")
        put("robot_to_robot.rotation_deg", 0, 0, rotation_angle_deg(T, tr["T_a1_a2"]), "deg")
        put("robot_to_robot.direction_deg", 0, 0, vector_angle_deg(cal["robot_to_robot"]["direction_a1"], tr["direction_a1"]), "deg")
        put("time_offset.latency_ms", cal["time_offset"]["latency_s"] * 1e3, tr["latency_s"] * 1e3,
            (cal["time_offset"]["latency_s"] - tr["latency_s"]) * 1e3, "ms")
        ls, tl = cal["line_scan"], tr["line_c1"]
        # the line's along-belt offset: where each line crosses the plane through camera 1's optical axis that contains the belt normal,
        # measured along the TRUE belt direction (a frame both lines share)
        d_true = tr["direction_c1"]
        est_a, est_b = ls["a"], ls["b"]

        def crossing(a, b):
            e = np.cross(self._normal_c1(), d_true)
            sa, sb = float(e @ a), float(e @ b)
            return a + (b - a) * (sa / (sa - sb))

        along_err = float(d_true @ (crossing(est_a, est_b) - crossing(tl["a"], tl["b"])))
        put("line_scan.offset_mm", float(d_true @ crossing(est_a, est_b)) / MM, float(d_true @ crossing(tl["a"], tl["b"])) / MM, along_err / MM, "mm")
        put("line_scan.yaw_deg", 0, 0, _line_angle_deg(est_b - est_a, tl["b"] - tl["a"]), "deg")
        put("line_scan.trigger_delay_ms", ls["delay_s"] * 1e3, tr["line_delay_s"] * 1e3, (ls["delay_s"] - tr["line_delay_s"]) * 1e3, "ms")
        put("line_scan.mm_per_px_pct", ls["m_per_px"] / MM, tl["m_per_px"] / MM, (ls["m_per_px"] / tl["m_per_px"] - 1) * 100, "%")
        return out

    def _normal_c1(self) -> np.ndarray:
        return self.T_cam["camera_1"][:3, :3].T @ self.T_belt[:3, 2]


def _line_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    angle = vector_angle_deg(a, b)
    return min(angle, 180 - angle)
