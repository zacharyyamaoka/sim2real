"""The run page: the run's entity tree on the left, and on the right the picked level's standard dashboard with the data captured in this
run (type_cards/CONTRACT.md, "The run page: entity tree and the standard dashboard per level").

Zach, PROJECT - Sim2Real, 2026-11-06: "if I click on any run I should be able to view the data for that run. On the left should be like an
entity tree. so you can see basically the results at different levels. and then on the page what shows is the standard dashboard for that
level with the data that was capture from the run" (his RobotDx device tree as the picture); "Ok are we looking at models there though? Hmm
no in these dashboards we are seeing like the metrics and diagonistics that are indepdent of the models".

- **The tree** (ui_shared.status_tree in the workbench's left column, ui_shared.record_page): the contract's rule, from the served
  deployments.json: the run's deployment's nodes at the run's device (its station and the station's parts), every ancestor of them, and
  the cameras whose `sees` holds the station. Each node's dot is its level in this run: a typed node's worst model-independent diagnostic
  (domain.LEVEL_RANK; unknown when it has none with a value), a structural node the worst under it, a camera unknown (which run a camera
  filmed is its session's, not runs.json's).
- **A level per node** (one <section class="s2r-level"> each, the station's first and shown; static/ui-shared.js shows the picked one and
  writes ?entity=<node id>): its pinned metrics first, then its other model-independent metrics, its diagnostics with their levels and its
  coverage, all from sel.compute([run]) (a selection of one); then what was captured at that level: the station's is the Playback tab (the
  joint-3d component, and the camera-clip and joint-render pair where the session filmed it), a camera's its clip (camera-clip), a part's
  a data-ui dashboard of its channels in this run's samples (views/levels/<type>.base); the deployment rolls the run up entity by entity,
  an adapter lists its boards. Models are their own section, labelled: each model's fidelity is its error against real ÷ the station's T1
  floor, apart from the model-independent numbers.
- **The run's tags** in the header, for every level: excitation, closed loop, offline scope and the config snapshot, and Zach's caveat in
  plain words (offline evaluation judges models, not tracking under changed feedback).

Stdlib only. The numbers are type_cards' (selection.compute, domain.level); the page computes none of its own.
"""

from __future__ import annotations

import dataclasses
import json
from urllib.parse import quote, urlencode

from catalog_workbench.html import e, plural

import components
import deploy_tree  # noqa: F401  (puts the repo on sys.path for type_cards)
import pages
import ui_shared
import media as site_media
from adapter import deployment_url, run_url, station_key, station_url
from type_cards import domain as dm
from type_cards import selection as sel

SCRIPTS = ("site", "ui-shared", "sim2real")  # WHY ui-shared before sim2real: a deep link's level is picked before the dashboards mount
LEVEL_VIEWS = {  # the parts whose captured channels a level dashboard draws (site/views.py LEVELS), keyed by v3 type
    "foc_controller": "the board's own channels as it logged them: its q-axis current, the bus voltage and its temperature on the run's clock, "
                      "then where the run drove it (current against speed); real only, because the twins replay the joint's position and "
                      "torque, not the board's current loop",
    "bldc_motor": "the torque at the output, real (blue) against every model that replayed this run (orange); the board's torque against its "
                  "current, which is the torque constant the board assumes, a straight line (a measured torque per amp needs a load cell no "
                  "producer records); and the motor's operating map (torque against speed)",
    "encoder": "the angle it measured (real, blue) against the command (grey, dashed), the error between them as it saw it, and where the "
               "joint spent its time; no model, because an encoder model reads noise and latency, which no producer replays yet",
    "gearbox": "its output only, because no producer records the gearbox's input angle apart from its output, so its lost motion is not "
               "measured here: torque against angle in time order (the loop backlash and friction draw) and the output speed, real against "
               "every model",
}
NO_PART_MODEL = {  # why a part's model-dependent metrics have no value in a run (no producer replays these parts on their own yet)
    "foc_controller": "no producer replays the board's current loop on its own yet",
    "bldc_motor": "the twins replay the whole joint; none predicts the shaft torque or the winding temperature on its own yet",
    "gearbox": "no producer replays the gearbox's transmission on its own yet",
    "encoder": "no producer replays the encoder's noise on its own yet",
}
CAVEATS = {  # Zach's caveat (2026-11-06) per offline scope, in plain words: "You cannot do offline evaluation of online robot tracking
    # performance ... (but you can do it of models.) (althought be careful... if you have feedback control running on the real robot arm
    # and you change it right. you may get different response"
    "its own config": "This run was driven under the board's own feedback (closed loop), so replaying it offline judges a model only with this "
                      "run's own config{gains}; it cannot say how the joint would track under other feedback gains: that takes a new run.",
    "any config": "No command or feedback acted on this run (a free response), so a model can be judged on it offline under any config.",
    "any feedback gains": "This run was driven with no feedback acting, so replaying it offline judges a model under any feedback gains, though "
                          "only with this run's drive config (its current loop and limits).",
    "split": "Part of this run was driven under feedback (judge a model on that part only with this run's own config{gains}) and part was "
             "free, which any config can replay: {why}.",
    "unknown": "Nobody recorded what drove this run, so no offline scope is claimed for it.",
}
LEVEL_VERDICT = {"ok": "pass", "warning": "warn", "error": "fail", "unknown": "not_run"}  # a level's chip in the site's verdict colours


