"""The homing bench's MuJoCo rung, pass 6: gravity feed-forward on every hold and move, judged in the form the real arm runs.

    systemd-run --user --scope -q -p MemoryMax=12G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra homing --extra sim python -m sim2real.sim.homing.gff_rung --out /home/bam/sim2real/src/sim2real/data/homing_fivebar_mujoco_pass6_2026-11-13.json --workers 4

Why a pass of its own (2026-11-13): pass 5 sent single_touch and tview_v2 to the real five-bar and 0 of 16 episodes finished - every zero was
taken and repeated (spread J2 0.060 / C1 0.000 deg), then 0.1-0.2 s later the first hold after the zero, carrying no gravity feed-forward,
let J2 fall past the rack's 86 deg/s runaway ceiling (the real end group is 22 % heavier than CAD). The MuJoCo rung had not seen it: its
plant had no runaway check and CAD's masses. This rung closes both gaps and asks one question: which procedures can now go to the arm?

What is run, and why each choice:

* **The real form.** Each row is ``real_bench.RealRow`` - the exact sequence ``fivebar_homed --stage homing --homing-procedure <row>``
  sends: the bare procedure (the real lane's recovery is the home button, which sets every start), sag_proof's completion, J1 held
  (``hold_j1``: its stops are unconfirmed on the rack, so it is never homed and its zero is not scored), J2 never let go under load
  (``keep_j2_powered``), ``+gff`` where named. Rows: single_touch, tview_v2 (the pass-5 sequences, un-fed - the red baseline) and
  single_touch+gff, tview_v2+gff (gravity_ff: every hold and move fed from the pose it starts at and the pose it ends at).
* **The starts: the real lane's start family.** The real runner walks the arm with the home button to the homed map's home plus an offset
  and releases it; the procedure starts from wherever the released arm comes to rest. Here: the homed map's home (Craig 91.01, -126.438,
  homed_083647) plus the real lane's four offsets (``real_bench.STARTS``: (0, 0), (0, -10), (4, 0), (4, -10) Craig deg) and 12 scrambled
  Sobol offsets inside the box they span, J1 vertical (the rack's plane, held), each motor anywhere in its gap, placed and then settled
  unpowered (``mujoco_plant``: the released arm). 16 starts. WHY not the 16 recovery starts of pass 4 (bowl, flipped crank, ...): those
  test the recovery in front of a procedure, and on the real arm that recovery is the home button, replayed on this rung separately
  (``home_button``); a bare procedure from a flipped crank is a test the real lane never runs.
* **The masses.** ``cad`` (the bundle's) and ``end+22%``: the twin's end-group body scaled x1.2249 (``mujoco_plant.END_GROUP_MASS_SCALE``,
  the home button's mass-ID, massid_real_093852) - the real arm.
* **The feed-forward's own error.** The comp is the home button's identified model; a +gff row runs it at x0.75, x1.0 and x1.25 (the comp
  25 % light, right, 25 % heavy) on both masses, so a feed-forward that only works when its model is right is not called ready.
* **The boards and the runaway check.** The real record (J2 kp 144 / kd 8, C1 kp 200 / kd 4 N.m per output rev, ilimit_scale 0, no
  velocity target: ``mujoco_plant.REAL_BOARD_RECORD``) and the real runner's runaway stop on every powered J2 / C1 plain position command:
  over 1.5 rad/s (86 deg/s) the episode ends, tripped (``MujocoRigPlant(runaway_rad_s=...)``), as ``run_phase_real`` ends a real one.
* **The table.** None, as on the real arm (no real identify_backlash: press_reverse cannot run there); single_touch's half-gap correction
  is then 0, as in pass 5.

Gates (frozen, unchanged): reliability == 100 % (every start finished, every stall on its stop), the zero within ``GATE_DEG`` 0.1 deg (p95
over the reliable starts, J2 and C1) and within ``ZERO_VS_KINEMATIC_DEG`` 0.1 of the kinematic rung's p95 for the same procedure. Judged
against the twin's own stop contacts (the coordinator's 2026-11-12 ruling: the exporter's J2 pair sits 0.285 deg short of CAD), with the
CAD verdict kept beside it. A row is READY for the real arm when it passes on B0, B1 and B2 with the end group +22 % at every feed-forward
error (and on CAD masses at nominal).
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import replace
from pathlib import Path

from robot_models.homing.metrics import EpisodeRecord, JointOutcome, scorecard

from .bench import EPISODE_COLUMNS, compact, expand, git_sha, prior_for, run_episode
from .geometry import BUNDLE_SHA, C1, DRIVES, EXPORT, J1, J2, ROLE, FivebarGeometry
from .mujoco_bench import kinematic_reference, twin_prior
from .mujoco_plant import BAM_WS_SRC, END_GROUP_MASS_SCALE, REAL_BOARD_RECORD, RUNAWAY_RAD_S, MujocoRigPlant, twin_contacts
from .plant import HIDDEN_GAP_ARCMIN, Start
from .procedures import HomingRefused

RUNG = "mujoco"
PASS = 6
GATE_DEG = 0.1  # frozen (mujoco_bench.GATE_DEG)
ZERO_VS_KINEMATIC_DEG = 0.1  # frozen (mujoco_bench.ZERO_VS_KINEMATIC_DEG)
RELIABILITY_TARGET_PCT = 100.0  # frozen
MODELS = ("B0", "B1", "B2")
ROWS = ("single_touch", "tview_v2", "single_touch+gff", "tview_v2+gff")
MASSES = {"cad": 1.0, "end+22%": END_GROUP_MASS_SCALE}
MASS_LABEL = {"cad": "CAD mass", "end+22%": "end group +22 %"}
FF_SCALES = (0.75, 1.0, 1.25)
FF_LABEL = {0.75: "ff -25 %", 1.0: "ff nominal", 1.25: "ff +25 %"}
# homed_083647's home in Craig deg (J2, C1): the home button's target on every real run (data/fivebar_home_button_real_2026-11-12.json)
HOME_CRAIG_DEG = (91.01, -126.438)
REAL_OFFSETS_DEG = ((0.0, 0.0), (0.0, -10.0), (4.0, 0.0), (4.0, -10.0))  # real_bench.STARTS, in order
N_STARTS = 16
SOBOL_SEED = 20261113
HIDDEN_OFFSETS = {J1: 0.31, J2: -1.7, C1: 2.6}  # bench.named_rests' power-up zeros: nothing may assume the encoder reads the joint
KINEMATIC_JSON = Path(__file__).resolve().parents[2] / "data" / "homing_fivebar_kinematic_2026-11-12.json"


def config_name(row: str, mass: str, ff: float | None) -> str:
    """A leaderboard row: the procedure, its form, the mass case and (+gff only) the comp's assumed error."""
    parts = [row, "real form", MASS_LABEL[mass]]
    if row.endswith("+gff"):
        parts.append(FF_LABEL[ff])
    return " · ".join(parts)


