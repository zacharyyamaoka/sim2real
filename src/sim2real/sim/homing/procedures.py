"""Homing procedures as black boxes (robot_models ``HomingProcedure``): ``plan`` emits one robot_msgs ``JointCommandSequence``, run
by the ``JointCommandSequenceController``; ``observe`` turns the run into a ``HomingResult`` in the power-up encoder frame.

The five leaderboard rows (decision report, section 4), each wrapped without changing its logic:

* ``tview_v2``           Zach's tview sequence (vault ``moteus_homing/examples/tview_seq/v2.md``; bam_fb_test_rig.homing, the real
                         lane's tview_run): J1 holds; J2 and C1 seek together until both stall; ``cfg-set-output`` 0.34722 / 0.66347
                         rev; his moves (0.25, 0.4), (0.06, 0.23), (0.0, 0.1); J1 seeks, set-output 0.25, to 0; home (0, 0, 0.371).
                         The zero is the set-output itself: no backlash correction, his typed numbers.
* ``single_touch``       sim2real's ``homing.single_touch``: one seek per joint at the seek cap (the real lane's sequential order:
                         J2, then C1 with J2 still pushing, then J1), zero = the stall minus the CAD stop, corrected by half the stored
                         gap and the stored give at the stall torque (it ``requires`` backlash_rad: the stored table).
* ``repeat_checked_seek``  bam_homing's HardstopSeekGroup (PRESS at the cap, BACKOFF 0.045 rev, PROBE at half cap and half speed,
                         REPRESS): a stop only if it repeats (1 mrad) and is stiff (>= 400 N.m/rev, probe step >= 1e-9 rev); the datum
                         is the confirmed reading less its push over the measured stiffness. No gap correction (it has none).
* ``two_level_touch``    the report's B ``home()``: one touch per joint at half then full cap; zero from the stored gap and its OWN
                         compliance (the slope of the two levels); ``recalibrate`` when its compliance and the table's differ > 50 %.
* ``press_reverse``      the report's A one routine: two levels on the seek side, a diagonal walk to the far corner, two levels on
                         the other side; ``fit`` identifies gap (stop span vs CAD, sim only) and compliance and zeroes in one run.
                         ``identify_backlash`` is this procedure's fit, kept as the stored table the boot procedures read.

Seek side, speeds and caps are tview's: every drive homes on its CAD upper stop (J2 +125.00, C1 +197.77, J1 +89.975 deg) at
0.1 rev/s under 10 / 7 / 10 N.m.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from robot_models.homing.fit import fit
from robot_models.homing.protocols import Phase, Prior
from robot_models.homing.types import (
    BacklashModel,
    BacklashTable,
    HomingResult,
    JointBacklash,
    JointZero,
    StallEvidence,
)
from robot_msgs.control import (
    Elapsed,
    JointCommand,
    JointCommandSequence,
    JointCommandStep,
    Reached,
    Stall,
)

from .geometry import C1, DRIVES, J1, J2

TAU = 2.0 * math.pi
REV_S = TAU  # rad/s per rev/s
SEEK_SPEED = 0.1 * REV_S  # tview's 0.1 rev/s
SEEK_DISTANCE = 2.5 * TAU  # tview_run.SEEK_TIMEOUT_S: two and a half output turns, a sanity bound, not a travel bound
SEEK_CAP_NM = {J1: 10.0, J2: 10.0, C1: 7.0}  # his lines: 12>d pos nan 0.1 10, 13>d pos nan 0.1 7, 11>d pos nan 0.1 10
HOLD_CAP_NM = {J1: 7.0, J2: 10.0, C1: 7.0}  # tview_run.J1_HOLD_NM for J1; his move caps for J2 / C1
MOVE_SPEED = 0.1 * REV_S  # v0.1
REACH_RAD = math.radians(0.5)
# tview_run's own reaches (bam_rack_twin.hardware.tview_run): REACH_RAD 20 deg on the way (a PD carrying the arm sags ~13 deg),
# HOME_REACH_RAD 3 deg at home. WHY tview keeps them: they are part of how his sequence is run on the boards.
TVIEW_REACH_RAD = math.radians(20.0)
TVIEW_HOME_REACH_RAD = math.radians(3.0)
PRESS_S = 0.8  # a press held long enough for the board's PD to reach its cap (lead grows 0.63 rad/s; 10 N.m needs 0.31 rad)
STEP_TIMEOUT_S = 40.0
# tview v2's constants (bam_fb_test_rig.homing / bam_rack_twin.hardware.tview_replay SHOULDER_LINES), revolutions in his frame
SET_OUTPUT_REV = {J2: 0.34722, C1: 0.66347, J1: 0.25}
MOVES_REV = ((0.25, 0.4), (0.06, 0.23))
J1_PREP_REV = (0.0, 0.1)
HOME_REV = {J1: 0.0, J2: 0.0, C1: 0.371}
# bam_homing controller.py (HomingControllerConfig) and hardstop_seek.py
BACKOFF_REV = 0.045
PROBE_FRACTION = 0.5
REPEAT_TOLERANCE_RAD = 1e-3
MIN_STIFFNESS_NM_PER_REV = 400.0
MIN_PROBE_DISPLACEMENT_REV = 1e-9
RECALIBRATE_FRACTION = 0.5


class HomingRefused(RuntimeError):
    """The procedure's own checks refused to declare a zero (bam_homing's faults): not a crash, an outcome."""


def frame_offsets(prior: Prior) -> dict[str, float]:
    """Zach's frame minus CAD, per drive: his typed set-output against the CAD stop it labels. J1 and J2's typed values ARE the CAD
    stops to his typing precision (0.25 rev = 90.000 vs 89.975 deg; 0.34722 rev = 124.999 vs 125.000 deg), so their frame is CAD;
    C1's 0.66347 rev (238.85 deg) is in his own crank frame, 41.08 deg from CAD's 197.77, with no other reference to place it."""
    upper = prior.stops.q_rad(C1, +1)
    return {J1: 0.0, J2: 0.0, C1: SET_OUTPUT_REV[C1] * TAU - upper}


def home_cad(prior: Prior) -> dict[str, float]:
    """tview's home (0, 0, 0.371 rev) in CAD: the same physical home for every procedure."""
    d = frame_offsets(prior)
    return {joint: HOME_REV[joint] * TAU - d[joint] for joint in DRIVES}


