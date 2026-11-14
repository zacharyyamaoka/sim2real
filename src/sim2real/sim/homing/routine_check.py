"""Run the full-arm homing routines (``fullarm_routine.ROWS``) over the ruler's start grid and environments (``routine_ruler``) - sim only.

    systemd-run --user --scope -q -p MemoryMax=24G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/sim2real/.venv/bin/python -m sim2real.sim.homing.routine_check --plan all --out /home/bam/sim2real/src/sim2real/data/homing_routine_2026-11-13.json --cache /home/bam/.cache/sim2real/homing_routine_2026-11-13.jsonl --workers 10

What runs (``plan_jobs``):

* ``GRID_ROWS`` on every grid cell, nominal environment;
* ``SUBSET_ROWS`` on the subset cells, nominal (the rows whose answer a quarter of the grid settles);
* ``PERTURBED_ROWS`` on the subset cells in every other environment (``+table`` only where a table can differ: B1, B2).

**One five-bar phase per (cell, environment).** Every READY row starts with the same phase 0 (single_touch_ready+gff, the wrist and
claw braked), so it is run once and each row carries on from a deep copy of the plant (``fullarm_check.run_episode(resume_phases=...)``).
Each row still plans its own phase 0 first, and a row whose plan differs from the shared one runs from scratch. ``test_homing_routine``
holds a branched episode equal to a full one, number for number.

**The plant** (``PLANT``): the belt as a contact (main's ``belt_top_m=0``) and stiff (``belt_solref``), the whole arm settled before
power-on (``settle_all``), and the five-bar's stop / loop pairs at 10 ms (``contact_timeconst_s`` with ``contact_timeconst_scope
"fivebar"``) - PEP 0047's evening finding: at the bundle's 2 ms the twin kicks J2 off its upper stops, which the real arm did not; the wrist
and claw stops keep the bundle's 2 ms.

**Every row is planned once, in its own process** (``preplan``): a row's two sequences do not depend on the start or the environment (the
five-bar's seeks and its walk to READY are open-loop from the CAD stops; phase 1 holds READY on the comp's gravity there), and planning them
builds the gravity comp's bench model - ~1.5 GB, which the machine's memory guard kills a worker for. Workers run the planned sequences
through ``Preplanned`` and never build the comp.

**The stored table** (option B's row): ``identify_backlash`` once per environment - press_reverse on ``CALIBRATION_START`` - and its wrist
and claw rows handed to the row's prior (calibrated once on this arm, as the rack would).

Every angle shown is in degrees.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import time
from dataclasses import asdict
from pathlib import Path

from . import routine_ruler as ruler

GRID_ROWS = ("zach_v1 @ READY", "park_first+witness @ READY", "multi x2 (3D-printer) @ READY", "press_reverse (backlash every home) @ READY",
             "park_first+witness+table @ READY")
SUBSET_ROWS = ("PEP 0047 (wrist at the five-bar's home)", "fast single @ READY", "multi x3 (3D-printer) @ READY")
PERTURBED_ROWS = ("park_first+witness @ READY", "multi x2 (3D-printer) @ READY", "press_reverse (backlash every home) @ READY",
                  "park_first+witness+table @ READY", "zach_v1 @ READY", "zach_v1+table @ READY")
# WHY a lighter plan past READY's map (2026-11-13 18:00, a machine at load 65-72: the full plan was ~4 h more): the "+table" rows are exact
# from their plain rows (table_derived); multi x2 ended as park_first did on 34 of READY's 36 starts (the other two: the near-stop plate
# stalls, refused in both by the tight witness) at its own, faster pace; and the subset rows' answers came from READY - so the other
# five-bar poses run V1 and park_first (the recommended routine's two paths), the perturbed twins those two and press_reverse (B1 / B2),
# and the subset rows past READY only PEP 0047
LIGHT_GRID_ROWS = ("zach_v1 @ READY", "park_first+witness @ READY")
LIGHT_PERTURBED_ROWS = ("park_first+witness @ READY", "press_reverse (backlash every home) @ READY", "zach_v1 @ READY")
LIGHT_SUBSET_ROWS = ("PEP 0047 (wrist at the five-bar's home)",)
TABLE_ENVIRONMENTS = ("B1", "B2")  # where a stored table can differ from B0's (B0: every gap 0)
CALIBRATION_START = {"name": "calibration: power lost at READY, claw plumb", "j2_deg": ruler.FIVEBAR_LEVELS["READY"][0],
                     "c1_deg": ruler.FIVEBAR_LEVELS["READY"][1], "wrist_deg": (1.167, 90.0, 0.0), "claw_deg": 30.0, "knee": -1,
                     "j1_deg": 0.0, "family": "calibration"}
CACHE_FIELDS = ("key", "row", "environment", "cell_index")


def plant_kwargs(environment: str) -> dict:
    from .fullarm_plant import BELT_STIFF_SOLREF  # noqa: PLC0415

    env = ruler.ENVIRONMENTS[environment]
    out = {"kind": env["kind"], "truth": env["truth"], "belt_top_m": 0.0, "settle_all": True, "belt_solref": BELT_STIFF_SOLREF,
           "contact_timeconst_s": 0.01, "contact_timeconst_scope": "fivebar", "log_qpos": False}
    if "wrist_friction" in env:
        out["wrist_friction"] = env["wrist_friction"]
    if "rotor_phase_deg" in env:
        out["rotor_phase_deg"] = dict(env["rotor_phase_deg"])
    return out


def prior_for(environment: str, table=None):
    from .fullarm_plant import arm_prior  # noqa: PLC0415

    env = ruler.ENVIRONMENTS[environment]
    return arm_prior(table, phase_error_deg=env.get("phase_error_deg", 0.0), rotor_phase_deg=env.get("rotor_phase_deg"))


def needs_table(row: str) -> bool:
    from .fullarm_routine import ROWS  # noqa: PLC0415

    return bool(ROWS[row].get("needs_table"))


def episode_key(row: str, environment: str, cell_name: str) -> str:
    return f"{row} | {environment} | {cell_name}"


# ---------------------------------------------------------------------------------------------------------------- planned once

PLANS: dict = {}  # row -> {"sequences": [phase 0, phase 1], "evidence_plan": [...], "notes": {...}} (``preplan``; set before the pool forks)


def preplan(rows) -> dict:
    """Each row's sequences, planned once on the nominal prior (module docstring). Run it in a process of its own (``preplan_file``)."""
    from .fullarm_routine import make_row  # noqa: PLC0415

    prior = prior_for(ruler.NOMINAL)
    out = {}
    for row in rows:
        procedure = make_row(row)
        first = procedure.plan(prior, [])
        second = procedure.plan(prior, [None])  # WHY a placeholder: FullArmHome plans phase 1 from len(so_far) alone
        out[row] = {"sequences": [first, second], "evidence_plan": list(getattr(procedure, "evidence_plan", [])),
                    "notes": copy.deepcopy(dict(procedure.notes))}
    return out


