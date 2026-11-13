"""The full-arm homing check: run ANY homing sequence on the bam_fb_v2 twin and say what it did - PEP 0047 (bam_ws), sim only.

    systemd-run --user --scope -q -p MemoryMax=16G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m sim2real.sim.homing.fullarm_check --sweep orders --out /home/bam/sim2real/src/sim2real/data/fullarm_check_orders_2026-11-13.json --workers 6

What "any sequence" means: a PEP 0002 ``HomingProcedure`` (``fullarm_procedures.FullArmHome``, or anything with ``plan`` / ``observe``)
whose sequences are robot_msgs ``JointCommandSequence``s over ``fullarm_plant.JOINTS``, run tick by tick by the
``JointCommandSequenceController`` (``bench.run_phase``) on ``fullarm_plant.FullArmHomingPlant``.

Every tick is checked twice for self-collision, because the two answers differ:

* **the CAD guard** - ``bam_cad_descriptions.self_collision.check_pose`` on the true link angles with the bundle's
  ``self_collision_wrist.json`` rules (the visual meshes, FCL, a 5 deg grid): a tick it calls ``contact_possible`` is a guard breach.
* **the twin's contact** - the plant's primitives touching (``fullarm_plant``'s self-contact scene): a tick with any is a self-contact.

What an episode reports (``EpisodeReport``): finished / outcome; time to home (the tick clock); each joint's zero error against the hidden
truth (``truth()["true_offset_rad"]``, wrapped to +-180 deg); each joint's identified gap against the hidden one; every stall the result
used, checked against the CAD stop it meant (within 1.0 deg, robot_models.homing.metrics); guard breaches and self-contacts (first time,
ticks, which pairs); each joint's peak powered speed against its ceiling and peak torque (and current) against its board's cap.
``scorecard`` (robot_models.homing.metrics) turns a list of them into the five PEP 0002 metrics; the extras sit beside it.

``replay_vs_real`` puts a real run's per-tick rows (wrist_home_v1's evidence JSON) beside the same plan on the twin from the same start: the
homing sim-to-real trace.

Every angle shown is in degrees; the arrays inside are SI unless named ``_deg``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from robot_models.homing.metrics import EpisodeRecord, JointOutcome, StallCheck, scorecard

from .bench import run_phase
from .fullarm_plant import (
    CLAW,
    FIVEBAR,
    J1,
    JOINTS,
    KT_NM_PER_A,
    BOARD_MAX_NM,
    ROLE,
    W1,
    W2,
    W3,
    WRIST,
    WRIST_SPEED_CEILING_RAD_S,
    ArmStart,
    FullArmHomingPlant,
    StartRefused,
    arm_prior,
)
from .mujoco_plant import BAM_WS_SRC
from .procedures import HomingRefused

GATE_DEG = 0.1  # the MuJoCo rung's zero gate (gff_rung.GATE_DEG, wrist.GATE_DEG), frozen
MAX_EPISODE_S = 400.0
SPEED_CEILING_RAD_S = {J1: 1.5, **{j: 1.5 for j in FIVEBAR}, **{j: WRIST_SPEED_CEILING_RAD_S for j in WRIST}, CLAW: 1.5}
HOME_CRAIG_DEG = (91.01, -126.438)  # gff_rung.HOME_CRAIG_DEG: the homed map's home
REAL_OFFSETS_DEG = ((0.0, 0.0), (0.0, -10.0), (4.0, 0.0), (4.0, -10.0))  # gff_rung.REAL_OFFSETS_DEG: the real lane's five-bar starts
REAL_V1_JSON = Path("/archive/datasets/bam_rig/rack_2026-11-13/wrist_home_v1/wrist_home_v1_172448.json")
SOBOL_SEED = 20261113
# WHY its own source (default bam_ws main): the guard landed on main (35f9d1f0b) and the bam_fb_v2 comp is still on a lane
# (SIM2REAL_BAM_WS_SRC may point there); the guard is read from main unless told otherwise
SELF_COLLISION_SRC = Path(os.environ.get("SIM2REAL_SELF_COLLISION_SRC", "/home/bam/bam_ws/src"))


# ---------------------------------------------------------------------------------------------------------------- the CAD guard


def self_collision_module():
    """bam_cad_descriptions.self_collision, loaded from its file alone. WHY not ``import bam_cad_descriptions``: the package's __init__ pulls
    the whole description stack (bam_robot_descriptions, robot_msgs' URDF layer); the guard itself is pure (json + math)."""
    import importlib.util  # noqa: PLC0415
    import sys  # noqa: PLC0415

    name = "_bam_cad_descriptions_self_collision"
    if name not in sys.modules:
        path = SELF_COLLISION_SRC / "dev" / "bam_cad_descriptions" / "bam_cad_descriptions" / "self_collision.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def cad_rules():
    """bam_cad_descriptions' rules for bam_fb_v2's wrist (self_collision_wrist.json)."""
    from . import fullarm_home as fh  # noqa: PLC0415

    return self_collision_module().rules_from_bundle(fh.v2_root() / "self_collision_wrist.json")


def guard_ticks(log: dict, rules) -> list[tuple[int, tuple[str, ...]]]:
    """(tick, rules breached) for every logged tick the CAD guard calls contact_possible."""
    guard = self_collision_module()
    index = {j: JOINTS.index(j) for j in (W1, W2, W3, CLAW)}
    out = []
    for k, row in enumerate(log["link"]):
        verdict = guard.check_pose({j: float(row[i]) for j, i in index.items()}, rules)
        if not verdict.safe:
            out.append((k, tuple(name for name, v in verdict.per_rule.items() if v == guard.CONTACT_POSSIBLE)))
    return out


# ---------------------------------------------------------------------------------------------------------------- one episode


def wrap_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


@dataclass
class EpisodeReport:
    procedure: str
    environment: str
    start: str
    family: str
    finished: bool
    outcome: str
    time_s: float | None
    zero_error_deg: dict
    gap_identified_deg: dict
    gap_truth_deg: dict
    stalls: list
    guard_breach_ticks: int
    guard_first_s: float | None
    guard_rules: list
    self_contact_ticks: int
    self_contact_first_s: float | None
    self_contact_pairs: list
    peak_speed_deg_s: dict
    speed_ceiling_deg_s: dict
    peak_torque_nm: dict
    torque_cap_nm: dict
    peak_current_a: dict
    start_settled_deg: dict
    witness_deg: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    trace: dict | None = None

    def record(self, scored: Sequence[str]) -> EpisodeRecord:
        """robot_models' EpisodeRecord over the ``scored`` joints (J1 is held and never homed in the real form: never scored)."""
        joints = tuple(JointOutcome(j, self.zero_error_deg.get(ROLE[j]), self.gap_identified_deg.get(ROLE[j]), self.gap_truth_deg[ROLE[j]])
                       for j in scored)
        stalls = tuple(StallCheck(**s) for s in self.stalls)
        return EpisodeRecord(self.procedure, self.environment, self.start, self.finished, self.outcome, self.time_s, stalls, joints)

    @property
    def safe(self) -> bool:
        return self.guard_breach_ticks == 0 and self.self_contact_ticks == 0


def run_episode(procedure, plant: FullArmHomingPlant, start: ArmStart, prior, *, environment: str = "", rules=None,
                trace_every: int = 0, limit_s: float = MAX_EPISODE_S) -> EpisodeReport:
    """One episode of ``procedure`` from ``start`` on ``plant`` (module docstring). ``trace_every`` > 0 keeps every n-th tick's qpos and
    joint log for a video / a trace plot."""
    from .plant import PlantTrip  # noqa: PLC0415,F401 - run_phase scores a trip as a phase status

    rules = cad_rules() if rules is None else rules
    plant.reset(start)
    phases, outcome = [], "done"
    while (sequence := procedure.plan(prior, phases)) is not None:
        phase = run_phase(plant, sequence, limit_s=limit_s)
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
        except KeyError as error:  # a step the observer reads never ended (the controller skipped it): an outcome, not a crash
            outcome, finished = f"refused: no reading for step {error}", False
    truth = plant.truth()
    log = plant.log
    stalls = []
    for phase_index, tick, joint, side in (procedure.references if finished else []):
        k = phases[phase_index].log["plant_offset"] + tick
        link = log["link"][k][JOINTS.index(joint)]
        cad = math.degrees(prior.stops.q_rad(joint, side))
        # WHY wrapped onto the CAD's turn: C1 is a crank - its link reads -162.23 deg at the stop the CAD calls 197.77
        stalls.append({"joint": joint, "side": side, "link_deg": cad + wrap_deg(math.degrees(link) - cad), "cad_deg": cad})
    zero, gap = {}, {}
    for joint in JOINTS:
        zero[ROLE[joint]] = None
        gap[ROLE[joint]] = None
        if result is not None and result.zero(joint) is not None:
            zero[ROLE[joint]] = wrap_deg(math.degrees(result.zero(joint).offset_rad - truth["true_offset_rad"][joint]))
            entry = result.backlash.get(joint)
            if entry is not None and entry.gap_observable:
                gap[ROLE[joint]] = math.degrees(entry.model.gap_rad)
    breaches = guard_ticks(log, rules)
    touched = [(k, pairs) for k, pairs in enumerate(log["self_contact"]) if pairs]
    t = log["t"]
    report = EpisodeReport(
        procedure=procedure.name, environment=environment or f"mujoco/{plant.kind}/{plant.truth_name}", start=start.name,
        family=start.family, finished=finished, outcome=outcome, time_s=plant.time if finished else None, zero_error_deg=zero,
        gap_identified_deg=gap, gap_truth_deg={ROLE[j]: math.degrees(m.gap_rad) for j, m in truth["backlash"].items()}, stalls=stalls,
        guard_breach_ticks=len(breaches), guard_first_s=t[breaches[0][0]] if breaches else None,
        guard_rules=sorted({r for _, rs in breaches for r in rs}), self_contact_ticks=len(touched),
        self_contact_first_s=t[touched[0][0]] if touched else None, self_contact_pairs=sorted({p for _, ps in touched for p in ps}),
        peak_speed_deg_s={ROLE[j]: round(math.degrees(v), 2) for j, v in plant.peak_powered_rad_s.items()},
        speed_ceiling_deg_s={ROLE[j]: round(math.degrees(v), 1) for j, v in SPEED_CEILING_RAD_S.items()},
        peak_torque_nm={ROLE[j]: round(v, 4) for j, v in plant.peak_torque_nm.items()},
        torque_cap_nm={ROLE[j]: v for j, v in BOARD_MAX_NM.items()},
        peak_current_a={ROLE[j]: round(v / KT_NM_PER_A[j], 3) for j, v in plant.peak_torque_nm.items()},
        start_settled_deg=dict(truth["start_settled_deg"]), witness_deg=dict(procedure.notes.get("witness_deg", {})),
        notes={k: v for k, v in procedure.notes.items() if k in ("witness_refused", "phase1_parked")})
    if trace_every:
        report.trace = trace_of(plant, phases, every=trace_every)
    return report


def trace_of(plant: FullArmHomingPlant, phases, every: int = 3) -> dict:
    """Every ``every``-th tick: t, the full qpos (for a video), the seven link angles, efforts and the step running (for a plot)."""
    log = plant.log
    steps = []
    for phase in phases:
        offset = phase.log["plant_offset"]
        for k, index in enumerate(phase.log["step"]):
            steps.append((offset + k, phase.sequence.steps[min(index, len(phase.sequence.steps) - 1)].name))
    step_at = dict(steps)
    keep = range(0, len(log["t"]), every)
    return {"t": [log["t"][k] for k in keep], "qpos": [log["qpos"][k] for k in keep] if "qpos" in log else None,
            "link_deg": [[round(math.degrees(v), 3) for v in log["link"][k]] for k in keep],
            "effort_nm": [[round(v, 4) for v in log["effort"][k]] for k in keep],
            "self_contact": [log["self_contact"][k] for k in keep], "step": [step_at.get(k, "") for k in keep], "joints": list(JOINTS)}


# ---------------------------------------------------------------------------------------------------------------- starts


def _sobol(n: int, dims: int, seed: int) -> np.ndarray:
    from scipy.stats import qmc  # noqa: PLC0415

    return qmc.Sobol(dims, scramble=True, seed=seed).random(n)


def real_v1_start(path: Path = REAL_V1_JSON) -> ArmStart:
    """The rack's wrist_home_v1 start (2026-11-13 10:24), from where each wrist seek stalled: start = stop - dir x travel."""
    document = json.loads(path.read_text())
    wrist = []
    for joint, stop_dir in ((W1, +1), (W2, -1), (W3, +1)):
        seek = document["joints"][joint]["seek"]
        wrist.append(round(stop_dir * 169.851 - stop_dir * float(seek["travel_deg"]), 2))
    return ArmStart("rack wrist_home_v1 start (10:24)", *HOME_CRAIG_DEG, tuple(wrist), 30.0, family="real")


def starts(family: str, n: int = 8, seed: int = SOBOL_SEED) -> list[ArmStart]:
    """Start families. ``real``: the rack's V1 wrist start on the real lane's five-bar offsets. ``wrist``: the wrist and claw anywhere
    (Sobol). ``adversarial``: the wrist where a one-joint-at-a-time sweep can meet the forearm (|W2| > 105 with W1 on the far side, W1 past
    105 already, the claw open with W2 past 130 and W3 past 50) and joints resting on a stop."""
    out = []
    if family == "real":
        base = real_v1_start()
        for d2, dc in REAL_OFFSETS_DEG:
            out.append(ArmStart(f"real V1 wrist, five-bar home{d2:+.0f}/{dc:+.0f}", HOME_CRAIG_DEG[0] + d2, HOME_CRAIG_DEG[1] + dc,
                                base.wrist_deg, 30.0, family="real"))
        return out
    if family == "wrist":
        for k, u in enumerate(_sobol(n, 4, seed)):
            w = tuple(round(-165.0 + 330.0 * x, 1) for x in u[:3])
            out.append(ArmStart(f"wrist sobol {k}", *HOME_CRAIG_DEG, w, round(75.0 * u[3], 1), family="wrist"))
        return out
    if family == "adversarial":
        named = [("W1 far side, W2 past 105", (-120.0, 140.0, 0.0), 20.0), ("W1 far side, W2 past 105 (neg)", (-150.0, -130.0, 40.0), 10.0),
                 ("W1 past 105, W2 past 105 (corner)", (125.0, 125.0, -30.0), 5.0), ("W1 -60, W2 160", (-60.0, 160.0, 90.0), 15.0),
                 ("claw open, W2 140, W3 60", (0.0, 140.0, 60.0), 75.0), ("claw open, W2 -150, W3 -120", (40.0, -150.0, -120.0), 70.0),
                 ("W1 on its + stop", (169.0, 30.0, 0.0), 20.0), ("W2 on its - stop, W1 120", (120.0, -169.0, 0.0), 10.0),
                 ("W2 100 (guard edge), W1 -150", (-150.0, 100.0, 10.0), 20.0), ("all three at -160", (-160.0, -160.0, -160.0), 40.0)]
        return [ArmStart(name, *HOME_CRAIG_DEG, w, claw, family="adversarial") for name, w, claw in named]
    raise ValueError(f"family must be real, wrist or adversarial, not {family!r}")


# ---------------------------------------------------------------------------------------------------------------- sweeps


def make_procedure(spec: dict):
    from .fullarm_procedures import FullArmHome  # noqa: PLC0415

    return FullArmHome(**spec)


def _job(job: dict) -> dict:
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    from .fullarm_procedures import FullArmHome  # noqa: F401,PLC0415

    belt = job.get("belt_top_m")
    plant = FullArmHomingPlant(job["kind"], job.get("truth", "cad"), belt_top_m=belt, settle_s=3.0 if job.get("hanging") else 0.5,
                               contact_timeconst_s=job.get("contact_timeconst_s"))
    table = None
    if job.get("table"):
        table = table_from_json(job["table"])
    prior = arm_prior(table, phase_error_deg=job.get("phase_error_deg", 0.0))
    procedure = make_procedure(job["procedure"])
    if job.get("hanging"):
        from .fullarm_plant import hanging_start  # noqa: PLC0415

        start = hanging_start(plant, job["start"]["name"])
    else:
        start = ArmStart(**job["start"])
    began = time.time()
    try:
        report = run_episode(procedure, plant, start, prior, trace_every=job.get("trace_every", 0))
    except StartRefused as error:
        return {"job": job, "refused_start": str(error)}
    out = asdict(report)
    out["wall_s"] = round(time.time() - began, 1)
    out["job_key"] = job["key"]
    return out


def table_to_json(table) -> list:
    return [{"joint": e.joint, "kind": e.model.kind, "gap_rad": e.model.gap_rad, "compliance_rad_per_nm": e.model.compliance_rad_per_nm,
             "gap_observable": e.gap_observable, "compliance_observable": e.compliance_observable, "source": e.source} for e in table.entries]


def table_from_json(rows: list):
    from robot_models.homing.types import BacklashModel, BacklashTable, JointBacklash  # noqa: PLC0415

    return BacklashTable(tuple(JointBacklash(r["joint"], BacklashModel(r["kind"], r["gap_rad"], r["compliance_rad_per_nm"]),
                                             r["gap_observable"], r["compliance_observable"], r["source"]) for r in rows))


def identify_job(kind: str, start: ArmStart, order: str = "park_first", truth: str = "cad") -> dict:
    """identify_backlash once on ``kind``: its table (JSON rows) and its episode report."""
    from .fullarm_procedures import identify_backlash  # noqa: PLC0415

    plant = FullArmHomingPlant(kind, truth)
    prior = arm_prior()
    procedure = identify_backlash(order)
    plant.reset(start)
    phases = []
    while (sequence := procedure.plan(prior, phases)) is not None:
        phase = run_phase(plant, sequence, limit_s=MAX_EPISODE_S)
        phases.append(phase)
        if phase.status != "done":
            return {"kind": kind, "table": None, "outcome": f"{phase.status}: {phase.message}", "time_s": plant.time}
    result = procedure.observe(prior, phases)
    truth_backlash = hidden_truth(kind)
    rows = table_to_json(result.backlash)
    return {"kind": kind, "table": rows, "outcome": "done", "time_s": plant.time,
            "gap_error_deg": {ROLE[e.joint]: (round(math.degrees(e.model.gap_rad - truth_backlash[e.joint].gap_rad), 4) if e.gap_observable else None)
                              for e in result.backlash.entries},
            "compliance_identified_deg_per_nm": {ROLE[e.joint]: round(math.degrees(e.model.compliance_rad_per_nm), 4) for e in result.backlash.entries},
            "compliance_truth_deg_per_nm": {ROLE[j]: round(math.degrees(m.compliance_rad_per_nm), 4) for j, m in truth_backlash.items()}}


def hidden_truth(kind: str) -> dict:
    from .fullarm_plant import hidden_backlash  # noqa: PLC0415

    return hidden_backlash(kind)


SCORED = (JOINTS[1], JOINTS[2], W1, W2, W3, CLAW)
SCORED_FIVEBAR = (JOINTS[1], JOINTS[2])  # J2, C1, the wrist and the claw; J1 is held, never homed (real form)


def summarize(reports: list[dict], scored=SCORED) -> dict:
    """Per (procedure, environment): robot_models' scorecard over the scored joints plus the safety and effort extras."""
    groups: dict = {}
    for r in reports:
        if "refused_start" in r:
            continue
        groups.setdefault((r["procedure"], r["environment"]), []).append(r)
    out = {}
    for (procedure, environment), rows in groups.items():
        records = []
        for r in rows:
            joints = tuple(JointOutcome(j, r["zero_error_deg"].get(ROLE[j]), r["gap_identified_deg"].get(ROLE[j]), r["gap_truth_deg"][ROLE[j]])
                           for j in scored)
            records.append(EpisodeRecord(procedure, environment, r["start"], r["finished"], r["outcome"], r["time_s"],
                                         tuple(StallCheck(**s) for s in r["stalls"]), joints))
        card = scorecard(records, gate_deg=GATE_DEG)
        card.update({
            "safe_pct": round(100.0 * sum(1 for r in rows if r["guard_breach_ticks"] == 0 and r["self_contact_ticks"] == 0) / len(rows), 1),
            "guard_breach_episodes": sum(1 for r in rows if r["guard_breach_ticks"]),
            "self_contact_episodes": sum(1 for r in rows if r["self_contact_ticks"]),
            "silent_wrong": sum(1 for r in rows if r["finished"] and any(abs(v) > GATE_DEG for k, v in r["zero_error_deg"].items()
                                                                           if v is not None and k != "J1")),
            "refused": sum(1 for r in rows if r["outcome"].startswith("refused")),
            "tripped": sum(1 for r in rows if r["outcome"].startswith("tripped")),
            "worst_speed_deg_s": {k: max(r["peak_speed_deg_s"][k] for r in rows) for k in rows[0]["peak_speed_deg_s"]},
            "worst_torque_nm": {k: max(r["peak_torque_nm"][k] for r in rows) for k in rows[0]["peak_torque_nm"]},
            "worst_zero_deg": {k: max((abs(r["zero_error_deg"][k]) for r in rows if r["finished"] and r["zero_error_deg"][k] is not None),
                                      default=None) for k in rows[0]["zero_error_deg"]},
            "outcomes": [(r["start"], r["outcome"][:120]) for r in rows if r["outcome"] != "done"],
        })
        out[f"{procedure} | {environment}"] = card
    return out


def sweep_jobs(sweep: str, *, n_wrist: int = 12) -> list[dict]:
    jobs = []

    def add(procedure: dict, kind: str, start: ArmStart, **extra):
        key = f"{procedure} {kind} {start.name} {extra.get('tag', '')}"
        jobs.append({"key": key, "procedure": procedure, "kind": kind, "start": asdict(start), **extra})

    if sweep == "orders":
        family_starts = starts("real")[:1] + starts("wrist", n_wrist) + starts("adversarial")
        for order in ("zach_v1", "park_first"):
            for start in family_starts:
                add({"order": order}, "B0", start)
    elif sweep == "fivebar":
        # the five-bar alone (wrist braked), the ease-off on and off (PEP 0047 "The motor-driven five-bar home"): every start family plus
        # the rack's hanging-on-the-belt rest
        family_starts = starts("real") + starts("wrist", n_wrist) + starts("adversarial")
        for ease in (True, False):
            spec = {"fivebar_only": True, "wrist_during_fivebar": "brake", "ease_c1_first": ease,
                    "name": f"fivebar_home[single_touch+gff, J2 first seek 0.05, ease C1 {'on' if ease else 'off'}]"}
            for start in family_starts:
                add(spec, "B0", start)
            hang = ArmStart("hanging on the belt", *HOME_CRAIG_DEG, family="hanging")
            for kind in ("B0", "B1", "B2"):
                add(spec, kind, hang, hanging=True, belt_top_m=0.0, tag=kind)
    elif sweep == "fivebar_soft":
        # the same with the stop / loop pairs at a 10 ms time constant (the bundle's 2 ms): is the kick the twin's stiff contacts?
        for job in sweep_jobs("fivebar", n_wrist=n_wrist):
            job["contact_timeconst_s"] = 0.01
            job["key"] += " soft"
            job["procedure"] = {**job["procedure"], "name": job["procedure"]["name"] + " [stops 10 ms]"}
            jobs.append(job)
    elif sweep == "wrist_policy":
        for policy in ("hold", "brake"):
            for start in starts("real") + starts("wrist", 4):
                add({"order": "park_first", "wrist_during_fivebar": policy}, "B1", start)
    elif sweep == "comps":
        for comp in ("plate", "nominal", "v2_cad"):
            for start in starts("real"):
                add({"order": "park_first", "comp": comp}, "B0", start)
    else:
        raise ValueError(f"unknown sweep {sweep!r}")
    return jobs


def run_jobs(jobs: list[dict], workers: int = 6) -> list[dict]:
    if workers <= 1:
        return [_job(j) for j in jobs]
    from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415
    import multiprocessing  # noqa: PLC0415

    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        return list(pool.map(_job, jobs))


# ---------------------------------------------------------------------------------------------------------------- sim vs real


def real_v1_rows(path: Path = REAL_V1_JSON) -> dict:
    """wrist_home_v1's per-joint rows (t, q, tau, phase) from its evidence JSON, joint -> columns (rad, N.m, s from the joint's first row)."""
    document = json.loads(path.read_text())
    out = {}
    for joint in (W1, W2, W3):
        entry = document["joints"][joint]
        rows = entry.get("rows") or []
        if not rows:
            continue
        t0 = rows[0]["t"]
        zero = float(entry.get("zero_board_rad", 0.0))  # the board reading the run assigned joint 0: q_joint = q_board - zero
        out[joint] = {"t": [r["t"] - t0 for r in rows], "q": [r["q"] - zero for r in rows], "tau": [r.get("tau", math.nan) for r in rows],
                      "phase": [r.get("phase", "") for r in rows], "seek": entry.get("seek"), "config": entry.get("config")}
    return out


def replay_vs_real(path: Path = REAL_V1_JSON) -> dict:
    """wrist_home_v1 (Zach's wrist order, the claw closed first) on the twin from the rack run's start, beside the rack run: per joint the
    seek travel, the stall torque and the settle error at "0" (real: -8.6 / +5.3 / +14.4 deg at kp 15)."""
    from .fullarm_procedures import FullArmHome  # noqa: PLC0415

    from .fullarm_plant import AS_FOUND_1024  # noqa: PLC0415

    start = real_v1_start(path)
    plant = FullArmHomingPlant("B0", wrist_gains=AS_FOUND_1024)  # the gains that run had
    prior = arm_prior()
    procedure = FullArmHome(order="zach_v1", wrist_only=True, wrist_kp_nm_per_rev=AS_FOUND_1024[0])
    report = run_episode(procedure, plant, start, prior, trace_every=2)
    real = json.loads(path.read_text())
    sim_rows = report.trace
    per = {}
    for joint in (W1, W2, W3):
        role = ROLE[joint]
        seek = real["joints"][joint]["seek"]
        index = JOINTS.index(joint)
        steps = sim_rows["step"]
        seek_ticks = [k for k, s in enumerate(steps) if s == f"{role} seeks"]
        home_ticks = [k for k, s in enumerate(steps) if s == f"{role} to 0"]
        sim_travel = (abs(sim_rows["link_deg"][seek_ticks[-1]][index] - sim_rows["link_deg"][seek_ticks[0]][index]) if seek_ticks else None)
        sim_settle = sim_rows["link_deg"][home_ticks[-1]][index] if home_ticks else None
        per[role] = {"real_travel_deg": round(float(seek["travel_deg"]), 2), "sim_travel_deg": None if sim_travel is None else round(sim_travel, 2),
                     "real_stall_nm": round(float(seek["torque_nm"]), 3),
                     "sim_stall_nm": round(max(abs(sim_rows["effort_nm"][k][index]) for k in seek_ticks), 3) if seek_ticks else None,
                     "real_settle_deg": round(float(real["joints"][joint]["at_zero_deg"]), 2) if "at_zero_deg" in real["joints"][joint] else None, "sim_settle_deg": None if sim_settle is None else round(sim_settle, 2)}
    summary = asdict(report)
    trace = summary.pop("trace")
    trace.pop("qpos", None)  # the poses are for a video; the page plots the joint angles
    real_rows = real_v1_rows(path)
    return {"start": asdict(start), "report": summary, "per_joint": per, "sim_trace": trace,
            "real_rows": {ROLE[j]: {k: v for k, v in rows.items() if k in ("t", "q", "tau", "phase")} for j, rows in real_rows.items()}}


# ---------------------------------------------------------------------------------------------------------------- CLI


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sweep", default="orders")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--n-wrist", type=int, default=12)
    args = parser.parse_args(argv)
    from sim2real.provenance import code_sha, write_results  # noqa: PLC0415

    began = time.time()
    if args.sweep == "replay":
        results = {"replay": replay_vs_real()}
    elif args.sweep == "backlash":
        results = backlash_ladder(workers=args.workers)
    elif args.sweep == "backlash_rerun":
        results = rerun_with_tables(json.loads(args.out.read_text()), workers=args.workers)
    else:
        jobs = sweep_jobs(args.sweep, n_wrist=args.n_wrist)
        reports = run_jobs(jobs, args.workers)
        results = {"reports": reports, "summary": summarize(reports, SCORED_FIVEBAR if args.sweep == "fivebar" else SCORED)}
    results.update({"schema": "sim2real.fullarm_check/1", "sweep": args.sweep, "seconds": round(time.time() - began, 1),
                    "sim2real_sha": code_sha(Path(__file__)), "bam_ws_sha": code_sha(BAM_WS_SRC), "bundle": "bam_fb_v2 @ cad-exporter 09374d7"})
    write_results(args.out, results, default=str)
    print(json.dumps(results.get("summary", {k: v for k, v in results.items() if k != "reports"}), indent=1, default=str)[:6000])
    return 0


