"""sim2real's own HTML inside the workbench's frame: each record's header and tab panels, the home's tiles and its
"Where it fails" matrix, the lists, and the Analysis reports.

WHY static HTML for the verdicts (Zach, 2026-10-29: "easy for me to understand where and why we are failing"): the gate
matrix, the why rows, a run's gate cells and diagnostics are drawn here at build time, so they read at once, without
JavaScript and without waiting on a 35 MB dataset; the data-ui dashboards (the playback, the runs table with its rail,
coverage, the gates overlay) sit in their own tabs and load only when their tab opens (static/sim2real.js).

Colours: blue is real and orange is a model (data-ui series slots 1 and 2); green and red mean pass and fail only, and
every verdict also carries a word or a symbol, never colour alone.
"""

from __future__ import annotations

import json
import re

from catalog_workbench.home import Group, tile, tile_home
from catalog_workbench.html import breadcrumb, e, plural, results_line

import adapter
from adapter import Deployment, Site, Station, deployment_url, rewrite_links, run_url, station_key, station_url

ROOT_CRUMB = ("Home", "/")
SYMBOL = {"pass": "✓", "fail": "✗", "warn": "!", "partial": "!", "not_run": "–"}
WORD = {"pass": "pass", "fail": "fail", "warn": "warn", "partial": "partial", "not_run": "not run"}
NEWEST = 10


# --- small parts ------------------------------------------------------------------------------------------------------

def chip(verdict: str | None, text: str | None = None) -> str:
    v = verdict or "not_run"
    return f'<span class="s2r-v s2r-{e(v)}">{e(text or WORD.get(v, v))}</span>'


def num(value, digits: int = 3) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def when(stamp: str | None) -> str:
    """2026-10-29T04:07:25-07:00 -> 2026-10-29 04:07 (the rack's local time, as recorded)."""
    return stamp[:16].replace("T", " ") if stamp else "—"


def a(href: str, text: str, cls: str = "") -> str:
    return f'<a href="{e(href)}"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{e(text)}</a>'


def file_link(path: str | None) -> str:
    """An archive path is shown, not linked (the archive is not served); a site path is linked."""
    if not path:
        return "—"
    path = rewrite_links(path)
    return a(path, path) if path.startswith("/") and not path.startswith(("/archive/", "/home/")) else f"<code>{e(path)}</code>"


def gate_ids(dep: Deployment) -> list[tuple[str, str]]:
    """(T1, "T1 floor") in gate order."""
    seen = {}
    for g in sorted(dep.gates, key=lambda g: g["order"]):
        seen.setdefault(g["gate"].split()[0], g["gate"])
    return list(seen.items())


def why_anchor(device: str, gate_id: str) -> str:
    return f"{station_key(device)}-{gate_id}"


def cell_href(dep: Deployment, g: dict) -> str:
    """A cell opens why it fails (the report's row) or, when it passes, the station's gates."""
    gid = g["gate"].split()[0]
    if g["verdict"] != "pass" or any(w["device"] == g["device"] and w["gate_id"] == gid for w in dep.why):
        return f"/analysis/why-it-fails/#{why_anchor(g['device'], gid)}"
    return station_url(dep.id, g["device"]) + "#gates"


def matrix(dep: Deployment, caption: str = "") -> str:
    """Stations × gates, one cell per gate with its verdict as a symbol and a colour; each cell opens its why."""
    gates = gate_ids(dep)
    head = "".join(f'<th scope="col" title="{e(name)}">{e(gid)}</th>' for gid, name in gates)
    names = " · ".join(f"<b>{e(gid)}</b> {e(name.split(' ', 1)[1] if ' ' in name else '')}" for gid, name in gates)
    rows = []
    for station in sorted(dep.devices, key=lambda d: d.get("order", 0)):
        device = station["device"]
        cells = {g["gate"].split()[0]: g for g in dep.gates_of(device)}
        passing = sum(1 for g in cells.values() if g["verdict"] == "pass")
        tds = []
        for gid, name in gates:
            g = cells.get(gid)
            if g is None:
                tds.append('<td class="s2r-cell s2r-none">·</td>')
                continue
            title = f"{device} · {g['gate']} — {WORD.get(g['verdict'], g['verdict'])}" + (f": {g['message']}" if g.get("message") else "")
            tds.append(f'<td class="s2r-cell s2r-{e(g["verdict"])}" data-device="{e(device)}" data-gate="{e(gid)}" data-verdict="{e(g["verdict"])}">'
                       f'<a href="{e(cell_href(dep, g))}" title="{e(title)}" aria-label="{e(title)}">{SYMBOL.get(g["verdict"], "?")}</a></td>')
        rows.append(f'<tr><th scope="row">{a(station_url(dep.id, device), device)}<small>{passing} of {len(cells)}</small></th>{"".join(tds)}</tr>')
    cap = f"<caption>{caption}</caption>" if caption else ""
    return f"""<div class="s2r-scroll"><table class="s2r-matrix">{cap}
<thead><tr><th scope="col">Station</th>{head}</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table></div>
<p class="s2r-legend">{chip("pass", "✓ pass")} {chip("fail", "✗ fail")} {chip("warn", "! warn / partial")} {chip("not_run", "– not run")} · a cell opens why it fails</p>
<p class="s2r-legend">{names}</p>"""


