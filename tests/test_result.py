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


# ── the Data question's angle frame (rack_results.joint_data; regression, 2026-11-11) ─────────────────────────────────────────────

def description(low_deg: float, high_deg: float) -> dict:
    import math

    return {"name": "j", "can_id": 1, "origin_rad": 0.0, "range_rad": [math.radians(low_deg), math.radians(high_deg)], "speed_rad_s": 2.0,
            "accel_rad_s2": 20.0, "torque_limit_nm": 5.0, "cap_command_nm": 5.0, "drive_torque_nm": 5.0, "gravity_nm": 0.0,
            "gravity_bottom_rad": 0.0, "coulomb_nm": 0.0, "inertia_kg_m2": 0.01, "kp_nm_rad": 10.0, "kd_nm_s_rad": 1.0,
            "integrator_scale": 0.0, "output_per_board": 1.0, "window_rad": [math.radians(low_deg), math.radians(high_deg)],
            "overspeed_rad_s": None, "rotor_rev_rad": 0.63}


def angles(*degrees: float):
    import math

    import numpy as np

    q = np.radians(np.array(degrees, float))
    return [(q, np.zeros_like(q), np.zeros_like(q))]


def visited(answer: dict) -> float:
    return float(answer["numbers"].split(" %")[0])


def test_a_range_wider_than_180_keeps_its_samples():
    from sim2real.rack_results import joint_data

    d = description(-248.0, 73.0)   # the wrist's CAN 14 from its origin
    inside = visited(joint_data(d, angles(-240, -200, -150), 0.0, "test"))
    assert inside > 0 and inside == visited(joint_data(d, angles(-240, -200, -150), 0.0, "test"))
    # -200 deg is in range: a +-180 wrap would have moved it to +160, outside, and visited one cell fewer
    assert visited(joint_data(d, angles(-200), 0.0, "test")) > 0


def test_an_angle_logged_a_turn_away_lands_in_the_range():
    from sim2real.rack_results import joint_data

    d = description(-304.0, -93.0)   # the five-bar's C1 is written -304..-93 and logged 64..255
    assert visited(joint_data(d, angles(64.0, 150.0, 255.0), 0.0, "test")) == visited(joint_data(d, angles(-296.0, -210.0, -105.0), 0.0, "test")) > 0


# ---- Twin and Job check in order (Zach 2026-11-11 21:50): target vs sim -> sim vs real -> target vs real; a camera number is a flag

from sim2real.rack_results import controller_check, order_twin_job  # noqa: E402
from sim2real.result import check, ordered_answer, with_checks  # noqa: E402


def ordered(target_sim: str, sim_real: str, target_real: str) -> dict:
    """A joint whose Twin and Job are rebuilt from three checks, as rack_results does."""
    questions = answers()
    questions["Twin"] = {"own": sim_real, "numbers": "twin ratio", "gate": "≤ 1.5× floor"}
    questions["Job"] = {"own": target_real, "numbers": "settled vs share", "gate": "≤ share"}
    order_twin_job(questions, check("target vs sim", target_sim, "sim settled"))
    return questions


def test_a_controller_failing_in_sim_reads_controller_not_twin():
    v = tree(ordered("no", "no", "no")).verdicts()
    assert v["d/arm/j2"]["verdict"] == "stops at Twin (controller)"
    assert v["d/arm/j2"]["answers"]["Job"]["cause"] == "controller"


def test_the_twin_missing_on_its_own_reads_plain_twin():
    v = tree(ordered("yes", "no", "no")).verdicts()
    assert v["d/arm/j2"]["verdict"] == "stops at Twin"
    assert v["d/arm/j2"]["answers"]["Job"]["own"] == "no" and v["d/arm/j2"]["answers"]["Job"]["cause"] == "twin"


def test_a_job_miss_after_controller_and_twin_pass_is_plain_job():
    v = tree(ordered("yes", "yes", "no")).verdicts()
    assert v["d/arm/j2"]["verdict"] == "stops at Job"


def test_the_controller_cause_is_carried_up_to_the_parent():
    v = tree(ordered("no", "yes", "yes")).verdicts()
    assert v["d/arm/j2"]["verdict"] == "stops at Twin (controller)"
    assert v["d/arm"]["verdict"] == "stops at Twin" and v["d/arm"]["why"] == "a child stops here: joint 2 (controller)"


def test_an_unmeasured_controller_never_passes_silently():
    assert ordered_answer([check("target vs sim", "unknown", ""), check("sim vs real", "yes", "")]) == ("partial", None)
    assert ordered_answer([check("target vs sim", "yes", ""), check("sim vs real", "unknown", "")]) == ("unknown", None)
    # but a later "no" still fails, with no cause blamed on the unmeasured check
    assert ordered_answer([check("target vs sim", "unknown", ""), check("sim vs real", "no", "")]) == ("no", None)


def test_the_checks_table_lists_them_in_order_and_marks_the_one_that_decides():
    rows = [r for r in tree(ordered("no", "no", "yes")).tables()["checks"] if r["node"] == "d/arm/j2"]
    assert [(r["question"], r["check"], r["decides"]) for r in rows] == [
        ("Twin", "target vs sim", "controller"), ("Twin", "sim vs real", ""),
        ("Job", "target vs sim", "controller"), ("Job", "sim vs real", ""), ("Job", "target vs real", "")]


def test_controller_check_judges_the_twin_settled_median_against_the_share():
    assert controller_check(0.33, [0.2, 0.3, 0.4], "rows")["answer"] == "yes"
    assert controller_check(0.25, [0.2, 0.3, 0.4], "rows")["answer"] == "no"
    assert controller_check(0.33, [], "rows")["answer"] == "unknown"
    assert controller_check(None, [0.1], "rows")["answer"] == "unknown"


def test_a_camera_flag_never_gates():
    job = with_checks({"own": "yes", "numbers": "", "gate": "", "flag": "camera vs FK: 20 mm"},
                      [check("target vs sim", "yes", ""), check("sim vs real", "yes", ""), check("target vs real", "yes", "0.4 mm by FK")])
    questions = answers()
    questions["Job"] = job
    v = tree(questions).verdicts()
    assert v["d/arm/j2"]["verdict"] == "passes all five"
    assert [r["flag"] for r in tree(questions).tables()["questions"] if r["node"] == "d/arm/j2" and r["question"] == "Job"] == ["camera vs FK: 20 mm"]


def test_controller_check_at_the_tool_reads_in_mm_against_the_tool_gate():
    out = controller_check(1.0, [4.2, 3.9, 4.5], "holds", unit=" mm")
    assert out["answer"] == "no" and "4.20 mm median" in out["numbers"] and "≤ 1.00 mm, the tool gate" in out["gate"]
