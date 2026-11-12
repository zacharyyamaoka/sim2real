"""The frozen contract every PEP 0001 lane builds on, committed GREEN by the designer before any lane starts (no lane may edit it):

- the routine catalog's dependency fields (cards/schema.py CalibrationRoutine.requires / uses / refines, by parameter or setting NAME);
- the one recovery reader both the planner and the docs site use (sim2real.calibration.recovery) and its ladder-file format.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_calibration_contract.py
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from sim2real.calibration import recovery as rec
from sim2real.cards import calibration as cat
from sim2real.cards import schema

REPO = Path(__file__).resolve().parents[1]


def test_dependency_fields_are_additive_name_tuples_that_default_empty():
    names = [f.name for f in dataclasses.fields(schema.CalibrationRoutine)]
    assert names[-3:] == ["requires", "uses", "refines"], "appended after configures: additive (cards/CONTRACT.md)"
    for r in cat.ROUTINES:
        for field in ("requires", "uses", "refines"):
            value = getattr(r, field)
            assert isinstance(value, tuple) and all(isinstance(n, str) and n and "." not in n for n in value), (r.id, field, value)
        assert not set(r.requires) & set(r.uses), f"{r.id}: a name is either a hard or a soft dependency"


def test_the_wrist_routines_declare_what_their_code_reads():
    """Read off sysid/examples/ur_wrist_test_rig/rig.py: what each routine's runs() and fit() take from `values` (a hard edge when the
    value must be found first, soft when the prior serves), and DelayScan starting from the delay Dynamics sets provisionally."""
    by_id = {r.id: r for r in cat.ROUTINES}
    assert by_id["servo.backlash_reversal_held"].requires == () and "static_friction_nm" in by_id["servo.backlash_reversal_held"].uses
    assert by_id["servo.breakaway_two_sided"].requires == ("backlash_rad",)
    assert by_id["homing.single_touch"].requires == ("backlash_rad",)
    assert set(by_id["servo.dynamics_regression"].requires) == {"zero_offset_rad", "static_friction_nm"}
    assert set(by_id["arm.gravity_direction"].requires) == {"gravity_nm", "gravity_bottom_rad"}
    assert by_id["servo.command_delay_scan"].requires == ("zero_offset_rad",)
    assert by_id["servo.command_delay_scan"].refines == ("command_delay_s",)


def test_the_kinds_run_configure_fit_tune_measure():
    """Zach, 2026-11-12: "configure -> fit -> tune -> measure". The catalog keeps its word "identify" for fit (no export changes)."""
    assert schema.KIND_STAGE[:4] == ("configure", "identify", "tune", "measure")
    assert set(schema.KIND_STAGE) == set(schema.ROUTINE_KINDS) == set(schema.KIND_WORDS)
    assert schema.KIND_WORDS["identify"] == "fit" and "tune" in schema.ROUTINE_KINDS
    assert all(r.kind in schema.ROUTINE_KINDS for r in cat.ROUTINES)


def test_recovery_reads_the_sysid_table_and_unknown_stays_none():
    table = json.loads((REPO / "sysid" / "results" / "calibration_routines.json").read_text())
    row = next(r for r in table["rows"] if r["routine"] == "servo.dynamics_regression")
    assert rec.recovery("servo.dynamics_regression", "1x") == row["recovery"]["1x"]
    assert rec.recovery("servo.dynamometer", "1x") is None, "not implemented: nobody graded it"
    assert rec.source("servo.dynamics_regression") == "sysid/results/calibration_routines.json"
    with pytest.raises(ValueError):
        rec.recovery("servo.dynamics_regression", "2x")


def test_a_ladder_file_grades_a_routine_and_wins_over_the_table(tmp_path):
    (tmp_path / "sysid" / "results" / "routine_ladders").mkdir(parents=True)
    (tmp_path / "sysid" / "results" / "calibration_routines.json").write_text(json.dumps(
        {"rows": [{"routine": "a.b", "recovery": {"1x": {"pass": False, "worst_error_over_tolerance": 3.0}}}]}))
    (tmp_path / "sysid" / "results" / "routine_ladders" / "a.b.json").write_text(json.dumps(
        {"schema": rec.LADDER_SCHEMA, "routine": "a.b", "generated_by": "tests/x.py",
         "levels": {"0x": {"pass": True, "worst_error_over_tolerance": 0.0}, "1x": {"pass": True, "worst_error_over_tolerance": 0.4}}}))
    root = str(tmp_path)
    assert rec.recovery("a.b", "1x", root=root)["worst_error_over_tolerance"] == 0.4
    assert rec.recovery("a.b", "10x", root=root) is None
    assert rec.source("a.b", root=root) == "sysid/results/routine_ladders/a.b.json"
    (tmp_path / "sysid" / "results" / "routine_ladders" / "bad.json").write_text(json.dumps({"schema": "other/1", "routine": "c"}))
    rec.ladders.cache_clear()
    with pytest.raises(ValueError, match="schema"):
        rec.ladders(root + "/")
