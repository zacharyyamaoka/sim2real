"""The ArUco Marker type's three fits (PEP 0001 section 8): the printed size by caliper, the ids actually printed, and one bundle adjustment
of the camera, every sticker's as-built pose and print scale and the joints' zeros.

    from sim2real.fit import aruco
    aruco.caliper_scale([0.09849, 0.09851], 0.100, resolution_m=1e-5, tolerance=0.005)   # CaliperCheck(scale, ci95, n, within_tolerance)
    aruco.confirm_ids(images, "DICT_4X4_50", expected_ids)                               # IdCheck(found, missing, duplicate, ...)
    aruco.bundle_adjust(views, sheets, K=K, dist=dist, camera_in_base=T, link_pose=fk, anchor="plate_a", ...)   # Bundle

The instance is one printed sticker carrying one or more markers rigidly (a five-bar strip, a plate, a single tag), its layout from CAD.

WHY one bundle adjustment and not a pose per view (Zach, 2026-11-11, feedback-aruco-bundle-adjustment-every-rig): a sticker that is
1.5 % small or tilted 2 degrees reads as a 12-17 mm error at the strip's far end (the five-bar's L2, bam_rack_twin.fivebar_asbuilt); only a
joint fit of camera, stickers, scales and joint zeros against the encoders, with the CAD as the prior, separates them. The maths is
bam_rack_twin calib.py's (corners reprojected through the forward kinematics) and fivebar_asbuilt.py's (a 6-DOF correction in the sticker
frame plus a print scale), on fit/least_squares.py's numpy Levenberg-Marquardt (scipy is not a runtime dependency).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from .least_squares import levenberg_marquardt

__all__ = ["CaliperCheck", "IdCheck", "View", "MarkerSheet", "Bundle", "caliper_scale", "confirm_ids", "bundle_adjust", "reproject",
           "PREDEFINED_DICTIONARIES"]


# --- caliper: the printed size against its spec ------------------------------------------------------------------------------------------

# Student-t 97.5 % quantiles by degrees of freedom (Abramowitz and Stegun table 26.10); WHY a table: scipy is not a runtime dependency
_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
         13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000,
         120: 1.980}


def _t975(dof: int) -> float:
    if dof <= 0:
        return float("inf")
    for k in sorted(_T975):
        if dof <= k:
            return _T975[k]
    return 1.960


@dataclass(frozen=True)
class CaliperCheck:
    scale: float                      # measured / nominal (1.0 = printed to spec)
    ci95: tuple[float, float]         # the scale's 95 % interval
    n: int                            # readings
    within_tolerance: bool            # |scale - 1| <= the print tolerance
    tolerance: float = 0.0
    nominal_m: float = 0.0


def caliper_scale(readings_m: Sequence[float], nominal_m: float, *, resolution_m: float = 1e-5, tolerance: float = 0.005) -> CaliperCheck:
    """An operator's caliper readings of a printed length (aruco-studio sheets print a 100 mm ruler bar; a marker side works too) ->
    the print scale with a 95 % interval, and whether it is inside the print tolerance.

    WHY the interval never collapses below the resolution: three readings that agree to the last digit say the spread is under one count,
    not zero; the spread used is at least a uniform count's (resolution / sqrt 12) and the half-width at least half a count."""

    values = np.asarray(readings_m, float)
    if values.size == 0 or nominal_m <= 0:
        raise ValueError("caliper_scale needs at least one reading and a positive nominal length")
    n = int(values.size)
    mean = float(values.mean())
    spread = float(values.std(ddof=1)) if n > 1 else 0.0
    spread = max(spread, resolution_m / math.sqrt(12.0))
    half = (_t975(n - 1) * spread / math.sqrt(n)) if n > 1 else resolution_m
    half = max(half, 0.5 * resolution_m)
    scale = mean / nominal_m
    ci = (scale - half / nominal_m, scale + half / nominal_m)
    return CaliperCheck(scale=scale, ci95=ci, n=n, within_tolerance=bool(abs(scale - 1.0) <= tolerance), tolerance=tolerance,
                        nominal_m=float(nominal_m))


# --- id confirmation: every expected id, no duplicate, no stranger, the right dictionary ---------------------------------------------------

