"""A routine is collect + fit (PEP 0001 §3; Zach, 2026-11-12: "for deployment stuff to separate the data collection routine and then
fitting which just works on any type of data").

    data = sim2real.calibration.collect(twin)      # plan, then play every planned routine's runs once: {run_id: measured} + the plan
    fitted = twin.calibrate(data=data)             # fit from the recorded runs; the backend's measure is never called

The seam already splits each routine into runs(values) (what to record) and fit(measured, values, twin) (what to compute). collect() plays
the runs; calibrate(data=) fits them. WHY collect plans each routine's runs from the priors (plus CalibrationConfig.known): in the field
nothing has been fitted yet when the data is logged. A routine whose runs depend on what an earlier routine found (homing corrected by the
measured gap) may then ask, at fit time, for a run the data does not hold; that is refused by name, never re-measured.

This module also holds the planner's side of RobotTwin.calibrate (fit_rig), so twin.py's hook stays a few lines.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import CalibrationConfig
from .plan import CalibrationPlan, CalibrationPlanError, plan


@dataclass(frozen=True)
class CalibrationData:
    """Recorded runs ready to fit: `runs` {run id: what the backend's measure returned}, `plan` the plan they were collected for, `noise`
    the noise model's dict they were drawn at (sim) or None."""
    runs: Mapping[str, Any]
    plan: CalibrationPlan
    noise: dict | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


class _Recorder:
    """A planned routine that records the measurements its runs return and fits nothing (collect's stand-in for the routine)."""

    def __init__(self, routine: Any, store: dict) -> None:
        self.id = routine.id
        self.identifies = tuple(getattr(routine, "identifies", ()))
        self.adjusts = tuple(getattr(routine, "adjusts", ()))
        self._routine, self._store = routine, store

    def runs(self, values):
        return self._routine.runs(values)

    def fit(self, measured, values, twin):
        self._store.update(measured)
        return {}


def _rig_runner(twin: Any):
    runner = getattr(twin, "runner", None)
    if runner is None or not hasattr(runner, "rig"):
        raise NotImplementedError("collect() and calibrate(config=, data=) run a rig on the one-click seam (sim2real.rig); the pendulum "
                                  "tracer runs sysid's five-function pipeline")
    return runner


def resolve_noise(runner: Any, noise: Any, config: CalibrationConfig):
    """The noise a run plays: calibrate(noise=) or CalibrationConfig.noise (both is refused), a number or a NoiseModel or its dict, then
    config.seed. None keeps the rig's measured 1x."""
    if noise is not None and config.noise is not None:
        raise ValueError("noise is given twice: calibrate(noise=...) and CalibrationConfig.noise; pass one of them")
    chosen = noise if noise is not None else config.noise
    if isinstance(chosen, Mapping):
        from ..rig import NoiseModel  # noqa: PLC0415

        chosen = NoiseModel.from_dict(chosen)
    if config.seed is not None:
        chosen = dataclasses.replace(runner._noise(chosen), seed=int(config.seed))
    return chosen


def collect(twin: Any, config: CalibrationConfig | None = None) -> CalibrationData:
    """Plan, then play every planned routine's runs once through the backend's measure (a run two routines share is played once).
    Returns CalibrationData(runs, plan); calibrate(data=...) fits it."""
    config = config or CalibrationConfig()
    runner = _rig_runner(twin)
    planned = plan(twin, config)
    noise = resolve_noise(runner, None, config)
    store: dict[str, Any] = {}
    runner.calibrate(model=twin.model, noise=noise, routines=[_Recorder(r, store) for r in planned.routines], known=config.known)
    used = runner._noise(noise)
    return CalibrationData(runs=dict(store), plan=planned, noise=used.to_dict(), meta={"twin": planned.twin, "backend": "sim"})


def fit_rig(twin: Any, *, move_truth: Mapping[str, float] | None = None, noise: Any = None, config: CalibrationConfig | None = None,
            data: CalibrationData | None = None) -> tuple[Any, dict, CalibrationPlan]:
    """RobotTwin.calibrate's planner side on a rig: plan (or take the data's plan), resolve the noise, and run the rig's runner over the
    planned routines in the planned order, measuring or reading the recorded runs. Returns (RigCalibration, state, plan)."""
    runner = _rig_runner(twin)
    if data is not None and not isinstance(data, CalibrationData):
        raise TypeError(f"data is a sim2real.calibration.CalibrationData (from collect()), not {type(data).__name__}")
    explicit = config is not None
    config = config or CalibrationConfig()
    planned = plan(twin, config) if (data is None or explicit) else data.plan
    if data is not None and noise is None and config.noise is None and data.noise is not None:
        noise = data.noise
    resolved = resolve_noise(runner, noise, config)
    calibration, state = runner.calibrate(model=twin.model, truth=move_truth, noise=resolved, routines=list(planned.routines),
                                          measured=None if data is None else dict(data.runs), known=config.known)
    return calibration, state, planned


__all__ = ["CalibrationData", "CalibrationPlanError", "collect", "fit_rig", "resolve_noise"]
