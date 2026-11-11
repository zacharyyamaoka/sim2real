"""sim2real.schedule: a 1-DOF joint description -> its test schedule, with the coverage known before anything runs.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_schedule_joint.py

Zach, 2026-11-10 (proposal 2, step 4): "schedule/: description -> test schedule, with coverage known before running. It comes from
bam_rack_twin/schedule.py." Written before sim2real.schedule held it (red first).

Oracles from outside the code under test: every schedule the rack froze on /archive (36 documents, each with the coverage it was
written with) must get that coverage back from its own trajectories and runs; and the dense cell counts must equal robot_msgs.coverage's
own binning rule (numpy.histogramdd's convention) point by point. The build is driven by a toy player that knows no rack, so the
generator's split rule and stretch ladder are proven without the runner.
"""

from __future__ import annotations

import functools
import glob
import json
import math
import random
from pathlib import Path

import numpy as np
import pytest
from robot_msgs.coverage import occupancy as rm_occupancy
from robot_msgs.coverage import signed

from sim2real.cards import servo_gates as cards
from sim2real.schedule import joint

SCHEDULES = sorted(glob.glob("/archive/datasets/bam_rig/schedules/**/schedule.json", recursive=True))


# --------------------------------------------------------------------------- the frozen schedules (the oracle)


@pytest.mark.skipif(not SCHEDULES, reason="the rack archive is not mounted")
def test_every_frozen_schedule_gets_its_own_coverage_back():
    assert len(SCHEDULES) >= 30
    for path in SCHEDULES:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        got = joint.coverage(document, minimum_pct=document["coverage"]["gate"]["minimum_pct"], note_targets=cards.NOTE_TARGETS)
        assert json.loads(json.dumps(got)) == document["coverage"], path


# --------------------------------------------------------------------------- the binning rule is robot_msgs.coverage's


def test_dense_occupancy_is_robot_msgs_occupancy_cell_by_cell():
    rng = np.random.default_rng(7)
    edges = [np.linspace(-1.0, 1.0, 13), np.array(signed((0.01, 0.1, 1.0), 2.0)), np.array(signed((0.1, 0.5, 1.0), 40.0))]
    points = np.column_stack([rng.uniform(-1.2, 1.2, 4000), rng.uniform(-2.5, 2.5, 4000), rng.uniform(-50, 50, 4000)])
    points[:4] = [[1.0, 2.0, 40.0], [-1.0, -2.0, -40.0], [0.0, 0.0, 0.0], [math.nan, 0.0, 0.0]]  # last edges, first edges, the dead cell, NaN
    dense = joint.occupancy(points, edges)
    cells, outside = rm_occupancy(points.tolist(), [edge.tolist() for edge in edges])
    assert {cell: int(dense[cell]) for cell in cells} == cells
    assert int(dense.sum()) == sum(cells.values()) and outside == len(points) - int(dense.sum())


def test_edges_are_signed_fractions_of_the_envelope():
    edges = joint.edges_of({"range_rad": (-0.5, 0.7), "speed_rad_s": 2.0, "accel_rad_s2": 80.0})
    assert edges[0].tolist() == np.linspace(-0.5, 0.7, joint.Q_BINS + 1).tolist()
    assert edges[1].tolist() == signed(joint.QD_EDGE_FRACTIONS, 2.0) and edges[2].tolist() == signed(joint.QDD_EDGE_FRACTIONS, 80.0)


# --------------------------------------------------------------------------- the build, through a player that knows no rack

TOY = joint.JointDescription(name="toy", can_id=None, origin_rad=0.0, range_rad=(-0.5, 0.5), speed_rad_s=2.0, accel_rad_s2=20.0,
                             torque_limit_nm=5.0, cap_command_nm=5.0, gravity_nm=1.0, inertia_kg_m2=0.01, coulomb_nm=0.05)


def _sine(amplitude):
    def make(description, rng, stretch, variant):
        duration = 4.0 * stretch
        return joint.Sampled(lambda t: amplitude * np.sin(2 * np.pi * 0.5 / stretch * np.asarray(t, float)) * joint.fade(t, duration, 0.5 * stretch),
                             duration + 0.5, {"amplitude_rad": amplitude, "stretch": stretch})
    return make


def _hop(description, rng, stretch):
    reach = rng.uniform(0.1, 0.3)
    duration = 3.0 * stretch
    return joint.Sampled(lambda t: reach * joint.fade(t, duration, 1.0 * stretch), duration + 0.5, {"reach_rad": reach, "stretch": stretch})


