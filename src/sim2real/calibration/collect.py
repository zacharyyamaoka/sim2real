"""A routine is collect + fit (PEP 0001 §3; Zach, 2026-11-12: "for deployment stuff to separate the data collection routine and then
fitting which just works on any type of data").

    data = sim2real.calibration.collect(twin)      # plan, then play every planned routine's runs once: {run_id: measured} + the plan
    fitted = twin.calibrate(data=data)             # fit from the recorded runs; the backend's measure is never called

The seam already splits each routine into runs(values) (what to record) and fit(measured, values, twin) (what to compute). collect() plays
the runs; calibrate(data=) fits them. WHY collect plans each routine's runs from the priors (plus CalibrationConfig.known): in the field
nothing has been fitted yet when the data is logged. The one exception is a step the schedule shows made after an earlier one (its commands
are made from what that step finds: the dynamics tapes in the homed frame): collect fits the steps it waits for as it goes, so the
made-after step is recorded the way a replay will build it, and calibrate(data=) replays without measuring and without a mismatch. A
routine that comes back for more (next_runs: rounds) is fitted as it goes too, since each round's runs are made after the last fit, and so
are the earlier steps whose found values its fit reads; the data then holds every round's runs, and calibrate(data=) replays the same
rounds, with the same commands, by run id. A run a fit asks for that the data does not hold is refused by name, never re-measured.

This module also holds the planner's side of RobotTwin.calibrate (fit_rig), so twin.py's hook stays a few lines.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import CalibrationConfig
from .plan import CalibrationPlan, CalibrationPlanError, declaration, plan


@dataclass(frozen=True)
class CalibrationData:
    """Recorded runs ready to fit: `runs` {run id: what the backend's measure returned}, `plan` the plan they were collected for, `noise`
    the noise model's dict they were drawn at (sim) or None."""
    runs: Mapping[str, Any]
    plan: CalibrationPlan
    noise: dict | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)


class _Recorder:
    """A planned routine that records the measurements its runs return (collect's stand-in for the routine). It fits nothing, unless
    `fits`: a step whose found values a later step's commands are made from (see _fitted_online), or a routine that comes back for more,
    whose round members (max_rounds, next_runs, converged) it carries so the runner plays its rounds."""

    def __init__(self, routine: Any, store: dict, *, fits: bool = False) -> None:
        self.id = routine.id
        self.identifies = tuple(getattr(routine, "identifies", ()))
        self.adjusts = tuple(getattr(routine, "adjusts", ()))
        if callable(getattr(routine, "next_runs", None)):
            # WHY fitted online (gap A2): a round's runs are made after the last fit, so collection cannot run ahead of fitting
            self.max_rounds, self.next_runs, fits = getattr(routine, "max_rounds", None), routine.next_runs, True
            if callable(getattr(routine, "converged", None)):
                self.converged = routine.converged
        self._routine, self._store, self._fits = routine, store, fits

    def runs(self, values):
        return self._routine.runs(values)

    def fit(self, measured, values, twin):
        self._store.update(measured)
        return self._routine.fit(measured, values, twin) if self._fits else {}


def _fitted_online(planned: CalibrationPlan) -> set[str]:
    """The steps collect fits as it goes: every step some made-after step's commands wait for (PlanStep.commands_after), every routine that
    comes back for more (next_runs), and the earlier steps whose found values those fits read (requires, uses, refines), so each is fitted
    on what a replay hands it."""
    steps = list(planned.steps)
    at = {s.routine: k for k, s in enumerate(steps)}
    writes = []
    for s in steps:
        d = declaration(s.routine_object)
        writes.append(set(d.identifies + d.configures + d.adjusts))
    # WHY an iterating step seeds the closure too (gap A2, fix round 1): its later rounds are made after its own fit, so that fit must
    # see in collect exactly what a replay hands it; an earlier step it reads left unfitted here would leave those keys at the priors,
    # and the replay would rebuild a round under the same run id with a different command (the same reason as a made-after step)
    iterating = {s.routine for s in steps if callable(getattr(s.routine_object, "next_runs", None))}
    online = {rid for s in steps for rid in s.commands_after} | iterating
    todo = list(online)
    while todo:
        k = at[todo.pop()]
        reads = set(steps[k].requires + steps[k].uses + steps[k].refines)
        for j in range(k):
            if steps[j].routine not in online and reads & writes[j]:
                online.add(steps[j].routine)
                todo.append(steps[j].routine)
    return online


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
    """Plan, then play every planned routine's runs once through the backend's measure (a run two routines share is played once); the
    steps a made-after step waits for, and every routine that comes back for more, are fitted as they go (see the module docstring).
    Returns CalibrationData(runs, plan);
    calibrate(data=...) fits it."""
    config = config or CalibrationConfig()
    runner = _rig_runner(twin)
    planned = plan(twin, config)
    noise = resolve_noise(runner, None, config)
    store: dict[str, Any] = {}
    online = _fitted_online(planned)
    runner.calibrate(model=twin.model, noise=noise, routines=[_Recorder(r, store, fits=r.id in online) for r in planned.routines],
                     known=config.known, schedule=planned)
    used = runner._noise(noise)
    return CalibrationData(runs=dict(store), plan=planned, noise=used.to_dict(), meta={"twin": planned.twin, "backend": "sim"})


def fit_rig(twin: Any, *, move_truth: Mapping[str, float] | None = None, noise: Any = None, config: CalibrationConfig | None = None,
            data: CalibrationData | None = None) -> tuple[Any, dict, CalibrationPlan]:
    """RobotTwin.calibrate's planner side on a rig: plan (or take the data's plan), resolve the noise, and run the rig's runner over the
    planned routines in the planned order, measuring or reading the recorded runs, held to the schedule (a known-now step plays exactly the
    runs it shows). Returns (RigCalibration, state, plan)."""
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
                                          measured=None if data is None else dict(data.runs), known=config.known, schedule=planned)
    return calibration, state, planned


__all__ = ["CalibrationData", "CalibrationPlanError", "collect", "fit_rig", "resolve_noise"]
