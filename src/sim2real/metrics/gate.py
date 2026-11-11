"""gate(value, target): is a number inside the range a target allows? The target is a robot_msgs Value, checked through robot_msgs.space.Space.

    from sim2real.metrics.gate import at_most, gate
    gate(1.42, at_most(1.5, "x floor")).passes    # True
    gate(1.61, at_most(1.5, "x floor")).violations # ('value=1.61 outside [-inf, 1.5]',)

WHY no range type of sim2real's own (Zach, 2026-11-10, proposal 2): a datasheet value and a gate target are the same noun, a number that
carries its range and its source, and robot_msgs already has it (Value(raw, unit, low=, high=, choices=, source=)) with the one check
(Space(msg).contains / .violations). A second range type would drift from it. So a one-sided limit is a Value whose other side is
infinite, and a boolean requirement is a Value whose only choice is True.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from robot_msgs.space import Space, Value, meta

__all__ = ["Verdict", "gate", "at_most", "at_least", "required", "rule_of"]


@dataclass(frozen=True)
class Verdict:
    passes: bool
    violations: tuple[str, ...] = ()  # Space's own lines: ``value=1.61 outside [-inf, 1.5]``


@dataclass(frozen=True)
class _Reading:
    """One ranged field. WHY: Space checks a message field by field, so a bare number rides in a one-field message."""

    value: Any


def _ranged(target: Any) -> dict:
    found = meta(target)
    if not found or (found["choices"] is None and (found["low"] is None or found["high"] is None)):
        # WHY refused: Space skips a field with no range, so a plain number as a target would pass everything (a ruler that cannot fail)
        raise TypeError(f"a gate's target is a robot_msgs Value with low and high (or choices), not {target!r}")
    return found


def gate(value: Any, target: Value) -> Verdict:
    """``value`` against ``target``'s range (its low..high, both inclusive, or its choices). None never passes; NaN is outside every range."""

    _ranged(target)
    if value is None:
        return Verdict(False, ("no value",))
    found = Space(_Reading(target)).violations(_Reading(value))
    return Verdict(not found, tuple(found))


def at_most(limit: float, unit: str | None = None, **evidence: Any) -> Value:
    """A target met at or under ``limit`` (one-sided: low is -inf)."""

    return Value(limit, unit, low=-math.inf, high=limit, **evidence)


def at_least(limit: float, unit: str | None = None, **evidence: Any) -> Value:
    """A target met at or over ``limit`` (one-sided: high is +inf)."""

    return Value(limit, unit, low=limit, high=math.inf, **evidence)


def required(**evidence: Any) -> Value:
    """The boolean requirement: met only by True. WHY a Value of 1 with the one choice True: Python forbids a bool carrying evidence."""

    return Value(1, None, choices=(True,), **evidence)


def rule_of(target: Value) -> tuple[str, Any]:
    """(the rule, the limit) a target reads as, for a verdict's own text: ("<=", high), (">=", low) or ("==", the one choice), each limit
    exactly as written (an int stays an int)."""

    found = _ranged(target)
    if found["choices"] is not None:
        return "==", found["choices"][0]
    if found["low"] == -math.inf:
        return "<=", found["high"]
    if found["high"] == math.inf:
        return ">=", found["low"]
    raise ValueError(f"{target!r} has two finite sides; a gate here is one-sided")
