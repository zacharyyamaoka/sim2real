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


def _mesh_peaks(plant):
    """Hook the twin's dead zone: the largest mesh torque (N.m) each wrapped drive has carried since, per physics step."""
    wrapped = plant.rig.backlash
    peaks = {name: 0.0 for name in wrapped.joints}
    before = wrapped.before_step

    def hooked(data):
        before(data)
        for name, joint in wrapped.joints.items():
            peaks[name] = max(peaks[name], abs(float(data.qfrc_applied[joint.gap_dof])))

    wrapped.before_step = hooked
    return peaks, (lambda: setattr(wrapped, "before_step", before))


def test_the_dead_zone_stays_bounded_while_both_drives_press_their_stops_under_gravity(rests):
    """B1 (gear_backlash's dead zone) pressing J2 and C1 on their stops from the bowl, tview's step 2 (seek together at 10 / 7 N.m).

    Red before 2026-11-12 pass 4: at the twin's 0.25 ms step the explicit dead-zone spring on C1 (13 N.m/arcmin on a 0.0020 kg.m^2 mesh
    mode, omega dt = 1.19) gained energy at every flank impact - 5800 N.m of mesh torque and 70 rad/s on the drives within 8 s, where
    the boards give 12 N.m at most and the arm's weight ~6 N.m. That is what tripped the sequences' 3 rad/s speed guard on B1."""
    import numpy as np  # noqa: PLC0415
    from robot_msgs.control import ServoCommand  # noqa: PLC0415

    mujoco_plant = _plant_or_skip()
    plant = mujoco_plant.MujocoRigPlant("B1")
    state = plant.reset(rests["bowl"])
    peaks, unhook = _mesh_peaks(plant)
    start = dict(zip(state.name, state.position, strict=True))
    fastest = 0.0
    try:
        for k in range(800):
            d = 0.1 * 2.0 * math.pi * 0.01 * (k + 1)  # 0.1 rev/s, tview's seek speed
            state = plant.tick(ServoCommand(name=DRIVES, position=np.array([start[DRIVES[0]], start[DRIVES[1]] + d, start[DRIVES[2]] + d]),
                                            max_effort=np.array([7.0, 10.0, 7.0])), 0.01)
            fastest = max(fastest, float(np.abs(state.velocity[1:]).max()))
    finally:
        unhook()
    assert plant.log["touching"][-1][1:] == ["upper", "upper"]  # both drives on their stops: the press the dead zone must carry
    # 150 N.m: a crank impact on its stop through the gap measured 139 N.m at dt/4 and dt/8 alike (converged), 2.5x the board limit
    assert max(peaks.values()) < 150.0, peaks
    assert fastest < 3.0  # the sequences' speed guard (JointCommandSequence.max_speed)


def test_tview_keeps_j2_pressed_on_its_stop_until_c1_has_stalled_too(rests):
    """tview's set-output is defined when C1 stalls (step 2b), so J2 must still be on its stop then. The real lane keeps a stalled drive
    pushing (bam_rack_twin.hardware.tview_run: ``held`` pins its control position cap/kp into the stop, ``literal`` lets it run on).

    Red before 2026-11-12 pass 4: step 2b re-sent J2's seek, and a robot_msgs move_by starts from where the joint is - J2's push dropped
    from its 10 N.m cap to nothing, L1's weight took it 0.57 deg off its stop before C1's stall fired, and tview defined J2's frame there
    (0.85 deg zero error vs CAD where single_touch has the contact pair's 0.285)."""
    from sim2real.sim.homing.bench import prior_for, run_phase  # noqa: PLC0415
    from sim2real.sim.homing.geometry import FivebarGeometry  # noqa: PLC0415
    from sim2real.sim.homing.procedures import TviewV2  # noqa: PLC0415
    from sim2real.sim.homing.sag_proof import sag_proof  # noqa: PLC0415

    mujoco_plant = _plant_or_skip()
    prior = prior_for(FivebarGeometry())
    sequence = TviewV2().plan(prior, [])
    sequence = sag_proof(type(sequence)(joint_names=sequence.joint_names, steps=sequence.steps[:4], name=sequence.name))
    plant = mujoco_plant.MujocoRigPlant("B0")
    plant.reset(rests["home"])
    phase = run_phase(plant, sequence)
    assert phase.status == "done", phase.message
    event = next(e for e in phase.events if e.name.startswith("2b."))
    k = phase.log["plant_offset"] + int(round(event.finished / 0.01)) - 1  # the tick the controller saw when C1's stall held
    assert plant.log["touching"][k][1] == "upper"
    contact = math.radians(124.7144)  # mujoco_plant.twin_contacts: the twin's J2 upper contact
    assert abs(math.degrees(plant.log["link"][k][1] - contact)) < 0.02, math.degrees(plant.log["link"][k][1])
