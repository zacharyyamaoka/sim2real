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
RESULTS = Path.home() / ".cache" / "sim2real" / "homing_routine" / "results_2026-11-13.json"  # the full results (homing_routine_publish)
CACHE = Path.home() / ".cache" / "sim2real" / "homing_routine" / "episodes_2026-11-13.jsonl"
CALIBRATIONS = Path.home() / ".cache" / "sim2real" / "homing_routine" / "calibrations_tight_2026-11-13.json"
PLANS = Path.home() / ".cache" / "sim2real" / "homing_routine_plans.pkl"
PLANS_J1 = Path.home() / ".cache" / "sim2real" / "homing_routine_plans_j1.pkl"  # the J1 rows' plans (routine_check --plan j1)
# the control that splits J1's wrist losses between J1's home and the rack's J1 gravity (tools/homing_routine_j1_control.py)
J1_CONTROL = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data" / "homing_routine_j1_control_2026-11-14.json"
MEDIA_REL = "media/homing-routine-2026-11-13"
# the rack's wrist homes of 2026-11-13 (10:24, 10:50, 11:24 and the cold one after the 18:05 power-up); 10:24's W3 stalled early
RACK_HOMED = Path("/archive/datasets/bam_rig/full_arm/homed")
RACK_WRIST_HOMES = ("homed_2026-11-13T172448Z.json", "homed_2026-11-13T175048Z.json", "homed_2026-11-13T182448Z.json",
                    "homed_2026-11-14T011708Z.json")
PHYSICAL = ("nominal", "B1", "B2", "friction", "claw_heavy", "phase_draw_2")  # every twin but the stale witness calibration
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


def url_safe(url: str) -> str:
    """A W&B link with its spaces, middle dot and em dash percent-encoded (wandb returns them raw), so it opens from any viewer."""
    from urllib.parse import quote, unquote, urlsplit, urlunsplit  # noqa: PLC0415

    parts = urlsplit(url or "")
    return urlunsplit((parts.scheme, parts.netloc, quote(unquote(parts.path), safe="/=-_.~"), parts.query, parts.fragment))


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


def current_cell(episodes, routine: str, environment: str) -> str:
    if not episodes:
        return "—"
    ratio, joint = current_ratio(episodes, routine, environment)
    return "—" if ratio is None else f"{ratio:.2f} <span class='sub'>{esc(joint)}</span>"


def verdict_chips(card: dict) -> str:
    """How many targets pass, and the names of those that fail."""
    measured = {k: v for k, v in card["verdict"].items() if k != "pass" and v is not None}
    passed = sum(1 for v in measured.values() if v)
    failing = ", ".join(SHORT.get(k, k) for k, v in measured.items() if not v)
    return (f"<span class='{'pass' if passed == len(measured) else ''}'>{passed}/{len(measured)}</span>"
            + (f"<br><span class='sub'>✗ {esc(failing)}</span>" if failing else ""))


def current_ratio(episodes: list[dict], routine: str, environment: str = ruler.NOMINAL) -> tuple[float | None, str]:
    """The worst powered joint's peak current over its board's cap (torque over the board's maximum torque: current is torque / Kt),
    and which joint - the brief's "peak current vs the caps" (the frozen ruler scores speed; this is reported beside it)."""
    worst, joint = None, ""
    for e in episodes:
        if e.get("row") != routine or e.get("environment") != environment or "refused_start" in e:
            continue
        for role, peak in (e.get("peak_torque_nm") or {}).items():
            cap = (e.get("torque_cap_nm") or {}).get(role)
            if cap and role != "J1" and (worst is None or peak / cap > worst):
                worst, joint = peak / cap, role
    return worst, joint


def scoreboard(cards: dict, environment: str = ruler.NOMINAL, episodes: list | None = None) -> str:
    rows = sorted(((key.split(" | ")[0], card) for key, card in cards.items() if key.endswith(f" | {environment}")), key=lambda rc: rank_key(rc[1]))
    head = ("<tr><th>routine (ranked)</th><th>cells run / feasible</th><th>coverage %</th><th>silent wrong</th><th>refused</th>"
            "<th>tripped / timeout</th><th>inaccurate</th><th>zero p95 °</th><th>W1 / W2 / W3 p95 °</th><th>repeat °</th>"
            "<th>backlash ID % · err p95 ′</th><th>time median / p95 s</th><th>belt after lift-off</th><th>peak speed / ceiling</th>"
            "<th>peak current / board cap</th><th>targets</th></tr>")
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
            f"<td>{fmt(card['peak_speed_ratio'], 2)}</td><td>{current_cell(episodes, routine, environment)}</td>"
            f"<td>{verdict_chips(card)}</td></tr>")
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
    # WHY the plain row's plan for a "+table" row: the stored table only re-zeroes in observe - the two command the same
    plan = plans.get(row) or plans.get(row.replace("+table", ""))
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


def ready_only(episodes: list[dict]) -> list[dict]:
    """The episodes on READY's cells - the like-for-like set every row ran (after the rack's pause only V1's and park_first's paths ran
    the other five-bar poses)."""
    first = next(iter(ruler.FIVEBAR_LEVELS))
    return [e for e in episodes if (e.get("family") or str(e.get("start", "")).split(" ")[0]) == first]


def overall(cards: dict, whole: dict | None = None) -> list[tuple[str, dict]]:
    """Every routine ranked across the twins (the ruler's order, per routine): silent wrong summed over every twin, then nominal coverage,
    then the worst perturbed twin's coverage, then nominal zero p95, then nominal median time. ``cards`` are READY's (like for like);
    ``whole`` adds each routine's coverage over every five-bar pose it ran, where that is more than READY.
    WHY rank on READY (2026-11-13): the light plan ran PICK, LIFT and UP for the recommended routine's two paths only, so a whole-grid
    number beside a READY-only one would rank rows on different start sets."""
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
        grid = (whole or {}).get(f"{routine} | {ruler.NOMINAL}")
        if grid and (grid.get("cells") or 0) > (nominal.get("cells") or 0):
            summary.update(grid_coverage=grid["coverage_pct"], grid_feasible=grid["feasible"], grid_cells=grid["cells"],
                           grid_silent=sum(c["silent_wrong"] for k, c in (whole or {}).items() if k.split(" | ")[0] == routine))
        out.append((routine, summary))
    # WHY the rows run on the six subset cells only (fast single, multi x3, PEP 0047) rank after the full ones: 4 of 6 is not 22 of 33
    out.sort(key=lambda rs: (rs[1]["environments"] < 5, rs[1]["silent_wrong_all"], -(rs[1]["coverage"] or 0.0),
                             -(rs[1]["worst_perturbed"] if rs[1]["worst_perturbed"] is not None else -1.0),
                             rs[1]["zero_p95"] if rs[1]["zero_p95"] is not None else 9e9, rs[1]["time"] if rs[1]["time"] is not None else 9e9))
    return out


