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
    subset = ruler.subset_cells()
    assert len(subset) == 24
    # amendment 3: every W1 and every W2 level in each pose's subset - "every 6th cell" had been W2 -150 only
    for level in ruler.FIVEBAR_LEVELS:
        mine = [c for c in subset if c["family"] == level]
        assert sorted(c["cell"]["i"] for c in mine) == list(range(6)) and sorted(c["cell"]["j"] for c in mine) == list(range(6))
    assert {c["wrist_deg"][1] for c in ruler.folded_subset_cells()} == {-150.0}
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
    # amendment 4: the controller's own words for a step that never finished
    assert ruler.outcome_class(report(finished=False, outcome="aborted: step 'W1 walks across' was not done within 40.0 s")) == "timeout"
    assert ruler.outcome_class(report(finished=False, outcome="aborted: bench limit 400.0 s")) == "timeout"
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


# ---------------------------------------------------------------------------------------------------------------- the routine's plan

import os  # noqa: E402

RECOMMENDED_ROWS = ("park_first+witness @ READY", "multi x2 (3D-printer) @ READY", "press_reverse (backlash every home) @ READY",
                    "zach_v1 @ READY", "zach_v1+J1 @ READY")
slow = pytest.mark.skipif(not os.environ.get("SIM2REAL_SLOW"), reason="episode tests run with SIM2REAL_SLOW=1 (~2-5 min each)")


@pytest.fixture(scope="module")
def plans(tmp_path_factory):
    """Each row planned once, out of process (routine_check.preplan_file: the comp's model never loads in the test process)."""
    if not (twin_available() and fh.CAD_EXPORTER.is_dir()):
        pytest.skip("bam_ws's twin or the cad-exporter clone is not here")
    from sim2real.sim.homing import routine_check as rc

    return rc.preplan_file(RECOMMENDED_ROWS, tmp_path_factory.mktemp("plans") / "plans.pkl")


def _moving(command) -> bool:
    """A command that moves its joint (not a hold, not limp, not a 1 urad re-capture)."""
    if command.mode in ("hold", "limp", "stop", "brake"):
        return False
    if command.mode == "move_by" and abs(float(command.distance or 0.0)) < 1e-5:
        return False
    return True


def test_the_routine_walks_the_five_bar_to_ready_after_easing_c1_not_to_its_home(plans):
    """With the claw on, the five-bar's home is ~101 mm into the belt (bam_rack_twin full_arm): phase 0 ends at READY."""
    from sim2real.sim.homing.fullarm_plant import C1, J2
    from sim2real.sim.homing.fullarm_routine import ready_cad

    first = plans["park_first+witness @ READY"]["sequences"][0]
    names = [s.name for s in first.steps]
    walk = [k for k, n in enumerate(names) if n.startswith("J2 + C1 home")]
    assert walk and all("to READY" in names[k] for k in walk)
    assert names[walk[0] - 1] == "C1 eases off its stop (J2 held)"
    last = first.steps[-1]
    target = {c.joint: c.position for c in last.commands if c.joint in (J2, C1)}
    ready = ready_cad()
    assert target[J2] == pytest.approx(ready[J2], abs=1e-9) and target[C1] == pytest.approx(ready[C1], abs=1e-9)


def _movers(sequence) -> list[set]:
    """Per step, the joints it moves: a real relative move, or a position target other than the one that joint already held."""
    held: dict = {}
    out = []
    for step in sequence.steps:
        moving = set()
        for c in step.commands:
            if c.mode == "position":
                if held.get(c.joint) is None or abs(held[c.joint] - float(c.position)) > 1e-9:
                    moving.add(c.joint)
                held[c.joint] = float(c.position)
            else:
                held[c.joint] = None
                if _moving(c):
                    moving.add(c.joint)
        out.append(moving)
    return out


def test_phase_1_closes_the_claw_first_then_moves_one_wrist_joint_at_a_time(plans):
    from sim2real.sim.homing.fullarm_plant import CLAW, WRIST

    for row in RECOMMENDED_ROWS:
        second = plans[row]["sequences"][1]
        names = [s.name for s in second.steps]
        movers = _movers(second)
        first_wrist = min(k for k, moving in enumerate(movers) if moving & set(WRIST))
        assert names.index("claw closes") < first_wrist
        for step, moving in zip(second.steps, movers, strict=True):
            assert len(moving & set(WRIST)) <= 1, f"{row}: step {step.name!r} moves {moving}"
            assert not (moving & set(WRIST) and CLAW in moving), f"{row}: {step.name!r} moves the claw with a wrist joint"


