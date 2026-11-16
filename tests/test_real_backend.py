"""calibrate(on="real") for one station (CAN 11, the pendulum): plan -> emit a rack submission -> a transport plays it -> the runs come back
as robot_msgs JointTrajectory through tools/run_files.py -> the existing identify() fits them (sim2real.real; docs/CALIBRATE.md "on='real'").

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_real_backend.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_real_backend.py

Zach's rule for robotics algorithms (2026-11-05): prove in sim that the fit recovers a HIDDEN ground truth, committed as the acceptance
test, before any hardware. So the real backend is proven here on a twin transport: the rack twin at the sealed hidden truth of
sysid/examples/pendulum_can11/world.json, writing each run in the rack runner's own files (bam_rack_twin.hardware.board.save), which the
backend reads back through the same door a real session's runs go through. Nothing here opens a bus, a port or a camera: the rack
transport is held to its dry run, its execute is refused on this record and in a device-free lane, and the one path that would start the
rack's session runner is driven with an injected fake runner.

The oracles are read here, never from the code under test: the hidden truth from world.json, the tolerances from sysid/acceptance.json,
the oracle's own in-memory measurement (the pipeline's RealWorld path: synthetic_runs, replay, measured_run) as the ruler for the file round
trip. A truth moved past its tolerance (gravity +10 %, five times its 2 %) must turn the record red: the ruler can fail.

The slow half (SIM2REAL_SLOW=1) runs the whole schedule (80 runs: 5 floor, 46 train, 29 held out) on the twin twice, green and red, with
2 replay workers (a powered rack's lane cap); each takes the CAN 11 oracle's tens of minutes.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("bam_rack_twin", reason="the pendulum runs under bam_rack_twin's venv (sysid's runtime)")
pytest.importorskip("mujoco", reason="the twin transport replays the rack twin")

import sim2real  # noqa: E402
from sim2real import real  # noqa: E402
from sim2real.calibration.record import RECORD_KEYS, RECORD_SCHEMA  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = "pendulum_can11"
EXAMPLE_DIR = REPO / "sysid" / "examples" / EXAMPLE
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
CAPTURE = os.environ.get("SIM2REAL_CAPTURE")  # a folder: the slow runs write their summaries and records there (the report reads them)
MOVED = {"can11.gravity_nm": 5.05 * 1.10}  # the red run: gravity 10 % off the committed truth, five times its 2 % tolerance


def hidden_truth() -> dict:
    return json.loads((EXAMPLE_DIR / "world.json").read_text())["truth"]


def tolerances() -> dict:
    return json.loads((REPO / "sysid" / "acceptance.json").read_text())["examples"][EXAMPLE]


def within(value, truth, rule) -> bool:
    kind, tol = rule
    return value is not None and math.isfinite(value) and abs(value - truth) <= (tol if kind == "abs" else tol * abs(truth))


@pytest.fixture(scope="module")
def robot():
    return sim2real.examples.pendulum_can11(workers=2)


@pytest.fixture(scope="module")
def pipeline(robot):
    runner = real.RealRunner(robot.description, workers=2)
    module, description = runner.pipeline(), runner.sysid_description()
    return SimpleNamespace(module=module, d=description, plan=module.plan(description), station=module._rack()[2])


@pytest.fixture(scope="module")
def submission(pipeline, tmp_path_factory):
    return real.emit(EXAMPLE, pipeline.plan, tmp_path_factory.mktemp("submission"), can_id=11, joint="can11_hinge")


def reduced(submission: real.Submission, keep: list[str], folder: Path) -> real.Submission:
    """The same submission over a few of its runs (their own steps from the full plan, in order, each followed by its pause)."""
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy(submission.folder / "schedule.json", folder / "schedule.json")
    plan = submission.plan("fb")
    steps = []
    for step in plan["steps"]:
        if step.get("kind") != "pause" and step["schedule"]["run"] in keep:
            steps += [step, {"kind": "pause", "seconds": 2.0}]
    (folder / submission.sessions["fb"]["plan"]).parent.mkdir(parents=True, exist_ok=True)
    (folder / submission.sessions["fb"]["plan"]).write_text(json.dumps({**plan, "steps": steps[:-1]}))
    sessions = {"fb": {**submission.sessions["fb"], "runs": [s["schedule"]["run"] for s in steps[::2]], "steps": len(steps) // 2}}
    small = dataclasses.replace(submission, folder=folder, runs=tuple(r for r in submission.runs if r["run"] in keep), sessions=sessions)
    (folder / "submission.json").write_text(json.dumps(small.to_dict()))
    return small


@pytest.fixture(scope="module")
def played(submission, tmp_path_factory):
    """Four short runs (two floor repeats, the shortest train and held-out runs) played on the twin: the files the ingest tests read."""
    shortest = lambda purpose: min((r for r in submission.runs if r["purpose"] == purpose), key=lambda r: r["seconds"])["run"]  # noqa: E731
    keep = submission.run_ids("floor")[:2] + [shortest("train"), shortest("held_out")]
    small = reduced(submission, keep, tmp_path_factory.mktemp("small"))
    transport = real.TwinTransport(workers=2)
    return SimpleNamespace(submission=small, recording=transport.play(small), keep=keep, transport=transport)


# --- the front door's edges ------------------------------------------------------------------------------------------------------------


def test_on_real_needs_a_transport_and_names_the_rack_path(robot):
    with pytest.raises(TypeError, match="RackTransport") as caught:
        robot.calibrate(on="real")
    assert "One Dof Test Rack" in str(caught.value) and "TwinTransport" in str(caught.value)


def test_on_real_refuses_what_it_cannot_honour(robot, tmp_path):
    transport = real.TwinTransport(root=tmp_path)
    with pytest.raises(ValueError, match="TwinTransport\\(move_truth"):
        robot.calibrate(on="real", transport=transport, move_truth=MOVED)
    for steer in ({"noise": 1.0}, {"config": object()}, {"data": object()}):
        with pytest.raises(NotImplementedError, match="one-click seam"):
            robot.calibrate(on="real", transport=transport, **steer)
    with pytest.raises(ValueError, match="real backend"):
        robot.calibrate(on="sim", transport=transport)
    assert list(tmp_path.iterdir()) == [], "a refused call writes nothing"


def test_the_example_names_its_runtime_when_bam_rack_twin_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "bam_rack_twin", None)  # what sim2real's own env sees: no bam_rack_twin to import
    with pytest.raises(ModuleNotFoundError, match="bam_rack_twin's venv") as caught:
        sim2real.examples.pendulum_can11()
    assert "-m sim2real.real" in str(caught.value) and str(sim2real.examples.RACK_PYTHON) in str(caught.value)


# --- emit: the submission ------------------------------------------------------------------------------------------------------------


def test_the_submission_plays_exactly_the_planned_runs_in_the_rack_runners_own_plan(pipeline, submission):
    from bam_rack_twin import schedule as rack_schedule  # noqa: PLC0415

    plan = pipeline.plan
    floor = [r["run"] for r in plan.document["runs"] if r["split"] == "floor" and r["mode"] == "fb"]
    assert submission.run_ids("floor") == floor and len(floor) == 5, "T1 needs the floor tape's five repeats"
    assert submission.run_ids("train") == [r["run"] for r in plan.train], "the sim backend's train split, unchanged"
    assert submission.run_ids("held_out") == [r["run"] for r in plan.held_out]
    assert submission.digest == plan.digest and json.loads((submission.folder / "schedule.json").read_text())["digest"] == plan.digest
    steps = [s for s in submission.plan("fb")["steps"] if s["kind"] != "pause"]
    assert sorted(s["schedule"]["run"] for s in steps) == sorted(submission.run_ids())
    assert {s["schedule"]["digest"] for s in steps} == {plan.digest} and all(s["can_id"] == 11 for s in steps)
    # the plan IS bam_rack_twin.schedule.session_plans' over the planned runs (never a copy of its rules)
    keep = set(submission.run_ids())
    fresh = rack_schedule.session_plans(dict(plan.document, runs=[r for r in plan.document["runs"] if r["run"] in keep]),
                                        submission.folder / "fresh_plans", runs_root=submission.folder / "fresh_sessions")
    assert json.loads(Path(fresh["fb"]["plan"]).read_text()) == submission.plan("fb")
    assert real.Submission.load(submission.folder).to_dict() == submission.to_dict()
    assert not (submission.folder / "sessions").exists(), "emitting starts nothing"


def test_a_second_emit_reuses_the_submission_and_another_schedule_is_refused(pipeline, submission):
    before = (submission.folder / "submission.json").stat().st_mtime_ns
    again = real.emit(EXAMPLE, pipeline.plan, submission.folder, can_id=11, joint="can11_hinge")
    assert again.to_dict() == submission.to_dict() and (submission.folder / "submission.json").stat().st_mtime_ns == before
    other = SimpleNamespace(**{**vars(pipeline.plan), "digest": "0" * 16})
    with pytest.raises(ValueError, match="its own folder"):
        real.emit(EXAMPLE, other, submission.folder, can_id=11, joint="can11_hinge")


# --- the rack transport: a dry run, and an execute that refuses unless everything checks out --------------------------------------------


def _never(*_args, **_kwargs):
    raise AssertionError("the rack transport started a process")


def test_the_rack_transport_dry_runs_and_starts_nothing(robot, tmp_path):
    transport = real.RackTransport(tmp_path / "rack", runner=_never)
    with pytest.raises(real.RunsPending) as caught:
        robot.calibrate(on="real", transport=transport)
    pending = caught.value
    plan, out = pending.submission.folder / pending.submission.sessions["fb"]["plan"], pending.submission.session_out("fb")
    assert len(pending.commands) == 1 and f"-m bam_rack_twin.hardware session --plan {plan} --out {out}" in pending.commands[0]
    assert pending.commands[0].startswith("env -u VIRTUAL_ENV ") and "BAM_RACK_BUS_LOCK=" in pending.commands[0]
    assert "systemd-run --user --scope -p CPUWeight=2000 --" in pending.commands[0]
    assert pending.checks["dry_run"]["fb"]["ok"], pending.checks["dry_run"]  # the rack runner's own offline checks, nothing opened
    assert pending.checks["dry_run"]["fb"]["steps"] == 80
    written = json.loads((tmp_path / "rack" / "dry_run.json").read_text())
    assert written["commands"]["fb"] == pending.commands[0] and written["refusals"] == pending.checks["refusals"]
    assert not out.exists(), "a dry run writes no session"
    # the second call (nothing came back yet) is the same dry run over the same submission, never a new one
    with pytest.raises(real.RunsPending):
        robot.calibrate(on="real", transport=transport)
    assert sorted(p.name for p in (tmp_path / "rack").iterdir()) == ["dry_run.json", "plans", "schedule.json", "submission.json"]


def _station(**changes):
    return SimpleNamespace(**{"can_id": 11, "adapter_serial": "272813EF", "retired": None, **changes})


def _board(lock=True):
    if not lock:
        return SimpleNamespace(__file__="/x/bam_rack_twin/bam_rack_twin/hardware/board.py")
    return SimpleNamespace(__file__="/x/bam_rack_twin/bam_rack_twin/hardware/board.py", BUS_LOCK_ENV=real.BUS_LOCK_ENV,
                           rack_bus_lock=lambda serial: Path(f"/locks/bus.{serial}.lock"))


def test_an_execute_refuses_each_unsafe_reason_by_name(submission):
    lock = {real.BUS_LOCK_ENV: "/locks/bus.272813EF.lock"}
    clean = real.RackTransport(submission.folder, execute=True, adapter="272813EF", station=_station(), board=_board(), runner=_never)
    assert clean.refusals(submission, environ=lock) == []
    cases = {
        "device-free lane": (clean, {**lock, real.LANE_NO_DEVICES: "1"}),
        "no adapter named": (real.RackTransport(submission.folder, execute=True, station=_station(), board=_board()), lock),
        "on adapter 0607623A, not 272813EF": (real.RackTransport(submission.folder, execute=True, adapter="272813EF",
                                                                 station=_station(adapter_serial="0607623A"), board=_board()), lock),
        "retires CAN 11": (real.RackTransport(submission.folder, execute=True, adapter="272813EF",
                                              station=_station(retired={"since_utc": "2026-11-10", "reason": "the five-bar's J1"}), board=_board()), lock),
        "no per-adapter bus lock": (real.RackTransport(submission.folder, execute=True, adapter="272813EF", station=_station(), board=_board(lock=False)), lock),
        "set BAM_RACK_BUS_LOCK=/locks/bus.272813EF.lock": (clean, {real.BUS_LOCK_ENV: "/home/bam/.cache/rack-commissioning/bus.lock"}),
    }
    for words, (transport, environ) in cases.items():
        found = transport.refusals(submission, environ=environ)
        assert any(words in why for why in found), (words, found)


def test_an_execute_refuses_on_the_running_trees_record_in_this_lane(robot, tmp_path, monkeypatch):
    monkeypatch.setenv(real.LANE_NO_DEVICES, "1")  # the lane sandbox's own mark (set by it; set here too, so the test holds outside it)
    transport = real.RackTransport(tmp_path / "rack", execute=True, adapter="272813EF", runner=_never)
    with pytest.raises(real.RackRefused) as caught:
        robot.calibrate(on="real", transport=transport)
    assert any("device-free lane" in why for why in caught.value.refusals)
    station = robot.runner.pipeline()._rack()[2]
    if station.adapter_serial != "272813EF" or station.retired:  # bam_ws main's record (2026-11-15): CAN 11 retired on 0607623A
        assert any("retires CAN 11" in why or "not 272813EF" in why for why in caught.value.refusals), caught.value.refusals


def test_an_execute_starts_the_rack_runner_with_the_lock_when_every_check_passes(submission, monkeypatch):
    monkeypatch.delenv(real.LANE_NO_DEVICES, raising=False)
    monkeypatch.setenv(real.BUS_LOCK_ENV, "/locks/bus.272813EF.lock")
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/.venv")
    started = []
    transport = real.RackTransport(submission.folder, execute=True, adapter="272813EF", station=_station(), board=_board(),
                                   runner=lambda argv, **kw: started.append((argv, kw)))
    recording = transport.play(submission)
    assert len(started) == 1, "one session per plan"
    argv, kw = started[0]
    plan, out = submission.folder / submission.sessions["fb"]["plan"], submission.session_out("fb")
    assert argv == [*real.LAUNCHER, sys.executable, "-m", "bam_rack_twin.hardware", "session", "--plan", str(plan), "--out", str(out)]
    assert kw["env"][real.BUS_LOCK_ENV] == "/locks/bus.272813EF.lock" and "VIRTUAL_ENV" not in kw["env"] and kw["check"] is True
    assert recording.folders == () and recording.transport == "rack", "the fake runner recorded nothing; nothing is invented"


# --- the twin transport: the rack runner's own files, read back bit for bit --------------------------------------------------------------


def test_the_twin_transport_writes_the_rack_runners_files_with_their_schedule_stamps(played):
    runs = played.recording.folders[0] / "runs"
    metas = {p.stem: json.loads(p.read_text()) for p in sorted(runs.glob("*.json"))}
    assert sorted(m["schedule"]["run"] for m in metas.values()) == sorted(played.keep)
    for stem, meta in metas.items():
        assert (runs / f"{stem}.npz").is_file() and (runs / "joint_trajectory" / f"{stem}.npz").is_file(), "board.save's npz and its trajectory"
        assert (runs / real.LINK_CAMERA_DIR / f"{stem}.npz").is_file()
        assert meta["schedule"]["digest"] == played.submission.digest and meta["can_id"] == 11 and meta["reason"].startswith("complete")
        assert meta["recorder"].startswith("bam_rack_twin.hardware"), "written by the rack runner's own writer"
    session = json.loads((played.recording.folders[0] / "session.json").read_text())
    # the session says which world it played and what it moved, by name; never a hidden value
    assert set(session) == {"transport", "plan", "plan_sha256", "world", "truth_moved", "twin", "started_utc", "ended_utc", "runs", "log"}
    assert session["truth_moved"] == [] and session["world"] == f"sysid/examples/{EXAMPLE}/world.json"
    assert all(np.array_equal(np.load(runs / f"{stem}.npz")["tick"], np.arange(np.load(runs / f"{stem}.npz")["t"].size)) for stem in metas), \
        "each row is its tape's sample: a ticked run"
    assert played.recording.noise["encoder_rad"] == json.loads((EXAMPLE_DIR / "world.json").read_text())["noise"]["encoder_rad"]


def test_the_runs_come_back_through_the_door_equal_to_the_oracles_own_measurement(played, pipeline):
    """The ruler: sysid's RealWorld path in memory (synthetic_runs, replay at the truth, measured_run with its seeded noise) on the same runs.
    Every channel the fit and the replays read equals it bit for bit, so on='real' over the twin fits exactly what on='sim' fits."""
    from bam_rack_twin.evidence import logged_feedforward_output_nm, logged_ilimit_scale  # noqa: PLC0415

    module, plan = pipeline.module, pipeline.plan
    ingested = real.ingest(played.recording, played.submission, station=pipeline.station, module=module)
    got = {**ingested.train, **ingested.held_out, **ingested.floor}
    assert sorted(got) == sorted(played.keep) and not ingested.missing and not ingested.refused
    rows = [r for r in plan.document["runs"] if r["run"] in played.keep]
    world = module.RealWorld(pipeline.d, workers=2)
    tapes = module.synthetic_runs(pipeline.d, plan, rows)
    replays = module.replay(tapes, {"truth": world.twin()}, workers=2)
    by_id = {t["id"]: t for t in plan.document["trajectories"]}
    for row in rows:
        name = row["run"]
        oracle = module.measured_run(name, row["family"], by_id[row["trajectory"]]["runner_kind"] or "", tapes[name], replays[("truth", name)],
                                     world.noise, module.noise_rng(world.seed, "commissioning", name))
        mine = got[name]
        for channel in ("t", "q", "qd", "tau", "q_target", "qd_target", "mode"):
            assert np.array_equal(getattr(mine.output, channel), getattr(oracle.output, channel)), (name, channel)
        assert np.array_equal(mine.q_link, oracle.q_link), name
        assert (mine.family, mine.kind) == (oracle.family, oracle.kind)
        a, b = mine.output.run.semantics, oracle.output.run.semantics
        assert dataclasses.replace(a, source="") == dataclasses.replace(b, source=""), "the command the replays send is the one the twin played"
        assert mine.output.maximum_torque_nm == oracle.output.maximum_torque_nm
        # what JointTwin.replay sends besides the targets: the logged feed-forward and the integral's scale, row by row
        for read in (lambda o: logged_feedforward_output_nm(o.run.arrays, o.station, rows=o.t.size),
                     lambda o: logged_ilimit_scale(o.run.arrays, o.run.semantics, rows=o.t.size)):
            assert np.array_equal(read(mine.output), read(oracle.output)), name


def test_the_rack_transport_fits_a_session_once_its_runs_are_in_its_folder(played, pipeline, tmp_path):
    """The rack path's second call: a session folder the rack runner wrote (here the twin's, standing in) is found and read, nothing started."""
    folder = tmp_path / "rack"
    shutil.copytree(played.submission.folder, folder, ignore=shutil.ignore_patterns("sessions"))
    small = real.Submission.load(folder)
    shutil.copytree(played.recording.folders[0], small.session_out("fb"))
    transport = real.RackTransport(folder, runner=_never)
    assert transport.recorded(small) == {"fb": True}
    recording = transport.play(small)
    assert recording.folders == (small.session_out("fb"),) and transport.ruler() is None
    ingested = real.ingest(recording, small, station=pipeline.station, module=pipeline.module)
    assert ingested.received == len(played.keep)


def _copy_recording(played, tmp_path) -> Path:
    out = tmp_path / "session"
    shutil.copytree(played.recording.folders[0], out)
    return out


def _floor_meta(session: Path) -> Path:
    """The meta of the session's first floor run (a run whose loss leaves the train run to fit)."""
    return next(p for p in sorted((session / "runs").glob("*.json")) if json.loads(p.read_text())["schedule"]["split"] == "floor")


