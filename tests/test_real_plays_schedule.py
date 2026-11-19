"""Gap F-real: calibrate(on="real") plays the same CalibrationPlan routines plan(twin) shows, the ones calibrate(on="sim") plays (2026-11-18,
red first).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src nice -n 19 taskset -c 2-5,16,17 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_real_plays_schedule.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src nice -n 19 taskset -c 2-5,16,17 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_real_plays_schedule.py

Zach, Daily Note 2026-11-17 ("One click sim to real how does that tie in?"):

    robottwin.calibrate()
    internall mabye that does .generate_schedule() -> CalibrationSchedule
    and then you can pass that to something thats gonna like dispatch/execute it.

and, 2026-11-18, on calibration before deployment: "Bench vs Deployment right ... We want a routine we can run on the robot".

Gap F (23a176f) made calibrate(on="sim") play exactly plan(twin): CAN 11's two routines (servo.backlash_reversals_camera, then
servo.dynamics_regression), each through its own runs() and fit(). calibrate(on="real") still fitted the returned runs with identify() in
one call and recorded a sysid plan of model rungs (sysid.pendulum_can11.M0..M4), so the schedule the pendulum shows was not the one the rack
would run, and the gap step never ran there. This file is the ruler for closing that, written before the code, and not to be edited by
whoever turns it green:

1. on="real" plays plan(twin)'s routines, in its order, each through its own fit(), over exactly the train runs the transport sent back:
   one submission, played and read back once for both steps; no held-out or floor run reaches a fit; the ruler is asked after the last fit.
2. What step 1 found reaches step 2: the regression is handed the gap the reversals step found (identify(..., gap=)) at the twin's worker
   cap, and the backlash row keeps that step's value, interval, method and routine.
3. The fitted twin carries that plan: plan_.ids == plan(twin).ids, the record's plan steps and routines are those ids (source "planner",
   never "sysid"), and the calibration's summary says "through <step 1> -> <step 2>".
4. A twin fitted on real plans the same schedule, never the catalog's stand-ins.
5. The sim's guards hold on real: a routine returning a value it does not declare is refused before the next step runs; a routine that
   reaches for the hidden truth is refused (each fit sealed), and the ruler is never asked.
6. (slow) Over the twin transport at the sealed truth: the same, every value lands within its tolerance of world.json, the gap is the
   pipeline's own gear_gap() over exactly the train runs that came back (the test calls it itself), and no pool opens more than 2 workers.

The fast half stubs only the pipeline the backend reaches (sysid's oracle.example_module, what RealRunner.pipeline() returns), emit and
ingest: no replay, no MuJoCo, no file, no bus. The routines themselves (sysid/examples/pendulum_can11/routines.py) are the real ones; their
fit() is wrapped to record each call and then runs unchanged (a tune step after the fits is recorded, not run: gap C grades it).

SIM2REAL_REQUIRE_RACK=1 (the cloud job sets it) turns the missing-venv skip into a failure. Landing needs the slow test green on a cloud VM,
reported as "1 passed", not merely "no failures".
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

if os.environ.get("SIM2REAL_REQUIRE_RACK") == "1":
    import bam_rack_twin  # noqa: F401  WHY: the cloud job sets this, so a wrong venv is red, never an all-skipped green
else:
    pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv (see the module docstring)")

import sim2real  # noqa: E402
from sim2real import real  # noqa: E402
from sim2real import twin as twin_module  # noqa: E402
from sim2real.calibration import plan  # noqa: E402
from sim2real.calibration.plan import CalibrationPlan  # noqa: E402
from sim2real.calibration.record import RECORD_KEYS  # noqa: E402
from sim2real.calibration import CalibrationPlanError  # noqa: E402
from sim2real.rig import Estimate, Run  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = "pendulum_can11"
EXAMPLE_DIR = REPO / "sysid" / "examples" / EXAMPLE
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
WORKERS = 2  # the powered rig's cap: at most 2 worker processes beside the arm (bam_ws feedback-live-rig-cpu-cap)
GAP_STEP, REGRESSION_STEP = "servo.backlash_reversals_camera", "servo.dynamics_regression"
FITS = (GAP_STEP, REGRESSION_STEP)  # the fit steps this ruler grades; a tune step after them (gap C) has its own ruler
GAP_KEY = "can11.backlash_rad"
# what the stub's gear_gap() finds: no prior (0, "a rigid twin") and no truth (0.002) carries these numbers, so they can only arrive by the
# gap step's own fit
FOUND_GAP = 0.0123
FOUND_CI = (0.0117, 0.0129)
STUB_GAP_METHOD = "the stub gear_gap's method (the gap step's own)"


@pytest.fixture(scope="module")
def twin():
    return sim2real.examples.pendulum_can11(workers=WORKERS)


@pytest.fixture(scope="module")
def schedule(twin):
    return plan(twin)


# --- the stubbed bench: the pipeline the backend reaches, a transport, emit and ingest ------------------------------------------------------


class _Bench:
    """A transport standing in for the rack: it plays nothing (emit and ingest are stubbed), has no hidden truth (ruler None, as hardware),
    and says when it is asked to play and for the ruler."""

    name = "bench"

    def __init__(self, events: list):
        self.events = events

    def folder(self, twin, digest):
        return Path("/nonexistent/sim2real-real-plays-schedule")  # emit is stubbed: nothing is ever written here

    def play(self, submission):
        self.events.append("play")
        return real.Recording((), self.name, {"sources": {"all": "the bench stub"}}, {})

    def ruler(self):
        self.events.append("ruler")
        return None


def _bench(monkeypatch, twin, schedule) -> SimpleNamespace:
    """Stub what on="real" reaches beyond the routines, record every call in order, and wrap each scheduled routine's fit() to record
    (its id, the runs it was handed, the values it saw) before running unchanged."""
    events: list[str] = []
    seen: dict[str, list] = {"emit": [], "ingest": [], "gear_gap": [], "identify": [], "fits": []}
    servo = twin.runner.typed()
    names = tuple(servo.parameters)
    rung = twin_module.SimRunner._rung(servo.type, twin.model)
    rungs = tuple(dict.fromkeys(("M0", "M2", "M3", "M4", rung)))
    pipeline_plan = SimpleNamespace(digest="5eed5eed5eed5eed", coverage={"train": {"pct": 90.0}}, train=[{"run": "t1"}, {"run": "t2"}],
                                    held_out=[{"run": "h1"}], document={"runs": [], "trajectories": []})
    train = {"t1": SimpleNamespace(name="t1"), "t2": SimpleNamespace(name="t2")}
    held_out = {"h1": SimpleNamespace(name="h1")}
    floor = {"f1": SimpleNamespace(name="f1")}

    def fit_of(gap: float, gap_ci) -> SimpleNamespace:
        """pipeline.Fit's shape: every rung's values, the bootstrap intervals of what each rung estimated, a method per rung. As the
        pipeline's identify(): the twin's rung carries the gap it was handed (or found), the others none; a handed gap has no interval here."""
        values = {k: {n: 0.5 + 0.1 * i for i, n in enumerate(names)} for k in rungs}
        for k in rungs:
            values[k]["backlash_rad"] = gap if k == rung else 0.0
        ci95 = {k: {n: (0.9 * v, 1.1 * v) for n, v in values[k].items() if n != "backlash_rad"} for k in rungs}
        if gap_ci is not None:
            ci95[rung]["backlash_rad"] = tuple(gap_ci)
        return SimpleNamespace(values=values, ci95=ci95, rows=1000, runs=len(train), methods={k: f"the stub regression, rung {k}" for k in rungs},
                               stock={})

    class Pipeline:
        """The surface of sysid/examples/pendulum_can11/pipeline.py the real backend's fit reaches, stubbed."""

        JOINT = "can11_hinge"
        RUNGS = rungs
        GAP_METHOD = STUB_GAP_METHOD

        @staticmethod
        def plan(description):
            return pipeline_plan

        @staticmethod
        def _rack():
            return None, None, SimpleNamespace(can_id=11)

        @staticmethod
        def gear_gap(measurements):
            events.append("gear_gap")
            seen["gear_gap"].append(dict(measurements))
            return SimpleNamespace(rad=FOUND_GAP, levels=(-FOUND_GAP / 2, FOUND_GAP / 2), ci95=FOUND_CI, runs=len(measurements))

        @staticmethod
        def identify(description, measurements, *, workers: int = 8, gap: float | None = None):
            events.append("identify")
            seen["identify"].append({"runs": dict(measurements), "workers": workers, "gap": gap})
            found = Pipeline.gear_gap(measurements) if gap is None else None  # as the pipeline's: no gap handed in, it finds its own
            return fit_of(found.rad if found is not None else float(gap), found.ci95 if found is not None else None)

    submission = SimpleNamespace(folder=Path("/nonexistent/sim2real-bench-submission"), digest=pipeline_plan.digest, minutes=12.0,
                                 runs=tuple({"run": n, "purpose": purpose} for purpose, runs in (("train", train), ("held_out", held_out),
                                                                                                  ("floor", floor)) for n in runs))
    submission.run_ids = lambda purpose=None: [r["run"] for r in submission.runs if purpose is None or r["purpose"] == purpose]

    def fake_emit(*args, **kwargs):
        events.append("emit")
        seen["emit"].append(any(a is pipeline_plan for a in (*args, *kwargs.values())))
        return submission

    def fake_ingest(recording, sub, **kwargs):
        events.append("ingest")
        seen["ingest"].append(sub is submission)
        return real.Ingested(train=train, held_out=held_out, floor=floor, missing={}, refused={}, skipped=(),
                             files={n: f"/nonexistent/{n}.npz" for n in (*train, *held_out, *floor)})

    _, oracle, _, _ = twin_module._sysid()
    monkeypatch.setattr(oracle, "example_module", lambda name: Pipeline)
    monkeypatch.setattr(real, "emit", fake_emit)
    monkeypatch.setattr(real, "ingest", fake_ingest)
    for cls in {type(r) for r in schedule.routines}:
        def recording(self, measured, values, handle, _fit=cls.fit):
            events.append(f"fit:{self.id}")
            seen["fits"].append((self.id, dict(measured), dict(values)))
            if getattr(self, "kind", "identify") == "tune":
                return {}  # WHY: a tune after the fits (gap C's pid.pidtuna on the fitted twin) is graded by its own ruler, not here
            return _fit(self, measured, values, handle)

        monkeypatch.setattr(cls, "fit", recording)
    return SimpleNamespace(events=events, seen=seen, transport=_Bench(events), train=train, held_out=held_out, floor=floor)


