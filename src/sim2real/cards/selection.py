"""Metrics, diagnostics and coverage over any list of run ids (type_cards/CONTRACT.md, "Domain model v3": selections).

Zach (PROJECT - Sim2Real, 2026-11-06): "Generally I think we can calculate these metrics on a per run basis... but also accross all the
runs which is what we really want to do... But its just the row model you can basically like include or not what runs will be included
in the metrics/diagonistics etc"; "we want to make sure that the runs have good coverage so we can trust the metrics ... visualize
quickly like the currently selected runs or run what is its coverage ... wether it happens live or not. we certaintly need the ability to
do the computation".

compute(run_ids, tables) is a pure function: the same ids and tables give the same result, in any order. A single run is a selection
of one. The site calls it at build time for presets (instances.write); the browser does the same live by the rules in CONTRACT.md:
every per-run value is a column of a table the page already has (runs.json, run_gates.json), every cross-run value is one of data-ui's
own summaries (domain.AGGREGATES), a level is the diagnostic's limits on that value, and coverage is the count of distinct reachable
cells of the run x cell table (coverage_cells) whose run is selected, over the device's reachable cells. Stdlib only.

WHY the type card's own coverage function (cov.actuator_coverage), never a second binning: a coverage number must mean one thing in a
plan (schedule.py's rule, pinned to CAN 11's 66.15 % by tests/test_contract.py) and over recorded runs.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import coverage as cov
from . import domain as dm
from . import registry as reg

SCHEMA = "sim2real.domain/3#selection"


@dataclass(frozen=True, kw_only=True)
class Tables:
    """What a selection reads, one deployment's: its v3 nodes (instances), runs.json's rows, RobotDx's per-run diagnostic rows
    (run_gates.json), the coverage table's points (coverage.json: the absolute output angle in degrees), each station's T1 floor in
    mrad (gates.json) and each station's joint description (its live test schedule's); since 2026-11-07 the model-independent metrics
    tools/run_metrics.py writes per run (run_metrics.json: RobotDx's catalog entries on each run's npz)."""
    nodes: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    run_diagnostics: list = field(default_factory=list)
    coverage_points: list = field(default_factory=list)
    floors: dict = field(default_factory=dict)
    descriptions: dict = field(default_factory=dict)
    run_metrics: list = field(default_factory=list)   # tools/run_metrics.py's rows (run_metrics.json), 2026-11-07, additive


def aggregate(values: list[float], how: str) -> float | None:
    if not values:
        return None
    if how == "median":
        return float(statistics.median(values))
    if how == "mean":
        return float(statistics.fmean(values))
    if how in ("min", "max"):
        return float(min(values) if how == "min" else max(values))
    if how == "sum":
        return float(sum(values))
    if how == "count":
        return float(len(values))
    raise ValueError(f"aggregate {how!r} is not one of {dm.AGGREGATES}")


def model_label(title: str) -> str:
    """RobotDx's stock.model_error rows are titled "<model> vs real": the model's label is the producer's own words."""
    return title[:-len(" vs real")] if title.endswith(" vs real") else title


