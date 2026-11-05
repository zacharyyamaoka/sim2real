"""The type cards' v2 schema (Zach, PROJECT - Sim2Real, "Proposed Work Flow Nov 5 2026"): model rungs with references, wear and
learned rungs, diagnostics and gates over black-box metrics, test types by setting, the coverage a rung needs, and the calibration
packages. Stdlib only. Additive: registry.py's v1 names are unchanged, and registry re-exports everything here, so a consumer
imports one module (`from type_cards import registry as reg`; `reg.Rung`, `reg.select_rung`, ...). The API is written down in
type_cards/CONTRACT.md; tests/test_contract.py holds this module to it.

Pure functions here need no card; the ones that look a card up (select a card's rung, check a card's drift) are in registry.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

SCHEMA = "sim2real.type_cards/2"

# A rung's kind. WHY three (Zach via the coordinator, 2026-11-05): the top of each ladder is learned: a grey-box residual (the best
# physics rung plus a small net on what it misses) and a black-box actuator network above it.
KINDS = ("physics", "residual", "learned")

# Where a test runs. WHY two (Zach, Nov 5: "this bench level work and then the customer facility work ... we need methods for
# recalibration in deployment as well as in the office"); a run is tagged with one of these.
SETTINGS = {
    "bench": "in the office: on the test rack or a bench rig, any input we like",
    "deployed": "in the customer's facility: live data from normal work, or a short maintenance routine",
}

# A parameter's role in a rung. WHY (the count Zach asked for is a model's size): config terms are read from the deployment's config
# receipt and assembly terms belong to the station the unit is mounted in; both are needed to run the model, neither is the type's own.
ROLES = ("model", "driver", "assembly", "config")

# Wear laws: how a wear parameter p grows with a usage u, from p0 at u = 0 with rate k (the rate is a parameter of the same rung).
WEAR_LAWS = {
    "linear": "p(u) = p0 + k·u",
    "sqrt": "p(u) = p0 + k·√u",
    "archard": "p(u) = p0 + k·Σ(load·distance): Archard, wear grows with the load carried times the distance slid",
}

DRIFT_MESSAGE = "model drift detected — recalibration required"
OUT_OF_COVERAGE = "out of coverage"
TWINNED_LIMIT = 1.5  # × floor: the README's ruler (held-out twin error ÷ the device's own floor; ≤ 1.5× is twinned)
DRIFT_THRESHOLD = 1.25  # live fidelity ÷ calibrated fidelity; settable per card and per call
# WHY 1.25 by default: a twin calibrated near 1.0× its floor fails the 1.5× twinned limit after a 50 % loss; warning at +25 % leaves
# room to recalibrate before a gate fails (RobotDx's gearbox.wear flags a 20 % friction change, the same order).


@dataclass(frozen=True)
class Reference:
    """Where to learn a model. Real and citable only: a DOI is checked against Crossref and a URL against the live web by
    type_cards/check_references.py (results in references_checked.json); a work with no stable URL is cited without one."""
    title: str               # authors (year). Title. Venue volume(issue):pages
    url: str = ""            # "" when cited without a URL
    kind: str = "paper"      # paper | book | chapter | standard | datasheet | doc | code | preprint
    doi: str = ""
    note: str = ""           # what in it this rung uses


@dataclass(frozen=True)
class Wear:
    """A parameter that grows with use: p(u) = law(p0, k, u). `rate` names the rate parameter k, a Parameter of the same rung."""
    usage: str               # deployment hours | output revolutions | torque-weighted revolutions | duty | vibration hours | belt distance
    unit: str                # h | rev | N·m·rev | A²·s | km ...
    law: str                 # a WEAR_LAWS key
    rate: str                # the rate parameter's name
    note: str = ""


@dataclass(frozen=True)
class Architecture:
    """A learned rung's network: its size is its weight count, not named physical parameters."""
    family: str                          # MLP | GRU | B-spline grid ...
    inputs: tuple[str, ...]              # the signals fed at each history step
    output: str                          # what it predicts (torque, residual torque, position error, pixel offset ...)
    history: int = 1                     # history samples per input signal
    history_dt_s: float | None = None    # spacing of the history samples
    hidden: tuple[int, ...] = ()         # units per hidden layer (MLP)
    activation: str = ""
    n_outputs: int = 1
    n_weights: int | None = None         # stated when the family is not an MLP (a GRU, a grid); an MLP's is computed

    @property
    def n_inputs(self) -> int:
        return len(self.inputs) * self.history

    @property
    def weights(self) -> int:
        return self.n_weights if self.n_weights is not None else mlp_weights(self.n_inputs, self.hidden, self.n_outputs)


