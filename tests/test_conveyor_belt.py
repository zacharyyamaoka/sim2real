"""The conveyor belt type: its parameters, its card, and a hidden-truth sim proof of every calibration routine.

    env -u VIRTUAL_ENV MUJOCO_GL=egl uv run --project /home/bam/sim2real --extra sim --extra vision --extra test pytest -q tests/test_conveyor_belt.py

Zach, 2026-11-11 (Daily Note, "# Conveyor belt calibration"): a new robot type, Conveyor Belt, with its model (the parameters) and the
routines that get them, proven in sim first so the real runs start the moment the belt is plugged in. Written before the code (red first).

The oracle is outside the code under test: the MuJoCo twin holds a HIDDEN truth (scale, direction, plane, camera, arm and line-scanner
poses, latency, runout, slip) set apart from the description's nominal values, and the routines only see what a real rig would give them
(rendered images, encoder revs, probe force, touched points). Each recovered quantity must land inside the card's tolerance, and the
nominal description (no calibration) must FAIL the same gate, so a gate that passes everything cannot pass.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from robot_msgs.space import meta

from sim2real.cards import conveyor_belt as card
from sim2real.fit import belt_geometry as geo
from sim2real.metrics.gate import gate

# ----------------------------------------------------------------------------------------------------------------------------------
# The card: data only


def test_every_parameter_is_a_value_with_nominal_range_and_source():
    from sim2real.models.conveyor_belt import NOMINAL

    params = NOMINAL.parameters()
    assert len(params) >= 15
    for name, value in params.items():
        found = meta(value)
        assert found, name
        assert found["unit"], name
        assert found["source"], name
        assert found["low"] is not None and found["high"] is not None, name
        assert found["low"] <= float(value) <= found["high"], name


def test_every_routine_states_its_tolerances_and_what_limits_it():
    ids = [r.id for r in card.ROUTINES]
    assert len(ids) == len(set(ids)) >= 9
    for routine in card.ROUTINES:
        assert routine.limited_by in card.LIMITS, routine.id
        assert routine.quantities, routine.id
        for quantity in routine.quantities:
            assert quantity in card.TOLERANCES, (routine.id, quantity)
    # Zach's < 1 mm target: only the arm probe claims it for the belt plane
    sub_mm = [r.id for r in card.ROUTINES if r.sub_mm]
    assert "conveyor_belt.plane_probe" in sub_mm
    assert "conveyor_belt.plane_depth" not in sub_mm


def test_card_metrics_and_gates_point_at_tolerances():
    for metric in card.METRICS:
        assert metric.unit in ("mm", "deg", "ms", "%", "mm/rev", "x floor"), metric.id
    for gate_id, target in card.GATES.items():
        assert meta(target)["source"], gate_id


# ----------------------------------------------------------------------------------------------------------------------------------
# The fit verbs on synthetic data (fast; no simulator)


def test_plane_fit_recovers_a_tilted_plane():
    rng = np.random.default_rng(0)
    normal = np.array([math.sin(0.01), -math.sin(0.02), 1.0])
    normal /= np.linalg.norm(normal)
    xy = rng.uniform(-0.2, 0.2, size=(200, 2))
    z = -0.3 - (normal[0] * xy[:, 0] + normal[1] * xy[:, 1]) / normal[2]
    points = np.column_stack([xy, z + rng.normal(0, 1e-4, size=len(z))])
    plane = geo.fit_plane(points)
    assert math.degrees(math.acos(abs(float(plane.normal @ normal)))) < 0.02
    assert abs(plane.height_at(0.0, 0.0) + 0.3) < 5e-5


def test_kabsch_recovers_a_rigid_transform():
    rng = np.random.default_rng(1)
    a = rng.uniform(-1, 1, size=(10, 3))
    rot = geo.rotation_zyx(0.3, -0.1, 0.05)
    b = a @ rot.T + np.array([0.1, -0.2, 0.3])
    t = geo.kabsch(a, b)
    assert np.allclose(t[:3, :3], rot, atol=1e-9) and np.allclose(t[:3, 3], [0.1, -0.2, 0.3], atol=1e-9)


def test_line_scale_fit_separates_scale_direction_and_runout():
    rng = np.random.default_rng(2)
    direction = np.array([0.99, 0.1, -0.02])
    direction /= np.linalg.norm(direction)
    revs = np.concatenate([np.linspace(0, 20, 60), np.linspace(20, 0, 60)])
    drum = 2 * math.pi * revs / 10.0
    travel = 32.1e-3 * revs + 0.15e-3 * (np.sin(drum + 0.7) - math.sin(0.7))
    points = np.array([0.1, 0.0, 0.6]) + np.outer(travel, direction) + rng.normal(0, 3e-5, size=(len(revs), 3))
    fit = geo.fit_belt_line(revs, points, revs_per_drum_turn=10.0)
    assert abs(fit.m_per_rev - 32.1e-3) / 32.1e-3 < 1e-4
    assert math.degrees(math.acos(float(fit.direction @ direction))) < 0.01
    assert abs(fit.runout_m - 0.15e-3) < 2e-5


def test_time_offset_fit_recovers_latency():
    rng = np.random.default_rng(3)
    t_log = np.arange(0, 8, 1e-3)
    speed = np.where(t_log < 2, 3.0, np.where(t_log < 4, -3.0, np.where(t_log < 6, 6.0, -6.0)))
    revs = np.cumsum(speed) * 1e-3
    t_capture = np.arange(0.05, 7.95, 1 / 30)
    position = 0.0314 * np.interp(t_capture, t_log, revs) + rng.normal(0, 5e-5, size=len(t_capture))
    stamps = t_capture + 0.023
    latency = geo.fit_time_offset(stamps, position, t_log, revs, search_s=(-0.1, 0.1))
    assert abs(latency - 0.023) < 1e-3


# ----------------------------------------------------------------------------------------------------------------------------------
# The hidden-truth proof: every routine on the MuJoCo twin


@pytest.fixture(scope="module")
def calibrated():
    pytest.importorskip("mujoco")
    pytest.importorskip("cv2")
    from sim2real.models.conveyor_belt import NOMINAL, ConveyorBelt
    from sim2real.sim.conveyor_belt import BeltTruth, BeltTwin

    twin = BeltTwin(NOMINAL, BeltTruth.default(), seed=0)
    try:
        belt = ConveyorBelt(NOMINAL, twin)
        result = belt.calibrate()
        held_out = belt.eval_twin(result)
        yield twin, belt, result, twin.score(result), twin.score(belt.nominal_calibration()), held_out
    finally:
        twin.close()


def _quantities():
    return [(r.id, q) for r in card.ROUTINES for q in r.quantities]


@pytest.mark.parametrize("routine,quantity", _quantities())
def test_routine_recovers_the_hidden_truth(calibrated, routine, quantity):
    _, _, _, scores, _, _ = calibrated
    error = scores[quantity].error
    verdict = gate(abs(error), card.TOLERANCES[quantity])
    assert verdict.passes, f"{routine} {quantity}: |error| {abs(error):.4g} {scores[quantity].unit}; {verdict.violations}"


@pytest.mark.parametrize("routine,quantity", _quantities())
def test_the_nominal_description_fails_the_same_gate(calibrated, routine, quantity):
    _, _, _, _, nominal_scores, _ = calibrated
    error = nominal_scores[quantity].error
    assert not gate(abs(error), card.TOLERANCES[quantity]).passes, f"{quantity}: the nominal already passes; the gate cannot fail"


def test_the_probe_reaches_under_a_millimetre_and_the_depth_camera_does_not(calibrated):
    _, _, _, scores, _, _ = calibrated
    assert abs(scores["plane_probe.height_mm"].error) < 1.0
    assert abs(scores["plane_depth.height_mm"].error) > abs(scores["plane_probe.height_mm"].error)


def test_the_depth_step_leaves_a_background_model(calibrated):
    _, _, result, _, _, _ = calibrated
    background = result["plane_depth"]["background"]
    assert background["mean_m"].shape == background["std_m"].shape
    assert np.isfinite(background["mean_m"]).mean() > 0.8


def test_eval_twin_predicts_held_out_hand_offs(calibrated):
    _, _, _, _, _, held_out = calibrated
    for key, tolerance in card.EVAL_TOLERANCES.items():
        assert gate(held_out[key], tolerance).passes, (key, held_out[key])


# ----------------------------------------------------------------------------------------------------------------------------------
# Registered in cards/calibration.py beside every other type's routines (the coordinator, 2026-11-11: additively, with the new kinds)


def test_the_belt_routines_are_registered_with_their_kinds():
    from sim2real.cards import registry as reg

    ids = {r.id for r in reg.ROUTINES}
    assert {r.id for r in card.ROUTINES} <= ids, sorted({r.id for r in card.ROUTINES} - ids)
    kinds = {r.id: r.kind for r in reg.ROUTINES}
    # scale, direction and the planes are identify / measure; the belt's speed set-up writes the drive, so it is configure
    assert kinds["conveyor_belt.scale"] == "identify"
    for rid in ("conveyor_belt.direction", "conveyor_belt.plane_depth", "conveyor_belt.plane_probe"):
        assert kinds[rid] in ("identify", "measure"), rid
    setup = reg.routine("conveyor_belt.speed_setup")
    assert setup.kind == "configure" and not setup.identifies
    assert any(c.card == "conveyor" for c in setup.configures)
    assert "conveyor_belt.speed_setup" in {r.id for r in reg.routines_configuring("conveyor")}
    # the scale is the drum radius the actuator card already carries; both routines that find it name each other
    assert "conveyor_belt.scale" in {r.id for r in reg.routines_identifying("conveyor", "drum_radius_m")}
    assert "conveyor.radius_tracker" in reg.routine("conveyor_belt.scale").alternatives
    assert set(reg.routine("conveyor_belt.plane_probe").alternatives) == {"conveyor_belt.plane_depth"}
