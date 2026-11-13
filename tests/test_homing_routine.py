"""The full-arm homing routine's ruler (sim2real.sim.homing.routine_ruler, frozen 2026-11-13 before any routine ran) and the routine
itself (fullarm_routine). Sim only.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_routine.py

The ruler tests are pure (no simulator). The episode tests need bam_ws's twin and the bam_fb_v2 bundle and skip without them.
"""

from __future__ import annotations

import json
import math
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from sim2real.sim.homing import routine_ruler as ruler

BAM_RACK_TWIN_PY = Path("/home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python")


def report(**overrides) -> dict:
    """A finished, homed episode on the nominal environment; ``overrides`` replace fields."""
    base = {"procedure": "r", "environment": "nominal", "start": "s", "finished": True, "outcome": "done", "time_s": 50.0,
            "zero_error_deg": {"J1": None, "J2": 0.01, "C1": -0.02, "W1": 0.003, "W2": 0.0, "W3": -0.004, "CLAW": 0.001},
            "gap_identified_deg": {r: None for r in ("J1", "J2", "C1", "W1", "W2", "W3", "CLAW")},
            "gap_truth_deg": {r: 0.0 for r in ("J1", "J2", "C1", "W1", "W2", "W3", "CLAW")},
            "stalls": [{"joint": "revolute_11", "side": 1, "link_deg": 169.86, "cad_deg": 169.85}],
            "belt_after_liftoff_ticks": 0, "belt_start_bodies": ["hard_stop_3"], "self_contact_ticks": 0,
            "peak_speed_deg_s": {"J1": 0.0, "J2": 50.0, "W1": 40.0}, "speed_ceiling_deg_s": {"J1": 85.9, "J2": 85.9, "W1": 85.9}}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------------------------------------------- the grid


def test_the_grid_is_144_cells_over_all_seven_joints_with_every_level_equally_often():
    cells = ruler.grid_cells()
    assert len(cells) == 144
    assert len({c["name"] for c in cells}) == 144
    assert cells == ruler.grid_cells()  # deterministic
    assert Counter(c["family"] for c in cells) == {level: 36 for level in ruler.FIVEBAR_LEVELS}
    assert Counter(c["wrist_deg"][2] for c in cells) == {v: 48 for v in ruler.W3_LEVELS_DEG}
    assert Counter(c["claw_deg"] for c in cells) == {v: 48 for v in ruler.CLAW_LEVELS_DEG}
    assert Counter(c["j1_deg"] for c in cells) == {v: 72 for v in ruler.J1_LEVELS_DEG}
    # the forearm band (|W2| 150) and both W1 extremes are on the grid
    assert any(abs(c["wrist_deg"][1]) == 150.0 and abs(c["wrist_deg"][0]) == 150.0 for c in cells)


def test_no_wrist_level_is_tied_to_one_w3_claw_or_j1_level():
    cells = ruler.grid_cells()
    for axis in (0, 1):
        for value in ruler.WRIST_LEVELS_DEG:
            row = [c for c in cells if c["wrist_deg"][axis] == value]
            assert len({c["wrist_deg"][2] for c in row}) == 3
            assert len({c["claw_deg"] for c in row}) == 3
            assert len({c["j1_deg"] for c in row}) == 2


def test_the_subset_and_the_tuning_starts():
    assert len(ruler.subset_cells()) == 24
    names = {c["name"] for c in ruler.grid_cells()}
    assert not names & {c["name"] for c in ruler.tuning_cells()}


@pytest.mark.skipif(not BAM_RACK_TWIN_PY.exists(), reason="bam_rack_twin's venv is not here")
def test_the_fivebar_levels_are_what_bam_rack_twin_says_today():
    """READY is full_arm.ready_motors; PICK / LIFT / UP are tool_ik of their TCPs (the ruler's comments)."""
    script = """
import json, math
from bam_rack_twin.hardware.full_arm import ready_motors, full_arm_cell, full_arm_tool
from bam_rack_twin.hardware.fivebar_run import bench_real
from bam_fivebar.kinematics import inverse_pose, tool_ik
b = bench_real(); cell = full_arm_cell('cap', 0); tool = full_arm_tool(0)
out = {'READY': [math.degrees(v) for v in ready_motors(b, cell, tool)]}
for name, tcp in (('PICK', (0.434, 0.575)), ('LIFT', (0.434, 0.455)), ('UP', (0.30, 0.30))):
    p = inverse_pose(b, *tool_ik(b, *tool.j4_of(tcp)))
    out[name] = [math.degrees(p.j2), math.degrees(p.c1)]
print(json.dumps(out))
"""
    done = subprocess.run(["env", "-u", "VIRTUAL_ENV", str(BAM_RACK_TWIN_PY), "-c", script], capture_output=True, text=True, timeout=300,
                          cwd=str(BAM_RACK_TWIN_PY.parents[2]))
    if done.returncode != 0:
        pytest.skip(f"bam_rack_twin did not import: {done.stderr[-300:]}")
    found = json.loads(done.stdout.strip().splitlines()[-1])
    for level, (j2, c1) in ruler.FIVEBAR_LEVELS.items():
        assert found[level][0] == pytest.approx(j2, abs=0.01)
        assert found[level][1] == pytest.approx(c1, abs=0.01)


