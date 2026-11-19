"""Gap FF, part 1: the bench feedforward routine ``arm.feedforward_bench``: its catalog row, its collection (paired out-and-back
transfers from the trajectory library), its fit (gravity linear in the twin's regressor plus Coulomb and net viscous friction per drive,
friction cancelled by the way back, holds never rows) and the feedforward it commands. Rounds (collect -> fit -> come back) are part 2,
tests/test_feedforward_rounds.py, after gap A's rounds protocol.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test --extra trajectories pytest -q /home/bam/sim2real/tests/test_feedforward_bench.py

Run it on a cloud VM while the arm is powered (robot_trajectories has no remote: the cut carries it). Pure numpy: no MuJoCo, no device.

Zach, Daily Note 2026-11-18 ("Feedforward CAlibration"): "like whats the process for calibrating this and evaluating it..."; "Right now we
are prior to deployment. Bench vs Deployment right."; "I basically just want to do .calibrate() and then for the feedforward model to be
fit as accurately as possible."; on the motions: "that calibration routine basically can use the trajectory lib to just generate the
things that its needs".

The ruler (written before the code, owned by the FF session; the implementer never edits it or tests/feedforward_toy.py):
1. The catalog row: bench, identify, implemented, no equipment; it finds the chain's link inertials and refines the drives' friction
   (never in an integrated-servo-only cover), names the routines that find them another way (they name it back), its proof, and a
   recorded decision.
2. Each round-1 run is ONE robot_trajectories.trapezoidal_velocity call, played out and back along one path (the up and down legs over the
   same poses cancel friction): a robot_msgs JointTrajectory in Run.command, its cell in Run.spec.
3. The fit recovers gravity on held-out poses and each drive's Coulomb and net viscous friction (negative where friction weakens), from
   moving rows only; the CAD prior fails the same ruler; the grader is THIS file's arithmetic and fails its mutations.
4. A run that goes one way, or comes back along another path, is refused by name ("both directions"). Holds never enter the fit.
5. The feedforward a run commands is the curve the routine fits, at the values it is handed.
6. metrics.actuator.feedback_share is the feedback torque's share of the command on moving rows.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import numpy as np
import pytest

import feedforward_toy as toy  # the shared toy arm: tests/feedforward_toy.py (pytest puts tests/ on the path)

REPO = Path(__file__).resolve().parents[1]


def _fit_module():
    from sim2real.fit import feedforward as ff  # noqa: PLC0415

    return ff


def grade(fit, *, speeds=(0.2, 0.5, 0.8)) -> dict:
    """This file's own grader (never the code under test's): the worst gravity error on 200 held-out poses, and the worst friction error
    at +/- each speed, against the toy's hidden truth."""
    held = toy.held_out_poses()
    gravity = float(np.abs(fit.gravity(toy.regressor, held) - toy.true_gravity(held)).max())
    v = np.array([s for speed in speeds for s in (speed, -speed)])
    got = np.asarray(fit.friction_torque(np.column_stack([v, v])))
    want = np.column_stack([toy.true_friction(j, v) for j in range(2)])
    friction = float(np.abs(got - want).max())
    return {"gravity_error_nm": gravity, "friction_error_nm": friction,
            "passed": gravity <= toy.GRAVITY_TOL_NM and friction <= toy.FRICTION_TOL_NM}


# --- 1. the catalog -----------------------------------------------------------------------------------------------------------------


def test_the_catalog_lists_the_bench_feedforward_routine_its_alternatives_and_its_proof():
    from sim2real.cards import registry as reg  # noqa: PLC0415

    routine = reg.routine(toy.ROUTINE)
    assert (routine.kind, routine.setting, routine.status) == ("identify", "bench", "implemented")
    assert routine.equipment == (), "the robot's own encoders and board torques: nothing to buy"
    def names(entries) -> set[str]:
        return {n for e in entries for n in getattr(e, "parameters", (e,))}

    assert "link_inertials" in names(routine.identifies), routine.identifies
    # WHY refines, not identifies: an integrated-servo-only pick must never get an arm routine in its cover, and must keep
    # servo.dynamics_regression (tests/test_calibration_backend.py); on an arm it refines the friction that routine found
    assert {"frictionloss_nm", "damping_nm_s_rad"} <= names(routine.refines), routine.refines
    assert not {"frictionloss_nm", "damping_nm_s_rad"} & names(routine.identifies), routine.identifies
    for other in ("arm.dynamics_excitation", "servo.dynamics_regression"):
        assert other in routine.alternatives and toy.ROUTINE in reg.routine(other).alternatives, other
    # WHY the checkout under test, never the canonical path (type_cards/tests/test_routines.py's rule): a lane or a cloud cut has its own
    homes = [(REPO if h.repo == "/home/bam/sim2real" else Path(h.repo)) / h.path for h in routine.code if not h.ref]
    assert any(p.name == "feedforward.py" and p.parent.name == "calibration" and p.is_file() for p in homes), homes
    assert "test_feedforward_rounds.py" in routine.oracle_note
    assert sorted((REPO / "docs").glob("decision-feedforward-bench-*.md")), "a new catalog row names its alternatives by a decision"


