"""Metrics, diagnostics and coverage over any list of run ids (type_cards/selection.py), written before it (2026-11-07).

    uv run --no-project --with pytest pytest -q /home/bam/sim2real/type_cards/tests

Zach (2026-11-06): "Generally I think we can calculate these metrics on a per run basis... but also accross all the runs which is what
we really want to do... its just the row model you can basically like include or not what runs will be included"; coverage "for the
currently selected runs or run". The rules held here, on a fixture worked by hand:
- a run's value is its own row's (runs.json's column, or RobotDx's per-run diagnostic row, ÷ the station's T1 floor where the metric
  says so); across runs the metric's aggregate (median, data-ui's own summary, so the browser can do the same);
- a diagnostic's level is its limits' on that value; a gate's verdict its target's; per model where the metric needs one;
- coverage is the type card's own function over the selected runs' points (the card's rule, never a second one), and the browser's
  rule (distinct reachable cells of the run x cell table) gives the same number;
- one run is a selection of one; order does not matter; an unknown id is reported, never dropped silently.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from type_cards import coverage as cov  # noqa: E402
from type_cards import selection as sel  # noqa: E402

DESC_A = {"name": "a", "range_rad": [-1.0, 1.0], "speed_rad_s": 1.0, "accel_rad_s2": 1.0, "torque_limit_nm": 100.0, "origin_rad": 0.1}
NODES = [
    {"id": "rig", "parent": None, "device": None, "entity_type": None, "structural": "deployment"},
    {"id": "rig/a", "parent": "rig", "device": "A", "entity_type": "integrated_servo", "structural": "station"},
    {"id": "rig/a/driver", "parent": "rig/a", "device": "A", "entity_type": "foc_controller", "structural": None},
    {"id": "rig/b", "parent": "rig", "device": "B", "entity_type": "integrated_servo", "structural": "station"},
]
RUNS = [
    {"run": "r1", "device": "A", "kind": "waypoints", "samples": 100, "tracking_mrad": 2.0, "rate_hz": 100.0, "split": "train"},
    {"run": "r2", "device": "A", "kind": "sine", "samples": 100, "tracking_mrad": 4.0, "rate_hz": 90.0, "split": "held_out"},
    {"run": "r3", "device": "A", "kind": "chirp", "samples": 100, "tracking_mrad": 6.0, "rate_hz": 80.0, "split": "held_out"},
    {"run": "r4", "device": "B", "kind": "sine", "samples": 100, "tracking_mrad": 1.0, "rate_hz": 100.0, "split": "held_out"},
]


def model_error(run, device, title, value):
    return {"run": run, "device": device, "subject": f"rig/{device}", "diagnostic": "stock.model_error", "title": title, "value": value,
            "unit": "mrad"}


DIAGNOSTICS = [model_error("r1", "A", "twin of record vs real", 3.0), model_error("r2", "A", "twin of record vs real", 5.0),
               model_error("r3", "A", "twin of record vs real", 9.0), model_error("r2", "A", "refit R1 vs real", 2.0),
               model_error("r4", "B", "twin of record vs real", 1.0)]


def points(run, device, qs):
    return [{"run": run, "device": device, "q_deg": q, "qd_deg_s": qd, "qdd_deg_s2": qdd, "tau_nm": tau} for q, qd, qdd, tau in qs]


COVERAGE = (points("r1", "A", [(10.0, 5.0, 0.0, 0.1), (20.0, -5.0, 2.0, 0.2), (-30.0, 20.0, -10.0, -0.3)])
            + points("r2", "A", [(10.0, 5.0, 0.0, 0.1), (40.0, 30.0, 20.0, 0.5)])
            + points("r3", "A", [(-50.0, -40.0, -30.0, -0.5), (500.0, 0.0, 0.0, 0.0)])   # 500 deg is outside the range: dropped, counted
            + points("r4", "B", [(1.0, 1.0, 1.0, 0.0)]))


@pytest.fixture()
def tables():
    return sel.Tables(nodes=NODES, runs=RUNS, run_diagnostics=DIAGNOSTICS, coverage_points=COVERAGE, floors={"A": 2.0, "B": 1.0},
                      descriptions={"A": DESC_A})


def node(result, node_id):
    return next(n for n in result["nodes"] if n["node"] == node_id)


def metric(n, metric_id, model=None):
    return next(m for m in n["metrics"] if m["metric"] == metric_id and m.get("model") == model)


def card_points(run_ids, description):
    """The fixture's points as the servo card's actuator_coverage reads them: q relative to the joint's origin, every angle in rad."""
    out = []
    for p in COVERAGE:
        if p["run"] in run_ids and p["device"] == "A":
            out.append({"q": math.radians(p["q_deg"]) - description["origin_rad"], "qd": math.radians(p["qd_deg_s"]),
                        "qdd": math.radians(p["qdd_deg_s2"]), "load torque": p["tau_nm"]})
    return out


