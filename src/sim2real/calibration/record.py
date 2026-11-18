"""What calibrate() returns: one stable record, ``sim2real.calibration/1`` (PEP 0001 §7). The frozen schema is
tests/fixtures/calibration_record_v1.json (the UR wrist's real run in this shape); docs/CALIBRATE.md documents every key.

    fitted = twin.calibrate()
    fitted.record_.to_dict()          # {"schema": "sim2real.calibration/1", "twin", "backend", "model", "written", "seconds", "noise",
                                      #  "plan", "parameters", "routines", "passed", "failing", "evaluation"}
    CalibrationRecord.from_rig(doc["calibration"], report=doc["report"], description=describe("ur_wrist_test_rig"))
    CalibrationRecord.from_sysid(...)  # the pendulum tracer: one plan step per model rung sysid's identify() fitted (sysid_plan)

WHY plain dicts inside a frozen record and not a tree of dataclasses: the record is the JSON a page, a notebook or another machine reads;
the typed objects (CalibrationPlan, RigCalibration) stay on the fitted twin beside it (plan_, calibration_).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any

RECORD_SCHEMA = "sim2real.calibration/1"
RECORD_KEYS = ("schema", "twin", "backend", "model", "written", "seconds", "noise", "plan", "parameters", "routines", "passed", "failing",
               "evaluation")
PARAMETER_KEYS = ("key", "instance", "name", "unit", "nominal", "value", "ci95", "true", "error", "tolerance", "pass", "routine", "method",
                  "why_not")
ROUTINE_KEYS = ("routine", "identifies", "runs", "seconds", "found")
GATE_KEYS = ("id", "title", "value", "rule", "passed")


def _split(key: str, description: Any) -> tuple[str, str]:
    """(instance, name) of a key from the description's own instances (structured; no key is parsed). A key the description does not
    carry splits at its first dot."""
    if description is not None:
        for i in description.instances:
            for name in i.parameters:
                if f"{i.id}.{name}" == key:
                    return i.id, name
    inst, _, name = key.partition(".")
    return inst, name


def evaluation_from_report(report: Mapping[str, Any] | None) -> dict | None:
    """The record's `evaluation` from eval()'s report dict (RigReport.to_dict()): the gates and the verdict."""
    if report is None:
        return None
    gates = [{k: g.get(k) for k in GATE_KEYS} for g in report.get("gates", [])]
    passed = bool(report.get("passed", all(g["passed"] for g in gates)))
    return {"gates": gates, "passed": passed, "summary": f"{sum(bool(g['passed']) for g in gates)}/{len(gates)} gates pass"}


@dataclass(frozen=True)
class CalibrationRecord:
    """A calibration as one stable, documented record (docs/CALIBRATE.md). Build it with from_rig(), read it back with from_dict()."""
    twin: str
    backend: str
    model: str
    written: str
    seconds: float
    noise: dict
    plan: dict
    parameters: list
    routines: list
    passed: bool
    failing: list
    evaluation: dict | None = None
    schema: str = RECORD_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RECORD_SCHEMA:
            raise ValueError(f"schema {self.schema!r}; this reader knows {RECORD_SCHEMA!r}")

    def to_dict(self) -> dict:
        return copy.deepcopy({k: getattr(self, k) for k in RECORD_KEYS})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CalibrationRecord:
        missing = [k for k in RECORD_KEYS if k not in data]
        if missing:
            raise KeyError(f"a {RECORD_SCHEMA} record carries {list(RECORD_KEYS)}; this one lacks {missing}")
        return cls(**copy.deepcopy({k: data[k] for k in RECORD_KEYS}))

    def with_evaluation(self, report: Mapping[str, Any] | None) -> CalibrationRecord:
        """A NEW record carrying eval()'s gates (RigReport.to_dict())."""
        return CalibrationRecord.from_dict({**self.to_dict(), "evaluation": evaluation_from_report(report)})

    @classmethod
    def from_rig(cls, calibration: Mapping[str, Any], *, report: Mapping[str, Any] | None = None, description: Any = None,
                 plan: Any = None, written: str | None = None) -> CalibrationRecord:
        """A rig's calibration (RigCalibration.to_dict(), the seam's sim2real.rig/1) as a record, losing no row. `report`: eval()'s
        RigReport.to_dict(), or None before eval. `plan`: the CalibrationPlan (or its dict) that ran; without one, the plan is rebuilt from
        the routines as they ran, ordered by their catalog declarations. `description`: the twin's, to name each key's instance."""
        rows = calibration["rows"]
        parameters = []
        for row in rows:
            inst, name = _split(row["key"], description)
            parameters.append({"key": row["key"], "instance": inst, "name": name, "unit": row.get("unit"), "nominal": row.get("nominal"),
                               "value": row.get("recovered"), "ci95": list(row["ci95"]) if row.get("ci95") else None, "true": row.get("true"),
                               "error": row.get("error"), "tolerance": row.get("tolerance"), "pass": row.get("pass"),
                               "routine": row.get("routine"), "method": row.get("method", ""), "why_not": row.get("why_not", "")})
        routines = [{"routine": s["routine"], "identifies": list(s.get("identifies", [])), "runs": s.get("runs"), "seconds": s.get("seconds"),
                     "found": dict(s.get("found", {}))} for s in calibration["routines"]]
        if plan is None:
            plan = _plan_from_steps(calibration["routines"], description, calibration.get("rig"))
        plan_doc = plan.to_dict() if hasattr(plan, "to_dict") else dict(plan)
        failing = list(calibration.get("failing", [r["key"] for r in rows if r.get("pass") is False]))
        passed = calibration.get("passed")
        if passed is None:
            passed = any(r.get("pass") is True for r in rows) and not failing
        return cls(twin=calibration.get("rig") or calibration.get("twin", ""), backend=calibration.get("backend", "sim"),
                   model=calibration.get("model", ""), written=written or date.today().isoformat(), seconds=calibration.get("seconds"),
                   noise=dict(calibration.get("noise") or {}), plan=plan_doc, parameters=parameters, routines=routines, passed=bool(passed),
                   failing=failing, evaluation=evaluation_from_report(report))

    @classmethod
    def from_sysid(cls, calibration: Mapping[str, Any], *, fits: Sequence[Mapping[str, Any]], plan: Any, runs: int, noise: Mapping[str, Any],
                   twin: str, description: Any = None, report: Mapping[str, Any] | None = None, written: str | None = None) -> CalibrationRecord:
        """A sysid pipeline's calibration (the pendulum tracer's sim2real.twin.Calibration.to_dict()) as a record, losing no row. `fits`:
        the model rungs identify() fitted, in the order it fitted them, each {"rung", "model", "found": {key: value}} with only the values
        that rung estimated; `plan`: sysid_plan() over the same fits; `runs`: the train runs every rung's fit drew on (one shared
        collection); `noise`: the world's noise block as it was played. Each parameter row names the step of the rung the twin runs
        (calibration["rung"]) as its routine. WHY a converter onto from_rig's shape and not a second record builder: one code path writes
        every sim2real.calibration/1 record, so the two backends cannot drift apart."""
        rung = calibration["rung"]
        chosen = next((f for f in fits if f["rung"] == rung), None)
        if chosen is None:
            raise ValueError(f"the twin runs rung {rung}, which none of the fits ran ({[f['rung'] for f in fits]})")
        step_id = sysid_step_id(twin, rung)
        rows = [{**r, "routine": step_id if r["key"] in chosen["found"] else None} for r in calibration["rows"]]
        routines = [{"routine": sysid_step_id(twin, f["rung"]), "identifies": list(f["found"]), "runs": runs, "seconds": None,
                     "found": dict(f["found"])} for f in fits]
        seam = {"rig": twin, "backend": calibration.get("backend", "sim"), "model": calibration.get("model", ""),
                "seconds": calibration.get("seconds"), "noise": dict(noise), "rows": rows, "routines": routines,
                "passed": calibration.get("passed"), "failing": list(calibration.get("failing", []))}
        return cls.from_rig(seam, report=report, description=description, plan=plan, written=written)

    @classmethod
    def from_schedule(cls, calibration: Mapping[str, Any], *, routines: Sequence[Mapping[str, Any]], plan: Any, noise: Mapping[str, Any],
                      twin: str, description: Any = None, report: Mapping[str, Any] | None = None, written: str | None = None) -> CalibrationRecord:
        """The pendulum tracer's calibration (sim2real.twin.Calibration.to_dict()) played as its schedule (plan(twin), the example's
        routines.py; 2026-11-17) as a record, losing no row. `routines`: the steps as they ran, in order, each {"routine", "identifies",
        "runs", "seconds", "found"} with only the values that step estimated; `plan`: the CalibrationPlan that ran. Each parameter row names
        the step that found it (none: a structural constant of the twin's rung, or a value whose step was not in the plan). WHY onto
        from_rig's shape, as from_sysid: one code path writes every sim2real.calibration/1 record."""
        owner = {key: step["routine"] for step in routines for key in step.get("found", {})}
        rows = [{**r, "routine": owner.get(r["key"])} for r in calibration["rows"]]
        steps = [{"routine": s["routine"], "identifies": list(s.get("identifies", [])), "runs": s.get("runs"), "seconds": s.get("seconds"),
                  "found": dict(s.get("found", {}))} for s in routines]
        seam = {"rig": twin, "backend": calibration.get("backend", "sim"), "model": calibration.get("model", ""),
                "seconds": calibration.get("seconds"), "noise": dict(noise), "rows": rows, "routines": steps,
                "passed": calibration.get("passed"), "failing": list(calibration.get("failing", []))}
        return cls.from_rig(seam, report=report, description=description, plan=plan, written=written)

    def summary(self) -> str:
        identified = [p for p in self.parameters if p["pass"] is not None]
        lines = [f"{self.twin} on {self.backend}: {len(self.routines)} routines, {self.seconds} s; "
                 f"{sum(p['pass'] is True for p in identified)}/{len(identified)} identified values within tolerance"
                 + (f" (failing: {', '.join(self.failing)})" if self.failing else "")]
        if self.evaluation:
            lines.append(f"  eval: {self.evaluation['summary']}")
        return "\n".join(lines)


