"""camera_rgbd's depth rungs as equations, and the fit that identifies them (cards: camera_rgbd M0 ideal stereo, M1 + disparity noise,
M2 + depth bias). Its colour stream is a camera_rgb (the card's member) and is fitted by sim2real.fit.camera_rgb.

- M0: z = f b / d, the stereo law; nothing to fit beyond the factory's baseline, focal length and depth scale.
- M1: sigma_z = subpixel_sigma * z^2 / (f b) (Khoshelham & Elberink 2012), the disparity noise seen in depth.
- M2: z_measured = z + bias(z), bias a low-order polynomial in z (Herrera et al. 2012 also let it vary across the image; one global
  curve is this rung, the B-spline field is the card's M6 residual).

``fit_flat_target`` takes a flat target at several measured distances: per distance, the mean depth over the target's pixels and the
per-pixel std over frames. Black box: the true distances in, the camera's depths out.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["stereo_sigma", "DepthModel", "fit_flat_target", "flat_target_statistics"]


def stereo_sigma(z_m, focal_px: float, baseline_m: float, subpixel_sigma: float) -> np.ndarray:
    """M1's depth noise at range z: subpixel_sigma * z^2 / (f b)."""
    z = np.asarray(z_m, float)
    return subpixel_sigma * z * z / (focal_px * baseline_m)


@dataclass(frozen=True)
class DepthModel:
    """camera_rgbd M0-M2 with the card's parameter names: baseline_m and focal_px are the factory's; subpixel_sigma (M1) and
    depth_bias_coeffs (M2, highest power first, metres) are what the flat target identifies."""

    baseline_m: float
    focal_px: float
    subpixel_sigma: float = 0.0
    depth_bias_coeffs: tuple[float, ...] = (0.0,)

    def bias(self, z_m) -> np.ndarray:
        return np.polyval(np.asarray(self.depth_bias_coeffs, float), np.asarray(z_m, float))

    def mean_depth(self, z_m) -> np.ndarray:
        """What the camera reads on average for a surface truly at z."""
        z = np.asarray(z_m, float)
        return z + self.bias(z)

    def sigma(self, z_m) -> np.ndarray:
        return stereo_sigma(z_m, self.focal_px, self.baseline_m, self.subpixel_sigma)

    def correct(self, z_measured) -> np.ndarray:
        """The inverse of M2: a measured depth back to the true one (one fixed-point step is exact to well under a micron here)."""
        z = np.asarray(z_measured, float)
        return z - self.bias(z - self.bias(z))

    def simulate(self, z_m, frames: int, rng: np.random.Generator) -> np.ndarray:
        """(frames, *z.shape) depth readings of surfaces at z: the twin's output for a static scene."""
        z = np.asarray(z_m, float)
        return self.mean_depth(z) + rng.normal(size=(frames, *z.shape)) * self.sigma(z)


def flat_target_statistics(depth_frames: np.ndarray) -> tuple[float, float]:
    """(mean depth, per-pixel temporal std RMS) of one flat target's pixels over frames: (frames, pixels) in metres; 0 = no depth."""
    frames = np.asarray(depth_frames, float)
    valid = np.all(frames > 0.0, axis=0)
    frames = frames[:, valid]
    return float(frames.mean()), float(np.sqrt(np.mean(np.var(frames, axis=0, ddof=1))))


def fit_flat_target(true_z_m, mean_depth_m, temporal_std_m, *, focal_px: float, baseline_m: float, bias_degree: int = 2) -> DepthModel:
    """M1 + M2 from a flat target: subpixel_sigma by least squares through the origin of std on z^2 / (f b); depth_bias_coeffs a
    polynomial of (measured - true) on z. Needs bias_degree + 2 distances at least."""

    z = np.asarray(true_z_m, float)
    measured = np.asarray(mean_depth_m, float)
    std = np.asarray(temporal_std_m, float)
    if z.size < bias_degree + 2:
        raise ValueError(f"a degree-{bias_degree} bias needs at least {bias_degree + 2} distances")
    a = z * z / (focal_px * baseline_m)
    subpixel = float(a @ std / (a @ a))
    coeffs = np.polyfit(z, measured - z, bias_degree)
    return DepthModel(baseline_m, focal_px, subpixel, tuple(float(c) for c in coeffs))
