"""The homing bench on the kinematic rung: every procedure x backlash model (B0 / B1 / B2) x start, scored by robot_models' five
metrics. Writes one results JSON (the page and the leaderboard read it; nothing is recomputed there).

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 uv run --project /home/bam/sim2real --extra homing python -m sim2real.sim.homing.bench --out /tmp/homing.json --workers 3

The episode: the plant is reset to a start (links, where each motor sits in its gap, the power-up's hidden zero); the procedure plans
a robot_msgs ``JointCommandSequence``; the ``JointCommandSequenceController`` runs it tick by tick on the plant (10 ms, the rack's
host period); the procedure observes what it measured and returns a ``HomingResult``. Truth is read only to score.

Starts: 64 scrambled-Sobol poses of the export assembly's free map (J1, J2, C1 uniform inside the exact stops, 0.5 deg in; each
motor anywhere in its gap; each power-up zero anywhere in a turn), plus the named rests.

WHY a stored table per environment from press_reverse's fit at home (``identify_backlash``): B's ``home()`` reads the table its
calibration wrote, so single_touch and two_level_touch get that table, measured on the same plant, never the hidden truth.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from robot_models.homing.metrics import EpisodeRecord, JointOutcome, StallCheck, scorecard
from robot_models.homing.protocols import Phase, Prior
from robot_msgs.control import JointCommandSequenceController

from .geometry import BUNDLE_SHA, C1, DRIVES, EXPORT, J1, J2, MIRROR, ROLE, FivebarGeometry
from .plant import HIDDEN_GAP_ARCMIN, KinematicStopPlant, PlantTrip, Start, hidden_backlash
from .procedures import PROCEDURES, HomingRefused, PressReverse, home_cad, identify_backlash
from .recover import RECOVER_PREFIX_NAME as RECOVER
from .recover import recover_first

DT = 0.01
RUNG = "kinematic"
GATE_DEG = 0.01  # the kinematic rung's zero gate (report section 5)
MODELS = ("B0", "B1", "B2")
SOBOL_STARTS = 64
SOBOL_SEED = 20261112
EDGE_DEG = 0.5
MAX_EPISODE_S = 600.0
# 2026-11-11 MuJoCo rests (bam_ws reports/media/homing-sim-2026-11-11/fivebar_bundle: start_link_rad after the unpowered drop)
BOWL_RAD = {J1: 0.13823765845473987, J2: -0.10625451439579624, C1: 2.7879602093540417}
OTHER_RAD = {J1: 0.13667560191075892, J2: 0.1911302622427555, C1: 1.9763605680118146}


def prior_for(geometry: FivebarGeometry, table=None) -> Prior:
    return Prior(stops=geometry.cad, joints=DRIVES, seek_side={j: +1 for j in DRIVES}, table=table,
                 caps_nm={J1: 10.0, J2: 10.0, C1: 7.0})


# ---------------------------------------------------------------------------------------------------------------- starts


def _inside(geometry: FivebarGeometry, q: dict, branch: str = EXPORT) -> bool:
    edge = math.radians(EDGE_DEG)
    for joint in DRIVES:
        lo = geometry.stop(joint, -1, q[J2] if joint == C1 else 0.0)
        hi = geometry.stop(joint, +1, q[J2] if joint == C1 else 0.0)
        if not (lo + edge <= q[joint] <= hi - edge):
            return False
    return not geometry.loop_blocked(q[J2], q[C1], branch)


def sobol_starts(geometry: FivebarGeometry, n: int = SOBOL_STARTS, seed: int = SOBOL_SEED) -> list[Start]:
    from scipy.stats import qmc  # noqa: PLC0415

    sampler = qmc.Sobol(d=9, scramble=True, seed=seed)
    box = {j: (geometry.cad.q_rad(j, -1), geometry.cad.q_rad(j, +1)) for j in DRIVES}
    out = []
    for row in sampler.random(1024):
        q = {j: box[j][0] + row[i] * (box[j][1] - box[j][0]) for i, j in enumerate(DRIVES)}
        if not _inside(geometry, q):
            continue
        out.append(Start(f"sobol-{len(out):02d}", q,
                         {j: 2.0 * row[3 + i] - 1.0 for i, j in enumerate(DRIVES)},
                         {j: (2.0 * row[6 + i] - 1.0) * math.pi for i, j in enumerate(DRIVES)}))
        if len(out) == n:
            return out
    raise RuntimeError(f"only {len(out)} free Sobol starts in 1024 draws")


def _first_free(geometry, q7, q6_from, step, branch=EXPORT):
    q6 = q6_from
    for _ in range(4000):
        q = {J1: 0.0, J2: q6, C1: q7}
        if _inside(geometry, q, branch):
            return q6
        q6 += step
    raise RuntimeError("no free pose on the scan")


def named_rests(geometry: FivebarGeometry, prior: Prior) -> list[Start]:
    """The named rests (what the recovery code and the 11-11 page call them), each with a fixed power-up zero per drive."""
    stop = lambda joint, side, q6=0.0: geometry.stop(joint, side, q6)  # noqa: E731
    home = home_cad(prior)
    offsets = {J1: 0.31, J2: -1.7, C1: 2.6}  # arbitrary power-up zeros: nothing may assume the encoder reads the joint
    edge = math.radians(0.05)
    fold_q6 = _first_free(geometry, 0.0, math.radians(-60.0), math.radians(0.05))
    mirror = geometry.maps[MIRROR]
    row = int(np.argmin(np.abs(mirror.rows_deg - (-30.0))))
    free = [k for k, ch in enumerate(mirror.rows[row]) if ch == "."]
    flipped_q7 = math.radians(float(mirror.cols_deg[free[len(free) // 2]]))
    rests = [
        ("bowl", BOWL_RAD, "the real arm's rest before tview_home_044823 (04:48), dropped unpowered in MuJoCo (2026-11-11 page)"),
        ("other", OTHER_RAD, "the CAD export's assembly dropped unpowered in MuJoCo (2026-11-11 page)"),
        ("export_pose", {J1: 0.0, J2: 0.0, C1: 0.0}, "the CAD export pose (every joint 0)"),
        ("home", home, "tview's home (0, 0, 0.371 rev): J2 0, C1 92.48 deg CAD"),
        ("on_seek_stops", {J1: stop(J1, 1) - edge, J2: stop(J2, 1) - edge, C1: stop(C1, 1, stop(J2, 1)) - edge},
         "every drive resting 0.05 deg off the stop it seeks (a power-up after a stall)"),
        ("lower_corner", {J1: stop(J1, -1) + edge, J2: stop(J2, -1) + edge, C1: stop(C1, -1, stop(J2, -1)) + edge},
         "every drive resting on its other stop: the farthest seek"),
        ("fold", {J1: 0.0, J2: fold_q6, C1: 0.0},
         f"the loop's toggle (loops.json: J2 cannot close below -57 deg with C1 at 0): J2 {math.degrees(fold_q6):.2f} deg, C1 0"),
        ("flipped_crank", {J1: 0.0, J2: math.radians(float(mirror.rows_deg[row])), C1: flipped_q7},
         "the crank flipped (the mirrored assembly, loops.json mirror_grids): J2 -30 deg, C1 mid its free range there"),
    ]
    out = []
    for name, q, why in rests:
        branch = MIRROR if name == "flipped_crank" else EXPORT
        out.append(Start(name, dict(q), {j: 0.0 for j in DRIVES}, offsets, branch))
        NAMED_WHY[name] = why
    return out


NAMED_WHY: dict[str, str] = {}


# ---------------------------------------------------------------------------------------------------------------- one episode


def run_phase(plant: KinematicStopPlant, sequence, *, dt: float = DT, limit_s: float = MAX_EPISODE_S) -> Phase:
    controller = JointCommandSequenceController(sequence)
    state = plant.state()
    log = {"t": [], "position": [], "velocity": [], "effort": [], "defines": [], "events": [], "step": [],
           "plant_offset": len(plant.log["t"]) - 1}
    while controller.status == "running" and plant.time < limit_s:
        command, defines = controller.tick(state, dt)
        log["t"].append(plant.time)
        log["position"].append([float(x) for x in state.position])
        log["velocity"].append([float(x) for x in state.velocity])
        log["effort"].append([float(x) for x in state.effort])
        log["defines"].append(dict(defines))
        log["events"].append(len(controller.events))
        log["step"].append(controller.step_index)
        try:
            state = plant.tick(command, dt, defines)
        except PlantTrip as trip:
            # WHY a phase status and not a crash (2026-11-13, homing pass 6): a plant's controlled stop (the MuJoCo runaway check) ends the
            # episode as the real plant's trips do (real_plant.run_phase_real) - an outcome, scored as not finished
            step = sequence.steps[min(controller.step_index, len(sequence.steps) - 1)].name
            return Phase(sequence, "tripped", f"{trip} in step {step!r}", tuple(controller.events), log)
    status, message = controller.status, controller.message
    if status == "running":
        status, message = "aborted", f"bench limit {limit_s} s"
    return Phase(sequence, status, message, tuple(controller.events), log)


@dataclass
class Episode:
    record: EpisodeRecord
    result: object | None
    phases: list
    notes: dict


def make_procedure(name: str):
    """A leaderboard procedure by name; ``recover_first+<name>`` puts the blind recovery in front (recover.py)."""
    if name.startswith(RECOVER):
        return recover_first(name.removeprefix(RECOVER))
    return PROCEDURES[name]()


def inner_name(name: str) -> str:
    return name.removeprefix(RECOVER)


def run_episode(name: str, plant: KinematicStopPlant, start: Start, prior: Prior, environment: str, procedure=None) -> Episode:
    """One episode on any ``HomingPlant`` (the kinematic plant or the MuJoCo rung's); ``procedure`` defaults to ``make_procedure(name)``."""
    procedure = make_procedure(name) if procedure is None else procedure
    plant.reset(start)
    phases, outcome = [], "done"
    while (sequence := procedure.plan(prior, phases)) is not None:
        phase = run_phase(plant, sequence)
        phases.append(phase)
        if phase.status != "done":
            outcome = f"{phase.status}: {phase.message}"
            break
    result, finished = None, outcome == "done"
    if finished:
        try:
            result = procedure.observe(prior, phases)
        except HomingRefused as error:
            outcome, finished = f"refused: {error}", False
    truth = plant.truth()
    stalls = []
    for phase_index, tick, joint, side in procedure.references if finished else []:
        k = phases[phase_index].log["plant_offset"] + tick
        link = plant.log["link"][k][DRIVES.index(joint)]
        stalls.append(StallCheck(joint, side, math.degrees(link), math.degrees(prior.stops.q_rad(joint, side))))
    joints = []
    for joint in DRIVES:
        model = plant.backlash[joint]
        zero_error = gap = None
        if result is not None and result.zero(joint) is not None:
            zero_error = math.degrees(result.zero(joint).offset_rad - truth["true_offset_rad"][joint])
            entry = result.backlash.get(joint)
            if entry is not None and entry.gap_observable:
                gap = math.degrees(entry.model.gap_rad)
        joints.append(JointOutcome(joint, zero_error, gap, math.degrees(model.gap_rad)))
    record = EpisodeRecord(name, environment, start.name, finished, outcome, plant.time if finished else None,
                           tuple(stalls), tuple(joints))
    notes = dict(procedure.notes)
    # the flank-contact log, summarised: how long each drive pressed a loop contact (the exporter's map), never a drive stop
    loop_s = {ROLE[j]: round(DT * sum(1 for row in plant.log["touching"] if row[i] == "loop"), 3) for i, j in enumerate(DRIVES)}
    if any(loop_s.values()):
        notes["loop_contact_s"] = loop_s
    if not finished:
        last = plant.log["link"][-1]
        notes["ended_at_deg"] = {ROLE[j]: round(math.degrees(last[i]), 3) for i, j in enumerate(DRIVES)}
        notes["ended_touching"] = {ROLE[j]: plant.log["touching"][-1][i] for i, j in enumerate(DRIVES)}
    return Episode(record, result, phases, notes)


def calibrate(geometry: FivebarGeometry, model: str, start: Start):
    """identify_backlash on this environment: press_reverse's run from ``start``, its fit's table (B's calibration verb)."""
    plant = KinematicStopPlant(geometry, hidden_backlash(model))
    prior = prior_for(geometry)
    procedure = PressReverse()
    plant.reset(start)
    phase = run_phase(plant, procedure.plan(prior, []))
    if phase.status != "done":
        raise RuntimeError(f"calibration run on {model} did not finish: {phase.message}")
    return identify_backlash(procedure, prior, [phase]), plant.time


# ---------------------------------------------------------------------------------------------------------------- the bench


def _job(args):
    name, model, start, table_dict, root = args
    from robot_models.homing.types import BacklashTable  # noqa: PLC0415

    geometry = _GEOMETRY.get(root) or _GEOMETRY.setdefault(root, FivebarGeometry(root))
    table = BacklashTable.from_dict(table_dict) if table_dict is not None else None
    plant = KinematicStopPlant(geometry, hidden_backlash(model))
    uses_table = inner_name(name) in ("single_touch", "two_level_touch")
    episode = run_episode(name, plant, start, prior_for(geometry, table if uses_table else None), f"{RUNG} · {model}")
    return model, name, start.name, episode.record.to_dict(), episode.notes


_GEOMETRY: dict = {}


def git_sha(path: Path) -> str:
    try:
        sha = subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                               text=True, check=True).stdout.strip()
        return sha.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def trace_of(geometry, model, name, start, prior) -> dict:
    """One episode's per-tick truth for the page's figure: links, motors, efforts and step names."""
    plant = KinematicStopPlant(geometry, hidden_backlash(model))
    episode = run_episode(name, plant, start, prior, f"{RUNG} · {model}")
    phase = episode.phases[0]
    steps = [s.name for s in phase.sequence.steps]
    every = 5
    return {"procedure": name, "model": model, "start": start.name,
            "t": [round(t, 3) for t in plant.log["t"][::every]],
            "link_deg": np.degrees(np.array(plant.log["link"])).round(4)[::every].tolist(),
            "motor_deg": np.degrees(np.array(plant.log["motor"])).round(4)[::every].tolist(),
            "effort_nm": np.array(plant.log["effort"]).round(3)[::every].tolist(),
            "step": ([0] + phase.log["step"])[::every], "steps": steps,  # the plant log has the reset row first
            "events": [(e.index, e.name, e.outcome, round(e.started, 3), round(e.finished, 3)) for e in phase.events],
            "sequence": phase.sequence.to_dict()}


