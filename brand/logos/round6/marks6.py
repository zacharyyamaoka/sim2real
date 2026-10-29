"""Round 6: the sim2real logo, final. R5-03 Clipped Dither and R5-01 Quantised Silhouette, refined.

Zach, 2026-10-28: "For logo do the clipped dither. Make it center tooth only 1 thick though so exactly
just half of it is pixels. and then for the clipping don't completely round the pixels if more than 50%
of the pixel is showing then draw the entire block. On the quantised silhouette split it evenly as well
so the middle tooth is only 1 pixel thick."

- The split is the gear's vertical centre line, x = cx. Steel to the right, pixels to the left.
- The grid is anchored on that line and its cell is the half-width of a tooth, so the top and bottom
  teeth (which straddle the line) get exactly one pixel column on the digital side.
- No clipped pixels: a block is drawn whole when more than half its area lies inside the gear outline
  (measured on an 8 x 8 sample grid, bore excluded), and dropped otherwise.
"""

from __future__ import annotations

import math
import pathlib
import sys

ROUND5 = pathlib.Path(__file__).resolve().parents[1] / "round5"
sys.path.insert(0, str(ROUND5))

import marks5  # noqa: E402  (puts rounds 4, 3 and 2 on the path)
from geom import f  # noqa: E402
from logos import Logo, defs  # noqa: E402
from marks3 import blocks, gear, kit_defs, steel  # noqa: E402
from marks4 import rect_mask  # noqa: E402
from marks5 import G, density, keep  # noqa: E402


def tooth_half_width(g) -> float:
    """Half the width of a tooth, measured halfway up it: one pixel column fills it exactly."""
    pitch = 2 * math.pi / g.n
    hb = pitch * g.tooth / 2
    ht = hb * g.taper * (g.r_root / g.r_tip)
    return ((g.r_root * math.sin(hb)) + (g.r_tip * math.sin(ht))) / 2


def coverage(g, x0: float, y0: float, cell: float, n: int = 8) -> float:
    hits = 0
    for a in range(n):
        for b in range(n):
            if g.contains(x0 + (a + 0.5) * cell / n, y0 + (b + 0.5) * cell / n):
                hits += 1
    return hits / (n * n)


def half_cells(g, cell):
    """Grid cells left of the split line (x = cx) with more than half their area inside the gear."""
    out = []
    m = int(g.r_tip / cell) + 2
    for i in range(-m, 0):  # columns ending at or before cx
        for j in range(-m, m):
            x0, y0 = g.cx + i * cell, g.cy + j * cell
            if coverage(g, x0, y0, cell) > 0.5:
                out.append((i, j, x0 + cell / 2, y0 + cell / 2))
    return out


def steel_half(uid, g, P) -> str:
    return defs(kit_defs(uid), rect_mask(uid, "keep", g.cx, 612)) + f'<g mask="url(#{uid}-keep)">{steel(uid, g, P)}</g>'


def clipped_dither_whole(P, uid):
    """R6-A: R5-03's dither, whole blocks only, split exactly on the centre line."""
    g = gear(*G)
    cell = tooth_half_width(g)
    x_far = g.cx - g.r_tip
    bs = [(x, y, cell) for i, j, x, y in half_cells(g, cell) if keep(i, j, 0.4 + 0.6 * density(x, g, x_far - cell, g.cx))]
    return steel_half(uid, g, P) + blocks(bs, P, gap=0.12)


def quantised_even(P, uid):
    """R6-B: R5-01's quantised silhouette on the same even split; edge blocks always kept."""
    g = gear(*G)
    cell = tooth_half_width(g)
    x_far = g.cx - g.r_tip
    cells = half_cells(g, cell)
    on = {(i, j) for i, j, _, _ in cells}

    def edge(i, j):
        for di, dj in ((-1, 0), (0, 1), (0, -1)):
            n = (i + di, j + dj)
            if n not in on and coverage(g, g.cx + n[0] * cell, g.cy + n[1] * cell, cell) <= 0.5:
                return True
        return False

    bs = [(x, y, cell) for i, j, x, y in cells if edge(i, j) or keep(i, j, 0.3 + 0.7 * density(x, g, x_far, g.cx))]
    return steel_half(uid, g, P) + blocks(bs, P, gap=0.1)


R6 = [
    Logo("clipped-dither-whole", "Clipped Dither (final)", "R5-03 with whole blocks only, split exactly on the centre line",
         "Exactly half the gear is pixels; the top and bottom teeth are one pixel column on the digital side; every block is whole.",
         clipped_dither_whole, tags=["final"]),
    Logo("quantised-even", "Quantised Silhouette (even)", "R5-01 on the same even split",
         "R5-01's stepped silhouette on the centre-line split: the middle tooth is one pixel thick, blocks whole.",
         quantised_even, tags=["alternative"]),
]
BEFORE = {"clipped-dither-whole": next(lg for lg in marks5.R5 if lg.slug == "clipped-dither"),
          "quantised-even": next(lg for lg in marks5.R5 if lg.slug == "quantised-silhouette")}


# ---------------------------------------------------------------------------------------------
# The toolbar icon: R6-A drawn as a lucide mark (24 grid, stroke 2, currentColor, no fill)
# ---------------------------------------------------------------------------------------------


ICON_CELL = 2


def icon24_paths() -> list[str]:
    """Right half: the gear's outline and bore as strokes. Left half: the same gear's whole-block
    pixels on a 4-unit grid anchored on the centre line, each a 1-unit square that a stroke of 2
    paints as a 3-unit block. WHY 4 units: the round-1 grid rule (a visible gap of one unit at 24)."""
    g = gear(12, 12, 10.5)
    g.r_tip = 10.5
    pitch = 2 * math.pi / g.n
    # right half of the outline: the gear polygon's points from -90 to +90 degrees, in angle order
    pts = [(x, y, math.atan2(y - 12, x - 12)) for x, y in g.polygon(step_deg=3)]
    right = sorted((p for p in pts if -math.pi / 2 <= p[2] <= math.pi / 2), key=lambda p: p[2])
    outline = f"M12 {f(12 - g.r_tip)}" + "".join(f"L{f(x)} {f(y)}" for x, y, _ in right) + f"L12 {f(12 + g.r_tip)}"
    bore = f"M12 {f(12 - g.r_bore)}A{f(g.r_bore)} {f(g.r_bore)} 0 0 1 12 {f(12 + g.r_bore)}"
    # left half: the same gear quantised on a 3-unit grid anchored on the centre line, traced as one
    # stepped outline (a stroke can't fill 1.5-unit pixels; the steps carry the 'pixel' read at 16 px)
    cell = ICON_CELL
    rows = {}
    m = int(11 / cell) + 1
    for j in range(-m, m):
        cols = [i for i in range(-m, 0) if coverage(g, 12 + i * cell, 12 + j * cell, cell) > 0.5]
        if cols:
            rows[j] = min(cols)
    js = sorted(rows)
    step = f"M12 {f(12 + js[0] * cell)}"
    for j in js:
        x = 12 + rows[j] * cell
        step += f"H{f(x)}V{f(12 + (j + 1) * cell)}"
    step += "H12"
    left_bore = f"M12 {f(12 - 2)}H{f(10)}V{f(12 + 2)}H12"
    dots = "M7 7.5h.01M6.5 16.5h.01"
    return [outline + step + left_bore, bore, dots]
