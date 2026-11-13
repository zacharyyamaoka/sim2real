"""The homing bench's MuJoCo rung, pass 7: the blind recovery fed so "any start" holds, and the crank powered through J2's seek.

    systemd-run --user --scope -q -p MemoryMax=24G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl SIM2REAL_BAM_WS_SRC=<a clean bam_ws checkout>/src PYTHONPATH=/home/bam/sim2real/src /home/bam/sim2real/.venv/bin/python -m sim2real.sim.homing.pass7_rung --out /home/bam/sim2real/src/sim2real/data/homing_fivebar_mujoco_pass7_2026-11-13.json --workers 8

Two questions, each in the form the real arm runs (``real_bench.RealRow``: sag_proof, J1 held, J2 kept powered, ``+gff``), on the pass-6
plant (B0 / B1 / B2, the real board record, the runaway check at 86 deg/s on every powered J2 / C1 command):

1. **Does "any start" now hold?** ``recover_first(fed)+single_touch+gff`` and ``recover_first(fed)+tview_v2+gff`` (recovery_ff: the
   blind recovery with every powered hold and move fed) from **pass 4's 16 recovery starts** (``bench.named_rests`` - bowl, other,
   export_pose, home, on_seek_stops, lower_corner, fold, flipped_crank - and ``bench.sobol_starts``' first 8), each placed and settled
   unpowered. WHY these and not pass 6's real-lane family: these are the starts the recovery exists for (the flipped crank, the fold);
   pass 6's family is near home, where the home button sets every start.
2. **Can the crank stay powered through J2's seek?** ``single_touch_c1seek+gff`` (c1_seek: C1 seeks beside J2, as tview_v2's step 2) on
   pass 6's real-lane family (``gff_rung.real_lane_starts``: the form it would replace single_touch+gff in), and
   ``recover_first(fed)+single_touch_c1seek+gff`` on the recovery starts. Every episode also records how fast each drive moved while
   limp (``limp_peaks``): the real arm's limp crank reached 87.7 deg/s in single_touch+gff's J2 seek, outside the runaway check.

Masses and the comp's own error as pass 6: the end group +22 % (the real arm) at ff x0.75 / x1.0 / x1.25, and CAD masses at nominal.
Gates (frozen, gff_rung's): reliability 100 %, zero p95 vs the twin's contacts <= 0.1 deg and within 0.1 of the kinematic rung's p95 for
the same procedure (none for single_touch_c1seek, which the kinematic rung never ran: the 0.1 deg gate alone). READY for the real arm =
passes on B0, B1 and B2 at every one of the four cases (``gff_rung.readiness``).
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from robot_models.homing.metrics import EpisodeRecord, JointOutcome, scorecard

from sim2real.provenance import code_sha, write_results
from .bench import EPISODE_COLUMNS, compact, expand, prior_for, run_episode
from .geometry import BUNDLE_SHA, C1, DRIVES, J2, ROLE, FivebarGeometry
from .gff_rung import (
    FF_SCALES,
    GATE_DEG,
    MASS_LABEL,
    MASSES,
    MODELS,
    RELIABILITY_TARGET_PCT,
    ZERO_VS_KINEMATIC_DEG,
    _strip_j1,
    _vs_twin,
    config_name,
    configs,
    readiness,
    real_lane_starts,
    step_peaks,
    trips,
    verdict,
)
from .mujoco_bench import kinematic_reference, twin_prior
from .mujoco_plant import BAM_WS_SRC, REAL_BOARD_RECORD, RUNAWAY_RAD_S, MujocoRigPlant, twin_contacts
from .plant import HIDDEN_GAP_ARCMIN
from .procedures import HomingRefused

RUNG = "mujoco"
PASS = 7
KINEMATIC_JSON = Path(__file__).resolve().parents[2] / "data" / "homing_fivebar_kinematic_2026-11-12.json"
N_SOBOL = 8  # pass 4's: named_rests + sobol_starts[:8] = 16
RECOVERY, REAL_LANE = "recovery", "real-lane"
# (row, start family): module docstring
ROWS = (
    ("recover_first(fed)+single_touch+gff", RECOVERY),
    ("recover_first(fed)+tview_v2+gff", RECOVERY),
    ("single_touch_c1seek+gff", REAL_LANE),
    ("recover_first(fed)+single_touch_c1seek+gff", RECOVERY),
    # the baseline the c1seek row is judged against for the limp crank: pass 6's single_touch+gff in the same form, re-run here because
    # pass 6 recorded no limp speeds (its gates are pass 6's and unchanged)
    ("single_touch+gff", REAL_LANE),
)
FAMILY_WHY = {RECOVERY: "pass 4's 16 recovery starts (bench.named_rests + bench.sobol_starts[:8]), placed then settled unpowered",
              REAL_LANE: "pass 6's real-lane family (gff_rung.real_lane_starts): the homed map's home + offsets, released"}


def base_name(row: str) -> str:
    """The procedure a row is built on (no recovery prefix, no +gff): the kinematic rung's row name."""
    from .recover import RECOVER_PREFIX_NAME  # noqa: PLC0415
    from .recovery_ff import FED_RECOVER_PREFIX  # noqa: PLC0415

    return row.removeprefix(FED_RECOVER_PREFIX).removeprefix(RECOVER_PREFIX_NAME).removesuffix("+gff")