def test_the_park_touch_is_never_a_reference_and_w2_is_defined_with_w1_parked(plans):
    from sim2real.sim.homing.fullarm_plant import W1, W2

    for row in ("park_first+witness @ READY", "multi x2 (3D-printer) @ READY", "press_reverse (backlash every home) @ READY"):
        second = plans[row]["sequences"][1]
        names = [s.name for s in second.steps]
        park = names.index("W1 park touch")
        assert not second.steps[park].define_position
        defines = [k for k, s in enumerate(second.steps) if s.define_position]
        w2 = next(k for k in defines if W2 in second.steps[k].define_position)
        w1 = next(k for k in defines if W1 in second.steps[k].define_position)
        assert park < w2 < w1


def test_a_multi_touch_locates_without_a_reference_and_defines_on_its_last_slow_retouch(plans):
    from sim2real.sim.homing.fullarm_plant import WRIST

    plan = plans["multi x2 (3D-printer) @ READY"]
    second = plan["sequences"][1]
    by_name = {s.name: s for s in second.steps}
    for role in ("W1", "W2", "W3"):
        locate = by_name[f"{role} locates"]
        retouch = by_name[f"{role} re-touch 1"]
        assert not locate.define_position and retouch.define_position
        fast = next(c.speed for c in locate.commands if c.joint in WRIST and _moving(c))
        gentle = next(c.speed for c in retouch.commands if c.joint in WRIST and _moving(c))
        assert math.degrees(fast) == pytest.approx(60.0) and math.degrees(gentle) == pytest.approx(9.0)
    uses = {(step, use) for step, _, _, use in plan["evidence_plan"]}
    assert ("W1 locates", "locate") in uses and ("W1 re-touch 1", "define") in uses


def test_the_routine_ends_holding_ready_with_the_claw_plumb(plans):
    from sim2real.sim.homing.fullarm_plant import W1, W2
    from sim2real.sim.homing.fullarm_routine import READY_TD4_WRIST_DEG

    second = plans["park_first+witness @ READY"]["sequences"][1]
    end = {c.joint: c.position for s in second.steps[-2:] for c in s.commands if c.joint in (W1, W2) and c.mode == "position"}
    assert math.degrees(end[W2]) == pytest.approx(READY_TD4_WRIST_DEG[1]) and math.degrees(end[W1]) == pytest.approx(READY_TD4_WRIST_DEG[0])


# ---------------------------------------------------------------------------------------------------------------- the checks


def _stall(joint, side, raw_deg, torque=1.0):
    from robot_models.homing.types import StallEvidence

    return StallEvidence(joint, side, torque, math.radians(raw_deg), rung="mujoco")


def test_touch_consistency_refuses_retouches_or_a_locate_that_disagree():
    from sim2real.sim.homing.fullarm_plant import W1
    from sim2real.sim.homing.fullarm_routine import FullArmRoutine
    from sim2real.sim.homing.procedures import HomingRefused

    routine = FullArmRoutine.__new__(FullArmRoutine)  # the check alone: no five-bar procedure built
    routine.consistency_tol_deg, routine.locate_tol_deg, routine.notes = 0.25, 1.5, {}
    routine._consistency([_stall(W1, 1, 100.0), _stall(W1, 1, 100.1)], {W1: (1, math.radians(100.4))})
    with pytest.raises(HomingRefused, match="consistency"):
        routine._consistency([_stall(W1, 1, 100.0), _stall(W1, 1, 100.6)], {W1: (1, math.radians(100.3))})
    with pytest.raises(HomingRefused, match="consistency"):
        routine._consistency([_stall(W1, 1, 100.0)], {W1: (1, math.radians(102.0))})


