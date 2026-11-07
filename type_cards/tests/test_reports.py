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


# --- a report from a selection, from the build CLI (2026-11-07, the metrics lane) --------------------------------------------------
# The brief: "Create a report from the build CLI from a selection, for example python -m type_cards.report freeze --name ... --runs ...".
# The definition stays a Python record, one per file (Zach's ground truth); the CLI writes it from the selection, then freezes it. The
# snapshot also keeps the rows it froze (inputs.rows), so its page shows them as they were, whatever runs.json says later.

def test_runs_are_selected_by_id_by_column_or_by_preset():
    assert rep.select_runs(RUNS, runs=["r3", "r1"]) == ["r1", "r3"]
    assert rep.select_runs(RUNS, select=["device=A"]) == ["r1", "r2", "r3"]
    assert rep.select_runs(RUNS, select=["device=A", "split=held_out,train"]) == ["r1", "r2", "r3"]
    assert rep.select_runs(RUNS, select=["device=A", "split=held_out"]) == ["r2", "r3"]
    assert rep.select_runs(RUNS, preset="split: held_out") == ["r2", "r3", "r4"]
    with pytest.raises(ValueError):
        rep.select_runs(RUNS, select=["nope=1"])     # a column no run has is a typo, never an empty report
    with pytest.raises(ValueError):
        rep.select_runs(RUNS, preset="split: nope")
    with pytest.raises(ValueError):
        rep.select_runs(RUNS, runs=["r1"], select=["device=A"])   # one way to name the rows


def test_a_new_report_refuses_a_run_id_the_data_does_not_hold(tmp_path, monkeypatch):
    """The v3 audit (2026-11-07, finding 9): `--runs typo` passed the empty-selection check and froze a report of one declared run, none
    evaluated, whose digest verified. A new report's runs are runs the data holds: an id it does not hold is refused, the whole selection
    (never the typo silently dropped), before anything is written. Re-freezing an existing definition still freezes and names its lost runs
    (test_a_frozen_report_does_not_change_as_data_grows)."""
    with pytest.raises(ValueError, match="typo"):
        rep.select_runs(RUNS, runs=["typo"])
    with pytest.raises(ValueError, match="typo"):
        rep.select_runs(RUNS, runs=["r1", "typo"])
    out = tmp_path / "frozen_reports"
    out.mkdir()
    monkeypatch.setattr(rep, "REPORTS_DIR", out)
    monkeypatch.setattr(rep, "_context", lambda data_dir, deployment: (NODES, [], tables()))
    for runs in ("typo", "r1,typo"):
        code = rep.main(["freeze", "--id", "a-typo", "--title", "A typo", "--question", "Does a typo freeze?", "--deployment", "rig",
                         "--runs", runs, "--data", str(tmp_path)])
        assert code != 0, runs
        assert sorted(p.name for p in out.iterdir()) == [], f"--runs {runs}: nothing is written"


