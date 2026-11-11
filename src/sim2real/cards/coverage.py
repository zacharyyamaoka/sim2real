"""Coverage of a planned set, per type: how much of a type's input space a plan visits, before anything runs.

One binned rule for every type: a type declares its input axes (continuous axes with edges, categorical axes with levels), a plan is
a list of points on those axes, and coverage is the share of the reachable cells that at least one point visits. The types differ only
in their axes, their edges and which cells are reachable.

The rule itself (CoverageResult, bin_index, occupancy, binned, marginal, signed, random_plan) is robot_msgs.coverage since 2026-11-10;
this module keeps every type's axes, edges and reachable rule and re-exports the rule's names, so `from type_cards.coverage import binned`
keeps working. WHY split there (Zach, 2026-11-10, "Sim2Real as a Pure Library on robot_msgs", proposal 2): robot_msgs changes slowest,
so it holds only the math with one definition; a type's axes, edges, reachable cells and gates are policy that churns, so they stay
here, and nothing in robot_msgs may import them. Stdlib plus robot_msgs (which brings numpy); still no MuJoCo.

WHY generalised from bam_rack_twin.schedule and not re-derived (dispatcher brief, 2026-11-04: "Generalise schedule.py's for the
1-DOF case rather than duplicating it"): the servo's (q, qd, qdd) edges, its reachable rule and numpy.histogramdd's bin
convention are schedule.py's (edges_of, reachable_cells, occupancy at bam_ws main b5600075), written once for any
number of axes; tests/test_registry.py holds this module to schedule.py's own CAN 11 number, so a drift in either shows.
"""

from __future__ import annotations

import functools
import itertools
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from robot_msgs.coverage import (  # noqa: F401  (re-exported: this module's public names before 2026-11-10)
    CoverageResult,
    bin_index,
    binned,
    centres,
    marginal,
    n_cells,
    occupancy,
    random_plan,  # WHY (Zach, Nov 5: "you can randomly sample within the full space, but its a easy way to quickly check if your
    signed,       # covering it ... its like a histogram"): the cells are only the ruler; a plan need not sit on them.
)


# --- the 1-DOF actuator (servo, and a gearbox or motor on a 1-DOF rig) --------------------------------------------------------

# schedule.py's constants (bam_ws main b5600075): QD_EDGE_FRACTIONS, QDD_EDGE_FRACTIONS, Q_BINS, TAU_CELL_NM, FF_BAND_RAD_S
QD_EDGE_FRACTIONS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
QDD_EDGE_FRACTIONS = (0.00625, 0.025, 0.0625, 0.1875, 0.5, 1.0)
Q_BINS = 12
TAU_CELL_NM = 0.25
FF_BAND_RAD_S = 0.05  # bam_rack_twin.hardware.experiments.FF_BAND_RAD_S: the tanh band of the model's Coulomb term


def joint_edges(description: Mapping[str, Any]) -> list[list[float]]:
    """(q, qd, qdd) edges of a 1-DOF joint description (schedule.py's JointDescription JSON): q in 12 cells over the range,
    qd and qdd signed and log-spaced with a dead cell around 0."""
    low, high = description["range_rad"]
    q = [low + (high - low) * i / Q_BINS for i in range(Q_BINS + 1)]
    return [q, signed(QD_EDGE_FRACTIONS, description["speed_rad_s"]), signed(QDD_EDGE_FRACTIONS, description["accel_rad_s2"])]


def joint_reachable(description: Mapping[str, Any]) -> Callable[[tuple], bool]:
    """A cell is reachable when its centre's demand J qdd + G sin(q_abs - bottom) + Fc tanh(qd / band) is inside the torque limit
    and the joint can brake from qd before the end of the range it moves toward (schedule.reachable_cells)."""
    d = description
    low, high = d["range_rad"]

    def ok(c: tuple) -> bool:
        q, qd, qdd = c
        tau = (d.get("inertia_kg_m2", 0.0) * qdd + d.get("gravity_nm", 0.0) * math.sin(d["origin_rad"] + q - d.get("gravity_bottom_rad", 0.0))
               + d.get("coulomb_nm", 0.0) * math.tanh(qd / FF_BAND_RAD_S))
        room = high - q if qd > 0 else q - low
        return abs(tau) <= d["torque_limit_nm"] and qd * qd / (2 * d["accel_rad_s2"]) <= room + 1e-12

    return ok


