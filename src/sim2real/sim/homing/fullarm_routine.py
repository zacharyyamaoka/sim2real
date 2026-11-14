"""The full arm's homing ROUTINE (bam_fb_v2: five-bar J1 / J2 / C1, UR wrist W1-W3, crab claw), the rows it is compared with, and what each
row's touch does - sim only; the Sim to Real Agent runs the chosen row on the rack (bam_ws PEP 0047, its 2026-11-13 update).

Every row is a PEP 0002 ``HomingProcedure`` (``plan`` -> robot_msgs ``JointCommandSequence`` over the seven joints, ``observe`` ->
``HomingResult``), so the sequence the twin runs is the sequence the rack runs. What PEP 0047 landed (``fullarm_procedures.FullArmHome``)
stays as it was; the rows here differ from it in three ways:

1. **Where the wrist homes: READY, not the five-bar's home.** The five-bar's single_touch+gff ends with a walk to its home, the gravity
   bowl, where the full arm's claw sits ~101 mm into the belt (bam_rack_twin full_arm; the twin with the belt refuses that pose). Phase 0
   here is the same single_touch+gff with its last walk retargeted to READY (``SingleTouchReady``: the claw over the bin's drop, 215 mm
   over the belt) - the pose the rack walks to anyway (walk_ready) - and the wrist homes there, clear of the belt and the bin on every
   sweep. The routine ends holding READY with the claw plumb (TD4: W1 = L2's angle, W2 +90, W3 0).
2. **How a wrist joint touches its stop** (``touch``):
   ``single``         one seek at the recipe's 36 deg/s and 1 N.m, the zero at its stall (PEP 0047's)
   ``multi``          3D-printer homing: a FAST locate (``seek_speed_deg_s``), back off ``backoff_deg``, then ``touches - 1`` SLOW re-touches
                      (``slow_speed_deg_s``) at the same cap; the zero is the mean of the slow touches. The locate is never a reference -
                      it only finds the stop quickly - and the touches must agree: slow touches within ``consistency_tol_deg`` of each
                      other, the locate within ``locate_tol_deg`` of them, else the routine refuses (``HomingRefused``).
   ``press_reverse``  both stops at half and full cap, every joint, every home (robot_models ``fit(identify="B2")``): the gap and the mesh
                      compliance identified on each run, no stored table; the measured stop span must sit within ``span_tol_deg`` of the
                      CAD's plus a plausible gap, else it refuses (a stall on an obstacle on either side breaks the span).
3. **Every defining stall passes the rotor-phase witness** (PEP 0047's): a board boots reading its output modulo one rotor turn, so on its
   true stop it must read ``stop + phase`` mod 36 deg - including the locate of a multi touch. ``witness_tol_deg`` is PEP 0047's 2 deg by
   default; the rack runs 0.5 deg on a trusted home's own stall (``rotor_phase_from_homed``, ``rack_plan``), which the grid showed refuses
   every near-stop stall the 2 deg one lets through and no true stop (routine_check.tight_witness).

The rows (``ROWS``) are the ruler's list (routine_ruler's docstring); ``make_row(name)`` builds one. **The recommended routine**
(``RECOMMENDED``): V1's order with the stored table and the 0.5 deg witness, taking park_first's path when the witness refuses W1's
first stall - the two orders command the same up to that stall, so the grid scores it exactly from their runs (routine_check.FALLBACK)
and ``rack_plan_fallback`` hands the rack both paths and the branch rule.

Every angle shown is in degrees; the sequences are SI (rad, rad/s, N.m).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from robot_models.homing.fit import fit
from robot_models.homing.protocols import Phase
from robot_models.homing.types import BacklashModel, BacklashTable, HomingResult, JointBacklash
from robot_msgs.control import Elapsed, JointCommand, JointCommandSequence

from . import procedures as five
from .fullarm_plant import C1, CLAW, FIVEBAR, J1, J2, JOINTS, ROLE, W1, W2, W3, WRIST, ArmPrior
from .fullarm_procedures import (
    CLAW_CAP_NM,
    CLAW_HOLD_CAP_NM,
    CLAW_SEEK_SPEED,
    DEFAULT_COMP,
    PARK_BACK_RAD,
    PARK_BACK_SPEED,
    PARK_SEEK_SIDE,
    WITNESS_TOL_RAD,
    WRIST_CAP_NM,
    WRIST_HOLD_CAP_NM,
    WRIST_MOVE_SPEED,
    FullArmHome,
    _by,
    _hold,
    _reached,
    _recapture,
    _seek,
    _stall,
    _to,
    arm_comp,
    full_step,
    project,
    step_readings,
    witness_error,
    wrist_seek_distance,
)
from .procedures import HomingRefused
from .routine_ruler import FIVEBAR_LEVELS

TAU = 2.0 * math.pi
# WHY these offsets (bam_fb_test_rig.gravity.CraigMap on the bam_fb_v2 twin; tests/test_homing_routine.py holds them equal): Craig = URDF +
# offset - the CAD's stops (bundle stops.json) read J2 Craig in [-0.03, 215.0], C1 in [24.77, 335.23]
CRAIG_OFFSET_DEG = {J2: 90.0, C1: 137.45861811322055}
READY_CRAIG_DEG = FIVEBAR_LEVELS["READY"]
# TD4 at READY (bam_rack_twin full_arm.wrist_td4: W1 = L2's angle j2 + j3, W2 +90, W3 0; READY's j3 is -64.079 deg): the claw plumb
READY_TD4_WRIST_DEG = (1.167, 90.0, 0.0)
RECIPE_SEEK_DEG_S = math.degrees(0.1 * TAU)  # 36 deg/s: the recipe's max_vel 0.1 rev/s
MULTI_LOCATE_DEG_S = 60.0  # 0.7 x the wrist's 86 deg/s speed ceiling (the ruler's 0.8 margin, with room for the stall's overshoot)
MULTI_RETOUCH_DEG_S = 9.0  # a quarter of the recipe
MULTI_BACKOFF_DEG = 4.0
FAST_MOVE_DEG_S = 60.0  # the fast rows' moves (to 0, to TD4, across, parking back): as fast as their seeks
PARK_UNLOAD_DEG = 5.0  # the fast park-back's slow first part: the forearm / stop contact unloads (PARK_BACK_SPEED's WHY), then full speed
CONSISTENCY_TOL_DEG = 0.25
LOCATE_TOL_DEG = 1.5
SPAN_TOL_DEG = 1.0
GAP_MAX_DEG = 1.0  # the most backlash a GIM4305-10 could plausibly carry (datasheet class: 12-18 arcmin): a "gap" past it is not a gap
TOUCHES = ("single", "multi", "press_reverse")
WRIST_POSES = ("ready", "bowl")


def craig_to_cad(joint: str, craig_deg: float) -> float:
    """A five-bar drive's Craig angle (deg) in the procedures' CAD / URDF frame (rad), C1 wrapped onto (-180, 180]."""
    value = math.radians(craig_deg - CRAIG_OFFSET_DEG[joint])
    return math.remainder(value, TAU) if joint == C1 else value


def ready_cad() -> dict:
    return {J2: craig_to_cad(J2, READY_CRAIG_DEG[0]), C1: craig_to_cad(C1, READY_CRAIG_DEG[1])}


# ------------------------------------------------------------------------------------------------------------------------ phase 0


@dataclass
class SingleTouchReady(five.SingleTouch):
    """sim2real ``procedures.SingleTouch`` (the five-bar's real default, inside RealRow's ``single_touch_ready+gff``) with its last walk
    ending at READY instead of tview's home (module docstring, 1). Everything before that walk - J1 held, J2's seek with C1 unpowered,
    C1's with J2 pushing, the defines - is SingleTouch's own."""

    name: str = "single_touch_ready"

    def plan(self, prior, so_far):
        sequence = super().plan(prior, so_far)
        if sequence is None:
            return None
        target = ready_cad()
        steps = list(sequence.steps)
        last = steps[-1]
        if last.name != "J2 + C1 home":
            raise RuntimeError(f"SingleTouch's last step is {last.name!r}, not the walk home this retargets")
        cad = {j: prior.stops.q_rad(j, +1) for j in five.DRIVES}
        steps[-1] = five._diagonal({J2: target[J2], C1: target[C1]}, cad, "J2 + C1 home (to READY)", others=(J1,))
        return replace(sequence, steps=tuple(steps), name=sequence.name.replace("single touch", "single touch to READY"))


five.PROCEDURES.setdefault(SingleTouchReady().name, SingleTouchReady)


def _c1seek_ready_class():
    """c1_seek's SingleTouchC1Seek (C1 seeking beside J2 in J2's first seek, the crank never let go once powered) walking to READY."""
    from .c1_seek import VARIANTS, SingleTouchC1Seek  # noqa: PLC0415

    @dataclass
    class SingleTouchC1SeekReady(SingleTouchC1Seek):
        name: str = "single_touch_c1seek_ready"

        def plan(self, prior, so_far):
            sequence = super().plan(prior, so_far)
            if sequence is None:
                return None
            steps = list(sequence.steps)
            if steps[-1].name != "J2 + C1 home":
                raise RuntimeError(f"the last step is {steps[-1].name!r}, not the walk home this retargets")
            target = ready_cad()
            cad = {j: prior.stops.q_rad(j, +1) for j in five.DRIVES}
            steps[-1] = five._diagonal({J2: target[J2], C1: target[C1]}, cad, "J2 + C1 home (to READY)", others=(J1,))
            return replace(sequence, steps=tuple(steps), name=sequence.name + ", to READY")

    VARIANTS.setdefault(SingleTouchC1SeekReady().name, SingleTouchC1SeekReady)
    return SingleTouchC1SeekReady


_c1seek_ready_class()


def fivebar_hold_at(target: dict, comp: str = DEFAULT_COMP, ff_scale: float = 1.0) -> dict:
    """The five-bar held at ``target`` (CAD rad) on the comp's gravity there, J1 held: what phase 1 sends J1 / J2 / C1 every step."""
    gravity = arm_comp(comp, ff_scale).torque({J1: 0.0, J2: target[J2], C1: target[C1]}) or {J2: 0.0, C1: 0.0}
    return {J1: _hold(J1), J2: JointCommand.to(J2, target[J2], speed=0.1 * TAU, max_effort=10.0, feedforward_effort=gravity[J2]),
            C1: JointCommand.to(C1, target[C1], speed=0.1 * TAU, max_effort=7.0, feedforward_effort=gravity[C1])}


