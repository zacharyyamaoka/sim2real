"""Round 5: five variants of R4-03 Density Ramp, Zach's pick.

Zach, 2026-10-28: "Make 5 variants of the Density Ramp but make the shape of the pixel better match
the gear shape."

R4-03's dither was a rectangular block field to the left of the gear. Here the dithered side IS the
gear: the same 8-tooth silhouette rendered in pixels, getting denser left to right until it is steel.
The wordmark is untouched; built on round 3's kit (chunky gear, big blocks, flat steel, mono mode).
"""

from __future__ import annotations

import math
import pathlib
import sys

ROUND4 = pathlib.Path(__file__).resolve().parents[1] / "round4"
sys.path.insert(0, str(ROUND4))

import marks4  # noqa: E402  (puts round3 and round2 on the path too)
from geom import circle_d, f  # noqa: E402
from logos import Logo, defs  # noqa: E402
from marks3 import M, blocks, gear, kit_defs, pix_colour, steel  # noqa: E402
from marks4 import rect_mask  # noqa: E402

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
G = (256, 256, 200)  # one gear, centred, for all five


def density(x: float, g, x_far: float, x_solid: float) -> float:
    return max(0.0, min(1.0, (x - x_far) / (x_solid - x_far))) ** 1.3


def keep(i: int, j: int, d: float) -> bool:
    return (BAYER[j % 4][i % 4] + 0.5) / 16 < d


def grid_cells(g, cell, ox, oy, test):
    out = []
    n = int(g.r_tip / cell) + 2
    for i in range(-n, n):
        for j in range(-n, n):
            x, y = ox + (i + 0.5) * cell, oy + (j + 0.5) * cell
            if test(x, y):
                out.append((i, j, x, y))
    return out


def steel_right(uid, g, P, x_solid) -> str:
    return defs(kit_defs(uid), rect_mask(uid, "keep", x_solid, 612)) + f'<g mask="url(#{uid}-keep)">{steel(uid, g, P)}</g>'


def clipped_dither(P, uid):
    """Square pixels on a grid, kept by an ordered dither, and clipped exactly to the gear outline, teeth included."""
    g = gear(*G)
    cell = 30
    x_far, x_solid = g.cx - g.r_tip, g.cx + g.r_tip * 0.1
    bs = [(x, y, cell) for i, j, x, y in grid_cells(g, cell, g.cx, g.cy, lambda x, y: x < x_solid and math.hypot(x - g.cx, y - g.cy) < g.r_tip + cell)
          if keep(i, j, 0.4 + 0.6 * density(x, g, x_far - cell, x_solid))]
    d = g.path() + circle_d(g.cx, g.cy, g.r_bore)
    clip = f'<clipPath id="{uid}-g"><path d="{d}" clip-rule="evenodd"/></clipPath>'
    return steel_right(uid, g, P, x_solid) + defs(clip) + f'<g clip-path="url(#{uid}-g)">{blocks(bs, P, gap=0.12)}</g>'


def polar_dither(P, uid):
    """Pixels on a polar grid: rings and sectors that follow the hub, the body and each tooth."""
    g = gear(*G)
    x_far, x_solid = g.cx - g.r_tip, g.cx + g.r_tip * 0.1
    pitch = 2 * math.pi / g.n
    segs = []
    rings = [(g.r_bore + 6, g.r_bore + 38, 16), (g.r_bore + 44, g.r_root - 8, 24), (g.r_root - 2, g.r_tip, 8)]
    for ri, (r0, r1, n) in enumerate(rings):
        for k in range(n):
            a_mid = 2 * math.pi * (k + 0.5) / n if ri < 2 else k * pitch  # outer ring: one block per tooth
            half = (math.pi / n) * 0.78 if ri < 2 else pitch * 0.58 * 0.36
            xm = g.cx + (r0 + r1) / 2 * math.cos(a_mid)
            if xm >= x_solid:
                continue
            if ri < 2 and not ((BAYER[ri % 4][k % 4] + 0.5) / 16 < 0.35 + 0.65 * density(xm, g, x_far - 20, x_solid)):
                continue
            a0, a1 = a_mid - half, a_mid + half
            p = lambda r, a: f"{f(g.cx + r * math.cos(a))} {f(g.cy + r * math.sin(a))}"
            segs.append(f"M{p(r0, a0)}A{f(r0)} {f(r0)} 0 0 1 {p(r0, a1)}L{p(r1, a1)}A{f(r1)} {f(r1)} 0 0 0 {p(r1, a0)}Z")
    return steel_right(uid, g, P, x_solid) + f'<path d="{"".join(segs)}" fill="{pix_colour(P)}"/>'


