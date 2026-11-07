"""Metrics, diagnostics and coverage over any selection of a deployment's runs, live in the browser (type_cards/CONTRACT.md, "Domain model
v3": metrics, diagnostics and coverage over selected runs).

Zach (PROJECT - Sim2Real, 2026-11-06): "Each entity type has Metrics we evaluate for it. Some of those metrics are more important than others
ones (the most improtant ones we kinda pin to the top ...) Then we have DIAGONISTICS ... metrics + gate that reports warning or error.
Generally I think we can calculate these metrics on a per run basis... but also accross all the runs which is what we really want to do...
But its just the row model you can basically like include or not what runs will be included in the metrics/diagonistics etc"; "As a model
can be good BUT only in a certain area. we want to make sure that the runs have good coverage so we can trust the metrics ... visualize
quickly like the currently selected runs or run what is its coverage ... we certaintly need the ability to do the computation".

/metrics/<dep>/ (the workbench's two panes): the runs table's filter rail in the left column; on the right the runs table (data-ui,
selectable) and beside it what the runs in play give: each station's pinned metrics with their diagnostics' levels and its coverage, every
diagnostic and metric of every entity in play (data-ui tables), the coverage heatmap (data-ui's chart, the robotics template's phase-space
view) and the command that freezes the selection as a report. The runs in play are the table's ticked rows when it has any, else the rows
its filters leave: Zach's "row model". static/metrics.js computes them by the contract's browser rule (each metric's per-run values from
data/domain/metric_values/<dep>.json, its aggregate by data-ui's own summarize, each diagnostic's limits with the unit's own from
deployments.json, the distinct reachable cells of data/domain/coverage_cells/<dep>.json); site/tests/test_site_flow.py holds every number to
selection.compute for three selections made in the page. Without script the page shows the build's "all" preset (sel.compute at build time).

Writes (site/build.py): data/domain/metric_runs/<dep>.json (the runs table's rows: each run's tags, its per-run values and their levels),
views/metrics-runs/<dep>.base, metrics/index.html and metrics/<dep>/index.html. Stdlib only. WHY a page of its own beside the deployments
pages, the host computing with data-ui's reducers and data-ui drawing, and the presets: docs/decision-metrics-reports-2026-11-07.md.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import PurePath

from catalog_workbench.data_ui import views_element
from catalog_workbench.html import breadcrumb, e, plural

import adapter
import deployments_pages as dpages
import pages
import ui_shared
import views
from type_cards import domain as dm  # noqa: E402
from type_cards import instances as inst  # noqa: E402
from type_cards import selection as sel  # noqa: E402

URL = "/metrics/"
RUNS_ID = "metrics-runs"
STYLES = ui_shared.head() + '<link rel="stylesheet" href="/static/metrics.css">\n'
SCRIPT = '<script type="module" src="/static/metrics.js"></script>\n'
# the per-run columns the runs table shows beside each run's tags: (column, its level's column, node type, metric, diagnostic, label)
PER_RUN = (
    ("stop_error_mrad", "stop_level", "integrated_servo", "servo.stop_error", "servo.stop_error.dx", "Stop error p90"),
    ("loop_rate_hz", "loop_level", "foc_controller", "driver.loop_rate", "driver.loop_rate.dx", "Loop rate"),
    ("saturation_pct", "saturation_level", "foc_controller", "driver.saturation", "driver.saturation.dx", "On the torque cap"),
)
TWIN = "twin of record"  # the model a run's twin column shows: the producer's own label for each station's twin of record
SUMMARY_NAME = {"median": "Median", "mean": "Average", "min": "Min", "max": "Max", "sum": "Sum", "count": "Count"}  # data-ui's names
TRUST = ("A model can be good only where it has been tried. Coverage is how much of where the joint can go the runs in play visited: each "
         "cell is a band of angle (q) and speed (qd) the joint can reach, shaded by the share of its acceleration bands (qdd) these runs went "
         "through. Trust the numbers above inside the shaded cells; outside them they say nothing, whatever their level.")


def base_text(doc: dict, what: str) -> str:
    text = (f"# sim2real · {what}\n# Written by site/metrics_pages.py (do not edit by hand); data by type_cards (selection.metric_values) and "
            f"site/build.py.\n") + views.data_ui_base.dumps(doc)
    assert views.data_ui_base.loads(text) == json.loads(json.dumps(doc)), f"{what}: the .base does not round-trip"
    return text


def page_url(dep: str) -> str:
    return f"{URL}{dep}/"


def runs_base_path(dep: str) -> str:
    return f"views/metrics-runs/{dep}.base"


def runs_data_path(dep: str) -> str:
    return f"data/domain/metric_runs/{dep}.json"


# --- the runs table: each run's tags, its per-run values and their levels -------------------------------------------------------------

def run_rows(d: dpages.Domain, dep: str) -> list[dict]:
    """One row per run (runs.json's, newest first): its tags, its per-run values (the metric values table's) and each value's level
    (domain.level with the unit's own limits: the run page's dots), the producer's why where a value is missing."""
    tables = d.tables[dep]
    values = sel.metric_values(tables)["rows"]
    by = {(r["run"], r["metric"], r["model"]): r["value"] for r in values}
    produced = {(r["run"], r["metric"]): r for r in tables.run_metrics}
    nodes = [n for n in d.tree(dep) if n.get("device") and n.get("entity_type")]
    node_of = {(n["device"], n["entity_type"]): n for n in nodes}
    twin_dx = dm.diagnostic("integrated_servo", "servo.twin_fidelity.dx")
    out = []
    for r in d.runs.get(dep, []):
        # WHY the run file's name as the first column: a run's title starts with its session's path, so a narrow column showed only that
        row = {"id": r["run"], "run": r["run"], "name": PurePath(r.get("npz") or r["run"]).stem, "title": r.get("title"), "url": adapter.run_url(r),
               "device": r["device"], "day": r.get("day"),
               "started": r.get("started"), "kind": r.get("kind"), "split": r.get("split"), "mode": r.get("mode"), "round": r.get("round"),
               "run_set": r.get("run_set"), "excitation": r.get("excitation"), "closed_loop": r.get("closed_loop"),
               "offline_scope": r.get("offline_scope"), "config": r.get("config"), "models": r.get("models"),
               "tracking_mrad": by.get((r["run"], "servo.tracking_rms", None))}
        for column, level, tid, metric, diag, _label in PER_RUN:
            node = node_of.get((r["device"], tid)) or {}
            value = by.get((r["run"], metric, None))
            row[column] = value
            row[level] = dm.level(dm.diagnostic(tid, diag), value, sel.level_limits(sel.node_limits(node).get(diag)))
            made = produced.get((r["run"], metric))
            if value is None and made and made.get("why"):
                row[column.rsplit("_", 1)[0] + "_why"] = made["why"]
        twin = by.get((r["run"], "servo.twin_fidelity", TWIN))
        row["twin_floor"] = twin
        row["twin_level"] = dm.level(twin_dx, twin)
        out.append(row)
    return out


