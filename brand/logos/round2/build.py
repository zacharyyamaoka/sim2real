"""Build the round-2 sim2real logos (20 gear logos + 20 s2r type logos), lockups, README and pick page.

    uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round2/render_check.py --out /tmp/s2r-logos --previews
    python3 /home/bam/sim2real/brand/logos/round2/build.py

Run render_check first: it writes the 32 px PNG previews this page embeds. Writes, numbered best first,
the gear set into brand/logos/round2/ and the s2r type set into brand/logos/round2/s2r/:
- NN-<slug>.svg / NN-<slug>-dark.svg                 the 512 px logo for light / dark grounds
- NN-<slug>-lockup.svg / NN-<slug>-lockup-dark.svg   logo + 'sim2real' wordmark
- brand/logos/round2/README.md (both sets)
- reports/sim2real-logos-r2-2026-10-28.html
Round 1 (brand/icons/) is only read: its 09 is shown as Zach's reference.
"""

from __future__ import annotations

import base64
import html
import json
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Callable

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

from geom import BAM_GREEN, DARK, GREEN_LIT, INK, LIGHT, PAPER  # noqa: E402
from logos import Logo, svg  # noqa: E402
from scores import CRITERIA, S2R_HIS, S2R_SCORES, SCORES, ordered, s2r_ordered, s2r_score, score  # noqa: E402
from wordmark import wordmark  # noqa: E402

DATE = "2026-10-28"
REPORT = REPO / "reports" / f"sim2real-logos-r2-{DATE}.html"
R1_09 = REPO / "brand" / "icons" / "proposals" / "09-wipe-split.svg"
R1_09_APP = REPO / "brand" / "icons" / "proposals" / "09-wipe-split-app.svg"
XH = 160  # wordmark x-height in the lockup, on the logo's 512 px artboard

TOP3_WHY = {
    "split-gear": "His 'pixelated digital thing vs the analog real thing' in one object: the left half in hard pixel "
    "steps, the right half machined. It reads at 32 px and has the shortest path to a 24 px icon (a gear with one half "
    "stepped). Its gap: no screen.",
    "screen-hub": "A real gear whose hub is a screen showing the same gear in pixels: screen and reality in one silhouette. "
    "At 32 px it is still a gear with a dark square and a green dot.",
    "half-screen": "His 09 idea taken literally: half a computer screen, half reality, the gear on the cut. "
    "Take this one if the screen has to be in the logo.",
    "two-boundary": "His 'half a computer screen, half in reality' done with the letters: the 2's diagonal is the edge "
    "of the screen, a pixel s inside it and a steel r outside it. The 2 itself is the boundary.",
    "res-ramp": "The plainest version of 'fades from pixel to real': a coarse pixel s, a finer pixel 2, a set r. "
    "Pixel letters are BAM's own block type, so it fits the family.",
    "s2r-tiles": "The BAM lockup's own form (the B-A-M tiles) applied to s-2-r: a screen tile, an ink tile, a steel tile. "
    "The easiest of the type marks to turn into a 24 px icon.",
}


@dataclass
class Section:
    key: str  # "G" or "S": prefixes every number on the page and in "Copy my picks"
    title: str
    logos: list
    folder: pathlib.Path
    score: Callable[[str], int]
    scores: dict
    his: str  # what the first criterion means for this set


SECTIONS = [
    Section("G", "Gear logos", ordered(), HERE, score, SCORES, CRITERIA[0][3]),
    Section("S", "s2r type logos", s2r_ordered(), HERE / "s2r", s2r_score, S2R_SCORES, S2R_HIS),
]


def n2(i: int) -> str:
    return f"{i:02d}"


BBOXES = json.loads((HERE / "bboxes.json").read_text()) if (HERE / "bboxes.json").exists() else {}


