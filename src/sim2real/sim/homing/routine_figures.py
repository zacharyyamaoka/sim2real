"""The homing routine's coverage maps (routine_ruler's grid, routine_check's episodes) as SVG for the report and PNG for W&B - stdlib + PIL.

One map per (routine, environment): four panels, one per five-bar level (READY, PICK, LIFT, UP), each the 6 x 6 wrist grid (W1 down, W2
across, degrees). A cell is the start's outcome (routine_ruler.OUTCOMES) as a status colour AND a glyph, so colour never carries it alone
(the house dataviz rule; status steps: good #0ca30c, warning #fab219, serious #ec835a, critical #d03b3b). A refusal is a safe stop, not
an alarm: neutral grey. A start the twin cannot hold (infeasible) is an empty, hairline cell; a start not run yet is dashed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from html import escape
from pathlib import Path

from . import routine_ruler as ruler

STYLE = {  # display class -> (fill, ink, glyph, label)
    "homed": ("#0ca30c", "#ffffff", "✓", "homed (zeros within 0.1°)"),
    "homed_belt": ("#fab219", "#0b0b0b", "b", "homed, but pressed the belt after lift-off"),
    "inaccurate": ("#fab219", "#0b0b0b", "~", "right stops, a zero 0.1-1° off"),
    "refused": ("#8d8c86", "#ffffff", "R", "refused by its own check (safe stop)"),
    "timeout": ("#ec835a", "#0b0b0b", "T", "a step never finished"),
    "tripped": ("#ec835a", "#0b0b0b", "X", "tripped (runaway / guard)"),
    "silent_wrong": ("#d03b3b", "#ffffff", "!", "SILENT WRONG: claimed a home, a zero > 1° off"),
    "infeasible": ("none", "#8d8c86", "·", "start the arm cannot be in (self-contact / through the belt)"),
    "missing": ("none", "#c3c2b7", "", "not run"),
}
ORDER = ("homed", "homed_belt", "inaccurate", "refused", "timeout", "tripped", "silent_wrong", "infeasible", "missing")
LEVELS = tuple(ruler.FIVEBAR_LEVELS)
N = len(ruler.WRIST_LEVELS_DEG)
CELL, GAP, PAD = 24, 2, 34
INK, MUTED, SURFACE, HAIR = "#0b0b0b", "#5f5e5a", "#fcfcfb", "#e1e0d9"


def display_class(report: dict | None) -> str:
    if report is None:
        return "missing"
    cls = report.get("outcome_class") or ruler.outcome_class(report)
    if cls == "homed" and not ruler.clean(report):
        return "homed_belt"
    return cls


def grid_of(episodes: Iterable[dict], row: str, environment: str) -> dict:
    """(level, i, j) -> the episode report of ``row`` in ``environment`` (cells not run are absent)."""
    out = {}
    for r in episodes:
        if r.get("row") != row or r.get("environment") != environment or not r.get("cell"):
            continue
        cell = r["cell"]
        out[(cell["fivebar"], int(cell["i"]), int(cell["j"]))] = r
    return out


def counts(grid: dict) -> dict:
    out = {k: 0 for k in ORDER}
    for level in LEVELS:
        for i in range(N):
            for j in range(N):
                out[display_class(grid.get((level, i, j)))] += 1
    return out


def coverage_svg(episodes: Sequence[dict], row: str, environment: str, *, title: str | None = None) -> str:
    grid = grid_of(episodes, row, environment)
    panel = N * (CELL + GAP)
    width = PAD + len(LEVELS) * (panel + 26) + 8
    height = 40 + 18 + panel + 22 + 18 * ((len(ORDER) + 2) // 3) + 10
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
             f'aria-label="{escape(title or row)}" style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:{SURFACE}">']
    c = counts(grid)
    feasible = sum(v for k, v in c.items() if k not in ("infeasible", "missing"))
    head = title or f"{row} · {environment}"
    parts.append(f'<text x="4" y="16" font-size="13" font-weight="600" fill="{INK}">{escape(head)}</text>')
    parts.append(f'<text x="4" y="32" font-size="11" fill="{MUTED}">homed and clean {c["homed"]} of {feasible} run'
                 f'{"" if not c["missing"] else f" ({c["missing"]} cells not run)"} · silent wrong {c["silent_wrong"]} · refused {c["refused"]} '
                 f'· infeasible {c["infeasible"]}</text>')
    top = 58
    for p, level in enumerate(LEVELS):
        x0 = PAD + p * (panel + 26)
        parts.append(f'<text x="{x0}" y="{top - 6}" font-size="11" font-weight="600" fill="{INK}">{level}</text>')
        for j, w2 in enumerate(ruler.WRIST_LEVELS_DEG):
            parts.append(f'<text x="{x0 + j * (CELL + GAP) + CELL / 2}" y="{top + panel + 12}" font-size="9" fill="{MUTED}" '
                         f'text-anchor="middle">{w2:+.0f}</text>')
        for i, w1 in enumerate(ruler.WRIST_LEVELS_DEG):
            if p == 0:
                parts.append(f'<text x="{x0 - 4}" y="{top + i * (CELL + GAP) + CELL / 2 + 3}" font-size="9" fill="{MUTED}" '
                             f'text-anchor="end">{w1:+.0f}</text>')
            for j in range(N):
                report = grid.get((level, i, j))
                cls = display_class(report)
                fill, ink, glyph, label = STYLE[cls]
                x, y = x0 + j * (CELL + GAP), top + i * (CELL + GAP)
                tip = f"{level} W1 {w1:+.0f}° W2 {ruler.WRIST_LEVELS_DEG[j]:+.0f}°: {label}"
                if report is not None and report.get("start"):
                    tip = f"{report['start']}: {label}"
                    if report.get("time_s"):
                        tip += f", {report['time_s']:.0f} s"
                    if report.get("outcome") and cls not in ("homed", "infeasible"):
                        tip += f" — {str(report['outcome'])[:140]}"
                    elif report.get("refused_start"):
                        tip += f" — {str(report['refused_start'])[:140]}"
                stroke = f'stroke="{HAIR}" stroke-width="1"' + (' stroke-dasharray="3 2"' if cls == "missing" else "")
                parts.append(f'<g><title>{escape(tip)}</title><rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" fill="{fill}" '
                             f'{stroke if fill == "none" else ""}/>'
                             f'<text x="{x + CELL / 2}" y="{y + CELL / 2 + 4}" font-size="12" font-weight="700" fill="{ink}" '
                             f'text-anchor="middle">{escape(glyph)}</text></g>')
    parts.append(f'<text x="4" y="{top + panel / 2}" font-size="10" fill="{MUTED}" transform="rotate(-90 10 {top + panel / 2})" '
                 f'text-anchor="middle">W1 (°)</text>')
    parts.append(f'<text x="{PAD + panel / 2}" y="{top + panel + 24}" font-size="10" fill="{MUTED}" text-anchor="middle">W2 (°)</text>')
    ly = top + panel + 40
    for k, cls in enumerate(ORDER):
        fill, ink, glyph, label = STYLE[cls]
        lx = 4 + (k % 3) * ((width - 8) / 3)
        yy = ly + (k // 3) * 18
        parts.append(f'<rect x="{lx}" y="{yy - 10}" width="13" height="13" rx="2" fill="{fill}" '
                     f'{f"stroke={chr(34)}{HAIR}{chr(34)}" if fill == "none" else ""}/>'
                     f'<text x="{lx + 6.5}" y="{yy}" font-size="9" font-weight="700" fill="{ink}" text-anchor="middle">{escape(glyph)}</text>'
                     f'<text x="{lx + 18}" y="{yy}" font-size="10" fill="{INK}">{escape(label)} ({c[cls]})</text>')
    parts.append("</svg>")
    return "".join(parts)


def coverage_png(episodes: Sequence[dict], row: str, environment: str, path: Path, *, scale: int = 2) -> Path:
    """The same map as a PNG (W&B's media panel), drawn with PIL."""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    grid = grid_of(episodes, row, environment)
    c = counts(grid)
    s = scale
    cell, gap = CELL * s, GAP * s
    panel = N * (cell + gap)
    pad = PAD * s
    width = pad + len(LEVELS) * (panel + 26 * s) + 8 * s
    height = (40 + 18 + 22 + 18 * ((len(ORDER) + 2) // 3) + 10) * s + panel
    image = Image.new("RGB", (int(width), int(height)), SURFACE)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 10 * s)
        bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 11 * s)
        head = ImageFont.truetype("DejaVuSans-Bold.ttf", 13 * s)
    except OSError:
        font = bold = head = ImageFont.load_default()
    feasible = sum(v for k, v in c.items() if k not in ("infeasible", "missing"))
    draw.text((4 * s, 4 * s), f"{row} · {environment}", fill=INK, font=head)
    draw.text((4 * s, 22 * s), f"homed and clean {c['homed']} of {feasible} run · silent wrong {c['silent_wrong']} · refused {c['refused']}"
                               f" · infeasible {c['infeasible']}" + (f" · {c['missing']} not run" if c["missing"] else ""), fill=MUTED, font=font)
    top = 58 * s
    for p, level in enumerate(LEVELS):
        x0 = pad + p * (panel + 26 * s)
        draw.text((x0, top - 16 * s), level, fill=INK, font=bold)
        for i, w1 in enumerate(ruler.WRIST_LEVELS_DEG):
            if p == 0:
                draw.text((x0 - 30 * s, top + i * (cell + gap) + 6 * s), f"{w1:+.0f}", fill=MUTED, font=font)
            for j in range(N):
                cls = display_class(grid.get((level, i, j)))
                fill, ink, glyph, _ = STYLE[cls]
                x, y = x0 + j * (cell + gap), top + i * (cell + gap)
                if fill == "none":
                    draw.rounded_rectangle((x, y, x + cell, y + cell), radius=3 * s, outline=HAIR, width=s)
                else:
                    draw.rounded_rectangle((x, y, x + cell, y + cell), radius=3 * s, fill=fill)
                if glyph:
                    draw.text((x + cell / 2, y + cell / 2), glyph, fill=ink, font=bold, anchor="mm")
        for j, w2 in enumerate(ruler.WRIST_LEVELS_DEG):
            draw.text((x0 + j * (cell + gap) + cell / 2, top + panel + 4 * s), f"{w2:+.0f}", fill=MUTED, font=font, anchor="ma")
    draw.text((4 * s, top + panel + 18 * s), "rows W1 (°), columns W2 (°)", fill=MUTED, font=font)
    ly = top + panel + 36 * s
    for k, cls in enumerate(ORDER):
        fill, ink, glyph, label = STYLE[cls]
        lx = 4 * s + (k % 3) * ((width - 8 * s) / 3)
        yy = ly + (k // 3) * 18 * s
        if fill == "none":
            draw.rounded_rectangle((lx, yy, lx + 13 * s, yy + 13 * s), radius=2 * s, outline=HAIR, width=s)
        else:
            draw.rounded_rectangle((lx, yy, lx + 13 * s, yy + 13 * s), radius=2 * s, fill=fill)
        if glyph:
            draw.text((lx + 6.5 * s, yy + 6.5 * s), glyph, fill=ink, font=font, anchor="mm")
        draw.text((lx + 18 * s, yy), f"{label} ({c[cls]})", fill=INK, font=font)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


__all__ = ["ORDER", "STYLE", "counts", "coverage_png", "coverage_svg", "display_class", "grid_of"]