def _metric_entries(spec: dm.MetricSpec, runs: list[dict], diags: dict, floor: float | None, measured: dict | None = None) -> list[dict]:
    base = {"metric": spec.id, "title": spec.title, "unit": spec.unit, "pinned": spec.pinned, "family": spec.family,
            "aggregate": spec.aggregate}
    src = spec.per_run
    if src is None:
        return [{**base, "model": None, "value": None, "low": None, "high": None, "n": 0, "source": "", "why": spec.why_not}]
    if src.table == "run_metrics":
        rows = [m for r in runs for m in (measured or {}).get(r["run"], ()) if m.get("metric") == spec.id]
        values = [float(m["value"]) for m in rows if _number(m.get("value"))]
        # WHY the producer's own words when no run has a value: "no dwell of 0.25 s or more" says why a sine has no stop error
        whys = Counter(m.get("why") for m in rows if not _number(m.get("value")) and m.get("why"))
        why = "" if values else (whys.most_common(1)[0][0] if whys else f"no selected run has a run_metrics.json row for {spec.id} (tools/run_metrics.py)")
        # WHY the side beside the value: the stop error's title says "at the output", and the producer measures it on the encoder side (T4's
        # partial); a page says which, never the title alone
        sides = {m.get("side") for m in rows if _number(m.get("value")) and m.get("side")}
        return [{**base, "model": None, **_summary(values, spec.aggregate), "source": f"run_metrics.json {spec.id}", "why": why,
                 **({"side": sides.pop()} if len(sides) == 1 else {})}]
    if src.table == "runs":
        values = [float(r[src.column]) for r in runs if _number(r.get(src.column))]
        return [{**base, "model": None, **_summary(values, spec.aggregate), "source": f"runs.json {src.column}",
                 "why": "" if values else f"no selected run has {src.column}"}]
    by_model: dict[str | None, list[float]] = {}
    why = ""
    for r in runs:
        for d in diags.get(r["run"], ()):
            if d.get("diagnostic") != src.diagnostic or not _number(d.get("value")):
                continue
            value = float(d["value"])
            if src.divide_by == "floor":
                if not floor:
                    why = "the station has no T1 floor (gates.json) to divide by"
                    continue
                value /= floor
            by_model.setdefault(model_label(d.get("title", "")) if src.per_model else None, []).append(value)
    if not by_model:
        return [{**base, "model": None, "value": None, "low": None, "high": None, "n": 0, "source": f"run_gates.json {src.diagnostic}",
                 "why": why or ("no model replayed the selected runs" if src.per_model else f"no selected run has {src.diagnostic}")}]
    return [{**base, "model": m, **_summary(v, spec.aggregate), "source": f"run_gates.json {src.diagnostic}" + (" ÷ T1 floor" if src.divide_by else ""),
             "why": ""} for m, v in sorted(by_model.items(), key=lambda kv: kv[0] or "")]


