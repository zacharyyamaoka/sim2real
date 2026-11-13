"""Full-arm homing procedures for bam_fb_v2 (five-bar + UR wrist + crab claw) as robot_msgs JointCommandSequences - PEP 0047 (bam_ws).

Every procedure here is a PEP 0002 ``HomingProcedure`` (``plan`` -> sequence, ``observe`` -> ``HomingResult``) over the seven joints of
``fullarm_plant.JOINTS``, so the SAME sequence runs on the MuJoCo twin (``fullarm_plant``), and - through the Sim to Real Agent - on the
rack. Two phases:

* **phase 0, the five-bar**: ``real_bench.RealRow("single_touch+gff")`` - the exact sequence ``fivebar_homed --homing-procedure
  single_touch+gff`` sends (J1 held and never homed, sag_proof, J2 kept powered, the home button's gravity feed-forward), the default the
  real arm passed 4/4 - with the wrist and the claw HELD where they are on every step (a limp wrist swings into the forearm at up to 1100
  deg/s while L2 moves: fullarm_home's wrist sweep, 2026-11-13).
* **phase 1, the claw and the wrist, ONE JOINT AT A TIME** (self_collision_wrist.json: homing wrist 1 and 2 together is not safe), the
  five-bar held at its home with its gravity feed-forward. The claw closes first: its zero is the closed fingers, and closed it cannot reach
  the finger / wrist-plate region (|claw| > 66.81 deg) the wrist sweeps could otherwise enter.

Wrist orders (``WRIST_ORDERS``):

``zach_v1``     Zach's choreography (bam_homing examples/bam_fb_homing.py) as wrist_home_v1 runs it on the rack: W1 +1, W2 -1, W3 +1, each
                seek -> assign the CAD stop -> move to 0. One joint at a time, but from an unknown start W1's sweep to +169.85 deg crosses
                the gripper/forearm region whenever |W2| > 104.91 deg - and a stall on the forearm is assigned as the stop.
``park_first``  The proper order. W1's first touch is a PARKING move, never a reference: whatever stopped it - its stop or the forearm -
                it is then somewhere in (104.91, 169.85] deg (the only things that stall a +W1 sweep at <= 1 N.m are the stop and the
                gripper meeting the forearm, which needs |W1| > 104.91), so moving it back 135 deg puts it in (-30, 35] deg, inside the
                proof (|W1| <= 95 clears both CAD pairs). Then W2 homes with nothing to hit, goes to 0; W1 homes for real (|W2| = 0), goes
                to 0; W3 last. Every defining stall passes the ROTOR-PHASE WITNESS: a board reads its output mod one rotor turn (36 deg)
                at power-on, so a true stop must read ``stop + phase`` mod 36 deg; a stall that does not is refused, never assigned.

``identify_backlash`` (option B's calibration verb): the five-bar's ``press_reverse+gff`` and, per wrist joint in the park_first order,
both stops pressed at half and full cap; ``fit(identify="B2")`` gives the BacklashTable ``home()`` stores. The claw's single closed stop
gives no gap (only one side is observable), so it stays B0, flagged unobserved.

Every angle shown is in degrees; the sequences are SI (rad, rad/s, N.m).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from robot_models.homing.fit import fit
from robot_models.homing.protocols import Phase
from robot_models.homing.types import BacklashModel, BacklashTable, HomingResult, JointBacklash, StallEvidence
from robot_msgs.control import Elapsed, JointCommand, JointCommandSequence, JointCommandStep, Reached, Stall

from .fullarm_plant import (
    BOARD_MAX_NM,
    C1,
    CLAW,
    CLAW_KP_NM_PER_RAD,
    FIVEBAR,
    J1,
    J2,
    JOINTS,
    ROLE,
    W1,
    W2,
    W3,
    WRIST,
    WRIST_KP_NM_PER_REV,
    ArmPrior,
    wrap_turn,
)
from .procedures import HomingRefused

TAU = 2.0 * math.pi
WRIST_SEEK_SPEED = 0.1 * TAU  # the recipe's max_vel 0.1 rev/s (wrist_home_v1.SPEED_DEG_S 36)
WRIST_SEEK_DISTANCE = math.radians(350.0)  # wrist_home_v1.TRAVEL_DEG: from an unknown rest the stop can be almost a full travel away
WRIST_CAP_NM = 1.0  # the recipe's max_torque 1.0
WRIST_HOLD_CAP_NM = 1.0
WRIST_MOVE_SPEED = 0.1 * TAU
WRIST_KP_NM_PER_RAD = WRIST_KP_NM_PER_REV / TAU
CLAW_SEEK_SPEED = math.radians(30.0)  # wrist_home_v1.CLAW_SPEED_DEG_S
CLAW_SEEK_DISTANCE = math.radians(100.0)  # past the claw's whole 77 deg travel
CLAW_CAP_NM = 0.3  # claw_jog / wrist_home_v1.CLAW_CAP_NM
CLAW_HOLD_CAP_NM = 0.3
J1_HOLD_CAP_NM = 7.0  # tview_run.J1_HOLD_NM
PARK_BACK_RAD = math.radians(135.0)  # (104.91, 169.85] - 135 = (-30.1, 34.85]: inside |W1| <= 95 (module docstring)
PARK_SEEK_SIDE = +1
PARK_BACK_SPEED = 0.05 * TAU  # half the seek speed: the contact unloads over ~0.5 s
WITNESS_TOL_RAD = math.radians(2.0)  # a stall's reading vs stop + phase mod one turn: the gap/2 + compliance at 1 N.m is < 0.6 deg
PRESS_S = 0.8
STEP_TIMEOUT_S = 40.0
WRIST_ORDERS = ("zach_v1", "park_first")


# ------------------------------------------------------------------------------------------------------------------- sequence words


def _hold(joint: str, feedforward: float = 0.0) -> JointCommand:
    cap = {J1: J1_HOLD_CAP_NM, CLAW: CLAW_HOLD_CAP_NM}.get(joint, WRIST_HOLD_CAP_NM if joint in WRIST else 10.0)
    return JointCommand.hold(joint, max_effort=cap, feedforward_effort=feedforward)


def _seek(joint: str, side: int, cap: float) -> JointCommand:
    if joint == CLAW:
        return JointCommand.move_by(joint, side * CLAW_SEEK_DISTANCE, speed=CLAW_SEEK_SPEED, max_effort=cap)
    return JointCommand.move_by(joint, side * WRIST_SEEK_DISTANCE, speed=WRIST_SEEK_SPEED, max_effort=cap)


def _stall(joint: str, cap: float) -> Stall:
    # WHY the lead past the PD's sag under its cap (wrist._stall, sag_proof's rule): at kp 15 N.m/rev a 1 N.m push needs 0.42 rad of
    # lead - a stall must mean the board is pressing at its cap, not climbing friction and gravity on the way
    kp = CLAW_KP_NM_PER_RAD if joint == CLAW else WRIST_KP_NM_PER_RAD
    return Stall(joint=joint, lead=0.06 + cap / kp)


def _reached(joint: str, cap: float) -> list:
    """A move's done-when: within 0.5 deg, or arrived and still within what its PD can sag under its cap (wrist._reached's WHY: at kp 15
    the wrist rests up to ~15 deg off its target under gravity, wrist_home_v1's real settle errors)."""
    kp = CLAW_KP_NM_PER_RAD if joint == CLAW else WRIST_KP_NM_PER_RAD
    return [Reached(joints=(joint,), tolerance=math.radians(0.5)),
            Reached(joints=(joint,), tolerance=math.radians(0.5) + cap / kp, speed=0.02, dwell=0.5)]