@functools.lru_cache(maxsize=64)
def _reachable_cells(key: str) -> frozenset:
    d = json.loads(key)
    edges, ok = joint_edges(d), joint_reachable(d)
    grid = [centres(a) for a in edges]
    return frozenset(cell for cell in itertools.product(*(range(n_cells(a)) for a in edges)) if ok(tuple(grid[k][i] for k, i in enumerate(cell))))


def reachable_cells(description: Mapping[str, Any]) -> frozenset:
    """The joint's reachable (q, qd, qdd) cells: joint_reachable at each cell's centre over joint_edges, computed once per description.
    WHY memoized, on the whole description (its JSON, keys sorted), bounded: the site's run page computes a selection of one for each of
    2239 runs, and each call rebuilt the same 2016-cell set (19 s of a 35 s build); any field of the description is part of the key, so
    a changed joint is a new set (tests/test_coverage_cache.py)."""
    return _reachable_cells(json.dumps(description, sort_keys=True, default=str))


reachable_cells.cache_info = _reachable_cells.cache_info
reachable_cells.cache_clear = _reachable_cells.cache_clear


def tau_edges(description: Mapping[str, Any]) -> list[float]:
    cells = int(math.ceil(description["torque_limit_nm"] / TAU_CELL_NM))
    return [k * TAU_CELL_NM for k in range(-cells, cells + 1)]


SPLITS = {"train": lambda r: r["split"] == "train", "held_out": lambda r: r["split"] == "held_out",
          "h1": lambda r: r.get("held_out_set") == "H1", "h2": lambda r: r.get("held_out_set") == "H2", "all": lambda r: True}


def plan_points(schedule: Mapping[str, Any], split: str = "train", columns=("q", "qd", "qdd")) -> list[tuple]:
    """Every planned run's target once per run (a repeat counts again), runs whose trajectory counts for coverage
    (schedule.py's _split_samples)."""
    by_id = {t["id"]: t for t in schedule["trajectories"]}
    keep = SPLITS[split]
    out = []
    for run in schedule["runs"]:
        t = by_id[run["trajectory"]]
        if keep(run) and t["counts_for_coverage"]:
            out.extend(zip(*(t["target"][c] for c in columns)))
    return out


def servo_coverage(schedule: Mapping[str, Any], split: str = "train") -> CoverageResult:
    """A 1-DOF servo's coverage of a bam_rack_twin.schedule document: the (q, qd, qdd) cube over its reachable cells (the
    headline, schedule.py's number), with load torque (the planned demand tau_pred, over the torque limit) as its own marginal,
    and temperature named as unplanned (no schedule family varies it yet)."""
    d = schedule["description"]
    points = plan_points(schedule, split, ("q", "qd", "qdd", "tau_pred"))
    limit = d["torque_limit_nm"]
    load = marginal([p[3] for p in points], tau_edges(d), keep=lambda c: abs(c) <= limit) if points else 0.0
    return binned([p[:3] for p in points], joint_edges(d), reach=reachable_cells(d),
                  axes={"load torque": load, "temperature": None}, unplanned=("temperature",),
                  note=f"{schedule.get('description', {}).get('name', '')} schedule {schedule.get('digest', '')}, split {split}")


def actuator_coverage(points: Sequence[Mapping[str, float]], description: Mapping[str, Any]) -> CoverageResult:
    """Any 1-DOF actuator (servo, a gearbox or motor on a 1-DOF rig): points as {q, qd, qdd, load torque, temperature}."""
    cube = [(p["q"], p["qd"], p["qdd"]) for p in points]
    load = [p["load torque"] for p in points if p.get("load torque") is not None]
    temps = [p["temperature"] for p in points if p.get("temperature") is not None]
    limit = description["torque_limit_nm"]
    t_edges = [description.get("temp_min_c", 20.0) + 10.0 * i for i in range(int((description.get("temp_max_c", 80.0) - description.get("temp_min_c", 20.0)) / 10) + 1)]
    return binned(cube, joint_edges(description), reach=reachable_cells(description),
                  axes={"load torque": marginal(load, tau_edges(description), keep=lambda c: abs(c) <= limit) if load else None,
                        "temperature": marginal(temps, t_edges) if temps else None},
                  unplanned=tuple(k for k, v in (("load torque", load), ("temperature", temps)) if not v))


# --- the driver: its own electrical operating map --------------------------------------------------------------------------

