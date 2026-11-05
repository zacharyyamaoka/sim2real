"""Cameras for the two cell examples: the stock pinhole (bam_scan_tunnel's PinholeCamera), pose corrections, bundle adjustment.

The "real" pixels come from bam_scan_tunnel.camera_geometry.PinholeCamera (the scan tunnel's and bam_grasp's camera math: CV frame,
the +0.5 pixel-centre convention, a MuJoCo camera's pose through diag(1, -1, -1)) at the HIDDEN intrinsics and pose. The fit uses
`project`, a vectorised copy of the same equations; `check_against_stock` holds the two to 1e-9 px on every call site's points.

A pose correction is a world-frame translation d and rotation vector r applied to the drawn pose: R = exp([r]) R_drawn,
t = t_drawn + d (sysid's descriptions state it in their known block).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

POSE_NAMES = ("dx_m", "dy_m", "dz_m", "rx_rad", "ry_rad", "rz_rad")
K_NAMES = ("fx_px", "fy_px", "cx_px", "cy_px")
CV_FLIP = np.diag([1.0, -1.0, -1.0])


def rotation(rotvec) -> np.ndarray:
    from scipy.spatial.transform import Rotation  # noqa: PLC0415

    return Rotation.from_rotvec(np.asarray(rotvec, float)).as_matrix()


def rotvec_of(R) -> np.ndarray:
    from scipy.spatial.transform import Rotation  # noqa: PLC0415

    return Rotation.from_matrix(np.asarray(R, float)).as_rotvec()


def corrected(R: np.ndarray, t: np.ndarray, d, r) -> tuple[np.ndarray, np.ndarray]:
    return rotation(r) @ R, np.asarray(t, float) + np.asarray(d, float)


def correction_of(values: dict, prefix: str) -> tuple[np.ndarray, np.ndarray]:
    d = np.array([float(values.get(f"{prefix}.{n}", 0.0)) for n in POSE_NAMES[:3]])
    r = np.array([float(values.get(f"{prefix}.{n}", 0.0)) for n in POSE_NAMES[3:]])
    return d, r


@dataclass
class Pinhole:
    fx: float
    fy: float
    cx: float
    cy: float
    R: np.ndarray  # world from CV camera
    t: np.ndarray  # camera centre in world
    width: int
    height: int

    def camera_points(self, points: np.ndarray) -> np.ndarray:
        return (np.asarray(points, float) - self.t) @ self.R

    def project(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(pixels (n, 2), depth (n,)): PinholeCamera.project, vectorised."""
        pc = self.camera_points(points)
        z = pc[:, 2]
        return np.column_stack([pc[:, 0] / z * self.fx + self.cx - 0.5, pc[:, 1] / z * self.fy + self.cy - 0.5]), z

    def ray(self, pixels: np.ndarray) -> np.ndarray:
        """World-frame ray directions through pixels (PinholeCamera.deproject's equations at unit depth)."""
        pixels = np.asarray(pixels, float)
        pc = np.column_stack([(pixels[:, 0] + 0.5 - self.cx) / self.fx, (pixels[:, 1] + 0.5 - self.cy) / self.fy, np.ones(len(pixels))])
        return pc @ self.R.T

    def stock(self):
        from bam_scan_tunnel.camera_geometry import PinholeCamera  # noqa: PLC0415

        return PinholeCamera(fx=self.fx, fy=self.fy, cx=self.cx, cy=self.cy, width=self.width, height=self.height,
                             world_from_cam_rotation=self.R, world_from_cam_translation=self.t)

    def visible(self, pixels: np.ndarray, depth: np.ndarray, margin: float = 2.0) -> np.ndarray:
        return (depth > 0.05) & (pixels[:, 0] > margin) & (pixels[:, 0] < self.width - margin) & (pixels[:, 1] > margin) & (pixels[:, 1] < self.height - margin)


def mujoco_pose(model, data, camera: str) -> tuple[np.ndarray, np.ndarray]:
    """A MuJoCo camera's world-from-CV rotation and centre (PinholeCamera.from_mujoco's convention)."""
    cam = model.camera(camera).id
    return data.cam_xmat[cam].reshape(3, 3) @ CV_FLIP, data.cam_xpos[cam].copy()


def check_against_stock(camera: Pinhole, points: np.ndarray) -> float:
    """Max |vectorised - stock| over `points`, px. The stock projector is bam_scan_tunnel's; a drift here would be a different camera."""
    mine, _ = camera.project(points)
    stock = camera.stock()
    theirs = np.array([stock.project(p)[:2] for p in points])
    err = float(np.abs(mine - theirs).max()) if len(points) else 0.0
    if err > 1e-9:
        raise AssertionError(f"the vectorised pinhole drifted from bam_scan_tunnel's PinholeCamera by {err:.3g} px")
    return err


def tag_corners(size_m: float) -> np.ndarray:
    """A square tag's corners in its own plane (x = 0, facing +x), centred."""
    h = size_m / 2.0
    return np.array([[0.0, -h, -h], [0.0, h, -h], [0.0, h, h], [0.0, -h, h]])


def least_squares_with_ci(residual, x0, x_scale, *, names) -> tuple[np.ndarray, dict, object]:
    """scipy least_squares (Levenberg-Marquardt) with 95 % intervals from the Jacobian at the solution, scaled by the residual's own
    variance (the pixel noise is white: one detection per corner per view)."""
    from scipy.optimize import least_squares  # noqa: PLC0415

    fit = least_squares(residual, x0, x_scale=x_scale, method="lm")
    dof = max(1, fit.fun.size - len(x0))
    cov = np.linalg.pinv(fit.jac.T @ fit.jac) * float(fit.fun @ fit.fun) / dof
    half = 1.96 * np.sqrt(np.clip(np.diag(cov), 0.0, None))
    return fit.x, {n: (float(v - h), float(v + h)) for n, v, h in zip(names, fit.x, half)}, fit


def rms(x) -> float:
    x = np.asarray(x, float)
    return float(math.sqrt(np.mean(x ** 2))) if x.size else float("nan")
