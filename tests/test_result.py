"""sim2real.result: the calibration page's roll-up (proposal C: five questions in order), on a synthetic tree (no archive, no browser).

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_result.py
"""

from __future__ import annotations

import json

from sim2real.result import QUESTIONS, CalibrationResult, Node, verdict_of


def answers(**own: str) -> dict:
    """Every question "yes" at this node's own output unless named."""
    return {q: {"own": own.get(q.lower(), "yes"), "numbers": f"{q} numbers", "gate": f"{q} gate"} for q in QUESTIONS}


def errors(after: float, before: float, runs: int = 3) -> list[dict]:
    rows = []
    for k in range(runs):
        rows.append({"run": f"r{k}", "stage": "before", "held_out": True, "sim_real_deg": before, "target_real_deg": 1.0, "phase": "before"})
        rows.append({"run": f"r{k}", "stage": "after", "held_out": True, "sim_real_deg": after, "target_real_deg": 1.0, "phase": "after"})
    return rows


def tree(j2: dict, arm: dict | None = None) -> CalibrationResult:
    return CalibrationResult("t", "T", ["before", "after"], [
        Node("d", "deployment", "deployment", questions=answers()),
        Node("d/arm", "arm", "arm", parent="d", questions=arm or answers()),
        Node("d/arm/j1", "joint 1", "joint", parent="d/arm", floor_deg=0.2, errors=errors(0.2, 0.5), questions=answers()),
        Node("d/arm/j2", "joint 2", "joint", parent="d/arm", floor_deg=0.1, errors=errors(0.25, 0.6), questions=j2),
    ], source="synthetic")


def test_the_twin_bands_are_unchanged():
    assert [verdict_of(r) for r in (1.5, 1.51, 3.0, 3.1, None)] == ["twinned", "close", "close", "not twinned", "no data"]


def test_all_yes_everywhere_passes_all_five():
    v = tree(answers()).verdicts()
    assert {node: x["verdict"] for node, x in v.items()} == {n: "passes all five" for n in ("d", "d/arm", "d/arm/j1", "d/arm/j2")}


def test_the_verdict_is_the_first_question_not_passed():
    v = tree(answers(twin="no", data="partial")).verdicts()
    assert v["d/arm/j2"]["verdict"] == "stops at Data" and v["d/arm/j2"]["why"] == "Data numbers"


def test_a_parent_passes_only_with_its_own_yes_and_every_child_passing():
    v = tree(answers(floor="no")).verdicts()
    assert v["d/arm/j1"]["verdict"] == "passes all five"
    # the arm says yes at its own output, but a child stops at Floor: so does the arm, and the deployment
    assert v["d/arm"]["stops_at"] == v["d"]["stops_at"] == "Floor"
    assert v["d/arm"]["why"] == "a child stops here: joint 2"
    tables = tree(answers(floor="no")).tables()
    chips = {row["node"]: row["floor"] for row in tables["nodes"]}
    assert chips == {"d": "child", "d/arm": "child", "d/arm/j1": "yes", "d/arm/j2": "no"}


def test_a_parent_failing_at_its_own_output_stops_even_when_children_pass():
    v = tree(answers(), arm=answers(job="no")).verdicts()
    assert v["d/arm"]["verdict"] == "stops at Job" and v["d/arm/j2"]["verdict"] == "passes all five"


def test_an_unanswered_question_is_unknown_and_stops():
    v = tree({q: a for q, a in answers().items() if q != "Routines"}).verdicts()
    assert v["d/arm/j2"]["answers"]["Routines"]["own"] == "unknown" and v["d/arm/j2"]["stops_at"] == "Routines"


def test_soft_numbers_still_roll_up_and_the_page_writes(tmp_path):
    result = tree(answers())
    v = result.verdicts()
    assert v["d/arm/j1"]["sim_real_before_deg"] == 0.5 and v["d/arm"]["ratio"] == 2.5   # the worst child's driven ratio
    tables = result.tables()
    assert len([r for r in tables["questions"] if r["node"] == "d/arm"]) == 5
    index = result.write(tmp_path / "page")
    assert index.exists() and (tmp_path / "page" / "views.base").exists()
    assert json.loads((tmp_path / "page" / "data" / "nodes.json").read_text())["rows"][0]["node"] == "d"
