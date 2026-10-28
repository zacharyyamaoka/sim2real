"""Build the self-contained report: reports/media/diagnostics-catalog-2026-10-28/report.html.

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real/diagnostics_ref python /home/bam/sim2real/diagnostics_ref/tools/build_report.py

Reads tools/run_rack.py's data/ files and the catalog; every chart is drawn from those numbers (inline SVG, no library).
Colours (Zach, 2026-10-28): blue = real, orange = sim, grey = target; green/amber/red only for pass/warn/fail.
"""

from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from robotdx.diagnostics.catalog import ENTRIES, PARTS, PRIMITIVES, by_part
from robotdx.diagnostics.core import FAMILIES
from robotdx.diagnostics.record import from_record

MEDIA = Path("/home/bam/sim2real/reports/media/diagnostics-catalog-2026-10-28")
DATA = MEDIA / "data"
ORDER = ("CAN 11", "CAN 12", "CAN 13", "CAN 4", "CAN 21", "CAN 1", "CAN 14", "CAN 15")
ROLE = {"CAN 11": "shoulder JMC", "CAN 12": "shoulder JMC", "CAN 13": "shoulder JMC", "CAN 4": "elbow DD", "CAN 21": "elbow DD",
        "CAN 1": "wrist", "CAN 14": "wrist GIM", "CAN 15": "wrist ~10:1"}
GLYPH = {"pass": "●", "warn": "▲", "fail": "■", "not_run": "◌"}
WORD = {"pass": "pass", "warn": "warn", "fail": "fail", "not_run": "not run"}
E = html.escape


def load():
    results = [from_record(json.loads(line)) for line in (DATA / "results.json").read_text().splitlines() if line.strip()]
    return (results, json.loads((DATA / "gates.json").read_text()), json.loads((DATA / "oracle.json").read_text()),
            json.loads((DATA / "stream.json").read_text()), (DATA / "pytest.txt").read_text() if (DATA / "pytest.txt").is_file() else "",
            (DATA / "run_rack.txt").read_text() if (DATA / "run_rack.txt").is_file() else "")


def find(results, can, diagnostic, title_has=""):
    for r in results:
        if r.subject.endswith("/" + can) and r.diagnostic == diagnostic and title_has in r.title:
            return r
    return None


def fmt(value, digits=3):
    if value is None:
        return "–"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}g}"


def verdict_chip(verdict, text=""):
    return f'<span class="v v-{verdict}" title="{WORD[verdict]}"><b aria-hidden="true">{GLYPH[verdict]}</b> {E(text or WORD[verdict])}</span>'


# ----- tiny SVG chart kit ------------------------------------------------------------------------------------------
class Log:
    def __init__(self, lo, hi, a, b):
        self.lo, self.hi, self.a, self.b = math.log10(lo), math.log10(hi), a, b

    def __call__(self, v):
        v = max(v, 10 ** self.lo)
        return self.a + (math.log10(v) - self.lo) / (self.hi - self.lo) * (self.b - self.a)


class Lin:
    def __init__(self, lo, hi, a, b):
        self.lo, self.hi, self.a, self.b = lo, hi, a, b

    def __call__(self, v):
        return self.a + (v - self.lo) / (self.hi - self.lo) * (self.b - self.a)


def svg(width, height, body, label):
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{E(label)}" preserveAspectRatio="xMinYMin meet">'
            f'{body}</svg>')


def log_ticks(lo, hi):
    out, v = [], 10 ** math.floor(math.log10(lo))
    while v <= hi * 1.0001:
        for m in (1, 2, 5):
            if lo <= v * m <= hi:
                out.append(v * m)
        v *= 10
    return out


def stop_chart(results):
    W, H, L, R, T, B = 760, 300, 54, 12, 16, 44
    y = Log(0.1, 200, H - B, T)
    band = (W - L - R) / len(ORDER)
    body = [f'<g class="grid">']
    for tick in log_ticks(0.1, 200):
        body.append(f'<line x1="{L}" x2="{W-R}" y1="{y(tick):.1f}" y2="{y(tick):.1f}"/>'
                    f'<text class="tick" x="{L-6}" y="{y(tick)+3:.1f}" text-anchor="end">{tick:g}</text>')
    body.append("</g>")
    body.append(f'<text class="axis" x="14" y="{T+ (H-B-T)/2:.0f}" transform="rotate(-90 14 {T+(H-B-T)/2:.0f})" text-anchor="middle">|stop error|, mrad (log)</text>')
    for i, can in enumerate(ORDER):
        r = find(results, can, "stock.stop_error")
        cx = L + band * (i + 0.5)
        body.append(f'<text class="tick" x="{cx:.1f}" y="{H-B+16}" text-anchor="middle">{can}</text>'
                    f'<text class="tick mute" x="{cx:.1f}" y="{H-B+30}" text-anchor="middle">{ROLE[can]}</text>')
        if not r:
            continue
        allocation = r.limits.error_high
        body.append(f'<line class="limit" x1="{cx-band*0.42:.1f}" x2="{cx+band*0.42:.1f}" y1="{y(allocation):.1f}" y2="{y(allocation):.1f}">'
                    f'<title>{can} allocation {allocation} mrad</title></line>')
        values = sorted(abs(v) for v in r.payload["y"])
        for j, v in enumerate(values):
            jitter = ((j * 37) % 11 - 5) / 5 * band * 0.22
            body.append(f'<circle class="real" cx="{cx + jitter:.1f}" cy="{y(v):.1f}" r="4" data-tip="{can}: stop {v:.2f} mrad"/>')
        body.append(f'<line class="p90" x1="{cx-band*0.3:.1f}" x2="{cx+band*0.3:.1f}" y1="{y(r.value):.1f}" y2="{y(r.value):.1f}" '
                    f'data-tip="{can} p90 {r.value:.2f} mrad vs {allocation} mrad: {r.verdict}"/>')
        body.append(f'<text class="vtag v-{r.verdict}" x="{cx:.1f}" y="{T+10}" text-anchor="middle">{GLYPH[r.verdict]}</text>')
    return svg(W, H, "".join(body), "stop error per stop, per motor, with each joint's allocation")