def strip_svg(dep: Deployment, device: str) -> str:
    """A station's gates as a strip of squares: the home tile's picture."""
    cells = dep.gates_of(device)
    size, gap = 10, 3
    rects = "".join(f'<rect x="{i * (size + gap)}" y="0" width="{size}" height="{size}" rx="2" class="s2r-sq s2r-{e(g["verdict"])}"><title>{e(g["gate"])}: {e(g["verdict"])}</title></rect>'
                    for i, g in enumerate(cells))
    width = max(1, len(cells) * (size + gap) - gap)
    return f'<svg class="s2r-strip" viewBox="0 0 {width} {size}" width="{width * 1.6:.0f}" height="{size * 1.6:.0f}" role="img" aria-label="{e(device)} gates">{rects}</svg>'


def gate_chips(dep: Deployment, device: str) -> str:
    """A station's T1-T11 in a line of chips, each opening its why (or its gates when it passes)."""
    out = []
    for g in dep.gates_of(device):
        gid = g["gate"].split()[0]
        out.append(f'<a class="s2r-gchip s2r-{e(g["verdict"])}" href="{e(cell_href(dep, g))}" title="{e(g["gate"])}: {e(g["verdict"])}">'
                   f'{e(gid)} {SYMBOL.get(g["verdict"], "?")}</a>')
    return f'<p class="s2r-gchips" aria-label="{e(device)} gates">{"".join(out)}</p>'


def why_rows(dep: Deployment, rows: list[dict], heading_level: int = 3, with_device: bool = True) -> str:
    """Each cell the newest acceptance does not pass (and each pass that flips under the pooled floor), in words: the
    number against its limit, why, the evidence, the floor rules, and the next test or what is blocked on Zach."""
    if not rows:
        return ""
    out = []
    for w in rows:
        flips = w["status"] == "pass"
        label = "pass today · fails under the pooled floor" if flips else WORD.get(w["status"], w["status"])
        play = (f'<p class="s2r-play">{a(rewrite_links(w["page"]), "▶ Play the worst window" if "tr=" in w["page"] else "Open the run")}</p>'
                if w.get("page") else "")
        blocked = ' <span class="s2r-blocked">blocked on Zach</span>' if str(w.get("next", "")).startswith("blocked on Zach") else ""
        fields = [("Why", w.get("why")), ("Evidence and uncertainty", w.get("evidence")), ("Floor rules", w.get("floor_rules")),
                  ("Next", w.get("next")), ("Kind of step", w.get("category")), ("Source", w.get("source"))]
        dl = "".join(f"<dt>{e(k)}</dt><dd>{e(v) if k != 'Source' else file_link(v)}</dd>" for k, v in fields if v)
        who = f"{w['device']} · " if with_device else ""
        out.append(f"""<article class="s2r-whyrow s2r-st-{e("warn" if flips else w["status"])}" id="{e(why_anchor(w['device'], w['gate_id']))}" data-cell="{e(w['device'])} {e(w['gate_id'])}">
<h{heading_level}>{chip("warn" if flips else w["status"], label)} {e(who)}{e(w["gate"])}{blocked}</h{heading_level}>
<p class="s2r-num">{e(w.get("measured") or "—")}</p>
<dl class="s2r-dl">{dl}</dl>
{play}</article>""")
    return f'<div class="s2r-why">{"".join(out)}</div>'


def dashboard(src: str, label: str, own_url: bool = False) -> str:
    """A data-ui dashboard that loads when its tab is first shown (static/sim2real.js makes the element). WHY lazy: the
    coverage set is 35 MB and a run has six tables; only the open tab's are fetched. Only the first tab's dashboard owns
    the URL (#t=… is its clock), so an old #t= link still lands on the Playback."""
    own = " data-own-url" if own_url else ""
    return (f'<div class="s2r-dash" data-src="{e(src)}" aria-label="{e(label)}"{own}>'
            f'<noscript><p>This panel is a data-ui dashboard ({a(src, src)}); it needs JavaScript.</p></noscript></div>')


def record_json(**fields) -> str:
    return f'<script type="application/json" id="s2r-record">{json.dumps(fields, ensure_ascii=False)}</script>'


def table(head: list[str], rows: list[list[str]], cls: str = "s2r-table", caption: str = "") -> str:
    th = "".join(f'<th scope="col">{h}</th>' for h in head)
    body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    cap = f"<caption>{caption}</caption>" if caption else ""
    return f'<div class="s2r-scroll"><table class="{cls}">{cap}<thead><tr>{th}</tr></thead><tbody>\n{body}\n</tbody></table></div>'


