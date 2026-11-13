"""Pass 7 of the homing bench (2026-11-13): the blind recovery fed so "any start" holds, the crank powered through single_touch's J2
seek, and three housekeeping fixes. Written before the code they test.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_pass7_1113.py

* recovery_ff (``recover_first(fed)+<row>``): recover_first's holds carry no feed-forward, and its re-hold after the first J2 seek ran away
  on the real arm (91-93 deg/s, every start) and on the MuJoCo plant with the end group +22 % (86-87 deg/s, bowl / flipped_crank, B0).
* c1_seek (``single_touch_c1seek``): single_touch+gff's limp crank swung at 87.7 deg/s in its J2 seek on the real arm.
* housekeeping: gff_rung stamps through provenance.code_sha; ``real_bench score --mujoco-json``; two_level_touch+gff's NOT_RUN reason
  no longer claims its first seek carries the upper stop's feed-forward (pass 6's rule leaves a seek from an unknown pose un-fed).

The plan tests use the home button's real comp (bam_ws twin) and skip without it; SIM2REAL_SLOW=1 adds the whole-episode red / green.
"""

from __future__ import annotations

import inspect
import math
import os

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from sim2real.sim.homing.geometry import C1, DEFAULT_ROOT, J1, J2  # noqa: E402

if not (DEFAULT_ROOT / "hardstops.json").is_file():
    pytest.skip("the v11 bundle is not on disk", allow_module_level=True)

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
FED = "recover_first(fed)+single_touch+gff"
UNFED = "recover_first+single_touch+gff"


@pytest.fixture(scope="module")
def comp():
    try:
        from sim2real.sim.homing.gravity_ff import default_comp

        return default_comp()
    except Exception as error:  # noqa: BLE001 - bam_ws twin absent
        pytest.skip(f"the home button's comp needs bam_ws: {error}")


@pytest.fixture(scope="module")
def prior():
    from sim2real.sim.homing.real_bench import load_prior

    return load_prior()[0]


def _plan(name, prior):
    from sim2real.sim.homing.real_bench import RealRow

    row = RealRow(name)
    return row, row.plan(prior, [])


def _step(sequence, name):
    return next(s for s in sequence.steps if s.name == name)


def _cmd(step, joint):
    return next(c for c in step.commands if c.joint == joint)


# ---------------------------------------------------------------------------------------------------------------- the limp crank's rest


def test_the_limp_crank_rests_where_the_twin_put_it(comp):
    from sim2real.sim.homing.recovery_ff import limp_rest

    # MuJoCo's recovery landed the limp crank at C1 151.94 deg with J2 stalled at 124.71 (pass 4, bowl, B0)
    rest = limp_rest(comp, {J2: math.radians(124.71)})
    assert rest is not None and abs(math.degrees(rest) - 151.94) < 1.0
    torque = comp.torque({J2: math.radians(124.71), C1: rest})
    assert abs(torque[C1]) < 1e-3
    up, down = (comp.torque({J2: math.radians(124.71), C1: rest + d})[C1] for d in (math.radians(2.0), math.radians(-2.0)))
    assert up > 0.0 > down, "a stable rest: the holding torque rises through zero"


# ---------------------------------------------------------------------------------------------------------------- the fed recovery


def test_red_the_unfed_recovery_holds_j2_at_its_stop_with_nothing(prior, comp):
    _, sequence = _plan(UNFED, prior)
    rehold = next(s for s in sequence.steps if s.name.startswith("re-hold") and s.name.endswith("J2 - 15 deg (lift L1 off), crank limp"))
    assert _cmd(rehold, J2).feedforward_effort == 0.0


def test_after_the_first_j2_stall_every_powered_hold_and_move_is_fed(prior, comp):
    row, sequence = _plan(FED, prior)
    names = [s.name for s in sequence.steps]
    after = set(names[names.index("recover: J2 + until it stalls, crank limp") + 1:])
    note = row.notes["recovery_ff"]
    assert [u for u in note["unfed_non_seek"] if u["step"] in after] == []
    assert len(note["filled_steps"]) >= 10


def test_the_recovery_holds_j2_with_the_limp_crank_torque(prior, comp):
    from sim2real.sim.homing.recovery_ff import limp_crank_torque

    _, sequence = _plan(FED, prior)
    stop = prior.stops.q_rad(J2, +1)
    rehold = next(s for s in sequence.steps if s.name.startswith("re-hold") and s.name.endswith("J2 - 15 deg (lift L1 off), crank limp"))
    assert _cmd(rehold, J2).feedforward_effort == pytest.approx(limp_crank_torque(comp, stop), rel=1e-6)
    lift = _step(sequence, "recover: J2 - 15 deg (lift L1 off), crank limp")
    expected = 0.5 * (limp_crank_torque(comp, stop) + limp_crank_torque(comp, stop - math.radians(15.0)))
    assert _cmd(lift, J2).feedforward_effort == pytest.approx(expected, rel=1e-6)
    off = _step(sequence, "recover: J2 5 deg off its stop, crank holds")
    assert _cmd(off, J2).feedforward_effort > 5.0 and _cmd(off, C1).feedforward_effort > 3.0  # the defined pose: the full comp


