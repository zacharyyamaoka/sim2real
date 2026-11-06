"""The system-ID oracle's acceptance test, written before any identification code.

Zach, PROJECT - Sim2Real, "Proposed Work Flow Nov 5 2026": "In all the cases its just Robot Description in. and then a better
model out ... if we assumed the simulator data was real, we should check that our system ID can match the real values!!!! (this is
super important as the base oracle check for all of this...)".

For every example (sysid/examples/<id>/description.json, a robot description in) the simulator plays the real hardware from HIDDEN
true parameters (sysid/examples/<id>/world.json); identification starts from the description's nominal values and never reads the
world. It must

1. recover every hidden value inside its stated tolerance, where the tolerance is one the description's nominal value FAILS (so a
   fit that hands the description back unchanged fails), and
2. improve every held-out fidelity metric by its stated factor (before / after).

Drift (the coordinator's brief and Zach's wear addition, 2026-11-05): the servo's backlash grows with deployment hours,
b(h) = b0 + k h; its rate k is recovered from the early-life checks, the hour the drift ratio crosses the threshold is predicted
before it happens and compared with the hour it does, and the plain drift detector fires after it; recalibration restores the
fit. A camera knocked out of pose: the drift diagnostic fires on the next check and never before, and recalibration restores it.

The tolerances and factors are sysid/acceptance.json, pinned below by digest: loosening the ruler is a visible diff of this file.

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/sysid/tests
"""

from __future__ import annotations

import fnmatch
import hashlib
import inspect
import json
import math
import os
from pathlib import Path

import pytest

SYSID = Path(__file__).resolve().parents[1]
ACCEPTANCE_PATH = SYSID / "acceptance.json"
# WHY pinned: the ruler is data the pipeline reads too (the site shows its pass/fail); a digest here makes any edit to it an edit
# of this file, reviewed as a ruler change.
ACCEPTANCE_SHA256 = "2c28aad2bb6e536f81480912137a2af89e2861c6b6193dc98f210d844104005e"
ACCEPTANCE = json.loads(ACCEPTANCE_PATH.read_text())
EXAMPLES = tuple(ACCEPTANCE["examples"])
WORKERS = int(os.environ.get("SYSID_WORKERS", "6"))
_RESULTS: dict[str, dict] = {}
_DRIFT: dict[str, dict] = {}


def world(example: str) -> dict:
    """The hidden truth, read here directly: the test's own oracle, independent of what the pipeline reports."""
    return json.loads((SYSID / "examples" / example / "world.json").read_text())


def result(example: str) -> dict:
    if example not in _RESULTS:
        from sysid import oracle
        _RESULTS[example] = oracle.run(example, workers=WORKERS)
    return _RESULTS[example]


def drift_result(name: str) -> dict:
    if name not in _DRIFT:
        from sysid import drift
        _DRIFT[name] = {"backlash_wear": drift.run_backlash, "camera_knock": drift.run_camera}[name](workers=WORKERS)
    return _DRIFT[name]


def gated(example: str) -> dict[str, tuple[str, float]]:
    """{hidden key: (kind, tolerance)}: every world truth key matched to exactly one acceptance pattern."""
    patterns = ACCEPTANCE["examples"][example]["parameters"]
    out = {}
    for key in world(example)["truth"]:
        hits = [p for p in patterns if fnmatch.fnmatchcase(key, p)]
        assert len(hits) == 1, f"{example}: hidden {key} matches {len(hits)} acceptance patterns ({hits}); every hidden value is gated once"
        out[key] = tuple(patterns[hits[0]])
    for pattern in patterns:
        assert any(fnmatch.fnmatchcase(key, pattern) for key in out), f"{example}: acceptance pattern {pattern} gates no hidden value"
    return out


def within(value, truth: float, kind: str, tol: float) -> bool:
    if value is None or not math.isfinite(float(value)):
        return False
    bound = tol if kind == "abs" else tol * abs(truth)
    return abs(float(value) - truth) <= bound


