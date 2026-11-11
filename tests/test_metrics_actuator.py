"""sim2real.metrics for the actuator: gate(value, target), the series helpers and the actuator verbs, on synthetic data with known answers.

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_metrics_actuator.py

Zach, 2026-11-10 (proposal 2, step 4): metrics is data in, numbers out; tracking error comes from robot_msgs.compare, coverage from
robot_msgs.coverage, and a range check from robot_msgs.space.Space(msg).contains / .violations, with no range type of sim2real's own.
Written before sim2real.metrics held any verb (red first). Every number below is worked by hand or by an outside oracle (robot_msgs,
numpy's own percentile), never by the function under test.
"""

from __future__ import annotations

import math
import subprocess
import sys

import numpy as np
import pytest
from robot_msgs.compare import error_stats
from robot_msgs.coverage import occupancy as rm_occupancy
from robot_msgs.space import Value

from sim2real.metrics import actuator, coverage, series
from sim2real.metrics.gate import Verdict, at_least, at_most, gate, required, rule_of

# --------------------------------------------------------------------------- gate(value, target): a robot_msgs Value's range, through Space


def test_at_most_passes_up_to_and_including_its_limit():
    target = at_most(1.5, "1")
    assert isinstance(target, Value) and target.high == 1.5 and target.low == -math.inf
    assert gate(1.5, target) == Verdict(True, ())
    assert gate(-3.0, target).passes and gate(-math.inf, target).passes
    over = gate(1.5000001, target)
    assert not over.passes and len(over.violations) == 1 and "1.5000001" in over.violations[0]


def test_at_least_passes_from_its_limit_up():
    target = at_least(5, "repeats")
    assert target.low == 5 and target.high == math.inf
    assert gate(5, target).passes and gate(6, target).passes and gate(math.inf, target).passes
    assert not gate(4, target).passes


def test_a_missing_or_non_finite_number_never_passes():
    for value in (None, math.nan):
        assert not gate(value, at_most(1.5)).passes
        assert not gate(value, at_least(5)).passes
    assert gate(None, at_most(1.5)).violations == ("no value",)
    assert not gate(math.inf, at_most(1.5)).passes


def test_required_is_the_boolean_requirement():
    assert gate(True, required()).passes
    assert not gate(False, required()).passes and not gate(None, required()).passes


def test_a_target_without_a_range_is_refused():
    # WHY: Space skips a field with no range, so a plain number as a target would pass everything; a ruler that cannot fail is refused
    for target in (1.5, Value(1.5, "1")):
        with pytest.raises(TypeError):
            gate(1.0, target)


def test_rule_of_names_the_side_and_the_limit_as_given():
    assert rule_of(at_most(1.5)) == ("<=", 1.5)
    assert rule_of(at_least(5)) == (">=", 5) and type(rule_of(at_least(5))[1]) is int
    assert rule_of(required()) == ("==", True)


# --------------------------------------------------------------------------- series: one ruler for real-vs-real and model-vs-real


def test_rms_is_robot_msgs_error_stats_rms_bit_for_bit():
    rng = np.random.default_rng(3)
    for values in (rng.normal(size=1000), rng.normal(size=7) * 1e-3, np.array([2.0])):
        assert series.rms(values) == error_stats(values).rms
    assert math.isnan(series.rms(np.array([])))
    assert math.isnan(series.rms(np.array([1.0, math.nan])))  # an RMS over a gap is no number (as RobotDx's rms always was)


def test_center_is_the_stdlib_median_or_median_high():
    assert series.center([3.0, 1.0, 2.0, 10.0]) == 2.5
    assert series.center([3.0, 1.0, 2.0, 10.0], "median_high") == 3.0
    assert series.center([1.0, None, math.nan, 5.0]) == 3.0
    assert math.isnan(series.center([]))


def test_difference_never_extrapolates():
    t_a, y_a = np.array([0.0, 1.0, 2.0, 3.0]), np.zeros(4)
    t_b, y_b = np.array([0.5, 2.5]), np.array([1.0, 3.0])
    t, gap = series.difference((t_a, y_a), (t_b, y_b))
    assert t.tolist() == [1.0, 2.0] and gap.tolist() == [1.5, 2.5]


def test_pairwise_rms_on_the_common_clock():
    t = np.arange(0.0, 1.0001, 0.001)
    runs = [(t, np.zeros_like(t)), (t, np.full_like(t, 2e-3)), (t, np.full_like(t, -1e-3))]
    pairs = series.pairwise_rms(runs, dt=0.002)
    assert [(i, j) for i, j, _ in pairs] == [(0, 1), (0, 2), (1, 2)]
    assert [round(value, 12) for _, _, value in pairs] == [2e-3, 1e-3, 3e-3]