# --- the run's view: its tree, its selection of one, each node's level --------------------------------------------------------------

@dataclasses.dataclass
class RunView:
    row: dict
    tree: list[dict]  # the contract's tree for the run, depth first
    station: dict
    nodes: dict  # node id -> its selection node (sel.compute([run])["nodes"])
    levels: dict  # node id -> ok | warning | error | unknown
    whys: dict  # node id -> its dot's words
    outside: list[dict]  # the deployment's nodes this run's tree leaves out


class Context:
    """One build's v3 data for the run pages: the served deployments.json's nodes and each deployment's selection tables (read once)."""

    def __init__(self, site):
        self.site = site
        self.nodes = json.loads((site.data / "domain" / "deployments.json").read_text(encoding="utf-8"))["rows"]
        self._tables: dict = {}
        self._views: dict = {}

    def tables(self, dep: str):
        if dep not in self._tables:
            mine = [n for n in self.nodes if n["root"] == dep]
            tables = sel.load_tables(self.site.data, dep, nodes=mine)
            self._tables[dep] = (tables, sel._index(tables.run_diagnostics), sel._index(tables.coverage_points))
        return self._tables[dep]

    def selection(self, row: dict) -> dict:
        """sel.compute([run]) over this run's own rows: the same result as over the deployment's whole tables (compute reads only the
        selected runs' rows; site/tests checks it), at a thousandth of the cost per page."""
        tables, diags, points = self.tables(row["deployment"])
        mine = dataclasses.replace(tables, runs=[row], run_diagnostics=diags.get(row["run"], []), coverage_points=points.get(row["run"], []))
        return sel.compute([row["run"]], mine)

    def view(self, row: dict) -> RunView:
        if row["run"] not in self._views:
            self._views.clear()  # a page reads its run's view twice (the tree, the header), then never again
            self._views[row["run"]] = self._view(row)
        return self._views[row["run"]]

    def _view(self, row: dict) -> RunView:
        tree = run_tree(self.nodes, row)
        station = next(n for n in tree if n.get("structural") == "station")
        result = self.selection(row)
        by_node = {n["node"]: n for n in result["nodes"]}
        levels, whys = node_levels(tree, by_node)
        ids = {n["id"] for n in tree}
        outside = [n for n in self.nodes if n["root"] == row["deployment"] and n["id"] not in ids]
        return RunView(row=row, tree=tree, station=station, nodes=by_node, levels=levels, whys=whys, outside=outside)


def context(site) -> Context:
    ctx = getattr(site, "_run_pages", None)
    if ctx is None:
        ctx = site._run_pages = Context(site)
    return ctx


def run_tree(nodes: list[dict], row: dict) -> list[dict]:
    """The contract's tree for a run: its deployment's nodes at the run's device (the station and its parts), every ancestor of them, the
    cameras whose `sees` holds the station; depth first, siblings in deployments.json's order."""
    mine = [n for n in nodes if n["root"] == row["deployment"]]
    by_id = {n["id"]: n for n in mine}
    own = [n for n in mine if n.get("device") == row["device"]]
    station = next((n for n in own if n.get("structural") == "station"), None)
    if station is None:
        raise ValueError(f"{row['run']}: no station node at {row['device']} in {row['deployment']}'s tree (deployments.json)")
    keep: set = set()
    for n in own:
        while n is not None and n["id"] not in keep:
            keep.add(n["id"])
            n = by_id.get(n.get("parent"))
    keep |= {n["id"] for n in mine if station["id"] in (n.get("sees") or [])}
    kids: dict = {}
    for n in mine:
        kids.setdefault(n.get("parent"), []).append(n)
    out: list[dict] = []

    def walk(parent):
        for n in kids.get(parent, []):
            if n["id"] in keep:
                out.append(n)
                walk(n["id"])

    walk(None)
    return out


def independent(type_id: str, metric_id: str) -> bool:
    """A metric (or its diagnostic) that needs no model: what a level's dashboard shows by default (Zach, 2026-11-06)."""
    spec = dm.metric(type_id, metric_id)
    return spec is not None and not spec.model_dependent


def node_levels(tree: list[dict], by_node: dict) -> tuple[dict, dict]:
    """Each node's level in this run and its dot's words: a typed node's worst model-independent diagnostic (domain.LEVEL_RANK, none is
    unknown), a camera unknown, a structural node the worst under it."""
    rank = dm.LEVEL_RANK
    levels, whys = {}, {}
    for n in reversed(tree):  # children first
        nid = n["id"]
        if nid in by_node:
            sn = by_node[nid]
            rows = [d for d in sn["diagnostics"] if independent(sn["entity_type"], d["metric"])]
            levels[nid] = max((d["level"] for d in rows), key=rank.get, default="unknown")
            known = [d for d in rows if d["value"] is not None]
            whys[nid] = (f"the worst of its {plural(len(rows), 'model-independent diagnostic')}, {len(known)} with a value in this run" if rows
                         else "its type has no model-independent diagnostic")
        elif n.get("entity_type") and not n.get("structural"):
            levels[nid] = "unknown"
            whys[nid] = "a camera's diagnostics are not computed per run: which runs it filmed is its sessions', not runs.json's"
        else:
            under = [levels[c["id"]] for c in tree if c.get("parent") == nid]
            levels[nid] = max(under, key=rank.get, default="unknown")
            whys[nid] = "the worst level under it in this run"
    return levels, whys


