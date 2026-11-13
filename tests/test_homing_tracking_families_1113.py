"""The W&B tracker reads a results file whose starts come in families (pass 7, 2026-11-13).

WHY: pass7_rung writes ``starts`` as {family: [start, ...]} (the recovery rows run pass 4's 16 recovery starts, the real-lane rows pass 6's
real-lane family); tracking.homing.records indexed it as one list and crashed ("string indices must be integers") logging pass 7.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("coal", reason="bench.expand needs robot_models' contact extra")

PASS7 = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "homing_fivebar_mujoco_pass7_2026-11-13.json"


@pytest.mark.skipif(not PASS7.is_file(), reason="the pass-7 results file is not in this checkout")
def test_records_take_each_rows_own_start_family():
    from sim2real.tracking.homing import records

    results = json.loads(PASS7.read_text())
    assert isinstance(results["starts"], dict)
    out = records(results)
    assert out
    family = {r["row"]: r["starts"] for r in results["rows"]}
    for record in out:
        row = record["config"]["procedure"].split(" · ")[0]
        names = [s["name"] for s in results["starts"][family[row]]]
        assert record["config"]["start_names"] == names and record["config"]["starts"] == len(names) == 16


def test_a_flat_start_list_still_reads():
    from sim2real.tracking.homing import start_rows_for

    results = {"starts": [{"name": "a"}, {"name": "b"}]}
    assert [s["name"] for s in start_rows_for(results, "x · y")] == ["a", "b"]