# ---------------------------------------------------------------------------------------------------------------- one outcome per episode


def test_a_zero_past_one_degree_is_a_silent_wrong_never_an_inaccuracy():
    assert ruler.outcome_class(report()) == "homed"
    wrong = report(zero_error_deg={**report()["zero_error_deg"], "W1": 1.5})
    assert ruler.outcome_class(wrong) == "silent_wrong"
    rotor_turn = report(zero_error_deg={**report()["zero_error_deg"], "W3": -36.0})
    assert ruler.outcome_class(rotor_turn) == "silent_wrong"


def test_a_stall_off_its_cad_stop_is_a_silent_wrong_even_when_the_zero_looks_fine():
    off = report(stalls=[{"joint": "revolute_14", "side": -1, "link_deg": -166.5, "cad_deg": -169.85}])
    assert ruler.outcome_class(off) == "silent_wrong"


def test_a_claimed_home_with_a_scored_joint_unzeroed_is_a_silent_wrong():
    assert ruler.outcome_class(report(zero_error_deg={**report()["zero_error_deg"], "CLAW": None})) == "silent_wrong"


def test_inside_one_degree_but_past_the_gate_is_inaccurate():
    assert ruler.outcome_class(report(zero_error_deg={**report()["zero_error_deg"], "W2": 0.49})) == "inaccurate"
    assert ruler.outcome_class(report(zero_error_deg={**report()["zero_error_deg"], "W2": 0.1})) == "homed"


def test_refused_tripped_timeout_and_infeasible():
    assert ruler.outcome_class(report(finished=False, outcome="refused: rotor-phase witness")) == "refused"
    assert ruler.outcome_class(report(finished=False, outcome="tripped: runaway: J2 at 90 deg/s")) == "tripped"
    assert ruler.outcome_class(report(finished=False, outcome="timeout: step 'W1 seeks'")) == "timeout"
    assert ruler.outcome_class({"refused_start": "through the belt"}) == "infeasible"


def test_coverage_counts_homed_and_clean_over_feasible_starts_only():
    rows = [report(), report(belt_after_liftoff_ticks=3), report(zero_error_deg={**report()["zero_error_deg"], "W1": 0.5}),
            report(finished=False, outcome="refused: witness"), {"refused_start": "self-contact", "procedure": "r", "environment": "nominal"}]
    card = ruler.card(rows)
    assert card["feasible"] == 4
    assert card["coverage_pct"] == 25.0  # one of four: the belt-touching home is not clean, the 0.5 deg one inaccurate
    assert card["homed_pct"] == 50.0
    assert card["outcomes"]["infeasible"] == 1 and card["belt_after_liftoff"] == 1


def test_repeatability_is_the_signed_spread_and_excludes_wrong_stops():
    rows = [report(zero_error_deg={**report()["zero_error_deg"], "W1": v}) for v in (0.01, -0.01, 0.004)]
    rows.append(report(zero_error_deg={**report()["zero_error_deg"], "W1": 55.0}))  # a wrong stop: its own outcome, not a spread
    card = ruler.card(rows)
    assert card["repeatability_deg_by_joint"]["W1"] == pytest.approx(0.02)
    assert card["silent_wrong"] == 1


def test_backlash_is_identified_only_when_every_wrist_gap_is_reported():
    gaps = {"J1": None, "J2": None, "C1": None, "W1": 0.25, "W2": 0.3, "W3": 0.2, "CLAW": None}
    truth = {"J1": 0.0, "J2": 0.2, "C1": 0.2, "W1": 0.25, "W2": 0.3, "W3": 0.2, "CLAW": 0.0}
    one = report(gap_identified_deg=gaps, gap_truth_deg=truth)
    two = report(gap_identified_deg={**gaps, "W3": None}, gap_truth_deg=truth)
    card = ruler.card([one, two])
    assert card["backlash_identified_pct"] == 50.0
    assert card["backlash_error_p95_arcmin"] == pytest.approx(0.0)
    assert card["backlash_within_gate_pct"] == 100.0


