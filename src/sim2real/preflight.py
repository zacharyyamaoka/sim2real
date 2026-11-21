"""sim2real.preflight(fitted): the check a calibrated RobotTwin passes before its values ship. Sim only.

    import sim2real
    fitted = twin.calibrate(on="sim")
    report = sim2real.preflight(fitted)          # soak_s=6.0, workers=1
    print(report.summary()); report.passed; report.to_dict()

WHY (Zach's 2026-11-19 pipeline, step 8: "preflight / wear-in before shipping"): a fit that recovered its values is not yet a twin you
can ship. Before the values reach a board, the twin is held to four blocking checks and one informational one, each a Check whose
`passed` is True, False or None ("could not be checked", with its reason; never a pass):

1. record_matches_description: every value the fitted twin carries has a unit and a source; every key the schedule says it identifies has
   a fitted value (a tune step's keys are settings, fitted.settings_, and are left to check 2); the record (record_, sim2real.calibration/1) names this twin, and its units are the description's.
2. gains_within_board_limits: the kp / kd / ki the twin would ship (a tune step's fitted.settings_ and proposals_ when one ran, else the
   description's priors, else the board as it runs today: the description's joint and its unit's deployment record) pass pidtuna's analytic
   bounds (pidtuna.analytic.limits, CONTRACT amendment 3) on the twin's model and stated loop, at pidtuna's own Objective() (its gain margin
   and its damping band's floor): the gain margin with the loop's delay, current loop, velocity filter and rate; the damping floor; the
   velocity-noise budget (kd x noise inside the tuner's chatter share of the cap); one encoder count against the cap; a third of the
   structural mode; the linear range. Each bound's value, limit and the source of every piece it read are in the check's limit. A bound
   whose piece the twin does not state is None, naming the piece, and the check is None ("could not be checked"), never True, except
   the structural mode, which pidtuna's §2 applies only to a known mode: unstated, it is "not applied" (in the limit, never a pass on
   its own) and blocks nothing; any bound
   broken is False with its numbers. A relative range only where one is stated (preflight(gain_range=...), with its source; pidtuna's
   Envelope states none since amendment 3). And no integrator. WHY PD only (Zach, 2026-11-13): the real arm runs PD + feed-forward, never
   an integrator; a board that keeps its ki with ilimit 0 integrates nothing (moteus holds the integral to +-ilimit; bam_ws 9de804493), so
   ki 0 or ilimit 0 passes.
3. torque_margin: the peak torque over the planned envelope (the soak, and the fit's recorded runs when it holds them) under the torque
   cap. WHY this cap (the house rule): the motor's datasheet peak x the gear ratio x 0.97, read from the twin's robotparts parts; a
   gearbox whose own peak is lower binds instead.
4. sim_soak: a burn_in_wiggle (robot_trajectories) played on the fitted twin's simulator under the gains it would ship, then a hold: no
   NaN, no runner guard tripped (travel, overspeed, the proven window), settled by the end of the hold, the stop error inside the unit's
   own stop gate (cards: its deployment's servo.stop_error.dx), and no torque-cap hit (the house cap, or the board's current ceiling).
5. schedule_complete (informational: shown, never blocking): nothing the record needed was dropped, left uncovered or assumed by the
   schedule the fit played (plan_.dropped / uncovered / assumed, with their reasons). A routine dropped only because Budget.equipment lacks
   its kit is None, naming the items: the plan's equipment gate, not a fault of the twin.

A nominal-world twin (sim2real.nominal: RobotTwin.from_robot_description of a description no sysid world binds) is checked per servo the
world drives, through the world itself (NominalRig): the gains it would ship are a tune's settings_ / proposals_, else the world's own board
loop (the description's stated kp / kd, or its default 5 Hz loop), ki 0 (the world's loop is PD); their bounds read the world's own board
loop (a PD per 1 kHz tick, the torque held over it, on the raw joint velocity: no delay, current loop or filter unless the description
states one), its mass matrix and gravity at the fitted values, its noise model, and the servo's datasheet cap, encoder bits and dead band. The soak is a
burn_in_wiggle per servo (the others held) inside the envelope the fit's tapes spanned, then a hold, on the description's MJCF at the
FITTED values under those gains and the fitted model's feed-forward, the command clipped at the cap; its stop gate is the strictest
servo.stop_error.dx any deployment card declares (a nominal twin names no unit). Each servo's cap is its motor's datasheet peak x its
gearbox ratio x 0.97, or an integrated servo's own datasheet peak (at its output) x 0.97 (robotparts' built part, else its user/ part
datasheet); the envelope is the soak's peak commanded torque.

What it reads, and from where, is each check's `why`. It writes nothing but the rack twin's scene cache (~/.cache/sim2real/sysid/scenes,
the pipeline's own). `workers` caps the soak's replay pool (1 replays in this process).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import math
import sys
import time
import types
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import paths

TAU = 2.0 * math.pi
HOUSE_CAP_FRACTION = 0.97          # the house torque cap: datasheet peak x gear ratio x 0.97 (Zach, 2026-11-13)
ROBOT_TRAJECTORIES = paths.env_path("SIM2REAL_ROBOT_TRAJECTORIES", "/home/bam/robot_trajectories")  # burn_in_wiggle's home
PARTS = ("dist", "site", "v2", "parts")   # robotparts' built part documents (<id>.json): specs with value, unit and source
SOAK_RATE_HZ = 200.0               # the schedule's command rate (bam_rack_twin schedule tapes)
HOLD_S = 1.5                       # the hold at home after the wiggle: the stop the soak judges
SETTLE_S = 0.5                     # the tail of the hold that must be still
STOP_DIAGNOSTIC = "servo.stop_error.dx"   # the unit's stop gate (cards deployments' UnitLimit, in mrad)
BLOCKING = ("record_matches_description", "gains_within_board_limits", "torque_margin", "sim_soak")
INFORMATIONAL = ("schedule_complete",)


@dataclass(frozen=True)
class Check:
    """One preflight check. `passed`: True, False, or None = could not be checked (`why` says why; never a pass). `value` and `limit` are
    JSON-ready (SI); `informational` checks are shown and never block."""
    id: str
    title: str
    passed: bool | None
    value: Any
    limit: Any
    unit: str
    why: str
    informational: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "passed": self.passed, "value": _plain(self.value), "limit": _plain(self.limit),
                "unit": self.unit, "why": self.why, "informational": self.informational}


@dataclass(frozen=True)
class Preflight:
    """preflight()'s report: the twin, its checks in order and the seconds it took. `passed`: every blocking check is True."""
    twin: str
    checks: tuple[Check, ...]
    seconds: float

    @property
    def passed(self) -> bool:
        blocking = [c for c in self.checks if not c.informational]
        return bool(blocking) and all(c.passed is True for c in blocking)

    def summary(self) -> str:
        lines = [f"preflight {self.twin}: {len(self.checks)} checks, {self.seconds:.1f} s"]
        for c in self.checks:
            word = {True: "pass", False: "FAIL", None: "unknown"}[c.passed]
            lines.append(f"  {word:7s} {c.id:28s}{' (informational)' if c.informational else ''} {c.title}")
            lines.append(f"          {c.why}")
        blocking = [c for c in self.checks if not c.informational]
        lines.append(f"  => {'PASS' if self.passed else 'FAIL'}: {sum(c.passed is True for c in blocking)}/{len(blocking)} blocking checks pass")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"twin": self.twin, "passed": self.passed, "seconds": self.seconds, "checks": [c.to_dict() for c in self.checks]}


def preflight(fitted, *, soak_s: float = 6.0, workers: int = 1, gain_range: Mapping[str, Any] | None = None) -> Preflight:
    """The preflight of a fitted RobotTwin (the module docstring). `soak_s`: at least this many seconds of wiggle (whole sweeps), then a
    hold. `workers`: the soak's replay pool (1: in this process). `gain_range`: a relative range the shipped gains must also sit in,
    {"kp": (low, high), "kd": (low, high), "source": "..."} times the as-found gains; it is a cap on the joint, so its source is required
    (a datasheet value, a measured limit, or the owner's dated words; pidtuna CONTRACT amendment 3). None: only a range pidtuna's
    Envelope states by default, which it no longer does."""
    if not getattr(fitted, "fitted", False):
        raise RuntimeError("preflight needs a fitted twin: fitted = twin.calibrate(...), then sim2real.preflight(fitted)")
    if gain_range is not None:
        _relative_range(gain_range)   # a stated range without its source is refused before anything plays
    started = time.monotonic()
    rig = _nominal_rig(fitted)
    if rig is not None:
        return _preflight_nominal(fitted, rig, soak_s=soak_s, started=started, gain_range=gain_range)
    unit = _Unit.of(fitted)
    cap = _torque_cap(fitted, unit)
    gains, shipped = _gains(fitted, unit, cap, gain_range)
    soak, soak_peak = _soak(fitted, unit, shipped, cap, soak_s=soak_s, workers=workers)
    checks = (_record(fitted, unit), gains, _torque_margin(fitted, cap, soak_peak), soak, _schedule(fitted))
    return Preflight(fitted.description.id, checks, round(time.monotonic() - started, 2))


# --- what the twin exposes about its unit ---------------------------------------------------------------------------------------------------


@dataclass
class _Unit:
    """What the checks read about the twin's unit, each None where the twin does not expose it: the servo instance id (the runner's typed
    instance), the joint description the schedule is built from (the sim runner's sysid description: range, speed, gains, current
    ceiling), the board's deployment-record component and the record's path."""
    servo: str | None = None
    joint: Any = None
    board: Mapping[str, Any] | None = None
    record: Path | None = None
    module: Any = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, fitted) -> _Unit:
        unit = cls()
        runner = fitted.runner
        try:
            unit.servo = runner.typed().id
        except Exception as error:  # noqa: BLE001  (a rig names its servos its own way)
            unit.notes.append(f"the runner names no one servo ({type(error).__name__}: {error})")
        try:
            unit.joint = runner.sysid_description().station_description
            unit.module = runner.pipeline()
        except Exception as error:  # noqa: BLE001
            unit.notes.append(f"the runner exposes no joint description ({type(error).__name__}: {error})")
        record = None if unit.joint is None else (getattr(unit.joint, "sources", None) or {}).get("record")
        if record and Path(record).is_file():
            unit.record = Path(record)
            components = json.loads(unit.record.read_text(encoding="utf-8")).get("components", [])
            component = next((c for c in components if c.get("can_id") == unit.joint.can_id), None)
            unit.board = None if component is None else component.get("moteus_config")
        return unit


