"""The data-ui dashboards the record tabs hold: tools/build_pages.py's pages, cut along the tabs.

Every panel the app showed is in exactly one tab's .base here, taken from the same functions (build_pages.deployment_page,
deployment_gates_page, run_page, run_why_page), so a panel can never drift between the app and the site:

    deployment-runs.base      the deployment's Runs tab: intro, the four KPIs, Runs · newest first (owns the URL)
    deployment-gates.base     its Gates tab: the gates layer overlay (gauge, passing per gate, stations x gates, verdicts)
    deployment-why.base       its Why it fails tab: the why tables, Evidence files, Caveats
    deployment-coverage.base  its Coverage tab: phase space, time at (q, qd), the histograms and boxes, angle over time
    station-runs.base         a station's Runs tab: the deployment's runs scoped to the station
    station-coverage.base     a station's Coverage tab: the coverage panels scoped to the station
    run.base                  a run's Playback tab (unchanged)
    run-why.base              a run's Why it fails tab: its station's decomposition bars (the playback stays one tab away)

Paths are rooted at /data/ (the site's copy of app/data); `{deployment}`, `{run}`, `{station}` and `{device}` are filled
by static/sim2real.js from the page's record, as app/app.js did (data-ui has no per-run dataset template yet, PEP 0010 P3).
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


def deployment_runs() -> dict:
    page = build_pages.deployment_page()
    runs = {"Runs shown", "Hours shown", "Stations shown", "Runs with models", "Runs"}
    return subset(page, lambda i, p: i == 0 or bool(set(panel_views(p)) & runs))


def deployment_gates() -> dict:
    page = build_pages.deployment_gates_page()
    overlay = {"Gate cells passing", "Runs a model twins", "Passing per gate", "Stations × gates", "Run verdicts", "Station diagnostics"}
    return subset(page, lambda i, p: text_starts(p, "## Gates layer") or bool(set(panel_views(p)) & overlay))


def deployment_why() -> dict:
    page = build_pages.deployment_page()
    why = {"Why it fails", "Why it fails · columns", "Evidence files", "Caveats"}
    return subset(page, lambda i, p: text_starts(p, "### Why it fails") or bool(set(panel_views(p)) & why))


COVERAGE = {"Phase space · every run", "Time at (q, qd)", "Angle histogram", "Speed histogram", "Acceleration histogram",
            "Angle by station", "Speed by station", "Acceleration by station", "Angle over time · every run"}


def deployment_coverage() -> dict:
    page = build_pages.deployment_page()
    return subset(page, lambda i, p: text_starts(p, "### Coverage", "### Every station") or bool(set(panel_views(p)) & COVERAGE))


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
    doc["layout"]["panels"][0] = {"text": "### {device} · runs\n**REAL data**: every run this station recorded, newest first. "
                                          "**Open ↗** plays one back against its models. Blue is real, orange is a model, grey dashed is the target.", "w": 12}
    doc["views"] = [v for v in doc["views"] if v["name"] != "Stations shown"]
    doc["layout"]["panels"] = [p for p in doc["layout"]["panels"] if "Stations shown" not in panel_views(p)]
    for p in doc["layout"]["panels"]:
        if set(panel_views(p)) & {"Runs shown", "Hours shown", "Runs with models"}:
            p["w"] = 4
    return doc


def station_coverage() -> dict:
    page = build_pages.deployment_page()
    by_station = {"Angle by station", "Speed by station", "Acceleration by station"}
    doc = subset(page, lambda i, p: text_starts(p, "### Coverage") or bool(set(panel_views(p)) & (COVERAGE - by_station)))
    doc["layout"]["panels"][0] = {"text": "### Coverage · {device}\nWhere this station's runs went. Every path is drawn at 1/n opacity, so the dark "
                                          "bands are where it spends its time; the dashed box is its proven window (travel × speed ceiling) when one is recorded.", "w": 12}
    return scoped(doc, 'device == "{device}"')


def run_playback() -> dict:
    return build_pages.run_page()


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


PAGES = {
    "deployment-runs.base": ("a deployment's Runs tab", deployment_runs),
    "deployment-gates.base": ("a deployment's Gates tab", deployment_gates),
    "deployment-why.base": ("a deployment's Why it fails tab", deployment_why),
    "deployment-coverage.base": ("a deployment's Coverage tab", deployment_coverage),
    "station-runs.base": ("a station's Runs tab", station_runs),
    "station-coverage.base": ("a station's Coverage tab", station_coverage),
    "run.base": ("a run's Playback tab", run_playback),
    "run-why.base": ("a run's Why it fails tab: its station's residual decomposition", run_why),
}


def files():
    """(views/<name>.base, text) for every tab dashboard, checked to round-trip through data-ui's own reader."""
    for name, (what, make) in PAGES.items():
        doc = rooted(make())
        text = (f"# sim2real · {what}\n# Written by site/views.py from tools/build_pages.py (do not edit by hand). static/sim2real.js fills "
                f"{{deployment}}, {{run}}, {{station}} and {{device}}.\n") + data_ui_base.dumps(doc)
        assert data_ui_base.loads(text) == json.loads(json.dumps(doc)), f"{name}: the .base does not round-trip"
        yield f"views/{name}", text
