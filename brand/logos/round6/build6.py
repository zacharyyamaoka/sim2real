"""Round 6: make the picked logos the defaults, and one small before/after page.

    uv run --no-project --with playwright --with pillow --with svgpathtools python /home/bam/sim2real/brand/logos/round6/build6.py

Writes:
- brand/logos/round6/: R6-A and R6-B (light, dark, lockups), previews, bboxes.json
- brand/logos/sim2real-logo.svg, -dark.svg, -lockup.svg, -lockup-dark.svg: R6-A, the sim2real default
- brand/icons/sim2real.svg, sim2real-app.svg, sim2real.iconnode.json: R6-A simplified (what Clank reads)
- /home/bam/cad2robot-website/brand/cad2robot-*.svg: C2R-02 Mirror Line as cad2robot's default mark
  (brand/ only: public/ and the live site are untouched until Zach says deploy)
- reports/sim2real-logos-r6-2026-10-28.html
"""

from __future__ import annotations

import base64
import html
import io
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "round5"))

import marks6  # noqa: E402
import build5  # noqa: E402  (the round-5 page parts: lockup, context mocks, CSS, JS)
from geom import DARK, LIGHT  # noqa: E402
from logos import svg  # noqa: E402
from marks3 import mono  # noqa: E402

DATE = "2026-10-28"
REPORT = REPO / "reports" / f"sim2real-logos-r6-{DATE}.html"
LOGOS_DIR = REPO / "brand" / "logos"
ICONS_DIR = REPO / "brand" / "icons"
C2R_REPO = pathlib.Path("/home/bam/cad2robot-website")
C2R_SRC = C2R_REPO / "brand" / "logos" / "round1"
C2R_OUT = C2R_REPO / "brand"
CHROME = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"

R6A, R6B = marks6.R6
ALL = [R6A, R6B, marks6.BEFORE[R6A.slug], marks6.BEFORE[R6B.slug]]
LABEL = {R6A.slug: "R6-A", R6B.slug: "R6-B", "clipped-dither": "R5-03", "quantised-silhouette": "R5-01"}


def icon24(size: int = 24) -> str:
    body = "".join(f'<path d="{d}"/>' for d in marks6.icon24_paths())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def square(box, pad=10):
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0) + 2 * pad
    return (x0 + x1) / 2 - side / 2, (y0 + y1) / 2 - side / 2, side


def app256(box) -> str:
    """The dock/app icon: R6-A (dark palette) cropped to its ink, at 80 % of an ink tile with the BAM micro radius."""
    x, y, s = square(box)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><title>sim2real</title>'
            '<rect x="1" y="1" width="254" height="254" rx="12" fill="#0E100E"/>'
            f'<svg x="26" y="26" width="204" height="204" viewBox="{x:.1f} {y:.1f} {s:.1f} {s:.1f}">{R6A.draw(DARK, "app")}</svg></svg>')


def render_assets() -> dict:
    """Ink boxes and the 16/32 px rasters and one-colour silhouettes, for the four logos and the icon."""
    from PIL import Image
    from playwright.sync_api import sync_playwright

    pv = HERE / "preview"
    pv.mkdir(exist_ok=True)
    boxes = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME)
        page = b.new_page(viewport={"width": 512, "height": 512})
        for lg in ALL:
            box = None
            for P in (LIGHT, DARK):
                page.set_content(f'<body style="margin:0;background:transparent">{svg(lg, P, size=512)}</body>')
                img = Image.open(io.BytesIO(page.locator("svg").screenshot(omit_background=True)))
                bb = img.getchannel("A").point(lambda a: 255 if a > 60 else 0).getbbox()
                box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
            boxes[lg.slug] = list(box)
            x, y, s = square(box)
            for P, suf in ((LIGHT, ""), (DARK, "-dark")):
                for size in (16, 32):
                    page.set_content(f'<body style="margin:0;background:transparent"><svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {s} {s}" '
                                     f'width="{size}" height="{size}">{lg.draw(P, "pv")}</svg></body>')
                    page.locator("svg").screenshot(path=str(pv / f"{lg.slug}-{size}{suf}.png"), omit_background=True)
                for size in (16, 24, 32):
                    page.set_content(f'<body style="margin:0;background:{P["bg"]}"><svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {s} {s}" '
                                     f'width="{size}" height="{size}">{lg.draw(mono(P), "pm")}</svg></body>')
                    page.locator("svg").screenshot(path=str(pv / f"{lg.slug}-mono-{size}{suf}.png"))
        # the toolbar icon as Clank draws it: currentColor in the sidebar's text colour
        for bg, fg, suf in (("#F6F6F6", "#222222", ""), ("#262626", "#DADADA", "-dark")):
            for size in (16, 24, 32):
                page.set_content(f'<body style="margin:0;background:{bg};color:{fg}">{icon24(size)}</body>')
                page.locator("svg").screenshot(path=str(pv / f"icon-{size}{suf}.png"))
        b.close()
    (HERE / "bboxes.json").write_text(json.dumps(boxes, indent=1) + "\n")
    return boxes


