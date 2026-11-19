"""What calibrate() runs, and in what order (PEP 0001 §4-5): models picked per part give parameters, the catalog routines that identify them
are selected by a metric, and the selected routines are ordered from what each declares it needs.

    from sim2real.calibration import plan, select, order
    plan({"cam": ("camera", "M1.measurement.distortion")}).ids   # ('camera.exposure_lock', 'camera.intrinsics_charuco', ...)
    plan(twin).steps                                               # a rig twin: its own routines, in the declared order
    twin.generate_schedule().summary()                             # the same CalibrationSchedule: each step's runs, known now or made after
    order(routines, names=names)                                   # the same objects, ordered

The schedule (``_bind``, on a twin that ships its routines): each step's runs bound at the priors, each run's command typed (sim2real.rig.Run),
and whether its commands are known now, made after an earlier step runs, or it is fit only, from what each routine declares.

The order (``order``): a hard graph from ``requires`` (after every routine that identifies or configures the name) and ``refines`` (after
every OTHER routine that sets the name, provisionally or not), sorted by stdlib graphlib; among the ready routines the first by: no unplaced
soft predecessor (``uses``: after a routine that finds the name, ignored where it contradicts a hard edge), then the kind's stage
(cards.schema.KIND_STAGE: configure -> fit -> tune -> measure -> use), then wall time, then id. A hard cycle is refused.

WHY three edge kinds and not one (measured on the UR wrist's six routines, PEP 0001 §4): with one "reads" edge the wrist is a cycle (the
backlash reversal reads the breakaway prior for its cap, the breakaway reads the backlash). The ruler is the wrist's hand order as it ran
(src/sim2real/data/ur_wrist_one_click_2026-11-11.json), reproduced in all 720 input orders by tests/test_calibration_backend.py.

Layer: like twin.py and rig.py, right of every folder; no layer imports this package. It may call anything below it.
"""

from __future__ import annotations

import copy
import dataclasses
import graphlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..cards import domain as dm
from ..cards import registry as reg
from ..cards.schema import KIND_STAGE, KIND_WORDS, Configures, Identifies
from . import recovery as rec
from .config import CalibrationConfig
from .options import options, routine_rank

CATALOG = "src/sim2real/cards/calibration.py"


class CalibrationPlanError(ValueError):
    """A plan that cannot be made as asked: an unregistered custom routine, an explicit order that breaks a requirement, a strict budget
    exceeded, recorded data missing a planned run."""


class CalibrationCycleError(ValueError):
    """The declared hard edges (requires, refines) form a cycle. `cycle`: the routine ids on it."""

    def __init__(self, message: str, cycle: Sequence[str]):
        super().__init__(message)
        self.cycle = tuple(cycle)


# --- declarations ------------------------------------------------------------------------------------------------------------------------


def _catalog() -> dict[str, Any]:
    return {r.id: r for r in reg.ROUTINES}


@dataclass(frozen=True)
class Declaration:
    """What a routine says about itself, resolved: the object's own attribute where it carries one, else the catalog's by routine id.
    identifies / configures / adjusts are what it writes (keys, or names for a bare catalog routine); requires / uses / refines are
    names (or keys) it needs."""
    id: str
    identifies: tuple[str, ...]
    configures: tuple[str, ...]
    adjusts: tuple[str, ...]
    requires: tuple[str, ...]
    uses: tuple[str, ...]
    refines: tuple[str, ...]
    kind: str
    title: str
    setting: str
    wall_time_s: float
    operator_time_s: float
    equipment_usd: float
    registered: bool


def _written(items) -> tuple[str, ...]:
    """Keys or names a routine writes: strings as they are, a catalog Identifies as its (renamed) parameter names, a Configures as its
    setting names."""
    out: list[str] = []
    for item in items or ():
        if isinstance(item, Identifies):
            out += [dm.legacy_parameter(item.card, p)[1] if item.card in dm.CARD_TYPE else p for p in item.parameters]
        elif isinstance(item, Configures):
            out += list(item.settings)
        else:
            out.append(str(item))
    return tuple(dict.fromkeys(out))


def declaration(routine: Any) -> Declaration:
    """A routine's declaration (see Declaration). WHY the object first: a custom routine declares its own needs; a rig's routine carries
    only what it runs (id, identifies, adjusts) and the catalog speaks for the rest."""
    rid = str(getattr(routine, "id"))
    cat = _catalog().get(rid)

    def pick(name: str, default):
        if hasattr(routine, name):
            return getattr(routine, name)
        return getattr(cat, name) if cat is not None and hasattr(cat, name) else default

    wall = getattr(routine, "wall_time_s", None)
    if wall is None:
        wall = float(cat.wall_time.value or 0.0) if cat is not None else 0.0
    operator = getattr(routine, "operator_time_s", None)
    if operator is None:
        operator = float(cat.operator_time.value or 0.0) if cat is not None else 0.0
    equipment = getattr(routine, "equipment_usd", None)
    if equipment is None:
        equipment = float(reg.equipment_cost(cat).value or 0.0) if cat is not None else 0.0
    return Declaration(
        id=rid, identifies=_written(pick("identifies", ())), configures=_written(pick("configures", ())),
        adjusts=_written(getattr(routine, "adjusts", ())), requires=tuple(pick("requires", ())), uses=tuple(pick("uses", ())),
        refines=tuple(pick("refines", ())), kind=str(pick("kind", "identify")), title=str(pick("title", rid)),
        setting=str(pick("setting", "both")), wall_time_s=float(wall), operator_time_s=float(operator), equipment_usd=float(equipment),
        registered=cat is not None)