def kpis(items: list[tuple[str, str]]) -> str:
    return '<dl class="s2r-kpis">' + "".join(f"<div><dt>{e(k)}</dt><dd>{v}</dd></div>" for k, v in items) + "</dl>"


def open_counts(dep: Deployment) -> dict:
    counts = {}
    for g in dep.gates:
        counts[g["verdict"]] = counts.get(g["verdict"], 0) + 1
    return counts


def standing_line(dep: Deployment) -> str:
    counts = open_counts(dep)
    acc = dep.acceptance()
    src = f' · from {e(adapter_name(acc["file"]))} ({e(acc["dated"])})' if acc else ""
    rest = ", ".join(f"{n} {WORD.get(v, v)}" for v, n in sorted(counts.items()) if v != "pass")
    return (f'<p class="s2r-standing"><strong>{counts.get("pass", 0)} of {len(dep.gates)} gate cells pass</strong> · {e(rest)}{src} · '
            f'{a("/analysis/why-it-fails/", "why each one fails")}</p>')


def adapter_name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


# --- the deployment ---------------------------------------------------------------------------------------------------

def deployment_header(site: Site, dep: Deployment) -> str:
    row = dep.row
    return f"""{record_json(deployment=dep.id, run="", station="", device="")}
<h1>{e(row["title"])}</h1>
<p class="sub">{e(row.get("kind") or "")} · {e(row.get("family") or "")} · {e(row.get("where") or "")}</p>
<p>{e(row.get("summary") or "")}</p>
{kpis([("Stations", str(row.get("stations"))), ("Real runs", f'{row.get("runs"):,}'), ("Runs with models", str(row.get("runs_with_models"))),
       ("Hours of real data", str(row.get("hours"))), ("Days", str(row.get("days"))), ("Last run", e(when(row.get("last_run"))))])}
{standing_line(dep)}
<p class="s2r-stations">{" ".join(station_badge(dep, d["device"]) for d in sorted(dep.devices, key=lambda d: d.get("order", 0)))}</p>"""


def station_badge(dep: Deployment, device: str) -> str:
    """A station's name, its gate strip and how many of its cells pass: where it fails, at a glance, one click from why."""
    cells = dep.gates_of(device)
    passing = sum(1 for g in cells if g["verdict"] == "pass")
    return (f'<a class="s2r-badge" href="{e(station_url(dep.id, device))}"><b>{e(device)}</b>{strip_svg(dep, device)}'
            f'<small>{passing} of {len(cells)}</small></a>')


def deployment_runs(site, dep: Deployment) -> str:
    return dashboard("/views/deployment-runs.base", f"{dep.row['title']}: runs", own_url=True)


def deployment_gates(site, dep: Deployment) -> str:
    return (f"<h2>Where it fails</h2>{matrix(dep, 'Stations × gates, from the newest acceptance')}\n"
            + dashboard("/views/deployment-gates.base", f"{dep.row['title']}: gates"))


def deployment_why(site, dep: Deployment) -> str:
    return dashboard("/views/deployment-why.base", f"{dep.row['title']}: why it fails")


def deployment_coverage(site, dep: Deployment) -> str:
    return dashboard("/views/deployment-coverage.base", f"{dep.row['title']}: coverage")


def deployment_evidence(site, dep: Deployment) -> str:
    files = table(["Kind", "Dated", "File", "What it says"],
                  [[e(r.get("kind")), e(r.get("dated") or "—"), file_link(r.get("file")), e(r.get("note") or "")] for r in dep.evidence],
                  caption="The files the gates and the why rows were built from, each the newest of its kind by the date written inside it")
    caveats = "".join(f"<li><strong>{e(c['caveat'])}.</strong> {e(c['detail'])}</li>" for c in dep.caveats)
    tables = " · ".join(a(f"/data/{dep.id}/{name}.json", f"{name}.json") for name in ("runs", "devices", "gates", "why", "evidence", "caveats", "diagnostics", "run_gates"))
    archive = "".join(f"<li><code>{e(d)}</code></li>" for d in dep.row.get("archive") or [])
    return f"""<h2>Evidence files</h2>{files}
<h2>Caveats</h2><ul class="s2r-caveats">{caveats}</ul>
<h2>The tables this page reads</h2><p>{tables} (data-ui's robotics contract tables, written by <code>tools/build_app.py</code>).</p>
{f"<h2>Archive days</h2><ul>{archive}</ul>" if archive else ""}"""


# --- a station --------------------------------------------------------------------------------------------------------

