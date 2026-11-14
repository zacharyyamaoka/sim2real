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


def perturbed(cards: dict, suffix: str = "") -> str:
    environments = [e + suffix for e in ruler.ENVIRONMENTS if e != ruler.NOMINAL or suffix]
    environments = [e for e in environments if any(k.endswith(f" | {e}") for k in cards)]
    routines = sorted({k.split(" | ")[0] for k in cards if k.split(" | ")[1] in environments})
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
    why = "".join(f"<li><b>{esc(k)}</b>: {esc(v['why'])}</li>" for k, v in ruler.ENVIRONMENTS.items()) if not suffix else ""
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


def sequence_table(plans: dict, row: str, phases: tuple = (0, 1)) -> str:
    plan = plans.get(row)
    if not plan:
        return "<p class='sub'>(the plan is not cached)</p>"
    out = []
    for phase, sequence in enumerate(plan["sequences"]):
        if sequence is None or phase not in phases:
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
        # the folded-wrist cells (amendment 3) count for safety - a silent wrong there is one - but not in a twin's coverage
        # WHY phase_cal_error apart: it is the stale-calibration case (the witness's calibration 1.5 deg off), where a tight witness is
        # MEANT to refuse everything - an operating rule (re-take the calibration), not a start the routine should cover
        perturbed = [c["coverage_pct"] for e, c in mine.items() if e not in (ruler.NOMINAL, "phase_cal_error")
                     and not e.endswith(" · folded wrist") and c["coverage_pct"] is not None]
        stale = mine.get("phase_cal_error")
        summary = {"silent_wrong_all": sum(c["silent_wrong"] for c in mine.values()), "coverage": nominal["coverage_pct"],
                   "worst_perturbed": min(perturbed) if perturbed else None,
                   "environments": sum(1 for e in mine if not e.endswith(" · folded wrist")),
                   "zero_p95": nominal["zero_error_p95_deg"], "time": nominal["time_to_home_median_s"], "card": nominal,
                   "stale": None if stale is None else stale["coverage_pct"],
                   "stale_silent": None if stale is None else stale["silent_wrong"]}
        out.append((routine, summary))
    out.sort(key=lambda rs: (rs[1]["silent_wrong_all"], -(rs[1]["coverage"] or 0.0),
                             -(rs[1]["worst_perturbed"] if rs[1]["worst_perturbed"] is not None else -1.0),
                             rs[1]["zero_p95"] if rs[1]["zero_p95"] is not None else 9e9, rs[1]["time"] if rs[1]["time"] is not None else 9e9))
    return out


def overall_table(ranked: list[tuple[str, dict]]) -> str:
    head = ("<tr><th>rank · routine</th><th>silent wrong, every twin</th><th>coverage nominal %</th><th>worst physical twin %</th>"
            "<th>stale calibration % (silent wrong)</th><th>twins run</th><th>zero p95 °</th><th>median s</th></tr>")
    body = "".join(f"<tr><td>{k + 1}. <b>{esc(routine)}</b></td><td class='{'pass' if r['silent_wrong_all'] == 0 else 'fail'}'>"
                   f"{r['silent_wrong_all']}</td><td>{fmt(r['coverage'], 1)}</td><td>{fmt(r['worst_perturbed'], 1)}</td>"
                   f"<td>{fmt(r['stale'], 0)} ({fmt(r['stale_silent'], 0)})</td>"
                   f"<td>{r['environments']}</td><td>{fmt(r['zero_p95'], 3)}</td><td>{fmt(r['time'], 1)}</td></tr>"
                   for k, (routine, r) in enumerate(ranked))
    return f"<div class='scroll'><table>{head}{body}</table></div>"


def _c(cards: dict, routine: str, environment: str = ruler.NOMINAL) -> dict:
    return cards.get(f"{routine} | {environment}") or {}


def wrist_p95(card: dict) -> float | None:
    values = [v for k, v in (card.get("zero_error_p95_deg_by_joint") or {}).items() if k in ("W1", "W2", "W3") and v is not None]
    return max(values) if values else None


def fivebar_p95(card: dict) -> float | None:
    values = [v for k, v in (card.get("zero_error_p95_deg_by_joint") or {}).items() if k in ("J2", "C1") and v is not None]
    return max(values) if values else None


