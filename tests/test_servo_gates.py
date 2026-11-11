"""The servo acceptance gates T1-T11 as calls into sim2real.metrics, their targets as cards/ data.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_servo_gates.py

Zach, 2026-11-10 (proposal 2, step 4): "the gates T1-T11 (bam_rack_twin/acceptance.py) become calls into sim2real.metrics. Their targets
go into cards/ as data." Written before sim2real.metrics.servo_gates existed (red first).

The oracle is outside the code under test: every acceptance file the rack wrote since 2026-11-05 holds each station's facts AND the gates
bam_rack_twin's own evaluate() wrote from them; sim2real must write the same gates from the same facts, to the bit (the JSON text). The
mutation check moves one target in cards and the same facts must then grade differently, so a ruler that ignores its targets fails.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from robot_msgs.space import Value

from sim2real.cards import ladders, registry, servo_gates as cards
from sim2real.metrics import servo_gates
from sim2real.metrics.gate import at_most, rule_of

ANALYSIS = Path("/archive/datasets/bam_rig/rack_2026-10-28/analysis")
# The rack's acceptance files written by the evaluate() of record since 2026-11-05 (each re-checked 8 / 8 on 2026-11-10 before the move)
ORACLE_FILES = ("acceptance_pooled_safer_can12_warm_1105.json", "acceptance_pooled_safer_can12_t10v3_1106.json",
                "acceptance_pooled_safer_t10_pooled_1106.json", "acceptance_pooled_safer_learner_v2_1106.json",
                "acceptance_pooled_safer_otherday_1106.json", "acceptance_pooled_safer_otherday_1107.json",
                "acceptance_pooled_safer_otherday_1107b.json")
needs_archive = pytest.mark.skipif(not (ANALYSIS / ORACLE_FILES[-1]).is_file(), reason="the rack archive is not mounted")


def _written(gates) -> list[dict]:
    """The gates as the acceptance file writes them: asdict, then JSON (default=str), then read back."""

    return json.loads(json.dumps([dataclasses.asdict(gate) for gate in gates], indent=1, default=str))


def _evaluate(can: int, facts: dict, targets=cards.SERVO):
    return servo_gates.evaluate(facts, targets, allocation_mrad=cards.STOP_ALLOCATION_MRAD.get(can))


# --------------------------------------------------------------------------- the oracle: the rack's own written verdicts


@needs_archive
@pytest.mark.parametrize("name", ORACLE_FILES)
def test_every_station_grades_as_the_rack_wrote_it(name):
    document = json.loads((ANALYSIS / name).read_text(encoding="utf-8"))
    stations = {can: station for can, station in document["stations"].items() if "facts" in station}
    assert len(stations) == 8
    for can, station in stations.items():
        gates = _evaluate(int(can), station["facts"])
        assert _written(gates) == station["gates"], f"{name} CAN {can}"
        assert servo_gates.twinned(gates, cards.TYPE_GATES) == station["twinned_type"]
        assert servo_gates.twinned(gates, cards.UNIT_GATES) == station["twinned_unit"]


@needs_archive
def test_a_moved_target_grades_differently():
    document = json.loads((ANALYSIS / ORACLE_FILES[-1]).read_text(encoding="utf-8"))
    facts = document["stations"]["4"]["facts"]
    stored = {gate["id"]: gate for gate in document["stations"]["4"]["gates"]}
    assert stored["T2"]["status"] == "pass"
    tighter = dataclasses.replace(cards.SERVO, fidelity_tapes=at_most(0.5, "x floor"))
    moved = {gate.id: gate for gate in _evaluate(4, facts, tighter)}
    assert moved["T2"].status == "fail" and moved["T2"].limit == 0.5


# --------------------------------------------------------------------------- facts in, gates out (no archive)


def test_no_facts_is_not_run_everywhere_and_never_twinned():
    gates = _evaluate(11, {})
    assert [gate.id for gate in gates] == [f"T{n}" for n in range(1, 12)]
    assert {gate.status for gate in gates} == {"not_run"}
    assert not servo_gates.twinned(gates, cards.TYPE_GATES)
    # every gate carries its rule and limit even when it did not run
    by_id = {gate.id: gate for gate in gates}
    assert by_id["T2"].target == cards.GATE_RULES[1][2] and by_id["T2"].limit == 1.5 and by_id["T4"].limit == 3.6


def test_t1_t2_and_the_proxy_floor():
    facts = {"floor": {"kind": "repeats", "repeats": 5, "mrad": 2.0}, "twin_mrad": 2.9, "class_ratio": {"pickplace": 1.45, "cycle": 1.9}}
    by_id = {gate.id: gate for gate in _evaluate(11, facts)}
    assert by_id["T1"].status == "pass" and by_id["T1"].judged == [{"name": "identical repeats", "value": 5, "rule": ">=", "limit": 5, "passes": True}]
    assert by_id["T2"].status == "pass" and by_id["T2"].value == 1.45
    assert {gate.id: gate for gate in _evaluate(11, {**facts, "twin_mrad": 3.1})}["T2"].status == "fail"
    proxy = {gate.id: gate for gate in _evaluate(11, {**facts, "floor": {"kind": "proxy", "repeats": 0, "mrad": 2.0}})}
    assert proxy["T1"].status == "fail" and proxy["T2"].status == "partial"
    worst_class = {gate.id: gate for gate in _evaluate(11, {**facts, "class_ratio": {"pickplace": 1.45, "cycle": 2.1}})}
    assert worst_class["T2"].status == "fail"


def test_t4_by_side_and_the_direct_drive():
    stop = {"side": "encoder", "p90_mrad": 3.0, "n": 12}
    assert {g.id: g for g in _evaluate(11, {"stop": stop})}["T4"].status == "partial"  # within, but encoder side
    assert {g.id: g for g in _evaluate(11, {"stop": {**stop, "side": "output"}})}["T4"].status == "pass"
    assert {g.id: g for g in _evaluate(11, {"stop": {**stop, "p90_mrad": 3.7}})}["T4"].status == "fail"
    direct = {"direct_drive": True, "ratio_verified": True}
    approach = {"positive": {"n": 5, "p90_mrad": 2.0}, "negative": {"n": 4, "p90_mrad": 2.5}}
    t4 = {g.id: g for g in _evaluate(21, {"stop": {**stop, "approach": approach}, "encoder_blind": direct})}["T4"]
    assert t4.status == "partial" and "negative side 4 of 5 stops" in t4.detail
    approach["negative"]["n"] = 5
    assert {g.id: g for g in _evaluate(21, {"stop": {**stop, "approach": approach}, "encoder_blind": direct})}["T4"].status == "pass"


def test_t5_to_t11_read_their_own_targets():
    facts = {"encoder_blind": {"direct_drive": False, "ratio_verified": True, "gap_ci_half_arcmin": 1.9, "stiffness_measured": True},
             "drive_gain_error_pct": -4.9, "envelope": {"speed_error_pct": 4.0, "limits_reproduced": True},
             "thermal": {"status": "measured", "thermocouple_error_c": 5.1}, "warm_cold_ratio": 1.2, "live_reid_restores": 1.6,
             "provenance": {"terms": 9, "complete": 9, "firmware": "1.0.0", "config_hash": "abc"}}
    by_id = {gate.id: gate.status for gate in _evaluate(11, facts)}
    assert by_id == {"T1": "not_run", "T2": "not_run", "T3": "not_run", "T4": "not_run", "T5": "pass", "T6": "pass", "T7": "pass",
                     "T8": "fail", "T9": "pass", "T10": "fail", "T11": "pass"}


# --------------------------------------------------------------------------- cards: the targets are data, robot_msgs Values, one source


def test_the_targets_are_robot_msgs_values_with_ranges():
    for field in dataclasses.fields(cards.SERVO):
        if field.name == "rules":
            continue
        target = getattr(cards.SERVO, field.name)
        assert isinstance(target, Value) and (target.low is not None and target.high is not None), field.name
        assert target.source, f"{field.name} names where its number comes from"
    assert rule_of(cards.SERVO.fidelity_tapes) == ("<=", 1.5) and rule_of(cards.SERVO.floor_repeats) == (">=", 5)


def test_the_rule_text_and_allocations_are_the_racks_unchanged():
    assert cards.GATE_RULES == (
        ("T1", "floor", "the rack against itself: >= 5 identical repeats of one tape"),
        ("T2", "fidelity", "held-out twin error <= 1.5x the floor, and <= 2.0x in every dataset class"),
        ("T3", "torque", "predicted q-current within 2.0x of the run-to-run current scatter"),
        ("T4", "static accuracy", "p90 stop error at the OUTPUT within the joint's allocation of the 5 mm tool gate (a camera, an output encoder, "
                                  "or a verified direct drive's own encoder with stops from both approach directions)"),
        ("T5", "encoder-blind terms", "gear ratio verified on camera, backlash CI half-width <= 2.0 arcmin, stiffness measured"),
        ("T6", "drive gain", "known-mass torque within 5.0%"),
        ("T7", "envelope", "top speed within 5.0% and the voltage/current limits reproduced"),
        ("T8", "thermal", "winding temperature model within 5.0 degC of a thermocouple"),
        ("T9", "warm and cold", "one twin holds T2 (<= 1.5x) cold and warm"),
        ("T10", "live re-identification", "a 60 s live routine restores T2 after drift"),
        ("T11", "provenance", "every model term has a value, grade and evidence, plus firmware and config hash"),
    )
    assert cards.STOP_ALLOCATION_MRAD == {11: 3.6, 12: 3.6, 13: 3.6, 4: 6.7, 21: 6.7, 1: 10.0, 14: 10.0, 15: 10.0}
    assert cards.TYPE_GATES == ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8") and cards.UNIT_GATES == ("T1", "T2", "T5", "T6")
    assert cards.SERVO.camera_share.high == 1 / 3 and cards.SERVO.current_limiter_share.low == 0.9


def test_the_servo_cards_gates_read_the_same_targets():
    # WHY: the servo card's own gates (ladders) held T2/T3/T7/T8/T9 as literals beside acceptance's constants; one number, two places
    by_acceptance = {gate.acceptance: gate for gate in registry.SERVO.gates if gate.acceptance}
    expected = {"T2": cards.SERVO.fidelity_tapes, "T3": cards.SERVO.torque_ratio, "T9": cards.SERVO.fidelity_tapes, "T7": cards.SERVO.speed_pct,
                "T8": cards.SERVO.thermocouple_c}
    for gate_id, target in expected.items():
        assert (by_acceptance[gate_id].target.op, by_acceptance[gate_id].target.value) == rule_of(target), gate_id
    assert by_acceptance["T4"].target.value is None  # per station: STOP_ALLOCATION_MRAD


def test_schedule_targets_are_cards_data():
    assert cards.MINIMUM_COVERAGE_PCT == 40.0
    assert cards.NOTE_TARGETS == {"train_samples_per_cell": 200, "held_out_samples_per_cell": 50, "reachable_pct": 95.0,
                                  "deployment_weighted_pct": 99.0, "reversals": 50, "reversal_q_cells": 8, "stops_per_direction": 20,
                                  "stop_positions": 5, "condition_number": 20.0, "ci_half_width_pct": 20.0}
    assert ladders.GATE_PCT == cards.MINIMUM_COVERAGE_PCT  # the cards' coverage gate is the schedule's, one number
