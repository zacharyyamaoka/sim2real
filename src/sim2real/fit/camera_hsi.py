"""camera_hsi's rungs as equations, and the fits that identify them (cards: camera_hsi M0 bands, M1 + band widths, M2 + smile and
keystone; M3's push-broom geometry is sysid's linescan_cell).

The detector of a push-broom spectrometer is (spatial column x, spectral pixel p). The model:

    wavelength seen   lambda(p, x) = poly(p + smile(x))             M0 band_centres = poly(p) at the slit's centre; M2 smile(x)
    band response     Gaussian of FWHM band_fwhm around lambda      M1
    spatial position  x_scene = x + keystone * (p - p_centre)       M2 keystone (a band's image of the slit shifted along the line)
    radiometry        DN = dark + gain * radiance                   M0 dark_white_refs (sysid's linescan.radiometry_refs fits it)

The fits take what a black-box test sees: a spectral lamp's frame (known lines in, peaks out) and an edge's frame (a known step in, its
position per band out).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = ["ARGON_LINES_NM", "HsiModel", "peak_centre", "fit_lamp_lines", "fit_smile", "fit_keystone", "LampFit"]

# Argon I emission lines in the 900-1700 nm SWIR (NIST Atomic Spectra Database, air wavelengths, rounded to 0.01 nm): the known
# inputs of the lamp test. Well separated, so each is one peak at a few-nm FWHM.
ARGON_LINES_NM = (912.30, 965.78, 1047.01, 1148.81, 1295.67, 1350.42, 1694.06)
FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))


@dataclass(frozen=True)
class HsiModel:
    """camera_hsi M0-M2 with the card's parameters: band_centres come from ``wavelength_coeffs`` (pixel -> nm, highest power first),
    band_fwhm is ``fwhm_nm``, smile_keystone_map is ``smile_coeffs`` (spectral px vs column offset from the centre, highest power
    first) with ``keystone_px_per_band``."""

    bands: int
    columns: int
    wavelength_coeffs: tuple[float, ...]
    fwhm_nm: float = 0.0
    smile_coeffs: tuple[float, ...] = (0.0,)
    keystone_px_per_band: float = 0.0

    @property
    def band_centres(self) -> np.ndarray:
        return np.polyval(self.wavelength_coeffs, np.arange(self.bands, dtype=float))

    def smile(self, column) -> np.ndarray:
        return np.polyval(self.smile_coeffs, np.asarray(column, float) - (self.columns - 1) / 2.0)

    def wavelength(self, spectral_px, column) -> np.ndarray:
        return np.polyval(self.wavelength_coeffs, np.asarray(spectral_px, float) + self.smile(column))

    def lamp_frame(self, lines_nm, intensities, *, noise: float = 0.0, rng: np.random.Generator | None = None) -> np.ndarray:
        """(columns, bands) DN of a lamp with these emission lines filling the slit."""
        p, x = np.meshgrid(np.arange(self.bands, dtype=float), np.arange(self.columns, dtype=float))
        lam = self.wavelength(p, x)
        sigma = max(self.fwhm_nm, 1e-6) / FWHM_PER_SIGMA
        frame = np.zeros_like(lam)
        for line, intensity in zip(lines_nm, intensities, strict=True):
            frame += intensity * np.exp(-0.5 * ((lam - line) / sigma) ** 2)
        if noise and rng is not None:
            frame = frame + rng.normal(0.0, noise, frame.shape)
        return frame

    def edge_frame(self, edge_column: float, *, blur_px: float = 0.7, noise: float = 0.0,
                   rng: np.random.Generator | None = None) -> np.ndarray:
        """(columns, bands) of a bright/dark step at ``edge_column`` on the slit, as each band images it (keystone shifts it)."""
        p, x = np.meshgrid(np.arange(self.bands, dtype=float), np.arange(self.columns, dtype=float))
        imaged = edge_column + self.keystone_px_per_band * (p - (self.bands - 1) / 2.0)
        frame = 0.5 * (1.0 + np.tanh((x - imaged) / blur_px))
        if noise and rng is not None:
            frame = frame + rng.normal(0.0, noise, frame.shape)
        return frame


def peak_centre(profile: np.ndarray, near: int, half_window: int = 3) -> tuple[float, float]:
    """(centre px, sigma px) of a Gaussian peak near ``near``: least squares of a parabola on the log of the samples (Caruana's
    method) over the top of the peak."""

    profile = np.asarray(profile, float)
    lo, hi = max(0, near - half_window), min(len(profile), near + half_window + 1)
    top = lo + int(np.argmax(profile[lo:hi]))
    lo, hi = max(0, top - 2), min(len(profile), top + 3)
    xs = np.arange(lo, hi, dtype=float)
    ys = np.log(np.clip(profile[lo:hi], 1e-9, None))
    a, b, _ = np.polyfit(xs, ys, 2)
    if a >= 0:
        return float(top), float("nan")
    return float(-b / (2.0 * a)), float(math.sqrt(-1.0 / (2.0 * a)))


@dataclass(frozen=True)
class LampFit:
    wavelength_coeffs: tuple[float, ...]
    fwhm_nm: float
    line_pixels: tuple[float, ...]
    residual_nm: tuple[float, ...]   # known line - fitted wavelength at its peak: the M0 fit's own error


def fit_lamp_lines(frame: np.ndarray, lines_nm, approximate_coeffs, *, degree: int = 2) -> LampFit:
    """Band centres and widths from a lamp frame (columns, bands): each known line's peak on the slit's centre column, located near where
    the nominal wavelength map ``approximate_coeffs`` (the datasheet's range, linear is enough) puts it; then a polynomial pixel -> nm."""

    frame = np.asarray(frame, float)
    centre = frame.shape[0] // 2
    profile = frame[max(0, centre - 1):centre + 2].mean(axis=0)  # three central columns: the slit centre, less noise
    bands = frame.shape[1]
    nominal = np.polyval(approximate_coeffs, np.arange(bands, dtype=float))
    pixels, sigmas, used = [], [], []
    for line in lines_nm:
        if not nominal.min() + 2 <= line <= nominal.max() - 2:
            continue
        guess = int(np.argmin(np.abs(nominal - line)))
        centre_px, sigma_px = peak_centre(profile, guess)
        if math.isfinite(sigma_px):
            pixels.append(centre_px)
            sigmas.append(sigma_px)
            used.append(line)
    if len(used) < degree + 2:
        raise ValueError(f"only {len(used)} lamp lines found; a degree-{degree} wavelength map needs {degree + 2}")
    coeffs = np.polyfit(pixels, used, degree)
    slope = np.polyval(np.polyder(coeffs), np.asarray(pixels))
    fwhm = float(np.median(np.asarray(sigmas) * np.abs(slope)) * FWHM_PER_SIGMA)
    residual = np.asarray(used) - np.polyval(coeffs, np.asarray(pixels))
    return LampFit(tuple(float(c) for c in coeffs), fwhm, tuple(pixels), tuple(float(r) for r in residual))


def fit_smile(frame: np.ndarray, line_pixel: float, *, degree: int = 2) -> tuple[float, ...]:
    """Smile: one lamp line's peak along every column. Where the line lands at p(x), p(x) + smile(x) is constant, so smile(x) =
    p(centre) - p(x); a polynomial in the column's offset from the centre (highest power first)."""

    frame = np.asarray(frame, float)
    columns = frame.shape[0]
    centres = np.array([peak_centre(frame[x], int(round(line_pixel)))[0] for x in range(columns)])
    offset = np.arange(columns, dtype=float) - (columns - 1) / 2.0
    coeffs = np.polyfit(offset, centres, degree)
    centre_value = np.polyval(coeffs, 0.0)
    smile = -coeffs
    smile[-1] = smile[-1] + centre_value
    return tuple(float(c) for c in smile)


def fit_keystone(frame: np.ndarray) -> float:
    """Keystone: an edge's column in every band (where the profile crosses half its range), then the slope against the band (px / band)."""

    frame = np.asarray(frame, float)
    columns, bands = frame.shape
    positions = []
    for p in range(bands):
        profile = frame[:, p]
        low, high = np.percentile(profile, 5), np.percentile(profile, 95)
        half = 0.5 * (low + high)
        above = np.nonzero(profile >= half)[0]
        i = int(above[0])
        if i == 0:
            positions.append(0.0)
            continue
        y0, y1 = profile[i - 1], profile[i]
        positions.append(i - 1 + (half - y0) / (y1 - y0) if y1 != y0 else float(i))
    slope, _ = np.polyfit(np.arange(bands, dtype=float), np.asarray(positions), 1)
    return float(slope)
