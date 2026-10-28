"""Criteria first, then the scores (AI judgement, 1-5 each, not measured; "small" re-judged on the simplified marks' silhouettes). The order of SCORES breaks
ties, and R3-01 (the first after sorting) is the recommendation."""

from __future__ import annotations

from marks3 import R3

CRITERIA = [
    ("fav", "His favourites", 30, "Builds on what he liked in round 2: the dither going off into pixelated land, the breakout, viewfinder and loupe."),
    ("small", "Holds up small", 25, "Still a gear with a digital part at 32 px, and at least a shape at 16 px (favicon, sidebar)."),
    ("simp", "Simplifies to the icon", 15, "A clear path to the 24 px toolbar mark later."),
    ("own", "Its own", 15, "Not a stock settings gear, and not confusable with c2r or another x2y sibling."),
    ("fun", "Fun", 15, "His word for Breakout: it has energy, it would make someone smile."),
]

SCORES: dict[str, dict[str, int]] = {
    "dissolve-trail": dict(fav=5, small=5, simp=4, own=4, fun=5),
    "loupe-2": dict(fav=5, small=5, simp=4, own=4, fun=4),
    "viewfinder-brackets": dict(fav=5, small=5, simp=5, own=4, fun=3),
    "assemble": dict(fav=5, small=4, simp=4, own=4, fun=4),
    "exploded-half": dict(fav=5, small=4, simp=4, own=4, fun=4),
    "frame-spill": dict(fav=5, small=4, simp=4, own=4, fun=4),
    "dither-sweep-2": dict(fav=5, small=4, simp=4, own=4, fun=3),
    "breakout-2": dict(fav=5, small=4, simp=3, own=4, fun=5),
    "screen-dissolve": dict(fav=5, small=3, simp=3, own=4, fun=5),
    "ghost-tile": dict(fav=4, small=4, simp=4, own=4, fun=4),
    "phone-ar": dict(fav=5, small=3, simp=3, own=4, fun=4),
    "dither-loupe": dict(fav=5, small=3, simp=2, own=4, fun=5),
    "upward-drift": dict(fav=4, small=4, simp=3, own=4, fun=4),
    "gear-badge": dict(fav=4, small=4, simp=3, own=5, fun=3),
    "tile-monogram": dict(fav=4, small=4, simp=4, own=4, fun=3),
    "teeth-to-pixels": dict(fav=4, small=5, simp=5, own=4, fun=3),
    "pixel-wake": dict(fav=4, small=3, simp=3, own=4, fun=4),
    "lens-flip": dict(fav=4, small=3, simp=3, own=4, fun=4),
    "s2r-dissolve": dict(fav=4, small=3, simp=3, own=4, fun=4),
    "window-breakout": dict(fav=4, small=3, simp=3, own=3, fun=4),
}
assert set(SCORES) == {lg.slug for lg in R3}


def score(slug: str) -> int:
    return round(sum(SCORES[slug][k] * w for k, _, w, _ in CRITERIA) / 5)


def ordered():
    rank = {slug: i for i, slug in enumerate(SCORES)}
    return sorted(R3, key=lambda lg: (-score(lg.slug), rank[lg.slug]))
