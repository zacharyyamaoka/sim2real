"""Watching a calibration while it runs (gap E, 2026-11-18): ``calibrate(callbacks=[...])`` reports the schedule, each step as it finishes,
the fitted twin and evaluate()'s gates to its callbacks, a local Ledger first and W&B only as a copy of that ledger.

    ledger = sim2real.calibration.Ledger()                    # one folder per calibration: events.jsonl, schedule.json, calibration.json, eval.json
    fitted = twin.calibrate(on="sim", callbacks=[ledger])      # ledger.folder fills line by line as the calibration runs
    fitted.evaluate()                                          # appends the gates there too (fitted.callbacks_ keeps the callbacks)
    SIM2REAL_TRACK=ledger python my_script.py                  # the same with no code change: off | ledger | wandb
    python -m sim2real.tracking.calibrate_wandb --follow FOLDER   # the W&B copy, from the ledger (or --sync afterwards)

Zach, Daily Note 2026-11-17: "As that calibration is running you will see like the results in weights and biases, or etc. you can visually
see once it has been calibrated and how it improves"; "W&B is just a visualizer for the dat". 2026-11-11: "have the results like show up in
weights and biases should be all automated".

WHY callbacks on calibrate() and not on CalibrationConfig (Keras's fit(callbacks=)): a config steers WHAT is calibrated and lands in the
record; an observer changes nothing about the fit, so it stays out of the record and out of the session id a dataset is grown by.

WHY observers never guard (the module docstring of twin.py: "guards live in the runner, never in callbacks"): a hook that raises is detached
with one RuntimeWarning and a ``callback_error`` line, and the calibration goes on unchanged; a calibration that fails still raises, after
its ledger says so.

WHY off by default on the sim and a ledger by default on the rack: the sim's calibrate() is called hundreds of times by sweeps and stress
lanes (writing a folder each would flood the disk, and a W&B run each the free tier), and it documented "writes nothing"; a rack calibration
spends robot time, so its ledger is kept beside its submission (``<submission>/calibrate/<stamp>/``) unless SIM2REAL_TRACK=off.

WHY a ledger first and W&B a copy (house rule: W&B is a copy of a local ledger): the files hold everything a W&B run shows, so a run that
never reached W&B, or died halfway, is rebuilt from them (sim2real.tracking.calibrate_wandb.records / --sync).

Stdlib only at import; nothing here imports wandb (sim2real.tracking.calibrate_wandb is loaded lazily, for SIM2REAL_TRACK=wandb only).
"""

from __future__ import annotations

import importlib
import json
import os
import time
import uuid
import warnings
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .._json import json_default_or_text

EVENTS_SCHEMA = "sim2real.calibration-events/1"
TRACK_ENV = "SIM2REAL_TRACK"
TRACK_CHOICES = ("off", "ledger", "wandb")
TERMINAL = ("done", "error", "pending")


class Callback:
    """The hooks a calibration reports to, each a no-op here. Duck-typed: a callback needs no base class and implements only the hooks it
    wants. Every hook is handed the event (a JSON-ready dict: schema, kind, calibration, twin, utc, t, and the kind's fields) and, where
    it says so, the live objects.

    on_calibrate_begin(event, *, schedule, twin)   kind "schedule": the CalibrationSchedule about to run, before anything is played
    on_submission(event)                           kind "submission" (the rack only, never a ledger line): the submission folder emit
                                                   wrote, before the rack plays it
    on_collect_end(event)                          kind "collect": the runs played up front (the tracer's world, the rack's ingest)
    on_step_end(event)                             kind "step": one planned routine, as its fit finishes
    on_calibrate_end(event, *, fitted)             kind "done": the fitted twin
    on_calibrate_error(event)                      kind "error" (the calibration raised) or "pending" (the rack has runs still to play)
    on_evaluate_end(event, *, report, fitted)      kind "evaluate": evaluate()'s gates
    on_callback_error(event)                       kind "callback_error": another callback raised and was detached"""

    def on_calibrate_begin(self, event: dict, *, schedule: Any, twin: Any) -> None:
        """The schedule, before anything is played."""

    def on_submission(self, event: dict) -> None:
        """The rack's submission folder, written and not yet played."""

    def on_collect_end(self, event: dict) -> None:
        """The runs played up front, before the first fit."""

    def on_step_end(self, event: dict) -> None:
        """One planned routine, as its fit finishes."""

    def on_calibrate_end(self, event: dict, *, fitted: Any) -> None:
        """The fitted twin."""

    def on_calibrate_error(self, event: dict) -> None:
        """The calibration raised ("error"), or the rack has runs still to play ("pending")."""

    def on_evaluate_end(self, event: dict, *, report: Any, fitted: Any) -> None:
        """evaluate()'s report."""

    def on_callback_error(self, event: dict) -> None:
        """Another callback raised and was detached."""


