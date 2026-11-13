"""Build the full-arm homing report (bam_fb_v2, sim only) from the fullarm_check results and the episode videos.

    /home/bam/sim2real/.venv/bin/python /home/bam/sim2real/tools/fullarm_homing_report.py --out /home/bam/bam_ws/reports/fullarm-homing-2026-11-13.html

Reads src/sim2real/data/fullarm_check_{orders,backlash,replay}_2026-11-13.json (+ the _held runs) and the media folder's videos.json; the
videos stay files beside the page (reports/media/fullarm-homing-2026-11-13/), referenced relatively.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "sim2real" / "data"
MEDIA_REL = "media/fullarm-homing-2026-11-13"


def load(name: str) -> dict | None:
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else None


def fmt(value, digits: int = 3, unit: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}{unit}"
    return f"{value}{unit}"


def esc(text) -> str:
    return html.escape(str(text))


def card_rows(summary: dict) -> list[dict]:
    rows = []
    for key, card in summary.items():
        procedure, environment = key.split(" | ")
        worst = card["worst_zero_deg"]
        rows.append({
            "procedure": procedure, "environment": environment, "episodes": card["episodes"],
            "reliability": card["reliability_pct"], "any_start": card["any_start_pct"], "safe": card["safe_pct"],
            "guard": card["guard_breach_episodes"], "contact": card["self_contact_episodes"], "silent": card["silent_wrong"],
            "refused": card["refused"], "tripped": card["tripped"], "time": card["time_to_home_s"], "time95": card.get("time_to_home_p95_s"),
            "zero_p95": card.get("joint_angle_error_deg"), "gap": card.get("backlash_error_deg"),
            "wrist_zero": max((worst.get(k) or 0.0) for k in ("W1", "W2", "W3")),
            "speed": card["worst_speed_deg_s"], "torque": card["worst_torque_nm"], "outcomes": card["outcomes"]})
    return rows


def table(rows: list[dict], *, title: str) -> str:
    head = ("<tr><th>procedure</th><th>env</th><th>n</th><th>reliable %</th><th>any-start %</th><th>no contact, no guard breach %</th>"
            "<th>guard breach</th><th>twin contact</th><th>silent wrong</th><th>refused</th><th>tripped</th><th>time median s</th>"
            "<th>zero p95 °</th><th>worst wrist zero °</th><th>peak W1 °/s</th><th>peak J2 / C1 °/s</th></tr>")
    body = []
    for r in rows:
        silent_class = "bad" if r["silent"] else "good"
        body.append(
            f"<tr><td><b>{esc(r['procedure'])}</b></td><td>{esc(r['environment'].removeprefix('mujoco/'))}</td><td>{r['episodes']}</td>"
            f"<td>{fmt(r['reliability'], 1)}</td><td>{fmt(r['any_start'], 1)}</td><td>{fmt(r['safe'], 1)}</td><td>{r['guard']}</td>"
            f"<td>{r['contact']}</td><td class='{silent_class}'>{r['silent']}</td><td>{r['refused']}</td><td>{r['tripped']}</td>"
            f"<td>{fmt(r['time'], 1)}</td><td>{fmt(r['zero_p95'], 3)}</td><td>{fmt(r['wrist_zero'], 3)}</td>"
            f"<td>{fmt(r['speed'].get('W1'), 0)}</td><td>{fmt(r['speed'].get('J2'), 0)} / {fmt(r['speed'].get('C1'), 0)}</td></tr>")
    return f"<h3>{esc(title)}</h3><div class='scroll'><table>{head}{''.join(body)}</table></div>"


def outcomes(rows: list[dict]) -> str:
    items = []
    for r in rows:
        for start, outcome in r["outcomes"]:
            items.append(f"<li><b>{esc(r['procedure'])}</b> ({esc(r['environment'].removeprefix('mujoco/'))}) from <i>{esc(start)}</i>: "
                         f"{esc(outcome)}</li>")
    return "<ul class='small'>" + "".join(items) + "</ul>" if items else "<p>Every episode finished.</p>"


def video(name: str, videos: dict, caption: str) -> str:
    entry = videos.get(name)
    if not entry:
        return f"<p class='small'>(video {esc(name)} not rendered)</p>"
    report = entry["report"]
    zero = {k: v for k, v in report["zero_error_deg"].items() if v is not None}
    zero_text = ", ".join(f"{k} {v:+.3f}°" for k, v in zero.items())
    return (f"<figure><video src='{MEDIA_REL}/{name}.mp4' poster='{MEDIA_REL}/{name}.jpg' autoplay muted loop playsinline controls></video>"
            f"<figcaption><b>{esc(caption)}</b> — {esc(report['outcome'][:140])}; zero error vs hidden truth: {esc(zero_text) or '—'}; "
            f"twin self-contact ticks {report['self_contact_ticks']}, CAD-guard breach ticks {report['guard_breach_ticks']}. "
            f"{entry['speedup']:g}× real time. <a href='{MEDIA_REL}/{name}.gif'>GIF</a></figcaption></figure>")


CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#e2e1dc;--good:#1f7a3a;--bad:#b3261e;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--good:#6fcf8f;--bad:#ff8a80;--card:#1f1f1d}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Segoe UI,Inter,sans-serif;margin:0 auto;max-width:1100px;padding:24px 16px}
h1{font-size:24px;margin:0 0 6px}h2{font-size:19px;margin:34px 0 8px;border-top:1px solid var(--line);padding-top:18px}h3{font-size:16px}
.verdict{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px}
table{border-collapse:collapse;font-size:13px;width:100%}th,td{border-bottom:1px solid var(--line);padding:5px 7px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}.scroll{overflow-x:auto}.good{color:var(--good)}.bad{color:var(--bad);font-weight:600}
.small{font-size:13px;color:var(--muted)}figure{margin:12px 0}video{width:100%;max-width:640px;border-radius:6px;border:1px solid var(--line)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}code{font-size:13px}
"""


