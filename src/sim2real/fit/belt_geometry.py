"""Standard geometric fits a belt calibration is made of: plane, rigid transform, a carried line with scale and runout, a time offset.

numpy only (fit/ sits left of sim/ and models/; decision-package-layers-2026-11-10). Each is a textbook method, named where it comes from,
so a reader can check it against the source rather than against this file:

- fit_plane: total least squares by SVD (the smallest singular vector of the centred points is the normal), with one trimmed re-fit.
- kabsch: Kabsch 1976 / Umeyama 1991 without scale.
- fit_belt_line: PCA direction, then ordinary least squares of travel on encoder revs with a once-per-drum-turn sine and cosine (an
  eccentric drum's position ripple), the way a Prusa belt tuner or ABB's conveyor calibration reads counts per metre.
- fit_time_offset: grid then golden refinement of the shift that best explains a camera track by the encoder log (cross-correlation in
  the time domain, as Kalibr's temporal calibration does with splines).

SI inside (m, rad, s); callers convert to mm and degrees for people.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = ["Plane", "BeltLine", "fit_plane", "kabsch", "fit_belt_line", "fit_time_offset", "rotation_zyx", "mean_transform",
           "rotation_angle_deg", "vector_angle_deg", "invert", "scan_line_on_plane"]


def rotation_zyx(yaw: float, pitch: float, roll: float) -> np.ndarray:
    """R = Rz(yaw) Ry(pitch) Rx(roll), radians."""

    cz, sz, cy, sy, cx, sx = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1.0]])
    ry = np.array([[cy, 0, sy], [0, 1.0, 0], [-sy, 0, cy]])
    rx = np.array([[1.0, 0, 0], [0, cx, -sx], [0, sx, cx]])
    return rz @ ry @ rx


def invert(t: np.ndarray) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = t[:3, :3].T
    out[:3, 3] = -t[:3, :3].T @ t[:3, 3]
    return out


def rotation_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """The angle of the rotation between two rotation matrices (or the rotation parts of two 4 x 4 transforms)."""

    rel = a[:3, :3].T @ b[:3, :3]
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(rel) - 1.0) / 2.0))))


def vector_angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    c = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


@dataclass(frozen=True)
class Plane:
    normal: np.ndarray   # unit, pointing up (+z)
    offset: float        # normal . p = offset
    rms: float           # perpendicular residual RMS of the points kept
    n_points: int

    def height_at(self, x: float, y: float) -> float:
        n = self.normal
        return float((self.offset - n[0] * x - n[1] * y) / n[2])

    def distance(self, points: np.ndarray) -> np.ndarray:
        return np.asarray(points) @ self.normal - self.offset

    @property
    def tilt_deg(self) -> float:
        """The plane's angle from horizontal."""

        return math.degrees(math.acos(min(1.0, abs(float(self.normal[2])))))

    def transformed(self, t: np.ndarray) -> "Plane":
        """The same plane expressed in another frame: t maps this plane's frame into it."""

        n = t[:3, :3] @ self.normal
        p = t[:3, :3] @ (self.normal * self.offset) + t[:3, 3]
        if n[2] < 0:
            n = -n
        return Plane(n, float(n @ p), self.rms, self.n_points)


def fit_plane(points: np.ndarray, trim_sigma: float = 3.0) -> Plane:
    points = np.asarray(points, dtype=float)
    points = points[np.all(np.isfinite(points), axis=1)]

    def _fit(p):
        centre = p.mean(axis=0)
        _, _, vt = np.linalg.svd(p - centre, full_matrices=False)
        n = vt[-1]
        if n[2] < 0:
            n = -n
        return n, float(n @ centre)

    n, d = _fit(points)
    residual = points @ n - d
    keep = np.abs(residual) <= trim_sigma * max(residual.std(), 1e-12)
    if keep.sum() >= 3 and keep.sum() < len(points):
        points = points[keep]
        n, d = _fit(points)
        residual = points @ n - d
    return Plane(n, d, float(np.sqrt(np.mean(residual ** 2))), len(points))


