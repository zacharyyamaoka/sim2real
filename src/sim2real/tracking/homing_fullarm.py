"""W&B project "Homing · bam_fb_v2": the full arm's homing routines scored by the ruler (sim2real.sim.homing.routine_ruler) - one run per
routine x environment, from one routine_check results JSON; nothing recomputed but the ruler's own cards.

    env -u VIRTUAL_ENV /home/bam/sim2real/.venv/bin/python -m sim2real.tracking.homing_fullarm /home/bam/sim2real/src/sim2real/data/homing_routine_2026-11-13.json --replays /home/bam/.cache/sim2real/homing_routine/replays.json

A run carries: config = the routine (its row in fullarm_routine.ROWS), the environment (its hidden truth, in words), the plant, the ruler,
the code shas, how many grid cells it ran; summary = the ruler's card (coverage, outcomes, zero error p95 per joint, repeatability, backlash,
time, belt, speed ratio, every target's pass / fail as 1 / 0); tables = ``starts`` (one row per start: its cell, outcome, zeros, belt,
witness) and ``metrics`` (the card, one row); media = ``coverage_map`` (routine_figures' PNG); and, when the results' replays index names
one, the run's Rerun replay through ``data_recorder.runlink.log_to_wandb`` (the run's typical episode) plus a ``replays`` table of the
others' links.

The project's report ("Homing · bam_fb_v2 — routines") holds the runs table, a parallel-coordinates plot over the targets, coverage and
time bars, and the coverage maps (``build_report``).

WHY one run per routine x environment and not per episode (Zach, 16:50: "create a W&B track for this homing routine"): the ruler scores a
routine over a grid; an episode is a row of that run's ``starts`` table. WHY nothing deleted (sim2real.tracking.homing's rule): a re-run of
the same numbers maps to the same run ids; a changed number makes a new evaluation and the older runs are marked superseded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .homing import _tag
from .wandb_log import ENTITY, WANDB_DIR, _clean, _save_report, _table_rows, browser_url, retire, run_id

PROJECT = "Homing · bam_fb_v2"
REPORT_TITLE = "Homing · bam_fb_v2 — routines"
DATA_RECORDER_SRC = Path("/home/bam/data_recorder/src")
MEDIA = Path.home() / ".cache" / "sim2real" / "homing_routine" / "wandb_media"
REGISTRY = Path(__file__).resolve().parent / "homing_fullarm_views.json"  # the report's URL, so a rebuild updates it in place
STARTS_COLUMNS = ("start", "five_bar", "W1_deg", "W2_deg", "W3_deg", "claw_deg", "J1_deg", "outcome", "covered", "time_s",
                  "zero_J2_deg", "zero_C1_deg", "zero_W1_deg", "zero_W2_deg", "zero_W3_deg", "zero_CLAW_deg", "belt_drag_s",
                  "belt_after_liftoff_ticks", "self_contact_ticks", "witness_deg", "detail")


def _flat(card: dict) -> dict:
    out = {}
    for key, value in card.items():
        if key in ("outcomes", "verdict") or isinstance(value, dict):
            continue
        if isinstance(value, bool):
            out[key] = int(value)
        elif isinstance(value, (int, float)) and value is not None:
            out[key] = value
    for name, count in (card.get("outcomes") or {}).items():
        out[f"outcomes/{name}"] = count
    for group in ("zero_error_p95_deg_by_joint", "repeatability_deg_by_joint"):
        for joint, value in (card.get(group) or {}).items():
            if value is not None:
                out[f"{group.removesuffix('_by_joint')}/{joint}"] = value
    for target, passed in (card.get("verdict") or {}).items():
        if passed is not None:
            out[f"target/{target}"] = int(bool(passed))
    return out


def _start_row(r: dict) -> dict:
    from sim2real.sim.homing.routine_figures import display_class  # noqa: PLC0415

    cell = r.get("cell") or {}
    start = r.get("start", "")
    parts = dict(zip(("W1", "W2", "W3", "claw", "J1"), _parse_levels(start)))
    zero = r.get("zero_error_deg") or {}
    return {"start": start, "five_bar": cell.get("fivebar", r.get("family", "")), "W1_deg": parts.get("W1"), "W2_deg": parts.get("W2"),
            "W3_deg": parts.get("W3"), "claw_deg": parts.get("claw"), "J1_deg": parts.get("J1"), "outcome": display_class(r),
            "covered": bool(r.get("covered")), "time_s": r.get("time_s"),
            **{f"zero_{j}_deg": zero.get(j) for j in ("J2", "C1", "W1", "W2", "W3", "CLAW")},
            "belt_drag_s": r.get("belt_drag_s"), "belt_after_liftoff_ticks": r.get("belt_after_liftoff_ticks"),
            "self_contact_ticks": r.get("self_contact_ticks"), "witness_deg": json.dumps(r.get("witness_deg") or {}),
            "detail": str(r.get("refused_start") or (r.get("outcome") if r.get("outcome") != "done" else ""))[:300]}


def _parse_levels(name: str) -> list:
    """routine_ruler.grid_cells' name -> [W1, W2, W3, claw, J1] (deg)."""
    words = name.split()
    out = []
    for key in ("W1", "W2", "W3", "claw", "J1"):
        try:
            out.append(float(words[words.index(key) + 1]))
        except (ValueError, IndexError):
            out.append(None)
    return out


