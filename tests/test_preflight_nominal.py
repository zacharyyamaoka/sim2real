"""sim2real.preflight(fitted) on a NOMINAL-world twin (sim2real.nominal: RobotTwin.from_robot_description of a description no sysid world
binds). Sim only, one worker.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src taskset -c 2-5,16,17 nice -n 19 ionice -c3 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_preflight_nominal.py

The ruler, written before the code (red first); whoever turns it green may not edit it. On the pendulum tracer path the three checks
gains_within_board_limits, sim_soak and torque_margin read the tracer's runner (runner.typed(), runner.sysid_description()); a nominal twin's
RigRunner has neither, so they came back None. Here they must be ANSWERED:

1. CAN 11 with record None (bam_rack_twin.description.station_description(11), no unit): all four blocking checks True or False, never
   None; a False says its physical reason. The gains it would ship with no tune are the nominal world's own loop (5 Hz, damping ratio 1 on
   the description's lumped inertia, ki 0); its torque cap is the JMC 60ASM200's datasheet peak x the AD60-G10's 10:1 x 0.97; the envelope
   is the soak's peak torque.
2. The UR wrist test rig's Cad2Robot bundle (three GIM4305-10 integrated servos): torque_margin answered where the servo's part carries a
   datasheet (robotparts' built part, or its user/ part datasheet), its cap the datasheet's output peak x 0.97; a part with no datasheet is
   None naming the part. Gains and soak answered.
3. Mutations turn their check red: an inertia 20x the fit turns the soak red; a tuned kp outside pidtuna's admissible range about the
   nominal loop (0.25-2x) turns the gains red, and an integrating ki does too; a tune inside the range passes.

Amended 2026-11-21 for pidtuna contract amendment 3 (v2.3: no relative gain range by default; the shipped gains are held by pidtuna's
analytic bounds on the twin's model and stated loop, tests/test_preflight_analytic_bounds.py): gains_within_board_limits is answered, or
None naming the pieces of a bound the twin does not state (the nominal CAN 11 states no encoder count), never None for want of the
tracer's runner and never a pass on nothing; an unstated structural mode is not applied (pidtuna §2 bounds a known mode), so the wrist passes. A 5x kp is red for a bound it breaks (the damping floor, the
linear range); a tune inside every bound is not red.

The oracles are this file's own: the nominal loop's kp from the description's inertia and LOOP_HZ, the caps from the robotparts files.
"""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

pytest.importorskip("bam_rack_twin", reason="CAN 11's description lives in bam_rack_twin (the rack venv)")
pytest.importorskip("mujoco", reason="the nominal world and the soak need the sim extra")

from robot_msgs.space import Value  # noqa: E402

import sim2real  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
BLOCKING = ("record_matches_description", "gains_within_board_limits", "torque_margin", "sim_soak")
ANSWERED = ("gains_within_board_limits", "torque_margin", "sim_soak")
ROBOTPARTS = Path("/home/bam/robotparts")
TAU = 2.0 * math.pi