def kabsch(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The rigid T (4 x 4) with b ~= R a + t, least squares over corresponding rows."""

    a, b = np.asarray(a, float), np.asarray(b, float)
    ca, cb = a.mean(axis=0), b.mean(axis=0)
    h = (a - ca).T @ (b - cb)
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    r = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    out = np.eye(4)
    out[:3, :3] = r
    out[:3, 3] = cb - r @ ca
    return out


def mean_transform(transforms: list[np.ndarray]) -> np.ndarray:
    """Translation mean and the chordal L2 mean of the rotations (Hartley et al. 2013, "Rotation averaging")."""

    rs = sum(t[:3, :3] for t in transforms)
    u, _, vt = np.linalg.svd(rs)
    out = np.eye(4)
    out[:3, :3] = u @ np.diag([1.0, 1.0, np.sign(np.linalg.det(u @ vt))]) @ vt
    out[:3, 3] = np.mean([t[:3, 3] for t in transforms], axis=0)
    return out


@dataclass(frozen=True)
class BeltLine:
    m_per_rev: float          # surface travel per motor rev
    direction: np.ndarray     # unit, in the points' frame, positive revs move along it
    origin: np.ndarray        # the fitted position at revs = 0
    runout_m: float           # amplitude of the once-per-drum-turn position ripple
    runout_phase_rad: float
    residual_rms_m: float     # along-track residual after the fit
    wander_rms_m: float       # perpendicular scatter: sideways tracking wander plus pose noise
    n_points: int


def fit_belt_line(revs: np.ndarray, points: np.ndarray, revs_per_drum_turn: float) -> BeltLine:
    revs, points = np.asarray(revs, float), np.asarray(points, float)
    centre = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - centre, full_matrices=False)
    direction = vt[0]
    along = (points - centre) @ direction
    if np.polyfit(revs, along, 1)[0] < 0:
        direction, along = -direction, -along
    phase = 2 * math.pi * revs / revs_per_drum_turn
    a = np.column_stack([np.ones_like(revs), revs, np.sin(phase), np.cos(phase)])
    coef, *_ = np.linalg.lstsq(a, along, rcond=None)
    residual = along - a @ coef
    perpendicular = (points - centre) - np.outer(along, direction)
    # r sin(phi + p) = r cos p sin(phi) + r sin p cos(phi)
    runout = math.hypot(coef[2], coef[3])
    return BeltLine(float(coef[1]), direction, centre + direction * coef[0], runout, math.atan2(coef[3], coef[2]),
                    float(np.sqrt(np.mean(residual ** 2))), float(np.sqrt(np.mean(np.sum(perpendicular ** 2, axis=1)))), len(revs))


def fit_time_offset(stamps: np.ndarray, position: np.ndarray, t_log: np.ndarray, revs_log: np.ndarray,
                    search_s: tuple[float, float] = (-0.2, 0.2)) -> float:
    """The latency d with position(stamp) ~= a + b * revs(stamp - d): the camera's frame was taken d before it was stamped.

    Needs the belt to move both ways (or at two speeds): at one constant speed a latency and a position offset are the same thing."""

    stamps, position = np.asarray(stamps, float), np.asarray(position, float)

    def cost(d):
        x = np.interp(stamps - d, t_log, revs_log)
        a = np.column_stack([np.ones_like(x), x])
        coef, *_ = np.linalg.lstsq(a, position, rcond=None)
        return float(np.sum((position - a @ coef) ** 2))

    grid = np.linspace(search_s[0], search_s[1], 401)
    best = grid[int(np.argmin([cost(d) for d in grid]))]
    lo, hi = best - (grid[1] - grid[0]), best + (grid[1] - grid[0])
    g = (math.sqrt(5) - 1) / 2
    for _ in range(60):
        m1, m2 = hi - g * (hi - lo), lo + g * (hi - lo)
        if cost(m1) < cost(m2):
            hi = m2
        else:
            lo = m1
    return float((lo + hi) / 2)


def scan_line_on_plane(camera_pose: np.ndarray, camera_matrix: np.ndarray, plane_point: np.ndarray, plane_normal: np.ndarray,
                       half_width_px: float = 300.0) -> tuple[np.ndarray, np.ndarray, float]:
    """Where a line scanner's centre row (v = cy) meets a plane: two points (at u = cx -+ half_width_px) and the metres per pixel there.

    The pinhole push-broom model of Gupta & Hartley 1997 restricted to one row; camera_pose maps OpenCV camera coordinates into the
    plane's frame."""

    k = camera_matrix
    points = []
    for u in (k[0, 2] - half_width_px, k[0, 2] + half_width_px):
        ray = camera_pose[:3, :3] @ np.array([(u - k[0, 2]) / k[0, 0], 0.0, 1.0])
        origin = camera_pose[:3, 3]
        s = float(plane_normal @ (plane_point - origin)) / float(plane_normal @ ray)
        points.append(origin + s * ray)
    return points[0], points[1], float(np.linalg.norm(points[1] - points[0]) / (2 * half_width_px))