def driver_coverage(points: Sequence[Mapping[str, float]], description: Mapping[str, Any] | None = None) -> CoverageResult:
    """Points {current command (A), speed (rad/s at the rotor), bus voltage (V), board temperature (degC)}: the (i_q, speed)
    operating map in signed cells to the limits, every bus voltage and temperature band as its own marginal."""
    d = {"current_limit_a": 20.0, "speed_limit_rad_s": 300.0, "v_bus": (20.0, 26.0, 32.0, 38.0, 44.0), "temp_c": (20.0, 40.0, 60.0, 80.0), **(description or {})}
    i_edges = signed((0.05, 0.15, 0.3, 0.6, 1.0), d["current_limit_a"])
    w_edges = signed((0.02, 0.1, 0.3, 0.6, 1.0), d["speed_limit_rad_s"])
    cube = [(p["current command"], p["speed"]) for p in points]
    v = [p["bus voltage"] for p in points if p.get("bus voltage") is not None]
    t = [p["board temperature"] for p in points if p.get("board temperature") is not None]
    return binned(cube, [i_edges, w_edges], axes={"bus voltage": marginal(v, list(d["v_bus"])) if v else None,
                                                  "board temperature": marginal(t, list(d["temp_c"])) if t else None},
                  unplanned=tuple(k for k, vals in (("bus voltage", v), ("board temperature", t)) if not vals))


# --- arms: joint space plus tool pose ---------------------------------------------------------------------------------------

UR5E_LIMITS = ((-6.28, 6.28), (-6.28, 6.28), (-3.14, 3.14), (-6.28, 6.28), (-6.28, 6.28), (-6.28, 6.28))
JOINT_BINS = 4  # per joint: 4^6 = 4096 joint cells; a finer grid needs FK-weighted sampling to be meaningful
TOOL_BOX_M = ((-0.85, 0.85), (-0.85, 0.85), (-0.2, 1.0))  # UR5e's reach (850 mm) as a box around the base
TOOL_VOXEL_M = 0.1


ARM_MOUNTS = ("ur5e_floor", "ur5e_2f85_floor")  # type_cards/arm_reachable/<mount>.json, written by tools/arm_reachable.py
DEFAULT_ARM_MOUNT = "ur5e_floor"
ARM_REACHABLE_DIR = Path(__file__).resolve().parent / "arm_reachable"
_ARM_MASKS: dict[str, frozenset] = {}


def arm_reachable_cells(mount: str) -> frozenset:
    """The joint-cube cells (index tuples) a mounted arm can be in: a collision-free configuration of the arm lies inside the cell,
    its shoulder lift inside the span connected to home. A committed mask (4,096 bits in itertools.product order) because the rule
    needs MuJoCo's collision check and this module never imports MuJoCo; tools/arm_reachable.py writes it and
    sysid/tests/test_arm_reachable_mask.py holds the file to a fresh run."""
    if mount not in _ARM_MASKS:
        if mount not in ARM_MOUNTS:
            raise KeyError(f"no reachable mask for mount {mount!r}; mounts: {ARM_MOUNTS}")
        doc = json.loads((ARM_REACHABLE_DIR / f"{mount}.json").read_text())
        order = itertools.product(range(doc["joint_bins"]), repeat=len(doc["limits"]))
        _ARM_MASKS[mount] = frozenset(cell for cell, bit in zip(order, doc["mask"]) if bit == "1")
    return _ARM_MASKS[mount]


def arm_coverage(points: Sequence[Mapping[str, Any]], limits: Sequence[tuple[float, float]] = UR5E_LIMITS, mount: str | None = None) -> CoverageResult:
    """Points {joint space: (q1..qn) rad, tool pose: (x, y, z) m or absent}: the joint cube (JOINT_BINS per joint inside the
    limits) as the headline, the tool position's voxels (TOOL_VOXEL_M over TOOL_BOX_M) as a marginal. With a `mount`
    (ARM_MOUNTS) the cube counts over that mount's reachable cells (arm_reachable_cells), as the servo counts over its
    joint_reachable cells; without one every cell of the box counts (the sub-assembly's, and this function before 2026-11-05).
    WHY no reachable-voxel mask yet: it needs the arm's FK (pin_utils), so the voxel share is over the box and says so."""
    edges = [[lo + (hi - lo) * i / JOINT_BINS for i in range(JOINT_BINS + 1)] for lo, hi in limits]
    joints = [tuple(p["joint space"]) for p in points]
    tools = [tuple(p["tool pose"])[:3] for p in points if p.get("tool pose") is not None]
    tool_pct = None
    if tools:
        vox = [[lo + TOOL_VOXEL_M * i for i in range(int(round((hi - lo) / TOOL_VOXEL_M)) + 1)] for lo, hi in TOOL_BOX_M]
        tool_pct = binned(tools, vox).pct
    reachable = None
    if mount is not None:
        if tuple(tuple(x) for x in limits) != UR5E_LIMITS:
            raise ValueError(f"mount {mount!r}'s mask is over UR5E_LIMITS, not {limits}")
        reach = arm_reachable_cells(mount)

        def reachable(centre: tuple) -> bool:
            return tuple(bin_index(c, e) for c, e in zip(centre, edges)) in reach

    note = "tool voxels are over the reach box, not the FK-reachable set"
    return binned(joints, edges, reachable, axes={"tool pose": tool_pct, "payload": None}, unplanned=("payload",),
                  note=note if mount is None else f"joint cells over {mount}'s reachable mask; {note}")


