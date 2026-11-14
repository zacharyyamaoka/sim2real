"""The control for what only the J1 rows do: V1 and park_first WITHOUT J1's home on the J1 rows' plant (the rack's J1 gravity from
power-on), on every start the recommended routine lost in the wrist only with J1, and on every start V1+J1 touched something (itself,
or the belt after lift-off) that V1 without J1 did not. A start the control loses, or touches, the same way did so through the plant's
landing (the arm falls onto the belt differently from power-on); otherwise through J1's home (J1 at READY's -12.7 deg, the sweep).
Sim only.

    env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/sim2real/.venv/bin/python /home/bam/sim2real/tools/homing_routine_j1_control.py

WHY (2026-11-14): the J1 rows run the rack's J1 gravity (fullarm_plant j1_rack) and the rows without J1 the CAD's, so "with J1 against
without" mixes J1's home with where the arm lands; phase 0 runs before J1 moves, so only what comes after it - the wrist's losses
and contacts - needs this control.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from sim2real.provenance import code_sha, write_results
from sim2real.sim.homing import fullarm_routine as fr
from sim2real.sim.homing import routine_check as rc
from sim2real.sim.homing import routine_ruler as ruler
from sim2real.sim.homing.mujoco_plant import BAM_WS_SRC

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path.home() / ".cache" / "sim2real" / "homing_routine" / "results_2026-11-13.json"
PLANS = Path.home() / ".cache" / "sim2real" / "homing_routine_plans.pkl"  # the rows without J1 (the control commands the same)
OUT = ROOT / "src" / "sim2real" / "data" / "homing_routine_j1_control_2026-11-14.json"
REC = fr.RECOMMENDED + rc.TIGHT_SUFFIX
NO_J1 = fr.RECOMMENDED_NO_J1 + rc.TIGHT_SUFFIX
PAIRS = {"zach_v1 @ READY": "zach_v1+J1 @ READY", "park_first+witness @ READY": "park_first+witness+J1 @ READY"}


def control_name(base: str) -> str:
    return base.replace(" @ READY", " [rack J1 gravity, J1 held] @ READY")


def main() -> int:
    episodes = json.loads(RESULTS.read_text())["episodes"]
    by = {(e.get("row"), e.get("environment"), e.get("start")): e for e in episodes if "refused_start" not in e}
    lost = {(e["environment"], e["start"], e["cell_index"]) for e in episodes if e.get("row") == REC
            and rc.ended_in(e) == "wrist" and (by.get((NO_J1, e["environment"], e["start"])) or {}).get("outcome_class") == "homed"}
    touched = {}
    for e in episodes:
        o = by.get(("zach_v1 @ READY", e.get("environment"), e.get("start")))
        if e.get("row") != "zach_v1+J1 @ READY" or o is None or "refused_start" in e:
            continue
        extra = sorted(set(e.get("self_contact_pairs") or []) - set(o.get("self_contact_pairs") or []))
        belt = (e.get("belt_after_liftoff_ticks") or 0) > 0 and not (o.get("belt_after_liftoff_ticks") or 0)
        if extra or belt:
            touched[(e["environment"], e["start"], e["cell_index"])] = {"pairs": extra, "belt_after_liftoff": belt,
                                                                       "first_s": e.get("self_contact_first_s")}
    starts = sorted(lost | set(touched))
    plans = pickle.loads(PLANS.read_bytes())
    for base in PAIRS:
        fr.ROWS[control_name(base)] = {**fr.ROWS[base], "plant": {"j1_rack": True}}
        rc.PLANS[control_name(base)] = plans[base]
    cells = ruler.grid_cells()
    rows = []
    for environment, start, index in starts:
        out = {r["row"]: r for r in rc.run_job({"cell_index": index, "cell": cells[index], "environment": environment,
                                                "rows": [control_name(b) for b in PAIRS]}, tables={})}
        entry = {"environment": environment, "start": start, "recommended_with_j1": by[(REC, environment, start)]["outcome_class"],
                 "recommended_without_j1": by[(NO_J1, environment, start)]["outcome_class"], "rows": {},
                 "wrist_lost_only_with_j1": (environment, start, index) in lost}
        if (environment, start, index) in touched:
            extra = touched[(environment, start, index)]
            held = out[control_name("zach_v1 @ READY")]
            same = set(extra["pairs"]) <= set(held.get("self_contact_pairs") or []) and (
                not extra["belt_after_liftoff"] or (held.get("belt_after_liftoff_ticks") or 0) > 0)
            entry["touched_only_with_j1"] = {**extra, "control_pairs": held.get("self_contact_pairs") or [],
                                             "control_first_s": held.get("self_contact_first_s"),
                                             "touched_by": "the plant's landing" if same else "J1's home"}
        same_as_j1 = True
        for base, with_j1 in PAIRS.items():
            control = out[control_name(base)]
            outcome = ruler.outcome_class(control)
            entry["rows"][base] = {"cad_plant": by[(base, environment, start)]["outcome_class"],
                                   "rack_j1_gravity_held": outcome, "rack_j1_gravity_homed": by[(with_j1, environment, start)]["outcome_class"],
                                   "control_outcome": str(control.get("outcome"))[:200]}
            same_as_j1 &= outcome == by[(with_j1, environment, start)]["outcome_class"]
        if entry["wrist_lost_only_with_j1"]:
            entry["lost_to"] = "the plant's landing" if same_as_j1 else "J1's home"
        rows.append(entry)
        print(environment, start, entry.get("lost_to"), (entry.get("touched_only_with_j1") or {}).get("touched_by"), flush=True)
    write_results(OUT, {"schema": "sim2real.homing_j1_control/1", "question": __doc__.split("\n\n")[0], "starts": rows,
                        "sim2real_sha": code_sha(Path(__file__)), "bam_ws_sha": code_sha(BAM_WS_SRC)}, default=str)
    print(OUT, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