PREDEFINED_DICTIONARIES = (
    "DICT_4X4_50", "DICT_4X4_100", "DICT_4X4_250", "DICT_4X4_1000", "DICT_5X5_50", "DICT_5X5_100", "DICT_5X5_250", "DICT_5X5_1000",
    "DICT_6X6_50", "DICT_6X6_100", "DICT_6X6_250", "DICT_6X6_1000", "DICT_7X7_50", "DICT_7X7_100", "DICT_7X7_250", "DICT_7X7_1000",
    "DICT_ARUCO_ORIGINAL", "DICT_APRILTAG_16h5", "DICT_APRILTAG_25h9", "DICT_APRILTAG_36h10", "DICT_APRILTAG_36h11", "DICT_ARUCO_MIP_36h12",
)


@dataclass(frozen=True)
class IdCheck:
    found: tuple[int, ...]            # every expected-dictionary id seen in any image, sorted
    missing: tuple[int, ...]          # expected, never seen
    duplicate: tuple[int, ...]        # seen more than once in one image (two stickers printed with one id)
    unexpected: tuple[int, ...]       # seen, not expected (a stranger in the cell)
    wrong_dictionary: str | None      # the predefined dictionary that actually decodes the markers, when the expected one does not
    passed: bool
    dictionary: str = ""
    per_image: tuple[tuple[int, ...], ...] = field(default=())


def _detect(cv2, image: np.ndarray, dictionary: str) -> list[int]:
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary)), cv2.aruco.DetectorParameters())
    _corners, ids, _rejected = detector.detectMarkers(image)
    return [] if ids is None else [int(i) for i in np.asarray(ids).ravel()]


def confirm_ids(images: Sequence[np.ndarray], dictionary: str, expected_ids: Sequence[int]) -> IdCheck:
    """Detect every marker of `dictionary` in each image (OpenCV's ArucoDetector) and compare with the ids the sheet should carry.

    When expected ids are missing, every predefined dictionary is tried: one that decodes more markers than the expected one is named in
    `wrong_dictionary` (the smallest such, since OpenCV's dictionaries of one bit size nest: DICT_5X5_50 is DICT_5X5_100's first 50)."""

    import cv2  # noqa: PLC0415  (the vision extra; WHY lazy: the module imports without OpenCV, and only this check needs it)

    expected = {int(i) for i in expected_ids}
    per_image = []
    duplicate: set[int] = set()
    for image in images:
        ids = _detect(cv2, np.asarray(image), dictionary)
        per_image.append(tuple(sorted(ids)))
        duplicate |= {i for i, count in Counter(ids).items() if count > 1}
    found = set().union(*map(set, per_image)) if per_image else set()
    missing = expected - found
    wrong = None
    if missing:
        best_count = sum(len(ids) for ids in per_image)
        for name in PREDEFINED_DICTIONARIES:
            if name == dictionary or not hasattr(cv2.aruco, name):
                continue
            count = sum(len(_detect(cv2, np.asarray(image), name)) for image in images)
            if count > best_count:
                best_count, wrong = count, name
    unexpected = found - expected
    passed = not missing and not duplicate and not unexpected and wrong is None
    return IdCheck(found=tuple(sorted(found)), missing=tuple(sorted(missing)), duplicate=tuple(sorted(duplicate)),
                   unexpected=tuple(sorted(unexpected)), wrong_dictionary=wrong, passed=passed, dictionary=dictionary,
                   per_image=tuple(per_image))


# --- bundle adjustment -------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class View:
    """One image: the joint readings (encoders, zeros not applied) and every detected marker's four corners in pixels, by id."""

    joints: Mapping[str, float]
    corners_px: Mapping[int, np.ndarray]


@dataclass(frozen=True)
class MarkerSheet:
    """One printed sticker: its markers' corners in the sheet frame (N, 4, 3) in metres at print scale 1, and its CAD pose on its link."""

    group: str
    link: str
    dictionary: str
    ids: tuple[int, ...]
    corners_m: np.ndarray
    pose_on_link: np.ndarray


@dataclass(frozen=True)
class Bundle:
    camera_in_base: np.ndarray                 # 4 x 4
    joint_offsets: dict[str, float]            # rad, added to each encoder reading
    sheet_poses: dict[str, np.ndarray]         # group -> 4 x 4 on its link (CAD pose x the as-built correction)
    scales: dict[str, float]                   # group -> print scale
    residual_px: float                         # per-axis RMS of the corners' reprojection
    observability: dict[str, str]              # "<group>.print_scale" / "<joint>.zero_offset" -> measured | prior-held | unobservable
    as_built_offsets: dict[str, np.ndarray] = field(default_factory=dict)  # group -> the 4 x 4 correction in the sheet frame
    noise_px: float = 0.0                      # the robust per-axis corner noise the residuals were weighted by
    iterations: int = 0
    converged: bool = False


