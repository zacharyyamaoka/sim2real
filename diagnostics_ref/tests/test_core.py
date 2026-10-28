"""The shared shapes: limits, verdicts, the Result's own rules, the registry and configs as data."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from robotdx.diagnostics import FAIL, NOT_RUN, PASS, WARN, Limits, Result, config_from_dict, evaluate, judge, names, worst
from robotdx.diagnostics.core import HINTS, result
from robotdx.diagnostics.registry import REGISTRY, Spec, load_toml, register
from robotdx.diagnostics.stock import BoxConfig, CoverageConfig, StopErrorConfig, stop_error

from conftest import tape


def test_a_value_on_the_limit_is_inside_and_beyond_it_trips():
    limits = Limits.at_most(3.6, warn=3.0)
    assert judge(3.6, limits) == (WARN, "AboveWarnLimit")
    assert judge(3.6000001, limits) == (FAIL, "AboveErrorLimit")
    assert judge(3.0, limits) == (PASS, "")


def test_zero_is_a_real_limit_not_skip():
    # WHY: the old bam_diagnostics read warn = error = 0 as "SKIPPING" and reported OK
    assert judge(-0.5, Limits.at_least(0.0)) == (FAIL, "BelowErrorLimit")


def test_no_value_is_not_run_never_pass():
    for value in (None, math.nan, math.inf):
        assert judge(value, Limits.at_most(1.0))[0] == NOT_RUN
    assert worst([PASS, NOT_RUN]) == NOT_RUN and worst([NOT_RUN, FAIL]) == FAIL and worst([]) == NOT_RUN


def test_limits_must_be_ordered():
    with pytest.raises(ValueError):
        Limits(warn_high=5.0, error_high=4.0)


def test_a_non_pass_result_needs_a_code_and_a_known_view():
    with pytest.raises(ValueError):
        Result(diagnostic="x", title="x", verdict=FAIL, value=1.0, unit="1")
    with pytest.raises(ValueError):
        Result(diagnostic="x", title="x", verdict=PASS, value=1.0, unit="1", hint="pie_chart")
    assert set(HINTS) == {"gate_matrix", "threshold_band", "kpi_trend", "rollup_tree", "evidence", "distribution", "level_history", "path_overlay"}


def test_every_stock_spec_carries_a_view_hint_and_a_shape():
    for name in names():
        spec = REGISTRY[name]
        assert spec.hint in HINTS and spec.emits in ("series", "matrix", "scalar"), name
        if spec.view_extra:
            assert len(spec.view_extra) > 20, f"{name}: view_extra needs its one-line reason"


def test_evaluate_stamps_registry_facts_and_refuses_the_wrong_config():
    out = evaluate("stock.stop_error", StopErrorConfig(), [tape()], subject="rack/can14", stamp=1.0)
    assert (out.diagnostic, out.subject, out.hint, out.emits, out.family, out.stamp) == (
        "stock.stop_error", "rack/can14", "distribution", "series", "real_vs_target", 1.0)
    with pytest.raises(TypeError):
        evaluate("stock.stop_error", BoxConfig(), [tape()], subject="rack/can14")


def test_configs_round_trip_through_plain_data():
    config = StopErrorConfig(limits=Limits.at_most(3.6), side="output")
    out = evaluate("stock.stop_error", config, [tape()], subject="s")
    assert config_from_dict(StopErrorConfig, out.config) == config
    coverage = CoverageConfig(x_range=(-1.0, 1.0), bins=(4, 4))
    assert config_from_dict(CoverageConfig, {"x_range": [-1.0, 1.0], "bins": [4, 4]}) == coverage
    with pytest.raises(ValueError):
        config_from_dict(StopErrorConfig, {"dwell_s": 1.0})


@dataclass(frozen=True)
class DoubleStopConfig:
    limits: Limits = field(default_factory=Limits)


def double_stop(config, runs):
    inner = stop_error(StopErrorConfig(limits=config.limits), runs)
    return result(config, value=2 * inner.value, unit="mrad", metric="double", limits=config.limits, title="double", message="x2",
                  payload=inner.payload)


def test_a_custom_diagnostic_registers_from_toml(tmp_path: Path):
    (tmp_path / "custom.toml").write_text(
        '[[diagnostic]]\nname = "rack.double_stop"\nfunction = "test_core:double_stop"\nconfig = "test_core:DoubleStopConfig"\n'
        'title = "double stop"\nfamily = "real_vs_target"\nrole = "driver"\nhint = "distribution"\nemits = "series"\nunit = "mrad"\n')
    registry: dict[str, Spec] = {}
    specs = load_toml(tmp_path / "custom.toml", registry=registry)
    assert [spec.name for spec in specs] == ["rack.double_stop"]
    register(specs[0])
    try:
        out = evaluate("rack.double_stop", DoubleStopConfig(), [tape(offset=0.002)], subject="s")
        assert out.value == pytest.approx(4.0)
    finally:
        REGISTRY.pop("rack.double_stop")


def test_a_spec_refuses_an_unknown_view():
    with pytest.raises(ValueError):
        Spec("bad", double_stop, DoubleStopConfig, "bad", "health", "health", "pie_chart", "scalar", "1")