def _step_class(schedule, routine_id: str):
    return next(type(r) for r in schedule.routines if r.id == routine_id)


# --- 1. the schedule plan(twin) shows is what on="real" plays -------------------------------------------------------------------------------


def test_on_real_plays_the_schedule_plan_shows_over_the_runs_that_came_back(twin, schedule, monkeypatch):
    # the premise (sysid/examples/pendulum_can11/routines.py, gap F): the gap from reversals, then the regression that reads it
    assert list(schedule.ids)[:2] == list(FITS), schedule.summary()
    assert all(s.kind == "tune" for s in schedule.steps[2:]), "after the two fits only a tune may follow (gap C)"
    bench = _bench(monkeypatch, twin, schedule)
    twin.calibrate(on="real", transport=bench.transport)
    played = [e.split(":", 1)[1] for e in bench.events if e.startswith("fit:")]
    assert played == list(schedule.ids), f"on='real' played {played}; plan(twin) shows {list(schedule.ids)}"
    # one recorded session serves both steps (both read the train split): one submission, cut from the pipeline's own run schedule,
    # played once and read back once
    assert bench.seen["emit"] == [True], "one submission, cut from the pipeline's run schedule (pipeline.plan)"
    assert bench.events.count("play") == 1 and bench.seen["ingest"] == [True]
    # each step read exactly the train runs the transport sent back, in their order, the same objects; never a held-out or floor run
    for routine_id, measured, _ in (f for f in bench.seen["fits"] if f[0] in FITS):
        assert list(measured) == list(bench.train), (routine_id, list(measured))
        assert all(measured[name] is bench.train[name] for name in bench.train), routine_id
    # WHY after (sim2real.real's guard): the transport's ruler, the hidden truth of a simulator, is read only once every fit is done
    last_fit = max(i for i, e in enumerate(bench.events) if e.startswith("fit:"))
    assert "ruler" in bench.events and bench.events.index("ruler") > last_fit, bench.events


