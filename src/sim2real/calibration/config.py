"""CalibrationConfig: the one value that steers a whole calibrate() run (PEP 0001 §6, Zach 2026-11-11: ".calibrate(CalibrationConfig) to
propagate information to each routine and control the whole thing").

    from sim2real.calibration import Budget, CalibrationConfig
    config = (CalibrationConfig(known={"can14.backlash_rad": 0.003}, level="3x",
                                budget=Budget(settings=("deployed",), max_wall_time_s=3600.0))
              .with_routine("servo.breakaway_two_sided", cycles=5))
    fitted = twin.calibrate(config=config)

WHY a frozen dataclass with a JSON round trip (the pattern sim2real.rig.NoiseModel already uses): a config is a record of how a run was
steered, so it must compare by value, never change under a run, and travel with the run's record. Stdlib only.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

LEVELS = ("0x", "1x", "3x", "10x")  # sim2real.calibration.recovery.LEVELS: the noise levels a routine's recovery is graded at
SETTINGS = ("bench", "deployed")    # cards.schema.SETTINGS; a routine's "both" fits either


@dataclass(frozen=True)
class Budget:
    """What a run may spend. `settings`: where routines may run (a routine that runs "both" fits either). `max_wall_time_s`: the plan's
    wall time, counted once: each routine's own time (its set-up included; operator time is a share of it) plus each run counted once
    however many routines read it, as the runner plays it (the plan's totals["wall_time_s"]). `max_equipment_usd`: the distinct equipment
    the plan needs, each item counted once. None = no limit."""
    settings: tuple[str, ...] = SETTINGS
    max_wall_time_s: float | None = None
    max_equipment_usd: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", tuple(self.settings))
        unknown = [s for s in self.settings if s not in SETTINGS]
        if unknown or not self.settings:
            raise ValueError(f"budget settings are a non-empty subset of {SETTINGS}, not {self.settings}")

    def allows(self, setting: str) -> bool:
        return setting == "both" or setting in self.settings

    def to_dict(self) -> dict:
        return {"settings": list(self.settings), "max_wall_time_s": self.max_wall_time_s, "max_equipment_usd": self.max_equipment_usd}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Budget:
        return cls(tuple(data.get("settings", SETTINGS)), data.get("max_wall_time_s"), data.get("max_equipment_usd"))


@dataclass(frozen=True)
class RoutineOptions:
    """Options for one routine, by name. They reach a COPY of the routine (sim2real.calibration.plan applies them): its `options` dict
    when it has one, else its attribute or dataclass field of that name. A name the routine does not have raises KeyError naming it."""
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", dict(self.options))


@dataclass(frozen=True)
class CalibrationConfig:
    """Steers calibrate(), plan() and collect() (PEP 0001 §6).

    - `models`: {instance: model id}, a rung picked per part (the type's current model otherwise).
    - `known`: {key: value}, fixed: the routines that would only find these are dropped ("known") and every routine sees the value.
    - `exclude`, `include`: routine ids kept out / brought in (a configure or tune routine included joins the plan's setup).
    - `order`: an explicit order of routine ids; refused if it runs a routine before one it `requires` or `refines` after.
    - `level`: the noise level ("0x", "1x", "3x", "10x") whose recovery ranks alternatives.
    - `noise`: a number (every term at that level) or a NoiseModel's dict; refused if calibrate(noise=) is also given.
    - `budget`: a Budget; `strict`: over budget -> refuse instead of dropping.
    - `seed`: the noise model's seed for this run.
    - `routines`: per-routine options ({id: RoutineOptions}), set with .with_routine(id, **options).
    - `custom`: injected routine objects: each replaces the rig's implementation of a registered id (cards/calibration.py ROUTINES);
      an unregistered id is refused.
    """
    models: Mapping[str, str] = field(default_factory=dict)
    known: Mapping[str, float] = field(default_factory=dict)
    exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    order: tuple[str, ...] | None = None
    level: str = "1x"
    noise: Any = None
    budget: Budget = field(default_factory=Budget)
    strict: bool = False
    seed: int | None = None
    routines: Mapping[str, RoutineOptions] = field(default_factory=dict)
    custom: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "models", dict(self.models))
        set_(self, "known", {k: float(v) for k, v in self.known.items()})
        set_(self, "exclude", tuple(self.exclude))
        set_(self, "include", tuple(self.include))
        set_(self, "order", None if self.order is None else tuple(self.order))
        set_(self, "custom", tuple(self.custom))
        set_(self, "routines", {rid: (o if isinstance(o, RoutineOptions) else RoutineOptions(o)) for rid, o in self.routines.items()})
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, not {self.level!r}")
        if not isinstance(self.budget, Budget):
            raise TypeError(f"budget is a sim2real.calibration.Budget, not {type(self.budget).__name__}")

    def with_routine(self, routine_id: str, **options: Any) -> CalibrationConfig:
        """A NEW config whose options for `routine_id` are these (merged over any it had); this one is unchanged."""
        old = self.routines.get(routine_id, RoutineOptions()).options
        return dataclasses.replace(self, routines={**self.routines, routine_id: RoutineOptions({**old, **options})})

    def to_dict(self) -> dict:
        """JSON-able. `custom` is written as its routine ids (objects do not travel): from_dict refuses them unless passed again."""
        return {"models": dict(self.models), "known": dict(self.known), "exclude": list(self.exclude), "include": list(self.include),
                "order": None if self.order is None else list(self.order), "level": self.level, "noise": self.noise,
                "budget": self.budget.to_dict(), "strict": self.strict, "seed": self.seed,
                "routines": {rid: dict(o.options) for rid, o in self.routines.items()},
                "custom": [getattr(r, "id", repr(r)) for r in self.custom]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, custom: tuple[Any, ...] = ()) -> CalibrationConfig:
        named = list(data.get("custom") or [])
        given = [getattr(r, "id", None) for r in custom]
        if named != given:
            raise ValueError(f"the config names custom routines {named}; pass the same objects as from_dict(..., custom=(...)) (got {given})")
        return cls(models=dict(data.get("models") or {}), known=dict(data.get("known") or {}), exclude=tuple(data.get("exclude") or ()),
                   include=tuple(data.get("include") or ()), order=None if data.get("order") is None else tuple(data["order"]),
                   level=data.get("level", "1x"), noise=data.get("noise"), budget=Budget.from_dict(data.get("budget") or {}),
                   strict=bool(data.get("strict", False)), seed=data.get("seed"),
                   routines={rid: RoutineOptions(o) for rid, o in (data.get("routines") or {}).items()}, custom=tuple(custom))
