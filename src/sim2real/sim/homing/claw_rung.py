"""home() with the crab claw on the five-bar, on the MuJoCo rung (2026-11-13, sim only): does single_touch+gff still pass with the claw's
mass in place of the plate's, and does its gravity feed-forward need the claw added?

    systemd-run --user --scope -q -p MemoryMax=12G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra homing --extra sim python -m sim2real.sim.homing.claw_rung --out /home/bam/sim2real/src/sim2real/data/homing_fivebar_claw_2026-11-13.json --workers 6

Everything is pass 6's (``gff_rung``), the rung single_touch+gff was made READY on and then passed 8/8 on the real arm with: the real form
(``real_bench.RealRow``: bare, sag_proof, J1 held, J2 kept powered, +gff), the real lane's 16 starts (``gff_rung.real_lane_starts``), B0 /
B1 / B2, the real boards, the runaway check on every powered J2 / C1 command (86 deg/s), the frozen gates (reliability 100 %, the zero
p95 <= 0.1 deg against the twin's own contacts and within 0.1 deg of the kinematic rung). Two inputs change:

* **The plant's end payload.** ``MujocoRigPlant(end_payload_kg=CLAW_KG)``: the plate and its mount out of the end group, the crab claw's
  mass on J4's axis (mujoco_plant END_PAYLOAD_WHY). ``claw`` = that alone; ``claw +22 %`` = then x1.2249, pass 6's heavier-arm reading
  applied to the claw-on group (the upper end of what the mass ID's excess could be). CLAW_KG is bam_ws claw_payload.CASES["nominal"]:
  the crab claw's CAD 0.3033 kg x 1.2249 (no scale reading exists; its low / high bracket 0.303 / 0.50 kg moves the claw-on gravity by
  -7 / +13 % at the tray pose, inside the comp's +-25 % below).
* **The feed-forward's comp.** ``plate comp`` = gravity_ff.COMP, today's (the mass ID's, plate on): what home() sends if nothing changes.
  ``claw comp`` = bam_ws docs/pick_tracking/data/gravity_params_claw_nominal_2026-11-13.json: that same identified comp with the payload
  swapped plate -> claw (claw_payload.claw_parameters). The claw comp runs pass 6's readiness form - claw +22 % at ff x0.75 / x1.0 / x1.25
  and claw at nominal - so "ready" means it survives its own model being 25 % off; the plate comp runs at nominal on both masses.

READY (pass 6's rule, unchanged) = every (model, case) the form names passes. WHY a module and not gff_rung flags: gff_rung is pass 6's
record (its results file stands as run) and a peer lane is editing it for pass 7; this module only imports its pieces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

from robot_models.homing.metrics import EpisodeRecord, JointOutcome, scorecard

from sim2real.provenance import code_sha, write_results
from .bench import EPISODE_COLUMNS, compact, expand, git_sha, prior_for, run_episode
from .geometry import BUNDLE_SHA, C1, J2, ROLE, FivebarGeometry
from .gff_rung import GATE_DEG, KINEMATIC_JSON, MODELS, N_STARTS, RUNG, ZERO_VS_KINEMATIC_DEG, _strip_j1, _vs_twin, real_lane_starts, \
    step_peaks, trips, verdict
from .gravity_ff import COMP, GravityFF
from .mujoco_bench import kinematic_reference, twin_prior
from .mujoco_plant import BAM_WS_SRC, END_GROUP_MASS_SCALE, RUNAWAY_RAD_S, MujocoRigPlant, end_payload_parts, twin_contacts
from .plant import HIDDEN_GAP_ARCMIN, Start
from .procedures import HomingRefused

PASS = "claw"
ROW = "single_touch+gff"
CLAW_KG = (0.273365 + 0.029933) * END_GROUP_MASS_SCALE  # bam_ws docs/pick_tracking/claw_payload.py CASES["nominal"]: CAD hand + finger x1.2249
CLAW_COMP = Path("/home/bam/bam_ws/docs/pick_tracking/data/gravity_params_claw_nominal_2026-11-13.json")
MASSES = {"claw": 1.0, "claw+22%": END_GROUP_MASS_SCALE}
MASS_LABEL = {"claw": "claw (plate out)", "claw+22%": "claw, end group +22 %"}
COMPS = {"plate comp": COMP, "claw comp": None}  # None: --comp (CLAW_COMP)
FF_SCALES = (0.75, 1.0, 1.25)
FF_LABEL = {0.75: "ff -25 %", 1.0: "ff nominal", 1.25: "ff +25 %"}
# the bam_ws code the twin and the comp import, by path (mujoco_plant.BAM_WS_PATHS + home_button.HOME_BUTTON_PATHS, their packages only):
# WHY a scope (2026-11-13): the bam_ws main checkout carries peers' uncommitted AGENTS.md / uv.lock edits that no import reads
BAM_WS_SCOPE = ("src/dev/bam_fb_test_rig/bam_fb_test_rig", "src/dev/bam_fivebar/bam_fivebar", "src/dev/bam_fivebar_recovery/bam_fivebar_recovery",
                "src/dev/bam_rack_twin/records", "src/core/bam_robot_descriptions/src", "src/core/mdp/agent/world_model/bam_aruco/bam_aruco",
                "src/core/mdp/agent/actuators/moteus_servo/src", "src/core/mdp/agent/actuators/gear_backlash/src",
                "src/core/mdp/env/cad2robot_payload/cad2robot_payload",
                "src/core/mdp/agent/actor/trajectory_generation/five_bar_kin_dyn/src/five_bar")


def config_name(comp: str, mass: str, ff: float) -> str:
    return " · ".join((ROW, "real form", MASS_LABEL[mass], comp, FF_LABEL[ff]))


def configs() -> list[tuple[str, str, float]]:
    out = [("claw comp", "claw+22%", ff) for ff in FF_SCALES] + [("claw comp", "claw", 1.0)]
    return out + [("plate comp", "claw", 1.0), ("plate comp", "claw+22%", 1.0)]


def with_comp(row, comp: str):
    """``row`` (a RealRow) with its gravity feed-forward planned from ``comp`` (a file name in the comp dir or an absolute path)."""
    target = row.procedure
    while not isinstance(target, GravityFF):
        target = target.inner
    target.comp_name = str(comp)
    return row


def run_one(comp_label: str, comp: str, mass: str, ff: float, model: str, start: Start, prior, twin) -> tuple[dict, dict]:
    """One episode (gff_rung.run_one's body, the plant's payload and the comp as inputs)."""
    from .real_bench import RealRow  # noqa: PLC0415

    name = config_name(comp_label, mass, ff)
    plant = MujocoRigPlant(model, end_mass_scale=MASSES[mass], runaway_rad_s=RUNAWAY_RAD_S, end_payload_kg=CLAW_KG)
    procedure = with_comp(RealRow(ROW, ff_scale=ff), comp)
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
    comp_label, comp, mass, ff, model, start, contacts = args
    prior = prior_for(FivebarGeometry())
    twin = twin_prior(prior, contacts)
    t0 = time.time()
    try:
        record, notes = run_one(comp_label, comp, mass, ff, model, start, prior, twin)
    except Exception as error:  # a crash is an outcome, recorded (never a silent drop from the denominator)
        record = EpisodeRecord(config_name(comp_label, mass, ff), f"{RUNG} · {model}", start.name, False,
                               f"crashed: {type(error).__name__}: {error}", None, (),
                               tuple(JointOutcome(j, None, None, HIDDEN_GAP_ARCMIN[j] / 60.0) for j in (J2, C1))).to_dict()
        notes = {"crash": repr(error)}
    return comp_label, mass, ff, model, start.name, record, notes, time.time() - t0


# WHY a cache (tests/test_homing_claw_rung_cache_1113.py): fleet-throttle's memory guard SIGTERMed a pool worker in the first run; the Pool
# replaced it but lost its task, and imap_unordered waited forever at 283 of 288 with no results file. Each episode lands here as it
# finishes, so a rerun with the same --cache only runs what is missing.
CACHE_KEYS = ("comp", "mass", "ff", "model", "start", "record", "notes", "seconds")


def append_cache(path: Path, output: tuple) -> None:
    with Path(path).open("a") as handle:
        handle.write(json.dumps(dict(zip(CACHE_KEYS, output, strict=True)), default=str) + "\n")


def load_cache(path: Path) -> list[tuple]:
    path = Path(path)
    if not path.is_file():
        return []
    outputs = []
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:  # a line torn by a killed process: that episode simply runs again
            continue
        outputs.append(tuple(row[key] for key in CACHE_KEYS))
    return outputs


def _key(comp: str, mass: str, ff: float, model: str, start: str) -> tuple:
    return comp, mass, round(float(ff), 6), model, start


def pending(jobs: list, done: list[tuple]) -> list:
    """The jobs whose (comp, mass, ff, model, start) the cache does not hold."""
    have = {_key(*output[:5]) for output in done}
    return [job for job in jobs if _key(job[0], job[2], job[3], job[4], job[5].name) not in have]


def readiness(verdicts: dict) -> dict:
    """Per comp: READY when every (model, case) its form names passes (module docstring)."""
    out = {}
    for comp_label in COMPS:
        needed = [config_name(c, m, f) for c, m, f in configs() if c == comp_label]
        failed = [f"{model}: {name}" for name in needed for model in MODELS if not ((verdicts.get(model) or {}).get(name) or {}).get("pass")]
        out[comp_label] = {"ready": not failed, "judged_on": needed, "failed": failed}
    return out


def run_bench(comp_path: Path, *, n_starts: int = N_STARTS, workers: int = 6, cache: Path | None = None) -> dict:
    t0 = time.time()
    comps = {"plate comp": COMP, "claw comp": str(comp_path)}
    payload = json.loads(Path(comp_path).read_text())
    if abs(float(payload["masses"]["disc_mass"]) - CLAW_KG) > 1e-3:
        raise SystemExit(f"REFUSED: {comp_path} carries disc_mass {payload['masses']['disc_mass']} kg, not the claw's {CLAW_KG:.4f}")
    geometry = FivebarGeometry()
    prior = prior_for(geometry)
    starts = real_lane_starts(n_starts)
    from .bench import named_rests  # noqa: PLC0415

    rest = {s.name: s for s in named_rests(geometry, prior)}
    contacts = twin_contacts({+1: rest["on_seek_stops"], -1: rest["lower_corner"]})
    jobs = [(c, comps[c], m, f, model, start, contacts) for (c, m, f) in configs() for model in MODELS for start in starts]
    jobs.sort(key=lambda job: job[4] != "B1")  # gff_rung's WHY: B1's dead zone sets the wall time
    total = len(jobs)
    outputs = load_cache(cache) if cache is not None else []
    outputs = [o for o in outputs if _key(*o[:5]) in {_key(j[0], j[2], j[3], j[4], j[5].name) for j in jobs}]
    jobs = pending(jobs, outputs)
    print(f"{len(outputs)} episodes from the cache, {len(jobs)} to run", flush=True)

    def progress(output):
        outputs.append(output)
        if cache is not None:
            append_cache(cache, output)
        c, m, f, model, start, record, _, seconds = output
        print(f"[{len(outputs)}/{total}] {model} {config_name(c, m, f)} {start}: {record['outcome'][:90]} ({seconds:.0f} s)", flush=True)

    if workers > 1:
        import multiprocessing  # noqa: PLC0415

        # WHY maxtasksperchild: a worker's RSS grew to ~2.8 GB over ~40 episodes in the first run (load 60, swap full)
        with multiprocessing.get_context("fork").Pool(workers, maxtasksperchild=12) as pool:
            for output in pool.imap_unordered(_job, jobs, chunksize=1):
                progress(output)
    else:
        for job in jobs:
            progress(_job(job))
    episodes, episodes_vs_twin, notes, wall = {}, {}, {}, {}
    order = {s.name: k for k, s in enumerate(starts)}
    for c, m, f, model, start, record, note, seconds in sorted(outputs, key=lambda o: order[o[4]]):
        name = config_name(c, m, f)
        episodes.setdefault(model, {}).setdefault(name, []).append(compact(record))
        episodes_vs_twin.setdefault(model, {}).setdefault(name, []).append(compact(_vs_twin(record, note)))
        notes.setdefault(model, {}).setdefault(name, {})[start] = note
        wall.setdefault(model, {}).setdefault(name, []).append(round(seconds, 1))
    reference = kinematic_reference(KINEMATIC_JSON)
    kin = ((reference.get("cards") or {}))
    cards, cards_vs_twin, verdicts, peaks = {}, {}, {}, {}
    for model, by_name in episodes.items():
        for name, rows_ in by_name.items():
            card = scorecard([expand(r, name, f"{RUNG} · {model}") for r in rows_], gate_deg=GATE_DEG)
            twin_card = scorecard([expand(r, name, f"{RUNG} · {model}") for r in episodes_vs_twin[model][name]], gate_deg=GATE_DEG)
            kin_p95 = ((kin.get(model) or {}).get("single_touch") or {}).get("joint_angle_error_deg")
            cards.setdefault(model, {})[name] = card
            cards_vs_twin.setdefault(model, {})[name] = twin_card
            verdicts.setdefault(model, {})[name] = verdict(card, twin_card, kin_p95)
            by_start = notes[model][name].values()
            peaks.setdefault(model, {})[name] = {role: max((n.get("peak_powered_deg_s") or {}).get(role, 0.0) for n in by_start)
                                                 for role in ("J2", "C1")}
    any_plant = MujocoRigPlant(MODELS[0], settle_s=0.0, end_payload_kg=CLAW_KG)
    any_heavy = MujocoRigPlant(MODELS[0], settle_s=0.0, end_payload_kg=CLAW_KG, end_mass_scale=END_GROUP_MASS_SCALE)
    plate = MujocoRigPlant(MODELS[0], settle_s=0.0)
    l2 = lambda plant: float(plant.rig.model.body_mass[plant.rig.model.body("l2").id])  # noqa: E731
    return {
        "schema": "sim2real_homing_bench/1",
        "rig": "five-bar",
        "rung": RUNG,
        "pass": PASS,
        "row": ROW,
        "form": "real (real_bench.RealRow: bare, sag_proof, J1 held, J2 kept powered, +gff), the plant's end payload = the crab claw",
        "bundle_sha": BUNDLE_SHA,
        "sim2real_sha": git_sha(Path(__file__).resolve().parents[4]),
        "robot_models_sha": git_sha(Path("/home/bam/robot_models")),
        "bam_ws_sha": code_sha(BAM_WS_SRC.parent, scope=BAM_WS_SCOPE),
        "bam_ws_scope": list(BAM_WS_SCOPE),
        "bam_ws_whole_tree_sha": git_sha(BAM_WS_SRC.parent),
        "gate_deg": GATE_DEG,
        "zero_vs_kinematic_deg": ZERO_VS_KINEMATIC_DEG,
        "runaway_deg_s": math.degrees(RUNAWAY_RAD_S),
        "claw_kg": CLAW_KG,
        "end_group_kg": {"plate (CAD)": l2(plate), "claw": l2(any_plant), "claw+22%": l2(any_heavy)},
        "end_payload_removed": {k: v["mass_kg"] for k, v in end_payload_parts(plate.rig).items()},
        "comps": {"plate comp": COMP, "claw comp": str(comp_path)},
        "claw_comp_sha256": hashlib.sha256(Path(comp_path).read_bytes()).hexdigest(),
        "ff_scales": list(FF_SCALES),
        "models": list(MODELS),
        "procedures": [config_name(*c) for c in configs()],
        "starts": [s.name for s in starts],
        "scorecards": cards,
        "scorecards_vs_twin": cards_vs_twin,
        "verdicts": verdicts,
        "readiness": readiness(verdicts),
        "peak_powered_deg_s": peaks,
        "trips": trips(notes),
        "episode_columns": list(EPISODE_COLUMNS),
        "episodes": episodes,
        "episodes_vs_twin": episodes_vs_twin,
        "notes": notes,
        "wall_s": wall,
        "seconds": time.time() - t0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--comp", type=Path, default=CLAW_COMP)
    parser.add_argument("--starts", type=int, default=N_STARTS)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cache", type=Path, default=None, help="episodes JSONL: appended as they land, a rerun resumes from it")
    arguments = parser.parse_args(argv)
    results = run_bench(arguments.comp, n_starts=arguments.starts, workers=arguments.workers, cache=arguments.cache)
    written = write_results(arguments.out, results, indent=1, default=str, newline=True)
    for comp, ready in results["readiness"].items():
        print(f"{comp}: {'READY' if ready['ready'] else 'NOT READY'}  failed: {ready['failed'] or 'none'}")
    for model, by_name in results["verdicts"].items():
        for name, v in by_name.items():
            print(f"{model} {name}: reliability {v['reliability_pct']:.0f} %, zero p95 vs twin {v['zero_p95_vs_twin_deg']}, pass {v['pass']}, "
                  f"peak J2/C1 {results['peak_powered_deg_s'][model][name]}")
    print(f"provenance_clean {written['provenance_clean']}  {arguments.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
