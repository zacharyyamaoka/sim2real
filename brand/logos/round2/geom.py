"""Shared drawing parts for the round-2 sim2real logos: one gear, drawn digitally and for real.

Everything returns SVG markup strings on a 512 x 512 artboard. Each logo is drawn twice, for a
light and a dark background, from one palette dict, and every id inside it is prefixed with a
per-logo, per-palette ``uid`` so 40 logos can share one HTML page without their gradients,
clip paths and filters colliding.

Two textures carry the idea:
- **digital**: hard square pixels on the gear's own grid, shaded like pixel art (a lit top-left
  edge, a dark bottom-right edge), green on a dark screen;
- **real**: a smooth machined gear, a grey metal gradient with lathe rings, a dark rim, a bore and
  a soft contact shadow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# BAM Grid Purist (Oct 24 2026): ink, paper, one green; the lit green is that hue for dark grounds.
INK = "#0E100E"
PAPER = "#FBFBF8"
BAM_GREEN = "#2F6F4F"
GREEN_LIT = "#35DE95"

LIGHT = {
    "name": "light",
    "bg": PAPER,
    "ink": INK,
    "line": "#2A2F2A",
    "muted": "#8A8F89",
    "ground": "#E6E8E2",
    "shadow": "#0E100E",
    "shadow_op": 0.22,
    # pixels drawn straight on the page (no screen behind them)
    "pix": BAM_GREEN,
    "pix_hi": "#4C9C73",
    "pix_lo": "#1D4732",
    # pixels on a screen
    "screen": "#0E100E",
    "screen_grid": "#1A211B",
    "spix": GREEN_LIT,
    "spix_hi": "#B9F5D6",
    "spix_lo": "#1F9C64",
    "bezel": "#1B1F1B",
    "bezel_edge": "#0E100E",
    "bezel_hi": "#3A403A",
}

DARK = {
    **LIGHT,
    "name": "dark",
    "bg": "#121412",
    "ink": "#ECEDE8",
    "line": "#C9CCC5",
    "muted": "#8A8F89",
    "ground": "#232823",
    "shadow": "#000000",
    "shadow_op": 0.55,
    "pix": GREEN_LIT,
    "pix_hi": "#B9F5D6",
    "pix_lo": "#1F9C64",
    "screen": "#070807",
    "screen_grid": "#151B16",
    "bezel": "#2A2F2A",
    "bezel_edge": "#4A504A",
    "bezel_hi": "#5A615A",
}

PALETTES = {"light": LIGHT, "dark": DARK}

# Machined steel, shared by both palettes (it reads on paper and on ink).
METAL = ("#F4F5F1", "#C9CDC5", "#8C918A", "#5F645E")
RIM = "#2B302A"


def f(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# ---------------------------------------------------------------------------------------------
# Gear geometry
# ---------------------------------------------------------------------------------------------


@dataclass
class Gear:
    cx: float
    cy: float
    r_tip: float
    n: int = 10
    depth: float = 0.2  # tooth depth as a fraction of r_tip
    tooth: float = 0.5  # tooth share of the pitch at the root
    taper: float = 0.68  # tip width / root width
    rot: float = 0.0  # degrees
    bore: float = 0.26  # bore radius as a fraction of r_tip

    @property
    def r_root(self) -> float:
        return self.r_tip * (1 - self.depth)

    @property
    def r_bore(self) -> float:
        return self.r_tip * self.bore

    def scaled(self, k: float, cx: float | None = None, cy: float | None = None) -> "Gear":
        return Gear(cx if cx is not None else self.cx, cy if cy is not None else self.cy, self.r_tip * k,
                    self.n, self.depth, self.tooth, self.taper, self.rot, self.bore)

    def _angles(self):
        pitch = 2 * math.pi / self.n
        hb = pitch * self.tooth / 2
        ht = hb * self.taper * (self.r_root / self.r_tip)
        r0 = math.radians(self.rot)
        return pitch, hb, ht, r0

    def path(self) -> str:
        """Outline as one closed SVG path (root and tip arcs are true arcs)."""
        pitch, hb, ht, r0 = self._angles()
        R, T = self.r_root, self.r_tip
        cx, cy = self.cx, self.cy

        def p(r, a):
            return f"{f(cx + r * math.cos(a))} {f(cy + r * math.sin(a))}"

        d = []
        for i in range(self.n):
            ac = r0 + i * pitch
            if i == 0:
                d.append(f"M{p(R, ac - hb)}")
            d.append(f"L{p(T, ac - ht)}")
            d.append(f"A{f(T)} {f(T)} 0 0 1 {p(T, ac + ht)}")
            d.append(f"L{p(R, ac + hb)}")
            nxt = ac + pitch
            d.append(f"A{f(R)} {f(R)} 0 0 1 {p(R, nxt - hb)}")
        d.append("Z")
        return "".join(d)

    def polygon(self, step_deg: float = 1.5) -> list[tuple[float, float]]:
        pitch, hb, ht, r0 = self._angles()
        R, T = self.r_root, self.r_tip
        pts = []

        def arc(r, a0, a1):
            n = max(2, int(abs(math.degrees(a1 - a0)) / step_deg))
            for k in range(n + 1):
                a = a0 + (a1 - a0) * k / n
                pts.append((self.cx + r * math.cos(a), self.cy + r * math.sin(a)))

        for i in range(self.n):
            ac = r0 + i * pitch
            arc(T, ac - ht, ac + ht)
            arc(R, ac + hb, ac + pitch - hb)
        return pts

    def contains(self, x: float, y: float, poly=None) -> bool:
        dx, dy = x - self.cx, y - self.cy
        r = math.hypot(dx, dy)
        if r <= self.r_bore or r > self.r_tip:
            return False
        if r <= self.r_root:
            return True
        return _inside(poly or self.polygon(), x, y)


def _inside(poly, x, y) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def circle_d(cx: float, cy: float, r: float) -> str:
    return f"M{f(cx - r)} {f(cy)}a{f(r)} {f(r)} 0 1 0 {f(2 * r)} 0a{f(r)} {f(r)} 0 1 0 {f(-2 * r)} 0Z"


# ---------------------------------------------------------------------------------------------
# Real: a machined metal gear
# ---------------------------------------------------------------------------------------------


def metal_defs(uid: str, angle: float = 0) -> str:
    """Gradients and filters every metal gear in one logo shares."""
    a, b, c, d = METAL
    return (
        f'<linearGradient id="{uid}-metal" x1="0" y1="0" x2="1" y2="1" gradientTransform="rotate({f(angle)} .5 .5)">'
        f'<stop offset="0" stop-color="{a}"/><stop offset=".45" stop-color="{b}"/>'
        f'<stop offset=".8" stop-color="{c}"/><stop offset="1" stop-color="{d}"/></linearGradient>'
        f'<linearGradient id="{uid}-recess" x1="1" y1="1" x2="0" y2="0">'
        f'<stop offset="0" stop-color="{a}"/><stop offset=".5" stop-color="{b}"/><stop offset="1" stop-color="{c}"/></linearGradient>'
        f'<radialGradient id="{uid}-hub" cx=".38" cy=".34" r=".75">'
        f'<stop offset="0" stop-color="{a}"/><stop offset=".55" stop-color="{b}"/><stop offset="1" stop-color="{c}"/></radialGradient>'
        f'<filter id="{uid}-soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>'
    )


def metal_gear(uid: str, g: Gear, P: dict, *, shadow: bool = True, rim: float = 5, rings: bool = True,
               shadow_dy: float | None = None) -> str:
    """A machined gear: drop shadow, gradient body with a rim, a recessed web, a hub and a bore."""
    out = []
    if shadow:
        dy = g.r_tip * 0.07 if shadow_dy is None else shadow_dy
        out.append(
            f'<path d="{g.path()}" transform="translate({f(g.r_tip * 0.03)} {f(dy)})" fill="{P["shadow"]}" '
            f'opacity="{P["shadow_op"]}" filter="url(#{uid}-soft)"/>'
        )
    out.append(
        f'<path d="{g.path()}{circle_d(g.cx, g.cy, g.r_bore)}" fill="url(#{uid}-metal)" fill-rule="evenodd" '
        f'stroke="{RIM}" stroke-width="{f(rim)}" stroke-linejoin="round"/>'
    )
    # recessed web between rim and hub: a darker annulus with its own light from the other side
    r_web_out = g.r_root * 0.8
    r_web_in = g.r_tip * 0.42
    if r_web_out > r_web_in + 6:
        out.append(
            f'<path d="{circle_d(g.cx, g.cy, r_web_out)}{circle_d(g.cx, g.cy, r_web_in)}" fill="url(#{uid}-recess)" '
            f'fill-rule="evenodd" stroke="{RIM}" stroke-opacity=".55" stroke-width="{f(rim * 0.5)}"/>'
        )
        if rings:
            for k in range(1, 4):
                r = r_web_in + (r_web_out - r_web_in) * k / 4
                out.append(
                    f'<circle cx="{f(g.cx)}" cy="{f(g.cy)}" r="{f(r)}" fill="none" stroke="#FFFFFF" '
                    f'stroke-opacity=".28" stroke-width="{f(max(1, rim * 0.3))}"/>'
                )
    out.append(
        f'<path d="{circle_d(g.cx, g.cy, g.r_tip * 0.42)}{circle_d(g.cx, g.cy, g.r_bore)}" fill="url(#{uid}-hub)" '
        f'fill-rule="evenodd" stroke="{RIM}" stroke-opacity=".7" stroke-width="{f(rim * 0.5)}"/>'
    )
    out.append(
        f'<circle cx="{f(g.cx)}" cy="{f(g.cy)}" r="{f(g.r_bore)}" fill="none" stroke="{RIM}" stroke-width="{f(rim)}"/>'
    )
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# Digital: the same gear on a pixel grid
# ---------------------------------------------------------------------------------------------


def pixel_cells(g: Gear, cell: float, ox: float | None = None, oy: float | None = None) -> set[tuple[int, int]]:
    """Grid cells (i, j) whose centre lies in the gear. The grid is anchored at (ox, oy)."""
    ox = g.cx if ox is None else ox
    oy = g.cy if oy is None else oy
    poly = g.polygon()
    n = int(math.ceil(g.r_tip / cell)) + 1
    cells = set()
    i0 = int(math.floor((g.cx - ox) / cell))
    j0 = int(math.floor((g.cy - oy) / cell))
    for i in range(i0 - n, i0 + n + 1):
        for j in range(j0 - n, j0 + n + 1):
            x = ox + (i + 0.5) * cell
            y = oy + (j + 0.5) * cell
            if g.contains(x, y, poly):
                cells.add((i, j))
    return cells


def _runs(cells: set[tuple[int, int]]):
    rows: dict[int, list[int]] = {}
    for i, j in cells:
        rows.setdefault(j, []).append(i)
    for j, xs in rows.items():
        xs.sort()
        start = prev = xs[0]
        for x in xs[1:]:
            if x == prev + 1:
                prev = x
                continue
            yield j, start, prev
            start = prev = x
        yield j, start, prev


def cells_path(cells, cell: float, ox: float, oy: float, gap: float = 0.0) -> str:
    """Cells as one compact path. With a gap each cell is its own inset square (visible pixels)."""
    if not cells:
        return ""
    out = []
    if gap <= 0:
        for j, a, b in _runs(cells):
            out.append(f"M{f(ox + a * cell)} {f(oy + j * cell)}h{f((b - a + 1) * cell)}v{f(cell)}h{f(-(b - a + 1) * cell)}z")
    else:
        s = cell - gap
        for i, j in sorted(cells, key=lambda c: (c[1], c[0])):
            out.append(f"M{f(ox + i * cell + gap / 2)} {f(oy + j * cell + gap / 2)}h{f(s)}v{f(s)}h{f(-s)}z")
    return "".join(out)


def shade_cells(cells: set[tuple[int, int]]):
    """Split cells into lit edge (top-left), shadow edge (bottom-right) and face, pixel-art style."""
    hi, lo, face = set(), set(), set()
    for i, j in cells:
        up_left = (i - 1, j) not in cells or (i, j - 1) not in cells
        down_right = (i + 1, j) not in cells or (i, j + 1) not in cells
        if up_left and not down_right:
            hi.add((i, j))
        elif down_right and not up_left:
            lo.add((i, j))
        elif up_left and down_right:
            (hi if (i + j) % 2 == 0 else lo).add((i, j))
        else:
            face.add((i, j))
    return hi, lo, face


def pixel_gear(g: Gear, P: dict, cell: float, *, on_screen: bool = True, keep=None, gap_ratio: float = 0.14,
               ox: float | None = None, oy: float | None = None) -> str:
    """The digital gear: shaded square pixels. ``keep(x, y)`` filters cells by their centre."""
    ox = g.cx if ox is None else ox
    oy = g.cy if oy is None else oy
    cells = pixel_cells(g, cell, ox, oy)
    if keep is not None:
        cells = {(i, j) for i, j in cells if keep(ox + (i + 0.5) * cell, oy + (j + 0.5) * cell)}
    hi, lo, face = shade_cells(cells)
    k = "s" if on_screen else ""
    gap = cell * gap_ratio
    return (
        f'<path d="{cells_path(face, cell, ox, oy, gap)}" fill="{P[k + "pix"]}"/>'
        f'<path d="{cells_path(hi, cell, ox, oy, gap)}" fill="{P[k + "pix_hi"]}"/>'
        f'<path d="{cells_path(lo, cell, ox, oy, gap)}" fill="{P[k + "pix_lo"]}"/>'
    )


def screen_grid(x: float, y: float, w: float, h: float, cell: float, P: dict, ox: float, oy: float) -> str:
    """Faint pixel grid lines across a screen, aligned with a pixel gear's grid."""
    lines = []
    k0 = math.ceil((x - ox) / cell)
    while ox + k0 * cell < x + w:
        xx = ox + k0 * cell
        lines.append(f"M{f(xx)} {f(y)}v{f(h)}")
        k0 += 1
    k0 = math.ceil((y - oy) / cell)
    while oy + k0 * cell < y + h:
        yy = oy + k0 * cell
        lines.append(f"M{f(x)} {f(yy)}h{f(w)}")
        k0 += 1
    return f'<path d="{"".join(lines)}" stroke="{P["screen_grid"]}" stroke-width="1.2" fill="none"/>'