def starts_for(family: str, geometry: FivebarGeometry, prior) -> list:
    from .bench import named_rests, sobol_starts  # noqa: PLC0415

    if family == RECOVERY:
        return named_rests(geometry, prior) + sobol_starts(geometry)[:N_SOBOL]
    return real_lane_starts()


def limp_peaks(plant: MujocoRigPlant, phase) -> dict:
    """Per drive, the fastest it moved while limp (deg/s) and in which step - every step but the recovery's own opening drop
    ('recover: limp', where the blind recovery lets the arm fall on purpose) - from the plant's log (one 10 ms tick per row)."""
    import numpy as np  # noqa: PLC0415

    offset = phase.log["plant_offset"]
    motor = np.asarray(plant.log["motor"], dtype=float)
    setpoint = np.asarray(plant.log["setpoint"], dtype=float)
    names = [s.name for s in phase.sequence.steps]
    out = {ROLE[j]: {"deg_s": 0.0, "step": None} for j in (J2, C1)}
    for k, step in enumerate(phase.log["step"]):
        row = offset + k + 1
        if row >= len(motor):
            break
        name = names[min(step, len(names) - 1)]
        if name == "recover: limp":
            continue
        for joint in (J2, C1):
            i = DRIVES.index(joint)
            if np.isfinite(setpoint[row, i]):
                continue
            speed = math.degrees(abs(motor[row, i] - motor[row - 1, i]) / 0.01)
            if speed > out[ROLE[joint]]["deg_s"]:
                out[ROLE[joint]] = {"deg_s": round(speed, 2), "step": name}
    return out


def run_one(row: str, model: str, mass: str, ff: float | None, start, prior, twin) -> tuple[dict, dict]:
    """One episode (gff_rung.run_one's, plus the limp peaks and the fed recovery's plan note)."""
    from .real_bench import RealRow  # noqa: PLC0415

    name = config_name(row, mass, ff)
    plant = MujocoRigPlant(model, end_mass_scale=MASSES[mass], runaway_rad_s=RUNAWAY_RAD_S)
    procedure = RealRow(row, ff_scale=1.0 if ff is None else ff)
    episode = run_episode(name, plant, start, prior, f"{RUNG} · {model}", procedure=procedure)
    record = _strip_j1(episode.record)
    notes = dict(episode.notes)
    notes["start"] = plant.start_settled
    notes["peak_powered_deg_s"] = {k: round(math.degrees(v), 2) for k, v in plant.peak_powered_rad_s.items()}
    if episode.phases:
        phase = episode.phases[0]
        notes["status"] = phase.status
        notes["message"] = phase.message
        notes["step_peaks"] = step_peaks(plant, phase)
        notes["limp_peaks"] = limp_peaks(plant, phase)
        defines = [k for k, d in enumerate(phase.log["defines"]) if d]
        if defines:
            notes["zero_defined_at_s"] = round(phase.log["t"][defines[-1]], 3)
    feed = procedure.notes.get("recovery_ff")
    if feed is not None:
        notes["recovery_ff"] = {"filled_steps": len(feed["filled_steps"]), "unfed_non_seek": feed["unfed_non_seek"]}
    if episode.result is not None:
        try:
            result = procedure.observe_vs_twin(prior, twin, episode.phases)
        except HomingRefused as error:
            notes["zero_error_vs_twin_deg"] = {"refused": str(error)}
        else:
            true = plant.truth()["true_offset_rad"]
            notes["zero_error_vs_twin_deg"] = {ROLE[j]: (None if result.zero(j) is None else math.degrees(result.zero(j).offset_rad - true[j]))
                                               for j in (J2, C1)}
    return record.to_dict(), notes


