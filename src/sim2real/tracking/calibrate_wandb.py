"""The W&B copy of a calibration's ledger (gap E, 2026-11-18): one run per calibration, rebuilt from the ledger's files alone, in the
deployment's (or rig's) own registered project.

    fitted = twin.calibrate(callbacks=[ledger, WandbLogger(ledger)])     # the live copy, beside the ledger (an unpowered host, a cloud VM)
    python -m sim2real.tracking.calibrate_wandb --follow FOLDER           # the live copy from another process (the powered rig's host)
    python -m sim2real.tracking.calibrate_wandb --sync FOLDER... | --all  # afterwards: push what W&B lacks (--dry-run shows it)
    python -m sim2real.tracking.calibrate_wandb --show FOLDER             # the rows, printed (no wandb, no network)

On the powered rig's host the calibration keeps wandb-core out of its own process: run SIM2REAL_TRACK=ledger (a rack calibration's
default) and follow its ledger at low priority, capped:

    systemd-run --user --scope -p MemoryMax=1G nice -n 19 taskset -c 2-5,16,17 python -m sim2real.tracking.calibrate_wandb --follow FOLDER

Zach, Daily Note 2026-11-17: "I decied I would have a weights and bias account for each deployment"; "W&B is just a visualizer for the dat".
House rule: W&B is a copy of a local ledger, and a project is registered in bam_ws tools/wandb_trackers/trackers/ before its first run.

The run: id run_id("calibrate", <calibration id>) (stable: a replay of the same ledger is the same run), job_type "calibrate", group
"calibrate · <twin>". History, one row per ledger event in order: the schedule, one row per step (found values with their intervals), the
outcome (the verdict, recovery per value), evaluate()'s gates (each value beside its verdict, before -> after per metric). WHY angles in
degrees here and only here (Zach, 2026-11-11: angles shown to him in degrees, never rad): the ledger keeps SI; a key whose unit is rad
(or mrad, rad/s) is logged as <name>_deg (<name>_deg_s), its _rad suffix replaced. The live copy, the follower and the replay share row(),
so all three log exactly the same rows.

WHY a twin with no project logs nowhere (rather than to the hub "Sim2Real"): a toy or test twin is not a deployment, and the free plan's
5 GB is shared by every project; WandbLogger(ledger, project=...) sends one anywhere on purpose.

Stdlib at import: wandb is imported only inside the functions that talk to W&B (the `tracking` extra).
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .._json import json_default_or_text
from .rigs import HUB, RIGS
from .wandb_log import ENTITY, REPO, WANDB_DIR, _clean, _table_rows, push, run_id

REGISTRY = REPO / "app" / "registry.json"            # the deployments, each with its W&B project (the Deployments page's "Open in W&B")
EXAMPLES = REPO / "sysid" / "examples"                 # each twin's manifest names its unit (record.path: the deployment record)
JOB_TYPE = "calibrate"
ENDED = ("done", "error", "pending", "evaluate")
# a unit an angle is stored in -> (the suffix it is shown with, the stored suffix it replaces, the factor to degrees)
ANGLES = {"rad": ("_deg", "_rad", math.degrees(1.0)), "mrad": ("_deg", "_mrad", math.degrees(1e-3)),
          "rad/s": ("_deg_s", "_rad_s", math.degrees(1.0))}

__all__ = ["HUB", "WandbLogger", "deployment_for", "follow", "project_for", "records", "row", "sync"]


# --- where a twin's runs go --------------------------------------------------------------------------------------------------------------


def deployment_for(twin_id: str) -> dict | None:
    """The app/registry.json deployment a twin's unit belongs to: the twin's manifest (sysid/examples/<id>/description.json) names its
    deployment record (record.path), and the deployment whose `record` is that same file (resolved) is its. None when either is missing."""
    if not twin_id or "/" in twin_id or twin_id.startswith("."):
        return None
    try:
        unit = json.loads((EXAMPLES / twin_id / "description.json").read_text(encoding="utf-8")).get("record") or {}
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not unit.get("path"):
        return None
    wanted = Path(unit["path"]).resolve()
    return next((d for d in registry.get("deployments", []) if d.get("record") and Path(d["record"]).resolve() == wanted), None)


def project_for(twin_id: str) -> str | None:
    """The W&B project a twin's calibrations are copied to: its deployment's (app/registry.json, Zach 2026-11-17: one project per
    deployment), else its rig's (sim2real.tracking.rigs.RIGS: a twin named after the rig, "ur_wrist_test_rig" for "ur_wrist"), else None."""
    project = ((deployment_for(twin_id) or {}).get("wandb") or {}).get("project")
    if project:
        return project
    # WHY by the twin's name: a rig's twin is its sysid example, named "<rig>_<what>" (ur_wrist_test_rig); RIGS holds no example ids
    for name, rig in sorted(RIGS.items(), key=lambda item: -len(item[0])):
        if twin_id == name or str(twin_id).startswith(f"{name}_"):
            return rig.project
    return None


