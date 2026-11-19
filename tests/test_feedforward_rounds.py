"""Gap FF, part 2: the bench feedforward routine's rounds, on gap A's rounds protocol: round 1 plays the slow band on the CAD prior's
feedforward; each later round collects only empty or over-tolerance cells, with commands made from the last fit; it stops when the fit stops
changing (converged), when it stops improving, or at its cap, and says which. Graded against a sealed hidden truth in sim, then on
performance gained (feedback share and tracking, four controller variants). Needs gap A part 2 and FF part 1.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test --extra trajectories pytest -q /home/bam/sim2real/tests/test_feedforward_rounds.py

SIM2REAL_SLOW=1 adds the closed-loop tier; the orchestrator runs it with SIM2REAL_WRITE_LADDERS=1 on a cloud VM (never this host while the
arm is powered) and commits sysid/results/routine_ladders/arm.feedforward_bench.json, which the planner's recovery reads.

Zach, 2026-11-18: "a routine should include datacollection and fitting steps, and then iterating things that all goes into it...".
2026-11-11: "we also want to see low feedback torque, where most of it is coming from feedforward terms". 2026-11-13: show "Fb only, FF
only FB + FF (showing the contribution of both)".

The ruler (written before the code, owned by the FF session; the implementer never edits it or tests/feedforward_toy.py):
1. Round 2 collects exactly what round 1 lacked, with commands made after round 1's fit; at noise 0 it stops converged at two rounds.
   Only the runner plays rounds, at the world's values (a routine playing its own data through the handle is caught).
2. Under noise it recovers every value inside its cap; a model that cannot explain the data stops on "no improvement", never "converged".
3. Closed loop (slow): recovery at 0x/1x/3x, a 10x run that never claims a convergence the truth refutes, and the fitted feedforward at
   least halves the feedback share and the tracking error of the CAD feedforward on transfers it never played; FB-only and FF-only are
   reported beside them. The ladder is written before any pass assertion and carries the code's hashes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

import feedforward_toy as toy  # the shared toy arm: tests/feedforward_toy.py

REPO = Path(__file__).resolve().parents[1]
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
WRITE = os.environ.get("SIM2REAL_WRITE_LADDERS") == "1"
slow = pytest.mark.skipif(not SLOW, reason="the closed-loop toy arm (minutes of numpy): SIM2REAL_SLOW=1, on a cloud VM")
LADDER = REPO / "sysid" / "results" / "routine_ladders" / f"{toy.ROUTINE}.json"
CODE = (REPO / "src" / "sim2real" / "calibration" / "feedforward.py", REPO / "src" / "sim2real" / "fit" / "feedforward.py")
LEVELS = {"0x": 0.0, "1x": 1.0, "3x": 3.0, "10x": 10.0}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _round(run_id: str) -> int:
    return int(toy.ROUND.search(run_id).group(1))


def _step(calibration) -> dict:
    (step,) = calibration.routines
    return step


def _only_the_runner_played(rig) -> None:
    assert rig.asked and all(stream.startswith("routine:") for stream, _ in rig.asked), {s for s, _ in rig.asked}
    for _stream, values in rig.asked:
        assert all(values[k] == pytest.approx(toy.TRUTH[k]) for k in toy.TRUTH), "every play is at the world's values: the runner's"


def _gravity_error(values) -> float:
    held = toy.held_out_poses()
    return float(np.abs(toy.regressor(held) @ toy.theta(values) - toy.true_gravity(held)).max())


def _friction_error(values) -> float:
    v = np.array([0.2, -0.2, 0.5, -0.5, 0.8, -0.8])
    return max(float(np.abs(toy.true_friction(j, v, values) - toy.true_friction(j, v)).max()) for j in range(2))


# --- 1-2. the runner: collect, fit, come back for more -------------------------------------------------------------------------------


def test_calibrate_comes_back_for_what_round_one_lacked_and_stops_when_the_fit_stops_changing():
    routine = toy.make_routine()
    rig = toy.ToyArm(routine)
    calibration, _ = toy.runner(rig).calibrate(noise=0.0)
    _only_the_runner_played(rig)
    rounds = sorted({_round(run_id) for run_id, _ in rig.played})
    assert rounds == [1, 2], rounds
    assert {cell for run_id, cell in rig.played if "/r1/" in run_id} == set(toy.FIRST)
    assert {cell for run_id, cell in rig.played if "/r2/" in run_id} == set(toy.GRID) - set(toy.FIRST)
    step = _step(calibration)
    assert len(step["rounds"]) == 2 and step["converged"] is True and "converged" in step["stopped"], step["stopped"]

    def feedforward_error(run_id, low, high):
        c = toy.derivatives(rig.commands[run_id])
        channel = np.asarray(c.channels["feedforward_effort"])
        want = toy.true_gravity(c.positions) + np.column_stack([toy.true_friction(j, c.velocities[:, j]) for j in range(2)])
        cruise = (np.abs(c.velocities) > low) & (np.abs(c.velocities) < high) & (np.abs(c.accelerations) < 1e-6)
        return float(np.abs(channel - want)[cruise].max()) if cruise.any() else None

    # round 1 ran on the CAD prior; round 2's commands were made after round 1's fit (at the speeds round 1 covered)
    first = [e for e in (feedforward_error(run_id, 0.05, 2.0) for run_id, _ in rig.played if "/r1/" in run_id) if e is not None]
    second = [e for e in (feedforward_error(run_id, 0.15, 0.4) for run_id, _ in rig.played if "/r2/" in run_id) if e is not None]
    assert len(first) == len(toy.FIRST) and min(first) > 0.3, first
    assert second and max(second) < 0.02, second
    rows_by_key = {r["key"]: r for r in calibration.rows}
    assert all(rows_by_key[k]["pass"] is True for k in toy.GRAVITY_KEYS + toy.FRICTION_KEYS), \
        [(k, rows_by_key[k]["recovered"], rows_by_key[k]["true"]) for k in toy.GRAVITY_KEYS + toy.FRICTION_KEYS]


def test_calibrate_under_noise_recovers_inside_the_cap():
    routine = toy.make_routine(max_rounds=4)
    rig = toy.ToyArm(routine)
    calibration, state = toy.runner(rig).calibrate(noise=1.0)
    _only_the_runner_played(rig)
    rounds = {_round(run_id) for run_id, _ in rig.played}
    assert 2 <= max(rounds) <= 4 and len(_step(calibration)["rounds"]) == max(rounds), rounds
    assert calibration.failing == [] and calibration.passed, calibration.failing
    assert _gravity_error(state["values"]) <= toy.GRAVITY_TOL_NM


def test_a_model_that_cannot_explain_the_data_stops_on_no_improvement_never_converged():
    keys = (toy.GRAVITY_KEYS[0], toy.GRAVITY_KEYS[2])

    def blind(q):   # the centres of mass's offsets left out
        return toy.regressor(q)[..., [0, 2]]

    routine = toy.make_routine(regressor=blind, gravity_keys=keys, max_rounds=4)
    rig = toy.ToyArm(routine)
    calibration, _ = toy.runner(rig).calibrate(noise=0.0)
    step = _step(calibration)
    assert 2 <= len(step["rounds"]) <= 4 and step["converged"] is False, step["stopped"]
    assert "no improvement" in step["stopped"] or "max_rounds" in step["stopped"], step["stopped"]
    assert "converged" not in step["stopped"].split(":")[0], step["stopped"]


def test_the_committed_ladder_is_this_files_run_of_this_code():
    assert LADDER.is_file(), f"{LADDER.relative_to(REPO)} is written by this file's slow ladder (SIM2REAL_WRITE_LADDERS=1 SIM2REAL_SLOW=1)"
    doc = json.loads(LADDER.read_text(encoding="utf-8"))
    assert doc["routine"] == toy.ROUTINE and set(doc["levels"]) == set(LEVELS)
    assert doc["provenance"]["code_sha256"] == [_sha256(p) for p in CODE], "the ladder graded other code: run it again"
    assert doc["provenance"]["test_sha256"] == _sha256(Path(__file__))
    assert doc["levels"]["1x"]["pass"] is True, doc["levels"]


# --- 3. the closed-loop tier (SIM2REAL_SLOW=1) ----------------------------------------------------------------------------------------


@slow
def test_closed_loop_ladder_recovers_the_identifiable_model_and_never_claims_a_convergence_the_truth_refutes():
    from sim2real.calibration import recovery as rec  # noqa: PLC0415

    levels = {}
    for level, scale in LEVELS.items():
        routine = toy.make_routine()
        rig = toy.ToyArm(routine, closed_loop=True)
        calibration, state = toy.runner(rig).calibrate(noise=scale)
        step = _step(calibration)
        gravity, friction = _gravity_error(state["values"]), _friction_error(state["values"])
        levels[level] = {"pass": bool(gravity <= toy.GRAVITY_TOL_NM and friction <= 2 * toy.FRICTION_TOL_NM),
                         "worst_error_over_tolerance": max(gravity / toy.GRAVITY_TOL_NM, friction / (2 * toy.FRICTION_TOL_NM)),
                         "gravity_error_nm": gravity, "friction_error_nm": friction, "rounds": len(step["rounds"]),
                         "converged": step["converged"], "stopped": step["stopped"]}
        print(level, levels[level], flush=True)
    doc = {"schema": rec.LADDER_SCHEMA, "routine": toy.ROUTINE, "generated_by": "tests/test_feedforward_rounds.py", "levels": levels,
           "tolerance": {"gravity_nm": toy.GRAVITY_TOL_NM, "friction_nm": 2 * toy.FRICTION_TOL_NM},
           "provenance": {"code_sha256": [_sha256(p) for p in CODE], "test_sha256": _sha256(Path(__file__))}}
    if WRITE:  # WHY before the asserts: a FAIL lands in the committed ladder, where the planner reports it truthfully
        LADDER.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    else:  # WHY (the 2026-11-18 dry-run review): without this, any hand-written ladder with the right hashes passes the fast check
        committed = json.loads(LADDER.read_text(encoding="utf-8"))["levels"]
        for level, entry in levels.items():
            assert committed[level]["pass"] == entry["pass"], ("the committed ladder is not this run", level, committed[level], entry)
            assert committed[level]["worst_error_over_tolerance"] == pytest.approx(entry["worst_error_over_tolerance"], rel=1e-3, abs=1e-9), level
    for level in ("0x", "1x", "3x"):
        assert levels[level]["pass"], (level, levels[level])
    for level, entry in levels.items():
        assert 1 <= entry["rounds"] <= 4, (level, entry)
        if entry["converged"]:
            assert entry["gravity_error_nm"] <= toy.GRAVITY_TOL_NM, (level, "it claimed a convergence the truth refutes", entry)


@slow
def test_the_fitted_feedforward_halves_the_feedback_share_and_the_tracking_error_on_held_out_transfers():
    """Performance, not only recovery: transfers the routine never played, run on four controllers (the board's PD alone, the fitted
    feedforward alone, CAD feedforward + PD, fitted feedforward + PD), so each one's contribution shows."""
    routine = toy.make_routine()
    rig = toy.ToyArm(routine, closed_loop=True)
    _, state = toy.runner(rig).calibrate(noise=1.0)
    noise = rig.noise()
    held_cells = tuple(((a, b), 0.5) for a, b in ((0, 3), (0, 4), (2, 3), (1, 4)))
    variants = {"fb only": None, "ff only": state["values"], "cad ff + fb": toy.NOMINAL, "fitted ff + fb": state["values"]}
    results = {name: [] for name in variants}
    for run in toy.make_routine(first=held_cells).runs(dict(toy.NOMINAL)):
        for name, values in variants.items():
            command = toy.bare(run.command) if values is None else routine.with_feedforward(toy.bare(run.command), values)
            gains = ((0.0, 0.0), (0.0, 0.0)) if name == "ff only" else None
            measured = toy.closed_loop(command, toy.TRUTH, noise, noise.rng("performance", f"{name}/{run.id}"), gains=gains)
            results[name].append(toy.share_and_tracking(measured))
    means = {name: np.mean(v, axis=0) for name, v in results.items()}
    print({name: dict(share=float(m[0]), tracking=float(m[1])) for name, m in means.items()}, flush=True)
    assert means["fitted ff + fb"][0] <= 0.5 * means["cad ff + fb"][0], means
    assert means["fitted ff + fb"][1] <= 0.5 * means["cad ff + fb"][1], means
    assert means["fitted ff + fb"][1] <= means["fb only"][1], "the feedforward never makes the board track worse than PD alone"
