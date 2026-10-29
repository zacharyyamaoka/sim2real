"""Criteria first, then the scores (AI judgement, 1-5 each, not measured). R5-01 is the recommendation."""

from __future__ import annotations

from marks5 import R5

CRITERIA = [
    ("dir", "Pixels match the gear", 30, "His ask: the pixel side reads as the same gear, not a rectangular block field."),
    ("small", "Holds up small", 25, "The one-colour silhouette still reads at 16 px."),
    ("keep", "Still Density Ramp", 15, "Still a dither that gets denser until it is steel."),
    ("simp", "Simplifies to the icon", 15, "A clear path to the 24 px toolbar mark."),
    ("fresh", "A real variant", 15, "Clearly different from R4-03 and the other four."),
]

SCORES: dict[str, dict[str, int]] = {
    "quantised-silhouette": dict(dir=5, small=5, keep=5, simp=4, fresh=4),
    "clipped-dither": dict(dir=5, small=4, keep=5, simp=4, fresh=4),
    "outlined-dither": dict(dir=5, small=5, keep=4, simp=4, fresh=4),
    "tooth-pixels": dict(dir=4, small=4, keep=4, simp=4, fresh=4),
    "polar-dither": dict(dir=5, small=3, keep=4, simp=3, fresh=5),
}
assert set(SCORES) == {lg.slug for lg in R5}


def score(slug: str) -> int:
    return round(sum(SCORES[slug][k] * w for k, _, w, _ in CRITERIA) / 5)


def ordered():
    rank = {slug: i for i, slug in enumerate(SCORES)}
    return sorted(R5, key=lambda lg: (-score(lg.slug), rank[lg.slug]))