def quantised_silhouette(P, uid):
    """The gear's exact silhouette quantised to whole pixels (stepped edge), thinned by the dither toward the left."""
    g = gear(*G)
    cell = 32
    x_far, x_solid = g.cx - g.r_tip, g.cx + g.r_tip * 0.1
    cells = grid_cells(g, cell, g.cx, g.cy, lambda x, y: x < x_solid and g.contains(x, y))
    on = {(i, j) for i, j, _, _ in cells}
    edge = lambda i, j: any(((i + di, j + dj) not in on) and not g.contains(g.cx + (i + di + 0.5) * cell, g.cy + (j + dj + 0.5) * cell)
                            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    # WHY the edge cells always stay: a sparse dither alone lost the left teeth, and with them the gear
    bs = [(x, y, cell) for i, j, x, y in cells if edge(i, j) or keep(i, j, 0.3 + 0.7 * density(x, g, x_far, x_solid))]
    return steel_right(uid, g, P, x_solid) + blocks(bs, P, gap=0.1)


def tooth_pixels(P, uid):
    """Each left-hand tooth is one solid pixel block sitting exactly on the real tooth; the body between is dithered."""
    g = gear(*G)
    cell = 34
    x_far, x_solid = g.cx - g.r_tip, g.cx + g.r_tip * 0.1
    body = [(x, y, cell) for i, j, x, y in grid_cells(g, cell, g.cx, g.cy, lambda x, y: x < x_solid and math.hypot(x - g.cx, y - g.cy) < g.r_root - 6
                                                       and math.hypot(x - g.cx, y - g.cy) > g.r_bore + 4)
            if keep(i, j, 0.2 + 0.8 * density(x, g, x_far, x_solid))]
    pitch = 2 * math.pi / g.n
    teeth = []
    for k in range(g.n):
        a = k * pitch
        rm = (g.r_root + g.r_tip) / 2 - 4
        x, y = g.cx + rm * math.cos(a), g.cy + rm * math.sin(a)
        if x < x_solid - 10:
            teeth.append((x, y, 58))
    return steel_right(uid, g, P, x_solid) + blocks(body, P, gap=0.12) + blocks(teeth, P, gap=0.0)


def outlined_dither(P, uid):
    """Own idea: the whole gear outline stays drawn, and only the fill dithers from pixels into steel."""
    g = gear(*G)
    cell = 30
    x_far, x_solid = g.cx - g.r_tip, g.cx + g.r_tip * 0.1
    bs = [(x, y, cell) for i, j, x, y in grid_cells(g, cell, g.cx, g.cy, lambda x, y: x < x_solid and g.contains(x, y))
          if keep(i, j, density(x, g, x_far, x_solid))]
    d = g.path() + circle_d(g.cx, g.cy, g.r_bore)
    clip = f'<clipPath id="{uid}-g"><path d="{d}" clip-rule="evenodd"/></clipPath>'
    rim = P["ink"] if M(P) else "#2B302A"
    outline = f'<path d="{d}" fill="none" stroke="{rim}" stroke-width="12" stroke-linejoin="round"/>'
    return (steel_right(uid, g, P, x_solid) + defs(clip) + f'<g clip-path="url(#{uid}-g)">{blocks(bs, P, gap=0.12)}</g>' + outline)


REFERENCE = Logo("density-ramp", "Density Ramp", "his pick from round 4, unchanged",
                 "An ordered dither getting denser until it closes into steel: the reference these five vary.", marks4.density_ramp,
                 tags=["reference"])

R5: list[Logo] = [
    Logo("clipped-dither", "Clipped Dither", "square pixels clipped exactly to the gear outline, teeth included",
         "The same dither as R4-03, but only inside the gear: the left half is the gear itself in pixels, cut on its real outline.",
         clipped_dither, tags=["outline"]),
    Logo("polar-dither", "Polar Dither", "pixels on a polar grid: hub ring, body ring, one block per tooth",
         "The pixels follow the gear's own geometry: curved blocks round the hub and body, and each tooth is a block.",
         polar_dither, tags=["polar"]),
    Logo("quantised-silhouette", "Quantised Silhouette", "the gear's exact silhouette in whole pixels, thinning to the left",
         "The gear's outline quantised onto the pixel grid: stepped teeth that read as the same gear, densifying into steel.",
         quantised_silhouette, tags=["quantised"]),
    Logo("tooth-pixels", "Tooth Pixels", "each left tooth is one block sitting on the real tooth; the body is dithered",
         "The pixel teeth line up with the real teeth, so the gear's shape survives even where the body is sparse.",
         tooth_pixels, tags=["teeth"]),
    Logo("outlined-dither", "Outlined Dither", "the gear outline stays drawn; only the fill dithers into steel",
         "Own idea: keep the whole outline, dither only the fill. The silhouette is a complete gear at any size.",
         outlined_dither, tags=["outline"]),
]
