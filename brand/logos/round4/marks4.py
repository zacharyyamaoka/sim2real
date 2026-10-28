"""Round 4: ten variants of R3-04 Assemble, Zach's pick.

Zach, 2026-10-28: "Ok I like assemble the most. can you please make like 10 different variants on it
though: I like the sim2real text that perfect keep that but please kinda change how the assemble
looks. I feel like it needs to kinda more progressively change into the gear as one of the options..
like maybe the cut outs should be more blocked? idk make 10 more variants."

The wordmark is untouched (round 2's 'sim2real': pixel 'sim', grey '2', set 'real'); only the mark
changes. Three families:
- progressive: the blocks become the gear by steps (size, resolution, density, teeth);
- blocked cut-outs: square holes, a stepped silhouette, a clean staircase cut;
- composition: from above, radially into the hub, a tight snap-fit.

Built on round 3's kit (chunky 8-tooth gear, big blocks, flat steel, one-colour mode).
"""

from __future__ import annotations

import math
import pathlib
import sys

ROUND3 = pathlib.Path(__file__).resolve().parents[1] / "round3"
sys.path.insert(0, str(ROUND3))

import marks3  # noqa: E402  (puts round2 on the path too)
from geom import circle_d, f, pixel_cells  # noqa: E402
from logos import Logo, defs  # noqa: E402
from marks3 import M, blocks, gear, kit_defs, rnd, steel  # noqa: E402

GREY_BLOCK = "#B4B8B0"  # steel-coloured blocks: halfway between pixel and part


def cells_mask(uid: str, name: str, cells, cell: float, ox: float, oy: float, extra: str = "") -> str:
    """A mask that shows only the given grid cells (plus any extra white shapes)."""
    d = "".join(f"M{f(ox + i * cell)} {f(oy + j * cell)}h{f(cell)}v{f(cell)}h{f(-cell)}z" for i, j in cells)
    return (f'<mask id="{uid}-{name}" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<path d="{d}" fill="#fff"/>{extra}</mask>')


def rect_mask(uid: str, name: str, x0: float, x1: float, y0: float = -100, y1: float = 612) -> str:
    return (f'<mask id="{uid}-{name}" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<rect x="{f(x0)}" y="{f(y0)}" width="{f(x1 - x0)}" height="{f(y1 - y0)}" fill="#fff"/></mask>')


def grey_blocks(bs, P) -> str:
    colour = P["ink"] if M(P) else GREY_BLOCK
    return f'<path d="{marks3.squares(bs, 0.1)}" fill="{colour}"/>' if bs else ""


def slide_in(uid, g, P, *, cell, cut, gap, direction=(-1, 0), base=18):
    """The gear with a clean staircase cut on one side; the cut cells sit in their own rows (or columns),
    slid out along ``direction`` by ``base + gap * k`` (k = cells from the cut), so they visibly slide
    back into place. A cell is cut when its index along the arrival axis is below ``cut(row)``."""
    dx, dy = direction
    # cells of the gear's outline ignoring the bore: a cut block may carry a piece of the hole with it
    cells = pixel_cells(gear(g.cx, g.cy, g.r_tip, rot=g.rot, bore=0.0), cell)
    cut_cells, fly = [], []
    for i, j in cells:
        along, row = (i, j) if dx else (j, i)
        if along < cut(row):
            k = cut(row) - along
            x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
            off = base + gap * (k - 1)
            fly.append((x + dx * off, y + dy * off, cell))
            cut_cells.append((i, j))
    cut_d = "".join(f"M{f(g.cx + i * cell)} {f(g.cy + j * cell)}h{f(cell)}v{f(cell)}h{f(-cell)}z" for i, j in cut_cells)
    # the cut also takes whatever of the gear lies beyond the grid in those rows (tooth tips)
    for i, j in cut_cells:
        along, row = (i, j) if dx else (j, i)
        if along == min(a for (a, r) in (((ii, jj) if dx else (jj, ii)) for ii, jj in cut_cells) if r == row):
            if dx:
                cut_d += f"M{f(g.cx + i * cell - 200)} {f(g.cy + j * cell)}h200v{f(cell)}h-200z"
            else:
                cut_d += f"M{f(g.cx + i * cell)} {f(g.cy + j * cell - 200)}h{f(cell)}v200h{f(-cell)}z"
    # WHY subtract the cut rather than keep the rest: a keep-mask of grid cells also clipped the tooth
    # tips that stick out past the grid, and the gear came out hollow
    mask = (f'<mask id="{uid}-keep" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<rect x="-100" y="-100" width="712" height="712" fill="#fff"/><path d="{cut_d}" fill="#000"/></mask>')
    return defs(mask) + f'<g mask="url(#{uid}-keep)">{steel(uid, g, P)}</g>' + blocks(fly, P)