def test_the_gap_the_reversals_step_found_reaches_the_regression_and_the_record(twin, schedule, monkeypatch):
    bench = _bench(monkeypatch, twin, schedule)
    fitted = twin.calibrate(on="real", transport=bench.transport)
    assert len(bench.seen["gear_gap"]) == 1, "the gap is found once, by its own step"
    assert len(bench.seen["identify"]) == 1, "the regression runs once"
    call = bench.seen["identify"][0]
    assert call["gap"] == FOUND_GAP, f"identify() was handed gap={call['gap']!r}; the reversals step found {FOUND_GAP}"
    assert call["workers"] == WORKERS, "the twin's cap reaches identify()'s pool"
    assert list(call["runs"]) == list(bench.train)
    seen_by_regression = next(values for routine_id, _, values in bench.seen["fits"] if routine_id == REGRESSION_STEP)
    assert seen_by_regression.get(GAP_KEY) == FOUND_GAP, "the regression sees what the step before it found"
    record = fitted.record_.to_dict()
    row = next(p for p in record["parameters"] if p["key"] == GAP_KEY)
    # the backlash keeps the step that found it: its value, its interval, its method, its routine (the ladder was handed it)
    assert row["routine"] == GAP_STEP, row
    assert row["value"] == FOUND_GAP and row["ci95"] == list(FOUND_CI) and row["method"] == STUB_GAP_METHOD, row
    assert float(fitted.values_["backlash_rad"]) == FOUND_GAP and fitted.values_["backlash_rad"].source == STUB_GAP_METHOD
    # every value the regression declares is the regression's
    declared = set(_step_class(schedule, REGRESSION_STEP).identifies)
    dynamics = [p for p in record["parameters"] if p["key"] in declared]
    assert len(dynamics) == len(declared) and {p["routine"] for p in dynamics} == {REGRESSION_STEP}, [(p["key"], p["routine"]) for p in dynamics]