# ---------------------------------------------------------------------------------------------------------------- sequence words


def _limp(joint):
    return JointCommand.limp(joint)


def _hold(joint):
    return JointCommand.hold(joint, max_effort=HOLD_CAP_NM[joint])


def _seek(joint, side, cap, speed=SEEK_SPEED):
    return JointCommand.move_by(joint, side * SEEK_DISTANCE, speed=speed, max_effort=cap)


def _to(joint, position, speed=MOVE_SPEED, cap=None):
    return JointCommand.to(joint, position, speed=speed, max_effort=cap if cap is not None else HOLD_CAP_NM[joint])


def _step(name, commands, done, *, timeout=STEP_TIMEOUT_S, define=None):
    named = {c.joint for c in commands}
    full = list(commands) + [_limp(j) for j in DRIVES if j not in named]
    return JointCommandStep(name=name, commands=tuple(full), done_when=tuple(done), timeout=timeout, define_position=define or {})


def _sequence(name, steps):
    return JointCommandSequence(joint_names=DRIVES, steps=tuple(steps), name=name)


def _diagonal(joints_targets: dict, frm: dict, name: str, others=()):
    """A straight move in joint space: every joint arrives together (each at its share of v0.1)."""
    spans = {j: abs(joints_targets[j] - frm[j]) for j in joints_targets}
    longest = max(spans.values()) or 1.0
    commands = [_to(j, joints_targets[j], speed=max(MOVE_SPEED * spans[j] / longest, 1e-3)) for j in joints_targets]
    commands += [_hold(j) for j in others]
    return _step(name, commands, [Reached(joints=tuple(joints_targets), tolerance=REACH_RAD)])


