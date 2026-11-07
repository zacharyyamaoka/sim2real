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
b(h) = b0 + k h; its rate k is recovered from the early-life checks, the hour the gap grows past its allowance is predicted before it
happens and compared with the hour it does, and the plain gap check fires after it; recalibration restores the fit. Since 2026-11-07
the servo's alarm is in the gap's own units (type_cards servo.gap_drift: the gap a check measures less the commissioned gap, against
the station's allowance, T5's 2 arcmin on CAN 11), because the fidelity ratio's alarm went deaf as the camera's noise grew; the ratio
is still computed on the same checks, beside it. A camera knocked out of pose: the drift diagnostic fires on the next check and never
before, and recalibration restores it.

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

def test_backlash_wear_is_recovered_and_the_gap_check_warns_on_time():
    from sysid import drift

    gate = ACCEPTANCE["drift"]["backlash_wear"]
    hidden = world(gate["example"])["drift"]["backlash_wear"]
    doc = drift_result("backlash_wear")
    rate = doc["rate_recovered"]
    assert within(rate, hidden["rate_rad_per_h"], "rel", gate["rate_rel"]), f"wear rate {rate} vs true {hidden['rate_rad_per_h']}"
    # the gap the checks ran on is the world's wear line (its process noise inside 5 sigma): the test's own read of the truth
    for check in doc["checks"]:
        line = hidden["b0_rad"] + hidden["rate_rad_per_h"] * check["h"]
        assert abs(check["b_true_rad"] - line) <= 5 * hidden["process_noise_rad"], check["h"]
    allowance, commissioned = doc["allowance_rad"], doc["commissioned_gap_rad"]
    # every check is type_cards' servo.gap_drift: the gap it measures less the commissioned gap, against the station's allowance
    for check in doc["checks"]:
        growth = check["b_hat_rad"] - commissioned
        assert math.isclose(check["gap_growth_rad"], growth, rel_tol=1e-12, abs_tol=1e-15), check["h"]
        assert check["status"] == ("warning" if growth > allowance else "ok"), check
    # the truth's crossing: the first hour the hidden gap has grown the allowance past the gap the twin was commissioned with
    actual = doc["actual_crossing_h"]
    want = drift.crossing_hour([(c["h"], c["b_true_rad"] - commissioned) for c in doc["checks"]], allowance)
    assert actual is not None and math.isclose(actual, want, rel_tol=1e-12), "the hidden gap never grew past its allowance inside the horizon"
    predicted = doc["predicted_crossing_h"]
    assert predicted is not None and abs(predicted - actual) <= gate["crossing_hour_rel"] * actual, f"predicted {predicted} h, crossed at {actual:.1f} h"
    assert actual - doc["predicted_at_h"] >= gate["lead_h_min"], "the prediction was not made ahead of the crossing"
    alarm = doc["detector_alarm_h"]
    assert alarm is not None and actual <= alarm <= actual + gate["detector_within_checks"] * doc["check_every_h"], (
        f"the gap check warned at {alarm} h; the hidden gap crossed at {actual:.1f} h")
    assert alarm == next(c["h"] for c in doc["checks"] if c["status"] == "warning")
    rec = doc["recalibrated"]
    assert rec["h"] == alarm and rec["ratio"] <= gate["recalibrated_ratio_max"], f"after recalibration the ratio is {rec['ratio']:.3f}"
    assert rec["status"] == "ok", f"the next check reads the recalibrated gap's growth at {rec['gap_growth_rad']} rad"


def test_the_fidelity_ratio_is_kept_beside_the_gap_check():
    """The old alarm, live fidelity / the camera's floor / its hour-0 value against the servo card's 1.25 (servo.drift), is computed on
    the same checks so every run carries the comparison the decision rests on; it is never the alarm."""
    from type_cards import registry as reg

    from sysid import drift

    doc = drift_result("backlash_wear")
    threshold = doc["threshold"]
    assert threshold == reg.drift_diagnostic("servo").threshold.value == reg.DRIFT_THRESHOLD, "the servo card's own fidelity drift threshold"
    assert math.isclose(doc["calibrated_x_floor"], doc["checks"][0]["live_x_floor"], rel_tol=1e-12)
    for check in doc["checks"]:
        assert math.isclose(check["ratio"], check["live_x_floor"] / doc["calibrated_x_floor"], rel_tol=1e-12), check["h"]
        assert check["ratio_status"] == ("warning" if check["ratio"] > threshold else "ok"), check
    assert doc["ratio_alarm_h"] == next((c["h"] for c in doc["checks"] if c["ratio_status"] == "warning"), None)
    want = drift.crossing_hour([(c["h"], c["ratio"]) for c in doc["checks"]], threshold)
    assert (doc["ratio_crossing_h"] is None and want is None) or math.isclose(doc["ratio_crossing_h"], want, rel_tol=1e-12)


