"""metrics.series.repeat_floor: a floor is made only of SAME-INPUT repeats (2026-11-11 review: 55 of CAN 15's 60 "repeat pairs" had
different commanded inputs, up to 143 deg apart, and the floor they made let a twin read 0.40x when it was 2.6x).

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_repeat_floor.py
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim2real.metrics.series import SAME_INPUT_TOLERANCE_RAD, repeat_floor

T = np.linspace(0.0, 4.0, 2001)


def run(amplitude: float, seed: int, noise: float = 1e-4):
    command = amplitude * np.sin(2 * math.pi * 0.5 * T)
    response = command + np.random.default_rng(seed).normal(0.0, noise, T.size)
    return T, command, response


def test_pairs_with_different_commands_never_count():
    same = [run(0.5, seed) for seed in range(6)]
    other = [run(0.5 + 0.2 * k, 100 + k) for k in range(1, 4)]  # commands 0.2..0.6 rad off: not repeats
    floor = repeat_floor(same + other)
    assert floor.runs == 6 and floor.pairs == 15
    assert floor.rejected == len(list(range(9))) * 8 // 2 - 15
    assert math.isclose(floor.value, math.sqrt(2) * 1e-4, rel_tol=0.15)   # two independent noises: sqrt(2) sigma


def test_only_different_inputs_is_unknown_not_a_number():
    floor = repeat_floor([run(0.3 * k, k) for k in range(1, 4)])
    assert floor.pairs == 0 and floor.value is None and not floor.known


def test_too_few_repeats_report_their_number_but_are_not_known():
    floor = repeat_floor([run(0.5, seed) for seed in range(3)])
    assert floor.pairs == 3 and floor.runs == 3 and floor.value is not None and not floor.known


def test_the_tolerance_is_a_hundredth_of_a_degree():
    assert math.isclose(SAME_INPUT_TOLERANCE_RAD, math.radians(0.01))
    nearly = [run(0.5, 0), (T, 0.5 * np.sin(2 * math.pi * 0.5 * T) + math.radians(0.02), run(0.5, 1)[2])]
    assert repeat_floor(nearly).pairs == 0


def jittered(seed: int, noise: float = 1e-4):
    """One tape played on a host whose clock jitters: the same command per plan tick, sent at wall times off by up to 8 ms."""
    rng = np.random.default_rng(seed)
    command = 0.5 * np.sin(2 * math.pi * 0.5 * T)
    wall = T + np.cumsum(rng.uniform(-1e-3, 3e-3, T.size)).clip(0) * 0.05 + rng.uniform(0, 8e-3, T.size)
    response = command + rng.normal(0.0, noise, T.size)
    return np.sort(wall) - wall.min(), command, response, np.arange(T.size)


def test_inputs_are_compared_on_the_tick_clock_when_the_runs_carry_one():
    # WHY (2026-11-11, the five-bar's 5 repeats): on the host wall clock jitter puts identical tapes 1.6-3.1 deg apart; per plan tick they
    # are the same input, so the pairs count and the floor is the response's own scatter
    runs = [jittered(seed) for seed in range(5)]
    floor = repeat_floor(runs)
    assert floor.pairs == 10 and floor.runs == 5 and floor.known
    assert math.isclose(floor.value, math.sqrt(2) * 1e-4, rel_tol=0.2)


def test_without_a_tick_clock_the_wall_clock_still_decides():
    runs = [jittered(seed)[:3] for seed in range(5)]   # the same runs, no tick: aligned by wall time, the jitter separates them
    assert repeat_floor(runs).pairs == 0


# ---------------------------------------------------------------- the whole command (found in review, 2026-11-12)
#
# A position command is its position, its velocity and its feed-forward torque. Compared on the position alone, five runs with identical
# position targets but velocity targets 0-4 rad/s were accepted as same-input repeats (10 of 10 pairs) and made a "known" floor. A run may now
# carry its command as {channel: values}, each channel judged in its own unit against its own tolerance; a single series is unchanged.

from sim2real.metrics import series  # noqa: E402

TICKS = np.arange(T.size)


def tolerances() -> dict:
    """Each channel's same-input tolerance in its own unit (looked up at call time, so the file collects before they exist)."""
    return {"q": series.SAME_INPUT_TOLERANCE_RAD, "qd": series.SAME_INPUT_TOLERANCE_RAD_S, "ff": series.SAME_INPUT_TOLERANCE_NM}


def command_rms(a, b):
    return series.command_rms(a, b)


def channels(seed: int, *, qd_offset: float = 0.0, ff_offset: float = 0.0, noise: float = 1e-4, tick: bool = True):
    """One repeat of a 0.5 Hz sine tape as a multi-channel command: q (rad), qd (rad/s) and a Coulomb-like feed-forward (N.m), response noisy."""
    w = 2 * math.pi * 0.5
    q = 0.5 * np.sin(w * T)
    qd = 0.5 * w * np.cos(w * T) + qd_offset
    ff = 0.07 * np.tanh(qd / 0.05) + ff_offset
    response = q + np.random.default_rng(seed).normal(0.0, noise, T.size)
    command = {"q": q, "qd": qd, "ff": ff}
    return (T, command, response, TICKS) if tick else (T, command, response)


