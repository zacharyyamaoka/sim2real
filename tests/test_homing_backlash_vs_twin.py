"""The vs-twin backlash score (2026-11-13): pass 4's ``calibration.twin_gap_deg`` recovered the hidden gaps within 1 arcmin, yet
``scorecards_vs_twin`` for press_reverse+gff recorded backlash_error 0.123 deg and a failed backlash gate on B0, B1 and B2. The vs-twin
row swapped each joint's ZERO for the one against the twin's own contacts but kept the GAP identified against CAD's stop span, so the
twin scorecard graded a CAD-referenced gap (J1: truth + the 0.1232 deg span error) against the hidden truth. Pure tests: no MuJoCo.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_backlash_vs_twin.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from robot_models.homing.metrics import backlash_gate_deg, scorecard  # noqa: E402
from robot_models.homing.types import (  # noqa: E402
    BacklashModel,
    BacklashTable,
    HomingResult,
    JointBacklash,
    JointZero,
    StopMap,
)

from sim2real.sim.homing.bench import compact, expand  # noqa: E402
from sim2real.sim.homing.geometry import C1, DRIVES, J1, J2, ROLE  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data"
PASS4 = DATA / "homing_fivebar_mujoco_pass4_2026-11-12.json"
ROW = "recover_first+press_reverse+gff"

# pass 4's B1 bowl episode, as stored: J1's CAD-referenced gap is the hidden 3.5' plus the 0.1232 deg span error
B1_RECORD = {
    "procedure": ROW, "environment": "mujoco · B1", "start": "bowl", "finished": True, "outcome": "done", "time_s": 165.67, "stalls": [],
    "joints": [{"joint": J1, "zero_error_deg": 0.0, "gap_identified_deg": 0.1816138, "gap_truth_deg": 3.5 / 60.0},
               {"joint": J2, "zero_error_deg": 0.1437404, "gap_identified_deg": 0.0, "gap_truth_deg": 2.5 / 60.0},
               {"joint": C1, "zero_error_deg": -0.0004017, "gap_identified_deg": 0.0604857, "gap_truth_deg": 4.0 / 60.0}],
}
B1_NOTE = {"zero_error_vs_twin_deg": {"J1": 0.0, "J2": -0.0002542, "C1": 0.0017595},
           "gap_identified_vs_twin_deg": {"J1": 0.0584031, "J2": 0.0410212, "C1": 0.0636859}}


def test_the_vs_twin_row_scores_the_gap_against_the_twin_too():
    from sim2real.sim.homing.mujoco_bench import vs_twin_row  # noqa: PLC0415

    row = vs_twin_row(B1_RECORD, B1_NOTE)
    gaps = {j["joint"]: j["gap_identified_deg"] for j in row["joints"]}
    assert gaps == {J1: 0.0584031, J2: 0.0410212, C1: 0.0636859}
    card = scorecard([expand(compact(row), ROW, "mujoco · B1")], gate_deg=0.1)
    assert card["backlash_error_deg"] == pytest.approx(abs(0.0636859 - 4.0 / 60.0))
    assert card["backlash_gate_pass"] is True
    # the CAD row is untouched: its gap is still CAD's, and still fails the same (unchanged) gate
    cad = scorecard([expand(compact(B1_RECORD), ROW, "mujoco · B1")], gate_deg=0.1)
    assert cad["backlash_gate_pass"] is False and cad["backlash_error_deg"] == pytest.approx(0.1816138 - 3.5 / 60.0)


def test_a_vs_twin_row_never_borrows_the_cad_gap():
    from sim2real.sim.homing.mujoco_bench import vs_twin_row  # noqa: PLC0415

    row = vs_twin_row(B1_RECORD, {"zero_error_vs_twin_deg": B1_NOTE["zero_error_vs_twin_deg"]})  # an older note: no twin gaps
    assert all(j["gap_identified_deg"] is None for j in row["joints"])  # unscored ('-'), never CAD's gap under the twin's name


def test_the_twin_note_carries_each_observable_gap_and_zero():
    from sim2real.sim.homing.mujoco_bench import twin_note  # noqa: PLC0415

    gap = {J1: math.radians(0.0584031), J2: math.radians(0.0410212), C1: 0.0}
    table = BacklashTable(tuple(JointBacklash(j, BacklashModel("B1", gap[j]), gap_observable=(j != C1)) for j in DRIVES))
    zeros = tuple(JointZero(j, 1.0 + 0.001 * i, 0.0, 4, (-1, 1)) for i, j in enumerate(DRIVES))
    result = HomingResult(zeros, table, StopMap(()), (), "mujoco")
    note = twin_note(result, {j: 1.0 for j in DRIVES})
    assert note["zero_error_vs_twin_deg"] == pytest.approx({ROLE[j]: math.degrees(0.001 * i) for i, j in enumerate(DRIVES)})
    assert note["gap_identified_vs_twin_deg"] == pytest.approx({"J1": 0.0584031, "J2": 0.0410212, "C1": None}, abs=1e-12)


def test_the_twin_gap_is_the_cad_gap_moved_by_the_span_difference():
    """The re-score's arithmetic, checked on pass 4's calibration run, which stored both tables: the gap is the motor's travel between
    the stops minus the stop span, so against another stop map it moves by exactly (CAD span - twin span); a gap CAD clipped at 0
    (J2: CAD's span is 0.283 deg too long) cannot be recovered from the row and is None."""
    from sim2real.sim.homing.mujoco_bench import rescore_gap_vs_twin, span_shift_deg  # noqa: PLC0415

    if not PASS4.is_file():
        pytest.skip(f"no pass-4 results: {PASS4}")
    results = json.loads(PASS4.read_text())
    shift = span_shift_deg(results["twin_contacts_deg"])
    assert shift["J1"] == pytest.approx(-0.1232107, abs=1e-6) and shift["J2"] == pytest.approx(0.2832749, abs=1e-6)
    for model in ("B1", "B2"):
        cal = results["calibration"][model]
        for joint in (J1, C1):
            assert rescore_gap_vs_twin(cal["gap_deg"][joint], shift[ROLE[joint]]) == pytest.approx(cal["twin_gap_deg"][joint], abs=1e-9)
        assert cal["gap_deg"][J2] == 0.0 and rescore_gap_vs_twin(0.0, shift["J2"]) is None


def test_the_hidden_truth_the_twin_gaps_are_judged_against_is_a_full_gap_in_degrees():
    """The oracle: the plant's hidden gaps (HIDDEN_GAP_ARCMIN, full mesh play) are what each row's gap_truth_deg carries, in degrees, and
    the gate is max(1', 25 %) of that - unchanged."""
    from sim2real.sim.homing.plant import HIDDEN_GAP_ARCMIN  # noqa: PLC0415

    if not PASS4.is_file():
        pytest.skip(f"no pass-4 results: {PASS4}")
    results = json.loads(PASS4.read_text())
    for model, truth_scale in (("B0", 0.0), ("B1", 1.0), ("B2", 1.0)):
        for row in results["episodes"][model][ROW]:
            truth = {j[0]: j[3] for j in row[5]}
            assert truth == pytest.approx({j: truth_scale * HIDDEN_GAP_ARCMIN[j] / 60.0 for j in DRIVES}, abs=1e-7)
    assert backlash_gate_deg(3.5 / 60.0) == pytest.approx(1.0 / 60.0) and backlash_gate_deg(0.0) == pytest.approx(1.0 / 60.0)