# --- 2. collection: paired transfers from the trajectory library -------------------------------------------------------------------


def test_each_round_one_run_is_one_trajectory_library_call_out_and_back_on_one_path():
    from robot_msgs.trajectory import JointTrajectory  # noqa: PLC0415

    rt = toy._rt()
    runs = list(toy.make_routine(first=toy.GRID).runs(dict(toy.NOMINAL)))
    assert len(runs) == len(toy.GRID) and len({r.id for r in runs}) == len(toy.GRID)
    assert {tuple(r.spec["cell"]) for r in runs} == set(toy.GRID)
    for run in runs:
        assert run.id.startswith(f"{toy.ROUTINE}/r1/") and run.split == "train"
        command = run.command
        assert isinstance(command, JointTrajectory) and command.joint_names == toy.DRIVES
        calls = [c for c in json.loads(rt.recipe(command))["calls"] if c["kind"] == "trapezoidal_velocity"]
        assert len(calls) == 1 and calls[0]["back_to_start"] is True, json.loads(rt.recipe(command))["calls"]
        (edge, band) = run.spec["cell"]
        assert calls[0]["velocity_fraction"] == pytest.approx(band)
        a, b = toy.POSES[edge[0]], toy.POSES[edge[1]]
        q = command.positions
        assert np.allclose(q[0], a, atol=1e-9) and np.allclose(q[-1], a, atol=1e-9), run.id
        far = int(np.argmax(np.linalg.norm(q - a, axis=1)))
        assert np.allclose(q[far], b, atol=1e-9), run.id
        # the way back retraces the way out: what cancels friction is the same poses passed in both directions
        assert toy.polyline_gap(q[: far + 1], q[far:]) < 1e-6 and toy.polyline_gap(q[far:], q[: far + 1]) < 1e-6, run.id
    by_cell = {tuple(r.spec["cell"]): r for r in runs}
    for edge in toy.EDGES:
        slow_peak = np.abs(toy.derivatives(by_cell[(edge, toy.BANDS[0])].command).velocities).max()
        fast_peak = np.abs(toy.derivatives(by_cell[(edge, toy.BANDS[1])].command).velocities).max()
        assert fast_peak > 1.5 * slow_peak, (edge, slow_peak, fast_peak)


# --- 3-4. the fit and its guards ----------------------------------------------------------------------------------------------------


def test_the_fit_recovers_gravity_and_friction_from_paired_transfers():
    ff = _fit_module()
    measured, cells = toy.collect(toy.GRID)
    fit = ff.fit(measured, toy.regressor, inertial=toy.inertial, prior=toy.theta(toy.NOMINAL), prior_sigma=1.0, groups=cells)
    got = grade(fit)
    assert got["passed"], got
    for j, drive in enumerate(toy.DRIVES):
        assert fit.coulomb[j] == pytest.approx(toy.TRUTH[f"{drive}.frictionloss_nm"], abs=toy.FRICTION_TOL_NM), (drive, fit.coulomb)
        assert fit.damping[j] == pytest.approx(toy.TRUTH[f"{drive}.damping_nm_s_rad"], abs=toy.FRICTION_TOL_NM), (drive, fit.damping)
        assert fit.damping[j] < 0, "friction that weakens with speed is a negative net viscous term, not a clipped zero"
    held = toy.held_out_poses()
    prior_error = float(np.abs(toy.regressor(held) @ toy.theta(toy.NOMINAL) - toy.true_gravity(held)).max())
    assert prior_error > 5 * toy.GRAVITY_TOL_NM, prior_error   # the ruler can fail: CAD sits far outside it
    assert len(fit.residual_nm) == 2 and max(fit.residual_nm) <= 0.08, fit.residual_nm
    assert set(fit.residual_by_group) == set(cells.values()), "the held-out residual leaves out whole cells, never one run of a pair"


def test_this_files_grader_fails_a_friction_sign_flip_and_the_cad_gravity():
    ff = _fit_module()
    measured, cells = toy.collect(toy.GRID)
    fit = ff.fit(measured, toy.regressor, inertial=toy.inertial, groups=cells)
    assert grade(fit)["passed"]
    flipped = grade(dataclasses.replace(fit, coulomb=tuple(-c for c in fit.coulomb), damping=tuple(-d for d in fit.damping)))
    assert not flipped["passed"] and flipped["friction_error_nm"] > 1.0, flipped
    cad = grade(dataclasses.replace(fit, theta=toy.theta(toy.NOMINAL)))
    assert not cad["passed"] and cad["gravity_error_nm"] > 5 * toy.GRAVITY_TOL_NM, cad


def test_a_run_that_goes_one_way_is_refused_by_name():
    ff = _fit_module()
    measured, _cells = toy.collect(toy.FIRST)
    one_way = {}
    for run_id, run in measured.items():
        far = int(np.argmax(np.linalg.norm(run.positions - run.positions[0], axis=1)))
        one_way[run_id] = toy.rows(run, slice(0, far + 1))
    with pytest.raises(ValueError, match="both directions") as refused:
        ff.fit(one_way, toy.regressor, inertial=toy.inertial)
    assert any(run_id in str(refused.value) for run_id in one_way), str(refused.value)