def test_identical_positions_with_different_velocity_targets_are_not_the_same_input():
    """The review's fixture: the same q on every tick, velocity targets 0-4 rad/s apart. Every pair is a different input; no floor."""
    runs = [channels(seed, qd_offset=float(seed)) for seed in range(5)]   # qd offsets 0, 1, 2, 3, 4 rad/s
    floor = repeat_floor(runs, tolerance=tolerances())
    assert floor.pairs == 0 and floor.rejected == 10 and floor.value is None and not floor.known
    assert floor.rejected_by == {"qd": 10}
    # the position alone would have taken all ten (what the scorer did)
    position_only = [(t, command["q"], response, tick) for t, command, response, tick in runs]
    assert repeat_floor(position_only).pairs == 10


def test_true_repeats_of_the_whole_command_keep_the_same_floor():
    runs = [channels(seed) for seed in range(5)]
    floor = repeat_floor(runs, tolerance=tolerances())
    assert floor.pairs == 10 and floor.runs == 5 and floor.known and floor.rejected_by == {}
    position_only = repeat_floor([(t, command["q"], response, tick) for t, command, response, tick in runs])
    assert floor.value == position_only.value      # the response is compared exactly as before


def test_each_channel_is_judged_in_its_own_unit():
    assert math.isclose(series.SAME_INPUT_TOLERANCE_RAD_S, math.radians(1.0)) and series.SAME_INPUT_TOLERANCE_NM == 1e-3
    base = channels(0)
    for name, inside, outside in (("qd", math.radians(0.5), math.radians(2.0)), ("ff", 0.5e-3, 2e-3)):
        near = channels(1, **{f"{name}_offset": inside})
        far = channels(1, **{f"{name}_offset": outside})
        assert repeat_floor([base, near], tolerance=tolerances()).pairs == 1, name
        far_floor = repeat_floor([base, far], tolerance=tolerances())
        assert far_floor.pairs == 0 and far_floor.rejected_by == {name: 1}, name


def test_command_rms_reports_every_channel_on_the_common_ticks():
    a, b = channels(0), channels(1, qd_offset=0.25, tick=True)
    skipped = (b[0][5:], {name: values[5:] for name, values in b[1].items()}, b[2][5:], b[3][5:])  # b starts 5 ticks late
    differences = command_rms(a, skipped)
    assert set(differences) == {"q", "qd", "ff"}
    assert differences["q"] == 0.0 and math.isclose(differences["qd"], 0.25, rel_tol=1e-12)
    assert command_rms(run(0.5, 0), run(0.5, 1)) == {"command": 0.0}  # a single series is the one channel "command"


def test_a_run_whose_channels_differ_is_never_the_same_input():
    a = channels(0)
    b = channels(1)
    fewer = (b[0], {"q": b[1]["q"], "qd": b[1]["qd"]}, b[2], b[3])    # no feed-forward channel: not the command a sent
    floor = repeat_floor([a, fewer], tolerance=tolerances())
    assert floor.pairs == 0 and floor.rejected == 1 and floor.rejected_by == {"channels": 1}
    assert command_rms(a, fewer) is None


def test_a_multi_channel_command_needs_a_tolerance_in_each_channels_unit():
    runs = [channels(seed) for seed in range(2)]
    with pytest.raises(ValueError, match="per channel"):
        repeat_floor(runs)                                              # one number for three units
    with pytest.raises(ValueError, match="ff"):
        repeat_floor(runs, tolerance={"q": series.SAME_INPUT_TOLERANCE_RAD, "qd": series.SAME_INPUT_TOLERANCE_RAD_S})


def test_without_a_tick_the_channels_are_compared_on_the_common_clock():
    same = [channels(seed, tick=False) for seed in range(3)]
    assert repeat_floor(same, tolerance=tolerances(), min_repeats=3).pairs == 3
    apart = [channels(seed, qd_offset=0.5 * seed, tick=False) for seed in range(3)]
    floor = repeat_floor(apart, tolerance=tolerances())
    assert floor.pairs == 0 and floor.rejected_by == {"qd": 3}


def test_a_single_series_command_is_unchanged():
    runs = [run(0.5, seed) for seed in range(6)] + [run(0.7, 9)]
    single = repeat_floor(runs)
    named = repeat_floor([(t, {"q": c}, y) for t, c, y in runs], tolerance={"q": SAME_INPUT_TOLERANCE_RAD})
    assert (single.value, single.pairs, single.runs, single.rejected) == (named.value, named.pairs, named.runs, named.rejected)
    assert single.rejected_by == {"command": 6} and named.rejected_by == {"q": 6}
