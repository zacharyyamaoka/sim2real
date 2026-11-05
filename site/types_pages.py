"""The Types area: one record per part type, drawn from type_cards/registry.py (the code is the spec; these pages only show it).

WHY a record kind of its own (Zach, PROJECT - Sim2Real, Nov 4 2026: "for each 'type' of actuator, sensor robot I think we need like
the models, and then the dashboards to view the results"): a type is what a station *is*, so a station links to its card, and the
card's Coverage tab shows the planned coverage of every station of that type that has a schedule, computed by the card's own
function from the producer's schedule.json (never re-typed). Static HTML: a card reads at once and without JavaScript.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from catalog_workbench.html import e

import adapter
from adapter import deployment_url, station_url

if str(adapter.REPO) not in sys.path:
    sys.path.append(str(adapter.REPO))  # appended, so the repo's own site/ folder never shadows the stdlib's `site`

from type_cards import coverage as cov  # noqa: E402
from type_cards import registry as reg  # noqa: E402

GROUPS = (("actuator", "Actuators"), ("sensor", "Sensors"))
OBS = {"yes": ("pass", "yes"), "partial": ("partial", "partly"), "no": ("not_run", "no")}
KIND = {"physics": ("none", "physics"), "residual": ("partial", "grey-box residual"), "learned": ("warn", "black-box net")}
FAMILIES = (("performance", "Performance: the real device against its target"), ("fidelity", "Fidelity: the twin against the real device, same input"))
STATUS = {"exists": "pass", "partial": "partial", "proposed": "not_run", "unknown": "not_run"}
REPO_SHORT = {"/home/bam/bam_ws": "bam_ws", "/home/bam/io-diagnostics": "io-diagnostics", "/home/bam/robotparts": "robotparts", "/home/bam/pidtuna": "pidtuna"}
KEYS_NOTE = ("M0–M5 are physics: on the actuators robotparts publishes (servo, motor, gearbox, conveyor) they follow robotparts' ladder "
             "(M0 ideal, M2 Coulomb + viscous, M3 Stribeck / load, M4 ripple + backlash, M5 motor electrics; its M1 is the datasheet, here "
             "every parameter's Nominal), and every other card defines its own. A .wear rung takes usage as an input. M6 is always the "
             "grey-box residual and M7 always the black-box net.")


@dataclass
class TypeRecord:
    card: reg.Card
    stations: list = field(default_factory=list)   # [(Station, schedule doc or None)]

    @property
    def id(self) -> str:
        return self.card.id


def type_url(card_id: str) -> str:
    return f"/types/{card_id}/"


def station_type(st) -> str | None:
    """The card a station is: devices.json's `type` (every rack station is a servo)."""
    kind = (st.row.get("type") or "").lower()
    return kind if kind in reg.CARDS else None


def _schedule(st):
    path = adapter.SCHEDULES / st.deployment.id / st.key / "schedule.json"
    return json.loads(path.read_text()) if st.key in st.deployment.schedules and path.is_file() else None


def records(site) -> list[TypeRecord]:
    cached = getattr(site, "_types", None)
    if cached is None:
        by_type = {cid: TypeRecord(card) for cid, card in reg.CARDS.items()}
        for st in site.stations:
            t = station_type(st)
            if t:
                by_type[t].stations.append((st, _schedule(st)))
        cached = site._types = list(by_type.values())
    return cached


def chip(verdict: str, text: str) -> str:
    return f'<span class="s2r-v s2r-{e(verdict)}">{e(text)}</span>'


def code(text) -> str:
    return f"<code>{e(text)}</code>"


def table(head, rows, caption="", cls="s2r-table") -> str:
    th = "".join(f'<th scope="col">{h}</th>' for h in head)
    cap = f"<caption>{caption}</caption>" if caption else ""
    return f'<div class="s2r-scroll"><table class="{cls}">{cap}<thead><tr>{th}</tr></thead><tbody>\n' + "\n".join(rows) + "\n</tbody></table></div>"


def tr(cells, **data) -> str:
    attrs = "".join(f' data-{k.replace("_", "-")}="{e(str(v))}"' for k, v in data.items())
    return f"<tr{attrs}>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


# --- the list and the header ---------------------------------------------------------------------------------------------

