"""The servo's drift alarm in the gap's own units (2026-11-07), written before the code it holds.

The calibration-routines lane found the servo's drift alarm (live fidelity / the camera's floor, / its hour-0 value, against 1.25) deaf at
3x the camera's noise: CAN 11's gap check never warned inside its 480 h horizon. The domain-v3 lane decided the threshold belongs in the
gap's own units (type_cards servo.gap_drift, dm.parameter_drift) and left sysid's adoption to sysid. This file holds that adoption's
pieces that need no replay:

- the gap check is type_cards' own servo.gap_drift (dm.parameter_drift), never a second rule;
- its allowance is set per station, and CAN 11's is T5's: bam_rack_twin's unit gate on a geared joint's gap (GAP_CI_HALF_ARCMIN, 2 arcmin
  at the output, its 95 % interval's half-width), read live, so a change to T5 fails here; a direct drive has no gap and no allowance;
- the forecast is the wear line on the checks so far, solved for the hour the gap reaches the commissioned gap plus the allowance, and it
  reads no check after its own hour.

The demo itself (CAN 11's checks replayed at 30 kHz) is held by test_oracle.py; the ladder's 1x / 3x / 10x rows by test_noise_ladder.py.

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/sysid/tests/test_drift_gap.py
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

SYSID = Path(__file__).resolve().parents[1]
HOURS = [12.0 * i for i in range(41)]


def test_the_gap_check_is_type_cards_gap_drift():
    from type_cards import domain as dm

    from sysid import drift

    spec = dm.diagnostic("integrated_servo", "servo.gap_drift")
    assert (spec.units, spec.parameter, spec.warn.unit) == ("parameter", "backlash_rad", "rad")
    commissioned, allowance = 0.0020, 0.00058
    for measured in (0.0018, 0.0020, 0.00250, 0.00257, 0.00259, 0.0031):
        got = drift.gap_verdict(measured, commissioned=commissioned, allowance=allowance)
        assert got["status"] == dm.parameter_drift(spec, commissioned=commissioned, measured=measured, allowance=allowance), measured
        assert math.isclose(got["growth_rad"], measured - commissioned, rel_tol=1e-12, abs_tol=1e-18), measured
        assert got["message"] == (spec.message if got["status"] == "warning" else ""), measured
    assert [drift.gap_verdict(b, commissioned=commissioned, allowance=allowance)["status"] for b in (0.00257, 0.00259)] == ["ok", "warning"]


def test_the_gap_allowance_is_t5_on_a_geared_station():
    """CAN 11's allowance as its description declares it (monitoring.gap_allowance) is the rule's on its own station record: T5's gap
    half-width on a geared station (its board turns the rotor 10 times an output turn), none on a direct drive; and the same 2 arcmin the
    noise ladder grades every UR gap against (sysid/noise_ladder.json, the rack's T5 gate)."""
    from bam_rack_twin import acceptance

    from sysid import describe, drift
    from sysid.examples.pendulum_can11 import pipeline as P

    description = describe.load("pendulum_can11")
    allowance = drift.gap_allowance(description)
    station = P._rack()[2]
    assert description.manifest["record"]["station"] == station.can_id == 11
    assert station.board_rotor_to_output_ratio != 1.0, "CAN 11 is geared (JMC 10:1)"
    assert (allowance["unit"], allowance["rule"]) == ("rad", "T5") and allowance["source"] and allowance["why"]
    t5 = math.radians(acceptance.GAP_CI_HALF_ARCMIN / 60.0)
    assert math.isclose(allowance["value"], t5, rel_tol=1e-12), (allowance["value"], t5)
    assert drift.t5_gap_allowance_rad(station) == t5
    assert drift.t5_gap_allowance_rad(dataclasses.replace(station, board_rotor_to_output_ratio=1.0)) is None, "a direct drive has no gap"
    ruler = json.loads((SYSID / "noise_ladder.json").read_text())
    assert math.isclose(ruler["tolerances"]["ur5e_backlash"]["*.backlash_rad"][1], t5, rel_tol=1e-12), "one T5 in this repo"


def test_a_description_without_a_gap_allowance_is_refused():
    import pytest

    from sysid import describe, drift

    description = describe.load("pendulum_can11")
    for bad in ({}, {"value": 0.5, "unit": "arcmin"}, {"value": -1e-4, "unit": "rad"}, {"value": None, "unit": "rad"}):
        manifest = {**description.manifest, "monitoring": {**description.monitoring, "gap_allowance": bad}}
        with pytest.raises(ValueError):
            drift.gap_allowance(dataclasses.replace(description, manifest=manifest))


def _line(b0: float, rate: float, wiggle: float = 1e-6) -> list[dict]:
    return [{"h": h, "b_hat_rad": b0 + rate * h + (wiggle if i % 2 else -wiggle)} for i, h in enumerate(HOURS)]


def test_the_forecast_solves_the_wear_line_for_the_commissioned_gap_plus_the_allowance():
    from sysid import drift

    checks = _line(0.00195, 1.9e-6)
    level = 0.00195 + 0.00058
    made = drift.wear_forecast(checks, forecast_h=168.0, level=level)
    k, b0, k_ci = drift.line_fit([(c["h"], c["b_hat_rad"]) for c in checks if c["h"] <= 168.0])
    assert made["checks_h"] == [h for h in HOURS if h <= 168.0]
    assert (made["rate"], made["b0_rad"], made["rate_ci95"]) == (k, b0, list(k_ci))
    assert math.isclose(made["predicted_crossing_h"], (level - b0) / k, rel_tol=1e-12)
    assert math.isclose(made["remaining_h"], made["predicted_crossing_h"] - 168.0, rel_tol=1e-9)
    assert made["gap_at_threshold_rad"] == level
    assert 168.0 < made["plan_by_h"] <= made["predicted_crossing_h"], "the upper band reaches the level first"
    # no peeking: checks after the forecast's hour change nothing
    tampered = [c if c["h"] <= 168.0 else {**c, "b_hat_rad": 10 * c["b_hat_rad"]} for c in checks]
    assert drift.wear_forecast(tampered, forecast_h=168.0, level=level) == made
    # a gap that is not growing is never forecast to reach the level
    assert drift.wear_forecast(_line(0.00200, -1e-7), forecast_h=168.0, level=level)["predicted_crossing_h"] is None


def test_the_forecast_is_issued_inside_its_horizon_or_at_the_end_of_early_life():
    from sysid import drift

    # the line reaches the level at ~ (0.00058 - 0.00005) / 2.5e-6 + ... : early, so it is issued as soon as a forecast is within 96 h
    soon = drift.issue_forecast(_line(0.00195, 2.5e-6), level=0.00195 + 0.00058, latest_h=168.0)
    assert soon["forecast_h"] < 168.0 and soon["predicted_crossing_h"] - soon["forecast_h"] <= drift.FORECAST_HORIZON_H
    assert [h for h, _ in soon["rolling"]] == [h for h in HOURS[drift.MIN_CHECKS - 1:] if h <= soon["forecast_h"]]
    assert all(p - h > drift.FORECAST_HORIZON_H for h, p in soon["rolling"][:-1])
    # a slow line: no forecast comes within 96 h before hour 168, so it is issued there
    late = drift.issue_forecast(_line(0.00195, 1.0e-6), level=0.00195 + 0.00058, latest_h=168.0)
    assert late["forecast_h"] == 168.0 and late["predicted_crossing_h"] - 168.0 > drift.FORECAST_HORIZON_H
    assert late == {**drift.wear_forecast(_line(0.00195, 1.0e-6), forecast_h=168.0, level=0.00195 + 0.00058),
                    "forecast_h": 168.0, "rolling": late["rolling"]}