def _number(value) -> bool:
    """A finite number. WHY: a producer may write NaN (Python's json allows it); skipped, it can neither turn a median into NaN nor stop
    the site build's JSON, which refuses NaN (browsers cannot parse it)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _summary(values: list[float], how: str) -> dict:
    if not values:
        return {"value": None, "low": None, "high": None, "n": 0}
    return {"value": aggregate(values, how), "low": float(min(values)), "high": float(max(values)), "n": len(values)}


def _gates(t: dm.EntityType, entries: dict, limits: dict | None = None) -> list[dict]:
    out = []
    diags = {d.id: d for d in t.diagnostics}
    for g in t.gates:
        d = diags.get(g.diagnostic)
        metric = d.metric if d else ""
        unit_target = ((limits or {}).get(g.diagnostic) or {}).get("target")
        for e in entries.get(metric, [{"model": None, "value": None}]):
            value = e["value"]
            if value is None:
                verdict, why = "not_run", "no value from the selected runs"
            elif g.target.value is None and unit_target is None:
                verdict, why = "unknown", f"its target is set per unit ({g.target.note or 'no value'})"
            else:
                # WHY a unit's target (2026-11-07): the T4 gate's target is the joint's own allocation, set on the deployment's record
                verdict, why = reg.gate_status(g, value, None if g.target.value is not None else unit_target), ""
            # WHY "statistic": the gate's target on this selection's aggregate, never bam_rack_twin's acceptance statistic (T2 pools its
            # held-out set its own way); the acceptance verdicts stay gates.json's
            out.append({"gate": g.id, "diagnostic": g.diagnostic, "metric": metric, "model": e["model"], "verdict": verdict, "value": value,
                        "target": g.target.text(), "acceptance": g.acceptance, "statistic": "the selection's aggregate (its metric's)", "why": why,
                        **({"target_value": unit_target} if g.target.value is None and unit_target is not None else {})})
    return out


def _coverage(t: dm.EntityType, device: str, ids: set, tables: Tables, points_by_run: dict) -> dict:
    spec = t.coverage
    base = {"gate_pct": spec.gate_pct, "rule": spec.rule}
    if not spec.from_runs:
        return {**base, "pct": None, "visited": None, "reachable": None, "samples": 0, "outside": 0, "verdict": "observed", "why": spec.why_not}
    desc = tables.descriptions.get(device)
    if not desc:
        return {**base, "pct": None, "visited": None, "reachable": None, "samples": 0, "outside": 0, "verdict": "unknown",
                "why": f"no joint description for {device} (its live test schedule's description: range, speed, accel, torque limit)"}
    points = [p for run in sorted(ids) for p in card_points(points_by_run.get(run, ()), device, desc)]
    result = cov.actuator_coverage(points, desc)
    verdict = "observed" if spec.gate_pct is None else ("pass" if result.pct >= spec.gate_pct else "fail")
    return {**base, "pct": result.pct, "visited": result.visited, "reachable": result.reachable, "samples": result.samples,
            "outside": result.outside, "marginals": dict(result.axes), "unplanned": list(result.unplanned), "verdict": verdict, "why": ""}


def card_points(rows, device: str, desc: dict) -> list[dict]:
    """coverage.json rows as the servo card's actuator_coverage reads them: q relative to the joint's origin, every angle in rad."""
    out = []
    for p in rows:
        if p.get("device") != device or None in (p.get("q_deg"), p.get("qd_deg_s"), p.get("qdd_deg_s2")):
            continue
        point = {"q": math.radians(p["q_deg"]) - desc.get("origin_rad", 0.0), "qd": math.radians(p["qd_deg_s"]), "qdd": math.radians(p["qdd_deg_s2"])}
        if p.get("tau_nm") is not None:
            point["load torque"] = p["tau_nm"]
        out.append(point)
    return out


def _index(rows, key="run") -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r.get(key), []).append(r)
    return out


def compute(run_ids, tables: Tables, name: str = "") -> dict:
    """Every metric, diagnostic, gate and coverage of every typed node the selected runs touch (a node touches a run when the run's
    device is its own). Pure: sorted, deduplicated ids; an id no table holds is reported in unknown_runs, never dropped silently."""
    ids = sorted(set(run_ids))
    by_run = {r["run"]: r for r in tables.runs}
    found = [i for i in ids if i in by_run]
    diags = _index(tables.run_diagnostics)
    points = _index(tables.coverage_points)
    measured = _index(tables.run_metrics)
    devices = {by_run[i]["device"] for i in found}
    out_nodes = []
    for node in sorted((n for n in tables.nodes if n.get("device") in devices and n.get("entity_type")), key=lambda n: n["id"]):
        t = dm.TYPES[node["entity_type"]]
        runs = [by_run[i] for i in found if by_run[i]["device"] == node["device"]]
        floor = tables.floors.get(node["device"])
        limits = node_limits(node)
        entries: dict[str, list[dict]] = {}
        metrics = []
        for spec in t.metrics:
            got = _metric_entries(spec, runs, diags, floor, measured)
            entries[spec.id] = got
            metrics += got
        rows = []
        for d in t.diagnostics:
            if d.units != "metric":
                continue  # a drift check needs its calibrated or commissioned value, which a selection alone does not hold
            for e in entries.get(d.metric, []):
                rows.append(dm.diagnostic_row(d, e["value"], subject=node["id"], limits=level_limits(limits.get(d.id)), metric=d.metric,
                                              model=e["model"], runs=e["n"], device=node["device"], hint="threshold_band"))
        out_nodes.append({"node": node["id"], "device": node["device"], "entity_type": t.id, "runs": len(runs), "metrics": metrics,
                          "diagnostics": rows, "gates": _gates(t, entries, limits),
                          "coverage": _coverage(t, node["device"], {r["run"] for r in runs}, tables, points)})
    return {"schema": SCHEMA, "name": name, "runs": len(found), "run_ids": found,
            "run_ids_sha256": hashlib.sha256("\n".join(found).encode()).hexdigest(), "unknown_runs": [i for i in ids if i not in by_run],
            "nodes": out_nodes}


def node_limits(node: dict) -> dict[str, dict]:
    """A node's per-unit limits by diagnostic id (deployments.json `limits`: one record per diagnostic, instances.unit_limits)."""
    return {x["diagnostic"]: x for x in (node.get("limits") or [])}


def level_limits(limit: dict | None) -> dict[str, float]:
    """The {"warn": v, "error": v} that domain.level and diagnostic_row take, from one of a node's limit records."""
    return {k: float(limit[k]) for k in ("warn", "error") if limit and limit.get(k) is not None}


# --- the browser's metrics rule -------------------------------------------------------------------------------------------------------

METRIC_VALUE_FIELDS = (("run", "string"), ("node", "string"), ("device", "string"), ("entity_type", "string"), ("metric", "string"),
                       ("model", "string"), ("value", "number"))


