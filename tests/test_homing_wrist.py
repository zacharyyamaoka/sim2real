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


def test_every_start_is_a_pose_the_rig_can_rest_in(rig):
    """A start is where the wrist rests at power-up, so its links cannot interpenetrate. 2026-11-12: Sobol draw 14 put the tip's ArUco
    holder 6 mm into the base's marker plate; the first tick ejected CAN 15 at 7 rad/s and both procedures were charged a guard trip for
    a pose no real wrist can be in."""
    import mujoco  # noqa: PLC0415

    for start in wrist.starts(rig, 15):
        plant = wrist.WristPlant()
        plant.reset(start)
        mujoco.mj_forward(plant.plant.model, plant.plant.data)
        assert plant.plant.data.ncon == 0, f"{start.name}: {plant.plant.data.ncon} contacts at rest"
    names = [s.name for s in wrist.starts(rig, 15)]
    assert len(names) == 16 and names[:15] == ["real_power_up"] + [f"sobol-{k:02d}" for k in range(14)]  # draws keep their names


# ---------------------------------------------------------------------------------------------------------------- self-contact (pass 5)
# Pass 4 (homing_wrist_mujoco_2026-11-12.json): on sobol-01, 03 and 12 CAN 15's tip-first seek drove the ArUco holder (hard_stop_3) into
# the base's marker plate, and single_touch took that stall as CAN 15's stop - a frame 19-63 deg wrong, returned as a zero. The pose each
# claimed at that stall: CAN 14 where it was holding (truth from that run's note "first_self_contact"), CAN 15 on its CAD lower stop.
PASS4_LINK_STALLS = {"sobol-01": (-158.23, 0.28), "sobol-03": (138.89, 0.29), "sobol-12": (161.02, 0.28)}  # CAN 14, CAN 16 deg


def _claim(rig, q14_deg, q15_rad, q16_deg):
    """A stall reading and a result whose zeros are all 0, so the claimed pose IS the reading (the detector's arithmetic is separate)."""
    from types import SimpleNamespace  # noqa: PLC0415

    can15 = rig.joints[1]
    raw = dict(zip(rig.joints, (math.radians(q14_deg), q15_rad, math.radians(q16_deg)), strict=True))
    result = SimpleNamespace(zero=lambda joint: SimpleNamespace(offset_rad=0.0))
    return [(can15, -1, wrist.Reading(0, raw, {j: 1.0 for j in rig.joints}))], result


@pytest.mark.parametrize("start", sorted(PASS4_LINK_STALLS))
def test_a_stall_whose_claimed_pose_puts_the_holder_in_the_base_plate_is_refused(rig, start):
    q14, q16 = PASS4_LINK_STALLS[start]
    stalls, result = _claim(rig, q14, rig.cad.q_rad(rig.joints[1], -1), q16)
    faults = wrist.link_stall_faults(stalls, result)
    assert len(faults) == 1 and "base_link" in faults[0] and "hard_stop_3" in faults[0], faults


def test_a_stall_on_the_stop_tooth_is_not_refused(rig):
    """The real power-up's CAN 15 stall (CAN 14 holding at 81 deg) and the far stop: the claimed poses are poses the wrist can be in."""
    for q14 in (81.0, 0.0, -100.0, 100.0):
        for side in (-1, +1):
            stalls, result = _claim(rig, q14, rig.cad.q_rad(rig.joints[1], side), 0.0)
            assert wrist.link_stall_faults(stalls, result) == [], (q14, side)


def test_single_touch_park_defines_can_15_last_with_can_14_at_home(rig):
    sequence = wrist.WristSingleTouchPark().plan(wrist.prior_for(rig), [])
    seeks = [s.name for s in sequence.steps if s.name.endswith("seeks")]
    assert seeks == ["CAN 16 seeks", "CAN 15 park seeks", "CAN 14 seeks", "CAN 15 seeks"]
    names = [s.name for s in sequence.steps]
    assert names.index("CAN 14 home") < names.index("CAN 15 seeks")  # CAN 15's defining touch runs with CAN 14 at home
    assert wrist.WristSingleTouch().plan(wrist.prior_for(rig), []).steps == wrist.WristSingleTouch().plan(wrist.prior_for(rig), []).steps


