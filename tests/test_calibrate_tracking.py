"""Gap E: a calibration you can watch while it runs (2026-11-18, red first). calibrate(callbacks=...) reports the schedule, each step as it
finishes, the fitted twin and evaluate()'s gates to a local ledger first (events.jsonl beside schedule.json, calibration.json, eval.json),
and to W&B only as a copy rebuilt from that ledger, in the deployment's or rig's registered project.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_calibrate_tracking.py

Run it on a cloud VM while the arm is powered, twice: in sim2real's own venv (wandb is there) and in bam_rack_twin's venv (the pendulum and
rack tests; SIM2REAL_REQUIRE_RACK=1 turns their skip into a failure); add SIM2REAL_SLOW=1 with WANDB_MODE=offline for the slow tier.

Zach, Daily Note 2026-11-17: "As that calibration is running you will see like the results in weights and biases, or etc. you can
visually see once it has been calibrated and how it improves." "I decied I would have a weights and bias account for each deployment."
"W&B is just a visualizer for the dat". 2026-11-11: "have the results like show up in weights and biases should be all automated".
House rule: W&B is a copy of a local ledger; register a project in bam_ws tools/wandb_trackers/trackers/ before its first run.

The ruler, each item a way the logging could lie; written before the code, and whoever turns it green may not edit it:
1. A callback sees the schedule, then one step per planned routine in order AS EACH FINISHES (the next fit can read the last step off
   disk; the tracer's runner hands each step over before the next fit runs), then the fitted twin, then evaluate()'s report.
2. The ledger is enough on its own: the schedule, every step with the runs it read, its found values with intervals and units (SI), the
   record (calibration.json) and the report (eval.json); one folder per calibration, and a reused Ledger never writes one calibration's
   events into another's folder.
3. Observers never guard: a callback that raises is detached with a warning and the fit is unchanged; a calibration that fails still
   raises and its ledger ends saying so; a fitted twin built without callbacks still evaluates.
4. Defaults: a sim calibration writes nothing unless asked (sweeps call it hundreds of times); a rack calibration keeps a ledger beside
   its submission; SIM2REAL_TRACK=off|ledger|wandb overrides, callbacks=[] wins, an unknown value is refused by name, resolving never
   imports wandb.
5. On the rack the schedule is on disk before the rack plays, each step lands as its fit finishes, and runs still to be played end the
   ledger "pending" (not "error").
6. The W&B copy: one run per calibration with a stable id; rows schedule -> each step -> outcome -> evaluation, gate values beside their
   verdicts; angles in degrees (Zach, 2026-11-11); the live copy and a follower process log exactly the rows the replay rebuilds; a W&B
   that will not start costs one warning, never a retry loop, never the ledger.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import shutil
import subprocess
import sys
import types
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
SCHEMA = "sim2real.calibration-events/1"
TRUTH = {"toy.gain": 2.5, "toy.offset": -0.4}
NOMINAL = {"toy.gain": 2.0, "toy.offset": 0.0}
UNITS = {"toy.gain": "1", "toy.offset": "rad"}  # WHY one angle: the W&B copy must show it in degrees while the ledger keeps radians
OFFSET_ID, GAIN_ID = "servo.backlash_reversal_held", "servo.breakaway_two_sided"  # registered ids (the seam refuses others)
RUN_KEYS = {"id", "name", "group", "job_type", "tags", "notes", "config", "history", "summary", "tables"}  # wandb_log.records()'s shape


def _cal():
    """WHY imported per test and never importorskip: a missing piece must FAIL here, not skip."""
    import sim2real.calibration as module  # noqa: PLC0415

    return module


def _copy():
    from sim2real.tracking import calibrate_wandb  # noqa: PLC0415

    return calibrate_wandb


def _need_rack():
    if os.environ.get("SIM2REAL_REQUIRE_RACK") == "1":
        import bam_rack_twin  # noqa: F401, PLC0415
    else:
        pytest.importorskip("bam_rack_twin", reason="the CAN 11 pendulum runs in bam_rack_twin's venv")


def _seam():
    from sim2real import rig as seam  # noqa: PLC0415

    return seam


def events(folder: Path) -> list[dict]:
    return [json.loads(line) for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def kinds(folder: Path) -> list[str]:
    return [e["kind"] for e in events(folder)]


def steps(folder: Path) -> list[dict]:
    return [e for e in events(folder) if e["kind"] == "step"]


def roundtrip(obj):
    return json.loads(json.dumps(obj, default=str))


# --- the toy rig: y = gain u + offset + noise (tests/test_calibration_backend.py's, the offset in radians) --------------------------------


def _inputs(run_id: str) -> np.ndarray:
    return np.random.default_rng(zlib.crc32(run_id.encode())).uniform(-1.0, 1.0, 300)


def toy_description():
    from robot_msgs.space import Basis, Value  # noqa: PLC0415

    from sim2real.twin import Description, Instance  # noqa: PLC0415

    params = {k.split(".", 1)[1]: Value(v, UNITS[k], basis=Basis.ASSUMED, source="the toy's datasheet") for k, v in NOMINAL.items()}
    return Description("toy", "Toy rig", model=None, instances=(
        Instance("cell", "Cell", None, None, structural="deployment"),
        Instance("toy", "Toy servo", "integrated_servo", "cell", params, {k: False for k in params})), source="tests")


def world_doc() -> dict:
    from sysid import world as hidden  # noqa: PLC0415

    if hidden.is_sealed():
        raise hidden.SealedWorld("sealed")
    return {"truth": dict(TRUTH), "seed": 3}


@dataclass
class OffsetFit:
    id: str = OFFSET_ID
    identifies: tuple[str, ...] = ("toy.offset",)
    requires: tuple[str, ...] = ()

    def runs(self, values):
        return [_seam().Run(f"zero{k}", "train", None) for k in range(3)]

    def fit(self, measured, values, twin):
        y = np.concatenate([m["y"] - values["toy.gain"] * m["u"] for m in measured.values()])
        mean = float(np.mean(y))
        return {"toy.offset": _seam().Estimate(mean, (mean - 0.01, mean + 0.01), "mean residual")}


@dataclass
class GainFit:
    id: str = GAIN_ID
    identifies: tuple[str, ...] = ("toy.gain",)
    requires: tuple[str, ...] = ("toy.offset",)
    options: dict = field(default_factory=lambda: {"runs": 4})
    peek: object = None        # called inside fit: what the test reads off disk while the calibration is still running
    broken: bool = False       # the fit raises: a calibration that fails
    seen: list = field(default_factory=list)

    def runs(self, values):
        return [_seam().Run(f"gain{k}", "train", None) for k in range(int(self.options["runs"]))]

    def fit(self, measured, values, twin):
        if self.peek is not None:
            self.seen.append(self.peek())
        if self.broken:
            raise RuntimeError("the gain fit broke")
        u = np.concatenate([m["u"] for m in measured.values()])
        y = np.concatenate([m["y"] for m in measured.values()]) - values["toy.offset"]
        gain = float(u @ y / (u @ u))
        return {"toy.gain": _seam().Estimate(gain, (gain - 0.01, gain + 0.01), "least squares through the found offset")}


class ToyRig:
    name = "toy"

    def __init__(self):
        self.gain, self.offset = GainFit(), OffsetFit()

    def parameters(self):
        seam = _seam()
        return (seam.Parameter("toy.gain", UNITS["toy.gain"], ("rel", 0.05), "proposed", self.gain.id),
                seam.Parameter("toy.offset", UNITS["toy.offset"], ("abs", 0.05), "proposed", self.offset.id))

    def noise(self):
        return _seam().NoiseModel(torque_noise_nm=0.02, sources={"torque_noise_nm": "the toy's datasheet"})

    def routines(self):
        return (self.gain, self.offset)   # the planner orders them: the gain needs the offset first

    def held_out(self, values=None):
        return [_seam().Run(f"held{k}", "held_out", None) for k in range(2)]

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
        per_run = {rid: {"toy": float(np.sqrt(np.mean((predicted[rid]["y"] - m["y"]) ** 2)))} for rid, m in measured.items()}
        return _seam().Score({"toy": float(np.mean([v["toy"] for v in per_run.values()]))}, per_run)


@pytest.fixture
def toy(monkeypatch):
    from sim2real import twin as twin_module  # noqa: PLC0415

    monkeypatch.delenv("SIM2REAL_TRACK", raising=False)
    monkeypatch.delenv("SIM2REAL_CALIBRATIONS", raising=False)
    rig = ToyRig()
    monkeypatch.setattr(twin_module, "_runner", lambda description, workers: _seam().RigRunner(description, rig, workers=1, world=world_doc))
    d = toy_description()
    return twin_module.RobotTwin(d.instances, name="toy"), rig




# --- 1. the hooks: the schedule, each step as it finishes, the fitted twin, the report -------------------------------------------------------


class Recorder:
    """Duck-typed on purpose (no base class): a callback implements only the hooks it wants."""

    def __init__(self):
        self.calls = []

    def on_calibrate_begin(self, event, *, schedule, twin):
        self.calls.append(("begin", event["kind"], schedule, twin))

    def on_step_end(self, event):
        self.calls.append(("step", event["kind"], event["routine"], None))

    def on_calibrate_end(self, event, *, fitted):
        self.calls.append(("end", event["kind"], fitted, None))

    def on_evaluate_end(self, event, *, report, fitted):
        self.calls.append(("evaluate", event["kind"], report, fitted))


def test_calibrate_takes_callbacks():
    from sim2real.twin import RobotTwin  # noqa: PLC0415

    assert "callbacks" in inspect.signature(RobotTwin.calibrate).parameters


def test_a_callback_sees_the_schedule_then_each_step_then_the_fitted_twin_then_the_report(toy):
    twin, _ = toy
    seen = Recorder()
    fitted = twin.calibrate(on="sim", callbacks=[seen])
    assert [c[:2] for c in seen.calls] == [("begin", "schedule"), ("step", "step"), ("step", "step"), ("end", "done")]
    _, _, schedule, given = seen.calls[0]
    assert tuple(schedule.ids) == tuple(fitted.plan_.ids) == (OFFSET_ID, GAIN_ID), "the schedule calibrate() then plays"
    assert given is twin
    assert [c[2] for c in seen.calls[1:3]] == [OFFSET_ID, GAIN_ID], "one step per planned routine, in the planned order"
    assert seen.calls[3][2] is fitted
    assert tuple(fitted.callbacks_) == (seen,), "the fitted twin keeps its callbacks, so evaluate() reports to them"
    report = fitted.evaluate()
    assert seen.calls[4][:2] == ("evaluate", "evaluate") and seen.calls[4][2] is report and seen.calls[4][3] is fitted


def test_the_ledger_is_written_as_the_calibration_runs_not_after(toy, tmp_path):
    cal = _cal()
    twin, rig = toy
    ledger = cal.Ledger(tmp_path / "ledgers")
    rig.gain.peek = lambda: events(ledger.folder)
    twin.calibrate(on="sim", callbacks=[ledger])
    on_disk = rig.gain.seen[-1]
    assert [e["kind"] for e in on_disk] == ["schedule", "step"], "while the gain fit runs, the offset step is already on disk"
    assert on_disk[1]["routine"] == OFFSET_ID
    assert ledger.folder.parent == tmp_path / "ledgers" and "toy" in ledger.folder.name
    assert kinds(ledger.folder) == ["schedule", "step", "step", "done"]


# --- 2. the ledger alone is enough ---------------------------------------------------------------------------------------------------------


def test_the_ledger_holds_the_plan_every_step_with_its_intervals_and_the_record(toy, tmp_path):
    cal = _cal()
    twin, _ = toy
    ledger = cal.Ledger(tmp_path)
    fitted = twin.calibrate(on="sim", callbacks=[ledger])
    folder = ledger.folder
    lines = events(folder)
    assert all(e["schema"] == SCHEMA for e in lines)
    plan_event = lines[0]
    assert plan_event["kind"] == "schedule" and plan_event["twin"] == "toy" and plan_event["backend"] == "sim"
    assert plan_event["schedule"] == roundtrip(fitted.plan_.to_dict())
    assert json.loads((folder / "schedule.json").read_text(encoding="utf-8")) == roundtrip(fitted.plan_.to_dict())
    record = roundtrip(fitted.record_.to_dict())
    assert json.loads((folder / "calibration.json").read_text(encoding="utf-8")) == record, "the frozen sim2real.calibration/1 record"
    logged = steps(folder)
    assert [s["index"] for s in logged] == [0, 1]
    assert [s["routine"] for s in logged] == [r["routine"] for r in record["routines"]] == list(fitted.plan_.ids)
    assert logged[0]["runs"] == [f"zero{k}" for k in range(3)] and logged[1]["runs"] == [f"gain{k}" for k in range(4)]
    assert logged[0]["played"] == logged[0]["runs"] and logged[1]["played"] == logged[1]["runs"], "each run measured once, by its step"
    assert all(s["live"] is True for s in logged), "sent as each step finished, not rebuilt afterwards"
    for step, row in zip(logged, record["routines"]):
        assert {k: f["value"] for k, f in step["found"].items()} == row["found"], "the ledger's steps are the record's routines"
        assert len(step["runs"]) == row["runs"]
        assert step["collected"] == "measured" and step["round"] == 0
        assert step["collect_s"] >= 0 and step["fit_s"] >= 0 and step["collect_s"] + step["fit_s"] <= step["seconds"] + 0.1
    offset = logged[0]["found"]["toy.offset"]
    assert offset["unit"] == "rad" and offset["value"] == pytest.approx(fitted.values_["toy.offset"].value), "SI in the ledger"
    assert offset["ci95"][0] <= offset["value"] <= offset["ci95"][1] and offset["method"] == "mean residual"
    gain = logged[1]["found"]["toy.gain"]
    assert gain["method"] == "least squares through the found offset" and gain["value"] == pytest.approx(TRUTH["toy.gain"], rel=0.05)
    done = lines[-1]
    assert done["kind"] == "done" and done["passed"] is fitted.calibration_.passed is True


def test_evaluate_appends_its_gates_to_the_same_ledger(toy, tmp_path):
    cal = _cal()
    twin, _ = toy
    ledger = cal.Ledger(tmp_path)
    fitted = twin.calibrate(on="sim", callbacks=[ledger])
    report = fitted.evaluate()
    assert kinds(ledger.folder) == ["schedule", "step", "step", "done", "evaluate"]
    last = events(ledger.folder)[-1]
    assert last["passed"] is report.passed
    assert [(g["id"], g["passed"]) for g in last["gates"]] == [(g.id, g.passed) for g in report.gates]
    assert all(g["value"] == pytest.approx(float(r.value)) for g, r in zip(last["gates"], report.gates)
               if isinstance(r.value, (int, float)) and math.isfinite(r.value)), "each gate's value beside its verdict"
    assert json.loads((ledger.folder / "eval.json").read_text(encoding="utf-8")) == roundtrip(report.to_dict())
    assert list(tmp_path.iterdir()) == [ledger.folder], "one folder per calibration"


def test_a_fit_on_recorded_runs_is_logged_as_recorded(toy, tmp_path):
    cal = _cal()
    twin, _ = toy
    data = cal.collect(twin)
    ledger = cal.Ledger(tmp_path)
    twin.calibrate(data=data, callbacks=[ledger])
    assert [s["collected"] for s in steps(ledger.folder)] == ["recorded", "recorded"]


# --- 3. observers never guard -----------------------------------------------------------------------------------------------------------------


class Exploding:
    def __init__(self):
        self.calls = 0

    def on_step_end(self, event):
        self.calls += 1
        raise ValueError("the dashboard is down")


def test_a_callback_that_raises_is_detached_and_never_changes_the_fit(toy, tmp_path):
    cal = _cal()
    twin, _ = toy
    clean = twin.calibrate(on="sim")
    boom, ledger = Exploding(), cal.Ledger(tmp_path)
    with pytest.warns(RuntimeWarning, match="the dashboard is down"):
        fitted = twin.calibrate(on="sim", callbacks=[boom, ledger])
    assert boom.calls == 1, "detached after its first failure"
    assert {k: v.value for k, v in fitted.values_.items()} == pytest.approx({k: v.value for k, v in clean.values_.items()}, rel=1e-12)
    got = kinds(ledger.folder)
    assert [k for k in got if k != "callback_error"] == ["schedule", "step", "step", "done"]
    errors = [e for e in events(ledger.folder) if e["kind"] == "callback_error"]
    assert len(errors) == 1 and errors[0]["callback"] == "Exploding" and errors[0]["hook"] == "on_step_end"
    assert "the dashboard is down" in errors[0]["error"]


def test_a_calibration_that_fails_still_raises_and_its_ledger_says_where(toy, tmp_path):
    cal = _cal()
    twin, rig = toy
    rig.gain.broken = True
    ledger = cal.Ledger(tmp_path)
    with pytest.raises(RuntimeError, match="the gain fit broke"):
        twin.calibrate(on="sim", callbacks=[ledger])
    lines = events(ledger.folder)
    assert [e["kind"] for e in lines] == ["schedule", "step", "error"]
    assert lines[1]["routine"] == OFFSET_ID and "the gain fit broke" in lines[-1]["error"]


def test_a_live_copy_that_cannot_reach_wandb_leaves_the_ledger_whole(toy, tmp_path, monkeypatch):
    cal, copy = _cal(), _copy()
    twin, _ = toy
    monkeypatch.setitem(sys.modules, "wandb", None)  # `import wandb` raises ImportError, as in an env without the tracking extra
    ledger = cal.Ledger(tmp_path)
    with pytest.warns(RuntimeWarning, match="WandbLogger"):
        fitted = twin.calibrate(on="sim", callbacks=[ledger, copy.WandbLogger(ledger, project="Sim2Real")])
    assert [k for k in kinds(ledger.folder) if k != "callback_error"] == ["schedule", "step", "step", "done"]
    errors = [e for e in events(ledger.folder) if e["kind"] == "callback_error"]
    assert len(errors) == 1 and errors[0]["callback"] == "WandbLogger"
    assert fitted.values_["toy.gain"].value == pytest.approx(TRUTH["toy.gain"], rel=0.05)


# --- 4. off by default; SIM2REAL_TRACK opts in ------------------------------------------------------------------------------------------------


def test_by_default_calibrate_writes_nothing(toy, tmp_path, monkeypatch):
    twin, _ = toy
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SIM2REAL_CALIBRATIONS", str(tmp_path / "ledgers"))
    fitted = twin.calibrate(on="sim")
    fitted.evaluate()
    assert tuple(fitted.callbacks_) == ()
    assert not (tmp_path / "ledgers").exists() and not (tmp_path / "home").exists(), "calibrate() writes nothing unless asked"


def test_SIM2REAL_TRACK_ledger_opts_in_without_code_and_an_explicit_empty_list_wins(toy, tmp_path, monkeypatch):
    twin, _ = toy
    root = tmp_path / "ledgers"
    monkeypatch.setenv("SIM2REAL_CALIBRATIONS", str(root))
    monkeypatch.setenv("SIM2REAL_TRACK", "ledger")
    twin.calibrate(on="sim", callbacks=[])
    assert not root.exists(), "callbacks=[] wins over the environment"
    fitted = twin.calibrate(on="sim")
    (folder,) = list(root.iterdir())
    assert kinds(folder) == ["schedule", "step", "step", "done"]
    fitted.evaluate()
    assert kinds(folder)[-1] == "evaluate"
    monkeypatch.setenv("SIM2REAL_TRACK", "off")
    twin.calibrate(on="sim")
    assert list(root.iterdir()) == [folder]


def test_an_unknown_SIM2REAL_TRACK_is_refused_by_name(toy, monkeypatch):
    twin, _ = toy
    monkeypatch.setenv("SIM2REAL_TRACK", "loud")
    with pytest.raises(ValueError, match="SIM2REAL_TRACK") as caught:
        twin.calibrate(on="sim")
    assert all(word in str(caught.value) for word in ("off", "ledger", "wandb"))


def test_SIM2REAL_TRACK_wandb_adds_the_live_copy_without_importing_wandb(tmp_path):
    code = ("import sys; from sim2real.calibration import resolve_callbacks; found = resolve_callbacks(None); "
            "print(' '.join(type(c).__name__ for c in found), found[1].ledger is found[0], 'wandb' in sys.modules)")
    env = {**os.environ, "SIM2REAL_TRACK": "wandb", "SIM2REAL_CALIBRATIONS": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env).stdout.split()
    assert out == ["Ledger", "WandbLogger", "True", "False"]
    assert list(tmp_path.iterdir()) == [], "resolving writes nothing: a ledger opens its folder when a calibration begins"


def test_importing_the_copy_never_imports_wandb():
    code = "import sys, sim2real.calibration, sim2real.tracking.calibrate_wandb; print('wandb' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["False"]


# --- 5. the W&B copy, rebuilt from the ledger alone -------------------------------------------------------------------------------------------


def test_the_wandb_copy_is_one_run_per_calibration_rebuilt_from_the_ledger(toy, tmp_path):
    cal, copy = _cal(), _copy()
    twin, _ = toy
    ledger = cal.Ledger(tmp_path)
    fitted = twin.calibrate(on="sim", callbacks=[ledger])
    report = fitted.evaluate()
    (run,) = copy.records(ledger.folder)
    assert RUN_KEYS <= set(run)
    assert run["id"] == copy.records(ledger.folder)[0]["id"] and len(run["id"]) == 16 and int(run["id"], 16) >= 0, "a stable W&B id"
    assert run["job_type"] == "calibrate"
    assert run["config"]["twin"] == "toy" and run["config"]["backend"] == "sim"
    assert run["config"]["routines"] == list(fitted.plan_.ids) and run["config"]["ledger"] == ledger.folder.name
    history = run["history"]
    assert len(history) == 1 + 2 + 1 + 1, "the plan, one row per step, the outcome, the evaluation"
    assert history[0]["schedule/steps"] == 2
    assert [history[k]["step/index"] for k in (1, 2)] == [0, 1]
    gain = fitted.values_["toy.gain"].value
    assert history[2]["found/toy/gain"] == pytest.approx(gain)
    assert history[2]["found/toy/gain/ci95_lo"] <= history[2]["found/toy/gain"] <= history[2]["found/toy/gain/ci95_hi"]
    # degrees on the way out, radians in the ledger (Zach, 2026-11-11: angles shown to him in degrees, never rad)
    offset_deg = math.degrees(fitted.values_["toy.offset"].value)
    assert history[1]["found/toy/offset_deg"] == pytest.approx(offset_deg)
    assert history[1]["found/toy/offset_deg/ci95_lo"] <= history[1]["found/toy/offset_deg"] <= history[1]["found/toy/offset_deg/ci95_hi"]
    assert not [key for row in history for key in row if key.startswith("found/toy/offset") and "_deg" not in key], "never radians"
    assert history[3]["calibration/passed"] == 1
    assert history[3]["recovery/toy/gain/pass"] == 1 and history[3]["recovery/toy/offset_deg/pass"] == 1
    assert history[4]["eval/passed"] == int(report.passed)
    for g in report.gates:
        assert history[4][f"gate/{g.id}/passed"] == int(g.passed), g.id
        if isinstance(g.value, (int, float)) and math.isfinite(g.value):
            assert history[4][f"gate/{g.id}/value"] == pytest.approx(float(g.value)), g.id
    moved = tmp_path / "moved" / ledger.folder.name
    shutil.copytree(ledger.folder, moved)
    assert copy.records(moved)[0]["history"] == history, "rebuilt from the files alone, wherever they are"
    assert [row["routine"] for row in run["tables"]["steps"]] == list(fitted.plan_.ids)
    other = cal.Ledger(tmp_path)
    twin.calibrate(on="sim", callbacks=[other])
    assert other.folder != ledger.folder and copy.records(other.folder)[0]["id"] != run["id"], "each calibration is its own run"




def test_the_copy_logs_to_the_deployments_or_rigs_registered_project_and_a_bare_twin_to_none():
    copy = _copy()
    from sim2real import paths  # noqa: PLC0415

    registry = json.loads((REPO / "app" / "registry.json").read_text(encoding="utf-8"))
    unit = json.loads((REPO / "sysid" / "examples" / "pendulum_can11" / "description.json").read_text(encoding="utf-8"))["record"]
    deployment = next(d for d in registry["deployments"] if Path(d["record"]).name == Path(unit["path"]).name)
    assert copy.project_for("pendulum_can11") == deployment["wandb"]["project"], "CAN 11 is the One Dof Test Rack's: its project"
    wrist = copy.project_for("ur_wrist_test_rig")
    assert wrist and "wrist" in wrist.lower() and wrist != "Sim2Real", f"the wrist rig has its own registered project, got {wrist!r}"
    assert copy.project_for("toy") is None, "a twin with no deployment or rig project logs nothing to W&B unless a project is given"
    trackers = paths.BAM_WS / "tools" / "wandb_trackers" / "trackers"
    if not trackers.is_dir():
        pytest.skip(f"no bam_ws trackers registry at {trackers}")
    registered = "\n".join(p.read_text(encoding="utf-8") for p in sorted(trackers.glob("*.py")))
    for project in (copy.project_for("pendulum_can11"), wrist):
        assert f'project="{project}"' in registered, f"register {project!r} in bam_ws tools/wandb_trackers/trackers/ before its first run"


def test_a_reused_ledger_never_writes_one_calibrations_events_into_anothers_folder(toy, tmp_path):
    cal = _cal()
    twin, _ = toy
    ledger = cal.Ledger(tmp_path)
    first = twin.calibrate(on="sim", callbacks=[ledger])
    first_folder = ledger.folder
    second = twin.calibrate(on="sim", callbacks=[ledger])
    second_folder = ledger.folder
    assert first_folder != second_folder
    first.evaluate()
    assert kinds(first_folder)[-1] == "evaluate" and (first_folder / "eval.json").is_file()
    assert "evaluate" not in kinds(second_folder) and not (second_folder / "eval.json").exists()
    second.evaluate()
    assert kinds(second_folder)[-1] == "evaluate"


def test_a_fitted_twin_built_without_callbacks_still_evaluates(toy, tmp_path, monkeypatch):
    """Twins built outside RobotTwin.calibrate (real.calibrate's RobotTwin.__new__, before gap E) carry no callbacks_."""
    twin, _ = toy
    monkeypatch.setenv("SIM2REAL_CALIBRATIONS", str(tmp_path / "ledgers"))
    fitted = twin.calibrate(on="sim")
    del fitted.callbacks_
    assert fitted.evaluate().gates
    assert not (tmp_path / "ledgers").exists()


# --- the W&B copy, live and followed, against a stand-in wandb module ------------------------------------------------------------------------


class _Table:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs


class _Run:
    def __init__(self, module):
        self.module, self.summary, self.config = module, {}, {}

    def log(self, row, *args, **kwargs):
        self.module.logged.append(dict(row))

    def finish(self, *args, **kwargs):
        self.module.finished += 1


class FakeWandb(types.ModuleType):
    """Records what the copy logs. WHY a stand-in: the fast tier never starts wandb-core beside the powered arm."""

    def __init__(self, fail: bool = False):
        super().__init__("wandb")
        self.inits, self.logged, self.finished, self.fail = [], [], 0, fail
        self.Table, self.Settings = _Table, (lambda **kwargs: SimpleNamespace(**kwargs))
        self.run = None

    def init(self, **kwargs):
        self.inits.append(kwargs)
        if self.fail:
            raise RuntimeError("wandb is down")
        self.run = _Run(self)
        return self.run

    def log(self, row, *args, **kwargs):
        self.logged.append(dict(row))

    def finish(self, *args, **kwargs):
        self.finished += 1


def _history(module) -> list[dict]:
    return [row for row in module.logged if not any(isinstance(v, _Table) for v in row.values())]


def test_the_live_copy_logs_exactly_the_rows_the_replay_rebuilds(toy, tmp_path, monkeypatch):
    cal, copy = _cal(), _copy()
    twin, _ = toy
    fake = FakeWandb()
    monkeypatch.setitem(sys.modules, "wandb", fake)
    ledger = cal.Ledger(tmp_path)
    fitted = twin.calibrate(on="sim", callbacks=[ledger, copy.WandbLogger(ledger, project="Sim2Real")])
    fitted.evaluate()
    (record,) = copy.records(ledger.folder)
    assert _history(fake) == record["history"], "the live copy and the replay share one row() function"
    assert {i["id"] for i in fake.inits} == {record["id"]} and all(i["project"] == "Sim2Real" for i in fake.inits)
    assert all(i["job_type"] == "calibrate" for i in fake.inits)
    assert "callback_error" not in kinds(ledger.folder)


def test_a_wandb_that_will_not_start_costs_one_warning_and_no_retries(toy, tmp_path, monkeypatch):
    cal, copy = _cal(), _copy()
    twin, _ = toy
    fake = FakeWandb(fail=True)
    monkeypatch.setitem(sys.modules, "wandb", fake)
    ledger = cal.Ledger(tmp_path)
    with pytest.warns(RuntimeWarning, match="WandbLogger"):
        fitted = twin.calibrate(on="sim", callbacks=[ledger, copy.WandbLogger(ledger, project="Sim2Real")])
    fitted.evaluate()
    assert len(fake.inits) == 1, "tried once, then quiet"
    errors = [e for e in events(ledger.folder) if e["kind"] == "callback_error"]
    assert len(errors) == 1 and errors[0]["callback"] == "WandbLogger", errors
    assert [k for k in kinds(ledger.folder) if k != "callback_error"] == ["schedule", "step", "step", "done", "evaluate"]


def test_a_follower_process_copies_a_ledger_with_the_same_rows(toy, tmp_path, monkeypatch):
    """WHY a follower: on the powered rig's host the calibration keeps wandb-core out of its own process; a low-priority follower tails
    events.jsonl (calibrate_wandb --follow FOLDER) and logs each row as it appears."""
    cal, copy = _cal(), _copy()
    twin, _ = toy
    ledger = cal.Ledger(tmp_path)
    twin.calibrate(on="sim", callbacks=[ledger]).evaluate()
    fake = FakeWandb()
    monkeypatch.setitem(sys.modules, "wandb", fake)
    copy.follow(ledger.folder, project="Sim2Real", idle_s=0.0, poll_s=0.0)
    assert _history(fake) == copy.records(ledger.folder)[0]["history"]


# --- the tracer hands each step over as it finishes ---------------------------------------------------------------------------------------


class _Stop(Exception):
    pass


def test_the_tracer_hands_each_step_over_before_the_next_fit_runs(monkeypatch):
    _need_rack()
    import sim2real  # noqa: PLC0415

    twin = sim2real.examples.pendulum_can11(workers=2)

    class World:
        truth, noise, seed = {}, {}, 0

        def __init__(self, d, *, workers):
            pass

        def measure(self, plan):
            return SimpleNamespace(train={}, held_out={}, repeat={})

    class Module:
        RealWorld = World

        @staticmethod
        def plan(d):
            return object()

    delivered: list[dict] = []

    class First:
        id, kind, identifies = "servo.backlash_reversals_camera", "identify", ()

        def runs(self, values):
            return ()

        def fit(self, measured, values, twin):
            return {}

    class Second:
        id, kind, identifies = "servo.dynamics_regression", "identify", ()

        def runs(self, values):
            return ()

        def fit(self, measured, values, twin):
            assert [s["routine"] for s in delivered] == [First.id], f"step 1 must be handed over before step 2's fit: {delivered}"
            raise _Stop

    monkeypatch.setattr(twin.runner, "pipeline", lambda: Module)
    monkeypatch.setattr(twin.runner, "sysid_description", lambda: object())
    with pytest.raises(_Stop):
        twin.runner.calibrate(routines=[First(), Second()], on_step=delivered.append)


# --- the rack: on disk before it plays, live steps, "pending" (its pipeline, emit and ingest stubbed) -----------------------------------------

from sim2real import real  # noqa: E402
from sim2real import twin as twin_module  # noqa: E402

WORKERS = 2
FOUND_GAP = 0.0123
FOUND_CI = (0.0117, 0.0129)
STUB_GAP_METHOD = "the stub gear_gap's method (the gap step's own)"


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



def _pendulum():
    _need_rack()
    import sim2real  # noqa: PLC0415

    return sim2real.examples.pendulum_can11(workers=WORKERS)


def test_on_real_the_schedule_is_on_disk_before_the_rack_plays_and_each_step_lands_live(tmp_path, monkeypatch):
    cal = _cal()
    from sim2real.calibration import plan as schedule_of  # noqa: PLC0415

    monkeypatch.delenv("SIM2REAL_TRACK", raising=False)
    twin = _pendulum()
    bench = _bench(monkeypatch, twin, schedule_of(twin))
    ledger = cal.Ledger(tmp_path / "ledgers")
    at_play = []
    played = bench.transport.play

    def watched(submission):
        at_play.append(kinds(ledger.folder))
        return played(submission)

    monkeypatch.setattr(bench.transport, "play", watched)
    fitted = twin.calibrate(on="real", transport=bench.transport, callbacks=[ledger])
    assert at_play == [["schedule"]], "the schedule is on disk before the rack moves"
    lines = events(ledger.folder)
    assert lines[0]["backend"] == "real"
    logged = [e for e in lines if e["kind"] == "step"]
    assert [e["routine"] for e in logged] == list(fitted.plan_.ids) and all(e["live"] is True for e in logged)
    assert lines[-1]["kind"] == "done"


def test_runs_the_rack_has_not_played_yet_end_the_ledger_pending_not_error(tmp_path, monkeypatch):
    cal = _cal()
    from sim2real.calibration import plan as schedule_of  # noqa: PLC0415

    twin = _pendulum()
    bench = _bench(monkeypatch, twin, schedule_of(twin))
    try:
        pending = real.RunsPending("the rack has not played the submission yet")
    except TypeError:
        pending = real.RunsPending.__new__(real.RunsPending)

    def not_yet(submission):
        raise pending

    monkeypatch.setattr(bench.transport, "play", not_yet)
    ledger = cal.Ledger(tmp_path)
    with pytest.raises(real.RunsPending):
        twin.calibrate(on="real", transport=bench.transport, callbacks=[ledger])
    assert kinds(ledger.folder) == ["schedule", "pending"], kinds(ledger.folder)
    assert events(ledger.folder)[-1].get("submission"), "the pending event names the submission folder the rack will play"


def test_a_rack_calibration_keeps_a_ledger_beside_its_submission_by_default(tmp_path, monkeypatch):
    from sim2real.calibration import plan as schedule_of  # noqa: PLC0415

    monkeypatch.delenv("SIM2REAL_TRACK", raising=False)
    twin = _pendulum()
    bench = _bench(monkeypatch, twin, schedule_of(twin))
    emitted = real.emit

    def emit_here(*args, **kwargs):
        submission = emitted(*args, **kwargs)
        submission.folder = tmp_path / "submission"
        return submission

    monkeypatch.setattr(real, "emit", emit_here)
    twin.calibrate(on="real", transport=bench.transport)
    (folder,) = list((tmp_path / "submission" / "calibrate").iterdir())
    assert kinds(folder)[0] == "schedule" and kinds(folder)[-1] == "done"
    monkeypatch.setenv("SIM2REAL_TRACK", "off")
    twin.calibrate(on="real", transport=bench.transport)
    assert len(list((tmp_path / "submission" / "calibrate").iterdir())) == 1, "SIM2REAL_TRACK=off writes no ledger"


# --- slow (SIM2REAL_SLOW=1, cloud VM) ------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(not SLOW, reason="the CAN 11 pendulum's whole schedule runs minutes: SIM2REAL_SLOW=1")
def test_the_pendulum_logs_its_schedule_and_plays_the_shared_train_run_once(tmp_path):
    _need_rack()
    import sim2real  # noqa: PLC0415

    cal = _cal()
    twin = sim2real.examples.pendulum_can11(workers=2)  # the powered rig's cap
    ledger = cal.Ledger(tmp_path)
    fitted = twin.calibrate(on="sim", callbacks=[ledger])
    logged = steps(ledger.folder)
    record = roundtrip(fitted.record_.to_dict())
    assert [s["routine"] for s in logged] == list(fitted.plan_.ids) == [r["routine"] for r in record["routines"]]
    assert kinds(ledger.folder)[:2] == ["schedule", "collect"], "the tracer's world measures every run up front: said once, as it is"
    assert all(s["runs"] == ["train"] for s in logged if s["runs"]), "the pendulum's fits read the train run"
    for step, row in zip(logged, record["routines"]):
        assert {k: f["value"] for k, f in step["found"].items()} == row["found"]
    assert kinds(ledger.folder)[-1] == "done" and events(ledger.folder)[-1]["passed"] is fitted.calibration_.passed


@pytest.mark.skipif(not SLOW, reason="the whole CAN 11 schedule on the twin transport takes tens of minutes: SIM2REAL_SLOW=1")
def test_on_real_logs_its_steps_and_outcome_to_the_same_ledger(tmp_path):
    _need_rack()
    pytest.importorskip("mujoco", reason="the twin transport replays the rack twin")
    import sim2real  # noqa: PLC0415
    from sim2real import real  # noqa: PLC0415

    cal = _cal()
    twin = sim2real.examples.pendulum_can11(workers=2)
    ledger = cal.Ledger(tmp_path / "ledgers")
    fitted = twin.calibrate(on="real", transport=real.TwinTransport(root=tmp_path / "rack", workers=2), callbacks=[ledger])
    lines = events(ledger.folder)
    record = roundtrip(fitted.record_.to_dict())
    assert lines[0]["kind"] == "schedule" and lines[0]["backend"] == "real"
    assert all(e["live"] is True for e in lines if e["kind"] == "step"), "the rack's steps land as each fit finishes"
    assert [e["routine"] for e in lines if e["kind"] == "step"] == [r["routine"] for r in record["routines"]]
    assert lines[-1]["kind"] == "done" and lines[-1]["passed"] is record["passed"]
    assert json.loads((ledger.folder / "calibration.json").read_text(encoding="utf-8")) == record


@pytest.mark.skipif(not SLOW, reason="starts W&B's service process (wandb-core): SIM2REAL_SLOW=1")
def test_the_live_copy_writes_a_wandb_run_offline_under_the_replays_id(toy, tmp_path, monkeypatch):
    pytest.importorskip("wandb", reason="sim2real's tracking extra")
    cal, copy = _cal(), _copy()
    twin, _ = toy
    monkeypatch.setenv("WANDB_MODE", "offline")  # no network: the run lands on disk, `wandb sync` would upload it
    ledger = cal.Ledger(tmp_path / "ledgers")
    twin.calibrate(on="sim", callbacks=[ledger, copy.WandbLogger(ledger, project="Sim2Real", wandb_dir=tmp_path / "wandb")])
    run_id = copy.records(ledger.folder)[0]["id"]
    assert list((tmp_path / "wandb").rglob(f"offline-run-*-{run_id}")), "the live run carries the id the replay would use"
    assert "callback_error" not in kinds(ledger.folder)