def configs(rows=ROWS, masses=tuple(MASSES), ff_scales=FF_SCALES) -> list[tuple[str, str, float | None]]:
    out = []
    for row in rows:
        for mass in masses:
            for ff in (ff_scales if row.endswith("+gff") else (None,)):
                out.append((row, mass, ff))
    return out


def craig_offsets() -> dict:
    """Craig = URDF + offset (sign +1 on bundle 8957130: home_button.craig_frame's check)."""
    from .mujoco_plant import RigCache, bam_ws_path  # noqa: PLC0415

    bam_ws_path()
    from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415

    craig = CraigMap(RigCache.get("B0"))
    for role in ("J2", "C1"):
        if craig.sign[role] != 1.0:
            raise ValueError(f"CraigMap gives {role} sign {craig.sign[role]}: the starts assume Craig = URDF + offset")
    return {J2: float(craig.offset["J2"]), C1: float(craig.offset["C1"])}


def real_lane_starts(n: int = N_STARTS, seed: int = SOBOL_SEED) -> list[Start]:
    """The real lane's start family (module docstring): home + the four real offsets, then Sobol offsets inside their box."""
    from scipy.stats import qmc  # noqa: PLC0415

    offset = craig_offsets()
    lo = (min(o[0] for o in REAL_OFFSETS_DEG), min(o[1] for o in REAL_OFFSETS_DEG))
    hi = (max(o[0] for o in REAL_OFFSETS_DEG), max(o[1] for o in REAL_OFFSETS_DEG))
    sampler = qmc.Sobol(d=5, scramble=True, seed=seed)
    draws = sampler.random(32)
    offsets = list(REAL_OFFSETS_DEG) + [(lo[0] + r[0] * (hi[0] - lo[0]), lo[1] + r[1] * (hi[1] - lo[1])) for r in draws[: n - 4]]
    out = []
    for k, (dj2, dc1) in enumerate(offsets[:n]):
        craig = (HOME_CRAIG_DEG[0] + dj2, HOME_CRAIG_DEG[1] + dc1)
        j2 = math.radians(craig[0]) - offset[J2]
        c1 = (math.radians(craig[1]) - offset[C1] + math.pi) % (2.0 * math.pi) - math.pi
        fractions = draws[k % len(draws)][2:5]
        name = ("real-" if k < 4 else "band-") + f"{k:02d} ({dj2:+.1f}, {dc1:+.1f})"
        out.append(Start(name, {J1: 0.0, J2: j2, C1: c1}, {j: 2.0 * float(f) - 1.0 for j, f in zip(DRIVES, fractions, strict=True)},
                         dict(HIDDEN_OFFSETS), EXPORT))
    return out