def _to(joint: str, target: float, cap: float, speed: float = WRIST_MOVE_SPEED) -> JointCommand:
    return JointCommand.to(joint, target, speed=speed, max_effort=cap)


def _by(joint: str, distance: float, cap: float, speed: float = WRIST_MOVE_SPEED) -> JointCommand:
    return JointCommand.move_by(joint, distance, speed=speed, max_effort=cap)


def _recapture(joint: str) -> JointCommand:
    """A hold re-latched where the joint IS. WHY not ``hold``: robot_msgs' controller keeps a hold-after-hold at its old setpoint (on purpose,
    so holds do not walk the arm down one sag per step); a 1 urad move starts its track at the measured pose."""
    return JointCommand.move_by(joint, 1e-6, speed=WRIST_MOVE_SPEED, max_effort=WRIST_HOLD_CAP_NM)


def full_step(name: str, commands, done, *, holds: dict, timeout: float = STEP_TIMEOUT_S, define=None) -> JointCommandStep:
    """A step over all seven joints: the named commands, every other joint as ``holds`` says (joint -> JointCommand)."""
    named = {c.joint for c in commands}
    full = list(commands) + [holds[j] for j in JOINTS if j not in named]
    return JointCommandStep(name=name, commands=tuple(full), done_when=tuple(done), timeout=timeout, define_position=define or {})