def mlp_weights(n_in: int, hidden: Sequence[int], n_out: int = 1) -> int:
    """Weights and biases of a fully connected net: Σ (fan_in · fan_out + fan_out) over its layers."""
    sizes = [n_in, *hidden, n_out]
    return sum(a * b + b for a, b in zip(sizes[:-1], sizes[1:]))


@dataclass(frozen=True)
class CoverageNeed:
    """The coverage a rung needs before it may be fitted and judged. WHY per rung (Zach via the coordinator, 2026-11-05): learned
    rungs need far more data and do not extrapolate outside the cells they were trained on, so the coverage gate binds harder."""
    min_pct: float                       # % of the type's reachable headline cells the train split must visit
    min_samples: int = 1                 # train samples a cell needs to count
    extrapolates: bool = True            # False: judged only inside its covered cells; outside, the flag is OUT_OF_COVERAGE
    deployment_weighted_pct: float | None = None  # % of deployed samples that must fall in counted cells, where stated
    note: str = ""


@dataclass(frozen=True)
class Rung:
    """One model on a type's ladder. `parameters` is the WHOLE rung (cumulative), never only what it adds over the rung below."""
    key: str                             # M<k>: k is the highest layer it holds (CONTRACT.md, "Rung keys"); ".wear" marks its wear variant
    name: str
    parameters: tuple                    # registry.Parameter, every named parameter of the model (a learned rung has none)
    references: tuple[Reference, ...]
    equation: str = ""
    kind: str = "physics"                # a KINDS value
    architecture: Architecture | None = None
    base: str = ""                       # a residual rung: the key of the physics rung it corrects
    needs: CoverageNeed | None = None
    robotparts: str | None = None        # the robotparts model it is (models/actuator/<word> or lab/models/actuator/twin)
    implemented: str = ""                # where it runs today; "proposed: ..." when nowhere yet
    current: bool = False                # the one rung that equals the card's `model` (today's single model)
    note: str = ""

    @property
    def n_named(self) -> int:
        return len(self.parameters)

    @property
    def n_parameters(self) -> int:
        """Named parameters plus a net's weights: a physics rung counts its parameters, a learned rung its weights."""
        return self.n_named + (self.architecture.weights if self.architecture else 0)

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.parameters)

    @property
    def wear_parameters(self) -> tuple:
        return tuple(p for p in self.parameters if getattr(p, "wear", None) is not None)


@dataclass(frozen=True)
class RungScore:
    """A rung's held-out fidelity for the selection rule (× floor). A residual or learned rung's score is judged only on held-out
    data inside its covered cells (`in_coverage` True); samples outside them are counted, flagged OUT_OF_COVERAGE, never scored."""
    ratio: float
    in_coverage: bool = True
    out_of_coverage: int = 0             # held-out samples outside the covered cells (flagged, not scored)


@dataclass(frozen=True)
class Limit:
    """One side of a number that is fine: `op` "<=" or ">=" against `value` in `unit`. `value` None: set per unit (`note` says where)."""
    op: str
    value: float | None
    unit: str
    note: str = ""

    def ok(self, x: float, value: float | None = None) -> bool:
        v = self.value if value is None else value
        if v is None:
            raise ValueError(f"this limit is set per unit ({self.note or 'no value'}): pass value=")
        return x <= v if self.op == "<=" else x >= v if self.op == ">=" else _bad_op(self.op)

    def text(self) -> str:
        return f"{self.op} {self.value:g} {self.unit}".strip() if self.value is not None else f"{self.op} {self.note or 'per unit'}"


def _bad_op(op: str) -> bool:
    raise ValueError(f"a limit's op is <= or >=, not {op!r}")


@dataclass(frozen=True)
class Forecast:
    """A drift diagnostic's prediction: fit the wear law to the drift statistic's history over usage and solve for the crossing."""
    usage: str
    unit: str
    law: str                             # a WEAR_LAWS key
    parameters: tuple[str, ...] = ()     # the wear parameters behind the drift (Parameter.wear set on the card's wear rung)
    method: str = "least squares of the statistic on g(usage) (g = usage, or √usage for sqrt), solved for the threshold"


