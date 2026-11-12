"""The Kinematic Calibration project on W&B: Zach's bam_calibration simulation ledgers as runs, plus one Weave leaderboard.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra tracking python -m sim2real.tracking.kincal log /home/bam/sim2real/src/sim2real/data/kincal_ledger_2026-11-12.json

Two steps, because the raw ledgers sit in a gitignored bam_ws worktree that a disk sweep can delete:

* ``extract --v1 <runs.jsonl> --v2 <runs.jsonl> [--v2 <more.jsonl>] --out <compact.json>`` keeps the per-seed numbers only (no raw arrays) in
  a small JSON that is committed (src/sim2real/data/). Several v2 ledgers are unioned; the newest ok row per (cell_id, seed_index) wins.
* ``log <compact.json> [--no-weave] [--out <file>]`` pushes it to W&B project "Kinematic Calibration":
  one run per v2 (cell, algorithm) -- UR's own dual-arm method (patent US 9,248,573) and its variants on two arms on UR's calibration
  "horse" -- one run per v1 cell (bam_calibration's first study, questions Q0-Q9), and ONE Weave leaderboard over the v2 runs
  (rows the algorithms, columns cell x metric), built on bam_ws bam_trackio.bbo like homing.py.

WHY nothing is deleted: bbo's ``delete_unended`` and ``prune_superseded`` are switched off (never delete anything in Zach's W&B), and a
re-run of the same numbers maps to the same run ids. A changed number makes a new evaluation; ``wandb_log.retire`` marks the older runs
superseded, never removed. WHY the paired ratio is a median of per-seed ratios: every seed plans one dataset that all algorithms of a cell
see, so alg/A0 on the same seed isolates the algorithm from the seed's luck; a ratio of medians mixes seeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from .wandb_log import ENTITY, browser_url, push, retire, run_id

PROJECT = "Kinematic Calibration"
LEADERBOARD = "Kinematic Calibration · UR horse (v2)"
COMPACT_SCHEMA = "kincal-compact/1"
BASELINE = "A0"
SCORERS = ["k4d_pos_mean_mm", "ratio_vs_A0"]
# leaderboard columns per environment: (title, summary key, minimize)
COLUMNS = (
    ("K4d mean, worst arm (mm)", "k4d_pos_mean_mm", True),
    ("K4d p95, worst arm (mm)", "k4d_pos_p95_mm", True),
    ("Ratio vs A0 (paired median)", "ratio_vs_A0", True),
)
# bam_calibration docs/study/SPEC-v2.md D39
ALGORITHM_DESC = {
    "A0": "UR patent baseline: 47 free parameters, Gauss-Newton, unit SI weights",
    "A0.46": "A0 as the patent's Table 1: 46 parameters",
    "A0L": "A0 with a 0.1 m rotation lever",
    "A3": "A0 + per-pose whitening",
    "A4": "A3 + Huber robust loss",
    "A6w": "A3 + joint compliance from model torque",
    "A1": "v1 full-chain MAP",
    "A1.p05": "A1 with prior sigma x0.5",
    "A1.p2": "A1 with prior sigma x2",
    "A2": "minimal POE (equivalence check)",
    "A3b": "Gauss-Helmert errors-in-variables (equivalence check)",
    "A0fb": "A0 + five-bar map (BAM only)",
}
V1_CONFIG = ("topology", "arms", "sessions", "poses_per_session", "fit", "tilt_rad")
# WHY several names: the per-parameter recovery block of a BAM row is not written yet; take the first one a row carries
RECOVERY_KEYS = ("parameter_recovery", "recovery", "parameters_recovery")


# ---------------------------------------------------------------------------------------------------------------- reading the ledgers


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _started(row: dict) -> tuple[datetime, str]:
    return datetime.fromisoformat(row["started_at"]), row.get("run_id", "")


def latest_rows(rows: list[dict]) -> list[dict]:
    """The newest ok row per (cell_id, seed_index), cells in order of first appearance, seeds ascending."""
    best: dict[tuple[str, int], dict] = {}
    cell_order: dict[str, int] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        cell_order.setdefault(row["cell_id"], len(cell_order))
        key = (row["cell_id"], row["seed_index"])
        if key not in best or _started(row) > _started(best[key]):
            best[key] = row
    return [best[key] for key in sorted(best, key=lambda k: (cell_order[k[0]], k[1]))]


def _worst_arm(kpi: dict) -> tuple[str, float]:
    worst = kpi.get("worst_arm")
    if worst:
        return worst["arm"], worst["K4d_pos_mean_mm"]
    # WHY a fallback: a row from another lane may not carry the roll-up; the worst arm is the one with the largest K4d mean
    arms = {arm: block["K4d"]["pos_mm"]["mean"] for arm, block in kpi.items() if isinstance(block, dict) and "K4d" in block}
    arm = max(arms, key=arms.get)
    return arm, arms[arm]


def _recovery_rows(record: dict) -> list[dict]:
    """A row's per-parameter recovery block as flat rows: a list of dicts, or {parameter: number | {field: number}}."""
    block = next((record[key] for key in RECOVERY_KEYS if record.get(key)), None)
    rows = []
    if isinstance(block, list):
        rows = [dict(item) for item in block if isinstance(item, dict)]
    elif isinstance(block, dict):
        for name, value in block.items():
            rows.append({"parameter": name, **(value if isinstance(value, dict) else {"value": value})})
    return [{k: v for k, v in row.items() if isinstance(v, (str, int, float, bool)) or v is None} for row in rows]


