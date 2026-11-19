"""W2 must-meet #2 video: the arm's A-to-B speed ladder through the same three dashboards as the pendulum's (round 9) video.

    env -u VIRTUAL_ENV nice -n 10 taskset -c 2-5,16,17 uv run --isolated --project /home/bam/sim2real --extra tracking \
        --with playwright==1.65.2 python /home/bam/sim2real/docs/build_w2_arm_dashboard.py

Zach's W2 must-meet #2 (2026-11-18): "Video of Arm motion, with same dashbaords etc." Three captioned segments, recorded headlessly:
  1. the ladder report (bam_ws reports/media/a2b-speed-ladder-2026-11-18): its Hero tab (the real arm on the OBSBOT), then its Summary;
  2. Rerun at the top rung (11 PPM): target vs friction twin vs real encoders, then the error traces (the .rrd written by the ladder's own
     build_report.py with traj_compare's rerun=True, served here on 127.0.0.1:9894/9895 and stopped at the end);
  3. the W&B project "Real SPPM · A→B ladder" across rungs, rendered from W&B API data (the headless browser is not signed in to Forge,
     and is never signed in on Zach's behalf).

Out: reports/media/w2-arm-dashboard-2026-11-19/ (MP4, GIF, one still per segment) and the page reports/w2-arm-dashboard-2026-11-19.html.
Reuses the pendulum video's recorder (the caption overlay, swiftshader Chromium, per-segment record + marks); the pendulum's own segments
were scratch, so this file is that recorder kept. WHY the captions quote numbers: every number on screen comes from the ladder ledger
(summary.json) or the W&B table read back here, so a caption can never claim more than the dashboards show.

Rerunnable: new rungs (the dwell-and-distance study's real flights) land in the W&B project with bam_ws
a2b_speed_ladder/ladder_wandb.py; run this again and segment 3 and the captions pick them up (the real-rung count and the top real rung
are read, not typed).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATE = "2026-11-19"
SLUG = f"w2-arm-dashboard-{DATE}"
MEDIA = REPO / "reports" / "media" / SLUG
PAGE = REPO / "reports" / f"{SLUG}.html"
WORK = Path.home() / ".cache" / "sim2real" / SLUG
LADDER = Path("/home/bam/bam_ws/reports/media/a2b-speed-ladder-2026-11-18")
RRD = Path("/home/bam/bam_ws/reports/media/a2b-ladder-rerun-2026-11-18/rerun/a2b_top.rrd")
RERUN = Path("/home/bam/bam_ws/src/core/mdp/agent/actor/trajectory_generation/traj_compare/.venv/bin/rerun")  # rerun-sdk 0.40.0 = the .rrd's SDK
WEB_PORT, GRPC_PORT = 9894, 9895
ENTITY, PROJECT = "zach-yamaoka-independent", "Real SPPM · A→B ladder"
SUMMARY_RUN = "a2b-ladder-summary"
CHROME = "/home/bam/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome"
VW, VH = 1440, 810
TOOL_GATE_MM = 1.0
CPUS = "2-5,16,17"  # WHY: the full arm may be powered; this host keeps CPUs 22-23 for it (memory rig-host-while-powered)

CAP_JS = """(t)=>{let d=document.getElementById('__cap');if(!d){d=document.createElement('div');d.id='__cap';
d.style.cssText='position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:2147483647;background:rgba(15,17,20,.88);color:#fff;font:600 22px/1.3 system-ui,sans-serif;padding:10px 20px;border-radius:10px;max-width:1300px;text-align:center;pointer-events:none;box-shadow:0 4px 18px rgba(0,0,0,.35)';
document.documentElement.appendChild(d);} d.innerHTML=t;}"""


# ---------------------------------------------------------------------------------------------------------------- data


def ladder_rows() -> list[dict]:
    return json.loads((LADDER / "summary.json").read_text())


def wandb_table() -> tuple[list[dict], str]:
    """The summary run's `ladder` table, read back through the API (what W&B holds, not the local file)."""
    import wandb  # noqa: PLC0415

    api = wandb.Api(timeout=60)
    run = api.run(f"{ENTITY}/{PROJECT}/{SUMMARY_RUN}")
    path = dict(run.summary["ladder"])["path"]
    local = run.file(path).download(root=str(WORK / "wandb"), replace=True).name
    doc = json.loads(Path(local).read_text())
    return [dict(zip(doc["columns"], row)) for row in doc["data"]], run.url