# --- 1. the record against the description ---------------------------------------------------------------------------------------------------


def _is_tune(routine_id: str | None) -> bool:
    """True when the catalog (sim2real.calibration.plan.declaration) declares `routine_id` a tune routine."""
    from types import SimpleNamespace  # noqa: PLC0415

    from .calibration.plan import declaration  # noqa: PLC0415

    return routine_id is not None and declaration(SimpleNamespace(id=routine_id)).kind == "tune"


def _record(fitted, unit: _Unit) -> Check:
    title = "every value has a unit and a source; every identified key is fitted; the record matches the description"
    values = fitted.description.values()
    problems = []
    for key, value in values.items():
        if value is None:
            continue
        if not getattr(value, "unit", None):
            problems.append(f"{key} carries no unit")
        if not getattr(value, "source", None):
            problems.append(f"{key} carries no source")
    for name, value in (getattr(fitted, "values_", None) or {}).items():
        key = f"{unit.servo}.{name}" if unit.servo and "." not in name else name
        if value is not None and not (getattr(value, "unit", None) and getattr(value, "source", None)):
            problems.append(f"the fit's {key} lacks its unit or source")
    plan, record = getattr(fitted, "plan_", None), getattr(fitted, "record_", None)
    # WHY a tune step's keys are left out (gap C, lane L10): what a tune (pid.pidtuna) chooses are settings (fitted.settings_), never
    # fitted values or a record row, so "every identified key is fitted" does not hold for them; gains_within_board_limits checks them
    identified = [k for s in plan.steps if s.kind != "tune" for k in s.identifies] if plan is not None else \
                 [k for r in (record.routines if record is not None else []) for k in r.get("identifies", [])
                  if not (k in r.get("configures", ()) and _is_tune(r.get("routine")))]
    rows = {} if record is None else {row["key"]: row for row in record.parameters}
    for key in dict.fromkeys(identified):
        if values.get(key) is None:
            problems.append(f"{key} is identified by the schedule and has no fitted value")
        elif record is not None and (key not in rows or rows[key].get("value") is None):
            problems.append(f"{key} is identified by the schedule and the record holds no value for it")
    if record is not None:
        if record.twin != fitted.description.id:
            problems.append(f"the record is twin {record.twin!r}, the description {fitted.description.id!r}")
        for key, row in rows.items():
            if key not in values:
                problems.append(f"the record carries {key}, which the description does not")
            elif row.get("unit") and values[key] is not None and row["unit"] != values[key].unit:
                problems.append(f"{key}: the record's unit {row['unit']!r}, the description's {values[key].unit!r}")
    checked = sum(v is not None for v in values.values())
    if problems:
        return Check("record_matches_description", title, False, len(problems), 0, "problems",
                     f"{len(problems)} problem(s): " + "; ".join(problems))
    if record is None:
        return Check("record_matches_description", title, None, 0, 0, "problems",
                     f"could not be checked: the fitted twin holds no record (record_ is None: its runner reported no routines); "
                     f"its {checked} values each carry a unit and a source")
    return Check("record_matches_description", title, True, 0, 0, "problems",
                 f"{checked} values each carry a unit and a source (fitted.description); all {len(set(identified))} keys the schedule "
                 f"identifies (plan_) are fitted and in the record (record_, twin {record.twin!r}) with the description's units")


# --- 2. the gains the twin would ship ------------------------------------------------------------------------------------------------------


def _proposed(fitted, unit: _Unit) -> dict | None:
    """The tuned gains (SI) a tune step's proposal carries for this servo (fitted.proposals_: pidtuna's gains document), or None."""
    for proposal in (getattr(fitted, "proposals_", None) or {}).values():
        joints = (proposal or {}).get("joints", {}) if isinstance(proposal, Mapping) else {}
        mine = [j for name, j in joints.items() if name == unit.servo or (unit.joint is not None and j.get("can_id") == unit.joint.can_id)]
        mine = mine or (list(joints.values()) if len(joints) == 1 else [])
        if mine and isinstance(mine[0].get("tuned"), Mapping):
            return dict(mine[0]["tuned"].get("gains_si") or {})
    return None


def _shipped(fitted, unit: _Unit) -> dict | None:
    """{kp_nm_rad, kd_nm_s_rad, ki_nm_rad_s, ilimit_nm, source} the twin would ship, or None when it states none."""
    s = unit.servo
    board_ki = None if unit.board is None else float(unit.board.get("ki", 0.0)) / TAU
    board_ilimit = None if unit.board is None else unit.board.get("ilimit")
    settings = getattr(fitted, "settings_", None) or {}
    if s and f"{s}.kp_nm_rad" in settings and f"{s}.kd_nm_s_rad" in settings:
        tuned = _proposed(fitted, unit) or {}
        # WHY the board's ki and ilimit where the proposal states none: a tune proposes kp and kd only (pidtuna v2), the board keeps the rest
        ki = tuned.get("ki", board_ki)
        ilimit = tuned["ilimit"] if "ki" in tuned else board_ilimit
        return {"kp_nm_rad": float(settings[f"{s}.kp_nm_rad"]), "kd_nm_s_rad": float(settings[f"{s}.kd_nm_s_rad"]),
                "ki_nm_rad_s": None if ki is None else float(ki), "ilimit_nm": ilimit,
                "source": "the tune step's proposal (fitted.settings_ kp, kd; fitted.proposals_ ki, ilimit)"}
    priors = fitted.parameters.get(s, {}) if s else {}
    if priors.get("kp_nm_rad") is not None and priors.get("kd_nm_s_rad") is not None:
        ki = priors.get("ki_nm_rad_s")
        return {"kp_nm_rad": float(priors["kp_nm_rad"]), "kd_nm_s_rad": float(priors["kd_nm_s_rad"]),
                "ki_nm_rad_s": float(ki) if ki is not None else board_ki, "ilimit_nm": priors.get("ilimit_nm", board_ilimit),
                "source": "the description's priors (kp_nm_rad, kd_nm_s_rad)"}
    joint = unit.joint
    if joint is not None and getattr(joint, "kp_nm_rad", 0.0) > 0.0:
        return {"kp_nm_rad": float(joint.kp_nm_rad), "kd_nm_s_rad": float(joint.kd_nm_s_rad), "ki_nm_rad_s": board_ki,
                "ilimit_nm": board_ilimit,
                "source": f"the board as it runs today, no tune step having run: the description's joint (kp, kd) and its unit's "
                          f"deployment record ({unit.record.name if unit.record else 'none'}: ki, ilimit)"}
    return None


# WHY the analytic bounds and no relative range (pidtuna docs/CONTRACT.md amendment 3, v2.3, pidtuna 7a46660; Zach, 2026-11-20,
# zach_brain Settings/Memory/feedback_no_artificial_guards.md: every cap on a robot cites a datasheet, a measured limit or his dated words):
# pidtuna's old default guard, 0.25-2x the as-found gains, cited nothing, and on a friction-dominated pendulum it held kd under half of
# what the damping floor needs. The gains are held by pidtuna's analytic bounds on the twin's model and stated loop instead. Each bound
# needs pieces of the twin, each a (value, source), or (None, why it is missing): a bound with a piece missing is None, never a pass.
GAIN_TITLE = "the kp / kd it would ship pass pidtuna's analytic bounds on the twin's model and stated loop; PD only (ki 0, or ilimit 0)"
GAIN_UNIT = "N·m/rad, N·m·s/rad, N·m/(rad·s), N·m"
BOUND_NEEDS = {
    "gain margin": ("inertia_kg_m2", "loop_hz", "delay_s", "torque_bandwidth_hz", "velocity_filter_hz"),
    "damping floor": ("inertia_kg_m2",),
    "velocity noise": ("velocity_noise_rad_s", "torque_cap_nm"),
    "encoder count": ("encoder_quantum_rad", "torque_cap_nm"),
    "structural mode": ("inertia_kg_m2", "structural_hz"),
    "linear range": ("inertia_kg_m2", "torque_cap_nm", "travel_rad", "gravity_load_nm", "coulomb_nm", "backlash_rad"),
}
# a piece the description may state on the servo (<instance>.<name>, a Value with its source): it wins over the rig's own
STATED = {"delay_s": "command_delay_s", "torque_bandwidth_hz": "current_loop_hz", "loop_hz": "loop_hz", "velocity_filter_hz": "velocity_filter_hz",
          "velocity_noise_rad_s": "velocity_noise_rad_s", "encoder_quantum_rad": "encoder_quantum_rad", "structural_hz": "structural_hz"}
ARCMIN_RAD = math.pi / (180.0 * 60.0)


def _pidtuna(name: str):
    """A pidtuna module, imported now: the installed package, else the checkout at sim2real.paths.PIDTUNA (the tune routine's import)."""
    from .calibration.pid_tune import _pidtuna_module  # noqa: PLC0415

    return _pidtuna_module(name)


def _described(fitted, instance: str, name: str) -> tuple[float, str] | None:
    """(value, source) of a parameter the description states on `instance`, or None."""
    value = fitted.description.values().get(f"{instance}.{name}")
    if value is None or not math.isfinite(float(value)):
        return None
    return float(value), f"the description's {instance}.{name} ({getattr(value, 'source', None) or 'no source'})"


def _with_stated(fitted, instance: str, pieces: dict) -> dict:
    """`pieces`, each one the description states on `instance` (STATED) in place of the rig's own."""
    for piece, name in STATED.items():
        found = _described(fitted, instance, name)
        if found is not None:
            pieces[piece] = found
    return pieces


def _parts_of(fitted, instance: str) -> list[tuple[str, str]]:
    """(type, robotparts part) of the servo and of each child naming a part, the servo first."""
    own = [(i.type, i.part) for i in fitted.description.instances if i.id == instance and i.part]
    return own + [(i.type, i.part) for i in fitted.description.instances if i.parent == instance and i.part]