def calibrations_root() -> Path:
    """Where a ledger with no root of its own opens its folders: $SIM2REAL_CALIBRATIONS (read now, not at import), else paths.CALIBRATIONS."""
    from .. import paths  # noqa: PLC0415

    return paths.env_path("SIM2REAL_CALIBRATIONS", paths.CALIBRATIONS)


def _utc() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _dumps(value: Any, **options: Any) -> str:
    return json.dumps(value, default=json_default_or_text, **options)


class Ledger(Callback):
    """A calibration's local ledger: one new folder per calibration under `root`, named '<UTC stamp>-<twin id>', holding events.jsonl
    (every event, appended, flushed and fsynced as it happens), schedule.json (the schedule's to_dict()), calibration.json (the record,
    sim2real.calibration/1, rewritten with evaluate()'s gates) and eval.json (the report's to_dict()). SI units throughout, never converted.

    `root` None: $SIM2REAL_CALIBRATIONS, else paths.CALIBRATIONS, read when a calibration begins. `beside_submission` (a rack calibration's
    default): the folder opens under '<submission folder>/calibrate/' once emit has written the submission, before the rack plays it; the
    lines before that wait in memory. `folder` is the latest calibration's folder. One Ledger reused for several calibrations opens one
    folder each, and every event lands in its own calibration's folder (each event names its calibration), so a twin fitted earlier and
    evaluated later still writes beside its own steps."""

    def __init__(self, root: str | os.PathLike | None = None, *, beside_submission: bool = False):
        self.root = None if root is None else Path(root)
        self.beside_submission = bool(beside_submission)
        self.folder: Path | None = None
        self._folders: dict[str, Path] = {}
        self._waiting: dict[str, list[tuple[str, Any, Any]]] = {}

    def folder_of(self, calibration: str) -> Path | None:
        """The folder this ledger keeps for one calibration (an event's "calibration"), or None."""
        return self._folders.get(calibration)

    # ---- hooks

    def on_calibrate_begin(self, event: dict, *, schedule: Any = None, twin: Any = None) -> None:
        cid = event["calibration"]
        if cid in self._folders or cid in self._waiting:
            return   # WHY idempotent: a WandbLogger listed before its ledger opens it first, and the ledger's own call is then a no-op
        if self.beside_submission:
            self._waiting[cid] = []
        else:
            self._open(event, self.root or calibrations_root())
        self._line(event)
        self._file(cid, "schedule.json", event.get("schedule"))

    def on_submission(self, event: dict) -> None:
        cid = event["calibration"]
        if cid not in self._waiting or not event.get("submission"):
            return
        where = Path(event["submission"])
        # WHY a refit's folder only when it exists: a refit from held runs names the submission they came from, which may be another
        # machine's path; a fresh emit's folder is the one the rack is about to play, written or not
        root = where / "calibrate" if (event.get("emitted") or where.is_dir()) else (self.root or calibrations_root())
        self._flush(event, root)

    def on_collect_end(self, event: dict) -> None:
        self._line(event)

    def on_step_end(self, event: dict) -> None:
        self._line(event)

    def on_calibrate_end(self, event: dict, *, fitted: Any = None) -> None:
        self._line(event)
        record = getattr(fitted, "record_", None)
        if record is not None:
            self._file(event["calibration"], "calibration.json", record.to_dict())

    def on_calibrate_error(self, event: dict) -> None:
        self._line(event)

    def on_evaluate_end(self, event: dict, *, report: Any = None, fitted: Any = None) -> None:
        self._line(event)
        cid = event["calibration"]
        as_dict = report.to_dict()
        self._file(cid, "eval.json", as_dict)
        record = getattr(fitted, "record_", None)
        if record is not None:
            self._file(cid, "calibration.json", record.with_evaluation(as_dict).to_dict())

    def on_callback_error(self, event: dict) -> None:
        self._line(event)

    # ---- the files

    def _open(self, event: dict, root: Path) -> Path:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        twin = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(event.get("twin") or "twin"))
        base = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{twin}"
        name, n = base, 2
        while True:
            try:
                (root / name).mkdir()
                break
            except FileExistsError:
                name, n = f"{base}-{n}", n + 1
        folder = root / name
        self._folders[event["calibration"]] = folder
        self.folder = folder
        return folder

    def _flush(self, event: dict, root: Path) -> None:
        waiting = self._waiting.pop(event["calibration"])
        self._open(event, root)
        for what, name, payload in waiting:
            if what == "line":
                self._append(payload)
            else:
                self._write(event["calibration"], name, payload)

    def _line(self, event: dict) -> None:
        cid = event["calibration"]
        if cid in self._waiting:
            if event["kind"] not in (*TERMINAL, "evaluate"):
                self._waiting[cid].append(("line", None, event))
                return
            # the calibration ended before a submission named the folder (a refused run, a refit with no submission): the pending event
            # names the submission it waits on, anything else goes under the ledger's own root
            where = event.get("submission")
            self._flush(event, Path(where) / "calibrate" if where else (self.root or calibrations_root()))
        elif cid not in self._folders:
            self._open(event, self.root or calibrations_root())   # an evaluate of a calibration this ledger did not see begin
        self._append(event)

    def _append(self, event: dict) -> None:
        text = _dumps(event) + "\n"
        with open(self._folders[event["calibration"]] / "events.jsonl", "a", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())   # WHY fsync: the ledger is the copy that survives a crash, and a follower tails it live

    def _file(self, cid: str, name: str, payload: Any) -> None:
        if payload is None:
            return
        if cid in self._waiting:
            self._waiting[cid].append(("file", name, payload))
            return
        self._write(cid, name, payload)

    def _write(self, cid: str, name: str, payload: Any) -> None:
        path = self._folders[cid] / name
        part = path.with_name(f".{name}.part")
        part.write_text(_dumps(payload, indent=1) + "\n", encoding="utf-8")
        os.replace(part, path)   # whole or not at all: a follower never reads half a file


