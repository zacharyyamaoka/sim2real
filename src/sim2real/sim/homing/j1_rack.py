"""MOTION: J1's home on the REAL full arm (bam_fb_v2, CAN 11) - the routine's own two J1 steps (``j1_home``: the bytes the twin was scored
on, run by robot_msgs' ``JointCommandSequenceController``), in ONE process, done on ``EffortStall``, and J1's zero written only through
``bam_rack_twin.hardware.zero_writer`` (``shift --joint J1``; its commit is ``homed_history.write_latest``, the one writer of latest.json).

WHY (the coordinator, 2026-11-14, with the Sim to Real Agent): every real J1 home runs the routine, not a scratch tool - j1_seek_min's own seek
was not the routine's, and its second touch could never stall (its 30 deg travel gate) - on the deployment tree ~/bam_ws-armhold, from the
next power-up on.

    cd ~/bam_ws-armhold/src/dev/bam_rack_twin
    # files only, nothing opened: the checks, the sequence, the witness, and what a stall at the expected stop would write
    env -u VIRTUAL_ENV uv run --no-sync python -m sim2real.sim.homing.j1_rack --dry-run
    # the J1 twin: this loop on a stand-in J1 (the rack's gains, its gravity curve, friction, the stop); the zero goes into a COPY of homed/
    env -u VIRTUAL_ENV uv run --no-sync python -m sim2real.sim.homing.j1_rack --twin --out /tmp/j1_rack_twin
    # the real run: a transient service at powered priority (powered_launch fills {stamp} and {out})
    env -u VIRTUAL_ENV uv run --no-sync python -m bam_rack_twin.hardware.powered_launch j1-home /archive/datasets/bam_rig/full_arm/j1_home_{stamp} -- -m sim2real.sim.homing.j1_rack --allow-motion --out {out}

The real run, in order (every rack piece is bam_rack_twin.hardware's, never re-made here):

1. **Refused before anything opens:** no ``--allow-motion`` or ``--out`` (an existing folder too); the rack's HOLD marker; latest.json's
   revolute_3 without a sign whose status says "confirmed" (the two stops alias 5 rotor turns apart, so only the sign tells them apart); J2 / C1
   / the wrist / the claw not homed since their boards' last power-up (``fullarm_stops.check_homed``); no READY record; not at powered priority
   (``keep_fed``); the adapter enumerated under ``USB_QUIET_S`` ago.
2. **The bus:** ``systemctl --user stop arm-hold`` (j1_nudge's hand-over), the bus lock, the port check, every board answering and sane
   (``preflight_boards``), then the FAST take-over from arm-hold's hand-off record (``handoff_power``: the boards are held at the targets
   arm-hold left, so C1 does not sag), the five-bar on the full arm's comp, the wrist and claw held. ``J1HomeBus`` is fullarm_stops'
   ``StopsBus`` (HeldBus's guards: faults, mode 11, the voltage, J1 off its hold, the drives' tracking; the measured-pose belt guard) with J1's
   ceiling raised from J1_HOLD_NM to each step's own cap (11 N.m seek, 17.98 return) - the one change j1_seek_min's SeekBus also made.
3. **The homing posture:** every joint but J1 walked to the named pose "homing" (``homing_start_q``; READY's record until READY moved
   on 2026-11-19) by ``fullarm_stops.route_to_start`` when it is off by more than the tolerance (Zach:
   runners route, they do not refuse a pose); J1 is not routed - its frame is what this run establishes. **The measured cell, fail closed**
   (2026-11-22, after the 17:57Z seek hit the right flood lamp): the seek to the stop and its return leg are judged against
   ``fullarm_stops.cell_judge`` (cell_frame.FULL_CELL_POSTS) from the planned posture BEFORE the route moves anything, the route itself with
   ``cell=``, and the seek again from the measured pose before step 4 (``route_and_judge``). A breach, or a deployment without the judge,
   is Refused with nothing moved, naming the member and the gap.
4. **J1's home:** the seek (-110 deg relative at 7.2 deg/s, cap 11 N.m) until EffortStall (still < 0.01 rad/s for 0.2 s while pushing the way
   it seeks past 9 N.m), which defines J1 = -89.972 deg; then back to the homing posture's -12.7 deg in that frame. J1 runs PID tuna's gains (j1_gains:
   kp x14 / kd x16.8, ilimit 0 - PD only) and J1's gravity fed forward EVERY tick at its joint angle in the best frame known: the map's when
   J1's board has not powered up since J1 was homed, else none until the stall defines the frame (a power-up shifts J1's board by whole rotor
   turns, and j1_gains' curve is in the frame of the 2026-11-14 home). A step that times out (no stall: a cap or feed-forward fault, the
   trap the rule exists for) or the sequence's own guard ends the home: J1 walks back to where it started and the run is refused. A bus
   guard (a fault, J1 off its hold, the belt) holds every board where it is (HeldBus.hold_here) and nothing more moves.
5. **The end:** every board held at the homing posture (the bring-up then walks the arm to READY: ``bam_robot_activity.runner --return-home``), the transport closed without a stop and arm-hold's targets written (HeldBus.close: arm-hold's
   restore ramps back to them), the bus lock released, arm-hold restarted.
6. **J1's zero, after the bus is closed** (file writes never inside a powered tick): the stall's board reading must sit on the stop's rotor
   phase (within WITNESS_TOL_DEG, mod one 36 deg turn, of the 05:41Z / 05:56Z stalls). Then the shift that puts the stall at -89.972: under
   CONFIRM_DEG nothing is written (the zero is confirmed); a sub-turn shift is written; a whole-turn shift only when J1's board powered up
   after J1's home (a power-up re-latches whole turns), else refused. A finished home (confirmed or shifted) then stamps J1's ``homed_utc``
   through ``homed_history.write_latest`` (``stamp_j1_homed``). ``--no-write`` prints zero_writer's plan and writes nothing.

Every angle a person reads is in degrees; the run folder gets ``report.json`` (also on a refusal or a crash) and the bus trace.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import os
import shutil
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robot_msgs.control import JointCommand, JointCommandSequence, JointCommandSequenceController, JointCommandStep
from robot_msgs.sensor import JointState
from robot_msgs.std import Header

from ... import paths as _paths
from ...named_poses import named_pose
from .j1_home import (
    J1,
    J1_JOINT_CAP_NM,
    J1_READY_RAD,
    J1_RETURN_SPEED,
    J1_SEEK_CAP_NM,
    J1_STOP_DEG,
    STEP_TIMEOUT_S,
    j1_home_sequence,
    reached_j1,
)

TAU = 2.0 * math.pi
DT = 0.01  # the bus's tick (HeldBus.control_period_s)
J1_CAN = 11
TURN_DEG = 36.0  # one rotor turn of the JMC 60ASM400's 1:10 at the output: what a power-up re-latches by
# WHY these two readings: the rack's two J1 homes on the stop (j1home_054105 / j1home3_055613, board -1.31529 / -1.31654, 0.07 deg apart, from
# two arm configurations) - the stop's rotor phase, which survives a power-up (the encoder is absolute within one rotor turn)
REFERENCE_STALL_BOARD_RAD = (-1.31529, -1.31654)
WITNESS_TOL_DEG = 0.5  # the routine's tight witness (RACK_WITNESS_TOL_DEG): the real stalls repeat within 0.07 deg
# WHY 0.1 deg, not zero_writer's 0.05 (2026-11-14): the stop gives under load - the rack's two stalls read 0.07 deg apart at 6.4 and 10.2 N.m
# (~3000 N.m/rad), and this seek presses at its 11 N.m cap, ~0.05-0.08 deg deeper than the map's mean of the two. Under 0.1 deg (the ruler's
# zero gate) a home confirms the map and writes nothing, so every re-home does not churn a new map and READY record out of the stop's give
CONFIRM_DEG = 0.1
FIT_ZERO_BOARD_RAD = 0.25439  # J1's zero when j1_gains' curve was fitted (its board frame): the curve's joint-frame argument is q + this
RECOVER_TIMEOUT_S = 40.0
START_TOLERANCE_DEG = 8.0  # fullarm_stops' runs (its default is 5; a hand-over droops C1 a few deg)
USB_QUIET_S = 30.0
DEPLOYMENT = Path.home() / "bam_ws-armhold" / "src" / "dev" / "bam_rack_twin"
# WHY through sim2real.paths (tests/test_paths.py): the same /archive/datasets/bam_rig/full_arm/homed on the workstation, a copy's on a VM
HOMED_DIR = _paths.RIG_DATA / "full_arm" / "homed"


# ---------------------------------------------------------------------------------------------------------------- J1's map and its zero


@dataclass(frozen=True)
class J1Map:
    """latest.json's revolute_3: joint(board) = joint_at_zero + sign x (board - zero_board), and when J1 was homed (epoch s or None)."""

    sign: float
    zero_board_rad: float
    joint_at_zero_rad: float
    homed_s: float | None
    sign_status: str = ""

    @classmethod
    def from_latest(cls, document: Mapping[str, Any]) -> J1Map:
        entry = (document.get("joints") or {}).get(J1)
        if not isinstance(entry, Mapping):
            raise ValueError(f"latest.json has no {J1}")
        return cls(sign=float(entry["sign"]), zero_board_rad=float(entry["zero_board_rad"]), joint_at_zero_rad=float(entry.get("joint_at_zero_rad", 0.0)),
                   homed_s=_stamp_seconds(entry.get("homed_utc") or document.get("stamp_utc")), sign_status=str(entry.get("sign_status", "")))

    def joint(self, board_rad: float) -> float:
        return self.joint_at_zero_rad + self.sign * (float(board_rad) - self.zero_board_rad)

    def board(self, joint_rad: float) -> float:
        return self.zero_board_rad + self.sign * (float(joint_rad) - self.joint_at_zero_rad)