def _backlash(fitted, instance: str) -> tuple[float | None, str]:
    """The gear's dead band (rad): the larger of what the twin states (its backlash_rad) and its gear's robotparts datasheet backlash
    (arcmin). WHY the larger: an unidentified prior of 0 must not hide a datasheet's dead band (pidtuna's linear range also takes the
    larger of its loop's and its model's)."""
    found = [] if (stated := _described(fitted, instance, "backlash_rad")) is None else [stated]
    for kind, part in _parts_of(fitted, instance):
        sheet = _datasheet(part, "backlash") if kind in ("gearbox", "integrated_servo") else None
        if sheet is not None and sheet[1] == "arcmin":
            found.append((sheet[0] * ARCMIN_RAD, f"robotparts {part} backlash {sheet[0]:g} arcmin ({sheet[2]})"))
    if not found:
        return None, f"no backlash: neither the twin ({instance}.backlash_rad) nor a gear's robotparts datasheet states one"
    value, source = max(found, key=lambda f: f[0])
    others = [s for _, s in found if s != source]
    return value, source + (f"; the larger of it and {'; '.join(others)}" if others else "")


def _encoder_count(fitted, instance: str) -> tuple[float | None, str]:
    """One encoder count at the output (rad) from a robotparts datasheet: an integrated servo's encoder_bits (at its rotor) over its own
    gear_ratio, or its motor's encoder_bits over its gearbox's gear_ratio; None when no datasheet states the bits."""
    parts = _parts_of(fitted, instance)
    gears = [g for kind, part in parts if kind == "gearbox" and (g := _datasheet(part, "gear_ratio")) is not None]
    for kind, part in parts:
        bits = _datasheet(part, "encoder_bits") if kind in ("integrated_servo", "bldc_motor") else None
        if bits is None:
            continue
        gear = _datasheet(part, "gear_ratio") if kind == "integrated_servo" else (gears[0] if gears else None)
        has_gearbox = kind == "integrated_servo" or any(k == "gearbox" for k, _ in parts)
        if gear is None and has_gearbox and kind == "bldc_motor":
            continue
        ratio = 1.0 if gear is None else gear[0]
        return TAU / (2.0 ** bits[0] * ratio), (f"robotparts {part} encoder_bits {bits[0]:g} at the rotor ({bits[2]})"
                                                + (f" over gear_ratio {ratio:g} ({gear[2]})" if gear is not None else ", direct"))
    return None, (f"no encoder count: no robotparts datasheet of {instance}'s servo or motor states its encoder_bits (and the description "
                  f"states no {instance}.encoder_quantum_rad)")


NOT_APPLIED = "not applied: no structural mode stated (pidtuna §2 applies it to a known mode)"
# WHY a bound that is not applied rather than None (the coordinator's ruling, 2026-11-21): pidtuna's contract §2 bounds wn at a third of a
# KNOWN structural mode and analytic.limits treats an unstated one as no bound; preflight must not be stricter than the deploy it gates,
# or gains pidtuna delivers are blocked here. Every other unstated piece stays None: pidtuna needs those
APPLIED_ONLY_WHEN_STATED = {"structural mode": "structural_hz"}


def _no_structural_mode(instance: str) -> tuple[None, str]:
    return None, (f"{NOT_APPLIED}; {instance}.structural_hz in the description (a gearbox's or a belt's stiffness against the inertia, "
                  "from a datasheet or a measurement) would apply it")


def _finite(number: float) -> float | str:
    """A JSON-ready number: inf as the word (a margin with no crossing), never a silent None."""
    return float(number) if math.isfinite(number) else ("inf" if number > 0 else "-inf")


def _bounds(pieces: Mapping[str, tuple], kp: float, kd: float) -> dict[str, dict]:
    """pidtuna's analytic bounds for (kp, kd) on what the twin states (`pieces`: name -> (value, source), value None where it states none).
    Per bound {passed, value, limit, rule, unit, why, from}: decided by pidtuna.analytic.limits on pidtuna's own Objective() (its gain margin
    and its damping band's floor, the rule the tuner, its closed form and its oracle hold), the velocity-noise budget by the tuner's chatter
    rule (kd x velocity noise <= LoopModel.chatter_fraction x the cap: analytic.candidate's kd budget). A bound with a piece missing is
    {passed: None, missing: [why]}."""
    analytic, ptypes, gainlib = _pidtuna("pidtuna.analytic"), _pidtuna("pidtuna.types"), _pidtuna("pidtuna.gains")
    rules = ptypes.Objective()
    margin, floor = rules.gain_margin, rules.damping_band[0]
    have = {k: float(v) for k, (v, _) in pieces.items() if v is not None}
    inertia = have.get("inertia_kg_m2", 1.0)   # a placeholder only where every bound reading it is reported missing
    model = ptypes.PlantModel(inertia, have.get("viscous_nm_s_rad", 0.0), have.get("coulomb_nm", 0.0), backlash_rad=have.get("backlash_rad", 0.0))
    base = analytic.LoopModel()   # its loop numbers stand in only where the gain margin is reported missing
    loop = analytic.LoopModel(
        delay_s=have.get("delay_s", base.delay_s), torque_bandwidth_hz=have.get("torque_bandwidth_hz", base.torque_bandwidth_hz),
        velocity_filter_hz=have.get("velocity_filter_hz", base.velocity_filter_hz), loop_hz=have.get("loop_hz", base.loop_hz),
        velocity_noise_rad_s=have.get("velocity_noise_rad_s", 0.0), position_quantum_rad=have.get("encoder_quantum_rad", 0.0),
        torque_cap_nm=have.get("torque_cap_nm", math.inf), structural_hz=have.get("structural_hz", 0.0), travel=have.get("travel_rad", 0.0),
        gravity_load_nm=have.get("gravity_load_nm", 0.0), backlash_rad=have.get("backlash_rad", 0.0), min_damping=floor)
    gains = ptypes.Gains(kp, kd)
    verdict = analytic.limits(model, loop, gains, margin=margin, min_damping=floor)
    wn, zeta = gainlib.bandwidth_of(gains, model)
    cap, chatter = loop.torque_cap_nm, kd * loop.velocity_noise_rad_s
    rows = {
        "gain margin": (analytic.gain_margin(inertia, model.viscous_nm_s_rad, gains, loop, 0.0), margin, ">=", "", verdict["gain margin"],
                        f"pidtuna Objective().gain_margin {margin:g}, the loop's delay, current loop, velocity filter and rate in the loop "
                        "(analytic.gain_margin)"),
        "damping floor": (zeta, floor, ">=", "", verdict["damping"],
                          f"pidtuna Objective().damping_band's floor ({rules.damping_ratio:g} less its band; analytic.limits 'damping')"),
        "velocity noise": (chatter, loop.chatter_fraction * cap, "<=", " N·m", chatter <= loop.chatter_fraction * cap,
                           f"kd x the velocity noise within pidtuna LoopModel.chatter_fraction {loop.chatter_fraction:g} of the cap (the "
                           "tuner's chatter rule, analytic.candidate's kd budget)"),
        "encoder count": (kp * loop.position_quantum_rad, loop.quantum_fraction * cap, "<=", " N·m", verdict["quantization"],
                          f"kp x one count within pidtuna LoopModel.quantum_fraction {loop.quantum_fraction:g} of the cap"),
        "structural mode": (wn, TAU * loop.structural_hz / 3.0, "<=", " rad/s", verdict["structural mode"],
                            "wn within a third of the first structural mode (analytic.limits)"),
        "linear range": (kp + kd * wn, analytic.linear_range_budget(model, loop), "<=", " N·m/rad", verdict["linear range"],
                         f"kp + kd wn within the cap left after the gravity load and the Coulomb, over pidtuna LoopModel.linear_range "
                         f"{loop.linear_range:g} of the travel plus the backlash (analytic.linear_range_budget)"),
    }
    out = {}
    for name, (value, limit, rule, unit, ok, why) in rows.items():
        missing = [pieces.get(p, (None, f"no {p}"))[1] for p in BOUND_NEEDS[name] if pieces.get(p, (None,))[0] is None]
        optional = APPLIED_ONLY_WHEN_STATED.get(name)
        if optional is not None and pieces.get(optional, (None,))[0] is None and len(missing) == 1:
            out[name] = {"passed": "not applied", "value": _finite(value), "limit": None, "rule": rule, "unit": unit.strip(),
                         "why": missing[0], "from": {p: pieces[p][1] for p in BOUND_NEEDS[name] if p != optional}}
        elif missing:
            out[name] = {"passed": None, "value": None, "limit": None, "rule": rule, "unit": unit.strip(), "missing": missing}
        else:
            out[name] = {"passed": bool(ok), "value": _finite(value), "limit": _finite(limit), "rule": rule, "unit": unit.strip(), "why": why,
                         "from": {p: pieces[p][1] for p in BOUND_NEEDS[name]}}
    return out


def _bound_words(name: str, b: Mapping[str, Any]) -> str:
    if b["passed"] is None:
        return f"{name} could not be checked ({'; '.join(b['missing'])})"
    if b["passed"] == "not applied":
        return f"{name} {b['why']}"
    unit = f" {b['unit']}" if b["unit"] else ""
    shown = [v if isinstance(v, str) else f"{v:.4g}" for v in (b["value"], b["limit"])]
    return f"{name} {shown[0]}{unit} {'≥' if b['rule'] == '>=' else '≤'} {shown[1]}{unit}" + ("" if b["passed"] else " BROKEN")


def _relative_range(gain_range: Mapping[str, Any] | None) -> tuple[tuple | None, tuple | None, str] | None:
    """(kp range, kd range, source) relative to the as-found gains: the caller's (preflight(gain_range=...)), else pidtuna's Envelope
    default where it states one; None when neither states one. A caller's range names its source (pidtuna amendment 3)."""
    if gain_range is not None:
        source = gain_range.get("source")
        if not (isinstance(source, str) and source.strip()):
            raise ValueError("preflight(gain_range=...) is a cap on the joint's gains and needs its source beside it (\"source\": a "
                             "datasheet value, a measured limit, or the owner's dated words; pidtuna docs/CONTRACT.md amendment 3)")
        kp = tuple(gain_range["kp"]) if gain_range.get("kp") is not None else None
        kd = tuple(gain_range["kd"]) if gain_range.get("kd") is not None else kp
        return kp, kd, f"the caller's range ({source})"
    try:
        envelope = _pidtuna("pidtuna.types").Envelope()
    except Exception:  # noqa: BLE001  (no pidtuna: no Envelope to state one)
        return None
    kp, kd = getattr(envelope, "gain_scale_range", None), getattr(envelope, "kd_range", None)
    if kp is None and kd is None:
        return None
    return (None if kp is None else tuple(kp)), (None if kd is None else tuple(kd)), "pidtuna types.Envelope's default range"


