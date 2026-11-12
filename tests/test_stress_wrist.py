"""The wrist's one-click under stress (tools/stress_wrist.py): the ladders are the brief's, each single-term ladder moves only its own
noise terms, the far truth stays physical, the motor-side friction is in the world and not in the twin, and the breaking point is the
first level where any seed misses. The slow part pins the 1x: on three fixed seeds, every identifiable hidden value is recovered within
its tolerance and every gate passes.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_stress_wrist.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src systemd-run --user --scope -p MemoryMax=24G -p OOMPolicy=continue -- /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_stress_wrist.py

Zach (2026-11-11): "once you can prove that the entire routine recovers perfectly (and you stress test it with different levels of noise)
then we run that routine in reality." The coordinator's brief, the same evening: overall noise 0-10x, torque / encoder+velocity / timing
alone, the truth's distance from nominal, and a motor-side friction the model lacks; 3 seeds a level; a red-first pin of the 1x.

The oracle is read here, never from the tool or the seam's verdict: the hidden truth from sysid/examples/ur_wrist_test_rig/world.json, the
tolerances from the rig's parameter table (the use's), the 1x noise from the rig itself.
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("bam_rack_twin", reason="the wrist's twin runs under bam_rack_twin's venv (moteus_servo, cad2robot_payload, MuJoCo 3.11)")
pytest.importorskip("mujoco")

import sim2real  # noqa: E402
from sim2real import rig as seam  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import stress_wrist as sw  # noqa: E402

NAME = "ur_wrist_test_rig"
EXAMPLE = REPO / "sysid" / "examples" / NAME
GREEN = REPO / "src" / "sim2real" / "data" / "ur_wrist_one_click_2026-11-11.json"   # the one-click lane's 1x green run (seed 20261111)
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
SEEDS = (20261111, 20261112, 20261113)
PARALLEL = int(os.environ.get("STRESS_WRIST_PARALLEL", "3"))
WORKERS = int(os.environ.get("STRESS_WRIST_WORKERS", "6"))
OUT = os.environ.get("STRESS_WRIST_OUT")   # a folder: the slow cells are written there (the ladder reuses them); else a tmp folder


def world() -> dict:
    return json.loads((EXAMPLE / "world.json").read_text())


def within(value, truth, rule) -> bool:
    kind, tol = rule
    # the seam's rule (a part in 1e9 of slack, so binary floating point cannot fail a value exactly one tolerance away)
    return value is not None and math.isfinite(value) and abs(value - truth) <= (tol if kind == "abs" else tol * abs(truth)) * (1.0 + 1e-9)


def missed(record: dict, truth: dict, params: dict) -> dict:
    """Every identified parameter whose recovered value is outside its tolerance of ``truth`` (or missing): {key: (recovered, truth)}."""
    rows = {r["key"]: r for r in record["calibration"]["rows"]}
    out = {}
    for key, p in params.items():
        if p.routine is None or key not in truth:
            continue
        recovered = rows.get(key, {}).get("recovered")
        if not within(recovered, truth[key], p.tolerance):
            out[key] = (recovered, truth[key])
    return out


@pytest.fixture(scope="module")
def twin():
    return sim2real.Twin.load(NAME, workers=1)


@pytest.fixture(scope="module")
def params(twin):
    return {p.key: p for p in twin.runner.rig.parameters()}


# --- the ladders are the brief's -----------------------------------------------------------------------------------------------------


def test_the_ladders_are_the_briefs():
    assert list(sw.LADDERS) == ["overall", "torque", "encoder", "timing", "truth", "mismatch"]
    assert sw.LADDERS["overall"].levels == (0, 1, 2, 3, 5, 10)
    assert sw.LADDERS["torque"].levels == (1, 3, 10)
    assert sw.LADDERS["encoder"].levels == (1, 3, 10)
    assert sw.LADDERS["timing"].levels == (0, 1, 3)
    assert sw.LADDERS["truth"].levels == (1, 2, 3)
    assert sw.LADDERS["mismatch"].levels[0] == 0 and len(sw.LADDERS["mismatch"].levels) >= 3
    assert len(sw.SEEDS) >= 3 and sw.SEEDS[0] == 20261111, "three fixed seeds, the one-click lane's own first"


def test_the_overall_ladder_is_every_term_times_its_level(twin):
    base = twin.noise()
    for level in sw.LADDERS["overall"].levels:
        noise = sw.noise_for("overall", level, 7, base)
        assert noise.seed == 7 and noise.truth_offset == 1.0
        for term, value in noise.effective().items():
            assert value == pytest.approx(level * base.effective()[term], rel=1e-12, abs=0.0), (level, term)


def test_each_single_term_ladder_moves_only_its_own_terms(twin):
    base = twin.noise()
    owned = {"torque": {"torque_noise_nm", "torque_disturbance_nm"},
             "encoder": {"encoder_quantum_rad", "encoder_noise_rad", "velocity_noise_rad_s"},
             "timing": {"period_overrun_s", "latency_jitter_s"}}
    for ladder, terms in owned.items():
        assert set(sw.LADDERS[ladder].terms) <= terms, ladder
        for level in sw.LADDERS[ladder].levels:
            noise = sw.noise_for(ladder, level, 7, base)
            moved = {t for t in base.TERMS if noise.effective()[t] != base.effective()[t]}
            assert moved <= terms, (ladder, level, moved)
            if level == 1:
                assert moved == set(), (ladder, "level 1 is the rig's 1x")
        # the term the ladder is about really moves
        top = sw.noise_for(ladder, max(sw.LADDERS[ladder].levels), 7, base)
        assert any(top.effective()[t] > base.effective()[t] for t in terms), ladder


def test_level_one_of_every_noise_ladder_is_the_one_click_1x(twin):
    base = twin.noise()
    for ladder in ("overall", "torque", "encoder", "timing", "truth", "mismatch"):
        level = 0 if ladder == "mismatch" else 1
        noise = sw.noise_for(ladder, level, 20261111, base)
        assert noise.effective() == base.effective() and noise.truth_offset == 1.0, ladder
        assert sw.variant_for(ladder, level) == {}, f"{ladder} at {level} plays the committed world"


def test_the_far_truth_is_the_seams_ruler_at_one_and_physical_at_every_level(twin):
    nominal = twin.runner.nominal()
    truth = world()["truth"]
    seams = seam.ruler(truth, nominal, twin.noise())
    for level in sw.LADDERS["truth"].levels:
        far, clamped = sw.far_truth(truth, nominal, level)
        for key, value in far.items():
            if level == 1:
                assert value == pytest.approx(seams[key], rel=1e-12, abs=1e-15), key
            elif key not in clamped:
                prior = nominal.get(key)
                expected = truth[key] if prior is None else prior + level * (truth[key] - prior)
                assert value == pytest.approx(expected, rel=1e-12, abs=1e-15), key
        for can in (14, 15, 16):
            assert far[f"can{can}.damping_nm_s_rad"] >= 0.0
            assert far[f"can{can}.static_friction_nm"] >= far[f"can{can}.coulomb_nm"] > 0.0
            assert far[f"can{can}.backlash_rad"] > 0.0 and far[f"can{can}.armature_kg_m2"] > 0.0
        assert far["wrist.command_delay_s"] >= 0.0
        assert level > 1 or not clamped
    # the seam's own knob leaves the physical domain past 1 (why this ladder clamps): every damping and the delay go negative at 2
    at2 = seam.ruler(truth, nominal, twin.noise().with_terms(truth_offset=2.0))
    assert all(at2[f"can{c}.damping_nm_s_rad"] < 0.0 for c in (14, 15, 16)) and at2["wrist.command_delay_s"] < 0.0


def test_the_motor_friction_is_in_the_world_and_not_in_the_twin(twin):
    nominal = twin.runner.rig.nominal_values()
    values = {**nominal, **world()["truth"]}
    with sw.motor_friction(0.02):
        from sysid.examples.ur_wrist_test_rig import rig as wr  # noqa: PLC0415

        start = wr._rest_cad()
        world_plant = wr.build_plant(values, start, noise=twin.noise().effective(), seed=[1, 2, 3])
        twin_plant = wr.build_plant(values, start)
    for plant, expected in ((world_plant, 0.02), (twin_plant, 0.0)):
        motors = plant.wrist.dof_adr[plant.wrist.wrapped]
        assert len(motors) == 3, "every joint is geared in the truth"
        assert list(plant.model.dof_frictionloss[motors]) == [expected] * 3
    from sysid.examples.ur_wrist_test_rig import rig as wr  # noqa: PLC0415

    after = wr.build_plant(values, wr._rest_cad(), noise={}, seed=[1, 2, 3])
    assert list(after.model.dof_frictionloss[after.wrist.dof_adr]) == [0.0] * 3, "the patch is undone on exit"


# --- the verdicts ----------------------------------------------------------------------------------------------------------------------


def test_the_pin_catches_a_value_outside_its_tolerance(params):
    """The slow pin's own check, mutated: the committed 1x green run passes it, and the same run with one value moved past its tolerance
    does not (a ruler that cannot fail proves nothing)."""
    green = json.loads(GREEN.read_text())
    truth = world()["truth"]
    assert missed(green, truth, params) == {}
    moved = copy.deepcopy(green)
    row = next(r for r in moved["calibration"]["rows"] if r["key"] == "can16.coulomb_nm")
    row["recovered"] = truth["can16.coulomb_nm"] * 1.11
    assert set(missed(moved, truth, params)) == {"can16.coulomb_nm"}


def test_the_breaking_point_is_the_first_level_where_any_seed_misses():
    def record(level, seed, fails):
        rows = [{"key": k, "pass": k not in fails, "routine": "r", "error": 2.0 if k in fails else 0.1,
                 "tolerance": {"kind": "abs", "value": 1.0}, "true": 0.0, "recovered": 0.0} for k in ("a", "b", "c")]
        return {"cell": {"ladder": "x", "level": level, "seed": seed}, "calibration": {"rows": rows, "passed": not fails}}

    records = [record(1, s, ()) for s in (1, 2, 3)] + [record(2, 1, ()), record(2, 2, ("b",)), record(2, 3, ())] + \
              [record(3, s, ("a", "b")) for s in (1, 2, 3)]
    broken = sw.breaking_point(records)
    assert broken["level"] == 2 and broken["params"] == ["b"] and broken["seeds"] == {"b": [2]}
    assert sw.breaking_point([record(1, s, ()) for s in (1, 2, 3)])["level"] is None
    # a calibration that raised is a miss at its level, named by the routine that raised
    raised = {"cell": {"ladder": "x", "level": 2, "seed": 3}, "error": "ValueError: CAN 15: not observable", "routine": "servo.backlash_reversal_held"}
    broken = sw.breaking_point([record(1, s, ()) for s in (1, 2, 3)] + [record(2, 1, ()), record(2, 2, ()), raised])
    assert broken["level"] == 2 and broken["params"] == ["raised in servo.backlash_reversal_held"]


# --- the 1x pin, three seeds (slow) ------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def one_x(tmp_path_factory):
    if not SLOW:
        pytest.skip("three whole calibrations, ~10 min each in parallel: SIM2REAL_SLOW=1")
    out = Path(OUT) if OUT else tmp_path_factory.mktemp("stress_wrist")
    cells = [sw.Cell("overall", 1, seed) for seed in SEEDS]
    records = sw.run_cells(cells, out=out, parallel=PARALLEL, workers=WORKERS, reuse=False)
    for record in records:
        print(record.get("summary", record.get("error")), flush=True)
    return records


def test_1x_recovers_every_identifiable_hidden_value_on_every_seed(one_x, twin, params):
    truth = world()["truth"]
    base = twin.noise()
    assert [r["cell"]["seed"] for r in one_x] == list(SEEDS)
    misses = {}
    for record in one_x:
        assert "error" not in record, record.get("error")
        noise = seam.NoiseModel.from_dict(record["calibration"]["noise"])
        assert noise.effective() == base.effective() and noise.truth_offset == 1.0, "the rig's own 1x, the committed truth"
        assert noise.seed == record["cell"]["seed"]
        assert record["variant"] == {}
        bad = missed(record, truth, params)
        if bad:
            misses[record["cell"]["seed"]] = bad
    assert not misses, f"outside tolerance of the hidden truth, per seed: {misses}"
    assert all(r["calibration"]["passed"] for r in one_x)


def test_1x_meets_every_gate_on_every_seed(one_x):
    for record in one_x:
        report = record["report"]
        gates = {g["id"]: g["passed"] for g in report["gates"]}
        assert gates == {"twinned": True, "recovery": True, "tool_at_stops": True}, (record["cell"]["seed"], gates)
        assert max(report["ratios"]["fitted"].values()) <= 1.5
        assert report["tool_stop_m"]["fitted"] <= 1e-3, "Zach: final tool error sub 1 mm"
