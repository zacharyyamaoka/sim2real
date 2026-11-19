"""Gap A, part 1: the CalibrationSchedule, a static object you can look at. Each step carries its runs bound at the priors, each run a
typed command (a robot_msgs JointTrajectory or JointCommandSequence) or none, and the schedule says which commands wait for an earlier
step's fit. What calibrate() then plays is held to it (Zach, Daily Note 2026-11-17).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_calibration_schedule.py

Run it on a cloud VM (bam_ws tools/cloud, job sim2real-calibrate-tests) while the arm is powered. The pendulum test needs bam_rack_twin's
venv; SIM2REAL_REQUIRE_RACK=1 (the cloud job sets it) turns its skip into a failure.

Zach, Daily Note 2026-11-17 ("One click sim to real how does that tie in?"):

    And then the first output I think should be like A CalibrationSchedule
    Its almost like a JointTrajecotry though I think in that its a static description of the routines that will be run... so its nice
    to be able to kinda like see it as a static object.
    could a routine just be described as as long joint traecjtory? or how about like ServoCommandSequence..
    internall mabye that does .generate_schedule() -> CalibrationSchedule

and: "routines can almost like declare depencies on what they require to run ahead of time so you can ... atuomaticaly generate the
schedule". Collect -> fit -> iterate (rounds) is part 2 (tests/test_calibration_rounds.py).

The ruler, written before the code; whoever turns it green may not edit it:
1. CalibrationSchedule is the plan under Zach's name; plan(), CalibrationPlan stay as aliases; twin.generate_schedule() makes it.
2. A run's command is a robot_msgs JointTrajectory or JointCommandSequence, or none. Anything else is refused. Its robot time comes from
   the command, else from Run.seconds; one run has one length. It round-trips as JSON, its spec included (refused if not JSON).
3. Which commands are made after an earlier step comes from what the routine DECLARES (commands_read; default: the keys it requires that
   an earlier step writes), never from the order, and plan() runs no probe. A made-after step is previewed at the priors when it can be.
4. calibrate() is held to the schedule: a known-now step plays exactly the commands shown, or calibrate() refuses by name; a run id means
   one command; runs() gives the same runs for the same values.
5. collect() records made-after steps the way a replay builds them, so calibrate(data=) replays without measuring and without mismatch.
6. The pendulum: every step with runs is known now on the one train run, its length the committed schedule's train seconds.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from robot_msgs import allclose
from robot_msgs.control import Elapsed, JointCommand, JointCommandSequence, JointCommandStep, Stall
from robot_msgs.trajectory import JointTrajectory

from sim2real import rig as seam

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # sysid (the sealed world) lives beside the package

WORKERS = 2  # the powered rig's cap: at most 2 worker processes beside the arm
CAN11_RESULT = REPO / "sysid" / "results" / "pendulum_can11.json"
STEP_KEYS = {"routine", "title", "kind", "setting", "identifies", "requires", "uses", "refines", "after", "why_here", "wall_time_s",
             "operator_time_s", "equipment_usd", "recovery", "source"}
NOMINAL = {"toy.zero": 0.0, "toy.gain": 2.0, "toy.offset": 0.0, "toy.tilt": 0.0}
TRUTH = {"toy.zero": 0.03, "toy.gain": 2.5, "toy.offset": -0.4, "toy.tilt": 0.5}
T = np.linspace(0.0, 3.0, 61)
PATTERN = np.sin(2.0 * np.pi * T / 3.0)


def _cal():
    """WHY imported per test: a missing name must FAIL the test that needs it, never skip, never fail the whole file at collection."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module


def _need_rack():
    if os.environ.get("SIM2REAL_REQUIRE_RACK") == "1":
        import bam_rack_twin  # noqa: F401, PLC0415
    else:
        pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv")


# --- commands ----------------------------------------------------------------------------------------------------------------------------


def tape(origin: float = 0.0) -> JointTrajectory:
    """A 3 s open-loop tape on joint "toy", around `origin` (its frame)."""
    return JointTrajectory(t=T, joint_names=("toy",), positions=(PATTERN + origin)[:, None])


