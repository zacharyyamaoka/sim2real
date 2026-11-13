"""The home button on the full arm's twin (bam_fb_v2: five-bar + UR wrist + crab claw), sim only: the twin is mounted where the five-bar's is,
reads the same Craig angles, its truths move only the end group, the self-contact regions are the CAD's, and a press from home stays home.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_fullarm.py

Needs bam_ws's twin packages and the bam_fb_v2 bundle (cad-exporter 09374d7, git-archived into the cache on first use); skips without them.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from sim2real.sim.homing import fullarm_home as fh
from sim2real.sim.homing.mujoco_plant import available as twin_available

needs_twin = pytest.mark.skipif(not (twin_available() and fh.CAD_EXPORTER.is_dir()), reason="bam_ws's twin or the cad-exporter clone is not here")


def test_the_cad_self_contact_regions():
    assert fh.in_region_a(106.0, -106.0) and not fh.in_region_a(106.0, 95.0) and not fh.in_region_a(-100.0, 150.0)
    assert fh.in_region_b(131.0, -51.0, 68.0) and not fh.in_region_b(131.0, 49.0, 68.0)


@needs_twin
def test_the_full_arm_twin_sits_where_the_five_bars_does_and_reads_the_same_craig_angles():
    import mujoco

    from sim2real.sim.homing.mujoco_plant import bam_ws_path

    bam_ws_path()
    from bam_fb_test_rig.bundle import bundle_dir, load_bundle
    from bam_fb_test_rig.gravity import CraigMap
    from bam_fb_test_rig.rig import bench_rig

    v11_root = bundle_dir("8957130")
    if not (v11_root / "robot.json").exists():
        pytest.skip("the v11 bundle is not in the cache")
    v2, v11 = fh.build_rig("cad"), bench_rig(load_bundle(v11_root), backlash=None)
    positions = []
    for rig in (v2, v11):
        data = mujoco.MjData(rig.model)
        mujoco.mj_kinematics(rig.model, data)
        positions.append([data.xpos[rig.model.body(name).id].copy() for name in ("l1", "l2", "c1", "c2")])
    assert np.allclose(positions[0], positions[1], atol=1e-6)
    craig_v2, craig_v11 = CraigMap(v2), CraigMap(v11)
    assert craig_v2.sign == craig_v11.sign == {"J2": 1.0, "C1": 1.0}
    assert all(abs(craig_v2.offset[k] - craig_v11.offset[k]) < 1e-9 for k in ("J2", "C1"))


@needs_twin
def test_a_truth_moves_only_the_end_group():
    cad, heavy = fh.build_rig("cad"), fh.build_rig("end+22%")
    for body in range(cad.model.nbody):
        name = cad.model.body(body).name
        ratio = heavy.model.body_mass[body] / cad.model.body_mass[body] if cad.model.body_mass[body] else 1.0
        assert math.isclose(ratio, fh.END_GROUP_MASS_SCALE if name in fh.END_BODIES else 1.0, rel_tol=1e-9), name
    claw = fh.build_rig("claw_high")
    added = claw.model.body_mass[claw.model.body(fh.GRIPPER_BODY).id] - cad.model.body_mass[cad.model.body(fh.GRIPPER_BODY).id]
    assert math.isclose(added, 0.50 - fh.CLAW_CAD_KG, rel_tol=1e-9)


@needs_twin
def test_a_start_past_the_cads_own_stop_is_refused():
    with pytest.raises(ValueError, match="outside the CAD's stops"):
        fh.place(fh.build_rig("cad"), fh.FullStart("L1 through its lower hardstop", -15.0, 60.0))


@needs_twin
def test_a_press_from_home_stays_home_and_holds_the_wrist_still():
    result = fh.run_episode(fh.EpisodeConfig(start=fh.REAL_STARTS[2], comp="v2_cad", truth="cad", wrist="hold"))
    assert result["status"] == "done" and result["reached"], result
    assert max(result["wrist_excursion_deg"]) < 6.0, result["wrist_excursion_deg"]
    assert not result["region_a"] and not result["region_b"]


@needs_twin
def test_the_stripped_scene_keeps_every_mass_inertia_and_contact_pair():
    import mujoco

    root = fh.v2_root()
    full = mujoco.MjModel.from_xml_path(str(root / "mjcf" / "scene.xml"))
    lean = mujoco.MjModel.from_xml_path(str(fh.stripped_scene(root)))
    assert lean.ngeom < full.ngeom / 10
    for field in ("body_mass", "body_ipos", "body_inertia", "body_iquat", "jnt_axis", "jnt_range", "dof_armature", "dof_damping"):
        assert np.allclose(getattr(full, field), getattr(lean, field)), field
    assert lean.npair == full.npair and lean.neq == full.neq
    assert [lean.pair(i).name for i in range(lean.npair)] == [full.pair(i).name for i in range(full.npair)]
