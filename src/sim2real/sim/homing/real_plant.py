"""RealRigPlant: the real five-bar on the One Dof Test Rack behind the homing bench's ``HomingPlant`` seam - the third rung.

The same procedure, the same sequence bytes the MuJoCo rung ran (``mujoco_bench.make``: recover_first + the procedure, sag_proof on,
``+gff`` where named), run tick by tick by robot_msgs' ``JointCommandSequenceController`` - only the plant changes. What changes for the
real arm, and why:

* **The boards.** Each tick's ``ServoCommand`` becomes the drives' ``moteus_servo.MoteusCommand`` exactly as the MuJoCo plant and the
  rack runner's adapter (bam_fivebar_recovery ``PlantBackend``) make it: a limp joint (NaN position or cap 0) is a STOPped board; any
  other is a position setpoint with its feed-forward and cap, ``ilimit_scale`` 0 (a PD), no velocity target, kp / kd scale 1. The bus is
  any object with bam_rack_twin ``BusPlant``'s calls (``read`` / ``send`` / ``step`` / ``send_j1``): the real plant behind ``KeepFed``,
  the CAD twin of the dry run, or a test's stand-in. This module imports nothing from bam_ws: the runner injects the command maker.
* **Frames.** What the controller sees is ``sign x board + frame``: ``sign`` is the homed map's board-to-joint direction (J2 -1, C1 +1 on
  homed_083647; Craig = URDF + offset with sign +1 on bundle 8957130, so it is the URDF direction too), ``frame`` is what the sequence's
  defines added (moteus ``set_output_exact`` kept on the host: nothing is written to a board). A procedure's ``offset_rad`` is therefore
  in the board frame, which the boards keep across sessions (their multi-turn output; ``frame_check`` proves it at every open), so the
  zeros of different starts and procedures are comparable directly.
* **J1 holds.** J1 (CAN 11) is the plane's tilt: the real lane holds it where it is (tview_run's ``11>d pos nan 0 nan``) and never seeks
  it, because its CAD stops at +-89.98 deg are not confirmed on the rack (fivebar-real-night: "Default target -85 deg once Zach confirms
  the stop is real") and a 10 N.m seek tilts the whole plane. :class:`J1Held` rewrites a sequence so every J1 command is that hold and
  every J1 completion condition is dropped (a step left with none ends after ``J1_SKIP_S``); every step keeps its name, so a procedure's
  own ``observe`` still finds its steps, and its J1 zero is dropped. J2 and C1 are untouched.
* **Time.** The tick clock (``ticks x dt``), never the wall clock (fivebar-real-night: a stalled host shifts ``t``, never the ticks).
* **No truth.** ``truth()`` holds the encoders only. Whether a stall was on its stop is judged by the real lane's own stall gate
  (:class:`StopGuard`, tview_run's 1.5 deg against the stops' known board positions), live: a define taken off its stop aborts the
  sequence before anything moves in the wrong frame, and the arm is held (the plant's controlled stop) for the home button.

An aborted sequence ends with every joint limp on the wire (robot_msgs' controller); on this plant a limp arm falls, so the runner
(:func:`run_phase_real`) never sends that command: it asks the bus to hold where it is (``hold_here``) instead, as the home button does.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from robot_models.homing.protocols import Phase, Prior
from robot_models.homing.types import HomingResult
from robot_msgs.control import (
    Elapsed,
    JointCommand,
    JointCommandSequence,
    JointCommandSequenceController,
    JointCommandStep,
    Reached,
    ServoCommand,
    Settled,
    Stall,
)
from robot_msgs.sensor import JointState
from robot_msgs.std import Header

from .geometry import C1, DRIVES, J1, J2, ROLE

DT = 0.01
TAU = 2.0 * math.pi
DRIVE_JOINTS = (J2, C1)  # the bus's drive order: CAN 12, CAN 13
J1_HOLD_CAP_NM = 7.0  # procedures.HOLD_CAP_NM[J1] = tview_run.J1_HOLD_NM
J1_SKIP_S = 0.05  # a step whose only completion watched J1 ends after this (its J1 work is the hold)
# The real lane's stall gate (bam_rack_twin tview_run.STALL_GATE_RAD): the stalls of tview_replay_083647 and full_home_050750 agree within
# 0.011 deg in an unchanged frame, and a drive that binds on the linkage stalls degrees off.
STALL_GATE_DEG = 1.5
# Where each upper stop reads on the boards (tview_run --expect-stall-board-deg, measured on tview_replay_083647; the frames carried since
# by receipt and re-proven by every open's frame check). Board degrees, CAN 12 / CAN 13.
STALL_BOARD_DEG = {J2: -109.715, C1: 102.420}
MAX_EPISODE_S = 600.0
# A powered drive faster than this is a runaway: the bus is held where it is (the plant's controlled stop). WHY 1.5 rad/s (86 deg/s): the
# bus plant's own runaway ceiling (fivebar_plant.PlantLimits.runaway_ceiling_rad_s), which watches only board-trajectory commands - the
# homing sequences send plain position setpoints, so the plant never sees these drives' speeds; this is the same ceiling, applied here.
RUNAWAY_RAD_S = 1.5


# ---------------------------------------------------------------------------------------------------------------- J1 held


def _without_j1(condition):
    """``condition`` with J1 taken out; None when nothing is left to watch."""
    if isinstance(condition, Stall):
        return None if condition.joint == J1 else condition
    if isinstance(condition, (Reached, Settled)):
        joints = tuple(j for j in condition.joints if j != J1)
        if not joints:
            return None
        return condition if len(joints) == len(condition.joints) else replace(condition, joints=joints)
    return condition


def hold_j1_step(step: JointCommandStep) -> JointCommandStep:
    """``step`` with J1 held (whatever it was told) and J1 out of its completion and its defines (module docstring)."""
    commands = tuple(JointCommand.hold(J1, max_effort=J1_HOLD_CAP_NM) if c.joint == J1 else c for c in step.commands)
    if not any(c.joint == J1 for c in commands):
        commands = commands + (JointCommand.hold(J1, max_effort=J1_HOLD_CAP_NM),)
    done = tuple(c for c in (_without_j1(condition) for condition in step.done_when) if c is not None)
    if not done:
        done = (Elapsed(duration=J1_SKIP_S),)
    defines = {j: v for j, v in step.define_position.items() if j != J1}
    return JointCommandStep(name=step.name, commands=commands, done_when=done, timeout=step.timeout, define_position=defines)


def hold_j1(sequence: JointCommandSequence) -> JointCommandSequence:
    return replace(sequence, steps=tuple(hold_j1_step(step) for step in sequence.steps), name=f"{sequence.name} (J1 held)")


def keep_j2_powered(sequence: JointCommandSequence) -> tuple[JointCommandSequence, list[str]]:
    """``sequence`` with J2 never let go once powered: a step that would make J2 limp right after a step that powered it holds J2 instead
    (the previous step's cap and feed-forward). Returns the sequence and the steps changed.

    WHY (the real rung, 2026-11-13): every procedure's first step ("J1 holds") makes J2 and C1 limp for 0.3 s, and behind recover_first
    it follows the recovery's last step, which leaves L1 raised at J2 120 deg (5 deg off its upper stop). On the MuJoCo rung L1 then
    falls ~70 deg in those 0.3 s and the re-hold catches it (sag_proof's docstring). On the real arm that is a free fall of the loaded
    arm caught at the cap - what the bus plant's whole design forbids (fivebar_plant: "a STOPped arm falls", home_004146: 52 deg at
    3.3 rad/s). The crank alone may still go limp with J2 held: that is the home button's own move (J2 holds, the crank comes to rest),
    proven on this arm. The procedure's seek then starts 5 deg from the stop instead of ~70 deg; the stall, its press and the define are
    the procedure's own."""
    steps, changed = [], []
    previous = None
    for step in sequence.steps:
        if previous is not None:
            before = next((c for c in previous.commands if c.joint == J2), None)
            now = next((c for c in step.commands if c.joint == J2), None)
            if now is not None and now.mode == "limp" and before is not None and before.mode != "limp":
                hold = JointCommand.hold(J2, max_effort=float(before.max_effort), feedforward_effort=float(before.feedforward_effort or 0.0))
                step = replace(step, commands=tuple(hold if c.joint == J2 else c for c in step.commands))
                changed.append(step.name)
        steps.append(step)
        previous = step
    return replace(sequence, steps=tuple(steps)), changed


@dataclass
class J1Held:
    """``inner`` (any homing procedure) with J1 held throughout and its J1 zero dropped (module docstring)."""

    inner: Any
    name: str = ""
    references: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def __post_init__(self):
        self.name = self.inner.name

    def plan(self, prior: Prior, so_far: Sequence[Phase]):
        sequence = self.inner.plan(prior, so_far)
        return None if sequence is None else hold_j1(sequence)

    def _strip(self, result: HomingResult) -> HomingResult:
        self.references = [r for r in getattr(self.inner, "references", []) if r[2] != J1]
        self.notes.update(getattr(self.inner, "notes", {}))
        self.notes["j1"] = "held, not homed (its CAD stops are unconfirmed on the rack)"
        return HomingResult(tuple(z for z in result.zeros if z.joint != J1),
                            result.backlash, result.stops, tuple(e for e in result.evidence if e.joint != J1), "real")

    def observe(self, prior: Prior, phases: Sequence[Phase]) -> HomingResult:
        return self._strip(self.inner.observe(prior, phases))

    def observe_vs_twin(self, prior: Prior, twin: Prior, phases: Sequence[Phase]) -> HomingResult:
        return self._strip(self.inner.observe_vs_twin(prior, twin, phases))


# ---------------------------------------------------------------------------------------------------------------- the plant


@dataclass(frozen=True)
class RealStart:
    """A start: where the home button walks the arm before it is released (the homed map's home plus ``offset_deg``, Craig J2 / C1,
    degrees); the episode starts from wherever the released arm comes to rest (recorded, never assumed)."""

    name: str
    offset_deg: tuple[float, float]
    why: str = ""


class RealRigPlant:
    """The real five-bar as a ``HomingPlant`` (module docstring).

    ``bus``: BusPlant's calls. ``make_command(position_rad, feedforward_nm, cap_nm)``: one drive's board command (moteus_servo
    ``MoteusCommand``, ilimit_scale 0). ``j1_command(j1_rad)``: J1's hold where it is. ``setup(start)``: puts the arm at ``start``'s rest
    with the boards stopped and returns a record of it (the runner's home-button walk and release); None leaves the arm where it is.
    ``signs``: board-to-joint direction per drive (J2, C1)."""

    joint_names = DRIVES

    def __init__(self, bus, *, make_command: Callable[[float, float, float], Any], j1_command: Callable[[float], Any] | None = None,
                 setup: Callable[[Any], dict] | None = None, signs: tuple[float, float] = (-1.0, 1.0), dt: float = DT,
                 wall: Callable[[], float] = time.monotonic):
        self.bus = bus
        self.make_command = make_command
        self.j1_command = j1_command
        self.setup = setup
        self.sign = {J2: float(signs[0]), C1: float(signs[1]), J1: 1.0}
        self.dt = float(dt)
        self.wall = wall
        self.ticks = 0
        self.time = 0.0
        self.frame = {j: 0.0 for j in DRIVES}
        self.reading = None
        self.start_record: dict = {}
        self.j1_hold_rad: float | None = None
        self.log: dict[str, list] = {}

    # -- HomingPlant ----------------------------------------------------------------------------------------------------

    def reset(self, start: RealStart | None) -> JointState:
        self.start_record = {"name": None if start is None else start.name}
        if self.setup is not None and start is not None:
            self.start_record["setup"] = self.setup(start)
        self.ticks, self.time = 0, 0.0
        self.frame = {j: 0.0 for j in DRIVES}
        self.reading = self.bus.read()
        j1 = float(getattr(self.reading, "j1_rad", math.nan))
        self.j1_hold_rad = None
        if self.j1_command is not None and hasattr(self.bus, "send_j1") and math.isfinite(j1):
            self.bus.send_j1(self.j1_command(j1))  # held where it is, for the whole episode (module docstring)
            self.j1_hold_rad = j1
        self.start_record.update(board_rad=[float(x) for x in self.reading.position_rad], j1_rad=j1,
                                 mode=[int(m) for m in getattr(self.reading, "mode", (-1, -1))])
        self.log = {"tick": [], "wall": [], "board_rad": [], "velocity_rad_s": [], "torque_nm": [], "setpoint_board_rad": [],
                    "cap_nm": [], "feedforward_nm": [], "mode": [], "j1_rad": [], "exchange_s": []}
        self._record(None)
        return self.state()

    def raw(self, joint: str) -> float:
        if joint == J1:
            return float(getattr(self.reading, "j1_rad", math.nan))
        return self.sign[joint] * float(self.reading.position_rad[DRIVE_JOINTS.index(joint)])

    def tick(self, command: ServoCommand, dt: float, defines: Mapping[str, float] | None = None) -> JointState:
        """Apply the tick's defines on the reading the controller was given, then ``command`` for one bus period (``dt`` must be it)."""
        if abs(float(dt) - self.dt) > 1e-9:
            raise ValueError(f"the bus steps every {self.dt} s; the controller ticked {dt}")
        for joint, value in (defines or {}).items():
            if joint == J1:
                raise ValueError("J1 is held on the real rung: a J1 define means the sequence was not passed through hold_j1")
            self.frame[joint] = float(value) - self.raw(joint)
        index = {name: i for i, name in enumerate(command.name)}
        size = len(command.name)
        cap = np.zeros(size) if command.max_effort is None else np.asarray(command.max_effort, dtype=float)
        feedforward = np.zeros(size) if command.feedforward_effort is None else np.asarray(command.feedforward_effort, dtype=float)
        out, sent = [], []
        for joint in DRIVE_JOINTS:
            i = index.get(joint)
            position = math.nan if i is None else float(command.position[i])
            if i is None or cap[i] <= 0.0 or not math.isfinite(position):
                out.append(None)  # limp: the board STOPped
                sent.append((math.nan, 0.0, 0.0))
                continue
            sign = self.sign[joint]
            board = sign * (position - self.frame[joint])
            out.append(self.make_command(board, sign * float(feedforward[i]), float(cap[i])))
            sent.append((board, float(cap[i]), sign * float(feedforward[i])))
        self.bus.send(out)
        self.reading = self.bus.step()
        self.ticks += 1
        self.time = self.ticks * self.dt
        self._record(sent)
        return self.state()

    def state(self) -> JointState:
        r = self.reading
        position = [self.raw(j) + self.frame[j] if j != J1 else self.raw(J1) for j in DRIVES]
        velocity = [float(getattr(r, "j1_velocity_rad_s", 0.0)) if j == J1 else
                    self.sign[j] * float(r.velocity_rad_s[DRIVE_JOINTS.index(j)]) for j in DRIVES]
        effort = [float(getattr(r, "j1_torque_nm", 0.0)) if j == J1 else
                  self.sign[j] * float(r.torque_nm[DRIVE_JOINTS.index(j)]) for j in DRIVES]
        velocity = [0.0 if not math.isfinite(v) else v for v in velocity]
        effort = [0.0 if not math.isfinite(e) else e for e in effort]
        position = [0.0 if not math.isfinite(p) else p for p in position]
        return JointState(name=DRIVES, position=np.array(position), velocity=np.array(velocity), effort=np.array(effort),
                          header=Header(stamp=self.time))

    def truth(self) -> dict:
        return {"rung": "real", "time_s": self.time, "ticks": self.ticks, "start": dict(self.start_record),
                "board_rad": [float(x) for x in self.reading.position_rad], "frame_rad": dict(self.frame),
                "j1_hold_rad": self.j1_hold_rad, "true_offset_rad": None,
                "why_no_truth": "the real arm: the encoders are all there is; the stall gate judges whether a stall was on its stop"}

    def board_deg(self, joint: str) -> float:
        return math.degrees(float(self.reading.position_rad[DRIVE_JOINTS.index(joint)]))

    def _record(self, sent) -> None:
        r = self.reading
        self.log["tick"].append(self.ticks)
        self.log["wall"].append(float(self.wall()))
        self.log["board_rad"].append([float(x) for x in r.position_rad])
        self.log["velocity_rad_s"].append([float(x) for x in r.velocity_rad_s])
        self.log["torque_nm"].append([float(x) for x in r.torque_nm])
        self.log["setpoint_board_rad"].append([s[0] for s in sent] if sent else [math.nan, math.nan])
        self.log["cap_nm"].append([s[1] for s in sent] if sent else [0.0, 0.0])
        self.log["feedforward_nm"].append([s[2] for s in sent] if sent else [0.0, 0.0])
        self.log["mode"].append([int(m) for m in getattr(r, "mode", (-1, -1))])
        self.log["j1_rad"].append(float(getattr(r, "j1_rad", math.nan)))
        self.log["exchange_s"].append(float(getattr(r, "exchange_s", math.nan)))


# ---------------------------------------------------------------------------------------------------------------- guard and runner


@dataclass
class StopGuard:
    """The real lane's stall gate, live: a define of J2 / C1 is taken only where the drive reads within ``gate_deg`` of its stop's known
    board position (``expected_board_deg``); otherwise the sequence is stopped before anything moves in that frame."""

    expected_board_deg: Mapping[str, float] = field(default_factory=lambda: dict(STALL_BOARD_DEG))
    gate_deg: float = STALL_GATE_DEG
    checks: list = field(default_factory=list)

    # WHY not the recovery's define (blind_recovery's step 11, "the hub meets L1's plate, J2 pressed on its stop"): it is a working
    # frame the procedure behind it replaces - every procedure seeks and defines J2 and C1 again before its zero is read, and the only
    # move made in the recovery's frame is "J2 5 deg off its stop" at the procedure's own cap. On the twin C1 is defined there ~30 deg
    # short of its stop (mujoco_bench.recovery_landing, every start); on the real arm the hub pushed L1 3.7 deg off J2's stop at J2's
    # 10 N.m (real_rf_two_level_touch_gff_064427, recorded as a finding). The gate guards the defines a zero is made of.
    unguarded: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: {"recover: ": (J2, C1)})

    def check(self, plant: RealRigPlant, defines: Mapping[str, float], step_name: str) -> str | None:
        far = []
        skip = {j for prefix, joints in self.unguarded.items() if step_name.startswith(prefix) for j in joints}
        for joint in defines:
            if joint not in self.expected_board_deg or joint in skip:
                continue
            board = plant.board_deg(joint)
            off = board - float(self.expected_board_deg[joint])
            self.checks.append({"step": step_name, "joint": ROLE[joint], "board_deg": round(board, 4), "off_deg": round(off, 4),
                                "tick": plant.ticks, "pass": abs(off) <= self.gate_deg})
            if abs(off) > self.gate_deg:
                far.append(f"{ROLE[joint]} {off:+.2f} deg")
        if far:
            return (f"stall gate: a define in {step_name!r} off its stop's known board position ({', '.join(far)}; gate "
                    f"{self.gate_deg:.1f} deg)")
        return None