def test_a_snapshot_freezes_the_titles_and_the_model_each_label_names():
    """The v3 audit (2026-11-07, finding 7): a report's page named its parts by today's node titles and its models by today's label map,
    so renaming a station or remapping a producer's label changed what a verified report said. The snapshot keeps both as they were when
    it froze, under its digest: the title of its deployment and of every node it computed, and for every model label in its results the
    ladder model that label named (none when nobody mapped it), read from the deployment's record unless given."""
    titled = [{**n, "title": f"title of {n['id']}"} for n in NODES]
    t = sel.Tables(nodes=titled, runs=RUNS, run_diagnostics=DIAGNOSTICS, coverage_points=COVERAGE, floors={"A": 2.0, "B": 1.0}, descriptions={"A": DESC_A})
    report = rep.Report(id="fixture-b", title="A and B", question="How do A and B do?", runs=("r1", "r2", "r4"), deployment="rig")
    named = {"twin of record": {"type": "integrated_servo", "model": "M4.dynamics.twin", "model_title": "Rack twin"}}
    snap = rep.freeze(report, t, parameter_rows=[], frozen_at="2026-11-07T00:00:00Z", code="abc1234", labels=named)
    ann = snap["annotations"]
    computed = {n["node"] for n in snap["results"]["selection"]["nodes"]}
    assert set(ann["titles"]) == computed | {"rig"} and all(ann["titles"][k] == f"title of {k}" for k in ann["titles"])
    used = {x["model"] for n in snap["results"]["selection"]["nodes"] for x in n["metrics"] + n["diagnostics"] + n["gates"] if x.get("model")}
    assert used == {"twin of record", "refit R1"} and ann["model_labels"] == {"twin of record": named["twin of record"], "refit R1": None}
    assert rep.verify(snap)
    for edit in (lambda s: s["annotations"]["titles"].__setitem__("rig/a", "renamed"),
                 lambda s: s["annotations"]["model_labels"].__setitem__("refit R1", named["twin of record"])):
        edited = copy.deepcopy(snap)
        edit(edited)
        assert not rep.verify(edited), "the digest covers what the page names"
    # unless given, a label is mapped by the deployment's record at freeze time (inst.label_model); the rack's twin of record is M4
    rack = rep.freeze(rep.Report(id="x", title="x", question="x", runs=("r1",), deployment="one-dof-test-rack"), t, parameter_rows=[],
                      frozen_at="2026-11-07T00:00:00Z", code="abc1234")
    assert rack["annotations"]["model_labels"]["twin of record"]["model"] == "M4.dynamics.twin"


def test_a_definition_is_written_as_python_and_reads_back():
    text = rep.definition_text(DEFINITION, doc="Station A over its three runs.")
    space: dict = {}
    exec(compile(text, "fixture_a.py", "exec"), space)  # noqa: S102  (the generated record, the way load_definitions imports it)
    assert space["record"] == DEFINITION
    assert text.count("\n    ") >= 5, "one keyword per line"


def test_the_snapshot_keeps_the_rows_it_froze():
    snap = rep.freeze(DEFINITION, tables(), parameter_rows=[], frozen_at="2026-11-07T00:00:00Z", code="abc1234")
    rows = snap["inputs"]["rows"]
    assert [r["run"] for r in rows] == ["r1", "r2", "r3"] and rows[0]["kind"] == "waypoints" and rows[0]["device"] == "A"
    assert set(rows[0]) <= set(rep.ROW_FIELDS)
    edited = copy.deepcopy(snap)
    edited["inputs"]["rows"][0]["kind"] = "sine"
    assert not rep.verify(edited), "the digest covers the frozen rows"


def test_the_cli_creates_and_freezes_a_report_from_a_selection(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "rig").mkdir(parents=True)
    for name, table in (("runs.json", RUNS), ("run_gates.json", DIAGNOSTICS), ("coverage.json", COVERAGE), ("gates.json", []),
                        ("devices.json", [{"device": "A"}, {"device": "B"}])):
        (data / "rig" / name).write_text(json.dumps({"rows": table}))
    out = tmp_path / "frozen_reports"
    out.mkdir()
    monkeypatch.setattr(rep, "REPORTS_DIR", out)
    monkeypatch.setattr(rep, "_context", lambda data_dir, deployment: (NODES, [], tables()))
    code = rep.main(["freeze", "--id", "a-held-out", "--title", "A, held out", "--question", "How does A do held out?", "--deployment", "rig",
                     "--select", "device=A", "--select", "split=held_out", "--models", "integrated_servo/M4.dynamics.twin", "--data", str(data)])
    assert code == 0
    snap = rep.read_snapshot(out / "a-held-out.json")
    assert rep.verify(snap) and snap["report"]["runs"] == ["r2", "r3"] and snap["results"]["selection"]["runs"] == 2
    definition = (out / "a_held_out.py").read_text()
    assert 'id="a-held-out"' in definition and "r2" in definition and "record = Report(" in definition
    # a definition already written is never overwritten: re-freezing is a new decision (freeze <id> re-freezes one on purpose)
    assert rep.main(["freeze", "--id", "a-held-out", "--title", "x", "--question", "x", "--deployment", "rig", "--runs", "r1",
                     "--data", str(data)]) != 0
    assert rep.read_snapshot(out / "a-held-out.json") == snap
