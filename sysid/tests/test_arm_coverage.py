"""The UR examples' schedules meet the arm card's own coverage gate, and stay physically plausible doing it.

Written before the schedule that passes it (2026-11-05, arm-coverage lane). The ruler is the card's, read here, never copied:
type_cards' arm_6dof card (its coverage function, its gate_pct, and the min_pct / min_samples of every physics rung sysid fits
on it) judges the train split of each UR example's plan. The schedule that meets it must also be one a real UR5e on a floor could
run: every commanded sample inside Menagerie's joint ranges, at most Universal Robots' 180 deg/s per joint (ur_description
config/ur5e/joint_limits.yaml, every joint), and no sample where MuJoCo finds the arm in the floor (its base's mounting plane, z = 0)
or in itself. The collision check is this file's own (MuJoCo's mj_collision on Menagerie's collision geoms), not the planner's.

    env -u VIRTUAL_ENV /home/bam/bam_ws/src/dev/bam_rack_twin/.venv/bin/python -m pytest -q -p no:cacheprovider /home/bam/sim2real/sysid/tests/test_arm_coverage.py
"""

from __future__ import annotations

import importlib
import math

import numpy as np
import pytest

UR_EXAMPLES = ("ur5e", "ur5e_2f85")
UR_SPEED_RAD_S = math.pi        # ur_description ur5e joint_limits.yaml: max_velocity 180 deg on every joint
COVERAGE_EVERY = 25             # the coverage rule's stride (every 50 ms at 500 Hz): sysid.arm.arm_coverage
_PLANS: dict = {}


def plan_of(example: str):
    if example not in _PLANS:
        from sysid import describe
        description = describe.load(example)
        _PLANS[example] = (description, importlib.import_module(f"sysid.examples.{example}.pipeline").plan(description))
    return _PLANS[example]


def trajectories(p, split: str) -> list[np.ndarray]:
    """Every commanded joint trajectory of a split: the identification excitations and any coverage sweep."""
    return list(getattr(p, f"excitations_{split}")) + list(getattr(p, f"sweep_{split}", None) or [])


def card_need():
    """The arm card's gate: its gate_pct, and the strictest min_pct / min_samples among the physics rungs sysid fits."""
    from type_cards import registry as reg
    card = reg.CARDS["arm_6dof"]
    physics = [r.needs for r in card.rungs if r.kind == "physics" and r.needs is not None]
    assert physics, "the arm card has no physics rung with a coverage need"
    return card, max([card.coverage.gate_pct] + [n.min_pct for n in physics]), max(n.min_samples for n in physics)


@pytest.mark.parametrize("example", UR_EXAMPLES)
def test_the_train_schedule_meets_the_arm_cards_coverage_gate(example):
    from type_cards import coverage as cov
    from type_cards import registry as reg

    _, p = plan_of(example)
    card, min_pct, min_samples = card_need()
    points = [{"joint space": tuple(q)} for q in p.poses_train]
    for e in trajectories(p, "train"):
        points.extend({"joint space": tuple(q)} for q in e[::COVERAGE_EVERY])
    # WHY the mount's mask (2026-11-05, docs/decision-arm-reachable-coverage-2026-11-05.md; was "== 4096", the whole box): the card
    # counts over the cells the mounted arm can reach, and the 2F-85 example's arm carries its gripper
    result = card.coverage.measure(points, mount=p.mount)
    reach = cov.arm_reachable_cells(p.mount)
    counted = sum(1 for cell, c in result.cells.items() if c >= min_samples and cell in reach)
    pct = 100.0 * counted / result.reachable
    assert result.reachable == len(reach) < 4096, f"{example}: the card counts {result.reachable} cells, {p.mount}'s mask holds {len(reach)}"
    assert pct >= min_pct, (f"{example}: train visits {counted} of {result.reachable} cells with >= {min_samples} samples "
                            f"({pct:.2f} %), the arm card's gate is {min_pct:g} %")
    assert reg.coverage_gate(card, result) == "pass"
    assert math.isclose(p.coverage["train"]["pct"], result.pct), f"{example}: the plan reports {p.coverage['train']['pct']} %, the card computes {result.pct} %"


