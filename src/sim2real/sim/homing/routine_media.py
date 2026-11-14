"""The homing routine's media: an episode re-run with its trace (deterministic: same plant, start, prior and plan), rendered as a video with
the belt drawn (fullarm_media), a still, and a Rerun recording (tools/homing_routine_rrd.py, in data_recorder's venv) - sim only.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m sim2real.sim.homing.routine_media --episodes /home/bam/sim2real/src/sim2real/data/homing_routine_media_2026-11-13.json --out-dir /home/bam/bam_ws/reports/media/homing-routine-2026-11-13

``--episodes`` lists what to film: [{"name", "row", "environment", "cell_index"}, ...]. Each gets <name>.mp4 / .gif / .jpg / .rrd in
``--out-dir`` and an index (media.json) the report and the W&B logger read.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from ... import paths as _paths
from . import routine_check as rc
from . import routine_ruler as ruler

RRD_PYTHON = _paths.DATA_RECORDER / ".venv" / "bin" / "python"
RRD_TOOL = Path(__file__).resolve().parents[4] / "tools" / "homing_routine_rrd.py"
STICK_BODIES = ("shoulder", "l1", "l2", "hard_stop", "hard_stop_2", "hard_stop_3", "moving_finger")
SPEEDUP = 4.0
FPS = 30


def traced(row: str, environment: str, cell_index: int, *, every: int) -> tuple[dict, object]:
    """The row's episode with its trace (qpos included) and the plant's model."""
    from .fullarm_plant import FullArmHomingPlant  # noqa: PLC0415

    cell = ruler.grid_cells()[cell_index] if cell_index >= 0 else rc.CALIBRATION_START
    job = {"cell_index": cell_index, "cell": cell, "environment": environment, "rows": [row]}
    tables = None
    if rc.needs_table(row):
        tables = {k: v["table"] for k, v in json.loads(Path(os.environ["HOMING_ROUTINE_TABLES"]).read_text()).items() if v.get("table")}
    out = rc.run_job(job, tables=tables, branch=False, trace_every=every, plant_overrides={"log_qpos": True}, keep_trace=True)
    model = FullArmHomingPlant(**rc.plant_kwargs(environment)).rig.model
    return out[0], model


def stick(model, qpos_rows) -> list:
    """Each traced pose as the arm's stick figure: the world positions (m) of STICK_BODIES' origins."""
    import mujoco  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    data = mujoco.MjData(model)
    ids = [model.body(name).id for name in STICK_BODIES]
    out = []
    for q in qpos_rows:
        data.qpos[:] = np.asarray(q, dtype=float)
        mujoco.mj_kinematics(model, data)
        out.append([[round(float(v), 4) for v in data.xpos[i]] for i in ids])
    return out


def write_rrd(report: dict, model, path: Path) -> Path | None:
    from .fullarm_plant import BELT_CENTRE_M, BELT_HALF_M  # noqa: PLC0415

    trace = report["trace"]
    payload = {k: trace[k] for k in ("t", "link_deg", "effort_nm", "step", "self_contact", "belt") if k in trace}
    payload["stick_m"] = stick(model, trace["qpos"]) if trace.get("qpos") else None
    payload["belt_box"] = {"centre": [BELT_CENTRE_M[0], BELT_CENTRE_M[1], -BELT_HALF_M[2]], "half": list(BELT_HALF_M)}
    payload["recording_id"] = report.get("key")
    scratch = path.with_suffix(".trace.json")
    scratch.write_text(json.dumps(payload))
    try:
        subprocess.run(["env", "-u", "VIRTUAL_ENV", str(RRD_PYTHON), "-I", str(RRD_TOOL), str(scratch), str(path)], check=True,
                       capture_output=True, text=True, timeout=600)
    except (subprocess.SubprocessError, OSError) as error:
        print(f"rrd failed for {path.name}: {error}", flush=True)
        return None
    finally:
        scratch.unlink(missing_ok=True)
    return path


def film(item: dict, out_dir: Path) -> dict:
    from PIL import Image  # noqa: PLC0415

    from .fullarm_media import encode, iter_frames  # noqa: PLC0415

    every = max(1, round(SPEEDUP / (FPS * 0.01)))
    report, model = traced(item["row"], item["environment"], int(item["cell_index"]), every=every)
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / f"{item['name']}.mp4"
    # WHY this camera (still_test, 2026-11-13): the default frames the shoulder; with the belt drawn the whole arm and the belt fit here
    times = report["trace"]["t"]
    at = item.get("still_s")
    pick = len(times) // 2 if at is None else min(range(len(times)), key=lambda k: abs(times[k] - at))
    still = mp4.with_suffix(".jpg")
    count = 0

    def frames():
        nonlocal count
        for k, frame in enumerate(iter_frames(model, report["trace"], belt=True, azimuth=120.0, elevation=-14.0, distance=1.55,
                                              lookat=(0.28, 0.0, 0.28))):
            if k == pick:
                Image.fromarray(frame).save(still, quality=85)
            count += 1
            yield frame

    files = encode(frames(), mp4)
    rrd = write_rrd(report, model, mp4.with_suffix(".rrd"))
    report.pop("trace", None)
    return {**item, **files, "still": str(still), "rrd": None if rrd is None else str(rrd), "frames": count, "speedup": SPEEDUP,
            "report": {k: report.get(k) for k in ("outcome", "outcome_class", "covered", "time_s", "zero_error_deg", "belt_drag_s",
                                                   "belt_after_liftoff_ticks", "self_contact_pairs", "witness_deg", "notes", "start")}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--plans", type=Path, default=Path.home() / ".cache" / "sim2real" / "homing_routine_plans.pkl")
    args = parser.parse_args(argv)
    items = json.loads(args.episodes.read_text())
    rows = sorted({item["row"] for item in items})
    rc.PLANS.update(rc.preplan_file(rows, args.plans))
    index_path = args.out_dir / "media.json"
    index = json.loads(index_path.read_text()) if index_path.is_file() else {}
    for item in items:
        if item["name"] in index and Path(index[item["name"]].get("mp4", "")).is_file() and not item.get("redo"):
            continue
        index[item["name"]] = film(item, args.out_dir)
        index_path.write_text(json.dumps(index, indent=1, default=str))
        print(item["name"], index[item["name"]]["report"]["outcome_class"], index[item["name"]].get("mp4_bytes"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
