"""``single_touch_c1seek``: single_touch with the crank powered through J2's seek - it seeks up beside J2, as tview_v2's step 2 does.

Why (pass 7, 2026-11-13): on the real five-bar single_touch+gff homes 4/4, but in its "J2 seeks (C1 unpowered)" the limp crank swings at
up to 87.7 deg/s (home start; 77.5 on j2+4) as L1 lifts it - the fastest motion of the run, and outside the 86 deg/s runaway check, which
watches powered drives only. tview_v2+gff, run in the same session, powers C1 in that phase ("2. J2 + C1 seek together") and its crank
never moved faster than 1.1 deg/s while limp.

Why not simply HOLD C1 while J2 seeks (the first idea): the five-bar has two degrees of freedom, so it can - but from a near-home rest
(C1 ~92 deg) the loop does not close past J2 ~60-90 deg with the crank fixed (the comp's ``gravity_at_motors`` returns None from J2 90
on), so J2 would bind and "stall" far short of its stop. Seeking the crank up beside J2 lets the chain choose its pose, as tview's does.

So the one change: "J2 seeks (C1 unpowered)" becomes "J2 seeks (C1 seeking too)" - C1 seeks + with its own seek cap (7 N.m) and speed,
the step still ends on J2's ``Stall`` only (its evidence is unchanged: the J2 stall read at the end of this step). Then "C1 seeks (J2
pushing)" continues C1's seek to its stall, its define and everything after are single_touch's. And :func:`keep_c1_powered`: a crank
powered in one step is not let go in the next (behind the recovery its last step holds the crank; the procedure's "J1 holds" would drop it
for 0.3 s) - the same rule ``real_plant.keep_j2_powered`` applies to J2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from robot_models.homing.fit import fit
from robot_models.homing.protocols import Phase, Prior
from robot_models.homing.types import BacklashModel, BacklashTable, HomingResult, JointBacklash
from robot_msgs.control import JointCommand, JointCommandSequence

from .geometry import C1, DRIVES, J1, J2
from .procedures import SEEK_CAP_NM, SingleTouch, _hold, _seek, _step, step_ends

C1SEEK = "single_touch_c1seek"
J2_SEEK_OLD = "J2 seeks (C1 unpowered)"
J2_SEEK = "J2 seeks (C1 seeking too)"


@dataclass
class SingleTouchC1Seek(SingleTouch):
    """single_touch with C1 seeking beside J2 in J2's seek (module docstring)."""

    name: str = C1SEEK

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        sequence = super().plan(prior, so_far)
        if sequence is None:
            return None
        steps = []
        for step in sequence.steps:
            if step.name == J2_SEEK_OLD:
                step = _step(J2_SEEK, [_hold(J1), _seek(J2, +1, SEEK_CAP_NM[J2]), _seek(C1, +1, SEEK_CAP_NM[C1])], list(step.done_when),
                             timeout=step.timeout)
            steps.append(step)
        if not any(s.name == J2_SEEK for s in steps):
            raise ValueError(f"single_touch has no step {J2_SEEK_OLD!r} to change")
        return replace(sequence, steps=tuple(steps), name=sequence.name + ", C1 seeking beside J2")

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        # single_touch's observe with its J2 evidence read at the end of the renamed seek (the same reading: J2's stall)
        self.references = []
        ends = step_ends(phases[0])
        evidence = [self._evidence(0, ends[J2_SEEK], J2, +1),
                    self._evidence(0, ends["C1 seeks (J2 pushing)"], C1, +1),
                    self._evidence(0, ends["J1 seeks"], J1, +1)]
        stored = prior.table or BacklashTable(tuple(JointBacklash(j, BacklashModel("B0"), source="no stored table") for j in DRIVES))
        result = fit(evidence, prior.stops, table=stored)
        table = BacklashTable(tuple(JointBacklash(e.joint, e.model, False, False, "stored table (identify_backlash)")
                                    for e in stored.entries))
        return HomingResult(result.zeros, table, prior.stops, tuple(evidence), "kinematic")


def keep_c1_powered(sequence: JointCommandSequence) -> tuple[JointCommandSequence, list[str]]:
    """A step that would make C1 limp right after a step that powered it holds C1 instead (the previous step's cap and feed-forward);
    returns the sequence and the steps changed (module docstring)."""
    steps, changed = [], []
    previous = None
    for step in sequence.steps:
        if previous is not None:
            before = next((c for c in previous.commands if c.joint == C1), None)
            now = next((c for c in step.commands if c.joint == C1), None)
            if now is not None and now.mode == "limp" and before is not None and before.mode != "limp":
                hold = JointCommand.hold(C1, max_effort=float(before.max_effort), feedforward_effort=float(before.feedforward_effort or 0.0))
                step = replace(step, commands=tuple(hold if c.joint == C1 else c for c in step.commands))
                changed.append(step.name)
        steps.append(step)
        previous = step
    return replace(sequence, steps=tuple(steps)), changed


VARIANTS = {C1SEEK: SingleTouchC1Seek}

__all__ = ["C1SEEK", "J2_SEEK", "VARIANTS", "SingleTouchC1Seek", "keep_c1_powered"]