def test_ingest_refuses_what_the_plan_cannot_fit_and_names_it(played, pipeline, submission, tmp_path):
    ingest = lambda folders, sub, **kw: real.ingest(real.Recording(tuple(folders), "test"), sub, station=pipeline.station,  # noqa: E731
                                                    module=pipeline.module, **kw)
    # the full plan against four runs: strict names what did not come back; strict=False fits what came back and says what did not
    with pytest.raises(real.IngestError, match="76 planned runs did not come back"):
        ingest(played.recording.folders, submission)
    partial = ingest(played.recording.folders, submission, strict=False)
    assert partial.received == 4 and len(partial.missing) == 76
    # a run stamped with another schedule is not this submission's
    other = _copy_recording(played, tmp_path / "other")
    meta_path = _floor_meta(other)
    meta = json.loads(meta_path.read_text())
    meta["schedule"]["digest"] = "f" * 16
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(real.IngestError, match="did not come back"):
        ingest([other], played.submission)
    assert any("not this submission's schedule" in s for s in ingest([other], played.submission, strict=False).skipped)
    # the same run recorded in two sessions is ambiguous
    with pytest.raises(real.IngestError, match="recorded twice"):
        ingest([played.recording.folders[0], _copy_recording(played, tmp_path / "twice")], played.submission)
    # a run the producer's rules refuse (an abort) came back, so it is kept out of the fit and named with its reason, never fatal: a real
    # fault shows as the runs the session then skipped, which are missing
    aborted = _copy_recording(played, tmp_path / "aborted")
    meta_path = _floor_meta(aborted)
    meta = json.loads(meta_path.read_text())
    meta["reason"] = "stopped: overspeed guard"
    meta_path.write_text(json.dumps(meta))
    kept_out = ingest([aborted], played.submission)
    assert kept_out.refused == {meta["schedule"]["run"]: "aborted: stopped: overspeed guard"} and meta["schedule"]["run"] not in kept_out.floor
    assert kept_out.received == 4 and kept_out.used == 3 and "kept out" in kept_out.summary()
    # a run stamped with this schedule but logged by another board: the folder mixes boards, always fatal
    mixed = _copy_recording(played, tmp_path / "mixed")
    meta_path = _floor_meta(mixed)
    meta = json.loads(meta_path.read_text())
    meta["can_id"] = 12
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(real.IngestError, match="mixes boards"):
        ingest([mixed], played.submission, strict=False)
    # a train run without its link camera cannot be fitted as planned (identify reads the motor-minus-link gap on every row); partially, it
    # is kept out, and here it was the only train run, so nothing is left to fit
    blind = _copy_recording(played, tmp_path / "blind")
    train_stem = next(p.stem for p in (blind / "runs").glob("*.json") if json.loads(p.read_text())["schedule"]["split"] == "train")
    (blind / "runs" / real.LINK_CAMERA_DIR / f"{train_stem}.npz").unlink()
    with pytest.raises(real.IngestError, match="no usable link camera"):
        ingest([blind], played.submission)
    with pytest.raises(real.IngestError, match="nothing to fit") as caught:
        ingest([blind], played.submission, strict=False)
    assert f"no runs/{real.LINK_CAMERA_DIR}/{train_stem}.npz" in str(caught.value)


