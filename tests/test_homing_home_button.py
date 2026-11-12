"""The MuJoCo rung against ground truth: the real arm's home button replayed on ``MujocoRigPlant`` from the real starts, the real board
record as the plant's default, and sag_proof's two fixes on the blind recovery.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_home_button.py

The replay tests need bam_ws's twin and the home button's packages on disk (they skip without them) and the v11 bundle; SIM2REAL_SLOW=1
adds both assemblies from the fold rest and the backlash models (B1, B2).
"""

from __future__ import annotations

import math
import os

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from robot_msgs.control import Reached, Settled, Stall  # noqa: E402

from sim2real.sim.homing import home_button, sag_proof  # noqa: E402
from sim2real.sim.homing.geometry import C1, DEFAULT_ROOT, EXPORT, J1, J2, MIRROR  # noqa: E402
from sim2real.sim.homing.mujoco_plant import REAL_BOARD_RECORD  # noqa: E402
from sim2real.sim.homing.mujoco_plant import available as twin_available  # noqa: E402
from sim2real.sim.homing.recover import PREFIX, load_recovery, recovery_steps  # noqa: E402

SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
needs_twin = pytest.mark.skipif(not (twin_available() and home_button.available() and DEFAULT_ROOT.is_dir()),
                                reason="bam_ws's twin, the home button's packages or the v11 bundle are not on disk")


# ---------------------------------------------------------------------------------------------------------------- the real runs


def test_the_real_runs_are_every_complete_real_home_and_say_what_they_did():
    real = home_button.load_real()
    runs = {run["run"]: run for run in real["runs"]}
    assert set(runs) == {"home_real_222746_t1", "home_real_after_gate1_085634", "home_real_repeatfloor_012056"}
    fold = runs["home_real_222746_t1"]
    assert fold["start_kind"].startswith("does not close") and [s["sequence"][:15] for s in fold["sequences"]] == ["five-bar settle", "five-bar walk h"]
    assert fold["settled"][0]["motors_deg"] == [86.77, -138.8]  # the receipt's settle pose ...
    assert fold["sequences"][0]["steps"][-1]["end_deg"] == pytest.approx([86.77, -138.8], abs=0.01)  # ... read back off the tick rows
    assert fold["end_deg"] == pytest.approx(fold["sequences"][-1]["steps"][-1]["end_deg"], abs=0.01)
    assert runs["home_real_after_gate1_085634"]["comp"] == "gravity_params_massid_real_093852.json" and fold["comp"] == "nominal"
    assert home_button.branches_for(fold) == (EXPORT, MIRROR)
    assert home_button.branches_for(runs["home_real_after_gate1_085634"]) == (EXPORT,)


# ---------------------------------------------------------------------------------------------------------------- the plant's boards


def test_the_plant_runs_the_real_board_record_by_default():
    # CAN 12 (J2) was retuned on the five-bar: kp 144 / kd 8, not RACK_BOARD's 200 / 4 (the runs' own config checks)
    assert REAL_BOARD_RECORD["J2"] == {"kp": 144.0, "ki": 16000.0, "kd": 8.0, "ilimit": 0.8}
    assert REAL_BOARD_RECORD["C1"]["kp"] == REAL_BOARD_RECORD["J1"]["kp"] == 200.0
    assert sag_proof.KP_NM_PER_RAD[J2] == pytest.approx(144.0 / (2 * math.pi))


@needs_twin
def test_mujoco_plant_builds_its_drives_from_the_real_record():
    from sim2real.sim.homing.mujoco_plant import MujocoRigPlant

    plant = MujocoRigPlant("B0", settle_s=0.0)
    assert {role: (cfg.kp, cfg.kd) for role, cfg in plant.boards.items()} == {"J1": (200.0, 4.0), "J2": (144.0, 8.0), "C1": (200.0, 4.0)}


# ---------------------------------------------------------------------------------------------------------------- ground truth


def _check(run_name: str, branch: str, kind: str = "B0"):
    real = {run["run"]: run for run in home_button.load_real()["runs"]}[run_name]
    sim = home_button.replay(real, kind=kind, branch=branch)
    verdict = home_button.verdict(real, sim)
    rows = home_button.compare(real, sim)
    # the same sequences and steps, in order, each ending the way the real one did
    assert verdict["complete"] and verdict["same_steps"], (sim.get("error"), rows)
    assert [r["sim_outcome"] for r in rows] == [r["real_outcome"] for r in rows]
    # and the arm ends where the real one ended, within the home button's own reach (0.06 rad = 3.44 deg)
    assert verdict["lands"], verdict
    return sim, verdict, rows


@needs_twin
@pytest.mark.parametrize("run_name", ["home_real_222746_t1", "home_real_after_gate1_085634", "home_real_repeatfloor_012056"])
def test_the_real_home_sequence_completes_in_sim_from_the_real_start_and_lands_where_the_real_arm_did(run_name):
    sim, verdict, rows = _check(run_name, EXPORT)
    # measured 2026-11-12 (real boards, B0): within 1.1 deg of the real end on both drives
    assert max(abs(v) for v in verdict["end_minus_real_deg"]) <= 1.5, verdict


