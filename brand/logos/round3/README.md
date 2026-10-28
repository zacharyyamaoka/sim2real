# sim2real logos, round 3

Zach, 2026-10-28, on round 2: "The dither sweep one is really cool I can imagine like that design often used where it
shows something like turning pixeled and then kinda like going off into pixelated land ... you kinda like leave out
certain of the pixels... I really like the break out one it looks like an extra really fun: similar idea with the view
finder and loupe: That one is very strong I think. I think the s2r thing is also like a decent thing ... The issue though
is ... if you have s2r c2r like visually they start to look very very similar. ... Please show as we did for previous
logo design what it looks like in the top left of the website, as a favicon, as a desktop icon, etc"

- **Recommendation: R3-01 Dissolve Trail.** Nothing is simplified into the toolbar icon yet; `brand/icons/sim2real.svg`
  (round 1) stays Clank's default until a logo is picked and simplified.
- **Pick page:** `/home/bam/sim2real/reports/sim2real-logos-r3-2026-10-28.html`: his round-2 favourites at the top, the
  c2r check, then all 20, each in a website header, a browser tab strip (16 and 32 px), a dock and desktop, and Clank's
  Workspaces sidebar (three styles, light and dark) next to Robot Parts and BAM Robotics.
- **Spread:** 7 dissolve (the real gear breaking into pixels, pixels left out, pixels drifting off), 6 frame (breakout,
  loupe, phone, viewfinder, window), 4 hybrids, 3 text-led marks that carry the dissolve.
- **Simplified** ("their level of detail is a bit too high ... look good kinda from a silhouette, and smaller"): one chunky
  8-tooth gear, blocks about five across the gear, flat steel with a thick rim, thick frames; no lathe rings, bevels,
  screen grids or glare. Every mark has a one-colour mode, rendered as `preview/NN-<slug>-mono-{16,24,32}[-dark].png`.
- **c2r check** (16 px greyscale, mean difference from a plain 'c2r' set in the same face): a plain 's2r' differs by
  3.4%; the three text-led marks by 11.6% (s2r Dissolve), 18.4%
  (Gear Badge) and 44.0% (Tile Monogram); every gear mark by at least
  11.6%.
- **Files:** `NN-<slug>.svg`, `-dark.svg`, `-lockup.svg`, `-lockup-dark.svg`; `preview/NN-<slug>-16.png`, `-32.png`
  (and `-dark`), cropped to the ink as a favicon would be; `preview/NN-<slug>-mono-{16,24,32}.png` (and `-dark`), the silhouettes.

Scores are AI judgement, 1-5 per criterion, weighted (His favourites 30, Holds up small 25, Simplifies to the icon 15, Its own 15, Fun 15); not measured. "vs c2r" is the measured check above.

| # | name | kind | score | vs c2r | why |
|---|---|---|---|---|---|
| R3-01 | **Dissolve Trail** | dissolve | 94 | 14% | His 'turning pixeled and then going off into pixelated land': the gear's right side breaks into blocks, some left out, the rest drifting away. A gear plus a trail of squares, even as a silhouette. |
| R3-02 | **Loupe II** | frame | 91 | 22% | G18 simplified: a thick loupe over the teeth, and inside it the same teeth as a few big blocks. |
| R3-03 | **Viewfinder Brackets** | frame | 91 | 20% | A viewfinder with no device: four brackets, blocks inside, metal outside. The simplest frame, and it holds as a silhouette. |
| R3-04 | **Assemble** | dissolve | 86 | 15% | The dissolve run backwards so it reads sim → real: blocks gathering from the left and becoming the real part. |
| R3-05 | **Exploded Half** | dissolve | 86 | 15% | Split gear meets dissolve: the right half blown outward into blocks, an exploded view of the twin. |
| R3-06 | **Frame Spill** | hybrid | 86 | 18% | Viewfinder plus dissolve: the blocks can't stay in the frame and leak out of its right side. |
| R3-07 | **Breakout II** | frame | 86 | 23% | G11 made bolder: a thick-framed screen, the gear blocky inside it and metal where it smashes out of the corner. |
| R3-08 | **Teeth to Pixels** | dissolve | 85 | 16% | Only the teeth go: each tooth on the right comes off as one square. The simplest dissolve, and it holds at 16 px. |
| R3-09 | **Dither Sweep II** | dissolve | 83 | 15% | His round-2 favourite with the noise taken out: the gear keeps its outline and its right half is a few big blocks with gaps. |
| R3-10 | **Screen Dissolve** | hybrid | 81 | 28% | Breakout in reverse, plus the dissolve: half the gear is in the room, the half inside the screen breaks into blocks. |
| R3-11 | **Ghost Tile** | hybrid, tile | 80 | 45% | Built as an app tile from the start: the gear half metal, its blocks escaping over the tile's edge. |
| R3-12 | **Phone AR** | frame | 78 | 23% | G14 as a phone: the real gear behind, a thick tilted phone in front, the same gear in blocks on its screen. |
| R3-13 | **Dither Loupe** | hybrid | 78 | 18% | Dissolve plus loupe: the gear goes off into blocks, and the loupe follows them to check. |
| R3-14 | **Upward Drift** | dissolve | 77 | 16% | The same break-up going up: the top teeth lift off as blocks and float away. |
| R3-15 | **Gear Badge** | text | 77 | 18% | The gear carries the text: s2r in a disc at the centre of a chunky gear that breaks into blocks on its right. |
| R3-16 | **Tile Monogram** | text, tile | 77 | 44% | App-icon form: the monogram for quick reading, the breaking gear as the hook that tells it from c2r. |
| R3-17 | **Pixel Wake** | dissolve | 72 | 14% | Motion: the real gear rolling right, two fading block ghosts behind it. Real, coming out of the sim. |
| R3-18 | **Lens Flip** | frame | 72 | 39% | Loupe reversed: the twin is blocks, and looking closely shows the real machined part. |
| R3-19 | **s2r Dissolve** | text | 72 | 12% | Text you read at once with its own hook: the s breaks up into blocks drifting off left. A plain c2r can't look like this. |
| R3-20 | **Window Breakout** | frame | 69 | 25% | Breakout with an app window: a solid title bar, blocks inside, the real gear pushing out the side. |

## Rebuild

```bash
uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round3/render3.py --out /tmp/s2r-r3 --previews
```

```bash
python3 /home/bam/sim2real/brand/logos/round3/build3.py
```

Source: `marks3.py` (the 20, built on round 2's `geom.py`), `scores3.py`, `c2r.py` (the check), `render3.py`, `build3.py`.
