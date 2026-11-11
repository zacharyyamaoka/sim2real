"""Black-box camera metrics: how close a camera model is to the real camera, from inputs and outputs only.

Every camera type (camera_rgb, camera_rgbd, camera_hsi) is scored the same way the servo is: the model's error on HELD-OUT captures,
divided by the camera's own floor, the error the real camera makes against itself when nothing changes (sim2real's rule: a model is
twinned when it is no further from the real camera than the real camera is from itself, within 1.5x: cards.schema.TWINNED_LIMIT).

    model error  = predicted output vs measured output, on captures the fit never saw
    floor        = measured output vs itself, repeated captures of a static scene
    fidelity     = model error / floor        (<= 1.5 twinned; >> 1 a missing term, a wrong rung or a stale calibration)

What a camera outputs, and so what is compared (the black box):

| type        | output compared                   | model error                              | floor                                   |
|-------------|-----------------------------------|------------------------------------------|-----------------------------------------|
| camera_rgb  | where a known point lands (px)    | reprojection RMS                         | corner jitter on a static target        |
| camera_rgb  | how bright a known patch is (DN)  | DN residual RMS at unseen settings       | temporal noise of the patch             |
| camera_rgb  | when a frame says it saw an event | latency error                            | stamp jitter                            |
| camera_rgbd | how far a known surface is (m)    | depth residual RMS per distance band     | temporal depth noise at that distance   |
| camera_hsi  | which wavelength a band sees (nm) | lamp-line centre residual                | line-centre repeatability               |
| camera_hsi  | a known material's spectrum       | spectral angle, model vs measured        | spectral angle between repeat scans     |

A second check per model: its NOISE is right too. ``noise_calibration`` is the std of residual / predicted sigma; 1.0 means the model's
stated uncertainty is the real one (a twin that is right on average but claims too little noise gives a planner false confidence).

Pure numpy; no camera, no fitting. The fits that make the predictions are sim2real.fit.camera_*.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = ["Fidelity", "fidelity", "jitter_floor", "temporal_noise", "session_floor", "reprojection_rms", "residual_rms", "noise_calibration",
           "spectral_angle", "mean_spectral_angle", "repeat_spectral_angle", "NOISE_CALIBRATION_BAND"]

# The model's stated noise is right when residual / sigma has a std in this band (a chi-square 95 % band for a few hundred samples,
# rounded out): below, the model claims more noise than there is; above, it is overconfident.
NOISE_CALIBRATION_BAND = (0.7, 1.4)


@dataclass(frozen=True)
class Fidelity:
    """One black-box comparison: the model's error, the real camera's floor, their ratio, and the unit both are in."""

    metric: str
    model_error: float
    floor: float
    unit: str
    samples: int

    @property
    def ratio(self) -> float:
        if self.floor <= 0.0:
            return math.inf if self.model_error > 0.0 else 0.0
        return self.model_error / self.floor

    def twinned(self, limit: float) -> bool:
        """True when the model is within ``limit`` x the camera's own floor (pass cards.schema.TWINNED_LIMIT, 1.5)."""
        return self.ratio <= limit


def fidelity(metric: str, model_error: float, floor: float, unit: str, samples: int) -> Fidelity:
    return Fidelity(metric, float(model_error), float(floor), unit, int(samples))


# --------------------------------------------------------------------------------------------------------------------- the floors


def jitter_floor(repeats: np.ndarray) -> float:
    """RMS scatter of repeated measurements of the same things, e.g. corner pixels over frames of a static target.

    ``repeats`` is (n_repeats, n_items, ...): each item measured n_repeats times. Returns the RMS distance from each item's own mean,
    unbiased (x sqrt(n / (n - 1))), over every coordinate the trailing axes hold: for 2-D pixels it is the per-axis RMS, so it compares
    directly with ``reprojection_rms``'s per-axis RMS.
    """

    repeats = np.asarray(repeats, float)
    n = repeats.shape[0]
    if n < 2:
        raise ValueError("a floor needs at least two repeats")
    deviation = repeats - repeats.mean(axis=0, keepdims=True)
    return float(np.sqrt(np.mean(deviation ** 2) * n / (n - 1)))