def _servo_gains(label: str, shipped: dict, pieces: Mapping[str, tuple], relative, as_found: tuple[float, float] | None,
                 as_found_source: str) -> dict:
    """One servo's verdict on the gains it would ship: {limit, problems (False), unknown (None), words (what was computed)}."""
    kp, kd, ki, ilimit = shipped["kp_nm_rad"], shipped["kd_nm_s_rad"], shipped["ki_nm_rad_s"], shipped["ilimit_nm"]
    prefix = f"{label}: " if label else ""
    problems, unknown = [], []
    words = [f"{prefix}kp {kp:.4g} N·m/rad, kd {kd:.4g} N·m·s/rad"]
    if ki is None or (ki != 0.0 and ilimit != 0.0):
        problems.append(prefix + ("ki is unknown" if ki is None else
                                  f"ki {ki:g} N·m/(rad·s) with ilimit {ilimit} integrates: the real arm runs PD + feed-forward only (ki 0, or ilimit 0)"))
    limit: dict[str, Any] = {"ki_nm_rad_s": 0.0}
    try:
        bounds = _bounds(pieces, kp, kd)
    except ImportError as error:
        bounds = None
        unknown.append(f"{prefix}pidtuna, which holds the analytic bounds, cannot be imported here ({error}; no installed package, no "
                       f"checkout at {paths.PIDTUNA}: set SIM2REAL_PIDTUNA)")
    if bounds is not None:
        limit["bounds"] = bounds
        for name, b in bounds.items():
            (problems if b["passed"] is False else unknown if b["passed"] is None else words).append(prefix + _bound_words(name, b))
    if relative is not None:
        kp_range, kd_range, source = relative
        if as_found is None:
            unknown.append(f"{prefix}{source} is relative to the as-found gains, and the twin states none")
        else:
            ranges = {}
            for name, scale, base in (("kp_nm_rad", kp_range, as_found[0]), ("kd_nm_s_rad", kd_range, as_found[1])):
                if scale is None:
                    continue
                low, high = base * scale[0], base * scale[1]
                ranges[name] = [low, high]
                inside = low <= shipped[name] <= high
                (words if inside else problems).append(f"{prefix}{name.split('_')[0]} {shipped[name]:.4g} {'inside' if inside else 'outside'} "
                                                       f"[{low:.4g}, {high:.4g}] ({source} x {as_found_source})")
            limit["relative"] = {**ranges, "source": source}
    return {"limit": limit, "problems": problems, "unknown": unknown, "words": words}


def _gains_check(entries: Mapping[str, dict], value: Any, limit: Any, sources: str) -> Check:
    """The gains check over every servo's verdict: False when any rule is broken (its numbers named), else None when any bound could
    not be computed (naming the missing pieces), else True."""
    problems = [p for e in entries.values() for p in e["problems"]]
    unknown = [u for e in entries.values() for u in e["unknown"]]
    computed = "; ".join(w for e in entries.values() for w in e["words"])
    if problems:
        return Check("gains_within_board_limits", GAIN_TITLE, False, value, limit, GAIN_UNIT,
                     f"{'; '.join(problems)}. Inside: {computed}. Shipped: {sources}")
    if unknown:
        return Check("gains_within_board_limits", GAIN_TITLE, None, value, limit, GAIN_UNIT,
                     f"could not be checked: {'; '.join(unknown)}. Inside: {computed}. PD only holds. Shipped: {sources}")
    return Check("gains_within_board_limits", GAIN_TITLE, True, value, limit, GAIN_UNIT,
                 f"every analytic bound it applies is inside: {computed}; no integrator. Shipped: {sources}")


def _tracer_pieces(fitted, unit: _Unit, cap: dict) -> dict:
    """What the pendulum tracer's twin states for the bounds: the fitted servo values (the whole axis's inertia, viscous, the kinetic
    Coulomb, the gravity over the joint's range), the twin of record's board knobs (current loop, command delay), the driver's datasheet
    control rate, the world's measured velocity noise, the house torque cap, the gear's dead band."""
    s = unit.servo
    values = {k: float(v) for k, v in fitted.description.values().items() if v is not None and math.isfinite(float(v))}
    pieces: dict[str, tuple] = {}

    def fitted_piece(name: str, why: str) -> tuple:
        found = _described(fitted, s, name)
        return found if found is not None else (None, why)

    pieces["inertia_kg_m2"] = fitted_piece("armature_kg_m2", f"no inertia: the twin holds no {s}.armature_kg_m2")
    damping = values.get(f"{s}.damping_nm_s_rad")
    pieces["viscous_nm_s_rad"] = ((max(0.0, damping), f"the fitted {s}.damping_nm_s_rad") if damping is not None else
                                  (0.0, f"no {s}.damping_nm_s_rad: 0, the side that only lowers the margin and the damping"))
    static = values.get(f"{s}.frictionloss_nm")
    pieces["coulomb_nm"] = ((max(0.0, static - values.get(f"{s}.friction_stribeck_drop_nm", 0.0)),
                             f"the fitted {s}.frictionloss_nm less its Stribeck drop (the kinetic level)") if static is not None else
                            (None, f"no Coulomb friction: the twin holds no {s}.frictionloss_nm"))
    joint = unit.joint
    if joint is not None and getattr(joint, "range_rad", None) is not None:
        low, high = (float(x) for x in joint.range_rad)
        pieces["travel_rad"] = (max(abs(low), abs(high)), f"{joint.name}'s joint description range [{low:.3g}, {high:.3g}] rad about its origin")
        gravity, bottom = values.get(f"{s}.gravity_nm", 0.0), values.get(f"{s}.gravity_bottom_rad", 0.0)
        reach = [float(joint.origin_rad) + low + (high - low) * k / 400.0 for k in range(401)]
        pieces["gravity_load_nm"] = (max(abs(gravity * math.sin(q - bottom)) for q in reach),
                                     f"the fitted gravity {gravity:.4g} N·m sin(q - {bottom:.4g}) over the joint's range")
    else:
        pieces["travel_rad"] = (None, "no travel: the runner exposes no joint description")
        pieces["gravity_load_nm"] = (None, "no gravity load: the runner exposes no joint description")
    pieces["backlash_rad"] = _backlash(fitted, s)
    pieces["torque_cap_nm"] = (cap["cap_nm"], cap["why"]) if "cap_nm" in cap else (None, f"no torque cap: {cap['why']}")
    record = None
    if unit.module is not None and hasattr(unit.module, "twin"):
        try:
            record = unit.module.twin({k: float(v) for k, v in fitted.parameters.get(s, {}).items() if v is not None}, "preflight")
        except Exception as error:  # noqa: BLE001  (a pipeline builds its twin its own way)
            unit.notes.append(f"the twin of record could not be built ({type(error).__name__}: {error})")
    knobs = "the twin of record's board knobs (the sysid description's known.board_knobs)"
    lag, delay = getattr(record, "current_loop_hz", None), getattr(record, "command_delay_s", None)
    pieces["torque_bandwidth_hz"] = ((float(lag), f"{knobs}: current_loop_hz") if lag else (None, f"no current loop: {knobs} state none"))
    pieces["delay_s"] = ((float(delay), f"{knobs}: command_delay_s") if delay is not None else (None, f"no command delay: {knobs} state none"))
    pieces["loop_hz"] = _driver_rate(fitted, s)
    pieces["velocity_filter_hz"] = (None, f"no velocity filter: neither the description ({s}.velocity_filter_hz), the twin of record nor "
                                          f"the deployment record ({unit.record.name if unit.record else 'none'}) states the board's")
    noise = (getattr(fitted.runner, "state", None) or {}).get("noise") or {}
    speed = noise.get("speed_rad_s", noise.get("velocity_noise_rad_s"))
    pieces["velocity_noise_rad_s"] = ((float(speed), (noise.get("sources") or {}).get("speed_rad_s", "the world's noise block"))
                                      if speed else (None, "no velocity noise: the fit's noise record states none"))
    pieces["encoder_quantum_rad"] = _encoder_count(fitted, s)
    pieces["structural_hz"] = _no_structural_mode(s)
    return _with_stated(fitted, s, pieces)


def _driver_rate(fitted, instance: str) -> tuple[float | None, str]:
    """The board loop's rate (Hz): its driver's robotparts datasheet control_rate (a foc_controller child), the low end of a stated range
    (the slower loop leaves the smaller margin); None when no driver part states one."""
    for kind, part in _parts_of(fitted, instance):
        if kind != "foc_controller":
            continue
        path = Path(paths.ROBOTPARTS, *PARTS, f"{part}.json")
        spec = json.loads(path.read_text(encoding="utf-8")).get("specs", {}).get("control_rate") if path.is_file() else None
        raw = None if not spec else spec.get("value")
        scale = {"kHz": 1000.0, "Hz": 1.0}.get((spec or {}).get("unit"))
        if raw is None or scale is None:
            continue
        low = min(raw) if isinstance(raw, (list, tuple)) else raw
        return float(low) * scale, (f"robotparts {part} control_rate {spec.get('raw') or raw} ({spec.get('source_url', 'its datasheet')}): "
                                    "the low end, the slower loop")
    return None, f"no board loop rate: no driver part of {instance} states its control_rate (and the description states no {instance}.loop_hz)"


def _gains(fitted, unit: _Unit, cap: dict, gain_range: Mapping[str, Any] | None = None) -> tuple[Check, dict | None]:
    shipped = _shipped(fitted, unit)
    if shipped is None:
        return Check("gains_within_board_limits", GAIN_TITLE, None, None, None, GAIN_UNIT,
                     "could not be checked: the twin states no gains to ship (no tune step's settings_, no kp/kd priors, no board record)"
                     + (f"; {'; '.join(unit.notes)}" if unit.notes else "")), None
    value = {k: shipped[k] for k in ("kp_nm_rad", "kd_nm_s_rad", "ki_nm_rad_s", "ilimit_nm")}
    as_found = None if unit.board is None else (float(unit.board["kp"]) / TAU, float(unit.board["kd"]) / TAU)
    where = (f"the board's as-found kp {unit.board['kp']:g} / kd {unit.board['kd']:g} N·m/rev ({unit.record.name})"
             if unit.board is not None else "no board record")
    entry = _servo_gains("", shipped, _tracer_pieces(fitted, unit, cap), _relative_range(gain_range), as_found, where)
    return _gains_check({unit.servo or "": entry}, value, entry["limit"], shipped["source"]), shipped


# --- 3. the torque cap and the margin ------------------------------------------------------------------------------------------------------