def lockup(lg: Logo, P: dict, uid: str, inner: str | None = None, wm_ref: str | None = None) -> tuple[str, int]:
    """Logo + the 'sim2real' wordmark on a 512-tall canvas. The mark is cropped to its own ink box
    (bboxes.json, measured by render_check) so it sits tight against the word; max 400 tall, 560 wide.
    With wm_ref the wordmark is a <use> of a shared symbol (the page)."""
    wm, w, asc, _ = wordmark(P, XH)
    box = next((b[lg.slug] for b in BBOXES.values() if lg.slug in b), [0, 0, 512, 512])
    pad = 10
    bx, by, bw, bh = box[0] - pad, box[1] - pad, box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
    k = min(400 / bh, 560 / bw)
    mw, mh = bw * k, bh * k
    content = inner if inner is not None else lg.draw(P, uid)
    mark = (f'<svg x="24" y="{256 - mh / 2:.1f}" width="{mw:.1f}" height="{mh:.1f}" viewBox="{bx} {by} {bw} {bh}" overflow="hidden">'
            f'{content}</svg>')
    x0 = 24 + mw + 44
    width = int(x0 + w + 40)
    base = 256 + XH / 2
    words = f'<use href="#{wm_ref}"/>' if wm_ref else wm
    body = f'{mark}<g transform="translate({x0:.1f} {base:.1f})">{words}</g>'
    return body, width