def _wrist_module():
    spec = importlib.util.spec_from_file_location("_nominal_ruler", REPO / "tests" / "test_from_robot_description_nominal.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module   # WHY: its dataclasses resolve their annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def check(report, check_id):
    found = [c for c in report.checks if c.id == check_id]
    assert len(found) == 1, f"one {check_id} check, got {[c.id for c in report.checks]}"
    return found[0]


def revalue(value, raw):
    meta = {**value.meta(), "low": None, "high": None}
    unit = meta.pop("unit")
    return Value(float(raw), unit, **meta)


def datasheet_peak(part: str) -> float | None:
    """The part's peak torque (N·m) from robotparts, read here: its built part (dist/site/v2/parts/<id>.json specs.peak_torque), else its
    user/ part datasheet (user/parts/**/<id>/parameters.json, the chosen peak_torque row)."""
    built = ROBOTPARTS / "dist" / "site" / "v2" / "parts" / f"{part}.json"
    if built.is_file():
        spec = json.loads(built.read_text()).get("specs", {}).get("peak_torque")
        if spec and spec.get("value") is not None:
            return float(spec["value"])
    for sheet in (ROBOTPARTS / "user" / "parts").rglob(f"{part}/parameters.json"):
        for row in json.loads(sheet.read_text()).get("rows", []):
            if row.get("id") == "peak_torque" and isinstance(row.get("chosen"), dict) and row["chosen"].get("value") is not None:
                return float(row["chosen"]["value"])
    return None


# --- the twins ------------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def can11():
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    rd = dataclasses.replace(station_description(11), record=None)
    return sim2real.RobotTwin.from_robot_description(rd, workers=1)


@pytest.fixture(scope="module")
def can11_fitted(can11):
    return can11.calibrate(on="sim", callbacks=[])


@pytest.fixture(scope="module")
def can11_report(can11_fitted):
    report = sim2real.preflight(can11_fitted)
    print("\n" + report.summary())
    return report


@pytest.fixture(scope="module")
def wrist_fitted():
    module = _wrist_module()
    if not (module.BUNDLE / "robot.json").exists():
        pytest.skip(f"no Cad2Robot bundle at {module.BUNDLE}")
    twin = sim2real.RobotTwin.from_robot_description(module.wrist_description(), workers=1)
    return twin.calibrate(on="sim", callbacks=[])


@pytest.fixture(scope="module")
def wrist_report(wrist_fitted):
    report = sim2real.preflight(wrist_fitted)
    print("\n" + report.summary())
    return report


def nominal_loop_kp(fitted) -> float:
    """The nominal world's kp when the description states none: a 5 Hz, damping-ratio-1 loop on the lumped inertia (CAN 11's
    armature_kg_m2, the total about the hinge), computed here from the description, never read from the code under test."""
    inertia = float(fitted.description.instance("can11").parameters["armature_kg_m2"])
    return inertia * (2 * math.pi * 5.0) ** 2


def nominal_loop_kd(fitted) -> float:
    inertia = float(fitted.description.instance("can11").parameters["armature_kg_m2"])
    return 2 * 1.0 * inertia * (2 * math.pi * 5.0)


def tuned(fitted, *, kp, kd, ki=0.0, ilimit=0.0):
    out = copy.copy(fitted)
    out.settings_ = {"can11.kp_nm_rad": kp, "can11.kd_nm_s_rad": kd}
    out.proposals_ = {"pid.pidtuna": {"schema": "pidtuna/gains-1", "tier": "sim", "joints": {"can11": {
        "joint": "can11", "can_id": 11, "tuned": {"gains_si": {"kp": kp, "kd": kd, "ki": ki, "ilimit": ilimit}}}}}}
    return out


# --- CAN 11, record None --------------------------------------------------------------------------------------------------------------


def unstated_bounds_only(gains) -> bool:
    """Amendment 3: a None gains check is None only for bounds whose pieces the twin does not state (each naming them), none broken."""
    per_servo = [gains.limit["bounds"]] if "bounds" in (gains.limit or {}) else [v["bounds"] for v in (gains.limit or {}).values()]
    return (gains.passed is None and bool(per_servo) and "could not be checked" in gains.why
            and all(b["passed"] is not False and (b["passed"] in (True, "not applied") or b["missing"]) for bounds in per_servo
                    for b in bounds.values()))


def test_can11_nominal_answers_every_blocking_check(can11_report):
    unanswered = {c.id: c.why for c in can11_report.checks if c.id in BLOCKING and c.passed is None
                  and not (c.id == "gains_within_board_limits" and unstated_bounds_only(c))}
    assert not unanswered, unanswered
    for c in can11_report.checks:
        if c.id in BLOCKING and c.passed is False:
            assert c.why and len(c.why) > 20, c   # a red check says its physical reason


def test_can11_ships_the_nominal_loop_pd_only(can11_fitted, can11_report):
    gains = check(can11_report, "gains_within_board_limits")
    value = gains.value["can11"] if "can11" in gains.value else gains.value
    assert value["kp_nm_rad"] == pytest.approx(nominal_loop_kp(can11_fitted), rel=1e-3), gains
    assert value["kd_nm_s_rad"] == pytest.approx(nominal_loop_kd(can11_fitted), rel=1e-3), gains
    assert value["ki_nm_rad_s"] == 0.0, gains
    assert gains.passed is True or unstated_bounds_only(gains), gains


def test_can11_torque_cap_is_the_datasheet_house_cap(can11_report):
    torque = check(can11_report, "torque_margin")
    assert torque.limit == pytest.approx(datasheet_peak("jmc-60asm200-5-1024c") * 10 * 0.97, rel=1e-6), torque
    soak = check(can11_report, "sim_soak")
    assert torque.value == pytest.approx(soak.value["peak_torque_nm"]["can11"] if isinstance(soak.value["peak_torque_nm"], dict)
                                         else soak.value["peak_torque_nm"], rel=1e-6), (torque, soak)
    assert torque.passed is (torque.value < torque.limit)


# --- the wrist ------------------------------------------------------------------------------------------------------------------------


def test_the_wrist_is_answered_where_its_part_has_a_datasheet(wrist_fitted, wrist_report):
    parts = {i.part for i in wrist_fitted.description.instances if i.type == "integrated_servo"}
    assert parts == {"steadywin-gim4305-10"}
    peak = datasheet_peak("steadywin-gim4305-10")
    torque = check(wrist_report, "torque_margin")
    if peak is None:
        assert torque.passed is None and "steadywin-gim4305-10" in torque.why, torque
    else:
        # an integrated servo's datasheet peak is at its output (the gear inside): the cap is that peak x 0.97
        assert torque.passed in (True, False) and torque.limit == pytest.approx(peak * 0.97, rel=1e-6), torque
    assert check(wrist_report, "sim_soak").passed in (True, False), check(wrist_report, "sim_soak")
    gains = check(wrist_report, "gains_within_board_limits")
    assert gains.passed in (True, False) or unstated_bounds_only(gains), gains


def test_a_wrist_part_with_no_datasheet_is_none_naming_the_part(wrist_fitted):
    bare = copy.copy(wrist_fitted)
    bare.description = dataclasses.replace(wrist_fitted.description, instances=tuple(
        dataclasses.replace(i, part="no-such-servo-part") if i.type == "integrated_servo" else i for i in wrist_fitted.description.instances))
    torque = check(sim2real.preflight(bare, soak_s=0.5), "torque_margin")
    assert torque.passed is None and "no-such-servo-part" in torque.why, torque


# --- mutations ------------------------------------------------------------------------------------------------------------------------


def test_an_inertia_20x_turns_the_soak_red(can11_fitted):
    heavy = copy.copy(can11_fitted)
    inertia = can11_fitted.description.instance("can11").parameters["armature_kg_m2"]
    heavy.description = can11_fitted.description.with_values({"can11.armature_kg_m2": revalue(inertia, 20.0 * float(inertia))})
    soak = check(sim2real.preflight(heavy), "sim_soak")
    assert soak.passed is False, soak


def test_a_tuned_kp_outside_its_range_turns_the_gains_red(can11_fitted):
    report = sim2real.preflight(tuned(can11_fitted, kp=5.0 * nominal_loop_kp(can11_fitted), kd=nominal_loop_kd(can11_fitted)), soak_s=0.5)
    gains = check(report, "gains_within_board_limits")
    assert gains.passed is False and "kp" in gains.why, gains
    assert "damping floor" in gains.why or "linear range" in gains.why, gains.why   # amendment 3: the bound it breaks, named
    assert report.passed is False


def test_an_integrating_ki_turns_the_gains_red(can11_fitted):
    gains = check(sim2real.preflight(tuned(can11_fitted, kp=nominal_loop_kp(can11_fitted), kd=nominal_loop_kd(can11_fitted), ki=2.0,
                                           ilimit=0.5), soak_s=0.5), "gains_within_board_limits")
    assert gains.passed is False and "ki" in gains.why, gains


def test_a_tune_inside_the_range_passes_the_gains(can11_fitted):
    gains = check(sim2real.preflight(tuned(can11_fitted, kp=1.3 * nominal_loop_kp(can11_fitted), kd=1.2 * nominal_loop_kd(can11_fitted)),
                                     soak_s=0.5), "gains_within_board_limits")
    assert gains.passed is True or unstated_bounds_only(gains), gains


# --- added after the first green (tests only; nothing above edited): the soak's mutation must fail for its OWN reason --------------------
# WHY: CAN 11 at its default 5 Hz loop already fails the stop gate (Coulomb 0.83 N·m / kp 120 N·m/rad ~ 6.9 mrad of deadband against the
# 3.6 mrad gate), so "the 20x soak is red" alone would pass a soak that ignored the inertia. These hold the mutation to a new reason and the
# soak to a pass where the physics allows one.


def test_the_20x_soak_fails_for_the_inertia_not_the_baseline(can11_fitted):
    heavy = copy.copy(can11_fitted)
    inertia = can11_fitted.description.instance("can11").parameters["armature_kg_m2"]
    heavy.description = can11_fitted.description.with_values({"can11.armature_kg_m2": revalue(inertia, 20.0 * float(inertia))})
    soak = check(sim2real.preflight(heavy), "sim_soak")
    assert soak.passed is False and ("settle" in soak.why or "torque-cap" in soak.why), soak


def test_a_2x_stiffer_tune_passes_every_blocking_check_on_can11(can11_fitted):
    # WHY 1.9 and not 2.0: 2x sits on pidtuna's upper bound, and this file's loop kp (from the FITTED inertia) is a hair above the world's
    # (the nominal inertia), so 2.0x lands just outside it
    report = sim2real.preflight(tuned(can11_fitted, kp=1.9 * nominal_loop_kp(can11_fitted), kd=1.4 * nominal_loop_kd(can11_fitted)))
    failing = {c.id: c.why for c in report.checks if c.id in BLOCKING and c.passed is not True
               and not (c.id == "gains_within_board_limits" and unstated_bounds_only(c))}
    assert not failing, failing