EPISODE_COLUMNS = ("start", "finished", "outcome", "time_s", "stalls [joint, side, link_deg, cad_deg]",
                   "joints [joint, zero_error_deg, gap_identified_deg, gap_truth_deg]")


def _r(value, digits=7):
    return None if value is None else round(float(value), digits)


def compact(record: dict) -> list:
    """An EpisodeRecord dict as one short row (EPISODE_COLUMNS); ``expand`` gives the record back (degrees to 1e-7)."""
    return [record["start"], record["finished"], record["outcome"], _r(record["time_s"], 3),
            [[s["joint"], s["side"], _r(s["link_deg"]), _r(s["cad_deg"])] for s in record["stalls"]],
            [[j["joint"], _r(j["zero_error_deg"]), _r(j["gap_identified_deg"]), _r(j["gap_truth_deg"])] for j in record["joints"]]]


def expand(row: list, procedure: str, environment: str) -> EpisodeRecord:
    start, finished, outcome, time_s, stalls, joints = row
    return EpisodeRecord(procedure, environment, start, finished, outcome, time_s,
                         tuple(StallCheck(*s) for s in stalls), tuple(JointOutcome(*j) for j in joints))


RULING = ("2026-11-12 coordinator: assembly-mode starts (flipped_crank, any mirror start) are judged on the MuJoCo rung; the kinematic "
          "rung's reliability gate is 100 % over working-assembly starts; the strict xfail test_recover_first_homes_from_the_flipped_crank "
          "stays as the kinematic record.")
