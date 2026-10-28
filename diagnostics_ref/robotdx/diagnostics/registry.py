"""Name -> stock diagnostic. Custom ones register the same way: in code (``register``), from a TOML file
(``load_toml``, the shape of io-diagnostics' ``plugins.d``), or from a package's entry point (group ``robotdx.diagnostics``).

A registry entry is the function plus everything a host needs to show it without running it: its config type (so a
page can drill in and edit the thresholds, Zach 2026-10-28: "drill in and you can see and even configure these
values"), its family and role, and the data-ui view hint (``hint``).
"""

from __future__ import annotations

import dataclasses
import importlib
import tomllib
import typing
from dataclasses import dataclass, replace
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping

from .core import CONSUMERS, EMITS, FAMILIES, HINTS, ROLES, Limits, Result

ENTRY_POINT_GROUP = "robotdx.diagnostics"


@dataclass(frozen=True)
class Spec:
    name: str  # "stock.stop_error"; custom ones take their own prefix ("rack.cogging_phase")
    function: Callable[[Any, Any], Result]  # pure: (config, data) -> Result
    config_type: type
    title: str
    family: str
    role: str
    hint: str  # one of core.HINTS (data-ui PEP 0010 §10)
    emits: str
    unit: str
    consumers: tuple[str, ...] = CONSUMERS  # robotdx (one robot's live stream), sim2real (datasets of runs), or both
    view_extra: str = ""  # a view outside the six, with its one-line reason
    summary: str = ""

    def __post_init__(self):
        problems = []
        if self.family not in FAMILIES:
            problems.append(f"family {self.family!r} not in {FAMILIES}")
        if self.role not in ROLES:
            problems.append(f"role {self.role!r} not in {ROLES}")
        if self.hint not in HINTS:
            problems.append(f"hint {self.hint!r} not in {HINTS}")
        if self.emits not in EMITS:
            problems.append(f"emits {self.emits!r} not in {EMITS}")
        if any(c not in CONSUMERS for c in self.consumers):
            problems.append(f"consumers {self.consumers} not within {CONSUMERS}")
        if not dataclasses.is_dataclass(self.config_type) or not self.config_type.__dataclass_params__.frozen:
            problems.append(f"{self.config_type} must be a frozen dataclass")
        if problems:
            raise ValueError(f"{self.name}: " + "; ".join(problems))


REGISTRY: dict[str, Spec] = {}


def register(spec: Spec, *, registry: dict[str, Spec] | None = None) -> Spec:
    registry = REGISTRY if registry is None else registry
    if spec.name in registry and registry[spec.name] is not spec:
        raise ValueError(f"{spec.name} is already registered")
    registry[spec.name] = spec
    return spec


def get(name: str) -> Spec:
    return REGISTRY[name]


def names() -> list[str]:
    return sorted(REGISTRY)


def _payload_problem(spec: Spec, out: Result) -> str:
    payload = out.payload or {}
    if spec.emits == "series" and out.value is not None and not {"x", "y"} <= set(payload):
        return "a series result needs payload x and y"
    if spec.emits == "matrix" and out.value is not None and not {"rows", "cols", "cells"} <= set(payload):
        return "a matrix result needs payload rows, cols and cells"
    return ""


def evaluate(name: str, config: Any, data: Any, *, subject: str, stamp: float | None = None) -> Result:
    """Run one diagnostic and stamp what the registry knows onto its Result (name, view hint, family, role, subject)."""

    spec = REGISTRY[name]
    if not isinstance(config, spec.config_type):
        raise TypeError(f"{name} takes a {spec.config_type.__name__}, got {type(config).__name__}")
    out = spec.function(config, data)
    out = replace(out, diagnostic=name, subject=subject, family=spec.family, role=spec.role, hint=spec.hint,
                  emits=spec.emits, view_extra=spec.view_extra, stamp=stamp if stamp is not None else out.stamp)
    problem = _payload_problem(spec, out)
    if problem:
        raise ValueError(f"{name}: {problem}")
    return out


# ----- configs as data: what a page edits and a TOML file declares -----------------------------------------------
def config_from_dict(config_type: type, values: Mapping[str, Any]):
    """Build a frozen config from plain data (TOML, JSON, a form); nested ``Limits`` and tuples are rebuilt by type."""

    hints = typing.get_type_hints(config_type)
    kwargs = {}
    for spec in dataclasses.fields(config_type):
        if spec.name not in values:
            continue
        value, hint = values[spec.name], hints.get(spec.name)
        if hint is Limits or (isinstance(value, Mapping) and set(value) <= {"warn_low", "warn_high", "error_low", "error_high"}):
            value = Limits(**value)
        elif isinstance(value, list):
            value = tuple(value)
        kwargs[spec.name] = value
    unknown = set(values) - {spec.name for spec in dataclasses.fields(config_type)}
    if unknown:
        raise ValueError(f"{config_type.__name__} has no field(s) {sorted(unknown)}")
    return config_type(**kwargs)


def _resolve(dotted: str):
    module, _, attribute = dotted.partition(":")
    return getattr(importlib.import_module(module), attribute)


def load_toml(path: Path, *, registry: dict[str, Spec] | None = None) -> list[Spec]:
    """Register every ``[[diagnostic]]`` table: name, function = "pkg.mod:fn", config = "pkg.mod:Config", title,
    family, role, hint, emits, unit, optional consumers / view_extra / summary. A broken table raises with its name."""

    tables = tomllib.loads(Path(path).read_text())["diagnostic"]
    out = []
    for table in tables:
        fields = {k: v for k, v in table.items() if k not in ("function", "config")}
        if "consumers" in fields:
            fields["consumers"] = tuple(fields["consumers"])
        out.append(register(Spec(function=_resolve(table["function"]), config_type=_resolve(table["config"]), **fields), registry=registry))
    return out


def load_entry_points(group: str = ENTRY_POINT_GROUP, *, registry: dict[str, Spec] | None = None) -> list[Spec]:
    """Each entry point loads a ``Spec`` or a list of them (a package ships its custom diagnostics this way)."""

    out = []
    for point in metadata.entry_points(group=group):
        loaded = point.load()
        for spec in loaded if isinstance(loaded, (list, tuple)) else [loaded]:
            out.append(register(spec, registry=registry))
    return out
