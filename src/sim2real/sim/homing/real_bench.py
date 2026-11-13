"""The homing bench's real rung: the MuJoCo-passing procedures on the real five-bar (One Dof Test Rack), behind ``RealRigPlant``.

Three parts, each in the environment it needs:

* ``prior`` (sim2real's venv, coal + trimesh): the v11 CAD stop map and the twin-contact stop map as JSON
  (``data/homing_fivebar_real_prior_2026-11-12.json``), so the rack's venv (no coal) builds the procedures' ``Prior`` without the meshes.
* :func:`run_homing` (the rack's venv, ``PYTHONPATH`` = sim2real/src + robot_models/src): called by bam_rack_twin ``fivebar_homed
  --stage homing`` inside its bus lock, KeepFed and the plant of record (the home button's ``LIMITS``, frame check, controlled stops), so
  every rack rule the home button runs under holds here too. Per start: the home button walks the arm to the start (``run_home`` with the
  start as its target) and releases it; ``RealRigPlant`` reads the rest the boards came to; the procedure's sequence (planned before the
  bus opened) runs on the JointCommandSequenceController; ``observe`` gives the zero. A trip, an abort or the stall gate: the arm is held
  where it is, the home button takes it home, and the next start goes on.
* ``score`` (either venv): every run folder's episodes -> ``data/homing_fivebar_real_2026-11-12.json`` (the gates; the comparison with the
  MuJoCo rung).

The rows (the four MuJoCo-passing procedures, ``mujoco_bench.make`` - recover_first in front, sag_proof on, ``+gff`` where named): three
run as they ran in MuJoCo with J1 held (``real_plant.J1Held``). ``recover_first+press_reverse+gff`` is NOT run: its second side seeks J2's
lower stop (CAD -90.03 deg = Craig ~0) and walks J2 to -85 deg (Craig 5) on the way, while the real arm meets an unidentified contact at
Craig j2 12.6 and 16.5 deg (fivebar-real-night F08; ``fivebar_homed.LADDER_J2_MIN_DEG`` 20 keeps every stage out of j2 < 20): it would press
up to 10 N.m into that contact and then define it as J2's lower stop. Without press_reverse there is no real ``identify_backlash``, so
single_touch and two_level_touch run with no stored table (the half-gap correction is 0; the gearbox's 3 arcmin datasheet gap would move
a zero by 0.025 deg, inside the 0.1 deg gate) - ``score`` also re-observes them with the MuJoCo rung's calibration tables to show it.

Run (the CAD twin first, then the arm; each powered run a transient service at CPUWeight 2000, see the rack rules):

    cd ~/bam_ws/src/dev/bam_rack_twin
    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/robot_models/src uv run --no-sync python -m bam_rack_twin.hardware.fivebar_homed --stage homing --homing-procedure recover_first+tview_v2 --homed /archive/datasets/bam_rig/rack_2026-11-10/fivebar_real/homed/homed_083647.json --twin --twin-model cad
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from .geometry import BUNDLE_SHA, C1, DRIVES, J1, J2, ROLE
from .real_plant import (
    DRIVE_JOINTS,
    J1_HOLD_CAP_NM,
    STALL_BOARD_DEG,
    STALL_GATE_DEG,
    J1Held,
    RealRigPlant,
    RealStart,
    SequenceStopped,
    StopGuard,
    hold_j1,
    keep_j2_powered,
    run_phase_real,
)

DATA = Path(__file__).resolve().parents[2] / "data"
PRIOR_JSON = DATA / "homing_fivebar_real_prior_2026-11-12.json"
RESULTS_JSON = DATA / "homing_fivebar_real_2026-11-12.json"
MUJOCO_JSON = DATA / "homing_fivebar_mujoco_pass4_2026-11-12.json"
RAW_DIR = Path("/archive/datasets/bam_rig/rack_2026-11-10/fivebar/homing")
RUNG = "real"
ENVIRONMENT = "real · rig"
DT = 0.01
GATE_DEG = 0.1  # frozen: the MuJoCo rung's GATE_DEG and ZERO_VS_KINEMATIC_DEG
RELIABILITY_TARGET_PCT = 100.0
# WHY the two +gff rows (pass 6, 2026-11-13): pass 5's 16 real episodes all tripped 0.1-0.2 s after the zero, when the first un-fed hold
# let J2 fall past the runaway ceiling; single_touch+gff / tview_v2+gff feed every hold and move once the plan knows the pose (gravity_ff),
# proven on the MuJoCo rung in this exact form (gff_rung: the real form, the end group +22 %, the comp +-25 %, the runaway check on)
ROWS = ("tview_v2", "single_touch", "two_level_touch+gff", "single_touch+gff", "tview_v2+gff")
# the MuJoCo rung's row each real row is compared with (the same procedure; MuJoCo ran every row behind recover_first)
MUJOCO_ROW = {"tview_v2": "recover_first+tview_v2", "single_touch": "recover_first+single_touch",
              "two_level_touch+gff": "recover_first+two_level_touch+gff",
              # pass 6 ran these in this very form (gff_rung): the real arm is its end group +22 % with the comp as identified (score
              # them with --mujoco-json data/homing_fivebar_mujoco_pass6_2026-11-13.json)
              "single_touch+gff": "single_touch+gff · real form · end group +22 % · ff nominal",
              "tview_v2+gff": "tview_v2+gff · real form · end group +22 % · ff nominal"}
RECOVER_ROWS = ("recover_first+tview_v2", "recover_first+single_touch", "recover_first+two_level_touch+gff")
NOT_RUN = {
    "two_level_touch+gff": (
        "not runnable on the real arm in either form. Behind recover_first (the MuJoCo row) the blind recovery's re-hold after its first J2 "
        "seek ran away on the real arm at 91-93 deg/s powered, every start (run real_two_level_touch_gff_*, the plant's controlled stop "
        "and the home button each time). Bare (the home button as the recovery), its first seek carries the gravity feed-forward planned "
        "for the upper stop (J2 6.6 N.m) from the hanging rest, where gravity is ~0: on the MuJoCo rung that lunges J2 to 3.4 rad/s and "
        "the sequence's own speed guard aborts it (B0 and B2, home start) - not sent to the arm."),
    "press_reverse+gff": (
        "not run on the real arm: its second side walks J2 to -85 deg (Craig 5) and seeks J2's lower stop (CAD -90.03 = Craig ~0), "
        "below the unidentified contact the real arm meets at Craig j2 12.6 / 16.5 deg (fivebar-real-night F08, two stalls on one map; "
        "fivebar_homed.LADDER_J2_MIN_DEG 20 keeps every stage above it). It would press up to 10 N.m into that contact and define it as "
        "J2's lower stop: a guaranteed wrong zero and an unknown thing pressed. Needs the contact identified (Zach's eye at j2 ~17) or "
        "a second side that stays above j2 20."),
}
# Each start: the home button walks to the homed map's home plus this (Craig J2, C1, deg), then releases. WHY these: inside the real
# hanging rest's friction band (J2 +-4.5, C1 +-12 deg: fivebar-real-night "passive releases") so a release does not drop the arm, and
# every one with both fold margins >= 0.04 (bam_fivebar_recovery.home.classify on bench_real: C1 +10 and J2 -4 are past straight).
STARTS = (
    RealStart("home", (0.0, 0.0), "the home button's own rest (homed_083647's home): margins 0.057 / 0.041"),
    RealStart("c1-10", (0.0, -10.0), "the crank 10 deg below home: margins 0.111 / 0.064"),
    RealStart("j2+4", (4.0, 0.0), "L1 4 deg above home: margins 0.086 / 0.072"),
    RealStart("j2+4 c1-10", (4.0, -10.0), "both: margins 0.145 / 0.099"),
)
STARTS_BY_NAME = {s.name: s for s in STARTS}
NEAR_DEG = 2.0  # a rest this close to a walk's target (both drives) is the target
LEG_SPAN_DEG = 15.0  # starts and rests within this of home are walked by the board leg, not the home button


def git_sha(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# ---------------------------------------------------------------------------------------------------------------- the prior


def write_prior(path: Path = PRIOR_JSON, mujoco_json: Path = MUJOCO_JSON) -> dict:
    """sim2real's venv: the CAD stop map (``bench.prior_for``) and the twin-contact map (the MuJoCo rung's ``twin_contacts_deg``) as JSON,
    with the MuJoCo rung's calibration tables (for ``score``'s sensitivity re-observe)."""
    from .bench import prior_for  # noqa: PLC0415
    from .geometry import FivebarGeometry  # noqa: PLC0415
    from .mujoco_bench import twin_prior  # noqa: PLC0415

    geometry = FivebarGeometry()
    prior = prior_for(geometry)
    mujoco = json.loads(Path(mujoco_json).read_text())
    roles = {v: k for k, v in ROLE.items()}
    contacts = {(roles[role], +1 if side == "upper" else -1): math.radians(entry["twin"])
                for role, sides in mujoco["twin_contacts_deg"].items() for side, entry in sides.items()}
    twin = twin_prior(prior, contacts)
    payload = {"schema": "sim2real_homing_real_prior/1", "bundle_sha": BUNDLE_SHA, "hardstops_sha256": geometry.hardstops_sha256,
               "cad": prior.stops.to_dict(), "twin": twin.stops.to_dict(), "joints": list(prior.joints),
               "seek_side": dict(prior.seek_side), "caps_nm": dict(prior.caps_nm),
               "mujoco_tables": {model: {"cad": (mujoco["calibration"][model] or {}).get("table"),
                                         "twin": None} for model in mujoco["models"]},
               "source": {"mujoco": str(mujoco_json), "sim2real_sha": git_sha(Path(__file__).resolve().parents[4])}}
    Path(path).write_text(json.dumps(payload, indent=1) + "\n")
    return payload


def load_prior(path: Path = PRIOR_JSON, table=None):
    """(the CAD prior, the twin-contact prior) from ``write_prior``'s JSON; ``table`` a BacklashTable (or None) for both."""
    from robot_models.homing.protocols import Prior  # noqa: PLC0415
    from robot_models.homing.types import StopMap  # noqa: PLC0415

    payload = json.loads(Path(path).read_text())

    def prior(key):
        return Prior(stops=StopMap.from_dict(payload[key]), joints=tuple(payload["joints"]),
                     seek_side={k: int(v) for k, v in payload["seek_side"].items()}, table=table,
                     caps_nm={k: float(v) for k, v in payload["caps_nm"].items()})

    return prior("cad"), prior("twin"), payload


