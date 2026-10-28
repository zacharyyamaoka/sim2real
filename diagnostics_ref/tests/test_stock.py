"""Every stock diagnostic against an answer known by construction (independent of the code under test)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from robotdx.diagnostics import FAIL, NOT_RUN, PASS, WARN, Limits, evaluate
from robotdx.diagnostics.record import from_record, to_record
from robotdx.diagnostics.rollup import GateMatrixConfig, RollupConfig
from robotdx.diagnostics.stock import (BoxConfig, CoverageConfig, FaultCodesConfig, FidelityRatioConfig, FloorConfig,
                                       KnownLoadConfig, KtConsistencyConfig, ModelErrorConfig, RateConfig, StopErrorConfig,
                                       TrackingErrorConfig)
from robotdx.diagnostics.stock.fidelity import FidelityInput, ModelRow, rows_of
from robotdx.diagnostics.stock.health import Stamps
from robotdx.diagnostics.stock.truthfulness import GRAVITY, KnownLoadInput, KtReadings
from robotdx.diagnostics.stream import monitor

from conftest import tape


def test_tracking_error_of_a_constant_offset_is_that_offset():
    out = evaluate("stock.tracking_error", TrackingErrorConfig(limits=Limits.at_most(2.0)), [tape(offset=0.003)], subject="s")
    assert out.value == pytest.approx(3.0) and out.verdict == FAIL and out.code == "AboveErrorLimit"


def test_stop_error_finds_every_dwell_followed_by_motion():
    run = tape(offset=0.001)
    out = evaluate("stock.stop_error", StopErrorConfig(limits=Limits.at_most(3.6)), [run], subject="s")
    assert {m.key: m.value for m in out.measurements}["n"] == 3  # the last dwell is not followed by motion
    assert out.value == pytest.approx(1.0)
    assert (out.verdict, out.code) == (WARN, "MeasuredOnEncoderSide")  # within 3.6, but encoder-side
    output_side = evaluate("stock.stop_error", StopErrorConfig(limits=Limits.at_most(3.6), side="output"), [run], subject="s")
    assert output_side.verdict == PASS


def test_floor_of_repeats_that_differ_by_a_constant_is_that_constant():
    runs = [tape(offset=0.0, run="a"), tape(offset=0.002, run="b")]
    out = evaluate("stock.repeatability_floor", FloorConfig(min_repeats=2), runs, subject="s")
    assert out.value == pytest.approx(2.0, rel=1e-9)
    assert out.payload["cells"][0][1] == pytest.approx(2.0)
    few = evaluate("stock.repeatability_floor", FloorConfig(min_repeats=5), runs, subject="s")
    assert (few.verdict, few.code) == (FAIL, "TooFewRepeats")
    assert evaluate("stock.repeatability_floor", FloorConfig(), runs[:1], subject="s").verdict == NOT_RUN


def test_model_error_and_fidelity_ratio_compare_many_models():
    real = tape(offset=0.002, run="r1", **{"class": "pickplace"})
    perfect = real.as_situation(real.q_target_rad, "perfect servo", "target")
    close = real.as_situation(real.q_rad - 0.0005, "twin")
    errors = [evaluate("stock.model_error", ModelErrorConfig(), [(real, model)], subject="s") for model in (perfect, close)]
    assert errors[0].value == pytest.approx(2.0) and errors[1].value == pytest.approx(0.5)
    rows = [row for out in errors for row in rows_of(out)]
    ratio = evaluate("stock.fidelity_ratio", FidelityRatioConfig(model="twin"), FidelityInput(0.4, rows, "repeats", "pickplace"), subject="s")
    assert ratio.value == pytest.approx(1.25) and ratio.verdict == PASS
    assert set(ratio.payload["group"]) == {"perfect servo", "twin"}
    proxy = evaluate("stock.fidelity_ratio", FidelityRatioConfig(model="twin"), FidelityInput(0.4, rows, "proxy", "pickplace"), subject="s")
    assert (proxy.verdict, proxy.code) == (WARN, "ProxyFloor")


def _sweep(gain: float, mass: float, run_id: str) -> object:
    t = np.arange(0, 20, 0.01)
    q = 1.2 * np.sin(2 * np.pi * t / 20.0)
    qd = np.gradient(q, t)
    link = 0.4 * np.sin(q)  # the link's own gravity: unknown, cancelled by load-off
    friction = 0.05 * np.sign(qd)
    rng = np.random.default_rng(len(run_id))
    tau = gain * (mass * GRAVITY * 0.27 * np.sin(q) + link) + friction + rng.normal(0, 0.003, t.size)
    run = tape(n=t.size)
    return replace(run, t=t, q_rad=q, qd_rad_s=qd, tau_nm=tau, mode=np.full(t.size, 10.0), run=run_id)


def test_known_load_gain_recovers_the_drive_gain():
    config = KnownLoadConfig(mass_kg=1.254, lever_m=0.27, max_speed_rad_s=1.0)
    out = evaluate("stock.known_load_gain", config, KnownLoadInput([_sweep(0.879, 1.254, "on")], [_sweep(0.879, 0.0, "off")]), subject="s")
    gain = {m.key: m.value for m in out.measurements}["gain"]
    assert gain == pytest.approx(0.879, abs=0.004)
    assert out.verdict == FAIL and out.code == "BelowErrorLimit"
    unknown = evaluate("stock.known_load_gain", KnownLoadConfig(), KnownLoadInput([]), subject="s")
    assert (unknown.verdict, unknown.code) == (NOT_RUN, "NoKnownLoad")


def test_kt_consistency_reads_the_can14_artifact():
    out = evaluate("stock.kt_consistency", KtConsistencyConfig(), KtReadings(199.78, 162.56), subject="s")
    assert 1 / out.value == pytest.approx(1.229, abs=5e-4) and out.verdict == FAIL


def test_box_uses_zachs_board_temperature_thresholds():
    run = tape()
    hot = replace(run, temp_c=np.linspace(40, 72, run.t.size))
    config = BoxConfig(max=Limits.at_most(70.0, warn=60.0), mean=Limits(error_low=5, warn_low=10, warn_high=55, error_high=65))
    out = evaluate("stock.box", config, [hot], subject="s")
    assert (out.verdict, out.code, out.value) == (FAIL, "MaxAboveErrorLimit", pytest.approx(72.0))
    assert evaluate("stock.box", config, [run], subject="s").verdict == PASS
    assert evaluate("stock.box", BoxConfig(channel="i_d"), [run], subject="s").verdict == NOT_RUN


def test_sample_rate_counts_gaps_and_a_slow_stream():
    t = np.arange(0, 10, 0.01)
    gappy = np.delete(t, np.arange(300, 340))
    out = evaluate("stock.sample_rate", RateConfig(expected_hz=100), [Stamps(t, "a"), Stamps(gappy, "b")], subject="s")
    assert {m.key: m.value for m in out.measurements}["gaps"] == 1
    assert out.verdict == WARN
    slow = evaluate("stock.sample_rate", RateConfig(expected_hz=100), [Stamps(np.arange(0, 10, 0.03), "c")], subject="s")
    assert slow.verdict == FAIL  # 33 Hz < half of 100


def test_fault_codes_fail_on_a_hard_fault_and_warn_on_a_busy_limiter():
    run = tape()
    fault = np.zeros(run.t.size)
    fault[100:110] = 102  # torque cap on 10/600 rows = 1.7 %: under the 2 % warn
    assert evaluate("stock.fault_codes", FaultCodesConfig(), [replace(run, fault=fault)], subject="s").verdict == PASS
    fault[100:200] = 102
    assert evaluate("stock.fault_codes", FaultCodesConfig(), [replace(run, fault=fault)], subject="s").code == "LimiterEngaged"
    mode = run.mode.copy()
    mode[300:] = 1
    fault[300:] = 33
    out = evaluate("stock.fault_codes", FaultCodesConfig(), [replace(run, fault=fault, mode=mode)], subject="s")
    assert (out.verdict, out.code, out.value) == (FAIL, "HardFault", 1)


def test_coverage_counts_visited_cells():
    run = tape()
    out = evaluate("stock.coverage", CoverageConfig(x_range=(0.0, 2.0), y_range=(-1.0, 1.0), bins=(4, 2), min_samples=1), [run], subject="s")
    assert out.value == pytest.approx(4 / 8)  # q spans the 4 x bins; qd is 0 or +0.5, the upper half only


def test_rollup_is_the_spider_rule_and_names_its_causes():
    a = evaluate("stock.tracking_error", TrackingErrorConfig(limits=Limits.at_most(1.0)), [tape(offset=0.003)], subject="rack/can12")
    b = evaluate("stock.tracking_error", TrackingErrorConfig(limits=Limits.at_most(1.0)), [tape()], subject="rack/can13")
    strict = evaluate("stock.rollup", RollupConfig(), [a, b], subject="rack")
    spider = evaluate("stock.rollup", RollupConfig(tolerate_fail=1), [a, b], subject="rack")
    assert (strict.verdict, spider.verdict, strict.caused_by) == (FAIL, WARN, ("rack/can12",))
    matrix = evaluate("stock.gate_matrix", GateMatrixConfig(gates=("T4", "T6")), [("can12", "T4", a), ("can13", "T4", b)], subject="rack")
    assert matrix.value == 1 and matrix.payload["cells"] == [["fail", "not_run"], ["pass", "not_run"]]


def test_the_robotdx_consumer_windows_a_stream_into_records():
    pairs = monitor("stock.box", BoxConfig(max=Limits.at_most(70.0)), tape(), subject="host/can14", window_s=1.0, step_s=1.0, wall_start=1e9)
    assert len(pairs) == 5  # t runs 0 .. 5.99 s: five whole 1 s windows
    result, record = pairs[-1]
    assert record["expected_period_s"] == 1.0 and record["stamp"] == pytest.approx(1e9 + 5.0)
    assert from_record(to_record(result)) == result
