"""The deployments: an index of every deployment, virtual or physical, filtered on the left by kind and tags, and a page for every node
of every deployment's tree, each a deployment of its own (type_cards/CONTRACT.md, "Domain model v3").

Zach (PROJECT - Sim2Real, 2026-11-06): "Ok I like organizing this around Deployments. The orcale examples are also deployments its just
they are 'Virtual' ... Ok now when I click a deployment... I will see the deployment page ... Each sub componet of the deployment could
basically be its own deployment (in fact it almost is) ... the first level of filtering I think is for the type of dpeloyment... It is
helpful for example to see thoose deployments tagged with orcale example. Or perhaps only deployments that use a camera".

What a page reads, never a new number:
- data/domain/deployments.json, the contract's projection (type_cards/instances.py): the nodes, their trees, kinds and tags;
- a node's runs: the runs.json rows whose device is under it (the contract's rule; none kept for a virtual node, unknown for a camera),
  and over them sel.compute (type_cards/selection.py): every typed entity's metrics, diagnostics, gates and coverage. One selection per
  node (a station's equals the build's own preset of it; the site test holds both);
- per entity type, its ladder's current model (domain v3) and the ones used here: the system-ID oracle's fit or the selection rule's pick
  (sysid/results/<example>.json, a virtual deployment), the producer's models that replayed the runs (a physical one);
- the media index for the renders (site/media.py), the oracle's results for a virtual deployment's verdict and held-out errors.

Writes (site/build.py): data/deployment-cards.json (the index's rows, data-ui's runtime shape), views/deployments.base (the index: a
rail, cards and a table), views/deployment-node-runs.base (a node's runs, its scope in the URL's query), deployments/index.html and
deployments/<node id>/index.html. Stdlib only.

WHY a page per node at /deployments/<node id>/, beside the record pages that stay (gates, why it fails, evidence), and why a fidelity
metric's headline is the model that replayed the most runs: docs/decision-deployments-pages-2026-11-07.md.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode

from catalog_workbench.data_ui import views_element
from catalog_workbench.html import breadcrumb, e, plural

import adapter
import components
import deploy_tree  # noqa: F401  (puts the repo on sys.path, appended, as the site's other modules rely on)
import landing
import pages
import ui_shared
import views
from type_cards import domain as dm  # noqa: E402  (CONTRACT.md, "Domain model v3": the type level)
from type_cards import instances as inst  # noqa: E402  (the instance level)
from type_cards import selection as sel  # noqa: E402  (metrics, diagnostics and coverage over any runs)

URL = "/deployments/"
VIEWS_ID = "deployments-views"
CARDS = "deployment-cards.json"  # under the site's data/
INDEX_BASE = "views/deployments.base"
RUNS_BASE = "views/deployment-node-runs.base"
STYLES = ui_shared.head() + '<link rel="stylesheet" href="/static/deployments.css">\n'
# WHY blue and orange (the site's convention, Zach 2026-10-28: "train the eye to know what is real and what is sim"): a physical deployment
# is real hardware, a virtual one a simulation
KIND_TONE = {"physical": "real", "virtual": "sim"}
KIND_SLOT = {"physical": 1, "virtual": 2}
BASIS_WORDS = {"selected": "the selection rule's pick on held-out data (sysid)",
               "fitted": "fitted by sysid: the highest rung with a parameter it identified here"}


def node_url(node_id: str) -> str:
    return f"{URL}{node_id}/"


# --- the domain, loaded once per build ---------------------------------------------------------------------------------------------

@dataclass
class Domain:
    nodes: list[dict]
    results: dict                      # oracle example -> its committed sysid result
    runs: dict                         # physical deployment -> its runs.json rows (the site's, tagged)
    tables: dict                       # physical deployment -> sel.Tables
    parameters: list[dict]
    media: object = None
    by_id: dict = field(init=False)
    kids: dict = field(init=False)
    _selections: dict = field(default_factory=dict)

    def __post_init__(self):
        self.by_id = {n["id"]: n for n in self.nodes}
        self.kids = {}
        for n in self.nodes:
            self.kids.setdefault(n["parent"], []).append(n)

    def roots(self) -> list[dict]:
        return self.kids.get(None, [])

    def tree(self, root: str) -> list[dict]:
        return [n for n in self.nodes if n["root"] == root]

    def subtree(self, node_id: str) -> list[dict]:
        return inst.subtree(self.nodes, node_id)

    def path(self, node_id: str) -> list[dict]:
        """The node and its ancestors, the deployment first."""
        out, at = [], self.by_id.get(node_id)
        while at is not None:
            out.append(at)
            at = self.by_id.get(at["parent"])
        return out[::-1]

    def run_rows(self, node: dict) -> list[dict] | None:
        """The contract's runs of a node: the runs whose device is under it. A virtual node keeps none (sysid does not persist its
        simulated runs); a physical node with no device under it (a camera) does not know which runs it saw: None."""
        if node["kind"] == "virtual":
            return []
        devices = {n["device"] for n in self.subtree(node["id"]) if n.get("device")}
        if not devices:
            return None
        return [r for r in self.runs.get(node["root"], []) if r["device"] in devices]

    def selection(self, node: dict) -> dict | None:
        """sel.compute over every run of the node (memoised by the run ids: a station and its parts share one)."""
        rows = self.run_rows(node)
        if not rows or node["root"] not in self.tables:
            return None
        ids = tuple(sorted(r["run"] for r in rows))
        if ids not in self._selections:
            self._selections[ids] = sel.compute(ids, self.tables[node["root"]])
        return self._selections[ids]

    def entries(self, node: dict) -> list[dict]:
        """The selection's typed entities under the node, in the contract's tree order."""
        result = self.selection(node)
        if not result:
            return []
        order = {n["id"]: i for i, n in enumerate(self.subtree(node["id"]))}
        return sorted((x for x in result["nodes"] if x["node"] in order), key=lambda x: order[x["node"]])


def load(site) -> Domain:
    cached = getattr(site, "_domain_v3", None)
    if cached is not None:
        return cached
    folder = site.data / "domain"
    nodes = json.loads((folder / "deployments.json").read_text(encoding="utf-8"))["rows"]
    params = folder / "parameters.json"
    parameters = json.loads(params.read_text(encoding="utf-8"))["rows"] if params.is_file() else []
    have = {d.id: d for d in site.deployments}
    runs, tables = {}, {}
    for n in nodes:
        if n["parent"] is None and n["kind"] == "physical" and n["id"] in have:
            runs[n["id"]] = have[n["id"]].runs
            tables[n["id"]] = sel.load_tables(site.data, n["id"], nodes=[x for x in nodes if x["root"] == n["id"]])
    site._domain_v3 = Domain(nodes=nodes, results=inst.load_results(), runs=runs, tables=tables, parameters=parameters,
                             media=getattr(site, "media", None))
    return site._domain_v3


# --- small words --------------------------------------------------------------------------------------------------------------------

def num(value, digits: int = 3) -> str:
    return landing.num(value, digits) if value is not None else "—"


def with_unit(value, unit: str) -> str:
    if value is None:
        return "—"
    if unit.startswith("×"):
        return f"{num(value)}{unit}"
    return f"{num(value)} {unit}".strip()


def target_words(text: str) -> str:
    return (text or "").replace("<=", "≤").replace(">=", "≥")


def kind_chip(kind: str) -> str:
    return ui_shared.chip(kind, KIND_TONE.get(kind, ""), dm.DEPLOYMENT_KINDS.get(kind, ""))


def tag_chips(tags) -> str:
    return " ".join(ui_shared.chip(t, "tag", dm.TAGS.get(t, "")) for t in tags)


def level_word(node: dict) -> str:
    """What a node is, in words: its type's title, else its structural word."""
    if node.get("entity_type"):
        return dm.TYPES[node["entity_type"]].title
    return (node.get("structural") or "part").replace("_", " ")