def arm_6dof_coverage(points: Sequence[Mapping[str, Any]], mount: str = DEFAULT_ARM_MOUNT) -> CoverageResult:
    """The arm_6dof card's measure: arm_coverage over a mount's reachable cells (the bare UR5e on a floor unless told)."""
    return arm_coverage(points, UR5E_LIMITS, mount=mount)


def arm_gripper_coverage(points: Sequence[Mapping[str, Any]], mount: str = "ur5e_2f85_floor") -> CoverageResult:
    """The arm_6dof_gripper card's measure: the arm's, over the arm-with-gripper's reachable cells (the 2F-85 on a UR5e)."""
    return arm_coverage(points, UR5E_LIMITS, mount=mount)


# --- cameras: scene conditions ----------------------------------------------------------------------------------------------

CAMERA_AXES = {
    "distance": [0.1, 0.3, 0.6, 1.2, 2.5],                 # m, log-ish: near to the D435's useful range
    "incidence angle": [0.0, 15.0, 30.0, 45.0, 75.0],      # deg from the optical axis's normal
    "illumination": [10.0, 150.0, 600.0, 20000.0],          # lux: dim, indoor, bright indoor to daylight
    "material": ("levels", "matte white", "black plastic", "metal", "clear PET", "cardboard", "film"),
    "exposure": [0.1, 3.0, 15.0, 40.0],                    # ms: short, mid, long (past one 30 fps frame)
}
HSI_AXES = {**CAMERA_AXES,
            "wavelength band": ("levels", "VIS 400-700 nm", "red edge 700-1000 nm", "SWIR 1000-1700 nm"),
            "material class": ("levels", "PET", "HDPE", "PP", "PS", "PVC", "paper", "organic", "metal", "glass")}


def condition_coverage(axes: Mapping[str, Sequence[Any]]) -> Callable[[Sequence[Mapping[str, Any]]], CoverageResult]:
    """A sensor's coverage over named scene axes; every cell is reachable (a rig can set any condition)."""
    names = list(axes)

    def measure(points: Sequence[Mapping[str, Any]]) -> CoverageResult:
        given = [n for n in names if any(n in p for p in points)]
        rows = [tuple(p.get(n) for n in names) for p in points if all(p.get(n) is not None for n in names)]
        result = binned(rows, [axes[n] for n in names])
        return CoverageResult(**{**result.__dict__, "unplanned": tuple(n for n in names if n not in given)})

    return measure


# --- the conveyor: belt speed by load ------------------------------------------------------------------------------------------

def conveyor_coverage(points: Sequence[Mapping[str, Any]], description: Mapping[str, Any] | None = None) -> CoverageResult:
    """Points {belt speed (m/s), load mass (kg), position (m along the belt), acceleration (m/s²)}: the (speed, load) cells, signed
    speed to the limit; position and acceleration as their own marginals. Defaults are pidtuna's conveyor plant (0.5 m/s, a 2 m belt)."""
    d = {"speed_limit_m_s": 0.5, "accel_limit_m_s2": 1.0, "belt_length_m": 2.0, "load_kg": (0.0, 5.0, 10.0, 15.0, 20.0, 30.0), **(description or {})}
    speed_edges = signed((0.05, 0.15, 0.3, 0.6, 1.0), d["speed_limit_m_s"])
    cells = int(round(d["belt_length_m"] / 0.25))
    pos_edges = [0.25 * i for i in range(cells + 1)]
    acc_edges = signed((0.1, 0.5, 1.0), d["accel_limit_m_s2"])
    cube = [(p["belt speed"], p["load mass"]) for p in points]
    pos = [p["position"] for p in points if p.get("position") is not None]
    acc = [p["acceleration"] for p in points if p.get("acceleration") is not None]
    return binned(cube, [speed_edges, list(d["load_kg"])], axes={"position": marginal(pos, pos_edges) if pos else None,
                                                                "acceleration": marginal(acc, acc_edges) if acc else None},
                  unplanned=tuple(k for k, v in (("position", pos), ("acceleration", acc)) if not v))
