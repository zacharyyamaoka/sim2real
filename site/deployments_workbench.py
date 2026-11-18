"""/deployments/: the Deployments workbench. Every deployment; open one for its 3D and its typed component tree; any node of the tree shows
that level's data: performance first (real vs the target), then fidelity (real vs sim) and the five questions.

Obsidian's frame (Zach 2026-11-17, on proposal V1: "update it so it has the left toolbar sidebar like Obsidian. And then I think 3 primary
views could be the Scene View, the Sheet view and the Workbench-like view"): a 44 px ribbon at the far left (Deployments; Scene · Sheet ·
Workbench; then Runs), the typed tree in a collapsible, resizable left sidebar, a right inspector that folds. Three primary views share
one selection and one round through the URL: Scene (the 3D is the page, V3), Sheet (the nested table, round 0 · now · change side by
side, the 3D and the inspector docked, V2), Workbench (the tree and the node's page, V1); and Runs (every run of every round, each opening
its Rerun recording).

Zach (Daily Note 2026-11-17, "# What is required for me to actually get this working?"): "Sim2Real at the top level we seperate it into
DEPLOYMENTS. When I click into each deployment I should bring up the 3D viewer of that deployment AND the tree should be the typed
component tree. then If I click on any of the thingsin that tree than I can see the dat relevant to that level"; "A table like this I think
is cool ... nestedf table". And ("# Ok"): "Performance is what matters at the end of the day ... So performance is first and up center";
"Runs are the atomic unit ... drill into a particular run (rerun)".

The design is the AI pick from the proposal round (docs/proposals/2026-11-17-deployment-page/, reports/deployment-page-proposals-
2026-11-17.html), spliced: V1 Workbench's frame (tree | the node's page with tabs | Table view with a foldable inspector | 3D), V4's banner,
question columns and "What changed" mode, V2's round 0 · now · change columns, V3's pulled-apart servo; then re-ordered performance first.

What it reads, never a new number:
- sim2real.deployments_page (src/): the One Dof Test Rack's pendulum campaign scorecards -> its typed tree, every node's metrics per round,
  the five-question verdicts (sim2real.verdicts), round-by-round history, and every run of every round with its Rerun recording;
- the deployments (data/domain/deployments.json via site/deployments_pages.py's Domain): the list on the home view, each other deployment
  opening its existing page /deployments/<id>/;
- each deployment's W&B project (sim2real.deployments_page.wandb_links over app/registry.json): its "Open in W&B" button, the backdoor
  Zach asked for (Daily Note 2026-11-18: "Each deployment in the sim2real app should have a button to open within weights and biases");
- data_recorder.runlink (/home/bam/data_recorder): each recording registered (an additive write to its replay index) for its
  http://127.0.0.1:8771/f/<token>/<id> link, the always-on bam-replay-link launcher (bam_ws bam_trackio.replay_link) that opens the
  native Rerun viewer. WHY not the campaign's pendulum_rerun links (9461/9462): those servers live only while someone runs them.

Writes (site/build.py): data/deployments-workbench.json (the page's data), data/deployments-workbench-runs.json (every run, the table a
later W&B sync can log as it is), deployments/index.html, static/three-orbit-0.186.1.min.js (vendor/three). The page's code is
static/deployments-workbench.js and .css. The old filter-bar index of deployment cards moved to /deployments/all/ (deployments_pages.py).
Stdlib only.
"""

from __future__ import annotations

import datetime
import json
import sys

from catalog_workbench.html import breadcrumb, e

import adapter
import deployments_pages as dps

if str(adapter.REPO / "src") not in sys.path:
    # WHY this checkout's src first (as type_cards' shim does): the build runs `uv run --no-project`, sim2real is not installed
    sys.path.insert(0, str(adapter.REPO / "src"))

from sim2real import deployments_page as dpage  # noqa: E402
from sim2real import paths  # noqa: E402

URL = "/deployments/"
ALL_URL = dps.INDEX_URL
DATA = "deployments-workbench.json"
RUNS = "deployments-workbench-runs.json"
THREE = adapter.REPO / "vendor" / "three" / "three-orbit-0.186.1.min.js"
THREE_NAME = "three-orbit-0.186.1.min.js"
WORKBENCH = {dpage.DEPLOYMENT}  # the deployments the workbench opens itself; every other one opens its page


def runlink():
    """data_recorder.runlink (stdlib only), from its checkout; None when it is not on this machine."""
    src = paths.DATA_RECORDER / "src"
    if not (src / "data_recorder" / "runlink.py").is_file():
        return None
    if str(src) not in sys.path:
        sys.path.append(str(src))
    from data_recorder import runlink as rl  # noqa: PLC0415

    return rl