def level_kind(n: dict) -> str:
    """What a node's level is on the page: deployment, adapter, station, camera or part."""
    if n.get("structural"):
        return n["structural"]
    return "camera" if (n.get("entity_type") or "").endswith("camera") else "part"


def entity_href(node_id: str) -> str:
    return f"?entity={quote(node_id, safe='')}"


def part_label(n: dict) -> str:
    """"driver: moteus-r4.11" -> "moteus-r4.11" (deployments.json titles a part by its role, then the record's words)."""
    title = n.get("title") or ""
    return title.split(": ", 1)[1] if ": " in title else title


def short_name(n: dict) -> str:
    kind = level_kind(n)
    if kind == "station":
        return n.get("device") or n["title"]
    if kind == "part":
        return (n.get("title") or "").split(": ", 1)[0] or n["id"].rsplit("/", 1)[-1]
    return (n.get("title") or n["id"]).replace("Intel RealSense ", "RealSense ")


# --- numbers in words -------------------------------------------------------------------------------------------------------------------

def fmt(value, unit: str = "") -> str:
    if value is None:
        return "—"
    unit = "" if unit == "1" else unit  # UCUM's dimensionless unit (RobotDx's fault count): a count reads as a number
    text = pages.num(float(value), 3) if isinstance(value, float) else pages.num(value)
    if unit.startswith("×"):
        return f"{text}{unit.split(' ', 1)[0]}" + (f" {unit.split(' ', 1)[1]}" if " " in unit else "")
    return f"{text} {unit}".strip()


def raw(value) -> str:
    """A number as its data attribute holds it: the full value (repr), "" for none."""
    return "" if value is None else repr(float(value))


def level_chip(level: str) -> str:
    return pages.chip(LEVEL_VERDICT.get(level, "not_run"), level)


def limits_text(d: dict) -> str:
    parts = []
    for word, lo, hi in (("warn", d.get("warn_lo"), d.get("warn_hi")), ("error", d.get("error_lo"), d.get("error_hi"))):
        if hi is not None:
            parts.append(f"{word} above {pages.num(hi)}")
        if lo is not None:
            parts.append(f"{word} below {pages.num(lo)}")
    return " · ".join(parts) or "set per unit (no value)"


# --- the header: every level's ------------------------------------------------------------------------------------------------------

def run_tags(row: dict) -> str:
    """The run's tags (type_cards domain v3, site/deploy_tree.py's columns) and Zach's caveat in plain words."""
    exc = row.get("excitation") or "unknown"
    loop = row.get("closed_loop")
    scope = row.get("offline_scope") or "unknown"
    full = row.get("config") == deploy_tree.FULL and row.get("config_sha256")
    cfg = (f"full config · sha256 {row['config_sha256'][:12]}" + (f" · {row['config_keys']} keys" if row.get("config_keys") else "")) if full \
        else "config not recorded"
    why = dm.RUN_KINDS.get(row.get("kind") or "", (None, None, ""))[2]
    tags = [("excitation", exc, exc, f"{dm.EXCITATIONS.get(exc, '')}. {why}".strip(". ")),
            ("closed_loop", {True: "true", False: "false"}.get(loop, "unknown"), {True: "closed loop", False: "open loop"}.get(loop, "loop unknown"),
             "whether the board's feedback acted during the run"),
            ("offline_scope", scope, f"offline: {scope}", dm.OFFLINE_SCOPES.get(scope, "")),
            ("config", row["config_sha256"] if full else "not recorded", cfg, row.get("config_detail") or "")]
    chips = "".join(f'<span class="s2r-rtag s2r-rtag-{e(key)}" data-tag="{e(key)}" data-value="{e(value)}" title="{e(tip)}">{e(words)}</span>'
                    for key, value, words, tip in tags)
    rest = (f'<span class="s2r-rtag-more">environment {e(row.get("environment") or deploy_tree.UNKNOWN)} · setting '
            f'{e(row.get("setting") or deploy_tree.UNKNOWN)}'
            + (f" · test type {e(row['test_type'])}" if row.get("test_type") not in (None, deploy_tree.NOT_RECORDED) else "")
            + f' · {pages.a("#evidence", "what is recorded")}</span>')
    gains = f" ({row['gains']})" if row.get("gains") else ""
    sentence = CAVEATS.get(scope, CAVEATS["unknown"]).format(gains=gains, why=why or "its kind's producer code says how")
    return (f'<p class="s2r-runtags" aria-label="Run tags">{chips}{rest}</p>\n'
            f'<p class="s2r-caveat"><b>Offline evaluation is valid for models, not for online tracking under changed feedback.</b> {e(sentence)}</p>')