def label_of(node: dict) -> str:
    """A node's name where several sit side by side: a station is its device ("CAN 11"), a station's part is its device and its own
    title ("CAN 11 · gearbox: 10:1 planetary": two stations' parts read alike), anything else its title. Stored fields, never a cut title."""
    if node.get("structural") == "station" and node.get("device"):
        return node["device"]
    if node.get("device"):
        return f"{node['device']} · {node['title']}"
    return node["title"]


def type_link(type_id: str) -> str:
    t = dm.TYPES[type_id]
    return pages.a(f"/types/{t.legacy_cards[0]}/", t.title) if t.legacy_cards else e(t.title)


def node_link(node: dict, text: str | None = None) -> str:
    return pages.a(node_url(node["id"]), text or node["title"])


def fitted(doc: dict | None) -> dict[str, tuple[tuple[str, ...], str, str]]:
    """{v3 type: (model ids, basis, "<v2 card> <rung>")} an oracle example used, read from its committed result: on its first card ladder
    the selection rule's pick where sysid ran one (selected_rung), else each ladder's highest rung with an identified parameter, in ladder
    order (a v2 rung is a combination of v3 models, one per family: dm.legacy_models)."""
    out: dict = {}
    for i, lad in enumerate((doc or {}).get("card_ladders", [])):
        keys = [r["key"] for r in lad["rungs"] if r.get("identified")]
        if i == 0 and doc.get("selected_rung"):
            key, basis = doc["selected_rung"], "selected"
        elif keys:
            key, basis = keys[-1], "fitted"
        else:
            continue
        tid = dm.CARD_TYPE[lad["card"]]
        if tid in out:
            raise ValueError(f"{doc.get('example')}: two card ladders fit type {tid}")
        out[tid] = (tuple(dm.legacy_models(lad["card"], key)), basis, f"{lad['card']} {key}")
    return out


def headline(metrics: list[dict]) -> dict | None:
    """Of one metric's entries (one per model for a fidelity metric), the one shown first: the model that replayed the most of the runs,
    then by its name. WHY most runs and not a named model: the producer's labels are words, never parsed; the twin that replayed the most
    of the selection is the one its median speaks for."""
    valued = [m for m in metrics if m["value"] is not None]
    return sorted(valued, key=lambda m: (-m["n"], m["model"] or ""))[0] if valued else None


def gate_of(entry: dict, metric: str, model: str | None) -> dict | None:
    return next((g for g in entry["gates"] if g["metric"] == metric and g["model"] == model), None)


def verdict_chip(gate: dict | None) -> str:
    if not gate or gate["verdict"] not in ("pass", "fail"):
        return ""
    return f'<span class="s2r-v s2r-{gate["verdict"]}" title="{e(target_words(gate["target"]))} ({e(gate["acceptance"] or "no acceptance gate")})">{gate["verdict"]} {e(target_words(gate["target"]))}</span>'


LEVEL_CLASS = {"ok": "pass", "warning": "warn", "error": "fail", "unknown": "not_run"}


# --- the calm answer --------------------------------------------------------------------------------------------------------------

def servo_like(entries: list[dict]) -> list[dict]:
    """The entities whose type computes coverage from runs (the integrated servo today): the ones a station-level answer speaks for."""
    return [x for x in entries if dm.TYPES[x["entity_type"]].coverage.from_runs]


def fidelity_head(entry: dict) -> tuple[dict | None, dict | None]:
    """(the headline entry of the type's pinned fidelity metric, its gate) for one entity."""
    pinned = [m.id for m in dm.pinned(entry["entity_type"]) if m.family == "fidelity"]
    for mid in pinned:
        head = headline([m for m in entry["metrics"] if m["metric"] == mid])
        if head:
            return head, gate_of(entry, mid, head["model"])
    return None, None


