"""The 20 sim2real icon proposals as data, and the two SVG renderings of each.

Every mark is drawn on lucide's own 24-unit grid (24x24 viewBox, stroke 2, round caps
and joins, no fill) so it can sit in Clank's ribbon next to stock lucide icons. Each
stroke carries a role:

- ``real``  the physical device: a solid stroke.
- ``sim``   the twin: a dashed stroke (lucide's own ``square-dashed`` convention).
- ``aux``   a neutral helper line (an axis, a mirror, a wipe bar).
- ``realfill`` / ``realshade`` / ``simfill``  fill-only shapes that exist only in the 256 px app icon.

The toolbar SVG draws real, sim and aux all in ``currentColor``; the app SVG puts the
same geometry on a tile and colours it by role.

WHY explicit dash segments instead of ``stroke-dasharray``: a dasharray's phase lands
anywhere, so an edge can end in a gap and a corner can vanish; lucide's dashed icons
(``square-dashed``, ``circle-dashed``) are drawn as explicit short paths for the same
reason, with dashes that start and end on the path's endpoints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from svgpathtools import parse_path

# Brand tokens (BAM Grid Purist, Oct 24 2026: ink, paper and one green).
INK = "#0E100E"
PAPER = "#FBFBF8"
BAM_GREEN = "#2F6F4F"
# WHY a second green: BAM Green on the ink tile is 3.2:1, too faint for a dashed
# hairline in a dock. This is the same hue (OKLCH 159) lifted to L 0.80, 11:1 on ink.
BAM_GREEN_LIT = "#35DE95"
AUX_ON_INK = "#8A8F89"
AUX_ON_PAPER = "#9DA29B"
LINE = "#DFE1DB"

# The palettes the app icon can be shown in. "ink" is what the -app.svg files use.
PALETTES = {
    "ink": {"tile": INK, "real": PAPER, "shade": "#B9BDB6", "sim": BAM_GREEN_LIT, "aux": AUX_ON_INK, "keyline": None},
    "paper": {"tile": PAPER, "real": INK, "shade": "#4A4F4A", "sim": BAM_GREEN, "aux": AUX_ON_PAPER, "keyline": LINE},
}
FILL_ROLES = {"realfill": "real", "realshade": "shade", "simfill": "sim"}


@dataclass
class El:
    d: str
    role: str = "real"
    dashed: bool = False
    closed: bool = False
    phase: float = 0.0  # where the first dash starts, as a fraction of one period (closed paths)
    dash: float = 2.8  # target dash length in path units (round caps add 1 unit each end)
    gap: float = 4.0  # path gap; 4 leaves a visible gap of 2 units after the round caps


def circle_d(cx: float, cy: float, r: float) -> str:
    return f"M{cx - r:g} {cy:g}a{r:g} {r:g} 0 1 0 {2 * r:g} 0a{r:g} {r:g} 0 1 0 {-2 * r:g} 0Z"


def ellipse_d(cx: float, cy: float, rx: float, ry: float) -> str:
    return f"M{cx - rx:g} {cy:g}a{rx:g} {ry:g} 0 1 0 {2 * rx:g} 0a{rx:g} {ry:g} 0 1 0 {-2 * rx:g} 0Z"


def rect_d(x: float, y: float, w: float, h: float, r: float) -> str:
    return (
        f"M{x + r:g} {y:g}h{w - 2 * r:g}a{r:g} {r:g} 0 0 1 {r:g} {r:g}v{h - 2 * r:g}"
        f"a{r:g} {r:g} 0 0 1 {-r:g} {r:g}h{-(w - 2 * r):g}a{r:g} {r:g} 0 0 1 {-r:g} {-r:g}"
        f"v{-(h - 2 * r):g}a{r:g} {r:g} 0 0 1 {r:g} {-r:g}Z"
    )


def S(d: str, role: str = "real") -> El:
    return El(d, role)


def D(d: str, role: str = "sim", closed: bool = False, phase: float = 0.0, dash: float = 2.8, gap: float = 4.0) -> El:
    return El(d, role, dashed=True, closed=closed, phase=phase, dash=dash, gap=gap)


def F(d: str, role: str = "realfill") -> El:
    return El(d, role)


@dataclass
class Mark:
    slug: str
    name: str
    metaphor: str
    why: str  # one line of rationale for the README / report
    elements: list[El]
    risk: str = ""  # which stock lucide icon (or sibling mark) it could be mistaken for, if any
    app_scale: float = 7.5
    app_stroke: float = 1.75
    tags: list[str] = field(default_factory=list)


def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _simplify(pts: list[complex], eps: float = 0.03) -> list[complex]:
    """Ramer-Douglas-Peucker, so straight dashes collapse to two points."""
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    best, idx = -1.0, 0
    for i, p in enumerate(pts[1:-1], 1):
        if abs(ab) < 1e-9:
            dist = abs(p - a)
        else:
            dist = abs((ab.real * (a.imag - p.imag) - (a.real - p.real) * ab.imag)) / abs(ab)
        if dist > best:
            best, idx = dist, i
    if best <= eps:
        return [a, b]
    return _simplify(pts[: idx + 1], eps)[:-1] + _simplify(pts[idx:], eps)


def dash_segments(el: El) -> str:
    """Cut a path into explicit dashes whose ends sit on the path's own endpoints."""
    path = parse_path(el.d)
    total = path.length()
    period_target = el.dash + el.gap
    spans: list[tuple[float, float]] = []
    if el.closed:
        n = max(3, round(total / period_target))
        while n > 3 and total / n - el.gap < 0.9:
            n -= 1
        period = total / n
        dash = period - el.gap
        start = el.phase * period
        for i in range(n):
            s0 = start + i * period
            spans.append((s0, s0 + dash))
    else:
        n = max(1, round((total + el.gap) / period_target))
        while n > 1 and (total - (n - 1) * el.gap) / n < 0.9:
            n -= 1
        if n == 1:
            return el.d
        dash = (total - (n - 1) * el.gap) / n
        for i in range(n):
            s0 = i * (dash + el.gap)
            spans.append((s0, s0 + dash))

    def point_at(s: float) -> complex:
        s = s % total if el.closed else min(max(s, 0.0), total)
        return path.point(path.ilength(min(s, total - 1e-9) if s >= total else s, s_tol=1e-6))

    out = []
    for s0, s1 in spans:
        steps = max(2, math.ceil((s1 - s0) / 0.35))
        pts = [point_at(s0 + (s1 - s0) * k / steps) for k in range(steps + 1)]
        pts = _simplify(pts)
        out.append("M" + "L".join(f"{_fmt(p.real)} {_fmt(p.imag)}" for p in pts))
    return "".join(out)