def test_metrics_over_a_selection(tables):
    out = sel.compute(["r1", "r2", "r3"], tables, name="A, all")
    assert (out["name"], out["runs"], out["unknown_runs"]) == ("A, all", 3, [])
    a = node(out, "rig/a")
    tracking = metric(a, "servo.tracking_rms")
    assert (tracking["value"], tracking["low"], tracking["high"], tracking["n"], tracking["aggregate"]) == (4.0, 2.0, 6.0, 3, "median")
    assert tracking["pinned"] is True and tracking["unit"] == "mrad"
    twin = metric(a, "servo.twin_fidelity", "twin of record")
    assert twin["value"] == pytest.approx(2.5) and twin["n"] == 3 and twin["unit"] == "× floor"   # median of 3/2, 5/2, 9/2
    refit = metric(a, "servo.twin_fidelity", "refit R1")
    assert refit["value"] == pytest.approx(1.0) and refit["n"] == 1
    assert metric(a, "servo.stop_error")["value"] is None and metric(a, "servo.stop_error")["why"]
    driver = node(out, "rig/a/driver")
    assert metric(driver, "driver.loop_rate")["value"] == 90.0
    assert not any(n["node"] == "rig/b" for n in out["nodes"]), "a node no selected run touches is not in the result"


def test_diagnostics_and_gates_over_a_selection(tables):
    a = node(sel.compute(["r1", "r2", "r3"], tables), "rig/a")
    rows = {(d["diagnostic"], d.get("model")): d for d in a["diagnostics"]}
    assert rows[("servo.twin_fidelity.dx", "twin of record")]["level"] == "warning"      # 2.5 > 2.0
    assert rows[("servo.twin_fidelity.dx", "refit R1")]["level"] == "ok"
    assert rows[("servo.twin_fidelity.dx", "twin of record")]["rank"] == 1
    assert rows[("servo.twin_fidelity.dx", "twin of record")]["subject"] == "rig/a"
    assert rows[("servo.twin_fidelity.dx", "twin of record")]["runs"] == 3
    gates = {(g["gate"], g.get("model")): g for g in a["gates"]}
    assert gates[("servo.twin_fidelity.gate", "twin of record")]["verdict"] == "fail"    # T2: <= 1.5
    assert gates[("servo.twin_fidelity.gate", "refit R1")]["verdict"] == "pass"
    assert gates[("servo.stop_error.gate", None)]["verdict"] == "not_run"
    driver = node(sel.compute(["r1", "r2", "r3"], tables), "rig/a/driver")
    loop = next(d for d in driver["diagnostics"] if d["diagnostic"] == "driver.loop_rate.dx")
    assert loop["level"] == "unknown" and loop["value"] == 90.0   # its limit is per unit and no unit sets one: never a guess


def test_one_run_is_a_selection_of_one(tables):
    a = node(sel.compute(["r2"], tables), "rig/a")
    assert metric(a, "servo.tracking_rms")["value"] == 4.0
    assert metric(a, "servo.twin_fidelity", "twin of record")["value"] == pytest.approx(2.5)
    assert metric(a, "servo.twin_fidelity", "refit R1")["value"] == pytest.approx(1.0)
    rows = {(d["diagnostic"], d.get("model")): d for d in a["diagnostics"]}
    assert rows[("servo.twin_fidelity.dx", "twin of record")]["level"] == "warning"