def preplan_file(rows, path: Path) -> dict:
    """``preplan`` in a fresh interpreter, pickled to ``path`` and loaded back: this process never holds the comp's model."""
    import pickle  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    path = Path(path)
    code = ("import pickle, sys; from sim2real.sim.homing.routine_check import preplan; "
            f"pickle.dump(preplan({list(rows)!r}), open({str(path)!r}, 'wb'))")
    subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ, "OPENBLAS_NUM_THREADS": "1"})
    return pickle.loads(path.read_bytes())


class Preplanned:
    """A row's procedure that runs its planned sequences (``PLANS``) and observes as itself. Fresh per episode."""

    def __init__(self, procedure, plan: dict):
        self.procedure = procedure
        self.sequences = list(plan["sequences"])
        if hasattr(procedure, "evidence_plan"):
            procedure.evidence_plan = list(plan["evidence_plan"])
        procedure.notes.update(copy.deepcopy(plan["notes"]))

    @property
    def name(self) -> str:
        return self.procedure.name

    @property
    def notes(self) -> dict:
        return self.procedure.notes

    @property
    def references(self) -> list:
        return self.procedure.references

    @property
    def wrist_pose(self):
        return getattr(self.procedure, "wrist_pose", None)

    def plan(self, prior, so_far):
        k = len(so_far)
        return self.sequences[k] if k < len(self.sequences) else None

    def observe(self, prior, phases):
        return self.procedure.observe(prior, phases)


def procedure_for(row: str):
    from .fullarm_routine import make_row  # noqa: PLC0415

    return Preplanned(make_row(row), PLANS[row]) if row in PLANS else make_row(row)


# ---------------------------------------------------------------------------------------------------------------- the plan


