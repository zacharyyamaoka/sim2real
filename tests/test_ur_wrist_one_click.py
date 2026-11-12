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
joint, friction on the output). The coordinator, the same evening, from the real lane: the rig LIES ON ITS SIDE (real up 94.7 deg from the
twin's z, a D405 floor-plane fit), so gravity's direction is a description parameter set from that vector, hidden tilted in the truth and
recovered (a mount tilt, as the five-bar's J1); CAN 14, vertical in the bundle, carries the wrist's ~0.25 N.m, and is driven now; the real
repeat floors (CAN 15 0.092 deg, CAN 16 0.241, CAN 14 0.100, driven, 5 same-input repeats) anchor the noise model's 1x.

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
MOVING = ("can14", "can15", "can16")
REAL_FLOOR_DEG = {"can14": 0.100, "can15": 0.092, "can16": 0.241}  # the real lane's repeat floors, driven (bam_ws claude/ur-wrist-real @ 6e26aa27a)
ARCMIN = math.pi / (180 * 60)
# the mutation run: CAN 15's backlash 50 % past the committed truth (its tolerance is 10 %), the ruler unchanged
MOVED_KEY = "can15.backlash_rad"


def manifest() -> dict:
    return json.loads((EXAMPLE / "description.json").read_text())


def world() -> dict:
    return json.loads((EXAMPLE / "world.json").read_text())


def within(value, truth, rule) -> bool:
    kind, tol = rule
    # the seam's rule (sim2real.rig: a part in 1e9 of slack, so binary floating point cannot fail a value exactly one tolerance away:
    # |0.8 ms - 0.6 ms| reads 2.0000000000000001e-4 against 2e-4)
    return value is not None and math.isfinite(value) and abs(value - truth) <= (tol if kind == "abs" else tol * abs(truth)) * (1.0 + 1e-9)


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
    # backlash, the joint zero (homing), the mount tilt, the dynamics and the command delay, each a routine in the sequence
    assert {"servo.backlash_reversal_held", "servo.breakaway_two_sided", "homing.single_touch", "arm.gravity_direction",
            "servo.dynamics_regression", "servo.command_delay_scan"} <= set(ids)
    assert ids.index("servo.backlash_reversal_held") < ids.index("homing.single_touch"), "homing corrects its stall by half the gap"
    assert ids.index("servo.backlash_reversal_held") < ids.index("servo.breakaway_two_sided"), "the breakaway's walk crosses the measured gap"
    assert ids.index("servo.breakaway_two_sided") < ids.index("servo.dynamics_regression"), "the dynamics hold the breakaway it measured"
    assert ids.index("servo.dynamics_regression") < ids.index("arm.gravity_direction"), "the direction is read off the load the dynamics found"


def test_every_hidden_value_is_a_row_identified_or_said_why_not(twin):
    params = {p.key: p for p in twin.runner.rig.parameters()}
    assert set(world()["truth"]) <= set(params), set(world()["truth"]) - set(params)
    for key, p in params.items():
        if p.routine is None:
            assert p.why_not, f"{key}: an unidentified parameter says why"
        else:
            assert p.tolerance is not None and p.tolerance_source, f"{key}: an identified parameter has a tolerance and its source"
    # every joint is driven: each servo's own terms are identified
    for can in MOVING:
        for name in ("axis_inertia_kg_m2", "coulomb_nm", "static_friction_nm", "damping_nm_s_rad", "backlash_rad", "zero_offset_rad"):
            assert params[f"{can}.{name}"].routine is not None, f"{can}.{name}"
        # only the axis inertia is seen: the armature apart from the links it turns is not (the CAD links are a prior the masses move)
        assert params[f"{can}.armature_kg_m2"].routine is None and "axis inertia" in params[f"{can}.armature_kg_m2"].why_not
    assert params["wrist.command_delay_s"].routine == "servo.command_delay_scan"
    # the breakaway is measured where it happens (both ways from a held flank), not read off refit's onset percentile, which a gear's gap
    # flattens: the gap's crossings start at ~0 N.m
    for can in MOVING:
        assert params[f"{can}.static_friction_nm"].routine == "servo.breakaway_two_sided"
        assert params[f"{can}.backlash_rad"].routine == "servo.backlash_reversal_held"
    # on its side, CAN 14 carries the wrist's gravity and 15 / 16 next to none: only CAN 14's is identified, the others say why
    assert params["can14.gravity_nm"].routine == "servo.dynamics_regression"
    for can in ("can15", "can16"):
        assert params[f"{can}.gravity_nm"].routine is None and "noise" in params[f"{can}.gravity_nm"].why_not
    assert params["wrist.gravity_azimuth_rad"].routine == "arm.gravity_direction"
    # near 90 deg CAN 14's load goes as sin(polar): flat, so the polar angle is said, not faked
    assert params["wrist.gravity_polar_rad"].routine is None and "sin(polar)" in params["wrist.gravity_polar_rad"].why_not


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


def test_gravity_is_the_measured_up_and_the_truth_tilts_it(twin):
    floor = json.loads(Path("/archive/datasets/bam_rig/rack_2026-11-10/ur_wrist/camera/floor_gravity_a/floor.json").read_text())
    nominal = {k: float(v) for k, v in twin.description.values().items() if v is not None}
    from sysid.examples.ur_wrist_test_rig import rig as wr  # noqa: PLC0415

    up = wr.up_vector(nominal["wrist.gravity_polar_rad"], nominal["wrist.gravity_azimuth_rad"])
    measured = np.asarray(floor["up_base"], float) / np.linalg.norm(floor["up_base"])
    assert np.degrees(np.arccos(np.clip(up @ measured, -1, 1))) < 1e-6, "the description's up is the floor-plane fit's"
    assert math.degrees(nominal["wrist.gravity_polar_rad"]) == pytest.approx(floor["angle_between_up_and_twin_world_z_deg"], abs=1e-6)
    truth = world()["truth"]
    tilt = np.degrees(np.arccos(np.clip(wr.up_vector(truth["wrist.gravity_polar_rad"], truth["wrist.gravity_azimuth_rad"]) @ up, -1, 1)))
    assert 1.0 < tilt < 5.0, "the hidden mount tilt is a few degrees off the measured up"
    # the rig's derived gravity rows are what MuJoCo gives for world.json's masses under world.json's gravity
    derived = twin.runner.rig.derived({**nominal, **truth})
    for key in ("can14.gravity_nm", "can14.gravity_bottom_rad"):
        assert derived[key] == pytest.approx(truth[key], rel=1e-9, abs=1e-12)
    assert 0.2 < truth["can14.gravity_nm"] < 0.35, "on its side CAN 14 carries the wrist (the real lane: ~0.23 N.m)"


def test_can14s_frozen_plans_are_the_coverage_builders(twin):
    """CAN 14's plans (plans_can14.json) are exactly what bam_ur_wrist_coverage.plans builds with CAN 14 let move: frozen, never edited."""
    from sysid.examples.ur_wrist_test_rig import rig as wr  # noqa: PLC0415

    frozen = json.loads((EXAMPLE / "plans_can14.json").read_text())["steps"]
    assert frozen == json.loads(json.dumps(wr.can14_plans_built()))


def test_the_noise_model_at_one_is_the_real_wrists(twin):
    noise = twin.noise()
    assert isinstance(noise, seam.NoiseModel) and noise.level == 1.0
    terms = noise.effective()
    # the real runs' smallest position step (rack_2026-11-10/ur_wrist/coverage/real/ram): 2 pi / 65536 rad
    assert terms["encoder_quantum_rad"] == pytest.approx(2 * math.pi / 65536, rel=1e-6)
    # the real host loop: median 10.57 ms, mean 10.71 ms over the same runs; overrun = the mean past the plan's 10 ms tick
    assert terms["period_overrun_s"] == pytest.approx(0.71e-3, rel=0.1)
    assert terms["torque_noise_nm"] > 0.0
    # the unmeasured terms are set by the floor anchor (test_the_sims_repeat_floor_at_one_is_the_real_floor), and say so
    assert "anchor" in noise.sources["latency_jitter_s"] and "anchor" in noise.sources["torque_disturbance_nm"]
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


def test_the_gap_is_read_by_the_five_bar_lanes_estimator(twin):
    """The coordinator, 2026-11-11: reuse the mount lane's backlash routine, don't re-implement it. Both rigs read a dead band with one
    function, bam_fb_test_rig.backlash.dead_band; the wrist drives its reversal under the position loop (the rig's WHY)."""
    from sysid.examples.ur_wrist_test_rig import plant as wp
    from sysid.examples.ur_wrist_test_rig import rig as wr

    assert wp.FIVEBAR_TEST_RIG is not None, "bam_fb_test_rig.backlash is on bam_ws main or the mount lane's worktree"
    import bam_fb_test_rig.backlash as fb

    values = {**twin.runner.rig.nominal_values(), "can15.backlash_rad": 15.0 * ARCMIN}
    run = next(r for r in wr.BacklashReversal().runs(values) if r.spec["can"] == 15)
    rec = wr.play({"kind": "reversal", "spec": run.spec, "values": values, "noise": {}, "seed": None})
    estimate = wr.BacklashReversal().fit({run.id: rec}, values, None)["can15.backlash_rad"]
    band = fb.dead_band(rec["q"], rec["tau"], threshold_nm=wr.DEAD_BAND_THRESHOLD_FRACTION * run.spec["cap_nm"],
                        mesh_stiffness_nm_per_rad=wr.MESH_STIFFNESS_NM_PER_RAD)
    assert estimate.value == band.backlash_rad and "bam_fb_test_rig.backlash.dead_band" in estimate.method


def test_the_breakaway_reads_the_static_friction_from_both_sides(twin):
    """servo.breakaway_two_sided on a noise-free world whose CAN 15 breaks away at a set level: the two caps' mean, within 2 %."""
    rig = twin.runner.rig
    for static in (0.12, 0.24):
        found = rig.breakaway_check(static_nm=static)
        assert abs(found - static) <= 0.02 * static, (found, static)


def test_the_gap_prior_is_the_gearboxs_datasheet(twin):
    """The GIM4305-10's rated 15 arcmin (SteadyWin, robotparts' record) is every joint's prior, and every hidden gap is set apart from it."""
    params = manifest()["parameters"]
    for can in MOVING:
        prior = params[f"{can}.backlash_rad"]
        assert abs(prior["value"] - 15.0 * ARCMIN) < 1e-12 and "GIM4305-10" in prior["source"]
        assert abs(world()["truth"][f"{can}.backlash_rad"] - prior["value"]) >= 1.5 * ARCMIN


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


@pytest.mark.skipif(not SLOW, reason="the floor repeats take minutes: SIM2REAL_SLOW=1")
def test_the_sims_repeat_floor_at_one_is_the_real_floor(twin):
    """The noise model's 1x is anchored to the real lane's repeat floors: each joint's floor tape (+-10 deg out and back) five times under
    independent draws, the median pairwise RMS, within 2x of the real one per joint."""
    rig = twin.runner.rig
    floors = rig.floor_check(twin.noise())
    print({k: round(v, 4) for k, v in floors.items()}, flush=True)
    for joint, real in REAL_FLOOR_DEG.items():
        assert real / 2.0 <= floors[joint] <= 2.0 * real, (joint, floors[joint], real)


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
