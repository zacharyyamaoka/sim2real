"""The One Dof Test Rack's W&B view: the summary across its runs first, then every run, each with a Rerun link that opens.

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra tracking python /home/bam/sim2real/tools/deployments_wandb.py

    ... --dry-run     build the tables and print the headline; write nothing
    ... --verify      read the project and the report back through the API, HEAD-check three Rerun links through 8771

Zach (Daily Note 2026-11-18, "# Ok back to performance metrics"): "go on weights and biases and go the 1 dof rack/pendulum deployment. I want
to be able to see the summary statistics accross a bunch of runs. Then I want to be able to drill down and look at a specific run". His
3000-ft view (memory deployment-view-3000ft, 11-17): performance first; runs are the atomic unit; one W&B project per deployment is the
store; Rerun links only through the always-on launcher on 127.0.0.1:8771, never the campaign's 9461/9462 web viewer (dead when not served).

What a sync writes into the deployment's project ("Sim2Real · 1-DOF rack", bam_ws tools/wandb_trackers/trackers/sim2real_1_dof_rack.py):
- the summary run (id `deployment-summary`, group deployment-summary): the round-by-round table (runs, median and p95 tracking RMS, worst
  stop, share of runs meeting the goal, the scorecard's own goal and gates), the same per station, goal-line charts across the rounds, and
  the runs table: one row per run of every scored round, its `rerun` cell the 8771 link or "no recording yet" (never a dead link);
- one run per round (id `deployment-summary-r<n>`): that round's headline as summary numbers and its own runs table, so the round's W&B
  run page is its drill-down. WHY not one W&B run per rig run: 2485 runs would bury the project, and a rig run's drill-down is its Rerun
  recording, one click from its row;
- the report "1-DOF rack · where we stand": the summary first, then the runs table, then the per-station panels.

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
from sim2real.tracking.wandb_log import ENTITY, WANDB_DIR  # noqa: E402 - stdlib only at import (wandb is imported inside its functions)

PROJECT = "Sim2Real · 1-DOF rack"
GROUP = "deployment-summary"
SUMMARY_ID = "deployment-summary"
SUMMARY_NAME = "1-DOF rack · where we stand"
ROUND_JOB = "round_summary"
REPORT_TITLE = "1-DOF rack · where we stand"
STATE = Path.home() / ".local" / "state" / "sim2real" / "deployments-wandb.json"
# WHY the /wandb prefix by hand: the app lives at forge.coreweave.com/wandb and wandb-workspaces' Report.url drops it (bam_interventions)
WEB = "https://forge.coreweave.com/wandb"
NO_RECORDING = "no recording yet"
NO_LAUNCHER = "recorded; no 8771 launcher on this computer"
LINESERIES = "wandb/lineseries/v0"
LINE_FIELDS = {"step": "step", "lineKey": "lineKey", "lineVal": "lineVal"}

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
    return {"rows": rows, "by_round": by_round, "by_station": by_station, "charts": charts,
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


def table(rows: list[dict], columns: tuple[str, ...]):
    import wandb  # noqa: PLC0415

    return wandb.Table(columns=list(columns), data=[[r.get(c) for c in columns] for r in rows], allow_mixed_types=True)


def chart(spec: dict):
    import wandb  # noqa: PLC0415

    data = wandb.Table(columns=["step", "lineKey", "lineVal"], data=spec["rows"])
    return wandb.plot_table(vega_spec_name=LINESERIES, data_table=data, fields=LINE_FIELDS,
                            string_fields={"title": spec["title"], "xname": "round"})


def flat(prefix: str, row: dict, keys: tuple[str, ...]) -> dict:
    out = {}
    for k in keys:
        v = row.get(k)
        if isinstance(v, bool):
            out[f"{prefix}{k}"] = int(v)
        elif isinstance(v, (int, float)) and v is not None:
            out[f"{prefix}{k}"] = v
    return out


def write_run(api, *, run_id: str, name: str, job_type: str, tags: list[str], notes: str, config: dict, values: dict,
              summary: dict, content: Any, entity: str, project: str) -> dict:
    """Write one of this tool's runs: unchanged content (its digest already in the run's summary) writes nothing; else one more step with
    `values` (tables, charts) and `summary` updated."""
    import wandb  # noqa: PLC0415

    want = digest(content)
    # WHY a miss is harmless: right after a write the API can still serve the old summary (seen 2026-11-18, a sync a minute after the
    # first rewrote every run); the extra step logs identical tables, which W&B keeps as the same artifact version
    try:
        have = api.run(f"{entity}/{project}/{run_id}").summary.get("sync/digest")
    except Exception:  # noqa: BLE001 - wandb raises CommError / ValueError for a run that does not exist yet
        have = None
    if have == want:
        return {"id": run_id, "name": name, "written": False}
    WANDB_DIR.mkdir(parents=True, exist_ok=True)
    run = wandb.init(entity=entity, project=project, id=run_id, name=name, group=GROUP, job_type=job_type, tags=tags, notes=notes,
                     config=config, resume="allow", reinit="create_new", allow_val_change=True, dir=str(WANDB_DIR),
                     settings=wandb.Settings(silent=True, console="off"))
    run.log(values)
    run.summary.update({**summary, "sync/digest": want, "sync/utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")})
    url = run.url
    run.finish()
    return {"id": run_id, "name": name, "written": True, "url": url}


def sync(data: dict, *, entity: str = ENTITY, project: str = PROJECT, scorecards: Path = dp.SCORECARDS) -> list[dict]:
    """The summary run, then one run per round (see the module docstring)."""
    import wandb  # noqa: PLC0415

    api = wandb.Api(timeout=60)
    sha = code_version()
    base = {"deployment": dp.DEPLOYMENT, "deployment_label": "One Dof Test Rack", "scorecards": str(scorecards),
            "built_by": "sim2real tools/deployments_wandb.py", "sim2real_sha": sha, "goal_fraction": dp.GOAL_FRACTION}
    now = data["now"]
    summary_values = {"by_round": table(data["by_round"], ROUND_COLUMNS), "by_round_station": table(data["by_station"], STATION_COLUMNS),
                      "runs": table(data["rows"], RUN_COLUMNS), **{k: chart(v) for k, v in data["charts"].items()}}
    summary_scalars = {**flat("now/", now, ROUND_COLUMNS), "now/headline": headline(now), "links/rows": data["links"]["rows"],
                       "links/with_link": data["links"]["with_link"], "links/no_recording": data["links"]["no_recording"]}
    out = [write_run(api, run_id=SUMMARY_ID, name=SUMMARY_NAME, job_type="summary", tags=["deployment-summary", "summary"],
                     notes="The summary across every run of the pendulum campaign, and every run with its Rerun link (8771 launcher).",
                     config={**base, "rounds": [r["round"] for r in data["by_round"]]}, values=summary_values, summary=summary_scalars,
                     content={k: data[k] for k in ("rows", "by_round", "by_station", "charts")}, entity=entity, project=project)]
    for r in data["by_round"]:
        n = r["round"]
        rows = [x for x in data["rows"] if x["round"] == n]
        stations = [x for x in data["by_station"] if x["round"] == n]
        scalars = {**flat("", r, ROUND_COLUMNS), "headline": headline(r)}
        for s in stations:
            scalars.update(flat(f"{s['station']}/", s, STATION_COLUMNS[3:]))
        out.append(write_run(api, run_id=f"{SUMMARY_ID}-r{n}", name=f"round {n} · {r['controller']}", job_type=ROUND_JOB,
                             tags=["deployment-summary", f"round {n}", *(["goal met"] if r["goal_met"] else [])],
                             notes=headline(r), config={**base, "round": n, "controller": r["controller"], "twin": r["twin"],
                                                        "scored_utc": r["scored_utc"]},
                             values={"runs": table(rows, RUN_COLUMNS), "by_station": table(stations, STATION_COLUMNS)},
                             summary=scalars, content={"round": r, "rows": rows, "stations": stations}, entity=entity, project=project))
    return out


# ---------------------------------------------------------------------------------------------------------------- W&B: the report


def web_url(entity: str, project: str, title: str, report_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
    return f"{WEB}/{entity}/{urllib.parse.quote(project)}/reports/{slug}--{report_id}"


def project_url(entity: str = ENTITY, project: str = PROJECT) -> str:
    return f"{WEB}/{entity}/{urllib.parse.quote(project)}"


def report_blocks(data: dict, *, entity: str = ENTITY, project: str = PROJECT) -> list:
    import wandb_workspaces.reports.v2 as wr  # noqa: PLC0415

    now, links = data["now"], data["links"]

    def summary_grid(panels: list):
        return wr.PanelGrid(runsets=[wr.Runset(entity=entity, project=project, name="summary", filters=f"ID in ['{SUMMARY_ID}']")],
                            panels=panels, hide_run_sets=True)

    def line(key: str, w: int = 12, h: int = 9):
        spec = data["charts"][key]
        return wr.CustomChart(query={"summaryTable": {"tableKey": f"{key}_table"}}, chart_name=LINESERIES, chart_fields=LINE_FIELDS,
                              chart_strings={"title": spec["title"], "xname": "round"}, layout=wr.Layout(w=w, h=h))

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
            "first, then sort or filter the runs table and click a row's `rerun` link to open that run in Rerun.")),
        wr.H2("Now"),
        summary_grid([tile("now/share_meeting_goal", "Share of runs meeting the goal (to 0.9)"),
                      tile("now/tracking_rms_median_deg", "Median run tracking RMS (°)"),
                      tile("now/perf_gates_passed", f"Real performance gates passed (of {now['perf_gates_total']})"),
                      tile("now/worst_stop_mm", "Worst tip stop (mm)")]),
        wr.H2("Summary across rounds"),
        summary_grid([line("chart/tracking_rms_at_goal"), line("chart/stop_at_goal"), line("chart/share_meeting_goal", w=24, h=8),
                      wr.WeavePanelSummaryTable(table_name="by_round", layout=wr.Layout(w=24, h=10))]),
        wr.H2("Every run"),
        wr.MarkdownBlock(text=(
            f"{links['rows']} runs, one row each. {links['with_link']} have a Rerun recording: the `rerun` cell is a link to "
            "127.0.0.1:8771, the always-on launcher on Zach's workstation, which opens the native Rerun viewer there (it works only on "
            f"that computer). {links['no_recording']} runs have no recording yet and say so ({missing}). The stop columns are the run's "
            "rung (the scorer measures stops per rung). Filter with the table's filter box, e.g. `row[\"round\"] = 9`.")),
        summary_grid([wr.WeavePanelSummaryTable(table_name="runs", layout=wr.Layout(w=24, h=20))]),
        wr.H2("Per station"),
        summary_grid([line(f"station/{sid}/tracking_rms", w=8, h=8) for sid in dp.STATIONS]
                     + [wr.WeavePanelSummaryTable(table_name="by_round_station", layout=wr.Layout(w=24, h=12))]),
        wr.H2("Each round's own page"),
        wr.MarkdownBlock(text=(
            "One W&B run per round (group `deployment-summary`, job type `round_summary`): its headline in the summary and its own runs "
            "table. Click a round's name below to open its page.")),
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


def verify(data: dict, *, entity: str = ENTITY, project: str = PROJECT, state: Path = STATE, samples: int = 3) -> list[str]:
    """Read back: the summary and round runs exist with this sync's digest, the report exists and its panels are listed; HEAD-check
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
        print(f"  summary run {summary.url}: runs table {summary.summary.get('runs', {}).get('nrows')} rows, "
              f"now/round {summary.summary.get('now/round')}, links {summary.summary.get('links/with_link')} of {summary.summary.get('links/rows')}")
        if summary.summary.get("runs", {}).get("nrows") != len(data["rows"]):
            failures.append(f"summary runs table: {summary.summary.get('runs', {}).get('nrows')} rows, want {len(data['rows'])}")
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