def _stamp_seconds(text: Any) -> float | None:
    """A UTC stamp in the rack's spellings (power_up.stamp_seconds' forms) as epoch seconds."""
    if not text:
        return None
    for form in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H%M%SZ", "%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return dt.datetime.strptime(str(text), form).replace(tzinfo=dt.UTC).timestamp()
        except ValueError:
            continue
    return None


def wrap_turn_deg(value_deg: float) -> float:
    """``value_deg`` folded onto (-18, 18]: its distance from the nearest whole rotor turn."""
    return -(((-float(value_deg)) + TURN_DEG / 2.0) % TURN_DEG - TURN_DEG / 2.0)


def witness_deg(stall_board_rad: float, reference: Sequence[float] = REFERENCE_STALL_BOARD_RAD) -> float:
    """How far the stall's board reading sits from the stop's rotor phase (the real stalls' mean), mod one turn (deg)."""
    return wrap_turn_deg(math.degrees(float(stall_board_rad) - statistics.fmean(reference)))


def zero_decision(stall_board_rad: float, j1map: J1Map, *, powered_up_since_home: bool | None) -> dict[str, Any]:
    """What a stall at ``stall_board_rad`` does to J1's zero (module docstring, step 6): "confirmed" (nothing to write), "shift" (``deg`` for
    zero_writer), or "refused" with ``why``. ``powered_up_since_home``: J1's board powered up after the map's J1 home (None: unknown)."""

    stop = math.radians(J1_STOP_DEG)
    reading = j1map.joint(stall_board_rad)
    shift = math.degrees(stop - reading)
    turns = round(shift / TURN_DEG)
    out = {"stall_board_rad": float(stall_board_rad), "stall_deg_on_map": math.degrees(reading), "shift_deg": shift, "turns": int(turns),
           "witness_deg": witness_deg(stall_board_rad), "powered_up_since_home": powered_up_since_home}
    if abs(out["witness_deg"]) > WITNESS_TOL_DEG:
        return {**out, "verdict": "refused", "why": (f"the stall sits {out['witness_deg']:+.3f} deg off the stop's rotor phase (tolerance "
                                                     f"{WITNESS_TOL_DEG:g}): an obstacle or a short stall, not the -89.97 stop - nothing written")}
    if abs(shift) < CONFIRM_DEG:
        return {**out, "verdict": "confirmed", "why": f"the stall reads {shift:+.3f} deg from the map's stop: J1's zero confirmed, nothing written"}
    if turns != 0 and not powered_up_since_home:
        known = "J1's board has not powered up since its home" if powered_up_since_home is False else "J1's power-up time is unknown"
        return {**out, "verdict": "refused", "why": (f"a {turns:+d}-turn J1 shift ({shift:+.3f} deg) but {known}: only a power-up re-latches "
                                                     "whole turns - nothing written")}
    return {**out, "verdict": "shift", "why": f"J1's zero moves {shift:+.4f} deg ({turns:+d} whole turns + {shift - turns * TURN_DEG:+.4f})"}


# ---------------------------------------------------------------------------------------------------------------- the loop (any bus)


@dataclass
class TwinJ1Command:
    """The command the twin bus takes (TrajectoryCommand's attributes the loop sets)."""

    position_rad: float
    feedforward_torque_nm: float
    maximum_torque_nm: float
    kp_scale: float = 14.0
    kd_scale: float = 16.8
    ilimit_scale: float = 0.0
    velocity_rad_s: float = 0.0


@dataclass
class LoopRecord:
    """What one run of a sequence on J1 did (degrees where a person reads it)."""

    outcome: str = "running"  # done | timeout: ... | guard: ... | tripped: ...
    start_board_rad: float = math.nan
    stall_board_rad: float | None = None
    stall_effort_nm: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    peak_effort_nm: float = 0.0
    peak_speed_deg_s: float = 0.0
    ticks: int = 0
    feedforward: str = ""
    rows: list[list[float]] = field(default_factory=list)  # t_s, board_rad, velocity, torque, setpoint_board_rad, ff_nm, cap_nm


