"""Write the review report of sim2real's move onto catalog-workbench (2026-10-29).

    python3 /home/bam/sim2real-worktrees/catalog-workbench/docs/build_report_catalog_workbench.py
    uv run --no-project --with playwright python /home/bam/sim2real-worktrees/catalog-workbench/docs/build_report_catalog_workbench.py --capture

--capture first records the data-ui 006e9d5 section's stills and its pick-and-Back clip from the built site (served on a free
port in 4711-4799, stopped by its pid) into data-ui-006e9d5/; its acceptance log is data-ui-006e9d5/test.log (the site test's
output). Without it the page is rebuilt from what is there.

Reads the captures in /home/bam/sim2real/reports/media/catalog-workbench-2026-10-29/ (before/: the old app's own test
with --record; after-final/: site/tests/test_site_flow.py --record; hero/: the click path) and the acceptance log, and
writes report.html beside them (media folder, gitignored; images by relative path).
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time

MEDIA = pathlib.Path("/home/bam/sim2real/reports/media/catalog-workbench-2026-10-29")
DUI = MEDIA / "data-ui-006e9d5"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
# WHY the newest log by default: the verdict line counts the checks as they stand now (the data-ui section's run, if there is one)
LOG = pathlib.Path(ARGS[0]) if ARGS else (DUI / "test.log" if (DUI / "test.log").is_file() else MEDIA / "test.log")
SITE_OUT = pathlib.Path.home() / ".cache" / "sim2real" / "site"
DEP = "one-dof-test-rack"
HELD_OUT = "2026-10-28~t2~heldout_can12~runs~s18_can12_sine"
LAUNCH = "python3 -m http.server 4710 --bind 127.0.0.1 --directory /home/bam/.cache/sim2real/site"
BUILD = "python3 /home/bam/sim2real-worktrees/catalog-workbench/site/build.py"
e = html.escape

PAIRS = [
    ("Home", "before/1-deployments.png", "after-final/1-home.png",
     "Was a deployments table. Now the workbench's home: Choose column (drag-resizable), tiles of deployments and stations (each station's picture is its T1-T11 strip), and below them <b>Where it fails</b>: every gate cell, each opening its why."),
    ("A deployment", "before/2-deployment.png", "after-final/3-deployment.png",
     "Same runs dashboard (rail on the right, newest first), now under the record header: KPIs, the 32 of 88 standing, and a badge per station with its strip, then tabs Runs · Gates · Why it fails · Coverage · Evidence."),
    ("Gates", "before/4-gates-layer.png", "after-final/4-gates.png",
     "The Gates layer switch became the Gates tab: a static stations × gates matrix on top, then the same overlay dashboard (gauge, passing per gate, tracker, run verdicts, station diagnostics)."),
    ("A run · Playback", "before/5-run.png", "after-final/5-run-playback.png",
     "The same run.base (blue real, orange models, trajectory3d, legend toggle, play). The header now says real vs target, the closest model and the station's gates."),
    ("A run · Gates / Diagnostics", "before/7-run-gates.png", "after-final/7-run-diagnostics.png",
     "The run's gates layer became two tabs: Gates (this run's verdicts and its station's T1-T11) and Diagnostics (every robotdx diagnostic, evidence links jump the playback)."),
    ("Why it fails · the deployment", "before/8-why-it-fails.png", "after-final/8-why-it-fails.png",
     "The same why dashboard (one wrapped column grouped by station, the columns one tab away, evidence files, caveats), now its own tab."),
    ("Why it fails · from a row", "before/9-why-run.png", "after-final/10-run-why.png",
     "A T2 row still opens its worst held-out window on the Playback (after-final/9-why-run.png). The decomposition moved to the run's Why it fails tab, and it now draws its bars (they were blank before: see Fixed)."),
]
NEW = [("Analysis › Why it fails", "after-final/11-analysis-why.png", "Every open cell in words, grouped by station, with the matrix on top and a resizable contents column. No JavaScript needed."),
       ("Search", "after-final/2-search.png", "The workbench's search: stations and runs as you type; Enter lists the matching runs."),
       ("Phone, 390 px", "after-final/12-home-390.png", "No sideways scroll on the click path (measured on 5 pages).")]

STOCK = [
    ("Header bar", "app/index.html .bar: lockup, crumbs, Gates layer switch, Proposals link", "shell.site_header: wordmark, one centred search, quick links, Account ▾", "the lockup in light and dark; one click home"),
    ("Breadcrumb", "app.js builds Deployments › rack › run", "html.breadcrumb in the trail (+ Back to results)", "deployment › station › run, every crumb a link"),
    ("Routes", "?d= &run= &layer=gates &why= in app.js", "Kind.url static paths, Writer", "old links still land: /app/?d=… rewritten at build; #t=…&tr=… still the clock"),
    ("Deployments list", "deployments.base table", "home.tile_home groups + /deployments/", "open the rack in one click"),
    ("Deployment page", "deployment.base, one long dashboard", "record.record_page, Kind DEPLOYMENT, 5 Tabs", "runs newest first, the rail, coverage at 1/n opacity"),
    ("Gates layer", "#layer switch swapping to -gates.base", "Tab “Gates”", "the matrix, verdicts, diagnostics"),
    ("Run page", "run.base", "Kind RUN, Tab “Playback” (same run.base)", "blue real / orange model, legend toggle, trajectory3d, Play"),
    ("Run gates layer", "run-gates.base", "Tabs “Gates” and “Diagnostics” (static)", "every diagnostic; evidence jumps the playback"),
    ("Why it fails", "a table panel in deployment.base", "Tab “Why it fails” (same panels) + AnalysisArea report + station/run Why tabs", "one row per open cell, number vs limit, why, next; fits 1280 and 390 px"),
    ("Run opened from Why", "run-why.base: playback + decomposition", "Playback at #t window + the run's Why tab", "worst window, the decomposition bars"),
    ("Evidence / caveats", "panels in deployment.base", "Tab “Evidence” + the same panels", "each source file and its date"),
    ("Search", "none", "shell search menu + /search/suggest.json + /search/ data-views", "(new)"),
    ("Settings", "the OS theme only", "Account menu: theme, recently viewed runs, open mode, keys", "dark mode"),
    ("Side panels", "data-ui rail moved right", "data-resizable Choose column / contents column; rail stays right", "every side panel resizable"),
    ("Colours", "app.css --s2r-* tokens", "Brand.styles → sim2real.css over robotparts' site.css", "blue = real, orange = model, green/red = pass/fail only"),
    ("data-ui kit", "vendor/data-ui served at /vendor/", "a real vendored copy of data-ui 006e9d5 at /static/data-ui/ (DATA_UI), pinned by manifest", "re-vendored 2026-10-29 (was a0b229b, linked)"),
    ("Gate matrix", "a static HTML table (pages.matrix) + a tracker without columns", "data-ui tracker + column (gate_matrix, §35); the static table its fallback", "every cell a glyph and a word; a cell opens its why"),
    ("Gate standing number", "a gauge", "kpi + spark + target (kpi_trend)", "the newest acceptance's count, and its history"),
    ("Rack roll-up", "the station badges' strips", "table + tree + dataset roll-up (rollup_tree)", "the worst gate under each node"),
    ("Limits", "none on the plots", "timeseries limits (threshold_band)", "T2's 1.5× floor and T4's stop allocation"),
    ("A run's evidence", "static tables with links", "tracker + record.sections[].view + display: link (evidence)", "the link lands on the Playback at #t"),
    ("Picking a run", "Open ↗ to its own page", "a dataset read per pick + one-way link (PEP 0013)", "Open ↗ still works; Back restores a pick"),
    ("Page build", "build_pages.py writes app/*.base", "build.build + Writer; site/views.py cuts build_pages along tabs", "a panel can't drift between app and site"),
    ("Data", "tools/build_app.py → app/data", "unchanged (stock seam)", "the robotics contract tables"),
]

# ---- data-ui 006e9d5 (PEP 0010 P3 / P5): what the site adopted, as stills from the built site ------------------------------
DUI_SHOTS = [
    ("gate-matrix-home.png", "Gate matrix · the home",
     "data-ui's gate_matrix (tracker + column): stations × T1-T11, each cell its verdict as a glyph and a word in RobotDx's status order "
     "(pass, warn / partial, not run, fail). The static matrix stays as what reads before the kit loads. Partial is the site's amber now: "
     "robotparts' red-orange --warn had leaked in."),
    ("gate-peek.png", "A matrix cell opens its gate", "Click CAN 12 · T3: the side peek holds its verdict, number, limit and the link to why it fails."),
    ("kpi-trend.png", "KPI trend against its target",
     "Gate cells passing per bam_rack_twin acceptance file in the archive (14 files, Oct 26-29: 16 → 32), every cell the target (88), "
     "and one card per station against its 11."),
    ("rollup-tree.png", "The rack roll-up", "rollup_tree: the rack, its plates and stations, each the worst gate under it (Max of RobotDx's ranks), word and glyph."),
    ("threshold-run.png", "Threshold bands on a run",
     "T4's stop allocation on the error against the target and T2's 1.5× floor on each model's error against real, per series, dashed red with the zone beyond shaded."),
    ("evidence-peek.png", "Evidence in the peek",
     "A run-check cell opens its check: the evidence link (lands on the run's Playback at #t=) and that run's other checks, embedded."),
    ("path-overlay.png", "Path overlay on the run's 3D",
     "The real marker's path coloured by its distance from the target (the producer's err_mm, now written on the pose rows), T4's allocation at the 100 mm marker as the target's tube (± 0.36 mm)."),
    ("voxels.png", "Verdict voxels on Coverage",
     "Runs per (q, qd) cell, every station on its own 24 × 24 grid: 1,525 runs counted, not faded at 1/n opacity. Red few, green many (the resting cell holds 730)."),
    ("picked-run.png", "A row click plays that run", "P3: the Runs tab reads one run's samples on a pick; Back and Forward restore the pick and t."),
]
DUI_NOT = [
    ("A T2 band per run on the station's Gates tab", "Tried and dropped: a station's model runs come in bursts (CAN 12: 28 in ten minutes on 10-28, one on 10-25), and a timeseries' x is time, so they drew as one vertical line. T2's band is on each run's Playback, per model."),
    ("Presets (<code>selected: first</code>)", "Not used: the Runs tab opens with nothing picked, so it reads no run's samples until you click one, and its hash stays free for the tabs."),
    ("Add to dashboard (§34)", "Arrives with the kit on every panel's ⋯ menu. The site gives no <code>dashboards()</code> hook, so it copies the panel's .base text to the clipboard."),
    ("<code>level_history</code>, a keyed live feed", "No diagnostic history per window is written for the rack yet; nothing to draw."),
    ("The Playback + Gates twins wholesale", "Their views are mirrored (matrix, roll-up tree, run checks with an embedded section view, limits), on sim2real's own tables; their .base files read the gallery's files, not the site's."),
]


def capture() -> None:
    """Stills and the pick clip from the built site, headless; the server is ours and is stopped by its pid."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "site" / "tests"))
    import test_site_flow as T  # noqa: PLC0415  (its browser, its panel finder and its port rule)
    DUI.mkdir(parents=True, exist_ok=True)
    port = T.free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(SITE_OUT)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=T.EXE)
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            def shot(url, title, name, before=None, settle=3500):
                page.goto(base + url)
                page.wait_for_load_state("load")
                page.wait_for_timeout(2500)
                loc = T.panel(page, title)
                loc.evaluate("el => el.scrollIntoView({block: \'center\'})")  # clear of the sticky bar
                page.wait_for_timeout(settle)
                if before:
                    before(loc)
                loc.screenshot(path=str(DUI / name))

            shot("/", "Stations × gates", "gate-matrix-home.png")
            page.goto(f"{base}/{DEP}/#gates")
            page.wait_for_timeout(5000)
            page.locator("[role=tabpanel][data-tab=gates] [role=gridcell][aria-label^='CAN 12 · T3']").first.click()
            page.wait_for_timeout(2000)
            page.screenshot(path=str(DUI / "gate-peek.png"))
            page.keyboard.press("Escape")
            kpi_a, kpi_b = T.panel(page, "Gate cells passing"), T.panel(page, "Passing per station · history")
            kpi_a.evaluate("el => el.scrollIntoView({block: \'center\'})")  # clear of the sticky bar
            page.wait_for_timeout(2500)
            kpi_a.screenshot(path=str(DUI / "kpi-a.png"))
            kpi_b.evaluate("el => el.scrollIntoView({block: \'center\'})")  # clear of the sticky bar
            page.wait_for_timeout(2500)
            kpi_b.screenshot(path=str(DUI / "kpi-b.png"))
            T.panel(page, "The rack").screenshot(path=str(DUI / "rollup-tree.png"))
            _stack([DUI / "kpi-a.png", DUI / "kpi-b.png"], DUI / "kpi-trend.png")
            page.goto(f"{base}/{DEP}/runs/{HELD_OUT}/")
            page.wait_for_timeout(4000)
            a, b = T.panel(page, "Error against the target (target − each)"), T.panel(page, "Model error against real (real − model)")
            a.evaluate("el => el.scrollIntoView({block: \'center\'})")  # clear of the sticky bar
            page.wait_for_timeout(3500)
            page.screenshot(path=str(DUI / "threshold-run.png"), clip=_union(a, b, page.evaluate("scrollY")), full_page=True)
            p3d = T.panel(page, "Output link · distance from the target")
            p3d.evaluate("el => el.scrollIntoView({block: \'center\'})")  # clear of the sticky bar
            page.wait_for_timeout(4000)
            p3d.screenshot(path=str(DUI / "path-overlay.png"))
            page.goto(f"{base}/{DEP}/can12/#gates")
            page.wait_for_timeout(5000)
            cell = page.locator("[role=tabpanel][data-tab=gates] [role=gridcell][data-id][data-column='tracking error rms']").first
            cell.evaluate("el => el.scrollIntoView({block: \'center\'})")  # clear of the sticky bar
            cell.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(DUI / "evidence-peek.png"))
            shot(f"/{DEP}/#coverage", "Runs per cell · every station", "voxels.png", settle=5000)
            page.close()
            # the pick clip: a row, another, Back (the first comes back with its t), Forward
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, record_video_dir=str(DUI / "clip"), record_video_size={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.goto(f"{base}/{DEP}/")
            page.wait_for_timeout(3500)
            page.locator(".dd-rail label", has_text="real + 4 models").first.click()
            page.wait_for_timeout(1200)
            T.panel(page, "Playback · the picked run").scroll_into_view_if_needed()
            page.evaluate("scrollBy(0, -420)")
            page.wait_for_timeout(800)
            rows = T.panel(page, "Runs · newest first").locator("tbody tr")
            rows.nth(0).locator("td").first.click()
            page.wait_for_timeout(2500)
            page.locator("button[aria-label*='Play' i]").last.click()
            page.wait_for_timeout(2500)
            page.locator("button[aria-label*='Pause' i]").last.click()
            rows.nth(3).locator("td").first.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(DUI / "picked-run.png"))
            page.go_back()
            page.wait_for_timeout(3000)
            page.go_forward()
            page.wait_for_timeout(2500)
            ctx.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    clips = sorted((DUI / "clip").glob("*.webm"), key=lambda f: f.stat().st_mtime)
    if clips:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clips[-1]), "-an", "-vf", "fps=12,scale=960:-2", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(DUI / "pick.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(DUI / "pick.mp4"), "-vf", "fps=6,scale=640:-2:flags=lanczos", str(DUI / "pick.gif")], check=True)
        shutil.rmtree(DUI / "clip")


def _union(a, b, scroll_y: float) -> dict:
    """The box round two panels, in the document's coordinates (a full-page clip)."""
    ra, rb = a.bounding_box(), b.bounding_box()
    x0, y0 = min(ra["x"], rb["x"]), min(ra["y"], rb["y"]) + scroll_y
    return {"x": x0, "y": y0, "width": max(ra["x"] + ra["width"], rb["x"] + rb["width"]) - x0, "height": max(ra["y"] + ra["height"], rb["y"] + rb["height"]) + scroll_y - y0}


def _stack(parts, out) -> None:
    """Two stills one above the other (ffmpeg's vstack after padding to one width)."""
    widths = [int(json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "json", str(p)],
                                            capture_output=True, text=True).stdout)["streams"][0]["width"]) for p in parts]
    w = max(widths)
    pads = "".join(f"[{i}:v]pad={w}:ih:0:0:white[p{i}];" for i in range(len(parts)))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *sum([["-i", str(p)] for p in parts], []), "-filter_complex",
                    pads + "".join(f"[p{i}]" for i in range(len(parts))) + f"vstack=inputs={len(parts)}", str(out)], check=True)
    for p in parts:
        p.unlink()