def rescored(results: dict | None) -> dict | None:
    """A run scored before the crank fix (C1's stall read on the CAD's turn, sim2real 1fd3a52): its stalls re-wrapped, its summary recomputed
    with fullarm_check's own scorer. Nothing else changes."""
    if results is None:
        return None
    import sys  # noqa: PLC0415

    sys.path.insert(0, str(DATA.parents[1]))
    from sim2real.sim.homing.fullarm_check import summarize, wrap_deg  # noqa: PLC0415

    for report in results["reports"]:
        for stall in report.get("stalls", []):
            stall["link_deg"] = stall["cad_deg"] + wrap_deg(stall["link_deg"] - stall["cad_deg"])
    results["summary"] = summarize(results["reports"])
    return results


def build(out: Path) -> Path:
    orders = load("fullarm_check_orders_2026-11-13.json")
    held = rescored(load("fullarm_check_orders_held_2026-11-13.json"))
    kp15 = load("fullarm_check_orders_kp15_2026-11-13.json")
    backlash = load("fullarm_check_backlash_2026-11-13.json")
    backlash_held = load("fullarm_check_backlash_held_2026-11-13.json")
    replay = load("fullarm_check_replay_2026-11-13.json")
    videos_path = out.parent / MEDIA_REL / "videos.json"
    videos = json.loads(videos_path.read_text()) if videos_path.exists() else {}
    parts = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Full-arm homing</title><style>{CSS}</style></head><body>"]
    parts.append(Path(__file__).with_name("fullarm_homing_report_head.html").read_text() if
                 Path(__file__).with_name("fullarm_homing_report_head.html").exists() else "")
    parts.append("<h2>1 · The sequence, from the rack's own start</h2>")
    parts.append(video("park_first_real", videos, "park_first, full arm: five-bar single_touch+gff (wrist braked) → claw → W1 park → W2 → W1 → W3"))
    parts.append("<h2>2 · Zach's wrist order vs park_first from a start where W1's sweep meets the forearm</h2><div class='grid'>")
    parts.append(video("zach_v1_trap", videos, "zach_v1 (wrist_home_v1's order)"))
    parts.append(video("park_first_trap", videos, "park_first + rotor-phase witness"))
    parts.append("</div>")
    parts.append(video("park_first_corner", videos, "park_first from the gripper/forearm corner (W1 125, W2 125)"))
    parts.append("<h2>3 · Criteria: every procedure, every start family</h2>")
    if orders:
        rows = card_rows(orders["summary"])
        parts.append(table(rows, title=f"The proper form: wrist braked during the five-bar, wrist boards at the rack's kp 75 / kd 0.75 — "
                                       f"sim2real {orders['sim2real_sha']}, {orders['seconds'] / 60:.0f} min"))
        parts.append(outcomes(rows))
    if kp15:
        rows = card_rows(kp15["summary"])
        parts.append(table(rows, title=f"The same at the 10:24 gains (kp 15 / kd 0.15) — sim2real {kp15['sim2real_sha']}"))
        parts.append(outcomes(rows))
    if held:
        rows = card_rows(held["summary"])
        parts.append(table(rows, title=f"Wrist HELD during the five-bar (first run, kept as run) — sim2real {held['sim2real_sha']}"))
        parts.append(outcomes(rows))
    parts.append("<h2>4 · Live backlash: identify_backlash, then home() with its table</h2>")
    if backlash:
        parts.append(backlash_section(backlash))
    if backlash_held:
        parts.append("<p class='small'>The wrist-held run of this ladder aborted identify_backlash on both models (W1 flung past the 3 rad/s "
                     "guard during the five-bar's press) — the reason the wrist is braked now.</p>")
    parts.append("<h2>5 · Homing sim-to-real: wrist_home_v1 on the rack vs the twin</h2>")
    if replay:
        parts.append(replay_section(replay["replay"]))
    parts.append(Path(__file__).with_name("fullarm_homing_report_tail.html").read_text() if
                 Path(__file__).with_name("fullarm_homing_report_tail.html").exists() else "")
    parts.append("</body></html>")
    out.write_text("".join(parts))
    return out


