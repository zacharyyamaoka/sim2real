"""Gap D: a RobotTwin holds the runs it was fitted on, refits from them on either backend without measuring, and grows them session by
session (Zach, Daily Notes 2026-11-11, 11-17, 11-18).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_twin_holds_data.py

Run it on a cloud VM while the arm is powered, in bam_rack_twin's venv for the pendulum half (SIM2REAL_REQUIRE_RACK=1 turns its skip into
a failure) and with SIM2REAL_SLOW=1 for the CAN 11 oracle end to end.

Zach, in his own words:
    "and I think its the RobotTwin that can kidna like hold all the dataset, etc. etc." (2026-11-17)
    "What about if you are doing like incoeprating life time learning... Then you need to like consider offline datasets" (2026-11-17)
    "So on any dataset... now I should be able to just like better fit the models no?" (2026-11-18)
    "The run can come from a calibration routine or just normal operation / ITs all just runs at the end of the day though" (2026-11-11)

The ruler, written before the code; whoever turns it green may not edit it:
1. A fitted twin holds every run its fit read (fitted.data_, a CalibrationData): the very recordings, each measured once, the plan and the
   twin they came from, one key per run (a run id a routine asks for is answered by the keys `serves` maps to it). A loaded twin holds none.
2. A fitted twin refits from its own data without measuring and gets the same values, generation after generation (each refit starts from
   the description's priors); calibrate() still writes nothing.
3. Datasets grow by session (data + more): a session already held is kept once, however it comes back; the same run recorded in another
   session is kept beside the first, never overwriting it; the grown twin holds all of it, runs no routine read included.
4. Growth and refits refuse another twin's runs; a held-out run never becomes a training run (compared by run name, session suffix
   stripped); rack runs are never fitted on the sim (graded against a truth that did not make them) and one dataset never mixes the two;
   recorded runs are never refitted at a moved truth (move_truth with data= is refused).
5. The pendulum fits recorded runs too, one key per run, every session reaching its routines.
6. A twin fitted on the rack holds its runs, held-out and floor runs apart, and the file each came from; calibrate(on="real", data=) refits
   them with no transport, no emit, no play.

Not here (later legs, each with its own red tests): saving and loading a dataset, ingesting the 1-DOF campaign rounds by query.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
WORKERS = 2  # the powered rig's cap: at most 2 worker processes beside the arm

TRUTH = {"toy.gain": 2.5, "toy.offset": -0.4}
NOMINAL = {"toy.gain": 2.0, "toy.offset": 0.0}
OFFSET_RUNS = tuple(f"zero{k}" for k in range(3))
GAIN_RUNS = tuple(f"gain{k}" for k in range(4))
FOUND_GAP = 0.0123
FOUND_CI = (0.0117, 0.0129)
STUB_GAP_METHOD = "the stub gear_gap's method (the gap step's own)"


def _calibration():
    """WHY imported per test and never importorskip: a missing back end must FAIL here, not skip."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module


def _need_rack():
    if os.environ.get("SIM2REAL_REQUIRE_RACK") == "1":
        import bam_rack_twin  # noqa: F401, PLC0415
    else:
        pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv")


def _forbid(*_args, **_kwargs):
    raise AssertionError("fitting recorded data measured again")


def _same_recordings(a, b) -> None:
    """Two datasets hold the same recordings under the same keys, answering the same run ids, from the same sessions."""
    assert set(a.runs) == set(b.runs) and set(a.held_out) == set(b.held_out), (sorted(a.runs), sorted(b.runs))
    for key in a.runs:
        assert np.array_equal(a.runs[key]["y"], b.runs[key]["y"]), key
    assert dict(a.serves) == dict(b.serves) and tuple(a.sessions) == tuple(b.sessions)


# --- the toy rig: two routines, the second reading what the first found -----------------------------------------------------------------


def _inputs(run_id: str) -> np.ndarray:
    return np.random.default_rng(zlib.crc32(run_id.encode())).uniform(-1.0, 1.0, 300)


def _world() -> dict:
    from sysid import world as hidden  # noqa: PLC0415

    if hidden.is_sealed():
        raise hidden.SealedWorld("sealed")
    return {"truth": dict(TRUTH), "seed": 3}


