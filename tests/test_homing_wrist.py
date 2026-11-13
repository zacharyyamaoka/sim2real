"""The homing bench's wrist rung (sim2real.sim.homing.wrist): bam_ur_wrist's KarnoppPlant behind the homing seam, single_touch and
press_reverse on CAN 14 / 15 / 16. Needs bam_ws's bam_ur_wrist and its bundle on disk (skips without); SIM2REAL_SLOW=1 adds an episode.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_wrist.py
"""

from __future__ import annotations

import math
import os

import pytest

pytest.importorskip("mujoco")
pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from robot_msgs.control import Reached, Stall  # noqa: E402

from sim2real.sim.homing import wrist  # noqa: E402

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"


@pytest.fixture(scope="module")
def rig():
    if not wrist.available():
        pytest.skip("bam_ws's bam_ur_wrist is not on disk")
    try:
        return wrist.WristRig.get()
    except Exception as error:  # noqa: BLE001 -- the bundle cache may be absent on this machine
        pytest.skip(f"the wrist bundle does not load: {error}")


def test_single_touch_homes_tip_first_and_stalls_only_pressing_at_its_cap(rig):
    sequence = wrist.WristSingleTouch().plan(wrist.prior_for(rig), [])
    seeks = [s for s in sequence.steps if s.name.endswith("seeks")]
    assert [s.name for s in seeks] == ["CAN 16 seeks", "CAN 15 seeks", "CAN 14 seeks"]  # bam_ur_wrist.homing.HOME_ORDER
    for step in seeks:
        (stall,) = [c for c in step.done_when if isinstance(c, Stall)]
        assert stall.lead == pytest.approx(0.06 + wrist.SEEK_CAP_NM / wrist.KP_NM_PER_RAD)
        joint = stall.joint
        assert step.define_position == {joint: rig.cad.q_rad(joint, rig.side[joint])}
    homes = [s for s in sequence.steps if s.name.endswith(" home")]
    assert all(any(isinstance(c, Reached) and c.tolerance > math.radians(5.0) for c in s.done_when) for s in homes)


def test_press_reverse_touches_both_stops_of_every_joint_at_two_levels(rig):
    sequence = wrist.WristPressReverse().plan(wrist.prior_for(rig), [])
    names = [s.name for s in sequence.steps]
    for can in wrist.CAN_IDS:
        for tag in ("near", "far"):
            assert f"CAN {can} {tag} press half" in names and f"CAN {can} {tag} press full" in names


def test_the_plant_reads_board_plus_frame_and_scores_against_the_latched_offset(rig):
    from robot_msgs.control import ServoCommand  # noqa: PLC0415

    plant = wrist.WristPlant()
    start = wrist.starts(rig, 1)[0]
    state = plant.reset(start)
    truth = plant.truth()
    for i, joint in enumerate(rig.joints):  # q_joint = board + offset: the offset is the hidden zero a procedure estimates
        assert state.position[i] + truth["true_offset_rad"][joint] == pytest.approx(start.q_rad[joint], abs=1e-6)
    state = plant.tick(ServoCommand(name=rig.joints, position=[math.nan] * 3, max_effort=[0.0] * 3), 0.01, {rig.joints[0]: 1.0})
    assert state.position[0] == pytest.approx(1.0, abs=2e-3)


@pytest.mark.skipif(not SLOW, reason="a whole wrist episode, ~90 s: SIM2REAL_SLOW=1")
def test_single_touch_homes_from_the_real_power_up(rig):
    record, note = wrist.run_episode("single_touch", wrist.starts(rig, 1)[0], None)
    assert record["finished"], record["outcome"]
