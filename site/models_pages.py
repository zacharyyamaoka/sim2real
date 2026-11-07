"""The models by entity type, the calibration routines both ways, and the parameters view (type_cards/CONTRACT.md, "Domain model v3").

Zach (PROJECT - Sim2Real, 2026-11-06): "a MODEL is associated with a type ... We organize all of the models related to a particular part type
into a ladder. of icnreasing paramters basically" (his table: rung, model, parameters, adds, identified here) "... the 6 DOF robot arm is not a
type.. the type here is more generic ... MO.kinematics.X MO.dynamics.X"; "lets call it CALIBRATION ROUTINE or just ROUTINE ... a table of
calibration routines in the first column and then the parameters that they identify. Another way to see it is with the parameters in the
first column and all the ROUTINES that can idneity it"; "in the parameter view. lets use DATA-UI ... all of the paramteres ... only of the
parmaters for the Winning model(s) ... all of the paramters that had at least some model run and rpocuded datata ... each model if you
display mutliple at the same time should get its own Recovered error toerlance colum ... under a subheader of the model ... For compactness
... just so the error so its easy to compare. And you can color the models by row based on what has the lowest error ... filter what model
results we are showing".

What a page reads, never a new number:
- the type level, type_cards/domain.py (dm): every generic type, its models in ladder order by family, their parameters and adds;
- data/domain/parameters.json (the contract's parameters table): what was identified where (identified here) and the parameters view's rows;
- data/domain/deployments.json and the oracle's results: which models each virtual deployment's fit holds (deployments_pages.fitted, the
  deployments pages' own rule); data/domain/model_labels.json and run_gates.json: which ladder model each producer's model is and how many of
  a station's runs it replayed (a physical deployment);
- reg.ROUTINES and sysid/results/calibration_routines.json: each routine's setting, time, cost, equipment, what it identifies (dm.routine_
  parameters, the contract's routine -> parameters) and its recovery at every level of the noise ladder (0x, 1x, 3x, 10x: the worst error
  over tolerance, the verdict, what was not recovered or not run and why); dm.parameter_routines() the other direction.
The parameters view's cells are the contract's values; the only arithmetic here is a display unit (mrad for rad, mm for m, the same per row,
so a row's errors compare in one unit) and the oracle's own error (recovered - true).

Writes (site/build.py): models/index.html, models/<type>/index.html, routines/index.html, parameters/index.html, views/routines.base,
views/parameter-routines.base, views/parameters.base, data/routines.json, data/parameter-routines.json, data/parameters-view.json.
Decision record: docs/decision-models-routines-parameters-2026-11-07.md. Stdlib only.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter

from catalog_workbench.data_ui import views_element
from catalog_workbench.html import breadcrumb, e, plural

import adapter
import deployments_pages as dp
import landing
import pages
import ui_shared
from type_cards import domain as dm  # noqa: E402  (deployments_pages put the repo on sys.path)
from type_cards import instances as inst  # noqa: E402
from type_cards import registry as reg  # noqa: E402

MODELS_URL = "/models/"
ROUTINES_URL = "/routines/"
PARAMETERS_URL = "/parameters/"
PARAMS_ID = "parameters-views"
ROUTINES_BASE = "views/routines.base"
PARAM_ROUTINES_BASE = "views/parameter-routines.base"
PARAMS_BASE = "views/parameters.base"
STYLES = ui_shared.head() + '<link rel="stylesheet" href="/static/models.css">\n'
KIND_WORD = {"physics": "physics", "residual": "grey-box residual", "learned": "black-box net"}
FAMILY_TITLE = {"kinematics": "Kinematics", "dynamics": "Dynamics", "measurement": "Measurement"}
# a display unit and its factor (Zach's own table, 2026-11-06: "4.200 mrad"): landing.display's rule, decided once per row so every error of
# a row is in one unit and compares; the site test converts back with its own copy of this table
DISPLAY = {("rad", "mrad"): 1e3, ("m", "mm"): 1e3, ("rad/h", "mrad/h"): 1e3}
SETTING_WORD = {"bench": "bench", "deployed": "deployed", "both": "bench or deployed"}
# the noise ladder's levels (sysid/noise_ladder.json), each in words; the routine table shows every one (the v3 audit, finding 5)
LEVEL_WORDS = {"0x": "with no sensor noise", "1x": "at the oracle's own sensor noise", "3x": "at three times it", "10x": "at ten times it"}


def model_url(type_id: str, model_id: str | None = None) -> str:
    return f"{MODELS_URL}{type_id}/" + (f"#{model_id}" if model_id else "")


def rung(m: dm.Model) -> str:
    """M<k>, and .wear on a wear model (Zach's own column: "M3.wear"); read from the model's fields, never its id."""
    return f"M{m.k}" + (".wear" if m.wear else "")


# --- what the pages read, once per build -------------------------------------------------------------------------------------------

class Data:
    def __init__(self, site):
        self.site = site
        self.domain = dp.load(site)
        folder = site.data / "domain"
        self.params = json.loads((folder / "parameters.json").read_text(encoding="utf-8"))
        path = folder / "model_labels.json"
        self.labels = {(r["deployment"], r["label"]): r for r in json.loads(path.read_text(encoding="utf-8"))["rows"]} if path.is_file() else {}
        path = site.data / "sysid" / "calibration_routines.json"
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        self.routines = {r["routine"]: r for r in doc.get("rows", [])}
        self.levels = list(doc.get("levels") or LEVEL_WORDS)
        self.used = self._used()

    def _replayed(self, dep: str) -> Counter:
        """{(device, the producer's label): runs it replayed} from RobotDx's stock.model_error rows (titled "<label> vs real")."""
        path = self.site.data / dep / "run_gates.json"
        out: Counter = Counter()
        if path.is_file():
            for r in json.loads(path.read_text(encoding="utf-8"))["rows"]:
                if r.get("diagnostic") == "stock.model_error":
                    out[(r["device"], dp.sel.model_label(r.get("title") or ""))] += 1
        return out

    def _used(self) -> dict:
        """{(type, model id): [(node, how, runs)]}: the oracle examples whose fit holds the model (its typed nodes, else the example; how is
        the deployments pages' basis, selected or fitted) and the stations whose runs a producer's model replayed (how is its label, by
        the label map; runs how many)."""
        d = self.domain
        out: dict = {}
        for ex, doc in d.results.items():
            for tid, (ids, basis, _rung) in dp.fitted(doc).items():
                typed = [n["id"] for n in d.nodes if n["root"] == ex and n["entity_type"] == tid] or [ex]
                for mid in ids:
                    have = out.setdefault((tid, mid), [])
                    have.extend(x for x in ((nid, basis, "") for nid in typed) if x not in have)
        for root in d.roots():
            if root["kind"] != "physical":
                continue
            stations = {n["device"]: n["id"] for n in d.tree(root["id"]) if n.get("structural") == "station"}
            for (device, label), n in sorted(self._replayed(root["id"]).items(), key=lambda kv: (kv[0][0], -kv[1], kv[0][1])):
                m = self.labels.get((root["id"], label))
                if m and device in stations:
                    out.setdefault((m["type"], m["model"]), []).append((stations[device], label, str(n)))
        return out

    def identified(self, tid: str, mid: str) -> list[dict]:
        """The graded values of the parameters a model adds (Zach's "identified here"): the contract's rows of its type whose parameter is
        introduced by the model and that some routine produced a value for."""
        return [r for r in self.params["rows"] if r["entity_type"] == tid and r["introduced_in"] == mid and r["has_results"]]


def load(site) -> Data:
    cached = getattr(site, "_models_pages", None)
    if cached is None:
        cached = site._models_pages = Data(site)
    return cached


# --- the models: an index and a page per generic type --------------------------------------------------------------------------------

def index_body(d: Data) -> str:
    rows = []
    for tid in dm.TYPE_ORDER:
        t = dm.TYPES[tid]
        current = " · ".join(f"<code>{e(m.id)}</code>" for m in dm.current_models(tid))
        used = {node.split("/")[0] for m in t.models for node, _h, _r in d.used.get((tid, m.id), [])}
        rows.append(f'<tr data-row-type="{e(tid)}"><th scope="row"><span class="s2r-ei">{ui_shared.icon(tid)}</span> '
                    f'<a data-type="{e(tid)}" href="{e(model_url(tid))}">{e(t.title)}</a><br><small class="mut">{e(t.covers)}</small></th>'
                    f'<td class="s2r-nw">{e(t.group)}</td><td>{e(" · ".join(FAMILY_TITLE[f] for f in t.families))}</td><td>{len(t.models)}</td>'
                    f'<td>{current}</td><td>{len(t.parameters)}</td><td>{plural(len(used), "deployment") if used else "—"}</td></tr>')
    table = ('<div class="s2r-scroll"><table class="s2r-table s2r-mtypes"><thead><tr><th scope="col">Type</th><th scope="col">Group</th>'
             '<th scope="col">Families</th><th scope="col">Models</th><th scope="col">Today\'s model</th><th scope="col">Parameters</th>'
             f'<th scope="col">Used on</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return f"""<article class="s2r-models" data-page="models">
<h1>Models <span class="n">({len(dm.TYPE_ORDER)} types)</span></h1>
<p class="lede">Every model belongs to a generic type, never an instance: a UR5e is a rigid body chain, CAN 11 an integrated servo. Each type
orders its models into a ladder of increasing parameters, one ladder per family ({e(", ".join(f"{FAMILY_TITLE[f].lower()}: {w}" for f, w in dm.FAMILIES.items()))}),
so a family is usable without the others. M6 is always the grey-box residual and M7 the black-box net. Open a type for its ladder, what has
been identified at each model and where each model is used. The routines that identify the parameters are on <a href="{ROUTINES_URL}">Routines</a>,
every value on <a href="{PARAMETERS_URL}">Parameters</a>.</p>
{table}
</article>"""


def identified_cell(d: Data, rows: list[dict]) -> str:
    if not rows:
        return '<span class="mut">—</span>'
    by_dep: dict = {}
    for r in rows:
        by_dep.setdefault(r["deployment"], []).append(r)
    parts = []
    for dep, mine in by_dep.items():
        node = d.domain.by_id.get(dep)
        keys = ", ".join(f'<span data-key="{e(r["id"])}">{e(r["key"] or r["parameter"])}</span>' for r in mine)
        parts.append(f'<div class="s2r-idf"><a href="{e(dp.node_url(dep))}">{e(node["title"] if node else dep)}</a>: <span class="s2r-adds">{keys}</span></div>')
    return "".join(parts)


def used_cell(d: Data, uses: list[tuple]) -> str:
    """Where a model is used: per deployment, its nodes (an oracle fit says selected or fitted; a station each producer label that replayed
    its runs, with the count)."""
    if not uses:
        return '<span class="mut">—</span>'
    by_root: dict = {}
    for node, how, runs in uses:
        by_root.setdefault(d.domain.by_id[node]["root"] if node in d.domain.by_id else node, []).append((node, how, runs))
    out = []
    for root, items in by_root.items():
        rnode = d.domain.by_id.get(root)
        head = f'<a href="{e(dp.node_url(root))}"><b>{e(rnode["title"] if rnode else root)}</b></a>'
        if rnode and rnode["kind"] == "physical":
            per: dict = {}
            for node, how, runs in items:
                per.setdefault(node, []).append((how, runs))
            bits = []
            for node, hows in per.items():
                n = d.domain.by_id[node]
                labels = ", ".join(f'<a href="{e(dp.node_url(node))}" data-node="{e(node)}" data-how="{e(how)}" data-runs="{e(runs)}">{e(how)}</a>'
                                   f' <small class="mut">{int(runs):,}</small>' for how, runs in hows)
                bits.append(f'<span class="s2r-use">{e(dp.label_of(n))}: {labels}</span>')
            # WHY a line per station: a station's labels read together, and the next station starts a line of its own
            out.append(f'<div class="s2r-used">{head} <small class="mut">replayed its runs</small>{"".join(f"<br>{b}" for b in bits)}</div>')
        else:
            basis = sorted({how for _n, how, _r in items})
            word = " and ".join("the selection rule's pick" if b == "selected" else "its fit" for b in basis)
            if [n for n, _h, _r in items] == [root]:  # the example itself holds the model (no node of the type in its tree)
                head = (f'<a href="{e(dp.node_url(root))}" data-node="{e(root)}" data-how="{e(items[0][1])}" data-runs="">'
                        f'<b>{e(rnode["title"] if rnode else root)}</b></a>')
                out.append(f'<div class="s2r-used">{head} <small class="mut">{e(word)}</small></div>')
                continue
            nodes = ", ".join(f'<a href="{e(dp.node_url(node))}" data-node="{e(node)}" data-how="{e(how)}" data-runs="">'
                              f'{e(d.domain.by_id[node]["title"] if node in d.domain.by_id else node)}</a>' for node, how, _r in items)
            out.append(f'<div class="s2r-used">{head} <small class="mut">{e(word)}</small><br><span class="s2r-use">{nodes}</span></div>')
    return "".join(out)


def ladder_section(d: Data, tid: str, family: str) -> str:
    t = dm.TYPES[tid]
    rows = []
    for m in (x for x in t.models if x.family == family):
        current = ' <span class="s2r-v s2r-pass">today\'s model</span>' if m.current else ""
        kind = "" if m.kind == "physics" else f' <span class="s2r-chip">{e(KIND_WORD[m.kind])}</span>'
        size = f"{m.n_parameters:,}" + (f' <small class="mut">({len(m.parameters)} named + {m.architecture.weights:,} weights)</small>' if m.architecture and m.parameters
                                        else ' <small class="mut">weights</small>' if m.architecture else "")
        adds = (f'<span class="s2r-adds">{e(", ".join(m.adds))}</span>' if m.adds else
                f'<span class="mut">a net on {e(m.base)}</span>' if m.kind == "residual" else
                '<span class="mut">a net, no named parameter</span>' if m.kind == "learned" else
                f'<span class="mut">wear on {e(m.base)}</span>' if m.wear else '<span class="mut">—</span>')
        eq = f'<br><small class="s2r-eq">{e(m.equation)}</small>' if m.equation else ""
        rows.append(f'<tr id="{e(m.id)}" data-model="{e(m.id)}" data-k="{m.k}" data-family="{e(m.family)}" data-n="{m.n_parameters}" '
                    f'data-current="{str(m.current).lower()}" data-kind="{e(m.kind)}" data-adds="{e(" ".join(m.adds))}">'
                    f'<th scope="row" data-col="rung">{e(rung(m))}</th>'
                    f'<td data-col="model"><b>{e(m.title)}</b>{current}{kind}<br><code class="mut">{e(m.id)}</code>{eq}</td>'
                    f'<td data-col="parameters">{size}</td><td data-col="adds">{adds}</td>'
                    f'<td data-col="identified">{identified_cell(d, d.identified(tid, m.id))}</td>'
                    f'<td data-col="used">{used_cell(d, d.used.get((tid, m.id), []))}</td></tr>')
    return (f'<section id="family-{e(family)}" data-family="{e(family)}" aria-labelledby="fam-{e(family)}-h">'
            f'<h2 id="fam-{e(family)}-h">{e(FAMILY_TITLE[family])} <span class="n">· M&lt;k&gt;.{e(family)}.*</span></h2>'
            f'<p class="mut">{e(dm.FAMILIES[family][0].upper() + dm.FAMILIES[family][1:])}.</p>'
            '<div class="s2r-scroll"><table class="s2r-table s2r-ladder"><thead><tr><th scope="col">rung</th><th scope="col">model</th>'
            '<th scope="col">parameters</th><th scope="col">adds</th><th scope="col">identified here</th><th scope="col">used on</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>')


def type_body(d: Data, tid: str) -> str:
    t = dm.TYPES[tid]
    members = ", ".join(f'{p.count} × <a href="{e(model_url(p.type))}">{e(dm.TYPES[p.type].title)}</a> <small class="mut">({e(p.role)})</small>'
                        if p.type in dm.TYPES else f"{p.count} × {e(p.type)} <small class=\"mut\">({e(p.role)})</small>" for p in t.members)
    part_of = [o for o in dm.TYPES.values() if any(p.type == tid for p in o.members) and o.id != tid]
    cards = " · ".join(f'<a href="/types/{e(c)}/">{e(reg.CARDS[c].title)}</a>' for c in t.legacy_cards)
    routines = sorted({rid for per in dm.parameter_routines()[tid].values() for rid in per})
    lines = [f'<p><b>Made of:</b> {members}.</p>' if members else "",
             f'<p><b>Part of:</b> {", ".join(pages.a(model_url(o.id), o.title) for o in part_of)}.</p>' if part_of else "",
             f'<p class="s2r-else">Its parameters: {pages.a(PARAMETERS_URL + "?entity_type=" + tid, f"{len(t.parameters)} on Parameters")} · the routines that '
             f'identify them: {pages.a(ROUTINES_URL + "#by-parameter", plural(len(routines), "routine"))} · the v2 type card: {cards}</p>']
    fams = "".join(ladder_section(d, tid, f) for f in t.families)
    return f"""<article class="s2r-modelpage" data-type="{e(tid)}">
<h1><span class="s2r-ei s2r-ei-lg">{ui_shared.icon(tid)}</span> {e(t.title)}</h1>
<p class="sub">{e(t.group.title())} · Zach's word: {e(t.zach)} · {e(" · ".join(FAMILY_TITLE[f] for f in t.families))}</p>
<p class="lede">{e(t.covers[0].upper() + t.covers[1:])}. Its models, lowest first in each family: each holds every parameter of the one below it
in its family and adds its own. <b>Identified here</b> is every value a routine recovered of a parameter the model adds; <b>used on</b>, where
the model runs: an oracle example whose fit or selection holds it, a station whose runs a producer's model replayed (the producer's own words,
mapped to the ladder by type_cards).</p>
{"".join(lines)}
{fams}
</article>"""


# --- the routines, both ways --------------------------------------------------------------------------------------------------------

def _seconds(q) -> str:
    s = float(q.value)
    if s == 0:
        return "0 s"
    if s < 1:
        return f"{s * 1000:.3g} ms"
    if s < 90:
        return f"{s:.3g} s"
    if s < 5400:
        return f"{s / 60:.3g} min"
    return f"{s / 3600:.3g} h"


def _quantity(q, text: str) -> dict:
    """A routine's number as data-ui's rich cell: its value, the words shown, and an estimate marked as one (CONTRACT §22 basis)."""
    cell = {"value": q.value, "text": text, "note": (q.source + (f"; {q.note}" if q.note else "")).strip("; ")}
    if q.source == reg.ESTIMATE:
        cell["basis"] = "estimate"
    return cell


def level_cells(cell: dict | None, level: str) -> dict:
    """A routine's recovery at one level of the noise ladder as its table shows it (the producer's numbers, calibration_routines.json):
    recovery_<L>, the worst |error| / tolerance with what was not recovered in its words; state_<L>, the verdict as a status (pass, fail,
    or not run where no check ran there, the ruler's reason beside it); pass_<L>, pass as the ladder wrote it. A routine nobody checked
    against a hidden truth has none (its Oracle column says so)."""
    if cell is None:
        return {f"recovery_{level}": None, f"state_{level}": None, f"pass_{level}": None}
    where = LEVEL_WORDS.get(level, level)
    skipped = "; ".join(f"{cid.split(':', 1)[1]}: {why}" for cid, why in (cell.get("not_run") or {}).items())
    if not cell.get("checks"):
        why = f"not run {where}: {skipped}"
        return {f"recovery_{level}": {"value": None, "text": "not run", "why": why},
                f"state_{level}": {"value": "not run", "note": why}, f"pass_{level}": None}
    worst, missing, n = cell.get("worst_error_over_tolerance"), cell.get("missing") or 0, cell.get("parameters") or 0
    lost = f"{missing} of {n} not recovered" if missing else ""
    text = " · ".join(x for x in (f"{worst:.3g}×" if worst is not None else "", lost) if x) or "—"
    detail = [f"the worst |recovered − true| ÷ tolerance {where}, over the {n - missing} of {n} parameters it recovered" if worst is not None
              else f"nothing recovered {where}", lost, f"{cell.get('failing') or 0} of {n} outside the ladder's bound" if cell.get("failing") else "",
              "" if cell.get("usable") or not cell.get("pass") else "within the ladder's bound, not within the tolerance itself",
              f"not run there: {skipped}" if skipped else ""]
    note = "; ".join(x for x in detail if x)
    return {f"recovery_{level}": {"value": worst, "text": text, "note": note} if worst is not None else {"value": None, "text": text, "why": note},
            f"state_{level}": {"value": "pass" if cell.get("pass") else "fail", "note": note}, f"pass_{level}": cell.get("pass")}


def routine_rows(d: Data) -> list[dict]:
    rows = []
    for r in reg.ROUTINES:
        cost = reg.equipment_cost(r)
        rec = (d.routines.get(r.id) or {}).get("recovery") or {}
        ident = [f"{t} · {p}" for t, _m, p in dm.routine_parameters(r.id)]
        levels = {}
        for level in d.levels:
            levels.update(level_cells(rec.get(level) if rec else None, level))
        rows.append({"id": r.id, "title": r.title, "package": r.package, "kind": r.kind, "setting": r.setting, "status": r.status,
                     "wall_time_s": _quantity(r.wall_time, _seconds(r.wall_time)),
                     "operator_time_s": _quantity(r.operator_time, _seconds(r.operator_time)),
                     "cost_usd": _quantity(cost, f"${cost.value:,.0f}"), "equipment": [reg.EQUIPMENT[x].title for x in r.equipment],
                     "identifies": ident, "n_parameters": len(ident), **levels,
                     "oracle": (d.routines.get(r.id) or {}).get("oracle", {}).get("status") or "not checked"})
    return rows


def parameter_routine_rows() -> list[dict]:
    by_id = {r.id: r for r in reg.ROUTINES}
    rows = []
    for tid, per in dm.parameter_routines().items():
        for name, ids in per.items():
            spec = dm.parameter(tid, name)
            rows.append({"id": f"{tid}/{name}", "parameter": name, "type": tid, "type_title": dm.TYPES[tid].title, "family": spec.family,
                         "introduced_in": spec.introduced_in, "unit": spec.unit, "routines": [by_id[i].title for i in ids], "routine_ids": list(ids),
                         "n_routines": len(ids), "where": sorted({SETTING_WORD[by_id[i].setting] for i in ids}),
                         "status": sorted({by_id[i].status for i in ids})})
    return rows


def routines_dataset(d: Data) -> dict:
    return {"id": "routines", "title": "Calibration routines", "titleProperty": "title",
            "source": "site/models_pages.py over type_cards (reg.ROUTINES, dm.routine_parameters) and sysid/results/calibration_routines.json",
            "properties": {"title": {"type": "text", "label": "Routine"}, "package": {"type": "text", "label": "Package"},
                           "kind": {"type": "text", "label": "Kind", "note": "identify: finds parameters; measure: a gauge; use: identifies nothing"},
                           "setting": {"type": "text", "label": "Runs", "note": "where it runs: " + ", ".join(reg.ROUTINE_SETTINGS)},
                           "status": {"type": "text", "label": "Status", "note": "its code: " + ", ".join(reg.ROUTINE_STATUS)},
                           "wall_time_s": {"type": "number", "label": "Time", "note": "the whole routine, set-up included (an estimate is marked)"},
                           "operator_time_s": {"type": "number", "label": "Hands-on", "note": "a person's share of the time"},
                           "cost_usd": {"type": "number", "label": "Equipment $", "note": "the equipment's cost beyond the robot, in USD"},
                           "equipment": {"type": "list", "label": "Equipment"}, "identifies": {"type": "list", "label": "Identifies (type · parameter)"},
                           "n_parameters": {"type": "number", "label": "Parameters"},
                           **{k: v for level in d.levels for k, v in level_properties(level).items()},
                           "oracle": {"type": "text", "label": "Oracle"}},
            "rows": routine_rows(d)}


def level_properties(level: str) -> dict:
    where = LEVEL_WORDS.get(level, level)
    # WHY "error/tol" and "verdict": they sit under their level's header ("Recovery at 1x"), in a column 78 px wide
    return {f"recovery_{level}": {"type": "number", "label": "error/tol",
                                  "note": f"the worst |recovered − true| ÷ tolerance over its parameters {where} (sysid's noise ladder; 1 is at the "
                                          "tolerance); empty: not checked against a hidden truth"},
            f"state_{level}": {"type": "text", "label": "verdict", "display": "status",
                               "note": f"its verdict {where}: pass (every parameter within the ladder's bound), fail (one is not, or was not "
                                       "recovered) or not run (no check ran there, and why)"},
            f"pass_{level}": {"type": "boolean", "label": f"{level} ok"}}


def parameter_routines_dataset() -> dict:
    return {"id": "parameter-routines", "title": "Every parameter and the routines that can identify it", "titleProperty": "parameter",
            "source": "site/models_pages.py over type_cards (dm.parameter_routines: the contract's parameter -> routines)",
            "properties": {"parameter": {"type": "text", "label": "Parameter"}, "type": {"type": "text", "label": "Type id"},
                           "type_title": {"type": "text", "label": "Type"}, "family": {"type": "text", "label": "Family"},
                           "introduced_in": {"type": "text", "label": "Enters at"}, "unit": {"type": "text", "label": "Unit"},
                           "routines": {"type": "list", "label": "Routines that can identify it"}, "routine_ids": {"type": "list", "label": "Routine ids"},
                           "n_routines": {"type": "number", "label": "Routines"}, "where": {"type": "list", "label": "Where"},
                           "status": {"type": "list", "label": "Their status"}},
            "rows": parameter_routine_rows()}


def routines_base_properties(levels) -> dict:
    return {f"recovery_{level}": {"digits": 3} for level in levels}


def routines_base(levels=tuple(LEVEL_WORDS)) -> dict:
    # WHY this order (Zach's list: where it runs, its time, its $ cost, its equipment, its recovery, its status): the short answers first, the
    # long lists (equipment, what it identifies) after them. WHY every level, each its recovery and verdict under one header (the v3 audit,
    # 2026-11-07, finding 5): 1x and 3x alone hid 0x's bias and 10x's breakdown, and a level a check skips
    by_level = [x for level in levels for x in (f"recovery_{level}", f"state_{level}")]
    order = ["title", "setting", "status", "wall_time_s", "cost_usd", *by_level, "equipment", "operator_time_s", "identifies", "n_parameters", "kind", "package"]
    groups = {f"Recovery at {level}": [f"recovery_{level}", f"state_{level}"] for level in levels}
    return {"data": "/data/routines.json", "properties": routines_base_properties(levels),
            "views": [{"type": "table", "name": "Routine → parameters", "order": order, "columnGroups": groups,
                       # WHY these widths: at 1280 px the four levels' verdicts sit beside the routine without a sideways scroll; a cell
                       # cut short ends in an ellipsis and its whole text (what was not recovered, what did not run and why) is its hover
                       "columnSize": {"title": 184, "setting": 76, "status": 130, "wall_time_s": 106, "cost_usd": 92, "equipment": 220, "identifies": 360,
                                      **{f"recovery_{level}": 78 for level in levels},
                                      **{f"state_{level}": 78 for level in levels}}}]}


def parameter_routines_base() -> dict:
    order = ["parameter", "type_title", "routines", "n_routines", "where", "status", "introduced_in", "family", "unit"]
    return {"data": "/data/parameter-routines.json",
            "views": [{"type": "table", "name": "Parameter → routines", "order": order, "columnSize": {"parameter": 240, "routines": 420}}]}


def routines_body(d: Data) -> str:
    rrows = routine_rows(d)
    prows = parameter_routine_rows()
    fall_r = "".join(f'<tr data-routine="{e(r["id"])}"><th scope="row">{e(r["title"])}</th><td>{e(SETTING_WORD[r["setting"]])}</td>'
                     f'<td>{e(r["wall_time_s"]["text"])}</td><td>{e(r["cost_usd"]["text"])}</td><td>{e(", ".join(r["identifies"]) or "—")}</td>'
                     f'<td>{e(r["status"])}</td></tr>' for r in rrows)
    fall_p = "".join(f'<tr data-parameter="{e(r["id"])}"><th scope="row">{e(r["parameter"])}</th><td>{e(r["type_title"])}</td>'
                     f'<td>{e(", ".join(r["routines"]) or "none yet")}</td></tr>' for r in prows)
    t_r = (f'<table class="s2r-table"><thead><tr><th>Routine</th><th>Runs</th><th>Time</th><th>Equipment $</th><th>Identifies</th><th>Status</th></tr></thead>'
           f'<tbody>{fall_r}</tbody></table>')
    t_p = f'<table class="s2r-table"><thead><tr><th>Parameter</th><th>Type</th><th>Routines</th></tr></thead><tbody>{fall_p}</tbody></table>'
    none = sum(1 for r in prows if not r["routine_ids"])
    checked = sum(1 for r in rrows if any(r.get(f"state_{level}") for level in d.levels))
    return f"""<article class="s2r-routines" data-page="routines">
<h1>Calibration routines <span class="n">({len(rrows)})</span></h1>
<p class="lede">A routine is one way to identify parameters: where it runs (on the bench or in a deployment), how long it takes and how much of a
person, what its equipment costs, and how well it recovers a hidden truth in simulation (sysid's noise ladder, at each level of sensor noise:
{e(", ".join(f"{level} {LEVEL_WORDS.get(level, '')}" for level in d.levels))}): the worst error over tolerance among its parameters and the
verdict, fail where a parameter falls outside the ladder's bound or is not recovered, not run where no check ran at that level (each cell says
why). {checked} of {len(rrows)} are checked against a hidden truth; {none} of {len(prows)} parameters have no routine yet. Two ways in: a routine
and what it identifies, or a parameter and every routine that can identify it.</p>
<nav class="tabs" aria-label="Routines, both ways"><div role="tablist" aria-label="Routines, both ways"><a role="tab" id="t-by-routine" href="#by-routine" aria-controls="tab-by-routine">Routine → parameters</a><a role="tab" id="t-by-parameter" href="#by-parameter" aria-controls="tab-by-parameter">Parameter → routines</a></div></nav>
<div class="panels">
<div class="panel" role="tabpanel" id="tab-by-routine" data-tab="by-routine" aria-label="Routine → parameters">
{views_element("routines-by-routine", "/" + ROUTINES_BASE, "Routine → parameters", t_r, frame="page", attrs='toolbar="bar"')}
</div>
<div class="panel" role="tabpanel" id="tab-by-parameter" data-tab="by-parameter" aria-label="Parameter → routines">
{views_element("routines-by-parameter", "/" + PARAM_ROUTINES_BASE, "Parameter → routines", t_p, frame="page", attrs='toolbar="bar"')}
</div>
</div>
</article>"""


# --- the parameters view (data-ui) -----------------------------------------------------------------------------------------------

def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def display_unit(row: dict, cols: list[dict]) -> tuple[str, float]:
    """The row's display unit and factor, from its first stated value (true, nominal, the oracle's fit, else a model's), by landing's rule;
    one per row, so every value of a row is in the same unit."""
    ref = next((v for v in [row.get("true"), row.get("nominal"), row.get("recovered")] + [row.get(f"recovered@{c['id']}") for c in cols]
                if isinstance(v, (int, float))), None)
    unit = row.get("unit") or ""
    if ref is None:
        return unit, 1.0
    shown = landing.display(ref, unit)[1]
    return (shown, DISPLAY[(unit, shown)]) if (unit, shown) in DISPLAY else (unit, 1.0)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _val(v, unit: str, f: float, **extra) -> dict | None:
    return {"value": v * f, "unit": unit, **extra} if _num(v) else None


def tolerance_cell(kind, value, unit: str, f: float, raw_unit: str) -> dict | None:
    if not _num(value):
        return None
    if kind == "rel":
        return {"value": value * 100, "text": f"± {landing.num(100 * value, 3)} %"}
    return {"value": value * f, "text": f"± {landing.num(value * f, 3)} {unit}".rstrip(), "unit": unit}


def column_label(c: dict) -> str:
    return f"{c['model']} · {reg.routine(c['routine']).title}"


def parameters_dataset(d: Data) -> dict:
    cols = d.params["result_columns"]
    keys = {c["id"]: slug(c["id"]) for c in cols}
    if len(set(keys.values())) != len(keys):
        raise ValueError("two result columns share a slug: give them distinct ids")
    nodes = d.domain.by_id
    props = {"name": {"type": "text", "label": "Parameter"}, "deployment": {"type": "text", "label": "Deployment"},
             "node": {"type": "text", "label": "Part"}, "entity_type": {"type": "text", "label": "Type"}, "parameter": {"type": "text", "label": "Name on the type"},
             "family": {"type": "text", "label": "Family"}, "introduced_in": {"type": "text", "label": "Enters at"}, "unit": {"type": "text", "label": "Unit"},
             "true": {"type": "number", "label": "True (hidden)", "note": "the value the oracle hid (a virtual deployment's only)"},
             "nominal": {"type": "number", "label": "Nominal", "note": "the value the description gives, where the fit starts"},
             "winning": {"type": "boolean", "label": "Winning model", "note": "a parameter of the selection rule's pick where the example ran one, else of the type's current model"},
             "has_results": {"type": "boolean", "label": "Has a result"},
             "models": {"type": "list", "label": "Models with a result", "note": "the (routine, model) column groups that hold a value in this row"},
             "fit_rec": {"type": "number", "label": "Recovered [95 %]"}, "fit_err": {"type": "number", "label": "Error"},
             "fit_tol": {"type": "number", "label": "Tolerance"}, "fit_ok": {"type": "text", "label": "✓", "display": "status"}}
    for c in cols:
        s = keys[c["id"]]
        props[f"rec__{s}"] = {"type": "number", "label": "Recovered [95 %]", "column": c["id"], "part": "recovered"}
        props[f"err__{s}"] = {"type": "number", "label": "Error", "column": c["id"], "part": "error"}
        props[f"tol__{s}"] = {"type": "number", "label": "Tolerance", "column": c["id"], "part": "tolerance"}
        props[f"ok__{s}"] = {"type": "text", "label": "✓", "display": "status", "column": c["id"], "part": "ok"}
    rows = []
    for r in d.params["rows"]:
        unit, f = display_unit(r, cols)
        node = nodes.get(r["node"])
        name = r["key"] or (f"{dp.label_of(node)} · {r['parameter']}" if node else r["id"])
        err = r["recovered"] - r["true"] if _num(r.get("recovered")) and _num(r.get("true")) else None
        out = {"id": r["id"], "name": name, "deployment": r["deployment"], "node": dp.label_of(node) if node else r["node"],
               "entity_type": dm.TYPES[r["entity_type"]].title, "parameter": r["parameter"], "family": r["family"], "introduced_in": r["introduced_in"],
               "unit": unit, "true": _val(r.get("true"), unit, f), "nominal": _val(r.get("nominal"), unit, f), "winning": r["winning"],
               "has_results": r["has_results"],
               "models": [column_label(c) for c in cols if r.get(f"recovered@{c['id']}") is not None or r.get(f"error@{c['id']}") is not None],
               "fit_rec": _val(r.get("recovered"), unit, f, **({"low": r["ci95_lo"] * f, "high": r["ci95_hi"] * f} if _num(r.get("ci95_lo")) and _num(r.get("ci95_hi")) else {})),
               "fit_err": _val(err, unit, f), "fit_tol": tolerance_cell(r.get("tolerance_kind"), r.get("tolerance"), unit, f, r.get("unit")),
               "fit_ok": None if r.get("pass") is None else ("pass" if r["pass"] else "fail")}
        for c in cols:
            s, cid = keys[c["id"]], c["id"]
            lo, hi = r.get(f"ci95_lo@{cid}"), r.get(f"ci95_hi@{cid}")
            rng = {"low": lo * f, "high": hi * f} if _num(lo) and _num(hi) else {}
            note = r.get(f"interval@{cid}")
            out[f"rec__{s}"] = _val(r.get(f"recovered@{cid}"), unit, f, **rng, **({"note": f"95 % interval: {note}"} if note else {}))
            out[f"err__{s}"] = _val(r.get(f"error@{cid}"), unit, f)
            out[f"tol__{s}"] = tolerance_cell(r.get("tolerance_kind"), r.get(f"tolerance@{cid}"), unit, f, r.get("unit")) if r.get(f"error@{cid}") is not None or r.get(f"recovered@{cid}") is not None else None
            within = r.get(f"within@{cid}")
            out[f"ok__{s}"] = None if within is None else ("pass" if within else "fail")
        rows.append(out)
    return {"id": "parameters", "title": "Every parameter: true, nominal and recovered per model", "titleProperty": "name",
            "source": "site/models_pages.py over data/domain/parameters.json (type_cards/instances.py parameter_table): the contract's rows, values in one "
                      "display unit per row", "properties": props, "rows": rows}


def parameters_base(d: Data) -> dict:
    cols = d.params["result_columns"]
    keys = {c["id"]: slug(c["id"]) for c in cols}
    # WHY the values right after the name (Zach's table: true, nominal, recovered [95 %], error, tolerance): the type and the model a parameter
    # enters at follow them, and the family is the rail's
    base = ["name", "deployment"]
    after = ["entity_type", "introduced_in"]
    fit = ["fit_rec", "fit_err", "fit_tol", "fit_ok"]
    # WHY a typographic apostrophe: the .base writer emits a plain key with a straight one that its own reader takes for a quote (found here)
    fit_group = {"Oracle fit (the example’s own)": fit}
    groups = {column_label(c): [f"{p}__{keys[c['id']]}" for p in ("rec", "err", "tol", "ok")] for c in cols}
    errs = [f"err__{keys[c['id']]}" for c in cols]
    # WHY 250 px for recovered: its 95 % interval is drawn beside the value (data-ui's range slot) and a narrower column clips it away
    size = {"name": 240, "deployment": 120, "entity_type": 130, "introduced_in": 190, "fit_rec": 250, "fit_err": 130, "fit_tol": 130,
            **{f"rec__{keys[c['id']]}": 250 for c in cols}, **{f"err__{keys[c['id']]}": 130 for c in cols}, **{f"tol__{keys[c['id']]}": 130 for c in cols}}
    # WHY declared digits (data-ui §17 addendum): the stored numbers are exact (4.6611971558188605); a person reads 4 significant figures,
    # as Zach's own table did ("4.205 mrad"), and the exact value stays one hover away
    numbers = ["true", "nominal", "fit_rec", "fit_err"] + [f"{p}__{keys[c['id']]}" for c in cols for p in ("rec", "err")]
    # WHY range declared: the kit sizes a column's interval slot from the view's display, so a recovered value's [95 %] is only drawn
    # beside it when the view says range (the cell alone would pick range, in a slot of no width)
    ranges = {"fit_rec": "range", **{f"rec__{keys[c['id']]}": "range" for c in cols}}
    return {
        "data": f"/data/{DATA_FILE}",
        "properties": {pid: {"digits": 4} for pid in numbers},
        "facets": [{"as": "current", "label": "Your filters"},
                   {"property": "deployment", "label": "Deployment"}, {"property": "entity_type", "label": "Type"},
                   {"property": "family", "label": "Family"}, {"property": "models", "label": "Models with a result",
                                                               "info": "a (routine, model) column group: keeps the rows it graded; With results then draws its group and every other model that graded them"},
                   {"property": "winning", "label": "Winning model"}, {"property": "has_results", "label": "Has a result"}],
        "views": [
            {"type": "table", "name": "All parameters", "units": "inline", "display": ranges, "order": base + ["true", "nominal"] + fit + after, "columnGroups": fit_group, "columnSize": size},
            {"type": "table", "name": "Winning model", "units": "inline", "display": ranges, "filters": "winning == true", "order": base + ["true", "nominal"] + fit + after,
             "columnGroups": fit_group, "columnSize": size},
            {"type": "table", "name": "With results", "units": "inline", "display": ranges, "filters": "has_results == true", "order": base + ["true", "nominal"] + [x for ids in groups.values() for x in ids],
             "columnGroups": groups, "emptyGroups": "hide", "columnSize": size},
            {"type": "table", "name": "Errors only", "units": "inline", "filters": "has_results == true", "order": ["name", "deployment", "true"] + errs,
             "columnGroups": {column_label(c): [f"err__{keys[c['id']]}"] for c in cols}, "best": {"among": errs, "by": "absmin"},
             "emptyGroups": "hide", "columnSize": {"name": 240, "deployment": 120, **{e: 170 for e in errs}}},
        ],
    }


DATA_FILE = "parameters-view.json"


def parameters_body(d: Data) -> str:
    rows = d.params["rows"]
    n_res = sum(1 for r in rows if r["has_results"])
    n_win = sum(1 for r in rows if r["winning"])
    cols = d.params["result_columns"]
    fallback = ('<table class="s2r-table"><thead><tr><th>Parameter</th><th>Deployment</th><th>True</th><th>Recovered</th></tr></thead><tbody>'
                + "".join(f'<tr data-param-row="{e(r["id"])}"><th scope="row">{e(r["key"] or r["parameter"])}</th><td>{e(r["deployment"])}</td>'
                          f'<td>{e(landing.quantity(r["true"], r["unit"]) if r.get("true") is not None else "—")}</td>'
                          f'<td>{e(landing.quantity(r["recovered"], r["unit"]) if r.get("recovered") is not None else "—")}</td></tr>' for r in rows if r["has_results"])
                + "</tbody></table>")
    return f"""<div class="s2r-params" data-page="parameters">
<h1>Parameters <span class="n">({len(rows):,})</span></h1>
<p class="lede">Every parameter of every typed part of every deployment: its true value where an oracle hid one, its nominal, and what each
model recovered. A model's results are its own column group: recovered with its 95 % interval, the error, the tolerance and ✓ when the error is
within it. {plural(len(cols), "model")} (a routine and the model it fits) have results on {n_res:,} rows; {n_win:,} rows are parameters of a winning model.
Errors only puts every model's error side by side and marks each row's least. Pick a deployment, a type or a model on the left to compare the
models that graded those rows; Properties shows or hides a model's whole group.</p>
{views_element(PARAMS_ID, "/" + PARAMS_BASE, "Parameters", fallback, frame="page", attrs='toolbar="bar" promote="properties"')}
</div>"""


# --- the site's files --------------------------------------------------------------------------------------------------------------

def base_text(doc: dict, what: str) -> str:
    return dp.base_text(doc, what)


def write_data(data, site) -> dict:
    """data/routines.json, data/parameter-routines.json and data/parameters-view.json (site/build.py, beside the deployments' cards)."""
    d = load(site)
    docs = {"routines.json": routines_dataset(d), "parameter-routines.json": parameter_routines_dataset(), DATA_FILE: parameters_dataset(d)}
    for name, doc in docs.items():
        (data / name).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return {name: len(doc["rows"]) for name, doc in docs.items()}


def files(site):
    """(path, text) of the models index and a page per type, the routines page and the parameters page, with their .base files."""
    import catalog as s2r  # noqa: PLC0415

    d = load(site)
    root = [s2r.ROOT_CRUMB]
    yield ROUTINES_BASE, base_text(routines_base(d.levels), "the calibration routines, routine -> parameters")
    yield PARAM_ROUTINES_BASE, base_text(parameter_routines_base(), "every parameter and the routines that can identify it")
    yield PARAMS_BASE, base_text(parameters_base(d), "every parameter: true, nominal and recovered, a column group per model; four presets")
    yield "models/index.html", s2r.page(site, "Models: sim2real", MODELS_URL, index_body(d), "models", extra_head=STYLES,
                                        trail=breadcrumb(root + [("Models", MODELS_URL)]),
                                        description="Every generic type's model ladder, by family, and where each model is used.")
    for tid in dm.TYPE_ORDER:
        t = dm.TYPES[tid]
        yield f"models/{tid}/index.html", s2r.page(
            site, f"{t.title} models: sim2real", model_url(tid), type_body(d, tid), "model-type", extra_head=STYLES,
            trail=breadcrumb(root + [("Models", MODELS_URL), (t.title, model_url(tid))], back=[MODELS_URL]),
            description=f"{t.title}: its model ladder by family ({', '.join(t.families)}), what was identified at each model and where each is used.")
    yield "routines/index.html", s2r.page(site, "Calibration routines: sim2real", ROUTINES_URL, routines_body(d), "routines", extra_head=STYLES,
                                          data_ui=True, trail=breadcrumb(root + [("Routines", ROUTINES_URL)]),
                                          description="Every calibration routine and the parameters it identifies, and every parameter with the routines that can identify it.")
    yield "parameters/index.html", s2r.page(site, "Parameters: sim2real", PARAMETERS_URL, parameters_body(d), "parameters", extra_head=STYLES,
                                            aside=ui_shared.filter_bar(PARAMS_ID, "The filters need JavaScript; the parameters with a result are listed on the right."),
                                            data_ui=True, trail=breadcrumb(root + [("Parameters", PARAMETERS_URL)]),
                                            description="Every parameter: true, nominal and recovered per model, in data-ui, with presets.")
