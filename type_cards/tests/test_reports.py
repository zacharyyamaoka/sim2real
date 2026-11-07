"""Reports: a frozen, named set of rows and the results computed at freeze time (type_cards/report.py), written before it (2026-11-07).

    uv run --no-project --with pytest pytest -q /home/bam/sim2real/type_cards/tests

Zach (2026-11-06): "Now we can make a report with like a set number of rows etc. So that is how we kinda like 'freeze it' and see the
full breakdown. So even as you add more data etc.. the Reports is a great way to just see an overview fixed."

Held here:
- a report's definition is a Python record (one per file, type_cards/frozen_reports/<id>.py), its snapshot a JSON file written by
  freeze() and never edited; the snapshot's digest covers its definition and its results, so an edit shows;
- freeze() is a pure function of its inputs: the same tables give the same snapshot, and tables that grow afterwards change nothing in
  a snapshot already written (it is read, never recomputed);
- every committed snapshot verifies, its rows are its definition's, and its results are selection.compute()'s shape.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(Path(__file__).resolve().parent))  # the selection test's fixture rig

from type_cards import report as rep  # noqa: E402
from type_cards import selection as sel  # noqa: E402
from test_selection import COVERAGE, DESC_A, DIAGNOSTICS, NODES, RUNS  # noqa: E402

DEFINITION = rep.Report(id="fixture-a", title="Station A, every run", question="How does A do over its three runs?",
                        runs=("r1", "r2", "r3"), models=("integrated_servo/M4.dynamics.twin",), parameters=())


def tables(runs=RUNS):
    return sel.Tables(nodes=NODES, runs=runs, run_diagnostics=DIAGNOSTICS, coverage_points=COVERAGE, floors={"A": 2.0, "B": 1.0},
                      descriptions={"A": DESC_A})


def test_a_report_is_a_frozen_keyword_record():
    with pytest.raises(Exception):
        DEFINITION.title = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        rep.Report("positional")  # type: ignore[misc]


def test_freeze_is_pure_and_its_digest_covers_everything():
    a = rep.freeze(DEFINITION, tables(), parameter_rows=[], frozen_at="2026-11-07T00:00:00Z", code="abc1234")
    b = rep.freeze(DEFINITION, tables(), parameter_rows=[], frozen_at="2026-11-07T00:00:00Z", code="abc1234")
    assert a == b
    assert a["schema"] == rep.SCHEMA and a["report"]["id"] == "fixture-a" and a["frozen_at"] == "2026-11-07T00:00:00Z"
    assert a["results"]["selection"]["runs"] == 3
    assert rep.verify(a)
    tampered = copy.deepcopy(a)
    tampered["results"]["selection"]["nodes"][0]["metrics"][0]["value"] = 99.0
    assert not rep.verify(tampered)
    renamed = copy.deepcopy(a)
    renamed["report"]["runs"] = ["r1"]
    assert not rep.verify(renamed)


def test_a_frozen_report_does_not_change_as_data_grows(tmp_path):
    snap = rep.freeze(DEFINITION, tables(), parameter_rows=[], frozen_at="2026-11-07T00:00:00Z", code="abc1234")
    path = tmp_path / "fixture-a.json"
    rep.write_snapshot(snap, path)
    more = RUNS + [{"run": "r9", "device": "A", "kind": "sine", "samples": 100, "tracking_mrad": 50.0, "rate_hz": 10.0, "split": "held_out"}]
    _ = tables(more)  # the data grew; the snapshot is read, never recomputed
    again = rep.read_snapshot(path)
    assert again == snap and rep.verify(again)
    # and a definition that names a run the tables no longer hold still freezes, saying so
    gone = rep.freeze(rep.Report(id="g", title="g", question="g", runs=("r1", "lost"), models=(), parameters=()), tables(),
                      parameter_rows=[], frozen_at="2026-11-07T00:00:00Z", code="abc1234")
    assert gone["results"]["selection"]["unknown_runs"] == ["lost"]


def test_the_committed_reports_verify_and_match_their_definitions():
    definitions = rep.load_definitions()
    assert definitions, "at least one report is committed (type_cards/frozen_reports/)"
    for rid, d in definitions.items():
        assert d.id == rid
        snap = rep.read_snapshot(rep.REPORTS_DIR / f"{rid}.json")
        assert rep.verify(snap), rid
        assert snap["report"] == rep.plain(d), f"{rid}: the snapshot's rows are its definition's (re-freeze after editing the .py)"
        assert {"runs", "nodes", "unknown_runs"} <= set(snap["results"]["selection"])
        assert len(snap["results"]["parameters"]) == len(d.parameters)
        json.dumps(snap)
