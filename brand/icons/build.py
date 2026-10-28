"""Build the sim2real icon proposals, the default icon, the README and the pick report.

    uv run --no-project --with svgpathtools python /home/bam/sim2real/brand/icons/build.py

Writes (all derived from marks.py, so edit the marks there and rebuild):
- brand/icons/proposals/NN-<slug>.svg      the 24 px lucide-style toolbar mark
- brand/icons/proposals/NN-<slug>-app.svg  the 256 px colour app/dock icon
- brand/icons/sim2real.svg, sim2real-app.svg, sim2real.iconnode.json   proposal 01, the default
- brand/icons/README.md
- reports/sim2real-icons-2026-10-27.html   the self-contained pick surface
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from marks import (  # noqa: E402
    BAM_GREEN,
    BAM_GREEN_LIT,
    CRITERIA,
    INK,
    MARKS,
    PAPER,
    SCORES,
    Mark,
    icon_node,
    score,
    svg24,
    svg_app,
)

DATE = "2026-10-27"
REPORT = REPO / "reports" / f"sim2real-icons-{DATE}.html"
LUCIDE = json.loads((HERE / "lucide_reference.json").read_text())["icons"]

TOP3_WHY = {
    "twin-tiles": "The BAM mark's own grammar (square tiles, a one-stroke gap), nothing in lucide or the sibling "
    "apps looks like it, and at 16 px it still says 'a thing and its twin'. Its one weakness: it is 8 of 24 units "
    "tall, so it sits a little lighter than its lucide neighbours.",
    "half-wire-cube": "The clearest picture of a digital twin (solid half, wireframe half) and the richest app icon. "
    "Second only because objectdb's proposals are cubes too, so the two could blur in one ribbon.",
    "approx-twin": "The simplest mark and the best at 16 px: ≈ with the twin's line dashed. The price is that it sits "
    "close to lucide's own equal-approximately.",
}


def num(i: int) -> str:
    return f"{i:02d}"


def write_files() -> None:
    proposals = HERE / "proposals"
    proposals.mkdir(exist_ok=True)
    for i, m in enumerate(MARKS, 1):
        (proposals / f"{num(i)}-{m.slug}.svg").write_text(svg24(m) + "\n")
        (proposals / f"{num(i)}-{m.slug}-app.svg").write_text(svg_app(m, title=f"sim2real - {m.name}") + "\n")
    default = MARKS[0]
    (HERE / "sim2real.svg").write_text(svg24(default) + "\n")
    (HERE / "sim2real-app.svg").write_text(svg_app(default, title="sim2real") + "\n")
    (HERE / "sim2real.iconnode.json").write_text(json.dumps(icon_node(default)) + "\n")


def write_readme() -> None:
    d = MARKS[0]
    def cell(text: str) -> str:
        return text.replace("|", "\\|")  # a bare | ends a markdown table cell (Mirror Handle's ‹|›)

    rows = "\n".join(
        f"| {num(i)} | **{cell(m.name)}** | {cell(m.metaphor)} | {score(m.slug)} | {cell(m.why)} |"
        for i, m in enumerate(MARKS, 1)
    )
    crit = ", ".join(f"{label} {w}" for _, label, w, _ in CRITERIA)
    text = f"""# sim2real icons

Twenty proposals for the sim2real app icon (Zach, {DATE}: "Please make 20 proposals for a simple icon for sim2real").

- **Default until Zach picks: 01 {d.name}.** `sim2real.svg` (toolbar) and `sim2real-app.svg` (app/dock) are copies of
  `proposals/01-{d.slug}.svg` and `proposals/01-{d.slug}-app.svg`. Picking another number means rebuilding with that
  mark first in `marks.py`.
- **Pick surface:** `/home/bam/sim2real/reports/sim2real-icons-{DATE}.html` (every mark at 16 / 24 / 48 px in a mock
  Clank ribbon, dark and light, the 256 px app icon, a pick toggle and comment per mark, and "Copy my picks").

## The rules every mark follows

- **Toolbar mark = a lucide icon:** 24×24 viewBox, `stroke="currentColor"`, `stroke-width="2"`, round caps and joins, no
  fill, so it sits in Clank's ribbon (`ctx.registerRibbonItem({{ icon }})` takes a `LucideIcon`) beside stock icons.
