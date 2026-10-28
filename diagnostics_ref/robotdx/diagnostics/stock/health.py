"""Health: the checks so stock that no part should hand-write them. Ported from Zach's ``bam_diagnostics`` task types
(like_keras archive, ``v2/common_tasks.py``): ``BoxChartTask`` -> ``box``, ``EventPeriodTask`` -> ``sample_rate``, the
moteus ``ErrorDef`` table -> ``fault_codes``. What changed, and why, is in docs/diagnostics-library-2026-10-28.md:
pure functions over a window the caller slices; units decided once (seconds AND Hz, never Hz-shaped numbers on a period);
an empty window is not_run, never OK; a threshold of 0 is a real limit, never "skip".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..core import FAIL, PASS, WARN, Evidence, Limits, Measure, judge, result, worst
from ..data import Trajectory


def _envelope(t: np.ndarray, y: np.ndarray, points: int = 400) -> tuple[list[float], list[float]]:
    """Min/max per bucket so a long stream draws as its true band in <= ``points`` points."""

    if len(t) <= points:
        return t.tolist(), y.tolist()
    buckets = np.array_split(np.arange(len(t)), points // 2)
    xs, ys = [], []
    for bucket in buckets:
        lo, hi = bucket[np.argmin(y[bucket])], bucket[np.argmax(y[bucket])]
        for index in sorted((lo, hi)):
            xs.append(float(t[index]))
            ys.append(float(y[index]))
    return xs, ys


@dataclass(frozen=True)
class BoxConfig:
    """Zach's ``BoxChartThresholds`` (min, max, mean_min/mean_max, std) as one frozen config of four ``Limits``."""

    channel: str = "temp_c"
    unit: str = "Cel"
    min: Limits = field(default_factory=Limits)
    max: Limits = field(default_factory=Limits)
    mean: Limits = field(default_factory=Limits)
    std: Limits = field(default_factory=Limits)
    headline: str = "max"  # which statistic is the headline number
    skip_prelude: bool = False


def box(config: BoxConfig, runs: Sequence[Trajectory]):
    """min / max / mean / std of one channel over the window (all rows of the given runs); worst statistic decides."""

    pieces = [(run.t[run.rows(skip_prelude=config.skip_prelude)], run.channel(config.channel)[run.rows(skip_prelude=config.skip_prelude)])
              for run in runs if run.has(config.channel)]
    title = f"{config.channel} box"
    if not pieces:
        return result(config, value=None, unit=config.unit, metric=config.headline, limits=getattr(config, config.headline),
                      title=title, message=f"no {config.channel} channel", code="NoChannel")
    offset, ts, ys = 0.0, [], []
    for t, y in pieces:  # runs end to end on one clock, so a window of many runs reads as one stream
        keep = np.isfinite(y)
        ts.append(t[keep] - t[0] + offset)
        ys.append(y[keep])
        offset = ts[-1][-1] + 1.0 if ts[-1].size else offset
    t, y = np.concatenate(ts), np.concatenate(ys)
    if y.size == 0:
        return result(config, value=None, unit=config.unit, metric=config.headline, limits=getattr(config, config.headline),
                      title=title, message="every sample is NaN", code="NoSamples")
    stats = {"min": float(y.min()), "max": float(y.max()), "mean": float(y.mean()), "std": float(y.std())}
    judged = {name: judge(stats[name], getattr(config, name)) for name in stats}
    verdict = worst(v for v, _ in judged.values())
    culprit = next((name for name in ("max", "min", "mean", "std") if judged[name][0] == verdict), config.headline)
    code = "" if verdict == PASS else f"{culprit.capitalize()}{judged[culprit][1]}"
    x, values = _envelope(t, y)
    return result(config, value=stats[config.headline], unit=config.unit, metric=config.headline,
                  limits=getattr(config, config.headline), title=title, verdict=verdict, code=code,
                  message=f"{config.channel}: min {stats['min']:.3g}, max {stats['max']:.3g}, mean {stats['mean']:.3g}, std {stats['std']:.3g} {config.unit}"
                          + ("" if verdict == PASS else f" ({culprit} out of bounds)"),
                  measurements=tuple(Measure(name, stats[name], config.unit) for name in ("min", "max", "mean", "std") if name != config.headline)
                               + (Measure("n", int(y.size)),),
                  payload={"x": x, "y": values, "x_label": "t (s, runs end to end)", "y_label": f"{config.channel} ({config.unit})",
                           "bands": {name: [getattr(config, name).warn_low, getattr(config, name).warn_high,
                                            getattr(config, name).error_low, getattr(config, name).error_high] for name in stats}},
                  evidence=tuple(Evidence(run.run, config.channel) for run in runs if run.has(config.channel)))