# The coordinator's ruling (2026-11-12, the decision report's "MuJoCo proves dynamics"): a start on the mirrored assembly (the flipped
# crank, any start whose branch is ``mirror``) is an assembly-mode start, judged on the MuJoCo rung; the kinematic rung's reliability gate is
# 100 % over the working-assembly starts only. WHY: the kinematic plant has no gravity, so nothing can carry the loop across the toggle
# between the two assemblies; a kinematic verdict on those starts measures the plant, not the procedure. Its record stays (the strict xfail
# test_recover_first_homes_from_the_flipped_crank); its scorecard is kept apart and labelled, never dropped.
WORKING, ASSEMBLY_MODE = "working_assembly", "assembly_mode"
JUDGED_ON = {"kinematic": {WORKING: "kinematic", ASSEMBLY_MODE: "MuJoCo"}, "mujoco": {WORKING: "MuJoCo", ASSEMBLY_MODE: "MuJoCo"}}


def scope_of(branch: str) -> str:
    return ASSEMBLY_MODE if branch == MIRROR else WORKING


def split_scorecards(episodes: dict, starts: list[dict], rung: str, gate_deg: float) -> dict:
    """``{scope: {model: {procedure: scorecard}}}`` over the working-assembly and the assembly-mode starts (the ruling above), from the
    compact episode rows; each card carries ``judged_on`` (where that scope's verdict is taken) and its start count."""
    scope = {start["name"]: scope_of(start["branch"]) for start in starts}
    out: dict = {WORKING: {}, ASSEMBLY_MODE: {}}
    for model, by_name in episodes.items():
        for name, rows in by_name.items():
            for which in (WORKING, ASSEMBLY_MODE):
                picked = [expand(row, name, f"{rung} · {model}") for row in rows if scope[row[0]] == which]
                if not picked:
                    continue
                card = scorecard(picked, gate_deg=gate_deg)
                card["judged_on"] = JUDGED_ON[rung][which]
                card["starts"] = sorted(r.start for r in picked) if which == ASSEMBLY_MODE else len(picked)
                if card["judged_on"] != rung.replace("mujoco", "MuJoCo"):
                    card["reliability_gate_pass"] = None  # not this rung's verdict (the ruling)
                out[which].setdefault(model, {})[name] = card
    return out


