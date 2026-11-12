"""The homing bench on the MuJoCo rung: the same procedures (each behind recover_first) x B0 / B1 / B2 x the starts, on bam_fb_test_rig's
v11 twin with gravity (``mujoco_plant.MujocoRigPlant``), scored by robot_models' five metrics. Writes one results JSON in the kinematic
bench's schema (the page, the leaderboard and the W&B logger read either).

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra homing --extra sim python -m sim2real.sim.homing.mujoco_bench --out /tmp/homing_mujoco.json --workers 3

What differs from the kinematic bench, and why:

* **Starts.** The 8 named rests (the flipped crank included) plus the first ``--sobol`` (default 8) of the kinematic bench's 64 Sobol
  starts - the same draws, so a start means the same pose on both rungs. Each is placed on its assembly and then settled unpowered
  (``mujoco_plant``); the settled pose and its assembly are recorded per start. WHY fewer Sobol starts: an episode is 40-140 s of 0.25 ms
  physics (~0.3 s wall per simulated second); the named rests carry the assembly-mode and edge cases the gate is about.
* **Gates** (the brief): zero error within 0.1 deg of the kinematic result (``ZERO_VS_KINEMATIC_DEG``, against the kinematic rung's
  working-assembly p95 for the same procedure and model), reliability 100 % over every start including the flipped crank.
* **The stored table** for single_touch and two_level_touch is identified on this plant the kinematic bench's way (plain press_reverse
  from ``home``); when that run cannot finish under gravity there is no table, and the two procedures run with none (``calibration``
  says why) - never the hidden truth, never the kinematic rung's table.
* **The recovery's landing.** Every episode records where the links were at the end of each ``recover:`` step against the v11
  references (J2's upper stop, C1's upper stop at that J2): the brief's "do stalls 2-6 land on the v11 J2 stop and C1 contact".
* ``--timed-recovery`` adds the DIAGNOSTIC ``recover_first(timed)+<name>`` rows: the same prefix with an ``Elapsed`` alternative on its
  two ``Reached`` steps (3 and 7), so a step whose reach the PD's gravity sag never meets still hands over. It answers "would the
  procedure home if the prefix got through?"; it is not blind_recovery and never stands in for it on the leaderboard.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import replace
from pathlib import Path

from robot_models.homing.metrics import scorecard
from robot_msgs.control import Elapsed, Reached

from .bench import (
    EPISODE_COLUMNS,
    NAMED_WHY,
    WORKING,
    compact,
    expand,
    git_sha,
    inner_name,
    named_rests,
    prior_for,
    run_episode,
    run_phase,
    sobol_starts,
    split_scorecards,
)
from .geometry import BUNDLE_SHA, C1, DRIVES, J2, ROLE, FivebarGeometry
from .mujoco_plant import BACKLASH_METHOD, BAM_WS_SRC, MujocoRigPlant
from .plant import HIDDEN_GAP_ARCMIN
from .procedures import PROCEDURES, PressReverse, identify_backlash
from .recover import PREFIX, RECOVER_PREFIX_NAME, RecoverFirst

RUNG = "mujoco"
GATE_DEG = 0.1  # the MuJoCo rung's any-start gate (report section 5); the brief's comparison gate is ZERO_VS_KINEMATIC_DEG
ZERO_VS_KINEMATIC_DEG = 0.1
MODELS = ("B0", "B1", "B2")
SOBOL_STARTS = 8
TIMED = "recover_first(timed)+"
TIMED_EXTRA_S = 6.0  # the diagnostic's Elapsed: a 15 deg move at 0.15 rad/s takes 1.75 s; 6 s is past any reach that is going to happen
KINEMATIC_JSON = Path(__file__).resolve().parents[2] / "data" / "homing_fivebar_kinematic_recover_first_2026-11-12.json"


class TimedRecoverFirst(RecoverFirst):
    """DIAGNOSTIC (module docstring): recover_first with an Elapsed alternative on its Reached steps."""

    def __post_init__(self):
        super().__post_init__()
        self.name = TIMED + self.inner.name

    def plan(self, prior, so_far):
        sequence = super().plan(prior, so_far)
        if sequence is None:
            return None
        steps = []
        for step in sequence.steps:
            if step.name.startswith(PREFIX) and any(isinstance(c, Reached) for c in step.done_when):
                step = replace(step, done_when=tuple(step.done_when) + (Elapsed(duration=TIMED_EXTRA_S),))
            steps.append(step)
        return replace(sequence, steps=tuple(steps))


def make(name: str):
    if name.startswith(TIMED):
        return TimedRecoverFirst(inner=PROCEDURES[name.removeprefix(TIMED)]())
    from .bench import make_procedure  # noqa: PLC0415

    return make_procedure(name)


def recovery_landing(plant: MujocoRigPlant, phase, geometry: FivebarGeometry) -> list[dict]:
    """Where the links were when each ``recover:`` step ended, against the v11 references (degrees)."""
    out = []
    offset = phase.log["plant_offset"]
    j2_stop = geometry.stop(J2, +1)
    for event in phase.events:
        name = phase.sequence.steps[event.index].name
        if not name.startswith(PREFIX):
            continue
        k = offset + int(round(event.finished / 0.01))
        k = min(k, len(plant.log["link"]) - 1)
        link = dict(zip(DRIVES, plant.log["link"][k], strict=True))
        c1_stop = geometry.stop(C1, +1, link[J2])
        out.append({"step": event.index + 1, "name": name.removeprefix(PREFIX), "outcome": event.outcome,
                    "t_s": round(event.finished, 3), "J2_deg": round(math.degrees(link[J2]), 4), "C1_deg": round(math.degrees(link[C1]), 4),
                    "J2_minus_stop_deg": round(math.degrees(link[J2] - j2_stop), 4),
                    "C1_minus_stop_deg": round(math.degrees(link[C1] - c1_stop), 4),
                    "touching": dict(zip((ROLE[j] for j in DRIVES), plant.log["touching"][k], strict=True))})
    return out


def run_one(name: str, plant: MujocoRigPlant, start, prior, geometry, environment: str):
    episode = run_episode(name, plant, start, prior, environment, procedure=make(name))
    if episode.phases:
        episode.notes["recovery_landing"] = recovery_landing(plant, episode.phases[0], geometry)
    episode.notes["start"] = plant.start_settled
    return episode


def trace_of(geometry: FivebarGeometry, model: str, name: str, start, every: int = 5) -> dict:
    """One episode's per-tick truth for the page's figure: links, motor setpoints (the true motor angle each command asked for), board
    torques and step names, every ``every`` control ticks."""
    import numpy as np  # noqa: PLC0415

    plant = MujocoRigPlant(model)
    episode = run_one(name, plant, start, prior_for(geometry), geometry, f"{RUNG} · {model}")
    phase = episode.phases[0]
    setpoint = np.array(plant.log["setpoint"], dtype=float)
    return {"procedure": name, "model": model, "start": start.name, "outcome": episode.record.outcome,
            "t": [round(t, 3) for t in plant.log["t"][::every]],
            "link_deg": np.degrees(np.array(plant.log["link"])).round(4)[::every].tolist(),
            "setpoint_deg": [[None if math.isnan(v) else round(v, 4) for v in row] for row in np.degrees(setpoint)[::every].tolist()],
            "effort_nm": np.array(plant.log["effort"]).round(3)[::every].tolist(),
            "step": ([0] + phase.log["step"])[::every], "steps": [s.name for s in phase.sequence.steps],
            "events": [(e.index, e.name, e.outcome, round(e.started, 3), round(e.finished, 3)) for e in phase.events],
            "recovery_landing": episode.notes.get("recovery_landing"), "start_settled": plant.start_settled}


def calibrate(geometry: FivebarGeometry, model: str, start):
    """identify_backlash on this plant (the kinematic bench's ``calibrate``): plain press_reverse from ``start``."""
    plant = MujocoRigPlant(model)
    prior = prior_for(geometry)
    procedure = PressReverse()
    plant.reset(start)
    phase = run_phase(plant, procedure.plan(prior, []))
    if phase.status != "done":
        return None, {"seconds": plant.time, "failed": f"{phase.status}: {phase.message}", "start": plant.start_settled}
    table = identify_backlash(procedure, prior, [phase])
    return table, {"seconds": plant.time, "table": table.to_dict(),
                   "gap_deg": {j: math.degrees(table.get(j).model.gap_rad) for j in DRIVES}, "start": plant.start_settled}


_GEOMETRY: dict = {}


def _job(args):
    name, model, start, table_dict, root, cogging = args
    from robot_models.homing.types import BacklashTable  # noqa: PLC0415

    geometry = _GEOMETRY.get(root) or _GEOMETRY.setdefault(root, FivebarGeometry(root))
    table = BacklashTable.from_dict(table_dict) if table_dict is not None else None
    plant = MujocoRigPlant(model, cogging=cogging)
    uses_table = inner_name(name.replace(TIMED, RECOVER_PREFIX_NAME)) in ("single_touch", "two_level_touch")
    t0 = time.time()
    try:
        episode = run_one(name, plant, start, prior_for(geometry, table if uses_table else None), geometry, f"{RUNG} · {model}")
    except Exception as error:  # a crash is an outcome, recorded (never a silent drop from the denominator)
        from robot_models.homing.metrics import EpisodeRecord, JointOutcome  # noqa: PLC0415

        record = EpisodeRecord(name, f"{RUNG} · {model}", start.name, False, f"crashed: {type(error).__name__}: {error}", None, (),
                               tuple(JointOutcome(j, None, None, math.degrees(plant.backlash[j].gap_rad)) for j in DRIVES))
        return model, name, start.name, record.to_dict(), {"crash": repr(error)}, time.time() - t0
    return model, name, start.name, episode.record.to_dict(), episode.notes, time.time() - t0


def kinematic_reference(path: Path = KINEMATIC_JSON) -> dict:
    """The kinematic rung's working-assembly scorecards for the same procedures (the brief's 0.1 deg comparison)."""
    if not path.is_file():
        return {}
    results = json.loads(path.read_text())
    by_scope = results.get("scorecards_by_scope") or split_scorecards(results["episodes"], results["starts"], "kinematic",
                                                                       results["gate_deg"])
    return {"path": str(path), "sim2real_sha": results.get("sim2real_sha"), "cards": by_scope[WORKING]}


def verdicts(cards: dict, reference: dict) -> dict:
    """Per (model, procedure): the brief's two MuJoCo gates, each with its numbers."""
    out = {}
    for model, by_name in cards.items():
        for name, card in by_name.items():
            ref = (reference.get("cards", {}).get(model, {}).get(name.replace(TIMED, RECOVER_PREFIX_NAME)) or {})
            kin = ref.get("joint_angle_error_deg")
            mine = card.get("joint_angle_error_deg")
            zero_ok = None if (kin is None or mine is None) else bool(mine <= kin + ZERO_VS_KINEMATIC_DEG)
            out.setdefault(model, {})[name] = {
                "reliability_pct": card["reliability_pct"], "reliability_gate_pass": bool(card["reliability_pct"] == 100.0),
                "zero_p95_deg": mine, "kinematic_zero_p95_deg": kin, "zero_vs_kinematic_pass": zero_ok,
                "pass": bool(card["reliability_pct"] == 100.0 and zero_ok is True)}
    return out


def run_bench(*, procedures, models=MODELS, n_sobol: int = SOBOL_STARTS, workers: int = 3, cogging: bool = True,
              root: Path | None = None) -> dict:
    t0 = time.time()
    geometry = FivebarGeometry(root) if root else FivebarGeometry()
    prior = prior_for(geometry)
    starts = named_rests(geometry, prior) + sobol_starts(geometry)[:n_sobol]
    home_start = next(s for s in starts if s.name == "home")
    calibration, tables = {}, {}
    for model in models:
        table, info = calibrate(geometry, model, home_start)
        calibration[model] = info
        tables[model] = None if table is None else table.to_dict()
    jobs = [(name, model, start, tables[model], str(geometry.root), cogging) for model in models for name in procedures for start in starts]
    if workers > 1:
        import multiprocessing  # noqa: PLC0415

        with multiprocessing.get_context("fork").Pool(min(workers, 3)) as pool:
            outputs = pool.map(_job, jobs, chunksize=1)
    else:
        outputs = [_job(job) for job in jobs]
    episodes: dict = {}
    notes: dict = {}
    wall: dict = {}
    for model, name, start, record, note, seconds in outputs:
        episodes.setdefault(model, {}).setdefault(name, []).append(compact(record))
        notes.setdefault(model, {}).setdefault(name, {})[start] = note
        wall.setdefault(model, {}).setdefault(name, []).append(round(seconds, 1))
    cards = {}
    for model, by_name in episodes.items():
        for name, rows in by_name.items():
            cards.setdefault(model, {})[name] = scorecard([expand(r, name, f"{RUNG} · {model}") for r in rows], gate_deg=GATE_DEG)
    start_rows = [{"name": s.name, "branch": s.branch, "link_deg": {j: math.degrees(v) for j, v in s.link_rad.items()},
                   "why": NAMED_WHY.get(s.name, "Sobol")} for s in starts]
    reference = kinematic_reference()
    any_plant = MujocoRigPlant(models[0], cogging=cogging, settle_s=0.0)
    return {
        "schema": "sim2real_homing_bench/1",
        "rung": RUNG,
        "bundle_sha": BUNDLE_SHA,
        "bundle_root": str(geometry.root),
        "hardstops_sha256": geometry.hardstops_sha256,
        "loops_sha256": geometry.loops_sha256,
        "sim2real_sha": git_sha(Path(__file__).resolve().parents[4]),
        "robot_models_sha": git_sha(Path("/home/bam/robot_models")),
        "bam_ws_sha": git_sha(BAM_WS_SRC.parent),
        "dt_s": 0.01,
        "physics_dt_s": float(any_plant.rig.model.opt.timestep),
        "gate_deg": GATE_DEG,
        "zero_vs_kinematic_deg": ZERO_VS_KINEMATIC_DEG,
        "hidden_gap_arcmin": HIDDEN_GAP_ARCMIN,
        "backlash_methods": {m: BACKLASH_METHOD[m] for m in models},
        "cogging": ({"drives": sorted(any_plant.cogging), "source": "bam_fivebar.plant.JMC_COGGING (sim2real bldc_motor M4.dynamics.cogging)",
                     "not": "J1: no fitted cogging (CAN 11 was never in the fit)"} if cogging else None),
        "board": {"kp_nm_per_rev": any_plant.board.kp, "kd_nm_s_per_rev": any_plant.board.kd, "ilimit_scale": 0.0,
                  "why": "bam_fivebar_recovery.backend.PlantBackend: the rack runner's adapter (PD, no velocity target)"},
        "settle_s": any_plant.settle_s,
        "models": list(models),
        "procedures": list(procedures),
        "starts": start_rows,
        "calibration": calibration,
        "scorecards": cards,
        "scorecards_by_scope": split_scorecards(episodes, start_rows, RUNG, GATE_DEG),
        "kinematic_reference": {k: v for k, v in reference.items() if k != "cards"},
        "verdicts": verdicts(cards, reference),
        "episode_columns": list(EPISODE_COLUMNS),
        "episodes": episodes,
        "notes": notes,
        "wall_s": wall,
        "seconds": time.time() - t0,
    }


def merge(main: dict, extra: dict) -> dict:
    """``extra``'s rows (e.g. the DIAGNOSTIC timed run) added to ``main``'s: per-(model, procedure) tables merged, nothing overwritten."""
    out = dict(main)
    out["procedures"] = list(main["procedures"]) + [p for p in extra["procedures"] if p not in main["procedures"]]
    for key in ("episodes", "notes", "scorecards", "verdicts", "wall_s"):
        merged = {m: dict(v) for m, v in main[key].items()}
        for model, by_name in extra[key].items():
            for name, value in by_name.items():
                if name in merged.get(model, {}):
                    raise ValueError(f"{key}: {model} {name} is in both results")
                merged.setdefault(model, {})[name] = value
        out[key] = merged
    scopes = {}
    for scope in set(main["scorecards_by_scope"]) | set(extra["scorecards_by_scope"]):
        merged = {m: dict(v) for m, v in main["scorecards_by_scope"].get(scope, {}).items()}
        for model, by_name in extra["scorecards_by_scope"].get(scope, {}).items():
            merged.setdefault(model, {}).update(by_name)
        scopes[scope] = merged
    out["scorecards_by_scope"] = scopes
    out["diagnostic_runs"] = {"procedures": extra["procedures"], "models": extra["models"], "seconds": extra["seconds"],
                              "calibration": extra["calibration"]}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--sobol", type=int, default=SOBOL_STARTS)
    parser.add_argument("--procedures", nargs="*", default=list(PROCEDURES))
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--timed-recovery", action="store_true", help="also run the DIAGNOSTIC recover_first(timed)+ rows")
    parser.add_argument("--only-timed", action="store_true", help="run only the DIAGNOSTIC rows (merged into a main results JSON later)")
    parser.add_argument("--no-cogging", action="store_true")
    parser.add_argument("--merge", type=Path, nargs=2, metavar=("MAIN", "EXTRA"), help="merge EXTRA's rows into MAIN, write --out")
    parser.add_argument("--add-traces", type=Path, help="add the page's traces (bowl, B2) to this results JSON and exit")
    args = parser.parse_args(argv)
    if args.merge:
        merged = merge(*(json.loads(path.read_text()) for path in args.merge))
        args.out.write_text(json.dumps(merged))
        print(f"{args.out}: {len(merged['procedures'])} procedures")
        return 0
    if args.add_traces:
        results = json.loads(args.add_traces.read_text())
        geometry = FivebarGeometry()
        rests = {s.name: s for s in named_rests(geometry, prior_for(geometry))}
        results["traces"] = [trace_of(geometry, "B2", name, rests["bowl"]) for name in
                             (RECOVER_PREFIX_NAME + "press_reverse", TIMED + "press_reverse", RECOVER_PREFIX_NAME + "tview_v2")]
        args.out.write_text(json.dumps(results))
        print(f"{args.out}: {len(results['traces'])} traces")
        return 0
    procedures = [] if args.only_timed else [RECOVER_PREFIX_NAME + inner_name(p) for p in args.procedures]
    if args.timed_recovery or args.only_timed:
        procedures += [TIMED + inner_name(p) for p in args.procedures]
    results = run_bench(procedures=tuple(procedures), models=tuple(args.models), n_sobol=args.sobol, workers=min(args.workers, 3),
                        cogging=not args.no_cogging)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results))
    for model, by_name in results["verdicts"].items():
        for name, v in by_name.items():
            print(f"{model} {name:38s} rel {v['reliability_pct']:6.1f}%  zero p95 {v['zero_p95_deg']}  kin {v['kinematic_zero_p95_deg']}  "
                  f"{'PASS' if v['pass'] else 'FAIL'}")
    print(f"{results['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RUNG", "TimedRecoverFirst", "calibrate", "recovery_landing", "run_bench", "verdicts"]
