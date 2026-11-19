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

The twin holds its data (gap D): every fitted twin carries what it was fitted on as `fitted.data_`, and datasets grow by session.

    fitted = twin.calibrate(on="sim")                      # fitted.data_: the very recordings the fit read, one key per run
    refit = fitted.calibrate(data=fitted.data_ + more)    # refit on everything so far, from the description's priors, never measuring

WHY (Zach, 2026-11-17: "I think its the RobotTwin that can kidna like hold all the dataset"; 2026-11-18: "So on any dataset... now I
should be able to just like better fit the models no?"): a run is a run, whether a calibration routine or normal operation recorded it
(2026-11-11), so the twin keeps every one it was fitted on and a later fit reads all of them.

This module also holds the planner's side of RobotTwin.calibrate (fit_rig), so twin.py's hook stays a few lines.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import CalibrationConfig
from .plan import CalibrationPlan, CalibrationPlanError, declaration, plan

SESSION_MARK = "@"  # a run recorded again in another session is kept as "<key>@<session>", answering the same run id


def _base(key: str) -> str:
    """A recording key's run name: the key with its session suffix stripped ("gain0@3f9a1c2b4d5e" -> "gain0")."""
    return key.split(SESSION_MARK, 1)[0]


def session_id(twin: str, plan_ids: Any, noise: Any, **drawn: Any) -> str:
    """A deterministic id for one session of recordings: the twin, the routines the plan ran and the noise drawn (its seed in it), plus
    whatever else moved the draws when it is set (`drawn`: known values, a moved truth). The same inputs give the same id, so the same
    session collected twice is recognised and kept once when two datasets are joined."""
    doc = {"twin": twin, "plan": list(plan_ids), "noise": noise, **{k: v for k, v in drawn.items() if v}}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=repr).encode()).hexdigest()[:12]


