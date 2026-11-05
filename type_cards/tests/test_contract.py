"""The type cards' v2 contract (type_cards/CONTRACT.md), written before it (2026-11-05).

    uv run --no-project --with pytest pytest -q /home/bam/sim2real/type_cards/tests

What it holds, independent of the cards' content (tests/test_ladders.py holds the content):
- every v1 name is still there and v1 constructors still work (positional Parameter, Card without the new fields): additive only;
- the v2 names, constants and defaults the contract promises (rungs, references, wear, learned rungs, diagnostics and gates,
  test types, calibration packages, the export);
- the behaviour of each function on numbers worked by hand: rung parameter counts (an MLP's weights: Hwangbo 2019's actuator net is
  2,369), wear laws and their inversion, the usage-remaining forecast, the drift check (warning text, settable threshold), Zach's
  selection rule (the lowest rung that reaches the floor on held-out data; learned rungs judged only inside their covered cells),
  gates versus observed metrics, the coverage gate, random plans over the full space;
- the servo coverage function is byte for byte what main 61a9de7 computes on CAN 11 (66.15 %), digest pinned before any change.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from type_cards import coverage as cov  # noqa: E402
from type_cards import registry as reg  # noqa: E402

SCHEDULE = Path("/archive/datasets/bam_rig/schedules/one-dof-test-rack/can11/schedule.json")

V1_NAMES = ("Metric", "Parameter", "Model", "Axis", "Coverage", "View", "Observability", "Member", "Floor", "Step", "Tool", "Card",
            "STEPS", "CARDS", "ORDER", "gaps", "P", "proc", "REPO", "ROBOTDX_COMMIT", "data_ui_commit", "robotdx_catalog")
V2_TYPES = ("Reference", "Wear", "Architecture", "CoverageNeed", "Rung", "RungScore", "Limit", "Forecast", "Diagnostic", "Gate",
            "TestType", "CodeHome", "CalibrationPackage", "DriftResult")
V2_FUNCTIONS = ("rungs", "rung", "current_rung", "added", "select_rung", "drift_diagnostic", "check_drift", "metric_status", "gate_status",
                "coverage_gate", "tests_for", "packages_for", "card_for", "export", "wear_value", "wear_usage_at", "usage_remaining",
                "mlp_weights", "coverage_flag", "drift_check")
V1_FIELDS = {
    "Parameter": ["name", "unit", "nominal", "source", "identified_by", "observable", "note"],
    "Axis": ["name", "unit", "binning"],
    "Coverage": ["axes", "rule", "measure", "robotdx", "plan_source"],
    "Card": ["id", "title", "group", "zach", "robotdx_part", "robotdx_gap", "inputs", "outputs", "metrics", "floor", "model", "coverage", "view",
             "observability", "procedure", "members", "error_budget"],
    "Metric": ["id", "family", "title", "defined_on", "unit", "robotdx", "proposed", "normalised", "gate", "today"],
}
HWANGBO = reg.Architecture("MLP", ("position error", "velocity"), "torque", history=3, history_dt_s=0.01, hidden=(32, 32, 32), activation="softsign")


def names(cls) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


# --- additive only -----------------------------------------------------------------------------------------------------------

def test_every_v1_name_is_still_there():
    missing = [n for n in V1_NAMES if not hasattr(reg, n)]
    assert not missing, missing


def test_v1_fields_keep_their_order_and_new_ones_default():
    for cls, fields in V1_FIELDS.items():
        assert names(getattr(reg, cls))[:len(fields)] == fields, cls
    p = reg.P("x", "m", 1.0, "datasheet", "a sweep", "yes", "a note")
    assert (p.note, p.wear, p.role) == ("a note", None, "model")
    axis = reg.Axis("q", "rad", "12 cells")
    assert (axis.bin_size, axis.marginal) == (None, False)
    servo = reg.CARDS["servo"]
    coverage = reg.Coverage(servo.coverage.axes, "a rule", servo.coverage.measure)
    assert coverage.gate_pct is None
    bare = reg.Card(**{f: getattr(servo, f) for f in V1_FIELDS["Card"]})
    assert (bare.rungs, bare.diagnostics, bare.gates, bare.tests) == ((), (), (), ())


def test_v2_names_and_constants():
    missing = [n for n in V2_TYPES + V2_FUNCTIONS if not hasattr(reg, n)]
    assert not missing, missing
    assert reg.SCHEMA == "sim2real.type_cards/2"
    assert reg.KINDS == ("physics", "residual", "learned")
    assert set(reg.SETTINGS) == {"bench", "deployed"}
    assert set(reg.WEAR_LAWS) == {"linear", "sqrt", "archard"}
    assert set(reg.ROLES) == {"model", "driver", "assembly", "config"}
    assert reg.DRIFT_MESSAGE == "model drift detected — recalibration required"
    assert reg.OUT_OF_COVERAGE == "out of coverage"
    assert reg.TWINNED_LIMIT == 1.5 and 1.0 < reg.DRIFT_THRESHOLD < reg.TWINNED_LIMIT
    assert isinstance(reg.CALIBRATION_PACKAGES, tuple)
    assert reg.Rung is reg.schema.Rung  # one class, re-exported: the registry is the one import


# --- rungs ------------------------------------------------------------------------------------------------------------------

def test_an_mlps_size_is_its_weight_count():
    assert reg.mlp_weights(6, (32, 32, 32), 1) == 6 * 32 + 32 + 2 * (32 * 32 + 32) + 32 + 1 == 2369
    assert HWANGBO.n_inputs == 6 and HWANGBO.weights == 2369
    assert reg.Architecture("GRU", ("e", "v"), "torque", history=30, n_weights=3201).weights == 3201


def test_a_rungs_count_is_named_parameters_plus_weights():
    params = tuple(reg.P(n, "1", None, "unknown", "a sweep", "yes") for n in ("a", "b", "c"))
    physics = reg.Rung("M2", "three terms", params, ())
    learned = reg.Rung("M7", "actuator net", (), (), kind="learned", architecture=HWANGBO, needs=reg.CoverageNeed(95, 200, extrapolates=False))
    residual = reg.Rung("M6", "residual", params[:2], (), kind="residual", base="M2",
                        architecture=reg.Architecture("MLP", ("e", "v", "tau"), "residual torque", history=3, hidden=(32, 32)))
    assert (physics.n_parameters, physics.n_named, physics.parameter_names) == (3, 3, ("a", "b", "c"))
    assert learned.n_parameters == 2369 and learned.n_named == 0
    assert residual.n_parameters == 2 + reg.mlp_weights(9, (32, 32), 1)
    worn = dataclasses.replace(params[0], wear=reg.Wear("deployment hours", "h", "linear", "a_rate"))
    assert reg.Rung("M2.wear", "worn", (worn, *params[1:]), ()).wear_parameters == (worn,)


def test_limits():
    assert reg.Limit("<=", 1.5, "× floor").ok(1.5) and not reg.Limit("<=", 1.5, "× floor").ok(1.51)
    assert reg.Limit(">=", 40, "%").ok(66.15) and not reg.Limit(">=", 40, "%").ok(39.9)
    per_unit = reg.Limit("<=", None, "mrad", note="STOP_ALLOCATION_MRAD per station")
    assert per_unit.ok(2.0, value=3.6)
    with pytest.raises(ValueError):
        per_unit.ok(2.0)


# --- wear and the forecast -----------------------------------------------------------------------------------------------------

def test_wear_laws_and_their_inversion():
    assert reg.wear_value(0.001, 2e-6, 100.0, "linear") == pytest.approx(0.0012)
    assert reg.wear_value(1.0, 0.5, 16.0, "sqrt") == pytest.approx(3.0)
    assert reg.wear_value(0.001, 1e-7, 500.0, "archard") == pytest.approx(0.00105)  # usage = load × distance
    assert reg.wear_usage_at(1.0, 0.5, 3.0, "sqrt") == pytest.approx(16.0)
    assert reg.wear_usage_at(0.001, 2e-6, 0.002, "linear") == pytest.approx(500.0)
    assert reg.wear_usage_at(0.001, 0.0, 0.002, "linear") is None
    assert reg.wear_usage_at(0.002, 1e-6, 0.001, "linear") is None
    with pytest.raises(ValueError):
        reg.wear_value(1, 1, 1, "exponential")


def test_usage_remaining_solves_the_law_for_the_threshold():
    linear = [(0, 1.0), (100, 1.1), (200, 1.2)]
    assert reg.usage_remaining(linear, 1.25, "linear") == pytest.approx(50.0)
    sqrt = [(0, 1.0), (25, 1.25), (100, 1.5)]
    assert reg.usage_remaining(sqrt, 1.75, "sqrt") == pytest.approx(125.0)
    assert reg.usage_remaining([(0, 1.0), (100, 1.3)], 1.25, "linear") == 0.0       # past it already
    assert reg.usage_remaining([(0, 1.2), (100, 1.1)], 1.25, "linear") is None      # improving: never crosses
    assert reg.usage_remaining([(50, 1.1)], 1.25, "linear") is None                 # one point fits no line
    assert reg.usage_remaining([(0, 60.0), (10, 55.0)], 40.0, "linear", op=">=") == pytest.approx(30.0)


def test_the_drift_check_warns_in_zachs_words_with_a_settable_threshold_and_a_forecast():
    dx = reg.Diagnostic("t.drift", "t.twin_fidelity", reg.Limit("<=", 1.25, "× calibrated"), kind="drift", message=reg.DRIFT_MESSAGE,
                        baseline="the held-out fidelity at calibration", forecast=reg.Forecast("deployment hours", "h", "linear", ("backlash_rad",)))
    ok = reg.drift_check(dx, live=1.2, calibrated=1.0)
    assert (ok.status, ok.message, ok.ratio) == ("ok", "", pytest.approx(1.2))
    bad = reg.drift_check(dx, live=1.4, calibrated=1.0)
    assert (bad.status, bad.message) == ("warning", "model drift detected — recalibration required")
    assert reg.drift_check(dx, live=1.4, calibrated=1.0, threshold=1.5).status == "ok"
    fc = reg.drift_check(dx, live=1.2, calibrated=1.0, history=[(0, 1.0), (100, 1.1), (200, 1.2)])
    assert fc.remaining == pytest.approx(50.0) and fc.unit == "h"
    with pytest.raises(ValueError):
        reg.drift_check(dataclasses.replace(dx, kind="threshold"), 1.0, 1.0)


# --- the selection rule -----------------------------------------------------------------------------------------------------

def ladder():
    learned_need = reg.CoverageNeed(95, 200, extrapolates=False)
    return (reg.Rung("M0", "ideal", (), ()), reg.Rung("M2", "friction", (), ()),
            reg.Rung("M6", "residual", (), (), kind="residual", base="M2", needs=learned_need),
            reg.Rung("M7", "net", (), (), kind="learned", architecture=HWANGBO, needs=learned_need))


def test_selection_picks_the_lowest_rung_that_reaches_the_floor():
    rungs = ladder()
    S = reg.RungScore
    assert reg.select_rung(rungs, {"M0": 3.0, "M2": 1.4, "M6": S(1.1), "M7": S(1.0)}).key == "M2"
    assert reg.select_rung(rungs, {"M0": 3.0, "M2": 2.0, "M6": S(1.2, in_coverage=False), "M7": S(1.3)}).key == "M7"
    assert reg.select_rung(rungs, {"M0": 3.0, "M2": 2.0}) is None
    assert reg.select_rung(rungs, {"M0": 3.0, "M2": 2.0}, limit=2.0).key == "M2"
    with pytest.raises(ValueError):  # a learned rung's bare number may be an out-of-coverage score: refused
        reg.select_rung(rungs, {"M0": 3.0, "M6": 1.1})


def test_learned_rungs_are_flagged_outside_their_covered_cells():
    m0, _m2, m6, _m7 = ladder()
    trained = {(0, 1, 2), (3, 4, 5)}
    assert reg.coverage_flag(m0, (9, 9, 9), trained) is None
    assert reg.coverage_flag(m6, (0, 1, 2), trained) is None
    assert reg.coverage_flag(m6, (9, 9, 9), trained) == reg.OUT_OF_COVERAGE == "out of coverage"


# --- diagnostics, gates, observed metrics ---------------------------------------------------------------------------------------

def test_a_gate_is_a_diagnostic_with_a_target_and_the_rest_is_observed():
    servo = reg.CARDS["servo"]
    dx = reg.Diagnostic("servo.twin_fidelity.dx", "servo.twin_fidelity", reg.Limit("<=", 2.0, "× floor"))
    gate = reg.Gate("servo.twin_fidelity.gate", dx.id, reg.Limit("<=", 1.5, "× floor"), acceptance="T2")
    card = dataclasses.replace(servo, diagnostics=(dx,), gates=(gate,))
    assert reg.metric_status(card, "servo.twin_fidelity") == "gated"
    assert reg.metric_status(card, "servo.tracking_rms") == "observed"
    assert [reg.gate_status(gate, v) for v in (1.2, 1.6, None)] == ["pass", "fail", "not_run"]


def test_the_coverage_gate():
    servo = reg.CARDS["servo"]
    gated = dataclasses.replace(servo, coverage=dataclasses.replace(servo.coverage, gate_pct=40.0))
    ungated = dataclasses.replace(servo, coverage=dataclasses.replace(servo.coverage, gate_pct=None))
    assert reg.coverage_gate(gated, cov.CoverageResult(66.15, 1069, 1616, 77969)) == "pass"
    assert reg.coverage_gate(gated, cov.CoverageResult(30.0, 485, 1616, 100)) == "fail"
    assert reg.coverage_gate(ungated, cov.CoverageResult(66.15, 1069, 1616, 77969)) == "observed"


# --- lookups and the export -------------------------------------------------------------------------------------------------

def test_card_for_maps_a_description_word_to_its_card():
    assert reg.card_for("servo").id == "servo"
    assert reg.card_for("Integrated Servo").id == "servo"
    assert reg.card_for("bldc_driver").id == "driver"
    assert reg.card_for("RGBD Camera").id == "camera_rgbd"
    assert reg.card_for("a teapot") is None


def test_the_export_is_json_and_versioned():
    doc = reg.export()
    text = json.dumps(doc)
    assert doc["schema"] == reg.SCHEMA and json.loads(text) == doc
    assert [c["id"] for c in doc["cards"]] == list(reg.CARDS)
    for key in ("settings", "kinds", "roles", "wear_laws", "drift_message", "twinned_limit", "calibration_packages", "selection_rule"):
        assert key in doc, key
    for card in doc["cards"]:
        for key in ("rungs", "diagnostics", "gates", "tests", "coverage", "metrics", "model"):
            assert key in card, (card["id"], key)
        assert all({"bin_size", "marginal"} <= set(a) for a in card["coverage"]["axes"]), card["id"]
        assert "gate_pct" in card["coverage"] and "measure" not in card["coverage"]


# --- coverage ------------------------------------------------------------------------------------------------------------------

def test_random_plans_sample_the_full_space_and_are_reproducible():
    edges = [[0.0, 1.0, 2.0, 3.0, 4.0], [0.0, 10.0, 20.0], ("levels", "a", "b")]
    pts = cov.random_plan(edges, 2000, seed=7)
    assert pts == cov.random_plan(edges, 2000, seed=7) and pts != cov.random_plan(edges, 2000, seed=8)
    assert len(pts) == 2000 and all(0 <= x <= 4 and 0 <= y <= 20 and z in ("a", "b") for x, y, z in pts)
    assert cov.binned(pts, edges).pct == 100.0 and cov.binned(pts[:3], edges).pct < 20


@pytest.mark.skipif(not SCHEDULE.is_file(), reason="the rack archive is not mounted")
def test_servo_coverage_is_byte_compatible_with_main_on_can11():
    """Digests of (pct, visited, reachable, samples, outside, axes, unplanned, every cell's count) from main 61a9de7's code."""
    sched = json.loads(SCHEDULE.read_text())
    want = {"train": (66.15, "df127fa9724436ffb00095bf373f458bd84db28c0662c9191f0f53f35070ca69"),
            "held_out": (67.2, "e922fc3668b9b19d1e5997df7d19aaa5f4b52edfc20ff7c1144c9579b0d695ce")}
    for split, (pct, digest) in want.items():
        r = cov.servo_coverage(sched, split=split)
        blob = json.dumps({"pct": r.pct, "visited": r.visited, "reachable": r.reachable, "samples": r.samples, "outside": r.outside, "axes": r.axes,
                           "unplanned": list(r.unplanned), "cells": sorted([list(k), v] for k, v in r.cells.items())}, sort_keys=True)
        assert r.pct == pct and hashlib.sha256(blob.encode()).hexdigest() == digest, split