class RealRow:
    """A real row: the MuJoCo rung's procedure (``mujoco_bench.make``: recover_first + sag_proof, ``+gff`` where named) built with J1 held
    INSIDE the gravity feed-forward (so the +gff comp never plans J1 at a stop: the real plane stays vertical, cos J1 = 1), then two
    rewrites of the planned sequence - ``hold_j1`` (J1 held everywhere, the recovery's own J1 hold included) and ``keep_j2_powered`` (J2
    never let go under load; real_plant says why). ``observe`` is the procedure's own, J1 dropped."""

    def __init__(self, name: str, *, ff_scale: float = 1.0):
        from .gravity_ff import GFF_SUFFIX, GravityFF  # noqa: PLC0415
        from .procedures import PROCEDURES  # noqa: PLC0415
        from .recover import RECOVER_PREFIX_NAME, RecoverFirst  # noqa: PLC0415

        self.recover = name.startswith(RECOVER_PREFIX_NAME)
        bare = name.removeprefix(RECOVER_PREFIX_NAME)
        gff = bare.endswith(GFF_SUFFIX)
        inner = J1Held(PROCEDURES[bare.removesuffix(GFF_SUFFIX)]())
        if gff:
            inner = GravityFF(inner=inner, ff_scale=ff_scale)  # ff_scale: the comp's assumed error (the MuJoCo rung only; the arm runs 1)
        # WHY a row without recover_first (the real rung, 2026-11-13): on the real arm the recovery is the home button, which sets every
        # start; the blind recovery's own re-hold after its first J2 seek ran away on the real arm (91 deg/s powered, every start of the
        # first real run). The bare row keeps sag_proof - the MuJoCo rung's completion under gravity - over the procedure's own steps.
        self.procedure = RecoverFirst(inner=inner, sag_proof=True) if self.recover else inner
        if self.procedure.name != name:
            raise ValueError(f"built {self.procedure.name!r} for {name!r}")
        self.name = name
        self.rewritten: list[str] = []

    @property
    def references(self):
        return [r for r in self.procedure.references if r[2] != J1]

    @references.setter
    def references(self, value):
        self.procedure.references = list(value)

    @property
    def notes(self):
        return self.procedure.notes

    @notes.setter
    def notes(self, value):
        self.procedure.notes = dict(value)

    def plan(self, prior, so_far):
        sequence = self.procedure.plan(prior, so_far)
        if sequence is None:
            return None
        if not self.recover:
            from .sag_proof import sag_proof  # noqa: PLC0415

            sequence = sag_proof(sequence)
        sequence, self.rewritten = keep_j2_powered(hold_j1(sequence))
        self.procedure.notes["j2_kept_powered_in"] = list(self.rewritten)
        return sequence

    def observe(self, prior, phases):
        result = self.procedure.observe(prior, phases)
        return result if self.recover else self._strip(result)

    def observe_vs_twin(self, prior, twin, phases):
        result = self.procedure.observe_vs_twin(prior, twin, phases)
        return result if self.recover else self._strip(result)

    @staticmethod
    def _strip(result):
        from robot_models.homing.types import HomingResult  # noqa: PLC0415

        return HomingResult(tuple(z for z in result.zeros if z.joint != J1), result.backlash, result.stops,
                            tuple(e for e in result.evidence if e.joint != J1), "real")


