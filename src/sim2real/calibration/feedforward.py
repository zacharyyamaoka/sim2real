"""``arm.feedforward_bench``: the bench routine that fits an arm's feedforward, gravity and friction, from paired out-and-back transfers
made with the trajectory library (gap FF-1, 2026-11-18). Part 2 (FF-2) adds its rounds: collect -> fit -> come back for what is missing.

    from sim2real.calibration import FeedforwardBench
    routine = FeedforwardBench(space=space, poses=poses, grid=grid, first=first, drives=("j2", "c1"), gravity_keys=keys,
                               regressor=regressor, inertial=inertial)
    runs = routine.runs(values)          # round 1: one robot_trajectories.trapezoidal_velocity(..., back_to_start=True) per cell
    found = routine.fit(measured, values, twin)            # {key: Estimate}: theta and each drive's frictionloss_nm, damping_nm_s_rad
    routine.with_feedforward(command, values)              # the command with channels["feedforward_effort"] at these values
    routine.next_runs(values, history)   # round k >= 2 (gap A2's members, the runner calls them): empty cells, then over-tolerance ones
    routine.converged(history, values)   # "converged: ..." | Stop("no improvement in 2 rounds: ...") | None (the next round)

Zach, Daily Note 2026-11-18 ("Feedforward CAlibration"): "I basically just want to do .calibrate() and then for the feedforward model to be
fit as accurately as possible", and on the motions: "that calibration routine basically can use the trajectory lib to just generate the
things that its needs". So a run's command is one library call, never a profile re-derived here; the recipe it carries says which.

A cell is (edge, speed): edge = (start pose index, end pose index) into ``poses``, speed = the fraction of each joint's top speed. Each run
goes out along the edge and comes back over the same poses (the way back cancels the friction), its feedforward channel made from the values
it is handed (the board runs the current model while collecting; round k >= 2's commands are made after round k-1's fit). The fit is
sim2real.fit.feedforward.fit over the runs measured, with the prior the values runs() was handed (a snapshot, so a later round never counts
the prior twice), held out by cell.

The rounds (FF-2), on gap A2's protocol, which sim2real.rig.RigRunner plays: round 1 is ``first`` (the slow band, on the prior's
feedforward; default the whole grid); each later round collects the grid's cells never collected, then the collected cells whose held-out
residual (that cell left out of the last fit) is over ``tolerance_nm``, worst first, at most ``per_round`` of them, as fresh runs
(``.../r{k}/...``) whose commands carry the last fit's feedforward; when every cell is collected and within ``tolerance_nm`` but the stop
still waits on ΔG (one fit so far, or ΔG >= ``delta_nm``), it re-collects the collected cells, worst residual first, at most ``per_round``.
It stops converged when, after two rounds or more, the gravity of the last two fits differs by less than ``delta_nm`` on the pose graph
(ΔG), the worst held-out cell residual is within ``tolerance_nm`` and no cell is empty; it stops NOT converged when, with every cell
collected and that residual still over ``tolerance_nm``, ``patience`` rounds in a row cut it (over the cells both fits held) by less than
``min_improvement`` (relative: a model that cannot explain the data), or at ``max_rounds``. The runner says which in the step's ``stopped``.
WHY the residual and ΔG and never the 95 % intervals alone (the runner's default stop): at noise 0 every interval is tight after round 1
while the fast band is still empty, and a stop rule must read only what the bench reads too (no hidden truth). Graded by
tests/test_feedforward_rounds.py and its committed ladder sysid/results/routine_ladders/arm.feedforward_bench.json (0x / 1x / 3x / 10x on
the closed-loop toy arm).

Layer: like rig.py and twin.py, right of every folder; robot_trajectories (the ``trajectories`` extra) is imported only when runs are made.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from ..fit import feedforward as ff
from ..rig import Estimate, Run, Stop

__all__ = ["FeedforwardBench"]

Cell = tuple[tuple[int, int], float]
CHANNEL = "feedforward_effort"
# The routine's defaults for the fit's two row rules, where the bench differs from fit.feedforward's own (0.02 / 0.02), both measured on the
# closed-loop toy arm (tests/feedforward_toy.py, cloud dispatches d06364981, d07015580, d07280523, 2026-11-19):
# WHY 0.05 rad to pair the legs: on a board's PD the measured way out and way back part by the tracking error (friction short of the
# feedforward / kp, opposite on the two legs); with round 1 on the CAD prior only 12 % of one slow edge's way out lay within 0.02 rad of the
# way back, so the fit refused the very first round; at 0.05 rad every round-1 leg at every noise level pairs (>= 96 %). The guard is against a run one
# way or back along a detour (0.4 rad in tests/test_feedforward_bench.py), and the regressor reads the MEASURED poses, so a few
# hundredths of a radian of parting costs the fit nothing
BENCH_PAIR_TOL_RAD = 0.05
# WHY 0.1 rad/s for a moving row: a board's speed noise makes a hold read as moving (at 3x, 0.015 rad/s of noise puts ~18 % of resting
# samples over 0.02 rad/s), and each such sample enters with a random sign(qd) and a torque that rests on static friction ("no hold is a
# row", 15c): at 0.02 the 3x fit's Coulomb fell to 0.78 N.m and its worst held-out cell residual sat at 0.75-0.84 N.m; at 0.1 the 3x and
# 10x fits keep Coulomb within 0.03 N.m and gravity within 0.015 N.m, and 0x / 1x are unchanged (gravity <= 0.009 N.m)
BENCH_MOVING_RAD_S = 0.1


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
    ``poses``: (P, J) joint positions; ``grid``: every cell the routine may collect; ``first``: round 1's cells (default the grid). A bench
    sets ``first`` to the slow band, a strict part of the grid (round 1 on the prior then costs less arm time). With the default a fit
    within ``tolerance_nm`` everywhere still converges: converged() needs two fits to read ΔG, so next_runs() re-collects the worst cells
    for the second (and does so at any later round whose cells all fit while ΔG is still >= ``delta_nm``). ``gravity_keys``: the twin's keys
    for theta, in the regressor's order; ``regressor(q)``: (N, J) -> (N, J, P); ``inertial(q, qd, qdd)``: (N, J), the twin's inertial term
    (the commands carry it, the fit removes it). ``prior_sigma``: the ridge toward the values handed to runs() (theta's units; None: no
    ridge). Each drive's friction is its ``frictionloss_nm`` (Coulomb) and ``damping_nm_s_rad`` (NET viscous: negative where friction
    weakens with speed). The rounds (module docstring): ``max_rounds`` (the runner's cap), ``tolerance_nm`` (a cell's held-out residual),
    ``delta_nm`` (ΔG between rounds), ``per_round`` (cells a later round may collect; None: no cap), ``patience`` and ``min_improvement``
    (the no-improvement stop). ``moving_rad_s`` / ``pair_tol_rad``: the fit's row rules at the bench's defaults, 0.1 rad/s (5.7°/s) and 0.05
    rad (2.9°) (BENCH_MOVING_RAD_S, BENCH_PAIR_TOL_RAD: why, beside them)."""

    id = "arm.feedforward_bench"
    FRICTION = ("frictionloss_nm", "damping_nm_s_rad")

    def __init__(self, *, space: Any, poses, grid: Sequence[Cell], drives: Sequence[str], gravity_keys: Sequence[str],
                 regressor: Callable[[np.ndarray], np.ndarray], first: Sequence[Cell] | None = None, inertial: Callable | None = None,
                 prior_sigma=None, tolerance_nm: float = 0.10, delta_nm: float = 0.05, max_rounds: int = 4, per_round: int | None = None,
                 dwell_s: float = 0.3, moving_rad_s: float = BENCH_MOVING_RAD_S, pair_tol_rad: float = BENCH_PAIR_TOL_RAD,
                 patience: int = 2, min_improvement: float = 0.10) -> None:
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
        # WHY first=None still means the whole grid (FF-1's public default, kept): changing it would move round 1 for every caller. A good
        # fit on it no longer stops after one round "did not converge": next_runs() re-collects the worst cells so converged() reads ΔG
        self.first = self.grid if first is None else tuple(_cell(c, len(poses)) for c in first)
        self.gravity_keys = tuple(str(k) for k in gravity_keys)
        self.regressor, self.inertial = regressor, inertial
        self.prior_sigma, self.dwell_s = prior_sigma, float(dwell_s)
        self.moving_rad_s, self.pair_tol_rad = float(moving_rad_s), float(pair_tol_rad)
        self.identifies = self.gravity_keys + tuple(f"{d}.{name}" for d in self.drives for name in self.FRICTION)
        # WHY declared (fix round 1, lane L4): each run's feedforward channel is made from these very values, and the catalog's refines
        # edge puts this routine after the step that finds the drives' friction (servo.dynamics_regression on the CAN 11 pendulum).
        # Undeclared, the schedule would show it "known now" at the priors and RigRunner.calibrate(schedule=) would refuse it at play time
        self.commands_read = self.identifies
        # the rounds (gap FF-2, on gap A2's protocol: max_rounds, next_runs, converged; Zach, Daily Note 2026-11-18: "a routine should
        # include datacollection and fitting steps, and then iterating things that all goes into it")
        if isinstance(max_rounds, bool) or int(max_rounds) != max_rounds or max_rounds < 1:
            raise ValueError(f"{self.id}: max_rounds is an int >= 1, not {max_rounds!r}")
        if per_round is not None and (isinstance(per_round, bool) or int(per_round) != per_round or per_round < 1):
            raise ValueError(f"{self.id}: per_round is None (no cap) or an int >= 1, not {per_round!r}")
        if isinstance(patience, bool) or int(patience) != patience or patience < 1:
            raise ValueError(f"{self.id}: patience is an int >= 1, not {patience!r}")
        self.max_rounds = int(max_rounds)
        self.tolerance_nm, self.delta_nm = float(tolerance_nm), float(delta_nm)
        self.per_round = None if per_round is None else int(per_round)
        self.patience, self.min_improvement = int(patience), float(min_improvement)
        self._fresh()

    def _fresh(self) -> None:
        self._bare: dict[Cell, Any] = {}     # each cell's motion, made once (the library is deterministic)
        self._cells: dict[str, Cell] = {}    # run id -> its cell: the held-out residual leaves out a cell, never one run of a pair
        self._prior: dict[str, float] | None = None
        self.fits_: list[ff.FeedforwardFit] = []
        self._fit_of: dict[frozenset[str], ff.FeedforwardFit] = {}   # the runs a fit saw -> that fit (a round reads its own fit back)

    def __copy__(self) -> FeedforwardBench:
        """WHY its own caches (fix round 1, lane L8): calibration.plan.apply_options plays a copy.copy with other options (dwell_s, space,
        poses, grid); a shallow copy would share the motions made at the original's options and the fits the original made."""
        out = object.__new__(type(self))
        out.__dict__.update(self.__dict__)
        out._fresh()
        return out

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
        self._fit_of = {}
        return tuple(self._run(cell, 1, values) for cell in self._cells_of(self.first))

    def next_runs(self, values: Mapping[str, float], history: Sequence[Any]) -> tuple[Run, ...]:
        """The next round's runs (gap A2's member; ``history``: the runner's rounds so far, each with the runs it asked for): the grid's
        cells never collected first, in grid order, then the collected cells whose held-out residual (the last fit's, that cell left out)
        is over ``tolerance_nm``, worst first; at most ``per_round`` of them. Each is a fresh run, ``…/r{k}/…`` for round k (1 = runs()),
        its feedforward made from ``values``: the runner hands the values after the last fit, so the board runs the latest model while it
        collects. When nothing is empty or over tolerance but converged() still waits (one fit so far, or ΔG >= ``delta_nm``), the
        collected cells again, worst residual first (a NaN residual first), at most ``per_round``. () only when converged() has an
        answer: the runner stops on that first, so it never asks then."""
        self._needs(values)
        if not history:
            return ()
        latest = self._fits(history)[-1]
        collected = self._collected(history)
        empty = [cell for cell in self._cells_of(self.grid) if cell not in collected]
        residual = {cell: float(latest.residual_by_group.get(cell, math.nan)) for cell in collected}
        # WHY sorted on the residual alone (stable): ties keep the order they were collected in, so a round is the same for the same data
        over = sorted((cell for cell in collected if residual[cell] > self.tolerance_nm), key=lambda cell: -residual[cell])
        cells = (empty + over)[: self.per_round]
        # WHY re-collect when every cell fits but converged() still waits (orchestrator's call on the L8 review, 2026-11-19): converged()
        # needs two fits to read ΔG, and with nothing empty or over tolerance this returned (), so a good fit on first = the whole grid
        # (or any round whose cells all fit while ΔG >= delta_nm) ended "did not converge". The worst cells first: their fresh runs are the
        # data most likely to move the fit, so the next ΔG is the hardest read of whether it has stopped changing; per_round caps the arm
        # time as for any later round, and a round is never empty (collected holds round 1's cells)
        if not cells and self.converged(history, values) is None:
            cells = sorted(collected, key=lambda cell: -residual[cell] if math.isfinite(residual[cell]) else -math.inf)[: self.per_round]
        return tuple(self._run(cell, len(history) + 1, values) for cell in cells)

    def converged(self, history: Sequence[Any], values: Mapping[str, float] | None = None) -> str | Stop | None:
        """Gap A2's member, its own stop (it replaces the runner's default, every 95 % interval inside its tolerance, which an empty fast
        band would never trip). Converged, after two rounds or more: the gravity the last two fits give differs by less than ``delta_nm``
        anywhere on the pose graph's edges (ΔG), the worst cell's held-out residual is within ``tolerance_nm``, and no cell of the grid is
        still empty: "converged: ...". Else, with more than ``patience`` rounds, every cell collected and the worst residual still over
        ``tolerance_nm``, a Stop (not converged) when none of the last ``patience`` rounds cut the worst held-out residual over the cells
        both fits held by ``min_improvement`` (relative): "no improvement in {patience} rounds: ...". Else None, the next round. The cap
        is the runner's (max_rounds)."""
        if len(history) < 2:
            return None
        fits = self._fits(history)
        change = self._gravity_change(fits[-2], fits[-1])
        worst = self._worst(fits[-1])
        collected = self._collected(history)
        empty = [cell for cell in self._cells_of(self.grid) if cell not in collected]
        if change < self.delta_nm and worst <= self.tolerance_nm and not empty:
            return (f"converged: ΔG {change:.3g} N·m < {self.delta_nm:g} N·m between rounds {len(history) - 1} and {len(history)}, and the "
                    f"worst held-out cell residual {worst:.3g} N·m <= {self.tolerance_nm:g} N·m over all {len(collected)} cells")
        # WHY only over tolerance with every cell collected (fix round 1, lane L8): a model within tolerance, or one with cells still
        # empty (per_round caps a round: 20-30 arm-minutes each), has not shown that it cannot explain the data; next_runs collects
        # the empty cells first and the runner's cap still bounds it. A NaN residual is not within tolerance
        if len(history) > self.patience and not worst <= self.tolerance_nm and not empty:
            # WHY over the cells both fits held: round 1 holds the slow band only, so the worst over all cells would compare unlike sets
            steps = [self._shared_worst(before, after) for before, after in zip(fits[-(self.patience + 1):-1], fits[-self.patience:])]
            # WHY a NaN or a rise counts as no improvement: only a residual that measurably falls earns another round of arm time
            cut = [(before - after) / before if before > 0 else math.nan for before, after, _n in steps]
            if not any(c >= self.min_improvement for c in cut):
                return Stop(f"no improvement in {self.patience} rounds: the worst held-out cell residual over the cells both fits held went "
                            + ", ".join(f"{before:.3g} -> {after:.3g} ({n} cells)" for before, after, n in steps)
                            + f" N·m (each round must cut it by {self.min_improvement:.0%}; now {worst:.3g} N·m over all "
                            f"{len(collected)} cells, tolerance {self.tolerance_nm:g} N·m), ΔG {change:.3g} N·m")
        return None

    # --- the rounds' bookkeeping (read from the fits this routine made, keyed by the runs each one saw)

    def _fits(self, history: Sequence[Any]) -> list[ff.FeedforwardFit]:
        out, seen = [], set()
        for done in history:
            seen |= {run.id for run in done.runs}
            found = self._fit_of.get(frozenset(seen))
            if found is None:
                raise RuntimeError(f"{self.id}: no fit of this routine saw exactly the runs of rounds 1-{len(out) + 1} "
                                   f"({len(seen)} runs): next_runs() and converged() read the fits it made since runs()")
            out.append(found)
        return out

    def _collected(self, history: Sequence[Any]) -> list[Cell]:
        cells: list[Cell] = []
        for done in history:
            for run in done.runs:
                spec = run.spec if isinstance(run.spec, Mapping) else {}
                cell = _cell(spec["cell"], len(self.poses)) if "cell" in spec else self._cells[run.id]
                if cell not in cells:
                    cells.append(cell)
        return cells

    @staticmethod
    def _worst(found: ff.FeedforwardFit, cells=None) -> float:
        finite = [float(v) for cell, v in found.residual_by_group.items() if (cells is None or cell in cells) and math.isfinite(v)]
        return max(finite) if finite else math.nan

    def _shared_worst(self, before: ff.FeedforwardFit, after: ff.FeedforwardFit) -> tuple[float, float, int]:
        shared = set(before.residual_by_group) & set(after.residual_by_group)
        return self._worst(before, shared), self._worst(after, shared), len(shared)

    def _gravity_change(self, before: ff.FeedforwardFit, after: ff.FeedforwardFit) -> float:
        return float(np.abs(np.asarray(self.regressor(self._probe()), float) @ (np.asarray(after.theta) - np.asarray(before.theta))).max())

    def _probe(self) -> np.ndarray:
        """Where ΔG is read: every edge the routine may play, 11 points along each (the poses its transfers pass through). WHY at use:
        calibration.plan.apply_options hands the runner a copy with its own grid / first / poses."""
        edges = sorted({edge for edge, _speed in (*self._cells_of(self.grid), *self._cells_of(self.first))})
        poses = np.asarray(self.poses, float)
        along = np.linspace(0.0, 1.0, 11)[:, None]
        return np.concatenate([poses[a] + along * (poses[b] - poses[a]) for a, b in edges])

    def _cells_of(self, cells: Sequence[Any]) -> tuple[Cell, ...]:
        return tuple(_cell(c, len(self.poses)) for c in cells)

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
        self._fit_of[frozenset(str(run_id) for run_id in measured)] = found
        worst = max(found.residual_nm)
        method = (f"{self.id}: gravity on the regressor + Coulomb and net viscous friction per drive, least squares over {found.rows} "
                  f"moving rows of {len(found.runs)} paired transfers (holds never rows); held-out residual by cell {worst:.3g} N.m")
        out = {key: Estimate(found.theta[i], found.theta_ci95[i], method) for i, key in enumerate(self.gravity_keys)}
        for j, drive in enumerate(self.drives):
            out[f"{drive}.frictionloss_nm"] = Estimate(found.coulomb[j], found.coulomb_ci95[j], method)
            out[f"{drive}.damping_nm_s_rad"] = Estimate(found.damping[j], found.damping_ci95[j], method)
        return out
