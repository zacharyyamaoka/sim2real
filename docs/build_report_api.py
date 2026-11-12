"""The public API report (2026-11-11): the architecture diagram, the compact example, the real output of running it, and the API
reference rendered from docs/API.md.

    python3 /home/bam/sim2real/docs/build_report_api.py

Stdlib only. Reads, never computes: docs/API.md, docs/api_example.py (the runnable form of the compact example), and the capture of its
run in reports/media/sim2real-api-2026-11-11/ (example.log: the example's own terminal output; example.json: the fitted twin's parameters,
calibration and eval report, written by docs/run_api_example.py from the example's own variables; slow/: the slow acceptance tests' log and
summaries, SIM2REAL_SLOW=1 with SIM2REAL_CAPTURE). Writes reports/sim2real-api-2026-11-11.html, one text page: the diagram is inline SVG,
nothing is linked from media.

WHY a hand-drawn SVG (Zach, 2026-11-11: "create a public API documentation and architecture diagram so I understand how to use this
api"): the repo's reports draw their figures as inline SVG from Python (build_report_calibration_routines.py), themed by CSS variables,
so the page needs no library and reads in light and dark.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "reports" / "media" / "sim2real-api-2026-11-11"
OUT = REPO / "reports" / "sim2real-api-2026-11-11.html"
API = REPO / "docs" / "API.md"
EXAMPLE = REPO / "docs" / "api_example.py"


def e(text) -> str:
    return html.escape(str(text), quote=True)


def g(x, digits: int = 4) -> str:
    return "—" if x is None else f"{x:.{digits}g}"


def read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


# --- docs/API.md -> HTML (the subset it uses: headings, paragraphs, bullets two deep, fenced code, `code`, **bold**) ------------------


def inline(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{e(part[1:-1])}</code>")
        else:
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e(part)))
    return "".join(out)


def markdown(text: str) -> str:
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            body = []
            i += 1
            while not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            out.append(f"<pre>{e(chr(10).join(body))}</pre>")
            i += 1
        elif m := re.match(r"(#{1,4}) (.*)", line):
            level = len(m.group(1))
            slug = re.sub(r"[^a-z0-9]+", "-", m.group(2).lower()).strip("-")
            out.append(f"<h{level + 1} id='{slug}'>{inline(m.group(2))}</h{level + 1}>")
            i += 1
        elif line.startswith("- "):
            items: list[tuple[int, str]] = []
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("  - ")):
                depth = 1 if lines[i].startswith("  - ") else 0
                items.append((depth, lines[i].strip()[2:]))
                i += 1
            html_items, open_sub = [], False
            for depth, item in items:
                if depth == 1 and not open_sub:
                    html_items[-1] = html_items[-1].removesuffix("</li>") + "<ul>"
                    open_sub = True
                if depth == 0 and open_sub:
                    html_items.append("</ul></li>")
                    open_sub = False
                html_items.append(f"<li>{inline(item)}</li>")
            if open_sub:
                html_items.append("</ul></li>")
            out.append("<ul>" + "".join(html_items) + "</ul>")
        elif line.strip():
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,4} |- |```)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
        else:
            i += 1
    return "\n".join(out)


# --- the diagram ---------------------------------------------------------------------------------------------------------------------


def box(x, y, w, h, title, sub="", cls="pkg") -> str:
    lines = [f"<rect class='{cls}' x='{x}' y='{y}' width='{w}' height='{h}' rx='8'/>",
             f"<text class='t' x='{x + w / 2}' y='{y + (h / 2 if not sub else h / 2 - 6)}' text-anchor='middle' dominant-baseline='middle'>{e(title)}</text>"]
    if sub:
        lines.append(f"<text class='s' x='{x + w / 2}' y='{y + h / 2 + 12}' text-anchor='middle' dominant-baseline='middle'>{e(sub)}</text>")
    return "".join(lines)


def arrow(x1, y1, x2, y2, label="", cls="imp", lx=None, ly=None, anchor="start") -> str:
    out = f"<line class='{cls}' x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' marker-end='url(#head-{cls})'/>"
    if label:
        out += f"<text class='a' x='{lx if lx is not None else (x1 + x2) / 2 + 6}' y='{ly if ly is not None else (y1 + y2) / 2}' text-anchor='{anchor}' dominant-baseline='middle'>{e(label)}</text>"
    return out


def markers() -> str:
    return "<defs>" + "".join(
        f"<marker id='head-{c}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
        f"<path class='head-{c}' d='M0,0 L10,5 L0,10 z'/></marker>" for c in ("imp", "flow", "todo")) + "</defs>"


def layers_svg() -> str:
    """The packages as layers, arrows for imports only (each points at what it imports), and sim2real's own folders inside it."""
    w = 680
    parts = [f"<svg viewBox='0 0 {w} 470' role='img' aria-label='Package layers: robot_msgs, then sim2real, then robot_description, then "
             "robotparts and scripts; arrows are imports'>", markers()]
    users = ["robotparts", "cad2robot", "five_bar", "scripts"]
    for k, name in enumerate(users):
        parts.append(box(20 + k * 162, 14, 150, 40, name, cls="pkg user"))
        parts.append(arrow(95 + k * 162, 54, 95 + k * 162 if k in (1, 2) else 340, 92))
    parts.append(box(20, 92, 640, 52, "robot_description", "one robot: topology + typed instances holding Values · to_robot_twin() / from_robot_twin()",
                     cls="pkg rd"))
    parts.append(arrow(340, 144, 340, 182))
    parts.append("<text class='s' x='350' y='163' dominant-baseline='middle'>imports the light core only: types, models, RobotTwin</text>")
    # sim2real, with its folders inside
    parts.append("<rect class='pkg s2r' x='20' y='182' width='640' height='206' rx='10'/>")
    parts.append("<text class='t' x='36' y='204'>sim2real</text><text class='s' x='118' y='204'>every robot description comes with a twin</text>")
    parts.append(box(36, 220, 608, 50, "twin.py · RobotTwin · examples", "the front door over every folder: simulate() · calibrate() · eval() · .parameters",
                     cls="pkg front"))
    folders = ["metrics", "schedule", "fit", "sim", "models", "cards"]
    for k, name in enumerate(folders):
        x = 36 + k * 102
        parts.append(box(x, 296, 92, 36, name, cls="pkg folder"))
        if k:
            parts.append(arrow(x, 314, x - 8, 314, cls="imp"))
    parts.append("<text class='s' x='36' y='352'>most stable</text><text class='s' x='644' y='352' text-anchor='end'>churns most</text>")
    parts.append("<text class='s' x='340' y='352' text-anchor='middle'>each folder imports only those to its left</text>")
    parts.append("<text class='s' x='36' y='374'>MuJoCo is the `sim` extra (install size only); the app, site and dashboards live beside the package</text>")
    parts.append(arrow(340, 388, 340, 420))
    parts.append(box(20, 420, 640, 40, "robot_msgs", "Value (unit, low/high, basis, source) · JointTrajectory · Pose", cls="pkg base"))
    parts.append("</svg>")
    return "".join(parts)


