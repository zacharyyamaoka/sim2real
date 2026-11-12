"""The homing bench's MuJoCo rung (mujoco_plant / mujoco_bench) and the coordinator's 2026-11-12 ruling on assembly-mode starts.

    systemd-run --user --scope -q -p MemoryMax=8G -p OOMPolicy=continue -- env -u VIRTUAL_ENV OPENBLAS_NUM_THREADS=1 MUJOCO_GL=egl /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_mujoco_rung.py

The ruling (robot_models PEP 0002 addendum 1): a start on the mirrored assembly is judged on the MuJoCo rung; the kinematic rung's
reliability gate is 100 % over working-assembly starts. The plant tests need bam_ws's twin on disk (bam_fb_test_rig and friends) and the
v11 bundle; they skip without them. SIM2REAL_SLOW=1 adds the whole-episode record (~30 s each).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from sim2real.sim.homing.bench import ASSEMBLY_MODE, WORKING, split_scorecards  # noqa: E402
from sim2real.sim.homing.geometry import DEFAULT_ROOT, DRIVES, EXPORT, MIRROR  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data"
KINEMATIC = DATA / "homing_fivebar_kinematic_recover_first_2026-11-12.json"
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"


# ---------------------------------------------------------------------------------------------------------------- the ruling


@pytest.fixture(scope="module")
def kinematic():
    if not KINEMATIC.is_file():
        pytest.skip(f"no kinematic results: {KINEMATIC}")
    return json.loads(KINEMATIC.read_text())


def test_the_split_puts_only_mirror_starts_in_assembly_mode(kinematic):
    cards = split_scorecards(kinematic["episodes"], kinematic["starts"], "kinematic", kinematic["gate_deg"])
    mirror = sorted(s["name"] for s in kinematic["starts"] if s["branch"] == MIRROR)
    assert mirror == ["flipped_crank"]
    card = cards[ASSEMBLY_MODE]["B2"]["recover_first+press_reverse"]
    assert card["starts"] == mirror and card["episodes"] == 1
    working = cards[WORKING]["B2"]["recover_first+press_reverse"]
    assert working["episodes"] + card["episodes"] == len(kinematic["starts"]) == working["starts"] + 1


def test_kinematic_gate_is_working_assembly_and_assembly_mode_is_judged_on_mujoco(kinematic):
    cards = split_scorecards(kinematic["episodes"], kinematic["starts"], "kinematic", kinematic["gate_deg"])
    for model in ("B0", "B1", "B2"):
        for name in ("recover_first+press_reverse", "recover_first+two_level_touch", "recover_first+single_touch"):
            working, mode = cards[WORKING][model][name], cards[ASSEMBLY_MODE][model][name]
            # the record: the flipped crank fails on the kinematic rung (no gravity) - kept, not dropped
            assert mode["reliability_pct"] == 0.0 and mode["judged_on"] == "MuJoCo" and mode["reliability_gate_pass"] is None
            # the gate: every working-assembly start homes
            assert working["judged_on"] == "kinematic"
            assert working["reliability_pct"] == 100.0 and working["reliability_gate_pass"] is True, (model, name)
    # repeat_checked_seek's own stiffness check refuses rigid stops: still a failing working-assembly card, not hidden by the split
    assert cards[WORKING]["B0"]["recover_first+repeat_checked_seek"]["reliability_gate_pass"] is False


def test_on_the_mujoco_rung_both_scopes_carry_a_verdict(kinematic):
    cards = split_scorecards(kinematic["episodes"], kinematic["starts"], "mujoco", 0.1)
    assert cards[ASSEMBLY_MODE]["B2"]["recover_first+press_reverse"]["judged_on"] == "MuJoCo"
    assert cards[ASSEMBLY_MODE]["B2"]["recover_first+press_reverse"]["reliability_gate_pass"] is False


# ---------------------------------------------------------------------------------------------------------------- the plant


def _plant_or_skip():
    pytest.importorskip("mujoco")
    from sim2real.sim.homing import mujoco_plant  # noqa: PLC0415

    if not mujoco_plant.available() or not (DEFAULT_ROOT / "hardstops.json").is_file():
        pytest.skip("bam_ws's twin or the v11 bundle is not on disk")
    return mujoco_plant


@pytest.fixture(scope="module")
def rests():
    from sim2real.sim.homing.bench import named_rests, prior_for  # noqa: PLC0415
    from sim2real.sim.homing.geometry import FivebarGeometry  # noqa: PLC0415

    geometry = FivebarGeometry()
    return {start.name: start for start in named_rests(geometry, prior_for(geometry))}


def test_a_start_is_placed_on_the_assembly_it_names(rests):
    mujoco_plant = _plant_or_skip()
    plant = mujoco_plant.MujocoRigPlant("B2", settle_s=0.0)
    for name in ("bowl", "flipped_crank"):
        plant.reset(rests[name])
        placed = plant.start_settled["placed_link_deg"]
        for joint, role in zip(DRIVES, ("J1", "J2", "C1"), strict=True):
            assert placed[role] == pytest.approx(math.degrees(rests[name].link_rad[joint]), abs=1e-6)
        assert plant.start_settled["settled_assembly"] == (MIRROR if name == "flipped_crank" else EXPORT)


def test_the_encoder_reads_motor_minus_hidden_zero_plus_its_frame(rests):
    from robot_msgs.control import ServoCommand  # noqa: PLC0415

    mujoco_plant = _plant_or_skip()
    plant = mujoco_plant.MujocoRigPlant("B2", settle_s=0.0)
    state = plant.reset(rests["home"])
    truth = plant.truth()
    for i, joint in enumerate(DRIVES):
        expected = truth["motor_rad"][joint] - rests["home"].hidden_offset_rad[joint]
        assert state.position[i] == pytest.approx(expected, abs=1e-12)
    limp = ServoCommand(name=DRIVES, position=[math.nan] * 3, max_effort=[0.0] * 3)
    state = plant.tick(limp, 0.01, {DRIVES[1]: 1.0})
    assert state.position[1] == pytest.approx(1.0, abs=2e-3)  # the define, then one 10 ms limp tick of drift at most
    assert list(state.effort) == [0.0, 0.0, 0.0]  # a limp board pushes nothing
    assert plant.backlash[DRIVES[2]].gap_rad == pytest.approx(math.radians(4.0 / 60.0))  # the truth scored = the twin's gap


@pytest.mark.skipif(not SLOW, reason="a whole MuJoCo episode, ~30 s: SIM2REAL_SLOW=1")
@pytest.mark.xfail(strict=True, reason="MuJoCo rung 2026-11-12: recover_first's step 3 (J2 -15 deg, Reached 0.06 rad) never completes "
                   "under gravity - J2 hangs 5.85 deg below its target (109.74 -> 103.89 deg, 0.102 rad: 3.24 N.m of gravity on the "
                   "board's 31.8 N.m/rad PD), a lag behind the motion is not a Stall, and the step times out at 60 s from 13 of 16 starts")
def test_recover_first_homes_from_the_bowl_on_mujoco(rests):
    from sim2real.sim.homing.bench import prior_for, run_episode  # noqa: PLC0415
    from sim2real.sim.homing.geometry import FivebarGeometry  # noqa: PLC0415

    mujoco_plant = _plant_or_skip()
    episode = run_episode("recover_first+press_reverse", mujoco_plant.MujocoRigPlant("B2"), rests["bowl"], prior_for(FivebarGeometry()),
                          "mujoco · B2")
    assert episode.record.finished, episode.record.outcome