def resolve_callbacks(callbacks: Any, *, backend: str = "sim") -> list:
    """The callbacks a calibration reports to. A list or tuple is taken as given (callbacks=[] wins over everything). None reads
    SIM2REAL_TRACK: "off" gives none; "ledger" a Ledger; "wandb" a Ledger and a WandbLogger copying it (sim2real.tracking.calibrate_wandb,
    loaded here, lazily); unset or empty gives none on the sim and a Ledger beside the submission on the rack (backend "real"). Any other
    value is refused by name. Resolving writes nothing (a ledger opens its folder when a calibration begins) and never imports wandb."""
    if callbacks is not None:
        if not isinstance(callbacks, (list, tuple)):
            raise TypeError(f"callbacks is a list of callback objects (a Ledger, a WandbLogger, your own), not {type(callbacks).__name__}")
        return list(callbacks)
    raw = os.environ.get(TRACK_ENV) or ""
    value = raw.strip().lower()
    if value not in ("", *TRACK_CHOICES):
        raise ValueError(f"{TRACK_ENV}={raw!r} is not one of {', '.join(TRACK_CHOICES)} (off: no ledger; ledger: a local ledger; wandb: a ledger "
                         "and its live W&B copy)")
    if value == "off" or (value == "" and backend != "real"):
        return []
    ledger = Ledger(beside_submission=backend == "real")
    if value in ("", "ledger"):
        return [ledger]
    copy = importlib.import_module("sim2real.tracking.calibrate_wandb")
    return [ledger, copy.WandbLogger(ledger)]


# --- the dispatcher: builds each event once and hands it to every callback --------------------------------------------------------------


def _words(caught: BaseException) -> str:
    text = str(caught)
    return f"{type(caught).__name__}: {text}" if text else type(caught).__name__


def _plain(value: Any) -> Any:
    """A JSON-native copy of one value a report carries (a numpy scalar as its number, anything unknown as its text)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        return json.loads(_dumps(value))
    except (TypeError, ValueError):
        return str(value)


def _rows(calibration: Any) -> list[dict]:
    """A calibration's parameter rows, the fields a dashboard plots (key, unit, nominal, true, recovered, ci95, error, tolerance, pass)."""
    out = []
    for r in getattr(calibration, "rows", None) or ():
        recovered, true = r.get("recovered"), r.get("true")
        error = r.get("error")
        if error is None and recovered is not None and true is not None:
            error = recovered - true
        out.append({"key": r.get("key"), "unit": r.get("unit"), "nominal": r.get("nominal"), "true": true, "recovered": recovered,
                    "ci95": list(r["ci95"]) if r.get("ci95") else None, "error": error, "tolerance": r.get("tolerance"), "pass": r.get("pass")})
    return out