@dataclass(frozen=True)
class CalibrationData:
    """Recorded runs ready to fit, and the runs kept to judge the fit.

    `runs` {recording key: what the backend measured}, the runs a fit may read; `plan` the plan they were collected for; `noise` the noise
    model's dict they were drawn at (sim), or what the transport said it played (real), or None. `meta`: `twin` (the twin's description
    id), `backend` ("sim" | "real") and `session` (one id per session of recordings; on the rack, the submission folder's name), plus, on
    real, `transport`, `submission`, `schedule_digest`, `files` {key: the file it was read from}, `refused` and `missing`; a grown dataset
    also lists its `sessions` {session: [keys]}. `held_out` {key: recording}: runs kept only to judge the fit, never fitted. `serves`
    {key: the run id it answers}: a key with no entry answers its own id (a rig's runs); the pendulum's keys answer "train", "held_out",
    "repeat" or "floor".

    WHY no key in both `runs` and `held_out`, compared by run name (sklearn's leakage rule, as eval() refuses it): a held-out run never
    becomes a training run, on any day it was recorded."""
    runs: Mapping[str, Any]
    plan: CalibrationPlan
    noise: dict | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)
    held_out: Mapping[str, Any] = field(default_factory=dict)
    serves: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        both = sorted({_base(k) for k in self.runs} & {_base(k) for k in self.held_out})
        if both:
            raise ValueError(f"run {both} is both a training run and a held-out run here (compared by run name, the session suffix "
                             "stripped): a held-out run never becomes a training run")
        stray = sorted(set(self.serves) - set(self.runs) - set(self.held_out))
        if stray:
            raise ValueError(f"serves names {stray}, which this dataset holds no recording for")

    def answering(self, run_id: str) -> tuple[str, ...]:
        """Every recording key that answers `run_id`, training runs first, each in the order it was added (a plain dataset: (run_id,) or
        ())."""
        return tuple(k for k in (*self.runs, *self.held_out) if self.serves.get(k, k) == run_id)

    @property
    def sessions(self) -> tuple[str, ...]:
        """The sessions this dataset holds, in the order they were added."""
        return tuple(s for s in self._by_session() if s is not None)

    def _by_session(self) -> dict[str | None, list[str]]:
        """{session: its keys}: a grown dataset's `sessions` list, else every key under `session` (None when it names none)."""
        present = [*self.runs, *self.held_out]
        listed = self.meta.get("sessions")
        out: dict[str | None, list[str]] = {}
        if isinstance(listed, Mapping):
            out = {sid: [k for k in keys if k in self.runs or k in self.held_out] for sid, keys in listed.items()}
        seen = {k for keys in out.values() for k in keys}
        rest = [k for k in present if k not in seen]
        if rest or not out:
            out.setdefault(self.meta.get("session") or None, []).extend(rest)
        return out

    def extend(self, other: CalibrationData) -> CalibrationData:
        """A NEW dataset holding this one's recordings and `other`'s (this one is unchanged); `data + other` is the same.

        It grows by session: a session this dataset already holds is kept once, however it comes back (`(a + b) + b` is `a + b`). A run
        recorded again in another session is kept beside the first as "<key>@<session>", answering the same run id, never overwriting
        it. Refused: anything but a CalibrationData; another twin's runs; the sim's draws joined with the rack's recordings; a run held out
        on one side and trained on on the other (compared by run name, the session suffix stripped). The plan and noise stay this one's.

        WHY by session and never by key (Zach, 2026-11-17: "incoeprating life time learning... Then you need to like consider offline
        datasets"): the same schedule played on two days gives the same run ids and two recordings, and both are data."""
        if not isinstance(other, CalibrationData):
            raise TypeError(f"a CalibrationData grows with another CalibrationData (collect(), a fitted twin's data_), not {type(other).__name__}")
        mine, theirs = self.meta.get("twin"), other.meta.get("twin")
        if mine != theirs:
            raise ValueError(f"these are two twins' runs, {mine!r} and {theirs!r}: a twin's data grows with its own runs only")
        ours, yours = self.meta.get("backend", "sim"), other.meta.get("backend", "sim")
        if ours != yours:
            # WHY never mixed: the sim's draws are graded against a hidden truth, the rack's against nothing but themselves
            raise ValueError(f"one dataset never mixes the sim's draws and the rack's recordings: this one holds backend {ours!r} runs, the "
                             f"other backend {yours!r}")
        clash = sorted(({_base(k) for k in self.runs} | {_base(k) for k in other.runs}) &
                       ({_base(k) for k in self.held_out} | {_base(k) for k in other.held_out}))
        if clash:
            raise ValueError(f"run {clash} is held out in one dataset and trained on in the other (compared by run name, the session suffix "
                             "stripped): a held-out run never becomes a training run")
        held, theirs_by = self._by_session(), other._by_session()
        unnamed = [label for label, d in (("this", held), ("the other", theirs_by)) if None in d]
        if unnamed:
            raise ValueError(f"{' and '.join(unnamed)} dataset names no session (meta['session']): a dataset grows by session, and "
                             "collect() and a fitted twin's data_ name theirs")
        runs, held_out, serves = dict(self.runs), dict(self.held_out), dict(self.serves)
        files = dict(self.meta.get("files") or {})
        for session, keys in theirs_by.items():
            if session in held:
                continue   # a session already held is kept once, however it comes back
            added = []
            for key in keys:
                trained = key in other.runs
                new = key
                if new in runs or new in held_out:
                    new, n = f"{key}{SESSION_MARK}{session}", 2
                    while new in runs or new in held_out:
                        new, n = f"{key}{SESSION_MARK}{session}.{n}", n + 1
                (runs if trained else held_out)[new] = (other.runs if trained else other.held_out)[key]
                if new != key or key in other.serves:
                    serves[new] = other.serves.get(key, key)
                if key in (other.meta.get("files") or {}):
                    files[new] = other.meta["files"][key]
                added.append(new)
            held[session] = added
        meta = {**self.meta, "sessions": {sid: list(keys) for sid, keys in held.items()}}
        if files:
            meta["files"] = files
        return CalibrationData(runs, self.plan, self.noise, meta, held_out, serves)

    def __add__(self, other: Any) -> CalibrationData:
        if not isinstance(other, CalibrationData):
            return NotImplemented
        return self.extend(other)


