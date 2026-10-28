"""Round 3: twenty sim2real logos from Zach's round-2 favourites, drawn simple enough to be icons.

Zach, 2026-10-28, on round 2: "The dither sweep one is really cool ... something like turning pixeled
and then kinda like going off into pixelated land ... you kinda like leave out certain of the pixels...
I really like the break out one ... similar idea with the view finder and loupe: That one is very
strong ... if you have s2r c2r like visually they start to look very very similar."
And then: "for all of the icons btw, I feel their level of detail is a bit too high. please simplify
if possible so they look good kinda from a silhouette, and smaller. Make sure to show a dark and
light mode for the icons."

So every mark here is built from few, large parts:
- one chunky 8-tooth gear (round 2's had 10 thin teeth);
- pixels as big blocks, about five across the gear (round 2's were 15-20 across);
- flat steel for the real part (one soft gradient and a thick rim; no lathe rings, recess or hub);
- frames drawn thick (bezels, loupe rings, brackets); no screen grid, no glare.

Every mark also draws as a one-colour silhouette (``mono(P)``): the future icon, and the test that
the shape alone still says "gear going digital".
"""

from __future__ import annotations

import math
import pathlib
import sys

ROUND2 = pathlib.Path(__file__).resolve().parents[1] / "round2"
sys.path.insert(0, str(ROUND2))

from geom import GREEN_LIT, RIM, Gear, circle_d, f, pixel_cells  # noqa: E402
from logos import Logo, defs  # noqa: E402
from s2r_type import layout, raster  # noqa: E402

STEEL = ("#D3D6CF", "#8E938B")  # WHY this dark: a paler steel went faint on white at favicon size


def gear(cx: float, cy: float, r: float, rot: float = 0, bore: float = 0.25) -> Gear:
    """The round-3 gear: 8 chunky teeth and a big bore, so it still reads as a gear at 16 px."""
    return Gear(cx, cy, r, n=8, depth=0.26, tooth=0.58, taper=0.74, rot=rot, bore=bore)


def mono(P: dict) -> dict:
    """The one-colour palette: everything in ink (paper on dark), knockouts in the background colour."""
    return P | {"mono": True}


def M(P) -> bool:
    return bool(P.get("mono"))


def rnd(i: int, j: int, k: int = 0) -> float:
    """A repeatable pseudo-random number in [0, 1), so every rebuild draws the same scatter."""
    n = ((i * 73856093) ^ (j * 19349663) ^ (k * 83492791) ^ 0x5BD1E995) & 0xFFFFFFFF
    n = ((n ^ (n >> 15)) * 2246822519) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 3266489917) & 0xFFFFFFFF
    n ^= n >> 16
    return (n & 0xFFFFFF) / 0x1000000


# ---------------------------------------------------------------------------------------------
# The kit
# ---------------------------------------------------------------------------------------------


def kit_defs(uid: str) -> str:
    return (f'<linearGradient id="{uid}-st" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{STEEL[0]}"/>'
            f'<stop offset="1" stop-color="{STEEL[1]}"/></linearGradient>'
            f'<filter id="{uid}-soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="10"/></filter>')


def steel(uid: str, g: Gear, P: dict, shadow: bool = True) -> str:
    """The real gear: flat steel, one soft gradient, a thick rim. In mono, a solid shape."""
    d = g.path() + circle_d(g.cx, g.cy, g.r_bore) if g.r_bore > 1 else g.path()
    if M(P):
        return f'<path d="{d}" fill="{P["ink"]}" fill-rule="evenodd"/>'
    sh = (f'<path d="{d}" transform="translate(6 {f(g.r_tip * 0.08)})" fill="{P["shadow"]}" fill-rule="evenodd" '
          f'opacity="{P["shadow_op"]}" filter="url(#{uid}-soft)"/>') if shadow else ""
    return sh + f'<path d="{d}" fill="url(#{uid}-st)" fill-rule="evenodd" stroke="{RIM}" stroke-width="10" stroke-linejoin="round"/>'


def pix_colour(P: dict, on_screen: bool = False) -> str:
    if M(P):
        return P["ink"]
    return GREEN_LIT if on_screen else P["pix"]


def squares(bs, gap: float = 0.1) -> str:
    """Blocks as one path; each block is (x, y, size) with (x, y) its centre."""
    out = []
    for x, y, s in bs:
        g = s * gap / 2
        out.append(f"M{f(x - s / 2 + g)} {f(y - s / 2 + g)}h{f(s - 2 * g)}v{f(s - 2 * g)}h{f(-(s - 2 * g))}z")
    return "".join(out)