def test_the_span_witness_refuses_a_stall_on_an_obstacle_on_either_side():
    from robot_models.homing.types import BacklashModel, BacklashTable, JointBacklash

    from sim2real.sim.homing.fullarm_plant import W2, arm_prior
    from sim2real.sim.homing.fullarm_routine import FullArmRoutine
    from sim2real.sim.homing.procedures import HomingRefused

    prior = arm_prior()
    span = math.degrees(prior.stops.span_rad(W2))
    low = -100.0
    table = BacklashTable((JointBacklash(W2, BacklashModel("B0")),))
    routine = FullArmRoutine.__new__(FullArmRoutine)
    routine.span_tol_deg, routine.notes = 1.0, {}
    routine._span(prior, [_stall(W2, -1, low), _stall(W2, +1, low + span + 0.3)], table)  # a 0.3 deg gap: fine
    assert routine.notes["span_error_deg"]["W2"] == pytest.approx(0.3, abs=1e-6)
    with pytest.raises(HomingRefused, match="span"):
        routine._span(prior, [_stall(W2, -1, low), _stall(W2, +1, low + span - 18.0)], table)  # stalled 18 deg short: an obstacle


def test_rotor_phases_from_a_homed_file(tmp_path):
    """The witness's calibration from the rack's bam-homed/1 file: each board's zero reading wrapped to one rotor turn (36 deg)."""
    from sim2real.sim.homing.fullarm_routine import rotor_phase_from_homed

    path = tmp_path / "latest.json"
    path.write_text(json.dumps({"schema": "bam-homed/1", "joints": {
        "revolute_11": {"homed": True, "sign": 1, "zero_board_rad": math.radians(-11.08)},
        "revolute_14": {"homed": True, "sign": 1, "zero_board_rad": math.radians(-145.06)},
        "revolute_5": {"homed": True, "sign": 1, "zero_board_rad": math.radians(-47.46)}}}))
    phases = rotor_phase_from_homed(path)
    assert phases["revolute_11"] == pytest.approx(-11.08) and phases["revolute_14"] == pytest.approx(-1.06)
    assert phases["revolute_5"] == pytest.approx(-11.46)


# ---------------------------------------------------------------------------------------------------------------- episodes (slow)


@slow
@needs_twin
def test_a_branched_episode_equals_a_full_one(tmp_path):
    """routine_check runs a cell's five-bar phase once and every row from a copy: that row's numbers must be a full run's."""
    from sim2real.sim.homing import routine_check as rc

    rows = ["park_first+witness @ READY", "multi x2 (3D-printer) @ READY"]
    rc.PLANS.update(rc.preplan_file(rows, tmp_path / "plans.pkl"))
    job = {"cell_index": 22, "cell": ruler.grid_cells()[22], "environment": "nominal", "rows": rows}
    branched = rc.run_job(job, branch=True)[0]
    full = rc.run_job({**job, "rows": rows[:1]}, branch=False)[0]
    for key in ("outcome", "time_s", "zero_error_deg", "belt_contact_ticks", "belt_after_liftoff_ticks", "peak_speed_deg_s", "witness_deg"):
        assert branched[key] == full[key], key


@slow
@needs_twin
def test_the_routine_homes_from_a_rest_on_the_belt(tmp_path):
    from sim2real.sim.homing import routine_check as rc

    row = "park_first+witness @ READY"
    rc.PLANS.update(rc.preplan_file([row], tmp_path / "plans.pkl"))
    report = rc.run_job({"cell_index": 22, "cell": ruler.grid_cells()[22], "environment": "nominal", "rows": [row]}, branch=False)[0]
    assert report["belt_start_bodies"], "the start rests on the belt"
    assert report["outcome_class"] == "homed" and report["covered"]
    assert report["belt_after_liftoff_ticks"] == 0


RACK_HOMED_1124 = Path("/archive/datasets/bam_rig/full_arm/homed/homed_2026-11-13T182448Z.json")