def collision_checker(description):
    """(q) -> None or the first offending pair: Menagerie's collision geoms plus a floor plane at the base's mounting plane."""
    import mujoco

    spec = description.spec()
    floor = spec.worldbody.add_geom()
    floor.name, floor.type, floor.size = "test_floor", mujoco.mjtGeom.mjGEOM_PLANE, [5.0, 5.0, 0.1]
    model = spec.compile()
    data = mujoco.MjData(model)
    qadr = model.jnt_qposadr[[model.joint(f"{j}_joint").id for j in ("shoulder_pan", "shoulder_lift", "elbow", "wrist_1", "wrist_2", "wrist_3")]]
    gripper = {b for b in range(model.nbody) if model.body(b).name.startswith("grip_")}
    rest = data.qpos.copy()

    def check(q):
        data.qpos[:] = rest
        data.qpos[qadr] = q
        mujoco.mj_kinematics(model, data)
        mujoco.mj_collision(model, data)
        for c in data.contact[: data.ncon]:
            b1, b2 = model.geom_bodyid[c.geom1], model.geom_bodyid[c.geom2]
            if b1 in gripper and b2 in gripper:  # the 2F-85's own linkage touches itself by design
                continue
            if c.dist < 0:
                return f"{model.body(b1).name or 'floor'} | {model.body(b2).name or 'floor'}"
        return None

    return check


@pytest.mark.parametrize("example", UR_EXAMPLES)
def test_the_schedule_is_one_a_floor_mounted_ur5e_can_run(example):
    from sysid import arm

    description, p = plan_of(example)
    import mujoco  # noqa: F401
    model = arm.ArmModel.build(description).model
    lo, hi = np.array([model.jnt_range[model.joint(f"{j}_joint").id] for j in arm.JOINTS]).T
    check = collision_checker(description)
    for split in ("train", "held_out"):
        for k, q in enumerate(getattr(p, f"poses_{split}")):
            assert np.all(q >= lo) and np.all(q <= hi), f"{example} {split} pose {k} outside the joint ranges"
            hit = check(q)
            assert hit is None, f"{example} {split} pose {k} collides: {hit}"
        for k, e in enumerate(trajectories(p, split)):
            assert np.all(e >= lo) and np.all(e <= hi), f"{example} {split} trajectory {k} leaves the joint ranges"
            speed = np.abs(np.diff(e, axis=0)).max() / arm.DT
            assert speed <= UR_SPEED_RAD_S + 1e-9, f"{example} {split} trajectory {k} commands {speed:.3f} rad/s, UR's limit is {UR_SPEED_RAD_S:.3f}"
            for i in range(0, e.shape[0], 5):  # every 10 ms
                hit = check(e[i])
                assert hit is None, f"{example} {split} trajectory {k} collides at {i * arm.DT:.2f} s: {hit}"


@pytest.mark.parametrize("example", UR_EXAMPLES)
def test_the_schedule_states_its_duration(example):
    """The plan says how long it takes: every commanded second and every settle, so the report's duration is the plan's."""
    from sysid import arm

    _, p = plan_of(example)
    for split in ("train", "held_out"):
        motion = sum(e.shape[0] for e in trajectories(p, split)) * arm.DT
        assert p.coverage[split].get("motion_s") is not None and math.isclose(p.coverage[split]["motion_s"], round(motion, 1), abs_tol=0.05)


@pytest.mark.parametrize("example", UR_EXAMPLES)
def test_the_sweep_stops_at_the_cards_gate_plus_its_margin(example):
    """The sweep's target is a share of the mount's reachable cells, a stated margin above the card's gate, and the train split
    stops near it: the schedule is as long as the gate needs, not the old box target's 1,721 cells.

    Written before the code (2026-11-05, sweep-trim lane): the gate moved to 40 % of the 2,560 reachable cells (1,024) while the
    sweep still ran to 42 % of the 4,096-cell box (1,721 cells, 67 % of reachable), about 15 min of motion for coverage the card
    no longer asks for."""
    from type_cards import coverage as cov

    _, p = plan_of(example)
    card, min_pct, _ = card_need()
    sweep = p.sweep
    reachable = len(cov.arm_reachable_cells(p.mount))
    margin = sweep["target_pct"] - min_pct
    assert 0 < margin <= 5, f"{example}: the sweep targets {sweep['target_pct']} %, the gate is {min_pct:g} %: the margin must be stated and small"
    assert sweep["target_of"] == "reachable cells" and sweep["reachable_cells"] == reachable
    assert sweep["target_cells"] == math.ceil(sweep["target_pct"] / 100.0 * reachable), f"{example}: target {sweep['target_cells']} cells"
    assert min_pct <= p.coverage["train"]["pct"] < sweep["target_pct"] + 2.0, (
        f"{example}: train covers {p.coverage['train']['pct']} % of reachable, the sweep targets {sweep['target_pct']} %")
