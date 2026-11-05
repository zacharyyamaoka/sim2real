"""UR5e + Robotiq 2F-85: the arm, the tool it carries (mass, centre of mass, TCP) and the gripper's drive (sysid.arm does the work)."""

from __future__ import annotations

from sysid import arm
from sysid import world as hidden

EXAMPLE = "ur5e_2f85"
GRIPPER = True


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
    """Kinematics (joint zeros, TCP), then the joint dynamics with the tool's mass and centre of mass, then the gripper's drive."""
    return arm.identify_example(description, measurements, gripper=GRIPPER)


def score(description, plan_, fit, measured, *, workers: int = 6) -> dict:
    return arm.score_example(description, plan_, fit, measured, gripper=GRIPPER)


def assemble(description, plan_, fit, scores, *, truth: dict) -> dict:
    return arm.assemble_example(EXAMPLE, description, plan_, fit, scores, truth, gripper=GRIPPER)
