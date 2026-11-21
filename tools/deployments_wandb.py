"""The One Dof Test Rack's W&B view: the summary across its runs first, then every run, each with a Rerun link that opens.

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python /home/bam/sim2real/tools/deployments_wandb.py

    ... --dry-run     build the tables and print the headline; write nothing
    ... --verify      read the project and the report back through the API, HEAD-check three Rerun links through 8771

Zach (Daily Note 2026-11-18, "# Ok back to performance metrics"): "go on weights and biases and go the 1 dof rack/pendulum deployment. I want
to be able to see the summary statistics accross a bunch of runs. Then I want to be able to drill down and look at a specific run". His
3000-ft view (memory deployment-view-3000ft, 11-17): performance first; runs are the atomic unit; one W&B project per deployment is the
store; Rerun links only through the always-on launcher on 127.0.0.1:8771, never the campaign's 9461/9462 web viewer (dead when not served).

What a sync writes into the deployment's project ("Sim2Real · 1-DOF rack", bam_ws tools/wandb_trackers/trackers/sim2real_1_dof_rack.py):
- the summary run (id `deployment-summary`, group deployment-summary): the latest round's headline as summary numbers (now/*), and the
  goal lines across the rounds as history steps, one per round (x = `round`: each station's tracking RMS and tip stop at 0.9 of top
  speed beside the round's own goal, the share of runs meeting the goal, each station's median and p95 run);
- one run per round (id `deployment-summary-r<n>`): that round's headline and per-station numbers as summary scalars. WHY not one W&B
  run per rig run: 2485 runs would bury the project, and a rig run's drill-down is its Rerun recording, one click from its row;
- the report "1-DOF rack · where we stand": the summary first, the round-by-round numbers, then where every run is kept, then the
  per-station panels.

WHY the tables are local (Zach, 2026-11-21: "to help limit W and B storage I think we need to just be using it for summary statistics;
for the media-rich things we should be using rerun!"): the project held ~17 MB of runs-table artifacts per sync. The drill-down - one
row per run of every scored round, its `rerun` cell the 8771 link or "no recording yet" (never a dead link) - and the round and station
roll-ups are jsonl under LOCAL (runs.jsonl, by_round.jsonl, by_round_station.jsonl, lines.jsonl; r<n>/runs.jsonl per round), each W&B
run's config names its folder (`local_tables`) and its summary carries the row counts (`rows/<table>`). The sim2real app's Runs view
shows the same rows.

WHY a copy: W&B is a copy of a local ledger (vault memory project_wandb_trackers). Every number comes from sim2real.deployments_page (runs(),
read_round(), performance(), history()), which reads the campaign's scorecards read-only; this file only rolls them up. The links come from
data_recorder.runlink (each .rrd registered once, the launcher's URL). WHY idempotent this way: fixed run ids, resumed; a sync whose numbers
did not change writes nothing (a digest in each run's summary), a changed one logs one more step, so the panels show the latest and nothing
piles up. The campaign's own runs (group one-dof-test-rack) are never touched. The report keeps its id (STATE), so its link never changes.

Held by tools/tests/test_deployments_wandb.py (a two-round synthetic campaign, every roll-up worked by hand).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sim2real import deployments_page as dp  # noqa: E402
from sim2real import paths  # noqa: E402
from sim2real.tracking.wandb_log import ENTITY, WANDB_DIR, project_dir, write_tables  # noqa: E402 - stdlib only at import

PROJECT = "Sim2Real · 1-DOF rack"
GROUP = "deployment-summary"
SUMMARY_ID = "deployment-summary"
SUMMARY_NAME = "1-DOF rack · where we stand"
ROUND_JOB = "round_summary"
REPORT_TITLE = "1-DOF rack · where we stand"
STATE = Path.home() / ".local" / "state" / "sim2real" / "deployments-wandb.json"
# the runs table and the roll-ups, kept on this computer (LOCAL/<project>/...); W&B gets the folder and the row counts
LOCAL = Path.home() / ".cache" / "sim2real" / "deployments_wandb"
# the sim2real app's Runs view of the rack (Stable channel, :4820): the same rows, each opening its Rerun recording
RUNS_VIEW = f"http://127.0.0.1:4820/deployments/?d={dp.DEPLOYMENT}&view=runs"
# WHY a schema in every run's digest: the 2026-11-21 move to scalars must rewrite each run once even where the campaign did not change
SCHEMA = "deployments-wandb/2 summary-only 2026-11-21"
# WHY the /wandb prefix by hand: the app lives at forge.coreweave.com/wandb and wandb-workspaces' Report.url drops it (bam_interventions)
WEB = "https://forge.coreweave.com/wandb"
NO_RECORDING = "no recording yet"
NO_LAUNCHER = "recorded; no 8771 launcher on this computer"

# The runs table, in the order a reader wants it: what the run was, how it did against the target, the link, then the rest of its metadata.
# WHY the stop columns are the RUNG's: the scorer measures the tip stop per rung (median, p95, max over its stops), not per play.
RUN_COLUMNS = (
    "round", "station", "rung", "speed_deg_s", "kind", "tracks", "tracking_rms_deg", "tracking_peak_deg",
    "rung_stop_mm", "rung_stop_worst_mm", "rung_stop", "rerun",
    "sim_tracking_rms_deg", "sim_vs_real_deg", "tape_rms_deg", "stops", "fault", "status", "seed",
    "name", "controller", "twin", "scored_utc", "motor", "load", "run", "rrd", "rrd_via",
)
STAT_COLUMNS = (
    "runs", "recordings", "tracking_rms_median_deg", "tracking_rms_p95_deg", "tracking_peak_worst_deg", "worst_stop_mm",
    "stop_at_goal_mm", "share_meeting_goal", "share_tracking_ok",
)
ROUND_COLUMNS = ("round", "scored_utc", "controller", "twin", "goal_met", "gates_passed", "gates_total", "perf_gates_passed",
                 "perf_gates_total", "stations_at_goal", *STAT_COLUMNS)
STATION_COLUMNS = ("round", "station", "motor", "passes_up_to", "perf_gates_passed", "perf_gates_total", *STAT_COLUMNS)


# ---------------------------------------------------------------------------------------------------------------- numbers (pure)


def percentile(values, q: float) -> float | None:
    """Linear-interpolated percentile (numpy's default) of the finite values; None when there are none."""
    xs = sorted(v for v in (dp.finite(v) for v in values) if v is not None)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def read_rounds(scorecards: Path = dp.SCORECARDS, now: str = dp.NOW_FILE) -> dict[int, dict]:
    """Every scored round (deployments_page.scored_rounds), read by deployments_page.read_round, with its performance() beside it."""
    out = {}
    for n, path in dp.scored_rounds(scorecards, now)[0]:
        rd = dp.read_round(f"r{n}", path)
        out[n] = {**rd, "performance": dp.performance(rd)}
    return out


def run_rows(runs: list[dict], rounds: dict[int, dict], urls: dict[str, str | None]) -> list[dict]:
    """deployments_page.runs()'s rows as the runs table: each with its rung's stop numbers, its round's controller and twin, its station's
    motor and load, and `rerun`: the launcher link of its recording (`urls`: rrd -> link), else why there is none. Speeds in deg/s (Zach
    reads angles in degrees; the data stays SI)."""
    out = []
    for row in runs:
        rd = rounds[row["round"]]
        rung = {r["fraction"]: r for r in rd["stations"][row["station"]]["rungs"]}.get(row["fraction"]) or {}
        facts = dp.STATION_FACTS.get(row["station"], {})
        speed = dp.finite(row.get("speed_rad_s"))
        if row.get("rrd"):
            rerun = urls.get(row["rrd"]) or NO_LAUNCHER
        else:
            rerun = NO_RECORDING
        out.append({
            "round": row["round"], "station": row["station"], "rung": row["fraction"],
            "speed_deg_s": None if speed is None else round(math.degrees(speed), 1), "kind": row.get("kind"), "tracks": row["tracks"],
            "tracking_rms_deg": row["tracking_rms_deg"], "tracking_peak_deg": row["tracking_peak_deg"],
            "rung_stop_mm": rung.get("stop_tool_mm"), "rung_stop_worst_mm": rung.get("stop_tool_max_mm"),
            "rung_stop": (rung.get("gates") or {}).get("target_vs_real_stop", "not_run"), "rerun": rerun,
            "sim_tracking_rms_deg": row.get("sim_tracking_rms_deg"), "sim_vs_real_deg": row.get("sim_vs_real_deg"),
            "tape_rms_deg": row.get("tape_rms_deg"), "stops": row.get("stops"), "fault": bool(row.get("fault")), "status": row.get("status"),
            "seed": row.get("seed"), "name": row["name"], "controller": rd.get("controller"), "twin": rd.get("twin"),
            "scored_utc": rd.get("scored_utc"), "motor": facts.get("motor"), "load": facts.get("load"), "run": row["run"],
            "rrd": row.get("rrd"), "rrd_via": row.get("rrd_via"),
        })
    return out


def stats(rows: list[dict], stations: list[dict]) -> dict:
    """The roll-up of some runs (`rows`) and the stations they ran on (read_round's station dicts): run and recording counts, median and
    p95 tracking RMS, the worst instant, the worst stop at any rung, the median stop at the goal's rung (the worst station's), the share
    of runs meeting the goal (the tracking gate, at rungs up to the goal's 0.9 of top speed) and the share meeting the tracking gate at
    every rung."""
    judged = [r for r in rows if r["tracks"] in ("pass", "fail")]
    to_goal = [r for r in judged if r["rung"] <= dp.GOAL_FRACTION + 1e-9]
    worst = [r["stop_tool_max_mm"] for st in stations for r in st["rungs"] if r["stop_tool_max_mm"] is not None]
    at_goal = [r["stop_tool_mm"] for st in stations for r in st["rungs"]
               if abs(r["fraction"] - dp.GOAL_FRACTION) < 1e-9 and r["stop_tool_mm"] is not None]
    peaks = [r["tracking_peak_deg"] for r in rows if r["tracking_peak_deg"] is not None]
    median = percentile([r["tracking_rms_deg"] for r in rows], 0.5)
    p95 = percentile([r["tracking_rms_deg"] for r in rows], 0.95)
    return {
        "runs": len(rows), "recordings": sum(1 for r in rows if r.get("rrd")),
        "tracking_rms_median_deg": dp.rounded(median), "tracking_rms_p95_deg": dp.rounded(p95),
        "tracking_peak_worst_deg": max(peaks) if peaks else None, "worst_stop_mm": max(worst) if worst else None,
        "stop_at_goal_mm": max(at_goal) if at_goal else None,
        "share_meeting_goal": share(sum(1 for r in to_goal if r["tracks"] == "pass"), len(to_goal)),
        "share_tracking_ok": share(sum(1 for r in judged if r["tracks"] == "pass"), len(judged)),
    }


def round_rows(rows: list[dict], rounds: dict[int, dict]) -> list[dict]:
    """One row per round: the scorecard's own headline (goal met, cell gates, real performance gates, stations at the goal) beside stats()."""
    out = []
    for n, rd in sorted(rounds.items()):
        mine = [r for r in rows if r["round"] == n]
        goal = rd["goal"]
        at_goal = sum(1 for st in rd["stations"].values() if st["max_trackable_fraction"] >= dp.GOAL_FRACTION - 1e-9 and st["twin_ok"])
        out.append({"round": n, "scored_utc": rd.get("scored_utc"), "controller": rd.get("controller"), "twin": rd.get("twin"),
                    "goal_met": bool(goal.get("goal_met")), "gates_passed": goal.get("gates_passed"), "gates_total": goal.get("gates_total"),
                    "perf_gates_passed": rd["performance"]["passed"], "perf_gates_total": rd["performance"]["of"],
                    "stations_at_goal": at_goal, **stats(mine, list(rd["stations"].values()))})
    return out


def station_rows(rows: list[dict], rounds: dict[int, dict]) -> list[dict]:
    """One row per (round, station): how far up its ladder it tracks and stops (passes_up_to), its real performance gates, and stats()."""
    out = []
    for n, rd in sorted(rounds.items()):
        for sid in dp.STATIONS:
            st = rd["stations"][sid]
            p, of = dp.perf_gates(st)
            mine = [r for r in rows if r["round"] == n and r["station"] == sid]
            out.append({"round": n, "station": sid, "motor": dp.STATION_FACTS.get(sid, {}).get("motor"),
                        "passes_up_to": st["max_trackable_fraction"], "perf_gates_passed": p, "perf_gates_total": of,
                        **stats(mine, [st])})
    return out


def label(sid: str) -> str:
    return f"CAN {sid[3:]}" if sid.startswith("can") else sid


def goal_lines(history: list[dict], rounds: dict[int, dict]) -> dict[str, dict]:
    """The goal-line charts across the rounds, as line-series rows (step = round, lineKey, lineVal; a value not measured is left out,
    never drawn as 0): each station's tracking RMS and tip stop at the goal's rung (0.9 of its top speed; deployments_page.history(), the
    scorer's numbers) with each round's own goal (its scorecard's thresholds) drawn as a line beside them."""
    track, stop = [], []
    for h in history:
        n, t = h["round"], rounds[h["round"]]["thresholds"]
        for sid in dp.STATIONS:
            s = h["stations"][sid]
            if s["tracking_rms_09"] is not None:
                track.append([n, label(sid), s["tracking_rms_09"]])
            if s["stop_09"] is not None:
                stop.append([n, label(sid), s["stop_09"]])
        track.append([n, f"goal ≤ {t['tracking_rms_deg']:g}°", t["tracking_rms_deg"]])
        stop.append([n, f"goal ≤ {t['stop_tool_mm']:g} mm", t["stop_tool_mm"]])
    return {
        "chart/tracking_rms_at_goal": {"title": "Tracking RMS (°) at 0.9 of top speed, per station, vs the goal", "rows": track},
        "chart/stop_at_goal": {"title": "Tip stop (mm, median) at 0.9 of top speed, per station, vs the goal", "rows": stop},
    }


def share_lines(by_round: list[dict], by_station: list[dict]) -> dict[str, dict]:
    rows = [[r["round"], "all stations", r["share_meeting_goal"]] for r in by_round if r["share_meeting_goal"] is not None]
    rows += [[r["round"], label(r["station"]), r["share_meeting_goal"]] for r in by_station if r["share_meeting_goal"] is not None]
    return {"chart/share_meeting_goal": {"title": "Share of runs meeting the tracking goal (rungs up to 0.9 of top speed)", "rows": rows}}


def station_lines(by_station: list[dict], rounds: dict[int, dict]) -> dict[str, dict]:
    """Per station: its runs' median and p95 tracking RMS per round, with the goal beside them (the report's per-station panels)."""
    out = {}
    for sid in dp.STATIONS:
        rows = []
        for r in (r for r in by_station if r["station"] == sid):
            goal = rounds[r["round"]]["thresholds"]["tracking_rms_deg"]
            if r["tracking_rms_median_deg"] is not None:
                rows.append([r["round"], "median run", r["tracking_rms_median_deg"]])
            if r["tracking_rms_p95_deg"] is not None:
                rows.append([r["round"], "p95 run", r["tracking_rms_p95_deg"]])
            rows.append([r["round"], f"goal ≤ {goal:g}°", goal])
        facts = dp.STATION_FACTS.get(sid, {})
        out[f"station/{sid}/tracking_rms"] = {"title": f"{label(sid)} · {facts.get('plain', '')}: runs' tracking RMS (°) per round",
                                               "rows": rows}
    return out


def series_id(line: str) -> str:
    """A chart line's stable key: "CAN 11" -> "can11", "goal ≤ 0.5°" -> "goal" (one line even when a round's goal number moves),
    "all stations" -> "all", "median run" -> "median", "p95 run" -> "p95"."""
    if line.startswith("goal"):
        return "goal"
    if line.startswith("CAN "):
        return "can" + line[4:]
    return {"all stations": "all", "median run": "median", "p95 run": "p95"}.get(line, re.sub(r"[^A-Za-z0-9]+", "_", line).strip("_"))


def round_steps(charts: dict[str, dict]) -> list[dict]:
    """The charts' lines as W&B history steps, one per round: {"round": n, "<chart>/<line>": value}, e.g.
    "chart/tracking_rms_at_goal/can11" beside "chart/tracking_rms_at_goal/goal". A value not measured is left out (never 0), as in the
    charts. WHY steps of scalars (Zach, 2026-11-21: W&B is for summary statistics): a line plot over x = `round` draws what the
    line-series tables drew, with no table stored."""
    by_round: dict[int, dict] = {}
    for key, spec in charts.items():
        for n, line, value in spec["rows"]:
            by_round.setdefault(n, {"round": n})[f"{key}/{series_id(line)}"] = value
    return [by_round[n] for n in sorted(by_round)]


def headline(r: dict) -> str:
    """One sentence for a round, performance first."""
    goal = "goal met" if r["goal_met"] else "goal not met"
    pct = "n/a" if r["share_meeting_goal"] is None else f"{r['share_meeting_goal']:.0%}"
    return (f"Round {r['round']} ({str(r['scored_utc'])[:10]}, controller {r['controller']}): {goal}, {r['stations_at_goal']} of "
            f"{len(dp.STATIONS)} stations tracking through 0.9 of top speed with the twin passing; real performance gates "
            f"{r['perf_gates_passed']} of {r['perf_gates_total']}, all cell gates {r['gates_passed']} of {r['gates_total']}; {pct} of runs "
            f"up to 0.9 meet the tracking gate; median run tracking RMS {r['tracking_rms_median_deg']}°, p95 {r['tracking_rms_p95_deg']}°; "
            f"worst stop {r['worst_stop_mm']} mm; {r['recordings']} of {r['runs']} runs recorded.")


def payload(runs: list[dict], rounds: dict[int, dict], history: list[dict], urls: dict[str, str | None]) -> dict:
    """Everything a sync logs, built from deployments_page's rows and rounds (pure: no W&B, no files)."""
    rows = run_rows(runs, rounds, urls)
    by_round = round_rows(rows, rounds)
    by_station = station_rows(rows, rounds)
    charts = {**goal_lines(history, rounds), **share_lines(by_round, by_station), **station_lines(by_station, rounds)}
    return {"rows": rows, "by_round": by_round, "by_station": by_station, "charts": charts, "steps": round_steps(charts),
            "now": by_round[-1] if by_round else None,
            "links": {"rows": len(rows), "with_link": sum(1 for r in rows if r["rerun"].startswith("http")),
                      "no_recording": sum(1 for r in rows if r["rerun"] == NO_RECORDING),
                      "no_recording_by_round": {str(n): sum(1 for r in rows if r["round"] == n and r["rerun"] == NO_RECORDING)
                                                for n in sorted(rounds)}}}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------------------------- links


def runlink():
    """data_recorder.runlink (stdlib only), from its checkout; None when it is not on this machine."""
    src = paths.DATA_RECORDER / "src"
    if not (src / "data_recorder" / "runlink.py").is_file():
        return None
    if str(src) not in sys.path:
        sys.path.append(str(src))
    from data_recorder import runlink as rl  # noqa: PLC0415

    return rl


def replay_urls(runs: list[dict], rl=None) -> dict[str, str | None]:
    """Each recording's launcher link (rrd -> http://127.0.0.1:8771/f/<token>/<id>; None without a launcher). Each .rrd is registered
    once (runlink.register: an atomic rewrite of the whole index), so only one not yet in the index is written."""
    rl = rl if rl is not None else runlink()
    out: dict[str, str | None] = {}
    if rl is None:
        return {row["rrd"]: None for row in runs if row.get("rrd")}
    prefix = None
    for row in runs:
        rrd = row.get("rrd")
        if not rrd or rrd in out:
            continue
        key = rl.replay_id(rrd)
        if prefix is None:
            # WHY one links() call: the launcher's URL is the same for every id, so the first link gives the prefix
            url = rl.links(rrd)["replay_url"]
            prefix = url[: -len(key)] if url.endswith("/" + key) else ""
        elif rl.resolve(key) is None:
            rl.register(rrd)
        out[rrd] = (prefix + key) if prefix else None
    return out


# ---------------------------------------------------------------------------------------------------------------- W&B: writes


def code_version() -> str:
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "tools/deployments_wandb.py"], capture_output=True,
                               text=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def flat(prefix: str, row: dict, keys: tuple[str, ...]) -> dict:
    out = {}
    for k in keys:
        v = row.get(k)
        if isinstance(v, bool):
            out[f"{prefix}{k}"] = int(v)
        elif isinstance(v, (int, float)) and v is not None:
            out[f"{prefix}{k}"] = v
    return out


