"""The full-arm homing ruler (PEP 0047, bam_ws): the harness sees self-contact, Zach's wrist order assigns a forearm stall, park_first
does not, the witness refuses what the harness calls wrong, identify_backlash recovers the hidden wrist gaps, and the replay matches the
rack's wrist seeks. Sim only.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_fullarm_homing.py

The episode tests run the wrist-only form (the five-bar held where it is): ~30 s each. Skips without bam_ws's twin or the bundle.
"""

from __future__ import annotations

import math

import pytest

from sim2real.sim.homing import fullarm_home as fh
from sim2real.sim.homing.mujoco_plant import available as twin_available

needs_twin = pytest.mark.skipif(not (twin_available() and fh.CAD_EXPORTER.is_dir()), reason="bam_ws's twin or the cad-exporter clone is not here")

STOP = 169.85
GUARD = 104.91


# ---------------------------------------------------------------------------------------------------------------- pure


def test_the_park_lands_inside_the_proof_from_every_stall_a_plus_sweep_can_end_on():
    """park_first's argument: a +W1 sweep at 1 N.m stops only on its stop or on the forearm (|W1| > 104.91), so anywhere in
    (104.91, 169.85]; 135 deg back is inside |W1| <= 95, where the CAD proves both pairs clear."""
    from sim2real.sim.homing.fullarm_procedures import PARK_BACK_RAD

    back = math.degrees(PARK_BACK_RAD)
    for tenth in range(int(GUARD * 10) + 1, int(STOP * 10) + 1):
        assert abs(tenth / 10.0 - back) <= 95.0


def test_the_witness_reads_zero_on_the_true_stop_and_the_offset_elsewhere():
    from sim2real.sim.homing.fullarm_plant import W1, arm_prior, wrap_turn
    from sim2real.sim.homing.fullarm_procedures import witness_error

    prior = arm_prior()
    stop = prior.stops.q_rad(W1, +1)
    turn = prior.turn[W1]
    for k in (-3, 0, 5):  # any whole number of rotor turns
        raw = stop + prior.rotor_phase[W1] + k * turn
        assert abs(witness_error(prior, W1, +1, raw)) < 1e-9
    forearm = math.radians(112.6)  # the zach_v1 stall below
    raw = wrap_turn(forearm + prior.rotor_phase[W1], turn)
    assert abs(math.degrees(witness_error(prior, W1, +1, raw))) == pytest.approx(abs(math.degrees(wrap_turn(forearm - stop, turn))), abs=1e-6)


@needs_twin
def test_the_plant_boots_each_wrist_board_inside_one_rotor_turn():
    from sim2real.sim.homing.fullarm_check import HOME_CRAIG_DEG
    from sim2real.sim.homing.fullarm_plant import CLAW, ROTOR_PHASE_DEG, TURN_RAD, WRIST, ArmStart, FullArmHomingPlant, wrap_turn

    plant = FullArmHomingPlant("B0")
    plant.reset(ArmStart("t", *HOME_CRAIG_DEG, (120.0, -40.0, 75.0), 40.0))
    for joint in (*WRIST, CLAW):
        raw = plant.raw(joint)
        assert abs(raw) <= 0.5 * TURN_RAD[joint] + 1e-9
        assert wrap_turn(raw - plant._motor(joint) - math.radians(ROTOR_PHASE_DEG[joint]), TURN_RAD[joint]) == pytest.approx(0.0, abs=1e-9)


@needs_twin
def test_zach_v1_matches_the_rack_recipe():
    """zach_v1 is wrist_home_v1's plan (bam_rack_twin), not a hand copy that can drift: same joints, order, sides, stops, speed, cap, travel."""
    import sys

    from sim2real.sim.homing import fullarm_procedures as fp
    from sim2real.sim.homing.fullarm_check import SELF_COLLISION_SRC

    sys.path.insert(0, str(SELF_COLLISION_SRC / "dev" / "bam_rack_twin"))
    try:
        from bam_rack_twin.hardware.wrist_home_v1 import plan_v1
    except ImportError as error:
        pytest.skip(f"bam_rack_twin's wrist_home_v1 is not importable here: {error}")
    seeks = [s for s in plan_v1() if s["action"] == "find_hardstop"]
    assigns = [s for s in plan_v1() if s["action"] == "assign"]
    from sim2real.sim.homing.fullarm_plant import W1, W2, W3, arm_prior

    sides = arm_prior().seek_side
    assert [s["joint"] for s in seeks] == [W1, W2, W3]
    assert [s["dir"] for s in seeks] == [sides[W1], sides[W2], sides[W3]]
    assert [abs(a["stop_deg"]) for a in assigns] == pytest.approx([STOP] * 3, abs=0.01)
    for seek in seeks:
        assert seek["speed_deg_s"] == pytest.approx(math.degrees(fp.WRIST_SEEK_SPEED))
        assert seek["cap_nm"] == pytest.approx(fp.WRIST_CAP_NM)
        assert seek["travel_deg"] == pytest.approx(math.degrees(fp.WRIST_SEEK_DISTANCE))
        # our seek travels AT LEAST the recipe's (more where robot_msgs' lead-based stall needs it: wrist_seek_distance's WHY)
        assert math.degrees(fp.wrist_seek_distance(75.0 / (2 * math.pi))) >= seek["travel_deg"]


# ---------------------------------------------------------------------------------------------------------------- episodes