def f2(v) -> str:
    return "—" if v is None else f"{v:.2f}"


def wb_page(rows: list[dict], url: str, out: Path) -> dict:
    """Segment 3's page: the W&B summary run's numbers drawn as its panels would (tiles, two charts across rungs, the table)."""
    real = [r for r in rows if r["side"] == "real"]
    twin = [r for r in rows if r["side"] == "twin"]
    top = max(real, key=lambda r: r["ab_speed_mm_s"])
    passed = [r for r in real if r["gate_1mm"] == "pass"]
    pending = [r for r in twin if r["rung"] not in {x["rung"] for x in real}]

    W, H, L, T, R, B = 640, 300, 60, 24, 20, 44
    xmax = max(r["ab_speed_mm_s"] for r in rows) * 1.08

    def chart(key: str, title: str, ymax: float, gate: float | None, steps: int = 5) -> str:
        x = lambda v: L + v / xmax * (W - L - R)  # noqa: E731
        y = lambda v: T + (1 - v / ymax) * (H - T - B)  # noqa: E731
        s = [f'<svg viewBox="0 0 {W} {H}" width="100%">']
        for i in range(steps + 1):
            v = ymax * i / steps
            s.append(f'<line x1="{L}" x2="{W-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#ececec"/>'
                     f'<text x="{L-8}" y="{y(v)+4:.1f}" text-anchor="end" font-size="12" fill="#666">{v:.1f}</text>')
        for v in range(0, int(xmax) + 1, 20):
            s.append(f'<text x="{x(v):.1f}" y="{H-24}" text-anchor="middle" font-size="12" fill="#666">{v}</text>')
        s.append(f'<text x="{(L+W-R)/2}" y="{H-6}" text-anchor="middle" font-size="12" fill="#666">A→B speed (mm/s)</text>')
        if gate is not None:
            s.append(f'<line x1="{L}" x2="{W-R}" y1="{y(gate):.1f}" y2="{y(gate):.1f}" stroke="#c62828" stroke-dasharray="6 5" stroke-width="1.5"/>'
                     f'<text x="{L+6}" y="{y(gate)-6:.1f}" text-anchor="start" font-size="12" fill="#c62828">1 mm gate</text>')
        for side, color, shape in (("twin", "#1e6fd9", "circle"), ("real", "#ef6c00", "rect")):
            pts = sorted((r for r in rows if r["side"] == side and r.get(key) is not None), key=lambda r: r["ab_speed_mm_s"])
            ladder_pts = [r for r in pts if not r["rung"].startswith("a2b_short") and "nocap" not in r["rung"]]
            if len(ladder_pts) > 1:
                s.append('<polyline points="' + " ".join(f'{x(r["ab_speed_mm_s"]):.1f},{y(min(r[key], ymax)):.1f}' for r in ladder_pts)
                         + f'" fill="none" stroke="{color}" stroke-width="2.5"/>')
            for r in sorted(pts, key=lambda r: r in ladder_pts):  # study (hollow) first, so a ladder point is never hidden
                cx, cy = x(r["ab_speed_mm_s"]), y(min(r[key], ymax))
                hollow = r not in ladder_pts
                fill = "#fff" if hollow else color
                if shape == "circle":
                    s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{fill}" stroke="{color}" stroke-width="2"/>')
                else:
                    s.append(f'<rect x="{cx-6:.1f}" y="{cy-6:.1f}" width="12" height="12" fill="{fill}" stroke="{color}" stroke-width="2"/>')
                if side == "real":
                    s.append(f'<text x="{cx:.1f}" y="{cy-11:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="{color}">{r[key]:.2f}</text>')
        s.append("</svg>")
        return f'<div class="panel half"><div class="t">{title}</div>{"".join(s)}</div>'

    def tile(v: str, label: str) -> str:
        return f'<div class="tile"><div class="v">{v}</div><div class="l">{label}</div></div>'

    cols = [("rung", "rung"), ("side", "side"), ("ppm", "PPM"), ("ab_speed_mm_s", "A→B mm/s"), ("peak_of_rule", "peak / rule"),
            ("j2_rms_deg", "J2 RMS °"), ("c1_rms_deg", "C1 RMS °"), ("claw_path_rms_max_mm", "claw path RMS mm"),
            ("settled_max_mm", "settled max mm"), ("gate_max_mm", "1 mm gate max"), ("gate_1mm", "gate"), ("rerun", "rerun")]

    def cell(r: dict, k: str) -> str:
        v = r.get(k)
        if k == "rerun":
            return f'<td class="link">{"/f/…/" + v.rsplit("/", 1)[-1] if str(v).startswith("http") else v}</td>'
        if k == "gate_1mm":
            return f'<td class="{v}">{v}</td>'
        if isinstance(v, float):
            return f"<td>{v:.2f}</td>" if k != "ppm" else f"<td>{v:g}</td>"
        return f"<td>{v}</td>"

    head = "".join(f"<th>{t}</th>" for _, t in cols)
    body = "".join(f'<tr class="{"real" if r["side"] == "real" else ""}">' + "".join(cell(r, k) for k, _ in cols) + "</tr>" for r in rows)
    html = f'''<!doctype html><meta charset="utf-8"><title>W&B data</title><style>
body{{margin:0;font:15px/1.4 "Source Sans Pro",system-ui,sans-serif;background:#fafafa;color:#1a1a1a}}
.top{{background:#1a1c1f;color:#fff;padding:12px 28px}} .top b{{color:#ffbe00;margin-right:14px}} .wrap{{padding:16px 28px 130px}}
.note{{background:#fff4d6;border:1px solid #ffbe00;padding:8px 12px;border-radius:6px;font-size:14px;margin-bottom:10px}}
h2{{font-size:20px;margin:12px 0 8px}} .tiles{{display:flex;gap:14px}}
.tile{{flex:1;background:#fff;border:1px solid #e3e3e3;border-radius:6px;padding:10px 16px}} .tile .v{{font-size:28px;font-weight:700}} .tile .l{{color:#666;font-size:13px}}
.row{{display:flex;gap:14px}} .panel{{background:#fff;border:1px solid #e3e3e3;border-radius:6px;padding:10px 14px;margin-top:12px}} .half{{flex:1}}
.panel .t{{font-weight:600;margin-bottom:4px}} .legend{{font-size:13px;color:#666;margin-top:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #eee;padding:4px 7px;text-align:right}} th{{color:#555;font-weight:600}}
td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){{text-align:left}} tr.real td{{background:#fff7ef}}
td.pass{{color:#2e7d32;font-weight:700}} td.fail{{color:#c62828;font-weight:700}} td.link{{color:#1e6fd9;font-family:ui-monospace,monospace;font-size:12px}}
</style>
<div class="top"><b>W&amp;B</b>{ENTITY} / {PROJECT} / run: A→B ladder · real vs twin across rungs</div>
<div class="wrap">
<div class="note">Rendered from W&amp;B API data (headless browser not signed in): run <code>{SUMMARY_RUN}</code>, table <code>ladder</code> ({len(rows)} rows: {len(real)} real, {len(twin)} twin), read via wandb.Api.</div>
<h2>Top real rung · {top["label"]}</h2>
<div class="tiles">{tile(f'{top["ab_speed_mm_s"]:.1f} mm/s', "A→B speed")}{tile(f'{top["j2_rms_deg"]:.2f}° / {top["c1_rms_deg"]:.2f}°', "J2 / C1 tracking RMS")}{tile(f'{top["gate_max_mm"]:.2f} mm', "1 mm gate, worst set-leg stop")}{tile(f'{top["peak_of_rule"]:.3f}', "peak speed / 68.75 °/s rule")}{tile(f'{len(passed)} / {len(real)}', "real rungs passing the 1 mm gate")}</div>
<h2>Summary across rungs</h2>
<div class="row">{chart("gate_max_mm", "1 mm gate: worst set-leg stop (mm)", 2.0, TOOL_GATE_MM)}{chart("j2_rms_deg", "J2 tracking RMS (°)", 1.2, None, steps=6)}</div>
<div class="legend">■ real (orange) · ● friction twin (blue) · hollow = dwell-and-distance study variant (twin only until it flies: {", ".join(r["rung"] for r in pending) or "none"})</div>
<div class="panel"><div class="t">ladder (one row per rung and side; <code>rerun</code> = the 127.0.0.1:8771 launcher link)</div><table><tr>{head}</tr>{body}</table></div>
</div>'''
    out.write_text(html)
    return {"top": top, "real": len(real), "passed": len(passed), "pending": [r["rung"] for r in pending], "url": url}