def gear_blocks(g: Gear, cell: float, keep=None) -> list[tuple[float, float, float]]:
    """The gear on a coarse grid anchored at its centre: about five blocks across."""
    out = []
    for i, j in pixel_cells(g, cell):
        x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
        if keep is None or keep(x, y):
            out.append((x, y, cell))
    return out


def blocks(bs, P, on_screen=False, gap=0.1) -> str:
    return f'<path d="{squares(bs, gap)}" fill="{pix_colour(P, on_screen)}"/>' if bs else ""


def frame_rect(x, y, w, h, r, P, *, thick=26) -> str:
    """A thick screen frame: a dark bezel round a dark screen; in mono, just the thick outline."""
    if M(P):
        return (f'<rect x="{f(x + thick / 2)}" y="{f(y + thick / 2)}" width="{f(w - thick)}" height="{f(h - thick)}" rx="{f(r)}" '
                f'fill="none" stroke="{P["ink"]}" stroke-width="{thick}"/>')
    return (f'<rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(r + thick / 2)}" fill="{P["bezel"]}" '
            f'stroke="{P["bezel_edge"]}" stroke-width="3"/>'
            f'<rect x="{f(x + thick)}" y="{f(y + thick)}" width="{f(w - 2 * thick)}" height="{f(h - 2 * thick)}" '
            f'rx="{f(max(2, r - thick / 2))}" fill="{P["screen"]}"/>')


def frame_ink(P) -> str:
    return P["ink"] if M(P) else P["bezel"]


def half_plane(cx, cy, angle_deg, offset) -> str:
    """Everything behind a line through (cx, cy) + offset along angle: the part that is certainly metal."""
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)
    px, py = cx + ux * offset, cy + uy * offset
    L = 3000
    vx, vy = -uy, ux
    pts = [(px + vx * L, py + vy * L), (px - vx * L, py - vy * L), (px - vx * L - ux * L, py - vy * L - uy * L),
           (px + vx * L - ux * L, py + vy * L - uy * L)]
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in pts) + "Z"


def dissolve(uid, g: Gear, P, *, cell, angle, start, spread, drop=0.35, debris=0.5, seed=1, ordered=False, shrink=0.35,
             jitter=0.3, radial=False, shadow=True, on_screen=False) -> str:
    """The real gear breaking up into big blocks.

    Cells past ``start`` (a fraction of the radius along ``angle``) turn into blocks with rising
    probability; some are left out (``drop``), the rest drift up to ``spread`` px along ``angle`` (or
    radially), shrinking; a few throw off a smaller block further out (``debris``). The metal's edge
    is stepped on the same grid, so metal and blocks fit together."""
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    keep, fly = [], []
    for i, j in pixel_cells(g, cell):
        x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
        s = ((x - g.cx) * ux + (y - g.cy) * uy) / g.r_tip
        t = min(1.0, max(0.0, (s - start) / max(1e-6, 1.0 - start)))
        r = ((i + 2 * j) % 3) / 3 + 0.15 if ordered else rnd(i, j, seed)
        if t <= 0 or r >= t * 1.7:
            keep.append((i, j))
            continue
        if rnd(i, j, seed + 1) < drop * t:
            continue  # left out: the gaps he asked for
        dx, dy = (x - g.cx, y - g.cy) if radial else (ux, uy)
        nrm = math.hypot(dx, dy) or 1
        dx, dy = dx / nrm, dy / nrm
        dist = spread * t * (0.45 + 0.55 * rnd(i, j, seed + 2))
        side = (rnd(i, j, seed + 3) - 0.5) * spread * jitter * t
        sz = cell * (1 - shrink * t)
        fly.append((x + dx * dist - dy * side, y + dy * dist + dx * side, sz))
        if rnd(i, j, seed + 4) < debris * t:
            d2 = dist * 1.6 + cell
            fly.append((x + dx * d2 - dy * side * 1.3, y + dy * d2 + dx * side * 1.3, sz * 0.55))
    keep_d = "".join(f"M{f(g.cx + i * cell)} {f(g.cy + j * cell)}h{f(cell)}v{f(cell)}h{f(-cell)}z" for i, j in keep)
    # WHY a mask, not a clipPath: Chrome merges a clipPath's children into one path, so a clockwise cell
    # over a counter-clockwise half-plane winds to zero and punches a hole. Mask shapes always union.
    hub = f'<path d="{circle_d(g.cx, g.cy, g.r_bore + cell * 0.6)}" fill="#fff"/>' if start > 0 else ""
    mask = (f'<mask id="{uid}-keep" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<path d="{keep_d}" fill="#fff"/><path d="{half_plane(g.cx, g.cy, angle, start * g.r_tip)}" fill="#fff"/>{hub}</mask>')
    return f"<defs>{mask}</defs>" + f'<g mask="url(#{uid}-keep)">{steel(uid, g, P, shadow)}</g>' + blocks(fly, P, on_screen)