def widen(sequence: JointCommandSequence, holds: dict) -> JointCommandSequence:
    """A five-bar sequence over all seven joints: every step keeps its own commands and holds the rest (``holds``)."""
    steps = tuple(full_step(s.name, s.commands, s.done_when, holds=holds, timeout=s.timeout, define=dict(s.define_position))
                  for s in sequence.steps)
    return JointCommandSequence(joint_names=JOINTS, steps=steps, name=sequence.name)


def project(phase: Phase, joints: Sequence[str]) -> Phase:
    """``phase`` as a procedure over ``joints`` only would have logged it (its columns picked out of the seven)."""
    index = [JOINTS.index(j) for j in joints]
    log = dict(phase.log)
    for key in ("position", "velocity", "effort"):
        log[key] = [[row[i] for i in index] for row in phase.log[key]]
    log["defines"] = [{j: v for j, v in d.items() if j in joints} for d in phase.log["defines"]]
    return Phase(phase.sequence, phase.status, phase.message, phase.events, log)


def step_readings(phase: Phase) -> dict:
    """Step name -> (tick, raw reading per joint in the power-up frame, effort per joint) on the tick that step's done-when held."""
    from .wrist import step_ends  # noqa: PLC0415

    return step_ends(phase, JOINTS)


# ------------------------------------------------------------------------------------------------------------------- the five-bar


COMPS = ("plate", "nominal", "v2_cad", "v2_identified")
# WHY v2_cad and not today's plate (gravity_ff.COMP): on the bam_fb_v2 twin the plate comp lets J2 run away (290 deg/s) on single_touch+gff's
# walk home from the upper stops - the plate rig's end group is not the wrist + claw; nominal / v2_cad / v2_identified all home (sim, 2026-11-13).
# v2_cad is bam_rack_twin.fullarm_comp's (Sim to Real's `fivebar_home --comp bam_fb_v2`): the comp of THIS arm.
DEFAULT_COMP = "v2_cad"


_ARM_COMPS: dict = {}


def arm_comp(name: str = DEFAULT_COMP, scale: float = 1.0):
    """A ``gravity_ff.GravityComp`` for comp ``name`` (``fullarm_home.COMP_NAMES``): ``plate`` is gravity_ff's own (the mass-ID file); the
    others are fullarm_home's ``comp_model`` (``nominal``, and bam_rack_twin.fullarm_comp's bam_fb_v2 swaps ``v2_cad`` / ``v2_identified``)."""
    from .gravity_ff import COMP, GravityComp, default_comp  # noqa: PLC0415
    from .mujoco_plant import RigCache  # noqa: PLC0415

    if name == "plate":
        return default_comp(COMP, scale)
    key = (name, float(scale))
    if key not in _ARM_COMPS:
        from . import fullarm_home as fh  # noqa: PLC0415

        from .mujoco_plant import bam_ws_path  # noqa: PLC0415

        bam_ws_path()
        from bam_fb_test_rig.gravity import CraigMap  # noqa: PLC0415

        comp = GravityComp.__new__(GravityComp)
        comp.comp = name if scale == 1.0 else f"{name} x{scale:g}"
        comp.scale = float(scale)
        comp.bench, comp.model = fh.bench_real(), fh.comp_model(name)
        craig = CraigMap(RigCache.get("B0"))  # v11's Craig map: equal to bam_fb_v2's (tests/test_homing_fullarm.py)
        comp.offset = {J2: float(craig.offset["J2"]), C1: float(craig.offset["C1"])}
        _ARM_COMPS[key] = comp
    return _ARM_COMPS[key]


