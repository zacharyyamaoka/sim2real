"""The arm card's reachable-cell masks: which of the joint cube's 4,096 cells a mounted arm can actually be in.

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python /home/bam/sim2real/tools/arm_reachable.py --write

writes type_cards/arm_reachable/<mount>.json for every mount; without --write it prints each mask's count and whether the committed
file matches. sysid/tests/test_arm_reachable_mask.py holds the committed files to compute().

A cell is reachable when a configuration inside it clears the floor by 5 cm and the arm itself by 1 cm (sysid.arm.Clearance:
MuJoCo's mj_collision on the description's collision geoms plus a floor plane at the base's mounting plane, the check the UR
schedules are planned and tested with) AND its shoulder lift lies in the span connected to the arm's home posture.

1. The lift span: the shoulder lift on a 0.01 rad grid over its range; a lift value is clear when any of a fixed probe of the other
   five joints (scrambled Sobol, 2^9, seed 0) is collision-free there; the span is the run of clear values around home's lift.
2. Each cell: a fixed scrambled Sobol probe (2^10 points, seed 0, the same unit points scaled into every cell, the lift slice
   clipped to the span); the cell is reachable at its first collision-free point. Cells whose lift slice misses the span are not.

WHY a span connected to home and not every collision-free cell (the UR coverage lane, 2026-11-05): the shoulder lift's range is
+-2 pi, so a lift posture and the same posture 2 pi away are both collision-free, but going from one to the other swings the upper
arm through the floor; an installed arm only ever holds one of them. WHY a probe per cell and not one shared pool: a shared
2^17 pool (the coverage sweep's) put only a few points in each cell whose lift slice is a 0.2 rad sliver past horizontal and found
2,092 / 2,073 cells; per cell, both mounts reach 2,560 by 2^8 / 2^10 points and no more at 2^12 (measured 2026-11-05).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "type_cards" / "arm_reachable"
MOUNTS = {"ur5e_floor": "ur5e", "ur5e_2f85_floor": "ur5e_2f85"}  # mount -> the sysid example whose description it is
LIFT = 1
LIFT_STEP_RAD = 0.01
LIFT_PROBE_LOG2 = 9
CELL_PROBE_LOG2 = 10
PROBE_SEED = 0


def lift_span(clear, limits: np.ndarray, home_lift: float) -> tuple[float, float]:
    from scipy.stats import qmc  # noqa: PLC0415

    others = [j for j in range(limits.shape[0]) if j != LIFT]
    probe = qmc.scale(qmc.Sobol(len(others), scramble=True, seed=PROBE_SEED).random_base2(LIFT_PROBE_LOG2), limits[others, 0], limits[others, 1])
    lo, hi = limits[LIFT]
    lifts = np.round(np.arange(lo, hi + 1e-9, LIFT_STEP_RAD), 2)
    ok = np.array([any(clear(np.insert(o, LIFT, th)) for o in probe) for th in lifts])
    home = int(np.argmin(np.abs(lifts - home_lift)))
    if not ok[home]:
        raise RuntimeError(f"no clear configuration at home's lift {home_lift}")
    a = b = home
    while a > 0 and ok[a - 1]:
        a -= 1
    while b < len(lifts) - 1 and ok[b + 1]:
        b += 1
    return float(lifts[a]), float(lifts[b])


def compute(mount: str) -> dict:
    import mujoco  # noqa: PLC0415
    import scipy  # noqa: PLC0415
    from scipy.stats import qmc  # noqa: PLC0415

    from sysid import arm, describe  # noqa: PLC0415
    from type_cards import coverage as cov  # noqa: PLC0415

    example = MOUNTS[mount]
    clear = arm.Clearance(describe.load(example))
    limits = np.array(cov.UR5E_LIMITS, float)
    bins = cov.JOINT_BINS
    home_lift = float(arm.ArmPlan.__dataclass_fields__["hold"].default_factory()[LIFT])
    span = lift_span(clear, limits, home_lift)
    edges = np.array([np.linspace(lo, hi, bins + 1) for lo, hi in limits])
    unit = qmc.Sobol(limits.shape[0], scramble=True, seed=PROBE_SEED).random_base2(CELL_PROBE_LOG2)
    rows = np.arange(limits.shape[0])
    bits = []
    for cell in itertools.product(range(bins), repeat=limits.shape[0]):
        idx = np.array(cell)
        lo, hi = edges[rows, idx].copy(), edges[rows, idx + 1].copy()
        lo[LIFT], hi[LIFT] = max(lo[LIFT], span[0]), min(hi[LIFT], span[1])
        bits.append("1" if lo[LIFT] < hi[LIFT] and any(clear(q) for q in lo + unit * (hi - lo)) else "0")
    mask = "".join(bits)
    return {"mount": mount, "example": example, "arm": "UR5e, MuJoCo Menagerie's collision geoms" + (" + Robotiq 2F-85" if "2f85" in mount else ""),
            "mounted_on": "a floor plane at the base's mounting plane", "limits": [list(x) for x in cov.UR5E_LIMITS], "joint_bins": bins,
            "cell_order": "itertools.product(range(joint_bins), repeat=6): joint 1 (shoulder pan) most significant",
            "reachable": mask.count("1"), "sha256": hashlib.sha256(mask.encode()).hexdigest(),
            "floor_clearance_m": clear.floor_m, "self_clearance_m": clear.self_m, "home_lift_rad": home_lift, "lift_span_rad": list(span),
            "lift_probe": {"step_rad": LIFT_STEP_RAD, "sobol_log2": LIFT_PROBE_LOG2, "seed": PROBE_SEED, "scramble": True},
            "probe": {"sobol_log2": CELL_PROBE_LOG2, "seed": PROBE_SEED, "scramble": True, "per_cell": True},
            "rule": "a cell is reachable when a configuration inside it (lift clipped to the span connected to home) clears the floor and the arm",
            "generator": "tools/arm_reachable.py", "versions": {"mujoco": mujoco.__version__, "scipy": scipy.__version__, "numpy": np.__version__},
            "mask": mask}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write type_cards/arm_reachable/<mount>.json")
    ap.add_argument("mounts", nargs="*", default=sorted(MOUNTS))
    args = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for mount in args.mounts:
        doc = compute(mount)
        path = OUT / f"{mount}.json"
        same = path.is_file() and json.loads(path.read_text()).get("sha256") == doc["sha256"]
        by_lift = [sum(1 for cell, bit in zip(itertools.product(range(4), repeat=6), doc["mask"]) if bit == "1" and cell[LIFT] == b) for b in range(4)]
        print(f"{mount}: {doc['reachable']} of {len(doc['mask'])} cells, lift span {doc['lift_span_rad']}, by lift bin {by_lift}, "
              f"committed {'matches' if same else 'differs'}")
        if args.write:
            path.write_text(json.dumps(doc, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
