"""Each joint's lever arm to its rig's tool point, for the 1 mm tool gate's per-joint share (sim2real.rack_results, Job).

    lever = |d tool / d q_joint| at the workspace's typical pose (mm per rad): the plain lever for a serial joint, the Jacobian column's
            norm for a closed chain (the five-bar's C1 moves the tool through the loop). Typical pose = the median of the real runs' poses.

Writes src/sim2real/data/tool_levers_2026-11-11.json (one rig per call, merged). Each rig needs its own FK, so each runs in its environment:

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src:/home/bam/sim2real/sysid/examples /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/tools/tool_levers.py ur_wrist
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/bam_ws/src/dev/bam_fivebar uv run --isolated --no-project --with-editable /home/bam/bam_ws/src/core/mdp/agent/actor/trajectory_generation/five_bar_kin_dyn/src --with numpy python /home/bam/sim2real/tools/tool_levers.py fivebar
"""

from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "tool_levers_2026-11-11.json"
RACK = Path("/archive/datasets/bam_rig/rack_2026-11-10")
STEP = 1e-4  # rad, central difference


def wrist() -> dict:
    from ur_wrist_test_rig.rig import _tool  # the holder board's origin through the chain's FK (CAD rad -> m)

    poses = []  # the multi-joint runs (all three joints free) are the wrist's workspace; CAD degrees
    for trace in sorted(glob.glob(str(RACK / "ur_wrist/coverage/multi3/twin_traces/*/*.npz"))):
        data = np.load(trace)
        poses.append(np.column_stack([data[f"q_real_can{c}"] for c in (14, 15, 16)])[::20])
    typical = np.radians(np.median(np.vstack(poses), axis=0))
    levers = {}
    for k, can in enumerate((14, 15, 16)):
        up, down = typical.copy(), typical.copy()
        up[k] += STEP
        down[k] -= STEP
        levers[f"can{can}"] = float(np.linalg.norm(_tool(up) - _tool(down)) / (2 * STEP) * 1e3)
    return {"tool": "the holder board #4-7's origin (ur_wrist_test_rig.rig._tool, bam_ur_wrist WristModel)",
            "typical_pose_deg": {f"can{c}": round(math.degrees(v), 2) for c, v in zip((14, 15, 16), typical)},
            "typical_pose_source": "median of the multi3 runs' real poses (CAD), every 20th row", "lever_mm_per_rad": levers}


def fivebar() -> dict:
    from bam_fivebar.bench import BENCH
    from bam_fivebar.kinematics import forward_pose, tool_point

    def tool(j2: float, c1: float) -> np.ndarray:
        pose = forward_pose(BENCH, j2, c1)
        return np.array(tool_point(BENCH, pose.j2, pose.j3)) if pose else np.full(2, np.nan)

    poses = []
    for path in sorted(glob.glob(str(RACK / "fivebar_real/ladder_real_*/ladder/rungs/vertical/*.npz"))):
        if path.endswith("_approach.npz"):
            continue
        poses.append(np.load(path)["measured_motors"][::50])
    typical = np.median(np.vstack(poses), axis=0)
    levers = {}
    for k, joint in enumerate(("j2", "c1")):
        up, down = typical.copy(), typical.copy()
        up[k] += STEP
        down[k] -= STEP
        levers[joint] = float(np.linalg.norm(tool(*up) - tool(*down)) / (2 * STEP) * 1e3)
    return {"tool": "the tool point (L2 tip) through bam_fivebar's forward_pose + tool_point on BENCH",
            "typical_pose_deg": {j: round(math.degrees(v), 2) for j, v in zip(("j2", "c1"), typical)},
            "typical_pose_source": "median of every ladder_real_* rung's measured motors, every 50th tick",
            "lever_mm_per_rad": levers, "note": "C1's lever is |d tool / d c1| through the closed loop (J2 held)"}


def main() -> int:
    name = sys.argv[1]
    document = json.loads(OUT.read_text()) if OUT.exists() else {"schema": "sim2real.rack.tool_levers/1", "rigs": {}}
    document["rigs"][name] = {"ur_wrist": wrist, "fivebar": fivebar}[name]()
    OUT.write_text(json.dumps(document, indent=1) + "\n")
    print(json.dumps(document["rigs"][name], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