def _spec(part: str, name: str) -> tuple[float, str] | None:
    """(value, unit) of a robotparts part's spec, from its built part document, or None."""
    path = Path(paths.ROBOTPARTS, *PARTS, f"{part}.json")
    if not path.is_file():
        return None
    spec = json.loads(path.read_text(encoding="utf-8")).get("specs", {}).get(name)
    if not spec or spec.get("value") is None:
        return None
    return float(spec["value"]), spec.get("unit", "")


def _torque_cap(fitted, unit: _Unit) -> dict:
    """{cap_nm, house_nm, motor, motor_peak_nm, gearbox, ratio, gearbox_peak_nm, why} or {why} when it cannot be had."""
    instances = fitted.description.instances
    mine = [i for i in instances if unit.servo is None or i.parent == unit.servo] or list(instances)
    motors = [i for i in mine if i.type == "bldc_motor"]
    gearboxes = [i for i in mine if i.type == "gearbox"]
    if len(motors) != 1 or motors[0].part is None:
        return {"why": f"the twin names {'no' if not motors else len(motors)} motor{'' if len(motors) == 1 else 's'}"
                       f"{' without a robotparts part' if len(motors) == 1 else ''} for its servo, so no datasheet peak (a twin built "
                       "from a robot description carries its parts: RobotTwin.from_robot_description)"}
    motor = motors[0]
    peak = _spec(motor.part, "peak_torque")
    if peak is None or peak[1] != "N·m":
        return {"why": f"robotparts states no peak torque in N·m for {motor.part} ({Path(paths.ROBOTPARTS, *PARTS)})"}
    ratio, gearbox, gearbox_peak = 1.0, None, None
    if gearboxes:
        gearbox = gearboxes[0].part
        stated = None if gearbox is None else _spec(gearbox, "gear_ratio")
        if stated is None:
            return {"why": f"the servo's gearbox ({gearboxes[0].id}) has no robotparts part stating its gear ratio"}
        ratio = stated[0]
        rated = _spec(gearbox, "peak_torque")
        gearbox_peak = None if rated is None or rated[1] != "N·m" else rated[0]
    house = peak[0] * ratio * HOUSE_CAP_FRACTION
    cap = house if gearbox_peak is None else min(house, gearbox_peak)
    why = (f"{motor.part} peak {peak[0]:g} N·m x {ratio:g}:1 ({gearbox or 'direct drive'}) x {HOUSE_CAP_FRACTION} = {house:.4g} N·m"
           + ("" if gearbox_peak is None else f"; the gearbox's own peak {gearbox_peak:g} N·m" + (" binds" if gearbox_peak < house else " does not bind")))
    return {"cap_nm": cap, "house_nm": house, "motor": motor.part, "motor_peak_nm": peak[0], "gearbox": gearbox, "ratio": ratio,
            "gearbox_peak_nm": gearbox_peak, "why": why}


def _data_peak(fitted) -> float | None:
    """The peak |torque| over the runs the fit holds (fitted.data_: train and held out), or None when it holds none with a torque."""
    data = getattr(fitted, "data_", None)
    peaks = []
    for pool in (getattr(data, "runs", None) or {}, getattr(data, "held_out", None) or {}):
        for run in pool.values():
            tau = getattr(getattr(run, "output", run), "tau", None)
            if tau is not None:
                try:
                    peaks.append(max(abs(float(x)) for x in tau))
                except (TypeError, ValueError):
                    continue
    return max(peaks) if peaks else None


def _torque_margin(fitted, cap: dict, soak_peak: float | None) -> Check:
    title = "the peak torque over the planned envelope stays under the cap (datasheet peak x ratio x 0.97)"
    data_peak = _data_peak(fitted)
    if "cap_nm" not in cap:
        return Check("torque_margin", title, None, None, None, "N·m", f"could not be checked: {cap['why']}")
    peaks = [p for p in (soak_peak, data_peak) if p is not None]
    if not peaks:
        return Check("torque_margin", title, None, None, cap["cap_nm"], "N·m",
                     f"could not be checked: no envelope (the soak did not run, and the fit holds no run with a torque); cap {cap['why']}")
    peak = max(peaks)
    margin = 100.0 * (cap["cap_nm"] - peak) / cap["cap_nm"]
    over = ", ".join(filter(None, [None if soak_peak is None else f"the soak's {soak_peak:.3f} N·m",
                                   None if data_peak is None else f"the fit's runs' {data_peak:.3f} N·m"]))
    return Check("torque_margin", title, peak < cap["cap_nm"], round(peak, 6), round(cap["cap_nm"], 9), "N·m",
                 f"peak {peak:.3f} N·m ({over}) against the cap {cap['cap_nm']:.3f} N·m ({cap['why']}): margin {margin:.1f} %")


# --- 4. the soak ---------------------------------------------------------------------------------------------------------------------------


def _wiggle(joint, soak_s: float):
    """robot_trajectories.burn_in_wiggle about the joint's home (its origin, 0) in its range, speed and acceleration, enough whole sweeps
    for `soak_s`; (t, q, qd, qdd) relative to the origin, a hold at home appended."""
    import numpy as np  # noqa: PLC0415

    if importlib.util.find_spec("robot_trajectories") is None and str(ROBOT_TRAJECTORIES / "src") not in sys.path:
        sys.path.append(str(ROBOT_TRAJECTORIES / "src"))
    rt = importlib.import_module("robot_trajectories")
    from robot_msgs.trajectory import JointLimits  # noqa: PLC0415

    limits = JointLimits(joint_names=(joint.name,), min_position=np.array([joint.range_rad[0]]), max_position=np.array([joint.range_rad[1]]),
                         max_velocity=np.array([joint.speed_rad_s]), max_acceleration=np.array([joint.accel_rad_s2]), position_kind=("software",))
    space = rt.JointSpace.from_limits(limits, home=[0.0], rate_hz=SOAK_RATE_HZ, source=f"{joint.name}'s joint description")
    motion = rt.burn_in_wiggle(space, sweeps=1)
    sweeps = max(1, math.ceil(soak_s / max(float(motion.t[-1]), 1e-9)))
    if sweeps > 1:
        motion = rt.burn_in_wiggle(space, sweeps=sweeps)
    t, q, qd = (np.asarray(x, float) for x in (motion.t, motion.positions[:, 0], motion.velocities[:, 0]))
    qdd = np.asarray(motion.accelerations[:, 0], float) if motion.accelerations is not None else np.gradient(qd, t)
    hold = np.arange(1, int(round(HOLD_S * SOAK_RATE_HZ)) + 1) / SOAK_RATE_HZ
    return (np.concatenate([t, t[-1] + hold]), np.concatenate([q, np.full(hold.size, q[-1])]),
            np.concatenate([qd, np.zeros(hold.size)]), np.concatenate([qdd, np.zeros(hold.size)]))


def _stop_gate(unit: _Unit) -> tuple[float, str] | None:
    """(rad, source) of the unit's stop gate: its deployment's UnitLimit for servo.stop_error.dx (cards/deployments/<record folder>.py)."""
    if unit.record is None or unit.joint is None:
        return None
    name = unit.record.parent.name.replace("-", "_")
    try:
        record = importlib.import_module(f"sim2real.cards.deployments.{name}").record
    except (ImportError, AttributeError):
        return None
    for limit in record.limits:
        if limit.device == f"CAN {unit.joint.can_id}" and limit.diagnostic == STOP_DIAGNOSTIC and limit.target is not None:
            return limit.target / 1000.0, f"sim2real/cards/deployments/{name}.py ({limit.source})"
    return None


