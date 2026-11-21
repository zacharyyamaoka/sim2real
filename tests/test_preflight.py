"""sim2real.preflight(fitted): the "preflight / wear-in before shipping" check of a calibrated RobotTwin (Zach's 2026-11-19 pipeline, step 8).
Sim only. The CAN 11 pendulum is the golden case.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src taskset -c 2-5,16,17 nice -n 19 ionice -c3 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/tests/test_preflight.py
    env -u VIRTUAL_ENV SIM2REAL_SLOW=1 PYTHONPATH=/home/bam/sim2real/src taskset -c 2-5,16,17 nice -n 19 ionice -c3 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_preflight.py

The ruler, written before the code (red first); whoever turns it green may not edit it:

1. An unfitted twin raises, with evaluate()'s "fitted twin" wording.
2. preflight(fitted) returns a frozen Preflight: .checks (each Check(id, title, passed, value, limit, unit, why); passed None = "could not be
   checked", with its reason, never a pass), .passed (every blocking check True), .summary() and a JSON-ready .to_dict().
3. The checks: record_matches_description, gains_within_board_limits, torque_margin, sim_soak (blocking) and schedule_complete
   (informational: it reports, it never blocks).
4. The golden case passes every blocking check it can be checked for: CAN 11's twin from its description
   (bam_rack_twin.description.station_description(11)), fitted cheaply from the committed fit (sysid/results/pendulum_can11.json, the
   oracle's recovered values) and carrying the gains a tune step proposes, in the shape claude/l10-c's PidTune writes (fitted.settings_,
   fitted.proposals_: kp and kd at the output, the board's ki with ilimit 0).
   Amended 2026-11-21 for pidtuna contract amendment 3 (v2.3: no relative gain range by default; the gains are held by pidtuna's analytic
   bounds): the tune's kd is the one that puts the committed fit at damping 0.8 (pidtuna's Objective), since a tune never delivers outside
   its damping band and the old 1.2x the board's kd sits at 0.22, under the band's 0.65 floor (now its own mutation, below). Every piece
   the bounds read is stated and cited: CAN 11's encoder count and velocity filter from its board's recorded config (sim2real/data/
   board_configs.json, a copy of the moteus dump), its loop from the twin of record and the driver's datasheet, its velocity noise from
   the noise the calibrate records (the cheap fit records it as the real calibrate does); the structural mode, stated nowhere, is not
   applied (pidtuna §2 bounds a known one). So the golden case passes every blocking check again.
5. Each mutation turns its check red: a gain past a bound (5x kp: under the damping floor); the old golden gains, underdamped; an
   integrating ki; no tune (the board's as-found ki 16000, ilimit 0.5);
   a torque cap cut below the envelope (a robotparts datasheet whose peak is cut); a value with its source stripped; a soak on an unstable
   parameter. A twin with no parts cannot be checked for torque (None, naming the parts). A schedule that dropped a routine for missing
   equipment is None naming the items; one that excluded a routine the record needed is False.

The slow half (SIM2REAL_SLOW=1) fits CAN 11 end to end (about 36 min at one worker) and preflights the real fitted twin.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import math
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("bam_rack_twin", reason="the pendulum oracle runs under bam_rack_twin's venv (sysid's runtime)")
pytest.importorskip("mujoco", reason="the soak needs the sim extra")

from robot_msgs.space import Basis, Value  # noqa: E402

import sim2real  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SLOW = os.environ.get("SIM2REAL_SLOW") == "1"
TAU = 2.0 * math.pi
BLOCKING = ("record_matches_description", "gains_within_board_limits", "torque_margin", "sim_soak")
INFORMATIONAL = ("schedule_complete",)
# the board as it runs today: CAN 11's deployment record, moteus_config (N.m/rev at the output), read here, never from the code under test
RECORD = Path("/home/bam/bam_ws/src/dev/bam_rack_twin/records/one-dof-test-rack/deployment.json")


def board() -> dict:
    component = next(c for c in json.loads(RECORD.read_text())["components"] if c.get("can_id") == 11)
    return component["moteus_config"]


def committed_fit() -> dict:
    return json.loads((REPO / "sysid" / "results" / "pendulum_can11.json").read_text())


def _loaded():
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    return sim2real.RobotTwin.from_robot_description(station_description(11), workers=1)


def _cheap_fit(twin):
    """The fitted twin without the 36-minute fit: calibrate() runs as it always does, but its runner hands back the committed fit's values
    (sysid/results/pendulum_can11.json), so plan_, record_ and data_ are built by the twin's own code."""
    rows = committed_fit()["parameters"]
    values = {r["name"]: Value(float(r["recovered"]), r["unit"], basis=Basis.MEASURED, source=r["method"],
                               measured_by="sysid/results/pendulum_can11.json (the committed fit)") for r in rows}
    planned = twin.generate_schedule()
    recovered = {r["key"]: float(r["recovered"]) for r in rows}
    steps = [{"routine": s.routine, "identifies": list(s.identifies), "runs": 0, "seconds": 0.0,
              # WHY a tune step's keys are configured, never found (L10, 2026-11-20, applied for the One-click session, which owns this file and
              # was not running): pid.pidtuna lists kp / kd in identifies, but they are settings (settings_), so the committed fit has no
              # value for them and calibrate() records them under configures, the way PidTune's real step does
              "found": {k: recovered[k] for k in s.identifies if s.kind != "tune"},
              **({"configures": list(s.identifies)} if s.kind == "tune" else {})} for s in planned.steps]
    calibration = sim2real.twin.Calibration("sim", twin.model, "M4", values, {"M4": {k: float(v) for k, v in values.items()}}, rows, {}, 0.0,
                                            {"train_runs": 0, "held_out_runs": 0, "digest": "committed", "coverage_train_pct": 0.0,
                                             "routines": [s["routine"] for s in steps]})
    # WHY the world's noise block (amended 2026-11-21): the real calibrate records the noise the world played (world.json's block at the
    # ladder's scale, twin.py's TracerRunner.calibrate) and preflight's velocity-noise bound reads it; the cheap fit records it the same way
    world = json.loads((REPO / "sysid" / "examples" / "pendulum_can11" / "world.json").read_text())
    noise = {**world["noise"], "level": 1.0, "seed": world["seed"],
             "sources": {name: "sysid/examples/pendulum_can11/world.json noise block x1 (sysid.hidden.load)" for name in world["noise"]}}
    state = {"routines": steps, "noise": noise, "measured": SimpleNamespace(train={}, held_out={}, repeat={})}
    twin.runner.calibrate = lambda **_: (calibration, state)
    return twin.calibrate(on="sim", callbacks=[])