# --------------------------------------------------------------------------- the actuator verbs


def test_floor_is_the_median_pairwise_rms_scaled():
    t = np.arange(0.0, 2.0, 0.001)
    runs = [(t, np.full_like(t, offset * 1e-3)) for offset in (0.0, 1.0, 3.0, 4.0)]
    value, pairs = actuator.floor(runs)
    # pairs: 1, 3, 4, 2, 3, 1 mrad -> median 2.5
    assert value == pytest.approx(2.5, abs=1e-9)
    assert len(pairs) == 6 and max(scaled for _, _, scaled in pairs) == pytest.approx(4.0, abs=1e-9)


def test_tracking_statistic_comes_from_robot_msgs_compare():
    rng = np.random.default_rng(5)
    error, t = rng.normal(size=500), np.arange(500) * 0.01
    stats = error_stats(error)
    assert actuator.tracking_statistic(error, t, "rms") == stats.rms
    assert actuator.tracking_statistic(error, t, "p95") == stats.p95_abs
    assert actuator.tracking_statistic(error, t, "max") == stats.max_abs
    window = t >= t[-1] - 0.5
    assert actuator.tracking_statistic(error, t, "final", final_window_s=0.5) == float(np.mean(np.abs(error[window])))
    with pytest.raises(ValueError):
        actuator.tracking_statistic(error, t, "median")


def _stop_tape():
    """Move, dwell 1 s at 1.0 (q 2 mrad short), move, dwell 1 s at 0.0 (q 1 mrad past), move, park at 2.0 (never counted on a tape)."""

    t = np.round(np.arange(0.0, 6.0, 0.01), 9)
    q_target, qd_target, q = np.zeros_like(t), np.zeros_like(t), np.zeros_like(t)
    for start, end, frm, to in ((0.0, 1.0, 0.0, 1.0), (2.0, 3.0, 1.0, 0.0), (4.0, 5.0, 0.0, 2.0)):
        inside = (t >= start) & (t < end)
        q_target[inside] = frm + (to - frm) * (t[inside] - start) / (end - start)
        qd_target[inside] = (to - frm) / (end - start)
    q_target[(t >= 1.0) & (t < 2.0)], q_target[(t >= 3.0) & (t < 4.0)], q_target[t >= 5.0] = 1.0, 0.0, 2.0
    q[:] = q_target
    q[(t >= 1.0) & (t < 2.0)] -= 2e-3
    q[(t >= 3.0) & (t < 4.0)] += 1e-3
    return t, q, q_target, qd_target


def test_stops_reads_each_dwell_followed_by_motion():
    t, q, q_target, qd_target = _stop_tape()
    found = actuator.stops(t, q, q_target, qd_target, dwell_min_s=0.25, settle_window_s=0.05)
    assert [round(error, 9) for error, _, _ in found] == [-2.0, 1.0]
    assert [(round(a, 6), round(b, 6)) for _, a, b in found] == [(1.0, 1.99), (3.0, 3.99)]
    # a window cut by the clock: the dwell it ends in is a stop still going
    assert len(actuator.stops(t, q, q_target, qd_target, dwell_min_s=0.25, settle_window_s=0.05, open_end=True)) == 3


def test_stop_summary_is_the_percentile_of_the_magnitudes():
    signed = [-2.0, 1.0, 0.5, -0.25]
    summary = actuator.stop_summary(signed, 90.0)
    magnitudes = np.abs(signed)
    assert summary["value"] == float(np.percentile(magnitudes, 90.0))
    assert summary["n"] == 4 and summary["median"] == 0.75 and summary["max"] == 2.0 and summary["mean_signed"] == -0.1875
    assert summary["worst"] == 0


def test_fidelity_ratios_per_model_and_class():
    rows = [("twin", "r1", "pickplace", 3.0), ("twin", "r2", "pickplace", 6.0), ("twin", "r3", "cycle", 4.0), ("perfect", "r1", "pickplace", 1.0)]
    by, ratios = actuator.fidelity_ratios(rows, 2.0, "median_high")
    assert by[("twin", "pickplace")] == [1.5, 3.0] and ratios[("twin", "pickplace")] == 3.0 and ratios[("twin", "cycle")] == 2.0
    assert ratios[("perfect", "pickplace")] == 0.5
    assert actuator.fidelity_ratios(rows, 2.0, "median")[1][("twin", "pickplace")] == 2.25