def test_order_does_not_matter_and_unknown_ids_are_reported(tables):
    one, two = sel.compute(["r1", "r2"], tables), sel.compute(["r2", "r1", "r2"], tables)
    assert one == two
    out = sel.compute(["r1", "nope"], tables)
    assert out["unknown_runs"] == ["nope"] and out["runs"] == 1
    empty = sel.compute([], tables)
    assert empty["runs"] == 0 and empty["nodes"] == []


def test_coverage_is_the_cards_own_function_over_the_selected_points(tables):
    for ids in (["r1"], ["r1", "r2"], ["r1", "r2", "r3"]):
        a = node(sel.compute(ids, tables), "rig/a")
        want = cov.actuator_coverage(card_points(ids, DESC_A), DESC_A)
        got = a["coverage"]
        assert (got["pct"], got["visited"], got["reachable"], got["samples"], got["outside"]) == (want.pct, want.visited, want.reachable,
                                                                                                 want.samples, want.outside), ids
        assert got["gate_pct"] == 40.0 and got["verdict"] == ("pass" if want.pct >= 40.0 else "fail")
    grow = [node(sel.compute(ids, tables), "rig/a")["coverage"]["visited"] for ids in (["r1"], ["r1", "r2"], ["r1", "r2", "r3"])]
    assert grow == sorted(grow) and grow[0] < grow[-1]
    b = node(sel.compute(["r4"], tables), "rig/b")
    assert b["coverage"]["pct"] is None and "description" in b["coverage"]["why"]


def test_the_browser_rule_gives_the_same_coverage(tables):
    """The live rule (CONTRACT, "Domain model v3"): count the distinct reachable cells of the run x cell table's rows whose run is
    selected, per device, over the device's reachable cells. Same number as the card's function."""
    cells = sel.coverage_cells(tables)
    assert {"run", "device", "cell", "reachable", "n"} <= set(cells["rows"][0])
    reachable = cells["reachable_cells"]
    for ids in (["r1"], ["r2"], ["r1", "r2", "r3"]):
        live = sel.coverage_from_cells(cells["rows"], ids, reachable)
        assert live["A"] == node(sel.compute(ids, tables), "rig/a")["coverage"]["pct"], ids


def test_presets_name_their_run_ids(tables):
    presets = sel.presets(RUNS)
    assert presets["all"] == ["r1", "r2", "r3", "r4"]
    assert presets["split: held_out"] == ["r2", "r3", "r4"]
    assert presets["split: train"] == ["r1"]


# --- on the rack's own data (skipped where the app's data is not built) ------------------------------------------------------------

DATA = Path("/home/bam/sim2real/app/data")


@pytest.mark.skipif(not (DATA / "one-dof-test-rack" / "runs.json").is_file(), reason="the app's data is not built (tools/build_app.py)")
def test_on_the_rack_a_selection_agrees_with_the_rows_it_reads():
    tables = sel.load_tables(DATA, "one-dof-test-rack")
    runs = json.loads((DATA / "one-dof-test-rack" / "runs.json").read_text())["rows"]
    held = [r for r in runs if r["device"] == "CAN 11" and r.get("split") == "held_out" and r.get("tracking_mrad") is not None]
    assert held, "CAN 11 has held-out runs"
    ids = [r["run"] for r in held]
    out = sel.compute(ids, tables)
    station = next(n for n in out["nodes"] if n["device"] == "CAN 11" and n["entity_type"] == "integrated_servo")
    assert metric(station, "servo.tracking_rms")["value"] == pytest.approx(statistics.median(r["tracking_mrad"] for r in held))
    c = station["coverage"]
    assert c["pct"] is not None and 0.0 < c["pct"] <= 100.0 and c["reachable"] > 0
    cells = sel.coverage_cells(tables)
    assert sel.coverage_from_cells(cells["rows"], ids, cells["reachable_cells"])["CAN 11"] == c["pct"]