def rerun_with_tables(previous: dict, *, workers: int = 6) -> dict:
    """``previous`` (a backlash_ladder result) with its with-table home() rows run again on the current code (the tables it identified,
    unchanged); every other row kept as run."""
    kept = [r for r in previous["reports"] if "identified table" not in r.get("procedure", "")]
    jobs = []
    for r in previous["reports"]:
        if "identified table" in r.get("procedure", ""):
            kind = r["environment"].split("/")[1]
            start = next(s for s in starts("real") + starts("wrist", 2) if s.name == r["start"])
            jobs.append({"key": f"home with table {kind} {start.name}", "kind": kind, "start": asdict(start),
                         "table": previous["identified"][kind]["table"],
                         "procedure": {"order": "park_first", "name": "home[park_first+witness] + identified table"}})
    reports = kept + run_jobs(jobs, workers)
    return {"identified": previous["identified"], "reports": reports, "summary": summarize(reports),
            "rerun": "the with-table rows re-run with the five-bar ignoring the stored table (FullArmHome.fivebar_table False)"}


def backlash_ladder(*, workers: int = 6, n_starts: int = 6) -> dict:
    """identify_backlash once per hidden model (B1, B2) from the real start, then home() from ``n_starts`` starts on B0 / B1 / B2 with no
    table and with that model's identified table: the zero error the table buys, and the gap it identified."""
    start = starts("real")[0]
    identified = {kind: identify_job(kind, start) for kind in ("B1", "B2")}
    jobs = []
    family = starts("real") + starts("wrist", n_starts - 4)
    for kind in ("B0", "B1", "B2"):
        for start_ in family:
            base = {"procedure": {"order": "park_first"}, "kind": kind, "start": asdict(start_)}
            jobs.append({**base, "key": f"home no table {kind} {start_.name}"})
            if kind in identified and identified[kind]["table"]:
                jobs.append({**base, "key": f"home with table {kind} {start_.name}", "table": identified[kind]["table"],
                             "procedure": {"order": "park_first", "name": "home[park_first+witness] + identified table"}})
    reports = run_jobs(jobs, workers)
    return {"identified": identified, "reports": reports, "summary": summarize(reports)}


if __name__ == "__main__":
    raise SystemExit(main())