def ladder_text(c) -> str:
    """Each rung's key and its parameter count, lowest first: what /types/ shows of a card's ladder."""
    return " · ".join(f'<span class="s2r-rungkey" title="{e(r.name)}" style="white-space:nowrap">{e(r.key)} {r.n_parameters:,}</span>' for r in c.rungs)


def code_home(h) -> str:
    where = f"{REPO_SHORT.get(h.repo, h.repo)}:{h.path}" + (f" @ {h.ref}" if h.ref else "")
    return f"<li>{code(where)}" + (f" — {e(h.note)}" if h.note else "") + "</li>"


def packages_table(packages, caption="") -> str:
    rows = []
    for pkg in packages:
        serves = ", ".join(f'<a href="{type_url(cid)}">{e(reg.CARDS[cid].title)}</a>' for cid in pkg.serves)
        homes = f'<ul class="s2r-homes">{"".join(code_home(h) for h in pkg.code)}</ul>' if pkg.code else "unknown: no code found"
        refs = "; ".join(ref_link(r) for r in pkg.references)
        rows.append(tr([f"<b>{e(pkg.group)}</b><br>{e(pkg.title)}" + (f" ({e(pkg.level)} level)" if pkg.level else ""), serves, homes,
                        chip(STATUS[pkg.status], pkg.status), e(pkg.note) + (f"<br><small>{refs}</small>" if refs else "")],
                       package=pkg.id, status=pkg.status))
    return table(["Package", "Serves", "Code today", "Status", "Note"], rows, caption=caption, cls="s2r-table s2r-packages")


def list_body(site) -> str:
    out = ['<h1>Types</h1>', '<p class="lede">One card per part type: the black-box metrics and the diagnostics and gates built on them, a ladder of '
           'models from the ideal one to learned nets (each counted, each with where to learn it), the tests that identify them on the bench '
           'and in a deployment, what the inputs must cover, the standard view and the shared procedure. The cards are code '
           '(<code>type_cards/registry.py</code>, its API <code>type_cards/CONTRACT.md</code>); the vault note is rendered from the same registry.</p>',
           f'<p class="lede">{e(KEYS_NOTE)} The rule that picks one: {e(reg.SELECTION_RULE)}.</p>']
    for group, label in GROUPS:
        rows = []
        for t in records(site):
            c = t.card
            if c.group != group:
                continue
            proposed = sum(1 for m in c.metrics if not m.robotdx)
            verdict, word = OBS[c.observability.today]
            rows.append(f'<tr data-type="{e(c.id)}" data-rungs="{len(c.rungs)}"><th scope="row"><a href="{type_url(c.id)}">{e(c.title)}</a></th>'
                        f'<td data-col="rungs">{ladder_text(c)}</td>'
                        f'<td>{len(c.metrics)} ({proposed} proposed)</td><td>{len(c.model.parameters)}</td>'
                        f'<td>{e(", ".join(a.name for a in c.coverage.axes))}</td><td>{code(c.view.template) if c.view.template else "proposed"}</td>'
                        f'<td>{chip(verdict, word)}</td><td>{len(t.stations) or "—"}</td></tr>')
        out.append(f"<h2>{label}</h2>" + table(["Type", "Model rungs (parameters)", "Metrics", "Today's model params", "Coverage axes", "View (data-ui)",
                                               "Measurable today", "Stations"], rows, cls="s2r-table s2r-types"))
    out.append("<h2>Calibration packages</h2><p>Zach's packages: each calibrates a slice of the types and has its own algorithms. Where the code "
               "lives today (found by reading bam_ws, io-diagnostics, robotparts and pidtuna; every path checked to exist at its ref):</p>"
               + packages_table(reg.CALIBRATION_PACKAGES))
    return "".join(out)


