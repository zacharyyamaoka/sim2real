"""Bench feedforward from paired out-and-back runs: gravity linear in a twin's regressor, plus Coulomb and net viscous friction per drive
(gap FF-1, 2026-11-18; the routine that plays it is sim2real.calibration.FeedforwardBench). numpy only.

    from sim2real.fit import feedforward
    fit = feedforward.fit(measured, regressor, inertial=inertial, prior=cad_theta, prior_sigma=1.0, groups=cell_of_run)
    fit.gravity(regressor, q)            # (N, J) N.m, at the fitted theta
    fit.friction_torque(qd)              # (N, J) N.m: Coulomb sign(v) + net viscous v, per drive
    fit.torque(regressor, q, qd, qdd, inertial=inertial)   # what a command carries as feedforward (Coulomb smoothed, at most tanh(v / 0.05))
    fit.residual_nm, fit.residual_by_group                 # the held-out residual, leaving out one group (cell) at a time

``measured``: {run id: robot_msgs JointTrajectory} with positions, effort (the board's torque) and, when present, velocities and
accelerations (else finite differences). ``regressor(q)``: (N, J) positions -> (N, J, P), G(q) = Y(q) theta. ``inertial(q, qd, qdd)``:
(N, J), what the twin says the inertia takes. Every run's columns are the regressor's drives, in its order.

The estimator, a port of bam_ws bam_pid_tunning docs/mass_refit (the 14b / 15c refits that put today's measured masses on the arm):
- rows are MOVING samples only, |qd| >= moving_rad_s on that drive. WHY (15c's lesson): a hold rests anywhere inside static friction, so it
  bounds gravity and never equals it; no hold is a row.
- target = effort - inertial; design = [Y(q) | per drive sign(v), v]. One least squares, with ridge rows toward the prior when prior_sigma is
  given (absolute, in theta's units; weighted by the data's own residual sigma, so it is the textbook MAP estimate).
- each run must go out and come back over the same poses: that is what cancels the friction (the way back reads gravity - friction where
  the way out read gravity + friction). A run that goes one way, or comes back along another path, is refused by name.
- friction is ONE curve, Coulomb plus a NET viscous term (negative where friction weakens with speed): sign(v)(Fc - w|v|) is Fc sign(v) - w v,
  the same column as b v, so a separate weakening term could never be told apart from it (tests/feedforward_toy.py).
- the residual is held out by group (a cell: one edge at one speed), never one run of a pair, and SYSTEMATIC: per drive, the RMS of the
  held-out residual's means over consecutive blocks of >= 25 moving rows (a pose bin along one leg), so torque noise averages out and
  model error does not.

Layer: fit/ (may import metrics and schedule; tests/test_layers.py).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = ["COULOMB_SMOOTH_RAD_S", "FeedforwardFit", "feedforward_torque", "fit", "friction_torque"]

# WHY at most 0.05 rad/s (the gap FF review, 2026-11-18): the board's feedforward needs Coulomb continuous through zero speed or it chatters
# on a reversal, but a wider tanh is a different curve from the one the fit found; at 0.2 rad/s tanh(v / 0.05) is within 0.07 % of sign(v)
COULOMB_SMOOTH_RAD_S = 0.05
MOVING_RAD_S = 0.02        # |qd| at or under this is a hold (metrics.actuator.HOLD_SPEED_RAD_S, the same line)
PAIR_TOL_RAD = 0.02        # how near a sample of one leg must lie to the other leg's path
LEG_SHARE = 0.20           # each leg holds at least this share of a run's moving rows
PATH_SHARE = 0.80          # and at least this share of each leg's samples lies within PAIR_TOL_RAD of the other leg's path
BLOCK_ROWS = 25            # rows per block of the systematic residual
_PATH_POINTS, _PATH_VERTICES = 200, 2000   # the path check's sampling (points of one leg, vertices of the other's polyline)


@dataclass(frozen=True)
class FeedforwardFit:
    """One fit. ``theta``: the regressor's P terms; ``theta_ci95``: each one's 95 % interval (lo, hi), from the covariance scaled by the
    residual's own variance (fit.least_squares.Solution.intervals' rule). ``coulomb`` / ``damping``: per drive, N.m and N.m.s/rad (net:
    negative where friction weakens with speed). ``residual_nm``: per drive, the held-out systematic residual (NaN with fewer than two
    groups: nothing to hold out). ``residual_by_group``: {group: the worst drive's held-out systematic residual on that group}. ``rows``: the
    design matrix's rows (one per moving sample per drive). ``runs``: the run ids it was fitted on."""
    theta: tuple[float, ...]
    theta_ci95: tuple[tuple[float, float], ...]
    coulomb: tuple[float, ...]
    damping: tuple[float, ...]
    residual_nm: tuple[float, ...]
    residual_by_group: Mapping[Hashable, float]
    rows: int
    runs: tuple[str, ...]
    coulomb_ci95: tuple[tuple[float, float], ...] = field(default=())
    damping_ci95: tuple[tuple[float, float], ...] = field(default=())

    def gravity(self, regressor: Callable[[np.ndarray], np.ndarray], q) -> np.ndarray:
        """G(q) = Y(q) theta: (N, J) positions -> (N, J) N.m."""
        return np.asarray(regressor(np.atleast_2d(np.asarray(q, float))), float) @ np.asarray(self.theta, float)

    def friction_torque(self, qd, *, smooth_rad_s: float = 0.0) -> np.ndarray:
        """Coulomb sign(v) + net viscous v per drive: (N, J) speeds -> (N, J) N.m (exact sign by default)."""
        return friction_torque(self.coulomb, self.damping, qd, smooth_rad_s=smooth_rad_s)

    def torque(self, regressor, q, qd, qdd=None, *, inertial=None, smooth_rad_s: float = COULOMB_SMOOTH_RAD_S) -> np.ndarray:
        """The feedforward a command carries at this fit: gravity + friction (Coulomb smoothed) + the twin's inertial term."""
        return feedforward_torque(regressor, self.theta, self.coulomb, self.damping, q, qd, qdd, inertial=inertial,
                                  smooth_rad_s=smooth_rad_s)


def friction_torque(coulomb: Sequence[float], damping: Sequence[float], qd, *, smooth_rad_s: float = 0.0) -> np.ndarray:
    """Coulomb sign(v) (or tanh(v / smooth_rad_s), at most COULOMB_SMOOTH_RAD_S wide) + net viscous v, per drive: (N, J) -> (N, J) N.m."""
    if smooth_rad_s > COULOMB_SMOOTH_RAD_S:
        raise ValueError(f"Coulomb smoothing of {smooth_rad_s:g} rad/s is wider than {COULOMB_SMOOTH_RAD_S:g} rad/s: another curve than "
                         "the fitted one")
    v = np.atleast_2d(np.asarray(qd, float))
    shape = np.tanh(v / smooth_rad_s) if smooth_rad_s > 0.0 else np.sign(v)
    return shape * np.asarray(coulomb, float) + v * np.asarray(damping, float)


def feedforward_torque(regressor, theta, coulomb, damping, q, qd, qdd=None, *, inertial=None,
                       smooth_rad_s: float = COULOMB_SMOOTH_RAD_S) -> np.ndarray:
    """Y(q) theta + friction(qd) (Coulomb smoothed) + inertial(q, qd, qdd): the ONE curve a round commands and a fit installs, (N, J) N.m."""
    q = np.atleast_2d(np.asarray(q, float))
    qd = np.atleast_2d(np.asarray(qd, float))
    tau = np.asarray(regressor(q), float) @ np.asarray(theta, float) + friction_torque(coulomb, damping, qd, smooth_rad_s=smooth_rad_s)
    if inertial is not None:
        if qdd is None:
            raise ValueError("the inertial term needs the accelerations (qdd)")
        tau = tau + np.asarray(inertial(q, qd, np.atleast_2d(np.asarray(qdd, float))), float)
    return tau


# --- the fit -----------------------------------------------------------------------------------------------------------------------------


@dataclass
class _Rows:
    run_id: str
    group: Hashable
    design: np.ndarray      # (m, K)
    target: np.ndarray      # (m,)
    drive: np.ndarray       # (m,) which drive each row is
    block: np.ndarray       # (m,) block id inside this run (the systematic residual's pose bins)


def _derivatives(run_id: str, run: Any):
    if run.effort is None:
        raise ValueError(f"{run_id}: no effort (the board's torque) to fit")
    if run.velocities is not None and run.accelerations is not None:
        return run
    return run.with_derivatives()


def _decimated(points: np.ndarray, most: int) -> np.ndarray:
    if len(points) <= most:
        return points
    keep = np.unique(np.linspace(0, len(points) - 1, most).round().astype(int))
    return points[keep]


def _near_share(points: np.ndarray, line: np.ndarray, tolerance: float) -> float:
    """The share of `points` within `tolerance` of the polyline `line` (sampled: _PATH_POINTS points, _PATH_VERTICES vertices at most)."""
    if not len(points):
        return 0.0
    points, line = _decimated(points, _PATH_POINTS), _decimated(line, _PATH_VERTICES)
    if len(line) == 1:
        distance = np.linalg.norm(points - line[0], axis=1)
    else:
        start, step = line[:-1], line[1:] - line[:-1]
        length2 = np.maximum((step ** 2).sum(axis=1), 1e-300)
        s = np.clip(np.einsum("psj,sj->ps", points[:, None, :] - start[None], step) / length2, 0.0, 1.0)
        nearest = start[None] + s[..., None] * step[None]
        distance = np.linalg.norm(nearest - points[:, None, :], axis=2).min(axis=1)
    return float(np.mean(distance <= tolerance))


def _legs(run_id: str, q: np.ndarray, qd: np.ndarray, moving_rad_s: float, pair_tol_rad: float) -> np.ndarray:
    """Each sample's leg: +1 out, -1 back, 0 at rest; refused unless the run goes out and comes back over the same poses."""
    moving = (np.abs(qd) >= moving_rad_s).any(axis=1)
    far = int(np.argmax(np.linalg.norm(q - q[0], axis=1)))
    away = q[far] - q[0]
    along = qd @ away
    leg = np.where(moving & (along > 0), 1, np.where(moving & (along < 0), -1, 0))
    n = int(moving.sum())
    out, back = int((leg > 0).sum()), int((leg < 0).sum())
    if n == 0 or not np.any(away) or min(out, back) < LEG_SHARE * n:
        raise ValueError(f"{run_id}: needs both directions over the same poses: of its {n} moving rows {out} go out and {back} come back "
                         f"(each way needs {LEG_SHARE:.0%}); a run one way cannot cancel the friction")
    for mine, other, word in ((leg > 0, leg < 0, "out"), (leg < 0, leg > 0, "back")):
        share = _near_share(q[mine], q[other], pair_tol_rad)
        if share < PATH_SHARE:
            raise ValueError(f"{run_id}: needs both directions over the same poses: only {share:.0%} of its way {word} lies within "
                             f"{pair_tol_rad:g} rad of the other way's path (needs {PATH_SHARE:.0%}); coming back along another path "
                             "cancels no friction")
    return leg


def _blocks(index: np.ndarray, leg: np.ndarray) -> np.ndarray:
    """Block ids over one drive's moving rows (`index`, ascending): consecutive rows on one leg, cut into blocks of >= BLOCK_ROWS."""
    if not len(index):
        return np.zeros(0, int)
    cut = np.flatnonzero((np.diff(index) != 1) | (np.diff(leg[index]) != 0)) + 1
    out = np.empty(len(index), int)
    next_id = 0
    for segment in np.split(np.arange(len(index)), cut):
        pieces = max(1, len(segment) // BLOCK_ROWS)
        for piece in np.array_split(segment, pieces):
            out[piece] = next_id
            next_id += 1
    return out


def _run_rows(run_id: str, group: Hashable, run: Any, regressor, inertial, moving_rad_s: float, pair_tol_rad: float, drives: int,
              terms: int | None) -> _Rows:
    c = _derivatives(run_id, run)
    q, qd, qdd = (np.asarray(a, float) for a in (c.positions, c.velocities, c.accelerations))
    leg = _legs(run_id, q, qd, moving_rad_s, pair_tol_rad)
    y = np.asarray(regressor(q), float)
    if y.ndim != 3 or y.shape[:2] != q.shape or (terms is not None and y.shape[2] != terms):
        raise ValueError(f"{run_id}: the regressor gave shape {y.shape}; expected ({len(q)}, {drives}, P)")
    target = np.asarray(c.effort, float) - (0.0 if inertial is None else np.asarray(inertial(q, qd, qdd), float))
    p = y.shape[2]
    design, values, drive, block, offset = [], [], [], [], 0
    for j in range(drives):
        index = np.flatnonzero(np.abs(qd[:, j]) >= moving_rad_s)
        rows = np.zeros((len(index), p + 2 * drives))
        rows[:, :p] = y[index, j, :]
        rows[:, p + 2 * j] = np.sign(qd[index, j])
        rows[:, p + 2 * j + 1] = qd[index, j]
        design.append(rows)
        values.append(target[index, j])
        drive.append(np.full(len(index), j))
        ids = _blocks(index, leg)
        block.append(ids + offset)
        offset += int(ids.max()) + 1 if len(ids) else 0
    return _Rows(run_id, group, np.concatenate(design), np.concatenate(values), np.concatenate(drive), np.concatenate(block))


def _solve(normal: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.solve(normal, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(normal) @ rhs   # rank-deficient (an unexcited direction): the minimum-norm solution


def _systematic(parts: Sequence[_Rows], x: np.ndarray, drives: int) -> list[list[float]]:
    """Per drive, the block means of the residual over `parts` at `x`."""
    means: list[list[float]] = [[] for _ in range(drives)]
    for part in parts:
        residual = part.target - part.design @ x
        if not len(residual):
            continue
        ids, inverse = np.unique(part.block, return_inverse=True)
        sums = np.bincount(inverse, residual, minlength=len(ids))
        counts = np.bincount(inverse, minlength=len(ids))
        owner = np.zeros(len(ids), int)
        owner[inverse] = part.drive
        for k, mean in enumerate(sums / counts):
            means[owner[k]].append(float(mean))
    return means


def _rms(values: Sequence[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else math.nan


def fit(measured: Mapping[str, Any], regressor: Callable[[np.ndarray], np.ndarray], *, inertial: Callable | None = None, prior=None,
        prior_sigma=None, moving_rad_s: float = MOVING_RAD_S, groups: Mapping[str, Hashable] | None = None,
        pair_tol_rad: float = PAIR_TOL_RAD) -> FeedforwardFit:
    """Gravity (theta, linear in ``regressor``) and per-drive Coulomb and net viscous friction from paired out-and-back runs, moving rows
    only (see the module docstring). ``prior`` (P,) with ``prior_sigma`` (a number or (P,), theta's units) adds ridge rows toward it.
    ``groups``: {run id: group} for the held-out residual (default: each run its own group). Raises ValueError naming the run id and
    "both directions" when a run lacks a way back over the same poses."""
    if not measured:
        raise ValueError("fit needs at least one run")
    if prior_sigma is not None and prior is None:
        raise ValueError("prior_sigma without a prior: the ridge pulls toward the prior")
    groups = dict(groups or {})
    names: tuple[str, ...] | None = None
    parts: list[_Rows] = []
    terms = None
    for run_id, run in measured.items():
        joints = tuple(run.joint_names)
        if names is None:
            names = joints
        elif joints != names:
            raise ValueError(f"{run_id}: joints {joints}; the other runs have {names} (one regressor, one drive order)")
        part = _run_rows(str(run_id), groups.get(run_id, run_id), run, regressor, inertial, moving_rad_s, pair_tol_rad, len(names), terms)
        terms = part.design.shape[1] - 2 * len(names)
        parts.append(part)
    drives, p = len(names), terms
    k = p + 2 * drives
    design = np.concatenate([part.design for part in parts])
    target = np.concatenate([part.target for part in parts])
    m = len(target)
    if m <= k:
        raise ValueError(f"{m} moving rows cannot fit {k} terms (theta {p}, friction {2 * drives}); the runs barely move")
    normal, rhs = design.T @ design, design.T @ target
    x = _solve(normal, rhs)
    sigma2 = float(np.sum((target - design @ x) ** 2)) / (m - k)
    ridge, pull = np.zeros((k, k)), np.zeros(k)
    if prior is not None and prior_sigma is not None:
        prior = np.asarray(prior, float).reshape(-1)
        sigma = np.broadcast_to(np.asarray(prior_sigma, float), (p,))
        if prior.shape != (p,) or np.any(sigma <= 0):
            raise ValueError(f"the prior needs {p} terms and a positive sigma; got {prior.shape} and {prior_sigma!r}")
        weight = sigma2 / sigma ** 2
        ridge[:p, :p] = np.diag(weight)
        pull[:p] = weight * prior
        x = _solve(normal + ridge, rhs + pull)
        sigma2 = float(np.sum((target - design @ x) ** 2)) / (m - k)
    half = 1.96 * np.sqrt(np.clip(np.diag(np.linalg.pinv(normal + ridge)) * sigma2, 0.0, None))
    interval = [(float(x[i] - half[i]), float(x[i] + half[i])) for i in range(k)]
    # the held-out residual: leave out one group at a time (a cell: both legs of every run in it), refit, score the group
    by_group: dict[Hashable, list[_Rows]] = {}
    for part in parts:
        by_group.setdefault(part.group, []).append(part)
    pooled: list[list[float]] = [[] for _ in range(drives)]
    residual_by_group: dict[Hashable, float] = {}
    for group, members in by_group.items():
        if len(by_group) < 2:
            residual_by_group[group] = math.nan
            continue
        own_normal = sum(member.design.T @ member.design for member in members)
        own_rhs = sum(member.design.T @ member.target for member in members)
        held = _solve(normal - own_normal + ridge, rhs - own_rhs + pull)
        means = _systematic(members, held, drives)
        for j in range(drives):
            pooled[j] += means[j]
        residual_by_group[group] = max((_rms(v) for v in means if v), default=math.nan)
    residual = tuple(_rms(v) if len(by_group) >= 2 else math.nan for v in pooled)
    return FeedforwardFit(theta=tuple(float(v) for v in x[:p]), theta_ci95=tuple(interval[:p]),
                          coulomb=tuple(float(x[p + 2 * j]) for j in range(drives)),
                          damping=tuple(float(x[p + 2 * j + 1]) for j in range(drives)),
                          residual_nm=residual, residual_by_group=residual_by_group, rows=m, runs=tuple(str(r) for r in measured),
                          coulomb_ci95=tuple(interval[p + 2 * j] for j in range(drives)),
                          damping_ci95=tuple(interval[p + 2 * j + 1] for j in range(drives)))
