"""W&B gets summary statistics only (Zach, 2026-11-21: "to help limit W and B storage I think we need to just be using it for summary
statistics; for the media-rich things we should be using rerun!"): wandb_log.push, the writer every tracker shares, run against a strict
stand-in wandb (tests/strict_wandb.py: a Table / Image / Artifact / plot raises, a non-scalar logged value fails), and the report panels.
No network, no wandb-core.

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_wandb_summary_only.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from strict_wandb import StrictWandb
from test_tracking import tree

from sim2real.tracking import wandb_log
from sim2real.tracking.wandb_log import _clean, push, records

REPO = Path(__file__).resolve().parents[1]
# the report panels that read a W&B table or media key: none may come back (a removed key would show a stale copy)
TABLE_PANELS = ("WeavePanelSummaryTable", "MediaBrowser", "CustomChart")


def rows_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture
def strict(tmp_path, monkeypatch):
    fake = StrictWandb()
    monkeypatch.setitem(sys.modules, "wandb", fake)
    monkeypatch.setattr(wandb_log, "WANDB_DIR", tmp_path / "wandb")
    monkeypatch.setattr(wandb_log, "TABLES_DIR", tmp_path / "tables")
    return fake


def test_push_logs_scalars_and_writes_every_table_as_local_jsonl(strict, tmp_path):
    batch = records(tree(), sha="abc")
    logged = push(batch, project="Sim2Real")
    assert len(logged) == len(batch) == len(strict.runs)
    root = next(r for r in batch if r["config"]["level"] == "deployment" and r["config"]["stage_role"] == "after")
    run = next(r for r in strict.runs if r.id == root["id"])
    folder = tmp_path / "tables" / "Sim2Real" / root["id"]
    assert run.config["local_tables"] == str(folder)
    for name, rows in root["tables"].items():
        if not rows:
            assert not (folder / f"{name}.jsonl").exists() and f"rows/{name}" not in run.summary
            continue
        kept = rows_of(folder / f"{name}.jsonl")
        assert kept == json.loads(json.dumps(rows, default=str)), f"{name}: every row, as the record holds it"
        assert run.summary[f"rows/{name}"] == len(rows)
    assert {"tree", "questions_all", "curriculum_all", "trend_all", "questions", "curriculum"} <= {p.stem for p in folder.glob("*.jsonl")}
    assert not list(folder.glob("*.partial")), "written through a .partial file, then renamed"
    # the history is the record's own steps, unchanged: no table rides on the last one any more
    assert run.logged == [_clean(step) for step in root["history"]]
    assert run.summary["verdict"] == root["summary"]["verdict"]
    earlier = next(r for r in batch if r["config"]["stage_role"] == "before")
    assert "local_tables" not in next(r for r in strict.runs if r.id == earlier["id"]).config, "a run without tables names no folder"


def test_push_to_a_run_w_and_b_already_holds_patches_scalars_only(tmp_path, monkeypatch):
    batch = records(tree(), sha="abc")
    root = next(r for r in batch if r["config"]["level"] == "deployment" and r["config"]["stage_role"] == "after")
    # W&B holds the run as an old sync wrote it: its tables under their own names, one number missing
    held = {k: v for k, v in root["history"][-1].items() if k != "questions_passed"}
    held.update({"tree": {"_type": "table-file", "nrows": 5}, "questions": {"_type": "table-file", "nrows": 25}})
    fake = StrictWandb(held={root["id"]: held})
    monkeypatch.setitem(sys.modules, "wandb", fake)
    monkeypatch.setattr(wandb_log, "WANDB_DIR", tmp_path / "wandb")
    monkeypatch.setattr(wandb_log, "TABLES_DIR", tmp_path / "tables")
    (entry,) = push([root], project="Sim2Real")
    (run,) = fake.runs
    assert entry["resumed"] and run.logged == [{"questions_passed": root["history"][-1]["questions_passed"]}], "only the missing number"
    assert (tmp_path / "tables" / "Sim2Real" / root["id"] / "tree.jsonl").is_file(), "the tables are local even for a resumed run"


def test_a_record_naming_its_own_folder_keeps_its_tables_there(strict, tmp_path):
    (record,) = [r for r in records(tree(), sha="abc") if r["config"]["level"] == "tool" and r["config"]["stage_role"] == "after"]
    beside = tmp_path / "ledger" / "tables"
    record["config"]["local_tables"] = str(beside)
    push([record], project="Sim2Real")
    assert rows_of(beside / "questions.jsonl") == json.loads(json.dumps(record["tables"]["questions"], default=str))
    assert not (tmp_path / "tables").exists()


def test_no_report_panel_reads_a_table_or_media_key():
    sources = [*sorted((REPO / "src" / "sim2real" / "tracking").glob("*.py")), REPO / "tools" / "deployments_wandb.py"]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert not [name for name in TABLE_PANELS if f"wr.{name}" in text], f"{path.name} builds a panel over a W&B table or media"


def test_the_hub_views_panels_are_charts_over_scalars_and_pointers():
    wr = pytest.importorskip("wandb_workspaces.reports.v2", reason="sim2real's tracking extra")
    for slice_ in ({"by": "deployment", "levels": []}, {"by": "type", "levels": ["joint", "arm", "tool"]}):
        panels = wandb_log._panels(wr, slice_, "Sim2Real")
        kinds = {type(p).__name__ for p in panels}
        assert kinds <= {"BarPlot", "LinePlot", "MarkdownPanel"}, kinds
        pointers = [p.markdown for p in panels if type(p).__name__ == "MarkdownPanel"]
        assert pointers and all("kept off W&B" in text and "questions.jsonl" in "".join(pointers) for text in pointers)
