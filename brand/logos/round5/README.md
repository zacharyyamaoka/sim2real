# sim2real logos, round 5: five variants of Density Ramp

Zach, 2026-10-28: "Make 5 variants of the Density Ramp but make the shape of the pixel better match the gear shape."

- **Recommendation: R5-01 Quantised Silhouette.** The reference, R4-03 Density Ramp, is first on the page; its files stay
  in `../round4/`. The toolbar icon `brand/icons/sim2real.svg` stays Clank's default until a logo is picked and simplified.
- **The wordmark is untouched** (pixel 'sim', grey '2', set 'real'); only the mark changes.
- **The pixel side is now the gear itself:** clipped to the outline, on a polar grid, quantised to whole pixels, with
  pixel teeth on the real teeth, and an outlined fill. Round 3's rules hold (chunky 8-tooth gear, big blocks, one-colour
  silhouette at 16/24/32 px, light and dark).
- **Pick page:** `/home/bam/sim2real/reports/sim2real-logos-r5-2026-10-28.html` (R4-03 first, the top pick, then all five in
  a site header, tab strip, dock and Clank's sidebar, light and dark).
- **Files:** `NN-<slug>.svg`, `-dark.svg`, `-lockup.svg`, `-lockup-dark.svg`; `preview/NN-<slug>-16.png`, `-32.png`,
  `-mono-{16,24,32}.png` (each also `-dark`); `00-density-ramp-*` previews are R4-03's.

Scores are AI judgement, 1-5 per criterion, weighted (Pixels match the gear 30, Holds up small 25, Still Density Ramp 15, Simplifies to the icon 15, A real variant 15); not measured.

| # | name | family | score | why |
|---|---|---|---|---|
| R5-01 | **Quantised Silhouette** | quantised | 94 | The gear's outline quantised onto the pixel grid: stepped teeth that read as the same gear, densifying into steel. |
| R5-02 | **Outlined Dither** | outline | 91 | Own idea: keep the whole outline, dither only the fill. The silhouette is a complete gear at any size. |
| R5-03 | **Clipped Dither** | outline | 89 | The same dither as R4-03, but only inside the gear: the left half is the gear itself in pixels, cut on its real outline. |
| R5-04 | **Polar Dither** | polar | 81 | The pixels follow the gear's own geometry: curved blocks round the hub and body, and each tooth is a block. |
| R5-05 | **Tooth Pixels** | teeth | 80 | The pixel teeth line up with the real teeth, so the gear's shape survives even where the body is sparse. |

## Rebuild

```bash
uv run --no-project --with playwright --with pillow python /home/bam/sim2real/brand/logos/round5/render5.py --out /tmp/s2r-r5 --previews
```

```bash
python3 /home/bam/sim2real/brand/logos/round5/build5.py
```

Source: `marks5.py` (the five, on round 3's kit in `../round3/marks3.py`), `scores5.py`, `render5.py`, `build5.py`.