@pytest.mark.skipif(not RACK_HOMED_1124.is_file(), reason="the rack's 11:24 homed file is not here")
def test_the_witness_calibrated_on_the_racks_1124_home_accepts_its_own_stalls_and_puts_w3s_stop_at_2_78():
    """Ground truth (the Sim to Real Agent, 2026-11-13; Zach from video, the ArUco CAD check within 0.5 deg): W3's + stop is the 11:24
    stall, board 1.9334 rad, +2.78 deg mod 36; 10:24's W3 stall (4.5906 rad, +11.02 mod 36) stalled early - the witness refuses it."""
    from sim2real.sim.homing.fullarm_plant import W3, TURN_RAD, arm_prior, wrap_turn
    from sim2real.sim.homing.fullarm_procedures import witness_error
    from sim2real.sim.homing.fullarm_routine import rotor_phase_from_homed

    phases = rotor_phase_from_homed(RACK_HOMED_1124)
    prior = arm_prior(rotor_phase_deg=phases)
    stop = prior.stops.q_rad(W3, +1)
    assert math.degrees(wrap_turn(stop + prior.rotor_phase[W3], TURN_RAD[W3])) == pytest.approx(2.78, abs=0.01)
    document = json.loads(RACK_HOMED_1124.read_text())
    for joint, entry in document["joints"].items():
        for stall in entry.get("stops_board_rad", [])[:1]:
            side = +1 if joint in ("revolute_11", "revolute_17") else -1
            assert abs(math.degrees(witness_error(prior, joint, side, stall))) < 0.01, joint
    assert abs(math.degrees(witness_error(prior, W3, +1, 4.5906))) > 8.0  # 10:24's early stall


# ---------------------------------------------------------------------------------------------------------------- W&B records (no network)


def test_the_wandb_records_are_one_run_per_routine_and_environment_with_the_map_and_the_starts(tmp_path, monkeypatch):
    from sim2real.tracking import homing_fullarm as hf

    monkeypatch.setattr(hf, "MEDIA", tmp_path)
    cell = ruler.grid_cells()[22]
    episodes = []
    for row in ("park_first+witness @ READY", "zach_v1 @ READY"):
        for environment in ("nominal", "B2"):
            r = report(procedure=row, environment=environment, start=cell["name"])
            r.update({"row": row, "cell": cell["cell"], "key": f"{row} | {environment} | {cell['name']}", "outcome_class": "homed", "covered": True})
            episodes.append(r)
    episodes.append({"refused_start": "self-contact", "procedure": "zach_v1 @ READY", "row": "zach_v1 @ READY", "environment": "nominal",
                     "cell": ruler.grid_cells()[0]["cell"], "start": ruler.grid_cells()[0]["name"], "key": "x", "outcome_class": "infeasible"})
    results = {"cards": ruler.score(episodes), "episodes": episodes, "environments": {k: v["why"] for k, v in ruler.ENVIRONMENTS.items()},
               "plant": {}, "ruler": "test", "targets": {}, "sim2real_sha": "abc", "bam_ws_sha": "def", "bundle": "b"}
    batch = hf.records(results)
    assert len(batch) == 4
    assert len({b["id"] for b in batch}) == 4
    for b in batch:
        assert all(len(t.encode()) <= 64 for t in b["tags"])
        assert "coverage_pct" in b["summary"] and "target/silent_wrong" in b["summary"]
        assert Path(b["images"]["coverage_map"]).is_file()
        assert b["tables"]["starts"] and b["tables"]["starts"][0]["W1_deg"] == cell["wrist_deg"][0]
    assert hf.records(results)[0]["id"] == batch[0]["id"]  # the same numbers map to the same run


@pytest.mark.skipif(not RACK_HOMED_1124.is_file(), reason="the rack's 11:24 homed file is not here")
@needs_twin
def test_the_rack_plan_carries_the_sequence_the_witness_calibration_and_which_steps_define(tmp_path):
    """fullarm_routine's CLI (run in its own process: planning builds the comp's model) writes what the Sim to Real Agent runs."""
    import sys

    out = tmp_path / "plan.json"
    done = subprocess.run([sys.executable, "-m", "sim2real.sim.homing.fullarm_routine", "--row", "zach_v1+table @ READY", "--out", str(out)],
                          capture_output=True, text=True, timeout=900, env={**os.environ, "OPENBLAS_NUM_THREADS": "1"})
    assert done.returncode == 0, done.stderr[-500:]
    plan = json.loads(out.read_text())
    assert plan["witness"]["tolerance_deg"] == 0.5
    assert plan["witness"]["rotor_phase_deg"]["W3"] == pytest.approx(12.926, abs=0.01)
    names = [s["name"] for s in plan["sequence"]["steps"]]
    assert names.index("claw closes") < names.index("W1 seeks") < names.index("W2 seeks") < names.index("W3 seeks")
    assert [e["role"] for e in plan["evidence_plan"]] == ["CLAW", "W1", "W2", "W3"]