def plan_jobs(plan: str = "all") -> list[dict]:
    """One job per (cell, environment): the rows to run there. ``plan``: all, nominal (the grid and the subset rows), perturbed, smoke."""
    cells = ruler.grid_cells()
    subset = {c["name"] for c in ruler.subset_cells()}
    jobs = []
    first = next(iter(ruler.FIVEBAR_LEVELS))
    for index, cell in enumerate(cells):
        light = plan == "light" and cell["family"] != first
        if plan in ("all", "nominal", "smoke", "light"):
            grid_rows = LIGHT_GRID_ROWS if light else GRID_ROWS
            subset_rows = LIGHT_SUBSET_ROWS if light else SUBSET_ROWS
            rows = list(grid_rows) + (list(subset_rows) if cell["name"] in subset else [])
            jobs.append({"cell_index": index, "cell": cell, "environment": ruler.NOMINAL, "rows": rows})
        if plan in ("all", "perturbed", "light") and cell["name"] in subset:
            for environment in ruler.ENVIRONMENTS:
                if environment == ruler.NOMINAL:
                    continue
                perturbed_rows = LIGHT_PERTURBED_ROWS if plan == "light" else PERTURBED_ROWS
                rows = [r for r in perturbed_rows if not needs_table(r) or environment in TABLE_ENVIRONMENTS]
                if plan == "light" and environment not in TABLE_ENVIRONMENTS:
                    # press_reverse's point is the backlash (B1, B2); elsewhere its walk-across timed out on the folded cells already
                    rows = [r for r in rows if not r.startswith("press_reverse")]
                jobs.append({"cell_index": index, "cell": cell, "environment": environment, "rows": rows})
    if plan == "smoke":
        jobs = [j for j in jobs if j["cell_index"] in (22,)]
    # WHY this order (a loaded machine, 2026-11-13): READY's 6 x 6 wrist map first (the answer to the order and the touch), then the
    # perturbed subset (backlash, friction, mass, calibration), then the other three five-bar poses - a run stopped early still answers
    first = next(iter(ruler.FIVEBAR_LEVELS))
    jobs.sort(key=lambda j: (0 if (j["environment"] == ruler.NOMINAL and j["cell"]["family"] == first) else
                             1 if j["environment"] != ruler.NOMINAL else 2, j["cell_index"]))
    return jobs


# ---------------------------------------------------------------------------------------------------------------- one job


def _signature(sequence) -> list:
    """What a phase-0 plan commands, step by step (names, joints, modes, targets, caps): two plans with one signature are one phase."""
    out = []
    for step in sequence.steps:
        out.append((step.name, tuple((c.joint, c.mode, None if c.position is None else round(float(c.position), 9),
                                      None if getattr(c, "distance", None) is None else round(float(c.distance), 9),
                                      None if c.speed is None else round(float(c.speed), 9),
                                      None if c.max_effort is None else round(float(c.max_effort), 9),
                                      None if c.feedforward_effort is None else round(float(c.feedforward_effort), 9))
                                     for c in step.commands)))
    return out


def _report_row(report, row: str, job: dict, wall_s: float, branched: bool, keep_trace: bool = False) -> dict:
    out = asdict(report)
    trace = out.pop("trace", None)
    if keep_trace:
        out["trace"] = trace
    out.update({"procedure": row, "row": row, "environment": job["environment"], "cell_index": job["cell_index"],
                "cell": job["cell"].get("cell"), "wall_s": round(wall_s, 1), "branched": branched,
                "key": episode_key(row, job["environment"], job["cell"]["name"])})
    out["outcome_class"] = ruler.outcome_class(out)
    out["covered"] = ruler.covered(out)
    return out


def run_job(job: dict, *, tables: dict | None = None, branch: bool = True, trace_every: int = 0, plant_overrides: dict | None = None,
            keep_trace: bool = False) -> list[dict]:
    """Every row of ``job`` from its cell in its environment (module docstring). ``trace_every`` / ``keep_trace``: keep each row's trace
    (routine_media's videos and replays; ``plant_overrides={"log_qpos": True}`` for the poses)."""
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    from .fullarm_check import run_episode, table_from_json  # noqa: PLC0415
    from .fullarm_plant import ArmStart, FullArmHomingPlant, StartRefused  # noqa: PLC0415
    from .fullarm_routine import FullArmRoutine  # noqa: PLC0415
    from .bench import run_phase  # noqa: PLC0415

    environment, cell = job["environment"], job["cell"]
    start = ArmStart(**{k: v for k, v in cell.items() if k != "cell"})
    plant = FullArmHomingPlant(**{**plant_kwargs(environment), **(plant_overrides or {})})
    table_rows = (tables or {}).get(environment)
    try:
        plant.place(start)
    except StartRefused as error:
        return [{"refused_start": str(error), "procedure": row, "row": row, "environment": environment, "cell_index": job["cell_index"],
                 "cell": cell.get("cell"), "start": cell["name"], "family": cell["family"], "outcome_class": "infeasible", "covered": False,
                 "key": episode_key(row, environment, cell["name"])} for row in job["rows"]]
    out = []
    shared = None  # (plant after phase 0, [phase 0], its signature)
    for row in job["rows"]:
        procedure = procedure_for(row)
        prior = prior_for(environment, table_from_json(table_rows) if needs_table(row) and table_rows else None)
        began = time.time()
        branched = False
        inner = getattr(procedure, "procedure", procedure)
        if branch and isinstance(inner, FullArmRoutine) and inner.wrist_pose == "ready":
            first = procedure.plan(prior, [])
            signature = _signature(first)
            if shared is None:
                plant.reset(start)
                phase0 = run_phase(plant, first, limit_s=400.0)
                shared = (copy.deepcopy(plant, memo={id(plant.rig): plant.rig}), phase0, signature, time.time() - began)
            if shared[2] == signature:
                copied = copy.deepcopy(shared[0], memo={id(shared[0].rig): shared[0].rig})
                phase0 = copy.deepcopy(shared[1])
                report = run_episode(procedure, copied, start, prior, environment=environment, trace_every=trace_every,
                                     resume_phases=[phase0])
                branched = True
                wall = time.time() - began + shared[3]  # the shared phase's own wall time, counted for every row it served
                out.append(_report_row(report, row, job, wall, branched, keep_trace))
                if needs_table(row):
                    out[-1]["table_used"] = bool(table_rows)
                continue
        procedure = procedure_for(row)
        report = run_episode(procedure, plant, start, prior, environment=environment, trace_every=trace_every)
        out.append(_report_row(report, row, job, time.time() - began, branched, keep_trace))
        if needs_table(row):
            out[-1]["table_used"] = bool(table_rows)
    return out