def header(site, t: TypeRecord) -> str:
    c = t.card
    verdict, word = OBS[c.observability.today]
    members = ", ".join(f'{m.count} × <a href="{type_url(m.card)}">{e(reg.CARDS[m.card].title)}</a>' if m.card in reg.CARDS else f"{m.count} × {e(m.card)} (RobotDx part type, no card)"
                        for m in c.members)
    used = [o for o in reg.CARDS.values() if any(m.card == c.id for m in o.members)]
    stations = " · ".join(f'<a href="{st.url}">{e(st.device)}</a>' for st, _s in t.stations)
    lines = [f"<p><b>In:</b> {e(c.inputs)}. <b>Out:</b> {e(c.outputs)}.</p>"]
    if members:
        lines.append(f"<p><b>Made of:</b> {members}." + (f" <b>Error budget:</b> {e(c.error_budget)}." if c.error_budget else "") + "</p>")
    if used:
        lines.append("<p><b>Part of:</b> " + ", ".join(f'<a href="{type_url(o.id)}">{e(o.title)}</a>' for o in used) + ".</p>")
    if stations:
        lines.append(f"<p><b>Stations of this type:</b> {stations}.</p>")
    lines.append(f"<p>{chip(verdict, 'measurable today: ' + word)} With {e('; '.join(c.observability.instruments))}."
                 + (f" <b>It needs</b> {e('; '.join(c.observability.needs))}." if c.observability.needs else "") + "</p>")
    rdx = f"RobotDx part type {code(c.robotdx_part)}" if c.robotdx_part else f"no RobotDx part type ({e(c.robotdx_gap)})"
    kpis = "".join(f"<div><dt>{e(k)}</dt><dd>{v}</dd></div>" for k, v in (
        ("Metrics", f"{len(c.metrics)} ({sum(1 for m in c.metrics if not m.robotdx)} proposed)"), ("Model rungs", str(len(c.rungs))),
        ("Today's model", f"{reg.current_rung(c).key if c.rungs else '—'} · {len(c.model.parameters)} params"), ("Gates", str(len(c.gates))),
        ("Test types", str(len(c.tests))), ("Measurable today", word)))
    return (f'<h1>{e(c.title)}</h1>\n<p class="sub">{e(c.group.title())} · Zach\'s word: {e(c.zach)} · {rdx}</p>\n'
            f'<dl class="s2r-kpis">{kpis}</dl>\n' + "\n".join(lines))


# --- the tabs ------------------------------------------------------------------------------------------------------------

def metrics_tab(site, t: TypeRecord) -> str:
    c = t.card
    out = ['<p class="lede">Black box and output-only: they read inputs and outputs, never a model parameter. <b>Performance</b> is the real device '
           'against its commanded target; <b>fidelity</b> is the twin against the real device on the same input. Each is divided by the device\'s own '
           f'repeatability floor where one is measurable. Ids are RobotDx stock-catalog entries (io-diagnostics {code(reg.ROBOTDX_COMMIT)}). '
           'A metric no gate reads is <b>observed</b>, not gated.</p>']
    for family, caption in FAMILIES:
        rows = [tr([e(m.title), e(m.defined_on), e(m.unit), code(m.robotdx) if m.robotdx else f"<b>proposed:</b> {e(m.proposed)}", e(m.normalised),
                    chip("pass" if reg.metric_status(c, m.id) == "gated" else "none", reg.metric_status(c, m.id)), e(m.gate or "—"), "yes" if m.today else "no"],
                   metric=m.id, family=m.family, robotdx=m.robotdx or "", status=reg.metric_status(c, m.id)) for m in c.metrics if m.family == family]
        out.append(table(["Metric", "Defined on", "Unit", "RobotDx id", "÷ floor", "Status", "Acceptance", "Today"], rows, caption=e(caption))
                   .replace('<table class="s2r-table">', f'<table class="s2r-table" data-family="{family}">', 1))
    out.append(f'<p><b>Floor:</b> {code(c.floor.robotdx) + ": " if c.floor.robotdx else ""}{e(c.floor.rule)}.</p>')
    gate_of = {g.diagnostic: g for g in c.gates}
    titles = {m.id: m.title for m in c.metrics}
    rows = []
    for d in c.diagnostics:
        g = gate_of.get(d.id)
        warn = f"{e(d.message)}" if d.kind == "drift" else ""
        fine = f"{e(d.threshold.text())}" + (" (settable)" if d.settable else "")
        target = (f"{e(g.target.text())}" + (f" · {e(g.acceptance)}" if g.acceptance else "")) if g else "— (observed)"
        forecast = (f"<br><small>Forecast: {e(d.forecast.usage)} left until the threshold, from the {e(d.forecast.law)} law of "
                    f"{e(', '.join(d.forecast.parameters))}.</small>" if d.forecast else "")
        rows.append(tr([f"{chip('warn' if d.kind == 'drift' else 'none', d.kind)} {e(titles.get(d.metric, d.metric))}",
                        fine + (f"<br><b>{warn}</b>" if warn else "") + forecast + (f"<br><small>{e(d.note)}</small>" if d.note else ""),
                        target, code(d.robotdx) if d.robotdx else "—"], diagnostic=d.id, kind=d.kind, gate=g.id if g else ""))
    out.append("<h2>Diagnostics and gates</h2><p>A <b>diagnostic</b> is a metric plus a threshold: past it, a warning. A <b>gate</b> is a diagnostic "
               "with a target: pass or fail. The drift diagnostic divides fidelity on live data by its calibrated value.</p>"
               + table(["Diagnostic (reads)", "Fine while (threshold)", "Gate target", "RobotDx"], rows))
    return "".join(out)


