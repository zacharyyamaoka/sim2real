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
    python3 -m type_cards.report freeze --id <id> --title "..." --question "..." --deployment <dep> (--runs a,b | --select col=v[,v] ... |
        --preset "station: CAN 11") [--models <type>/<model> ...] [--parameters <row id> ...] [--note "..."]
    python3 -m type_cards.report verify <id>
    python3 -m type_cards.report list

The second form (2026-11-07, the metrics lane) makes a report from a selection: it writes the definition, frozen_reports/<id with _>.py, from
the selected runs (by id, by runs.json columns, or by a preset of selection.presets), then freezes it. It never overwrites a report that
exists: re-freezing one is a new decision (`freeze <id>`, then its own commit). A snapshot keeps the rows it froze (inputs.rows, the
ROW_FIELDS of each run), so a report's page shows its runs as they were.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, fields
from pathlib import Path

from . import domain as dm
from . import selection as sel

SCHEMA = "sim2real.domain/3#report"
REPORTS_DIR = Path(__file__).resolve().parent / "frozen_reports"
# the runs.json columns a snapshot keeps of each run it froze (inputs.rows): what its page lists, as it was at freeze time
ROW_FIELDS = ("run", "title", "device", "day", "started", "kind", "class", "split", "mode", "round", "run_set", "session", "excitation",
              "closed_loop", "offline_scope", "config", "config_sha256", "gains", "duration_s", "samples", "rate_hz", "tracking_mrad",
              "best_model", "best_model_mrad", "verdict")
ID = re.compile(r"^[a-z][a-z0-9-]{0,80}$")


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
            "inputs": {"runs_sha256": hashlib.sha256(canonical(used).encode("utf-8")).hexdigest(), "runs": len(used),
                       "rows": [{k: r[k] for k in ROW_FIELDS if k in r} for r in used]},
            "results": {"selection": selection, "models": models,
                        "parameters": [by_id.get(pid) or {"id": pid, "missing": "not a row of the parameters table at freeze time"}
                                       for pid in report.parameters]}}
    snap["digest"] = digest(snap)
    return snap


