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
    mrad (gates.json) and each station's joint description (its live test schedule's)."""
    nodes: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    run_diagnostics: list = field(default_factory=list)
    coverage_points: list = field(default_factory=list)
    floors: dict = field(default_factory=dict)
    descriptions: dict = field(default_factory=dict)


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


def _metric_entries(spec: dm.MetricSpec, runs: list[dict], diags: dict, floor: float | None) -> list[dict]:
    base = {"metric": spec.id, "title": spec.title, "unit": spec.unit, "pinned": spec.pinned, "family": spec.family,
            "aggregate": spec.aggregate}
    src = spec.per_run
    if src is None:
        return [{**base, "model": None, "value": None, "low": None, "high": None, "n": 0, "source": "", "why": spec.why_not}]
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


def _gates(t: dm.EntityType, entries: dict) -> list[dict]:
    out = []
    diags = {d.id: d for d in t.diagnostics}
    for g in t.gates:
        d = diags.get(g.diagnostic)
        metric = d.metric if d else ""
        for e in entries.get(metric, [{"model": None, "value": None}]):
            value = e["value"]
            if value is None:
                verdict, why = "not_run", "no value from the selected runs"
            elif g.target.value is None:
                verdict, why = "unknown", f"its target is set per unit ({g.target.note or 'no value'})"
            else:
                verdict, why = reg.gate_status(g, value), ""
            # WHY "statistic": the gate's target on this selection's aggregate, never bam_rack_twin's acceptance statistic (T2 pools its
            # held-out set its own way); the acceptance verdicts stay gates.json's
            out.append({"gate": g.id, "diagnostic": g.diagnostic, "metric": metric, "model": e["model"], "verdict": verdict, "value": value,
                        "target": g.target.text(), "acceptance": g.acceptance, "statistic": "the selection's aggregate (its metric's)", "why": why})
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
    devices = {by_run[i]["device"] for i in found}
    out_nodes = []
    for node in sorted((n for n in tables.nodes if n.get("device") in devices and n.get("entity_type")), key=lambda n: n["id"]):
        t = dm.TYPES[node["entity_type"]]
        runs = [by_run[i] for i in found if by_run[i]["device"] == node["device"]]
        floor = tables.floors.get(node["device"])
        entries: dict[str, list[dict]] = {}
        metrics = []
        for spec in t.metrics:
            got = _metric_entries(spec, runs, diags, floor)
            entries[spec.id] = got
            metrics += got
        rows = []
        for d in t.diagnostics:
            if d.units != "metric":
                continue  # a drift check needs its calibrated or commissioned value, which a selection alone does not hold
            for e in entries.get(d.metric, []):
                rows.append(dm.diagnostic_row(d, e["value"], subject=node["id"], metric=d.metric, model=e["model"], runs=e["n"],
                                              device=node["device"], hint="threshold_band"))
        out_nodes.append({"node": node["id"], "device": node["device"], "entity_type": t.id, "runs": len(runs), "metrics": metrics,
                          "diagnostics": rows, "gates": _gates(t, entries),
                          "coverage": _coverage(t, node["device"], {r["run"] for r in runs}, tables, points)})
    return {"schema": SCHEMA, "name": name, "runs": len(found), "run_ids": found,
            "run_ids_sha256": hashlib.sha256("\n".join(found).encode()).hexdigest(), "unknown_runs": [i for i in ids if i not in by_run],
            "nodes": out_nodes}


# --- the browser's coverage rule ------------------------------------------------------------------------------------------------------

def _grid(desc: dict):
    edges = cov.joint_edges(desc)
    ok = cov.joint_reachable(desc)
    centres = [cov.centres(a) for a in edges]
    import itertools  # noqa: PLC0415

    reach = {cell for cell in itertools.product(*(range(cov.n_cells(a)) for a in edges)) if ok(tuple(centres[k][i] for k, i in enumerate(cell)))}
    return edges, reach


def coverage_cells(tables: Tables) -> dict:
    """The run x cell table the browser counts: one row per (run, device, cell) the run's points visit, with whether the cell is
    reachable and how many points fell in it; reachable_cells per device is the denominator. Devices with a joint description only."""
    rows = []
    reachable = {}
    for device, desc in sorted(tables.descriptions.items()):
        edges, reach = _grid(desc)
        reachable[device] = len(reach)
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
            "reachable_cells": reachable, "rows": rows}


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
                  coverage_points=_rows(folder / "coverage.json"), floors=floors, descriptions=descriptions)
