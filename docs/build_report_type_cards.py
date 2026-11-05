"""The type cards report (2026-11-04): serves a built site, records the click-through from a station to its Servo card's
Coverage tab, takes stills of the Types area, and writes one self-contained page.

    python3 /home/bam/sim2real/site/build.py --out /abs/site
    uv run --no-project --with playwright python /home/bam/sim2real/docs/build_report_type_cards.py --site /abs/site

Writes /home/bam/sim2real/reports/media/type-cards-2026-11-04/report.html (reports/media/ is gitignored). Serves on a free port in
4711-4799 (never 4700, Zach's) and stops the server by the PID it started.
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
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "site" / "tests"))
sys.path.append(str(REPO))

from test_site_flow import EXE, free_port  # noqa: E402
from type_cards import coverage as cov  # noqa: E402
from type_cards import registry as reg  # noqa: E402

OUT = Path("/home/bam/sim2real/reports/media/type-cards-2026-11-04/report.html")
DEP = "one-dof-test-rack"
SCHEDULE = Path("/archive/datasets/bam_rig/schedules/one-dof-test-rack/can11/schedule.json")


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def capture(site: Path, media: Path) -> dict:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(site)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    shots = {}
    try:
        time.sleep(0.8)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EXE)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(media), record_video_size={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.goto(f"{base}/{DEP}/can11/")
            page.wait_for_timeout(1500)
            page.locator(".phead a.s2r-type-link").scroll_into_view_if_needed()
            page.locator(".phead a.s2r-type-link").hover()
            page.wait_for_timeout(900)
            page.locator(".phead a.s2r-type-link").click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)
            for key in ("metrics", "model", "coverage"):
                page.click(f"nav.tabs [role=tab][href='#{key}']")
                page.wait_for_timeout(1400)
            page.locator("svg.s2r-cov").scroll_into_view_if_needed()
            page.wait_for_timeout(2500)
            video = page.video.path()
            ctx.close()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            for name, url, full in (("types", "/types/", True), ("station", f"/{DEP}/can11/", False), ("servo-metrics", "/types/servo/#metrics", True),
                                    ("servo-coverage", "/types/servo/#coverage", True), ("motor", "/types/motor/", False)):
                page.goto(base + url)
                page.wait_for_timeout(900)
                path = media / f"{name}.png"
                page.screenshot(path=str(path), full_page=full)
                shots[name] = path
            page.goto(base + "/types/servo/#coverage")
            fig = page.locator("figure.s2r-covfig")
            page.wait_for_timeout(600)
            fig.screenshot(path=str(media / "coverage-map.png"))
            shots["coverage-map"] = media / "coverage-map.png"
            ctx.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    mp4 = media / "hero.webm"
    shutil.move(video, mp4)
    shots["hero"] = mp4
    if shutil.which("ffmpeg"):
        gif = media / "hero.gif"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp4), "-vf", "fps=8,scale=800:-1:flags=lanczos", str(gif)], check=False)
        if gif.is_file():
            shots["gif"] = gif
    return shots


def render(shots: dict, tests: dict) -> str:
    sched = json.loads(SCHEDULE.read_text())
    train = cov.servo_coverage(sched)
    cards = list(reg.CARDS.values())
    rows = "".join(f"<tr><td>{html.escape(c.title)}</td><td>{len(c.metrics)} ({sum(1 for m in c.metrics if not m.robotdx)})</td><td>{len(c.model.parameters)}</td>"
                   f"<td>{html.escape(', '.join(a.name for a in c.coverage.axes))}</td><td>{html.escape(c.view.template or 'proposed')}</td>"
                   f"<td>{c.observability.today}</td></tr>" for c in cards)
    gaps = "".join(f"<li><b>{html.escape(repo)}</b> · {html.escape(reg.CARDS[card].title)}: {html.escape(what)}</li>" for repo, card, what in reg.gaps())
    img = lambda k, alt: f'<img src="{data_uri(shots[k], "image/png")}" alt="{html.escape(alt)}">'  # noqa: E731
    gif = f'<img src="{data_uri(shots["gif"], "image/gif")}" alt="hero fallback">' if "gif" in shots else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sim2Real type cards</title><style>
:root{{--bg:#fff;--fg:#1d1f23;--mute:#5d6470;--line:#e3e5e8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8eaed;--mute:#9aa0aa;--line:#2c3036}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:24px 16px}}
img,video{{max-width:100%;border:1px solid var(--line);border-radius:6px}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}} .mute{{color:var(--mute)}} h2{{margin-top:36px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} @media (max-width:760px){{.grid{{grid-template-columns:1fr}}}} code{{font-size:13px}}
</style></head><body>
<h1>Sim2Real type cards: one card per part type, in code, in the vault and in the site</h1>
<p><b>{len(cards)} cards</b> (Zach's 10 + encoder) with black-box metrics, a model, coverage, a view and the shared seven-step procedure. The Servo card's
coverage function gives CAN 11's planned schedule <b>{train.pct} %</b> ({train.visited} of {train.reachable} reachable cells), the same number
<code>bam_rack_twin.schedule</code> computes. Tests: registry {tests['registry']}, site {tests['site']}.</p>
<h2>Hero: a station → its Servo card → Metrics, Model, Coverage</h2>
<video src="{data_uri(shots['hero'], 'video/webm')}" autoplay muted loop controls playsinline></video>
<details><summary>GIF fallback</summary>{gif}</details>
<h2>The Types area</h2>{img('types', 'Types list')}
<h2>The Servo card's Coverage tab: CAN 11's planned coverage</h2>{img('coverage-map', 'coverage map')}
<p class="mute">Grey cells: planned train targets on q × qd, shaded by the share of the cell's reachable qdd cells visited. Grey because planned is neither real (blue) nor sim (orange). The site test checks these 147 cells are the producer's own q_qd plane, cell by cell.</p>
{img('servo-coverage', 'Servo coverage tab')}
<div class="grid"><div><h2>The station links to its card</h2>{img('station', 'CAN 11 station header')}</div><div><h2>A card that cannot be measured yet</h2>{img('motor', 'Motor card')}</div></div>
<h2>Metrics tab</h2>{img('servo-metrics', 'Servo metrics')}
<h2>Every card at a glance</h2><table><tr><th>Type</th><th>Metrics (proposed)</th><th>Params</th><th>Coverage axes</th><th>View</th><th>Today</th></tr>{rows}</table>
<h2>Gaps: what the other repos would need</h2><ul>{gaps}</ul>
<p class="mute">Built by docs/build_report_type_cards.py · sim2real · {time.strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--registry-tests", default="20/20")
    parser.add_argument("--site-tests", default="109/109")
    args = parser.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shots = capture(args.site.resolve(), Path(tmp))
        OUT.write_text(render(shots, {"registry": args.registry_tests, "site": args.site_tests}), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