# ---------------------------------------------------------------------------------------------------------------- recording


def start_rerun() -> subprocess.Popen:
    log = open(WORK / "rerun.log", "w")
    proc = subprocess.Popen(["taskset", "-c", CPUS, "nice", "-n", "10", str(RERUN), "--serve-web", "--bind", "127.0.0.1",
                             "--web-viewer-port", str(WEB_PORT), "--port", str(GRPC_PORT), str(RRD)],
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (WORK / "rerun.pid").write_text(str(proc.pid))
    return proc


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)


def record(seg: str, captions: dict[str, list[str]]) -> dict:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    marks: dict[str, float] = {}
    shots = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=CHROME,
                              args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars",
                                    "--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": VW, "height": VH}, record_video_dir=str(WORK / f"vid_{seg}"),
                            record_video_size={"width": VW, "height": VH})
        pg = ctx.new_page()
        t0 = time.time()

        def mark(k: str) -> None:
            marks[k] = round(time.time() - t0, 2)

        def cap(t: str) -> None:
            pg.evaluate(CAP_JS, t)

        def shot(name: str) -> None:
            path = WORK / f"chk_{name}.png"
            pg.screenshot(path=str(path))
            shots.append(str(path))

        c = captions[seg]
        if seg == "s1":
            pg.goto((LADDER / "index.html").as_uri())
            pg.wait_for_timeout(5000)
            # the Hero tab opens first; bring its OBSBOT video up and play it (muted)
            pg.evaluate("""()=>{const v=document.querySelector('video'); v.muted=true; v.scrollIntoView({block:'center'}); v.currentTime=0; v.play();}""")
            pg.wait_for_timeout(1200)
            cap(c[0])
            mark("start")
            pg.wait_for_timeout(9000)
            shot("s1a")
            pg.evaluate("""()=>window.scrollTo(0,0)""")
            pg.get_by_role("button", name="Summary", exact=True).first.click()
            pg.wait_for_timeout(1200)
            cap(c[1])
            pg.wait_for_timeout(4500)
            shot("s1b")
            pg.mouse.move(720, 500)
            pg.mouse.wheel(0, 520)
            pg.wait_for_timeout(4500)
            shot("s1c")
            mark("end")
        elif seg == "s2":
            pg.goto(f"http://127.0.0.1:{WEB_PORT}/?url=" + urllib.parse.quote(f"rerun+http://127.0.0.1:{GRPC_PORT}/proxy", safe=""))
            pg.wait_for_timeout(16000)
            pg.mouse.click(1033, 50)  # the "Signals" tab: Position, target vs twin vs real
            pg.wait_for_timeout(800)
            # WHY no Space: the viewer opens already in play mode, stopped at the end; a seek to the start resumes it (Space paused it)
            pg.mouse.click(250, 796)  # the timeline's start
            pg.wait_for_timeout(400)
            cap(c[0])
            mark("start")
            pg.wait_for_timeout(8000)
            shot("s2a")
            pg.mouse.click(626, 50)  # "Is it good?": the scorecard and the error traces
            pg.wait_for_timeout(500)
            cap(c[1])
            pg.wait_for_timeout(8000)
            shot("s2b")
            mark("end")
        elif seg == "s3":
            pg.goto((WORK / "wb.html").as_uri())
            pg.wait_for_timeout(1500)
            cap(c[0])
            mark("start")
            pg.wait_for_timeout(5500)
            shot("s3a")
            cap(c[1])
            pg.mouse.move(720, 400)
            pg.mouse.wheel(0, 600)
            pg.wait_for_timeout(6000)
            shot("s3b")
            mark("end")
        ctx.close()
        b.close()
    webm = sorted((WORK / f"vid_{seg}").glob("*.webm"), key=lambda q: q.stat().st_mtime)[-1]
    return {"seg": seg, "webm": str(webm), "marks": marks, "shots": shots}