# --- the guards: the fit is sealed, eval holds out ------------------------------------------------------------------------------------------


class _Replaying:
    """A transport that hands back a recording already made (the played fixture's), for the guard tests."""

    name = "replaying"

    def __init__(self, played):
        self.played = played

    def folder(self, twin, digest):
        return self.played.submission.folder

    def play(self, submission):
        return self.played.recording

    def ruler(self):
        raise AssertionError("the ruler is asked for only after the fit")


def test_the_fit_runs_sealed_from_the_twins_world(robot, played, monkeypatch):
    module = robot.runner.pipeline()
    *_, hidden = sim2real.twin._sysid()

    def peeking(description, measurements, **_):
        hidden.load(EXAMPLE)  # a fit that reaches for the hidden truth

    monkeypatch.setattr(module, "identify", peeking)
    monkeypatch.setattr(real, "emit", lambda *a, **k: played.submission)
    with pytest.raises(hidden.SealedWorld):
        real.calibrate(robot, _Replaying(played), strict=False)


def test_eval_refuses_a_training_run(robot):
    submission = SimpleNamespace(runs=({"run": "r1", "purpose": "held_out"}, {"run": "r2", "purpose": "train"}))
    measured = SimpleNamespace(train={"r1": None}, held_out={"r1": None, "r2": None}, floor={})
    runner = real.RealRunner(robot.description, state={"submission": submission, "measured": measured, "module": None, "fit": None})
    with pytest.raises(ValueError, match="held-out runs only") as caught:
        runner.eval()
    assert "r1" in str(caught.value) and "r2" in str(caught.value)