def seek() -> JointCommandSequence:
    """Two steps. A 2 s settle that ends by time, then a seek that ends on a stall or at its 4 s timeout: 2 to 6 robot-seconds in all."""
    return JointCommandSequence(joint_names=("toy",), name="toy zero seek", steps=(
        JointCommandStep(name="settle", commands=(JointCommand.hold("toy", max_effort=1.0),), done_when=(Elapsed(duration=2.0),),
                         timeout=5.0),
        JointCommandStep(name="seek", commands=(JointCommand.move_by("toy", -0.5, speed=0.2, max_effort=0.5),),
                         done_when=(Stall(joint="toy"), Elapsed(duration=10.0)), timeout=4.0, define_position={"toy": 0.0}),
    ))


def log_run():
    """A recorded log: no command of its own (nothing to play), its length known (already on disk: no robot time)."""
    return seam.Run("log", "train", {"source": "toy log", "split": "train", "session": "2026-11-18"}, seconds=0.0)


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
    commands_read: tuple | None = None  # None: not declared, so the planner assumes the keys it requires


@dataclass
class ZeroFind(Declared):
    """The joint's zero from where a closed-loop seek stops (a JointCommandSequence): its commands read no value."""
    id: str = "homing.single_touch"
    identifies: tuple = ("toy.zero",)

    def runs(self, values):
        return [seam.Run("zero/seq", "train", None, command=seek())]

    def fit(self, measured, values, twin):
        return {"toy.zero": _mean_estimate(np.concatenate([m["q"] for m in measured.values()]), "where the seek stopped")}


@dataclass
class GainTape(Declared):
    """The gain from an open-loop tape commanded in the homed frame: its commands are made from the zero ZeroFind finds."""
    id: str = "servo.dynamics_regression"
    identifies: tuple = ("toy.gain",)
    requires: tuple = ("toy.zero",)
    frame_from_zero: bool = True
    calls: int = 0

    def runs(self, values):
        self.calls += 1
        copied = dict(values)  # WHY a copy: the planner must find the dependence from the commands, however a routine reads its values
        return [seam.Run("gain/tape", "train", None, command=tape(copied["toy.zero"] if self.frame_from_zero else 0.0))]

    def fit(self, measured, values, twin):
        m = measured["gain/tape"]
        design = np.column_stack([m["q_cmd"] - values["toy.zero"], np.ones_like(m["q_cmd"])])
        coef, *_ = np.linalg.lstsq(design, m["y"], rcond=None)
        gain = float(coef[0])
        return {"toy.gain": seam.Estimate(gain, (gain - 0.01, gain + 0.01), "least squares in the homed frame")}


@dataclass
class OffsetFromLog(Declared):
    """The offset from a recorded log (a run with no command). Its fit reads the gain (uses), but its commands read nothing."""
    id: str = "servo.backlash_reversal_held"
    identifies: tuple = ("toy.offset",)
    uses: tuple = ("toy.gain",)

    def runs(self, values):
        return [log_run()]

    def fit(self, measured, values, twin):
        m = measured["log"]
        return {"toy.offset": _mean_estimate(m["y"] - values["toy.gain"] * m["u"], "mean residual through the found gain")}


@dataclass
class TiltFromGain(Declared):
    """Fit only: no motion of its own."""
    id: str = "arm.gravity_direction"
    identifies: tuple = ("toy.tilt",)
    requires: tuple = ("toy.gain", "toy.offset")

    def runs(self, values):
        return []

    def fit(self, measured, values, twin):
        tilt = float(values["toy.gain"]) - 2.0
        return {"toy.tilt": seam.Estimate(tilt, (tilt - 0.05, tilt + 0.05), "from the found gain")}


@dataclass
class Shares(Declared):
    id: str = "homing.single_touch"
    identifies: tuple = ("toy.zero",)
    shift: float = 0.0

    def runs(self, values):
        return [seam.Run("shared", "train", None, command=tape(self.shift))]

    def fit(self, measured, values, twin):
        return {}