def metric_values(tables: Tables) -> dict:
    """The run x metric table the browser aggregates (CONTRACT, "Domain model v3"): one row per (run, typed node at the run's device, metric,
    model) whose per-run value is a finite number, exactly the values compute() reads (each fidelity value already ÷ the station's T1 floor).
    WHY a projection, as coverage_cells is: the page reads one table whatever the source (runs.json, run_gates.json, run_metrics.json)."""
    diags = _index(tables.run_diagnostics)
    measured = _index(tables.run_metrics)
    by_device: dict = {}
    for n in tables.nodes:
        if n.get("device") is not None and n.get("entity_type"):
            by_device.setdefault(n["device"], []).append(n)
    rows = []
    for run in sorted(tables.runs, key=lambda r: r["run"]):
        for node in sorted(by_device.get(run.get("device"), []), key=lambda n: n["id"]):
            for spec in dm.TYPES[node["entity_type"]].metrics:
                for model, value in _run_values(spec, run, diags, measured, tables.floors.get(node["device"])):
                    rows.append({"run": run["run"], "node": node["id"], "device": node["device"], "entity_type": node["entity_type"],
                                 "metric": spec.id, "model": model, "value": value})
    return {"name": "metric_values", "title": "Every run's value of every metric, per node and model", "contract": dm.SCHEMA,
            "rule": "a metric over a selection = its aggregate (data-ui's summary of that name: median by default) over the values of rows whose "
                    "`run` is selected, per (node, metric, model), with min, max and the count beside it (selection.metrics_from_values)",
            "schema": {"fields": [{"name": f, "type": t} for f, t in METRIC_VALUE_FIELDS]}, "rows": rows}


def _run_values(spec: dm.MetricSpec, run: dict, diags: dict, measured: dict, floor: float | None) -> list[tuple[str | None, float]]:
    """One run's (model, value) pairs of a metric, by its per_run source: _metric_entries' rule for a selection of one."""
    src = spec.per_run
    if src is None:
        return []
    if src.table == "runs":
        return [(None, float(run[src.column]))] if _number(run.get(src.column)) else []
    if src.table == "run_metrics":
        return [(None, float(m["value"])) for m in measured.get(run["run"], ()) if m.get("metric") == spec.id and _number(m.get("value"))]
    out = []
    for d in diags.get(run["run"], ()):
        if d.get("diagnostic") != src.diagnostic or not _number(d.get("value")):
            continue
        value = float(d["value"])
        if src.divide_by == "floor":
            if not floor:
                continue
            value /= floor
        out.append((model_label(d.get("title", "")) if src.per_model else None, value))
    return out


def metrics_from_values(rows, run_ids) -> dict[tuple, dict]:
    """The browser's rule in Python: {(node, metric, model): {value, low, high, n}} over the rows whose run is selected, the value being the
    metric's aggregate (tests/test_selection.py holds it equal to compute()'s for every subset of a fixture)."""
    ids = set(run_ids)
    groups: dict[tuple, list[float]] = {}
    types: dict[tuple, str] = {}
    for r in rows:
        if r["run"] in ids:
            key = (r["node"], r["metric"], r["model"])
            groups.setdefault(key, []).append(float(r["value"]))
            types[key] = r["entity_type"]
    out = {}
    for key, values in groups.items():
        spec = dm.metric(types[key], key[1])
        out[key] = _summary(values, spec.aggregate if spec else "median")
    return out


# --- the browser's coverage rule ------------------------------------------------------------------------------------------------------

def _grid(desc: dict):
    """(edges, reachable cells): the card's own rule (coverage.reachable_cells, once per description)."""
    return cov.joint_edges(desc), cov.reachable_cells(desc)


