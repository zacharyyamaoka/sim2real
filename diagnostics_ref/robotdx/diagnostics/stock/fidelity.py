"""Sim vs real, judged against the rig's own floor.

- ``repeatability_floor`` (gate T1): run one tape N times from one start; the floor is the median over all pairs of
  RMS(e_a - e_b). Zach, DP - Reality as Oracle: "FANTASTIC POINT!! So important to baseline this and repeat it ... Two
  aspects accuracy and repeatability".
- ``model_error``: RMS(real - model) per run, for any number of models (a twin, a perfect servo, a lagged target).
  Zach, 2026-10-28: "we should support many way comparisons basically".
- ``fidelity_ratio`` (gates T2 on q, T3 on tau): model error / floor, per tape class.

All three use ``data.pairwise_rms`` / ``on_common_clock``: one ruler for real-vs-real and model-vs-real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..core import FAIL, PASS, WARN, Evidence, Limits, Measure, result
from ..data import TARGET_OF, Trajectory, center, difference, on_common_clock, pairwise_rms, rms


def _signal(run: Trajectory, channel: str, relative_to_target: bool, skip_prelude: bool) -> tuple[np.ndarray, np.ndarray]:
    """(t from the tape's start, signal): ``channel - channel_target`` when asked, else the raw channel; finite rows only."""

    values = run.channel(channel)
    if relative_to_target:
        values = values - run.channel(TARGET_OF[channel])
    keep = np.isfinite(values) & run.rows(skip_prelude=skip_prelude)
    t = run.t[keep]
    return t - t[0], values[keep]


@dataclass(frozen=True)
class FloorConfig:
    channel: str = "q_rad"
    relative_to_target: bool = True  # q_rad: the tracking error; tau_nm: the raw torque (gate T3's floor)
    skip_prelude: bool = True
    clock: str = "common"  # common: one grid of step dt over each pair's overlap (bam_rack_twin T1, the oracle);
    #                        a: the first run's own samples (data-ui PEP 0010 difference(a, b))
    dt: float = 0.002  # the common clock's step
    min_repeats: int = 5  # T1: >= 5 identical repeats
    scale: float = 1e3
    unit: str = "mrad"
    limits: Limits = field(default_factory=Limits)  # a floor is a reading, not a target; a bound flags a noisy rig


def repeatability_floor(config: FloorConfig, repeats: Sequence[Trajectory]):
    """Median pairwise RMS of the signal over identical repeats of one tape (each pair on its own overlap)."""

    title = f"repeatability floor ({config.channel})"
    if len(repeats) < 2:
        return result(config, value=None, unit=config.unit, metric="floor", limits=config.limits, title=title,
                      message=f"{len(repeats)} repeat(s): a floor needs at least 2", code="TooFewRepeats")
    series = [_signal(run, config.channel, config.relative_to_target, config.skip_prelude) for run in repeats]
    pairs = pairwise_rms(series, clock=config.clock, dt=config.dt)
    values = [config.scale * value for _, _, value in pairs]
    floor = center(values, "median")
    n = len(repeats)
    cells = [[0.0] * n for _ in range(n)]
    for (i, j, _), value in zip(pairs, values):
        cells[i][j] = cells[j][i] = value
    names = [run.run for run in repeats]
    worst_i = pairs[max(range(len(values)), key=values.__getitem__)][0]
    common = dict(measurements=(Measure("repeats", n), Measure("pairs", len(pairs)), Measure("max_pair", max(values), config.unit)),
                  payload={"rows": names, "cols": names, "cells": cells}, evidence=tuple(Evidence(name, config.channel) for name in names),
                  run=names[worst_i], t0=0.0, t1=float(series[worst_i][0][-1]),
                  why="repeats must start from one pose at one temperature; a pair far above the rest is a disturbed run")
    message = f"median of {len(pairs)} pairwise RMS over {n} repeats: {floor:.4g} {config.unit}"
    if n < config.min_repeats:
        return result(config, value=floor, unit=config.unit, metric="floor", limits=config.limits, title=title,
                      message=message + f" (needs {config.min_repeats} repeats)", verdict=FAIL, code="TooFewRepeats", **common)
    return result(config, value=floor, unit=config.unit, metric="floor", limits=config.limits, title=title, message=message, **common)


@dataclass(frozen=True)
class ModelErrorConfig:
    channel: str = "q_rad"
    skip_prelude: bool = False
    controlled_only: bool = True  # score where the real controller was tracking (mode 10)
    clock: str = "rows"  # rows: row by row on the real run's clock (a replay); a: difference(real, model) on the real
    #                      run's samples, the model interpolated (data-ui PEP 0010 §4.4)
    across_runs: str = "median"
    scale: float = 1e3
    unit: str = "mrad"
    limits: Limits = field(default_factory=Limits)


@dataclass(frozen=True)
class ModelRow:
    """One (model, run) score: what ``fidelity_ratio`` consumes. Produced by ``model_error`` or read from a twin's file."""

    model: str
    run_id: str
    cls: str
    error: float  # in the floor's unit


def model_error(config: ModelErrorConfig, pairs: Sequence[tuple[Trajectory, Trajectory]]):
    """RMS(real - model) per run; the headline is ``across_runs`` over runs. ``payload.breakdown.rows`` feeds fidelity_ratio."""

    rows = []
    for real, model in pairs:
        keep = real.rows(skip_prelude=config.skip_prelude, controlled_only=config.controlled_only)
        if config.clock == "rows":
            gap = model.channel(config.channel)[keep] - real.channel(config.channel)[keep]
        else:
            mine = model.rows(skip_prelude=config.skip_prelude, controlled_only=config.controlled_only)
            gap = difference((real.t[keep] - real.t[0], real.channel(config.channel)[keep]),
                             (model.t[mine] - model.t[0], model.channel(config.channel)[mine]))[1]
        gap = gap[np.isfinite(gap)]
        rows.append(ModelRow(model.situation, real.run, str(real.labels.get("class", "")), config.scale * rms(gap)))
    models = sorted({row.model for row in rows})
    title = f"model error ({config.channel})"
    if not rows:
        return result(config, value=None, unit=config.unit, metric="rms", limits=config.limits, title=title,
                      message="no (real, model) pair", code="NoPairs")
    value = center([row.error for row in rows], config.across_runs)
    worst = max(rows, key=lambda row: row.error)
    return result(config, value=value, unit=config.unit, metric="rms", limits=config.limits, title=title, run=worst.run_id,
                  message=f"{config.across_runs} RMS(real - {', '.join(models)}) over {len(rows)} runs: {value:.4g} {config.unit}",
                  measurements=(Measure("runs", len(rows)), Measure("worst_run", max(row.error for row in rows), config.unit)),
                  payload={"breakdown": {"rows": [[row.model, row.run_id, row.cls, row.error] for row in rows]}},
                  evidence=tuple(Evidence(row.run_id, f"{config.channel} real - {row.model}") for row in rows))


def rows_of(model_error_result) -> list[ModelRow]:
    return [ModelRow(*row) for row in (model_error_result.payload or {}).get("breakdown", {}).get("rows", [])]


@dataclass(frozen=True)
class FidelityInput:
    floor: float  # same unit as the rows' error
    rows: Sequence[ModelRow]
    floor_kind: str = "repeats"  # repeats | proxy: a proxy floor can never pass (T2 "partial" at best)
    floor_class: str = ""  # the tape class the floor was measured on
    unit: str = "mrad"  # the floor's (and the rows') unit


@dataclass(frozen=True)
class FidelityRatioConfig:
    model: str = "twin"  # the model judged; every other model in the rows is drawn beside it
    on_floor_class: bool = True  # T2: judge the twin on the floor's own tape class (WHY: bam_rack_twin acceptance)
    center: str = "median_high"  # bam_rack_twin takes sorted(v)[n // 2] per class
    class_limit: float | None = 2.0  # T2: every dataset class <= 2.0
    limits: Limits = field(default_factory=lambda: Limits.at_most(1.5))  # T2: <= 1.5 on the floor's tape


def fidelity_ratio(config: FidelityRatioConfig, data: FidelityInput):
    """Model error / floor per (model, class); the headline is the judged model on the floor's class."""

    by: dict[tuple[str, str], list[float]] = {}
    for row in data.rows:
        by.setdefault((row.model, row.cls), []).append(row.error / data.floor)
    ratios = {key: center(values, config.center) for key, values in by.items()}
    classes = sorted({cls for _, cls in ratios})
    models = sorted({model for model, _ in ratios})
    title = f"fidelity ratio ({config.model} / floor)"
    mine = {cls: value for (model, cls), value in ratios.items() if model == config.model}
    if not mine or not data.floor:
        return result(config, value=None, unit="1", metric="ratio", limits=config.limits, title=title,
                      message=f"no rows for model {config.model!r}" if data.floor else "no floor", code="NoRows" if data.floor else "NoFloor")
    if config.on_floor_class and data.floor_class in mine:
        value, basis = mine[data.floor_class], f"on the floor's {data.floor_class} tape"
    else:
        value = center([v for (model, _), values in by.items() if model == config.model for v in values], config.center)
        basis = "over all classes"
    worst_class = max(mine, key=mine.get)
    payload = {"x": [cls for model in models for cls in classes if (model, cls) in ratios],
               "y": [ratios[(model, cls)] for model in models for cls in classes if (model, cls) in ratios],
               "group": [model for model in models for cls in classes if (model, cls) in ratios],
               "x_label": "tape class", "y_label": "model error / floor"}
    measurements = (Measure("floor", data.floor, data.unit), Measure("worst_class_ratio", mine[worst_class]),
                    Measure("classes", len(mine)), Measure("models", len(models)))
    message = f"{config.model} is {value:.3g}x the floor {basis}; worst class {worst_class} {mine[worst_class]:.3g}x"
    judged_rows = [row for row in data.rows if row.model == config.model]
    worst_row = max(judged_rows, key=lambda row: row.error)
    common = dict(measurements=measurements, payload=payload, run=worst_row.run_id,
                  why="the term budget names the missing physics; a class far above the others is outside the fitted envelope")
    judged = result(config, value=value, unit="1", metric="ratio", limits=config.limits, title=title, message=message, **common)
    if config.class_limit is not None and mine[worst_class] > config.class_limit and judged.verdict == PASS:
        return result(config, value=value, unit="1", metric="ratio", limits=config.limits, title=title, verdict=FAIL,
                      code="ClassAboveLimit", message=message + f" > {config.class_limit}", **common)
    if data.floor_kind != "repeats" and judged.verdict == PASS:
        return result(config, value=value, unit="1", metric="ratio", limits=config.limits, title=title, verdict=WARN,
                      code="ProxyFloor", message=message + " (on a proxy floor, not identical repeats)", **common)
    return judged