def evaluation_digest(card: dict, episodes: list[dict], results: dict) -> str:
    payload = {"card": card, "episodes": sorted((e.get("key"), e.get("outcome_class"), e.get("time_s")) for e in episodes),
               "code": [results.get("sim2real_sha"), results.get("bam_ws_sha")]}
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:10]


def records(results: dict, *, replays: dict | None = None) -> list[dict]:
    """One W&B run record per (routine, environment) card (wandb_log.push's shape, plus ``images`` and ``replay``)."""
    from sim2real.sim.homing.fullarm_routine import ROWS  # noqa: PLC0415
    from sim2real.sim.homing.routine_figures import coverage_png  # noqa: PLC0415

    replays = replays or {}
    out = []
    for key, card in results["cards"].items():
        routine, environment = key.split(" | ")
        episodes = [e for e in results["episodes"] if e.get("row") == routine and e.get("environment") == environment]
        evaluation = evaluation_digest(card, episodes, results)
        result_id = f"homing-bam_fb_v2-{routine}-{environment}"
        png = coverage_png(results["episodes"], routine, environment,
                           MEDIA / f"{hashlib.sha1(key.encode()).hexdigest()[:12]}_{evaluation}.png")
        spec = {k: v for k, v in ROWS.get(routine, {}).items()}
        config = {"routine": routine, "environment": environment, "environment_why": results["environments"].get(environment),
                  "routine_spec": spec, "plant": results.get("plant"), "ruler": results.get("ruler"), "targets": results.get("targets"),
                  "sim2real_sha": results.get("sim2real_sha"), "bam_ws_sha": results.get("bam_ws_sha"), "bundle": results.get("bundle"),
                  "cells_run": card.get("cells"), "feasible": card.get("feasible"), "result_id": result_id, "evaluation": evaluation,
                  "evaluation_state": "latest", "rig": "bam_fb_v2", "wrist_pose": "five-bar home" if "PEP 0047" in routine else "READY"}
        numbers = _flat(card)
        replay = replays.get(key) or {}
        out.append({"id": run_id("homing-bam_fb_v2", routine, environment, evaluation), "name": f"{routine} · {environment}",
                    "group": environment, "job_type": "homing-routine",
                    "tags": ["homing", "bam_fb_v2", environment, _tag(routine), "latest"] + (["passes"] if card["verdict"]["pass"] else []),
                    "notes": f"{routine} on the bam_fb_v2 twin, {environment}: {results['environments'].get(environment)}",
                    "config": config, "history": [numbers], "summary": numbers,
                    "tables": {"starts": [_start_row(e) for e in episodes], "metrics": [numbers],
                               "replays": replay.get("table") or []},
                    "images": {"coverage_map": str(png)}, "replay": replay.get("typical")})
    return out


