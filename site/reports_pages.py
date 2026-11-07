"""Reports: a named, frozen set of runs and what was computed over them when it was frozen (type_cards/CONTRACT.md, "Domain model v3",
Reports; type_cards/report.py).

Zach (PROJECT - Sim2Real, 2026-11-06): "Now lets have another thing similar to RobotParts. We call Reports. Now we can make a report with like
a set number of rows etc. So that is how we kinda like 'freeze it' and see the ful lbreak down. So even as you add more data etc.. the Reports
is a great way to just see an overview fixed."

/reports/ lists every committed report (type_cards/frozen_reports/<id>.json, served at data/domain/reports/); /reports/<id>/ is its full
breakdown, read from the snapshot and never recomputed: what it answers, when and from which code it was frozen and that its digest verifies,
every entity's metrics (pinned first), diagnostics with their levels, gates and coverage, the models it names, its parameter rows, and its
rows (the snapshot's own, inputs.rows; a snapshot frozen before it kept them lists the rows runs.json holds today and says whether they
still hash to what it froze). The parts' titles and the ladder model beside each producer's label are the snapshot's own (annotations); a
snapshot frozen before it kept them (the first three) reads them from today's records and says so, and the page claims to stay as it is
only for what its snapshot froze (the v3 audit, 2026-11-07, finding 7). A report's runs open live on the metrics page
(/metrics/<dep>/?report=<id>), beside its frozen numbers.

Make one from a selection: `python3 -m type_cards.report freeze --id ... --title ... --question ... --deployment ... --runs | --select |
--preset` (the metrics page writes the command for its selection). Stdlib only. Decision: docs/decision-metrics-reports-2026-11-07.md.
"""

from __future__ import annotations

import hashlib
import json

from catalog_workbench.html import breadcrumb, e, plural

import adapter
import deployments_pages as dpages
import metrics_pages
import pages
import ui_shared
from type_cards import domain as dm  # noqa: E402
from type_cards import instances as inst  # noqa: E402
from type_cards import report as rep  # noqa: E402

URL = "/reports/"
STYLES = metrics_pages.STYLES
ROW_COLUMNS = (("title", "Run"), ("device", "Station"), ("day", "Day"), ("kind", "Kind"), ("split", "Split"), ("mode", "Mode"),
               ("excitation", "Excitation"), ("tracking_mrad", "Tracking RMS (mrad)"), ("best_model", "Closest model"), ("verdict", "Twinned?"))


def report_url(rid: str) -> str:
    return f"{URL}{rid}/"


def snapshots(site) -> dict[str, dict]:
    """The served snapshots (data/domain/reports/, type_cards/instances.write copies the committed ones), newest freeze first."""
    folder = site.data / "domain" / "reports"
    snaps = {p.stem: rep.read_snapshot(p) for p in sorted(folder.glob("*.json"))} if folder.is_dir() else {}
    return dict(sorted(snaps.items(), key=lambda kv: kv[1].get("frozen_at") or "", reverse=True))


def fmt(value, unit: str = "") -> str:
    return metrics_pages.fmt(value, unit)


def raw(value) -> str:
    return metrics_pages.raw(value)


def stations_of(snap: dict) -> list[str]:
    return sorted({n["device"] for n in snap["results"]["selection"]["nodes"] if n.get("device")}, key=lambda d: (len(d), d))


def index_body(snaps: dict) -> str:
    items = []
    for rid, s in snaps.items():
        r = s["report"]
        ok = rep.verify(s)
        items.append(f'<li class="s2r-report" data-report="{e(rid)}" data-runs="{len(r["runs"])}" data-verified="{"true" if ok else "false"}">'
                     f'<a href="{e(report_url(rid))}"><b>{e(r["title"])}</b></a> '
                     f'{pages.chip("pass" if ok else "fail", "digest verifies" if ok else "digest does not verify")}'
                     f'<p>{e(r["question"])}</p><small>{plural(len(r["runs"]), "run")} · {e(", ".join(stations_of(s)) or "no station")} · frozen '
                     f'{e((s.get("frozen_at") or "")[:16].replace("T", " "))} UTC from code {e(s.get("code") or "?")}</small></li>')
    return f"""<h1>Reports <span class="n">({len(snaps)})</span></h1>
<p class="lede">A report is a named, frozen set of runs with everything computed over them when it was frozen: each entity's metrics,
diagnostics with their levels, coverage, the models it names and its parameter rows. Those never change as runs are added; freezing it again is a
new decision. Each report's page says what its snapshot froze and what it reads from today's records (the reports frozen before snapshots kept
their parts' titles and label map read those today). Make one from any selection on a <a href="{e(metrics_pages.URL)}">metrics page</a>, which
writes the command, or from the repo:
<code>python3 -m type_cards.report freeze --id &lt;id&gt; --title "…" --question "…" --deployment one-dof-test-rack --select device="CAN 11"</code>.</p>
<ul class="s2r-reports">{"".join(items)}</ul>"""


