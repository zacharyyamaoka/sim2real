"""The real arm's home button replayed on the MuJoCo rung: ground truth for ``MujocoRigPlant`` before any procedure is judged on it.

The homing bench's MuJoCo rung failed recover_first under gravity (bam_fivebar_recovery's blind recovery, step 3 never ``Reached``),
while the real arm's home button (bam_rack_twin ``fivebar_home -f``) recovered it repeatedly. Zach's rule is to prove in sim against
ground truth, and here reality is the ground truth: so the sim must first reproduce what the real arm did, from where it did it.

What is replayed is the real code path, not a copy of it: ``bam_fivebar_recovery.home.return_home`` (classify the rest; the settle
``JointCommandSequence`` when off the working branch - J2 back with the crank limp; then the walk home, each waypoint carrying its static
gravity torque; a hold at home) through ``bam_fivebar_recovery.backend.PlantBackend`` (the rack runner's adapter: ilimit_scale 0, no
velocity target), on the same bench (``bam_rack_twin.hardware.fivebar_run.bench_real``: ``in_mode(real_assembly(BENCH), "vertical")``),
the same comp per run (the nominal ``ControllerModel`` before bam_ws 2ec4dd02a, the identified lumped model after) and the homed map's
home. Only the plant changes: :class:`RigBoards` puts ``MujocoRigPlant`` behind bam_fivebar's ``Plant`` seam in the arm's Craig drive
angles (``bam_fb_test_rig.gravity.CraigMap``: Craig = URDF + offset, sign +1 for J2 and C1 on bundle 8957130), J1 held where it starts.

The real runs (``data/fivebar_home_button_real_2026-11-12.json``, extracted by ``tools/extract_home_button_real.py`` from the receipts
and tick rows under ``/archive/datasets/bam_rig/rack_2026-11-10/fivebar_real``) give each step's outcome, duration and end pose; the
replay gives the same, and :func:`compare` lines them up.

Run (writes the JSON the homing report reads; exit 0 only when every replay passes :func:`verdict`):

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra homing --extra sim python -m sim2real.sim.homing.home_button --out /home/bam/sim2real/src/sim2real/data/fivebar_home_button_replay_2026-11-12.json --workers 3

WHY powered at the real start with no unpowered settle (``settle_s`` 0): the real start IS a rest - the receipt's first reading, taken
with the boards stopped - and the sequence's first command went out on the next tick. An unpowered settle in the sim would move the start
wherever the twin's friction leaves it, which is a different question (recorded separately, ``unpowered_drift_deg``).

WHY both assemblies from the fold rest: the t1 start does not close on the real bench (it rests on the closure fold, where the export and
mirror assemblies meet), so which side of the fold the sim's loop closes on is not given by the reading; both are replayed and reported.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from robot_msgs.control import ServoCommand

from .geometry import C1, DRIVES, EXPORT, J1, J2, MIRROR
from .mujoco_plant import BAM_WS_SRC, MujocoRigPlant, bam_ws_path
from .plant import Start

REAL_JSON = Path(__file__).resolve().parents[2] / "data" / "fivebar_home_button_real_2026-11-12.json"
COMP_DIR = BAM_WS_SRC / "dev" / "bam_rack_twin" / "records" / "fivebar-bench"
# the home button's own packages and what bam_fivebar's bench model imports (pure Python over numpy + MuJoCo, loaded by path like the
# twin's: mujoco_plant's docstring has the WHY)
HOME_BUTTON_PATHS = (
    "dev/bam_fivebar_recovery",
    "core/bam_robot_descriptions/src",
    "core/mdp/agent/world_model/bam_aruco",
    "core/mdp/agent/actor/trajectory_generation/five_bar_kin_dyn/src",
)
J1_HOLD_CAP_NM = 7.0  # the procedures' J1 hold (procedures.HOLD_CAP_NM)
CONTROL_DT = 0.01
# What "lands where the real arm landed" means, per drive (deg): the real run's own repeatability on its last hold is ~0.2 deg
# (fivebar-real-night: repeat floor J2 0.16-0.21 / C1 0.18-0.19 deg), and the home button's own Reached is 0.06 rad = 3.4 deg. A PD hold
# rests up to Coulomb / kp short of its target (0.74 N.m / 22.9 N.m/rad = 1.9 deg on J2 at kp 144), on either side of it depending on
# the side it came from - so the end pose is judged at the home button's own reach, 3.4 deg, never tighter than what it promises.
END_TOLERANCE_DEG = math.degrees(0.06)


def home_button_path(src: Path = BAM_WS_SRC) -> None:
    import sys  # noqa: PLC0415

    bam_ws_path(src)
    for relative in HOME_BUTTON_PATHS:
        path = str(src / relative)
        if path not in sys.path:
            sys.path.append(path)


def available(src: Path = BAM_WS_SRC) -> bool:
    return REAL_JSON.is_file() and all((src / relative).is_dir() for relative in HOME_BUTTON_PATHS)


def load_real(path: Path = REAL_JSON) -> dict:
    return json.loads(Path(path).read_text())


@dataclass
class Reading:
    """bam_fivebar's ``BoardReading`` fields the home button reads (Craig rad, rad/s, N.m), axes (j2, c1)."""

    t_s: float
    position_rad: np.ndarray
    velocity_rad_s: np.ndarray
    torque_nm: np.ndarray
    mode: tuple = (0, 0)
    j1_rad: float = 0.0


