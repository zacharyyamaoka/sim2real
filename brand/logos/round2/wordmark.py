"""The 'sim2real' wordmark used in every round-2 lockup: the same word, digital then real.

'sim' is drawn in square pixels (BAM Grid Purist's block letters, on a 5-cell x-height), '2real'
in Ubuntu Sans Bold outlines. One wordmark for all 20 lockups, so the marks are compared fairly.

The outlines are baked once from the system font into ``wordmark_glyphs.json`` (so a rebuild does
not need fontTools or the font); run this file directly to re-bake them:

    uv run --no-project --with fonttools python /home/bam/sim2real/brand/logos/round2/wordmark.py
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
GLYPHS = HERE / "wordmark_glyphs.json"
FONT = "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf"

# 'sim' on a 5-row x-height; row -2 is the i's dot. '#' = a pixel.
PIXEL_GLYPHS = {
    "s": [".###", "#...", ".##.", "...#", "###."],
    "i": ["#", "#", "#", "#", "#"],
    "m": ["####.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"],
}


def bake() -> None:
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = instancer.instantiateVariableFont(TTFont(FONT), {"wght": 700, "wdth": 100})
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    out = {"upm": font["head"].unitsPerEm, "xheight": font["OS/2"].sxHeight, "glyphs": {}}
    for ch in "2real":
        name = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[name].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))  # y down, baseline at 0
        out["glyphs"][ch] = {"d": pen.getCommands(), "adv": font["hmtx"][name][0]}
    GLYPHS.write_text(json.dumps(out))
    print(f"baked {GLYPHS}")


def wordmark(P: dict, xh: float) -> tuple[str, float, float, float]:
    """Markup with the baseline at y=0 and x from 0. Returns (markup, width, ascent, descent)."""
    data = json.loads(GLYPHS.read_text())
    cell = xh / 5
    gap = cell * 0.12
    parts = []
    x = 0.0
    sizes = {"s": 4, "i": 1, "m": 5}
    pix = []
    for ch in "sim":
        rows = PIXEL_GLYPHS[ch]
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                if v == "#":
                    pix.append((x + c * cell, -xh + r * cell))
        if ch == "i":
            pix.append((x, -xh - 2 * cell))
        x += (sizes[ch] + 1) * cell
    s = cell - gap
    d = "".join(f"M{px + gap / 2:.2f} {py + gap / 2:.2f}h{s:.2f}v{s:.2f}h{-s:.2f}z" for px, py in pix)
    parts.append(f'<path d="{d}" fill="{P["pix"]}"/>')
    x += cell * 0.3
    k = xh / data["xheight"]
    for ch in "2real":
        g = data["glyphs"][ch]
        colour = P["muted"] if ch == "2" else P["ink"]
        parts.append(f'<path transform="translate({x:.2f} 0) scale({k:.5f})" d="{g["d"]}" fill="{colour}"/>')
        x += g["adv"] * k - (cell * 0.15 if ch != "l" else 0)
    ascent = max(xh + 2 * cell, 0.72 * xh / 0.518)  # the i dot vs the font's ascenders (l, 2)
    return "".join(parts), x, ascent, 0.0


if __name__ == "__main__":
    bake()
