"""The data-ui dashboards the record tabs hold: tools/build_pages.py's pages, cut along the tabs.

Every panel the app showed is in exactly one tab's .base here, taken from the same functions (build_pages.deployment_page,
deployment_gates_page, run_page, run_why_page), so a panel can never drift between the app and the site:

    deployment-runs.base      the deployment's Runs tab: intro, the five KPIs, Runs · newest first (owns the URL); its rail opens on
                              the deployment's tree (data-ui's `tree` facet over node_1 …), then the run tags and the config snapshot
    deployment-gates.base     its Gates tab: the gates layer overlay (gauge, passing per gate, stations x gates, verdicts)
    deployment-why.base       its Why it fails tab: the why tables, Evidence files, Caveats
    deployment-coverage.base  its Coverage tab: phase space, time at (q, qd), the histograms and boxes, angle over time
    station-runs.base         a station's Runs tab: the deployment's runs scoped to the station
    station-coverage.base     a station's Coverage tab: the coverage panels scoped to the station
    run.base                  a run's Playback tab (unchanged)
    run-why.base              a run's Why it fails tab: its station's decomposition bars (the playback stays one tab away)
    station-schedule.base     a station's Schedule tab: the test schedule's targets, model curves, coverage and runs (not run yet)
    station-gates.base        a station's Gates tab: its gate history against every cell, and every run's checks with their
                              evidence in the peek
    gate-matrix.base          the home's matrix (stations x T1-T11), the deployment named in its URL (?deployment=)

data-ui 006e9d5 (CONTRACT §33, §35; PEP 0010 P3, P5): the Runs tabs read one run's samples per pick (`{run}` is data-ui's own
placeholder there, filled from the runs table's pick, so the host leaves it alone on a page that is no run); the gate views
are the stock hints (gate_matrix, threshold_band, kpi_trend, rollup_tree, evidence, path_overlay, verdict voxels), as the
"Playback + Gates" twins write them (data-ui gallery/examples/robotics-deployments-gates, robotics-arm-gates), on the rows
site/overlays.py writes.

Paths are rooted at /data/ (the site's copy of app/data); `{deployment}`, `{run}`, `{station}` and `{device}` are filled
by static/sim2real.js from the page's record (or the .base URL's query), as app/app.js did; a record field left empty is left
for data-ui (the Runs tabs' `{run}`).
"""

from __future__ import annotations

import copy
import json
import sys

from adapter import REPO

sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(1, str(REPO / "vendor" / "data-ui" / "dist" / "python"))
import build_pages  # noqa: E402
import data_ui_base  # noqa: E402

import components  # noqa: E402  (site/components.py: the media as entity-scoped components)


