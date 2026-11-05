# Decision: the arm card's coverage counts over reachable cells (2026-11-05)

**Status:** accepted on merge (sim2real main, type_cards contract v3 field `Coverage.reachable_mask`). Decided for Zach by the
arm-reachable lane; his to overrule (undo: `git revert` the merge commits named in the handoff).

## Context

The arm_6dof card bins joint space into a 4^6 = 4,096-cell cube (each joint's range split in 4) and gated a plan at 40 % of
**all** cells, "every cell counted reachable: the limits are a box". The UR coverage lane (sim2real 135c978..99393bf) built a
collision-free sweep to meet it and found:

- The shoulder lift's range is ±2π, so its bin 3 ([π, 2π]) is bin 1 ([−π, 0)) shifted 2π: the same posture, and getting from
  one to the other swings the upper arm through the floor. An installed arm holds one of them. Those 1,024 cells never count.
- Bins 0 and 2 are reachable only as slivers just past horizontal; many cells collide with the floor or the arm itself.

So the 40 % gate (1,639 cells) was really a demand for 64 % of what a floor-mounted UR5e can be in, while the servo's 40 % is
a share of its own reachable cells (`cov.joint_reachable`). The same number meant two different things.

## Decision

1. **Denominator.** A joint-cube cell is reachable when a configuration of the mounted arm inside it is collision-free
   (`sysid.arm.Clearance`: MuJoCo's `mj_collision` on the description's collision geoms, 5 cm over a floor plane at the base,
   1 cm clear of itself: the check the UR schedules are planned and tested with) **and** its shoulder lift lies in the span
   connected to the arm's home posture.
   - Lift span: lift on a 0.01 rad grid; a lift value is clear when any of 2^9 Sobol configurations of the other five joints
     clears there; the span is the clear run around home's lift (−1.2 rad). Measured: **−3.37 to 0.23 rad** (the lane hand-set
     −3.6 to 0.5). Every clear lift value outside it is a 2π duplicate.
   - Per cell: a fixed scrambled Sobol probe (2^10, seed 0) scaled into the cell, the lift clipped to the span; reachable at the
     first clear point.
2. **Committed per mount.** type_cards is stdlib-only, so the masks are files, `type_cards/arm_reachable/ur5e_floor.json` and
   `ur5e_2f85_floor.json` (4,096 bits, count, sha256, every probe setting, tool versions), written by `tools/arm_reachable.py`.
   `sysid/tests/test_arm_reachable_mask.py` regenerates them bit for bit and checks every sample the UR plans command lands in a
   reachable cell. The arm card's measure defaults to `ur5e_floor`; the 2F-85 example and the gripper card use `ur5e_2f85_floor`.
3. **Gate stays 40 %** (`ladders.GATE_PCT`, the same on every card), now 40 % of the reachable cells.

## The numbers

| | cells | % of the 4,096 box | % of the 2,560 reachable |
|---|---:|---:|---:|
| reachable, both UR5e mounts (bare and with the 2F-85) | 2,560 | 62.5 % | 100 % |
| old gate (40 % of the box) | 1,639 | 40 % | 64 % |
| **new gate (40 % of reachable)** | **1,024** | 25 % | **40 %** |
| ur5e train plan (unchanged) | 1,723 | 42.07 % | 67.30 % |
| ur5e_2f85 train plan (unchanged) | 1,722 | 42.04 % | 67.27 % |

By lift bin the masks hold 768 / 1,024 / 768 / 0 cells: bin 1 (the arm above its mount) whole, one elbow bin out in each
sliver, bin 3 empty.

## Why 40 % and not a higher share to keep the old absolute count

Criteria, weighted: **(a) the percentage means the same on every card (0.4)**: a reader comparing the servo's and the arm's
coverage reads one rule; **(b) not looser than a sensible absolute bar (0.35)**; **(c) the gate reflects what a schedule can
promise before it runs (0.25)**: schedule.py's reason for 40 %.

- **40 % of reachable (1,024 cells).** (a) yes. (b) The sensible bar is the servo's own promise, a share of what the device can
  hold; in absolute cells it asks for more than the servo's (CAN 11: 647 of 1,616) and every cell is π rad wide on five joints.
  It is looser than the old 1,639, but that number was not chosen: it came from counting a duplicate posture and the floor. (c) yes.
- **64 % of reachable (1,639 cells, the old absolute count).** (b) keeps the old bar, but (a) fails: the arm alone would carry a
  special percentage whose only reason is an accident of the old denominator. (c) The UR plans meet it today only because the
  sweep was tuned to the old gate.
- **Keep counting the box.** Rejected: the lane's finding. The gate punishes not visiting cells no installed arm can be in.

The UR plans keep their 15 min sweep (target 42 % of the box, 1,721 cells) and pass at 67 %. Shortening the sweep to the new
gate is possible (about 1,076 cells) but changes the identification data, so it is a separate, measured step.

## Consequences

- `cov.arm_coverage(points, limits, mount=None)`: unchanged without a mount (the sub-assembly's 3-joint box still counts every
  cell); `cov.arm_6dof_coverage` / `cov.arm_gripper_coverage` are the cards' measures; `cov.arm_reachable_cells(mount)`.
- `Coverage.reachable_mask` (additive, exported): `ur5e_floor`, `ur5e_2f85_floor`, else None.
- sysid's UR results report coverage of 2,560 reachable cells and the sweep's curve as % of reachable cells.
- A new arm, mount (wall, ceiling, a pedestal) or tool needs its own mask: add a `tools/arm_reachable.MOUNTS` entry and run it.

## Alternatives not taken

- **Bin the shoulder lift over its physical span instead of ±2π.** Removes the duplicate bin but keeps floor and self-collision
  cells, and changes the cube every consumer bins against.
- **The coverage sweep's own Sobol pool as the ruler.** One shared 2^17 pool put few points in the sliver cells and found
  2,092 / 2,073 cells; the ruler would then depend on the planner's seed. A per-cell probe saturates at 2,560 (2^8 points for the
  bare arm, 2^10 with the 2F-85; 2^12 finds no more).
- **FK in type_cards.** It would break the stdlib-only site build; the mask carries the result instead.
