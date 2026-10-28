"""Criteria first, then the scores (AI judgement, 1-5 each, not measured). R4-01 is the recommendation."""

from __future__ import annotations

from marks4 import R4

CRITERIA = [
    ("dir", "His direction", 30, "'more progressively change into the gear' or 'the cut outs should be more blocked'."),
    ("small", "Holds up small", 25, "The one-colour silhouette still reads at 16 px: a gear, and blocks becoming it."),
    ("keep", "Still Assemble", 15, "Still the idea he picked: blocks converging into the machined gear."),
    ("simp", "Simplifies to the icon", 15, "A clear path to the 24 px toolbar mark."),
    ("fresh", "A real variant", 15, "Clearly different from R3-04 and from the other nine."),
]

SCORES: dict[str, dict[str, int]] = {
    "resolution-ramp": dict(dir=5, small=4, keep=4, simp=4, fresh=5),
    "stair-cut": dict(dir=5, small=4, keep=5, simp=4, fresh=4),
    "density-ramp": dict(dir=5, small=4, keep=5, simp=3, fresh=4),
    "size-ramp": dict(dir=5, small=4, keep=5, simp=3, fresh=4),
    "snap-fit": dict(dir=4, small=5, keep=4, simp=5, fresh=3),
    "teeth-arriving": dict(dir=4, small=4, keep=4, simp=4, fresh=4),
    "vertical-drop": dict(dir=4, small=4, keep=4, simp=4, fresh=4),
    "blocky-steps": dict(dir=4, small=4, keep=3, simp=4, fresh=4),
    "square-holes": dict(dir=4, small=3, keep=4, simp=3, fresh=5),
    "radial-hub": dict(dir=3, small=4, keep=3, simp=4, fresh=5),
}
assert set(SCORES) == {lg.slug for lg in R4}


def score(slug: str) -> int:
    return round(sum(SCORES[slug][k] * w for k, _, w, _ in CRITERIA) / 5)


def ordered():
    rank = {slug: i for i, slug in enumerate(SCORES)}
    return sorted(R4, key=lambda lg: (-score(lg.slug), rank[lg.slug]))
