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

def list_body(site) -> str:
    out = ['<h1>Types</h1>', '<p class="lede">One card per part type: the black-box metrics, the model and its parameters, what the inputs must cover, '
           'the standard view and the shared procedure. The cards are code (<code>type_cards/registry.py</code>); '
           'the vault note is rendered from the same registry.</p>']
    for group, label in GROUPS:
        rows = []
        for t in records(site):
            c = t.card
            if c.group != group:
                continue
            proposed = sum(1 for m in c.metrics if not m.robotdx)
            verdict, word = OBS[c.observability.today]
            rows.append(f'<tr data-type="{e(c.id)}"><th scope="row"><a href="{type_url(c.id)}">{e(c.title)}</a></th>'
                        f'<td>{len(c.metrics)} ({proposed} proposed)</td><td>{len(c.model.parameters)}</td>'
                        f'<td>{e(", ".join(a.name for a in c.coverage.axes))}</td><td>{code(c.view.template) if c.view.template else "proposed"}</td>'
                        f'<td>{chip(verdict, word)}</td><td>{len(t.stations) or "—"}</td></tr>')
        out.append(f"<h2>{label}</h2>" + table(["Type", "Metrics", "Model params", "Coverage axes", "View (data-ui)", "Measurable today", "Stations"], rows, cls="s2r-table s2r-types"))
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
        ("Metrics", f"{len(c.metrics)} ({sum(1 for m in c.metrics if not m.robotdx)} proposed)"), ("Model parameters", str(len(c.model.parameters))),
        ("Coverage axes", str(len(c.coverage.axes))), ("Measurable today", word)))
    return (f'<h1>{e(c.title)}</h1>\n<p class="sub">{e(c.group.title())} · Zach\'s word: {e(c.zach)} · {rdx}</p>\n'
            f'<dl class="s2r-kpis">{kpis}</dl>\n' + "\n".join(lines))


# --- the tabs ------------------------------------------------------------------------------------------------------------

def metrics_tab(site, t: TypeRecord) -> str:
    c = t.card
    rows = [tr([e(m.title), chip("pass" if m.family == "performance" else "partial", m.family), e(m.defined_on), e(m.unit),
                code(m.robotdx) if m.robotdx else f"<b>proposed:</b> {e(m.proposed)}", e(m.normalised), e(m.gate or "—"), "yes" if m.today else "no"],
               metric=m.id, family=m.family, robotdx=m.robotdx or "") for m in c.metrics]
    floor = f'<p><b>Floor:</b> {code(c.floor.robotdx) + ": " if c.floor.robotdx else ""}{e(c.floor.rule)}.</p>'
    return ('<p class="lede">Black box and output-only: <b>performance</b> is the device against its commanded target; <b>fidelity</b> is the twin '
            'against the real device on the same input. Each is divided by the device\'s own repeatability floor where one is measurable. '
            f'Ids are RobotDx stock-catalog entries (io-diagnostics {code(reg.ROBOTDX_COMMIT)}).</p>'
            + table(["Metric", "Family", "Defined on", "Unit", "RobotDx id", "÷ floor", "Gate", "Today"], rows) + floor)


def model_tab(site, t: TypeRecord) -> str:
    m = t.card.model
    word = {"yes": "yes", "partial": "partly", "no": "no"}
    rows = [tr([code(p.name), e(p.unit), e("—" if p.nominal is None else str(p.nominal)), e(p.source), e(p.identified_by),
                chip(OBS[p.observable][0], word[p.observable]), e(p.note)], param=p.name, observable=p.observable) for p in m.parameters]
    return (f'<p class="lede"><b>{e(m.name)}</b> · robotparts {code(m.robotparts) if m.robotparts else "none"}{(" · " + e(m.proposed)) if m.proposed else ""}.</p>'
            f"<p>{code(m.equation)}</p>"
            + table(["Parameter", "Unit", "Nominal", "Source", "Identified by", "Outputs see it?", "Note"], rows)
            + "<p>Parameters are levers: improving the model and its calibration should move the metrics, never be one.</p>")


def coverage_map(sched) -> str:
    """CAN 11's train targets on the q × qd plane: per cell, the share of its reachable qdd cells the plan visits (grey: planned,
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
    return (f'<figure class="s2r-covfig"><svg class="s2r-cov" viewBox="0 0 {width} {height}" width="{width}" role="img" aria-label="CAN 11 planned train coverage, q by qd" '
            f'style="max-width:100%;height:auto;color:currentColor;fill:currentColor">{"".join(rects)}{ylabels}{xlabels}'
            f'<text x="{left + len(qc) * w / 2}" y="{height - 4}" text-anchor="middle" font-size="11">q (rad from origin) →</text></svg>'
            f'<figcaption>CAN 11 · train targets on q × qd (rows: qd from its lower edge, rad/s). Shade: share of the cell\'s reachable qdd cells visited; '
            f'outlined: not visited.</figcaption></figure>')


def coverage_tab(site, t: TypeRecord) -> str:
    c = t.card
    axes = table(["Axis", "Unit", "Binning"], [tr([e(a.name), e(a.unit), e(a.binning)], axis=a.name) for a in c.coverage.axes])
    out = [f'<p class="lede">{e(c.coverage.rule)}.' + (f" RobotDx: {code(c.coverage.robotdx)}." if c.coverage.robotdx else "")
           + (f" A plan comes from: {e(c.coverage.plan_source)}." if c.coverage.plan_source else "") + "</p>", axes]
    planned = [(st, s) for st, s in t.stations if s]
    if planned:
        rows = []
        for st, s in planned:
            train, held = cov.servo_coverage(s), cov.servo_coverage(s, split="held_out")
            same = train.pct == s["coverage"]["train"]["pct_reachable"]
            rows.append(tr([f'<a href="{st.url}#schedule">{e(st.device)}</a>', code(s["digest"]), f"<b>{train.pct} %</b>", f"{held.pct} %", f"{train.visited} of {train.reachable}",
                            f"{train.axes['load torque']} %", "not planned", chip("pass" if same else "fail", f"schedule.py: {s['coverage']['train']['pct_reachable']} %")],
                           station=st.key, train_pct=train.pct, held_out_pct=held.pct))
        out.append("<h2>Planned coverage, before anything runs</h2>"
                   + table(["Station", "Schedule", "Train (q, qd, qdd)", "Held out", "Cells", "Load torque", "Temperature", "Producer's number"], rows,
                           caption="Every station of this type with a schedule (bam_rack_twin.schedule), scored by this card's coverage function"))
        out.append(coverage_map(planned[0][1]))
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