def j1_reading(bus) -> tuple[float, float, float]:
    """(board rad, rad/s, N.m) of J1 from the bus's last reading."""
    reading = bus.last
    board = reading.boards[J1_CAN]
    return float(reading.j1_rad), float(board["velocity"]), float(board["torque"])


def run_sequence(bus, j1map: J1Map, sequence: JointCommandSequence, *, make_command: Callable[[float, float, float], Any],
                 gravity_nm: Callable[[float], float], frame_known: bool, dt_s: float = DT, max_s: float | None = None,
                 say: Callable[[str], Any] = lambda text: print(text, flush=True)) -> LoopRecord:
    """Tick ``sequence`` (J1 only) on the bus until it is done, aborted, or the bus holds. Each tick: J1's state in the controller's frame
    (the map's, plus what a define added), the controller's setpoint back to a board angle, J1's gravity fed forward at its joint angle when
    the frame is known (``frame_known``, or from the define on), the step's own cap; then one bus step. A limp command (an abort) is NEVER
    sent: the caller recovers or the bus holds."""

    controller = JointCommandSequenceController(sequence)
    record = LoopRecord(start_board_rad=j1_reading(bus)[0], feedforward="map" if frame_known else "none until the stall defines the frame")
    frame = 0.0  # joint (controller) = j1map.joint(board) + frame
    known = bool(frame_known)
    limit_s = max_s if max_s is not None else sum(step.timeout for step in sequence.steps) + 5.0
    while True:
        board, velocity, torque = j1_reading(bus)
        state = JointState(name=(J1,), position=[j1map.joint(board) + frame], velocity=[j1map.sign * velocity], effort=[j1map.sign * torque],
                           header=Header(stamp=record.ticks * dt_s))
        command, defines = controller.tick(state, dt_s)
        if J1 in defines:
            frame = float(defines[J1]) - j1map.joint(board)
            known = True
            record.stall_board_rad, record.stall_effort_nm = board, torque
            say(f"J1 stall at board {board:+.5f} rad ({math.degrees(j1map.joint(board)):+.3f} deg on the map), effort {torque:+.2f} N.m: "
                f"defined {math.degrees(defines[J1]):+.3f} deg")
        for event in controller.events[len(record.events):]:
            record.events.append({"step": event.name, "outcome": event.outcome, "t_s": round(event.finished, 3)})
        if controller.status != "running":
            record.outcome = "done" if controller.status == "done" else controller.message
            break
        setpoint = float(command.position[0])
        cap = float(command.max_effort[0]) if command.max_effort is not None else 0.0
        if not math.isfinite(setpoint) or cap <= 0.0:
            record.outcome = f"limp command at tick {record.ticks}: refused to send it"
            break
        joint_now = j1map.joint(board) + frame
        ff = j1map.sign * gravity_nm(joint_now + FIT_ZERO_BOARD_RAD) if known else 0.0
        target_board = j1map.board(setpoint - frame)
        bus.j1_cap_nm = cap
        bus.send_j1(make_command(target_board, ff, cap))
        bus.step()
        record.ticks += 1
        record.peak_effort_nm = max(record.peak_effort_nm, abs(torque))
        record.peak_speed_deg_s = max(record.peak_speed_deg_s, abs(math.degrees(velocity)))
        record.rows.append([round(record.ticks * dt_s, 3), board, velocity, torque, target_board, ff, cap])
        if getattr(bus, "held", None) is not None:
            record.outcome = f"tripped: {bus.held.get('reason')}"
            break
        if record.ticks * dt_s > limit_s:
            record.outcome = f"timeout: the loop ran {limit_s:g} s"
            break
    return record


def return_sequence(start_joint_rad: float) -> JointCommandSequence:
    """J1 back to where the home began (its joint angle in the frame the run was in): the recovery after a refused seek."""
    step = JointCommandStep(name="J1 back to its start", commands=(JointCommand.to(J1, float(start_joint_rad), speed=J1_RETURN_SPEED,
                                                                                    max_effort=J1_JOINT_CAP_NM),),
                            done_when=tuple(reached_j1()), timeout=RECOVER_TIMEOUT_S, define_position={})
    return JointCommandSequence(joint_names=(J1,), steps=(step,), name="J1 recovery")


def home_j1(bus, j1map: J1Map, *, make_command, gravity_nm, frame_known: bool, say=lambda text: print(text, flush=True)) -> dict[str, Any]:
    """The routine's J1 home on ``bus`` (module docstring, step 4), with the recovery walk when the seek is refused. Returns the record."""

    ff_mid = gravity_nm(0.5 * (J1_READY_RAD + math.radians(J1_STOP_DEG)) + FIT_ZERO_BOARD_RAD) if frame_known else 0.0
    sequence = j1_home_sequence(feedforward_nm=ff_mid)
    say(f"J1 home: seek -110 deg at 7.2 deg/s, cap {J1_SEEK_CAP_NM:g} N.m, EffortStall 9 N.m -> define {J1_STOP_DEG} deg -> back to "
        f"{math.degrees(J1_READY_RAD):.1f} deg; feed-forward {'on the map' if frame_known else 'off until the stall'}")
    start_board = j1_reading(bus)[0]
    run = run_sequence(bus, j1map, sequence, make_command=make_command, gravity_nm=gravity_nm, frame_known=frame_known, say=say)
    out: dict[str, Any] = {"home": _public(run), "home_rows": run.rows}
    if run.outcome == "done":
        return out
    say(f"J1 home ended: {run.outcome}")
    if run.outcome.startswith("tripped") or getattr(bus, "held", None) is not None:
        out["recovery"] = "none: the bus holds every board where it is (its guard's call)"
        return out
    # WHY walk back (Zach 2026-11-13: recover, don't stop): a seek that never stalled stands somewhere on the sweep; J1 goes back to where it
    # began, in the frame it began in (no define happened, or the define is the one that frame then holds)
    back_map = j1map if run.stall_board_rad is None else _defined(j1map, run.stall_board_rad)
    back = run_sequence(bus, back_map, return_sequence(back_map.joint(start_board)), make_command=make_command, gravity_nm=gravity_nm,
                        frame_known=frame_known or run.stall_board_rad is not None, say=say)
    out["recovery"] = _public(back)
    out["recovery_rows"] = back.rows
    return out


def _defined(j1map: J1Map, stall_board_rad: float) -> J1Map:
    """``j1map`` moved so the stall reads the stop (the frame a define gave)."""
    shift = math.radians(J1_STOP_DEG) - j1map.joint(stall_board_rad)
    return J1Map(sign=j1map.sign, zero_board_rad=j1map.zero_board_rad, joint_at_zero_rad=j1map.joint_at_zero_rad + shift, homed_s=j1map.homed_s,
                 sign_status=j1map.sign_status)