# ---------------------------------------------------------------------------------------------------------------- reading a run


@dataclass
class Reading:
    """One controller tick as the procedure saw it, in the power-up encoder frame (its own defines taken back out)."""

    tick: int
    raw: dict
    effort: dict


def step_ends(phase: Phase) -> dict[str, Reading]:
    """Step name -> the reading on the tick the step finished (the one its done_when held on)."""
    log = phase.log
    shift = {j: 0.0 for j in DRIVES}
    out = {}
    names = [s.name for s in phase.sequence.steps]
    previous = 0
    for k in range(len(log["t"])):
        seen = dict(zip(DRIVES, log["position"][k], strict=True))
        reading = Reading(k, {j: seen[j] - shift[j] for j in DRIVES}, dict(zip(DRIVES, log["effort"][k], strict=True)))
        count = log["events"][k]
        if count > previous:
            out[names[count - 1]] = reading
            previous = count
        for joint, value in log["defines"][k].items():
            shift[joint] += value - seen[joint]
    return out


def final_frame(phase: Phase) -> dict[str, float]:
    """What the sequence's defines added to the power-up reading, per joint: ``q = raw + frame``."""
    log = phase.log
    shift = {j: 0.0 for j in DRIVES}
    for k in range(len(log["t"])):
        seen = dict(zip(DRIVES, log["position"][k], strict=True))
        for joint, value in log["defines"][k].items():
            shift[joint] += value - seen[joint]
    return shift


@dataclass
class Procedure:
    """Shared plumbing: ``references`` lists (phase, tick, joint, side) of every stall the result relies on, for the bench's truth
    check (reliability: was each one truly on its stop?). It is filled by ``observe``."""

    name: str = ""
    references: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def _evidence(self, phase_index: int, reading: Reading, joint: str, side: int) -> StallEvidence:
        self.references.append((phase_index, reading.tick, joint, side))
        return StallEvidence(joint, side, abs(reading.effort[joint]), reading.raw[joint])


# ---------------------------------------------------------------------------------------------------------------- tview v2


@dataclass
class TviewV2(Procedure):
    name: str = "tview_v2"

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        if so_far:
            return None
        rev = lambda value: value * TAU  # noqa: E731
        steps = [
            _step("1. J1 holds", [_hold(J1)], [Elapsed(duration=0.3)], timeout=1.0),
            # WHY two steps: a step ends on ANY of its conditions and tview waits for BOTH stalls. Step 2 ends on J2's, step 2b on
            # C1's; whichever stalled first keeps pushing its stop meanwhile (tview leaves the seek running), as on the boards.
            _step("2. J2 + C1 seek together", [_hold(J1), _seek(J2, +1, SEEK_CAP_NM[J2]), _seek(C1, +1, SEEK_CAP_NM[C1])],
                  [Stall(joint=J2)]),
            _step("2b. ... until C1 has stalled too", [_hold(J1), _seek(J2, +1, SEEK_CAP_NM[J2]), _seek(C1, +1, SEEK_CAP_NM[C1])],
                  [Stall(joint=C1)], define={J2: rev(SET_OUTPUT_REV[J2]), C1: rev(SET_OUTPUT_REV[C1])}),
            _step("3. cfg-set-output 0.34722 / 0.66347", [_hold(J1), _hold(J2), _hold(C1)], [Elapsed(duration=0.2)]),
        ]
        for j2, c1 in (*MOVES_REV, J1_PREP_REV):
            steps.append(_step(f"4. move to ({j2}, {c1}) v0.1", [_hold(J1), _to(J2, rev(j2)), _to(C1, rev(c1))],
                               [Reached(joints=(J2, C1), tolerance=TVIEW_REACH_RAD)]))
        steps += [
            _step("5. J1 seek", [_seek(J1, +1, SEEK_CAP_NM[J1]), _hold(J2), _hold(C1)], [Stall(joint=J1)],
                  define={J1: rev(SET_OUTPUT_REV[J1])}),
            _step("5. J1 set output 0.25, move to 0", [_to(J1, 0.0), _hold(J2), _hold(C1)],
                  [Reached(joints=(J1,), tolerance=TVIEW_REACH_RAD)]),
            _step("6. home (0, 0, 0.371)", [_to(J1, rev(HOME_REV[J1])), _to(J2, rev(HOME_REV[J2])), _to(C1, rev(HOME_REV[C1]))],
                  [Reached(joints=DRIVES, tolerance=TVIEW_HOME_REACH_RAD)]),
        ]
        return _sequence("tview v2 (Zach's shoulder lines)", steps)

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        self.references = []
        phase = phases[0]
        ends = step_ends(phase)
        evidence = [self._evidence(0, ends["2b. ... until C1 has stalled too"], J2, +1),
                    self._evidence(0, ends["2b. ... until C1 has stalled too"], C1, +1),
                    self._evidence(0, ends["5. J1 seek"], J1, +1)]
        frame = final_frame(phase)
        d = frame_offsets(prior)
        zeros = tuple(JointZero(j, frame[j] - d[j], 0.0, 1, (+1,)) for j in DRIVES)
        table = BacklashTable(tuple(JointBacklash(j, BacklashModel("B0"), source="tview: no backlash model") for j in DRIVES))
        return HomingResult(zeros, table, prior.stops, tuple(evidence), "kinematic")


