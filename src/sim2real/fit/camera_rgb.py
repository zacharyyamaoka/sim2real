"""camera_rgb's rungs as equations, and the fits that identify them (cards: camera_rgb M0 pinhole ... M3 rolling shutter).

- M0 / M1 geometry: ``project`` (pinhole, then Brown-Conrady distortion in OpenCV's convention: k1 k2 p1 p2 k3), and ``calibrate_planar``,
  Zhang's (2000) planar calibration: a homography per view, the closed-form K, then Levenberg-Marquardt over K, distortion and every
  view's pose. ``distortion=False`` fits M0 (the pinhole alone).
- M2 photometry: ``fit_exposure_response``, the photon transfer method (EMVA 1288): mean DN on exposure for the black level, the response
  and the saturation, and variance on mean for the system gain and the read noise. Works on LINEAR DN: a gamma-encoded stream (the
  D435's rgb8) is decoded first.
- M2 timing: ``fit_latency`` from an LED switched on a stamped clock. M3: ``fit_line_delay`` from a target moving at known speed.

Every fit takes plain arrays (the camera is a black box: known inputs, measured outputs) and returns a frozen record whose field names are
the card's parameter names where one exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .least_squares import levenberg_marquardt

__all__ = ["Intrinsics", "project", "rodrigues", "calibrate_planar", "solve_pose", "PlanarCalibration", "ExposureResponse", "fit_exposure_response",
           "Latency", "fit_latency", "fit_line_delay", "board_points"]


# ------------------------------------------------------------------------------------------------------------------- M0 / M1 geometry


@dataclass(frozen=True)
class Intrinsics:
    """K and Brown-Conrady distortion (OpenCV's order and pixel convention: a pixel's centre at integer coordinates)."""

    fx: float
    fy: float
    cx: float
    cy: float
    distortion: tuple[float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0)  # k1 k2 p1 p2 k3

    @property
    def matrix(self) -> np.ndarray:
        return np.array([[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]])


def rodrigues(rvec) -> np.ndarray:
    """A rotation vector to its matrix."""
    rvec = np.asarray(rvec, float)
    theta = float(np.linalg.norm(rvec))
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + math.sin(theta) * kx + (1.0 - math.cos(theta)) * (kx @ kx)


def rotation_vector(R) -> np.ndarray:
    R = np.asarray(R, float)
    cosine = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    theta = math.acos(cosine)
    if theta < 1e-12:
        return np.zeros(3)
    axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2.0 * math.sin(theta))
    return axis * theta


def project(intrinsics: Intrinsics, rvec, tvec, points) -> np.ndarray:
    """World points (n, 3) through camera pose (rvec, tvec: camera from world) to pixels (n, 2)."""
    camera = np.asarray(points, float) @ rodrigues(rvec).T + np.asarray(tvec, float)
    x = camera[:, 0] / camera[:, 2]
    y = camera[:, 1] / camera[:, 2]
    k1, k2, p1, p2, k3 = intrinsics.distortion
    r2 = x * x + y * y
    radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
    xd = x * radial + 2.0 * p1 * x * y + p2 * (r2 + 2.0 * x * x)
    yd = y * radial + p1 * (r2 + 2.0 * y * y) + 2.0 * p2 * x * y
    return np.column_stack([intrinsics.fx * xd + intrinsics.cx, intrinsics.fy * yd + intrinsics.cy])


def board_points(columns: int, rows: int, pitch_m: float) -> np.ndarray:
    """A planar board's corners in its own frame (z = 0), row-major."""
    xs, ys = np.meshgrid(np.arange(columns) * pitch_m, np.arange(rows) * pitch_m)
    return np.column_stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)])


def _homography(plane_xy: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """Normalised DLT (Hartley): plane (x, y) -> pixel (u, v)."""

    def normaliser(points):
        centre = points.mean(axis=0)
        spread = np.sqrt(np.mean(np.sum((points - centre) ** 2, axis=1))) / math.sqrt(2.0)
        return np.array([[1 / spread, 0, -centre[0] / spread], [0, 1 / spread, -centre[1] / spread], [0, 0, 1]])

    Ta, Tb = normaliser(plane_xy), normaliser(pixels)
    a = (Ta @ np.column_stack([plane_xy, np.ones(len(plane_xy))]).T).T
    b = (Tb @ np.column_stack([pixels, np.ones(len(pixels))]).T).T
    rows = []
    for (x, y, _), (u, v, _) in zip(a, b, strict=True):
        rows.append([-x, -y, -1, 0, 0, 0, u * x, u * y, u])
        rows.append([0, 0, 0, -x, -y, -1, v * x, v * y, v])
    _, _, vt = np.linalg.svd(np.asarray(rows))
    H = vt[-1].reshape(3, 3)
    H = np.linalg.inv(Tb) @ H @ Ta
    return H / H[2, 2]


def _zhang_closed_form(homographies: list[np.ndarray]) -> np.ndarray:
    def v(H, i, j):
        h = H.T
        return np.array([h[i, 0] * h[j, 0], h[i, 0] * h[j, 1] + h[i, 1] * h[j, 0], h[i, 1] * h[j, 1],
                         h[i, 2] * h[j, 0] + h[i, 0] * h[j, 2], h[i, 2] * h[j, 1] + h[i, 1] * h[j, 2], h[i, 2] * h[j, 2]])

    V = []
    for H in homographies:
        V.append(v(H, 0, 1))
        V.append(v(H, 0, 0) - v(H, 1, 1))
    _, _, vt = np.linalg.svd(np.asarray(V))
    b11, b12, b22, b13, b23, b33 = vt[-1]
    if b11 < 0:
        b11, b12, b22, b13, b23, b33 = -b11, -b12, -b22, -b13, -b23, -b33
    cy = (b12 * b13 - b11 * b23) / (b11 * b22 - b12 * b12)
    scale = b33 - (b13 * b13 + cy * (b12 * b13 - b11 * b23)) / b11
    fx = math.sqrt(scale / b11)
    fy = math.sqrt(scale * b11 / (b11 * b22 - b12 * b12))
    cx = -b13 * fx * fx / scale
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]])


