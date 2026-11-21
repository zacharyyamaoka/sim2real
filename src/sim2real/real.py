"""The real backend: ``RobotTwin.calibrate(on="real", transport=...)`` plays the type's test schedule on hardware through a transport, reads
the runs back as robot_msgs JointTrajectory and fits them through the same routines, in the same loop, the sim backend plays (plan(twin):
twin._play_routines; Zach, 2026-11-11: sim or real is an argument, ``on=``, not another verb). First station: CAN 11 on the One Dof Test
Rack, swung as a pendulum (sysid's pendulum_can11).

    import sim2real
    from sim2real.real import RackTransport, TwinTransport
    twin = sim2real.examples.pendulum_can11(workers=2)
    fitted = twin.calibrate(on="real", transport=TwinTransport())              # the rack twin at a SEALED hidden truth (the acceptance test)
    twin.calibrate(on="real", transport=RackTransport(out))                    # the rack: writes the submission, dry-runs it, raises RunsPending
    twin.calibrate(on="real", transport=RackTransport(out, execute=True, adapter="272813EF"))   # the rack owner only: the session runs it
    fitted.record_.to_dict()                                                    # sim2real.calibration/1, backend "real"
    fitted.eval().summary()                                                     # held-out runs replayed, over the rack's own floor (T1)
    python -m sim2real.real --adapter 272813EF --out DIR                       # the same as one command (dry run unless --execute)

The four steps, each a function here, so there is always a level to drop to:

1. plan     the sim backend's own plan (sysid/examples/<id>/pipeline.py plan(): CAN 11's schedule, every FB run of its train and held-out
            splits) plus the schedule's floor repeats, which the rack needs and the sim does not (T1: the rack against itself);
2. emit     a Submission folder: ``submission.json`` (sim2real.real.submission/1), ``schedule.json`` (the schedule every command tape is cut
            from) and the rack runner's own session plans (``bam_rack_twin.schedule.session_plans`` over exactly the planned runs, each step
            stamped with its schedule run). Nothing here moves anything;
3. play     ``transport.play(submission)`` -> a Recording: session folders holding the runs in the rack runner's own files (``runs/<name>.npz``
            + ``.json``, ``bam_rack_twin.hardware.board.save``, each stamped with its schedule run) and each run's link angle
            (``runs/link_camera/<name>.npz``, a robot_msgs JointTrajectory, the camera on tags 8-12); ``RunsPending`` when they are not back;
4. ingest   every run read at the one door, ``tools/run_files.py`` (a JointTrajectory), judged and put in the joint output frame by the
            producer's own rules (``bam_rack_twin.evidence``: judge, command_semantics, to_output_frame), then fitted by the schedule's
            routines (plan(twin): CAN 11's gap from load reversals, then the regression at that gap), each inside ``sysid.world.sealed()``.

WHY a transport and never hardware here (the dispatcher's brief, 2026-11-15; Zach's rule that robot time is earned): this module plans,
writes and reads; a transport is the only thing that plays. ``TwinTransport`` plays a submission on the rack twin at the hidden truth
(the oracle's own replay and measurement model, written out in the rack's own file format, so the fit sees exactly what a rack session
would hand it). ``RackTransport`` hands it to the rack's own session runner (``python -m bam_rack_twin.hardware session``: the bus lock,
every board's config and frame checked, each step's own limits and guards) and refuses to start one unless the station's record names
the adapter it is asked for, the record does not retire the station, and the tree has the rack's own bus lock (BAM_RACK_BUS_LOCK).

WHY the fit is the sim's, unchanged (Zach, 2026-11-05: prove in sim that the fit recovers a hidden ground truth before any hardware): the
schedule's routines are the ones proven on the sealed world, played by the sim's own loop (twin._play_routines, one executor, so the
guards cannot drift); the real backend changes only where its runs come from. A planned run the submission cannot fill is refused before
emit (robot time is earned).

WHY eval replays each recorded run's OWN commands (not the schedule's tapes, as the sim's score() does): a real run's rows are the board's
stamps, with its jitter and its preludes, so a twin is judged on what the board was actually sent. The floor is the rack's own (T1: the
median pairwise RMS of >= 5 identical repeats of the floor tape), the gates are read from the motor encoder (Zach, 2026-11-11: "the actual
tracking error should 100% come from the joint readings, the camera is just like a secondary measurement"), and the link camera's ratio
over its own floor is reported beside them as a flag, never a gate.

Decision record: docs/decision-real-backend-2026-11-15.md (the transport seam, the run-file contract, real eval on the motor encoder).

Layer: like twin.py and rig.py, right of every folder (tests/test_layers.py); bam_rack_twin and sysid are imported lazily, from the
interpreter running this (bam_rack_twin's venv: sysid's runtime) and this checkout.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import importlib.util
import inspect
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

import numpy as np
from robot_msgs.space import Basis, Value

from . import paths
from . import twin as twin_module
from ._json import _json_default
from .cards import registry as reg
from .cards import servo_gates as targets
from .metrics.gate import at_least, gate
from .metrics.series import SAME_INPUT_TOLERANCE_NM, SAME_INPUT_TOLERANCE_RAD, SAME_INPUT_TOLERANCE_RAD_S, repeat_floor, rms
from .twin import ORACLE_CARD, REPO, Calibration, Gate, Instance, PipelineHandle, SimRunner, TwinReport, _g, _identified, _sysid

SUBMISSION_SCHEMA = "sim2real.real.submission/1"
LINK_CAMERA_DIR = "link_camera"  # runs/link_camera/<name>.npz: the link angle a camera saw during the run (robot_msgs JointTrajectory)
PURPOSES = ("floor", "train", "held_out")
# WHY a lane default of 2 (bam_ws memory feedback-live-rig-cpu-cap, 2026-11-13): while the rack is powered every lane together runs at most
# 2 worker processes; the replays are deterministic per (twin, run), so the pool's size moves no number
WORKERS = 2
# WHY systemd-run with CPUWeight 2000 (bam_ws memory onedof-pendulum-campaign, 2026-11-15 12:49): host stalls under load dropped bus ticks
# (gaps up to 205 ms at load 26-35); the rack's sessions run in a user scope that outweighs every lane
LAUNCHER = ("systemd-run", "--user", "--scope", "-p", "CPUWeight=2000", "--")
LANE_NO_DEVICES = "BAM_LANE_NO_DEVICES"  # set by the device-free lane sandbox (bam_ws memory feedback-lanes-no-device-sandbox)
BUS_LOCK_ENV = "BAM_RACK_BUS_LOCK"  # bam_rack_twin.hardware.board.BUS_LOCK_ENV where the tree has the rack's own lock (bam_ws fb236bb5f)


class RunsPending(RuntimeError):
    """The submission is written and dry-run; nothing has come back to fit yet. ``commands`` plays it on the rack (one line each),
    ``checks`` is the dry run (``dry_run``) and why an execute would refuse (``refusals``)."""

    def __init__(self, submission: Submission, commands: Sequence[str], checks: Mapping[str, Any]):
        self.submission, self.commands, self.checks = submission, list(commands), dict(checks)
        refusals = self.checks.get("refusals") or []
        lines = [f"on='real': {submission.twin}'s submission is written ({len(submission.runs)} runs, about {submission.minutes:.0f} min of "
                 f"rack time) at {submission.folder}; nothing has run. The rack plays it with:"]
        lines += [f"  {command}" for command in self.commands]
        for key, result in (self.checks.get("dry_run") or {}).items():
            lines.append(f"  dry run {key}: " + ("ok, " + f"{result['steps']} steps, {result['estimate_s']:.0f} s" if result["ok"] else f"REFUSED: {result['refusal']}"))
        lines += [f"  an execute here would refuse: {why}" for why in refusals] or ["  an execute here would start (every check passed)"]
        lines.append("  then calibrate again (the same transport) to fit what came back")
        super().__init__("\n".join(lines))


class RackRefused(RuntimeError):
    """RackTransport(execute=True) refused before anything was started; ``refusals`` says why."""

    def __init__(self, refusals: Sequence[str]):
        self.refusals = list(refusals)
        super().__init__("the rack transport refused to start a session:\n" + "\n".join(f"  - {why}" for why in self.refusals))


class IngestError(ValueError):
    """The returned runs cannot be fitted as the plan asked: each problem named (a missing run, a refused one, a run without its link camera)."""


# --- 1. plan and 2. emit ----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Submission:
    """What the backend hands a transport: every planned run with its purpose, the schedule it is cut from, and the rack runner's session
    plans that play it. Paths inside are relative to ``folder``, so the folder moves as one."""

    folder: Path
    twin: str
    can_id: int
    joint: str
    digest: str
    frozen_digest: str
    runs: tuple[dict, ...]
    sessions: Mapping[str, dict]
    created_utc: str
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def minutes(self) -> float:
        return round(sum(float(s["minutes"]) for s in self.sessions.values()), 1)

    def run_ids(self, purpose: str | None = None) -> list[str]:
        return [r["run"] for r in self.runs if purpose is None or r["purpose"] == purpose]

    def document(self) -> dict:
        """The schedule (bam_rack_twin.schedule.build_schedule's document) every command tape of this submission is cut from."""
        return json.loads((self.folder / "schedule.json").read_text(encoding="utf-8"))

    def plan(self, key: str) -> dict:
        return json.loads((self.folder / self.sessions[key]["plan"]).read_text(encoding="utf-8"))

    def session_out(self, key: str) -> Path:
        return self.folder / self.sessions[key]["out"]

    def to_dict(self) -> dict:
        return {"schema": SUBMISSION_SCHEMA, "twin": self.twin, "can_id": self.can_id, "joint": self.joint,
                "schedule": {"digest": self.digest, "frozen_digest": self.frozen_digest, "path": "schedule.json"},
                "runs": [dict(r) for r in self.runs], "sessions": {k: dict(v) for k, v in self.sessions.items()}, "minutes": self.minutes,
                "created_utc": self.created_utc, "provenance": dict(self.provenance)}

    @classmethod
    def load(cls, folder: str | Path) -> Submission:
        folder = Path(folder)
        doc = json.loads((folder / "submission.json").read_text(encoding="utf-8"))
        if doc.get("schema") != SUBMISSION_SCHEMA:
            raise ValueError(f"{folder / 'submission.json'}: schema {doc.get('schema')!r}, this reader knows {SUBMISSION_SCHEMA!r}")
        return cls(folder, doc["twin"], int(doc["can_id"]), doc["joint"], doc["schedule"]["digest"], doc["schedule"]["frozen_digest"],
                   tuple(doc["runs"]), doc["sessions"], doc["created_utc"], doc.get("provenance", {}))


def planned_runs(plan) -> list[dict]:
    """The runs a real calibration plays: the schedule's floor repeats under FB (T1's input), then the plan's own train and held-out FB
    runs (the sim backend's split, unchanged). Each row is the schedule's, plus its ``purpose`` (its split) and its target's seconds."""
    by_id = {t["id"]: t for t in plan.document["trajectories"]}
    floor = [r for r in plan.document["runs"] if r["split"] == "floor" and r["mode"] == "fb"]
    rows = [{**r, "purpose": r["split"], "seconds": float(by_id[r["trajectory"]]["duration_s"])} for r in (*floor, *plan.train, *plan.held_out)]
    ids = [r["run"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError(f"the plan names a run twice: {sorted({i for i in ids if ids.count(i) > 1})}")
    if any(r["purpose"] not in PURPOSES for r in rows):
        raise ValueError(f"a planned run has no purpose in {PURPOSES}")
    return rows


def emit(twin_id: str, plan, folder: str | Path, *, can_id: int, joint: str) -> Submission:
    """Write the submission for ``plan`` into ``folder``: schedule.json, the rack runner's session plans (plans/), submission.json. WHY the
    rack's own plan writer (bam_rack_twin.schedule.session_plans) and never a copy: its steps are what the session runner checks and plays
    (each kind's own fields, the mode's scales, the floor bracketing the session), and each step carries its schedule stamp, which every run
    it writes then carries (the key the ingest reads back)."""
    from bam_rack_twin import schedule as rack_schedule  # noqa: PLC0415

    folder = Path(folder)
    if (folder / "submission.json").is_file():
        # WHY reused, never rewritten (the rack path's second call fits what the first one queued): the plans the sessions played stay the
        # bytes they played; a folder holding another schedule's submission is refused, so two schedules' runs are never mixed
        existing = Submission.load(folder)
        if existing.digest != plan.digest or existing.twin != twin_id:
            raise ValueError(f"{folder} holds {existing.twin}'s submission for schedule {existing.digest}, not {twin_id}'s {plan.digest}: "
                             "give this calibration its own folder")
        return existing
    folder.mkdir(parents=True, exist_ok=True)
    rows = planned_runs(plan)
    keep = {r["run"] for r in rows}
    document = plan.document
    (folder / "schedule.json").write_text(json.dumps(document, separators=(",", ":"), default=_json_default) + "\n", encoding="utf-8")
    entries = rack_schedule.session_plans(dict(document, runs=[r for r in document["runs"] if r["run"] in keep]), folder / "plans",
                                          runs_root=folder / "sessions")
    sessions = {}
    for key, entry in entries.items():
        steps = [s for s in json.loads(Path(entry["plan"]).read_text())["steps"] if s.get("kind") != "pause"]
        sessions[key] = {"mode": entry["mode"], "plan": str(Path(entry["plan"]).relative_to(folder)), "out": str(Path(entry["out"]).relative_to(folder)),
                         "steps": entry["steps"], "minutes": entry["minutes"], "runner_kind": bool(entry["runner_kind"]),
                         "runs": [s["schedule"]["run"] for s in steps]}
    in_plans = {run for s in sessions.values() for run in s["runs"]}
    if in_plans != keep:
        raise ValueError(f"the session plans do not play exactly the planned runs: missing {sorted(keep - in_plans)[:5]}, extra {sorted(in_plans - keep)[:5]}")
    submission = Submission(folder, twin_id, int(can_id), joint, plan.digest, plan.frozen_digest, tuple(rows), sessions, _now(),
                            {"sim2real": _git(REPO), "bam_rack_twin": _git(Path(rack_schedule.__file__).resolve().parent),
                             "bam_rack_twin_path": str(Path(rack_schedule.__file__).resolve().parents[1])})
    (folder / "submission.json").write_text(json.dumps(submission.to_dict(), indent=1) + "\n", encoding="utf-8")
    return submission


# --- 3. play: the transports -------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Recording:
    """What a transport hands back: the session folders its runs are in (each with runs/), the noise it says it played (the twin: its
    world's block; the rack: its own sensors, which the floor measures), and anything else it reports."""

    folders: tuple[Path, ...]
    transport: str
    noise: Mapping[str, Any] = field(default_factory=dict)
    meta: Mapping[str, Any] = field(default_factory=dict)


class Transport(Protocol):
    """The seam: whatever plays a Submission. ``folder(twin, digest)`` is where the backend writes it, ``play`` returns the Recording (or
    raises RunsPending), ``ruler()`` the hidden truth to grade against AFTER the fit (a simulator's; None on hardware)."""

    name: str

    def folder(self, twin: str, digest: str) -> Path: ...

    def play(self, submission: Submission) -> Recording: ...

    def ruler(self) -> Mapping[str, float] | None: ...


class TwinTransport:
    """Plays a submission on the rack twin at the hidden truth: sysid/examples/<twin>/world.json, read here and never by the fit (the backend
    fits inside sysid.world.sealed()). Every step of every session plan is played as the oracle plays a schedule run (the pipeline's
    synthetic_runs: the run's sampled target and its mode's scales, position mode), on the twin of record at the truth (the pipeline's
    replay), and measured by the oracle's own noise model and seeded streams (measured_run: encoder, speed, torque, link camera). Each run is
    written in the rack runner's own files (bam_rack_twin.hardware.board.save: its FIELDS, its meta, its JointTrajectory beside it) with
    its schedule stamp, and its link angle as runs/link_camera/<name>.npz. ``move_truth`` moves named hidden values for this transport (the
    ruler's mutation test: the world plays the moved values, ruler() stays world.json's)."""

    name = "twin"

    def __init__(self, *, root: str | Path | None = None, move_truth: Mapping[str, float] | None = None, workers: int = WORKERS):
        self.root = None if root is None else Path(root)
        self.move_truth = dict(move_truth or {})
        self.workers = int(workers)
        self._twin_id: str | None = None

    def folder(self, twin: str, digest: str) -> Path:
        # WHY a fresh folder per call: two calibrations with one transport never read each other's runs
        base = self.root or Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f"{twin}-{digest[:8]}-twin-", dir=base))

    def play(self, submission: Submission) -> Recording:
        from bam_rack_twin.evidence import MODE_STOPPED  # noqa: PLC0415
        from bam_rack_twin.hardware import board  # noqa: PLC0415
        from robot_msgs import save_npz  # noqa: PLC0415
        from robot_msgs.std import Header  # noqa: PLC0415
        from robot_msgs.trajectory import JointTrajectory  # noqa: PLC0415

        sysid_describe, oracle, _, _ = _sysid()
        module, d = oracle.example_module(submission.twin), sysid_describe.load(submission.twin)
        self._twin_id = submission.twin
        world = module.RealWorld(d, workers=self.workers)
        unknown = sorted(set(self.move_truth) - set(world.truth))
        if unknown:
            raise KeyError(f"no hidden value {unknown} in {submission.twin}'s world (it has {sorted(world.truth)})")
        world.truth = {**world.truth, **self.move_truth}
        truth_twin = world.twin()
        _, _, station = module._rack()
        document = submission.document()
        if document["digest"] != submission.digest:
            raise ValueError(f"schedule.json is {document['digest']}, the submission names {submission.digest}")
        rows = {r["run"]: r for r in document["runs"]}
        by_id = {t["id"]: t for t in document["trajectories"]}
        plan_view = SimpleNamespace(document=document)
        opb = float(document["description"]["output_per_board"])
        folders = []
        for key, entry in submission.sessions.items():
            if not entry["runner_kind"]:
                continue  # WHY: the rack runner refuses a plan of steps it has no kind for; the twin plays what the rack would
            plan = submission.plan(key)
            out = submission.session_out(key)
            (out / "runs" / LINK_CAMERA_DIR).mkdir(parents=True, exist_ok=True)
            started = time.time()
            wall = started
            played = []
            for index, step in enumerate(plan["steps"]):
                if step.get("kind") == "pause":
                    wall += float(step.get("seconds", 0.0))
                    continue
                stamp = dict(step["schedule"])
                run = rows[stamp["run"]]
                synthetic = module.synthetic_runs(d, plan_view, [run])[run["run"]]
                name = f"s{index + 1:02d}_can{submission.can_id}_{step['kind']}"
                meta = self._meta(step, stamp, synthetic, opb, index)
                command = decode(meta, _trajectory(self._columns(synthetic, opb, wall, None, mode_stopped=MODE_STOPPED), submission.can_id), station,
                                 judged=False)
                played.append((name, run, meta, command, wall))
                wall += float(command.t[-1]) + 1.0
            replays = module.replay({name: command for name, _, _, command, _ in played}, {"truth": truth_twin}, workers=self.workers)
            log = out / "twin_transport.log"
            with log.open("w", encoding="utf-8") as stream, contextlib.redirect_stdout(stream):
                for name, run, meta, command, wall0 in played:
                    rp = replays[("truth", name)]
                    kind = by_id[run["trajectory"]]["runner_kind"] or ""
                    # the oracle's measurement model and seeded stream (sysid RealWorld.measure's), so the noise is the sim backend's
                    data = module.measured_run(run["run"], run["family"], kind, command, rp, world.noise,
                                               module.noise_rng(world.seed, "commissioning", run["run"]))
                    columns = self._columns(data.output, opb, wall0, rp, mode_stopped=MODE_STOPPED)
                    blank = np.full(columns["t"].size, np.nan)  # a column the tree's board logs that the twin models nothing for
                    table = np.column_stack([columns.get(f, blank) for f in board.FIELDS])
                    # WHY ticked (board.save's TICK_FIELD): row k is the tape's sample k, as a ticked rack run logs it, so T1 compares the
                    # floor's repeats tick for tick; on a 2 ms common clock the interpolation would shrink a white-noise floor by ~18 %
                    if "ticked" in inspect.signature(board.save).parameters:
                        board.save(out / "runs", name, np.column_stack([table, np.arange(table.shape[0])]).tolist(), meta, ticked=True)
                    else:
                        board.save(out / "runs", name, table.tolist(), meta)
                    link = JointTrajectory(t=np.asarray(columns["t"], float), joint_names=(f"{submission.joint}_link",),
                                           positions=np.asarray(data.q_link, float).reshape(-1, 1),
                                           header=Header(stamp=float(wall0), frame_id="joint_output",
                                                         meta={"units": "rad (the link angle after the gear, output frame)", "can_id": str(submission.can_id),
                                                               "source": "twin transport: the twin's link (gear-gap hinge) + the world's link_camera noise"}))
                    save_npz(link, out / "runs" / LINK_CAMERA_DIR / f"{name}.npz")
            (out / "session.json").write_text(json.dumps({
                "transport": "sim2real.real.TwinTransport", "plan": entry["plan"], "plan_sha256": _sha256(submission.folder / entry["plan"]),
                "world": f"sysid/examples/{submission.twin}/world.json", "truth_moved": sorted(self.move_truth), "twin": truth_twin.version,
                "started_utc": _utc(started), "ended_utc": _now(), "runs": [name for name, *_ in played], "log": log.name}, indent=1) + "\n")
            folders.append(out)
        noise = {**world.noise, "level": 1.0, "seed": world.seed,
                 "sources": {n: f"sysid/examples/{submission.twin}/world.json noise block (the twin transport's world)" for n in world.noise}}
        return Recording(tuple(folders), self.name, noise, {"truth_moved": dict(self.move_truth)})

    def ruler(self) -> Mapping[str, float] | None:
        """world.json's truth as committed: the ruler (never the moved values). Read after the fit, never inside the seal."""
        if self._twin_id is None:
            return None
        *_, hidden = _sysid()
        return json.loads(hidden.path(self._twin_id).read_text(encoding="utf-8"))["truth"]

    @staticmethod
    def _meta(step: Mapping[str, Any], stamp: Mapping[str, str], synthetic, opb: float, index: int) -> dict:
        """The run meta the rack runner writes, for what the twin played. WHY kind "samples" whatever the step's kind: the twin played the
        run's sampled target in position mode (the oracle's tape: a velocity kind replays as the position it integrates to), so its runs say
        so, and the backend replays them exactly as they were played (bam_rack_twin.evidence.command_semantics reads the kind)."""
        semantics = synthetic.run.semantics
        args = {key: value for key, value in step.items() if key not in ("kind", "label", "schedule")}
        args.update(cap_nm=float(semantics.maximum_torque_board_nm), kp_scale=float(semantics.kp_scale), kd_scale=float(semantics.kd_scale),
                    ilimit_scale_cmd=float(semantics.ilimit_scale))
        return {"kind": "samples", "step_kind": step["kind"], "can_id": int(step["can_id"]), "q0_rad": float(synthetic.run.arrays["q"][0]),
                "reason": "complete (twin transport)", "args": args, "schedule": dict(stamp), "label": step.get("label", ""),
                "session_step": index + 1, "transport": "sim2real.real.TwinTransport"}

    @staticmethod
    def _columns(run, opb: float, wall0: float, replay, *, mode_stopped: int) -> dict[str, np.ndarray]:
        """A run as the board logs it (board frame, bam_rack_twin.hardware.board.FIELDS): its command (q_target, qd_target, the feed-forward
        it carried) and, once a twin answered it (``replay``), the measured channels; NaN where the twin models nothing (current, temperature)."""
        arrays = run.run.arrays
        t = np.asarray(run.t, float)
        rows = t.size
        nan = np.full(rows, np.nan)
        measured = replay is not None
        columns = {
            "t": t, "wall": wall0 + t, "q_target": np.asarray(arrays["q_target"], float), "qd_target": np.asarray(arrays["qd_target"], float),
            "q": np.asarray(run.q, float) / opb if measured else np.asarray(arrays["q"], float),
            "qd": np.asarray(run.qd, float) / opb if measured else np.zeros(rows),
            "tau": np.asarray(run.tau, float) * opb if measured else np.zeros(rows),
            "mode": np.asarray(run.mode, float) if measured else np.full(rows, float(mode_stopped)), "fault": np.zeros(rows),
            "voltage": np.full(rows, 24.0), "i_q": nan, "temp_c": nan, "i_d": nan, "power_w": nan, "rotor_rev": nan,
            "ff_cog_nm": np.asarray(arrays.get("ff_cog_nm", np.zeros(rows)), float), "ff_model_nm": nan,
            "ilimit_scale_cmd": np.asarray(arrays["ilimit_scale_cmd"], float) if "ilimit_scale_cmd" in arrays else nan,
            "q_control": nan, "qd_control": nan,
        }
        lengths = {name: value.size for name, value in columns.items()}
        if len(set(lengths.values())) != 1:
            raise ValueError(f"{run.run.name}: columns of different lengths {lengths}")
        return columns


class RackTransport:
    """Hands a submission to the One Dof Test Rack's own session runner. ``out`` is the submission's folder; its sessions/ is where the
    runner writes. Without ``execute`` (the default) it writes nothing but the submission and its dry run (``dry_run.json``) and raises
    RunsPending with the one-line command per session; once the sessions' runs are in ``out`` it returns them. With ``execute=True`` it
    starts each missing session itself: ``<python> -m bam_rack_twin.hardware session --plan P --out O`` (the interpreter running this, so
    the session is the same bam_rack_twin tree that planned it) under ``launcher``, with BAM_RACK_BUS_LOCK set to ``adapter``'s lock, and
    only when every refusal check passes (``refusals``). ``runner`` is what starts a process (subprocess.run); ``station`` and ``board``
    default to the running tree's (its record's station, bam_rack_twin.hardware.board). A test injects all three; nothing else should."""

    name = "rack"

    def __init__(self, out: str | Path, *, execute: bool = False, adapter: str | None = None, launcher: Sequence[str] = LAUNCHER,
                 python: str | None = None, runner: Callable[..., Any] = subprocess.run, station=None, board=None):
        self.out = Path(out)
        self.execute = bool(execute)
        self.adapter = adapter
        self.launcher = tuple(launcher)
        self.python = python or sys.executable
        self.runner = runner
        self._station, self._board = station, board

    def folder(self, twin: str, digest: str) -> Path:
        return self.out

    def ruler(self) -> Mapping[str, float] | None:
        return None  # real hardware has no hidden truth: eval() judges the twin on held-out runs

    def board(self):
        if self._board is None:
            from bam_rack_twin.hardware import board  # noqa: PLC0415

            self._board = board
        return self._board

    def station(self, submission: Submission):
        if self._station is None:
            _, oracle, _, _ = _sysid()
            self._station = oracle.example_module(submission.twin)._rack()[2]
        return self._station

    def lock_path(self) -> str | None:
        """The adapter's own bus lock as the tree names it (bam_rack_twin.hardware.board.rack_bus_lock), or None (no adapter, or a tree
        without per-adapter locks)."""
        maker = getattr(self.board(), "rack_bus_lock", None)
        return None if (maker is None or not self.adapter) else str(maker(self.adapter))

    def argv(self, submission: Submission, key: str) -> list[str]:
        """The session command for one plan, as a list (what ``execute`` starts)."""
        return [*self.launcher, self.python, "-m", "bam_rack_twin.hardware", "session", "--plan", str(submission.folder / submission.sessions[key]["plan"]),
                "--out", str(submission.session_out(key))]

    def command(self, submission: Submission, key: str) -> str:
        """The same as one line a person (or the rack owner's agent) pastes: env, the lock, the command."""
        lock = self.lock_path() or "<rack_bus_lock(adapter): a bam_rack_twin with per-adapter locks and --adapter>"
        return shlex.join(["env", "-u", "VIRTUAL_ENV", f"{BUS_LOCK_ENV}={lock}", *self.argv(submission, key)])

    def refusals(self, submission: Submission, *, environ: Mapping[str, str] | None = None) -> list[str]:
        """Every reason an execute would refuse, before anything starts ([] = it would start)."""
        environ = os.environ if environ is None else environ
        station, board_module = self.station(submission), self.board()
        out = []
        if environ.get(LANE_NO_DEVICES):
            out.append(f"{LANE_NO_DEVICES} is set: this process runs in a device-free lane, which never starts a rack session")
        if not self.adapter:
            out.append("no adapter named: pass adapter= (the fdcanusb serial the station's record puts it on, e.g. 272813EF for the One Dof Test Rack)")
        elif station.adapter_serial != self.adapter:
            out.append(f"the record ({_record_path(board_module)}) puts CAN {station.can_id} on adapter {station.adapter_serial}, not {self.adapter}")
        if station.retired:
            out.append(f"the record retires CAN {station.can_id} ({station.retired.get('since_utc', '?')}): {station.retired.get('reason', '')}")
        if not hasattr(board_module, "BUS_LOCK_ENV") or not hasattr(board_module, "rack_bus_lock"):
            out.append(f"this bam_rack_twin ({_tree(board_module)}) has no per-adapter bus lock ({BUS_LOCK_ENV}): its session would take the "
                       "shared bus.lock, which the full arm's arm-hold holds while powered (bam_ws fb236bb5f adds it)")
        elif self.adapter:
            want = str(board_module.rack_bus_lock(self.adapter))
            if environ.get(BUS_LOCK_ENV) != want:
                out.append(f"set {BUS_LOCK_ENV}={want} (the adapter's own lock; now {environ.get(BUS_LOCK_ENV) or 'unset'})")
        for key, entry in submission.sessions.items():
            if not entry["runner_kind"]:
                out.append(f"session {key} holds steps the rack runner has no kind for (bam_rack_twin.schedule's _no_runner_kind plan)")
        return out

    def dry_run(self, submission: Submission) -> dict[str, dict]:
        """The rack runner's offline checks for each plan, nothing opened (bam_rack_twin.schedule.dry_run: every step's own limits and the
        proven window from a joint at the schedule's origin). It cannot read the boards' live config or where the joint is; the session does
        both before anything moves."""
        from bam_rack_twin import schedule as rack_schedule  # noqa: PLC0415

        description = submission.document()["description"]
        q0 = float(description["origin_rad"]) / float(description["output_per_board"])
        return {key: rack_schedule.dry_run(submission.plan(key), q0=q0) for key in submission.sessions}

    def recorded(self, submission: Submission) -> dict[str, bool]:
        """Per session: has it written runs stamped with this submission's schedule."""
        out = {}
        for key in submission.sessions:
            runs = submission.session_out(key) / "runs"
            out[key] = any(_stamped(path, submission.digest) for path in sorted(runs.glob("*.json"))) if runs.is_dir() else False
        return out

    def play(self, submission: Submission) -> Recording:
        recorded = self.recorded(submission)
        missing = [key for key, done in recorded.items() if not done]
        if not missing:
            return self._recording(submission)
        checks = {"dry_run": self.dry_run(submission), "refusals": self.refusals(submission), "written_utc": _now()}
        checks["refusals"] += [f"dry run {key} refused: {r['refusal']}" for key, r in checks["dry_run"].items() if not r["ok"]]
        (submission.folder / "dry_run.json").write_text(json.dumps({**checks, "commands": {k: self.command(submission, k) for k in missing}},
                                                                   indent=1, default=str) + "\n", encoding="utf-8")
        if not self.execute:
            raise RunsPending(submission, [self.command(submission, k) for k in missing], checks)
        if checks["refusals"]:
            raise RackRefused(checks["refusals"])
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env[BUS_LOCK_ENV] = self.lock_path()
        for key in missing:
            argv = self.argv(submission, key)
            print("starting: " + self.command(submission, key), flush=True)
            self.runner(argv, env=env, check=True)
        return self._recording(submission)

    def _recording(self, submission: Submission) -> Recording:
        folders = tuple(submission.session_out(key) for key in submission.sessions if (submission.session_out(key) / "runs").is_dir())
        return Recording(folders, self.name, {"sources": {"all": "the rack's own sensors: eval()'s floor (T1, the rack against itself) measures them"}},
                         {"adapter": self.adapter})


# --- 4. ingest -----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ingested:
    """The runs a Recording returned, as the pipeline fits them (its RunData: the run in the joint output frame and its link angle), by
    purpose; the planned runs that did not come back (``missing``) and the ones that came back but are kept out of the fit and eval
    (``refused``: the producer's judge, or no usable link camera when the ingest is not strict), each with why."""

    train: Mapping[str, Any]
    held_out: Mapping[str, Any]
    floor: Mapping[str, Any]
    missing: Mapping[str, str]
    refused: Mapping[str, str]
    skipped: tuple[str, ...]
    files: Mapping[str, str]

    @property
    def received(self) -> int:
        """Planned runs that came back (used or refused)."""
        return len(self.files)

    @property
    def used(self) -> int:
        return len(self.train) + len(self.held_out) + len(self.floor)

    def summary(self) -> str:
        line = (f"ingest: {self.received} runs read through tools/run_files.py; {self.used} used ({len(self.train)} train, "
                f"{len(self.held_out)} held out, {len(self.floor)} floor)")
        if self.refused:
            line += f"; {len(self.refused)} kept out: " + "; ".join(f"{n} ({why})" for n, why in sorted(self.refused.items()))
        if self.missing:
            line += f"; {len(self.missing)} missing"
        return line

    def to_dict(self) -> dict:
        return {"received": self.received, "used": self.used, "train": list(self.train), "held_out": list(self.held_out), "floor": list(self.floor),
                "missing": dict(self.missing), "refused": dict(self.refused), "skipped": list(self.skipped), "files": dict(self.files)}


def run_files_module():
    """tools/run_files.py, the one door to the rack's run files, loaded by its path (an app folder beside the package; WHY by path: putting
    tools/ on sys.path would let its other modules shadow installed ones)."""
    name = "sim2real_tools_run_files"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / "run_files.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _trajectory(columns: Mapping[str, np.ndarray], can_id: int):
    """In-memory columns as the door builds them (tools/run_files.trajectory): the same JointTrajectory a file would give."""
    return run_files_module().trajectory(dict(columns), can_id=can_id)


def arrays_of(trajectory) -> dict[str, np.ndarray]:
    """A run's JointTrajectory back as its board columns (t, q, qd, tau and every channel), the inverse of the door."""
    door = run_files_module()
    out = {"t": np.asarray(trajectory.t, float)}
    for name in door.FIELDS:
        values = door.column(trajectory, name)
        if values is not None:
            out[name] = np.asarray(values, float)
    out.update({name: np.asarray(values, float) for name, values in trajectory.channels.items()})
    return out


def decode(meta: Mapping[str, Any], trajectory, station, *, npz_path: Path | None = None, judged: bool = True):
    """One run (its meta and JointTrajectory) as the joint-output-frame OutputRun the pipeline fits and replays, by the producer's own rules
    (bam_rack_twin.evidence: EVIDENCE_FIELDS, judge, command_semantics, to_output_frame at the run's wall time). Raises ValueError for a run
    the rules refuse (a missing column, an abort, a latched watchdog, a hard fault) when ``judged``."""
    from bam_rack_twin import evidence  # noqa: PLC0415

    arrays = arrays_of(trajectory)
    missing = [name for name in evidence.EVIDENCE_FIELDS if name not in arrays]
    if missing:
        raise ValueError(f"no {missing} column: not a rack run")
    kept = {name: arrays[name] for name in evidence.EVIDENCE_FIELDS}
    # WHY the tick too (bam_rack_twin.hardware.board.TICK_FIELD): a ticked run's rows carry the commanded tape's sample index, which T1's
    # floor compares repeats on, tick for tick (sim2real.metrics.series.repeat_floor)
    for name in ("ff_cog_nm", "ff_model_nm", "ilimit_scale_cmd", "tick"):
        if name in arrays:
            kept[name] = arrays[name]
    problems, notes = evidence.judge(meta, kept) if judged else ((), ())
    if problems:
        raise ValueError("; ".join(problems))
    kind = str(meta.get("kind") or "unknown")
    run = evidence.RealRun(name=str(npz_path.with_suffix("")) if npz_path else str(meta.get("label") or kind), kind=kind, can_id=int(meta["can_id"]),
                           npz_path=npz_path or Path("/nonexistent"), npz_sha256=_sha256(npz_path) if npz_path else "", meta=dict(meta), arrays=kept,
                           semantics=evidence.command_semantics(kind, meta.get("args") or {}), problems=tuple(problems), notes=tuple(notes),
                           root=npz_path.parent if npz_path else None)
    if run.semantics is None:
        raise ValueError(f"kind {kind!r} with args {sorted(meta.get('args') or {})} has no command semantics: it cannot be replayed")
    return evidence.to_output_frame(run, station)


def link_angle(trajectory, link) -> np.ndarray:
    """The link camera's angle on the run's own rows: on the wall clock (each header's stamp + its t), linearly interpolated, never
    extrapolated (a row the camera did not see is refused: identify() reads the gap on every row)."""
    run_wall = trajectory.header.stamp + np.asarray(trajectory.t, float)
    link_wall = link.header.stamp + np.asarray(link.t, float)
    angle = np.asarray(link.positions[:, 0], float)
    if run_wall.size == link_wall.size and np.array_equal(run_wall, link_wall):
        return angle.copy()
    if run_wall[0] < link_wall[0] or run_wall[-1] > link_wall[-1]:
        raise ValueError(f"the link camera covers {link_wall[0] - run_wall[0]:+.3f} .. {link_wall[-1] - run_wall[-1]:+.3f} s of the run's ends")
    return np.interp(run_wall, link_wall, angle)


def ingest(recording: Recording, submission: Submission, *, station, module, strict: bool = True) -> Ingested:
    """Every run in the recording's session folders read through the door, keyed by its schedule stamp, judged, framed and paired with its
    link angle.

    A run the producer's rules refuse (bam_rack_twin.evidence.judge: an abort, a latched watchdog, a hard fault, too few controlled rows, a
    setpoint not followed) is kept out of the fit and eval and named with its reason, never fatal. WHY (measured 2026-11-15, the twin's
    world): CAN 11's multisine at kp x 0.25 sticks in its stiction band (5 mrad of a 100 mrad command), and bam_rack_twin's own convention
    is that "a problem keeps it out of every fit and replay"; refusing the whole calibration for it would block CAN 11 forever, since a
    re-run meets the same physics. A real fault still shows: the rack's session stops a board's later steps after one, and those are missing.

    Fatal, always: a run recorded twice, a run stamped with this schedule but logged by another board, nothing to fit. Fatal when ``strict``
    (the default): a planned run that did not come back, a train or held-out run without a usable link camera (identify() reads the
    motor-minus-link gap on every row). ``strict=False`` fits what came back, keeping those runs out, and says so."""
    from robot_msgs import load_npz  # noqa: PLC0415

    door = run_files_module()
    document = submission.document()
    rows = {r["run"]: r for r in submission.runs}
    by_id = {t["id"]: t for t in document["trajectories"]}
    got: dict[str, dict[str, Any]] = {p: {} for p in PURPOSES}
    refused, skipped, files, unlinked = {}, [], {}, {}
    for folder in recording.folders:
        for npz in sorted((Path(folder) / "runs").glob("*.npz")):
            loaded = door.load_run(npz)
            if loaded is None:
                skipped.append(f"{npz}: not a run (no meta with a can_id, or no t / q)")
                continue
            meta, trajectory = loaded
            stamp = meta.get("schedule") or {}
            if stamp.get("digest") != submission.digest:
                skipped.append(f"{npz}: stamped {stamp.get('digest')!r}, not this submission's schedule {submission.digest}")
                continue
            name = stamp.get("run")
            if name not in rows:
                skipped.append(f"{npz}: run {name!r} is not one this submission planned")
                continue
            if name in files:
                raise IngestError(f"run {name} was recorded twice ({files[name]} and {npz}): keep one session's copy")
            files[name] = str(npz)
            if int(meta.get("can_id", -1)) != submission.can_id:
                raise IngestError(f"{npz} is stamped with {submission.twin}'s run {name} but logged by CAN {meta.get('can_id')}, not "
                                  f"{submission.can_id}: this folder mixes boards")
            try:
                output = decode(meta, trajectory, station, npz_path=npz)
            except ValueError as error:
                refused[name] = str(error)  # the producer's rules keep it out of every fit and replay
                continue
            link_path = npz.parent / LINK_CAMERA_DIR / npz.name
            q_link, unlinked[name] = None, f"no runs/{LINK_CAMERA_DIR}/{npz.name}"
            if link_path.is_file():
                try:
                    q_link = link_angle(trajectory, load_npz(link_path))
                    unlinked.pop(name)
                except ValueError as error:
                    unlinked[name] = f"link camera: {error}"
            row = rows[name]
            data = module.RunData(name, row["family"], by_id[row["trajectory"]]["runner_kind"] or "", output, q_link)
            got[row["purpose"]][name] = data
    # WHY in the plan's order (the files sort by session step): identify() concatenates its runs in dict order and its block bootstrap
    # draws by that order, so the planned order keeps the fit's intervals the sim backend's for the same runs
    got = {p: {n: got[p][n] for n in submission.run_ids(p) if n in got[p]} for p in PURPOSES}
    missing = {name: rows[name]["purpose"] for name in rows if name not in files}
    no_link = {n: unlinked[n] for p in ("train", "held_out") for n in got[p] if got[p][n].q_link is None}
    fatal = []
    if missing and strict:
        fatal.append(f"{len(missing)} planned runs did not come back: {sorted(missing)[:8]}")
    if no_link and strict:
        fatal.append(f"{len(no_link)} train / held-out runs have no usable link camera (runs/{LINK_CAMERA_DIR}/<name>.npz, the link angle on "
                     f"tags 8-12): identify()'s M4 gap and gear-contact rows read it, e.g. " + "; ".join(f"{n}: {why}" for n, why in sorted(no_link.items())[:3]))
    elif no_link:
        for name, why in no_link.items():
            refused[name] = why
            got[rows[name]["purpose"]].pop(name)
    if not got["train"]:
        fatal.append("no train run came back usable: nothing to fit")
    if fatal:
        notes = [f"kept out by the producer's rules or the link camera: " + "; ".join(f"{n}: {why}" for n, why in sorted(refused.items())[:5])] if refused else []
        raise IngestError("the returned runs cannot be fitted as planned:\n" + "\n".join(f"  - {p}" for p in fatal + notes))
    return Ingested(got["train"], got["held_out"], got["floor"], missing, refused, tuple(skipped), files)


# --- the runner ----------------------------------------------------------------------------------------------------------------------


class RealRunner:
    """The real backend's runner: plan, emit, play (the transport), ingest, the schedule's routines fitted sealed; eval over the rack's own
    floor. ``state`` is a fitted twin's. Guards here, never in a transport: each routine fits inside sysid.world.sealed() and receives the
    train runs only; the ruler is asked of the transport only after the last fit; eval refuses any run the fit saw."""

    def __init__(self, description, *, workers: int = WORKERS, state: dict | None = None):
        self.description = description
        self.workers = int(workers)
        self.state: dict = dict(state or {})

    def pipeline(self):
        _, oracle, _, _ = _sysid()
        return oracle.example_module(self.description.id)

    def sysid_description(self):
        return SimRunner(self.description, workers=self.workers).sysid_description()

    def typed(self) -> Instance:
        return SimRunner(self.description, workers=self.workers).typed()

    def simulate(self, **options):
        return SimRunner(self.description, workers=self.workers).simulate(**options)

    def schedule(self):
        """The routines the example ships (SimRunner.schedule(): sysid/examples/<id>/routines.py), or None. WHY here too: a twin fitted on
        real plans the same schedule (plan(fitted)), never the catalog's stand-ins."""
        return SimRunner(self.description, workers=self.workers).schedule()

    def calibrate(self, *, model: str, transport: Transport | None, strict: bool = True,
                  routines: Sequence[Any] | None = None, data: Any = None, on_step: Callable[[dict], None] | None = None,
                  on_collect: Callable[[dict], None] | None = None, on_submission: Callable[..., None] | None = None,
                  on_pending: Callable[[Any, BaseException], None] | None = None) -> tuple[Calibration, dict]:
        """`routines`: the planned sequence (sim2real.calibration.plan(twin).routines), else the example's own routines in their declared
        order, as SimRunner.calibrate. The rack plays one submission (the pipeline's run schedule plus its floor repeats); the routines then
        fit the train runs that came back, in order, through the sim's own loop (twin._play_routines), each sealed from the hidden truth.

        `data` (rack runs a twin holds, a sim2real.calibration.CalibrationData of backend "real"): nothing is emitted or played and no
        transport is asked anything; the routines refit the held train runs, and eval judges on the held held-out and floor runs.

        The hooks (gap E: calibrate(callbacks=)), each called only when given: `on_submission(folder, emitted=)` once emit has written the
        submission, before the rack plays it (a refit names the submission its runs came from); `on_pending(submission, RunsPending)` when
        the rack has runs still to play, before it is raised; `on_collect` once with what came back; `on_step` each step as its fit
        finishes (twin._play_routines)."""
        from .calibration.plan import CalibrationPlanError, order  # noqa: PLC0415

        twin_module._refuse_rounds(routines, "the rack plays one submission")
        _, _, result, _ = _sysid()
        started = time.monotonic()
        module, d = self.pipeline(), self.sysid_description()
        servo = self.typed()
        rung = SimRunner._rung(servo.type, model)
        plan = module.plan(d)
        shipped = self.schedule()
        names = {f"{i.id}.{n}": n for i in self.description.instances for n in i.parameters}
        if routines is None:
            if shipped is None:
                raise NotImplementedError(f"{self.description.id} ships no routines (sysid/examples/{self.description.id}/routines.py): "
                                          "nothing here runs the catalog's routines plan() would show")
            routines = order(shipped.routines(), names)
        # the values each routine sees: the description's priors, then what each routine before it found
        values = {k: float(v) for k, v in self.description.values().items() if v is not None}
        if data is not None:
            # WHY no emit, no play, no ingest (gap D; Zach, 2026-11-18: "So on any dataset... now I should be able to just like better fit
            # the models no?"): the runs are already held, so a refit spends no rack time; each keeps the file it was read from (meta files)
            submission, recording, purposes = None, None, {k: data.serves.get(k, k) for k in (*data.runs, *data.held_out)}
            if on_submission is not None and data.meta.get("submission"):
                on_submission(data.meta["submission"], emitted=False)
            measured = _ingested(data)
            played = twin_module._played_from_data(data)
            noise = dict(data.noise or {})
            moved = dict(data.meta.get("truth_moved") or {})
            transport_name = data.meta.get("transport")
        else:
            # WHY before emit (Zach's rule that robot time is earned): a planned step asking for a run the submission does not carry would
            # fail only after the rack spent its minutes; refuse it here, before anything is written or played
            fills = {run_id for run_id, split in twin_module.PLAYED_SPLITS.items() if getattr(plan, split, None)}
            unfillable = _unfillable(routines, values, fills, names)
            if unfillable:
                raise CalibrationPlanError(f"on='real' refused before the rack moves: {'; '.join(unfillable)}; the submission fills "
                                           f"{sorted(fills) or 'no run id'} (twin.PLAYED_SPLITS over the pipeline's splits)")
            joint = servo.binds.get("joint") or module.JOINT
            submission = emit(self.description.id, plan, transport.folder(self.description.id, plan.digest),
                              can_id=int(servo.binds.get("station")), joint=joint)
            if on_submission is not None:
                on_submission(submission.folder, emitted=True)
            try:
                recording = transport.play(submission)
            except RunsPending as pending:
                if on_pending is not None:
                    on_pending(submission, pending)   # WHY before it is raised: a ledger ends "pending" naming the submission, never "error"
                raise
            _, _, station = module._rack()
            measured = ingest(recording, submission, station=station, module=module, strict=strict)
            played, purposes = twin_module._played_from(measured), None
            noise = {"transport": transport.name, **dict(recording.noise)}
            moved = dict(recording.meta.get("truth_moved") or {})
            transport_name = transport.name
        if on_collect is not None:
            on_collect({"collected": "recorded" if data is not None else "measured", "seconds": time.monotonic() - started,
                        "runs": {"train": len(measured.train), "held_out": len(measured.held_out), "floor": len(measured.floor)},
                        "missing": len(measured.missing), "refused": len(measured.refused),
                        "submission": str(submission.folder) if submission is not None else data.meta.get("submission")})
        handle = PipelineHandle(module, d, self.workers, rung)
        hooks = {} if on_step is None else {"on_step": on_step, "collected": "recorded" if data is not None else "measured"}
        settings, proposals = {}, {}   # what a configure / tune step chose (gap C): settings, never values
        # WHY keep_fits_on_failed_tune (L10 review): by now the rack has played and its runs are ingested; a tune that fails after that
        # is recorded as a stopped step and the fits it would have tuned on are kept, never lost to its error (twin._play_routines)
        fit, steps, handed = twin_module._play_routines(routines, played, values, handle, servo=servo.id, settings=settings,
                                                        proposals=proposals, keep_fits_on_failed_tune=True, **hooks)
        # WHY after the seal: the fit never sees it; real hardware has none (rows ungraded); a refit asks no transport, so none either
        ruler = dict(transport.ruler() or {}) if transport is not None else {}
        recovered = {f"{servo.id}.{name}": {"value": value, "ci95": fit.ci95[rung].get(name), "rung": f"fitted with {rung}",
                                              "method": handed.get(name, fit.methods[rung])} for name, value in fit.values[rung].items()}
        rows = result.parameter_rows(self.description.id, d, ruler, recovered)
        if not ruler:
            for r in rows:
                r["why_not"] = "real hardware has no hidden truth to grade against: eval() judges the twin on held-out runs"
        twin_module._mark_unplanned_rows(rows, routines, shipped)
        values = {}
        for name, value in fit.values[rung].items():
            key = f"{servo.id}.{name}"
            unit = d.nominal[key].unit if key in d.nominal else None
            ci = fit.ci95[rung].get(name)
            values[name] = None if value is None else Value(float(value), unit, basis=Basis.MEASURED,
                                                           measured_by=(f"sim2real.RobotTwin.calibrate(on='real', transport={transport_name}), {model}"
                                                                        if data is None else f"sim2real.RobotTwin.calibrate(on='real', data=), {model}"),
                                                           source=handed.get(name, fit.methods[rung]),
                                                           notes=f"95 % interval [{ci[0]:.6g}, {ci[1]:.6g}]" if ci else "")
        card = ORACLE_CARD[servo.type]
        from .cards import domain as dm  # noqa: PLC0415

        fits = [{"rung": k, "model": dm.RUNG_MODELS.get((card, k), (k,))[0],
                 "found": {f"{servo.id}.{name}": fit.values[k][name] for name in fit.values[k] if name in fit.ci95.get(k, {})}} for k in fit.values]
        state = {"d": d, "plan": plan, "submission": submission, "recording": recording, "measured": measured, "fit": fit, "ruler": ruler,
                 "model": model, "rung": rung, "module": module, "servo": servo, "noise": noise, "fits": fits, "noise_level": "real",
                 "transport": transport_name, "routines": steps, "settings": settings, "proposals": proposals}
        held = {}
        if data is not None:
            state.update(data=data, purposes=purposes)
            held = {"data_sessions": list(data.sessions)}
        calibration = Calibration("real", model, rung, values, {k: dict(v) for k, v in fit.values.items()}, rows, moved,
                                  round(time.monotonic() - started, 1),
                                  {"train_runs": len(measured.train), "held_out_runs": len(measured.held_out), "floor_runs": len(measured.floor),
                                   "digest": plan.digest, "transport": transport_name,
                                   "submission": str(submission.folder) if submission is not None else data.meta.get("submission"),
                                   "missing": dict(measured.missing), "refused": dict(measured.refused),
                                   "coverage_train_pct": plan.coverage["train"]["pct"], "routines": [s["routine"] for s in steps], **held})
        return calibration, state

    def eval(self) -> RealReport:
        if not self.state:
            raise RuntimeError("eval needs a fitted twin: fitted = twin.calibrate(on='real', transport=...), then fitted.eval()")
        _, _, result, _ = _sysid()
        s = self.state
        module, measured, fit = s["module"], s["measured"], s["fit"]
        # a refit from held runs has no submission: each held run's purpose is what it serves (gap D)
        purpose = s.get("purposes") or {r["run"]: r["purpose"] for r in s["submission"].runs}
        # WHY refused, not filtered (sklearn's leakage rule, as SimRunner.eval): only runs the plan held out may judge the twin
        leaked = sorted(n for n in measured.held_out if purpose.get(n) != "held_out" or n in measured.train)
        if leaked:
            raise ValueError(f"eval scores held-out runs only; these are training runs: {leaked[:5]}")
        names = sorted(measured.held_out)
        if not names:
            raise ValueError("eval needs held-out runs; none came back")
        twins = {"nominal": module.twin(module.nominal_values(s["d"]), "nominal")}
        twins.update({key: module.twin(fit.values[key], f"sysid-{key}") for key in module.RUNGS})
        replays = module.replay({n: measured.held_out[n].output for n in names}, twins, workers=self.workers)
        floor = _floor(measured.floor, "encoder")
        link_floor = _floor(measured.floor, "link")
        models, ratios = {}, {}
        with_link = all(measured.held_out[n].q_link is not None for n in names)
        for label in twins:
            motor = np.concatenate([replays[(label, n)].q - measured.held_out[n].output.q for n in names])
            torque = np.concatenate([replays[(label, n)].tau - measured.held_out[n].output.tau for n in names])
            link = np.concatenate([module.link_of(replays[(label, n)]) - measured.held_out[n].q_link for n in names]) if with_link else None
            entry = {"motor_mrad": rms(motor) * 1e3, "torque_nm": rms(torque), "link_mrad": None if link is None else rms(link) * 1e3}
            entry["ratio"] = entry["motor_mrad"] / (floor.value * 1e3) if floor.value else None
            entry["link_ratio"] = entry["link_mrad"] / (link_floor.value * 1e3) if (link is not None and link_floor.value) else None
            models[label] = entry
            ratios[label] = entry["ratio"]
        ladder, _ = _sysid_cards().ladder(ORACLE_CARD[s["servo"].type])
        scored = tuple(r for r in ladder if r.key in module.RUNGS)
        selected = reg.select_rung(scored, {r.key: ratios.get(r.key) for r in scored})
        rung, model = s["rung"], s["model"]
        need = result.ACCEPTANCE["examples"][self.description.id]["metrics"]["held_out_link_fidelity"]
        gates = []
        floor_value = f"{floor.value * 1e3:.4g} mrad, {floor.runs} repeats ({floor.pairs} pairs)" if floor.value is not None else "no repeats"
        verdict = gate(floor.runs if floor.value is not None else 0, targets.FLOOR_REPEATS)
        gates.append(Gate("floor", "T1: the rack against itself, the floor tape's identical repeats (motor encoder)", floor_value,
                          f">= {targets.FLOOR_REPEATS.low:g} repeats", verdict.passes, "sim2real.cards.servo_gates.FLOOR_REPEATS (T1)", verdict.violations))
        verdict = gate(ratios.get(rung), targets.FIDELITY_TAPES)
        gates.append(Gate("twinned", f"{model} held-out motor-encoder error / the floor (T2)", _g(ratios.get(rung), 3),
                          f"<= {targets.FIDELITY_TAPES.high:g}x", verdict.passes, "sim2real.cards.servo_gates.FIDELITY_TAPES (T2)", verdict.violations))
        factor = models["nominal"]["motor_mrad"] / models[rung]["motor_mrad"] if models[rung]["motor_mrad"] else None
        verdict = gate(factor, at_least(need, "x"))
        gates.append(Gate("held_out_fidelity", "held-out motor-encoder error, nominal / calibrated", _g(factor, 3), f">= {need:g}x", verdict.passes,
                          "sysid/acceptance.json held_out_link_fidelity's factor, read on the motor encoder", verdict.violations))
        metrics = {
            "held_out_motor_mrad": {"id": "held_out_motor_mrad", "before": models["nominal"]["motor_mrad"], "after": models[rung]["motor_mrad"],
                                    "factor": factor, "unit": "mrad", "gated": True},
            "held_out_link_fidelity": {"id": "held_out_link_fidelity", "before": models["nominal"]["link_ratio"], "after": models[rung]["link_ratio"],
                                       "factor": (models["nominal"]["link_mrad"] / models[rung]["link_mrad"]) if with_link and models[rung]["link_mrad"] else None,
                                       "unit": "x the link camera's floor", "gated": False,
                                       "note": "the camera on tags 8-12, over its own floor (the same repeats): a flag beside the encoder's gates, never a gate"},
            "models": models,
        }
        seconds = round(sum(float(measured.held_out[n].output.t[-1]) for n in names), 1)
        return RealReport(model, rung, selected.key if selected else None, (floor.value or math.nan) * 1e3, ratios, metrics, tuple(gates), len(names),
                          seconds, floor_runs=floor.runs, link_floor_mrad=None if link_floor.value is None else link_floor.value * 1e3,
                          link_ratios={k: v["link_ratio"] for k, v in models.items()})


@dataclass(frozen=True)
class RealReport(TwinReport):
    """eval()'s report on the real backend: TwinReport's fields (``ratios`` and ``floor_mrad`` on the motor encoder, the gates' channel) plus
    the floor's repeat count and the link camera's floor and ratios (the flag)."""
    floor_runs: int = 0
    link_floor_mrad: float | None = None
    link_ratios: Mapping[str, float | None] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"eval (real): {self.runs} held-out runs ({self.seconds:g} s of motion) replayed on their own commands; floor {self.floor_mrad:.4g} mrad "
                 f"(T1: {self.floor_runs} repeats of the floor tape, motor encoder)",
                 "  held-out motor-encoder error / floor: " + ", ".join(f"{k} {_g(v, 3)}x" for k, v in self.ratios.items()),
                 "  link camera / its floor" + (f" ({self.link_floor_mrad:.4g} mrad), a flag: " if self.link_floor_mrad else ", a flag: ")
                 + ", ".join(f"{k} {_g(v, 3)}x" for k, v in self.link_ratios.items()),
                 f"  the selection rule picks {self.selected}; the twin is {self.model} ({self.rung})"]
        for g in self.gates:
            lines.append(f"  gate {g.id:24s} {'pass' if g.passed else 'FAIL'}  {g.title}: {g.value} ({g.rule}; {g.source})")
        lines.append(f"  => {'PASS' if self.passed else 'FAIL'}: {sum(g.passed for g in self.gates)}/{len(self.gates)} gates")
        return "\n".join(lines)