def test_the_procedures_first_holds_after_the_recovery_are_fed_too(prior, comp):
    _, sequence = _plan(FED, prior)
    assert _cmd(_step(sequence, "J1 holds"), J2).feedforward_effort > 3.0
    _, unfed = _plan(UNFED, prior)
    assert _cmd(_step(unfed, "J1 holds"), J2).feedforward_effort == 0.0


def test_the_fed_recovery_changes_no_cap_no_seek_no_condition_and_no_define(prior, comp):
    """Only feed-forwards change - and, where keep_c1_powered says so (its note), a limp crank becomes a hold (recovery_ff's docstring:
    a crank let go from its stop swung at 183 deg/s and dragged J2 past the ceiling on the smoke run, bowl / other, B0)."""
    from sim2real.sim.homing.recovery_ff import seek_side

    row, fed = _plan(FED, prior)
    _, unfed = _plan(UNFED, prior)
    kept = set(row.notes["c1_kept_powered_in"])
    assert kept, "the crank is kept powered somewhere behind the recovery"
    assert [s.name for s in fed.steps] == [s.name for s in unfed.steps]
    for a, b in zip(fed.steps, unfed.steps, strict=True):
        assert a.done_when == b.done_when and a.define_position == b.define_position and a.timeout == b.timeout
        for ca, cb in zip(a.commands, b.commands, strict=True):
            if a.name in kept and ca.joint == C1:
                assert cb.mode == "limp" and ca.mode == "hold", (a.name, ca, cb)
                continue
            assert (ca.joint, ca.mode, ca.max_effort, ca.position, ca.distance, ca.speed) == (
                cb.joint, cb.mode, cb.max_effort, cb.position, cb.distance, cb.speed)
            if abs(float(cb.feedforward_effort or 0.0)) > 1e-12:
                assert ca.feedforward_effort == cb.feedforward_effort, (a.name, ca)  # what gravity_ff fed stays as it fed it


def test_a_seek_after_a_fed_hold_starts_with_the_holds_gravity(prior, comp):
    """The second smoke run: 'recover: J2 + onto its stop' dropped the re-hold's 7.0 N.m at once and J2 fell at 87-88 deg/s."""
    _, sequence = _plan(FED, prior)
    rehold = next(s for s in sequence.steps if s.name.startswith("re-hold") and s.name.endswith("recover: J2 + onto its stop, crank limp"))
    seek = _step(sequence, "recover: J2 + onto its stop, crank limp")
    assert _cmd(rehold, J2).feedforward_effort > 6.0
    assert _cmd(seek, J2).feedforward_effort == pytest.approx(_cmd(rehold, J2).feedforward_effort, rel=1e-9)


def test_the_fed_recovery_never_lets_a_powered_crank_go_and_keeps_its_first_limp_crank(prior, comp):
    _, sequence = _plan(FED, prior)
    previous = None
    for step in sequence.steps:
        if previous is not None and _cmd(previous, C1).mode != "limp":
            assert _cmd(step, C1).mode != "limp", step.name
        previous = step
    assert _cmd(_step(sequence, "recover: J2 + until it stalls, crank limp"), C1).mode == "limp"


def test_a_c1_seek_ends_on_its_frame_stop_whatever_j2_is(prior, comp):
    """C1's CAD stops are frame stops (FivebarGeometry.stop(C1, +-1, q6) is 197.77 / -112.69 at every J2), and the twin's recovery C1 seek
    with J2 held at 78 deg stalled on its upper stop at 197.772 (pass 4)."""
    from sim2real.sim.homing.geometry import FivebarGeometry
    from sim2real.sim.homing.recovery_ff import end_pose

    geometry = FivebarGeometry()
    assert {round(math.degrees(geometry.stop(C1, +1, math.radians(q6))), 2) for q6 in (0, 60, 110, 125)} == {197.77}
    _, sequence = _plan(FED, prior)
    step = _step(sequence, "recover: C1 + until it stalls, J2 holds")
    end = end_pose(step, {J1: None, J2: math.radians(110.0), C1: math.radians(147.0)}, prior, comp, defined=set())
    assert end[C1] == pytest.approx(prior.stops.q_rad(C1, +1))


def test_before_the_first_j2_stall_nothing_is_fed(prior, comp):
    _, sequence = _plan(FED, prior)
    for step in sequence.steps:
        if step.name == "recover: J2 + until it stalls, crank limp":
            break
        assert all(abs(float(c.feedforward_effort or 0.0)) < 1e-12 for c in step.commands), step.name


def test_the_recovery_is_fed_in_cad_even_in_front_of_tview(prior, comp):
    """Smoke run 3: tview's crank frame (C1 41.08 deg off CAD) was applied to the recovery's CAD define and J2 ran away at ff +25 %."""
    _, single = _plan(FED, prior)
    _, tview = _plan("recover_first(fed)+tview_v2+gff", prior)
    for name in ("recover: J2 5 deg off its stop, crank holds", "recover: C1 + until the hub meets L1's plate, J2 pressed on its stop: define both positions"):
        a, b = _step(single, name), _step(tview, name)
        for joint in (J2, C1):
            assert _cmd(a, joint).feedforward_effort == pytest.approx(_cmd(b, joint).feedforward_effort, rel=1e-9), (name, joint)


