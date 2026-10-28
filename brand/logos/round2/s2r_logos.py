"""Round 2, second set: twenty 's2r' TYPE logos. The letters themselves cross from digital to real.

Zach, 2026-10-28: "On the logo please also make 20 variants that use the s2r text. maybe it like
fades from like pixel to real, maybe in one its like in a computer screen, etc."

Same contract as logos.py: ``draw(P, uid) -> svg body`` on a 512 x 512 artboard, light and dark
palettes from geom.py. Digital = the set letter rasterised onto a square grid (s2r_type.raster),
so the pixel 's' and the set 's' are one letter at two resolutions.
"""

from __future__ import annotations

import math

from geom import BAM_GREEN, GREEN_LIT, RIM, Gear, cells_path, circle_d, f, glare, metal_defs, metal_gear, monitor, pixel_gear, shade_cells
from logos import Logo, clip_rect, defs
from s2r_type import Glyph, layout, raster

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def pix(glyphs: list[Glyph], P: dict, cell: float, *, on_screen: bool = False, keep=None, gap_ratio: float = 0.14,
        ox: float = 0.0, oy: float | None = None, shade: bool = True, colour: str | None = None) -> str:
    """The digital letters: the set glyphs rasterised onto a grid anchored on the baseline."""
    oy = glyphs[0].y if oy is None else oy
    cells = raster(glyphs, cell, ox, oy, keep)
    gap = cell * gap_ratio
    k = "s" if on_screen else ""
    if colour:
        return f'<path d="{cells_path(cells, cell, ox, oy, gap)}" fill="{colour}"/>'
    if not shade:
        return f'<path d="{cells_path(cells, cell, ox, oy, gap)}" fill="{P[k + "pix"]}"/>'
    hi, lo, face = shade_cells(cells)
    return (f'<path d="{cells_path(face, cell, ox, oy, gap)}" fill="{P[k + "pix"]}"/>'
            f'<path d="{cells_path(hi, cell, ox, oy, gap)}" fill="{P[k + "pix_hi"]}"/>'
            f'<path d="{cells_path(lo, cell, ox, oy, gap)}" fill="{P[k + "pix_lo"]}"/>')


def ink(g: Glyph, P: dict, colour: str | None = None) -> str:
    return g.use(f'fill="{colour or P["ink"]}"')


def fill(g: Glyph, colour: str) -> str:
    return g.use(f'fill="{colour}"')


def outline(g: Glyph, colour: str, px: float, extra: str = "") -> str:
    """The glyph's outline stroked ``px`` artboard pixels wide (the glyph is drawn scaled by g.k)."""
    return g.use(f'fill="none" stroke="{colour}" stroke-width="{f(px / g.k)}" stroke-linejoin="round" {extra}')


def metal_glyph(uid: str, g: Glyph, P: dict, *, shadow: bool = True, rim: float = 4) -> str:
    """A machined letter: soft shadow, a bevel (light up-left, dark down-right), steel face, dark rim."""
    sw = rim / g.k
    out = []
    if shadow:
        out.append(f'<g transform="translate(5 9)" filter="url(#{uid}-soft)" opacity="{P["shadow_op"]}">{fill(g, P["shadow"])}</g>')
    out.append(f'<g transform="translate(-2 -2)" opacity=".7">{fill(g, "#FFFFFF")}</g>')
    out.append(f'<g transform="translate(2 2.5)">{fill(g, RIM)}</g>')
    out.append(g.use(f'fill="url(#{uid}-metal)" stroke="{RIM}" stroke-width="{f(sw)}" stroke-linejoin="round"'))
    return "".join(out)


def word(width=430, baseline=352, cx=256) -> list[Glyph]:
    return layout("s2r", width=width, cx=cx, baseline=baseline)


def bbox_of(glyphs):
    boxes = [g.bbox() for g in glyphs]
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


# 1 ------------------------------------------------------------------------------------------
def res_ramp(P, uid):
    s, two, r = word(440, 356)
    return pix([s], P, 26) + pix([two], P, 13) + ink(r, P)


# 2 ------------------------------------------------------------------------------------------
def dither_fade(P, uid):
    gl = word(440, 356)
    x0, _, x1, _ = bbox_of(gl)
    cell = 11
    cells = raster(gl, cell, 0, gl[0].y)
    keep = set()
    for i, j in cells:
        v = ((i + 0.5) * cell - x0) / (x1 - x0)
        if (BAYER[j % 4][i % 4] + 0.5) / 16 < 1 - min(1, max(0, (v - 0.08) / 0.7)):
            keep.add((i, j))
    ramp = (f'<linearGradient id="{uid}-ramp" x1="{f(x0)}" x2="{f(x1)}" y1="0" y2="0" gradientUnits="userSpaceOnUse">'
            f'<stop offset=".25" stop-color="#fff" stop-opacity="0"/><stop offset=".8" stop-color="#fff"/></linearGradient>'
            f'<mask id="{uid}-m" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="url(#{uid}-ramp)"/></mask>')
    return (defs(ramp) + f'<g mask="url(#{uid}-m)">' + "".join(ink(g, P) for g in gl) + "</g>"
            + f'<path d="{cells_path(keep, cell, 0, gl[0].y, cell * 0.12)}" fill="{P["pix"]}"/>')


