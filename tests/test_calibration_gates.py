"""Gap B: the equipment you have, and the gates a routine passes before it is ranked (2026-11-18, red first).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_calibration_gates.py

Run it on a cloud VM (bam_ws tools/cloud) while the arm is powered. The pendulum test needs bam_rack_twin's venv; SIM2REAL_REQUIRE_RACK=1
(the cloud job sets it) turns its skip into a failure. Planning only: nothing here measures.

Zach's words, the only authority cited here:
    "you can define what equipment you have, etc. etc.." (Daily Note 2026-11-17, ".calibreat(Config) I think was the pattern")
    "dynameter could be one... but if you don't have access to that..." (2026-11-06)
    "recover the orginal values to within a tolerance" (2026-11-11)
The gate list itself (implemented -> runs where you are -> equipment you have -> recovery not failing at the config's noise level -> rank)
is the session's default, not his ruling; it is listed under "decided for you" with its undo.

What was wrong on sim2real main @ 7526705: Budget had a $ cap but no inventory, so a routine needing a jig you lack was planned (and a rig's
own routines had no equipment check at all); recovery only RANKED, so a routine graded wrong at the config's level could still be planned;
and a "why" could claim a routine is "ranked ahead of" one that ranks better.

The ruler (written before the code; whoever turns it green may not edit it):
1. Budget(equipment=...) is a frozen inventory (borrowed kit counts) with a JSON round trip; None, the default, means no inventory.
2. A routine needing an item you do not have is dropped, naming the item, its $ and Budget.equipment, on the catalog path, on a rig's own
   routines and on setup routines; what only it found is uncovered with that reason. An id the catalog does not hold is refused.
   Including a gated routine is refused, naming the gate (include never silently fails to force).
3. totals["equipment_usd"] stays the equipment the plan needs; totals["equipment_to_buy_usd"] leaves out what you have, and
   max_equipment_usd caps what is still to buy (strict mode included).
4. On the catalog path a FIT routine graded failing at config.level is never planned and says "recovery at <level> fails". A rig's own
   routines are its implementation and keep their place whatever another rig's grade says; setup (configure, tune) routines are judged on
   what they set, never on a recovery ladder.
5. The cover stays today's minimal greedy cover by routine_rank; a why never says "ranked ahead of" a routine that ranks better.
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
LEVELS = ("0x", "1x", "3x", "10x")
SERVO_M4 = {"j1": ("integrated_servo", "M4.dynamics.twin")}
SERVO_M2 = {"j1": ("integrated_servo", "M2.dynamics.coulomb_viscous")}
GEARBOX_M4 = {"gb": ("gearbox", "M4.dynamics.backlash")}
GRIPPER_TCP = {"g": ("gripper", "M0.kinematics.tcp")}


def _calibration():
    """WHY imported per test and never importorskip: a missing back end must FAIL here, not skip."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module


def _reg():
    from sim2real.cards import registry as reg  # noqa: PLC0415

    return reg


def _grade(routine_id: str, level: str) -> int:
    """0 passes, 1 not graded, 2 fails: read only through the one recovery reader."""
    from sim2real.calibration import recovery as rec  # noqa: PLC0415

    entry = rec.recovery(routine_id, level)
    passed = None if entry is None else entry.get("pass")
    return {True: 0, None: 1, False: 2}[passed]


def _reason(dropped, routine_id: str) -> str:
    reasons = [why for rid, why in dropped if rid == routine_id]
    assert reasons, f"{routine_id} is not in dropped: {dropped}"
    return reasons[0]


def _needs(routine_id: str) -> tuple[str, ...]:
    return tuple(_reg().routine(routine_id).equipment)


@dataclass(frozen=True)
class FakeRoutine:
    """A rig's routine as the planner reads it; its equipment is the catalog's for its registered id (one source for gate and cost)."""
    id: str
    identifies: tuple[str, ...]
    requires: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()

    def runs(self, values):
        return ()

    def fit(self, measured, values, twin):
        raise AssertionError("plan() fitted a routine: planning fits nothing")


GAP = FakeRoutine("servo.backlash_reversals_camera", ("can11.backlash_rad",))
DYNAMICS = FakeRoutine("servo.dynamics_regression",
                       ("can11.gravity_nm", "can11.armature_kg_m2", "can11.frictionloss_nm", "can11.damping_nm_s_rad"),
                       uses=("backlash_rad",))


