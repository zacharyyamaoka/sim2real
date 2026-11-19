"""Gap A, part 2: rounds. A routine may collect, fit and come back for more (next_runs, max_rounds, optionally converged): the runner
refits on every run so far and stops on the routine's own rule, else when every 95 % interval is inside its tolerance, else at
max_rounds, and says which (Zach, Daily Note 2026-11-18).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_calibration_rounds.py

Run it on a cloud VM while the arm is powered. Nothing here needs MuJoCo, bam_ws or a device.

Zach, Daily Note 2026-11-18 ("Feedforward CAlibration"): "Do routines include things about like calibrating data? yes.. totally.. like a
routine should include datacollection and fitting steps, and then iterating things that all goes into it...".

WHY "rounds", not "iterations": in sim2real an iteration is a twin's generation (result.py stages, the W&B trend "across twin
iterations"); a round is one collect -> fit inside one routine.

The ruler, written before the code; whoever turns it green may not edit it:
1. The schedule shows round 0's runs and the bound ("up to N rounds"); an iterating routine without max_rounds is refused, and so is a
   tune (or a routine that identifies nothing) without its own converged(): the tolerance rule cannot judge performance.
2. Each round's fit sees every run so far; each run is measured once; the default stop is the first round whose intervals are all inside
   their tolerances, a rule that never reads the hidden truth (moving the truth leaves the rounds unchanged).
3. A routine's own converged() replaces the default rule; next_runs() asking for nothing stops it unconverged; max_rounds caps it; a round
   with no new run is refused by name.
4. A tune's rounds carry the last fit in their commands (the bench feedforward's shape) and stop on its own performance rule.
5. The rounds reach the record; collect() follows the fits round by round and calibrate(data=) replays them without measuring.
6. The pendulum tracer plays its schedule once, so it refuses an iterating routine before touching its world.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from sim2real import rig as seam

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # sysid (the sealed world) lives beside the package

SAMPLES = 25  # per repeat round


def _cal():
    """WHY imported per test: a missing name must FAIL the test that needs it, never skip, never fail the whole file at collection."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module



# --- the toy world -----------------------------------------------------------------------------------------------------------------------


def toy_description(priors: dict):
    from robot_msgs.space import Basis, Value  # noqa: PLC0415

    from sim2real.twin import Description, Instance  # noqa: PLC0415

    params = {key.split(".", 1)[1]: (None if v is None else Value(v, "1", basis=Basis.ASSUMED, source="the toy's datasheet"))
              for key, v in priors.items()}
    return Description("toy", "Toy rig", model=None, instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("toy", "Toy servo", "integrated_servo", "cell", params, {k: False for k in params})), source="tests")


def world_of(truth: dict):
    """The toy's world.json, read through the same seal that sysid.world uses: inside sealed() it raises."""

    def world() -> dict:
        from sysid import world as hidden  # noqa: PLC0415

        if hidden.is_sealed():
            raise hidden.SealedWorld("the toy's world is sealed while a routine fits")
        return {"truth": dict(truth), "seed": 18}

    return world


def make_twin(monkeypatch, rig, priors: dict, truth: dict):
    from sim2real import twin as twin_module  # noqa: PLC0415

    description = toy_description(priors)
    monkeypatch.setattr(twin_module, "_runner", lambda d, workers: seam.RigRunner(d, rig, workers=1, world=world_of(truth)))
    return twin_module.RobotTwin(description.instances, name="toy")


def _mean_estimate(samples: np.ndarray, method: str):
    mean = float(np.mean(samples))
    half = 1.96 * float(np.std(samples, ddof=1)) / float(np.sqrt(samples.size))
    return seam.Estimate(mean, (mean - half, mean + half), method)


@dataclass
class Declared:
    """Every toy routine declares its own needs, and declaration() reads the object first, so the catalog entry behind each id adds no
    edge of its own."""
    requires: tuple = ()
    uses: tuple = ()
    refines: tuple = ()
    configures: tuple = ()
    kind: str = "identify"




# --- iterating routines ------------------------------------------------------------------------------------------------------------------


@dataclass
class RepeatMean(Declared):
    """Collect a round of SAMPLES, fit the mean over every round so far, then ask for one more round."""
    id: str = "servo.backlash_reversal_held"
    identifies: tuple = ("toy.offset",)
    max_rounds: int = 12
    log: list = field(default_factory=list)  # (the run ids the fit saw, sorted; the mean; its 95 % half-width)

    def _round(self, k: int):
        return seam.Run(f"mean/it{k}", "train", {"round": k}, seconds=1.0)

    def runs(self, values):
        return [self._round(0)]

    def next_runs(self, values, history):
        return [self._round(len(history))]

    def fit(self, measured, values, twin):
        y = np.concatenate([measured[rid]["y"] for rid in sorted(measured)])
        estimate = _mean_estimate(y, f"mean of {y.size} samples")
        self.log.append((sorted(measured), estimate.value, (estimate.ci95[1] - estimate.ci95[0]) / 2.0))
        return {"toy.offset": estimate}


