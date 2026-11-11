"""Camera configure routines: set a camera up under the deployment's conditions, the way homing finds a zero. Nothing here fits a model.

Zach, 2026-11-11: calibration routines that are "like homing, etc. we are not identifying a model so much as automatically configuring
it". cards routine kind "configure"; each routine names the settings it writes (cards ``configures``).

- camera_rgb / camera_rgbd colour: exposure, gain and white balance locked under the lights (``camera.exposure_lock``,
  ``camera.exposure_for_task``) live in bam_ws src/core/mdp/setup/bam_camera_calibration, beside the RealSense driver they write to.
- camera_hsi: ``configure_integration`` here (``hsi.integration_time``): the line rate from the belt, then the longest integration that
  fits the line period and keeps the white tile's brightest band at a target fraction of full scale, proved on a fresh capture.

The camera is a black box behind ``LineCameraControls``: write a setting, read lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

__all__ = ["LineCameraControls", "IntegrationSetting", "line_rate_for", "configure_integration"]


@runtime_checkable
class LineCameraControls(Protocol):
    """A line camera's set-up surface: the integration range it accepts, its full-scale DN, and lines of (columns, bands)."""

    integration_range_s: tuple[float, float]
    full_scale_dn: float

    def set_integration(self, seconds: float) -> None: ...

    def grab_lines(self, count: int) -> np.ndarray: ...  # (count, columns, bands) DN


@dataclass(frozen=True)
class IntegrationSetting:
    """What ``hsi.integration_time`` writes (cards configures: integration_time_s, line_rate_hz) and the proof it held."""

    integration_time_s: float
    line_rate_hz: float
    peak_fraction: float          # the white tile's brightest band / full scale, on a fresh capture at the setting
    saturated_bands: int          # bands of the white tile at or above full scale on that capture (0 when configured right)
    limited_by: str               # "target" | "line period" | "camera maximum"
    probes: int


def line_rate_for(belt_speed_m_s: float, along_track_pixel_m: float) -> float:
    """Lines per second so each line covers one along-track pixel of the belt: square pixels on the moving scene."""
    if belt_speed_m_s <= 0 or along_track_pixel_m <= 0:
        raise ValueError("belt speed and along-track pixel size must be positive")
    return belt_speed_m_s / along_track_pixel_m


def _peak(camera: LineCameraControls, columns: slice, lines: int) -> tuple[float, int]:
    cube = np.asarray(camera.grab_lines(lines), float)[:, columns, :]
    per_band = cube.mean(axis=(0, 1))
    saturated = int(np.sum(cube.max(axis=(0, 1)) >= camera.full_scale_dn))
    return float(per_band.max() / camera.full_scale_dn), saturated


def configure_integration(camera: LineCameraControls, white_columns: slice, *, line_rate_hz: float, target_fraction: float = 0.85,
                          tolerance: float = 0.01, lines: int = 20, max_probes: int = 30) -> IntegrationSetting:
    """The longest integration (<= the line period, <= the camera's maximum) whose white-tile brightest band is at most
    ``target_fraction`` of full scale. Bisection on log integration time: the DN rises with integration time, so the boundary is one
    crossing. WHY 85 %: the white reference must sit high in the range for the reflectance's resolution, with room for the lamp's drift
    and the tile's hot spots before a band clips (a clipped white makes every reflectance in that band wrong)."""

    if not 0.1 <= target_fraction < 1.0:
        raise ValueError("target_fraction must be in [0.1, 1)")
    low_limit, high_limit = camera.integration_range_s
    period = 1.0 / line_rate_hz
    ceiling = min(high_limit, period)
    limited_by = "line period" if period < high_limit else "camera maximum"
    probes = 0

    def measure(seconds: float) -> float:
        nonlocal probes
        probes += 1
        camera.set_integration(seconds)
        return _peak(camera, white_columns, lines)[0]

    if measure(ceiling) <= target_fraction:
        chosen = ceiling
    else:
        limited_by = "target"
        low, high = low_limit, ceiling
        if measure(low) > target_fraction:
            chosen = low
        else:
            while probes < max_probes and high / low > 1.0 + 1e-4:
                middle = float(np.sqrt(low * high))
                value = measure(middle)
                if value <= target_fraction:
                    low = middle
                    if target_fraction - value <= tolerance:
                        break
                else:
                    high = middle
            chosen = low
    camera.set_integration(chosen)
    peak, saturated = _peak(camera, white_columns, lines)
    return IntegrationSetting(chosen, line_rate_hz, peak, saturated, limited_by, probes + 1)
