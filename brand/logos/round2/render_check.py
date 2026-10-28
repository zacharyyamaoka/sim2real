"""Render every round-2 logo headlessly so it can be LOOKED at, and write the 32 px previews.

    uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round2/render_check.py --out /tmp/s2r-logos

Writes into --out: sheet-<set>-light.png and sheet-<set>-dark.png for the gear set and the s2r set
(every logo at 240 px, plus 32 px beside it, plus the 32 px raster blown up 4x), and, with
--previews, the 32 px PNGs into brand/logos/round2/preview32/ and brand/logos/round2/s2r/preview32/
(NN-<slug>-32.png and NN-<slug>-32-dark.png).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from geom import PALETTES  # noqa: E402
from logos import svg  # noqa: E402

CHROME = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"


def sets() -> dict:
    """{name: (logos best first, output folder)}: the gear logos and the s2r type logos."""
    from scores import SETS

    return SETS


def sheet(theme: str, logos: list) -> str:
    P = PALETTES[theme]
    cells = []
    for i, lg in enumerate(logos, 1):
        cells.append(
            f'<div class="c"><div class="big">{svg(lg, P, uid=f"a{i}", size=240)}</div>'
            f'<div class="sm">{svg(lg, P, uid=f"b{i}", size=32)}<canvas data-i="{i}" width="128" height="128"></canvas></div>'
            f'<p>{i:02d} {lg.name}</p></div>'
        )
    return (
        f'<body style="margin:0;background:{P["bg"]};color:{P["ink"]};font:13px sans-serif">'
        '<style>.g{display:grid;grid-template-columns:repeat(5,250px);gap:10px;padding:10px}.c p{margin:2px}'
        '.sm{display:flex;gap:8px;align-items:center}canvas{image-rendering:pixelated;width:128px;height:128px}</style>'
        f'<div class="g">{"".join(cells)}</div></body>'
    )


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--previews", action="store_true")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        for name, (logos, folder) in sets().items():
            for theme in ("light", "dark"):
                page = browser.new_page(viewport={"width": 1320, "height": 900}, device_scale_factor=1)
                page.set_content(sheet(theme, logos))
                page.evaluate(ZOOM_JS)
                page.screenshot(path=str(out / f"sheet-{name}-{theme}.png"), full_page=True)
                page.close()
        # the ink bounding box of every logo (union of light and dark, faint shadows ignored), so the
        # lockups can sit the mark tight against the wordmark; written next to this file
        import io
        import json

        from PIL import Image

        boxes = {}
        page = browser.new_page(viewport={"width": 512, "height": 512}, device_scale_factor=1)
        for name, (logos, folder) in sets().items():
            boxes[name] = {}
            for lg in logos:
                box = None
                for theme in ("light", "dark"):
                    page.set_content(f'<body style="margin:0;background:transparent">{svg(lg, PALETTES[theme], size=512)}</body>')
                    img = Image.open(io.BytesIO(page.locator("svg").screenshot(omit_background=True)))
                    alpha = img.getchannel("A").point(lambda a: 255 if a > 60 else 0)
                    b = alpha.getbbox() or (0, 0, 512, 512)
                    box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
                boxes[name][lg.slug] = list(box)
        page.close()
        (HERE / "bboxes.json").write_text(json.dumps(boxes, indent=1) + "\n")
        for name, (logos, folder) in sets().items() if args.previews else ():
            pv = folder / "preview32"
            pv.mkdir(parents=True, exist_ok=True)
            page = browser.new_page(viewport={"width": 32, "height": 32}, device_scale_factor=1)
            for i, lg in enumerate(logos, 1):
                for theme in ("light", "dark"):
                    P = PALETTES[theme]
                    page.set_content(f'<body style="margin:0;background:transparent">{svg(lg, P, size=32)}</body>')
                    suffix = "" if theme == "light" else "-dark"
                    page.locator("svg").screenshot(path=str(pv / f"{i:02d}-{lg.slug}-32{suffix}.png"), omit_background=True)
            page.close()
        browser.close()
    print(out)


if __name__ == "__main__":
    main()