def loupe_ring(cx, cy, r, P, handle_angle=45, handle_len=86, ring=26, colour=None) -> str:
    a = math.radians(handle_angle)
    hx0, hy0 = cx + (r + ring / 2) * math.cos(a), cy + (r + ring / 2) * math.sin(a)
    hx1, hy1 = cx + (r + handle_len) * math.cos(a), cy + (r + handle_len) * math.sin(a)
    c = colour or frame_ink(P)
    return (f'<path d="M{f(hx0)} {f(hy0)}L{f(hx1)} {f(hy1)}" stroke="{c}" stroke-width="44" stroke-linecap="round"/>'
            f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r + ring / 2)}" fill="none" stroke="{c}" stroke-width="{ring}"/>')


def outside(uid, x, y, w, h) -> str:
    return (f'<clipPath id="{uid}-out"><path d="M-100 -100H612V612H-100Z M{f(x)} {f(y)}V{f(y + h)}H{f(x + w)}V{f(y)}Z" '
            f'clip-rule="evenodd"/></clipPath>')


def inside(uid, x, y, w, h, rx=0, name="in") -> str:
    return f'<clipPath id="{uid}-{name}"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="{f(rx)}"/></clipPath>'


# =============================================================================================
# Dissolve
# =============================================================================================


def dissolve_trail(P, uid):
    """Placed by hand, not scattered: with five blocks across the gear, a random scatter left too few to read."""
    g = gear(190, 292, 168)
    cell = 56
    ang = math.radians(-24)
    ux, uy = math.cos(ang), math.sin(ang)
    start = 0.12
    keep, fly = [], []
    band = []
    for i, j in pixel_cells(g, cell):
        x, y = g.cx + (i + 0.5) * cell, g.cy + (j + 0.5) * cell
        sv = ((x - g.cx) * ux + (y - g.cy) * uy) / g.r_tip
        (band if sv > start else keep).append((sv, i, j, x, y))
    band.sort()
    for k, (sv, i, j, x, y) in enumerate(band):
        t = (sv - start) / (1 - start)
        if k % 4 == 3:
            continue  # every fourth left out
        if t < 0.18 and k % 2 == 0:
            keep.append((sv, i, j, x, y))  # a stepped edge: some near cells stay metal
            continue
        d = 36 + 150 * t
        side = ((k % 3) - 1) * 20 * t
        fly.append((x + ux * d - uy * side, y + uy * d + ux * side, cell * (1 - 0.4 * t)))
    for d, sz, side in ((300, 0.42, -14), (360, 0.32, 18), (412, 0.24, -4)):
        fly.append((g.cx + ux * d - uy * side, g.cy + uy * d + ux * side, cell * sz))
    keep_d = "".join(f"M{f(g.cx + i * cell)} {f(g.cy + j * cell)}h{f(cell)}v{f(cell)}h{f(-cell)}z" for _, i, j, _, _ in keep)
    mask = (f'<mask id="{uid}-keep" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<path d="{keep_d}" fill="#fff"/><path d="{half_plane(g.cx, g.cy, -24, start * g.r_tip)}" fill="#fff"/>'
            f'<path d="{circle_d(g.cx, g.cy, g.r_bore + cell * 0.6)}" fill="#fff"/></mask>')
    return (defs(kit_defs(uid), mask) + f'<g mask="url(#{uid}-keep)">{steel(uid, g, P)}</g>' + blocks(fly, P))


def dither_sweep_2(P, uid):
    g = gear(256, 256, 206)
    return defs(kit_defs(uid)) + dissolve(uid, g, P, cell=70, angle=0, start=-0.05, spread=20, drop=0.0, debris=0.0,
                                          ordered=True, shrink=0.15, jitter=0.0)


def upward_drift(P, uid):
    g = gear(256, 320, 170)
    return defs(kit_defs(uid)) + dissolve(uid, g, P, cell=64, angle=-90, start=0.1, spread=200, drop=0.3, debris=0.6, seed=7, jitter=0.4)