def dui_section() -> str:
    log = DUI / "test.log"
    lines = [l for l in log.read_text().splitlines() if l.startswith(("PASS", "FAIL"))] if log.is_file() else []
    passed = sum(1 for l in lines if l.startswith("PASS"))
    shots = "".join(f'<section class="pair"><h3>{e(t)}</h3><p>{e(c)}</p>{fig("data-ui-006e9d5/" + n)}</section>' for n, t, c in DUI_SHOTS if (DUI / n).is_file())
    clip = ('<video src="data-ui-006e9d5/pick.mp4" autoplay muted loop playsinline controls poster="data-ui-006e9d5/picked-run.png">'
            '<img src="data-ui-006e9d5/pick.gif" alt="pick, pick, Back, Forward"></video>'
            '<p class="mut">The Runs tab: a row click plays that run (only its samples.json is read), Play, a second row, then Back (the first run and its t '
            'come back without a refetch) and Forward. <a href="data-ui-006e9d5/pick.gif">GIF</a>.</p>') if (DUI / "pick.mp4").is_file() else ""
    nots = "".join(f"<li><b>{t}</b>: {c}</li>" for t, c in DUI_NOT)
    return f"""
<h2 id="data-ui-006e9d5">data-ui 006e9d5: navigation and the gate views</h2>
<p class="verdict"><b>The site now vendors data-ui <code>integrate/packet</code> @ <code>006e9d5</code> as a real copy (it linked the main checkout's a0b229b trial)
and draws its gates with data-ui's stock views.</b> {passed} of {len(lines)} checks pass; the {len(lines) - 58} new ones measure what was drawn (cells, Vega's guides and points, the scene's
segments and cells, the network log), and were committed red before the code. Still on branch <code>catalog-workbench</code>, not merged; data-ui 006e9d5 is not on data-ui main either.</p>
{clip}
{shots}
<h3>Adopted with a change of its own</h3>
<ul><li><b>tools/build_app.py</b> writes <code>err_mm</code> on every pose row (the target's 0), as CONTRACT §35 asks of a producer; app/data was rebuilt (1,549 runs, 32/88, 3 min).</li>
<li><b>site/overlays.py</b> writes the rows the views read, beside the app's tables: gate ranks and why links, the rack tree, the gate history from the archive's 14 acceptance files, and each station's coverage cells. Each is a lookup or a join of the producer's numbers.</li>
<li><b>The host's fill</b> (static/sim2real.js) leaves an empty field alone, so <code>{{run}}</code> is data-ui's own per-pick placeholder on the Runs tabs, and fills numbers (the station's T2 / T4 limits) unquoted.</li></ul>
<h3>Not adopted, and why</h3><ul>{nots}</ul>
<h3>data-ui issue found</h3>
<ul><li><b>A table ignores a property's <code>digits</code></b> (CONTRACT §17's declared rounding): neither the .base's <code>properties: {{value: {{digits: 3}}}}</code> nor the file's schema rounds a table cell (2.6799053096539507 stays), in a top-level table or a peek's section view; <code>decimals</code> does. The site uses decimals.</li></ul>
<details><summary>The {len(lines)} checks</summary><ul class="checks">{"".join(f'<li class="{"ok" if l.startswith("PASS") else "bad"}">{e(l)}</li>' for l in lines)}</ul></details>
"""