def overall_table(ranked: list[tuple[str, dict]]) -> str:
    head = ("<tr><th>rank · routine</th><th>silent wrong, every twin</th><th>coverage nominal % (READY)</th>"
            "<th>whole grid % (holdable starts; silent wrong)</th><th>worst physical twin %</th>"
            "<th>stale calibration % (silent wrong)</th><th>twins run</th><th>zero p95 °</th><th>median s</th></tr>")
    body = "".join(f"<tr><td>{k + 1}. <b>{esc(routine)}</b></td><td class='{'pass' if r['silent_wrong_all'] == 0 else 'fail'}'>"
                   f"{r['silent_wrong_all']}</td><td>{fmt(r['coverage'], 1)}</td>"
                   f"<td>{fmt(r['grid_coverage'], 1) + ' (' + str(r['grid_feasible']) + '; ' + str(r['grid_silent']) + ')' if r.get('grid_coverage') is not None else '—'}</td>"
                   f"<td>{fmt(r['worst_perturbed'], 1)}</td>"
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


def lost_split(episodes: list, routine: str) -> dict:
    """The recommended routine's starts over the nominal grid and the physical twins: homed, and the lost ones by where they were lost
    (routine_check.ended_in) and how (trip / timeout / refused / wrong)."""
    from collections import Counter  # noqa: PLC0415

    from sim2real.sim.homing.routine_check import ended_in  # noqa: PLC0415

    homed, lost, belt_s = 0, Counter(), []
    for e in episodes:
        if e.get("row") != routine or e.get("environment") not in PHYSICAL:
            continue
        where = ended_in(e)
        if where is None:
            if e.get("outcome_class") == "homed" and e.get("covered"):
                homed += 1
            elif e.get("outcome_class") == "homed":  # homed, but on the belt after lift-off: not clean, so not covered
                belt_s.append(e.get("belt_last_s") or 0.0)
            continue
        lost[(where, e.get("outcome_class"))] += 1
    return {"homed": homed, "lost": lost, "wrist_lost": sum(v for (w, _), v in lost.items() if w == "wrist"), "belt": len(belt_s),
            "belt_last_s": max(belt_s) if belt_s else None, "j1_lost": sum(v for (w, _), v in lost.items() if w == "J1 home")}


def j1_split(episodes: list, row: str) -> dict:
    """What J1's own seek did in each of ``row``'s episodes, whatever the rest of the arm did: "stop" - its stall recorded within
    ``WRONG_STOP_DEG`` of the CAD stop; "wrong" - recorded further off (a gravity stall read as the stop: silent wrong); "refused" - the
    episode ended in J1's home with no J1 stall (the seek timed out: J1 never assigned); "before" - lost before J1 moved.
    WHY its own count (2026-11-14, the dispatcher: an FF-off or low-cap seed must refuse or flag, never record a stop): the ruler's class
    is the whole arm's, so a V1 W1 gravity stall on the same start would hide what J1 did."""
    from collections import Counter  # noqa: PLC0415

    from sim2real.sim.homing.routine_check import ended_in  # noqa: PLC0415

    out, wrong_deg, error_deg = Counter(), [], []
    for e in episodes:
        if e.get("row") != row or e.get("outcome_class") == "infeasible":
            continue
        stall = next((s for s in e.get("stalls") or [] if s["joint"] == "revolute_3"), None)
        if stall is not None:
            off = stall["link_deg"] - stall["cad_deg"]
            out["wrong" if abs(off) > ruler.WRONG_STOP_DEG else "stop"] += 1
            (wrong_deg if abs(off) > ruler.WRONG_STOP_DEG else error_deg).append(off)
        else:
            out["refused" if ended_in(e) == "J1 home" else "before"] += 1
    return {**{k: out.get(k, 0) for k in ("stop", "wrong", "refused", "before")}, "n": sum(out.values()),
            "wrong_deg": wrong_deg, "stop_error_deg": max((abs(v) for v in error_deg), default=None)}


def j1_contacts(episodes: list, with_j1: str = "zach_v1+J1 @ READY", without: str = "zach_v1 @ READY") -> dict:
    """What J1's home adds to the arm's contacts, start by start in the same twin: the self-contact pairs and the belt re-contacts the J1
    row has that the row without J1 does not, and how much later J1's home makes the same routine end (homed both ways)."""
    old = {(e.get("environment"), e.get("start")): e for e in episodes if e.get("row") == without and "refused_start" not in e}
    compared, new, shifts = 0, [], []
    for e in episodes:
        o = old.get((e.get("environment"), e.get("start")))
        if e.get("row") != with_j1 or o is None or "refused_start" in e or e.get("environment") not in PHYSICAL:
            continue
        compared += 1
        extra = set(e.get("self_contact_pairs") or []) - set(o.get("self_contact_pairs") or [])
        if extra or ((e.get("belt_after_liftoff_ticks") or 0) > 0 and not (o.get("belt_after_liftoff_ticks") or 0)):
            new.append((e.get("environment"), e.get("start"), sorted(extra)))
        if e.get("outcome_class") == o.get("outcome_class") == "homed" and e.get("time_s") and o.get("time_s"):
            shifts.append(e["time_s"] - o["time_s"])
    shifts.sort()
    return {"compared": compared, "new": new, "shift_s": shifts[len(shifts) // 2] if shifts else None}


def j1_landing(episodes: list, with_j1: str = "zach_v1+J1 @ READY", without: str = "zach_v1 @ READY") -> dict:
    """How the J1 rows' plant (the rack's J1 gravity from power-on) changes phase 0, start by start in the same twin: J1's settled angle
    against the CAD plant's, the other joints' worst settled difference, and the starts phase 0 lost only one way.
    WHY (2026-11-14): phase 0 runs before J1 moves, so a start it loses only with J1 is the plant's landing, never J1's home."""
    import statistics  # noqa: PLC0415

    from sim2real.sim.homing.routine_check import ended_in  # noqa: PLC0415

    old = {(e.get("environment"), e.get("start")): e for e in episodes if e.get("row") == without and "refused_start" not in e}
    j1_diff, other, only_now, only_before, compared = [], [], 0, 0, 0
    for e in episodes:
        o = old.get((e.get("environment"), e.get("start")))
        if e.get("row") != with_j1 or o is None or "refused_start" in e or e.get("environment") not in PHYSICAL:
            continue
        compared += 1
        a, b = e.get("start_settled_deg") or {}, o.get("start_settled_deg") or {}
        if a.get("J1") is not None and b.get("J1") is not None:
            j1_diff.append(a["J1"] - b["J1"])
            other.append(max(abs(a[k] - b[k]) for k in ("J2", "C1", "W1", "W2", "W3", "CLAW") if a.get(k) is not None and b.get(k) is not None))
        lost_now, lost_before = ended_in(e) == "phase 0", ended_in(o) == "phase 0"
        only_now += lost_now and not lost_before
        only_before += lost_before and not lost_now
    return {"compared": compared, "j1_settle_median_deg": statistics.median(j1_diff) if j1_diff else None,
            "j1_settle_range_deg": [min(j1_diff), max(j1_diff)] if j1_diff else None, "other_worst_deg": max(other) if other else None,
            "other_median_deg": statistics.median(other) if other else None, "phase0_only_with_j1": only_now, "phase0_only_without": only_before}


def wrong_range(episodes: list, rows: tuple, role: str) -> tuple[float, float] | None:
    """The |zero error| range of ``role`` over the silent-wrong homes of ``rows`` whose worst joint is ``role`` (no folded-wrist cells)."""
    values = []
    for e in episodes:
        if e.get("row") not in rows or e.get("outcome_class") != "silent_wrong" or str(e.get("environment", "")).endswith("folded wrist"):
            continue
        errors = {k: abs(v) for k, v in (e.get("zero_error_deg") or {}).items() if v is not None}
        if errors and max(errors, key=errors.get) == role:
            values.append(errors[role])
    return (min(values), max(values)) if values else None


def wrist_speed_ratio(episodes: list, rows: tuple) -> float | None:
    """Median over the homed nominal starts of ``rows`` of the wrist's worst peak speed / its ceiling."""
    ratios = []
    for e in episodes:
        if e.get("row") not in rows or e.get("environment") != ruler.NOMINAL or e.get("outcome_class") != "homed":
            continue
        peak, ceiling = e.get("peak_speed_deg_s") or {}, e.get("speed_ceiling_deg_s") or {}
        wrist = [peak[r] / ceiling[r] for r in ("W1", "W2", "W3") if peak.get(r) is not None and ceiling.get(r)]
        if wrist:
            ratios.append(max(wrist))
    ratios.sort()
    return ratios[len(ratios) // 2] if ratios else None


def rack_check() -> dict | None:
    """fullarm_routine.rack_phase_spread over the rack's Nov 13 wrist homes (all four, and without 10:24's early W3), or None off this
    machine."""
    from sim2real.sim.homing.fullarm_routine import rack_phase_spread  # noqa: PLC0415

    paths = [RACK_HOMED / name for name in RACK_WRIST_HOMES]
    if not all(path.is_file() for path in paths):
        return None
    return {"all": rack_phase_spread(paths), "good": rack_phase_spread(paths[1:])}


def auto_notes(cards: dict, ranked: list, episodes: list, calibrations: dict, media: dict, wb: dict) -> dict:
    """The page's words from the numbers (every number below is read from the cards; the prose is the analysis of record)."""
    full = [(r, s) for r, s in ranked if s["environments"] >= 5]
    # WHY pinned to the J1 routine when it ran (Zach, 2026-11-13 night): a routine that leaves J1 unhomed does not home the arm, however
    # it ranks on the joints it does home (rows that hold J1 are scored without it - ruler amendment 5)
    from sim2real.sim.homing.fullarm_routine import RECOMMENDED  # noqa: PLC0415

    recommended = (RECOMMENDED + TIGHT if f"{RECOMMENDED + TIGHT} | {ruler.NOMINAL}" in cards else
                   full[0][0] if full else (ranked[0][0] if ranked else ""))
    rec = _c(cards, recommended)
    base = recommended.replace(TIGHT, "")
    plain = _c(cards, base)
    v1, park = _c(cards, "zach_v1 @ READY"), _c(cards, "park_first+witness @ READY")
    v1t, parkt = _c(cards, "zach_v1 @ READY" + TIGHT), _c(cards, "park_first+witness @ READY" + TIGHT)
    pep, multi, press = _c(cards, "PEP 0047 (wrist at the five-bar's home)"), _c(cards, "multi x2 (3D-printer) @ READY"), _c(
        cards, "press_reverse (backlash every home) @ READY")
    # WHY the 0.5 deg rows here: a plain row's p95 on B2 carries its silent wrongs (C1 jammed 44 deg), which is the witness's point, not
    # the table's
    fast, park_b2, table_b2 = _c(cards, "fast single @ READY"), _c(cards, "park_first+witness @ READY" + TIGHT, "B2"), _c(
        cards, "park_first+witness+table @ READY" + TIGHT, "B2")
    nominal = [e for e in episodes if e.get("environment") == ruler.NOMINAL and e.get("row") == "park_first+witness @ READY"
               and "refused_start" not in e]
    trips = [e for e in nominal if e.get("outcome_class") in ("tripped", "timeout")]
    c1_on_base = [e for e in nominal if e.get("outcome_class") == "silent_wrong" and (e.get("zero_error_deg") or {}).get("C1")
                  and abs(e["zero_error_deg"]["C1"]) > 1.0]
    locate = [v for e in episodes if e.get("row") == "multi x2 (3D-printer) @ READY" for v in
              ((e.get("notes") or {}).get("locate_minus_retouch_deg") or {}).values()]
    worst_locate = max((abs(v) for v in locate), default=None)
    locate_true = [abs(v) for e in episodes if e.get("row") == "multi x2 (3D-printer) @ READY" and e.get("outcome_class") == "homed"
                   for v in ((e.get("notes") or {}).get("locate_minus_retouch_deg") or {}).values()]
    true_locate = max(locate_true, default=None)
    n = len(nominal)
    split = lost_split(episodes, recommended)
    lost = split["lost"]
    phase0 = {how: v for (where, how), v in lost.items() if where == "phase 0"}
    park_rows = ("park_first+witness @ READY", "park_first+witness+table @ READY", "multi x2 (3D-printer) @ READY", "fast single @ READY",
                 "multi x3 (3D-printer) @ READY")
    w2_short = wrong_range(episodes, park_rows, "W2")
    w1_short = wrong_range(episodes, ("zach_v1 @ READY", "zach_v1+table @ READY"), "W1")
    c1_short = wrong_range(episodes, tuple({e.get("row") for e in episodes if TIGHT not in str(e.get("row")) and not is_seed(e.get("row"))}),
                           "C1")
    slow_ratio = wrist_speed_ratio(episodes, ("zach_v1 @ READY", "park_first+witness @ READY"))
    fast_ratio = wrist_speed_ratio(episodes, ("multi x2 (3D-printer) @ READY", "fast single @ READY", "multi x3 (3D-printer) @ READY"))
    press_t = _c(cards, "press_reverse (backlash every home) @ READY" + TIGHT)
    press_homes = [e for e in episodes if e.get("row") == "press_reverse (backlash every home) @ READY" and e.get("environment") in ("B1", "B2")
                   and e.get("outcome_class") == "homed"]
    press_missed = [e for e in press_homes if any((e.get("gap_truth_deg") or {}).get(r) and not (e.get("gap_identified_deg") or {}).get(r)
                                                   for r in ("W1", "W2", "W3"))]
    rack = rack_check()

    def rng(span, digits=2):
        return "—" if span is None else f"{span[0]:.{digits}f}-{span[1]:.{digits}f}"

    def pct(k, total):
        return f"{100.0 * k / total:.0f} %" if total else "—"

    order = ("Zach’s V1 order, falling back to PEP 0047’s parking path when W1’s first stall is refused" if "on a W1 refusal" in base
             else "Zach’s V1 order" if base.startswith("zach_v1") else "PEP 0047’s park_first order")
    if "+J1" in base:
        order += (" - after J1 is homed as the rack homes it: from READY one seek to its −89.97° stop under an 11 N·m cap on the rack's "
                  "gains and gravity feed-forward, the stop read only when J1 stands still pushing past 9 N·m, then back to READY's "
                  "−12.7° before the claw")
    rec_ready = _c(ruler.score(ready_only(episodes)), recommended)
    if (rec.get("cells") or 0) > (rec_ready.get("cells") or 0):
        reach = (f"{fmt(rec.get('coverage_pct'), 0)} % of the {rec.get('feasible')} holdable starts of the nominal grid "
                 f"({fmt(rec_ready.get('coverage_pct'), 0)} % at READY)")
    elif "+J1" in base:
        without = _c(cards, recommended.replace("+J1", ""))
        reach = (f"{fmt(rec.get('coverage_pct'), 0)} % of READY's {rec.get('feasible')} holdable starts (J1's rows ran READY's cells, "
                 f"where J1's home starts whatever the pose; the routine without J1 covers {fmt(without.get('coverage_pct'), 0)} % of the "
                 f"whole grid's {without.get('feasible')})")
    else:
        reach = f"{fmt(rec.get('coverage_pct'), 0)} % of the nominal start grid"
    verdict = (f"Home the wrist at READY in {order}, with a "
               f"tight rotor-phase witness (0.5° on a trusted home’s own stall, the five-bar’s drives included) and the stored backlash table: "
               f"0 silent wrong in every twin, {reach}, zeros p95 "
               f"{fmt(rec.get('zero_error_p95_deg'), 3)}°, {fmt(rec.get('time_to_home_median_s'), 0)} s median.")
    handed = split["homed"] + split["belt"] + split["wrist_lost"]
    j1_note = ""
    if split["j1_lost"]:
        from collections import Counter  # noqa: PLC0415

        from sim2real.sim.homing.routine_check import ended_in  # noqa: PLC0415

        where = Counter((e.get("environment"), e.get("outcome_class")) for e in episodes
                        if e.get("row") == recommended and e.get("environment") in PHYSICAL and ended_in(e) == "J1 home")
        j1_note = " (J1’s home lost " + ", ".join(f"{v} {cls} in {env}" for (env, cls), v in sorted(where.items())) + ")"
    qualification = ((f"Every start it lost was lost in the five-bar’s phase 0{', or in J1’s home' if split['j1_lost'] else ''}, not the "
                      f"wrist{j1_note}: the wrist phase homed all {handed} starts it was handed over the nominal grid and the five "
                      f"physical twins") if not split["wrist_lost"] else f"The wrist phase lost {split['wrist_lost']} of the {handed} starts it was handed")
    qualification += (f". On {len(trips)} of {n} nominal starts over the whole grid ({pct(len(trips), n)}) the twin’s five-bar home from a belt "
                      "rest trips J2’s or C1’s 86°/s runaway stop or times out, the same for every routine; the rack runs its own staged "
                      f"five-bar home, which the twin does not model yet. Time ({fmt(rec.get('time_to_home_median_s'), 0)} s median) and "
                      "speed miss their targets everywhere. Sim only; the "
                      "twin’s wrist gaps, claw mass and belt friction are assumptions, and on the rack the five-bar’s zeros carry the "
                      "camera’s J2 +0.8° / C1 −3.8° until its stall angles are re-anchored (the witness checks the same stop, not the angle).")
    j1_text = ""
    if "+J1" in base:
        j1_eps = [e for e in episodes if e.get("row") == recommended and e.get("environment") in PHYSICAL]
        no_j1_rows = recommended.replace("+J1", "")
        ready_cards = ruler.score(ready_only(episodes))
        with_j1, without = _c(ready_cards, recommended), _c(ready_cards, no_j1_rows)
        whole_without = _c(cards, no_j1_rows)
        j1_peak = [e["peak_speed_deg_s"].get("J1") for e in j1_eps if (e.get("peak_speed_deg_s") or {}).get("J1") is not None]
        from sim2real.sim.homing.fullarm_routine import (  # noqa: PLC0415
            J1_ADVERSARIAL_ROWS, J1_FRICTION_MAX_NM, J1_GRAVITY_WORST_NM, J1_JOINT_CAP_NM, J1_SEEK_CAP_NM, J1_STALL_EFFORT_NM)

        own = j1_split(j1_eps, recommended)
        seeds = {row: j1_split(episodes, row) for row in J1_ADVERSARIAL_ROWS}
        path = (media.get("zach_v1_j1_ready_belt_rest") or {}).get("j1") or {}
        rule_margin = J1_STALL_EFFORT_NM - J1_GRAVITY_WORST_NM - J1_FRICTION_MAX_NM
        landing = j1_landing(episodes)
        controlled = json.loads(J1_CONTROL.read_text()).get("starts", []) if J1_CONTROL.is_file() else []
        control = [c for c in controlled if c.get("wrist_lost_only_with_j1", True)]
        homes = [c for c in control if c.get("lost_to") == "J1's home"]
        touched_control = {(c["environment"], c["start"]): c["touched_only_with_j1"] for c in controlled if c.get("touched_only_with_j1")}
        gap = ""
        if landing["compared"]:
            gap = (f"Most of the gap is not J1's home but the J1 rows' plant: they feel the rack's J1 gravity from power-on, so the arm lands "
                   f"on the belt differently (J1 settles {fmt(-landing['j1_settle_median_deg'], 1)}° lower, median, the other joints up to "
                   f"{fmt(landing['other_worst_deg'], 0)}° apart) and phase 0 - which runs before J1 moves - lost "
                   f"{landing['phase0_only_with_j1']} starts only with it and {landing['phase0_only_without']} only without.")
            if control:
                import re  # noqa: PLC0415

                def why(c: dict) -> str:
                    e = next((x for x in episodes if x.get("row") == "zach_v1+J1 @ READY" and x.get("environment") == c["environment"]
                              and x.get("start") == c["start"]), {})
                    outcome = str(e.get("outcome", "")).removeprefix("aborted: ")
                    trip = re.search(r"(revolute_\d+) was driven faster than ([\d.]+) \(\+?(-?[\d.]+).*in step '([^']+)'", outcome)
                    if trip:
                        return (f"'{trip.group(4)}' trips the twin's {trip.group(2)} rad/s runaway stop at {abs(float(trip.group(3))):.1f} "
                                f"rad/s")
                    return f"it ends '{esc(outcome)}'"

                gap += (f" The wrist lost {len(control)} starts only with J1. A control - V1 and park_first on the same plant with J1 held, "
                        f"not homed (<code>tools/homing_routine_j1_control.py</code>) - loses {len(control) - len(homes)} of them the same way, "
                        f"so those are the landing too" + ("; " + "; ".join(
                            f"{c['environment']} {c['start'].split(' claw')[0]} is J1's home: with J1 held V1 ends "
                            f"{(c['rows'].get('zach_v1 @ READY') or {}).get('rack_j1_gravity_held')}, with J1 at −12.7° {why(c)}"
                            for c in homes) if homes else "; none is J1's home") + ".")
        reached = {row: (s.get("n", 0) - s.get("before", 0), s.get("before", 0)) for row, s in seeds.items()}

        def seed(row: str) -> str:
            s = seeds.get(row) or {}
            parts = [f"{s.get('stop', 0)} on the real stop", f"{s.get('refused', 0)} timed out", f"{s.get('wrong', 0)} recorded short"]
            if s.get("wrong_deg"):
                lo, hi = fmt(min(abs(v) for v in s["wrong_deg"]), 1), fmt(max(abs(v) for v in s["wrong_deg"]), 1)
                parts[-1] += f" ({lo}° short)" if lo == hi else f" ({lo}-{hi}° short)"
            if len(set(reached.values())) == 1:  # every seed reached J1's home on the same starts: said once, in the bullet's lead
                return ", ".join(parts)
            return f"{', '.join(parts)} of the {reached[row][0]} starts that reached J1's home"

        seeds_reached = next(iter(set(reached.values()))) if len(set(reached.values())) == 1 else None

        clearance = (f"In the filmed start J1 seeks from {fmt(path.get('seek_from_deg'), 1)}°, bottoms at {fmt(path.get('lowest_deg'), 2)}° "
                     f"and from its return on never rises past {fmt(path.get('highest_after_return_deg'), 2)}° (the clutter's envelope is "
                     f"−9°), pressing at most {fmt(path.get('peak_effort_nm'), 1)} N·m. " if path else "")
        touched = j1_contacts(episodes)

        def contact(env: str, start: str, pairs: list, *, verdict: bool = True) -> str:
            seen = touched_control.get((env, start))
            told = "" if seen is None else (f", first at {fmt(seen.get('first_s'), 1)} s" + (
                "" if not verdict else "; the control " + ("touches it too: the landing" if seen.get("touched_by") == "the plant's landing"
                                                          else "does not: J1's home")))
            named = {"hard_stop_3/l2": "the gripper plate on the forearm"}  # W3's stop block (the plate) on L2
            return f"{env} {start.split(' claw')[0]} ({', '.join(named.get(p, p) for p in pairs) or 'the belt'}{told})"

        landed = all((touched_control.get((env, start)) or {}).get("touched_by") == "the plant's landing" for env, start, _ in touched["new"])
        if touched["compared"]:
            clearance += ((f"Over the {touched['compared']} starts run both ways, J1's home added no contact: the J1 row touched only what "
                           f"the same start touched without J1, and homed {fmt(touched['shift_s'], 0)} s later (median). ")
                          if not touched["new"] else
                          ((f"J1's home added no contact: over the {touched['compared']} starts run both ways, {len(touched['new'])} touched "
                            f"something only on the J1 rows' plant, and the control with J1 held touches each the same way - " if landed else
                            f"Over the {touched['compared']} starts run both ways, {len(touched['new'])} touched something only with J1 - ")
                           + "; ".join(contact(env, start, pairs, verdict=not landed) for env, start, pairs in touched["new"]) + ". "))
        j1_text = (f"<li><b>J1 is homed as the rack homed it (2026-11-14 05:41Z / 05:56Z): J2/C1 → READY → J1 to its top stop → back to "
                   f"READY's −12.7° → the claw and the wrist.</b> One seek of −110° at 7.2°/s under an {J1_SEEK_CAP_NM:g} N·m cap toward "
                   f"stops.json's −89.972° stop - the side the rack homed on (board −1.31529 / −1.31654, 0.07° apart; zero_board 0.25439, "
                   f"sign +1), which swings the arm away from the D435 - on the rack's own gains (<code>bam_rack_twin.hardware.j1_gains</code>: "
                   f"kp ×14 / kd ×16.8, the gravity feed-forward 5.32·sin(q<sub>board</sub> − 0.075) every tick, no integrator), with J2/C1 "
                   f"held on their comp at the tilt. It ends on robot_msgs' new <code>EffortStall</code>: J1 still (&lt; 0.01 rad/s for 0.2 s) "
                   f"while its effort pushes past {J1_STALL_EFFORT_NM:g} N·m; the stall defines J1 and the next step eases it off at once, back "
                   f"to −12.7° under the joint's {J1_JOINT_CAP_NM:g} N·m cap. Margins: gravity peaks at the stop at {J1_GRAVITY_WORST_NM:g} N·m "
                   f"and friction adds ≤ {J1_FRICTION_MAX_NM:g}, so only the stop can push J1 past {J1_STALL_EFFORT_NM:g} N·m "
                   f"({rule_margin:.2f} N·m to spare); the cap leaves {J1_SEEK_CAP_NM - J1_STALL_EFFORT_NM:g} N·m to fire the rule and presses "
                   f"{J1_JOINT_CAP_NM - J1_SEEK_CAP_NM:.2f} N·m inside {J1_JOINT_CAP_NM:g}. The twin's own CAD gravity on J1 is wrong - it "
                   f"rests J1 at +24° where the real arm hangs at −10.3°, and gives 3.9 N·m at the stop against the rack's 5.2 - so the "
                   f"twin's J1 feels the rack's measured curve instead. Result: J1 recorded its real stop on {own['stop']} of {own['n']} "
                   f"recommended-routine starts (READY, the nominal twin and the five physical twins; {own['before']} were lost in phase 0 "
                   f"before J1 moved), worst "
                   f"{'under 0.001' if (own['stop_error_deg'] or 0) < 0.001 else fmt(own['stop_error_deg'], 3)}° off; {own['wrong']} recorded "
                   f"a wrong stop and {own['refused']} timed out in J1's home. "
                   f"At READY the routine covers {fmt(with_j1.get('coverage_pct'), 1)} % with J1 against {fmt(without.get('coverage_pct'), 1)} % "
                   f"without (the routine without J1 covers {fmt(whole_without.get('coverage_pct'), 1)} % of the whole grid); median "
                   f"{fmt(with_j1.get('time_to_home_median_s'), 0)} s against {fmt(without.get('time_to_home_median_s'), 0)} s; J1 peaks at "
                   f"{fmt(max(j1_peak) if j1_peak else None, 1)}°/s. {gap}</li>"
                   f"<li><b>The stall rule holds under adversarial seeds</b> (V1+J1 on the subset's six READY starts, nominal twin"
                   + (f"; {seeds_reached[1]} were lost in phase 0 before J1 moved, the same for every seed, so each counts the "
                      f"{seeds_reached[0]} that reached J1's home" if seeds_reached else "")
                   + f"). Feed-forward "
                   f"off at the 11 N·m cap: {seed('zach_v1+J1 FF off @ READY')} - the PD alone carries gravity and friction (≤ "
                   f"{J1_GRAVITY_WORST_NM + J1_FRICTION_MAX_NM:.1f} N·m), so the seek still reaches the stop and only the stop passes 9 N·m - "
                   f"which is how the rack's own minimal J1 home ran at 05:56Z (velocity mode, no feed-forward, 11 N·m, the 9 N·m rule). "
                   f"Cap 5.5 N·m: {seed('zach_v1+J1 cap 5.5 @ READY')}. Feed-forward off and cap 5.5: "
                   f"{seed('zach_v1+J1 FF off, cap 5.5 @ READY')} - J1 sags short under gravity, and 5.5 &lt; 9 can never fire the rule. "
                   f"The same seed on the old lead stall: {seed('zach_v1+J1 FF off, cap 5.5, lead rule @ READY')} - the gravity stall read "
                   f"as the stop, the rack's 22:54 trap and the silent wrong the rule exists to stop. So the rule, not the cap, keeps a "
                   f"gravity stall out: with it a fault either finds the real stop or times out and holds.</li>"
                   f"<li><b>J1's clearance and the rack's side.</b> On the rack J1 starts at READY's −12.7°, seeks away from the "
                   f"side-table clutter that blocks it above −7° (<code>full_arm/obstacles/j1_contact_20261114T0711Z.json</code>, "
                   f"envelope −9°) and comes back to −12.7°, so it never has to rise above where it began. {clearance}Along 0 → −90° "
                   f"(twin statics, 1° steps, five-bar at READY, every hanging wrist pose) "
                   f"nothing touches itself or the belt - J1 moves the arm rigidly - and the arm sweeps y −0.43…+0.27 m, z 0.18…0.80 m; the "
                   f"clutter, the rails and the D435 are not in the twin, and the grid's J1 starts (0°, +6°) sit in the band the clutter "
                   f"blocks, so they are twin-only. On the rack: phase 0's READY hold and J1's home run in one process with J1's "
                   f"feed-forward on from the first tick (hand-offs between processes sagged J1 15-30°); J1's zero goes through "
                   f"<code>bam_rack_twin.hardware.zero_writer</code>; the witness is the 05:41Z / 05:56Z stalls' phase at 0.5°, blind to "
                   f"which stop (the two are 179.95° apart = 5 rotor turns within 0.05°), so check the direction from the motion. I "
                   f"retract my earlier advice to check J1's first stall within 3.5° of the gravity rest's frame: that frame was 10.93° "
                   f"off, and only the camera (hand-eye −11.0 ± 0.5°) could vouch for the first stall.</li>")
    rack_text = ""
    if rack:
        good, every = rack["good"], rack["all"]
        rack_text = (f" <b>On the rack</b> (<code>rack_phase_spread</code> over the Nov 13 wrist homes at 10:24, 10:50, 11:24 and the cold one "
                     f"after the 18:05 power-up): each joint's seek stop repeated its phase mod 36° within "
                     f"{fmt(every.get('W1', {}).get('spread_deg'), 3)}° (W1), {fmt(every.get('W2', {}).get('spread_deg'), 3)}° (W2), "
                     f"{fmt(good.get('W3', {}).get('spread_deg'), 3)}° (W3 without 10:24) and {fmt(every.get('CLAW', {}).get('spread_deg'), 3)}° "
                     f"(the claw's closed stop); 10:24's early W3 stall sits {fmt(every.get('W3', {}).get('spread_deg'), 2)}° off. 0.5° leaves "
                     f"room for the real spread and refuses that home.")
    wrist_title = ("The wrist phase homes every start it is handed; the coverage that is missing is the five-bar's." if not split["wrist_lost"]
                   else f"The wrist phase homed {split['homed'] + split['belt']} of the {split['homed'] + split['belt'] + split['wrist_lost']} "
                        f"starts it was handed; the rest of the missing coverage is the five-bar's.")
    findings = f"""
<ol>
{j1_text}
<li><b>{wrist_title}</b> Over the nominal grid and the
five physical twins the recommended routine homed {split['homed']} starts cleanly and lost {sum(lost.values()) + split['belt']}:
{split['wrist_lost']} in the wrist phase, and in phase 0 {phase0.get('tripped', 0)} J2/C1 runaway trips, {phase0.get('timeout', 0)}
walk-home timeouts, {phase0.get('refused', 0)} C1 stalls on the claw jammed against the base that the witness refused (one wrist pose,
W1 +150 / W2 −90 / W3 −120, in every five-bar pose and twin){f" and {split['belt']} homes that brushed the belt with W3's stop block in their first {fmt(split['belt_last_s'], 1)} s" if split['belt'] else ""}.
Phase 0 here is the twin's <code>single_touch_ready+gff</code>; on the rack the Sim to Real Agent's staged five-bar home replaces it.</li>
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
(−30°, +35°]; with W3 near −120° the gripper plate (W3's stop block) meets the forearm (L2) {rng(w2_short)}° before W2's stop, inside PEP
0047's 2° tolerance: {park.get('silent_wrong', 0)} silent wrongs on the nominal grid. Zach's V1, which runs without a witness, assigned W1's
stall on the forearm as its stop when the wrist started folded ({v1.get('silent_wrong', 0)} silent wrongs, {rng(w1_short, 0)}° off), and
once the five-bar's C1 stalled {rng(c1_short, 0)}° short on the claw jammed against the base ({len(c1_on_base)} start), wrong for every
routine because the five-bar had no witness. Calibrated on a trusted home's own stall (the rack's <code>rotor_phase_from_homed</code> is one
by construction), a 0.5° witness on all six homed joints refuses every one of them and no true stop: V1 {v1.get('silent_wrong', 0)} → {v1t.get('silent_wrong', 0)},
park_first {park.get('silent_wrong', 0)} → {parkt.get('silent_wrong', 0)}. Its price: a calibration gone stale (an encoder recalibrated,
the gear train rebuilt) refuses everything - safe, and the <i>phase_cal_error</i> twin shows it. Re-take the calibration after any such
job.{rack_text}</li>
<li><b>The witness proves the same stop, not the right angle.</b> It compares each stall with a trusted home's stall mod one rotor
turn, so a home is only as accurate as the stop angle that trusted home assigned; the twin's {fmt(rec.get('zero_error_p95_deg'), 3)}° is
against the twin's own truth. On the rack the wrist's 11:24 reference is ArUco-checked to ±0.5° (W3 at −90 / +120 / +150), and the
camera fit puts the five-bar's homed map off by J2 +0.8° and C1 −3.8° (the Sim to Real Agent, Nov 13 night). While J2's and C1's stall
angles come from homed_083647, every home reproduces that offset and the witness cannot see it. Re-anchor the two stall angles to the
camera once, after checking the offset holds across the camera's poses (one that changes with pose is as-built geometry - the Nov 11
strips fit found L2 1.5 % short and tilted 2.4° - and belongs in the as-built model, not the zero); the witness then keeps every home on
that anchor. The witness's phases do not change: re-anchoring moves the angle assigned to a stop, not the board's reading at it. Its
other blind spot: a wrong stall within 0.5° of a whole 36° turn passes (about 1 in 36 of evenly spread wrong stalls; none in the twin),
which the same camera check after a home closes.</li>
<li><b>V1's order beats park_first once the witness is tight.</b> V1 covers {fmt(v1t.get('coverage_pct'), 1)} % against park_first's
{fmt(parkt.get('coverage_pct'), 1)} % and is {fmt((park.get('time_to_home_median_s') or 0) - (v1.get('time_to_home_median_s') or 0), 0)} s
faster: its own failure (W1 sweeping into the forearm when the wrist starts folded) is refused, not silent, under the witness, while
park_first's parking leaves W1 off zero for W2's seek and opens the plate-on-forearm stall. Both touch the forearm at ≤ 1 N·m on some starts
(Zach, 10:15: accepted).</li>
<li><b>The 3D-printer double touch buys no accuracy here.</b> On every true stop its fast locate and slow re-touch read the same angle
within {fmt(true_locate, 4)}° ({fmt(worst_locate, 3)}° at most on the wrong stops): a torque-capped stall is read standing still at a fixed
torque, with no trigger latency for a slow approach to remove. Its {fmt(multi.get('time_to_home_median_s'), 0)} s median comes from its
60°/s moves - the fast single control without the re-touch is {fmt(fast.get('time_to_home_median_s'), 0)} s - and at 60°/s the wrist peaks
at {fmt(fast_ratio, 2)}× its 86°/s ceiling on the median start ({fmt(slow_ratio, 2)}× at the recipe's 36°/s). The forward-and-back that
pays is touching BOTH stops: press_reverse identifies the wrist's gaps itself (wrist zeros p95
{fmt(wrist_p95(_c(cards, 'press_reverse (backlash every home) @ READY', 'B2')), 3)}° on the geared B2 twin; it read a 0.3° gap as 0 on
{len(press_missed)} of its {len(press_homes)} B1/B2 homes) and its span check refuses the near-stop stalls - for
{fmt((press_t.get('time_to_home_median_s') or 0) - (rec.get('time_to_home_median_s') or 0), 0)} s more than the recommended routine.</li>
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
move overshoots its ramp ~2× ({fmt(slow_ratio, 2)}× the 86°/s ceiling at the recipe's 36°/s), and the five-bar's trips peak far higher. Time:
the recommended routine's median is {fmt(rec.get('time_to_home_median_s'), 0)} s against the 60 s target (the five-bar's own home took
36-45 s alone in the phase-0 probe).</li>
</ol>"""
    handoff = (f"<p>Phase 0 is the rack's own staged five-bar home (stalls, C1 eased off, the corridor to READY) - this routine adds a "
               f"rotor-phase witness on J2 and C1 calibrated on the trusted manual stall zero. Phase 1, below, runs at READY with the "
               f"five-bar held: "
               + ("J1 seeks its −89.97° stop at 0.02 rev/s under 11 N·m on the rack's j1_gains (PD + gravity feed-forward every tick, no "
                  "integrator), is defined when it stands still pushing past 9 N·m (EffortStall), eases off at once and goes back to "
                  "READY's −12.7° under its 17.98 N·m cap - all in the process that held READY; then " if "+J1" in base else "")
               + f"the claw closes, then each wrist joint touches its stop once at 1 N·m and 36°/s, is witnessed "
               f"<b>as its defining step ends</b> (0.5° on the 11:24 home's stall: W3's + stop at +2.78° mod 36°; no expected-travel "
               f"check - a seek may end short because the joint started near its stop), goes to 0, and the routine ends at TD4. "
               + ("<b>The branch:</b> W1's first seek is the same move in V1 and park_first; if the witness refuses its stall (the "
                  "gripper on the forearm, a folded wrist), do not assign it - carry on with park_first's path (W1 back 135°, W2, W1 again, "
                  "W3). " if "on a W1 refusal" in base else "")
               + f"The stored table corrects each zero for its gap and wind-up. <code>python -m sim2real.sim.homing.fullarm_routine "
               f"--out plan.json</code> writes both paths and the branch rule as JSON.</p>"
               + ("<p><b>J1 on the rack runs this home itself:</b> <code>python -m sim2real.sim.homing.j1_rack</code> (in the deployment venv, "
                  "~/bam_ws-armhold/src/dev/bam_rack_twin; <code>--dry-run</code> reads the files and opens nothing, <code>--twin</code> runs the "
                  "same loop on a stand-in J1, <code>--allow-motion --out</code> under powered_launch is the real run). It sends "
                  "<code>j1_home</code>'s two steps - the bytes the twin ran, pinned equal by a test - in one process over fullarm_stops' bus "
                  "(the fast take-over from arm-hold, every HeldBus guard), J1's gravity fed forward at its joint angle only in a frame it can "
                  "trust (none after a power-up until the stall defines it), walks J1 back to its start when the seek is refused, and writes "
                  "J1's zero only through <code>zero_writer</code> (whose commit is <code>homed_history.write_latest</code>): a stall within "
                  "0.1° of the map confirms it, a sub-turn shift is written, whole rotor turns only after a power-up, never off the stop's "
                  "rotor phase (0.5° of the 05:41Z / 05:56Z stalls). PID tuna's measured-mass gravity (bam_fb_v2_masses_2026-11-14.json, on "
                  "bam_ws main) is not wired into arm-hold / fullarm_stops yet, so J1's feed-forward stays j1_gains' READY curve until it is.</p>"
                  if "+J1" in base else ""))
    decisions = """<ul>
<li><b>Decided for you</b> (each a default in code; undo in one line):
 <ul><li>J1 homes as the rack homed it - one 11 N·m seek to its −89.97° stop on the rack's j1_gains, done on robot_msgs'
 <code>EffortStall</code> at 9 N·m, then back to READY's −12.7° before the claw - and the ruler scores J1 for rows that home it
 (amendment 5) (undo: <code>home_j1=False</code>; the old lead stall: <code>j1_stall_rule="lead"</code>);</li>
 <li>the twin's J1 feels the rack's measured gravity, not the CAD's (undo: <code>j1_rack=False</code> on the plant);</li>
 <li>the wrist homes at READY, not the five-bar's home (undo: <code>wrist_pose="bowl"</code>);</li>
 <li>V1's order over PEP 0047's park_first for the rack (undo: <code>order="park_first"</code>);</li>
 <li>the witness at 0.5° on a trusted home's stall, the five-bar's drives included (undo: <code>witness_tol_deg=2.0</code>);</li>
 <li>the witness calibrated on the 11:24 home, per the Sim to Real Agent's ArUco check and Zach's video ruling;</li>
 <li>the ruler's four amendments, none moving a metric or target: lift-off is 2 s clear of the belt; rows added after READY's
 map (V1 in the perturbed twins, the tight witness and the table as derived rows); the perturbation subset made a W1 / W2 diagonal (it had
 been W2 −150 only, a sampling bug - the folded-wrist runs are shown apart); step timeouts labelled timeouts, not trips.</li></ul></li>
<li><b>Left, not blocked:</b> re-anchor J2's and C1's stall angles to the camera (the fit says J2 +0.8°, C1 −3.8°; check it holds across
 poses first - the Sim to Real Agent's rig); the five-bar's lift-off from a belt rest (the coverage ceiling; its lane: model the rack's staged five-bar home
 in the twin and re-score, or fix the J2/C1 runaways in <code>single_touch_ready+gff</code>); a retry after a refusal (turn W3 and
 touch W2 again) to win back the refused starts; accel-limited or better-damped wrist moves before any speed-up; the real rung through the
 Sim to Real Agent; J1's feed-forward on the rack's pose fit - the READY curve is pose-blind (5.2 N·m at the stop where the fit puts the
 twin's 32 settled wrist poses at 2.1-3.5), which the effort rule does not need, but it is why no check can tell a missing feed-forward from
 the curve's own error on the seek's lag.</li>
<li><b>Needs you:</b> nothing irreversible.</li>
<li><b>Not done:</b> no hardware moved (sim only); the five-bar's homing itself is unchanged beyond the witness.</li>
</ul>"""
    videos = [(k, v) for k, v in (("zach_v1_j1_ready_belt_rest", "J1 first: V1+J1 - the five-bar to READY, J1 seeks its −89.97° stop "
                                                                  "and comes back to READY's −12.7°, then the claw and the wrist"),
                                  ("zach_v1_ready_belt_rest", "V1 at READY from a rest on the belt (homed)"),
                                  ("park_first_ready_belt_rest", "park_first at READY from the same rest (homed)"),
                                  ("multi_x2_ready_belt_rest", "the 3D-printer double touch from the same rest"),
                                  ("press_reverse_ready_belt_rest", "press_reverse: both stops at two levels, every home"),
                                  ("zach_v1_forearm_stall", "V1: W1 stalls on the forearm and assigns it as its stop (silent wrong; the tight witness refuses it)"),
                                  ("park_first_w2_short_on_the_plate", "park_first: W2 stops 1.24° short on the gripper plate (W3\u2019s stop block) against the forearm (L2)"),
                                  ("fivebar_trip_from_the_belt", "the five-bar's lift-off from a belt rest trips J2's runaway stop"),
                                  ("pep0047_wrist_at_the_bowl", "PEP 0047 as landed: the walk to the five-bar's home drives the claw into the belt"))
              if k in media]
    hero = "zach_v1_ready_belt_rest" if (base.startswith("zach_v1") or base.startswith("V1")) else "park_first_ready_belt_rest"
    hero_caption = ("the recommended motion from a power cut at READY: the arm lands on the belt, the five-bar homes and walks to READY, "
                    "the claw closes, W1 / W2 / W3 touch their stops, TD4")
    if "+J1" in base and "zach_v1_j1_ready_belt_rest" in media:
        hero = "zach_v1_j1_ready_belt_rest"
        hero_caption = ("the recommended motion from a power cut at READY: the arm lands on the belt, the five-bar homes and walks to "
                        "READY, J1 rolls the plane to its −89.97° stop and comes back to READY's −12.7°, the claw closes, W1 / W2 / W3 "
                        "touch their stops, TD4")
    return {"recommended": base, "verdict": verdict, "qualification": qualification, "findings": findings, "handoff": handoff,
            "decisions": decisions, "videos": videos, "hero": hero,
            "hero_caption": hero_caption,
            "ruler_commit": "sim2real 7806abf (frozen), amendments 1-5"}


def grid_scope(run: list[dict]) -> str:
    """What the grid actually covered, read from the runs (the sweep was paused for the rack and capped afterwards)."""
    nominal = {(e.get("cell") or {}).get("fivebar") for e in run if e.get("environment") == ruler.NOMINAL and e.get("row") == "zach_v1 @ READY"}
    poses = [p for p in ruler.FIVEBAR_LEVELS if p in nominal]
    missing = [p for p in ruler.FIVEBAR_LEVELS if p not in nominal]
    per_twin: dict = {}
    for e in run:
        if e.get("environment") not in (ruler.NOMINAL, None) and not str(e.get("environment")).endswith(" · folded wrist"):
            per_twin.setdefault(e["environment"], set()).add(e.get("start"))
    counts = sorted({len(v) for v in per_twin.values()}) or [0]
    perturbed = f"{counts[0]}" if len(counts) == 1 else f"{counts[0]}-{counts[-1]}"
    every_row = {(e.get("cell") or {}).get("fivebar") for e in run if e.get("environment") == ruler.NOMINAL
                 and e.get("row") == "multi x2 (3D-printer) @ READY"}
    first = [p for p in ruler.FIVEBAR_LEVELS if p in every_row] or poses[:1]
    later = [p for p in poses if p not in first]
    text = (f"The nominal grid ran every row on {', '.join(first)} ({36 * len(first)} cells)"
            + (f", and V1's and park_first's paths (the recommended routine's two) on {', '.join(later)} too ({36 * len(poses)} cells)"
               if later else "")
            + (f"; {', '.join(missing)} were not run - the sweep was paused while the rack homed and the host was starved, and the "
               f"remaining cells are one command away (routine_check --plan light --workers 2, the cache skips what ran)" if missing else "")
            + f". The perturbed twins ran {perturbed} of the 24 subset cells each.")
    return text


def is_seed(row: str | None) -> bool:
    """An adversarial J1 seed (fullarm_routine.J1_ADVERSARIAL_ROWS) or its tight-witness re-judging: a fault injected to test J1's stall
    rule, not a routine - kept out of the rankings, the scoreboard and the maps, counted in J1's finding (j1_split)."""
    from sim2real.sim.homing.fullarm_routine import J1_ADVERSARIAL_ROWS  # noqa: PLC0415

    return str(row or "").removesuffix(TIGHT) in J1_ADVERSARIAL_ROWS


def build(out: Path, *, results_path: Path, media_index: Path, wandb_summary: Path | None, recommended: str, notes: dict) -> str:
    every_episode, calibrations = load(results_path)
    episodes = [e for e in every_episode if not is_seed(e.get("row"))]
    cards = ruler.score(episodes)
    ranked = overall(ruler.score(ready_only(episodes)), whole=cards)
    media_ = json.loads(media_index.read_text()) if media_index.is_file() else {}
    wb_ = json.loads(wandb_summary.read_text()) if wandb_summary and wandb_summary.is_file() else {}
    notes = {**auto_notes(cards, ranked, every_episode, calibrations, media_, wb_), **notes}
    recommended = notes.get("recommended") or recommended
    media = json.loads(media_index.read_text()) if media_index.is_file() else {}
    plans = {**(pickle.loads(PLANS.read_bytes()) if PLANS.is_file() else {}),
             **(pickle.loads(PLANS_J1.read_bytes()) if PLANS_J1.is_file() else {})}
    wb = json.loads(wandb_summary.read_text()) if wandb_summary and wandb_summary.is_file() else {}
    nominal_rows = sorted({k.split(" | ")[0] for k in cards if k.endswith(" | nominal")},
                          key=lambda r: rank_key(cards[f"{r} | nominal"]))
    # WHY not every row's map (the page's size: each map is 144 cells): the rows as run, plus the recommended one and the two orders under
    # the tight witness; a table row's map is its plain row's (the table only re-zeroes)
    shown = [r for r in nominal_rows if (not r.endswith(TIGHT) and "+table" not in r) or r in
             (recommended + TIGHT if not recommended.endswith(TIGHT) else recommended, "zach_v1 @ READY" + TIGHT,
              "park_first+witness @ READY" + TIGHT, "V1+table, park_first on a W1 refusal @ READY" + TIGHT)]
    maps = "".join(f"<div class='map'>{coverage_svg(episodes, row, ruler.NOMINAL)}</div>" for row in shown)
    run = [e for e in episodes if not e.get("derived_from") and not str(e.get("environment", "")).endswith(" · folded wrist")]
    done = sum(1 for e in run if e.get("environment") == ruler.NOMINAL)
    from sim2real.sim.homing.routine_check import plan_jobs  # noqa: PLC0415

    planned = (sum(len(j["rows"]) for j in plan_jobs("light") if j["environment"] == ruler.NOMINAL)
               + sum(len(j["rows"]) for j in plan_jobs("j1_ready") if j["environment"] == ruler.NOMINAL))
    calib = "".join(f"<li><b>{esc(env)}</b>: {esc(c.get('outcome'))}; gap error vs hidden (′): {esc(c.get('gap_error_arcmin'))}</li>"
                    for env, c in calibrations.items())
    wandb_line = (f"<p>W&amp;B: <a href='{esc(url_safe(wb.get('project_url', '')))}'>project {esc(wb.get('project', 'Homing · bam_fb_v2'))}</a>"
                  + (f" · <a href='{esc(url_safe(wb['report']))}'>the report (parallel coordinates, coverage maps, replays)</a>"
                     if wb.get("report") else "") + "</p>") if wb else ""
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Homing routine bam_fb_v2</title><style>{CSS}</style></head><body>",
             "<h1>A better homing routine for the full arm (bam_fb_v2) — sim only</h1>",
             f"<p class='verdict'>{notes.get('verdict', '')}</p><p class='sub'>{notes.get('qualification', '')}</p>",
             f"<p class='sub'>Episodes run: {done} of {planned} planned on the nominal twin (the J1 rows' {sum(1 for e in run if e.get('homes_j1') and e.get('environment') == ruler.NOMINAL)} "
             f"on READY's cells included) + {len(run) - done} in the perturbed twins "
             f"(+ {len(episodes) - len(run)} derived or folded-wrist rows). {grid_scope(run)} "
             + ("J1's rows (V1+J1, park_first+J1) ran READY's 36 cells and every twin's 6 READY cells, the four adversarial J1 "
                "seeds the subset's 6 READY cells. " if any(e.get("homes_j1") for e in run) else "")
             + f"Ruler frozen before any routine ran (<code>sim2real.sim.homing.routine_ruler</code>, {esc(notes.get('ruler_commit', ''))}). "
             f"Twin: MuJoCo, bam_fb_v2 @ cad-exporter 09374d7, the rack's belt as a contact.</p>", wandb_line,
             video(media, notes.get("hero", ""), notes.get("hero_caption", "")),
             "<h2>What good looks like (frozen first)</h2>", targets_table(),
             "<p class='sub'>Rank: silent wrong, then coverage, then zero error, then time — time never buys accuracy. A start is the pose "
             "the arm was in when the power went (4 five-bar poses × W1 × W2, W3 / claw / J1 balanced); the twin lets the whole arm fall "
             "onto the belt, its stops or itself before power-on, so hanging on the belt is where most starts begin, as on the rack.</p>",
             "<h2>Overall, across every twin</h2><p class='sub'>Ranked on READY's cells, which every row ran, by the ruler's order per routine: silent wrong summed over "
             "every twin, then nominal coverage, then the worst physical twin's coverage (B1, B2, friction, the heavy claw, another "
             "power-up frame), then zero error, then time. The stale-calibration twin is shown apart: there a tight witness is meant to "
             "refuse everything (re-take the calibration), a loose one passes it. Rows ending “witness 0.5°” are the same runs re-judged by "
             "the tight witness, and the “V1 …, park_first on a W1 refusal” rows are exact from V1's and park_first's runs (they move the "
             "same up to W1's first stall); neither moves the arm differently. A row without the stored table scores 0 % on B1 and B2: each wrist "
             "stop reads 0.46-0.50° off there, past the 0.1° gate, which is the table's point.</p>", overall_table(ranked),
             "<h2>Scoreboard, nominal twin</h2>", scoreboard(cards, episodes=episodes),
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
             *(("<h3>Path 1: V1 (W1's first stall passes the witness)</h3>",
                sequence_table(plans, "zach_v1+table+J1 @ READY" if "+J1" in recommended else "zach_v1+table @ READY", phases=(1,)),
                "<h3>Path 2: park_first (W1's first stall refused)</h3>",
                sequence_table(plans, "park_first+witness+table+J1 @ READY" if "+J1" in recommended else "park_first+witness+table @ READY",
                               phases=(1,)))
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