def ref_short(ref) -> str:
    """'Hwangbo et al. 2019' from 'Hwangbo, Lee, ... (2019). Title. Venue.'; a doc keeps its title: 'MuJoCo 2026: XML reference: ...'."""
    head, _, rest = ref.title.partition(" (")
    year, _, after = rest.partition(").")
    authors = [a for a in head.split(", ") if a]
    who = authors[0] + (" et al." if len(authors) > 2 else f" & {authors[1]}" if len(authors) == 2 else "")
    label = f"{who} {year}".strip()
    if ref.kind in ("doc", "standard", "code"):
        label += ": " + after.strip().rstrip(".")
    return label


def ref_link(ref) -> str:
    """A reference as a short link, the full citation (and what the rung uses it for) in its tooltip."""
    tip = e(ref.title + (f" — {ref.note}" if ref.note else ""))
    label = e(ref_short(ref))
    return f'<a href="{e(ref.url)}" title="{tip}">{label}</a>' if ref.url else f'<span title="{tip}">{label}</span>'


def model_tab(site, t: TypeRecord) -> str:
    c = t.card
    m = c.model
    word = {"yes": "yes", "partial": "partly", "no": "no"}
    out = [f'<p class="lede">{e(KEYS_NOTE)}</p>', f"<p><b>Selection rule:</b> {e(reg.SELECTION_RULE)}.</p>"]
    rows = []
    below: set[str] = set()
    for r in c.rungs:
        kind_v, kind_w = KIND[r.kind]
        names = ", ".join(f"<b>{e(n)}</b>" if n not in below else e(n) for n in r.parameter_names) or "—"
        size = f"{r.n_parameters:,}" + (f" <small>({r.n_named} named + {r.architecture.weights:,} weights)</small>" if r.architecture and r.n_named else
                                       " <small>weights</small>" if r.architecture else "")
        need = r.needs
        needs = (f"{need.min_pct:g} % of cells × ≥ {need.min_samples} samples" + ("" if need.extrapolates else "; no extrapolation")
                 + (f"; {need.deployment_weighted_pct:g} % deployment-weighted" if need.deployment_weighted_pct else "")) if need else "—"
        refs = "<br>".join(ref_link(x) for x in r.references)
        current = ' <span class="s2r-v s2r-pass">today\'s model</span>' if r.current else ""
        rows.append(f'<tr data-rung="{e(r.key)}" data-kind="{e(r.kind)}" data-n-params="{r.n_parameters}" data-current="{str(r.current).lower()}">'
                    f'<th scope="row">{e(r.key)}{current}</th><td>{e(r.name)}<br><small>{e(r.equation)}</small></td><td>{chip(kind_v, kind_w)}</td>'
                    f'<td>{size}</td><td>{names}</td><td>{e(needs)}</td><td>{code(r.robotparts) if r.robotparts else "—"}<br><small>{e(r.implemented)}</small></td>'
                    f'<td class="s2r-refs">{refs}</td></tr>')
        below = set(r.parameter_names)
    out.append("<h2>The ladder</h2>" + table(["Rung", "Model", "Kind", "Parameters", "Names (new in bold)", "Coverage it needs", "robotparts / runs in", "Learn it"],
                                              rows, caption="Lowest first. A physics rung holds every parameter of the rung below it."))
    learned = [r for r in c.rungs if r.architecture]
    if learned:
        arows = []
        for r in learned:
            a = r.architecture
            hidden = " × ".join(str(h) for h in a.hidden) or "—"
            history = f"{a.history} sample{'s' if a.history != 1 else ''}" + (f", {a.history_dt_s * 1000:g} ms apart" if a.history_dt_s else "")
            arows.append(f'<tr data-arch="{e(r.key)}"><th scope="row">{e(r.key)}</th><td>{e(a.family)}</td><td>{e(", ".join(a.inputs))} × {history} = {a.n_inputs} inputs</td>'
                         f'<td>{e(hidden)}{(" " + e(a.activation)) if a.activation else ""}</td><td>{e(a.output)}</td><td>{a.weights:,}</td>'
                         f'<td>{e(r.base) if r.base else "—"}</td></tr>')
        out.append("<h2>Learned rungs</h2><p>Their size is a weight count, not named parameters. They are judged only on held-out data inside the "
                   f"cells they were trained on; outside, a sample is flagged <b>{e(reg.OUT_OF_COVERAGE)}</b>.</p>"
                   + table(["Rung", "Family", "Inputs × history", "Hidden layers", "Predicts", "Weights", "On rung"], arows))
    worn = [(r, p) for r in c.rungs for p in r.wear_parameters]
    if worn:
        wrows = [tr([e(r.key), code(p.name), e(p.wear.usage) + f" ({e(p.wear.unit)})", e(p.wear.law) + f": {e(reg.WEAR_LAWS[p.wear.law])}", code(p.wear.rate),
                     "; ".join(ref_link(x) for x in reg.WEAR_LAW_REFERENCES[p.wear.law])], wear=p.name) for r, p in worn]
        out.append("<h2>Wear</h2><p>Known wear parameters grow with use; the drift diagnostic's forecast extrapolates the same law to its threshold.</p>"
                   + table(["Rung", "Parameter", "Usage", "Law", "Rate parameter", "Learn it"], wrows))
    first: dict[str, str] = {}
    union = []
    for r in c.rungs:
        for p in r.parameters:
            if p.name not in first:
                first[p.name] = r.key
                union.append(p)
    prow = [tr([code(p.name), e(first[p.name]), e(p.unit), e("—" if p.nominal is None else str(p.nominal)), e(p.source), e(p.identified_by),
                chip(OBS[p.observable][0], word[p.observable]), e(p.role), e(p.note)], param=p.name, observable=p.observable, rung=first[p.name], role=p.role)
            for p in union]
    out.append(f'<h2>Parameters</h2><p>Every named parameter once, with the rung it enters. Today\'s model is <b>{e(m.name)}</b> · robotparts '
               f'{code(m.robotparts) if m.robotparts else "none"}{(" · " + e(m.proposed)) if m.proposed else ""}: {code(m.equation)}.</p>'
               + table(["Parameter", "From", "Unit", "Nominal", "Source", "Identified by", "Outputs see it?", "Role", "Note"], prow)
               + "<p>Parameters are levers: improving the model and its calibration should move the metrics, never be one.</p>")
    return "".join(out)