def write_sim2real(boxes) -> list[pathlib.Path]:
    build5.BOXES = boxes  # the round-5 lockup crops to these ink boxes
    written = []
    for lg, nn in ((R6A, "A"), (R6B, "B")):
        for P, suf in ((LIGHT, ""), (DARK, "-dark")):
            (HERE / f"R6-{nn}-{lg.slug}{suf}.svg").write_text(svg(lg, P, title=f"sim2real - {lg.name}") + "\n")
            body, width = build5.lockup(lg, P, f"{lg.slug}-{P['name']}")
            (HERE / f"R6-{nn}-{lg.slug}-lockup{suf}.svg").write_text(
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 512" width="{width // 2}" height="256"><title>sim2real</title>{body}</svg>\n')
    # the defaults
    for P, suf in ((LIGHT, ""), (DARK, "-dark")):
        path = LOGOS_DIR / f"sim2real-logo{suf}.svg"
        path.write_text(svg(R6A, P, title="sim2real") + "\n")
        written.append(path)
        body, width = build5.lockup(R6A, P, f"default-{P['name']}")
        path = LOGOS_DIR / f"sim2real-logo-lockup{suf}.svg"
        path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 512" width="{width // 2}" height="256"><title>sim2real</title>{body}</svg>\n')
        written.append(path)
    (ICONS_DIR / "sim2real.svg").write_text(icon24() + "\n")
    (ICONS_DIR / "sim2real-app.svg").write_text(app256(boxes[R6A.slug]) + "\n")
    (ICONS_DIR / "sim2real.iconnode.json").write_text(json.dumps([["path", {"d": d}] for d in marks6.icon24_paths()]) + "\n")
    written += [ICONS_DIR / "sim2real.svg", ICONS_DIR / "sim2real-app.svg", ICONS_DIR / "sim2real.iconnode.json"]
    return written


# ---------------------------------------------------------------------------------------------
# cad2robot: C2R-02 Mirror Line as the default mark (brand/ only)
# ---------------------------------------------------------------------------------------------

C2R_ICON24 = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    # the robot face: head, ears, antenna, eyes; the dash-dot mirror line down the middle
    '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M4 12.5H2.5v4H4M20 12.5h1.5v4H20"/>'
    '<circle cx="12" cy="4" r="1.5"/><circle cx="8.5" cy="14" r="1.5"/><circle cx="15.5" cy="14" r="1.5"/>'
    '<path d="M12 6.5v1M12 10v1.5M12 16.5v1.5M12 21v1"/></svg>'
)


def write_cad2robot() -> list[pathlib.Path]:
    src = {"cad2robot-logo.svg": "02-mirror-line.svg", "cad2robot-logo-dark.svg": "02-mirror-line-dark.svg",
           "cad2robot-lockup.svg": "02-mirror-line-lockup.svg", "cad2robot-lockup-dark.svg": "02-mirror-line-lockup-dark.svg",
           "cad2robot-favicon.svg": "02-mirror-line-favicon.svg", "cad2robot-favicon-dark.svg": "02-mirror-line-favicon-dark.svg"}
    written = []
    for out, name in src.items():
        text = (C2R_SRC / name).read_text()
        (C2R_OUT / out).write_text(text)
        written.append(C2R_OUT / out)
    (C2R_OUT / "cad2robot-icon.svg").write_text(C2R_ICON24 + "\n")
    dark = (C2R_SRC / "02-mirror-line-dark.svg").read_text()
    vb = re.search(r'viewBox="([^"]+)"', dark).group(1)
    inner = re.sub(r"^.*?<svg[^>]*>|</svg>\s*$", "", dark, flags=re.S)
    inner = re.sub(r"<title>.*?</title>", "", inner)
    (C2R_OUT / "cad2robot-app.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><title>cad2robot</title>'
        '<rect x="1" y="1" width="254" height="254" rx="12" fill="#0E100E"/>'
        f'<svg x="20" y="20" width="216" height="216" viewBox="{vb}">{inner}</svg></svg>\n')
    written += [C2R_OUT / "cad2robot-icon.svg", C2R_OUT / "cad2robot-app.svg"]
    return written


# ---------------------------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------------------------


def png(p: pathlib.Path) -> str:
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


def uri_svg(text: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(text.encode()).decode()


def build_page(boxes) -> str:
    pvd = HERE / "preview"
    symbols, lock_w = [], {}
    for P, t in ((LIGHT, "l"), (DARK, "d")):
        symbols.append(f'<g id="WM{t}">{build5.wordmark(P, build5.XH)[0]}</g>')
    for k, lg in enumerate(ALL, 1):
        n = f"{k:02d}"
        for P, t in ((LIGHT, "l"), (DARK, "d")):
            uid = f"{n}{t}"
            symbols.append(f'<symbol id="L{uid}" viewBox="0 0 512 512">{lg.draw(P, "x" + uid)}</symbol>')
            body, lock_w[n] = build5.lockup(lg, P, uid, inner=f'<use href="#L{uid}" width="512" height="512"/>', wm_ref=f"WM{t}")
            symbols.append(f'<symbol id="K{uid}" viewBox="0 0 {lock_w[n]} 512">{body}</symbol>')
    for path, sid in ((build5.RP_MARK, "RPl"), (build5.RP_MARK_DARK, "RPd")):
        vb, inner = build5.strip_svg_root(path.read_text())
        symbols.append(f'<symbol id="{sid}" viewBox="{vb}">{inner}</symbol>')
    vb, inner = build5.strip_svg_root(build5.BAM_ICON.read_text())
    symbols.append(f'<symbol id="BAM" viewBox="{vb}">{inner}</symbol>')
    # cad2robot in the context mocks' tab strips is now its new favicon
    vb, inner = build5.strip_svg_root((C2R_OUT / "cad2robot-favicon.svg").read_text())
    symbols.append(f'<symbol id="C2R" viewBox="0 0 64 64"><svg width="64" height="64" viewBox="{vb}">{inner}</svg></symbol>')
    sprite = '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>' + "".join(symbols) + "</defs></svg>"

    def pv(slug):
        d = {}
        for suf in ("", "-dark"):
            for s in (16, 32):
                d[f"{s}{suf}"] = png(pvd / f"{slug}-{s}{suf}.png")
            for s in (16, 24, 32):
                d[f"mono-{s}{suf}"] = png(pvd / f"{slug}-mono-{s}{suf}.png")
        return d

    def tile(k, lg):
        n = f"{k:02d}"
        p = pv(lg.slug)
        return (f'<div class="t3"><div class="rank">{LABEL[lg.slug]}</div><h3>{html.escape(lg.name)}</h3>'
                f'<div class="pair"><div class="panel light">{build5.use(f"L{n}l", 210, cls="big")}</div><div class="panel dark">{build5.use(f"L{n}d", 210, cls="big")}</div></div>'
                f'<div class="lock one"><div class="panel light">{build5.use(f"K{n}l", lock_w[n] // 5, 512 // 5, vb=f"0 0 {lock_w[n]} 512")}</div></div>'
                f'<div class="sil"><span class="panel light s">{build5.sil(p, "")}</span><span class="panel dark s">{build5.sil(p, "-dark")}</span>'
                f'<span class="tl">one-colour silhouette at 16, 24, 32 px</span></div></div>')

    pairs = (f'<h2>R6-A: Clipped Dither, final (left: R5-03 before)</h2><div class="top3">{tile(3, ALL[2])}{tile(1, ALL[0])}</div>'
             f'<h2>R6-B: Quantised Silhouette, even split (left: R5-01 before)</h2><div class="top3">{tile(4, ALL[3])}{tile(2, ALL[1])}</div>')

    icon_rows = ""
    for bg, fg, suf, name in (("#F6F6F6", "#222222", "", "light"), ("#262626", "#DADADA", "-dark", "dark")):
        imgs = "".join(f'<img src="{png(pvd / f"icon-{s}{suf}.png")}" width="{s}" height="{s}" alt="">' for s in (16, 24, 32))
        big = icon24(96).replace("<svg ", f'<svg style="color:{fg}" ', 1)
        icon_rows += f'<div class="panel" style="background:{bg};color:{fg};gap:14px;padding:12px">{imgs}{big}</div>'
    app = (ICONS_DIR / "sim2real-app.svg").read_text().replace('width="256" height="256"', 'width="128" height="128"', 1)
    c2r_app = (C2R_OUT / "cad2robot-app.svg").read_text().replace('width="256" height="256"', 'width="128" height="128"', 1)
    c2r_icon = C2R_ICON24.replace('width="24" height="24"', 'width="96" height="96"', 1)

    # sim2real beside cad2robot in a tab strip, light and dark, 16 and 32 px
    p_a = pv(R6A.slug)
    fav_l, fav_d = uri_svg((C2R_OUT / "cad2robot-favicon.svg").read_text()), uri_svg((C2R_OUT / "cad2robot-favicon-dark.svg").read_text())
    strips = ""
    for dark in (False, True):
        for sz in (16, 32):
            cls = ("tabs x2" if sz == 32 else "tabs") + (" dark" if dark else " light")
            me = p_a[f"{sz}-dark" if dark else f"{sz}"]
            other = fav_d if dark else fav_l
            strips += (f'<div class="ctx {cls}"><div class="strip"><span class="tab on"><img src="{me}" width="{sz}" height="{sz}" alt="">sim2real · twins</span>'
                       f'<span class="tab"><img src="{other}" width="{sz}" height="{sz}" alt="">cad2robot</span></div>'
                       f'<div class="url">sim2real.local/twins</div></div>')

    ctx = build5.context("01", R6A, p_a)
    overwritten = "".join(f"<li><code>{html.escape(str(p).replace('/home/bam/', '~/'))}</code></li>" for p in WRITTEN)
    names = json.dumps({"R6-A": R6A.name, "R6-B": R6B.name}, ensure_ascii=False)
    js = build5.JS.replace("sim2real-logos-r5-2026-10-28", "sim2real-logos-r6-2026-10-28").replace("round 5", "round 6")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>sim2real logo, final</title><link rel="icon" href="{p_a["32"]}"><style>{build5.CSS}code{{overflow-wrap:anywhere}}</style></head>
<body>{sprite}<main>
<div class="topbar"><div><h1>sim2real logo · round 6 · the pick, finished</h1>
<p class="sub">{DATE} · R5-03 Clipped Dither refined into the default (R6-A), R5-01 refined the same way (R6-B), and cad2robot's pick C2R-02 Mirror Line applied as its default mark</p></div>
<div class="seg" role="group" aria-label="Page theme"><button type="button" data-theme-btn="auto">Auto</button><button type="button" data-theme-btn="light">Light</button><button type="button" data-theme-btn="dark">Dark</button></div></div>
<section class="verdict"><p class="lead"><b>R6-A Clipped Dither is now sim2real's logo and icon</b>; files written, nothing committed, nothing deployed.</p>
<p>Exactly half the gear is pixels: the split is the gear's centre line, and the pixel grid is anchored on it with a cell equal to half a tooth, so the top and bottom teeth are one pixel column thick on the digital side. No pixel is clipped: a block is drawn whole when more than half of it lies inside the gear, and dropped otherwise. The dither ramp is R5-03's.</p>
<blockquote>"For logo do the clipped dither. Make it center tooth only 1 thick though so exactly just half of it is pixels. and then for the clipping don't completely round the pixels if more than 50% of the pixel is showing then draw the entire block. On the quantised silhouette split it evenly as well so the middle tooth is only 1 pixel thick." Zach, {DATE}</blockquote></section>
{pairs}
<h2>The new toolbar and app icons (what Clank reads)</h2>
<p class="sub">R6-A simplified to a lucide mark (24 grid, stroke 2, currentColor): the right half the smooth gear, the left half the same gear quantised on a 2-unit grid, two loose pixels. Shown at 16, 24, 32 and 96 px in Clank's sidebar colours, then the 256 px app icon.</p>
<div class="sil">{icon_rows}<span class="panel dark" style="padding:8px">{app}</span></div>
<h2>sim2real beside cad2robot (C2R-02 Mirror Line)</h2>
<p class="sub">Browser tabs at 16 px and at 32 px on a 2× screen, light and dark. Then cad2robot's new 24 px icon and app icon.</p>
<div class="context">{strips}</div>
<div class="sil" style="margin-top:10px"><span class="panel light" style="padding:12px;color:#222">{c2r_icon}</span><span class="panel dark" style="padding:12px;color:#DADADA">{c2r_icon}</span><span class="panel dark" style="padding:8px">{c2r_app}</span></div>
<h2>R6-A in context</h2>
<div class="card"><div class="card-b"><div class="left"><p class="why">The logo cropped as a favicon and app tile, light and dark; Clank's sidebar shows the logo here, while the real sidebar draws the 24 px icon above.</p>
<div class="pick-row"><button type="button" class="pick" data-pick="R6-A" aria-pressed="false"><span class="star" aria-hidden="true">☆</span> Pick</button><textarea class="cmt" data-comment="R6-A" rows="2" placeholder="Comment on R6-A"></textarea></div>
<div class="pick-row"><button type="button" class="pick" data-pick="R6-B" aria-pressed="false"><span class="star" aria-hidden="true">☆</span> Pick R6-B instead</button><textarea class="cmt" data-comment="R6-B" rows="2" placeholder="Comment on R6-B"></textarea></div></div>
{ctx}</div></div>
<h2>Files written</h2><div class="note"><ul>{overwritten}</ul>
<p>Overwritten in place (old versions kept in git): <code>brand/icons/sim2real.svg</code>, <code>sim2real-app.svg</code>, <code>sim2real.iconnode.json</code>. Round files untouched. cad2robot: only new files in <code>brand/</code>; <code>public/</code> and the live site unchanged.</p></div>
</main>
<div class="dock-bar" role="region" aria-label="Your picks"><div class="dock-in"><span class="status" id="status" aria-live="polite"></span>
<button type="button" class="btn ghost" id="clear">Clear</button><button type="button" class="btn" id="copy">Copy my picks</button>
<textarea id="copyout" rows="5" readonly aria-label="Your picks as text"></textarea></div></div>
<script>const NAMES={names};{js}</script></body></html>
"""


WRITTEN: list[pathlib.Path] = []


def main() -> None:
    boxes = render_assets()
    WRITTEN.extend(write_sim2real(boxes))
    WRITTEN.extend(write_cad2robot())
    page = build_page(boxes)
    REPORT.write_text(page)
    print(f"{REPORT} ({len(page.encode()) / 1024:.0f} KB)")
    for p in WRITTEN:
        print("wrote", p)


if __name__ == "__main__":
    main()