FIELDS = {
    "run": ("string", {}), "name": ("string", {}), "title": ("string", {}), "url": ("string", {"display": "link"}), "device": ("string", {}), "day": ("string", {}),
    "started": ("datetime", {}), "kind": ("string", {"display": "badge"}), "split": ("string", {}), "mode": ("string", {}), "round": ("string", {}),
    "run_set": ("string", {}), "excitation": ("string", {}), "closed_loop": ("boolean", {}), "offline_scope": ("string", {}), "config": ("string", {}),
    "models": ("integer", {}), "tracking_mrad": ("number", {"unit": "mrad", "digits": 3}),
    "stop_error_mrad": ("number", {"unit": "mrad", "digits": 3}), "stop_level": ("string", {"display": "status"}),
    "loop_rate_hz": ("number", {"unit": "Hz", "digits": 3}), "loop_level": ("string", {"display": "status"}),
    "saturation_pct": ("number", {"unit": "%", "digits": 3}), "saturation_level": ("string", {"display": "status"}),
    "twin_floor": ("number", {"unit": "× floor", "digits": 3}), "twin_level": ("string", {"display": "status"}),
    "stop_error_why": ("string", {}), "saturation_why": ("string", {}),
}


def runs_dataset(d: dpages.Domain, dep: str) -> dict:
    rows = run_rows(d, dep)
    names = list(dict.fromkeys(["id"] + list(FIELDS) + [k for r in rows for k in r]))
    fields = [{"name": n, "type": FIELDS.get(n, ("string", {}))[0], **FIELDS.get(n, ("string", {}))[1]} for n in names]
    return {"name": "metric_runs", "title": f"{d.by_id[dep]['title']}: every run, its per-run values and their levels", "contract": dm.SCHEMA,
            "source": "runs.json (tagged) + data/domain/metric_values (selection.metric_values) + domain.level with each unit's limits "
                      "(site/metrics_pages.py)", "schema": {"fields": fields}, "rows": rows}