def sysid_step_id(twin: str, rung: str) -> str:
    """The plan-step id of one model rung a sysid pipeline fitted: sysid.<example>.<rung>. Never a catalog routine id: the catalog's
    routines did not run, so a record naming one would claim a routine nobody played."""
    return f"sysid.{twin}.{rung}"


def sysid_plan(twin: str, fits: Sequence[Mapping[str, Any]], *, level: str = "1x", wall_time_s: float | None = None,
               description: Any = None) -> Any:
    """The CalibrationPlan a sysid pipeline ran (the pendulum tracer: sysid/examples/<twin>/pipeline.py identify()): one fit step per
    model rung it fitted, in the order it fitted them, each identifying the values that rung estimated. Source "sysid", nothing dropped,
    nothing assumed. Each rung's fit is an independent regression over the same train runs, so no step requires, uses or refines another.
    Per-step wall time is None: identify() fits every rung in one call and times none of them apart (unknown stays unknown); the plan's
    totals carry the whole run's wall time. An instance parameter no rung estimated is listed uncovered."""
    from .plan import CalibrationPlan, PlanStep  # noqa: PLC0415

    steps = []
    for f in fits:
        steps.append(PlanStep(
            routine=sysid_step_id(twin, f["rung"]), title=f"{f['model']} fitted by sysid/examples/{twin} identify() (rung {f['rung']})",
            kind="identify", setting="bench", identifies=tuple(f["found"]), requires=(), uses=(), refines=(), after=(),
            why_here=f"identify() fits rung {f['rung']} here, an independent regression over the same train runs: nothing it needs comes "
                     "from another rung",
            wall_time_s=None, operator_time_s=0.0, equipment_usd=0.0, recovery=None, source="sysid"))
    found = {k for f in fits for k in f["found"]}
    uncovered = tuple((i.id, n, "sysid's identify() does not estimate it: the description's value serves")
                      for i in (description.instances if description is not None else ()) for n in i.parameters if f"{i.id}.{n}" not in found)
    return CalibrationPlan(tuple(s.routine for s in steps), tuple(steps), (), uncovered, (), "sysid",
                           {"wall_time_s": wall_time_s, "operator_time_s": 0.0, "equipment_usd": 0.0}, level, twin)


