"""Round 2: twenty sim2real LOGOS on one idea, the same gear shown digitally and for real.

Zach, 2026-10-28: "For me sim to real is like a picture of a gear on a computer screen vs on in real
life side by side. Or like a pixelated digital thing vs the analog real thing. Maybe some like 09
is promising if maybe its like half a computer screen half in reality. and perhaps there is like a
gear or something inside the middle of the screen."

Each logo is a function ``draw(P, uid) -> svg body`` on a 512 x 512 artboard; ``P`` is the light or
dark palette from geom.py and ``uid`` prefixes every id. The icon comes later, simplified from the
picked logo; these are not simplified yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from geom import (
    GREEN_LIT,
    RIM,
    Gear,
    cells_path,
    circle_d,
    f,
    glare,
    metal_defs,
    metal_gear,
    monitor,
    pixel_cells,
    pixel_gear,
    screen_grid,
    shade_cells,
    wire_gear,
)


@dataclass
class Logo:
    slug: str
    name: str
    idea: str
    why: str
    draw: Callable[[dict, str], str]
    develops_09: bool = False
    palette_break: str = ""
    faithful: bool = False
    tags: list[str] = field(default_factory=list)


def defs(*parts: str) -> str:
    return "<defs>" + "".join(parts) + "</defs>"


def clip_rect(cid: str, x, y, w, h) -> str:
    return f'<clipPath id="{cid}"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}"/></clipPath>'


def ground_shadow(uid: str, cx, cy, rx, ry, P, op=1.0) -> str:
    return (
        f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" fill="{P["shadow"]}" '
        f'opacity="{f(P["shadow_op"] * op)}" filter="url(#{uid}-soft)"/>'
    )


# ---------------------------------------------------------------------------------------------
# 1. Half Screen: a monitor cut down the middle; the gear sits on the cut (his 09 idea)
# ---------------------------------------------------------------------------------------------


def half_screen(P, uid):
    g = Gear(262, 226, 140, n=10)
    cell = 17.5
    x0, y0, x1, y1 = 30, 64, 262, 392
    r = 22
    body = f"M{x1} {y0}H{x0 + r}a{r} {r} 0 0 0 -{r} {r}V{y1 - r}a{r} {r} 0 0 0 {r} {r}H{x1}Z"
    sx0, sy0, sx1, sy1 = x0 + 16, y0 + 16, x1 - 10, y1 - 16
    out = [defs(metal_defs(uid), clip_rect(f"{uid}-in", sx0, sy0, sx1 - sx0, sy1 - sy0),
                clip_rect(f"{uid}-out", x1 + 8, 0, 512, 512))]
    # stand under the half monitor
    sx = (x0 + x1) / 2
    out.append(
        f'<path d="M{f(sx - 20)} {y1 - 2}L{f(sx - 28)} {y1 + 42}h56L{f(sx + 20)} {y1 - 2}Z" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="3" stroke-linejoin="round"/>'
        f'<rect x="{f(sx - 70)}" y="{y1 + 38}" width="140" height="16" rx="8" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="3"/>'
    )
    out.append(f'<path d="{body}" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="4" stroke-linejoin="round"/>')
    out.append(f'<rect x="{sx0}" y="{sy0}" width="{sx1 - sx0}" height="{sy1 - sy0}" rx="6" fill="{P["screen"]}"/>')
    out.append(f'<g clip-path="url(#{uid}-in)">{screen_grid(sx0, sy0, sx1 - sx0, sy1 - sy0, cell, P, g.cx, g.cy)}'
               f'{pixel_gear(g, P, cell)}{glare(sx0, sy0, sx1 - sx0, sy1 - sy0)}</g>')
    out.append(f'<g clip-path="url(#{uid}-out)">{metal_gear(uid, g, P)}</g>')
    # the cut edge of the monitor: a bezel bar the gear passes through
    out.append(f'<rect x="{x1 - 10}" y="{y0}" width="18" height="{y1 - y0}" rx="3" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="3"/>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 2. Side by Side: the gear on a screen, the same gear on the bench (his words, literally)
# ---------------------------------------------------------------------------------------------


def side_by_side(P, uid):
    ground = 122 + 212 + 58  # the monitor's foot sits on it
    mon_svg, clip = monitor(uid, P, 18, 122, 246, 212, bezel=14, r=16, stand=True)
    g_scr = Gear(141, 228, 80, n=10)
    g_real = Gear(384, ground - 106, 106, n=10)
    out = [defs(metal_defs(uid))]
    out.append(f'<path d="M8 {ground}H504" stroke="{P["line"]}" stroke-width="4" stroke-linecap="round" opacity=".35"/>')
    out.append(mon_svg)
    out.append(f'<g clip-path="url(#{clip})">{screen_grid(32, 136, 218, 184, 10, P, g_scr.cx, g_scr.cy)}'
               f'{pixel_gear(g_scr, P, 10)}{glare(32, 136, 218, 184)}</g>')
    out.append(ground_shadow(uid, g_real.cx + 6, ground - 2, 92, 10, P))
    out.append(metal_gear(uid, g_real, P, shadow=False))
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 3. Split Gear: one gear, left half pixel-stepped, right half machined
# ---------------------------------------------------------------------------------------------


def split_gear(P, uid):
    g = Gear(256, 256, 200, n=10)
    cell = 25
    out = [defs(metal_defs(uid), clip_rect(f"{uid}-r", 256, 0, 256, 512))]
    out.append(pixel_gear(g, P, cell, on_screen=False, keep=lambda x, y: x < 256))
    out.append(f'<g clip-path="url(#{uid}-r)">{metal_gear(uid, g, P)}</g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 4. Wipe Slider: a whole monitor; a compare slider wipes the screen from sim to reality
# ---------------------------------------------------------------------------------------------


def wipe_slider(P, uid):
    x, y, w, h = 36, 72, 440, 304
    mon_svg, clip = monitor(uid, P, x, y, w, h, bezel=16, r=20, stand=True)
    g = Gear(256, 224, 118, n=10)
    cell = 14.75
    sx, sy, sw, sh = x + 16, y + 16, w - 32, h - 32
    real_bg = "#ECEEE8" if P["name"] == "light" else "#1E231E"
    out = [defs(metal_defs(uid), clip_rect(f"{uid}-l", 0, 0, 256, 512), clip_rect(f"{uid}-r", 256, 0, 256, 512))]
    out.append(mon_svg)
    out.append(f'<g clip-path="url(#{clip})"><g clip-path="url(#{uid}-l)">{screen_grid(sx, sy, sw, sh, cell, P, g.cx, g.cy)}'
               f'{pixel_gear(g, P, cell)}</g>'
               f'<g clip-path="url(#{uid}-r)"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" fill="{real_bg}"/>'
               f'{metal_gear(uid, g, P)}</g></g>')
    c = P["pix"]
    out.append(
        f'<path d="M256 34V430" stroke="{P["bg"]}" stroke-width="12" stroke-linecap="round"/>'
        f'<path d="M256 34V430" stroke="{c}" stroke-width="6" stroke-linecap="round"/>'
        f'<circle cx="256" cy="224" r="30" fill="{P["bg"]}" stroke="{c}" stroke-width="6"/>'
        f'<path d="M248 212l-11 12 11 12M264 212l11 12-11 12" fill="none" stroke="{c}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 5. Dashed Frame: round-1 09 itself, with the gear inside (solid screen half, dashed real half)
# ---------------------------------------------------------------------------------------------


def dashed_frame(P, uid):
    x0, y0, x1, y1, r = 56, 80, 456, 432, 44
    g = Gear(256, 256, 138, n=10)
    cell = 17.25
    left = f"M256 {y0}H{x0 + r}a{r} {r} 0 0 0 -{r} {r}V{y1 - r}a{r} {r} 0 0 0 {r} {r}H256"
    right = f"M256 {y0}H{x1 - r}a{r} {r} 0 0 1 {r} {r}V{y1 - r}a{r} {r} 0 0 1 -{r} {r}H256"
    L = 2 * (200 - r) + math.pi * r + (y1 - y0 - 2 * r)
    n = 9
    gap = 34
    dash = (L - (n - 1) * gap) / n
    out = [defs(metal_defs(uid), f'<clipPath id="{uid}-scr"><path d="{left}Z"/></clipPath>', clip_rect(f"{uid}-r", 256, 0, 256, 512))]
    out.append(f'<path d="M256 34V478" stroke="{P["muted"]}" stroke-width="16" stroke-linecap="round"/>')
    out.append(f'<path d="{left}Z" fill="{P["screen"]}"/>')
    out.append(f'<g clip-path="url(#{uid}-scr)">{screen_grid(x0, y0, 200, y1 - y0, cell, P, g.cx, g.cy)}{pixel_gear(g, P, cell)}</g>')
    out.append(f'<path d="{left}" fill="none" stroke="{P["ink"]}" stroke-width="22" stroke-linejoin="round"/>')
    out.append(f'<path d="{right}" fill="none" stroke="{P["ink"]}" stroke-width="22" stroke-linecap="round" stroke-dasharray="{f(dash)} {f(gap)}"/>')
    out.append(f'<g clip-path="url(#{uid}-r)">{metal_gear(uid, g, P)}</g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 6. Breakout: the screen gear is too real for its screen; its teeth push out through the corner
# ---------------------------------------------------------------------------------------------


def breakout(P, uid):
    x, y, w, h = 22, 168, 330, 262
    mon_svg, clip = monitor(uid, P, x, y, w, h, bezel=16, r=18, stand=False)
    sx, sy, sw, sh = x + 16, y + 16, w - 32, h - 32
    g = Gear(304, 214, 150, n=10, rot=8)
    cell = 18.75
    outside = (f'<clipPath id="{uid}-out"><path d="M0 0H512V512H0Z M{sx} {sy}V{sy + sh}H{sx + sw}V{sy}Z" clip-rule="evenodd"/></clipPath>')
    out = [defs(metal_defs(uid), outside)]
    out.append(f'<path d="M{f(x + w / 2 - 20)} {y + h - 2}l-8 44h56l-8-44Z" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="3" stroke-linejoin="round"/>'
               f'<rect x="{f(x + w / 2 - 70)}" y="{y + h + 38}" width="140" height="16" rx="8" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="3"/>')
    out.append(mon_svg)
    out.append(f'<g clip-path="url(#{clip})">{screen_grid(sx, sy, sw, sh, cell, P, g.cx, g.cy)}{pixel_gear(g, P, cell)}{glare(sx, sy, sw, sh)}</g>')
    out.append(f'<g clip-path="url(#{uid}-out)">{metal_gear(uid, g, P)}</g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 7. Meshing Pair: a pixel gear drives a real gear
# ---------------------------------------------------------------------------------------------


def meshing_pair(P, uid):
    rt = 112
    a = Gear(0, 256, rt, n=10)
    pitch_r = (a.r_root + a.r_tip) / 2
    d = 2 * pitch_r + 3
    a.cx = 256 - d / 2
    b = Gear(256 + d / 2, 256, rt, n=10, rot=18)
    out = [defs(metal_defs(uid))]
    out.append(pixel_gear(a, P, 14, on_screen=False))
    out.append(metal_gear(uid, b, P))
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 8. Pixel Shadow: the real gear casts its twin as a pixel shadow
# ---------------------------------------------------------------------------------------------


def pixel_shadow(P, uid):
    """WHY a drop shadow on the wall: a floor shadow squashed flat read as a slab of pixels, not a gear."""
    g = Gear(232, 232, 186, n=10)
    sh = Gear(g.cx + 44, g.cy + 40, g.r_tip, n=10)
    out = [defs(metal_defs(uid))]
    out.append(pixel_gear(sh, P, 18, on_screen=False, gap_ratio=0.16))
    out.append(metal_gear(uid, g, P, shadow=False))
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 9. Reflection: the gear on the screen, reflected below it as the real thing
# ---------------------------------------------------------------------------------------------


def reflection(P, uid):
    x, y, w, h = 56, 24, 400, 236
    mon_svg, clip = monitor(uid, P, x, y, w, h, bezel=14, r=16, stand=False)
    g = Gear(256, y + h / 2, 94, n=10)
    mirror = y + h + 8
    g_real = Gear(256, mirror + (mirror - g.cy), 94, n=10)
    fade = (f'<linearGradient id="{uid}-fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="1"/>'
            f'<stop offset="1" stop-color="#fff" stop-opacity=".4"/></linearGradient>'
            f'<mask id="{uid}-mask" maskUnits="userSpaceOnUse" x="0" y="{mirror}" width="512" height="{512 - mirror}">'
            f'<rect x="0" y="{mirror}" width="512" height="{512 - mirror}" fill="url(#{uid}-fade)"/></mask>')
    out = [defs(metal_defs(uid), fade)]
    out.append(mon_svg)
    out.append(f'<g clip-path="url(#{clip})">{screen_grid(x + 14, y + 14, w - 28, h - 28, 11.75, P, g.cx, g.cy)}'
               f'{pixel_gear(g, P, 11.75)}{glare(x + 14, y + 14, w - 28, h - 28)}</g>')
    out.append(f'<path d="M24 {mirror}H488" stroke="{P["line"]}" stroke-width="3" stroke-linecap="round" opacity=".4"/>')
    out.append(f'<g mask="url(#{uid}-mask)">{metal_gear(uid, g_real, P, shadow=False)}</g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 10. Circuit Cast: half circuit board, half sand-cast bronze (palette break: bronze)
# ---------------------------------------------------------------------------------------------


def circuit_cast(P, uid):
    g = Gear(256, 256, 198, n=10)
    board, trace, pad = "#2F6F4F", "#9BE7BF", "#DADDD6"
    bronze = (f'<linearGradient id="{uid}-bz" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E7B77E"/>'
              f'<stop offset=".5" stop-color="#B07A43"/><stop offset="1" stop-color="#6E4724"/></linearGradient>'
              f'<filter id="{uid}-grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" seed="7"/>'
              f'<feColorMatrix values="0 0 0 0 .1  0 0 0 0 .06  0 0 0 0 .02  0 0 0 -1.4 1.05"/></filter>'
              f'<filter id="{uid}-soft" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>')
    clips = (clip_rect(f"{uid}-l", 0, 0, 256, 512) + clip_rect(f"{uid}-r", 256, 0, 256, 512)
             + f'<clipPath id="{uid}-g"><path d="{g.path()}{circle_d(g.cx, g.cy, g.r_bore)}" clip-rule="evenodd"/></clipPath>')
    out = [defs(bronze, clips)]
    body = f"{g.path()}{circle_d(g.cx, g.cy, g.r_bore)}"
    # left: the board
    traces = []
    pads = []
    for k in range(10):
        a = math.radians(k * 36)
        if math.cos(a) > 0.2:
            continue
        r1, r2, r3 = g.r_bore + 16, g.r_tip * 0.55, g.r_tip * 0.86
        bend = 0.16 if math.sin(a) >= 0 else -0.16
        p1 = (g.cx + r1 * math.cos(a), g.cy + r1 * math.sin(a))
        p2 = (g.cx + r2 * math.cos(a), g.cy + r2 * math.sin(a))
        p3 = (g.cx + r3 * math.cos(a + bend * 0.0), g.cy + r3 * math.sin(a + bend * 0.0))
        mid = (g.cx + (r2 + 18) * math.cos(a + bend * 0.5), g.cy + (r2 + 18) * math.sin(a + bend * 0.5))
        traces.append(f"M{f(p1[0])} {f(p1[1])}L{f(p2[0])} {f(p2[1])}L{f(mid[0])} {f(mid[1])}L{f(p3[0])} {f(p3[1])}")
        pads.append(circle_d(p3[0], p3[1], 10))
        pads.append(circle_d(p1[0], p1[1], 6))
    inset = Gear(g.cx, g.cy, g.r_tip - 14, n=10, depth=0.2 * 198 / 184)
    out.append(f'<path d="{body}" transform="translate(6 14)" fill="{P["shadow"]}" opacity="{P["shadow_op"]}" filter="url(#{uid}-soft)"/>')
    out.append(f'<g clip-path="url(#{uid}-l)"><path d="{body}" fill="{board}" fill-rule="evenodd" stroke="#1B3D2C" stroke-width="5"/>'
               f'<path d="{inset.path()}" fill="none" stroke="{trace}" stroke-width="2.5" opacity=".55"/>'
               f'<circle cx="{g.cx}" cy="{g.cy}" r="{f(g.r_bore + 16)}" fill="none" stroke="{trace}" stroke-width="5"/>'
               f'<path d="{"".join(traces)}" fill="none" stroke="{trace}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
               f'<path d="{"".join(pads)}" fill="{pad}" stroke="{trace}" stroke-width="3"/></g>')
    # right: cast bronze with sand grain
    out.append(f'<g clip-path="url(#{uid}-r)"><path d="{body}" fill="url(#{uid}-bz)" fill-rule="evenodd" stroke="#4A2F17" stroke-width="5"/>'
               f'<g clip-path="url(#{uid}-g)"><rect x="256" y="40" width="220" height="432" filter="url(#{uid}-grain)" opacity=".55"/></g>'
               f'<circle cx="{g.cx}" cy="{g.cy}" r="{f(g.r_tip * 0.42)}" fill="none" stroke="#4A2F17" stroke-opacity=".5" stroke-width="4"/>'
               f'<circle cx="{g.cx}" cy="{g.cy}" r="{f(g.r_bore)}" fill="none" stroke="#4A2F17" stroke-width="5"/></g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 11. CRT Cutaway: a phosphor gear on an old CRT, the set torn open to the real gear
# ---------------------------------------------------------------------------------------------


def crt_cutaway(P, uid):
    g = Gear(262, 222, 120, n=10)
    tear = [(262, 40), (250, 86), (272, 130), (250, 178), (274, 226), (250, 272), (272, 318), (252, 366), (270, 410), (258, 470)]
    tear_l = "M0 0H" + f(tear[0][0]) + "".join(f"L{f(px)} {f(py)}" for px, py in tear) + "L" + f(tear[-1][0]) + " 512H0Z"
    tear_r = "M512 0H" + f(tear[0][0]) + "".join(f"L{f(px)} {f(py)}" for px, py in tear) + "L" + f(tear[-1][0]) + " 512H512Z"
    phos = (f'<filter id="{uid}-glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="5" result="b"/>'
            f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
            f'<pattern id="{uid}-scan" width="8" height="8" patternUnits="userSpaceOnUse"><rect width="8" height="5" fill="#fff"/></pattern>'
            f'<mask id="{uid}-scanm" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="url(#{uid}-scan)"/></mask>')
    out = [defs(metal_defs(uid), phos, f'<clipPath id="{uid}-l"><path d="{tear_l}"/></clipPath>',
                f'<clipPath id="{uid}-r"><path d="{tear_r}"/></clipPath>',
                f'<clipPath id="{uid}-scr"><rect x="70" y="88" width="372" height="270" rx="46"/></clipPath>')]
    crt = (
        f'<rect x="30" y="52" width="452" height="390" rx="34" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="5"/>'
        f'<rect x="56" y="74" width="400" height="298" rx="56" fill="{P["bezel_edge"]}" opacity=".55"/>'
        f'<rect x="70" y="88" width="372" height="270" rx="46" fill="{P["screen"]}"/>'
        f'<g clip-path="url(#{uid}-scr)"><g mask="url(#{uid}-scanm)" filter="url(#{uid}-glow)">'
        f'<path d="{g.path()}{circle_d(g.cx, g.cy, g.r_bore)}" fill="{GREEN_LIT}" fill-rule="evenodd"/></g>'
        f'<path d="M70 88h372v120Q256 150 70 220Z" fill="#fff" opacity=".05"/></g>'
        + "".join(f'<rect x="{x}" y="396" width="34" height="8" rx="4" fill="{P["bezel_edge"]}"/>' for x in (64, 108, 152))
        + f'<circle cx="404" cy="400" r="14" fill="{P["bezel_edge"]}"/><circle cx="446" cy="400" r="9" fill="{GREEN_LIT}"/>'
    )
    out.append(f'<g clip-path="url(#{uid}-l)">{crt}</g>')
    out.append(f'<path d="M{f(tear[0][0])} {f(tear[0][1])}' + "".join(f"L{f(px)} {f(py)}" for px, py in tear[1:])
               + f'" fill="none" stroke="{P["bezel_edge"]}" stroke-width="7" stroke-linejoin="round"/>')
    out.append(f'<g clip-path="url(#{uid}-r)">{metal_gear(uid, g, P)}</g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 12. Dither Sweep: pixels dissolve into metal, left to right, through an ordered dither
# ---------------------------------------------------------------------------------------------

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def dither_sweep(P, uid):
    g = Gear(256, 256, 200, n=10)
    cell = 16
    cells = pixel_cells(g, cell)
    keep = set()
    for i, j in cells:
        x = g.cx + (i + 0.5) * cell
        v = (x - (g.cx - g.r_tip)) / (2 * g.r_tip)
        density = 1 - min(1, max(0, (v - 0.12) / 0.62))
        t = (BAYER[j % 4][i % 4] + 0.5) / 16
        if t < density:
            keep.add((i, j))
    ramp = (f'<linearGradient id="{uid}-ramp" x1="{f(g.cx - g.r_tip)}" x2="{f(g.cx + g.r_tip)}" y1="0" y2="0" gradientUnits="userSpaceOnUse">'
            f'<stop offset=".2" stop-color="#fff" stop-opacity="0"/><stop offset=".72" stop-color="#fff" stop-opacity="1"/></linearGradient>'
            f'<mask id="{uid}-m" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="url(#{uid}-ramp)"/></mask>')
    out = [defs(metal_defs(uid), ramp)]
    out.append(f'<g mask="url(#{uid}-m)">{metal_gear(uid, g, P)}</g>')
    out.append(f'<path d="{cells_path(keep, cell, g.cx, g.cy, cell * 0.12)}" fill="{P["pix"]}"/>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 13. LOD Sectors: four quarters at four resolutions, converging on the real thing
# ---------------------------------------------------------------------------------------------


def lod_sectors(P, uid):
    g = Gear(256, 256, 200, n=10, rot=18)
    out = [defs(metal_defs(uid), clip_rect(f"{uid}-bl", 0, 256, 256, 256))]
    quads = [(40, lambda x, y: x < 256 and y < 256), (20, lambda x, y: x >= 256 and y < 256), (10, lambda x, y: x >= 256 and y >= 256)]
    for cell, keep in quads:
        out.append(pixel_gear(g, P, cell, on_screen=False, keep=keep, gap_ratio=0.1))
    out.append(f'<g clip-path="url(#{uid}-bl)">{metal_gear(uid, g, P)}</g>')
    out.append(f'<path d="M256 40V472M40 256H472" stroke="{P["muted"]}" stroke-width="3" stroke-dasharray="10 9" opacity=".7"/>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 14. Wireframe Twin: the CAD wireframe on the monitor, the machined part set down in front of it
# ---------------------------------------------------------------------------------------------


def wireframe_twin(P, uid):
    x, y, w, h = 26, 40, 352, 262
    mon_svg, clip = monitor(uid, P, x, y, w, h, bezel=16, r=18, stand=True)
    g_w = Gear(196, 171, 100, n=10)
    g_r = Gear(352, 334, 134, n=10)
    out = [defs(metal_defs(uid))]
    out.append(mon_svg)
    out.append(f'<g clip-path="url(#{clip})">{wire_gear(g_w, GREEN_LIT, 4.5)}{glare(x + 16, y + 16, w - 32, h - 32)}</g>')
    out.append(metal_gear(uid, g_r, P, shadow_dy=16))
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 15. Loupe: look closely at the real gear and you find its pixels
# ---------------------------------------------------------------------------------------------


def loupe(P, uid):
    g = Gear(228, 272, 186, n=10, rot=-9)
    lx, ly, lr = 330, 170, 104
    k = 1.55
    gz = Gear(lx + (g.cx - lx) * k, ly + (g.cy - ly) * k, g.r_tip * k, n=10)
    out = [defs(metal_defs(uid), f'<clipPath id="{uid}-lens"><circle cx="{lx}" cy="{ly}" r="{lr}"/></clipPath>')]
    out.append(metal_gear(uid, g, P))
    hx0, hy0 = lx + lr * 0.72, ly + lr * 0.72
    out.append(f'<path d="M{f(hx0)} {f(hy0)}L{f(hx0 + 70)} {f(hy0 + 70)}" stroke="{P["bezel"]}" stroke-width="40" stroke-linecap="round"/>'
               f'<path d="M{f(hx0)} {f(hy0)}L{f(hx0 + 70)} {f(hy0 + 70)}" stroke="{P["bezel_hi"]}" stroke-width="4" stroke-linecap="round" opacity=".6" transform="translate(-9 9)"/>')
    out.append(f'<g clip-path="url(#{uid}-lens)"><rect x="{lx - lr}" y="{ly - lr}" width="{2 * lr}" height="{2 * lr}" fill="{P["screen"]}"/>'
               f'{screen_grid(lx - lr, ly - lr, 2 * lr, 2 * lr, 21, P, gz.cx, gz.cy)}{pixel_gear(gz, P, 21)}'
               f'<path d="M{lx - lr} {ly - lr}h{2 * lr}L{lx - lr} {ly + lr * 0.4}Z" fill="#fff" opacity=".07"/></g>')
    out.append(f'<circle cx="{lx}" cy="{ly}" r="{lr + 9}" fill="none" stroke="{P["bezel"]}" stroke-width="20"/>'
               f'<circle cx="{lx}" cy="{ly}" r="{lr + 1}" fill="none" stroke="{P["bezel_hi"]}" stroke-width="3" opacity=".8"/>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 16. Viewfinder: hold a tablet up to the real gear and see its twin through it
# ---------------------------------------------------------------------------------------------


def viewfinder(P, uid):
    g = Gear(300, 262, 182, n=10)
    tx, ty, tw, th, rot = 28, 120, 276, 300, -9
    tcx, tcy = tx + tw / 2, ty + th / 2
    a = math.radians(-rot)
    dx, dy = g.cx - tcx, g.cy - tcy
    lx = tcx + dx * math.cos(a) - dy * math.sin(a)
    ly = tcy + dx * math.sin(a) + dy * math.cos(a)
    gl = Gear(lx, ly, g.r_tip, n=10, rot=-rot)
    sx, sy, sw, sh = tx + 16, ty + 16, tw - 32, th - 32
    cell = 18
    out = [defs(metal_defs(uid), f'<clipPath id="{uid}-scr"><rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="10"/></clipPath>')]
    out.append(metal_gear(uid, g, P))
    br = []
    bx0, by0, bx1, by1 = lx - 120, ly - 120, sx + sw - 20, ly + 120
    for (cx_, cy_, sxn, syn) in ((bx0, by0, 1, 1), (bx1, by0, -1, 1), (bx0, by1, 1, -1), (bx1, by1, -1, -1)):
        br.append(f"M{f(cx_)} {f(cy_ + 26 * syn)}V{f(cy_)}H{f(cx_ + 26 * sxn)}")
    tablet = (
        f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="28" fill="{P["bezel"]}" stroke="{P["bezel_edge"]}" stroke-width="4"/>'
        f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="10" fill="{P["screen"]}"/>'
        f'<g clip-path="url(#{uid}-scr)">{screen_grid(sx, sy, sw, sh, cell, P, gl.cx, gl.cy)}{pixel_gear(gl, P, cell)}'
        f'<path d="{"".join(br)}" fill="none" stroke="{GREEN_LIT}" stroke-width="5" stroke-linecap="round" opacity=".9"/>'
        f'<circle cx="{sx + 22}" cy="{sy + 22}" r="7" fill="{GREEN_LIT}"/>{glare(sx, sy, sw, sh)}</g>'
        f'<circle cx="{tx + tw - 9}" cy="{tcy}" r="4" fill="{P["bezel_hi"]}"/>'
    )
    out.append(f'<g transform="rotate({rot} {f(tcx)} {f(tcy)})">{tablet}</g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 17. Sim Floor: the real gear standing on a simulator's checker floor
# ---------------------------------------------------------------------------------------------


def sim_floor(P, uid):
    horizon, fz, cx = 300, 190, 256

    def proj(X, Z):
        return cx + X * 175 / Z, horizon + fz / Z

    tiles = []
    # WHY dark in both themes: a sim viewport's floor; the light-grey version vanished at 32 px
    dark, lite = "#141814", "#232A24"
    for zi in range(10):
        z0, z1 = 1 + zi * 0.6, 1 + (zi + 1) * 0.6
        for xi in range(-5, 5):
            x0, x1 = xi * 0.75, (xi + 1) * 0.75
            pts = [proj(x0, z0), proj(x1, z0), proj(x1, z1), proj(x0, z1)]
            colour = dark if (xi + zi) % 2 else lite
            tiles.append(f'<path d="M' + "L".join(f"{f(px)} {f(py)}" for px, py in pts) + f'Z" fill="{colour}"/>')
    lines = []
    for xi in range(-5, 6):
        a, b = proj(xi * 0.75, 1), proj(xi * 0.75, 7)
        lines.append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
    for zi in range(11):
        a, b = proj(-3.75, 1 + zi * 0.6), proj(3.75, 1 + zi * 0.6)
        lines.append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
    fade = (f'<linearGradient id="{uid}-ff" x1="0" y1="{horizon}" x2="0" y2="{horizon + fz}" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".55" stop-color="#fff" stop-opacity="1"/></linearGradient>'
            f'<mask id="{uid}-fm" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512"><rect width="512" height="512" fill="url(#{uid}-ff)"/></mask>'
            f'<clipPath id="{uid}-art"><rect width="512" height="512" rx="0"/></clipPath>')
    g = Gear(256, 238, 176, n=10)
    contact = g.cy + g.r_tip
    out = [defs(metal_defs(uid), fade)]
    out.append(f'<g clip-path="url(#{uid}-art)" mask="url(#{uid}-fm)">{"".join(tiles)}'
               f'<path d="{"".join(lines)}" stroke="{GREEN_LIT}" stroke-width="2.5" opacity=".8"/></g>')
    out.append(ground_shadow(uid, g.cx + 30, contact - 4, 150, 16, P, 1.1))
    out.append(metal_gear(uid, g, P, shadow=False))
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 18. Overlay Offset: the twin's pixel outline laid over the real gear, a few degrees off
# ---------------------------------------------------------------------------------------------


def overlay_offset(P, uid):
    g = Gear(250, 262, 188, n=10)
    twin = Gear(262, 250, 188, n=10, rot=7)
    cell = 11.75
    cells = pixel_cells(twin, cell)
    edge = {(i, j) for i, j in cells if any((i + di, j + dj) not in cells for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
    out = [defs(metal_defs(uid))]
    out.append(metal_gear(uid, g, P))
    col = GREEN_LIT if P["name"] == "dark" else "#23A86C"
    out.append(f'<path d="{cells_path(edge, cell, twin.cx, twin.cy, 0)}" fill="{col}" opacity=".95"/>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 19. Screen Hub: a real gear whose hub is a screen showing its own twin
# ---------------------------------------------------------------------------------------------


def screen_hub(P, uid):
    g = Gear(256, 256, 214, n=10, bore=0.02)
    small = Gear(256, 256, 58, n=10)
    w, h = 176, 152
    x, y = 256 - w / 2, 256 - h / 2
    out = [defs(metal_defs(uid), f'<clipPath id="{uid}-scr"><rect x="{x + 11}" y="{y + 11}" width="{w - 22}" height="{h - 22}" rx="6"/></clipPath>')]
    out.append(metal_gear(uid, g, P))
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{P["bezel"]}" stroke="{RIM}" stroke-width="5"/>'
               f'<rect x="{x + 11}" y="{y + 11}" width="{w - 22}" height="{h - 22}" rx="6" fill="{P["screen"]}"/>'
               f'<g clip-path="url(#{uid}-scr)">{screen_grid(x + 11, y + 11, w - 22, h - 22, 8, P, 256, 256)}{pixel_gear(small, P, 8)}</g>')
    return "".join(out)


# ---------------------------------------------------------------------------------------------
# 20. Mesh Metal: half a low-poly render mesh, half machined metal
# ---------------------------------------------------------------------------------------------


def mesh_metal(P, uid):
    g = Gear(256, 256, 200, n=10)
    seg = 40
    radii = [g.r_bore, g.r_tip * 0.42, g.r_tip * 0.6, g.r_root]
    tris = []

    def pt(r, k):
        a = 2 * math.pi * k / seg
        return (g.cx + r * math.cos(a), g.cy + r * math.sin(a))

    for ri in range(len(radii) - 1):
        for k in range(seg):
            a0, a1 = pt(radii[ri], k + (ri % 2) * 0.5), pt(radii[ri], k + 1 + (ri % 2) * 0.5)
            b0, b1 = pt(radii[ri + 1], k + ((ri + 1) % 2) * 0.5), pt(radii[ri + 1], k + 1 + ((ri + 1) % 2) * 0.5)
            tris += [(a0, a1, b0), (a1, b1, b0)]
    pitch, hb, ht, r0 = g._angles()
    for i in range(g.n):
        ac = r0 + i * pitch
        p = lambda r, a: (g.cx + r * math.cos(a), g.cy + r * math.sin(a))
        q = [p(g.r_root, ac - hb), p(g.r_tip, ac - ht), p(g.r_tip, ac + ht), p(g.r_root, ac + hb)]
        tris += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
    lo, mid, hi = P["pix_lo"], P["pix"], P["pix_hi"]

    def mix(c1, c2, t):
        a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{round(a[k] + (b[k] - a[k]) * t):02X}" for k in range(3))

    polys = []
    for idx, (p1, p2, p3) in enumerate(tris):
        cxm = (p1[0] + p2[0] + p3[0]) / 3
        cym = (p1[1] + p2[1] + p3[1]) / 3
        if cxm > g.cx + 4:
            continue
        light = 0.5 - 0.35 * ((cxm - g.cx) + (cym - g.cy)) / (2 * g.r_tip) + 0.18 * math.sin(idx * 2.399)
        light = min(1, max(0, light))
        colour = mix(lo, mid, light * 2) if light < 0.5 else mix(mid, hi, (light - 0.5) * 2)
        polys.append(f'<path d="M{f(p1[0])} {f(p1[1])}L{f(p2[0])} {f(p2[1])}L{f(p3[0])} {f(p3[1])}Z" fill="{colour}"/>')
    out = [defs(metal_defs(uid), clip_rect(f"{uid}-l", 0, 0, 256, 512), clip_rect(f"{uid}-r", 256, 0, 256, 512))]
    out.append(f'<g clip-path="url(#{uid}-l)" stroke="{P["pix_lo"]}" stroke-width="1.6" stroke-linejoin="round">{"".join(polys)}</g>')
    out.append(f'<g clip-path="url(#{uid}-r)">{metal_gear(uid, g, P)}</g>')
    return "".join(out)


LOGOS: list[Logo] = [
    Logo("half-screen", "Half Screen", "a monitor cut down the middle, the gear sitting on the cut",
         "His 09 idea taken literally: half a computer screen, half reality, the gear in the middle. "
         "Inside the bezel it is pixels, outside it is a machined part.", half_screen, develops_09=True, tags=["screen", "split"]),
    Logo("side-by-side", "Side by Side", "the gear on a screen beside the same gear on the bench",
         "His sentence drawn straight: a gear on a computer screen next to the gear in real life.", side_by_side,
         faithful=True, tags=["screen", "pair"]),
    Logo("split-gear", "Split Gear", "one gear, left half pixel-stepped, right half machined",
         "No screen at all: the pixel steps alone say 'digital' and the smooth half says 'real'. "
         "The most direct path to a 24 px icon.", split_gear, tags=["split"]),
    Logo("wipe-slider", "Wipe Slider", "a compare slider wipes the screen from sim to reality",
         "The whole monitor stays; a compare-slider handle wipes it from the pixel twin to the real gear. "
         "This is also how the tool's views work.", wipe_slider, develops_09=True, tags=["screen", "split"]),
    Logo("dashed-frame", "Dashed Frame", "round-1 09 itself, with the gear inside",
         "The 09 shape he pointed at, kept exactly: a solid half that is a screen, a dashed half that is reality, "
         "and the gear across the wipe bar.", dashed_frame, develops_09=True, tags=["screen", "split", "round1"]),
    Logo("breakout", "Breakout", "the gear's teeth break out of the screen into the real world",
         "The twin got good enough to leave the screen: inside the bezel it is pixels, the teeth that push "
         "through the corner are metal.", breakout, tags=["screen"]),
    Logo("meshing-pair", "Meshing Pair", "a pixel gear meshes with a real gear",
         "Twin and hardware as two gears that have to mesh: if the teeth don't line up, nothing turns.",
         meshing_pair, tags=["pair"]),
    Logo("pixel-shadow", "Pixel Shadow", "the real gear casts a pixelated shadow",
         "The twin is the real part's shadow: the same outline, cast on the wall behind it in pixels.",
         pixel_shadow, tags=["shadow"]),
    Logo("reflection", "Reflection", "the screen gear reflected below as the real one",
         "The gear on the screen, mirrored below its bezel as the machined part: the two reflections of one object.",
         reflection, tags=["screen", "mirror"]),
    Logo("circuit-cast", "Circuit Cast", "half circuit board, half sand-cast bronze",
         "The digital half is a circuit board, the analog half is a casting. The textures are more physical than pixels.",
         circuit_cast, palette_break="bronze casting and PCB pads", tags=["split", "texture"]),
    Logo("crt-cutaway", "CRT Cutaway", "a phosphor gear on an old CRT, torn open to the real gear",
         "Another take on 09 with more character: a glowing scanline gear on a CRT, the set torn down the "
         "middle to the real part.", crt_cutaway, develops_09=True, tags=["screen", "split", "retro"]),
    Logo("dither-sweep", "Dither Sweep", "pixels dissolve into metal through an ordered dither",
         "Digital becomes analog across the gear: an ordered dither thins out left to right until only the metal is left.",
         dither_sweep, tags=["texture"]),
    Logo("lod-sectors", "LOD Sectors", "four quarters at four resolutions, the last one real",
         "Level of detail going round the gear: 4×4 blocks, 8×8, 16×16, then the machined part. The twin converging on reality.",
         lod_sectors, tags=["texture"]),
    Logo("wireframe-twin", "Wireframe Twin", "the CAD wireframe on screen, the machined part in front",
         "A CAD wireframe on the monitor and the finished part set down in front of it: model and made thing, one glance.",
         wireframe_twin, tags=["screen", "pair", "cad"]),
    Logo("loupe", "Loupe", "look closely at the real gear and you find its pixels",
         "Inspection as the metaphor: put a loupe on the real gear and you see the pixels underneath. The tool is that loupe.",
         loupe, tags=["inspect"]),
    Logo("viewfinder", "Viewfinder", "a tablet held up to the real gear shows its twin",
         "Augmented reality: the real gear behind, a tablet in front, and on the screen the same gear in pixels, lined up exactly.",
         viewfinder, tags=["screen", "ar"]),
    Logo("sim-floor", "Sim Floor", "the real gear standing on a simulator's checker floor",
         "A real part standing on a simulator's checker floor (MuJoCo's default ground): the real thing inside the sim world.",
         sim_floor, tags=["sim"]),
    Logo("overlay-offset", "Overlay Offset", "the twin's pixel outline laid over the real gear, a few degrees off",
         "The measurement itself: the twin's outline laid over the real part, close but a few degrees and pixels off.",
         overlay_offset, tags=["overlay"]),
    Logo("screen-hub", "Screen Hub", "a real gear whose hub is a screen showing its own twin",
         "The twin lives inside the real part: the gear's hub is a little screen showing the same gear in pixels.",
         screen_hub, tags=["screen"]),
    Logo("mesh-metal", "Mesh Metal", "half a low-poly render mesh, half machined metal",
         "A 3D render mesh against the machined part: digital as triangles instead of pixels, like objectdb's meshes.",
         mesh_metal, tags=["split", "mesh"]),
]
assert len(LOGOS) == 20


def svg(logo: Logo, palette: dict, uid: str | None = None, size: int | None = 512, background: bool = False,
        title: str = "") -> str:
    uid = uid or f"{logo.slug}-{palette['name']}"
    bg = f'<rect width="512" height="512" fill="{palette["bg"]}"/>' if background else ""
    t = f"<title>{title}</title>" if title else ""
    wh = f' width="{size}" height="{size}"' if size else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"{wh}>{t}{bg}{logo.draw(palette, uid)}</svg>'