def make_row(name: str) -> RealRow:
    return RealRow(name)


def describe(sequence) -> list[dict]:
    """The planned sequence, step by step (what the arm will be told), for the receipt."""
    out = []
    for step in sequence.steps:
        out.append({"name": step.name, "timeout_s": step.timeout,
                    "commands": {ROLE[c.joint]: {"mode": c.mode, "cap_nm": c.max_effort, "ff_nm": c.feedforward_effort,
                                                 "position_deg": None if c.position is None else math.degrees(c.position),
                                                 "distance_deg": None if c.distance is None else math.degrees(c.distance),
                                                 "speed_deg_s": None if c.speed is None else math.degrees(c.speed)}
                                 for c in step.commands},
                    "done_when": [type(d).__name__ + ":" + json.dumps(d.to_dict(), default=str) for d in step.done_when],
                    "define_deg": {ROLE[j]: math.degrees(v) for j, v in step.define_position.items()}})
    return out


def prepare_homing(name: str, prior_path: Path = PRIOR_JSON) -> dict:
    """Before the bus opens (no drive powered): the prior, the row and its planned sequence (the +gff comp builds a MuJoCo model here,
    seconds of host work that must never fall inside a powered tick)."""
    if name in NOT_RUN:
        raise SystemExit(f"REFUSED: {name} is {NOT_RUN[name]}")
    if name not in ROWS + RECOVER_ROWS:
        raise SystemExit(f"REFUSED: the real rung's rows are {ROWS} (and, as run first, {RECOVER_ROWS}), not {name!r}")
    prior, twin, payload = load_prior(prior_path)
    row = make_row(name)
    sequence = row.plan(prior, [])
    caps = {ROLE[j]: max(float(c.max_effort or 0.0) for s in sequence.steps for c in s.commands if c.joint == j) for j in DRIVES}
    return {"name": name, "prior": prior, "twin": twin, "prior_payload": payload, "row": row, "sequence": sequence,
            "steps": describe(sequence), "max_cap_nm": caps}


# ---------------------------------------------------------------------------------------------------------------- the run (rack venv)


def _event_dicts(events) -> list[dict]:
    return [{"index": e.index, "name": e.name, "outcome": e.outcome, "started_s": round(e.started, 3), "finished_s": round(e.finished, 3)}
            for e in events]


def _zeros_deg(result) -> dict:
    return {ROLE[z.joint]: math.degrees(z.offset_rad) for z in result.zeros if z.joint != J1}


def _save_episode(path: Path, plant: RealRigPlant, phase, record: dict) -> None:
    arrays = {f"plant_{k}": np.asarray(v, dtype=float) for k, v in plant.log.items()}
    if phase is not None:
        arrays.update(phase_t=np.asarray(phase.log["t"], dtype=float), phase_position=np.asarray(phase.log["position"], dtype=float),
                      phase_velocity=np.asarray(phase.log["velocity"], dtype=float), phase_effort=np.asarray(phase.log["effort"], dtype=float),
                      phase_events=np.asarray(phase.log["events"], dtype=int), phase_step=np.asarray(phase.log["step"], dtype=int))
        record["phase_defines"] = [{"k": k, "defines": {ROLE[j]: v for j, v in d.items()}} for k, d in enumerate(phase.log["defines"]) if d]
        record["phase_plant_offset"] = int(phase.log["plant_offset"])
    np.savez_compressed(path.with_suffix(".npz"), **arrays)
    path.with_suffix(".json").write_text(json.dumps(record, indent=1, default=float) + "\n")