@dataclass
class RigBoards:
    """``MujocoRigPlant`` behind bam_fivebar's ``Plant`` seam (``read`` / ``send([j2, c1])`` / ``step``) in the arm's Craig angles.

    A command is turned into the plant's ``ServoCommand`` (position, feed-forward, cap; None = limp); the plant itself applies the rest of
    what the rack runner sends (ilimit_scale 0, no velocity target). J1 holds where it started, at the procedures' J1 cap."""

    plant: MujocoRigPlant
    control_period_s: float = CONTROL_DT
    commands: list = field(default_factory=lambda: [None, None])
    j1_hold_rad: float = 0.0
    log: list = field(default_factory=list)

    def read(self) -> Reading:
        state = self.plant.state()
        position = dict(zip(state.name, state.position, strict=True))
        velocity = dict(zip(state.name, state.velocity, strict=True))
        effort = dict(zip(state.name, state.effort, strict=True))
        return Reading(t_s=float(self.plant.time), position_rad=np.array([position[J2], position[C1]]),
                       velocity_rad_s=np.array([velocity[J2], velocity[C1]]), torque_nm=np.array([effort[J2], effort[C1]]),
                       j1_rad=float(position[J1]))

    def send(self, commands) -> None:
        if len(commands) != 2:
            raise ValueError("one command per drive (j2, c1)")
        self.commands = list(commands)

    def step(self) -> Reading:
        position, feedforward, cap = [self.j1_hold_rad], [0.0], [J1_HOLD_CAP_NM]
        for command in self.commands:
            if command is None:
                position.append(math.nan), feedforward.append(0.0), cap.append(0.0)
                continue
            if (float(command.ilimit_scale), float(command.velocity_rad_s), float(command.kp_scale), float(command.kd_scale)) != (0.0, 0.0, 1.0, 1.0):
                raise ValueError("the home button's backend sends ilimit_scale 0, velocity 0 and unit gain scales; this adapter carries only that")
            position.append(float(command.position_rad))
            feedforward.append(float(command.feedforward_torque_nm))
            cap.append(float(command.maximum_torque_nm))
        self.plant.tick(ServoCommand(name=DRIVES, position=np.array(position), feedforward_effort=np.array(feedforward),
                                     max_effort=np.array(cap)), self.control_period_s)
        reading = self.read()
        self.log.append([reading.t_s, *np.degrees(reading.position_rad), *np.degrees(reading.velocity_rad_s), *reading.torque_nm])
        return reading


def craig_frame(plant: MujocoRigPlant) -> dict[str, float]:
    """The plant's ``frame`` (rad) that makes its positions the arm's Craig angles: ``CraigMap``'s offsets (its signs must be +1)."""
    bam_ws_path()
    from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415

    craig = CraigMap(plant.rig)
    for role in ("J2", "C1"):
        if craig.sign[role] != 1.0:
            raise ValueError(f"CraigMap gives {role} sign {craig.sign[role]}: the replay assumes Craig = URDF + offset")
    return {J1: 0.0, J2: float(craig.offset["J2"]), C1: float(craig.offset["C1"])}


def start_for(plant: MujocoRigPlant, craig_deg, branch: str, name: str) -> Start:
    """The Start (URDF link angles, J1 vertical) whose drives read ``craig_deg`` in the Craig frame; C1 on the turn the map holds."""
    frame = craig_frame(plant)
    j2 = math.radians(craig_deg[0]) - frame[J2]
    c1 = math.radians(craig_deg[1]) - frame[C1]
    c1 = (c1 + math.pi) % (2.0 * math.pi) - math.pi
    return Start(name=name, link_rad={J1: 0.0, J2: j2, C1: c1}, branch=branch)