def pixel_wake(P, uid):
    """The real gear rolls out of pixel land, leaving a fading block wake behind it."""
    g = gear(334, 262, 156, rot=8)
    out = [defs(kit_defs(uid))]
    for k, (dx, keepp) in enumerate(((-150, 0.75), (-262, 0.4))):
        ghost = gear(g.cx + dx, g.cy, g.r_tip, rot=8 - 20 * (k + 1))
        bs = [b for idx, b in enumerate(gear_blocks(ghost, 62, keep=lambda x, y: x < g.cx - g.r_tip * 0.75)) if rnd(idx, k, 20) < keepp]
        out.append(blocks(bs, P))
    out.append(steel(uid, g, P))
    return "".join(out)


def exploded_half(P, uid):
    g = gear(232, 256, 186)
    return defs(kit_defs(uid)) + dissolve(uid, g, P, cell=62, angle=0, start=0.0, spread=110, drop=0.2, debris=0.3, seed=11,
                                          radial=True, jitter=0.0, shrink=0.2)


def teeth_to_pixels(P, uid):
    """The body stays metal; each tooth on the right comes off as one block, flying outward."""
    g = gear(226, 262, 190)
    pitch = 2 * math.pi / g.n
    gone = [k for k in range(g.n) if math.cos(k * pitch) > 0.1]
    mask = (f'<mask id="{uid}-m" maskUnits="userSpaceOnUse" x="-100" y="-100" width="712" height="712">'
            f'<rect x="-100" y="-100" width="712" height="712" fill="#fff"/>'
            + "".join(f'<circle cx="{f(g.cx + g.r_tip * math.cos(k * pitch))}" cy="{f(g.cy + g.r_tip * math.sin(k * pitch))}" '
                      f'r="{f(g.r_tip - g.r_root + 16)}" fill="#000"/>' for k in gone) + "</mask>")
    bs = []
    for n_, k in enumerate(gone):
        a = k * pitch
        d = g.r_tip + 30 + 16 * (n_ % 2)
        bs.append((g.cx + d * math.cos(a), g.cy + d * math.sin(a), 58))
        bs.append((g.cx + (d + 66) * math.cos(a + 0.05), g.cy + (d + 66) * math.sin(a + 0.05), 30))
    return defs(kit_defs(uid), mask) + f'<g mask="url(#{uid}-m)">{steel(uid, g, P)}</g>' + blocks(bs, P)


def assemble(P, uid):
    """Read left to right, sim to real: blocks converge from the left into the machined gear."""
    g = gear(318, 256, 172)
    return defs(kit_defs(uid)) + dissolve(uid, g, P, cell=64, angle=180, start=0.1, spread=200, drop=0.3, debris=0.7, seed=9, jitter=0.5)


# =============================================================================================
# Frames: breakout, loupe, phone, viewfinder, window
# =============================================================================================


def breakout_2(P, uid):
    x, y, w, h = 24, 196, 300, 236
    g = gear(316, 210, 168, rot=4)
    T = 28
    sx, sy, sw, sh = x + T, y + T, w - 2 * T, h - 2 * T
    bs = gear_blocks(g, 60, keep=lambda px, py: sx < px < sx + sw and sy < py < sy + sh)
    fly = [(x + w + 40, y + 70, 40), (x + w + 92, y + 40, 26), (x + 110, y - 44, 34)]
    return (defs(kit_defs(uid), outside(uid, x, y, w, h), inside(uid, sx, sy, sw, sh, 6))
            + frame_rect(x, y, w, h, 18, P, thick=T)
            + f'<g clip-path="url(#{uid}-in)">{blocks(bs, P, on_screen=True)}</g>'
            + f'<g clip-path="url(#{uid}-out)">{steel(uid, g, P)}</g>' + blocks(fly, P))


def loupe_2(P, uid):
    g = gear(206, 300, 176, rot=-11)
    lx, ly, lr = 330, 176, 104
    k = 1.5
    gz = gear(lx + (g.cx - lx) * k, ly + (g.cy - ly) * k, g.r_tip * k, rot=-11)
    bs = gear_blocks(gz, 52, keep=lambda px, py: math.hypot(px - lx, py - ly) < lr + 20)
    lens = f'<clipPath id="{uid}-lens"><circle cx="{lx}" cy="{ly}" r="{lr}"/></clipPath>'
    knock = f'<circle cx="{lx}" cy="{ly}" r="{lr}" fill="{P["bg"] if M(P) else P["screen"]}"/>'
    return (defs(kit_defs(uid), lens) + steel(uid, g, P) + knock
            + f'<g clip-path="url(#{uid}-lens)">{blocks(bs, P, on_screen=True)}</g>' + loupe_ring(lx, ly, lr, P, handle_len=70))


