#!/usr/bin/env python3
"""The Deployments workbench's review report: reports/deployment-page-2026-11-17.html, from the RUNNING app.

    env -u VIRTUAL_ENV taskset -c 2-5,16,17 uv run --isolated --no-project --with playwright python /home/bam/sim2real/docs/build_report_deployments_workbench.py --stills /abs/capture/dir --acceptance /abs/acceptance.log --pytest /abs/pytest.log

Serves the built site (site/build.py's OUT, --out) on a free port in 4711-4799 (or uses --base), records the hero clip from the real page
in headless Chromium (the Obsidian frame's three views with CAN 11 selected: Scene -> Sheet -> Workbench -> Runs, each switched from the
ribbon), copies the acceptance run's stills (site/tests/test_deployments_workbench.py --record DIR), and writes the page. Media go to
reports/media/deployment-page-2026-11-17/ (gitignored); the page is text and links to them. Nothing is opened.
"""

from __future__ import annotations

import argparse
import contextlib
import html
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SLUG = "deployment-page-2026-11-17"
REPORT = ROOT / "reports" / f"{SLUG}.html"
MEDIA = ROOT / "reports" / "media" / SLUG
DEFAULT_OUT = Path.home() / ".cache" / "sim2real" / "site"
EXE = str(max(Path.home().glob(".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
              key=lambda p: int(p.parts[-3].rsplit("-", 1)[1])))
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
FRAME_STILLS = [
    ("s11-ribbon-tooltip", "The ribbon at the far left (Obsidian's 44 px strip): Deployments; Scene · Sheet · Workbench; Runs. Tooltips to the right"),
    ("s12-scene-can11", "Scene: the 3D is the page; every station wears its performance in place; CAN 11 clicked in 3D, the inspector performance first"),
    ("s13-sheet", "Sheet: CAN 11 and round 0 carried over; every performance metric round 0 · now · change, fidelity beside it; 3D and inspector docked"),
    ("s14-scene-servo", "Scene: CAN 11's servo pulled apart, each part named in place; motor and gearbox not observable on this rack"),
    ("s15-runs-selected", "Runs: the tree's pick filters the runs to its station; every run one click from its Rerun recording"),
]
STILLS = [
    ("s01-deployments", "Deployments: every deployment; the rack leads with performance (67 of 72 real gates, 28 as found)"),
    ("s02-rack-performance", "The rack: performance first, the top gap (tracking at full speed), CAN 11's worst stops, fidelity under it"),
    ("s03-rack-round-by-round", "Round by round with the goal line drawn, and every station × every speed rung"),
    ("s04-can11", "CAN 11 in the typed tree: tracks to 1.0 of top speed; its twin 2.14× its floor (4.27× as found)"),
    ("s05-can11-metrics", "CAN 11's Metrics tab: performance and fidelity as two groups, round 0 · now · change"),
    ("s06-table-performance", "The Sheet (RobotDx's nested table): performance as round 0 · now · change, the 3D and inspector docked"),
    ("s07-table-questions", "The Sheet's optional column group, the five questions: Floor → Data → Routines → Twin → Job"),
    ("s08-table-what-changed", "What changed: every cell round 0 → round 8; rows that did not move are dimmed"),
    ("s09-servo-parts", "The servo: driver, motor, gearbox, encoder under it, pulled apart in 3D; motor and gearbox not observable here"),
    ("s10-runs", "Runs: round 8's 252 runs, the summary on top, each with its Rerun recording"),
]


def free_port(lo: int = 4711, hi: int = 4799) -> int:
    for port in range(lo, hi + 1):
        with contextlib.closing(socket.socket()) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("no free port in 4711-4799")


@contextlib.contextmanager
def serve(out: Path):
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.8)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def record_hero(base: str) -> Path:
    """About 14 s of the real page: CAN 11 picked in the Scene, then the ribbon's Sheet, Workbench and Runs, the selection carried."""
    tmp = Path(tempfile.mkdtemp(prefix="dw-hero-"))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EXE, args=ARGS)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", record_video_dir=str(tmp),
                                  record_video_size={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(base + "/deployments/?d=one-dof-test-rack&view=scene")
        page.evaluate("Object.keys(localStorage).filter((k) => k.startsWith('s2r.deployments-workbench.')).forEach((k) => localStorage.removeItem(k))")
        page.reload()
        page.wait_for_function("document.getElementById('dw').dataset.ready === '1'")
        page.wait_for_timeout(1600)
        pt = page.evaluate("window.__dwRack.screenOf('can11')")
        page.mouse.move(pt["x"], pt["y"] + 2, steps=10)
        page.mouse.click(pt["x"], pt["y"] + 2)
        page.wait_for_timeout(2400)
        for view, dwell in (("sheet", 2400), ("page", 2400), ("runs", 1300)):
            page.hover(f'.dw-rb[data-v="{view}"]')
            page.wait_for_timeout(700)
            page.click(f'.dw-rb[data-v="{view}"]')
            page.mouse.move(700, 600)
            page.wait_for_timeout(dwell)
        page.click('.dw-rfilters button[data-st="can11"]')
        page.wait_for_timeout(1700)
        video = page.video.path()
        ctx.close()
        browser.close()
    return Path(video)


def encode(webm: Path) -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(webm), "-an", "-vf", "fps=24,scale=1440:-2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "27", "-movflags", "+faststart", str(MEDIA / "hero.mp4")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(webm), "-vf",
                    "fps=5,scale=800:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=bayer", str(MEDIA / "hero.gif")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "3.5", "-i", str(MEDIA / "hero.mp4"), "-frames:v", "1", "-q:v", "4", str(MEDIA / "poster.jpg")], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def lines(path: Path | None, keep) -> list[str]:
    if not path or not path.is_file():
        return []
    return [ln.rstrip() for ln in path.read_text(errors="replace").splitlines() if keep(ln)]