def calibrate(environment: str) -> dict:
    """identify_backlash once in ``environment``: press_reverse from CALIBRATION_START; its wrist and claw rows (JSON) and what it found."""
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    from .bench import run_phase  # noqa: PLC0415
    from .fullarm_check import table_to_json  # noqa: PLC0415
    from .fullarm_plant import ArmStart, FullArmHomingPlant, hidden_backlash, ROLE, WRIST, CLAW  # noqa: PLC0415
    from .procedures import HomingRefused  # noqa: PLC0415

    plant = FullArmHomingPlant(**plant_kwargs(environment))
    procedure = procedure_for("press_reverse (backlash every home) @ READY")
    prior = prior_for(environment)
    plant.reset(ArmStart(**CALIBRATION_START))
    phases = []
    while (sequence := procedure.plan(prior, phases)) is not None:
        phase = run_phase(plant, sequence, limit_s=400.0)
        phases.append(phase)
        if phase.status != "done":
            return {"environment": environment, "table": None, "outcome": f"{phase.status}: {phase.message}"}
    try:
        result = procedure.observe(prior, phases)
    except HomingRefused as error:
        return {"environment": environment, "table": None, "outcome": f"refused: {error}"}
    truth = hidden_backlash(plant.kind)
    rows = [r for r in table_to_json(result.backlash) if r["joint"] in (*WRIST, CLAW)]
    return {"environment": environment, "table": rows, "outcome": "done", "time_s": plant.time,
            "gap_error_arcmin": {ROLE[r["joint"]]: round((r["gap_rad"] - truth[r["joint"]].gap_rad) * 60.0 * 180.0 / math.pi, 3)
                                 for r in rows if r["gap_observable"]},
            "stall_witness_deg": stall_witness(prior, result.evidence)}


def stall_witness(prior, evidence) -> dict:
    """Role -> the rotor-phase witness's reading (deg) on this trusted home's defining stall of each joint: the claw's close, each wrist
    joint's full-cap press on its seek side. A routine's stall on the same stop, same side, same cap reads the same (the gap and the
    wind-up are systematic), so a witness calibrated on it can be tight (``tight_witness``)."""
    from .fullarm_plant import CLAW, ROLE, WRIST  # noqa: PLC0415
    from .fullarm_procedures import witness_error  # noqa: PLC0415

    out = {}
    for joint in (*WRIST, CLAW):
        side = int(prior.seek_side[joint])
        stalls = [s for s in evidence if s.joint == joint and s.side == side]
        if not stalls:
            continue
        defining = max(stalls, key=lambda s: s.torque_nm)
        error = witness_error(prior, joint, side, defining.motor_raw_rad)
        if error is not None:
            out[ROLE[joint]] = math.degrees(error)
    return out


# ---------------------------------------------------------------------------------------------------------------- the folded-wrist cells

FOLDED = " · folded wrist"


def partition(episodes: list[dict]) -> list[dict]:
    """Ruler amendment 3: perturbed-twin episodes (and the subset rows' nominal ones) on the old "every 6th cell" subset - W2 at -150 only -
    that the balanced subset does not hold are re-labelled "<twin> · folded wrist", so they make cards of their own and never mix into
    the perturbed cards."""
    balanced = {c["name"] for c in ruler.subset_cells()}
    out = []
    for e in episodes:
        environment = e.get("environment")
        subset_only = environment != ruler.NOMINAL or e.get("row", "").removesuffix(TIGHT_SUFFIX) in SUBSET_ROWS
        if subset_only and e.get("start") not in balanced and not str(environment).endswith(FOLDED):
            e = {**e, "environment": f"{environment}{FOLDED}"}
        # the class as the ruler reads it now (amendment 4 relabelled step timeouts), not as the episode was stamped when it ran
        e = {**e, "outcome_class": ruler.outcome_class(e)}
        e["covered"] = ruler.covered(e) if "refused_start" not in e else False
        out.append(e)
    return out


