"""The UR wrist test rig on the one-click seam: Twin.load("ur_wrist_test_rig").calibrate(on="sim", truth="sealed") runs the wrist's whole
calibration sequence in sim against a sealed hidden truth, and recovers it; eval_twin() scores the fitted twin held out over the sim's own
repeat floor; result().display() shows it.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_ur_wrist_one_click.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src:/home/bam/dataclass_values/src systemd-run --user --scope -p MemoryMax=24G -- /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_ur_wrist_one_click.py

Zach (2026-11-11): "now that we have realistic sim models of the wrist and 5 bar ... verify that you can basically get perfect calibration by
applying noise to the sim vs sim w/ noise ... once you can prove that the entire routine recovers perfectly (and you stress test it with
different levels of noise) then we run that routine in reality." And, the same day: "backlash calibration is definitely something we want to
be detecting and measuring, so we need to actually include this in the routine"; homing (the joint zero) is one of the routines; "we certainly
need final tool error sub 1 mm".

The wrist (bam_ws src/dev/bam_ur_wrist): CAN 14/15/16, SteadyWin GIM4305-10 (10:1, encoder on the ROTOR) on moteus C1, the coverage lane's
twin of record it5 (Karnopp Coulomb + 0.6 ms command delay + the gravity refit's masses), with gear backlash added (gear_backlash's double
joint, friction on the output). CAN 14 is HELD (Zach's cable rule): no routine moves it, so its terms are listed unidentified, never faked.

The oracles are read here, never from the code under test: the hidden truth from sysid/examples/ur_wrist_test_rig/world.json, the units from
the description's manifest, the real noise floor's numbers from the archive's own runs.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

pytest.importorskip("bam_rack_twin", reason="the wrist's twin runs under bam_rack_twin's venv (moteus_servo, cad2robot_payload, MuJoCo 3.11)")
pytest.importorskip("mujoco")

import numpy as np  # noqa: E402
from robot_msgs.space import Value  # noqa: E402

import sim2real  # noqa: E402
from sim2real import rig as seam  # noqa: E402
from sim2real.cards import domain as dm  # noqa: E402
from sim2real.cards import registry as reg  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
NAME = "ur_wrist_test_rig"
EXAMPLE = REPO / "sysid" / "examples" / NAME
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
CAPTURE = os.environ.get("SIM2REAL_CAPTURE")  # a folder: the slow runs write their documents there (the report reads them)
WORKERS = int(os.environ.get("SIM2REAL_WORKERS", "4"))
MOVING = ("can15", "can16")
ARCMIN = math.pi / (180 * 60)
# the mutation run: CAN 15's backlash 50 % past the committed truth (its tolerance is 10 %), the ruler unchanged
MOVED_KEY = "can15.backlash_rad"


def manifest() -> dict:
    return json.loads((EXAMPLE / "description.json").read_text())


def world() -> dict:
    return json.loads((EXAMPLE / "world.json").read_text())


def within(value, truth, rule) -> bool:
    kind, tol = rule
    return value is not None and math.isfinite(value) and abs(value - truth) <= (tol if kind == "abs" else tol * abs(truth))


@pytest.fixture(scope="module")
def twin():
    return sim2real.Twin.load(NAME, workers=WORKERS)


# --- the description: typed instances, every value with its unit and source ----------------------------------------------------------


def test_the_wrist_is_a_composition_of_typed_instances(twin):
    types = {i.id: i.type for i in twin.description.instances}
    assert types["wrist"] == "rigid_body_chain"
    for can in ("can14", "can15", "can16"):
        assert types[can] == "integrated_servo", "each of the three joints is an integrated servo"
        for part, tid in (("motor", "bldc_motor"), ("gearbox", "gearbox"), ("driver", "foc_controller"), ("encoder", "encoder")):
            assert types[f"{can}_{part}"] == tid
            assert twin.description.instance(f"{can}_{part}").parent == can
        assert twin.description.instance(can).parent == "wrist"
    assert twin.description.instance("rig").structural == "deployment"
    units = {k: v["unit"] for k, v in manifest()["parameters"].items()}
    values = twin.description.values()
    assert set(values) == set(units)
    for key, value in values.items():
        assert isinstance(value, Value), key
        assert value.unit == units[key] and value.source, key


def test_the_runner_is_the_seam_and_every_routine_is_a_registered_one(twin):
    assert isinstance(twin.runner, seam.RigRunner)
    rig = twin.runner.rig
    ids = [r.id for r in rig.routines()]
    known = {r.id for r in reg.ROUTINES}
    assert set(ids) <= known, set(ids) - known
    # backlash, the joint zero (homing), the dynamics and the command delay: Zach's four, each a routine in the sequence
    assert {"servo.backlash_reversal_held", "homing.single_touch", "servo.dynamics_regression", "servo.command_delay_scan"} <= set(ids)
    assert ids.index("servo.backlash_reversal_held") < ids.index("homing.single_touch"), "homing corrects its stall by half the gap"


def test_every_hidden_value_is_a_row_identified_or_said_why_not(twin):
    params = {p.key: p for p in twin.runner.rig.parameters()}
    assert set(world()["truth"]) <= set(params), set(world()["truth"]) - set(params)
    for key, p in params.items():
        if p.routine is None:
            assert p.why_not, f"{key}: an unidentified parameter says why"
        else:
            assert p.tolerance is not None and p.tolerance_source, f"{key}: an identified parameter has a tolerance and its source"
    # CAN 14 is held by Zach's cable rule: no routine moves it, so none of its servo terms is identified
    for name in ("armature_kg_m2", "coulomb_nm", "static_friction_nm", "backlash_rad", "zero_offset_rad"):
        assert params[f"can14.{name}"].routine is None and "held" in params[f"can14.{name}"].why_not
    for can in MOVING:
        for name in ("armature_kg_m2", "coulomb_nm", "static_friction_nm", "backlash_rad", "zero_offset_rad"):
            assert params[f"{can}.{name}"].routine is not None, f"{can}.{name}"
    assert params["wrist.command_delay_s"].routine == "servo.command_delay_scan"


def test_the_hidden_truth_is_set_apart_from_nominal(twin):
    nominal = {k: (None if v is None else float(v)) for k, v in twin.description.values().items()}
    truth = world()["truth"]
    for p in twin.runner.rig.parameters():
        if p.routine is None or p.key not in truth:
            continue
        assert not within(nominal[p.key] or 0.0, truth[p.key], p.tolerance), f"{p.key}: the nominal must fail its own tolerance"
    # Zach's ask: 10-20 arcmin of backlash per joint
    for can in ("can14", "can15", "can16"):
        assert 10.0 <= truth[f"{can}.backlash_rad"] / ARCMIN <= 20.0


def test_the_noise_model_at_one_is_the_real_wrists(twin):
    noise = twin.noise()
    assert isinstance(noise, seam.NoiseModel) and noise.level == 1.0
    terms = noise.effective()
    # the real runs' smallest position step (rack_2026-11-10/ur_wrist/coverage/real/ram): 2 pi / 65536 rad
    assert terms["encoder_quantum_rad"] == pytest.approx(2 * math.pi / 65536, rel=1e-6)
    # the real host loop: median 10.57 ms, mean 10.71 ms over the same runs; overrun = the mean past the plan's 10 ms tick
    assert terms["period_overrun_s"] == pytest.approx(0.71e-3, rel=0.1)
    assert terms["torque_noise_nm"] > 0.0 and terms["latency_jitter_s"] > 0.0
    for term in seam.NoiseModel.TERMS:
        assert noise.sources.get(term), f"{term} says where its 1x value comes from"


# --- the plant: the it5 twin plus gear_backlash's double joint ------------------------------------------------------------------------


def test_the_backlash_plant_with_no_gap_is_the_twin_of_record(twin):
    rig = twin.runner.rig
    a, b = rig.plant_check(seconds=1.5)
    assert np.allclose(a, b, atol=1e-9), np.max(np.abs(a - b))


def test_the_held_reversal_reads_a_gap_from_the_motor_encoder_alone(twin):
    rig = twin.runner.rig
    gap = 15.0 * ARCMIN
    found = rig.reversal_check(gap_rad=gap)
    assert abs(found - gap) <= 0.05 * gap, (found / ARCMIN, gap / ARCMIN)


# --- the one click, end to end (slow) --------------------------------------------------------------------------------------------------


def _capture(name: str, fitted, report) -> None:
    if not CAPTURE:
        return
    folder = Path(CAPTURE)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"calibration": fitted.calibration_.to_dict(), "report": report.to_dict()}, indent=1, default=str))


@pytest.fixture(scope="module")
def green(twin):
    if not SLOW:
        pytest.skip("the wrist's whole sequence takes tens of minutes: SIM2REAL_SLOW=1")
    fitted = twin.calibrate(on="sim", truth="sealed")
    print(fitted.calibration_.summary(), flush=True)
    report = fitted.eval_twin()
    print(report.summary(), flush=True)
    _capture("green", fitted, report)
    return fitted, report


def test_one_click_recovers_every_identifiable_hidden_value(green, twin):
    fitted, _ = green
    cal = fitted.calibration_
    truth = world()["truth"]
    assert fitted is not twin and not twin.fitted
    params = {p.key: p for p in twin.runner.rig.parameters()}
    rows = {r["key"]: r for r in cal.rows}
    missed = {}
    for key, p in params.items():
        if p.routine is None:
            assert rows[key]["recovered"] is None, f"{key} is not identified, so nothing is reported for it"
            continue
        if key in truth and not within(rows[key]["recovered"], truth[key], p.tolerance):
            missed[key] = (rows[key]["recovered"], truth[key])
    assert not missed, f"outside tolerance of the hidden truth: {missed}"
    assert cal.passed, cal.summary()
    for key in (f"{can}.backlash_rad" for can in MOVING):
        assert rows[key]["ci95"] is not None, f"{key} carries its 95 % interval"


def test_one_click_twin_is_twinned_held_out_and_meets_the_tool_gate(green):
    _, report = green
    gates = {g.id: g for g in report.gates}
    assert {"twinned", "recovery", "tool_at_stops"} <= set(gates)
    for can in MOVING:
        assert report.ratios["fitted"][can] <= reg.TWINNED_LIMIT, (can, report.ratios["fitted"][can])
        assert report.ratios["nominal"][can] > report.ratios["fitted"][can]
    assert report.tool_stop_m["fitted"] <= 1e-3, "Zach: final tool error sub 1 mm"
    assert report.passed, report.summary()


def test_the_result_page_is_the_typed_tree(green, tmp_path):
    fitted, _ = green
    result = fitted.result()
    ids = [n.id for n in result.nodes]
    assert ids[0] == "rig" and any(i.endswith("/can15") for i in ids) and any(i.endswith("/holder") for i in ids)
    assert all(n.floor_deg for n in result.nodes if n.id.endswith(("/can15", "/can16")))
    kit = REPO / "vendor" / "data-ui" / "dist" / "data-ui.js"
    if kit.exists():
        assert Path(result.display(tmp_path / "page", open=False)).exists()


@pytest.mark.skipif(not SLOW, reason="the wrist's whole sequence takes tens of minutes: SIM2REAL_SLOW=1")
def test_a_moved_truth_turns_its_row_and_the_recovery_gate_red(twin):
    truth = world()["truth"][MOVED_KEY]
    fitted = twin.calibrate(on="sim", truth="sealed", move_truth={MOVED_KEY: truth * 1.5})
    cal = fitted.calibration_
    print(cal.summary(), flush=True)
    report = fitted.eval_twin()
    print(report.summary(), flush=True)
    _capture("red", fitted, report)
    assert MOVED_KEY in cal.failing and not cal.passed
    assert not report.passed and "recovery" in [g.id for g in report.gates if not g.passed]