def _strip_j1(record: EpisodeRecord) -> EpisodeRecord:
    """J1 is held on the real form, never homed: its row is not scored (real_plant.J1Held)."""
    return replace(record, joints=tuple(j for j in record.joints if j.joint != J1))


def step_peaks(plant: MujocoRigPlant, phase) -> list[dict]:
    """Per step: the peak J2 / C1 speed (deg/s) and whether each was powered there, from the plant's own log (the speed the runaway
    check watches)."""
    import numpy as np  # noqa: PLC0415

    offset = phase.log["plant_offset"]
    motor = np.asarray(plant.log["motor"], dtype=float)
    setpoint = np.asarray(plant.log["setpoint"], dtype=float)
    names = [s.name for s in phase.sequence.steps]
    out: dict[int, dict] = {}
    for k, step in enumerate(phase.log["step"]):
        row = offset + k + 1
        if row >= len(motor):
            break
        index = min(step, len(names) - 1)
        entry = out.setdefault(index, {"step": names[index], "J2_deg_s": 0.0, "C1_deg_s": 0.0, "J2_powered": False, "C1_powered": False})
        for joint in (J2, C1):
            i = DRIVES.index(joint)
            speed = abs(motor[row, i] - motor[row - 1, i]) / 0.01
            powered = bool(np.isfinite(setpoint[row, i]))
            role = ROLE[joint]
            if powered:
                entry[f"{role}_powered"] = True
                entry[f"{role}_deg_s"] = max(entry[f"{role}_deg_s"], round(math.degrees(speed), 2))
    return [out[k] for k in sorted(out)]


def run_one(row: str, model: str, mass: str, ff: float | None, start: Start, prior, twin) -> tuple[dict, dict]:
    """One episode of a pass-6 row: (the EpisodeRecord dict with J1 dropped, the notes incl. the vs-twin zero error and the peaks)."""
    from .real_bench import RealRow  # noqa: PLC0415

    name = config_name(row, mass, ff)
    environment = f"{RUNG} · {model}"
    plant = MujocoRigPlant(model, end_mass_scale=MASSES[mass], runaway_rad_s=RUNAWAY_RAD_S)
    procedure = RealRow(row, ff_scale=1.0 if ff is None else ff)
    episode = run_episode(name, plant, start, prior, environment, procedure=procedure)
    record = _strip_j1(episode.record)
    notes = dict(episode.notes)
    notes["start"] = plant.start_settled
    notes["peak_powered_deg_s"] = {k: round(math.degrees(v), 2) for k, v in plant.peak_powered_rad_s.items()}
    if episode.phases:
        phase = episode.phases[0]
        notes["status"] = phase.status
        notes["message"] = phase.message
        notes["step_peaks"] = step_peaks(plant, phase)
        defines = [k for k, d in enumerate(phase.log["defines"]) if d]
        if defines:
            notes["zero_defined_at_s"] = round(phase.log["t"][defines[-1]], 3)
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


def _vs_twin(record: dict, note: dict) -> dict:
    twin = (note or {}).get("zero_error_vs_twin_deg") or {}
    joints = [dict(j, zero_error_deg=(twin.get(ROLE[j["joint"]]) if j["zero_error_deg"] is not None else None)) for j in record["joints"]]
    return dict(record, joints=joints)


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