def flow_svg() -> str:
    """Data flow: description -> RobotTwin -> simulate / calibrate -> fitted RobotTwin -> eval -> Report, and the calibrated values back to
    a description, then an explicit save. Dashed = robot_description's side, not built yet."""
    parts = ["<svg viewBox='0 0 680 400' role='img' aria-label='Data flow from a description to a twin, a fitted twin, a report, and back to a "
             "description'>", markers()]
    parts.append(box(20, 20, 180, 50, "RobotDescription", "robot_description (not built yet)", cls="pkg todo"))
    parts.append(box(240, 20, 220, 50, "RobotTwin", "sim2real.examples.pendulum_can11()", cls="pkg front"))
    parts.append(arrow(200, 45, 238, 45, cls="todo"))
    parts.append("<text class='a' x='220' y='88' text-anchor='middle'>to_robot_twin()</text>")
    parts.append(box(500, 20, 160, 50, "Simulation", "JointTrajectory · MuJoCo", cls="pkg out"))
    parts.append(arrow(460, 45, 498, 45, cls="flow"))
    parts.append("<text class='a' x='480' y='88' text-anchor='middle'>simulate()</text>")
    parts.append(arrow(350, 70, 350, 158, "calibrate(on=\"sim\")", cls="flow", lx=360, ly=104))
    parts.append("<text class='s' x='360' y='124'>a NEW twin; the fit never sees the truth</text>")
    parts.append(box(240, 160, 220, 50, "fitted RobotTwin", ".parameters · values_ · calibration_", cls="pkg front"))
    parts.append(box(500, 160, 160, 50, "Report", "error ÷ floor · gates", cls="pkg out"))
    parts.append(arrow(460, 185, 498, 185, cls="flow"))
    parts.append("<text class='a' x='480' y='228' text-anchor='middle'>eval()</text>")
    parts.append("<text class='s' x='480' y='244' text-anchor='middle'>held-out runs only</text>")
    parts.append(box(20, 160, 180, 50, "new RobotDescription", "calibrated Values, MEASURED", cls="pkg todo"))
    parts.append(arrow(240, 185, 202, 185, cls="todo"))
    parts.append("<text class='a' x='220' y='228' text-anchor='middle'>from_robot_twin(fitted)</text>")
    parts.append(arrow(110, 210, 110, 298, "explicit save", cls="todo", lx=120, ly=254))
    parts.append(box(20, 300, 180, 50, "file · robotparts", "never written by calibrate()", cls="pkg todo"))
    parts.append("<line class='todo' x1='250' y1='336' x2='290' y2='336'/><text class='s' x='298' y='336' dominant-baseline='middle'>"
                 "robot_description's side, not built yet</text>")
    parts.append("<line class='flow' x1='250' y1='362' x2='290' y2='362'/><text class='s' x='298' y='362' dominant-baseline='middle'>"
                 "sim2real, runs today</text>")
    parts.append("</svg>")
    return "".join(parts)