def _soak(fitted, unit: _Unit, shipped: dict | None, cap: dict, *, soak_s: float, workers: int) -> tuple[Check, float | None]:
    import numpy as np  # noqa: PLC0415

    title = "a burn-in wiggle on the fitted twin: no NaN or instability, settled inside its stop gate, no torque-cap hit"
    joint, module = unit.joint, unit.module
    if joint is None or module is None or not all(hasattr(module, n) for n in ("twin", "replay", "_rack")) or unit.servo is None:
        return Check("sim_soak", title, None, None, None, "", "could not be checked: the soak plays the pendulum tracer's twin (the rack "
                     "twin behind its board's PID), which this twin's runner does not expose" + (f"; {'; '.join(unit.notes)}" if unit.notes else "")), None
    values = {name: float(v) for name, v in fitted.parameters.get(unit.servo, {}).items() if v is not None}
    bad = sorted(k for k, v in values.items() if not math.isfinite(v))
    if bad:
        return Check("sim_soak", title, False, None, None, "", f"the fitted values {bad} are not finite: nothing to soak"), None
    try:
        t, q, qd, qdd = _wiggle(joint, soak_s)
    except Exception as error:  # noqa: BLE001
        return Check("sim_soak", title, None, None, None, "", f"could not be checked: burn_in_wiggle could not be made ({type(error).__name__}: "
                     f"{error}; robot_trajectories at {ROBOT_TRAJECTORIES})"), None
    from bam_rack_twin import schedule as rack_schedule  # noqa: PLC0415  (the pendulum tracer's runtime: the rack twin)

    _, _, station = module._rack()
    pid = station.output_pid()
    # the feed-forward the twin would ship with: the fitted model's gravity, inertia and kinetic Coulomb (the static level less its drop)
    fitted_joint = replace(joint, gravity_nm=values.get("gravity_nm", joint.gravity_nm),
                           gravity_bottom_rad=values.get("gravity_bottom_rad", joint.gravity_bottom_rad),
                           inertia_kg_m2=values.get("armature_kg_m2", joint.inertia_kg_m2),
                           coulomb_nm=max(0.0, values.get("frictionloss_nm", joint.coulomb_nm) - values.get("friction_stribeck_drop_nm", 0.0)))
    integrates = shipped is None or shipped["ki_nm_rad_s"] is None or (shipped["ki_nm_rad_s"] != 0.0 and shipped["ilimit_nm"] != 0.0)
    # WHY the gains as scales on the board's own: the rack twin's runner sends kp/kd/ilimit scales on the board's configured gains
    mode = {"kp_scale": 1.0 if shipped is None else shipped["kp_nm_rad"] / (pid.kp / TAU),
            "kd_scale": 1.0 if shipped is None else shipped["kd_nm_s_rad"] / (pid.kd / TAU),
            "feedforward": ["gravity", "inertia", "coulomb"], "ilimit_scale": 1.0 if integrates else 0.0}
    trajectory = {"id": "preflight/soak", "runner_kind": "waypoints",
                  "target": {"t": t.tolist(), "q": q.tolist(), "qd": qd.tolist(), "qdd": qdd.tolist()}}
    name = "preflight/soak"
    try:
        run, _ = rack_schedule._synthetic_run(name, station, fitted_joint, trajectory, mode, 1.0)
        replayed = module.replay({name: run}, {"fitted": module.twin(values, "preflight")}, workers=max(1, int(workers)))[("fitted", name)]
    except (ValueError, FloatingPointError) as error:
        return Check("sim_soak", title, False, None, None, "", f"the fitted twin refused to run: {error}"), None
    error = replayed.q - run.q_target
    finite = bool(np.isfinite(replayed.q).all() and np.isfinite(replayed.qd).all() and np.isfinite(replayed.tau).all())
    peak = float(np.abs(replayed.tau).max()) if finite else None
    dt = float(np.median(np.diff(replayed.t)))
    tail = slice(-max(1, int(round(SETTLE_S / dt))), None)
    settle_speed = float(np.abs(replayed.qd[tail]).max()) if finite else None
    stop_error = float(abs(error[-1])) if finite else None
    reach = float(np.abs(q).max())
    # WHY the rack's own guards (bam_rack_twin.schedule._first_trip: travel, overspeed, the proven window), at the margin replay_schedule
    # gives its runs (the reach + 0.15 rad): the soak trips what the runner would trip, never a guard of its own
    guard = rack_schedule._first_trip(replayed, fitted_joint, travel_rad=reach + 0.15) if finite else None
    ceiling = joint.drive_torque_nm or joint.cap_command_nm
    gate = _stop_gate(unit)
    still = float(module.MOVING_RAD_S) if hasattr(module, "MOVING_RAD_S") else 0.03
    value = {"seconds": round(float(t[-1]), 3), "hold_s": HOLD_S, "peak_torque_nm": peak, "stop_error_rad": stop_error,
             "max_tracking_error_rad": float(np.abs(error).max()) if finite else None,
             "rms_tracking_error_rad": float(np.sqrt(np.mean(error ** 2))) if finite else None, "settle_speed_rad_s": settle_speed,
             "guard": guard, "kp_scale": round(mode["kp_scale"], 6), "kd_scale": round(mode["kd_scale"], 6), "integrator": integrates}
    limit = {"stop_error_rad": None if gate is None else gate[0], "settle_speed_rad_s": still, "torque_cap_nm": cap.get("cap_nm"),
             "board_ceiling_nm": ceiling}
    problems = []
    if not finite:
        problems.append("NaN or infinity in the replay")
    else:
        if guard:
            problems.append(f"a runner guard tripped: {guard}")
        if settle_speed > still:
            problems.append(f"not settled: still moving {math.degrees(settle_speed):.2f}°/s in the last {SETTLE_S:g} s of the hold "
                            f"(still is under {math.degrees(still):.2f}°/s)")
        if gate is not None and stop_error > gate[0]:
            problems.append(f"stop error {math.degrees(stop_error):.3f}° over the unit's stop gate {math.degrees(gate[0]):.3f}°")
        for what, bound in (("the torque cap", cap.get("cap_nm")), ("the board's current ceiling", ceiling)):
            if bound is not None and peak >= bound:
                problems.append(f"torque-cap hit: peak {peak:.3f} N·m >= {what} {bound:.3f} N·m")
    played = (f"burn_in_wiggle (robot_trajectories), {t[-1] - HOLD_S:.1f} s and a {HOLD_S:g} s hold, on the rack twin (pipeline.twin) at the "
              f"fitted values under kp x{mode['kp_scale']:.3g}, kd x{mode['kd_scale']:.3g} of the board's"
              f"{', its integrator on' if integrates else ', no integrator'} and the fitted feed-forward")
    if problems:
        return Check("sim_soak", title, False, value, limit, "", f"{'; '.join(problems)}. Played: {played}"), peak
    measured = (f"tracking error max {math.degrees(value['max_tracking_error_rad']):.3f}°, RMS {math.degrees(value['rms_tracking_error_rad']):.3f}°; "
                f"stop error {math.degrees(stop_error):.3f}°; peak {peak:.3f} N·m (board ceiling {ceiling:g} N·m)")
    if gate is None:
        return Check("sim_soak", title, None, value, limit, "", f"could not be checked: the unit declares no stop gate ({STOP_DIAGNOSTIC}); "
                     f"{measured}. Played: {played}"), peak
    return Check("sim_soak", title, True, value, limit, "",
                 f"{measured}, inside the stop gate {math.degrees(gate[0]):.3f}° ({gate[1]}); settled; no guard. Played: {played}"), peak


# --- 2-4 on a nominal-world twin (sim2real.nominal), per servo the world drives ------------------------------------------------------------

STILL_RAD_S = 0.03                 # "still" when no pipeline states it (the tracer path's fallback for MOVING_RAD_S)
TRAVEL_MARGIN_RAD = 0.15           # the travel guard past the soak's window (bam_rack_twin replay_schedule's reach + 0.15 rad)


def _nominal_rig(fitted):
    """The twin's NominalRig when its runner plays a nominal world (sim2real.nominal), else None (the tracer path)."""
    rig = getattr(getattr(fitted, "runner", None), "rig", None)
    if rig is None:
        return None
    from .nominal import NominalRig  # noqa: PLC0415

    return rig if isinstance(rig, NominalRig) else None


def _preflight_nominal(fitted, rig, *, soak_s: float, started: float, gain_range: Mapping[str, Any] | None = None) -> Preflight:
    servos = rig.servos
    shipped = {s.instance: _nominal_shipped(fitted, rig, s) for s in servos}
    caps = {s.instance: _servo_cap(fitted, s.instance) for s in servos}
    gains = _nominal_gains(fitted, rig, shipped, caps, gain_range)
    soak, peaks = _nominal_soak(fitted, rig, shipped, caps, soak_s=soak_s)
    checks = (_record(fitted, _Unit()), gains, _nominal_torque(caps, peaks), soak, _schedule(fitted))
    return Preflight(fitted.description.id, checks, round(time.monotonic() - started, 2))


def _nominal_shipped(fitted, rig, servo) -> dict:
    """{kp_nm_rad, kd_nm_s_rad, ki_nm_rad_s, ilimit_nm, source} the servo would ship on a nominal twin."""
    i = servo.instance
    settings = getattr(fitted, "settings_", None) or {}
    if f"{i}.kp_nm_rad" in settings and f"{i}.kd_nm_s_rad" in settings:
        tuned = _proposed(fitted, _Unit(servo=i)) or {}
        # WHY ki 0 where the proposal states none: the nominal world's board loop is PD (sim2real.nominal), there is no board ki to keep
        ki = float(tuned.get("ki", 0.0))
        ilimit = tuned.get("ilimit", 0.0) if "ki" in tuned else 0.0
        return {"kp_nm_rad": float(settings[f"{i}.kp_nm_rad"]), "kd_nm_s_rad": float(settings[f"{i}.kd_nm_s_rad"]), "ki_nm_rad_s": ki,
                "ilimit_nm": ilimit, "source": "the tune step's proposal (fitted.settings_ kp, kd; fitted.proposals_ ki, ilimit)"}
    params = fitted.description.instance(i).parameters
    ki, ilimit = params.get("ki_nm_rad_s"), params.get("ilimit_nm")
    return {"kp_nm_rad": float(servo.kp), "kd_nm_s_rad": float(servo.kd), "ki_nm_rad_s": 0.0 if ki is None else float(ki),
            "ilimit_nm": 0.0 if ilimit is None else float(ilimit),
            "source": f"no tune step having run, {rig.gains_source(i)}; ki " + ("0: the world's loop is PD" if ki is None else "as stated")}


def _nominal_pieces(fitted, rig, servo, cap: dict, model, envelope: Mapping[str, float], noise) -> dict:
    """What a nominal-world twin states for the bounds on one servo: the world's mass matrix and gravity at the fitted values (the others
    held at their start poses, as the soak holds them), its joint damping and frictionloss as it plays them, the envelope the soak plays,
    the world's own board loop (sim2real.nominal: a PD per BOARD_HZ tick, the torque held over it, on the raw joint velocity), its noise
    model, and the servo's datasheet torque cap, encoder count and dead band."""
    import mujoco  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    from .nominal import BOARD_HZ  # noqa: PLC0415

    i = servo.instance
    data = mujoco.MjData(model)

    def pose(q: float) -> None:
        data.qpos[:] = model.qpos0
        for other in rig.servos:
            data.qpos[other.qpos] = other.q0
        data.qpos[servo.qpos] = q
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)

    pose(servo.q0)
    dense = np.zeros((model.nv, model.nv))
    mujoco.mj_fullM(model, data, dense)
    inertia = float(dense[servo.dof, servo.dof])
    low, high = float(envelope["low_rad"]), float(envelope["high_rad"])
    gravity = 0.0
    for q in np.linspace(low, high, 41):
        pose(float(q))
        gravity = max(gravity, abs(float(data.qfrc_bias[servo.dof])))
    world = "the nominal world (sim2real.nominal NominalRig._play)"
    pieces = {
        "inertia_kg_m2": (inertia, f"the nominal world's mass matrix at {i}'s start pose ({servo.q0:.3g} rad, the others at theirs) at the "
                                   "fitted values (NominalRig.model_at)"),
        "viscous_nm_s_rad": (float(model.dof_damping[servo.dof]), f"{i}'s joint damping as the fitted twin plays it"),
        "coulomb_nm": (float(model.dof_frictionloss[servo.dof]), f"{i}'s joint frictionloss as the fitted twin plays it"),
        "travel_rad": (max(high - servo.q0, servo.q0 - low), f"the soak's envelope [{low:.3g}, {high:.3g}] rad about the start pose "
                                                             "(NominalRig.tape_envelope)"),
        "gravity_load_nm": (gravity, f"the largest gravity on {i} over that envelope (MuJoCo's qfrc_bias at rest, the others held)"),
        "backlash_rad": _backlash(fitted, i),
        "torque_cap_nm": (cap["cap_nm"], cap["why"]) if "cap_nm" in cap else (None, f"no torque cap: {cap['why']}"),
        "loop_hz": (BOARD_HZ, f"{world}: its board loop computes the PD once per {BOARD_HZ:g} Hz tick and holds the torque over it"),
        "delay_s": (0.0, f"{world}: each tick's PD torque acts within that tick, no command delay"),
        "torque_bandwidth_hz": (math.inf, f"{world}: the PD torque is applied as commanded, no current-loop lag"),
        "velocity_filter_hz": (math.inf, f"{world}: the PD reads MuJoCo's joint velocity, unfiltered"),
        "velocity_noise_rad_s": ((float(noise.velocity_noise_rad_s), noise.sources.get("velocity_noise_rad_s", "the world's noise model"))
                                 if noise is not None and noise.velocity_noise_rad_s > 0 else
                                 (None, "no velocity noise: the world's noise model states none")),
        "encoder_quantum_rad": ((float(noise.encoder_quantum_rad), noise.sources.get("encoder_quantum_rad", "the world's noise model"))
                                if noise is not None and noise.encoder_quantum_rad > 0 else _encoder_count(fitted, i)),
        "structural_hz": _no_structural_mode(i),
    }
    return _with_stated(fitted, i, pieces)


