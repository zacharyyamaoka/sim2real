"""The +gff rows (gravity_ff): the home button's gravity feed-forward on a homing procedure's sequence, the twin-contact scoring and the
verdict that judges against it. Pure sequence tests on a stand-in comp - no MuJoCo, no bam_ws.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_gravity_ff.py
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from robot_msgs.control import JointCommand, JointCommandStep, Reached, Settled  # noqa: E402

from sim2real.sim.homing.bench import prior_for  # noqa: E402
from sim2real.sim.homing.geometry import C1, DEFAULT_ROOT, DRIVES, J1, J2, FivebarGeometry  # noqa: E402
from sim2real.sim.homing.gravity_ff import BOARD_MAX_NM, GravityFF, procedure, with_gravity_ff  # noqa: E402
from sim2real.sim.homing.procedures import BOARD_KP_NM_PER_RAD, SEEK_CAP_NM, TwoLevelTouch, TviewV2  # noqa: E402

if not (DEFAULT_ROOT / "hardstops.json").is_file():
    pytest.skip("the v11 bundle is not on disk", allow_module_level=True)


class StandIn:
    """A comp: J2 6.6 N.m and C1 4.6 N.m at J2's upper stop (the identified comp's numbers), scaled by sin of J2 elsewhere, cos J1."""

    comp = "stand-in"

    def torque(self, pose):
        if pose.get(J2) is None or pose.get(C1) is None:
            return None
        tilt = math.cos(pose[J1]) if pose.get(J1) is not None else 1.0
        scale = math.sin(pose[J2]) / math.sin(math.radians(125.0))
        return {J1: 0.0, J2: 6.6 * scale * tilt, C1: 4.6 * scale * tilt}


@pytest.fixture(scope="module")
def prior():
    return prior_for(FivebarGeometry())


def _by_name(sequence):
    return {step.name: step for step in sequence.steps}


def _command(step, joint):
    return next(c for c in step.commands if c.joint == joint)


def test_a_seek_presses_with_its_push_over_the_gravity_it_lifts_and_keeps_the_two_level_ratio(prior):
    original = TwoLevelTouch().plan(prior, [])
    gff, note = with_gravity_ff(original, prior, StandIn())
    steps = _by_name(gff)
    half, full = steps["J2+C1 press half"], steps["J2+C1 press full"]
    # J2: 10 N.m + 6.6 does not fit the board's 12, so both levels shrink: full = 12 - 6.6 = 5.4 N.m of push, half = 2.7
    assert _command(full, J2).max_effort == pytest.approx(BOARD_MAX_NM)
    assert _command(half, J2).max_effort == pytest.approx(0.5 * (BOARD_MAX_NM - 6.6) + 6.6)
    # C1: 7 + 4.6 fits; the levels are the original's pushes over the gravity
    assert _command(full, C1).max_effort == pytest.approx(SEEK_CAP_NM[C1] + 4.6)
    assert _command(half, C1).max_effort == pytest.approx(0.5 * SEEK_CAP_NM[C1] + 4.6)
    for step in (half, full):
        assert _command(step, J2).feedforward_effort == pytest.approx(6.6)
        assert _command(step, C1).feedforward_effort == pytest.approx(4.6)
        assert _command(step, J1).feedforward_effort == 0.0  # the comp is the five-bar's two drives
    # nothing renamed, nothing dropped: every original step is there, in order
    names = [s.name for s in gff.steps]
    assert [n for n in names if "(waypoint" not in n] == [s.name for s in original.steps]
    assert note["waypoint_steps_added"] > 0 and not note["no_comp_steps"]


def test_a_limp_joint_or_an_unknown_pose_gets_no_feed_forward(prior):
    gff, _ = with_gravity_ff(TwoLevelTouch().plan(prior, []), prior, StandIn())
    first = gff.steps[0]  # "J1 holds": J2 and C1 limp, the pose unknown
    assert all(c.feedforward_effort == 0.0 for c in first.commands)
    assert [c.mode for c in first.commands if c.joint != J1] == ["limp", "limp"]


def test_a_long_move_walks_the_home_buttons_waypoints_each_with_its_own_gravity(prior):
    original = TwoLevelTouch().plan(prior, [])
    gff, _ = with_gravity_ff(original, prior, StandIn())
    walk = [s for s in gff.steps if s.name.startswith("J2 + C1 home")]
    assert walk[-1].name == "J2 + C1 home" and walk[-1].done_when == _by_name(original)["J2 + C1 home"].done_when
    targets = [_command(s, J2).position for s in walk]
    assert max(abs(b - a) for a, b in zip(targets[:-1], targets[1:], strict=True)) <= math.radians(4.0) + 1e-9
    assert all(s.done_when == (Reached(joints=(J2, C1), tolerance=0.06),) for s in walk[:-1])
    feedforward = [_command(s, J2).feedforward_effort for s in walk]
    assert feedforward[0] > feedforward[-1]  # from near the upper stop toward home: the gravity follows the pose


def test_j1_on_its_stop_tilts_the_plane_level_and_the_feed_forward_with_it(prior):
    gff, _ = with_gravity_ff(TwoLevelTouch().plan(prior, []), prior, StandIn())
    press = _by_name(gff)["J1 press full"]  # J1 on its upper stop (89.98 deg): the five-bar's plane is level
    assert abs(_command(press, J2).feedforward_effort) < 0.01


def test_gff_is_a_new_row_beside_the_original():
    assert procedure("press_reverse+gff").name == "press_reverse+gff"
    assert isinstance(procedure("press_reverse+gff"), GravityFF)
    assert procedure("press_reverse").name == "press_reverse"


def test_a_rehold_keeps_the_feed_forward_its_joint_was_carrying():
    from sim2real.sim.homing.sag_proof import rehold_step  # noqa: PLC0415

    previous = JointCommandStep(name="hold", commands=(JointCommand.hold(J1, max_effort=7.0),
                                                       JointCommand.hold(J2, max_effort=10.0, feedforward_effort=6.6),
                                                       JointCommand.limp(C1)), done_when=(Settled(joints=(J2,), speed=0.02, dwell=1.0),), timeout=10.0)
    seek = JointCommandStep(name="seek", commands=(JointCommand.hold(J1, max_effort=7.0),
                                                   JointCommand.move_by(J2, 1.0, speed=0.6, max_effort=12.0, feedforward_effort=6.6),
                                                   JointCommand.move_by(C1, 1.0, speed=0.6, max_effort=8.0, feedforward_effort=4.6)),
                            done_when=(Settled(joints=(J2,), speed=0.02, dwell=1.0),), timeout=10.0)
    step = rehold_step(previous, seek, [J2, C1])
    assert _command(step, J2).feedforward_effort == pytest.approx(6.6)  # held with it before: kept
    assert _command(step, C1).feedforward_effort == 0.0  # limp before: it rests where it fell, no plan names that pose


def test_tviews_pin_is_cap_over_the_real_boards_kp():
    from sim2real.sim.homing.mujoco_plant import REAL_BOARD_RECORD  # noqa: PLC0415

    for joint, role in ((J1, "J1"), (J2, "J2"), (C1, "C1")):
        assert BOARD_KP_NM_PER_RAD[joint] == pytest.approx(REAL_BOARD_RECORD[role]["kp"] / (2.0 * math.pi))
    prior = prior_for(FivebarGeometry())
    pin = _command(_by_name(TviewV2().plan(prior, []))["2b. ... until C1 has stalled too"], J2)
    assert pin.mode == "move_by" and pin.distance == pytest.approx(SEEK_CAP_NM[J2] / BOARD_KP_NM_PER_RAD[J2])


def test_the_twin_prior_swaps_only_the_stops_it_measured(prior):
    from sim2real.sim.homing.mujoco_bench import twin_prior  # noqa: PLC0415

    contacts = {(J2, +1): math.radians(124.7144)}
    twin = twin_prior(prior, contacts)
    assert twin.stops.q_rad(J2, +1) == pytest.approx(math.radians(124.7144))
    assert twin.stops.get(J2, +1).basis == "measured"
    assert twin.stops.q_rad(C1, +1) == prior.stops.q_rad(C1, +1)


def test_tview_against_the_twin_moves_each_zero_by_the_twins_offset_from_cad(prior):
    from robot_models.homing.types import HomingResult, JointZero  # noqa: PLC0415

    from sim2real.sim.homing.mujoco_bench import twin_prior  # noqa: PLC0415

    tview = TviewV2()
    zeros = tuple(JointZero(j, 1.0, 0.0, 1, (+1,)) for j in DRIVES)
    tview.observe = lambda p, phases: HomingResult(zeros, None, p.stops, (), "kinematic")  # noqa: ARG005
    twin = twin_prior(prior, {(J2, +1): prior.stops.q_rad(J2, +1) - math.radians(0.285)})
    result = tview.observe_vs_twin(prior, twin, [])
    assert result.zero(J2).offset_rad == pytest.approx(1.0 - math.radians(0.285))
    assert result.zero(J1).offset_rad == pytest.approx(1.0)


def test_the_verdict_judges_against_the_twin_and_keeps_the_cad_verdict():
    from sim2real.sim.homing.mujoco_bench import verdicts  # noqa: PLC0415

    name = "recover_first+single_touch"
    cards = {"B0": {name: {"reliability_pct": 100.0, "joint_angle_error_deg": 0.2855}}}
    twin = {"B0": {name: {"reliability_pct": 100.0, "joint_angle_error_deg": 0.004}}}
    reference = {"cards": {"B0": {name: {"joint_angle_error_deg": 0.0039}}}}
    v = verdicts(cards, reference, twin)["B0"][name]
    assert v["pass"] is True and v["pass_vs_cad"] is False
    assert v["zero_vs_kinematic_pass"] is False and v["zero_vs_kinematic_vs_twin_pass"] is True
    # the gate itself is unchanged: 0.1 deg over the kinematic p95
    twin["B0"][name]["joint_angle_error_deg"] = 0.0039 + 0.1001
    assert verdicts(cards, reference, twin)["B0"][name]["pass"] is False
    gff = {"B0": {name + "+gff": {"reliability_pct": 100.0, "joint_angle_error_deg": 0.004}}}
    assert verdicts(gff, reference, gff)["B0"][name + "+gff"]["kinematic_zero_p95_deg"] == 0.0039  # judged against its original
