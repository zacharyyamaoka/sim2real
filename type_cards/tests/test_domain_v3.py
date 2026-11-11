"""Domain model v3 (type_cards/CONTRACT.md, "Domain model v3"), written before type_cards/domain.py (2026-11-07).

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --with pytest pytest -q /home/bam/sim2real/type_cards/tests

Zach, PROJECT - Sim2Real, "Feedback on how it is right now" (2026-11-06): deployments (virtual or physical, tagged, a tree), runs
(raw data, tagged with their config, driven or free response, closed loop), entity TYPES (generic, not instances: "the 6 DOF robot arm
is not a type"), MODELS as one ladder per type in families ("M0.kinematics.X, M0.dynamics.X ... definetily you can use a robot arm
without a dynamics model"), parameters (true / nominal / recovered), routines both ways, metrics with the important ones pinned,
diagnostics (a metric plus a gate that reports warning or error), coverage, reports.

What it holds, type level (tests/test_instances.py holds deployments and runs, tests/test_selection.py the computation,
tests/test_reports.py the frozen reports):
- the vocabularies and record classes the contract names, frozen and keyword-only;
- the entity types are generic (no instance word in an id), every v2 card maps to exactly one, and back;
- every model id is M<k>.<family>.<name>; within a family parameters nest; M6 is the residual and M7 the network on every type;
  the chain has a kinematics family usable with no dynamics model;
- the migration from v2 rung keys loses no parameter and invents none it does not declare; every v2 parameter, metric and
  routine reference resolves in v3;
- routine -> parameters and parameter -> routines are inverses and agree with reg.parameter_routines();
- every type pins its headline performance metric and its twin-fidelity metric, pinned first;
- a diagnostic's level on numbers worked by hand (ok / warning / error / unknown, RobotDx's ranks), and the drift check in the
  parameter's own units (the gap) does not move with the sensor's noise;
- run tags per bam_rack_twin.hardware kind, and the offline scope they give;
- the committed projection type_cards/domain_v3.json is this code's export, byte for byte.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from type_cards import domain as dm  # noqa: E402
from type_cards import registry as reg  # noqa: E402

GENERIC = {"rigid_body_chain", "integrated_servo", "bldc_motor", "gearbox", "foc_controller", "encoder", "camera", "depth_camera",
           "hyperspectral_camera", "conveyor", "gripper"}
INSTANCE_WORDS = ("6dof", "6_dof", "ur5", "arm_6", "d405", "d435", "moteus", "jmc", "gim43", "subassembly")
MODEL_ID = re.compile(r"^M(\d+)\.(kinematics|dynamics|measurement)\.([a-z0-9_]+)$")


# --- the vocabulary and the records --------------------------------------------------------------------------------------------

def test_schema_and_vocabularies():
    assert dm.SCHEMA == "sim2real.domain/3"
    assert list(dm.DEPLOYMENT_KINDS) == ["virtual", "physical"]
    assert list(dm.FAMILIES) == ["kinematics", "dynamics", "measurement"]
    assert list(dm.EXCITATIONS) == ["driven", "free response", "mixed", "unknown"]
    assert set(dm.OFFLINE_SCOPES) == {"any config", "any feedback gains", "its own config", "split", "unknown"}
    assert dm.LEVELS == ("ok", "warning", "error", "unknown")
    # RobotDx's ranks (data-ui STATUS_ORDER): ok 0 < warn 1 < unknown 2 < error 4
    assert dm.LEVEL_RANK == {"ok": 0, "warning": 1, "unknown": 2, "error": 4}
    assert set(dm.AGGREGATES) <= {"median", "mean", "min", "max", "sum", "count"}  # data-ui's summaries: the browser can do the same
    assert {"oracle example", "uses camera"} <= set(dm.TAGS)


RECORDS = {
    "EntityType": ["id", "title", "zach", "group", "covers", "families", "models", "parameters", "metrics", "diagnostics", "gates",
                   "coverage", "dashboard", "members", "legacy_cards", "robotdx_part", "note"],
    "Model": ["id", "type", "k", "family", "name", "title", "kind", "parameters", "adds", "base", "wear", "current", "n_parameters",
              "equation", "references", "architecture", "needs", "robotparts", "implemented", "legacy", "note"],
    "ParameterSpec": ["type", "name", "unit", "family", "introduced_in", "models", "nominal", "source", "identified_by", "observable",
                      "role", "wear", "legacy", "note"],
    "MetricSpec": ["id", "type", "family", "title", "unit", "defined_on", "pinned", "model_dependent", "aggregate", "per_run", "why_not",
                   "robotdx", "normalised", "acceptance", "today", "legacy"],
    "RunSource": ["table", "column", "diagnostic", "per_model", "divide_by", "note"],
    "DiagnosticSpec": ["id", "type", "metric", "title", "warn", "error", "kind", "units", "parameter", "message", "baseline", "robotdx",
                       "note", "legacy"],
    "Dimension": ["name", "unit", "headline", "bin_size", "binning"],
    "CoverageSpec": ["type", "dimensions", "rule", "gate_pct", "reachable", "from_runs", "why_not"],
    "Dashboard": ["template", "panels", "components", "proposed"],
    "RunTags": ["excitation", "closed_loop", "offline_scope", "why"],
    "Estimate": ["mean", "ci95", "interval", "form"],
    "CameraDecl": ["serial", "model", "type", "sees", "source"],
    "PhysicalDeployment": ["id", "tags", "cameras", "note"],
}


@pytest.mark.parametrize("name", sorted(RECORDS))
def test_records_are_frozen_keyword_dataclasses_with_their_fields(name):
    cls = getattr(dm, name)
    assert dataclasses.is_dataclass(cls)
    params = cls.__dataclass_params__
    assert params.frozen, f"{name} is frozen"
    assert all(f.kw_only for f in dataclasses.fields(cls)), f"{name} is keyword-only (Zach's Python ground truth: one keyword per line)"
    assert [f.name for f in dataclasses.fields(cls)][:len(RECORDS[name])] == RECORDS[name]


# --- entity types: generic, every card maps to one ----------------------------------------------------------------------------

def test_the_entity_types_are_generic():
    assert set(dm.TYPES) == GENERIC
    for tid, t in dm.TYPES.items():
        assert t.id == tid
        assert not any(w in tid for w in INSTANCE_WORDS), f"{tid} names an instance"
    assert dm.TYPES["rigid_body_chain"].title == "Rigid Body Chain"
    assert dm.TYPES["integrated_servo"].title == "Integrated Servo"
    assert dm.TYPES["foc_controller"].title == "FOC Controller"


def test_every_v2_card_maps_to_exactly_one_type_and_back():
    assert set(dm.CARD_TYPE) == set(reg.CARDS)
    for card, tid in dm.CARD_TYPE.items():
        assert tid in dm.TYPES
        assert card in dm.TYPES[tid].legacy_cards
    assert sorted(c for t in dm.TYPES.values() for c in t.legacy_cards) == sorted(reg.CARDS)
    # Zach: "the 6 DOF robot arm is not a type ... the same model works for different types of chains"
    assert dm.CARD_TYPE["arm_6dof"] == dm.CARD_TYPE["arm_subassembly"] == "rigid_body_chain"
    assert dm.entity_type("arm_6dof") is dm.TYPES["rigid_body_chain"] is dm.entity_type("rigid_body_chain")


# --- models: ids, families, ladders -------------------------------------------------------------------------------------------

def test_model_ids_name_their_layer_family_and_name():
    for t in dm.TYPES.values():
        ids = [m.id for m in t.models]
        assert len(ids) == len(set(ids)), t.id
        for m in t.models:
            hit = MODEL_ID.match(m.id)
            assert hit, m.id
            assert (int(hit.group(1)), hit.group(2), hit.group(3)) == (m.k, m.family, m.name)
            assert m.type == t.id and m.family in t.families
            assert m.kind in reg.KINDS
            assert dm.model(t.id, m.id) is m
            assert m.key == f"{t.id}/{m.id}"


def test_m6_is_the_residual_and_m7_the_network_on_every_type():
    for t in dm.TYPES.values():
        for m in t.models:
            assert (m.k == 6) == (m.kind == "residual"), m.key
            assert (m.k == 7) == (m.kind == "learned"), m.key
            if m.kind == "residual":
                assert dm.model(t.id, m.base).kind == "physics"
            if m.kind == "learned":
                assert m.parameters == () and m.architecture is not None and m.n_parameters == m.architecture.weights


def test_parameters_nest_within_a_family_and_count():
    for t in dm.TYPES.values():
        names = {p.name for p in t.parameters}
        for fam in t.families:
            physics = [m for m in t.models if m.family == fam and m.kind == "physics" and not m.wear]
            for below, above in zip(physics, physics[1:]):
                assert set(below.parameters) < set(above.parameters), (below.key, above.key)
                assert above.k > below.k
        for i, m in enumerate(t.models):
            assert set(m.parameters) <= names, m.key
            assert all(dm.parameter(t.id, n).family == m.family for n in m.parameters), m.key
            if m.kind == "physics" and not m.wear:
                below = next((x for x in reversed(t.models[:i]) if x.family == m.family and x.kind == "physics" and not x.wear), None)
                assert set(m.adds) == set(m.parameters) - set(below.parameters if below else ()), m.key
                assert m.n_parameters == len(m.parameters)
            elif m.wear:
                worn = dm.model(t.id, m.base)
                assert worn.kind == "physics" and not worn.wear and set(worn.parameters) < set(m.parameters), m.key
                assert set(m.adds) == set(m.parameters) - set(worn.parameters) and m.adds, m.key
                assert any(dm.parameter(t.id, n).wear is not None for n in m.parameters), m.key
            elif m.kind == "residual":
                assert m.parameters == dm.model(t.id, m.base).parameters and m.adds == ()
        for p in t.parameters:
            assert p.introduced_in == next(m.id for m in t.models if p.name in m.parameters), (t.id, p.name)
            assert p.models == tuple(m.id for m in t.models if p.name in m.parameters)


def test_the_chain_has_kinematics_usable_without_dynamics():
    chain = dm.TYPES["rigid_body_chain"]
    assert chain.families == ("kinematics", "dynamics")
    kin = [m for m in chain.models if m.family == "kinematics"]
    assert [m.id for m in kin][:3] == ["M0.kinematics.nominal", "M1.kinematics.zero_offsets", "M2.kinematics.geometric"]
    assert "M0.dynamics.rigid" in [m.id for m in chain.models]
    # a kinematics model never needs a dynamics term: no parameter of a kinematics model is a dynamics parameter
    for m in kin:
        assert all(dm.parameter("rigid_body_chain", n).family == "kinematics" for n in m.parameters)
    # every type's families are a subset, single-family types keep v2's numbering
    assert dm.TYPES["integrated_servo"].families == ("dynamics",)
    assert dm.TYPES["camera"].families == ("measurement",)
    assert dm.TYPES["conveyor"].families == ("kinematics", "dynamics")


# --- the migration from v2 ------------------------------------------------------------------------------------------------------

def test_every_v2_rung_maps_and_loses_no_parameter():
    for card in reg.CARDS.values():
        tid = dm.CARD_TYPE[card.id]
        for rung in card.rungs:
            ids = dm.legacy_models(card.id, rung.key)
            assert ids, (card.id, rung.key)
            mapped = [dm.model(tid, i) for i in ids]
            assert len({m.family for m in mapped}) == len(mapped), f"one model per family: {card.id} {rung.key}"
            held = {n for m in mapped for n in m.parameters}
            translated = {dm.legacy_parameter(card.id, p.name)[1] for p in rung.parameters}
            assert translated <= held, (card.id, rung.key, translated - held)
            extra = held - translated
            assert extra <= set(dm.declared_extra(card.id, rung.key)), (card.id, rung.key, extra)
            assert all((card.id, rung.key) in m.legacy for m in mapped)
            # each mapped model is needed: without it a translated parameter would be lost
            for m in mapped:
                rest = {n for x in mapped if x is not m for n in x.parameters}
                if translated:
                    assert not translated <= rest, (card.id, rung.key, m.id)
                    assert {m.kind} <= {"physics", rung.kind}, (card.id, rung.key, m.id)
            if len(dm.TYPES[tid].families) == 1:
                assert ids[0].split(".")[0] == rung.key.split(".")[0], "a single-family type keeps v2's layer number"


def test_every_v2_parameter_metric_and_routine_reference_resolves():
    for card in reg.CARDS.values():
        tid = dm.CARD_TYPE[card.id]
        for rung in card.rungs:
            for p in rung.parameters:
                t2, name = dm.legacy_parameter(card.id, p.name)
                assert t2 == tid and dm.parameter(tid, name).unit == p.unit, (card.id, p.name)
                assert (card.id, p.name) in dm.parameter(tid, name).legacy
        for m in card.metrics:
            assert dm.metric(tid, dm.legacy_metric(card.id, m.id)) is not None
    for r in reg.ROUTINES:
        for item in r.identifies:
            tid = dm.CARD_TYPE[item.card]
            for p in item.parameters:
                assert dm.legacy_parameter(item.card, p)[1] in {x.name for x in dm.TYPES[tid].parameters}


def test_current_models_are_the_primary_cards_current_rung():
    """Today's model of a type is its primary card's current rung (the first legacy card: the chain's is the arm's), one model per
    family; a second card folded in (the sub-assembly) keeps its own current combination in the map, not in `current`."""
    for t in dm.TYPES.values():
        card = reg.CARDS[t.legacy_cards[0]]
        cur = reg.current_rung(card)
        assert {m.id for m in dm.current_models(t.id)} == set(dm.legacy_models(card.id, cur.key)), t.id


# --- routines, both ways ----------------------------------------------------------------------------------------------------------

def test_routines_both_ways_are_inverses_and_agree_with_v2():
    forward = {r.id: set(dm.routine_parameters(r.id)) for r in reg.ROUTINES}
    back = dm.parameter_routines()
    for tid, params in back.items():
        assert set(params) == {p.name for p in dm.TYPES[tid].parameters}
        for name, ids in params.items():
            for rid in ids:
                assert (tid, name) in {(t, n) for t, _m, n in forward[rid]}
            assert ids == [r.id for r in dm.routines_identifying(tid, name)]
    for rid, triples in forward.items():
        for tid, mid, name in triples:
            assert rid in back[tid][name]
            assert name in dm.model(tid, mid).parameters
    v2 = reg.parameter_routines()
    for card, params in v2.items():
        for name, ids in params.items():
            tid, n3 = dm.legacy_parameter(card, name)
            assert set(ids) <= set(back[tid][n3]), (card, name)


# --- metrics and diagnostics --------------------------------------------------------------------------------------------------------

def test_pinned_metrics_lead_and_cover_the_headline_and_the_twin():
    for t in dm.TYPES.values():
        pinned = [m for m in t.metrics if m.pinned]
        assert pinned, t.id
        assert t.metrics[:len(pinned)] == tuple(pinned), "pinned first"
        assert any(m.family == "performance" for m in pinned), t.id
        assert any(m.family == "fidelity" for m in pinned), t.id
        assert [m.id for m in dm.pinned(t.id)] == [m.id for m in pinned]
        for m in t.metrics:
            assert m.model_dependent == (m.family == "fidelity")
            assert m.aggregate in dm.AGGREGATES
            assert (m.per_run is None) == bool(m.why_not), m.id


def test_metrics_computable_from_runs_today():
    servo = dm.TYPES["integrated_servo"]
    tracking = dm.metric("integrated_servo", "servo.tracking_rms")
    assert tracking.per_run == dm.RunSource(table="runs", column="tracking_mrad", note=tracking.per_run.note)
    fidelity = dm.metric("integrated_servo", "servo.twin_fidelity")
    assert (fidelity.per_run.table, fidelity.per_run.diagnostic, fidelity.per_run.per_model, fidelity.per_run.divide_by) == (
        "run_diagnostics", "stock.model_error", True, "floor")
    assert dm.metric("foc_controller", "driver.loop_rate").per_run.column == "rate_hz"
    assert servo.coverage.from_runs and not dm.TYPES["camera"].coverage.from_runs


def test_diagnostic_levels_on_hand_numbers():
    d = dm.DiagnosticSpec(id="x.dx", type="integrated_servo", metric="x", title="x", warn=reg.Limit("<=", 2.0, "× floor"),
                          error=reg.Limit("<=", 4.0, "× floor"))
    assert dm.level(d, 1.0) == "ok"
    assert dm.level(d, 2.0) == "ok"            # a limit's fine side includes it (Limit.ok: <=)
    assert dm.level(d, 2.5) == "warning"
    assert dm.level(d, 4.5) == "error"
    assert dm.level(d, None) == "unknown"
    per_unit = dm.DiagnosticSpec(id="y.dx", type="integrated_servo", metric="y", title="y", warn=reg.Limit("<=", None, "mrad", "per unit"))
    assert dm.level(per_unit, 3.0) == "unknown"                       # no value for this unit: never a guess
    assert dm.level(per_unit, 3.0, limits={"warn": 3.6}) == "ok"
    assert dm.level(per_unit, 3.7, limits={"warn": 3.6}) == "warning"
    floor = dm.DiagnosticSpec(id="z.dx", type="foc_controller", metric="z", title="z", warn=reg.Limit(">=", 90.0, "Hz"))
    assert dm.level(floor, 95.0) == "ok" and dm.level(floor, 80.0) == "warning"
    row = dm.diagnostic_row(d, 2.5, subject="CAN 11")
    assert (row["level"], row["rank"], row["warn_hi"], row["error_hi"], row["warn_lo"]) == ("warning", 1, 2.0, 4.0, None)


def test_v2_diagnostics_become_warn_or_error_limits():
    for card in reg.CARDS.values():
        tid = dm.CARD_TYPE[card.id]
        for d2 in card.diagnostics:
            d3 = dm.diagnostic(tid, dm.legacy_diagnostic(card.id, d2.id))
            assert (card.id, d2.id) in d3.legacy
            assert d3.metric == dm.legacy_metric(card.id, d2.metric)
            assert d3.units == ("ratio" if d2.kind == "drift" else "metric")
            if d3.id == d2.id:  # carried over as it was (a folded card's duplicate maps onto the primary card's)
                assert (d3.warn, d3.error) == ((d2.threshold, None) if d2.level == "warning" else (None, d2.threshold))
                assert (d3.kind, d3.message) == (d2.kind, d2.message)


def test_the_gap_drift_is_in_the_gap_units_and_does_not_move_with_noise():
    """The calibration-routines lane's finding (decision-calibration-routines-2026-11-07, last bullet): a drift alarm on live fidelity
    ÷ the camera's floor goes deaf as the camera's noise grows. In the gap's own units it does not: the same gaps give the same levels
    whatever the floor."""
    gap = dm.diagnostic("integrated_servo", "servo.gap_drift")
    assert (gap.kind, gap.units, gap.parameter) == ("drift", "parameter", "backlash_rad")
    assert gap.warn.unit == "rad"
    commissioned, allowance = 0.0020, 0.00035
    seen = [dm.parameter_drift(gap, commissioned=commissioned, measured=b, allowance=allowance) for b in (0.0021, 0.00234, 0.00236, 0.0030)]
    assert seen == ["ok", "ok", "warning", "warning"]
    assert dm.parameter_drift(gap, commissioned=commissioned, measured=None, allowance=allowance) == "unknown"
    assert dm.parameter_drift(gap, commissioned=commissioned, measured=0.003, allowance=None) == "unknown"
    # the ratio form: the same gap error over a floor 3x larger reads 3x smaller, and stops alarming
    ratio = dm.diagnostic("integrated_servo", "servo.drift")
    assert dm.level(ratio, 1.4 / 1.0) == "warning" and dm.level(ratio, 1.4 / 3.0) == "ok"


# --- run tags -----------------------------------------------------------------------------------------------------------------------

RACK_KINDS = {
    "waypoints": ("driven", True), "sine": ("driven", True), "samples": ("driven", True), "chirp": ("driven", True),
    "gravity": ("driven", True), "friction": ("driven", True), "tape": ("driven", True), "staircase": ("driven", True),
    "hardstop": ("driven", True), "impact": ("driven", True), "swing": ("mixed", True), "thermal": ("mixed", False),
}


@pytest.mark.parametrize("kind", sorted(RACK_KINDS))
def test_run_tags_per_rack_kind(kind):
    tags = dm.run_tags(kind)
    assert (tags.excitation, tags.closed_loop) == RACK_KINDS[kind]
    assert tags.why
    assert tags.offline_scope == dm.offline_scope(tags.excitation, tags.closed_loop)


def test_offline_scope_follows_zachs_caveat():
    """Zach: "You cannot do offline evaluation of online robot tracking performance ... (but you can do it of models.) ... if you have
    feedback control running ... and you change it ... you may get different response ... action free response is helpful"."""
    assert dm.offline_scope("free response", False) == "any config"
    assert dm.offline_scope("free response", None) == "any config"
    assert dm.offline_scope("driven", False) == "any feedback gains"
    assert dm.offline_scope("driven", True) == "its own config"
    assert dm.offline_scope("mixed", True) == "split"
    assert dm.offline_scope("unknown", None) == "unknown"
    assert dm.run_tags("a kind nobody wrote") == dm.RunTags(excitation="unknown", closed_loop=None, offline_scope="unknown",
                                                            why=dm.run_tags("a kind nobody wrote").why)
    assert dm.run_tags(None).excitation == "unknown"