def _floor(runs: Mapping[str, Any], channel: str):
    """T1 over the floor runs: sim2real.metrics.series.repeat_floor, each run (t from 0, its whole command: position, velocity and the
    feed-forward it carried, each against its own same-input tolerance, the response: the motor encoder or the link camera)."""
    from bam_rack_twin.evidence import logged_feedforward_output_nm  # noqa: PLC0415

    series = []
    for name in sorted(runs):
        data = runs[name]
        out = data.output
        response = out.q if channel == "encoder" else data.q_link
        if response is None:
            continue
        command = {"q_target": out.q_target, "qd_target": out.qd_target,
                   "ff_nm": logged_feedforward_output_nm(out.run.arrays, out.station, rows=out.t.size)}
        tick = out.run.arrays.get("tick")
        entry = (np.asarray(out.t, float), command, np.asarray(response, float))
        series.append(entry if tick is None else (*entry, np.asarray(tick).astype(np.int64)))
    return repeat_floor(series, tolerance={"q_target": SAME_INPUT_TOLERANCE_RAD, "qd_target": SAME_INPUT_TOLERANCE_RAD_S, "ff_nm": SAME_INPUT_TOLERANCE_NM})


def _sysid_cards():
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))
    from sysid import cards  # noqa: PLC0415

    return cards