def station_header(site: Site, st: Station) -> str:
    dep, row = st.deployment, st.row
    cells = dep.gates_of(st.device)
    passing = sum(1 for g in cells if g["verdict"] == "pass")
    gains = " · ".join(f"{k} {num(row.get(k))}" for k in ("kp", "ki", "kd") if row.get(k) is not None)
    return f"""{record_json(deployment=dep.id, run="", station=st.key, device=st.device)}
<h1>{e(st.device)}</h1>
<p class="sub">{e(row.get("station") or "")} · {e(row.get("type") or "")} on {a(deployment_url(dep.id), dep.row["title"])}</p>
{kpis([("Gate cells passing", f"{passing} of {len(cells)}"), ("Real runs", f'{row.get("runs", 0):,}'), ("Gains (record)", e(gains or "—")),
       ("Speed ceiling", f'{num(row.get("qd_max_deg_s"))} °/s' if row.get("qd_max_deg_s") else "—")])}
{gate_chips(dep, st.device)}"""


def station_runs(site, st: Station) -> str:
    return dashboard("/views/station-runs.base", f"{st.device}: runs", own_url=True)


def gates_table(dep: Deployment, device: str) -> str:
    rows = []
    for g in dep.gates_of(device):
        gid = g["gate"].split()[0]
        value = g.get("value_text") or num(g.get("value"))
        why = f' {a(cell_href(dep, g), "why")}' if g["verdict"] != "pass" else ""
        rows.append(f'<tr data-verdict="{e(g["verdict"])}"><th scope="row">{e(g["gate"])}</th><td>{chip(g["verdict"])}{why}</td><td>{e(value)}</td>'
                    f'<td>{e(g.get("target") or "—")}</td><td>{e(g.get("message") or "")}</td></tr>')
    return f"""<div class="s2r-scroll"><table class="s2r-table s2r-gates"><caption>{e(device)} · gates T1-T11 from the newest acceptance</caption>
<thead><tr><th scope="col">Gate</th><th scope="col">Verdict</th><th scope="col">Value</th><th scope="col">Limit</th><th scope="col">What it measured</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>"""


def station_gates(site, st: Station) -> str:
    dx = st.deployment.diagnostics_of(st.device)
    dx_table = table(["Diagnostic", "Verdict", "Value", "Unit", "What it measured", "Evidence"],
                     [[e(d.get("title")), chip(d.get("verdict")), e(num(d.get("value"))), e(d.get("unit") or ""), e(d.get("message") or ""), file_link(d.get("evidence"))] for d in dx],
                     caption=f"Station diagnostics (robotdx.diagnostics, tools/diagnostics_run_rack.py)") if dx else ""
    return gates_table(st.deployment, st.device) + dx_table


def station_why(site, st: Station) -> str:
    rows = st.deployment.why_of(st.device)
    if not rows:
        return f"<p><strong>{e(st.device)} passes every gate the newest acceptance scores.</strong></p>"
    fails = sum(1 for w in rows if w["status"] != "pass")
    intro = f"<p>{plural(fails, 'cell')} of {e(st.device)} the newest acceptance does not pass, each with its number against the limit, why, and the next step.</p>"
    decomposition = (dashboard("/views/run-why.base", f"{st.device}: residual decomposition") if st.key in st.deployment.decompositions else "")
    return intro + why_rows(st.deployment, rows, with_device=False) + decomposition


def station_coverage(site, st: Station) -> str:
    return dashboard("/views/station-coverage.base", f"{st.device}: coverage")