def figures(items) -> str:
    e = html.escape
    return "".join(f'<figure><a href="media/{SLUG}/{name}.png"><img src="media/{SLUG}/{name}.png" alt="{e(cap)}" loading="lazy"></a><figcaption>{e(cap)}</figcaption></figure>'
                   for name, cap in items if (MEDIA / f"{name}.png").is_file())


def page(acceptance: list[str], pytest_lines: list[str], hero_s: float, commit: str) -> str:
    e = html.escape
    stills, frame = figures(STILLS), figures(FRAME_STILLS)
    acc = "".join(f'<li class="{"ok" if ln.startswith("PASS") else "bad"}">{e(ln)}</li>' for ln in acceptance)
    py = "<br>".join(e(ln) for ln in pytest_lines)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deployments workbench</title>
<style>
:root {{ --bg:#fff; --bg2:#f4f4f5; --ink:#1f2328; --ink2:#555; --ink3:#6b6e76; --rule:#d4d4d8; --pass:#1d7a3a; --fail:#b42318; --warn:#a15c07; --real:#2a78d6; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0b0c0e; --bg2:#141519; --ink:#f2f3f5; --ink2:#b0b3ba; --ink3:#8a8d96; --rule:#2a2c31; --pass:#4cc06e; --fail:#f2685c; --warn:#f0a548; --real:#3987e5; }} }}
:root[data-theme="dark"] {{ --bg:#0b0c0e; --bg2:#141519; --ink:#f2f3f5; --ink2:#b0b3ba; --ink3:#8a8d96; --rule:#2a2c31; --pass:#4cc06e; --fail:#f2685c; --warn:#f0a548; --real:#3987e5; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 60px; }}
h1 {{ font-size:26px; margin:0 0 6px; }} h2 {{ font-size:19px; margin:34px 0 8px; border-top:1px solid var(--rule); padding-top:18px; }}
.verdict {{ font-size:17px; font-weight:650; margin:6px 0 14px; }} .muted {{ color:var(--ink3); }}
video, .hero img {{ width:100%; border-radius:10px; border:1px solid var(--rule); background:#000; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:14px; }}
figure {{ margin:0; }} figure img {{ width:100%; border-radius:8px; border:1px solid var(--rule); display:block; }}
figcaption {{ font-size:13px; color:var(--ink2); margin-top:4px; }}
code {{ font:13px ui-monospace,Menlo,Consolas,monospace; background:var(--bg2); padding:1px 5px; border-radius:4px; overflow-wrap:anywhere; }}
ul.acc {{ list-style:none; padding:0; font:12.5px/1.45 ui-monospace,Menlo,Consolas,monospace; }} ul.acc li.ok::first-letter {{ color:var(--pass); }} ul.acc li.bad {{ color:var(--fail); }}
.box {{ background:var(--bg2); border:1px solid var(--rule); border-radius:10px; padding:10px 14px; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }} th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--rule); vertical-align:top; }}
@media (max-width:600px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style></head><body><main>
<h1>Deployments workbench</h1>
<p class="verdict">sim2real's /deployments/ now has Obsidian's left ribbon and three primary views, Scene · Sheet · Workbench, sharing one selection and one round, with Runs one icon below — verified in the running app ({len([a for a in acceptance if a.startswith("PASS")])} of {len(acceptance)} acceptance checks pass), on sim2real main {e(commit)}.</p>
<p class="muted">2026-11-17 · Zach's ask, on proposal V1: "update it so it has the left toolbar sidebar like Obsidian. And then I think 3 primary views could be the Scene View, the Sheet view and the Workbench-like view." Built on the morning's workbench (Daily Note Nov 17, "# What is required for me to actually get this working?" and "# Ok": performance first and up centre; runs are the atomic unit), whose write-up follows below the new part.</p>

<div class="hero"><video src="media/{SLUG}/hero.mp4" poster="media/{SLUG}/poster.jpg" autoplay muted loop playsinline controls>
<img src="media/{SLUG}/hero.gif" alt="the click-through"></video></div>
<p class="muted">{hero_s:.0f} s, recorded from the running app in headless Chromium: the Scene, CAN 11 clicked in 3D → the ribbon's Sheet (CAN 11 still selected, its row and the docked inspector) → Workbench (CAN 11's page) → Runs (CAN 11 still selected in the tree; one click shows only its runs). Each ribbon icon's tooltip shows before it is clicked. <a href="media/{SLUG}/hero.gif">GIF</a>.</p>

<h2>The Obsidian frame and the three views (new)</h2>
<ul>
<li><b>The ribbon</b>, matched to Obsidian's geometry (read from like_obsidian_md_viewer's captured <code>obsidian-app.css</code>, never from your running Obsidian): a 44 px strip at the far left; its 40 px header cell holds the sidebar toggle, Obsidian's own icon (the filled bar widens when the sidebar is open); 18 px icons at a 1.75 stroke in 30 × 26 buttons, 4 px apart; the active view on the hover fill, as Obsidian marks its active sidebar tab; tooltips to the right with an arrow. Order: <b>Deployments</b>; <b>Scene · Sheet · Workbench</b>; then <b>Runs</b> in a group of its own. Nothing Obsidian has that we cannot back (settings, help, vault switcher) is drawn.</li>
<li><b>The left sidebar</b> holds the typed component tree in every deployment view. The toggle collapses it and the view takes the room; collapsed or open and its width (drag the edge, double-click resets) are remembered across reloads. On the Deployments list there is no tree, so no sidebar and no toggle.</li>
<li><b>The right inspector</b> (Scene, Sheet) folds from the bar's toggle at the far right (Obsidian's place for the right sidebar's toggle) or Esc; its edge drags. It leads with the picked node's performance, then fidelity, then its parts, every metric round 0 → now, the five questions.</li>
<li><b>Scene</b> (V3): the 3D is the page. Each station's label wears its performance in place (how far up the speed ladder it does its job, its ring coloured by it) and, when it misses, its twin in red; labels never cover each other, a joint, the chips or the ViewCube. A click on a station or a part selects it; a servo pulls apart into driver, motor, gearbox and encoder, each named in place (motor and gearbox: "not observable on this rack"). A time bar moves between round 0 and now.</li>
<li><b>Sheet</b> (V2): the nested table is the page. Performance first, every metric as round 0 · now · change side by side (highest rung tracked, tracking RMS and peak at 0.9, tip stop median, worst stop), fidelity (twin ÷ floor) beside it; the five questions are an optional column group (+ Five questions); What changed dims the rows that did not move. The 3D (only the picked station labelled) and the inspector are docked on the right.</li>
<li><b>Workbench</b> (V1): this morning's tree and node page, unchanged inside.</li>
<li><b>One selection, one round:</b> both live in the URL (<code>n</code>, <code>round</code>), so CAN 11 picked in the Scene is CAN 11 in the Sheet, the Workbench and the tree in Runs, and round 0 stays round 0. <b>Runs</b> sits in the ribbon's second group: reachable from every view; a tree pick there filters the runs to that station, and "Only CAN 11's runs (selected)" does it in one click when you arrive with a selection.</li>
</ul>
<div class="grid">{frame}</div>

<h2>What you get (this morning's workbench, kept)</h2>
<ul>
<li><b>Performance leads every page.</b> The rack: all six stations track and stop within the gates up to 0.9 of top speed; 67 of 72 real performance gates (28 as found). The top gap: at full speed, tracking misses on CAN 1, 12, 13, 14, 15 (0.59–1.22° RMS against 0.5°). CAN 11's worst stop is over 1 mm at the 0.4, 0.9 and 1.0 rungs although the median passes. Fidelity sits under it: CAN 11's twin is 2.14× its floor (4.27× as found), the campaign goal's one miss.</li>
<li><b>The goal line drawn:</b> round-by-round charts (rounds 0–8, each station at 0.9 of top speed, "GOOD ≤ 0.5°" and "GOOD ≤ 1 mm"), the speed-ladder plots per station (round 0 dashed under now), and every station × every speed rung.</li>
<li><b>Typed component tree</b> on the left (search, keyboard, collapse; RobotDx's dots), the node's page on the right with tabs: Performance · Metrics (performance, fidelity and evidence as separate groups; round 0 · now · change) · Runs · Five questions · Where it is defined.</li>
<li><b>Table view</b>, now the <b>Sheet</b> (RobotDx's nested table): performance round 0 · now · change, the five question columns as an optional group; Now · As found · What changed; a foldable, resizable inspector whose metric column no longer wraps word by word.</li>
<li><b>Runs view:</b> every play of every scored round (rounds 0–8, 2,233 rows), round 8 by default, a summary on top, filters and sorting; each run's "Open in Rerun" goes through the always-on bam-replay-link launcher on 127.0.0.1:8771 (no more dead 9461/9462 links); a run with no .rrd says "no recording yet". The same table is written as JSON for a later W&amp;B sync.</li>
<li><b>3D</b> (schematic, labelled "schematic geometry · simulated"; "CAD render" shows the rack's MuJoCo render): a click selects the station, the servo pulls apart into motor, gearbox, encoder and driver.</li>
</ul>

<h2>Screens from the running app</h2>
<div class="grid">{stills}</div>

<h2>Proof</h2>
<div class="box"><b>Acceptance in the running app</b> (<code>site/tests/test_deployments_workbench.py</code>, headless Chromium on the built site):<ul class="acc">{acc}</ul></div>
<div class="box" style="margin-top:12px"><b>Tests</b><br><span style="font:12.5px ui-monospace,Menlo,monospace">{py}</span></div>

<h2>Where it lives</h2>
<table>
<tr><th>file</th><th>what</th></tr>
<tr><td><code>src/sim2real/verdicts.py</code></td><td>the five questions, once: a parent passes only at its own output and with every child that gates it (MOC decision 1: the servo shown, not gating, under a station)</td></tr>
<tr><td><code>src/sim2real/deployments_page.py</code></td><td>the scorecards (read-only) → the typed tree, every metric per round tagged performance / fidelity / evidence, round-by-round history, every run with its .rrd; re-scores the five cell gates and holds them to the scorecards' 82 and 151</td></tr>
<tr><td><code>tests/test_deployments_page.py</code></td><td>written red first: 82 → 151, 28 → 67 of 72, CAN 11 2.14× (4.27×), the tree, the families, the runs, the rule on a synthetic tree</td></tr>
<tr><td><code>site/deployments_workbench.py</code>, <code>site/static/deployments-workbench.{{js,css}}</code></td><td>the page at /deployments/, its data (<code>data/deployments-workbench.json</code>) and the runs table (<code>data/deployments-workbench-runs.json</code>), the replay links registered with data_recorder.runlink</td></tr>
<tr><td><code>site/deployments_pages.py</code></td><td>the old filter-bar index of deployment cards moved to /deployments/all/; the rack's and its stations' pages link the workbench</td></tr>
</table>

<h2>Decided for you</h2>
<ul>
<li><b>Runs is a ribbon icon in a group of its own</b>, not a mode inside each view: one place, reachable from every view; the selection carries in (the tree shows it, one click filters to it). Undo: move its entry in <code>site/deployments_workbench.py</code>'s <code>RIBBON</code>.</li>
<li><b>Opening a deployment still lands on the Workbench</b> (no <code>view</code> in the URL), so every older link (<code>?d=…&amp;n=…</code>, the station pages' links, the run rows) keeps opening the node's page; the ribbon's order follows yours, Scene · Sheet · Workbench. Undo: map <code>""</code> to <code>"scene"</code> in the JS's <code>VIEWS</code>.</li>
<li><b>The Table view is the Sheet</b> (<code>view=sheet</code>; <code>view=table</code> still opens it). Its five question columns moved from a switch to an optional group after performance and fidelity, so three acceptance checks now find the question cells by what they are (<code>th[data-q]</code>, <code>td[data-q='twin']</code>) instead of by position, and the Sheet's ribbon selector is <code>[data-v="sheet"]</code> — the same assertions on the same cells.</li>
<li>The sidebar is 300 px by default (Obsidian-like), was 330; the inspector 420, was 470. The tooltip uses a raised surface and a hairline: Obsidian's near-black message colour vanishes on this site's near-black dark theme.</li>
<li>The workbench replaced /deployments/; the card index moved to /deployments/all/ (undo: <code>git revert</code> the commit). <code>site/tests/test_site_flow.py</code>'s index checks now point at /deployments/all/ (paths only).</li>
<li>Each recording is registered in data_recorder's replay index (~1,040 added; additive) so its link works; registration happens at every site build, once per file.</li>
<li>Performance vs fidelity per metric follows sim2real's card families (T2, T3, T7, T8 fidelity; T4, T5, T6, limiter share performance); the repeat floor, data and routines are "evidence".</li>
<li>Parts of a servo gate their servo (strict rule); the servo never gates its station (decision 1). Not observable / not run never fails anything.</li>
</ul>

<h2>Simulated, or not done</h2>
<ul>
<li>Obsidian's sidebar slides open and shut; here it shows and hides without the animation. Obsidian has no default key for the sidebar toggle, so none is bound.</li>
<li>The Scene's 3D is the same schematic scene (labelled so), not a CAD scene; "CAD render" shows the MuJoCo still.</li>
<li>The 3D is schematic (real tip lengths, motor families and loads; plates laid out by hand) — not the house viser viewer, which needs a live server per page.</li>
<li>RobotDx's live unit health is not on the page (only this round's faults and missing plays).</li>
<li>Rounds 6 and 7 (and 31 plays of round 0, 27 of round 1, 84 of round 5) have no .rrd built: those rows say "no recording yet".</li>
<li>T3 (current fidelity) is the late-October value carried in both scorecards. The metric functions are not yet in robot_models (Zach's "folder called metrics"): that is the next step; this page reads the campaign scorer's numbers.</li>
<li>Nothing logs to W&amp;B: the runs JSON is written beside the page data for a later sync.</li>
</ul>
</main></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--base")
    parser.add_argument("--stills", type=Path, help="the acceptance run's --record folder")
    parser.add_argument("--acceptance", type=Path, help="the acceptance run's output")
    parser.add_argument("--pytest", type=Path, help="a summary of the test runs, every line shown as it is")
    parser.add_argument("--commit", default="(not committed yet)")
    parser.add_argument("--no-video", action="store_true", help="keep the hero clip already in the media folder")
    args = parser.parse_args()
    MEDIA.mkdir(parents=True, exist_ok=True)
    if not args.no_video:
        if args.base:
            webm = record_hero(args.base.rstrip("/"))
        else:
            with serve(args.out) as base:
                webm = record_hero(base)
        encode(webm)
        shutil.rmtree(webm.parent, ignore_errors=True)
    if args.stills:
        for name, _cap in STILLS + FRAME_STILLS:
            src = args.stills / f"{name}.png"
            if src.is_file():
                shutil.copyfile(src, MEDIA / f"{name}.png")
    acceptance = lines(args.acceptance, lambda ln: ln.startswith(("PASS ", "FAIL ")))
    pytest_lines = lines(args.pytest, lambda ln: bool(ln.strip()))
    REPORT.write_text(page(acceptance, pytest_lines, duration(MEDIA / "hero.mp4"), args.commit), encoding="utf-8")
    print(f"{REPORT} ({REPORT.stat().st_size / 1e3:.0f} kB; media {sum(p.stat().st_size for p in MEDIA.iterdir()) / 1e6:.1f} MB in {MEDIA})")


if __name__ == "__main__":
    main()