def runs_base(dep: str) -> dict:
    """views/metrics-runs/<dep>.base: the runs, newest first, with the rail Zach filters them by (station, day, kind, split, mode, session,
    excitation, the per-run levels) and each run's per-run values and levels beside its tags."""
    order = ["name", "device", "started", "kind", "stop_error_mrad", "stop_level", "loop_rate_hz", "loop_level", "saturation_pct",
             "saturation_level", "tracking_mrad", "twin_floor", "twin_level", "split", "round"]
    words = {"name": "Run file", "title": "Run", "device": "Station", "started": "Started", "kind": "Kind", "split": "Split", "tracking_mrad": "Tracking RMS",
             "stop_error_mrad": "Stop error p90", "stop_level": "Stop error level", "loop_rate_hz": "Loop rate", "loop_level": "Loop rate level",
             "saturation_pct": "On the torque cap", "saturation_level": "Torque cap level", "twin_floor": f"Twin / floor ({TWIN})",
             "twin_level": "Twin level", "day": "Day", "mode": "Mode", "round": "Session", "excitation": "Excitation", "run_set": "Run set",
             "config": "Config snapshot", "offline_scope": "Offline scope"}
    return {"data": "/" + runs_data_path(dep),
            "facets": [{"as": "current", "label": "Your filters"},
                       {"property": "device", "label": "Station"}, {"property": "day", "label": "Day"}, {"property": "kind", "label": "Kind"},
                       {"property": "split", "label": "Split"}, {"property": "mode", "label": "Mode"},
                       {"property": "round", "label": "Session", "searchable": True, "limit": 8},
                       {"property": "excitation", "label": "Excitation"}, {"property": "stop_level", "label": "Stop error level"},
                       {"property": "loop_level", "label": "Loop rate level"}, {"property": "saturation_level", "label": "Torque cap level"}],
            "properties": {k: {"displayName": v} for k, v in words.items()},
            "views": [{"type": "table", "name": "Runs", "order": order, "open": {"mode": "link", "url": "url"},
                       "columnSize": {"name": 190, "started": 150}, "sort": [{"property": "started", "direction": "DESC"}]}]}


# --- the page's spec: what static/metrics.js needs of the type level, the deployment's typed nodes and the presets ----------------------

def _limit(lim) -> dict | None:
    return None if lim is None else {"op": lim.op, "value": lim.value, "unit": lim.unit, "note": lim.note}


def sides(d: dpages.Domain, dep: str) -> dict[str, str]:
    """{metric: side} where every valued row of the producer's table names one side (the stop error: the encoder's)."""
    seen: dict[str, set] = {}
    for r in d.tables[dep].run_metrics:
        if r.get("value") is not None and r.get("side"):
            seen.setdefault(r["metric"], set()).add(r["side"])
    return {m: next(iter(v)) for m, v in seen.items() if len(v) == 1}


def labels(d: dpages.Domain, dep: str) -> dict[str, dict]:
    """{producer label: {type, model, url}} for every model the deployment's runs were replayed by, where type_cards maps the label to a ladder
    model (inst.label_model, exact words; a label nobody mapped is left out: unknown stays unknown)."""
    out = {}
    for row in d.tables[dep].run_diagnostics:
        if row.get("diagnostic") != "stock.model_error":
            continue
        label = sel.model_label(row.get("title", ""))
        m = inst.label_model(dep, label)
        if m and label not in out:
            out[label] = {"type": m.type, "model": m.model, "url": f"/models/{m.type}/#{m.model}"}
    return out


