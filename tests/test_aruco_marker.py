"""The ArUco Marker generic type and its routines (PEP 0001, docs/peps/0001-sim2real-docs-site-and-calibrate-backend.md, the aruco lane).

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_aruco_marker.py

Written by the designer BEFORE the type exists (red). The builder may not edit this file. Every hidden truth here is the TEST's: the
scenes, the renderer, the noise and the tolerances live in this file, and the code under test sees only what a real rig would see
(pixels, caliper readings, frames from a camera it can set). Zach's asks (2026-11-11): bundle adjustment, a caliper check of the printed
size, ID confirmation, and a camera tuned (exposure, gain, FPS) for ArUco ACCURACY rather than mean grey or markers read.

Ladder files: each graded routine's recovery at 0x / 1x / 3x / 10x is written to sysid/results/routine_ladders/<routine id>.json
(schema sim2real.routine_ladder/1, read by sim2real.calibration.recovery) BY THIS TEST, so the committed numbers are this code's:

    SIM2REAL_WRITE_LADDERS=1 env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/sim2real /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_aruco_marker.py -k ladder

Without the variable, the test re-derives every level and compares it with the committed file.
"""

from __future__ import annotations

import json
import math
import os
import zlib
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
LADDERS = REPO / "sysid" / "results" / "routine_ladders"
LEVELS = ("0x", "1x", "3x", "10x")
SCALE = {"0x": 0.0, "1x": 1.0, "3x": 3.0, "10x": 10.0}
WRITE = os.environ.get("SIM2REAL_WRITE_LADDERS") == "1"

TYPE = "aruco_marker"
MODELS = ("M0.kinematics.nominal", "M1.kinematics.as_built", "M2.kinematics.print_scale")
ROUTINES = ("aruco.id_confirm", "aruco.caliper_size", "aruco.bundle_adjustment", "camera.exposure_for_aruco")


def _fa():
    """WHY imported per test and never importorskip: a missing module must FAIL here, not skip."""
    from sim2real.fit import aruco  # noqa: PLC0415

    return aruco


def _tuner():
    from sim2real.schedule import aruco_exposure  # noqa: PLC0415

    return aruco_exposure


def _cv2():
    return pytest.importorskip("cv2")  # the vision extra (pyproject); the venv has it


# --- the catalog: type, models, parameters, routines ------------------------------------------------------------------------------------


def test_the_type_exists_with_its_model_rungs():
    from sim2real.cards import domain as dm  # noqa: PLC0415

    t = dm.entity_type(TYPE)
    assert TYPE in dm.TYPE_ORDER
    ids = [m.id for m in t.models]
    assert ids[: len(MODELS)] == list(MODELS), ids
    nominal, as_built, scaled = (dm.model(TYPE, m) for m in MODELS)
    assert {"dictionary", "marker_ids", "marker_length_m", "layout_m", "pose_on_link"} <= set(nominal.parameters)
    assert set(as_built.adds) == {"as_built_offset"} and set(scaled.adds) == {"print_scale"}
    assert scaled.current, "today's model: the five-bar strips are fitted with a print scale (bam_rack_twin.fivebar_asbuilt)"
    assert any("flatness_m" in m.adds for m in t.models), "flatness is a parameter of some rung, even with no routine yet"
    assert {p.unit for p in t.parameters if p.name == "marker_length_m"} == {"m"}, "SI in code; mm only at the display edge"


def test_the_routines_are_registered_with_what_they_identify_and_need():
    from sim2real.cards import calibration as cat  # noqa: PLC0415
    from sim2real.cards import domain as dm  # noqa: PLC0415

    by_id = {r.id: r for r in cat.ROUTINES}
    for rid in ROUTINES:
        r = by_id[rid]
        assert r.status == "implemented" and r.code, rid
        assert r.wall_time.value is not None and r.operator_time.value is not None, rid
    ident = by_id["aruco.id_confirm"]
    assert ident.kind == "identify" and {"dictionary", "marker_ids"} <= {p for _t, _m, p in dm.routine_parameters(ident.id)}
    caliper = by_id["aruco.caliper_size"]
    assert "caliper" in caliper.equipment and caliper.operator_time.value > 0, "an operator with a caliper"
    assert {p for _t, _m, p in dm.routine_parameters(caliper.id)} == {"print_scale"}
    bundle = by_id["aruco.bundle_adjustment"]
    assert {"as_built_offset", "print_scale"} <= {p for _t, _m, p in dm.routine_parameters(bundle.id)}
    assert "marker_ids" in bundle.requires and "print_scale" in bundle.uses
    tune = by_id["camera.exposure_for_aruco"]
    assert tune.kind == "tune"
    written = {(c.card, s) for c in tune.configures for s in c.settings}
    assert {("camera_rgb", "exposure"), ("camera_rgb", "gain"), ("camera_rgb", "fps")} <= written
    assert "marker_ids" in tune.requires and "exposure" in bundle.requires
    assert {"aruco.caliper_size", "aruco.bundle_adjustment"} <= set(dm.routines_identifying(TYPE, "print_scale"))
    assert cat.EQUIPMENT["caliper"].cost.value, "a digital caliper, priced (an estimate is fine, marked ESTIMATE)"


