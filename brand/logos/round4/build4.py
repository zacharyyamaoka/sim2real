"""Build round 4: ten variants of R3-04 Assemble, files, lockups, README, and the pick page in context.

    uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round4/render4.py --out /tmp/s2r-r4 --previews
    python3 /home/bam/sim2real/brand/logos/round4/build4.py

render4 first: it writes bboxes.json and the cropped previews this page reads (00 = R3-04, the reference).
Same in-context mocks as round 3 (website header, tab strip 16 and 32 px, desktop and dock, Clank's
sidebar), light and dark, and the same 'sim2real' wordmark: only the mark changes.
"""

from __future__ import annotations

import base64
import html
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

import marks4  # noqa: E402  (puts round3 and round2 on the path)
from geom import BAM_GREEN, DARK, GREEN_LIT, INK, LIGHT, PAPER  # noqa: E402
from logos import svg  # noqa: E402
from scores4 import CRITERIA, SCORES, ordered, score  # noqa: E402
from wordmark import wordmark  # noqa: E402

DATE = "2026-10-28"
REPORT = REPO / "reports" / f"sim2real-logos-r4-{DATE}.html"
BOXES = json.loads((HERE / "bboxes.json").read_text())
CAD2ROBOT_FAVICON = pathlib.Path("/home/bam/cad2robot-website/public/favicon.svg")  # read only, for the tab strip
XH = 160
RP_MARK = pathlib.Path("/home/bam/robotparts/design/logos-final-2026-10-26/mark.svg")
RP_MARK_DARK = pathlib.Path("/home/bam/robotparts/design/logos-final-2026-10-26/mark-dark.svg")
BAM_ICON = pathlib.Path("/home/bam/clank-workbench/src/shells/shadcn/workspaces/logos/bam-robotics.svg")
LUCIDE = json.loads((REPO / "brand" / "icons" / "lucide_reference.json").read_text())["icons"]
REF = marks4.REFERENCE

TOP3_WHY = {
    "resolution-ramp": "The most literal 'progressively change into the gear': coarse green blocks on the left, finer steel-grey "
    "blocks in the middle, smooth machined teeth on the right. One gear, three resolutions, and it still reads as a gear at 16 px.",
    "stair-cut": "'The cut outs should be more blocked', answered directly: R3-04's ragged edge becomes a clean chevron staircase, "
    "and the cut cells sit in their own rows, sliding back in. The most orderly version of the idea he picked.",
    "density-ramp": "His dither run into the gear: an ordered dither that gets denser toward the gear until it closes up into "
    "steel. Progressive, and the closest relative of the dither sweep he liked in round 2.",
}


def n3(i: int) -> str:
    """0 is R3-04 itself (the reference); 1-10 are the round-4 variants."""
    return "R3-04" if i == 0 else f"R4-{i:02d}"


def is_ref(lg) -> bool:
    return lg.slug == REF.slug


def square_box(box, pad: float = 10) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0) + 2 * pad
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - side / 2, cy - side / 2, side, side


def lockup(lg, P: dict, uid: str, inner: str | None = None, wm_ref: str | None = None) -> tuple[str, int]:
    """Logo cropped to its ink box beside the 'sim2real' wordmark (the round-2 wordmark), on a 512-tall canvas."""
    wm, w, _, _ = wordmark(P, XH)
    x0b, y0b, x1b, y1b = BOXES[lg.slug]
    pad = 10
    bx, by, bw, bh = x0b - pad, y0b - pad, x1b - x0b + 2 * pad, y1b - y0b + 2 * pad
    k = min(400 / bh, 560 / bw)
    mw, mh = bw * k, bh * k
    content = inner if inner is not None else lg.draw(P, uid)
    mark = f'<svg x="24" y="{256 - mh / 2:.1f}" width="{mw:.1f}" height="{mh:.1f}" viewBox="{bx} {by} {bw} {bh}">{content}</svg>'
    x0 = 24 + mw + 44
    width = int(x0 + w + 40)
    words = f'<use href="#{wm_ref}"/>' if wm_ref else wm
    return f'{mark}<g transform="translate({x0:.1f} {256 + XH / 2:.1f})">{words}</g>', width


def write_files(logos) -> None:
    for old in HERE.glob("[0-9][0-9]-*.svg"):
        old.unlink()  # numbering follows the scores; stale numbers must not linger
    for i, lg in enumerate(logos, 0):
        if is_ref(lg):
            continue  # R3-04's own files are in round3/
        for P, suffix in ((LIGHT, ""), (DARK, "-dark")):
            (HERE / f"{i:02d}-{lg.slug}{suffix}.svg").write_text(svg(lg, P, title=f"sim2real - {lg.name}") + "\n")
            body, width = lockup(lg, P, f"{lg.slug}-{P['name']}")
            (HERE / f"{i:02d}-{lg.slug}-lockup{suffix}.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 512" width="{width // 2}" height="256">'
                f"<title>sim2real - {lg.name}</title>{body}</svg>\n")