@dataclass(frozen=True)
class Diagnostic:
    """A metric plus a threshold (Zach, Nov 5: "Diagonistics build ontop of metrics, its just adding a threshold to a metric").
    Black box: it reads the metric, never a model parameter. kind "drift": live fidelity ÷ the calibrated value."""
    id: str
    metric: str                          # the Metric.id it reads
    threshold: Limit                     # the fine side; crossing it raises `level` with `message`
    level: str = "warning"               # warning | error
    message: str = ""
    kind: str = "threshold"              # threshold | drift
    baseline: str = ""                   # drift: what the live value is divided by
    settable: bool = True
    forecast: Forecast | None = None     # drift with a wear model: usage remaining until the threshold is crossed
    robotdx: str | None = None           # the RobotDx catalog entry it is, or a related one (`note` says which)
    note: str = ""


@dataclass(frozen=True)
class Gate:
    """A diagnostic with a target (Zach: "Gates we can set targets here, and see if passing or failing, or if not gated then we just
    observe it"). A metric no gate reads is observed, not gated."""
    id: str
    diagnostic: str                      # the Diagnostic.id
    target: Limit                        # pass when met
    acceptance: str = ""                 # the bam_rack_twin acceptance gate it is (T1-T11), where one exists
    note: str = ""


@dataclass(frozen=True)
class TestType:
    """A kind of test that identifies parameters, in one setting. WHY (Zach, Nov 5, "3. Test Type ... Will be different in deployed
    or in office"): recalibration has a method in both settings."""
    id: str
    title: str
    setting: str                         # a SETTINGS key
    identifies: tuple[str, ...]          # the parameter names it identifies (each a parameter of one of the card's rungs)
    how: str
    needs: tuple[str, ...] = ()          # instruments
    recalibration: bool = False          # a method to re-identify after drift, without the full schedule
    exists: str = ""                     # where it runs today; "proposed: ..." when nowhere yet
    duration: str = ""


@dataclass(frozen=True)
class CodeHome:
    repo: str                            # an absolute repo path
    path: str                            # a path inside it (checked to exist at `ref`, or in the working tree)
    ref: str = ""                        # a branch or commit when the code is not on the repo's checked-out main
    note: str = ""


@dataclass(frozen=True)
class CalibrationPackage:
    """One of Zach's calibration packages (Nov 5: "we can focus as separate packages"): what it calibrates, the type cards it
    serves, and where its code lives today. Unknown is a valid answer; a guessed path is not."""
    id: str
    group: str                           # Zach's heading: Hand Eye, Kinematic Length, Servo Dynamic, Camera, PID, Hardstop/Homing/Rezeroing
    title: str
    serves: tuple[str, ...]              # card ids
    code: tuple[CodeHome, ...]
    status: str                          # exists | partial | proposed | unknown
    level: str = ""                      # e.g. arm | actuator
    note: str = ""
    references: tuple[Reference, ...] = ()


@dataclass(frozen=True)
class DriftResult:
    status: str                          # ok | warning
    ratio: float                         # live fidelity ÷ calibrated fidelity
    threshold: float
    message: str                         # DRIFT_MESSAGE when warning, else ""
    remaining: float | None = None       # usage left until the threshold is crossed (from the history and the forecast's law)
    unit: str = ""


# --- pure functions --------------------------------------------------------------------------------------------------------

def wear_value(p0: float, rate: float, usage: float, law: str) -> float:
    """A wear parameter after `usage`: linear and archard p0 + k u (archard's usage is load times distance), sqrt p0 + k √u."""
    if law not in WEAR_LAWS:
        raise ValueError(f"wear law {law!r} is not one of {sorted(WEAR_LAWS)}")
    if usage < 0:
        raise ValueError("usage is accumulated: never negative")
    return p0 + rate * (math.sqrt(usage) if law == "sqrt" else usage)


def wear_usage_at(p0: float, rate: float, limit: float, law: str) -> float | None:
    """The usage at which a wear parameter reaches `limit` (None when it never does: no growth, or growth away from it)."""
    if law not in WEAR_LAWS:
        raise ValueError(f"wear law {law!r} is not one of {sorted(WEAR_LAWS)}")
    if rate == 0 or (limit - p0) / rate < 0:
        return None
    g = (limit - p0) / rate
    return g * g if law == "sqrt" else g