# --- the runs a twin fitted on the rack holds (gap D) -------------------------------------------------------------------------------------


def held_runs(twin_id: str, planned, state: Mapping[str, Any]):
    """What a twin fitted on the rack holds (its data_): one key per run that came back usable, the train runs to fit and the held-out and
    floor runs apart (never fitted), `serves` naming each one's purpose, and `meta` the twin, the backend ("real"), the transport, the
    submission folder (its absolute path is the session), the schedule digest, the file each run was read from, what was refused and
    missing.

    WHY the absolute path and never the folder's name (fix round 1): two RackTransport(out) sessions under different parents can share a
    basename, and a session already held is kept once when datasets grow, so a shared name would drop the second session."""
    from .calibration.collect import CalibrationData  # noqa: PLC0415

    measured, submission, recording = state["measured"], state["submission"], state["recording"]
    serves = {**{n: "train" for n in measured.train}, **{n: "held_out" for n in measured.held_out}, **{n: "floor" for n in measured.floor}}
    meta = {"twin": twin_id, "backend": "real", "session": str(Path(submission.folder).resolve()), "transport": state["transport"],
            "submission": str(submission.folder), "schedule_digest": submission.digest, "files": dict(measured.files),
            "refused": dict(measured.refused), "missing": dict(measured.missing)}
    if recording is not None and recording.meta.get("truth_moved"):
        meta["truth_moved"] = dict(recording.meta["truth_moved"])  # the twin transport's mutation test: a refit says so too
    return CalibrationData(runs=dict(measured.train), plan=planned, noise=dict(state["noise"]), meta=meta,
                           held_out={**dict(measured.held_out), **dict(measured.floor)}, serves=serves)