def _episode(order: str, wrist, claw: float, kind: str = "B0", table=None, identify: bool = False):
    from sim2real.sim.homing.fullarm_check import HOME_CRAIG_DEG, run_episode
    from sim2real.sim.homing.fullarm_plant import ArmStart, FullArmHomingPlant, arm_prior
    from sim2real.sim.homing.fullarm_procedures import FullArmHome

    plant = FullArmHomingPlant(kind)
    procedure = FullArmHome(order=order, wrist_only=True, identify=identify)
    report = run_episode(procedure, plant, ArmStart("t", *HOME_CRAIG_DEG, tuple(wrist), claw), arm_prior(table))
    return report, procedure


@needs_twin
def test_the_harness_sees_a_self_contact_and_a_guard_breach():
    """The ruler's ruler: a start whose W1 sweep meets the forearm must show up as twin contact AND a CAD-guard breach."""
    report, _ = _episode("zach_v1", (-100.0, -150.0, 0.0), 15.0)
    assert report.self_contact_ticks > 0 and "hard_stop_3/l2" in report.self_contact_pairs
    assert report.guard_breach_ticks > 0 and "l2/hard_stop_3" in report.guard_rules


@needs_twin
def test_zach_v1_assigns_a_forearm_stall_as_its_stop_and_the_witness_would_refuse_it():
    report, _ = _episode("zach_v1", (-100.0, -150.0, 0.0), 15.0)
    assert report.finished  # V1 has no witness: it finishes ...
    assert abs(report.zero_error_deg["W1"]) > 10.0  # ... with W1's zero tens of degrees wrong (57 deg on the twin)
    assert any(s["joint"] == "revolute_11" and abs(s["link_deg"] - s["cad_deg"]) > 1.0 for s in report.stalls)
    assert abs(report.witness_deg["W1"][0]) > 2.0  # and the rotor phase says so


@needs_twin
def test_park_first_homes_every_wrist_joint_from_the_same_start():
    report, _ = _episode("park_first", (-100.0, -150.0, 0.0), 15.0)
    assert report.finished, report.outcome
    for role in ("W1", "W2", "W3", "CLAW"):
        assert abs(report.zero_error_deg[role]) < 0.1
    assert all(abs(s["link_deg"] - s["cad_deg"]) <= 1.0 for s in report.stalls)


@needs_twin
def test_identify_backlash_recovers_each_hidden_wrist_gap():
    from sim2real.sim.homing.fullarm_plant import WRIST, hidden_backlash

    report, _ = _episode("park_first", (20.0, 30.0, -40.0), 15.0, kind="B1", identify=True)
    assert report.finished, report.outcome
    truth = hidden_backlash("B1")
    for joint in WRIST:
        role = {"revolute_11": "W1", "revolute_14": "W2", "revolute_17": "W3"}[joint]
        gate = max(1.0 / 60.0, 0.25 * math.degrees(truth[joint].gap_rad))  # PEP 0002: max(1', 25 % of truth)
        assert report.gap_identified_deg[role] == pytest.approx(math.degrees(truth[joint].gap_rad), abs=gate)


@needs_twin
def test_the_replay_matches_the_racks_w2_and_w3_seek_travel():
    from sim2real.sim.homing.fullarm_check import REAL_V1_JSON, replay_vs_real

    if not REAL_V1_JSON.exists():
        pytest.skip("the rack run's evidence is not on this machine")
    out = replay_vs_real()
    for role in ("W2", "W3"):
        row = out["per_joint"][role]
        assert row["sim_travel_deg"] == pytest.approx(row["real_travel_deg"], abs=2.0)


@needs_twin
def test_resting_on_the_belt_a_0_1_rev_s_first_seek_lurches_and_the_0_05_default_does_not():
    """The rack's power-up rest (2026-11-13 15:50: hanging, the claw on the belt): J2's first seek at single_touch's 0.1 rev/s sticks on the
    belt, then slips past the 86 deg/s runaway stop; FullArmHome's default first seek (0.05 rev/s) does not (PEP 0047).

    WHY the trip is asserted on masses="cad" (2026-11-17, bam_ws PEP 0060 addendum: the twin's default became the measured masses): the
    15:50 reproduction was made on the CAD twin, where the old seek peaks at 86.1 deg/s and trips; on the measured twin it peaks at 83.3
    and finishes - 3 deg/s under the stop, the same lurch - so the trip itself is a CAD-twin fact. The default seek's claim holds on both
    (57.9 / 54.3 deg/s, done), and on the measured twin the old seek still lurches ~30 deg/s past the default's."""
    from sim2real.sim.homing.fullarm_check import run_episode
    from sim2real.sim.homing.fullarm_plant import FullArmHomingPlant, arm_prior, hanging_start
    from sim2real.sim.homing.fullarm_procedures import FullArmHome

    outcomes = {}
    for masses in ("cad", "measured"):
        for label, speed in (("old", None), ("default", 0.05)):
            plant = FullArmHomingPlant("B0", settle_s=3.0, belt_top_m=0.0, contact_timeconst_s=0.01, masses=masses)
            start = hanging_start(plant)
            report = run_episode(FullArmHome(fivebar_only=True, wrist_during_fivebar="brake", j2_first_seek_rev_s=speed), plant, start, arm_prior())
            outcomes[masses, label] = (report.outcome, report.peak_speed_deg_s["J2"], any(plant.log["belt_contact"]))
    old = outcomes["cad", "old"]
    assert old[0].startswith("tripped: runaway: J2") and "J2 seeks" in old[0] and old[2]
    for masses in ("cad", "measured"):
        assert outcomes[masses, "default"][0] == "done" and outcomes[masses, "default"][1] < 86.0, (masses, outcomes[masses, "default"])
    assert outcomes["measured", "old"][1] > outcomes["measured", "default"][1] + 15.0 and outcomes["measured", "old"][2]
