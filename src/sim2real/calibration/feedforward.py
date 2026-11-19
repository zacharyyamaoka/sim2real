"""``arm.feedforward_bench``: the bench routine that fits an arm's feedforward, gravity and friction, from paired out-and-back transfers
made with the trajectory library (gap FF-1, 2026-11-18). Part 2 (FF-2) adds its rounds: collect -> fit -> come back for what is missing.

    from sim2real.calibration import FeedforwardBench
    routine = FeedforwardBench(space=space, poses=poses, grid=grid, first=first, drives=("j2", "c1"), gravity_keys=keys,
                               regressor=regressor, inertial=inertial)
    runs = routine.runs(values)          # round 1: one robot_trajectories.trapezoidal_velocity(..., back_to_start=True) per cell
    found = routine.fit(measured, values, twin)            # {key: Estimate}: theta and each drive's frictionloss_nm, damping_nm_s_rad
    routine.with_feedforward(command, values)              # the command with channels["feedforward_effort"] at these values

Zach, Daily Note 2026-11-18 ("Feedforward CAlibration"): "I basically just want to do .calibrate() and then for the feedforward model to be
fit as accurately as possible", and on the motions: "that calibration routine basically can use the trajectory lib to just generate the
things that its needs". So a run's command is one library call, never a profile re-derived here; the recipe it carries says which.

A cell is (edge, speed): edge = (start pose index, end pose index) into ``poses``, speed = the fraction of each joint's top speed. Each run
goes out along the edge and comes back over the same poses (the way back cancels the friction), its feedforward channel made from the values
it is handed (the board runs the current model while collecting; round k >= 2's commands are made after round k-1's fit). The fit is
sim2real.fit.feedforward.fit over the runs measured, with the prior the values runs() was handed (a snapshot, so a later round never counts
the prior twice), held out by cell.

Layer: like rig.py and twin.py, right of every folder; robot_trajectories (the ``trajectories`` extra) is imported only when runs are made.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from ..fit import feedforward as ff
from ..rig import Estimate, Run

__all__ = ["FeedforwardBench"]

Cell = tuple[tuple[int, int], float]
CHANNEL = "feedforward_effort"


def _trajectories():
    """WHY at call time: robot_trajectories is the optional ``trajectories`` extra (it has no remote yet); sim2real imports without it."""
    import robot_trajectories  # noqa: PLC0415

    return robot_trajectories


def _cell(cell: Any, poses: int) -> Cell:
    (start, end), speed = cell
    start, end, speed = int(start), int(end), float(speed)
    if not (0 <= start < poses and 0 <= end < poses) or start == end:
        raise ValueError(f"cell {cell!r}: an edge joins two different poses of the {poses} given")
    if not 0.0 < speed <= 1.0:
        raise ValueError(f"cell {cell!r}: the speed is a fraction of each joint's top speed, in (0, 1]")
    return ((start, end), speed)


class FeedforwardBench:
    """The routine (a sim2real.rig Routine; see the module docstring). ``space``: a robot_trajectories JointSpace over ``drives``;
    ``poses``: (P, J) joint positions; ``grid``: every cell the routine may collect; ``first``: round 1's cells (default the grid);
    ``gravity_keys``: the twin's keys for theta, in the regressor's order; ``regressor(q)``: (N, J) -> (N, J, P); ``inertial(q, qd, qdd)``:
    (N, J), the twin's inertial term (the commands carry it, the fit removes it). ``prior_sigma``: the ridge toward the values handed to
    runs() (theta's units; None: no ridge). Each drive's friction is its ``frictionloss_nm`` (Coulomb) and ``damping_nm_s_rad`` (NET
    viscous: negative where friction weakens with speed)."""

    id = "arm.feedforward_bench"
    FRICTION = ("frictionloss_nm", "damping_nm_s_rad")

    def __init__(self, *, space: Any, poses, grid: Sequence[Cell], drives: Sequence[str], gravity_keys: Sequence[str],
                 regressor: Callable[[np.ndarray], np.ndarray], first: Sequence[Cell] | None = None, inertial: Callable | None = None,
                 prior_sigma=None, tolerance_nm: float = 0.10, delta_nm: float = 0.05, max_rounds: int = 4, per_round: int | None = None,
                 dwell_s: float = 0.3, moving_rad_s: float = ff.MOVING_RAD_S, pair_tol_rad: float = ff.PAIR_TOL_RAD) -> None:
        self.space = space
        self.drives = tuple(str(d) for d in drives)
        if tuple(space.joint_names) != self.drives:
            raise ValueError(f"{self.id}: the space's joints {tuple(space.joint_names)} are not the drives {self.drives}")
        poses = np.array(poses, float)
        if poses.ndim != 2 or poses.shape[1] != len(self.drives) or len(poses) < 2:
            raise ValueError(f"{self.id}: poses is (P >= 2, {len(self.drives)}) joint positions, not shape {poses.shape}")
        poses.setflags(write=False)
        self.poses = poses
        self.grid = tuple(_cell(c, len(poses)) for c in grid)
        self.first = self.grid if first is None else tuple(_cell(c, len(poses)) for c in first)
        self.gravity_keys = tuple(str(k) for k in gravity_keys)
        self.regressor, self.inertial = regressor, inertial
        self.prior_sigma, self.dwell_s = prior_sigma, float(dwell_s)
        self.moving_rad_s, self.pair_tol_rad = float(moving_rad_s), float(pair_tol_rad)
        self.identifies = self.gravity_keys + tuple(f"{d}.{name}" for d in self.drives for name in self.FRICTION)
        # WHY kept aside and not as max_rounds / converged members (lane L4): part 1 plays one round, so it exposes none of gap A's round
        # members and every runner treats it as a one-round routine; part 2 (FF-2) turns these into max_rounds, next_runs and converged
        self._rounds = {"tolerance_nm": float(tolerance_nm), "delta_nm": float(delta_nm), "max_rounds": int(max_rounds),
                        "per_round": per_round}
        self._bare: dict[Cell, Any] = {}     # each cell's motion, made once (the library is deterministic)
        self._cells: dict[str, Cell] = {}    # run id -> its cell: the held-out residual leaves out a cell, never one run of a pair
        self._prior: dict[str, float] | None = None
        self.fits_: list[ff.FeedforwardFit] = []

    def __repr__(self) -> str:
        return (f"FeedforwardBench({len(self.drives)} drives {self.drives}, {len(self.poses)} poses, {len(self.grid)} cells, "
                f"round 1 plays {len(self.first)})")

    # --- what it plays

    def _needs(self, values: Mapping[str, float]) -> None:
        missing = [k for k in (*self.gravity_keys, *(f"{d}.{n}" for d in self.drives for n in self.FRICTION)) if k not in values]
        if missing:
            raise KeyError(f"{self.id}: the values it is handed lack {missing}")

    def _motion(self, cell: Cell):
        if cell not in self._bare:
            (start, end), speed = cell
            self._bare[cell] = _trajectories().trapezoidal_velocity(self.space, target=self.poses[end], start=self.poses[start],
                                                                   velocity_fraction=speed, dwell_s=self.dwell_s, back_to_start=True)
        return self._bare[cell]

    def _run(self, cell: Cell, round_k: int, values: Mapping[str, float]) -> Run:
        (start, end), speed = cell
        run_id = f"{self.id}/r{round_k}/e{start}-{end}/v{speed:g}"
        self._cells[run_id] = cell
        return Run(run_id, "train", spec={"cell": cell, "round": round_k}, command=self.with_feedforward(self._motion(cell), values))

    def runs(self, values: Mapping[str, float]) -> tuple[Run, ...]:
        """Round 1: one paired transfer per cell of ``first``, its feedforward made from ``values``. Resets ``fits_``."""
        self._needs(values)
        self._prior = {k: float(values[k]) for k in self.gravity_keys}
        self.fits_ = []
        return tuple(self._run(cell, 1, values) for cell in self.first)

    def with_feedforward(self, command, values: Mapping[str, float]):
        """``command`` with channels["feedforward_effort"] = gravity at the values' theta + each drive's friction (Coulomb, smoothed at
        most tanh(v / 0.05), plus the net viscous term) + the twin's inertial term, at the command's own positions, speeds and accelerations
        (a channel already there is replaced). The same curve the fit installs (fit.feedforward.feedforward_torque)."""
        self._needs(values)
        c = command if command.velocities is not None and command.accelerations is not None else command.with_derivatives()
        theta = [float(values[k]) for k in self.gravity_keys]
        coulomb = [float(values[f"{d}.frictionloss_nm"]) for d in self.drives]
        damping = [float(values[f"{d}.damping_nm_s_rad"]) for d in self.drives]
        effort = ff.feedforward_torque(self.regressor, theta, coulomb, damping, c.positions, c.velocities, c.accelerations,
                                       inertial=self.inertial)
        return command.with_channel(CHANNEL, effort)

    # --- what it finds

    def fit(self, measured: Mapping[str, Any], values: Mapping[str, float], twin: Any = None) -> dict[str, Estimate]:
        """fit.feedforward.fit over ``measured`` (held out by cell), the prior the values runs() was handed. ``twin`` is not played: the
        twin's part (its inertial term) is the ``inertial`` the routine was built with."""
        prior = self._prior if self._prior is not None else {k: float(values[k]) for k in self.gravity_keys}
        found = ff.fit(measured, self.regressor, inertial=self.inertial, prior=np.array([prior[k] for k in self.gravity_keys]),
                       prior_sigma=self.prior_sigma, moving_rad_s=self.moving_rad_s,
                       groups={run_id: self._cells.get(run_id, run_id) for run_id in measured}, pair_tol_rad=self.pair_tol_rad)
        self.fits_.append(found)
        worst = max(found.residual_nm)
        method = (f"{self.id}: gravity on the regressor + Coulomb and net viscous friction per drive, least squares over {found.rows} "
                  f"moving rows of {len(found.runs)} paired transfers (holds never rows); held-out residual by cell {worst:.3g} N.m")
        out = {key: Estimate(found.theta[i], found.theta_ci95[i], method) for i, key in enumerate(self.gravity_keys)}
        for j, drive in enumerate(self.drives):
            out[f"{drive}.frictionloss_nm"] = Estimate(found.coulomb[j], found.coulomb_ci95[j], method)
            out[f"{drive}.damping_nm_s_rad"] = Estimate(found.damping[j], found.damping_ci95[j], method)
        return out