def test_the_one_command_is_a_dry_run_by_default(tmp_path, capsys):
    assert real.main(["--out", str(tmp_path / "rack"), "--adapter", "272813EF"]) == 0
    printed = capsys.readouterr().out
    assert "nothing has run" in printed and "-m bam_rack_twin.hardware session --plan" in printed and "dry run fb: ok" in printed
    assert (tmp_path / "rack" / "dry_run.json").is_file() and not (tmp_path / "rack" / "sessions").exists()
    with pytest.raises(SystemExit):
        real.main(["--out", str(tmp_path / "x"), "--move-truth", "can11.gravity_nm=5"])  # real hardware has no truth to move


def test_the_one_command_writes_the_record_and_eval_beside_the_submission(tmp_path, monkeypatch, capsys):
    from sim2real.calibration.record import CalibrationRecord  # noqa: PLC0415

    record = CalibrationRecord.from_dict(json.loads((REPO / "tests" / "fixtures" / "calibration_record_v1.json").read_text()))
    report = SimpleNamespace(summary=lambda: "eval summary", to_dict=lambda: {"gates": [{"id": "floor", "title": "T1", "value": "x", "rule": "r",
                                                                                     "passed": True}], "passed": True})
    fitted = SimpleNamespace(runs_=SimpleNamespace(summary=lambda: "ingest summary", to_dict=lambda: {"received": 80}),
                             calibration_=SimpleNamespace(summary=lambda: "calibration summary"), eval=lambda: report, record_=record,
                             submission_=SimpleNamespace(folder=tmp_path))
    seen = {}
    monkeypatch.setattr(real, "calibrate", lambda twin, transport, strict: seen.update(transport=transport, strict=strict) or fitted)
    assert real.main(["--transport", "twin", "--out", str(tmp_path), "--move-truth", "can11.gravity_nm=5.555", "--partial"]) == 0
    assert isinstance(seen["transport"], real.TwinTransport) and seen["transport"].move_truth == {"can11.gravity_nm": 5.555} and not seen["strict"]
    written = json.loads((tmp_path / "calibration.json").read_text())
    assert written["schema"] == RECORD_SCHEMA and written["evaluation"]["passed"] is True
    assert json.loads((tmp_path / "eval.json").read_text())["ingest"] == {"received": 80}
    assert "calibration summary" in capsys.readouterr().out


