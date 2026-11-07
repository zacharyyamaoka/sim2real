"""Deployments, their trees and the parameters table (type_cards/instances.py), written before it (2026-11-07).

    uv run --no-project --with pytest pytest -q /home/bam/sim2real/type_cards/tests

Zach (2026-11-06): "I like organizing this around Deployments ... The orcale examples are also deployments its just they are
'Virtual' ... Each sub componet of the deployment could basically be its own deployment ... the first level of filtering ... those
deployments tagged with orcale example. Or perhaps only deployments that use a camera". And the parameter view: "one of the preset views
should be all of the paramteres ... only of the parmaters for the Winning model(s) ... all of the paramters that had at least some model
run and rpocuded datata ... each model if you display mutliple at the same time should get its own Recovered error toerlance colum".

Held here, over the committed sysid results (always present), the registry and the v3 records; the rack's tree where the app's data
is built:
- six virtual deployments (the oracle examples) and every physical one in app/registry.json, kinds and tags right, ids unique;
- every node's parent is a node of its deployment; a virtual tree mirrors its sysid tree node for node; every node is typed by v3;
- the parameters table carries every graded value the oracle wrote, true / nominal / recovered as written, one column group per
  (routine, model), and its three presets (all, winning model, with results) nest;
- the run tags reach runs.json through the site's tree overlay (site/deploy_tree.py) as additive columns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from type_cards import domain as dm  # noqa: E402
from type_cards import instances as inst  # noqa: E402

RESULTS = inst.load_results(REPO / "sysid" / "results")
EXAMPLES = ("pendulum_can11", "ur5e", "ur5e_2f85", "conveyor", "dual_arm_cell", "linescan_cell")
DATA = Path("/home/bam/sim2real/app/data")


@pytest.fixture(scope="module")
def nodes():
    return inst.virtual_nodes(RESULTS)


def test_six_virtual_deployments_from_the_oracle(nodes):
    roots = [n for n in nodes if n["parent"] is None]
    assert [r["id"] for r in roots] == list(EXAMPLES)
    for r in roots:
        assert r["kind"] == "virtual" and "oracle example" in r["tags"]
        assert r["page"] == f"/sysid/{r['id']}/" and r["depth"] == 0 and r["root"] == r["id"]
        assert r["title"] == RESULTS[r["id"]]["title"]


def test_virtual_trees_mirror_the_sysid_trees(nodes):
    for ex in EXAMPLES:
        tree = RESULTS[ex]["tree"]
        mine = [n for n in nodes if n["root"] == ex]
        assert len(mine) == len(tree), ex
        ids = {n["id"] for n in mine}
        for n in mine:
            assert n["parent"] is None or n["parent"] in ids
            assert n["kind"] == "virtual"
            assert n["entity_type"] is None or n["entity_type"] in dm.TYPES
            assert n["entity_type"] is not None or n["structural"] in dm.STRUCTURAL, (ex, n["id"])
        # a sysid node typed by a v2 card is typed by that card's v3 type
        for row in tree:
            if row["type_source"] == "type_cards":
                n = next(x for x in mine if x["sysid_id"] == row["id"])
                assert n["entity_type"] == dm.CARD_TYPE[row["type"]] or (row["type"] == "arm_6dof_gripper" and n["structural"] == "assembly")


def test_tags_are_declared_or_derived_from_the_tree(nodes):
    tags = {n["id"]: set(n["tags"]) for n in nodes if n["parent"] is None}
    assert "uses camera" in tags["dual_arm_cell"] and "uses camera" in tags["linescan_cell"] and "uses camera" in tags["pendulum_can11"]
    assert "uses camera" not in tags["ur5e"] and "uses camera" not in tags["conveyor"]
    assert "uses arm" in tags["ur5e"] and "uses gripper" in tags["ur5e_2f85"] and "uses conveyor" in tags["linescan_cell"]
    assert all(t in dm.TAGS for ts in tags.values() for t in ts)


def test_a_sub_component_is_a_deployment_of_its_own(nodes):
    """Every node is addressable as a deployment (its subtree); its children are its sub-deployments."""
    arm = next(n for n in nodes if n["root"] == "ur5e" and n["entity_type"] == "rigid_body_chain")
    subs = inst.sub_deployments(nodes, arm["id"])
    assert len(subs) == 6 and all(s["entity_type"] == "integrated_servo" for s in subs)
    assert [n["id"] for n in inst.subtree(nodes, arm["id"])][0] == arm["id"]
    assert inst.sub_deployments(nodes, "ur5e")[0]["id"] == arm["id"]


def test_the_physical_deployments_come_from_the_registry_and_their_records():
    registry = json.loads((REPO / "app" / "registry.json").read_text())["deployments"]
    records = inst.physical_records()
    assert {d["id"] for d in registry} == set(records), "every registry deployment has a v3 record (type_cards/deployments/), and back"
    rack = records["one-dof-test-rack"]
    assert isinstance(rack, dm.PhysicalDeployment)
    assert {c.serial for c in rack.cameras} == {"218622274411", "218622276036"}
    assert {s for c in rack.cameras for s in c.sees} == {1, 4, 11, 12, 13, 14, 15, 21}


@pytest.mark.skipif(not (DATA / "one-dof-test-rack" / "devices.json").is_file(), reason="the app's data is not built")
def test_the_rack_tree_has_adapters_stations_parts_and_cameras():
    nodes = inst.physical_nodes(DATA)
    rack = [n for n in nodes if n["root"] == "one-dof-test-rack"]
    root = rack[0]
    assert (root["id"], root["kind"], root["parent"]) == ("one-dof-test-rack", "physical", None)
    assert "uses camera" in root["tags"] and "uses servo" in root["tags"] and "oracle example" not in root["tags"]
    stations = [n for n in rack if n["structural"] == "station"]
    assert len(stations) == 8 and all(n["entity_type"] == "integrated_servo" for n in stations)
    assert all(n["runs"] > 0 for n in stations)
    cams = [n for n in rack if n["entity_type"] == "depth_camera"]
    assert len(cams) == 2 and all(c["parent"] == "one-dof-test-rack" for c in cams)
    assert all(set(c["sees"]) <= {s["id"] for s in stations} and c["sees"] for c in cams)
    drivers = [n for n in rack if n["entity_type"] == "foc_controller"]
    assert len(drivers) == 8 and all(next(s for s in stations if s["id"] == d["parent"])["device"] == d["device"] for d in drivers)
    # a direct drive has no gearbox node: the record says "none"
    can4 = next(s for s in stations if s["device"] == "CAN 4")
    assert not any(n["parent"] == can4["id"] and n["entity_type"] == "gearbox" for n in rack)


# --- the parameters table ----------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def table(nodes):
    routines = json.loads((REPO / "sysid" / "results" / "calibration_routines.json").read_text())
    return inst.parameter_table(nodes, RESULTS, routines)


def test_every_graded_value_is_a_row_as_the_oracle_wrote_it(table):
    rows = {r["id"]: r for r in table["rows"]}
    for ex in EXAMPLES:
        for p in RESULTS[ex]["parameters"]:
            r = rows[f"{ex}/{p['key']}"]
            assert (r["true"], r["nominal"], r["unit"]) == (p["true"], p["nominal"], p["unit"])
            assert r["entity_type"] == dm.CARD_TYPE[p["card"]] and r["deployment"] == ex
            assert r["parameter"] in {x.name for x in dm.TYPES[r["entity_type"]].parameters}
            assert r["has_results"] is True
    # the noise ladder grades a few values the examples do not (CAN 11's sliding Coulomb level and wear rate, the cell's camera knock):
    # rows too, on the deployment's one node of their type
    routines = json.loads((REPO / "sysid" / "results" / "calibration_routines.json").read_text())
    for p in routines["parameters"]:
        if p["example"] in EXAMPLES:
            r = rows[f"{p['example']}/{p['key']}"]
            assert (r["true"], r["entity_type"]) == (p["true"], dm.CARD_TYPE[p["card"]]), p["key"]
            assert r["node"].startswith(p["example"])
    assert rows["dual_arm_cell/camera_knock.dx_m"]["node"] == "dual_arm_cell/torso/head_camera"
    assert rows["pendulum_can11/can11.backlash_wear_rad_per_h"]["parameter"] == "backlash_wear_rad_per_nm_rev"


def test_one_column_group_per_routine_and_model(table):
    cols = {c["id"]: c for c in table["result_columns"]}
    assert len(cols) == len(table["result_columns"])
    for c in cols.values():
        assert c["id"] == f"{c['routine']}:{c['model']}"
        assert dm.model(c["entity_type"], c["model"]) is not None
        assert c["properties"] == [f"{p}@{c['id']}" for p in inst.RESULT_PROPERTIES]
    assert "servo.dynamics_regression:M4.dynamics.twin" in cols and "servo.dynamics_regression:M0.dynamics.ideal" in cols
    rows = {r["id"]: r for r in table["rows"]}
    g = rows["pendulum_can11/can11.gravity_nm"]
    reg_m4 = g["recovered@servo.dynamics_regression:M4.dynamics.twin"]
    routines = json.loads((REPO / "sysid" / "results" / "calibration_routines.json").read_text())
    entry = next(p for p in routines["parameters"] if p["example"] == "pendulum_can11" and p["key"] == "can11.gravity_nm")
    want = next(m for m in entry["models"] if m["routine"] == "servo.dynamics_regression" and m["fit"] == "M4")["levels"]["1x"]
    assert reg_m4 == want["recovered"]["mean"]
    assert g["error@servo.dynamics_regression:M4.dynamics.twin"] == want["error"]
    assert g["tolerance@servo.dynamics_regression:M4.dynamics.twin"] == entry["tolerance"]["value"]
    # the best column is the one with the least error over tolerance
    scored = {c: g.get(f"error_over_tolerance@{c}") for c in cols if g.get(f"error_over_tolerance@{c}") is not None}
    assert g["best"] == min(scored, key=lambda c: abs(scored[c]))


def test_the_three_presets_nest(table):
    rows = table["rows"]
    presets = table["presets"]
    assert set(presets) >= {"all", "winning model", "with results", "errors only"}
    every = [r["id"] for r in rows]
    winning = [r["id"] for r in rows if r["winning"]]
    results = [r["id"] for r in rows if r["has_results"]]
    assert set(results) <= set(every) and set(winning) <= set(every)
    assert len(results) < len(every), "all parameters includes the ones no routine produced a value for"
    assert 0 < len(winning) < len(every)
    assert presets["with results"]["filter"] == "has_results == true"
    # CAN 11's selection picked M4: its gravity is a parameter of the winning model, its thermal model is not
    rows_by = {r["id"]: r for r in rows}
    assert rows_by["pendulum_can11/can11.gravity_nm"]["winning"] is True
    m5_only = [r for r in rows if r["deployment"] == "pendulum_can11" and r["parameter"] == "voltage_available_v"]
    assert m5_only and not any(r["winning"] for r in m5_only)
    assert all(r["winning_basis"] in ("selected", "current") for r in rows if r["entity_type"])


def test_recovered_values_are_single_valued_estimates(table):
    for r in table["rows"]:
        for c in table["result_columns"]:
            v = r.get(f"recovered@{c['id']}")
            if v is not None:
                assert isinstance(v, (int, float))
                lo, hi = r.get(f"ci95_lo@{c['id']}"), r.get(f"ci95_hi@{c['id']}")
                assert (lo is None) == (hi is None)
    est = dm.Estimate(mean=1.0, ci95=(0.9, 1.1), interval="bootstrap")
    assert est.form == "single"
    with pytest.raises(ValueError):
        dm.Estimate(mean=1.0, form="network")    # room is left for it, not in scope yet


# --- run tags in runs.json -----------------------------------------------------------------------------------------------------------

def test_run_tags_are_additive_columns_of_runs_json(tmp_path):
    sys.path.insert(0, str(REPO / "site"))
    import deploy_tree  # noqa: PLC0415

    row = {"run": "x", "device": "CAN 11", "kind": "swing", "npz": None, "basis": "real"}
    doc = {"name": "runs", "schema": {"fields": [{"name": "run", "type": "string"}, {"name": "kind", "type": "string"}]}, "rows": [row]}
    (tmp_path / "runs.json").write_text(json.dumps(doc))
    deploy_tree.enrich_runs(tmp_path, {"id": "d", "title": "D", "archive": []}, [{"id": "d", "parent": None, "depth": 0, "device": None, "label": "D"}],
                            [{"device": "CAN 11", "type": "servo"}])
    out = json.loads((tmp_path / "runs.json").read_text())
    r = out["rows"][0]
    assert (r["excitation"], r["closed_loop"], r["offline_scope"]) == ("mixed", True, "split")
    names = [f["name"] for f in out["schema"]["fields"]]
    assert {"excitation", "closed_loop", "offline_scope", "run", "kind"} <= set(names)


def test_a_row_no_graded_value_binds_never_borrows_another_parts_nominal(table):
    """The v2 servo card's nominal values are CAN 11's (its armature, its gravity); a CAN 4 or a UR joint row must not show them as its
    own. A row with no graded value has nominal null and the type card's value apart, labelled."""
    spec_rows = [r for r in table["rows"] if r["key"] is None]
    assert spec_rows and all(r["nominal"] is None for r in spec_rows)
    kp = next(r for r in spec_rows if r["entity_type"] == "integrated_servo" and r["parameter"] == "kp_nm_rad")  # CAN 11's 31.831 on the card
    assert kp["type_nominal"] == dm.parameter("integrated_servo", "kp_nm_rad").nominal == 31.831 and kp["nominal"] is None


