"""The wrist's real rung, prepared offline (homing pass 7, 2026-11-13, rack on HOLD): wrist_real's RealWristPlant behind the homing seam,
the CAD self-contact detector live at every define, the wrist's home button (a robot_msgs JointCommandSequence to READY), CAN 14's gravity
feed-forward and the runaway stop - through the same ``real_plant.run_phase_real`` loop the five-bar's real runs use.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_wrist_real_1113.py

The plumbing tests use fakes (no MuJoCo); SIM2REAL_SLOW=1 adds the twin dry run of single_touch_park+gff through that path.
"""

from __future__ import annotations

import math
import os
from types import SimpleNamespace

import numpy as np
import pytest

from sim2real.sim.homing import wrist_real as wr

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
J14, J15, J16 = wr.JOINTS


class Map:
    """A self-contact map that touches where |CAN 14| and |CAN 15| are both past 106 deg (the real map's shape, wrist.SelfContactMap)."""

    def pairs(self, pose):
        return "hard_stop_3/base_plate" if abs(math.degrees(pose[J14])) >= 106 and abs(math.degrees(pose[J15])) >= 106 else ""


class Bus:
    """The rack plant's calls over a trivial plant: each drive goes to its setpoint in one tick; ``trip_at`` raises on that step."""

    def __init__(self, board_deg=(80.0, -38.0, 0.0), trip_at=None):
        self.q = np.radians(board_deg)
        self.sent, self.held, self.trip_at, self.steps, self.released = [], None, trip_at, 0, False

    def read(self):
        return SimpleNamespace(position_rad=self.q.copy(), velocity_rad_s=np.zeros(3), torque_nm=np.zeros(3), mode=(0, 0, 0))

    def send(self, commands):
        self.sent.append(list(commands))

    def step(self):
        self.steps += 1
        if self.trip_at is not None and self.steps >= self.trip_at:
            raise RuntimeError("CAN [15] did not reply: every wrist drive braked")
        for i, command in enumerate(self.sent[-1]):
            if command is not None:
                self.q[i] = command[0]
        return self.read()

    holding = False
    braked = False

    def hold_here(self, reason):
        self.held = reason

    def release(self):
        self.released = True
        return {"released": True}


def _plant(bus):
    return wr.RealWristPlant(bus, make_command=lambda position, feedforward, cap: (position, feedforward, cap))


def test_the_guard_judges_keeping_defines_and_never_a_working_one():
    guard = wr.SelfContactGuard(Map())
    plant = SimpleNamespace(drive_joints=wr.JOINTS, ticks=0, raw=lambda j: {J14: math.radians(10.0), J15: math.radians(5.0), J16: 0.0}[j])
    assert guard.check(plant, {J15: math.radians(120.0)}, "CAN 15 park touch") is None  # a working frame: never judged, never kept
    assert guard.check(plant, {J16: 0.0}, "CAN 16 seeks") is None
    # CAN 14's define puts it at 115 deg; CAN 15's keeping define then claims a pose 125 / 120 deg: both past 106 -> the holder in the plate
    assert guard.check(plant, {J14: math.radians(115.0)}, "CAN 14 seeks") is None  # CAN 15 has no keeping frame yet: nothing judged
    refused = guard.check(plant, {J15: math.radians(115.0)}, "CAN 15 seeks")
    assert refused and "pressed a link, not its stop" in refused and "hard_stop_3/base_plate" in refused
    assert guard.checks[-1]["pass"] is False and guard.checks[0]["working"] is True


def test_the_home_button_walks_can_14_fed_in_4_degree_waypoints_in_the_board_frame():
    from sim2real.sim.homing.wrist_gff import WristGravityComp

    comp = WristGravityComp()
    rest = {J14: math.radians(10.0), J15: math.radians(-38.0), J16: math.radians(20.0)}
    target = {j: math.radians(v) for j, v in wr.READY_DEG.items()}
    offset = {J14: math.radians(3.74), J15: 0.0, J16: math.radians(-1.0)}
    sequence = wr.recovery_sequence(rest, target, offset, (15, 14, 16), comp=comp)
    moves = [(s, c) for s in sequence.steps for c in s.commands if c.mode == "position"]
    q14 = [math.degrees(c.position + offset[J14]) for s, c in moves if c.joint == J14]
    assert len(q14) == math.ceil((86.0 - 10.0) / 4.0) and q14[-1] == pytest.approx(86.0)
    assert max(abs(b - a) for a, b in zip([10.0] + q14, q14, strict=False)) <= 4.0 + 1e-9
    for step, command in moves:
        if command.joint == J14:
            assert command.feedforward_effort != 0.0 and abs(command.feedforward_effort) <= wr.RECOVERY_CAP_NM
    pose14 = math.radians(10.0)
    for step in sequence.steps:
        moving14 = [c for c in step.commands if c.joint == J14 and c.mode == "position"]
        for hold in (c for c in step.commands if c.joint == J14 and c.mode == "hold"):
            assert hold.feedforward_effort == pytest.approx(comp.at(pose14)), step.name  # CAN 14 held with its gravity where it is
        if moving14:
            pose14 = moving14[0].position + offset[J14]
    order = [c.joint for _, c in moves]
    assert order.index(J15) < order.index(J14) < order.index(J16)
    assert sequence.steps[-1].name == "recover: hold at the target"


