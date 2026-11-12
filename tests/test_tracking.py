"""sim2real.tracking: the curriculum rungs and the W&B records, on a synthetic tree (no archive, no wandb, no network).

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_tracking.py
"""

from __future__ import annotations

import subprocess
import sys

from sim2real.result import QUESTIONS, CalibrationResult, Node
from sim2real.tracking import curriculum
from sim2real.tracking.wandb_log import _table_rows, digest, percentages, records, worst_ratio


def answers(**own: str) -> dict:
    return {q: {"own": own.get(q.lower(), "yes"), "numbers": f"{q} numbers", "gate": f"{q} gate"} for q in QUESTIONS}


def errors(before: float, after: float) -> list[dict]:
    rows = []
    for k in range(3):
        rows.append({"run": f"r{k}", "stage": "nominal", "held_out": True, "sim_real_deg": before, "target_real_deg": 1.0, "phase": "before"})
        rows.append({"run": f"r{k}", "stage": "refit", "held_out": True, "sim_real_deg": after, "target_real_deg": 1.0, "phase": "after"})
    return rows


def tree(j2: dict | None = None, j2_after: float = 0.25) -> CalibrationResult:
    floors = [{"kind": "tape-a (driven)", "mode": "driven", "floor_deg": 0.1, "pairs": 10, "runs": 5, "known": True, "twin_deg": 0.12,
               "twin_over_floor": 1.2, "verdict": "twinned", "source": "synthetic"}]
    data = {**answers(), "Data": {"own": "yes", "numbers": "45.7 % of 1716 reachable (q, qd, qdd) cells visited by 9 real samples", "gate": "g"}}
    return CalibrationResult("rig-2026-11-11", "Rig", ["nominal", "refit"], [
        Node("rig", "the rig", "deployment", "Deployment", questions=answers()),
        Node("rig/arm", "the arm", "arm", "robot arm", parent="rig", questions=answers()),
        Node("rig/arm/j1", "CAN 11 joint", "joint", "integrated_servo", parent="rig/arm", floor_deg=0.2, twin_ratio=1.1,
             errors=errors(0.5, 0.2), questions=data),
        Node("rig/arm/j2", "CAN 12 joint", "joint", "integrated_servo", parent="rig/arm", floor_deg=0.1, twin_ratio=1.2, floors=floors,
             errors=errors(0.6, j2_after), questions=j2 or data),
        Node("rig/arm/tool", "the tool", "tool", "Tool (payload + TCP)", parent="rig/arm", questions=answers(floor="no")),
    ], source="synthetic")


def test_importing_the_logger_never_imports_wandb():
    code = "import sys, sim2real.tracking.wandb_log; print('wandb' in sys.modules, 'wandb_workspaces' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["False", "False"]


def test_one_run_per_node_per_twin_iteration_with_stable_unique_ids():
    first, again = records(tree(), sha="abc"), records(tree(), sha="abc")
    assert len(first) == 5 * 2
    assert [r["id"] for r in first] == [r["id"] for r in again]
    assert len({r["id"] for r in first}) == len(first)
    # the content id: new numbers are a new evaluation (new runs), the same numbers the same one
    assert {r["config"]["evaluation"] for r in records(tree(j2_after=0.3))} != {first[0]["config"]["evaluation"]}


def test_every_run_carries_the_filterable_config():
    for record in records(tree(), extra_config={"rig": "test rack"}):
        config = record["config"]
        for key in ("type", "level", "deployment", "node", "instance", "twin_iteration", "iteration", "stage_role", "evaluation",
                    "evaluation_state", "result_id", "rig"):
            assert key in config, key
    by_node = {r["config"]["node"]: r["config"] for r in records(tree()) if r["config"]["stage_role"] == "after"}
    # a description word ("robot arm", "Tool (payload + TCP)") falls back to the sim2real type id of its level
    assert {n: c["type"] for n, c in by_node.items()} == {"rig": "deployment", "rig/arm": "rigid_body_chain",
                                                         "rig/arm/j1": "integrated_servo", "rig/arm/j2": "integrated_servo",
                                                         "rig/arm/tool": "tool"}
    assert by_node["rig/arm/j2"]["can_id"] == 12 and by_node["rig/arm/j2"]["floor_kind"] == "tape-a (driven)"


def test_the_last_iteration_carries_the_tree_s_own_answers_and_numbers():
    result = tree(j2=answers(twin="no", data="partial"))
    verdicts = result.verdicts()
    after = {r["config"]["node"]: r for r in records(result) if r["config"]["stage_role"] == "after"}
    j2 = after["rig/arm/j2"]
    assert j2["summary"]["verdict"] == verdicts["rig/arm/j2"]["verdict"] == "stops at Data"
    assert j2["summary"]["Twin/own"] == "no"
    last = j2["history"][-1]
    assert last["questions_passed"] == 1 and last["Floor/pass"] == 1 and last["Data/pass"] == 0
    # nothing recomputed: the ratio and floor are the node's own, the medians the verdict's
    assert last["Twin/ratio"] == 1.2 and last["Floor/floor_deg"] == 0.1 and last["Floor/pairs"] == 10
    assert last["Twin/sim_real_after_deg"] == verdicts["rig/arm/j2"]["sim_real_deg"]
    # the parent passes nothing a child does not: the deployment's verdict is the child's first "no"
    assert after["rig"]["summary"]["verdict"] == "stops at Floor"    # the tool's Floor is "no"
    assert set(after["rig"]["tables"]) >= {"tree", "questions_all", "curriculum_all", "trend_all", "questions", "curriculum"}