def write_readme(logos) -> None:
    def cell(t):
        return t.replace("|", "\\|")

    rows = "\n".join(f"| {n3(i)} | **{cell(lg.name)}** | {', '.join(lg.tags)} | {score(lg.slug)} | {cell(lg.why)} |"
                     for i, lg in enumerate(logos, 0) if not is_ref(lg))
    crit = ", ".join(f"{label} {w}" for _, label, w, _ in CRITERIA)
    (HERE / "README.md").write_text(f"""# sim2real logos, round 4: ten variants of Assemble

Zach, {DATE}: "Ok I like assemble the most. can you please make like 10 different variants on it though: I like the
sim2real text that perfect keep that but please kinda change how the assemble looks. I feel like it needs to kinda more
progressively change into the gear as one of the options.. like maybe the cut outs should be more blocked? idk make 10
more variants."

- **Recommendation: {n3(1)} {logos[1].name}.** The reference, R3-04 Assemble, is first on the page; its files stay in
  `../round3/`. The toolbar icon `brand/icons/sim2real.svg` (round 1) stays Clank's default until a logo is picked and
  simplified.
- **The wordmark is untouched:** the same 'sim2real' lockup as R3-04 (pixel 'sim', grey '2', set 'real'). Only the mark changes.
- **Three families:** progressive (size, resolution, density, teeth arriving), blocked cut-outs (square holes, a stepped
  steel silhouette, a clean staircase cut), and composition (from above, radially into the hub, a tight snap-fit).
- **Round 3's simplicity rules hold:** one chunky 8-tooth gear, big blocks, flat steel, thick shapes, and a one-colour
  silhouette at 16, 24 and 32 px, light and dark.
- **Pick page:** `/home/bam/sim2real/reports/sim2real-logos-r4-{DATE}.html`: R3-04 first, the top 3, then all ten, each in
  a website header, a tab strip (16 and 32 px), a desktop and dock, and Clank's sidebar, light and dark.
- **Files:** `NN-<slug>.svg`, `-dark.svg`, `-lockup.svg`, `-lockup-dark.svg`; `preview/NN-<slug>-16.png`, `-32.png`,
  `-mono-{{16,24,32}}.png` (each also `-dark`); `00-assemble-*` previews are R3-04's.

Scores are AI judgement, 1-5 per criterion, weighted ({crit}); not measured.

| # | name | family | score | why |
|---|---|---|---|---|
{rows}

## Rebuild

```bash
uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round4/render4.py --out /tmp/s2r-r4 --previews
```

```bash
python3 /home/bam/sim2real/brand/logos/round4/build4.py
```

Source: `marks4.py` (the ten, on round 3's kit in `../round3/marks3.py`), `scores4.py`, `render4.py`, `build4.py`.
""")


# ---------------------------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------------------------