# =============================================================================================
# Progressive: the blocks become the gear by steps
# =============================================================================================


def size_ramp(P, uid):
    """Blocks grow as they approach: tiny far left, full size at the gear, then the gear's own stepped edge."""
    g = gear(332, 256, 160)
    cell = 54
    cells = pixel_cells(g, cell)
    cut = -1  # columns left of this are blocks, not metal
    keep = [(i, j) for i, j in cells if i >= cut]
    rows_by_col = {}
    for i, j in cells:
        rows_by_col.setdefault(i, []).append(j)
    bs = []
    left_cols = sorted(c for c in rows_by_col if c < cut)
    # the gear's own left columns, in place, then three further columns of shrinking echoes
    for i in left_cols:
        for j in rows_by_col[i]:
            bs.append((g.cx + (i + 0.5) * cell - 14, g.cy + (j + 0.5) * cell, cell * 0.92))
    far = rows_by_col[left_cols[0]] if left_cols else [-1, 0]
    x = g.cx + (left_cols[0] + 0.5) * cell - 14 if left_cols else g.cx - 160
    for k, scale in enumerate((0.7, 0.5, 0.32)):
        x -= cell * (0.62 + 0.55 * scale) + 8
        rows = far if k < 2 else [r for r in far if r in (-1, 0)]
        for j in rows:
            bs.append((x, g.cy + (j + 0.5) * cell * (0.85 + 0.15 * scale), cell * scale))
    del keep
    mask = rect_mask(uid, "keep", g.cx + cut * cell, 612)
    return defs(kit_defs(uid), mask) + f'<g mask="url(#{uid}-keep)">{steel(uid, g, P)}</g>' + blocks(bs, P)


def resolution_ramp(P, uid):
    """Left to right: big green blocks, finer steel-grey blocks, then the smooth machined teeth."""
    g = gear(268, 256, 200)
    x1, x2 = g.cx - g.r_tip * 0.38, g.cx + g.r_tip * 0.12
    coarse = marks3.gear_blocks(g, 66, keep=lambda x, y: x < x1)
    fine = marks3.gear_blocks(g, 33, keep=lambda x, y: x1 <= x < x2)
    arriving = [(36, g.cy - 40, 30), (58, g.cy + 62, 22)]
    return (defs(kit_defs(uid), rect_mask(uid, "smooth", x2, 612)) + f'<g mask="url(#{uid}-smooth)">{steel(uid, g, P)}</g>'
            + grey_blocks(fine, P) + blocks(coarse, P) + blocks(arriving, P))


def density_ramp(P, uid):
    """An ordered dither whose density rises toward the gear until the blocks are solid steel."""
    g = gear(338, 256, 160)
    cell = 34
    x_solid = g.cx - g.r_tip * 0.3
    x_far = 26
    bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
    bs = []
    j_range = range(-4, 4)
    for i in range(-14, 0):
        for j in j_range:
            x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
            if x >= x_solid or x < x_far:
                continue
            inside = g.contains(x, y)
            if not inside and abs(y - g.cy) > g.r_root * 0.82:
                continue
            dens = ((x - x_far) / (x_solid - x_far)) ** 1.4
            if (bayer[j % 4][i % 4] + 0.5) / 16 < dens:
                bs.append((x, y, cell))
    return (defs(kit_defs(uid), rect_mask(uid, "keep", x_solid, 612)) + f'<g mask="url(#{uid}-keep)">{steel(uid, g, P)}</g>'
            + blocks(bs, P, gap=0.12))


def teeth_arriving(P, uid):
    """The left teeth are still on their way: each one a block sliding in from the left toward its socket."""
    g = gear(310, 256, 178)
    pitch = 2 * math.pi / g.n
    gone = [k for k in range(g.n) if math.cos(k * pitch) < -0.1]
    mask = (f'<mask id="{uid}-m" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<rect x="-100" y="-100" width="712" height="712" fill="#fff"/>'
            + "".join(f'<circle cx="{f(g.cx + g.r_tip * math.cos(k * pitch))}" cy="{f(g.cy + g.r_tip * math.sin(k * pitch))}" '
                      f'r="{f(g.r_tip - g.r_root + 16)}" fill="#000"/>' for k in gone) + "</mask>")
    bs = []
    for n_, k in enumerate(gone):
        a = k * pitch
        sx, sy = g.cx + (g.r_root + 26) * math.cos(a), g.cy + (g.r_root + 26) * math.sin(a)
        d = 40 + 70 * n_
        bs.append((sx - d, sy, 56))
        bs.append((sx - d - 64, sy + (12 if n_ % 2 else -12), 28))
    return defs(kit_defs(uid), mask) + f'<g mask="url(#{uid}-m)">{steel(uid, g, P)}</g>' + blocks(bs, P)