class Restless:
    """Draws a new run id on every call: not a static schedule."""
    id = "servo.backlash_reversal_held"
    identifies = ("toy.offset",)
    requires = uses = refines = configures = ()
    kind = "identify"

    def __init__(self) -> None:
        self._draws = itertools.count()

    def runs(self, values):
        return [seam.Run(f"draw{next(self._draws)}", "train", None)]

    def fit(self, measured, values, twin):
        return {}


class ChainRig:
    """zero (homing) -> gain (a tape in the homed frame) -> offset (a log) -> tilt (fit only). Records every run measure() is handed."""
    name = "toy"

    def __init__(self, routines=None) -> None:
        self._routines = tuple(routines) if routines is not None else (ZeroFind(), GainTape(), OffsetFromLog(), TiltFromGain())
        self.played: list[tuple[str, object]] = []

    def parameters(self):
        return (seam.Parameter("toy.zero", "1", ("abs", 0.01), "proposed: the test's", "homing.single_touch"),
                seam.Parameter("toy.gain", "1", ("rel", 0.05), "proposed: the test's", "servo.dynamics_regression"),
                seam.Parameter("toy.offset", "1", ("abs", 0.05), "proposed: the test's", "servo.backlash_reversal_held"),
                seam.Parameter("toy.tilt", "1", ("abs", 0.1), "proposed: the test's", "arm.gravity_direction"))

    def noise(self):
        return seam.NoiseModel(torque_noise_nm=0.02, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return self._routines

    def held_out(self, values=None):
        return [seam.Run("held0", "held_out", None)]

    def measure(self, runs, values, noise, stream, *, workers=1):
        sigma = noise.effective()["torque_noise_nm"]
        out = {}
        for run in runs:
            self.played.append((stream, run))
            rng = noise.rng(stream, run.id)
            if isinstance(run.command, JointCommandSequence):
                out[run.id] = {"q": values["toy.zero"] + rng.normal(0.0, sigma, 40)}
            elif isinstance(run.command, JointTrajectory):
                q_cmd = np.asarray(run.command.positions, dtype=float)[:, 0]
                y = values["toy.gain"] * (q_cmd - values["toy.zero"]) + values["toy.offset"] + rng.normal(0.0, sigma, q_cmd.size)
                out[run.id] = {"q_cmd": q_cmd, "y": y}
            else:  # a recorded log: the world hands back the session it holds
                u = np.random.default_rng(zlib.crc32(run.id.encode())).uniform(-1.0, 1.0, 200)
                out[run.id] = {"u": u, "y": values["toy.gain"] * u + values["toy.offset"] + rng.normal(0.0, sigma, u.size)}
        return out

    def predict(self, measured, values, *, workers=1):
        return measured

    def score(self, predicted, measured):
        return seam.Score({"toy": 0.0})


@pytest.fixture
def chain(monkeypatch):
    rig = ChainRig()
    return make_twin(monkeypatch, rig, NOMINAL, TRUTH), rig




# --- 1. the name -------------------------------------------------------------------------------------------------------------------------


def test_calibration_schedule_is_the_plan_under_zachs_name():
    cal = _cal()
    assert cal.CalibrationSchedule is cal.CalibrationPlan, "one class: CalibrationPlan stays as an alias"
    assert cal.CalibrationSchedule.__name__ == "CalibrationSchedule", "Zach's name is the class's own"
    assert cal.generate_schedule is cal.plan
    assert {"CalibrationSchedule", "generate_schedule", "CalibrationPlan", "plan"} <= set(cal.__all__), "the docs site lists every one"
    picked = {"cam": ("camera", "M1.measurement.distortion")}
    schedule = cal.generate_schedule(picked)
    assert isinstance(schedule, cal.CalibrationSchedule) and schedule.ids == cal.plan(picked).ids
    assert "schedule" not in schedule.to_dict(), "catalog stand-ins bind no runs: such a plan's dict is unchanged"


def test_a_twin_generates_its_schedule_and_calibrate_carries_it(chain):
    cal = _cal()
    twin, _rig = chain
    schedule = twin.generate_schedule()
    assert isinstance(schedule, cal.CalibrationSchedule) and schedule.ids == cal.plan(twin).ids
    steered = twin.generate_schedule(cal.CalibrationConfig(exclude=("arm.gravity_direction",)))
    assert "arm.gravity_direction" not in steered.ids
    assert any(rid == "arm.gravity_direction" and "exclude" in why for rid, why in steered.dropped)
    fitted = twin.calibrate(on="sim")
    assert isinstance(fitted.plan_, cal.CalibrationSchedule) and fitted.plan_.ids == schedule.ids



# --- 2. typed commands -------------------------------------------------------------------------------------------------------------------


def test_a_run_carries_a_typed_command_and_refuses_anything_else():
    plain = seam.Run("a", "train", {"kind": "tape"})  # positional, as every rig builds its runs today
    assert plain.command is None and plain.seconds is None and plain.spec == {"kind": "tape"}
    for command in (tape(), seek()):
        assert seam.Run("b", "train", None, command=command).command is command
    for wrong in ({"kind": "tape"}, "every FB run of the train split", [tape()]):
        with pytest.raises(TypeError, match="JointTrajectory"):
            seam.Run("c", "train", None, command=wrong)


def test_a_runs_robot_time_comes_from_its_command_else_its_seconds_and_one_run_has_one_length():
    assert seam.Run("t", "train", None, command=tape()).robot_seconds() == pytest.approx((3.0, 3.0))
    assert seam.Run("s", "train", None, command=seek()).robot_seconds() == pytest.approx((2.0, 6.0)), \
        "a sequence's bounds: each step ends by its Elapsed or its timeout, or as soon as another condition holds"
    assert log_run().robot_seconds() == (0.0, 0.0), "already recorded"
    assert seam.Run("k", "train", "a schedule split", seconds=771.8).robot_seconds() == (771.8, 771.8)
    assert seam.Run("n", "train", None).robot_seconds() is None, "unknown stays unknown"
    assert seam.Run("t", "train", None, seconds=3.0, command=tape()).robot_seconds() == pytest.approx((3.0, 3.0))
    with pytest.raises(ValueError, match="seconds"):
        seam.Run("t", "train", None, seconds=5.0, command=tape())  # one run, one length: a tape's length is its own
    with pytest.raises(ValueError, match="seconds"):
        seam.Run("u", "train", None, seconds=-1.0)


def test_a_run_round_trips_as_json_with_its_command_and_its_spec():
    for command in (tape(0.2), seek()):
        back = seam.Run.from_dict(json.loads(json.dumps(seam.Run("r", "held_out", {"why": "the toy's"}, command=command).to_dict())))
        assert (back.id, back.split, back.spec) == ("r", "held_out", {"why": "the toy's"})
        assert type(back.command) is type(command) and allclose(back.command, command)
    assert seam.Run.from_dict(json.loads(json.dumps(log_run().to_dict()))) == log_run()
    with pytest.raises(TypeError, match="r2"):
        seam.Run("r2", "train", object()).to_dict()  # a spec that is not JSON is refused by name, never silently dropped


# --- 3. the schedule binds the runs and says which wait for an earlier fit ---------------------------------------------------------------


def test_the_schedule_binds_each_steps_runs_at_the_priors(chain):
    cal = _cal()
    twin, _rig = chain
    schedule = cal.plan(twin)
    assert schedule.ids == ("homing.single_touch", "servo.dynamics_regression", "servo.backlash_reversal_held", "arm.gravity_direction")
    zero, gain, offset, tilt = schedule.steps
    assert [r.id for r in zero.runs] == ["zero/seq"] and isinstance(zero.runs[0].command, JointCommandSequence)
    assert [r.id for r in gain.runs] == ["gain/tape"]
    assert allclose(gain.runs[0].command, tape(NOMINAL["toy.zero"])), "a made-after step is previewed at the prior"
    assert tuple(offset.runs) == (log_run(),)
    assert tuple(tilt.runs) == ()
    assert [s.status for s in schedule.steps] == ["known now", "made after", "known now", "fit only"]
    assert [tuple(s.commands_after) for s in schedule.steps] == [(), ("homing.single_touch",), (), ()]
    assert [r.id for r in schedule.runs] == ["zero/seq", "log"], "the runs known now, each once, in the order they are first played"
    assert [r.id for r in schedule.previews] == ["gain/tape"], "a made-after step's runs are previews, never shown as known"


@pytest.mark.parametrize("frame_from_zero, declared, status", [
    (True, None, "made after"),            # declares nothing: it requires toy.zero, which homing writes
    (False, (), "known now"),              # declares that its commands read nothing
    (False, ("toy.zero",), "made after"),  # declares the read: taken as declared, even where the tape happens not to move
])
def test_which_commands_wait_for_an_earlier_fit_comes_from_the_declaration_not_the_order(monkeypatch, frame_from_zero, declared, status):
    cal = _cal()
    routine = GainTape(frame_from_zero=frame_from_zero, commands_read=declared)
    rig = ChainRig((ZeroFind(), routine, OffsetFromLog(), TiltFromGain()))
    twin = make_twin(monkeypatch, rig, NOMINAL, TRUTH)
    routine.calls = 0
    steps = {s.routine: s for s in cal.plan(twin).steps}
    step = steps["servo.dynamics_regression"]
    assert step.after == ("homing.single_touch",), "the order still puts it after homing: it requires toy.zero"
    assert step.status == status
    assert tuple(step.commands_after) == (() if status == "known now" else ("homing.single_touch",))
    assert routine.calls <= 2, f"runs() called {routine.calls} times: plan() binds once and checks it is static, it never probes"
    offset = steps["servo.backlash_reversal_held"]
    assert (offset.status, tuple(offset.commands_after)) == ("known now", ()), "its fit reads the gain (uses); its commands read nothing"


def test_a_step_whose_commands_need_a_value_only_an_earlier_step_finds_has_no_preview(monkeypatch):
    cal = _cal()
    rig = ChainRig()
    twin = make_twin(monkeypatch, rig, {**NOMINAL, "toy.zero": None}, TRUTH)  # the description states no zero
    step = {s.routine: s for s in cal.plan(twin).steps}["servo.dynamics_regression"]
    assert step.status == "made after" and step.commands_after == ("homing.single_touch",)
    assert step.runs is None, "no prior to make its commands from: they exist only once homing has run"
    fitted = twin.calibrate(on="sim")
    played = [run for stream, run in rig.played if stream == "routine:servo.dynamics_regression"]
    assert len(played) == 1
    assert np.allclose(np.asarray(played[0].command.positions)[:, 0] - PATTERN, fitted.values_["toy.zero"].value, atol=1e-12)



def test_a_known_now_step_that_plays_other_commands_than_it_showed_is_refused(monkeypatch):
    """The schedule is what the robot will play. A routine whose declaration hides a read (its tape is in the homed frame, yet it declares
    its commands read nothing) shows as known now, and calibrate() refuses it by name before playing it: no probe needed, nothing guessed."""
    cal = _cal()
    liar = GainTape(frame_from_zero=True, commands_read=())
    rig = ChainRig((ZeroFind(), liar, OffsetFromLog(), TiltFromGain()))
    twin = make_twin(monkeypatch, rig, NOMINAL, TRUTH)
    assert {s.routine: s.status for s in cal.plan(twin).steps}["servo.dynamics_regression"] == "known now"
    with pytest.raises(cal.CalibrationPlanError) as refused:
        twin.calibrate(on="sim")
    assert "servo.dynamics_regression" in str(refused.value) and "gain/tape" in str(refused.value), str(refused.value)
    assert not [run for stream, run in rig.played if stream == "routine:servo.dynamics_regression"], "refused before it played"


def test_the_schedule_reads_as_text_and_as_json_and_leaves_the_frozen_step_rows_alone(chain):
    cal = _cal()
    twin, _rig = chain
    schedule = cal.plan(twin)
    text = schedule.summary()
    for words in ("commands made after homing.single_touch runs", "known now", "fit only", "zero/seq", "gain/tape"):
        assert words in text, (words, text)
    doc = json.loads(json.dumps(schedule.to_dict()))
    rows = {row["routine"]: row for row in doc["schedule"]}
    assert list(rows) == list(schedule.ids)
    assert rows["servo.dynamics_regression"]["status"] == "made after"
    assert rows["servo.dynamics_regression"]["commands_after"] == ["homing.single_touch"]
    assert [(r["id"], r["command"], r["preview"]) for r in rows["servo.dynamics_regression"]["runs"]] == [("gain/tape", "JointTrajectory", True)]
    assert [(r["command"], r["seconds"], r["preview"]) for r in rows["homing.single_touch"]["runs"]] == [("JointCommandSequence", [2.0, 6.0], False)]
    assert [(r["command"], r["seconds"]) for r in rows["servo.backlash_reversal_held"]["runs"]] == [(None, [0.0, 0.0])]
    assert rows["arm.gravity_direction"]["runs"] == [] and rows["arm.gravity_direction"]["status"] == "fit only"
    assert all(set(step) == STEP_KEYS for step in doc["steps"]), "the record's step rows stay sim2real.calibration/1's"




def test_the_schedule_tells_the_truth_about_what_calibrate_plays(chain):
    cal = _cal()
    twin, rig = chain
    schedule = cal.plan(twin)
    fitted = twin.calibrate(on="sim")
    assert fitted.plan_.ids == schedule.ids
    by_stream: dict[str, list] = {}
    for stream, run in rig.played:
        by_stream.setdefault(stream, []).append(run)
    bound = {s.routine: s for s in schedule.steps}
    for rid in ("homing.single_touch", "servo.backlash_reversal_held"):  # known now: exactly the commands the schedule showed
        played = by_stream[f"routine:{rid}"]
        assert [r.id for r in played] == [r.id for r in bound[rid].runs]
        assert all((p.command is None and b.command is None) or allclose(p.command, b.command)
                   for p, b in zip(played, bound[rid].runs)), rid
    played = by_stream["routine:servo.dynamics_regression"]  # made after homing: moved by exactly what homing found
    assert [r.id for r in played] == ["gain/tape"]
    found_zero = fitted.values_["toy.zero"].value
    assert found_zero != NOMINAL["toy.zero"]
    shift = np.asarray(played[0].command.positions) - np.asarray(bound["servo.dynamics_regression"].runs[0].command.positions)
    assert np.allclose(shift, found_zero - NOMINAL["toy.zero"], atol=1e-12)
    assert "routine:arm.gravity_direction" not in by_stream, "fit only: nothing played"
    recorded = fitted.record_.to_dict()["plan"]["schedule"]
    assert [row["status"] for row in recorded] == [s.status for s in schedule.steps], "the record carries the schedule that ran"


# --- 4. one run id, one command; a static schedule ---------------------------------------------------------------------------------------


def test_one_run_id_is_one_command(monkeypatch):
    cal = _cal()
    same = ChainRig((Shares(), Shares(id="servo.backlash_reversal_held", identifies=("toy.offset",))))
    schedule = cal.plan(make_twin(monkeypatch, same, NOMINAL, TRUTH))
    assert [r.id for r in schedule.runs] == ["shared"], "a run two steps read is one run, played once"
    assert all([r.id for r in s.runs] == ["shared"] for s in schedule.steps)
    clash = ChainRig((Shares(), Shares(id="servo.backlash_reversal_held", identifies=("toy.offset",), shift=0.25)))
    with pytest.raises(cal.CalibrationPlanError, match="shared"):
        cal.plan(make_twin(monkeypatch, clash, NOMINAL, TRUTH))



def test_a_run_id_a_made_after_step_shares_with_a_known_now_step_is_refused(monkeypatch):
    """At the priors both steps would play the same tape under "shared", but one of them is made after homing: once homing has run the
    two commands differ under one id. Refused at plan time, by the id."""
    cal = _cal()

    @dataclass
    class SharedAfterZero(Declared):
        id: str = "servo.dynamics_regression"
        identifies: tuple = ("toy.gain",)
        requires: tuple = ("toy.zero",)

        def runs(self, values):
            return [seam.Run("shared", "train", None, command=tape(dict(values)["toy.zero"]))]

        def fit(self, measured, values, twin):
            return {}

    rig = ChainRig((Shares(), SharedAfterZero()))
    with pytest.raises(cal.CalibrationPlanError, match="shared"):
        cal.plan(make_twin(monkeypatch, rig, NOMINAL, TRUTH))


def test_runs_that_change_between_two_calls_are_refused(monkeypatch):
    cal = _cal()
    with pytest.raises(cal.CalibrationPlanError) as refused:
        cal.plan(make_twin(monkeypatch, ChainRig((Restless(),)), NOMINAL, TRUTH))
    assert "servo.backlash_reversal_held" in str(refused.value) and "runs()" in str(refused.value)



# --- 5. collect records what a replay asks for ----------------------------------------------------------------------------------------------


def test_collect_records_a_made_after_step_the_way_a_replay_builds_it(chain, monkeypatch):
    cal = _cal()
    twin, rig = chain
    data = cal.collect(twin)
    collected = [run for _stream, run in rig.played if run.id == "gain/tape"][-1]
    frame = np.asarray(collected.command.positions)[:, 0] - PATTERN
    assert not np.allclose(frame, NOMINAL["toy.zero"], atol=1e-6), "collected in the frame homing found, never the prior's"

    def measured_again(*_args, **_kwargs):
        raise AssertionError("calibrate(data=) fits the recorded runs and never measures")

    monkeypatch.setattr(rig, "measure", measured_again)
    replayed = twin.calibrate(on="sim", data=data)
    assert replayed.values_["toy.zero"].value == pytest.approx(float(frame[0]), abs=1e-12), "the replay asks for the frame that was recorded"
    assert replayed.values_["toy.gain"].value == pytest.approx(TRUTH["toy.gain"], rel=0.05)


# --- 6. the pendulum ---------------------------------------------------------------------------------------------------------------------


def test_the_pendulum_schedule_shows_its_steps_known_now_on_one_train_run_of_the_committed_length():
    _need_rack()
    import sim2real  # noqa: PLC0415

    cal = _cal()
    twin = sim2real.examples.pendulum_can11(workers=WORKERS)
    schedule = cal.plan(twin)
    assert {"servo.backlash_reversals_camera", "servo.dynamics_regression"} <= set(schedule.ids), schedule.summary()
    with_runs = [s for s in schedule.steps if s.runs]
    assert {"servo.backlash_reversals_camera", "servo.dynamics_regression"} <= {s.routine for s in with_runs}
    assert all(s.status == "known now" and tuple(r.id for r in s.runs) == ("train",) for s in with_runs), schedule.summary()
    assert all(s.status == "fit only" for s in schedule.steps if s.runs is not None and not s.runs), "a tune after the fits plays nothing"
    assert [r.id for r in schedule.runs] == ["train"], "a run two steps share is one run"
    train = schedule.runs[0]
    assert train.command is None or isinstance(train.command, JointTrajectory), "the rack plays these runs: never labelled recorded data"
    seconds = json.loads(CAN11_RESULT.read_text())["schedule"]["train"]["seconds"]
    assert train.robot_seconds() == pytest.approx((seconds, seconds)), "the committed schedule's train seconds, read, never re-derived"
    assert "commands made after" not in schedule.summary(), "the regression reads step 1's gap in its fit, never in its commands"
    assert twin.generate_schedule().ids == schedule.ids