def _v2_algorithm(record: dict) -> dict:
    arm, mean = _worst_arm(record["kpi"])
    k4d = record["kpi"][arm]["K4d"]["pos_mm"]
    out = {"k4d_pos_mean_mm": mean, "k4d_pos_p95_mm": k4d["p95"], "k4d_pos_max_mm": k4d["max"], "worst_arm": arm,
           "form": record.get("form"), "converged": record.get("converged"), "iterations": record.get("iterations"),
           "runtime_s": record.get("runtime_s"), "parameters": record.get("parameters"),
           "ur_accept": (record.get("ur") or {}).get("accept")}
    recovery = _recovery_rows(record)
    if recovery:
        out["parameter_recovery"] = recovery
    return out


def _v2_seed(row: dict) -> dict:
    head = row["headline"]
    return {"seed_index": row["seed_index"], "batch_id": row.get("batch_id"), "started_at": row["started_at"],
            "git_sha": row.get("git_sha"), "code_hash": row.get("code_hash"), "before_mm": head.get("before"),
            "floor_mm": head.get("floor"),
            "algorithms": {alg: _v2_algorithm(record) for alg, record in row["algorithms"].items()}}


def _v1_seed(row: dict) -> dict:
    head = row["headline"]
    return {"seed_index": row["seed_index"], "worst_arm": head.get("worst_arm"), "pos_rms_mm": head["pos_rms_mm"],
            "pos_p95_mm": head["pos_p95_mm"], "pos_max_mm": head["pos_max_mm"], "rot_rms_mrad": head["rot_rms_mrad"],
            "before_pos_rms_mm": head["before_pos_rms_mm"], "internal_pos_rms_mm": head.get("internal_pos_rms_mm"),
            "floor_worst_arm_pos_rms_mm": (row.get("prediction") or {}).get("floor_worst_arm_pos_rms_mm"),
            "git_sha": row.get("git_sha"), "code_hash": row.get("code_hash"), "started_at": row["started_at"],
            "duration_s": row.get("duration_s")}


def _shas(rows: list[dict]) -> list[str]:
    return sorted({row["git_sha"] for row in rows if row.get("git_sha")})


def compact_ledgers(v1_rows: list[dict], v2_rows: list[dict], *, v1_source: str, v2_sources: list[str]) -> dict:
    """The compact ledger: per-seed numbers only, with where they came from."""
    v1_kept, v2_kept = latest_rows(v1_rows), latest_rows(v2_rows)
    v1: dict[str, dict] = {}
    for row in v1_kept:
        cell = v1.setdefault(row["cell_id"], {"question": row["question"], "seeds": [], "config": {
            **{k: row["config"].get(k) for k in V1_CONFIG}, "coupling_kind": row["config"]["coupling"]["kind"],
            "datum_site_count": row["config"]["datum"]["site_count"], "noise_level": row["config"]["noise"]["level"]}})
        cell["seeds"].append(_v1_seed(row))
    v2: dict[str, dict] = {}
    for row in v2_kept:
        cell = v2.setdefault(row["cell_id"], {"rung": row["rung"], "label": row.get("label"), "setup": row.get("setup"), "seeds": []})
        cell["seeds"].append(_v2_seed(row))
    return {"schema": COMPACT_SCHEMA,
            "sources": {"v1": {"path": v1_source, "schema": "kincal-run/1", "rows": len(v1_rows), "kept": len(v1_kept),
                               "git_shas": _shas(v1_kept)},
                        "v2": {"paths": list(v2_sources), "schema": "kincal-run/2", "rows": len(v2_rows), "kept": len(v2_kept),
                               "git_shas": _shas(v2_kept)}},
            "v1": v1, "v2": v2}


