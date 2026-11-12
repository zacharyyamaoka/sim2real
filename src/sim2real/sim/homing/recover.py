"""recover_first: bam_fivebar_recovery's blind recovery in front of any homing procedure, as a prefix of its JointCommandSequence.

The decision report's B puts "recover_first in front" of ``home()`` so a start on the other assembly (the flipped crank) or a fold still
reaches its stops. The recovery is reused, not rewritten: ``data/fivebar_blind_recovery_v11.json`` is ``blind_recovery``'s own sequence
(steps 1-7, its two references set to the v11 CAD's), exported by ``recovery_export.py`` under bam_fivebar_recovery's environment. Here it
is only re-addressed to the bench's drives and prefixed:

* ``j2`` -> J2 (revolute_6), ``c1`` -> C1 (revolute_7), same numbers (Craig = URDF + offset, sign +1 for both on bundle 8957130); J1 holds
  through the whole prefix (the procedures' own J1 hold, 7 N.m), as every procedure's first step does;
* the step names get a ``recover:`` prefix, so a procedure's ``step_ends`` still finds its own steps by name;
* the prefix's defines are harmless: every procedure defines every drive it zeroes after it, and ``final_frame`` / ``step_ends`` take
  each define back out (the last define of a joint is the one that counts).

``RecoverFirst(inner)`` is a procedure: ``plan`` returns ONE sequence, the prefix then ``inner``'s; ``observe`` is ``inner``'s. The time to
home includes the recovery (the bench's tick clock runs from the first command).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from robot_models.homing.protocols import Phase, Prior
from robot_models.homing.types import HomingResult
from robot_msgs.control import JointCommand, JointCommandSequence, JointCommandStep

from .geometry import C1, DRIVES, J1, J2
from .procedures import HOLD_CAP_NM, PROCEDURES, Procedure

RECOVERY_JSON = Path(__file__).resolve().parents[2] / "data" / "fivebar_blind_recovery_v11.json"
RENAME = {"j2": J2, "c1": C1}
PREFIX = "recover: "
RECOVER_PREFIX_NAME = "recover_first+"  # a wrapped procedure's leaderboard name: recover_first+<name>


def load_recovery(path: Path = RECOVERY_JSON) -> tuple[JointCommandSequence, dict]:
    """The exported blind recovery (robot_msgs sequence on ``j2`` / ``c1``) and its provenance."""
    payload = json.loads(Path(path).read_text())
    return JointCommandSequence.from_dict(payload["sequence"]), {k: v for k, v in payload.items() if k != "sequence"}


def _readdress(command: JointCommand) -> JointCommand:
    return JointCommand(joint=RENAME[command.joint], mode=command.mode, position=command.position, distance=command.distance,
                        speed=command.speed, max_effort=command.max_effort, feedforward_effort=command.feedforward_effort)


def _condition(item):
    from dataclasses import replace  # noqa: PLC0415

    if hasattr(item, "joint"):
        return replace(item, joint=RENAME[item.joint])
    if hasattr(item, "joints"):
        return replace(item, joints=tuple(RENAME[j] for j in item.joints))
    return item


def recovery_steps(recovery: JointCommandSequence) -> tuple[JointCommandStep, ...]:
    """The recovery's steps on the bench's drives (module docstring), J1 held."""
    out = []
    for step in recovery.steps:
        commands = tuple(_readdress(c) for c in step.commands) + (JointCommand.hold(J1, max_effort=HOLD_CAP_NM[J1]),)
        out.append(JointCommandStep(name=PREFIX + step.name, commands=commands, done_when=tuple(_condition(c) for c in step.done_when),
                                    timeout=step.timeout, define_position={RENAME[j]: v for j, v in step.define_position.items()}))
    return tuple(out)


def with_prefix(prefix: Sequence[JointCommandStep], sequence: JointCommandSequence, *, max_speed: float | None = None) -> JointCommandSequence:
    """``prefix`` then ``sequence``'s steps, one sequence. WHY one sequence and not two phases: the brief's API is a prefix, and the
    real runner sends one sequence to one controller (no hand-off between them on the bus)."""
    names = [s.name for s in prefix] + [s.name for s in sequence.steps]
    if len(names) != len(set(names)):
        raise ValueError("a prefixed sequence needs unique step names")
    speed = sequence.max_speed if max_speed is None else min(max_speed, sequence.max_speed)
    return JointCommandSequence(joint_names=DRIVES, steps=tuple(prefix) + tuple(sequence.steps), name=f"recover_first + {sequence.name}",
                                max_speed=speed)


@dataclass
class RecoverFirst(Procedure):
    """``inner`` with the blind recovery in front (module docstring)."""

    inner: Procedure = None
    recovery_path: Path = RECOVERY_JSON
    provenance: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.inner is None:
            raise ValueError("RecoverFirst needs an inner procedure")
        self.name = RECOVER_PREFIX_NAME + self.inner.name

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        if so_far:
            return None
        recovery, self.provenance = load_recovery(self.recovery_path)
        inner = self.inner.plan(prior, [])
        return with_prefix(recovery_steps(recovery), inner, max_speed=recovery.max_speed)

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        result = self.inner.observe(prior, phases)
        self.references = self.inner.references
        self.notes.update(self.inner.notes)
        return result


def recover_first(name: str) -> RecoverFirst:
    """A leaderboard procedure by name with the recovery in front."""
    return RecoverFirst(inner=PROCEDURES[name]())


__all__ = ["PREFIX", "RECOVERY_JSON", "RECOVER_PREFIX_NAME", "RecoverFirst", "load_recovery", "recover_first", "recovery_steps", "with_prefix"]