def _ingested(data) -> Ingested:
    """Held rack runs back as the Ingested the fit and eval read: every recording that serves train, held_out and floor (each session's,
    by its key), the files they came from, and what the sessions refused or missed."""
    def serving(purpose: str, pool: Mapping[str, Any]) -> dict[str, Any]:
        return {k: pool[k] for k in data.answering(purpose) if k in pool}

    files = dict(data.meta.get("files") or {})
    keys = (*data.runs, *data.held_out)
    return Ingested(train=serving("train", data.runs), held_out=serving("held_out", data.held_out), floor=serving("floor", data.held_out),
                    missing=dict(data.meta.get("missing") or {}), refused=dict(data.meta.get("refused") or {}), skipped=(),
                    files={k: files[k] for k in keys if k in files})


# --- the front door's hook ------------------------------------------------------------------------------------------------------------


def _unfillable(routines: Sequence[Any], values: Mapping[str, float], fills: set[str], names: Mapping[str, str]) -> list[str]:
    """Each known-now routine whose runs at the priors name a run id no split of the submission fills: ["<routine> plays runs [...]"].
    Known now: nothing it requires is written by a routine before it (the planner's own requires edge). A routine whose runs are made after
    an earlier fit, or that has no preview at the priors (LookupError / OSError), is left to the executor, which refuses it before its fit."""
    from .calibration.plan import declaration  # noqa: PLC0415

    written: set[str] = set()
    out = []
    for routine in routines:
        decl = declaration(routine)
        made_after = any(need in written for need in decl.requires)
        keys = decl.identifies + decl.configures
        written |= set(keys) | {names[k] for k in keys if k in names}
        if made_after:
            continue
        try:
            runs = list(routine.runs(dict(values)))
        except (LookupError, OSError):
            continue
        missing = [run.id for run in runs if run.id not in fills]
        if missing:
            out.append(f"{routine.id} plays runs {missing}")
    return out