# ---------------------------------------------------------------------------------------------------------------- the stored table, derived

# WHY derived too (ruler amendment 2): a stored table, like a witness, only reads a run's stalls - fit() adds each defining stall's
# motor_past_link (side x (gap / 2 + compliance x torque)) to its zero - so "<order> + table" moves exactly as "<order>". A table row is
# derived from its plain row wherever it was not run (V1 + table on the nominal grid; both orders in the twins whose gaps are B0, with the
# nominal twin's table); routine_check's own "+table" episodes, where they exist, check the derivation (test_homing_routine).
TABLE_OF = {"zach_v1 @ READY": "zach_v1+table @ READY", "park_first+witness @ READY": "park_first+witness+table @ READY"}
SEEK_SIDE_ROLE = {"W1": +1, "W2": -1, "W3": +1, "CLAW": -1}
STALL_TORQUE_NM = {"W1": 1.0, "W2": 1.0, "W3": 1.0, "CLAW": 0.3}  # a stall is read saturated at its seek's cap (Stall's lead > cap / kp)


_FIVEBAR_ROLES = {"J1", "J2", "C1"}


def ended_in(episode: dict) -> str | None:
    """Where a lost start was lost - "phase 0" (the five-bar) or "wrist" (phase 1) - or None for a home or a start the twin cannot hold.
    A trip or a timeout is placed by the step it happened in; a refusal by the joints the witness refused (a five-bar joint among them was
    seen first, in phase 0); a finished wrong home by its worst joint. WHY (2026-11-13): the report's headline that every start the
    recommended routine lost was lost in phase 0 is counted here, not read off the plots."""
    import re  # noqa: PLC0415

    outcome_class = episode.get("outcome_class") or ruler.outcome_class(episode)
    if outcome_class in ("homed", "infeasible"):
        return None
    outcome = str(episode.get("outcome") or "")
    step = re.search(r"step '([^']+)'", outcome)
    if step:
        names = set(re.findall(r"\b(J1|J2|C1|W1|W2|W3|claw|CLAW)\b", step.group(1)))
        return "phase 0" if names and {n.upper() for n in names} <= _FIVEBAR_ROLES else "wrist"
    refused = re.search(r"\{([^}]*)\}", outcome) if outcome_class == "refused" else None
    if refused:
        joints = set(re.findall(r"'([A-Z0-9]+)'", refused.group(1)))
        return "phase 0" if joints & _FIVEBAR_ROLES else "wrist"
    errors = {role: abs(v) for role, v in (episode.get("zero_error_deg") or {}).items() if v is not None}
    if errors:
        return "phase 0" if max(errors, key=errors.get) in _FIVEBAR_ROLES else "wrist"
    return "wrist"


def with_table(episode: dict, table: list[dict]) -> dict:
    """``episode`` (a plain single-touch run) re-zeroed with ``table`` (table_to_json rows): each scored wrist / claw zero moves by its
    defining stall's motor_past_link."""
    from .fullarm_plant import ROLE  # noqa: PLC0415

    zero = dict(episode["zero_error_deg"])
    gaps = dict(episode.get("gap_identified_deg") or {})
    for row in table:
        role = ROLE.get(row["joint"])
        if role not in SEEK_SIDE_ROLE or zero.get(role) is None:
            continue
        past = SEEK_SIDE_ROLE[role] * (0.5 * row["gap_rad"] + row["compliance_rad_per_nm"] * STALL_TORQUE_NM[role])
        zero[role] = zero[role] + math.degrees(past)
    out = {**episode, "zero_error_deg": zero, "gap_identified_deg": gaps}
    out["outcome_class"] = ruler.outcome_class(out)
    out["covered"] = ruler.covered(out)
    return out


def table_derived(episodes: list[dict], calibrations: dict) -> list[dict]:
    """The "+table" rows wherever only their plain row ran (module comment above)."""
    have = {(e.get("row"), e.get("environment"), e.get("start")) for e in episodes}
    out = []
    for episode in episodes:
        target = TABLE_OF.get(episode.get("row"))
        if target is None or "error" in episode or (target, episode.get("environment"), episode.get("start")) in have:
            continue
        environment = episode["environment"].removesuffix(FOLDED)
        source = environment if (calibrations.get(environment) or {}).get("table") and environment in TABLE_ENVIRONMENTS else ruler.NOMINAL
        table = (calibrations.get(source) or {}).get("table")
        if not table:
            continue
        derived = with_table(episode, table) if "refused_start" not in episode and episode.get("finished") else dict(episode)
        derived.update({"row": target, "procedure": target, "key": episode["key"].replace(episode["row"], target, 1),
                        "derived_from": episode["row"], "table_from": source})
        derived["outcome_class"] = ruler.outcome_class(derived)
        derived["covered"] = ruler.covered(derived) if "refused_start" not in derived else False
        out.append(derived)
    return out