@dataclass
class EnoughAtTwo(RepeatMean):
    seen: list = field(default_factory=list)

    def converged(self, history, values):
        self.seen.append(tuple(history))
        return "two rounds are enough" if len(history) >= 2 else None


@dataclass
class GivesUpAfterTwo(RepeatMean):
    def next_runs(self, values, history):
        return [] if len(history) >= 2 else super().next_runs(values, history)


@dataclass
class AsksAgain(RepeatMean):
    def next_runs(self, values, history):
        return [self._round(0)]  # the round already played: no new data, so it would never converge


class Uncapped:
    """Iterates, but never says how many times."""
    id = "servo.backlash_reversal_held"
    identifies = ("toy.offset",)
    requires = uses = refines = configures = ()
    kind = "identify"

    def runs(self, values):
        return [seam.Run("mean/it0", "train", None)]

    def next_runs(self, values, history):
        return [seam.Run(f"mean/it{len(history)}", "train", None)]

    def fit(self, measured, values, twin):
        return {}


class RepeatRig:
    """y = offset + white noise (sigma 0.05), SAMPLES per round; the offset's tolerance is the test's."""
    name = "toy"

    def __init__(self, routine, tolerance: float) -> None:
        self.routine, self.tolerance = routine, tolerance
        self.measured_ids: list[str] = []

    def parameters(self):
        return (seam.Parameter("toy.offset", "1", ("abs", self.tolerance), "proposed: the test's", self.routine.id),)

    def noise(self):
        return seam.NoiseModel(torque_noise_nm=0.05, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return (self.routine,)

    def held_out(self, values=None):
        return [seam.Run("held0", "held_out", None)]

    def measure(self, runs, values, noise, stream, *, workers=1):
        out = {}
        for run in runs:
            self.measured_ids.append(run.id)
            out[run.id] = {"y": values["toy.offset"] + noise.rng(stream, run.id).normal(0.0, noise.effective()["torque_noise_nm"], SAMPLES)}
        return out

    def predict(self, measured, values, *, workers=1):
        return measured

    def score(self, predicted, measured):
        return seam.Score({"toy": 0.0})


def repeat_twin(monkeypatch, routine, tolerance: float = 0.010):
    rig = RepeatRig(routine, tolerance)
    return make_twin(monkeypatch, rig, {"toy.offset": 0.0}, {"toy.offset": -0.4}), rig


def only_step(fitted) -> dict:
    (step,) = fitted.calibration_.routines
    return step


# --- 1-3, 5, 6: collect, fit, come back for more -------------------------------------------------------------------------------------------------------------


def test_the_schedule_shows_an_iterating_routines_bound_and_refuses_one_without_a_cap(monkeypatch):
    cal = _cal()
    twin, _rig = repeat_twin(monkeypatch, RepeatMean(max_rounds=12))
    schedule = cal.plan(twin)
    (step,) = schedule.steps
    assert step.status == "known now" and step.max_rounds == 12
    assert [r.id for r in step.runs] == ["mean/it0"], "the schedule shows round 0's runs; each later round is made after a fit"
    assert "up to 12 rounds" in schedule.summary()
    capless, _ = repeat_twin(monkeypatch, Uncapped())
    with pytest.raises(cal.CalibrationPlanError, match="max_rounds"):
        cal.plan(capless)


def test_a_routine_collects_fits_and_iterates_until_every_interval_is_inside_its_tolerance(monkeypatch):
    routine = RepeatMean(max_rounds=12)
    twin, rig = repeat_twin(monkeypatch, routine, tolerance=0.010)
    fitted = twin.calibrate(on="sim")
    step = only_step(fitted)
    n = len(routine.log)
    assert 2 <= n < 12, f"{n} fits: {SAMPLES} samples a round need a few rounds to pin the offset to 0.010"
    assert [seen for seen, _v, _h in routine.log] == [sorted(f"mean/it{j}" for j in range(k + 1)) for k in range(n)], \
        "each fit sees every run so far"
    halves = [h for _s, _v, h in routine.log]
    assert halves[-1] <= 0.010 and all(h > 0.010 for h in halves[:-1]), f"stops at the first round inside the tolerance: {halves}"
    assert rig.measured_ids == [f"mean/it{k}" for k in range(n)], "each round's runs are measured once, and only they"
    assert [it["runs"] for it in step["rounds"]] == [[f"mean/it{k}"] for k in range(n)]
    assert step["rounds"][-1]["found"]["toy.offset"] == pytest.approx(routine.log[-1][1])
    assert step["converged"] is True and "tolerance" in step["stopped"]
    assert step["runs"] == n
    assert fitted.values_["toy.offset"].value == pytest.approx(routine.log[-1][1])


def test_iteration_stops_at_max_rounds_and_says_it_did_not_converge(monkeypatch):
    routine = RepeatMean(max_rounds=3)
    twin, rig = repeat_twin(monkeypatch, routine, tolerance=0.001)  # 0.001 at 25 samples a round needs ~380 rounds
    step = only_step(twin.calibrate(on="sim"))
    assert len(routine.log) == 3 and len(step["rounds"]) == 3
    assert rig.measured_ids == ["mean/it0", "mean/it1", "mean/it2"]
    assert step["converged"] is False and "max_rounds" in step["stopped"] and "3" in step["stopped"]


def test_a_routines_own_converged_stops_it_and_sees_the_history(monkeypatch):
    routine = EnoughAtTwo(max_rounds=6)
    twin, _rig = repeat_twin(monkeypatch, routine, tolerance=0.001)  # the default rule alone would never stop it
    step = only_step(twin.calibrate(on="sim"))
    assert len(step["rounds"]) == 2 and step["converged"] is True and "two rounds are enough" in step["stopped"]
    history = routine.seen[-1]
    assert all(isinstance(h, seam.Round) for h in history)
    assert [h.k for h in history] == [0, 1]
    assert [tuple(r.id for r in h.runs) for h in history] == [("mean/it0",), ("mean/it1",)]
    assert history[-1].found["toy.offset"].value == pytest.approx(routine.log[-1][1])


def test_a_routine_that_asks_for_nothing_more_stops_unconverged(monkeypatch):
    routine = GivesUpAfterTwo(max_rounds=6)
    twin, _rig = repeat_twin(monkeypatch, routine, tolerance=0.001)
    step = only_step(twin.calibrate(on="sim"))
    assert len(step["rounds"]) == 2 and step["converged"] is False and "next_runs" in step["stopped"]


def test_an_iteration_that_plays_no_new_run_is_refused(monkeypatch):
    cal = _cal()
    twin, _rig = repeat_twin(monkeypatch, AsksAgain(max_rounds=4), tolerance=0.001)
    with pytest.raises(cal.CalibrationPlanError) as refused:
        twin.calibrate(on="sim")
    assert "mean/it0" in str(refused.value) and "servo.backlash_reversal_held" in str(refused.value)


def test_collect_then_fit_replays_every_iteration_without_measuring_again(monkeypatch):
    cal = _cal()
    routine = RepeatMean(max_rounds=12)
    twin, rig = repeat_twin(monkeypatch, routine)
    direct = twin.calibrate(on="sim")
    rounds = len(only_step(direct)["rounds"])
    assert rounds >= 2
    data = cal.collect(twin)
    assert set(data.runs) == {f"mean/it{k}" for k in range(rounds)}, "collection follows the fits round by round"

    def measured_again(*_args, **_kwargs):
        raise AssertionError("calibrate(data=) fits the recorded rounds and never measures")

    monkeypatch.setattr(rig, "measure", measured_again)
    replayed = twin.calibrate(on="sim", data=data)
    assert len(only_step(replayed)["rounds"]) == rounds
    assert replayed.values_["toy.offset"].value == direct.values_["toy.offset"].value


def test_the_tracer_refuses_an_iterating_routine_before_touching_its_world(monkeypatch):
    from sim2real import twin as twin_module  # noqa: PLC0415

    def untouched():
        raise AssertionError("the refusal must come before the tracer touches sysid or plays its world")

    monkeypatch.setattr(twin_module, "_sysid", untouched)
    runner = twin_module.SimRunner(toy_description({"toy.offset": 0.0}), workers=1)
    with pytest.raises(NotImplementedError, match=r"servo\.backlash_reversal_held") as refused:
        runner.calibrate(routines=[RepeatMean()])
    assert "round" in str(refused.value)



# --- 4. a tune's rounds: commands made after the last fit, stopped on performance ---------------------------------------------------------


@dataclass
class TrimTune(Declared):
    """Iterates the way the bench feedforward does: every round plays the same reference with the trim the last fit found in its command;
    what the board still has to push is the error; it stops on its own rule (a tune recovers no hidden value, so no tolerance judges it)."""
    id: str = "pid.pidtuna"
    kind: str = "tune"
    identifies: tuple = ()
    adjusts: tuple = ("toy.trim",)
    max_rounds: int = 8
    target: float = 0.01

    def _run(self, k: int, trim: float):
        return seam.Run(f"trim/r{k}", "train", {"trim": float(trim)})

    def runs(self, values):
        return [self._run(0, 0.0)]

    def next_runs(self, values, history):
        return [self._run(len(history), history[-1].found["toy.trim"].value)]

    def fit(self, measured, values, twin):
        last = measured[max(measured, key=lambda rid: int(rid.split("/r")[1]))]
        trim = last["trim"] + float(np.mean(last["error"]))
        return {"toy.trim": seam.Estimate(trim, None, "feedback-error learning: the trim plus the error it left")}

    def converged(self, history, values):
        if len(history) >= 2 and abs(history[-1].found["toy.trim"].value - history[-2].found["toy.trim"].value) < self.target:
            return "the trim stopped changing: the feedback has nothing left to learn"
        return None


class NoStopTune:
    """A tune that iterates with no rule of its own."""
    id = "pid.pidtuna"
    kind = "tune"
    identifies = ()
    adjusts = ("toy.trim",)
    requires = uses = refines = configures = ()
    max_rounds = 4

    def runs(self, values):
        return [seam.Run("trim/r0", "train", {"trim": 0.0})]

    def next_runs(self, values, history):
        return [seam.Run(f"trim/r{len(history)}", "train", {"trim": 0.0})]

    def fit(self, measured, values, twin):
        return {"toy.trim": seam.Estimate(0.0, None, "nothing")}


class TrimRig(RepeatRig):
    """The board's error is the offset the trim still misses, plus noise; the rig logs every trim it was asked to play."""

    def __init__(self, routine) -> None:
        super().__init__(routine, 0.01)
        self.commanded: list[float] = []

    def parameters(self):
        # WHY both keys (the 2026-11-18 cloud dry run, a fixture error): RigRunner refuses an `adjusts` key the rig does not carry before
        # any round runs, so the trim the tune adjusts is declared here as a parameter nothing identifies
        return (seam.Parameter("toy.offset", "1", why_not="the trim absorbs it; nothing identifies it"),
                seam.Parameter("toy.trim", "1", why_not="a setting the tune adjusts; nothing identifies it"))

    def measure(self, runs, values, noise, stream, *, workers=1):
        out = {}
        for run in runs:
            trim = float(run.spec["trim"])
            self.commanded.append(trim)
            sigma = noise.effective()["torque_noise_nm"]
            out[run.id] = {"trim": trim, "error": values["toy.offset"] - trim + noise.rng(stream, run.id).normal(0.0, sigma, SAMPLES)}
        return out


def test_a_tunes_rounds_carry_the_last_fit_in_their_commands_and_stop_on_its_own_rule(monkeypatch):
    routine = TrimTune()
    rig = TrimRig(routine)
    twin = make_twin(monkeypatch, rig, {"toy.offset": 0.0, "toy.trim": 0.0}, {"toy.offset": -0.4})
    step = only_step(twin.calibrate(on="sim"))
    rounds = step["rounds"]
    assert 2 <= len(rounds) <= 4 and step["converged"] is True and "stopped changing" in step["stopped"], step
    assert rig.commanded[0] == 0.0
    for k in range(1, len(rounds)):
        assert rig.commanded[k] == pytest.approx(rounds[k - 1]["found"]["toy.trim"]), "each round's command is made after the last fit"
    assert rounds[-1]["found"]["toy.trim"] == pytest.approx(-0.4, abs=0.01)


def test_a_tune_that_iterates_with_no_rule_of_its_own_is_refused(monkeypatch):
    cal = _cal()
    twin = make_twin(monkeypatch, TrimRig(NoStopTune()), {"toy.offset": 0.0, "toy.trim": 0.0}, {"toy.offset": -0.4})
    with pytest.raises(cal.CalibrationPlanError, match="converged"):
        cal.plan(twin)


# --- the default rule never reads the hidden truth; the rounds reach the record ---------------------------------------------------------


def test_the_default_stop_never_reads_the_hidden_truth(monkeypatch):
    plain, _ = repeat_twin(monkeypatch, RepeatMean(max_rounds=12))
    a = only_step(plain.calibrate(on="sim"))
    moved, _ = repeat_twin(monkeypatch, RepeatMean(max_rounds=12))
    b = only_step(moved.calibrate(on="sim", move_truth={"toy.offset": 0.4}))
    assert len(a["rounds"]) == len(b["rounds"]) >= 2, "the world plays 0.4, the ruler keeps -0.4: a rule peeking at the truth would differ"


def test_the_rounds_reach_the_record(monkeypatch):
    routine = RepeatMean(max_rounds=12)
    twin, _rig = repeat_twin(monkeypatch, routine)
    fitted = twin.calibrate(on="sim")
    row = next(r for r in fitted.record_.to_dict()["routines"] if r["routine"] == routine.id)
    assert len(row["rounds"]) == len(routine.log) and row["converged"] is True and "tolerance" in row["stopped"], row
    assert [r["runs"] for r in row["rounds"]] == [[f"mean/it{k}"] for k in range(len(routine.log))]
