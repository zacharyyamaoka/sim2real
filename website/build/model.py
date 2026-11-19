"""Everything the sim2real docs site knows, read from sim2real's own registries. Nothing here is written per type or per routine.

- types, models, parameters: ``sim2real.cards.domain`` (TYPE_ORDER, entity_type, models, current_models, routines_identifying,
  parameter_routines, routine_parameters)
- calibration routines and equipment: ``sim2real.cards.calibration`` (ROUTINES, EQUIPMENT) and ``schema.equipment_cost``
- the routine kinds as pages print them: ``sim2real.cards.schema.KIND_WORDS``
- recovery at 0x / 1x / 3x / 10x: ``sim2real.calibration.recovery``, the ONE reader shared with the planner (never sysid/results/*.json
  directly)
- the API reference: introspection of ``sim2real.twin.RobotTwin`` and every public name in ``sim2real.calibration.__all__`` (robotmsgs.com's
  split_doc / first_line / render_signature)
- examples: ``website/examples/<name>.py`` and the real output ``record_examples.py`` wrote beside it

WHY a new model.py and not robotmsgs': robot_msgs' model.py imports robot_msgs and walks message dataclasses; only its introspection
helpers carry over (PEP 0001 section 10).
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import inspect
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sim2real.calibration import recovery as rec
from sim2real.cards import calibration as cat
from sim2real.cards import domain as dm
from sim2real.cards import schema

WEBSITE = Path(__file__).resolve().parent.parent
REPO = WEBSITE.parent
EXAMPLES_DIR = WEBSITE / "examples"
LEVELS = rec.LEVELS
EXAMPLES = ("pendulum_can11", "ur_wrist_test_rig")
EXAMPLE_TITLES = {
    "pendulum_can11": "CAN 11 pendulum",
    "ur_wrist_test_rig": "UR wrist test rig",
}
LEVEL_WORDS = {"0x": "with no sensor noise", "1x": "at the oracle's own sensor noise", "3x": "at three times it", "10x": "at ten times it"}
DOCS = (  # (slug, markdown file, nav label): a file that does not exist yet is skipped, never an empty page
    ("guide", REPO / "docs" / "API.md", "Guide"),
    ("calibrate", REPO / "docs" / "CALIBRATE.md", "What calibrate() returns"),
)


# ---------------------------------------------------------------------------------- docstrings (robotmsgs.com's model.py)


def split_doc(obj: Any) -> tuple[str, str]:
    """(first paragraph on one line, the rest)."""
    doc = inspect.getdoc(obj) or ""
    first, _, rest = doc.partition("\n\n")
    return " ".join(first.split()), rest.strip()


def first_line(obj: Any) -> str:
    doc = inspect.getdoc(obj) or ""
    return doc.splitlines()[0].strip() if doc else ""


class Raw:
    """An annotation kept as written: signature printing would repr (and quote) a string."""

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text


def as_written(sig: inspect.Signature) -> inspect.Signature:
    def raw(annotation: Any) -> Any:
        return Raw(annotation) if isinstance(annotation, str) else annotation

    return sig.replace(
        parameters=[p.replace(annotation=raw(p.annotation)) for p in sig.parameters.values()],
        return_annotation=raw(sig.return_annotation),
    )


def render_signature(name: str, sig: inspect.Signature) -> str:
    sig = as_written(sig)
    text = f"{name}{sig}"
    if len(text) <= 72:
        return text
    params = [str(p) for p in sig.parameters.values()]
    ret = f" -> {sig.return_annotation!r}" if sig.return_annotation is not sig.empty else ""
    return f"{name}(\n" + "".join(f"    {p},\n" for p in params) + f"){ret}"


def drop_first(sig: inspect.Signature) -> inspect.Signature:
    return sig.replace(parameters=list(sig.parameters.values())[1:])


# ------------------------------------------------------------------------------------------------- formatting


def seconds_text(value: float | None) -> str:
    """A routine's time as people read it (site/models_pages.py's _seconds)."""
    if value is None:
        return "unknown"
    s = float(value)
    if s == 0:
        return "0 s"
    if s < 1:
        return f"{s * 1000:.3g} ms"
    if s < 90:
        return f"{s:.3g} s"
    if s < 5400:
        return f"{s / 60:.3g} min"
    return f"{s / 3600:.3g} h"


def usd_text(value: float | None) -> str:
    return "unknown" if value is None else f"${value:,.0f}"


# ---------------------------------------------------------------------------------------------------- routines


@dataclass(frozen=True)
class Level:
    level: str
    ratio: float | None          # worst |error| / tolerance, None = not graded there
    passed: bool | None
    entry: dict | None           # the reader's whole entry (carried, shown on the routine page)


@dataclass(frozen=True)
class RoutineInfo:
    id: str
    title: str
    kind: str                    # schema.ROUTINE_KINDS
    kind_word: str               # KIND_WORDS[kind]: what pages print ("fit" for identify)
    setting: str
    status: str
    package: str
    wall_time_s: float | None
    wall_time_source: str
    operator_time_s: float | None
    operator_time_source: str
    equipment: tuple[tuple[str, str, float | None, str], ...]   # (id, title, cost, source)
    cost_usd: float | None
    cost_source: str
    cost_estimated: bool
    identifies: tuple[tuple[str, str, str], ...]                 # (type, model, parameter)
    configures: tuple[tuple[str, str], ...]                      # (card, setting)
    requires: tuple[str, ...]
    uses: tuple[str, ...]
    refines: tuple[str, ...]
    levels: tuple[Level, ...]
    recovery_source: str | None
    excitation: str
    coverage: str
    repeats: int
    how: str
    code: tuple[str, ...]
    oracle: tuple[str, ...]
    oracle_note: str
    alternatives: tuple[str, ...]
    references: tuple[tuple[str, str], ...]                      # (title, url)
    note: str

    @property
    def path(self) -> str:
        return f"/routines/{self.id}/"


def _ref_id(r: Any) -> str:
    """A routine id from whatever cards.domain hands back (an id, or a CalibrationRoutine)."""
    return r if isinstance(r, str) else r.id


def routines() -> list[RoutineInfo]:
    out = []
    for r in cat.ROUTINES:
        cost = schema.equipment_cost(r, cat.EQUIPMENT)
        levels = []
        for level in LEVELS:
            entry = rec.recovery(r.id, level)
            ratio = None if entry is None else entry.get("worst_error_over_tolerance")
            levels.append(Level(level, None if ratio is None else float(ratio), None if entry is None else entry.get("pass"), entry))
        out.append(RoutineInfo(
            id=r.id, title=r.title, kind=r.kind, kind_word=schema.KIND_WORDS[r.kind], setting=r.setting, status=r.status,
            package=r.package,
            wall_time_s=r.wall_time.value, wall_time_source=r.wall_time.source,
            operator_time_s=r.operator_time.value, operator_time_source=r.operator_time.source,
            equipment=tuple((e, cat.EQUIPMENT[e].title, cat.EQUIPMENT[e].cost.value, cat.EQUIPMENT[e].cost.source) for e in r.equipment),
            cost_usd=cost.value, cost_source=cost.source, cost_estimated=schema.ESTIMATE in (cost.source or ""),
            identifies=tuple(dm.routine_parameters(r.id)),
            configures=tuple((c.card, s) for c in r.configures for s in c.settings),
            requires=tuple(r.requires), uses=tuple(r.uses), refines=tuple(r.refines),
            levels=tuple(levels), recovery_source=rec.source(r.id),
            excitation=r.excitation, coverage=r.coverage, repeats=r.repeats, how=r.how,
            code=tuple(f"{c.repo}/{c.path}" + (f" ({c.note})" if c.note else "") for c in r.code),
            oracle=tuple(r.oracle), oracle_note=r.oracle_note, alternatives=tuple(r.alternatives),
            references=tuple((ref.title, ref.url) for ref in r.references), note=r.note,
        ))  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------- types and models


@dataclass(frozen=True)
class ModelInfo:
    id: str
    type: str
    k: int
    family: str
    name: str
    title: str
    kind: str
    parameters: tuple[str, ...]
    adds: tuple[str, ...]
    identified_by: tuple[str, ...]          # routines identifying what it adds
    current: bool
    equation: str
    base: str
    wear: bool
    implemented: str
    note: str
    references: tuple[tuple[str, str], ...]

    @property
    def path(self) -> str:
        return f"/models/{self.type}/{self.id}/"

    @property
    def rung(self) -> str:
        return f"M{self.k}"


@dataclass(frozen=True)
class ParameterInfo:
    type: str
    name: str
    unit: str
    family: str
    introduced_in: str
    models: tuple[str, ...]
    nominal: Any
    source: str
    identified_by_words: str
    observable: str
    role: str
    note: str
    routines: tuple[str, ...]               # routine ids that identify it (cards.domain.routines_identifying order)

    @property
    def path(self) -> str:
        return f"/parameters/{self.type}/{self.name}/"


@dataclass(frozen=True)
class TypeInfo:
    id: str
    title: str
    zach: str
    group: str
    covers: str
    families: tuple[str, ...]
    models: tuple[ModelInfo, ...]
    parameters: tuple[ParameterInfo, ...]
    routines: tuple[str, ...]               # every routine identifying its parameters or configuring its cards (catalog order)
    legacy_cards: tuple[str, ...]
    members: tuple[tuple[str, int, str], ...]
    note: str

    @property
    def path(self) -> str:
        return f"/types/{self.id}/"


def _identifying(tid: str, name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_ref_id(r) for r in dm.routines_identifying(tid, name)))


def types() -> list[TypeInfo]:
    out = []
    for tid in dm.TYPE_ORDER:
        t = dm.entity_type(tid)
        params = tuple(ParameterInfo(
            type=tid, name=p.name, unit=p.unit or "", family=p.family, introduced_in=p.introduced_in, models=tuple(p.models),
            nominal=p.nominal, source=p.source, identified_by_words=p.identified_by, observable=p.observable, role=p.role, note=p.note,
            routines=_identifying(tid, p.name),
        ) for p in t.parameters)  # fmt: skip
        by_name = {p.name: p for p in params}
        models = tuple(ModelInfo(
            id=m.id, type=tid, k=m.k, family=m.family, name=m.name, title=m.title, kind=m.kind, parameters=tuple(m.parameters),
            adds=tuple(m.adds), identified_by=tuple(dict.fromkeys(rid for n in m.adds for rid in (by_name[n].routines if n in by_name else _identifying(tid, n)))),
            current=bool(m.current), equation=m.equation, base=m.base, wear=m.wear, implemented=m.implemented, note=m.note,
            references=tuple((ref.title, ref.url) for ref in m.references),
        ) for m in t.models)  # fmt: skip
        ids = {rid for p in params for rid in p.routines}
        ids |= {r.id for r in cat.ROUTINES for c in r.configures if c.card in t.legacy_cards}
        ordered = tuple(r.id for r in cat.ROUTINES if r.id in ids)
        out.append(TypeInfo(
            id=tid, title=t.title, zach=t.zach, group=t.group, covers=t.covers, families=tuple(t.families), models=models, parameters=params,
            routines=ordered, legacy_cards=tuple(t.legacy_cards), members=tuple((m.type, m.count, m.role) for m in t.members), note=t.note,
        ))  # fmt: skip
    return out


# ---------------------------------------------------------------------------------------------------- examples


@dataclass(frozen=True)
class ExampleInfo:
    name: str
    title: str
    summary: str
    source: str
    recorded: dict | None
    stale: bool

    @property
    def path(self) -> str:
        return f"/examples/{self.name}/"


def examples() -> list[ExampleInfo]:
    out = []
    for name in EXAMPLES:
        source_path = EXAMPLES_DIR / f"{name}.py"
        source = source_path.read_text(encoding="utf-8")
        out_path = EXAMPLES_DIR / f"{name}.out.json"
        recorded = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else None
        stale = recorded is not None and recorded.get("source_sha256") != hashlib.sha256(source.encode()).hexdigest()
        doc = re.match(r'\s*"""(.*?)"""', source, re.S)
        summary = " ".join(doc.group(1).split()) if doc else ""
        out.append(ExampleInfo(name, EXAMPLE_TITLES.get(name, name), summary, source, recorded, stale))
    return out


# --------------------------------------------------------------------------------------------------------- API


@dataclass(frozen=True)
class MemberInfo:
    name: str
    signature: str
    summary: str
    rest: str
    group: str                    # constructor | property | method | function | class | module | value


@dataclass(frozen=True)
class ApiEntry:
    anchor: str
    name: str
    qualname: str
    kind: str                     # class | function | module | value | alias
    signature: str
    summary: str
    rest: str
    members: tuple[tuple[str, MemberInfo], ...] = field(default=())   # (anchor, member)
    fields: tuple[tuple[str, str, str], ...] = field(default=())     # a dataclass's (name, annotation, default)


def _member(cls: type, name: str) -> MemberInfo | None:
    raw = inspect.getattr_static(cls, name)
    try:
        if isinstance(raw, (classmethod, staticmethod)):
            fn = raw.__func__
            sig = inspect.signature(getattr(cls, name))
            return MemberInfo(name, render_signature(name, sig), *split_doc(fn), "constructor")
        if isinstance(raw, property):
            ret = inspect.signature(raw.fget).return_annotation
            shown = name if ret is inspect.Signature.empty else f"{name}: {ret if isinstance(ret, str) else inspect.formatannotation(ret)}"
            return MemberInfo(name, shown, *split_doc(raw.fget), "property")
        if inspect.isfunction(raw):
            return MemberInfo(name, render_signature(name, drop_first(inspect.signature(raw))), *split_doc(raw), "method")
    except (TypeError, ValueError):  # no introspectable signature
        return None
    return None


def _class_entry(cls: type, anchor_name: str, qualname: str) -> ApiEntry:
    try:
        sig = render_signature(cls.__name__, inspect.signature(cls))
    except (TypeError, ValueError):
        sig = cls.__name__
    summary, rest = split_doc(cls)
    members = []
    for name, value in cls.__dict__.items():
        if name.startswith("_"):
            continue
        info = _member(cls, name)
        if info is not None:
            members.append((f"api-{anchor_name}-{name}", info))
    order = {"constructor": 0, "method": 1, "property": 2}
    members.sort(key=lambda item: (order.get(item[1].group, 3), item[1].name))
    fields_ = ()
    if dataclasses.is_dataclass(cls):
        fields_ = tuple((f.name, f.type if isinstance(f.type, str) else inspect.formatannotation(f.type), default_text(f))
                        for f in dataclasses.fields(cls) if not f.name.startswith("_"))
    return ApiEntry(f"api-{anchor_name}", cls.__name__, qualname, "class", sig, summary, rest, tuple(members), fields_)


def default_text(f: dataclasses.Field) -> str:
    if f.default is not dataclasses.MISSING:
        return repr(f.default)
    if f.default_factory is not dataclasses.MISSING:
        factory = f.default_factory
        return {dict: "{}", tuple: "()", list: "[]"}.get(factory, f"{getattr(factory, '__name__', 'factory')}()")
    return "required"


def api() -> list[ApiEntry]:
    """RobotTwin first, then every public name of sim2real.calibration (its __all__), so the backend's CalibrationConfig, CalibrationPlan,
    CalibrationRecord, plan and collect appear here the moment they are exported, with no edit to the site."""
    from sim2real.twin import RobotTwin  # noqa: PLC0415

    entries = [_class_entry(RobotTwin, "RobotTwin", "sim2real.RobotTwin")]
    taken = {entries[0].anchor, *(a for a, _m in entries[0].members)}
    try:
        cal = importlib.import_module("sim2real.calibration")
    except ImportError:
        return entries
    for name in getattr(cal, "__all__", ()):
        obj = getattr(cal, name, None)
        if obj is None:
            continue
        anchor = f"api-{name}"
        if anchor in taken:
            continue
        qual = f"sim2real.calibration.{name}"
        own = getattr(obj, "__name__", name)
        if (inspect.isclass(obj) or inspect.isroutine(obj)) and own != name and getattr(cal, own, None) is obj:
            # WHY one line: an alias (CalibrationPlan of CalibrationSchedule, generate_schedule of plan) is the same object under a second
            # name; its full entry would repeat every member under a second set of anchors
            entries.append(ApiEntry(anchor, name, qual, "alias", f"{name} = {own}",
                                    f"Alias of `{own}`: the same object, documented under its own name.", ""))
            taken.add(anchor)
            continue
        if inspect.isclass(obj):
            entry = _class_entry(obj, name, qual)
        elif inspect.isroutine(obj):
            try:
                sig = render_signature(name, inspect.signature(obj))
            except (TypeError, ValueError):
                sig = name
            entry = ApiEntry(anchor, name, qual, "function", sig, *split_doc(obj))
        elif inspect.ismodule(obj):
            entry = ApiEntry(anchor, name, qual, "module", f"import {qual}", *split_doc(obj))
        else:
            entry = ApiEntry(anchor, name, qual, "value", f"{name} = {obj!r}"[:200], "", "")
        members = tuple((a, m) for a, m in entry.members if a not in taken)
        entry = ApiEntry(entry.anchor, entry.name, entry.qualname, entry.kind, entry.signature, entry.summary, entry.rest, members, entry.fields)
        taken |= {entry.anchor, *(a for a, _m in members)}
        entries.append(entry)
    return entries


# ------------------------------------------------------------------------------------------------------- docs


def docs() -> list[tuple[str, str, str, str]]:
    """(slug, title, label, markdown) for every docs file that exists."""
    out = []
    for slug_, path, label in DOCS:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), label)
        out.append((slug_, title, label, text))
    return out


def source_stamp() -> str:
    """'sim2real @ 5d4cab0' for the footer; the commit part is best effort."""
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "sim2real"
    return f"sim2real @ {sha}"
