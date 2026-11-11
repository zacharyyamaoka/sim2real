"""sim2real.result: the calibration page's roll-up rules, on a synthetic tree (no archive, no browser).

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_result.py
"""

from __future__ import annotations

import json

from sim2real.result import CalibrationResult, Node, verdict_of


def errors(after: float, before: float, runs: int = 3) -> list[dict]:
    rows = []
    for k in range(runs):
        rows.append({"run": f"r{k}", "stage": "before", "held_out": True, "sim_real_deg": before, "target_real_deg": 1.0, "phase": "before"})
        rows.append({"run": f"r{k}", "stage": "after", "held_out": True, "sim_real_deg": after, "target_real_deg": 1.0, "phase": "after"})
    return rows


def tree(tool_gate: str | None) -> CalibrationResult:
    root = Node("d", "deployment", "deployment")
    arm = Node("d/arm", "arm", "arm", parent="d")
    j1 = Node("d/arm/j1", "joint 1", "joint", parent="d/arm", floor_deg=0.2, errors=errors(0.2, 0.5))      # 1.0x: twinned
    j2 = Node("d/arm/j2", "joint 2", "joint", parent="d/arm", floor_deg=0.1, errors=errors(0.25, 0.6))     # 2.5x: close
    nodes = [root, arm, j1, j2]
    if tool_gate:
        nodes.append(Node("d/arm/tool", "tool", "tool", parent="d/arm", gate={"gate_mm": 5.0, "sim_real_mm": 9.0, "verdict": tool_gate}))
    return CalibrationResult("t", "T", ["before", "after"], nodes, source="synthetic")


def test_the_ruler_bands():
    assert [verdict_of(r) for r in (1.5, 1.51, 3.0, 3.1, None)] == ["twinned", "close", "close", "not twinned", "no data"]


def test_a_parent_is_its_worst_child_and_keeps_the_worst_ratio():
    v = tree(None).verdicts()
    assert (v["d/arm/j1"]["verdict"], v["d/arm/j2"]["verdict"]) == ("twinned", "close")
    assert v["d"]["verdict"] == "close" and v["d"]["ratio"] == 2.5
    assert v["d/arm/j1"]["sim_real_before_deg"] == 0.5  # before = the first twin, after = the last


def test_a_failed_tool_gate_fails_every_level_above_it_even_with_twinned_joints():
    v = tree("fail (sim→real p95 at stops ≤ 5 mm)").verdicts()
    assert v["d/arm/tool"]["verdict"] == "gate fail"
    assert v["d/arm"]["verdict"] == v["d"]["verdict"] == "gate fail"


def test_picking_a_level_pools_its_subtree(tmp_path):
    result = tree(None)
    tables = result.tables()
    arm_runs = [r for r in tables["errors"] if r["node"] == "d/arm"]
    assert len(arm_runs) == len(result.node("d/arm/j1").errors) + len(result.node("d/arm/j2").errors)
    trend = {(r["node"], r["stage"], r["scope"]): r["median_deg"] for r in tables["error_stats"]}
    assert trend[("d/arm/j1", "after", "held out")] == 0.2
    index = result.write(tmp_path / "page")
    assert index.exists() and (tmp_path / "page" / "views.base").exists()
    assert json.loads((tmp_path / "page" / "data" / "nodes.json").read_text())["rows"][0]["node"] == "d"
