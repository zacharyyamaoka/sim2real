"""The real rung's plant seam (real_plant): J1 held, J2 never let go under load, frames and commands on a stand-in bus, the stall gate,
the runaway hold, and an abort that never sends a limp arm. Pure: no bus, no MuJoCo, no bam_ws.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_real_plant.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pytest
from robot_msgs.control import Elapsed, JointCommand, JointCommandSequence, JointCommandStep, Reached, Settled, Stall

from sim2real.sim.homing.geometry import C1, DRIVES, J1, J2
from sim2real.sim.homing.real_plant import (
    RUNAWAY_RAD_S,
    STALL_BOARD_DEG,
    RealRigPlant,
    SequenceStopped,
    StopGuard,
    hold_j1,
    keep_j2_powered,
    run_phase_real,
)


@dataclass
class Reading:
    position_rad: np.ndarray
    velocity_rad_s: np.ndarray
    torque_nm: np.ndarray
    mode: tuple = (0, 0)
    j1_rad: float = 0.01


@dataclass
class StandInBus:
    """BusPlant's calls: each drive's board angle follows its position command at once (a stiff stand-in), STOP leaves it."""

    board: list = field(default_factory=lambda: [math.radians(-10.0), math.radians(5.0)])
    sent: list = field(default_factory=list)
    j1: list = field(default_factory=list)
    holds: list = field(default_factory=list)
    holding: bool = False
    braked: bool = False
    speed: float = 0.0
    pending: list = field(default_factory=lambda: [None, None])

    def read(self):
        return Reading(np.array(self.board), np.array([self.speed, 0.0]), np.zeros(2))

    def send(self, commands):
        self.pending = list(commands)
        self.sent.append(list(commands))

    def step(self):
        for axis, command in enumerate(self.pending):
            if command is not None:
                self.board[axis] = command[0]
        return self.read()

    def send_j1(self, command):
        self.j1.append(command)

    def hold_here(self, reason):
        self.holds.append(reason)
        self.holding = True


def make(position_rad, feedforward_nm, cap_nm):
    return (position_rad, feedforward_nm, cap_nm)


def _seq(*steps):
    return JointCommandSequence(joint_names=DRIVES, steps=tuple(steps))


def test_hold_j1_holds_j1_drops_its_conditions_and_defines():
    step = JointCommandStep(name="J1 seeks", commands=(JointCommand.move_by(J1, 10.0, speed=0.6, max_effort=10.0),
                                                       JointCommand.hold(J2, max_effort=10.0), JointCommand.limp(C1)),
                            done_when=(Stall(joint=J1),), timeout=40.0, define_position={J1: 1.5, J2: 2.0})
    reach = JointCommandStep(name="home", commands=(JointCommand.to(J1, 0.0, speed=0.6, max_effort=7.0),
                                                    JointCommand.to(J2, 0.0, speed=0.6, max_effort=10.0), JointCommand.limp(C1)),
                             done_when=(Reached(joints=DRIVES, tolerance=0.05), Settled(joints=(J1,), speed=0.1, dwell=0.1)), timeout=40.0)
    out = hold_j1(_seq(step, reach))
    first, second = out.steps
    assert next(c for c in first.commands if c.joint == J1).mode == "hold"
    assert first.done_when == (Elapsed(duration=0.05),) or isinstance(first.done_when[0], Elapsed)
    assert J1 not in first.define_position and first.define_position[J2] == 2.0
    assert first.name == "J1 seeks"  # the procedure's observe finds its steps by name
    assert second.done_when[0].joints == (J2, C1) and len(second.done_when) == 1  # the J1-only Settled dropped


def test_keep_j2_powered_turns_a_limp_after_power_into_a_hold():
    up = JointCommandStep(name="J2 to 120", commands=(JointCommand.to(J2, 2.1, speed=0.6, max_effort=10.0, feedforward_effort=1.5),
                                                       JointCommand.hold(C1, max_effort=6.0)), done_when=(Elapsed(duration=1.0),), timeout=40.0)
    limp = JointCommandStep(name="J1 holds", commands=(JointCommand.limp(J2), JointCommand.limp(C1)), done_when=(Elapsed(duration=0.3),), timeout=40.0)
    first = JointCommandStep(name="recover: limp", commands=(JointCommand.limp(J2), JointCommand.limp(C1)), done_when=(Elapsed(duration=3.0),), timeout=40.0)
    out, changed = keep_j2_powered(_seq(first, up, limp))
    assert changed == ["J1 holds"]
    assert next(c for c in out.steps[0].commands if c.joint == J2).mode == "limp"  # from a rest: untouched
    held = next(c for c in out.steps[2].commands if c.joint == J2)
    assert held.mode == "hold" and held.max_effort == 10.0 and held.feedforward_effort == 1.5
    assert next(c for c in out.steps[2].commands if c.joint == C1).mode == "limp"  # the crank may still go limp


def test_plant_frames_signs_and_commands():
    bus = StandInBus()
    plant = RealRigPlant(bus, make_command=make, j1_command=lambda j1: ("hold", j1), signs=(-1.0, 1.0))
    state = plant.reset(None)
    assert bus.j1 == [("hold", 0.01)]
    assert state.position[DRIVES.index(J2)] == pytest.approx(math.radians(10.0))  # sign -1
    assert state.position[DRIVES.index(C1)] == pytest.approx(math.radians(5.0))
    from robot_msgs.control import ServoCommand

    command = ServoCommand(name=DRIVES, position=np.array([0.0, math.radians(125.0), math.nan]), velocity=np.zeros(3),
                           max_effort=np.array([7.0, 10.0, 0.0]), feedforward_effort=np.array([0.0, 2.0, 0.0]))
    plant.tick(command, 0.01, {J2: math.radians(125.0)})
    j2, c1 = bus.sent[-1]
    assert c1 is None  # limp: STOP
    # defined 125 deg where the joint read 10 deg: the setpoint 125 deg is the board where it was (-10 deg), ff in the board's sign
    assert j2[0] == pytest.approx(math.radians(-10.0)) and j2[1] == pytest.approx(-2.0) and j2[2] == 10.0
    assert plant.state().position[DRIVES.index(J2)] == pytest.approx(math.radians(125.0))
    assert plant.time == pytest.approx(0.01)  # the tick clock


def test_a_define_off_its_stop_is_refused_and_held():
    bus = StandInBus(board=[math.radians(STALL_BOARD_DEG[J2] + 3.0), math.radians(STALL_BOARD_DEG[C1])])
    plant = RealRigPlant(bus, make_command=make, signs=(-1.0, 1.0))
    plant.reset(None)
    step = JointCommandStep(name="define", commands=(JointCommand.hold(J2, max_effort=10.0), JointCommand.hold(C1, max_effort=7.0)),
                            done_when=(Elapsed(duration=0.02),), define_position={J2: 2.18, C1: 3.45}, timeout=40.0)
    with pytest.raises(SequenceStopped) as stop:
        run_phase_real(plant, _seq(step, step.__class__(name="after", commands=step.commands, done_when=(Elapsed(duration=1.0),), timeout=40.0)),
                       guard=StopGuard())
    assert stop.value.kind == "stall_gate" and bus.holds
    assert "J2 +3.00 deg" in str(stop.value)


def test_the_recovery_define_is_not_gated_but_the_procedures_are():
    bus = StandInBus(board=[math.radians(STALL_BOARD_DEG[J2] + 3.7), math.radians(STALL_BOARD_DEG[C1] - 30.0)])
    plant = RealRigPlant(bus, make_command=make, signs=(-1.0, 1.0))
    plant.reset(None)
    guard = StopGuard()
    assert guard.check(plant, {J2: 2.18, C1: 3.45}, "recover: C1 + until the hub meets L1's plate") is None
    refused = guard.check(plant, {J2: 2.18, C1: 3.45}, "C1 seeks (J2 pushing)")
    assert refused is not None and "J2 +3.70" in refused and "C1 -30.00" in refused


def test_an_abort_holds_and_never_sends_the_limp_command():
    bus = StandInBus()
    plant = RealRigPlant(bus, make_command=make, signs=(-1.0, 1.0))
    plant.reset(None)
    step = JointCommandStep(name="never", commands=(JointCommand.hold(J2, max_effort=10.0), JointCommand.hold(C1, max_effort=7.0)),
                            done_when=(Stall(joint=J2),), timeout=0.05)
    sent_before = len(bus.sent)
    with pytest.raises(SequenceStopped) as stop:
        run_phase_real(plant, _seq(step))
    assert stop.value.kind == "aborted" and bus.holds
    assert all(cmd is not None for row in bus.sent[sent_before:] for cmd in row)  # every tick sent was a hold, never a STOP


def test_a_powered_runaway_is_held():
    bus = StandInBus(speed=RUNAWAY_RAD_S + 0.1)
    plant = RealRigPlant(bus, make_command=make, signs=(-1.0, 1.0))
    plant.reset(None)
    step = JointCommandStep(name="hold", commands=(JointCommand.hold(J2, max_effort=10.0), JointCommand.limp(C1)),
                            done_when=(Elapsed(duration=1.0),), timeout=40.0)
    with pytest.raises(SequenceStopped) as stop:
        run_phase_real(plant, _seq(step))
    assert stop.value.kind == "runaway" and bus.holds


def test_a_limp_drive_is_not_a_runaway():
    bus = StandInBus(speed=RUNAWAY_RAD_S + 0.1)
    plant = RealRigPlant(bus, make_command=make, signs=(-1.0, 1.0))
    plant.reset(None)
    step = JointCommandStep(name="limp", commands=(JointCommand.limp(J2), JointCommand.limp(C1)), done_when=(Elapsed(duration=0.05),), timeout=40.0)
    peaks = {}
    phase = run_phase_real(plant, _seq(step), peaks=peaks)
    assert phase.status == "done" and not bus.holds
    assert peaks[("limp", "J2", "limp")] == pytest.approx(RUNAWAY_RAD_S + 0.1)
