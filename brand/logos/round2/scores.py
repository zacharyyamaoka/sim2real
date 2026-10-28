"""Criteria first, then the scores. AI judgement, 1-5 per criterion, not measured; they set the numbering."""

from __future__ import annotations

import pathlib

from logos import LOGOS
from s2r_logos import S2R

HERE = pathlib.Path(__file__).resolve().parent

CRITERIA = [
    ("his", "His picture", 30, "A gear on a screen vs the gear in real life, or pixel vs analog, as Zach described it on 2026-10-28."),
    ("r32", "Reads at 32 px", 25, "Still a gear, and still two halves, at 32 px."),
    ("simp", "Simplifies to the icon", 20, "A clear path to a 24 px lucide mark later, without losing the idea."),
    ("fam", "Family fit", 15, "BAM Grid Purist: square pixels, ink and paper, one green."),
    ("dist", "Distinct", 10, "Memorable, and unlike a stock settings-gear icon."),
]

SCORES: dict[str, dict[str, int]] = {
    "split-gear": dict(his=4, r32=5, simp=5, fam=5, dist=4),
    "screen-hub": dict(his=4, r32=5, simp=5, fam=4, dist=5),
    "half-screen": dict(his=5, r32=4, simp=4, fam=4, dist=3),
    "dashed-frame": dict(his=5, r32=4, simp=4, fam=4, dist=3),
    "mesh-metal": dict(his=4, r32=4, simp=4, fam=3, dist=4),
    "dither-sweep": dict(his=4, r32=4, simp=3, fam=4, dist=4),
    "pixel-shadow": dict(his=3, r32=4, simp=4, fam=4, dist=4),
    "wipe-slider": dict(his=5, r32=3, simp=3, fam=3, dist=3),
    "meshing-pair": dict(his=3, r32=4, simp=4, fam=4, dist=3),
    "overlay-offset": dict(his=3, r32=4, simp=4, fam=3, dist=3),
    "breakout": dict(his=4, r32=3, simp=3, fam=3, dist=4),
    "crt-cutaway": dict(his=4, r32=3, simp=3, fam=3, dist=4),
    "wireframe-twin": dict(his=5, r32=3, simp=2, fam=3, dist=3),
    "viewfinder": dict(his=4, r32=3, simp=3, fam=3, dist=4),
    "side-by-side": dict(his=5, r32=3, simp=2, fam=3, dist=2),
    "circuit-cast": dict(his=3, r32=4, simp=3, fam=2, dist=5),
    "reflection": dict(his=4, r32=3, simp=2, fam=3, dist=3),
    "loupe": dict(his=3, r32=3, simp=3, fam=3, dist=4),
    "sim-floor": dict(his=3, r32=3, simp=2, fam=3, dist=4),
    "lod-sectors": dict(his=3, r32=2, simp=2, fam=3, dist=4),
}
assert set(SCORES) == {lg.slug for lg in LOGOS}


def score(slug: str) -> int:
    return round(sum(SCORES[slug][k] * w for k, _, w, _ in CRITERIA) / 5)


def ordered():
    """Best first; ties keep the order of SCORES above."""
    rank = {slug: i for i, slug in enumerate(SCORES)}
    return sorted(LOGOS, key=lambda lg: (-score(lg.slug), rank[lg.slug]))


# ---------------------------------------------------------------------------------------------
# The s2r type logos: the same five criteria, the first one read as "the letters cross from
# digital to real"; scored separately and numbered separately.
# ---------------------------------------------------------------------------------------------
S2R_SCORES: dict[str, dict[str, int]] = {
    "two-boundary": dict(his=5, r32=4, simp=4, fam=4, dist=5),
    "res-ramp": dict(his=5, r32=4, simp=4, fam=5, dist=3),
    "s2r-tiles": dict(his=4, r32=4, simp=5, fam=5, dist=4),
    "dither-fade": dict(his=5, r32=4, simp=3, fam=4, dist=4),
    "type-wipe": dict(his=5, r32=4, simp=3, fam=4, dist=4),
    "led-matrix": dict(his=4, r32=4, simp=4, fam=4, dist=4),
    "metal-r": dict(his=4, r32=4, simp=4, fam=4, dist=3),
    "pixel-shadow-type": dict(his=4, r32=4, simp=4, fam=4, dist=3),
    "screen-escape": dict(his=5, r32=3, simp=3, fam=3, dist=4),
    "glitch-print": dict(his=4, r32=4, simp=3, fam=3, dist=4),
    "nameplate": dict(his=4, r32=3, simp=3, fam=3, dist=5),
    "halftone-fade": dict(his=4, r32=3, simp=3, fam=3, dist=4),
    "mesh-s": dict(his=3, r32=4, simp=3, fam=3, dist=3),
    "subpixel": dict(his=4, r32=3, simp=3, fam=2, dist=4),
    "circuit-s": dict(his=3, r32=4, simp=3, fam=2, dist=4),
    "stencil-r": dict(his=3, r32=3, simp=3, fam=3, dist=4),
    "vector-handles": dict(his=3, r32=3, simp=3, fam=3, dist=4),
    "wire-solid": dict(his=3, r32=3, simp=3, fam=3, dist=3),
    "gear-two": dict(his=4, r32=2, simp=2, fam=3, dist=4),
    "mirror-line": dict(his=3, r32=3, simp=2, fam=3, dist=3),
}
assert set(S2R_SCORES) == {lg.slug for lg in S2R}

# For the s2r set the first criterion reads: the letters themselves cross from digital to real
# ("fades from like pixel to real, maybe in one its like in a computer screen").
S2R_HIS = "The letters themselves cross from digital to real: 'fades from like pixel to real, maybe in one its like in a computer screen'."


def s2r_score(slug: str) -> int:
    return round(sum(S2R_SCORES[slug][k] * w for k, _, w, _ in CRITERIA) / 5)


def s2r_ordered():
    rank = {slug: i for i, slug in enumerate(S2R_SCORES)}
    return sorted(S2R, key=lambda lg: (-s2r_score(lg.slug), rank[lg.slug]))


SETS = {"gear": (ordered(), HERE), "s2r": (s2r_ordered(), HERE / "s2r")}