def run_header(site, row: dict) -> str:
    """The record's header: the run's title and line, its tags and caveat (every level's), then one section per level of its tree."""
    dep = site.deployment(row["deployment"])
    media = pages.media_of(site)
    v = context(site).view(row)
    # WHY the station's link model and the clip's camera in the record: the joint-3d and camera-clip components read them as {glb} and
    # {camera} (static/sim2real.js fills them from here; a component mounted alone reads them from its .base URL's query)
    glb = (media.glb_url(row["deployment"], station_key(row["device"])) if media else None) or ""
    camera = next((x.id for x in components.entities_of(row, media) if x.kind == "camera"), "")
    record = pages.record_json(deployment=row["deployment"], run=row["run"], station=station_key(row["device"]), device=row["device"], glb=glb,
                               camera=camera, **pages.limits(dep, row["device"]))
    levels = [station_level(site, v, v.station)] + [level_of(site, v, n) for n in v.tree if n is not v.station]
    return f"""{record}
<h1>{e(pages.run_title(row))}</h1>
<p class="sub">{e(pages.when(row.get("started")))} · {e(row.get("kind") or "")} · {pages.num(row.get("duration_s"))} s · {e(row.get("gains") or "")} · {e(row.get("compare") or "")}</p>
{run_tags(row)}
{"".join(levels)}"""


# --- the levels -------------------------------------------------------------------------------------------------------------------------

def section(n: dict, body: str, shown: bool) -> str:
    return (f'<section class="s2r-level" data-entity="{e(n["id"])}" data-entity-kind="{e(level_kind(n))}" aria-label="{e(short_name(n))} in this run"'
            f'{"" if shown else " hidden"}>\n{body}\n</section>\n')


def level_head(v: RunView, n: dict, sub: str) -> str:
    by_id = {x["id"]: x for x in v.tree}
    path, at = [], by_id.get(n.get("parent"))
    while at is not None:
        path.insert(0, f'<a href="{e(entity_href(at["id"]))}">{e(short_name(at))}</a>')
        at = by_id.get(at.get("parent"))
    crumbs = (f'<p class="s2r-level-path">{" › ".join(path)} › <span title="{e(n.get("title") or "")}">{e(n.get("title") or "")}</span></p>'
              if path else "")  # WHY none on the root: its heading is its whole title
    return (f'<h2 class="s2r-level-h">{ui_shared.dot(v.levels[n["id"]], v.whys[n["id"]])}<span class="s2r-level-ic">{ui_shared.icon(ui_shared.icon_word(n))}</span>'
            f'{e(short_name(n))} <small>{e(sub)}</small></h2>\n{crumbs}')


def what(text: str) -> str:
    return f'<p class="s2r-what"><b>What you\'re looking at:</b> {e(text)}</p>'


def metric_kpis(sn: dict | None, type_id: str) -> str:
    """The level's model-independent metrics, pinned first, each its value in this run or why it has none."""
    rows = [m for m in (sn or {}).get("metrics", []) if independent(type_id, m["metric"]) and m.get("model") is None]
    if not rows:
        specs = [m for m in dm.TYPES[type_id].metrics if not m.model_dependent]
        rows = [{"metric": m.id, "title": m.title, "unit": m.unit, "pinned": m.pinned, "value": None, "why": m.why_not or "not computed per run"}
                for m in specs]
    rows.sort(key=lambda m: not m["pinned"])
    items, whys = [], {}
    for m in rows:
        pin = ' <span class="s2r-pin" title="pinned: one of the type\'s headline numbers">pinned</span>' if m["pinned"] else ""
        if m["value"] is None:
            whys.setdefault(m.get("why") or "not computed per run", []).append(m["title"])
        value = (f'<span data-metric="{e(m["metric"])}" data-value="{raw(m["value"])}">{e(fmt(m["value"], m["unit"]))}</span>' if m["value"] is not None
                 else f'<span data-metric="{e(m["metric"])}" data-value="" title="{e(m.get("why") or "")}">—</span>')
        items.append(f'<div{' class="s2r-none"' if m["value"] is None else ""}><dt>{e(m["title"])}{pin}</dt><dd>{value}</dd></div>')
    note = "".join(f'<p class="s2r-whynot">— {e(", ".join(titles))}: {e(why)}.</p>' for why, titles in whys.items())
    return f'<h3>Metrics <small>this run, no model needed</small></h3><dl class="s2r-kpis s2r-level-kpis">{"".join(items)}</dl>{note}'


