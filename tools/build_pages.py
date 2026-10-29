"""The sim2real app's pages: one data-ui `.base` per level, and each level's gates layer as a second `.base` on the same data.

    python3 -I /home/bam/sim2real/tools/build_pages.py

Writes (committed): app/deployments.base, app/deployment.base, app/deployment-gates.base, app/run.base, app/run-gates.base.
Stdlib only; the `.base` text comes from data-ui's own writer (vendor/data-ui/dist/python/data_ui_base.py) and is checked to
round-trip.

WHY generated, not hand-written: Zach (2026-10-28), "make a really great robotic data visualizer first and THEN afterwards
... the diagnostics layer"; the gates layer is the playback page plus gate datasets and views (data-ui PEP 0010 §10: "the
seam is a file diff"). One function draws the playback page, another adds the overlay, so the two files can never drift.

The host (app/app.js) fills `{deployment}` and `{run}` in each data path. WHY in the host: data-ui has no per-run dataset
template yet (PEP 0010 P3, `datasets.<d>: {data: "runs/{run}.json"}`); sim2real owns the routes (PEP 0010 §8).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO / "vendor" / "data-ui" / "dist" / "python"))
import data_ui_base  # noqa: E402

# Zach (2026-10-28): "train the eye to know what is real and what is sim. Blue and orange ... leaves green and red for
# elsewhere". Real is data-ui's series slot 1 (blue), every model is slot 2 (orange); the target is a muted dashed grey.
# Members of the sim family keep the hue and change lightness (data-ui has no per-member line style yet: a listed gap).
# The host resolves var() and color-mix() per theme before data-ui reads the file (app.js), as dashboards/host.js does.
REAL = "var(--data-series-1)"
# WHY a fixed 10 % for every path: data-ui's chart has no opacity: auto (max(1/n, 0.04), PEP 0010 §2) yet; a listed gap
PATH = "color-mix(in srgb, var(--data-series-1) 10%, transparent)"
SIM = "var(--data-series-2)"
MUTED = "#8b9099"
MODELS = ["twin D · LuGre", "twin G · LuGre re-fit", "twin H · + dwell", "twin R · rate-state", "twin · full", "twin A · deployed", "twin C · calibrated", "twin C1 · fast inertia"]
SIM_SHADES = [SIM, f"color-mix(in srgb, {SIM} 62%, black)", f"color-mix(in srgb, {SIM} 55%, white)", f"color-mix(in srgb, {SIM} 80%, black)", SIM,
              f"color-mix(in srgb, {SIM} 55%, white)", SIM, f"color-mix(in srgb, {SIM} 62%, black)"]
PALETTE = {"real": REAL, "target": MUTED, **dict(zip(MODELS, SIM_SHADES))}
PALETTE.update({f"{model} vs real": shade for model, shade in zip(MODELS, SIM_SHADES)})
PALETTE["real vs target"] = REAL
# style.families (CONTRACT §32): the family picks the hue when a series has no palette entry; real blue, sim orange, target muted
STYLE = {"chrome": "minimal", "numbers": {"digits": 3, "compact": True}, "palette": PALETTE,
         "families": {"property": "source", "colors": {"real": 1, "sim": 2, "target": "muted"}}}
TONES = {"pass": "good", "warn": "warn", "partial": "warn", "fail": "bad", "not_run": "muted"}
RUN_DATA = "data/{deployment}/runs/{run}"
DEP_DATA = "data/{deployment}"


def head(what: str) -> str:
    return (f"# sim2real app · {what}\n# Written by tools/build_pages.py (do not edit by hand); data by tools/build_app.py. Grammar: vendor/data-ui\n"
            f"# (PEP 0004 dashboards, PEP 0005 cards). The host (app/app.js) fills {{deployment}} and {{run}}. REAL rack data; models are bam_rack_twin replays.\n")


# ---------------------------------------------------------------------------------------------------- deployments


def deployments_page() -> dict:
    return {
        "data": "data/deployments.json",
        "properties": {"title": {"displayName": "Deployment"}, "kind": {"displayName": "Kind"}, "where": {"displayName": "Where"},
                       "stations": {"displayName": "Stations"}, "runs": {"displayName": "Runs"}, "runs_with_models": {"displayName": "Runs with models"},
                       "hours": {"displayName": "Hours"}, "days": {"displayName": "Days"}, "last_run": {"displayName": "Last run"},
                       "gate_summary": {"displayName": "Gates"}, "page": {"displayName": "Open"}},
        "style": STYLE,
        "layout": {"panels": [
            {"text": "## Deployments\nEvery machine we run sim to real on. Each is unique; the numbers above the list roll up across all of them. Click one to open its runs.", "w": 12},
            {"view": "Deployments", "w": 3, "h": 2}, {"view": "Runs", "w": 3, "h": 2}, {"view": "Hours of data", "w": 3, "h": 2},
            {"view": "Stations", "w": 3, "h": 2},
            {"view": "All deployments", "w": 12, "h": 2, "title": "All deployments"},
        ]},
        "views": [
            {"type": "kpi", "name": "Deployments", "kpi": {"label": "Deployments", "value": {"property": "id", "summary": "Count"}}},
            {"type": "kpi", "name": "Runs", "kpi": {"label": "Real runs, all deployments", "value": {"property": "runs", "summary": "Sum"}}},
            {"type": "kpi", "name": "Hours of data", "kpi": {"label": "Hours of real data", "value": {"property": "hours", "summary": "Sum"}}},
            {"type": "kpi", "name": "Stations", "kpi": {"label": "Stations (devices)", "value": {"property": "stations", "summary": "Sum"}}},
            {"type": "table", "name": "All deployments", "open": {"mode": "link", "url": "page"},
             "order": ["title", "kind", "where", "stations", "runs", "runs_with_models", "hours", "days", "last_run", "gate_summary"],
             "sort": [{"property": "last_run", "direction": "DESC"}]},
        ],
    }


# ---------------------------------------------------------------------------------------------------- one deployment

W = "datum.w == 1"


def histogram(name: str, field: str, title: str) -> dict:
    return {"type": "chart", "name": name, "from": "coverage",
            "chart": {"mark": {"type": "bar"},
                      "encoding": {"color": {"value": REAL}, "x": {"field": field, "type": "quantitative", "bin": {"maxbins": 40}, "title": title},
                                   "y": {"field": "w", "aggregate": "sum", "type": "quantitative", "title": "samples (÷ grid Hz = s)"}}}}


def boxes(name: str, field: str, title: str) -> dict:
    return {"type": "chart", "name": name, "from": "coverage_all", "filters": 'layer == "path"',
            "chart": {"mark": {"type": "boxplot", "extent": "min-max"},
                      "encoding": {"color": {"value": REAL}, "x": {"field": "device", "type": "nominal", "title": None, "sort": ["CAN 1", "CAN 4", "CAN 11", "CAN 12", "CAN 13", "CAN 14", "CAN 15", "CAN 21"]},
                                   "y": {"field": field, "type": "quantitative", "title": title}}}}


def deployment_page() -> dict:
    page = {
        "data": f"{DEP_DATA}/runs.json",
        "properties": {"title": {"displayName": "Run"}, "started": {"displayName": "Started"}, "device": {"displayName": "Station"},
                       "status": {"displayName": "T2"}, "moves_x": {"displayName": "Moves ÷ floor (gate 1.5)"}, "hold_x": {"displayName": "Hold ÷ floor (gate 1.5)"},
                       "gate_x": {"displayName": "Gate"}, "moves_before_x": {"displayName": "Moves, twin before / today"}, "hold_before_x": {"displayName": "Hold, twin before"},
                       "limiting_term": {"displayName": "Limiting term"}, "evidence": {"displayName": "Evidence share"}, "why": {"displayName": "Why (the study)"},
                       "floor_growth_x": {"displayName": "Floor grew"}, "overfit_pick": {"displayName": "Overfit pick"}, "pick_rule": {"displayName": "Pick rule"}, "round": {"displayName": "Round"},
                       "worst_window": {"displayName": "Worst window"}, "caveat": {"displayName": "Caveat"}, "detail": {"displayName": "What it means"},
                       "kind": {"displayName": "Kind"}, "duration_s": {"displayName": "Duration"}, "gains": {"displayName": "Gains (board)"},
                       "compare": {"displayName": "Situations"}, "tracking_mrad": {"displayName": "Real vs target"},
                       "best_model": {"displayName": "Closest model"}, "best_model_mrad": {"displayName": "Model vs real"},
                       "verdict": {"displayName": "Twinned?"}, "page": {"displayName": "Open"}, "day": {"displayName": "Day"},
                       "session": {"displayName": "Session"}, "rate_hz": {"displayName": "Rate"}},
        "style": STYLE,
        "datasets": {
            "runs": {"data": f"{DEP_DATA}/runs.json", "label": "Runs",
                     "facets": [{"property": "device", "label": "Station"}, {"property": "kind", "label": "Kind"}, {"property": "day", "label": "Day"},
                                {"property": "compare", "label": "Situations"}, {"property": "duration_s", "as": "range", "label": "Duration"}]},
            # WHY one station at a time for the joint-level panels: the stations' ranges differ 100x (a JMC shoulder moves +-40 deg,
            # the GIM wrists turn 3,700 deg at 3,000 deg/s), and Vega-Lite bins before it facets, so pooled histograms are unreadable
            "coverage": {"data": f"{DEP_DATA}/coverage.json", "label": "Coverage station",
                         "facets": [{"property": "device", "as": "select", "label": "Coverage station"}], "filters": 'device == "CAN 12"'},
            "coverage_all": {"data": f"{DEP_DATA}/coverage.json", "label": "Coverage, every station"},
            "devices": {"data": f"{DEP_DATA}/devices.json", "label": "Stations"},
            "why": {"data": f"{DEP_DATA}/why.json", "label": "Why it fails"},
            "caveats": {"data": f"{DEP_DATA}/caveats.json", "label": "Caveats"},
        },
        # WHY linked: the runs rail and a selection in the runs table narrow every coverage panel (many-run comparison)
        "links": [{"from": "coverage_all.run", "to": "runs.run"}, {"from": "devices.device", "to": "runs.device"}],
        "layout": {"panels": [
            {"text": "## One Dof Test Rack · runs\n**REAL data**, Oct 23-28: every run the rack recorded, newest first. The rail narrows the runs; "
                     "click rows to overlay just those runs in *Angle over time* and the station boxes, or **Open ↗** to play one back against its models. "
                     "Blue is real, orange is a model, grey dashed is the target.", "w": 12},
            {"view": "Runs shown", "w": 3, "h": 2}, {"view": "Hours shown", "w": 3, "h": 2}, {"view": "Stations shown", "w": 3, "h": 2},
            {"view": "Runs with models", "w": 3, "h": 2},
            {"text": "### Why it fails\nOne row per station from the calibration round and its 10-29 follow-ups (bam_rack_twin calibration_why_2.json): T2 on the held-out tapes, moves and hold "
                     "offset each against **1.5× the floor** (after the round, with the twin before it beside it), the limiting term in the study's words, and how "
                     "much of the held-out torque gap that term's family explains on its own. **Click a row** to play its worst held-out window. "
                     "Read it with the caveats below it: they change how good the ratios look, and one is a decision still open.", "w": 12},
            {"view": "Why it fails", "w": 12, "h": 4},
            {"view": "Caveats", "w": 12, "h": 5, "toolbar": "none"},
            {"view": "Runs", "w": 12, "h": 5, "title": "Runs · newest first", "toolbar": "compact"},
            {"text": "### Coverage\nWhere the runs went. Every path is drawn faint (10 %), so the dark bands are where the rack spends its time; "
                     "the dashed box is each station's proven window (bam_rack_twin TAPE_STATIONS: travel × speed ceiling; stations with no recorded window have none). "
                     "Counts are grid samples, so ÷ the grid rate is seconds. The station panels follow **Coverage station** on the rail (CAN 12 first).", "w": 12},
            {"view": "Phase space · every run", "w": 7, "h": 5},
            {"view": "Time at (q, qd)", "w": 5, "h": 5},
            {"view": "Angle histogram", "w": 4, "h": 3}, {"view": "Speed histogram", "w": 4, "h": 3}, {"view": "Acceleration histogram", "w": 4, "h": 3},
            {"text": "### Every station side by side\nMin-max whiskers, so the extremes are exact (each run's argmin/argmax rows are kept).", "w": 12},
            {"view": "Angle by station", "w": 4, "h": 3}, {"view": "Speed by station", "w": 4, "h": 3}, {"view": "Acceleration by station", "w": 4, "h": 3},
            {"view": "Angle over time · every run", "w": 12, "h": 4},
        ]},
        "views": [
            {"type": "kpi", "name": "Runs shown", "from": "runs", "kpi": {"label": "Runs", "value": {"property": "run", "summary": "Count"}}},
            {"type": "kpi", "name": "Hours shown", "from": "runs", "kpi": {"label": "Seconds of real data", "value": {"property": "duration_s", "summary": "Sum"}}},
            {"type": "kpi", "name": "Stations shown", "from": "runs", "kpi": {"label": "Stations", "value": {"property": "device", "summary": "Unique"}}},
            {"type": "kpi", "name": "Runs with models", "from": "runs", "filters": "models > 0",
             "kpi": {"label": "Runs replayed by a model", "value": {"property": "run", "summary": "Count"}}},
            {"type": "table", "name": "Why it fails", "from": "why", "open": {"mode": "link", "url": "page"},
             "order": ["device", "status", "moves_x", "hold_x", "moves_before_x", "floor_growth_x", "overfit_pick", "pick_rule", "limiting_term", "evidence", "why",
                       "worst_window", "hold_before_x", "round"]},
            # WHY tall rows and a wide detail column: the caveats are read in full, never clipped behind a hover
            {"type": "table", "name": "Caveats", "from": "caveats", "order": ["caveat", "detail"], "rowHeight": "extra",
             "columnSize": {"caveat": 200, "detail": 900}},
            {"type": "table", "name": "Runs", "from": "runs", "select": "run",
             "order": ["title", "started", "device", "kind", "duration_s", "gains", "compare", "tracking_mrad", "best_model", "best_model_mrad", "page"],
             "sort": [{"property": "started", "direction": "DESC"}]},
            {"type": "chart", "name": "Phase space · every run", "from": "coverage",
             "chart": {"mark": {"type": "line", "strokeWidth": 1, "interpolate": "linear"},
                       "encoding": {"x": {"field": "q_deg", "type": "quantitative", "title": "q (°)"}, "y": {"field": "qd_deg_s", "type": "quantitative", "title": "qd (°/s)"},
                                    "detail": {"field": "run", "type": "nominal"}, "order": {"field": "t", "type": "quantitative"},
                                    "color": {"field": "layer", "type": "nominal", "title": None, "scale": {"domain": ["path", "workspace"], "range": [PATH, MUTED]}}}}},
            {"type": "chart", "name": "Time at (q, qd)", "from": "coverage",
             "chart": {"transform": [{"filter": W}], "mark": "rect",
                       "encoding": {"x": {"field": "q_deg", "type": "quantitative", "bin": {"maxbins": 60}, "title": "q (°)"},
                                    "y": {"field": "qd_deg_s", "type": "quantitative", "bin": {"maxbins": 40}, "title": "qd (°/s)"},
                                    "color": {"field": "w", "aggregate": "sum", "type": "quantitative", "title": "samples", "scale": {"scheme": "blues", "type": "log"}}}}},
            boxes("Angle by station", "q_deg", "q (°)"), boxes("Speed by station", "qd_deg_s", "qd (°/s)"),
            boxes("Acceleration by station", "qdd_deg_s2", "qdd (°/s², derived)"),
            histogram("Angle histogram", "q_deg", "q (°)"), histogram("Speed histogram", "qd_deg_s", "qd (°/s)"),
            histogram("Acceleration histogram", "qdd_deg_s2", "qdd (°/s², derived)"),
            {"type": "chart", "name": "Angle over time · every run", "from": "coverage_all", "filters": 'layer == "path"',
             "chart": {"mark": {"type": "line", "strokeWidth": 1},
                       "encoding": {"color": {"value": PATH}, "x": {"field": "t", "type": "quantitative", "title": "t from run start (s)"},
                                    "y": {"field": "q_deg", "type": "quantitative", "title": "q (°)"},
                                    "detail": {"field": "run", "type": "nominal"}}}},
        ],
    }
    return page


def deployment_gates_page() -> dict:
    """The playback page plus the gates layer: the rack's gate matrix, every diagnostic row, and each run's verdicts."""

    page = copy.deepcopy(deployment_page())
    page["datasets"].update({
        "gates": {"data": f"{DEP_DATA}/gates.json", "label": "Gate cells", "facets": [{"property": "verdict", "label": "Gate verdict"}]},
        "diagnostics": {"data": f"{DEP_DATA}/diagnostics.json", "label": "Diagnostics"},
        "run_gates": {"data": f"{DEP_DATA}/run_gates.json", "label": "Run diagnostics", "facets": [{"property": "title", "label": "Diagnostic"}]},
    })
    page["links"] += [{"from": "run_gates.run_slug", "to": "runs.run"}, {"from": "gates.device", "to": "runs.device"}]
    page["properties"].update({"gate": {"displayName": "Gate"}, "subject": {"displayName": "Subject"}, "message": {"displayName": "What it measured"},
                               "value": {"displayName": "Value"}, "unit": {"displayName": "Unit"}, "evidence": {"displayName": "Evidence"}})
    overlay = [
        {"text": "## Gates layer\nComputed **from** the runs below by robotdx.diagnostics (io-diagnostics), never by the page: the station gates "
                 "(tools/diagnostics_run_rack.py) and, per run, each model's error against real over the station's floor. "
                 "Green and red mean pass and fail only. Turn the layer off in the header to see the data alone.", "w": 12},
        {"view": "Gate cells passing", "w": 3, "h": 2}, {"view": "Runs a model twins", "w": 3, "h": 2},
        {"view": "Passing per gate", "w": 6, "h": 2},
        {"view": "Stations × gates", "w": 12, "h": 4},
        {"view": "Run verdicts", "w": 12, "h": 4, "toolbar": "compact"},
        {"view": "Station diagnostics", "w": 12, "h": 4, "toolbar": "compact"},
    ]
    page["layout"]["panels"] = page["layout"]["panels"][:1] + overlay + page["layout"]["panels"][1:]
    page["views"] += [
        {"type": "gauge", "name": "Gate cells passing", "from": "gates",
         "gauge": {"value": {"property": "passed", "summary": "Ratio", "per": "cell"}, "min": 0, "max": 1, "target": 1, "shape": "arc", "better": "higher",
                   "label": "Station gate cells passing", "bands": [{"to": 0.5, "tone": "bad"}, {"to": 0.99, "tone": "warn"}, {"tone": "good"}]}},
        {"type": "kpi", "name": "Runs a model twins", "from": "runs", "filters": 'verdict == "pass"',
         "kpi": {"label": "Runs where a model is within 1.5× the floor", "value": {"property": "run", "summary": "Count"}}},
        {"type": "barlist", "name": "Passing per gate", "from": "gates",
         "barlist": {"label": "gate", "value": {"property": "passed", "summary": "Sum"}, "better": "higher"}},
        {"type": "tracker", "name": "Stations × gates", "from": "gates", "groupBy": {"property": "device"},
         "groupOrder": ["CAN 11", "CAN 12", "CAN 13", "CAN 4", "CAN 21", "CAN 1", "CAN 14", "CAN 15"],
         "sort": [{"property": "order", "direction": "ASC"}], "tracker": {"state": "verdict", "label": "gate", "tones": TONES}},
        {"type": "table", "name": "Run verdicts", "from": "run_gates", "filters": 'diagnostic == "stock.model_error"',
         "order": ["parent", "title", "verdict", "value", "unit", "message", "evidence"], "groupBy": {"property": "device"}},
        {"type": "table", "name": "Station diagnostics", "from": "diagnostics",
         "order": ["subject", "title", "verdict", "value", "unit", "message", "evidence"], "groupBy": {"property": "subject"}},
    ]
    return page


# ---------------------------------------------------------------------------------------------------- one run


def ts(name: str, dataset: str, y: str, unit: str, *, series: str = "situation", filters: str | None = None, rules=None) -> dict:
    view = {"type": "timeseries", "name": name, "from": dataset,
            "timeseries": {"x": "t", "y": y, "series": series, "unit": unit, "legend": "top", "dash": ["target"]}}
    if filters:
        view["filters"] = filters
    if rules:
        view["timeseries"]["rules"] = rules
    return view


def run_page() -> dict:
    return {
        "data": f"{RUN_DATA}/samples.json",
        "properties": {"situation": {"displayName": "Situation"}, "source": {"displayName": "Family"}, "title": {"displayName": "Run"},
                       "started": {"displayName": "Started"}, "device": {"displayName": "Station"}, "kind": {"displayName": "Kind"},
                       "duration_s": {"displayName": "Duration"}, "gains": {"displayName": "Gains (board)"}, "compare": {"displayName": "Situations"},
                       "reference": {"displayName": "Against"}},
        "style": STYLE,
        "clock": {"data": "samples", "time": "t"},
        "datasets": {
            "samples": {"data": f"{RUN_DATA}/samples.json", "label": "Samples",
                        "facets": [{"property": "situation", "label": "Show"}, {"property": "source", "label": "Family"}]},
            # the contract's difference(a, b) rows (tools/trajectory.py): situation = a, reference = b, e_q_mrad = b − a
            "diff": {"data": f"{RUN_DATA}/diff_samples.json", "label": "Errors", "facets": [{"property": "reference", "label": "Error against"}]},
            "run": {"data": f"{RUN_DATA}/run.json", "label": "Run"},
            # the output link's marker 100 mm out along its x axis, in the joint's own frame (tools/build_app.py MARKER_BODY)
            "poses": {"data": f"{RUN_DATA}/poses.json", "label": "Poses", "filters": 'body == "marker_100mm"'},
        },
        # WHY linked: hiding a situation on the rail hides its error line too
        "links": [{"from": "diff.situation", "to": "samples.situation"}, {"from": "poses.situation", "to": "samples.situation"}],
        "layout": {"panels": [
            {"view": "Run", "w": 12, "h": 2, "toolbar": "none"},
            {"view": "Playback", "w": 12},
            {"view": "Output link · 3D in its joint frame", "w": 7, "h": 5}, {"view": "Output link · top (down the joint axis)", "w": 5, "h": 5},
            {"view": "Angle · real vs models", "w": 12, "h": 4},
            {"view": "Error against the target (target − each)", "w": 6, "h": 3}, {"view": "Model error against real (real − model)", "w": 6, "h": 3},
            {"view": "Speed", "w": 6, "h": 3}, {"view": "Torque", "w": 6, "h": 3},
            {"view": "Acceleration (derived)", "w": 6, "h": 3}, {"view": "Current · real", "w": 6, "h": 3},
            {"view": "Board temperature · real", "w": 6, "h": 3}, {"view": "Angle histogram · this run", "w": 6, "h": 3},
        ]},
        "views": [
            {"type": "table", "name": "Run", "from": "run", "order": ["title", "started", "device", "kind", "duration_s", "gains", "compare"]},
            {"type": "playback", "name": "Playback", "playback": {"speeds": [0.25, 0.5, 1, 2, 4], "range": True, "readout": True}},
            # WHY trail with a 1 s decay: a run sweeps the same arc many times; the trail shows where it is now and the last second
            {"type": "trajectory3d", "name": "Output link · 3D in its joint frame", "from": "poses",
             "trajectory3d": {"series": "situation", "family": "source", "unit": "mm", "show": "trail", "decay": 1.0, "projection": "perspective",
                              "axes": "auto", "density": 20}},
            {"type": "trajectory3d", "name": "Output link · top (down the joint axis)", "from": "poses",
             "trajectory3d": {"series": "situation", "family": "source", "unit": "mm", "show": "trail", "decay": 1.0, "projection": "top", "axes": "auto"}},
            ts("Angle · real vs models", "samples", "q_deg", "°"),
            ts("Error against the target (target − each)", "diff", "e_q_mrad", "mrad", filters='reference == "target"'),
            ts("Model error against real (real − model)", "diff", "e_q_mrad", "mrad", filters='reference == "real"'),
            ts("Speed", "samples", "qd_deg_s", "°/s"),
            ts("Torque", "samples", "tau_nm", "N·m", filters='source != "target"'),
            ts("Acceleration (derived)", "samples", "qdd_deg_s2", "°/s²"),
            ts("Current · real", "samples", "i_q_a", "A", filters='situation == "real"'),
            ts("Board temperature · real", "samples", "temp_c", "°C", filters='situation == "real"'),
            {"type": "chart", "name": "Angle histogram · this run", "from": "samples",
             "chart": {"mark": {"type": "line", "interpolate": "step"},
                       "encoding": {"x": {"field": "q_deg", "type": "quantitative", "bin": {"maxbins": 50}, "title": "q (°)"},
                                    "y": {"aggregate": "count", "type": "quantitative", "title": "samples"},
                                    "color": {"field": "situation", "type": "nominal", "title": None,
                                              "scale": {"domain": [k for k in PALETTE if " vs " not in k], "range": [v for k, v in PALETTE.items() if " vs " not in k]}}}}},
        ],
    }


def run_gates_page() -> dict:
    page = copy.deepcopy(run_page())
    page["datasets"]["dx"] = {"data": f"{RUN_DATA}/diagnostics.json", "label": "Diagnostics", "facets": [{"property": "verdict", "label": "Verdict"}]}
    page["properties"].update({"subject": {"displayName": "Subject"}, "message": {"displayName": "What it measured"}, "evidence": {"displayName": "Evidence"}})
    overlay = [
        {"text": "### Gates layer · this run\nComputed **from** this run's data by robotdx.diagnostics: real vs target, each model against real "
                 "(pass at ≤ 1.5× the station's floor, whole-run RMS), board temperature, faults and the sample rate. Evidence links jump the playback to the window.", "w": 12},
        {"view": "Diagnostics of this run", "w": 12, "h": 3, "toolbar": "compact"},
    ]
    page["layout"]["panels"] = page["layout"]["panels"][:2] + overlay + page["layout"]["panels"][2:]
    page["views"].append({"type": "table", "name": "Diagnostics of this run", "from": "dx",
                          "order": ["title", "verdict", "value", "unit", "warn_hi", "error_hi", "message", "evidence"]})
    return page


def run_why_page() -> dict:
    """The run page opened from "Why it fails": the station's row and its residual decomposition beside the playback."""

    page = copy.deepcopy(run_page())
    page["datasets"]["why"] = {"data": f"{DEP_DATA}/why.json", "label": "Why", "filters": 'station == "{station}"'}
    page["datasets"]["decomposition"] = {"data": f"{DEP_DATA}/why/{{station}}.json", "label": "Residual decomposition"}
    page["properties"].update({"limiting_term": {"displayName": "Limiting term"}, "evidence": {"displayName": "Evidence share"},
                               "moves_x": {"displayName": "Moves ÷ floor"}, "hold_x": {"displayName": "Hold ÷ floor"}, "worst_window": {"displayName": "Worst window"},
                               "why": {"displayName": "Why (the study)"}})
    overlay = [
        {"text": "### Why this station fails\nThe playback opens on the worst held-out window (the shaded range). The bars are the study's residual "
                 "decomposition on the held-out tapes: how much of the torque the rack needed beyond the twin each term family explains on its own "
                 "(unique R²), and where the move error sits. Blue and orange stay real and model; the bars are neither, so they are grey.", "w": 12},
        {"view": "This station", "w": 12, "h": 2, "toolbar": "none"},
        {"view": "Torque gap by term family", "w": 6, "h": 3}, {"view": "Move error by phase", "w": 6, "h": 3},
    ]
    page["layout"]["panels"] = page["layout"]["panels"][:2] + overlay + page["layout"]["panels"][2:]

    def bars(name, chart, title):
        return {"type": "chart", "name": name, "from": "decomposition", "filters": f'chart == "{chart}"',
                "chart": {"mark": "bar", "encoding": {"y": {"field": "what", "type": "nominal", "title": None, "sort": "-x"},
                                                      "x": {"field": "share", "type": "quantitative", "title": title, "axis": {"format": "%"}},
                                                      "yOffset": {"field": "when", "type": "nominal"},
                                                      "color": {"field": "when", "type": "nominal", "title": None,
                                                                "scale": {"domain": ["before (deployed twin)", "after (calibrated twin)"], "range": ["#b8bcc4", "#6b7079"]}}}}}

    page["views"] += [
        {"type": "table", "name": "This station", "from": "why", "order": ["device", "moves_x", "hold_x", "limiting_term", "evidence", "worst_window", "why"]},
        bars("Torque gap by term family", "torque gap", "share of the held-out torque gap (unique R²)"),
        bars("Move error by phase", "move error", "share of the moving q error"),
    ]
    return page


PAGES = {"deployments.base": ("deployments", deployments_page), "deployment.base": ("one deployment: runs + coverage", deployment_page),
         "deployment-gates.base": ("one deployment + the gates layer", deployment_gates_page), "run.base": ("one run: playback", run_page),
         "run-gates.base": ("one run + the gates layer", run_gates_page),
         "run-why.base": ("one run opened from Why it fails: playback + the station's residual decomposition", run_why_page)}


def main() -> int:
    for name, (what, make) in PAGES.items():
        doc = make()
        text = head(what) + data_ui_base.dumps(doc)
        assert data_ui_base.loads(text) == json.loads(json.dumps(doc)), f"{name}: the .base does not round-trip"
        (APP / name).write_text(text, encoding="utf-8")
        print(f"wrote app/{name} ({len(doc['views'])} views)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