def _arm_gff_class():
    from .gravity_ff import GravityFF, procedure_frame, with_gravity_ff  # noqa: PLC0415

    class ArmGravityFF(GravityFF):
        """gravity_ff's ``GravityFF`` with any ``arm_comp`` (its own takes a mass-ID file only)."""

        def plan(self, prior, so_far):
            sequence = self.inner.plan(prior, so_far)
            if sequence is None:
                return None
            sequence, self.plan_note = with_gravity_ff(sequence, prior, arm_comp(self.comp_name, self.ff_scale),
                                                       frame=procedure_frame(self.inner, prior))
            self.notes["gravity_ff"] = self.plan_note
            return sequence

    return ArmGravityFF


def fivebar_procedure(name: str = "single_touch+gff", *, comp: str = DEFAULT_COMP, ff_scale: float = 1.0):
    """The five-bar's real-form procedure (``real_bench.RealRow``) with its gravity feed-forward from ``arm_comp(comp)``."""
    from .gravity_ff import GravityFF  # noqa: PLC0415
    from .real_bench import RealRow  # noqa: PLC0415

    row = RealRow(name, ff_scale=ff_scale)
    if isinstance(row.inner, GravityFF) and comp != "plate":  # RealRow builds gravity_ff.COMP (the plate) itself
        swapped = _arm_gff_class()(inner=row.inner.inner, comp_name=comp, ff_scale=ff_scale)
        if row.procedure is row.inner:
            row.procedure = swapped
        row.inner = swapped
    return row


def fivebar_home_hold(prior: ArmPrior, comp: str = DEFAULT_COMP, ff_scale: float = 1.0) -> dict:
    """The five-bar held at single_touch's home with the comp's gravity there (J1 held): what phase 1 sends J1 / J2 / C1 every step."""
    from .procedures import home_cad  # noqa: PLC0415

    home = home_cad(prior)
    gravity = arm_comp(comp, ff_scale).torque({J1: 0.0, J2: home[J2], C1: home[C1]}) or {J2: 0.0, C1: 0.0}
    return {J1: _hold(J1), J2: JointCommand.to(J2, home[J2], speed=0.1 * TAU, max_effort=10.0, feedforward_effort=gravity[J2]),
            C1: JointCommand.to(C1, home[C1], speed=0.1 * TAU, max_effort=7.0, feedforward_effort=gravity[C1])}


# ------------------------------------------------------------------------------------------------------------------- the witness


def witness_error(prior: ArmPrior, joint: str, side: int, raw: float) -> float | None:
    """How far a stall's power-up reading sits from where the true ``side`` stop must read (rad, wrapped to half a rotor turn), or None
    for a joint with no rotor phase. A board boots reading ``wrap(q + phase)`` and counts on from there, so on the true stop it reads
    ``stop + phase`` plus a whole number of turns (module docstring)."""
    if joint not in prior.rotor_phase:
        return None
    turn = prior.turn[joint]
    return wrap_turn(raw - prior.stops.q_rad(joint, side) - prior.rotor_phase[joint], turn)


# ------------------------------------------------------------------------------------------------------------------- the procedure