@dataclass(frozen=True)
class RateConfig:
    """ROS ``FrequencyStatus`` (min/max freq, tolerance) plus a gap count: Zach's ``EventPeriodTask`` with its unit fixed."""

    expected_hz: float = 100.0
    tolerance: float = 0.1  # ROS FrequencyStatus default: OK within [f (1 - tol), f (1 + tol)]
    gap_factor: float = 3.0  # a period > gap_factor / expected_hz is a dropped stretch (DroneCAN/record v0: 3x period)
    max_gaps: int = 0
    stamps_scale: float = 1.0  # 1e-3 for millisecond stamps (a RealSense hw_ms)


@dataclass(frozen=True)
class Stamps:
    t: np.ndarray
    source_id: str = ""


def sample_rate(config: RateConfig, data: Sequence[Stamps]):
    """Achieved rate (Hz) over each stream, the worst stream heading; gaps and period jitter beside it."""

    rows = []
    for stream in data:
        t = np.asarray(stream.t, float) * config.stamps_scale
        if t.size < 3:
            continue
        period = np.diff(t)
        rows.append({"id": stream.source_id, "rate": float((t.size - 1) / (t[-1] - t[0])), "median_period": float(np.median(period)),
                     "p99_period": float(np.percentile(period, 99)), "gaps": int(np.sum(period > config.gap_factor / config.expected_hz)),
                     "jitter": float(np.std(period))})
    low, high = config.expected_hz * (1 - config.tolerance), config.expected_hz * (1 + config.tolerance)
    limits = Limits(warn_low=low, warn_high=high, error_low=0.5 * config.expected_hz)
    title = "sample rate"
    if not rows:
        return result(config, value=None, unit="Hz", metric="rate", limits=limits, title=title, message="fewer than 3 stamps", code="NoStamps")
    head = min(rows, key=lambda row: row["rate"])
    gaps = sum(row["gaps"] for row in rows)
    judged = result(config, value=head["rate"], unit="Hz", metric="rate", limits=limits, title=title, message="")
    verdict, code = judged.verdict, judged.code
    if gaps > config.max_gaps and verdict == PASS:
        verdict, code = WARN, "DroppedSamples"
    return result(config, value=head["rate"], unit="Hz", metric="rate", limits=limits, title=title, verdict=verdict, code=code,
                  message=f"slowest stream {head['rate']:.4g} Hz (expected {config.expected_hz:g} +-{config.tolerance:.0%}); {gaps} gaps > {config.gap_factor:g} periods",
                  measurements=(Measure("median_period", head["median_period"], "s"), Measure("p99_period", head["p99_period"], "s"),
                                Measure("gaps", gaps), Measure("streams", len(rows))),
                  payload={"x": [row["id"] for row in rows], "y": [row["rate"] for row in rows], "x_label": "stream", "y_label": "rate (Hz)"},
                  evidence=tuple(Evidence(row["id"], "t") for row in rows))