def _observe_with_j1_steps_closed(row, prior, phase, record: dict):
    """A stopped phase whose only missing evidence is J1's (tview reads its J1 seek, after the moves a runaway stopped): the steps it
    never reached are closed on its last reading - only steps that define nothing (the frame is untouched) - and the procedure observed
    again; the result is kept only when no J2 / C1 reference lands on a closed step (so no J2 / C1 evidence is made up). J1's zero is
    dropped as on every real row. Returns the result or None."""
    from robot_models.homing.protocols import Phase  # noqa: PLC0415

    steps = phase.sequence.steps
    done = phase.log["events"][-1] if phase.log["events"] else 0
    remaining = steps[done:]
    if not remaining or any(step.define_position for step in remaining):
        return None
    log = {key: (list(value) if isinstance(value, list) else value) for key, value in phase.log.items()}
    real_ticks = len(log["t"])
    for k in range(1, len(remaining) + 1):
        for key in ("t", "position", "velocity", "effort", "step"):
            log[key].append(log[key][-1])
        log["defines"].append({})
        log["events"].append(done + k)
    try:
        result = row.observe(prior, [Phase(phase.sequence, "stopped", phase.message, phase.events, log)])
    except Exception as error:  # noqa: BLE001
        record["evidence_missing_after_closing_j1"] = f"{type(error).__name__}: {error}"
        return None
    made_up = [r for r in row.references if r[1] >= real_ticks and r[2] != J1]
    if made_up:
        record["evidence_missing_after_closing_j1"] = f"a J2 / C1 reference on a closed step: {made_up}"
        return None
    record["evidence_complete"] = True
    record["closed_steps"] = [step.name for step in remaining]
    return result


