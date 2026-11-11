"""The rulers every comparison shares: one RMS, one centre, one clock, for real-vs-real (the floor) and model-vs-real (fidelity).

Moved from RobotDx (robotdx/diagnostics/data.py: rms, difference, on_common_clock, pair_rms, pairwise_rms, center) on 2026-11-10 (Zach,
proposal 2 step 4): RobotDx's stock checks and bam_rack_twin's gates computed T1-T4 from these, so they live once, here, and RobotDx
calls them. Behaviour unchanged to the bit; the RMS of a finite series is robot_msgs.compare.error_stats's own.

A series is ``(t, y)``: seconds from the tape's start and the signal, finite rows only.
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Sequence

import numpy as np
from robot_msgs.compare import error_stats

__all__ = ["rms", "center", "difference", "on_common_clock", "pair_rms", "pairwise_rms"]


def rms(values) -> float:
    """RMS of a series; NaN for an empty one. WHY robot_msgs.compare (Zach, 2026-11-10: "tracking error from robot_msgs.compare"): a finite
    series' RMS is error_stats(...).rms, the one definition. A series holding a NaN or an inf has no RMS over its gap: the plain mean of
    squares answers it (NaN, or inf), exactly as RobotDx's rms always did, where error_stats would skip the gap."""

    values = np.asarray(values, float)
    if not values.size:
        return math.nan
    stats = error_stats(values)
    return stats.rms if stats.n == values.size else float(np.sqrt(np.mean(values ** 2)))


def center(values: Sequence[float | None], how: str = "median") -> float:
    """``median`` or ``median_high`` (the stdlib names) of the finite values; NaN with none. WHY a choice: bam_rack_twin's per-class twin
    ratio takes ``sorted(v)[n // 2]``, which is ``statistics.median_high``; the floor takes ``statistics.median``."""

    kept = [v for v in values if v is not None and math.isfinite(v)]
    if not kept:
        return math.nan
    return float(statistics.median_high(kept) if how == "median_high" else statistics.median(kept))


def difference(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """data-ui PEP 0010 §4.4 ``difference(a, b)``: on a's own samples inside b's span, b(t_i) - a(t_i), b linearly interpolated; no row
    outside b's span (never extrapolates). Returns (t_i, b - a)."""

    (t_a, y_a), (t_b, y_b) = a, b
    inside = (t_a >= t_b[0]) & (t_a <= t_b[-1])
    return t_a[inside], np.interp(t_a[inside], t_b, y_b) - y_a[inside]


def on_common_clock(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray], dt: float) -> tuple[np.ndarray, np.ndarray]:
    """Two (t from 0, signal) series linearly interpolated onto one grid over their overlap: ``arange(0, min end, dt)``. WHY beside
    ``difference``: bam_rack_twin's floor (gate T1) is defined on this shared clock."""

    (t_a, y_a), (t_b, y_b) = a, b
    grid = np.arange(0.0, min(t_a[-1], t_b[-1]), dt)
    return np.interp(grid, t_a, y_a), np.interp(grid, t_b, y_b)


def pair_rms(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray], *, clock: str = "common", dt: float = 0.002) -> float:
    """RMS(b - a) on one clock: ``common`` (a shared grid of step dt) or ``a`` (a's own samples, PEP 0010)."""

    if clock == "a":
        return rms(difference(a, b)[1])
    y_a, y_b = on_common_clock(a, b, dt)
    return rms(y_b - y_a)


def pairwise_rms(series: Sequence[tuple[np.ndarray, np.ndarray]], *, clock: str = "common", dt: float = 0.002) -> list[tuple[int, int, float]]:
    """RMS of the difference for every pair (i < j). WHY one function: a fidelity ratio is never a ratio of two different rulers."""

    return [(i, j, pair_rms(a, b, clock=clock, dt=dt)) for (i, a), (j, b) in itertools.combinations(enumerate(series), 2)]