def in_band_kd_scale(kp_scale: float, zeta: float = 0.8) -> float:
    """The kd scale (on the board's kd) that puts the committed fit at damping `zeta` under kp_scale x the board's kp: kd = 2 zeta wn J - b,
    wn = sqrt(kp / J), from the committed fit's inertia and viscous (read here). WHY 0.8: pidtuna's Objective().damping_ratio, the middle
    of the band a tune delivers inside."""
    fit = {r["key"]: float(r["recovered"]) for r in committed_fit()["parameters"]}
    inertia, viscous = fit["can11.armature_kg_m2"], fit["can11.damping_nm_s_rad"]
    kp = board()["kp"] / TAU * kp_scale
    return (2.0 * zeta * math.sqrt(kp / inertia) * inertia - viscous) / (board()["kd"] / TAU)


def _tuned(fitted, *, kp_scale=1.3, kd_scale=None, ki=None, ilimit=0.0):
    """The fitted twin carrying the gains a tune step proposed, in claude/l10-c's shape (settings_ in SI at the output; proposals_ the
    pidtuna gains document, its `tuned` the board's ki with ilimit 0 by default). kd_scale None: the in-band kd (in_band_kd_scale)."""
    b = board()
    kd_scale = in_band_kd_scale(kp_scale) if kd_scale is None else kd_scale
    kp, kd = b["kp"] / TAU * kp_scale, b["kd"] / TAU * kd_scale
    ki = b["ki"] / TAU if ki is None else ki
    out = copy.copy(fitted)
    out.settings_ = {"can11.kp_nm_rad": kp, "can11.kd_nm_s_rad": kd}
    out.proposals_ = {"pid.pidtuna": {"schema": "pidtuna/gains-1", "tier": "sim", "joints": {"can11": {
        "joint": "can11", "can_id": 11, "tuned": {"gains_si": {"kp": kp, "kd": kd, "ki": ki, "ilimit": ilimit}}}}}}
    return out