- **Solid stroke = the real device, dashed stroke = the twin.** Dashes are explicit short paths that start and end on
  the path's own corners (lucide's `square-dashed` convention), never a `stroke-dasharray` that can drop a corner.
- **App icon = the same strokes on a Grid Purist tile:** ink `{INK}` tile with the BAM mark's micro radius (12/256),
  the real part in paper `{PAPER}`, the twin in green, helper lines in grey.
- **Green on the ink tile is `{BAM_GREEN_LIT}`,** BAM Green `{BAM_GREEN}`'s own hue lifted to OKLCH L 0.80: `{BAM_GREEN}`
  is 3.2:1 on ink, too faint for a dashed line in a dock; the lit one is 11:1. On a paper tile the brand green
  `{BAM_GREEN}` is used as decided on 2026-10-24 (the report's palette switch shows both).

## The twenty

Numbered by score, best first. Scores are AI judgement, 1-5 per criterion, weighted ({crit}); not measured.

| # | name | metaphor | score | why |
|---|---|---|---|---|
{rows}

## Use it in Clank

`sim2real.iconnode.json` is the default mark in lucide's own iconNode shape:

```ts
const Sim2Real = createLucideIcon('sim2real', iconNode)
```

`createLucideIcon` is lucide-react's own factory (`lucide-react` 1.42.0 in Clank); the result is a `LucideIcon` that
`registerRibbonItem` accepts.

## Rebuild and check

```bash
uv run --no-project --with svgpathtools python /home/bam/sim2real/brand/icons/build.py
```

```bash
uv run --no-project --with playwright --with svgpathtools --with pillow python /home/bam/sim2real/brand/icons/render_check.py --out /tmp/s2r-renders
```

`render_check.py` rasterises every mark at 16 / 24 / 48 px at device pixel ratio 1 and writes a 3× nearest-neighbour
zoom, so the 16 px case can be looked at pixel by pixel. `lucide_reference.json` holds the stock lucide icons (ISC)
the report draws beside the proposals.
"""
    (HERE / "README.md").write_text(text)


# ----------------------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------------------


def lucide_symbol(name: str) -> str:
    body = []
    for tag, attrs in LUCIDE[name]:
        a = " ".join(f'{k}="{html.escape(v)}"' for k, v in attrs.items())
        body.append(f"<{tag} {a}/>")
    return (
        f'<symbol id="L-{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{"".join(body)}</symbol>'
    )


def mark_symbol(i: int, m: Mark) -> str:
    inner = re.sub(r"^<svg[^>]*>|</svg>$", "", svg24(m))
    return (
        f'<symbol id="i{num(i)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</symbol>'
    )


def app_symbol(i: int, m: Mark) -> str:
    inner = re.sub(r"^<svg[^>]*>|</svg>$", "", svg_app(m, classes=True))
    return f'<symbol id="a{num(i)}" viewBox="0 0 256 256">{inner}</symbol>'


def use(ref: str, size: int, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<svg{c} width="{size}" height="{size}" aria-hidden="true"><use href="#{ref}"/></svg>'


def ribbon_btn(ref: str, size: int, label: str = "") -> str:
    tip = f' title="{html.escape(label)}"' if label else ""
    return f'<span class="rb rb{size}"{tip}>{use(ref, size)}</span>'


def sizes_strip(i: int, theme: str) -> str:
    cells = "".join(f'<span class="rb rb{s}">{use("i" + num(i), s)}</span>' for s in (16, 24, 48))
    return f'<div class="rib {theme} sizes">{cells}</div>'


def rail(ref: str, theme: str, label: str) -> str:
    """A mock of Clank's collapsed shadcn ribbon (sidebar-07 rail): 32 px buttons, 16 px icons."""
    top = ["folder", "search", "git-branch", "puzzle"]
    bottom = ["settings", "circle-question-mark"]
    btns = "".join(ribbon_btn(f"L-{n}", 16) for n in top)
    btns += f'<span class="rb rb16 cand" title="{html.escape(label)}">{use(ref, 16)}</span>'
    btns += ribbon_btn("L-layout-grid", 16)
    btns += '<span class="spacer"></span>' + "".join(ribbon_btn(f"L-{n}", 16) for n in bottom)
    return f'<div class="rail {theme}" aria-label="{html.escape(label)} in a mock Clank ribbon">{btns}</div>'


def toolbar(top5: list[tuple[int, Mark]], theme: str, size: int) -> str:
    left = "".join(ribbon_btn(f"L-{n}", size) for n in ("folder", "search", "git-branch", "box", "bot"))
    mid = "".join(
        f'<span class="rb rb{size} cand" title="{num(i)} {html.escape(m.name)}">{use("i" + num(i), size)}</span>'
        for i, m in top5
    )
    right = "".join(ribbon_btn(f"L-{n}", size) for n in ("columns-2", "settings", "circle-question-mark"))
    return f'<div class="rib {theme} toolbar">{left}<span class="sep"></span>{mid}<span class="sep"></span>{right}</div>'


def criteria_chips(m: Mark) -> str:
    chips = []
    for key, label, weight, _ in CRITERIA:
        v = SCORES[m.slug][key]
        chips.append(
            f'<span class="chip" title="{html.escape(label)} (weight {weight}): {v} of 5">'
            f'<span class="cl">{html.escape(label)}</span><span class="dots">'
            + "".join(f'<i class="{"on" if k < v else ""}"></i>' for k in range(5))
            + "</span></span>"
        )
    return '<div class="chips">' + "".join(chips) + "</div>"


def card(i: int, m: Mark) -> str:
    n = num(i)
    risk = f'<p class="risk"><b>Could be mistaken for:</b> {html.escape(m.risk)}</p>' if m.risk else ""
    return f"""
<article class="card" id="m{n}" data-n="{n}">
  <header class="card-h">
    <span class="no">{n}</span>
    <div class="nm"><h3>{html.escape(m.name)}</h3><span class="meta">{html.escape(m.metaphor)}</span></div>
    <span class="score" title="weighted score out of 100">{score(m.slug)}</span>
  </header>
  <div class="card-top">
    {use("a" + n, 112, "appicon")}
    <div class="px"><div class="pxrow"><canvas class="pxv" data-n="{n}" data-theme="dark" width="64" height="64" aria-label="16 px raster, dark, zoomed 4x"></canvas><canvas class="pxv" data-n="{n}" data-theme="light" width="64" height="64" aria-label="16 px raster, light, zoomed 4x"></canvas></div><span class="pxcap">16 px at 1×, zoomed 4×</span></div>
  </div>
  <div class="tb">{sizes_strip(i, "dark")}{sizes_strip(i, "light")}</div>
  <p class="why">{html.escape(m.why)}</p>
  {risk}
  {criteria_chips(m)}
  <div class="pick-row">
    <button type="button" class="pick" data-pick="{n}" aria-pressed="false"><span class="star" aria-hidden="true">☆</span> Pick</button>
    <textarea class="cmt" data-comment="{n}" rows="2" placeholder="Comment on {n} (saved in this browser)"></textarea>
  </div>
</article>"""


CSS = """
:root{--bg:#FBFBF8;--surface:#FFFFFF;--ink:#0E100E;--muted:#5D625C;--line:#DFE1DB;--green:#2F6F4F;--green-ink:#FBFBF8;
--soft:#F1F3EE;--rib-d-bg:#262626;--rib-d-fg:#dadada;--rib-d-hover:rgba(255,255,255,.067);--rib-d-line:#363636;
--rib-l-bg:#f6f6f6;--rib-l-fg:#222222;--rib-l-hover:rgba(0,0,0,.067);--rib-l-line:#e0e0e0;
--app-tile:#0E100E;--app-real:#FBFBF8;--app-shade:#B9BDB6;--app-sim:#35DE95;--app-aux:#8A8F89;--app-key:none;
color-scheme:light dark}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0E100E;--surface:#161916;--ink:#ECEDE8;--muted:#9AA09A;
--line:#2A2E2A;--green:#35DE95;--green-ink:#0E100E;--soft:#1C201C}}
:root[data-theme="dark"]{--bg:#0E100E;--surface:#161916;--ink:#ECEDE8;--muted:#9AA09A;--line:#2A2E2A;--green:#35DE95;
--green-ink:#0E100E;--soft:#1C201C}
:root.pal-paper{--app-tile:#FBFBF8;--app-real:#0E100E;--app-shade:#4A4F4A;--app-sim:#2F6F4F;--app-aux:#9DA29B;--app-key:#DFE1DB}
.ic-tile{fill:var(--app-tile);stroke:var(--app-key)}.ic-real{stroke:var(--app-real)}.ic-sim{stroke:var(--app-sim)}
.ic-aux{stroke:var(--app-aux)}.ic-realfill{fill:var(--app-real)}.ic-shade{fill:var(--app-shade)}.ic-simfill{fill:var(--app-sim)}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1240px;margin:0 auto;padding:28px 16px 120px}
h1{font-size:26px;line-height:1.2;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:19px;margin:44px 0 6px;letter-spacing:-.005em}
h3{font-size:16px;margin:0}
p{margin:6px 0}
.sub{color:var(--muted);margin:0 0 18px}
.mono,code{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.92em}
code{background:var(--soft);padding:1px 5px;border-radius:4px}
.topbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;margin-bottom:14px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{background:transparent;color:var(--ink);border:0;padding:6px 10px;font:inherit;font-size:13px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.verdict{border:1px solid var(--line);border-left:4px solid var(--green);background:var(--surface);border-radius:10px;padding:14px 16px}
.verdict .lead{font-size:17px;margin:0 0 4px}
.top3{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:14px}
.t3{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:start}
.t3 .rank{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.t3 h3{margin:2px 0 6px}
.t3 .rowi{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.crit{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--muted);font-size:13px;margin-top:10px}
.crit b{color:var(--ink);font-weight:600}
.rib{display:flex;align-items:center;gap:2px;padding:6px;border-radius:8px;border:1px solid}
.rib.dark,.rail.dark{background:var(--rib-d-bg);color:var(--rib-d-fg);border-color:var(--rib-d-line)}
.rib.light,.rail.light{background:var(--rib-l-bg);color:var(--rib-l-fg);border-color:var(--rib-l-line)}
.rb{display:inline-flex;align-items:center;justify-content:center;border-radius:6px;flex:none}
.rb16{width:32px;height:32px}.rb24{width:40px;height:40px}.rb48{width:64px;height:64px}
.dark .rb:hover{background:var(--rib-d-hover)}.light .rb:hover{background:var(--rib-l-hover)}
.dark .cand{box-shadow:inset 0 0 0 1px rgba(255,255,255,.16)}.light .cand{box-shadow:inset 0 0 0 1px rgba(0,0,0,.14)}
.allrib{display:flex;flex-direction:column;gap:10px;margin-top:12px}
.allrow{display:flex;flex-wrap:wrap;gap:2px 4px;padding:8px}
.allrow .cell{display:inline-flex;flex-direction:column;align-items:center;gap:2px}
.allrow .lbl{font:11px/1 ui-monospace,Menlo,monospace;opacity:.7}
.allrow .sz{font:11px/1 ui-monospace,Menlo,monospace;opacity:.6;width:34px;align-self:center}
.strip{display:flex;flex-wrap:wrap;gap:14px;margin-top:12px}
.strip-group{display:flex;flex-direction:column;gap:8px}
.strip-group .gl{font-size:12px;color:var(--muted)}
.rails{display:flex;gap:8px;flex-wrap:wrap}
.railwrap{display:flex;flex-direction:column;align-items:center;gap:4px}
.railwrap{width:56px}.railwrap .rl{font:10.5px/1.2 ui-monospace,Menlo,monospace;color:var(--muted);text-align:center;max-width:56px}
.rail{display:flex;flex-direction:column;align-items:center;gap:2px;width:48px;height:330px;padding:8px 0;border-radius:8px;border:1px solid}
.rail .spacer{flex:1}
.toolbar{flex-wrap:wrap}
.toolbar .sep{width:1px;align-self:stretch;margin:4px 6px;background:currentColor;opacity:.2}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px;margin-top:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:8px}
.card.picked{border-color:var(--green);box-shadow:0 0 0 1px var(--green)}
.card-h{display:flex;align-items:center;gap:10px}
.card-h .no{font:600 20px/1 ui-monospace,Menlo,monospace;color:var(--muted)}
.card-h .nm{flex:1;min-width:0}.card-h .meta{font-size:12.5px;color:var(--muted)}
.score{font:600 13px/1 ui-monospace,Menlo,monospace;border:1px solid var(--line);border-radius:999px;padding:4px 8px}
.card-top{display:flex;gap:14px;align-items:center}
.appicon{display:block;flex:none}
.tb{display:flex;gap:6px;flex-wrap:wrap}
.sizes{padding:2px;gap:0}.sizes .rb48{width:58px;height:58px}
.px{display:flex;flex-direction:column;gap:4px}.pxrow{display:flex;gap:6px}
.pxv{width:64px;height:64px;image-rendering:pixelated;border-radius:4px;border:1px solid var(--line)}
.pxcap{font-size:11px;color:var(--muted)}
.why{font-size:14px}
.risk{font-size:13px;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:4px 10px}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--muted)}
.dots{display:inline-flex;gap:2px}.dots i{width:6px;height:6px;border-radius:1px;background:var(--line);display:block}
.dots i.on{background:var(--green)}
.pick-row{display:flex;gap:8px;align-items:stretch}
.pick{flex:none;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:8px;padding:6px 12px;font:inherit;font-size:14px;cursor:pointer}
.pick[aria-pressed="true"]{background:var(--green);color:var(--green-ink);border-color:var(--green)}
.cmt{flex:1;min-width:0;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit;font-size:13px;padding:6px 8px;resize:vertical}
.dock{position:fixed;left:0;right:0;bottom:0;background:var(--surface);border-top:1px solid var(--line);z-index:5}
.dock-in{max-width:1240px;margin:0 auto;padding:10px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dock .status{flex:1;min-width:0;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{border:1px solid var(--ink);background:var(--ink);color:var(--bg);border-radius:8px;padding:8px 14px;font:inherit;font-size:14px;cursor:pointer}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
#copyout{width:100%;font:12px/1.4 ui-monospace,Menlo,monospace;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);padding:8px;display:none}
.notes{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:10px}
.note{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;font-size:14px}
.note h3{margin-bottom:6px}
.note ul{margin:6px 0;padding-left:18px}
.swatch{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;border:1px solid var(--line)}
pre{white-space:pre-wrap;word-break:break-all;background:var(--soft);padding:8px;border-radius:8px;font-size:12px;margin:6px 0}
a{color:inherit}
@media (max-width:520px){h1{font-size:22px}.t3{grid-template-columns:1fr}.rail{height:300px}}
"""

JS = r"""
(function(){
const KEY='sim2real-icons-2026-10-27';
let state={picks:{},comments:{},palette:'ink',theme:''};
try{const raw=localStorage.getItem(KEY);if(raw){const s=JSON.parse(raw);if(s&&typeof s==='object')state=Object.assign(state,s);}}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(e){}}
const root=document.documentElement;
function applyPalette(){root.classList.toggle('pal-paper',state.palette==='paper');
  document.querySelectorAll('[data-palette]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.palette===state.palette)));}
function applyTheme(){if(state.theme)root.setAttribute('data-theme',state.theme);else root.removeAttribute('data-theme');
  document.querySelectorAll('[data-theme-btn]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeBtn===(state.theme||'auto'))));}
document.querySelectorAll('[data-palette]').forEach(b=>b.addEventListener('click',()=>{state.palette=b.dataset.palette;applyPalette();save();}));
document.querySelectorAll('[data-theme-btn]').forEach(b=>b.addEventListener('click',()=>{const t=b.dataset.themeBtn;state.theme=t==='auto'?'':t;applyTheme();save();}));
function renderPicks(){
  document.querySelectorAll('[data-pick]').forEach(b=>{const n=b.dataset.pick,on=!!state.picks[n];
    b.setAttribute('aria-pressed',String(on));b.querySelector('.star').textContent=on?'★':'☆';
    const c=document.getElementById('m'+n);if(c)c.classList.toggle('picked',on);});
  const picked=Object.keys(state.picks).filter(n=>state.picks[n]).sort();
  const cm=Object.keys(state.comments).filter(n=>(state.comments[n]||'').trim()).length;
  document.getElementById('status').textContent=picked.length?('Picked: '+picked.map(n=>n+' '+NAMES[n]).join(', ')+(cm?' · '+cm+' comment'+(cm>1?'s':''):'')):(cm?cm+' comment'+(cm>1?'s':'')+', nothing picked yet':'Nothing picked yet. Default stays 01 '+NAMES['01']+'.');
}
document.querySelectorAll('[data-pick]').forEach(b=>b.addEventListener('click',()=>{const n=b.dataset.pick;state.picks[n]=!state.picks[n];if(!state.picks[n])delete state.picks[n];renderPicks();save();}));
document.querySelectorAll('[data-comment]').forEach(t=>{const n=t.dataset.comment;t.value=state.comments[n]||'';
  t.addEventListener('input',()=>{state.comments[n]=t.value;if(!t.value.trim())delete state.comments[n];renderPicks();save();});});
function picksText(){
  const picked=Object.keys(state.picks).filter(n=>state.picks[n]).sort();
  const nums=Array.from(new Set(picked.concat(Object.keys(state.comments).filter(n=>(state.comments[n]||'').trim())))).sort();
  const lines=['sim2real icon picks (reports/sim2real-icons-2026-10-27.html)'];
  lines.push('Picked: '+(picked.length?picked.map(n=>n+' '+NAMES[n]).join(', '):'none (default stays 01 '+NAMES['01']+')'));
  lines.push('App tile: '+(state.palette==='paper'?'paper':'ink'));
  nums.forEach(n=>{const c=(state.comments[n]||'').trim();lines.push('- '+n+' '+NAMES[n]+(state.picks[n]?' [picked]':'')+(c?': '+c.replace(/\s+/g,' '):''));});
  return lines.join('\n');
}
const out=document.getElementById('copyout');
document.getElementById('copy').addEventListener('click',async()=>{
  const text=picksText();out.value=text;out.style.display='block';let ok=false;
  try{if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(text);ok=true;}}catch(e){}
  if(!ok){try{out.focus();out.select();ok=document.execCommand('copy');}catch(e){}}
  const b=document.getElementById('copy');b.textContent=ok?'Copied':'Select and copy below';setTimeout(()=>{b.textContent='Copy my picks';},1800);
});
document.getElementById('clear').addEventListener('click',()=>{if(!confirm('Clear every pick and comment in this browser?'))return;
  state.picks={};state.comments={};document.querySelectorAll('[data-comment]').forEach(t=>t.value='');renderPicks();save();});
// Pixel views: rasterise each mark onto a real 16x16 canvas, then blow it up 4x with no smoothing.
const BG={dark:['#262626','#dadada'],light:['#f6f6f6','#222222']};
document.querySelectorAll('canvas.pxv').forEach(cv=>{
  const n=cv.dataset.n,th=BG[cv.dataset.theme];const dpr=window.devicePixelRatio||1;
  cv.width=64*dpr;cv.height=64*dpr;
  const img=new Image();
  img.onload=()=>{const s=document.createElement('canvas');s.width=16;s.height=16;const x=s.getContext('2d');
    x.fillStyle=th[0];x.fillRect(0,0,16,16);x.drawImage(img,0,0,16,16);
    const c=cv.getContext('2d');c.imageSmoothingEnabled=false;c.drawImage(s,0,0,16,16,0,0,cv.width,cv.height);};
  img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(ICONS[n].replace(/currentColor/g,th[1]));
});
applyPalette();applyTheme();renderPicks();
})();
"""


def build_report() -> str:
    numbered = list(enumerate(MARKS, 1))
    top5 = numbered[:5]
    sprite = (
        '<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>'
        + "".join(mark_symbol(i, m) for i, m in numbered)
        + "".join(app_symbol(i, m) for i, m in numbered)
        + "".join(lucide_symbol(n) for n in LUCIDE)
        + "</defs></svg>"
    )
    top3 = ""
    for i, m in numbered[:3]:
        n = num(i)
        top3 += f"""
<div class="t3">
  {use("a" + n, 96, "appicon")}
  <div>
    <div class="rank">#{i} · score {score(m.slug)}</div>
    <h3><a href="#m{n}">{n} {html.escape(m.name)}</a></h3>
    <p>{html.escape(TOP3_WHY[m.slug])}</p>
    <div class="rowi">{sizes_strip(i, "dark")}{sizes_strip(i, "light")}</div>
  </div>
</div>"""
    crit = "".join(
        f'<span title="{html.escape(desc)}"><b>{html.escape(label)}</b> {w}</span>' for _, label, w, desc in CRITERIA
    )

    def all_rows(theme: str) -> str:
        rows = ""
        for s in (16, 24, 48):
            cells = "".join(
                f'<span class="cell"><span class="rb rb{s}" title="{num(i)} {html.escape(m.name)}">{use("i" + num(i), s)}</span>'
                f'<span class="lbl">{num(i)}</span></span>'
                for i, m in numbered
            )
            rows += f'<div class="rib {theme} allrow"><span class="sz">{s}px</span>{cells}</div>'
        return rows

    rails = ""
    for theme in ("dark", "light"):
        rails += (
            f'<div class="strip-group"><span class="gl">Clank ribbon, {theme}</span><div class="rails">'
            + "".join(
                f'<div class="railwrap">{rail("i" + num(i), theme, num(i) + " " + m.name)}<span class="rl">{num(i)} {html.escape(m.name)}</span></div>'
                for i, m in top5
            )
            + "</div></div>"
        )
    toolbars = "".join(
        f'<div class="strip-group"><span class="gl">toolbar, {theme}, {s} px · lucide | top 5 | lucide</span>{toolbar(top5, theme, s)}</div>'
        for theme in ("dark", "light")
        for s in (16, 24)
    )
    cards = "".join(card(i, m) for i, m in numbered)
    names = json.dumps({num(i): m.name for i, m in numbered}, ensure_ascii=False)
    icons = json.dumps({num(i): svg24(m) for i, m in numbered})
    default = MARKS[0]

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sim2real icon proposals</title>
<link rel="icon" href="data:image/svg+xml,{html.escape(svg_app(default, size=64).replace('#', '%23'))}">
<style>{CSS}</style>
</head>
<body>
{sprite}
<main>
<div class="topbar">
  <div>
    <h1>sim2real icon · 20 proposals</h1>
    <p class="sub">{DATE} · for Clank's ribbon (lucide grid, 24 px, stroke 2) and the dock (256 px, colour) · solid stroke = real, dashed = twin</p>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <div class="seg" role="group" aria-label="App tile colour"><button type="button" data-palette="ink">Ink tile</button><button type="button" data-palette="paper">Paper tile</button></div>
    <div class="seg" role="group" aria-label="Page theme"><button type="button" data-theme-btn="auto">Auto</button><button type="button" data-theme-btn="light">Light</button><button type="button" data-theme-btn="dark">Dark</button></div>
  </div>
</div>

<section class="verdict" aria-label="Verdict">
  <p class="lead"><b>Default: 01 {html.escape(default.name)}</b>, applied as <code>brand/icons/sim2real.svg</code> and <code>sim2real-app.svg</code> until you pick.
  Top 3 by score: 01 {html.escape(MARKS[0].name)} ({score(MARKS[0].slug)}), 02 {html.escape(MARKS[1].name)} ({score(MARKS[1].slug)}), 03 {html.escape(MARKS[2].name)} ({score(MARKS[2].slug)}).</p>
  <p>Pick one or more below (★), comment on any, then <b>Copy my picks</b> and paste the text into chat. Nothing is wired into Clank yet.</p>
  <div class="crit">Criteria, weight out of 100 (AI judgement, 1-5 each, not measured): {crit}</div>
</section>
<div class="top3">{top3}</div>

<h2>All 20 in a Clank ribbon row</h2>
<p class="sub">Clank's Obsidian-skin ribbon colours; 16 px is the real ribbon size (32 px buttons). Hover a cell for its name.</p>
<div class="allrib">{all_rows("dark")}{all_rows("light")}</div>

<h2>Top 5 beside lucide</h2>
<p class="sub">Each candidate dropped into a mock collapsed Clank ribbon (Folder, Search, Git, Plugins, the candidate, Grid … Settings, Help), then all five in one toolbar between stock lucide icons. The candidate's button has a faint outline.</p>
<div class="strip">{rails}</div>
<div class="strip">{toolbars}</div>

<h2>All 20, with picks and comments</h2>
<p class="sub">The 256 px app icon (switch Ink / Paper tile at the top), the toolbar mark at 16 / 24 / 48 px dark and light, and the 16 px raster at device pixel ratio 1 blown up 4×, which is what a non-retina screen draws.</p>
<div class="grid">{cards}</div>

<h2>Notes</h2>
<div class="notes">
  <div class="note"><h3>Colour</h3>
    <ul>
      <li>Brand: BAM Grid Purist (Oct 24): ink <span class="swatch" style="background:{INK}"></span> <code>{INK}</code>, paper <span class="swatch" style="background:{PAPER}"></span> <code>{PAPER}</code>, one green <span class="swatch" style="background:{BAM_GREEN}"></span> <code>{BAM_GREEN}</code>.</li>
      <li>On the ink tile BAM Green is only 3.2:1, too faint for a dashed line, so the twin is drawn in <span class="swatch" style="background:{BAM_GREEN_LIT}"></span> <code>{BAM_GREEN_LIT}</code>: the same hue (OKLCH 159) lifted to L 0.80, 11:1 on ink. The brief said "neon green"; this is the brand green made bright, not the old site lime <code>#C4FF4D</code>.</li>
      <li>The Paper tile switch shows the other reading: paper tile, ink real, brand green twin, as robotparts' app icon does.</li>
    </ul></div>
  <div class="note"><h3>How the marks are built</h3>
    <ul>
      <li>One source, <code>brand/icons/marks.py</code>: each stroke has a role (real, sim, aux) and the 24 px and 256 px files are both generated from it by <code>build.py</code>.</li>
      <li>Dashes are explicit short paths whose ends sit on the path's own corners (lucide's <code>square-dashed</code> convention), not a <code>stroke-dasharray</code> that can drop a corner.</li>
      <li>Every mark was rasterised at 16 / 24 / 48 px at 1× by <code>render_check.py</code> and looked at zoomed; five were redrawn after that (Ghost Horn read as lucide share-2, Cast Shadow as user and then search, a mirrored arm as a planet, Twin Tiles touched, Floor Bars was a stock chart).</li>
    </ul></div>
  <div class="note"><h3>Wiring it into Clank (not done)</h3>
    <p><code>brand/icons/sim2real.iconnode.json</code> is the default in lucide's iconNode shape, so a plugin can do:</p>
    <pre>const Sim2Real = createLucideIcon('sim2real', iconNode)