def usage_remaining(history: Sequence[tuple[float, float]], threshold: float, law: str = "linear", op: str = "<=") -> float | None:
    """Usage left until a statistic leaves its fine side (`op` against `threshold`; a drift ratio is fine while <= its threshold),
    from its history [(usage, value), ...]: least squares of value on g(usage) (g = usage for linear and archard, √usage for sqrt),
    solved for the threshold, minus the last usage. 0.0 when the fit is past it already; None when it is not heading there or the
    history cannot fit a line (fewer than two distinct usages)."""
    if law not in WEAR_LAWS:
        raise ValueError(f"wear law {law!r} is not one of {sorted(WEAR_LAWS)}")
    if op not in ("<=", ">="):
        raise ValueError(f"op is <= or >=, not {op!r}")
    pts = [(float(u), float(v)) for u, v in history]
    if len({u for u, _ in pts}) < 2:
        return None
    g = (lambda u: math.sqrt(u)) if law == "sqrt" else (lambda u: u)
    xs, ys = [g(u) for u, _ in pts], [v for _, v in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    intercept = my - slope * mx
    u_now = max(u for u, _ in pts)
    value_now = intercept + slope * g(u_now)
    rising = op == "<="                       # "<=" is left by rising past the threshold, ">=" by falling below it
    if (value_now >= threshold) if rising else (value_now <= threshold):
        return 0.0
    if (slope <= 0) if rising else (slope >= 0):
        return None
    g_cross = (threshold - intercept) / slope
    if law == "sqrt" and g_cross < 0:
        return None
    return max(0.0, (g_cross * g_cross if law == "sqrt" else g_cross) - u_now)


def drift_check(diagnostic: Diagnostic, live: float, calibrated: float, threshold: float | None = None,
                history: Sequence[tuple[float, float]] | None = None) -> DriftResult:
    """A drift diagnostic on live data: ratio = live fidelity ÷ calibrated fidelity, warning (DRIFT_MESSAGE) past the threshold.
    `threshold` overrides the card's (settable); `history` [(usage, ratio)] adds the forecast's usage remaining."""
    if diagnostic.kind != "drift":
        raise ValueError(f"{diagnostic.id} is not a drift diagnostic")
    if calibrated <= 0:
        raise ValueError("the calibrated fidelity must be positive (it is a ratio to the floor)")
    limit = diagnostic.threshold.value if threshold is None else float(threshold)
    ratio = live / calibrated
    fine = Limit(diagnostic.threshold.op, limit, diagnostic.threshold.unit).ok(ratio)
    remaining, unit = None, ""
    if history and diagnostic.forecast:
        remaining = usage_remaining(history, limit, diagnostic.forecast.law, diagnostic.threshold.op)
        unit = diagnostic.forecast.unit
    return DriftResult("ok" if fine else "warning", ratio, limit, "" if fine else (diagnostic.message or DRIFT_MESSAGE), remaining, unit)


def coverage_flag(rung: Rung, cell, trained_cells) -> str | None:
    """None when `rung` may be judged at `cell`; OUT_OF_COVERAGE when a rung that does not extrapolate (residual, learned) is asked
    outside the cells it was trained on."""
    needs = rung.needs
    if needs is None or needs.extrapolates:
        return None
    return None if tuple(cell) in {tuple(c) for c in trained_cells} else OUT_OF_COVERAGE


def select(ladder: Sequence[Rung], held_out: Mapping[str, float | RungScore], limit: float = TWINNED_LIMIT) -> Rung | None:
    """The selection rule (CONTRACT.md): the LOWEST rung, in ladder order, whose held-out fidelity reaches the floor (held-out
    error ÷ the floor ≤ `limit`). A rung that does not extrapolate counts only with a RungScore judged inside its covered cells; a
    bare number for it is refused, so an out-of-coverage score can never select a learned rung. None when no rung reaches it."""
    for rung in ladder:
        score = held_out.get(rung.key)
        if score is None:
            continue
        if not isinstance(score, RungScore):
            if rung.needs is not None and not rung.needs.extrapolates:
                raise ValueError(f"{rung.key} ({rung.kind}) is judged only inside its covered cells: pass a RungScore")
            score = RungScore(float(score))
        if not score.in_coverage:
            continue
        if score.ratio <= limit:
            return rung
    return None