def ffmpeg(*args: str) -> None:
    subprocess.run(["taskset", "-c", CPUS, "nice", "-n", "10", "ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def assemble(segments: list[dict]) -> dict:
    MEDIA.mkdir(parents=True, exist_ok=True)
    parts = []
    for s in segments:
        a, b = s["marks"]["start"], s["marks"]["end"]
        part = WORK / f"seg_{s['seg']}.mp4"
        ffmpeg("-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-i", s["webm"], "-vf", "scale=1280:-2,fps=24", "-an", "-c:v", "libx264",
               "-preset", "medium", "-crf", "30", "-pix_fmt", "yuv420p", "-threads", "2", str(part))
        parts.append(part)
    (WORK / "list.txt").write_text("".join(f"file '{q}'\n" for q in parts))
    mp4 = MEDIA / "w2-arm-dashboard.mp4"
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(WORK / "list.txt"), "-c", "copy", "-movflags", "+faststart", str(mp4))
    gif = MEDIA / "w2-arm-dashboard.gif"
    palette = WORK / "palette.png"
    ffmpeg("-i", str(mp4), "-vf", "fps=6,scale=800:-1:flags=lanczos,palettegen=max_colors=96", "-threads", "2", str(palette))
    ffmpeg("-i", str(mp4), "-i", str(palette), "-lavfi", "fps=6,scale=800:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
           "-threads", "2", str(gif))
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                                    capture_output=True, text=True, check=True).stdout)
    for old in MEDIA.glob("still-*.png"):  # a re-record moves the segment boundaries; never leave a stale still beside the new ones
        old.unlink()
    stills = []
    t = 0.0
    for s, part in zip(segments, parts):
        length = s["marks"]["end"] - s["marks"]["start"]
        for frac in (0.4, 0.85):
            at = int(t + frac * length)
            still = MEDIA / f"still-{at}.png"
            ffmpeg("-ss", str(at), "-i", str(mp4), "-frames:v", "1", str(still))
            stills.append(still)
        t += length
    return {"mp4": mp4, "gif": gif, "duration": duration, "stills": stills}