# moteus fw/error.h (docs/protocol/registers.md, 0x00f): valid as faults in mode 1; 96-105 are limiters in running modes.
MOTEUS_CODES = {
    32: "calibration fault", 33: "motor driver fault", 34: "over voltage", 35: "encoder fault", 36: "motor not configured",
    37: "pwm cycle overrun", 38: "over temperature", 39: "outside limit", 40: "under voltage", 41: "config changed",
    42: "theta invalid", 43: "position invalid", 44: "driver enable fault", 45: "stop position deprecated",
    46: "timing violation", 47: "bemf feedforward no accel", 48: "invalid limits", 49: "position control error",
    50: "velocity control error",
    96: "max velocity", 97: "max power", 98: "max voltage (back-EMF)", 99: "max current", 100: "FET temperature",
    101: "motor temperature", 102: "torque cap", 103: "position bounds", 104: "flux braking", 105: "field weakening",
}
MODE_FAULT, MODE_TIMEOUT = 1, 11


@dataclass(frozen=True)
class FaultCodesConfig:
    fault_codes: tuple[int, int] = (32, 50)  # inclusive: a hard fault = FAIL
    limiter_codes: tuple[int, int] = (96, 105)  # a limiter engaged = not a fault
    limiter_share_warn: float = 0.02  # WHY 2 %: bam_rack_twin envelope's SATURATION_GATE (share of rows on the cap)
    timeout_is_fault: bool = True  # mode 11: the watchdog latched


def fault_codes(config: FaultCodesConfig, runs: Sequence[Trajectory]):
    """Hard faults and watchdog timeouts fail; a limiter engaged on more than ``limiter_share_warn`` of rows warns."""

    rows = faults = timeouts = 0
    shares: dict[int, int] = {}
    for run in runs:
        if run.fault is None:
            continue
        codes = np.asarray(run.fault).astype(int)
        mode = np.asarray(run.mode).astype(int) if run.mode is not None else np.zeros_like(codes)
        rows += codes.size
        hard = (codes >= config.fault_codes[0]) & (codes <= config.fault_codes[1])
        faults += int(np.sum(np.diff(np.concatenate([[0], (hard | (mode == MODE_FAULT)).astype(int)])) == 1))
        timeouts += int(np.sum(np.diff(np.concatenate([[0], (mode == MODE_TIMEOUT).astype(int)])) == 1))
        for code in np.unique(codes):
            if config.limiter_codes[0] <= code <= config.limiter_codes[1]:
                shares[int(code)] = shares.get(int(code), 0) + int(np.sum(codes == code))
    title = "fault and limiter codes"
    limits = Limits.at_most(0)
    if not rows:
        return result(config, value=None, unit="1", metric="faults", limits=limits, title=title, message="no fault channel", code="NoChannel")
    share = {code: count / rows for code, count in sorted(shares.items())}
    events = faults + (timeouts if config.timeout_is_fault else 0)
    verdict, code = (FAIL, "HardFault" if faults else "WatchdogTimeout") if events else (PASS, "")
    busiest = max(share.items(), key=lambda item: item[1], default=(None, 0.0))
    if verdict == PASS and busiest[1] > config.limiter_share_warn:
        verdict, code = WARN, "LimiterEngaged"
    named = ", ".join(f"{c} {MOTEUS_CODES.get(c, '?')} {s:.1%}" for c, s in share.items()) or "none"
    return result(config, value=events, unit="1", metric="faults", limits=limits, title=title, verdict=verdict, code=code,
                  message=f"{faults} hard fault(s), {timeouts} watchdog timeout(s) over {len(runs)} runs; limiters: {named}",
                  measurements=(Measure("timeouts", timeouts), Measure("rows", rows))
                               + tuple(Measure(f"limiter_{c}_share", s) for c, s in share.items()),
                  payload={"x": [f"{c} {MOTEUS_CODES.get(c, '?')}" for c in share], "y": list(share.values()),
                           "x_label": "limiter code", "y_label": "share of rows"},
                  evidence=tuple(Evidence(run.run, "fault") for run in runs if run.fault is not None))


__all__ = ["BoxConfig", "box", "RateConfig", "Stamps", "sample_rate", "FaultCodesConfig", "fault_codes", "MOTEUS_CODES", "FAIL"]
