"""robotdx.diagnostics: stock diagnostics, KPIs and gates as pure functions ``diagnose(config, data) -> Result``.

One library, two consumers:
- RobotDx (one robot, its whole history, a system monitor): slice a window of the live stream, evaluate, emit the
  Result as a ``diagnostics-record/0`` status with ``expected_period_s`` (``record.to_record``).
- sim2real (datasets of runs, model vs model vs real): evaluate over runs, keep the Results, draw them with data-ui.

    from robotdx.diagnostics import evaluate, Limits
    from robotdx.diagnostics.stock import StopErrorConfig
    r = evaluate("stock.stop_error", StopErrorConfig(limits=Limits.at_most(3.6)), runs, subject="rack/can12")
"""

from __future__ import annotations

from .core import FAIL, NOT_RUN, PASS, WARN, Evidence, Limits, Measure, Result, judge, worst
from .data import Trajectory
from .registry import REGISTRY, Spec, config_from_dict, evaluate, get, load_entry_points, load_toml, names, register
from . import stock  # noqa: F401  (registers the stock diagnostics)

__all__ = ["PASS", "WARN", "FAIL", "NOT_RUN", "Evidence", "Limits", "Measure", "Result", "judge", "worst", "Trajectory",
           "REGISTRY", "Spec", "config_from_dict", "evaluate", "get", "load_entry_points", "load_toml", "names", "register"]