def test_both_datasets_are_house_tables_with_a_field_per_column(nodes, table):
    """The house table shape the app's own tables have (runs.json: name, title, source, contract, schema.fields, rows), so a data-ui
    view reads them as it reads the rest; every key a row has is a field, typed with the robotics contract's words."""
    dep = inst.deployments_dataset(nodes)
    for doc in (dep, table):
        assert doc["contract"] == dm.SCHEMA and {"name", "title", "source", "rows"} <= set(doc)
        fields = {f["name"]: f for f in doc["schema"]["fields"]}
        assert {k for r in doc["rows"] for k in r} <= set(fields), doc["name"]
        assert {f["type"] for f in fields.values()} <= {"string", "number", "integer", "boolean", "array"}
    assert {f["name"]: f["type"] for f in dep["schema"]["fields"]}["tags"] == "array"


# --- the producer's model labels: which ladder model each twin it replays is (2026-11-07, w2c) ------------------------------------------
# WHY (the coordinator, 2026-11-07: "the rack's producer labels ("twin of record", "twin A", "twin D"…) have no map to ladder models ...
# Twin of record is the M4.dynamics twin; read the bam_rack_twin record to decide each label"): a page that names "twin of record" can
# then name the ladder model it is, and a model's page can say which stations use it. The words stay the producer's: a label is looked
# up exactly, never parsed, and a label nobody mapped maps to nothing (unknown stays unknown).