@pytest.fixture(scope="module")
def loaded():
    return _loaded()


@pytest.fixture(scope="module")
def fitted():
    return _cheap_fit(_loaded())


@pytest.fixture(scope="module")
def golden(fitted):
    return _tuned(fitted)


@pytest.fixture(scope="module")
def golden_report(golden):
    return sim2real.preflight(golden)


def revalue(value, raw=None, **meta):
    """A robot_msgs Value with its raw number or metadata changed (a Value is an immutable float carrying meta, not a dataclass)."""
    merged = {**value.meta(), **meta}
    unit = merged.pop("unit")
    if raw is not None:
        merged["low"] = merged["high"] = None   # a moved value leaves its old interval
    return Value(float(value) if raw is None else float(raw), unit, **merged)


def check(report, check_id):
    found = [c for c in report.checks if c.id == check_id]
    assert len(found) == 1, f"one {check_id} check, got {[c.id for c in report.checks]}"
    return found[0]


# --- the contract -------------------------------------------------------------------------------------------------------------------


def test_an_unfitted_twin_raises(loaded):
    with pytest.raises(RuntimeError, match="fitted twin"):
        sim2real.preflight(loaded)


def test_the_report_is_a_frozen_value_with_every_check(golden_report):
    from sim2real.preflight import Check, Preflight  # noqa: PLC0415

    assert isinstance(golden_report, Preflight)
    with pytest.raises(dataclasses.FrozenInstanceError):
        golden_report.checks = ()
    assert [c.id for c in golden_report.checks] == [*BLOCKING, *INFORMATIONAL]
    for c in golden_report.checks:
        assert isinstance(c, Check) and c.title and c.why, c
        assert c.passed in (True, False, None)
    doc = golden_report.to_dict()
    assert json.loads(json.dumps(doc)) == doc, "to_dict() is JSON-ready"
    assert doc["passed"] is golden_report.passed and [c["id"] for c in doc["checks"]] == [*BLOCKING, *INFORMATIONAL]
    assert {"id", "title", "passed", "value", "limit", "unit", "why"} <= set(doc["checks"][0])
    text = golden_report.summary()
    assert all(i in text for i in (*BLOCKING, *INFORMATIONAL))


def test_the_callable_survives_importing_the_module(golden):
    import sim2real.preflight as module  # noqa: PLC0415

    assert callable(sim2real.preflight)
    assert module.Preflight is type(sim2real.preflight(golden, soak_s=0.5))


# --- the golden case ------------------------------------------------------------------------------------------------------------------


def test_the_can11_golden_case_passes_every_check(golden_report):
    failing = {c.id: (c.passed, c.why) for c in golden_report.checks if c.id in BLOCKING and c.passed is not True}
    assert not failing, failing
    assert golden_report.passed is True
    assert check(golden_report, "schedule_complete").passed is True, "CAN 11's default schedule drops and assumes nothing"
    assert "PASS" in golden_report.summary()