def test_a_value_that_is_not_a_number_is_skipped_never_propagated(tables):
    """A producer that writes NaN (Python's json allows it) must not turn a median into NaN, nor stop the site build's JSON (no NaN in JSON)."""
    runs = RUNS + [{"run": "r5", "device": "A", "kind": "sine", "samples": 100, "tracking_mrad": float("nan"), "rate_hz": float("inf"),
                    "split": "held_out"}]
    t = sel.Tables(nodes=NODES, runs=runs, run_diagnostics=DIAGNOSTICS, coverage_points=COVERAGE, floors={"A": 2.0}, descriptions={"A": DESC_A})
    a = node(sel.compute(["r1", "r2", "r3", "r5"], t), "rig/a")
    assert metric(a, "servo.tracking_rms")["value"] == 4.0 and metric(a, "servo.tracking_rms")["n"] == 3
    json.dumps(sel.compute(["r1", "r2", "r3", "r5"], t), allow_nan=False)


# --- the station's T1 floor is T1's row, never T10's or T11's (2026-11-07, found by the run page lane) ---------------------------------
# load_tables matched gates.json rows with str(gate).startswith("T1"), so "T10 live re-identification" and "T11 provenance" matched too and
# the last row won: 7 of the rack's 8 stations divided every model error by T10's value (CAN 12: 1.992 for its T1 floor 0.7459 mrad, so
# twin D's 2.575 mrad read 1.29x floor, ok, where it is 3.45x). Only CAN 11 read right, its T10 value being null.

def _gates_folder(tmp: Path, rows: list[dict]) -> Path:
    folder = tmp / "rig"
    folder.mkdir()
    for name, table in (("gates.json", rows), ("devices.json", [{"device": "A"}]), ("runs.json", []), ("run_gates.json", []),
                        ("coverage.json", [])):
        (folder / name).write_text(json.dumps({"rows": table}))
    return tmp


def test_the_t1_floor_is_t1s_row_never_t10s_or_t11s(tmp_path):
    data = _gates_folder(tmp_path, [{"device": "A", "gate": "T1 floor", "value": 0.7459},
                                    {"device": "A", "gate": "T10 live re-identification", "value": 1.992},
                                    {"device": "A", "gate": "T11 provenance", "value": None, "value_text": "12/24"}])
    tables = sel.load_tables(data, "rig", schedules=tmp_path / "no-schedules", nodes=[])
    assert tables.floors == {"A": pytest.approx(0.7459)}


@pytest.mark.skipif(not (DATA / "one-dof-test-rack" / "gates.json").is_file(), reason="the app's data is not built (tools/build_app.py)")
def test_on_the_rack_every_station_divides_by_its_own_t1_row():
    """CAN 12's T10 holds a number (its live re-identification), so a prefix match on "T1" reads it: the floor must be the T1 row's."""
    tables = sel.load_tables(DATA, "one-dof-test-rack")
    gates = json.loads((DATA / "one-dof-test-rack" / "gates.json").read_text())["rows"]
    t1 = {g["device"]: g["value"] for g in gates if g["gate"].split()[0] == "T1" and isinstance(g.get("value"), (int, float))}
    t10 = {g["device"]: g["value"] for g in gates if g["gate"].split()[0] == "T10" and isinstance(g.get("value"), (int, float))}
    assert "CAN 12" in t10 and t10["CAN 12"] != t1["CAN 12"], "the case that tells T1 from T10 is on the rack (CAN 12)"
    assert tables.floors == pytest.approx(t1)


# --- model-independent metrics per run (the run_metrics producer) and per-unit limits (2026-11-07, the metrics lane) -------------------
# Zach (2026-11-06): diagnostics "are basically like metrics + gate that reports warning or error ... we can calculate these metrics on a per
# run basis ... but also accross all the runs". Before this, no producer wrote a model-independent diagnostic per run, so the run page's dots
# read unknown: the stop error had no per-run value, and the board's loop rate a value with no limit (its limit is per unit). tools/
# run_metrics.py now writes <dep>/run_metrics.json (RobotDx's catalog entries servo.stop_error and driver.saturation per run), and a physical
# deployment's record sets each unit's limits (type_cards/deployments/<id>.py `limits`), which instances puts on its nodes.

