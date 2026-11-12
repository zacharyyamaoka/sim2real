"""The camera types as kits: name a type, get its model rungs, its identify, configure and tune routines and its black-box fidelity metrics.

Zach, 2026-11-11: "robot types I can assign those generic types and then they get all of the stuff for those types kinda like
automatically". A robot's camera names a type id (camera_rgb, camera_rgbd, camera_hsi: the cards' ids); ``kit(type_id)`` hands back
everything that type has here, and ``kits_for`` adds what its members bring (an RGBD camera's colour stream is a camera_rgb).

    from sim2real.models.camera import kits_for
    for k in kits_for(["camera_rgbd"]):           # -> camera_rgbd, then camera_rgb (its member)
        k.rungs, k.identify, k.configure, k.tune, k.fidelity

The cards (sim2real.cards, the stdlib contract) hold each routine's record: what it identifies or configures, its time, equipment and
status. This module is the code behind those ids; tests/test_camera_types.py holds the two to each other (every rung key and parameter
name here is the card's, every routine id here is a card routine of that type).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from ..fit import camera_hsi, camera_rgb, camera_rgbd
from ..metrics import camera as metric
from ..schedule import aruco_exposure, camera_configure

__all__ = ["TWINNED_LIMIT", "Rung", "FidelityMetric", "CameraKit", "CAMERA_KITS", "kit", "kits_for",
           "rgb_geometry_fidelity", "rgb_photometric_fidelity", "rgb_latency_fidelity", "rgbd_depth_fidelity", "rgbd_noise_calibration",
           "hsi_wavelength_fidelity", "hsi_spectral_fidelity"]

# WHY a copy and not an import: models may not import cards (sim2real's layer rule, tests/test_layers.py); the test pins it to
# cards.schema.TWINNED_LIMIT, the one rule for every type: a model is twinned within 1.5 x the real camera's own floor.
TWINNED_LIMIT = 1.5
BAM_CAMERA_CALIBRATION = "bam_ws:src/core/mdp/setup/bam_camera_calibration/src/bam_camera_calibration/calibrate.py"


@dataclass(frozen=True)
class Rung:
    """One card rung and the code that evaluates it. ``parameters`` are the card rung's parameter names; ``code`` the callable or record."""

    key: str
    name: str
    parameters: tuple[str, ...]
    code: object
    note: str = ""


@dataclass(frozen=True)
class FidelityMetric:
    """A black-box model-vs-real comparison: what is compared, the floor it is divided by, and the function computing both."""

    id: str                      # the card's metric id where the card has one; else marked proposed
    compares: str
    floor: str
    unit: str
    evaluate: Callable[..., metric.Fidelity]
    on_card: bool = True


@dataclass(frozen=True)
class CameraKit:
    type_id: str
    title: str
    rungs: tuple[Rung, ...]
    identify: dict[str, Callable] = field(default_factory=dict)
    configure: dict[str, object] = field(default_factory=dict)   # a callable here, or "<repo>:<path>" where the driver lives
    fidelity: tuple[FidelityMetric, ...] = ()
    members: tuple[str, ...] = ()
    # kind "tune" (PEP 0001): settings chosen by optimising a metric with no real reference, e.g. exposure / gain / fps for ArUco accuracy
    tune: dict[str, Callable] = field(default_factory=dict)

    def rung(self, key: str) -> Rung:
        for r in self.rungs:
            if r.key == key:
                return r
        raise KeyError(f"{self.type_id} has no rung {key!r}")


# ------------------------------------------------------------------------------------------------------------- fidelity evaluators


def rgb_geometry_fidelity(calibration: camera_rgb.PlanarCalibration, board: np.ndarray, held_out_views,
                          repeat_views: np.ndarray) -> metric.Fidelity:
    """Reprojection RMS on views the calibration never saw (each view's board pose solved with K and distortion held: the pose is the
    scene, not the camera), over the corner jitter of a static board (repeat_views: (frames, corners, 2))."""

    predicted = []
    measured = []
    for view in held_out_views:
        rvec, tvec = camera_rgb.solve_pose(calibration.intrinsics, board, view)
        predicted.append(camera_rgb.project(calibration.intrinsics, rvec, tvec, board))
        measured.append(np.asarray(view, float))
    error = metric.reprojection_rms(np.concatenate(predicted), np.concatenate(measured))
    return metric.fidelity("camera.intrinsics", error, metric.jitter_floor(repeat_views), "px", sum(len(m) for m in measured))


def rgb_photometric_fidelity(response: camera_rgb.ExposureResponse, exposure, frames_per_exposure, *,
                             calibration_samples: int) -> metric.Fidelity:
    """Predicted mean DN at exposures the sweep never used vs the measured mean (frames: (n, pixels) each), over the session floor:
    the patch's temporal noise at the calibration's and the held-out capture's sample counts (``calibration_samples``: frames x pixels
    per exposure of the sweep)."""

    predicted = response.mean(np.asarray(exposure, float))
    measured = np.array([np.mean(f) for f in frames_per_exposure])
    sigma = float(np.sqrt(np.mean([metric.temporal_noise(f) ** 2 for f in frames_per_exposure])))
    floor = metric.session_floor(sigma, calibration_samples, int(np.asarray(frames_per_exposure[0]).size))
    return metric.fidelity("camera.photometric", metric.residual_rms(predicted, measured), floor, "DN", len(measured))