# ------------------------------------------------------------------------------------------------------------------------ the routine


@dataclass
class FullArmRoutine(FullArmHome):
    """``FullArmHome`` (PEP 0047: phase 0 the five-bar with the wrist braked, phase 1 the claw then the wrist one joint at a time in
    ``order``) with the wrist homed at ``wrist_pose`` and each wrist joint touched as ``touch`` says (module docstring)."""

    wrist_pose: str = "ready"
    touch: str = "single"
    touches: int = 2
    seek_speed_deg_s: float = RECIPE_SEEK_DEG_S
    move_speed_deg_s: float = RECIPE_SEEK_DEG_S
    slow_speed_deg_s: float = MULTI_RETOUCH_DEG_S
    backoff_deg: float = MULTI_BACKOFF_DEG
    consistency_tol_deg: float = CONSISTENCY_TOL_DEG
    locate_tol_deg: float = LOCATE_TOL_DEG
    span_tol_deg: float = SPAN_TOL_DEG
    end: str = "td4"
    use_table: bool = True
    # WHY a knob (the routine's grid, 2026-11-13): at PEP 0047's 2 deg the witness passed W2 stalling 1.24 deg short of its stop, the gripper
    # plate on the forearm (W1 parked at +33, W3 at -119): a silent wrong. Calibrated on a trusted home's own stall (the rack's
    # rotor_phase_from_homed is), the same stop reads the same to ~0.1 deg (the rack's W1 / W2 / claw over three homes), so 0.5 deg holds.
    witness_tol_deg: float = math.degrees(WITNESS_TOL_RAD)
    evidence_plan: list = field(default_factory=list)

    def __post_init__(self):
        if self.wrist_pose not in WRIST_POSES:
            raise ValueError(f"wrist_pose must be one of {WRIST_POSES}, not {self.wrist_pose!r}")
        if self.touch not in TOUCHES:
            raise ValueError(f"touch must be one of {TOUCHES}, not {self.touch!r}")
        if self.touch == "multi" and self.touches < 2:
            raise ValueError("a multi touch needs a locate and at least one re-touch (touches >= 2)")
        if self.fivebar_name is None:
            self.fivebar_name = "single_touch_ready+gff" if self.wrist_pose == "ready" else "single_touch+gff"
        if not self.name:
            self.name = self.default_name()
        super().__post_init__()

    def default_name(self) -> str:
        touch = {"single": "single" if abs(self.seek_speed_deg_s - RECIPE_SEEK_DEG_S) < 1e-9 else f"single {self.seek_speed_deg_s:g} deg/s",
                 "multi": f"multi x{self.touches}", "press_reverse": "press_reverse"}[self.touch]
        return f"{self.order}{'+witness' if self.witness else ''} · {touch} · wrist at {self.wrist_pose}"

    @property
    def _seek_speed(self) -> float:
        return math.radians(self.seek_speed_deg_s)

    @property
    def _move_speed(self) -> float:
        return math.radians(self.move_speed_deg_s)

    @property
    def _fast(self) -> bool:
        return self.move_speed_deg_s > RECIPE_SEEK_DEG_S + 1e-9

    # -- plan ------------------------------------------------------------------------------------------------------------------------

    def plan(self, prior: ArmPrior, so_far: Sequence[Phase]):
        if self.wrist_only or len(so_far) != 1:
            return super().plan(prior, so_far)
        target = ready_cad() if self.wrist_pose == "ready" else {j: v for j, v in five.home_cad(prior).items() if j in (J2, C1)}
        return self._phase1(prior, fivebar_holds=fivebar_hold_at(target, self.comp, self.ff_scale))

    def _phase1(self, prior: ArmPrior, fivebar_holds: dict | None = None) -> JointCommandSequence:
        self.evidence_plan = []
        holds = {**fivebar_holds, **{j: _hold(j) for j in (*WRIST, CLAW)}}
        side = {j: int(prior.seek_side[j]) for j in (*WRIST, CLAW)}
        steps = [full_step("phase 1: everything holds", [], [Elapsed(duration=0.3)], holds=holds, timeout=1.0)]
        claw_stop = prior.stops.q_rad(CLAW, side[CLAW])
        # the claw first (PEP 0047, 3): its zero is the closed fingers; seek side and stop from the prior (Zach re-mounts it reversed)
        steps.append(full_step("claw closes", [_seek(CLAW, side[CLAW], CLAW_CAP_NM)], [_stall(CLAW, CLAW_CAP_NM)], holds=holds,
                               define={CLAW: claw_stop}))
        self.evidence_plan.append(("claw closes", CLAW, side[CLAW], "define"))
        claw_rest = claw_stop - side[CLAW] * math.radians(5.0)
        steps.append(full_step("claw eases off", [_to(CLAW, claw_rest, CLAW_HOLD_CAP_NM, CLAW_SEEK_SPEED)], _reached(CLAW, CLAW_HOLD_CAP_NM),
                               holds=holds))
        holds = {**holds, CLAW: _to(CLAW, claw_rest, CLAW_HOLD_CAP_NM, CLAW_SEEK_SPEED)}
        plan = [(W1, True), (W2, True), (W3, True)] if self.order == "zach_v1" else [(W1, False), (W2, True), (W1, True), (W3, True)]
        for joint, defines in plan:
            role = ROLE[joint]
            if not defines:
                # park_first's parking touch (PEP 0047, 4): never a reference; it ends on the stop or on the forearm, 135 deg back is clear
                steps.append(full_step(f"{role} park touch", [self._seek_cmd(joint, PARK_SEEK_SIDE, self._seek_speed)],
                                       [_stall(joint, WRIST_CAP_NM, self._kp)], holds=holds))
                recaptured = [_recapture(j) for j in WRIST if j != joint]
                if self._fast:
                    # WHY two parts: the slow start is what unloads the contact (PARK_BACK_SPEED's WHY); the other 130 deg need not crawl
                    unload = math.radians(PARK_UNLOAD_DEG)
                    steps.append(full_step(f"{role} unloads its park", [_by(joint, -PARK_SEEK_SIDE * unload, WRIST_HOLD_CAP_NM, PARK_BACK_SPEED),
                                                                       *recaptured], _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
                    steps.append(full_step(f"{role} parks back 135 deg", [_by(joint, -PARK_SEEK_SIDE * (PARK_BACK_RAD - unload),
                                                                            WRIST_HOLD_CAP_NM, self._move_speed)],
                                           _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
                else:
                    steps.append(full_step(f"{role} parks back 135 deg", [_by(joint, -PARK_SEEK_SIDE * PARK_BACK_RAD, WRIST_HOLD_CAP_NM,
                                                                            PARK_BACK_SPEED), *recaptured],
                                           _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
                holds = {**holds, joint: _hold(joint)}
                continue
            steps += self._wrist_touch(prior, joint, side[joint], holds)
            steps.append(full_step(f"{role} to 0", [_to(joint, 0.0, WRIST_HOLD_CAP_NM, self._move_speed)], _reached(joint, WRIST_HOLD_CAP_NM),
                                   holds=holds))
            holds = {**holds, joint: _to(joint, 0.0, WRIST_HOLD_CAP_NM)}
        if self.end == "td4":
            # the routine ends where the full arm waits: READY with the claw plumb (W2 +90 first: |W2| <= 95 is the CAD's proof)
            w1, w2, w3 = (math.radians(v) for v in READY_TD4_WRIST_DEG)
            steps.append(full_step("W2 to TD4", [_to(W2, w2, WRIST_HOLD_CAP_NM, self._move_speed)], _reached(W2, WRIST_HOLD_CAP_NM),
                                   holds=holds))
            holds = {**holds, W2: _to(W2, w2, WRIST_HOLD_CAP_NM)}
            steps.append(full_step("W1 to TD4", [_to(W1, w1, WRIST_HOLD_CAP_NM, self._move_speed)], _reached(W1, WRIST_HOLD_CAP_NM),
                                   holds=holds))
            if abs(w3) > 0.0:
                steps.append(full_step("W3 to TD4", [_to(W3, w3, WRIST_HOLD_CAP_NM)], _reached(W3, WRIST_HOLD_CAP_NM),
                                       holds={**holds, W1: _to(W1, w1, WRIST_HOLD_CAP_NM)}))
        self.notes["phase1_parked"] = self.order == "park_first"
        return JointCommandSequence(joint_names=JOINTS, steps=tuple(steps), name=f"claw + wrist ({self.name})")

    def _seek_cmd(self, joint: str, side: int, speed: float, cap: float = WRIST_CAP_NM) -> JointCommand:
        return JointCommand.move_by(joint, side * wrist_seek_distance(self._kp), speed=speed, max_effort=cap)

    def _wrist_touch(self, prior: ArmPrior, joint: str, side: int, holds: dict) -> list:
        role = ROLE[joint]
        near = prior.stops.q_rad(joint, side)
        if self.touch == "single":
            self.evidence_plan.append((f"{role} seeks", joint, side, "define"))
            return [full_step(f"{role} seeks", [self._seek_cmd(joint, side, self._seek_speed)], [_stall(joint, WRIST_CAP_NM, self._kp)],
                              holds=holds, define={joint: near})]
        if self.touch == "multi":
            back = math.radians(self.backoff_deg)
            steps = [full_step(f"{role} locates", [self._seek_cmd(joint, side, self._seek_speed)], [_stall(joint, WRIST_CAP_NM, self._kp)],
                               holds=holds)]
            self.evidence_plan.append((f"{role} locates", joint, side, "locate"))
            for k in range(1, self.touches):
                steps.append(full_step(f"{role} backs off {k}", [_by(joint, -side * back, WRIST_HOLD_CAP_NM, self._move_speed)],
                                       _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
                last = k == self.touches - 1
                # WHY the seek's own long travel at the slow speed: a re-touch that runs out of setpoint before its stall builds is a
                # timeout, not a home (fullarm_procedures.wrist_seek_distance's WHY)
                steps.append(full_step(f"{role} re-touch {k}", [self._seek_cmd(joint, side, math.radians(self.slow_speed_deg_s))],
                                       [_stall(joint, WRIST_CAP_NM, self._kp)], holds=holds, define={joint: near} if last else None))
                self.evidence_plan.append((f"{role} re-touch {k}", joint, side, "define"))
            return steps
        # press_reverse: both stops at half and full cap (fullarm_procedures.FullArmHome._touch's identify branch)
        far = prior.stops.q_rad(joint, -side)
        ease = math.radians(3.0)
        steps = []
        for tag, s in (("near", side), ("far", -side)):
            if tag == "far":
                steps.append(full_step(f"{role} walks across", [_to(joint, far + side * ease, WRIST_HOLD_CAP_NM, self._move_speed)],
                                       _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
            steps += [full_step(f"{role} {tag} seek", [self._seek_cmd(joint, s, self._seek_speed, 0.5 * WRIST_CAP_NM)],
                                [_stall(joint, 0.5 * WRIST_CAP_NM, self._kp)], holds=holds),
                      full_step(f"{role} {tag} press half", [self._seek_cmd(joint, s, self._seek_speed, 0.5 * WRIST_CAP_NM)],
                                [Elapsed(duration=0.8)], holds=holds),
                      full_step(f"{role} {tag} press full", [self._seek_cmd(joint, s, self._seek_speed)], [Elapsed(duration=0.8)],
                                holds=holds, define={joint: near} if tag == "near" else None)]
            self.evidence_plan += [(f"{role} {tag} press half", joint, s, "press"), (f"{role} {tag} press full", joint, s, "press")]
        return steps

    # -- observe ---------------------------------------------------------------------------------------------------------------------

    def observe(self, prior: ArmPrior, phases: Sequence[Phase]) -> HomingResult:
        if self.wrist_only:
            raise NotImplementedError("FullArmRoutine runs both phases (the wrist-only replay is FullArmHome's)")
        self.references = []
        five_prior = prior
        if not self.fivebar_table and prior.table is not None:
            kept = tuple(e for e in prior.table.entries if e.joint not in FIVEBAR)
            five_prior = replace(prior, table=BacklashTable(kept) if kept else None)
        fivebar = self.fivebar.observe(five_prior, [project(phases[0], FIVEBAR)])
        self.references = list(self.fivebar.references)
        ends = step_readings(phases[1])
        evidence, locates = [], {}
        for step, joint, side, use in self.evidence_plan:
            reading = ends[step]  # a KeyError is the harness's "no reading for step": the step never ended
            if use == "locate":
                locates[joint] = (side, reading.raw[joint])
                continue
            evidence.append(self._evidence(1, reading, joint, side))
        self._witness(prior, evidence, locates)
        if self.touch == "multi":
            self._consistency(evidence, locates)
        if self.touch == "press_reverse":
            arm = fit(evidence, prior.stops, identify="B2", rung="mujoco")
            entries = [e for e in arm.backlash.entries if e.joint != CLAW]
            entries.append(JointBacklash(CLAW, BacklashModel("B0"), False, False, "one closed stop: no gap is observable"))
            table = BacklashTable(tuple(entries))
            self._span(prior, evidence, table)
            arm = fit(evidence, prior.stops, table=table, rung="mujoco")
        else:
            stored = prior.table if self.use_table else None
            table = BacklashTable(tuple((stored.get(j) if stored is not None and stored.get(j) is not None else
                                         JointBacklash(j, BacklashModel("B0"), source="no stored table")) for j in (*WRIST, CLAW)))
            arm = fit(evidence, prior.stops, table=table, rung="mujoco")
            table = BacklashTable(tuple(JointBacklash(e.joint, e.model, False, False, e.source) for e in table.entries))
        spread = {ROLE[z.joint]: round(math.degrees(z.spread_rad), 4) for z in arm.zeros if z.n_evidence > 1}
        if spread:
            self.notes["touch_spread_deg"] = spread
        zeros = tuple(fivebar.zeros) + tuple(arm.zeros)
        backlash = BacklashTable(tuple(e for e in fivebar.backlash.entries if e.joint in FIVEBAR) + tuple(table.entries))
        return HomingResult(zeros, backlash, prior.stops, tuple(fivebar.evidence) + tuple(evidence), "mujoco")

    def _witness(self, prior: ArmPrior, evidence: list, locates: dict) -> None:
        readings = [(s.joint, s.side, s.motor_raw_rad) for s in evidence] + [(j, side, raw) for j, (side, raw) in locates.items()]
        witness = {}
        for joint, side, raw in readings:
            error = witness_error(prior, joint, side, raw)
            if error is not None:
                witness.setdefault(ROLE[joint], []).append(round(math.degrees(error), 3))
        self.notes["witness_deg"] = witness
        if self.witness:
            bad = {role: errors for role, errors in witness.items() if any(abs(e) > self.witness_tol_deg for e in errors)}
            if bad:
                self.notes["witness_refused"] = bad
                raise HomingRefused(f"rotor-phase witness: {bad} deg off the stop's phase (tolerance {self.witness_tol_deg:.1f})")

    def _consistency(self, evidence: list, locates: dict) -> None:
        bad = {}
        for joint, (side, locate) in locates.items():
            touches = [s.motor_raw_rad for s in evidence if s.joint == joint]
            spread = math.degrees(max(touches) - min(touches)) if len(touches) > 1 else 0.0
            off = math.degrees(locate - sum(touches) / len(touches))
            if spread > self.consistency_tol_deg or abs(off) > self.locate_tol_deg:
                bad[ROLE[joint]] = {"retouch_spread_deg": round(spread, 3), "locate_minus_retouch_deg": round(off, 3)}
            self.notes.setdefault("locate_minus_retouch_deg", {})[ROLE[joint]] = round(off, 4)
        if bad:
            self.notes["consistency_refused"] = bad
            raise HomingRefused(f"touch consistency: {bad}")

    def _span(self, prior: ArmPrior, evidence: list, table: BacklashTable) -> None:
        """press_reverse's span witness: the two stops' compliance-free levels must be the CAD's span apart plus a plausible gap."""
        out, bad = {}, {}
        for joint in WRIST:
            entry = table.get(joint)
            compliance = entry.model.compliance_rad_per_nm if entry is not None else 0.0
            levels = {}
            for side in (-1, +1):
                items = [s for s in evidence if s.joint == joint and s.side == side]
                if items:
                    levels[side] = sum(s.motor_raw_rad - side * compliance * s.torque_nm for s in items) / len(items)
            if len(levels) < 2:
                continue
            gap = math.degrees(levels[+1] - levels[-1] - prior.stops.span_rad(joint))
            out[ROLE[joint]] = round(gap, 4)
            if not -self.span_tol_deg <= gap <= GAP_MAX_DEG + self.span_tol_deg:
                bad[ROLE[joint]] = round(gap, 3)
        self.notes["span_error_deg"] = out
        if bad:
            raise HomingRefused(f"span witness: measured stop span minus CAD {bad} deg (a gap is 0-{GAP_MAX_DEG:g})")


# ------------------------------------------------------------------------------------------------------------------------ the rows

# The ruler's rows (routine_ruler docstring). WHY each, in one line:
ROWS = {
    # Zach's V1 wrist order as wrist_home_v1 runs it (W1 +1, W2 -1, W3 +1; no witness), homed at READY - where the rack has to do it
    "zach_v1 @ READY": {"order": "zach_v1", "witness": False, "touch": "single"},
    # PEP 0047 as landed: park_first + witness, the wrist homed at the five-bar's home (the gravity bowl) - through the belt with the claw on
    "PEP 0047 (wrist at the five-bar's home)": {"class": "FullArmHome", "order": "park_first"},
    "park_first+witness @ READY": {"order": "park_first", "touch": "single"},
    # speed alone: every wrist seek and move at 60 deg/s, one touch - what going fast costs without a slow re-touch
    "fast single @ READY": {"order": "park_first", "touch": "single", "seek_speed_deg_s": MULTI_LOCATE_DEG_S,
                            "move_speed_deg_s": FAST_MOVE_DEG_S},
    # Zach's 3D-printer homing: the fast row's locate, back off, slow re-touch(es); the zero is the slow touches'
    "multi x2 (3D-printer) @ READY": {"order": "park_first", "touch": "multi", "touches": 2, "seek_speed_deg_s": MULTI_LOCATE_DEG_S,
                                      "move_speed_deg_s": FAST_MOVE_DEG_S},
    "multi x3 (3D-printer) @ READY": {"order": "park_first", "touch": "multi", "touches": 3, "seek_speed_deg_s": MULTI_LOCATE_DEG_S,
                                      "move_speed_deg_s": FAST_MOVE_DEG_S},
    "press_reverse (backlash every home) @ READY": {"order": "park_first", "touch": "press_reverse"},
    # option B: one touch, the wrist's gaps and compliance from a stored identify_backlash table (``needs_table``)
    "park_first+witness+table @ READY": {"order": "park_first", "touch": "single", "needs_table": True},
    # added after READY's nominal map (ruler amendment 2): V1's order with the stored table - V1 covered the most of READY, and the table
    # is what a single touch needs on a geared joint
    "zach_v1+table @ READY": {"order": "zach_v1", "witness": False, "touch": "single", "needs_table": True},
}


# ------------------------------------------------------------------------------------------------------------------------ on the rack


def rotor_phase_from_homed(path) -> dict:
    """Each wrist / claw board's sub-turn phase (deg) from a bam-homed/1 file (the rack's full_arm/homed/latest.json): the witness's
    calibration. A board boots reading ``wrap(q + phase)`` and the file's ``zero_board_rad`` is its reading at joint 0, so the phase is
    that reading wrapped to one rotor turn - valid across power cycles while the gear train and the encoder calibration stay as they were.

    Take it only from a home you trust (camera-checked): a zero assigned on an obstacle calibrates the witness to that obstacle. The rack's
    trusted one (the Sim to Real Agent, 2026-11-13: Zach from video, the ArUco CAD check within 0.5 deg at W3 -90 / +120 / +150) is
    homed_2026-11-13T182448Z.json (11:24): W3's + stop at +2.78 deg mod 36. 10:24's W3 stall (+11.02 mod 36) stalled early.

    WHY no expected-travel check anywhere in this routine (Zach, 2026-11-13: "you don't actually know how far it should move before
    seeking"): a seek that ends short because the joint started near its stop is a valid home; only the rotor phase (and press_reverse's
    stop-to-stop span) can refuse a stall."""
    import json  # noqa: PLC0415

    from .fullarm_plant import TURN_RAD, wrap_turn  # noqa: PLC0415

    document = json.loads(Path(path).read_text())
    if document.get("schema") != "bam-homed/1":
        raise ValueError(f"{path} is not a bam-homed/1 file")
    out = {}
    for joint, entry in document["joints"].items():
        if joint not in TURN_RAD or not entry.get("homed"):
            continue
        if int(entry.get("sign", 1)) != 1:
            raise ValueError(f"{joint}: sign {entry.get('sign')} - the phase is derived for sign +1 boards only")
        out[joint] = math.degrees(wrap_turn(float(entry["zero_board_rad"]), TURN_RAD[joint]))
    return out


# Phase-0 variants tried on the grid's five-bar trips (routine_check's probe, not the ruler's rows): J2's first seek slower, and C1 seeking
# beside J2 (c1_seek) so the crank is never limp while L1 lifts the arm off the belt
EXPERIMENTAL_ROWS = {
    "park_first+witness @ READY, J2 first seek 0.025": {"order": "park_first", "touch": "single", "j2_first_seek_rev_s": 0.025},
    "park_first+witness @ READY, C1 seeks beside J2": {"order": "park_first", "touch": "single",
                                                       "fivebar_name": "single_touch_c1seek_ready+gff"},
    "park_first+witness @ READY, C1 beside J2, 0.025": {"order": "park_first", "touch": "single",
                                                        "fivebar_name": "single_touch_c1seek_ready+gff", "j2_first_seek_rev_s": 0.025},
}


def make_row(name: str, **overrides):
    """The procedure for row ``name`` (``ROWS``, or ``EXPERIMENTAL_ROWS``), ``overrides`` replacing its spec (tuning)."""
    spec = {**(ROWS.get(name) or EXPERIMENTAL_ROWS[name]), **overrides}
    spec.pop("needs_table", None)
    cls = spec.pop("class", "FullArmRoutine")
    if cls == "FullArmHome":
        return FullArmHome(name=name, **spec)
    return FullArmRoutine(name=name, **spec)


# ------------------------------------------------------------------------------------------------------------------------ the rack's plan

RACK_HOMED_TRUSTED = Path("/archive/datasets/bam_rig/full_arm/homed/homed_2026-11-13T182448Z.json")  # the ArUco-checked 11:24 home
RACK_WITNESS_TOL_DEG = 0.5


def rack_plan(row: str, homed: Path = RACK_HOMED_TRUSTED, *, witness_tol_deg: float = RACK_WITNESS_TOL_DEG) -> dict:
    """What the Sim to Real Agent runs on the rack for ``row``, as JSON: phase 1's robot_msgs JointCommandSequence (the claw and the wrist at
    READY; phase 0, the five-bar, is the rack's own staged home), the witness's calibration and tolerance, and which step's stall defines
    which joint. Every angle in the sequence is SI (rad), in the URDF joint frame.

    The witness is checked ONLINE: after each step that defines a joint, read that joint's power-up reading at the step's end and refuse
    (hold everything, end the run) when ``witness_error`` is past the tolerance - before the zero moves anything."""
    from .fullarm_plant import ROLE, arm_prior  # noqa: PLC0415

    procedure = make_row(row)
    procedure.witness, procedure.witness_tol_deg = True, witness_tol_deg  # the rack always runs the witness, whichever order
    phases = rotor_phase_from_homed(homed)
    prior = arm_prior(rotor_phase_deg=phases)
    sequence = procedure.plan(prior, [None])
    stops = {ROLE[j]: {"upper_deg": math.degrees(prior.stops.q_rad(j, +1)), "lower_deg": math.degrees(prior.stops.q_rad(j, -1)),
                       "seek_side": int(prior.seek_side[j])} for j in (*WRIST, CLAW)}
    return {"schema": "sim2real.homing_rack_plan/1", "row": row, "phase": "1 (claw + wrist at READY)",
            "sequence": sequence.to_dict(), "evidence_plan": [{"step": step, "joint": joint, "role": ROLE[joint], "side": side, "use": use}
                                                              for step, joint, side, use in procedure.evidence_plan],
            "witness": {"tolerance_deg": witness_tol_deg, "rotor_phase_deg": {ROLE[j]: v for j, v in phases.items()},
                        "calibrated_from": str(homed), "turn_deg": 36.0,
                        "rule": "error = wrap36(reading - stop - phase); refuse when |error| > tolerance, checked as each defining step ends"},
            "stops": stops, "ready_craig_deg": list(READY_CRAIG_DEG), "td4_wrist_deg": list(READY_TD4_WRIST_DEG),
            "table": "apply the stored identify_backlash table (wrist B2 rows) in observe; none = B0 (zeros 0.46-0.50 deg off on a geared joint)"}


RECOMMENDED = "V1+table, park_first on a W1 refusal @ READY"


def rack_plan_fallback(homed: Path = RACK_HOMED_TRUSTED, *, witness_tol_deg: float = RACK_WITNESS_TOL_DEG) -> dict:
    """The recommended routine for the rack: V1's order, and park_first's path when the witness refuses W1's first stall (routine_check's
    FALLBACK: the two share every step up to and including that seek). Both continuations, the branch rule, the witness, the stops."""
    v1 = rack_plan("zach_v1+table @ READY", homed, witness_tol_deg=witness_tol_deg)
    park = rack_plan("park_first+witness+table @ READY", homed, witness_tol_deg=witness_tol_deg)
    shared = [s["name"] for s in v1["sequence"]["steps"]][:4]
    if shared[-1] != "W1 seeks" or [s["name"] for s in park["sequence"]["steps"]][3] != "W1 park touch":
        raise RuntimeError("V1's W1 seek and park_first's park touch are no longer the fourth step of their sequences")
    return {**v1, "row": RECOMMENDED, "sequence_park_first": park["sequence"], "evidence_plan_park_first": park["evidence_plan"],
            "branch": {"after_step": "W1 seeks (V1) == W1 park touch (park_first): the same command and stall",
                       "rule": "witness W1's stall as that step ends: within tolerance -> carry on with V1's sequence ('W1 to 0', W2, W3, TD4); "
                               "past it -> carry on with park_first's from 'W1 parks back 135 deg' (W2, W1 again, W3, TD4) and do NOT assign "
                               "the refused stall",
                       "shared_steps": shared}}


def main(argv=None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="the rack's homing plan for one routine row (JSON)")
    parser.add_argument("--row", default=RECOMMENDED, help=f"a row of ROWS, or {RECOMMENDED!r} (the default: both paths and the branch)")
    parser.add_argument("--homed", type=Path, default=RACK_HOMED_TRUSTED)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = rack_plan_fallback(args.homed) if args.row == RECOMMENDED else rack_plan(args.row, args.homed)
    args.out.write_text(json.dumps(plan, indent=1, default=str))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CRAIG_OFFSET_DEG", "READY_CRAIG_DEG", "READY_TD4_WRIST_DEG", "ROWS", "FullArmRoutine", "SingleTouchReady", "craig_to_cad",
           "fivebar_hold_at", "make_row", "rack_plan", "rack_plan_fallback", "ready_cad", "rotor_phase_from_homed", "RECOMMENDED"]
