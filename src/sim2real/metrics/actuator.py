"""The actuator's metrics: data in, numbers out. Performance (real vs target) and fidelity (model vs real), on plain arrays.

- ``tracking_statistic`` (performance): a statistic of (actual - target); rms, p95 and max are robot_msgs.compare.error_stats's own.
- ``stops`` / ``stop_summary`` (gate T4): the error left at every dwell, and the percentile of its size.
- ``floor`` (gate T1): the rack against itself, the median pairwise RMS over identical repeats; the denominator of T2 and T3.
- ``fidelity_ratios`` (gates T2 on q, T3 on tau): model error / floor per (model, tape class).
- ``pair_parts`` / ``run_parts`` / ``rest_holds`` / ``rest_summary`` / ``split_ratios`` (T2's split): an error's moving part and hold
  part, where a model comes to rest against the real joint, and moves / floor's moving part and |hold offset| / floor's hold part.

Moved from RobotDx's stock checks (robotdx/diagnostics/stock/tracking.py and fidelity.py) on 2026-11-10 (Zach, proposal 2 step 4): the
gates T1-T11 (bam_rack_twin acceptance) and RobotDx's stock checks were the same checks twice. The formulas live here once; RobotDx keeps
its Trajectory, its row masks and its Result, and calls these. Behaviour unchanged to the bit (every recorded rack run re-scored
identically before and after the move). Which rows count (the prelude, position mode, both modes) is the caller's mask: a mask is the
data adapter's, never a metric's.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from robot_msgs.compare import error_stats

from .series import center, pairwise_rms, rms

__all__ = ["HOLD_SPEED_RAD_S", "PARTS", "tracking_statistic", "stops", "stop_summary", "floor", "fidelity_ratios", "pair_parts", "run_parts",
           "rest_holds", "rest_summary", "split_ratios"]

HOLD_SPEED_RAD_S = 0.02  # |commanded speed| at or under this is a hold (bam_rack_twin budget.HOLD_SPEED_RAD_S)
PARTS = ("all", "moves", "holds")
STATISTICS = ("rms", "p95", "max", "final")


# --------------------------------------------------------------------------- performance: real vs target


def tracking_statistic(error: np.ndarray, t: np.ndarray, statistic: str = "rms", *, final_window_s: float = 0.5) -> float:
    """One run's tracking error (unscaled): ``rms``, ``p95`` (|e|), ``max`` (|e|) or ``final`` (mean |e| over the last ``final_window_s``).
    WHY robot_msgs.compare (Zach, 2026-11-10): rms, p95 and max are error_stats's rms, p95_abs and max_abs; ``final`` is the stop band a
    tracking run ends in, which ErrorStats does not hold (its ``final`` is the last sample alone)."""

    if statistic == "final":
        return float(np.mean(np.abs(error[t >= t[-1] - final_window_s])))
    if statistic not in STATISTICS:
        raise ValueError(f"unknown statistic {statistic!r}")
    stats = error_stats(error)
    return {"rms": rms(error), "p95": stats.p95_abs, "max": stats.max_abs}[statistic]


def stops(t: np.ndarray, q: np.ndarray, q_target: np.ndarray, qd_target: np.ndarray, *, dwell_min_s: float, settle_window_s: float,
          scale: float = 1e3, origin: float | None = None, open_end: bool = False) -> list[tuple[float, float, float]]:
    """(signed stop error x scale, dwell start, dwell end) of every dwell (>= ``dwell_min_s`` at zero commanded speed on one constant target)
    followed by more motion; the error is mean(q - q_target) over the dwell's last ``settle_window_s``; times from ``origin`` (default t[0]).
    WHY the last dwell does not count on a tape: it is parking, not a stop (T4). ``open_end``: a window cut by the clock, where the dwell it
    ends in is a stop still going (RobotDx's stream windows)."""

    origin = t[0] if origin is None else origin
    still = np.abs(qd_target) < 1e-9
    errors, start, count = [], 0, len(t)
    while start < count:
        if not still[start]:
            start += 1
            continue
        end = start
        while end + 1 < count and still[end + 1] and abs(q_target[end + 1] - q_target[start]) < 1e-9:
            end += 1
        if t[end] - t[start] >= dwell_min_s and (end + 1 < count or open_end):
            window = (t >= t[end] - settle_window_s) & (t <= t[end])
            errors.append((float(scale * np.mean(q[window] - q_target[window])), float(t[start] - origin), float(t[end] - origin)))
        start = end + 1
    return errors


def stop_summary(signed: Sequence[float], percentile: float = 90.0) -> dict[str, Any]:
    """T4's numbers over every stop: ``value`` the percentile of |error|, its count, median, max, the signed mean, and ``worst`` the index
    of the largest."""

    magnitudes = np.abs(np.array(signed))
    return {"value": float(np.percentile(magnitudes, percentile)), "n": len(signed), "median": float(np.median(magnitudes)),
            "max": float(magnitudes.max()), "mean_signed": float(np.mean(signed)), "worst": int(np.argmax(magnitudes))}


# --------------------------------------------------------------------------- the floor and fidelity: model vs real over real vs real


def floor(series: Sequence[tuple[np.ndarray, np.ndarray]], *, clock: str = "common", dt: float = 0.002,
          scale: float = 1e3) -> tuple[float, list[tuple[int, int, float]]]:
    """T1: (the median over every pair of RMS(e_a - e_b) x scale, every pair (i, j, scaled RMS)). ``series``: each repeat's (t from its
    tape's start, its tracking error or raw signal), finite rows only, each pair on its own overlap. Zach, DP - Reality as Oracle: "So
    important to baseline this and repeat it"."""

    pairs = pairwise_rms(series, clock=clock, dt=dt)
    scaled = [(i, j, scale * value) for i, j, value in pairs]
    return center([value for _, _, value in scaled], "median"), scaled


def fidelity_ratios(rows: Sequence[tuple[str, str, str, float]], floor_value: float,
                    how: str = "median_high") -> tuple[dict[tuple[str, str], list[float]], dict[tuple[str, str], float]]:
    """T2 / T3: each (model, run, class, error) row's error / floor, grouped by (model, class), and each group's ``how`` (median or
    median_high, center's names). Returns (the grouped ratios, each group's centre)."""

    by: dict[tuple[str, str], list[float]] = {}
    for model, _run, cls, error in rows:
        by.setdefault((model, cls), []).append(error / floor_value)
    return by, {key: center(values, how) for key, values in by.items()}


# --------------------------------------------------------------------------- T2's split: the moving part and the hold part
# WHY a split (bam_rack_twin acceptance T2, 2026-10-25, Zach's default pick taken while he was away and his to overrule): with no integrator a
# stop lands anywhere in the friction band and the rack does not repeat where, so one RMS mixes two questions. Moves are judged by RMS over the
# floor's moving part; holds by where the model comes to rest against the floor's hold part. bam_rack_twin's definitions (round7_study.floor_split
# / rms_split, budget.hold_rest_differences, stations_d_pass.t2_of).


def _rms_or_none(values: np.ndarray, scale: float) -> float | None:
    return scale * rms(values) if values.size else None


def pair_parts(a: tuple[np.ndarray, np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray, np.ndarray], *, dt: float, hold_speed: float,
               scale: float) -> dict[str, float | None]:
    """One pair of repeats (each (t from 0, error, commanded speed with NaN taken as 0)): a dt grid over the overlap, RMS(e_a - e_b) over all
    points, over the holds (a's commanded speed interpolated, |v| <= hold_speed) and over the moves; and the holds' share of the grid."""

    (t_a, e_a, v_a), (t_b, e_b, _) = a, b
    grid = np.arange(0.0, min(t_a[-1], t_b[-1]), dt)
    gap = np.interp(grid, t_a, e_a) - np.interp(grid, t_b, e_b)
    hold = np.abs(np.interp(grid, t_a, v_a)) <= hold_speed
    return {"all": _rms_or_none(gap, scale), "moves": _rms_or_none(gap[~hold], scale), "holds": _rms_or_none(gap[hold], scale),
            "hold_fraction": float(hold.mean()) if hold.size else None}


def run_parts(real: np.ndarray, model: np.ndarray, rows: np.ndarray, hold: np.ndarray, *, scale: float) -> dict[str, float | None]:
    """One (real, model) run on the real run's clock: RMS(real - model) on the scored ``rows``, on their ``hold`` rows (a subset of rows)
    and on their moving rows; and the holds' share of the scored rows."""

    gap = real - model
    finite = np.isfinite(gap)
    return {"all": _rms_or_none(gap[rows & finite], scale), "moves": _rms_or_none(gap[rows & ~hold & finite], scale),
            "holds": _rms_or_none(gap[hold & finite], scale), "hold_fraction": float(hold.sum() / rows.sum()) if rows.any() else None}


def rest_holds(t: np.ndarray, target: np.ndarray, q_real: np.ndarray, q_model: np.ndarray, rows: np.ndarray, *, min_hold_s: float,
               tail_s: float, scale: float) -> list[dict[str, float]]:
    """Every hold (a run of ``rows``: scored, a finite target, at hold speed) lasting >= ``min_hold_s``, its rest = mean(target - q) over its
    last ``tail_s``, folded to the real joint's side: ``model_minus_real`` > 0 is a model resting FARTHER from the target than the real
    joint, < 0 nearer or across it. ``t``: seconds from the run's start."""

    edges = np.flatnonzero(np.diff(np.concatenate([[0], rows.astype(int), [0]])))
    holds = []
    for start, end in zip(edges[::2], edges[1::2], strict=True):
        if t[end - 1] - t[start] < min_hold_s:
            continue
        tail = np.arange(start, end)[t[start:end] >= t[end - 1] - tail_s]
        rest_real = float(np.mean(target[tail] - q_real[tail]))
        rest_model = float(np.mean(target[tail] - q_model[tail]))
        side = 1.0 if rest_real >= 0.0 else -1.0
        holds.append({"t_start_s": float(t[start]), "t_end_s": float(t[end - 1]), "real": scale * side * rest_real,
                      "model": scale * side * rest_model, "model_minus_real": scale * side * (rest_model - rest_real)})
    return holds


def rest_summary(d: np.ndarray) -> dict[str, float]:
    """The rest offsets' (model - real, every hold) median, median |d|, p10, p90 and the share where the model rests farther."""

    return {"median": float(np.median(d)), "median_abs": float(np.median(np.abs(d))), "p10": float(np.percentile(d, 10)),
            "p90": float(np.percentile(d, 90)), "farther_fraction": float(np.mean(d > 0.0))}


def split_ratios(moves: float, floor_moves: float, rest_offset: float, floor_holds: float) -> tuple[float, float]:
    """T2's split judgement: (moves / the floor's moving part, |rest offset| / the floor's hold part)."""

    return moves / floor_moves, abs(rest_offset) / floor_holds
