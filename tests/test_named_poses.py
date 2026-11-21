"""READY by name (bam_ws PEP 0056, 2026-11-15): sim2real reads the robot description's saved positions (``sim2real.named_poses``, a
generated copy of what bam_ws' description publishes) instead of copying READY's numbers.

Two kinds of test: the migration's proof (the homing ruler's cells, the routine's READY targets and J1's home sequence are byte for byte
what the literals gave - captured on main 2841f2f before the change) and the copy's own checks (digests, light import, equal to bam_ws').
When READY moves in the description, the proof fails ON PURPOSE: re-run the homing ruler's results at the new READY cells (PEP 0047's
coverage tables), then re-pin the two hashes below.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_named_poses.py
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from sim2real import named_poses, paths
from sim2real.sim.homing import fullarm_routine, j1_home, routine_check, routine_ruler

# the bytes of the ruler's start cells and of J1's home sequence (json.dumps, sort_keys) when READY was a literal (main 2841f2f)
CELLS_SHA256 = "21192b977b0dbdc12950f42023fb49736ae94203db847e1c421abddf4d425156"
J1_SEQUENCE_SHA256 = "c52e4677183b2c489b5a04ac6a89cd73e143e6791757228eb4381c5f1fbc23aa"


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def test_ready_by_name_is_the_literal_it_replaced():
    """The homing routine's posture, byte for byte the literals READY had (2026-11-15): since READY moved (2026-11-19) the routine reads it
    as the named pose "homing", so none of these moved."""
    ready = named_poses.named_pose("homing")
    assert ready.group == "arm" and ready.kind == "joint"
    assert routine_ruler.FIVEBAR_LEVELS["READY"] == (65.246, 122.791)
    assert fullarm_routine.READY_CRAIG_DEG == (65.246, 122.791)
    assert fullarm_routine.READY_TD4_WRIST_DEG == (1.167, 90.0, 0.0)
    assert routine_check.CALIBRATION_START["wrist_deg"] == (1.167, 90.0, 0.0)
    assert j1_home.J1_READY_RAD == math.radians(-12.7)
    assert fullarm_routine.CRAIG_OFFSET_DEG == {"revolute_6": 90.0, "revolute_7": 137.45861811322055}
    assert fullarm_routine.ready_cad() == {"revolute_6": ready.position_of("revolute_6"), "revolute_7": ready.position_of("revolute_7")}


def test_the_ruler_cells_and_j1s_home_are_byte_for_byte_the_old_ones():
    cells = {"grid": routine_ruler.grid_cells(), "subset": routine_ruler.subset_cells(), "tuning": routine_ruler.tuning_cells()}
    assert _sha(cells) == CELLS_SHA256, "READY's cells moved: re-run the homing ruler's results at them, then re-pin CELLS_SHA256"
    assert _sha(j1_home.j1_home_sequence().to_dict()) == J1_SEQUENCE_SHA256, "J1's home now returns to another READY: re-pin after its twin rows"


def test_the_copy_is_digest_checked_and_names_the_poses():
    assert [(p.name, p.group) for p in named_poses.named_poses()] == [("ready_to_pick", "arm"), ("stow_low_power", "arm"),
                                                                      ("sleep_limp", "arm"), ("homing", "arm"), ("home", "fivebar")]
    with pytest.raises(KeyError, match="there are"):
        named_poses.named_pose("fold")
    j2, c1 = named_poses.fivebar_craig_deg(named_poses.named_pose("home"))
    assert (j2, c1 - 360.0) == pytest.approx((91.01, -126.438), abs=1e-9)  # gff_rung / fullarm_check / fullarm_home HOME_CRAIG_DEG


def test_the_copy_is_bam_ws_descriptions_when_bam_ws_is_here():
    published = paths.BAM_WS_SRC / "dev" / "bam_cad_descriptions" / "bam_cad_descriptions" / "descriptions" / "bam_fb_v2.named_poses.json"
    if not published.exists():
        pytest.skip(f"no published description at {published} (set SIM2REAL_BAM_WS to a current bam_ws)")
    assert (named_poses.HERE / "bam_fb_v2.json").read_text() == published.read_text(), (
        "regenerate the copy: cd ~/bam_ws/src/dev/bam_cad_descriptions; env -u VIRTUAL_ENV uv run python -m bam_cad_descriptions.named_poses --write")


def test_reading_a_pose_loads_no_layer_and_nothing_heavy():
    """J1's home reads READY's J1 inside the rack's powered venv (robot_msgs + sim2real, no robot_models, no MuJoCo)."""

    probe = ("import sys, sim2real.named_poses as n; n.named_pose('ready_to_pick'); "
             "print(sorted(m for m in sys.modules if m.split('.')[0] in {'robot_models', 'mujoco', 'scipy', 'wandb'} "
             "or m.startswith(('sim2real.metrics', 'sim2real.schedule', 'sim2real.fit', 'sim2real.sim', 'sim2real.models', 'sim2real.cards'))))")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1] / "src"))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_ready_moved_and_homing_did_not():
    """2026-11-19: READY (where the arm waits) is the compact pose; the homing routine keeps the old READY's posture (the description's
    HOMING why: J1's top-stop seek and its 9 N.m stall rule were proven there)."""

    ready, homing = named_poses.named_pose("ready_to_pick"), named_poses.named_pose("homing")
    assert ready.digest() != homing.digest()
    assert -89.0 <= math.degrees(ready.position_of("revolute_3")) <= -1.0  # READY's numbers are the description's to change: not pinned
    assert j1_home.J1_READY_RAD == homing.position_of("revolute_3") != ready.position_of("revolute_3")


def test_j1_rack_walks_to_the_homing_posture_on_the_nearest_turn():
    """j1_rack's step 3 (homing_start_q): the named pose "homing", never READY's record, each joint on the turn nearest where it is (today's
    homed map reads C1 a whole turn off: -374.65 deg); the claw stays at the record's."""

    from sim2real.sim.homing.j1_rack import homing_start_q

    homing = named_poses.named_pose("homing")
    record = {"revolute_3": math.radians(-2.0), "revolute_6": math.radians(-5.0), "revolute_7": math.radians(31.4 - 360.0),
              "revolute_11": math.radians(-55.0), "revolute_14": math.radians(90.0), "revolute_17": 0.0, "revolute_5": math.radians(0.1)}
    here = {"revolute_7": math.radians(-374.0), "revolute_6": math.radians(-20.0)}
    out = homing_start_q(here, record)
    assert out["revolute_7"] == pytest.approx(homing.position_of("revolute_7") - 2.0 * math.pi)  # C1 on the measured turn, not 360 away
    assert out["revolute_6"] == pytest.approx(homing.position_of("revolute_6"))
    for joint in ("revolute_11", "revolute_14", "revolute_17"):
        assert out[joint] == pytest.approx(homing.position_of(joint))  # no reading: READY's record picks the turn
    assert out["revolute_5"] == record["revolute_5"]