def _job(args):
    row, model, mass, ff, start, contacts = args
    geometry = FivebarGeometry()
    prior = prior_for(geometry)
    twin = twin_prior(prior, contacts)
    t0 = time.time()
    try:
        record, notes = run_one(row, model, mass, ff, start, prior, twin)
    except Exception as error:  # a crash is an outcome, recorded (never a silent drop from the denominator)
        record = EpisodeRecord(config_name(row, mass, ff), f"{RUNG} · {model}", start.name, False,
                               f"crashed: {type(error).__name__}: {error}", None, (),
                               tuple(JointOutcome(j, None, None, HIDDEN_GAP_ARCMIN[j] / 60.0) for j in (J2, C1))).to_dict()
        notes = {"crash": repr(error)}
    return row, model, mass, ff, start.name, record, notes, time.time() - t0


def limp_summary(notes: dict) -> dict:
    """Per (model, config): the fastest limp J2 / C1 over its episodes, and where."""
    out = {}
    for model, by_name in notes.items():
        for name, by_start in by_name.items():
            best = {"J2": {"deg_s": 0.0}, "C1": {"deg_s": 0.0}}
            for start, note in by_start.items():
                for role, peak in ((note or {}).get("limp_peaks") or {}).items():
                    if peak["deg_s"] > best[role]["deg_s"]:
                        best[role] = dict(peak, start=start)
            out.setdefault(model, {})[name] = best
    return out