def diagnostics_table(sn: dict | None, type_id: str, subject: str) -> str:
    rows = [d for d in (sn or {}).get("diagnostics", []) if independent(type_id, d["metric"])]
    if sn is None:
        rows = [dm.diagnostic_row(d, None, subject=subject, metric=d.metric, model=None) for d in dm.TYPES[type_id].diagnostics
                if d.units == "metric" and independent(type_id, d.metric)]
    if not rows:
        return "<h3>Diagnostics</h3><p class=\"mut\">Its type has no model-independent diagnostic: every check of it needs a model (below).</p>"
    body = "".join(f'<tr data-diagnostic="{e(d["diagnostic"])}" data-level="{e(d["level"])}"><td>{level_chip(d["level"])}</td><th scope="row">{e(d["title"])}</th>'
                   f'<td>{e(fmt(d["value"], d.get("unit") or ""))}</td><td>{e(limits_text(d))}</td>'
                   f'<td>{e(d.get("message") or ("no value in this run" if d["value"] is None else "within its limits" if d["level"] == "ok" else "its limit has no value for this unit" if d["level"] == "unknown" else ""))}</td></tr>'
                   for d in rows)
    return (f'<h3>Diagnostics <small>a metric with its warning and error limits (type_cards, domain v3)</small></h3><div class="s2r-scroll">'
            f'<table class="s2r-table s2r-level-dx"><thead><tr><th scope="col">Level</th><th scope="col">Diagnostic</th><th scope="col">Value</th>'
            f'<th scope="col">Limits</th><th scope="col">What it says</th></tr></thead><tbody>{body}</tbody></table></div>')


def coverage_block(sn: dict | None, type_id: str) -> str:
    c = (sn or {}).get("coverage") or {"pct": None, "why": dm.TYPES[type_id].coverage.why_not or "not computed per run", "gate_pct": None}
    if c.get("pct") is None:
        return (f'<h3>Coverage of this run</h3><div class="s2r-cov" data-coverage-pct="" data-coverage-verdict="{e(c.get("verdict") or "unknown")}">'
                f'<p class="mut">{e(c.get("why") or "not computed")}</p></div>')
    gate = c.get("gate_pct")
    verdict = c.get("verdict") or "observed"
    marg = "; ".join(f"{k} {pages.num(val)} % of its bins" if val is not None else f"{k} not planned" for k, val in (c.get("marginals") or {}).items())
    tick = f'<b style="left:{min(100.0, gate):g}%" title="the type\'s gate: {gate:g} %"></b>' if gate is not None else ""
    return (f'<h3>Coverage of this run</h3><div class="s2r-cov" data-coverage-pct="{c["pct"]}" data-coverage-verdict="{e(verdict)}">'
            f'<p><strong>{pages.num(c["pct"])} %</strong> of the {c["reachable"]:,} reachable cells (q, qd, qdd), {c["visited"]:,} visited by '
            f'{plural(c["samples"], "sample")} ({c["outside"]:,} outside the range)'
            + (f' · the type\'s gate {gate:g} %: {pages.chip({"pass": "pass", "fail": "fail"}.get(verdict, "not_run"), verdict)}' if gate is not None else "")
            + f'</p><div class="s2r-bar" role="img" aria-label="{pages.num(c["pct"])} % covered"><i style="width:{min(100.0, c["pct"]):g}%"></i>{tick}</div>'
            + (f'<p class="mut">Beside it, never folded in: {e(marg)}. </p>' if marg else "")
            + f'<details class="s2r-rule"><summary>The rule</summary><p>{e(c.get("rule") or "")}</p></details></div>')


def model_rows(v: RunView, sn: dict | None, robotdx: dict) -> str:
    """One row per model the run replayed: its fidelity (error ÷ the station's T1 floor) with its level and T2's gate, and RobotDx's own
    check of this run. Twin of record first."""
    row = v.row
    names = [s for s in row.get("situations", []) if s not in ("real", "target")]
    names.sort(key=lambda s: s != "twin of record")
    fid = {m["model"]: m for m in (sn or {}).get("metrics", []) if m["metric"] == "servo.twin_fidelity" and m.get("model")}
    dx = {d["model"]: d for d in (sn or {}).get("diagnostics", []) if d["diagnostic"] == "servo.twin_fidelity.dx" and d.get("model")}
    gates = {g["model"]: g for g in (sn or {}).get("gates", []) if g["diagnostic"] == "servo.twin_fidelity.dx" and g.get("model")}
    spec = dm.diagnostic("integrated_servo", "servo.twin_fidelity.dx")
    out = []
    for name in names:
        m, d, g, r = fid.get(name) or {}, dx.get(name) or {}, gates.get(name) or {}, robotdx.get(name) or {}
        value = m.get("value")
        lv = d.get("level") or dm.level(spec, value)
        check = (f'{pages.chip(r.get("verdict"))} {e(fmt(r.get("value"), r.get("unit") or "mrad"))}'
                 + (f' <small>against {pages.num(r.get("error_hi"))} mrad</small>' if r.get("error_hi") is not None else "")) if r else "—"
        out.append(f'<tr data-model="{e(name)}" data-fidelity="{raw(value)}" data-level="{e(lv)}"><th scope="row"><span class="s2r-sim-dot"></span>{e(name)} '
                   f'<small>vs real</small></th><td>{e(fmt(value, "× floor"))}</td><td>{level_chip(lv)}</td>'
                   f'<td>{pages.chip(g.get("verdict")) if g else "—"}</td><td>{check}</td></tr>')
    return "".join(out)