# 3 ------------------------------------------------------------------------------------------
def halftone_fade(P, uid):
    gl = word(440, 356)
    x0, _, x1, _ = bbox_of(gl)
    cell = 12
    cells = raster(gl, cell, 0, gl[0].y)
    dots = []
    for i, j in cells:
        cx, cy = (i + 0.5) * cell, gl[0].y + (j + 0.5) * cell
        v = (cx - x0) / (x1 - x0)
        r = cell * (0.16 + 0.5 * min(1, v / 0.8))
        if v < 0.78:
            dots.append(circle_d(cx, cy, r))
    ramp = (f'<linearGradient id="{uid}-ramp" x1="{f(x0)}" x2="{f(x1)}" y1="0" y2="0" gradientUnits="userSpaceOnUse">'
            f'<stop offset=".55" stop-color="#fff" stop-opacity="0"/><stop offset=".8" stop-color="#fff"/></linearGradient>'
            f'<mask id="{uid}-m" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="url(#{uid}-ramp)"/></mask>')
    return (defs(ramp) + f'<g mask="url(#{uid}-m)">' + "".join(ink(g, P) for g in gl) + "</g>"
            + f'<path d="{"".join(dots)}" fill="{P["pix"]}"/>')


# 4 ------------------------------------------------------------------------------------------
def screen_escape(P, uid):
    x, y, w, h = 20, 116, 352, 238
    mon, clip = monitor(uid, P, x, y, w, h, bezel=16, r=18, stand=True)
    gl = word(372, 292, cx=250)
    sx, sy, sw, sh = x + 16, y + 16, w - 32, h - 32
    outside = f'<clipPath id="{uid}-out"><path d="M0 0H512V512H0Z M{sx} {sy}V{sy + sh}H{sx + sw}V{sy}Z" clip-rule="evenodd"/></clipPath>'
    return (defs(metal_defs(uid), outside) + mon
            + f'<g clip-path="url(#{clip})">{pix(gl, P, 12, on_screen=True)}{glare(sx, sy, sw, sh)}</g>'
            + f'<g clip-path="url(#{uid}-out)">{metal_glyph(uid, gl[2], P)}</g>')


# 5 ------------------------------------------------------------------------------------------
def metal_r(P, uid):
    s, two, r = word(440, 356)
    return defs(metal_defs(uid)) + pix([s], P, 15) + ink(two, P, P["muted"]) + metal_glyph(uid, r, P)


# 6 ------------------------------------------------------------------------------------------
def two_boundary(P, uid):
    s, two, r = word(440, 360)
    # the 2's diagonal, extended, is the edge of the screen: up-left of it is digital, down-right is real
    p1, p2 = (two.x + 300 * two.k, two.y - 470 * two.k), (two.x + 60 * two.k, two.y - 40 * two.k)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    a = (p1[0] - dx * 3, p1[1] - dy * 3)
    b = (p2[0] + dx * 3, p2[1] + dy * 3)
    region = f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}L-600 1200L-600 -600Z"
    panel = f'<rect x="22" y="96" width="468" height="320" rx="26"/>'
    d = (f'<clipPath id="{uid}-scr"><path d="{region}"/></clipPath>'
         f'<clipPath id="{uid}-panel">{panel}</clipPath>')
    return (defs(metal_defs(uid), d)
            + f'<g clip-path="url(#{uid}-panel)"><g clip-path="url(#{uid}-scr)"><rect x="0" y="0" width="512" height="512" fill="{P["screen"]}"/>'
            + pix([s], P, 13, on_screen=True) + "</g></g>"
            + f'<rect x="22" y="96" width="468" height="320" rx="26" fill="none" stroke="{P["line"]}" stroke-width="3" opacity=".35"/>'
            + metal_glyph(uid, r, P) + ink(two, P, GREEN_LIT if P["name"] == "dark" else BAM_GREEN))