def _tokens(keys: Sequence[str], names: Mapping[str, str] | None) -> set[str]:
    """A written key matches a needed name by the key itself or, when `names` maps it, by its name (no key is parsed)."""
    out = set(keys)
    if names:
        out |= {names[k] for k in keys if k in names}
    return out


@dataclass
class _Graph:
    hard: dict[int, set[int]]                       # node -> hard predecessors
    soft: dict[int, set[int]]                       # node -> soft predecessors that do not contradict a hard edge
    edges: dict[tuple[int, int], list[tuple[str, str]]]  # (before, after) -> [(edge kind, name)]
    unmet: dict[int, list[str]]                     # node -> required names nothing in the set provides


def _graph(decls: Sequence[Declaration], names: Mapping[str, str] | None) -> _Graph:
    found = [_tokens(d.identifies + d.configures, names) for d in decls]
    sets = [found[i] | _tokens(d.adjusts, names) for i, d in enumerate(decls)]
    n = len(decls)
    hard: dict[int, set[int]] = {i: set() for i in range(n)}
    soft_raw: dict[int, set[int]] = {i: set() for i in range(n)}
    edges: dict[tuple[int, int], list[tuple[str, str]]] = {}
    unmet: dict[int, list[str]] = {i: [] for i in range(n)}
    for i, d in enumerate(decls):
        for name in d.requires:
            providers = [j for j in range(n) if j != i and name in found[j]]
            if not providers:
                unmet[i].append(name)
            for j in providers:
                hard[i].add(j)
                edges.setdefault((j, i), []).append(("requires", name))
        for name in d.refines:
            for j in range(n):
                if j != i and name in sets[j]:
                    hard[i].add(j)
                    edges.setdefault((j, i), []).append(("refines", name))
        for name in d.uses:
            for j in range(n):
                if j != i and name in found[j]:
                    soft_raw[i].add(j)
                    edges.setdefault((j, i), []).append(("uses", name))
    def ancestors(i: int) -> set[int]:
        seen: set[int] = set()
        stack = list(hard[i])
        while stack:
            j = stack.pop()
            if j not in seen:
                seen.add(j)
                stack.extend(hard[j])
        return seen

    # WHY ignored, not refused (PEP 0001 §4): a soft edge is a preference ("read it if found, else the prior serves"); where the hard
    # graph puts the reader first (the backlash reversal reads the breakaway, which needs the backlash), the prior serves
    soft = {i: {j for j in preds if i not in ancestors(j)} for i, preds in soft_raw.items()}
    return _Graph(hard, soft, edges, unmet)


def _cycle_error(cycle_nodes: Sequence[int], decls: Sequence[Declaration], graph: _Graph) -> CalibrationCycleError:
    ids = [decls[i].id for i in cycle_nodes]
    hops = []
    for a, b in zip(cycle_nodes[:-1], cycle_nodes[1:]):
        keys = ", ".join(f"{kind} {name}" for kind, name in graph.edges.get((a, b), []) if kind != "uses") or "?"
        hops.append(f"{decls[b].id} runs after {decls[a].id} ({decls[b].id} {keys})")
    unique = list(dict.fromkeys(ids))
    message = (f"the calibration routines {', '.join(unique)} need each other first, so no order runs them: " + "; ".join(hops)
               + ". Break the cycle in a declaration: a name a routine can read at its prior when nothing has found it yet is a soft "
                 "edge, `uses`, not `requires`")
    return CalibrationCycleError(message, unique)


def _sorted(decls: Sequence[Declaration], graph: _Graph) -> list[int]:
    sorter = graphlib.TopologicalSorter({i: graph.hard[i] for i in range(len(decls))})
    try:
        sorter.prepare()
    except graphlib.CycleError as caught:
        raise _cycle_error(list(caught.args[1]), decls, graph) from None
    placed: set[int] = set()
    pool: list[int] = []
    out: list[int] = []

    def key(i: int):
        d = decls[i]
        stage = KIND_STAGE.index(d.kind) if d.kind in KIND_STAGE else len(KIND_STAGE)
        return (bool(graph.soft[i] - placed), stage, d.wall_time_s, d.id, i)

    while sorter.is_active():
        pool.extend(sorter.get_ready())
        best = min(pool, key=key)
        pool.remove(best)
        placed.add(best)
        out.append(best)
        sorter.done(best)
    return out


def order(routines: Sequence[Any], names: Mapping[str, str] | None = None) -> list[Any]:
    """The routines in the order their declarations give (see the module docstring); the SAME objects, never copies. `names` maps
    '<instance>.<name>' keys to names, so a key a routine writes satisfies a name another needs; without it, keys match keys only.
    Raises CalibrationCycleError when the hard edges form a cycle."""
    items = list(routines)
    decls = [declaration(r) for r in items]
    graph = _graph(decls, names)
    return [items[i] for i in _sorted(decls, graph)]


