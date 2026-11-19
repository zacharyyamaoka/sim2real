"""Gap T: a schedule's totals count a run that two steps share ONCE, the way the runner plays it.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_plan_totals_shared_runs.py

Run it on a cloud VM (bam_ws tools/cloud) while the arm is powered; add SIM2REAL_SLOW=1 for the fitted pendulum. The CAN 11 tests need
bam_rack_twin's venv; SIM2REAL_REQUIRE_RACK=1 (the cloud job sets it) turns their skip into a failure.

Zach, Daily Note 2026-11-17: the CalibrationSchedule is "a static description of the routines that will be run". A static description is
read before the robot moves, so what it says a calibration costs must be what playing it costs. CAN 11's two steps read the SAME train
runs (771.8 s: sysid/results/pendulum_can11.json schedule.train.seconds) and plan(twin).summary() added that motion once per step: 2744 s.
The runner plays a shared run once (RigRunner's `played`; the tracer measures the schedule once), and Budget.max_wall_time_s compared
against the double count, so a budget the real session fits dropped a routine (reports/pendulum-schedule-2026-11-17.html, "Left").

The ruler, written before the code; whoever turns it green may not edit it:
1. A run's length is Run.robot_seconds() (gap A: a timed command's own, else Run.seconds); plan() reads each kept routine's runs() ONCE,
   at the description's priors with CalibrationConfig.known on top, never for a routine the config drops.
2. totals["wall_time_s"] = each step's own time (its declared wall time less the known length of the runs it plays, floored at 0) plus
   every distinct run's known length once; totals["run_time_s"] = that run time ("runs planned at the priors, each counted once"). A
   step's own row still says what it costs alone. Two lengths for one run id is a declaration bug: refused by the id.
3. A run of unknown length is never guessed. A step whose runs read a value only an earlier fit gives keeps its whole time, plan() still
   answers, and its summary says so. Steps with no runs to read (catalog stand-ins, records of what ran) keep the per-step sum.
4. The budget and the strict refusal compare against the counted-once time.
5. CAN 11's train run carries the committed result's seconds (read from the file, never typed in), and its schedule counts them once.
"""

from __future__ import annotations

import json
import os
import sys
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # sysid lives beside the package
CAN11_RESULT = REPO / "sysid" / "results" / "pendulum_can11.json"
WRIST_RUN = REPO / "src" / "sim2real" / "data" / "ur_wrist_one_click_2026-11-11.json"
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
WORKERS = 2  # the powered rig's cap: at most 2 worker processes beside the arm
RECOVERS_CAN11 = {"servo.backlash_reversals_camera", "servo.dynamics_regression"}

OFFSET = "servo.backlash_reversal_held"
GAIN = "servo.breakaway_two_sided"
SHARED = (("shared0", 60.0), ("shared1", 40.0))   # two runs BOTH toy routines play: 100 s of motion
OWN = ("gain_own", 20.0)                          # a run only the gain routine plays
OFFSET_WALL_S = 50.0 + 100.0                      # its set-up + the shared runs
GAIN_WALL_S = 30.0 + 100.0 + 20.0                 # its set-up + the shared runs + its own run
COUNTED_ONCE_S = 50.0 + 30.0 + 100.0 + 20.0       # each set-up once, each run once: 200 s (the per-step sum says 300 s)
RUN_TIME_S = 60.0 + 40.0 + 20.0                   # the distinct runs, each once

TRUTH = {"toy.gain": 2.5, "toy.offset": -0.4}
NOMINAL = {"toy.gain": 2.0, "toy.offset": 0.0}