# 7 ------------------------------------------------------------------------------------------
def type_wipe(P, uid):
    gl = word(440, 352)
    c = P["pix"]
    left = f'<path d="M256 112H52a26 26 0 0 0-26 26V374a26 26 0 0 0 26 26H256Z" fill="{P["screen"]}"/>'
    return (defs(clip_rect(f"{uid}-r", 256, 0, 256, 512)) + left
            + pix(gl, P, 12, on_screen=True, keep=lambda x, y: x < 256)
            + f'<g clip-path="url(#{uid}-r)">' + "".join(ink(g, P) for g in gl) + "</g>"
            + f'<path d="M256 74V438" stroke="{P["bg"]}" stroke-width="12" stroke-linecap="round"/><path d="M256 74V438" stroke="{c}" stroke-width="6" stroke-linecap="round"/>'
            + f'<circle cx="256" cy="256" r="30" fill="{P["bg"]}" stroke="{c}" stroke-width="6"/>'
            + f'<path d="M248 244l-11 12 11 12M264 244l11 12-11 12" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>')


# 8 ------------------------------------------------------------------------------------------
def wire_solid(P, uid):
    s, two, r = word(410, 360, cx=246)
    ex, ey = 22, -16
    wire = P["pix"]
    pts = s.contours[0]
    links = "".join(f"M{f(px)} {f(py)}l{ex} {ey}" for px, py in pts[:: max(1, len(pts) // 14)])
    out = [defs(metal_defs(uid))]
    out.append(f'<g transform="translate({ex} {ey})" opacity=".6">{outline(s, wire, 2.4)}</g>')
    out.append(f'<path d="{links}" stroke="{wire}" stroke-width="2.4" opacity=".6"/>')
    out.append(s.use(f'fill="none" stroke="{wire}" stroke-width="{f(5 / s.k)}" stroke-linejoin="round"'))
    for g, face in ((two, P["muted"]), (r, None)):
        steps = 16
        side = "#4A4F48"
        for kk in range(steps, 0, -1):
            out.append(f'<g transform="translate({f(ex * kk / steps)} {f(ey * kk / steps)})">{fill(g, side)}</g>')
        out.append(ink(g, P, face) if face else g.use(f'fill="url(#{uid}-metal)" stroke="{RIM}" stroke-width="{f(3 / g.k)}"'))
    return "".join(out)


# 9 ------------------------------------------------------------------------------------------
def glitch_print(P, uid):
    s, two, r = word(440, 356)
    x0, y0, x1, y1 = s.bbox()
    shifts = [0, 9, -6, 14, -11, 4, -3, 10, 0, -8, 5]
    h = (y1 - y0 + 8) / len(shifts)
    clips, slices = [], []
    for i, sh in enumerate(shifts):
        cid = f"{uid}-sl{i}"
        clips.append(f'<clipPath id="{cid}"><rect x="0" y="{f(y0 - 4 + i * h)}" width="512" height="{f(h - 2.2)}"/></clipPath>')
        slices.append(f'<g clip-path="url(#{cid})"><g transform="translate({sh} 0)">'
                      f'<g transform="translate(-5 0)" opacity=".55">{ink(s, P, P["pix_hi"])}</g>{ink(s, P, P["pix"])}</g></g>')
    rough = (f'<filter id="{uid}-bleed" x="-10%" y="-10%" width="120%" height="120%"><feTurbulence type="fractalNoise" baseFrequency=".09" numOctaves="2" seed="3"/>'
             f'<feDisplacementMap in="SourceGraphic" scale="5" xChannelSelector="R" yChannelSelector="G"/></filter>')
    return (defs("".join(clips), rough) + "".join(slices) + ink(two, P, P["muted"])
            + f'<g filter="url(#{uid}-bleed)">{ink(r, P)}</g>')


# 10 -----------------------------------------------------------------------------------------
def stencil_r(P, uid):
    s, two, r = word(430, 356, cx=248)
    x0, y0, x1, y1 = r.bbox()
    px0, py0, px1, py1 = x0 - 26, y0 - 34, x1 + 30, y1 + 30
    bridge_y = y0 + (y1 - y0) * 0.28
    mask = (f'<mask id="{uid}-cut" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512">'
            f'<rect x="{f(px0)}" y="{f(py0)}" width="{f(px1 - px0)}" height="{f(py1 - py0)}" rx="14" fill="#fff"/>'
            f'{fill(r, "#000")}'
            f'<rect x="{f(x0 - 4)}" y="{f(bridge_y)}" width="{f(x1 - x0 + 8)}" height="9" fill="#fff"/></mask>'
            f'<mask id="{uid}-cut2" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512">{fill(r, "#fff")}'
            f'<g transform="translate(2 3)">{fill(r, "#000")}</g><rect x="{f(x0 - 4)}" y="{f(bridge_y)}" width="{f(x1 - x0 + 8)}" height="9" fill="#000"/></mask>')
    plate = (f'<g mask="url(#{uid}-cut)"><rect x="{f(px0)}" y="{f(py0)}" width="{f(px1 - px0)}" height="{f(py1 - py0)}" rx="14" '
             f'fill="url(#{uid}-metal)" stroke="{RIM}" stroke-width="4"/></g>'
             + "".join(f'<circle cx="{f(cx)}" cy="{f(cy)}" r="5" fill="{RIM}" opacity=".7"/>'
                       for cx, cy in ((px0 + 13, py0 + 13), (px1 - 13, py0 + 13), (px0 + 13, py1 - 13), (px1 - 13, py1 - 13))))
    shadow = (f'<g filter="url(#{uid}-soft)" opacity="{P["shadow_op"]}"><rect x="{f(px0 + 4)}" y="{f(py0 + 10)}" width="{f(px1 - px0)}" '
              f'height="{f(py1 - py0)}" rx="14" fill="{P["shadow"]}"/></g>')
    # WHY the shadow sits under the same mask: unmasked, it showed grey through the cut and the r vanished
    edge = f'<g transform="translate(-2 -3)">{fill(r, RIM)}</g>'
    return (defs(metal_defs(uid), mask) + pix([s], P, 15) + ink(two, P, P["muted"])
            + f'<g mask="url(#{uid}-cut)">{shadow}</g>' + plate.replace(f'<g mask="url(#{uid}-cut)">', f'<g mask="url(#{uid}-cut)">', 1)
            + f'<g mask="url(#{uid}-cut2)">{edge}</g>')


# 11 -----------------------------------------------------------------------------------------
def led_matrix(P, uid):
    s, two, r = word(430, 350, cx=262)
    x0, y0, x1, y1 = s.bbox()
    cell = 14
    oy = s.y
    i0, i1 = math.floor((x0 - 22) / cell), math.ceil((x1 + 22) / cell)
    j0, j1 = math.floor((y0 - 22 - oy) / cell), math.ceil((y1 + 22 - oy) / cell)
    on = raster([s], cell, 0, oy)
    lit, dim = [], []
    for i in range(i0, i1):
        for j in range(j0, j1):
            (lit if (i, j) in on else dim).append(circle_d((i + 0.5) * cell, oy + (j + 0.5) * cell, cell * 0.36))
    px0, py0 = i0 * cell - 8, oy + j0 * cell - 8
    pw, ph = (i1 - i0) * cell + 16, (j1 - j0) * cell + 16
    glow = (f'<filter id="{uid}-glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="4" result="b"/>'
            f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    return (defs(glow) + f'<rect x="{f(px0)}" y="{f(py0)}" width="{f(pw)}" height="{f(ph)}" rx="14" fill="{P["screen"]}" stroke="{P["bezel_edge"]}" stroke-width="3"/>'
            + f'<path d="{"".join(dim)}" fill="#1D2B22"/><path d="{"".join(lit)}" fill="{GREEN_LIT}" filter="url(#{uid}-glow)"/>'
            + ink(two, P, P["muted"]) + ink(r, P))


# 12 -----------------------------------------------------------------------------------------
def gear_two(P, uid):
    g = Gear(256, 248, 132, n=10, bore=0.0)
    s = layout("s", width=118, cx=74, baseline=318)[0]
    r = layout("r", width=104, cx=444, baseline=318)[0]
    two = layout("2", width=74, cx=258, baseline=286)[0]
    hub = 64
    out = [defs(metal_defs(uid), clip_rect(f"{uid}-r", 256, 0, 256, 512))]
    out.append(pixel_gear(g, P, 16.5, on_screen=False, keep=lambda x, y: x < 256))
    out.append(f'<g clip-path="url(#{uid}-r)">{metal_gear(uid, g, P)}</g>')
    out.append(f'<circle cx="{g.cx}" cy="{g.cy}" r="{hub}" fill="{P["bg"]}" stroke="{RIM}" stroke-width="5"/>')
    out.append(ink(two, P))
    out.append(pix([s], P, 11))
    out.append(metal_glyph(uid, r, P))
    return "".join(out)


# 13 -----------------------------------------------------------------------------------------
def nameplate(P, uid):
    s, two, r = word(380, 344, cx=262)
    x0, y0, x1, y1 = s.bbox()
    brushed = (f'<pattern id="{uid}-brush" width="512" height="6" patternUnits="userSpaceOnUse">'
               f'<rect width="512" height="3" fill="#fff" opacity=".18"/></pattern>')
    lx0, ly0, lx1, ly1 = x0 - 18, y0 - 18, x1 + 18, y1 + 16
    out = [defs(metal_defs(uid), brushed)]
    out.append(f'<g filter="url(#{uid}-soft)" opacity="{P["shadow_op"]}"><rect x="30" y="150" width="452" height="232" rx="22" fill="{P["shadow"]}"/></g>')
    out.append(f'<rect x="26" y="138" width="460" height="232" rx="22" fill="url(#{uid}-metal)" stroke="{RIM}" stroke-width="5"/>'
               f'<rect x="26" y="138" width="460" height="232" rx="22" fill="url(#{uid}-brush)"/>')
    for cx, cy in ((50, 162), (462, 162), (50, 346), (462, 346)):
        out.append(f'<circle cx="{cx}" cy="{cy}" r="9" fill="url(#{uid}-hub)" stroke="{RIM}" stroke-width="3"/>'
                   f'<path d="M{cx - 5} {cy}h10" stroke="{RIM}" stroke-width="2.5"/>')
    out.append(f'<rect x="{f(lx0)}" y="{f(ly0)}" width="{f(lx1 - lx0)}" height="{f(ly1 - ly0)}" rx="8" fill="{P["screen"]}" stroke="{RIM}" stroke-width="4"/>')
    out.append(pix([s], P, 9.5, on_screen=True))
    for g in (two, r):  # engraved: a light lip below-right, a dark cut
        out.append(f'<g transform="translate(1.6 2)">{ink(g, P, "#FFFFFF")}</g>{ink(g, P, "#3B403A")}')
    return "".join(out)


# 14 -----------------------------------------------------------------------------------------
def s2r_tiles(P, uid):
    t, gap = 140, 14
    xs = [256 - 1.5 * t - gap + k * (t + gap) for k in range(3)]
    y = 256 - t / 2
    s = layout("s", width=t * 0.62, cx=xs[0] + t / 2, baseline=y + t * 0.79)[0]
    two = layout("2", width=t * 0.6, cx=xs[1] + t / 2, baseline=y + t * 0.84)[0]
    r = layout("r", width=t * 0.52, cx=xs[2] + t / 2 + 4, baseline=y + t * 0.79)[0]
    tile_ink = "#0E100E" if P["name"] == "light" else "#ECEDE8"
    tile_on = "#FBFBF8" if P["name"] == "light" else "#0E100E"
    out = [defs(metal_defs(uid))]
    out.append(f'<rect x="{f(xs[0])}" y="{f(y)}" width="{t}" height="{t}" rx="6" fill="{P["screen"]}" stroke="{P["bezel_edge"]}" stroke-width="3"/>')
    out.append(pix([s], P, 8.5, on_screen=True))
    out.append(f'<rect x="{f(xs[1])}" y="{f(y)}" width="{t}" height="{t}" rx="6" fill="{tile_ink}"/>{ink(two, P, tile_on)}')
    out.append(f'<g filter="url(#{uid}-soft)" opacity="{P["shadow_op"]}"><rect x="{f(xs[2] + 3)}" y="{f(y + 9)}" width="{t}" height="{t}" rx="6" fill="{P["shadow"]}"/></g>'
               f'<rect x="{f(xs[2])}" y="{f(y)}" width="{t}" height="{t}" rx="6" fill="url(#{uid}-metal)" stroke="{RIM}" stroke-width="4"/>')
    out.append(f'<g transform="translate(1.4 1.8)">{ink(r, P, "#FFFFFF")}</g>{ink(r, P, "#2B302A")}')
    return "".join(out)


# 15 -----------------------------------------------------------------------------------------
def mesh_s(P, uid):
    s, two, r = word(440, 356)
    pts = s.contours[0]
    low = pts[:: max(1, len(pts) // 22)]
    clip = f'<clipPath id="{uid}-low"><path d="M' + "L".join(f"{f(x)} {f(y)}" for x, y in low) + 'Z"/></clipPath>'
    x0, y0, x1, y1 = s.bbox()
    side = 24
    tris = []
    lo, mid, hi = P["pix_lo"], P["pix"], P["pix_hi"]

    def mix(c1, c2, t):
        a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(a[q] + (b[q] - a[q]) * t):02X}" for q in range(3))

    hgt = side * math.sqrt(3) / 2
    idx = 0
    for row in range(int((y1 - y0) / hgt) + 3):
        yy = y0 - hgt + row * hgt
        off = (row % 2) * side / 2
        for col in range(int((x1 - x0) / side) + 4):
            xx = x0 - side + col * side + off
            for tri in (((xx, yy), (xx + side, yy), (xx + side / 2, yy + hgt)),
                        ((xx + side, yy), (xx + side * 1.5, yy + hgt), (xx + side / 2, yy + hgt))):
                idx += 1
                light = min(1, max(0, 0.55 - 0.4 * ((tri[0][0] - x0) / (x1 - x0) + (tri[0][1] - y0) / (y1 - y0)) / 2
                                   + 0.22 * math.sin(idx * 2.399)))
                colour = mix(lo, mid, light * 2) if light < 0.5 else mix(mid, hi, (light - 0.5) * 2)
                tris.append(f'<path d="M{f(tri[0][0])} {f(tri[0][1])}L{f(tri[1][0])} {f(tri[1][1])}L{f(tri[2][0])} {f(tri[2][1])}Z" fill="{colour}"/>')
    return (defs(metal_defs(uid), clip) + f'<g clip-path="url(#{uid}-low)" stroke="{P["pix_lo"]}" stroke-width="1.4" stroke-linejoin="round">{"".join(tris)}</g>'
            + ink(two, P, P["muted"]) + metal_glyph(uid, r, P))


# 16 -----------------------------------------------------------------------------------------
def pixel_shadow_type(P, uid):
    gl = word(420, 342, cx=248)
    return _shifted_pix(gl, P, 10, 20, 18) + "".join(ink(g, P) for g in gl)


def _shifted_pix(gl, P, cell, dx, dy):
    moved = [Glyph(g.ch, g.d, g.x + dx, g.y + dy, g.k, [[(x + dx, y + dy) for x, y in c] for c in g.contours]) for g in gl]
    return pix(moved, P, cell, oy=moved[0].y, shade=False, gap_ratio=0.16)


# 17 -----------------------------------------------------------------------------------------
def vector_handles(P, uid):
    s, two, r = word(440, 356)
    # the 's' as its own font outline: on-curve points, off-curve control points, handles
    import re as _re
    toks = _re.findall(r"[MLHVQCZ]|-?\d*\.?\d+", s.d)
    on, off, handles = [], [], []
    i, cmd, last = 0, "", (0.0, 0.0)
    T = lambda x, y: (s.x + x * s.k, s.y + y * s.k)
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            continue
        if cmd in ("M", "L"):
            last = (float(toks[i]), float(toks[i + 1]))
            on.append(T(*last))
            i += 2
        elif cmd == "Q":
            c = (float(toks[i]), float(toks[i + 1]))
            e = (float(toks[i + 2]), float(toks[i + 3]))
            off.append(T(*c))
            handles.append((T(*last), T(*c), T(*e)))
            on.append(T(*e))
            last = e
            i += 4
        else:
            i += 1
    x0, y0, x1, y1 = s.bbox()
    bp = (x0 - 22, y0 - 26, x1 + 22, y1 + 22)
    c = GREEN_LIT
    grid = "".join(f"M{f(bp[0])} {f(yy)}H{f(bp[2])}" for yy in range(int(bp[1]) + 12, int(bp[3]), 16))
    grid += "".join(f"M{f(xx)} {f(bp[1])}V{f(bp[3])}" for xx in range(int(bp[0]) + 12, int(bp[2]), 16))
    out = [f'<rect x="{f(bp[0])}" y="{f(bp[1])}" width="{f(bp[2] - bp[0])}" height="{f(bp[3] - bp[1])}" rx="12" fill="{P["screen"]}"/>'
           f'<path d="{grid}" stroke="{P["screen_grid"]}" stroke-width="1.5"/>']
    out.append(s.use(f'fill="{c}" fill-opacity=".14" stroke="{c}" stroke-width="{f(2.6 / s.k)}"'))
    out.append('<path d="' + "".join(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}L{f(e[0])} {f(e[1])}" for a, b, e in handles)
               + f'" fill="none" stroke="{c}" stroke-width="1.4" opacity=".7"/>')
    out.append('<path d="' + "".join(circle_d(x, y, 3) for x, y in off) + f'" fill="{P["screen"]}" stroke="{c}" stroke-width="1.6"/>')
    out.append('<path d="' + "".join(f"M{f(x - 3.4)} {f(y - 3.4)}h6.8v6.8h-6.8z" for x, y in on) + f'" fill="{c}"/>')
    out.append(ink(two, P, P["muted"]) + ink(r, P))
    return "".join(out)


# 18 -----------------------------------------------------------------------------------------
def subpixel(P, uid):
    s, two, r = word(430, 350, cx=262)
    x0, y0, x1, y1 = s.bbox()
    cell = 15
    oy = s.y
    on = raster([s], cell, 0, oy)
    i0, i1 = math.floor((x0 - 18) / cell), math.ceil((x1 + 18) / cell)
    j0, j1 = math.floor((y0 - 18 - oy) / cell), math.ceil((y1 + 18 - oy) / cell)
    bars = {"#FF3B30": [], "#34C759": [], "#2F7BFF": []}
    dimbars = []
    bw = cell / 3
    for i in range(i0, i1):
        for j in range(j0, j1):
            for q, colour in enumerate(bars):
                x = i * cell + q * bw + 0.8
                y = oy + j * cell + 1
                rect = f"M{f(x)} {f(y)}h{f(bw - 1.6)}v{f(cell - 2)}h{f(-(bw - 1.6))}z"
                (bars[colour] if (i, j) in on else dimbars).append(rect)
    panel = (f'<rect x="{f(i0 * cell - 8)}" y="{f(oy + j0 * cell - 8)}" width="{f((i1 - i0) * cell + 16)}" height="{f((j1 - j0) * cell + 16)}" '
             f'rx="12" fill="#050605" stroke="{P["bezel_edge"]}" stroke-width="3"/>')
    return (panel + f'<path d="{"".join(dimbars)}" fill="#141814"/>'
            + "".join(f'<path d="{"".join(v)}" fill="{k}"/>' for k, v in bars.items())
            + ink(two, P, P["muted"]) + ink(r, P))


# 19 -----------------------------------------------------------------------------------------
def mirror_line(P, uid):
    gl = word(420, 262)
    mirror = 276
    fade = (f'<linearGradient id="{uid}-fade" x1="0" y1="{mirror}" x2="0" y2="{mirror + 200}" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="#fff" stop-opacity=".75"/><stop offset=".8" stop-color="#fff" stop-opacity="0"/></linearGradient>'
            f'<mask id="{uid}-m" maskUnits="userSpaceOnUse" x="0" y="{mirror}" width="512" height="{512 - mirror}"><rect x="0" y="{mirror}" width="512" height="{512 - mirror}" fill="url(#{uid}-fade)"/></mask>')
    flipped = "".join(metal_glyph(uid, g, P, shadow=False) for g in gl)
    return (defs(metal_defs(uid), fade) + pix(gl, P, 11)
            + f'<path d="M30 {mirror - 4}H482" stroke="{P["line"]}" stroke-width="3" stroke-linecap="round" opacity=".45"/>'
            + f'<g mask="url(#{uid}-m)"><g transform="translate(0 {2 * mirror}) scale(1 -1)">{flipped}</g></g>')


# 20 -----------------------------------------------------------------------------------------
def circuit_s(P, uid):
    s, two, r = word(440, 356)
    trace, pad, board = "#9BE7BF", "#DADDD6", "#2F6F4F"
    pts = s.contours[0]
    a, b = pts[0], pts[len(pts) // 2]
    bronze = (f'<linearGradient id="{uid}-bz" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E7B77E"/>'
              f'<stop offset=".5" stop-color="#B07A43"/><stop offset="1" stop-color="#6E4724"/></linearGradient>'
              f'<filter id="{uid}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7"/>'
              f'<feColorMatrix values="0 0 0 0 .1  0 0 0 0 .06  0 0 0 0 .02  0 0 0 -1.4 1.05"/></filter>'
              f'<clipPath id="{uid}-s"><path transform="{s.transform}" d="{s.d}"/></clipPath>'
              f'<clipPath id="{uid}-rc"><path transform="{r.transform}" d="{r.d}"/></clipPath>')
    x0, y0, x1, y1 = r.bbox()
    sx0, sy0, sx1, sy1 = s.bbox()
    vias = "".join(circle_d(sx0 + (sx1 - sx0) * u, sy0 + (sy1 - sy0) * v, 4.5) for u, v in ((.3, .18), (.72, .5), (.3, .82)))
    return (defs(metal_defs(uid), bronze)
            + s.use(f'fill="{board}" stroke="#1B3D2C" stroke-width="{f(5 / s.k)}"')
            + f'<g clip-path="url(#{uid}-s)">{outline(s, trace, 14, 'opacity=".9"')}'
            + s.use(f'fill="none" stroke="{board}" stroke-width="{f(7 / s.k)}"') + "</g>"
            + f'<path d="{circle_d(a[0], a[1], 9)}{circle_d(b[0], b[1], 9)}" fill="{pad}" stroke="{trace}" stroke-width="3"/>'
            + f'<path d="{vias}" fill="{pad}"/>'
            + ink(two, P, P["muted"])
            + f'<g filter="url(#{uid}-soft)" opacity="{P["shadow_op"]}" transform="translate(5 9)">{ink(r, P, P["shadow"])}</g>'
            + r.use(f'fill="url(#{uid}-bz)" stroke="#4A2F17" stroke-width="{f(4 / r.k)}"')
            + f'<g clip-path="url(#{uid}-rc)"><rect x="{f(x0)}" y="{f(y0)}" width="{f(x1 - x0)}" height="{f(y1 - y0)}" filter="url(#{uid}-grain)" opacity=".55"/></g>')


def _soft(uid):  # the blur every metal letter's shadow uses (metal_defs carries it; plain marks need it too)
    return f'<filter id="{uid}-soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>'


S2R: list[Logo] = [
    Logo("res-ramp", "Res Ramp", "a coarse pixel s, a finer pixel 2, a set r",
         "The word sharpens as you read it: a coarse pixel s, a finer pixel 2, a set r. Digital to real in three steps.", res_ramp),
    Logo("dither-fade", "Dither Fade", "an ordered dither across the word, pixels to set type",
         "s2r dissolves from dithered pixels on the left into solid set type on the right; one continuous fade.", dither_fade),
    Logo("halftone-fade", "Halftone Fade", "halftone dots growing into solid type",
         "Dots grow along the word until they merge into the printed r: sampled to solid.", halftone_fade),
    Logo("screen-escape", "Screen Escape", "s2r in pixels on a monitor, the r escaping into the world in metal",
         "The word on a monitor, and the r walking off the screen as a machined letter. His 'in a computer screen' idea.",
         screen_escape, develops_09=True),
    Logo("metal-r", "Metal r", "pixel s, plain 2, machined r",
         "The plainest version of the idea: a pixel s, a quiet 2, and an r machined from steel.", metal_r),
    Logo("two-boundary", "2 Boundary", "the 2's diagonal is the edge of the screen",
         "The 2 is the border: up-left of its diagonal is a screen with a pixel s, down-right is the real world with a metal r.",
         two_boundary, develops_09=True),
    Logo("type-wipe", "Type Wipe", "a compare slider across the word, on the 2",
         "A compare slider wipes the word: pixels on a screen to the left of the handle, set type to the right. The 2 sits under the handle.",
         type_wipe, develops_09=True),
    Logo("wire-solid", "Wire / Solid", "a wireframe s, extruded solid 2 and r",
         "3D: the s is a wireframe extrusion, the 2 and r are solid extruded letters, the r in steel.", wire_solid),
    Logo("glitch-print", "Glitch / Print", "a scanline-glitched s beside a printed r",
         "The s is a screen glitch (shifted scanlines, a ghosted copy); the r is ink on paper, with a printed edge.", glitch_print),
    Logo("stencil-r", "Stencil r", "pixel s, laser-cut stencil r in a steel plate",
         "The r is cut through a steel plate as a stencil, with a bridge: a made, physical letter next to a pixel s.", stencil_r),
    Logo("led-matrix", "LED Matrix", "an s on a dot-matrix LED panel, 2r in type",
         "The s lights up on a round-LED dot-matrix panel, the dark LEDs still visible; 2r is plain type.", led_matrix),
    Logo("gear-two", "Gear 2", "the 2 sits in the hub of a half-pixel, half-metal gear",
         "Ties the two sets together: the 2 lives in the hub of the round-2 gear, between a pixel s and a metal r.", gear_two),
    Logo("nameplate", "Nameplate", "an engraved steel nameplate with the s on an inset LCD",
         "A machine's nameplate: 2r engraved into brushed steel, the s on a little inset LCD. Industrial, with real hardware in it.",
         nameplate),
    Logo("s2r-tiles", "s2r Tiles", "three BAM tiles: a screen s, an ink 2, a steel r",
         "The BAM lockup's own form (B-A-M tiles) applied to s-2-r: a screen tile, an ink tile, a steel tile.", s2r_tiles),
    Logo("mesh-s", "Mesh s", "a low-poly mesh s, a machined r",
         "The s as a faceted render mesh with a low-poly outline, the r machined: digital as triangles, like objectdb.", mesh_s),
    Logo("pixel-shadow-type", "Pixel Shadow", "set type casting a pixel shadow",
         "s2r in solid type with its twin as a green pixel drop shadow: the same word, cast digitally.", pixel_shadow_type),
    Logo("vector-handles", "Vector Handles", "the s as its own font outline with control points; 2r set",
         "The s as its source file: the font's real outline, control points and handles on a dark grid. 2r is the printed result.",
         vector_handles),
    Logo("subpixel", "Subpixel", "an s in red-green-blue LCD subpixels, 2r in ink",
         "Zoom into a screen and you see subpixels: the s in real RGB stripes, the 2r in ink.", subpixel,
         palette_break="RGB subpixels"),
    Logo("mirror-line", "Mirror Line", "pixel s2r above a line, reflected below in steel",
         "The pixel word on a line, its reflection below in machined steel: the twin and the thing, mirrored.", mirror_line),
    Logo("circuit-s", "Circuit s", "an s that is a circuit board, an r cast in bronze",
         "The s is a circuit board with a trace round its edge and pads; the r is sand-cast bronze. The same pairing as gear Circuit Cast.",
         circuit_s, palette_break="bronze casting and PCB pads"),
]
assert len(S2R) == 20

# metal_defs carries the shadow blur; the marks that don't load it need the blur on its own
_NEEDS_SOFT = {"res-ramp", "dither-fade", "halftone-fade", "type-wipe", "glitch-print", "led-matrix", "pixel-shadow-type",
               "vector-handles", "subpixel"}
for _lg in S2R:
    if _lg.slug in _NEEDS_SOFT:
        _fn = _lg.draw
        _lg.draw = (lambda fn: (lambda P, uid: defs(_soft(uid)) + fn(P, uid)))(_fn)
