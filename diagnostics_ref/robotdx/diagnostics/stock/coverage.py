"""Coverage: did the data visit the envelope the model will be used in?

Zach, 2026-10-24: "for a single servo I want to see datapoints like accross the full velocitys, acceleration position
range"; DP - Reality as Oracle: "lets make sure our dataset covers the entire distribution. so we always can be
interpolating". Discretize the declared envelope (his Oct 28 "the other is to discretize the space") and count the cells
the runs visited. Prior art: the identifiability argument in C - Practical Identifiability (only model what your
experiment can excite).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..core import Evidence, Limits, Measure, result
from ..data import Trajectory


@dataclass(frozen=True)
class CoverageConfig:
    x: str = "q_rad"  # any two channels; data-ui never needs to know what they mean
    y: str = "qd_rad_s"
    x_range: tuple[float, float] = (-np.pi, np.pi)  # the declared envelope (a datasheet or the deployment's range)
    y_range: tuple[float, float] = (-10.0, 10.0)
    bins: tuple[int, int] = (16, 16)
    min_samples: int = 5  # a cell counts as covered at >= this many rows
    controlled_only: bool = True
    limits: Limits = field(default_factory=lambda: Limits.at_least(0.5, warn=0.8))  # proposed: 80 % of cells warn, 50 % fail


def coverage(config: CoverageConfig, runs: Sequence[Trajectory]):
    """Fraction of the envelope's cells with >= ``min_samples`` rows; the 2-D counts are the payload."""

    xs, ys = [], []
    for run in runs:
        if not (run.has(config.x) and run.has(config.y)):
            continue
        keep = run.rows(controlled_only=config.controlled_only)
        xs.append(run.channel(config.x)[keep])
        ys.append(run.channel(config.y)[keep])
    title = f"coverage ({config.x} x {config.y})"
    if not xs:
        return result(config, value=None, unit="1", metric="covered", limits=config.limits, title=title,
                      message=f"no run has {config.x} and {config.y}", code="NoChannel")
    x, y = np.concatenate(xs), np.concatenate(ys)
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    counts, x_edges, y_edges = np.histogram2d(x, y, bins=list(config.bins), range=[list(config.x_range), list(config.y_range)])
    inside = int(counts.sum())
    covered = float(np.mean(counts >= config.min_samples))
    return result(config, value=covered, unit="1", metric="covered", limits=config.limits, title=title,
                  message=f"{covered:.0%} of {counts.size} cells have >= {config.min_samples} rows; {inside} of {x.size} rows inside the envelope",
                  measurements=(Measure("rows_outside", int(x.size - inside)), Measure(f"{config.x}_min", float(x.min())),
                                Measure(f"{config.x}_max", float(x.max())), Measure(f"{config.y}_abs_max", float(np.max(np.abs(y))))),
                  payload={"rows": (0.5 * (x_edges[:-1] + x_edges[1:])).tolist(), "cols": (0.5 * (y_edges[:-1] + y_edges[1:])).tolist(),
                           "cells": counts.astype(int).tolist(), "row_label": config.x, "col_label": config.y},
                  evidence=tuple(Evidence(run.run, f"{config.x},{config.y}") for run in runs))