def calibrate(twin, transport: Transport | None, *, strict: bool = True, data: Any = None, config: Any = None,
              on_plan: Callable[[Any], None] | None = None,
              on_step: Callable[[dict], None] | None = None, on_collect: Callable[[dict], None] | None = None,
              on_submission: Callable[..., None] | None = None, on_pending: Callable[[Any, BaseException], None] | None = None):
    """RobotTwin.calibrate(on="real")'s body: a NEW, fitted twin carrying the calibrated values, plan_ (the schedule plan(twin) shows, the
    one that ran), record_ (sim2real.calibration/1, backend "real"), submission_ and runs_ (what the transport sent back and what could not
    be used) and data_ (the runs it holds: held_runs). On a real record, plan.totals are the planner's estimates (the rack's own time is
    submission_.minutes) and plan.level is the planner's noise level, not the hardware's.

    `data` (rack runs a twin holds, checked by RobotTwin.calibrate): the refit plays nothing, its plan is the data's, its submission_ is
    None and its data_ is all of `data`.

    The on_* hooks (gap E; RobotTwin.calibrate and main pass them only when there are callbacks, sim2real.calibration.callbacks.Watch):
    `on_plan(schedule)` before anything is emitted, so a ledger holds the schedule before the rack moves; the rest are RealRunner.calibrate's.

    `config` (a CalibrationConfig, checked by RobotTwin.calibrate: today only one that excludes pid.pidtuna) plans the schedule; None plans
    with the default config."""
    from .calibration.config import CalibrationConfig  # noqa: PLC0415
    from .calibration.plan import plan as schedule_of  # noqa: PLC0415
    from .calibration.record import CalibrationRecord  # noqa: PLC0415
    from .twin import RobotTwin  # noqa: PLC0415

    # WHY plan first and play exactly its routines, as on='sim' (Zach, 2026-11-17: "robottwin.calibrate() internall mabye that does
    # .generate_schedule() -> CalibrationSchedule and then you can pass that to something thats gonna like dispatch/execute it"): one
    # schedule is shown, and it is the one the rack's runs are fitted by
    planned = data.plan if data is not None else schedule_of(twin, config if config is not None else CalibrationConfig())
    # WHY the twin's runner's description (gap D): it is the loaded twin's priors on a fitted twin too (whose own description is edited, and
    # the pipeline refuses edited priors), so a twin fitted on the rack refits from the same priors
    priors = twin.runner.description
    runner = RealRunner(priors, workers=twin.runner.workers)
    given = {} if data is None else {"data": data}
    given.update({name: hook for name, hook in (("on_step", on_step), ("on_collect", on_collect), ("on_submission", on_submission),
                                                ("on_pending", on_pending)) if hook is not None})
    if on_plan is not None:
        on_plan(planned)
    calibration, state = runner.calibrate(model=twin.model, transport=transport, strict=strict, routines=list(planned.routines), **given)
    servo = runner.typed().id
    fitted = RobotTwin.__new__(RobotTwin)
    fitted.description = twin.description.with_values(_identified(calibration, calibration.rung, lambda name: f"{servo}.{name}"))
    fitted.model, fitted.models = twin.model, twin.models
    fitted.runner = RealRunner(priors, workers=runner.workers, state=state)
    fitted.values_ = calibration.values
    fitted.intervals_ = {r["name"]: tuple(r["ci95"]) for r in calibration.rows if r["ci95"]}
    fitted.rungs_ = calibration.rungs
    fitted.calibration_ = calibration
    fitted.settings_, fitted.proposals_ = dict(state.get("settings", {})), dict(state.get("proposals", {}))
    fitted.submission_ = state["submission"]
    fitted.runs_ = state["measured"]
    fitted.data_ = data if data is not None else held_runs(twin.description.id, planned, state)
    fitted.plan_ = planned
    fitted.record_ = CalibrationRecord.from_schedule(calibration.to_dict(), routines=state["routines"], plan=planned, noise=state["noise"],
                                                     twin=twin.description.id, description=twin.description)
    return fitted