def answer(d: Domain, node: dict) -> str:
    """One calm sentence or three: what the node is and how close its twins are, before any detail (plain text)."""
    root = d.by_id[node["root"]]
    if node["kind"] == "virtual":
        doc = d.results.get(node["root"]) or {}
        if node["parent"] is None and doc:
            v = doc["verdict"]
            gated = [m for m in doc["metrics"] if m.get("gated")]
            return (f"{'Passes' if v['status'] == 'pass' else 'Fails'} the system-ID oracle: {v['parameters_pass']} of {v['parameters']} hidden values "
                    f"recovered within tolerance, and {v['metrics_pass']} of {v['metrics']} held-out errors improved by the factor each needs "
                    f"(best {num(max((m['factor'] for m in gated), default=None))}× better). It keeps no runs: sysid simulates them and keeps the results.")
        mine = {n["id"] for n in d.subtree(node["id"])}
        graded = [r for r in d.parameters if r["deployment"] == node["root"] and r["node"] in mine and r.get("pass") is not None]
        held = f"{len(graded)} of its values are graded by the oracle, {sum(1 for r in graded if r['pass'])} within tolerance" if graded else "the oracle grades none of its values"
        return f"{level_word(node)} in {root['title']}, a virtual deployment: {held}. It keeps no runs."
    rows = d.run_rows(node)
    if rows is None:
        seen = [label_of(d.by_id[s]) for s in node.get("sees") or [] if s in d.by_id]
        return (f"{level_word(node)} on {root['title']}" + (f", watching {', '.join(seen)}" if seen else "")
                + ". No run records which camera filmed it, so its runs are not known here.")
    if not rows:
        return f"{level_word(node)} on {root['title']}. No runs recorded yet."
    entries = d.entries(node)
    servos = servo_like(entries)
    n_runs = f"{len(rows):,} {'run' if len(rows) == 1 else 'runs'}"
    if node.get("device") and node.get("structural") != "station" and node.get("entity_type") and not servo_like([x for x in entries if x["node"] == node["id"]]):
        station = next((p for p in d.path(node["id"]) if p.get("structural") == "station"), None)
        mine = next((x for x in entries if x["node"] == node["id"]), None)
        valued = [m for m in (mine or {}).get("metrics", []) if m["pinned"] and m["value"] is not None]
        said = ("; ".join(f"{m['title']} {with_unit(m['value'], m['unit'])}" for m in valued) + ".") if valued else \
            f"None of its pinned metrics ({level_word(node)}) has a value yet: no producer writes them per run."
        return f"Part of {station['title'] if station else root['title']}, over its {n_runs}. {said}"
    if len(servos) == 1:
        x = servos[0]
        parts = [f"{n_runs}."]
        perf = [m for m in x["metrics"] if m["pinned"] and m["family"] == "performance" and m["value"] is not None]
        for m in perf:
            parts.append(f"{m['title']} {with_unit(m['value'], m['unit'])}, the {m['aggregate']} of {m['n']:,} runs.")
        head, gate = fidelity_head(x)
        if head:
            judged = f"{'within' if gate and gate['verdict'] == 'pass' else 'outside'} its gate ({target_words(gate['target'])})" if gate and gate["verdict"] in ("pass", "fail") else "no gate"
            parts.append(f"{head['title']}: {head['model']} {with_unit(head['value'], head['unit'])}, {judged}, the {head['aggregate']} of {head['n']:,} runs.")
        c = x["coverage"]
        if c.get("pct") is not None:
            parts.append(f"Coverage {num(c['pct'], 4)} % of its {c['reachable']:,} reachable cells"
                         + (f" ({'meets' if c['verdict'] == 'pass' else 'below'} the {c['gate_pct']:g} % gate)." if c.get("gate_pct") is not None else "."))
        return " ".join(parts)
    if servos:
        twinned = sum(1 for x in servos if (fidelity_head(x)[1] or {}).get("verdict") == "pass")
        covered = sum(1 for x in servos if x["coverage"].get("verdict") == "pass")
        target = next((target_words(g["target"]) for x in servos for g in [fidelity_head(x)[1]] if g), "its gate")
        word = "stations" if all(d.by_id[x["node"]].get("structural") == "station" for x in servos) else "joints"
        return (f"{n_runs} on {len(servos)} {word}. The model that replayed the most of each one's runs is within its gate ({target}) on {twinned} "
                f"of {len(servos)}; their coverage meets its gate on {covered} of {len(servos)}.")
    return f"{n_runs}. No entity under it computes a metric from runs yet."


# --- the index -----------------------------------------------------------------------------------------------------------------------

def card_line(d: Domain, node: dict) -> str:
    """A card's one line under its title and chips: what it is and how much of it there is."""
    parts = len(d.subtree(node["id"])) - 1
    rows = d.run_rows(node)
    if node["kind"] == "virtual":
        doc = d.results.get(node["id"]) or {}
        v = doc.get("verdict") or {}
        oracle = f" · oracle {v.get('parameters_pass')}/{v.get('parameters')} recovered" if v else ""
        return f"{node.get('machine') or ''} · {plural(parts, 'part')}{oracle}".lstrip(" ·")
    return f"{node.get('machine') or ''} · {plural(parts, 'part')} · {plural(len(rows or []), 'run')}".lstrip(" ·")


def card_rows(d: Domain) -> list[dict]:
    out = []
    for n in d.roots():
        sub = d.subtree(n["id"])
        rows = d.run_rows(n)
        out.append({"id": n["id"], "title": n["title"], "kind": n["kind"], "tags": list(n["tags"]), "url": node_url(n["id"]),
                    "image": d.media.scene_url(n["id"]) if d.media else None, "what": card_line(d, n), "parts": len(sub) - 1,
                    "runs": None if rows is None else len(rows),
                    "types": [dm.TYPES[t].title for t in dm.TYPE_ORDER if any(x["entity_type"] == t for x in sub)],
                    "where": n.get("where"), "summary": n.get("summary")})
    return out