def replay_links(rows: list[dict]) -> dict:
    """Give every row whose recording exists its launcher link (replay_url; "" when the launcher is not installed). Each recording is
    registered once (data_recorder.runlink.register: an additive, atomic write to its index); one already registered is not rewritten."""
    rl = runlink()
    seen: dict[str, str | None] = {}
    registered, prefix = 0, None
    for row in rows:
        row["replay_url"] = None
        if not row.get("rrd") or rl is None:
            continue
        if row["rrd"] not in seen:
            key = rl.replay_id(row["rrd"])
            if prefix is None:
                # WHY one links() call: it registers on every call (a rewrite of the whole index); the launcher's URL is the same for
                # every id, so the first link gives the prefix and the rest only register when they are not yet in the index
                url = rl.links(row["rrd"])["replay_url"]
                prefix = url[: -len(key)] if url.endswith("/" + key) else ""
            elif rl.resolve(key) is None:
                rl.register(row["rrd"])
                registered += 1
            seen[row["rrd"]] = (prefix + key) if prefix else None
        row["replay_url"] = seen[row["rrd"]]
    return {"recordings": len(seen), "registered_now": registered, "launcher": bool(rl and prefix)}


def old_pages(d: dps.Domain) -> dict[str, str]:
    """A station's device ("CAN 11") -> its page in the deployment's recorded-runs tree (every session, older ones too)."""
    out = {}
    for n in d.tree(dpage.DEPLOYMENT):
        if n.get("structural") == "station" and n.get("device"):
            out[n["device"]] = dps.node_url(n["id"])
    return out


def page_data(site, now: str | None = None) -> tuple[dict, dict]:
    """(the page's data, the runs table). `now`: the scorecard the Now column reads (default the campaign's latest, latest_real.json)."""
    now = now or dpage.NOW_FILE
    d = dps.load(site)
    trees, missing, rows = {}, None, []
    try:
        trees[dpage.DEPLOYMENT] = dpage.build(now=now)
        rows = dpage.runs(now=now)
    except FileNotFoundError as error:
        missing = str(error)
    links = replay_links(rows) if rows else {"recordings": 0, "registered_now": 0, "launcher": False}
    wandb = dpage.wandb_links()  # each deployment's W&B project, from app/registry.json: its "Open in W&B" button (none: no button)
    deployments = []
    for row in dps.card_rows(d):
        tree = trees.get(row["id"])
        headline = None
        if tree:
            headline = {r["id"]: {"goal_met": r["goal_met"], "gates_passed": r["gates_passed"], "gates_total": r["gates_total"],
                                  "perf_gates": tree["nodes"][0]["performance"][r["id"]]["passed"], "perf_total": tree["nodes"][0]["performance"][r["id"]]["of"]}
                        for r in tree["rounds"]}
        doc = d.results.get(row["id"]) or d.scenarios.get(row["id"]) or {}
        deployments.append({"id": row["id"], "title": row["title"], "kind": row["kind"], "tags": row["tags"], "what": row["what"],
                            "summary": row.get("summary") or "", "where": row.get("where") or "", "image": row["image"], "page": row["url"],
                            "workbench": row["id"] in trees, "headline": headline, "wandb": wandb.get(row["id"]),
                            "oracle": (doc.get("verdict") or {}).get("status") if row["kind"] == "virtual" else None})
    media = getattr(site, "media", None)
    data = {"schema": "sim2real.deployments-workbench/1", "built_utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "built_by": "site/deployments_workbench.py over sim2real.deployments_page", "deployments": deployments, "all_url": ALL_URL,
            "trees": trees, "missing": missing, "runs_url": "/data/" + RUNS,
            "render": media.scene_url(dpage.DEPLOYMENT) if media else None, "old_pages": old_pages(d),
            "replay": {**links, "how": "the always-on bam-replay-link launcher on 127.0.0.1:8771 opens the native Rerun viewer (data-recorder view)"}}
    runs_doc = {"schema": "sim2real.deployment-runs/1", "deployment": dpage.DEPLOYMENT, "built_utc": data["built_utc"],
                "source": str(dpage.SCORECARDS), "note": "one row per play of every scored round; replay_url opens its Rerun recording "
                "through the bam-replay-link launcher (null: no recording yet). The table a W&B sync logs as it is.",
                "thresholds": trees[dpage.DEPLOYMENT]["thresholds"] if trees else None, "rows": rows}
    return data, runs_doc


