"""The homing leaderboard on W&B: "Homing · five-bar rig", built on bam_ws bam_trackio.bbo (the house black-box template).

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra homing --extra tracking python -m sim2real.tracking.homing /home/bam/sim2real/src/sim2real/data/homing_fivebar_kinematic_2026-11-12.json

From one homing bench results JSON (sim2real.sim.homing.bench), nothing recomputed but the five metrics' scorecards it already holds:

* one W&B run per (rung, backlash model, procedure): config ``rung``, ``backlash_model``, ``procedure``, ``bundle_sha`` (+ the code
  shas, the hardstops sha, the gate), summary = the scorecard, a table of every start;
* one Weave evaluation per (procedure, environment), environment = "<rung> · <model>" (the black box is the procedure; each start
  is an episode), and ONE leaderboard, "Homing · five-bar rig": rows the procedures, columns (environment x metric).

WHY one project with procedures as rows (decision report, "challenging the brief"): a Weave leaderboard compares only within one
project. WHY nothing is deleted: bbo prunes superseded evaluations and deletes unended calls; both are switched off here (the brief
forbids deleting runs), and a re-run of the same numbers maps to the same run ids, so it is idempotent. A changed number makes a new
evaluation; the older runs are marked superseded (``wandb_log.retire``), never removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .wandb_log import ENTITY, browser_url, push, retire, run_id

PROJECT = "Homing · five-bar rig"
LEADERBOARD = "Homing · five-bar rig"
SCORERS = ["inside_gate", "reliable", "time_s", "zero_error_deg"]
# leaderboard columns per environment: (title, summary key, minimize)
COLUMNS = (
    ("Reliability (%)", "reliability_pct", False),
    ("Any start (%)", "any_start_pct", False),
    ("True-zero error p95 (°)", "joint_angle_error_deg", True),
    ("Backlash error p95 (°)", "backlash_error_deg", True),
    ("Time to home, median (s)", "time_to_home_s", True),
)


def evaluation_digest(results: dict, model: str, procedure: str) -> str:
    payload = {"card": results["scorecards"][model][procedure], "episodes": results["episodes"][model][procedure],
               "bundle": results["hardstops_sha256"], "code": [results["sim2real_sha"], results["robot_models_sha"]]}
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]


def _episode_rows(results: dict, model: str, procedure: str) -> list[dict]:
    from robot_models.homing.metrics import reliable  # noqa: PLC0415

    from ..sim.homing.bench import expand  # noqa: PLC0415 -- the compact rows' one reader

    rows = []
    for row in results["episodes"][model][procedure]:
        record = expand(row, procedure, f"{results['rung']} · {model}")
        worst = record.worst_zero_error_deg()
        rows.append({"start": record.start, "finished": record.finished, "reliable": reliable(record), "outcome": record.outcome,
                     "time_s": record.time_s, "worst_zero_error_deg": worst,
                     "inside_gate": bool(reliable(record) and worst is not None and worst <= results["gate_deg"]
                                         and all(j.zero_error_deg is not None for j in record.joints)),
                     **{f"zero_error_deg_{j.joint}": j.zero_error_deg for j in record.joints},
                     **{f"gap_error_deg_{j.joint}": (None if j.gap_identified_deg is None else j.gap_identified_deg - j.gap_truth_deg)
                        for j in record.joints}})
    return rows


def records(results: dict) -> list[dict]:
    """The W&B runs (wandb_log.push's record shape), one per (rung, model, procedure)."""
    out = []
    for model, by_procedure in results["scorecards"].items():
        for procedure, card in by_procedure.items():
            evaluation = evaluation_digest(results, model, procedure)
            result_id = f"homing-fivebar-{results['rung']}-{model}-{procedure}"
            config = {"rung": results["rung"], "backlash_model": model, "procedure": procedure, "bundle_sha": results["bundle_sha"],
                      "hardstops_sha256": results["hardstops_sha256"], "sim2real_sha": results["sim2real_sha"],
                      "robot_models_sha": results["robot_models_sha"], "gate_deg": results["gate_deg"],
                      "hidden_gap_arcmin": results["hidden_gap_arcmin"], "rig": "five-bar", "result_id": result_id,
                      "evaluation": evaluation, "evaluation_state": "latest", "starts": len(results["starts"])}
            numbers = {k: v for k, v in card.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None}
            flags = {k: v for k, v in card.items() if isinstance(v, bool)}
            out.append({"id": run_id("homing", results["rung"], model, procedure, evaluation),
                        "name": f"{procedure} · {results['rung']} · {model}", "group": f"{results['rung']} · {model}",
                        "job_type": "homing", "tags": ["homing", results["rung"], model, procedure, "latest"],
                        "notes": f"{procedure} on the {results['rung']} rung, hidden backlash {model}, bundle {results['bundle_sha']}",
                        "config": config, "history": [numbers], "summary": {**numbers, **{k: int(v) for k, v in flags.items()}},
                        "tables": {"starts": _episode_rows(results, model, procedure)}})
    return out


def scored_runs(bbo, results: dict) -> list:
    out = []
    for model, by_procedure in results["scorecards"].items():
        environment = f"{results['rung']} · {model}"
        for procedure, card in by_procedure.items():
            episodes = []
            for row in _episode_rows(results, model, procedure):
                scores = {"reliable": row["reliable"], "inside_gate": row["inside_gate"]}
                if row["time_s"] is not None:
                    scores["time_s"] = float(row["time_s"])
                if row["worst_zero_error_deg"] is not None:
                    scores["zero_error_deg"] = float(row["worst_zero_error_deg"])
                episodes.append(bbo.Episode(inputs={"start": row["start"]}, output={"outcome": row["outcome"]}, scores=scores))
            summary = {k: (int(v) if isinstance(v, bool) else v) for k, v in card.items()
                       if v is not None and isinstance(v, (int, float, bool))}
            out.append(bbo.ScoredRun(
                black_box=procedure,
                version={"sim2real_sha": results["sim2real_sha"], "robot_models_sha": results["robot_models_sha"],
                         "bundle_sha": results["bundle_sha"]},
                environment=environment, episodes=episodes, summary=summary,
                attributes={"run_id": run_id("homing-weave", results["rung"], model, procedure,
                                             evaluation_digest(results, model, procedure))}))
    return out


def log(results: dict, *, weave: bool = True) -> dict:
    from .rigs import load_bbo  # noqa: PLC0415 -- bbo by file, the house template on bam_ws main

    batch = records(results)
    runs = push(batch, project=PROJECT)
    retired = sum(retire(record["config"]["result_id"], record["config"]["evaluation"], project=PROJECT) for record in batch)
    board = None
    if weave:
        bbo = load_bbo()
        # WHY both off: never delete anything in Zach's W&B (see the module docstring)
        bbo.delete_unended = lambda client: 0
        bbo.prune_superseded = lambda client, runs, columns=None: 0
        entity_project = f"{ENTITY}/{PROJECT}"
        runs_weave = scored_runs(bbo, results)
        refs = bbo.log_evaluations(entity_project, runs_weave, scorers=SCORERS)
        environments = [f"{results['rung']} · {model}" for model in results["models"]]
        metrics = [bbo.Metric(title, key, minimize=minimize) for title, key, minimize in COLUMNS]
        board = bbo.publish_leaderboard(entity_project, LEADERBOARD,
                                        "Homing procedures as black boxes on the five-bar (decision report 2026-11-12): five metrics per "
                                        "rung x hidden backlash model; sort by reliability, then zero error, then time.",
                                        refs, metrics, environments)
    return {"project": PROJECT, "runs": len(runs), "new": sum(1 for r in runs if not r["resumed"]), "retired": retired,
            "urls": {r["name"]: browser_url(r["url"]) for r in runs}, "leaderboard": board}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--no-weave", action="store_true")
    parser.add_argument("--out", type=Path, help="write what was logged (run URLs, the leaderboard ref) here")
    args = parser.parse_args(argv)
    summary = log(json.loads(args.results.read_text()), weave=not args.no_weave)
    text = json.dumps(summary, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
