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


# ── the joint's Floor and Twin rules (rack_results.joint_questions; 2026-11-11 review, passive N/A proposed, Zach to confirm) ──

def joint(driven_floor=0.1, twin=0.12, known=True, passive=None):
    from sim2real.rack_results import joint_questions

    return joint_questions(driven={"floor_deg": driven_floor, "pairs": 10, "runs": 5, "known": known, "kind": "tape", "twin_deg": twin},
                           passive=passive or {"state": "na", "reason": "cannot move unpowered"}, before_deg=0.4, target_deg=0.3,
                           coverage_text="c", routines="r")


def test_passive_na_with_a_reason_lets_a_known_driven_floor_pass():
    q = joint()
    assert q["Floor"]["own"] == "yes" and "N/A: cannot move unpowered" in q["Floor"]["numbers"] and "Zach to confirm" in q["Floor"]["numbers"]
    assert q["Twin"]["own"] == "yes"   # 1.2x its same-kind floor, passive N/A


def test_no_passive_runs_fail_floor_and_a_passive_twin_far_off_fails_twin():
    assert joint(passive={"state": "none"})["Floor"]["own"] == "no"
    q = joint(passive={"state": "known", "floor_deg": 0.33, "twin_deg": 33.5, "note": "releases"})
    assert q["Floor"]["own"] == "yes" and q["Twin"]["own"] == "no"


def test_an_unknown_driven_floor_fails_floor_and_leaves_twin_unknown():
    q = joint(known=False)
    assert q["Floor"]["own"] == "no" and q["Twin"]["own"] == "unknown"


def test_a_twin_under_the_floor_check_fails_floor_not_passes_twin():
    q = joint(driven_floor=0.2, twin=0.1)   # 0.5x: the "repeats" were not repeats
    assert q["Floor"]["own"] == "no" and q["Twin"]["own"] == "no"