def station_schedule(site, st: Station) -> str:
    """The station's test schedule before anything runs (bam_rack_twin.schedule): what it plans, how well it covers the envelope,
    what it cannot cover, and the one-line command per plan. The numbers are the producer's summary.json; the plots are data-ui's."""
    s = st.deployment.schedules[st.key]
    cov, rt, gate, note = s["coverage"], s["run_time"], s["coverage_gate"], s["note_targets"]
    head = kpis([("Status", "not run yet"), ("Trajectories", str(s["trajectories"])), ("Runs", str(s["runs"])),
                 ("Train / held-out runs", f'{s["split_counts"]["train"]} / {s["split_counts"]["held_out"]}'),
                 ("Runnable today", f'{rt["runnable_today_min"]} min'), ("Every mode", f'{rt["all_modes_min"]} min'),
                 ("Train coverage", f'{cov["train"]} %'), ("Held-out coverage", f'{cov["held_out"]} %')])
    lede = (f'<p class="lede"><strong>Planned, not run yet.</strong> {e(s["station"].upper().replace("CAN", "CAN "))}\'s schedule {e(s["digest"])} from '
            f'<code>bam_rack_twin.schedule</code>: {s["trajectories"]} trajectories of {len(s["families"])} families, every target inside the '
            f'range, speed, accel and predicted torque. Train runs visit {cov["train"]} % of the {s["reachable_cells"]} reachable (q, qd, qdd) cells '
            f'(v1 gate {gate["minimum_pct"]:g} %: {"passes" if gate["passes"] else "fails"}); held out: the whole kp × 0.5 level (H1, '
            f'{s["held_out_sets"]["H1"]} runs) and operate seeds 3-5 under every mode (H2, {s["held_out_sets"]["H2"]} runs). '
            f'Twin: {e(s.get("twin") or "none")}.</p>')
    rows = []
    for c in s["commands"]:
        zach = " · needs Zach" if c["needs_zach"] else ""
        rows.append(f'<div class="s2r-command" data-runner="{e(c["runner"])}"><p>{chip("not_run", "runnable today" if c["runner"] == "runnable" else "not runnable yet")} '
                    f'<b>{e(c["plan_name"])}</b> · {c["runs"]} runs · ~{c["minutes"]} min{e(zach)}<br><small>{e(c["label"])}. '
                    f'Dry run: {e(c["dry_run"][:220])}. {e(c["why"]) if c["runner"] != "runnable" else ""}</small></p>'
                    f'<pre>{e(c["command"])}</pre></div>')
    commands = f'<h2>Run commands, one per plan</h2><div class="s2r-commands">{"".join(rows)}</div>'
    missing = []
    if not note["passes"]["reachable"]:
        missing.append(f'the note\'s ≥ 200 train samples in 95 % of reachable cells: {note["reachable_with_200_train_pct"]} % today')
    if not note["passes"]["deployment_weighted"]:
        missing.append(f'deployment-weighted coverage (H2 samples in cells with ≥ 200 train samples): {note["deployment_weighted_pct"]} % against 99 %')
    band = s["effects"]["band_power_pct"]
    missing.append(f'spectral power at 3-8 Hz: {band["3_8_hz"]} % of the train targets\' power (the accel envelope keeps high-frequency amplitudes to millimetres)')
    for item in s["skipped"]:
        missing.append(f'{item["family"]} variant {item["variant"]}: {item["reason"]}')
    for item in s["rejected"]:
        missing.append(f'{item["family"]} variant {item["variant"]}: rejected ({"; ".join(item["reasons"])})')
    for name, mode in s["modes"].items():
        if mode["runner"]["status"] != "runnable":
            missing.append(f'{name}: {mode["runner"]["reason"]}')
    gaps = "<h2>What it does not cover</h2><ul>" + "".join(f"<li>{e(m)}</li>" for m in missing) + "</ul>"
    ff = s["modes"].get("ff", {})
    safety = ""
    if ff.get("protects"):
        safety = ("<h2>FF only: what protects it, and what does not</h2><p>Planned, marked needs Zach; the safe stand-in is ff_weakfb "
                  f"(model fb share median {num(s.get('fb_share_ff_weakfb_median'))} in the twin).</p><ul>"
                  + "".join(f"<li>{e(x)}</li>" for x in ff["protects"]) + "</ul><p><strong>Not protected:</strong></p><ul>"
                  + "".join(f"<li>{e(x)}</li>" for x in ff["unprotected"]) + "</ul>")
    return (head + lede + dashboard("/views/station-schedule.base", f"{st.device}: test schedule") + commands + gaps + safety)


def station_evidence(site, st: Station) -> str:
    row = st.row
    fields = table(["Field", "Value"], [[e(k), e(num(v) if not isinstance(v, (list, dict)) else json.dumps(v))] for k, v in row.items()],
                   caption=f"{st.device} as devices.json records it")
    sources = sorted({g.get("source") for g in st.deployment.gates_of(st.device) if g.get("source")})
    return (f"<h2>Where the gates come from</h2><ul>{''.join(f'<li>{file_link(s)}</li>' for s in sources)}</ul>"
            f"<h2>The station</h2>{fields}")


# --- a run ------------------------------------------------------------------------------------------------------------

def run_title(row: dict) -> str:
    return f"{row['device']} · {row['title']}"


def run_header(site: Site, row: dict) -> str:
    dep = site.deployment(row["deployment"])
    best = (f'{e(row["best_model"])} {num(row.get("best_model_mrad"))} mrad from real' if row.get("best_model") else "no model replayed this run")
    verdict = row.get("verdict")
    return f"""{record_json(deployment=row["deployment"], run=row["run"], station=station_key(row["device"]), device=row["device"])}
<h1>{e(run_title(row))}</h1>
<p class="sub">{e(when(row.get("started")))} · {e(row.get("kind") or "")} · {num(row.get("duration_s"))} s · {e(row.get("gains") or "")} · {e(row.get("compare") or "")}</p>
<p class="s2r-runline"><span class="s2r-real">real</span> vs target {num(row.get("tracking_mrad"))} mrad · closest model: {best}{(" · twinned? " + chip(verdict)) if verdict else ""}</p>
<p class="s2r-gline">{a(station_url(dep.id, row["device"]), row["device"])} gates: {gate_chips(dep, row["device"])}</p>"""


def run_playback(site, row: dict) -> str:
    return dashboard("/views/run.base", f"{run_title(row)}: playback", own_url=True)