# --- helpers --------------------------------------------------------------------------------------------------------------------------


def _stamped(meta_path: Path, digest: str) -> bool:
    try:
        return (json.loads(meta_path.read_text(encoding="utf-8")).get("schedule") or {}).get("digest") == digest
    except (OSError, ValueError):
        return False


def _record_path(board_module) -> str:
    try:
        from bam_rack_twin.stations import DEFAULT_RECORD_PATH  # noqa: PLC0415

        return str(DEFAULT_RECORD_PATH)
    except ImportError:
        return f"the record beside {_tree(board_module)}"


def _tree(board_module) -> str:
    """The bam_rack_twin package folder a board module belongs to (<pkg>/bam_rack_twin/hardware/board.py)."""
    where = getattr(board_module, "__file__", None)
    return str(Path(where).resolve().parents[2]) if where else repr(board_module)


def _sha256(path: Path | None) -> str:
    if path is None:
        return ""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(folder: Path) -> dict:
    try:
        run = lambda *a: subprocess.run(["git", "-C", str(folder), *a], capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
        return {"commit": run("rev-parse", "--short", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "."))}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unknown", "dirty": None}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- one command ------------------------------------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """python -m sim2real.real: the real calibration of one station as one command. A dry run unless --execute (the rack transport writes
    the submission and its dry run, prints the session command and exits 0); once the sessions' runs are in --out it fits them, evaluates
    the fitted twin and writes calibration.json (sim2real.calibration/1 with eval's gates) and eval.json beside the submission.
    --transport twin plays the same command path on the rack twin at the sealed hidden truth (no hardware anywhere). Its ledger follows
    SIM2REAL_TRACK as calibrate() does (unset: a ledger beside the submission, <out>/calibrate/<stamp>/; off: none; wandb: and its W&B copy)."""
    parser = argparse.ArgumentParser(prog="python -m sim2real.real", description=main.__doc__)
    parser.add_argument("--twin", default="pendulum_can11", choices=("pendulum_can11",), help="the station's twin (sim2real.examples)")
    parser.add_argument("--transport", default="rack", choices=("rack", "twin"))
    parser.add_argument("--out", type=Path, default=None, help=f"the submission's folder (default: {paths.REAL_RUNS}/<twin>-<UTC stamp>)")
    parser.add_argument("--adapter", default=None, help="the fdcanusb serial the station's record must name (the One Dof Test Rack: 272813EF)")
    parser.add_argument("--execute", action="store_true", help="start the rack sessions (the rack owner only; refused unless every check passes)")
    parser.add_argument("--workers", type=int, default=WORKERS, help="replay worker processes for the fit and eval (default 2: a powered rack's lane cap)")
    parser.add_argument("--move-truth", action="append", default=[], metavar="KEY=VALUE", help="twin transport only: move a hidden value (the ruler's red run)")
    parser.add_argument("--partial", action="store_true", help="fit what came back even when planned runs are missing or refused")
    args = parser.parse_args(argv)
    import sim2real  # noqa: PLC0415

    out = args.out or paths.REAL_RUNS / f"{args.twin}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    if args.transport == "twin":
        if args.execute:
            parser.error("--execute is the rack transport's")
        moved = {}
        for item in args.move_truth:
            key, _, value = item.partition("=")
            moved[key] = float(value)
        transport = TwinTransport(root=out, move_truth=moved, workers=args.workers)
    else:
        if args.move_truth:
            parser.error("--move-truth is the twin transport's (real hardware has no truth to move)")
        transport = RackTransport(out, execute=args.execute, adapter=args.adapter)
    twin = getattr(sim2real.examples, args.twin)(workers=args.workers)
    from .calibration.callbacks import Watch, resolve_callbacks  # noqa: PLC0415

    # WHY resolved as RobotTwin.calibrate resolves them, and the hooks passed only when there are callbacks: one rule for both doors
    callbacks = resolve_callbacks(None, backend="real")
    watch = Watch(callbacks, twin, "real") if callbacks else None
    try:
        try:
            fitted = calibrate(twin, transport, strict=not args.partial, **(watch.real_hooks() if watch is not None else {}))
        except BaseException as caught:
            if watch is not None:
                watch.error(caught)   # a RunsPending already ended it "pending"
            raise
    except RunsPending as pending:
        print(pending, flush=True)
        return 0
    except RackRefused as refused:
        print(refused, flush=True)
        return 2
    if watch is not None:
        watch.end(fitted)   # and fitted.callbacks_, so the eval below lands in the same ledger
    print(fitted.runs_.summary(), flush=True)
    print(fitted.calibration_.summary(), flush=True)
    report = fitted.eval()
    print(report.summary(), flush=True)
    record = fitted.record_.with_evaluation(report.to_dict())
    folder = fitted.submission_.folder
    (folder / "calibration.json").write_text(json.dumps(record.to_dict(), indent=1, default=_json_default) + "\n", encoding="utf-8")
    (folder / "eval.json").write_text(json.dumps({**report.to_dict(), "ingest": fitted.runs_.to_dict()}, indent=1, default=_json_default) + "\n",
                                      encoding="utf-8")
    print(f"wrote {folder / 'calibration.json'} and {folder / 'eval.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