def test_move_hold_split_of_a_pair():
    t = np.arange(0.0, 2.0, 0.001)
    speed = np.where(t < 1.0, 1.0, 0.0)  # moving the first second, holding the second
    a = (t, np.where(t < 1.0, 3e-3, 0.0), speed)
    b = (t, np.zeros_like(t), speed)
    parts = actuator.pair_parts(a, b, dt=0.002, hold_speed=0.02, scale=1e3)
    assert parts["moves"] == pytest.approx(3.0, abs=1e-9) and parts["holds"] == pytest.approx(0.0, abs=1e-12)
    assert parts["hold_fraction"] == pytest.approx(0.5, abs=1e-3)


def test_run_parts_on_the_scored_rows():
    real, model = np.zeros(6), np.array([1e-3, 1e-3, 2e-3, 2e-3, 9.0, 9.0])
    rows = np.array([True, True, True, True, False, False])
    hold = np.array([False, False, True, True, False, False])
    parts = actuator.run_parts(real, model, rows, hold, scale=1e3)
    assert parts["moves"] == pytest.approx(1.0) and parts["holds"] == pytest.approx(2.0) and parts["hold_fraction"] == 0.5


def test_rest_holds_fold_to_the_real_side():
    t = np.arange(0.0, 2.0, 0.01)
    target = np.ones_like(t)
    q_real, q_model = target - 2e-3, target - 3e-3  # the real rests 2 mrad short, the model 3 mrad short: model farther, +1 mrad
    holds = actuator.rest_holds(t, target, q_real, q_model, np.ones_like(t, bool), min_hold_s=0.3, tail_s=0.2, scale=1e3)
    assert len(holds) == 1 and holds[0]["model_minus_real"] == pytest.approx(1.0) and holds[0]["real"] == pytest.approx(2.0)
    short = actuator.rest_holds(t[:20], target[:20], q_real[:20], q_model[:20], np.ones(20, bool), min_hold_s=0.3, tail_s=0.2, scale=1e3)
    assert short == []


def test_rest_summary_and_split_ratios():
    d = np.array([1.0, -1.0, 2.0, 3.0])
    summary = actuator.rest_summary(d)
    assert summary["median"] == 1.5 and summary["median_abs"] == 1.5 and summary["farther_fraction"] == 0.75
    assert summary["p10"] == float(np.percentile(d, 10)) and summary["p90"] == float(np.percentile(d, 90))
    assert actuator.split_ratios(3.0, 2.0, -1.0, 4.0) == (1.5, 0.25)


# --------------------------------------------------------------------------- coverage: robot_msgs.coverage's binning


def test_cell_counts_are_robot_msgs_occupancy_and_numpy_histogram2d():
    rng = np.random.default_rng(11)
    x, y = rng.uniform(-4, 4, 3000), rng.uniform(-12, 12, 3000)
    x[:3], y[:3] = [math.pi, 1.0, -math.pi], [10.0, -10.0, 0.0]  # on the last edges, on the first edges
    edges_x, edges_y = np.linspace(-math.pi, math.pi, 17), np.linspace(-10.0, 10.0, 17)
    counts = coverage.cell_counts(x, y, edges_x, edges_y)
    numpy_counts, _, _ = np.histogram2d(x, y, bins=[16, 16], range=[[-math.pi, math.pi], [-10.0, 10.0]])
    assert counts.tolist() == numpy_counts.astype(int).tolist()
    cells, outside = rm_occupancy(list(zip(x.tolist(), y.tolist())), [edges_x.tolist(), edges_y.tolist()])
    assert {cell: int(counts[cell]) for cell in cells} == cells and outside == len(x) - int(counts.sum())
    assert coverage.covered_share(counts, 5) == float(np.mean(numpy_counts >= 5))


# --------------------------------------------------------------------------- the layer: the stable end loads nothing that churns


def test_metrics_loads_no_rack_no_robotdx_and_no_churning_layer():
    probe = ("import sys, sim2real.metrics.actuator, sim2real.metrics.gate, sim2real.metrics.series, sim2real.metrics.coverage, "
             "sim2real.metrics.servo_gates; print(sorted(m for m in sys.modules if m.split('.')[0] in ('bam_rack_twin', 'robotdx') or "
             "m.startswith(('sim2real.cards', 'sim2real.models', 'sim2real.sim', 'sim2real.fit', 'sim2real.schedule'))))")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[]"