def bench_and_comp(comp: str):
    """bam_rack_twin's ``bench_real`` and the run's comp model (``nominal`` or a mass-ID gravity_params file name)."""
    home_button_path()
    from bam_fivebar import massid  # noqa: PLC0415
    from bam_fivebar.bench import BENCH  # noqa: PLC0415
    from bam_fivebar.dynamics import ControllerModel  # noqa: PLC0415
    from bam_fivebar.gains_check import in_mode, real_assembly  # noqa: PLC0415

    bench = in_mode(real_assembly(BENCH), "vertical")
    if comp == "nominal":
        return bench, ControllerModel.for_bench(bench)
    return bench, massid.identified_model(bench, massid.load_gravity_parameters(COMP_DIR / comp))


def nearest_closed_pose(plant: MujocoRigPlant, start: Start, step_deg: float = 0.05) -> tuple[np.ndarray, dict]:
    """The closed pose on ``start.branch`` nearest ``start``'s drives, for a rest where the CAD's loop does not close exactly (the t1
    rest on the closure fold): from the nearest closable cell of the exporter's map, the drives walk straight toward the reading in
    ``step_deg`` steps, re-closing the loop each step, and stop at the last pose that closes. Returns (qpos, how far short it stopped)."""
    import json as _json  # noqa: PLC0415

    from .mujoco_plant import loop_maps, map_path  # noqa: PLC0415

    loops = _json.loads((Path(plant.rig.bundle.root) / "loops.json").read_text())
    loop_map = loop_maps(loops)[start.branch]
    target = (math.degrees(start.link_rad[J2]), math.degrees(start.link_rad[C1]))
    rows, cols = loop_map.rows_deg, loop_map.cols_deg
    cells = sorted(((float(rows[i]), float(cols[k])) for i in range(len(rows)) for k in range(len(cols)) if loop_map.rows[i][k] in ".#"),
                   key=lambda cell: math.hypot(cell[0] - target[0], cell[1] - target[1]))
    origin = (0.0, 0.0) if start.branch == EXPORT else tuple(loops["mirror_grids"][0]["seed"]["cell_deg"])
    for cell in cells[:200]:
        if map_path(loop_map, origin, cell) is None:
            continue
        try:
            q = plant._closed_pose(Start(name=start.name, link_rad={J1: start.link_rad[J1], J2: math.radians(cell[0]),
                                                                    C1: math.radians(cell[1])}, branch=start.branch))
        except ValueError:
            continue
        here = np.array(cell)
        span = float(np.hypot(*(np.array(target) - here)))
        for _ in range(int(math.ceil(span / step_deg))):
            nxt = here + (np.array(target) - here) * min(1.0, step_deg / max(float(np.hypot(*(np.array(target) - here))), 1e-12))
            moved = plant._continue(q, {"J2": math.radians(nxt[0]), "C1": math.radians(nxt[1])}, steps=1)
            if moved is None:
                break
            q, here = moved, nxt
        return q, {"from_cell_deg": list(cell), "reached_deg": here.round(4).tolist(),
                   "short_deg": (np.array(target) - here).round(4).tolist()}
    raise ValueError(f"start {start.name!r}: no closable cell on the {start.branch} map leads toward {target}")


def place(kind: str, run: dict, branch: str, *, cogging: bool = True, boards=None) -> tuple[MujocoRigPlant, Start, dict]:
    """``MujocoRigPlant`` reset to ``run``'s real start on ``branch``, positions in Craig. Where the CAD's loop does not close at the
    reading exactly, the nearest pose that does (``nearest_closed_pose``), and the returned note says how far short of the reading."""
    plant = MujocoRigPlant(kind, cogging=cogging, settle_s=0.0, boards=boards)
    start = start_for(plant, run["start_deg"], branch, f"{run['run']}:{branch}")
    note: dict = {"exact": True}
    try:
        plant.reset(start)
    except ValueError as error:
        import mujoco  # noqa: PLC0415

        plant._pose_data = mujoco.MjData(plant.rig.model)
        q, note = nearest_closed_pose(plant, start)
        note.update(exact=False, why=str(error))
        exact = plant._closed_pose
        plant._closed_pose = lambda _start, q=q: q.copy()
        try:
            plant.reset(start)
        finally:
            plant._closed_pose = exact
    plant.frame = craig_frame(plant)
    return plant, start, note