RUN_METRICS = [
    {"run": "r1", "device": "A", "metric": "servo.stop_error", "value": 2.0, "unit": "mrad", "n": 4},
    {"run": "r2", "device": "A", "metric": "servo.stop_error", "value": 5.0, "unit": "mrad", "n": 6},
    {"run": "r3", "device": "A", "metric": "servo.stop_error", "value": None, "unit": "mrad", "n": 0, "why": "no dwell of 0.25 s or more followed by motion"},
    {"run": "r1", "device": "A", "metric": "driver.saturation", "value": 0.0, "unit": "%", "n": 100},
    {"run": "r2", "device": "A", "metric": "driver.saturation", "value": 3.0, "unit": "%", "n": 100},
    {"run": "r3", "device": "A", "metric": "driver.saturation", "value": 1.0, "unit": "%", "n": 100},
    {"run": "r4", "device": "B", "metric": "servo.stop_error", "value": 9.0, "unit": "mrad", "n": 2},
]
LIMITS = {"rig/a": {"servo.stop_error.dx": {"warn": 3.6, "target": 3.6, "source": "the fixture"}},
          "rig/a/driver": {"driver.loop_rate.dx": {"warn": 90.0, "source": "the fixture"}}}


def with_limits(nodes=NODES, limits=LIMITS):
    return [{**n, "limits": limits.get(n["id"], {})} for n in nodes]


@pytest.fixture()
def unit_tables():
    return sel.Tables(nodes=with_limits(), runs=RUNS, run_diagnostics=DIAGNOSTICS, coverage_points=COVERAGE, floors={"A": 2.0, "B": 1.0},
                      descriptions={"A": DESC_A}, run_metrics=RUN_METRICS)


def test_run_metrics_feed_the_stop_error_and_the_saturation(unit_tables):
    out = sel.compute(["r1", "r2", "r3"], unit_tables)
    a = node(out, "rig/a")
    stop = metric(a, "servo.stop_error")
    assert (stop["value"], stop["low"], stop["high"], stop["n"]) == (3.5, 2.0, 5.0, 2)   # median of 2 and 5; r3 has no stop
    assert stop["source"].startswith("run_metrics.json") and stop["why"] == ""
    sat = metric(node(out, "rig/a/driver"), "driver.saturation")
    assert (sat["value"], sat["n"]) == (1.0, 3)
    none = metric(node(sel.compute(["r3"], unit_tables), "rig/a"), "servo.stop_error")
    assert none["value"] is None and "dwell" in none["why"], "a run with no stop says why, in the producer's words"


def test_a_units_limits_give_the_diagnostics_their_levels(unit_tables):
    a = node(sel.compute(["r1", "r2", "r3"], unit_tables), "rig/a")
    stop = next(d for d in a["diagnostics"] if d["diagnostic"] == "servo.stop_error.dx")
    assert (stop["level"], stop["value"], stop["warn_hi"]) == ("ok", 3.5, 3.6)
    assert next(d for d in node(sel.compute(["r2"], unit_tables), "rig/a")["diagnostics"] if d["diagnostic"] == "servo.stop_error.dx")["level"] == "warning"
    driver = node(sel.compute(["r1", "r2", "r3"], unit_tables), "rig/a/driver")
    loop = next(d for d in driver["diagnostics"] if d["diagnostic"] == "driver.loop_rate.dx")
    assert (loop["level"], loop["value"], loop["warn_lo"]) == ("ok", 90.0, 90.0)              # >= the expected rate - 10 %: its fine side
    slow = node(sel.compute(["r3"], unit_tables), "rig/a/driver")
    assert next(d for d in slow["diagnostics"] if d["diagnostic"] == "driver.loop_rate.dx")["level"] == "warning"   # 80 Hz
    sat = next(d for d in driver["diagnostics"] if d["diagnostic"] == "driver.saturation.dx")
    assert sat["level"] == "ok" and sat["value"] == 1.0                                         # <= 2 %, the card's own limit
    b = node(sel.compute(["r4"], unit_tables), "rig/b")
    assert next(d for d in b["diagnostics"] if d["diagnostic"] == "servo.stop_error.dx")["level"] == "unknown", \
        "a unit with no limit set stays unknown, whatever its value: never a guess"


