"""KinematicStopPlant: the five-bar's drives on exact, rigid stops - the kinematic rung of the homing ladder (a ``HomingPlant``).

Quasi-static and frictionless, no gravity, no softness at the stops. Each drive (J1, J2, C1) has a motor (output referred) and a
link. The hidden backlash per drive is robot_models' ``BacklashModel``:

* B0  the link is the motor;
* B1  ``gear_backlash``'s dead zone (zero = centre) in its rigid limit: the link stays where it is until a flank of the motor's
      gap reaches it, then is carried (``twist = link - motor`` in ``[-gap/2, gap/2]``);
* B2  B1 plus the series compliance: pressed with torque T the motor goes ``compliance * T`` further.

A powered drive's motor follows its setpoint exactly until its link is blocked (an exact drive stop, or the exporter's loop map);
then the board's PD presses: ``T = min(cap, kp * e / (1 + kp * c))`` with ``e`` the setpoint's lead past the touching flank, and
the motor sits ``c * T`` past it. A limp drive stays where it is (no gravity). WHY the board's kp (200 N.m/rev, the rack record):
when a stall is detected depends on how fast the torque builds, which is the board's loop, not the stop.

What the controller sees is the encoder: ``position = (q_motor - hidden_offset) + frame``, where ``frame`` moves only when a
sequence step defines a position (moteus ``set_output_exact``), and ``hidden_offset`` is the power-up's unknown zero (any value:
the board's single-turn encoder after a 10:1 box knows the output only modulo 36 deg). The true zero, in the stop core's
convention ``q_joint = raw + offset``, is ``offset = hidden_offset``.

``truth()`` holds what no procedure may read: the links, the motors, which stop each link touches (the flank-contact log).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
from robot_msgs.control import ServoCommand
from robot_msgs.sensor import JointState
from robot_msgs.std import Header

from .geometry import C1, DRIVES, EXPORT, J2, FivebarGeometry

TAU = 2.0 * math.pi
# The rack record's board loop (bam_fb_test_rig.homing.RACK_BOARD, records/fivebar-bench: kp 200 N.m per output rev).
BOARD_KP_NM_PER_RAD = 200.0 / TAU
# The gearboxes' mesh stiffness: StepperOnline AD60-G10-D14 (= Apex AD064 10:1), 13 N.m/arcmin (bam_fb_test_rig.backlash).
MESH_NM_PER_ARCMIN = 13.0
ARCMIN = math.radians(1.0 / 60.0)
# The hidden gaps (bam_fb_test_rig.backlash.HIDDEN_ARCMIN): one value per drive, none the datasheet's 3 arcmin.
HIDDEN_GAP_ARCMIN = {"revolute_3": 3.5, "revolute_6": 2.5, "revolute_7": 4.0}
CATCH_UP_RAD_S = 2.0  # under the sequences' 3 rad/s speed guard (see tick)


def hidden_backlash(kind: str, gap_arcmin: Mapping[str, float] = HIDDEN_GAP_ARCMIN, *,
                    mesh_nm_per_arcmin: float = MESH_NM_PER_ARCMIN) -> dict:
    """The hidden truth per drive for ``kind`` B0 / B1 / B2 (robot_models ``BacklashModel``)."""
    from robot_models.homing.types import BacklashModel  # noqa: PLC0415

    out = {}
    for joint in DRIVES:
        gap = gap_arcmin[joint] * ARCMIN
        if kind == "B0":
            out[joint] = BacklashModel("B0")
        elif kind == "B1":
            out[joint] = BacklashModel("B1", gap)
        elif kind == "B2":
            out[joint] = BacklashModel("B2", gap, 1.0 / (mesh_nm_per_arcmin / ARCMIN))
        else:
            raise ValueError(f"backlash kind must be B0, B1 or B2, not {kind!r}")
    return out


@dataclass(frozen=True)
class Start:
    """Where an episode begins: each drive's link (rad), where its motor sits in the gap (-1..1 of gap/2), the power-up's hidden
    zero per drive (rad) and the assembly branch (``export`` or ``mirror``)."""

    name: str
    link_rad: Mapping[str, float]
    gap_fraction: Mapping[str, float] = field(default_factory=dict)
    hidden_offset_rad: Mapping[str, float] = field(default_factory=dict)
    branch: str = EXPORT


@dataclass
class _Drive:
    motor: float
    link: float
    gap: float
    compliance: float
    offset: float  # hidden: raw = motor - offset
    frame: float = 0.0  # what the controller's defines have added: position = raw + frame
    effort: float = 0.0
    velocity: float = 0.0
    touching: str = ""  # "lower" / "upper" (a drive stop), "loop", "" (free)


class KinematicStopPlant:
    """The v11 five-bar on exact rigid stops (see the module docstring). One instance per environment; ``reset`` per episode."""

    joint_names = DRIVES

    def __init__(self, geometry: FivebarGeometry, backlash: Mapping, *, kp_nm_per_rad: float = BOARD_KP_NM_PER_RAD):
        self.geometry = geometry
        self.backlash = dict(backlash)
        self.kp = float(kp_nm_per_rad)
        self.time = 0.0
        self.branch = EXPORT
        self.drives: dict[str, _Drive] = {}
        self.log: dict[str, list] = {}

    # -- HomingPlant ----------------------------------------------------------------------------------------------------

    def reset(self, start: Start) -> JointState:
        self.time = 0.0
        self.branch = start.branch
        self.drives = {}
        for joint in DRIVES:
            model = self.backlash[joint]
            link = float(start.link_rad[joint])
            fraction = float(start.gap_fraction.get(joint, 0.0))
            motor = link - fraction * 0.5 * model.gap_rad  # twist = link - motor in [-gap/2, gap/2]
            self.drives[joint] = _Drive(motor, link, model.gap_rad, model.compliance_rad_per_nm,
                                        float(start.hidden_offset_rad.get(joint, 0.0)))
        lo, hi = self._limits(J2)
        if not (lo <= self.drives[J2].link <= hi) or self._blocked(self.drives[J2].link, self.drives[C1].link):
            raise ValueError(f"start {start.name!r} is not a free pose of the {start.branch} assembly")
        for joint in DRIVES:
            lo, hi = self._limits(joint)
            if not (lo - 1e-12 <= self.drives[joint].link <= hi + 1e-12):
                raise ValueError(f"start {start.name!r}: {joint} at {math.degrees(self.drives[joint].link):.3f} deg is past its stops")
        self.log = {"t": [], "link": [], "motor": [], "position": [], "effort": [], "touching": [], "setpoint": []}
        self._record(None)
        return self.state()

    def tick(self, command: ServoCommand, dt: float, defines: Mapping[str, float] | None = None) -> JointState:
        """Apply the positions the controller defined this tick (on the reading it was given), then ``command`` for ``dt``.

        WHY defines first: the controller shifts its own setpoints into the new frame in the same tick it defines, so the command
        it returns is already in that frame."""
        for joint, value in (defines or {}).items():
            drive = self.drives[joint]
            drive.frame = float(value) - (drive.motor - drive.offset)
        index = {name: i for i, name in enumerate(command.name)}
        targets, caps, feedforward = {}, {}, {}
        for joint, drive in self.drives.items():
            i = index.get(joint)
            setpoint = math.nan if i is None else float(command.position[i])
            cap = 0.0 if i is None else float(command.max_effort[i])
            if math.isnan(setpoint) or cap <= 0.0:
                targets[joint] = None
            else:
                # the setpoint is in the controller's frame: back to the true motor angle
                targets[joint] = setpoint - drive.frame + drive.offset
                caps[joint] = cap
                feedforward[joint] = float(command.feedforward_effort[i])
        old = {joint: drive.motor for joint, drive in self.drives.items()}
        # WHY a catch-up rate (no inertia here): a motor far behind its setpoint (freed from a contact it pressed) moves at most
        # CATCH_UP_RAD_S toward it, a stand-in for the board's lunge. Whether a lunge trips the speed guard is dynamics: the MuJoCo
        # rung's to judge, never this one's (every seek and move here runs at 0.63 rad/s, well under it).
        reach = {joint: None if target is None else
                 old[joint] + max(-CATCH_UP_RAD_S * dt, min(CATCH_UP_RAD_S * dt, target - old[joint]))
                 for joint, target in targets.items()}
        self._move(reach)
        for joint, drive in self.drives.items():
            target = targets[joint]
            if target is None:
                drive.effort, drive.touching = 0.0, ""  # limp: the motor stays where it is (no gravity), no force on anything
                continue
            self._press(joint, drive, target, reach[joint], caps[joint], feedforward[joint])
        self.time += dt
        for joint, drive in self.drives.items():
            drive.velocity = (drive.motor - old[joint]) / dt
        self._record(targets)
        return self.state()

    def state(self) -> JointState:
        names = DRIVES
        return JointState(
            name=names,
            position=np.array([self.drives[j].motor - self.drives[j].offset + self.drives[j].frame for j in names]),
            velocity=np.array([self.drives[j].velocity for j in names]),
            effort=np.array([self.drives[j].effort for j in names]),
            header=Header(stamp=self.time),
        )

    def truth(self) -> dict:
        return {
            "time_s": self.time,
            "branch": self.branch,
            "link_rad": {j: d.link for j, d in self.drives.items()},
            "motor_rad": {j: d.motor for j, d in self.drives.items()},
            "true_offset_rad": {j: d.offset for j, d in self.drives.items()},
            "frame_rad": {j: d.frame for j, d in self.drives.items()},
            "touching": {j: d.touching for j, d in self.drives.items()},
            "backlash": {j: self.backlash[j] for j in self.drives},
        }

    # -- kinematics -----------------------------------------------------------------------------------------------------

    def _limits(self, joint: str) -> tuple[float, float]:
        q6 = self.drives[J2].link if joint == C1 else 0.0
        lo, hi = self.geometry.stop(joint, -1, q6), self.geometry.stop(joint, 1, q6)
        return (-math.inf if lo is None else lo), (math.inf if hi is None else hi)

    def _blocked(self, q6: float, q7: float) -> bool:
        return self.geometry.loop_blocked(q6, q7, self.branch)

    def _wanted_link(self, joint: str, target: float | None) -> float:
        drive = self.drives[joint]
        if target is None:
            return drive.link
        half = 0.5 * drive.gap
        # the dead zone: the link moves only when a flank of the motor's gap reaches it
        return min(max(drive.link, target - half), target + half)

    def _move(self, targets: Mapping[str, float | None]) -> None:
        """Every link to where its motor would carry it, stopped by the exact drive stops and (J2, C1) by the loop map."""
        wanted = {joint: self._wanted_link(joint, targets[joint]) for joint in DRIVES}
        # J1: its own stops only
        lo, hi = self._limits("revolute_3")
        self.drives["revolute_3"].link = min(max(wanted["revolute_3"], lo), hi)
        # J2 first (C1's stop rides on L1), then C1 at the new J2
        q6_old, q7_old = self.drives[J2].link, self.drives[C1].link
        lo6, hi6 = self._limits(J2)
        q6 = min(max(wanted[J2], lo6), hi6)
        lo7, hi7 = (self.geometry.stop(C1, -1, q6), self.geometry.stop(C1, 1, q6))
        q7 = min(max(wanted[C1], lo7), hi7)
        if self._blocked(q6, q7):
            # quasi-static contact: both links advance together as far as the loop allows, then each alone as far as it can
            # (WHY not all-or-nothing: a drive pressing a contact that recedes follows it, as a pressed link does; jumping to its
            # far setpoint the tick it is freed would be a lunge no drive makes)
            q6, q7 = self._advance((q6_old, q7_old), (q6, q7))
            q6, _ = self._advance((q6, q7), (min(max(wanted[J2], lo6), hi6), q7))
            lo7, hi7 = (self.geometry.stop(C1, -1, q6), self.geometry.stop(C1, 1, q6))
            _, q7 = self._advance((q6, q7), (q6, min(max(wanted[C1], lo7), hi7)))
        self.drives[J2].link, self.drives[C1].link = q6, q7
        self._loop_held = {J2: q6 != min(max(wanted[J2], lo6), hi6), C1: q7 != min(max(wanted[C1], lo7), hi7)}

    def _advance(self, frm: tuple[float, float], to: tuple[float, float]) -> tuple[float, float]:
        """The farthest free point on the straight path from ``frm`` (free) toward ``to``, to 1e-9 of the path."""
        if not self._blocked(*to):
            return to
        low, high = 0.0, 1.0
        for _ in range(32):
            middle = 0.5 * (low + high)
            if self._blocked(frm[0] + middle * (to[0] - frm[0]), frm[1] + middle * (to[1] - frm[1])):
                high = middle
            else:
                low = middle
        return frm[0] + low * (to[0] - frm[0]), frm[1] + low * (to[1] - frm[1])

    def _press(self, joint: str, drive: _Drive, target: float, reach: float, cap: float, feedforward: float) -> None:
        """Where the motor ends this tick and what the board's PD pushes: ``reach`` is where the motor heads (its setpoint,
        rate-limited); a link short of it is blocked, and the PD presses with the setpoint's whole lead past the touching flank."""
        half = 0.5 * drive.gap
        if reach > drive.link + half + 1e-12:
            side = 1
        elif reach < drive.link - half - 1e-12:
            side = -1
        else:
            lag = target - reach
            push = 0.0 if abs(lag) < 1e-12 else math.copysign(min(cap, self.kp * abs(lag)), lag)
            drive.motor, drive.effort, drive.touching = reach, feedforward + push, ""
            return
        lead = max(side * (target - drive.link) - half, 0.0)
        torque = min(cap, self.kp * lead / (1.0 + self.kp * drive.compliance))
        drive.motor = drive.link + side * (half + drive.compliance * torque)
        drive.effort = side * torque
        lo, hi = self._limits(joint)
        at_stop = (side > 0 and drive.link >= hi - 1e-12) or (side < 0 and drive.link <= lo + 1e-12)
        drive.touching = ("upper" if side > 0 else "lower") if at_stop else ("loop" if self._loop_held.get(joint) else "held")

    def _record(self, targets) -> None:
        self.log["t"].append(self.time)
        self.log["link"].append([self.drives[j].link for j in DRIVES])
        self.log["motor"].append([self.drives[j].motor for j in DRIVES])
        self.log["position"].append([self.drives[j].motor - self.drives[j].offset + self.drives[j].frame for j in DRIVES])
        self.log["effort"].append([self.drives[j].effort for j in DRIVES])
        self.log["touching"].append([self.drives[j].touching for j in DRIVES])
        self.log["setpoint"].append([math.nan if not targets or targets.get(j) is None else targets[j] for j in DRIVES])


__all__ = ["BOARD_KP_NM_PER_RAD", "HIDDEN_GAP_ARCMIN", "MESH_NM_PER_ARCMIN", "KinematicStopPlant", "Start", "hidden_backlash"]