# --- the rows: one pure function feeds the live copy, the follower and the replay ---------------------------------------------------------


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _shown(key: str, unit: str | None) -> tuple[str, float]:
    """A parameter key as a W&B path and the factor its value is shown with: "toy.offset" in rad -> ("toy/offset_deg", 57.29...)."""
    instance, _, name = str(key).partition(".")
    if not name:
        instance, name = "", instance
    factor = 1.0
    if unit in ANGLES:
        suffix, stored, factor = ANGLES[unit]
        name = name[: -len(stored)] + suffix if name.endswith(stored) else name + suffix
    return (f"{instance}/{name}" if instance else name), factor


def _scaled(value: Any, factor: float) -> float | None:
    number = _num(value)
    return None if number is None else number * factor


def row(event: Mapping[str, Any]) -> dict:
    """The W&B history row one ledger event makes ({} for an event that makes none: a callback_error). Pure: the same event gives the same
    row, in the live copy, the follower and the replay."""
    kind = event.get("kind")
    out: dict[str, Any] = {"time/elapsed_s": _num(event.get("t"))}
    if kind == "schedule":
        schedule = event.get("schedule") or {}
        totals = schedule.get("totals") or {}
        out.update({"schedule/steps": len(schedule.get("steps") or []), "schedule/dropped": len(schedule.get("dropped") or []),
                    "schedule/uncovered": len(schedule.get("uncovered") or []),
                    **{f"schedule/{name}": _num(totals.get(name)) for name in ("wall_time_s", "run_time_s", "operator_time_s", "equipment_usd")}})
    elif kind == "collect":
        out["collect/seconds"] = _num(event.get("seconds"))
        out.update({f"collect/{split}_runs": _num(n) for split, n in (event.get("runs") or {}).items()})
    elif kind == "step":
        out.update({"step/index": _num(event.get("index")), "step/round": _num(event.get("round")), "step/collect_s": _num(event.get("collect_s")),
                    "step/fit_s": _num(event.get("fit_s")), "step/seconds": _num(event.get("seconds")), "step/runs": len(event.get("runs") or [])})
        if "played" in event:
            out["step/played"] = len(event.get("played") or [])
        for key, found in (event.get("found") or {}).items():
            path, factor = _shown(key, found.get("unit"))
            out[f"found/{path}"] = _scaled(found.get("value"), factor)
            if found.get("ci95"):
                out[f"found/{path}/ci95_lo"] = _scaled(found["ci95"][0], factor)
                out[f"found/{path}/ci95_hi"] = _scaled(found["ci95"][1], factor)
    elif kind == "done":
        out.update({"calibration/passed": int(bool(event.get("passed"))), "calibration/seconds": _num(event.get("seconds")),
                    "calibration/failing": len(event.get("failing") or [])})
        for r in event.get("rows") or []:
            path, factor = _shown(r.get("key"), r.get("unit"))
            if r.get("pass") is not None:
                out[f"recovery/{path}/pass"] = int(bool(r["pass"]))
            out[f"recovery/{path}/error"] = _scaled(r.get("error"), factor)
    elif kind == "evaluate":
        gates = event.get("gates") or []
        out.update({"eval/passed": int(bool(event.get("passed"))), "eval/gates_passed": sum(bool(g.get("passed")) for g in gates),
                    "eval/gates_total": len(gates)})
        for g in gates:
            out[f"gate/{g.get('id')}/passed"] = int(bool(g.get("passed")))
            value = g.get("value")
            if isinstance(value, str):
                try:
                    value = float(value)   # a gate's value written as a plain number ("1.07"); "2/3" or "0.4 mm" stay in the gates table
                except ValueError:
                    value = None
            out[f"gate/{g.get('id')}/value"] = _num(value)
        for name, m in (event.get("compare") or {}).items():
            suffix, _, factor = ANGLES.get(m.get("unit"), ("", "", 1.0))
            for part in ("before", "after", "floor"):
                out[f"eval/{name}{suffix}/{part}"] = _scaled(m.get(part), factor)
            out[f"eval/{name}{suffix}/factor"] = _num(m.get("factor"))
    elif kind in ("error", "pending"):
        out[f"calibration/{kind}"] = 1
    else:
        return {}
    return _clean(out)