def stroke_d(el: El) -> str:
    return dash_segments(el) if el.dashed else el.d


ROOT_24 = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
)


def icon_node(mark: Mark) -> list[list]:
    """lucide's own iconNode shape: [["path", {"d": ...}], ...] (strokes only)."""
    return [["path", {"d": stroke_d(el)}] for el in mark.elements if el.role not in FILL_ROLES]


def svg24(mark: Mark, size: int = 24, extra_attrs: str = "") -> str:
    body = "".join(f'<path d="{node[1]["d"]}"/>' for node in icon_node(mark))
    return f"{ROOT_24.format(size=size)}{extra_attrs}>{body}</svg>"


def svg_app(mark: Mark, palette: str = "ink", classes: bool = False, size: int = 256, title: str = "") -> str:
    """The 256 px dock/app icon: the same strokes on a Grid Purist tile, coloured by role.

    With ``classes=True`` every element also carries a role class (``ic-tile``, ``ic-real``, ...) so the
    report can repaint the whole set when its palette switch flips.
    """
    pal = PALETTES[palette]
    scale = mark.app_scale
    offset = (256 - 24 * scale) / 2
    fills, strokes = [], []
    for el in mark.elements:
        if el.role in FILL_ROLES:
            base = FILL_ROLES[el.role]
            colour = pal[base]
            opacity = ' fill-opacity="0.16"' if base == "sim" else ""
            cls = f' class="{ {"real": "ic-realfill", "shade": "ic-shade", "sim": "ic-simfill"}[base] }"' if classes else ""
            fills.append(f'<path{cls} d="{el.d}" fill="{colour}"{opacity} stroke="none"/>')
        else:
            colour = pal[el.role]
            cls = f' class="{ {"real": "ic-real", "sim": "ic-sim", "aux": "ic-aux"}[el.role] }"' if classes else ""
            strokes.append(f'<path{cls} d="{stroke_d(el)}" stroke="{colour}"/>')
    tile_cls = ' class="ic-tile"' if classes else ""
    keyline = pal["keyline"]
    key = f' stroke="{keyline}" stroke-width="2"' if keyline else ""
    # WHY rx 12: the BAM mark's tile corner is 4/90 of its side ("micro radius: made, not
    # printed"); 12/256 keeps that proportion instead of a phone-style squircle.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 256 256">'
        + (f"<title>{title}</title>" if title else "")
        + f'<rect{tile_cls} x="1" y="1" width="254" height="254" rx="12" fill="{pal["tile"]}"{key}/>'
        f'<g transform="translate({_fmt(offset)} {_fmt(offset)}) scale({_fmt(scale)})" fill="none" '
        f'stroke-width="{_fmt(mark.app_stroke)}" stroke-linecap="round" stroke-linejoin="round">'
        + "".join(fills)
        + "".join(strokes)
        + "</g></svg>"
    )


