# sim2real icons

Twenty proposals for the sim2real app icon (Zach, 2026-10-27: "Please make 20 proposals for a simple icon for sim2real").

- **Default until Zach picks: 01 Twin Tiles.** `sim2real.svg` (toolbar) and `sim2real-app.svg` (app/dock) are copies of
  `proposals/01-twin-tiles.svg` and `proposals/01-twin-tiles-app.svg`. Picking another number means rebuilding with that
  mark first in `marks.py`.
- **Pick surface:** `/home/bam/sim2real/reports/sim2real-icons-2026-10-27.html` (every mark at 16 / 24 / 48 px in a mock
  Clank ribbon, dark and light, the 256 px app icon, a pick toggle and comment per mark, and "Copy my picks").

## The rules every mark follows

- **Toolbar mark = a lucide icon:** 24×24 viewBox, `stroke="currentColor"`, `stroke-width="2"`, round caps and joins, no
  fill, so it sits in Clank's ribbon (`ctx.registerRibbonItem({ icon })` takes a `LucideIcon`) beside stock icons.
- **Solid stroke = the real device, dashed stroke = the twin.** Dashes are explicit short paths that start and end on
  the path's own corners (lucide's `square-dashed` convention), never a `stroke-dasharray` that can drop a corner.
- **App icon = the same strokes on a Grid Purist tile:** ink `#0E100E` tile with the BAM mark's micro radius (12/256),
  the real part in paper `#FBFBF8`, the twin in green, helper lines in grey.
- **Green on the ink tile is `#35DE95`,** BAM Green `#2F6F4F`'s own hue lifted to OKLCH L 0.80: `#2F6F4F`
  is 3.2:1 on ink, too faint for a dashed line in a dock; the lit one is 11:1. On a paper tile the brand green
  `#2F6F4F` is used as decided on 2026-10-24 (the report's palette switch shows both).

## The twenty

Numbered by score, best first. Scores are AI judgement, 1-5 per criterion, weighted (Says sim vs real 30, Reads at 16 px 25, Not a stock icon 20, Family fit 15, Few strokes 10); not measured.

| # | name | metaphor | score | why |
|---|---|---|---|---|
| 01 | **Twin Tiles** | two Grid Purist tiles | 87 | Two BAM tiles side by side, the twin's dashed, each holding its pixel, and the twin's pixel sits a little off. The BAM mark's own grammar, no stock icon looks like it, and no sibling app uses it. |
| 02 | **Half-Wire Cube** | solid vs wireframe object | 84 | One object split down its own front edge: the real half solid, the twin half wireframe. The classic digital-twin picture and still a cube at 16 px; the catch is that objectdb's proposals are cubes too. |
| 03 | **Approx Twin** | the ≈ sign, one line real | 80 | sim ≈ real, literally: the top wave solid, the bottom wave dashed. Two strokes, reads at any size, and says 'close, not equal', which is what the tool measures. |
| 04 | **Overlap Venn** | two overlapping circles | 77 | Real and twin as two circles; the overlap is how twinned they are. Two strokes, unmistakable at 16 px. |
| 05 | **Ruler Gap** | two pins on a ruler | 75 | Two pins on a ruler, the real one solid and the twin's dashed: the gap between them is the error, read in ticks of the floor. |
| 06 | **s2r Type** | the type mark | 75 | The name as a mark: s, 2, r on one baseline. In colour the s is the twin green, the 2 is grey and the r is the real paper. |
| 07 | **Mirror Handle** | reflection across a line | 74 | A chevron and its reflection across a mirror line, the twin's dashed: ‹\|›. It is also the handle you drag to wipe between the sim and real views. |
| 08 | **Floor Band** | tolerance band | 73 | The ruler itself: the error trace stays inside a dashed band, the device's own repeatability floor. Reads as 'within tolerance' to anyone who has read a control chart. |
| 09 | **Wipe Split** | split / wipe half-and-half | 72 | A view with a wipe bar through it: solid real half, dashed sim half, the wipe-between-views gesture itself. Strong idea, but Clank's ribbon already has split-pane icons that look like it. |
| 10 | **Ghost Horn** | servo horn with a ghost | 72 | A servo output horn and its dashed ghost lagging behind: the rack's own question (where did the twin put the shaft?) drawn literally. Robotics-specific, and unlike anything in lucide. |
| 11 | **Delta Split** | the Δ between sim and real | 72 | Δ, the difference itself: two sides solid, one dashed. Minimal and mathematical; the error is the product. |
| 12 | **Swap Arrows** | ⇄ between sim and real | 65 | Real to sim on top, sim back to real below (dashed): the round trip, and the wipe between views. |
| 13 | **Sensor Echo** | one sensor, two readings | 64 | One sensor emitting two readings: the real one solid on the left, the twin's dashed on the right. Covers the cameras, IMUs and encoders, not just servos. |
| 14 | **Parity Plot** | measured vs predicted, y = x | 63 | The engineer's sim-vs-real chart: points scattered about a dashed y = x line. Anyone who has validated a model has drawn this plot. |
| 15 | **Twin Traces** | overlay of two traces | 63 | A plot with the real trace solid and the sim trace dashed beside it: what every page of the tool actually shows. |
| 16 | **Reprojection** | camera point vs projected twin point | 63 | A camera's viewfinder with the detected point (solid) and where the twin projects it (dashed ring): reprojection error, the camera's version of the servo gap. |
| 17 | **Sync Loop** | closing the loop | 60 | The sim-to-real loop as two arrows chasing each other: real to sim solid, sim back to real dashed. It is a loop, not a one-off check. |
| 18 | **Onion Skin** | onion-skin frames | 60 | Animation onion-skinning: the real frame in front, two dashed sim frames trailing behind it. Reads as 'the same thing, a moment apart'. |
| 19 | **Double Check** | twinned = passed | 60 | Two ticks: the real device passes, and the twin passes the same gate (dashed). The tool's verdict, twinned, as a mark. |
| 20 | **Split Bot** | robot, half twin | 53 | A robot, half real and half wireframe. The most literal 'robot digital twin', but lucide's bot already means 'AI agent' in most toolbars. |

## Use it in Clank

`sim2real.iconnode.json` is the default mark in lucide's own iconNode shape:

```ts
const Sim2Real = createLucideIcon('sim2real', iconNode)
```

`createLucideIcon` is lucide-react's own factory (`lucide-react` 1.42.0 in Clank); the result is a `LucideIcon` that
`registerRibbonItem` accepts.

## Rebuild and check

```bash
uv run --no-project --with svgpathtools python /home/bam/sim2real/brand/icons/build.py
```

```bash
uv run --no-project --with playwright --with svgpathtools --with pillow python /home/bam/sim2real/brand/icons/render_check.py --out /tmp/s2r-renders
```

`render_check.py` rasterises every mark at 16 / 24 / 48 px at device pixel ratio 1 and writes a 3× nearest-neighbour
zoom, so the 16 px case can be looked at pixel by pixel. `lucide_reference.json` holds the stock lucide icons (ISC)
the report draws beside the proposals.