def run_bench(*, procedures=tuple(PROCEDURES), models=MODELS, n_sobol: int = SOBOL_STARTS, workers: int = 3,
              root: Path | None = None) -> dict:
    t0 = time.time()
    geometry = FivebarGeometry(root) if root else FivebarGeometry()
    prior = prior_for(geometry)
    starts = sobol_starts(geometry, n_sobol) + named_rests(geometry, prior)
    geometry.save()
    found = geometry.found_stop_map()
    # warm the C1 table along every J2 a start or a seek can visit (each worker reads the disk cache)
    for q6 in np.arange(geometry.cad.q_rad(J2, -1), geometry.cad.q_rad(J2, 1) + 0.01, math.radians(0.5)):
        geometry.stop(C1, -1, float(q6))
        geometry.stop(C1, 1, float(q6))
    geometry.save()
    home_start = next(s for s in starts if s.name == "home")
    calibration = {}
    for model in models:
        table, seconds = calibrate(geometry, model, home_start)
        calibration[model] = {"table": table.to_dict(), "seconds": seconds,
                              "gap_deg": {j: math.degrees(table.get(j).model.gap_rad) for j in DRIVES},
                              "compliance_rad_per_nm": {j: table.get(j).model.compliance_rad_per_nm for j in DRIVES}}
    jobs = [(name, model, start, calibration[model]["table"], str(geometry.root)) for model in models for name in procedures
            for start in starts]
    if workers > 1:
        import multiprocessing  # noqa: PLC0415

        with multiprocessing.get_context("fork").Pool(min(workers, 3)) as pool:
            outputs = pool.map(_job, jobs, chunksize=4)
    else:
        outputs = [_job(job) for job in jobs]
    episodes: dict = {}
    notes: dict = {}
    for model, name, start, record, note in outputs:
        episodes.setdefault(model, {}).setdefault(name, []).append(compact(record))
        if note:
            notes.setdefault(model, {}).setdefault(name, {})[start] = note
    cards = {}
    for model, by_name in episodes.items():
        for name, records in by_name.items():
            parsed = [expand(row, name, f"{RUNG} · {model}") for row in records]
            cards.setdefault(model, {})[name] = scorecard(parsed, gate_deg=GATE_DEG)
    stops = []
    for stop in geometry.cad.sides:
        stops.append({"joint": stop.joint, "role": ROLE.get(stop.joint, stop.joint), "side": stop.side,
                      "cad_deg": stop.q_deg, "found_deg": found.get(stop.joint, stop.side).q_deg,
                      "c1_at_j2_stop_deg": (math.degrees(geometry.stop(C1, stop.side, geometry.stop(J2, 1 if stop.side > 0 else -1)))
                                            if stop.joint == C1 else None),
                      "pair": list(stop.pair)})
    traces = [trace_of(geometry, model, "tview_v2", next(s for s in starts if s.name == "bowl"), prior) for model in ("B2",)]
    traces.append(trace_of(geometry, "B2", "press_reverse", next(s for s in starts if s.name == "bowl"),
                           prior_for(geometry)))
    return {
        "schema": "sim2real_homing_bench/1",
        "rung": RUNG,
        "bundle_sha": BUNDLE_SHA,
        "bundle_root": str(geometry.root),
        "hardstops_sha256": geometry.hardstops_sha256,
        "loops_sha256": geometry.loops_sha256,
        "sim2real_sha": git_sha(Path(__file__).resolve().parents[4]),
        "robot_models_sha": git_sha(Path("/home/bam/robot_models")),
        "dt_s": DT,
        "gate_deg": GATE_DEG,
        "hidden_gap_arcmin": HIDDEN_GAP_ARCMIN,
        "models": list(models),
        "procedures": list(procedures),
        "starts": [{"name": s.name, "branch": s.branch, "link_deg": {j: math.degrees(v) for j, v in s.link_rad.items()},
                    "why": NAMED_WHY.get(s.name, "Sobol")} for s in starts],
        "stops": stops,
        "calibration": calibration,
        "scorecards": cards,
        "scorecards_by_scope": split_scorecards(episodes, [{"name": s.name, "branch": s.branch} for s in starts], RUNG, GATE_DEG),
        "ruling": RULING,
        "episode_columns": list(EPISODE_COLUMNS),
        "episodes": episodes,
        "notes": notes,
        "traces": traces,
        "seconds": time.time() - t0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--sobol", type=int, default=SOBOL_STARTS)
    parser.add_argument("--procedures", nargs="*", default=list(PROCEDURES))
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--recover-first", action="store_true", help="put the blind recovery in front of every procedure (recover.py)")
    parser.add_argument("--rescore", type=Path, help="add the ruling's working / assembly-mode split to this results JSON (no episode is "
                        "re-run: the split is a denominator over the stored episodes) and write it to --out")
    args = parser.parse_args(argv)
    if args.rescore:
        results = json.loads(args.rescore.read_text())
        results["scorecards_by_scope"] = split_scorecards(results["episodes"], results["starts"], results["rung"], results["gate_deg"])
        results["ruling"] = RULING
        args.out.write_text(json.dumps(results))
        for name, card in results["scorecards_by_scope"][WORKING].get("B2", {}).items():
            print(f"B2 working assembly {name:34s} rel {card['reliability_pct']:6.1f}%  gate {card['reliability_gate_pass']}")
        return 0
    procedures = [RECOVER + inner_name(p) for p in args.procedures] if args.recover_first else args.procedures
    results = run_bench(procedures=tuple(procedures), models=tuple(args.models), n_sobol=args.sobol,
                        workers=min(args.workers, 3))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results))
    for model, by_name in results["scorecards_by_scope"][WORKING].items():
        for name, card in by_name.items():
            print("working assembly", end=" ")
            print(f"{model} {name:20s} rel {card['reliability_pct']:6.1f}%  any {card['any_start_pct']:6.1f}%  "
                  f"zero p95 {card['joint_angle_error_deg']}  gap {card['backlash_error_deg']}  t {card['time_to_home_s']}")
    print(f"{results['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