def fig(src: str, cap: str = "") -> str:
    return f'<figure><a href="{e(src)}"><img src="{e(src)}" loading="lazy" alt="{e(cap)}"></a>{f"<figcaption>{cap}</figcaption>" if cap else ""}</figure>'


def main():
    if "--capture" in sys.argv:
        capture()
    lines = [l for l in LOG.read_text().splitlines() if l.startswith(("PASS", "FAIL"))] if LOG.is_file() else []
    passed = sum(1 for l in lines if l.startswith("PASS"))
    checks = "".join(f'<li class="{"ok" if l.startswith("PASS") else "bad"}">{e(l)}</li>' for l in lines)
    pairs = "".join(f'<section class="pair"><h3>{e(t)}</h3><p>{c}</p><div class="two">{fig(b, "before · the app")}{fig(a, "after · catalog-workbench")}</div></section>'
                    for t, b, a, c in PAIRS)
    new = "".join(f'<section class="pair"><h3>{e(t)}</h3><p>{e(c)}</p>{fig(s)}</section>' for t, s, c in NEW)
    stock = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td><td>{e(d)}</td></tr>" for a, b, c, d in STOCK)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>sim2real on catalog-workbench</title>
<style>
:root {{ --bg:#fff; --ink:#18181b; --mut:#5b5b66; --rule:#e4e4e7; --ok:#1d7a3a; --bad:#b42318; --code:#f4f4f5; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0c0c0e; --ink:#ececef; --mut:#a1a1aa; --rule:#2c2c31; --ok:#4cc06e; --bad:#f2685c; --code:#18181b; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ font-size:26px; margin:0 0 6px; }} h2 {{ margin-top:36px; border-bottom:1px solid var(--rule); padding-bottom:4px; }}
.verdict {{ font-size:17px; }} .mut {{ color:var(--mut); }}
code, pre {{ background:var(--code); border-radius:4px; padding:1px 5px; font-size:13px; }} pre {{ padding:10px; overflow-x:auto; }}
video, img {{ max-width:100%; height:auto; border:1px solid var(--rule); border-radius:6px; display:block; }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }} @media (max-width:760px) {{ .two {{ grid-template-columns:1fr; }} }}
figure {{ margin:0; }} figcaption {{ font-size:12.5px; color:var(--mut); margin-top:4px; }}
table {{ border-collapse:collapse; font-size:13.5px; width:100%; }} th, td {{ border-bottom:1px solid var(--rule); padding:5px 8px 5px 0; text-align:left; vertical-align:top; }}
.scroll {{ overflow-x:auto; }} ul.checks {{ font:12.5px/1.45 ui-monospace, monospace; padding-left:18px; }} li.ok::marker {{ color:var(--ok); }} li.bad {{ color:var(--bad); }}
</style></head><body><main>
<h1>sim2real on catalog-workbench</h1>
<p class="verdict"><b>sim2real now runs on the shared catalog-workbench shell, the same as robotparts and the object database: the same bar, search, Account menu, trail, home tiles and tabbed record pages.</b>
It lives on branch <code>catalog-workbench</code> (worktree <code>/home/bam/sim2real-worktrees/catalog-workbench</code>) and is not merged. Acceptance: <b>{passed} of {len(lines)}</b> checks pass. The workbench needed no change.</p>
<p>Open it (build first, about 1 s):</p><pre>{e(BUILD)}
{e(LAUNCH)}</pre><p class="mut">then <code>http://127.0.0.1:4710/</code>. It does not use port 4700 (Zach's serve.py).</p>

<h2>The click path: home → deployment → Why it fails → a run</h2>
<video src="hero/hero.mp4" autoplay muted loop playsinline controls poster="after-final/1-home.png"><img src="hero/hero.gif" alt="click path"></video>
<p class="mut">25 s, recorded headless from the built site: the home and its Where it fails matrix, the rack tile, the Why it fails tab, a CAN 11 T2 row (it opens the run's playback at its worst held-out window, 2.85 s), Play, then the run's Why it fails tab with the decomposition. <a href="hero/hero.gif">GIF</a>.</p>

{dui_section()}
<h2>What you need to decide</h2>
<ul>
<li><b>Merge?</b> Recommended once you have clicked through it. If you say nothing, it stays on the branch.</li>
<li><b>Retire <code>/app/</code>?</b> The old app is untouched on the branch, and serve.py still serves it. Recommendation: once this is merged, serve the new site from serve.py and drop app/index.html, app.js and app.css. Default: keep both.</li>
<li><b>Workbench candidates.</b> Under the “two catalogs need it now” rule, two behaviours now qualify. (1) shell.js's “parts / brand / level” words, which the object database and sim2real both relabel in their own JS. (2) Lazy tab panels: a tab whose content loads the first time it opens. I did not change catalog-workbench. Default: leave both to the workbench's owner.</li>
</ul>

<h2>Before and after</h2>{pairs}
<h2>New with the workbench</h2>{new}

<h2>Stock-part mapping</h2>
<div class="scroll"><table><thead><tr><th>Element</th><th>Today in sim2real</th><th>catalog-workbench part</th><th>Behaviour that must survive</th></tr></thead><tbody>{stock}</tbody></table></div>

<h2>What did not survive, or changed</h2>
<ul>
<li><b>The Gates layer as an overlay on the same page.</b> It is now its own tab, so the gate matrix and the runs table are no longer on one scroll. The Gates tab repeats the matrix statically at its top.</li>
<li><b>The combined run-why page</b> (playback and decomposition on one page). A Why row now opens the Playback tab at the worst window, and the decomposition is one tab over.</li>
<li><b>Rail filters in the URL</b> are kept only by each page's first-tab dashboard. The other tabs' dashboards are <code>no-url</code>, so data-ui keeps <code>#t=</code> unscoped and old evidence links still land.</li>
<li><b>Proposals link</b> (<code>/dashboards/</code>): not part of the site. serve.py still serves the proposals.</li>
<li><b>Settings keys</b> are <code>robotparts.*</code>, because the shared shell.js uses them, as it does for the object database. They are per origin, so nothing is shared.</li>
<li><b>Accent colour</b> is neutral, not robotparts' blue, and robotparts' purple series slot 2 is reset to data-ui's orange. Blue still means only real.</li>
</ul>

<h2>Fixed on the way</h2>
<ul><li>The residual-decomposition bars were blank in the old app too: the v2 rows name “before (twin today, C)”, which build_pages' fixed colour domain did not hold. The site's copy drops the domain, so the bars now draw. <code>app/</code> on main still has the bug.</li>
<li>Stations with an empty decomposition file show no empty chart.</li></ul>

<h2>Data note</h2>
<p>The main checkout's <code>app/data</code> is stale: it uses acceptance_warm4.json (28/88), and the old app's own test fails 3 checks on it today, because the newest file is acceptance_limiting.json (32/88). The site was built from data rebuilt in the worktree (<code>tools/build_app.py</code>, 1,549 runs), so it shows 32/88. The main checkout was not touched.</p>

<h2>Acceptance checks ({passed}/{len(lines)})</h2>
<p class="mut">site/tests/test_site_flow.py. It was committed before the site (9cec549). It ports app/tests/test_app_flow.py's 25 checks and adds the shell's own. Spatial checks are measured with getBoundingClientRect in headless Chromium at 1280 and 390 px. Since then the ruler has had two selector fixes, both named in commit cc2cf51.</p>
<ul class="checks">{checks}</ul>
</main></body></html>
"""
    (MEDIA / "report.html").write_text(page, encoding="utf-8")
    print(MEDIA / "report.html")


if __name__ == "__main__":
    main()