def local_folder(project: str = PROJECT, local: Path | None = None) -> Path:
    """Where a sync keeps the runs table and the roll-ups on this computer: `local`, else LOCAL/<project>."""
    return Path(local) if local is not None else LOCAL / project_dir(project)


def write_local(data: dict, folder: Path) -> dict[str, dict[str, str]]:
    """The drill-down and the roll-ups as jsonl in `folder`: runs.jsonl (one row per run of every scored round, its `rerun` link),
    by_round.jsonl, by_round_station.jsonl, lines.jsonl (the goal lines, one row per round), and r<n>/runs.jsonl, r<n>/by_station.jsonl
    per round. Returns {"all": {table: path}, "r<n>": {table: path}}.

    WHY local (Zach, 2026-11-21: "to help limit W and B storage I think we need to just be using it for summary statistics; for the
    media-rich things we should be using rerun!"): every row is on this computer before W&B hears of it; W&B gets the folder."""
    out = {"all": write_tables(folder, {"runs": data["rows"], "by_round": data["by_round"], "by_round_station": data["by_station"],
                                        "lines": data["steps"]})}
    for r in data["by_round"]:
        n = r["round"]
        out[f"r{n}"] = write_tables(folder / f"r{n}", {"runs": [x for x in data["rows"] if x["round"] == n],
                                                        "by_station": [x for x in data["by_station"] if x["round"] == n]})
    return out


