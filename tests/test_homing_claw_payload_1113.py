"""The five-bar twin with the crab claw for the 2.5 lb plate (2026-11-13): mujoco_plant's end-payload swap, written before it exists.

    env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q tests/test_homing_claw_payload_1113.py

Why: Zach is mounting the crab claw on the five-bar in place of the plate. The twin's end group (body "l2", 1.6595 kg) carries the plate
(Fusion "2.5 lbs Weight" 1.1467 kg) and its mount ("Weight To Servo Mount v2" 0.0554 kg), both on J4's axis. The claw hangs on the
unpowered J4, so for J2 / C1 it is a point mass on that axis (bam_ws docs/pick_tracking/claw_payload.py). The swap must take exactly the
plate and its mount out, put the claw's mass on the axis at the plate's centre, leave every other body alone, and compose with the
end-group mass scale (pass 6's x1.2249) in that order.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from sim2real.sim.homing.geometry import DEFAULT_ROOT  # noqa: E402

if not (DEFAULT_ROOT / "hardstops.json").is_file():
    pytest.skip("the v11 bundle is not on disk", allow_module_level=True)

PLATE_KG = 1.146671837566224  # cad-exporter 8957130 fusion360_data.json "2.5 lbs Weight:1"
MOUNT_KG = 0.055438010499180734  # "Weight To Servo Mount v2:1"
CLAW_KG = 0.3712862  # bam_ws claw_payload.CASES["nominal"]: the crab claw's CAD 0.3033 kg x 1.2249


def _plant():
    from sim2real.sim.homing import mujoco_plant  # noqa: PLC0415

    if not mujoco_plant.available():
        pytest.skip("bam_ws's twin is not on disk")
    return mujoco_plant


def _first_moment(model, body: int) -> np.ndarray:
    return model.body_mass[body] * np.asarray(model.body_ipos[body])


def test_the_plate_and_its_mount_are_read_from_the_bundle():
    mujoco_plant = _plant()
    parts = mujoco_plant.end_payload_parts(mujoco_plant.RigCache.get("B0"))
    assert parts["plate"]["mass_kg"] == pytest.approx(PLATE_KG, abs=1e-9)
    assert parts["mount"]["mass_kg"] == pytest.approx(MOUNT_KG, abs=1e-9)
    # both on J4's axis: the l2 frame's x = 0 and z = L2's length (the plate geom's centre, the J4 axis along l2's y)
    for part in parts.values():
        assert abs(part["com_l2_m"][0]) < 1e-3 and part["com_l2_m"][2] == pytest.approx(0.2997, abs=1e-3)


def test_the_swap_takes_out_the_plate_and_mount_and_puts_the_claw_on_j4s_axis():
    mujoco_plant = _plant()
    cad = mujoco_plant.RigCache.get("B0").model
    claw = mujoco_plant.RigCache.get("B0", end_payload_kg=CLAW_KG).model
    index = cad.body(mujoco_plant.END_GROUP_BODY).id
    assert claw.body_mass[index] == pytest.approx(cad.body_mass[index] - PLATE_KG - MOUNT_KG + CLAW_KG, abs=1e-9)
    parts = mujoco_plant.end_payload_parts(mujoco_plant.RigCache.get("B0"))
    expected = (_first_moment(cad, index) - PLATE_KG * np.asarray(parts["plate"]["com_l2_m"]) - MOUNT_KG * np.asarray(parts["mount"]["com_l2_m"])
                + CLAW_KG * np.asarray(parts["plate"]["com_l2_m"]))
    assert np.allclose(_first_moment(claw, index), expected, atol=1e-9)
    assert all(claw.body_mass[b] == cad.body_mass[b] for b in range(cad.nbody) if b != index)
    assert np.all(claw.body_inertia[index] > 0.0)


def test_swapping_in_the_plates_own_mass_leaves_the_gravity_load_where_it_was():
    mujoco_plant = _plant()
    cad = mujoco_plant.RigCache.get("B0").model
    same = mujoco_plant.RigCache.get("B0", end_payload_kg=PLATE_KG + MOUNT_KG).model
    index = cad.body(mujoco_plant.END_GROUP_BODY).id
    assert same.body_mass[index] == pytest.approx(cad.body_mass[index], abs=1e-9)
    in_plane = [0, 2]  # the l2 frame's x and z span the arm's plane (y is J4's axis, out of it)
    assert np.allclose(_first_moment(same, index)[in_plane], _first_moment(cad, index)[in_plane], atol=1e-9)


def test_the_claw_composes_with_the_end_group_scale_swap_first():
    mujoco_plant = _plant()
    claw = mujoco_plant.RigCache.get("B0", end_payload_kg=CLAW_KG).model
    both = mujoco_plant.RigCache.get("B0", mujoco_plant.END_GROUP_MASS_SCALE, end_payload_kg=CLAW_KG).model
    index = claw.body(mujoco_plant.END_GROUP_BODY).id
    assert both.body_mass[index] == pytest.approx(claw.body_mass[index] * mujoco_plant.END_GROUP_MASS_SCALE, abs=1e-9)


def test_the_plant_carries_the_payload_it_was_given():
    mujoco_plant = _plant()
    plant = mujoco_plant.MujocoRigPlant("B0", end_payload_kg=CLAW_KG, settle_s=0.0)
    assert plant.end_payload_kg == CLAW_KG
    assert plant.rig is mujoco_plant.RigCache.get("B0", end_payload_kg=CLAW_KG)
    assert mujoco_plant.MujocoRigPlant("B0", settle_s=0.0).end_payload_kg is None