def auto_notes(cards: dict, ranked: list, episodes: list, calibrations: dict, media: dict, wb: dict) -> dict:
    """The page's words from the numbers (every number below is read from the cards; the prose is the analysis of record)."""
    full = [(r, s) for r, s in ranked if s["environments"] >= 5]
    recommended = full[0][0] if full else (ranked[0][0] if ranked else "")
    rec = _c(cards, recommended)
    base = recommended.replace(TIGHT, "")
    plain = _c(cards, base)
    v1, park = _c(cards, "zach_v1 @ READY"), _c(cards, "park_first+witness @ READY")
    v1t, parkt = _c(cards, "zach_v1 @ READY" + TIGHT), _c(cards, "park_first+witness @ READY" + TIGHT)
    pep, multi, press = _c(cards, "PEP 0047 (wrist at the five-bar's home)"), _c(cards, "multi x2 (3D-printer) @ READY"), _c(
        cards, "press_reverse (backlash every home) @ READY")
    fast, park_b2, table_b2 = _c(cards, "fast single @ READY"), _c(cards, "park_first+witness @ READY", "B2"), _c(
        cards, "park_first+witness+table @ READY", "B2")
    nominal = [e for e in episodes if e.get("environment") == ruler.NOMINAL and e.get("row") == "park_first+witness @ READY"
               and "refused_start" not in e]
    trips = [e for e in nominal if e.get("outcome_class") in ("tripped", "timeout")]
    c1_on_base = [e for e in nominal if e.get("outcome_class") == "silent_wrong" and (e.get("zero_error_deg") or {}).get("C1")
                  and abs(e["zero_error_deg"]["C1"]) > 1.0]
    locate = [v for e in episodes if e.get("row") == "multi x2 (3D-printer) @ READY" for v in
              ((e.get("notes") or {}).get("locate_minus_retouch_deg") or {}).values()]
    worst_locate = max((abs(v) for v in locate), default=None)
    n = len(nominal)

    def pct(k, total):
        return f"{100.0 * k / total:.0f} %" if total else "—"

    order = ("Zach’s V1 order, falling back to PEP 0047’s parking path when W1’s first stall is refused" if "on a W1 refusal" in base
             else "Zach’s V1 order" if base.startswith("zach_v1") else "PEP 0047’s park_first order")
    verdict = (f"Home the wrist at READY in {order}, with a "
               f"tight rotor-phase witness (0.5° on a trusted home’s own stall, the five-bar’s drives included) and the stored backlash table: "
               f"0 silent wrong in every twin, {fmt(rec.get('coverage_pct'), 0)} % of the nominal start grid, zeros p95 "
               f"{fmt(rec.get('zero_error_p95_deg'), 3)}°, {fmt(rec.get('time_to_home_median_s'), 0)} s median.")
    qualification = (f"Coverage is capped by the five-bar’s own home from a rest on the belt, not by the wrist: {len(trips)} of {n} nominal "
                     f"starts ({pct(len(trips), n)}) trip J2’s or C1’s 86°/s runaway stop or time out before the wrist moves, the same "
                     "for every routine. Time misses the 60 s target everywhere (the five-bar alone takes ~39 s). Sim only; the twin’s "
                     "wrist gaps, claw mass and belt friction are assumptions.")
    findings = f"""
<ol>
<li><b>The belt moves the wrist's home to READY.</b> PEP 0047 homes the wrist at the five-bar's home, the gravity bowl, where the claw's
tips sit ~101 mm into the belt (bam_rack_twin full_arm; with the belt as a contact the twin refuses that pose). Run as landed it homed
{fmt(pep.get('coverage_pct'), 0)} % of its starts ({pep.get('outcomes', {}).get('tripped', 0)} trips walking down into the belt,
{pep.get('belt_after_liftoff', 0)} pressing it after lift-off). At READY (the claw 215 mm over the belt, over the bin's drop) every wrist
sweep clears the belt and the bin, and the routine ends where the full arm waits anyway, holding TD4.</li>
<li><b>Every start begins on the belt, and the five-bar's lift-off is the weak step.</b> A limp full arm falls onto the belt; leaving it, the
claw drags for a few seconds while J2's first seek lifts the arm (reported as <code>belt_drag_s</code>, accepted). On {len(trips)} of {n}
nominal starts that lift-off - J2's first seek with C1 limp, C1's seek with J2 pushing, or the walk to READY - lurches past the 86°/s
runaway stop. A slower first seek (0.025 rev/s) and C1 seeking beside J2 (c1_seek) fixed 1 of 6 of them in a probe. This is the five-bar
lane's next problem (PEP 0047's evening section), and it caps every routine here.</li>
<li><b>The 2° witness lets near-stop obstacles through; 0.5° on a trusted home's own stall does not.</b> park_first parks W1 anywhere in
(−30°, +35°]; with W3 near −120° the gripper plate meets the forearm 1.2-2.0° before W2's stop, inside PEP 0047's 2° tolerance:
{park.get('silent_wrong', 0)} silent wrongs on the nominal grid. Zach's V1 assigned W1's forearm stall as its stop ({v1.get('silent_wrong', 0)}
silent wrongs, 64-68° off), and once the five-bar's C1 stalled 45° short on the claw jammed against the base ({len(c1_on_base)} start),
wrong for every routine because the five-bar had no witness. Calibrated on a trusted home's own stall - the rack's
<code>rotor_phase_from_homed</code> is one by construction; its W1, W2 and claw stalls repeat to 0.006-0.13° over three homes - a 0.5°
witness on all six homed joints refuses every one of them and no true stop: V1 {v1.get('silent_wrong', 0)} → {v1t.get('silent_wrong', 0)},
park_first {park.get('silent_wrong', 0)} → {parkt.get('silent_wrong', 0)}. Its price: a calibration gone stale (an encoder recalibrated,
the gear train rebuilt) refuses everything - safe, and the <i>phase_cal_error</i> twin shows it. Re-take the calibration after any such
job.</li>
<li><b>V1's order beats park_first once the witness is tight.</b> V1 covers {fmt(v1t.get('coverage_pct'), 1)} % against park_first's
{fmt(parkt.get('coverage_pct'), 1)} % and is {fmt((park.get('time_to_home_median_s') or 0) - (v1.get('time_to_home_median_s') or 0), 0)} s
faster: its own failure (W1 sweeping into the forearm when the wrist starts folded) is refused, not silent, under the witness, while
park_first's parking leaves W1 off zero for W2's seek and opens the plate-on-forearm stall. Both touch the forearm at ≤ 1 N·m on some starts
(Zach, 10:15: accepted).</li>
<li><b>The 3D-printer double touch buys no accuracy here.</b> Its fast locate and slow re-touch read the same stall within
{fmt(worst_locate, 4)}°: a torque-capped stall is read standing still at a fixed torque, with no trigger latency for a slow approach to
remove. Its {fmt(multi.get('time_to_home_median_s'), 0)} s median comes from its 60°/s moves - the fast single control without the re-touch
is {fmt(fast.get('time_to_home_median_s'), 0)} s - and at 60°/s the wrist's held moves overshoot to 1.8× the 86°/s ceiling. The
forward-and-back that pays is touching BOTH stops: press_reverse identifies every wrist gap every home (wrist zeros p95
{fmt(wrist_p95(_c(cards, 'press_reverse (backlash every home) @ READY', 'B2')), 3)}° on the geared B2 twin) and its span check refuses the
near-stop stalls - for {fmt((press.get('time_to_home_median_s') or 0) - (park.get('time_to_home_median_s') or 0), 0)} s more.</li>
<li><b>Backlash needs the table (or press_reverse).</b> With hidden gaps a single touch reads each wrist stop 0.46-0.50° off (B2: park_first
{fmt(park_b2.get('coverage_pct'), 0)} % coverage, wrist p95 {fmt(wrist_p95(park_b2), 3)}°); the stored identify_backlash table brings the
wrist to {fmt(wrist_p95(table_b2), 3)}° ({fmt(table_b2.get('coverage_pct'), 0)} %; the five-bar's own zeros sit at
{fmt(fivebar_p95(table_b2), 3)}° on that twin - its gaps are not in the wrist table). The table is identified once with press_reverse and
holds until a wrist module is rebuilt; it is exact to apply - derived from a plain run it equals the run "+table" zeros to 1e-6°.</li>
<li><b>press_reverse is not yet a dependable cold fallback.</b> Its walk across the whole span (W1 from one stop to 3° short of the
other at the hold cap) timed out on {_c(cards, 'press_reverse (backlash every home) @ READY', 'friction').get('outcomes', {}).get('timeout', 0)}
of {_c(cards, 'press_reverse (backlash every home) @ READY', 'friction').get('feasible', 0)} starts with the wrist's breakaway friction and
{_c(cards, 'press_reverse (backlash every home) @ READY', 'claw_heavy').get('outcomes', {}).get('timeout', 0)} of
{_c(cards, 'press_reverse (backlash every home) @ READY', 'claw_heavy').get('feasible', 0)} with the 0.50 kg claw; identify_backlash (PEP 0047)
walks the same way, so take the table's calibration on a light, warm wrist and fix that step before leaning on it.</li>
<li><b>Speed and time.</b> Every routine misses the 0.8 × speed margin: the wrist's kp 75 / kd 0.75 PD is underdamped on the twin, so a held
move overshoots its ramp ~2× (75°/s at the recipe's 36°/s), and the five-bar's trips peak far higher. Time: the five-bar phase is ~39 s, 23 s
of it the gravity-fed walk to READY; the wrist phase is 38-90 s by routine.</li>
</ol>"""
    handoff = (f"<p>Phase 0 is the rack's own staged five-bar home (stalls, C1 eased off, the corridor to READY) - this routine adds a "
               f"rotor-phase witness on J2 and C1 calibrated on the trusted manual stall zero. Phase 1, below, runs at READY with the "
               f"five-bar held: the claw closes, then each wrist joint touches its stop once at 1 N·m and 36°/s, is witnessed "
               f"<b>as its defining step ends</b> (0.5° on the 11:24 home's stall: W3's + stop at +2.78° mod 36°; no expected-travel "
               f"check - a seek may end short because the joint started near its stop), goes to 0, and the routine ends at TD4. "
               + ("<b>The branch:</b> W1's first seek is the same move in V1 and park_first; if the witness refuses its stall (the "
                  "gripper on the forearm, a folded wrist), do not assign it - carry on with park_first's path (W1 back 135°, W2, W1 again, "
                  "W3). " if "on a W1 refusal" in base else "")
               + f"The stored table corrects each zero for its gap and wind-up. <code>python -m sim2real.sim.homing.fullarm_routine "
               f"--out plan.json</code> writes both paths and the branch rule as JSON.</p>")
    decisions = """<ul>
<li><b>Decided for you</b> (each a default in code; undo in one line):
 <ul><li>the wrist homes at READY, not the five-bar's home (undo: <code>wrist_pose="bowl"</code>);</li>
 <li>V1's order over PEP 0047's park_first for the rack (undo: <code>order="park_first"</code>);</li>
 <li>the witness at 0.5° on a trusted home's stall, the five-bar's drives included (undo: <code>witness_tol_deg=2.0</code>);</li>
 <li>the witness calibrated on the 11:24 home, per the Sim to Real Agent's ArUco check and Zach's video ruling;</li>
 <li>the ruler's four amendments, none moving a metric or target: lift-off is 2 s clear of the belt; rows added after READY's
 map (V1 in the perturbed twins, the tight witness and the table as derived rows); the perturbation subset made a W1 / W2 diagonal (it had
 been W2 −150 only, a sampling bug - the folded-wrist runs are shown apart); step timeouts labelled timeouts, not trips.</li></ul></li>
<li><b>Left, not blocked:</b> the five-bar's lift-off from a belt rest (the coverage ceiling; its lane); a retry after a refusal (turn W3 and
 touch W2 again) to win back the refused starts; accel-limited or better-damped wrist moves before any speed-up; the real rung through the
 Sim to Real Agent.</li>
<li><b>Needs you:</b> nothing irreversible.</li>
<li><b>Not done:</b> no hardware moved (sim only); the five-bar's homing itself is unchanged beyond the witness.</li>
</ul>"""
    videos = [(k, v) for k, v in (("zach_v1_ready_belt_rest", "V1 at READY from a rest on the belt (homed)"),
                                  ("park_first_ready_belt_rest", "park_first at READY from the same rest (homed)"),
                                  ("multi_x2_ready_belt_rest", "the 3D-printer double touch from the same rest"),
                                  ("press_reverse_ready_belt_rest", "press_reverse: both stops at two levels, every home"),
                                  ("zach_v1_forearm_stall", "V1: W1 stalls on the forearm and assigns it as its stop (silent wrong; the tight witness refuses it)"),
                                  ("park_first_w2_short_on_the_plate", "park_first: W2 stops 1.24° short on the gripper plate against the forearm"),
                                  ("fivebar_trip_from_the_belt", "the five-bar's lift-off from a belt rest trips J2's runaway stop"),
                                  ("pep0047_wrist_at_the_bowl", "PEP 0047 as landed: the walk to the five-bar's home drives the claw into the belt"))
              if k in media]
    hero = "zach_v1_ready_belt_rest" if (base.startswith("zach_v1") or base.startswith("V1")) else "park_first_ready_belt_rest"
    return {"recommended": base, "verdict": verdict, "qualification": qualification, "findings": findings, "handoff": handoff,
            "decisions": decisions, "videos": videos, "hero": hero,
            "hero_caption": "the recommended motion from a power cut at READY: the arm lands on the belt, the five-bar homes and walks to READY, the claw closes, W1 / W2 / W3 touch their stops, TD4",
            "ruler_commit": "sim2real 7806abf (frozen), amendments 1-4"}


