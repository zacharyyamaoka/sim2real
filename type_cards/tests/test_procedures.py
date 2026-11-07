"""Calibration procedures as typed records, written before them (2026-11-07).

Zach, 2026-11-07 (via the coordinator): "We have the real thing and we have the twin. Any error is caused by errors in our model: the
fidelity of the models and the accuracy of the parameters (kinematic, dynamic, ...). So this whole conversation is about what are the
parameters and what are the methods we have to calibrate those parameters." And his daily note of Nov 6 ("Bench marking the different
methods of identify the parmaters"): "enumerate some different like calibration schemes ... dynameter could be one ... Some of these we
can run on a bench some we can run when the robot is deployed etc.. We can also like check these vs an orcale in simulation".

    uv run --no-project --with pytest pytest -q /home/bam/sim2real/type_cards/tests

What it holds type_cards/calibration.py's PROCEDURES and EQUIPMENT to (they extend that module's packages; the API is CONTRACT.md's):
- a procedure belongs to one of Zach's packages and names what it identifies as (card, rung, parameter), each real on that card's ladder;
- it runs on the bench, deployed, or both; its wall time and operator time carry a unit and a source, a citation or "estimate";
- its equipment exists in EQUIPMENT, each item with a cost in USD and a source; the procedure's cost is their sum, its source honest;
- it states the excitation and coverage it needs and how many times its measurement is taken;
- its code homes exist at their refs; "not implemented" means no code, and no code means no oracle numbers;
- an oracle check is named only where the sysid oracle can run it (code on bam_ws main or in this repo), else a note says why not;
- alternatives name each other (the same parameters, another method), so a comparison is never one-sided;
- the procedures the coordinator listed (2026-11-07) are all there, each pair as alternatives;
- the export carries procedures and equipment as JSON, each procedure with its summed equipment cost.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from type_cards import registry as reg  # noqa: E402

CHECKED = REPO / "type_cards" / "references_checked.json"
SYSID_EXAMPLES = REPO / "sysid" / "examples"
# The coordinator's list (2026-11-07), as procedure ids, and the pairs that are each other's alternative.
REQUIRED = {
    "homing.single_touch", "homing.repeat_averaged",
    "kinematics.dh_ur_style", "kinematics.general_transform", "kinematics.ik_fine_tune",
    "servo.dynamics_regression", "servo.dynamometer",
    "servo.backlash_reversals_camera", "servo.backlash_clamp",
    "cell.tags_bundle_adjustment",
    "servo.live_reid_t10", "servo.camera_dwell_stop_ruler",
    "arm.backlash_gravity_sweep",
}
PAIRS = (("homing.single_touch", "homing.repeat_averaged"), ("servo.dynamics_regression", "servo.dynamometer"),
         ("servo.backlash_reversals_camera", "servo.backlash_clamp"), ("kinematics.dh_ur_style", "kinematics.general_transform"))


def procedures():
    return reg.PROCEDURES


def exists(home) -> bool:
    # WHY this repo's canonical path is read as the checkout under test: a worktree's new files are not in the main checkout until merged
    repo = str(REPO) if home.repo == "/home/bam/sim2real" else home.repo
    if home.ref:
        return subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{home.ref}:{home.path}"], capture_output=True).returncode == 0
    return (Path(repo) / home.path).exists()


# --- the shape ---------------------------------------------------------------------------------------------------------------

def test_the_procedure_types_are_on_the_one_import():
    for name in ("CalibrationProcedure", "Quantity", "Equipment", "Identifies", "PROCEDURES", "EQUIPMENT", "PROCEDURE_SETTINGS",
                 "PROCEDURE_KINDS", "PROCEDURE_STATUS", "ESTIMATE", "procedure", "procedures_for", "equipment_cost"):
        assert hasattr(reg, name), name
    assert reg.CalibrationProcedure is reg.schema.CalibrationProcedure and reg.Quantity is reg.schema.Quantity
    assert reg.PROCEDURE_SETTINGS == ("bench", "deployed", "both") and set(reg.SETTINGS) < set(reg.PROCEDURE_SETTINGS)
    assert reg.PROCEDURE_KINDS == ("identify", "measure", "use")
    assert reg.PROCEDURE_STATUS == ("implemented", "partial", "not implemented")
    assert reg.ESTIMATE == "estimate"
    assert isinstance(reg.PROCEDURES, tuple) and len(reg.PROCEDURES) >= 20, len(reg.PROCEDURES)


def test_ids_are_unique_and_every_package_is_zachs():
    ids = [p.id for p in procedures()]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    packages = {p.id for p in reg.CALIBRATION_PACKAGES}
    assert all(p.package in packages for p in procedures()), [p.id for p in procedures() if p.package not in packages]
    assert reg.procedure("servo.dynamics_regression").id == "servo.dynamics_regression"
    assert {p.id for p in reg.procedures_for("servo")} >= {"servo.dynamics_regression", "servo.live_reid_t10"}
    assert {p.id for p in reg.procedures_for("hardstop_homing")} >= {"homing.single_touch", "homing.repeat_averaged"}


# --- what it identifies ---------------------------------------------------------------------------------------------------------

def test_every_identified_parameter_is_on_its_cards_ladder():
    for p in procedures():
        assert p.kind in reg.PROCEDURE_KINDS, p.id
        assert p.identifies or p.kind != "identify", f"{p.id} identifies nothing"
        for item in p.identifies:
            assert item.card in reg.CARDS, (p.id, item.card)
            rung = reg.rung(item.card, item.rung)
            assert item.parameters and set(item.parameters) <= set(rung.parameter_names), (p.id, item.card, item.rung, item.parameters)


def test_every_card_with_parameters_has_a_procedure():
    """Each type's identifiable parameters are reached by at least one procedure (a test type alone is not a procedure)."""
    reached = {item.card for p in procedures() for item in p.identifies}
    for cid in ("servo", "gearbox", "arm_6dof", "arm_6dof_gripper", "conveyor", "camera_rgb", "camera_rgbd", "camera_hsi"):
        assert cid in reached, cid