def run_bench(*, rows=ROWS, models=MODELS, masses=tuple(MASSES), ff_scales=FF_SCALES, workers: int = 4, limit_starts: int | None = None) -> dict:
    t0 = time.time()
    geometry = FivebarGeometry()
    prior = prior_for(geometry)
    from .bench import named_rests  # noqa: PLC0415

    rest = {s.name: s for s in named_rests(geometry, prior)}
    contacts = twin_contacts({+1: rest["on_seek_stops"], -1: rest["lower_corner"]})
    families = {family: starts_for(family, geometry, prior)[:limit_starts] for family in {f for _, f in rows}}
    jobs = [(row, model, mass, ff, start, contacts) for row, family in rows for (_, mass, ff) in configs((row,), masses, ff_scales)
            for model in models for start in families[family]]
    jobs.sort(key=lambda job: job[1] != "B1")  # B1 (a quarter timestep) sets the wall time: first
    outputs = []

    def progress(output):
        outputs.append(output)
        row, model, mass, ff, start, record, _, seconds = output
        print(f"[{len(outputs)}/{len(jobs)}] {model} {config_name(row, mass, ff)} {start}: {record['outcome'][:90]} ({seconds:.0f} s)",
              flush=True)

    if workers > 1:
        import multiprocessing  # noqa: PLC0415

        with multiprocessing.get_context("fork").Pool(workers, maxtasksperchild=8) as pool:
            for output in pool.imap_unordered(_job, jobs, chunksize=1):
                progress(output)
    else:
        for job in jobs:
            progress(_job(job))
    family_of = dict(rows)
    order = {(family, s.name): k for family, starts in families.items() for k, s in enumerate(starts)}
    episodes, episodes_vs_twin, notes, wall = {}, {}, {}, {}
    for row, model, mass, ff, start, record, note, seconds in sorted(outputs, key=lambda o: (o[0], order[(family_of[o[0]], o[4])])):
        name = config_name(row, mass, ff)
        episodes.setdefault(model, {}).setdefault(name, []).append(compact(record))
        episodes_vs_twin.setdefault(model, {}).setdefault(name, []).append(compact(_vs_twin(record, note)))
        notes.setdefault(model, {}).setdefault(name, {})[start] = note
        wall.setdefault(model, {}).setdefault(name, []).append(round(seconds, 1))
    reference = kinematic_reference(KINEMATIC_JSON)
    cards, cards_vs_twin, verdicts = {}, {}, {}
    row_names = [r for r, _ in rows]
    for model, by_name in episodes.items():
        for name, rows_ in by_name.items():
            row = name.split(" · ")[0]
            card = scorecard([expand(r, name, f"{RUNG} · {model}") for r in rows_], gate_deg=GATE_DEG)
            twin_card = scorecard([expand(r, name, f"{RUNG} · {model}") for r in episodes_vs_twin[model][name]], gate_deg=GATE_DEG)
            kin = ((reference.get("cards") or {}).get(model, {}).get(base_name(row)) or {}).get("joint_angle_error_deg")
            cards.setdefault(model, {})[name] = card
            cards_vs_twin.setdefault(model, {})[name] = twin_card
            verdicts.setdefault(model, {})[name] = verdict(card, twin_card, kin)
    start_rows = {family: [{"name": s.name, "branch": s.branch, "link_deg": {j: math.degrees(v) for j, v in s.link_rad.items()},
                            "gap_fraction": dict(s.gap_fraction)} for s in starts] for family, starts in families.items()}
    any_plant = MujocoRigPlant(models[0], settle_s=0.0, end_mass_scale=MASSES["end+22%"])
    return {
        "schema": "sim2real_homing_bench/1",
        "rig": "five-bar",
        "rung": RUNG,
        "pass": PASS,
        "form": "real (real_bench.RealRow: sag_proof, J1 held, J2 kept powered, +gff; recover_first(fed) = recovery_ff's fill as the last "
                "rewrite; single_touch_c1seek = c1_seek, C1 kept powered)",
        "bundle_sha": BUNDLE_SHA,
        "bundle_root": str(geometry.root),
        "hardstops_sha256": geometry.hardstops_sha256,
        "loops_sha256": geometry.loops_sha256,
        "sim2real_sha": code_sha(Path(__file__).resolve().parents[4]),
        "robot_models_sha": code_sha(Path("/home/bam/robot_models")),
        "bam_ws_sha": code_sha(BAM_WS_SRC.parent),
        "bam_ws_src": str(BAM_WS_SRC),
        "dt_s": 0.01,
        "gate_deg": GATE_DEG,
        "zero_vs_kinematic_deg": ZERO_VS_KINEMATIC_DEG,
        "reliability_target_pct": RELIABILITY_TARGET_PCT,
        "hidden_gap_arcmin": HIDDEN_GAP_ARCMIN,
        "runaway_rad_s": RUNAWAY_RAD_S,
        "runaway_deg_s": math.degrees(RUNAWAY_RAD_S),
        "masses": {k: {"end_group_mass_scale": v, "label": MASS_LABEL[k],
                       "end_group_kg": None if k == "cad" else any_plant.rig.model.body_mass[any_plant.rig.model.body("l2").id]}
                   for k, v in MASSES.items()},
        "ff_scales": list(ff_scales),
        "comp": "gravity_ff.COMP (the home button's identified comp, bam_ws 2ec4dd02a)",
        "board": {"per_drive": REAL_BOARD_RECORD, "ilimit_scale": 0.0, "record": "mujoco_plant.REAL_BOARD_RECORD"},
        "models": list(models),
        "rows": [{"row": r, "starts": f, "why": FAMILY_WHY[f]} for r, f in rows],
        "procedures": [config_name(*c) for r in row_names for c in configs((r,), masses, ff_scales)],
        "starts": start_rows,
        "twin_contacts_deg": {ROLE[j]: {("upper" if side > 0 else "lower"): {
            "twin": math.degrees(contacts[(j, side)]), "cad": math.degrees(prior.stops.q_rad(j, side)),
            "cad_minus_twin": math.degrees(prior.stops.q_rad(j, side) - contacts[(j, side)])} for side in (+1, -1)} for j in DRIVES},
        "kinematic_reference": {k: v for k, v in reference.items() if k != "cards"},
        "scorecards": cards,
        "scorecards_vs_twin": cards_vs_twin,
        "verdicts": verdicts,
        "readiness": readiness(verdicts, tuple(row_names), models),
        "trips": trips(notes),
        "limp_peaks": limp_summary(notes),
        "episode_columns": list(EPISODE_COLUMNS),
        "episodes": episodes,
        "episodes_vs_twin": episodes_vs_twin,
        "notes": notes,
        "wall_s": wall,
        "seconds": time.time() - t0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rows", nargs="*", default=None, help="row names (default: every row of ROWS, each with its start family)")
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--masses", nargs="*", default=list(MASSES))
    parser.add_argument("--ff", nargs="*", type=float, default=list(FF_SCALES))
    parser.add_argument("--limit-starts", type=int, default=None, help="a smoke run: the first N starts of each family")
    args = parser.parse_args(argv)
    rows = ROWS if args.rows is None else tuple((r, f) for r, f in ROWS if r in args.rows)
    results = run_bench(rows=rows, models=tuple(args.models), masses=tuple(args.masses), ff_scales=tuple(args.ff), workers=args.workers,
                        limit_starts=args.limit_starts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_results(args.out, results, default=float)
    for model, by_name in results["verdicts"].items():
        for name, v in by_name.items():
            print(f"{model} {name:80s} rel {v['reliability_pct']:6.1f}%  zero p95 vs twin {v['zero_p95_vs_twin_deg']}  "
                  f"{'PASS' if v['pass'] else 'FAIL'}")
    for row, r in results["readiness"].items():
        print(f"{row:48s} {'READY' if r['ready'] else 'not ready'}  {'; '.join(r['failed'][:4])}")
    print(f"{results['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PASS", "ROWS", "base_name", "limp_peaks", "run_bench", "run_one", "starts_for"]
