"""Extract the five-bar home button's REAL runs (bam_rack_twin ``fivebar_home -f``) into one small JSON the homing bench replays.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 python3 /home/bam/sim2real/tools/extract_home_button_real.py

Reads, per run, its receipt (``fivebar_homed.json``: the start reading, the homed map's servo map, each sequence's steps with outcome and
seconds, where it ended) and its tick rows (``leg_rows.npy``: board position / velocity / torque every 10 ms), and writes, in the arm's
Craig drive angles (deg; joint = sign x board + offset, the homed map's servo map): the start, each step's end pose read off the rows at
the step's end time (the steps' rounded seconds summed from the first row), the end, and the trace decimated to 50 ms for the page.

WHY these three runs: they are every real ``stage: home`` receipt that ran to ``complete`` (the others under
``/archive/datasets/bam_rig/rack_2026-11-10/fivebar_real/home_real_*`` were refused before any motion, or tripped on the bus); one from
the closure fold (settle + walk), one from a working-branch rest 9 / 20 deg off home (walk only), one from home (hold only).

WHY the comp per run: the home button's walk carries the gravity torque at each waypoint. bam_ws 2ec4dd02a (2026-11-12 05:20Z) made the
identified lumped model the default; the two runs before it (t1 22:27Z, repeat-floor 01:20Z) walked on ``ControllerModel.for_bench`` (the
nominal model), which their receipts record as no ``comp`` key.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

RUNS_DIR = Path("/archive/datasets/bam_rig/rack_2026-11-10/fivebar_real")
RUNS = ("home_real_222746_t1", "home_real_after_gate1_085634", "home_real_repeatfloor_012056")
OUT = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "fivebar_home_button_real_2026-11-12.json"
DECIMATE = 5


def main() -> int:
    runs = []
    for name in RUNS:
        folder = RUNS_DIR / name
        receipt = json.loads((folder / "fivebar_homed.json").read_text())
        if receipt.get("stage") != "home" or receipt.get("twin") or receipt.get("result") != "complete":
            raise SystemExit(f"{name}: not a complete real home run")
        sign = np.asarray(receipt["servo_map"]["sign"], dtype=float)
        offset = np.asarray(receipt["servo_map"]["offset_rad"], dtype=float)
        rows = np.load(folder / "leg_rows.npy")
        t = rows[:, 0] - rows[0, 0]
        craig = np.degrees(sign * rows[:, 1:3] + offset)
        rate = np.degrees(sign * rows[:, 3:5])
        torque = sign * rows[:, 5:7]
        attempt = receipt["home"]["attempts"]
        if len(attempt) != 1:
            raise SystemExit(f"{name}: {len(attempt)} attempts (the replay takes one)")
        attempt = attempt[0]
        clock = 0.0
        sequences = []
        for sequence in attempt["sequences"]:
            steps = []
            for step in sequence["steps"]:
                clock += float(step["seconds"])
                k = int(np.argmin(np.abs(t - clock)))
                steps.append({"step": step["step"], "outcome": step["outcome"], "seconds": step["seconds"], "end_t_s": round(clock, 2),
                              "end_deg": craig[k].round(3).tolist()})
            sequences.append({"sequence": sequence["sequence"], "status": sequence["status"], "end_deg": sequence["end_deg"],
                              "peak_speed_deg_s": sequence["peak_speed_deg_s"], "steps": steps})
        comp = receipt.get("comp")
        runs.append({
            "run": name,
            "utc": receipt["utc"],
            "receipt": str(folder / "fivebar_homed.json"),
            "homed": receipt["homed"],
            "comp": "nominal" if comp is None else Path(comp).name,
            "servo_map": receipt["servo_map"],
            "j1_board_rad": receipt["start"]["j1_rad"],
            "start_deg": [round(v, 4) for v in receipt["start"]["joint_deg"]],
            "home_deg": attempt["home_deg"],
            "start_kind": attempt["start"]["kind"],
            "settled": attempt.get("settled"),
            "path": attempt["path"],
            "end_deg": attempt["end_deg"],
            "off_home_deg": attempt["off_home_deg"],
            "seconds": round(float(t[-1]), 3),
            "rows": int(len(t)),
            "sequences": sequences,
            "trace": {"every_s": round(0.01 * DECIMATE, 3), "t": t[::DECIMATE].round(3).tolist(),
                      "craig_deg": craig[::DECIMATE].round(3).tolist(), "rate_deg_s": rate[::DECIMATE].round(2).tolist(),
                      "torque_nm": torque[::DECIMATE].round(3).tolist()},
        })
    payload = {"schema": "sim2real_home_button_real/1", "source": str(RUNS_DIR), "frame": "Craig drive angles (deg), the homed map's servo map",
               "why": __doc__.split("\n\n")[2].replace("\n", " "), "runs": runs}
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"{OUT}: {len(runs)} runs, {sum(r['rows'] for r in runs)} rows, {OUT.stat().st_size // 1024} KB")
    assert all(math.isfinite(v) for r in runs for v in r["start_deg"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
