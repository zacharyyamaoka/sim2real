# sim2real logos, round 4: ten variants of Assemble

Zach, 2026-10-28: "Ok I like assemble the most. can you please make like 10 different variants on it though: I like the
sim2real text that perfect keep that but please kinda change how the assemble looks. I feel like it needs to kinda more
progressively change into the gear as one of the options.. like maybe the cut outs should be more blocked? idk make 10
more variants."

- **Recommendation: R4-01 Resolution Ramp.** The reference, R3-04 Assemble, is first on the page; its files stay in
  `../round3/`. The toolbar icon `brand/icons/sim2real.svg` (round 1) stays Clank's default until a logo is picked and
  simplified.
- **The wordmark is untouched:** the same 'sim2real' lockup as R3-04 (pixel 'sim', grey '2', set 'real'). Only the mark changes.
- **Three families:** progressive (size, resolution, density, teeth arriving), blocked cut-outs (square holes, a stepped
  steel silhouette, a clean staircase cut), and composition (from above, radially into the hub, a tight snap-fit).
- **Round 3's simplicity rules hold:** one chunky 8-tooth gear, big blocks, flat steel, thick shapes, and a one-colour
  silhouette at 16, 24 and 32 px, light and dark.
- **Pick page:** `/home/bam/sim2real/reports/sim2real-logos-r4-2026-10-28.html`: R3-04 first, the top 3, then all ten, each in
  a website header, a tab strip (16 and 32 px), a desktop and dock, and Clank's sidebar, light and dark.
- **Files:** `NN-<slug>.svg`, `-dark.svg`, `-lockup.svg`, `-lockup-dark.svg`; `preview/NN-<slug>-16.png`, `-32.png`,
  `-mono-{16,24,32}.png` (each also `-dark`); `00-assemble-*` previews are R3-04's.

Scores are AI judgement, 1-5 per criterion, weighted (His direction 30, Holds up small 25, Still Assemble 15, Simplifies to the icon 15, A real variant 15); not measured.

| # | name | family | score | why |
|---|---|---|---|---|
| R4-01 | **Resolution Ramp** | progressive | 89 | Progressive by resolution: the gear is coarse green pixels on the left, finer steel-grey ones in the middle, machined on the right. |
| R4-02 | **Stair Cut** | blocked | 89 | R3-04 made orderly: the cut-out is a clean staircase, and the missing cells sit in their rows, sliding back into it. |
| R4-03 | **Density Ramp** | progressive | 86 | Progressive by density: sparse blocks far left, denser toward the gear, until they close up into the part. His dither, run into the gear. |
| R4-04 | **Size Ramp** | progressive | 86 | Progressive by size: tiny blocks far left, bigger ones nearer, full-size blocks in the gear's own columns, then steel. |
| R4-05 | **Snap Fit** | composition | 85 | The tightest gap: the gear is whole in outline, its left half in big blocks, and one block still sliding into its slot. |
| R4-06 | **Teeth Arriving** | progressive | 80 | Blocks as gear parts: each missing tooth on the left is a block on its way to its own socket. |
| R4-07 | **Vertical Drop** | composition | 80 | Composition: assembly from above, like blocks dropping into place. Taller mark, same idea. |
| R4-08 | **Blocky Steps** | blocked | 77 | The gear's own outline in steps: the left half is the same steel gear drawn on a coarse grid, the right half machined. |
| R4-09 | **Square Holes** | blocked | 75 | Blocked cut-outs, literally: the gear's left side has square holes, fewer toward the right, and the missing squares are flying in. |
| R4-10 | **Radial Hub** | composition | 74 | Composition: assembly into the hub. Two teeth are seated; the rest come in along their own radii, the furthest on the left. |

## Rebuild

```bash
uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round4/render4.py --out /tmp/s2r-r4 --previews
```

```bash
python3 /home/bam/sim2real/brand/logos/round4/build4.py
```

Source: `marks4.py` (the ten, on round 3's kit in `../round3/marks3.py`), `scores4.py`, `render4.py`, `build4.py`.
