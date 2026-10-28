"""The three shapes every stock diagnostic shares: ``Limits`` (thresholds as data), ``Evidence`` and ``Result``.

A diagnostic is a pure function ``diagnose(config, data) -> Result``. The config is a frozen dataclass (thresholds,
windows, which channel); the data is arrays (``data.Trajectory``) or rows; nothing else is read. WHY (Zach, 2026-10-28):
"you essentially like pass in a dataclass config, that paramterizes the diaginstics, and then at run time you just like
pass in the data". WHY the calculation and the threshold check are two steps (``measure`` then ``judge``): his old
``diagnostic-tracker.md``: "My goal was to seperate the calculation of the metric, and the checking of thresholds."
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

# ----- verdicts -------------------------------------------------------------------------------------------------
PASS, WARN, FAIL, NOT_RUN = "pass", "warn", "fail", "not_run"
VERDICTS = (PASS, WARN, FAIL, NOT_RUN)
Verdict = Literal["pass", "warn", "fail", "not_run"]
# WHY not_run ranks above warn (worse) and below fail: "can't tell is never green" (record v0 lesson 3) and a check
# that did not run must not count as a pass (record v0 lesson 5); nothing has shown it broken either. The numbers are
# RobotDx's level ranks (ok 0 < warn 1 < unknown 2 < stale 3 < error 4), so a worst-of over gates and levels agrees.
RANK = {PASS: 0, WARN: 1, NOT_RUN: 2, FAIL: 4}

# ----- the view contract with data-ui (PEP 0010 §10, 2026-10-28): exact strings, one hint per diagnostic -------------
HINTS = ("gate_matrix", "threshold_band", "kpi_trend", "rollup_tree", "evidence", "distribution", "level_history", "path_overlay")
EMITS = ("series", "matrix", "scalar")
BETTER = ("lower", "higher", "")
# What a number is FOR (Zach, 2026-10-14: "The gates set the bounds of the design space, and the KPI's are the things
# to optimize for"): headline = the one number on top; driver = a KPI that moves the headline; health = a watch item.
ROLES = ("headline", "driver", "health")
# The two families Zach uses (Jul 31 2026: "the error between actual sim and actual real, and the error between actual
# real and target"), plus the ones a part also needs.
# characteristic = a part's measured parameter against its datasheet (Zach, 2026-10-22: "datasheet vs measured values ...
# Similar to that GPU perf"): backlash, stiffness, Allan noise, SNR.
FAMILIES = ("real_vs_target", "sim_vs_real", "repeatability", "truthfulness", "coverage", "characteristic", "health", "envelope", "rollup")
CONSUMERS = ("robotdx", "sim2real")


@dataclass(frozen=True)
class Limits:
    """Warn/error bounds in the value's own unit. ``None`` = no bound on that side. A value strictly beyond a bound
    trips it; a value equal to the bound is inside (the same rule as the record's ``Measurement.level``)."""

    warn_low: float | None = None
    warn_high: float | None = None
    error_low: float | None = None
    error_high: float | None = None

    def __post_init__(self):
        present = [v for v in (self.error_low, self.warn_low, self.warn_high, self.error_high) if v is not None]
        if present != sorted(present):
            raise ValueError(f"limits must satisfy error_low <= warn_low <= warn_high <= error_high: {self}")

    @classmethod
    def at_most(cls, error: float, warn: float | None = None) -> "Limits":
        """Lower is better: fail above ``error``, warn above ``warn``."""

        return cls(warn_high=warn, error_high=error)

    @classmethod
    def at_least(cls, error: float, warn: float | None = None) -> "Limits":
        """Higher is better: fail below ``error``, warn below ``warn``."""

        return cls(warn_low=warn, error_low=error)

    @property
    def empty(self) -> bool:
        return all(v is None for v in (self.warn_low, self.warn_high, self.error_low, self.error_high))


def finite_or_none(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return value
    value = float(value) if not isinstance(value, int) else value
    return value if math.isfinite(value) else None


def judge(value: float | None, limits: Limits) -> tuple[str, str]:
    """(verdict, code). No value = not_run; no limits = pass (a reading, not a gate)."""

    value = finite_or_none(value)
    if value is None:
        return NOT_RUN, "NoValue"
    if limits.error_high is not None and value > limits.error_high:
        return FAIL, "AboveErrorLimit"
    if limits.error_low is not None and value < limits.error_low:
        return FAIL, "BelowErrorLimit"
    if limits.warn_high is not None and value > limits.warn_high:
        return WARN, "AboveWarnLimit"
    if limits.warn_low is not None and value < limits.warn_low:
        return WARN, "BelowWarnLimit"
    return PASS, ""


def worst(verdicts) -> str:
    verdicts = list(verdicts)
    return max(verdicts, key=RANK.__getitem__) if verdicts else NOT_RUN


@dataclass(frozen=True)
class Evidence:
    """Where a number came from: a run file (+ the array key or row), so a page can open the run behind a red cell."""

    path: str
    key: str = ""
    note: str = ""


@dataclass(frozen=True)
class Measure:
    """A secondary typed number beside the headline value (n, median, max ...)."""

    key: str
    value: float | int | None
    unit: str = "1"


def _canonical(value: Any) -> Any:
    """JSON-shaped and finite: what survives the record's string values unchanged (lists, not tuples; None, not NaN)."""

    def clean(item):
        if isinstance(item, float):
            return item if math.isfinite(item) else None
        if isinstance(item, Mapping):
            return {str(k): clean(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(v) for v in item]
        if hasattr(item, "tolist"):  # numpy scalar or array
            return clean(item.tolist())
        return item

    return json.loads(json.dumps(clean(value)))


@dataclass(frozen=True)
class Result:
    """One diagnostic, evaluated once, on one subject. Converts to a record-v0.2 ``DiagnosticStatus`` and back with no
    loss (``record.to_record`` / ``record.from_record``)."""

    diagnostic: str  # registry name, "servo.stop_error"
    title: str  # what a person reads, "stop error p90"
    verdict: str  # pass | warn | fail | not_run
    value: float | int | None  # the headline number; None = could not be computed
    unit: str  # UCUM: "mrad", "N.m", "Cel", "%", "1", "Hz", "s"
    metric: str = "value"  # the headline number's key, "p90"
    limits: Limits = field(default_factory=Limits)
    code: str = ""  # PascalCase machine reason; required whenever verdict != pass
    message: str = ""  # one human sentence
    subject: str = ""  # the entity path it is about; set by ``registry.evaluate``
    measurements: tuple[Measure, ...] = ()
    payload: Mapping[str, Any] | None = None  # the small series/matrix behind the number (``emits``)
    family: str = ""
    role: str = ""
    hint: str = ""  # one of HINTS: the stock data-ui view that shows it
    emits: str = "scalar"
    view_extra: str = ""  # a view outside the hints, with its one-line reason
    evidence: tuple[Evidence, ...] = ()
    caused_by: tuple[str, ...] = ()  # a composite's verdict names the members that caused it (record v0.1)
    config: Mapping[str, Any] = field(default_factory=dict)  # the config that produced it, as data (provenance)
    stamp: float | None = None  # evidence time (when it was measured), never compute time
    target: float | None = None  # for kpi_trend deltas and gauges; defaults to the bound that fails
    better: str = ""  # lower | higher | "" (two-sided or a reading)
    run: str = ""  # the run behind the worst number: where a click on a red cell lands
    t0: float | None = None  # the evidence window in that run, s from its start
    t1: float | None = None
    why: str = ""  # what to check next (RobotDx's why); empty on a pass
    basis: str = "computed"  # data-ui provenance basis: computed from measured rows; "derived" when read from a model file

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict {self.verdict!r} not in {VERDICTS}")
        if self.verdict != PASS and not self.code:
            raise ValueError(f"{self.diagnostic}: a {self.verdict} result needs a code")
        if self.emits not in EMITS:
            raise ValueError(f"emits {self.emits!r} not in {EMITS}")
        if self.hint and self.hint not in HINTS:
            raise ValueError(f"hint {self.hint!r} not in {HINTS}")
        if self.better not in BETTER:
            raise ValueError(f"better {self.better!r} not in {BETTER}")
        object.__setattr__(self, "value", finite_or_none(self.value))
        object.__setattr__(self, "target", finite_or_none(self.target))
        object.__setattr__(self, "t0", finite_or_none(self.t0))
        object.__setattr__(self, "t1", finite_or_none(self.t1))
        object.__setattr__(self, "measurements", tuple(Measure(m.key, finite_or_none(m.value), m.unit) for m in self.measurements))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "caused_by", tuple(self.caused_by))
        object.__setattr__(self, "config", _canonical(dict(self.config)))
        object.__setattr__(self, "payload", None if self.payload is None else _canonical(dict(self.payload)))


def config_dict(config: Any) -> dict[str, Any]:
    """A frozen config dataclass as plain data (nested Limits included)."""

    return _canonical(dataclasses.asdict(config)) if dataclasses.is_dataclass(config) else _canonical(dict(config))


def direction(limits: Limits) -> tuple[str, float | None]:
    """(better, target) read off the limits: an upper bound only = lower is better, its fail bound the target."""

    upper = limits.error_high if limits.error_high is not None else limits.warn_high
    lower = limits.error_low if limits.error_low is not None else limits.warn_low
    if upper is not None and lower is None:
        return "lower", upper
    if lower is not None and upper is None:
        return "higher", lower
    return "", None


def result(config: Any, *, value, unit: str, metric: str, limits: Limits, title: str, message: str,
           code: str | None = None, verdict: str | None = None, why: str = "", **rest) -> Result:
    """Judge ``value`` against ``limits`` (unless the caller already decided) and build the Result."""

    judged, judged_code = judge(value, limits)
    verdict = verdict or judged
    code = judged_code if code is None else code
    better, target = direction(limits)
    rest.setdefault("better", better)
    rest.setdefault("target", target)
    return Result(diagnostic="", title=title, verdict=verdict, value=value, unit=unit, metric=metric, limits=limits,
                  code=code if verdict != PASS else "", message=message, config=config_dict(config),
                  why=why if verdict != PASS else "", **rest)