def cards_dataset(d: Domain) -> dict:
    """data/deployment-cards.json: the contract's deployments (parent null) as data-ui's runtime shape, each with its page and render."""
    kinds = "; ".join(f"{k}: {v}" for k, v in dm.DEPLOYMENT_KINDS.items())
    tags = "; ".join(f"{k}: {v}" for k, v in dm.TAGS.items())
    return {"id": "deployments", "title": "Deployments", "titleProperty": "title", "linkProperty": "url", "imageProperty": "image",
            "source": "site/deployments_pages.py over data/domain/deployments.json (type_cards/instances.py) and the media index",
            "properties": {"title": {"type": "text", "label": "Deployment"},
                           "kind": {"type": "text", "label": "Kind", "note": kinds, "colors": KIND_SLOT},
                           # WHY muted: blue and orange are real and sim here (the kind's badge), green and red pass and fail; a tag is a word
                           "tags": {"type": "list", "label": "Tags", "note": tags, "colors": {t: 0 for t in dm.TAGS}},
                           "what": {"type": "text", "label": "What"}, "parts": {"type": "number", "label": "Parts"},
                           "runs": {"type": "number", "label": "Runs", "note": "the runs whose device is under it; a virtual deployment keeps none"},
                           "types": {"type": "list", "label": "Types in it"}, "where": {"type": "text", "label": "Where"},
                           "summary": {"type": "text", "label": "Summary"}, "url": {"type": "text", "label": "Page"},
                           "image": {"type": "text", "label": "Render"}},
            "rows": card_rows(d)}


def index_base() -> dict:
    """views/deployments.base: the rail (kind, then tags), the cards with the render on top, and the same rows as a table."""
    kinds = "; ".join(f"**{k}**: {v}" for k, v in dm.DEPLOYMENT_KINDS.items())
    return {
        "data": f"/data/{CARDS}",
        "facets": [{"as": "current", "label": "Your filters"},
                   {"property": "kind", "label": "Kind", "info": f"What a deployment is. {kinds}"},
                   {"property": "tags", "label": "Tags", "info": "Declared (oracle example) or derived from the types in its tree (uses camera, uses servo, …)"}],
        "properties": {"title": {"displayName": "Deployment"}, "kind": {"displayName": "Kind"}, "tags": {"displayName": "Tags"},
                       "what": {"displayName": "What"}, "parts": {"displayName": "Parts"}, "runs": {"displayName": "Runs"},
                       "types": {"displayName": "Types in it"}, "where": {"displayName": "Where"}},
        "views": [
            {"type": "cards", "name": "Deployments", "image": "image", "imageFit": "cover", "imageAspectRatio": 0.625, "cardSize": 250,
             "order": ["title", "kind", "tags", "what"], "display": {"kind": "badge"}, "open": {"mode": "link", "url": "url"},
             "sort": [{"property": "kind", "direction": "ASC"}]},
            {"type": "table", "name": "Table", "order": ["title", "kind", "tags", "parts", "runs", "types", "where"],
             "open": {"mode": "link", "url": "url"}, "sort": [{"property": "kind", "direction": "ASC"}]},
        ],
    }


def node_runs_base() -> dict:
    """views/deployment-node-runs.base: one node's runs, newest first. Its scope is data, never a filter the reader clears (as the station
    pages' are): `{deployment}`, `{scope}` (a runs.json column: node_<depth> for a level of the deployment's tree, device for a part)
    and `{node}` (its value) come from the mount's URL query (static/sim2real.js fills them)."""
    order = ["title", "device", "started", "kind", "excitation", "environment", "config", "tracking_mrad", "best_model", "verdict"]
    return {"data": "/data/{deployment}/runs.json",
            "properties": {"title": {"displayName": "Run"}, "device": {"displayName": "Station"}, "started": {"displayName": "Started"},
                           "kind": {"displayName": "Kind"}, "excitation": {"displayName": "Excitation"}, "environment": {"displayName": "Environment"},
                           "config": {"displayName": "Config"}, "tracking_mrad": {"displayName": "Real vs target"},
                           "best_model": {"displayName": "Closest model"}, "verdict": {"displayName": "Twinned?"}},
            "style": json.loads(json.dumps(views.build_pages.STYLE)),
            "datasets": {"runs": {"data": "/data/{deployment}/runs.json", "label": "Runs", "filters": '{scope} == "{node}"'}},
            "views": [{"type": "table", "name": "Runs", "from": "runs", "open": {"mode": "link", "url": "url"}, "order": order,
                       "columnSize": {"title": 360, "started": 150}, "sort": [{"property": "started", "direction": "DESC"}]}],
            "layout": {"panels": [{"view": "Runs", "w": 12, "h": 6, "title": "Runs · newest first", "toolbar": "compact"}]}}


def base_text(doc: dict, what: str) -> str:
    text = (f"# sim2real · {what}\n# Written by site/deployments_pages.py (do not edit by hand); data by type_cards/instances.py and "
            f"site/build.py.\n") + views.data_ui_base.dumps(doc)
    assert views.data_ui_base.loads(text) == json.loads(json.dumps(doc)), f"{what}: the .base does not round-trip"
    return text


def index_body(d: Domain) -> str:
    roots = d.roots()
    items = []
    for row in card_rows(d):
        img = (f'<img src="{e(row["image"])}" alt="" width="1280" height="800" loading="lazy" decoding="async">' if row["image"] else "")
        items.append(f'<li class="s2r-dcard" data-deployment="{e(row["id"])}" data-kind="{e(row["kind"])}" data-tags="{e("|".join(row["tags"]))}">'
                     f'<a href="{e(row["url"])}">{img}<b>{e(row["title"])}</b></a> {kind_chip(row["kind"])} {tag_chips(row["tags"])}'
                     f'<small>{e(row["what"])}</small></li>')
    fallback = f'<ul class="s2r-dcards">{"".join(items)}</ul>'
    n_virtual = sum(1 for n in roots if n["kind"] == "virtual")
    return f"""<div class="s2r-dindex">
<h1>Deployments <span class="n">({len(roots)})</span></h1>
<p class="lede">Every machine we do sim to real on: {plural(len(roots) - n_virtual, "physical deployment")}, hardware whose runs are recordings, and
{plural(n_virtual, "virtual deployment")}, the system-ID oracle's examples, where a robot description and a simulator play the hardware. Every part of
a deployment is a deployment of its own: open one for its tree. Filter by kind and tags.</p>
{views_element(VIEWS_ID, "/" + INDEX_BASE, "Deployments", fallback, frame="page", attrs='toolbar="bar"')}
</div>"""


# --- a deployment's page ---------------------------------------------------------------------------------------------------------------