def phone_ar(P, uid):
    g = gear(214, 266, 188)
    tx, ty, tw, th, rot = 262, 88, 196, 340, 12
    T = 24
    tcx, tcy = tx + tw / 2, ty + th / 2
    a = math.radians(-rot)
    dx, dy = g.cx - tcx, g.cy - tcy
    lx, ly = tcx + dx * math.cos(a) - dy * math.sin(a), tcy + dx * math.sin(a) + dy * math.cos(a)
    gl = gear(lx, ly, g.r_tip, rot=-rot)
    bs = gear_blocks(gl, 56, keep=lambda px, py: tx + T < px < tx + tw - T and ty + T < py < ty + th - T)
    knock = f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="34" fill="{P["bg"]}"/>' if M(P) else ""
    phone = (knock + frame_rect(tx, ty, tw, th, 22, P, thick=T) + f'<g clip-path="url(#{uid}-in)">{blocks(bs, P, on_screen=True)}</g>')
    return (defs(kit_defs(uid), inside(uid, tx + T, ty + T, tw - 2 * T, th - 2 * T, 8)) + steel(uid, g, P)
            + f'<g transform="rotate({rot} {f(tcx)} {f(tcy)})">{phone}</g>')


def viewfinder_brackets(P, uid):
    g = gear(214, 296, 190)
    x0, y0, x1, y1 = 196, 64, 452, 320
    L = 64
    bs = gear_blocks(g, 64, keep=lambda px, py: x0 < px < x1 and y0 < py < y1)
    br = "".join(f"M{cx_} {cy_ + L * syn}V{cy_}H{cx_ + L * sxn}" for cx_, cy_, sxn, syn in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)))
    # WHY no dark screen inside: filled, the brackets merged with it into one black square at icon size
    return (defs(kit_defs(uid), outside(uid, x0, y0, x1 - x0, y1 - y0), inside(uid, x0, y0, x1 - x0, y1 - y0))
            + f'<g clip-path="url(#{uid}-out)">{steel(uid, g, P)}</g>'
            + f'<g clip-path="url(#{uid}-in)">{blocks(bs, P)}</g>'
            + f'<path d="{br}" fill="none" stroke="{P["ink"]}" stroke-width="28" stroke-linecap="square"/>')


def window_breakout(P, uid):
    x, y, w, h = 24, 112, 304, 300
    tb, T = 58, 24
    g = gear(324, 292, 160, rot=6)
    sx, sy, sw, sh = x + T, y + tb, w - 2 * T, h - tb - T
    bs = gear_blocks(g, 60, keep=lambda px, py: sx < px < sx + sw and sy < py < sy + sh)
    c = frame_ink(P)
    if M(P):
        win = (f'<rect x="{x + T / 2}" y="{y + T / 2}" width="{w - T}" height="{h - T}" rx="18" fill="none" stroke="{c}" stroke-width="{T}"/>'
               f'<rect x="{x}" y="{y}" width="{w}" height="{tb}" rx="20" fill="{c}"/>')
    else:
        win = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="24" fill="{c}" stroke="{P["bezel_edge"]}" stroke-width="3"/>'
               f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="6" fill="{P["screen"]}"/>')
    dots = "".join(f'<circle cx="{x + 34 + 30 * k}" cy="{y + tb / 2}" r="9" fill="{P["bg"] if M(P) else ("#5A615A" if k < 2 else GREEN_LIT)}"/>' for k in range(3))
    fly = [(x + w + 40, y + 110, 38), (x + w + 92, y + 82, 24)]
    return (defs(kit_defs(uid), outside(uid, x, y, w, h), inside(uid, sx, sy, sw, sh, 6)) + win + dots
            + f'<g clip-path="url(#{uid}-in)">{blocks(bs, P, on_screen=True)}</g>'
            + f'<g clip-path="url(#{uid}-out)">{steel(uid, g, P)}</g>' + blocks(fly, P))