# --- selection: models -> parameters -> routines ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    """select()'s answer. `parameters`: (instance, type, name) to find (the picked models' parameters less the known). `routines`: a
    minimal cover (drop any one and something only it covered goes uncovered). `setup`: the configure / tune routines the types always want
    or the config includes; never part of the cover. `covers`: {routine: [(instance, name)]}. `why`: {routine: str}. `dropped`:
    [(routine, why)]. `uncovered`: [(instance, name, why)]. `configures`: {setup routine: [keys it writes]}."""
    parameters: tuple[tuple[str, str, str], ...]
    routines: tuple[str, ...]
    setup: tuple[str, ...]
    covers: dict[str, tuple[tuple[str, str], ...]]
    why: dict[str, str]
    dropped: tuple[tuple[str, str], ...]
    uncovered: tuple[tuple[str, str, str], ...]
    configures: dict[str, tuple[str, ...]] = field(default_factory=dict)
    level: str = "1x"


def _picked(picked: Mapping[str, Any], config: CalibrationConfig) -> dict[str, tuple[str, str]]:
    out = {}
    for inst, spec in picked.items():
        tid, mid = (spec, None) if isinstance(spec, str) else tuple(spec)
        mid = config.models.get(inst, mid) or options(tid).models[0]
        dm.model(tid, mid)  # KeyError naming the type's ladder when it is not on it
        out[inst] = (dm.entity_type(tid).id, mid)
    return out


def _recovery_words(rid: str, level: str) -> str:
    entry = rec.recovery(rid, level)
    if entry is None:
        return f"recovery at {level} not graded"
    worst = entry.get("worst_error_over_tolerance")
    verdict = {True: "passes", False: "fails", None: "ungraded"}[entry.get("pass")]
    return f"recovery at {level} {verdict}" + ("" if worst is None else f" (worst error {worst:.3g} x tolerance)")


def _setting_drop(r, budget) -> str | None:
    if budget.allows(r.setting):
        return None
    return f"outside the budget: it runs at the {r.setting} only and the budget allows {' / '.join(budget.settings)}"


def _filter(r, config: CalibrationConfig) -> str | None:
    if r.id in config.exclude:
        return "excluded (CalibrationConfig.exclude)"
    if r.status == "not implemented":
        return f"not implemented ({CATALOG} status)"
    return _setting_drop(r, config.budget)


def _configured_keys(r, picked: Mapping[str, tuple[str, str]]) -> tuple[str, ...]:
    out = []
    for c in r.configures:
        tid = dm.CARD_TYPE.get(c.card)
        out += [f"{inst}.{s}" for inst, (t, _m) in picked.items() if t == tid for s in c.settings]
    return tuple(dict.fromkeys(out))


def select(picked: Mapping[str, Any], config: CalibrationConfig | None = None) -> Selection:
    """Models picked per part -> parameters -> routines (PEP 0001 §5). `picked`: {instance: (type, model id)} (or {instance: type} for
    today's model); config.models overrides a pick. The metric between alternatives is options.routine_rank at config.level."""
    config = config or CalibrationConfig()
    catalog = _catalog()
    level, budget = config.level, config.budget
    rank = lambda rid: routine_rank(rid, level, budget.settings)  # noqa: E731
    chosen_models = _picked(picked, config)
    every = [(inst, tid, n) for inst, (tid, mid) in chosen_models.items() for n in dm.model(tid, mid).parameters]
    parameters = tuple(p for p in every if f"{p[0]}.{p[2]}" not in config.known)
    wanted = {(i, n) for i, _t, n in parameters}
    table = dm.parameter_routines()
    covers_all: dict[str, list[tuple[str, str]]] = {}
    for inst, tid, name in every:
        for rid in table.get(tid, {}).get(name, []):
            covers_all.setdefault(rid, []).append((inst, name))
    covers = {rid: tuple(c for c in cs if c in wanted) for rid, cs in covers_all.items()}
    dropped: dict[str, str] = {}
    for rid in covers_all:
        reason = _filter(catalog[rid], config)
        if reason is None and not covers[rid]:
            reason = "known: every parameter it identifies here is in CalibrationConfig.known"
        if reason:
            dropped[rid] = reason
    eligible = [rid for rid in covers_all if rid not in dropped]
    forced = []
    setup: list[str] = []
    why: dict[str, str] = {}
    for rid in config.include:
        if rid not in catalog:
            raise CalibrationPlanError(f"CalibrationConfig.include names {rid!r}, which is not a routine in {CATALOG}")
        if catalog[rid].kind in ("configure", "tune"):
            if rid not in setup:
                setup.append(rid)
                why[rid] = "setup: CalibrationConfig.include brings it in"
        elif rid in eligible:
            forced.append(rid)
            why[rid] = "CalibrationConfig.include brings it in"
    for tid in dict.fromkeys(t for t, _m in chosen_models.values()):
        for rid in options(tid).setup:
            if rid not in setup:
                setup.append(rid)
                why[rid] = f"setup: the {tid} type always wants it before it is fitted (sim2real.calibration.options.SETUP)"
    for rid in list(setup):
        reason = _filter(catalog[rid], config)
        if reason:
            setup.remove(rid)
            why.pop(rid, None)
            dropped[rid] = reason
    # the cover: the most constrained parameter first, its best-ranked routine; then prune any routine the others make redundant
    left = set(wanted)
    chosen = list(forced)
    for rid in chosen:
        left -= set(covers[rid])
    order_of = {p: k for k, p in enumerate((i, n) for i, _t, n in parameters)}
    while True:
        offers = {p: [rid for rid in eligible if p in covers[rid]] for p in left}
        open_ = [p for p, rids in offers.items() if rids]
        if not open_:
            break
        p = min(open_, key=lambda q: (len(offers[q]), order_of[q]))
        best = min(offers[p], key=rank)
        chosen.append(best)
        left -= set(covers[best])
    for rid in sorted(chosen, key=rank, reverse=True):
        if rid in forced:
            continue
        rest = {c for other in chosen if other != rid for c in covers[other]}
        if set(covers[rid]) <= rest:
            chosen.remove(rid)
    chosen.sort(key=rank)
    # the budget's time and money: drop the lowest-ranked until it fits (refused when strict)
    chosen, setup, over = _fit_budget(chosen, setup, config, rank)
    dropped.update(over)
    for rid in chosen:
        if rid not in why:
            alts = [a for a in eligible if a != rid and set(covers[a]) & set(covers[rid])]
            names = ", ".join(f"{i}.{n}" for i, n in covers[rid])
            why[rid] = (f"identifies {names}; {_recovery_words(rid, level)}"
                        + (f"; ranked ahead of {', '.join(sorted(alts, key=rank))}" if alts else "; the only routine left for it"))
    covered = {c for rid in chosen for c in covers[rid]}
    for rid in eligible:
        if rid not in chosen and rid not in dropped:
            by = sorted({o for o in chosen for c in covers[rid] if c in covers[o]}, key=rank)
            dropped[rid] = (f"not needed: {', '.join(by)} already cover{'s' if len(by) == 1 else ''} what it identifies here"
                            if by else "not needed")
    uncovered = []
    for inst, _tid, name in parameters:
        if (inst, name) in covered:
            continue
        rids = [rid for rid, cs in covers_all.items() if (inst, name) in cs]
        if not rids:
            uncovered.append((inst, name, "no catalog routine identifies it yet"))
        else:
            uncovered.append((inst, name, "its routines were dropped: " + "; ".join(f"{rid} ({dropped.get(rid, 'not chosen')})" for rid in rids)))
    configures = {rid: _configured_keys(catalog[rid], chosen_models) for rid in setup}
    return Selection(parameters, tuple(chosen), tuple(setup), {rid: covers[rid] for rid in chosen} | {rid: () for rid in setup},
                     why, tuple(dropped.items()), tuple(uncovered), configures, level)


def _fit_budget(chosen: list[str], setup: list[str], config: CalibrationConfig, rank) -> tuple[list[str], list[str], dict[str, str]]:
    budget = config.budget
    catalog = _catalog()
    decl = {rid: declaration(catalog[rid]) for rid in chosen + setup}
    over: dict[str, str] = {}
    _check_strict([decl[r] for r in chosen + setup], config)
    keep = list(chosen)
    for rid in sorted(chosen, key=rank, reverse=True):
        wall, usd = _spend([decl[r] for r in keep + setup])
        too_long = budget.max_wall_time_s is not None and wall > budget.max_wall_time_s
        too_dear = budget.max_equipment_usd is not None and usd > budget.max_equipment_usd
        if not (too_long or too_dear):
            break
        keep.remove(rid)
        over[rid] = (f"outside the budget: the plan's wall time {wall:.0f} s is over max_wall_time_s {budget.max_wall_time_s:g} s"
                     if too_long else f"outside the budget: the plan's equipment ${usd:,.0f} is over max_equipment_usd ${budget.max_equipment_usd:,.0f}")
    return keep, setup, over


def _spend(decls: Sequence[Declaration]) -> tuple[float, float]:
    """Summed wall time; equipment $ over the distinct items (one caliper serves every routine that needs it)."""
    catalog = _catalog()
    items: dict[str, float] = {}
    loose = 0.0
    for d in decls:
        r = catalog.get(d.id)
        if r is None:
            loose += d.equipment_usd
            continue
        for e in r.equipment:
            items[e] = float(reg.EQUIPMENT[e].cost.value or 0.0)
    return sum(d.wall_time_s for d in decls), sum(items.values()) + loose


def _check_strict(decls: Sequence[Declaration], config: CalibrationConfig) -> None:
    if not config.strict:
        return
    budget = config.budget
    wall, usd = _spend(decls)
    if budget.max_wall_time_s is not None and wall > budget.max_wall_time_s:
        raise CalibrationPlanError(f"the plan's wall time is {wall:.0f} s, over the budget's max_wall_time_s {budget.max_wall_time_s:g} s "
                                   f"(strict=True refuses instead of dropping routines): {', '.join(d.id for d in decls)}")
    if budget.max_equipment_usd is not None and usd > budget.max_equipment_usd:
        raise CalibrationPlanError(f"the plan's equipment is ${usd:,.0f}, over the budget's max_equipment_usd ${budget.max_equipment_usd:,.0f} "
                                   "(strict=True refuses instead of dropping routines)")


# --- the plan -------------------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanStep:
    """One step of a plan, in run order (the record's plan.steps rows: docs/CALIBRATE.md). `routine_object` is what runs (a rig's routine,
    an injected one, or a catalog stand-in that cannot run)."""
    routine: str
    title: str
    kind: str
    setting: str
    identifies: tuple[str, ...]
    requires: tuple[str, ...]
    uses: tuple[str, ...]
    refines: tuple[str, ...]
    after: tuple[str, ...]
    why_here: str
    wall_time_s: float
    operator_time_s: float
    equipment_usd: float
    recovery: dict | None
    source: str                                  # "rig" | "custom" | "catalog"
    routine_object: Any = field(default=None, compare=False, repr=False)
    # the schedule's facts (bound on a rig's plan; kept out of to_dict: the record's step rows are sim2real.calibration/1's):
    # runs: its runs at the priors (sim2real.rig.Run), () = it plays nothing, None = not bound or no preview (its runs() needs a value
    # only an earlier step finds). status: "known now" | "made after" | "fit only" ("" = not bound). commands_after: the steps whose
    # found values its commands are made from.
    runs: tuple[Any, ...] | None = field(default=None, compare=False, repr=False)
    status: str = field(default="", compare=False)
    commands_after: tuple[str, ...] = field(default=(), compare=False)

    def to_dict(self) -> dict:
        return {"routine": self.routine, "title": self.title, "kind": self.kind, "setting": self.setting, "identifies": list(self.identifies),
                "requires": list(self.requires), "uses": list(self.uses), "refines": list(self.refines), "after": list(self.after),
                "why_here": self.why_here, "wall_time_s": self.wall_time_s, "operator_time_s": self.operator_time_s,
                "equipment_usd": self.equipment_usd, "recovery": None if self.recovery is None else dict(self.recovery), "source": self.source}


@dataclass(frozen=True)
class CalibrationSchedule:
    """What calibrate() runs, in order, and what it leaves out: a static object to look at before anything runs. `ids`: the routine ids in
    run order. `dropped`: [(routine, why)]. `uncovered`: [(instance, name, why)]. `assumed`: [(routine, name, why)], a requirement no planned
    routine provides, held at its prior. `source`: "planner" (the declared order) or "config.order". `totals`: wall_time_s,
    operator_time_s, equipment_usd.

    On a twin that ships its routines, each step also holds its runs bound at the priors (PlanStep.runs, each a sim2real.rig.Run with its
    typed command) and says whether its commands are known now, made after an earlier step runs (from what the routine declares its
    commands read: commands_read, else the keys it requires that an earlier step writes; never from the order, never probed), or whether
    it is fit only. `runs`: the runs known now; `previews`: a made-after step's runs at the priors. calibrate() is held to it.

    WHY this name, with CalibrationPlan kept as an alias (Zach, Daily Note 2026-11-17): "the first output I think should be like A
    CalibrationSchedule ... a static description of the routines that will be run... so its nice to be able to kinda like see it as a
    static object ... internall mabye that does .generate_schedule() -> CalibrationSchedule"."""
    ids: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    dropped: tuple[tuple[str, str], ...]
    uncovered: tuple[tuple[str, str, str], ...]
    assumed: tuple[tuple[str, str, str], ...]
    source: str
    totals: dict
    level: str = "1x"
    twin: str | None = None

    @property
    def routines(self) -> tuple[Any, ...]:
        """The routine objects in run order (what a runner plays)."""
        return tuple(s.routine_object for s in self.steps)

    @property
    def runs(self) -> tuple[Any, ...]:
        """The runs known now, each once, in the order they are first played: what the robot plays whatever the earlier fits find."""
        return _distinct(r for s in self.steps if s.status == "known now" and s.runs for r in s.runs)

    @property
    def previews(self) -> tuple[Any, ...]:
        """A made-after step's runs as they would be at the priors, each once: never shown as known, since the earlier fit moves them."""
        return _distinct(r for s in self.steps if s.status == "made after" and s.runs for r in s.runs)

    def to_dict(self) -> dict:
        out = {"twin": self.twin, "source": self.source, "level": self.level, "steps": [s.to_dict() for s in self.steps],
               "dropped": [{"routine": r, "why": w} for r, w in self.dropped],
               "uncovered": [{"instance": i, "name": n, "key": f"{i}.{n}", "why": w} for i, n, w in self.uncovered],
               "assumed": [{"routine": r, "requires": n, "why": w} for r, n, w in self.assumed], "totals": dict(self.totals)}
        # WHY only when a step is bound, and beside the steps rather than in them: a catalog plan's dict stays as it was, and the record's
        # step rows (sim2real.calibration/1, STEP_KEYS) stay frozen
        if any(s.status for s in self.steps):
            out["schedule"] = [_schedule_row(s) for s in self.steps]
        return out

    def summary(self) -> str:
        lines = [f"plan ({self.source}, recovery at {self.level}): {len(self.steps)} routines, "
                 f"{self.totals['wall_time_s']:.0f} s wall, {self.totals['operator_time_s']:.0f} s hands-on, ${self.totals['equipment_usd']:,.0f} equipment"]
        for k, s in enumerate(self.steps, 1):
            lines.append(f"  {k}. {s.routine:34s} {KIND_WORDS.get(s.kind, s.kind):9s} {s.setting:8s} {s.why_here}")
            words = _schedule_words(s)
            if words:
                lines.append(f"       {words}")
        lines += [f"  dropped {r}: {w}" for r, w in self.dropped]
        lines += [f"  uncovered {i}.{n}: {w}" for i, n, w in self.uncovered]
        lines += [f"  assumed {n} for {r}: {w}" for r, n, w in self.assumed]
        return "\n".join(lines)


CalibrationPlan = CalibrationSchedule  # the name it had until 2026-11-18: every import and isinstance keeps working


# --- the schedule: each step's runs at the priors, and what its commands wait for -------------------------------------------------------


def _distinct(runs) -> tuple[Any, ...]:
    out: dict[str, Any] = {}
    for run in runs:
        out.setdefault(run.id, run)
    return tuple(out.values())


def _run_row(run: Any, preview: bool) -> dict:
    command = getattr(run, "command", None)
    seconds = run.robot_seconds() if callable(getattr(run, "robot_seconds", None)) else None
    return {"id": run.id, "split": run.split, "command": None if command is None else type(command).__name__,
            "seconds": None if seconds is None else [float(seconds[0]), float(seconds[1])], "preview": preview}


def _schedule_row(step: PlanStep) -> dict:
    preview = step.status == "made after"
    return {"routine": step.routine, "status": step.status, "commands_after": list(step.commands_after),
            "runs": None if step.runs is None else [_run_row(r, preview) for r in step.runs]}


def _runs_words(runs: Sequence[Any], shown: int = 4) -> str:
    def one(run) -> str:
        from ..rig import _span  # noqa: PLC0415

        command = getattr(run, "command", None)
        seconds = run.robot_seconds() if callable(getattr(run, "robot_seconds", None)) else None
        return f"{run.id} ({'no command' if command is None else type(command).__name__}, {_span(seconds)})"

    head = ", ".join(one(r) for r in runs[:shown])
    return head + (f" and {len(runs) - shown} more" if len(runs) > shown else "")


def _schedule_words(step: PlanStep) -> str:
    """The step's line of the schedule in summary()."""
    whole = "no preview at the priors (its runs() needs a value no prior states): its time is counted whole"
    if step.status == "fit only":
        return "fit only: no runs of its own"
    if step.status == "known now":
        return f"known now: {_runs_words(step.runs)}" if step.runs is not None else f"known now; {whole}"
    if step.status == "made after":
        return (f"commands made after {', '.join(step.commands_after)} runs; "
                + (f"preview at the priors: {_runs_words(step.runs)}" if step.runs is not None else whole))
    return ""


def _bind(steps: Sequence[PlanStep], priors: Mapping[str, float], names: Mapping[str, str], known: Mapping[str, float]) -> tuple[PlanStep, ...]:
    """Each step's runs at the priors and its status (see CalibrationSchedule). Each routine's runs() is called twice at the priors: once to
    bind, once to check it is static. Refused: runs() that change between the two calls; one run id bound to two different runs; a run id
    shared by a known-now step and a made-after step (once the earlier step has run, the two differ under one id).

    WHY from the declaration and never by probing runs() at moved values (Zach, 2026-11-17: "routines can almost like declare depencies on
    what they require to run ahead of time so you can ... atuomaticaly generate the schedule"): a routine says what its commands read
    (commands_read; by default the keys it requires that an earlier step writes), and a routine whose commands read more than it says is
    caught at play time by name (rig.RigRunner.calibrate(schedule=)). A known value is never moved by its writer, so it makes nothing wait."""
    from ..rig import _same_run, _same_runs  # noqa: PLC0415

    decls = [declaration(s.routine_object) for s in steps]
    written = {k for d in decls for k in d.identifies + d.configures + d.adjusts}
    writes = [_tokens(d.identifies + d.configures + d.adjusts, names) for d in decls]
    seen: dict[str, tuple[Any, str, str]] = {}   # run id -> (the run, the routine that binds it, its status)
    out = []
    for i, step in enumerate(steps):
        routine = step.routine_object
        if not callable(getattr(routine, "runs", None)):
            out.append(step)  # a catalog stand-in, or an injected routine with nothing to play: not bound
            continue
        declared = getattr(routine, "commands_read", None)
        reads = step.requires if declared is None else _expand(tuple(declared), names, written)
        reads = [k for k in reads if k not in known]
        after = tuple(dict.fromkeys(steps[j].routine for j in range(i) for k in reads if k in writes[j]))
        try:
            runs = tuple(routine.runs(dict(priors)))
        except (LookupError, OSError):
            runs = None   # no preview: its commands need a value no prior states (or a file this machine does not hold)
        except Exception as caught:
            caught.add_note(f"raised by {step.routine}'s runs() at the priors, while plan() bound its schedule")
            raise
        if runs is not None:
            again = tuple(routine.runs(dict(priors)))
            if not _same_runs(runs, again):
                raise CalibrationPlanError(f"{step.routine}: runs() gave {[r.id for r in runs]} and then {[r.id for r in again]} for the same "
                                           "values. A schedule is static: runs() must give the same runs for the same values (draw any "
                                           "randomness from a seed in the values or the run's spec)")
        status = "fit only" if runs == () else "made after" if after else "known now"
        if status == "fit only":
            after = ()
        for run in runs or ():
            if run.id not in seen:
                seen[run.id] = (run, step.routine, status)
                continue
            other, by, by_status = seen[run.id]
            if not _same_run(run, other):
                raise CalibrationPlanError(f"run id {run.id!r} is bound to two different runs, by {by} and by {step.routine} (another command, "
                                           "spec, split or length): one run id is one command; give one of them another id")
            if (by_status == "made after") != (status == "made after"):
                late, early = (step.routine, by) if status == "made after" else (by, step.routine)
                raise CalibrationPlanError(f"run id {run.id!r} is shared by {early}, known now, and {late}, whose commands are made after "
                                           f"an earlier step runs: they agree at the priors, but once that step has run the two commands "
                                           f"differ under one id; give {late}'s run an id of its own")
        out.append(dataclasses.replace(step, runs=runs, status=status, commands_after=after))
    return tuple(out)


@dataclass(frozen=True)
class _CatalogRoutine:
    """A catalog routine planned for picked models (no rig implements it here): what it writes on these instances. It cannot run."""
    id: str
    identifies: tuple[str, ...]
    configures: tuple[str, ...]


def apply_options(routine: Any, routine_options: Mapping[str, Any]) -> Any:
    """A COPY of the routine with these options (its `options` dict when it has one, else its attribute of that name); the routine itself
    is never changed. A name it does not have raises KeyError naming the option."""
    if not routine_options:
        return routine
    own = getattr(routine, "options", None)
    own = dict(own) if isinstance(own, Mapping) else None
    out = copy.copy(routine)
    for name, value in routine_options.items():
        if own is not None and name in own:
            own[name] = value
        elif name != "options" and hasattr(routine, name) and not callable(getattr(routine, name)):
            object.__setattr__(out, name, value)
        else:
            have = sorted(own) if own is not None else [f.name for f in dataclasses.fields(routine)] if dataclasses.is_dataclass(routine) else []
            raise KeyError(f"{getattr(routine, 'id', routine)!r} has no option {name!r} (its options: {have})")
    if own is not None:
        object.__setattr__(out, "options", own)
    return out


def _expand(wanted: Sequence[str], names: Mapping[str, str], written: set[str]) -> tuple[str, ...]:
    """Needed names as keys, sorted: the keys some routine in the plan writes that carry the name, else every key that carries it, else the
    name itself (nothing carries it)."""
    out: list[str] = []
    for w in wanted:
        carrying = [k for k, n in names.items() if n == w]
        if w in names or w in written:
            carrying.append(w)
        mine = [k for k in carrying if k in written]
        out += mine or carrying or [w]
    return tuple(sorted(dict.fromkeys(out)))


def _recovery_entry(routine_id: str, level: str) -> dict | None:
    """A step's recovery: the level and the two numbers every grading carries (pass, worst error / tolerance), or None when ungraded."""
    entry = rec.recovery(routine_id, level)
    if entry is None:
        return None
    return {"level": level, "pass": entry.get("pass"), "worst_error_over_tolerance": entry.get("worst_error_over_tolerance")}


def _steps(items: Sequence[Any], sources: Sequence[str], names: Mapping[str, str], config: CalibrationConfig, *,
           validate: bool = True) -> tuple:
    """Order (declared or config.order) and describe. Returns (steps, assumed, source). validate=False describes config.order as given
    (a record of routines that already ran in a hand order), refusing nothing."""
    decls = [declaration(r) for r in items]
    graph = _graph(decls, names)
    if config.order is None:
        ranked = _sorted(decls, graph)
        source = "planner"
    else:
        position = {d.id: k for k, d in enumerate(decls)}
        unknown = [rid for rid in config.order if rid not in position]
        if unknown:
            raise CalibrationPlanError(f"CalibrationConfig.order names {unknown}, which this plan does not hold (it holds {sorted(position)})")
        ranked = [position[rid] for rid in config.order]
        at = {i: k for k, i in enumerate(ranked)}
        for (before, after), why in (graph.edges.items() if validate else ()):
            if before not in at or after not in at:
                continue
            for kind, name in why:
                if kind != "uses" and at[before] > at[after]:
                    verb = "finds" if kind == "requires" else "sets first"
                    raise CalibrationPlanError(f"CalibrationConfig.order runs {decls[after].id} before {decls[before].id}, but "
                                               f"{decls[after].id} {kind} {name}, which {decls[before].id} {verb}")
        if validate:
            _sorted(decls, graph)  # a hard cycle is refused whatever the order
        source = "config.order"
    written = {k for d in decls for k in d.identifies + d.configures + d.adjusts}
    steps, assumed = [], []
    for i in ranked:
        d = decls[i]
        hard = sorted({decls[j].id for j in graph.hard[i]})
        soft = sorted({decls[j].id for j in graph.soft[i]})
        if source == "config.order":
            why_here = "CalibrationConfig.order puts it here" + (f"; after {', '.join(hard)} (requires/refines)" if hard else "")
        elif hard:
            why_here = f"after {', '.join(hard)} (requires/refines)"
        elif d.kind == "configure":
            why_here = "configure stage: nothing it requires is found by another routine, and set-up runs first"
        else:
            why_here = "nothing it requires is found by another routine"
        if soft and source == "planner":
            why_here += f"; prefers after {', '.join(soft)} (uses)"
        for name in graph.unmet[i]:
            assumed.append((d.id, name, "no planned routine finds it: held at its prior"))
        cat = _catalog().get(d.id)
        steps.append(PlanStep(
            routine=d.id, title=d.title, kind=d.kind, setting=d.setting, identifies=d.identifies + tuple(k for k in d.configures if k not in d.identifies),
            requires=_expand(d.requires, names, written), uses=_expand(d.uses, names, written), refines=_expand(d.refines, names, written),
            after=tuple(hard),
            why_here=why_here, wall_time_s=d.wall_time_s, operator_time_s=d.operator_time_s, equipment_usd=d.equipment_usd,
            recovery=_recovery_entry(d.id, config.level) if cat is not None else None, source=sources[i], routine_object=items[i]))
    return tuple(steps), tuple(assumed), source


def _totals(steps: Sequence[PlanStep]) -> dict:
    wall, usd = _spend([declaration(s.routine_object) for s in steps])
    return {"wall_time_s": wall, "operator_time_s": sum(s.operator_time_s for s in steps), "equipment_usd": usd}


def _custom(config: CalibrationConfig) -> dict[str, Any]:
    catalog = _catalog()
    out = {}
    for r in config.custom:
        rid = getattr(r, "id", None)
        if rid not in catalog:
            raise CalibrationPlanError(f"CalibrationConfig.custom holds a routine with id {rid!r}, which is not registered: a custom routine "
                                       f"replaces the implementation of a routine in {CATALOG} (ROUTINES); add its entry there first")
        out[rid] = r
    return out


def _with_config_options(items: list, config: CalibrationConfig, present: set[str]) -> list:
    catalog = _catalog()
    for rid in config.routines:
        if rid not in present and rid not in catalog:
            raise KeyError(f"CalibrationConfig.routines names {rid!r}, which is neither in this plan nor in {CATALOG}")
    return [apply_options(r, config.routines[r.id].options) if r.id in config.routines else r for r in items]


def _plan_catalog(picked: Mapping[str, Any], config: CalibrationConfig, twin: str | None = None) -> CalibrationSchedule:
    catalog = _catalog()
    sel = select(picked, config)
    chosen = _picked(picked, config)
    names = {f"{inst}.{p.name}": p.name for inst, (tid, _m) in chosen.items() for p in dm.entity_type(tid).parameters}
    for rid in sel.setup:
        for c in catalog[rid].configures:
            names.update({f"{inst}.{setting}": setting for inst, (tid, _m) in chosen.items() if tid == dm.CARD_TYPE.get(c.card)
                          for setting in c.settings})
    custom = _custom(config)
    items, sources = [], []
    for rid in sel.setup + sel.routines:
        if rid in custom:
            items.append(custom[rid])
            sources.append("custom")
        else:
            items.append(_CatalogRoutine(rid, tuple(f"{i}.{n}" for i, n in sel.covers.get(rid, ())), sel.configures.get(rid, ())))
            sources.append("catalog")
    items = _with_config_options(items, config, {r.id for r in items})
    steps, assumed, source = _steps(items, sources, names, config)
    return CalibrationSchedule(tuple(s.routine for s in steps), steps, sel.dropped, sel.uncovered, assumed, source, _totals(steps), config.level, twin)


def _plan_rig(twin: Any, config: CalibrationConfig, rig: Any = None) -> CalibrationSchedule:
    """A twin that ships its routines: a rig on the one-click seam (twin.runner.rig), or the pendulum tracer's example routines (`rig`:
    what SimRunner.schedule() gives, the planner's half of a RigBackend: name, parameters(), routines())."""
    catalog = _catalog()
    rig = twin.runner.rig if rig is None else rig
    description = twin.runner.description
    names = {f"{i.id}.{n}": n for i in description.instances for n in i.parameters}
    custom = _custom(config)
    items, sources = [], []
    for r in rig.routines():
        items.append(custom.get(r.id, r))
        sources.append("custom" if r.id in custom else "rig")
    for rid, r in custom.items():
        if rid not in {x.id for x in items}:
            items.append(r)
            sources.append("custom")
    for rid in config.include:
        if rid not in {x.id for x in items}:
            raise CalibrationPlanError(f"CalibrationConfig.include names {rid!r}, which {rig.name} does not implement: pass an "
                                       "implementation in CalibrationConfig.custom")
    items = _with_config_options(items, config, {r.id for r in items})
    dropped: list[tuple[str, str]] = []
    keep, keep_sources = [], []
    for r, src in zip(items, sources):
        cat = catalog.get(r.id)
        reason = None
        if r.id in config.exclude:
            reason = "excluded (CalibrationConfig.exclude)"
        elif cat is not None and _setting_drop(cat, config.budget):
            reason = _setting_drop(cat, config.budget)
        elif tuple(getattr(r, "identifies", ())) and all(k in config.known for k in r.identifies) and not getattr(r, "configures", ()):
            reason = "known: every parameter it identifies here is in CalibrationConfig.known"
        if reason:
            dropped.append((r.id, reason))
        else:
            keep.append(r)
            keep_sources.append(src)
    _check_strict([declaration(r) for r in keep], config)
    budget = config.budget
    # WHY drop from the end of the declared order: a routine late in the order needs the earlier ones, never the reverse
    source_of = {id(r): src for r, src in zip(keep, keep_sources)}
    if config.order is None:
        keep = order(keep, names)
        keep_sources = [source_of[id(r)] for r in keep]
    while keep and (budget.max_wall_time_s is not None or budget.max_equipment_usd is not None):
        wall, usd = _spend([declaration(r) for r in keep])
        too_long = budget.max_wall_time_s is not None and wall > budget.max_wall_time_s
        too_dear = budget.max_equipment_usd is not None and usd > budget.max_equipment_usd
        if not (too_long or too_dear):
            break
        last = keep.pop()
        keep_sources.pop()
        dropped.append((last.id, f"outside the budget: the plan's wall time {wall:.0f} s is over max_wall_time_s {budget.max_wall_time_s:g} s"
                        if too_long else f"outside the budget: the plan's equipment ${usd:,.0f} is over max_equipment_usd"))
    steps, assumed, source = _steps(keep, keep_sources, names, config)
    # the priors each step's runs are bound at: the description's stated values, the caller's known values on top (what the runner starts from)
    priors = {**{k: float(v) for k, v in description.values().items() if v is not None}, **config.known}
    steps = _bind(steps, priors, names, config.known)
    gone = {rid: why for rid, why in dropped}
    uncovered = []
    for p in rig.parameters():
        if p.routine in gone and p.key not in config.known:
            name = names.get(p.key, p.key)
            inst = p.key[: -len(name) - 1] if p.key.endswith("." + name) else p.key
            uncovered.append((inst, name, f"its routine {p.routine} was dropped: {gone[p.routine]}"))
    return CalibrationSchedule(tuple(s.routine for s in steps), steps, tuple(dropped), tuple(uncovered), assumed, source, _totals(steps),
                           config.level, getattr(rig, "name", description.id))


def plan(twin_or_picked: Any, config: CalibrationConfig | None = None) -> CalibrationSchedule:
    """What calibrate() would run, in what order, without running anything. Pass a RobotTwin (a rig twin plans its own routines; the
    pendulum tracer plans the routines its example ships, sysid/examples/<id>/routines.py, and only without them its servo's model from the
    catalog) or picked models {instance: (type, model id)}."""
    config = config or CalibrationConfig()
    if isinstance(twin_or_picked, Mapping):
        return _plan_catalog(twin_or_picked, config)
    twin = twin_or_picked
    runner = getattr(twin, "runner", None)
    if runner is not None and hasattr(runner, "rig"):
        return _plan_rig(twin, config)
    shipped = runner.schedule() if callable(getattr(runner, "schedule", None)) else None
    if shipped is not None:
        # WHY the routines the tracer plays and never the catalog's stand-ins (gap F, 2026-11-17): calibrate() plays this plan, so every
        # step shown must be one that runs here
        return _plan_rig(twin, config, shipped)
    if runner is not None and hasattr(runner, "typed"):
        servo = runner.typed()
        return _plan_catalog({servo.id: (servo.type, twin.model)}, config, twin=twin.description.id)
    raise TypeError(f"plan() takes a RobotTwin or picked models {{instance: (type, model id)}}, not {type(twin_or_picked).__name__}")


generate_schedule = plan  # Zach's name (Daily Note 2026-11-17: ".generate_schedule() -> CalibrationSchedule"); plan() stays
