"""metrics.series.on_common_clock / pair_rms over the series' real overlap (2026-11-12 verify of claude/fivebar-target-sim-real: a held-out
window that starts 30 s into a run was put on arange(0, end) and np.interp held the 30 s sample across 0-30 s, adding 30 s of a constant
offset to the 'held-out' RMS)."""

import numpy as np

from sim2real.metrics.series import on_common_clock, pair_rms


def _series(t0: float, t1: float, offset: float = 0.0, dt: float = 0.002):
    t = np.arange(t0, t1, dt)
    return t, np.sin(t) + offset


def test_a_window_that_starts_late_is_scored_only_over_its_samples():
    a = _series(30.0, 40.0)
    b = _series(30.0, 40.0, offset=0.01)
    assert abs(pair_rms(a, b) - 0.01) < 1e-9


def test_the_grid_spans_only_the_overlap_of_two_offset_windows():
    a, b = _series(30.0, 40.0), _series(32.0, 45.0)
    y_a, y_b = on_common_clock(a, b, 0.002)
    assert len(y_a) == len(y_b) == len(np.arange(32.0, a[0][-1], 0.002))
    assert np.allclose(y_a, y_b, atol=1e-5)


def test_series_from_zero_are_unchanged():
    a, b = _series(0.0, 5.0), _series(0.0, 6.0, offset=0.02)
    assert abs(pair_rms(a, b) - 0.02) < 1e-9


def test_two_identical_signals_starting_at_different_ticks_score_zero():
    a, b = _series(30.0, 40.0), _series(30.5, 40.0)
    assert pair_rms(a, b) < 1e-5