def test_the_home_button_takes_the_first_order_the_cad_map_clears():
    rest = {J14: math.radians(120.0), J15: math.radians(106.2), J16: 0.0}  # on the band's edge: touching, clear within 3 deg of CAN 15
    ready = {j: math.radians(v) for j, v in wr.READY_DEG.items()}
    order, rejected = wr.recovery_order(rest, ready, Map())
    assert order is not None and order[0] in (14, 15)
    assert wr.path_contacts(rest, ready, order, Map()) == []


def test_the_plant_frames_host_side_and_sends_a_limp_drive_as_none():
    from robot_msgs.control import ServoCommand

    bus = Bus()
    plant = _plant(bus)
    plant.reset(None)
    command = ServoCommand(name=wr.JOINTS, position=np.array([math.radians(30.0), math.nan, 0.0]),
                           max_effort=np.array([1.0, 0.0, 1.0]), feedforward_effort=np.array([0.2, 0.0, 0.0]))
    plant.tick(command, wr.DT, {J14: math.radians(90.0)})
    assert plant.frame[J14] == pytest.approx(math.radians(10.0))  # CAD 90 where the board read 80
    sent = bus.sent[-1]
    assert sent[1] is None and sent[0][0] == pytest.approx(math.radians(20.0)) and sent[0][1:] == (0.2, 1.0)


def test_a_bus_trip_stops_the_sequence_as_a_trip_and_the_home_button_does_not_take_over_a_brake():
    from robot_msgs.control import Elapsed, JointCommand, JointCommandSequence, JointCommandStep

    from sim2real.sim.homing.real_plant import SequenceStopped, run_phase_real

    bus = Bus(trip_at=3)
    plant = _plant(bus)
    plant.reset(None)
    sequence = JointCommandSequence(joint_names=wr.JOINTS, steps=(JointCommandStep(
        name="hold", commands=tuple(JointCommand.hold(j, max_effort=1.0) for j in wr.JOINTS), done_when=(Elapsed(duration=1.0),), timeout=5.0),),
        name="t")
    with pytest.raises(SequenceStopped) as stopped:
        run_phase_real(plant, sequence, dt=wr.DT, is_trip=lambda error: "braked" in str(error))
    assert stopped.value.kind == "trip"
    bus.braked = True
    record = wr.run_recovery(plant, {j: 0.0 for j in wr.JOINTS}, contact_map=Map())
    assert record["release"]["released"] is False and not bus.released


def test_the_twin_plant_trips_a_powered_runaway():
    pytest.importorskip("mujoco")
    from sim2real.sim.homing import wrist

    if not wrist.available():
        pytest.skip("bam_ws's bam_ur_wrist is not on disk")
    plant = wrist.WristPlant(runaway_rad_s=0.01)  # a ceiling any powered motion passes
    start = wrist.starts(wrist.WristRig.get(), 1)[0]
    plant.reset(start)
    from robot_msgs.control import ServoCommand

    from sim2real.sim.homing.plant import PlantTrip

    command = ServoCommand(name=tuple(plant.joint_names), position=np.array([plant.state().position[0] + 1.0, math.nan, math.nan]),
                           max_effort=np.array([1.0, 0.0, 0.0]), feedforward_effort=np.zeros(3))
    with pytest.raises(PlantTrip, match="runaway: CAN 14"):
        for _ in range(200):
            plant.tick(command, wr.DT)


@pytest.mark.skipif(not SLOW, reason="the twin dry run of one start (~3 min); SIM2REAL_SLOW=1")
def test_the_twin_dry_run_homes_through_the_real_path_as_the_mujoco_rung_did():
    result = wr.run_twin_homing("single_touch_park+gff", ["real_power_up"], mujoco_json=wr.Path(wr.__file__).resolve().parents[2]
                                / "data" / "homing_wrist_mujoco_pass5_2026-11-12.json")
    (episode,) = result["episodes"]
    assert episode["finished"] and episode["incident"] is None
    assert all(c["pass"] for c in episode["guard_checks"])
    assert max(abs(v) for v in episode["dryrun_minus_mujoco_deg"].values()) < 1e-3
    assert episode["home_button"]["result"] == "at target" and episode["home_button"]["release"]["released"]