def models_block(site, v: RunView, sn: dict | None, type_id: str) -> str:
    """The models, labelled apart (Zach: the dashboards are the metrics and diagnostics independent of the models)."""
    row = v.row
    current = ", ".join(f"{m.id} ({m.title})" for m in dm.current_models(type_id))
    pending = [m.title for m in dm.TYPES[type_id].metrics if m.model_dependent and m.per_run is None]
    later = f'<p class="mut">Not computed per run yet: {e(", ".join(pending))} (no producer writes them per run; the type card says how each is measured).</p>' if pending else ""
    if type_id != "integrated_servo":
        return (f'<div class="s2r-models-run"><h3>Models <small>apart from the numbers above</small></h3><p>This type\'s model today: {e(current or "none")}. '
                f'No replay of it on its own in this run: {e(NO_PART_MODEL.get(type_id, "no producer replays it per run yet"))}.</p>{later}</div>')
    names = [s for s in row.get("situations", []) if s not in ("real", "target")]
    if not names:
        return (f'<div class="s2r-models-run"><h3>Models on this run <small>apart from the numbers above</small></h3><p>No model replayed this run: it is '
                f'real only. The station\'s model today: {e(current)}.</p>{later}</div>')
    robotdx = {sel.model_label(d.get("title", "")): d for d in pages.run_diagnostics_rows(site, row) if d.get("diagnostic") == "stock.model_error"}
    floor = context(site).tables(row["deployment"])[0].floors.get(row["device"])
    return (f'<div class="s2r-models-run"><h3>Models on this run <small>twin of record vs real, apart from the numbers above</small></h3>'
            f'<p>Each model replayed this run\'s own command in simulation. Its fidelity is its error against real ÷ the station\'s T1 floor'
            f'{f" ({pages.num(floor)} mrad)" if floor else ""}: T2\'s ruler, ≤ 1.5× is twinned; the level is the type\'s diagnostic on it (warning above '
            f'2×). RobotDx\'s check is its own floor\'s, on this run alone. What each model is and its parameters: the Playback, below.</p>'
            f'<div class="s2r-scroll"><table class="s2r-table s2r-level-models"><thead><tr><th scope="col">Model</th><th scope="col">Twin / floor</th>'
            f'<th scope="col">Level</th><th scope="col">T2 gate (≤ 1.5×)</th><th scope="col">RobotDx\'s check</th></tr></thead><tbody>'
            f'{model_rows(v, sn, robotdx)}</tbody></table></div>{later}</div>')


def robotdx_checks(site, row: dict) -> str:
    """The model-independent checks robotdx.diagnostics computed from this run (its Diagnostics tab has every one)."""
    rows = [d for d in pages.run_diagnostics_rows(site, row) if d.get("diagnostic") != "stock.model_error"]
    if not rows:
        return ""
    body = "".join(f'<tr><td>{pages.chip(d.get("verdict"))}</td><th scope="row">{e(d.get("title") or "")}</th><td>{e(fmt(d.get("value"), d.get("unit") or ""))}</td>'
                   f'<td>{e(d.get("message") or "")}</td></tr>' for d in rows)
    return (f'<details class="s2r-rdx" open><summary>Checks robotdx.diagnostics computed from this run ({len(rows)})</summary><div class="s2r-scroll">'
            f'<table class="s2r-table s2r-level-rdx"><tbody>{body}</tbody></table></div></details>')


def station_level(site, v: RunView, n: dict) -> str:
    row = v.row
    media = pages.media_of(site)
    dep = site.deployment(row["deployment"])
    sn = v.nodes.get(n["id"])
    t = dm.TYPES[n["entity_type"]]
    gates = f'<p class="s2r-gline">{pages.a(station_url(dep.id, row["device"]), row["device"])} gates (the newest acceptance, over every run): {pages.gate_chips(dep, row["device"])}</p>'
    note = ('<p class="s2r-level-note">Captured at this level, on the Playback below: the link in 3D (the joint-3d component) and, where the session '
            'filmed it, the camera\'s clip beside the twin\'s render (camera-clip, joint-render), all on this run\'s clock, then every plot of the run.</p>')
    body = (level_head(v, n, f"{t.title} · station")
            + components.what_html(components.what_joint(row, media), components.what_camera(row, media))
            + metric_kpis(sn, t.id) + diagnostics_table(sn, t.id, n["id"]) + robotdx_checks(site, row) + coverage_block(sn, t.id)
            + models_block(site, v, sn, t.id) + gates + note)
    return section(n, body, shown=True)


def level_of(site, v: RunView, n: dict) -> str:
    kind = level_kind(n)
    if kind == "deployment":
        return deployment_level(site, v, n)
    if kind == "adapter":
        return adapter_level(site, v, n)
    if kind == "camera":
        return camera_level(site, v, n)
    return part_level(site, v, n)


def part_level(site, v: RunView, n: dict) -> str:
    row = v.row
    t = dm.TYPES[n["entity_type"]]
    sn = v.nodes.get(n["id"])
    captured = ""
    if t.id in LEVEL_VIEWS:
        query = urlencode({"deployment": row["deployment"], "run": row["run"], "device": row["device"], "station": station_key(row["device"])})
        captured = (f'<h3>Captured in this run</h3>'
                    + pages.dashboard(f"/views/levels/{t.id}.base?{query}", f"{short_name(n)} of {row['device']}: {pages.run_title(row)}"))
    words = (f"{row['device']}'s {short_name(n)} ({part_label(n)}; type {t.title}) in this run: "
             + (LEVEL_VIEWS.get(t.id) or "what its type measures") + ". Its numbers below need no model; its models are apart.")
    body = (level_head(v, n, f"{t.title} · {row['device']}") + what(words) + metric_kpis(sn, t.id) + diagnostics_table(sn, t.id, n["id"])
            + coverage_block(sn, t.id) + captured + models_block(site, v, sn, t.id))
    return section(n, body, shown=False)