def test_a_stored_table_moves_each_defining_stalls_zero_by_its_motor_past_link():
    """routine_check.with_table: the table is observe-only (fit adds side x (gap / 2 + compliance x torque) at the cap), so a "+table"
    row is its plain row re-zeroed - on the grid's own runs the derived zeros equal the run "+table" zeros to 1e-6 deg (144 joint-episodes)."""
    from sim2real.sim.homing import routine_check as rc

    episode = report(zero_error_deg={**report()["zero_error_deg"], "W1": -0.46, "W2": 0.48})
    gap, compliance = math.radians(0.25), math.radians(0.33)
    table = [{"joint": "revolute_11", "gap_rad": gap, "compliance_rad_per_nm": compliance},
             {"joint": "revolute_14", "gap_rad": gap, "compliance_rad_per_nm": compliance}]
    out = rc.with_table(episode, table)
    shift = math.degrees(0.5 * gap + compliance * 1.0)
    assert out["zero_error_deg"]["W1"] == pytest.approx(-0.46 + shift)
    assert out["zero_error_deg"]["W2"] == pytest.approx(0.48 - shift)
    assert out["zero_error_deg"]["W3"] == episode["zero_error_deg"]["W3"]


def test_v1_and_park_first_move_identically_until_w1s_first_stall(plans):
    """routine_check.FALLBACK's premise: up to and including W1's first seek (V1's 'W1 seeks', park_first's 'W1 park touch') the two
    sequences command the same, so 'V1, park_first on a W1 refusal' is exactly V1 or exactly park_first, decided at that stall."""
    v1, park = plans["zach_v1 @ READY"]["sequences"], plans["park_first+witness @ READY"]["sequences"]
    assert v1[0].to_dict() == park[0].to_dict()  # phase 0, the five-bar
    a, b = v1[1].steps[:4], park[1].steps[:4]
    assert [s.name for s in a][-1] == "W1 seeks" and [s.name for s in b][-1] == "W1 park touch"
    for x, y in zip(a, b, strict=True):
        assert [c.to_dict() for c in x.commands] == [c.to_dict() for c in y.commands]
        assert [d.to_dict() for d in x.done_when] == [d.to_dict() for d in y.done_when]


def test_the_five_bars_tight_witness_is_calibrated_on_a_geared_twin_too():
    """routine_check.trusted_homes: on B1 / B2 no table-less run is 'homed' (its wrist zeros sit 0.5 deg off), yet its five-bar stalls are
    the true ones - the five-bar's reference must come from them, or the witness skips C1 stalling 44 deg short (found 2026-11-13)."""
    from sim2real.sim.homing import routine_check as rc

    def run(start, c1, w1=0.48):
        r = report(environment="B2", start=start, zero_error_deg={**report()["zero_error_deg"], "C1": c1, "W1": w1})
        r.update({"row": "park_first+witness @ READY", "key": f"park_first+witness @ READY | B2 | {start}", "witness_deg": {}})
        return r

    episodes = [run(f"s{k}", 0.05) for k in range(4)] + [run("jammed", 43.95)]
    derived = rc.tight_witness(episodes, {"B2": {"stall_witness_deg": {"W1": 0.48}}})
    jammed = next(d for d in derived if d["start"] == "jammed")
    assert jammed["outcome_class"] == "refused" and "C1" in jammed["tight_off"]
    assert all(d["outcome_class"] != "refused" for d in derived if d["start"] != "jammed")