def rgb_latency_fidelity(latency: camera_rgb.Latency, event_times_s, first_seen_stamps_s, *, calibration_samples: int) -> metric.Fidelity:
    """The model's latency vs the held-out edges' median delay, over the session floor of a median (sqrt(pi / 2) x the mean's)."""
    delays = np.asarray(first_seen_stamps_s, float) - np.asarray(event_times_s, float)
    error = abs(float(np.median(delays)) - latency.latency_s)
    jitter = 1.4826 * float(np.median(np.abs(delays - np.median(delays))))
    floor = math.sqrt(math.pi / 2.0) * metric.session_floor(jitter, calibration_samples, len(delays))
    return metric.fidelity("camera.latency_model", error, floor, "s", len(delays))


def rgbd_depth_fidelity(model: camera_rgbd.DepthModel, true_z_m, depth_frames_per_z, *, calibration_samples: int) -> metric.Fidelity:
    """Held-out distances: |predicted mean depth - measured mean depth| RMS over distance bands, over the session floor at each distance
    (the temporal noise there, at the calibration's samples per distance and the held-out capture's): the twin's depth is as close as a
    second real calibration session would be."""

    true_z = np.asarray(true_z_m, float)
    predicted = model.mean_depth(true_z)
    stats = [camera_rgbd.flat_target_statistics(f) for f in depth_frames_per_z]
    measured = np.array([s[0] for s in stats])
    floors = np.array([metric.session_floor(s[1], calibration_samples, int(np.asarray(f).size))
                       for s, f in zip(stats, depth_frames_per_z, strict=True)])
    return metric.fidelity("depth.cloud_vs_sim", metric.residual_rms(predicted, measured), float(np.sqrt(np.mean(floors ** 2))),
                           "m", len(true_z))


def rgbd_noise_calibration(model: camera_rgbd.DepthModel, true_z_m, depth_frames_per_z) -> float:
    """std of (depth - mean) / the model's sigma(z), pooled over distances: 1.0 when M1's noise law is the camera's."""
    scores = []
    for z, frames in zip(np.asarray(true_z_m, float), depth_frames_per_z, strict=True):
        frames = np.asarray(frames, float)
        scores.append(((frames - frames.mean(axis=0)) / model.sigma(z)).ravel() * np.sqrt(frames.shape[0] / (frames.shape[0] - 1)))
    return float(np.std(np.concatenate(scores)))


def hsi_wavelength_fidelity(model: camera_hsi.HsiModel, lamp_frames, lines_nm, *, calibration_frames: int) -> metric.Fidelity:
    """Held-out lamp frames: each line's measured peak wavelength (its peak pixel through the real camera's map is unknown, so: the model's
    predicted pixel for the line vs the measured peak pixel, in nm through the model's own dispersion), over the peak's repeatability."""

    frames = [np.asarray(f, float) for f in lamp_frames]
    centre = frames[0].shape[0] // 2
    dispersion = np.polyder(np.asarray(model.wavelength_coeffs, float))
    lam = model.band_centres
    peaks = []
    for frame in frames:
        profile = frame[max(0, centre - 1):centre + 2].mean(axis=0)
        row = []
        for line in lines_nm:
            if lam.min() + 2 <= line <= lam.max() - 2:
                row.append(camera_hsi.peak_centre(profile, int(np.argmin(np.abs(lam - line))))[0])
        peaks.append(row)
    peaks = np.asarray(peaks)
    usable = [line for line in lines_nm if lam.min() + 2 <= line <= lam.max() - 2]
    nm_per_px = np.abs(np.polyval(dispersion, peaks.mean(axis=0)))
    predicted_px = np.array([np.interp(line, lam, np.arange(model.bands, dtype=float)) for line in usable])
    error_nm = metric.residual_rms(predicted_px * nm_per_px, peaks.mean(axis=0) * nm_per_px)
    floor_nm = metric.session_floor(metric.jitter_floor(peaks[:, :, None] * nm_per_px[None, :, None]), calibration_frames, len(frames))
    return metric.fidelity("hsi.wavelength", error_nm, floor_nm, "nm", len(usable))


def hsi_spectral_fidelity(predicted_spectra, measured_scans) -> metric.Fidelity:
    """Spectral angle between the model's spectra of held-out materials and the measured mean, over the repeat scans' own angle
    (measured_scans: (repeats, materials, bands))."""
    scans = np.asarray(measured_scans, float)
    error = metric.mean_spectral_angle(predicted_spectra, scans.mean(axis=0))
    floor = metric.repeat_spectral_angle(scans) / np.sqrt(scans.shape[0])
    return metric.fidelity("hsi.twin_cube", error, floor, "rad", scans.shape[1])


# --------------------------------------------------------------------------------------------------------------------------- kits

