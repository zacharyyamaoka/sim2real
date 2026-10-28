"""Render every proposal at its real toolbar sizes, headlessly, so the marks can be LOOKED at.

    uv run --no-project --with playwright --with svgpathtools --with pillow python /home/bam/sim2real/brand/icons/render_check.py --out /tmp/s2r-renders

Writes three PNGs into --out:
- sheet-1x.png  every mark at 16 / 24 / 48 px at device pixel ratio 1 (the honest 16 px case), dark and light
- sheet-1x-zoom.png  the same image blown up 3x with nearest-neighbour, so each screen pixel is visible
- sheet-app.png  every 256 app icon at 128 and 32 px
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from marks import MARKS, svg24, svg_app  # noqa: E402

CHROME = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"


def sheet_html() -> str:
    rows = []
    for i, m in enumerate(MARKS, 1):
        cells = []
        for bg, fg in (("#262626", "#dadada"), ("#f6f6f6", "#222222")):
            sizes = "".join(
                f'<span style="display:inline-flex;width:{s + 12}px;height:56px;align-items:center;justify-content:center">'
                f'{svg24(m, s)}</span>'
                for s in (16, 24, 48)
            )
            cells.append(f'<div style="background:{bg};color:{fg};display:flex;align-items:center;padding:0 6px">{sizes}</div>')
        rows.append(
            f'<div style="display:flex;gap:0;align-items:stretch;border-bottom:1px solid #ccc">'
            f'<div style="width:150px;font:12px sans-serif;padding:4px">{i:02d} {m.name}</div>{"".join(cells)}</div>'
        )
    return '<body style="margin:0;background:#fff">' + "".join(rows) + "</body>"


def app_html() -> str:
    cells = "".join(
        f'<div style="text-align:center;font:11px sans-serif">{svg_app(m, size=128)}<br>'
        f'{svg_app(m, size=32)} {svg_app(m, "paper", size=32)}<br>{i:02d} {m.name}</div>'
        for i, m in enumerate(MARKS, 1)
    )
    return f'<body style="margin:0;background:#3a3d3a"><div style="display:grid;grid-template-columns:repeat(5,150px);gap:14px;padding:14px;color:#eee">{cells}</div></body>'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={"width": 520, "height": 400}, device_scale_factor=1)
        page.set_content(sheet_html())
        page.screenshot(path=str(out / "sheet-1x.png"), full_page=True)
        page2 = browser.new_page(viewport={"width": 840, "height": 400}, device_scale_factor=1)
        page2.set_content(app_html())
        page2.screenshot(path=str(out / "sheet-app.png"), full_page=True)
        browser.close()
    img = Image.open(out / "sheet-1x.png")
    img.resize((img.width * 3, img.height * 3), Image.NEAREST).save(out / "sheet-1x-zoom.png")
    print(out)


if __name__ == "__main__":
    main()
