"""A ChArUco board's pose in one image: metrics.charuco's detection, then the camera lane's PnP (fit.camera_rgb.solve_pose).

    from sim2real.fit.charuco_pose import board_pose
    pose = board_pose(grey_image, BOARD, intrinsics)     # BoardPose | None; intrinsics: fit.camera_rgb.Intrinsics
    pose.camera_from_board, pose.centre_m, pose.reprojection_px

WHY here and not in metrics/charuco.py (2026-11-11, the coordinator: "swap any duplicate pose math for theirs"): the belt routines first
solved PnP with cv2.solvePnP inside metrics/; the camera types now own one pose solver (camera_rgb.solve_pose: the homography's pose
refined by fit.least_squares) and one projection (camera_rgb.project), both in fit/. metrics/ may not import fit/, so detection stays in
metrics.charuco and the pose is solved here, by their code, with their reprojection metric (metrics.camera.reprojection_rms).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sim2real.fit.camera_rgb import Intrinsics, project, rodrigues, solve_pose
from sim2real.metrics.camera import reprojection_rms
from sim2real.metrics.charuco import BOARD, CharucoSpec, detect_corners

__all__ = ["BoardPose", "board_pose"]


@dataclass(frozen=True)
class BoardPose:
    camera_from_board: np.ndarray   # 4 x 4
    n_corners: int
    reprojection_px: float          # per-axis RMS (metrics.camera.reprojection_rms)
    corner_ids: np.ndarray
    corner_px: np.ndarray           # (n, 2)
    spec: CharucoSpec = BOARD

    @property
    def centre_m(self) -> np.ndarray:
        """The board centre in the camera frame (a lever arm from a corner would couple rotation noise into position)."""

        return self.camera_from_board[:3, :3] @ self.spec.centre_m + self.camera_from_board[:3, 3]

    def point(self, board_xyz: np.ndarray) -> np.ndarray:
        return (self.camera_from_board[:3, :3] @ np.asarray(board_xyz, float).T).T + self.camera_from_board[:3, 3]


def board_pose(grey: np.ndarray, spec: CharucoSpec, intrinsics: Intrinsics, min_corners: int = 6) -> BoardPose | None:
    found = detect_corners(grey, spec)
    if found is None or len(found[0]) < min_corners:
        return None
    ids, px = found
    obj = spec.object_points(ids)
    rvec, tvec = solve_pose(intrinsics, obj, px)
    rms = reprojection_rms(project(intrinsics, rvec, tvec, obj), px)
    t = np.eye(4)
    t[:3, :3] = rodrigues(rvec)
    t[:3, 3] = tvec
    return BoardPose(t, len(ids), rms, ids, px, spec)
