"""The camera types, proven the sim2real way: a hidden truth, a fit that never sees it, and a black-box fidelity that can fail.

For every rung a fit identifies: (1) the fit recovers the hidden parameters; (2) on HELD-OUT captures the fitted model is within
TWINNED_LIMIT x the real camera's own floor; (3) the nominal model (the datasheet: what a robot description gives before calibration) is
NOT, on the same captures. (3) is what keeps the ruler able to fail (feedback: an independent oracle and a metric that can fail).

And the kits are the cards' types: every rung key, parameter name, routine id and on-card metric id here is the card's.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim2real import cards as _cards  # noqa: F401  (the shim registers the cards package)
from sim2real.cards import registry as reg
from sim2real.fit import camera_hsi, camera_rgb, camera_rgbd
from sim2real.metrics import camera as metric
from sim2real.models import camera as cam
from sim2real.schedule import camera_configure

LIMIT = cam.TWINNED_LIMIT


# ------------------------------------------------------------------------------------------------------------- the kits are the cards


def test_the_twinned_limit_is_the_cards():
    assert cam.TWINNED_LIMIT == reg.TWINNED_LIMIT


@pytest.mark.parametrize("type_id", sorted(cam.CAMERA_KITS))
def test_every_kit_is_its_card(type_id):
    k = cam.kit(type_id)
    card = reg.CARDS[type_id]
    for rung in k.rungs:
        card_rung = reg.rung(card, rung.key)
        assert set(rung.parameters) == set(card_rung.parameter_names), (type_id, rung.key)
    card_routines = {r.id: r for r in reg.routines_for(type_id)}
    for rid in k.identify:
        assert rid in card_routines and card_routines[rid].kind == "identify", (type_id, rid)
    for rid in k.configure:
        assert rid in card_routines and card_routines[rid].kind == "configure", (type_id, rid)
        assert any(c.card == type_id for c in card_routines[rid].configures), (type_id, rid)
    assert set(k.configure) == {r.id for r in reg.routines_configuring(type_id)}, type_id
    card_metrics = {m.id for m in card.metrics}
    for f in k.fidelity:
        assert (f.id in card_metrics) == f.on_card, (type_id, f.id)
    assert set(k.members) == {m.card for m in card.members if m.card in reg.CARDS}, type_id


def test_a_robot_naming_types_gets_every_kit_and_its_members():
    """Zach: "robot types I can assign those generic types and then they get all of the stuff for those types"."""
    kits = cam.kits_for(["camera_rgbd", "camera_hsi", "camera_rgbd"])
    assert [k.type_id for k in kits] == ["camera_rgbd", "camera_rgb", "camera_hsi"]
    configure = {rid for k in kits for rid in k.configure}
    assert {"camera.exposure_lock", "hsi.integration_time"} <= configure
    with pytest.raises(KeyError):
        cam.kit("camera_thermal")


# --------------------------------------------------------------------------------------------------------- camera_rgb: M0 / M1 geometry

HIDDEN_K = camera_rgb.Intrinsics(912.3, 908.7, 641.2, 359.4, (-0.11, 0.06, 0.0008, -0.0005, -0.01))
DATASHEET_K = camera_rgb.Intrinsics(900.0, 900.0, 639.5, 359.5)   # nominal: the sensor's nominal focal length, centred, no distortion
BOARD = camera_rgb.board_points(9, 6, 0.03)
CORNER_NOISE_PX = 0.15


def board_view(rng, intrinsics, *, noise=CORNER_NOISE_PX):
    centre = BOARD.mean(axis=0)
    rvec = rng.uniform(-0.45, 0.45, 3) * np.array([1.0, 1.0, 0.4])
    R = camera_rgb.rodrigues(rvec)
    t = np.array([rng.uniform(-0.12, 0.12), rng.uniform(-0.07, 0.07), rng.uniform(0.45, 0.8)]) - R @ centre
    pixels = camera_rgb.project(intrinsics, rvec, t, BOARD)
    return pixels + rng.normal(0.0, noise, pixels.shape), (rvec, t)


@pytest.fixture(scope="module")
def geometry():
    rng = np.random.default_rng(11)
    train = [board_view(rng, HIDDEN_K)[0] for _ in range(18)]
    held_out = [board_view(rng, HIDDEN_K)[0] for _ in range(6)]
    clean, pose = board_view(rng, HIDDEN_K, noise=0.0)
    repeats = clean[None] + rng.normal(0.0, CORNER_NOISE_PX, (40, *clean.shape))
    return train, held_out, repeats


def test_zhang_recovers_the_hidden_lens(geometry):
    train, _, _ = geometry
    fit = camera_rgb.calibrate_planar(BOARD, train)
    k = fit.intrinsics
    assert abs(k.fx / HIDDEN_K.fx - 1) < 0.003 and abs(k.fy / HIDDEN_K.fy - 1) < 0.003, (k.fx, k.fy)
    assert abs(k.cx - HIDDEN_K.cx) < 2.0 and abs(k.cy - HIDDEN_K.cy) < 2.0, (k.cx, k.cy)
    assert abs(k.distortion[0] - HIDDEN_K.distortion[0]) < 0.01
    # WHY the field and not k2 / k3 one by one: on a board this size they trade off (a k2 error is absorbed by k3), and only the
    # displacement they make together is observable; over the region the views covered it must match the hidden lens's
    covered = np.concatenate(train)
    rays = np.column_stack([(covered[:, 0] - HIDDEN_K.cx) / HIDDEN_K.fx, (covered[:, 1] - HIDDEN_K.cy) / HIDDEN_K.fy, np.ones(len(covered))])
    hidden_px = camera_rgb.project(HIDDEN_K, np.zeros(3), np.zeros(3), rays)
    fitted_px = camera_rgb.project(k, np.zeros(3), np.zeros(3), rays)
    fitted_px -= np.array([k.cx - HIDDEN_K.cx, k.cy - HIDDEN_K.cy])      # compare the distortion field, not the principal point
    assert np.max(np.abs(fitted_px - hidden_px)) < 1.0, np.max(np.abs(fitted_px - hidden_px))
    assert fit.rms_px < 1.5 * CORNER_NOISE_PX


def test_geometry_fidelity_twinned_after_m1_not_before(geometry):
    train, held_out, repeats = geometry
    m1 = camera_rgb.calibrate_planar(BOARD, train)
    m0 = camera_rgb.calibrate_planar(BOARD, train, distortion=False)
    nominal = camera_rgb.PlanarCalibration(DATASHEET_K, (), (), math.nan, {})
    scores = {name: cam.rgb_geometry_fidelity(c, BOARD, held_out, repeats) for name, c in
              (("M1", m1), ("M0", m0), ("nominal", nominal))}
    assert scores["M1"].twinned(LIMIT), scores["M1"]
    assert not scores["M0"].twinned(LIMIT), scores["M0"]          # the distortion rung matters on this lens
    assert not scores["nominal"].twinned(LIMIT), scores["nominal"]


def test_zhang_agrees_with_opencv_where_opencv_is_installed(geometry):
    cv2 = pytest.importorskip("cv2")
    train, _, _ = geometry
    mine = camera_rgb.calibrate_planar(BOARD, train).intrinsics
    _, K, dist, _, _ = cv2.calibrateCamera([BOARD.astype(np.float32)] * len(train), [v.astype(np.float32) for v in train], (1280, 720),
                                           None, None)
    assert abs(K[0, 0] - mine.fx) < 0.5 and abs(K[1, 1] - mine.fy) < 0.5 and abs(K[0, 2] - mine.cx) < 0.5
    assert abs(dist.ravel()[0] - mine.distortion[0]) < 1e-3


# ------------------------------------------------------------------------------------------------------- camera_rgb: M2 photometry

HIDDEN_RESPONSE = camera_rgb.ExposureResponse(black_dn=64.0, response_dn_per_unit=3.2, saturation_dn=4095.0, system_gain_dn_per_e=0.42,
                                              read_noise_dn=2.5)


def grey_patch(rng, exposure, frames=16, pixels=400):
    """A grey patch through the hidden sensor: Poisson electrons, read noise, 12-bit clip."""
    signal = HIDDEN_RESPONSE.response_dn_per_unit * exposure
    electrons = rng.poisson(signal / HIDDEN_RESPONSE.system_gain_dn_per_e, (frames, pixels))
    dn = HIDDEN_RESPONSE.black_dn + electrons * HIDDEN_RESPONSE.system_gain_dn_per_e + rng.normal(0, HIDDEN_RESPONSE.read_noise_dn,
                                                                                                    (frames, pixels))
    return np.clip(dn, 0, 4095)


def test_photon_transfer_recovers_black_response_gain_and_read_noise():
    rng = np.random.default_rng(3)
    exposures = np.geomspace(5, 1600, 14)
    frames = [grey_patch(rng, e) for e in exposures]
    means = [f.mean() for f in frames]
    variances = [np.mean(np.var(f, axis=0, ddof=1)) for f in frames]
    fit = camera_rgb.fit_exposure_response(exposures, means, variances)
    assert abs(fit.black_dn - 64.0) < 1.0 and abs(fit.response_dn_per_unit / 3.2 - 1) < 0.01
    assert abs(fit.system_gain_dn_per_e / 0.42 - 1) < 0.05 and abs(fit.read_noise_dn / 2.5 - 1) < 0.25
    held_exposures = np.array([40.0, 150.0, 420.0, 900.0])
    held = [grey_patch(rng, e) for e in held_exposures]
    good = cam.rgb_photometric_fidelity(fit, held_exposures, held, calibration_samples=16 * 400)
    nominal = camera_rgb.ExposureResponse(0.0, 3.0, 4095.0, 1.0, 0.0)  # a datasheet: no black level, a rounded response
    bad = cam.rgb_photometric_fidelity(nominal, held_exposures, held, calibration_samples=16 * 400)
    assert good.twinned(LIMIT), good
    assert not bad.twinned(LIMIT), bad


# ---------------------------------------------------------------------------------------------------- camera_rgb: M2 / M3 timing


def test_latency_and_line_delay_are_recovered():
    rng = np.random.default_rng(5)
    events = np.sort(rng.uniform(0, 30, 60))
    stamps = events + 0.0423 + rng.normal(0, 0.0012, events.size)
    latency = camera_rgb.fit_latency(events[:40], stamps[:40])
    assert abs(latency.latency_s - 0.0423) < 0.0008 and 0.0006 < latency.jitter_s < 0.0020
    good = cam.rgb_latency_fidelity(latency, events[40:], stamps[40:], calibration_samples=40)
    bad = cam.rgb_latency_fidelity(camera_rgb.Latency(0.0, 0.0), events[40:], stamps[40:], calibration_samples=40)  # nominal: no latency modelled
    assert good.twinned(LIMIT) and not bad.twinned(LIMIT), (good, bad)

    rows = np.arange(0, 720, 8, dtype=float)
    hidden_delay = 18.5e-6
    columns = 300.0 + 2000.0 * hidden_delay * rows + rng.normal(0, 0.2, rows.size)
    assert abs(camera_rgb.fit_line_delay(rows, columns, 2000.0) / hidden_delay - 1) < 0.03


# --------------------------------------------------------------------------------------------------------------- camera_rgbd: M1 / M2

HIDDEN_DEPTH = camera_rgbd.DepthModel(baseline_m=0.050, focal_px=640.0, subpixel_sigma=0.085, depth_bias_coeffs=(0.004, -0.002, 0.0015))


def test_flat_target_recovers_noise_law_and_bias_and_the_twin_holds_out():
    rng = np.random.default_rng(7)
    train_z = np.linspace(0.4, 1.6, 7)
    stats = [camera_rgbd.flat_target_statistics(HIDDEN_DEPTH.simulate(np.full(2000, z), 30, rng)) for z in train_z]
    fit = camera_rgbd.fit_flat_target(train_z, [s[0] for s in stats], [s[1] for s in stats], focal_px=640.0, baseline_m=0.050)
    assert abs(fit.subpixel_sigma / 0.085 - 1) < 0.03, fit.subpixel_sigma
    z_check = np.linspace(0.4, 1.6, 25)
    assert np.max(np.abs(fit.bias(z_check) - HIDDEN_DEPTH.bias(z_check))) < 3e-4

    held_z = np.array([0.5, 0.9, 1.3, 1.7])
    held = [HIDDEN_DEPTH.simulate(np.full(2000, z), 30, rng) for z in held_z]
    good = cam.rgbd_depth_fidelity(fit, held_z, held, calibration_samples=2000 * 30)
    m1 = camera_rgbd.DepthModel(0.050, 640.0, fit.subpixel_sigma)   # no bias rung
    assert good.twinned(LIMIT), good
    assert not cam.rgbd_depth_fidelity(m1, held_z, held, calibration_samples=2000 * 30).twinned(LIMIT)
    lo, hi = metric.NOISE_CALIBRATION_BAND
    assert lo <= cam.rgbd_noise_calibration(fit, held_z, held) <= hi
    nominal_noise = camera_rgbd.DepthModel(0.050, 640.0, 0.02, fit.depth_bias_coeffs)  # a datasheet's optimistic noise
    assert cam.rgbd_noise_calibration(nominal_noise, held_z, held) > hi


# --------------------------------------------------------------------------------------------------------------------- camera_hsi

HIDDEN_HSI = camera_hsi.HsiModel(bands=224, columns=320, wavelength_coeffs=(0.0004, 3.6, 900.0), fwhm_nm=7.5,
                                 smile_coeffs=(2.0e-5, 0.0, 0.0), keystone_px_per_band=0.004)
DATASHEET_HSI_COEFFS = (3.7, 900.0)   # nominal: "900-1730 nm over 224 bands", linear


def lamp(rng, model=HIDDEN_HSI, noise=2.0):
    return model.lamp_frame(camera_hsi.ARGON_LINES_NM, [1000.0] * len(camera_hsi.ARGON_LINES_NM), noise=noise, rng=rng)


def test_lamp_lines_recover_band_centres_and_widths():
    rng = np.random.default_rng(13)
    fit = camera_hsi.fit_lamp_lines(lamp(rng), camera_hsi.ARGON_LINES_NM, DATASHEET_HSI_COEFFS)
    fitted = camera_hsi.HsiModel(224, 320, fit.wavelength_coeffs, fit.fwhm_nm)
    error = fitted.band_centres - HIDDEN_HSI.band_centres
    assert np.sqrt(np.mean(error ** 2)) < 0.3, np.sqrt(np.mean(error ** 2))
    assert abs(fit.fwhm_nm / 7.5 - 1) < 0.05, fit.fwhm_nm

    held = [lamp(rng) for _ in range(8)]
    good = cam.hsi_wavelength_fidelity(fitted, held, camera_hsi.ARGON_LINES_NM, calibration_frames=1)
    nominal = camera_hsi.HsiModel(224, 320, DATASHEET_HSI_COEFFS, 0.0)
    bad = cam.hsi_wavelength_fidelity(nominal, held, camera_hsi.ARGON_LINES_NM, calibration_frames=1)
    assert good.twinned(LIMIT), good
    assert not bad.twinned(LIMIT), bad


def test_smile_and_keystone_are_recovered():
    rng = np.random.default_rng(17)
    frame = lamp(rng, noise=1.0)
    line_px = float(np.interp(1295.67, HIDDEN_HSI.band_centres, np.arange(224.0)))
    smile = camera_hsi.fit_smile(frame, line_px)
    assert abs(smile[0] / 2.0e-5 - 1) < 0.1, smile
    edge = HIDDEN_HSI.edge_frame(150.3, noise=0.005, rng=rng)
    assert abs(camera_hsi.fit_keystone(edge) / 0.004 - 1) < 0.1


def material_spectra(wavelengths):
    """Smooth stand-ins with absorption dips (not library data): the twin test needs held-out, non-flat spectra."""
    out = []
    for base, dips in ((0.8, ((1210, 35, 0.25), (1725, 35, 0.3))), (0.75, ((1660, 40, 0.2), (1130, 45, 0.1))),
                       (0.6, ((1450, 60, 0.3),))):
        r = np.full(wavelengths.shape, base)
        for centre, width, depth in dips:
            r -= depth * np.exp(-0.5 * ((wavelengths - centre) / width) ** 2)
        out.append(r)
    return np.array(out)


def band_integrate(model, spectra_on_grid, grid):
    """Each band's reading of a spectrum: its Gaussian response; a zero FWHM (a datasheet with no width) reads the centre's sample."""
    if model.fwhm_nm <= 0.0:
        return np.array([np.interp(model.band_centres, grid, s) for s in spectra_on_grid])
    sigma = model.fwhm_nm / camera_hsi.FWHM_PER_SIGMA
    weights = np.exp(-0.5 * ((grid[None, :] - model.band_centres[:, None]) / sigma) ** 2)
    weights /= weights.sum(axis=1, keepdims=True)
    return spectra_on_grid @ weights.T


def test_the_twin_cube_is_twinned_after_calibration_not_before():
    rng = np.random.default_rng(19)
    grid = np.arange(850.0, 1780.0, 0.5)
    truth = material_spectra(grid)
    measured = band_integrate(HIDDEN_HSI, truth, grid)
    scans = measured[None] + rng.normal(0, 0.004, (12, *measured.shape))
    fit = camera_hsi.fit_lamp_lines(lamp(rng), camera_hsi.ARGON_LINES_NM, DATASHEET_HSI_COEFFS)
    fitted = camera_hsi.HsiModel(224, 320, fit.wavelength_coeffs, fit.fwhm_nm)
    nominal = camera_hsi.HsiModel(224, 320, DATASHEET_HSI_COEFFS, 0.0)
    good = cam.hsi_spectral_fidelity(band_integrate(fitted, truth, grid), scans)
    bad = cam.hsi_spectral_fidelity(band_integrate(nominal, truth, grid), scans)
    assert good.twinned(LIMIT), good
    assert not bad.twinned(LIMIT), bad


# ------------------------------------------------------------------------------------------------------------ camera_hsi: configure


class FakeLineCamera:
    """A white tile through a line camera: DN = dark + k * t * radiance(band), noisy, clipped at 12 bits."""

    integration_range_s = (1e-5, 0.02)
    full_scale_dn = 4095.0

    def __init__(self, brightness: float, seed: int = 0):
        self.t = 1e-3
        self.radiance = brightness * (0.6 + 0.4 * np.sin(np.linspace(0.2, 2.8, 64)))
        self.rng = np.random.default_rng(seed)

    def set_integration(self, seconds):
        self.t = float(seconds)

    def grab_lines(self, count):
        dn = 64.0 + 2.0e6 * self.t * self.radiance
        cube = np.broadcast_to(dn, (count, 100, 64)) + self.rng.normal(0, 3.0, (count, 100, 64))
        return np.clip(cube, 0, self.full_scale_dn)


def test_integration_lands_on_the_target_and_never_clips():
    rate = camera_configure.line_rate_for(0.5, 0.001)       # 0.5 m/s belt, 1 mm along-track pixels -> 500 lines/s
    assert rate == 500.0
    bright = camera_configure.configure_integration(FakeLineCamera(1.0), slice(20, 80), line_rate_hz=rate)
    assert bright.limited_by == "target" and 0.83 <= bright.peak_fraction <= 0.85 and bright.saturated_bands == 0, bright
    dim = camera_configure.configure_integration(FakeLineCamera(0.05), slice(20, 80), line_rate_hz=rate)
    assert dim.limited_by == "line period" and dim.integration_time_s == pytest.approx(1 / rate), dim
    assert dim.peak_fraction < 0.85