def push(batch: list[dict], *, entity: str = ENTITY, project: str = PROJECT) -> list[dict]:
    """wandb_log.push's rule (an existing run gets only what it lacks), plus the coverage map image and the Rerun replay link."""
    import wandb  # noqa: PLC0415

    WANDB_DIR.mkdir(parents=True, exist_ok=True)
    api = wandb.Api(timeout=60)
    if str(DATA_RECORDER_SRC) not in sys.path:
        sys.path.append(str(DATA_RECORDER_SRC))
    from data_recorder.runlink import log_to_wandb  # noqa: PLC0415 - stdlib only, from its file

    logged = []
    for record in batch:
        try:
            have = dict(api.run(f"{entity}/{project}/{record['id']}").summary)
        except Exception:  # noqa: BLE001 - wandb raises CommError / ValueError for a run that does not exist yet
            have = None
        run = wandb.init(entity=entity, project=project, id=record["id"], name=record["name"], group=record["group"],
                         job_type=record["job_type"], tags=record["tags"], notes=record["notes"], config=record["config"],
                         resume="allow", reinit="create_new", allow_val_change=True, dir=str(WANDB_DIR),
                         settings=wandb.Settings(silent=True, console="off"))
        values = _clean(dict(record["history"][-1]))
        if have is None:
            for name, rows in record["tables"].items():
                if rows:
                    columns, data = _table_rows(rows)
                    values[name] = wandb.Table(columns=columns, data=data, allow_mixed_types=True)
            for name, path in record["images"].items():
                values[name] = wandb.Image(path, caption=record["name"])
            run.log(values)
        else:
            missing = {k: v for k, v in values.items() if k not in have}
            if missing:
                run.log(missing)
        run.summary.update(record["summary"])
        links = log_to_wandb(run, record["replay"]) if record.get("replay") else {}
        logged.append({"id": run.id, "url": browser_url(run.url), "name": record["name"], "resumed": have is not None, "replay": links})
        run.finish()
    return logged