def backlash_section(backlash: dict) -> str:
    rows = []
    for kind, entry in backlash["identified"].items():
        gaps = entry.get("gap_error_deg") or {}
        cells = ", ".join(f"{k} {v * 60:+.2f}′" if v is not None else f"{k} —" for k, v in gaps.items())
        rows.append(f"<tr><td>{kind}</td><td>{esc(entry['outcome'][:120])}</td><td>{fmt(entry.get('time_s'), 1)}</td><td>{esc(cells)}</td></tr>")
    out = ("<h3>identify_backlash (park_first order; the five-bar's press_reverse+gff) — identified gap minus hidden gap</h3><div class='scroll'><table>"
           "<tr><th>hidden model</th><th>outcome</th><th>time s</th><th>gap error per joint</th></tr>" + "".join(rows) + "</table></div>")
    out += table(card_rows(backlash["summary"]), title="home() from the same starts, with no table vs with that model's identified table")
    return out


def trace_chart(replay: dict, role: str, joint_index: int) -> str:
    """Real vs twin joint angle for one wrist joint over its own leg (seek, assign, move to 0), each from its seek's first tick."""
    real = replay["real_rows"].get(role)
    sim = replay["sim_trace"]
    starts = [k for k, step in enumerate(sim["step"]) if step == f"{role} seeks"]
    ends = [k for k, step in enumerate(sim["step"]) if step == f"{role} to 0"]
    if not real or not starts or not ends:
        return ""
    k0, k1 = starts[0], ends[-1]
    sim_t = [sim["t"][k] - sim["t"][k0] for k in range(k0, k1 + 1)]
    sim_q = [sim["link_deg"][k][joint_index] for k in range(k0, k1 + 1)]
    real_t, real_q = real["t"], [math.degrees(q) for q in real["q"]]
    t_max = max(max(sim_t), max(real_t))
    q_all = sim_q + real_q
    q_min, q_max = min(q_all) - 10, max(q_all) + 10
    w, h, pad = 520, 220, 36

    def path(ts, qs):
        points = [f"{pad + (w - 2 * pad) * t / t_max:.1f},{h - pad - (h - 2 * pad) * (q - q_min) / (q_max - q_min):.1f}" for t, q in zip(ts, qs)]
        return "M" + " L".join(points)

    zero_y = h - pad - (h - 2 * pad) * (0 - q_min) / (q_max - q_min)
    return (f"<figure><svg viewBox='0 0 {w} {h}' width='100%' style='max-width:{w}px' role='img' aria-label='{role} real vs twin'>"
            f"<rect x='0' y='0' width='{w}' height='{h}' fill='none'/>"
            f"<line x1='{pad}' x2='{w - pad}' y1='{zero_y:.1f}' y2='{zero_y:.1f}' stroke='currentColor' stroke-opacity='.25' stroke-dasharray='3 3'/>"
            f"<path d='{path(real_t, real_q)}' fill='none' stroke='#d0582c' stroke-width='2'/>"
            f"<path d='{path(sim_t, sim_q)}' fill='none' stroke='#2a6fdb' stroke-width='2'/>"
            f"<text x='{pad}' y='16' font-size='12' fill='currentColor'>{role}: <tspan fill='#d0582c'>rack</tspan> vs <tspan fill='#2a6fdb'>twin</tspan> "
            f"joint angle (°), 0 to {t_max:.0f} s from the seek</text>"
            f"<text x='4' y='{zero_y + 4:.1f}' font-size='10' fill='currentColor'>0°</text>"
            f"<text x='4' y='{pad:.0f}' font-size='10' fill='currentColor'>{q_max:.0f}°</text>"
            f"<text x='4' y='{h - pad:.0f}' font-size='10' fill='currentColor'>{q_min:.0f}°</text></svg></figure>")


def replay_section(replay: dict) -> str:
    rows = []
    for role, row in replay["per_joint"].items():
        rows.append(f"<tr><td>{role}</td><td>{fmt(row['real_travel_deg'], 1)}</td><td>{fmt(row['sim_travel_deg'], 1)}</td>"
                    f"<td>{fmt(row['real_stall_nm'], 3)}</td><td>{fmt(row['sim_stall_nm'], 3)}</td>"
                    f"<td>{fmt(row['real_settle_deg'], 1)}</td><td>{fmt(row['sim_settle_deg'], 1)}</td></tr>")
    report = replay["report"]
    return ("<div class='scroll'><table><tr><th>joint</th><th>real seek travel °</th><th>twin seek travel °</th><th>real stall N·m</th>"
            "<th>twin stall N·m</th><th>real rest at “0” °</th><th>twin rest at “0” °</th></tr>" + "".join(rows) + "</table></div>"
            f"<p class='small'>Twin start after power-on settle: {esc(report['start_settled_deg'])}. CAD-guard breach ticks on the twin: "
            f"{report['guard_breach_ticks']} ({esc(', '.join(report['guard_rules']))}); twin contact ticks: {report['self_contact_ticks']}.</p>"
            "<div class='grid'>" + "".join(trace_chart(replay, role, i) for role, i in (("W1", 3), ("W2", 4), ("W3", 5))) + "</div>")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    print(build(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
