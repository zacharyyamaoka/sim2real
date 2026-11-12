"""The UR wrist's target-vs-sim for CAN 14 and the holder's tool error by encoder FK at stops (sim2real.rack_results: Twin / Job checks,
Zach 2026-11-11 21:50: every gate from the joint encoders through FK; target vs sim checked first).

1. CAN 14's repeat campaign (ur_wrist/repeat_floor, the driven repeats) replayed on it5 under the MEASURED gravity, through the lane's own
   player (bam_ur_wrist_coverage.repeat_floor.replay + twin_for(14) + held_pose: the same call twin_scores.json was scored with); the
   settled rows (target at rest >= 0.3 s, rack_results.settled_mask) give twin-vs-target and real-vs-target.
2. The holder board #4-7 (bam_ur_wrist_coverage.multi.HOLDER_BOARD, WristModel.board_poses: the lane's own FK) at stops:
   - pick_sliding (the operating gains), single-joint runs: the moving joint's real / twin / target angle, the other two at the lane's rest
     pose (rig.REST_CAD_DEG; their own errors are not logged on these runs), board -> CAD by rig.board_to_cad;
   - multi3 (all three joints logged, CAD degrees, the it5 twin under the measured gravity): all three at once; a stop = every target at rest.
   FK runs at ~200 poses/s, so every STRIDE-th settled row is scored.

Writes src/sim2real/data/ur_wrist_twin_extra_2026-11-11.json. Run in the coverage lane's environment, on bam_ws main's code:

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/bam_ws/src/dev/bam_ur_wrist_coverage:/home/bam/sim2real/src /home/bam/bam_ws-worktrees/ur-wrist-coverage/src/dev/bam_ur_wrist_coverage/.venv/bin/python /home/bam/sim2real/tools/wrist_twin_extra.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from sim2real.rack_results import WRIST, WRIST_TWIN_CACHE, settled_mask

OUT = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "ur_wrist_twin_extra_2026-11-11.json"
STRIDE = 10        # pick_sliding single-joint rows (2,000+ settled rows a joint)
STRIDE_MULTI = 1   # multi3: every rested row (few: the tapes rarely stop)


def _r(values) -> list[float]:
    return [round(float(v), 5) for v in values]


def can14_campaign() -> dict:
    from bam_ur_wrist_coverage import repeat_floor

    pose = repeat_floor.held_pose()
    params = repeat_floor.twin_for(14)
    runs = []
    for (digest, trajectory, mode, can), group in sorted(repeat_floor.load_groups().items()):
        if can != 14 or mode != "driven":
            continue
        for name, run, _meta in sorted(group, key=lambda item: item[0]):
            twin_q = repeat_floor.replay(run, params, pose)
            t = np.asarray(run.t, float) - float(run.t[0])
            keep = settled_mask(t, run.q_target)
            runs.append({"run": name, "trajectory": trajectory, "file": str(run.source), "settled_rows": int(keep.sum()),
                         "twin_settled_deg": _r(np.degrees(np.abs(twin_q[keep] - run.q_target[keep]))),
                         "real_settled_deg": _r(np.degrees(np.abs(run.q[keep] - run.q_target[keep])))})
    return {"twin": params.label, "held_pose_cad_deg": np.degrees(pose).round(2).tolist(), "runs": runs,
            "player": "bam_ur_wrist_coverage.repeat_floor.replay (twin_for(14), held_pose), as twin_scores.json"}


_MODEL = None


def _board(q_cad: np.ndarray) -> np.ndarray:
    global _MODEL
    from bam_ur_wrist_coverage import multi, rig
    from bam_ur_wrist.model import WristModel

    if _MODEL is None:
        _MODEL = WristModel(rig.load_bundle())
    return _MODEL.board_poses(q_cad)[multi.HOLDER_BOARD][:3, 3]


def _single(job: tuple[str, str]) -> dict | None:
    """One pick_sliding single-joint run: tool errors (mm) at every STRIDE-th settled row, target / real / twin."""
    from bam_ur_wrist_coverage import rig

    session, name = job
    session_name, stem = name.split("/")
    can = int(re.match(r"can(\d+)_", session_name).group(1))
    data = np.load(Path(session) / "runs" / f"{stem}.npz")
    trace = WRIST_TWIN_CACHE / f"pick_sliding__{session_name}__{stem}.npz"
    sim = np.load(trace) if trace.exists() else None
    t = data["t"] - data["t"][0]
    rows = np.flatnonzero(settled_mask(t, data["q_target"]) & np.isfinite(data["q"]))[::STRIDE]
    rest = np.array(rig.rest_cad_rad())

    def tool(board_rad: float) -> np.ndarray:
        q = rest.copy()
        q[rig.AXIS[can]] = rig.board_to_cad(can, board_rad)
        return _board(q)

    out = {"can": can, "run": name, "target_real_mm": [], "target_sim_mm": [], "sim_real_mm": []}
    same = sim is not None and sim["q"].shape == data["q"].shape
    for k in rows:
        target, real = tool(data["q_target"][k]), tool(data["q"][k])
        out["target_real_mm"].append(1e3 * np.linalg.norm(real - target))
        if same and np.isfinite(sim["q"][k]):
            twin = tool(sim["q"][k])
            out["target_sim_mm"].append(1e3 * np.linalg.norm(twin - target))
            out["sim_real_mm"].append(1e3 * np.linalg.norm(twin - real))
    return {key: (_r(v) if isinstance(v, list) else v) for key, v in out.items()}


def _multi(path: str) -> dict:
    """One multi3 run (all three joints, CAD degrees): tool errors (mm) where every target rests."""
    data = np.load(path)
    t = data["t"] - data["t"][0]
    cans = (14, 15, 16)
    target = np.radians(np.column_stack([data[f"q_target_can{c}"] for c in cans]))
    real = np.radians(np.column_stack([data[f"q_real_can{c}"] for c in cans]))
    twin = np.radians(np.column_stack([data[f"q_twin_can{c}"] for c in cans]))
    ok = settled_mask(t, target) & np.isfinite(real).all(axis=1) & np.isfinite(twin).all(axis=1)
    out = {"run": str(Path(path).relative_to(WRIST)), "target_real_mm": [], "target_sim_mm": [], "sim_real_mm": []}
    for k in np.flatnonzero(ok)[::STRIDE_MULTI]:
        a, b, c = _board(target[k]), _board(real[k]), _board(twin[k])
        out["target_real_mm"].append(1e3 * np.linalg.norm(b - a))
        out["target_sim_mm"].append(1e3 * np.linalg.norm(c - a))
        out["sim_real_mm"].append(1e3 * np.linalg.norm(c - b))
    return {key: (_r(v) if isinstance(v, list) else v) for key, v in out.items()}


def main() -> int:
    summary = json.loads((WRIST / "summary_real.json").read_text())
    last = summary["trend"]["order"][-1]
    jobs = [(row["session"], row["name"]) for row in summary["iterations"][last]["scored"] if Path(row["session"]).parent.name == "pick_sliding"]
    multi3 = sorted(str(p) for p in (WRIST / "multi3" / "twin_traces").glob("*/*.npz"))
    with Pool(12) as pool:
        single = pool.map(_single, jobs)
        multis = pool.map(_multi, multi3)
    document = {"schema": "sim2real.rack.ur_wrist_twin_extra/1", "date": "2026-11-11", "settled_after_s": 0.3, "stride": STRIDE, "stride_multi3": STRIDE_MULTI,
                "can14_campaign": can14_campaign(),
                "tool": {"board": "holder board #4-7 (bam_ur_wrist_coverage.multi.HOLDER_BOARD, WristModel.board_poses)",
                         "pick_sliding": {"held": "the other two joints at rig.REST_CAD_DEG (not logged on single-joint runs)",
                                          "twin": "it5 replays (~/.cache/bam_sim2real_present/wrist_it5)", "runs": single},
                         "multi3": {"twin": "the multi3 traces' own twin (it5 + the measured gravity)", "runs": multis}}}
    OUT.write_text(json.dumps(document) + "\n")
    for name, runs in (("pick_sliding", single), ("multi3", multis)):
        for key in ("target_real_mm", "target_sim_mm", "sim_real_mm"):
            values = [v for r in runs for v in r[key]]
            print(name, key, len(values), f"median {np.median(values):.3f} p95 {np.percentile(values, 95):.3f}" if values else "-")
    for r in document["can14_campaign"]["runs"]:
        print("can14", r["run"], r["settled_rows"], f"twin {np.median(r['twin_settled_deg']):.3f} real {np.median(r['real_settled_deg']):.3f}"
              if r["settled_rows"] else "")
    print("wrote", OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