# --- the run, rebuilt from the files alone ------------------------------------------------------------------------------------------------


def _plain(event: Mapping[str, Any]) -> dict:
    """An event as the ledger wrote it (through JSON), so a live row and a replayed row are built from the same values."""
    return json.loads(json.dumps(event, default=json_default_or_text))


def read_events(folder: str | Path) -> list[dict]:
    path = Path(folder) / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _head(begun: Mapping[str, Any], ledger: str) -> dict:
    """A run's identity and config from its schedule event: everything but history, summary and tables."""
    twin, backend = str(begun.get("twin")), str(begun.get("backend"))
    schedule = begun.get("schedule") or {}
    routines = [s.get("routine") for s in schedule.get("steps") or []]
    code = begun.get("code") or {}
    deployment = deployment_for(twin) or {}
    config = {"twin": twin, "deployment": deployment.get("id"), "backend": backend, "model": begun.get("model"), "level": schedule.get("level"),
              "routines": routines, "ledger": ledger, "calibration": begun.get("calibration"), "sim2real_sha": code.get("sha"),
              "dirty": code.get("dirty"), "events_schema": begun.get("schema"), "version_kind": "calibration"}
    tags = {JOB_TYPE, backend, twin} | ({"dirty"} if code.get("dirty") else set())
    return {"id": run_id(JOB_TYPE, str(begun.get("calibration"))), "name": f"calibrate · {twin} · {backend} · {str(begun.get('utc', ''))[:19]}",
            "group": f"calibrate · {twin}", "job_type": JOB_TYPE, "tags": sorted(tags),
            "notes": f"calibrate(on={backend!r}) of {twin}: {' -> '.join(map(str, routines)) or 'no routines'}; rebuilt from its ledger {ledger}",
            "config": config}


def _tables(events: list[Mapping[str, Any]], names: Iterable[str] = ("schedule", "steps", "parameters", "gates")) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    wanted = set(names)
    begun = next((e for e in events if e.get("kind") == "schedule"), {})
    if "schedule" in wanted:
        out["schedule"] = [{"routine": s.get("routine"), "title": s.get("title"), "kind": s.get("kind"), "setting": s.get("setting"),
                            "wall_time_s": s.get("wall_time_s"), "why_here": s.get("why_here")}
                           for s in (begun.get("schedule") or {}).get("steps") or []]
    if "steps" in wanted:
        out["steps"] = []
        for e in (e for e in events if e.get("kind") == "step"):
            found = []
            for key, f in (e.get("found") or {}).items():
                path, factor = _shown(key, f.get("unit"))
                value = _scaled(f.get("value"), factor)
                found.append(f"{path}={'—' if value is None else f'{value:.6g}'}")
            out["steps"].append({"index": e.get("index"), "routine": e.get("routine"), "runs": len(e.get("runs") or []),
                                 "played": len(e.get("played") or []), "collected": e.get("collected"), "collect_s": e.get("collect_s"),
                                 "fit_s": e.get("fit_s"), "seconds": e.get("seconds"), "round": e.get("round"), "found": "; ".join(found)})
    done = next((e for e in reversed(events) if e.get("kind") == "done"), None)
    if "parameters" in wanted and done is not None:
        out["parameters"] = []
        for r in done.get("rows") or []:
            path, factor = _shown(r.get("key"), r.get("unit"))
            ci = r.get("ci95") or (None, None)
            out["parameters"].append({"parameter": path, "unit": "deg" if factor != 1.0 else r.get("unit"),
                                      **{name: _scaled(r.get(name), factor) for name in ("nominal", "true", "recovered", "error")},
                                      "ci95_lo": _scaled(ci[0], factor), "ci95_hi": _scaled(ci[1], factor), "pass": r.get("pass")})
    evaluated = next((e for e in reversed(events) if e.get("kind") == "evaluate"), None)
    if "gates" in wanted and evaluated is not None:
        out["gates"] = [{k: g.get(k) for k in ("id", "title", "value", "rule", "passed", "source")} for g in evaluated.get("gates") or []]
    return {name: rows for name, rows in out.items() if rows}


