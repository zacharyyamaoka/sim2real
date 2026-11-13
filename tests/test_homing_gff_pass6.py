"""Pass 6 of the homing bench: gravity feed-forward on every hold and move, the real arm's heavier end group and its runaway stop on the
MuJoCo rung, judged in the form the real arm runs (gravity_ff, sag_proof, mujoco_plant, real_bench.RealRow, gff_rung).

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl SIM2REAL_SLOW=1 /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_gff_pass6.py

Why (the real rung, 2026-11-13): 16 real episodes, 0 finished - the zeros repeat, then 0.1-0.2 s after each zero the first hold, carrying no
gravity feed-forward, let J2 drop past the rack's 86 deg/s runaway ceiling (the end group 22 % over CAD). The sequence tests run on a
stand-in comp (no MuJoCo); the plant tests need bam_ws's twin and skip without it; SIM2REAL_SLOW=1 adds the whole-episode red / green pair.
"""

from __future__ import annotations

import math
import os

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from robot_msgs.control import JointCommand, JointCommandStep, Settled, Stall  # noqa: E402

from sim2real.sim.homing.bench import prior_for  # noqa: E402
from sim2real.sim.homing.geometry import C1, DEFAULT_ROOT, J1, J2, FivebarGeometry  # noqa: E402

if not (DEFAULT_ROOT / "hardstops.json").is_file():
    pytest.skip("the v11 bundle is not on disk", allow_module_level=True)

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"


class StandIn:
    """A comp that depends on both drives (so a pose with C1 unknown has no gravity): J2 6.6 / C1 4.6 N.m at the upper stops, scaled by
    sin J2 and by (1 + 0.1 sin C1) elsewhere, plus 0.5 N.m (never exactly 0, so an un-fed command cannot pass as fed), cos J1."""

    comp = "stand-in"

    def torque(self, pose):
        if pose.get(J2) is None or pose.get(C1) is None:
            return None
        tilt = math.cos(pose[J1]) if pose.get(J1) is not None else 1.0
        scale = math.sin(pose[J2]) / math.sin(math.radians(125.0)) * (1.0 + 0.1 * math.sin(pose[C1]))
        return {J1: 0.0, J2: (6.6 * scale + 0.5) * tilt, C1: (4.6 * scale + 0.5) * tilt}


@pytest.fixture(scope="module")
def prior():
    return prior_for(FivebarGeometry())


def _command(step, joint):
    return next(c for c in step.commands if c.joint == joint)


def _fed(procedure, prior):
    from sim2real.sim.homing.gravity_ff import procedure_frame, with_gravity_ff  # noqa: PLC0415

    return with_gravity_ff(procedure.plan(prior, []), prior, StandIn(), frame=procedure_frame(procedure, prior))


def _real_form(name):
    """The bare procedure with J1 held - what the real lane's RealRow feeds (GravityFF wraps J1Held(procedure))."""
    from sim2real.sim.homing.procedures import PROCEDURES  # noqa: PLC0415
    from sim2real.sim.homing.real_plant import J1Held  # noqa: PLC0415

    return J1Held(PROCEDURES[name]())


# ---------------------------------------------------------------------------------------------------------------- the plan


@pytest.mark.parametrize("name", ["single_touch", "tview_v2"])
def test_every_hold_and_move_after_the_zero_carries_gravity_feed_forward(prior, name):
    sequence, note = _fed(_real_form(name), prior)
    names = [s.name for s in sequence.steps]
    zero = max(k for k, s in enumerate(sequence.steps) if s.define_position)
    unfed = {entry["step"] for entry in note["unfed_unknown_pose_steps"]}
    assert not unfed & set(names[zero + 1:]), "a hold or move after the zero runs un-fed"
    for step in sequence.steps[zero + 1:]:
        for joint in (J2, C1):
            command = _command(step, joint)
            assert command.mode in ("hold", "position") and command.feedforward_effort != 0.0, (step.name, joint)


def test_a_hold_carries_the_gravity_at_the_pose_it_holds(prior):
    sequence, _ = _fed(_real_form("single_touch"), prior)
    hold = next(s for s in sequence.steps if s.name == "J1 seeks")  # the first step after single_touch's zero (J1 held)
    pose = {J1: None, J2: prior.stops.q_rad(J2, +1), C1: prior.stops.q_rad(C1, +1)}
    g = StandIn().torque(pose)
    assert _command(hold, J2).feedforward_effort == pytest.approx(g[J2])
    assert _command(hold, C1).feedforward_effort == pytest.approx(g[C1])