def check_data(data: Any, twin_id: str, *, on: str, move_truth: Mapping[str, float] | None = None) -> CalibrationData:
    """Refuse, before anything runs, data a calibrate(on=`on`, data=) cannot honestly fit: anything but a CalibrationData, recorded runs
    at a moved truth, another twin's runs, and runs of the other backend. Returns the data."""
    if not isinstance(data, CalibrationData):
        raise TypeError(f"data is a sim2real.calibration.CalibrationData (from collect(), or a fitted twin's data_), not {type(data).__name__}")
    if move_truth:
        raise ValueError("move_truth with data= is refused: recorded runs were drawn at the truth they were drawn at, and moving it now "
                         "would move nothing they hold; move the truth on a fresh calibration (no data=)")
    theirs = data.meta.get("twin")
    if theirs is not None and theirs != twin_id:
        raise ValueError(f"these runs are {theirs!r}'s, not {twin_id!r}'s: a twin refits from its own runs only")
    backend = data.meta.get("backend", "sim")
    if backend != on:
        # WHY refused both ways: rack runs fitted on the sim would be graded against a hidden truth that did not make them, and the sim's
        # draws refitted as rack runs would be judged over a floor they were never part of
        where = "recorded on the rack" if backend == "real" else "drawn on the sim"
        raise ValueError(f"these runs were {where} (backend {backend!r}): refit them with calibrate(on={backend!r}, data=...), never "
                         f"calibrate(on={on!r})")
    return data


def recorded(twin: Any, planned: CalibrationPlan, runs: Mapping[str, Any], noise: dict, *, known: Mapping[str, float] | None = None,
             truth_moved: Mapping[str, float] | None = None) -> CalibrationData:
    """The sim's recordings of one session as a CalibrationData, its session id from what drew them (session_id): collect() and a fitted
    rig twin's data_ build it the same way, so one session collected and one calibrated are recognised as the same."""
    twin_id = twin.description.id
    session = session_id(twin_id, planned.ids, noise, known=dict(known or {}), truth_moved=dict(truth_moved or {}))
    return CalibrationData(runs=dict(runs), plan=planned, noise=noise, meta={"twin": twin_id, "backend": "sim", "session": session})


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
        raise NotImplementedError("collect() runs a rig on the one-click seam (sim2real.rig); the pendulum tracer runs sysid's "
                                  "five-function pipeline, and its recorded runs are a fitted twin's data_ (calibrate(data=fitted.data_))")
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
    return recorded(twin, planned, store, used.to_dict(), known=config.known)


def fit_rig(twin: Any, *, move_truth: Mapping[str, float] | None = None, noise: Any = None, config: CalibrationConfig | None = None,
            data: CalibrationData | None = None) -> tuple[Any, dict, CalibrationPlan]:
    """RobotTwin.calibrate's planner side on a rig: plan (or take the data's plan), resolve the noise, and run the rig's runner over the
    planned routines in the planned order, measuring or reading the recorded runs (each run id answered by every recording `serves` maps
    to it), held to the schedule (a known-now step plays exactly the runs it shows). Returns (RigCalibration, state, plan); state["data"]
    is what the fitted twin holds (data_): all of `data` when it was given, else the very recordings the fit played."""
    runner = _rig_runner(twin)
    if data is not None:
        check_data(data, twin.description.id, on="sim", move_truth=move_truth)
    explicit = config is not None
    config = config or CalibrationConfig()
    planned = plan(twin, config) if (data is None or explicit) else data.plan
    if data is not None and noise is None and config.noise is None and data.noise is not None:
        noise = data.noise
    resolved = resolve_noise(runner, noise, config)
    # WHY only the training runs reach the runner: a held-out recording never answers a run a fit asks for
    served = {} if data is None else {"serves": {k: v for k, v in data.serves.items() if k in data.runs}}
    calibration, state = runner.calibrate(model=twin.model, truth=move_truth, noise=resolved, routines=list(planned.routines),
                                          measured=None if data is None else dict(data.runs), known=config.known, schedule=planned, **served)
    if data is None and "played" in state:
        data = recorded(twin, planned, state["played"], state["noise"].to_dict(), known=config.known, truth_moved=move_truth)
    state["data"] = data   # None only when a runner hands back no recordings
    return calibration, state, planned


__all__ = ["CalibrationData", "CalibrationPlanError", "check_data", "collect", "fit_rig", "recorded", "resolve_noise", "session_id"]