def write_files(logos: list[Logo], folder: pathlib.Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("[0-9][0-9]-*.svg"):
        old.unlink()  # the numbering follows the scores, so stale numbers must not linger
    for i, lg in enumerate(logos, 1):
        for P, suffix in ((LIGHT, ""), (DARK, "-dark")):
            (folder / f"{n2(i)}-{lg.slug}{suffix}.svg").write_text(svg(lg, P, title=f"sim2real - {lg.name}") + "\n")
            body, width = lockup(lg, P, f"{lg.slug}-{P['name']}")
            (folder / f"{n2(i)}-{lg.slug}-lockup{suffix}.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 512" width="{width // 2}" height="256">'
                f"<title>sim2real - {lg.name}</title>{body}</svg>\n"
            )


def write_readme() -> None:
    def cell(t: str) -> str:
        return t.replace("|", "\\|")

    def table(sec: Section) -> str:
        return "\n".join(
            f"| {sec.key}{n2(i)} | **{cell(lg.name)}** | {cell(lg.idea)} | {sec.score(lg.slug)} | "
            + ", ".join(x for x in ("develops 09" if lg.develops_09 else "", "his words" if lg.faithful else "",
                                     f"palette break: {lg.palette_break}" if lg.palette_break else "") if x)
            + f" | {cell(lg.why)} |"
            for i, lg in enumerate(sec.logos, 1)
        )

    head = "| # | name | idea | score | notes | why |\n|---|---|---|---|---|---|"
    crit = ", ".join(f"{label} {w}" for _, label, w, _ in CRITERIA)
    (HERE / "README.md").write_text(f"""# sim2real logos, round 2

Zach, {DATE}: "I don't love any of the logos. For me sim to real is like a picture of a gear on a computer screen vs on
in real life side by side. Or like a pixelated digital thing vs the analog real thing. Maybe some like 09 is promising
if maybe its like half a computer screen half in reality. and perhaps there is like a gear or something inside the
middle of the screen or something. Make 20 more logo proposals. Lets do a logo first, that we simplify later to show
as the icon." Then: "On the logo please also make 20 variants that use the s2r text. maybe it like fades from like
pixel to real, maybe in one its like in a computer screen, etc."

- **Logo first, icon later.** Nothing here is simplified yet. The toolbar icon `brand/icons/sim2real.svg` (round 1, 01
  Twin Tiles) stays Clank's default until a logo is picked and simplified.
- **Pick page:** `/home/bam/sim2real/reports/sim2real-logos-r2-{DATE}.html`: two sections, gear (G01-G20) and s2r type
  (S01-S20), every logo large on light and dark with its lockup and 32 px preview, ★ pick, a comment, "Copy my picks".
- **One idea, two renderings.** Digital = square pixels shaded like pixel art, green on a dark screen; real = machined
  grey metal (rim, lathe rings, bore, soft shadow) or set ink type. The gear set uses one 10-tooth gear throughout; the
  s2r set uses Ubuntu Sans 800, its pixel letters rasterised from the same outlines.
- **Palette:** BAM Grid Purist, ink `{INK}`, paper `{PAPER}`, BAM Green `{BAM_GREEN}` (and `{GREEN_LIT}`, the same
  hue lit, on dark grounds), steel greys. Marked palette breaks: G Circuit Cast and S Circuit s (bronze), S Subpixel (RGB).
- **Files per logo** (gear set in this folder, s2r set in `s2r/`): `NN-<slug>.svg` (light ground), `NN-<slug>-dark.svg`,
  `NN-<slug>-lockup.svg`, `NN-<slug>-lockup-dark.svg`, `preview32/NN-<slug>-32.png` and `-32-dark.png`.
- **Wordmark** (every lockup): 'sim' in square pixels (Grid Purist's block letters), '2real' in Ubuntu Sans Bold.

Scores are AI judgement, 1-5 per criterion, weighted ({crit}); not measured. They set the numbering.

## Gear logos (G)

{head}
{table(SECTIONS[0])}

## s2r type logos (S)

{head}
{table(SECTIONS[1])}

## Rebuild

```bash
uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round2/render_check.py --out /tmp/s2r-logos --previews
```

```bash
python3 /home/bam/sim2real/brand/logos/round2/build.py
```

The first renders every logo at 240 px and 32 px headlessly into `--out` (to look at) and writes the 32 px previews;
the second writes the SVGs, lockups, this README and the pick page. Source: `geom.py` (gear, pixels, metal, screens),
`logos.py` (the gear 20), `s2r_type.py` + `s2r_logos.py` (the type 20), `scores.py`, `wordmark.py`.
""")


# ---------------------------------------------------------------------------------------------
# The pick page
# ---------------------------------------------------------------------------------------------


def png_uri(path: pathlib.Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def use(ref: str, w: int, h: int | None = None, cls: str = "", vb: str = "0 0 512 512") -> str:
    h = h or w
    c = f' class="{cls}"' if cls else ""
    return f'<svg{c} viewBox="{vb}" width="{w}" height="{h}" role="img"><use href="#{ref}"/></svg>'


def chips(slug: str, scores: dict) -> str:
    out = []
    for key, label, weight, _ in CRITERIA:
        v = scores[slug][key]
        out.append(
            f'<span class="chip" title="{html.escape(label)} (weight {weight}): {v} of 5"><span class="cl">{html.escape(label)}</span>'
            f'<span class="dots">' + "".join(f'<i class="{"on" if k < v else ""}"></i>' for k in range(5)) + "</span></span>"
        )
    return '<div class="chips">' + "".join(out) + "</div>"


def badges(lg: Logo) -> str:
    b = []
    if lg.develops_09:
        b.append('<span class="badge">develops 09</span>')
    if lg.faithful:
        b.append('<span class="badge">his words, literally</span>')
    if lg.palette_break:
        b.append(f'<span class="badge warn">palette break: {html.escape(lg.palette_break)}</span>')
    return "".join(b)


def card(sec: Section, i: int, lg: Logo, lock_ws: dict, previews: dict) -> str:
    n = sec.key + n2(i)
    lock_w = lock_ws[n]
    pv = previews[(sec.key, lg.slug)]
    return f"""
<article class="card" id="m{n}">
  <header class="card-h"><span class="no">{n}</span>
    <div class="nm"><h3>{html.escape(lg.name)}</h3><span class="meta">{html.escape(lg.idea)}</span></div>
    <span class="score" title="weighted score out of 100">{sec.score(lg.slug)}</span></header>
  <div class="badges">{badges(lg)}</div>
  <div class="pair"><div class="panel light">{use(f"L{n}l", 260, cls="big")}</div><div class="panel dark">{use(f"L{n}d", 260, cls="big")}</div></div>
  <div class="lock"><div class="panel light">{use(f"K{n}l", lock_w // 5, 512 // 5, vb=f"0 0 {lock_w} 512")}</div>
    <div class="panel dark">{use(f"K{n}d", lock_w // 5, 512 // 5, vb=f"0 0 {lock_w} 512")}</div></div>
  <div class="tiny">
    <span class="panel light t32"><img src="{pv["light"]}" width="32" height="32" alt="{html.escape(lg.name)} at 32 px, light"></span>
    <span class="panel dark t32"><img src="{pv["dark"]}" width="32" height="32" alt="{html.escape(lg.name)} at 32 px, dark"></span>
    <span class="panel light z"><img class="px" src="{pv["light"]}" width="96" height="96" alt=""></span>
    <span class="panel dark z"><img class="px" src="{pv["dark"]}" width="96" height="96" alt=""></span>
    <span class="tl">32 px, then the same pixels 3×</span></div>
  <p class="why">{html.escape(lg.why)}</p>
  {chips(lg.slug, sec.scores)}
  <div class="pick-row"><button type="button" class="pick" data-pick="{n}" aria-pressed="false"><span class="star" aria-hidden="true">☆</span> Pick</button>
    <textarea class="cmt" data-comment="{n}" rows="2" placeholder="Comment on {n} (saved in this browser)"></textarea></div>
</article>"""


CSS = """
:root{--bg:#FBFBF8;--surface:#FFFFFF;--ink:#0E100E;--muted:#5D625C;--line:#DFE1DB;--green:#2F6F4F;--green-ink:#FBFBF8;--soft:#F1F3EE;
--panel-l:#FBFBF8;--panel-d:#121412;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0E100E;--surface:#161916;--ink:#ECEDE8;--muted:#9AA09A;--line:#2A2E2A;--green:#35DE95;--green-ink:#0E100E;--soft:#1C201C}}
:root[data-theme="dark"]{--bg:#0E100E;--surface:#161916;--ink:#ECEDE8;--muted:#9AA09A;--line:#2A2E2A;--green:#35DE95;--green-ink:#0E100E;--soft:#1C201C}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1280px;margin:0 auto;padding:28px 16px 130px}
h1{font-size:26px;line-height:1.2;margin:0 0 4px;letter-spacing:-.01em}h2{font-size:19px;margin:44px 0 6px}h3{font-size:16px;margin:0}
p{margin:6px 0}.sub{color:var(--muted);margin:0 0 16px}
code{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.9em;background:var(--soft);padding:1px 5px;border-radius:4px}
blockquote{margin:10px 0;padding:8px 12px;border-left:3px solid var(--line);color:var(--muted);font-size:14px}
.topbar{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start;justify-content:space-between}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{background:transparent;color:var(--ink);border:0;padding:6px 10px;font:inherit;font-size:13px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.verdict{border:1px solid var(--line);border-left:4px solid var(--green);background:var(--surface);border-radius:10px;padding:14px 16px;margin-top:14px}
.verdict .lead{font-size:17px;margin:0 0 4px}
.crit{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--muted);font-size:13px;margin-top:10px}.crit b{color:var(--ink);font-weight:600}
.top3{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;margin-top:14px}
.t3{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px}
.t3 .rank{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.panel{display:inline-flex;align-items:center;justify-content:center;border-radius:10px;border:1px solid var(--line)}
.panel.light{background:var(--panel-l)}.panel.dark{background:var(--panel-d);border-color:#2A2E2A}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pair .panel{padding:8px}
.pair svg.big{width:100%;height:auto;max-width:260px;display:block}
.lock{display:grid;grid-template-columns:1fr 1fr;gap:8px}.lock.one{grid-template-columns:1fr}.lock.one svg{max-width:420px}.lock .panel{padding:8px 10px}.lock svg{width:100%;height:auto;display:block}
.tiny{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.tiny .tl{flex-basis:100%}.tl{font-size:11.5px;color:var(--muted)}
.t32{width:48px;height:48px}.z{padding:4px}img.px{image-rendering:pixelated;display:block}
.ref{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:12px}
.refc{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px;display:flex;flex-direction:column;gap:6px;align-items:center;text-align:center}
.refc .panel{width:100%;padding:8px}.refc svg{width:100%;height:auto;max-width:200px}
.refc.r1 .panel.light{color:#0E100E}.refc .cap{font-size:13px}.refc .cap b{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));gap:16px;margin-top:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:9px}
.card.picked{border-color:var(--green);box-shadow:0 0 0 1px var(--green)}
.card-h{display:flex;align-items:center;gap:10px}.card-h .no{font:600 20px/1 ui-monospace,Menlo,monospace;color:var(--muted)}
.card-h .nm{flex:1;min-width:0}.card-h .meta{font-size:12.5px;color:var(--muted)}
.score{font:600 13px/1 ui-monospace,Menlo,monospace;border:1px solid var(--line);border-radius:999px;padding:4px 8px}
.badges{display:flex;flex-wrap:wrap;gap:6px}.badges:empty{display:none}
.badge{font-size:11.5px;border:1px solid var(--green);color:var(--green);border-radius:999px;padding:1px 8px}
.badge.warn{border-color:#B07A43;color:#B07A43}
.why{font-size:14px}
.chips{display:flex;flex-wrap:wrap;gap:4px 10px}.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--muted)}
.dots{display:inline-flex;gap:2px}.dots i{width:6px;height:6px;border-radius:1px;background:var(--line);display:block}.dots i.on{background:var(--green)}
.pick-row{display:flex;gap:8px;align-items:stretch}
.pick{flex:none;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:8px;padding:6px 12px;font:inherit;font-size:14px;cursor:pointer}
.pick[aria-pressed="true"]{background:var(--green);color:var(--green-ink);border-color:var(--green)}
.cmt{flex:1;min-width:0;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit;font-size:13px;padding:6px 8px;resize:vertical}
.dock{position:fixed;left:0;right:0;bottom:0;background:var(--surface);border-top:1px solid var(--line);z-index:5}
.dock-in{max-width:1280px;margin:0 auto;padding:10px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dock .status{flex:1;min-width:0;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{border:1px solid var(--ink);background:var(--ink);color:var(--bg);border-radius:8px;padding:8px 14px;font:inherit;font-size:14px;cursor:pointer}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
#copyout{width:100%;font:12px/1.4 ui-monospace,Menlo,monospace;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);padding:8px;display:none}
.notes{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:10px}
.note{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;font-size:14px}.note ul{margin:6px 0;padding-left:18px}
.swatch{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;border:1px solid var(--line)}
a{color:inherit}
@media (max-width:520px){h1{font-size:22px}.grid{grid-template-columns:1fr}.top3{grid-template-columns:1fr}}
"""

JS = r"""
(function(){
const KEY='sim2real-logos-r2-2026-10-28';
let state={picks:{},comments:{},theme:''};
try{const raw=localStorage.getItem(KEY);if(raw){const s=JSON.parse(raw);if(s&&typeof s==='object')state=Object.assign(state,s);}}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(e){}}
const root=document.documentElement;
function applyTheme(){if(state.theme)root.setAttribute('data-theme',state.theme);else root.removeAttribute('data-theme');
  document.querySelectorAll('[data-theme-btn]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeBtn===(state.theme||'auto'))));}
document.querySelectorAll('[data-theme-btn]').forEach(b=>b.addEventListener('click',()=>{const t=b.dataset.themeBtn;state.theme=t==='auto'?'':t;applyTheme();save();}));
function picked(){return Object.keys(state.picks).filter(n=>state.picks[n]).sort();}
function commented(){return Object.keys(state.comments).filter(n=>(state.comments[n]||'').trim());}
function render(){
  document.querySelectorAll('[data-pick]').forEach(b=>{const n=b.dataset.pick,on=!!state.picks[n];
    b.setAttribute('aria-pressed',String(on));b.querySelector('.star').textContent=on?'★':'☆';
    const c=document.getElementById('m'+n);if(c)c.classList.toggle('picked',on);});
  const p=picked(),cm=commented().length;
  document.getElementById('status').textContent=p.length?('Picked: '+p.map(n=>n+' '+NAMES[n]).join(', ')+(cm?' · '+cm+' comment'+(cm>1?'s':''):''))
    :(cm?cm+' comment'+(cm>1?'s':'')+', nothing picked yet':'Nothing picked yet.');
}
document.querySelectorAll('[data-pick]').forEach(b=>b.addEventListener('click',()=>{const n=b.dataset.pick;if(state.picks[n])delete state.picks[n];else state.picks[n]=true;render();save();}));
document.querySelectorAll('[data-comment]').forEach(t=>{const n=t.dataset.comment;t.value=state.comments[n]||'';
  t.addEventListener('input',()=>{if(t.value.trim())state.comments[n]=t.value;else delete state.comments[n];render();save();});});
function text(){
  const p=picked(),nums=Array.from(new Set(p.concat(commented()))).sort();
  const lines=['sim2real logo picks, round 2 (reports/sim2real-logos-r2-2026-10-28.html; G = gear, S = s2r type)'];
  lines.push('Picked: '+(p.length?p.map(n=>n+' '+NAMES[n]).join(', '):'none'));
  nums.forEach(n=>{const c=(state.comments[n]||'').trim();lines.push('- '+n+' '+NAMES[n]+(state.picks[n]?' [picked]':'')+(c?': '+c.replace(/\s+/g,' '):''));});
  return lines.join('\n');
}
const out=document.getElementById('copyout');
document.getElementById('copy').addEventListener('click',async()=>{
  const t=text();out.value=t;out.style.display='block';let ok=false;
  try{if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(t);ok=true;}}catch(e){}
  if(!ok){try{out.focus();out.select();ok=document.execCommand('copy');}catch(e){}}
  const b=document.getElementById('copy');b.textContent=ok?'Copied':'Select and copy below';setTimeout(()=>{b.textContent='Copy my picks';},1800);
});
document.getElementById('clear').addEventListener('click',()=>{if(!confirm('Clear every pick and comment in this browser?'))return;
  state.picks={};state.comments={};document.querySelectorAll('[data-comment]').forEach(t=>t.value='');render();save();});
applyTheme();render();
})();
"""


def build_report() -> str:
    symbols = []
    lock_ws = {}
    for P, t in ((LIGHT, "l"), (DARK, "d")):
        wm, _, _, _ = wordmark(P, XH)
        symbols.append(f'<g id="WM{t}">{wm}</g>')  # one wordmark per palette, reused by all 80 lockups
    previews = {}
    for sec in SECTIONS:
        for i, lg in enumerate(sec.logos, 1):
            n = sec.key + n2(i)
            for P, t in ((LIGHT, "l"), (DARK, "d")):
                uid = f"{n}{t}"
                symbols.append(f'<symbol id="L{uid}" viewBox="0 0 512 512">{lg.draw(P, uid)}</symbol>')
                body, lock_ws[n] = lockup(lg, P, uid, inner=f'<use href="#L{uid}" width="512" height="512"/>', wm_ref=f"WM{t}")
                symbols.append(f'<symbol id="K{uid}" viewBox="0 0 {lock_ws[n]} 512">{body}</symbol>')
            pv = sec.folder / "preview32"
            previews[(sec.key, lg.slug)] = {"light": png_uri(pv / f"{n2(i)}-{lg.slug}-32.png"),
                                            "dark": png_uri(pv / f"{n2(i)}-{lg.slug}-32-dark.png")}
    sprite = '<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>' + "".join(symbols) + "</defs></svg>"

    def top3(sec: Section) -> str:
        out = ""
        for i, lg in enumerate(sec.logos[:3], 1):
            n = sec.key + n2(i)
            out += f"""
<div class="t3"><div class="rank">{html.escape(sec.title)} #{i} · score {sec.score(lg.slug)}</div><h3><a href="#m{n}">{n} {html.escape(lg.name)}</a></h3>
  <div class="pair"><div class="panel light">{use(f"L{n}l", 220, cls="big")}</div><div class="panel dark">{use(f"L{n}d", 220, cls="big")}</div></div>
  <div class="lock one"><div class="panel light">{use(f"K{n}l", lock_ws[n] // 5, 512 // 5, vb=f"0 0 {lock_ws[n]} 512")}</div></div>
  <p>{html.escape(TOP3_WHY[lg.slug])}</p></div>"""
        return out

    r1 = R1_09.read_text()
    r1 = re.sub(r'width="24" height="24"', 'width="200" height="200"', r1, count=1)
    r1_app = re.sub(r"<title>.*?</title>", "", R1_09_APP.read_text())
    r1_app = re.sub(r'width="256" height="256"', 'width="200" height="200"', r1_app, count=1)
    refs = (f'<div class="refc r1"><div class="panel light">{r1}</div><div class="panel light">{r1_app}</div>'
            f'<div class="cap"><b>Round 1 · 09 Wipe Split</b>his reference: a solid half and a dashed half</div></div>')
    for sec in SECTIONS:
        for i, lg in enumerate(sec.logos, 1):
            if lg.develops_09:
                n = sec.key + n2(i)
                refs += (f'<div class="refc"><div class="panel light">{use(f"L{n}l", 200)}</div><div class="panel dark">{use(f"L{n}d", 200)}</div>'
                         f'<div class="cap"><b><a href="#m{n}">{n} {html.escape(lg.name)}</a></b>{html.escape(lg.idea)}</div></div>')

    crit = "".join(f'<span title="{html.escape(d)}"><b>{html.escape(label)}</b> {w}</span>' for _, label, w, d in CRITERIA)
    sections = ""
    for sec in SECTIONS:
        cards = "".join(card(sec, i, lg, lock_ws, previews) for i, lg in enumerate(sec.logos, 1))
        sections += (f'<h2 id="sec-{sec.key}">{html.escape(sec.title)}: all 20, large on light and dark, with lockup and 32 px preview</h2>'
                     f'<p class="sub">{sec.key}01-{sec.key}20, numbered by score. "His picture" here means: {html.escape(sec.his)} '
                     f'The 32 px previews are real 32 × 32 rasters, then the same pixels 3× larger.</p><div class="grid">{cards}</div>')
    names = json.dumps({sec.key + n2(i): lg.name for sec in SECTIONS for i, lg in enumerate(sec.logos, 1)}, ensure_ascii=False)
    g1, s1 = SECTIONS[0].logos, SECTIONS[1].logos
    fav = svg(g1[0], LIGHT, uid="fav", size=64).replace("#", "%23")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sim2real logos, round 2</title>
<link rel="icon" href="data:image/svg+xml,{html.escape(fav)}">
<style>{CSS}</style>
</head>
<body>
{sprite}
<main>
<div class="topbar"><div><h1>sim2real logo · round 2 · 40 proposals</h1>
<p class="sub">{DATE} · 20 gear logos (G) and 20 s2r type logos (S) · digital vs real · a logo first; the icon gets simplified from the pick later</p></div>
<div class="seg" role="group" aria-label="Page theme"><button type="button" data-theme-btn="auto">Auto</button><button type="button" data-theme-btn="light">Light</button><button type="button" data-theme-btn="dark">Dark</button></div></div>

<section class="verdict" aria-label="Verdict">
  <p class="lead"><b>Gear: recommend G01 {html.escape(g1[0].name)}</b>, then G02 {html.escape(g1[1].name)} and G03 {html.escape(g1[2].name)} (take G03 if the screen has to be in the logo).
  <b>Type: recommend S01 {html.escape(s1[0].name)}</b>, then S02 {html.escape(s1[1].name)} and S03 {html.escape(s1[2].name)}.</p>
  <p>Digital is hard square pixels on a dark screen; real is a machined metal part or set ink type. Pick any number in either section (★), comment, then <b>Copy my picks</b> and paste the text into chat. Round 1's toolbar icon stays Clank's default until a logo is picked and simplified.</p>
  <blockquote>"For me sim to real is like a picture of a gear on a computer screen vs on in real life side by side. Or like a pixelated digital thing vs the analog real thing." · "maybe it like fades from like pixel to real, maybe in one its like in a computer screen" Zach, {DATE}</blockquote>
  <div class="crit">Criteria, weight out of 100 (AI judgement, 1-5 each, not measured): {crit}</div>
  <p class="sub" style="margin-top:8px"><a href="#sec-G">Gear logos ↓</a> · <a href="#sec-S">s2r type logos ↓</a></p>
</section>
<h2>Top 3 per section</h2>
<div class="top3">{top3(SECTIONS[0])}</div>
<div class="top3">{top3(SECTIONS[1])}</div>

<h2>His reference: round-1 09, and the logos that develop it</h2>
<p class="sub">"Maybe some like 09 is promising if maybe its like half a computer screen half in reality, and perhaps there is like a gear … inside the middle of the screen." Four gear logos and three type logos take that idea further.</p>
<div class="ref">{refs}</div>

{sections}

<h2>Notes</h2>
<div class="notes">
  <div class="note"><h3>How they are built</h3><ul>
    <li>One gear, ten teeth, in every logo. <b>Digital</b> = the gear rasterised onto its own square grid, shaded like pixel art (a lit top-left edge, a dark bottom-right edge). <b>Real</b> = the same outline as a machined part: a steel gradient, a rim, a recessed web with lathe rings, a hub and a bore.</li>
    <li>Source in <code>brand/logos/round2/</code>: <code>geom.py</code> (gear, pixels, metal, screens), <code>logos.py</code> (the 20), <code>scores.py</code>, <code>wordmark.py</code>. Each logo is drawn twice, for light and for dark grounds.</li>
    <li>The s2r set uses Ubuntu Sans 800; its pixel letters are those same outlines rasterised onto a square grid, so the pixel s and the set s are one letter at two resolutions.</li>
    <li>Every logo was rendered headlessly at 240 px and 32 px, on light and dark, and looked at. Redrawn after looking: gear Pixel Shadow (a floor shadow read as a slab), Loupe (the lens showed a green blob, not teeth), Sim Floor (a light floor vanished at 32 px); type Stencil r (its shadow showed through the cut), Screen Escape (crowded), Mirror Line (the reflection was too heavy).</li></ul></div>
  <div class="note"><h3>Palette</h3><ul>
    <li>BAM Grid Purist: ink <span class="swatch" style="background:{INK}"></span> <code>{INK}</code>, paper <span class="swatch" style="background:{PAPER}"></span> <code>{PAPER}</code>, BAM Green <span class="swatch" style="background:{BAM_GREEN}"></span> <code>{BAM_GREEN}</code>, lit on dark as <span class="swatch" style="background:{GREEN_LIT}"></span> <code>{GREEN_LIT}</code>; steel greys for the real gear.</li>
    <li>Palette breaks on purpose, marked on their cards: G Circuit Cast and S Circuit s (bronze casting, PCB pads), S Subpixel (real RGB stripes). G Sim Floor keeps its floor dark on both grounds, as a sim viewport does.</li></ul></div>
  <div class="note"><h3>Wordmark and files</h3><ul>
    <li>'sim' in square pixels (BAM's block letters), '2real' in Ubuntu Sans Bold: the word itself goes from digital to real. The same wordmark is used in all 20 lockups.</li>
    <li>Per logo, gear set in <code>brand/logos/round2/</code> and type set in <code>brand/logos/round2/s2r/</code>: <code>NN-slug.svg</code>, <code>-dark.svg</code>, <code>-lockup.svg</code>, <code>-lockup-dark.svg</code>, <code>preview32/NN-slug-32.png</code>.</li>
    <li>For the type logos the lockup repeats the word (s2r + sim2real), as a monogram beside its full name does; use the bare mark where that is too much.</li></ul></div>
</div>
</main>
<div class="dock" role="region" aria-label="Your picks"><div class="dock-in">
  <span class="status" id="status" aria-live="polite"></span>
  <button type="button" class="btn ghost" id="clear">Clear</button><button type="button" class="btn" id="copy">Copy my picks</button>
  <textarea id="copyout" rows="5" readonly aria-label="Your picks as text"></textarea></div></div>
<script>const NAMES={names};{JS}</script>
</body>
</html>
"""


def main() -> None:
    missing = [f"{sec.key}{n2(i)} {lg.slug}" for sec in SECTIONS for i, lg in enumerate(sec.logos, 1)
               if not (sec.folder / "preview32" / f"{n2(i)}-{lg.slug}-32.png").exists()]
    if missing:
        sys.exit(f"run render_check.py --previews first; missing 32 px previews for {missing}")
    for sec in SECTIONS:
        write_files(sec.logos, sec.folder)
    write_readme()
    page = build_report()
    REPORT.write_text(page)
    kb = len(page.encode()) / 1024
    print(f"G01 {SECTIONS[0].logos[0].name} · S01 {SECTIONS[1].logos[0].name} · {REPORT} ({kb:.0f} KB{', OVER 2 MB' if kb > 2048 else ''})")


if __name__ == "__main__":
    main()