def test_a_move_is_fed_from_the_pose_each_piece_starts_at_and_the_pose_it_ends_at(prior):
    from sim2real.sim.homing.procedures import home_cad  # noqa: PLC0415

    sequence, _ = _fed(_real_form("single_touch"), prior)
    walk = [s for s in sequence.steps if s.name.startswith("J2 + C1 home")]
    assert len(walk) > 1
    previous = {J1: None, J2: prior.stops.q_rad(J2, +1), C1: prior.stops.q_rad(C1, +1)}
    for piece in walk:
        end = {J1: None, J2: _command(piece, J2).position, C1: _command(piece, C1).position}
        g0, g1 = StandIn().torque(previous), StandIn().torque(end)
        for joint in (J2, C1):
            assert _command(piece, joint).feedforward_effort == pytest.approx(0.5 * (g0[joint] + g1[joint])), (piece.name, joint)
        previous = end
    home = home_cad(prior)
    assert previous[J2] == pytest.approx(home[J2]) and previous[C1] == pytest.approx(home[C1])


def test_a_seek_from_a_pose_no_plan_knows_carries_no_feed_forward(prior):
    # pass 5: two_level_touch+gff's first seek carried the upper stop's 6.6 N.m from the hanging rest and lunged J2 to 3.4 rad/s on MuJoCo
    from sim2real.sim.homing.procedures import TwoLevelTouch  # noqa: PLC0415

    sequence, note = _fed(TwoLevelTouch(), prior)
    first_seek = next(s for s in sequence.steps if s.name == f"J2+C1 seek {J2}")
    assert _command(first_seek, J2).feedforward_effort == 0.0 and _command(first_seek, C1).feedforward_effort == 0.0
    assert f"J2+C1 seek {J2}" in {entry["step"] for entry in note["unfed_unknown_pose_steps"]}


def test_tviews_feed_forward_is_planned_in_cad_not_in_zachs_crank_frame(prior):
    sequence, _ = _fed(_real_form("tview_v2"), prior)
    hold = next(s for s in sequence.steps if s.name.startswith("3. cfg-set-output"))
    g = StandIn().torque({J1: None, J2: prior.stops.q_rad(J2, +1), C1: prior.stops.q_rad(C1, +1)})
    assert _command(hold, C1).feedforward_effort == pytest.approx(g[C1], rel=1e-3)
    assert _command(hold, J2).feedforward_effort == pytest.approx(g[J2], rel=1e-3)


def test_a_feed_forward_never_exceeds_its_commands_cap(prior):
    for name in ("single_touch", "tview_v2"):
        sequence, _ = _fed(_real_form(name), prior)
        for step in sequence.steps:
            for command in step.commands:
                if command.mode != "limp":
                    assert abs(command.feedforward_effort) <= float(command.max_effort) + 1e-9, (name, step.name)


def test_single_touch_and_tview_have_gff_rows_on_both_rungs():
    from sim2real.sim.homing.gravity_ff import GFF_VARIANTS, GravityFF, procedure  # noqa: PLC0415
    from sim2real.sim.homing.real_bench import NOT_RUN, ROWS  # noqa: PLC0415

    for name in ("single_touch+gff", "tview_v2+gff"):
        assert name in GFF_VARIANTS and name in ROWS and name not in NOT_RUN
        built = procedure(name, ff_scale=0.75)
        assert isinstance(built, GravityFF) and built.ff_scale == 0.75 and built.name == name


def test_a_re_hold_keeps_a_joint_pressing_its_stop_pinned_on_it():
    from sim2real.sim.homing.procedures import PIN_SPEED  # noqa: PLC0415
    from sim2real.sim.homing.sag_proof import KP_NM_PER_RAD, rehold_step  # noqa: PLC0415

    previous = JointCommandStep(name="J2 seeks", commands=(JointCommand.hold(J1, max_effort=7.0),
                                                           JointCommand.move_by(J2, 15.0, speed=0.63, max_effort=10.0),
                                                           JointCommand.limp(C1)), done_when=(Stall(joint=J2),), timeout=40.0)
    step = JointCommandStep(name="C1 seeks (J2 pushing)", commands=(JointCommand.hold(J1, max_effort=7.0),
                                                                    JointCommand.move_by(J2, 15.0, speed=0.63, max_effort=12.0),
                                                                    JointCommand.move_by(C1, 15.0, speed=0.63, max_effort=7.0)),
                            done_when=(Stall(joint=C1),), timeout=40.0)
    rehold = rehold_step(previous, step, [C1])
    j2 = _command(rehold, J2)
    assert j2.mode == "move_by" and j2.distance == pytest.approx(10.0 / KP_NM_PER_RAD[J2]) and j2.speed == PIN_SPEED
    assert _command(rehold, C1).mode == "hold"
    assert rehold.done_when == (Settled(joints=(C1,), speed=0.02, dwell=1.0),)