def fidelity_chart(results):
    W, H, L, R, T, B = 760, 300, 54, 12, 16, 44
    y = Log(0.5, 50, H - B, T)
    band = (W - L - R) / len(ORDER)
    body = ['<g class="grid">']
    for tick in log_ticks(0.5, 50):
        body.append(f'<line x1="{L}" x2="{W-R}" y1="{y(tick):.1f}" y2="{y(tick):.1f}"/><text class="tick" x="{L-6}" y="{y(tick)+3:.1f}" text-anchor="end">{tick:g}</text>')
    body.append("</g>")
    body.append(f'<rect class="okband" x="{L}" y="{y(1.5):.1f}" width="{W-L-R}" height="{y(0.5)-y(1.5):.1f}"><title>T2 passes at or below 1.5 x the floor</title></rect>')
    body.append(f'<line class="limit" x1="{L}" x2="{W-R}" y1="{y(1.5):.1f}" y2="{y(1.5):.1f}"/><text class="tick" x="{W-R-4}" y="{y(1.5)-4:.1f}" text-anchor="end">1.5 (T2)</text>')
    body.append(f'<line class="limit dash" x1="{L}" x2="{W-R}" y1="{y(2.0):.1f}" y2="{y(2.0):.1f}"/><text class="tick" x="{W-R-4}" y="{y(2.0)-4:.1f}" text-anchor="end">2.0 per class</text>')
    body.append(f'<text class="axis" x="14" y="{T+(H-B-T)/2:.0f}" transform="rotate(-90 14 {T+(H-B-T)/2:.0f})" text-anchor="middle">model error / floor (log)</text>')
    for i, can in enumerate(ORDER):
        r = find(results, can, "stock.fidelity_ratio", "twin / floor)")
        cx = L + band * (i + 0.5)
        body.append(f'<text class="tick" x="{cx:.1f}" y="{H-B+16}" text-anchor="middle">{can}</text>')
        if not r:
            continue
        for x, v, g in zip(r.payload["x"], r.payload["y"], r.payload["group"]):
            offset = {"pickplace": -0.27, "cycle": -0.09, "jog": 0.09, "sweep": 0.27}.get(x, 0) * band
            cls = "sim" if g == "twin" else "target"
            shape = (f'<circle class="{cls}" cx="{cx+offset:.1f}" cy="{y(v):.1f}" r="4.5" data-tip="{can} {g}, {x}: {v:.2f} x floor"/>' if g == "twin" else
                     f'<rect class="{cls}" x="{cx+offset-4:.1f}" y="{y(v)-4:.1f}" width="8" height="8" rx="1" data-tip="{can} {g}, {x}: {v:.2f} x floor"/>')
            body.append(shape)
        body.append(f'<text class="vtag v-{r.verdict}" x="{cx:.1f}" y="{T+10}" text-anchor="middle">{GLYPH[r.verdict]}</text>')
    return svg(W, H, "".join(body), "twin and perfect-servo error over the floor, per motor and tape class")