RACK = "one-dof-test-rack"


def test_every_producer_label_names_a_model_on_its_types_ladder():
    for dep, record in inst.physical_records().items():
        labels = [m.label for m in record.models]
        assert len(labels) == len(set(labels)), f"{dep}: a label is mapped twice"
        for m in record.models:
            assert isinstance(m, dm.ModelLabel)
            assert dm.model(m.type, m.model).family in dm.TYPES[m.type].families
            assert m.fit and m.friction and m.source, f"{dep} {m.label}: say what set its values, its friction law and where it is built"


def test_the_twin_of_record_is_the_rack_twin_m4():
    m = inst.label_model(RACK, "twin of record")
    assert m is not None and (m.type, m.model) == ("integrated_servo", "M4.dynamics.twin")
    assert dm.model("integrated_servo", "M4.dynamics.twin").current, "the rack's twin of record is the servo ladder's current model"


def test_a_label_is_looked_up_exactly_and_an_unknown_one_maps_to_nothing():
    assert inst.label_model(RACK, "twin A · deployed") is not None
    assert inst.label_model(RACK, "twin A") is None, "a label is the producer's whole words, never a prefix"
    assert inst.label_model(RACK, "twin Z · not written yet") is None
    assert inst.label_model("no-such-deployment", "twin of record") is None
    assert inst.label_model(RACK, None) is None


