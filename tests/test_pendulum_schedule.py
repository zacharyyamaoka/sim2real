"""Gap F: the CAN 11 pendulum's calibrate() plays the schedule plan() shows, and every step in it can run (Zach, 2026-11-17).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src nice -n 19 taskset -c 2-5,16,17 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_pendulum_schedule.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src nice -n 19 taskset -c 2-5,16,17 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_pendulum_schedule.py

Zach, Daily Note 2026-11-17 "One click sim to real how does that tie in?":

    robotdescription -> robottwin
    robottwin.calibrate()
    internall mabye that does .generate_schedule() -> CalibrationSchedule
    and then you can pass that to something thats gonna like dispatch/execute it.

"Its almost like a JointTrajecotry though I think in that its a static description of the routines that will be run".

The gap this file holds the code to (found 2026-11-17 by the one-click and routines sessions): on the pendulum, his critical path,
plan(twin) returns a catalog schedule that calibrate() never plays. calibrate() runs sysid's pendulum pipeline directly and records a
sysid plan of model levels as plan_, and the catalog schedule picks routines nothing here can run (a clamp jig, a heating run, a known
mass) as stand-ins. Only rigs on the one-click seam (the UR wrist) play the schedule they show.

The ruler, written before the code (red first), and not to be edited by whoever turns it green:
1. plan(twin) on the pendulum shows only steps that can run: every step's routine object has runs() and fit(), none is a catalog
   stand-in, and every id is a registered catalog routine.
2. The schedule holds the two routines that recover CAN 11 in sim today: the excitation regression and the gap from load reversals.
3. The twin built from the description shows the same schedule as the hand-built one.
4. (slow) calibrate() plays exactly that schedule: the fitted twin's plan_ is a CalibrationPlan with the same ids, in the same order,
   and the fit still passes as it does today (calibration and evaluate() both pass).
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv (see the module docstring)")

import sim2real  # noqa: E402
from sim2real import RobotTwin  # noqa: E402
from sim2real.calibration import plan  # noqa: E402
from sim2real.calibration.plan import CalibrationPlan  # noqa: E402
from sim2real.cards import registry as reg  # noqa: E402

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
WORKERS = 2  # the powered rig's cap: at most 2 worker processes beside the arm (bam_ws feedback-live-rig-cpu-cap)
RECOVERS_CAN11 = {"servo.dynamics_regression", "servo.backlash_reversals_camera"}


@pytest.fixture(scope="module")
def twin():
    return sim2real.examples.pendulum_can11(workers=WORKERS)


@pytest.fixture(scope="module")
def schedule(twin):
    return plan(twin)


def test_every_step_in_the_schedule_can_run(schedule):
    assert schedule.steps, "the pendulum's schedule is not empty"
    stand_ins = [s.routine for s in schedule.steps if s.source == "catalog"]
    assert not stand_ins, f"catalog stand-ins that nothing here can run: {stand_ins}"
    for step in schedule.steps:
        obj = step.routine_object
        assert callable(getattr(obj, "runs", None)) and callable(getattr(obj, "fit", None)), f"{step.routine} cannot run"


def test_every_step_is_a_registered_routine(schedule):
    known = {r.id for r in reg.ROUTINES}
    assert set(schedule.ids) <= known, set(schedule.ids) - known


def test_the_schedule_holds_the_routines_that_recover_can11(schedule):
    assert RECOVERS_CAN11 <= set(schedule.ids), schedule.summary()


def test_the_description_twin_shows_the_same_schedule(schedule):
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    from_rd = RobotTwin.from_robot_description(station_description(11), workers=WORKERS)
    assert plan(from_rd).ids == schedule.ids


@pytest.mark.skipif(not SLOW, reason="SIM2REAL_SLOW=1: the CAN 11 oracle's calibration takes minutes")
def test_calibrate_plays_the_schedule_it_shows(twin, schedule, monkeypatch):
    # WHY every replay pool is watched (added 2026-11-17, the one-click session's point 3): bdfed7d capped workers in SimRunner only;
    # a scheduled routine that calls the pipeline without workers= reopens identify()'s 8-worker pool beside the powered arm. Every
    # pendulum replay goes through bam_rack_twin.budget.Replayer (imported at call time), so recording its workers catches any caller.
    from bam_rack_twin import budget  # noqa: PLC0415

    opened = []

    class Watched(budget.Replayer):
        def __init__(self, *args, **kwargs):
            opened.append(kwargs.get("workers", args[4] if len(args) > 4 else None))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(budget, "Replayer", Watched)
    fitted = twin.calibrate(on="sim", truth="sealed")
    assert opened and max(opened) <= WORKERS, f"replay pools opened with workers {sorted(set(opened))}, cap {WORKERS}"
    print(fitted.calibration_.summary(), flush=True)
    assert isinstance(fitted.plan_, CalibrationPlan), type(fitted.plan_)
    assert fitted.plan_.ids == schedule.ids, (fitted.plan_.ids, schedule.ids)
    assert fitted.calibration_.passed, fitted.calibration_.summary()
    report = fitted.evaluate()
    print(report.summary(), flush=True)
    assert report.passed, report.summary()