def rooted(value):
    """Every `data/…` path made `/data/…` (the .base files move from /app/ to /views/)."""
    if isinstance(value, dict):
        return {k: rooted(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rooted(v) for v in value]
    if isinstance(value, str) and value.startswith("data/"):
        return "/" + value
    return value


def panel_views(panel: dict) -> list[str]:
    return panel.get("views") or ([panel["view"]] if "view" in panel else [])


def subset(page: dict, keep) -> dict:
    """The page with only the panels `keep(index, panel)` accepts, and only the views and datasets they use."""
    doc = copy.deepcopy(page)
    panels = [p for i, p in enumerate(doc["layout"]["panels"]) if keep(i, p)]
    doc["layout"]["panels"] = panels
    used = {name for p in panels for name in panel_views(p)}
    doc["views"] = [v for v in doc["views"] if v["name"] in used]
    if "datasets" in doc:
        wanted = {v.get("from") for v in doc["views"] if v.get("from")}
        links = doc.get("links") or []
        for link in links:  # a link whose `to` side is kept keeps its rail working (the runs rail narrows coverage)
            a, b = link["from"].split(".")[0], link["to"].split(".")[0]
            if a in wanted:
                wanted.add(b)
        doc["datasets"] = {k: v for k, v in doc["datasets"].items() if k in wanted}
        doc["links"] = [l for l in links if l["from"].split(".")[0] in doc["datasets"] and l["to"].split(".")[0] in doc["datasets"]]
        if not doc["links"]:
            doc.pop("links")
    return doc


def text_starts(panel: dict, *heads: str) -> bool:
    return "text" in panel and any(panel["text"].startswith(h) for h in heads)


def deployment_runs(levels: list[str] | None = None) -> dict:
    page = build_pages.deployment_page()
    runs = {"Runs shown", "Hours shown", "Stations shown", "Runs with models", "Runs"}
    doc = subset(page, lambda i, p: i == 0 or bool(set(panel_views(p)) & runs))
    return picked_run(with_tree(doc, levels or []))


TREE_INFO = ("The deployment's tree, as RobotDx draws its entity tree: the deployment, each adapter, each station (the bam_rack_twin record's "
             "wiring). A node's n/m: n of the m gate cells under it pass. The number on the right is its runs. A click narrows the runs to "
             "it and opens what is under it; a second click gives them back.")
TAG_FACETS = [{"property": "environment", "label": "Environment"}, {"property": "setting", "label": "Setting"},
              {"property": "config", "label": "Config snapshot"}]
TAG_PROPERTIES = {"environment": {"displayName": "Environment"}, "setting": {"displayName": "Setting"}, "config": {"displayName": "Config"},
                  "full_config_pct": {"displayName": "Full config snapshot"}, "config_detail": {"displayName": "Configuration recorded"},
                  "test_type": {"displayName": "Test type"}, "type": {"displayName": "Type"}, "deployment_kind": {"displayName": "Deployment kind"}}


def with_tree(doc: dict, levels: list[str]) -> dict:
    """The runs rail opens on the deployment's tree (data-ui's `tree` facet, CONTRACT §7: one `p == v` per level), the Station facet
    folded into it (its leaves are the stations), then the run tags and the config snapshot; a KPI says the share of runs with a full
    config snapshot. WHY the tree in the rail (Zach, 2026-10-29: "The filter bar should always be on the left hand side"; Nov 5:
    "each deployment, should have a tree ... look at the level you want to look at"): the tree IS a filter of the runs."""
    ds = doc["datasets"]["runs"]
    rest = [f for f in ds.get("facets", []) if f.get("property") != "device"]
    tree = [{"as": "tree", "levels": list(levels), "label": "Deployment tree", "info": TREE_INFO}] if levels else []
    ds["facets"] = tree + TAG_FACETS + rest
    doc["properties"].update(TAG_PROPERTIES)
    doc["views"].append({"type": "kpi", "name": "Config recorded", "from": "runs",
                         "kpi": {"label": "Runs with a full config snapshot", "value": {"property": "full_config_pct", "summary": "Average"},
                                 "format": {"digits": 3}}})
    width = {"Runs shown": 3, "Hours shown": 3, "Stations shown": 2, "Runs with models": 2}
    panels = []
    for p in doc["layout"]["panels"]:
        name = next((n for n in panel_views(p) if n in width), None)
        panels.append({**p, "w": width[name]} if name else p)
        if name == "Runs with models":
            panels.append({"view": "Config recorded", "w": 2, "h": p.get("h", 2)})
    doc["layout"]["panels"] = panels
    for view in doc["views"]:
        if view["name"] == "Runs":
            order = view["order"]
            view["order"] = order[:order.index("kind") + 1] + ["environment"] + order[order.index("kind") + 1:order.index("gains") + 1] + ["config"] + order[order.index("gains") + 1:]
    return doc


def picked_run(doc: dict) -> dict:
    """PEP 0010 P3 (CONTRACT §33): a click on a runs-table row picks the run, and only its samples are read, from the file
    `{run}` names; Back and Forward restore the pick and t (a pick is a history entry). WHY one-way: the run pick names the
    file, and the samples' own rail (Show) never narrows the runs."""
    doc["datasets"]["samples"] = {"data": "data/{deployment}/runs/{run}/samples.json", "label": "Samples of the picked run",
                                  "facets": [{"property": "situation", "label": "Show"}]}
    doc.setdefault("links", []).append({"from": "runs.run", "to": "samples.run", "direction": "one-way"})
    doc["clock"] = {"data": "samples", "time": "t"}
    doc["views"] += [{"type": "playback", "name": "Playback · the picked run", "playback": {"speeds": [0.25, 0.5, 1, 2, 4], "readout": True}},
                     build_pages.ts("Angle · the picked run", "samples", "q_deg", "°")]
    doc["layout"]["panels"] += [{"text": "### The picked run\nClick a row above to play that run here (only its samples are read); "
                                         "Back and Forward step through your picks. **Open ↗** opens its own page with every panel.", "w": 12},
                                {"view": "Playback · the picked run", "w": 12}, {"view": "Angle · the picked run", "w": 12, "h": 4}]
    return doc


GATE_IDS = [f"T{i}" for i in range(1, 12)]
STATION_ORDER = ["CAN 1", "CAN 4", "CAN 11", "CAN 12", "CAN 13", "CAN 14", "CAN 15", "CAN 21"]


def gate_matrix(name: str = "Stations × gates", dataset: str = "gates") -> dict:
    """gate_matrix (CONTRACT §35): one row per station, one column per gate T1-T11 in order (each drawn even where no row has
    it), a cell its verdict as a glyph and a word in the status vocabulary's tone (RobotDx's order: pass, warn / partial,
    not run, fail). A cell opens the gate's row in the side peek, with its why one link away."""
    return {"type": "tracker", "name": name, "from": dataset, "groupBy": {"property": "device"}, "groupOrder": STATION_ORDER,
            "sort": [{"property": "order", "direction": "ASC"}],
            "tracker": {"state": "verdict", "column": "gate_id", "columns": GATE_IDS, "label": "gate"},
            "display": {"verdict": "status", "why_url": "link"},
            "record": {"sections": [{"name": "Verdict", "properties": ["gate", "verdict", "value", "value_text", "target", "message"]},
                                    {"name": "Why", "properties": ["why_url"]}, {"name": "Provenance", "properties": ["source"]}]}}


def kpi_trend(name: str, label: str, filters: str, group: bool = False) -> dict:
    """kpi_trend (CONTRACT §35): the newest acceptance file's cells passing, its history as the sparkline, every cell the target."""
    view = {"type": "kpi", "name": name, "from": "history", "filters": filters,
            "kpi": {"label": label, "value": {"property": "passing"}, "spark": {"x": "dated", "y": "passing"}, "target": "cells",
                    "compare": {"against": "target", "better": "higher"}}}
    if group:
        # WHY no groupOrder: with one, data-ui makes the first station a big headline card (KPI README), and no station is the headline
        view["groupBy"] = {"property": "device"}
    return view


def deployment_gates() -> dict:
    page = build_pages.deployment_gates_page()
    overlay = {"Gate cells passing", "Runs a model twins", "Passing per gate", "Stations × gates", "Run verdicts", "Station diagnostics"}
    doc = subset(page, lambda i, p: text_starts(p, "## Gates layer") or bool(set(panel_views(p)) & overlay))
    doc["datasets"]["history"] = {"data": "data/{deployment}/gate_history.json", "label": "Gate history"}
    # rollup_tree: the rack, its plates and stations; each node the worst gate under it (the Max of RobotDx's ranks)
    # WHY passing and cells beside the worst (Zach, Nov 5 2026: "we can see like how the matching is at that level"): each node's match in
    # numbers, the Sum and the Count of the cells' passes under it, data-ui's roll-up as the worst is
    doc["datasets"]["components"] = {"data": "data/{deployment}/components.json", "label": "The rack", "tree": {"parent": "parent"},
                                     "rollup": {"from": "gates", "values": {"worst": {"property": "rank", "summary": "Max"},
                                                                            "passing": {"property": "passes", "summary": "Sum"},
                                                                            "cells": {"property": "passes", "summary": "Count"}}}}
    doc["links"].append({"from": "gates.device", "to": "components.id"})
    doc["views"] = [v for v in doc["views"] if v["name"] not in ("Gate cells passing", "Stations × gates")]
    doc["views"] += [kpi_trend("Gate cells passing", "Gate cells passing (newest acceptance)", 'scope == "rack"'),
                     kpi_trend("Passing per station · history", "cells passing", 'scope == "station"', group=True),
                     gate_matrix(),
                     {"type": "table", "name": "The rack", "from": "components", "tree": {"parent": "parent"}, "fold": "open",
                      "order": ["label", "kind", "worst", "passing", "cells", "card"],
                      "columnSize": {"label": 380, "kind": 96, "worst": 110, "passing": 120, "cells": 80, "card": 96}, "display": {"worst": "status"}}]
    # the matrix's peek reads its gate rows' fields by these names ("Twinned?" is the runs' verdict, not a gate's)
    doc["properties"].update({"label": {"displayName": "Component"}, "worst": {"displayName": "Worst gate"}, "verdict": {"displayName": "Verdict"},
                              "passing": {"displayName": "Cells passing"}, "cells": {"displayName": "Cells"}, "card": {"displayName": "Type card"},
                              "value_text": {"displayName": "Value (text)"}, "target": {"displayName": "Limit"},
                              "message": {"displayName": "What it measured"}, "why_url": {"displayName": "Why it fails"},
                              "source": {"displayName": "Acceptance file"}})
    # the trend wide enough to read its dates; the matrix full width, then the tree beside the stations' trends
    size = {"Gate cells passing": (5, 3), "Runs a model twins": (3, 3), "Passing per gate": (4, 3), "Stations × gates": (12, 4)}
    panels = []
    for p in doc["layout"]["panels"]:
        name = next((n for n in panel_views(p) if n in size), None)
        if name:
            p = {**p, "view": name, "w": size[name][0], "h": size[name][1]}
        panels.append(p)
        if name == "Stations × gates":
            # WHY the tree full width (was 5 of 12 beside the history): it reads each node's match in numbers now (cells passing of cells,
            # the type card) beside the worst, and at 5 of 12 those columns were cut off at 1280 px
            panels += [{"view": "The rack", "w": 12, "h": 5}, {"view": "Passing per station · history", "w": 12, "h": 4}]
    doc["layout"]["panels"] = panels
    return doc


def station_gates() -> dict:
    """A station's Gates tab below its gate table: its gate history, and every run's checks with their evidence. WHY no T2 plot
    here: a station's model runs come in bursts (CAN 12: 28 in ten minutes on 10-28, one on 10-25), which a time axis squeezes
    into one line; T2's band is drawn per model on each run's Playback instead."""
    return {
        "data": "/data/{deployment}/run_gates.json",
        "properties": {"title": {"displayName": "Check"}, "verdict": {"displayName": "Verdict"}, "value": {"displayName": "Value", "digits": 3},
                       "unit": {"displayName": "Unit"}, "error_hi": {"displayName": "Limit (error above)", "digits": 3}, "message": {"displayName": "What it measured"},
                       "evidence": {"displayName": "Evidence (opens the playback there)"}, "t0": {"displayName": "From (s)"}, "t1": {"displayName": "To (s)"},
                       "source": {"displayName": "Source"}, "record": {"displayName": "Record"}, "started": {"displayName": "Started"}, "run": {"displayName": "Run"}},
        "style": copy.deepcopy(build_pages.STYLE),
        "datasets": {
            "history": {"data": "/data/{deployment}/gate_history.json", "label": "Gate history", "filters": 'scope == "station" && device == "{device}"'},
            "checks": {"data": "/data/{deployment}/run_gates.json", "label": "Run checks",
                       "filters": 'device == "{device}" && (diagnostic == "stock.model_error" || diagnostic == "stock.tracking_error")'},
        },
        "layout": {"panels": [
            {"text": "### {device} · gates over time, per run\n**Gate cells passing** per bam_rack_twin acceptance file, against every cell. "
                     
                     "**Run checks**: every run's checks by robotdx.diagnostics; a cell opens its evidence, and the link plays the run at its window.", "w": 12},
            {"view": "Gate cells passing · {device}", "w": 5, "h": 3},
            {"view": "Run checks", "w": 12, "h": 6},
        ]},
        "views": [
            kpi_trend("Gate cells passing · {device}", "{device} gate cells passing", 'scope == "station"'),
            # evidence: a cell opens its check; the peek shows the run's other checks and the link that plays its window
            {"type": "tracker", "name": "Run checks", "from": "checks", "groupBy": {"property": "run", "direction": "DESC"},
             "sort": [{"property": "title", "direction": "ASC"}],
             "tracker": {"state": "verdict", "column": "title", "label": "message"},
             "display": {"verdict": "status", "evidence": "link"},
             "record": {"sections": [
                 {"name": "Verdict", "properties": ["title", "verdict", "value", "unit", "error_hi", "message"]},
                 {"name": "Evidence", "properties": ["evidence", "t0", "t1"],
                  "view": {"type": "table", "name": "This run's checks", "from": "checks", "filters": "run == this.run",
                           "order": ["title", "verdict", "value", "unit", "error_hi"], "display": {"verdict": "status"}}},
                 {"name": "Provenance", "properties": ["source", "record", "started"]}]}},
        ],
    }


def home_gates() -> dict:
    """The home's matrix: the deployment the .base URL names (?deployment=, static/sim2real.js fills it)."""
    return {
        "data": "/data/{deployment}/gates.json",
        "properties": {"gate": {"displayName": "Gate"}, "verdict": {"displayName": "Verdict"}, "value": {"displayName": "Value"},
                       "value_text": {"displayName": "Value (text)"}, "target": {"displayName": "Limit"}, "message": {"displayName": "What it measured"},
                       "why_url": {"displayName": "Why it fails"}, "source": {"displayName": "Acceptance file"}},
        "style": {"chrome": "minimal"},
        "datasets": {"gates": {"data": "/data/{deployment}/gates.json", "label": "Gate cells"}},
        "layout": {"panels": [{"view": "Stations × gates", "w": 12, "h": 4, "toolbar": "none"}]},
        "views": [gate_matrix()],
    }


def deployment_why() -> dict:
    page = build_pages.deployment_page()
    why = {"Why it fails", "Why it fails · columns", "Evidence files", "Caveats"}
    return subset(page, lambda i, p: text_starts(p, "### Why it fails") or bool(set(panel_views(p)) & why))


COVERAGE = {"Phase space · every run", "Time at (q, qd)", "Angle histogram", "Speed histogram", "Acceleration histogram",
            "Angle by station", "Speed by station", "Acceleration by station", "Angle over time · every run"}


def deployment_coverage() -> dict:
    page = build_pages.deployment_page()
    return with_voxels(subset(page, lambda i, p: text_starts(p, "### Coverage", "### Every station") or bool(set(panel_views(p)) & COVERAGE)),
                       "Runs per cell · every station")


def with_voxels(doc: dict, name: str) -> dict:
    """Verdict-scaled voxels (CONTRACT §32, §35): how many runs reached each (q, qd) cell, red for few and green for many. WHY
    runs per cell: at 1/n opacity a path stops reading past ~200 runs (an 8-bit alpha), and the rack has 1,549; a count does not.
    Each station is on its own 24 x 24 grid over the range it ran (site/overlays.py), so the rack's stations share one picture."""
    doc["datasets"]["cells"] = {"data": "data/{deployment}/coverage_cells.json", "label": "Coverage cells"}
    doc["views"].append({"type": "voxels", "name": name, "from": "cells",
                         "voxels": {"x": "q_cell", "y": "qd_cell", "z": "z", "cell": 1, "unit": "m", "value": "runs", "scale": "verdict",
                                    "better": "higher", "projection": "top", "axes": "none"}})
    doc["layout"]["panels"] += [{"text": f"### {name}\nHow many runs reached each cell of (q, qd), each station on its own 24 × 24 grid over the "
                                         "range it ran (q across, qd up): green where many runs went, red where few did, nothing where none did. "
                                         "A count, so it still reads past the ~200 runs where 1/n opacity fades to nothing.", "w": 12},
                                {"view": name, "w": 12, "h": 6}]
    return doc


def scoped(doc: dict, device_filter: str) -> dict:
    """A deployment page's datasets scoped to one station (the page's scope is data, never a filter the reader clears)."""
    for name, ds in doc.get("datasets", {}).items():
        ds["filters"] = device_filter
        ds["facets"] = [f for f in ds.get("facets", []) if f.get("property") != "device"]
        if not ds["facets"]:
            ds.pop("facets")
    return doc


def station_runs() -> dict:
    doc = scoped(deployment_runs(), 'device == "{device}"')
    # WHY no tree here: the page is one station, a leaf; its place in the tree is the trail and the deployment's rail
    for ds in doc.get("datasets", {}).values():
        if ds.get("facets"):
            ds["facets"] = [f for f in ds["facets"] if f.get("as") != "tree"]
    doc["layout"]["panels"][0] = {"text": "### {device} · runs\n**REAL data**: every run this station recorded, newest first. "
                                          "**Open ↗** plays one back against its models. Blue is real, orange is a model, grey dashed is the target.", "w": 12}
    doc["views"] = [v for v in doc["views"] if v["name"] != "Stations shown"]
    doc["layout"]["panels"] = [p for p in doc["layout"]["panels"] if "Stations shown" not in panel_views(p)]
    for p in doc["layout"]["panels"]:
        if set(panel_views(p)) & {"Runs shown", "Hours shown", "Runs with models", "Config recorded"}:
            p["w"] = 3
    return doc


def station_coverage() -> dict:
    page = build_pages.deployment_page()
    by_station = {"Angle by station", "Speed by station", "Acceleration by station"}
    doc = subset(page, lambda i, p: text_starts(p, "### Coverage") or bool(set(panel_views(p)) & (COVERAGE - by_station)))
    doc["layout"]["panels"][0] = {"text": "### Coverage · {device}\nWhere this station's runs went. Every path is drawn at exactly 1/n opacity "
                                          "(n = its runs, no floor), so the dark bands are where it spends its time; past about 200 runs a lone path fades out, "
                                          "and **Runs per cell** below counts the runs in each cell where paths fade out; the dashed box is its proven window (travel × speed ceiling) when one is recorded.", "w": 12}
    return scoped(with_voxels(doc, "Runs per cell · {device}"), 'device == "{device}"')


def run_playback(models: list[str] | None = None, robots: bool = True) -> dict:
    """The run's Playback, plus the gates' limits: T4's stop allocation on the error against the target and T2's 1.5x floor on
    each model's error against real (threshold_band, one rule pair per series), and the output link coloured by its distance
    from the target with T4's allocation as a tube round the target's path (path_overlay). The numbers are the station's,
    filled per page from the record (static/sim2real.js); a station without one draws no limit (null)."""
    doc = build_pages.run_page()
    for view in doc["views"]:
        if view["name"] == "Error against the target (target − each)":
            view["timeseries"]["limits"] = {"error": ["{t4_lo_mrad}", "{t4_hi_mrad}"]}
        elif view["name"] == "Model error against real (real − model)":
            view["timeseries"]["limits"] = {"error": ["{t2_lo_mrad}", "{t2_hi_mrad}"]}
    # WHY real only beside the target: every model's path lies on the same arc, so painted together the last one drawn hides
    # the rest; the models' own errors against real are the panel above
    doc["views"].append({"type": "trajectory3d", "name": "Output link · distance from the target", "from": "poses",
                         "filters": 'source != "sim"',
                         "trajectory3d": {"series": "situation", "family": "source", "unit": "mm", "show": "all", "projection": "top",
                                          "axes": "auto", "color": "err_mm", "tolerance": "{t4_tube_mm}",
                                          # WHY the target as sparse points: within a millimetre of the real path, its line hid the colours
                                          "modes": {"target": ["points"]}, "density": 6}})
    panels = doc["layout"]["panels"]
    at = next(i for i, p in enumerate(panels) if p.get("view") == "Error against the target (target − each)")
    panels[at:at] = [{"text": "### Errors against the gates' limits\nThe dashed red rules are this station's limits: **T4's stop allocation** on the "
                              "error against the target (it binds at the holds; a move may pass it) and **T2's 1.5× floor** on each model's error "
                              "against real (T2 judges the whole run's RMS, so a moment past it is not a fail). Shaded: beyond the limit.", "w": 12}]
    at = next(i for i, p in enumerate(panels) if p.get("view") == "Output link · top (down the joint axis)") + 1
    panels[at:at] = [{"text": "### Distance from the target\nThe real marker's path coloured by how far it is from the target at that instant "
                              "(the producer's err_mm: blue near, amber far), with T4's stop allocation at the marker as a tube round the target's path.", "w": 12},
                     {"view": "Output link · distance from the target", "w": 12, "h": 5}]
    # WHY a component (the coordinator, 2026-11-07: the run page's next redesign drops the media in per entity level): the joint's 3D card is
    # site/components.py's joint-3d, composed in place of build_pages' own card, the same views a page of any entity level mounts
    return components.compose(doc, components.joint_3d(models or [])) if robots else doc


def run_media(models: list[str] | None = None) -> dict:
    """A run whose session filmed its station: the Playback plus the camera-clip and joint-render components side by side, right under
    the playback bar (tools/build_media.py's media.json, PEP 0005's media rows). WHY two video cards and not data-ui's video-compare
    overlay: the render is a front view of the joint's own frame, not the camera's calibrated pinhole, so an onion or a wipe would lay
    unregistered pictures on each other; side by side they read as what they are."""
    return components.compose(run_playback(models), components.clips_pair(), after="Playback")


def run_why() -> dict:
    page = build_pages.run_why_page()
    doc = subset(page, lambda i, p: bool(set(panel_views(p)) & {"Torque gap by term family", "Move error by phase"}))
    doc["layout"]["panels"] = [{"text": "### Residual decomposition · {device}\nThe study's decomposition on the held-out tapes: how much of the torque the rack "
                                        "needed beyond the twin each term family explains on its own (unique R²), and where the move error sits. "
                                        "The bars are neither real nor model, so they are grey.", "w": 12}] + doc["layout"]["panels"]
    doc["data"] = doc["datasets"]["decomposition"]["data"]
    doc.pop("clock", None)  # no samples here: the playback is its own tab
    for view in doc["views"]:
        # WHY no domain: the producer's v2 rows name the twins ("before (twin today, C)", "after (declared pick, …)"), which
        # build_pages' fixed domain (v1's "before (deployed twin)") does not hold, so Vega-Lite drew no bar at all. Two
        # greys in row order keep the bars neither real nor model.
        view["chart"]["encoding"]["color"]["scale"].pop("domain", None)
    return doc


MODEL = "var(--data-series-2)"
SCHEDULE_SERIES = {  # the schedule's curve series: the target grey (dashed), every model orange, lighter or darker per condition
    "target": "#8b9099",
    "model · fb": MODEL,
    "model · ff_weakfb": "color-mix(in srgb, var(--data-series-2) 62%, black)",
    "model · fb kp×0.5": "color-mix(in srgb, var(--data-series-2) 70%, white)",
    "model · fb kp×0.25": "color-mix(in srgb, var(--data-series-2) 45%, white)",
    "model · open_loop_torque": "color-mix(in srgb, var(--data-series-2) 80%, black)",
}


def _heat(name: str, plane: str, split: str, x_title: str, y_title: str, symlog: tuple[bool, bool]) -> dict:
    axis = lambda field, title, log: {"field": field, "type": "quantitative", "title": title,  # noqa: E731
                                      **({"scale": {"type": "symlog", "constant": 1}} if log else {})}
    return {"type": "chart", "name": name, "from": "cells", "filters": f'plane == "{plane}" && split == "{split}"',
            "chart": {"mark": {"type": "rect", "stroke": "var(--rule2, #e3e5e8)", "strokeWidth": 0.3},
                      "encoding": {"x": axis("x0", x_title, symlog[0]), "x2": {"field": "x1"}, "y": axis("y0", y_title, symlog[1]), "y2": {"field": "y1"},
                                   "color": {"field": "state", "type": "nominal", "title": None,
                                             "scale": {"domain": ["visited", "reachable, not visited"], "range": ["var(--data-series-1)", "#d5d8de"]}},
                                   "tooltip": [{"field": "samples", "type": "quantitative", "title": "samples"}]}}}


def station_schedule() -> dict:
    """A station's Schedule tab: bam_rack_twin.schedule's plan before anything runs (site/build.py links it under data/<dep>/schedule/)."""
    root = "/data/{deployment}/schedule/{station}/"
    return {
        "data": root + "runs.json",
        "properties": {"run": {"displayName": "Run"}, "trajectory": {"displayName": "Trajectory"}, "family": {"displayName": "Family"},
                       "code": {"displayName": "Code"}, "group": {"displayName": "Set"}, "split": {"displayName": "Split"},
                       "held_out_set": {"displayName": "Held-out set"}, "mode": {"displayName": "Mode"}, "kp_level": {"displayName": "kp ×"},
                       "runner": {"displayName": "Runner"}, "status": {"displayName": "Status"}, "duration_s": {"displayName": "Seconds"},
                       "torque_peak_nm": {"displayName": "Peak torque (N·m, predicted)"}, "model_q_rms_mrad": {"displayName": "Model vs target (mrad)"},
                       "fb_share": {"displayName": "FB share (model)"}, "guard": {"displayName": "First guard (model)"},
                       "trajectories": {"displayName": "Trajectories"}, "runs": {"displayName": "Runs"}, "seconds_each": {"displayName": "Seconds each"},
                       "run_seconds": {"displayName": "Seconds, all runs"}, "note": {"displayName": "What it is"}},
        "style": {"chrome": "minimal", "numbers": {"digits": 3, "compact": True}, "palette": dict(SCHEDULE_SERIES)},
        "datasets": {
            "runs": {"data": root + "runs.json", "label": "Planned runs",
                     "facets": [{"property": "group", "label": "Set"}, {"property": "family", "label": "Family"}, {"property": "split", "label": "Split"},
                                {"property": "mode", "label": "Mode"}]},
            "curves": {"data": root + "curves.json", "label": "Targets and model curves"},
            "cells": {"data": root + "cells.json", "label": "Coverage cells"},
            "families": {"data": root + "families.json", "label": "Families"},
        },
        "links": [{"from": "curves.trajectory", "to": "runs.trajectory"}],
        "layout": {"panels": [
            {"text": "### Planned · not run yet\nThe schedule bam_rack_twin.schedule wrote for {device}: every trajectory's **target** (grey, dashed) and the "
                     "twin of record's **model** of it (orange), before any run. The rail narrows it by set, family, split and mode.", "w": 12},
            {"view": "Planned trajectories", "w": 12, "h": 5},
            {"view": "Coverage · q × qd · train", "w": 6, "h": 4}, {"view": "Coverage · q × qd · held-out", "w": 6, "h": 4},
            {"view": "Coverage · qd × qdd · train", "w": 6, "h": 4}, {"view": "Coverage · qd × qdd · held-out", "w": 6, "h": 4},
            {"view": "Families", "w": 12, "h": 4},
            {"view": "Planned runs", "w": 12, "h": 6},
        ]},
        "views": [
            {"type": "chart", "name": "Planned trajectories", "from": "curves",
             "chart": {"mark": {"type": "line", "strokeWidth": 1.1, "interpolate": "linear"},
                       "encoding": {"x": {"field": "t", "type": "quantitative", "title": "t from the start of the run (s)"},
                                    "y": {"field": "q_deg", "type": "quantitative", "title": "q from the origin (°)"},
                                    "detail": {"field": "trajectory", "type": "nominal"},
                                    "color": {"field": "series", "type": "nominal", "title": None,
                                              "scale": {"domain": list(SCHEDULE_SERIES), "range": list(SCHEDULE_SERIES.values())}},
                                    "strokeDash": {"field": "series", "type": "nominal", "legend": None,
                                                   "scale": {"domain": list(SCHEDULE_SERIES), "range": [[5, 3]] + [[1, 0]] * (len(SCHEDULE_SERIES) - 1)}}}}},
            _heat("Coverage · q × qd · train", "q_qd", "train", "q (°)", "qd (°/s)", (False, True)),
            _heat("Coverage · q × qd · held-out", "q_qd", "held-out", "q (°)", "qd (°/s)", (False, True)),
            _heat("Coverage · qd × qdd · train", "qd_qdd", "train", "qd (°/s)", "qdd (°/s²)", (True, True)),
            _heat("Coverage · qd × qdd · held-out", "qd_qdd", "held-out", "qd (°/s)", "qdd (°/s²)", (True, True)),
            {"type": "table", "name": "Families", "from": "families", "order": ["code", "family", "group", "runner", "trajectories", "runs", "seconds_each",
                                                                                 "run_seconds", "note"]},
            {"type": "table", "name": "Planned runs", "from": "runs", "order": ["run", "status", "split", "held_out_set", "mode", "kp_level", "runner",
                                                                                "duration_s", "torque_peak_nm", "model_q_rms_mrad", "fb_share", "guard"]},
        ],
    }


PAGES = {
    "deployment-runs.base": ("a deployment's Runs tab", deployment_runs),
    "deployment-gates.base": ("a deployment's Gates tab", deployment_gates),
    "deployment-why.base": ("a deployment's Why it fails tab", deployment_why),
    "deployment-coverage.base": ("a deployment's Coverage tab", deployment_coverage),
    "station-runs.base": ("a station's Runs tab", station_runs),
    "station-coverage.base": ("a station's Coverage tab", station_coverage),
    "run.base": ("a run's Playback tab", run_playback),
    "run-media.base": ("a run's Playback tab when its session filmed it: the camera clip and the twin's render above the plots", run_media),
    "run-why.base": ("a run's Why it fails tab: its station's residual decomposition", run_why),
    "station-schedule.base": ("a station's Schedule tab: the test schedule before anything runs (bam_rack_twin.schedule)", station_schedule),
    "station-gates.base": ("a station's Gates tab: its gate history, every run's checks and their evidence", station_gates),
    "gate-matrix.base": ("the home's gate matrix: stations x T1-T11 of the deployment the URL names", home_gates),
}


def files(site=None):
    """(views/<name>.base, text) for every tab dashboard, checked to round-trip through data-ui's own reader. The deployment's tree
    facet takes its levels from the site's runs (node_1 … node_<depth>; node_0 is the deployment the page already is)."""
    import deploy_tree  # noqa: PLC0415

    levels = [f"node_{k}" for k in range(1, deploy_tree.depth(site) + 1)] if site is not None else []
    # every model name a run plays, so the 3D card draws each translucent (data-ui keys a robot's look by its series)
    models = sorted({s for r in (site.runs if site is not None else []) for s in r.get("situations", []) if s not in ("real", "target")})
    # WHY no robots without the media: their link poses and link model are tools/build_media.py's (a site built without them keeps the paths)
    media = getattr(site, "media", None) is not None
    pages = dict(PAGES)
    if media:
        # each media component alone, mountable at any entity level: its entity in the .base URL's query (site/components.py)
        for cname, cmake in components.COMPONENTS.items():
            pages[f"components/{cname}.base"] = (f"the {cname} component alone: {cmake().what if cname != 'joint-3d' else cmake(models).what}",
                                                 lambda cmake=cmake, cname=cname: components.standalone(cmake(models) if cname == "joint-3d" else cmake(),
                                                                                                         style=copy.deepcopy(build_pages.STYLE)))
    for name, (what, make) in pages.items():
        if name == "run-media.base" and not media:
            continue
        doc = rooted(make(levels) if name == "deployment-runs.base" else make(models, media) if name == "run.base" else make(models) if name == "run-media.base" else make())
        text = (f"# sim2real · {what}\n# Written by site/views.py from tools/build_pages.py (do not edit by hand). static/sim2real.js fills "
                f"{{deployment}}, {{run}}, {{station}}, {{device}} and {{glb}}.\n") + data_ui_base.dumps(doc)
        assert data_ui_base.loads(text) == json.loads(json.dumps(doc)), f"{name}: the .base does not round-trip"
        yield f"views/{name}", text