def run_gates(site, row: dict) -> str:
    dep = site.deployment(row["deployment"])
    verdicts = dep.run_gates.get(row["run"], [])
    mine = table(["Diagnostic", "Subject", "Verdict", "Value", "Unit", "What it measured", "Evidence"],
                 [[e(g.get("title")), e(g.get("parent") or g.get("subject") or ""), chip(g.get("verdict")), e(num(g.get("value"))), e(g.get("unit") or ""),
                   e(g.get("message") or ""), file_link(g.get("evidence"))] for g in verdicts],
                 caption="This run's verdicts: real vs target, and each model against real over the station's floor (≤ 1.5× = twinned)") if verdicts else \
        "<p>No run-level verdicts were computed for this run.</p>"
    return f"<h2>This run</h2>{mine}<h2>Its station, {e(row['device'])}</h2>{gates_table(dep, row['device'])}"


def run_why(site, row: dict) -> str:
    dep = site.deployment(row["deployment"])
    rows = dep.why_of(row["device"])
    if not rows:
        return f"<p><strong>{e(row['device'])} passes every gate the newest acceptance scores.</strong></p>"
    here = [w for w in rows if w.get("page") and f"/runs/{row['run']}/" in rewrite_links(w["page"])]
    note = (f"<p class=\"s2r-note\">This run is the worst held-out window of {', '.join(e(w['gate_id']) for w in here)}: "
            f"{a(rewrite_links(here[0]['page']), '▶ play it')}.</p>") if here else ""
    decomposition = dashboard("/views/run-why.base", f"{row['device']}: residual decomposition") if station_key(row["device"]) in dep.decompositions else ""
    return (f"<p>Why {e(row['device'])}, the station this run is on, fails: {plural(sum(1 for w in rows if w['status'] != 'pass'), 'open cell')}.</p>"
            + note + decomposition + why_rows(dep, rows, with_device=False))


def run_diagnostics_rows(site, row: dict) -> list[dict]:
    path = site.data / row["deployment"] / "runs" / row["run"] / "diagnostics.json"
    return adapter._rows(path)


def run_diagnostics(site, row: dict) -> str:
    rows = run_diagnostics_rows(site, row)
    body = [[e(d.get("title")), chip(d.get("verdict")), e(num(d.get("value"))), e(d.get("unit") or ""), e(num(d.get("warn_hi"))), e(num(d.get("error_hi"))),
             e(d.get("message") or ""), file_link(d.get("evidence"))] for d in rows]
    return table(["Diagnostic", "Verdict", "Value", "Unit", "Warn above", "Error above", "What it measured", "Evidence"], body, cls="s2r-table s2r-dx",
                 caption="Computed from this run's data by robotdx.diagnostics: real vs target, each model against real, board temperature, faults and the "
                         "sample rate. An evidence link opens the playback at its window.")


def run_evidence(site, row: dict) -> str:
    folder = f"/data/{row['deployment']}/runs/{row['run']}/"
    files = " · ".join(a(folder + name, name) for name in ("samples.json", "poses.json", "diff_samples.json", "diff_poses.json", "run.json", "diagnostics.json"))
    keep = ("run", "started", "session", "day", "device", "kind", "duration_s", "samples", "rate_hz", "gains", "situations", "compare", "npz", "round", "basis", "clock_offset_s")
    fields = table(["Field", "Value"], [[e(k), file_link(row[k]) if k == "npz" else e(", ".join(row[k]) if isinstance(row[k], list) else num(row[k]))]
                                         for k in keep if k in row], caption="This run as runs.json records it")
    return f"<h2>The recording</h2>{fields}<h2>The tables this page reads</h2><p>{files}</p>"


# --- the home and the lists -------------------------------------------------------------------------------------------

def app_icon() -> str:
    return '<span class="pic plate"><img src="/static/sim2real-app.svg" class="ph" alt="" loading="lazy"></span>'


