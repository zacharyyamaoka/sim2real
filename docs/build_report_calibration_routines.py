"""The Calibration Routines report (2026-11-07): every routine as a typed record, and the ones the oracle can run graded on the same
hidden truth at 0, 1x, 3x and 10x their sensor noise, plus a delay or a quantisation where one matters.

    python3 /home/bam/sim2real/docs/build_report_calibration_routines.py

Stdlib only. Every number on the page is read at build time from sysid/results/calibration_routines.json (the join of type_cards'
ROUTINES with the ladder, both directions) and sysid/results/noise_ladder.json (the ladder's rows), the files
sysid/tests/test_noise_ladder.py holds to the code; nothing is typed here. The one exception is "What it means": the bullets under
"What the ladder found" in docs/decision-calibration-routines-2026-11-07.md, the reading written from these results. Writes one
self-contained page (inline SVG, no media) to reports/calibration-routines-2026-11-07.html.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "sysid" / "results"
OUT = REPO / "reports" / "calibration-routines-2026-11-07.html"
DECISION = REPO / "docs" / "decision-calibration-routines-2026-11-07.md"
LEVELS = ("0x", "1x", "3x", "10x")
LADDER_REF = {"0x": 0.1, "1x": 1.0, "3x": 3.0, "10x": 10.0}  # the ruler's bound in tolerances before its cap at the nominal's error
Y_LO, Y_HI = 1e-5, 1e3


def e(text) -> str:
    return html.escape(str(text), quote=True)


def fmt(x, digits: int = 3) -> str:
    if x is None:
        return "—"
    if x == 0:
        return "0"
    if abs(x) >= 1000 or abs(x) < 1e-3:
        return f"{x:.2e}"
    return f"{x:.{digits}g}"


def seconds_text(s) -> str:
    if s is None:
        return "—"
    if s < 1:
        return f"{s * 1e3:.0f} ms"
    if s < 120:
        return f"{s:.0f} s"
    if s < 7200:
        return f"{s / 60:.0f} min"
    return f"{s / 3600:.1f} h"


def usd(x) -> str:
    return "—" if x is None else ("$0" if x == 0 else f"${x:,.0f}")


def chip(passed: bool | None) -> str:
    if passed is None:
        return '<span class="chip none">—</span>'
    return '<span class="chip ok">✓ pass</span>' if passed else '<span class="chip bad">✗ fail</span>'


def recovered_worst(params: list[dict]):
    values = [p["error_over_tolerance"] for p in params if p["error_over_tolerance"] is not None]
    return max(values) if values else None


def cell(c: dict | None, title: str) -> str:
    if c is None:
        return '<td class="na">—</td>'
    worst = c["worst_error_over_tolerance"]
    usable = "use" if c["usable"] else "nouse"
    missing = c.get("missing") or []
    failing = (" · failing " + ", ".join(c["failing"][:4]) + ("…" if len(c["failing"]) > 4 else "")) if c["failing"] else ""
    notes = (" · " + " / ".join(c.get("notes", [])[:1])) if c.get("notes") and worst is None else ""
    tip = f"{title}: worst error {fmt(worst)}x its tolerance over what it recovered; {c['within_tolerance']} within tolerance{failing}{notes}"
    gap = f'<small> +{len(missing)} not recovered</small>' if missing else ""
    return f'<td class="{usable}" title="{e(tip)}"><b>{fmt(worst) if worst is not None else "none"}</b>{chip(c["pass"])}{gap}</td>'


# --- small multiples: worst error / tolerance against the level --------------------------------------------------------------------

def decision_findings(path: Path = DECISION) -> str:
    """The bullets under the decision doc's "What the ladder found", as HTML. WHY read from the doc (2026-11-07): the reading of the
    numbers is written once, in the decision record, from these results; the report shows it beside them rather than a second copy."""
    import re  # noqa: PLC0415

    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## What the ladder found")), None)
    if start is None:
        return ""
    bullets: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif bullets and line.startswith("  ") and line.strip():
            bullets[-1] += " " + line.strip()
        elif bullets and not line.strip():
            continue

    def inline(text: str) -> str:
        text = e(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", text)

    return "<ul class=\"reading\">" + "".join(f"<li>{inline(b)}</li>" for b in bullets) + "</ul>"


def ylog(v: float, top: float, height: float) -> float:
    v = min(max(v, Y_LO), Y_HI)
    return top + height * (math.log10(Y_HI) - math.log10(v)) / (math.log10(Y_HI) - math.log10(Y_LO))


def multiple(check: dict) -> str:
    w, h, left, top, right, bottom = 250, 168, 40, 18, 10, 26
    pw, ph = w - left - right, h - top - bottom
    xs = {lv: left + pw * i / (len(LEVELS) - 1) for i, lv in enumerate(LEVELS)}
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{e(check["id"])}: worst error over tolerance by noise level">']
    for v, label in ((Y_LO, "≤1e-5"), (1e-3, "0.001"), (1e-1, "0.1"), (1e1, "10"), (Y_HI, "1000")):
        y = ylog(v, top, ph)
        parts.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text class="tick" x="{left - 4}" y="{y + 3:.1f}" text-anchor="end">{label}</text>')
    ref = " ".join(f"{xs[lv]:.1f},{ylog(LADDER_REF[lv], top, ph):.1f}" for lv in LEVELS)
    parts.append(f'<polyline class="ref" points="{ref}"><title>the ruler\'s bound in tolerances (0.1, 1, 3, 10) before its cap</title></polyline>')
    y1 = ylog(1.0, top, ph)
    parts.append(f'<line class="tol" x1="{left}" x2="{left + pw}" y1="{y1:.1f}" y2="{y1:.1f}"/>'
                 f'<text class="tick" x="{left + pw}" y="{y1 - 3:.1f}" text-anchor="end">tolerance</text>')
    for lv in LEVELS:
        parts.append(f'<text class="tick" x="{xs[lv]:.1f}" y="{h - 8}" text-anchor="middle">{lv}</text>')
    rows = {r["level"]: r for r in check["rows"] if r["variant"] is None}
    pts = [(lv, recovered_worst(rows[lv]["parameters"])) for lv in LEVELS if lv in rows]
    line = [f"{xs[lv]:.1f},{ylog(v, top, ph):.1f}" for lv, v in pts if v is not None]
    if len(line) > 1:
        parts.append(f'<polyline class="series" points="{" ".join(line)}"/>')
    for lv, v in pts:
        r = rows[lv]
        cls = "dot" if r["pass"] else "dot fail"
        if v is None:
            parts.append(f'<text class="miss" x="{xs[lv]:.1f}" y="{top + ph / 2:.1f}" text-anchor="middle">no value<title>{e(lv)}: a claimed '
                         f'parameter came back empty</title></text>')
            continue
        tip = (f"{lv}: worst error {fmt(v)}x tolerance{' (drawn at the floor, 1e-5)' if v < Y_LO else ''}, "
               f"{'passes' if r['pass'] else 'fails'} the ruler's bound")
        parts.append(f'<circle class="{cls}" cx="{xs[lv]:.1f}" cy="{ylog(v, top, ph):.1f}" r="4"><title>{e(tip)}</title></circle>')
    parts.append("</svg>")
    status = " · ".join(f"{lv} {'✓' if rows[lv]['pass'] else '✗'}" for lv in LEVELS if lv in rows)
    return (f'<figure class="mult"><figcaption><b>{e(check["routine"])}</b><span>{e(check["example"])} · {e(status)}</span></figcaption>'
            + "".join(parts) + "</figure>")


# --- one parameter, every model ---------------------------------------------------------------------------------------------------------

def model_table(params: list[dict], level: str) -> str:
    """The parameter index of one example as a table: true and nominal, then one recovered / error column group per model."""
    labels = list(dict.fromkeys(m["model"] for p in params for m in p["models"]))
    head = "".join(f'<th colspan="2" class="grp">{e(label)}</th>' for label in labels)
    sub = "".join('<th>recovered (95 %)</th><th>error</th>' for _ in labels)
    body = []
    for p in params:
        by = {m["model"]: m for m in p["models"]}
        tol = p["tolerance"]
        cells = []
        for label in labels:
            cell = (by.get(label) or {}).get("levels", {}).get(level)
            if not cell or cell["recovered"]["mean"] is None:
                cells.append('<td class="na">—</td><td class="na">—</td>')
                continue
            ci = cell["recovered"]["ci95"]
            ci_text = f"<small> [{fmt(ci[0], 4)}, {fmt(ci[1], 4)}]</small>" if ci else "<small> (no interval)</small>"
            cls = "use" if cell["within_tolerance"] else "nouse"
            cells.append(f'<td class="num">{fmt(cell["recovered"]["mean"], 4)}{ci_text}</td>'
                         f'<td class="{cls} num" title="{e(cell["recovered"]["interval"] or "")}">{fmt(cell["error_over_tolerance"])} tol</td>')
        tol_text = f"{fmt(tol['value'], 3)}{' rel' if tol['kind'] == 'rel' else ''}"
        body.append(f'<tr><td><code>{e(p["key"])}</code><br><small>{e(p["card"])} {e(p["rung"])} {e(p["card_parameter"])} · '
                    f'{len(p["routines"])} routine{"" if len(p["routines"]) == 1 else "s"} can identify it</small></td><td class="num">{fmt(p["true"], 4)}</td>'
                    f'<td class="num">{fmt(p["nominal"], 4)}</td><td class="num">{e(tol_text)}</td>{"".join(cells)}</tr>')
    return ('<table class="models"><thead><tr><th rowspan="2">Parameter</th><th rowspan="2">True</th><th rowspan="2">Nominal</th>'
            f'<th rowspan="2">Tolerance</th>{head}</tr><tr>{sub}</tr></thead><tbody>{"".join(body)}</tbody></table>')


# --- the page ------------------------------------------------------------------------------------------------------------------------

def build(out: Path) -> Path:
    table = json.loads((RESULTS / "calibration_routines.json").read_text())
    ladder = json.loads((RESULTS / "noise_ladder.json").read_text())
    rows = table["rows"]
    checks = ladder["checks"]
    checked = [r for r in rows if r["oracle"]["status"] == "checked"]
    by_level = {lv: [c for c in checks if any(r["level"] == lv and r["variant"] is None for r in c["rows"])] for lv in LEVELS}
    passing = {lv: sum(1 for c in by_level[lv] if next(r for r in c["rows"] if r["level"] == lv and r["variant"] is None)["pass"]) for lv in LEVELS}
    not_impl = [r for r in rows if r["status"] == "not implemented"]

    kpis = [("routines", len(rows), "typed in type_cards"), ("graded by the ladder", len(checked), f"routines, in {len(checks)} checks")]
    kpis += [(f"checks passing at {lv}", f"{passing[lv]} / {len(by_level[lv])}", "the ruler's bound") for lv in LEVELS]
    kpis.append(("not implemented", len(not_impl), "no code anywhere"))
    reading = decision_findings()

    # the comparison table (every routine)
    trs = []
    for r in rows:
        rec = r["recovery"]
        oc = (f'<td colspan="2" class="note">{e(r["oracle"]["note"])}</td>' if r["oracle"]["status"] != "checked"
              else "".join(cell(rec.get(lv) and {**rec[lv], "within_tolerance": f"{rec[lv]['parameters']} graded", "failing": [],
                                                 "missing": [None] * rec[lv].get("missing", 0)}, f"{r['routine']} at {lv}") for lv in ("1x", "3x")))
        equipment = ", ".join(x["id"].replace("_", " ") for x in r["equipment"]) or "nothing extra"
        trs.append(f'<tr data-routine="{e(r["routine"])}"><td><b>{e(r["title"])}</b><br><code>{e(r["routine"])}</code></td>'
                   f'<td>{e(r["setting"])}</td><td title="{e(r["wall_time"]["source"])}">{seconds_text(r["wall_time"]["value"])}</td>'
                   f'<td title="{e(r["operator_time"]["source"])}">{seconds_text(r["operator_time"]["value"])}</td>'
                   f'<td title="{e(r["equipment_cost"]["source"])}">{usd(r["equipment_cost"]["value"])}'
                   f'{" <small>est.</small>" if "estimate" in r["equipment_cost"]["source"] else ""}</td>'
                   f'<td>{e(equipment)}</td><td class="num">{r["parameters_covered"]}</td><td>{e(r["status"])}</td>{oc}</tr>')
    comparison = ('<table class="cmp"><thead><tr><th>Routine</th><th>Where</th><th>Wall time</th><th>Operator</th><th>Equipment</th>'
                  '<th>Needs</th><th>Params</th><th>Code</th><th>1x</th><th>3x</th></tr></thead><tbody>' + "".join(trs) + "</tbody></table>")

    # the ladder grid (every check)
    variant_names = list(ladder["variants"])
    grid_rows = []
    for c in checks:
        byk = {(r["level"], r["variant"]): r for r in c["rows"]}
        cells = []
        for lv in LEVELS:
            r = byk.get((lv, None))
            if r is None:
                why = c["not_at"].get(lv, "not declared")
                cells.append(f'<td class="na" title="{e(why)}">n/a</td>')
                continue
            cells.append(cell({"worst_error_over_tolerance": recovered_worst(r["parameters"]), "usable": r["usable"], "pass": r["pass"],
                               "within_tolerance": f"{sum(p['within_tolerance'] for p in r['parameters'])}/{len(r['parameters'])}",
                               "missing": [p["key"] for p in r["parameters"] if p["recovered"] is None], "notes": r.get("notes", []),
                               "failing": [p["key"] for p in r["parameters"] if not p["pass"]]}, f"{c['id']} at {lv}"))
        vtext = []
        for v in variant_names:
            r = byk.get(("1x", v))
            if r is not None:
                vtext.append(f'<span class="var" title="{e(ladder["variants"][v]["what"])}">{e(v)} <b>{fmt(recovered_worst(r["parameters"]))}</b>'
                             f'{chip(r["pass"])}</span>')
        owner = "bam_ws stock" if c["owner"] == "bam_ws" else "sysid"
        grid_rows.append(f'<tr><td><b>{e(c["routine"])}</b><br><small>{e(c["example"])} · {e(owner)} · {e(c["structure"].split(":")[0])} · '
                         f'{len(c["parameters"])} hidden</small></td>{"".join(cells)}<td class="vars">{"".join(vtext) or "—"}</td></tr>')
    grid = ('<table class="grid"><thead><tr><th>Check</th>' + "".join(f"<th>{lv}</th>" for lv in LEVELS)
            + "<th>1x + a delay or a quantisation</th></tr></thead><tbody>" + "".join(grid_rows) + "</tbody></table>")

    # findings, computed
    lines = []
    for c in checks:
        for r in c["rows"]:
            if not r["pass"]:
                label = r["level"] + (f" + {r['variant']}" if r["variant"] else "")
                worst = sorted((p for p in r["parameters"] if not p["pass"]), key=lambda p: -(p["error_over_tolerance"] or math.inf))[:3]
                what = "; ".join(f"{p['key']} {'no value' if p['recovered'] is None else fmt(p['error_over_tolerance']) + 'x tol'}" for p in worst)
                lines.append(f"<li><b>{e(c['routine'])}</b> ({e(c['example'])}) fails <b>{e(label)}</b>: {e(what)}</li>")
    findings = "<ul>" + "".join(lines) + "</ul>" if lines else "<p>Every check passes at every level.</p>"
    realism = "".join(f"<li><b>{e(c['routine'])}</b>: {e(c['realism'])}</li>" for c in checks if c.get("realism"))
    unchecked = "".join(f'<tr><td><b>{e(r["title"])}</b><br><code>{e(r["routine"])}</code></td><td>{e(r["status"])}</td>'
                        f'<td>{e(r["oracle"]["note"])}</td></tr>' for r in rows if r["oracle"]["status"] != "checked")
    multiples = "".join(multiple(c) for c in checks)
    can11 = [p for p in table["parameters"] if p["example"] == "pendulum_can11"]
    per_model_1x, per_model_10x = model_table(can11, "1x"), model_table(can11, "10x")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calibration routines</title>
<style>
:root {{ color-scheme: light; --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
  --series:#2a78d6; --use:#cde2fb; --nouse:#f0efec; --good:#0ca30c; --bad:#d03b3b; --ring:rgba(11,11,11,.10); }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --surface:#1a1a19; --page:#0d0d0d; --ink:#f0efec;
  --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --axis:#383835; --series:#3987e5; --use:#104281; --nouse:#383835; --ring:rgba(255,255,255,.10); }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --page:#0d0d0d; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a;
  --axis:#383835; --series:#3987e5; --use:#104281; --nouse:#383835; --ring:rgba(255,255,255,.10); }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--page); color:var(--ink); font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:26px; margin:0 0 6px; }} h2 {{ font-size:18px; margin:32px 0 8px; }}
.lede {{ color:var(--ink2); max-width:900px; }}
.reading li {{ margin:6px 0; max-width:72em; }}
.kpis {{ display:flex; flex-wrap:wrap; gap:10px; margin:16px 0; }}
.kpi {{ background:var(--surface); border:1px solid var(--ring); border-radius:8px; padding:10px 14px; min-width:150px; }}
.kpi .v {{ font-size:22px; font-weight:600; }} .kpi .l {{ color:var(--ink2); font-size:12px; }}
.wrap {{ overflow-x:auto; background:var(--surface); border:1px solid var(--ring); border-radius:8px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }}
th, td {{ padding:6px 8px; border-bottom:1px solid var(--grid); text-align:left; vertical-align:top; }}
th {{ color:var(--ink2); font-weight:600; position:sticky; top:0; background:var(--surface); }}
td.num {{ font-variant-numeric:tabular-nums; text-align:right; }}
td.use {{ background:var(--use); }} td.nouse {{ background:var(--nouse); }} td.na {{ color:var(--muted); }}
td.use b, td.nouse b {{ font-variant-numeric:tabular-nums; margin-right:6px; }}
td.note {{ color:var(--ink2); font-size:12px; }}
code {{ font-size:11px; color:var(--ink2); }} small {{ color:var(--ink2); }}
.chip {{ display:inline-block; font-size:11px; padding:0 6px; border-radius:9px; white-space:nowrap; }}
.chip.ok {{ background:var(--good); color:#fff; }} .chip.bad {{ background:var(--bad); color:#fff; }} .chip.none {{ color:var(--muted); }}
.vars .var {{ display:block; white-space:nowrap; }}
.legend {{ color:var(--ink2); font-size:12px; margin:6px 0 0; }}
.legend i {{ display:inline-block; width:12px; height:12px; border-radius:3px; vertical-align:-2px; margin:0 4px 0 10px; }}
.mults {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:10px; }}
table.models th.grp {{ text-align:center; border-left:1px solid var(--grid); }}
.mult {{ margin:0; background:var(--surface); border:1px solid var(--ring); border-radius:8px; padding:8px; }}
.mult figcaption {{ font-size:12px; display:flex; flex-direction:column; }} .mult figcaption span {{ color:var(--ink2); }}
svg {{ width:100%; height:auto; display:block; }}
svg .grid {{ stroke:var(--grid); stroke-width:1; }} svg .tol {{ stroke:var(--axis); stroke-width:1; }}
svg .ref {{ fill:none; stroke:var(--muted); stroke-width:1; }}
svg .series {{ fill:none; stroke:var(--series); stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }}
svg .dot {{ fill:var(--series); stroke:var(--surface); stroke-width:2; }} svg .dot.fail {{ fill:var(--bad); }}
svg .tick, svg .miss {{ fill:var(--muted); font-size:10px; }}
ul li {{ margin:2px 0; }}
</style></head><body><main>
<h1>Calibration Routines, graded on the same noise</h1>
<p class="lede">Every way the house has to calibrate a twin's parameters, as a typed record (type_cards <code>ROUTINES</code>): what it identifies, where
it runs, its time and equipment cost, what it needs. The {len(checked)} the sysid oracle can run are graded on the same hidden truth at 0, 1x, 3x and
10x their sensor noise (one draw, the same seeds, scaled) and at 1x plus a delay or a quantisation. The bound at 0x is a tenth of the tolerance;
at kx it is k tolerances, never wider than not calibrating. Ruler <code>sysid/noise_ladder.json</code> (sha256 {e(ladder["ruler"]["sha256"][:12])}),
committed before any run.</p>
<div class="kpis">{"".join(f'<div class="kpi"><div class="v">{e(v)}</div><div class="l">{e(k)}<br>{e(note)}</div></div>' for k, v, note in kpis)}</div>

<h2>What it means</h2>
<p class="legend">The reading of these numbers, from the decision record <code>docs/decision-calibration-routines-2026-11-07.md</code>.</p>
{reading}

<h2>The routines</h2>
<p class="legend">Number: the worst |recovered − true| over the routine's parameters, in tolerances (1 = the use's limit).
<i style="background:var(--use)"></i>within the tolerance <i style="background:var(--nouse)"></i>outside it · the chip is the ladder's bound
at that level. Hover a time or a cost for its source.</p>
<div class="wrap">{comparison}</div>

<h2>One parameter, every model: CAN 11</h2>
<p class="legend">The parameter index of <code>calibration_routines.json</code> drawn as a site would: each hidden parameter with its true and
nominal values, then one recovered / error column group per model that recovered it (the regression's rungs, the stock fits, T10, the
camera's gap), its 95 % interval where the routine makes one. Error in tolerances, tinted where it is within the tolerance. At 1x:</p>
<div class="wrap">{per_model_1x}</div>
<p class="legend">The same at 10x:</p>
<div class="wrap">{per_model_10x}</div>

<h2>The ladder, check by check</h2>
<div class="wrap">{grid}</div>

<h2>How the error grows with the noise</h2>
<p class="legend">Worst error over tolerance at each level (log scale); the grey line is the ruler's bound before its cap, the hairline the tolerance.
A routine that degrades gracefully runs parallel to the grey line; one that breaks down crosses it.</p>
<div class="mults">{multiples}</div>

<h2>What failed where</h2>
{findings}

<h2>How real 1x is</h2>
<ul>{realism}</ul>

<h2>Not graded by the ladder, and why</h2>
<div class="wrap"><table><thead><tr><th>Routine</th><th>Code</th><th>Why no oracle numbers</th></tr></thead><tbody>{unchecked}</tbody></table></div>

<p class="legend">Built by docs/build_report_calibration_routines.py from sysid/results/calibration_routines.json and
sysid/results/noise_ladder.json (rows computed by {e(", ".join(sorted({code for c in checks for code in c["provenance"]["code"]})))}).</p>
</main></body></html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    path = build(args.out)
    print(f"{path} ({path.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