# ---------------------------------------------------------------------------------------------------------------- the tight witness

TIGHT_WITNESS_DEG = 0.5
# WHY derived offline (the witness only reads a run's stalls; it never moves the arm): a row with the tight witness moves exactly as its
# plain row, so its episodes are the plain row's with each defining stall re-judged against the trusted home's own reading of that stall
TIGHT_ROWS = ("park_first+witness @ READY", "park_first+witness+table @ READY", "multi x2 (3D-printer) @ READY",
              "multi x3 (3D-printer) @ READY", "fast single @ READY", "zach_v1 @ READY", "press_reverse (backlash every home) @ READY",
              "zach_v1+table @ READY")
# WHY press_reverse gets only the five-bar's: its wrist stalls are pressed at two levels on both sides, so they read the gap and the wind-up
# a one-touch reference does not; its span witness already guards the wrist
FIVEBAR_ONLY_TIGHT = ("press_reverse (backlash every home) @ READY",)
FIVEBAR_ROLES = ("J2", "C1")
TIGHT_SUFFIX = " · witness 0.5° (stall-calibrated)"
# phase_cal_error's witness is calibrated on the NOMINAL twin's trusted home: a calibration gone stale by 1.5 deg (an encoder recalibrated
# after the home it was taken from) - the case a tight witness must refuse, never accept
STALE_CALIBRATION = {"phase_cal_error": "nominal"}


def trusted_homes(episodes: list[dict], environment: str) -> list[dict]:
    """The plain park_first runs in ``environment`` that ended on their right stops - homed, or inaccurate only by an uncorrected gap
    (B1 / B2 without a table). WHY not "homed" alone (2026-11-13): on the geared twins no table-less run is homed, so the five-bar's
    reference came out empty and its witness skipped C1 stalling 44 deg short on the claw jammed against the base."""
    return [e for e in episodes if e.get("environment") == environment and e.get("row") == "park_first+witness @ READY"
            and ruler.outcome_class(e) in ("homed", "inaccurate")]


def tight_witness(episodes: list[dict], calibrations: dict, *, tol_deg: float = TIGHT_WITNESS_DEG) -> list[dict]:
    """Derived episodes: each TIGHT_ROWS episode re-judged by a witness tolerance ``tol_deg`` on the trusted home's stall readings
    (``calibrations[environment]["stall_witness_deg"]``). Finished episodes past the tolerance become refusals; the rest are unchanged."""
    import statistics  # noqa: PLC0415

    references = {}
    for environment in {e.get("environment") for e in episodes}:
        base = str(environment).removesuffix(FOLDED)
        source = STALE_CALIBRATION.get(base, base)
        reference = (calibrations.get(source) or {}).get("stall_witness_deg")
        if not reference:
            # WHY a fallback (2026-11-13: press_reverse's calibration timed out walking W1 across under the wrist's breakaway friction and
            # under the 0.5 kg claw): the trusted home is then the plain routine's own homed, clean episodes in that twin - the median of
            # each joint's defining-stall reading, which is the true stop's (most of them are on it)
            homed = trusted_homes(episodes, source)
            values: dict = {}
            for e in homed:
                for role, readings in (e.get("witness_deg") or {}).items():
                    values.setdefault(role, []).extend(readings)
            reference = {role: statistics.median(v) for role, v in values.items() if v} or None
        # the five-bar's boards boot mod one rotor turn too (10:1, 36 deg; the rack's sub-turn offsets, PEP 0017's whole-turn re-latch): its
        # witness reads a stall's distance from where a trusted home's stall read, mod 36 - here each drive's zero error against the
        # median of the plain routine's homed, clean episodes in the source twin (a home in that twin you trust)
        homed = trusted_homes(episodes, source)
        fivebar = {role: statistics.median([e["zero_error_deg"][role] for e in homed if e["zero_error_deg"].get(role) is not None])
                   for role in FIVEBAR_ROLES if any(e["zero_error_deg"].get(role) is not None for e in homed)}
        references[environment] = ({**(reference or {}), **{f"fivebar:{k}": v for k, v in fivebar.items()}} or None)
    out = []
    for episode in episodes:
        if episode.get("row") not in TIGHT_ROWS or "error" in episode:
            continue
        environment = episode.get("environment")
        reference = references.get(environment)
        if not reference:
            continue
        derived = {**episode, "row": episode["row"] + TIGHT_SUFFIX, "procedure": episode["row"] + TIGHT_SUFFIX,
                   "key": episode["key"].replace(episode["row"], episode["row"] + TIGHT_SUFFIX, 1), "derived_from": episode["row"]}
        if episode.get("finished"):
            off = {}
            if episode["row"] not in FIVEBAR_ONLY_TIGHT:
                for role, values in (episode.get("witness_deg") or {}).items():
                    if role not in reference:
                        continue
                    worst = max((abs((v - reference[role] + 18.0) % 36.0 - 18.0) for v in values), default=0.0)
                    if worst > tol_deg:
                        off[role] = round(worst, 3)
            for role in FIVEBAR_ROLES:
                value, ref = episode["zero_error_deg"].get(role), reference.get(f"fivebar:{role}")
                if value is None or ref is None:
                    continue
                worst = abs((value - ref + 18.0) % 36.0 - 18.0)
                if worst > tol_deg:
                    off[role] = round(worst, 3)
            if off:
                derived.update({"finished": False, "time_s": None, "outcome": f"refused: tight witness {off} deg off the trusted home's stall"})
            derived["tight_off"] = off
        derived["outcome_class"] = ruler.outcome_class(derived)
        derived["covered"] = ruler.covered(derived)
        out.append(derived)
    return out