def png(path: pathlib.Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def strip_svg_root(s: str) -> tuple[str, str]:
    """(viewBox, inner markup) of a standalone SVG file."""
    import re

    vb = re.search(r'viewBox="([^"]+)"', s).group(1)
    inner = re.sub(r"^.*?<svg[^>]*>", "", s, count=1, flags=re.S)
    inner = re.sub(r"</svg>\s*$", "", inner)
    inner = re.sub(r"<title>.*?</title>", "", inner)
    inner = re.sub(r"<style>.*?</style>", "", inner, flags=re.S)
    return vb, inner


def use(ref: str, w: float, h: float | None = None, vb: str = "0 0 512 512", cls: str = "") -> str:
    h = h or w
    c = f' class="{cls}"' if cls else ""
    return f'<svg{c} viewBox="{vb}" width="{w:g}" height="{h:g}" role="img"><use href="#{ref}"/></svg>'


def mark(ref: str, slug: str, px: float) -> str:
    """The logo cropped square to its ink, at px: how a favicon, app tile or sidebar slot draws it."""
    x, y, w, h = square_box(BOXES[slug])
    return f'<svg viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}" width="{px:g}" height="{px:g}"><use href="#{ref}" width="512" height="512"/></svg>'


def lucide(name: str, px: int, colour: str) -> str:
    body = "".join(f"<{t} " + " ".join(f'{k}="{v}"' for k, v in a.items()) + "/>" for t, a in LUCIDE[name])
    return (f'<svg viewBox="0 0 24 24" width="{px}" height="{px}" fill="none" stroke="{colour}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def wordmark_svg(t: str, h: float) -> str:
    P = LIGHT if t == "l" else DARK
    _, w, asc, desc = wordmark(P, XH)
    top = asc + 6
    vb = f"0 {-top:.1f} {w:.1f} {top + 8:.1f}"
    return f'<svg viewBox="{vb}" height="{h:g}" width="{h * w / (top + 8):.1f}"><use href="#WM{t}"/></svg>'


def context(n: str, lg, pv: dict) -> str:
    ref = lambda t: f"L{n}{t}"
    tile = "tile" in lg.tags

    def header(t):
        th = "light" if t == "l" else "dark"
        return (f'<div class="ctx site {th}"><div class="bar"><span class="brand">{mark(ref(t), lg.slug, 30)}{wordmark_svg(t, 17)}</span>'
                f'<nav><span>Twins</span><span>Runs</span><span>Gates</span><span>Docs</span></nav><span class="cta">Open app</span></div>'
                f'<div class="hero"><b>How close is the twin?</b><i></i><i class="s"></i></div></div>')

    def tabs(x2: bool, dark: bool):
        cls = ("tabs x2" if x2 else "tabs") + (" dark" if dark else " light")
        sz = 32 if x2 else 16
        fav = pv[f"{sz}-dark" if dark else f"{sz}"]
        rp = "RPd" if dark else "RPl"
        return (f'<div class="ctx {cls}"><div class="strip">'
                f'<span class="tab on"><img src="{fav}" width="{sz}" height="{sz}" alt="">sim2real · twins</span>'
                f'<span class="tab">{use(rp, sz, vb=RP_VB)}robotparts.dev</span>'
                f'<span class="tab">{use("C2R", sz, vb="0 0 64 64")}cad2robot</span></div>'
                f'<div class="url">sim2real.local/twins</div></div>')

    def app_tile(px, dark: bool):
        t = "d" if dark else "l"
        if tile:
            return f'<span class="app" style="width:{px}px;height:{px}px">{mark(ref(t), lg.slug, px)}</span>'
        cls = "app ink" if dark else "app paper"
        return (f'<span class="{cls}" style="width:{px}px;height:{px}px;border-radius:{px * 0.22:.0f}px">'
                f'{mark(ref(t), lg.slug, px * 0.8)}</span>')

    def dock(dark: bool):
        other = lambda name, bg, fg: (f'<span class="app" style="width:52px;height:52px;border-radius:12px;background:{bg}">{lucide(name, 28, fg)}</span>')
        rp = f'<span class="app" style="width:52px;height:52px;border-radius:12px;background:#FBFBF8;box-shadow:inset 0 0 0 1px #DFE1DB">{use("RPl", 42, vb=RP_VB)}</span>'
        return (f'<div class="ctx desk {"dark" if dark else "light"}"><div class="desktop-icon">{app_tile(96, dark)}<span>sim2real</span></div>'
                f'<div class="dock">{other("folder", "#3A6EA5", "#FFFFFF")}{other("terminal", "#2A2F2A", "#E6E8E2")}{rp}'
                f'<span class="run">{app_tile(52, dark)}<i></i></span></div></div>')

    def clank(t):
        th = "light" if t == "l" else "dark"
        rp = use("RPl" if t == "l" else "RPd", 20, vb=RP_VB)
        bam = use("BAM", 20, vb="0 0 32 32")
        me = mark(ref(t), lg.slug, 22)
        rail = f'<div class="rail obs"><span>{rp}</span><span class="on">{me}</span><span>{bam}</span></div>'
        fig = (f'<div class="rail fig"><span>{rp}<em>Robot<br>Parts</em></span><span class="on">{me}<em>sim2real</em></span>'
               f'<span>{bam}<em>BAM<br>Robotics</em></span></div>')
        shop = (f'<div class="rail shop"><span>{rp}<em>Robot Parts</em></span><span class="on">{me}<em>sim2real</em></span>'
                f'<span>{bam}<em>BAM Robotics</em></span></div>')
        return f'<div class="ctx clank {th}">{rail}{fig}{shop}</div>'

    return (f'<div class="context"><div class="cg"><span class="cl">Website header</span>{header("l")}{header("d")}</div>'
            f'<div class="cg"><span class="cl">Browser tab: 16 px, light and dark</span>{tabs(False, False)}{tabs(False, True)}</div>'
            f'<div class="cg"><span class="cl">Browser tab: 32 px on a 2× screen, light and dark</span>{tabs(True, False)}{tabs(True, True)}</div>'
            f'<div class="cg"><span class="cl">Desktop icon and dock, light and dark</span><div class="docks">{dock(False)}{dock(True)}</div></div>'
            f'<div class="cg"><span class="cl">Clank sidebar: Obsidian rail, Figma rail, Shopify list</span>{clank("l")}{clank("d")}</div></div>')


def sil(pv: dict, suffix: str) -> str:
    return "".join(f'<img src="{pv[f"mono-{s}{suffix}"]}" width="{s}" height="{s}" alt="silhouette at {s} px">' for s in (16, 24, 32))


def chips(slug: str) -> str:
    out = []
    for key, label, weight, _ in CRITERIA:
        v = SCORES[slug][key]
        out.append(f'<span class="chip" title="{html.escape(label)} (weight {weight}): {v} of 5"><span>{html.escape(label)}</span><span class="dots">'
                   + "".join(f'<i class="{"on" if k < v else ""}"></i>' for k in range(5)) + "</span></span>")
    return '<div class="chips">' + "".join(out) + "</div>"


def card(i: int, lg, lock_w: int, pv: dict) -> str:
    n = f"{i:02d}"
    rid = n3(i)
    return f"""
<article class="card" id="m{rid}">
  <header class="card-h"><span class="no">{rid}</span><div class="nm"><h3>{html.escape(lg.name)}</h3><span class="meta">{html.escape(lg.idea)}</span></div>
    <span class="kind">{html.escape(", ".join(lg.tags))}</span>{"" if is_ref(lg) else f'<span class="score" title="weighted score out of 100">{score(lg.slug)}</span>'}</header>
  <div class="card-b">
    <div class="left">
      <div class="pair"><div class="panel light">{use(f"L{n}l", 230, cls="big")}</div><div class="panel dark">{use(f"L{n}d", 230, cls="big")}</div></div>
      <div class="lock"><div class="panel light">{use(f"K{n}l", lock_w // 5, 512 // 5, vb=f"0 0 {lock_w} 512")}</div>
        <div class="panel dark">{use(f"K{n}d", lock_w // 5, 512 // 5, vb=f"0 0 {lock_w} 512")}</div></div>
      <div class="tiny"><span class="panel light t"><img src="{pv["16"]}" width="16" height="16" alt=""></span><span class="panel dark t"><img src="{pv["16-dark"]}" width="16" height="16" alt=""></span>
        <span class="panel light t"><img src="{pv["32"]}" width="32" height="32" alt=""></span><span class="panel dark t"><img src="{pv["32-dark"]}" width="32" height="32" alt=""></span>
        <span class="panel light z"><img class="px" src="{pv["32"]}" width="96" height="96" alt=""></span><span class="panel dark z"><img class="px" src="{pv["32-dark"]}" width="96" height="96" alt=""></span>
        <span class="tl">16 px, 32 px, then the 32 px pixels 3×</span></div>
      <div class="sil"><span class="panel light s">{sil(pv, "")}</span><span class="panel dark s">{sil(pv, "-dark")}</span>
        <span class="tl">Silhouette test: one colour, filled, at 16, 24 and 32 px</span></div>
      <p class="why">{html.escape(lg.why)}</p>
      {"" if is_ref(lg) else chips(lg.slug)}
    </div>
    {context(n, lg, pv)}
  </div>
  <div class="pick-row"><button type="button" class="pick" data-pick="{rid}" aria-pressed="false"><span class="star" aria-hidden="true">☆</span> Pick</button>
    <textarea class="cmt" data-comment="{rid}" rows="2" placeholder="Comment on {rid} (saved in this browser)"></textarea></div>
</article>"""


RP_VB = "0 0 64 64"

CSS = """
:root{--bg:#FBFBF8;--surface:#FFFFFF;--ink:#0E100E;--muted:#5D625C;--line:#DFE1DB;--green:#2F6F4F;--green-ink:#FBFBF8;--soft:#F1F3EE;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0E100E;--surface:#161916;--ink:#ECEDE8;--muted:#9AA09A;--line:#2A2E2A;--green:#35DE95;--green-ink:#0E100E;--soft:#1C201C}}
:root[data-theme="dark"]{--bg:#0E100E;--surface:#161916;--ink:#ECEDE8;--muted:#9AA09A;--line:#2A2E2A;--green:#35DE95;--green-ink:#0E100E;--soft:#1C201C}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1320px;margin:0 auto;padding:28px 16px 130px}
h1{font-size:26px;line-height:1.2;margin:0 0 4px}h2{font-size:19px;margin:44px 0 6px}h3{font-size:16px;margin:0}
p{margin:6px 0}.sub{color:var(--muted);margin:0 0 14px}a{color:inherit}
code{font-family:ui-monospace,Menlo,monospace;font-size:.9em;background:var(--soft);padding:1px 5px;border-radius:4px}
blockquote{margin:10px 0;padding:8px 12px;border-left:3px solid var(--line);color:var(--muted);font-size:14px}
.topbar{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start;justify-content:space-between}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{background:transparent;color:var(--ink);border:0;padding:6px 10px;font:inherit;font-size:13px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.verdict{border:1px solid var(--line);border-left:4px solid var(--green);background:var(--surface);border-radius:10px;padding:14px 16px;margin-top:14px}
.verdict .lead{font-size:17px;margin:0 0 4px}
.crit{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--muted);font-size:13px;margin-top:10px}.crit b{color:var(--ink);font-weight:600}
.panel{display:inline-flex;align-items:center;justify-content:center;border-radius:10px;border:1px solid var(--line)}
.panel.light{background:#FBFBF8}.panel.dark{background:#121412;border-color:#2A2E2A}
.liked{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:10px}
.lk{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:8px;display:flex;flex-direction:column;gap:6px;font-size:13px}
.lk .two{display:grid;grid-template-columns:1fr 1fr;gap:6px}.lk .panel{padding:4px}.lk svg{width:100%;height:auto;display:block}
.top3{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px;margin-top:14px}
.t3{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px}
.t3 .rank{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pair .panel{padding:8px}.pair svg.big{width:100%;height:auto;max-width:230px;display:block}
.lock{display:grid;grid-template-columns:1fr 1fr;gap:8px}.lock .panel{padding:6px 8px}.lock svg{width:100%;height:auto;display:block}
.lock.one{grid-template-columns:1fr}
.tiny{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.tiny .t{width:44px;height:44px}.tiny .z{padding:4px}
.tl{font-size:11.5px;color:var(--muted);flex-basis:100%}img.px{image-rendering:pixelated;display:block}
.check{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px;overflow-x:auto}
.check table{border-collapse:collapse;min-width:560px}.check td,.check th{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line);font-size:13px;vertical-align:middle}
.check td.sz{background:#FBFBF8;border-radius:6px}.check .bar{display:inline-block;height:8px;background:var(--green);border-radius:4px;vertical-align:middle;margin-right:6px}
.grid{display:flex;flex-direction:column;gap:18px;margin-top:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px}
.card.picked{border-color:var(--green);box-shadow:0 0 0 1px var(--green)}
.card-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.card-h .no{font:600 18px/1 ui-monospace,Menlo,monospace;color:var(--muted)}
.card-h .nm{flex:1;min-width:200px}.card-h .meta{font-size:12.5px;color:var(--muted)}
.kind{font-size:11.5px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;color:var(--muted)}
.score{font:600 13px/1 ui-monospace,Menlo,monospace;border:1px solid var(--line);border-radius:999px;padding:4px 8px}
.card-b{display:grid;grid-template-columns:minmax(0,470px) minmax(0,1fr);gap:16px;align-items:start}
.left{display:flex;flex-direction:column;gap:9px}
.why{font-size:14px}.c2r{font-size:12.5px;color:var(--muted)}.c2r b{color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:4px 10px}.chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--muted)}
.dots{display:inline-flex;gap:2px}.dots i{width:6px;height:6px;border-radius:1px;background:var(--line);display:block}.dots i.on{background:var(--green)}
.context{display:flex;flex-direction:column;gap:10px;min-width:0}
.cg{display:flex;flex-direction:column;gap:6px}.cl{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.ctx{border-radius:10px;overflow:hidden;border:1px solid var(--line)}
.site.light{background:#FBFBF8;color:#0E100E}.site.dark{background:#0E100E;color:#ECEDE8;border-color:#2A2E2A}
.site .bar{display:flex;align-items:center;gap:14px;padding:10px 14px;border-bottom:1px solid rgba(128,128,128,.25)}
.site .brand{display:flex;align-items:center;gap:8px}.site nav{display:flex;gap:14px;font-size:13px;opacity:.75;margin-left:auto}
.site .cta{font-size:12.5px;border:1px solid currentColor;border-radius:7px;padding:4px 9px}
.site .hero{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px}.site .hero b{font-size:16px}
.site .hero i{display:block;height:7px;width:62%;border-radius:4px;background:currentColor;opacity:.13}.site .hero i.s{width:40%}
.tabs.light{background:#DEE1E6;color:#1F1F1F}.tabs.dark{background:#1E1F22;color:#E3E3E3;border-color:#2A2E2A}
.tabs .strip{display:flex;gap:2px;padding:6px 8px 0;overflow:hidden}
.tabs .tab{display:inline-flex;align-items:center;gap:7px;padding:7px 12px;border-radius:9px 9px 0 0;font-size:12px;white-space:nowrap;max-width:200px;overflow:hidden;opacity:.8}
.tabs .tab.on{background:#FFFFFF;opacity:1}.tabs.dark .tab.on{background:#35363A}
.tabs .url{font-size:12px;padding:6px 14px;background:#FFFFFF;color:#555}.tabs.dark .url{background:#35363A;color:#BBB}
.tabs.x2 .tab{font-size:22px;padding:12px 20px;gap:12px;max-width:none;border-radius:16px 16px 0 0}.tabs.x2 .url{font-size:20px;padding:10px 20px}
.docks{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.desk{padding:14px;display:flex;flex-direction:column;gap:14px;align-items:flex-start}
.desk.dark{background:linear-gradient(135deg,#1D3B30,#0E1A16 55%,#2B2140);border-color:#2A2E2A}
.desk.light{background:linear-gradient(135deg,#F3F5EF,#DDE6E0 55%,#E6E1EE)}
.desktop-icon{display:flex;flex-direction:column;align-items:center;gap:6px;font-size:13px}
.desk.dark .desktop-icon{color:#FFFFFF;text-shadow:0 1px 2px #000}.desk.light .desktop-icon{color:#1F1F1F}
.app{display:inline-flex;align-items:center;justify-content:center;flex:none}.app.ink{background:#0E100E;box-shadow:inset 0 0 0 1px #2E332E}
.app.paper{background:#FBFBF8;box-shadow:inset 0 0 0 1px #DFE1DB}
.dock{display:flex;gap:8px;align-items:center;padding:8px 10px;border-radius:18px;align-self:center;flex-wrap:wrap;justify-content:center}
.desk.dark .dock{background:rgba(20,22,20,.72);box-shadow:0 0 0 1px rgba(255,255,255,.08)}.desk.light .dock{background:rgba(255,255,255,.62);box-shadow:0 0 0 1px rgba(0,0,0,.08)}
.dock .run{display:inline-flex;flex-direction:column;align-items:center;gap:3px}.dock .run i{width:6px;height:6px;border-radius:3px}
.desk.dark .dock .run i{background:#FFFFFF}.desk.light .dock .run i{background:#1F1F1F}
.sil{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.sil .s{gap:8px;padding:6px 10px;align-items:center}.sil img{display:block}
.clank{display:flex;gap:10px;padding:10px;align-items:flex-start;flex-wrap:wrap}
.clank.light{background:#F6F6F6;color:#222222}.clank.dark{background:#262626;color:#DADADA;border-color:#363636}
.rail{display:flex;flex-direction:column;gap:4px;padding:6px;border-right:1px solid rgba(128,128,128,.25)}
.rail span{display:flex;align-items:center;gap:10px;border-radius:7px;padding:6px}
.rail span.on{background:rgba(128,128,128,.16)}
.rail.obs span{justify-content:center;width:40px;height:40px;padding:0}
.rail.fig{width:84px}.rail.fig span{flex-direction:column;gap:4px;text-align:center;padding:6px 2px}.rail.fig em{font-style:normal;font-size:11.5px;line-height:1.15}
.rail.shop{flex:1;min-width:190px;border-right:0}.rail.shop em{font-style:normal;font-size:15px}
.pick-row{display:flex;gap:8px;align-items:stretch}
.pick{flex:none;border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:8px;padding:6px 12px;font:inherit;font-size:14px;cursor:pointer}
.pick[aria-pressed="true"]{background:var(--green);color:var(--green-ink);border-color:var(--green)}
.cmt{flex:1;min-width:0;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit;font-size:13px;padding:6px 8px;resize:vertical}
.dock-bar{position:fixed;left:0;right:0;bottom:0;background:var(--surface);border-top:1px solid var(--line);z-index:5}
.dock-in{max-width:1320px;margin:0 auto;padding:10px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.dock-in .status{flex:1;min-width:0;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{border:1px solid var(--ink);background:var(--ink);color:var(--bg);border-radius:8px;padding:8px 14px;font:inherit;font-size:14px;cursor:pointer}
.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
#copyout{width:100%;font:12px/1.4 ui-monospace,Menlo,monospace;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);padding:8px;display:none}
.notes{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:10px}
.note{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;font-size:14px}.note ul{margin:6px 0;padding-left:18px}
@media (max-width:900px){.card-b{grid-template-columns:1fr}}
@media (max-width:620px){.docks{grid-template-columns:1fr}}
@media (max-width:520px){h1{font-size:22px}.top3{grid-template-columns:1fr}.site nav{display:none}.tabs.x2 .tab:nth-child(n+2){display:none}.tabs .tab:nth-child(3){display:none}}
"""

JS = r"""
(function(){
const KEY='sim2real-logos-r4-2026-10-28';
let state={picks:{},comments:{},theme:''};
try{const raw=localStorage.getItem(KEY);if(raw){const s=JSON.parse(raw);if(s&&typeof s==='object')state=Object.assign(state,s);}}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(e){}}
const root=document.documentElement;
function applyTheme(){if(state.theme)root.setAttribute('data-theme',state.theme);else root.removeAttribute('data-theme');
  document.querySelectorAll('[data-theme-btn]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeBtn===(state.theme||'auto'))));}
document.querySelectorAll('[data-theme-btn]').forEach(b=>b.addEventListener('click',()=>{const t=b.dataset.themeBtn;state.theme=t==='auto'?'':t;applyTheme();save();}));
const picked=()=>Object.keys(state.picks).filter(n=>state.picks[n]).sort();
const commented=()=>Object.keys(state.comments).filter(n=>(state.comments[n]||'').trim());
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
  const lines=['sim2real logo picks, round 4 (reports/sim2real-logos-r4-2026-10-28.html)'];
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


def build_report(logos) -> str:
    symbols, lock_ws = [], {}
    for P, t in ((LIGHT, "l"), (DARK, "d")):
        symbols.append(f'<g id="WM{t}">{wordmark(P, XH)[0]}</g>')
    for i, lg in enumerate(logos, 0):
        n = f"{i:02d}"
        for P, t in ((LIGHT, "l"), (DARK, "d")):
            uid = f"{n}{t}"
            symbols.append(f'<symbol id="L{uid}" viewBox="0 0 512 512">{lg.draw(P, "x" + uid)}</symbol>')
            body, lock_ws[n] = lockup(lg, P, uid, inner=f'<use href="#L{uid}" width="512" height="512"/>', wm_ref=f"WM{t}")
            symbols.append(f'<symbol id="K{uid}" viewBox="0 0 {lock_ws[n]} 512">{body}</symbol>')
    for path, sid in ((RP_MARK, "RPl"), (RP_MARK_DARK, "RPd")):
        vb, inner = strip_svg_root(path.read_text())
        symbols.append(f'<symbol id="{sid}" viewBox="{vb}">{inner}</symbol>')
    vb, inner = strip_svg_root(BAM_ICON.read_text())
    symbols.append(f'<symbol id="BAM" viewBox="{vb}">{inner}</symbol>')
    vb, inner = strip_svg_root(CAD2ROBOT_FAVICON.read_text())
    symbols.append(f'<symbol id="C2R" viewBox="{vb}">{inner}</symbol>')
    sprite = '<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>' + "".join(symbols) + "</defs></svg>"

    pvs = {}
    for i, lg in enumerate(logos, 0):
        base = HERE / "preview" / f"{i:02d}-{lg.slug}"
        pvs[lg.slug] = {"16": png(pathlib.Path(f"{base}-16.png")), "32": png(pathlib.Path(f"{base}-32.png")),
                        "16-dark": png(pathlib.Path(f"{base}-16-dark.png")), "32-dark": png(pathlib.Path(f"{base}-32-dark.png"))}
        for sz in (16, 24, 32):
            for suf in ("", "-dark"):
                pvs[lg.slug][f"mono-{sz}{suf}"] = png(pathlib.Path(f"{base}-mono-{sz}{suf}.png"))

    top3 = ""
    for i, lg in enumerate(logos[1:4], 1):
        n = f"{i:02d}"
        pv = pvs[lg.slug]
        top3 += (f'<div class="t3"><div class="rank">#{i} · score {score(lg.slug)}</div><h3><a href="#m{n3(i)}">{n3(i)} {html.escape(lg.name)}</a></h3>'
                 f'<div class="pair"><div class="panel light">{use(f"L{n}l", 210, cls="big")}</div><div class="panel dark">{use(f"L{n}d", 210, cls="big")}</div></div>'
                 f'<div class="lock one"><div class="panel light">{use(f"K{n}l", lock_ws[n] // 5, 512 // 5, vb=f"0 0 {lock_ws[n]} 512")}</div></div>'
                 f'<div class="tiny"><span class="panel light t"><img src="{pv["16"]}" width="16" height="16" alt=""></span>'
                 f'<span class="panel light t"><img src="{pv["32"]}" width="32" height="32" alt=""></span><span class="panel dark t"><img src="{pv["32-dark"]}" width="32" height="32" alt=""></span>'
                 f'<span class="tl">favicon at 16 and 32 px</span></div>'
                 f'<div class="sil"><span class="panel light s">{sil(pv, "")}</span><span class="panel dark s">{sil(pv, "-dark")}</span>'
                 f'<span class="tl">silhouette at 16, 24, 32 px</span></div><p>{html.escape(TOP3_WHY[lg.slug])}</p></div>')

    crit = "".join(f'<span title="{html.escape(d)}"><b>{html.escape(label)}</b> {w}</span>' for _, label, w, d in CRITERIA)
    ref_card = card(0, logos[0], lock_ws["00"], pvs[logos[0].slug])
    cards = "".join(card(i, lg, lock_ws[f"{i:02d}"], pvs[lg.slug]) for i, lg in enumerate(logos, 0) if i > 0)
    names = json.dumps({n3(i): lg.name for i, lg in enumerate(logos, 0)}, ensure_ascii=False)
    fav = pvs[logos[1].slug]["32"]
    t = logos[1:4]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sim2real logos, round 4</title>
<link rel="icon" href="{fav}">
<style>{CSS}</style>
</head>
<body>
{sprite}
<main>
<div class="topbar"><div><h1>sim2real logo · round 4 · ten variants of Assemble</h1>
<p class="sub">{DATE} · his pick, R3-04 Assemble, ten ways: blocks that progressively become the gear, cut-outs that are more blocked, and three other compositions · same wordmark</p></div>
<div class="seg" role="group" aria-label="Page theme"><button type="button" data-theme-btn="auto">Auto</button><button type="button" data-theme-btn="light">Light</button><button type="button" data-theme-btn="dark">Dark</button></div></div>

<section class="verdict" aria-label="Verdict">
  <p class="lead"><b>Recommend {n3(1)} {html.escape(t[0].name)}</b>, then {n3(2)} {html.escape(t[1].name)} and {n3(3)} {html.escape(t[2].name)}.</p>
  <p>The 'sim2real' wordmark is exactly R3-04's; only the mark changes. Four variants change progressively into the gear (size, resolution, density, teeth), three make the cut-outs blocky (square holes, a stepped silhouette, a clean staircase), three try other compositions (from above, into the hub, a tight snap-fit). Round 3's rules hold: a chunky 8-tooth gear, big blocks, a one-colour silhouette at 16, 24 and 32 px, and every mark shown in light and dark in a site header, a tab strip, a dock and Clank's sidebar.</p>
  <p>Pick any (★, R3-04 included), comment, then <b>Copy my picks</b> and paste the text into chat.</p>
  <blockquote>"Ok I like assemble the most ... I like the sim2real text that perfect keep that but please kinda change how the assemble looks. I feel like it needs to kinda more progressively change into the gear as one of the options.. like maybe the cut outs should be more blocked?" Zach, {DATE}</blockquote>
  <div class="crit">Criteria, weight out of 100 (AI judgement, 1-5 each, not measured): {crit}</div>
</section>

<h2>The reference: R3-04 Assemble, as he picked it</h2>
<div class="grid">{ref_card}</div>

<h2>Top 3</h2>
<div class="top3">{top3}</div>

<h2>All ten, each in context</h2>
<p class="sub">{n3(1)}-{n3(10)}, numbered by score. Left: the mark on light and dark, the lockup, the favicon rasters, the silhouette. Right: the same mark in a site header, a tab strip, a dock, and Clank's sidebar, light and dark.</p>
<div class="grid">{cards}</div>

<h2>Notes</h2>
<div class="notes">
  <div class="note"><h3>How they are built</h3><ul>
    <li>Round 3's kit (<code>brand/logos/round3/marks3.py</code>): one 8-tooth gear with a big bore, blocks on a grid, flat steel with a thick rim; the ten marks are in <code>brand/logos/round4/marks4.py</code>.</li>
    <li>Every mark has the one-colour mode (steel and blocks in ink, knock-outs in the background colour): the silhouette test, and the start of the 24 px icon.</li>
    <li>Rendered headlessly at 240, 48, 32, 24 and 16 px, light and dark, and looked at. Fixed after looking: Stair Cut and Vertical Drop came out hollow (a keep-mask of grid cells also clipped the tooth tips past the grid, so the cut is now subtracted), and their first staircase was too shallow to see; Size Ramp's steel was clipped to a bracket; Square Holes had too few holes and its squares had flown off the artboard.</li></ul></div>
  <div class="note"><h3>Context mocks</h3><ul>
    <li>Clank's sidebar copies the three styles in <code>clank-workbench/reports/media/clank-sidebar-styles-2026-10-26.html</code> (Obsidian rail, Figma rail, Shopify list; light #F6F6F6, dark #262626), with Robot Parts' and BAM Robotics' real icons. Clank itself was only read.</li>
    <li>The tab strip uses the real 16 and 32 px rasters; its neighbours are robotparts.dev and cad2robot.com's real favicons.</li>
    <li>Palette: BAM Grid Purist, ink <code>{INK}</code>, paper <code>{PAPER}</code>, BAM Green <code>{BAM_GREEN}</code>, lit <code>{GREEN_LIT}</code> on dark.</li></ul></div>
  <div class="note"><h3>Files</h3><ul>
    <li><code>brand/logos/round4/NN-slug.svg</code>, <code>-dark.svg</code>, <code>-lockup.svg</code>, <code>-lockup-dark.svg</code>; <code>preview/NN-slug-16.png</code>, <code>-32.png</code>, <code>-mono-16/24/32.png</code> (and dark). R3-04's own files stay in <code>round3/</code>.</li>
    <li>Rebuild: <code>render4.py --previews</code>, then <code>build4.py</code> (commands in <code>brand/logos/round4/README.md</code>).</li></ul></div>
</div>
</main>
<div class="dock-bar" role="region" aria-label="Your picks"><div class="dock-in">
  <span class="status" id="status" aria-live="polite"></span>
  <button type="button" class="btn ghost" id="clear">Clear</button><button type="button" class="btn" id="copy">Copy my picks</button>
  <textarea id="copyout" rows="5" readonly aria-label="Your picks as text"></textarea></div></div>
<script>const NAMES={names};{JS}</script>
</body>
</html>
"""


def main() -> None:
    logos = [REF] + ordered()
    missing = [lg.slug for i, lg in enumerate(logos, 0) if not (HERE / "preview" / f"{i:02d}-{lg.slug}-32.png").exists()]
    if missing or set(BOXES) != {lg.slug for lg in logos}:
        sys.exit(f"run render4.py --previews first (missing previews or boxes: {missing})")
    write_files(logos)
    write_readme(logos)
    page = build_report(logos)
    REPORT.write_text(page)
    kb = len(page.encode()) / 1024
    print(f"{n3(1)} {logos[1].name} · {REPORT} ({kb:.0f} KB)")


if __name__ == "__main__":
    main()
