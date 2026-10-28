"""Result -> RobotDx record (diagnostics-record/0, revision 0.2) -> Result, with no loss; and the data-ui row."""

from __future__ import annotations

import json

import numpy as np
import pytest

from robotdx.diagnostics import Limits, evaluate
from robotdx.diagnostics.record import from_record, to_record
from robotdx.diagnostics.rollup import GateMatrixConfig, RollupConfig
from robotdx.diagnostics.rows import ROW_COLUMNS, diff_rows, result_row, sample_rows
from robotdx.diagnostics.stock import (BoxConfig, CoverageConfig, FaultCodesConfig, FidelityRatioConfig, FloorConfig,
                                       KnownLoadConfig, KtConsistencyConfig, ModelErrorConfig, RateConfig, StopErrorConfig,
                                       TrackingErrorConfig)
from robotdx.diagnostics.stock.fidelity import FidelityInput, rows_of
from robotdx.diagnostics.stock.health import Stamps
from robotdx.diagnostics.stock.truthfulness import KnownLoadInput, KtReadings

from conftest import tape


def every_stock_result():
    runs = [tape(offset=0.001, run="a", **{"class": "pickplace"}), tape(offset=0.0025, run="b", **{"class": "pickplace"})]
    real = runs[0]
    error = evaluate("stock.model_error", ModelErrorConfig(), [(real, real.as_situation(real.q_target_rad, "twin"))], subject="rack/can14")
    out = [
        evaluate("stock.tracking_error", TrackingErrorConfig(limits=Limits.at_most(2.0)), runs, subject="rack/can14", stamp=1761600000.25),
        evaluate("stock.stop_error", StopErrorConfig(limits=Limits.at_most(3.6)), runs, subject="rack/can14"),
        evaluate("stock.repeatability_floor", FloorConfig(min_repeats=2), runs, subject="rack/can14"),
        error,
        evaluate("stock.fidelity_ratio", FidelityRatioConfig(), FidelityInput(0.4, rows_of(error), "repeats", "pickplace"), subject="rack/can14"),
        evaluate("stock.known_load_gain", KnownLoadConfig(), KnownLoadInput([]), subject="rack/can14"),
        evaluate("stock.kt_consistency", KtConsistencyConfig(), KtReadings(199.78, 162.56, "kt_can14.json"), subject="rack/can14"),
        evaluate("stock.box", BoxConfig(max=Limits.at_most(70.0, warn=60.0)), runs, subject="rack/can14"),
        evaluate("stock.sample_rate", RateConfig(), [Stamps(real.t, "a")], subject="rack/can14"),
        evaluate("stock.fault_codes", FaultCodesConfig(), runs, subject="rack/can14"),
        evaluate("stock.coverage", CoverageConfig(), runs, subject="rack/can14"),
    ]
    out.append(evaluate("stock.rollup", RollupConfig(title="CAN 14"), out, subject="rack/can14-composite"))
    out.append(evaluate("stock.gate_matrix", GateMatrixConfig(), [("CAN 14", r.diagnostic, r) for r in out[:4]], subject="rack"))
    return out


def test_every_result_survives_the_record_both_ways():
    for result in every_stock_result():
        line = json.loads(json.dumps(to_record(result)))  # through JSON, as a host reads it
        assert from_record(line) == result, result.diagnostic


def test_the_real_contract_accepts_every_record_and_gives_it_back_unchanged(contract):
    for result in every_stock_result():
        status = contract.from_dict(to_record(result, expected_period_s=1.0))
        assert contract.validate(status) == [], (result.diagnostic, contract.validate(status))
        assert from_record(contract.to_dict(status)) == result, result.diagnostic
        stock = contract.to_diagnostic_status(status)  # the plain ROS view still reads: level byte, name, values
        assert stock["level"] == contract.ROS_LEVEL[contract.from_dict(to_record(result)).level]


def test_levels_map_one_to_one():
    levels = {r.verdict: to_record(r)["level"] for r in every_stock_result()}
    assert levels.get("pass", "ok") == "ok" and levels.get("fail", "error") == "error" and levels.get("not_run", "unknown") == "unknown"


def test_the_row_has_exactly_data_uis_columns():
    results = every_stock_result()
    row = result_row(results[1], parent="rack/can14-composite")
    assert tuple(row) == ROW_COLUMNS
    assert row["parent"] == "rack/can14-composite" and row["hint"] == "distribution" and row["emits"] == "series"
    assert row["evidence"].startswith(row["run"] + "#t=") and row["error_hi"] == 3.6 and row["better"] == "lower" and row["target"] == 3.6
    live = result_row(results[1], vocabulary="level")
    assert "level" in live and "verdict" not in live and live["rank"] == row["rank"]
    assert all(set(result_row(r)) == set(ROW_COLUMNS) for r in results)


def test_trajectory_rows_end_in_their_unit_and_difference_stays_on_a():
    real = tape(offset=0.002, run="r")
    samples = sample_rows(real, every=100)
    assert {"q_deg", "qd_deg_s", "tau_nm", "v_bus_v", "temp_c"} <= set(samples[0]) and samples[1]["t"] == pytest.approx(1.0)
    target = real.as_situation(real.q_target_rad, "target", "target")
    diffs = diff_rows(real, target)
    assert len(diffs) == real.t.size and diffs[0]["e_q_mrad"] == pytest.approx(-2.0) and diffs[0]["reference"] == "target"
    shorter = target.as_situation(target.q_rad, "target", "target")
    from dataclasses import replace
    short = replace(shorter, t=shorter.t[:300], q_rad=shorter.q_rad[:300])
    assert len(diff_rows(real, short)) == 300  # never extrapolates past b's span
    assert np.isfinite([d["e_q_mrad"] for d in diffs]).all()