def _summary(events: list[Mapping[str, Any]]) -> dict:
    last = next((e for e in reversed(events) if e.get("kind") in (*ENDED, "step", "collect", "schedule")), {})
    state = {"done": "done", "error": "error", "pending": "pending", "evaluate": "evaluated"}.get(last.get("kind"), "running")
    out: dict[str, Any] = {"state": state}
    for e in events:
        if e.get("kind") == "done":
            out["passed"] = bool(e.get("passed"))
        elif e.get("kind") == "evaluate":
            out["eval_passed"] = bool(e.get("passed"))
        elif e.get("kind") in ("error", "pending"):
            out["error"] = e.get("error") or ""
            if e.get("submission"):
                out["submission"] = e["submission"]
    return out


def records(folder: str | Path) -> list[dict]:
    """The W&B run one ledger folder makes, as plain dicts in wandb_log.records()' shape (no wandb needed): [{id, name, group, job_type,
    tags, notes, config, history, summary, tables}], from the files alone (copy the folder anywhere, the run is the same). [] for a
    folder with no schedule event."""
    folder = Path(folder)
    events = read_events(folder)
    begun = next((e for e in events if e.get("kind") == "schedule"), None)
    if begun is None:
        return []
    history = [values for values in (row(e) for e in events) if values]
    return [{**_head(begun, folder.name), "history": history, "summary": _summary(events), "tables": _tables(events)}]


# --- the live copy ----------------------------------------------------------------------------------------------------------------------


