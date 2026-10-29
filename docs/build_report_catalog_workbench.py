"""Write the review report of sim2real's move onto catalog-workbench (2026-10-29).

    python3 /home/bam/sim2real-worktrees/catalog-workbench/docs/build_report_catalog_workbench.py

Reads the captures in /home/bam/sim2real/reports/media/catalog-workbench-2026-10-29/ (before/: the old app's own test
with --record; after-final/: site/tests/test_site_flow.py --record; hero/: the click path) and the acceptance log, and
writes report.html beside them (media folder, gitignored; images by relative path).
"""

from __future__ import annotations

import html
import pathlib
import sys

MEDIA = pathlib.Path("/home/bam/sim2real/reports/media/catalog-workbench-2026-10-29")
LOG = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else MEDIA / "test.log"
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
    ("data-ui kit", "vendor/data-ui served at /vendor/", "the same vendored copy at /static/data-ui/ (DATA_UI), pinned by manifest", "unchanged (not re-vendored)"),
    ("Page build", "build_pages.py writes app/*.base", "build.build + Writer; site/views.py cuts build_pages along tabs", "a panel can't drift between app and site"),
    ("Data", "tools/build_app.py → app/data", "unchanged (stock seam)", "the robotics contract tables"),
]


def fig(src: str, cap: str = "") -> str:
    return f'<figure><a href="{e(src)}"><img src="{e(src)}" loading="lazy" alt="{e(cap)}"></a>{f"<figcaption>{cap}</figcaption>" if cap else ""}</figure>'


def main():
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