@pytest.mark.skipif(not (DATA / RACK / "run_gates.json").is_file(), reason="the app's data is not built")
def test_every_label_the_rack_replays_is_mapped():
    """Every model the producer replayed a rack run with (RobotDx's stock.model_error rows, titled "<label> vs real") has its ladder
    model: a new label fails here until someone reads its twin and maps it, never a guess."""
    from type_cards import selection as sel  # noqa: PLC0415

    rows = json.loads((DATA / RACK / "run_gates.json").read_text())["rows"]
    written = {sel.model_label(r.get("title", "")) for r in rows if r.get("diagnostic") == "stock.model_error"}
    assert written, "the rack's run_gates.json has model_error rows"
    missing = sorted(label for label in written if inst.label_model(RACK, label) is None)
    assert not missing, f"labels with no ladder model: {missing}"


def test_the_label_map_is_a_house_table_the_site_serves(tmp_path):
    doc = inst.model_labels_dataset()
    assert doc["contract"] == dm.SCHEMA and {"name", "title", "source", "rows"} <= set(doc)
    fields = {f["name"] for f in doc["schema"]["fields"]}
    assert {k for r in doc["rows"] for k in r} <= fields
    want = [(dep, m.label, m.type, m.model) for dep, rec in inst.physical_records().items() for m in rec.models]
    assert [(r["deployment"], r["label"], r["type"], r["model"]) for r in doc["rows"]] == want
    for r in doc["rows"]:
        spec = dm.model(r["type"], r["model"])
        assert (r["model_key"], r["model_title"], r["family"], r["k"]) == (spec.key, spec.title, spec.family, spec.k)