def tests_tab(site, t: TypeRecord) -> str:
    c = t.card
    rows = []
    for x in c.tests:
        rows.append(tr([e(x.title), chip("pass" if x.setting == "bench" else "partial", x.setting), ", ".join(code(n) for n in x.identifies), e(x.how),
                        e("; ".join(x.needs) or "—"), "recalibrates" if x.recalibration else "—", e(x.exists or "—") + (f" <small>({e(x.duration)})</small>" if x.duration else "")],
                       test=x.id, setting=x.setting, recalibration=str(x.recalibration).lower()))
    settings = " ".join(f"<b>{e(k)}</b>: {e(v)}." for k, v in reg.SETTINGS.items())
    return (f'<p class="lede">The tests that identify this type\'s parameters. {settings} A run is tagged with its setting and its test type.</p>'
            + table(["Test", "Setting", "Identifies", "How", "Needs", "Recalibration", "Today"], rows)
            + "<h2>Calibration packages that serve it</h2>" + packages_table(reg.packages_for(c)))


def coverage_map(sched, st) -> str:
    """One station's train targets on the q × qd plane: per cell, the share of its reachable qdd cells the plan visits (grey: planned,
    never blue or orange, which mean real and sim). Drawn from the card's coverage function's cells."""
    d = sched["description"]
    q_e, qd_e, qdd_e = cov.joint_edges(d)
    result = cov.servo_coverage(sched)
    ok = cov.joint_reachable(d)
    qc, qdc, qddc = cov.centres(q_e), cov.centres(qd_e), cov.centres(qdd_e)
    w, h, left, top = 34, 18, 64, 8
    rects = []
    for i in range(len(qc)):
        for j in range(len(qdc)):
            reach = [k for k in range(len(qddc)) if ok((qc[i], qdc[j], qddc[k]))]
            visited = [k for k in reach if (i, j, k) in result.cells]
            samples = sum(n for (a, b, _k), n in result.cells.items() if a == i and b == j)
            share = len(visited) / len(reach) if reach else 0.0
            fill = "var(--s2r-cov, #8b9099)"
            style = f'fill="{fill}" fill-opacity="{0.12 + 0.88 * share:.3f}"' if samples else 'fill="none" stroke="currentColor" stroke-opacity="0.15"'
            y = top + (len(qdc) - 1 - j) * h
            rects.append(f'<rect data-i="{i}" data-j="{j}" data-samples="{samples}" data-reachable="{len(reach)}" data-visited="{len(visited)}" x="{left + i * w}" y="{y}" '
                         f'width="{w - 2}" height="{h - 2}" {style}><title>q {q_e[i]:.3f}..{q_e[i + 1]:.3f} rad, qd {qd_e[j]:g}..{qd_e[j + 1]:g} rad/s: '
                         f'{len(visited)} of {len(reach)} reachable qdd cells, {samples} samples</title></rect>')
    width, height = left + len(qc) * w + 8, top + len(qdc) * h + 34
    ylabels = "".join(f'<text x="{left - 6}" y="{top + (len(qdc) - 1 - j) * h + h * 0.65}" text-anchor="end" font-size="10">{qd_e[j]:g}</text>' for j in range(len(qdc)))
    xlabels = "".join(f'<text x="{left + i * w + w / 2}" y="{top + len(qdc) * h + 12}" text-anchor="middle" font-size="10">{qc[i]:.2f}</text>' for i in range(0, len(qc), 2))
    return (f'<figure class="s2r-covfig" data-station="{e(st.key)}"><svg class="s2r-cov" viewBox="0 0 {width} {height}" width="{width}" role="img" aria-label="{e(st.device)} planned train coverage, q by qd" '
            f'style="max-width:100%;height:auto;color:currentColor;fill:currentColor">{"".join(rects)}{ylabels}{xlabels}'
            f'<text x="{left + len(qc) * w / 2}" y="{height - 4}" text-anchor="middle" font-size="11">q (rad from origin) →</text></svg>'
            f'<figcaption>{e(st.device)} · train targets on q × qd (rows: qd from its lower edge, rad/s). Shade: share of the cell\'s reachable qdd cells visited; '
            f'outlined: not visited.</figcaption></figure>')