def header(d: Domain, node: dict) -> str:
    root = d.by_id[node["root"]]
    media = d.media
    shot = landing.site_media.figure(media, node["id"], cls="s2r-shot s2r-hero", eager=True) if node["parent"] is None else ""
    scene = media.scenes.get(node["id"]) if (media and node["parent"] is None) else None
    parent = d.by_id.get(node["parent"])
    within = "" if parent is None else f' · part of {node_link(parent, label_of(parent))}' + ("" if parent is root else f' on {node_link(root)}')
    kind = f'{kind_chip(node["kind"])} {ui_shared.chip(level_word(node))}{within}'
    what = f'<p class="s2r-what"><b>What you\'re looking at:</b> {e(scene["what"])}</p>' if scene else ""
    text = f"""<h1>{e(node["title"])}</h1>
<p class="sub s2r-dsub">{kind}</p>
{f'<p class="s2r-dtags">{tag_chips(node["tags"])}</p>' if node["tags"] else ""}
<p class="s2r-answer">{e(answer(d, node))}</p>
{what}"""
    return f'<div class="s2r-headshot">{shot}<div>{text}</div></div>' if shot else text


def link_3d(d: Domain, node: dict) -> str:
    """A station's link in 3D: the media lane's joint-3d component (site/components.py, scoped to the joint) on the newest run a model
    replayed, else its newest run with link poses. WHY a component and not a render (Zach, 2026-11-07: "we can basically always have a 3D
    view"): a station has no scene of its own, and its runs' link poses and its link model are the media lane's (tools/build_media.py)."""
    media = d.media
    if not media or node["kind"] != "physical" or node.get("structural") != "station":
        return ""
    rows = sorted((r for r in d.run_rows(node) or [] if (media.runs.get(r["run"]) or {}).get("links")), key=lambda r: r["started"], reverse=True)
    run = next((r for r in rows if r.get("models")), rows[0] if rows else None)
    if run is None:
        return ""
    key = adapter.station_key(node["device"])
    entity = components.Entity("joint", node["device"], node["root"], key)
    what = components.joint_3d().what
    which = "its newest run a model replayed" if run.get("models") else "its newest run (no model replayed one)"
    mount = components.mount("joint-3d", entity, run["run"], glb=media.glb_url(node["root"], key) or "", label=node["device"] + ": its link in 3D")
    return (f'<section id="link-3d" aria-labelledby="l3-h"><h2 id="l3-h">Its link in 3D</h2>'
            f'<p class="lede">{e(what[0].upper() + what[1:])}, on {which}: {pages.a(adapter.run_url(run), run["title"])} '
            f'<small class="mut">({e(run.get("kind") or "")}, {e(pages.when(run.get("started")))})</small>.</p>{mount}</section>')


def sub_deployments(d: Domain, node: dict) -> str:
    kids = d.kids.get(node["id"], [])
    if not kids:
        root = d.by_id[node["root"]]
        return (f'<section id="sub-deployments" aria-labelledby="sub-h"><h2 id="sub-h">Sub-deployments</h2>'
                f'<p class="mut">None: it is a leaf of {e(root["title"])}\'s tree.</p></section>')
    items = []
    for k in kids:
        rows = d.run_rows(k)
        parts = len(d.subtree(k["id"])) - 1
        bits = [level_word(k)]
        if parts:
            bits.append(plural(parts, "part"))
        if rows is not None and k["kind"] == "physical":
            bits.append(plural(len(rows), "run"))
        items.append(f'<li><a class="s2r-subdep" data-node="{e(k["id"])}" href="{e(node_url(k["id"]))}"><span class="s2r-ei">'
                     f'{ui_shared.icon(ui_shared.icon_word(k))}</span><span class="t" title="{e(k["title"])}">{e(k["title"])}</span>'
                     f'<small>{e(" · ".join(bits))}</small></a></li>')
    return (f'<section id="sub-deployments" aria-labelledby="sub-h"><h2 id="sub-h">Sub-deployments <span class="n">({len(kids)})</span></h2>'
            f'<p class="mut">Each is a deployment of its own: open one for its page.</p><ul class="s2r-subs">{"".join(items)}</ul></section>')


def coverage_section(d: Domain, node: dict) -> str:
    rows = d.run_rows(node)
    head = '<section id="coverage" aria-labelledby="cov-h"><h2 id="cov-h">Coverage'
    if node["kind"] == "virtual":
        doc = d.results.get(node["root"]) or {}
        planned = (f'<p>Planned by the oracle\'s schedule, not runs: {landing.schedule_line(doc)}</p>{landing.coverage_line(doc)}'
                   if node["parent"] is None and doc else "")
        return (f'{head}</h2><p class="mut">No runs are kept for a virtual deployment, so none is computed over runs.</p>{planned}</section>')
    if rows is None:
        return f'{head}</h2><p class="mut">Not computed: its runs are not known.</p></section>'
    entries = d.entries(node)
    if not rows:
        return f'{head}</h2><p class="mut">No runs yet.</p></section>'
    bars, quiet = [], Counter()
    for x in entries:
        c = x["coverage"]
        if not dm.TYPES[x["entity_type"]].coverage.from_runs:
            quiet[x["entity_type"]] += 1
            continue
        n = d.by_id[x["node"]]
        gate = c.get("gate_pct")
        name = node_link(n, label_of(n))
        if c.get("pct") is None:
            # WHY shown, empty (unknown stays unknown): the type computes coverage from runs, but not for this joint, and it says why
            bars.append(f'<div class="s2r-cov" data-entity="{e(x["node"])}" data-coverage="" data-visited="" data-reachable="" data-gate="{"" if gate is None else gate}">'
                        f'{name}<span class="s2r-bar" role="img" aria-label="not known"></span><span class="s2r-covn mut">not known: {e(c.get("why") or "")}</span></div>')
            continue
        tick = f'<i style="left:{gate:g}%" title="the type card\'s gate, {gate:g} %"></i>' if gate is not None else ""
        verdict = pages.chip("pass" if c["verdict"] == "pass" else "fail", f"{'meets' if c['verdict'] == 'pass' else 'below'} {gate:g} %") if gate is not None else ""
        bars.append(f'<div class="s2r-cov" data-entity="{e(x["node"])}" data-coverage="{c["pct"]}" data-visited="{c["visited"]}" data-reachable="{c["reachable"]}"'
                    f' data-gate="{"" if gate is None else gate}">{name}'
                    f'<span class="s2r-bar" role="img" aria-label="{num(c["pct"], 4)} % of {c["reachable"]:,} reachable cells"><span style="width:{min(100.0, c["pct"])}%"></span>{tick}</span>'
                    f'<span class="s2r-covn"><b>{num(c["pct"], 4)} %</b> · {c["visited"]:,} of {c["reachable"]:,} cells · {c["samples"]:,} samples {verdict}</span></div>')
    rule = next((x["coverage"]["rule"] for x in entries if dm.TYPES[x["entity_type"]].coverage.from_runs), "")
    why = next((x["coverage"].get("why") for x in entries if not dm.TYPES[x["entity_type"]].coverage.from_runs and x["coverage"].get("why")), "")
    quiet_line = (f'<p class="mut">Not computed from runs for {e(", ".join(f"{dm.TYPES[t].title} ({k})" for t, k in quiet.items()))}: {e(why)}.</p>'
                  if quiet else "")
    lede = (f'<p class="lede">The share of each joint\'s reachable (q, qd, qdd) cells its runs visited: the type card\'s own coverage function over every run '
            f'(sel.compute). The tick is the card\'s gate.</p>' if bars else "")
    detail = f'<details class="s2r-more"><summary>The rule</summary><p>{e(rule)}.</p></details>' if rule else ""
    return f'{head} <span class="n">· over all {len(rows):,} of its runs</span></h2>{lede}<div class="s2r-covs">{"".join(bars)}</div>{quiet_line}{detail}</section>'


