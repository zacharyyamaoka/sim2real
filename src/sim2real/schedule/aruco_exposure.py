"""The camera tuned for ArUco ACCURACY: pick exposure, gain and frame rate by how well a known board's corners can be located, not by mean
grey (bam_rack_twin.hardware.d435_exposure's band) and not by markers read (bam_camera_calibration task.aruco_score).

    from sim2real.schedule.aruco_exposure import Board, tune
    board = Board("DICT_4X4_50", {0: corners0, 1: corners1, ...})          # each (4, 3) in metres, the board frame
    result = tune(camera.capture, board, K, dist, candidates, frames=5)     # candidates: (exposure_s, gain, fps), exposure <= 1 / fps
    result.exposure_s, result.gain, result.fps, result.rows

`capture(exposure_s, gain, fps, n)` sets the camera and returns n uint8 frames; the tuner never sees the truth. Per candidate it scores:

    score_px = board PnP reprojection RMS                (the corners' noise: shot noise, read noise x gain, quantisation)
             + MISS_PX x the share of markers not read   (a missed marker costs what the accuracy oracle charges it: 5 px)
             + BLUR_WEIGHT x the blur length              (the board's image speed x exposure: a residual is blind to blur)

the first two pooled over every frame rate tried at the same (exposure, gain).

WHY the blur term (PEP 0001 section 9, the designer's prototype, 2026-11-12): a board PnP residual alone picks within 1.1 x of the true
best in static scenes but cannot see motion blur, which shifts every corner together; the image speed is measured from the board's
frame-to-frame motion at the fastest frame rate tried and multiplied by each candidate's exposure. WHY the frame rate can drop: in the dark
only exposures past 1/15 s are good, so the right rate is 6 fps (the rack's own 2026-11-10 finding,
bam_rack_twin.hardware.fivebar_run.D435_STILL_LOOK); on near-ties the higher frame rate wins.

Runs after the exposure lock (camera.exposure_lock, bam_camera_calibration) and refines its exposure and gain. Layer: schedule/ (imports
nothing above metrics/; OpenCV imported lazily, the vision extra).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

__all__ = ["Board", "ArucoTuning", "tune", "MISS_PX", "BLUR_WEIGHT"]

MISS_PX = 5.0          # what a missed marker costs: the accuracy oracle's charge (tests/test_aruco_marker.py)
BLUR_WEIGHT = 0.05     # px of score per px of blur length (the designer's prototype)
TIE = (1.02, 0.005)    # a candidate within 2 % + 0.005 px of the best is a tie; ties go to the higher frame rate


@dataclass(frozen=True)
class Board:
    """A rigid board of markers: its dictionary and each marker's four corners (4, 3) in metres in the board frame."""

    dictionary: str
    corners_m: Mapping[int, np.ndarray]


@dataclass(frozen=True)
class ArucoTuning:
    exposure_s: float
    gain: float
    fps: float
    score_px: float
    detection_rate: float
    rows: tuple[dict, ...] = field(default=())
    speed_px_s: float = 0.0          # the board's measured image speed


def _detector(cv2, dictionary: str):
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary)), params)


def _frame_stats(cv2, detector, board: Board, K: np.ndarray, dist: np.ndarray, frame: np.ndarray):
    """(markers read, reprojection RMS px or None, {id: corner centroid px})."""
    corners, ids, _rejected = detector.detectMarkers(frame)
    if ids is None:
        return 0, None, {}
    seen = {int(i): np.asarray(c, float).reshape(4, 2) for i, c in zip(np.asarray(ids).ravel(), corners) if int(i) in board.corners_m}
    if not seen:
        return 0, None, {}
    obj = np.concatenate([np.asarray(board.corners_m[i], float).reshape(4, 3) for i in seen]).astype(np.float64)
    img = np.concatenate([seen[i] for i in seen]).astype(np.float64)
    flag = cv2.SOLVEPNP_IPPE if np.ptp(obj[:, 2]) < 1e-9 else cv2.SOLVEPNP_ITERATIVE
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=flag)
    rms = None
    if ok:
        ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, rvec, tvec, useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
        projected, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
        rms = float(np.sqrt(np.mean((projected.reshape(-1, 2) - img) ** 2)))
    return len(seen), rms, {i: c.mean(axis=0) for i, c in seen.items()}