def lens_flip(P, uid):
    """The other way round: a block gear on a screen, and the loupe shows the real part."""
    g = gear(220, 286, 180, rot=-11)
    lx, ly, lr = 330, 172, 100
    k = 1.5
    gz = gear(lx + (g.cx - lx) * k, ly + (g.cy - ly) * k, g.r_tip * k, rot=-11)
    tile = "" if M(P) else f'<rect x="28" y="72" width="420" height="412" rx="30" fill="{P["screen"]}"/>'
    lens_bg = P["bg"] if M(P) else ("#ECEEE8" if P["name"] == "light" else "#2A2F2A")
    return (defs(kit_defs(uid), f'<clipPath id="{uid}-lens"><circle cx="{lx}" cy="{ly}" r="{lr}"/></clipPath>') + tile
            + blocks(gear_blocks(g, 60), P, on_screen=True)
            + f'<circle cx="{lx}" cy="{ly}" r="{lr}" fill="{lens_bg}"/><g clip-path="url(#{uid}-lens)">{steel(uid, gz, P, shadow=False)}</g>'
            + loupe_ring(lx, ly, lr, P, handle_len=70, colour=P["ink"]))


# =============================================================================================
# Hybrids
# =============================================================================================


def dither_loupe(P, uid):
    g = gear(184, 306, 150)
    lx, ly, lr = 362, 154, 92
    base = dissolve(uid, g, P, cell=58, angle=-30, start=0.15, spread=150, drop=0.35, debris=0.3, seed=13)
    lens = [(lx - 30, ly - 22, 50), (lx + 30, ly + 30, 50), (lx + 34, ly - 34, 30)]
    knock = f'<circle cx="{lx}" cy="{ly}" r="{lr}" fill="{P["bg"] if M(P) else P["screen"]}"/>'
    return defs(kit_defs(uid)) + base + knock + blocks(lens, P, on_screen=True) + loupe_ring(lx, ly, lr, P, handle_angle=135, handle_len=64)


def screen_dissolve(P, uid):
    """The real gear moves into a screen and, inside it, falls apart into blocks."""
    x, y, w, h = 20, 96, 300, 300
    T = 28
    g = gear(336, 246, 162)
    edge = x + w
    sx, sy, sw, sh = x + T, y + T, w - 2 * T, h - 2 * T
    bs = []
    c = 48
    for i, j in pixel_cells(g, c):
        px, py = g.cx + (i + 0.5) * c, g.cy + (j + 0.5) * c
        if px < edge - T / 2:
            t = min(1, (edge - px) / 180)
            if rnd(i, j, 17) < 0.2 * t:
                continue
            bs.append((px - 100 * t * (0.4 + 0.6 * rnd(i, j, 18)), py + (rnd(i, j, 19) - 0.5) * 50 * t, c * (1 - 0.3 * t)))
    stand = (f'<path d="M{x + w / 2 - 24} {y + h}l-10 44h68l-10-44Z" fill="{frame_ink(P)}"/>'
             f'<rect x="{x + w / 2 - 74}" y="{y + h + 40}" width="148" height="20" rx="10" fill="{frame_ink(P)}"/>')
    return (defs(kit_defs(uid), inside(uid, sx, sy, sw, sh, 6), f'<clipPath id="{uid}-r"><rect x="{edge}" y="-100" width="700" height="712"/></clipPath>')
            + stand + frame_rect(x, y, w, h, 18, P, thick=T)
            + f'<g clip-path="url(#{uid}-in)">{blocks(bs, P, on_screen=True)}</g>'
            + f'<g clip-path="url(#{uid}-r)">{steel(uid, g, P)}</g>')


def frame_spill(P, uid):
    """Inside the viewfinder the gear is blocks; they spill out of the frame's right side and thin away."""
    g = gear(196, 304, 172)
    x0, y0, x1, y1 = 178, 96, 372, 290
    L = 56
    bs = gear_blocks(g, 60, keep=lambda px, py: x0 < px < x1 and y0 < py < y1)
    spill = [(x1 + 46, y0 + 70, 46), (x1 + 104, y0 + 40, 32), (x1 + 50, y0 + 150, 34), (x1 + 112, y0 + 128, 20)]
    br = "".join(f"M{cx_} {cy_ + L * syn}V{cy_}H{cx_ + L * sxn}" for cx_, cy_, sxn, syn in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)))
    return (defs(kit_defs(uid), outside(uid, x0, y0, x1 - x0, y1 - y0), inside(uid, x0, y0, x1 - x0, y1 - y0))
            + f'<g clip-path="url(#{uid}-out)">{steel(uid, g, P)}</g>'
            + f'<g clip-path="url(#{uid}-in)">{blocks(bs, P)}</g>' + blocks(spill, P)
            + f'<path d="{br}" fill="none" stroke="{P["ink"]}" stroke-width="26" stroke-linecap="square"/>')


