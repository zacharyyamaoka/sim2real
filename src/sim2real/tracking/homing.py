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
# one project (and one leaderboard) per rig: a result JSON names its rig ("rig"; a five-bar result predates the key)
PROJECTS = {"five-bar": PROJECT, "ur-wrist": "Homing · UR wrist rig"}
SLUG = {"five-bar": "fivebar", "ur-wrist": "urwrist"}


def rig_of(results: dict) -> str:
    return results.get("rig", "five-bar")
SCORERS = ["inside_gate", "reliable", "time_s", "zero_error_deg"]
# leaderboard columns per environment: (title, summary key, minimize)
COLUMNS = (
    ("Reliability (%)", "reliability_pct", False),
    ("Any start (%)", "any_start_pct", False),
    ("True-zero error p95 (°)", "joint_angle_error_deg", True),
    ("True-zero error vs twin contact p95 (°)", "vs_twin.joint_angle_error_deg", True),
    ("Backlash error p95 (°)", "backlash_error_deg", True),
    ("Time to home, median (s)", "time_to_home_s", True),
    # the real rung's zero checks (it has no truth): the zero's spread over its starts, and its offset from the run rows' consensus
    # against the same on the MuJoCo rung (real_bench.score); empty on the simulated rungs
    ("Zero repeat spread, real (°)", "zero_spread_max_deg", True),
    ("Real − MuJoCo zero (°)", "real_minus_mujoco_deg", True),
)


def twin_card(results: dict, model: str, procedure: str) -> dict:
    """The scorecard against the twin's own stop contacts (the MuJoCo rung's ``scorecards_vs_twin``, 2026-11-12 pass 4). The kinematic
    rung's stops ARE CAD's (coal first contact on the meshes hardstops.json names), so there its CAD card is its twin card."""
    cards = results.get("scorecards_vs_twin")
    if cards is None:
        return results["scorecards"][model][procedure]
    return cards.get(model, {}).get(procedure) or {}


def evaluation_digest(results: dict, model: str, procedure: str) -> str:
    payload = {"card": results["scorecards"][model][procedure], "episodes": results["episodes"][model][procedure],
               "bundle": results["hardstops_sha256"], "code": [results["sim2real_sha"], results["robot_models_sha"]]}
    if results.get("scorecards_vs_twin") is not None:  # WHY only then: a kinematic result's digest stays what it was (no new evaluation)
        payload["vs_twin"] = twin_card(results, model, procedure)
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]


def _numbers(card: dict, prefix: str = "") -> dict:
    return {f"{prefix}{k}": v for k, v in card.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None}


def _episode_rows(results: dict, model: str, procedure: str) -> list[dict]:
    from robot_models.homing.metrics import reliable  # noqa: PLC0415

    if results["rung"] == "real":
        # WHY its own rows (real_bench.score): no true zero on the real arm, so no zero error; a start is inside the gate when it is
        # reliable and its zero sits within the gate of the row's median (the spread gate's per-start view)
        gate = results["gate_deg"]
        return [{**row, "worst_zero_error_deg": None,
                 "inside_gate": bool(row["reliable"] and all(row.get(f"zero_minus_median_deg_{j}") is not None
                                                             and abs(row[f"zero_minus_median_deg_{j}"]) <= gate for j in ("J2", "C1")))}
                for row in results["real_rows"].get(procedure, [])]

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


TAG_MAX_BYTES = 64  # W&B refuses a longer tag - counted in UTF-8 bytes ('·' is two)


def _tag(text: str) -> str:
    """``text`` as a W&B tag: itself when it fits, else its head and an 8-hex digest of the whole (still one tag per procedure); the
    full name stays in the run's name and config (pass 7's 'recover_first(fed)+single_touch_c1seek+gff · ...' names run to 76)."""
    if len(text.encode("utf-8")) <= TAG_MAX_BYTES:
        return text
    suffix = " ~" + hashlib.sha256(text.encode()).hexdigest()[:8]
    head = text
    while len((head + suffix).encode("utf-8")) > TAG_MAX_BYTES:
        head = head[:-1]
    return head.rstrip() + suffix


def start_rows_for(results: dict, procedure: str) -> list[dict]:
    """The starts ``procedure`` ran from: ``results["starts"]`` when it is one list; when it comes in families (pass7_rung, 2026-11-13:
    {family: [start, ...]}, each row on its own family) the family ``results["rows"]`` names for the procedure's row."""
    starts = results["starts"]
    if isinstance(starts, list):
        return starts
    row = procedure.split(" · ")[0]
    family = {r["row"]: r["starts"] for r in results.get("rows") or ()}.get(row)
    if family in starts:
        return starts[family]
    return [s for rows in starts.values() for s in rows]


