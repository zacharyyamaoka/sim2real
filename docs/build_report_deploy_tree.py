"""The deployment tree report (2026-11-05): serves a built site, records the hero (the rack's Runs tab: a click on an adapter in
the rail's tree, then on CAN 11, the runs narrowing each time), takes stills of the tree, the flat /runs/ list, the Gates tab's
roll-up tree, a run's configuration and a station's place in the tree, and writes one self-contained page.

    python3 /home/bam/sim2real/site/build.py --out /abs/site
    uv run --no-project --with playwright python /home/bam/sim2real/docs/build_report_deploy_tree.py --site /abs/site

Writes /home/bam/sim2real/reports/media/deploy-tree-2026-11-05/report.html (reports/media/ is gitignored). Serves on a free port in
4711-4799 (never 4700, Zach's) and stops the server by the PID it started. Every number on the page is read from the built site's
own data (tree.json, runs.json) or passed in from a test run (--site-tests, --rack-tests).
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "site" / "tests"))

from test_site_flow import EXE, free_port  # noqa: E402

OUT = Path("/home/bam/sim2real/reports/media/deploy-tree-2026-11-05/report.html")
DEP = "one-dof-test-rack"
RAIL = "[role=tabpanel][data-tab=runs] .dd-rail"
SESSION_EXAMPLE = {"board_configs": {"11": {"file": "board_configs/can11.cfg", "sha256": "3f0c…", "keys": 1396, "firmware": "657b5c5…",
                                            "port": "/dev/serial/by-id/usb-mjbots_fdcanusb_0607623A-if00", "seconds": 27.0, "read_wall": 1793900000.0,
                                            "source": "conf enumerate, read-only, at the session's start (bam_rack_twin.hardware.configcheck.read_whole_configs)"},
                                     "15": {"error": "conf enumerate: TimeoutError", "read_wall": 1793900000.0}}}


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def wait_runs(page, n: int | None = None) -> None:
    js = """(n) => { const s = [...document.querySelectorAll('.dd-panel[data-panel]')].find((x) => { const e = x.querySelector(':scope > data-views');
        return e && e.view && e.view.name === 'Runs' && x.getClientRects().length > 0; }); const e = s && s.querySelector(':scope > data-views');
        return !!e && !!e.model && (n === null || (e.model.matched ?? e.model.rows.length) === n); }"""
    page.wait_for_function(js, arg=n, timeout=30000)


CLIP_JS = """([top, bottom, pad]) => { const a = document.querySelector(top), b = document.querySelector(bottom) || a; if (!a) return null;
  a.scrollIntoView({block: 'start'}); window.scrollBy(0, -90); const r1 = a.getBoundingClientRect(), r2 = b.getBoundingClientRect();
  const x = Math.max(0, Math.min(r1.left, r2.left) - pad), y = Math.max(0, r1.top - pad);
  return {x, y, width: Math.min(innerWidth - x, Math.max(r1.right, r2.right) - x + pad), height: Math.min(innerHeight - y, r2.bottom - y + pad)}; }"""


def shot(page, path: Path, top: str, bottom: str | None = None, pad: int = 8, height: int | None = None) -> Path:
    """A still of the page between two elements (CSS selectors), below the sticky bar; `height` caps it."""
    clip = page.evaluate(CLIP_JS, [top, bottom or top, pad])
    page.wait_for_timeout(300)
    clip = page.evaluate(CLIP_JS, [top, bottom or top, pad])
    if height:
        # no bottom element: the region is `height` tall from the top one; with one, `height` caps it
        room = page.evaluate("innerHeight") - clip["y"]
        clip["height"] = min(room, height) if bottom is None else min(clip["height"], height)
        if bottom is None:
            clip["x"], clip["width"] = 0, page.evaluate("innerWidth")
    page.screenshot(path=str(path), clip=clip)
    return path


def capture(site: Path, media: Path, tree: list[dict], runs_of: Counter) -> dict:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(site)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    shots: dict[str, Path] = {}
    adapter = next(n for n in tree if n["kind"] == "adapter" and "0607623A" in n["label"])
    can11 = next(n for n in tree if n.get("device") == "CAN 11")
    under = sum(runs_of[n["device"]] for n in tree if n.get("device") and n["parent"] == adapter["id"])
    try:
        time.sleep(0.8)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EXE)
            # the hero: the Runs tab, the tree in the rail, an adapter, then CAN 11 (960 x 600 keeps the page under the preview's limit)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(media), record_video_size={"width": 960, "height": 600})
            page = ctx.new_page()
            page.goto(f"{base}/{DEP}/")
            wait_runs(page)
            page.wait_for_timeout(1800)
            node = page.locator(f"{RAIL} button.df-node[data-level='0'][data-value='{adapter['id']}']").first
            node.hover()
            page.wait_for_timeout(900)
            node.click()
            wait_runs(page, under)
            page.wait_for_timeout(1800)
            leaf = page.locator(f"{RAIL} button.df-node[data-level='1'][data-value='{can11['id']}']").first
            leaf.hover()
            page.wait_for_timeout(700)
            leaf.click()
            wait_runs(page, runs_of["CAN 11"])
            page.wait_for_timeout(1600)
            page.locator(".dd-panel[data-panel]", has=page.locator(".dd-panel-h:has-text('Runs · newest first')")).first.scroll_into_view_if_needed()
            page.wait_for_timeout(2200)
            video = page.video.path()
            ctx.close()

            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.goto(f"{base}/{DEP}/")
            wait_runs(page)
            page.wait_for_timeout(1500)
            shots["tree-rail"] = shot(page, media / "tree-rail.png", "nav.tabs", None, height=620)
            page.locator(f"{RAIL} button.df-node[data-level='0'][data-value='{adapter['id']}']").first.click()
            wait_runs(page, under)
            page.locator(f"{RAIL} button.df-node[data-level='1'][data-value='{can11['id']}']").first.click()
            wait_runs(page, runs_of["CAN 11"])
            page.wait_for_timeout(1500)
            shots["tree-can11"] = shot(page, media / "tree-can11.png", "nav.tabs", None, height=620)
            shots["rail-close"] = shot(page, media / "rail-close.png", RAIL, None, height=420)
            page.goto(f"{base}/{DEP}/#gates")
            page.wait_for_function("""() => [...document.querySelectorAll('.dd-panel[data-panel]')].some((s) => { const e = s.querySelector(':scope > data-views');
                return e && e.view && e.view.name === 'The rack' && s.querySelectorAll('td[data-col=worst] .dv-state').length > 0; })""", timeout=30000)
            page.wait_for_timeout(1200)
            rack = page.locator(".dd-panel[data-panel]", has=page.locator(".dd-panel-h:has-text('The rack')")).first
            rack.scroll_into_view_if_needed()
            page.wait_for_timeout(600)
            rack.screenshot(path=str(media / "rollup.png"))
            shots["rollup"] = media / "rollup.png"
            page.goto(f"{base}/runs/")
            page.locator("data-views tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(media / "runs-flat.png"))
            shots["runs-flat"] = media / "runs-flat.png"
            page.goto(f"{base}/{DEP}/can11/")
            page.wait_for_timeout(1200)
            shots["station"] = shot(page, media / "station.png", ".phead h1", ".phead .s2r-tree", pad=10)
            page.goto(f"{base}/{DEP}/")
            wait_runs(page)
            first = page.locator(".dd-panel a[href*='/runs/']").first.get_attribute("href")
            page.goto(base + first.split("#")[0])
            page.wait_for_timeout(1200)
            shots["run-head"] = shot(page, media / "run-head.png", ".phead h1", ".phead .s2r-cfg", pad=10)
            page.click("nav.tabs [role=tab][href='#evidence']")
            page.wait_for_timeout(700)
            shots["run-config"] = shot(page, media / "run-config.png", "[role=tabpanel][data-tab=evidence] h2", "[role=tabpanel][data-tab=evidence] table", pad=10)
            ctx.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    shutil.move(video, media / "raw.webm")
    shots["hero"] = media / "raw.webm"
    # WHY re-encoded and scaled (the desktop preview opens a media page up to ~1.9 MB): VP9 at CRF 44 keeps the rail's words legible
    # at about a quarter of Playwright's VP8; the GIF fallback at 480 px, 5 fps; stills as JPEG at 1100 px
    if shutil.which("ffmpeg"):
        small = media / "hero.webm"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(shots["hero"]), "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "44",
                        "-row-mt", "1", "-an", str(small)], check=False)
        if small.is_file() and small.stat().st_size:
            shots["hero"] = small
        gif = media / "hero.gif"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(shots["hero"]), "-vf",
                        "fps=5,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse", str(gif)], check=False)
        if gif.is_file():
            shots["gif"] = gif
        for key in [k for k in shots if shots[k].suffix == ".png"]:
            jpg = shots[key].with_suffix(".jpg")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(shots[key]), "-vf", "scale='min(1100,iw)':-2", "-q:v", "7", str(jpg)], check=False)
            if jpg.is_file():
                shots[key] = jpg
    return shots


def render(shots: dict, tree: list[dict], rows: list[dict], tests: dict, shas: dict) -> str:
    def img(key: str, alt: str) -> str:
        mime = "image/jpeg" if shots[key].suffix == ".jpg" else "image/png"
        return f'<img src="{data_uri(shots[key], mime)}" alt="{html.escape(alt)}">'

    env, setting, cfg = Counter(r.get("environment") for r in rows), Counter(r.get("setting") for r in rows), Counter(r.get("config") for r in rows)
    full = cfg.get("full", 0)
    by_id = {n["id"]: n for n in tree}
    number = lambda n: int(n["device"].split()[-1]) if n.get("device") and n["device"].split()[-1].isdigit() else 0  # noqa: E731
    order = sorted(tree, key=lambda n: (n["depth"] > 0, by_id.get(n["parent"], {}).get("label", "") if n["depth"] == 2 else n["label"], n["depth"], number(n)))
    tree_rows = "".join(
        f'<tr><td style="padding-left:{8 + 18 * n["depth"]}px">{html.escape(n["label"])}</td><td>{html.escape(n["kind"])}</td>'
        f'<td>{n["passing"]} / {n["cells"]}</td><td>{html.escape(n["worst"] or "—")}</td><td>{n["runs"]:,}</td>'
        f'<td>{html.escape(n.get("card") or "—")}</td></tr>' for n in order)
    tags = "".join(f"<tr><td>{w}</td><td>{env.get(w, 0):,}</td></tr>" for w in ("sim", "bench", "real", "unknown"))
    sets = "".join(f"<tr><td>{w}</td><td>{setting.get(w, 0):,}</td></tr>" for w in ("bench", "deployed", "unknown"))
    gif = f'<img src="{data_uri(shots["gif"], "image/gif")}" alt="hero fallback">' if "gif" in shots else ""
    example = html.escape(json.dumps(SESSION_EXAMPLE, indent=1))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deployment tree report</title><style>
:root{{--bg:#fff;--fg:#1d1f23;--mute:#5d6470;--line:#e3e5e8;--ok:#1a7f37;--bad:#b42318}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8eaed;--mute:#9aa0aa;--line:#2c3036;--ok:#4ac26b;--bad:#ff7b72}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:24px 16px}}
img,video{{max-width:100%;border:1px solid var(--line);border-radius:6px}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}} .mute{{color:var(--mute)}} h2{{margin-top:36px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} @media (max-width:760px){{.grid{{grid-template-columns:1fr}}}} code,pre{{font-size:12.5px}}
pre{{overflow:auto;border:1px solid var(--line);border-radius:6px;padding:10px}} .scroll{{overflow-x:auto}} .lede{{font-size:16px}}
</style></head><body>
<h1>Deployment tree, run tags and config snapshots</h1>
<p class="lede"><b>The rack's runs sit under its tree in the left rail, and a click narrows them to that level.</b> The tree is the bam_rack_twin
record's wiring, as RobotDx draws it: One Dof Test Rack → 2 fdcanusb adapters → 8 stations, each node with the gate cells passing under it
({by_id[DEP]["passing"]} of {by_id[DEP]["cells"]} for the rack). All {len(rows):,} runs are tagged <b>bench</b> (environment) and <b>bench</b>
(setting); <b>{full} of {len(rows):,} runs ({100 * full / len(rows):.0f} %) carry a full config snapshot</b>, because no session recorded the
board's config until now: bam_rack_twin sessions record each board's whole config from today, read-only.</p>
<p class="mute">sim2real {html.escape(shas.get('sim2real', ''))} · bam_ws {html.escape(shas.get('bam_ws', ''))} · site test {tests['site']} ·
bam_rack_twin {tests['rack']}</p>
<h2>Hero: the Runs tab, an adapter, then CAN 11</h2>
<video src="{data_uri(shots['hero'], 'video/webm')}" autoplay muted loop controls playsinline></video>
<details><summary>GIF fallback</summary>{gif}</details>
<div class="grid"><div><h3>The rail opens on the tree</h3>{img('tree-rail', 'the Runs tab with the tree in the rail')}</div>
<div><h3>fdcanusb 0607623A, then CAN 11</h3>{img('tree-can11', 'the runs filtered to CAN 11')}</div></div>
<h3>The rail, close up</h3>{img('rail-close', 'the rail after the clicks')}
<p class="mute">The tree is data-ui's stock <code>tree</code> facet (CONTRACT §7: one <code>p == v</code> per level, Algolia's hierarchical
menu), so a pick lands in the URL and Back undoes it. Each node's words are its gate cells passing; its number is its runs. Default order is
most runs first.</p>
<h2>The match at each level of the rack</h2>
<div class="scroll"><table><tr><th>Node</th><th>Kind</th><th>Gate cells passing</th><th>Worst cell</th><th>Runs</th><th>Type card</th></tr>{tree_rows}</table></div>
<p class="mute">From the newest acceptance's gate cells (gates.json). A node's cells are every cell of every station under it. The Gates tab
draws the same tree with data-ui's roll-up (worst = the Max of RobotDx's ranks, passing = the Sum of passes, cells = their Count):</p>
{img('rollup', 'the Gates tab roll-up tree')}
<h2>Every run, flat</h2>{img('runs-flat', '/runs/ with its facets')}
<p class="mute">/runs/ facets every run by the tree (deployment at its root), environment, setting, test type, type and deployment kind, and
config snapshot.</p>
<h2>Run tags</h2><div class="grid"><div><table><tr><th>Environment</th><th>Runs</th></tr>{tags}</table></div>
<div><table><tr><th>Setting (type_cards SETTINGS)</th><th>Runs</th></tr>{sets}</table></div></div>
<p>Every run is a real recording in the rack's own archive days, so it is <b>bench</b> on both: a test run on real hardware, in the office.
A run outside the registry's archive days, or whose basis is not real, would stay <b>unknown</b>. No run records a type_cards test type, so
every run's test type reads <b>not recorded</b> (the servo card lists no test types yet).</p>
<h2>Configuration snapshots</h2>
<p><b>{full} of {len(rows):,} runs ({100 * full / len(rows):.0f} %)</b> carry a full one. What every session did record: the code
(bam_rack_twin version and git head), the plan and its sha256, each run's own command arguments; the gains shown on a run come from the
record's config_history. A key outside the interlock's 16 (CAN 12's <code>servo.default_accel_limit</code>) was nowhere.</p>
<h3>A run says so in its header</h3>{img('run-head', 'run header: config not recorded')}
<h3>…and on its Evidence tab, what is recorded</h3>{img('run-config', 'run evidence: configuration')}
<h3>From today, every bam_rack_twin session writes each board's whole config</h3>
<p>One <code>conf enumerate</code> per board after the config check and before the recorder (read-only: nothing set, written or reset),
written to <code>board_configs/can&lt;id&gt;.cfg</code> in moteus_tool --dump-config's text (its --restore-config takes it) and named in
session.json with its sha256 and key count. A read that fails is recorded with its reason and the session still runs. sim2real counts a run
as full only when the file's key lines hash to that sha256.</p><pre>{example}</pre>
<h3>A station's place in the tree</h3>{img('station', 'CAN 11 header with its tree line')}
<h2>Stock parts</h2><div class="scroll"><table><tr><th>Element</th><th>Before</th><th>Off-the-shelf part</th><th>Behaviour that must survive</th></tr>
<tr><td>The tree in the rail</td><td>a flat Station facet</td><td>data-ui <code>tree</code> facet (vendored d5ede93, unedited)</td><td>the rail on the left; a pick filters every panel and is in the URL</td></tr>
<tr><td>Match per node</td><td>stations only (gate chips)</td><td>gates.json cells, counted per subtree; node words via the field's <code>labels</code></td><td>the same cells the matrix draws</td></tr>
<tr><td>Roll-up tree (Gates tab)</td><td>rack → plates → stations</td><td>data-ui roll-up (§17, §35): Max of rank, Sum and Count of passes</td><td>worst word and glyph per node</td></tr>
<tr><td>RobotDx's entity tree</td><td>—</td><td>its data shape (path ids, a parent, icon words), not its renderer</td><td>its renderer is app-internal (web/tree/v6.js on RobotDx's /state API), so it is not imported</td></tr>
<tr><td>Flat runs by tag</td><td>Station, kind, day…</td><td>data-ui values facets</td><td>counts per value, Show more</td></tr></table></div>
<h2>Decided for you</h2><ul>
<li><b>The rack's tags: environment bench, setting bench.</b> The registry says the rack is on Zach's bench at home: in the office.
Undo: drop <code>environment</code> / <code>setting</code> from app/registry.json and every run reads unknown.</li>
<li><b>Setting uses type_cards' SETTINGS (bench | deployed)</b>, as the coordinator asked, not "office / facility".</li>
<li><b>No host level.</b> No run or session records the computer it ran on; the tree starts at the adapters.</li>
<li><b>A failed config read never blocks a session.</b> The interlock already passed; the run is marked "config not recorded" with the
reason. Undo: raise from <code>_read_board_configs</code> to refuse instead.</li>
<li><b>The Gates tab's roll-up tree is the adapter tree</b> (was plates; the groups hold the same stations on this rack).</li></ul>
<h2>Left</h2><ul><li>Config coverage climbs only as new sessions run: the next rack session is the first with a full snapshot.</li>
<li>Test types: once the servo card lists TestTypes, the runner's schedule stamp could carry the id.</li>
<li>A deployed (facility) deployment would add <code>real</code> runs and the deeper tree (facility → robot → arm → joint → servo).</li></ul>
<p class="mute">Built by docs/build_report_deploy_tree.py · sim2real · {time.strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--site-tests", default="?")
    parser.add_argument("--rack-tests", default="?")
    parser.add_argument("--sim2real-sha", default="")
    parser.add_argument("--bam-ws-sha", default="")
    args = parser.parse_args()
    site = args.site.resolve()
    tree = json.loads((site / "data" / DEP / "tree.json").read_text())["rows"]
    rows = json.loads((site / "data" / DEP / "runs.json").read_text())["rows"]
    runs_of = Counter(r["device"] for r in rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shots = capture(site, Path(tmp), tree, runs_of)
        OUT.write_text(render(shots, tree, rows, {"site": args.site_tests, "rack": args.rack_tests},
                              {"sim2real": args.sim2real_sha, "bam_ws": args.bam_ws_sha}), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