# --- the captured run ----------------------------------------------------------------------------------------------------------------


def parameters_table(run: dict | None) -> str:
    if run is None:
        return "<p class='mut'>Not captured yet: run docs/run_api_example.py.</p>"
    rows = []
    for instance, named in run["parameters"].items():
        for name, v in named.items():
            prior = run["priors"].get(instance, {}).get(name)
            if v is None:
                continue
            fitted = v.get("basis") == "measured"
            interval = f"[{g(v.get('low'), 5)}, {g(v.get('high'), 5)}]" if v.get("low") is not None else "—"
            rows.append(f"<tr class='{'fit' if fitted else ''}'><th scope='row'><code>{e(instance)}.{e(name)}</code></th><td>{e(v.get('unit', ''))}</td>"
                        f"<td>{g(None if prior is None else prior['value'])}</td><td><b>{g(v['value'])}</b></td><td>{e(interval)}</td>"
                        f"<td>{e(v.get('basis', ''))}</td><td class='mut'>{e(v.get('source', ''))}</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>parameter</th><th>unit</th><th>prior</th><th>fitted.parameters</th><th>95 % interval (low, high)</th>"
            "<th>basis</th><th>source</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def slow_summary() -> str:
    log = read(MEDIA / "slow" / "slow.log")
    if log is None:
        return "<p class='mut'>Not run yet.</p>"
    tail = [line for line in log.splitlines() if re.search(r"passed|failed|error|^exit ", line)]
    return f"<pre>{e(chr(10).join(tail[-3:]))}</pre>"


def main() -> None:
    run = json.loads(read(MEDIA / "example.json")) if (MEDIA / "example.json").is_file() else None
    log = read(MEDIA / "example.log")
    err = read(MEDIA / "example.err") or ""
    took = re.search(r"real\s+(\S+)", err)
    passed = run is not None and run["report"]["passed"] and run["calibration"]["passed"]
    compact = API.read_text(encoding="utf-8").split("```python\n", 1)[1].split("```", 1)[0].rstrip()
    verdict = ("<b>The compact example runs end to end on the CAN 11 oracle, and the fitted twin passes its gates.</b>" if passed else
               "<b>The compact example has not passed yet.</b>" if run else "<b>The compact example's run is not captured yet.</b>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>sim2real API</title>
<style>
:root {{ --bg:#fff; --bg2:#f5f6f7; --ink:#16181b; --ink3:#5f6670; --rule:#dcdfe3; --good:#1f7a3d; --bad:#b42318; --accent:#1d5fbf;
  --pkg:#f3f5f8; --pkg-ring:#b9c0c9; --front:#e7f0fd; --front-ring:#1d5fbf; --todo-ring:#8a919b; --out:#eef7f0; --out-ring:#1f7a3d; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141619; --bg2:#1d2024; --ink:#e7e9ec; --ink3:#a3aab4; --rule:#30343a;
  --good:#5cc27e; --bad:#ff7b6e; --accent:#7fb0ff; --pkg:#1d2126; --pkg-ring:#4a515b; --front:#16263d; --front-ring:#7fb0ff; --todo-ring:#7d848e;
  --out:#15291c; --out-ring:#5cc27e; }} }}
:root[data-theme="dark"] {{ --bg:#141619; --bg2:#1d2024; --ink:#e7e9ec; --ink3:#a3aab4; --rule:#30343a; --good:#5cc27e; --bad:#ff7b6e; --accent:#7fb0ff;
  --pkg:#1d2126; --pkg-ring:#4a515b; --front:#16263d; --front-ring:#7fb0ff; --todo-ring:#7d848e; --out:#15291c; --out-ring:#5cc27e; }}
body {{ background:var(--bg); color:var(--ink); font:15px/1.55 system-ui, sans-serif; margin:0; }}
main {{ max-width:1000px; margin:0 auto; padding:20px 16px 60px; }}
h1 {{ font-size:25px; margin:8px 0 6px; }} h2 {{ margin-top:36px; border-bottom:1px solid var(--rule); padding-bottom:4px; font-size:20px; }}
h3 {{ font-size:17px; margin-top:26px; }} h4 {{ font-size:15px; margin:22px 0 4px; font-family:ui-monospace, monospace; }}
.verdict {{ font-size:16px; padding:10px 14px; border-left:4px solid var(--good); background:var(--bg2); }}
.mut {{ color:var(--ink3); }} code, pre {{ font-family:ui-monospace, monospace; font-size:12.5px; }}
pre {{ background:var(--bg2); border:1px solid var(--rule); padding:10px 12px; overflow:auto; white-space:pre; max-height:620px; }}
pre.hero {{ font-size:14px; line-height:1.6; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }} th, td {{ text-align:left; padding:5px 8px; border-bottom:1px solid var(--rule); vertical-align:top; }}
td {{ font-variant-numeric:tabular-nums; }} tr.fit th, tr.fit td b {{ color:var(--accent); }}
.scroll {{ overflow-x:auto; }}
.fig {{ overflow-x:auto; border:1px solid var(--rule); border-radius:8px; background:var(--bg); padding:8px; margin:10px 0 4px; }}
.fig svg {{ display:block; width:100%; min-width:600px; height:auto; }}
svg .pkg {{ fill:var(--pkg); stroke:var(--pkg-ring); stroke-width:1.2; }} svg .user {{ fill:var(--bg); }}
svg .front {{ fill:var(--front); stroke:var(--front-ring); stroke-width:1.6; }} svg .out {{ fill:var(--out); stroke:var(--out-ring); }}
svg .todo {{ fill:none; stroke:var(--todo-ring); stroke-width:1.4; stroke-dasharray:5 4; }} svg rect.todo {{ fill:var(--bg); }}
svg .s2r {{ fill:none; stroke:var(--front-ring); stroke-width:1.6; }} svg .base, svg .rd {{ fill:var(--pkg); }}
svg .t {{ fill:var(--ink); font:600 14px system-ui, sans-serif; }} svg .s {{ fill:var(--ink3); font:11.5px system-ui, sans-serif; }}
svg .a {{ fill:var(--ink); font:12px ui-monospace, monospace; }}
svg .imp {{ stroke:var(--ink3); stroke-width:1.4; }} svg .flow {{ stroke:var(--accent); stroke-width:1.8; }}
svg .head-imp {{ fill:var(--ink3); }} svg .head-flow {{ fill:var(--accent); }} svg .head-todo {{ fill:var(--todo-ring); }}
ul li {{ margin:3px 0; }} .ref h2 {{ font-size:19px; }}
</style></head><body><main>
<h1>sim2real public API</h1>
<p class="verdict">{verdict} <code>sim2real.examples.pendulum_can11()</code> → <code>.simulate()</code> → <code>.calibrate(on="sim")</code> →
<code>.eval()</code>, and <code>fitted.parameters</code> carries the calibrated values with their provenance. The robot_description side
(<code>to_robot_twin()</code> / <code>from_robot_twin()</code>) isn't built yet.</p>

<h2>The compact example</h2>
<pre class="hero">{e(compact)}</pre>
<p class="mut">What ran: <code>docs/api_example.py</code>, the same lines with the last one (robot_description's, not built yet) swapped for
<code>parameters = fitted.parameters</code>, which is what <code>from_robot_twin</code> will take.</p>
<pre>{e(read(EXAMPLE) or "")}</pre>

<h2>Its real output</h2>
<p class="mut">The example's own stdout (<code>docs/run_api_example.py</code> runs it verbatim and keeps its variables){f"; wall time {e(took.group(1))}" if took else ""}.
<code>twin.simulate()</code> prints nothing because the example doesn't print it.</p>
<pre>{e((log or "(not captured yet)").rstrip())}</pre>
<h3>What <code>fitted.parameters</code> holds</h3>
<p>Every fitted value replaces its prior as a <code>measured</code> robot_msgs <code>Value</code>, with its 95 % interval as <code>low</code>/<code>high</code>
and a source that names the calibration. The loaded twin keeps its priors.</p>
{parameters_table(run)}
<h3>The slow acceptance tests, same code</h3>
<p class="mut"><code>SIM2REAL_SLOW=1 pytest tests/test_one_click.py</code>: green on the hidden truth and red on a truth moved 10 %. The green test also asserts
<code>fitted.parameters</code>.</p>
{slow_summary()}

<h2>Architecture</h2>
<h3>Packages: arrows are imports</h3>
<div class="fig">{layers_svg()}</div>
<p class="mut">sim2real sits right above robot_msgs on purpose: every robot description should come with a twin. robot_description imports only
sim2real's light core, and sim2real imports neither robot_description nor robotparts, so there is no cycle.</p>
<h3>Data flow</h3>
<div class="fig">{flow_svg()}</div>

<h2>The reference</h2>
<p class="mut">Rendered from <code>docs/API.md</code>.</p>
<div class="ref">{markdown(API.read_text(encoding="utf-8").split(chr(10), 1)[1])}</div>
</main></body></html>"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