# --- per-unit limits (2026-11-07, the metrics lane) --------------------------------------------------------------------------------
# A diagnostic whose limit is "set per unit" (the servo's stop error: the joint's share of the 5 mm tool gate; the board's loop rate: the
# expected rate less 10 %) reads unknown until a unit sets it. The rack's record sets them, each with its source, and instances puts them on
# the nodes they bind (deployments.json `limits`), where selection.compute and the browser read them.

RACK_TWIN = Path("/home/bam/bam_ws/src/dev/bam_rack_twin/bam_rack_twin")


def _constant(path: Path, name: str):
    """A module-level constant read from the producer's source (ast, never imported): the oracle the record's copy is held to."""
    import ast  # noqa: PLC0415

    for stmt in ast.parse(path.read_text()).body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
            return ast.literal_eval(stmt.value)
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == name:
            return ast.literal_eval(stmt.value)
    raise KeyError(name)


def test_a_unit_limit_is_a_frozen_keyword_record():
    import dataclasses  # noqa: PLC0415

    assert dataclasses.is_dataclass(dm.UnitLimit) and dm.UnitLimit.__dataclass_params__.frozen
    assert all(f.kw_only for f in dataclasses.fields(dm.UnitLimit))
    assert [f.name for f in dataclasses.fields(dm.UnitLimit)][:6] == ["device", "diagnostic", "warn", "error", "target", "source"]
    assert "limits" in [f.name for f in dataclasses.fields(dm.PhysicalDeployment)]