def records(results: dict) -> list[dict]:
    """The W&B runs (wandb_log.push's record shape), one per (rung, model, procedure)."""
    out = []
    for model, by_procedure in results["scorecards"].items():
        for procedure, card in by_procedure.items():
            evaluation = evaluation_digest(results, model, procedure)
            result_id = f"homing-{SLUG[rig_of(results)]}-{results['rung']}-{model}-{procedure}"
            config = {"rung": results["rung"], "backlash_model": model, "procedure": procedure, "bundle_sha": results["bundle_sha"],
                      "hardstops_sha256": results["hardstops_sha256"], "sim2real_sha": results["sim2real_sha"],
                      "robot_models_sha": results["robot_models_sha"], "gate_deg": results["gate_deg"],
                      "hidden_gap_arcmin": results["hidden_gap_arcmin"], "rig": rig_of(results), "result_id": result_id,
                      "evaluation": evaluation, "evaluation_state": "latest", "starts": len(start_rows_for(results, procedure)),
                      "start": f"all {len(start_rows_for(results, procedure))} (per-start rows in the starts table)",
                      "start_names": [s["name"] for s in start_rows_for(results, procedure)]}
            if results.get("pass") is not None:  # WHY (pass 6): a pass's rows sit beside the earlier passes' on one leaderboard, labelled
                config.update({"pass": results["pass"], "form": results.get("form")})
            numbers = _numbers(card)
            numbers.update(_numbers(twin_card(results, model, procedure), "vs_twin."))
            verdict = (results.get("verdicts") or {}).get(model, {}).get(procedure)
            if verdict:
                config.update({"gate_pass": verdict.get("pass"), "gate_pass_vs_cad": verdict.get("pass_vs_cad", verdict.get("pass")),
                               "judged_against": "twin contacts" if "pass_vs_cad" in verdict else "CAD"})
            if results.get("twin_contacts_deg"):
                config["twin_contacts_deg"] = results["twin_contacts_deg"]
            # the coordinator's ruling (2026-11-12): working-assembly and assembly-mode starts scored apart, each with where it is judged
            for scope, by_model in (results.get("scorecards_by_scope") or {}).items():
                scoped = by_model.get(model, {}).get(procedure)
                if scoped:
                    numbers.update({f"{scope}.{k}": v for k, v in scoped.items()
                                    if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None})
                    config[f"{scope}_judged_on"] = scoped.get("judged_on")
            flags = {k: v for k, v in card.items() if isinstance(v, bool)}
            out.append({"id": run_id("homing", results["rung"], model, procedure, evaluation),
                        "name": f"{procedure} · {results['rung']} · {model}", "group": f"{results['rung']} · {model}",
                        "job_type": "homing", "tags": ["homing", results["rung"], model, _tag(procedure), "latest"],
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
            summary.update(_numbers(twin_card(results, model, procedure), "vs_twin."))
            out.append(bbo.ScoredRun(
                black_box=procedure,
                version={"sim2real_sha": results["sim2real_sha"], "robot_models_sha": results["robot_models_sha"],
                         "bundle_sha": results["bundle_sha"]},
                environment=environment, episodes=episodes, summary=summary,
                attributes={"run_id": run_id("homing-weave", results["rung"], model, procedure,
                                             evaluation_digest(results, model, procedure))}))
    return out


def log(results: dict | list[dict], *, weave: bool = True) -> dict:
    """Log one or several bench results (one per rung) into the one project and the one leaderboard. WHY several in one call: the
    leaderboard is published from this call's evaluations, so logging the rungs one at a time would leave only the last rung's columns."""
    from .rigs import load_bbo  # noqa: PLC0415 -- bbo by file, the house template on bam_ws main

    many = list(results) if isinstance(results, list) else [results]
    rigs = {rig_of(one) for one in many}
    if len(rigs) != 1:
        raise ValueError(f"one rig per call (one project, one leaderboard): got {sorted(rigs)}")
    project = PROJECTS[rigs.pop()]
    batch = [record for one in many for record in records(one)]
    runs = push(batch, project=project)
    retired = sum(retire(record["config"]["result_id"], record["config"]["evaluation"], project=project) for record in batch)
    board = None
    if weave:
        bbo = load_bbo()
        # WHY both off: never delete anything in Zach's W&B (see the module docstring)
        bbo.delete_unended = lambda client: 0
        bbo.prune_superseded = lambda client, runs, columns=None: 0
        entity_project = f"{ENTITY}/{project}"
        runs_weave = [run for one in many for run in scored_runs(bbo, one)]
        refs = bbo.log_evaluations(entity_project, runs_weave, scorers=SCORERS)
        environments = list(dict.fromkeys(f"{one['rung']} · {model}" for one in many for model in one["models"]))
        metrics = [bbo.Metric(title, key, minimize=minimize) for title, key, minimize in COLUMNS]
        board = bbo.publish_leaderboard(entity_project, project,
                                        f"Homing procedures as black boxes on the {'five-bar' if project == PROJECT else 'UR wrist'} (decision "
                                        "report 2026-11-12): five metrics per rung x hidden backlash model, zero error vs CAD and vs the twin's "
                                        "own contacts; sort by reliability, then zero error, then time.",
                                        refs, metrics, environments)
    return {"project": project, "runs": len(runs), "new": sum(1 for r in runs if not r["resumed"]), "retired": retired,
            "urls": {r["name"]: browser_url(r["url"]) for r in runs}, "leaderboard": board}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path, nargs="+", help="one results JSON per rung (kinematic, mujoco)")
    parser.add_argument("--no-weave", action="store_true")
    parser.add_argument("--out", type=Path, help="write what was logged (run URLs, the leaderboard ref) here")
    args = parser.parse_args(argv)
    summary = log([json.loads(path.read_text()) for path in args.results], weave=not args.no_weave)
    text = json.dumps(summary, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