# ---------------------------------------------------------------------------------------------------------------- single touch


@dataclass
class SingleTouch(Procedure):
    name: str = "single_touch"

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        if so_far:
            return None
        cad = {j: prior.stops.q_rad(j, +1) for j in DRIVES}
        home = home_cad(prior)
        steps = [
            _step("J1 holds", [_hold(J1)], [Elapsed(duration=0.3)], timeout=1.0),
            _step("J2 seeks (C1 unpowered)", [_hold(J1), _seek(J2, +1, SEEK_CAP_NM[J2])], [Stall(joint=J2)]),
            _step("C1 seeks (J2 pushing)", [_hold(J1), _seek(J2, +1, SEEK_CAP_NM[J2]), _seek(C1, +1, SEEK_CAP_NM[C1])],
                  [Stall(joint=C1)], define={J2: cad[J2], C1: cad[C1]}),
            _step("J1 seeks", [_seek(J1, +1, SEEK_CAP_NM[J1]), _hold(J2), _hold(C1)], [Stall(joint=J1)], define={J1: cad[J1]}),
        ]
        frm = dict(cad)
        steps.append(_diagonal({J1: home[J1]}, frm, "J1 to home", others=(J2, C1)))
        steps.append(_diagonal({J2: home[J2], C1: home[C1]}, frm, "J2 + C1 home", others=(J1,)))
        return _sequence("single touch (sequential, the real lane's order)", steps)

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        self.references = []
        ends = step_ends(phases[0])
        # J2's stall: read at the end of its own seek (its press); C1's at the end of the C1 seek
        evidence = [self._evidence(0, ends["J2 seeks (C1 unpowered)"], J2, +1),
                    self._evidence(0, ends["C1 seeks (J2 pushing)"], C1, +1),
                    self._evidence(0, ends["J1 seeks"], J1, +1)]
        stored = prior.table or BacklashTable(tuple(JointBacklash(j, BacklashModel("B0"), source="no stored table") for j in DRIVES))
        result = fit(evidence, prior.stops, table=stored)
        # WHY re-flagged: the table is the calibration's, read back; this run identified none of it, so it reports '-' (stored)
        table = BacklashTable(tuple(JointBacklash(e.joint, e.model, False, False, "stored table (identify_backlash)")
                                    for e in stored.entries))
        return HomingResult(result.zeros, table, prior.stops, tuple(evidence), "kinematic")


# ---------------------------------------------------------------------------------------------------------------- bam_homing


