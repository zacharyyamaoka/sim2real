"""UR5e: Menagerie's arm as it ships in, this arm's joint zeros and joint servo dynamics out (sysid.arm does the work)."""

from __future__ import annotations

from sysid import arm
from sysid import world as hidden

EXAMPLE = "ur5e"
GRIPPER = False


def plan(description) -> arm.ArmPlan:
    return arm.plan(description, gripper=GRIPPER)


class RealWorld:
    """The arm at world.json's joint zeros, reflected inertias and friction, through the encoders, the torque and the tracker."""

    def __init__(self, description, *, workers: int = 6):
        self.description = description
        doc = hidden.load(EXAMPLE)
        self.truth, self.noise, self.seed = doc["truth"], doc["noise"], doc["seed"]

    def measure(self, plan_: arm.ArmPlan) -> arm.Measured:
        return arm.measure_example(self.description, plan_, self.truth, self.noise, self.seed, gripper=GRIPPER)


def identify(description, measurements: arm.ArmMeasured) -> arm.ArmFit:
    """Kinematics (joint zero offsets), then each joint's reflected inertia, viscous and Coulomb friction."""
    return arm.identify_example(description, measurements, gripper=GRIPPER)


def score(description, plan_, fit, measured, *, workers: int = 6) -> dict:
    return arm.score_example(description, plan_, fit, measured, gripper=GRIPPER)


def assemble(description, plan_, fit, scores, *, truth: dict) -> dict:
    return arm.assemble_example(EXAMPLE, description, plan_, fit, scores, truth, gripper=GRIPPER)