# ----------------------------------------------------------------------------------------
# The 20 marks. Order = the order in the report; 01 is the recommended default.
# ----------------------------------------------------------------------------------------


# Cube corners on lucide's `box` grid.
_T, _UL, _UR, _C, _LL, _LR, _B = (12, 2), (3, 7), (21, 7), (12, 12), (3, 17), (21, 17), (12, 22)


def _pt(p) -> str:
    return f"{p[0]:g} {p[1]:g}"


def _edge(a, b) -> str:
    return f"M{_pt(a)}L{_pt(b)}"


MARKS: list[Mark] = [
    Mark(
        "half-wire-cube",
        "Half-Wire Cube",
        "solid vs wireframe object",
        "One object split down its own front edge: the real half solid, the twin half wireframe. "
        "The classic digital-twin picture and still a cube at 16 px; the catch is that objectdb's "
        "proposals are cubes too.",
        [
            F(f"M{_pt(_T)}L{_pt(_UL)}L{_pt(_C)}Z", "realfill"),
            F(f"M{_pt(_UL)}L{_pt(_LL)}L{_pt(_B)}L{_pt(_C)}Z", "realshade"),
            F(f"M{_pt(_T)}L{_pt(_UR)}L{_pt(_LR)}L{_pt(_B)}L{_pt(_C)}Z", "simfill"),
            # WHY one dashed path per edge: each edge then starts and ends on a corner, so the
            # wireframe keeps its corners at 16 px (a single long path put gaps on them).
            D(_edge(_T, _UR)),
            D(_edge(_UR, _LR)),
            D(_edge(_LR, _B)),
            D(_edge(_C, _UR)),
            S(f"M{_pt(_B)}L{_pt(_LL)}L{_pt(_UL)}L{_pt(_T)}"),
            S(f"M{_pt(_UL)}L{_pt(_C)}L{_pt(_B)}"),
        ],
        risk="lucide box / package (all solid); objectdb's cube proposals",
        tags=["object", "split"],
    ),
    Mark(
        "ghost-horn",
        "Ghost Horn",
        "servo horn with a ghost",
        "A servo output horn and its dashed ghost lagging behind: the rack's own question (where did the "
        "twin put the shaft?) drawn literally. Robotics-specific, and unlike anything in lucide.",
        [
            S(circle_d(7, 16.5, 3.2)),
            D("M10.09 15.67L20.6 12.85", dash=2.6, gap=3.6),
            S("M9.26 14.24L15.69 7.81"),
            S(circle_d(17.32, 6.18, 1.6)),
        ],
        tags=["servo", "ghost"],
    ),
    Mark(
        "approx-twin",
        "Approx Twin",
        "the ≈ sign, one line real",
        "sim ≈ real, literally: the top wave solid, the bottom wave dashed. Two strokes, reads at any size, "
        "and says 'close, not equal', which is what the tool measures.",
        [
            S("M3 9a7.5 7.5 0 0 1 9 0a7.5 7.5 0 0 0 9 0"),
            D("M3 15.5a7.5 7.5 0 0 1 9 0a7.5 7.5 0 0 0 9 0", dash=3.0, gap=4.2),
        ],
        risk="lucide equal-approximately (both lines solid)",
        tags=["math"],
    ),
    Mark(
        "wipe-split",
        "Wipe Split",
        "split / wipe half-and-half",
        "A view with a wipe bar through it: solid real half, dashed sim half, the wipe-between-views gesture "
        "itself. Strong idea, but Clank's ribbon already has split-pane icons that look like it.",
        [
            F("M12 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7Z", "realfill"),
            S("M12 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7"),
            D("M12 4h7a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-7", dash=2.6),
            S("M12 2v20", "aux"),
        ],
        risk="Clank's own Columns2 / SquareSplitHorizontal pane icons",
        tags=["split", "view"],
    ),
    Mark(
        "parity-plot",
        "Parity Plot",
        "measured vs predicted, y = x",
        "The engineer's sim-vs-real chart: points scattered about a dashed y = x line. Anyone who has "
        "validated a model has drawn this plot.",
        [
            S("M3 3v16a2 2 0 0 0 2 2h16", "aux"),
            D("M8 16L20 4", dash=2.8),
            S(circle_d(9.5, 9, 1)),
            S(circle_d(16, 13.5, 1)),
            S(circle_d(19.5, 9.6, 1)),
        ],
        risk="lucide chart-scatter",
        tags=["chart"],
    ),
    Mark(
        "overlap-venn",
        "Overlap Venn",
        "two overlapping circles",
        "Real and twin as two circles; the overlap is how twinned they are. Two strokes, unmistakable at 16 px.",
        [
            F(circle_d(8.5, 12, 6.3), "realfill"),
            S(circle_d(8.5, 12, 6.3)),
            D(circle_d(15.5, 12, 6.3), closed=True, phase=0.4, dash=2.6),
        ],
        tags=["overlap"],
    ),
    Mark(
        "twin-traces",
        "Twin Traces",
        "overlay of two traces",
        "A plot with the real trace solid and the sim trace dashed beside it: what every page of the tool actually shows.",
        [
            S("M3 3v16a2 2 0 0 0 2 2h16", "aux"),
            S("M7 14C9.4 14 10.4 6 13.2 6S17 13 21 11"),
            D("M7 16.5C9.8 16.5 10.9 9.5 13.8 9.5S17.6 15.5 21 14.5", dash=2.6),
        ],
        risk="lucide chart-spline",
        tags=["chart", "trace"],
    ),
    Mark(
        "floor-band",
        "Floor Band",
        "tolerance band",
        "The ruler itself: the error trace stays inside a dashed band, the device's own repeatability floor. "
        "Reads as 'within tolerance' to anyone who has read a control chart.",
        [
            D("M2 6.5h20", "sim", dash=3.0, gap=4.2),
            D("M2 17.5h20", "sim", dash=3.0, gap=4.2),
            S("M3 12c2.5-3.2 4.5-3.2 6 0s4 3.2 6 0 4.5-2.8 6-0.6"),
        ],
        tags=["ruler", "band"],
    ),
    Mark(
        "swap-arrows",
        "Swap Arrows",
        "⇄ between sim and real",
        "Real to sim on top, sim back to real below (dashed): the round trip, and the wipe between views.",
        [
            S("m16 3 4 4-4 4"),
            S("M20 7H4"),
            S("m8 21-4-4 4-4", "sim"),
            D("M4 17h16", dash=2.8),
        ],
        risk="lucide arrow-right-left",
        tags=["arrows"],
    ),
    Mark(
        "s2r-type",
        "s2r Type",
        "the type mark",
        "The name as a mark: s, 2, r on one baseline. In colour the s is the twin green, the 2 is grey "
        "and the r is the real paper.",
        [
            S("M7.5 10.6C7 9.6 6.1 9 4.9 9 3.5 9 2.5 9.8 2.5 11c0 2.7 5 1.4 5 4 0 1.2-1.1 2-2.6 2-1.2 0-2.1-.6-2.6-1.6", "sim"),
            S("M9.4 9.2C9.8 7.8 10.9 7 12.3 7 13.9 7 15 8 15 9.5c0 2.9-5.6 4.4-5.6 7.5H15", "aux"),
            S("M17.5 17V9"),
            S("M17.5 13c0-2.5 1.4-4 3.9-4"),
        ],
        tags=["type"],
        app_scale=8.5,
    ),
    Mark(
        "onion-skin",
        "Onion Skin",
        "onion-skin frames",
        "Animation onion-skinning: the real frame in front, two dashed sim frames trailing behind it. "
        "Reads as 'the same thing, a moment apart'.",
        [
            D("M2 10.5V4a2 2 0 0 1 2-2h6.5", dash=2.8, gap=4.2),
            D("M6 14.5V8a2 2 0 0 1 2-2h6.5", dash=2.8, gap=4.2),
            F(rect_d(10, 10, 11, 11, 2), "realfill"),
            S(rect_d(10, 10, 11, 11, 2)),
        ],
        risk="lucide layers / copy",
        tags=["ghost", "layers"],
    ),
    Mark(
        "twin-tiles",
        "Twin Tiles",
        "two Grid Purist tiles",
        "Two BAM tiles side by side, the twin's dashed, each holding its pixel, and the twin's pixel sits a "
        "little off. The BAM mark's own grammar, no stock icon looks like it, and no sibling app uses it.",
        [
            # WHY a 2-unit gap between the 8-unit tiles: after the strokes that leaves one stroke
            # of air, the BAM mark's own rule ("tile gap = one stroke"); 9-unit tiles touched.
            F(rect_d(2, 8, 8, 8, 1.5), "realfill"),
            S(rect_d(2, 8, 8, 8, 1.5)),
            # phase 0.612 centres a dash on every corner (corner midpoint 6.18 of a 7.36 period), so the
            # twin tile keeps its corners.
            D(rect_d(14, 8, 8, 8, 1.5), closed=True, phase=0.612, dash=3.35, gap=4.0),
            S("M6 12h.01", "aux"),
            S("M19 11h.01", "sim"),
        ],
        tags=["tiles", "family"],
        app_scale=9.0,  # WHY: the mark is only 8 units tall, so at 7.5 it floated small on the tile
    ),
    Mark(
        "delta-split",
        "Delta Split",
        "the Δ between sim and real",
        "Δ, the difference itself: two sides solid, one dashed. Minimal and mathematical; the error is the product.",
        [
            F("M12 3.5L2.8 20H12Z", "realfill"),
            S("M12 3.5L2.8 20H21.2"),
            D("M12 3.5L21.2 20", dash=3.2, gap=4.8),
        ],
        risk="lucide triangle (warning)",
        tags=["math"],
    ),
    Mark(
        "split-bot",
        "Split Bot",
        "robot, half twin",
        "A robot, half real and half wireframe. The most literal 'robot digital twin', but lucide's bot "
        "already means 'AI agent' in most toolbars.",
        [
            S("M12 8V4H8"),
            F("M12 8H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h6Z", "realfill"),
            S("M12 8H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h6"),
            D("M12 8h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-6", dash=2.4),
            S("M2 14h2"),
            S("M20 14h2", "sim"),
            S("M9 13v2", "aux"),
            S("M15 13v2", "sim"),
        ],
        risk="lucide bot (the usual 'agent' icon)",
        tags=["robot", "split"],
    ),
    Mark(
        "mirror-handle",
        "Mirror Handle",
        "reflection across a line",
        "A chevron and its reflection across a mirror line, the twin's dashed: ‹|›. It is also the "
        "handle you drag to wipe between the sim and real views.",
        [
            S("M12 3v18", "aux"),
            S("M8.5 6l-6 6 6 6"),
            D("M15.5 6l6 6-6 6", dash=2.6, gap=4.0),
        ],
        risk="lucide chevrons-left-right / unfold-horizontal",
        tags=["mirror", "wipe"],
    ),
    Mark(
        "ruler-gap",
        "Ruler Gap",
        "two pins on a ruler",
        "Two pins on a ruler, the real one solid and the twin's dashed: the gap between them is the error, "
        "read in ticks of the floor.",
        [
            S("M3 21h18", "aux"),
            S("M3 21v-3M7.5 21v-1.5M12 21v-3M16.5 21v-1.5M21 21v-3", "aux"),
            S(circle_d(8, 6, 2.2)),
            S("M8 8.2V15"),
            S(circle_d(16, 6, 2.2), "sim"),
            D("M16 8.2V15", dash=1.6, gap=3.2),
        ],
        risk="lucide ruler-dimension-line (loosely)",
        tags=["ruler"],
    ),
    Mark(
        "sync-loop",
        "Sync Loop",
        "closing the loop",
        "The sim-to-real loop as two arrows chasing each other: real to sim solid, sim back to real dashed. "
        "It is a loop, not a one-off check.",
        [
            S("M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"),
            S("M21 3v5h-5"),
            D("M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", dash=2.6),
            S("M8 16H3v5", "sim"),
        ],
        risk="lucide refresh-cw (reload)",
        tags=["arrows", "loop"],
    ),
    Mark(
        "double-check",
        "Double Check",
        "twinned = passed",
        "Two ticks: the real device passes, and the twin passes the same gate (dashed). The tool's verdict, twinned, as a mark.",
        [
            S("M2 10l4.5 4.5L15 6"),
            S("M9 17.5l4 4", "sim"),
            D("M13 21.5l9-9", dash=3.0, gap=4.4),
        ],
        risk="lucide check-check (read receipts)",
        tags=["verdict"],
    ),
    Mark(
        "reprojection",
        "Reprojection",
        "camera point vs projected twin point",
        "A camera's viewfinder with the detected point (solid) and where the twin projects it (dashed ring): "
        "reprojection error, the camera's version of the servo gap.",
        [
            S("M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2", "aux"),
            S(circle_d(9, 15, 1)),
            D(circle_d(14.5, 9.5, 3.2), closed=True, phase=0.15, dash=2.6, gap=4.0),
        ],
        risk="lucide scan / focus",
        tags=["camera", "sensor"],
    ),
    Mark(
        "sensor-echo",
        "Sensor Echo",
        "one sensor, two readings",
        "One sensor emitting two readings: the real one solid on the left, the twin's dashed on the right. "
        "Covers the cameras, IMUs and encoders, not just servos.",
        [
            S("M7.75 16.24a6 6 0 0 1 0-8.48M4.93 19.07a10 10 0 0 1 0-14.14"),
            D("M16.25 7.76a6 6 0 0 1 0 8.48", dash=2.8, gap=4.0),
            D("M19.07 4.93a10 10 0 0 1 0 14.14", dash=2.8, gap=4.0),
            S(circle_d(12, 12, 2)),
        ],
        risk="lucide radio (broadcast)",
        tags=["sensor"],
    ),
]