def test_the_fitted_twin_carries_the_plan_it_played(twin, schedule, monkeypatch):
    bench = _bench(monkeypatch, twin, schedule)
    fitted = twin.calibrate(on="real", transport=bench.transport)
    assert isinstance(fitted.plan_, CalibrationPlan), type(fitted.plan_)
    assert fitted.plan_.ids == schedule.ids and fitted.plan_.source == schedule.source == "planner", (fitted.plan_.ids, fitted.plan_.source)
    record = fitted.record_.to_dict()
    assert set(record) == set(RECORD_KEYS), "the frozen sim2real.calibration/1 record, no key added"
    assert record["backend"] == "real" and record["noise"]["transport"] == "bench"
    assert record["plan"]["source"] == "planner", record["plan"]["source"]
    assert [s["routine"] for s in record["plan"]["steps"]] == list(schedule.ids)
    assert [r["routine"] for r in record["routines"]] == list(schedule.ids), [r["routine"] for r in record["routines"]]
    assert [r["runs"] for r in record["routines"] if r["routine"] in FITS] == [len(bench.train)] * 2, "each fit read the train runs that came back"
    assert record["routines"][0]["found"] == {GAP_KEY: FOUND_GAP}
    assert f"through {GAP_STEP} -> {REGRESSION_STEP}" in fitted.calibration_.summary(), fitted.calibration_.summary()


def test_a_twin_fitted_on_real_plans_the_same_schedule(twin, schedule, monkeypatch):
    bench = _bench(monkeypatch, twin, schedule)
    fitted = twin.calibrate(on="real", transport=bench.transport)
    again = plan(fitted)
    stand_ins = [s.routine for s in again.steps if s.source == "catalog"]
    assert again.ids == schedule.ids and not stand_ins, again.summary()


def test_on_real_refuses_before_the_rack_moves_a_run_the_submission_cannot_fill(twin, schedule, monkeypatch):
    """Robot time is earned: a planned step that asks for a run the submission does not carry is refused before emit and play, never
    after the rack has spent its minutes."""
    bench = _bench(monkeypatch, twin, schedule)
    monkeypatch.setattr(_step_class(schedule, GAP_STEP), "runs", lambda self, values: [Run("nope", "train", "a run no split holds")])
    with pytest.raises(CalibrationPlanError, match="nope"):
        twin.calibrate(on="real", transport=bench.transport)
    assert "emit" not in bench.events and "play" not in bench.events, bench.events


def test_on_real_and_on_sim_share_one_routine_executor(twin, schedule, monkeypatch):
    """One loop for both backends, so their guards cannot drift: real.py reaches it as sim2real.twin._play_routines at call time."""
    import inspect  # noqa: PLC0415

    bench = _bench(monkeypatch, twin, schedule)
    calls = []
    original = twin_module._play_routines

    def spy(*args, **kwargs):
        calls.append(kwargs.get("servo"))
        return original(*args, **kwargs)

    monkeypatch.setattr(twin_module, "_play_routines", spy)
    twin.calibrate(on="real", transport=bench.transport)
    assert len(calls) == 1, calls
    assert "_play_routines(" in inspect.getsource(twin_module.SimRunner.calibrate), "the sim plays its routines through the same loop"