def metric_cell(x: dict, mid: str) -> str:
    spec = next(m for m in dm.pinned(x["entity_type"]) if m.id == mid)
    entries = [m for m in x["metrics"] if m["metric"] == mid]
    head = headline(entries)
    if head is None:
        why = next((m["why"] for m in entries if m.get("why")), "no value from the selected runs")
        return f'<td data-entity="{e(x["node"])}" data-metric="{e(mid)}" data-value="" title="{e(why)}"><span class="mut">—</span></td>'
    more = sum(1 for m in entries if m["value"] is not None) - 1
    who = (f"{e(head['model'])} · {head['n']:,} runs" + (f" · +{more} more" if more > 0 else "")) if head["model"] else f"{head['aggregate']} of {head['n']:,} runs"
    return (f'<td data-entity="{e(x["node"])}" data-metric="{e(mid)}" data-value="{head["value"]!r}" data-model="{e(head["model"] or "")}" data-n="{head["n"]}">'
            f'<b>{e(with_unit(head["value"], spec.unit))}</b> {verdict_chip(gate_of(x, mid, head["model"]))}<small>{who}</small></td>')


def metrics_section(d: Domain, node: dict) -> str:
    rows = d.run_rows(node)
    head = '<section id="metrics" aria-labelledby="met-h"><h2 id="met-h">Pinned metrics'
    if node["kind"] == "virtual":
        doc = d.results.get(node["root"]) or {}
        oracle = (f'<p>The oracle\'s own held-out errors, before → after its fit:</p>{landing.metric_rows(doc)}' if node["parent"] is None and doc else "")
        tid = node.get("entity_type")
        pinned = (f'<p class="mut">Pinned for its type ({e(dm.TYPES[tid].title)}): {e(", ".join(m.title for m in dm.pinned(tid)))}.</p>' if tid else "")
        return f'{head}</h2><p class="mut">None is computed over runs: a virtual deployment keeps no runs.</p>{oracle}{pinned}</section>'
    if rows is None:
        return f'{head}</h2><p class="mut">Not computed: its runs are not known.</p></section>'
    if not rows:
        return f'{head}</h2><p class="mut">No runs yet.</p></section>'
    entries = d.entries(node)
    tables, quiet = [], []
    for tid in dm.TYPE_ORDER:
        ents = [x for x in entries if x["entity_type"] == tid]
        if not ents:
            continue
        pinned = dm.pinned(tid)
        if not any(m["value"] is not None for x in ents for m in x["metrics"] if m["pinned"]):
            quiet.append((tid, len(ents)))
            continue
        heads = "".join(f'<th scope="col" title="{e(m.id)}">{e(m.title)}</th>' for m in pinned)
        body = "".join(f'<tr data-entity="{e(x["node"])}"><th scope="row">{node_link(d.by_id[x["node"]], label_of(d.by_id[x["node"]]))}</th>'
                       f'{"".join(metric_cell(x, m.id) for m in pinned)}</tr>' for x in ents)
        tables.append(f'<h3>{type_link(tid)} <span class="n">({len(ents)})</span></h3>'
                      f'<div class="s2r-scroll"><table class="s2r-table s2r-pins"><thead><tr><th scope="col">{e(dm.TYPES[tid].title)}</th>{heads}</tr></thead>'
                      f'<tbody>{body}</tbody></table></div>')
    quiet_line = (f'<p class="s2r-novalue" data-types="{e(" ".join(t for t, _k in quiet))}">No pinned metric has a value yet for '
                  f'{e(", ".join(f"{dm.TYPES[t].title} ({k})" for t, k in quiet))}: no producer writes them per run (each type card says how they are measured).</p>'
                  if quiet else "")
    lede = ('<p class="lede">The metrics each type pins (type_cards), each the median over the runs (sel.compute: one value per run, then data-ui\'s '
            'own summary); a fidelity metric shows the model that replayed the most of them. A chip is its gate on that median.</p>' if tables else "")
    return (f'{head} <span class="n">· over all {len(rows):,} of its runs</span></h2>{lede}{"".join(tables)}{quiet_line}'
            f'{every_metric(d, entries)}</section>')