def _nominal_gains(fitted, rig, shipped: Mapping[str, dict], caps: Mapping[str, dict], gain_range: Mapping[str, Any] | None = None) -> Check:
    value = {i: {k: g[k] for k in ("kp_nm_rad", "kd_nm_s_rad", "ki_nm_rad_s", "ilimit_nm")} for i, g in shipped.items()}
    values = {k: float(v) for k, v in fitted.description.values().items() if v is not None and math.isfinite(float(v))}
    try:
        model, envelope, noise, failure = rig.model_at(values), rig.tape_envelope(), rig.noise(), None
    except Exception as error:  # noqa: BLE001  (a refused build is the soak's to fail; here it only leaves the pieces unstated)
        model, envelope, noise, failure = None, None, None, f"{type(error).__name__}: {error}"
    relative = _relative_range(gain_range)
    entries = {}
    for k, s in enumerate(rig.servos):
        pieces = ({"inertia_kg_m2": (None, f"no inertia: the fitted twin's world could not be built ({failure})")} if model is None else
                  _nominal_pieces(fitted, rig, s, caps[s.instance], model, envelope[k], noise))
        # WHY a relative range about the world's own loop (only when one is stated): the board config the fit was played under is the
        # nominal twin's as-found gains; a nominal twin has no board record
        entries[s.instance] = _servo_gains(s.instance, shipped[s.instance], pieces, relative, (s.kp, s.kd),
                                           f"{s.instance}'s nominal-world loop (kp {s.kp:.4g}, kd {s.kd:.4g})")
    sources = "; ".join(dict.fromkeys(f"{i}: {g['source']}" for i, g in shipped.items()))
    return _gains_check(entries, value, {i: e["limit"] for i, e in entries.items()}, sources)


def _datasheet(part: str, name: str) -> tuple[float, str, str] | None:
    """(value, unit, where) of a part's spec: robotparts' built part (dist/site/v2/parts/<id>.json), else its user/ part datasheet
    (user/parts/**/<id>/parameters.json, the chosen row), else None."""
    built = _spec(part, name)
    if built is not None:
        return built[0], built[1], f"{Path(*PARTS, part)}.json"
    for sheet in sorted(Path(paths.ROBOTPARTS, "user", "parts").rglob(f"{part}/parameters.json")):
        try:
            rows = json.loads(sheet.read_text(encoding="utf-8")).get("rows", [])
        except (OSError, ValueError):
            continue
        for row in rows:
            chosen = row.get("chosen")
            if row.get("id") == name and isinstance(chosen, Mapping) and chosen.get("value") is not None:
                try:
                    return float(chosen["value"]), row.get("unit", ""), f"{sheet.relative_to(paths.ROBOTPARTS)} ({chosen.get('source', '')})"
                except (TypeError, ValueError):
                    return None
    return None


def _servo_cap(fitted, instance: str) -> dict:
    """The servo's torque cap: its motor child's datasheet peak x its gearbox's ratio x 0.97 (the tracer path's _torque_cap), or, an
    integrated servo with no motor child, its own part's datasheet peak at the output x 0.97 (the gear is inside: the ratio is in the peak)."""
    children = [i for i in fitted.description.instances if i.parent == instance]
    if any(i.type == "bldc_motor" for i in children):
        return _torque_cap(fitted, _Unit(servo=instance))
    part = fitted.description.instance(instance).part
    if part is None:
        return {"why": f"{instance} names no robotparts part (and no motor child), so no datasheet peak"}
    peak = _datasheet(part, "peak_torque")
    if peak is None or peak[1] != "N·m":
        return {"why": f"robotparts carries no datasheet peak torque in N·m for {instance}'s part {part} (looked in "
                       f"{Path(paths.ROBOTPARTS, *PARTS)} and user/parts/**/{part}/parameters.json)"}
    cap = peak[0] * HOUSE_CAP_FRACTION
    return {"cap_nm": cap, "house_nm": cap, "motor": part, "motor_peak_nm": peak[0], "gearbox": None, "ratio": 1.0, "gearbox_peak_nm": None,
            "why": f"{part} peak {peak[0]:g} N·m at its output ({peak[2]}) x {HOUSE_CAP_FRACTION} = {cap:.4g} N·m"}


def _nominal_torque(caps: Mapping[str, dict], peaks: Mapping[str, float] | None) -> Check:
    title = "the peak torque over the planned envelope stays under the cap (datasheet peak x ratio x 0.97)"
    unknown = {i: c["why"] for i, c in caps.items() if "cap_nm" not in c}
    if not peaks:
        known = {i: c for i, c in caps.items() if "cap_nm" in c}
        first = next(iter(known.values()), None)
        return Check("torque_margin", title, None, None, None if first is None else first["cap_nm"], "N·m",
                     "could not be checked: no envelope (the soak did not run)" + "".join(f"; {i}: cap {c['why']}" for i, c in caps.items()))
    rows, worst = [], None
    for i, cap in caps.items():
        if "cap_nm" not in cap or peaks.get(i) is None:
            continue
        margin = 100.0 * (cap["cap_nm"] - peaks[i]) / cap["cap_nm"]
        rows.append(f"{i} peak {peaks[i]:.3f} N·m against {cap['cap_nm']:.3f} N·m ({cap['why']}): margin {margin:.1f} %")
        if worst is None or margin < worst[0]:
            worst = (margin, i, peaks[i], cap["cap_nm"])
    over = worst is not None and worst[0] <= 0.0
    if over or not unknown:
        if worst is None:
            return Check("torque_margin", title, None, None, None, "N·m", "could not be checked: no servo has both a cap and a soak peak")
        return Check("torque_margin", title, not over, round(worst[2], 6), round(worst[3], 9), "N·m",
                     f"the soak's peak commanded torque per servo: {'; '.join(rows)}"
                     + "".join(f"; {i}: could not be checked, {why}" for i, why in unknown.items()))
    return Check("torque_margin", title, None, None if worst is None else round(worst[2], 6), None if worst is None else round(worst[3], 9),
                 "N·m", "could not be checked: " + "; ".join(f"{i}: {why}" for i, why in unknown.items())
                 + (f"; checked: {'; '.join(rows)}" if rows else ""))


def _strictest_stop_gate() -> tuple[float, str] | None:
    """(rad, source) of the strictest servo.stop_error.dx target any deployment card declares (sim2real/cards/deployments/*.py): a
    nominal twin names no unit, so its stop gate is the house's tightest joint share, never a looser guess."""
    import pkgutil  # noqa: PLC0415

    from .cards import deployments  # noqa: PLC0415

    best = None
    for info in pkgutil.iter_modules(deployments.__path__):
        try:
            record = importlib.import_module(f"{deployments.__name__}.{info.name}").record
        except (ImportError, AttributeError):
            continue
        for limit in record.limits:
            if limit.diagnostic == STOP_DIAGNOSTIC and limit.target is not None and (best is None or limit.target < best[0]):
                best = (float(limit.target), f"sim2real/cards/deployments/{info.name}.py, {limit.device} ({limit.source})")
    return None if best is None else (best[0] / 1000.0, f"the strictest {STOP_DIAGNOSTIC} any deployment card declares: {best[1]}")


def _nominal_wiggle(rig, soak_s: float):
    """robot_trajectories.burn_in_wiggle over every servo the world drives (each in turn, the others held at their start pose) inside the
    envelope the fit's tapes spanned, at the board rate, enough whole sweeps for `soak_s`, then a hold: (t, q, qd, qdd), joints as columns."""
    import numpy as np  # noqa: PLC0415

    if importlib.util.find_spec("robot_trajectories") is None and str(ROBOT_TRAJECTORIES / "src") not in sys.path:
        sys.path.append(str(ROBOT_TRAJECTORIES / "src"))
    rt = importlib.import_module("robot_trajectories")
    from robot_msgs.trajectory import JointLimits  # noqa: PLC0415

    from .nominal import BOARD_HZ  # noqa: PLC0415

    servos, envelope = rig.servos, rig.tape_envelope()
    n = len(servos)
    limits = JointLimits(joint_names=tuple(s.joint for s in servos), min_position=np.array([e["low_rad"] for e in envelope]),
                         max_position=np.array([e["high_rad"] for e in envelope]), max_velocity=np.array([e["speed_rad_s"] for e in envelope]),
                         max_acceleration=np.array([e["accel_rad_s2"] for e in envelope]), position_kind=("software",) * n)
    space = rt.JointSpace.from_limits(limits, home=[s.q0 for s in servos], rate_hz=BOARD_HZ,
                                      source="the nominal world's train tapes' envelope (NominalRig.tape_envelope)")
    motion = rt.burn_in_wiggle(space, sweeps=1)
    sweeps = max(1, math.ceil(soak_s / max(float(motion.t[-1]), 1e-9)))
    if sweeps > 1:
        motion = rt.burn_in_wiggle(space, sweeps=sweeps)
    t = np.asarray(motion.t, float)
    q = np.asarray(motion.positions, float).reshape(t.size, n)
    qd = np.asarray(motion.velocities, float).reshape(t.size, n)
    qdd = (np.asarray(motion.accelerations, float).reshape(t.size, n) if motion.accelerations is not None else np.gradient(qd, t, axis=0))
    hold = np.arange(1, int(round(HOLD_S * BOARD_HZ)) + 1) / BOARD_HZ
    return (np.concatenate([t, t[-1] + hold]), np.vstack([q, np.repeat(q[-1:], hold.size, axis=0)]),
            np.vstack([qd, np.zeros((hold.size, n))]), np.vstack([qdd, np.zeros((hold.size, n))]), envelope)


