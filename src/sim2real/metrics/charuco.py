"""A ChArUco board and its corners in a camera image: the measurement every belt routine is built on.

    from sim2real.metrics.charuco import BOARD, detect_corners
    ids, pixels = detect_corners(grey_image, BOARD)    # or None
    BOARD.object_points(ids)                           # the same corners on the board, (n, 3) m

The pose itself is solved in sim2real.fit.charuco_pose by the camera types' PnP (fit.camera_rgb.solve_pose).

WHY here (decision-package-layers-2026-11-10: metrics/ is "data in, numbers out, per modality"): an image in, corner pixels out;
the same call runs on a MuJoCo render and on a real D435 frame. cv2 is imported inside the functions (the 'vision' extra), so importing
sim2real.metrics never needs OpenCV. A peer lane owns the camera types (metrics/camera.py); this module is only the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

__all__ = ["CharucoSpec", "BOARD", "detect_corners"]


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

    def object_points(self, ids) -> np.ndarray:
        """The chessboard corners with these ids, in the board's frame (z = 0), (n, 3) m."""

        return np.asarray(self.board().getChessboardCorners(), float)[np.asarray(ids, int)]

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


def detect_corners(grey: np.ndarray, spec: CharucoSpec = BOARD) -> tuple[np.ndarray, np.ndarray] | None:
    """(ids, pixels) of the interpolated chessboard corners, or None."""

    corners, ids, _, _ = _detector(spec).detectBoard(np.ascontiguousarray(grey))
    if ids is None or len(ids) == 0:
        return None
    return ids.reshape(-1), corners.reshape(-1, 2)