def _speed(centroids: Sequence[dict], fps: float) -> float | None:
    """The board's median image speed (px/s) from consecutive frames' common markers."""
    speeds = []
    for a, b in zip(centroids, centroids[1:]):
        common = set(a) & set(b)
        if common:
            shift = np.mean([b[i] - a[i] for i in common], axis=0)
            speeds.append(float(np.linalg.norm(shift)) * fps)
    return float(np.median(speeds)) if speeds else None


def tune(capture: Callable[[float, float, float, int], Sequence[np.ndarray]], board: Board, K, dist,
         candidates: Sequence[tuple[float, float, float]], *, frames: int = 5, min_fps: float = 0.0) -> ArucoTuning:
    """Score every (exposure_s, gain, fps) candidate on `frames` captured frames and return the most accurate (see the module doc)."""

    import cv2  # noqa: PLC0415  (the vision extra)

    K = np.asarray(K, np.float64)
    dist = np.zeros(5) if dist is None else np.asarray(dist, np.float64)
    detector = _detector(cv2, board.dictionary)
    n_markers = len(board.corners_m)
    usable = [tuple(map(float, c)) for c in candidates if c[2] >= min_fps and c[0] <= 1.0 / c[2] + 1e-9]
    if not usable:
        raise ValueError("no candidate fits its frame (exposure <= 1 / fps) at or above min_fps")

    measured = []
    for exposure, gain, fps in usable:
        shots = capture(exposure, gain, fps, frames)
        stats = [_frame_stats(cv2, detector, board, K, dist, np.asarray(f)) for f in shots]
        read = sum(s[0] for s in stats)
        rms = [s[1] for s in stats if s[1] is not None]
        measured.append({"exposure_s": exposure, "gain": gain, "fps": fps, "detection_rate": read / float(n_markers * len(shots)),
                         "reprojection_px": float(np.mean(rms)) if rms else None, "speed_px_s": _speed([s[2] for s in stats], fps)})

    # the scene's image speed: from the fastest frame rate tried (the shortest gap between frames aliases least), its best-read frames
    fastest = max(m["fps"] for m in measured)
    speeds = [m["speed_px_s"] for m in measured if m["fps"] == fastest and m["speed_px_s"] is not None and m["detection_rate"] >= 0.5]
    speed = float(np.median(speeds)) if speeds else 0.0

    # WHY pooled over frame rates: one frame's corners depend on its exposure and gain, not on how often frames come (the rate only
    # bounds the exposure); pooling every rate's frames of one (exposure, gain) halves the noise of its score, and equal scores then go
    # to the highest rate that fits
    pooled: dict[tuple[float, float], list[dict]] = {}
    for m in measured:
        pooled.setdefault((m["exposure_s"], m["gain"]), []).append(m)
    rows = []
    for m in measured:
        group = pooled[(m["exposure_s"], m["gain"])]
        rms = [g["reprojection_px"] for g in group if g["reprojection_px"] is not None]
        residual = float(np.mean(rms)) if rms else MISS_PX
        detection = float(np.mean([g["detection_rate"] for g in group]))
        blur = speed * m["exposure_s"]
        score = residual + MISS_PX * (1.0 - detection) + BLUR_WEIGHT * blur
        rows.append({**m, "blur_px": blur, "pooled_reprojection_px": residual, "pooled_detection_rate": detection, "score_px": float(score)})

    best = min(r["score_px"] for r in rows)
    ties = [r for r in rows if r["score_px"] <= TIE[0] * best + TIE[1]]
    pick = min(ties, key=lambda r: (-r["fps"], r["score_px"]))
    if not math.isfinite(pick["score_px"]):
        raise RuntimeError("no candidate read the board")
    return ArucoTuning(exposure_s=pick["exposure_s"], gain=pick["gain"], fps=pick["fps"], score_px=pick["score_px"],
                       detection_rate=pick["detection_rate"], rows=tuple(rows), speed_px_s=speed)