def test_the_park_variant_moves_only_where_no_link_can_touch(rig):
    """The variant's safety, on the rig's own CAD (SelfContactMap, CAN 16 at home): CAN 14 sweeps its whole travel with CAN 15 parked
    (park in [0.6, 63.2] deg +- 4.8 held sag -> |CAN 15| <= 70), and CAN 15 sweeps its whole travel with CAN 14 at home (|CAN 14| <= 12).
    The nearest touching pose is >= 30 deg away from both strips (|CAN 14| >= 106, |CAN 15| >= 107), so a 2 deg grid cannot miss one."""
    contact = wrist.SelfContactMap.get()
    j14, j15, j16 = rig.joints
    sweep = [float(x) for x in range(-170, 171, 2)]
    park = [float(x) for x in range(-70, 71, 2)]
    home14 = [float(x) for x in range(-12, 13, 2)]
    touching = [(a, b) for a in sweep for b in park if contact.pairs({j14: math.radians(a), j15: math.radians(b), j16: 0.0})]
    touching += [(a, b) for a in home14 for b in sweep if contact.pairs({j14: math.radians(a), j15: math.radians(b), j16: 0.0})]
    assert touching == []
    assert contact.pairs({j14: math.radians(140.0), j15: math.radians(-150.0), j16: 0.0})  # the map does see the band (not vacuous)


@pytest.mark.skipif(not SLOW, reason="the whole self-contact set on a 3 deg grid at three CAN 16 angles, ~40 s: SIM2REAL_SLOW=1")
def test_every_self_contact_is_far_round_on_both_can_14_and_can_15(rig):
    contact = wrist.SelfContactMap.get()
    j14, j15, j16 = rig.joints
    grid = [float(x) for x in range(-170, 171, 3)]
    for q16 in (-8.0, 0.0, 8.0):
        cells = [(a, b) for a in grid for b in grid if contact.pairs({j14: math.radians(a), j15: math.radians(b), j16: math.radians(q16)})]
        assert cells and min(abs(a) for a, _ in cells) >= 100.0 and min(abs(b) for _, b in cells) >= 100.0, q16


@pytest.mark.skipif(not SLOW, reason="three wrist episodes, ~3 min: SIM2REAL_SLOW=1")
@pytest.mark.parametrize("start", sorted(PASS4_LINK_STALLS))
def test_single_touch_reports_the_link_stall_instead_of_defining_a_frame(rig, start):
    record, note = wrist.run_episode("single_touch", {s.name: s for s in wrist.starts(rig, 15)}[start], None)
    assert not record["finished"] and record["outcome"].startswith("refused") and "hard_stop_3" in record["outcome"], record["outcome"]


@pytest.mark.skipif(not SLOW, reason="three wrist episodes, ~4 min: SIM2REAL_SLOW=1")
@pytest.mark.parametrize("start", sorted(PASS4_LINK_STALLS))
def test_single_touch_park_homes_where_single_touch_stalled_on_a_link(rig, start):
    record, note = wrist.run_episode("single_touch_park", {s.name: s for s in wrist.starts(rig, 15)}[start], wrist.twin_contacts())
    assert record["finished"], record["outcome"]
    assert all(abs(s["link_deg"] - s["cad_deg"]) <= 1.0 for s in record["stalls"])  # every stall it relied on was its stop tooth
    assert max(abs(v) for v in note["zero_error_vs_twin_deg"].values()) <= wrist.GATE_DEG
    assert note["park_touch_short_deg"] > 1.0  # the park touch did meet the plate here: the variant, not luck, is what homed it
