"""sim2real.tracking.rigs: the per-rig W&B projects' gates, offline (no wandb, no network).

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_tracking_rigs.py

Zach's gate rulings (2026-11-11 21:50) are the ruler here: every gate and tracking error comes from the joint encoders through FK,
never the camera; ArUco is a 6-DOF tracked point logged as a flag, never a gate; the gate order is target vs sim (the controller)
first, then sim vs real (the twin, <= 1.5x the same-input repeat floor on the tick clock), then target vs real; the tool gate is
1 mm at a settled stop. The same gate names on both rigs, so one cross-project report compares them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim2real.tracking import rigs
from test_tracking import tree

WANTED = {"tool_error_at_stop_mm", "heldout_sim_vs_real_deg", "target_vs_sim_tracking_deg", "target_vs_sim_at_stop_mm",
          "target_vs_real_at_stop_mm", "tracking_rms_deg", "tracking_rms_tool_mm", "home_repeatability_deg", "aruco_vs_fk_mm"}
ARCHIVE = Path("/archive/datasets/bam_rig/rack_2026-11-10")


def test_every_rig_logs_the_same_named_gates():
    assert set(rigs.GATES) == WANTED
    assert rigs.GATES["tool_error_at_stop_mm"]["limit"] == 1.0


def test_aruco_is_a_flag_never_a_gate():
    aruco = rigs.GATES["aruco_vs_fk_mm"]
    assert aruco["role"] == "flag" and aruco["limit"] is None
    assert all(g["role"] in ("gate", "kpi", "flag") for g in rigs.GATES.values())
    assert [name for name, g in rigs.GATES.items() if g["role"] == "flag"] == ["aruco_vs_fk_mm"]


def test_the_gate_order_is_controller_then_twin_then_real():
    assert rigs.GATE_ORDER == ("target_vs_sim", "sim_vs_real", "target_vs_real")
    stages = {name: g.get("stage") for name, g in rigs.GATES.items()}
    assert stages["target_vs_sim_tracking_deg"] == stages["target_vs_sim_at_stop_mm"] == "target_vs_sim"
    assert stages["heldout_sim_vs_real_deg"] == "sim_vs_real"
    assert stages["tool_error_at_stop_mm"] == stages["target_vs_real_at_stop_mm"] == stages["tracking_rms_deg"] == "target_vs_real"


def test_a_settled_stop_reads_the_encoders_through_fk_never_the_camera(tmp_path):
    dwell = {"source": "synthetic", "summary": {"encoders_fk_mm": {"median": 0.8, "p95": 1.4},
                                                "camera_vs_commanded_mm": {"median": 19.9, "p95": 28.0}},
             "rows": [{"pose": k, "joint_fk_cad_lever_mm": 0.8, "motor_error_deg": [0.01, -0.02], "camera_frames": 15} for k in range(3)]}
    path = tmp_path / "dwell.json"
    path.write_text(json.dumps(dwell))
    numbers = rigs._fivebar_dwell(path, "k", "t", "w", 1)["numbers"]
    assert numbers["tool_error_at_stop_mm"] == numbers["target_vs_real_at_stop_mm"] == 0.8
    assert numbers["tool_error_at_stop_pass"] == 1
    # the camera's number stays beside it as a flag, under a name no gate reads
    assert numbers["flag_camera_vs_commanded_mm"] == 19.9
    assert not any("camera" in key for key in numbers if key in rigs.GATES or key.endswith("_pass"))


def test_every_twin_version_run_carries_type_joint_deployment_and_every_gate_line():
    rig = rigs.Rig("rig", "Sim2Real · test rig", "test rig", ("j1", "j2"))
    batch = rigs.twin_records(tree(), rig, sha="abc", dirty=False)
    assert len(batch) == 5 * 2
    for record in batch:
        config = record["config"]
        assert {"type", "joint", "deployment", "level", "version_kind"} <= set(config)
        assert config["joint"] == (config["instance"] if config["level"] == "joint" else "")
    root = [r for r in batch if r["config"]["level"] == "deployment"]
    assert all(set(rigs.GATES) <= {k.split("/", 1)[1] for k in r["summary"] if k.startswith("gate/")} for r in root)
    after = next(r for r in root if r["config"]["stage_role"] == "after")
    held = {(r["node"], r["stage"]): r for r in tree().tables()["error_stats"] if r["scope"] == "held out"}
    assert after["history"][-1]["heldout_sim_vs_real_deg"] == held[("rig", "refit")]["median_deg"]
    assert "aruco_vs_fk_mm_pass" not in after["history"][-1]


@pytest.mark.skipif(not ARCHIVE.exists(), reason="the rig archive is not mounted")
def test_both_real_rigs_share_the_gate_names_and_lines():
    from sim2real.rack_results import load

    numeric, lines = {}, {}
    for name, rig in rigs.RIGS.items():
        result = load(name)
        batch = rigs.twin_records(result, rig, sha="abc", dirty=False)
        batch += rigs.controller_records(result, rig, rigs.controller_versions(result, rig), sha="abc", dirty=False)
        numeric[name] = {k for r in batch for k in r["history"][-1]}
        lines[name] = {frozenset(k for k in r["summary"] if k.startswith("gate/")) for r in batch if r["config"]["level"] == "deployment"}
        assert all(r["config"]["joint"] in ("",) + rig.joints for r in batch)
    shared = set.intersection(*numeric.values())
    assert {"heldout_sim_vs_real_deg", "tracking_rms_deg", "target_vs_sim_tracking_deg"} <= shared
    assert "tool_error_at_stop_mm" in numeric["fivebar"]
    assert lines["fivebar"] == lines["ur_wrist"] == {frozenset(f"gate/{g}" for g in rigs.GATES)}