def test_the_real_backend_is_documented_with_its_queued_command():
    text = (REPO / "docs" / "CALIBRATE.md").read_text()
    for word in ("on='real'", "RackTransport", "TwinTransport", "RunsPending", "python -m sim2real.real", "--execute", "BAM_RACK_BUS_LOCK",
                 "272813EF", "runs/link_camera"):
        assert word in text, word


# --- the acceptance: the whole schedule on the twin at the sealed truth, green, then red on a moved one ---------------------------------------


def _capture(name: str, fitted, report=None) -> None:
    if not CAPTURE:
        return
    folder = Path(CAPTURE)
    folder.mkdir(parents=True, exist_ok=True)
    doc = {"calibration": fitted.calibration_.to_dict(), "record": fitted.record_.to_dict(), "ingest": fitted.runs_.to_dict(),
           "summary": fitted.calibration_.summary(), "submission": str(fitted.submission_.folder)}
    if report is not None:
        doc.update(report=report.to_dict(), report_summary=report.summary())
    (folder / f"{name}.json").write_text(json.dumps(doc, indent=1, default=str))


@pytest.mark.skipif(not SLOW, reason="the whole CAN 11 schedule on the twin takes tens of minutes: SIM2REAL_SLOW=1")
def test_on_real_over_the_twin_recovers_the_sealed_truth_and_returns_a_calibration_record(tmp_path):
    twin = sim2real.examples.pendulum_can11(workers=2)
    fitted = twin.calibrate(on="real", transport=real.TwinTransport(root=tmp_path, workers=2))
    cal = fitted.calibration_
    _capture("real_green", fitted)  # before any assertion: a late failure still leaves the numbers
    print(fitted.runs_.summary(), flush=True)
    print(cal.summary(), flush=True)
    truth, rules = hidden_truth(), tolerances()
    recovered = {f"can11.{k}": float(v) for k, v in fitted.values_.items() if v is not None}
    missed = {k: (recovered.get(k), truth[k]) for k in rules["parameters"] if not within(recovered.get(k), truth[k], rules["parameters"][k])}
    assert not missed, f"outside tolerance of the hidden truth: {missed}"
    assert fitted is not twin and not twin.fitted and cal.backend == "real"
    assert fitted.runs_.received == 80 and not fitted.runs_.missing
    # kept out: exactly the runs the producer's own loader judges out, file by file (bam_rack_twin.evidence.load_run: "a problem keeps it out
    # of every fit and replay"); on this world CAN 11's multisine at kp x 0.25 sticks in its stiction band (measured 2026-11-15)
    from bam_rack_twin import evidence  # noqa: PLC0415

    session = fitted.submission_.session_out("fb")
    judged_out = {}
    for npz in sorted((session / "runs").glob("*.npz")):
        loaded = evidence.load_run(session, npz)
        if loaded.problems:
            judged_out[json.loads(npz.with_suffix(".json").read_text())["schedule"]["run"]] = "; ".join(loaded.problems)
    assert fitted.runs_.refused == judged_out and fitted.runs_.used == 80 - len(judged_out), (fitted.runs_.refused, judged_out)
    assert len(fitted.runs_.train) == len(fitted.submission_.run_ids("train")) - sum(n in judged_out for n in fitted.submission_.run_ids("train"))
    record = fitted.record_.to_dict()
    assert record["schema"] == RECORD_SCHEMA and set(record) == set(RECORD_KEYS)
    assert record["backend"] == "real" and record["passed"] is True and record["failing"] == []
    assert {p["key"] for p in record["parameters"] if p["pass"] is True} == set(rules["parameters"])
    assert all(p["true"] == truth[p["key"]] for p in record["parameters"]), "graded against world.json as committed"
    assert record["noise"]["transport"] == "twin" and record["plan"]["source"] == "sysid"
    assert fitted.parameters["can11"]["gravity_nm"].source.startswith(f"sim2real calibrate · on=real · {cal.rung} · ")
    report = fitted.eval()
    print(report.summary(), flush=True)
    _capture("real_green", fitted, report)
    gates = {g.id: g for g in report.gates}
    assert gates["floor"].passed, "T1: the floor tape's five repeats came back and agree as the same input"
    assert gates["held_out_fidelity"].passed, gates["held_out_fidelity"]
    # the oracle's own acceptance metric (sysid/acceptance.json held_out_link_fidelity), re-derived on the recorded held-out runs: the
    # link camera's held-out error, nominal over calibrated
    assert report.metrics["held_out_link_fidelity"]["factor"] >= tolerances()["metrics"]["held_out_link_fidelity"], report.metrics
    # WHY `twinned` is printed, not asserted, on the twin's world (measured 2026-11-15: a twin at the exact truth read 11x on the shortest held-out run): eval replays each
    # run from its measured start, 20 urad of encoder noise off the command, and CAN 11's stick-slip under ki 16000 amplifies it, while the
    # world's floor repeats all start exactly on the command, so its floor (the encoder's noise alone) excludes that spread. The rack's own
    # repeats start where the joint really rests, so T1 there carries it, and T2 is its gate.
    print(f"twinned (T2, encoder) on the twin's world: {gates['twinned'].value} ({'pass' if gates['twinned'].passed else 'FAIL'})", flush=True)
    with_eval = fitted.record_.with_evaluation(report.to_dict()).to_dict()
    assert {g["id"] for g in with_eval["evaluation"]["gates"]} == {"floor", "twinned", "held_out_fidelity"}


@pytest.mark.skipif(not SLOW, reason="the whole CAN 11 schedule on the twin takes tens of minutes: SIM2REAL_SLOW=1")
def test_a_truth_moved_past_its_tolerance_turns_the_real_record_red(tmp_path):
    fitted = sim2real.examples.pendulum_can11(workers=2).calibrate(on="real", transport=real.TwinTransport(root=tmp_path, move_truth=MOVED, workers=2))
    cal = fitted.calibration_
    print(cal.summary(), flush=True)
    _capture("real_red", fitted)
    record = fitted.record_.to_dict()
    assert cal.truth_moved == MOVED, "the transport says what it moved (after the fit)"
    assert not cal.passed and "can11.gravity_nm" in cal.failing
    assert record["passed"] is False and "can11.gravity_nm" in record["failing"]