def _plan_from_steps(steps: Sequence[Mapping[str, Any]], description: Any, twin: str | None) -> dict:
    """A plan for routines that already ran (no CalibrationPlan kept): routine-likes carrying what ran (id, identifies, and adjusts as
    what they found beyond it), described by their catalog declarations, in the order they ran."""
    from .config import CalibrationConfig  # noqa: PLC0415
    from .plan import _steps, _totals  # noqa: PLC0415

    names = {f"{i.id}.{n}": n for i in description.instances for n in i.parameters} if description is not None else {}
    items = [SimpleNamespace(id=s["routine"], identifies=tuple(s.get("identifies", ())),
                             adjusts=tuple(sorted(set(s.get("found", {})) - set(s.get("identifies", ()))))) for s in steps]
    ran_ids = tuple(s["routine"] for s in steps)
    try:
        out, assumed, source = _steps(items, ["rig"] * len(items), names, CalibrationConfig())
    except ValueError:
        out = None
    if out is None or tuple(s.routine for s in out) != ran_ids:
        # WHY: a hand-ordered run that differs from the declared order is still a record of what ran: described in its own order
        out, assumed, source = _steps(items, ["rig"] * len(items), names, CalibrationConfig(order=ran_ids), validate=False)
    from .plan import CalibrationPlan  # noqa: PLC0415

    ran = CalibrationPlan(tuple(s.routine for s in out), out, (), (), assumed, source, _totals(out), "1x", twin)
    return ran.to_dict()
