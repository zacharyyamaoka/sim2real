"""The RobotDx consumer: one robot's stream, evaluated window by window.

RobotDx is a system monitor over one robot's whole history (Zach, 2026-10-28). It needs no other function: it slices
the stream it already keeps into windows (his old ``queue_type = "count" | "timed"``, now the caller's job), calls the
same stock diagnostic on each window, and emits each Result as a record with ``expected_period_s`` = the step, so the
host marks the row STALE when evaluations stop arriving. sim2real calls the same functions on whole runs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterator

import numpy as np

from .core import Result
from .data import COLUMNS, Trajectory
from .record import to_record
from .registry import evaluate

_ARRAYS = ("t", *COLUMNS)


def windows(run: Trajectory, window_s: float, step_s: float) -> Iterator[Trajectory]:
    """Timed windows [end - window_s, end) stepping by ``step_s``; each a Trajectory over the same arrays."""

    t = run.t
    end = t[0] + window_s
    while end <= t[-1] + 1e-9:
        rows = (t >= end - window_s) & (t < end)
        if rows.sum() >= 2:
            sliced = {name: np.asarray(getattr(run, name))[rows] for name in _ARRAYS if getattr(run, name) is not None}
            yield replace(run, prelude_s=0.0, labels={**run.labels, "window_end_s": float(end - t[0])}, **sliced)
        end += step_s


def monitor(name: str, config: Any, run: Trajectory, *, subject: str, window_s: float, step_s: float,
            wall_start: float | None = None) -> list[tuple[Result, dict]]:
    """Evaluate ``name`` on every window; return (Result, record line) pairs, stamped with the window's end time."""

    out = []
    for window in windows(run, window_s, step_s):
        stamp = None if wall_start is None else wall_start + window.labels["window_end_s"]
        result = evaluate(name, config, [window], subject=subject, stamp=stamp)
        out.append((result, to_record(result, expected_period_s=step_s)))
    return out