def clip_of(site, row: dict) -> tuple[str, str]:
    """(the serial of the camera whose clip of this run the media hold, or "", why there is none)."""
    media = pages.media_of(site)
    entry = (media.runs.get(row["run"]) if media else None) or {}
    if entry.get("media") and entry.get("camera"):
        return str(entry["camera"]), ""
    return "", (entry.get("why_none") or ("the media are not built (tools/build_media.py)" if not media else "this run has no clip"))


def camera_level(site, v: RunView, n: dict) -> str:
    row = v.row
    t = dm.TYPES[n["entity_type"]]
    serial = n["id"].rsplit("camera-", 1)[-1]
    filmed, why_none = clip_of(site, row)
    by_id = {x["id"]: x for x in v.outside + v.tree}
    sees = ", ".join(short_name(by_id[s]) for s in n.get("sees") or [] if s in by_id)
    if filmed == serial:
        clip = components.mount("camera-clip", components.Entity("camera", serial, row["deployment"]), row["run"], device=row["device"],
                                label=f"camera-clip · {short_name(n)} · {pages.run_title(row)}")
        words = (f"the {short_name(n)} that watches {sees} (the deployment's record), and its clip of this run: cut from its session's recording "
                 f"onto the run's clock, {row['device']}'s tag boxed in blue where the camera found it. It plays on its own clock here; the Playback "
                 f"plays it beside the twin's render.")
        captured = f"<h3>Captured in this run</h3>{clip}"
    else:
        words = f"the {short_name(n)} that watches {sees} (the deployment's record). " + (
            f"No clip of this run from it: {why_none}." if not filmed else f"This run was filmed by camera {filmed}, not by this one.")
        captured = ""
    body = (level_head(v, n, t.title) + what(words) + captured + metric_kpis(None, t.id) + diagnostics_table(None, t.id, n["id"])
            + coverage_block(None, t.id) + models_block(site, v, None, t.id))
    return section(n, body, shown=False)


def deployment_level(site, v: RunView, n: dict) -> str:
    row = v.row
    media = pages.media_of(site)
    dep = site.deployment(row["deployment"])
    rows = []
    for x in v.tree:
        sn = v.nodes.get(x["id"])
        tid = x.get("entity_type")
        pinned = [m for m in (sn or {}).get("metrics", []) if m["pinned"] and m.get("model") is None and independent(tid, m["metric"])]
        nums = " · ".join(f"{m['title']} {fmt(m['value'], m['unit'])}" for m in pinned if m["value"] is not None) or "—"
        cov = ((sn or {}).get("coverage") or {}).get("pct")
        pad = "&nbsp;" * 3 * (x["depth"] - n["depth"])
        rows.append(f'<tr data-entity="{e(x["id"])}"><th scope="row">{pad}<a href="{e(entity_href(x["id"]))}">{e(short_name(x))}</a></th>'
                    f'<td>{e(x.get("entity_title") or x.get("structural") or "")}</td><td>{ui_shared.dot(v.levels[x["id"]], v.whys[x["id"]])} {level_chip(v.levels[x["id"]])}</td>'
                    f'<td>{e(nums)}</td><td>{e(fmt(cov, "%")) if cov is not None else "—"}</td></tr>')
    left_out = ", ".join(plural(k, w) for w, k in (("other station", sum(1 for x in v.outside if x.get("structural") == "station")),
                                                    ("camera", sum(1 for x in v.outside if level_kind(x) == "camera"))) if k)
    words = (f"the deployment this run belongs to ({n.get('kind')}, {row.get('environment') or 'unknown'}): below, every entity of it this run "
             f"touched, each with its level in this run and its pinned numbers. Its own page has every run, the gates and coverage.")
    own_page = pages.a(deployment_url(dep.id), f"{dep.row['title']}'s page")
    body = (level_head(v, n, f"deployment · {n.get('kind')}")
            + f'<div class="s2r-level-shot">{site_media.figure(media, dep.id, cls="s2r-shot")}<div><p>{e(n.get("summary") or dep.row.get("summary") or "")}</p>{what(words)}</div></div>'
            + '<h3>This run, entity by entity</h3><div class="s2r-scroll"><table class="s2r-table s2r-rollup"><thead><tr><th scope="col">Entity</th>'
              '<th scope="col">Type</th><th scope="col">Level</th><th scope="col">Pinned, no model</th><th scope="col">Coverage</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>"
            + f'<p>Not in this run: {e(left_out or "nothing")}. {own_page}: every run, the gates, coverage.</p>')
    return section(n, body, shown=False)