def wire_gear(g: Gear, colour: str, width: float = 4, spokes: int = 0, construction: bool = True) -> str:
    """A CAD wireframe of the same gear: outline, pitch circle, bore, centre mark, optional spokes."""
    pitch_r = (g.r_root + g.r_tip) / 2
    out = [f'<path d="{g.path()}" fill="none" stroke="{colour}" stroke-width="{f(width)}" stroke-linejoin="round"/>']
    out.append(f'<circle cx="{f(g.cx)}" cy="{f(g.cy)}" r="{f(g.r_bore)}" fill="none" stroke="{colour}" stroke-width="{f(width)}"/>')
    out.append(f'<circle cx="{f(g.cx)}" cy="{f(g.cy)}" r="{f(g.r_tip * 0.42)}" fill="none" stroke="{colour}" stroke-width="{f(width * 0.6)}"/>')
    if construction:
        out.append(
            f'<circle cx="{f(g.cx)}" cy="{f(g.cy)}" r="{f(pitch_r)}" fill="none" stroke="{colour}" '
            f'stroke-width="{f(width * 0.45)}" stroke-dasharray="{f(width * 3)} {f(width * 2.2)}" opacity=".75"/>'
        )
        L = g.r_tip * 1.12
        out.append(
            f'<path d="M{f(g.cx - L)} {f(g.cy)}h{f(2 * L)}M{f(g.cx)} {f(g.cy - L)}v{f(2 * L)}" stroke="{colour}" '
            f'stroke-width="{f(width * 0.45)}" stroke-dasharray="{f(width * 5)} {f(width * 1.6)} {f(width)} {f(width * 1.6)}" opacity=".7"/>'
        )
    for k in range(spokes):
        a = math.radians(g.rot) + 2 * math.pi * k / spokes
        r0, r1 = g.r_tip * 0.42, g.r_root * 0.82
        out.append(
            f'<path d="M{f(g.cx + r0 * math.cos(a))} {f(g.cy + r0 * math.sin(a))}L{f(g.cx + r1 * math.cos(a))} '
            f'{f(g.cy + r1 * math.sin(a))}" stroke="{colour}" stroke-width="{f(width * 0.6)}"/>'
        )
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------------------------