def run_homing(bus, homed, servo_map, bench, out: Path, report: dict, *, prepared: dict, rows: list | None = None, comp=None,
               start_names: tuple[str, ...] | None = None) -> dict:
    """The real rung for one row (module docstring). ``bus``: the plant of record behind KeepFed (or the dry run's twin);
    ``prepared``: :func:`prepare_homing`'s."""
    from bam_rack_twin.hardware.fivebar_homed import HOME_REACH_RAD, board_leg, home_offset, hold_feedforward, run_home  # noqa: PLC0415
    from bam_rack_twin.hardware.fivebar_homed import hold_j1 as hold_j1_board  # noqa: PLC0415
    from bam_rack_twin.hardware.tview_run import _release  # noqa: PLC0415
    from bam_rack_twin.hardware.fivebar_plant import PlantTrip, TrajectoryCommand  # noqa: PLC0415
    from bam_rack_twin.hardware.tview_run import J1_HOLD_NM, _command  # noqa: PLC0415
    from bam_fivebar.dynamics import ControllerModel  # noqa: PLC0415
    from bam_fivebar_recovery.home import classify  # noqa: PLC0415

    if abs(J1_HOLD_NM - J1_HOLD_CAP_NM) > 1e-9:
        raise RuntimeError(f"J1's hold is tview_run's {J1_HOLD_NM} N.m; the real rung's J1Held says {J1_HOLD_CAP_NM}")
    rows = [] if rows is None else rows
    name, prior, sequence, row = prepared["name"], prepared["prior"], prepared["sequence"], prepared["row"]
    starts = [STARTS_BY_NAME[n] for n in (start_names or [s.name for s in STARTS])]
    episodes_dir = Path(out) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    signs = tuple(float(v) for v in servo_map.sign)
    if signs != (-1.0, 1.0):
        raise RuntimeError(f"the homed map's signs are {signs}: the real rung's frames were checked on (-1, +1) (homed_083647)")
    comp_model = ControllerModel.for_bench(bench)
    if comp is not None:
        from bam_fivebar import massid  # noqa: PLC0415

        comp_model = massid.identified_model(bench, massid.load_gravity_parameters(comp))
    set_hold = getattr(bus, "set_hold_feedforward", None)
    if set_hold is not None:
        set_hold(hold_feedforward(servo_map, bench, comp_model))
    homing: dict[str, Any] = {"procedure": name, "rung": RUNG, "starts": [s.name for s in starts], "episodes": [], "recoveries": [],
                              "steps": prepared["steps"], "max_cap_nm": prepared["max_cap_nm"], "stall_board_deg": dict(
                                  (ROLE[j], v) for j, v in STALL_BOARD_DEG.items()), "stall_gate_deg": STALL_GATE_DEG,
                              "signs": list(signs), "comp": str(comp) if comp is not None else "nominal"}
    report["homing"] = homing

    def make_command(position_rad: float, feedforward_nm: float, cap_nm: float):
        # WHY this command (bam_fivebar_recovery.backend.PlantBackend.write; mujoco_plant.tick): ilimit_scale 0 and no velocity target -
        # the boards run as PDs, which is what the sequences' caps and stall thresholds were tuned against on the MuJoCo rung.
        # WHY no board trajectory (velocity and accel limits inf = moteus "none"; the first real run, 2026-11-13): a plain position
        # command leaves CAN 12's servo.default_accel_limit (100 rev/s^2, records/fivebar-bench) in charge, so the firmware walks its
        # control position from where IT is - a seek's setpoint 25 deg into the stop after its press - to the new setpoint and feeds that
        # trajectory's velocity to the D term: at the re-hold after the recovery's J2 seek the board pushed J2 off its stop at +7.7 N.m,
        # 91-93 deg/s on all four starts (real_two_level_touch_gff_*). The MuJoCo rung's boards are plain PDs; so are these now.
        return TrajectoryCommand(position_rad=float(position_rad), velocity_rad_s=0.0, feedforward_torque_nm=float(feedforward_nm),
                                 kp_scale=1.0, kd_scale=1.0, ilimit_scale=0.0, maximum_torque_nm=float(cap_nm),
                                 velocity_limit_rad_s=math.inf, accel_limit_rad_s2=math.inf)

    def j1_command(j1_rad: float):
        return _command(float(j1_rad), 0.0, J1_HOLD_NM)

    home = np.asarray(homed.home, dtype=float)

    def within(joints, target, tol_deg: float) -> bool:
        return bool(np.max(np.abs(np.degrees(home_offset(joints, target)))) <= tol_deg)

    def walk_and_release(target_joint: np.ndarray, label: str) -> dict:
        target_joint = np.asarray(target_joint, dtype=float)
        entry: dict[str, Any] = {"label": label, "target_joint_deg": np.degrees(target_joint).round(4).tolist()}
        held = bool(getattr(bus, "holding", False))
        if held:
            bus.take_over()
            entry["taken_over"] = True
        began = time.monotonic()
        now = servo_map.to_joint(np.asarray(bus.read().position_rad, dtype=float))
        stopped = all(int(m) == 0 for m in getattr(bus.read(), "mode", (0, 0)))
        if not held and stopped and within(now, target_joint, NEAR_DEG):
            # already resting there: nothing to walk (WHY: the home button refuses a rest its classifier calls past_straight, and the
            # real home rest sits on that boundary - real_rf_two_level_touch_gff_064427 ended on exactly that refusal, at home)
            entry["walk"] = f"already within {NEAR_DEG} deg, released"
        elif not held and within(now, home, LEG_SPAN_DEG) and within(target_joint, home, LEG_SPAN_DEG):
            # a few degrees about the hanging rest (every start): the real lane's board leg (tview's v0.1 a0.2 on the boards' own
            # trajectory, fivebar_homed.board_leg), then tview's release - the home button's classifier never gates a start
            sub: dict[str, Any] = {"j1_hold_rad": hold_j1_board(bus)}
            try:
                sub["leg"] = board_leg(bus, servo_map, target_joint, name=f"{label} (board leg)", reach_rad=HOME_REACH_RAD, rows=rows)
                sub["rest_board_rad"] = _release(bus)
            finally:
                entry["board_leg"] = sub
                entry["wall_s"] = round(time.monotonic() - began, 2)
        else:
            sub = {}
            try:
                run_home(bus, replace(homed, home=target_joint), servo_map, bench, out, sub, rows=rows, comp=comp)
            except RuntimeError as error:
                # the home button's classifier refusing at the very rest it walks to (the boundary above) is "there", not a failure
                rest_now = servo_map.to_joint(np.asarray(bus.read().position_rad, dtype=float))
                if "did not settle onto its working branch" in str(error) and within(rest_now, target_joint, NEAR_DEG) \
                        and not getattr(bus, "holding", False) and not getattr(bus, "braked", False):
                    entry["home_button_refused_at_target"] = str(error)
                    _release(bus)
                else:
                    entry["run_home"] = sub
                    raise
            finally:
                entry["run_home"] = sub
                entry["wall_s"] = round(time.monotonic() - began, 2)
        rest = bus.read()
        joints = servo_map.to_joint(np.asarray(rest.position_rad, dtype=float))
        state = classify(bench, joints)
        entry.update(rest_board_rad=[float(x) for x in rest.position_rad], rest_joint_deg=np.degrees(joints).round(4).tolist(),
                     rest_off_target_deg=np.degrees(home_offset(joints, target_joint)).round(4).tolist(),
                     rest_margins=[float(m) for m in state.margins], rest_kind=state.kind, j1_rad=float(getattr(rest, "j1_rad", math.nan)),
                     modes=[int(m) for m in getattr(rest, "mode", (-1, -1))])
        return entry

    def setup(start: RealStart) -> dict:
        target = np.asarray(homed.home, dtype=float) + np.radians(np.asarray(start.offset_deg, dtype=float))
        return walk_and_release(target, f"start {start.name}")

    def recover(reason: str, k: int) -> dict:
        """The home button after a trip, an abort or the stall gate (standing rule: recover yourself, then continue)."""
        entry = {"after_episode": k, "reason": reason}
        try:
            entry.update(walk_and_release(np.asarray(homed.home, dtype=float), "home button (recovery)"))
            entry["result"] = "home"
        except Exception as error:  # noqa: BLE001 - recorded, then judged below
            entry["result"] = f"{type(error).__name__}: {error}"
            homing["recoveries"].append(entry)
            raise
        homing["recoveries"].append(entry)
        return entry

    def is_trip(error: BaseException) -> bool:
        return isinstance(error, PlantTrip)

    # wall = epoch seconds, so a tick lines up with the D435's own wall stamps (record.py's stamps.npz) for the report's video
    plant = RealRigPlant(bus, make_command=make_command, j1_command=j1_command, setup=setup, signs=signs, dt=DT, wall=time.time)
    for k, start in enumerate(starts):
        row.references, row.notes = [], {}
        record: dict[str, Any] = {"schema": "sim2real_homing_real_episode/1", "procedure": name, "episode": k, "start": start.name,
                                  "start_offset_deg": list(start.offset_deg), "start_why": start.why,
                                  "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        guard = StopGuard()
        phase, result, incident = None, None, None
        report["phase"] = f"homing {name}: start {start.name} ({k + 1} of {len(starts)})"
        try:
            plant.reset(start)
            record["start_record"] = plant.start_record
            began = time.monotonic()
            phase = run_phase_real(plant, sequence, guard=guard, dt=DT, is_trip=is_trip)
            record["run_wall_s"] = round(time.monotonic() - began, 2)
            record["status"], record["message"] = phase.status, phase.message
            record["time_s"] = plant.time if phase.status == "done" else None
            if phase.status == "done":
                try:
                    result = row.observe(prior, [phase])
                except Exception as error:  # HomingRefused: an outcome
                    record["refused"] = f"{type(error).__name__}: {error}"
        except SequenceStopped as stop:
            phase = stop.phase
            incident = {"kind": stop.kind, "message": str(stop), "tick": plant.ticks, "time_s": plant.time,
                        "board_deg": [math.degrees(float(x)) for x in plant.reading.position_rad] if plant.reading is not None else None}
            record["status"], record["message"] = "stopped", str(stop)
            record["time_s"] = None
        except PlantTrip as trip:  # a trip outside the sequence (the start's walk): recorded, recovered below
            incident = {"kind": "trip during setup", "message": f"{type(trip).__name__}: {trip}", "held": getattr(trip, "held", None)}
            record["status"], record["message"] = "setup tripped", str(trip)
            record["time_s"] = None
            record["start_record"] = plant.start_record
        if result is None and incident is not None and phase is not None and incident["kind"] in ("runaway", "aborted", "limit"):
            # WHY (the real rung): a stop AFTER every step the procedure reads (its stalls, presses, defines) leaves its zero fully
            # evidenced - e.g. a runaway on the move home. The episode is still not reliable (not finished); its zero is kept, flagged
            # "evidence_complete", for the spread and the MuJoCo comparison, never for reliability.
            try:
                result = row.observe(prior, [phase])
                record["evidence_complete"] = True
            except Exception as error:  # noqa: BLE001 - a step it reads never ran
                record["evidence_complete"] = False
                record["evidence_missing"] = f"{type(error).__name__}: {error}"
                result = _observe_with_j1_steps_closed(row, prior, phase, record)
        record["incident"] = incident
        record["guard_checks"] = guard.checks
        if phase is not None:
            record["events"] = _event_dicts(phase.events)
        record["truth"] = plant.truth() if plant.reading is not None else None
        if result is not None:
            record["zeros_deg"] = _zeros_deg(result)
            try:
                record["zeros_vs_twin_deg"] = _zeros_deg(row.observe_vs_twin(prior, prepared["twin"], [phase]))
            except Exception as error:  # noqa: BLE001
                record["zeros_vs_twin_deg"] = {"refused": f"{type(error).__name__}: {error}"}
            record["evidence"] = [{"joint": ROLE[e.joint], "side": e.side, "torque_nm": e.torque_nm,
                                   "raw_deg": math.degrees(e.motor_raw_rad)} for e in result.evidence]
            record["backlash"] = result.backlash.to_dict()
            stalls = []
            for phase_index, tick, joint, side in row.references:
                row_k = phase.log["plant_offset"] + tick
                board = math.degrees(plant.log["board_rad"][row_k][DRIVE_JOINTS.index(joint)])
                stalls.append({"joint": ROLE[joint], "side": side, "tick": tick, "board_deg": board,
                               "expected_board_deg": STALL_BOARD_DEG[joint], "off_deg": board - STALL_BOARD_DEG[joint]})
            record["stalls"] = stalls
        record["notes"] = json.loads(json.dumps(row.notes, default=str))
        record["finished"] = bool(result is not None and incident is None and "refused" not in record)
        homing["episodes"].append({key: record.get(key) for key in ("episode", "start", "status", "message", "time_s", "finished",
                                                                    "zeros_deg", "incident")})
        _save_episode(episodes_dir / f"{k:02d}_{start.name.replace(' ', '_')}", plant, phase, record)
        print(json.dumps({"episode": k, "start": start.name, "status": record["status"], "time_s": record.get("time_s"),
                          "zeros_deg": record.get("zeros_deg"), "incident": incident}, default=float), flush=True)
        if incident is not None:
            if getattr(bus, "braked", False):
                homing["ended"] = f"braked after episode {k}: a lost bus or a board fault; nothing walks a braked arm"
                raise RuntimeError(homing["ended"])
            recover(incident["message"], k)
    # the session ends at home, released (the frames carried by fivebar_homed after the plant closes)
    homing["end"] = walk_and_release(np.asarray(homed.home, dtype=float), "end of session: home")
    return homing


# ---------------------------------------------------------------------------------------------------------------- scoring


def _median(values):
    return None if not values else statistics.median(values)


def load_episodes(run_dirs: list[Path]) -> dict[str, list[dict]]:
    """{procedure: [episode records]} from every run folder's episodes/*.json (in run then episode order)."""
    out: dict[str, list[dict]] = {}
    for run in run_dirs:
        for path in sorted((Path(run) / "episodes").glob("*.json")):
            record = json.loads(path.read_text())
            record["run_dir"] = str(run)
            record["file"] = str(path)
            out.setdefault(record["procedure"], []).append(record)
    return out


def mujoco_reference(mujoco: dict, name: str) -> dict:
    """The MuJoCo rung's zeros for ``name``: per model, the median zero error vs CAD per joint over its reliable starts, and its time."""
    from .bench import expand  # noqa: PLC0415

    out = {}
    for model in mujoco["models"]:
        rows = (mujoco["episodes"].get(model) or {}).get(name) or []
        errors = {"J2": [], "C1": []}
        for r in rows:
            record = expand(r, name, model)
            if not (record.finished and record.stalls and all(s.ok() for s in record.stalls)):
                continue
            for j in record.joints:
                if ROLE[j.joint] in errors and j.zero_error_deg is not None:
                    errors[ROLE[j.joint]].append(j.zero_error_deg)
        card = mujoco["scorecards"][model].get(name) or {}
        out[model] = {"zero_error_median_deg": {k: _median(v) for k, v in errors.items()}, "n": len(errors["J2"]),
                      "time_to_home_s": card.get("time_to_home_s"), "reliability_pct": card.get("reliability_pct")}
    return out


def score(run_dirs: list[Path], *, mujoco_json: Path = MUJOCO_JSON, out: Path = RESULTS_JSON, video: dict | None = None,
          notes: Path | None = None) -> dict:
    """The real rung's results JSON: per row reliability, the zero's repeat spread, real vs MuJoCo, time to home; the gates."""
    from robot_models.homing.metrics import EpisodeRecord, JointOutcome, StallCheck, scorecard  # noqa: PLC0415

    from .bench import compact  # noqa: PLC0415

    mujoco = json.loads(Path(mujoco_json).read_text())
    by_row = load_episodes(run_dirs)
    rows_out, cards, episodes, verdicts, table_rows = {}, {}, {}, {}, {}
    medians: dict[str, dict[str, float]] = {}
    ran = [n for n in ROWS if by_row.get(n)]
    for name in ran:
        records = by_row.get(name, [])
        ep_records, real_rows = [], []
        for r in records:
            stalls = tuple(StallCheck(s["joint"], s["side"], s["board_deg"], s["expected_board_deg"]) for s in r.get("stalls") or [])
            joints = tuple(JointOutcome(role, None, None, None) for role in ("J2", "C1"))
            outcome = "done" if r["finished"] else (r.get("refused") or r.get("message") or r.get("status"))
            ep_records.append(EpisodeRecord(name, ENVIRONMENT, r["start"], bool(r["finished"]), str(outcome), r.get("time_s"), stalls, joints))
        card = scorecard(ep_records, gate_deg=GATE_DEG, reliability_target_pct=RELIABILITY_TARGET_PCT) if ep_records else {}
        from robot_models.homing.metrics import reliable  # noqa: PLC0415

        # the zero's evidence: every reliable start, and every start stopped after its last reference step whose stalls were all on
        # their stops (evidence_complete; run_homing says why) - never counted as reliable
        good = [r for r, e in zip(records, ep_records, strict=True)
                if r.get("zeros_deg") and e.stalls and all(st.ok() for st in e.stalls) and (reliable(e) or r.get("evidence_complete"))]
        zeros = {role: [r["zeros_deg"][role] for r in good if r.get("zeros_deg")] for role in ("J2", "C1")}
        zeros_twin = {role: [r["zeros_vs_twin_deg"][role] for r in good if isinstance(r.get("zeros_vs_twin_deg"), dict)
                             and role in r["zeros_vs_twin_deg"]] for role in ("J2", "C1")}
        med = {role: _median(v) for role, v in zeros.items()}
        medians[name] = med
        spread = {role: (max(v) - min(v)) if len(v) >= 2 else None for role, v in zeros.items()}
        for r, e in zip(records, ep_records, strict=True):
            real_rows.append({"start": r["start"], "run": Path(r["run_dir"]).name, "finished": r["finished"], "reliable": reliable(e),
                              "evidence_complete": bool(r.get("evidence_complete") or reliable(e)), "zero_used": r in good,
                              "outcome": e.outcome, "time_s": r.get("time_s"),
                              "start_rest_joint_deg": ((r.get("start_record") or {}).get("setup") or {}).get("rest_joint_deg"),
                              "start_rest_board_deg": [math.degrees(x) for x in (r.get("start_record") or {}).get("board_rad") or []],
                              **{f"zero_deg_{role}": (r.get("zeros_deg") or {}).get(role) for role in ("J2", "C1")},
                              **{f"zero_minus_median_deg_{role}": (None if not r.get("zeros_deg") or med[role] is None
                                                                   else r["zeros_deg"][role] - med[role]) for role in ("J2", "C1")},
                              "stalls_off_deg": [round(s["off_deg"], 4) for s in r.get("stalls") or []],
                              "incident": r.get("incident")})
        card = dict(card)
        card["any_start_pct"] = None  # no true zero on the real arm (the spread and the MuJoCo comparison below are its zero checks)
        card.update({"episodes": len(records), "zero_median_deg": med, "zero_spread_deg": spread,
                     "zero_spread_max_deg": max((v for v in spread.values() if v is not None), default=None),
                     "zero_vs_twin_median_deg": {role: _median(v) for role, v in zeros_twin.items()}})
        cards[name] = card
        table_rows[name] = real_rows
        episodes[name] = [compact(e.to_dict()) for e in ep_records]
        rows_out[name] = {"mujoco": mujoco_reference(mujoco, MUJOCO_ROW.get(name, name)), "mujoco_row": MUJOCO_ROW.get(name, name),
                          "zero_starts": len(good)}
    # real vs MuJoCo: each row's zero against the rows' consensus, on each rung (module docstring of the results: "comparison")
    run_rows = [n for n in ran if all(medians.get(n, {}).get(role) is not None for role in ("J2", "C1"))]
    for name in ran:
        card = cards[name]
        comparison = {}
        if name in run_rows and len(run_rows) >= 2:
            for model in mujoco["models"]:
                per = {}
                for role in ("J2", "C1"):
                    real_consensus = statistics.mean(medians[n][role] for n in run_rows)
                    sim = {n: rows_out[n]["mujoco"][model]["zero_error_median_deg"][role] for n in run_rows}
                    if any(v is None for v in sim.values()):
                        per[role] = None
                        continue
                    sim_consensus = statistics.mean(sim.values())
                    real_dev = medians[name][role] - real_consensus
                    sim_dev = sim[name] - sim_consensus
                    per[role] = {"real_minus_consensus_deg": real_dev, "mujoco_minus_consensus_deg": sim_dev,
                                 "real_minus_mujoco_deg": real_dev - sim_dev}
                comparison[model] = per
        worst = [abs(v["real_minus_mujoco_deg"]) for per in comparison.values() for v in per.values() if v]
        card["real_minus_mujoco_deg"] = max(worst) if worst else None
        rows_out[name]["comparison"] = comparison
        reliability_ok = card.get("reliability_pct") == RELIABILITY_TARGET_PCT and card.get("episodes", 0) >= 4
        enough = rows_out[name]["zero_starts"] >= 4
        spread_ok = enough and card.get("zero_spread_max_deg") is not None and card["zero_spread_max_deg"] <= GATE_DEG
        mujoco_ok = enough and card["real_minus_mujoco_deg"] is not None and card["real_minus_mujoco_deg"] <= GATE_DEG
        verdicts[name] = {"reliability_pct": card.get("reliability_pct"), "reliability_gate_pass": bool(reliability_ok),
                          "zero_spread_max_deg": card.get("zero_spread_max_deg"), "spread_gate_pass": bool(spread_ok),
                          "real_minus_mujoco_deg": card["real_minus_mujoco_deg"], "vs_mujoco_gate_pass": bool(mujoco_ok),
                          "zero_starts": rows_out[name]["zero_starts"],
                          "pass": bool(reliability_ok and spread_ok and mujoco_ok)}
    for name, why in NOT_RUN.items():
        if name not in verdicts:
            verdicts[name] = {"pass": False, "not_run": why, "reliability_gate_pass": False, "spread_gate_pass": False,
                              "vs_mujoco_gate_pass": False}
    attempts = {}
    for name in RECOVER_ROWS:
        for r in by_row.get(name, []):
            attempts.setdefault(name, []).append({"start": r["start"], "run": Path(r["run_dir"]).name, "status": r.get("status"),
                                                  "incident": r.get("incident"), "time_s": r.get("time_s")})
    results = {
        "schema": "sim2real_homing_bench/1", "rig": "five-bar", "rung": RUNG, "attempts_recover_first": attempts, "models": ["rig"], "environment": ENVIRONMENT,
        "bundle_sha": BUNDLE_SHA, "hardstops_sha256": mujoco.get("hardstops_sha256"),
        "sim2real_sha": git_sha(Path(__file__).resolve().parents[4]), "robot_models_sha": git_sha(Path("/home/bam/robot_models")),
        "bam_ws_sha": git_sha(Path("/home/bam/bam_ws")), "gate_deg": GATE_DEG, "zero_vs_kinematic_deg": GATE_DEG,
        "reliability_target_pct": RELIABILITY_TARGET_PCT, "hidden_gap_arcmin": None, "dt_s": DT,
        "procedures": ran, "procedures_planned": list(ROWS), "not_run": NOT_RUN,
        "starts": [{"name": s.name, "offset_deg": list(s.offset_deg), "why": s.why} for s in STARTS],
        "stall_board_deg": {ROLE[j]: v for j, v in STALL_BOARD_DEG.items()}, "stall_gate_deg_live": STALL_GATE_DEG,
        "stall_tolerance_deg_scored": 1.0,
        "gates": {"reliability": "100 % of >= 4 starts finished with every referenced stall within 1.0 deg (robot_models "
                                 "STALL_TOLERANCE_DEG) of its stop's known board position (the live gate aborts at tview_run's 1.5)",
                  "spread": f"max - min of the identified zero over the reliable starts <= {GATE_DEG} deg, per joint (J2, C1)",
                  "vs_mujoco": f"|(row - consensus of the run rows) on the real arm - the same on the MuJoCo rung| <= {GATE_DEG} deg, "
                               "per joint, worst over B0 / B1 / B2 (the real arm has no truth, so each rung's zero is compared as its "
                               "offset from the rows' consensus: what a row adds or removes that its peers do not)"},
        "zero_frame": "q_URDF = sign x board + offset (sign J2 -1, C1 +1, homed_083647); the boards keep their frame across sessions "
                      "(frame check at every open), so zeros of different starts and rows compare directly",
        "j1": "held, never homed on the real rung (its CAD stops +-89.98 deg are unconfirmed on the rack; tview_run holds it)",
        "scorecards": {"rig": cards}, "verdicts": {"rig": verdicts}, "episodes": {"rig": episodes},
        "episode_columns": ["start", "finished", "outcome", "time_s", "stalls [joint, side, board_deg, expected_board_deg]",
                            "joints [joint, zero_error_deg (None: no truth), gap_identified_deg, gap_truth_deg]"],
        "real_rows": table_rows, "rows": rows_out, "mujoco_json": str(mujoco_json), "run_dirs": [str(p) for p in run_dirs],
        "video": video,
    }
    if notes is not None:
        # the page's prose (verdict, findings), written by the coordinator from these numbers, kept beside them
        results.update(json.loads(Path(notes).read_text()))
    Path(out).write_text(json.dumps(results, indent=1, default=float) + "\n")
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prior", help="sim2real's venv: write the prior JSON the rack's venv reads")
    p.add_argument("--out", type=Path, default=PRIOR_JSON)
    s = sub.add_parser("plan", help="print a row's planned sequence (no bus)")
    s.add_argument("name")
    s.add_argument("--prior", type=Path, default=PRIOR_JSON)
    c = sub.add_parser("score", help="the results JSON from run folders")
    c.add_argument("runs", type=Path, nargs="+")
    c.add_argument("--out", type=Path, default=RESULTS_JSON)
    c.add_argument("--video", type=Path, default=None, help="the hero clip's JSON (bam_ws docs/homing/clip_real_episode.py), plus a caption key")
    c.add_argument("--notes", type=Path, default=None, help="a JSON of page prose merged into the results (verdict_html, findings_html)")
    args = parser.parse_args(argv)
    if args.command == "prior":
        payload = write_prior(args.out)
        print(json.dumps({"out": str(args.out), "hardstops_sha256": payload["hardstops_sha256"]}))
    elif args.command == "plan":
        prepared = prepare_homing(args.name, args.prior)
        print(json.dumps({"max_cap_nm": prepared["max_cap_nm"], "steps": prepared["steps"]}, indent=1, default=float))
    else:
        video = None if args.video is None else json.loads(args.video.read_text())
        results = score(args.runs, out=args.out, video=video, notes=args.notes)
        print(json.dumps({"verdicts": results["verdicts"]}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