def test_the_torque_margin_reads_the_datasheet_cap(golden_report):
    torque = check(golden_report, "torque_margin")
    # JMC 60ASM200's peak (robotparts: JMC's drawing, 1.28 N.m) x the AD60-G10's 10:1 x 0.97 (the house cap)
    assert torque.limit == pytest.approx(1.28 * 10 * 0.97, rel=1e-6), torque
    assert torque.unit == "N·m" and 0.0 < torque.value < torque.limit
    assert "%" in torque.why and "margin" in torque.why


def test_none_never_counts_as_a_pass(golden):
    from sim2real.preflight import Check, Preflight  # noqa: PLC0415

    unknown = Preflight("t", (Check("x", "x", None, None, None, "", "could not be checked: no data"),), 0.0)
    assert unknown.passed is False


# --- each mutation turns its check red -------------------------------------------------------------------------------------------------


def test_a_gain_outside_its_limit_turns_gains_red(fitted):
    # amendment 3: 5x kp at the golden kd (not re-damped) leaves the damping floor; red for the bound it breaks, with its numbers
    report = sim2real.preflight(_tuned(fitted, kp_scale=5.0, kd_scale=in_band_kd_scale(1.3)), soak_s=0.5)
    gains = check(report, "gains_within_board_limits")
    assert gains.passed is False and "kp" in gains.why, gains
    assert "damping floor" in gains.why, gains.why
    assert report.passed is False


def test_the_old_golden_gains_are_underdamped_and_red(fitted):
    # 1.3x kp and 1.2x kd of the board (the golden gains before amendment 3): damping 0.22 on the committed fit, under pidtuna's 0.65 floor
    gains = check(sim2real.preflight(_tuned(fitted, kd_scale=1.2), soak_s=0.5), "gains_within_board_limits")
    floor = gains.limit["bounds"]["damping floor"]
    assert gains.passed is False and floor["passed"] is False and floor["value"] < floor["limit"], gains
    assert "damping floor" in gains.why, gains.why


def test_an_integrating_ki_turns_gains_red(fitted):
    report = sim2real.preflight(_tuned(fitted, ilimit=0.5), soak_s=0.5)
    gains = check(report, "gains_within_board_limits")
    assert gains.passed is False and "ki" in gains.why, gains


def test_no_tune_ships_the_boards_integrator_and_is_red(fitted):
    assert not getattr(fitted, "settings_", None), "the cheap fit ran no tune step"
    gains = check(sim2real.preflight(fitted, soak_s=0.5), "gains_within_board_limits")
    assert gains.passed is False and "ki" in gains.why, gains
    assert gains.value["ki_nm_rad_s"] == pytest.approx(board()["ki"] / TAU) and gains.value["ilimit_nm"] == board()["ilimit"]


def test_a_torque_cap_cut_below_the_envelope_turns_torque_red(golden, golden_report, tmp_path, monkeypatch):
    import sim2real.paths as paths  # noqa: PLC0415

    parts = tmp_path / "dist" / "site" / "v2" / "parts"
    parts.mkdir(parents=True)
    for part in Path(paths.ROBOTPARTS, "dist", "site", "v2", "parts").glob("*.json"):
        shutil.copy(part, parts / part.name)
    motor = parts / "jmc-60asm200-5-1024c.json"
    doc = json.loads(motor.read_text())
    peak = check(golden_report, "torque_margin").value
    doc["specs"]["peak_torque"]["value"] = 0.5 * peak / (10 * 0.97)   # the cap now half the envelope's peak
    motor.write_text(json.dumps(doc))
    monkeypatch.setattr(paths, "ROBOTPARTS", tmp_path)
    report = sim2real.preflight(golden)
    torque = check(report, "torque_margin")
    assert torque.passed is False and torque.limit == pytest.approx(0.5 * peak, rel=1e-6), torque
    assert check(report, "sim_soak").passed is False, "the soak's torque hits the cut cap"