assert len(MARKS) == 20, len(MARKS)
assert len({m.slug for m in MARKS}) == len(MARKS)


# ----------------------------------------------------------------------------------------
# Criteria first, then the scores (AI judgement, 1-5 each; not measured).
# ----------------------------------------------------------------------------------------
CRITERIA = [
    ("says", "Says sim vs real", 30, "Would someone guess 'twin vs hardware' before reading the tooltip?"),
    ("r16", "Reads at 16 px", 25, "Survives Clank's 16 px ribbon slot at device pixel ratio 1."),
    ("own", "Not a stock icon", 20, "Can't be mistaken for a lucide icon already common in toolbars, or for a sibling app."),
    ("fam", "Family fit", 15, "Belongs with BAM Grid Purist, robotparts and objectdb."),
    ("few", "Few strokes", 10, "Simple enough to redraw from memory."),
]

SCORES: dict[str, dict[str, int]] = {
    "twin-tiles": dict(says=4, r16=4, own=5, fam=5, few=4),
    "half-wire-cube": dict(says=5, r16=4, own=4, fam=4, few=3),
    "approx-twin": dict(says=4, r16=5, own=3, fam=3, few=5),
    "overlap-venn": dict(says=3, r16=4, own=5, fam=3, few=5),
    "ruler-gap": dict(says=4, r16=4, own=4, fam=3, few=3),
    "s2r-type": dict(says=3, r16=4, own=5, fam=3, few=4),
    "mirror-handle": dict(says=3, r16=5, own=3, fam=3, few=5),
    "floor-band": dict(says=4, r16=3, own=5, fam=2, few=4),
    "wipe-split": dict(says=4, r16=4, own=2, fam=4, few=4),
    "ghost-horn": dict(says=4, r16=3, own=4, fam=3, few=4),
    "delta-split": dict(says=3, r16=4, own=3, fam=4, few=5),
    "swap-arrows": dict(says=3, r16=5, own=2, fam=2, few=4),
    "sensor-echo": dict(says=3, r16=4, own=3, fam=2, few=4),
    "parity-plot": dict(says=4, r16=3, own=3, fam=2, few=3),
    "twin-traces": dict(says=4, r16=3, own=3, fam=2, few=3),
    "reprojection": dict(says=4, r16=3, own=3, fam=2, few=3),
    "sync-loop": dict(says=3, r16=4, own=2, fam=2, few=4),
    "onion-skin": dict(says=3, r16=3, own=3, fam=3, few=3),
    "double-check": dict(says=3, r16=4, own=2, fam=2, few=4),
    "split-bot": dict(says=4, r16=3, own=1, fam=2, few=2),
}


def score(slug: str) -> int:
    return round(sum(SCORES[slug][key] * weight for key, _, weight, _ in CRITERIA) / 5)


# Number the marks by score, best first (ties keep the order of SCORES above), so 01 is the pick.
_rank = {slug: i for i, slug in enumerate(SCORES)}
MARKS.sort(key=lambda m: (-score(m.slug), _rank[m.slug]))
assert set(SCORES) == {m.slug for m in MARKS}