# --- where, how long, what it costs ----------------------------------------------------------------------------------------------

def quantity_ok(q, unit: str, *, positive: bool) -> bool:
    return (isinstance(q, reg.Quantity) and q.unit == unit and isinstance(q.source, str) and q.source.strip()
            and q.value is not None and (q.value > 0 if positive else q.value >= 0))


def test_setting_times_and_costs_carry_units_and_sources():
    for p in procedures():
        assert p.setting in reg.PROCEDURE_SETTINGS, p.id
        assert quantity_ok(p.wall_time, "s", positive=True), (p.id, p.wall_time)
        assert quantity_ok(p.operator_time, "s", positive=False), (p.id, p.operator_time)
        # wall time is the whole procedure, set-up included; operator time is a person's hands-on share of it
        assert p.operator_time.value <= p.wall_time.value, p.id
        missing = [e for e in p.equipment if e not in reg.EQUIPMENT]
        assert not missing, (p.id, missing)
    for eid, item in reg.EQUIPMENT.items():
        assert item.id == eid and item.title and quantity_ok(item.cost, "USD", positive=False), eid


def test_a_procedures_cost_is_its_equipments_sum_and_says_where_it_comes_from():
    for p in procedures():
        cost = reg.equipment_cost(p)
        assert cost.unit == "USD" and abs(cost.value - sum(reg.EQUIPMENT[e].cost.value for e in p.equipment)) < 1e-9, p.id
        estimated = any(reg.EQUIPMENT[e].cost.source == reg.ESTIMATE for e in p.equipment)
        assert (reg.ESTIMATE in cost.source) == estimated, (p.id, cost.source)
        if not p.equipment:
            assert cost.value == 0.0, p.id
    none = [p for p in procedures() if not p.equipment]
    assert none, "some procedures need nothing beyond the robot's own sensors"


def test_excitation_coverage_and_repeats_are_stated():
    for p in procedures():
        assert len(p.excitation) >= 12 and len(p.coverage) >= 8 and len(p.how) >= 20, p.id
        assert isinstance(p.repeats, int) and p.repeats >= 1, (p.id, p.repeats)
    assert reg.procedure("homing.repeat_averaged").repeats > reg.procedure("homing.single_touch").repeats == 1