def every_metric(d: Domain, entries: list[dict]) -> str:
    rows = []
    for x in entries:
        n = d.by_id[x["node"]]
        for m in x["metrics"]:
            g = gate_of(x, m["metric"], m["model"])
            dx = next((r for r in x["diagnostics"] if r["metric"] == m["metric"] and r["model"] == m["model"]), None)
            level = (f'<span class="s2r-v s2r-{LEVEL_CLASS.get(dx["level"], "not_run")}">{e(dx["level"])}</span>' if dx else "")
            gate = (f'{pages.chip(g["verdict"], g["verdict"].replace("_", " "))} <small>{e(target_words(g["target"]))}</small>' if g else "")
            span = f"{num(m['low'])} – {num(m['high'])}" if m.get("low") is not None else ""
            rows.append([node_link(n, label_of(n)), e(m["title"]) + (" <small>pinned</small>" if m["pinned"] else ""), e(m["model"] or ""),
                         e(with_unit(m["value"], m["unit"])), e(span), str(m["n"]), level, gate, f'<small>{e(m.get("why") or "")}</small>'])
    table = pages.table(["Entity", "Metric", "Model", "Median", "Low – high", "Runs", "Diagnostic", "Gate", "Why not"], rows,
                        caption="Every metric of every entity under it over its runs (sel.compute); a diagnostic is the metric against its warn and error "
                                "limits, a gate its target on the selection's median (bam_rack_twin's acceptance verdicts stay on the Gates tabs)")
    return f'<details class="s2r-more"><summary>Every metric, model, diagnostic and gate ({len(rows)})</summary>{table}</details>'


def model_link(tid: str, mid: str) -> str:
    """A model id linking to its row on its type's ladder (/models/<type>/#<model id>, site/models_pages.py)."""
    return f'<a data-model-link="{e(mid)}" href="/models/{e(tid)}/#{e(mid)}"><code>{e(mid)}</code></a>'


def label_words(node: dict, tid: str, label: str, n: int) -> str:
    """A producer's label with its run count and, where type_cards maps it (inst.label_model), the ladder model it is, linked."""
    m = inst.label_model(node["root"], label)
    ladder = m.model if m and m.type == tid else ""
    to = f' <span class="mut">→</span> {model_link(tid, ladder)}' if ladder else ""
    return f'<span data-label="{e(label)}" data-ladder="{e(ladder)}">{e(label)} <small>({n:,})</small>{to}</span>'


def models_section(d: Domain, node: dict) -> str:
    sub = d.subtree(node["id"])
    here = Counter(n["entity_type"] for n in sub if n["entity_type"])
    fits = fitted(d.results.get(node["root"])) if node["kind"] == "virtual" else {}
    types = [t for t in dm.TYPE_ORDER if t in here or (node["parent"] is None and t in fits)]
    replayed: dict = {}
    for x in d.entries(node):
        for m in x["metrics"]:
            if m["family"] == "fidelity" and m["model"] and m["value"] is not None:
                replayed.setdefault(x["entity_type"], Counter())[m["model"]] += m["n"]
    rows = []
    for tid in types:
        current = dm.current_models(tid)
        used, basis, rung = fits.get(tid, ((), "", ""))
        reps = replayed.get(tid, Counter())
        # WHY links (w2c, 2026-11-07, the brief: "models used here" links to the model's ladder row): each id opens its row on /models/<type>/
        cur = " ".join(f'{model_link(tid, m.id)} <small>{e(m.title)}</small>' for m in current)
        if used:
            use = " ".join(f'{model_link(tid, i)} <small>{e(dm.model(tid, i).title)}</small>' for i in used) + f'<br><small class="mut">{e(BASIS_WORDS[basis])} (v2 rung {e(rung)})</small>'
        elif reps:
            use = ('<small class="mut">the producer\'s models that replayed its runs, and the ladder model each is:</small> '
                   + ", ".join(label_words(node, tid, k, v) for k, v in sorted(reps.items(), key=lambda kv: (-kv[1], kv[0]))))
        else:
            use = '<span class="mut">— nothing fitted or replayed for it here</span>'
        rows.append(f'<tr data-type="{e(tid)}" data-current="{e(" ".join(m.id for m in current))}" data-used="{e(" ".join(used))}" data-basis="{e(basis)}"'
                    f' data-replayed="{e("|".join(sorted(reps)))}"><th scope="row"><span class="s2r-ei">{ui_shared.icon(tid)}</span> {type_link(tid)}</th>'
                    f'<td>{here.get(tid, 0) or "—"}</td><td>{cur}</td><td>{use}</td></tr>')
    if not rows:
        return ('<section id="models" aria-labelledby="mod-h"><h2 id="mod-h">Models, per entity type</h2>'
                f'<p class="mut">No typed part under it: a {e(level_word(node))} holds no model of its own.</p></section>')
    used_words = ("the oracle's fit" if node["kind"] == "virtual" else "the producer's models that replayed its runs (their labels as the producer wrote them, "
                  "each with the ladder model type_cards maps it to)")
    return f"""<section id="models" aria-labelledby="mod-h"><h2 id="mod-h">Models, per entity type</h2>
<p class="lede">Each type's model ladder (type_cards, domain v3): the model current on it, and the ones used here, {used_words}.</p>
<div class="s2r-scroll"><table class="s2r-table s2r-mods"><thead><tr><th scope="col">Entity type</th><th scope="col">Here</th><th scope="col">Current on its ladder</th><th scope="col">Used here</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div></section>"""


def runs_scope(node: dict) -> tuple[str, str]:
    """The runs.json column and value that keep exactly a node's runs: a level of the deployment's tree is its node_<depth> column (the
    tree's path ids, site/deploy_tree.py), a part its station's device."""
    if node.get("structural") in ("deployment", "adapter", "station"):
        return f"node_{node['depth']}", node["id"]
    return "device", node["device"]


