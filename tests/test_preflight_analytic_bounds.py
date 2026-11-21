"""preflight's gains check after pidtuna contract amendment 3 (v2.3, pidtuna 7a46660): the description's guard defaults to no relative
gain range, so the gains a twin would ship are held by pidtuna's analytic bounds on the twin's model and stated loop. Sim only, one worker.

    env -u VIRTUAL_ENV PYTHONPATH=/home/bam/sim2real/src taskset -c 2-5,16,17 nice -n 19 /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -s -p no:cacheprovider /home/bam/sim2real/tests/test_preflight_analytic_bounds.py

Written red first: on fde2239 (pidtuna 5db5ceb) every preflight raised TypeError: 'NoneType' object is not iterable in _gain_range(),
for every twin (the UR wrist bundle's nominal twin, which passed 4 of 4 blocking checks on Nov 21, among them). The ruler:

1. preflight on a nominal twin (CAN 11 with record None; the UR wrist Cad2Robot bundle when it is on disk) and on the pendulum tracer
   does not raise.
2. gains_within_board_limits is never a pass with no limit behind it: True only when every analytic bound is computed (gain margin,
   damping floor, velocity noise, encoder count, structural mode, linear range), each with its value, its limit and its source.
3. A piece the twin does not state makes its bound None and the check None, naming the piece; never True.
4. A bound broken turns the check False with its numbers: a kp past the gain margin (damping held at 1).
5. A twin that states every piece passes, every bound computed and inside.
6. A relative range is kept only where it is stated, and a stated range must cite its source; pidtuna's Envelope states none now.
7. Without pidtuna the check says so (None), and only then.

The oracles are this file's own: the bound names and the rule (pidtuna's Objective() margin and damping floor) are read from pidtuna here.
"""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import math
import sys
from pathlib import Path

import pytest

pytest.importorskip("bam_rack_twin", reason="CAN 11's description lives in bam_rack_twin (the rack venv)")
pytest.importorskip("mujoco", reason="the nominal world and the soak need the sim extra")

from robot_msgs.space import Basis, Value  # noqa: E402

import sim2real  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
BOUNDS = ("gain margin", "damping floor", "velocity noise", "encoder count", "structural mode", "linear range")
TAU = 2.0 * math.pi
PIDTUNA = Path("/home/bam/pidtuna/src")


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tests" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module   # WHY: their dataclasses resolve their annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def objective():
    if importlib.util.find_spec("pidtuna") is None and str(PIDTUNA) not in sys.path:
        sys.path.insert(0, str(PIDTUNA))
    from pidtuna.types import Objective  # noqa: PLC0415

    return Objective()


def check(report, check_id="gains_within_board_limits"):
    found = [c for c in report.checks if c.id == check_id]
    assert len(found) == 1, f"one {check_id} check, got {[c.id for c in report.checks]}"
    return found[0]


def bounds_of(gains, servo=None):
    """{bound: {passed, value, limit, ...}} for one servo (the nominal path keys its limit by servo, the tracer's has one)."""
    limit = gains.limit if servo is None else gains.limit[servo]
    return limit["bounds"]


def never_a_bare_pass(gains):
    """Rule 2: True only with every bound computed, inside its limit, with a source."""
    assert gains.limit is not None or gains.passed is not True, gains
    if gains.passed is True:
        per_servo = [gains.limit["bounds"]] if "bounds" in gains.limit else [v["bounds"] for v in gains.limit.values()]
        for bounds in per_servo:
            assert set(bounds) == set(BOUNDS), bounds
            for name, b in bounds.items():
                assert b["passed"] is True and b["value"] is not None and b["limit"] is not None and b["from"], (name, b)


def stating(fitted, instance: str, **pieces):
    """The fitted twin with these pieces stated on `instance` (a Value with its unit and a source, as a description states them)."""
    units = {"structural_hz": "Hz", "encoder_quantum_rad": "rad", "velocity_filter_hz": "Hz", "loop_hz": "Hz", "command_delay_s": "s",
             "current_loop_hz": "Hz"}
    out = copy.copy(fitted)
    out.description = dataclasses.replace(fitted.description, instances=tuple(
        dataclasses.replace(i, parameters={**i.parameters, **{name: Value(float(v), units[name], basis=Basis.ASSUMED,
                                                                            source=f"stated by this ruler ({name})")
                                                              for name, v in pieces.items()}}) if i.id == instance else i
        for i in fitted.description.instances))
    return out


# --- the twins ------------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def nominal():
    return _load("_preflight_nominal_ruler", "test_preflight_nominal.py")


@pytest.fixture(scope="module")
def can11_fitted():
    from bam_rack_twin.description import station_description  # noqa: PLC0415

    rd = dataclasses.replace(station_description(11), record=None)
    return sim2real.RobotTwin.from_robot_description(rd, workers=1).calibrate(on="sim", callbacks=[])


@pytest.fixture(scope="module")
def can11_report(can11_fitted):
    report = sim2real.preflight(can11_fitted, soak_s=0.5)
    print("\n" + report.summary())
    return report


@pytest.fixture(scope="module")
def tracer():
    return _load("_preflight_tracer_ruler", "test_preflight.py")


