"""The five-bar's 16 dwell holds (dwell_real_identified_035048, the identified lumped comp) replayed on the AFTER twin, for the Twin and Job
checks' target vs sim (Zach 2026-11-11 21:50: the controller's own gate, checked first) and the tool's sim vs real, all by encoders + FK.

The holds run through the real lane's own code, read-only from bam_ws claude/fivebar-guard (bam_rack_twin.hardware.fivebar_homed.dwell_holds:
per pose a joint move under gravity_ff + the host's Coulomb feed-forward, then a 3 s hold at kd x 4, the settled reading = the median of
the hold's last DWELL_SETTLED_S), on the record's settings (fivebar_homed.json: hold_kd_scale 4.0, Coulomb FF 0.70 / 0.78 N.m, no
settle integrator, the identified lumped comp) from the homed home pose. The twin is bam_fivebar.refit.twin_plant with the tick-clock
refit's best (refit_breakdown_123729: Coulomb 0.74, viscous 0.1, armature x1, delay 2.5 ms) and the mass ID's theta, the record's board
gains (J2 kp 144 / kd 8, C1 kp 200 / kd 4: the same at the dwell's 03:50Z as in the newest config), the way refit --evaluate builds it.
Tool point: bam_fivebar.kinematics forward_pose + tool_point on the bench (the dwell json's joint_fk_cad_lever_mm).

Writes src/sim2real/data/fivebar_dwell_twin_2026-11-11.json:

    PYTHONDONTWRITEBYTECODE=1 env -u VIRTUAL_ENV MUJOCO_GL=egl /home/bam/bam_ws-worktrees/fivebar-guard/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/tools/fivebar_dwell_twin.py
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
RACK = Path("/archive/datasets/bam_rig/rack_2026-11-10/fivebar_real")
RUN = RACK / "dwell_real_identified_035048"
REFIT = RACK / "refit_breakdown_123729" / "refit.json"
REAL = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "fivebar_dwell_identified_2026-11-11.json"
OUT = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "fivebar_dwell_twin_2026-11-11.json"


def main() -> int:
    from bam_fivebar.kinematics import forward_pose, tool_point
    from bam_fivebar.massid import identified_model, load_gravity_parameters, massid_poses
    from bam_fivebar.refit import TwinParams, twin_plant
    from bam_fivebar.speed_ladder import load_identified
    from bam_rack_twin.hardware import fivebar_homed as fh

    record = json.loads((RUN / "fivebar_homed.json").read_text())
    gravity = Path(record["dwell_comp"]["gravity"])
    coulomb = tuple(record["dwell_comp"]["coulomb_ff_nm"])
    homed = fh.Homed.load(Path(record["homed"]))
    from bam_rack_twin.hardware.fivebar_run import bench_real

    bench = bench_real()
    poses = massid_poses(bench, j2_min_deg=fh.MASSID_J2_MIN_DEG)
    planned = np.array([[math.degrees(v) for v in (p.j2, p.j3, p.c1)] for p in poses])
    assert np.allclose(planned, record["massid_poses_deg"], atol=1e-6), "the poses differ from the record's"
    plant_bench = load_identified(gravity, bench)[0]
    theta = np.asarray(load_gravity_parameters(gravity).theta)
    params = TwinParams(**json.loads(REFIT.read_text())["best"])
    board_gains = fh.record_board_gains(bench, fh.FIVEBAR_RECORD)
    start = forward_pose(bench, float(homed.home[0]), float(homed.home[1]))
    plant = twin_plant(plant_bench, params, start, theta=theta, board_gains=board_gains)
    model = identified_model(bench, load_gravity_parameters(gravity))
    result = fh.dwell_holds(plant, plant.servo_map_truth, bench, poses, model, hold_kd_scale=float(record["hold_kd_scale"]), coulomb_ff_nm=coulomb)

    def tool_mm(j2_deg: float, c1_deg: float) -> np.ndarray:
        pose = forward_pose(bench, math.radians(j2_deg), math.radians(c1_deg))
        return np.array(tool_point(bench, pose.j2, pose.j3)) * 1e3 if pose else np.full(2, np.nan)

    real_rows = {row["pose"]: row for row in json.loads(REAL.read_text())["rows"]}
    rows = []
    for hold in result["holds"]:
        real = real_rows[hold["pose"]]
        commanded = np.asarray(hold["commanded_deg"])
        sim = np.asarray(hold["settled_deg"])
        real_motors = commanded + np.asarray(real["motor_error_deg"])
        target_tool, sim_tool, real_tool = tool_mm(*commanded), tool_mm(*sim), tool_mm(*real_motors)
        rows.append({"pose": hold["pose"], "commanded_deg": commanded.tolist(), "sim_error_deg": hold["error_deg"],
                     "real_error_deg": real["motor_error_deg"], "sim_minus_real_deg": (sim - real_motors).tolist(),
                     "target_sim_tool_mm": float(np.linalg.norm(sim_tool - target_tool)),
                     "sim_real_tool_mm": float(np.linalg.norm(sim_tool - real_tool)),
                     "target_real_tool_mm": float(np.linalg.norm(real_tool - target_tool))})
    document = {"schema": "sim2real.rack.fivebar_dwell_twin/1", "date": "2026-11-11", "run": str(RUN), "twin": params.label(),
                "twin_source": str(REFIT), "gravity": str(gravity), "coulomb_ff_nm": list(coulomb), "hold_kd_scale": record["hold_kd_scale"],
                "board_gains": None if board_gains is None else [{"kp": g.kp, "kd": g.kd} for g in board_gains],
                "player": "bam_rack_twin.hardware.fivebar_homed.dwell_holds on bam_fivebar.refit.twin_plant (bam_ws claude/fivebar-guard, read-only)",
                "settled_s": fh.DWELL_SETTLED_S, "rows": rows}
    OUT.write_text(json.dumps(document, indent=1) + "\n")
    for key in ("target_sim_tool_mm", "sim_real_tool_mm", "target_real_tool_mm"):
        values = [r[key] for r in rows]
        print(key, f"median {np.median(values):.2f} mm, p95 {np.percentile(values, 95):.2f}")
    for k, joint in enumerate(("j2", "c1")):
        print(joint, "sim |err| median", f"{np.median([abs(r['sim_error_deg'][k]) for r in rows]):.3f}°",
              "real", f"{np.median([abs(r['real_error_deg'][k]) for r in rows]):.3f}°",
              "sim-real", f"{np.median([abs(r['sim_minus_real_deg'][k]) for r in rows]):.3f}°")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