def _player():
    families: dict = {}
    register = functools.partial(joint.register, families)
    register("sine", origin="a test sine", runner=False, group="excite", code="E1", variants=1)(_sine(0.3))
    register("too_wide", origin="a sine past the range", runner=False, group="excite", code="E2", variants=1)(_sine(2.0))
    register("hop", origin="a seeded hop", runner=False)(_hop)
    modes = {name: {"runner": {"status": "runnable"}} for name in joint.TRACKING_MODES}
    return joint.Player(families=families, modes=lambda description: dict(modes),
                        sample=functools.partial(joint.sample, fine_s=0.001, rate_hz=100.0), step_of=lambda description, candidate, q: None,
                        velocity_kinds=(), run_time=lambda document: {"fb": 1.0}, rate_hz=100.0, schema="sim2real.test_schedule/1", note="toy")


def test_the_split_rule_and_the_stretch_ladder():
    document = joint.build_schedule(TOY, _player(), families=("sine", "too_wide", "hop"), minimum_pct=10.0, note_targets=cards.NOTE_TARGETS)
    assert document["schema"] == "sim2real.test_schedule/1" and document["rate_hz"] == 100.0 and document["run_time"] == {"fb": 1.0}
    # the excite sine: one run per kp level, the middle one held out (H1); the operate hop: 3 train seeds under fb, 3 held out under every mode
    sine = [run for run in document["runs"] if run["family"] == "sine"]
    assert [(run["kp_level"], run["split"], run["held_out_set"]) for run in sine] == [(1.0, "train", None), (0.5, "held_out", "H1"),
                                                                                       (0.25, "train", None)]
    hop = [run for run in document["runs"] if run["family"] == "hop"]
    assert sum(run["split"] == "train" for run in hop) == 3 and {run["mode"] for run in hop if run["split"] == "train"} == {"fb"}
    assert sum(run["held_out_set"] == "H2" for run in hop) == 3 * len(joint.TRACKING_MODES)
    # a target past the range at every stretch is rejected with its reasons, never clipped into the schedule
    assert [item["family"] for item in document["rejected"]] == ["too_wide"] and "range" in document["rejected"][0]["reasons"][0]
    # the coverage is known before anything runs, and its gate is the one asked for
    assert document["coverage"]["gate"]["minimum_pct"] == 10.0 and document["coverage"]["train"]["runs"] == 2 + 3
    assert all(trajectory["status"] == "not run yet" for trajectory in document["trajectories"])


def test_the_build_is_reproducible_from_its_seed():
    first = joint.build_schedule(TOY, _player(), families=("sine", "hop"), minimum_pct=10.0, note_targets=cards.NOTE_TARGETS)
    again = joint.build_schedule(TOY, _player(), families=("sine", "hop"), minimum_pct=10.0, note_targets=cards.NOTE_TARGETS)
    other = joint.build_schedule(TOY, _player(), families=("sine", "hop"), seed=1, minimum_pct=10.0, note_targets=cards.NOTE_TARGETS)
    assert first["digest"] == again["digest"] and first["digest"] != other["digest"]
    with pytest.raises(ValueError, match="unknown families"):
        joint.build_schedule(TOY, _player(), families=("nope",), minimum_pct=10.0, note_targets=cards.NOTE_TARGETS)


def test_the_description_round_trips_and_keeps_old_digests():
    values = TOY.to_json()
    assert "integral_within_bound" not in values  # written only when True, so a description from before it keeps its digest
    assert joint.JointDescription.from_json(values) == TOY
    assert joint.JointDescription.from_json({**values, "integral_within_bound": True}).to_json()["integral_within_bound"] is True
    assert joint.integral_over_bound(200.0, 2.0, 16000.0, 0.02) == pytest.approx(16000.0 / (2.0 * 200.0 / 0.02))
    assert joint.integral_over_bound(200.0, 2.0, 0.0, 0.02) is None


def test_violations_name_every_limit_crossed():
    t = np.arange(0.0, 1.0, 0.01)
    target = {"t": t, "q": 0.9 * np.ones_like(t), "qd": 3.0 * np.ones_like(t), "qdd": np.zeros_like(t), "qdd_fine_peak": 30.0}
    found = joint.violations(TOY, target)
    assert [line.split()[0] for line in found] == ["range", "speed", "accel"]
    assert joint.violations(TOY, {**target, "q": np.zeros_like(t), "qd": np.zeros_like(t), "qdd_fine_peak": 0.0}) == []
    random.seed(0)  # (the generator's own randomness is seeded per trajectory; nothing global)