def rig_twin(*routines: FakeRoutine):
    """A twin whose runner carries a rig (plan() takes its rig path): the rig's routines, each key owned by the routine that writes it."""
    keys = [k for r in routines for k in r.identifies]
    rig = SimpleNamespace(
        name="fake_can11",
        routines=lambda: tuple(routines),
        parameters=lambda: tuple(SimpleNamespace(key=k, routine=r.id) for r in routines for k in r.identifies))
    servo = SimpleNamespace(id="can11", parameters={k.split(".", 1)[1]: None for k in keys})
    description = SimpleNamespace(id="fake_can11", instances=(servo,), values=lambda: {})
    return SimpleNamespace(runner=SimpleNamespace(rig=rig, description=description), description=description)


# --- 1. the inventory -----------------------------------------------------------------------------------------------------------------------


def test_the_budget_holds_the_equipment_you_have_and_round_trips():
    cal = _calibration()
    assert cal.Budget().equipment is None, "no inventory by default: every item counts as available (today's behaviour)"
    budget = cal.Budget(settings=("bench",), equipment=["camera_tags", "charuco_board", "camera_tags"])
    assert budget.equipment == ("camera_tags", "charuco_board"), "a tuple, each item once, in the order given"
    assert budget.missing(("camera_tags", "output_clamp", "dynamometer")) == ("output_clamp", "dynamometer")
    assert cal.Budget().missing(("output_clamp",)) == (), "no inventory: nothing is missing"
    assert cal.Budget(equipment=()).missing(("camera_tags",)) == ("camera_tags",), "an empty inventory has nothing"
    with pytest.raises(TypeError):
        cal.Budget(equipment="camera_tags")  # a bare string is not a tuple of ids
    with pytest.raises(dataclasses.FrozenInstanceError):
        budget.equipment = ()  # type: ignore[misc]
    config = cal.CalibrationConfig(budget=budget, level="3x")
    doc = json.loads(json.dumps(config.to_dict()))
    assert doc["budget"]["equipment"] == ["camera_tags", "charuco_board"]
    assert cal.CalibrationConfig.from_dict(doc) == config
    default = json.loads(json.dumps(cal.CalibrationConfig().to_dict()))
    assert cal.CalibrationConfig.from_dict(default).budget.equipment is None


def test_an_equipment_id_the_catalog_does_not_hold_is_refused():
    cal = _calibration()
    config = cal.CalibrationConfig(budget=cal.Budget(equipment=("camera_tags", "dyno")))
    with pytest.raises(cal.CalibrationPlanError, match="dyno"):
        cal.select(SERVO_M4, config=config)
    with pytest.raises(cal.CalibrationPlanError, match="dyno"):
        cal.plan(rig_twin(GAP, DYNAMICS), config)


# --- 2. the equipment gate ---------------------------------------------------------------------------------------------------------------


def test_a_routine_needing_equipment_you_lack_is_dropped_and_its_parameters_say_why():
    cal = _calibration()
    assert "output_clamp" in _needs("servo.backlash_clamp")  # the premise, from the catalog
    sel = cal.select(GEARBOX_M4, config=cal.CalibrationConfig(budget=cal.Budget(equipment=())))
    assert "servo.backlash_clamp" not in sel.routines
    why = _reason(sel.dropped, "servo.backlash_clamp")
    assert "output_clamp" in why and "$150" in why and "Budget.equipment" in why, why
    uncovered = {n: w for _i, n, w in sel.uncovered}
    for name in ("backlash_rad", "gear_stiffness_nm_rad"):
        assert name in uncovered and "output_clamp" in uncovered[name], (name, uncovered)
    have = cal.select(GEARBOX_M4, config=cal.CalibrationConfig(budget=cal.Budget(equipment=("output_clamp",))))
    assert "servo.backlash_clamp" in have.routines, have.dropped


def test_the_racks_kit_drops_the_jigs_it_lacks_and_still_finds_the_backlash():
    """The 1-DOF rack has its link camera on tags (camera_tags) and no clamp jig, weighed mass or thermocouple (the routines session's
    finding of 2026-11-17)."""
    cal = _calibration()
    kit = ("camera_tags",)
    sel = cal.select(SERVO_M4, config=cal.CalibrationConfig(budget=cal.Budget(equipment=kit)))
    for rid, item in (("servo.backlash_clamp", "output_clamp"), ("servo.known_mass", "weighed_mass"), ("servo.heating_t8", "thermocouple")):
        assert rid not in sel.routines, rid
        assert item in _reason(sel.dropped, rid), (rid, sel.dropped)
    for rid in tuple(sel.routines) + tuple(sel.setup):
        assert set(_needs(rid)) <= set(kit), f"{rid} is planned but needs {_needs(rid)}, outside the kit {kit}"
    uncovered = {n: w for _i, n, w in sel.uncovered}
    assert "output_clamp" in uncovered["gear_stiffness_nm_rad"], uncovered
    assert "weighed_mass" in uncovered["torque_scale"] and "thermocouple" in uncovered["thermal_r_c"], uncovered
    assert "backlash_rad" not in uncovered, "a routine the rack can run finds the backlash"