CAMERA_KITS: dict[str, CameraKit] = {
    "camera_rgb": CameraKit(
        "camera_rgb", "RGB camera",
        rungs=(
            Rung("M0", "Pinhole", ("fx_fy", "cx_cy", "extrinsics"), camera_rgb.project, "distortion all zero"),
            Rung("M1", "+ Brown-Conrady distortion", ("fx_fy", "cx_cy", "extrinsics", "distortion"), camera_rgb.project),
            Rung("M2", "+ exposure response and latency", ("fx_fy", "cx_cy", "extrinsics", "distortion", "exposure_response", "latency_s"),
                 camera_rgb.ExposureResponse),
            Rung("M3", "Rolling shutter: + line delay",
                 ("fx_fy", "cx_cy", "extrinsics", "distortion", "exposure_response", "latency_s", "line_delay_s"), camera_rgb.fit_line_delay),
        ),
        identify={"camera.intrinsics_charuco": camera_rgb.calibrate_planar,
                  "camera.exposure_response_ptc": camera_rgb.fit_exposure_response,
                  "camera.latency_led": camera_rgb.fit_latency,
                  "camera.rolling_shutter_target": camera_rgb.fit_line_delay},
        configure={"camera.exposure_lock": BAM_CAMERA_CALIBRATION, "camera.exposure_for_task": BAM_CAMERA_CALIBRATION,
                   "camera.focus_lock": "not implemented"},
        fidelity=(
            FidelityMetric("camera.intrinsics", "where known board corners land (held-out views)", "corner jitter on a static board", "px",
                           rgb_geometry_fidelity),
            FidelityMetric("camera.photometric", "a grey patch's mean DN at exposures the fit never used", "its temporal noise, session floor",
                           "DN", rgb_photometric_fidelity, on_card=False),
            FidelityMetric("camera.latency_model", "event-to-stamp delay on held-out LED edges", "stamp jitter, session floor", "s", rgb_latency_fidelity,
                           on_card=False),
        ),
        tune={"camera.exposure_for_aruco": aruco_exposure.tune},
    ),
    "camera_rgbd": CameraKit(
        "camera_rgbd", "RGBD camera",
        rungs=(
            Rung("M0", "Ideal stereo", ("baseline_m", "depth_scale", "depth_to_color"), camera_rgbd.DepthModel, "subpixel 0, no bias"),
            Rung("M1", "+ disparity noise", ("baseline_m", "depth_scale", "subpixel_sigma", "depth_to_color"), camera_rgbd.stereo_sigma),
            Rung("M2", "+ depth bias", ("baseline_m", "depth_scale", "subpixel_sigma", "depth_to_color", "depth_bias_coeffs"),
                 camera_rgbd.DepthModel),
        ),
        identify={"rgbd.flat_target_noise": camera_rgbd.fit_flat_target},
        configure={"camera.exposure_lock": BAM_CAMERA_CALIBRATION, "camera.exposure_for_task": BAM_CAMERA_CALIBRATION,
                   "rgbd.depth_emitter_settings": "not implemented"},
        fidelity=(
            FidelityMetric("depth.cloud_vs_sim", "a flat surface's depth at held-out distances", "the depth noise there, session floor", "m",
                           rgbd_depth_fidelity),
        ),
        members=("camera_rgb",),
        tune={"camera.exposure_for_aruco": aruco_exposure.tune},
    ),
    "camera_hsi": CameraKit(
        "camera_hsi", "Hyperspectral camera",
        rungs=(
            Rung("M0", "Ideal spectral bands", ("band_centres", "dark_white_refs"), camera_hsi.HsiModel, "fwhm and smile zero"),
            Rung("M1", "+ band widths", ("band_centres", "dark_white_refs", "band_fwhm"), camera_hsi.HsiModel),
            Rung("M2", "+ smile and keystone", ("band_centres", "dark_white_refs", "band_fwhm", "smile_keystone_map"), camera_hsi.HsiModel),
        ),
        identify={"hsi.lamp_lines": camera_hsi.fit_lamp_lines, "hsi.smile_keystone_bars": camera_hsi.fit_smile},
        configure={"hsi.integration_time": camera_configure.configure_integration, "camera.focus_lock": "not implemented"},
        fidelity=(
            FidelityMetric("hsi.wavelength", "known lamp lines' positions on held-out frames", "the line centre's repeatability", "nm",
                           hsi_wavelength_fidelity, on_card=False),
            FidelityMetric("hsi.twin_cube", "held-out materials' spectra, model vs measured", "spectral angle between repeat scans", "rad",
                           hsi_spectral_fidelity),
        ),
    ),
}


def kit(type_id: str) -> CameraKit:
    try:
        return CAMERA_KITS[type_id]
    except KeyError:
        raise KeyError(f"no camera type {type_id!r} (types: {', '.join(CAMERA_KITS)})") from None


def kits_for(type_ids) -> tuple[CameraKit, ...]:
    """Every kit a robot's cameras bring, members included, each once, in first-seen order."""
    seen: dict[str, CameraKit] = {}

    def add(type_id: str) -> None:
        if type_id in seen:
            return
        k = kit(type_id)
        seen[type_id] = k
        for member in k.members:
            add(member)

    for type_id in type_ids:
        add(type_id)
    return tuple(seen.values())