def home_body(site: Site) -> str:
    groups = []
    deps = site.deployments
    groups.append(Group("deployments", "Deployments", "/deployments/", len(deps),
                        tuple(tile(deployment_url(d.id), d.row["title"], len(d.runs), app_icon()) for d in deps)))
    tiles = tuple(tile(st.url, st.device, len(st.deployment.runs_of(st.device)),
                       f'<span class="pic" data-thumb>{strip_svg(st.deployment, st.device)}</span>') for st in site.stations)
    groups.append(Group("stations", "Stations", "/stations/", len(tiles), tiles))
    frame = tile_home("sim2real: how close each twin is to its real hardware", "Choose", groups)
    where = "".join(f"""<h2 id="where-h">Where it fails · {e(dep.row["title"])}</h2>
{standing_line(dep)}
<div id="where">{matrix(dep)}</div>""" for dep in deps)
    newest = sorted(site.runs, key=lambda r: r["started"], reverse=True)[:NEWEST]
    runs = table(["Started", "Run", "Station", "Kind", "Situations"],
                 [[e(when(r["started"])), a(run_url(r), r["title"]), a(station_url(r["deployment"], r["device"]), r["device"]), e(r.get("kind") or ""), e(r.get("compare") or "")]
                  for r in newest])
    return f"""{frame}
{where}
<h2>Newest runs</h2>{runs}<p>{a("/runs/", f"Every run ({len(site.runs):,})")}</p>
<h2>Analysis</h2>
<ul class="s2r-analyses"><li>{a("/analysis/why-it-fails/", "Why it fails")}: every gate cell that does not pass, in words: the number against its limit, why, and the next step.</li>
<li>{a("/analysis/gate-standing/", "Gate standing")}: the stations × gates matrix, passing per gate and per station, and the caveats on the numbers.</li></ul>
<h2>About</h2>
<p class="lede">How close each digital twin is to its real hardware, and where it falls short. Every run is played back real (blue) against every
model (orange) that replayed it; the gates (T1-T11 per station) divide each error by the device's own run-to-run floor, and ≤ 1.5× is twinned.</p>"""


def deployments_body(site: Site) -> str:
    rows = [[a(deployment_url(d.id), d.row["title"]), e(d.row.get("kind") or ""), e(d.row.get("where") or ""), str(d.row.get("stations")),
             f'{d.row.get("runs"):,}', e(when(d.row.get("last_run"))), e(d.row.get("gate_summary") or ""), e(d.row.get("gates_source") or "")] for d in site.deployments]
    return f"<h1>Deployments ({len(site.deployments)})</h1>" + table(["Deployment", "Kind", "Where", "Stations", "Runs", "Last run", "Gates", "Gates from"], rows)


def stations_body(site: Site) -> str:
    out = [f"<h1>Stations ({len(site.stations)})</h1>"]
    for dep in site.deployments:
        out.append(f"<h2>{a(deployment_url(dep.id), dep.row['title'])}</h2>{standing_line(dep)}{matrix(dep)}")
        out.append(table(["Station", "What it is", "Runs", "Gates passing", "Open cells"],
                         [[a(station_url(dep.id, d["device"]), d["device"]), e(d.get("station") or ""), f'{d.get("runs", 0):,}',
                           f'{sum(1 for g in dep.gates_of(d["device"]) if g["verdict"] == "pass")} of {len(dep.gates_of(d["device"]))}',
                           e(", ".join(w["gate_id"] for w in dep.why_of(d["device"]) if w["status"] != "pass") or "—")]
                          for d in sorted(dep.devices, key=lambda d: d.get("order", 0))]))
    return "".join(out)


def runs_list(site: Site, label: str) -> tuple[str, str]:
    """(the filter column, the results) of every run: the kit's rail, and <data-views> on /views/runs.base with the server
    table inside it as the reading without JavaScript."""
    from catalog_workbench.data_ui import views_element  # noqa: PLC0415
    aside = '<data-facets for="parts-views" class="rail"></data-facets>\n<noscript><p>The filters need JavaScript; the full table is on the right.</p></noscript>'
    rows = sorted(site.runs, key=lambda r: r["started"], reverse=True)
    body = "\n".join(f'<tr><td>{a(run_url(r), r["title"])}</td><td>{e(r["device"])}</td><td>{e(when(r["started"]))}</td><td>{e(r.get("kind") or "")}</td>'
                     f'<td>{e(r.get("compare") or "")}</td></tr>' for r in rows)
    inner = f"""<div class="scroll"><table id="parts"><caption>{e(label)}: one row per real run, newest first.</caption>
<thead><tr><th scope="col">Run</th><th scope="col">Station</th><th scope="col">Started</th><th scope="col">Kind</th><th scope="col">Situations</th></tr></thead>
<tbody>
{body}
</tbody></table></div>"""
    return aside, views_element("parts-views", "/views/runs.base", label, inner, attrs='toolbar="bar" filters="pills"')


def runs_base(site: Site) -> str:
    """/views/runs.base: every run as one list (the search page reads it too)."""
    return """# sim2real · every run (the /runs/ and /search/ lists). Written by site/pages.py.
data: /data/search.json
facets:
  - { as: current, label: Your filters }
  - { property: title, as: search, properties: [title, device, kind, session, compare], label: Find, placeholder: "Run, station or kind" }
  - { property: device, label: Station }
  - { property: kind, label: Kind, limit: 8 }
  - { property: compare, label: Situations }
  - { property: day, label: Day }
  - { property: verdict, label: Twinned? }
properties:
  title: { displayName: Run }
  device: { displayName: Station }
  started: { displayName: Started }
  kind: { displayName: Kind }
  compare: { displayName: Situations }
  duration_s: { displayName: Duration }
  gains: { displayName: Gains (board) }
  tracking_mrad: { displayName: Real vs target }
  best_model: { displayName: Closest model }
  verdict: { displayName: Twinned? }
  day: { displayName: Day }
  session: { displayName: Session }
  url: { displayName: Open }
views:
  - type: table
    name: Runs
    open: { mode: link, url: url }
    order: [title, device, started, kind, compare, duration_s, gains, tracking_mrad, best_model, verdict]
    sort:
      - { property: started, direction: DESC }
"""