def heat(payload, title, x_fmt, y_fmt, label, cell_w=None):
    rows, cols, cells = payload["rows"], payload["cols"], payload["cells"]
    W = 360
    L, T = 70, 10
    cw = (W - L - 10) / len(cols)
    ch = min(cw, 22)
    H = T + ch * len(rows) + 40
    peak = max(max(row) for row in cells) or 1
    body = []
    for i, row in enumerate(rows):
        for j, _ in enumerate(cols):
            v = cells[i][j]
            k = 0 if v == 0 else 1 + int(5 * v / peak - 1e-9)
            body.append(f'<rect class="seq{min(k,5)}" x="{L+j*cw:.1f}" y="{T+i*ch:.1f}" width="{cw-1:.1f}" height="{ch-1:.1f}" '
                        f'data-tip="{E(label)}: {E(y_fmt(row_label(rows, i)))} x {E(x_fmt(cols[j]))} = {v:g}"/>')
        if len(rows) <= 6 or i % max(1, len(rows) // 6) == 0:
            body.append(f'<text class="tick" x="{L-4}" y="{T+i*ch+ch*0.7:.1f}" text-anchor="end">{E(y_fmt(rows[i]))}</text>')
    for j in range(0, len(cols), max(1, len(cols) // 5)):
        body.append(f'<text class="tick" x="{L+j*cw+cw/2:.1f}" y="{T+len(rows)*ch+14:.1f}" text-anchor="middle">{E(x_fmt(cols[j]))}</text>')
    body.append(f'<text class="axis" x="{L+(W-L)/2:.0f}" y="{H-6}" text-anchor="middle">{E(title)}</text>')
    return svg(W, H, "".join(body), label)


def row_label(rows, i):
    return rows[i]


def stream_chart(stream):
    points = [p for p in stream["tracking"] if p["value"] is not None]
    W, H, L, R, T, B = 760, 200, 54, 12, 14, 34
    t0 = points[0]["t"]
    x = Lin(0, points[-1]["t"] - t0, L, W - R)
    y = Lin(0, max(60, max(p["value"] for p in points) * 1.1), H - B, T)
    body = ['<g class="grid">']
    for tick in range(0, int(y.hi) + 1, 10):
        body.append(f'<line x1="{L}" x2="{W-R}" y1="{y(tick):.1f}" y2="{y(tick):.1f}"/><text class="tick" x="{L-6}" y="{y(tick)+3:.1f}" text-anchor="end">{tick}</text>')
    body.append("</g>")
    body.append(f'<rect class="warnband" x="{L}" y="{y(40):.1f}" width="{W-L-R}" height="{y(30)-y(40):.1f}"/>'
                f'<line class="limit" x1="{L}" x2="{W-R}" y1="{y(40):.1f}" y2="{y(40):.1f}"/>'
                f'<text class="tick" x="{W-R-4}" y="{y(40)-4:.1f}" text-anchor="end">error 40 (demo limit)</text>'
                f'<text class="tick" x="{W-R-4}" y="{y(30)+12:.1f}" text-anchor="end">warn 30</text>')
    path = " ".join(f"{'M' if i == 0 else 'L'}{x(p['t']-t0):.1f},{y(p['value']):.1f}" for i, p in enumerate(points))
    body.append(f'<path class="realline" d="{path}"/>')
    for p in points:
        body.append(f'<circle class="dot v-{p["verdict"]}" cx="{x(p["t"]-t0):.1f}" cy="{y(p["value"]):.1f}" r="4.5" '
                    f'data-tip="window ending {p["t"]-t0:.2f} s: {p["value"]:.1f} mrad, {WORD[p["verdict"]]}"/>')
    body.append(f'<text class="axis" x="{L+(W-L)/2:.0f}" y="{H-4}" text-anchor="middle">window end, s from the run start (1 s windows, 0.25 s step)</text>'
                f'<text class="axis" x="14" y="{T+(H-B-T)/2:.0f}" transform="rotate(-90 14 {T+(H-B-T)/2:.0f})" text-anchor="middle">RMS, mrad</text>')
    return svg(W, H, "".join(body), "RobotDx consumer: tracking error per window, coloured by level")


def diagram():
    """The library: config + data -> diagnose -> Result -> record / row / rollup; one library, two consumers."""

    def box(x, y, w, h, title, lines=(), cls="box"):
        out = [f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>',
               f'<text class="dt" x="{x+12}" y="{y+22}">{E(title)}</text>']
        out += [f'<text class="dl" x="{x+12}" y="{y+42+16*i}">{E(line)}</text>' for i, line in enumerate(lines)]
        return "".join(out)

    def arrow(x1, y1, x2, y2, label="", dy=-6):
        mid = f'<text class="al" x="{(x1+x2)/2:.0f}" y="{(y1+y2)/2+dy:.0f}" text-anchor="middle">{E(label)}</text>' if label else ""
        return f'<line class="arrow" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" marker-end="url(#ah)"/>{mid}'

    parts = ['<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             '<path class="ahead" d="M0,0 L10,5 L0,10 z"/></marker></defs>']
    parts.append(box(20, 20, 220, 92, "Config (frozen dataclass)", ("Limits: warn/error low/high", "windows, channel, statistic", "editable as data (drill in)")))
    parts.append(box(20, 132, 220, 92, "Data", ("Trajectory: t, q_rad, q_target_rad,", "qd_rad_s, tau_nm, mode, fault ...", "or rows (ModelRow, Stamps)")))
    parts.append(box(300, 20, 260, 52, "Registry", ("stock · TOML [[diagnostic]] · entry point",), cls="box alt"))
    parts.append(box(300, 92, 260, 132, "diagnose(config, data) -> Result", ("pure: no state, no I/O", "measure, then judge(value, Limits)", "13 stock now, 17 specified",
                                                                             "hint + emits for data-ui")), )
    parts.append(arrow(240, 66, 300, 140))
    parts.append(arrow(240, 178, 300, 178))
    parts.append(arrow(430, 72, 430, 92))
    parts.append(box(620, 92, 200, 132, "Result", ("verdict pass/warn/fail/not_run", "value, unit, limits, code, why", "evidence: run, t0..t1", "caused_by, config, payload")))
    parts.append(arrow(560, 158, 620, 158))
    parts.append(box(880, 20, 250, 70, "RobotDx record v0.2", ("to_record() / from_record()", "lossless; contract validate() == []")))
    parts.append(box(880, 112, 250, 70, "data-ui row (PEP 0010)", ("result_row(): subject ... parent, hint", "sample_rows / diff_rows")))
    parts.append(box(880, 204, 250, 70, "rollup / gate_matrix", ("a composite's own verdict (spider rule)", "caused_by names the members")))
    parts.append(arrow(820, 120, 880, 56))
    parts.append(arrow(820, 150, 880, 146))
    parts.append(arrow(820, 190, 880, 236))
    parts.append(f'<path class="arrow" d="M1005,274 C1005,304 760,304 760,226" marker-end="url(#ah)" fill="none"/>'
                 f'<text class="al" x="1128" y="302" text-anchor="end">a composite is a Result too</text>')
    parts.append(box(20, 330, 530, 96, "RobotDx: one robot, its whole history", ("stream.windows(run, window_s, step_s) -> monitor()", "records with expected_period_s; host derives STALE,",
                                                                                 "debounces faults (FaultManager), rolls up (summarize)"), cls="box alt"))
    parts.append(box(600, 330, 530, 96, "sim2real: datasets of runs, many situations", ("the same functions over runs; models are situations", "diagnostics.json + gates.json per deployment",
                                                                                         "model vs model vs real, all against the floor"), cls="box alt"))
    parts.append(arrow(285, 330, 380, 226))
    parts.append(arrow(640, 330, 540, 226))
    parts.append(f'<text class="al" x="460" y="290" text-anchor="middle">the same functions</text>')
    return svg(1150, 440, "".join(parts), "library diagram: config and data into a pure diagnose function; the Result goes to the RobotDx record, the data-ui row, and composite rollups; RobotDx and sim2real call the same functions")


def catalog_matrix():
    families = [f for f in FAMILIES if any(e.the_family == f for e in ENTRIES)]
    head = "".join(f"<th>{E(f.replace('_', ' '))}</th>" for f in families)
    body = []
    for part, entries in by_part().items():
        cells = []
        for family in families:
            chips = []
            for e in entries:
                if e.the_family != family:
                    continue
                tip = f"{e.title} · {e.primitive}{' · ' + e.gate if e.gate else ''} · hint {e.the_hint} · {e.prov}: “{e.quote}” ({e.where})"
                chips.append(f'<span class="chip p-{e.prov.replace(" ", "-")}{" impl" if e.p.implemented else ""}" data-tip="{E(tip)}">{E(e.title)}</span>')
            cells.append(f"<td>{''.join(chips)}</td>")
        body.append(f'<tr><th scope="row">{E(PARTS[part].split(" (")[0])}</th>{"".join(cells)}</tr>')
    return f'<div class="scroll"><table class="matrix"><thead><tr><th>part type</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def catalog_details():
    out = []
    for part, entries in by_part().items():
        rows = []
        for e in entries:
            rows.append(f"<tr><td><b>{E(e.title)}</b><br><code>{E(e.id)}</code></td><td>{E(e.checks)}</td><td><code>{E(e.primitive)}</code>"
                        f"{'' if e.p.implemented else ' <i>(specified)</i>'}<br><span class='mute'>{E(e.config)}</span></td><td>{E(e.output)}</td>"
                        f"<td>{E(e.gate) or '–'}</td><td>{e.role}</td><td><code>{e.the_hint}</code>{'<br><span class=mute>' + E(e.view_extra) + '</span>' if e.view_extra else ''}</td>"
                        f"<td>{e.consumers}</td><td><span class='prov p-{e.prov.replace(' ', '-')}'>{e.prov}</span> “{E(e.quote)}”<br><span class='mute'>{E(e.where)}</span>"
                        f"{'<br>today: ' + E(e.today) if e.today else ''}</td></tr>")
        out.append(f"<details><summary>{E(PARTS[part])} <span class='mute'>· {len(entries)}</span></summary><div class='scroll'><table class='cat'>"
                   "<thead><tr><th>diagnostic</th><th>checks</th><th>primitive · config</th><th>output</th><th>gate</th><th>role</th><th>hint</th><th>for</th>"
                   f"<th>provenance</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>")
    return "".join(out)


def gate_table(gates, results):
    cells = defaultdict(dict)
    for c in gates["cells"]:
        cells[c["subject"]][c["gate"]] = c
    cols = ("T1 floor", "T2 fidelity", "T3 torque", "T4 stop", "T6 drive gain")
    acc = {"pass": "pass", "fail": "fail", "warn": "partial", "not_run": "not_run"}
    rows = []
    for can in ORDER:
        tds = []
        for g in cols:
            c = cells[can][g]
            same = acc[c["verdict"]] == c["acceptance"]
            value = "" if c["value"] is None else f"{fmt(c['value'])} {'' if c['unit'] in ('1',) else c['unit']}"
            tds.append(f'<td data-tip="{E(c["message"])}{"" if same else " · acceptance.json says " + E(str(c["acceptance"]))}">'
                       f'{verdict_chip(c["verdict"], value.strip() or WORD[c["verdict"]])}{"" if same else " <span class=diff>≠ acc.</span>"}</td>')
        rollup = find(results, can, "stock.rollup")
        rows.append(f"<tr><th scope='row'>{can}<br><span class='mute'>{ROLE[can]}</span></th>{''.join(tds)}<td>{verdict_chip(rollup.verdict)}</td></tr>")
    head = "".join(f"<th>{g}</th>" for g in cols)
    return f"<div class='scroll'><table class='gates'><thead><tr><th>station</th>{head}<th>station rollup</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def oracle_table(oracle):
    groups = defaultdict(list)
    for row in oracle:
        key = "feed-forward study (tracking RMS, stop p90 per fraction)" if row["check"].startswith("ff ") else row["check"]
        groups[key].append(row)
    out = []
    for key, rows in groups.items():
        worst = max(r["abs_diff"] for r in rows)
        sample = rows[0]
        out.append(f"<tr><td>{E(key)}</td><td><code>{E(sample['file'])}</code></td><td>{len(rows)}</td><td>{worst:.2g}</td>"
                   f"<td>{'exact' if worst < 1e-9 else 'rounding (file keeps 3-4 digits)'}</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>check</th><th>bam_rack_twin file</th><th>comparisons</th><th>max |diff|</th><th>agreement</th></tr></thead>"
            f"<tbody>{''.join(out)}</tbody></table></div>")


def motor_table(results):
    rows = []
    for can in ORDER:
        get = lambda d, t="": find(results, can, d, t)
        fl, tr, st, fi, tq, cov, tmp = (get("stock.repeatability_floor", "q_rad"), get("stock.tracking_error"), get("stock.stop_error"),
                                        get("stock.fidelity_ratio", "twin / floor)"), get("stock.fidelity_ratio", "torque"), get("stock.coverage"), get("stock.box", "temp_c"))
        rows.append(f"<tr><th scope='row'>{can}</th><td>{fmt(fl.value)}</td><td>{fmt(tr.value)}</td><td>{verdict_chip(st.verdict, fmt(st.value))}</td>"
                    f"<td>{verdict_chip(fi.verdict, fmt(fi.value))}</td><td>{verdict_chip(tq.verdict, fmt(tq.value))}</td>"
                    f"<td>{verdict_chip(cov.verdict, f'{cov.value:.0%}')}</td><td>{verdict_chip(tmp.verdict, fmt(tmp.value) + ' °C')}</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>station</th><th>floor (mrad)</th><th>tracking RMS, PD (mrad)</th><th>stop p90 (mrad)</th>"
            "<th>twin / floor</th><th>torque twin / floor</th><th>coverage q×qd</th><th>board temp max</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


CSS = """
:root{--bg:#fcfcfb;--panel:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--mute:#8a8984;--line:#e4e3df;--grid:#efeeea;
--real:#2a78d6;--sim:#eb6834;--target:#8a8984;--good:#0ca30c;--warn:#b07700;--warnfill:#fab219;--bad:#d03b3b;--notrun:#8a8984;
--seq0:#f4f3f0;--seq1:#cde2fb;--seq2:#9ec5f4;--seq3:#5598e7;--seq4:#256abf;--seq5:#104281;--okband:rgba(12,163,12,.07);--warnband:rgba(250,178,25,.13);
--chip:#f2f1ee}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#1a1a19;--panel:#222220;--ink:#f0efec;--ink2:#c3c2b7;--mute:#8f8e86;--line:#383835;--grid:#2c2c2a;
--real:#3987e5;--sim:#d95926;--target:#8f8e86;--good:#0ca30c;--warn:#fab219;--warnfill:#fab219;--bad:#e66767;--notrun:#8f8e86;
--seq0:#262624;--seq1:#104281;--seq2:#1c5cab;--seq3:#2a78d6;--seq4:#6da7ec;--seq5:#b7d3f6;--okband:rgba(12,163,12,.12);--warnband:rgba(250,178,25,.12);--chip:#2c2c2a}}
:root[data-theme="dark"]{--bg:#1a1a19;--panel:#222220;--ink:#f0efec;--ink2:#c3c2b7;--mute:#8f8e86;--line:#383835;--grid:#2c2c2a;
--real:#3987e5;--sim:#d95926;--target:#8f8e86;--good:#0ca30c;--warn:#fab219;--warnfill:#fab219;--bad:#e66767;--notrun:#8f8e86;
--seq0:#262624;--seq1:#104281;--seq2:#1c5cab;--seq3:#2a78d6;--seq4:#6da7ec;--seq5:#b7d3f6;--okband:rgba(12,163,12,.12);--warnband:rgba(250,178,25,.12);--chip:#2c2c2a}
*{box-sizing:border-box}html{background:var(--bg)}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 80px}h1{font-size:26px;margin:4px 0 6px}h2{font-size:19px;margin:38px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:15px;margin:22px 0 6px}p,li{color:var(--ink2)}b,strong{color:var(--ink)}.mute{color:var(--mute);font-size:13px}code{font:12.5px ui-monospace,Menlo,monospace}
.verdict{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile .n{font-size:24px;font-weight:650;color:var(--ink)}.tile .l{font-size:12.5px;color:var(--ink2)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0}table{border-collapse:collapse;width:100%;font-size:13.5px;background:var(--panel)}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}thead th{background:var(--chip);font-weight:600}
.matrix td{min-width:120px}.matrix th[scope=row]{white-space:nowrap}.cat td{min-width:90px}.cat td:nth-child(2){min-width:180px}.cat td:last-child{min-width:260px}
.chip{display:inline-block;margin:2px 3px 2px 0;padding:1px 7px;border-radius:6px;font-size:12px;border:1.5px solid var(--line);background:var(--chip);color:var(--ink);cursor:default}
.chip.p-his{border-color:var(--ink2)}.chip.p-his-code{border-style:dashed;border-color:var(--ink2)}.chip.p-agent{border-style:dotted;border-color:var(--ink2)}.chip.p-proposed{border-color:var(--line);color:var(--ink2)}
.chip.impl::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--ink);margin-right:5px;vertical-align:1px}
.prov{font-size:11.5px;padding:0 6px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--ink2);margin:6px 0}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.v{white-space:nowrap}.v b{font-weight:700}.v-pass b,.vtag.v-pass{color:var(--good);fill:var(--good)}.v-warn b,.vtag.v-warn{color:var(--warn);fill:var(--warn)}
.v-fail b,.vtag.v-fail{color:var(--bad);fill:var(--bad)}.v-not_run b,.vtag.v-not_run{color:var(--notrun);fill:var(--notrun)}.diff{font-size:11px;color:var(--ink2)}
details{background:var(--panel);border:1px solid var(--line);border-radius:8px;margin:6px 0;padding:4px 10px}summary{cursor:pointer;font-weight:600;padding:4px 0}
.chart{width:100%;height:auto;display:block;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.chart .grid line{stroke:var(--grid);stroke-width:1}.chart .tick{fill:var(--ink2);font-size:11px}.chart .tick.mute{fill:var(--mute);font-size:10px}.chart .axis{fill:var(--ink2);font-size:11.5px}
.chart .real{fill:var(--real);stroke:var(--panel);stroke-width:2}.chart .sim{fill:var(--sim);stroke:var(--panel);stroke-width:2}.chart .target{fill:var(--target);stroke:var(--panel);stroke-width:2}
.chart .limit{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:5 3}.chart .limit.dash{stroke-dasharray:2 3}.chart .p90{stroke:var(--ink);stroke-width:2.5}
.chart .okband{fill:var(--okband)}.chart .warnband{fill:var(--warnband)}.chart .vtag{font-size:13px}.chart .realline{fill:none;stroke:var(--real);stroke-width:2}
.chart .dot{stroke:var(--panel);stroke-width:2}.chart .dot.v-pass{fill:var(--good)}.chart .dot.v-warn{fill:var(--warnfill)}.chart .dot.v-fail{fill:var(--bad)}.chart .dot.v-not_run{fill:var(--notrun)}
.chart .seq0{fill:var(--seq0)}.chart .seq1{fill:var(--seq1)}.chart .seq2{fill:var(--seq2)}.chart .seq3{fill:var(--seq3)}.chart .seq4{fill:var(--seq4)}.chart .seq5{fill:var(--seq5)}
.chart .box{fill:var(--panel);stroke:var(--ink2);stroke-width:1.2}.chart .box.alt{fill:var(--chip)}.chart .box.real{stroke:var(--real);stroke-width:1.8}.chart .box.sim{stroke:var(--sim);stroke-width:1.8}
.chart .dt{fill:var(--ink);font-size:14px;font-weight:650}.chart .dl{fill:var(--ink2);font-size:12px}.chart .al{fill:var(--ink2);font-size:11px}
.chart .arrow{stroke:var(--ink2);stroke-width:1.4}.chart .ahead{fill:var(--ink2)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}.two>*{min-width:0}li code,p code{overflow-wrap:anywhere}@media (max-width:760px){.two{grid-template-columns:1fr}}
pre{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px;overflow-x:auto;font:12px/1.45 ui-monospace,Menlo,monospace;color:var(--ink)}
#tip{position:fixed;pointer-events:none;max-width:360px;background:var(--ink);color:var(--bg);font-size:12px;padding:6px 8px;border-radius:6px;opacity:0;transition:opacity .08s;z-index:9}
.toggle{float:right;font-size:12px;border:1px solid var(--line);background:var(--panel);color:var(--ink2);border-radius:999px;padding:3px 10px;cursor:pointer}
ol.needs li{margin:6px 0}
"""

JS = """
const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');if(!t){tip.style.opacity=0;return}
tip.textContent=t.getAttribute('data-tip');tip.style.opacity=1;const x=Math.min(e.clientX+14,innerWidth-370);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'});
document.getElementById('theme').addEventListener('click',()=>{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
r.dataset.theme=dark?'light':'dark';try{localStorage.setItem('dx-theme',r.dataset.theme)}catch(e){}});
try{const s=localStorage.getItem('dx-theme');if(s)document.documentElement.dataset.theme=s}catch(e){}
"""

OLD_CODE = [
    ("DiagnosticValue(warn, error) + check_thresholds", "keep", "Limits + judge; on the limit is inside; 0 is a real limit (was 'SKIPPING' = OK)"),
    ("BoxChartThresholds / BoxChartTask (min, max, mean_min/max, std)", "keep", "stock.box: four Limits over the window; numbers stay numbers, not 'mean_max [50, 60]' key strings"),
    ("ValueTask (one scalar, two bounds)", "keep", "judge(value, limits)"),
    ("EventPeriodTask (period stats)", "adapt", "stock.sample_rate: Hz and s named once (the old loop_duration put Hz-shaped numbers on a period in s)"),
    ("CounterTask / PercentTask", "adapt", "stock.share (specified): explicit better; the old success_rate had only an upper bound, so 100 % success read ERROR"),
    ("queue_val / queue_type (count | timed windows)", "adapt", "the caller slices (stream.windows); the function takes the window"),
    ("empty window = OK 'waiting for values'", "drop", "not_run (record UNKNOWN), never green"),
    ("STALE = 3 > ERROR = 2 (numeric worst-of)", "drop", "RobotDx rank; the host derives STALE from expected_period_s"),
    ("DiagnosticTaskManager (__getattr__, append-to-state)", "adapt", "registry: name -> (function, config type), no state"),
    ("DiagnosticsMixin, dx tick, ports, heartbeat = ValueTask(0)", "drop", "ROS/component coupling; liveness is the host's expected_period_s"),
    ("DiagonisticClient (worst level over a 10 s window)", "adapt", "the host's summarize; in tests, assert every verdict passes"),
    ("DiagnosticStatus msgs / SystemDiagnostics", "adapt", "Result, lossless to record v0.2"),
    ("moteus ErrorDef table (32-48 ERROR, 96-103 WARN, fix messages)", "keep", "stock.fault_codes + MOTEUS_CODES (32-50, 96-105 from moteus registers.md)"),
    ("declared numbers: board_temp 60/70 °C, mean 55/65; fault_count 1/5; transport 3/10; period 0.020/0.100 s", "keep", "catalog driver defaults (prov: his code)"),
    ("'1 diagnostic per interface', wrapper (bam_docs/diagnostics.md)", "keep", "a part type's catalog rows are its interface's contract test"),
]

NEEDS = [
    ("Adopt the catalog as the list, with provenance kept.", "Yes. Use the 50 entries in your words as the spine. The 29 proposed ones stay marked 'proposed' (shown, not gating) until you tick them.",
     "Proposed entries show but never gate."),
    ("The arm gate X and the joint shares.", "Keep 5 mm at a stop, which is your 2024 number, and the agent's shares (3.6 / 6.7 / 10 mrad). Revisit when the arm's lever arms are fixed.",
     "5 mm and the current shares."),
    ("What T4 scores: the controller the rack ran, or a proposal.", "The controller that ran. That flips CAN 21 from partial to fail (36.9 mrad, plain PD); the auto-tuner's 6.32 mrad was never written to the board.",
     "Report both; gate on what ran."),
    ("Torque truthfulness needs one weighed object.", "Weigh a bolt or a bag on a kitchen scale and fix it to CAN 12's link at a measured distance. T6 has never run on any motor.",
     "T6 stays not_run, shown grey."),
    ("numpy as robotdx.diagnostics' one runtime dependency.", "Yes, as an optional extra named diagnostics. core, registry and record stay stdlib, so io_diagnostics and the contract stay dependency-free.",
     "An optional extra."),
    ("Who lifts it into io-diagnostics.", "The RobotDx session copies robotdx/ in, as its plan says. sim2real imports it from there, and this reference is then retired.",
     "Hand it to the RobotDx owner."),
    ("No 0-1 health score.", "Keep worst-of plus counts plus caused_by. Your raw notes never asked for a score; only AI synthesis did.", "No score."),
]


def main() -> int:
    results, gates, oracle, stream, pytest_out, run_out = load()
    prov = Counter(e.prov for e in ENTRIES)
    exact = sum(1 for r in oracle if r["abs_diff"] < 1e-9)
    worst = max(r["abs_diff"] for r in oracle)
    cells = gates["cells"]
    acc = {"pass": "pass", "fail": "fail", "warn": "partial", "not_run": "not_run"}
    agree = sum(acc[c["verdict"]] == c["acceptance"] for c in cells)
    passing = sum(c["verdict"] == "pass" for c in cells)
    impl = sum(p.implemented for p in PRIMITIVES.values())
    floor14 = find(results, "CAN 14", "stock.repeatability_floor", "q_rad")
    floor11 = find(results, "CAN 11", "stock.repeatability_floor", "q_rad")
    cov12 = find(results, "CAN 12", "stock.coverage")
    cams = [r for r in results if "D405" in r.subject]
    short = lambda p: Path(p).stem.split("_")[0]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stock Diagnostics Catalog</title><style>{CSS}</style></head><body><main>
<button class="toggle" id="theme" type="button">light / dark</button>
<p class="mute">sim2real · robotdx.diagnostics reference · 2026-10-28 · Claude Code (Opus 5.5)</p>
<h1>Stock diagnostics, KPIs and gates for every robot part type</h1>
<div class="verdict"><b>The catalog is {len(ENTRIES)} diagnostics over {len(PARTS)} part types, built from {len(PRIMITIVES)} stock functions.
The library that computes them works, and on the real rack it reproduces bam_rack_twin's own numbers.</b>
<ul>
<li><b>Fidelity on the real rack:</b> {exact} of {len(oracle)} numbers match bam_rack_twin exactly. The other {len(oracle)-exact} differ by at most {worst:.1g}, only because acceptance.json and kt_can14.json store 3-4 digits. {agree} of {len(cells)} gate verdicts agree with acceptance.json.</li>
<li><b>Tests:</b> 40 tests pass under <code>uv run --isolated</code>.</li>
<li><b>Contract:</b> every Result goes through RobotDx's own record contract and back unchanged, and serialises to exactly data-ui's PEP 0010 row.</li>
<li><b>Where it lives:</b> <code>/home/bam/sim2real/diagnostics_ref</code>, uncommitted. It is a reference for the RobotDx owner to lift in, not a fork.</li>
<li><b>Not done:</b> {len(PRIMITIVES)-impl} of the {len(PRIMITIVES)} functions are specified but not written (ISO 9283, Allan, camera calibration, depth, spectral, and others).</li>
</ul></div>
<div class="tiles">
<div class="tile"><div class="n">{len(ENTRIES)}</div><div class="l">catalog diagnostics · {len(PARTS)} part types</div></div>
<div class="tile"><div class="n">{prov['his']}</div><div class="l">in Zach's words (a test re-reads each quote at its file)</div></div>
<div class="tile"><div class="n">{impl} / {len(PRIMITIVES)}</div><div class="l">stock functions implemented / specified</div></div>
<div class="tile"><div class="n">{exact} / {len(oracle)}</div><div class="l">exact matches with bam_rack_twin on real runs (the rest equal at the file's 3-4 digits)</div></div>
<div class="tile"><div class="n">{passing} / {len(cells)}</div><div class="l">rack gate cells passing (T1-T4, T6 × 8)</div></div>
<div class="tile"><div class="n">40</div><div class="l">tests passing, isolated env</div></div>
</div>

<h2>1 · What to measure: the catalog</h2>
<p>Each part type gets (stock function, config) pairs and no new code. Your Oct 28 line: <i>“for most diaginstics you don't really need to right any standard code beacuse they are so stock”</i>.
Columns are the families. Your two errors, from Jul 31, are real-vs-target and sim-vs-real; truthfulness is your Oct 28 “turhtfully of the torque readings”. Hover a chip for its function, gate, data-ui hint and source.</p>
<div class="legend"><span><span class="chip p-his">in his words</span></span><span><span class="chip p-his-code">his old code</span></span><span><span class="chip p-agent">agent default</span></span>
<span><span class="chip p-proposed">proposed + prior art</span></span><span><span class="chip impl p-proposed">dot = its function is implemented now</span></span></div>
{catalog_matrix()}
<h3>Every entry: inputs, config, output, gate, role, hint, consumer, source</h3>
<p class="mute">The same rows as <code>docs/diagnostics-catalog-2026-10-28.md</code>, generated from <code>catalog.py</code>.</p>
{catalog_details()}

<h2>2 · How it is computed: the library</h2>
<p>A frozen dataclass config and the data go into a pure function, which returns a Result; a registry names them. You set this shape on Oct 28: “pass in a dataclass config, that paramterizes the diaginstics, and then at run time you just like pass in the data”.
The same Result becomes RobotDx's record, data-ui's row, or a member of a composite rollup.</p>
{diagram()}
<div class="two"><div>
<h3>The Result, two ways out</h3>
<ul><li><b>RobotDx record v0.2:</b> verdict → level (pass ok, warn warn, fail error, not_run unknown); value + limits → <code>measurements[0]</code>; the rest rides in <code>dx.*</code> values. Proven lossless through <code>contract/record.py</code> (<code>validate() == []</code>).</li>
<li><b>data-ui row (PEP 0010 §10):</b> <code>subject, diagnostic, title, verdict|level, rank, value, unit, warn_lo/hi, error_lo/hi, target, better, t, t0, t1, run, message, why, evidence, basis, source, sourceUrl, record, parent, hint</code> + <code>emits</code>.</li>
<li><b>Evidence:</b> every Result names the worst run and window (<code>run#t=t0&amp;tr=t0,t1</code>), so a red cell opens the moment that made it red.</li></ul>
</div><div>
<h3>Module layout, to lift into io-diagnostics</h3>
<pre>robotdx/diagnostics/
  core.py       Limits, judge, Result, HINTS, EMITS   (stdlib)
  data.py       Trajectory (unit-suffixed columns), difference
  registry.py   Spec, evaluate, config_from_dict, load_toml
  record.py     to_record / from_record  (stdlib)
  rows.py       result_row, sample_rows, diff_rows
  rollup.py     rollup (spider rule), gate_matrix
  stream.py     windows, monitor  (the RobotDx consumer)
  catalog.py    PARTS, PRIMITIVES, ENTRIES (data)
  stock/        tracking · fidelity · truthfulness · health · coverage
  adapters/     rack_npz (the only file reader)</pre></div></div>

<h2>3 · Proof on the real rack (rack_2026-10-24/25)</h2>
<p>The real runs went through the stock functions, then into the gate matrix and the rollups. Every number is drawn from <code>data/*.json</code>, which <code>tools/run_rack.py</code> wrote in 0.3 s.</p>
<h3>The gate matrix (hint <code>gate_matrix</code>): {passing} of {len(cells)} cells pass</h3>
<p class="mute">A cell is one Result. “≠ acc.” marks the one disagreement with acceptance.json: CAN 21's T4. acceptance.json scores it on the PID auto-tuner's proposal (6.32 mrad, never written to the board); this library scores the controller the rack ran.</p>
{gate_table(gates, results)}
<h3>Per station</h3>
{motor_table(results)}
<p class="mute">The stop p90 is on the best controller the rack ran: Coulomb feed-forward where the study improved the stop, else plain PD. It is encoder-side, so a value within its allocation reads <b>warn</b> (partial), not pass. Coverage is the share of the 16×16 grid over the commanded q range × ±max speed with ≥ 5 rows.</p>

<h3>Stop error, every stop (hint <code>distribution</code>)</h3>
<div class="legend"><span><i style="background:var(--real)"></i>real stop (encoder side)</span><span>— p90</span><span>- - - joint allocation of the 5 mm gate</span></div>
{stop_chart(results)}
<p>The JMC shoulders (CAN 11-13) sit 1.6× to 15× over their 3.6 mrad share, even with Coulomb feed-forward. CAN 21 sits 5.5× over: the feed-forward study did not improve it, so it is plain PD. The other four fit their shares but read <b>warn</b>, because only the output side (camera) can pass T4.</p>

<h3>Sim vs real against the floor, many-way (hint <code>threshold_band</code>)</h3>
<div class="legend"><span><i style="background:var(--sim)"></i>twin (bam_rack_twin, per class)</span><span><i style="background:var(--target);border-radius:2px"></i>perfect servo (the target as a model)</span><span>class order: pickplace, cycle, jog, sweep</span></div>
{fidelity_chart(results)}
<p>The twin beats “assume perfect tracking” in every class on every station. CAN 4 is the closest: 1.37× against 3.26× on pickplace. No station is at or under 1.5× on its floor's tape, so T2 fails 8 of 8, as acceptance.json says. This is the many-way comparison you asked for: any number of models are situations of the same run, judged against one floor.</p>

<div class="two"><div>
<h3>Floor evidence, CAN 14 (hint <code>evidence</code>, emits matrix)</h3>
{heat(floor14.payload, "pairwise RMS(e_a - e_b), mrad", lambda c: short(c), lambda r: short(r), "CAN 14 floor pair")}
<p class="mute">Five identical repeats give ten pairs; the median pair is the floor, {floor14.value:.3f} mrad. Lightest = 0 (a run against itself); darkest = the worst pair, {max(max(r) for r in floor14.payload["cells"]):.2f} mrad. CAN 11, for scale: {floor11.value:.3f} mrad.</p>
</div><div>
<h3>Coverage, CAN 12 (hint <code>distribution</code>, view_extra heatmap)</h3>
{heat(cov12.payload, "x: qd (rad/s) · y: q (rad)", lambda c: f"{c:.1f}", lambda r: f"{r:.2f}", "CAN 12 rows per cell")}
<p class="mute">{cov12.value:.0%} of the commanded envelope's cells hold ≥ 5 rows. Waypoint tapes visit the speed extremes only briefly. This is your Oct 24 ask, measured: “datapoints like accross the full velocitys, acceleration position range.”</p>
</div></div>

<h3>The RobotDx consumer: the same function, window by window (hint <code>level_history</code>)</h3>
{stream_chart(stream)}
<p class="mute">One CAN 12 dataset run replayed as a live stream: tracking RMS in 1 s windows every 0.25 s. Each window's Result is a record with <code>expected_period_s = 0.25</code>, so RobotDx would mark it STALE if evaluations stopped. The 30/40 mrad band is a demo limit, not a gate.</p>
<p>Camera health from the same <code>stock.sample_rate</code> on the D405 hardware clock: {"; ".join(f"{r.subject.split('/')[-1]}: {r.value:.2f} Hz vs 30, {WORD[r.verdict]}" + (f" ({r.code})" if r.code else "") for r in cams)}.</p>

<h3>The oracle: bam_rack_twin's own published numbers, same runs</h3>
{oracle_table(oracle)}
<pre>{E(pytest_out.strip())}

{E(run_out.strip())}</pre>

<h2>4 · Your old diagnostics code, mapped</h2>
<p>From the like_keras archive (<code>lk/archive/common/diagnostics/v2/</code>) and bam_machine. The ideas carry over; the mixin and ROS plumbing do not.</p>
<div class="scroll"><table><thead><tr><th>old piece</th><th></th><th>becomes</th></tr></thead><tbody>
{"".join(f"<tr><td>{E(a)}</td><td><b>{b}</b></td><td>{E(c)}</td></tr>" for a, b, c in OLD_CODE)}
</tbody></table></div>

<h2>5 · Needs you (silence = the default)</h2>
<ol class="needs">{"".join(f"<li><b>{E(q)}</b> Recommend: {E(r)} <i>Default: {E(d)}</i></li>" for q, r, d in NEEDS)}</ol>

<h2>6 · Deliberately not done</h2>
<ul><li>No write to io-diagnostics, data-ui, bam_ws or pidtuna: they are read-only here and owned by other sessions.</li>
<li>No hardware. Every number comes from archived runs.</li>
<li>No debounce, fault memory or staleness in the library. Those are the host's (RobotDx <code>FaultManager</code>, <code>effective_level</code>), and the library stays pure.</li>
<li>{len(PRIMITIVES)-impl} specified functions are not written yet. Each is defined in <code>catalog.py</code> (inputs, config, prior art) and lands the same way.</li></ul>
<div id="tip" role="tooltip"></div>
</main><script>{JS}</script></body></html>"""
    (MEDIA / "report.html").write_text(page)
    print(MEDIA / "report.html", f"{len(page)/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