def by_key(rows: list[dict]) -> dict[str, dict]:
    return {row["key"]: row for row in rows}


# --- the ruler itself -------------------------------------------------------------------------------------------------------

def test_the_ruler_is_pinned():
    assert hashlib.sha256(ACCEPTANCE_PATH.read_bytes()).hexdigest() == ACCEPTANCE_SHA256


@pytest.mark.parametrize("example", EXAMPLES)
def test_every_hidden_value_is_gated(example):
    assert gated(example), f"{example} hides nothing"


@pytest.mark.parametrize("example", EXAMPLES)
def test_the_description_fails_the_ruler(example):
    """The ruler can fail: every gated parameter's nominal value (the description's, parsed) is outside its own tolerance."""
    from sysid import describe
    nominal = describe.load(example).nominal
    truth = world(example)["truth"]
    passing = [key for key, (kind, tol) in gated(example).items() if within(nominal[key].value, truth[key], kind, tol)]
    assert not passing, f"{example}: the nominal value already passes for {passing}; that tolerance cannot tell a fit from no fit"


@pytest.mark.parametrize("example", EXAMPLES)
def test_identification_never_reads_the_world(example):
    """The fit sees measurements and the description only: its source never names the world, and the pipeline seals the world
    while it runs (sysid.world.sealed)."""
    from sysid import oracle
    module = oracle.example_module(example)
    source = inspect.getsource(module.identify)
    assert "world" not in source.lower() and "truth" not in source.lower(), f"{example}: identify() names the world or the truth"
    assert result(example)["provenance"]["identify_sealed"] is True


# --- recovery and held-out fidelity ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("example", EXAMPLES)
def test_recovered_within_tolerance(example):
    rows = by_key(result(example)["parameters"])
    truth = world(example)["truth"]
    missing = sorted(set(gated(example)) - set(rows))
    assert not missing, f"{example}: no recovered value for {missing}"
    failing = {key: (rows[key]["recovered"], truth[key], f"{kind} {tol:g}") for key, (kind, tol) in gated(example).items()
               if not within(rows[key]["recovered"], truth[key], kind, tol)}
    assert not failing, f"{example}: recovered outside tolerance (recovered, true, tolerance): {failing}"


@pytest.mark.parametrize("example", EXAMPLES)
def test_the_reported_truth_is_the_world(example):
    rows = by_key(result(example)["parameters"])
    truth = world(example)["truth"]
    assert all(rows[key]["true"] == truth[key] for key in truth), f"{example}: the result's 'true' column is not world.json's"


@pytest.mark.parametrize("example", EXAMPLES)
def test_held_out_fidelity_improves(example):
    metrics = {m["id"]: m for m in result(example)["metrics"]}
    for metric_id, factor in ACCEPTANCE["examples"][example]["metrics"].items():
        assert metric_id in metrics, f"{example}: no held-out metric {metric_id}"
        m = metrics[metric_id]
        assert m["split"] == "held_out", f"{example}: {metric_id} is scored on {m['split']}, not the held-out split"
        assert m["after"] > 0 and m["before"] / m["after"] >= factor, (
            f"{example}: {metric_id} improved {m['before']:.4g} -> {m['after']:.4g} {m['unit']} "
            f"({m['before'] / m['after']:.2f}x), needs {factor:g}x")


def test_the_servo_ladder_selects_the_truths_rung():
    """CAN 11: the selection rule (type_cards: the lowest rung whose held-out fidelity reaches the floor) picks the rung whose
    structure the hidden truth has, and every rung below it is scored and misses."""
    expected = ACCEPTANCE["examples"]["pendulum_can11"]["selected_rung"]
    doc = result("pendulum_can11")
    assert doc["selected_rung"] == expected, f"selected {doc['selected_rung']}, the truth's structure is {expected}"
    keys = [r["key"] for r in doc["rungs"]]
    below = keys[:keys.index(expected)]
    assert below and all(r["held_out_ratio"] > r["limit"] for r in doc["rungs"] if r["key"] in below)


