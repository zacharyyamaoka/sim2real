"""The arm card's reachable-cell masks are what the collision model says (2026-11-05, docs/decision-arm-reachable-coverage-2026-11-05.md).
Written before the code.

type_cards is stdlib only, so the masks it counts over are committed files (type_cards/arm_reachable/<mount>.json). Here, with
MuJoCo, tools/arm_reachable.py regenerates each one from its example's collision geoms and the file must equal it bit for bit;
and every sample the UR plans command (each one collision-free, test_arm_coverage.py) must land in a reachable cell, so the mask
never drops a cell a real schedule visits. Slow (the 2F-85's meshes: about 4 min).

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/sysid/tests/test_arm_reachable_mask.py
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
MOUNTS = {"ur5e_floor": "ur5e", "ur5e_2f85_floor": "ur5e_2f85"}


def tool():
    sys.path.insert(0, str(ROOT))
    return importlib.import_module("tools.arm_reachable")


@pytest.mark.parametrize("mount", sorted(MOUNTS))
def test_the_committed_mask_is_the_generators(mount):
    t = tool()
    assert t.MOUNTS == MOUNTS
    committed = json.loads((ROOT / "type_cards" / "arm_reachable" / f"{mount}.json").read_text())
    fresh = t.compute(mount)
    for key in ("mask", "reachable", "sha256", "lift_span_rad", "probe", "lift_probe", "floor_clearance_m", "self_clearance_m", "home_lift_rad"):
        assert fresh[key] == committed[key], (mount, key)


@pytest.mark.parametrize("mount", sorted(MOUNTS))
def test_every_planned_sample_lands_in_a_reachable_cell(mount):
    from sysid import arm, describe
    from type_cards import coverage as cov

    example = MOUNTS[mount]
    description = describe.load(example)
    p = importlib.import_module(f"sysid.examples.{example}.pipeline").plan(description)
    assert p.mount == mount
    reach = cov.arm_reachable_cells(mount)
    edges = [[lo + (hi - lo) * i / cov.JOINT_BINS for i in range(cov.JOINT_BINS + 1)] for lo, hi in cov.UR5E_LIMITS]
    for split in ("train", "held_out"):
        points = arm.coverage_points(getattr(p, f"poses_{split}"), p.trajectories(split))
        cells = {tuple(cov.bin_index(float(v), e) for v, e in zip(q, edges)) for q in np.asarray(points)}
        assert not cells - reach, f"{example} {split}: {len(cells - reach)} visited cells are outside {mount}'s mask, e.g. {sorted(cells - reach)[:3]}"