# --- coverage and dashboards -------------------------------------------------------------------------------------------------------

def test_coverage_dimensions_come_from_the_cards():
    for card in reg.CARDS.values():
        t = dm.entity_type(card.id)
        names = [d.name for d in t.coverage.dimensions]
        for axis in card.coverage.axes:
            assert axis.name in names
            d = next(x for x in t.coverage.dimensions if x.name == axis.name)
            assert d.headline == (not axis.marginal) and d.unit == axis.unit
        assert t.coverage.gate_pct == card.coverage.gate_pct


def test_every_type_and_structural_level_has_a_standard_dashboard():
    for t in dm.TYPES.values():
        assert isinstance(t.dashboard, dm.Dashboard)
        assert t.dashboard.template or t.dashboard.proposed
    assert "joint-3d" in dm.TYPES["integrated_servo"].dashboard.components
    assert "camera-clip" in dm.TYPES["depth_camera"].dashboard.components
    assert {"deployment", "adapter", "assembly"} <= set(dm.STRUCTURAL)


# --- the committed projection ------------------------------------------------------------------------------------------------------

def test_the_export_is_json_and_the_committed_file_is_it():
    data = dm.export()
    text = json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    assert json.loads(text) == data
    assert data["schema"] == dm.SCHEMA
    assert {"families", "excitations", "offline_scopes", "levels", "tags", "structural", "entity_types", "models", "parameters",
            "metrics", "diagnostics", "coverage", "routines", "parameter_routines", "migration"} <= set(data)
    assert len(data["models"]) == sum(len(t.models) for t in dm.TYPES.values())
    assert {m["key"] for m in data["models"]} == {m.key for t in dm.TYPES.values() for m in t.models}
    committed = dm.DOMAIN_JSON.read_text(encoding="utf-8")
    assert committed == text, "type_cards/domain_v3.json is stale: python3 -m type_cards.domain --write"


def test_the_stop_error_and_the_saturation_are_computed_per_run_now():
    """2026-11-07 (the metrics lane): tools/run_metrics.py writes RobotDx's catalog entries servo.stop_error and driver.saturation per run
    (<dep>/run_metrics.json); the metric's own id keys its rows. The other model-independent metrics of the rack's parts say what they lack."""
    stop = dm.metric("integrated_servo", "servo.stop_error")
    sat = dm.metric("foc_controller", "driver.saturation")
    assert (stop.per_run.table, sat.per_run.table) == ("run_metrics", "run_metrics")
    assert stop.robotdx == "servo.stop_error" and sat.robotdx == "driver.saturation"
    assert not stop.why_not and not sat.why_not
    for tid in ("integrated_servo", "foc_controller", "bldc_motor", "gearbox", "encoder"):
        for m in dm.TYPES[tid].metrics:
            if m.per_run is None and not m.model_dependent:
                assert m.why_not != dm.WHY_NOT_RUN, f"{m.id}: a model-independent metric of the rack's parts says what its runs lack"