def temporal_noise(frames: np.ndarray) -> float:
    """Per-pixel std over frames of a static scene, RMS over pixels (DN, metres, whatever the frames hold). Frames are (n, ...)."""

    frames = np.asarray(frames, float)
    if frames.shape[0] < 2:
        raise ValueError("temporal noise needs at least two frames")
    return float(np.sqrt(np.mean(np.var(frames, axis=0, ddof=1))))


def session_floor(sigma_one: float, calibration_samples: int, held_out_samples: int) -> float:
    """The floor for a statistic estimated from a calibration capture and checked on a held-out one: how far a SECOND real calibration
    session's estimate would land from the held-out capture's, sigma * sqrt(1 / n_calibration + 1 / n_held_out).

    WHY not the held-out capture's standard error alone (found 2026-11-11, the hidden-truth tests): a fitted model carries its own
    calibration capture's noise too, so dividing by sigma / sqrt(n_held_out) fails a perfect calibration as soon as the held-out capture
    is averaged long enough. Real against real, at the same sample sizes, is the servo's rule (metrics.actuator.floor) said for a
    statistic.
    """

    if calibration_samples < 1 or held_out_samples < 1:
        raise ValueError("both captures need at least one sample")
    return float(sigma_one * math.sqrt(1.0 / calibration_samples + 1.0 / held_out_samples))


# --------------------------------------------------------------------------------------------------------------- the model errors


def reprojection_rms(predicted_px: np.ndarray, measured_px: np.ndarray) -> float:
    """Per-axis RMS of predicted minus measured pixel positions, (n, 2) each."""

    difference = np.asarray(predicted_px, float) - np.asarray(measured_px, float)
    return float(np.sqrt(np.mean(difference ** 2)))


def residual_rms(predicted: np.ndarray, measured: np.ndarray) -> float:
    difference = np.asarray(predicted, float) - np.asarray(measured, float)
    return float(np.sqrt(np.mean(difference ** 2)))


def noise_calibration(residuals: np.ndarray, predicted_sigma: np.ndarray) -> float:
    """std(residual / predicted sigma): 1.0 when the model's noise is the real noise (see NOISE_CALIBRATION_BAND)."""

    residuals = np.asarray(residuals, float)
    sigma = np.broadcast_to(np.asarray(predicted_sigma, float), residuals.shape)
    if np.any(sigma <= 0.0):
        raise ValueError("predicted sigma must be positive")
    return float(np.std(residuals / sigma, ddof=1))


# ------------------------------------------------------------------------------------------------------------------------ spectra


def spectral_angle(a: np.ndarray, b: np.ndarray) -> float:
    """The angle between two spectra (rad), the remote-sensing SAM (Kruse 1993): blind to an overall brightness scale, so it scores shape."""

    a = np.asarray(a, float).ravel()
    b = np.asarray(b, float).ravel()
    cosine = float(a @ b) / max(float(np.linalg.norm(a) * np.linalg.norm(b)), 1e-300)
    return float(math.acos(max(-1.0, min(1.0, cosine))))


def mean_spectral_angle(predicted: np.ndarray, measured: np.ndarray) -> float:
    """Mean SAM over spectra, rows of (n, bands)."""

    predicted = np.atleast_2d(np.asarray(predicted, float))
    measured = np.atleast_2d(np.asarray(measured, float))
    return float(np.mean([spectral_angle(p, m) for p, m in zip(predicted, measured, strict=True)]))


def repeat_spectral_angle(scans: np.ndarray) -> float:
    """The floor for spectra: mean SAM of each repeat scan to the mean of all repeats, (n_repeats, n_spectra, bands), x sqrt(n / (n - 1))."""

    scans = np.asarray(scans, float)
    n = scans.shape[0]
    if n < 2:
        raise ValueError("a spectral floor needs at least two repeat scans")
    mean = scans.mean(axis=0)
    angles = [mean_spectral_angle(scan, mean) for scan in scans]
    return float(np.mean(angles) * math.sqrt(n / (n - 1)))
