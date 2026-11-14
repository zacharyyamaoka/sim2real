"""Build the homing-routine report (bam_fb_v2 full arm, sim only) from routine_check's episodes, the media index and the W&B summary.

    env -u VIRTUAL_ENV /home/bam/sim2real/.venv/bin/python /home/bam/sim2real/tools/homing_routine_report.py --out /home/bam/bam_ws/reports/homing-routine-2026-11-13.html

Reads the results JSON (or, while the grid still runs, its episode cache), scores it with the frozen ruler (routine_ruler), and writes one
page: the verdict, the hero video, what good means, the scoreboard, the coverage maps, the perturbed twins, the findings, the sequence
handed to the rack and the decision surface. Videos stay files beside the page (reports/media/homing-routine-2026-11-13/), referenced
relatively; the coverage maps are inline SVG.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import pickle
from pathlib import Path

from sim2real.sim.homing import routine_ruler as ruler
from sim2real.sim.homing.routine_figures import coverage_svg

DATA = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data"
RESULTS = DATA / "homing_routine_2026-11-13.json"
CACHE = Path.home() / ".cache" / "sim2real" / "homing_routine" / "episodes_2026-11-13.jsonl"
CALIBRATIONS = Path.home() / ".cache" / "sim2real" / "homing_routine" / "calibrations_tight_2026-11-13.json"
PLANS = Path.home() / ".cache" / "sim2real" / "homing_routine_plans.pkl"
MEDIA_REL = "media/homing-routine-2026-11-13"
ROLES = ("J2", "C1", "W1", "W2", "W3", "CLAW")

CSS = """
:root{--bg:#fcfcfb;--fg:#0b0b0b;--muted:#5f5e5a;--line:#e1e0d9;--card:#ffffff;--good:#0ca30c;--goodtext:#006300;--warn:#fab219;
--serious:#ec835a;--bad:#d03b3b;--chip:#f1f0ec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#1a1a19;--fg:#ecebe6;--muted:#a3a29b;--line:#2c2c2a;--card:#232321;
--goodtext:#0ca30c;--chip:#2c2c2a}}
:root[data-theme="dark"]{--bg:#1a1a19;--fg:#ecebe6;--muted:#a3a29b;--line:#2c2c2a;--card:#232321;--goodtext:#0ca30c;--chip:#2c2c2a}
body{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0 auto;max-width:1180px;
padding:24px 16px}
h1{font-size:24px;margin:0 0 6px}h2{font-size:19px;margin:34px 0 8px;border-top:1px solid var(--line);padding-top:18px}
h3{font-size:16px;margin:20px 0 6px}
.verdict{font-size:17px;font-weight:600;margin:10px 0 4px}.sub{color:var(--muted);font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:5px 7px;text-align:right;vertical-align:top}
th:first-child,td:first-child{text-align:left}th{font-weight:600;color:var(--muted);background:var(--card);position:sticky;top:0}
.scroll{overflow-x:auto}.chip{display:inline-block;border-radius:9px;padding:0 7px;font-size:12px;background:var(--chip);margin:1px}
.pass{color:var(--goodtext);font-weight:600}.fail{color:var(--bad);font-weight:600}
.map{overflow-x:auto;margin:6px 0 18px}.map svg{max-width:100%;height:auto}
figure{margin:12px 0}figcaption{color:var(--muted);font-size:13px}video,img.still{max-width:100%;border-radius:6px;border:1px solid var(--line)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:14px}
.box{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
code{background:var(--chip);padding:0 4px;border-radius:4px;font-size:13px}
ul{padding-left:20px}li{margin:3px 0}
"""


def esc(text) -> str:
    return html.escape(str(text))


def fmt(value, digits: int = 3, unit: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}{unit}"
    return f"{value}{unit}"


def load(results_path: Path) -> tuple[list[dict], dict]:
    """(episodes, calibrations): the results JSON when it exists, else the run's cache (the grid still running)."""
    if results_path.is_file():
        results = json.loads(results_path.read_text())
        return results["episodes"], results.get("calibrations") or {}
    episodes = []
    if CACHE.is_file():
        for line in CACHE.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "error" not in row:
                episodes.append(row)
    calibrations = json.loads(CALIBRATIONS.read_text()) if CALIBRATIONS.is_file() else {}
    from sim2real.sim.homing.routine_check import tight_witness  # noqa: PLC0415

    episodes = [e for e in episodes if not e.get("derived_from")] + tight_witness(episodes, calibrations)
    return episodes, calibrations


def rank_key(card: dict):
    """The ruler's order: silent wrong, then coverage, then zero error, then time (time never buys accuracy)."""
    return (card["silent_wrong"], -(card["coverage_pct"] or 0.0), card["zero_error_p95_deg"] if card["zero_error_p95_deg"] is not None else 9e9,
            card["time_to_home_median_s"] if card["time_to_home_median_s"] is not None else 9e9)


SHORT = {"silent_wrong": "silent wrong", "coverage_pct": "coverage", "zero_error_p95_deg": "zero p95", "repeatability_deg": "repeat",
         "time_to_home_median_s": "median time", "time_to_home_p95_s": "p95 time", "belt_after_liftoff": "belt", "tripped": "trips",
         "peak_speed_ratio": "speed"}


def verdict_chips(card: dict) -> str:
    """How many targets pass, and the names of those that fail."""
    measured = {k: v for k, v in card["verdict"].items() if k != "pass" and v is not None}
    passed = sum(1 for v in measured.values() if v)
    failing = ", ".join(SHORT.get(k, k) for k, v in measured.items() if not v)
    return (f"<span class='{'pass' if passed == len(measured) else ''}'>{passed}/{len(measured)}</span>"
            + (f"<br><span class='sub'>✗ {esc(failing)}</span>" if failing else ""))


def scoreboard(cards: dict, environment: str = ruler.NOMINAL) -> str:
    rows = sorted(((key.split(" | ")[0], card) for key, card in cards.items() if key.endswith(f" | {environment}")), key=lambda rc: rank_key(rc[1]))
    head = ("<tr><th>routine (ranked)</th><th>cells run / feasible</th><th>coverage %</th><th>silent wrong</th><th>refused</th>"
            "<th>tripped / timeout</th><th>inaccurate</th><th>zero p95 °</th><th>W1 / W2 / W3 p95 °</th><th>repeat °</th>"
            "<th>backlash ID % · err p95 ′</th><th>time median / p95 s</th><th>belt after lift-off</th><th>peak speed / ceiling</th>"
            "<th>targets</th></tr>")
    body = []
    for routine, card in rows:
        o = card["outcomes"]
        by = card["zero_error_p95_deg_by_joint"]
        body.append(
            f"<tr><td><b>{esc(routine)}</b></td><td>{card['cells']} / {card['feasible']}</td>"
            f"<td class='{'pass' if card['verdict'].get('coverage_pct') else 'fail'}'>{fmt(card['coverage_pct'], 1)}</td>"
            f"<td class='{'pass' if card['silent_wrong'] == 0 else 'fail'}'>{card['silent_wrong']}</td><td>{card['refused']}</td>"
            f"<td>{o['tripped']} / {o['timeout']}</td><td>{o['inaccurate']}</td><td>{fmt(card['zero_error_p95_deg'], 3)}</td>"
            f"<td>{fmt(by.get('W1'), 3)} / {fmt(by.get('W2'), 3)} / {fmt(by.get('W3'), 3)}</td><td>{fmt(card['repeatability_deg'], 4)}</td>"
            f"<td>{fmt(card['backlash_identified_pct'], 0)} · {fmt(card['backlash_error_p95_arcmin'], 2)}</td>"
            f"<td>{fmt(card['time_to_home_median_s'], 1)} / {fmt(card['time_to_home_p95_s'], 1)}</td><td>{card['belt_after_liftoff']}</td>"
            f"<td>{fmt(card['peak_speed_ratio'], 2)}</td><td>{verdict_chips(card)}</td></tr>")
    return f"<div class='scroll'><table>{head}{''.join(body)}</table></div>"


def perturbed(cards: dict) -> str:
    environments = [e for e in ruler.ENVIRONMENTS if e != ruler.NOMINAL]
    routines = sorted({k.split(" | ")[0] for k in cards if k.split(" | ")[1] != ruler.NOMINAL})
    head = "<tr><th>routine</th>" + "".join(f"<th>{esc(e)}</th>" for e in environments) + "</tr>"
    body = []
    for routine in routines:
        cells = []
        for environment in environments:
            card = cards.get(f"{routine} | {environment}")
            if card is None:
                cells.append("<td>—</td>")
                continue
            sw = card["silent_wrong"]
            cells.append(f"<td><span class='{'pass' if card['verdict']['pass'] else ''}'>{fmt(card['coverage_pct'], 0)} %</span><br>"
                         f"<span class='{'fail' if sw else 'sub'}'>sw {sw}</span> · <span class='sub'>p95 {fmt(card['zero_error_p95_deg'], 3)}°"
                         f"</span><br><span class='sub'>{card['feasible']} cells · t {fmt(card['time_to_home_median_s'], 0)} s</span></td>")
        body.append(f"<tr><td><b>{esc(routine)}</b></td>{''.join(cells)}</tr>")
    why = "".join(f"<li><b>{esc(k)}</b>: {esc(v['why'])}</li>" for k, v in ruler.ENVIRONMENTS.items())
    return (f"<div class='scroll'><table>{head}{''.join(body)}</table></div><p class='sub'>Each cell: coverage, silent wrong, zero p95, "
            f"feasible cells, median time.</p><ul class='sub'>{why}</ul>")


def targets_table() -> str:
    rows = [("silent wrong", "a home claimed with a zero > 1° off, or on a stall > 1° off its CAD stop", "0, every environment"),
            ("coverage", "homed (every zero ≤ 0.1°) and clean (nothing on the belt after lift-off) / feasible starts", "≥ 95 % nominal, ≥ 90 % each perturbed twin"),
            ("zero error p95", "worst scored joint |zero − truth|, over finished episodes", "≤ 0.1°"),
            ("repeatability", "per joint, max − min of the signed zero error over the starts", "≤ 0.02°"),
            ("backlash", "every wrist gap identified by the routine itself; |gap − truth|", "≤ max(1′, 25 % of the truth)"),
            ("time to home", "tick clock, first command → done, homed episodes", "median ≤ 60 s, p95 ≤ 90 s"),
            ("belt after lift-off", "episodes touching the belt after 2 s clear of it", "0"),
            ("peak speed", "worst powered joint speed / its ceiling (86 °/s)", "≤ 0.8"),
            ("tripped", "runaway stop or guard", "0")]
    body = "".join(f"<tr><td><b>{esc(a)}</b></td><td style='text-align:left'>{esc(b)}</td><td>{esc(c)}</td></tr>" for a, b, c in rows)
    return f"<table><tr><th>metric</th><th style='text-align:left'>what</th><th>good</th></tr>{body}</table>"


def video(media: dict, name: str, caption: str, *, poster: bool = True) -> str:
    item = media.get(name)
    if not item or not item.get("mp4"):
        return f"<p class='sub'>(video “{esc(name)}” not rendered)</p>"
    mp4 = f"{MEDIA_REL}/{Path(item['mp4']).name}"
    gif = f"{MEDIA_REL}/{Path(item['gif']).name}" if item.get("gif") else ""
    still = f"{MEDIA_REL}/{Path(item['still']).name}" if item.get("still") else ""
    rrd = item.get("rrd")
    replay = (f" · Rerun: <code>/home/bam/data_recorder/.venv/bin/data-recorder view {esc(rrd)}</code>" if rrd else "")
    return (f"<figure><video src='{mp4}' {f'poster={chr(39)}{still}{chr(39)}' if poster and still else ''} autoplay muted loop playsinline controls "
            f"preload='metadata' width='960'></video><figcaption>{caption} · {item.get('speedup', 4):g}× real time · left the whole arm, "
            f"right the wrist close-up · <a href='{gif}'>GIF</a>{replay}</figcaption></figure>")


def sequence_table(plans: dict, row: str) -> str:
    plan = plans.get(row)
    if not plan:
        return "<p class='sub'>(the plan is not cached)</p>"
    out = []
    for phase, sequence in enumerate(plan["sequences"]):
        if sequence is None:
            continue
        steps = []
        for step in sequence.steps:
            if "(waypoint" in step.name:
                continue
            moving = []
            for c in step.commands:
                if c.mode in ("hold", "limp"):
                    continue
                if c.mode == "move_by" and abs(float(c.distance or 0.0)) < 1e-5:
                    continue
                speed = f" at {math.degrees(c.speed):.0f}°/s" if c.speed else ""
                what = (f"by {math.degrees(c.distance):+.0f}°" if c.mode == "move_by" else f"to {math.degrees(c.position):+.1f}°")
                moving.append(f"{c.joint}: {what}{speed}, cap {c.max_effort:g} N·m")
            done = ", ".join(type(d).__name__ for d in step.done_when)
            define = ", ".join(f"{j} := {math.degrees(v):+.2f}°" for j, v in step.define_position.items())
            steps.append(f"<tr><td style='text-align:left'>{esc(step.name)}</td><td style='text-align:left'>{esc('; '.join(moving) or '—')}</td>"
                         f"<td>{esc(done)}</td><td>{esc(define)}</td></tr>")
        out.append(f"<h3>Phase {phase}: {esc(sequence.name)}</h3><div class='scroll'><table><tr><th>step</th><th style='text-align:left'>"
                   f"what moves (URDF frame)</th><th>done when</th><th>defines</th></tr>{''.join(steps)}</table></div>")
    return "".join(out)


TIGHT = " · witness 0.5° (stall-calibrated)"


def overall(cards: dict) -> list[tuple[str, dict]]:
    """Every routine ranked across the twins (the ruler's order, per routine): silent wrong summed over every twin, then nominal coverage,
    then the worst perturbed twin's coverage, then nominal zero p95, then nominal median time."""
    routines = sorted({k.split(" | ")[0] for k in cards})
    out = []
    for routine in routines:
        mine = {k.split(" | ")[1]: c for k, c in cards.items() if k.split(" | ")[0] == routine}
        nominal = mine.get(ruler.NOMINAL)
        if nominal is None:
            continue
        perturbed = [c["coverage_pct"] for e, c in mine.items() if e != ruler.NOMINAL and c["coverage_pct"] is not None]
        summary = {"silent_wrong_all": sum(c["silent_wrong"] for c in mine.values()), "coverage": nominal["coverage_pct"],
                   "worst_perturbed": min(perturbed) if perturbed else None, "environments": len(mine),
                   "zero_p95": nominal["zero_error_p95_deg"], "time": nominal["time_to_home_median_s"], "card": nominal}
        out.append((routine, summary))
    out.sort(key=lambda rs: (rs[1]["silent_wrong_all"], -(rs[1]["coverage"] or 0.0),
                             -(rs[1]["worst_perturbed"] if rs[1]["worst_perturbed"] is not None else -1.0),
                             rs[1]["zero_p95"] if rs[1]["zero_p95"] is not None else 9e9, rs[1]["time"] if rs[1]["time"] is not None else 9e9))
    return out


def overall_table(ranked: list[tuple[str, dict]]) -> str:
    head = ("<tr><th>rank · routine</th><th>silent wrong, every twin</th><th>coverage nominal %</th><th>worst perturbed twin %</th>"
            "<th>twins run</th><th>zero p95 °</th><th>median s</th></tr>")
    body = "".join(f"<tr><td>{k + 1}. <b>{esc(routine)}</b></td><td class='{'pass' if r['silent_wrong_all'] == 0 else 'fail'}'>"
                   f"{r['silent_wrong_all']}</td><td>{fmt(r['coverage'], 1)}</td><td>{fmt(r['worst_perturbed'], 1)}</td>"
                   f"<td>{r['environments']}</td><td>{fmt(r['zero_p95'], 3)}</td><td>{fmt(r['time'], 1)}</td></tr>"
                   for k, (routine, r) in enumerate(ranked))
    return f"<div class='scroll'><table>{head}{body}</table></div>"


def build(out: Path, *, results_path: Path, media_index: Path, wandb_summary: Path | None, recommended: str, notes: dict) -> str:
    episodes, calibrations = load(results_path)
    cards = ruler.score(episodes)
    ranked = overall(cards)
    media = json.loads(media_index.read_text()) if media_index.is_file() else {}
    plans = pickle.loads(PLANS.read_bytes()) if PLANS.is_file() else {}
    wb = json.loads(wandb_summary.read_text()) if wandb_summary and wandb_summary.is_file() else {}
    nominal_rows = sorted({k.split(" | ")[0] for k in cards if k.endswith(" | nominal")},
                          key=lambda r: rank_key(cards[f"{r} | nominal"]))
    maps = "".join(f"<div class='map'>{coverage_svg(episodes, row, ruler.NOMINAL)}</div>" for row in nominal_rows)
    done = sum(1 for e in episodes if e.get("environment") == ruler.NOMINAL)
    planned = len(ruler.grid_cells()) * 5 + len(ruler.subset_cells()) * 3
    calib = "".join(f"<li><b>{esc(env)}</b>: {esc(c.get('outcome'))}; gap error vs hidden (′): {esc(c.get('gap_error_arcmin'))}</li>"
                    for env, c in calibrations.items())
    wandb_line = (f"<p>W&amp;B: <a href='{esc(wb.get('project_url', ''))}'>{esc(wb.get('project', 'Homing · bam_fb_v2'))}</a>"
                  + (f" · report <a href='{esc(wb['report'])}'>{esc(wb['report'])}</a>" if wb.get("report") else "") + "</p>") if wb else ""
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Homing routine bam_fb_v2</title><style>{CSS}</style></head><body>",
             "<h1>A better homing routine for the full arm (bam_fb_v2) — sim only</h1>",
             f"<p class='verdict'>{notes.get('verdict', '')}</p><p class='sub'>{notes.get('qualification', '')}</p>",
             f"<p class='sub'>Episodes scored: {done} nominal of ~{planned} planned + {len(episodes) - done} perturbed. "
             f"Ruler frozen before any routine ran (<code>sim2real.sim.homing.routine_ruler</code>, {esc(notes.get('ruler_commit', ''))}). "
             f"Twin: MuJoCo, bam_fb_v2 @ cad-exporter 09374d7, the rack's belt as a contact.</p>", wandb_line,
             video(media, notes.get("hero", ""), notes.get("hero_caption", "")),
             "<h2>What good looks like (frozen first)</h2>", targets_table(),
             "<p class='sub'>Rank: silent wrong, then coverage, then zero error, then time — time never buys accuracy. A start is the pose "
             "the arm was in when the power went (4 five-bar poses × W1 × W2, W3 / claw / J1 balanced); the twin lets the whole arm fall "
             "onto the belt, its stops or itself before power-on, so hanging on the belt is where most starts begin, as on the rack.</p>",
             "<h2>Overall, across every twin</h2><p class='sub'>Ranked by the ruler's order per routine: silent wrong summed over "
             "every twin, then nominal coverage, then the worst perturbed twin's coverage, then zero error, then time. Rows ending “witness "
             "0.5°” are the same runs re-judged by the tight witness (it never moves the arm).</p>", overall_table(ranked),
             "<h2>Scoreboard, nominal twin</h2>", scoreboard(cards),
             "<h2>Coverage maps (nominal)</h2><p class='sub'>Rows W1, columns W2 (°), one panel per five-bar pose; hover a cell for its start "
             "and outcome.</p>", maps,
             "<h2>Perturbed twins (every 6th cell)</h2>", perturbed(cards),
             f"<h3>The stored tables (identify_backlash once per twin)</h3><ul class='sub'>{calib}</ul>",
             "<h2>What we found</h2>", notes.get("findings", ""),
             "<h2>Videos</h2>", "".join(video(media, name, caption) for name, caption in notes.get("videos", [])),
             f"<h2>The sequence for the rack: {esc(recommended)}</h2>", notes.get("handoff", ""), sequence_table(plans, recommended),
             "<h2>Decisions and what is left</h2>", notes.get("decisions", ""),
             "<h2>Provenance</h2>", notes.get("provenance", ""), "</body></html>"]
    page = "".join(parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return page


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--media", type=Path, default=Path("/home/bam/bam_ws/reports") / MEDIA_REL / "media.json")
    parser.add_argument("--wandb", type=Path)
    parser.add_argument("--notes", type=Path, help="the page's words (JSON): verdict, findings, decisions, ... (tools/homing_routine_notes.json)")
    parser.add_argument("--recommended", default="park_first+witness @ READY")
    args = parser.parse_args(argv)
    notes = json.loads(args.notes.read_text()) if args.notes and args.notes.is_file() else {}
    page = build(args.out, results_path=args.results, media_index=args.media, wandb_summary=args.wandb, recommended=args.recommended, notes=notes)
    print(args.out, len(page.encode()), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