def _public(record: LoopRecord) -> dict[str, Any]:
    out = {k: v for k, v in record.__dict__.items() if k != "rows"}
    out["start_board_rad"] = record.start_board_rad
    out["ticks"] = record.ticks
    return out


# ---------------------------------------------------------------------------------------------------------------- the J1 twin


class TwinJ1Bus:
    """A stand-in J1 on the bus's calls (``last`` / ``step`` / ``send_j1`` / ``held`` / ``hold_here`` / ``close``): one joint driven like the
    board drives it - PD at the command's kp / kd scales on J1's base gains (200 N.m/rev; kd for zeta ~0.7 at x14), its feed-forward, the
    cap - against J1's gravity (j1_gains' READY curve x ``gravity_scale``), Coulomb friction with stiction, a hard stop at ``stop_board_rad``
    (and an optional obstacle), at 1 kHz inside each 10 ms tick. The rest of the arm is not modelled: the real bus holds it.
    ``board_offset_rad`` puts the twin's board frame off the map's (a power-up's whole turns); ``cap_ceiling_nm`` is a board current limit
    under every command's cap (the low-cap seed)."""

    def __init__(self, *, gravity_nm: Callable[[float], float], start_joint_rad: float = J1_READY_RAD, map_zero_board_rad: float = FIT_ZERO_BOARD_RAD,
                 board_offset_rad: float = 0.0, gravity_scale: float = 1.0, friction_nm: float = 0.5, inertia: float = 0.13,
                 obstacle_joint_rad: float | None = None, stop_joint_rad: float = math.radians(J1_STOP_DEG), dt_s: float = DT,
                 cap_ceiling_nm: float = math.inf):
        self.gravity_nm, self.gravity_scale, self.friction_nm, self.inertia, self.dt = gravity_nm, gravity_scale, friction_nm, inertia, dt_s
        self.zero = map_zero_board_rad + board_offset_rad  # board = zero + joint (sign +1, joint_at_zero 0)
        self.stop, self.obstacle, self.cap_ceiling = stop_joint_rad, obstacle_joint_rad, float(cap_ceiling_nm)
        self.q, self.v, self.torque = float(start_joint_rad), 0.0, 0.0
        self.kp_base, self.kd_base = 200.0 / TAU, 1.4 * math.sqrt(14.0 * 200.0 / TAU * inertia) / 16.8 / 1.0
        self.command = TwinJ1Command(position_rad=self.zero + self.q, feedforward_torque_nm=0.0, maximum_torque_nm=7.0, kp_scale=1.0, kd_scale=1.0)
        self.held: dict[str, Any] | None = None
        self.j1_cap_nm = 7.0
        self.t = 0.0
        self.last = self._reading()

    def _reading(self):
        board = {"position": self.zero + self.q, "velocity": self.v, "torque": self.torque, "mode": 10, "fault": 0, "voltage": 36.0}
        return _TwinReading(t_s=self.t, j1_rad=self.zero + self.q, boards={J1_CAN: board})

    def send_j1(self, command) -> None:
        self.command = command

    def hold_here(self, reason: str) -> None:
        self.held = {"reason": reason}

    def step(self):
        c = self.command
        cap = min(float(c.maximum_torque_nm), float(self.j1_cap_nm), self.cap_ceiling)
        for _ in range(10):
            sub = self.dt / 10.0
            target = float(c.position_rad) - self.zero
            motor = (self.kp_base * c.kp_scale * (target - self.q) + self.kd_base * c.kd_scale * (getattr(c, "velocity_rad_s", 0.0) - self.v)
                     + float(c.feedforward_torque_nm))
            motor = max(-cap, min(cap, motor))
            gravity = -self.gravity_scale * self.gravity_nm(self.q + FIT_ZERO_BOARD_RAD)  # the hold torque, as a force on the joint
            wall = 0.0
            for limit in [x for x in (self.stop, self.obstacle) if x is not None]:
                if self.q < limit:  # both lie on the seek's side (-): the stop pushes back up
                    wall += 4000.0 * (limit - self.q) - 20.0 * min(self.v, 0.0)
            net = motor + gravity + wall
            if abs(self.v) < 1e-4 and abs(net) <= self.friction_nm:
                self.v, accel = 0.0, 0.0
            else:
                accel = (net - math.copysign(self.friction_nm, self.v if abs(self.v) >= 1e-4 else net)) / self.inertia
            self.v += accel * sub
            self.q += self.v * sub
            self.torque = motor
        self.t += self.dt
        self.last = self._reading()
        return self.last


@dataclass
class _TwinReading:
    t_s: float
    j1_rad: float
    boards: dict[int, dict[str, float]]


# ---------------------------------------------------------------------------------------------------------------- the rack (bam_rack_twin)