@dataclass
class OffsetFit:
    """Registered id (the seam refuses others). `seen`: the recording keys each fit was handed."""
    id: str = "servo.backlash_reversal_held"
    identifies: tuple[str, ...] = ("toy.offset",)
    requires: tuple[str, ...] = ()
    seen: list = field(default_factory=list)

    def runs(self, values):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(run_id, "train", None) for run_id in OFFSET_RUNS]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        self.seen.append(sorted(measured))
        y = np.concatenate([m["y"] - values["toy.gain"] * m["u"] for m in measured.values()])
        mean = float(np.mean(y))
        return {"toy.offset": seam.Estimate(mean, (mean - 0.01, mean + 0.01), "mean residual")}


@dataclass
class GainFit:
    id: str = "servo.breakaway_two_sided"
    identifies: tuple[str, ...] = ("toy.gain",)
    requires: tuple[str, ...] = ("toy.offset",)
    seen: list = field(default_factory=list)

    def runs(self, values):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(run_id, "train", None) for run_id in GAIN_RUNS]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        self.seen.append(sorted(measured))
        u = np.concatenate([m["u"] for m in measured.values()])
        y = np.concatenate([m["y"] for m in measured.values()]) - values["toy.offset"]
        gain = float(u @ y / (u @ u))
        return {"toy.gain": seam.Estimate(gain, (gain - 0.01, gain + 0.01), "least squares through the found offset")}


