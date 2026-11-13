"""The homing leaderboard's W&B records (sim2real.tracking.homing): the MuJoCo rung's scores against the twin's own contacts ride beside the
CAD ones, and a kinematic result (no twin card: its stops are CAD's) keeps the digest it had. No network: records() only shapes runs.

    env -u VIRTUAL_ENV /home/bam/sim2real/.venv/bin/python -m pytest -q /home/bam/sim2real/tests/test_homing_tracking.py
"""

from __future__ import annotations

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")

from sim2real.tracking import homing  # noqa: E402

CARD = {"reliability_pct": 100.0, "joint_angle_error_deg": 0.2855, "episodes": 1}
TWIN = {"reliability_pct": 100.0, "joint_angle_error_deg": 0.0041, "episodes": 1}
ROW = ["home", True, "done", 30.0, [["revolute_6", 1, 124.71, 125.0]], [["revolute_6", 0.2855, None, 0.0]]]


def _results(**extra):
    base = {"rung": "mujoco", "models": ["B0"], "bundle_sha": "8957130", "hardstops_sha256": "h", "sim2real_sha": "s", "robot_models_sha": "r",
            "gate_deg": 0.1, "hidden_gap_arcmin": {}, "starts": [{"name": "home"}], "scorecards": {"B0": {"recover_first+single_touch": CARD}},
            "episodes": {"B0": {"recover_first+single_touch": [ROW]}}}
    base.update(extra)
    return base


def test_the_twin_card_rides_beside_the_cad_card_with_both_verdicts():
    results = _results(scorecards_vs_twin={"B0": {"recover_first+single_touch": TWIN}},
                       verdicts={"B0": {"recover_first+single_touch": {"pass": True, "pass_vs_cad": False}}},
                       twin_contacts_deg={"J2": {"upper": {"twin": 124.7144, "cad": 125.0, "cad_minus_twin": 0.2856}}})
    (record,) = homing.records(results)
    assert record["summary"]["joint_angle_error_deg"] == 0.2855
    assert record["summary"]["vs_twin.joint_angle_error_deg"] == 0.0041
    assert record["config"]["gate_pass"] is True and record["config"]["gate_pass_vs_cad"] is False
    assert record["config"]["judged_against"] == "twin contacts"


def test_a_kinematic_result_keeps_its_digest_and_its_twin_card_is_its_cad_card():
    results = _results(rung="kinematic")
    assert homing.twin_card(results, "B0", "recover_first+single_touch") is CARD
    before = homing.evaluation_digest(results, "B0", "recover_first+single_touch")
    assert homing.evaluation_digest(dict(results), "B0", "recover_first+single_touch") == before
    with_twin = _results(rung="kinematic", scorecards_vs_twin={"B0": {"recover_first+single_touch": TWIN}})
    assert homing.evaluation_digest(with_twin, "B0", "recover_first+single_touch") != before  # a re-score is a new evaluation


def test_a_wrist_result_goes_to_its_own_project_under_its_own_ids():
    results = _results(rig="ur-wrist")
    (record,) = homing.records(results)
    assert record["config"]["rig"] == "ur-wrist"
    assert record["config"]["result_id"].startswith("homing-urwrist-mujoco-B0-")
    assert homing.PROJECTS[homing.rig_of(results)] == "Homing · UR wrist rig"
    assert homing.records(_results())[0]["config"]["result_id"].startswith("homing-fivebar-")  # the five-bar's ids (and supersede chain) kept
