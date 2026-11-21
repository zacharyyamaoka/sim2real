"""L10's real-path fixes, pinned (written by the lane as proposals on claude/l10-g-proposed 41e075c; landed by the routines dispatcher
2026-11-20 beside the frozen rulers, which they do not replace).

1. on="real" takes CalibrationConfig(exclude=("pid.pidtuna",)) and no other config (twin._calibrate_real, real.calibrate(config=)).
2. a tune whose fit raises on the real path is recorded as a stopped step and the fits are kept (twin._play_routines
   keep_fits_on_failed_tune, passed by RealRunner.calibrate); on="sim" still raises.
3. preflight's record_matches_description leaves a tune step's keys (settings) to the gains check, on a cheap fit whose plan has the tune.

Rack venv (bam_rack_twin), fast: the real path runs through test_real_plays_schedule's stubbed bench (nothing plays)."""

import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.dirname(__file__))
pytest.importorskip("bam_rack_twin")

import test_preflight as pf  # noqa: E402
import test_real_plays_schedule as rps  # noqa: E402
from test_real_plays_schedule import schedule, twin  # noqa: E402, F401  (fixtures)

import sim2real  # noqa: E402
from sim2real.calibration import CalibrationConfig  # noqa: E402

TUNE = "pid.pidtuna"


def _tune_class(schedule):  # noqa: F811
    return next(type(r) for r in schedule.routines if r.id == TUNE)


def test_on_real_excluding_the_tune_plays_the_fits_only(twin, schedule, monkeypatch):  # noqa: F811
    bench = rps._bench(monkeypatch, twin, schedule)
    fitted = twin.calibrate(on="real", transport=bench.transport, config=CalibrationConfig(exclude=(TUNE,)))
    played = [e.split(":", 1)[1] for e in bench.events if e.startswith("fit:")]
    assert played == list(rps.FITS), played
    assert TUNE not in fitted.plan_.ids and any(r == TUNE and "excluded" in w for r, w in fitted.plan_.dropped), fitted.plan_.dropped
    assert fitted.settings_ == {} and fitted.proposals_ == {}
    assert bench.events.count("play") == 1, "the submission is the same one: the tune plays no run"


@pytest.mark.parametrize("config", [CalibrationConfig(), CalibrationConfig(exclude=("servo.backlash_reversals_camera",)),
                                    CalibrationConfig(exclude=(TUNE,), level="3x"), CalibrationConfig(exclude=(TUNE,), seed=1)])
def test_on_real_refuses_every_other_config_before_anything_plays(twin, schedule, monkeypatch, config):  # noqa: F811
    bench = rps._bench(monkeypatch, twin, schedule)
    with pytest.raises(NotImplementedError, match="one-click seam") as caught:
        twin.calibrate(on="real", transport=bench.transport, config=config)
    assert "exclude=('pid.pidtuna',)" in str(caught.value)
    assert bench.events == [], bench.events


def test_a_tune_that_fails_on_the_real_path_is_a_stopped_step_and_the_fits_are_kept(twin, schedule, monkeypatch):  # noqa: F811
    bench = rps._bench(monkeypatch, twin, schedule)

    def broken(self, measured, values, handle):
        raise ValueError("pidtuna drifted")

    monkeypatch.setattr(_tune_class(schedule), "fit", broken)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fitted = twin.calibrate(on="real", transport=bench.transport)
    assert any("pid.pidtuna failed: ValueError: pidtuna drifted" in str(w.message) for w in caught), [str(w.message) for w in caught]
    steps = {r["routine"]: r for r in fitted.record_.routines}
    assert list(steps) == list(schedule.ids)
    assert steps[TUNE]["stopped"] == "failed: ValueError: pidtuna drifted" and steps[TUNE]["found"] == {}, steps[TUNE]
    assert all("stopped" not in steps[r] for r in rps.FITS)
    assert fitted.settings_ == {} and fitted.proposals_ == {}
    assert fitted.values_ and fitted.calibration_.rows, "the fits the rack paid for are kept"


def test_a_tune_that_fails_on_the_sim_path_still_raises(twin, schedule, monkeypatch):  # noqa: F811
    from sim2real import twin as twin_module

    def broken(self, measured, values, handle):
        raise ValueError("pidtuna drifted")

    monkeypatch.setattr(_tune_class(schedule), "fit", broken)
    tune = next(r for r in schedule.routines if r.id == TUNE)
    with pytest.raises(ValueError, match="pidtuna drifted"):
        twin_module._play_routines([tune], {}, {}, twin_module.PipelineHandle(None, None, 1, "M4"), servo="can11")


def test_preflight_leaves_a_tune_steps_keys_to_the_gains_check():
    """pf._cheap_fit with the tune step's settings left out of its fake steps (the fixture fix landed in test_preflight.py beside it)."""
    from types import SimpleNamespace

    from robot_msgs.space import Basis, Value

    loaded = pf._loaded()
    rows = pf.committed_fit()["parameters"]
    values = {r["name"]: Value(float(r["recovered"]), r["unit"], basis=Basis.MEASURED, source=r["method"],
                               measured_by="sysid/results/pendulum_can11.json (the committed fit)") for r in rows}
    planned = loaded.generate_schedule()
    assert TUNE in planned.ids, planned.summary()
    recovered = {r["key"]: float(r["recovered"]) for r in rows}
    steps = [{"routine": s.routine, "identifies": list(s.identifies), "runs": 0, "seconds": 0.0,
              "found": {k: recovered[k] for k in s.identifies if s.kind != "tune"},
              **({"configures": list(s.identifies)} if s.kind == "tune" else {})} for s in planned.steps]
    calibration = sim2real.twin.Calibration("sim", loaded.model, "M4", values, {"M4": {k: float(v) for k, v in values.items()}}, rows, {},
                                            0.0, {"train_runs": 0, "held_out_runs": 0, "digest": "committed", "coverage_train_pct": 0.0,
                                                  "routines": [s["routine"] for s in steps]})
    state = {"routines": steps, "noise": {"sources": {"all": "the committed fit's"}},
             "measured": SimpleNamespace(train={}, held_out={}, repeat={})}
    loaded.runner.calibrate = lambda **_: (calibration, state)
    fitted = pf._tuned(loaded.calibrate(on="sim", callbacks=[]))
    report = sim2real.preflight(fitted)
    print(report.summary())
    record = next(c for c in report.checks if c.id == "record_matches_description")
    assert record.passed is True, record
    gains = next(c for c in report.checks if c.id == "gains_within_board_limits")
    assert gains.passed is True, gains
