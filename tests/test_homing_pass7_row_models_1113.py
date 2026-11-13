"""Pass 7, the run's shape (2026-11-13): a row may name its own models.

WHY: the fed recovery rows are already falsified on B0 (a smoke sweep from d308187: recover_first(fed)+single_touch+gff trips on
lower_corner and sobol-04 at CAD mass, ff nominal, B0 - the first J2 stall from a crank-below start is a loop contact at J2 -10.75 /
C1 -79.77 deg, not J2's stop, so every feed the plan computed for "on its stop" overfeeds J2 by 4-7 N.m). Running them on B1 (a quarter
timestep, ~5x slower) only re-measures a FAIL; readiness still counts the models a row did not run as missing (not ready).
"""

from __future__ import annotations

import pytest

pytest.importorskip("coal", reason="the homing rung needs robot_models' contact extra (coal + trimesh)")


def test_plan_jobs_runs_each_row_on_its_own_models():
    from sim2real.sim.homing.pass7_rung import plan_jobs

    families = {"recovery": ["r1", "r2"], "real-lane": ["l1"]}
    rows = (("recover_first(fed)+single_touch+gff", "recovery"), ("single_touch+gff", "real-lane"))
    jobs = plan_jobs(rows, ("B0", "B1", "B2"), ("cad",), (1.0,), families, None,
                     row_models={"recover_first(fed)+single_touch+gff": ("B0",)})
    by_row = {}
    for row, model, mass, ff, start, _ in jobs:
        by_row.setdefault(row, set()).add(model)
    assert by_row == {"recover_first(fed)+single_touch+gff": {"B0"}, "single_touch+gff": {"B0", "B1", "B2"}}
    assert len(jobs) == 2 * 1 + 3 * 1
    assert jobs[0][1] == "B1", "B1 sets the wall time: first"


def test_row_models_parse_from_the_command_line():
    from sim2real.sim.homing.pass7_rung import parse_row_models

    assert parse_row_models(["recover_first(fed)+tview_v2+gff=B0", "single_touch+gff=B0,B2"]) == {
        "recover_first(fed)+tview_v2+gff": ("B0",), "single_touch+gff": ("B0", "B2")}
    with pytest.raises(ValueError):
        parse_row_models(["no-equals-sign"])


def test_readiness_counts_a_model_a_row_did_not_run_as_missing():
    from sim2real.sim.homing.gff_rung import config_name, readiness

    row = "recover_first(fed)+single_touch+gff"
    verdicts = {"B0": {config_name(row, m, f): {"pass": True} for m, f in (("end+22%", 0.75), ("end+22%", 1.0), ("end+22%", 1.25), ("cad", 1.0))}}
    r = readiness(verdicts, (row,), ("B0", "B1", "B2"))[row]
    assert not r["ready"] and len(r["missing"]) == 8