# ---------------------------------------------------------------------------------------------------------------- V1, parking on a refusal

# WHY exact from two rows' runs (the routine's analysis, 2026-11-13): V1's first wrist move - the claw closes, then W1 seeks +1 at 1 N.m and
# 36 deg/s - IS park_first's (its park touch is that same seek); they differ only in what they do with W1's stall: V1 assigns it, park_first
# never trusts it and parks back 135 deg. So "V1, and park_first's path when the tight witness refuses W1's stall" moves exactly as V1 when
# the witness passes and exactly as park_first when it does not, decided by a reading the rack has at that tick.
FALLBACK = {"zach_v1 @ READY": ("park_first+witness @ READY", "V1, park_first on a W1 refusal @ READY"),
            "zach_v1+table @ READY": ("park_first+witness+table @ READY", "V1+table, park_first on a W1 refusal @ READY")}


def fallback_derived(episodes: list[dict]) -> list[dict]:
    """The FALLBACK rows (comment above), from the tight-witness rows: per (twin, start), V1's episode unless its tight witness refused W1,
    else park_first's."""
    index = {(e.get("row"), e.get("environment"), e.get("start")): e for e in episodes}
    out = []
    for (v1_row, (park_row, name)) in FALLBACK.items():
        for (row, environment, start), v1 in list(index.items()):
            if row != v1_row + TIGHT_SUFFIX:
                continue
            park = index.get((park_row + TIGHT_SUFFIX, environment, start))
            if park is None:
                continue
            refused_w1 = "W1" in (v1.get("tight_off") or {})
            chosen = park if refused_w1 else v1
            derived = {**chosen, "row": name + TIGHT_SUFFIX, "procedure": name + TIGHT_SUFFIX, "derived_from": f"{v1_row} / {park_row}",
                       "branch": "park_first (W1 refused)" if refused_w1 else "V1",
                       "key": f"{name}{TIGHT_SUFFIX} | {environment} | {start}"}
            out.append(derived)
    return out


# ---------------------------------------------------------------------------------------------------------------- the pool, the cache


def load_cache(path: Path | None) -> list[dict]:
    if path is None or not Path(path).is_file():
        return []
    out = []
    for line in Path(path).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # a line torn by a killed worker: that episode simply runs again
            continue
    return out


def pending(jobs: list[dict], done: list[dict]) -> list[dict]:
    have = {r["key"] for r in done}
    out = []
    for job in jobs:
        missing = [row for row in job["rows"] if episode_key(row, job["environment"], job["cell"]["name"]) not in have]
        if missing:
            out.append({**job, "rows": missing if len(missing) < len(job["rows"]) else job["rows"]})
    return out


def _worker(payload):
    job, tables = payload
    try:
        return run_job(job, tables=tables)
    except Exception as error:  # noqa: BLE001 - one broken episode must not take the sweep down; it is reported, not hidden
        import traceback  # noqa: PLC0415

        return [{"procedure": row, "row": row, "environment": job["environment"], "cell_index": job["cell_index"], "cell": job["cell"].get("cell"),
                 "start": job["cell"]["name"], "error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()[-2000:],
                 "key": episode_key(row, job["environment"], job["cell"]["name"]) + " | error"} for row in job["rows"]]


