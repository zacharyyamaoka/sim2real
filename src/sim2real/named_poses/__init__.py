"""A robot's saved positions, by name: ``named_pose("ready")`` - sim2real's copy of what the robot description publishes.

The description owns the poses: bam_ws ``bam_cad_descriptions/descriptions/bam_fb_v2.py`` declares them (robot_msgs ``NamedPose``,
MoveIt's SRDF group_state with its reason) and generates ``bam_fb_v2.named_poses.json``. sim2real imports nothing of bam_ws, so the same
file is kept here as ``<robot>.json`` (generated, never edited: robot_msgs refuses a pose whose digest the file misstates), and bam_ws'
``tests/test_named_poses.py`` fails while this copy differs from the description's. After a pose moves in the description:

    cd ~/bam_ws/src/dev/bam_cad_descriptions
    env -u VIRTUAL_ENV uv run python -m bam_cad_descriptions.named_poses --write

WHY by name (Zach, 2026-11-15): "all the code should not be like referencing an exact position, but should rather be like accessing that
saved position by name, so that in the future you can always just change it easily and it continues to work." PEP 0056 in bam_ws.

Light on purpose (robot_msgs + the standard library, no layer): J1's home on the rack (``sim.homing.j1_home``) reads READY's J1 from here
inside the powered deployment venv.
"""

from __future__ import annotations

import functools
import math
from pathlib import Path

from robot_msgs.manipulation import NamedPose, find_named_pose, named_poses_from_json

HERE = Path(__file__).resolve().parent
ROBOT = "bam_fb_v2"  # the full arm: five-bar + UR wrist + crab claw (cad-exporter 09374d7)
FIVEBAR = ("revolute_6", "revolute_7")  # J2, C1 (URDF names)
WRIST = ("revolute_11", "revolute_14", "revolute_17")  # W1, W2, W3
# Craig = URDF + offset for the five-bar's two drives (bam_fb_test_rig.gravity.CraigMap on the bam_fb_v2 twin): the description's
# CRAIG_OFFSET_DEG; bam_ws tests/test_named_poses_1115.py holds the copies equal
CRAIG_OFFSET_DEG = {"revolute_6": 90.0, "revolute_7": 137.45861811322055}


@functools.cache
def named_poses(robot: str = ROBOT) -> tuple[NamedPose, ...]:
    """Every saved position the robot's description publishes (read once per process)."""

    return named_poses_from_json((HERE / f"{robot}.json").read_text())


def named_pose(name: str, group: str | None = None, robot: str = ROBOT) -> NamedPose:
    """The saved position called ``name`` (``"ready"``); an unknown name raises KeyError listing those there are."""

    return find_named_pose(named_poses(robot), name, group)


def fivebar_craig_deg(pose: NamedPose) -> tuple[float, float]:
    """``pose``'s five-bar drives (J2, C1) in Craig degrees: URDF degrees + CRAIG_OFFSET_DEG (C1 on the branch the pose is written on)."""

    return tuple(math.degrees(pose.position_of(joint)) + CRAIG_OFFSET_DEG[joint] for joint in FIVEBAR)


def wrist_deg(pose: NamedPose) -> tuple[float, float, float]:
    """``pose``'s wrist (W1, W2, W3) in degrees."""

    return tuple(math.degrees(pose.position_of(joint)) for joint in WRIST)


__all__ = ["CRAIG_OFFSET_DEG", "FIVEBAR", "ROBOT", "WRIST", "fivebar_craig_deg", "named_pose", "named_poses", "wrist_deg"]
