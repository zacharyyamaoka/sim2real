"""Result <-> RobotDx's diagnostics record (``diagnostics-record/0``, revision 0.2: io-diagnostics ``contract/record.py``).

Stdlib only, and no import of the contract: this module writes the record's JSON shape (``to_dict`` of a
``DiagnosticStatus``), so a host loads it with ``contract.record.from_dict``. ``from_record(to_record(r)) == r`` for every
Result (tests/test_record.py proves it through the real contract when it is on disk).

| Result              | DiagnosticStatus                                   |
|---------------------|----------------------------------------------------|
| verdict             | level: pass->ok, warn->warn, fail->error, not_run->unknown (UNKNOWN is never green) |
| title, message      | name, message                                      |
| subject             | path                                               |
| code, stamp         | code, stamp                                        |
| value, unit, limits, metric | measurements[0] (key = metric; warn/error low/high in the value's unit) |
| measurements        | measurements[1:]                                   |
| caused_by           | caused_by                                          |
| diagnostic, family, role, hint, emits, view_extra, better, run, why, basis, target, t0, t1, config, payload, evidence | values, keys "dx.*" (strings for people; JSON where structured or numeric) |
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .core import FAIL, NOT_RUN, PASS, WARN, Evidence, Limits, Measure, Result

SCHEMA = "diagnostics-record/0"
RECORD_VERSION = "0.2"
SOURCE = "robotdx.diagnostics"
LEVEL_OF = {PASS: "ok", WARN: "warn", FAIL: "error", NOT_RUN: "unknown"}
VERDICT_OF = {level: verdict for verdict, level in LEVEL_OF.items()}
PREFIX = "dx."
_PLAIN = ("diagnostic", "family", "role", "hint", "emits", "view_extra", "better", "run", "why", "basis")
_NUMBERS = ("target", "t0", "t1")


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def to_record(result: Result, *, hardware_id: str = "", expected_period_s: float | None = None,
              source: str = SOURCE) -> dict[str, Any]:
    """The record line a host ingests. ``expected_period_s``: set it when a live consumer re-evaluates on a period
    (RobotDx), so the host can mark the row STALE; leave it None for a dataset evaluation (sim2real)."""

    primary = {"key": result.metric, "value": result.value, "unit": result.unit,
               **{k: v for k, v in vars(result.limits).items() if v is not None}}
    values = [{"key": PREFIX + name, "value": str(getattr(result, name))} for name in _PLAIN if getattr(result, name)]
    values += [{"key": PREFIX + name, "value": _json(getattr(result, name))} for name in _NUMBERS if getattr(result, name) is not None]
    if result.config:
        values.append({"key": PREFIX + "config", "value": _json(result.config)})
    if result.payload is not None:
        values.append({"key": PREFIX + "payload", "value": _json(result.payload)})
    if result.evidence:
        values.append({"key": PREFIX + "evidence", "value": _json([[e.path, e.key, e.note] for e in result.evidence])})
    record: dict[str, Any] = {"schema": SCHEMA, "record": "status", "level": LEVEL_OF[result.verdict], "name": result.title,
                              "message": result.message, "values": values, "path": result.subject, "source": source,
                              "measurements": [primary] + [{"key": m.key, "value": m.value, "unit": m.unit} for m in result.measurements]}
    for key, value in (("code", result.code), ("stamp", result.stamp), ("hardware_id", hardware_id),
                       ("expected_period_s", expected_period_s), ("caused_by", list(result.caused_by))):
        if value not in (None, "", []):
            record[key] = value
    return record


def from_record(record: Mapping[str, Any]) -> Result:
    """The inverse of ``to_record``: reads a record dict (ours, or ``contract.record.to_dict`` of one we wrote)."""

    if record.get("schema", SCHEMA) != SCHEMA or record.get("record", "status") != "status":
        raise ValueError("not a diagnostics-record/0 status")
    values = {pair["key"][len(PREFIX):]: pair["value"] for pair in record.get("values", []) if pair["key"].startswith(PREFIX)}
    measurements = list(record.get("measurements", []))
    primary = measurements[0] if measurements else {"key": "value"}
    limits = Limits(**{k: primary[k] for k in ("warn_low", "warn_high", "error_low", "error_high") if primary.get(k) is not None})
    return Result(
        diagnostic=values.get("diagnostic", ""), title=record.get("name", ""), verdict=VERDICT_OF[record.get("level", "unknown")],
        value=primary.get("value"), unit=primary.get("unit", ""), metric=primary["key"], limits=limits,
        code=record.get("code", ""), message=record.get("message", ""), subject=record.get("path", ""),
        measurements=tuple(Measure(m["key"], m.get("value"), m.get("unit", "")) for m in measurements[1:]),
        payload=json.loads(values["payload"]) if "payload" in values else None,
        **{name: values.get(name, "") for name in _PLAIN if name not in ("diagnostic", "emits")},
        **{name: json.loads(values[name]) if name in values else None for name in _NUMBERS},
        emits=values.get("emits", "scalar"),
        evidence=tuple(Evidence(*item) for item in json.loads(values.get("evidence", "[]"))),
        caused_by=tuple(record.get("caused_by", ())), config=json.loads(values.get("config", "{}")), stamp=record.get("stamp"))