@dataclass
class FullArmHome:
    """The full-arm home: phase 0 the five-bar (``fivebar``), phase 1 the claw then the wrist in ``order`` (module docstring).

    ``witness``: refuse a defining stall whose rotor phase says it is not on its stop (``park_first`` uses it; ``zach_v1`` does not, as on
    the rack). ``identify``: press both stops of every wrist joint at two levels and fit B2 (identify_backlash) instead of one touch."""

    order: str = "park_first"
    witness: bool | None = None
    identify: bool = False
    wrist_only: bool = False
    wrist_during_fivebar: str = "brake"
    fivebar_name: str | None = None
    comp: str = DEFAULT_COMP
    ff_scale: float = 1.0
    name: str = ""
    references: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.order not in WRIST_ORDERS:
            raise ValueError(f"order must be one of {WRIST_ORDERS}, not {self.order!r}")
        if self.witness is None:
            self.witness = self.order == "park_first"
        if self.fivebar_name is None:
            self.fivebar_name = "press_reverse+gff" if self.identify else "single_touch+gff"
        self.fivebar = fivebar_procedure(self.fivebar_name, comp=self.comp, ff_scale=self.ff_scale)
        if not self.name:
            self.name = (("identify_backlash" if self.identify else "home") + f"[{self.order}{'+witness' if self.witness else ''}]"
                         + (" wrist only" if self.wrist_only else ""))

    # -- plan ------------------------------------------------------------------------------------------------------------------------

    def plan(self, prior: ArmPrior, so_far: Sequence[Phase]):
        if self.wrist_only:
            # WHY a wrist-only form (the sim-vs-real replay): wrist_home_v1 ran on the rack with the five-bar where it was, held; the
            # five-bar is not homed, so its holds are "where it is" with no feed-forward (no pose is known to feed)
            return None if so_far else self._phase1(prior, fivebar_holds={j: _hold(j) for j in FIVEBAR})
        if not so_far:
            # WHY braked by default (sim 2026-11-13, the backlash ladder): HELD on its kp 15 boards the wrist is flung by L2 and springs
            # back past the controller's 3 rad/s guard (aborted 9 of 18 episodes on B1 / B2 and identify_backlash on both), the held claw
            # whips at ~300 deg/s; fullarm_home's sweep found the brake the gentlest of limp / hold / brake. A limp step here is `d brake`.
            if self.wrist_during_fivebar == "hold":
                others = {j: _hold(j) for j in (*WRIST, CLAW)}
            elif self.wrist_during_fivebar == "brake":
                others = {j: JointCommand.limp(j) for j in (*WRIST, CLAW)}
            else:
                raise ValueError(f"wrist_during_fivebar must be hold or brake, not {self.wrist_during_fivebar!r}")
            return widen(self.fivebar.plan(prior, []), others)
        if len(so_far) == 1:
            return self._phase1(prior)
        return None

    def _phase1(self, prior: ArmPrior, fivebar_holds: dict | None = None) -> JointCommandSequence:
        fivebar_holds = fivebar_holds or fivebar_home_hold(prior, self.comp, self.ff_scale)
        holds = {**fivebar_holds, **{j: _hold(j) for j in (*WRIST, CLAW)}}
        side = {j: int(prior.seek_side[j]) for j in (*WRIST, CLAW)}
        steps = [full_step("phase 1: everything holds", [], [Elapsed(duration=0.3)], holds=holds, timeout=1.0)]
        claw_stop = prior.stops.q_rad(CLAW, side[CLAW])
        # the claw first: close onto its stop, assign it, ease off 5 deg and hold there (wrist_home_v1.CLAW_MARGIN_DEG: held just off the
        # closed stop, not pressing into it). WHY a parameter and not -1: Zach is re-mounting the claw reversed (2026-11-13); its seek side
        # and closed stop come from the prior (the bundle's stops.json), never from this code.
        steps.append(full_step("claw closes", [_seek(CLAW, side[CLAW], CLAW_CAP_NM)], [_stall(CLAW, CLAW_CAP_NM)], holds=holds,
                               define={CLAW: claw_stop}))
        claw_rest = claw_stop - side[CLAW] * math.radians(5.0)
        steps.append(full_step("claw eases off", [_to(CLAW, claw_rest, CLAW_HOLD_CAP_NM, CLAW_SEEK_SPEED)], _reached(CLAW, CLAW_HOLD_CAP_NM),
                               holds=holds))
        holds = {**holds, CLAW: _to(CLAW, claw_rest, CLAW_HOLD_CAP_NM, CLAW_SEEK_SPEED)}
        if self.order == "zach_v1":
            plan = [(W1, True), (W2, True), (W3, True)]
            parked = False
        else:
            plan = [(W1, False), (W2, True), (W1, True), (W3, True)]
            parked = True
        for joint, defines in plan:
            role = ROLE[joint]
            if not defines:
                steps.append(full_step(f"{role} park touch", [_seek(joint, PARK_SEEK_SIDE, WRIST_CAP_NM)], [_stall(joint, WRIST_CAP_NM)],
                                       holds=holds))
                # WHY the others re-captured where they are, and a slow retreat (sim 2026-11-13, start W1 -60 / W2 160): a park touch on the
                # forearm pushes W2 off its hold (kp 15: 1 N.m is 24 deg of sag); backing W1 off at once released W2's wound-up PD and
                # whipped it past the sequence controller's 3 rad/s guard. A fresh hold at the deflected angle unloads it gently.
                recaptured = [_recapture(j) for j in WRIST if j != joint]
                steps.append(full_step(f"{role} parks back 135 deg", [_by(joint, -PARK_SEEK_SIDE * PARK_BACK_RAD, WRIST_HOLD_CAP_NM,
                                                                        PARK_BACK_SPEED), *recaptured],
                                       _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
                holds = {**holds, joint: _hold(joint)}
                continue
            steps += self._touch(prior, joint, side[joint], holds)
            steps.append(full_step(f"{role} to 0", [_to(joint, 0.0, WRIST_HOLD_CAP_NM)], _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
            holds = {**holds, joint: _to(joint, 0.0, WRIST_HOLD_CAP_NM)}
        self.notes["phase1_parked"] = parked
        return JointCommandSequence(joint_names=JOINTS, steps=tuple(steps), name=f"claw + wrist ({self.order})")

    def _touch(self, prior: ArmPrior, joint: str, side: int, holds: dict) -> list:
        role = ROLE[joint]
        near = prior.stops.q_rad(joint, side)
        if not self.identify:
            return [full_step(f"{role} seeks", [_seek(joint, side, WRIST_CAP_NM)], [_stall(joint, WRIST_CAP_NM)], holds=holds,
                              define={joint: near})]
        far = prior.stops.q_rad(joint, -side)
        ease = math.radians(3.0)
        steps = []
        for tag, s in (("near", side), ("far", -side)):
            if tag == "far":
                steps.append(full_step(f"{role} walks across", [_to(joint, far + side * ease, WRIST_HOLD_CAP_NM)],
                                       _reached(joint, WRIST_HOLD_CAP_NM), holds=holds))
            steps += [full_step(f"{role} {tag} seek", [_seek(joint, s, 0.5 * WRIST_CAP_NM)], [_stall(joint, 0.5 * WRIST_CAP_NM)], holds=holds),
                      full_step(f"{role} {tag} press half", [_seek(joint, s, 0.5 * WRIST_CAP_NM)], [Elapsed(duration=PRESS_S)], holds=holds),
                      full_step(f"{role} {tag} press full", [_seek(joint, s, WRIST_CAP_NM)], [Elapsed(duration=PRESS_S)], holds=holds,
                                define={joint: near} if tag == "near" else None)]
        return steps

    # -- observe ---------------------------------------------------------------------------------------------------------------------

    def _evidence(self, phase_index: int, reading, joint: str, side: int) -> StallEvidence:
        self.references.append((phase_index, reading.tick, joint, side))
        return StallEvidence(joint, side, abs(reading.effort[joint]), reading.raw[joint], rung="mujoco")

    def observe(self, prior: ArmPrior, phases: Sequence[Phase]) -> HomingResult:
        self.references = []
        if self.wrist_only:
            five, wrist_phase = None, 0
        else:
            five = self.fivebar.observe(prior, [project(phases[0], FIVEBAR)])
            self.references = [r for r in self.fivebar.references]
            wrist_phase = 1
        ends = step_readings(phases[wrist_phase])
        side = {j: int(prior.seek_side[j]) for j in (*WRIST, CLAW)}
        evidence = [self._evidence(wrist_phase, ends["claw closes"], CLAW, side[CLAW])]
        for joint in WRIST:
            role = ROLE[joint]
            if self.identify:
                for tag, s in (("near", side[joint]), ("far", -side[joint])):
                    for level in ("half", "full"):
                        evidence.append(self._evidence(wrist_phase, ends[f"{role} {tag} press {level}"], joint, s))
            else:
                evidence.append(self._evidence(wrist_phase, ends[f"{role} seeks"], joint, side[joint]))
        witness = {}
        for stall in evidence:
            error = witness_error(prior, stall.joint, stall.side, stall.motor_raw_rad)
            if error is not None:
                witness.setdefault(ROLE[stall.joint], []).append(round(math.degrees(error), 3))
        self.notes["witness_deg"] = witness
        if self.witness:
            bad = {role: errors for role, errors in witness.items() if any(abs(e) > math.degrees(WITNESS_TOL_RAD) for e in errors)}
            if bad:
                self.notes["witness_refused"] = bad
                raise HomingRefused(f"rotor-phase witness: {bad} deg off the stop's phase (tolerance {math.degrees(WITNESS_TOL_RAD):.1f})")
        if self.identify:
            arm = fit(evidence, prior.stops, identify="B2", rung="mujoco")
            claw = arm.backlash.get(CLAW)
            entries = [e for e in arm.backlash.entries if e.joint != CLAW]
            entries.append(JointBacklash(CLAW, BacklashModel("B0"), False, False, "one closed stop: no gap is observable"))
            if claw is not None:
                self.notes["claw_fit_ignored"] = "the claw's one-sided stalls identify no gap"
            table = BacklashTable(tuple(entries))
            arm = fit(evidence, prior.stops, table=table, rung="mujoco")
        else:
            stored = prior.table
            table = BacklashTable(tuple((stored.get(j) if stored is not None and stored.get(j) is not None else
                                         JointBacklash(j, BacklashModel("B0"), source="no stored table")) for j in (*WRIST, CLAW)))
            arm = fit(evidence, prior.stops, table=table, rung="mujoco")
            table = BacklashTable(tuple(JointBacklash(e.joint, e.model, False, False, "stored table (identify_backlash)") for e in table.entries))
        five_zeros, five_table, five_evidence = ((), (), ()) if five is None else (
            # WHY filtered: single_touch's observe echoes the WHOLE stored table, wrist rows included (a full-arm table on a home())
            five.zeros, tuple(e for e in five.backlash.entries if e.joint in FIVEBAR), five.evidence)
        zeros = tuple(five_zeros) + tuple(arm.zeros)
        backlash = BacklashTable(tuple(five_table) + tuple(e for e in table.entries if e.joint not in FIVEBAR))
        return HomingResult(zeros, backlash, prior.stops, tuple(five_evidence) + tuple(evidence), "mujoco")


def identify_backlash(order: str = "park_first", **kwargs) -> FullArmHome:
    """B's calibration verb for the whole arm (module docstring)."""
    return FullArmHome(order=order, identify=True, **kwargs)


def home(order: str = "park_first", **kwargs) -> FullArmHome:
    """B's boot verb: one touch per joint, the stored table (``prior.table``) correcting each zero for its backlash."""
    return FullArmHome(order=order, **kwargs)


__all__ = ["WITNESS_TOL_RAD", "WRIST_ORDERS", "FullArmHome", "fivebar_procedure", "home", "identify_backlash", "project", "widen",
           "witness_error"]