def load_j1_gains(root: Path = DEPLOYMENT):
    """bam_rack_twin.hardware.j1_gains (stdlib only): imported when the package is on the path, else loaded from ``root``'s file."""
    try:
        from bam_rack_twin.hardware import j1_gains  # noqa: PLC0415

        return j1_gains
    except ImportError:
        path = Path(root) / "bam_rack_twin" / "hardware" / "j1_gains.py"
        spec = importlib.util.spec_from_file_location("j1_gains_by_path", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def j1_home_bus(fs, home, plant):
    """fullarm_stops' StopsBus with J1's ceiling the step's own cap (``j1_cap_nm``) instead of J1_HOLD_NM, while nothing holds."""

    class J1HomeBus(fs.StopsBus):
        tool = "sim2real.j1_rack"
        j1_cap_nm = home.J1_HOLD_NM

        def _frames(self):
            frames = super()._frames()
            if self.held is None and self.j1 is not None:
                frames[home.J1_ID] = ("position", plant.command_kwargs(self.j1, min(float(self.j1_cap_nm), J1_JOINT_CAP_NM)))
            return frames

    return J1HomeBus


def powered_up_since(j1map: J1Map, power: Mapping[int, Mapping[str, Any]]) -> bool | None:
    """Whether J1's board powered up after the map's J1 home (None: either time unknown)."""
    stamp = (power.get(J1_CAN) or {}).get("stamp")
    if stamp is None or j1map.homed_s is None:
        return None
    return float(stamp) >= float(j1map.homed_s)


def preflight(arguments, *, rack) -> dict[str, Any]:
    """Every file check (module docstring, step 1). Returns what the run needs; Refused (the rack's) on any failure."""

    refused = rack.board.Refused
    homed_dir = Path(arguments.homed_dir)
    latest_path = homed_dir / "latest.json"
    latest = json.loads(latest_path.read_text())
    try:
        j1map = J1Map.from_latest(latest)
    except (KeyError, TypeError, ValueError) as error:
        raise refused(f"REFUSED: latest.json's {J1} is not readable ({error})") from None
    if "confirmed" not in j1map.sign_status:
        raise refused(f"REFUSED: J1's sign is not confirmed in latest.json ({j1map.sign_status!r}): the two stops alias 5 rotor turns apart, "
                      "so only the sign tells them apart")
    power = rack.power_up.power_ups(arguments.power_on_dir)
    fivebar = rack.fs.newest_fivebar_homed(homed_dir)
    homed = rack.fs.check_homed(fivebar, latest_path, power)
    ready_path = rack.zero_writer.newest_ready(rack.zero_writer.default_ready_root(homed_dir))
    ready = rack.zero_writer.ready_joints_rad(json.loads(Path(ready_path).read_text())["boards"], latest)
    since = powered_up_since(j1map, power)
    return {"latest": str(latest_path), "latest_stamp": latest.get("stamp_utc"), "j1_map": j1map.__dict__, "fivebar_homed": str(fivebar),
            "homed": homed, "ready_record": str(ready_path), "ready_deg": {k: math.degrees(v) for k, v in ready.items()}, "ready_rad": ready,
            "power_up_j1": power.get(J1_CAN), "powered_up_since_j1_home": since,
            "j1_frame": ("the map's (J1's board has not powered up since its home)" if since is False else
                         "unknown until the stall (J1's board powered up since its home, or a time is missing): feed-forward off until the define"),
            "_j1map": j1map, "_power": power}


class Rack:
    """bam_rack_twin.hardware's modules, imported once from the deployment tree (the run's own path, or ~/bam_ws-armhold)."""

    def __init__(self, root: Path = DEPLOYMENT):
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from bam_rack_twin.hardware import board, fivebar_plant, j1_gains, j1_nudge, keep_fed, power_up, zero_writer  # noqa: PLC0415
        from bam_rack_twin.hardware import fullarm_stops as fs  # noqa: PLC0415
        from bam_rack_twin.hardware import fullarm_tview_home as home  # noqa: PLC0415

        self.board, self.plant, self.j1_gains, self.j1_nudge, self.keep_fed, self.power_up = board, fivebar_plant, j1_gains, j1_nudge, keep_fed, power_up
        self.zero_writer, self.fs, self.home = zero_writer, fs, home


def j1_gravity_source(rack) -> Callable[[float], float]:
    """J1's holding torque (N.m) at the curve's board-frame angle (``q_joint + FIT_ZERO_BOARD_RAD``): the ONE place the real run takes its
    feed-forward from.

    TODO(measured-mass FF, the dispatcher 2026-11-14): PnP is landing ``MeasuredWristFF`` in bam_rack_twin.hardware.wrist_gains (PID tuna's
    measured masses, data/bam_fb_v2_masses_2026-11-14.json), and arm-hold / fullarm_stops rebase onto it. Once it is on bam_ws main, J1's
    feed-forward comes from THAT module - import it from wrist_gains, never from j1_gains' READY curve, which is pose-blind and over-compensates
    at the stop (the mass fit puts the twin's 32 settled wrist poses at 2.1-3.5 N.m there, the curve at 5.2). Not on main at sim2real cbfca46
    / bam_ws cc9ca44b3, so the curve stays. The switch is here alone (the real run and ``--twin``'s loop both take it; the stand-in J1's own
    gravity stays the curve), with the frame rule (``frame_known``) unchanged - a measured model needs the pose, so pass the bus's last
    reading through when it lands."""
    return rack.j1_gains.j1_gravity_nm


def real_command(rack):
    """J1's command on the real bus: PID tuna's gains (j1_gains), no integrator, the host's setpoint (no board trajectory), its FF and cap."""

    def make(board_rad: float, feedforward_nm: float, cap_nm: float):
        return rack.plant.TrajectoryCommand(position_rad=float(board_rad), velocity_rad_s=0.0, feedforward_torque_nm=float(feedforward_nm),
                                            kp_scale=rack.j1_gains.J1_KP_SCALE, kd_scale=rack.j1_gains.J1_KD_SCALE, ilimit_scale=rack.j1_gains.ILIMIT_SCALE,
                                            maximum_torque_nm=float(cap_nm), velocity_limit_rad_s=math.inf, accel_limit_rad_s2=math.inf)

    return make


def twin_command(rack_gains):
    def make(board_rad: float, feedforward_nm: float, cap_nm: float):
        return TwinJ1Command(position_rad=float(board_rad), feedforward_torque_nm=float(feedforward_nm), maximum_torque_nm=float(cap_nm),
                             kp_scale=rack_gains.J1_KP_SCALE, kd_scale=rack_gains.J1_KD_SCALE, ilimit_scale=rack_gains.ILIMIT_SCALE)

    return make


def decide_and_write(home_record: Mapping[str, Any], check: Mapping[str, Any], *, rack, homed_dir: Path, out: Path, write: bool,
                     say=lambda text: print(text, flush=True)) -> dict[str, Any]:
    """Step 6: the witness and the zero (``zero_decision``), then zero_writer.shift for a "shift" - dry when ``write`` is False."""

    run = home_record.get("home") or {}
    if run.get("outcome") != "done" or run.get("stall_board_rad") is None:
        return {"verdict": "refused", "why": f"J1's home did not finish on a stall ({run.get('outcome')}): nothing written"}
    decision = zero_decision(run["stall_board_rad"], check["_j1map"], powered_up_since_home=check["powered_up_since_j1_home"])
    say(f"J1 zero: {decision['verdict']} - {decision['why']}")
    if decision["verdict"] != "shift":
        return decision
    reason = (f"J1 top-stop home (sim2real.sim.homing.j1_rack: the routine's EffortStall seek, stall at board {run['stall_board_rad']:+.5f} rad, "
              f"witness {decision['witness_deg']:+.3f} deg)")
    try:
        plan = rack.zero_writer.shift(homed_dir, "J1", decision["shift_deg"], reason=reason, evidence=str(out), dry_run=not write)
        decision["zero_writer"] = {"dry_run": not write, "writes": [str(p) for p in plan.writes()]}
    except rack.zero_writer.ZeroRefused as refusal:
        decision.update(verdict="refused", why=f"zero_writer refused: {refusal}")
    return decision


def stamp_j1_homed(homed_dir: Path, *, when: dt.datetime, note: str, homed_history, wait=time.sleep) -> Path:
    """latest.json's revolute_3 ``homed_utc`` set to this home and ``note`` appended to its ``source``, through homed_history.write_latest
    (the one writer; the map's own ``stamp_utc`` - the wrist's power-up staleness clock - is kept). Returns the dated copy.

    WHY (2026-11-14): zero_writer moves a zero and keeps every stamp, and a home that CONFIRMS the zero writes nothing - either way J1's entry
    would still say it was homed before the power-up this home was for, and the next run (and anyone reading homed_utc) would take J1's
    frame for stale. One write per finished home; a second write in the same second (zero_writer's) is retried once a second later."""

    path = Path(homed_dir) / "latest.json"
    document = json.loads(path.read_text())
    entry = document["joints"][J1]
    entry["homed_utc"] = when.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    entry["source"] = f"{entry.get('source') or ''} | {note}".lstrip(" |")
    try:
        return homed_history.write_latest(document, note, path=path)
    except FileExistsError:
        wait(1.1)
        return homed_history.write_latest(document, note, path=path)


def run_twin(arguments, *, rack) -> dict[str, Any]:
    """``--twin``: the files' checks against a COPY of homed/ (and its READY records), the loop on TwinJ1Bus, the zero into the copy."""

    out = Path(arguments.out)
    out.mkdir(parents=True, exist_ok=False)
    source = Path(arguments.homed_dir)
    copy_root = out / "full_arm_copy"
    shutil.copytree(source, copy_root / "homed")
    ready_source = rack.zero_writer.newest_ready(rack.zero_writer.default_ready_root(source))
    (copy_root / "ready_copy" / "sweep").mkdir(parents=True)
    shutil.copy2(ready_source, copy_root / "ready_copy" / "sweep" / "ready_record.json")
    latest = json.loads((copy_root / "homed" / "latest.json").read_text())
    j1map = J1Map.from_latest(latest)
    since = True if arguments.twin_turns else False
    check = {"_j1map": j1map, "powered_up_since_j1_home": since, "latest": str(copy_root / "homed" / "latest.json")}
    gains = rack.j1_gains
    bus = TwinJ1Bus(gravity_nm=gains.j1_gravity_nm, map_zero_board_rad=j1map.zero_board_rad,
                    board_offset_rad=math.radians(TURN_DEG * arguments.twin_turns + arguments.twin_offset_deg),
                    gravity_scale=arguments.twin_gravity_scale, obstacle_joint_rad=None if arguments.twin_obstacle_deg is None
                    else math.radians(arguments.twin_obstacle_deg))
    record = home_j1(bus, j1map, make_command=twin_command(gains), gravity_nm=j1_gravity_source(rack), frame_known=not since)
    result = {"mode": "twin", "homed_dir_copy": str(copy_root / "homed"), **record}
    result["zero"] = decide_and_write(record, check, rack=rack, homed_dir=copy_root / "homed", out=out, write=not arguments.no_write)
    result["homed_stamp"] = _stamp_after(result["zero"], record, homed_dir=copy_root / "homed", out=out, rack=rack, write=not arguments.no_write)
    result["j1_end_deg_true"] = math.degrees(bus.q)
    _write_rows(out, result)
    return result



def homing_start_q(here: Mapping[str, float], ready_rad: Mapping[str, float]) -> dict[str, float]:
    """Where step 3 walks every joint but J1 before the seek (URDF rad, the run's frames): the description's named pose "homing" on the turn
    nearest where each joint is now (``here``; else READY's record, ``ready_rad``), the claw (not in the pose's arm group) at READY's record.

    WHY "homing" and not READY's record (2026-11-19, READY moved to the compact pose): J1 seeks its top stop in this posture, where its
    gravity at the stop measured 5.2 N.m under the 9 N.m stall rule (j1_home); READY's compact posture hangs the arm lower (the model's
    gravity there 1.6x), too close to the rule to tell the stop from a stall. WHY the nearest turn: today's homed map reads C1 a whole turn
    off READY's URDF angle (-374.65 deg), so a target taken as written would ask C1 for a 360 deg walk."""

    pose = named_pose("homing")
    out = dict(ready_rad)
    for joint in pose.joint_names:
        target = float(pose.position_of(joint))
        reference = here.get(joint, ready_rad.get(joint))
        out[joint] = target if reference is None else float(reference) + math.remainder(target - float(reference), 2.0 * math.pi)
    return out

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim2real.sim.homing.j1_rack", description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="files only: the checks, the sequence, the witness; nothing opened")
    parser.add_argument("--twin", action="store_true", help="the loop on a stand-in J1; the zero written into a copy of homed/ under --out")
    parser.add_argument("--allow-motion", action="store_true", help="REQUIRED for the real run: this moves the arm")
    parser.add_argument("--out", type=Path, help="the run's folder (made; must not exist)")
    parser.add_argument("--no-write", action="store_true", help="plan the zero (zero_writer --dry-run), write nothing")
    parser.add_argument("--homed-dir", type=Path, default=HOMED_DIR)
    parser.add_argument("--power-on-dir", type=Path, default=None)
    parser.add_argument("--deployment", type=Path, default=DEPLOYMENT, help="the bam_rack_twin checkout the rack modules come from")
    parser.add_argument("--start-tolerance-deg", type=float, default=START_TOLERANCE_DEG)
    parser.add_argument("--port", help="the fdcanusb port (default: adapter 0607623A's)")
    parser.add_argument("--no-priority-check", action="store_true", help="skip keep_fed.require_powered_priority (never on the rack)")
    parser.add_argument("--twin-turns", type=int, default=0, help="--twin: J1's board frame this many rotor turns off the map (a power-up)")
    parser.add_argument("--twin-offset-deg", type=float, default=0.0, help="--twin: and this much more (a stale zero)")
    parser.add_argument("--twin-gravity-scale", type=float, default=1.0)
    parser.add_argument("--twin-obstacle-deg", type=float, default=None, help="--twin: an obstacle on the sweep at this joint angle")
    arguments = parser.parse_args(argv)
    rack = Rack(arguments.deployment)
    if arguments.power_on_dir is None:
        arguments.power_on_dir = rack.power_up.POWER_ON_DIR
    say = lambda text: print(text, flush=True)  # noqa: E731
    if arguments.twin:
        if arguments.out is None:
            raise SystemExit("--twin needs --out (the copy of homed/ and the report go there)")
        result = run_twin(arguments, rack=rack)
        _write(Path(arguments.out) / "report.json", result)
        say(json.dumps({"home": result["home"]["outcome"], "zero": result["zero"]["verdict"], "why": result["zero"]["why"]}))
        return 0 if result["zero"]["verdict"] in ("confirmed", "shift") else 1
    if not arguments.dry_run:
        # WHY first, before any file is read: a real run that cannot start says so at once, the same way every time
        if not arguments.allow_motion:
            say("REFUSED: this moves the arm; it needs --allow-motion")
            return 2
        if arguments.out is None or Path(arguments.out).exists():
            say("REFUSED: a run needs a new --out <folder>")
            return 2
        if rack.home.HOLD_MARKER.exists():
            say(f"REFUSED: the rack's HOLD marker ({rack.home.HOLD_MARKER}) is present: no motion")
            return 2
    try:
        check = preflight(arguments, rack=rack)
    except (rack.board.Refused, rack.zero_writer.ZeroRefused, OSError, KeyError, ValueError) as refusal:
        say(f"REFUSED before anything opened: {refusal}" if not str(refusal).startswith("REFUSED") else str(refusal))
        return 2
    sequence = j1_home_sequence()
    if arguments.dry_run:
        expected = zero_decision(check["_j1map"].board(math.radians(J1_STOP_DEG)), check["_j1map"],
                                 powered_up_since_home=check["powered_up_since_j1_home"])
        say(json.dumps({k: v for k, v in check.items() if not k.startswith("_") and k != "ready_rad"}, indent=1, default=str))
        say(json.dumps({"sequence": [step.name for step in sequence.steps], "seek_cap_nm": J1_SEEK_CAP_NM, "stall_effort_nm": 9.0,
                        "stop_deg": J1_STOP_DEG, "return_deg": math.degrees(J1_READY_RAD), "witness_reference_board_rad": REFERENCE_STALL_BOARD_RAD,
                        "a_stall_where_the_map_puts_the_stop": expected}, indent=1, default=str))
        return 0
    return real_run(arguments, check, rack=rack, say=say)


# ---------------------------------------------------------------------------------------------------------------- the measured cell
#
# WHY (2026-11-22, fail closed per CONTRACT v3.11): the 17:57Z step-8 seek (j1_home_175659) drove the wrist into the right flood lamp - the
# route judged the belt only and the seek nothing. Every motion this run makes is now judged against the MEASURED cell
# (fullarm_stops.cell_judge: cell_frame.FULL_CELL_POSTS at plan margins, bam_ws 265d451ce) BEFORE it starts: the route to the homing
# posture, the seek to the stop and its return leg. A breach, a pose the judge cannot place, or a deployment without the judge is Refused
# with nothing moved. With the 2026-11-21 cell record this refuses EVERY J1 top-stop seek (the five-bar links cross the carved right side
# near the stop; lane F's HOMING_CELL_CHECK.md) until the right side is re-measured or the lamps move: intended.


def cell_judge_for(fs, geometry, *, refused) -> Callable[[Mapping[str, float]], str]:
    """fullarm_stops' measured-cell judge for this geometry; Refused when the deployment's fullarm_stops has none (never run unjudged)."""
    make = getattr(fs, "cell_judge", None)
    if make is None:
        raise refused(f"REFUSED before motion: the deployment's fullarm_stops ({getattr(fs, '__file__', fs)}) has no cell_judge, so J1's "
                      "seek cannot be judged against the measured cell (needs bam_ws >= 265d451ce; fail closed)")
    return make(geometry)


def full_q(geometry, joints: Mapping[str, float], *, refused) -> dict[str, float]:
    """The full URDF pose (the five-bar closed) for the arm's named joints - what the cell's hulls are placed from; Refused if it won't close."""
    names = (J1, "revolute_6", "revolute_7", "revolute_11", "revolute_14", "revolute_17", "revolute_5")
    missing = [name for name in names if joints.get(name) is None]
    if missing:
        raise refused(f"REFUSED before motion: the seek's posture has no {', '.join(missing)}, so the cell cannot judge it (fail closed)")
    q = geometry.q_from(geometry.craig_of(joints), j1=joints[J1], wrist=[joints["revolute_11"], joints["revolute_14"], joints["revolute_17"]],
                        claw=joints["revolute_5"])
    if q is None:
        raise refused("REFUSED before motion: the seek's posture does not close the five-bar, so the cell cannot judge it (fail closed)")
    return q


def judge_seek(fs, geometry, here: Mapping[str, float], judge, *, refused) -> dict[str, Any]:
    """The seek (J1 from ``here`` to J1_STOP_DEG, every other joint held) and its return leg (to J1_READY_RAD), each a ``plan_route`` J1 step
    judged against ``judge`` at every sample; Refused naming the leg, the member and the gap on the first breach."""
    stop = {**here, J1: math.radians(J1_STOP_DEG)}
    legs = []
    for name, a, b in (("seek", here, stop), ("return", stop, {**stop, J1: J1_READY_RAD})):
        try:
            plan = fs.plan_route(a, geometry.craig_of(a), b, geometry, None, cell=judge)
        except refused as refusal:
            raise refused(f"REFUSED before motion: J1's top-stop {name} ({math.degrees(a[J1]):+.1f} -> {math.degrees(b[J1]):+.1f} deg, every "
                          f"other joint held) breaches the measured cell (fullarm_stops.cell_judge, fail closed): {refusal}") from None
        legs.append({"leg": name, "from_deg": math.degrees(a[J1]), "to_deg": math.degrees(b[J1]), "order": plan.get("order")})
    return {"legs": legs}


def route_and_judge(bus, frames, geometry, start_q: Mapping[str, float], *, fs, judge, refused, tolerance_deg: float, say) -> dict[str, Any]:
    """Steps 3-4's gate: the seek judged from the PLANNED posture (before the route moves anything), the route walked with the cell judged,
    then the seek judged again from the MEASURED pose the route left (just before home_j1)."""
    planned = judge_seek(fs, geometry, full_q(geometry, start_q, refused=refused), judge, refused=refused)
    route = fs.route_to_start(bus, frames, geometry, start_q, tolerance_deg=tolerance_deg, say=say, cell=judge)
    here = frames.q(fs.board_angles(bus.last), geometry)
    if here is None:
        raise refused("REFUSED before the seek: the measured five-bar does not close after the route, so the cell cannot judge the seek")
    measured = judge_seek(fs, geometry, here, judge, refused=refused)
    say("cell: the seek and its return clear the measured cell (fullarm_stops.cell_judge)")
    return {"planned": planned, "route": route, "measured": measured}


def real_run(arguments, check: Mapping[str, Any], *, rack, say) -> int:
    """The real run (module docstring, steps 1-6); the report is written on every exit."""

    Refused, home, fs = rack.board.Refused, rack.home, rack.fs
    out = Path(arguments.out)
    result: dict[str, Any] = {"schema": "sim2real/j1-rack-home/1", "utc": dt.datetime.now(dt.UTC).isoformat(), "argv": list(sys.argv),
                              "sequence": j1_home_sequence().to_dict(), "preflight": {k: v for k, v in check.items() if not k.startswith("_")}}
    try:
        if not arguments.no_priority_check:
            result["priority"] = rack.keep_fed.host_priority()
            try:
                rack.keep_fed.require_powered_priority(result["priority"])
            except SystemExit as error:
                raise Refused(str(error)) from None
        port = arguments.port or rack.board.port_for(home.ADAPTER)
        if arguments.port is None and time.time() - os.lstat(port).st_mtime < USB_QUIET_S:
            raise Refused(f"REFUSED: fdcanusb {home.ADAPTER} enumerated under {USB_QUIET_S:g} s ago")
        geometry = fs.ClawGeometry()  # before the bus: seconds of loading, never inside a powered tick
        frames = fs.ArmFrames.load(Path(check["fivebar_homed"]), Path(check["latest"]))
        judge = cell_judge_for(fs, geometry, refused=Refused)  # the measured cell, before the bus (fail closed: no judge, no run)
    except Refused as refusal:
        say(str(refusal))
        result["result"] = str(refusal)
        out.mkdir(parents=True, exist_ok=True)
        _write(out / "report.json", result)
        return 2
    out.mkdir(parents=True, exist_ok=False)
    bus, stopped_arm_hold, record = None, False, None
    try:
        result["arm_hold_stop"] = rack.j1_nudge.stop_arm_hold()
        stopped_arm_hold = True
        rack.board.hold_bus_lock(rack.board.BUS_LOCK, wait_for_others_s=rack.j1_nudge.LOCK_WAIT_S)
        try:
            if rack.board.find_port_holders(port):
                raise Refused(f"REFUSED: port busy {rack.board.find_port_holders(port)}")
            loop, transport, controllers, register = home._open_real(port)
            from bam_rack_twin.viewer_state import publish_joint_state  # noqa: PLC0415

            bus_class = j1_home_bus(fs, home, rack.plant)
            bus = bus_class(transport, controllers, register, loop=loop, pose_guard=fs.make_pose_guard(frames, geometry, None),
                            publish=lambda boards: publish_joint_state(boards, source="sim2real.j1_rack"))
            bus.port = port
            bus.handoff_power = check["_power"]  # the fast take-over: arm-hold's hand-off record held first (fullarm_stops' WHY)
            replies = bus._exchange({can_id: ("query", None) for can_id in home.ALL_IDS})
            configs = home._read_timeout_modes(loop, controllers)
            home.preflight_boards(replies, configs)
            bus.take_over(drive_cap_nm=dict(home.HELD_MOVE_CAP_NM), feedforward=home.full_arm_comp(_servo_map(check["fivebar_homed"])),
                          hold_riders=True)
            result["take_over"] = {"fast": bus.fast_takeover, "boards": {str(k): v for k, v in bus.taken_over.items()}}
            here = frames.q(fs.board_angles(bus.last), geometry) or {}
            start_q = homing_start_q(here, check["ready_rad"])
            start_q[J1] = here.get(J1, start_q.get(J1, 0.0))  # J1 is not routed: its frame is what this run establishes
            gate = route_and_judge(bus, frames, geometry, start_q, fs=fs, judge=judge, refused=Refused,
                                   tolerance_deg=arguments.start_tolerance_deg, say=say)
            result["route"], result["cell"] = gate["route"], {"planned": gate["planned"], "measured": gate["measured"]}
            bus.stage = "J1 home"
            record = home_j1(bus, check["_j1map"], make_command=real_command(rack), gravity_nm=j1_gravity_source(rack),
                             frame_known=check["powered_up_since_j1_home"] is False, say=say)
            result.update(record)
            _write_rows(out, result)
            result["result"] = "complete" if record["home"]["outcome"] == "done" else f"refused: {record['home']['outcome']}"
        except BaseException as error:
            result["result"] = f"{type(error).__name__}: {error}"
            if bus is not None and bus.taken_over:
                result.update(home.hold_after_trip(bus, error))
            raise
        finally:
            if bus is not None and not bus.taken_over:
                getattr(bus.transport, "close", lambda: None)()
                result["close"] = {"note": "refused before the take-over: no frame sent"}
                bus = None
            if bus is not None:
                result["close"] = bus.close()
                result["trips"] = bus.trips
                _save_trace(out, bus)
            rack.board.release_bus_lock(rack.board.BUS_LOCK)
    except Refused as refusal:
        say(str(refusal))
        result["result"] = str(refusal)
    finally:
        if stopped_arm_hold:
            result["arm_hold_resume"] = rack.j1_nudge.resume_arm_hold()
        _write(out / "report.json", result)
    if record is not None:
        result["zero"] = decide_and_write(record, check, rack=rack, homed_dir=Path(arguments.homed_dir), out=out, write=not arguments.no_write, say=say)
        result["homed_stamp"] = _stamp_after(result["zero"], record, homed_dir=Path(arguments.homed_dir), out=out, rack=rack,
                                             write=not arguments.no_write)
        _write(out / "report.json", result)
        say(json.dumps({"home": record["home"]["outcome"], "zero": result["zero"]["verdict"], "why": result["zero"]["why"]}))
        return 0 if result["zero"]["verdict"] in ("confirmed", "shift") else 1
    return 2


def _stamp_after(zero: Mapping[str, Any], record: Mapping[str, Any], *, homed_dir: Path, out: Path, rack, write: bool) -> dict[str, Any]:
    """``stamp_j1_homed`` after a home whose zero was confirmed or shifted (never after a refusal, nor with ``--no-write``)."""
    if zero.get("verdict") not in ("confirmed", "shift") or not write:
        return {"written": False, "why": "no finished home to stamp" if write else "--no-write"}
    from bam_rack_twin.hardware import homed_history  # noqa: PLC0415

    note = (f"J1 HOMED {dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} by sim2real.sim.homing.j1_rack ({out}): stall at board "
            f"{record['home']['stall_board_rad']:+.5f} rad, zero {zero['verdict']} ({zero['shift_deg']:+.4f} deg)")
    copy = stamp_j1_homed(homed_dir, when=dt.datetime.now(dt.UTC), note=note, homed_history=homed_history)
    return {"written": True, "dated_copy": str(copy), "note": note}


def _servo_map(fivebar_homed: str) -> Any:
    document = json.loads(Path(fivebar_homed).read_text())
    return (document.get("calibrate") or document).get("servo_map")


def _save_trace(out: Path, bus) -> None:
    try:
        import numpy as np  # noqa: PLC0415

        np.save(out / "bus_trace.npy", np.asarray(bus.trace, dtype=float))
        (out / "bus_trace_columns.json").write_text(json.dumps(bus.trace_columns()))
    except Exception as error:  # noqa: BLE001 - a trace that cannot be saved must not mask the run's end
        print(f"trace not saved: {type(error).__name__}: {error}", flush=True)


def _write_rows(out: Path, result: dict[str, Any]) -> None:
    """J1's per-tick rows (t_s, board rad, rad/s, N.m, setpoint board rad, ff N.m, cap N.m) beside the report, out of it."""
    rows = {key: result.pop(key) for key in ("home_rows", "recovery_rows") if key in result}
    _write(out / "j1_rows.json", {"columns": ["t_s", "board_rad", "velocity_rad_s", "torque_nm", "setpoint_board_rad", "feedforward_nm",
                                              "cap_nm"], **rows})


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(document, indent=1, default=lambda value: getattr(value, "__dict__", str(value))))
    os.replace(tmp, path)


if __name__ == "__main__":
    raise SystemExit(main())