def test_the_fed_rows_are_real_rows():
    from sim2real.sim.homing.real_bench import ROWS

    assert FED in ROWS


# ---------------------------------------------------------------------------------------------------------------- the crank seeking


def test_c1seek_powers_the_crank_through_j2s_seek(prior, comp):
    from sim2real.sim.homing.c1_seek import J2_SEEK

    _, sequence = _plan("single_touch_c1seek+gff", prior)
    seek = _step(sequence, J2_SEEK)
    assert _cmd(seek, C1).mode == "move_by" and float(_cmd(seek, C1).distance) > 0
    assert {type(c).__name__ for c in seek.done_when} == {"Stall"} and all(c.joint == J2 for c in seek.done_when)
    _, original = _plan("single_touch+gff", prior)
    tail = lambda seq: [s.name for s in seq.steps][[s.name for s in seq.steps].index("C1 seeks (J2 pushing)"):]  # noqa: E731
    assert tail(sequence) == tail(original), "from C1's seek on, single_touch's own steps"


def test_keep_c1_powered_never_drops_a_powered_crank(prior, comp):
    _, sequence = _plan("recover_first(fed)+single_touch_c1seek+gff", prior)
    previous = None
    for step in sequence.steps:
        if previous is not None and _cmd(previous, C1).mode != "limp":
            assert _cmd(step, C1).mode != "limp", step.name
        previous = step


# ---------------------------------------------------------------------------------------------------------------- housekeeping


def test_gff_rung_stamps_through_provenance_code_sha():
    from sim2real import provenance
    from sim2real.sim.homing import gff_rung

    assert getattr(gff_rung, "code_sha", None) is provenance.code_sha
    source = inspect.getsource(gff_rung.run_bench)
    assert "code_sha(" in source and "git_sha(" not in source


def test_score_takes_the_mujoco_json_on_the_command_line(monkeypatch, tmp_path):
    from sim2real.sim.homing import real_bench

    seen = {}
    monkeypatch.setattr(real_bench, "score", lambda runs, **kw: seen.update(kw) or {"verdicts": {}})
    real_bench.main(["score", str(tmp_path), "--mujoco-json", str(tmp_path / "m.json")])
    assert seen["mujoco_json"] == tmp_path / "m.json"


def test_two_level_touch_gff_reason_matches_its_plan(prior, comp):
    from sim2real.sim.homing.real_bench import NOT_RUN, RealRow

    reason = NOT_RUN["two_level_touch+gff"]
    assert "carries the gravity feed-forward planned for the upper stop" not in reason
    row = RealRow("two_level_touch+gff")
    sequence = row.plan(prior, [])
    first_seek = next(s for s in sequence.steps if any(c.mode == "move_by" and c.joint == J2 for c in s.commands)
                      and not s.name.startswith("re-hold"))
    assert _cmd(first_seek, J2).feedforward_effort == 0.0, "its first seek runs un-fed (pass 6's rule)"


# ---------------------------------------------------------------------------------------------------------------- whole episodes


def _episode(row, start_name, ff=1.0):
    from sim2real.sim.homing import mujoco_plant
    from sim2real.sim.homing.bench import named_rests, prior_for, run_episode
    from sim2real.sim.homing.geometry import FivebarGeometry
    from sim2real.sim.homing.real_bench import RealRow

    geometry = FivebarGeometry()
    prior = prior_for(geometry)
    start = next(s for s in named_rests(geometry, prior) if s.name == start_name)
    plant = mujoco_plant.MujocoRigPlant("B0", end_mass_scale=mujoco_plant.END_GROUP_MASS_SCALE, runaway_rad_s=mujoco_plant.RUNAWAY_RAD_S)
    return run_episode(row, plant, start, prior, "mujoco · B0", procedure=RealRow(row, ff_scale=ff)), plant


@pytest.mark.skipif(not SLOW, reason="a MuJoCo episode to its trip (~15 s); SIM2REAL_SLOW=1")
def test_red_the_unfed_recovery_trips_lifting_l1_off_its_stop():
    episode, _ = _episode(UNFED, "bowl")
    phase = episode.phases[0]
    assert phase.status == "tripped" and "J2 - 15 deg" in phase.message, phase.message


@pytest.mark.skipif(not SLOW, reason="two whole MuJoCo episodes (~90 s each); SIM2REAL_SLOW=1")
@pytest.mark.parametrize("start", ["bowl", "flipped_crank"])
def test_green_the_fed_recovery_homes_the_same_starts_without_a_trip(start):
    from sim2real.sim.homing.mujoco_plant import RUNAWAY_RAD_S

    episode, plant = _episode(FED, start)
    assert episode.record.finished, episode.record.outcome
    assert max(plant.peak_powered_rad_s.values()) < RUNAWAY_RAD_S