def _limits(d: dict) -> str:
    parts = []
    for word, lo, hi in (("warn", d.get("warn_lo"), d.get("warn_hi")), ("error", d.get("error_lo"), d.get("error_hi"))):
        if hi is not None:
            parts.append(f"{word} above {pages.num(hi)}")
        if lo is not None:
            parts.append(f"{word} below {pages.num(lo)}")
    return " · ".join(parts) or "set per unit (no value then)"


def label_words(dep: str, label: str, frozen: dict | None = None) -> str:
    """A model label as the snapshot froze it and the ladder model it named: the snapshot's own map (annotations.model_labels), else, for a
    snapshot frozen before it kept one, what type_cards maps it to today (inst.label_model), marked "today"."""
    if not label:
        return "—"
    if frozen is not None:
        m = frozen.get(label)
        return metrics_pages.model_words(label, {label: {"model": m["model"], "url": f"/models/{m['type']}/#{m['model']}"}} if m else {}, as_="frozen")
    m = inst.label_model(dep, label)
    return metrics_pages.model_words(label, {label: {"model": m.model, "url": f"/models/{m.type}/#{m.model}"}} if m else {}, as_="today",
                                     mark="today" if m else "")


def node_block(node: dict, title: str, dep: str = "", frozen_labels: dict | None = None) -> str:
    tid = node["entity_type"]
    t = dm.TYPES.get(tid)
    order = {m.id: i for i, m in enumerate(t.metrics)} if t else {}
    metrics = sorted(node["metrics"], key=lambda m: (not m["pinned"], order.get(m["metric"], 99), m.get("model") or ""))
    mrows = []
    for m in metrics:
        model = m.get("model") or ""
        if m["value"] is None:
            cell = f'<span class="mut" title="{e(m.get("why") or "")}">— {e(m.get("why") or "")}</span>'
        else:
            side = f', {m["side"]} side' if m.get("side") else ""
            cell = (f'<span data-node="{e(node["node"])}" data-metric="{e(m["metric"])}" data-model="{e(model)}" data-value="{raw(m["value"])}">'
                    f'{e(fmt(m["value"], m["unit"]))}</span> <small class="mut">{e(fmt(m["low"], ""))}–{e(fmt(m["high"], m["unit"]))}, {plural(m["n"], "run")}{e(side)}</small>')
        pin = ' <span class="s2r-pin">pinned</span>' if m["pinned"] else ""
        mrows.append(f'<tr><th scope="row">{e(m["title"])}{pin}</th><td>{label_words(dep, model, frozen_labels)}</td><td>{cell}</td></tr>')
    drows = "".join(
        f'<tr data-node="{e(node["node"])}" data-diagnostic="{e(d["diagnostic"])}" data-model="{e(d.get("model") or "")}" data-level="{e(d["level"])}">'
        f'<td>{metrics_pages.level_chip(d["level"])}</td><th scope="row">{e(d["title"])}</th><td>{label_words(dep, d.get("model") or "", frozen_labels)}</td>'
        f'<td>{e(fmt(d["value"], d.get("unit") or ""))}</td><td>{e(_limits(d))}</td></tr>' for d in node["diagnostics"])
    gates = " · ".join(f'<span data-gate="{e(g["gate"])}">{e(g.get("acceptance") or g["gate"])}{f" ({e(g.get("model"))})" if g.get("model") else ""} '
                       f'{pages.chip(g["verdict"])}</span>' for g in node["gates"])
    c = node["coverage"]
    if tid == "integrated_servo":
        cov = (f'<div class="s2r-mcov" data-coverage-node="{e(node["node"])}" data-coverage-pct="{raw(c.get("pct"))}">'
               + (f'<b>{pages.num(c["pct"])} %</b> of {c["reachable"]:,} reachable cells (q, qd, qdd) visited ({c["visited"]:,}, '
                  f'{c.get("samples", 0):,} samples) · gate {c["gate_pct"]:g} % {pages.chip({"pass": "pass", "fail": "fail"}.get(c.get("verdict"), "not_run"), c.get("verdict"))}'
                  f'<span class="s2r-mbar" role="img" aria-label="{pages.num(c["pct"])} % covered"><i style="width:{min(100.0, c["pct"]):g}%"></i><b style="left:{c["gate_pct"]:g}%"></b></span>'
                  if c.get("pct") is not None else f'<span class="mut">{e(c.get("why") or "")}</span>') + "</div>")
        marg = "; ".join(f"{k} {pages.num(v)} % of its bins" if v is not None else f"{k}: none recorded" for k, v in (c.get("marginals") or {}).items())
        if marg:
            cov += f'<p class="mut">Beside it, never folded in: {e(marg)}.</p>'
    else:
        cov = f'<p class="mut">Coverage: {e(c.get("why") or c.get("verdict") or "")}</p>'
    level = metrics_pages.node_level(node)
    return (f'<section class="s2r-rnode" data-rnode="{e(node["node"])}"><h3>{ui_shared.dot(level, "the worst of its model-independent diagnostics, frozen")}'
            f'{e(title)} <small>{e(node["entity_type"])} · {plural(node["runs"], "run")}</small></h3>'
            f'<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th scope="col">Metric</th><th scope="col">Model</th><th scope="col">Value (median, min–max)</th></tr></thead>'
            f'<tbody>{"".join(mrows)}</tbody></table></div>'
            + (f'<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th scope="col">Level</th><th scope="col">Diagnostic</th><th scope="col">Model</th>'
               f'<th scope="col">Value</th><th scope="col">Limits</th></tr></thead><tbody>{drows}</tbody></table></div>' if drows else "")
            + (f'<p class="s2r-gates">Gates on the selection\'s aggregate: {gates}</p>' if gates else "") + cov + "</section>")