def ghost_tile(P, uid):
    """Built as an app tile from the start: a tile, the gear half metal, its blocks flying off the tile."""
    t0, t1 = 44, 468
    g = gear(222, 264, 150)
    tile_fill = P["ink"] if M(P) else "#0E100E"
    inner = (P | {"ink": P["bg"]}) if M(P) else (P | {"pix": GREEN_LIT})
    body = dissolve(uid, g, inner, cell=56, angle=-12, start=0.1, spread=200, drop=0.3, debris=0.6, seed=23, shadow=False)
    return defs(kit_defs(uid)) + f'<rect x="{t0}" y="{t0}" width="{t1 - t0}" height="{t1 - t0}" rx="40" fill="{tile_fill}"/>' + body


# =============================================================================================
# Text-led: 's2r', carrying the dissolve so it can't be read as a plain 'c2r'
# =============================================================================================


def s2r_dissolve(P, uid):
    s, two, r = layout("s2r", width=372, cx=296, baseline=354)
    cell = 22
    bs = []
    x0, _, x1, _ = s.bbox()
    for i, j in raster([s], cell, 0, s.y):
        x, y = (i + 0.5) * cell, s.y + (j + 0.5) * cell
        t = min(1, max(0, (x0 + (x1 - x0) * 0.45 - x) / ((x1 - x0) * 0.55)))
        if rnd(i, j, 61) < 0.35 * t:
            continue
        d = 110 * t * (0.5 + 0.5 * rnd(i, j, 62))
        bs.append((x - d, y + (rnd(i, j, 63) - 0.5) * 30 * t, cell * (1 - 0.3 * t)))
    two_c = P["ink"] if M(P) else P["muted"]
    return defs(kit_defs(uid)) + blocks(bs, P, gap=0.08) + two.use(f'fill="{two_c}"') + r.use(f'fill="{P["ink"]}"')


def gear_badge(P, uid):
    g = gear(256, 256, 220, bore=0.0)
    body = dissolve(uid, g, P, cell=62, angle=0, start=0.45, spread=90, drop=0.3, debris=0.4, seed=29)
    s, two, r = layout("s2r", width=190, cx=256, baseline=292)
    rim = "" if M(P) else f' stroke="{RIM}" stroke-width="8"'
    disc = f'<circle cx="256" cy="256" r="118" fill="{P["bg"]}"{rim}/>'
    sc = P["ink"] if M(P) else P["pix"]
    tc = P["ink"] if M(P) else P["muted"]
    return defs(kit_defs(uid)) + body + disc + s.use(f'fill="{sc}"') + two.use(f'fill="{tc}"') + r.use(f'fill="{P["ink"]}"')


def tile_monogram(P, uid):
    t0, t1 = 44, 468
    tile_fill = P["ink"] if M(P) else "#0E100E"
    inner = (P | {"ink": P["bg"]}) if M(P) else (P | {"pix": GREEN_LIT})
    g = gear(324, 186, 112)
    body = dissolve(uid, g, inner, cell=44, angle=200, start=0.1, spread=130, drop=0.3, debris=0.6, seed=37, shadow=False)
    s, two, r = layout("s2r", width=280, cx=210, baseline=420)
    if M(P):
        txt = "".join(gl.use(f'fill="{P["bg"]}"') for gl in (s, two, r))
    else:
        txt = s.use(f'fill="{GREEN_LIT}"') + two.use('fill="#8A8F89"') + r.use('fill="#FBFBF8"')
    return defs(kit_defs(uid)) + f'<rect x="{t0}" y="{t0}" width="{t1 - t0}" height="{t1 - t0}" rx="40" fill="{tile_fill}"/>' + body + txt


