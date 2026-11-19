"""sim2real.preflight(fitted): the check a calibrated RobotTwin passes before its values ship. Sim only.

    import sim2real
    fitted = twin.calibrate(on="sim")
    report = sim2real.preflight(fitted)          # soak_s=6.0, workers=1
    print(report.summary()); report.passed; report.to_dict()

WHY (Zach's 2026-11-19 pipeline, step 8: "preflight / wear-in before shipping"): a fit that recovered its values is not yet a twin you
can ship. Before the values reach a board, the twin is held to four blocking checks and one informational one, each a Check whose
`passed` is True, False or None ("could not be checked", with its reason; never a pass):

1. record_matches_description: every value the fitted twin carries has a unit and a source; every key the schedule says it identifies has
   a fitted value; the record (record_, sim2real.calibration/1) names this twin, and its units are the description's.
2. gains_within_board_limits: the kp / kd / ki the twin would ship (a tune step's fitted.settings_ and proposals_ when one ran, else the
   description's priors, else the board as it runs today: the description's joint and its unit's deployment record) inside the board's
   admissible range, and no integrator. WHY PD only (Zach, 2026-11-13): the real arm runs PD + feed-forward, never an integrator; a board
   that keeps its ki with ilimit 0 integrates nothing (moteus holds the integral to +-ilimit; bam_ws 9de804493), so ki 0 or ilimit 0 passes.
3. torque_margin: the peak torque over the planned envelope (the soak, and the fit's recorded runs when it holds them) under the torque
   cap. WHY this cap (the house rule): the motor's datasheet peak x the gear ratio x 0.97, read from the twin's robotparts parts; a
   gearbox whose own peak is lower binds instead.
4. sim_soak: a burn_in_wiggle (robot_trajectories) played on the fitted twin's simulator under the gains it would ship, then a hold: no
   NaN, no runner guard tripped (travel, overspeed, the proven window), settled by the end of the hold, the stop error inside the unit's
   own stop gate (cards: its deployment's servo.stop_error.dx), and no torque-cap hit (the house cap, or the board's current ceiling).
5. schedule_complete (informational: shown, never blocking): nothing the record needed was dropped, left uncovered or assumed by the
   schedule the fit played (plan_.dropped / uncovered / assumed, with their reasons). A routine dropped only because Budget.equipment lacks
   its kit is None, naming the items: the plan's equipment gate, not a fault of the twin.

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


def preflight(fitted, *, soak_s: float = 6.0, workers: int = 1) -> Preflight:
    """The preflight of a fitted RobotTwin (the module docstring). `soak_s`: at least this many seconds of wiggle (whole sweeps), then a
    hold. `workers`: the soak's replay pool (1: in this process)."""
    if not getattr(fitted, "fitted", False):
        raise RuntimeError("preflight needs a fitted twin: fitted = twin.calibrate(...), then sim2real.preflight(fitted)")
    started = time.monotonic()
    unit = _Unit.of(fitted)
    gains, shipped = _gains(fitted, unit)
    cap = _torque_cap(fitted, unit)
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
    identified = [k for s in plan.steps for k in s.identifies] if plan is not None else \
                 [k for r in (record.routines if record is not None else []) for k in r.get("identifies", [])]
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


def _gain_range() -> tuple[tuple[float, float], tuple[float, float]] | None:
    """pidtuna's admissible gain range, relative to the board's as-found gains ((kp low, high), (kd low, high)), or None without pidtuna.
    WHY this range (pidtuna types.Envelope): "a session never strays further than that from gains known to be safe"; it is the guard
    the tune itself is held to, so a shipped gain outside it is one nothing has shown the board tolerates."""
    try:
        if importlib.util.find_spec("pidtuna") is None and str(paths.PIDTUNA / "src") not in sys.path:
            sys.path.append(str(paths.PIDTUNA / "src"))
        envelope = importlib.import_module("pidtuna.types").Envelope()
    except Exception:  # noqa: BLE001
        return None
    return tuple(envelope.gain_scale_range), tuple(envelope.kd_range)


def _gains(fitted, unit: _Unit) -> tuple[Check, dict | None]:
    title = "the kp / kd / ki it would ship are inside the board's range, PD only (ki 0, or ilimit 0)"
    gain_unit = "N·m/rad, N·m·s/rad, N·m/(rad·s), N·m"
    shipped = _shipped(fitted, unit)
    if shipped is None:
        return Check("gains_within_board_limits", title, None, None, None, gain_unit,
                     "could not be checked: the twin states no gains to ship (no tune step's settings_, no kp/kd priors, no board record)"
                     + (f"; {'; '.join(unit.notes)}" if unit.notes else "")), None
    value = {k: shipped[k] for k in ("kp_nm_rad", "kd_nm_s_rad", "ki_nm_rad_s", "ilimit_nm")}
    ki, ilimit = shipped["ki_nm_rad_s"], shipped["ilimit_nm"]
    integrates = ki is None or (ki != 0.0 and ilimit != 0.0)
    problems = []
    if integrates:
        problems.append("ki is unknown" if ki is None else
                        f"ki {ki:g} N·m/(rad·s) with ilimit {ilimit} integrates: the real arm runs PD + feed-forward only (ki 0, or ilimit 0)")
    scale = _gain_range()
    limit = None
    if unit.board is not None and scale is not None:
        (kp_lo, kp_hi), (kd_lo, kd_hi) = scale
        kp0, kd0 = float(unit.board["kp"]) / TAU, float(unit.board["kd"]) / TAU
        limit = {"kp_nm_rad": [kp0 * kp_lo, kp0 * kp_hi], "kd_nm_s_rad": [kd0 * kd_lo, kd0 * kd_hi], "ki_nm_rad_s": 0.0}
        for name, (low, high) in (("kp_nm_rad", limit["kp_nm_rad"]), ("kd_nm_s_rad", limit["kd_nm_s_rad"])):
            if not low <= shipped[name] <= high:
                problems.append(f"{name.split('_')[0]} {shipped[name]:.4g} is outside [{low:.4g}, {high:.4g}]")
    where = (f"limits: the board's as-found kp {unit.board['kp']:g} / kd {unit.board['kd']:g} N·m/rev ({unit.record.name}) x pidtuna's "
             f"admissible range {scale[0]} / {scale[1]}") if limit else ""
    if problems:
        return Check("gains_within_board_limits", title, False, value, limit, gain_unit,
                     f"{'; '.join(problems)}. Shipped: {shipped['source']}" + (f"; {where}" if where else "")), shipped
    if limit is None:
        return Check("gains_within_board_limits", title, None, value, None, gain_unit,
                     f"could not be checked: no gain limit is declared (" + ("no board record" if unit.board is None else
                     "pidtuna, which holds the admissible range, cannot be imported here") + f"); PD only holds. Shipped: {shipped['source']}"), shipped
    return Check("gains_within_board_limits", title, True, value, limit, gain_unit,
                 f"kp {shipped['kp_nm_rad']:.4g} N·m/rad, kd {shipped['kd_nm_s_rad']:.4g} N·m·s/rad inside the range; "
                 f"{'ki 0' if ki == 0.0 else f'ki {ki:g} with ilimit 0'}: no integrator. Shipped: {shipped['source']}; {where}"), shipped


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