# --- 5. the sim's guards hold on real ----------------------------------------------------------------------------------------------------


def test_on_real_refuses_a_value_a_routine_does_not_declare(twin, schedule, monkeypatch):
    bench = _bench(monkeypatch, twin, schedule)
    gap_step = _step_class(schedule, GAP_STEP)
    inner = gap_step.fit

    def overreaching(self, measured, values, handle):
        return {**inner(self, measured, values, handle), "can11.gravity_nm": Estimate(5.0, None, "a value this step does not declare")}

    monkeypatch.setattr(gap_step, "fit", overreaching)
    with pytest.raises(KeyError, match="does not declare"):
        twin.calibrate(on="real", transport=bench.transport)
    assert "identify" not in bench.events, "refused before the next step runs"
    assert "ruler" not in bench.events


def test_on_real_fits_each_routine_sealed_from_the_hidden_truth(twin, schedule, monkeypatch):
    bench = _bench(monkeypatch, twin, schedule)
    *_, hidden = twin_module._sysid()

    def peeking(self, measured, values, handle):
        hidden.load(EXAMPLE)  # a routine that reaches for the hidden truth
        return {}

    monkeypatch.setattr(_step_class(schedule, GAP_STEP), "fit", peeking)
    with pytest.raises(hidden.SealedWorld):
        twin.calibrate(on="real", transport=bench.transport)
    assert "ruler" not in bench.events, "the ruler is never asked before the fit is done"


# --- 6. the acceptance: the whole schedule on the twin transport at the sealed truth --------------------------------------------------------


def hidden_truth() -> dict:
    return json.loads((EXAMPLE_DIR / "world.json").read_text())["truth"]


def tolerances() -> dict:
    return json.loads((REPO / "sysid" / "acceptance.json").read_text())["examples"][EXAMPLE]


def within(value, truth, rule) -> bool:
    kind, tol = rule
    return value is not None and math.isfinite(value) and abs(value - truth) <= (tol if kind == "abs" else tol * abs(truth))


@pytest.mark.skipif(not SLOW, reason="the whole CAN 11 schedule on the twin transport takes tens of minutes: SIM2REAL_SLOW=1")
def test_on_real_over_the_twin_plays_the_schedule_and_recovers_the_sealed_truth(twin, schedule, tmp_path, monkeypatch):
    pytest.importorskip("mujoco", reason="the twin transport replays the rack twin")
    # WHY every replay pool is watched (as tests/test_pendulum_schedule.py): every pendulum replay goes through
    # bam_rack_twin.budget.Replayer, imported at call time, so recording its workers catches any caller that drops the cap
    from bam_rack_twin import budget  # noqa: PLC0415

    opened = []

    class Watched(budget.Replayer):
        def __init__(self, *args, **kwargs):
            opened.append(kwargs.get("workers", args[4] if len(args) > 4 else None))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(budget, "Replayer", Watched)
    fitted = twin.calibrate(on="real", transport=real.TwinTransport(root=tmp_path, workers=WORKERS))
    print(fitted.runs_.summary(), flush=True)
    print(fitted.calibration_.summary(), flush=True)
    assert opened and max(opened) <= WORKERS, f"replay pools opened with workers {sorted(set(opened))}, cap {WORKERS}"
    record = fitted.record_.to_dict()
    assert fitted.plan_.ids == schedule.ids
    assert [s["routine"] for s in record["plan"]["steps"]] == list(schedule.ids) == [r["routine"] for r in record["routines"]]
    # step 1 is the pipeline's own gear_gap() over exactly the train runs that came back: an oracle this test calls itself
    module = real.RealRunner(twin.description, workers=WORKERS).pipeline()
    gap = module.gear_gap(dict(fitted.runs_.train))
    row = next(p for p in record["parameters"] if p["key"] == GAP_KEY)
    assert row["routine"] == GAP_STEP and row["value"] == gap.rad and row["ci95"] == list(gap.ci95), (row, gap)
    truth, rules = hidden_truth(), tolerances()
    recovered = {f"can11.{k}": float(v) for k, v in fitted.values_.items() if v is not None}
    missed = {k: (recovered.get(k), truth[k]) for k in rules["parameters"] if not within(recovered.get(k), truth[k], rules["parameters"][k])}
    assert not missed, f"outside tolerance of the hidden truth: {missed}"
    assert record["backend"] == "real" and record["passed"] is True and record["failing"] == []
