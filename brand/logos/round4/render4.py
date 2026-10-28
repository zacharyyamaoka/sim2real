"""Render the round-4 marks (R3-04 as the reference, then the ten variants) headlessly so they can be LOOKED at.

    uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round4/render4.py --out /tmp/s2r-r4 --previews

Writes into --out: sheet-light.png and sheet-dark.png (every logo at 240 px, at 32 px, and the 32 px raster
blown up 4x, plus the one-colour silhouette). With --previews: bboxes.json (the ink box of every mark, so the
lockups and context mocks can crop to it), and preview/NN-<slug>-{16,32}[-dark].png and
preview/NN-<slug>-mono-{16,24,32}[-dark].png cropped to that box (00 = R3-04, the reference).
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import marks4  # noqa: E402  (puts round3 and round2 on the path)
import marks3  # noqa: E402
from geom import PALETTES  # noqa: E402
from logos import svg  # noqa: E402

CHROME = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"


def ordered():
    """R3-04 itself first (numbered 00), then the ten variants best first."""
    from scores4 import ordered as o

    return [marks4.REFERENCE] + o()


def sheet(theme: str, logos) -> str:
    P = PALETTES[theme]
    cells = []
    for i, lg in enumerate(logos, 1):
        cells.append(
            f'<div class="c"><div class="big">{svg(lg, P, uid=f"a{i}", size=240)}</div>'
            f'<div class="sm">{svg(lg, P, uid=f"b{i}", size=32)}{svg(lg, P, uid=f"c{i}", size=16)}<canvas width="128" height="128"></canvas></div>'
            f'<div class="sm">{svg(lg, marks3.mono(P), uid=f"m{i}", size=48)}{svg(lg, marks3.mono(P), uid=f"n{i}", size=24)}{svg(lg, marks3.mono(P), uid=f"o{i}", size=16)}</div>'
            f'<p>{"R3-04" if i == 1 else f"R4-{i - 1:02d}"} {lg.name}</p></div>'
        )
    return (f'<body style="margin:0;background:{P["bg"]};color:{P["ink"]};font:13px sans-serif">'
            '<style>.g{display:grid;grid-template-columns:repeat(5,250px);gap:10px;padding:10px}.c p{margin:2px}'
            '.sm{display:flex;gap:8px;align-items:center}canvas{image-rendering:pixelated;width:128px;height:128px}</style>'
            f'<div class="g">{"".join(cells)}</div></body>')


ZOOM_JS = """
async () => {
  for (const cv of document.querySelectorAll('canvas')) {
    const svg = cv.closest('.c').querySelector('.sm svg');
    const s = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    await new Promise(r => { img.onload = r; img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(s); });
    const t = document.createElement('canvas'); t.width = 32; t.height = 32;
    const x = t.getContext('2d'); x.fillStyle = getComputedStyle(document.body).backgroundColor; x.fillRect(0, 0, 32, 32); x.drawImage(img, 0, 0, 32, 32);
    const c = cv.getContext('2d'); c.imageSmoothingEnabled = false; c.drawImage(t, 0, 0, 128, 128);
  }
}
"""


def square_box(box, pad: float = 10) -> str:
    """A square viewBox around an ink box (what a favicon or app tile crops to)."""
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0) + 2 * pad
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return f"{cx - side / 2:.1f} {cy - side / 2:.1f} {side:.1f} {side:.1f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--previews", action="store_true")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    from playwright.sync_api import sync_playwright

    logos = ordered()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        for theme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1320, "height": 900}, device_scale_factor=1)
            page.set_content(sheet(theme, logos))
            page.evaluate(ZOOM_JS)
            page.screenshot(path=str(out / f"sheet-{theme}.png"), full_page=True)
            page.close()
        if args.previews:
            pv = HERE / "preview"
            pv.mkdir(exist_ok=True)
            boxes = {}
            page = browser.new_page(viewport={"width": 512, "height": 512}, device_scale_factor=1)
            for lg in logos:  # pass 1: the ink box of every logo (light and dark unioned, faint shadows ignored)
                box = None
                for theme in ("light", "dark"):
                    page.set_content(f'<body style="margin:0;background:transparent">{svg(lg, PALETTES[theme], size=512)}</body>')
                    img = Image.open(io.BytesIO(page.locator("svg").screenshot(omit_background=True)))
                    b = img.getchannel("A").point(lambda a: 255 if a > 60 else 0).getbbox() or (0, 0, 512, 512)
                    box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
                boxes[lg.slug] = list(box)
            # pass 2: 16 and 32 px previews cropped to a square around the ink, as a real favicon would be drawn
            for i, lg in enumerate(logos, 0):
                vb = square_box(boxes[lg.slug])
                for theme in ("light", "dark"):
                    P = PALETTES[theme]
                    suffix = "" if theme == "light" else "-dark"
                    for size in (16, 32):
                        page.set_content(f'<body style="margin:0;background:transparent"><svg xmlns="http://www.w3.org/2000/svg" '
                                         f'viewBox="{vb}" width="{size}" height="{size}">{lg.draw(P, "pv")}</svg></body>')
                        page.locator("svg").screenshot(path=str(pv / f"{i:02d}-{lg.slug}-{size}{suffix}.png"), omit_background=True)
                    # the silhouette test: one colour, filled, at icon sizes
                    for size in (16, 24, 32):
                        page.set_content(f'<body style="margin:0;background:{P["bg"]}"><svg xmlns="http://www.w3.org/2000/svg" '
                                         f'viewBox="{vb}" width="{size}" height="{size}">{lg.draw(marks3.mono(P), "pm")}</svg></body>')
                        page.locator("svg").screenshot(path=str(pv / f"{i:02d}-{lg.slug}-mono-{size}{suffix}.png"))
            (HERE / "bboxes.json").write_text(json.dumps(boxes, indent=1) + "\n")
            page.close()
        browser.close()
    print(out)


if __name__ == "__main__":
    main()