def coverage_tab(site, t: TypeRecord) -> str:
    c = t.card
    axes = table(["Axis", "Unit", "Bin size", "Binning", "Marginal"],
                 [f'<tr data-axis="{e(a.name)}" data-bin-size="{"" if a.bin_size is None else f"{a.bin_size:g}"}" data-marginal="{str(a.marginal).lower()}">'
                  f'<td>{e(a.name)}</td><td>{e(a.unit)}</td><td>{"—" if a.bin_size is None else f"{a.bin_size:g} {e(a.unit)}"}</td><td>{e(a.binning)}</td>'
                  f'<td>{"yes" if a.marginal else "headline"}</td></tr>' for a in c.coverage.axes])
    gate = c.coverage.gate_pct
    needs = "; ".join(f"{r.key} {r.needs.min_pct:g} % × ≥ {r.needs.min_samples}" for r in c.rungs if r.needs and r.kind != "physics")
    out = [f'<p class="lede">{e(c.coverage.rule)}.' + (f" RobotDx: {code(c.coverage.robotdx)}." if c.coverage.robotdx else "")
           + (f" A plan comes from: {e(c.coverage.plan_source)}." if c.coverage.plan_source else "") + "</p>",
           f'<p data-coverage-gate="{gate:g}"><b>Coverage gate:</b> a plan passes when it visits at least {gate:g} % of the reachable headline cells (a '
           f'histogram over the binned space; the plan may sample anywhere in the full space). The learned rungs bind harder: {e(needs or "none on this card")}.</p>'
           if gate is not None else "", axes]
    planned = [(st, s) for st, s in t.stations if s]
    if planned:
        rows = []
        for st, s in planned:
            train, held = cov.servo_coverage(s), cov.servo_coverage(s, split="held_out")
            same = train.pct == s["coverage"]["train"]["pct_reachable"]
            verdict = reg.coverage_gate(c, train)
            q_edges = cov.joint_edges(s["description"])[0]
            q_bin = f"{q_edges[1] - q_edges[0]:.4g}"
            rows.append(tr([f'<a href="{st.url}#schedule">{e(st.device)}</a>', code(s["digest"]), f"<b>{train.pct} %</b>", f"{held.pct} %", f"{train.visited} of {train.reachable}",
                            f"{q_bin} rad",
                            f"{train.axes['load torque']} %", "not planned", chip("pass" if same else "fail", f"schedule.py: {s['coverage']['train']['pct_reachable']} %"),
                            chip(verdict if verdict != "observed" else "none", verdict)],
                           station=st.key, train_pct=train.pct, held_out_pct=held.pct, gate=verdict, q_bin=q_bin))
        out.append("<h2>Planned coverage, before anything runs</h2>"
                   + table(["Station", "Schedule", "Train (q, qd, qdd)", "Held out", "Cells", "q cell", "Load torque", "Temperature", "Producer's number",
                            f"Gate (≥ {c.coverage.gate_pct:g} %)" if c.coverage.gate_pct is not None else "Gate"], rows,
                           caption="Every station of this type with a schedule (bam_rack_twin.schedule), scored by this card's coverage function"))
        # WHY one map per station (2026-11-04): with every servo scheduled, a single map under one station's name was another's plan
        out.extend(coverage_map(sched, st) for st, sched in planned)
    elif t.stations:
        out.append(f"<p>No station of this type has a schedule yet.</p>")
    else:
        out.append("<p>No unit of this type is deployed yet: the axes above are what its first schedule must cover.</p>")
    return "".join(out)