def model_block(m: dict) -> str:
    refs = "; ".join(r.get("title") or "" for r in m.get("references") or [])
    return (f'<section class="s2r-rmodel" data-model-key="{e(m["key"])}"><h3>{e(m["key"])} · {e(m.get("title") or "")}</h3>'
            f'<p>{e(m.get("kind") or "")} · family {e(m.get("family") or "")} · {plural(m.get("n_parameters") or 0, "parameter")}'
            + (f' · adds {e(", ".join(m.get("adds") or []))}' if m.get("adds") else "") + "</p>"
            + (f'<p><code>{e(m["equation"])}</code></p>' if m.get("equation") else "")
            + (f'<p class="mut">Parameters: {e(", ".join(m.get("parameters") or []))}</p>' if m.get("parameters") else "")
            + (f'<p class="mut">References: {e(refs)}</p>' if refs else "") + "</section>")


def parameter_rows(rows: list[dict]) -> str:
    if not rows:
        return '<p class="mut">This report names no parameter row.</p>'
    body = []
    for r in rows:
        if r.get("missing"):
            body.append(f'<tr data-parameter-row="{e(r["id"])}"><th scope="row">{e(r["id"])}</th><td colspan="7" class="mut">{e(r["missing"])}</td></tr>')
            continue
        ci = f'{fmt(r.get("ci95_lo"))}…{fmt(r.get("ci95_hi"))}' if r.get("ci95_lo") is not None else "—"
        body.append(f'<tr data-parameter-row="{e(r["id"])}"><th scope="row">{e(r.get("parameter") or r["id"])} <small class="mut">{e(r.get("node") or "")}</small></th>'
                    f'<td>{e(r.get("unit") or "")}</td><td>{e(fmt(r.get("true")))}</td><td>{e(fmt(r.get("nominal")))}</td><td>{e(fmt(r.get("recovered")))}</td>'
                    f'<td>{e(ci)}</td><td>{e(fmt(r.get("tolerance")))}</td><td>{pages.chip("pass" if r.get("pass") else ("fail" if r.get("pass") is False else "not_run"))}</td></tr>')
    return ('<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th scope="col">Parameter</th><th scope="col">Unit</th><th scope="col">True</th>'
            '<th scope="col">Nominal</th><th scope="col">Recovered</th><th scope="col">95 % interval</th><th scope="col">Tolerance</th><th scope="col">Within</th>'
            f'</tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def rows_block(snap: dict, current: list[dict], dep: str) -> str:
    ids = list(snap["report"]["runs"])
    frozen = (snap.get("inputs") or {}).get("rows")
    if frozen is not None:
        rows, note = frozen, f"The {plural(len(frozen), 'row')} as they were when it was frozen (the snapshot keeps them)."
    else:
        by = {r["run"]: r for r in current}
        rows = [by[i] for i in sorted(ids) if i in by]
        used = sorted(rows, key=lambda r: r["run"])
        now = hashlib.sha256(rep.canonical(used).encode("utf-8")).hexdigest()
        same = now == (snap.get("inputs") or {}).get("runs_sha256")
        note = (f"Frozen before snapshots kept their rows: these are the rows runs.json holds today for its {plural(len(ids), 'run')}, and they "
                + ("still hash to what it froze (sha256 " + now[:12] + ")." if same else
                   f"no longer hash to what it froze (it froze {str((snap.get('inputs') or {}).get('runs_sha256'))[:12]}, today {now[:12]}): runs.json "
                   "gained columns since; the numbers above are the freeze's."))
    missing = [i for i in ids if i not in {r["run"] for r in rows}]
    head = "".join(f'<th scope="col">{e(w)}</th>' for _k, w in ROW_COLUMNS)
    body = []
    for r in sorted(rows, key=lambda r: (r.get("started") or "", r["run"])):
        cells = []
        for k, _w in ROW_COLUMNS:
            v = r.get(k)
            if k == "title":
                cells.append(f'<td>{pages.a(adapter.run_url({"deployment": dep, "run": r["run"]}), v or r["run"])}</td>' if dep else f"<td>{e(v or r['run'])}</td>")
            else:
                cells.append(f"<td>{e(fmt(v) if isinstance(v, float) else ('—' if v is None else v))}</td>")
        body.append(f'<tr data-run="{e(r["run"])}">{"".join(cells)}</tr>')
    lost = f'<p class="mut">Not in the data any more: {e(", ".join(missing[:5]))}{"…" if len(missing) > 5 else ""}.</p>' if missing else ""
    return (f'<p class="mut">{e(note)}</p>{lost}<div class="s2r-scroll" data-report-rows><table class="s2r-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def frozen_words(snap: dict) -> tuple[str, list[str]]:
    """What the page may say stays as it is (what the snapshot froze), what it reads from today's records instead, and those as data-today
    words. WHY (the v3 audit, 2026-11-07, finding 7): the page said it "stays as it is" while its titles and label map were today's."""
    ann, kept_rows = snap.get("annotations"), (snap.get("inputs") or {}).get("rows") is not None
    frozen = ["its numbers (every metric, diagnostic level, gate and coverage)", "its models", "its parameter rows"]
    today, words = [], []
    (frozen if kept_rows else today).append("its rows" if kept_rows else "its rows (runs.json's today, checked against the hash it froze)")
    words += [] if kept_rows else ["rows"]
    (frozen if ann else today).append("the parts' titles and the ladder model each producer's label names")
    words += [] if ann else ["titles", "model_labels"]
    text = f"It reads its snapshot and never recomputes: as runs are added, {', '.join(frozen[:-1])} and {frozen[-1]} stay as they are."
    if today:
        text += (f" Read from today's records, not frozen (it was frozen before snapshots kept them): {' and '.join(today)}, each marked today "
                 "where it shows.")
    return text, words


def report_body(d: dpages.Domain, snap: dict) -> str:
    r = snap["report"]
    ok = rep.verify(snap)
    dep = r.get("deployment") or ""
    ann = snap.get("annotations")
    # WHY the snapshot's titles and label map (the v3 audit, finding 7): today's would change what a verified report says
    titles = ann["titles"] if ann else {n["id"]: n["title"] for n in d.nodes}
    labels = ann["model_labels"] if ann else None
    nodes = snap["results"]["selection"]["nodes"]
    stations = [n for n in nodes if n["entity_type"] == "integrated_servo"]
    blocks = []
    for st in stations:
        blocks.append(node_block(st, titles.get(st["node"]) or st["node"], dep, labels))
        for p in nodes:
            if p is not st and p.get("device") == st.get("device"):
                blocks.append(node_block(p, titles.get(p["node"]) or p["node"], dep, labels))
    blocks += [node_block(n, titles.get(n["node"]) or n["node"], dep, labels) for n in nodes if n.get("device") is None]
    claim, today = frozen_words(snap)
    current = d.runs.get(dep, [])
    live = (f' · <a href="{e(metrics_pages.page_url(dep))}?report={e(r["id"])}">its runs on the metrics page, live</a>' if dep in d.runs else "")
    sel = snap["results"]["selection"]
    unknown = f' {plural(len(sel.get("unknown_runs") or []), "run")} it named were not in the data then.' if sel.get("unknown_runs") else ""
    return f"""<article class="s2r-rep" data-report="{e(r["id"])}" data-digest="{e(snap["digest"])}" data-verified="{"true" if ok else "false"}" data-frozen-at="{e(snap.get("frozen_at") or "")}" data-today="{e(" ".join(today))}">
<h1>{e(r["title"])}</h1>
<p class="s2r-question">{e(r["question"])}</p>
<p class="s2r-frozen">Frozen {e((snap.get("frozen_at") or "")[:16].replace("T", " "))} UTC from code {e(snap.get("code") or "?")} over {plural(sel["runs"], "run")} of
{e(titles.get(dep, dep) or "no deployment")} · {pages.chip("pass" if ok else "fail", "digest verifies" if ok else "digest does not verify")}
<small>sha256 {e(snap["digest"][:16])}…</small>{live}. {e(claim)}{e(unknown)}</p>
{f'<p class="mut">{e(r["note"])}</p>' if r.get("note") else ""}
<section id="results" aria-labelledby="results-h"><h2 id="results-h">What it found, entity by entity</h2>
<p class="mut">Each metric is its median over the report's runs (min–max and the count beside it); each diagnostic its limits on that value; each
gate its target on it (not bam_rack_twin's acceptance statistic); coverage the type card's own function over the runs' points.{"" if ann else
" Each part's title and the ladder model beside each label are today's (marked today): this snapshot was frozen before snapshots kept them."}</p>
{"".join(blocks)}</section>
<section id="models" aria-labelledby="models-h"><h2 id="models-h">Models <small>({len(snap["results"]["models"])})</small></h2>
{"".join(model_block(m) for m in snap["results"]["models"]) or '<p class="mut">It names no model.</p>'}</section>
<section id="parameters" aria-labelledby="parameters-h"><h2 id="parameters-h">Parameters <small>({len(snap["results"]["parameters"])})</small></h2>
{parameter_rows(snap["results"]["parameters"])}</section>
<section id="rows" aria-labelledby="rows-h"><h2 id="rows-h">Its rows <small>({len(r["runs"])})</small></h2>
{rows_block(snap, current, dep)}</section>
</article>"""


def files(site):
    import catalog as s2r  # noqa: PLC0415

    d = dpages.load(site)
    snaps = snapshots(site)
    yield "reports/index.html", s2r.page(site, "Reports: sim2real", URL, index_body(snaps), "reports", extra_head=STYLES,
                                         trail=breadcrumb([s2r.ROOT_CRUMB, ("Reports", URL)]),
                                         description="Named, frozen sets of runs with their results captured when they were frozen.")
    for rid, snap in snaps.items():
        yield f"reports/{rid}/index.html", s2r.page(
            site, f"{snap['report']['title']}: a sim2real report", report_url(rid), report_body(d, snap), "reports", extra_head=STYLES,
            trail=breadcrumb([s2r.ROOT_CRUMB, ("Reports", URL), (snap["report"]["title"], report_url(rid))]),
            description=snap["report"]["question"][:240])