def search_rows(site: Site) -> str:
    keep = ("title", "device", "started", "kind", "compare", "duration_s", "gains", "tracking_mrad", "best_model", "verdict", "day", "session")
    rows = [{**{k: r.get(k) for k in keep}, "id": r["run"], "url": run_url(r)} for r in sorted(site.runs, key=lambda r: r["started"], reverse=True)]
    return json.dumps({"id": "runs", "title": "Every run", "titleProperty": "title", "linkProperty": "url", "rows": rows},
                      ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


# --- the Analysis area ------------------------------------------------------------------------------------------------

def why_report(site: Site) -> tuple[str, str]:
    """(article, toc) of Analysis › Why it fails: every open cell grouped by station, fails first."""
    parts, toc = [], []
    for dep in site.deployments:
        parts.append(f"<h1>Why it fails</h1><p class=\"lede\">{e(dep.row['title'])}: every gate cell the newest acceptance does not pass, and each "
                     f"pass that turns into a fail under the pooled floor, in words. Grouped by station; each says the number against its limit, why, "
                     f"the evidence and its uncertainty, and the next discriminating test or what is blocked on Zach.</p>{standing_line(dep)}"
                     f"{matrix(dep)}")
        for st in sorted(dep.devices, key=lambda d: d.get("order", 0)):
            rows = dep.why_of(st["device"])
            if not rows:
                continue
            key = station_key(st["device"])
            fails = sum(1 for w in rows if w["status"] != "pass")
            toc.append(f'<li><a href="#{e(key)}">{e(st["device"])} <span class="n">({fails})</span></a></li>')
            parts.append(f'<h2 id="{e(key)}">{a(station_url(dep.id, st["device"]), st["device"])} · {plural(fails, "open cell")}</h2>'
                         f'<p class="mut">{e(st.get("station") or "")}</p>{gate_chips(dep, st["device"])}{why_rows(dep, rows, with_device=False)}')
    toc_html = f'<p class="an-toc-h">Stations</p><ul>{"".join(toc)}</ul>'
    return "".join(parts), toc_html


def standing_report(site: Site) -> tuple[str, str]:
    parts, toc = ["<h1>Gate standing</h1>"], []
    for dep in site.deployments:
        per_gate = []
        for gid, name in gate_ids(dep):
            cells = [g for g in dep.gates if g["gate"].split()[0] == gid]
            per_gate.append([e(name), f'{sum(1 for g in cells if g["verdict"] == "pass")} of {len(cells)}',
                             e(", ".join(g["device"] for g in cells if g["verdict"] != "pass") or "—")])
        caveats = "".join(f"<li><strong>{e(c['caveat'])}.</strong> {e(c['detail'])}</li>" for c in dep.caveats)
        sources = "".join(f"<li>{e(r['kind'])} · {e(r.get('dated') or '')} · {file_link(r.get('file'))}</li>" for r in dep.evidence)
        parts.append(f"""<p class="lede">The KPI: how many of {e(dep.row['title'])}'s station gate cells pass (T1-T11 on each of {len(dep.devices)} stations). A cell passes when the twin's error is within the gate's limit, most of them 1.5× the station's own run-to-run floor.</p>
{standing_line(dep)}
<h2 id="matrix">Stations × gates</h2>{matrix(dep)}
<h2 id="per-gate">Passing per gate</h2>{table(["Gate", "Passing", "Not passing"], per_gate)}
<h2 id="caveats">Caveats on the numbers</h2><ul class="s2r-caveats">{caveats}</ul>
<h2 id="sources">Where the numbers come from</h2><ul>{sources}</ul>""")
        toc += ['<li><a href="#matrix">Stations × gates</a></li>', '<li><a href="#per-gate">Passing per gate</a></li>',
                '<li><a href="#caveats">Caveats</a></li>', '<li><a href="#sources">Sources</a></li>']
    return "".join(parts), f'<p class="an-toc-h">Contents</p><ul>{"".join(toc)}</ul>'


def analysis_list(site: Site, reports) -> str:
    items = "".join(f'<li>{a(f"/analysis/{r.slug}/", r.title)}<br><span class="mut">{e(r.description)}</span></li>' for r in reports)
    return f"""<div class="an-listhead"><h1>Analysis</h1>
<p class="an-lede">Standard analyses over every deployment's gates and runs, each one page built from the same tables as the record pages.</p></div>
<ul class="s2r-analyses">{items}</ul>"""
