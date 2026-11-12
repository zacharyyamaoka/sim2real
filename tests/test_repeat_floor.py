"""metrics.series.repeat_floor: a floor is made only of SAME-INPUT repeats (2026-11-11 review: 55 of CAN 15's 60 "repeat pairs" had
different commanded inputs, up to 143 deg apart, and the floor they made let a twin read 0.40x when it was 2.6x).

    env -u VIRTUAL_ENV uv run --project /home/bam/sim2real --extra test pytest -q /home/bam/sim2real/tests/test_repeat_floor.py
"""

from __future__ import annotations

import math

import numpy as np

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
