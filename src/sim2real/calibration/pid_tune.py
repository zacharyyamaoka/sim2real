"""PID tuna as a calibration routine: ``pid.pidtuna``, kind "tune" (gap C, docs/decision-pidtuna-tune-2026-11-18.md).

    from sim2real.calibration import PidTune
    PidTune("can11", servo=board, can_id=11)   # a schedule step: no run on the robot; it tunes on the twin the steps before it fitted

The SIM tier: once the fits before it have found the joint's inertia and friction, PID tuna (``pidtuna.tune``, /home/bam/pidtuna) tunes
the board's kp and kd on a ServoSim of the FITTED twin, under the fitted model's feed-forward held fixed (pidtuna v2: it owns only the
PD terms; the feed-forward is the model's). It proposes and never writes a board. What it returns are settings (the step's found,
fitted.settings_), never model values, and the board change it was made from rides along as ``proposal`` (fitted.proposals_). A tune
recovers no hidden value: it is graded on the performance it gains, against the best PD + feed-forward on a hidden truth
(sysid/results/routine_ladders/pid.pidtuna.json, written by tests/test_pid_tune_routine.py).

WHY sim2real -> pidtuna one way, imported only when the routine runs (Zach, 2026-11-11: PID tuna stays "its own standalone thing"):
importing sim2real imports no pidtuna, and pidtuna never imports sim2real; planning only asks whether it could import it
(``unavailable()``), so a machine without pidtuna plans the schedule with this step dropped by name.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import math
import sys
import warnings
from collections.abc import Mapping
from typing import Any, ClassVar

from .. import paths
from ..rig import Estimate

ROUTINE = "pid.pidtuna"
SETTINGS = ("kp_nm_rad", "kd_nm_s_rad")   # the board's feedback gains at the output, SI: the settings it proposes
REQUIRES = ("armature_kg_m2", "frictionloss_nm")   # what it tunes on: the fitted inertia and friction (hard edges)
USES = ("gravity_nm", "gravity_bottom_rad", "damping_nm_s_rad", "command_delay_s", "friction_stribeck_drop_nm")   # read when found
# WHY 200 Hz: the moteus board's current loop as the rack configures it (sysid/examples/pendulum_can11/description.json, known.board_knobs:
# current_loop_hz 200), the lag between the torque asked and the torque applied in the plant PID tuna tunes on
TORQUE_BANDWIDTH_HZ = 200.0


def importable() -> bool:
    """True when pidtuna can be imported here: installed, or a checkout at sim2real.paths.PIDTUNA (SIM2REAL_PIDTUNA). Imports nothing."""
    return importlib.util.find_spec("pidtuna") is not None or (paths.PIDTUNA / "src" / "pidtuna").is_dir()


def _pidtuna_module(name: str):
    """A pidtuna module, imported now: the installed package, else the checkout at sim2real.paths.PIDTUNA."""
    if importlib.util.find_spec("pidtuna") is None:
        src = str(paths.PIDTUNA / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
    return importlib.import_module(name)


def _close(servo_sim, plant) -> None:
    """Shut the process pool the tune played on, now, so its workers exit instead of idling until the interpreter does: through the
    public ``ServoSim.close()``, else through servo_sim's own pool registry, the one ``close()`` empties (the pool for this sim's
    worker count, waited for)."""
    close = getattr(plant, "close", None)
    if callable(close):
        close()
        return
    # WHY the registry fallback: pidtuna main has no ServoSim.close() yet (it waits on the local branch claude/l10-servosim-close,
    # 30d01e9, until the peer's v2 lanes settle), and a tune beside the powered arm must not leave its workers sitting there
    pools = getattr(servo_sim, "_POOLS", None)
    if not isinstance(pools, dict):
        warnings.warn("this pidtuna has neither ServoSim.close() nor servo_sim._POOLS: the tune's pool idles until the interpreter "
                      "exits", stacklevel=3)
        return
    for workers in [plant.workers] if plant.workers else list(pools):
        pool = pools.pop(workers, None)
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)


class Tuned(dict):
    """What a tune returns: {key: sim2real.rig.Estimate} for each setting it proposes, and ``proposal``, the reviewable board change it
    was made from (pidtuna's gains document, schema pidtuna/gains-1, plus the feed-forward it was tuned under and the tier)."""

    def __init__(self, settings: Mapping[str, Estimate], proposal: dict) -> None:
        super().__init__(settings)
        self.proposal = proposal


def _plant_model(types, values: Mapping[str, float], instance: str):
    """The fitted joint as pidtuna's PlantModel: tau = J qdd + b qd + tau_c sign(qd) + g_s sin q + g_c cos q, from the values the steps
    before it found (else the description's priors). The Coulomb is the KINETIC level: frictionloss is the static level from M3 up, the
    Stribeck drop falls from it (0 where no rung fitted one)."""
    def value(name: str, default: float | None = None) -> float | None:
        found = values.get(f"{instance}.{name}")
        return default if found is None or not math.isfinite(float(found)) else float(found)

    inertia, static = value("armature_kg_m2"), value("frictionloss_nm")
    if inertia is None or inertia <= 0.0 or static is None:
        raise ValueError(f"{ROUTINE} tunes on the fitted plant, and the values hold no usable {instance}.armature_kg_m2 ({inertia}) or "
                         f"{instance}.frictionloss_nm ({static}): the steps that find them run first (its requires)")
    gravity, bottom = value("gravity_nm", 0.0), value("gravity_bottom_rad", 0.0)
    kinetic = max(0.0, static - value("friction_stribeck_drop_nm", 0.0))
    # the pendulum's gravity torque G sin(q - bottom) = G cos(bottom) sin q - G sin(bottom) cos q
    return types.PlantModel(inertia, max(0.0, value("damping_nm_s_rad", 0.0)), kinetic, gravity * math.cos(bottom),
                            -gravity * math.sin(bottom), source="sim2real: the fitted twin's values")


@dataclasses.dataclass
class PidTune:
    """``pid.pidtuna`` on one servo instance (its keys are "<instance>.<name>"). ``servo``: the board as it runs today, a pidtuna Servo
    whose gains are the as-found controller (or a zero-argument callable that builds one when the routine runs, so planning never
    imports pidtuna). ``goal``: a pidtuna Objective (None: pidtuna's defaults, one repeat). ``can_id``: the board's id, checked against
    the servo's. It plays no run on the robot and needs no hands (the SIM tier); its pools are the twin's workers, closed when it is
    done."""
    instance: str = "can11"
    _: dataclasses.KW_ONLY
    servo: Any = None
    goal: Any = None
    can_id: int | None = None

    id: ClassVar[str] = ROUTINE
    kind: ClassVar[str] = "tune"
    identifies: ClassVar[tuple[str, ...]] = ()
    refines: ClassVar[tuple[str, ...]] = ()
    # WHY no wall_time_s here (2026-11-19): the catalog's (cards/calibration.py) is the one number, the SIM tier's compute on the fitted
    # twin as a cloud grade measured it, and the planner's declaration reads it there; "no robot time" is runs() being empty
    operator_time_s: ClassVar[float] = 0.0

    @property
    def configures(self) -> tuple[str, ...]:
        return tuple(f"{self.instance}.{name}" for name in SETTINGS)

    @property
    def requires(self) -> tuple[str, ...]:
        return tuple(f"{self.instance}.{name}" for name in REQUIRES)

    @property
    def uses(self) -> tuple[str, ...]:
        return tuple(f"{self.instance}.{name}" for name in USES)

    def runs(self, values: Mapping[str, float]) -> tuple:
        return ()   # the SIM tier tunes on the fitted twin: nothing plays on the robot

    def unavailable(self) -> str | None:
        """Why it cannot run on this machine (the planner drops it, naming this), or None. Imports nothing."""
        if importable():
            return None
        return f"pidtuna cannot be imported here (no installed package, no checkout at {paths.PIDTUNA}: set SIM2REAL_PIDTUNA)"

    def _as_run(self):
        """The board as it runs today (the servo, built now when it is a callable), checked against can_id."""
        servo = self.servo() if callable(self.servo) else self.servo
        if servo is None:
            raise ValueError(f"{ROUTINE} needs servo=: the board as it runs today (a pidtuna Servo, or a callable that builds one), whose "
                             "gains are the as-found controller")
        if self.can_id is not None and servo.can_id not in (None, self.can_id):
            raise ValueError(f"{ROUTINE}: can_id {self.can_id} names another board than the servo's ({servo.can_id})")
        return servo

    def _board(self, types, model, servo):
        """The board PID tuna plays: `servo` (as it runs) with its integrator off and the fitted plant as its priors."""
        gains = servo.gains
        if gains.ki:
            # WHY ilimit 0 (bam_ws 9de804493; Zach, 2026-11-13: PD + feed-forward only on a real arm, never an integrator): moteus holds the
            # integral to +-ilimit, so ilimit 0 switches it off whatever ki is; the board keeps its ki (a runner cannot change it per
            # command) and every controller PID tuna plays, the as-found one included, is PD
            gains = dataclasses.replace(gains, ilimit=0.0)
        return dataclasses.replace(servo, gains=gains, priors=model,
                                   can_id=servo.can_id if servo.can_id is not None else self.can_id)

    def fit(self, measured: Mapping[str, Any], values: Mapping[str, float], twin: Any) -> Tuned:
        """Tune kp and kd on a ServoSim of the twin the earlier steps fitted (``values``), under its feed-forward held fixed. Reads only
        ``twin.workers`` (the cap on every pool) from the handle; ``measured`` is empty (it plays no run)."""
        types = _pidtuna_module("pidtuna.types")
        servo_sim = _pidtuna_module("pidtuna.plants.servo_sim")
        analytic = _pidtuna_module("pidtuna.analytic")
        config = _pidtuna_module("pidtuna.config")
        model = _plant_model(types, values, self.instance)
        as_run = self._as_run()
        servo = self._board(types, model, as_run)
        static = float(values[f"{self.instance}.frictionloss_nm"])
        speed = values.get(f"{self.instance}.friction_stribeck_speed_rad_s")
        delay = values.get(f"{self.instance}.command_delay_s")
        template = servo_sim.Truth(inertia_kg_m2=model.inertia_kg_m2, viscous_nm_s_rad=0.0, coulomb_nm=0.0,
                                   torque_bandwidth_hz=TORQUE_BANDWIDTH_HZ, command_delay_s=float(delay) if delay is not None else 0.0)
        truth = servo_sim.from_model(servo, model, template=template).truth
        if speed is not None and float(speed) > 0.0 and static > model.coulomb_nm:
            # WHY the Stribeck terms the fit found (from_model keeps only the Coulomb): the twin PID tuna tunes on is the fitted twin, whole
            truth = dataclasses.replace(truth, static_nm=static, stribeck_speed_rad_s=float(speed))
        # WHY the twin's workers (Zach's cap while the rig is powered: at most 2 across every lane) and a pool closed when it is done
        plant = servo_sim.ServoSim(servo, truth, seed=0, workers=int(twin.workers))
        # WHY one repeat: the fitted twin carries no sensor noise, so a second repeat replays the same tapes
        objective = self.goal if self.goal is not None else types.Objective(repeats=1)
        feedforward = model.feedforward()   # the fitted model's: held fixed, so before and after differ only in kp and kd
        cap = min(servo.envelope.max_torque_nm, servo.torque_limit_nm)
        loop = analytic.LoopModel(torque_bandwidth_hz=TORQUE_BANDWIDTH_HZ, torque_cap_nm=cap,
                                  **({} if delay is None else {"delay_s": float(delay)}))
        seed, _info = analytic.analytic_controller(model, loop, objective)
        try:
            # WHY looked up at call time on the module: the tuner PID tuna exports now, and the one a test watches
            # WHY oracle=False: the plant's truth here is the fitted model itself; its brute-force ideal would cost a grid and say nothing
            # about the joint
            tuning = importlib.import_module("pidtuna.tune").tune(servo, plant, objective, feedforward=feedforward, seed=seed, oracle=False)
        finally:
            _close(servo_sim, plant)
        gains = tuning.gains[servo.name]
        verdict = tuning.verdicts.get(servo.name, {})
        wn, zeta = verdict.get("wn_tuned"), verdict.get("zeta_tuned")
        method = ("pidtuna.tune on the fitted twin (SIM tier) under its feed-forward held fixed"
                  + (f": wn {wn:.3g} rad/s, zeta {zeta:.2f}" if wn is not None and zeta is not None else "")
                  + (", the as-found kp and kd" if verdict.get("kept_as_found") else ""))
        found = {f"{self.instance}.kp_nm_rad": Estimate(float(gains.kp), None, method),
                 f"{self.instance}.kd_nm_s_rad": Estimate(float(gains.kd), None, method)}
        # WHY the document against the board as it RUNS, not the ilimit-0 copy PID tuna played (Zach, 2026-11-13: PD + feed-forward only):
        # pidtuna writes into board_set only what differs from servo.gains, so against the copy the change dropped ilimit 0 and a reviewer
        # applying board_set left the board's integrator on (ki with ilimit 0.5); against the board as it runs, board_set carries
        # servo.pid_position.ilimit 0 and board_before / as_found state what the board runs today
        proposal = {**config.gains_document(tuning, dataclasses.replace(servo, gains=as_run.gains)),
                    "feedforward": dataclasses.asdict(feedforward), "tier": "sim",
                    "before_scored_as": "the as-found kp and kd with the integrator off (ilimit 0): PID tuna plays PD + feed-forward only"}
        return Tuned(found, proposal)


__all__ = ["REQUIRES", "ROUTINE", "SETTINGS", "USES", "PidTune", "Tuned", "importable"]
