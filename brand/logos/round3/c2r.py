"""The c2r check: would a sim2real text mark be mistaken for cad2robot's ('c2r')?

Plain 's2r' and 'c2r' are set in the same face as the type logos (Ubuntu Sans 800), so the check
compares like with like. The 'c' outline is baked once into c_glyph.json (run this file to re-bake):

    uv run --no-project --with fonttools python /home/bam/sim2real/brand/logos/round3/c2r.py
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "round2"))
from s2r_type import GLYPHS as S2R_GLYPHS  # noqa: E402

C_GLYPH = HERE / "c_glyph.json"
FONT = "/usr/share/fonts/truetype/ubuntu/UbuntuSans[wdth,wght].ttf"
CAD2ROBOT_FAVICON = pathlib.Path("/home/bam/cad2robot-website/public/favicon.svg")


def bake() -> None:
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    font = instancer.instantiateVariableFont(TTFont(FONT), {"wght": 800, "wdth": 100})
    gs = font.getGlyphSet()
    name = font.getBestCmap()[ord("c")]
    pen = SVGPathPen(gs)
    gs[name].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
    C_GLYPH.write_text(json.dumps({"d": pen.getCommands(), "adv": font["hmtx"][name][0]}))
    print(f"baked {C_GLYPH}")


def plain_word(word: str, colour: str, width: float = 440, baseline: float = 340) -> str:
    """'s2r' or 'c2r' as plain set type on the 512 artboard: the problem case."""
    glyphs = json.loads(S2R_GLYPHS.read_text())["glyphs"]
    glyphs["c"] = json.loads(C_GLYPH.read_text())
    advs = [glyphs[c]["adv"] for c in word]
    k = width / sum(advs)
    x = 256 - width / 2
    out = []
    for c, a in zip(word, advs):
        out.append(f'<path transform="translate({x:.2f} {baseline}) scale({k:.5f})" d="{glyphs[c]["d"]}" fill="{colour}"/>')
        x += a * k
    return "".join(out)


def cad2robot_favicon() -> str:
    return CAD2ROBOT_FAVICON.read_text()


if __name__ == "__main__":
    bake()