def test_the_verdict_holds_every_environment_to_ninety_and_nominal_to_ninety_five():
    card = ruler.card([report() for _ in range(9)] + [report(finished=False, outcome="refused: witness")])
    assert card["coverage_pct"] == 90.0
    assert ruler.verdict(card, "nominal")["coverage_pct"] is False
    assert ruler.verdict(card, "B2")["coverage_pct"] is True
    assert ruler.verdict(card, "B2")["silent_wrong"] is True


def test_p95_is_a_value_an_episode_produced():
    assert ruler._p95([1.0, 2.0, 3.0]) == 3.0
    assert ruler._p95(list(range(1, 101))) == 95


# ---------------------------------------------------------------------------------------------------------------- the belt in the twin

from sim2real.sim.homing import fullarm_home as fh  # noqa: E402
from sim2real.sim.homing.mujoco_plant import available as twin_available  # noqa: E402

needs_twin = pytest.mark.skipif(not (twin_available() and fh.CAD_EXPORTER.is_dir()), reason="bam_ws's twin or the cad-exporter clone is not here")


@needs_twin
def test_the_belt_is_a_contact_and_the_five_bars_home_is_through_it_with_the_claw_on():
    """bam_rack_twin full_arm: at the five-bar's home (the gravity bowl) the claw's tips sit ~101 mm into the belt - the twin refuses it."""
    from sim2real.sim.homing.fullarm_plant import ArmStart, FullArmHomingPlant, StartRefused

    plant = FullArmHomingPlant("B0", belt_top_m=0.0, settle_all=True)
    with pytest.raises(StartRefused, match="into the belt"):
        plant.place(ArmStart("bowl, wrist 0", 91.01, -126.438, (0.0, 0.0, 0.0), 30.0))
    without = FullArmHomingPlant("B0")  # the PEP 0047 twin: no belt, so the same pose places
    without.place(ArmStart("bowl, wrist 0", 91.01, -126.438, (0.0, 0.0, 0.0), 30.0))


@needs_twin
def test_power_lost_at_ready_lands_the_claw_on_the_belt_and_it_stays_there():
    from sim2real.sim.homing.fullarm_plant import BELT_STIFF_SOLREF, ArmStart, FullArmHomingPlant

    plant = FullArmHomingPlant("B0", belt_top_m=0.0, settle_all=True, belt_solref=BELT_STIFF_SOLREF)
    plant.reset(ArmStart("READY TD4", *ruler.FIVEBAR_LEVELS["READY"], (1.17, 90.0, 0.0), 30.0))
    assert plant.start_belt, "the limp arm should come to rest on the belt"
    assert plant.settle_waited_s < 5.0, "and stay put (no contact creep on the stiff belt)"
    assert max(abs(v) for v in plant.sim.data.qvel) < 0.02


@needs_twin
def test_on_the_default_soft_belt_the_limp_arm_creeps_and_never_settles():
    """The WHY of ``belt_solref``: MuJoCo's default 0.02 s contact lets the arm creep along the belt (~0.6 deg/s), so a whole-arm settle
    runs out its 10 s; the stiff belt holds it (the test above)."""
    from sim2real.sim.homing.fullarm_plant import ArmStart, FullArmHomingPlant

    plant = FullArmHomingPlant("B0", belt_top_m=0.0, settle_all=True)
    plant.reset(ArmStart("READY TD4", *ruler.FIVEBAR_LEVELS["READY"], (1.17, 90.0, 0.0), 30.0))
    assert plant.start_belt
    assert plant.settle_waited_s >= 9.9


@needs_twin
def test_two_plants_on_one_cached_rig_each_get_their_own_contacts_back():
    """The model is shared per process: a plant that stiffens the belt or the stop pairs must not leave them stiff for the next plant."""
    from sim2real.sim.homing.fullarm_plant import BELT, BELT_STIFF_SOLREF, ArmStart, FullArmHomingPlant

    start = ArmStart("READY TD4", *ruler.FIVEBAR_LEVELS["READY"], (1.17, 90.0, 0.0), 30.0)
    stiff = FullArmHomingPlant("B0", belt_top_m=0.0, belt_solref=BELT_STIFF_SOLREF, contact_timeconst_s=0.01)
    stiff.reset(start)
    soft = FullArmHomingPlant("B0", belt_top_m=0.0)
    soft.reset(start)
    model = soft.rig.model
    assert tuple(model.geom_solref[model.geom(BELT).id]) != BELT_STIFF_SOLREF
    assert float(model.pair_solref[0, 0]) != 0.01