def test_a_rigs_own_routine_needing_equipment_you_lack_is_dropped():
    cal = _calibration()
    assert "camera_tags" in _needs(GAP.id)
    twin = rig_twin(GAP, DYNAMICS)
    assert cal.plan(twin).ids == (GAP.id, DYNAMICS.id), "no inventory: the rig's schedule as it ships"
    kit = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(equipment=("camera_tags",))))
    assert kit.ids == (GAP.id, DYNAMICS.id), kit.dropped
    bare = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(equipment=())))
    assert bare.ids == (DYNAMICS.id,), bare.summary()
    why = _reason(bare.dropped, GAP.id)
    assert "camera_tags" in why and "Budget.equipment" in why, why
    uncovered = {f"{i}.{n}": w for i, n, w in bare.uncovered}
    assert "camera_tags" in uncovered["can11.backlash_rad"], uncovered


def test_including_a_routine_a_gate_drops_is_refused_naming_the_gate():
    cal = _calibration()
    config = cal.CalibrationConfig(include=("servo.backlash_clamp",), budget=cal.Budget(equipment=()))
    with pytest.raises(cal.CalibrationPlanError, match="output_clamp"):
        cal.select(SERVO_M4, config=config)


# --- 3. equipment you have is not bought again ------------------------------------------------------------------------------------------


def test_equipment_you_have_is_not_bought_again():
    cal = _calibration()
    twin = rig_twin(GAP, DYNAMICS)
    have = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(equipment=("camera_tags",), max_equipment_usd=0.0)))
    assert have.ids == (GAP.id, DYNAMICS.id), have.dropped
    assert have.totals["equipment_to_buy_usd"] == 0.0, have.totals
    assert have.totals["equipment_usd"] > 0.0, "equipment_usd still says what the plan needs"
    strict = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(equipment=("camera_tags",), max_equipment_usd=0.0), strict=True))
    assert strict.ids == have.ids
    with pytest.raises(cal.CalibrationPlanError):
        cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(max_equipment_usd=0.0), strict=True))  # no inventory: it all costs
    sel = cal.select(GRIPPER_TCP, config=cal.CalibrationConfig(budget=cal.Budget(equipment=("laser_tracker",), max_equipment_usd=500.0)))
    assert "kinematics.zero_offsets_tracker" in sel.routines, sel.dropped
    unowned = cal.select(GRIPPER_TCP, config=cal.CalibrationConfig(budget=cal.Budget(max_equipment_usd=500.0)))
    assert "kinematics.zero_offsets_tracker" not in unowned.routines
    assert "max_equipment_usd" in _reason(unowned.dropped, "kinematics.zero_offsets_tracker")


# --- 4. the recovery gate: catalog fits only ---------------------------------------------------------------------------------------------


def test_a_catalog_fit_graded_failing_at_the_level_is_dropped_saying_so():
    cal = _calibration()
    assert _grade("servo.live_reid_t10", "1x") == 2 and _grade("servo.stock_quasistatic", "1x") == 2
    assert _grade("servo.dynamics_regression", "10x") == 2
    at_1x = cal.select(SERVO_M2)
    assert "recovery at 1x fails" in _reason(at_1x.dropped, "servo.live_reid_t10")
    assert "recovery at 1x fails" in _reason(at_1x.dropped, "servo.stock_quasistatic")
    at_10x = cal.select(SERVO_M2, config=cal.CalibrationConfig(level="10x"))
    assert "recovery at 10x fails" in _reason(at_10x.dropped, "servo.dynamics_regression")


def test_a_rigs_own_routine_keeps_its_place_whatever_its_ids_catalog_grade():
    """A rig's routine is its implementation: the grade on its id was measured on another rig (the black-box rule, 2026-11-11)."""
    cal = _calibration()
    failing_id = FakeRoutine("servo.stock_quasistatic", ("can11.frictionloss_nm", "can11.damping_nm_s_rad"))
    assert _grade(failing_id.id, "1x") == 2
    planned = cal.plan(rig_twin(failing_id))
    assert planned.ids == (failing_id.id,), planned.summary()
    assert not planned.dropped, planned.dropped


