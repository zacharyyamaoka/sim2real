"""Levenberg-Marquardt with 95 % intervals, numpy only.

WHY not scipy.optimize.least_squares (the stock part sysid uses): sim2real's runtime is robot_msgs (numpy) and nothing heavier
(pyproject, Zach 2026-11-10); scipy is an extra. This is the textbook damped Gauss-Newton (Marquardt 1963) with a forward-difference
Jacobian, small enough to read; tests hold it to scipy where scipy is installed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

__all__ = ["Solution", "levenberg_marquardt"]


@dataclass(frozen=True)
class Solution:
    x: np.ndarray
    residual: np.ndarray
    jacobian: np.ndarray
    iterations: int
    converged: bool

    @property
    def rms(self) -> float:
        return float(np.sqrt(np.mean(self.residual ** 2)))

    def intervals(self) -> np.ndarray:
        """95 % half-widths from the Jacobian at the solution, scaled by the residual's own variance (white noise assumed)."""
        dof = max(1, self.residual.size - self.x.size)
        covariance = np.linalg.pinv(self.jacobian.T @ self.jacobian) * float(self.residual @ self.residual) / dof
        return 1.96 * np.sqrt(np.clip(np.diag(covariance), 0.0, None))


def _jacobian(residual: Callable[[np.ndarray], np.ndarray], x: np.ndarray, r0: np.ndarray, scale: np.ndarray) -> np.ndarray:
    jac = np.empty((r0.size, x.size))
    for i in range(x.size):
        step = 1e-6 * max(abs(x[i]), scale[i])
        bumped = x.copy()
        bumped[i] += step
        jac[:, i] = (residual(bumped) - r0) / step
    return jac


def levenberg_marquardt(residual: Callable[[np.ndarray], np.ndarray], x0, *, scale=None, max_iterations: int = 100,
                        tolerance: float = 1e-10,
                        jacobian: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None) -> Solution:
    """Minimise sum(residual(x)^2) from x0. ``scale`` is each parameter's typical size (the finite-difference step and the damping's
    metric); defaults to max(|x0|, 1). ``jacobian(x, r)`` replaces the dense forward difference when the caller knows the structure
    (a bundle adjustment: each view's pose moves only its own residuals)."""

    x = np.asarray(x0, float).copy()
    scale = np.maximum(np.abs(x), 1.0) if scale is None else np.asarray(scale, float)
    if jacobian is None:
        def jacobian(at, r_at):
            return _jacobian(residual, at, r_at, scale)
    r = np.asarray(residual(x), float)
    cost = float(r @ r)
    damping = 1e-3
    jac = jacobian(x, r)
    converged = False
    iteration = 0
    for iteration in range(1, max_iterations + 1):
        gradient = jac.T @ r
        normal = jac.T @ jac
        diagonal = np.maximum(np.diag(normal), 1e-12)
        improved = False
        for _ in range(12):
            step = np.linalg.solve(normal + damping * np.diag(diagonal), -gradient)
            trial = x + step
            r_trial = np.asarray(residual(trial), float)
            cost_trial = float(r_trial @ r_trial)
            if np.isfinite(cost_trial) and cost_trial < cost:
                relative = (cost - cost_trial) / max(cost, 1e-300)
                x, r, cost = trial, r_trial, cost_trial
                damping = max(damping / 3.0, 1e-12)
                improved = True
                break
            damping *= 4.0
        if not improved:
            converged = True
            break
        jac = jacobian(x, r)
        if relative < tolerance or np.max(np.abs(step) / scale) < tolerance:
            converged = True
            break
    return Solution(x, r, jac, iteration, converged)