def write_data(data_dir, site, now: str | None = None) -> dict:
    data, runs_doc = page_data(site, now)
    (data_dir / DATA).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    (data_dir / RUNS).write_text(json.dumps(runs_doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    tree = data["trees"].get(dpage.DEPLOYMENT)
    return {"nodes": sum(len(t["nodes"]) for t in data["trees"].values()), "runs": len(runs_doc["rows"]), "missing": data["missing"],
            "now": tree["rounds"][-1]["long"] if tree else None, "history_missing": tree["history_missing"] if tree else None, **data["replay"]}


# WHY an Obsidian frame (Zach 2026-11-17: "update it so it has the left toolbar sidebar like Obsidian ... 3 primary views could be the Scene
# View, the Sheet view and the Workbench-like view"): Obsidian's geometry, read from like_obsidian_md_viewer's captured obsidian-app.css
# (.workspace-ribbon 44 px, its 40 px header cell holding the sidebar toggle, ribbon padding 8/4/12 px, 4 px gap, 18 px icons at 1.75
# stroke, the active icon on the hover fill, tooltips to the right, the sidebar's edge drags); nothing Obsidian has that we cannot back
# (settings, help, vault switcher) is drawn.
RIBBON_ICONS = {
    "home": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/><path d="M14 4h7M14 9h7M14 15h7M14 20h7"/>',
    "scene": '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>',
    "sheet": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18M3 15h18M9 9v12M15 9v12"/>',
    "page": '<rect width="7" height="18" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/>',
    "runs": '<path d="M12 12H3M16 6H3M12 18H3"/><path d="m16 12 5 3-5 3v-6Z"/>',
}
# (data-v, label, tooltip); the group after the rule holds Runs, the atomic unit, reachable from every view
RIBBON = [[("home", "Deployments", "Deployments · every machine we do sim to real on")],
          [("scene", "Scene", "Scene · the 3D is the page"), ("sheet", "Sheet", "Sheet · the nested table, round 0 · now · change"),
           ("page", "Workbench", "Workbench · the tree and the node's page")],
          [("runs", "Runs", "Runs · every run, each with its Rerun recording")]]


def ribbon_html() -> str:
    groups = []
    for group in RIBBON:
        groups.append("".join(
            f'<a class="dw-view dw-rb" data-v="{v}" data-go href="/deployments/" aria-label="{e(label)}" data-tip="{e(tip)}">'
            f'<svg viewBox="0 0 24 24" aria-hidden="true">{RIBBON_ICONS[v]}</svg></a>' for v, label, tip in group))
    return '<span class="dw-rb-sep" aria-hidden="true"></span>'.join(groups)


TOGGLE = ('<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" y="4" width="19" height="16" rx="2.5"/>'
          '<rect class="inner" x="4.5" y="6" width="4.3" height="12" rx="1"/></svg>')

BODY = """<div class="dw" id="dw" data-src="/data/{data}">
<nav class="dw-ribbon" id="dw-ribbon" aria-label="Views">
  <div class="dw-rb-head"><button class="dw-toggle" id="dw-sidetoggle" type="button" aria-label="Collapse the sidebar" data-tip="Collapse the sidebar" aria-expanded="true">{toggle}</button></div>
  <div class="dw-rb-actions">{ribbon}</div>
</nav>
<aside class="dw-left" id="dw-left" aria-label="Typed component tree"></aside>
<div class="dw-sash" id="dw-sashL"></div>
<div class="dw-work">
  <div class="dw-bar">
    <div class="dw-vtitle" id="dw-vtitle"></div>
    <span class="dw-grow"></span>
    <span class="dw-depacts" id="dw-depacts"></span>
    <div class="dw-seg" id="dw-round" role="group" aria-label="Round shown" hidden></div>
    <button class="dw-toggle right" id="dw-unfold" type="button" aria-label="Collapse the inspector" data-tip="Collapse the inspector" data-tip-pos="left" aria-expanded="true" hidden>{toggle}</button>
  </div>
  <div class="dw-row">
    <section class="dw-home" id="dw-home" hidden></section>
    <section class="dw-dep" id="dw-dep" hidden><div class="dw-entity" id="dw-entity"></div></section>
    <section class="dw-scenev" id="dw-scene" hidden><div class="dw-stage" id="dw-stage"><div class="dw-timebar" id="dw-timebar"></div></div></section>
    <section class="dw-tablev" id="dw-table" hidden><div class="dw-tablewrap" id="dw-tablewrap"></div></section>
    <section class="dw-runs" id="dw-runs" hidden></section>
    <div class="dw-sash" id="dw-sashT"></div>
    <aside class="dw-insp" id="dw-insp" aria-label="Inspector" hidden>
      <div class="dw-dock3d" id="dw-dock3d"></div>
      <div class="dw-sash h" id="dw-sashD"></div>
      <div class="dw-insp-scroll" id="dw-inspBody"></div>
    </aside>
  </div>
</div>
<noscript><p class="lede">The workbench needs JavaScript. Every deployment is also listed, without it, at <a href="{all}">{all}</a>.</p></noscript>
</div>
<div class="dw-tip" id="dw-tip" role="tooltip" hidden></div>
<script src="/static/{three}" defer></script>
<script src="/static/deployments-workbench.js" defer></script>"""


def files(site):
    import catalog as s2r  # noqa: PLC0415

    body = BODY.format(data=e(DATA), all=e(ALL_URL), three=e(THREE_NAME), ribbon=ribbon_html(), toggle=TOGGLE)
    yield "deployments/index.html", s2r.page(
        site, "Deployments: sim2real", URL, body, "deployments-workbench", extra_head='<link rel="stylesheet" href="/static/deployments-workbench.css">\n',
        trail=breadcrumb([s2r.ROOT_CRUMB, ("Deployments", URL)]),
        description="Every deployment: its 3D, its typed component tree and, at every node, its performance against the target first, "
                    "then how close its twin is.")
    yield f"static/{THREE_NAME}", THREE.read_bytes()