def unpowered_drift(kind: str, run: dict, branch: str, seconds: float = 2.0, **options) -> list[float]:
    """How far (Craig deg) the twin moves from the real start if left unpowered ``seconds`` (the real arm sat still there)."""
    plant, _, _ = place(kind, run, branch, **options)
    before = np.degrees([plant.state().position[1], plant.state().position[2]])
    plant.sim.step(seconds)
    after = np.degrees([plant.state().position[1], plant.state().position[2]])
    return (after - before).round(3).tolist()


def replay(run: dict, *, kind: str = "B0", branch: str = EXPORT, cogging: bool = True, boards=None) -> dict:
    """The home button on the MuJoCo rung from ``run``'s start: each sequence's steps (outcome, seconds, end Craig deg) and the end."""
    home_button_path()
    from bam_fivebar_recovery.backend import PlantBackend  # noqa: PLC0415
    from bam_fivebar_recovery.home import return_home  # noqa: PLC0415

    plant, start, placement = place(kind, run, branch, cogging=cogging, boards=boards)
    boards_seam = RigBoards(plant, j1_hold_rad=float(plant.state().position[0]))
    placed = np.degrees(boards_seam.read().position_rad).round(4).tolist()
    bench, comp = bench_and_comp(run["comp"])
    backend = PlantBackend(boards_seam, signs=(1.0, 1.0))
    out = {"run": run["run"], "kind": kind, "branch": branch, "cogging": cogging, "placed_deg": placed,
           "placed_assembly": plant.start_settled["settled_assembly"], "placement": placement}
    sequences: list[dict] = []
    try:
        record = return_home(backend, bench, comp, np.radians(run["home_deg"]), log=sequences.append)
        out.update(status="complete", end_deg=record["end_deg"], off_home_deg=record["off_home_deg"], path=record.get("path"),
                   start_kind=record["start"]["kind"], settled=record.get("settled"))
    except RuntimeError as error:
        out.update(status="failed", error=str(error), end_deg=np.degrees(backend.read().position).round(3).tolist())
    # each step's end pose from the tick log (the controller's events carry only times)
    log = np.asarray(boards_seam.log, dtype=float)
    clock = 0.0
    for sequence in sequences:
        for step in sequence["steps"]:
            clock += float(step["seconds"])
            k = int(np.argmin(np.abs(log[:, 0] - log[0, 0] + CONTROL_DT - clock))) if len(log) else 0
            step["end_deg"] = log[k, 1:3].round(3).tolist() if len(log) else None
            step["end_t_s"] = round(clock, 2)
    out["sequences"] = sequences
    out["seconds"] = round(float(plant.time), 2)
    out["trace"] = {"every_s": 0.05, "t": log[::5, 0].round(3).tolist(), "craig_deg": log[::5, 1:3].round(3).tolist(),
                    "torque_nm": log[::5, 5:7].round(3).tolist()} if len(log) else None
    out["boards"] = {role: {"kp": state.drive.config.kp, "kd": state.drive.config.kd, "ki": state.drive.config.ki,
                            "ilimit": state.drive.config.ilimit} for role, state in plant.sim.states.items()}
    return out


def compare(real: dict, sim: dict) -> list[dict]:
    """Step by step (matched by sequence and step name, in order): real vs sim outcome, seconds and end pose (Craig deg)."""
    rows = []
    sim_steps = [(s["sequence"], st) for s in sim.get("sequences", []) for st in s["steps"]]
    real_steps = [(s["sequence"], st) for s in real["sequences"] for st in s["steps"]]
    for index in range(max(len(sim_steps), len(real_steps))):
        r = real_steps[index] if index < len(real_steps) else (None, None)
        s = sim_steps[index] if index < len(sim_steps) else (None, None)
        row = {"index": index + 1, "real_step": r[1] and r[1]["step"], "sim_step": s[1] and s[1]["step"],
               "real_outcome": r[1] and r[1]["outcome"], "sim_outcome": s[1] and s[1]["outcome"],
               "real_s": r[1] and r[1]["seconds"], "sim_s": s[1] and s[1]["seconds"],
               "real_end_deg": r[1] and r[1]["end_deg"], "sim_end_deg": s[1] and s[1].get("end_deg")}
        if r[1] and s[1] and s[1].get("end_deg"):
            # the crank turns all the way round: the sim's C1 on the real reading's turn (fivebar_homed.home_offset's rule)
            sim_end = np.asarray(s[1]["end_deg"], dtype=float)
            sim_end[1] -= 360.0 * round((sim_end[1] - r[1]["end_deg"][1]) / 360.0)
            row["sim_end_deg"] = sim_end.round(3).tolist()
            row["sim_minus_real_deg"] = (sim_end - np.asarray(r[1]["end_deg"])).round(3).tolist()
        rows.append(row)
    return rows


