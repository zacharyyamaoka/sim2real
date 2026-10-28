"""The letters 's', '2', 'r' for the round-2 type logos: set type, and the same type on a pixel grid.

Set type is Ubuntu Sans at weight 800, its outlines baked once into ``s2r_glyphs.json`` (run this
file directly to re-bake). The digital versions are those same outlines rasterised onto a square
grid, so the pixel 's' and the smooth 's' are one letter at two resolutions, the way the gear logos
use one gear.

    uv run --no-project --with fonttools python /home/bam/sim2real/brand/logos/round2/s2r_type.py
"""

from __future__ import annotations

import json
import math
import pathlib
import re
from dataclasses import dataclass

HERE = pathlib.Path(__file__).resolve().parent
GLYPHS = HERE / "s2r_glyphs.json"
FONT = "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf"
KERN = {"s2": -10, "2r": -20}  # font units; Ubuntu's own kerning is not applied, so a light hand here


def bake() -> None:
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = instancer.instantiateVariableFont(TTFont(FONT), {"wght": 800, "wdth": 100})
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    out = {"upm": font["head"].unitsPerEm, "glyphs": {}}
    for ch in "s2r":
        name = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[name].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
        out["glyphs"][ch] = {"d": pen.getCommands(), "adv": font["hmtx"][name][0]}
    GLYPHS.write_text(json.dumps(out))
    print(f"baked {GLYPHS}")


def _contours(d: str, steps: int = 6) -> list[list[tuple[float, float]]]:
    """Flatten an absolute M/L/H/V/Q/C/Z path into closed polylines."""
    toks = re.findall(r"[MLHVQCZ]|-?\d*\.?\d+(?:e-?\d+)?", d)
    contours, cur = [], []
    x = y = 0.0
    i = 0
    cmd = ""
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd == "Z":
                if cur:
                    contours.append(cur)
                cur = []
                continue
        nums = lambda k: [float(v) for v in toks[i:i + k]]
        if cmd == "M":
            if cur:
                contours.append(cur)
            x, y = nums(2)
            cur = [(x, y)]
            i += 2
            cmd = "L"
        elif cmd == "L":
            x, y = nums(2)
            cur.append((x, y))
            i += 2
        elif cmd == "H":
            x = nums(1)[0]
            cur.append((x, y))
            i += 1
        elif cmd == "V":
            y = nums(1)[0]
            cur.append((x, y))
            i += 1
        elif cmd == "Q":
            cx, cy, ex, ey = nums(4)
            for k in range(1, steps + 1):
                t_ = k / steps
                cur.append(((1 - t_) ** 2 * x + 2 * (1 - t_) * t_ * cx + t_ ** 2 * ex,
                            (1 - t_) ** 2 * y + 2 * (1 - t_) * t_ * cy + t_ ** 2 * ey))
            x, y = ex, ey
            i += 4
        elif cmd == "C":
            c1x, c1y, c2x, c2y, ex, ey = nums(6)
            for k in range(1, steps + 1):
                t_ = k / steps
                a, b, c, e = (1 - t_) ** 3, 3 * (1 - t_) ** 2 * t_, 3 * (1 - t_) * t_ ** 2, t_ ** 3
                cur.append((a * x + b * c1x + c * c2x + e * ex, a * y + b * c1y + c * c2y + e * ey))
            x, y = ex, ey
            i += 6
        else:
            i += 1
    if cur:
        contours.append(cur)
    return contours


@dataclass
class Glyph:
    ch: str
    d: str  # font units, y down, baseline 0
    x: float  # artboard placement
    y: float  # baseline
    k: float  # scale
    contours: list  # artboard coordinates

    @property
    def transform(self) -> str:
        return f"translate({self.x:.2f} {self.y:.2f}) scale({self.k:.5f})"

    def use(self, attrs: str = "") -> str:
        return f'<path transform="{self.transform}" d="{self.d}" {attrs}/>'

    def bbox(self):
        xs = [p[0] for c in self.contours for p in c]
        ys = [p[1] for c in self.contours for p in c]
        return min(xs), min(ys), max(xs), max(ys)

    def contains(self, px: float, py: float) -> bool:
        wn = 0  # nonzero winding, as TrueType fills
        for c in self.contours:
            n = len(c)
            for i in range(n):
                (x1, y1), (x2, y2) = c[i], c[(i + 1) % n]
                if y1 <= py < y2 or y2 <= py < y1:
                    xi = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                    if xi > px:
                        wn += 1 if y2 > y1 else -1
        return wn != 0


def layout(text: str = "s2r", width: float = 430, cx: float = 256, baseline: float = 340,
           letter_gap: float = 0.0) -> list[Glyph]:
    """Set the word centred on cx at a given total width; returns one Glyph per letter."""
    data = json.loads(GLYPHS.read_text())
    advs = [data["glyphs"][c]["adv"] for c in text]
    kerns = [KERN.get(text[i:i + 2], 0) for i in range(len(text) - 1)]
    # ink width: from the first glyph's left bearing to the last glyph's right edge, roughly the advances
    total_units = sum(advs) + sum(kerns) + letter_gap * (len(text) - 1)
    k = width / total_units
    x = cx - width / 2
    out = []
    for i, ch in enumerate(text):
        g = data["glyphs"][ch]
        cons = [[(x + px * k, baseline + py * k) for px, py in c] for c in _contours(g["d"])]
        out.append(Glyph(ch, g["d"], x, baseline, k, cons))
        x += (advs[i] + (kerns[i] if i < len(kerns) else 0) + letter_gap) * k
    return out


def raster(glyphs: list[Glyph], cell: float, ox: float, oy: float, keep=None) -> set[tuple[int, int]]:
    """Cells on a grid anchored at (ox, oy) whose centres fall inside any glyph."""
    cells = set()
    for g in glyphs:
        x0, y0, x1, y1 = g.bbox()
        for i in range(math.floor((x0 - ox) / cell) - 1, math.ceil((x1 - ox) / cell) + 1):
            for j in range(math.floor((y0 - oy) / cell) - 1, math.ceil((y1 - oy) / cell) + 1):
                cx, cy = ox + (i + 0.5) * cell, oy + (j + 0.5) * cell
                if (keep is None or keep(cx, cy)) and g.contains(cx, cy):
                    cells.add((i, j))
    return cells


if __name__ == "__main__":
    bake()