def build_report(results: dict, *, entity: str = ENTITY, project: str = PROJECT) -> str:
    """The project's report: the runs table, parallel coordinates over the targets, coverage and time bars, the coverage maps."""
    import wandb_workspaces.reports.v2 as wr  # noqa: PLC0415
    from wandb_workspaces.reports.v2 import expr  # noqa: PLC0415

    L = wr.Layout  # noqa: N806

    def runset(name: str, *filters):
        return wr.Runset(entity=entity, project=project, name=name, filters=[expr.Config("evaluation_state") == "latest", *filters])

    nominal = runset("nominal", expr.Config("environment") == "nominal")
    every = runset("every environment")
    columns = [wr.ParallelCoordinatesPlotColumn(metric=wr.SummaryMetric(m)) for m in
               ("coverage_pct", "silent_wrong", "zero_error_p95_deg", "repeatability_deg", "backlash_error_p95_arcmin", "time_to_home_median_s",
                "belt_after_liftoff", "peak_speed_ratio")]
    blocks = [
        wr.MarkdownBlock(text=(
            "**What a good home is** (the ruler, frozen before any routine ran: `sim2real.sim.homing.routine_ruler`): **0 silent wrong** in "
            "every environment; **coverage ≥ 95 %** of the feasible start grid on the nominal twin (≥ 90 % in each perturbed one) - homed with "
            "every zero within 0.1° and nothing pressing the belt after lift-off; zero error p95 ≤ 0.1°; repeatability ≤ 0.02°; median time "
            "≤ 60 s (p95 ≤ 90 s); peak speed ≤ 0.8 × each joint's ceiling. Rank by silent wrong, then coverage, then zero error, then time. "
            "The grid: 4 five-bar poses × W1 × W2 (6 × 6) with W3, the claw and J1 balanced over it - where the arm was when the power went; "
            "the twin lets it fall onto the belt first. Sim only (MuJoCo, bam_fb_v2 bundle @ cad-exporter 09374d7).")),
        wr.PanelGrid(hide_run_sets=False, runsets=[nominal],
                     panels=[wr.ParallelCoordinatesPlot(title="Every routine against every target (nominal twin)", columns=columns,
                                                        layout=L(x=0, y=0, w=24, h=10)),
                             wr.BarPlot(title="Coverage of the start grid (%)", metrics=["coverage_pct"], orientation="h",
                                        max_bars_to_show=20, layout=L(x=0, y=10, w=12, h=9)),
                             wr.BarPlot(title="Median time to home (s)", metrics=["time_to_home_median_s"], orientation="h",
                                        max_bars_to_show=20, layout=L(x=12, y=10, w=12, h=9)),
                             wr.BarPlot(title="Silent wrong (episodes)", metrics=["silent_wrong"], orientation="h",
                                        max_bars_to_show=20, layout=L(x=0, y=19, w=12, h=9)),
                             wr.BarPlot(title="Zero error p95 (°)", metrics=["zero_error_p95_deg"], orientation="h",
                                        max_bars_to_show=20, layout=L(x=12, y=19, w=12, h=9)),
                             wr.MediaBrowser(media_keys=["coverage_map"], num_columns=1, layout=L(x=0, y=28, w=24, h=24))]),
        wr.MarkdownBlock(text="**Perturbed twins** (hidden B1 / B2 gaps, the wrist's breakaway friction, a 0.50 kg claw, the witness's "
                              "calibration 1.5° off, another power-up frame) on every 6th grid cell."),
        wr.PanelGrid(hide_run_sets=False, runsets=[every],
                     panels=[wr.ParallelCoordinatesPlot(title="Every routine x environment", columns=columns, layout=L(x=0, y=0, w=24, h=10)),
                             wr.BarPlot(title="Coverage by environment (%)", metrics=["coverage_pct"], groupby=wr.Config("environment"),
                                        groupby_aggfunc="mean", groupby_rangefunc="minmax", orientation="v", max_bars_to_show=20,
                                        layout=L(x=0, y=10, w=24, h=9))]),
    ]
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.is_file() else {}
    url = _save_report(wr, entity, project, registry.get("report"), REPORT_TITLE,
                       "The full arm's homing routines, scored on the twin by the frozen ruler (sim only).", blocks)
    REGISTRY.write_text(json.dumps({**registry, "report": url}, indent=1) + "\n")
    return url


def log(results: dict, *, replays: dict | None = None, report: bool = True) -> dict:
    batch = records(results, replays=replays)
    runs = push(batch)
    retired = sum(retire(r["config"]["result_id"], r["config"]["evaluation"], project=PROJECT) for r in batch)
    url = build_report(results) if report else None
    return {"project": PROJECT, "project_url": browser_url(f"https://wandb.ai/{ENTITY}/{PROJECT.replace(' ', '%20')}"), "runs": len(runs),
            "new": sum(1 for r in runs if not r["resumed"]), "retired": retired, "report": url,
            "urls": {r["name"]: r["url"] for r in runs}, "replays": {r["name"]: r["replay"] for r in runs if r["replay"]}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--replays", type=Path, help="routine card key -> {typical: .rrd, table: [...]} (homing_routine_media)")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    replays = json.loads(args.replays.read_text()) if args.replays and args.replays.is_file() else None
    summary = log(json.loads(args.results.read_text()), replays=replays, report=not args.no_report)
    text = json.dumps(summary, indent=1, default=str)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