def test_a_lost_start_is_placed_in_phase_0_or_the_wrist_by_the_step_or_joint_it_ended_on():
    """The report's "every lost start is phase 0" is counted by routine_check.ended_in: the step a trip or a timeout happened in, the joints a
    witness refused (a five-bar joint among them fired first), or a finished wrong home's worst joint."""
    from sim2real.sim.homing.routine_check import ended_in

    assert ended_in(report(outcome_class="homed")) is None
    assert ended_in(report(outcome_class="infeasible")) is None
    lost = lambda outcome, outcome_class: report(outcome=outcome, outcome_class=outcome_class, finished=False)  # noqa: E731
    assert ended_in(lost("tripped: runaway: J2 at 123 deg/s powered, over 86 deg/s at t 6.32 s in step 'C1 seeks (J2 pushing)'",
                         "tripped")) == "phase 0"
    assert ended_in(lost("aborted: step 'J2 + C1 home (to READY) (waypoint 11 of 54)' was not done within 40.0 s", "timeout")) == "phase 0"
    assert ended_in(lost("aborted: step 'W1 walks across' was not done within 40.0 s", "timeout")) == "wrist"
    assert ended_in(lost("refused: tight witness {'C1': 9.262} deg off the trusted home's stall", "refused")) == "phase 0"
    assert ended_in(lost("refused: rotor-phase witness: {'W2': [2.033]} deg off the stop's phase (tolerance 2.0)", "refused")) == "wrist"
    # a stale calibration refuses the wrist; a five-bar stall in the same refusal was seen first, in phase 0
    assert ended_in(lost("refused: tight witness {'CLAW': 1.5, 'W1': 1.5} deg off the trusted home's stall", "refused")) == "wrist"
    assert ended_in(lost("refused: tight witness {'CLAW': 1.5, 'W1': 1.5, 'C1': 9.262} deg off the trusted home's stall", "refused")) == "phase 0"
    wrong = report(outcome_class="silent_wrong", zero_error_deg={"J2": 0.005, "C1": 45.25, "W1": 0.001, "W2": 0.0, "W3": 0.0, "CLAW": 0.0})
    assert ended_in(wrong) == "phase 0"
    wrong["zero_error_deg"] = {"J2": 0.005, "C1": 0.007, "W1": 67.6, "W2": 0.0, "W3": None, "CLAW": 0.0}
    assert ended_in(wrong) == "wrist"


def test_the_racks_homes_repeat_their_seek_stop_phase_and_a_stall_off_the_stop_stands_out(tmp_path):
    """fullarm_routine.rack_phase_spread: each joint's seek-stop reading mod one rotor turn over the rack's homed files - what the 0.5 deg
    witness has to fit inside. Two homes on W3's stop a power cycle apart (two rotor turns) agree; the 10:24-like early stall is 8.25 off;
    phases either side of the turn's wrap are 0.02 apart, not 35.98."""
    from sim2real.sim.homing.fullarm_routine import rack_phase_spread

    def homed(name, stops_deg):
        joints = {joint: {"can_id": can, "homed": True, "sign": 1, "zero_board_rad": math.radians(deg - 5.0), "stops_board_rad": [math.radians(deg)]}
                  for joint, can, deg in stops_deg}
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"schema": "bam-homed/1", "joints": joints}))
        return path

    paths = [homed("a", [("revolute_17", 16, 110.777), ("revolute_11", 14, 35.99)]),
             homed("b", [("revolute_17", 16, 182.775), ("revolute_11", 14, 72.01)]),
             homed("c", [("revolute_17", 16, 263.023)])]
    out = rack_phase_spread(paths)
    assert out["W3"]["phases_deg"] == pytest.approx([2.777, 2.775, 11.023], abs=1e-6)
    assert out["W3"]["spread_deg"] == pytest.approx(8.248, abs=1e-6)
    assert rack_phase_spread(paths[:2])["W3"]["spread_deg"] == pytest.approx(0.002, abs=1e-6)
    assert out["W1"]["spread_deg"] == pytest.approx(0.02, abs=1e-6)
    assert "W2" not in out


