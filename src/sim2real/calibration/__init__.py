"""calibrate()'s back end (PEP 0001, docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md): pick models per part, derive the
parameters, select the catalog routines that identify them by metric, order them from their declared dependencies, steer the whole run
with a CalibrationConfig, and return one stable record.

The one recovery reader is ``recovery`` (shared by the planner and the docs site); plan.py orders and selects, config.py steers,
record.py is what calibrate() returns, options.py is each type's offer, collect.py splits collect from fit (docs/CALIBRATE.md).

Layer: like twin.py and rig.py, right of every folder (tests/test_layers.py names the folders); no layer folder imports this package.
"""

from . import recovery
from .collect import CalibrationData, collect
from .config import Budget, CalibrationConfig, RoutineOptions
from .options import TypeOptions, options
from .plan import (CalibrationCycleError, CalibrationPlan, CalibrationPlanError, CalibrationSchedule, Declaration, PlanStep, Selection,
                   declaration, generate_schedule, order, plan, select)
from .record import RECORD_SCHEMA, CalibrationRecord

__all__ = ["RECORD_SCHEMA", "Budget", "CalibrationConfig", "CalibrationCycleError", "CalibrationData", "CalibrationPlan", "CalibrationPlanError",
           "CalibrationRecord", "CalibrationSchedule", "Declaration", "PlanStep", "RoutineOptions", "Selection", "TypeOptions", "collect",
           "declaration", "generate_schedule", "options", "order", "plan", "recovery", "select"]