def monitor(uid: str, P: dict, x: float, y: float, w: float, h: float, *, bezel: float = 16, r: float = 18,
            stand: bool = True, stand_x: float | None = None) -> tuple[str, str]:
    """A flat-panel monitor. Returns (body markup, screen clip id); the screen is drawn dark."""
    sx, sy, sw, sh = x + bezel, y + bezel, w - 2 * bezel, h - 2 * bezel
    parts = []
    if stand:
        cx = x + w / 2 if stand_x is None else stand_x
        parts.append(
            f'<path d="M{f(cx - 22)} {f(y + h - 2)}L{f(cx - 30)} {f(y + h + 46)}h60L{f(cx + 22)} {f(y + h - 2)}Z" fill="{P["bezel"]}" '
            f'stroke="{P["bezel_edge"]}" stroke-width="3" stroke-linejoin="round"/>'
            f'<rect x="{f(cx - 78)}" y="{f(y + h + 42)}" width="156" height="16" rx="8" fill="{P["bezel"]}" '
            f'stroke="{P["bezel_edge"]}" stroke-width="3"/>'
        )
    parts.append(
        f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(r)}" fill="{P["bezel"]}" '
        f'stroke="{P["bezel_edge"]}" stroke-width="4"/>'
        f'<rect x="{f(x + 3)}" y="{f(y + 3)}" width="{f(w - 6)}" height="{f(h - 6)}" rx="{f(r - 3)}" fill="none" '
        f'stroke="{P["bezel_hi"]}" stroke-width="2" opacity=".7"/>'
        f'<rect x="{f(sx)}" y="{f(sy)}" width="{f(sw)}" height="{f(sh)}" rx="{f(max(2, r - bezel))}" fill="{P["screen"]}"/>'
    )
    clip = f"{uid}-scr"
    defs = f'<clipPath id="{clip}"><rect x="{f(sx)}" y="{f(sy)}" width="{f(sw)}" height="{f(sh)}" rx="{f(max(2, r - bezel))}"/></clipPath>'
    return defs + "".join(parts), clip


def glare(x: float, y: float, w: float, h: float) -> str:
    """A faint diagonal glass highlight across a screen."""
    return (
        f'<path d="M{f(x)} {f(y)}h{f(w * 0.55)}L{f(x)} {f(y + h * 0.75)}Z" fill="#FFFFFF" opacity=".045"/>'
    )