@dataclass
class RepeatCheckedSeek(Procedure):
    name: str = "repeat_checked_seek"

    def _group(self, joints, others, tag):
        caps = {j: SEEK_CAP_NM[j] for j in joints}
        seek = lambda frac, speed: [_seek(j, +1, caps[j] * frac, speed) for j in joints] + [_hold(o) for o in others]  # noqa: E731
        steps = []
        for stage, frac, speed in (("PRESS", 1.0, SEEK_SPEED), ("PROBE", PROBE_FRACTION, SEEK_SPEED * PROBE_FRACTION),
                                   ("REPRESS", 1.0, SEEK_SPEED * PROBE_FRACTION)):
            for joint in joints:  # WHY one step per joint: a step ends on ANY condition; the group waits for every member
                steps.append(_step(f"{tag} {stage} {joint}", seek(frac, speed), [Stall(joint=joint)]))
            # settled at the stage's cap (bam_homing samples at the barrier, pressing at the cap)
            steps.append(_step(f"{tag} {stage} settled", seek(frac, speed), [Elapsed(duration=PRESS_S)]))
            if stage == "PRESS":
                steps.append(_step(f"{tag} BACKOFF", [JointCommand.move_by(j, -BACKOFF_REV * TAU, speed=SEEK_SPEED, max_effort=caps[j])
                                                      for j in joints] + [_hold(o) for o in others],
                                   [Reached(joints=tuple(joints), tolerance=REACH_RAD)]))
        return steps

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        if so_far:
            return None
        cad = {j: prior.stops.q_rad(j, +1) for j in DRIVES}
        home = home_cad(prior)
        steps = [_step("J1 holds", [_hold(J1)], [Elapsed(duration=0.3)], timeout=1.0)]
        steps += self._group((J2, C1), (J1,), "J2+C1")
        steps.append(_step("define J2 + C1", [_hold(J1), _hold(J2), _hold(C1)], [Elapsed(duration=0.05)],
                           define={J2: cad[J2], C1: cad[C1]}))
        steps += self._group((J1,), (J2, C1), "J1")
        steps.append(_step("define J1", [_hold(J1), _hold(J2), _hold(C1)], [Elapsed(duration=0.05)], define={J1: cad[J1]}))
        steps.append(_diagonal({J1: home[J1]}, cad, "J1 to home", others=(J2, C1)))
        steps.append(_diagonal({J2: home[J2], C1: home[C1]}, cad, "J2 + C1 home", others=(J1,)))
        return _sequence("bam_homing checked seek (press, back off, probe, re-press)", steps)

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        self.references = []
        ends = step_ends(phases[0])
        zeros, evidence, faults = [], [], []
        for tag, joints in (("J2+C1", (J2, C1)), ("J1", (J1,))):
            first, probe, confirmed = ends[f"{tag} PRESS settled"], ends[f"{tag} PROBE settled"], ends[f"{tag} REPRESS settled"]
            for joint in joints:
                for reading in (first, probe, confirmed):
                    evidence.append(self._evidence(0, reading, joint, +1))
                x1, xp, xc = first.raw[joint], probe.raw[joint], confirmed.raw[joint]
                t1, tp, tc = first.effort[joint], probe.effort[joint], confirmed.effort[joint]
                if abs(xc - x1) > REPEAT_TOLERANCE_RAD:
                    faults.append(f"{joint} did not repeat ({math.degrees(xc - x1):+.4f} deg)")
                    continue
                displacement_rev = abs(x1 - xp) / TAU
                if displacement_rev < MIN_PROBE_DISPLACEMENT_REV:
                    faults.append(f"{joint}: probe displacement {displacement_rev:.2e} rev under {MIN_PROBE_DISPLACEMENT_REV:g}: "
                                  "stiffness unresolved, the seek refuses")
                    continue
                stiffness = (t1 - tp) / (x1 - xp)  # N.m per rad, direction-signed
                if stiffness * TAU < MIN_STIFFNESS_NM_PER_REV:
                    faults.append(f"{joint}: stiffness {stiffness * TAU:.0f} N.m/rev under the floor")
                    continue
                unloaded = xc - tc / stiffness
                zeros.append(JointZero(joint, prior.stops.q_rad(joint, +1) - unloaded, 0.0, 3, (+1,)))
        if faults:
            raise HomingRefused("; ".join(faults))
        table = BacklashTable(tuple(JointBacklash(j, BacklashModel("B0"), source="bam_homing: no gap model") for j in DRIVES))
        return HomingResult(tuple(zeros), table, prior.stops, tuple(evidence), "kinematic")