def verdict(card: dict, twin_card: dict, kinematic_p95: float | None) -> dict:
    """The frozen gates on one (model, row) - module docstring."""
    mine, twin = card.get("joint_angle_error_deg"), twin_card.get("joint_angle_error_deg")
    reliable_ok = bool(card["reliability_pct"] == RELIABILITY_TARGET_PCT)

    def zero_ok(value):
        if value is None:
            return None
        ok = value <= GATE_DEG
        if kinematic_p95 is not None:
            ok = ok and value <= kinematic_p95 + ZERO_VS_KINEMATIC_DEG
        return bool(ok)

    return {"reliability_pct": card["reliability_pct"], "reliability_gate_pass": reliable_ok, "zero_p95_deg": mine,
            "zero_p95_vs_twin_deg": twin, "kinematic_zero_p95_deg": kinematic_p95, "zero_gate_pass_vs_cad": zero_ok(mine),
            "zero_gate_pass": zero_ok(twin), "pass_vs_cad": bool(reliable_ok and zero_ok(mine) is True),
            "pass": bool(reliable_ok and zero_ok(twin) is True)}


def readiness(verdicts: dict, rows=ROWS, models=MODELS) -> dict:
    """Per row: READY for the real arm when it passes on every model with the end group +22 % at every feed-forward error, and on CAD
    masses at nominal (module docstring); otherwise which (model, case) failed."""
    out = {}
    for row in rows:
        needed = [config_name(row, "end+22%", ff) for ff in (FF_SCALES if row.endswith("+gff") else (None,))]
        needed.append(config_name(row, "cad", 1.0 if row.endswith("+gff") else None))
        failed = [f"{model}: {name}" for name in needed for model in models
                  if not ((verdicts.get(model) or {}).get(name) or {}).get("pass")]
        missing = [f"{model}: {name}" for name in needed for model in models if name not in (verdicts.get(model) or {})]
        out[row] = {"ready": not failed and not missing, "judged_on": needed, "failed": failed, "missing": missing}
    return out


def trips(notes: dict) -> dict:
    """Per (model, row): the episodes the runaway check ended, with where and how fast."""
    out = {}
    for model, by_name in notes.items():
        for name, by_start in by_name.items():
            hits = [{"start": s, "message": n.get("message")} for s, n in by_start.items() if (n or {}).get("status") == "tripped"]
            out.setdefault(model, {})[name] = hits
    return out