# ---------------------------------------------------------------------------------------------------------------- the plant


def _plant_or_skip():
    pytest.importorskip("mujoco")
    from sim2real.sim.homing import mujoco_plant  # noqa: PLC0415

    if not mujoco_plant.available():
        pytest.skip("bam_ws's twin is not on disk")
    return mujoco_plant


def test_the_end_group_case_scales_only_the_twins_end_group_body():
    mujoco_plant = _plant_or_skip()
    cad = mujoco_plant.RigCache.get("B0").model
    heavy = mujoco_plant.RigCache.get("B0", mujoco_plant.END_GROUP_MASS_SCALE).model
    index = cad.body(mujoco_plant.END_GROUP_BODY).id
    assert mujoco_plant.END_GROUP_MASS_SCALE == pytest.approx(2.0628530325950996 / 1.6841719999999998)  # massid_real_093852's l2 group
    assert heavy.body_mass[index] == pytest.approx(cad.body_mass[index] * mujoco_plant.END_GROUP_MASS_SCALE)
    others = [b for b in range(cad.nbody) if b != index]
    assert all(heavy.body_mass[b] == cad.body_mass[b] for b in others)


def test_the_runaway_check_is_the_real_runners_ceiling_on_the_bus_drives():
    mujoco_plant = _plant_or_skip()
    from sim2real.sim.homing.real_plant import DRIVE_JOINTS, RUNAWAY_RAD_S  # noqa: PLC0415

    assert mujoco_plant.RUNAWAY_RAD_S == RUNAWAY_RAD_S == 1.5 and mujoco_plant.RUNAWAY_JOINTS == DRIVE_JOINTS == (J2, C1)


def _episode(row, ff=1.0):
    mujoco_plant = _plant_or_skip()
    from sim2real.sim.homing.bench import run_episode  # noqa: PLC0415
    from sim2real.sim.homing.gff_rung import real_lane_starts  # noqa: PLC0415
    from sim2real.sim.homing.real_bench import RealRow  # noqa: PLC0415

    prior = prior_for(FivebarGeometry())
    plant = mujoco_plant.MujocoRigPlant("B0", end_mass_scale=mujoco_plant.END_GROUP_MASS_SCALE, runaway_rad_s=mujoco_plant.RUNAWAY_RAD_S)
    episode = run_episode(row, plant, real_lane_starts()[0], prior, "mujoco · B0", procedure=RealRow(row, ff_scale=ff))
    return episode, plant


@pytest.mark.skipif(not SLOW, reason="a whole MuJoCo episode (~15 s); SIM2REAL_SLOW=1")
def test_red_the_pass5_unfed_hold_trips_the_runaway_check_with_the_heavier_end_group():
    episode, _ = _episode("single_touch")
    phase = episode.phases[0]
    assert phase.status == "tripped" and phase.message.startswith("runaway: J2"), phase.message
    zero = max(k for k, d in enumerate(phase.log["defines"]) if d)
    assert len(phase.log["t"]) - zero < 50, "the trip is within 0.5 s after the zero, as on the real arm (0.1-0.2 s)"


@pytest.mark.skipif(not SLOW, reason="two whole MuJoCo episodes (~40 s each); SIM2REAL_SLOW=1")
@pytest.mark.parametrize("ff", [0.75, 1.25])
def test_green_with_feed_forward_the_same_start_homes_without_a_trip_at_25_percent_comp_error(ff):
    from sim2real.sim.homing.mujoco_plant import RUNAWAY_RAD_S  # noqa: PLC0415

    episode, plant = _episode("single_touch+gff", ff)
    assert episode.record.finished, episode.record.outcome
    assert max(plant.peak_powered_rad_s.values()) < RUNAWAY_RAD_S