def verdict(real: dict, sim: dict, tolerance_deg: float = END_TOLERANCE_DEG) -> dict:
    """Did the sim do what the real arm did: complete, the same sequences and steps (names, in order), and end within ``tolerance_deg``
    of the real end on each drive (the crank's on the nearest turn)?"""
    same_steps = [st["step"] for s in real["sequences"] for st in s["steps"]] == [st["step"] for s in sim.get("sequences", [])
                                                                                     for st in s["steps"]]
    off = None
    if sim.get("end_deg") is not None:
        off = np.asarray(sim["end_deg"], dtype=float) - np.asarray(real["end_deg"], dtype=float)
        off[1] = (off[1] + 180.0) % 360.0 - 180.0
        off = off.round(3).tolist()
    lands = off is not None and all(abs(v) <= tolerance_deg for v in off)
    return {"complete": sim.get("status") == "complete", "same_steps": bool(same_steps), "end_minus_real_deg": off,
            "tolerance_deg": round(tolerance_deg, 3), "lands": bool(lands),
            "pass": bool(sim.get("status") == "complete" and same_steps and lands)}


def branches_for(run: dict) -> tuple[str, ...]:
    """The assemblies a real start is replayed on: the export (working) one, and the mirror one too from a rest the real bench says does
    not close (the closure fold, where the two meet: module docstring)."""
    return (EXPORT, MIRROR) if run["start_kind"].startswith("does not close") else (EXPORT,)


def _job(args):
    run, branch, kind = args
    sim = replay(run, kind=kind, branch=branch)
    sim["verdict"] = verdict(run, sim)
    sim["steps"] = compare(run, sim)
    sim["unpowered_drift_deg"] = unpowered_drift(kind, run, branch)
    return sim


def main(argv=None) -> int:
    """Replay every real home run on B0 / B1 / B2 and write the comparison JSON the homing report reads."""
    import argparse  # noqa: PLC0415
    import time  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--models", nargs="*", default=["B0", "B1", "B2"])
    args = parser.parse_args(argv)
    t0 = time.time()
    real = load_real()
    jobs = [(run, branch, kind) for run in real["runs"] for branch in branches_for(run) for kind in args.models]
    if args.workers > 1:
        from multiprocessing import get_context  # noqa: PLC0415

        with get_context("fork").Pool(min(args.workers, 3)) as pool:
            replays = pool.map(_job, jobs, chunksize=1)
    else:
        replays = [_job(job) for job in jobs]

    def sha(path: Path) -> str:
        from sim2real.provenance import code_sha  # noqa: PLC0415 - WHY: a bare rev-parse stamped a dirty tree as a clean commit

        return code_sha(path)

    from .mujoco_plant import REAL_BOARD_RECORD  # noqa: PLC0415

    payload = {"schema": "sim2real_home_button_replay/1", "real": str(REAL_JSON.name), "board_record": REAL_BOARD_RECORD,
               "end_tolerance_deg": round(END_TOLERANCE_DEG, 3), "sim2real_sha": sha(Path(__file__).resolve().parents[4]),
               "bam_ws_sha": sha(BAM_WS_SRC.parent), "replays": replays,
               "real_runs": [{k: v for k, v in run.items() if k != "trace"} | {"trace": run["trace"]} for run in real["runs"]],
               "passed": sum(r["verdict"]["pass"] for r in replays), "total": len(replays), "seconds": round(time.time() - t0, 1)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload) + "\n")
    for r in replays:
        v = r["verdict"]
        print(f"{r['run']:32s} {r['branch']:6s} {r['kind']}  {r['status']:8s} end - real {v['end_minus_real_deg']} deg  "
              f"{'PASS' if v['pass'] else 'FAIL'}")
    print(f"{payload['passed']}/{payload['total']} pass, {payload['seconds']} s -> {args.out}")
    return 0 if payload["passed"] == payload["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["END_TOLERANCE_DEG", "REAL_JSON", "RigBoards", "available", "bench_and_comp", "compare", "craig_frame", "load_real", "replay",
           "branches_for", "start_for", "unpowered_drift", "verdict"]