def _calibration():
    """WHY imported per test and never importorskip: a missing back end must FAIL here, not skip."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module


def _need_rack():
    if os.environ.get("SIM2REAL_REQUIRE_RACK") == "1":
        import bam_rack_twin  # noqa: F401, PLC0415
    else:
        pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv")


def _run(run_id: str, seconds: float | None):
    from sim2real import rig as seam  # noqa: PLC0415

    return seam.Run(run_id, "train", None, seconds=seconds)


def _inputs(run_id: str) -> np.ndarray:
    return np.random.default_rng(zlib.crc32(run_id.encode())).uniform(-1.0, 1.0, 300)


@dataclass
class OffsetFit:
    id: str = OFFSET
    identifies: tuple[str, ...] = ("toy.offset",)
    requires: tuple[str, ...] = ()
    wall_time_s: float = OFFSET_WALL_S
    lengths_known: bool = True
    asked: list = field(default_factory=list)   # the values each runs() call was handed

    def runs(self, values):
        self.asked.append(dict(values))
        return [_run(rid, s if self.lengths_known else None) for rid, s in SHARED]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        y = np.concatenate([m["y"] - values["toy.gain"] * m["u"] for m in measured.values()])
        mean = float(np.mean(y))
        return {"toy.offset": seam.Estimate(mean, (mean - 0.01, mean + 0.01), "mean residual")}


@dataclass
class GainFit:
    id: str = GAIN
    identifies: tuple[str, ...] = ("toy.gain",)
    requires: tuple[str, ...] = ("toy.offset",)
    wall_time_s: float = GAIN_WALL_S
    lengths_known: bool = True
    made_after: bool = False
    shared_seconds: float | None = None   # set: it gives shared0 another length than the offset step does
    asked: list = field(default_factory=list)

    def runs(self, values):
        self.asked.append(dict(values))
        if self.made_after:
            # a command built from a value only an earlier fit gives (as the wrist's breakaway reads step 1's gap): the priors lack it
            float(values["toy.offset_found_by_step_1"])
        shared = [_run(rid, s if self.lengths_known else None) for rid, s in SHARED]
        if self.shared_seconds is not None:
            shared[0] = _run(SHARED[0][0], self.shared_seconds)
        return [*shared, _run(*OWN)]

    def fit(self, measured, values, twin):
        from sim2real import rig as seam  # noqa: PLC0415

        u = np.concatenate([m["u"] for m in measured.values()])
        y = np.concatenate([m["y"] for m in measured.values()]) - values["toy.offset"]
        gain = float(u @ y / (u @ u))
        return {"toy.gain": seam.Estimate(gain, (gain - 0.01, gain + 0.01), "least squares through the found offset")}


class ToyRig:
    name = "toy"

    def __init__(self, **options):
        self.offset = OffsetFit(lengths_known=options.get("lengths_known", True))
        self.gain = GainFit(lengths_known=options.get("lengths_known", True), made_after=options.get("made_after", False),
                            shared_seconds=options.get("shared_seconds"))

    def parameters(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return (seam.Parameter("toy.gain", "1", ("rel", 0.05), "proposed", self.gain.id),
                seam.Parameter("toy.offset", "1", ("abs", 0.05), "proposed", self.offset.id))

    def noise(self):
        from sim2real import rig as seam  # noqa: PLC0415

        return seam.NoiseModel(torque_noise_nm=0.02, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return (self.gain, self.offset)   # the planner orders them: the gain requires the offset

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


def toy_description():
    from robot_msgs.space import Basis, Value  # noqa: PLC0415

    from sim2real.twin import Description, Instance  # noqa: PLC0415

    params = {k.split(".", 1)[1]: Value(v, "1", basis=Basis.ASSUMED, source="the toy's datasheet") for k, v in NOMINAL.items()}
    return Description("toy", "Toy rig", model=None, instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("toy", "Toy servo", "integrated_servo", "cell", params, {k: False for k in params})), source="tests")


def world_doc() -> dict:
    from sysid import world as hidden  # noqa: PLC0415

    if hidden.is_sealed():
        raise hidden.SealedWorld("sealed")
    return {"truth": dict(TRUTH), "seed": 3}


def _toy_twin(monkeypatch, **options):
    from sim2real import rig as seam  # noqa: PLC0415
    from sim2real import twin as twin_module  # noqa: PLC0415

    rig = ToyRig(**options)
    monkeypatch.setattr(twin_module, "_runner", lambda description, workers: seam.RigRunner(description, rig, workers=1, world=world_doc))
    return twin_module.RobotTwin(toy_description().instances, name="toy"), rig


# --- fast: lengths and the counted-once totals (no MuJoCo, no bam_ws) ------------------------------------------------------------------


def test_a_run_carries_its_length_and_the_three_field_form_still_builds():
    from sim2real import rig as seam  # noqa: PLC0415

    assert seam.Run("r", "train", None).seconds is None, "a run's length is unknown unless the rig says it"
    assert seam.Run("r", "train", None, seconds=12.5).robot_seconds() == (12.5, 12.5)


def test_can11s_train_run_carries_the_committed_seconds_read_from_the_result_file():
    """No bam_rack_twin needed: the routines module imports only sim2real.rig. WHY here and not only under the rack's venv: a wrong path to
    the result file would give None silently and bring the double count back unseen."""
    from sysid.examples.pendulum_can11 import routines  # noqa: PLC0415

    seconds = json.loads(CAN11_RESULT.read_text())["schedule"]["train"]["seconds"]
    assert routines.TRAIN.seconds == pytest.approx(seconds), routines.TRAIN
    assert routines.TRAIN.robot_seconds() == pytest.approx((seconds, seconds))


def test_a_run_two_steps_share_is_counted_once(monkeypatch):
    cal = _calibration()
    twin, _rig = _toy_twin(monkeypatch)
    schedule = cal.plan(twin)
    assert schedule.ids == (OFFSET, GAIN), schedule.summary()
    walls = {s.routine: s.wall_time_s for s in schedule.steps}
    assert walls == pytest.approx({OFFSET: OFFSET_WALL_S, GAIN: GAIN_WALL_S}), "a step's own row still says what it costs alone"
    assert schedule.totals["wall_time_s"] == pytest.approx(COUNTED_ONCE_S), schedule.summary()
    assert schedule.totals["run_time_s"] == pytest.approx(RUN_TIME_S)
    assert f"{COUNTED_ONCE_S:.0f} s wall" in schedule.summary().splitlines()[0], schedule.summary()


def test_plan_reads_each_kept_routines_runs_once_at_the_priors_and_known_values(monkeypatch):
    cal = _calibration()
    twin, rig = _toy_twin(monkeypatch)
    rig.offset.asked.clear()
    rig.gain.asked.clear()
    cal.plan(twin, cal.CalibrationConfig(known={"toy.gain": 2.2}))
    assert rig.gain.asked == [], "a routine the config drops (everything it finds is known) is never asked for its runs"
    assert rig.offset.asked and all(a == {"toy.gain": 2.2, "toy.offset": 0.0} for a in rig.offset.asked), rig.offset.asked
    assert len(rig.offset.asked) <= 2, "bound once, and once more to check it is static (gap A): never a probe per key"


def test_the_budget_keeps_both_steps_when_the_counted_once_time_fits(monkeypatch):
    cal = _calibration()
    twin, _rig = _toy_twin(monkeypatch)
    fits = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(max_wall_time_s=250.0)))
    assert fits.ids == (OFFSET, GAIN), fits.summary()
    assert not [rid for rid, why in fits.dropped if "outside the budget" in why], fits.dropped
    strict = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(max_wall_time_s=250.0), strict=True))
    assert strict.ids == (OFFSET, GAIN)


def test_over_the_counted_once_time_the_budget_names_it(monkeypatch):
    cal = _calibration()
    twin, _rig = _toy_twin(monkeypatch)
    tight = cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(max_wall_time_s=199.0)))
    assert tight.ids == (OFFSET,), tight.summary()
    over = [(rid, why) for rid, why in tight.dropped if "outside the budget" in why]
    assert len(over) == 1 and over[0][0] == GAIN, tight.dropped
    assert "wall time 200 s" in over[0][1], over[0][1]
    assert tight.totals["wall_time_s"] == pytest.approx(OFFSET_WALL_S), "alone, the offset step plays the shared runs itself"
    with pytest.raises(cal.CalibrationPlanError, match="wall time is 200 s"):
        cal.plan(twin, cal.CalibrationConfig(budget=cal.Budget(max_wall_time_s=199.0), strict=True))


def test_two_lengths_for_one_run_are_refused_by_the_id(monkeypatch):
    cal = _calibration()
    twin, _rig = _toy_twin(monkeypatch, shared_seconds=75.0)
    with pytest.raises(cal.CalibrationPlanError, match="shared0"):
        cal.plan(twin)


def test_a_run_of_unknown_length_is_never_guessed(monkeypatch):
    cal = _calibration()
    twin, _rig = _toy_twin(monkeypatch, lengths_known=False)
    schedule = cal.plan(twin)
    assert schedule.totals["wall_time_s"] == pytest.approx(OFFSET_WALL_S + GAIN_WALL_S), "unknown lengths: the per-step count stands"
    assert schedule.totals["run_time_s"] == pytest.approx(OWN[1]), "only the run whose length is known"


def test_a_step_whose_runs_need_an_earlier_fit_keeps_its_whole_time_and_says_so(monkeypatch):
    cal = _calibration()
    twin, _rig = _toy_twin(monkeypatch, made_after=True)
    schedule = cal.plan(twin)   # plays nothing; a runs() that needs a found value never makes plan() fail
    assert schedule.ids == (OFFSET, GAIN)
    assert schedule.totals["run_time_s"] == pytest.approx(100.0), "the offset step's shared runs, known at the priors"
    assert schedule.totals["wall_time_s"] == pytest.approx(OFFSET_WALL_S + GAIN_WALL_S)
    lines = [line for line in schedule.summary().splitlines() if GAIN in line and "counted whole" in line]
    assert lines, f"the summary names the step whose runs are unknown until an earlier step runs:\n{schedule.summary()}"


def test_the_fitted_twin_records_the_counted_once_totals(monkeypatch):
    twin, _rig = _toy_twin(monkeypatch)
    fitted = twin.calibrate(on="sim")
    assert fitted.plan_.totals["wall_time_s"] == pytest.approx(COUNTED_ONCE_S)
    totals = fitted.record_.to_dict()["plan"]["totals"]
    assert totals["wall_time_s"] == pytest.approx(COUNTED_ONCE_S)
    assert totals["run_time_s"] == pytest.approx(RUN_TIME_S)


def test_steps_with_no_runs_to_read_keep_the_per_step_sum():
    cal = _calibration()
    catalog = cal.plan({"cam": ("camera", "M1.measurement.distortion")})
    assert catalog.totals["wall_time_s"] == pytest.approx(sum(s.wall_time_s for s in catalog.steps))
    assert catalog.totals["run_time_s"] == 0.0
    from sim2real.twin import describe  # noqa: PLC0415

    doc = json.loads(WRIST_RUN.read_text())
    record = cal.CalibrationRecord.from_rig(doc["calibration"], report=doc["report"], description=describe("ur_wrist_test_rig")).to_dict()
    steps = record["plan"]["steps"]
    assert record["plan"]["totals"]["wall_time_s"] == pytest.approx(sum(s["wall_time_s"] for s in steps)), "a record of what ran"
    assert record["plan"]["totals"]["run_time_s"] == 0.0


def test_the_counted_once_rule_is_documented():
    text = (REPO / "docs" / "CALIBRATE.md").read_text()
    assert "`run_time_s`" in text and "counted once" in text


# --- fast on CAN 11 (bam_rack_twin's venv): the pendulum's two steps share the train runs ---------------------------------------------------


def test_can11s_two_steps_count_the_train_runs_once():
    _need_rack()
    import sim2real  # noqa: PLC0415

    cal = _calibration()
    twin = sim2real.examples.pendulum_can11(workers=WORKERS)
    schedule = cal.plan(twin)
    assert RECOVERS_CAN11 <= set(schedule.ids), schedule.summary()
    runs = {s.routine: {r.id: r for r in (s.runs or ())} for s in schedule.steps}
    gap, dynamics = (runs[rid] for rid in sorted(RECOVERS_CAN11))
    assert set(gap) and set(gap) == set(dynamics), "both steps read the same train runs"
    train_s = json.loads(CAN11_RESULT.read_text())["schedule"]["train"]["seconds"]
    assert sum(r.robot_seconds()[1] for r in gap.values()) == pytest.approx(train_s, abs=0.05), "the committed train seconds"
    distinct = {rid: r for per in runs.values() for rid, r in per.items()}
    plays = Counter(rid for per in runs.values() for rid in per)
    walls = sum(s.wall_time_s for s in schedule.steps)
    length = {rid: (r.robot_seconds() or (0.0, 0.0))[1] for rid, r in distinct.items()}
    expected = walls - sum((plays[rid] - 1) * length[rid] for rid in distinct)
    assert expected <= walls - train_s + 0.05, "the shared train runs are counted once"
    assert schedule.totals["wall_time_s"] == pytest.approx(expected, abs=0.05), schedule.summary()
    assert schedule.totals["run_time_s"] == pytest.approx(sum(length.values()), abs=0.05)
    assert f"{expected:.0f} s wall" in schedule.summary().splitlines()[0], schedule.summary()


@pytest.mark.skipif(not SLOW, reason="SIM2REAL_SLOW=1: the CAN 11 oracle's calibration takes minutes (cloud VM only)")
def test_slow_the_fitted_can11_records_the_counted_once_totals():
    _need_rack()
    import sim2real  # noqa: PLC0415

    cal = _calibration()
    twin = sim2real.examples.pendulum_can11(workers=WORKERS)
    schedule = cal.plan(twin)
    fitted = twin.calibrate(on="sim", truth="sealed")
    recorded = fitted.record_.to_dict()["plan"]
    assert recorded["totals"]["wall_time_s"] == pytest.approx(schedule.totals["wall_time_s"])
    assert recorded["totals"]["wall_time_s"] < sum(s["wall_time_s"] for s in recorded["steps"]) - 1.0, "the shared runs counted once"
    assert recorded["totals"]["run_time_s"] == pytest.approx(schedule.totals["run_time_s"])