def _compare(report: Any) -> dict[str, dict]:
    """evaluate()'s before -> after numbers, {name: {before, after, factor, unit}}: a tracer's or the rack's metrics that carry both
    (held-out error at the priors vs at the fitted values), a rig's held-out RMS per joint (nominal twin vs fitted twin, over its floor)."""
    out: dict[str, dict] = {}
    for name, m in (getattr(report, "metrics", None) or {}).items():
        if isinstance(m, Mapping) and "before" in m and "after" in m:
            out[str(name)] = {"before": _plain(m.get("before")), "after": _plain(m.get("after")), "factor": _plain(m.get("factor")),
                              "unit": m.get("unit")}
    errors = getattr(report, "errors", None)
    if isinstance(errors, Mapping) and "fitted" in errors:
        floor = getattr(report, "floor", None) or {}
        for joint, after in errors["fitted"].items():
            before = (errors.get("nominal") or {}).get(joint)
            out[f"heldout_rms/{joint}"] = {"before": _plain(before), "after": _plain(after), "floor": _plain(floor.get(joint)),
                                           "factor": _plain(before / after) if before is not None and after else None, "unit": "rad"}
    return out


class Watch:
    """Internal: one calibration's dispatcher. It builds each event exactly once (schema, kind, calibration id, twin, utc, t since the
    calibration began, and the kind's fields), hands it to each live callback in list order through the hook its kind names, and detaches
    a callback whose hook raises (one RuntimeWarning, one callback_error event to the callbacks still attached). RobotTwin.calibrate and
    real.main build one when there are callbacks; the runners only ever see its plain functions (on_plan, on_step, ...)."""

    def __init__(self, callbacks, twin: Any, backend: str, *, config: Any = None, calibration: str | None = None, started: float | None = None):
        self.alive = list(callbacks)
        self.twin = twin
        self.twin_id = str(twin.description.id)
        self.backend = backend
        self.config = config
        self.id = calibration or uuid.uuid4().hex
        self.started = time.monotonic() if started is None else float(started)
        self.began = self.ended = False
        self.ids: tuple[str, ...] = ()
        self._steps = 0
        self._errors: list[dict] = []

    # ---- the plain functions the runners call

    def rig_hooks(self) -> dict:
        return {"on_plan": self.begin, "on_step": self.step}

    def tracer_hooks(self) -> dict:
        return {"on_step": self.step, "on_collect": self.collect}

    def real_hooks(self) -> dict:
        return {"on_plan": self.begin, "on_step": self.step, "on_collect": self.collect, "on_submission": self.submission,
                "on_pending": self.pending}

    def begin(self, schedule: Any) -> None:
        if self.began:
            return
        self.began = True
        self.ids = tuple(getattr(schedule, "ids", ()) or ())
        config = self.config.to_dict() if callable(getattr(self.config, "to_dict", None)) else None
        event = self._event("schedule", backend=self.backend, model=getattr(self.twin, "model", None), schedule=schedule.to_dict(),
                            config=config, code=_code())
        self._call("on_calibrate_begin", event, schedule=schedule, twin=self.twin)

    def submission(self, folder: Any, *, emitted: bool = True) -> None:
        if folder is None:
            return
        self._call("on_submission", self._event("submission", submission=str(folder), emitted=bool(emitted)))

    def collect(self, raw: Mapping[str, Any]) -> None:
        self._call("on_collect_end", self._event("collect", **{**dict(raw), "live": True}))

    def step(self, raw: Mapping[str, Any]) -> None:
        """One raw step a runner hands over as its fit finishes ({routine, identifies, runs, played (a rig), collected, collect_s, fit_s,
        seconds, found {key: {value, ci95, method, unit}}, round, ...}): its plan position is added and it is sent, live."""
        routine = raw.get("routine")
        index = self.ids.index(routine) if routine in self.ids else self._steps
        self._steps += 1
        self._call("on_step_end", self._event("step", **{**dict(raw), "index": index, "round": raw.get("round", 0), "live": True}))

    def pending(self, submission: Any, caught: BaseException) -> None:
        folder = getattr(submission, "folder", None) or getattr(getattr(caught, "submission", None), "folder", None)
        self.ended = True
        self._call("on_calibrate_error", self._event("pending", submission=None if folder is None else str(folder), error=_words(caught),
                                                     commands=list(getattr(caught, "commands", None) or [])))

    # ---- the front door's

    def error(self, caught: BaseException) -> None:
        """The calibration raised: an "error" line, unless it never began (a refusal before its schedule writes nothing) or it already
        ended (RunsPending wrote "pending")."""
        if not self.began or self.ended:
            return
        self.ended = True
        self._call("on_calibrate_error", self._event("error", error=_words(caught)))

    def end(self, fitted: Any) -> None:
        """The fitted twin: the "done" line (its verdict and parameter rows), then fitted.callbacks_ (the callbacks still attached), so
        evaluate() reports to the same ledger, in this calibration's folder."""
        if not self.began and getattr(fitted, "plan_", None) is not None:
            self.begin(fitted.plan_)
        calibration = getattr(fitted, "calibration_", None)
        fields = {"passed": bool(getattr(calibration, "passed", False)), "failing": list(getattr(calibration, "failing", None) or []),
                  "seconds": getattr(calibration, "seconds", None), "rows": _rows(calibration)}
        folder = getattr(getattr(fitted, "submission_", None), "folder", None)
        if folder is not None:
            fields["submission"] = str(folder)
        self.ended = True
        self._call("on_calibrate_end", self._event("done", **fields), fitted=fitted)
        fitted.callbacks_ = tuple(self.alive)
        fitted._watched = {"calibration": self.id, "backend": self.backend, "started": self.started}

    @classmethod
    def evaluated(cls, fitted: Any, report: Any) -> None:
        """evaluate()'s report to the fitted twin's callbacks (getattr: a twin built without callbacks_ reports to none), in the folder of
        the calibration that fitted it."""
        callbacks = tuple(getattr(fitted, "callbacks_", ()) or ())
        if not callbacks:
            return
        info = getattr(fitted, "_watched", None) or {}
        backend = info.get("backend") or getattr(getattr(fitted, "calibration_", None), "backend", "sim")
        watch = cls(callbacks, fitted, backend, calibration=info.get("calibration"), started=info.get("started"))
        watch.began = True
        gates = [{"id": g.id, "title": g.title, "value": _plain(g.value), "rule": g.rule, "passed": bool(g.passed), "source": g.source}
                 for g in getattr(report, "gates", ())]
        event = watch._event("evaluate", passed=bool(report.passed), gates=gates, compare=_compare(report))
        watch._call("on_evaluate_end", event, report=report, fitted=fitted)
        fitted.callbacks_ = tuple(watch.alive)

    # ---- delivery

    def _event(self, kind: str, **fields: Any) -> dict:
        return {"schema": EVENTS_SCHEMA, "kind": kind, "calibration": self.id, "twin": self.twin_id, "utc": _utc(),
                "t": time.monotonic() - self.started, **fields}

    def _call(self, hook: str, event: dict, **objects: Any) -> None:
        for callback in list(self.alive):
            method = getattr(callback, hook, None)
            if not callable(method):
                continue
            try:
                method(event, **objects)
            except Exception as caught:   # WHY Exception, not BaseException: a Ctrl-C inside a hook still stops the calibration
                self._detach(callback, hook, caught)
        while self._errors:
            failure = self._errors.pop(0)
            for callback in list(self.alive):
                method = getattr(callback, "on_callback_error", None)
                if not callable(method):
                    continue
                try:
                    method(failure)
                except Exception as caught:
                    self._detach(callback, "on_callback_error", caught)

    def _detach(self, callback: Any, hook: str, caught: Exception) -> None:
        if callback in self.alive:
            self.alive.remove(callback)
        name = type(callback).__name__
        warnings.warn(f"sim2real calibrate: callback {name}.{hook} raised {caught!r}; detached, the calibration goes on", RuntimeWarning,
                      stacklevel=3)
        # WHY queued until this event has reached every callback: a ledger listed after the one that raised still writes the event first
        self._errors.append(self._event("callback_error", callback=name, hook=hook, error=_words(caught)))


def _code() -> dict:
    """The sim2real commit running this calibration and whether its src/ is dirty (tracking.wandb_log.code_version, stdlib at import)."""
    try:
        from ..tracking.wandb_log import code_version  # noqa: PLC0415

        sha, dirty = code_version()
    except Exception:   # noqa: BLE001  (an observer's provenance never stops a calibration)
        return {"sha": "unknown", "dirty": None}
    return {"sha": sha, "dirty": bool(dirty)}


__all__ = ["EVENTS_SCHEMA", "TRACK_CHOICES", "TRACK_ENV", "Callback", "Ledger", "Watch", "calibrations_root", "resolve_callbacks"]