def test_the_trend_is_the_result_s_own_error_table_one_step_per_iteration():
    result = tree()
    stats = {(r["node"], r["stage"]): r["median_deg"] for r in result.tables()["error_stats"] if r["scope"] == "held out"}
    after = next(r for r in records(result) if r["config"]["node"] == "rig/arm/j2" and r["config"]["stage_role"] == "after")
    assert [step["iteration"] for step in after["history"]] == [0, 1]
    assert [step["trend/heldout_median_deg"] for step in after["history"]] == [stats[("rig/arm/j2", "nominal")], stats[("rig/arm/j2", "refit")]]
    before = next(r for r in records(result) if r["config"]["node"] == "rig/arm/j2" and r["config"]["stage_role"] == "before")
    assert before["history"] == [after["history"][0]] and before["tables"] == {}


def test_coverage_numbers_are_read_from_the_answer_s_own_text():
    assert percentages("45.7 % of 1716 reachable (q, qd, qdd) cells visited by 97710 real samples") == \
        {"coverage_pct": 45.7, "reachable_cells": 1716}
    assert percentages("joint cube 100.0 % of allowed (≥ 90 %); workspace 60.5 % of allowed (≥ 50 %); facing 100.0 % of allowed (≥ 90 %)") == \
        {"cube_pct": 100.0, "workspace_pct": 60.5, "facing_pct": 100.0}
    assert percentages("joint cube 100.0 % of allowed (≥ 90 %); workspace (2 cm tool pixels) 85.4 % of allowed (≥ 50 %); "
                       "heading (15°, for facing) 100.0 % of allowed (≥ 90 %)") == {"cube_pct": 100.0, "workspace_pct": 85.4, "heading_pct": 100.0}
    assert percentages("physical runs: 407") == {}
    assert worst_ratio("full_ff: after twin 4.3 mm vs tool floor 1.7 mm = 2.6×; gravity_ff: after twin 4.1 mm vs tool floor 1.3 mm = 3.1×") == 3.1
    after = {r["config"]["node"]: r for r in records(tree()) if r["config"]["stage_role"] == "after"}
    assert after["rig/arm/j1"]["history"][-1]["Data/coverage_pct"] == 45.7


def test_a_rung_passes_exactly_when_its_question_passes():
    result = tree(j2=answers(routines="partial", twin="no"))
    rows = curriculum.status(result)
    verdicts = result.verdicts()
    for row in rows:
        if row["question"]:
            assert (row["status"] == "passed") == verdicts[row["node"]]["answers"][row["question"]]["passes"], row
        else:
            assert row["status"] == "passed"   # S0: in the description
    assert [r["rung"] for r in rows if r["node"] == "rig/arm/tool"] == ["T0", "T1", "T2", "T3", "T4", "T5"]
    assert curriculum.next_rung(rows, "rig/arm/j2") == "S1"            # work order: Routines first
    assert curriculum.next_rung(rows, "rig/arm/j1") is None
    assert curriculum.next_rung(rows, "rig/arm") == "A1"               # its own answers are yes; a child holds Routines back
    assert next(r for r in rows if r["node"] == "rig/arm" and r["rung"] == "A1")["status"] == "child"
    assert curriculum.compact(rows, "rig/arm/j2") == "S0 ✓ · S1 ~ · S2 ✓ · S3 ✓ · S4 ✗ · S5 ✓"


def test_every_ladder_reads_the_five_questions_once_in_work_order():
    for ladder in curriculum.LADDERS.values():
        assert [r.question for r in ladder] == [None, "Routines", "Floor", "Data", "Twin", "Job"]
        assert set(QUESTIONS) == {r.question for r in ladder if r.question}


def test_a_table_column_has_one_type():
    columns, data = _table_rows([{"a": 1, "b": "x"}, {"a": 2.5, "b": 3}, {"a": None, "c": True}])
    assert columns == ["a", "b", "c"]
    assert data == [[1.0, "x", None], [2.5, "3", None], [None, None, True]]


def test_the_evaluation_id_follows_the_numbers_the_page_shows():
    def of(result):
        return digest(result, result.tables())

    assert of(tree()) == of(tree())
    assert of(tree(j2_after=0.25000001)) == of(tree())     # below the page's rounding: the same evaluation
    assert of(tree(j2_after=0.3)) != of(tree())            # a shown number moved: a new one