def extract(v1_path: Path, v2_paths: list[Path]) -> dict:
    v2_rows = [row for path in v2_paths for row in read_jsonl(path)]
    return compact_ledgers(read_jsonl(v1_path), v2_rows, v1_source=str(v1_path), v2_sources=[str(p) for p in v2_paths])


# ---------------------------------------------------------------------------------------------------------------- statistics


def spread(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def _median(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _rate(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(1 for v in values if v) / len(values) if values else None


def paired_ratios(cell: dict, algorithm: str, baseline: str = BASELINE) -> list[tuple[int, float]]:
    """(seed_index, alg / baseline) for every seed of the cell that has both and a positive baseline."""
    out = []
    for seed in cell["seeds"]:
        algorithms = seed["algorithms"]
        if algorithm in algorithms and baseline in algorithms and algorithms[baseline]["k4d_pos_mean_mm"] > 0:
            out.append((seed["seed_index"], algorithms[algorithm]["k4d_pos_mean_mm"] / algorithms[baseline]["k4d_pos_mean_mm"]))
    return out


def algorithms_of(cell: dict) -> list[str]:
    """Every algorithm any seed of the cell ran, in first-seen order (BAM cells lack the UR-only ones)."""
    found: list[str] = []
    for seed in cell["seeds"]:
        found += [alg for alg in seed["algorithms"] if alg not in found]
    return found


def _digest(payload) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]


_TIMING = {"runtime_s"}   # WHY left out of the digests: how long a machine took is not a different result


def evaluation_digest_v2(cell: dict, cell_id: str, algorithm: str) -> str:
    """A content id for one (cell, algorithm): its per-seed results, the baseline's (the ratio reads it) and the code that made them."""
    def result(record):
        return {k: v for k, v in record.items() if k not in _TIMING}

    seeds = [{"seed": s["seed_index"], "git_sha": s["git_sha"], "code_hash": s["code_hash"], "before": s["before_mm"],
              "floor": s["floor_mm"], "result": result(s["algorithms"][algorithm]),
              "baseline": s["algorithms"].get(BASELINE, {}).get("k4d_pos_mean_mm")}
             for s in cell["seeds"] if algorithm in s["algorithms"]]
    return _digest({"cell": cell_id, "algorithm": algorithm, "seeds": seeds})


def evaluation_digest_v1(cell: dict, cell_id: str) -> str:
    seeds = [{k: v for k, v in s.items() if k not in ("started_at", "duration_s")} for s in cell["seeds"]]
    return _digest({"cell": cell_id, "config": cell["config"], "seeds": seeds})


# ---------------------------------------------------------------------------------------------------------------- W&B runs


# WHY n_seeds, not seeds: a run's summary key is also its table's name, and run.summary.update would overwrite the "seeds" table with a count
def _numbers(values: dict) -> dict:
    return {k: v for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None}


def _unique(values) -> list:
    return sorted({v for v in values if v is not None}, key=str)


def _v2_record(cell_id: str, cell: dict, algorithm: str) -> dict:
    seeds = [s for s in cell["seeds"] if algorithm in s["algorithms"]]
    runs = [s["algorithms"][algorithm] for s in seeds]
    means = [r["k4d_pos_mean_mm"] for r in runs]
    ratios = dict(paired_ratios(cell, algorithm))
    evaluation = evaluation_digest_v2(cell, cell_id, algorithm)
    arm = (cell.get("setup") or {}).get("arm", "ur5e")
    parameter_counts = _unique(r["parameters"] for r in runs)
    config = {"version": "v2", "rung": cell["rung"], "cell_id": cell_id, "label": cell.get("label"), "algorithm": algorithm,
              "algorithm_desc": ALGORITHM_DESC.get(algorithm, ""), "form": (_unique(r["form"] for r in runs) or [None])[0],
              "parameters": parameter_counts[0] if len(parameter_counts) == 1 else parameter_counts,
              "seeds": [s["seed_index"] for s in seeds], "git_shas": _unique(s["git_sha"] for s in seeds),
              "code_hashes": _unique(s["code_hash"] for s in seeds), "result_id": f"kincal-v2-{cell_id}-{algorithm}",
              "evaluation": evaluation, "evaluation_state": "latest"}
    summary = {f"k4d_pos_mean_mm_worst_arm_{k}": v for k, v in spread(means).items()}
    summary.update({"k4d_pos_p95_mm_worst_arm_median": _median([r["k4d_pos_p95_mm"] for r in runs]),
                    "before_mm_median": _median([s["before_mm"] for s in seeds]),
                    "floor_mm_median": _median([s["floor_mm"] for s in seeds]),
                    "converged_rate": _rate([r["converged"] for r in runs]),
                    "ur_accept_rate": _rate([r["ur_accept"] for r in runs]),
                    "runtime_s_median": _median([r["runtime_s"] for r in runs]), "n_seeds": len(seeds)})
    if ratios:
        summary["ratio_vs_A0"] = statistics.median(ratios.values())
        summary["wins_vs_A0"] = sum(1 for r in ratios.values() if r < 1)
    table = [{"seed_index": s["seed_index"], "k4d_pos_mean_mm_worst_arm": r["k4d_pos_mean_mm"],
              "k4d_pos_p95_mm_worst_arm": r["k4d_pos_p95_mm"], "k4d_pos_max_mm_worst_arm": r["k4d_pos_max_mm"],
              "worst_arm": r["worst_arm"], "before_mm": s["before_mm"], "floor_mm": s["floor_mm"],
              "ratio_vs_A0": ratios.get(s["seed_index"]), "converged": r["converged"], "iterations": r["iterations"],
              "runtime_s": r["runtime_s"], "ur_accept": r["ur_accept"], "git_sha": s["git_sha"], "code_hash": s["code_hash"]}
             for s, r in zip(seeds, runs)]
    tables = {"seeds": table}
    recovery = [{"seed_index": s["seed_index"], **row} for s, r in zip(seeds, runs) for row in r.get("parameter_recovery", [])]
    if recovery:
        tables["parameters"] = recovery
    summary = {k: (int(v) if isinstance(v, bool) else v) for k, v in summary.items() if v is not None}
    return {"id": run_id("kincal", "v2", cell_id, algorithm, evaluation), "name": f"{algorithm} · {cell_id}", "group": cell_id,
            "job_type": "kincal", "tags": ["v2", cell["rung"], algorithm, arm, "latest"],
            "notes": f"{algorithm} ({ALGORITHM_DESC.get(algorithm, 'no description')}) on {cell_id}: {cell.get('label')}",
            "config": config, "history": [_numbers(summary)], "summary": summary, "tables": tables}


def _v1_record(cell_id: str, cell: dict) -> dict:
    seeds, config = cell["seeds"], cell["config"]
    evaluation = evaluation_digest_v1(cell, cell_id)
    summary = {f"pos_rms_mm_{k}": v for k, v in spread([s["pos_rms_mm"] for s in seeds]).items()}
    for key, source in (("pos_p95_mm_median", "pos_p95_mm"), ("pos_max_mm_median", "pos_max_mm"),
                        ("rot_rms_mrad_median", "rot_rms_mrad"), ("before_pos_rms_mm_median", "before_pos_rms_mm"),
                        ("internal_pos_rms_mm_median", "internal_pos_rms_mm"),
                        ("floor_worst_arm_pos_rms_mm_median", "floor_worst_arm_pos_rms_mm")):
        summary[key] = _median([s[source] for s in seeds])
    summary["n_seeds"] = len(seeds)
    summary = {k: v for k, v in summary.items() if v is not None}
    run_config = {"version": "v1", "question": cell["question"], "cell_id": cell_id, **config,
                  "seeds": [s["seed_index"] for s in seeds], "git_shas": _unique(s["git_sha"] for s in seeds),
                  "code_hashes": _unique(s["code_hash"] for s in seeds), "result_id": f"kincal-v1-{cell_id}",
                  "evaluation": evaluation, "evaluation_state": "latest"}
    tags = ["v1", cell["question"], config["topology"], config["fit"], config["noise_level"], "latest"]
    table = [{k: v for k, v in s.items() if k != "started_at"} for s in seeds]
    return {"id": run_id("kincal", "v1", cell_id, evaluation), "name": cell_id, "group": cell["question"], "job_type": "kincal",
            "tags": list(dict.fromkeys(tags)),
            "notes": f"bam_calibration v1 study, {cell['question']}: {config['topology']}, {config['fit']} fit, noise {config['noise_level']}",
            "config": run_config, "history": [_numbers(summary)], "summary": summary, "tables": {"seeds": table}}


def records(compact: dict) -> list[dict]:
    """The W&B runs (wandb_log.push's record shape): one per v2 (cell, algorithm), then one per v1 cell."""
    out = [_v2_record(cell_id, cell, algorithm) for cell_id, cell in compact["v2"].items() for algorithm in algorithms_of(cell)]
    return out + [_v1_record(cell_id, cell) for cell_id, cell in compact["v1"].items()]


# ---------------------------------------------------------------------------------------------------------------- Weave


def scored_runs(bbo, compact: dict) -> list:
    """The v2 leaderboard's entries: black box = algorithm, environment = cell, episodes = seeds."""
    out = []
    for cell_id, cell in compact["v2"].items():
        for algorithm in algorithms_of(cell):
            ratios = dict(paired_ratios(cell, algorithm))
            episodes, means, p95s = [], [], []
            for seed in cell["seeds"]:
                if algorithm not in seed["algorithms"]:
                    continue
                record = seed["algorithms"][algorithm]
                scores = {"k4d_pos_mean_mm": float(record["k4d_pos_mean_mm"])}
                if seed["seed_index"] in ratios:
                    scores["ratio_vs_A0"] = float(ratios[seed["seed_index"]])
                means.append(record["k4d_pos_mean_mm"])
                p95s.append(record["k4d_pos_p95_mm"])
                episodes.append(bbo.Episode(inputs={"seed_index": seed["seed_index"]},
                                            output={"worst_arm": record["worst_arm"], "converged": record["converged"]},
                                            scores=scores))
            summary = {"k4d_pos_mean_mm": statistics.median(means), "k4d_pos_p95_mm": statistics.median(p95s)}
            if ratios:
                summary["ratio_vs_A0"] = statistics.median(ratios.values())
            evaluation = evaluation_digest_v2(cell, cell_id, algorithm)
            out.append(bbo.ScoredRun(
                black_box=algorithm,
                version={"git_shas": _unique(s["git_sha"] for s in cell["seeds"]),
                         "code_hashes": _unique(s["code_hash"] for s in cell["seeds"])},
                environment=cell_id, episodes=episodes, summary=summary,
                attributes={"run_id": run_id("kincal-weave", "v2", cell_id, algorithm, evaluation)}))
    return out


def log(compact: dict, *, weave: bool = True) -> dict:
    batch = records(compact)
    runs = push(batch, project=PROJECT)
    retired = sum(retire(record["config"]["result_id"], record["config"]["evaluation"], project=PROJECT) for record in batch)
    board = None
    if weave:
        from .rigs import load_bbo  # noqa: PLC0415 -- bbo by file, the house template on bam_ws main

        bbo = load_bbo()
        # WHY both off: never delete anything in Zach's W&B (see the module docstring)
        bbo.delete_unended = lambda client: 0
        bbo.prune_superseded = lambda client, runs, columns=None: 0
        entity_project = f"{ENTITY}/{PROJECT}"
        refs = bbo.log_evaluations(entity_project, scored_runs(bbo, compact), scorers=SCORERS)
        metrics = [bbo.Metric(title, key, minimize=minimize) for title, key, minimize in COLUMNS]
        board = bbo.publish_leaderboard(
            entity_project, LEADERBOARD,
            "Zach's kinematic-calibration simulation (bam_calibration v2): UR's own dual-arm method (patent US 9,248,573) and its "
            "variants as black boxes on UR's calibration horse; K4d position error of the worst arm, per cell, over seeds.",
            refs, metrics, list(compact["v2"]))
    return {"project": PROJECT, "runs": len(runs), "new": sum(1 for r in runs if not r["resumed"]), "retired": retired,
            "urls": {r["name"]: browser_url(r["url"]) for r in runs}, "leaderboard": board}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("extract", help="the raw ledgers -> the compact JSON")
    pull.add_argument("--v1", type=Path, required=True)
    pull.add_argument("--v2", type=Path, action="append", required=True, help="repeatable; ledgers are unioned, newest row per (cell, seed) wins")
    pull.add_argument("--out", type=Path, required=True)
    push_ = commands.add_parser("log", help="the compact JSON -> W&B")
    push_.add_argument("compact", type=Path)
    push_.add_argument("--no-weave", action="store_true")
    push_.add_argument("--out", type=Path, help="write what was logged (run URLs, the leaderboard ref) here")
    args = parser.parse_args(argv)
    if args.command == "extract":
        data = extract(args.v1, args.v2)
        args.out.write_text(json.dumps(data, separators=(",", ":")) + "\n")
        print(json.dumps({"out": str(args.out), "bytes": args.out.stat().st_size, "v1": data["sources"]["v1"]["kept"],
                          "v2": data["sources"]["v2"]["kept"], "v1_cells": len(data["v1"]), "v2_cells": len(data["v2"])}))
        return 0
    summary = log(json.loads(args.compact.read_text()), weave=not args.no_weave)
    text = json.dumps(summary, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