@pytest.fixture(scope="module")
def tracer_fitted(tracer):
    return tracer._cheap_fit(tracer._loaded())


# --- 1-3: no twin raises, and no pass stands on nothing --------------------------------------------------------------------------------


def test_a_nominal_twin_preflights_without_raising_and_names_what_it_lacks(can11_report):
    gains = check(can11_report)
    never_a_bare_pass(gains)
    bounds = bounds_of(gains, "can11")
    assert set(bounds) == set(BOUNDS), bounds
    # the nominal CAN 11 states no structural mode and no encoder count (its encoder names no part, the motor's datasheet gives lines, not
    # the count the board reads): those bounds and the check are None, the check naming both
    for name in ("structural mode", "encoder count"):
        assert bounds[name]["passed"] is None and bounds[name]["missing"], (name, bounds[name])
    assert gains.passed is None, gains
    assert "could not be checked" in gains.why and "structural mode" in gains.why and "encoder count" in gains.why, gains.why
    for name, b in bounds.items():
        if b["passed"] is not None:
            assert b["value"] is not None and b["limit"] is not None and b["from"], (name, b)


def test_the_computed_bounds_use_pidtunas_objective(can11_report):
    rules = objective()
    bounds = bounds_of(check(can11_report), "can11")
    assert bounds["gain margin"]["limit"] == pytest.approx(rules.gain_margin), bounds["gain margin"]
    assert bounds["damping floor"]["limit"] == pytest.approx(rules.damping_band[0]), bounds["damping floor"]


def test_the_ur_wrist_bundle_preflights(nominal):
    module = nominal._wrist_module()
    if not (module.BUNDLE / "robot.json").exists():
        pytest.skip(f"no Cad2Robot bundle at {module.BUNDLE}")
    fitted = sim2real.RobotTwin.from_robot_description(module.wrist_description(), workers=1).calibrate(on="sim", callbacks=[])
    report = sim2real.preflight(fitted)
    print("\n" + report.summary())
    gains = check(report)
    never_a_bare_pass(gains)
    for servo in ("revolute_11", "revolute_14", "revolute_17"):
        assert set(bounds_of(gains, servo)) == set(BOUNDS)


def test_the_tracer_preflights_without_raising(tracer, tracer_fitted):
    report = sim2real.preflight(tracer._tuned(tracer_fitted), soak_s=0.5)
    gains = check(report)
    never_a_bare_pass(gains)
    assert set(bounds_of(gains)) == set(BOUNDS), gains.limit


# --- 4-5: a broken bound is red with its numbers; a twin stating everything passes -------------------------------------------------------


def test_a_kp_past_the_gain_margin_is_red_with_its_numbers(nominal, can11_fitted):
    kp, kd = nominal.nominal_loop_kp(can11_fitted), nominal.nominal_loop_kd(can11_fitted)
    gains = check(sim2real.preflight(nominal.tuned(can11_fitted, kp=400.0 * kp, kd=20.0 * kd), soak_s=0.5))   # wn x20, damping kept at 1
    margin = bounds_of(gains, "can11")["gain margin"]
    assert gains.passed is False and margin["passed"] is False and margin["value"] < margin["limit"], (gains.why, margin)
    assert "gain margin" in gains.why, gains.why


def test_a_twin_stating_every_piece_passes(nominal, can11_fitted):
    stated = stating(can11_fitted, "can11", structural_hz=200.0, encoder_quantum_rad=TAU / (2 ** 14 * 10))
    gains = check(sim2real.preflight(stated, soak_s=0.5))
    assert gains.passed is True, gains.why
    never_a_bare_pass(gains)


# --- 6-7: a relative range only where stated, with its source; without pidtuna the check says so --------------------------------------------


def test_pidtunas_envelope_states_no_relative_range():
    sys.path.insert(0, str(PIDTUNA)) if str(PIDTUNA) not in sys.path and importlib.util.find_spec("pidtuna") is None else None
    from pidtuna.types import Envelope  # noqa: PLC0415

    assert Envelope().gain_scale_range is None and Envelope().kd_range is None


def test_a_stated_range_holds_the_gains_and_must_cite_its_source(nominal, can11_fitted):
    kp, kd = nominal.nominal_loop_kp(can11_fitted), nominal.nominal_loop_kd(can11_fitted)
    stiff = nominal.tuned(can11_fitted, kp=1.9 * kp, kd=1.4 * kd)
    stated = {"kp": (0.5, 1.5), "kd": (0.5, 1.5), "source": "this ruler's range"}
    gains = check(sim2real.preflight(stiff, soak_s=0.5, gain_range=stated))
    assert gains.passed is False and "this ruler's range" in gains.why and "kp" in gains.why, gains.why
    with pytest.raises(ValueError, match="source"):
        sim2real.preflight(stiff, soak_s=0.5, gain_range={"kp": (0.5, 1.5)})


def test_without_pidtuna_the_check_says_so(can11_fitted, monkeypatch):
    import sim2real.preflight as module  # noqa: PLC0415

    def gone(name):
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(module, "_pidtuna", gone)
    gains = check(sim2real.preflight(can11_fitted, soak_s=0.5))
    assert gains.passed is None and "pidtuna" in gains.why and "cannot be imported" in gains.why, gains.why