class ToyRig:
    name = "toy"

    def __init__(self):
        self.offset, self.gain = OffsetFit(), GainFit()

    def parameters(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return (seam.Parameter("toy.gain", "1", ("rel", 0.05), "proposed", self.gain.id),
                seam.Parameter("toy.offset", "1", ("abs", 0.05), "proposed", self.offset.id))

    def noise(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return seam.NoiseModel(torque_noise_nm=0.02, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return (self.offset, self.gain)

    def held_out(self, values=None):
        from sim2real import rig as seam  # noqa: PLC0415

        return [seam.Run(f"held{k}", "held_out", None) for k in range(2)]

    def measure(self, runs, values, noise, stream, *, workers=1):
        sigma = noise.effective()["torque_noise_nm"]
        out = {}
        for run in runs:
            u = _inputs(run.id)
            out[run.id] = {"u": u, "y": values["toy.gain"] * u + values["toy.offset"] + noise.rng(stream, run.id).normal(0.0, sigma, u.size)}
        return out

    def predict(self, measured, values, *, workers=1):
        return {rid: {"u": m["u"], "y": values["toy.gain"] * m["u"] + values["toy.offset"]} for rid, m in measured.items()}

    def score(self, predicted, measured):
        from sim2real import rig as seam  # noqa: PLC0415

        per_run = {rid: {"toy": float(np.sqrt(np.mean((predicted[rid]["y"] - m["y"]) ** 2)))} for rid, m in measured.items()}
        return seam.Score({"toy": float(np.mean([v["toy"] for v in per_run.values()]))}, per_run)


def _toy_description():
    from robot_msgs.space import Basis, Value  # noqa: PLC0415

    from sim2real.twin import Description, Instance  # noqa: PLC0415

    params = {k.split(".", 1)[1]: Value(v, "1", basis=Basis.ASSUMED, source="the toy's datasheet") for k, v in NOMINAL.items()}
    return Description("toy", "Toy rig", model=None, instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("toy", "Toy servo", "integrated_servo", "cell", params, {k: False for k in params})), source="tests")


@pytest.fixture
def toy_twin(monkeypatch):
    from sim2real import rig as seam  # noqa: PLC0415
    from sim2real import twin as twin_module  # noqa: PLC0415

    rig = ToyRig()
    monkeypatch.setattr(twin_module, "_runner", lambda description, workers: seam.RigRunner(description, rig, workers=1, world=_world))
    return twin_module.RobotTwin(_toy_description().instances, name="toy"), rig


def _values(twin) -> dict[str, float]:
    return {k: float(v) for k, v in twin.values_.items() if v is not None}



class _Stop(Exception):
    pass


@dataclass
class _Measured:
    train: dict
    held_out: dict = field(default_factory=dict)
    repeat: dict = field(default_factory=dict)


def _stub_pipeline(seen: dict):
    """The pendulum's pipeline as the runner calls it, down to identify(), which stops the run (as tests/test_workers_cap.py does)."""

    class World:
        truth, noise, seed = {}, {}, 0

        def __init__(self, d, *, workers):
            pass

        def measure(self, plan):
            raise AssertionError("calibrate(data=...) played the pendulum's world")

    class Module:
        RealWorld = World
        Measured = _Measured
        GAP_METHOD = "the stub's gap"

        @staticmethod
        def plan(d):
            return SimpleNamespace(train=[], held_out=[], digest="stub", coverage={"train": {"pct": 0.0}}, document={"trajectories": []})

        @staticmethod
        def gear_gap(measurements):
            seen["gear_gap"] = dict(measurements)
            return SimpleNamespace(rad=0.01, ci95=(0.009, 0.011))

        @staticmethod
        def identify(description, measurements, **options):
            seen["identify"] = dict(measurements)
            seen["options"] = dict(options)
            raise _Stop

    return Module


@pytest.fixture
def pendulum():
    _need_rack()
    import sim2real  # noqa: PLC0415

    return sim2real.examples.pendulum_can11(workers=WORKERS)


def _stubbed(pendulum, monkeypatch) -> dict:
    seen: dict = {}
    monkeypatch.setattr(pendulum.runner, "pipeline", lambda: _stub_pipeline(seen))
    monkeypatch.setattr(pendulum.runner, "sysid_description", lambda: object())
    return seen



# --- the rack's surface the real backend reaches, stubbed (tests/test_real_plays_schedule.py's bench, so no rack, file or MuJoCo) -------

from sim2real import real  # noqa: E402
from sim2real import twin as twin_module  # noqa: E402

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



# --- 1-2: a fitted twin holds the data it was fitted on, and refits from it ------------------------------------------------------------------


def test_a_fitted_twin_holds_the_very_runs_its_fit_read_each_measured_once(toy_twin, monkeypatch):
    cal = _calibration()
    twin, rig = toy_twin
    assert not hasattr(twin, "data_"), "a loaded twin holds no fitted data (learned attributes exist only after a fit)"
    measured, returned = [], {}
    original = rig.measure

    def counted(runs, *args, **kwargs):
        out = original(runs, *args, **kwargs)
        measured.extend(run.id for run in runs)
        returned.update(out)
        return out

    monkeypatch.setattr(rig, "measure", counted)
    fitted = twin.calibrate(on="sim")
    data = fitted.data_
    assert isinstance(data, cal.CalibrationData), type(data)
    assert sorted(measured) == sorted(OFFSET_RUNS + GAIN_RUNS), "each run measured once: holding it never measures it again"
    assert set(data.runs) == set(OFFSET_RUNS) | set(GAIN_RUNS), sorted(data.runs)
    for run_id in OFFSET_RUNS + GAIN_RUNS:
        assert data.answering(run_id) == (run_id,), (run_id, data.answering(run_id))
        assert data.runs[run_id] is returned[run_id], "the recording the fit read, not a copy or a re-measure"
    assert data.plan.ids == fitted.plan_.ids
    assert data.meta["twin"] == "toy" and data.meta["backend"] == "sim" and data.meta["session"], data.meta
    assert tuple(data.sessions) == (data.meta["session"],)
    assert not hasattr(twin, "data_"), "the loaded twin is unchanged"


def test_a_twin_fitted_on_data_holds_that_data(toy_twin):
    """And, where no routine's runs read an earlier routine's result (true of this toy), a sim calibrate holds what collect() records."""
    cal = _calibration()
    twin, _rig = toy_twin
    collected = cal.collect(twin)
    _same_recordings(twin.calibrate(data=collected).data_, collected)
    _same_recordings(twin.calibrate(on="sim").data_, collected)


def test_a_fitted_twin_refits_from_its_own_data_without_measuring(toy_twin, monkeypatch, tmp_path):
    twin, rig = toy_twin
    monkeypatch.chdir(tmp_path)
    fitted = twin.calibrate(on="sim")
    monkeypatch.setattr(rig, "measure", _forbid)
    refit = fitted.calibrate(data=fitted.data_)
    assert refit is not fitted and refit.fitted
    assert _values(refit) == _values(fitted), "the same runs fit to the same values"
    again = refit.calibrate(data=refit.data_)
    assert _values(again) == _values(fitted), "every generation refits from the same priors: the same runs give the same values"
    assert list(tmp_path.iterdir()) == [], "calibrate() writes nothing: the twin holds its data in memory"


# --- 3-4: datasets grow session by session ---------------------------------------------------------------------------------------------


def test_datasets_grow_by_session_and_keep_every_recording_once(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    first = cal.collect(twin)
    second = cal.collect(twin, cal.CalibrationConfig(seed=7))  # the same schedule another day: the same run ids, other noise draws
    assert first.meta["session"] != second.meta["session"], "another session, another id"
    keys_before = set(first.runs)
    grown = first + second
    assert grown is not first and set(first.runs) == keys_before, "growing returns a new dataset"
    _same_recordings(grown, first.extend(second))
    assert tuple(grown.sessions) == (first.meta["session"], second.meta["session"])
    for run_id in OFFSET_RUNS + GAIN_RUNS:
        keys = grown.answering(run_id)
        assert len(keys) == 2 and keys[0] == run_id and keys[1] != run_id, (run_id, keys)
        assert np.array_equal(grown.runs[keys[0]]["y"], first.runs[run_id]["y"]), "the first session's recording is kept as it was"
        assert np.array_equal(grown.runs[keys[1]]["y"], second.runs[run_id]["y"]), "the second session's recording is kept beside it"
    assert len(grown.runs) == len(first.runs) + len(second.runs)
    _same_recordings(first + first, first)                # a session already held is kept once
    _same_recordings((first + second) + second, grown)    # however it comes back
    _same_recordings(first + (first + second), grown)


def test_a_refit_on_grown_data_reads_every_recording_and_the_twin_holds_all_of_it(toy_twin, monkeypatch):
    cal = _calibration()
    twin, rig = toy_twin
    fitted = twin.calibrate(on="sim")
    more = cal.collect(twin, cal.CalibrationConfig(seed=7))
    u = np.random.default_rng(zlib.crc32(b"spare0")).uniform(-1.0, 1.0, 300)
    spare = dataclasses.replace(more, runs={"spare0": {"u": u, "y": TRUTH["toy.gain"] * u + TRUTH["toy.offset"]}}, serves={},
                                meta={**more.meta, "session": "spare-session"})  # a run no routine asks for
    grown = fitted.data_ + more + spare
    rig.offset.seen.clear()
    rig.gain.seen.clear()
    monkeypatch.setattr(rig, "measure", _forbid)
    refit = fitted.calibrate(data=grown)
    offset_keys, gain_keys = rig.offset.seen[-1], rig.gain.seen[-1]
    assert len(gain_keys) == 2 * len(GAIN_RUNS) == len(set(gain_keys)) and set(GAIN_RUNS) <= set(gain_keys), gain_keys
    assert len(offset_keys) == 2 * len(OFFSET_RUNS) == len(set(offset_keys)) and set(OFFSET_RUNS) <= set(offset_keys), offset_keys
    assert "spare0" not in gain_keys + offset_keys, "a run no routine asks for is held, never fitted"
    _same_recordings(refit.data_, grown)
    assert refit.data_.answering("spare0") == ("spare0",), "all of it, read or not"
    assert refit.values_["toy.gain"].value == pytest.approx(TRUTH["toy.gain"], rel=0.05)
    assert refit.values_["toy.offset"].value == pytest.approx(TRUTH["toy.offset"], abs=0.05)


def test_growth_and_refits_refuse_another_twins_runs(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    mine = cal.collect(twin)
    theirs = dataclasses.replace(mine, meta={**mine.meta, "twin": "another_rig", "session": "theirs"})
    with pytest.raises(ValueError) as caught:
        mine + theirs
    assert "another_rig" in str(caught.value) and "toy" in str(caught.value), str(caught.value)
    with pytest.raises(ValueError, match="another_rig"):
        twin.calibrate(data=theirs)


def test_a_held_out_run_never_becomes_a_training_run(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    base = cal.collect(twin)
    u = np.random.default_rng(zlib.crc32(b"held0")).uniform(-1.0, 1.0, 300)
    judged = dataclasses.replace(base, held_out={"held0": {"u": u, "y": 2.5 * u - 0.4}}, meta={**base.meta, "session": "judged"})
    trained = dataclasses.replace(base, runs={**base.runs, "held0@tuesday": {"u": u, "y": 2.5 * u - 0.39}},
                                  serves={**base.serves, "held0@tuesday": "held0"}, meta={**base.meta, "session": "trained"})
    with pytest.raises(ValueError, match="held0"):
        judged + trained
    with pytest.raises(ValueError, match="held0"):
        trained + judged
    with pytest.raises(ValueError, match="held0"):
        dataclasses.replace(base, runs={**base.runs, "held0": {"u": u, "y": u}}, held_out={"held0": {"u": u, "y": u}})


def test_rack_runs_are_never_fitted_on_the_sim_and_never_mixed_with_sim_draws(toy_twin, monkeypatch):
    cal = _calibration()
    twin, rig = toy_twin
    simulated = cal.collect(twin)
    recorded = dataclasses.replace(cal.collect(twin, cal.CalibrationConfig(seed=7)),
                                   meta={**simulated.meta, "backend": "real", "session": "rack-monday"})
    monkeypatch.setattr(rig, "measure", _forbid)
    with pytest.raises(ValueError, match="on='real'"):
        twin.calibrate(on="sim", data=recorded)
    with pytest.raises(ValueError) as caught:
        simulated + recorded
    assert "backend 'sim'" in str(caught.value) and "'real'" in str(caught.value), str(caught.value)


def test_recorded_runs_are_never_refitted_at_a_moved_truth(toy_twin):
    cal = _calibration()
    twin, _rig = toy_twin
    data = cal.collect(twin)
    with pytest.raises(ValueError, match="move_truth"):
        twin.calibrate(on="sim", data=data, move_truth={"toy.gain": 2.6})


# --- 5: the pendulum fits recorded runs (its pipeline stubbed: no replay, no MuJoCo) ------------------------------------------------------------


def test_the_pendulum_fits_recorded_runs_one_key_per_run_without_playing_its_world(pendulum, monkeypatch):
    cal = _calibration()
    seen = _stubbed(pendulum, monkeypatch)
    with pytest.raises(TypeError, match="CalibrationData"):
        pendulum.calibrate(data={"train": {}})
    recorded = {"run_a": "RECORDING-A", "run_b": "RECORDING-B"}
    data = cal.CalibrationData(runs=dict(recorded), serves={"run_a": "train", "run_b": "train"}, plan=cal.plan(pendulum),
                               meta={"twin": "pendulum_can11", "backend": "sim", "session": "monday"})
    assert data.answering("train") == ("run_a", "run_b")
    with pytest.raises(_Stop):
        pendulum.calibrate(data=data)
    assert seen["gear_gap"] == recorded, "step 1 (the gap from the reversals) fits the recorded train runs"
    assert seen["identify"] == recorded, "step 2 (the regression) fits the same recorded runs"
    assert seen["options"].get("gap") == 0.01, "at the gap step 1 found"
    assert seen["options"].get("workers") == WORKERS, "the twin's worker cap still reaches every pool"


def test_every_session_of_a_grown_dataset_reaches_the_pendulums_routines(pendulum, monkeypatch):
    cal = _calibration()
    seen = _stubbed(pendulum, monkeypatch)
    planned = cal.plan(pendulum)
    monday = cal.CalibrationData(runs={"run_a": "MONDAY-A"}, serves={"run_a": "train"}, plan=planned,
                                 meta={"twin": "pendulum_can11", "backend": "sim", "session": "monday"})
    tuesday = cal.CalibrationData(runs={"run_a": "TUESDAY-A"}, serves={"run_a": "train"}, plan=planned,
                                  meta={"twin": "pendulum_can11", "backend": "sim", "session": "tuesday"})
    with pytest.raises(_Stop):
        pendulum.calibrate(data=monday + tuesday)
    assert sorted(seen["gear_gap"].values()) == ["MONDAY-A", "TUESDAY-A"], ("the same schedule run on two days: both are fitted, neither "
                                                                           f"overwrites the other by its name; got {seen['gear_gap']}")
    assert sorted(seen["identify"].values()) == ["MONDAY-A", "TUESDAY-A"], seen["identify"]


# --- 6: the rack: held, and refitted with no transport (its pipeline, emit and ingest stubbed) -------------------------------------------


def test_a_twin_fitted_on_the_rack_holds_its_runs_apart_and_refits_them_with_no_transport(pendulum, monkeypatch):
    from sim2real.calibration import plan as schedule_of  # noqa: PLC0415

    bench = _bench(monkeypatch, pendulum, schedule_of(pendulum))
    fitted = pendulum.calibrate(on="real", transport=bench.transport)
    data = fitted.data_
    assert data.meta["twin"] == "pendulum_can11" and data.meta["backend"] == "real", data.meta
    assert set(data.answering("train")) == set(bench.train) and all(data.runs[k] is bench.train[k] for k in bench.train)
    assert set(data.held_out) == set(bench.held_out) | set(bench.floor), "held-out and floor runs are held apart from the training runs"
    assert {k: data.serves[k] for k in data.held_out} == {"h1": "held_out", "f1": "floor"}
    assert data.meta["files"] == {n: f"/nonexistent/{n}.npz" for n in ("t1", "t2", "h1", "f1")}, "each run names the file it came from"

    def moved(*_args, **_kwargs):
        raise AssertionError("refitting recorded rack runs reached the rack")

    for name in ("emit", "ingest"):
        monkeypatch.setattr(real, name, moved)
    monkeypatch.setattr(bench.transport, "play", moved)
    refit = fitted.calibrate(on="real", data=data)
    assert {k: float(v) for k, v in refit.values_.items() if v is not None} == pytest.approx(
        {k: float(v) for k, v in fitted.values_.items() if v is not None}), "the same rack runs fit to the same values"
    assert refit.record_.to_dict()["backend"] == "real"
    with pytest.raises(ValueError, match="on='real'"):
        pendulum.calibrate(on="sim", data=data)


# --- slow (SIM2REAL_SLOW=1, cloud VM): the CAN 11 oracle end to end -----------------------------------------------------------------------


@pytest.mark.skipif(not SLOW, reason="SIM2REAL_SLOW=1: the CAN 11 oracle's calibration takes minutes")
def test_the_pendulum_twin_holds_its_runs_and_refits_from_them(pendulum, monkeypatch):
    fitted = pendulum.calibrate(on="sim", truth="sealed")
    data = fitted.data_
    assert data.meta["twin"] == "pendulum_can11" and data.meta["backend"] == "sim", data.meta
    train = data.answering("train")
    assert 0 < len(train) == fitted.calibration_.plan["train_runs"], (len(train), fitted.calibration_.plan)
    assert data.held_out, "the held-out runs are held too, so a refit twin can still be judged"
    assert set(train).isdisjoint(data.held_out), "no run is both trained on and held out"
    module = fitted.runner.pipeline()
    monkeypatch.setattr(module.RealWorld, "measure", _forbid)
    refit = fitted.calibrate(data=data)
    for name, value in _values(fitted).items():
        assert float(refit.values_[name]) == pytest.approx(value, rel=1e-9), name
    assert refit.runner.description is fitted.runner.description, "a refit keeps the priors the pipeline reads, so it can refit again"
    report = refit.evaluate()
    print(report.summary(), flush=True)
    assert report.passed, report.summary()


@pytest.mark.skipif(not SLOW, reason="the whole CAN 11 schedule on the rack twin takes tens of minutes: SIM2REAL_SLOW=1")
def test_a_twin_fitted_over_the_rack_transport_holds_its_runs_and_their_files(pendulum, tmp_path):
    pytest.importorskip("mujoco", reason="the twin transport replays the rack twin")
    fitted = pendulum.calibrate(on="real", transport=real.TwinTransport(root=tmp_path, workers=WORKERS))
    data = fitted.data_
    assert data.meta["twin"] == "pendulum_can11" and data.meta["backend"] == "real", data.meta
    assert set(data.answering("train")) == set(fitted.runs_.train), "the runs the fit read, as the ingest kept them"
    assert all(Path(data.meta["files"][name]).is_file() for name in data.answering("train")), "each run names the file it was read from"
    assert data.held_out and set(data.answering("train")).isdisjoint(data.held_out)