def _rot(rv: np.ndarray) -> np.ndarray:
    th = float(np.linalg.norm(rv))
    if th < 1e-15:
        return np.eye(3)
    k = rv / th
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + math.sin(th) * kx + (1.0 - math.cos(th)) * kx @ kx


def _delta(x6: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = _rot(x6[:3])
    T[:3, 3] = x6[3:6]
    return T


def _project(K: np.ndarray, dist: np.ndarray, pc: np.ndarray) -> np.ndarray:
    """Pinhole with Brown-Conrady distortion (k1, k2, p1, p2, k3: OpenCV's order) of camera-frame points (n, 3)."""
    z = pc[:, 2]
    x, y = pc[:, 0] / z, pc[:, 1] / z
    d = np.zeros(5)
    d[: min(5, len(dist))] = np.asarray(dist, float).ravel()[:5]
    if np.any(d):
        k1, k2, p1, p2, k3 = d
        r2 = x * x + y * y
        radial = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 ** 3
        x, y = x * radial + 2 * p1 * x * y + p2 * (r2 + 2 * x * x), y * radial + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
    return np.column_stack([K[0, 0] * x + K[0, 1] * y + K[0, 2], K[1, 1] * y + K[1, 2]])


def _soft_l1(e: np.ndarray, c: float) -> np.ndarray:
    """Each corner's 2-vector scaled so its squared norm is soft-L1's cost: c^2 * 2 (sqrt(1 + |e|^2 / c^2) - 1)."""
    n = np.linalg.norm(e, axis=1)
    z = (n / c) ** 2
    rho = 2.0 * (np.sqrt(1.0 + z) - 1.0)
    factor = np.ones_like(n)
    big = n > 1e-12
    factor[big] = c * np.sqrt(rho[big]) / n[big]
    return e * factor[:, None]


WEAK_SCALE_PRIOR = 0.02   # WHY 2 %: printers miss by up to ~1.5 % (the five-bar's L2 strip, 0.98493); a caliper reading replaces it
CAMERA_REGULARISER = (0.05, math.radians(5.0))   # only for the observability check's tiny regulariser; the camera itself has no prior


def bundle_adjust(views: Sequence[View], sheets: Sequence[MarkerSheet], *, K, dist, camera_in_base, link_pose: Callable,
                  anchor: str, joint_offsets: Mapping[str, float] | None = None, fit_joints: Sequence[str] = (),
                  scale_priors: Mapping[str, tuple[float, float]] | None = None, pose_prior: tuple[float, float] = (0.002, math.radians(1.0)),
                  joint_prior_rad: float = math.radians(2.0), robust_px: float = 1.0, max_iterations: int = 60) -> Bundle:
    """One fixed camera over stickers on links: fit the camera's pose, every free sticker's as-built 6-DOF correction (in its own frame)
    and print scale, and the zeros of `fit_joints`, by Levenberg-Marquardt on every corner's reprojection error.

    - `anchor`: the gauge sticker, held exactly at its CAD pose with scale 1.0 (it fixes the frame and the metre);
    - priors: each free sticker's CAD pose (`pose_prior`: metres, radians, 1 sigma), the joints' zeros at `joint_offsets`
      (`joint_prior_rad`), each sticker's print scale from `scale_priors` {group: (mean, sigma)} (the caliper routine's result) or else a
      weak CAD prior (1.0 +- WEAK_SCALE_PRIOR);
    - robust soft-L1 on each corner's pixel error at `robust_px`; the residuals are weighted by the corners' own robust noise (estimated
      from the fit, so the priors weigh what they should whatever the noise);
    - `observability`: for each print scale and joint zero, whether the views alone determine it ("measured"), or only a prior holds it
      ("prior-held"; "unobservable" when it has no prior). From one fixed camera a static sticker's depth and scale trade exactly, so
      its scale is only ever prior-held; a sticker the joints carry through a wide arc is measured."""

    K = np.asarray(K, float)
    dist = np.zeros(5) if dist is None else np.asarray(dist, float)
    camera0 = np.asarray(camera_in_base, float)
    sheets = list(sheets)
    by_group = {s.group: s for s in sheets}
    if anchor not in by_group:
        raise KeyError(f"anchor sticker {anchor!r} is not one of {sorted(by_group)}")
    free = [s.group for s in sheets if s.group != anchor]
    fit_joints = tuple(fit_joints)
    offsets0 = {k: float(v) for k, v in (joint_offsets or {}).items()}
    for j in fit_joints:
        offsets0.setdefault(j, 0.0)
    priors = dict(scale_priors or {})
    sigma_t, sigma_r = float(pose_prior[0]), float(pose_prior[1])

    # parameter layout: camera (6) | per free sheet: rotation (3), translation (3), scale (1) | joint zeros
    n_cam = 6
    sheet_at = {g: n_cam + 7 * i for i, g in enumerate(free)}
    joint_at = {j: n_cam + 7 * len(free) + i for i, j in enumerate(fit_joints)}
    n = n_cam + 7 * len(free) + len(fit_joints)
    x0 = np.zeros(n)
    for g in free:
        x0[sheet_at[g] + 6] = priors[g][0] if g in priors else 1.0
    for j in fit_joints:
        x0[joint_at[j]] = offsets0[j]

    # observations, gathered once: per (sheet, view) the layout rows seen and their pixels
    id_index = {}
    for s in sheets:
        layout = np.asarray(s.corners_m, float).reshape(-1, 4, 3)
        if len(layout) != len(s.ids):
            raise ValueError(f"sticker {s.group}: {len(s.ids)} ids but {len(layout)} markers in corners_m")
        for k, marker in enumerate(s.ids):
            id_index[int(marker)] = (s.group, k)
    blocks = []   # (group, view index, layout points (m, 3), pixels (m, 2))
    for vi, view in enumerate(views):
        rows: dict[str, tuple[list, list]] = {}
        for marker, px in view.corners_px.items():
            hit = id_index.get(int(marker))
            if hit is None:
                continue
            group, k = hit
            pts, obs = rows.setdefault(group, ([], []))
            pts.append(np.asarray(by_group[group].corners_m, float).reshape(-1, 4, 3)[k])
            obs.append(np.asarray(px, float).reshape(4, 2))
        for group, (pts, obs) in rows.items():
            blocks.append((group, vi, np.concatenate(pts), np.concatenate(obs)))
    if not blocks:
        raise ValueError("no view sees any sticker's markers")
    n_obs = sum(len(b[3]) for b in blocks)

    def unpack(x):
        camera = camera0 @ _delta(x[:6])
        poses, scales = {anchor: np.asarray(by_group[anchor].pose_on_link, float)}, {anchor: 1.0}
        deltas = {anchor: np.eye(4)}
        for g in free:
            deltas[g] = _delta(x[sheet_at[g]:sheet_at[g] + 6])
            poses[g] = np.asarray(by_group[g].pose_on_link, float) @ deltas[g]
            scales[g] = float(x[sheet_at[g] + 6])
        joints = dict(offsets0)
        for j in fit_joints:
            joints[j] = float(x[joint_at[j]])
        return camera, poses, scales, joints, deltas

    def reprojection(x) -> np.ndarray:
        camera, poses, scales, offsets, _ = unpack(x)
        base_in_camera = np.linalg.inv(camera)
        link_cache: dict[tuple[str, int], np.ndarray] = {}
        out = np.empty((n_obs, 2))
        at = 0
        for group, vi, pts, obs in blocks:
            sheet = by_group[group]
            key = (sheet.link, vi)
            if key not in link_cache:
                q = {name: float(v) + offsets.get(name, 0.0) for name, v in views[vi].joints.items()}
                link_cache[key] = np.asarray(link_pose(sheet.link, q), float)
            T = base_in_camera @ link_cache[key] @ poses[group]
            pc = pts * scales[group] @ T[:3, :3].T + T[:3, 3]
            out[at:at + len(pts)] = _project(K, dist, pc) - obs
            at += len(pts)
        return out

    def prior_rows(x) -> np.ndarray:
        rows = []
        for g in free:
            i = sheet_at[g]
            rows += list(x[i:i + 3] / sigma_r) + list(x[i + 3:i + 6] / sigma_t)
            mean, sd = priors.get(g, (1.0, WEAK_SCALE_PRIOR))
            rows.append((x[i + 6] - mean) / sd)
        for j in fit_joints:
            rows.append((x[joint_at[j]] - offsets0[j]) / joint_prior_rad)
        return np.asarray(rows, float)

    scale_vec = np.full(n, 1e-2)
    scale_vec[3:6] = 1e-3
    for g in free:
        scale_vec[sheet_at[g] + 3:sheet_at[g] + 6] = 1e-3

    # WHY re-weighted passes: the priors are in sigmas, so the pixel residuals must be too; the corners' noise is not given (it is the
    # camera's and the detector's), so it is estimated robustly from the fit's own residuals and the fit is run again at that weight
    noise = float(robust_px)
    x = x0
    solution = None
    for _pass in range(4):
        def residual(at_x, noise=noise):
            return np.concatenate([_soft_l1(reprojection(at_x), robust_px).ravel() / noise, prior_rows(at_x)])

        solution = levenberg_marquardt(residual, x, scale=scale_vec, max_iterations=max_iterations, tolerance=1e-12)
        x = solution.x
        err = reprojection(x).ravel()
        estimate = max(1.4826 * float(np.median(np.abs(err - np.median(err)))), 1e-3)
        if abs(estimate - noise) <= 0.02 * noise:
            noise = estimate
            break
        noise = estimate

    camera, poses, scales, offsets, deltas = unpack(x)
    err = reprojection(x)

    # observability: the views' information alone (the data rows of the Jacobian, in sigmas), regularised by a millionth of every prior
    # so an exact degeneracy reads as a huge variance rather than a singular matrix; a parameter is measured when that view-only spread is
    # under half its prior's
    # WHY at the robust scale and not the estimated noise: observability is the geometry's, not the noise draw's; with noise-free corners
    # the estimated noise floors near zero and finite-difference round-off would read as information along an exact degeneracy
    J = solution.jacobian[: 2 * n_obs] * (noise / robust_px)
    info = J.T @ J
    prior_sd = np.empty(n)
    prior_sd[:3] = CAMERA_REGULARISER[1]
    prior_sd[3:6] = CAMERA_REGULARISER[0]
    for g in free:
        i = sheet_at[g]
        prior_sd[i:i + 3] = sigma_r
        prior_sd[i + 3:i + 6] = sigma_t
        prior_sd[i + 6] = priors.get(g, (1.0, WEAK_SCALE_PRIOR))[1]
    for j in fit_joints:
        prior_sd[joint_at[j]] = joint_prior_rad
    view_only = np.linalg.pinv(info + 1e-6 * np.diag(1.0 / prior_sd ** 2))
    observability = {f"{anchor}.print_scale": "held at 1.0 (the gauge sticker)"}

    def verdict(i: int, has_prior: bool) -> str:
        if math.sqrt(max(view_only[i, i], 0.0)) < 0.5 * prior_sd[i]:
            return "measured"
        return "prior-held" if has_prior else "unobservable"

    for g in free:
        observability[f"{g}.print_scale"] = verdict(sheet_at[g] + 6, True)
    for j in fit_joints:
        observability[f"{j}.zero_offset"] = verdict(joint_at[j], True)

    return Bundle(camera_in_base=camera, joint_offsets={k: float(v) for k, v in offsets.items()}, sheet_poses=poses, scales=scales,
                  residual_px=float(np.sqrt(np.mean(err ** 2))), observability=observability, as_built_offsets=deltas, noise_px=noise,
                  iterations=solution.iterations, converged=solution.converged)


def reproject(bundle: Bundle, views: Sequence[View], sheets: Sequence[MarkerSheet], *, K, dist, link_pose: Callable) -> tuple[np.ndarray, np.ndarray]:
    """The fitted twin's corners (camera x stickers x forward kinematics with the fitted zeros) projected into `views` (held-out ones, for a
    fidelity check), beside the detected corners: (predicted (n, 2), measured (n, 2)), every marker of a known sticker in every view."""

    K = np.asarray(K, float)
    dist = np.zeros(5) if dist is None else np.asarray(dist, float)
    where = {int(m): (s, k) for s in sheets for k, m in enumerate(s.ids)}
    base_in_camera = np.linalg.inv(bundle.camera_in_base)
    predicted, measured = [], []
    for view in views:
        q = {name: float(v) + bundle.joint_offsets.get(name, 0.0) for name, v in view.joints.items()}
        for marker, px in view.corners_px.items():
            hit = where.get(int(marker))
            if hit is None:
                continue
            sheet, k = hit
            pts = np.asarray(sheet.corners_m, float).reshape(-1, 4, 3)[k] * bundle.scales[sheet.group]
            T = base_in_camera @ np.asarray(link_pose(sheet.link, q), float) @ bundle.sheet_poses[sheet.group]
            predicted.append(_project(K, dist, pts @ T[:3, :3].T + T[:3, 3]))
            measured.append(np.asarray(px, float).reshape(4, 2))
    if not predicted:
        return np.empty((0, 2)), np.empty((0, 2))
    return np.concatenate(predicted), np.concatenate(measured)
