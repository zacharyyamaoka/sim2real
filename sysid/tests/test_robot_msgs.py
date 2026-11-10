"""The oracle's measured runs are robot_msgs trajectories (2026-11-10, the robot_msgs migration; Zach: every package depends on robot_msgs).

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/sysid/tests/test_robot_msgs.py

Behaviour is held by test_oracle.py's test_the_committed_result_is_this_code (every example re-run against its committed result); held
here is the shape: the arm's excitations are JointTrajectory (encoder q, qd, joint torque, the command a channel) beside the tracker's
flange (and TCP) positions, and the conveyor's runs are the roller encoder and the belt tracker, each a JointTrajectory, whose tracker
rows are the encoder's own samples (no interpolation).
"""

from __future__ import annotations

import numpy as np
from robot_msgs.trajectory import JointTrajectory, Trajectory


def test_the_arms_excitations_are_joint_trajectories():
    from sysid import arm, describe, world  # noqa: PLC0415

    description = describe.load("ur5e")
    plan = arm.plan(description, gripper=False)
    truth = world.load("ur5e")
    model = arm.ArmModel.build(description)
    measured = arm.measure(model, truth["truth"], truth["noise"], truth["seed"], plan.poses_train[:1], plan.trajectories("train")[:1], label="train")
    (excitation,), (tracker,) = measured.excitations, measured.trackers
    command = plan.trajectories("train")[0]
    assert isinstance(excitation, JointTrajectory) and excitation.joint_names == arm.JOINTS
    assert excitation.positions.shape == excitation.velocities.shape == excitation.effort.shape == command.shape
    assert np.array_equal(excitation.channels["command"], command) and np.allclose(np.diff(excitation.t), arm.DT)
    assert type(tracker) is Trajectory and set(tracker.channels) == {"flange_p"}
    assert tracker.channels["flange_p"].shape == (len(excitation.t[::arm.TRACKER_EVERY]), 3)
    assert np.array_equal(tracker.t, excitation.t[::arm.TRACKER_EVERY])


def test_the_conveyors_runs_are_the_encoder_and_the_tracker():
    from sysid import describe  # noqa: PLC0415
    from sysid.examples.conveyor import pipeline as conveyor  # noqa: PLC0415

    description = describe.load("conveyor")
    plan = conveyor.plan(description)
    plan.train, plan.held_out = plan.train[:1], []
    (run,) = conveyor.RealWorld(description).measure(plan).train
    assert isinstance(run.encoder, JointTrajectory) and run.encoder.joint_names == ("drive_roller",)
    assert isinstance(run.tracker, JointTrajectory) and run.tracker.joint_names == ("belt",)
    assert np.array_equal(run.command, plan.train[0])
    assert np.array_equal(run.tracker.t, run.encoder.t[:: conveyor.TRACKER_EVERY])
    # the tracker's rows are the encoder's samples: theta_at_track is a view of them, bit for bit
    assert np.array_equal(run.theta_at_track, run.encoder[:: conveyor.TRACKER_EVERY].positions[:, 0])