def test_the_report_ranks_routines_on_readys_cells_like_for_like_and_subset_only_rows_last():
    """tools/homing_routine_report.overall: after the rack's pause only V1's and park_first's paths ran PICK, LIFT and UP, so the ranking
    reads READY's cards (every row ran them) and shows the whole grid beside; a row run on six subset cells ranks after the full rows
    whatever its percentage (4 of 6 is not 22 of 33)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("homing_routine_report", Path(__file__).parents[1] / "tools" / "homing_routine_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def start(family, k):
        return {"family": family, "start": f"{family} W1 {k}"}

    episodes = ([report(procedure="full", row="full", **start("READY", 0), finished=False, outcome="refused: tight witness {'W1': 4.4}")]
                + [report(procedure="full", row="full", **start("READY", k)) for k in range(1, 6)]
                + [report(procedure="full", row="full", **start("PICK", k), finished=False, outcome="tripped: runaway", outcome_class="tripped")
                   for k in range(6)]
                + [report(procedure="subset", row="subset", **start("READY", k)) for k in range(2)])
    for e in episodes:
        e.setdefault("outcome_class", ruler.outcome_class(e))
    assert {e["start"].split(" ")[0] for e in module.ready_only(episodes)} == {"READY"}
    whole = ruler.score(episodes)
    ready = ruler.score(module.ready_only(episodes))
    for environment in ("B1", "B2", "friction", "claw_heavy", "phase_draw_2"):  # the full row ran the twins too
        ready[f"full | {environment}"] = whole[f"full | {environment}"] = ready["full | nominal"]
    ranked = module.overall(ready, whole=whole)
    assert [name for name, _ in ranked] == ["full", "subset"]
    full = dict(ranked)["full"]
    assert full["coverage"] == pytest.approx(500 / 6, abs=0.01) and full["grid_coverage"] == pytest.approx(500 / 12, abs=0.01)
    assert full["grid_feasible"] == 12
    assert "grid_coverage" not in dict(ranked)["subset"]


# ---------------------------------------------------------------------------------------------------------------- J1 (amendment 5)


def test_j1_rows_tilt_j1_to_its_minus_90_stop_from_ready_then_back_before_the_claw(plans):
    """Zach's order (2026-11-13 night): J2/C1 -> READY -> J1 seeks its stop -> J1 back to its working angle -> the claw and the wrist. The seek
    is a torque-capped move toward stops.json's revolute_3 side -1 (-89.97 deg) with J1's gravity as feed-forward and J2 / C1 held at READY
    on their comp at the tilt; its stall defines J1 at that stop."""
    from robot_msgs.control import Stall

    from sim2real.sim.homing.fullarm_plant import C1, J1, J2
    from sim2real.sim.homing.fullarm_procedures import stall_lead
    from sim2real.sim.homing.fullarm_routine import J1_KP_NM_PER_RAD, J1_SEEK_CAP_NM, J1_STOP_SIDE, j1_gravity_nm

    second = plans["zach_v1+J1 @ READY"]["sequences"][1]
    names = [s.name for s in second.steps]
    assert names[:6] == ["phase 1: everything holds", "J1 tilts toward its stop", "J1 seeks its stop", "J1 back toward its working angle",
                         "J1 back to its working angle", "claw closes"]
    seek = second.steps[2]
    command = {c.joint: c for c in seek.commands}
    tilt = {c.joint: c for c in second.steps[1].commands}[J1]
    assert tilt.mode == "move_by" and tilt.distance < 0.0  # relative: before its stall J1 reads only its board's own frame
    # the setpoint runs past the stop by more than the stall's lead from the furthest the tilt can leave J1 (46 deg short of the stop)
    assert abs(command[J1].distance) > math.radians(46.0) + stall_lead(J1, J1_SEEK_CAP_NM, J1_KP_NM_PER_RAD)
    assert J1_STOP_SIDE == -1 and command[J1].mode == "move_by" and command[J1].distance < 0.0
    assert command[J1].max_effort == pytest.approx(J1_SEEK_CAP_NM) and command[J1].feedforward_effort < 0.0
    stall = [d for d in seek.done_when if isinstance(d, Stall)]
    assert len(stall) == 1 and stall[0].joint == J1 and stall[0].lead == pytest.approx(stall_lead(J1, J1_SEEK_CAP_NM, J1_KP_NM_PER_RAD))
    assert math.degrees(seek.define_position[J1]) == pytest.approx(-89.972, abs=0.01)
    # J2 / C1 on their comp at the tilt: C1 carries less than at the vertical plane (gravity turns onto the joint axes as J1 goes to -90)
    holds = {c.joint: c for c in second.steps[0].commands}
    assert abs(command[C1].feedforward_effort) < 0.5 * abs(holds[C1].feedforward_effort) and command[J2].mode == holds[J2].mode
    back = {c.joint: c for c in second.steps[4].commands}[J1]
    assert back.mode == "position" and back.position == pytest.approx(0.0)
    # the last part's feed-forward is within 0.7 N.m of J1's gravity at 0: the PD rests it inside its reach tolerance there
    assert abs(back.feedforward_effort - j1_gravity_nm(0.0)) < 0.7
    claw = {c.joint: c for c in second.steps[5].commands}[J1]
    assert claw.position == pytest.approx(0.0) and claw.feedforward_effort == pytest.approx(j1_gravity_nm(0.0))
    assert plans["zach_v1+J1 @ READY"]["evidence_plan"][0][1:] == (J1, -1, "define")


def test_the_j1_cap_beats_its_gravity_and_friction_over_the_whole_sweep():
    """J1's seek cannot stall short on friction: its cap less the worst gravity on the way (every hanging wrist pose of the grid, 15 %
    heavier than the twin) still exceeds the JMC breakaway (0.74 N.m identified on CAN 12; July's crank 1-1.5 N.m)."""
    from sim2real.sim.homing.fullarm_routine import (J1_FRICTION_MAX_NM, J1_GRAVITY_AT_READY_NM, J1_GRAVITY_WORST_NM, J1_SEEK_CAP_NM,
                                                     j1_gravity_nm)

    sweep = [abs(v) for deg, v in J1_GRAVITY_AT_READY_NM.items() if deg <= 0]
    assert max(sweep) <= J1_GRAVITY_WORST_NM
    assert J1_SEEK_CAP_NM - 1.15 * J1_GRAVITY_WORST_NM > J1_FRICTION_MAX_NM >= 1.5
    assert j1_gravity_nm(math.radians(-65.0)) == pytest.approx(J1_GRAVITY_AT_READY_NM[-65]) and j1_gravity_nm(0.0) < 0.0
    assert j1_gravity_nm(math.radians(-62.5)) == pytest.approx(0.5 * (J1_GRAVITY_AT_READY_NM[-65] + J1_GRAVITY_AT_READY_NM[-60]))


def test_the_ruler_scores_j1_only_for_rows_that_home_it():
    good = report(zero_error_deg={"J1": 0.02, "J2": 0.01, "C1": -0.02, "W1": 0.003, "W2": 0.0, "W3": -0.004, "CLAW": 0.001})
    assert ruler.outcome_class(good) == "homed" and ruler.outcome_class({**good, "homes_j1": True}) == "homed"
    off = {**good, "zero_error_deg": {**good["zero_error_deg"], "J1": 0.5}}
    assert ruler.outcome_class(off) == "homed"  # a row that holds J1: J1 is not its business
    assert ruler.outcome_class({**off, "homes_j1": True}) == "inaccurate"
    wrong = {**good, "homes_j1": True, "zero_error_deg": {**good["zero_error_deg"], "J1": 36.0}}
    assert ruler.outcome_class(wrong) == "silent_wrong"
    unzeroed = {**good, "homes_j1": True, "zero_error_deg": {**good["zero_error_deg"], "J1": None}}
    assert ruler.outcome_class(unzeroed) == "silent_wrong"
    assert "J1" in ruler.card([{**good, "homes_j1": True}])["zero_error_p95_deg_by_joint"]


def test_the_plant_runs_j1_without_its_integrator_when_asked():
    if not twin_available():
        pytest.skip("bam_ws's twin is not here")
    from sim2real.sim.homing.fullarm_plant import ArmStart, FullArmHomingPlant
    from sim2real.sim.homing.routine_ruler import FIVEBAR_LEVELS

    j2, c1 = FIVEBAR_LEVELS["READY"]
    start = ArmStart("j1 board", j2, c1, (1.167, 90.0, 0.0), 30.0)
    boards = {}
    for integrator in (True, False):
        plant = FullArmHomingPlant("B0", belt_top_m=0.0, j1_integrator=integrator)
        plant.reset(start)
        boards[integrator] = {d.role: d.config for d in plant.sim.drives}
    assert boards[True]["J1"].ki > 0.0 and boards[False]["J1"].ki == 0.0 and boards[False]["J1"].ilimit == 0.0
    assert boards[False]["J2"].ki == boards[True]["J2"].ki  # only J1's loop changes
