"""calibrate()'s back end (PEP 0001, docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md): pick models per part, derive the
parameters, select the catalog routines that identify them by metric, order them from their declared dependencies, steer the whole run
with a CalibrationConfig, and return one stable record.

The one recovery reader is ``recovery`` (shared by the planner and the docs site); plan.py orders and selects, config.py steers,
record.py is what calibrate() returns, options.py is each type's offer, collect.py splits collect from fit (docs/CALIBRATE.md).
feedforward.py is a routine object a rig hands its runner: FeedforwardBench, the bench feedforward (arm.feedforward_bench, gap FF).
pid_tune.py is another: PidTune, PID tuna as the tune routine pid.pidtuna (gap C; it imports pidtuna only when it runs).
callbacks.py is what watches a calibration while it runs (calibrate(callbacks=), gap E): Ledger, the local ledger W&B copies.

Layer: like twin.py and rig.py, right of every folder (tests/test_layers.py names the folders); no layer folder imports this package.
"""

from . import recovery
from .callbacks import EVENTS_SCHEMA, Callback, Ledger, resolve_callbacks
from .collect import CalibrationData, collect
from .config import Budget, CalibrationConfig, RoutineOptions
from .feedforward import FeedforwardBench
from .options import TypeOptions, options
from .pid_tune import PidTune
from .plan import (CalibrationCycleError, CalibrationPlan, CalibrationPlanError, CalibrationSchedule, Declaration, PlanStep, Selection,
                   declaration, generate_schedule, order, plan, select)
from .record import RECORD_SCHEMA, CalibrationRecord

__all__ = ["EVENTS_SCHEMA", "RECORD_SCHEMA", "Budget", "Callback", "CalibrationConfig", "CalibrationCycleError", "CalibrationData",
           "CalibrationPlan", "CalibrationPlanError", "CalibrationRecord", "CalibrationSchedule", "Declaration", "FeedforwardBench", "Ledger",
           "PidTune", "PlanStep", "RoutineOptions", "Selection", "TypeOptions", "collect",
           "declaration", "generate_schedule", "options", "order", "plan", "recovery", "resolve_callbacks", "select"]