# ---------------------------------------------------------------------------------------------------------------- B and A


def _two_levels(joints, others, side, tag):
    """Seek ``side`` at half the cap until stalled, press there, then press at the full cap: two settled torque levels."""
    caps = {j: SEEK_CAP_NM[j] for j in joints}
    seek = lambda frac: [_seek(j, side, caps[j] * frac) for j in joints] + [_hold(o) for o in others]  # noqa: E731
    steps = [_step(f"{tag} seek {joint}", seek(0.5), [Stall(joint=joint)]) for joint in joints]
    steps.append(_step(f"{tag} press half", seek(0.5), [Elapsed(duration=PRESS_S)]))
    steps.append(_step(f"{tag} press full", seek(1.0), [Elapsed(duration=PRESS_S)]))
    return steps


@dataclass
class TwoLevelTouch(Procedure):
    name: str = "two_level_touch"

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        if so_far:
            return None
        cad = {j: prior.stops.q_rad(j, +1) for j in DRIVES}
        home = home_cad(prior)
        steps = [_step("J1 holds", [_hold(J1)], [Elapsed(duration=0.3)], timeout=1.0)]
        steps += _two_levels((J2, C1), (J1,), +1, "J2+C1")
        steps.append(_step("define J2 + C1", [_hold(J1), _hold(J2), _hold(C1)], [Elapsed(duration=0.05)],
                           define={J2: cad[J2], C1: cad[C1]}))
        steps += _two_levels((J1,), (J2, C1), +1, "J1")
        steps.append(_step("define J1", [_hold(J1), _hold(J2), _hold(C1)], [Elapsed(duration=0.05)], define={J1: cad[J1]}))
        steps.append(_diagonal({J1: home[J1]}, cad, "J1 to home", others=(J2, C1)))
        steps.append(_diagonal({J2: home[J2], C1: home[C1]}, cad, "J2 + C1 home", others=(J1,)))
        return _sequence("two-level touch (B: home with a stored table)", steps)

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        self.references = []
        ends = step_ends(phases[0])
        evidence = []
        for tag, joints in (("J2+C1", (J2, C1)), ("J1", (J1,))):
            for joint in joints:
                evidence.append(self._evidence(0, ends[f"{tag} press half"], joint, +1))
                evidence.append(self._evidence(0, ends[f"{tag} press full"], joint, +1))
        own = fit(evidence, prior.stops, identify="B2").backlash
        entries, recalibrate = [], {}
        for joint in DRIVES:
            mine = own.get(joint)
            stored = prior.table.get(joint) if prior.table is not None else None
            gap = stored.model.gap_rad if stored is not None else 0.0
            c = mine.model.compliance_rad_per_nm
            stored_c = stored.model.compliance_rad_per_nm if stored is not None else 0.0
            recalibrate[joint] = bool(stored is None or (stored_c > 0 and abs(c - stored_c) > RECALIBRATE_FRACTION * stored_c)
                                      or (stored_c == 0 and c > 0))
            kind = "B2" if c > 0 else ("B1" if gap > 0 else "B0")
            entries.append(JointBacklash(joint, BacklashModel(kind, gap, c if kind == "B2" else 0.0),
                                         gap_observable=False, compliance_observable=mine.compliance_observable,
                                         source="stored gap + own two-level compliance"))
        self.notes["recalibrate"] = recalibrate
        table = BacklashTable(tuple(entries))
        result = fit(evidence, prior.stops, table=table)
        return HomingResult(result.zeros, table, prior.stops, tuple(evidence), "kinematic")