def write_page(out: dict, info: dict, captions: dict[str, list[str]]) -> None:
    rel = f"media/{SLUG}"
    poster = out["stills"][0].name
    top = info["top"]
    PAGE.write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>W2 Arm Dashboard</title>
<style>
:root{{--bg:#fafafa;--fg:#1a1a1a;--muted:#666}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141517;--fg:#eee;--muted:#aaa}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1280px;margin:0 auto;padding:20px 16px}}
h1{{font-size:22px;margin:0 0 6px}} p{{margin:4px 0 14px;color:var(--muted)}}
video,img{{width:100%;height:auto;border-radius:8px;display:block}}
ol{{color:var(--muted);font-size:15px}}
</style></head><body><main>
<h1>W2 must-meet #2 · arm dashboards (A→B speed ladder, bam_fb_v2)</h1>
<p>{out["duration"]:.0f} s, recorded headlessly on {time.strftime("%Y-%m-%d")}. Three captioned segments:</p>
<ol>
<li>The A-to-B speed ladder report: Hero (the real arm on the OBSBOT, 5 → 10 → 11 PPM, all complete, no trip), then Summary (real beside twin per rung; the 1 mm gate on the set-leg stops).</li>
<li>Rerun at the top rung (11 PPM): J2 / C1 position, target vs friction twin vs real encoders, then the scorecard and the error traces vs the commanded profile.</li>
<li>W&amp;B "{PROJECT}" across rungs, rendered from W&amp;B API data (run <code>{SUMMARY_RUN}</code>; the headless browser was not signed in to Forge): {info["real"]} real rungs, {info["passed"]} passing the 1 mm gate; top real rung {top["label"]} at {top["ab_speed_mm_s"]:.1f} mm/s, gate {top["gate_max_mm"]:.2f} mm.{(" Twin only until they fly: " + ", ".join(info["pending"]) + ".") if info["pending"] else ""}</li>
</ol>
<video autoplay muted loop playsinline controls poster="{rel}/{poster}">
<source src="{rel}/{out["mp4"].name}" type="video/mp4">
<img src="{rel}/{out["gif"].name}" alt="Arm dashboards walkthrough (GIF fallback)">
</video>
<p><a href="{rel}/{out["gif"].name}">GIF fallback</a> · W&amp;B project: <a href="{info["project_url"]}">{PROJECT}</a> · ladder report: <code>{LADDER}/index.html</code></p>
</main></body></html>
''')


def captions_for(rows: list[dict], info: dict) -> dict[str, list[str]]:
    by = {r["rung"]: r for r in rows}
    top = by["a2b_top"]["real"]
    twin = by["a2b_top"]["twin"]
    flown = [r for r in rows if r.get("real")]
    fails = [r for r in flown if (r["real"].get("gate_max_mm") or 9) > TOOL_GATE_MM]
    g = top["gate_readings_mm"]
    fail_text = "; ".join(f'{r["label"].split(" ·")[0]} misses it ({r["real"]["gate_max_mm"]:.2f} mm)' for r in fails)
    return {
        "s1": [f"1 / 3 · A→B speed ladder report · Hero — the real bam_fb_v2 arm on the OBSBOT, rung by rung: "
               f"{' → '.join(r['label'].split(' ·')[0].replace('top (11.0 PPM)', '11 PPM') for r in flown)}, all complete, no trip",
               f"Summary — real beside twin per rung. 11 PPM: J2 / C1 RMS {top['rms_deg'][0]:.2f}° / {top['rms_deg'][1]:.2f}°, "
               f"1 mm gate (set-leg stops) {g['a4']:.2f} / {g['b4']:.2f} / {g['ready_end']:.2f} mm" + (f"; {fail_text}" if fail_text else "")],
        "s2": ["2 / 3 · Rerun · top rung (11 PPM) — J2 and C1 position: target (black) vs friction twin (blue) vs real encoders (orange)",
               f"Error vs the commanded profile: worst joint {top['peak_deg'][0]:.2f}° real / {twin['peak_deg'][0]:.2f}° twin; "
               "claw-mount position error while moving, real and twin overlaid"],
        "s3": [f"3 / 3 · W&amp;B · {PROJECT} — rendered from W&amp;B API data (headless browser not signed in)",
               f"Across rungs: {info['passed']} of {info['real']} real rungs pass the 1 mm gate"
               + (f"; {len(info['pending'])} study variants are twin-only until they fly" if info["pending"] else "")],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--segments", default="s1,s2,s3", help="record only these (the rest reuse their last recording)")
    args = parser.parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    rows, url = wandb_table()
    info = wb_page(rows, url, WORK / "wb.html")
    info["project_url"] = f"https://forge.coreweave.com/wandb/{ENTITY}/{urllib.parse.quote(PROJECT)}"
    captions = captions_for(ladder_rows(), info)
    state = WORK / "segments.json"
    segments = {s["seg"]: s for s in json.loads(state.read_text())} if state.exists() else {}
    proc = start_rerun() if "s2" in args.segments else None
    try:
        for seg in args.segments.split(","):
            segments[seg] = record(seg, captions)
            print(json.dumps(segments[seg]))
    finally:
        if proc:
            stop(proc)
    state.write_text(json.dumps(list(segments.values()), indent=1))
    out = assemble([segments[s] for s in ("s1", "s2", "s3")])
    write_page(out, info, captions)
    sizes = {q.name: q.stat().st_size for q in (out["mp4"], out["gif"])}
    print(json.dumps({"page": str(PAGE), "duration_s": round(out["duration"], 1), "sizes": sizes,
                      "stills": [str(q) for q in out["stills"]], "checks": [x for s in segments.values() for x in s["shots"]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