class SequenceStopped(RuntimeError):
    """The runner stopped a sequence on the real arm (the controller aborted, the stall gate refused, or the bus tripped); the bus was
    asked to hold where it is when it still could."""

    def __init__(self, message: str, *, kind: str, phase: Phase | None = None, cause: BaseException | None = None):
        super().__init__(message)
        self.kind = kind
        self.phase = phase
        self.cause = cause


def run_phase_real(plant: RealRigPlant, sequence: JointCommandSequence, *, guard: StopGuard | None = None, dt: float = DT,
                   limit_s: float = MAX_EPISODE_S, is_trip: Callable[[BaseException], bool] = lambda error: False,
                   runaway_rad_s: float | None = RUNAWAY_RAD_S, peaks: dict | None = None) -> Phase:
    """``bench.run_phase`` for the real arm: the same controller loop and the same log, with three stops that never send a limp arm
    (module docstring) - each holds the bus where it is (``hold_here`` when the bus has it) and raises :class:`SequenceStopped` carrying
    the phase so far. ``is_trip(error)`` says which exceptions from the bus are its trips (PlantTrip: already holding or braked)."""
    controller = JointCommandSequenceController(sequence)
    state = plant.state()
    log = {"t": [], "position": [], "velocity": [], "effort": [], "defines": [], "events": [], "step": [],
           "plant_offset": len(plant.log["tick"]) - 1}
    names = [s.name for s in sequence.steps]

    def phase(status: str, message: str) -> Phase:
        return Phase(sequence, status, message, tuple(controller.events), log)

    def hold(reason: str) -> None:
        holder = getattr(plant.bus, "hold_here", None)
        if holder is not None and not getattr(plant.bus, "holding", False) and not getattr(plant.bus, "braked", False):
            holder(reason)

    while controller.status == "running" and plant.time < limit_s:
        command, defines = controller.tick(state, dt)
        log["t"].append(plant.time)
        log["position"].append([float(x) for x in state.position])
        log["velocity"].append([float(x) for x in state.velocity])
        log["effort"].append([float(x) for x in state.effort])
        log["defines"].append(dict(defines))
        log["events"].append(len(controller.events))
        log["step"].append(controller.step_index)
        if controller.status == "aborted":
            message = f"the controller aborted: {controller.message}"
            hold(message)
            raise SequenceStopped(message, kind="aborted", phase=phase("aborted", controller.message))
        if defines and guard is not None:
            step_name = names[min(len(controller.events), len(names)) - 1] if controller.events else names[0]
            refused = guard.check(plant, defines, step_name)
            if refused:
                hold(refused)
                raise SequenceStopped(refused, kind="stall_gate", phase=phase("stopped", refused))
        try:
            state = plant.tick(command, dt, defines)
        except Exception as error:
            if is_trip(error):
                raise SequenceStopped(f"the bus tripped: {type(error).__name__}: {error}", kind="trip",
                                      phase=phase("tripped", str(error)), cause=error) from error
            hold(f"host error in the homing runner: {type(error).__name__}: {error}")
            raise
        index = {name: i for i, name in enumerate(command.name)}
        step_name = names[min(controller.step_index, len(names) - 1)]
        for joint in DRIVE_JOINTS:
            i = index.get(joint)
            powered = i is not None and command.max_effort is not None and float(command.max_effort[i]) > 0.0 and \
                math.isfinite(float(command.position[i]))
            speed = abs(float(state.velocity[DRIVES.index(joint)]))
            if peaks is not None:
                key = (step_name, ROLE[joint], "powered" if powered else "limp")
                peaks[key] = max(peaks.get(key, 0.0), speed)
            if powered and runaway_rad_s is not None and speed > runaway_rad_s:
                message = (f"runaway: {ROLE[joint]} at {math.degrees(speed):.0f} deg/s powered, over {math.degrees(runaway_rad_s):.0f} deg/s, "
                           f"in step {step_name!r}")
                hold(message)
                raise SequenceStopped(message, kind="runaway", phase=phase("stopped", message))
    status, message = controller.status, controller.message
    if status == "running":
        hold(f"bench limit {limit_s} s")
        raise SequenceStopped(f"bench limit {limit_s} s", kind="limit", phase=phase("aborted", f"bench limit {limit_s} s"))
    return phase(status, message)


__all__ = ["DRIVE_JOINTS", "J1Held", "keep_j2_powered", "MAX_EPISODE_S", "RUNAWAY_RAD_S", "RealRigPlant", "RealStart", "STALL_BOARD_DEG", "STALL_GATE_DEG", "SequenceStopped",
           "StopGuard", "hold_j1", "hold_j1_step", "run_phase_real"]