def run_bench(*, rows=ROWS, models=MODELS, masses=tuple(MASSES), ff_scales=FF_SCALES, n_starts: int = N_STARTS, workers: int = 4) -> dict:
    t0 = time.time()
    geometry = FivebarGeometry()
    prior = prior_for(geometry)
    starts = real_lane_starts(n_starts)
    from .bench import named_rests  # noqa: PLC0415

    rest = {s.name: s for s in named_rests(geometry, prior)}
    # the twin's own contacts (gravity off: the masses do not move them), measured as pass 4 measures them
    contacts = twin_contacts({+1: rest["on_seek_stops"], -1: rest["lower_corner"]})
    jobs = [(row, model, mass, ff, start, contacts) for (row, mass, ff) in configs(rows, masses, ff_scales) for model in models
            for start in starts]
    # WHY the slow model first: B1's dead zone runs at a quarter of the timestep, so its jobs set the wall time; started first they finish
    jobs.sort(key=lambda job: job[1] != "B1")
    if workers > 1:
        import multiprocessing  # noqa: PLC0415

        with multiprocessing.get_context("fork").Pool(workers) as pool:
            outputs = pool.map(_job, jobs, chunksize=1)
    else:
        outputs = [_job(job) for job in jobs]
    episodes, episodes_vs_twin, notes, wall = {}, {}, {}, {}
    order = {s.name: k for k, s in enumerate(starts)}
    for row, model, mass, ff, start, record, note, seconds in sorted(outputs, key=lambda o: order[o[4]]):
        name = config_name(row, mass, ff)
        episodes.setdefault(model, {}).setdefault(name, []).append(compact(record))
        episodes_vs_twin.setdefault(model, {}).setdefault(name, []).append(compact(_vs_twin(record, note)))
        notes.setdefault(model, {}).setdefault(name, {})[start] = note
        wall.setdefault(model, {}).setdefault(name, []).append(round(seconds, 1))
    reference = kinematic_reference(KINEMATIC_JSON)
    cards, cards_vs_twin, verdicts = {}, {}, {}
    for model, by_name in episodes.items():
        for name, rows_ in by_name.items():
            row = name.split(" · ")[0]
            card = scorecard([expand(r, name, f"{RUNG} · {model}") for r in rows_], gate_deg=GATE_DEG)
            twin_card = scorecard([expand(r, name, f"{RUNG} · {model}") for r in episodes_vs_twin[model][name]], gate_deg=GATE_DEG)
            kin = ((reference.get("cards") or {}).get(model, {}).get(row.removesuffix("+gff")) or {}).get("joint_angle_error_deg")
            cards.setdefault(model, {})[name] = card
            cards_vs_twin.setdefault(model, {})[name] = twin_card
            verdicts.setdefault(model, {})[name] = verdict(card, twin_card, kin)
    start_rows = [{"name": s.name, "branch": s.branch, "link_deg": {j: math.degrees(v) for j, v in s.link_rad.items()},
                   "gap_fraction": dict(s.gap_fraction), "why": "the real lane's start family (module docstring)"} for s in starts]
    any_plant = MujocoRigPlant(models[0], settle_s=0.0, end_mass_scale=MASSES["end+22%"])
    return {
        "schema": "sim2real_homing_bench/1",
        "rig": "five-bar",
        "rung": RUNG,
        "pass": PASS,
        "form": "real (real_bench.RealRow: bare, sag_proof, J1 held, J2 kept powered, +gff where named)",
        "bundle_sha": BUNDLE_SHA,
        "bundle_root": str(geometry.root),
        "hardstops_sha256": geometry.hardstops_sha256,
        "loops_sha256": geometry.loops_sha256,
        "sim2real_sha": git_sha(Path(__file__).resolve().parents[4]),
        "robot_models_sha": git_sha(Path("/home/bam/robot_models")),
        "bam_ws_sha": git_sha(BAM_WS_SRC.parent),
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
        "mass_source": "bam_rack_twin records/fivebar-bench/gravity_params_massid_real_093852.json: group l2 2.0629 kg vs CAD 1.6842 kg",
        "ff_scales": list(ff_scales),
        "comp": "gravity_ff.COMP (the home button's identified comp, bam_ws 2ec4dd02a)",
        "board": {"per_drive": REAL_BOARD_RECORD, "ilimit_scale": 0.0, "record": "mujoco_plant.REAL_BOARD_RECORD"},
        "home_craig_deg": list(HOME_CRAIG_DEG),
        "models": list(models),
        "rows": list(rows),
        "procedures": [config_name(*c) for c in configs(rows, masses, ff_scales)],
        "starts": start_rows,
        "twin_contacts_deg": {ROLE[j]: {("upper" if side > 0 else "lower"): {
            "twin": math.degrees(contacts[(j, side)]), "cad": math.degrees(prior.stops.q_rad(j, side)),
            "cad_minus_twin": math.degrees(prior.stops.q_rad(j, side) - contacts[(j, side)])} for side in (+1, -1)} for j in DRIVES},
        "kinematic_reference": {k: v for k, v in reference.items() if k != "cards"},
        "scorecards": cards,
        "scorecards_vs_twin": cards_vs_twin,
        "verdicts": verdicts,
        "readiness": readiness(verdicts, rows, models),
        "trips": trips(notes),
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
    parser.add_argument("--starts", type=int, default=N_STARTS)
    parser.add_argument("--rows", nargs="*", default=list(ROWS))
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--masses", nargs="*", default=list(MASSES))
    parser.add_argument("--ff", nargs="*", type=float, default=list(FF_SCALES))
    args = parser.parse_args(argv)
    results = run_bench(rows=tuple(args.rows), models=tuple(args.models), masses=tuple(args.masses), ff_scales=tuple(args.ff),
                        n_starts=args.starts, workers=args.workers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, default=float))
    for model, by_name in results["verdicts"].items():
        for name, v in by_name.items():
            print(f"{model} {name:62s} rel {v['reliability_pct']:6.1f}%  zero p95 vs twin {v['zero_p95_vs_twin_deg']}  vs CAD "
                  f"{v['zero_p95_deg']}  {'PASS' if v['pass'] else 'FAIL'}")
    for row, r in results["readiness"].items():
        print(f"{row:20s} {'READY' if r['ready'] else 'not ready'}  {'; '.join(r['failed'][:4])}")
    print(f"{results['seconds']:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["GATE_DEG", "MASSES", "ROWS", "config_name", "configs", "readiness", "real_lane_starts", "run_bench", "run_one", "verdict"]
