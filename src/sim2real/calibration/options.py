"""Per-type options: the models and routines a part's designer offers, today's first (PEP 0001 §5; Zach, 2026-11-11: "In the spirit of
black-box design, it's up to the designer of the part to provide the modelling options and the calibration options for its part - a couple
of options in case people do different things").

    from sim2real.calibration import options
    options("camera")   # TypeOptions(type='camera', models=('M2.measurement.exposure_latency', ...), routines=(...), setup=('camera.exposure_lock',))

Derived from the type registry (cards/domain.py: its model ladder and the routines that identify its parameters), so there is no second
registry. The one thing the registry cannot say is which configure / tune routines a type ALWAYS wants; that is the one explicit dict
below, SETUP (a configure step sets the device before anything is fitted; a tune runs after the fits it requires).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..cards import domain as dm
from ..cards import registry as reg
from . import recovery as rec

# WHY explicit (PEP 0001 §5): "always wants" is a designer's call, not something a ladder implies. The camera locks its exposure under the
# deployment's lights before anything is fitted (bam_camera_calibration); an ArUco marker is read best by a camera whose exposure, gain and
# fps were tuned for corner accuracy (PEP 0001 §9). camera.exposure_for_aruco and the aruco_marker type arrive with the aruco lane; until
# they are in the catalog, options() drops the id it cannot find there and says so in TypeOptions.missing. An integrated servo has its
# board's gains tuned by PID tuna on the fitted twin once its inertia and friction are found (gap C; Zach, 2026-11-17: "PID Tuna is the
# backend for one of the routines"): a tune, so it joins the plan, never the cover, and runs after the fits it requires.
SETUP: dict[str, tuple[str, ...]] = {
    "camera": ("camera.exposure_lock",),
    "aruco_marker": ("camera.exposure_for_aruco",),
    "integrated_servo": ("pid.pidtuna",),
}


@dataclass(frozen=True)
class TypeOptions:
    """`models`: today's model first (models[0] is one of the type's current models), then the rest of its ladder in ladder order.
    `routines`: the catalog routines that identify the type's parameters, preferred first (recovery at 1x, then time, equipment $, id).
    `setup`: the configure / tune routines the type always wants (SETUP). `missing`: SETUP ids the catalog does not hold yet."""
    type: str
    models: tuple[str, ...]
    routines: tuple[str, ...]
    setup: tuple[str, ...]
    missing: tuple[str, ...] = ()


def routine_rank(routine_id: str, level: str = "1x", settings: tuple[str, ...] = ("bench", "deployed")) -> tuple:
    """The metric between alternatives (PEP 0001 §5), as a sort key: recovery at `level` (passing first, then not graded, then failing;
    within each the worst error / tolerance), then wall time plus operator time, then equipment $, then where it runs (a routine that runs
    "both" first, then in the order of `settings`, the budget's), then id. Recovery is read ONLY through sim2real.calibration.recovery, the
    one reader shared with the docs site."""
    r = reg.routine(routine_id)
    entry = rec.recovery(routine_id, level)
    passed = None if entry is None else entry.get("pass")
    grade = 0 if passed is True else (2 if passed is False else 1)
    worst = None if entry is None else entry.get("worst_error_over_tolerance")
    time_s = float(r.wall_time.value or 0.0) + float(r.operator_time.value or 0.0)
    cost = float(reg.equipment_cost(r).value or 0.0)
    where = 0 if r.setting == "both" else 1 + (settings.index(r.setting) if r.setting in settings else len(settings))
    return (grade, float("inf") if worst is None else float(worst), time_s, cost, where, routine_id)


@lru_cache(maxsize=None)
def options(type_id: str) -> TypeOptions:
    """The model and routine options a type's designer offers (see the module docstring)."""
    t = dm.entity_type(type_id)
    current = [m.id for m in t.models if m.current]
    models = tuple(current[:1] + [m.id for m in t.models if m.id not in current[:1]])
    ids = {r.id for r in reg.ROUTINES}
    identifying = dict.fromkeys(rid for rids in dm.parameter_routines().get(t.id, {}).values() for rid in rids)
    routines = tuple(sorted(identifying, key=routine_rank))
    wanted = SETUP.get(t.id, ())
    return TypeOptions(t.id, models, routines, tuple(r for r in wanted if r in ids), tuple(r for r in wanted if r not in ids))
