"""/deployments/: the Deployments workbench. Every deployment; open one for its 3D and its typed component tree; any node of the tree shows
that level's data: performance first (real vs the target), then fidelity (real vs sim) and the five questions; a Table view (the nested
tree-table, like RobotDx's) and a Runs view (every run of every round, each opening its Rerun recording).

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


def page_data(site) -> tuple[dict, dict]:
    """(the page's data, the runs table)."""
    d = dps.load(site)
    trees, missing, rows = {}, None, []
    try:
        trees[dpage.DEPLOYMENT] = dpage.build()
        rows = dpage.runs()
    except FileNotFoundError as error:
        missing = str(error)
    links = replay_links(rows) if rows else {"recordings": 0, "registered_now": 0, "launcher": False}
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
                            "workbench": row["id"] in trees, "headline": headline,
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


def write_data(data_dir, site) -> dict:
    data, runs_doc = page_data(site)
    (data_dir / DATA).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    (data_dir / RUNS).write_text(json.dumps(runs_doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    return {"nodes": sum(len(t["nodes"]) for t in data["trees"].values()), "runs": len(runs_doc["rows"]), "missing": data["missing"],
            **data["replay"]}


BODY = """<div class="dw" id="dw" data-src="/data/{data}">
<div class="dw-bar">
  <nav class="dw-views" role="tablist" aria-label="Views">
    <a class="dw-view" data-v="home" href="/deployments/">Deployments</a>
    <a class="dw-view" data-v="page" href="/deployments/?d=one-dof-test-rack" hidden>Workbench</a>
    <a class="dw-view" data-v="table" href="/deployments/?d=one-dof-test-rack&amp;view=table" hidden>Table</a>
    <a class="dw-view" data-v="runs" href="/deployments/?d=one-dof-test-rack&amp;view=runs" hidden>Runs</a>
  </nav>
  <span class="dw-grow"></span>
  <div class="dw-seg" id="dw-round" role="group" aria-label="Round shown" hidden></div>
</div>
<section class="dw-home" id="dw-home" hidden></section>
<section class="dw-dep" id="dw-dep" hidden>
  <aside class="dw-left" id="dw-left"></aside>
  <div class="dw-sash" id="dw-sashL"></div>
  <div class="dw-entity" id="dw-entity"></div>
</section>
<section class="dw-tablev" id="dw-table" hidden>
  <div class="dw-tablewrap" id="dw-tablewrap"></div>
  <div class="dw-sash" id="dw-sashT"></div>
  <aside class="dw-insp" id="dw-insp"></aside>
</section>
<section class="dw-runs" id="dw-runs" hidden></section>
<noscript><p class="lede">The workbench needs JavaScript. Every deployment is also listed, without it, at <a href="{all}">{all}</a>.</p></noscript>
</div>
<script src="/static/{three}" defer></script>
<script src="/static/deployments-workbench.js" defer></script>"""


def files(site):
    import catalog as s2r  # noqa: PLC0415

    body = BODY.format(data=e(DATA), all=e(ALL_URL), three=e(THREE_NAME))
    yield "deployments/index.html", s2r.page(
        site, "Deployments: sim2real", URL, body, "deployments-workbench", extra_head='<link rel="stylesheet" href="/static/deployments-workbench.css">\n',
        trail=breadcrumb([s2r.ROOT_CRUMB, ("Deployments", URL)]),
        description="Every deployment: its 3D, its typed component tree and, at every node, its performance against the target first, "
                    "then how close its twin is.")
    yield f"static/{THREE_NAME}", THREE.read_bytes()