def runs_section(d: Domain, node: dict) -> str:
    rows = d.run_rows(node)
    if node["kind"] == "virtual":
        doc = d.results.get(node["root"]) or {}
        sched = f" Its schedule: {e(landing.schedule_line(doc))}." if doc and node["parent"] is None else ""
        return (f'<section id="runs" data-runs="0" aria-labelledby="runs-h"><h2 id="runs-h">Runs</h2><p class="mut">None kept: sysid simulates the runs of '
                f'its schedule and keeps their results (sysid/results/{e(node["root"])}.json), not the runs.{sched} '
                f'{pages.a(landing.url(node["root"]), "The oracle example")} has every number.</p></section>')
    if rows is None:
        seen = [d.by_id[s] for s in node.get("sees") or [] if s in d.by_id]
        sees = (" It watches " + ", ".join(node_link(s, label_of(s)) for s in seen) + ".") if seen else ""
        return (f'<section id="runs" data-runs="" aria-labelledby="runs-h"><h2 id="runs-h">Runs</h2><p class="mut">Not known: no run records which camera '
                f'filmed it.{sees}</p></section>')
    if not rows:
        return '<section id="runs" data-runs="0" aria-labelledby="runs-h"><h2 id="runs-h">Runs</h2><p class="mut">No runs yet.</p></section>'
    scope, value = runs_scope(node)
    src = "/" + RUNS_BASE + "?" + urlencode({"deployment": node["root"], "scope": scope, "node": value})
    excitation = Counter(r.get("excitation") or "unknown" for r in rows)
    full = sum(1 for r in rows if r.get("config") == deploy_tree.FULL)
    tags = " · ".join(f"{k} {v:,}" for k, v in excitation.most_common())
    picks = "&".join(f"node_{p['depth']}={quote(p['id'], safe='')}" for p in d.path(node["id"])
                     if p.get("structural") in ("adapter", "station") and p["depth"])
    rail = pages.a(f"/{node['root']}/" + (f"?{picks}" if picks else ""), f"filter them on {d.by_id[node['root']]['title']}'s Runs tab")
    return (f'<section id="runs" data-runs="{len(rows)}" aria-labelledby="runs-h"><h2 id="runs-h">Runs <span class="n">({len(rows):,})</span></h2>'
            f'<p class="s2r-runtags">By excitation: {e(tags)} · full config snapshot on {full:,} of {len(rows):,} · {rail}</p>'
            f'{pages.dashboard(src, node["title"] + ": runs")}</section>')


def elsewhere(d: Domain, node: dict) -> str:
    links = []
    if node["kind"] == "virtual":
        links.append(pages.a(landing.url(node["root"]), "The oracle example: every parameter, its schedule and the drift demos"))
    elif node.get("page") and node["parent"] is None:
        links.append(pages.a(node["page"], f"{node['title']}'s record page: its gates T1-T11, why each fails, coverage plots and evidence"))
    elif node.get("page") and node.get("structural") == "station":
        links.append(pages.a(node["page"], f"{label_of(node)}'s station page: its gates, why it fails, its schedule"))
    if node.get("entity_type"):
        links.append(f"{type_link(node['entity_type'])}: the type card, its metrics and model ladder")
    rows = d.run_rows(node)
    if rows:  # the metrics lane (2026-11-07): its runs on the metrics page, its stations picked in the rail (data-ui's readable URL)
        devices = sorted({r["device"] for r in rows}, key=lambda x: (len(x), x))
        pick = "" if node["parent"] is None else "?" + urlencode({"device": ",".join(devices)})
        links.append(pages.a(f"/metrics/{node['root']}/{pick}", "Its metrics, diagnostics and coverage over any selection of its runs"))
    return f'<p class="s2r-else">{" · ".join(links)}</p>' if links else ""


def node_body(d: Domain, node: dict) -> str:
    return (f'<article class="s2r-dep" data-node="{e(node["id"])}" data-kind="{e(node["kind"])}" data-root="{e(node["root"])}">'
            f'{header(d, node)}{link_3d(d, node)}{sub_deployments(d, node)}{coverage_section(d, node)}{metrics_section(d, node)}{models_section(d, node)}'
            f'{runs_section(d, node)}{elsewhere(d, node)}</article>')


def tree_aside(d: Domain, node: dict, counts: dict) -> str:
    return ui_shared.entity_tree(d.tree(node["root"]), node["id"], lambda n: node_url(n["id"]),
                                 count=lambda n: f"{counts[n['id']]:,}" if counts.get(n["id"]) else "")


def run_counts(d: Domain, root: str) -> dict:
    out = {}
    for n in d.tree(root):
        rows = d.run_rows(n)
        out[n["id"]] = len(rows) if rows else 0
    return out


# --- the site's files --------------------------------------------------------------------------------------------------------------

def write_data(data, site) -> int:
    """data/deployment-cards.json (site/build.py, beside search.json: the workbench's writer keeps out of data/). Returns its rows."""
    doc = cards_dataset(load(site))
    (data / CARDS).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return len(doc["rows"])


def files(site):
    """(path, text) of the index, its .base, the runs .base and one page per node of every deployment's tree."""
    import catalog as s2r  # noqa: PLC0415

    d = load(site)
    yield INDEX_BASE, base_text(index_base(), "the deployments index: the rail (kind, tags), the cards with their renders, the table")
    yield RUNS_BASE, base_text(node_runs_base(), "a deployment's runs, newest first, scoped to the node its URL names")
    roots = d.roots()
    yield "deployments/index.html", s2r.page(
        site, "Deployments: sim2real", URL, index_body(d), "deployments", aside=ui_shared.filter_bar(VIEWS_ID, "The filters need JavaScript; every deployment is listed on the right."),
        data_ui=True, extra_head=STYLES, trail=breadcrumb([s2r.ROOT_CRUMB, ("Deployments", URL)]),
        description=f"Every deployment, virtual and physical ({len(roots)}), filtered by kind and tags; every part of one a deployment of its own.")
    counts = {r["id"]: run_counts(d, r["id"]) for r in roots}
    for node in d.nodes:
        crumbs = [s2r.ROOT_CRUMB, ("Deployments", URL)] + [(p["title"], node_url(p["id"])) for p in d.path(node["id"])]
        body = node_body(d, node)
        yield f"deployments/{node['id']}/index.html", s2r.page(
            site, f"{node['title']}: sim2real", node_url(node["id"]), body, "deployment-node", aside=tree_aside(d, node, counts[node["root"]]),
            data_ui='class="s2r-dash' in body, extra_head=STYLES, trail=breadcrumb(crumbs, back=[URL]), description=answer(d, node)[:240])