ctx.registerRibbonItem({{ id: 'sim2real', icon: Sim2Real, tooltip: 'sim2real', side: 'top', command: '…' }})</pre>
    <p>Clank itself was only read, never edited.</p></div>
  <div class="note"><h3>Files</h3>
    <ul>
      <li><code>brand/icons/proposals/NN-&lt;slug&gt;.svg</code> and <code>NN-&lt;slug&gt;-app.svg</code> for all 20</li>
      <li><code>brand/icons/sim2real.svg</code>, <code>sim2real-app.svg</code>: 01, the default</li>
      <li><code>brand/icons/README.md</code>: the 20 with one line each</li>
      <li>Rebuild: <code>uv run --no-project --with svgpathtools python /home/bam/sim2real/brand/icons/build.py</code></li>
    </ul></div>
</div>
</main>
<div class="dock" role="region" aria-label="Your picks">
  <div class="dock-in">
    <span class="status" id="status" aria-live="polite"></span>
    <button type="button" class="btn ghost" id="clear">Clear</button>
    <button type="button" class="btn" id="copy">Copy my picks</button>
    <textarea id="copyout" rows="5" readonly aria-label="Your picks as text"></textarea>
  </div>
</div>
<script>const NAMES={names};const ICONS={icons};{JS}</script>
</body>
</html>
"""


def main() -> None:
    write_files()
    write_readme()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    page = build_report()
    REPORT.write_text(page)
    print(f"{len(MARKS)} marks · default 01 {MARKS[0].name} · report {REPORT} ({len(page.encode()) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
