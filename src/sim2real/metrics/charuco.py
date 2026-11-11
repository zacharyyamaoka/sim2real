"""A ChArUco board's pose in a camera image: the measurement every belt routine is built on.

    from sim2real.metrics.charuco import BOARD, board_pose
    pose = board_pose(grey_image, BOARD, K)        # BoardPose | None
    pose.camera_from_board, pose.centre_m, pose.reprojection_px

WHY here (decision-package-layers-2026-11-10: metrics/ is "data in, numbers out, per modality"): an image in, a pose and its residual out;
the same call runs on a MuJoCo render and on a real D435 frame. cv2 is imported inside the functions (the 'vision' extra), so importing
sim2real.metrics never needs OpenCV. A peer lane owns the camera types (metrics/camera.py); this module is only the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

__all__ = ["CharucoSpec", "BoardPose", "BOARD", "detect_corners", "board_pose"]


@dataclass(frozen=True)
class CharucoSpec:
    squares_x: int = 7
    squares_y: int = 5
    square_m: float = 0.040
    marker_m: float = 0.030
    dictionary: str = "DICT_5X5_100"
    thickness_m: float = 0.003     # 3 mm aluminium composite (ACM)

    @property
    def size_m(self) -> tuple[float, float]:
        return self.squares_x * self.square_m, self.squares_y * self.square_m

    @property
    def centre_m(self) -> np.ndarray:
        """The board's centre in its own frame (OpenCV's board frame starts at a corner)."""

        w, h = self.size_m
        return np.array([w / 2, h / 2, 0.0])

    def board(self):
        return _board(self)

    def image(self, px_per_m: float = 5000.0) -> np.ndarray:
        w, h = self.size_m
        return self.board().generateImage((int(round(w * px_per_m)), int(round(h * px_per_m))), marginSize=0, borderBits=1)


BOARD = CharucoSpec()


@lru_cache(maxsize=8)
def _board(spec: CharucoSpec):
    import cv2

    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, spec.dictionary))
    return cv2.aruco.CharucoBoard((spec.squares_x, spec.squares_y), spec.square_m, spec.marker_m, dictionary)


@lru_cache(maxsize=8)
def _detector(spec: CharucoSpec):
    import cv2

    return cv2.aruco.CharucoDetector(_board(spec))


@dataclass(frozen=True)
class BoardPose:
    camera_from_board: np.ndarray   # 4 x 4
    n_corners: int
    reprojection_px: float          # RMS
    corner_ids: np.ndarray
    corner_px: np.ndarray           # (n, 2)
    spec: CharucoSpec = BOARD

    @property
    def centre_m(self) -> np.ndarray:
        """The board centre in the camera frame (a lever arm from a corner would couple rotation noise into position)."""

        return self.camera_from_board[:3, :3] @ self.spec.centre_m + self.camera_from_board[:3, 3]

    def point(self, board_xyz: np.ndarray) -> np.ndarray:
        return (self.camera_from_board[:3, :3] @ np.asarray(board_xyz, float).T).T + self.camera_from_board[:3, 3]


def detect_corners(grey: np.ndarray, spec: CharucoSpec = BOARD) -> tuple[np.ndarray, np.ndarray] | None:
    """(ids, pixels) of the interpolated chessboard corners, or None."""

    corners, ids, _, _ = _detector(spec).detectBoard(np.ascontiguousarray(grey))
    if ids is None or len(ids) == 0:
        return None
    return ids.reshape(-1), corners.reshape(-1, 2)


def board_pose(grey: np.ndarray, spec: CharucoSpec, camera_matrix: np.ndarray, distortion: np.ndarray | None = None,
               min_corners: int = 6) -> BoardPose | None:
    import cv2

    found = detect_corners(grey, spec)
    if found is None or len(found[0]) < min_corners:
        return None
    ids, px = found
    obj = spec.board().getChessboardCorners()[ids].astype(np.float64)
    dist = np.zeros(5) if distortion is None else np.asarray(distortion, float)
    ok, rvec, tvec = cv2.solvePnP(obj, px.astype(np.float64), np.asarray(camera_matrix, float), dist, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None
    rvec, tvec = cv2.solvePnPRefineLM(obj, px.astype(np.float64), np.asarray(camera_matrix, float), dist, rvec, tvec)
    projected, _ = cv2.projectPoints(obj, rvec, tvec, np.asarray(camera_matrix, float), dist)
    rms = float(np.sqrt(np.mean(np.sum((projected.reshape(-1, 2) - px) ** 2, axis=1))))
    t = np.eye(4)
    t[:3, :3] = cv2.Rodrigues(rvec)[0]
    t[:3, 3] = tvec.reshape(3)
    return BoardPose(t, len(ids), rms, ids, px, spec)