# =============================================================================================
# Blocked cut-outs
# =============================================================================================


def square_holes(P, uid):
    """The digital side is punched with square holes, fewer toward the real side; the missing squares arrive from the left."""
    g = gear(318, 256, 184, bore=0.16)
    cell = 42
    holes = []
    for i, j in pixel_cells(g, cell):
        x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
        r = math.hypot(x - g.cx, y - g.cy)
        if r < g.r_bore + cell * 0.5 or r > g.r_root - cell * 0.42:
            continue
        p = (g.cx + g.r_tip * 0.25 - x) / g.r_tip  # 0 toward the right, about 1 at the far left
        if p > 0.15 and (i + j) % 2 == 0 and rnd(i, j, 4) < 0.35 + 0.65 * p:
            holes.append((x, y, p))
    s_ = cell * 0.66
    hole_d = "".join(f"M{f(x - s_ / 2)} {f(y - s_ / 2)}h{f(s_)}v{f(s_)}h{f(-s_)}z" for x, y, _ in holes)
    left = g.cx - g.r_tip
    fly = []
    for k, (x, y, p) in enumerate(sorted(holes, key=lambda h: h[0])[:6]):
        fly.append((left - 28 - 52 * (k % 3) - 18 * (k // 3), y + (k % 2) * 8, s_ * (0.95 - 0.12 * (k % 3))))
    mask = (f'<mask id="{uid}-h" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<rect x="-100" y="-100" width="712" height="712" fill="#fff"/><path d="{hole_d}" fill="#000"/></mask>')
    return defs(kit_defs(uid), mask) + f'<g mask="url(#{uid}-h)">{steel(uid, g, P)}</g>' + blocks(fly, P)


def blocky_steps(P, uid):
    """The gear's own silhouette quantised on its left half (steel steps), smooth on its right."""
    g = gear(290, 256, 196)
    cell = 40
    left = [(i, j) for i, j in pixel_cells(g, cell) if g.cx + (i + 0.5) * cell < g.cx]
    d = "".join(f"M{f(g.cx + i * cell)} {f(g.cy + j * cell)}h{f(cell)}v{f(cell)}h{f(-cell)}z" for i, j in left)
    bore = circle_d(g.cx, g.cy, g.r_bore)
    if M(P):
        stepped = f'<path d="{d}" fill="{P["ink"]}"/><path d="{bore}" fill="{P["bg"]}"/>'
    else:
        stepped = (f'<path d="{d}" fill="url(#{uid}-st)" stroke="#2B302A" stroke-width="8" stroke-linejoin="miter"/>'
                   f'<path d="{d}" fill="url(#{uid}-st)"/><path d="{bore}" fill="{P["bg"]}" stroke="#2B302A" stroke-width="8"/>')
    arriving = [(g.cx - g.r_tip - 70, g.cy - 30, 36), (g.cx - g.r_tip - 128, g.cy + 22, 24), (g.cx - g.r_tip - 170, g.cy - 8, 14)]
    return (defs(kit_defs(uid), rect_mask(uid, "r", g.cx, 612)) + f'<g mask="url(#{uid}-r)">{steel(uid, g, P)}</g>'
            + stepped + blocks(arriving, P))


def stair_cut(P, uid):
    """R3-04 made orderly: a clean staircase cut out of the gear, the cut cells sliding back in along their rows."""
    g = gear(344, 256, 162)
    # a chevron notch: deepest at the middle rows, one cell less on each row outward
    cut = lambda row: {-4: -3, -3: -2, -2: -1, -1: 0, 0: 0, 1: -1, 2: -2, 3: -3}.get(row, -9)
    return defs(kit_defs(uid)) + slide_in(uid, g, P, cell=44, cut=cut, gap=40, direction=(-1, 0), base=26)


# =============================================================================================
# Composition
# =============================================================================================


def vertical_drop(P, uid):
    """The same slide-in from above: columns of blocks dropping into a stepped notch in the gear's top."""
    g = gear(256, 340, 160)
    cut = lambda col: {-4: -3, -3: -2, -2: -1, -1: 0, 0: 0, 1: -1, 2: -2, 3: -3}.get(col, -9)
    return defs(kit_defs(uid)) + slide_in(uid, g, P, cell=44, cut=cut, gap=34, direction=(0, -1), base=24)


def radial_hub(P, uid):
    """Assembly into the hub: the teeth arrive radially, one already seated, each next one further out."""
    g = gear(262, 256, 172)
    pitch = 2 * math.pi / g.n
    order = [0, 1, 7, 2, 6, 3, 5, 4]  # seated on the right first, the left teeth furthest out
    mask = (f'<mask id="{uid}-m" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<rect x="-100" y="-100" width="712" height="712" fill="#fff"/>'
            + "".join(f'<circle cx="{f(g.cx + g.r_tip * math.cos(k * pitch))}" cy="{f(g.cy + g.r_tip * math.sin(k * pitch))}" '
                      f'r="{f(g.r_tip - g.r_root + 16)}" fill="#000"/>' for k in order[2:]) + "</mask>")
    bs = []
    for n_, k in enumerate(order[2:], 1):
        a = k * pitch
        d = g.r_root + 30 + 15 * n_
        bs.append((g.cx + d * math.cos(a), g.cy + d * math.sin(a), 56 - 3 * n_))
    return defs(kit_defs(uid), mask) + f'<g mask="url(#{uid}-m)">{steel(uid, g, P)}</g>' + blocks(bs, P)


def snap_fit(P, uid):
    """Tight: the left half is already the gear in blocks, one block missing and one still sliding in."""
    g = gear(262, 256, 200)
    cell = 66
    cells = pixel_cells(g, cell)
    left = [(i, j) for i, j in cells if i < 0]
    missing = {min(left, key=lambda c: (c[0], abs(c[1] + 0.5)))}
    bs = []
    for i, j in left:
        if (i, j) in missing:
            continue
        x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
        bs.append((x, y, cell))
    for i, j in missing:
        x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
        bs.append((x - 70, y, cell * 0.8))
        bs.append((x - 126, y + 10, cell * 0.4))
    return (defs(kit_defs(uid), rect_mask(uid, "r", g.cx, 612)) + f'<g mask="url(#{uid}-r)">{steel(uid, g, P)}</g>'
            + blocks(bs, P, gap=0.08))


REFERENCE = Logo("assemble", "Assemble", "his pick from round 3, unchanged",
                 "Blocks converging from the left into the machined gear: the reference these ten vary.", marks3.assemble,
                 tags=["reference"])

R4: list[Logo] = [
    Logo("size-ramp", "Size Ramp", "blocks grow as they approach, then the gear's own stepped edge",
         "Progressive by size: tiny blocks far left, bigger ones nearer, full-size blocks in the gear's own columns, then steel.",
         size_ramp, tags=["progressive"]),
    Logo("resolution-ramp", "Resolution Ramp", "big green blocks, finer grey blocks, then smooth teeth",
         "Progressive by resolution: the gear is coarse green pixels on the left, finer steel-grey ones in the middle, machined on the right.",
         resolution_ramp, tags=["progressive"]),
    Logo("density-ramp", "Density Ramp", "an ordered dither getting denser until it is solid steel",
         "Progressive by density: sparse blocks far left, denser toward the gear, until they close up into the part. His dither, run into the gear.",
         density_ramp, tags=["progressive"]),
    Logo("teeth-arriving", "Teeth Arriving", "the left teeth are blocks still sliding in toward their sockets",
         "Blocks as gear parts: each missing tooth on the left is a block on its way to its own socket.",
         teeth_arriving, tags=["progressive"]),
    Logo("square-holes", "Square Holes", "the digital side punched with square holes; the squares arrive from the left",
         "Blocked cut-outs, literally: the gear's left side has square holes, fewer toward the right, and the missing squares are flying in.",
         square_holes, tags=["blocked"]),
    Logo("blocky-steps", "Blocky Steps", "the gear's silhouette quantised in steel steps on the left, smooth on the right",
         "The gear's own outline in steps: the left half is the same steel gear drawn on a coarse grid, the right half machined.",
         blocky_steps, tags=["blocked"]),
    Logo("stair-cut", "Stair Cut", "a clean staircase cut out of the gear; the cut cells slide back in along their rows",
         "R3-04 made orderly: the cut-out is a clean staircase, and the missing cells sit in their rows, sliding back into it.",
         stair_cut, tags=["blocked"]),
    Logo("vertical-drop", "Vertical Drop", "the same slide-in from above: columns of blocks dropping into the gear",
         "Composition: assembly from above, like blocks dropping into place. Taller mark, same idea.", vertical_drop, tags=["composition"]),
    Logo("radial-hub", "Radial Hub", "the teeth arrive radially, each one further out than the last",
         "Composition: assembly into the hub. Two teeth are seated; the rest come in along their own radii, the furthest on the left.",
         radial_hub, tags=["composition"]),
    Logo("snap-fit", "Snap Fit", "tight: the left half is already the gear in blocks, one still sliding in",
         "The tightest gap: the gear is whole in outline, its left half in big blocks, and one block still sliding into its slot.",
         snap_fit, tags=["composition"]),
]
assert len(R4) == 10