@pytest.mark.skipif(not SLOW, reason="both assemblies and B1/B2: SIM2REAL_SLOW=1")
@needs_twin
@pytest.mark.parametrize("kind", ["B1", "B2"])
@pytest.mark.parametrize(("run_name", "branch"), [("home_real_222746_t1", EXPORT), ("home_real_222746_t1", MIRROR),
                                                  ("home_real_after_gate1_085634", EXPORT)])
def test_the_real_home_sequence_on_every_backlash_model_and_both_sides_of_the_fold(run_name, branch, kind):
    _check(run_name, branch, kind)


# ---------------------------------------------------------------------------------------------------------------- sag_proof


@pytest.fixture(scope="module")
def recovery():
    sequence, _ = load_recovery()
    from robot_msgs.control import JointCommandSequence

    from sim2real.sim.homing.geometry import DRIVES

    return JointCommandSequence(joint_names=DRIVES, steps=recovery_steps(sequence), name="recover_first prefix")


def test_sag_proof_keeps_every_step_in_order_and_touches_no_define_or_elapsed(recovery):
    proofed = sag_proof.sag_proof(recovery)
    kept = [s for s in proofed.steps if not s.name.startswith(sag_proof.REHOLD_PREFIX)]
    assert [s.name for s in kept] == [s.name for s in recovery.steps]
    for before, after in zip(recovery.steps, kept, strict=True):
        assert after.define_position == before.define_position and after.commands == before.commands
        assert [c for c in after.done_when if not isinstance(c, (Reached, Stall))] == [c for c in before.done_when
                                                                                     if not isinstance(c, (Reached, Stall))]
        # every original Reached is still there, first
        assert [c for c in before.done_when if isinstance(c, Reached)] == [c for c in after.done_when if isinstance(c, Reached)][
            : sum(isinstance(c, Reached) for c in before.done_when)]


def test_the_lift_ends_still_at_its_target_within_what_the_pd_can_sag_under_its_cap(recovery):
    proofed = sag_proof.sag_proof(recovery)
    lift = next(s for s in proofed.steps if s.name == PREFIX + "J2 - 15 deg (lift L1 off), crank limp")
    reaches = [c for c in lift.done_when if isinstance(c, Reached)]
    assert len(reaches) == 2 and reaches[0].tolerance == pytest.approx(0.06)
    cap = next(c.max_effort for c in lift.commands if c.joint == J2)
    assert reaches[1].tolerance == pytest.approx(0.06 + cap / (144.0 / (2 * math.pi)))  # 0.06 + 8 / 22.9 rad
    assert reaches[1].speed == sag_proof.STILL_SPEED_RAD_S and reaches[1].dwell == sag_proof.STILL_DWELL_S


def test_j2s_seek_after_the_crank_seek_re_holds_first_and_stalls_only_past_its_cap(recovery):
    proofed = sag_proof.sag_proof(recovery)
    names = [s.name for s in proofed.steps]
    seek = names.index(PREFIX + "J2 + onto its stop, crank limp")
    rehold = proofed.steps[seek - 1]
    assert rehold.name.startswith(sag_proof.REHOLD_PREFIX) and names[seek - 2] == PREFIX + "C1 + until it stalls, J2 holds"
    modes = {c.joint: c.mode for c in rehold.commands}
    assert modes == {J2: "hold", C1: "limp", J1: "hold"}
    assert rehold.done_when == (Settled(joints=(J2, C1), speed=0.02, dwell=1.0),)  # the home button's settle (HomeTuning)
    stall = next(c for c in proofed.steps[seek].done_when if isinstance(c, Stall))
    original = next(c for s in recovery.steps if s.name == PREFIX + "J2 + onto its stop, crank limp" for c in s.done_when
                    if isinstance(c, Stall))
    assert original.lead == pytest.approx(0.06)
    cap = next(c.max_effort for c in proofed.steps[seek].commands if c.joint == J2)
    assert stall.lead == pytest.approx(0.06 + cap / (144.0 / (2 * math.pi))) and stall.dwell == original.dwell


def test_a_seek_continuing_the_previous_seek_is_left_alone(recovery):
    proofed = sag_proof.sag_proof(recovery)
    names = [s.name for s in proofed.steps]
    # step 6's J2 press continues step 5's J2 seek (same sign): no re-hold for J2 there; C1 begins its seek there, so C1 re-holds
    press = names.index(PREFIX + "C1 + until the hub meets L1's plate, J2 pressed on its stop: define both positions")
    assert proofed.steps[press - 1].name == f"{sag_proof.REHOLD_PREFIX}{C1} before: {names[press]}"
    assert sag_proof.needs_rehold(proofed.steps[press - 2], proofed.steps[press]) == [C1]