def build(out: Path, *, results_path: Path, media_index: Path, wandb_summary: Path | None, recommended: str, notes: dict) -> str:
    episodes, calibrations = load(results_path)
    cards = ruler.score(episodes)
    ranked = overall(cards)
    media_ = json.loads(media_index.read_text()) if media_index.is_file() else {}
    wb_ = json.loads(wandb_summary.read_text()) if wandb_summary and wandb_summary.is_file() else {}
    notes = {**auto_notes(cards, ranked, episodes, calibrations, media_, wb_), **notes}
    recommended = notes.get("recommended") or recommended
    media = json.loads(media_index.read_text()) if media_index.is_file() else {}
    plans = pickle.loads(PLANS.read_bytes()) if PLANS.is_file() else {}
    wb = json.loads(wandb_summary.read_text()) if wandb_summary and wandb_summary.is_file() else {}
    nominal_rows = sorted({k.split(" | ")[0] for k in cards if k.endswith(" | nominal")},
                          key=lambda r: rank_key(cards[f"{r} | nominal"]))
    # WHY not every row's map (the page's size: each map is 144 cells): the rows as run, plus the recommended one and the two orders under
    # the tight witness; a table row's map is its plain row's (the table only re-zeroes)
    shown = [r for r in nominal_rows if (not r.endswith(TIGHT) and "+table" not in r) or r in
             (recommended + TIGHT if not recommended.endswith(TIGHT) else recommended, "zach_v1 @ READY" + TIGHT,
              "park_first+witness @ READY" + TIGHT, "V1+table, park_first on a W1 refusal @ READY" + TIGHT)]
    maps = "".join(f"<div class='map'>{coverage_svg(episodes, row, ruler.NOMINAL)}</div>" for row in shown)
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
             "every twin, then nominal coverage, then the worst physical twin's coverage (B1, B2, friction, the heavy claw, another "
             "power-up frame), then zero error, then time. The stale-calibration twin is shown apart: there a tight witness is meant to "
             "refuse everything (re-take the calibration), a loose one passes it. Rows ending “witness 0.5°” are the same runs re-judged by "
             "the tight witness, and the “V1 …, park_first on a W1 refusal” rows are exact from V1's and park_first's runs (they move the "
             "same up to W1's first stall); neither moves the arm differently.</p>", overall_table(ranked),
             "<h2>Scoreboard, nominal twin</h2>", scoreboard(cards),
             "<h2>Coverage maps (nominal)</h2><p class='sub'>Rows W1, columns W2 (°), one panel per five-bar pose; hover a cell for its start "
             "and outcome.</p>", maps,
             "<h2>Perturbed twins (one W1 / W2 diagonal per five-bar pose, 24 cells)</h2>", perturbed(cards),
             "<h3>The folded-wrist cells (W2 at −150°), run before amendment 3</h3><p class='sub'>The first perturbed subset was every 6th "
             "cell - on this grid every cell with W2 at −150°, the folded wrist. Kept as a stress test, never mixed into the cards above.</p>",
             perturbed(cards, " · folded wrist"),
             f"<h3>The stored tables (identify_backlash once per twin)</h3><ul class='sub'>{calib}</ul>",
             "<h2>What we found</h2>", notes.get("findings", ""),
             "<h2>Videos</h2>", "".join(video(media, name, caption) for name, caption in notes.get("videos", [])),
             f"<h2>The sequence for the rack: {esc(recommended)}</h2>", notes.get("handoff", ""),
             *(("<h3>Path 1: V1 (W1's first stall passes the witness)</h3>", sequence_table(plans, "zach_v1+table @ READY", phases=(1,)),
                "<h3>Path 2: park_first (W1's first stall refused)</h3>", sequence_table(plans, "park_first+witness+table @ READY", phases=(1,)))
               if "on a W1 refusal" in recommended else (sequence_table(plans, recommended),)),
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