def write_snapshot(snapshot: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(snapshot, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def read_snapshot(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_runs(rows: list[dict], *, runs=(), select=(), preset: str | None = None) -> list[str]:
    """The run ids a new report names, one way: `runs` (ids), `select` (["col=v1,v2", ...]: a run keeps when every column holds one of its
    values; a list column when any item does) or `preset` (a selection.presets name). Sorted, deduplicated. A column no run has, or a preset
    that is none, is refused: a typo must never freeze an empty report."""
    ways = [w for w in (bool(runs), bool(select), preset is not None) if w]
    if len(ways) != 1:
        raise ValueError("name the runs one way: --runs, --select or --preset")
    if runs:
        return sorted(set(runs))
    if preset is not None:
        found = sel.presets(rows)
        if preset not in found:
            raise ValueError(f"no preset {preset!r}; the presets are: {', '.join(found)}")
        return found[preset]
    columns = {k for r in rows for k in r}
    clauses = []
    for item in select:
        column, eq, values = str(item).partition("=")
        if not eq or column not in columns:
            raise ValueError(f"--select {item!r}: write column=value[,value] with a runs.json column ({', '.join(sorted(columns))[:300]} ...)")
        clauses.append((column, {v.strip() for v in values.split(",")}))

    def keep(r: dict) -> bool:
        for column, values in clauses:
            v = r.get(column)
            if not (any(str(x) in values for x in v) if isinstance(v, list) else str(v) in values):
                return False
        return True

    return sorted({r["run"] for r in rows if keep(r)})


def definition_text(report: Report, doc: str = "") -> str:
    """A report's definition as its Python file (Zach's ground truth: `record = Report(...)`, one keyword per line, a run id per line)."""
    def lit(v) -> str:
        # WHY json's quoting: the house style's double quotes; a JSON string is a Python literal (the same escapes)
        if isinstance(v, tuple):
            if not v:
                return "()"
            return "(\n" + "".join(f"        {lit(x)},\n" for x in v) + "    )"
        return json.dumps(v, ensure_ascii=False) if isinstance(v, str) else repr(v)

    body = "".join(f"    {f.name}={lit(getattr(report, f.name))},\n" for f in fields(report))
    head = (doc.strip() + "\n\n" if doc.strip() else "") + (f"Written by `python3 -m type_cards.report freeze --id {report.id} ...` (type_cards/report.py) from a "
                                                          f"selection of {len(report.runs)} runs; its snapshot is {report.id}.json beside it.")
    return f'"""{head}\n"""\n\nfrom type_cards.report import Report\n\nrecord = Report(\n{body})\n'


def definition_path(report_id: str, folder: Path | None = None) -> Path:
    return (folder or REPORTS_DIR) / f"{report_id.replace('-', '_')}.py"


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


def _context(data: Path, deployment: str) -> tuple[list[dict], list[dict], sel.Tables]:
    """(every node, the parameters table's rows, the deployment's selection tables) from the app's data: what a freeze reads."""
    from . import instances  # noqa: PLC0415

    results = instances.load_results()
    nodes = instances.virtual_nodes(results) + instances.physical_nodes(data)
    routines = json.loads((instances.RESULTS / "calibration_routines.json").read_text(encoding="utf-8"))
    rows = instances.parameter_table(nodes, results, routines)["rows"]
    tables = sel.load_tables(data, deployment, nodes=[n for n in nodes if n["root"] == deployment]) if deployment else sel.Tables()
    return nodes, rows, tables


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="freeze a report: python3 -m type_cards.report freeze <id>, or freeze --id <id> ... from a selection")
    parser.add_argument("action", choices=("freeze", "verify", "list"))
    parser.add_argument("report", nargs="?", help="an existing report's id (freeze re-freezes it on purpose; verify checks its digest)")
    parser.add_argument("--data", type=Path, default=Path("/home/bam/sim2real/app/data"), help="the app's data (tools/build_app.py)")
    new = parser.add_argument_group("a new report from a selection")
    new.add_argument("--id", help="its id: lowercase words joined by '-' (its file is frozen_reports/<id with _>.py)")
    new.add_argument("--title")
    new.add_argument("--question", help="what it answers, in a sentence")
    new.add_argument("--deployment", default="")
    new.add_argument("--runs", default="", help="run ids, comma-separated")
    new.add_argument("--select", action="append", default=[], help="col=value[,value]: runs.json columns, every one must hold (repeatable)")
    new.add_argument("--preset", help='a selection preset\'s name ("station: CAN 11", "day: 2026-11-06", "split: held_out")')
    new.add_argument("--models", nargs="*", default=[], help="model keys, <type>/<model id>")
    new.add_argument("--parameters", nargs="*", default=[], help="parameters table row ids")
    new.add_argument("--note", default="")
    new.add_argument("--doc", default="", help="the definition file's opening lines (what the report is, its rows)")
    args = parser.parse_args(argv)
    if args.action == "list":
        for rid, d in load_definitions().items():
            path = REPORTS_DIR / f"{rid}.json"
            state = ("verifies" if verify(read_snapshot(path)) else "DOES NOT VERIFY") if path.is_file() else "not frozen"
            print(f"{rid}: {d.title} ({len(d.runs)} runs; {state})")
        return 0
    if args.action == "verify":
        path = REPORTS_DIR / f"{args.report}.json"
        ok = verify(read_snapshot(path))
        print(f"{path}: {'verifies' if ok else 'DOES NOT VERIFY'}")
        return 0 if ok else 1
    if args.id:
        return _create(args)
    if not args.report:
        parser.error("freeze <id>, or freeze --id <id> --title ... --question ... with --runs, --select or --preset")
    report = load_definitions()[args.report]
    _nodes, rows, tables = _context(args.data, report.deployment)
    path = REPORTS_DIR / f"{args.report}.json"
    snap = freeze(report, tables, parameter_rows=rows, frozen_at=_now(), code=_code())
    write_snapshot(snap, path)
    print(f"froze {args.report}: {snap['results']['selection']['runs']} runs, {len(snap['results']['parameters'])} parameter rows -> {path}")
    return 0


def _create(args) -> int:
    """A new report from a selection: its definition written, then frozen; never over one that exists."""
    if not ID.match(args.id or ""):
        print(f"--id {args.id!r}: lowercase letters, digits and '-', starting with a letter", file=sys.stderr)
        return 2
    if not (args.title and args.question):
        print("a new report needs --title and --question", file=sys.stderr)
        return 2
    py, snap_path = definition_path(args.id), REPORTS_DIR / f"{args.id}.json"
    if py.exists() or snap_path.exists() or args.id in load_definitions_safe():
        print(f"{args.id} exists ({py.name}); re-freezing a report is a new decision: python3 -m type_cards.report freeze {args.id}", file=sys.stderr)
        return 1
    _nodes, rows, tables = _context(args.data, args.deployment)
    try:
        ids = select_runs(tables.runs, runs=[x for x in args.runs.split(",") if x], select=args.select, preset=args.preset)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 2
    if not ids:
        print("the selection holds no run: nothing to freeze", file=sys.stderr)
        return 2
    for key in args.models:
        tid, _, mid = key.partition("/")
        dm.model(tid, mid)  # a model key that names no model is a KeyError here, before anything is written
    report = Report(id=args.id, title=args.title, question=args.question, runs=tuple(ids), models=tuple(args.models),
                    parameters=tuple(args.parameters), deployment=args.deployment, note=args.note)
    py.write_text(definition_text(report, args.doc), encoding="utf-8")
    snap = freeze(report, tables, parameter_rows=rows, frozen_at=_now(), code=_code())
    write_snapshot(snap, snap_path)
    print(f"wrote {py.name} and froze {args.id}: {snap['results']['selection']['runs']} runs, {len(snap['results']['parameters'])} parameter rows "
          f"-> {snap_path}")
    return 0


def load_definitions_safe() -> dict[str, Report]:
    try:
        return load_definitions()
    except Exception:  # noqa: BLE001  (a folder that is not the package: the CLI test's)
        return {}


if __name__ == "__main__":
    sys.exit(main())
