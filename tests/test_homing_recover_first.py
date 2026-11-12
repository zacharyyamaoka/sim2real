"""recover_first on the kinematic homing rung: bam_fivebar_recovery's blind recovery as a prefix of any procedure's JointCommandSequence.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_homing_recover_first.py

The prefix is the routine's own bytes (data/fivebar_blind_recovery_v11.json, exported by recovery_export.py from bam_fivebar_recovery);
these tests pin that it is carried unchanged, that it does not cost a procedure its zero, and (strict xfail) the rung's gate from the
flipped crank, which the kinematic rung cannot pass: it has no gravity, so nothing can carry the loop through the toggle between its two
assemblies (the decision report: "kinematic proves geometry, MuJoCo proves dynamics").
"""

from __future__ import annotations

import json
import math

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from robot_msgs.control import JointCommandSequence  # noqa: E402

from sim2real.sim.homing.geometry import C1, DEFAULT_ROOT, DRIVES, J1, J2, FivebarGeometry  # noqa: E402

if not (DEFAULT_ROOT / "hardstops.json").is_file():
    pytest.skip(f"cad2robot bundle not on disk: {DEFAULT_ROOT}", allow_module_level=True)

from sim2real.sim.homing import recover  # noqa: E402
from sim2real.sim.homing.bench import make_procedure, named_rests, prior_for, run_episode  # noqa: E402
from sim2real.sim.homing.plant import KinematicStopPlant, hidden_backlash  # noqa: E402
from sim2real.sim.homing.procedures import PROCEDURES  # noqa: E402


@pytest.fixture(scope="module")
def geometry():
    return FivebarGeometry()


@pytest.fixture(scope="module")
def rests(geometry):
    return {start.name: start for start in named_rests(geometry, prior_for(geometry))}


def test_the_prefix_is_the_exported_blind_recovery_readdressed(geometry):
    payload = json.loads(recover.RECOVERY_JSON.read_text())
    exported = payload["sequence"]["steps"]
    steps = recover.recovery_steps(recover.load_recovery()[0])
    assert len(steps) == len(exported) == 7
    for step, raw in zip(steps, exported, strict=True):
        assert step.name == recover.PREFIX + raw["name"]
        assert step.timeout == raw["timeout"]
        by_joint = {c.joint: c for c in step.commands}
        assert set(by_joint) == set(DRIVES)
        assert by_joint[J1].mode == "hold"  # J1 holds through the prefix
        for command in raw["commands"]:
            mine = by_joint[recover.RENAME[command["joint"]]]
            for key in ("mode", "position", "distance", "speed", "max_effort", "feedforward_effort"):
                assert getattr(mine, key) == command[key], (step.name, key)
        assert dict(step.define_position) == {recover.RENAME[j]: v for j, v in raw["define_position"].items()}
    # its references are the v11 CAD's exact stops (URDF frame), not the July bench's 114.4 / -38.61 deg Craig
    defines = dict(steps[5].define_position)
    assert math.degrees(defines[J2]) == pytest.approx(math.degrees(geometry.cad.q_rad(J2, +1)), abs=1e-3)
    assert math.degrees(defines[C1]) == pytest.approx(math.degrees(geometry.stop(C1, +1, geometry.cad.q_rad(J2, +1))), abs=1e-3)


@pytest.mark.parametrize("name", list(PROCEDURES))
def test_recover_first_is_one_sequence_the_prefix_then_the_procedure(geometry, name):
    prior = prior_for(geometry)
    wrapped = make_procedure(recover.RECOVER_PREFIX_NAME + name)
    plan = wrapped.plan(prior, [])
    inner = PROCEDURES[name]().plan(prior, [])
    assert isinstance(plan, JointCommandSequence) and plan.joint_names == DRIVES
    assert [s.name for s in plan.steps[7:]] == [s.name for s in inner.steps]
    assert plan.steps[7:] == inner.steps
    assert all(s.name.startswith(recover.PREFIX) for s in plan.steps[:7])
    assert wrapped.plan(prior, ["a phase"]) is None
    assert JointCommandSequence.from_dict(plan.to_dict()) == plan


def test_duplicate_step_names_are_refused():
    inner = PROCEDURES["press_reverse"]().plan(prior_for(FivebarGeometry()), [])
    with pytest.raises(ValueError, match="unique step names"):
        recover.with_prefix(inner.steps[:1], inner)


@pytest.mark.parametrize("name", ["press_reverse", "tview_v2"])
def test_the_prefix_costs_no_zero_from_a_working_branch_rest(geometry, rests, name):
    # the same zero with and without the recovery in front, from the real arm's rest: its defines are taken back out. WHY 1e-6 deg and
    # not exact: tview's zero is its set-output on the stall tick, and the seek starts from another pose after the prefix (6e-8 deg
    # measured); press_reverse's fit agrees to 1e-12. Either is 10^4 under the rung's 0.01 deg gate.
    plain = run_episode(name, KinematicStopPlant(geometry, hidden_backlash("B2")), rests["bowl"], prior_for(geometry), "k")
    first = run_episode(recover.RECOVER_PREFIX_NAME + name, KinematicStopPlant(geometry, hidden_backlash("B2")), rests["bowl"],
                        prior_for(geometry), "k")
    assert plain.record.finished and first.record.finished
    for a, b in zip(plain.record.joints, first.record.joints, strict=True):
        assert b.zero_error_deg == pytest.approx(a.zero_error_deg, abs=1e-6)
    assert first.record.time_s > plain.record.time_s  # the time to home includes the recovery


@pytest.mark.xfail(strict=True, reason="kinematic rung has no gravity: the loop cannot pass the toggle from the mirrored assembly, so "
                   "the recovery's stalls land on mirror contacts and its step 7 times out (2026-11-12 re-score: 98.6 %, flipped_crank 0/15)")
def test_recover_first_homes_from_the_flipped_crank(geometry, rests):
    episode = run_episode(recover.RECOVER_PREFIX_NAME + "press_reverse", KinematicStopPlant(geometry, hidden_backlash("B2")),
                          rests["flipped_crank"], prior_for(geometry), "k")
    assert episode.record.finished, episode.record.outcome
