"""Reports: a frozen, named set of rows and what was computed over them at freeze time (type_cards/CONTRACT.md, "Domain model v3").

Zach (PROJECT - Sim2Real, 2026-11-06): "Now lets have another thing similar to RobotParts. We call Reports. Now we can make a report with
like a set number of rows etc. So that is how we kinda like 'freeze it' and see the ful lbreak down. So even as you add more data etc..
the Reports is a great way to just see an overview fixed."

A report's definition is a Python record, one per file: type_cards/frozen_reports/<id>.py (`record = Report(...)`, its rows by id). Its
snapshot, type_cards/frozen_reports/<id>.json, is written once by freeze() and never edited: the definition, the selection computed over
its runs (selection.compute), its models' records and its parameter rows as the parameters table held them, when, from which code, and a
digest over all of it. A page reads the snapshot; nothing recomputes it, so a report never changes as data grows. Re-freezing is a new
decision (a new snapshot, its own commit).

    python3 -m type_cards.report freeze <id> [--data /home/bam/sim2real/app/data]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import domain as dm
from . import selection as sel

SCHEMA = "sim2real.domain/3#report"
REPORTS_DIR = Path(__file__).resolve().parent / "frozen_reports"


@dataclass(frozen=True, kw_only=True)
class Report:
    id: str
    title: str
    question: str                         # what it answers, in a sentence
    runs: tuple[str, ...]                 # run ids (runs.json `run`)
    models: tuple[str, ...] = ()          # model keys, "<type>/<model id>"
    parameters: tuple[str, ...] = ()      # parameters table row ids (instances.parameter_table)
    deployment: str = ""
    note: str = ""


def plain(report: Report) -> dict:
    return dm.plain(report)


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(snapshot: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in snapshot.items() if k != "digest"}).encode("utf-8")).hexdigest()


def verify(snapshot: dict) -> bool:
    return snapshot.get("schema") == SCHEMA and snapshot.get("digest") == digest(snapshot)


def freeze(report: Report, tables: sel.Tables, *, parameter_rows: list[dict], frozen_at: str, code: str) -> dict:
    """The snapshot: a pure function of its inputs (frozen_at and code are passed in, never read here)."""
    selection = sel.compute(report.runs, tables, name=report.title)
    by_id = {r["id"]: r for r in parameter_rows}
    models = []
    for key in report.models:
        tid, mid = key.split("/", 1)
        models.append(dm.plain(dm.model(tid, mid)))
    used = sorted((r for r in tables.runs if r["run"] in set(selection["run_ids"])), key=lambda r: r["run"])
    snap = {"schema": SCHEMA, "report": plain(report), "frozen_at": frozen_at, "code": code,
            "inputs": {"runs_sha256": hashlib.sha256(canonical(used).encode("utf-8")).hexdigest(), "runs": len(used)},
            "results": {"selection": selection, "models": models,
                        "parameters": [by_id.get(pid) or {"id": pid, "missing": "not a row of the parameters table at freeze time"}
                                       for pid in report.parameters]}}
    snap["digest"] = digest(snap)
    return snap


def write_snapshot(snapshot: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(snapshot, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def read_snapshot(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_definitions() -> dict[str, Report]:
    out = {}
    for path in sorted(REPORTS_DIR.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        record = importlib.import_module(f"type_cards.frozen_reports.{path.stem}").record
        out[record.id] = record
    return out


def _code() -> str:
    repo = Path(__file__).resolve().parents[1]
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    # WHY the snapshots are left out: freezing writes one, which is not the code it was computed with
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", "type_cards", ":!type_cards/frozen_reports/*.json"],
                           capture_output=True, text=True).stdout.strip()
    return head + ("+dirty" if dirty else "")


def main(argv=None) -> int:
    from . import instances  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="freeze a report: python3 -m type_cards.report freeze <id>")
    parser.add_argument("action", choices=("freeze", "verify"))
    parser.add_argument("id")
    parser.add_argument("--data", type=Path, default=Path("/home/bam/sim2real/app/data"), help="the app's data (tools/build_app.py)")
    args = parser.parse_args(argv)
    path = REPORTS_DIR / f"{args.id}.json"
    if args.action == "verify":
        ok = verify(read_snapshot(path))
        print(f"{path}: {'verifies' if ok else 'DOES NOT VERIFY'}")
        return 0 if ok else 1
    report = load_definitions()[args.id]
    results = instances.load_results()
    nodes = instances.virtual_nodes(results) + instances.physical_nodes(args.data)
    routines = json.loads((instances.RESULTS / "calibration_routines.json").read_text(encoding="utf-8"))
    rows = instances.parameter_table(nodes, results, routines)["rows"]
    tables = sel.load_tables(args.data, report.deployment, nodes=[n for n in nodes if n["root"] == report.deployment]) if report.deployment else sel.Tables()
    snap = freeze(report, tables, parameter_rows=rows, frozen_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), code=_code())
    write_snapshot(snap, path)
    print(f"froze {args.id}: {snap['results']['selection']['runs']} runs, {len(snap['results']['parameters'])} parameter rows -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