R3: list[Logo] = [
    Logo("dissolve-trail", "Dissolve Trail", "the real gear breaks into big blocks that thin out and drift off up-right",
         "His 'turning pixeled and then going off into pixelated land': the gear's right side breaks into blocks, some left out, "
         "the rest drifting away. A gear plus a trail of squares, even as a silhouette.", dissolve_trail, tags=["dissolve"]),
    Logo("dither-sweep-2", "Dither Sweep II", "G06 simplified: metal on the left, big blocks with gaps on the right",
         "His round-2 favourite with the noise taken out: the gear keeps its outline and its right half is a few big blocks with gaps.",
         dither_sweep_2, tags=["dissolve"]),
    Logo("upward-drift", "Upward Drift", "the top of the gear lifting off as blocks",
         "The same break-up going up: the top teeth lift off as blocks and float away.", upward_drift, tags=["dissolve"]),
    Logo("pixel-wake", "Pixel Wake", "the real gear rolls out of pixel land, leaving a block wake",
         "Motion: the real gear rolling right, two fading block ghosts behind it. Real, coming out of the sim.", pixel_wake, tags=["dissolve"]),
    Logo("exploded-half", "Exploded Half", "the right half bursts outward into blocks",
         "Split gear meets dissolve: the right half blown outward into blocks, an exploded view of the twin.", exploded_half, tags=["dissolve"]),
    Logo("teeth-to-pixels", "Teeth to Pixels", "the body stays metal; each right-hand tooth flies off as a block",
         "Only the teeth go: each tooth on the right comes off as one square. The simplest dissolve, and it holds at 16 px.",
         teeth_to_pixels, tags=["dissolve"]),
    Logo("assemble", "Assemble", "read left to right: blocks converge into the machined gear",
         "The dissolve run backwards so it reads sim → real: blocks gathering from the left and becoming the real part.",
         assemble, tags=["dissolve"]),
    Logo("breakout-2", "Breakout II", "the gear smashes out of a thick screen's corner, blocks flying",
         "G11 made bolder: a thick-framed screen, the gear blocky inside it and metal where it smashes out of the corner.",
         breakout_2, tags=["frame"]),
    Logo("loupe-2", "Loupe II", "a heavy loupe over the real gear shows big blocks",
         "G18 simplified: a thick loupe over the teeth, and inside it the same teeth as a few big blocks.", loupe_2, tags=["frame"]),
    Logo("phone-ar", "Phone AR", "a phone held up to the real gear shows its twin in blocks",
         "G14 as a phone: the real gear behind, a thick tilted phone in front, the same gear in blocks on its screen.", phone_ar, tags=["frame"]),
    Logo("viewfinder-brackets", "Viewfinder Brackets", "four thick corner brackets; inside them the gear is blocks",
         "A viewfinder with no device: four brackets, blocks inside, metal outside. The simplest frame, and it holds as a silhouette.",
         viewfinder_brackets, tags=["frame"]),
    Logo("window-breakout", "Window Breakout", "the gear breaks out of an app window's side",
         "Breakout with an app window: a solid title bar, blocks inside, the real gear pushing out the side.", window_breakout, tags=["frame"]),
    Logo("lens-flip", "Lens Flip", "a block gear; the loupe shows the real part",
         "Loupe reversed: the twin is blocks, and looking closely shows the real machined part.", lens_flip, tags=["frame"]),
    Logo("dither-loupe", "Dither Loupe", "the gear breaking into blocks, a loupe on the blocks",
         "Dissolve plus loupe: the gear goes off into blocks, and the loupe follows them to check.", dither_loupe, tags=["hybrid"]),
    Logo("screen-dissolve", "Screen Dissolve", "the real gear enters a screen and falls apart into blocks inside it",
         "Breakout in reverse, plus the dissolve: half the gear is in the room, the half inside the screen breaks into blocks.",
         screen_dissolve, tags=["hybrid"]),
    Logo("frame-spill", "Frame Spill", "inside the viewfinder the gear is blocks; they spill out and thin away",
         "Viewfinder plus dissolve: the blocks can't stay in the frame and leak out of its right side.", frame_spill, tags=["hybrid"]),
    Logo("ghost-tile", "Ghost Tile", "an app tile; the gear half real, its blocks flying off the tile",
         "Built as an app tile from the start: the gear half metal, its blocks escaping over the tile's edge.", ghost_tile, tags=["hybrid", "tile"]),
    Logo("s2r-dissolve", "s2r Dissolve", "the s of s2r breaks into blocks off the front of the word",
         "Text you read at once with its own hook: the s breaks up into blocks drifting off left. A plain c2r can't look like this.",
         s2r_dissolve, tags=["text"]),
    Logo("gear-badge", "Gear Badge", "s2r in the middle of a gear whose right side breaks up",
         "The gear carries the text: s2r in a disc at the centre of a chunky gear that breaks into blocks on its right.", gear_badge, tags=["text"]),
    Logo("tile-monogram", "Tile Monogram", "an app tile: s2r at the bottom, a gear breaking into blocks at the top",
         "App-icon form: the monogram for quick reading, the breaking gear as the hook that tells it from c2r.", tile_monogram, tags=["text", "tile"]),
]
assert len(R3) == 20 and len({lg.slug for lg in R3}) == 20