def model_words(label: str, mapped: dict, as_: str = "", mark: str = "") -> str:
    """A producer's label and, where it maps to one, the ladder model it is, linked (the models lane's rows: /models/<type>/#<model>).
    `as_` says whose map that is (a report's: frozen, or today's) as data-as; `mark` is a word shown after the model (a report's "today")."""
    m = mapped.get(label)
    to = (f' <span class="mut">→</span> <a data-model-link="{e(m["model"])}" href="{e(m["url"])}"><code>{e(m["model"])}</code></a>' if m else "")
    if mark:
        to += f' <small class="mut">{e(mark)}</small>'
    return f'<span data-label="{e(label)}" data-ladder="{e(m["model"] if m else "")}"{f" data-as={chr(34)}{e(as_)}{chr(34)}" if as_ else ""}>{e(label)}{to}</span>'


def spec(d: dpages.Domain, dep: str, presets: dict) -> dict:
    nodes = [n for n in d.tree(dep) if n.get("device") and n.get("entity_type")]
    side = sides(d, dep)
    station = {n["device"]: n["id"] for n in d.tree(dep) if n.get("structural") == "station"}
    types = {}
    for tid in sorted({n["entity_type"] for n in nodes}):
        t = dm.TYPES[tid]
        types[tid] = {"title": t.title,
                      "metrics": [{"id": m.id, "title": m.title, "unit": m.unit, "pinned": m.pinned, "family": m.family, "model_dependent": m.model_dependent,
                                   "aggregate": m.aggregate, "summary": SUMMARY_NAME[m.aggregate], "per_run": m.per_run is not None,
                                   "per_model": bool(m.per_run and m.per_run.per_model), "why_not": m.why_not, "side": side.get(m.id, "")}
                                  for m in t.metrics],
                      "diagnostics": [{"id": x.id, "metric": x.metric, "title": x.title, "warn": _limit(x.warn), "error": _limit(x.error),
                                       "units": x.units, "kind": x.kind, "message": x.message} for x in t.diagnostics],
                      "gates": [{"id": g.id, "diagnostic": g.diagnostic, "target": _limit(g.target), "acceptance": g.acceptance} for g in t.gates],
                      "coverage": {"from_runs": t.coverage.from_runs, "gate_pct": t.coverage.gate_pct, "rule": t.coverage.rule,
                                   "why_not": t.coverage.why_not, "dimensions": [x.name for x in t.coverage.dimensions if x.headline]}}
    return {"deployment": dep, "title": d.by_id[dep]["title"], "level_rank": dm.LEVEL_RANK,
            "nodes": [{"id": n["id"], "title": n["title"], "device": n["device"], "entity_type": n["entity_type"], "structural": n.get("structural"),
                       "parent": n.get("parent"), "station": station.get(n["device"]), "limits": n.get("limits") or []} for n in nodes],
            "types": types, "presets": presets, "labels": labels(d, dep),
            "data": {"values": f"/data/domain/metric_values/{dep}.json", "cells": f"/data/domain/coverage_cells/{dep}.json",
                     "runs": "/" + runs_data_path(dep), "reports": "/data/domain/reports/"}}


def preset_filters(runs: list[dict]) -> list[dict]:
    """The build's presets (selection.presets) as the rail filters that pick the same rows: every run, each split, each station, each day."""
    out = [{"name": "all", "label": "Every run", "filter": None, "runs": len(runs)}]
    for key, word in (("device", "station"), ("day", "day"), ("split", "split")):
        for value in sorted({r.get(key) for r in runs if r.get(key)}):
            n = sum(1 for r in runs if r.get(key) == value)
            out.append({"name": f"{word}: {value}", "label": value if key != "split" else f"{value.replace('_', ' ')}", "group": word,
                        "filter": f'{key} == "{value}"', "runs": n})
    return out


# --- the page --------------------------------------------------------------------------------------------------------------------------

def fmt(value, unit: str = "") -> str:
    if value is None:
        return "—"
    text = pages.num(float(value), 3) if isinstance(value, float) else pages.num(value)
    if unit.startswith("×"):
        return f"{text}{unit}"
    return f"{text} {unit}".strip()


def raw(value) -> str:
    return "" if value is None else repr(float(value))


def level_chip(level: str, text: str = "") -> str:
    return f'<span class="s2r-lv s2r-lv-{e(level)}" data-level="{e(level)}">{e(text or level)}</span>'


def node_level(result_node: dict) -> str:
    """The node's level over the runs in play: its worst model-independent diagnostic (the run page's dot, domain.LEVEL_RANK)."""
    rows = [x for x in result_node["diagnostics"] if not dm.metric(result_node["entity_type"], x["metric"]).model_dependent]
    return max((x["level"] for x in rows), key=dm.LEVEL_RANK.get, default="unknown")