def test_a_units_target_judges_its_gate(unit_tables):
    gates = {g["gate"]: g for g in node(sel.compute(["r1", "r2", "r3"], unit_tables), "rig/a")["gates"] if g.get("model") is None}
    assert gates["servo.stop_error.gate"]["verdict"] == "pass" and gates["servo.stop_error.gate"]["value"] == 3.5
    worse = {g["gate"]: g for g in node(sel.compute(["r2"], unit_tables), "rig/a")["gates"] if g.get("model") is None}
    assert worse["servo.stop_error.gate"]["verdict"] == "fail"


def test_the_metric_values_table_is_every_per_run_value(unit_tables):
    """The browser's input for metrics (CONTRACT, "Domain model v3"): one row per (run, node, metric, model) with a finite value, exactly the
    values compute() aggregates; its schema names the fields."""
    doc = sel.metric_values(unit_tables)
    rows = doc["rows"]
    assert {"run", "node", "device", "metric", "model", "value"} <= set(rows[0])
    key = {(r["run"], r["node"], r["metric"], r["model"]) for r in rows}
    assert ("r1", "rig/a", "servo.tracking_rms", None) in key and ("r3", "rig/a/driver", "driver.loop_rate", None) in key
    assert ("r2", "rig/a", "servo.twin_fidelity", "refit R1") in key and ("r3", "rig/a", "servo.stop_error", None) not in key
    assert next(r for r in rows if (r["run"], r["metric"], r["model"]) == ("r2", "servo.twin_fidelity", "twin of record"))["value"] == pytest.approx(2.5)
    assert all(math.isfinite(r["value"]) for r in rows)
    assert {f["name"] for f in doc["schema"]["fields"]} >= {"run", "node", "metric", "model", "value"}


def test_the_browser_rule_gives_the_same_metrics(unit_tables):
    """Per (node, metric, model): the metric's aggregate (data-ui's summary of that name) over the selected runs' rows of the metric
    values table, with min, max and the count beside it: compute()'s numbers, for every subset of the fixture's runs."""
    import itertools  # noqa: PLC0415

    rows = sel.metric_values(unit_tables)["rows"]
    ids = ["r1", "r2", "r3", "r4"]
    for k in range(1, len(ids) + 1):
        for pick in itertools.combinations(ids, k):
            live = sel.metrics_from_values(rows, pick)
            out = sel.compute(pick, unit_tables)
            want = {(n["node"], m["metric"], m["model"]): (m["value"], m["low"], m["high"], m["n"]) for n in out["nodes"] for m in n["metrics"]
                    if m["value"] is not None}
            assert {k2: (v["value"], v["low"], v["high"], v["n"]) for k2, v in live.items()} == want, pick


def test_the_coverage_grid_lists_each_devices_reachable_cells(unit_tables):
    """coverage_cells' grid (additive): each device's axes (name, unit, edges) and its reachable cells, so a page can draw where a joint can
    go and where the selection went (the heatmap) from the same cells the browser counts."""
    cells = sel.coverage_cells(unit_tables)
    grid = cells["grid"]["A"]
    assert [a["name"] for a in grid["axes"]] == ["q", "qd", "qdd"] and all(len(a["edges"]) >= 2 for a in grid["axes"])
    assert len(grid["reachable"]) == cells["reachable_cells"]["A"]
    reach = set(grid["reachable"])
    assert all(r["reachable"] == (r["cell"] in reach) for r in cells["rows"] if r["device"] == "A")