def test_a_run_that_comes_back_along_another_path_is_refused_by_name():
    """Out along one edge, back along a detour: both directions, but never over the same poses, so nothing cancels the friction."""
    ff = _fit_module()
    measured, _cells = toy.collect(toy.FIRST[:1])
    (run_id, run), = measured.items()
    far = int(np.argmax(np.linalg.norm(run.positions - run.positions[0], axis=1)))
    back = np.arange(far, len(run.t))
    detour = run.positions.copy()
    bulge = np.sin(np.linspace(0.0, math.pi, len(back)))[:, None] * np.array([[0.4, -0.4]])
    detour[back] = detour[back] + bulge
    bent = toy.JointTrajectory(t=run.t, joint_names=run.joint_names, positions=detour, velocities=run.velocities,
                               accelerations=run.accelerations, effort=run.effort)
    with pytest.raises(ValueError, match="both directions") as refused:
        ff.fit({run_id: bent}, toy.regressor, inertial=toy.inertial)
    assert run_id in str(refused.value)


def test_holds_never_enter_the_fit():
    """15c's lesson: a hold rests anywhere inside static friction, so it bounds gravity and never equals it. With two-second dwells that
    read heavy, the fit is the same as with every resting sample cut out."""
    ff = _fit_module()
    measured, cells = toy.collect(toy.GRID, dwell_s=2.0)
    moving = {run_id: toy.rows(run, np.flatnonzero(np.abs(run.velocities).max(axis=1) > 1e-6)) for run_id, run in measured.items()}
    with_holds = ff.fit(measured, toy.regressor, inertial=toy.inertial, groups=cells)
    without = ff.fit(moving, toy.regressor, inertial=toy.inertial, groups=cells)
    held = toy.held_out_poses()
    assert np.abs(with_holds.gravity(toy.regressor, held) - without.gravity(toy.regressor, held)).max() <= 0.01
    v = np.array([[0.2, 0.2], [-0.8, -0.8]])
    assert np.abs(np.asarray(with_holds.friction_torque(v)) - np.asarray(without.friction_torque(v))).max() <= 0.01


# --- 5-6. what the routine commands, and the feedback share -------------------------------------------------------------------------


def test_the_feedback_share_is_the_feedback_torques_share_of_the_command_on_moving_rows():
    from sim2real.metrics import actuator  # noqa: PLC0415

    assert "feedback_share" in actuator.__all__
    effort = np.array([[1.0, 2.0], [3.0, -1.0], [0.5, 0.5]])
    fed = np.array([[0.9, 2.0], [3.0, -0.5], [9.0, 9.0]])
    moving = np.array([True, True, False])
    want = math.sqrt(np.mean((effort - fed)[moving] ** 2)) / math.sqrt(np.mean(effort[moving] ** 2))
    assert actuator.feedback_share(effort, fed, moving) == pytest.approx(want)


def test_the_routine_declares_what_it_finds_and_plays_its_first_round_on_the_values_it_is_given():
    from sim2real import rig as seam  # noqa: PLC0415

    routine = toy.make_routine()
    assert routine.id == toy.ROUTINE and set(routine.identifies) == set(toy.GRAVITY_KEYS) | set(toy.FRICTION_KEYS)
    runs = list(routine.runs(dict(toy.NOMINAL)))
    assert all(isinstance(run, seam.Run) and run.split == "train" and "/r1/" in run.id for run in runs)
    assert {tuple(run.spec["cell"]) for run in runs} == set(toy.FIRST) and len(runs) == len(toy.FIRST)
    for run in runs:
        bare = run.command.channels.get("feedforward_effort")
        want = np.asarray(routine.with_feedforward(run.command, toy.NOMINAL).channels["feedforward_effort"])
        assert bare is not None and np.allclose(np.asarray(bare), want), run.id


def test_the_routines_feedforward_is_the_curve_it_fits():
    """What a round commands and what gets installed is one curve: gravity, the inertia's share, Coulomb and net viscous friction."""
    routine = toy.make_routine(first=((toy.EDGES[2], 0.8), (toy.EDGES[4], 0.3)))
    for run in routine.runs(dict(toy.NOMINAL)):
        fed = routine.with_feedforward(run.command, toy.TRUTH)
        assert np.allclose(fed.positions, run.command.positions)
        c = toy.derivatives(fed)
        channel = np.asarray(fed.channels["feedforward_effort"])
        friction = np.column_stack([toy.true_friction(j, c.velocities[:, j]) for j in range(2)])
        want = toy.true_gravity(c.positions) + friction
        cruise = (np.abs(c.velocities) > 0.3) & (np.abs(c.accelerations) < 1e-6)
        assert cruise.any() and np.abs(channel - want)[cruise].max() <= 1e-3, run.id