def test_every_type_and_model_follows_the_gates_at_every_level():
    """Against an oracle built from the cards and the one recovery reader, never from select() itself: no planned fit is graded failing;
    every implemented fit graded failing that a model offers says so; with no equipment, nothing planned (fit or setup) needs any; and no
    why claims a routine is ranked ahead of one that ranks better."""
    cal = _calibration()
    from sim2real.calibration.options import routine_rank  # noqa: PLC0415
    from sim2real.cards import domain as dm  # noqa: PLC0415

    reg = _reg()
    status = {r.id: r.status for r in reg.ROUTINES}
    kind = {r.id: r.kind for r in reg.ROUTINES}
    table = dm.parameter_routines()
    checked = 0
    for tid in dm.TYPE_ORDER:
        type_id = dm.entity_type(tid).id
        for model in dm.entity_type(tid).models:
            names = tuple(dm.model(tid, model.id).parameters)
            offered = {rid for n in names for rid in table.get(type_id, {}).get(n, [])}
            for level in LEVELS:
                sel = cal.select({"x": (tid, model.id)}, config=cal.CalibrationConfig(level=level))
                where = f"{tid} {model.id} at {level}"
                for rid in sel.routines:
                    assert not (kind[rid] == "identify" and _grade(rid, level) == 2), f"{where}: {rid} is planned but graded failing"
                reasons = dict(sel.dropped)
                for rid in offered:
                    if status[rid] != "not implemented" and kind[rid] == "identify" and _grade(rid, level) == 2:
                        assert f"recovery at {level} fails" in reasons.get(rid, ""), f"{where}: {rid}: {reasons.get(rid)!r}"
                for rid in sel.routines:
                    why = sel.why[rid]
                    if "ranked ahead of " in why:
                        tail = why.split("ranked ahead of ", 1)[1].split(";", 1)[0]
                        for other in (s.strip() for s in tail.split(",") if s.strip()):
                            assert routine_rank(other, level) > routine_rank(rid, level), (
                                f"{where}: {rid}'s why says it is ranked ahead of {other}, which ranks better")
                bare = cal.select({"x": (tid, model.id)}, config=cal.CalibrationConfig(level=level, budget=cal.Budget(equipment=())))
                for rid in tuple(bare.routines) + tuple(bare.setup):
                    assert not _needs(rid), f"{where}: {rid} is planned with no equipment at hand but needs {_needs(rid)}"
                checked += 1
    assert checked > 100, checked


def test_a_why_names_a_better_ranked_alternative_honestly():
    """Today the clamp's why says it is "ranked ahead of" the camera routine, which ranks better. The clamp stays planned (it is the
    only route to the gear stiffness and the minimal cover keeps it), but its why must say the truth about the camera routine."""
    cal = _calibration()
    from sim2real.calibration.options import routine_rank  # noqa: PLC0415

    assert routine_rank("servo.backlash_reversals_camera", "1x") < routine_rank("servo.backlash_clamp", "1x")
    sel = cal.select(SERVO_M4)
    assert "servo.backlash_clamp" in sel.routines, sel.why
    why = sel.why["servo.backlash_clamp"]
    tail = why.split("ranked ahead of ", 1)[1].split(";", 1)[0] if "ranked ahead of " in why else ""
    assert "servo.backlash_reversals_camera" not in tail, why
    assert "servo.backlash_reversals_camera" in why, f"the better-ranked alternative is named, not hidden: {why}"


# --- docs and the real pendulum ------------------------------------------------------------------------------------------------------------


def test_the_inventory_and_the_gates_are_documented_for_readers():
    text = (REPO / "docs" / "CALIBRATE.md").read_text()
    assert any("`equipment`" in line and "budget" in line.lower() for line in text.splitlines()), "the budget table names `equipment`"
    assert "never planned" in text and "recovery at" in text


def test_the_can11_pendulum_keeps_its_schedule_with_the_racks_camera_and_loses_the_gap_step_without_it():
    if os.environ.get("SIM2REAL_REQUIRE_RACK") == "1":
        import bam_rack_twin  # noqa: F401, PLC0415
    else:
        pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv")
    import sim2real  # noqa: PLC0415

    cal = _calibration()
    twin = sim2real.examples.pendulum_can11(workers=2)  # the powered rig's cap: at most 2 workers beside the arm
    shipped = cal.plan(twin).ids
    assert "servo.backlash_reversals_camera" in shipped and "servo.dynamics_regression" in shipped, shipped
    kit = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(equipment=("camera_tags",))))
    assert kit.ids == shipped, kit.summary()
    bare = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(equipment=())))
    assert "servo.backlash_reversals_camera" not in bare.ids and "servo.dynamics_regression" in bare.ids, bare.summary()
    assert "camera_tags" in _reason(bare.dropped, "servo.backlash_reversals_camera")
    uncovered = {f"{i}.{n}": w for i, n, w in bare.uncovered}
    assert "camera_tags" in uncovered.get("can11.backlash_rad", ""), uncovered