def test_a_twin_without_parts_cannot_be_checked_for_torque(golden):
    bare = copy.copy(golden)
    bare.description = dataclasses.replace(golden.description,
                                           instances=tuple(dataclasses.replace(i, part=None) for i in golden.description.instances))
    torque = check(sim2real.preflight(bare, soak_s=0.5), "torque_margin")
    assert torque.passed is None and "part" in torque.why, torque


def test_a_value_with_its_source_stripped_turns_the_record_red(golden):
    stripped = copy.copy(golden)
    gravity = golden.parameters["can11"]["gravity_nm"]
    stripped.description = golden.description.with_values({"can11.gravity_nm": revalue(gravity, source="")})
    record = check(sim2real.preflight(stripped, soak_s=0.5), "record_matches_description")
    assert record.passed is False and "can11.gravity_nm" in record.why, record


def test_a_soak_on_an_unstable_parameter_turns_the_soak_red(golden):
    unstable = copy.copy(golden)
    inertia = golden.parameters["can11"]["armature_kg_m2"]
    # WHY an inertia 20x the fit and not a negative damping: the twin clamps damping at 0 (pipeline.twin), so a negative one mutates
    # nothing. Under the same kp and kd the loop's damping ratio falls to ~0.03: it rings, saturates and has not settled when the hold ends
    unstable.description = golden.description.with_values({"can11.armature_kg_m2": revalue(inertia, 20.0 * float(inertia))})
    soak = check(sim2real.preflight(unstable), "sim_soak")
    assert soak.passed is False, soak
    assert "settle" in soak.why or "guard" in soak.why, soak


def test_a_schedule_short_of_equipment_is_unknown_naming_the_items(golden, loaded):
    from sim2real.calibration import Budget, CalibrationConfig  # noqa: PLC0415

    short = copy.copy(golden)
    short.plan_ = loaded.generate_schedule(CalibrationConfig(budget=Budget(equipment=())))
    assert short.plan_.dropped, "with no equipment the schedule drops a routine"
    report = sim2real.preflight(short, soak_s=0.5)
    schedule = check(report, "schedule_complete")
    assert schedule.passed is None and "equipment" in schedule.why, schedule
    assert all(rid in schedule.why for rid, _ in short.plan_.dropped)


def test_a_schedule_that_excluded_a_needed_routine_is_red_but_does_not_block(golden, loaded):
    from sim2real.calibration import CalibrationConfig  # noqa: PLC0415

    cut = copy.copy(golden)
    cut.plan_ = loaded.generate_schedule(CalibrationConfig(exclude=("servo.backlash_reversals_camera",)))
    report = sim2real.preflight(cut, soak_s=0.5)
    schedule = check(report, "schedule_complete")
    assert schedule.passed is False and "servo.backlash_reversals_camera" in schedule.why, schedule
    assert all(c.passed is True for c in report.checks if c.id in BLOCKING) and report.passed is True, "informational: it never blocks"


# --- the slow half: the real fit ---------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(not SLOW, reason="the whole CAN 11 fit takes about 36 min at one worker: SIM2REAL_SLOW=1")
def test_the_real_can11_fit_preflights():
    real = _loaded().calibrate(on="sim", callbacks=[])
    report = sim2real.preflight(real)
    print(report.summary())
    tuned = bool(getattr(real, "settings_", None))
    for c in report.checks:
        if c.id == "gains_within_board_limits" and not tuned:
            # no tune step on this main: the board's as-found ki 16000 with ilimit 0.5 integrates, and PD-only refuses it
            assert c.passed is False and "ki" in c.why, c
        elif c.id == "sim_soak" and not tuned:
            # WHY (ruler fix, found on the cheap fit before this ran): the soak plays what would ship, the integrating board, and CAN 11
            # limit-cycles under ki 16000 (pipeline.py's docstring): its stop error and torque ceiling fail; the tune's PD passes
            assert c.passed is False, c
        elif c.id in BLOCKING:
            assert c.passed is True, c
    assert sim2real.preflight(_tuned(real) if not tuned else real).passed is True