def headline_model(result_node: dict, metric: str) -> dict | None:
    """A fidelity metric's headline: the model that replayed the most of the runs, then by name (the deployments lane's rule)."""
    rows = [m for m in result_node["metrics"] if m["metric"] == metric and m["value"] is not None]
    return min(rows, key=lambda m: (-m["n"], m.get("model") or "")) if rows else None


def other_models(sn: dict, m, headline: str, dx: dict, diag, mapped: dict | None = None) -> str:
    """Beside a fidelity metric's headline model, every other model that replayed the runs, each with its value and level (most runs first)."""
    if not m.model_dependent:
        return ""
    rows = sorted((x for x in sn["metrics"] if x["metric"] == m.id and x["value"] is not None and (x.get("model") or "") != headline),
                  key=lambda x: (-x["n"], x.get("model") or ""))
    if not rows:
        return ""
    items = []
    for x in rows:
        lv = dx.get((diag.id, x.get("model")), {}).get("level") if diag else None
        items.append(f'<li>{model_words(x.get("model") or "", mapped or {})} <span data-node="{e(sn["node"])}" data-metric="{e(m.id)}" data-model="{e(x.get("model") or "")}" '
                     f'data-value="{raw(x["value"])}">{e(fmt(x["value"], m.unit))}</span>{" " + level_chip(lv) if lv else ""} <small>{plural(x["n"], "run")}</small></li>')
    return f'<ul class="s2r-mothers" aria-label="Other models">{"".join(items)}</ul>'


def station_card(d: dpages.Domain, dep: str, result: dict, station: dict) -> str:
    """The static (no-script) answer for one station: its pinned metrics with their levels and its coverage, from a computed selection
    (sel.compute's shape); static/metrics.js draws the same markup live."""
    mapped = labels(d, dep)
    by = {n["node"]: n for n in result["nodes"]}
    sn = by.get(station["id"])
    if sn is None:
        return ""
    parts = [n for n in d.tree(dep) if n.get("parent") == station["id"] and n["id"] in by]
    dx = {(x["diagnostic"], x.get("model")): x for x in sn["diagnostics"]}
    tiles = []
    for m in [m for m in dm.TYPES["integrated_servo"].metrics if m.pinned]:
        if m.model_dependent:
            entry = headline_model(sn, m.id)
        else:
            entry = next((x for x in sn["metrics"] if x["metric"] == m.id), None)
        value = (entry or {}).get("value")
        model = (entry or {}).get("model") or ""
        diag = next((x for x in dm.TYPES["integrated_servo"].diagnostics if x.metric == m.id and x.units == "metric"), None)
        lv = dx.get((diag.id, entry.get("model") if entry else None), {}).get("level") if diag else None
        note = (f"median of {plural(entry['n'], 'run')}" + (f" · {entry['side']} side" if entry.get("side") else "") if value is not None
                else ((entry or {}).get("why") or m.why_not or "no value"))
        model_tag = f" <small>{model_words(model, mapped)}</small>" if model else ""
        chip = " " + level_chip(lv) if lv else ""
        others = other_models(sn, m, model, dx, diag, mapped)
        tiles.append(f'<div class="s2r-mtile{" s2r-mtile-wide" if others else ""}"><dt>{e(m.title)}{model_tag}</dt>'
                     f'<dd><span data-node="{e(station["id"])}" data-metric="{e(m.id)}" data-model="{e(model)}" data-value="{raw(value)}">{e(fmt(value, m.unit))}</span>'
                     f'{chip}</dd><small>{e(note)}</small>{others}</div>')
    c = sn["coverage"]
    cov = (f'<div class="s2r-mcov" data-coverage-node="{e(station["id"])}" data-coverage-pct="{raw(c.get("pct"))}">'
           + (f'<b>{pages.num(c["pct"])} %</b> of {c["reachable"]:,} reachable cells visited ({c["visited"]:,}) · gate {c["gate_pct"]:g} % '
              f'{pages.chip({"pass": "pass", "fail": "fail"}.get(c.get("verdict"), "not_run"), c.get("verdict"))}'
              f'<span class="s2r-mbar" role="img" aria-label="{pages.num(c["pct"])} % covered"><i style="width:{min(100.0, c["pct"]):g}%"></i>'
              f'<b style="left:{c["gate_pct"]:g}%"></b></span>' if c.get("pct") is not None else f'<span class="mut">{e(c.get("why") or "")}</span>') + "</div>")
    part_words = []
    for p in parts:
        pn = by[p["id"]]
        vals = [f'{x["title"]} {fmt(x["value"], x["unit"])}' for x in pn["metrics"] if x["value"] is not None and not x["family"] == "fidelity"]
        part_words.append(f'<li>{ui_shared.dot(node_level(pn))}<b>{e(p["title"].split(": ", 1)[0])}</b> {e(" · ".join(vals) or "no model-independent value")}</li>')
    return (f'<section class="s2r-mnode" data-node="{e(station["id"])}" data-level="{e(node_level(sn))}">'
            f'<h3>{ui_shared.dot(node_level(sn))}{e(station["device"])} <small>{plural(sn["runs"], "run")}</small></h3>'
            f'<dl class="s2r-mtiles">{"".join(tiles)}</dl>{cov}<ul class="s2r-mparts">{"".join(part_words)}</ul></section>')


