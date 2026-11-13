"""Evidence for mujoco_plant.resolve_mesh_mode: recover_first+tview_v2 from the bowl on the B1 twin (gear_backlash's dead zone) at the
twin's own 0.25 ms step and at 1/2, 1/4 and 1/8 of it - outcome, the largest mesh torque each drive carried, and the zero errors.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra homing --extra sim python /home/bam/sim2real/tools/homing_b1_timestep.py --out /home/bam/sim2real/src/sim2real/data/homing_fivebar_b1_timestep_2026-11-12.json

The plant's timestep is set by hand here (resolve_mesh_mode is what the bench uses: 1/4); one process, one episode at a time.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path


def run(divisor: int, procedure: str, start_name: str) -> dict:
    from sim2real.sim.homing import mujoco_plant
    from sim2real.sim.homing.bench import named_rests, prior_for
    from sim2real.sim.homing.geometry import DRIVES, ROLE, FivebarGeometry
    from sim2real.sim.homing.mujoco_bench import run_one

    geometry = FivebarGeometry()
    prior = prior_for(geometry)
    start = {s.name: s for s in named_rests(geometry, prior)}[start_name]
    mujoco_plant.RigCache._rigs.pop("B1", None)
    rig = mujoco_plant.RigCache.get("B1")
    resolved = float(rig.model.opt.timestep)
    twin_dt = 0.00025
    rig.model.opt.timestep = twin_dt / divisor
    plant = mujoco_plant.MujocoRigPlant("B1")
    wrapped = plant.rig.backlash
    peaks = {name: 0.0 for name in wrapped.joints}
    before = wrapped.before_step

    def hooked(data):
        before(data)
        for name, joint in wrapped.joints.items():
            peaks[name] = max(peaks[name], abs(float(data.qfrc_applied[joint.gap_dof])))

    wrapped.before_step = hooked
    t0 = time.time()
    episode = run_one(procedure, plant, start, prior, geometry, "mujoco · B1")
    omega = max(math.sqrt(j.spec.mesh_stiffness_nm_per_rad / j.effective_inertia_kg_m2) for j in wrapped.joints.values())
    rig.model.opt.timestep = resolved
    return {"divisor": divisor, "dt_us": twin_dt / divisor * 1e6, "omega_dt": omega * twin_dt / divisor,
            "outcome": episode.record.outcome, "peak_mesh_torque_nm": {ROLE[j]: round(peaks[j], 1) for j in DRIVES},
            "zero_error_deg": {ROLE[j.joint]: j.zero_error_deg for j in episode.record.joints}, "wall_s": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--procedure", default="recover_first+tview_v2")
    parser.add_argument("--start", default="bowl")
    parser.add_argument("--divisors", type=int, nargs="*", default=[1, 2, 4, 8])
    args = parser.parse_args(argv)
    rows = []
    for divisor in args.divisors:
        rows.append(run(divisor, args.procedure, args.start))
        print(json.dumps(rows[-1]))
    args.out.write_text(json.dumps({"schema": "sim2real_homing_b1_timestep/1", "procedure": args.procedure, "start": args.start,
                                    "model": "B1 (gear_backlash deadzone)", "twin_dt_s": 0.00025, "rows": rows}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