def view_tab(site, t: TypeRecord) -> str:
    v = t.card.view
    if not v.template:
        return f"<p><b>Proposed.</b> {e(v.proposed)}.</p>"
    panels = "".join(f"<li>{e(p)}</li>" for p in v.panels)
    where = ""
    if t.stations:
        st = t.stations[0][0]
        where = f'<p>In sim2real it is drawn on every station page, e.g. <a href="{st.url}">{e(st.device)}</a> (Runs, Gates, Coverage, Schedule).</p>'
    return (f"<p>The standard view is data-ui's {code('gallery/examples/' + v.template)} at {code(reg.data_ui_commit())} (the commit sim2real vendors). Its panels:</p>"
            f'<ul class="s2r-panels">{panels}</ul>{where}' + (f"<p>{e(v.site)}.</p>" if v.site else ""))


def procedure_tab(site, t: TypeRecord) -> str:
    rows = []
    for i, s in enumerate(reg.STEPS, 1):
        tool = t.card.procedure[s.key]
        rows.append(f'<tr data-step="{s.key}" data-status="{tool.status}"><td>{i}</td><th scope="row">{e(s.title)}</th><td>{code(s.artifact)}</td><td>{e(s.does)}</td>'
                    f'<td>{chip("pass" if tool.status == "exists" else "not_run", tool.status)} {e(tool.text)}</td></tr>')
    return ('<p class="lede">The same seven steps for every type. Each writes a file, so a person or an agent can do any step, and the next step reads only that file.</p>'
            + table(["#", "Step", "File", "What", "This type's tool"], rows))


def station_link(st) -> str:
    """The station header's line to its type card."""
    t = station_type(st)
    return f'<p class="s2r-type">Type card: <a class="s2r-type-link" href="{type_url(t)}">{e(reg.CARDS[t].title)}</a></p>' if t else ""
