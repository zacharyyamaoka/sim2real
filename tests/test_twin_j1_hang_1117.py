"""The bam_fb_v2 twin hangs J1 where the real arm does, by default (the W1 dispatcher, 2026-11-17; bam_ws PEP 0060 and its addendum).

The real arm: 29 J1 rests of rackq 20ad + r1a (fixtures/j1_rests_1117.json: the measured J1 torque, the side J1 arrived from, J1's board
angle and the twin's qpos at each rest), through the pose-blind estimator the arm's numbers came from - A sin(q_board - hang) + f x side over
the 23 rests with a known side - give A 4.95 N.m and hang URDF -11.2 deg. The twin: MuJoCo's own J1 gravity (qfrc_bias at rest, mj_rne) at
the same 29 poses, through the SAME estimator. On the CAD's masses it hangs at +24.0 deg (the shoulder's COM 32 mm across J1's plane); on
the measured masses the description names, at -11.3.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_twin_j1_hang_1117.py

Needs bam_ws's twin packages and the bam_fb_v2 bundle (cad-exporter 09374d7); skips without them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from sim2real.sim.homing import fullarm_home as fh
from sim2real.sim.homing.mujoco_plant import available as twin_available

needs_twin = pytest.mark.skipif(not (twin_available() and fh.CAD_EXPORTER.is_dir()), reason="bam_ws's twin or the cad-exporter clone is not here")
RESTS = json.loads((Path(__file__).parent / "fixtures" / "j1_rests_1117.json").read_text())
MEASURED_HANG_DEG = -11.18  # the arm's (RESTS["measured_pose_blind"]); the acceptance: the default twin within 1 deg of it


def j1_hang(model) -> tuple[float, float]:
    """(hang URDF deg, amplitude N.m) of a MuJoCo model's J1 gravity at the 29 rests, through the arm's own pose-blind estimator."""

    import mujoco

    data, bias = mujoco.MjData(model), np.zeros(model.nv)
    dof = int(model.joint("revolute_3").dofadr[0])
    torques = []
    for rest in RESTS["rests"]:
        data.qpos[:] = model.qpos0
        for name, value in rest["qpos_by_joint_rad"].items():
            data.qpos[int(model.joint(name).qposadr[0])] = value
        data.qvel[:] = 0.0
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        mujoco.mj_comVel(model, data)
        mujoco.mj_rne(model, data, 0, bias)
        torques.append(float(bias[dof]))
    sided = [(rest, t) for rest, t in zip(RESTS["rests"], torques, strict=True) if rest["arrived"]]
    X = np.array([[math.sin(r["board_j1_rad"]), -math.cos(r["board_j1_rad"]), r["arrived"]] for r, _ in sided])
    (a, b, _f), *_ = np.linalg.lstsq(X, np.array([t for _, t in sided]), rcond=None)
    return math.degrees(math.atan2(b, a) - RESTS["j1_zero_board_rad"]), math.hypot(a, b)


def test_the_estimator_reads_the_arm_as_measured():
    """The same estimator on the measured torques reproduces the arm's -11.2 deg / 4.95 N.m (the ruler is the arm's own)."""

    sided = [r for r in RESTS["rests"] if r["arrived"]]
    X = np.array([[math.sin(r["board_j1_rad"]), -math.cos(r["board_j1_rad"]), r["arrived"]] for r in sided])
    (a, b, _f), *_ = np.linalg.lstsq(X, np.array([r["torque_nm"] for r in sided]), rcond=None)
    assert math.degrees(math.atan2(b, a) - RESTS["j1_zero_board_rad"]) == pytest.approx(MEASURED_HANG_DEG, abs=0.01)
    assert math.hypot(a, b) == pytest.approx(4.947, abs=0.002) and len(RESTS["rests"]) == 29 and len(sided) == 23


@needs_twin
def test_the_default_twin_hangs_j1_within_a_degree_of_the_arm():
    """``build_rig()`` as every caller gets it: J1's hang within 1 deg of the arm's, its amplitude inside the arm's 95 % interval."""

    hang, amplitude = j1_hang(fh.build_rig().model)
    assert abs(hang - MEASURED_HANG_DEG) <= 1.0, (hang, amplitude)
    low, high = RESTS["measured_pose_blind"]["A_95_nm"]
    assert low <= amplitude <= high, amplitude


@needs_twin
def test_every_builder_defaults_to_the_measured_masses():
    """fullarm_plant's contact twin and its FullArmHomingPlant take the same default as fullarm_home.build_rig."""

    from sim2real import masses
    from sim2real.sim.homing import fullarm_plant as fp

    hang, _ = j1_hang(fp.build_rig("B0").model)
    assert abs(hang - MEASURED_HANG_DEG) <= 1.0, hang
    assert masses.DEFAULT == "measured" and fh.build_rig().truth["masses"] == "measured"
    assert fh.build_rig().truth["masses_source"]["sha256"] == masses.SOURCE["sha256"]


@needs_twin
def test_the_cad_opt_out_still_hangs_where_the_bundle_does():
    """``masses="cad"`` is the bundle as exported, unchanged by the default's move: J1 at +24.02 deg / 4.731 N.m at the rests (the golden,
    measured on main 2749c82 before the change), the shoulder at the CAD's 8.6576 kg / 32.0 mm across J1's plane."""

    from sim2real.sim.homing import fullarm_plant as fp

    for model in (fh.build_rig(masses="cad").model, fp.build_rig("B0", masses="cad").model):
        hang, amplitude = j1_hang(model)
        assert hang == pytest.approx(24.0157, abs=0.01) and amplitude == pytest.approx(4.7308, abs=0.001), (hang, amplitude)
        shoulder = model.body("shoulder").id
        assert model.body_mass[shoulder] == pytest.approx(8.6576, abs=1e-6) and model.body_ipos[shoulder][1] == pytest.approx(0.0319874, abs=1e-7)
    with pytest.raises(ValueError, match="masses must be one of"):
        fh.build_rig(masses="as_built")