def coverage_cells(tables: Tables) -> dict:
    """The run x cell table the browser counts: one row per (run, device, cell) the run's points visit, with whether the cell is
    reachable and how many points fell in it; reachable_cells per device is the denominator. Devices with a joint description only."""
    rows = []
    reachable = {}
    grid = {}
    for device, desc in sorted(tables.descriptions.items()):
        edges, reach = _grid(desc)
        reachable[device] = len(reach)
        # WHY the grid (2026-11-07, additive): a page draws where the joint can go and where a selection went (the coverage heatmap) from the
        # same cells it counts; the axes are the card's own (coverage.joint_edges: q relative to the joint's origin, rad)
        grid[device] = {"axes": [{"name": name, "unit": unit, "edges": [float(x) for x in e]}
                                 for (name, unit), e in zip((("q", "rad"), ("qd", "rad/s"), ("qdd", "rad/s^2")), edges)],
                        "reachable": sorted(",".join(map(str, c)) for c in reach)}
        counts: dict = {}
        for p in tables.coverage_points:
            if p.get("device") != device:
                continue
            for point in card_points([p], device, desc):
                cell = tuple(cov.bin_index(v, e) for v, e in zip((point["q"], point["qd"], point["qdd"]), edges))
                if None not in cell:
                    counts[(p["run"], cell)] = counts.get((p["run"], cell), 0) + 1
        rows += [{"run": run, "device": device, "cell": ",".join(map(str, cell)), "reachable": cell in reach, "n": n}
                 for (run, cell), n in sorted(counts.items())]
    return {"name": "coverage_cells", "rule": "coverage of a selection = distinct `cell` values of rows whose `run` is selected and `reachable` is "
            "true, per device, ÷ reachable_cells[device], as a % to 2 decimals (selection.coverage_from_cells)",
            "reachable_cells": reachable, "grid": grid, "rows": rows}


def coverage_from_cells(rows, run_ids, reachable_cells: dict) -> dict[str, float]:
    ids = set(run_ids)
    seen: dict[str, set] = {}
    for r in rows:
        if r["run"] in ids:
            seen.setdefault(r["device"], set())
            if r["reachable"]:
                seen[r["device"]].add(r["cell"])
    return {d: round(100.0 * len(cells) / max(1, reachable_cells.get(d, 0)), 2) for d, cells in seen.items()}


# --- presets and loading ----------------------------------------------------------------------------------------------------------------

def presets(runs: list[dict]) -> dict[str, list[str]]:
    """The selections the site computes at build time: every run, each split, each station, each day (sorted ids)."""
    out = {"all": sorted(r["run"] for r in runs)}
    for key, word in (("split", "split"), ("device", "station"), ("day", "day")):
        for value in sorted({r.get(key) for r in runs if r.get(key)}):
            out[f"{word if key != 'split' else 'split'}: {value}"] = sorted(r["run"] for r in runs if r.get(key) == value)
    return out


def _rows(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")).get("rows", []) if path.is_file() else []


def gate_id(gate) -> str:
    """"T1 floor" -> "T1", "T10 live re-identification" -> "T10": a gates.json row's gate id is its first word."""
    words = str(gate or "").split()
    return words[0] if words else ""


def load_tables(data: Path, deployment: str, schedules: Path | None = None, nodes: list | None = None) -> Tables:
    """One deployment's tables from the app's data folder (app/data, or the site's OUT/data) and the test schedules' root."""
    from . import instances  # noqa: PLC0415  (instances.write calls this module: imported late, one way)

    folder = Path(data) / deployment
    schedules = Path(schedules) if schedules else instances.SCHEDULES
    # WHY the gate's id word, never a prefix: "T1" is also the start of "T10 live re-identification" and "T11 provenance", and a prefix
    # match read T10's value as 7 of the rack's 8 floors (tests/test_selection.py, the T1 floor tests)
    floors = {r["device"]: float(r["value"]) for r in _rows(folder / "gates.json")
              if gate_id(r.get("gate")) == "T1" and isinstance(r.get("value"), (int, float))}
    devices = [r["device"] for r in _rows(folder / "devices.json")]
    descriptions = {}
    for device in devices:
        path = schedules / deployment / device.lower().replace(" ", "") / "schedule.json"
        if path.is_file():
            descriptions[device] = json.loads(path.read_text(encoding="utf-8"))["description"]
    if nodes is None:
        nodes = [n for n in instances.physical_nodes(Path(data)) if n["root"] == deployment]
    return Tables(nodes=nodes, runs=_rows(folder / "runs.json"), run_diagnostics=_rows(folder / "run_gates.json"),
                  coverage_points=_rows(folder / "coverage.json"), floors=floors, descriptions=descriptions,
                  run_metrics=_rows(folder / "run_metrics.json"))