class _Copy:
    """One calibration's W&B run as it is written: opened at the schedule, one row per event, tables and summary when it closes."""

    def __init__(self, project: str, entity: str, wandb_dir: Path | None):
        self.project, self.entity, self.wandb_dir = project, entity, wandb_dir
        self.head: dict | None = None
        self.run = None
        self.events: list[dict] = []

    def start(self, begun: Mapping[str, Any], ledger: str) -> None:
        self.head = _head(begun, ledger)
        self._open()

    def _open(self) -> None:
        import wandb  # noqa: PLC0415  (the tracking extra)

        directory = Path(self.wandb_dir or WANDB_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        h = self.head
        # WHY resume="allow" under the replay's id: evaluate() reopens the same run, and --sync of a complete ledger finds it whole
        self.run = wandb.init(entity=self.entity, project=self.project, id=h["id"], name=h["name"], group=h["group"], job_type=h["job_type"],
                              tags=h["tags"], notes=h["notes"], config=h["config"], resume="allow", reinit="create_new", dir=str(directory),
                              settings=wandb.Settings(silent=True, console="off"))

    def log(self, event: Mapping[str, Any]) -> None:
        plain = _plain(event)
        self.events.append(plain)
        if self.run is None:
            self._open()
        values = row(plain)
        if values:
            self.run.log(values)

    def close(self, names: Iterable[str]) -> None:
        import wandb  # noqa: PLC0415

        if self.run is None:
            return
        tables = _tables(self.events, names)
        if tables:
            # WHY a row of their own: history rows stay exactly the replay's rows (a table is no point on a chart)
            self.run.log({name: wandb.Table(columns=columns, data=data, allow_mixed_types=True)
                          for name, (columns, data) in ((n, _table_rows(rows)) for n, rows in tables.items())})
        self.run.summary.update(_summary(self.events))
        self.run.finish()
        self.run = None


class WandbLogger:
    """The live W&B copy of a Ledger (a callback: list it after its ledger, callbacks=[ledger, WandbLogger(ledger)]). It requires the
    Ledger it copies (W&B is a copy of a local ledger, so a live copy without one is refused) and opens it first if it is listed first.
    `project` None: the twin's deployment's or rig's (project_for); a twin with neither gets none, which costs one callback_error and
    logs nothing. A W&B that will not start (no wandb, no network, no login) raises once in on_calibrate_begin: the calibration detaches
    the logger with one warning and never tries again; the ledger stays whole, and --sync copies it later. Mode is wandb's own
    (WANDB_MODE=offline on a cloud VM: the run lands under `wandb_dir`, `wandb sync` uploads it)."""

    def __init__(self, ledger: Any, *, project: str | None = None, entity: str = ENTITY, wandb_dir: str | Path | None = None):
        if not (callable(getattr(ledger, "on_calibrate_begin", None)) and callable(getattr(ledger, "folder_of", None))):
            raise TypeError(f"WandbLogger copies a sim2real.calibration.Ledger (W&B is a copy of a local ledger), not {type(ledger).__name__}")
        self.ledger, self.project, self.entity = ledger, project, entity
        self.wandb_dir = None if wandb_dir is None else Path(wandb_dir)
        self._copies: dict[str, _Copy] = {}

    def on_calibrate_begin(self, event: dict, *, schedule: Any = None, twin: Any = None) -> None:
        self.ledger.on_calibrate_begin(event, schedule=schedule, twin=twin)   # idempotent: the ledger's own call is then a no-op
        project = self.project or project_for(event.get("twin"))
        if not project:
            raise ValueError(f"WandbLogger: twin {event.get('twin')!r} has no W&B project (no deployment in app/registry.json names its unit, "
                             "no rig in sim2real.tracking.rigs.RIGS is it); pass WandbLogger(ledger, project=...) to copy it anyway")
        copy = _Copy(project, self.entity, self.wandb_dir)
        folder = self.ledger.folder_of(event["calibration"])
        copy.start(event, folder.name if folder is not None else "")
        self._copies[event["calibration"]] = copy
        copy.log(event)

    def _log(self, event: dict) -> _Copy | None:
        copy = self._copies.get(event["calibration"])
        if copy is not None:
            copy.log(event)
        return copy

    def on_collect_end(self, event: dict) -> None:
        self._log(event)

    def on_step_end(self, event: dict) -> None:
        self._log(event)

    def on_calibrate_end(self, event: dict, *, fitted: Any = None) -> None:
        copy = self._log(event)
        if copy is not None:
            copy.close(("schedule", "steps", "parameters"))

    def on_calibrate_error(self, event: dict) -> None:
        copy = self._log(event)
        if copy is not None:
            copy.close(("schedule", "steps"))

    def on_evaluate_end(self, event: dict, *, report: Any = None, fitted: Any = None) -> None:
        copy = self._log(event)   # reopens the calibration's run by its id
        if copy is not None:
            copy.close(("gates",))


# --- the follower and the replay ---------------------------------------------------------------------------------------------------------


def follow(folder: str | Path, *, project: str | None = None, entity: str = ENTITY, wandb_dir: str | Path | None = None,
           idle_s: float = 600.0, poll_s: float = 2.0, stale_s: float = 86400.0) -> dict:
    """Tail a ledger's events.jsonl and log each row as it appears: the live copy from another process. It stops `idle_s` after the
    calibration ended (done, error, pending, or an evaluate after it) with no new line, or `stale_s` after the last line of one that never
    ends. Returns {id, project, rows}.

    WHY a follower (the powered rig's host): wandb-core is a service process of its own; the calibration beside the arm keeps it out of
    its process and this one runs at low priority, capped (see the module docstring's systemd-run line)."""
    folder = Path(folder)
    path = folder / "events.jsonl"
    copy: _Copy | None = None
    offset, buffer, last_kind, rows = 0, "", None, 0
    quiet_since = time.monotonic()
    try:
        while True:
            fresh = False
            if path.is_file():
                with open(path, encoding="utf-8") as handle:
                    handle.seek(offset)
                    buffer += handle.read()
                    offset = handle.tell()
                *lines, buffer = buffer.split("\n")
                for line in filter(str.strip, lines):
                    event = json.loads(line)
                    fresh = True
                    if copy is None:
                        if event.get("kind") != "schedule":
                            continue
                        chosen = project or project_for(event.get("twin"))
                        if not chosen:
                            raise ValueError(f"no W&B project for twin {event.get('twin')!r}: pass --project")
                        copy = _Copy(chosen, entity, None if wandb_dir is None else Path(wandb_dir))
                        copy.start(event, folder.name)
                    copy.log(event)
                    rows += bool(row(event))
                    last_kind = event.get("kind")
            now = time.monotonic()
            if fresh:
                quiet_since = now
            quiet = now - quiet_since
            if (last_kind in ENDED and quiet >= idle_s) or quiet >= stale_s:
                break
            time.sleep(max(float(poll_s), 0.05))   # WHY a floor: a follower never spins a core beside the powered arm
    finally:
        if copy is not None:
            copy.close(("schedule", "steps", "parameters", "gates"))
    return {"id": None if copy is None else copy.head["id"], "project": None if copy is None else copy.project, "rows": rows}


def ledgers() -> list[Path]:
    """Every ledger folder on this machine: the sim's (paths.CALIBRATIONS) and the rack's, beside each submission (paths.REAL_RUNS)."""
    from .. import paths  # noqa: PLC0415

    sim = paths.env_path("SIM2REAL_CALIBRATIONS", paths.CALIBRATIONS)
    found = [p.parent for p in sorted(sim.glob("*/events.jsonl"))] + [p.parent for p in sorted(paths.REAL_RUNS.glob("*/calibrate/*/events.jsonl"))]
    return found


def _retire(api: Any, entity: str, project: str, run: str) -> None:
    """Mark a partial calibrate run superseded by its replay (config calibration_state + tag). Never deletes."""
    old = api.run(f"{entity}/{project}/{run}")
    old.config["calibration_state"] = "superseded"
    old.tags = sorted({*old.tags, "superseded"} - {"latest"})
    old.update()


def sync(folders: Iterable[str | Path], *, project: str | None = None, entity: str = ENTITY, dry_run: bool = False) -> list[dict]:
    """Push each ledger's run where W&B lacks it: a run W&B does not hold is written whole under its id; a run W&B holds short of the
    ledger (a live copy that died mid-schedule: its last time/elapsed_s is behind the ledger's) is replayed whole under a fresh id
    (run_id("calibrate", <calibration>, "replay")) and the partial run is marked superseded; a whole run is left alone. Never deletes."""
    out = []
    api = None
    for folder in folders:
        found = records(folder)
        if not found:
            out.append({"folder": str(folder), "action": "skipped: no schedule event"})
            continue
        record = found[0]
        chosen = project or project_for(record["config"]["twin"])
        if not chosen:
            out.append({"folder": str(folder), "id": record["id"], "action": "skipped: no W&B project (pass --project)"})
            continue
        entry = {"folder": str(folder), "id": record["id"], "project": chosen, "rows": len(record["history"])}
        last_t = max((r.get("time/elapsed_s", 0.0) for r in record["history"]), default=0.0)
        if dry_run:
            out.append({**entry, "action": "dry run"})
            continue
        import wandb  # noqa: PLC0415

        api = api or wandb.Api(timeout=60)
        try:
            have = dict(api.run(f"{entity}/{chosen}/{record['id']}").summary)
        except Exception:   # noqa: BLE001  (wandb raises CommError / ValueError for a run that does not exist yet)
            have = None
        if have is None:
            push([record], entity=entity, project=chosen)
            out.append({**entry, "action": "written"})
        elif float(have.get("time/elapsed_s") or 0.0) + 1e-6 < last_t:
            replay = {**record, "id": run_id(JOB_TYPE, str(record["config"]["calibration"]), "replay"), "name": f"{record['name']} · replay"}
            push([replay], entity=entity, project=chosen)
            _retire(api, entity, chosen, record["id"])
            out.append({**entry, "action": f"replayed as {replay['id']} (W&B held it short); the partial run is marked superseded"})
        else:
            out.append({**entry, "action": "whole on W&B already"})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim2real.tracking.calibrate_wandb", description=__doc__.split("\n\n")[0])
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--sync", nargs="+", type=Path, metavar="FOLDER", help="push each ledger folder's run where W&B lacks it")
    what.add_argument("--all", action="store_true", help="--sync every ledger on this machine (paths.CALIBRATIONS and each rack submission's)")
    what.add_argument("--follow", type=Path, metavar="FOLDER", help="tail one ledger and log each row as it appears")
    what.add_argument("--show", type=Path, metavar="FOLDER", help="print the run a ledger makes (no wandb, no network)")
    parser.add_argument("--project", default=None, help="the W&B project (default: the twin's deployment's or rig's)")
    parser.add_argument("--dry-run", action="store_true", help="with --sync/--all: say what would be pushed, push nothing")
    parser.add_argument("--idle-s", type=float, default=600.0, help="with --follow: stop this long after the calibration ended")
    parser.add_argument("--poll-s", type=float, default=2.0, help="with --follow: seconds between reads")
    args = parser.parse_args(argv)
    if args.show:
        print(json.dumps(records(args.show), indent=1, default=str))
        return 0
    if args.follow:
        print(json.dumps(follow(args.follow, project=args.project, idle_s=args.idle_s, poll_s=args.poll_s)))
        return 0
    for entry in sync(ledgers() if args.all else args.sync, project=args.project, dry_run=args.dry_run):
        print(json.dumps(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