# WHY 5 % (2026-11-05): 5 % of the ~234 h crossing is ~11.7 h, under one 12 h check interval, so a point forecast inside it is off by
# less than the spacing of the checks it replaces; the 15 % gate (~35 h, three checks) let a forecast 28 h late pass. A late forecast
# is the unsafe side for maintenance, so the plan-by hour (the same forecast at the wear rate's upper 95 % limit) must not be late
# at all. Not in acceptance.json: that file is pinned and may only tighten; this is an extra, tighter assertion beside its gate.
# WHY one check interval beside it (2026-11-07): the gap's own allowance is reached later (~290 h at 1x), where 5 % is ~14.6 h, more than
# one check; the interval the 5 % was chosen to stay under is asserted too, so moving the crossing never loosens the forecast's bound.
FORECAST_ERROR_REL = 0.05


def test_the_wear_forecast_is_close_not_late_and_reads_only_checks_up_to_its_hour():
    from sysid import drift

    gate = ACCEPTANCE["drift"]["backlash_wear"]
    doc = drift_result("backlash_wear")
    predicted, actual, at = doc["predicted_crossing_h"], doc["actual_crossing_h"], doc["predicted_at_h"]
    error = (predicted - actual) / actual
    assert abs(error) <= gate["crossing_hour_rel"], f"predicted {predicted:.1f} h, crossed at {actual:.1f} h ({100 * error:+.1f} %)"
    assert abs(error) <= FORECAST_ERROR_REL, f"predicted {predicted:.1f} h, crossed at {actual:.1f} h ({100 * error:+.1f} %, limit 5 %)"
    assert abs(predicted - actual) <= doc["check_every_h"], f"predicted {predicted:.1f} h, crossed at {actual:.1f} h: more than one check apart"
    plan_by = doc["plan_by_h"]
    assert plan_by is not None and at < plan_by <= actual, f"plan-by hour {plan_by} is late (crossed at {actual:.1f} h) or not ahead of hour {at}"
    level = doc["gap_at_threshold_rad"]
    assert math.isclose(level, doc["commissioned_gap_rad"] + doc["allowance_rad"], rel_tol=1e-12), "the forecast's target is the gap check's"

    # no peeking: the forecast reads only checks at or before its hour; corrupting every later check must not move it
    used = doc["forecast"]["checks_h"]
    assert used == [c["h"] for c in doc["checks"] if c["h"] <= at] and max(used) <= at, used
    tampered = [c if c["h"] <= at else {**c, "b_hat_rad": 10 * c["b_hat_rad"], "gap_growth_rad": 10 * c["gap_growth_rad"], "ratio": 10 * c["ratio"],
                                        "live_x_floor": 10 * c["live_x_floor"]}
                for c in doc["checks"]]
    clean = drift.wear_forecast(doc["checks"], forecast_h=at, level=level)
    assert drift.wear_forecast(tampered, forecast_h=at, level=level) == clean
    assert math.isclose(clean["predicted_crossing_h"], predicted, rel_tol=1e-12) and math.isclose(clean["plan_by_h"], plan_by, rel_tol=1e-12)
    # the hour the forecast is issued is itself decided from the checks so far (a rolling forecast at every check, issued at the first
    # one whose crossing is within the planning horizon, the monitoring's early_life_h at the latest): no later check may move it
    kwargs = {"level": level, "latest_h": doc["early_life_h"]}
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
    keys = (("rate_recovered", "predicted_crossing_h", "plan_by_h", "actual_crossing_h", "detector_alarm_h", "commissioned_gap_rad", "allowance_rad",
             "ratio_alarm_h", "ratio_crossing_h") if name == "backlash_wear" else ("alarm_h",))
    for key in keys:
        x, y = committed[key], fresh[key]
        assert (x is None and y is None) or math.isclose(x, y, rel_tol=1e-9), f"{name} {key}: committed {x}, now {y}"
    assert math.isclose(committed["recalibrated"]["ratio"], fresh["recalibrated"]["ratio"], rel_tol=1e-9)


def test_the_committed_can11_results_are_on_bam_ws_current_twin_of_record():
    """Not pinned, flagged (2026-11-05, the rack lane's twin of record moved A 89b6fde5 -> follow-up C 95198353 and the wear demo's
    crossing moved 234 -> 197 h). WHY not pin the example to a digest: the rack twin is the thing under test (decision doc, Alternatives
    not taken), and a pin would have hidden the forecast method's bug, which passed on A by luck of a jagged curve. Instead this fast
    check names the move the moment bam_ws's twin of record leaves the one the committed results were built on."""
    from sysid.examples.pendulum_can11 import pipeline as P

    label, record, _ = P._rack()
    for name in ("pendulum_can11", "drift_backlash_wear"):
        prov = json.loads((SYSID / "results" / f"{name}.json").read_text())["provenance"]
        assert prov.get("twin_of_record_digest") == record.digest(), (
            f"{name} was built on CAN 11's twin of record {prov.get('twin_of_record')!r} {prov.get('twin_of_record_digest')}; bam_ws now has "
            f"{label!r} {record.digest()}: re-run `python -m sysid all --write` and review the wear demo before committing the results")