@pytest.mark.parametrize("example", EXAMPLES)
def test_the_committed_result_is_this_code(example):
    """sysid/results/<id>.json (what the site shows) is what this code computes now."""
    committed = json.loads((SYSID / "results" / f"{example}.json").read_text())
    fresh = result(example)
    a, b = by_key(committed["parameters"]), by_key(fresh["parameters"])
    assert a.keys() == b.keys()
    for key in a:
        for field in ("nominal", "true", "recovered"):
            x, y = a[key][field], b[key][field]
            assert (x is None and y is None) or math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12), f"{example} {key} {field}: committed {x}, now {y}"
    ma, mb = {m["id"]: m for m in committed["metrics"]}, {m["id"]: m for m in fresh["metrics"]}
    assert ma.keys() == mb.keys()
    for mid in ma:
        assert math.isclose(ma[mid]["before"], mb[mid]["before"], rel_tol=1e-9) and math.isclose(ma[mid]["after"], mb[mid]["after"], rel_tol=1e-9), mid


# --- drift ------------------------------------------------------------------------------------------------------------------

def test_backlash_wear_is_recovered_and_its_crossing_predicted():
    gate = ACCEPTANCE["drift"]["backlash_wear"]
    hidden = world(gate["example"])["drift"]["backlash_wear"]
    doc = drift_result("backlash_wear")
    rate = doc["rate_recovered"]
    assert within(rate, hidden["rate_rad_per_h"], "rel", gate["rate_rel"]), f"wear rate {rate} vs true {hidden['rate_rad_per_h']}"
    predicted, actual = doc["predicted_crossing_h"], doc["actual_crossing_h"]
    assert actual is not None and predicted is not None, "the drift ratio never crossed its threshold inside the horizon"
    assert abs(predicted - actual) <= gate["crossing_hour_rel"] * actual, f"predicted {predicted:.1f} h, crossed at {actual:.1f} h"
    assert actual - doc["predicted_at_h"] >= gate["lead_h_min"], "the prediction was not made ahead of the crossing"
    alarm = doc["detector_alarm_h"]
    assert alarm is not None and actual <= alarm <= actual + gate["detector_within_checks"] * doc["check_every_h"], (
        f"plain detector alarmed at {alarm} h; the ratio crossed at {actual:.1f} h")
    for check in doc["checks"]:
        assert check["status"] == ("warning" if check["ratio"] > doc["threshold"] else "ok"), check
    assert doc["recalibrated"]["ratio"] <= gate["recalibrated_ratio_max"], f"after recalibration the ratio is {doc['recalibrated']['ratio']:.3f}"


# WHY 5 % (2026-11-05): 5 % of the ~234 h crossing is ~11.7 h, under one 12 h check interval, so a point forecast inside it is off by
# less than the spacing of the checks it replaces; the 15 % gate (~35 h, three checks) let a forecast 28 h late pass. A late forecast
# is the unsafe side for maintenance, so the plan-by hour (the same forecast at the wear rate's upper 95 % limit) must not be late
# at all. Not in acceptance.json: that file is pinned and may only tighten; this is an extra, tighter assertion beside its gate.
FORECAST_ERROR_REL = 0.05