def _nominal_soak(fitted, rig, shipped: Mapping[str, dict], caps: Mapping[str, dict], *, soak_s: float) -> tuple[Check, dict | None]:
    import mujoco  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    title = "a burn-in wiggle on the fitted twin: no NaN or instability, settled inside its stop gate, no torque-cap hit"
    values = {k: float(v) for k, v in fitted.description.values().items() if v is not None}
    bad = sorted(k for k, v in values.items() if not math.isfinite(v))
    if bad:
        return Check("sim_soak", title, False, None, None, "", f"the fitted values {bad} are not finite: nothing to soak"), None
    try:
        model = rig.model_at(values)
    except ValueError as error:
        return Check("sim_soak", title, False, None, None, "", f"the fitted twin refused to build: {error}"), None
    try:
        t, q_ref, qd_ref, qdd_ref, envelope = _nominal_wiggle(rig, soak_s)
    except Exception as error:  # noqa: BLE001
        return Check("sim_soak", title, None, None, None, "", f"could not be checked: burn_in_wiggle could not be made ({type(error).__name__}: "
                     f"{error}; robot_trajectories at {ROBOT_TRAJECTORIES})"), None
    servos = rig.servos
    names = [s.instance for s in servos]
    qadr, dadr = np.array([s.qpos for s in servos]), np.array([s.dof for s in servos])
    kp = np.array([shipped[i]["kp_nm_rad"] for i in names])
    kd = np.array([shipped[i]["kd_nm_s_rad"] for i in names])
    cap = np.array([caps[i].get("cap_nm", np.inf) for i in names])
    # the feed-forward the twin would ship with (the real arm runs PD + feed-forward): the fitted model's rigid-body torque at the
    # reference, M(q) qdd + C(q, qd) qd + g(q) (MuJoCo's RNE), plus its viscous damping and kinetic Coulomb (frictionloss) at the reference
    scratch = mujoco.MjData(model)
    rne = np.zeros(model.nv)
    ff = np.empty_like(q_ref)
    damping, friction = model.dof_damping[dadr], model.dof_frictionloss[dadr]
    for k in range(t.size):
        scratch.qpos[:] = model.qpos0
        scratch.qpos[qadr] = q_ref[k]
        scratch.qvel[:] = 0.0
        scratch.qvel[dadr] = qd_ref[k]
        mujoco.mj_forward(model, scratch)
        scratch.qacc[:] = 0.0
        scratch.qacc[dadr] = qdd_ref[k]
        mujoco.mj_rne(model, scratch, 1, rne)
        ff[k] = rne[dadr] + damping * qd_ref[k] + friction * np.sign(qd_ref[k])
    data = mujoco.MjData(model)
    data.qpos[:] = model.qpos0
    data.qpos[qadr] = q_ref[0]
    mujoco.mj_forward(model, data)
    q, qd, tau = (np.empty_like(q_ref) for _ in range(3))
    with np.errstate(all="ignore"):
        for k in range(t.size):
            q[k], qd[k] = data.qpos[qadr], data.qvel[dadr]
            tau[k] = kp * (q_ref[k] - q[k]) + kd * (qd_ref[k] - qd[k]) + ff[k]
            # WHY clipped at the cap: the board saturates its command there; the hit itself fails the soak below
            data.qfrc_applied[dadr] = np.clip(tau[k], -cap, cap)
            mujoco.mj_step(model, data, nstep=rig.substeps)
    finite = bool(np.isfinite(q).all() and np.isfinite(qd).all() and np.isfinite(tau).all())
    error = q - q_ref
    tail = slice(-max(1, int(round(SETTLE_S / float(np.median(np.diff(t)))))), None)
    window = {i: (e["low_rad"] - TRAVEL_MARGIN_RAD, e["high_rad"] + TRAVEL_MARGIN_RAD) for i, e in zip(names, envelope)}
    per = (lambda a: {i: float(a[j]) for j, i in enumerate(names)}) if finite else (lambda a: None)
    peak = per(np.abs(tau).max(axis=0)) if finite else None
    stop = per(np.abs(error[-1])) if finite else None
    settle = per(np.abs(qd[tail]).max(axis=0)) if finite else None
    gate = _strictest_stop_gate()
    value = {"seconds": round(float(t[-1]), 3), "hold_s": HOLD_S, "peak_torque_nm": peak, "stop_error_rad": stop,
             "max_tracking_error_rad": per(np.abs(error).max(axis=0)) if finite else None,
             "rms_tracking_error_rad": per(np.sqrt(np.mean(error ** 2, axis=0))) if finite else None, "settle_speed_rad_s": settle,
             "kp_nm_rad": per(kp), "kd_nm_s_rad": per(kd)}
    limit = {"stop_error_rad": None if gate is None else gate[0], "settle_speed_rad_s": STILL_RAD_S,
             "torque_cap_nm": {i: caps[i].get("cap_nm") for i in names}, "travel_rad": {i: list(w) for i, w in window.items()}}
    problems = []
    if not finite:
        problems.append("NaN or infinity in the soak")
    else:
        for j, i in enumerate(names):
            low, high = window[i]
            if q[:, j].min() < low or q[:, j].max() > high:
                problems.append(f"{i}: travel guard tripped: left [{math.degrees(low):.1f}°, {math.degrees(high):.1f}°] (the tapes' window "
                                f"+ {math.degrees(TRAVEL_MARGIN_RAD):.1f}°)")
            if settle[i] > STILL_RAD_S:
                problems.append(f"{i}: not settled: still moving {math.degrees(settle[i]):.2f}°/s in the last {SETTLE_S:g} s of the hold "
                                f"(still is under {math.degrees(STILL_RAD_S):.2f}°/s)")
            if gate is not None and stop[i] > gate[0]:
                problems.append(f"{i}: stop error {math.degrees(stop[i]):.3f}° over the stop gate {math.degrees(gate[0]):.3f}°")
            if math.isfinite(cap[j]) and peak[i] >= cap[j]:
                problems.append(f"{i}: torque-cap hit: peak commanded {peak[i]:.3f} N·m >= the cap {cap[j]:.3f} N·m")
    played = (f"burn_in_wiggle (robot_trajectories) per servo, the others held, inside the fit's tapes' envelope, {t[-1] - HOLD_S:.1f} s and "
              f"a {HOLD_S:g} s hold, on {Path(fitted.description.model).name} at the fitted values (NominalRig.model_at) under the shipped "
              f"PD at {1.0 / (rig.substeps * model.opt.timestep):.0f} Hz, the fitted model's feed-forward, the command clipped at the cap")
    if problems:
        return Check("sim_soak", title, False, value, limit, "", f"{'; '.join(problems)}. Played: {played}"), peak
    measured = "; ".join(f"{i} tracking max {math.degrees(value['max_tracking_error_rad'][i]):.3f}°, stop {math.degrees(stop[i]):.3f}°, "
                         f"peak {peak[i]:.3f} N·m" for i in names)
    if gate is None:
        return Check("sim_soak", title, None, value, limit, "", f"could not be checked: no deployment card declares a stop gate "
                     f"({STOP_DIAGNOSTIC}); {measured}. Played: {played}"), peak
    return Check("sim_soak", title, True, value, limit, "",
                 f"{measured}; inside the stop gate {math.degrees(gate[0]):.3f}° ({gate[1]}); settled; no guard. Played: {played}"), peak


# --- 5. the schedule the fit played (informational) -----------------------------------------------------------------------------------------


def _schedule(fitted) -> Check:
    title = "nothing the record needed was dropped, left uncovered or assumed (plan_)"
    plan = getattr(fitted, "plan_", None)
    if plan is None:
        return Check("schedule_complete", title, None, None, None, "", "could not be checked: the fitted twin holds no plan_", informational=True)
    from .cards import registry as reg  # noqa: PLC0415

    catalog = {r.id: r for r in reg.ROUTINES}
    short, missing, faults, for_kit = [], [], [], []
    for rid, why in plan.dropped:
        # WHY the equipment gate's own words and the catalog's items (calibration.plan._equipment_drop: "needs <item> ($...), which
        # Budget.equipment does not list"): a drop for missing kit is the plan's budget, not a fault of the twin
        items = [e for e in getattr(catalog.get(rid), "equipment", ()) if f"{e} (" in why]
        if "Budget.equipment does not list" in why and items:
            short.append(f"{rid} (needs {', '.join(items)})")
            for_kit.append(rid)
            missing += [e for e in items if e not in missing]
        else:
            faults.append(f"dropped {rid}: {why}")
    # WHY a key left uncovered (or a requirement assumed) BECAUSE a routine was dropped for kit is part of that shortfall, not a fault of
    # its own: the planner says so in its reason ("its routine <id> was dropped: ...")
    for what, why in [(f"uncovered {i}.{n}", why) for i, n, why in plan.uncovered] + [(f"assumed {n} for {r}", why) for r, n, why in plan.assumed]:
        if any(f"{rid} was dropped" in why for rid in for_kit):
            short.append(f"{what} (its routine lacks kit)")
        else:
            faults.append(f"{what}: {why}")
    value = {"dropped": [list(d) for d in plan.dropped], "uncovered": [list(u) for u in plan.uncovered],
             "assumed": [list(a) for a in plan.assumed], "missing_equipment": missing}
    if faults:
        return Check("schedule_complete", title, False, value, None, "", "; ".join(faults + [f"dropped for missing equipment: {s}" for s in short]),
                     informational=True)
    if short:
        return Check("schedule_complete", title, None, value, None, "",
                     f"could not be checked: dropped only for missing equipment, Budget.equipment lacking {', '.join(missing)}: "
                     + "; ".join(short), informational=True)
    return Check("schedule_complete", title, True, value, None, "",
                 f"the {len(plan.steps)} planned routines ({', '.join(plan.ids)}) dropped, left uncovered and assumed nothing", informational=True)


def _plain(value):
    """JSON-ready: floats for robot_msgs Values and numpy scalars, lists for tuples."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)) or hasattr(value, "__float__"):
        number = float(value)
        return number if math.isfinite(number) else None
    return str(value)


class _CallableModule(types.ModuleType):
    """WHY callable (sim2real.preflight is this module): `sim2real.preflight(fitted)` calls the function, and `import sim2real.preflight`,
    `from sim2real.preflight import Check` still reach the module. A package attribute bound to the function would be overwritten by the
    import system the first time anyone imports the submodule, so the module itself is what sim2real hands out."""

    def __call__(self, fitted, **options):
        return preflight(fitted, **options)


sys.modules[__name__].__class__ = _CallableModule

__all__ = ["BLOCKING", "INFORMATIONAL", "Check", "Preflight", "preflight"]