def test_the_rack_sets_each_stations_stop_allocation_and_loop_rate():
    rack = inst.physical_records()["one-dof-test-rack"]
    by = {(u.device, u.diagnostic): u for u in rack.limits}
    devices = {f"CAN {c}" for c in (1, 4, 11, 12, 13, 14, 15, 21)}
    assert {d for d, x in by if x == "servo.stop_error.dx"} == devices
    assert {d for d, x in by if x == "driver.loop_rate.dx"} == devices
    for u in rack.limits:
        assert u.source, f"{u.device} {u.diagnostic}: every per-unit limit says where it comes from"
        assert u.warn is not None or u.error is not None or u.target is not None
        dm.diagnostic(dm.TYPES[{"servo.stop_error.dx": "integrated_servo", "driver.loop_rate.dx": "foc_controller"}[u.diagnostic]].id, u.diagnostic)
    assert by[("CAN 11", "servo.stop_error.dx")].warn == 3.6 and by[("CAN 11", "servo.stop_error.dx")].target == 3.6
    assert by[("CAN 11", "driver.loop_rate.dx")].warn == 90.0


@pytest.mark.skipif(not (RACK_TWIN / "acceptance.py").is_file(), reason="bam_ws is not on this machine")
def test_the_racks_limits_are_the_producers_own_numbers():
    """The stop allocation is bam_rack_twin acceptance.py's STOP_ALLOCATION_MRAD, the expected rate experiments.py's RATE_HZ (less RobotDx's
    tolerance, 10 %), read from their source here, so a change there turns this red rather than leaving a stale copy."""
    allocation = _constant(RACK_TWIN / "acceptance.py", "STOP_ALLOCATION_MRAD")
    rate = _constant(RACK_TWIN / "hardware" / "experiments.py", "RATE_HZ")
    rack = inst.physical_records()["one-dof-test-rack"]
    stop = {u.device: u for u in rack.limits if u.diagnostic == "servo.stop_error.dx"}
    loop = {u.device: u for u in rack.limits if u.diagnostic == "driver.loop_rate.dx"}
    assert {d: (u.warn, u.target) for d, u in stop.items()} == {f"CAN {c}": (v, v) for c, v in allocation.items()}
    assert {d: u.warn for d, u in loop.items()} == {f"CAN {c}": pytest.approx(rate * 0.9) for c in allocation}


@pytest.mark.skipif(not (DATA / "one-dof-test-rack" / "devices.json").is_file(), reason="the app's data is not built")
def test_the_limits_reach_the_nodes_they_bind():
    nodes = inst.physical_nodes(DATA)
    assert "limits" in inst.NODE_FIELDS
    rack = [n for n in nodes if n["root"] == "one-dof-test-rack"]
    from type_cards import selection as sel  # noqa: PLC0415

    can11 = next(n for n in rack if n["structural"] == "station" and n["device"] == "CAN 11")
    assert sel.node_limits(can11)["servo.stop_error.dx"]["warn"] == 3.6 and sel.node_limits(can11)["servo.stop_error.dx"]["source"]
    driver = next(n for n in rack if n["entity_type"] == "foc_controller" and n["device"] == "CAN 11")
    assert [(x["diagnostic"], x["warn"]) for x in driver["limits"]] == [("driver.loop_rate.dx", 90.0)] and driver["limits"][0]["source"]
    assert set(driver["limits"][0]) == {"diagnostic", "warn", "source"}, "a side the unit does not set is left out, never null-filled"
    motor = next(n for n in rack if n["entity_type"] == "bldc_motor" and n["device"] == "CAN 11")
    assert motor["limits"] == [], "a limit binds only the node whose type holds that diagnostic"
    virtual = inst.virtual_nodes(RESULTS)
    assert all(n["limits"] == [] for n in virtual)
    assert {f["name"]: f["type"] for f in inst.deployments_dataset(nodes + virtual)["schema"]["fields"]}["limits"] == "array"


def test_a_limit_on_a_diagnostic_no_node_holds_is_refused(tmp_path):
    bad = dm.PhysicalDeployment(id="one-dof-test-rack", limits=(dm.UnitLimit(device="CAN 11", diagnostic="servo.nope.dx", warn=1.0, source="x"),))
    with pytest.raises(ValueError):
        inst.unit_limits(bad, [{"id": "r/can11", "device": "CAN 11", "entity_type": "integrated_servo"}])