def test_the_wear_forecast_is_close_not_late_and_reads_only_checks_up_to_its_hour():
    from sysid import drift

    gate = ACCEPTANCE["drift"]["backlash_wear"]
    doc = drift_result("backlash_wear")
    predicted, actual, at = doc["predicted_crossing_h"], doc["actual_crossing_h"], doc["predicted_at_h"]
    error = (predicted - actual) / actual
    assert abs(error) <= gate["crossing_hour_rel"], f"predicted {predicted:.1f} h, crossed at {actual:.1f} h ({100 * error:+.1f} %)"
    assert abs(error) <= FORECAST_ERROR_REL, f"predicted {predicted:.1f} h, crossed at {actual:.1f} h ({100 * error:+.1f} %, limit 5 %)"
    plan_by = doc["plan_by_h"]
    assert plan_by is not None and at < plan_by <= actual, f"plan-by hour {plan_by} is late (crossed at {actual:.1f} h) or not ahead of hour {at}"

    # no peeking: the forecast reads only checks at or before its hour; corrupting every later check must not move it
    used = doc["forecast"]["checks_h"]
    assert used == [c["h"] for c in doc["checks"] if c["h"] <= at] and max(used) <= at, used
    tampered = [c if c["h"] <= at else {**c, "b_hat_rad": 10 * c["b_hat_rad"], "ratio": 10 * c["ratio"], "live_x_floor": 10 * c["live_x_floor"]}
                for c in doc["checks"]]
    clean = drift.wear_forecast(doc["checks"], forecast_h=at, curve=doc["curve"], threshold=doc["threshold"])
    assert drift.wear_forecast(tampered, forecast_h=at, curve=doc["curve"], threshold=doc["threshold"]) == clean
    assert math.isclose(clean["predicted_crossing_h"], predicted, rel_tol=1e-12) and math.isclose(clean["plan_by_h"], plan_by, rel_tol=1e-12)
    # the hour the forecast is issued is itself decided from the checks so far (a rolling forecast at every check, issued at the first
    # one whose crossing is within the planning horizon, the monitoring's early_life_h at the latest): no later check may move it
    kwargs = {"curve": doc["curve"], "threshold": doc["threshold"], "latest_h": doc["early_life_h"]}
    issued = drift.issue_forecast(doc["checks"], **kwargs)
    assert drift.issue_forecast(tampered, **kwargs) == issued and issued["forecast_h"] == at <= doc["early_life_h"], issued["forecast_h"]
    assert math.isclose(issued["predicted_crossing_h"], predicted, rel_tol=1e-12)


def test_a_knocked_camera_is_detected_and_recalibrated():
    gate = ACCEPTANCE["drift"]["camera_knock"]
    hidden = world(gate["example"])["drift"]["camera_knock"]
    doc = drift_result("camera_knock")
    before = [c for c in doc["checks"] if c["h"] < hidden["hour"]]
    assert before and sum(c["status"] == "warning" for c in before) <= gate["false_alarms_max"], "false alarms before the knock"
    alarm = doc["alarm_h"]
    assert alarm is not None and hidden["hour"] <= alarm <= hidden["hour"] + gate["detect_within_checks"] * doc["check_every_h"], f"alarm at {alarm}"
    assert doc["recalibrated"]["ratio"] <= gate["recalibrated_ratio_max"], f"after recalibration the ratio is {doc['recalibrated']['ratio']:.3f}"
    for name, true in hidden["shift"].items():
        tol = gate["shift_translation_abs_m"] if name.endswith("_m") else gate["shift_rotation_abs_rad"]
        assert abs(doc["shift_recovered"][name] - true) <= tol, f"shift {name}: recovered {doc['shift_recovered'][name]}, true {true}"


@pytest.mark.parametrize("name", ("backlash_wear", "camera_knock"))
def test_the_committed_drift_result_is_this_code(name):
    committed = json.loads((SYSID / "results" / f"drift_{name}.json").read_text())
    fresh = drift_result(name)
    keys = ("rate_recovered", "predicted_crossing_h", "plan_by_h", "actual_crossing_h", "detector_alarm_h") if name == "backlash_wear" else ("alarm_h",)
    for key in keys:
        x, y = committed[key], fresh[key]
        assert (x is None and y is None) or math.isclose(x, y, rel_tol=1e-9), f"{name} {key}: committed {x}, now {y}"
    assert math.isclose(committed["recalibrated"]["ratio"], fresh["recalibrated"]["ratio"], rel_tol=1e-9)