def _pose_from_homography(K: np.ndarray, H: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    Kinv = np.linalg.inv(K)
    h1, h2, h3 = H[:, 0], H[:, 1], H[:, 2]
    lam = 1.0 / np.linalg.norm(Kinv @ h1)
    r1, r2 = lam * Kinv @ h1, lam * Kinv @ h2
    t = lam * Kinv @ h3
    if t[2] < 0:  # the board must be in front of the camera
        r1, r2, t = -r1, -r2, -t
    U, _, Vt = np.linalg.svd(np.column_stack([r1, r2, np.cross(r1, r2)]))
    return rotation_vector(U @ Vt), t


@dataclass(frozen=True)
class PlanarCalibration:
    """Zhang's result: the card's fx_fy, cx_cy and distortion, one pose per view (the board's extrinsics), and the fit's own error."""

    intrinsics: Intrinsics
    rvecs: tuple[np.ndarray, ...]
    tvecs: tuple[np.ndarray, ...]
    rms_px: float
    half_widths: dict

    @property
    def fx_fy(self) -> tuple[float, float]:
        return (self.intrinsics.fx, self.intrinsics.fy)

    @property
    def cx_cy(self) -> tuple[float, float]:
        return (self.intrinsics.cx, self.intrinsics.cy)

    @property
    def distortion(self) -> tuple[float, ...]:
        return self.intrinsics.distortion


def calibrate_planar(board: np.ndarray, views: list[np.ndarray], *, distortion: bool = True) -> PlanarCalibration:
    """Zhang (2000) over planar board corners (n, 3) with z = 0 and their pixels in each view [(n, 2), ...]; >= 3 views, tilted."""

    if len(views) < 3:
        raise ValueError("Zhang's calibration needs at least three views of the board")
    board = np.asarray(board, float)
    homographies = [_homography(board[:, :2], np.asarray(view, float)) for view in views]
    K = _zhang_closed_form(homographies)
    poses = [_pose_from_homography(K, H) for H in homographies]
    n_dist = 5 if distortion else 0

    def unpack(x):
        intr = Intrinsics(x[0], x[1], x[2], x[3], tuple(x[4:9]) if distortion else (0.0,) * 5)
        start = 4 + n_dist
        return intr, [(x[start + 6 * i:start + 6 * i + 3], x[start + 6 * i + 3:start + 6 * i + 6]) for i in range(len(views))]

    def residual(x):
        intr, view_poses = unpack(x)
        return np.concatenate([(project(intr, r, t, board) - np.asarray(view, float)).ravel()
                               for (r, t), view in zip(view_poses, views, strict=True)])

    x0 = np.concatenate([[K[0, 0], K[1, 1], K[0, 2], K[1, 2]], np.zeros(n_dist), *[np.concatenate(p) for p in poses]])
    scale = np.concatenate([[K[0, 0], K[1, 1], K[0, 0], K[1, 1]], np.full(n_dist, 0.1),
                            *[np.array([1.0, 1.0, 1.0, 0.1, 0.1, 1.0]) for _ in poses]])
    n_intr = 4 + n_dist
    n_points = len(board)

    def jacobian(x, r):
        # WHY by blocks: a view's pose moves only that view's 2n residuals, so its six columns need one small projection each, not a
        # full residual (the dense difference made an 18-view calibration take minutes)
        jac = np.zeros((r.size, x.size))
        for i in range(n_intr):
            step = 1e-6 * max(abs(x[i]), scale[i])
            bumped = x.copy()
            bumped[i] += step
            jac[:, i] = (residual(bumped) - r) / step
        intr, view_poses = unpack(x)
        for v, ((rvec, tvec), view) in enumerate(zip(view_poses, views, strict=True)):
            rows = slice(2 * n_points * v, 2 * n_points * (v + 1))
            base = r[rows]
            pose = np.concatenate([rvec, tvec])
            for j in range(6):
                column = n_intr + 6 * v + j
                step = 1e-6 * max(abs(x[column]), scale[column])
                bumped = pose.copy()
                bumped[j] += step
                jac[rows, column] = ((project(intr, bumped[:3], bumped[3:], board) - np.asarray(view, float)).ravel() - base) / step
        return jac

    solution = levenberg_marquardt(residual, x0, scale=scale, jacobian=jacobian)
    intr, view_poses = unpack(solution.x)
    widths = solution.intervals()
    names = ["fx", "fy", "cx", "cy"] + (["k1", "k2", "p1", "p2", "k3"] if distortion else [])
    return PlanarCalibration(intr, tuple(np.array(r) for r, _ in view_poses), tuple(np.array(t) for _, t in view_poses), solution.rms,
                             {n: float(w) for n, w in zip(names, widths[:len(names)], strict=True)})


def solve_pose(intrinsics: Intrinsics, board: np.ndarray, view: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """A planar board's pose in one view with K and distortion held (PnP): the homography's pose, refined by Levenberg-Marquardt."""
    board = np.asarray(board, float)
    view = np.asarray(view, float)
    rvec, tvec = _pose_from_homography(intrinsics.matrix, _homography(board[:, :2], view))

    def residual(x):
        return (project(intrinsics, x[:3], x[3:], board) - view).ravel()

    solution = levenberg_marquardt(residual, np.concatenate([rvec, tvec]), scale=np.array([0.1, 0.1, 0.1, 0.1, 0.1, 1.0]))
    return solution.x[:3], solution.x[3:]


# ---------------------------------------------------------------------------------------------------------------------- M2 photometry


@dataclass(frozen=True)
class ExposureResponse:
    """The card's exposure_response, as the photon transfer method splits it (EMVA 1288), in linear DN at one gain setting."""

    black_dn: float               # the dark level (mean DN at zero exposure)
    response_dn_per_unit: float   # DN per exposure unit on this target (a grey card under these lights)
    saturation_dn: float          # where the response stops rising
    system_gain_dn_per_e: float   # K: DN per photo-electron (variance on mean slope)
    read_noise_dn: float          # sigma at zero signal

    def mean(self, exposure) -> np.ndarray:
        return np.minimum(self.black_dn + self.response_dn_per_unit * np.asarray(exposure, float), self.saturation_dn)

    def sigma(self, exposure) -> np.ndarray:
        signal = np.clip(self.mean(exposure) - self.black_dn, 0.0, None)
        return np.sqrt(self.read_noise_dn ** 2 + self.system_gain_dn_per_e * signal)


def fit_exposure_response(exposure, mean_dn, variance_dn, *, saturation_fraction: float = 0.9) -> ExposureResponse:
    """Grey-card sweep: one exposure per row, the patch's mean DN and its frame-to-frame variance. Rows within ``saturation_fraction`` of
    the brightest mean are treated as saturating and left out of both lines (EMVA 1288 fits the linear range only)."""

    exposure = np.asarray(exposure, float)
    mean_dn = np.asarray(mean_dn, float)
    variance_dn = np.asarray(variance_dn, float)
    saturation = float(mean_dn.max())
    linear = mean_dn < saturation_fraction * saturation
    if linear.sum() < 3:
        raise ValueError("fewer than three unsaturated exposures: extend the sweep toward the dark end")
    slope, intercept = np.polyfit(exposure[linear], mean_dn[linear], 1)
    signal = mean_dn[linear] - intercept
    gain_k, read_variance = np.polyfit(signal, variance_dn[linear], 1)
    return ExposureResponse(float(intercept), float(slope), saturation, float(gain_k), float(math.sqrt(max(read_variance, 0.0))))


# ---------------------------------------------------------------------------------------------------------------------- M2 / M3 timing


@dataclass(frozen=True)
class Latency:
    latency_s: float   # the card's latency_s: the median delay from event to the stamp that first shows it
    jitter_s: float    # its spread (1.4826 x MAD): the timing floor

    @property
    def samples(self) -> int:
        return 0


def fit_latency(event_times_s, first_seen_stamps_s) -> Latency:
    """LED switched on a stamped clock: each edge's switch time and the stamp of the first frame that shows it."""
    delays = np.asarray(first_seen_stamps_s, float) - np.asarray(event_times_s, float)
    median = float(np.median(delays))
    return Latency(median, float(1.4826 * np.median(np.abs(delays - median))))


def fit_line_delay(rows, columns, speed_px_per_s: float) -> float:
    """The card's line_delay_s (M3): a vertical edge moving across the image at ``speed_px_per_s`` appears sheared, its column rising by
    speed x delay per row (Oth 2013's rolling shutter, linear). Least squares of the edge's column on the row."""

    slope, _ = np.polyfit(np.asarray(rows, float), np.asarray(columns, float), 1)
    return float(slope / speed_px_per_s)