@dataclass
class PressReverse(Procedure):
    name: str = "press_reverse"
    # the far corner it walks to before the other side's seeks: inside the export assembly's free map (loops.json), J2 near its
    # lower stop and C1 above its own
    corner_deg: dict = field(default_factory=lambda: {J2: -85.0, C1: -105.0})

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        if so_far:
            return None
        upper = {j: prior.stops.q_rad(j, +1) for j in DRIVES}
        lower = {j: prior.stops.q_rad(j, -1) for j in DRIVES}
        corner = {j: math.radians(v) for j, v in self.corner_deg.items()}
        home = home_cad(prior)
        steps = [_step("J1 holds", [_hold(J1)], [Elapsed(duration=0.3)], timeout=1.0)]
        steps += _two_levels((J2, C1), (J1,), +1, "J2+C1 upper")
        steps.append(_step("define J2 + C1", [_hold(J1), _hold(J2), _hold(C1)], [Elapsed(duration=0.05)],
                           define={J2: upper[J2], C1: upper[C1]}))
        steps.append(_diagonal({J2: corner[J2], C1: corner[C1]}, upper, "walk to the far corner", others=(J1,)))
        steps += _two_levels((J2,), (J1, C1), -1, "J2 lower")
        steps.append(_step("J2 eases off", [_hold(J1), _to(J2, lower[J2] + math.radians(3.0)), _hold(C1)],
                           [Reached(joints=(J2,), tolerance=REACH_RAD)]))
        steps += _two_levels((C1,), (J1, J2), -1, "C1 lower")
        steps += _two_levels((J1,), (J2, C1), +1, "J1 upper")
        steps.append(_step("define J1", [_hold(J1), _hold(J2), _hold(C1)], [Elapsed(duration=0.05)], define={J1: upper[J1]}))
        steps += _two_levels((J1,), (J2, C1), -1, "J1 lower")
        frm = {J1: lower[J1], J2: lower[J2] + math.radians(3.0), C1: lower[C1]}
        steps.append(_diagonal({J1: home[J1]}, frm, "J1 to home", others=(J2, C1)))
        steps.append(_diagonal({J2: home[J2], C1: home[C1]}, frm, "J2 + C1 home", others=(J1,)))
        return _sequence("press-reverse (A: stops, backlash and zero in one run)", steps)

    def stalls(self, phases: Sequence[Phase]) -> list[StallEvidence]:
        self.references = []
        ends = step_ends(phases[0])
        evidence = []
        for tag, joints, side in (("J2+C1 upper", (J2, C1), +1), ("J2 lower", (J2,), -1), ("C1 lower", (C1,), -1),
                                  ("J1 upper", (J1,), +1), ("J1 lower", (J1,), -1)):
            for joint in joints:
                evidence.append(self._evidence(0, ends[f"{tag} press half"], joint, side))
                evidence.append(self._evidence(0, ends[f"{tag} press full"], joint, side))
        return evidence

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        return fit(self.stalls(phases), prior.stops, identify="B2", rung="kinematic")


def identify_backlash(procedure: PressReverse, prior: Prior, phases: Sequence[Phase]) -> BacklashTable:
    """B's calibration verb on the kinematic rung: press_reverse's run, its fit's backlash table (what the boot procedures store)."""
    return procedure.observe(prior, phases).backlash


PROCEDURES = {cls().name: cls for cls in (TviewV2, SingleTouch, RepeatCheckedSeek, TwoLevelTouch, PressReverse)}

__all__ = ["PROCEDURES", "HomingRefused", "PressReverse", "RepeatCheckedSeek", "SingleTouch", "TviewV2", "TwoLevelTouch",
           "frame_offsets", "home_cad", "identify_backlash", "step_ends"]