def fallback(d: dpages.Domain, dep: str, result: dict) -> str:
    stations = [n for n in d.tree(dep) if n.get("structural") == "station"]
    cards = "".join(station_card(d, dep, result, s) for s in stations)
    return (f'<p class="s2r-mhow">Every run ({result["runs"]:,}), as the build computed it (selection.compute). With script the numbers follow '
            f'the table: tick runs, or filter them on the left.</p><div class="s2r-mnodes">{cards}</div>')


def body(d: dpages.Domain, dep: str, presets: dict) -> str:
    node = d.by_id[dep]
    runs = d.runs.get(dep, [])
    groups: dict = {}
    for p in presets["list"]:
        groups.setdefault(p.get("group") or "", []).append(p)
    chips = "".join(
        f'<span class="s2r-pgroup"><span class="s2r-pword">{e(word or "")}</span>'
        + "".join(f'<button type="button" class="s2r-preset" data-preset="{e(p["name"])}" data-filter="{e(p["filter"] or "")}" '
                  f'title="{e(p["name"])}: {p["runs"]:,} runs">{e(p["label"])} <span class="n">{p["runs"]:,}</span></button>' for p in ps)
        + "</span>" for word, ps in groups.items())
    computed = presets["computed"]
    spec_json = json.dumps(spec(d, dep, presets["list"]), ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    table_fallback = '<p class="mut">The runs table needs JavaScript: data-ui draws it.</p>'
    return f"""<article class="s2r-metrics" data-metrics-page data-deployment="{e(dep)}">
<h1>Metrics over a selection <span class="n">· {e(node["title"])}</span></h1>
<p class="lede">Pick the runs: tick rows, or filter the table on the left; with nothing ticked every run the filters leave is in play. Beside them,
each station's pinned metrics over those runs (the median), its diagnostics with their levels and how much of where it can go they covered.
Every number is computed here from each run's own value, the way <code>selection.compute</code> does it.</p>
<div class="s2r-presets" role="group" aria-label="Presets">{chips}</div>
<div class="s2r-mgrid">
<section class="s2r-mruns" aria-label="Runs">
{views_element(RUNS_ID, "/" + runs_base_path(dep), "Runs", table_fallback, attrs='selectable toolbar="bar" frame="flush"')}
</section>
<section class="s2r-mresults" aria-label="What the runs in play give">
<div id="s2r-metrics-results" data-how="preset" data-runs="{computed['all']['runs']}">{fallback(d, dep, computed['all'])}</div>
</section>
</div>
<section class="s2r-mcoverage" aria-labelledby="mcov-h"><h2 id="mcov-h">Coverage of the runs in play</h2>
<p class="s2r-trust">{e(TRUST)}</p>
<div id="s2r-metrics-coverage" class="s2r-mheat"><p class="mut">The heatmap needs JavaScript (data-ui's chart).</p></div>
<p class="mut s2r-mkey">Each station on its own grid: q across in 12 equal cells over its range, qd up as a share of its top speed (a dead band
around 0). Blue: the share of the cell's acceleration bands these runs visited; pale: reachable and not visited; blank: the joint cannot reach it
(it could not hold the cell's centre within its torque limit, or brake before its range ends). The numbers: <code>type_cards.coverage</code>, the
servo card's own cells.</p>
</section>
<details class="s2r-mdetail" open><summary><h2>Every diagnostic, with its level</h2></summary><div id="s2r-metrics-dx"></div></details>
<details class="s2r-mdetail"><summary><h2>Every metric</h2></summary><div id="s2r-metrics-all"></div></details>
<details class="s2r-freeze"><summary>Freeze this selection as a report</summary>
<p>A report is a named, frozen set of runs with its results captured when it is frozen (<a href="/reports/">Reports</a>). Run this from the repo,
then commit the two files it writes (<code>type_cards/frozen_reports/</code>):</p>
<pre><code></code></pre><p><button type="button" class="s2r-copy">Copy</button> <span class="mut s2r-freeze-note"></span></p>
</details>
<script type="application/json" id="s2r-metrics-spec">{spec_json}</script>
</article>"""


def index_body(d: dpages.Domain) -> str:
    items = []
    for n in d.roots():
        runs = d.runs.get(n["id"]) if n["kind"] == "physical" else None
        if runs:
            items.append(f'<li><a href="{e(page_url(n["id"]))}"><b>{e(n["title"])}</b></a> {ui_shared.chip(n["kind"], dpages.KIND_TONE.get(n["kind"], ""))} '
                         f'<small>{plural(len(runs), "run")} over {plural(len({r["device"] for r in runs}), "station")}</small></li>')
    virtual = [n for n in d.roots() if n["kind"] == "virtual"]
    # WHY a scenario links its deployment page: it has no oracle example page (sysid keeps the noise ladder's scenarios off the landing page)
    linked = ", ".join(pages.a(dpages.node_url(v["id"]) if dpages.is_scenario(d, v) else dpages.landing.url(v["id"]), v["title"]) for v in virtual)
    return f"""<h1>Metrics over a selection</h1>
<p class="lede">Each physical deployment's runs, with the metrics, diagnostics and coverage of whichever of them you pick. A virtual deployment
keeps no runs (sysid simulates them and keeps their results: {linked}).</p>
<ul class="s2r-mindex">{"".join(items)}</ul>"""


# --- the site's files --------------------------------------------------------------------------------------------------------------

def physical(d: dpages.Domain) -> list[str]:
    return [n["id"] for n in d.roots() if n["kind"] == "physical" and d.runs.get(n["id"]) and n["id"] in d.tables]


def write_data(data, site) -> dict:
    """data/domain/metric_runs/<dep>.json for every physical deployment with runs (site/build.py). Returns rows written."""
    d = dpages.load(site)
    out = {}
    for dep in physical(d):
        doc = runs_dataset(d, dep)
        path = data / "domain" / "metric_runs" / f"{dep}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
        out[dep] = len(doc["rows"])
    return out


def files(site):
    import catalog as s2r  # noqa: PLC0415

    d = dpages.load(site)
    deps = physical(d)
    yield "metrics/index.html", s2r.page(site, "Metrics: sim2real", URL, index_body(d), "metrics", extra_head=STYLES,
                                         trail=breadcrumb([s2r.ROOT_CRUMB, ("Metrics", URL)]),
                                         description="Metrics, diagnostics and coverage over any selection of a deployment's runs.")
    for dep in deps:
        yield runs_base_path(dep), base_text(runs_base(dep), f"{dep}'s runs for the metrics page: the rail, every run's per-run values and levels")
        selections = json.loads((site.data / "domain" / "selections" / f"{dep}.json").read_text(encoding="utf-8"))["presets"]
        presets = {"list": preset_filters(d.runs[dep]), "computed": selections}
        title = d.by_id[dep]["title"]
        yield f"metrics/{dep}/index.html", s2r.page(
            site, f"Metrics over a selection · {title}: sim2real", page_url(dep), body(d, dep, presets), "metrics",
            aside=ui_shared.filter_bar(RUNS_ID, "The filters need JavaScript; every run is listed on the right."), data_ui=True,
            extra_head=STYLES + SCRIPT, trail=breadcrumb([s2r.ROOT_CRUMB, ("Metrics", URL), (title, page_url(dep))]),
            description=f"{title}: metrics, diagnostics and coverage over any selection of its {len(d.runs[dep]):,} runs.")


def counts(site) -> Counter:
    d = dpages.load(site)
    return Counter({dep: len(d.runs[dep]) for dep in physical(d)})