def test_the_domain_export_is_current_and_carries_the_type():
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    doc = json.loads((REPO / "src" / "sim2real" / "cards" / "domain_v3.json").read_text())
    assert TYPE in {t["id"] for t in doc["entity_types"]}
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'src'}:{REPO}"}
    env.pop("VIRTUAL_ENV", None)
    check = subprocess.run([sys.executable, "-m", "type_cards.domain", "--check"], cwd=REPO, env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr


def test_the_kit_maps_every_routine_to_its_code():
    from sim2real.models import aruco_marker as am  # noqa: PLC0415

    kit = am.kit()
    assert kit.type_id == TYPE
    assert [r.key for r in kit.rungs][:3] == ["M0", "M1", "M2"]
    assert set(kit.identify) == {"aruco.id_confirm", "aruco.caliper_size", "aruco.bundle_adjustment"}
    assert all(callable(f) for f in kit.identify.values())
    from sim2real.models import camera  # noqa: PLC0415

    assert "camera.exposure_for_aruco" in {**camera.kit("camera_rgb").configure, **getattr(camera.kit("camera_rgb"), "tune", {})}


def test_every_graded_routine_is_read_by_the_one_recovery_reader():
    from sim2real.calibration import recovery as rec  # noqa: PLC0415

    rec.ladders.cache_clear()
    for rid in ROUTINES:
        assert rec.source(rid) == f"sysid/results/routine_ladders/{rid}.json", rid
        assert rec.recovery(rid, "1x")["pass"] is True, rid


# --- shared: ladder files ---------------------------------------------------------------------------------------------------------------


def _ladder(routine: str, levels: dict[str, dict], tolerance: dict) -> None:
    """Write (SIM2REAL_WRITE_LADDERS=1) or compare the committed ladder file with this run's levels."""
    path = LADDERS / f"{routine}.json"
    doc = {"schema": "sim2real.routine_ladder/1", "routine": routine, "generated_by": "tests/test_aruco_marker.py",
           "tolerance": tolerance, "levels": levels}
    if WRITE:
        path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    committed = json.loads(path.read_text())
    assert committed["schema"] == doc["schema"] and committed["routine"] == routine and committed["tolerance"] == tolerance
    for level, entry in levels.items():
        got = committed["levels"][level]
        assert got["pass"] == entry["pass"], (routine, level, got, entry)
        assert got["worst_error_over_tolerance"] == pytest.approx(entry["worst_error_over_tolerance"], rel=1e-3, abs=1e-6), (routine, level)


# --- caliper: the printed size against its spec -----------------------------------------------------------------------------------------

CALIPER_TRUE_SCALE = 0.98493     # the five-bar's L2 strip as fitted (bam_fivebar strips_asbuilt.json: 243.3 mm of a 247.0 mm spec)
CALIPER_BAR_M = 0.100            # aruco-studio sheets print a 100 mm ruler bar (aruco_studio/verify/sheet_check.py)
CALIPER_SIGMA_M = 3e-5           # 1x: an operator reading a 0.01 mm digital caliper, 0.03 mm between readings (estimate)
CALIPER_TOL = 5e-4               # recovered scale within 0.05 %


def _caliper_readings(level: str, n: int = 5) -> list[float]:
    rng = np.random.default_rng(1111)
    raw = CALIPER_BAR_M * CALIPER_TRUE_SCALE + rng.normal(0.0, CALIPER_SIGMA_M * SCALE[level], n)
    return [round(float(v), 5) for v in raw]   # the caliper shows 0.01 mm


def test_caliper_recovers_the_print_scale_and_flags_it_out_of_tolerance():
    fa = _fa()
    check = fa.caliper_scale(_caliper_readings("1x"), CALIPER_BAR_M, resolution_m=1e-5, tolerance=0.005)
    assert abs(check.scale - CALIPER_TRUE_SCALE) <= CALIPER_TOL
    assert check.ci95[0] <= CALIPER_TRUE_SCALE <= check.ci95[1] and check.n == 5
    assert check.within_tolerance is False, "1.5 % small is outside a 0.5 % print tolerance: the sticker is reprinted or its scale used"
    good = fa.caliper_scale([0.10001, 0.09999, 0.10000], CALIPER_BAR_M, resolution_m=1e-5, tolerance=0.005)
    assert good.within_tolerance is True and good.ci95[0] < good.ci95[1], "a resolution floor keeps the interval open"


def test_ladder_caliper_size():
    fa = _fa()
    levels = {}
    for level in LEVELS:
        check = fa.caliper_scale(_caliper_readings(level), CALIPER_BAR_M, resolution_m=1e-5, tolerance=0.005)
        ratio = abs(check.scale - CALIPER_TRUE_SCALE) / CALIPER_TOL
        levels[level] = {"pass": bool(ratio <= 1.0), "worst_error_over_tolerance": float(ratio),
                         "recovered": {"print_scale": float(check.scale)}, "true": {"print_scale": CALIPER_TRUE_SCALE}}
    assert levels["0x"]["pass"] and levels["1x"]["pass"]
    _ladder("aruco.caliper_size", levels, {"print_scale": {"kind": "abs", "value": CALIPER_TOL}})


# --- ID confirmation: every expected id, no duplicate, no stranger, the right dictionary ---------------------------------------------------


def _tag_image(dictionary: str, ids: list[int], level: str = "1x", seed: int = 0) -> np.ndarray:
    cv2 = _cv2()
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
    img = np.full((480, 640), 235, np.uint8)
    for k, marker in enumerate(ids):
        tile = cv2.aruco.generateImageMarker(d, int(marker), 80, borderBits=1)
        r, c = divmod(k, 5)
        y, x = 40 + r * 130, 30 + c * 120
        img[y:y + 80, x:x + 80] = np.where(tile > 127, 235, 20)
    noise = np.random.default_rng(seed).normal(0.0, 4.0 * SCALE[level], img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def test_id_confirmation_flags_missing_duplicate_and_strangers():
    fa = _fa()
    check = fa.confirm_ids([_tag_image("DICT_4X4_50", [0, 1, 2, 3, 3, 9])], "DICT_4X4_50", [0, 1, 2, 3, 4, 5])
    assert tuple(check.missing) == (4, 5) and tuple(check.duplicate) == (3,) and tuple(check.unexpected) == (9,)
    assert check.passed is False and check.wrong_dictionary is None
    ok = fa.confirm_ids([_tag_image("DICT_4X4_50", [0, 1, 2, 3, 4, 5])], "DICT_4X4_50", [0, 1, 2, 3, 4, 5])
    assert ok.passed is True and tuple(ok.found) == (0, 1, 2, 3, 4, 5)


def test_id_confirmation_names_the_dictionary_actually_printed():
    fa = _fa()
    check = fa.confirm_ids([_tag_image("DICT_5X5_50", [0, 1, 2, 3, 4, 5])], "DICT_4X4_50", [0, 1, 2, 3, 4, 5])
    assert check.passed is False and check.wrong_dictionary == "DICT_5X5_50"


def test_ladder_id_confirm():
    fa = _fa()
    levels = {}
    for level in LEVELS:
        images = [_tag_image("DICT_4X4_50", [0, 1, 2, 3, 3, 9], level, seed=s) for s in range(3)]
        check = fa.confirm_ids(images, "DICT_4X4_50", [0, 1, 2, 3, 4, 5])
        wrong = int(tuple(check.missing) != (4, 5)) + int(tuple(check.duplicate) != (3,)) + int(tuple(check.unexpected) != (9,))
        levels[level] = {"pass": wrong == 0, "worst_error_over_tolerance": float(wrong), "flags_wrong": wrong}
    assert levels["0x"]["pass"] and levels["1x"]["pass"]
    _ladder("aruco.id_confirm", levels, {"flags": {"kind": "abs", "value": 0}})


# --- bundle adjustment: camera + as-built sticker poses + print scale + joint offset, CAD as prior --------------------------------------
#
# One fixed camera over a base with two stickers (plate_a, the gauge, held at CAD; plate_b free) and a strip on a link turning about the
# base z axis through 30 views over +-50 deg. Hidden: the camera's pose, plate_b's and the strip's as-built 6-DOF and print scale, the
# joint's zero. WHY graded on corner positions in the base frame and not on each sticker parameter: from one fixed camera a sticker on the
# moving link and the joint's zero trade exactly (a joint offset and a sticker turned about the joint axis project the same), and a
# static sticker's depth trades with its print scale; the corners are what a twin uses, and they are fixed whatever the gauge.
# Linearised at 1x (0.5 px corners, the caliper's prior) the corners' 1-sigma is <= 0.7 mm, so 2 mm (Zach's manual-diagnosis line,
# feedback-aruco-bundle-adjustment-every-rig) passes at 1x and is expected to fail at 3x.

SIDE = 0.030
K = np.array([[615.0, 0.0, 320.0], [0.0, 615.0, 240.0], [0.0, 0.0, 1.0]])
DIST = np.zeros(5)
PIVOT = np.array([0.0, 0.0, 0.03])
QS = np.deg2rad(np.linspace(-50.0, 50.0, 30))
PX_SIGMA_1X = 0.5                    # 1x corner noise (estimate; the five-bar's fitted corners leave 1.12 px rms with model error in it)
TRUE_OFFSET = math.radians(1.5)
TOL_CORNER_M, TOL_CAMERA_M, TOL_CAMERA_RAD, TOL_SCALE = 0.002, 0.0015, math.radians(0.2), 0.002


def _rot(rv) -> np.ndarray:
    rv = np.asarray(rv, float)
    th = float(np.linalg.norm(rv))
    if th < 1e-15:
        return np.eye(3)
    k = rv / th
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * kx + (1 - math.cos(th)) * kx @ kx


def _T(R=None, t=(0.0, 0.0, 0.0)) -> np.ndarray:
    M = np.eye(4)
    M[:3, :3] = np.eye(3) if R is None else R
    M[:3, 3] = t
    return M


def _look_at(eye, target, up=(0.0, 0.0, 1.0)) -> np.ndarray:
    z = np.subtract(target, eye) / np.linalg.norm(np.subtract(target, eye))
    x = np.cross(z, up)
    x /= np.linalg.norm(x)
    return _T(np.column_stack([x, np.cross(z, x), z]), eye)


def _sheet(n: int, pitch: float, rows: int = 1) -> np.ndarray:
    out = []
    for r in range(rows):
        for i in range(n):
            x0, y0 = (i - (n - 1) / 2) * pitch - SIDE / 2, (r - (rows - 1) / 2) * pitch - SIDE / 2
            out.append([[x0, y0, 0.0], [x0 + SIDE, y0, 0.0], [x0 + SIDE, y0 + SIDE, 0.0], [x0, y0 + SIDE, 0.0]])
    return np.array(out)


CAMERA_NOMINAL = _look_at((0.10, -0.45, 0.42), (0.08, 0.02, 0.04))
CAMERA_TRUE = CAMERA_NOMINAL @ _T(_rot(np.deg2rad([0.4, -0.3, 0.5])), (0.002, -0.0015, 0.001))
SHEETS = {  # group: (link, CAD pose on link, layout in the sheet frame (N, 4, 3), first id)
    "plate_a": ("base", _T(_rot([0.6, 0.0, 0.0]), (-0.06, 0.08, 0.0)), _sheet(4, 0.05, 2), 0),
    "plate_b": ("base", _T(_rot([0.5, 0.0, 0.5]), (0.17, 0.10, 0.0)), _sheet(3, 0.045, 2), 10),
    "strip": ("arm", _T(_rot([0.7, 0.0, 0.0]), (0.12, 0.0, 0.02)), _sheet(5, 0.040), 20),
}
HIDDEN = {  # the as-built truth: a 6-DOF correction in the sheet frame and the print scale
    "plate_a": (_T(), 1.0),
    "plate_b": (_T(_rot(np.deg2rad([0.8, -0.6, 1.2])), (0.0015, -0.0010, 0.0020)), 1.004),
    "strip": (_T(_rot(np.deg2rad([-0.7, 0.9, 0.5])), (-0.0012, 0.0008, 0.0015)), CALIPER_TRUE_SCALE),
}


def link_pose(link: str, joints) -> np.ndarray:
    """The twin's forward kinematics, handed to the bundle adjustment: base is the identity, arm turns about base z through PIVOT."""
    if link == "base":
        return np.eye(4)
    return _T(_rot([0.0, 0.0, float(joints["j1"])]), PIVOT)


def _true_corners(group: str, q: float) -> np.ndarray:
    link, pose, layout, _ = SHEETS[group]
    delta, scale = HIDDEN[group]
    pts = layout.reshape(-1, 3) * scale
    return (link_pose(link, {"j1": q + TRUE_OFFSET}) @ pose @ delta @ np.c_[pts, np.ones(len(pts))].T).T[:, :3].reshape(-1, 4, 3)


def _project(camera_in_base: np.ndarray, points: np.ndarray) -> np.ndarray:
    pc = (np.linalg.inv(camera_in_base) @ np.c_[points, np.ones(len(points))].T).T[:, :3]
    uv = (K @ pc.T).T
    return uv[:, :2] / uv[:, 2:3]


def _views(level: str):
    fa = _fa()
    rng = np.random.default_rng(20261111)
    views = []
    for q in QS:
        corners = {}
        for group, (_link, _pose, _layout, first) in SHEETS.items():
            uv = _project(CAMERA_TRUE, _true_corners(group, q).reshape(-1, 3)).reshape(-1, 4, 2)
            uv = uv + rng.normal(0.0, PX_SIGMA_1X * SCALE[level], uv.shape)
            for k, c in enumerate(uv):
                corners[first + k] = c
        views.append(fa.View(joints={"j1": float(q)}, corners_px=corners))   # the encoder reads q; the zero is hidden
    return views


def _sheets():
    fa = _fa()
    return [fa.MarkerSheet(group=g, link=link, dictionary="DICT_4X4_50", ids=tuple(range(first, first + len(layout))),
                           corners_m=layout.copy(), pose_on_link=pose.copy()) for g, (link, pose, layout, first) in SHEETS.items()]


def _bundle(level: str, *, caliper: bool = True):
    fa = _fa()
    priors = {}
    if caliper:   # the caliper routine's results, read off the same truth with its own small error
        priors = {"plate_b": (HIDDEN["plate_b"][1] + 1e-4 * SCALE[level], 3e-4), "strip": (CALIPER_TRUE_SCALE - 1e-4 * SCALE[level], 3e-4)}
    return fa.bundle_adjust(_views(level), _sheets(), K=K, dist=DIST, camera_in_base=CAMERA_NOMINAL.copy(), link_pose=link_pose,
                            anchor="plate_a", joint_offsets={"j1": 0.0}, fit_joints=("j1",), scale_priors=priors,
                            pose_prior=(0.002, math.radians(1.0)), joint_prior_rad=math.radians(2.0), robust_px=1.0)


def _grade(bundle) -> dict:
    errors = {}
    worst_corner = 0.0
    for group in ("plate_b", "strip"):
        link, _pose, layout, _ = SHEETS[group]
        for q in QS:
            est = (link_pose(link, {"j1": q + bundle.joint_offsets["j1"]}) @ bundle.sheet_poses[group]
                   @ np.c_[layout.reshape(-1, 3) * bundle.scales[group], np.ones(layout.size // 3)].T).T[:, :3]
            worst_corner = max(worst_corner, float(np.max(np.linalg.norm(est - _true_corners(group, q).reshape(-1, 3), axis=1))))
    cam_err = np.linalg.inv(CAMERA_TRUE) @ bundle.camera_in_base
    cam_t = float(np.linalg.norm(cam_err[:3, 3]))
    cam_r = float(math.acos(max(-1.0, min(1.0, (np.trace(cam_err[:3, :3]) - 1) / 2))))
    scale = max(abs(bundle.scales[g] - HIDDEN[g][1]) for g in ("plate_b", "strip"))
    errors = {"corner_m": worst_corner, "camera_m": cam_t, "camera_rad": cam_r, "print_scale": scale}
    ratios = {"corner_m": worst_corner / TOL_CORNER_M, "camera_m": cam_t / TOL_CAMERA_M, "camera_rad": cam_r / TOL_CAMERA_RAD,
              "print_scale": scale / TOL_SCALE}
    return {"errors": errors, "ratios": ratios, "worst": max(ratios.values())}


def test_bundle_adjustment_recovers_the_as_built_cell_at_the_measured_noise():
    graded = _grade(_bundle("1x"))
    assert graded["worst"] <= 1.0, graded
    exact = _grade(_bundle("0x"))
    assert exact["worst"] <= 0.25, exact


def test_bundle_adjustment_keeps_the_gauge_sticker_at_cad_and_reports_residuals():
    fa = _fa()
    b = _bundle("1x")
    assert np.allclose(b.sheet_poses["plate_a"], SHEETS["plate_a"][1], atol=1e-12) and b.scales["plate_a"] == 1.0
    assert 0.2 * PX_SIGMA_1X < b.residual_px < 2.0 * PX_SIGMA_1X, b.residual_px
    assert isinstance(b, fa.Bundle)


def test_bundle_adjustment_says_what_it_could_not_see_without_the_caliper():
    """From one fixed camera, a static sticker's depth and its print scale trade: without the caliper's prior plate_b's scale is
    prior-held; the strip turns through 100 deg, so its scale is measured by the views alone."""
    b = _bundle("1x", caliper=False)
    assert b.observability["plate_b.print_scale"] in ("prior-held", "unobservable")
    assert b.observability["strip.print_scale"] == "measured"
    assert abs(b.scales["strip"] - CALIPER_TRUE_SCALE) <= 1.5 * TOL_SCALE


def test_ladder_bundle_adjustment():
    levels = {}
    for level in LEVELS:
        graded = _grade(_bundle(level))
        levels[level] = {"pass": bool(graded["worst"] <= 1.0), "worst_error_over_tolerance": float(graded["worst"]),
                         "errors": graded["errors"]}
    assert levels["0x"]["pass"] and levels["1x"]["pass"]
    _ladder("aruco.bundle_adjustment", levels, {"corner_m": {"kind": "abs", "value": TOL_CORNER_M},
                                                "camera_m": {"kind": "abs", "value": TOL_CAMERA_M},
                                                "camera_rad": {"kind": "abs", "value": TOL_CAMERA_RAD},
                                                "print_scale": {"kind": "abs", "value": TOL_SCALE}})


# --- the camera tuned for ArUco accuracy: exposure, gain and FPS ---------------------------------------------------------------------------
#
# A 2 x 2 board of 30 mm DICT_4X4_50 markers 0.40 m from a 320 x 240 camera. The renderer is the hidden truth: photons (scene light x
# exposure), Poisson shot noise, read noise x gain, 8-bit clipping, and motion blur (the board's image speed x exposure) along a constant
# speed back-and-forth path. The tuner sees frames only. The oracle scores every candidate by the TRUE mean corner error (a missed
# marker counts 5 px) on fresh frames. Measured on the designer's prototype (2026-11-12): in both static scenes, a board-PnP residual
# picks within 1.1 x of the oracle, while the house rule (shortest exposure within 90 % of the most markers read, bam_camera_calibration
# task.aruco_score) is 1.6-1.7 x worse; in the dark scene only exposures past 1/15 s are good, so the right FPS is 6 (the rack's own
# 2026-11-10 finding: bam_rack_twin.hardware.fivebar_run.D435_STILL_LOOK). A residual alone is blind to blur on a moving board; the
# moving scenes are what a blur-aware objective has to get right.

W, H = 320, 240
KC = np.array([[307.5, 0.0, 160.0], [0.0, 307.5, 120.0], [0.0, 0.0, 1.0]])
BOARD_SIDE, BOARD_GAP = 0.030, 0.010
MISS_PX = 5.0
READ_NOISE_E = 3.0
DN_PER_E = 0.25
SCENES = {
    "static_dim": {"speed_px_s": 0.0, "electrons_per_s": 2.0e4},
    "static_dark": {"speed_px_s": 0.0, "electrons_per_s": 4.0e3},
    "moving_bright": {"speed_px_s": 400.0, "electrons_per_s": 2.0e5},
    "moving_dim": {"speed_px_s": 60.0, "electrons_per_s": 1.0e5},
}
CANDIDATES = tuple((e, g, f) for f in (6.0, 15.0, 30.0) for e in (0.002, 0.004, 0.008, 0.016, 0.033, 0.066, 0.133)
                   for g in (1.0, 4.0, 16.0) if e <= 1.0 / f + 1e-9)


def _board_layout() -> dict[int, np.ndarray]:
    out = {}
    for k, (i, j) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
        x0 = i * (BOARD_SIDE + BOARD_GAP) - (BOARD_SIDE + BOARD_GAP / 2)
        y0 = j * (BOARD_SIDE + BOARD_GAP) - (BOARD_SIDE + BOARD_GAP / 2)
        out[k] = np.array([[x0, y0, 0.0], [x0 + BOARD_SIDE, y0, 0.0], [x0 + BOARD_SIDE, y0 + BOARD_SIDE, 0.0], [x0, y0 + BOARD_SIDE, 0.0]])
    return out


LAYOUT = _board_layout()


def _board_uv() -> dict[int, np.ndarray]:
    R, t = _rot([0.35, -0.25, 0.0]), np.array([0.0, 0.0, 0.40])
    out = {}
    for k, c in LAYOUT.items():
        uv = (KC @ ((R @ c.T).T + t).T).T
        out[k] = uv[:, :2] / uv[:, 2:3]
    return out


_REFLECTANCE: list[np.ndarray] = []


def _reflectance() -> np.ndarray:
    """The board's reflectance at rest (grey wall 0.55, white 0.9, black 0.05), rendered once."""
    if _REFLECTANCE:
        return _REFLECTANCE[0]
    cv2 = _cv2()
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    img = np.full((H, W), 0.55, np.float32)
    n = 120
    src = np.array([[-0.5, -0.5], [n - 0.5, -0.5], [n - 0.5, n - 0.5], [-0.5, n - 0.5]], np.float32)
    ones = np.ones((n, n), np.float32)
    for k, uv in _board_uv().items():
        quad = uv.astype(np.float32)
        white = ((quad - quad.mean(0)) * (1 + 2 / 6) + quad.mean(0)).astype(np.float32)
        mask = cv2.warpPerspective(ones, cv2.getPerspectiveTransform(src, white), (W, H))
        img = img * (1 - mask) + 0.9 * mask
        M = cv2.getPerspectiveTransform(src, quad)
        tex = np.where(cv2.aruco.generateImageMarker(d, k, n, borderBits=1) > 127, 0.9, 0.05).astype(np.float32)
        mk = cv2.warpPerspective(ones, M, (W, H))
        img = img * (1 - mk) + cv2.warpPerspective(tex, M, (W, H), flags=cv2.INTER_AREA)
    _REFLECTANCE.append(img)
    return img


def _position_px(t: float, speed: float) -> float:
    """Back and forth over +-30 px at a constant image speed (a triangle wave)."""
    if speed == 0.0:
        return 0.0
    period = 4 * 30.0 / speed
    phase = (t % period) / period
    return 30.0 * (4 * phase - 1 if phase < 0.5 else 3 - 4 * phase)


class _Camera:
    """The hidden-truth camera: what a tuner may call (capture), and the truth the oracle reads (the corners at mid-exposure)."""

    def __init__(self, scene: dict, level: str = "1x", seed: int = 0):
        self.scene, self.level, self.seed, self.calls = scene, level, seed, 0

    def frames(self, exposure_s: float, gain: float, fps: float, n: int, *, salt: str = ""):
        cv2 = _cv2()
        if exposure_s > 1.0 / fps + 1e-9:
            raise ValueError(f"exposure {exposure_s} s does not fit a frame at {fps} fps")
        rng = np.random.default_rng(zlib.crc32(f"{self.seed}{salt}{exposure_s}{gain}{fps}".encode()))
        speed = self.scene["speed_px_s"]
        base = _reflectance()
        t0 = rng.uniform(0.0, 10.0)
        frames, truths = [], []
        for k in range(n):
            t = t0 + k / fps
            x0, x1 = _position_px(t, speed), _position_px(t + exposure_s, speed)
            steps = max(1, min(48, int(math.ceil(abs(x1 - x0) / 0.5))))   # WHY capped: a 50 px smear is a bad candidate either way
            acc = np.zeros((H, W), np.float32)
            for s in range(steps):
                ts = t + (s + 0.5) / steps * exposure_s
                acc += cv2.warpAffine(base, np.float32([[1, 0, _position_px(ts, speed)], [0, 1, 0]]), (W, H),
                                      flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            acc /= steps
            electrons = rng.poisson(np.maximum(acc * self.scene["electrons_per_s"] * exposure_s, 0.0)).astype(np.float32)
            electrons += rng.normal(0.0, READ_NOISE_E * max(SCALE[self.level], 0.0), electrons.shape) if SCALE[self.level] else 0.0
            frames.append(np.clip(np.round(electrons * gain * DN_PER_E), 0, 255).astype(np.uint8))
            mid = _position_px(t + exposure_s / 2, speed)
            truths.append({k2: uv + np.array([mid, 0.0]) for k2, uv in _board_uv().items()})
        return frames, truths

    def capture(self, exposure_s: float, gain: float, fps: float, n: int):
        self.calls += 1
        return self.frames(exposure_s, gain, fps, n, salt="tuner")[0]


_ORACLE: dict = {}
_TUNED: dict = {}


def _oracle(scene: str, level: str) -> dict:
    """Every candidate's true mean corner error in a scene (cached: the oracle is the test's, deterministic)."""
    if (scene, level) not in _ORACLE:
        camera = _Camera(SCENES[scene], level, seed=7)
        _ORACLE[scene, level] = {s: _true_error(camera, s) for s in CANDIDATES}
    return _ORACLE[scene, level]


def _true_error(camera: _Camera, setting, n: int = 8) -> float:
    cv2 = _cv2()
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), params)
    frames, truths = camera.frames(*setting, n, salt="oracle")
    errs = []
    for img, truth in zip(frames, truths):
        corners, ids, _ = det.detectMarkers(img)
        got = {} if ids is None else {int(i): c.reshape(4, 2) for i, c in zip(ids.ravel(), corners)}
        errs += [MISS_PX if k not in got else float(np.mean(np.linalg.norm(got[k] - truth[k], axis=1))) for k in LAYOUT]
    return float(np.mean(errs))


def _count_pick(camera: _Camera):
    """The house rule today (bam_camera_calibration task stage with aruco_score): shortest exposure within 90 % of the most markers read,
    then the least gain. The baseline the accuracy objective must beat."""
    cv2 = _cv2()
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    rows = []
    for setting in CANDIDATES:
        found = [0 if ids is None else len(ids) for _c, ids, _r in (det.detectMarkers(f) for f in camera.capture(*setting, 5))]
        rows.append((float(np.mean(found)), setting))
    best = max(r[0] for r in rows)
    return min((s for score, s in rows if score >= 0.9 * best), key=lambda s: (s[0], s[1]))


def _board():
    tuner = _tuner()
    return tuner.Board(dictionary="DICT_4X4_50", corners_m={k: v.copy() for k, v in LAYOUT.items()})


def _tune(scene: str, level: str = "1x"):
    if (scene, level) not in _TUNED:
        camera = _Camera(SCENES[scene], level, seed=7)
        _TUNED[scene, level] = (camera, _tuner().tune(camera.capture, _board(), KC, np.zeros(5), CANDIDATES, frames=5))
    return _TUNED[scene, level]


@pytest.mark.parametrize("scene", sorted(SCENES))
def test_the_tuner_picks_an_exposure_whose_true_corner_error_is_near_the_best(scene):
    _camera, result = _tune(scene)
    assert (result.exposure_s, result.gain, result.fps) in CANDIDATES and result.exposure_s <= 1.0 / result.fps + 1e-9
    oracle = _oracle(scene, "1x")
    best = min(oracle.values())
    picked = oracle[(result.exposure_s, result.gain, result.fps)]
    slack = (1.15, 0.02) if scene.startswith("static") else (1.30, 0.05)
    assert picked <= slack[0] * best + slack[1], (scene, picked, best, sorted(oracle.items(), key=lambda kv: kv[1])[:4])
    assert len(result.rows) == len(CANDIDATES) and all({"exposure_s", "gain", "fps", "score_px", "detection_rate"} <= set(r) for r in result.rows)


@pytest.mark.parametrize("scene", ["static_dim", "static_dark"])
def test_accuracy_beats_markers_read_where_the_light_is_low(scene):
    camera, result = _tune(scene)
    oracle = _oracle(scene, "1x")
    mine, house = oracle[(result.exposure_s, result.gain, result.fps)], oracle[_count_pick(camera)]
    assert mine <= 0.8 * house, (scene, mine, house)


def test_in_the_dark_the_frame_rate_gives_way_to_the_exposure():
    _camera, result = _tune("static_dark")
    assert result.exposure_s >= 0.066 and result.fps <= 15.0, (result.exposure_s, result.fps)
    _camera, fast = _tune("moving_bright")
    assert fast.exposure_s <= 0.004, fast.exposure_s


def test_ladder_camera_exposure_for_aruco():
    levels = {}
    for level in ("0x", "1x", "3x"):
        worst = 0.0
        for scene in sorted(SCENES):
            _camera, result = _tune(scene, level)
            oracle = _oracle(scene, level)
            best = min(oracle.values())
            slack = (1.15, 0.02) if scene.startswith("static") else (1.30, 0.05)
            allowance = (slack[0] - 1.0) * best + slack[1]
            worst = max(worst, (oracle[(result.exposure_s, result.gain, result.fps)] - best) / allowance)
        levels[level] = {"pass": bool(worst <= 1.0), "worst_error_over_tolerance": float(worst)}
    assert levels["1x"]["pass"]
    _ladder("camera.exposure_for_aruco", levels, {"true_corner_error": {"kind": "rel_to_oracle", "value": "1.15x+0.02 px static, 1.30x+0.05 px moving"}})
