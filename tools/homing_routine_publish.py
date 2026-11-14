"""Finish the homing-routine deliverables from routine_check's episodes: the final results JSON (the tight witness rows included), the W&B
project "Homing · bam_fb_v2" (one run per routine x twin, the coverage maps, the Rerun replays) and the report.

    env -u VIRTUAL_ENV /home/bam/sim2real/.venv/bin/python /home/bam/sim2real/tools/homing_routine_publish.py --wandb --report

Reads the episode cache (the grid may still be running: what has landed is published, and a later run supersedes it), the per-twin
calibrations with their trusted stall readings, and the media index (reports/media/homing-routine-2026-11-13/media.json).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from sim2real.provenance import write_results
from sim2real.sim.homing import routine_check as rc

ROOT = Path(__file__).resolve().parents[1]
from sim2real.sim.homing.fullarm_routine import RECOMMENDED  # noqa: E402 - the routine the page leads with
CACHE = Path.home() / ".cache" / "sim2real" / "homing_routine" / "episodes_2026-11-13.jsonl"
CALIBRATIONS = Path.home() / ".cache" / "sim2real" / "homing_routine" / "calibrations_tight_2026-11-13.json"
# WHY two files (feedback_source_only_git_boundary): git keeps the cards, the calibrations and the raw run episodes gzipped (every derived
# row is recomputed from them by routine_check); the full results with every derived episode, which the report and W&B read, stay in the cache
RESULTS = Path.home() / ".cache" / "sim2real" / "homing_routine" / "results_2026-11-13.json"
COMMITTED = ROOT / "src" / "sim2real" / "data" / "homing_routine_2026-11-13.json"
EPISODES_GZ = ROOT / "src" / "sim2real" / "data" / "homing_routine_episodes_2026-11-13.jsonl.gz"
MEDIA = Path("/home/bam/bam_ws/reports/media/homing-routine-2026-11-13/media.json")
REPLAYS = Path.home() / ".cache" / "sim2real" / "homing_routine" / "replays.json"
WANDB_OUT = ROOT / "src" / "sim2real" / "data" / "homing_routine_wandb_2026-11-13.json"
REPORT = Path("/home/bam/bam_ws/reports/homing-routine-2026-11-13.html")
# which filmed episode is each nominal row's typical replay (the same motion serves the row re-judged by the tight witness)
TYPICAL = {"zach_v1 @ READY": "zach_v1_ready_belt_rest", "park_first+witness @ READY": "park_first_ready_belt_rest",
           "park_first+witness+table @ READY": "park_first_ready_belt_rest", "multi x2 (3D-printer) @ READY": "multi_x2_ready_belt_rest",
           "press_reverse (backlash every home) @ READY": "press_reverse_ready_belt_rest",
           "PEP 0047 (wrist at the five-bar's home)": "pep0047_wrist_at_the_bowl", "zach_v1+table @ READY": "zach_v1_ready_belt_rest",
           "V1, park_first on a W1 refusal @ READY": "zach_v1_ready_belt_rest",
           "V1+table, park_first on a W1 refusal @ READY": "zach_v1_ready_belt_rest",
           "zach_v1+J1 @ READY": "zach_v1_j1_ready_belt_rest", "zach_v1+table+J1 @ READY": "zach_v1_j1_ready_belt_rest",
           "V1+J1, park_first on a W1 refusal @ READY": "zach_v1_j1_ready_belt_rest",
           "V1+table+J1, park_first on a W1 refusal @ READY": "zach_v1_j1_ready_belt_rest"}


def final_results() -> dict:
    episodes = [e for e in rc.load_cache(CACHE) if "error" not in e]
    errors = [e for e in rc.load_cache(CACHE) if "error" in e]
    calibrations = json.loads(CALIBRATIONS.read_text())
    results = rc.results(episodes + errors, {k: v.get("table") for k, v in calibrations.items() if v.get("table")}, calibrations)
    write_results(RESULTS, results, default=str)
    import gzip  # noqa: PLC0415

    with gzip.open(EPISODES_GZ, "wt") as handle:
        for e in episodes + errors:
            handle.write(json.dumps(e, default=str) + "\n")
    write_results(COMMITTED, {k: v for k, v in results.items() if k != "episodes"} | {
        "episodes": f"{EPISODES_GZ.name}: the {len(episodes)} run episodes (+{len(errors)} errors); routine_check.results() re-derives the rest"},
        default=str)
    return results


def replays(results: dict) -> dict:
    media = json.loads(MEDIA.read_text()) if MEDIA.is_file() else {}
    out = {}
    for key in results["cards"]:
        routine, environment = key.split(" | ")
        base = routine.removesuffix(rc.TIGHT_SUFFIX)
        item = media.get(TYPICAL.get(base, "")) if environment == "nominal" else None
        table = [{"episode": name, "start": entry["report"].get("start"), "outcome": entry["report"].get("outcome_class"),
                  "rrd": entry.get("rrd"), "open": f"/home/bam/data_recorder/.venv/bin/data-recorder view {entry.get('rrd')}"}
                 for name, entry in media.items() if entry.get("row") == base and entry.get("environment") == environment and entry.get("rrd")]
        if item and item.get("rrd") or table:
            out[key] = {"typical": item.get("rrd") if item else None, "table": table}
    REPLAYS.write_text(json.dumps(out, indent=1))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wandb", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    results = final_results()
    print(f"results: {len(results['episodes'])} episodes, {len(results['cards'])} cards -> {RESULTS}", flush=True)
    links = replays(results)
    if args.wandb:
        from sim2real.tracking.homing_fullarm import log  # noqa: PLC0415

        summary = log(results, replays=links)
        WANDB_OUT.write_text(json.dumps(summary, indent=1, default=str))
        print(json.dumps({k: summary[k] for k in ("project", "project_url", "runs", "new", "retired", "report")}, indent=1), flush=True)
    if args.report:
        notes = ROOT / "tools" / "homing_routine_notes.json"
        subprocess.run([sys.executable, str(ROOT / "tools" / "homing_routine_report.py"), "--out", str(REPORT), "--results", str(RESULTS),
                        "--wandb", str(WANDB_OUT), "--notes", str(notes), "--recommended",
                        json.loads(notes.read_text()).get("recommended", RECOMMENDED) if notes.is_file() else RECOMMENDED],
                       check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
