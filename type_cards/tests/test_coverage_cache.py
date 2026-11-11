"""The 1-DOF joint's reachable cells are computed once per joint description (coverage.reachable_cells, memoized on the whole
description), and every coverage number is the same with the cache as without it. Written before the cache (2026-11-07): the run page
computes a selection of one per run, 2239 of them, and each call rebuilt the same reachable set over all 2016 cells (19 s of a 35 s
site build).

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --with pytest pytest -q /home/bam/sim2real/type_cards/tests/test_coverage_cache.py
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from type_cards import coverage as cov  # noqa: E402

SCHEDULES = Path("/archive/datasets/bam_rig/schedules/one-dof-test-rack")
FIXTURE = {"name": "a", "range_rad": [-1.0, 1.0], "speed_rad_s": 1.0, "accel_rad_s2": 1.0, "torque_limit_nm": 2.0, "origin_rad": 0.1,
           "inertia_kg_m2": 0.5, "gravity_nm": 1.5, "gravity_bottom_rad": 0.2, "coulomb_nm": 0.3}


def descriptions() -> list[dict]:
    """Every rack station's joint description (its live schedule's), and the fixture (a gravity load that leaves cells unreachable)."""
    out = [FIXTURE]
    for path in sorted(SCHEDULES.glob("*/schedule.json")) if SCHEDULES.is_dir() else []:
        out.append(json.loads(path.read_text())["description"])
    return out


def per_call(d: dict) -> set:
    """The reachable cells as binned built them on every call before the cache (the ruler's own copy of that rule)."""
    edges, ok = cov.joint_edges(d), cov.joint_reachable(d)
    grid = [cov.centres(a) for a in edges]
    return {cell for cell in itertools.product(*(range(cov.n_cells(a)) for a in edges)) if ok(tuple(grid[k][i] for k, i in enumerate(cell)))}


def points(d: dict, n: int = 400) -> list[dict]:
    """Points spread over and just past the joint's range, speed and acceleration (some outside: dropped and counted)."""
    lo, hi = d["range_rad"]
    out = []
    for k in range(n):
        f = k / (n - 1)
        out.append({"q": lo - 0.05 + (hi - lo + 0.1) * f, "qd": d["speed_rad_s"] * 1.1 * math.sin(7.0 * f * math.pi),
                    "qdd": d["accel_rad_s2"] * 1.1 * math.cos(5.0 * f * math.pi), "load torque": d["torque_limit_nm"] * math.sin(3.0 * f)})
    return out


def test_the_cached_cells_are_the_rules_cells():
    for d in descriptions():
        assert set(cov.reachable_cells(d)) == per_call(d), d.get("name")


def test_a_description_is_computed_once_and_any_change_is_a_new_one():
    cov.reachable_cells.cache_clear()
    d = dict(FIXTURE)
    first = cov.reachable_cells(d)
    again = cov.reachable_cells(json.loads(json.dumps(d)))  # an equal description read again: the same cells, not computed again
    info = cov.reachable_cells.cache_info()
    assert again == first and info.misses == 1 and info.hits == 1
    # any field of the description is part of the key: a weaker joint (a torque limit the fixture's gravity load passes) is a new set
    weaker = {**d, "torque_limit_nm": 0.6}
    assert cov.reachable_cells(weaker) == per_call(weaker) != first and cov.reachable_cells.cache_info().misses == 2
    assert cov.reachable_cells.cache_info().maxsize is not None, "the cache is bounded"


def test_every_coverage_number_is_the_same_with_the_cache():
    for d in descriptions():
        pts = points(d)
        got = cov.actuator_coverage(pts, d)
        want = cov.binned([(p["q"], p["qd"], p["qdd"]) for p in pts], cov.joint_edges(d), cov.joint_reachable(d))
        assert (got.pct, got.visited, got.reachable, got.samples, got.outside, got.cells) == \
            (want.pct, want.visited, want.reachable, want.samples, want.outside, want.cells), d.get("name")