def write_run(api, *, run_id: str, name: str, job_type: str, tags: list[str], notes: str, config: dict, summary: dict, content: Any,
              entity: str, project: str, steps: list[dict] = ()) -> dict:
    """Write one of this tool's runs: unchanged content (its digest already in the run's summary) writes nothing; else the history
    `steps` it does not hold yet (each names its `round`: those after the run's `sync/last_round`) and `summary`. Scalars only.

    WHY scalars only (Zach, 2026-11-21: "to help limit W and B storage I think we need to just be using it for summary statistics; for the
    media-rich things we should be using rerun!"): until then each changed sync logged the runs tables and line-series tables again
    (~17 MB of artifacts a round); they are write_local's jsonl now."""
    import wandb  # noqa: PLC0415

    want = digest({"schema": SCHEMA, "content": content})
    try:
        have = dict(api.run(f"{entity}/{project}/{run_id}").summary)
    except Exception:  # noqa: BLE001 - wandb raises CommError / ValueError for a run that does not exist yet
        have = {}
    if have.get("sync/digest") == want:
        return {"id": run_id, "name": name, "written": False}
    # WHY only the rounds the run lacks: a step's x is its round, so a round logged twice is drawn twice. A round re-scored after it was
    # logged keeps its first point in these lines; its own round run's summary carries the new numbers. A stale read right after a
    # write (the API can still serve the old summary, seen 2026-11-18) re-logs at most the rounds of that one write
    last = have.get("sync/last_round")
    fresh = [step for step in steps if not isinstance(last, (int, float)) or step["round"] > last]
    WANDB_DIR.mkdir(parents=True, exist_ok=True)
    run = wandb.init(entity=entity, project=project, id=run_id, name=name, group=GROUP, job_type=job_type, tags=tags, notes=notes,
                     config=config, resume="allow", reinit="create_new", allow_val_change=True, dir=str(WANDB_DIR),
                     settings=wandb.Settings(silent=True, console="off"))
    for step in fresh:
        run.log({k: v for k, v in step.items() if v is not None})
    rounds = [step["round"] for step in steps]
    run.summary.update({**summary, **({"sync/last_round": max(rounds)} if rounds else {}), "sync/digest": want,
                        "sync/utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    url = run.url
    run.finish()
    return {"id": run_id, "name": name, "written": True, "url": url}


def sync(data: dict, *, entity: str = ENTITY, project: str = PROJECT, scorecards: Path = dp.SCORECARDS, local: Path | None = None) -> list[dict]:
    """The local files first (write_local), then the summary run, then one run per round (see the module docstring)."""
    import wandb  # noqa: PLC0415

    folder = local_folder(project, local)
    write_local(data, folder)
    api = wandb.Api(timeout=60)
    sha = code_version()
    base = {"deployment": dp.DEPLOYMENT, "deployment_label": "One Dof Test Rack", "scorecards": str(scorecards),
            "built_by": "sim2real tools/deployments_wandb.py", "sim2real_sha": sha, "goal_fraction": dp.GOAL_FRACTION, "runs_view": RUNS_VIEW}
    now = data["now"]
    summary_scalars = {**flat("now/", now, ROUND_COLUMNS), "now/headline": headline(now), "links/rows": data["links"]["rows"],
                       "links/with_link": data["links"]["with_link"], "links/no_recording": data["links"]["no_recording"],
                       "rows/runs": len(data["rows"]), "rows/by_round": len(data["by_round"]), "rows/by_round_station": len(data["by_station"])}
    out = [write_run(api, run_id=SUMMARY_ID, name=SUMMARY_NAME, job_type="summary", tags=["deployment-summary", "summary"],
                     notes="The summary across every run of the pendulum campaign; every run with its Rerun link (8771 launcher) is in "
                           f"{folder / 'runs.jsonl'} on the workstation.",
                     config={**base, "rounds": [r["round"] for r in data["by_round"]], "local_tables": str(folder)},
                     summary=summary_scalars, steps=data["steps"], content={k: data[k] for k in ("rows", "by_round", "by_station", "charts")},
                     entity=entity, project=project)]
    lines = {step["round"]: step for step in data["steps"]}
    for r in data["by_round"]:
        n = r["round"]
        rows = [x for x in data["rows"] if x["round"] == n]
        stations = [x for x in data["by_station"] if x["round"] == n]
        scalars = {**flat("", r, ROUND_COLUMNS), "headline": headline(r), "rows/runs": len(rows), "rows/by_station": len(stations)}
        for s in stations:
            scalars.update(flat(f"{s['station']}/", s, STATION_COLUMNS[3:]))
        # the round's own point on each goal line, so a chart over the round runs' summaries draws the same lines
        scalars.update({k: v for k, v in lines.get(n, {}).items() if k != "round" and v is not None})
        out.append(write_run(api, run_id=f"{SUMMARY_ID}-r{n}", name=f"round {n} · {r['controller']}", job_type=ROUND_JOB,
                             tags=["deployment-summary", f"round {n}", *(["goal met"] if r["goal_met"] else [])],
                             notes=headline(r), config={**base, "round": n, "controller": r["controller"], "twin": r["twin"],
                                                        "scored_utc": r["scored_utc"], "local_tables": str(folder / f"r{n}")},
                             summary=scalars, content={"round": r, "rows": rows, "stations": stations}, entity=entity, project=project))
    return out


# ---------------------------------------------------------------------------------------------------------------- W&B: the report


def web_url(entity: str, project: str, title: str, report_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
    return f"{WEB}/{entity}/{urllib.parse.quote(project)}/reports/{slug}--{report_id}"


def project_url(entity: str = ENTITY, project: str = PROJECT) -> str:
    return f"{WEB}/{entity}/{urllib.parse.quote(project)}"


def by_round_markdown(by_round: list[dict]) -> str:
    """The round-by-round numbers as a markdown table (one row per round, a dozen rounds at most): the report's summary across rounds."""
    def cell(value, fmt="{}"):
        return "—" if value is None else fmt.format(value)

    lines = ["| Round | Scored | Controller | Goal | Stations at goal | Real perf gates | Meeting the goal | Median RMS (°) | p95 RMS (°) "
             "| Worst stop (mm) | Recorded |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in by_round:
        lines.append(f"| {r['round']} | {str(r['scored_utc'] or '')[:10]} | {r['controller']} | {'met' if r['goal_met'] else 'not met'} "
                     f"| {r['stations_at_goal']} of {len(dp.STATIONS)} | {r['perf_gates_passed']} of {r['perf_gates_total']} "
                     f"| {cell(r['share_meeting_goal'], '{:.0%}')} | {cell(r['tracking_rms_median_deg'])} | {cell(r['tracking_rms_p95_deg'])} "
                     f"| {cell(r['worst_stop_mm'])} | {r['recordings']} of {r['runs']} |")
    return "\n".join(lines)


def report_blocks(data: dict, *, entity: str = ENTITY, project: str = PROJECT, local: Path | None = None) -> list:
    """The report, charts over scalars only. WHY no table or custom-chart panels (Zach, 2026-11-21: "to help limit W and B storage I think
    we need to just be using it for summary statistics; for the media-rich things we should be using rerun!"): the lines are the summary
    run's history over x = round, the round-by-round numbers a markdown table written at build time, and every run's row a pointer to
    the local jsonl and the sim2real app's Runs view."""
    import wandb_workspaces.reports.v2 as wr  # noqa: PLC0415

    from sim2real.tracking.wandb_log import local_panel  # noqa: PLC0415

    now, links = data["now"], data["links"]
    folder = local_folder(project, local)

    def summary_grid(panels: list):
        return wr.PanelGrid(runsets=[wr.Runset(entity=entity, project=project, name="summary", filters=f"ID in ['{SUMMARY_ID}']")],
                            panels=panels, hide_run_sets=True)

    def line(key: str, w: int = 12, h: int = 9):
        """A chart's lines across the rounds: the summary run's history steps (round_steps), the goal drawn last."""
        spec = data["charts"][key]
        lines = sorted({series_id(name) for _, name, _ in spec["rows"]}, key=lambda one: (one == "goal", one))
        return wr.LinePlot(title=spec["title"], x="round", y=[f"{key}/{one}" for one in lines], title_x="round", layout=wr.Layout(w=w, h=h))

    def tile(metric: str, title: str):
        return wr.ScalarChart(title=title, metric=metric, font_size="large", layout=wr.Layout(w=6, h=4))

    missing = ", ".join(f"round {n}: {c}" for n, c in links["no_recording_by_round"].items() if c) or "none"
    built = dt.datetime.now().astimezone().strftime("%a %b %d %H:%M %Z")
    return [
        wr.CalloutBlock(text=f"Where we stand. {headline(now)}"),
        wr.MarkdownBlock(text=(
            "**Performance first: real vs the target.** Six single-joint pendulums on the One Dof Test Rack, each run up a speed ladder "
            "(0.2 to 1.0 of its top speed). The goal is every station tracking (RMS ≤ 0.5°, worst instant ≤ 1.5°) and stopping its tip "
            "within 1 mm, up to 0.9 of its top speed. A **run** is one play of one rung: the atomic unit. Read the summary across rounds "
            "first, then open the runs (on the workstation) and a run's `rerun` link to open it in Rerun.")),
        wr.H2("Now"),
        summary_grid([tile("now/share_meeting_goal", "Share of runs meeting the goal (to 0.9)"),
                      tile("now/tracking_rms_median_deg", "Median run tracking RMS (°)"),
                      tile("now/perf_gates_passed", f"Real performance gates passed (of {now['perf_gates_total']})"),
                      tile("now/worst_stop_mm", "Worst tip stop (mm)")]),
        wr.H2("Summary across rounds"),
        summary_grid([line("chart/tracking_rms_at_goal"), line("chart/stop_at_goal"), line("chart/share_meeting_goal", w=24, h=8)]),
        wr.MarkdownBlock(text=by_round_markdown(data["by_round"])),
        wr.H2("Every run"),
        wr.MarkdownBlock(text=(
            f"{links['rows']} runs, one row each, kept on the workstation (W&B holds summary statistics only, since 2026-11-21): "
            f"`{folder / 'runs.jsonl'}` (one round: `{folder}/r<n>/runs.jsonl`), and the same rows in the sim2real app's "
            f"[Runs view]({RUNS_VIEW}) (Stable channel). {links['with_link']} have a Rerun recording: the `rerun` field is a link to "
            "127.0.0.1:8771, the always-on launcher on Zach's workstation, which opens the native Rerun viewer there (it works only on "
            f"that computer). {links['no_recording']} runs have no recording yet and say so ({missing}). The stop columns are the run's "
            "rung (the scorer measures stops per rung).")),
        wr.H2("Per station"),
        summary_grid([line(f"station/{sid}/tracking_rms", w=8, h=8) for sid in dp.STATIONS]
                     + [local_panel(wr, "Each station's numbers per round", folder / "by_round_station.jsonl",
                                    layout=wr.Layout(w=24, h=5))]),
        wr.H2("Each round's own page"),
        wr.MarkdownBlock(text=(
            "One W&B run per round (group `deployment-summary`, job type `round_summary`): its headline and each station's numbers in "
            "the summary; its config `local_tables` names the round's runs on the workstation. Click a round's name below to open its "
            "page.")),
        wr.PanelGrid(runsets=[wr.Runset(entity=entity, project=project, name="rounds",
                                        filters=f"Group = '{GROUP}' and JobType = '{ROUND_JOB}'")],
                     panels=[wr.BarPlot(title="Share of runs meeting the goal, per round", metrics=["share_meeting_goal"],
                                        layout=wr.Layout(w=12, h=8)),
                             wr.BarPlot(title="Real performance gates passed, per round", metrics=["perf_gates_passed"],
                                        layout=wr.Layout(w=12, h=8))]),
        wr.MarkdownBlock(text=(
            f"_Built {built} by sim2real `tools/deployments_wandb.py` ({code_version()}) from the campaign's scorecards "
            f"(`{dp.SCORECARDS}`, read-only, through `sim2real.deployments_page`). Re-run it after a round to refresh this page; an "
            "unchanged campaign writes nothing._")),
    ]


def save_report(data: dict, *, entity: str = ENTITY, project: str = PROJECT, state: Path = STATE) -> str:
    """Save the report, in place when STATE holds its id (so its link never changes)."""
    import wandb_workspaces.reports.v2 as wr  # noqa: PLC0415

    try:
        known = json.loads(state.read_text())
    except (OSError, ValueError):
        known = {}
    report = wr.Report(entity=entity, project=project, title=REPORT_TITLE, width="fluid", blocks=report_blocks(data, entity=entity, project=project),
                       description="The 1-DOF rack's pendulum campaign: the summary across every run first, then every run with its Rerun link.")
    if known.get("report_id"):
        report.id = known["report_id"]
    report.save()
    url = web_url(entity, project, REPORT_TITLE, report.id)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"report_id": report.id, "report_url": url, "project_url": project_url(entity, project)}, indent=1) + "\n")
    return url


# ---------------------------------------------------------------------------------------------------------------- checks


def head(url: str, timeout: float = 10.0) -> int:
    """HTTP status of a HEAD request (the launcher answers HEAD without launching anything)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def panel_name(panel) -> str:
    strings = getattr(panel, "chart_strings", None) or {}
    name = getattr(panel, "title", None) or getattr(panel, "table_name", None) or strings.get("title") or getattr(panel, "metric", None)
    return f"{type(panel).__name__}({name or ''})"


def verify(data: dict, *, entity: str = ENTITY, project: str = PROJECT, state: Path = STATE, samples: int = 3,
           local: Path | None = None) -> list[str]:
    """Read back: the summary and round runs exist, the summary's row count matches the local runs.jsonl, the report exists and its panels
    are listed; HEAD-check
    `samples` linked rows (newest round, oldest, middle) through 8771 and resolve each id to its .rrd. Returns the failures."""
    import wandb  # noqa: PLC0415
    import wandb_workspaces.reports.v2 as wr  # noqa: PLC0415

    failures = []
    api = wandb.Api(timeout=60)
    path = f"{entity}/{project}"
    mine = list(api.runs(path, filters={"group": GROUP}))
    print(f"{path}: {len(mine)} runs in group {GROUP}: {sorted(r.id for r in mine)}")
    summary = next((r for r in mine if r.id == SUMMARY_ID), None)
    if summary is None:
        failures.append("no summary run")
    else:
        kept = Path(str(summary.config.get("local_tables") or local_folder(project, local))) / "runs.jsonl"
        lines = sum(1 for line in kept.read_text(encoding="utf-8").splitlines() if line.strip()) if kept.is_file() else None
        print(f"  summary run {summary.url}: {summary.summary.get('rows/runs')} runs ({lines} rows in {kept}), "
              f"now/round {summary.summary.get('now/round')}, links {summary.summary.get('links/with_link')} of {summary.summary.get('links/rows')}")
        if summary.summary.get("rows/runs") != len(data["rows"]) or lines != len(data["rows"]):
            failures.append(f"summary run: rows/runs {summary.summary.get('rows/runs')}, {lines} rows in {kept}, want {len(data['rows'])}")
    rounds = {r.config.get("round") for r in mine if r.job_type == ROUND_JOB}
    if rounds != {r["round"] for r in data["by_round"]}:
        failures.append(f"round runs {sorted(rounds)} != scored rounds {[r['round'] for r in data['by_round']]}")
    known = json.loads(state.read_text()) if state.exists() else {}
    reports = {str(r.id): r.display_name for r in api.reports(path)}
    if known.get("report_id") not in reports:
        failures.append(f"report {known.get('report_id')} not in {path}")
    else:
        report = wr.Report.from_url(f"https://wandb.ai/{entity}/{urllib.parse.quote(project)}/reports/report--{known['report_id']}")
        print(f"  report {reports[known['report_id']]!r} {known['report_url']}")
        for block in report.blocks:
            panels = getattr(block, "panels", None)
            if panels is None:
                print(f"    {type(block).__name__}")
            else:
                print("    PanelGrid: " + "; ".join(panel_name(p) for p in panels))
    rl = runlink()
    linked = [r for r in data["rows"] if r["rerun"].startswith("http")]
    picks = []
    if linked:
        newest = max(r["round"] for r in linked)
        picks = [next(r for r in linked if r["round"] == newest), linked[0], linked[len(linked) // 2]][:samples]
    for r in picks:
        status = head(r["rerun"])
        resolved = rl.resolve(r["rerun"].rsplit("/", 1)[-1]) if rl else None
        ok = status == 200 and resolved is not None and Path(resolved) == Path(r["rrd"]).resolve()
        print(f"  link round {r['round']} {r['station']} {r['name']}: HEAD {status}, resolves to {resolved} {'ok' if ok else 'FAIL'}")
        if not ok:
            failures.append(f"link {r['rerun']} ({r['name']}): HEAD {status}, resolves to {resolved}")
    return failures


# ---------------------------------------------------------------------------------------------------------------- CLI


def build(scorecards: Path = dp.SCORECARDS, now: str = dp.NOW_FILE) -> dict:
    runs = dp.runs(scorecards=scorecards, now=now)
    rounds = read_rounds(scorecards, now)
    return payload(runs, rounds, dp.history(scorecards, now), replay_urls(runs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scorecards", type=Path, default=dp.SCORECARDS)
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--dry-run", action="store_true", help="build and print; write nothing")
    parser.add_argument("--no-report", action="store_true", help="sync the runs, leave the report as it is")
    parser.add_argument("--verify", action="store_true", help="after the sync, read everything back and HEAD-check three links")
    args = parser.parse_args(argv)
    data = build(args.scorecards)
    links = data["links"]
    print(headline(data["now"]))
    print(f"runs table: {links['rows']} rows, {links['with_link']} with a Rerun link, {links['no_recording']} without a recording "
          f"(by round: {links['no_recording_by_round']})")
    if args.dry_run:
        return 0
    for result in sync(data, project=args.project, scorecards=args.scorecards):
        print(f"  {'wrote' if result['written'] else 'unchanged'} {result['id']} ({result['name']})")
    print(f"local: every run and roll-up as jsonl in {local_folder(args.project)}")
    if not args.no_report:
        print(f"report: {save_report(data, project=args.project)}")
    print(f"project: {project_url(project=args.project)}")
    if args.verify:
        failures = verify(data, project=args.project)
        print("verify: ok" if not failures else "verify FAILED:\n  " + "\n  ".join(failures))
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
