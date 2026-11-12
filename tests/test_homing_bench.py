"""The kinematic homing rung on the v11 five-bar (sim2real.sim.homing): the plant is exact, the sequences are robot_msgs data, and the
gates can fail.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_homing_bench.py

Needs the cad2robot bundle 8957130 on disk (~/.cache/cad2robot-build/bundles, or SIM2REAL_HOMING_BUNDLE); skipped without it.
Hidden backlash: J1 3.5' (0.058 deg), J2 2.5' (0.042 deg), C1 4.0' (0.067 deg); B2 adds the AD064's 13 N.m/arcmin mesh.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from robot_models.homing.metrics import EpisodeRecord, reliable, scorecard  # noqa: E402
from robot_msgs.control import JointCommandSequence  # noqa: E402

from sim2real.sim.homing.geometry import C1, DEFAULT_ROOT, DRIVES, J1, J2, FivebarGeometry  # noqa: E402
from sim2real.sim.homing.plant import ARCMIN, KinematicStopPlant, Start, hidden_backlash  # noqa: E402

if not (DEFAULT_ROOT / "hardstops.json").is_file():
    pytest.skip(f"cad2robot bundle not on disk: {DEFAULT_ROOT}", allow_module_level=True)

from sim2real.sim.homing import procedures  # noqa: E402
from sim2real.sim.homing.bench import calibrate, named_rests, prior_for, run_episode, run_phase  # noqa: E402

GATE_DEG = 0.01
HIDDEN_DEG = {J1: 3.5 / 60.0, J2: 2.5 / 60.0, C1: 4.0 / 60.0}


@pytest.fixture(scope="module")
def geometry():
    return FivebarGeometry()


@pytest.fixture(scope="module")
def rests(geometry):
    return {start.name: start for start in named_rests(geometry, prior_for(geometry))}


@pytest.fixture(scope="module")
def tables(geometry, rests):
    return {model: calibrate(geometry, model, rests["home"])[0] for model in ("B0", "B1", "B2")}


def _episode(geometry, name, model, start, table=None):
    plant = KinematicStopPlant(geometry, hidden_backlash(model))
    return run_episode(name, plant, start, prior_for(geometry, table), f"kinematic · {model}"), plant


# ---------------------------------------------------------------------------------------------------------------- the plant


def test_exact_stops_are_the_stop_cores(geometry):
    # robot_models' ruler values (bundle 8957130, coal first contact): the plant stops exactly there
    assert math.degrees(geometry.stop(J2, +1)) == pytest.approx(124.9986, abs=2e-4)
    assert math.degrees(geometry.stop(J2, -1)) == pytest.approx(-90.0291, abs=2e-4)
    assert math.degrees(geometry.stop(C1, +1, 0.0)) == pytest.approx(197.7708, abs=2e-4)
    assert math.degrees(geometry.stop(J1, +1)) == pytest.approx(89.9732, abs=2e-4)
    # C1's stop is a spacer on L1: computed at J2's angle, it moves under 0.005 deg over J2's whole range
    at = [math.degrees(geometry.stop(C1, +1, math.radians(q))) for q in (-90.0, 0.0, 60.0, 124.9)]
    assert max(at) - min(at) < 0.005


def test_a_seek_stops_on_the_exact_stop_and_presses_with_the_board_loop(geometry):
    plant = KinematicStopPlant(geometry, hidden_backlash("B2"))
    # J2 at 100 deg with the crank at 190: free all the way to J2's stop on the exporter's map
    plant.reset(Start("below the J2 stop", {J1: 0.0, J2: math.radians(100.0), C1: math.radians(190.0)}, {J2: 0.3}, {J2: 1.1}))
    from robot_msgs.control import JointCommand, JointCommandStep, Stall

    sequence = JointCommandSequence(joint_names=DRIVES, steps=(JointCommandStep(
        name="J2 seeks", commands=(JointCommand.hold(J1, max_effort=7.0), JointCommand.move_by(J2, 4.0, speed=0.63, max_effort=10.0),
                                   JointCommand.hold(C1, max_effort=7.0)), done_when=(Stall(joint=J2),), timeout=20.0),))
    phase = run_phase(plant, sequence)
    assert phase.status == "done"
    truth = plant.truth()
    assert truth["link_rad"][J2] == pytest.approx(geometry.stop(J2, +1), abs=1e-12)  # rigid: exactly on the stop
    torque = plant.log["effort"][-1][DRIVES.index(J2)]  # the plant after its last tick (the phase log holds what was seen before it)
    gap = 2.5 * ARCMIN
    compliance = hidden_backlash("B2")[J2].compliance_rad_per_nm
    # the motor sits past the link by half the gap plus the give at the torque the board is pressing with
    assert truth["motor_rad"][J2] - truth["link_rad"][J2] == pytest.approx(gap / 2 + compliance * torque, abs=1e-12)
    assert truth["touching"][J2] == "upper"


def test_a_start_off_the_free_map_is_refused(geometry):
    plant = KinematicStopPlant(geometry, hidden_backlash("B0"))
    with pytest.raises(ValueError, match="not a free pose"):
        plant.reset(Start("in the tube", {J1: 0.0, J2: math.radians(90.0), C1: math.radians(60.0)}))


# ---------------------------------------------------------------------------------------------------------------- the sequences


@pytest.mark.parametrize("name", sorted(procedures.PROCEDURES))
def test_every_procedure_is_one_robot_msgs_sequence(geometry, name):
    sequence = procedures.PROCEDURES[name]().plan(prior_for(geometry), [])
    assert isinstance(sequence, JointCommandSequence)
    assert JointCommandSequence.from_dict(sequence.to_dict()).to_dict() == sequence.to_dict()


# ---------------------------------------------------------------------------------------------------------------- tview v2


@pytest.mark.parametrize("model", ["B0", "B1", "B2"])
def test_tview_v2_runs_unchanged_and_its_zero_carries_the_backlash(geometry, rests, model):
    episode, plant = _episode(geometry, "tview_v2", model, rests["bowl"])
    record = episode.record
    assert record.finished and reliable(record), record.outcome
    errors = {j.joint: j.zero_error_deg for j in record.joints}
    # B0: only the typed numbers vs the found stops (J1's 0.25 rev = 90.000 against the 89.973 the meshes give)
    if model == "B0":
        assert errors[J1] == pytest.approx(90.0 - math.degrees(geometry.stop(J1, +1)), abs=1e-6)
        assert abs(errors[J2]) < GATE_DEG and abs(errors[C1]) < GATE_DEG
    else:
        # no correction: the stall reads half the gap (and the give) past the link, so J2 and C1 miss by about g/2
        for joint in (J2, C1):
            assert errors[joint] < -(HIDDEN_DEG[joint] / 2 - 0.005)
    assert max(abs(e) for e in errors.values()) > GATE_DEG  # tview v2 fails the 0.01 deg gate on every model


def test_tview_from_the_flipped_crank_never_reaches_its_stops(geometry, rests):
    episode, _ = _episode(geometry, "tview_v2", "B0", rests["flipped_crank"])
    assert not reliable(episode.record)


# ---------------------------------------------------------------------------------------------------------------- the leaderboard rows


@pytest.mark.parametrize("model", ["B0", "B1", "B2"])
def test_press_reverse_passes_the_zero_and_backlash_gates(geometry, rests, model):
    episode, _ = _episode(geometry, "press_reverse", model, rests["bowl"])
    card = scorecard([episode.record], gate_deg=GATE_DEG)
    assert card["zero_gate_pass"] is True, card
    assert card["backlash_gate_pass"] is True, card
    assert card["backlash_observable_pct"] == 100.0


def test_the_zero_gate_goes_red_without_the_gap(geometry, rests, tables):
    """Mutation: two_level_touch on a B1 plant with no stored table (a first boot) must fail the 0.01 deg gate; with the table it
    passes. (press_reverse is immune by construction: its two-sided average cancels the gap.)"""
    without, _ = _episode(geometry, "two_level_touch", "B1", rests["bowl"], None)
    assert scorecard([without.record], gate_deg=GATE_DEG)["zero_gate_pass"] is False
    with_table, _ = _episode(geometry, "two_level_touch", "B1", rests["bowl"], tables["B1"])
    assert scorecard([with_table.record], gate_deg=GATE_DEG)["zero_gate_pass"] is True


def test_the_stall_check_goes_red_on_a_contact_that_is_not_the_stop(geometry, rests):
    """single_touch seeks J2 alone; from the export pose L1's tube meets the coupler first and J2 stalls there, 100 deg short:
    finished, but not reliable."""
    episode, _ = _episode(geometry, "single_touch", "B0", rests["export_pose"])
    record = episode.record
    assert record.finished and not reliable(record)
    j2 = next(s for s in record.stalls if s.joint == J2)
    assert j2.cad_deg - j2.link_deg > 10.0


def test_a_rigid_stop_leaves_bam_homings_stiffness_unresolved(geometry, rests):
    episode, _ = _episode(geometry, "repeat_checked_seek", "B1", rests["bowl"])
    assert episode.record.outcome.startswith("refused") and "stiffness unresolved" in episode.record.outcome


@pytest.mark.parametrize("name", ["single_touch", "two_level_touch"])
def test_boot_procedures_with_the_stored_table_pass_and_report_the_gap_as_stored(geometry, rests, tables, name):
    episode, _ = _episode(geometry, name, "B2", rests["bowl"], tables["B2"])
    card = scorecard([episode.record], gate_deg=GATE_DEG)
    assert card["zero_gate_pass"] is True, card
    assert card["backlash_error_deg"] is None  # read from the table, not identified: '-'


def test_calibration_identifies_every_gap_within_the_gate(tables):
    from robot_models.homing.metrics import backlash_gate_deg

    for joint, truth in HIDDEN_DEG.items():
        entry = tables["B2"].get(joint)
        assert entry.gap_observable and entry.compliance_observable
        assert abs(math.degrees(entry.model.gap_rad) - truth) <= backlash_gate_deg(truth)
        assert entry.model.compliance_rad_per_nm == pytest.approx(hidden_backlash("B2")[joint].compliance_rad_per_nm, rel=1e-6)


def test_records_round_trip(geometry, rests):
    episode, _ = _episode(geometry, "two_level_touch", "B1", rests["home"])
    assert EpisodeRecord.from_dict(episode.record.to_dict()).to_dict() == episode.record.to_dict()


# ---------------------------------------------------------------------------------------------------------------- the leaderboard


def test_leaderboard_records_carry_the_four_config_keys_and_the_scorecard():
    import json
    from pathlib import Path

    from sim2real.tracking import homing as board

    path = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "homing_fivebar_kinematic_2026-11-12.json"
    if not path.is_file():
        pytest.skip("no committed bench results yet")
    results = json.loads(path.read_text())
    batch = board.records(results)
    assert len(batch) == len(results["models"]) * len(results["procedures"])
    for record in batch:
        config = record["config"]
        assert {"rung", "backlash_model", "procedure", "bundle_sha"} <= set(config)
        card = results["scorecards"][config["backlash_model"]][config["procedure"]]
        assert record["summary"]["episodes"] == card["episodes"] == len(results["starts"])
        assert len(record["tables"]["starts"]) == len(results["starts"])
    assert len({r["id"] for r in batch}) == len(batch)
    assert board.records(results)[0]["id"] == batch[0]["id"]  # the same numbers map to the same runs: re-logging is idempotent