def run(jobs: list[dict], *, workers: int, cache: Path | None, tables: dict) -> list[dict]:
    import multiprocessing  # noqa: PLC0415

    done = load_cache(cache)
    todo = pending(jobs, done)
    print(f"{len(jobs)} jobs, {len(todo)} to run, {len(done)} episodes cached", flush=True)
    began, finished = time.time(), 0
    if cache is not None:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
    payloads = [(job, tables) for job in todo]
    # WHY maxtasksperchild (claw_rung's WHY): a worker's RSS grows over tens of episodes; a fresh one every few jobs costs nothing
    with multiprocessing.get_context("fork").Pool(workers, maxtasksperchild=4) as pool:
        for rows in pool.imap_unordered(_worker, payloads, chunksize=1):
            finished += 1
            if cache is not None:
                with Path(cache).open("a") as handle:
                    for row in rows:
                        handle.write(json.dumps(row, default=str) + "\n")
            done.extend(rows)
            mins = (time.time() - began) / 60.0
            print(f"[{finished}/{len(todo)} jobs, {mins:.1f} min] {rows[0].get('start', '')[:48]} {rows[0]['environment']}: "
                  + ", ".join(f"{r['row'][:18]}={r.get('outcome_class', 'error')}" for r in rows), flush=True)
    keys = {episode_key(row, j["environment"], j["cell"]["name"]) for j in jobs for row in j["rows"]}
    return [r for r in done if r.get("key") in keys or (r.get("key", "").endswith(" | error") and r["key"][:-8] in keys)]


def results(reports: list[dict], tables: dict, calibrations: dict) -> dict:
    from sim2real.provenance import code_sha  # noqa: PLC0415

    from .mujoco_plant import BAM_WS_SRC  # noqa: PLC0415

    clean = partition([r for r in reports if "error" not in r and not r.get("derived_from")])
    clean = clean + table_derived(clean, calibrations)
    if any(c.get("stall_witness_deg") for c in calibrations.values()):
        clean = clean + tight_witness(clean, calibrations)
        clean = clean + fallback_derived(clean)
    return {"schema": "sim2real.homing_routine/1", "ruler": "sim2real.sim.homing.routine_ruler (frozen 2026-11-13, amendment 1)",
            "grid_rows": list(GRID_ROWS), "subset_rows": list(SUBSET_ROWS), "perturbed_rows": list(PERTURBED_ROWS),
            "environments": {k: v["why"] for k, v in ruler.ENVIRONMENTS.items()}, "targets": {k: list(v) for k, v in ruler.TARGETS.items()},
            "plant": {k: (list(v) if isinstance(v, tuple) else v) for k, v in plant_kwargs(ruler.NOMINAL).items()},
            "calibrations": calibrations, "cards": ruler.score(clean), "errors": [r for r in reports if "error" in r],
            "episodes": clean, "sim2real_sha": code_sha(Path(__file__)), "bam_ws_sha": code_sha(BAM_WS_SRC),
            "bundle": "bam_fb_v2 @ cad-exporter 09374d7"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plan", default="all", choices=("all", "nominal", "perturbed", "smoke", "light"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--tables", type=Path, help="calibrations JSON to reuse (else identify_backlash runs once per table environment)")
    parser.add_argument("--plans", type=Path, default=Path.home() / ".cache" / "sim2real" / "homing_routine_plans.pkl")
    args = parser.parse_args(argv)
    from sim2real.provenance import write_results  # noqa: PLC0415

    began = time.time()
    jobs = plan_jobs(args.plan)
    rows = sorted({row for job in jobs for row in job["rows"]} | {"press_reverse (backlash every home) @ READY"})
    args.plans.parent.mkdir(parents=True, exist_ok=True)
    PLANS.update(preplan_file(rows, args.plans))
    print(f"planned {len(PLANS)} rows once ({args.plans})", flush=True)
    environments = sorted({j["environment"] for j in jobs if any(needs_table(r) for r in j["rows"])})
    if args.tables and args.tables.is_file():
        calibrations = json.loads(args.tables.read_text())
    else:
        import multiprocessing  # noqa: PLC0415

        with multiprocessing.get_context("fork").Pool(max(1, min(args.workers, len(environments)))) as pool:
            calibrations = dict(zip(environments, pool.map(calibrate, environments), strict=True))
        if args.tables:
            args.tables.write_text(json.dumps(calibrations, indent=1, default=str))
    print("calibrations", json.dumps({k: (v["outcome"], v.get("gap_error_arcmin")) for k, v in calibrations.items()}), flush=True)
    tables = {k: v["table"] for k, v in calibrations.items() if v.get("table")}
    reports = run(jobs, workers=args.workers, cache=args.cache, tables=tables)
    out = results(reports, tables, calibrations)
    out["seconds"] = round(time.time() - began, 1)
    write_results(args.out, out, default=str)
    for name, card in sorted(out["cards"].items()):
        print(f"{name[:70]:70s} cov {card['coverage_pct']} sw {card['silent_wrong']} p95 {card['zero_error_p95_deg']} "
              f"t50 {card['time_to_home_median_s']} pass {card['verdict']['pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