def adapter_level(site, v: RunView, n: dict) -> str:
    row = v.row
    dep = site.deployment(row["deployment"])
    boards = [x for x in v.outside + v.tree if x.get("parent") == n["id"] and x.get("structural") == "station"]
    order = {d["device"]: d.get("order", 0) for d in dep.devices}
    boards.sort(key=lambda x: order.get(x.get("device"), 0))
    body_rows = []
    for x in boards:
        cells = dep.gates_of(x["device"])
        passing = sum(1 for g in cells if g["verdict"] == "pass")
        here = ' <span class="s2r-here">this run</span>' if x["device"] == row["device"] else ""
        body_rows.append(f'<tr data-board="{e(x["device"])}"><th scope="row">{pages.a(station_url(dep.id, x["device"]), x["device"])}{here}</th>'
                         f'<td>{e((x.get("title") or "").split(" · ", 1)[-1])}</td>'
                         f'<td>{passing} of {len(cells)}</td><td>{x.get("runs") or 0:,}</td></tr>')
    words = (f"the CAN-FD adapter this run's board talks through (the bam_rack_twin record wires each board to an adapter_serial): the "
             f"{plural(len(boards), 'board')} it carries, each with its gate cells passing in the newest acceptance; this run is {row['device']}'s.")
    body = (level_head(v, n, "adapter") + what(words)
            + '<div class="s2r-scroll"><table class="s2r-table s2r-boards"><thead><tr><th scope="col">Board</th><th scope="col">Station</th>'
              '<th scope="col">Gate cells passing</th><th scope="col">Runs</th></tr></thead><tbody>' + "".join(body_rows) + "</tbody></table></div>")
    return section(n, body, shown=False)


# --- the tree ---------------------------------------------------------------------------------------------------------------------------

def node_line(site, v: RunView, n: dict) -> str:
    row = v.row
    kind = level_kind(n)
    if kind == "deployment":
        stations = sum(1 for x in v.tree + v.outside if x.get("structural") == "station")
        return f"{n.get('kind')} · {row.get('environment') or 'unknown'} · {plural(stations, 'station')}"
    if kind == "adapter":
        boards = sum(1 for x in v.tree + v.outside if x.get("parent") == n["id"] and x.get("structural") == "station")
        return f"{plural(boards, 'board')} · this run on {row['device']}"
    if kind == "station":
        tracking = row.get("tracking_mrad")
        return (f"tracking {fmt(tracking, 'mrad')} · " if isinstance(tracking, (int, float)) else "") + (row.get("compare") or "real only")
    if kind == "camera":
        filmed, _why = clip_of(site, row)
        return f"filmed this run · {fmt(row.get('duration_s'), 's')}" if filmed == n["id"].rsplit("camera-", 1)[-1] else "no clip of this run"
    label = part_label(n)
    rate = next((m["value"] for m in (v.nodes.get(n["id"]) or {}).get("metrics", []) if m["metric"] == "driver.loop_rate" and m["value"] is not None), None)
    return label + (f" · loop {fmt(rate, 'Hz')}" if rate is not None else "")


def node_meta(v: RunView, n: dict) -> str:
    kind = level_kind(n)
    if kind == "deployment":
        return f"{n.get('runs') or 0:,} runs"
    if kind == "station":
        return v.row.get("kind") or ""
    return ""  # WHY none on a part, an adapter or a camera: the icon and the level's heading name the type; the row keeps its width


def tree_html(site, v: RunView) -> str:
    row = v.row
    need = sum(1 for lv in v.levels.values() if lv in ("warning", "error"))
    left_out = [x for x in v.outside if x.get("structural") == "station" or level_kind(x) == "camera"]
    more = ""
    if left_out:
        words = ", ".join(plural(k, w) for w, k in (("other station", sum(1 for x in left_out if x.get("structural") == "station")),
                                                     ("camera", sum(1 for x in left_out if level_kind(x) == "camera"))) if k)
        more = (f'<p class="s2r-tree-more">Not in this run: {pages.a(deployment_url(row["deployment"]), words)} of '
                f'{e(site.deployment(row["deployment"]).row["title"])}</p>')
    return ui_shared.status_tree(
        v.tree, selected=v.station["id"], href=lambda n: entity_href(n["id"]), name=short_name, line=lambda n: node_line(site, v, n),
        kind=level_kind, level=lambda n: v.levels[n["id"]], why=lambda n: v.whys[n["id"]], meta=lambda n: node_meta(v, n),
        key=row["deployment"], heading="Entities", section="In this run",
        summary=f"{len(v.tree)} {'entity' if len(v.tree) == 1 else 'entities'} · " + ("nothing needs you" if not need else f"{need} need you"), more=more)


# --- the pages --------------------------------------------------------------------------------------------------------------------------

def page(site, row: dict) -> str:
    import catalog  # noqa: PLC0415  (catalog imports this module)

    v = context(site).view(row)
    return ui_shared.record_page(catalog.CATALOG, catalog.RUN, site, row, tree_html(site, v),
                                 extra_head=f'<link rel="stylesheet" href="{ui_shared.RUN_STYLESHEET}">\n')


def pages_of(site):
    """(path, html) of every run's page."""
    for row in site.runs:
        yield run_url(row).strip("/") + "/index.html", page(site, row)