# --- implementation, oracle, alternatives -------------------------------------------------------------------------------------------

def test_tests_named_are_real_test_types():
    known = {t.id for c in reg.CARDS.values() for t in c.tests}
    for p in procedures():
        assert set(p.tests) <= known, (p.id, sorted(set(p.tests) - known))


def test_code_homes_exist_and_status_follows_the_code():
    for p in procedures():
        assert p.status in reg.PROCEDURE_STATUS, p.id
        assert (p.status == "not implemented") == (not p.code), (p.id, p.status, len(p.code))
        missing = [f"{h.repo}:{h.ref or 'worktree'}:{h.path}" for h in p.code if not exists(h)]
        assert not missing, (p.id, missing)


def test_an_oracle_check_only_where_the_oracle_can_run_it():
    """No code, no oracle numbers. sysid imports bam_ws main and this repo only (docs/decision-sysid-oracle-2026-11-05.md), so code on
    an unmerged branch is cited, never checked; every procedure without a check says why in its oracle_note."""
    check = re.compile(r"(?P<example>[a-z0-9_]+):(?P<procedure>[a-z0-9_.]+)")
    for p in procedures():
        if not p.oracle:
            assert len(p.oracle_note) >= 20, (p.id, "no oracle check and no reason given")
            continue
        assert p.status != "not implemented" and any(not h.ref for h in p.code), p.id
        for name in p.oracle:
            m = check.fullmatch(name)
            assert m and m["procedure"] == p.id and (SYSID_EXAMPLES / m["example"] / "world.json").is_file(), (p.id, name)
    for p in procedures():
        if p.status == "not implemented":
            assert not p.oracle and "not implemented" in p.oracle_note.lower(), p.id


def test_alternatives_name_each_other():
    ids = {p.id for p in procedures()}
    for p in procedures():
        assert set(p.alternatives) <= ids and p.id not in p.alternatives, p.id
        for other in p.alternatives:
            assert p.id in reg.procedure(other).alternatives, (p.id, other)


def test_the_coordinators_procedures_are_all_there():
    ids = {p.id for p in procedures()}
    assert REQUIRED <= ids, sorted(REQUIRED - ids)
    for a, b in PAIRS:
        assert b in reg.procedure(a).alternatives, (a, b)
    assert {reg.procedure(i).setting for i in ("servo.live_reid_t10",)} == {"deployed"}
    assert reg.procedure("servo.dynamometer").equipment and reg.procedure("servo.backlash_clamp").equipment
    assert any(i.card == "servo" and "backlash_rad" in i.parameters for i in reg.procedure("arm.backlash_gravity_sweep").identifies)
    assert reg.procedure("kinematics.ik_fine_tune").kind == "use"
    assert reg.procedure("servo.camera_dwell_stop_ruler").kind == "measure"


# --- the export -------------------------------------------------------------------------------------------------------------------

def test_the_export_carries_procedures_and_equipment():
    doc = reg.export()
    assert json.loads(json.dumps(doc)) == doc
    rows = {r["id"]: r for r in doc["procedures"]}
    assert list(rows) == [p.id for p in procedures()]
    for p in procedures():
        row = rows[p.id]
        assert row["equipment_cost"]["value"] == reg.equipment_cost(p).value and row["package"] == p.package
        assert row["wall_time"]["unit"] == "s" and row["identifies"] == [{"card": i.card, "rung": i.rung, "parameters": list(i.parameters)} for i in p.identifies]
    assert set(doc["equipment"]) == set(reg.EQUIPMENT)
    for key in ("procedure_settings", "procedure_kinds", "procedure_status"):
        assert key in doc, key


def test_procedure_references_are_real_and_checked():
    checked = json.loads(CHECKED.read_text())
    for p in procedures():
        for ref in p.references:
            assert re.search(r"\((1[89]|20)\d\d\)", ref.title), (p.id, ref.title)
            if ref.doi:
                hit = checked["doi"].get(ref.doi)
                assert hit and hit["ok"], (p.id, ref.doi)
            if ref.url:
                hit = checked["url"].get(ref.url)
                assert hit and hit["ok"], (p.id, ref.url, hit)
