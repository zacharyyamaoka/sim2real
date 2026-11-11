"""The media dashboards report (2026-11-07): the cards' renders, the run page's 3D link, the camera clip beside the twin's render, and
the lines that say what you are looking at.

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs python /home/bam/sim2real/site/build.py
    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs --with playwright python /home/bam/sim2real/docs/build_report_media_dashboards.py --site-tests /abs/site-test.log

Serves a built site (default ~/.cache/sim2real/site) with `python3 -m http.server` on a free port in 4711-4799 (never 4700, Zach's) and
stops it by the PID it started; records the click-through landing -> the oracle cards -> the rack's tile -> its page -> a run the camera
filmed (Play: the camera and the twin's render on the plots' clock, then the link in 3D); takes stills; re-encodes the video (H.264) with a
1 fps GIF fallback; writes one self-contained page to /home/bam/sim2real/reports/media/media-dashboards-2026-11-07/report.html
(reports/media/ is gitignored). Every count on the page is read from the media index and the site's build record, never typed.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "site" / "tests"))

from test_site_flow import EXE, free_port, camera_runs  # noqa: E402

OUT = Path("/home/bam/sim2real/reports/media/media-dashboards-2026-11-07/report.html")
SITE = Path.home() / ".cache" / "sim2real" / "site"
DEP = "one-dof-test-rack"
T2_RUN = "2026-10-28~t2~heldout_can12~runs~s18_can12_sine"
MIME = {".webp": "image/webp", ".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".mp4": "video/mp4"}


def data_uri(path: Path, mime: str | None = None) -> str:
    return f"data:{mime or MIME[path.suffix]};base64,{base64.b64encode(path.read_bytes()).decode()}"


def esc(x) -> str:
    return html.escape(str(x))


def unstick(page) -> None:
    page.add_style_tag(content="header.top, .top { position: static !important; }")


def clip_run(site: Path, index: dict) -> str:
    """The run the hero plays: CAN 14's longest filmed waypoints run under 20 s (its tag sits mid-frame on the GIM43 plate, in the camera's
    best light; CAN 11's link is at the other camera's edge), else the longest filmed run a model replayed (the site test's pick)."""
    data = site / "data" / DEP
    expected = {k: v for k, v in camera_runs(data).items() if (index.get("runs", {}).get(k) or {}).get("media")}
    swing = sorted((r for r, (row, _s, _p) in expected.items() if row["device"] == "CAN 14" and row["kind"] == "waypoints" and row["duration_s"] < 20),
                   key=lambda r: -expected[r][0]["duration_s"])
    with_models = sorted((r for r, (row, _s, _p) in expected.items() if row["models"]), key=lambda r: -expected[r][0]["duration_s"])
    return (swing or with_models or sorted(expected, key=lambda r: -expected[r][0]["duration_s"]))[0]


def seek(page, t: float) -> None:
    page.evaluate("""(t) => { const d = document.querySelector('[role=tabpanel][data-tab=playback] data-dashboard'); if (d && d.clock) { d.clock.pause(); d.clock.seek(t); } }""", t)


def capture(site: Path, media: Path, run: str) -> dict:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(site)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    shots: dict[str, Path] = {}
    try:
        time.sleep(0.8)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EXE)
            # the hero: landing -> the cards' renders -> the rack's tile -> its page -> a filmed run: Play, the clips and the 3D link
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(media), record_video_size={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.goto(f"{base}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(1200)
            page.locator("#oracle").scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            page.wait_for_timeout(700)
            tile = page.locator(f"a.tile[href='/{DEP}/']").first
            tile.hover()
            page.wait_for_timeout(400)
            tile.click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(1600)
            page.goto(f"{base}/{DEP}/runs/{run}/")
            page.wait_for_load_state("load")
            video_el = page.locator("[role=tabpanel][data-tab=playback] video[data-t0]").first
            video_el.wait_for(timeout=30000)
            # the playback bar and the two clips in one view while it plays (the clips sit right under the bar)
            page.evaluate("""() => { const v = document.querySelector('[role=tabpanel][data-tab=playback] video[data-t0]');
                const bar = document.querySelector('.dv-pb-time'); const top = Math.min(bar.getBoundingClientRect().top, v.getBoundingClientRect().top);
                window.scrollBy(0, top - 70); }""")
            page.wait_for_function("() => [...document.querySelectorAll('[role=tabpanel][data-tab=playback] video[data-t0]')].every((v) => v.readyState >= 2)", timeout=30000)
            page.wait_for_timeout(800)
            page.locator("button[aria-label*='Play' i]").first.click()
            page.wait_for_timeout(5500)
            page.locator(".dd-panel").filter(has=page.locator(".dd-panel-h:has-text('Output link · 3D in its joint frame')")).first.scroll_into_view_if_needed()
            page.wait_for_timeout(3200)
            page.locator("button[aria-label*='Pause' i]").first.click()
            page.wait_for_timeout(400)
            video = Path(page.video.path())
            ctx.close()

            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.goto(f"{base}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)
            shots["home"] = media / "home.png"
            page.screenshot(path=str(shots["home"]))
            unstick(page)
            page.locator("#oracle").scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
            shots["cards"] = media / "cards.png"
            page.locator("#oracle .s2r-ex-grid").screenshot(path=str(shots["cards"]))
            shots["card"] = media / "card.png"
            page.locator("#oracle article[data-example=dual_arm_cell]").screenshot(path=str(shots["card"]))
            page.goto(f"{base}/sysid/pendulum_can11/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(1200)
            shots["sysid"] = media / "sysid.png"
            page.screenshot(path=str(shots["sysid"]))
            page.goto(f"{base}/{DEP}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)
            shots["deployment"] = media / "deployment.png"
            page.screenshot(path=str(shots["deployment"]))
            # the filmed run: the what line, then the camera and the render at one instant, then the 3D link
            page.goto(f"{base}/{DEP}/runs/{run}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)
            shots["run-top"] = media / "run-top.png"
            page.screenshot(path=str(shots["run-top"]))
            unstick(page)
            page.locator("[role=tabpanel][data-tab=playback] video[data-t0]").first.wait_for(timeout=30000)
            page.locator("[role=tabpanel][data-tab=playback] video[data-t0]").first.scroll_into_view_if_needed()
            page.wait_for_function("() => [...document.querySelectorAll('[role=tabpanel][data-tab=playback] video[data-t0]')].every((v) => v.readyState >= 2)", timeout=30000)
            clock = page.evaluate("() => { const c = document.querySelector('[role=tabpanel][data-tab=playback] data-dashboard').clock; return [c.start, c.end]; }")
            seek(page, round(clock[0] + 0.55 * (clock[1] - clock[0]), 2))
            page.wait_for_timeout(1500)
            pair = page.locator(".dd-panel").filter(has=page.locator(".dd-panel-h:has-text('Camera · real')")).first
            box_a = pair.bounding_box()
            box_b = page.locator(".dd-panel").filter(has=page.locator(".dd-panel-h:has-text('Twin render · MuJoCo')")).first.bounding_box()
            shots["pair"] = media / "pair.png"
            page.screenshot(path=str(shots["pair"]), full_page=True, clip={"x": box_a["x"] - 4, "y": box_a["y"] + page.evaluate("scrollY") - 4,
                                                                            "width": box_b["x"] + box_b["width"] - box_a["x"] + 8, "height": max(box_a["height"], box_b["height"]) + 8})
            three = page.locator(".dd-panel").filter(has=page.locator(".dd-panel-h:has-text('Output link · 3D in its joint frame')")).first
            three.scroll_into_view_if_needed()
            page.wait_for_timeout(2500)
            shots["three-clip"] = media / "three-clip.png"
            three.screenshot(path=str(shots["three-clip"]))
            # the run with four models: the 3D link at an instant where they part, and the models in words
            page.goto(f"{base}/{DEP}/runs/{T2_RUN}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(2000)
            unstick(page)
            three = page.locator(".dd-panel").filter(has=page.locator(".dd-panel-h:has-text('Output link · 3D in its joint frame')")).first
            three.scroll_into_view_if_needed()
            page.wait_for_function("() => [...document.querySelectorAll('.dv-scene3d')].some((e) => e.scene3d && e.scene3d.robot().state === 'ready')", timeout=45000)
            seek(page, 3.2)
            page.wait_for_timeout(2000)
            shots["three-models"] = media / "three-models.png"
            three.screenshot(path=str(shots["three-models"]))
            models = page.locator("#models")
            models.scroll_into_view_if_needed()
            page.wait_for_timeout(600)
            shots["models"] = media / "models.png"
            models.screenshot(path=str(shots["models"]))
            ctx.close()
            # the components, each mounted alone for its entity (site/components.py; the shelf the run page's redesign takes them from)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"{base}/components/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(6000)
            unstick(page)
            shots["components"] = media / "components.png"
            page.screenshot(path=str(shots["components"]), full_page=True)
            page.close()
            phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            page = phone.new_page()
            page.goto(f"{base}/{DEP}/runs/{run}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(2500)
            page.locator("[role=tabpanel][data-tab=playback] video[data-t0]").first.scroll_into_view_if_needed()
            page.wait_for_timeout(2000)
            shots["phone"] = media / "phone.png"
            page.screenshot(path=str(shots["phone"]))
            phone.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    # WHY one lossy pass to WebP (<= 1000 px wide): the page stays near the desktop preview's ~1.9 MB media-page limit
    for name, path in list(shots.items()):
        webp = path.with_suffix(".webp")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-vf", "scale='min(1000,iw)':-1", "-c:v", "libwebp", "-quality", "70",
                        "-compression_level", "6", str(webp)], check=True)
        shots[name] = webp
    mp4 = media / "hero.mp4"
    # WHY twice the speed: on a shared, loaded machine the pages take their time to load; at 2x the click-through stays near 20 s
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", "setpts=PTS/2,fps=12,scale=880:-2", "-c:v", "libx264", "-crf", "34",
                    "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    shots["hero"] = mp4
    gif = media / "hero.gif"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                    "setpts=PTS/2,fps=1,scale=320:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=24[p];[b][p]paletteuse=dither=none", str(gif)], check=False)
    if gif.is_file():
        shots["gif"] = gif
    return shots


def test_count(value: str | None) -> str:
    if not value or not Path(value).is_file():
        return value or "not given"
    lines = Path(value).read_text(encoding="utf-8", errors="replace").splitlines()
    passes, fails = sum(x.startswith("PASS ") for x in lines), sum(x.startswith("FAIL ") for x in lines)
    return f"{passes} pass, {fails} fail"


def fails_of(value: str | None) -> list[str]:
    if not value or not Path(value).is_file():
        return []
    return [x[5:] for x in Path(value).read_text(encoding="utf-8", errors="replace").splitlines() if x.startswith("FAIL ")]


def mb(n: float) -> str:
    return f"{n / 1e6:,.1f} MB"


def render(shots: dict, index: dict, build: dict, run: str, tests: dict, shas: dict) -> str:
    img = lambda k, alt: f'<img src="{data_uri(shots[k])}" alt="{esc(alt)}" loading="lazy">' if k in shots else ""  # noqa: E731
    runs = index.get("runs", {})
    clips = {k: v for k, v in runs.items() if v.get("media")}
    clip_bytes = sum(v.get("bytes", 0) for v in clips.values())
    links_bytes = sum((Path(index["_root"]) / v["links"]).stat().st_size for v in runs.values() if v.get("links"))
    why = Counter(re_why(v.get("why_none")) for v in runs.values() if not v.get("media"))
    scenes = "".join(f"<tr><td><b>{esc(s['id'])}</b></td><td>{esc(s['what'])}</td><td class='mono'>{esc(', '.join(Path(m['path']).name + ' ' + m['sha256'][:10] for m in s['models']))}</td>"
                     f"<td>{s['width']}×{s['height']}, {s['bytes'] / 1e3:,.0f} kB</td></tr>" for s in index.get("scenes", []))
    stations = "".join(f"<tr><td><b>{esc(s['device'])}</b></td><td>{esc(s['drawn_from'])}</td><td>{s['triangles']:,} triangles, {s['bytes'] / 1e3:,.0f} kB</td></tr>"
                       for s in index.get("stations", []))
    why_rows = "".join(f"<tr><td>{esc(k)}</td><td>{n:,}</td></tr>" for k, n in why.most_common())
    models = index.get("models", {})
    with_params = sum(1 for m in models.values() if m.get("parameters"))
    gif = (f'<details><summary>GIF fallback</summary><img src="{data_uri(shots["gif"], "image/gif")}" alt="the click-through as a GIF"></details>' if "gif" in shots else "")
    failed = "".join(f"<li>{esc(f[:260])}</li>" for f in tests.get("fails", []))
    sha_line = " · ".join(f"<code>{esc(k)}</code> {esc(v)}" for k, v in shas.items())
    m = build.get("media") or {}
    load = next((st.get("load") for st in index.get("stations", []) if st["station"] == "can11"), None) or {}
    can11 = f"{load.get('mass_kg', 0):.2g} kg at {load.get('radius_m', 0) * 1e3:.0f} mm from the axis" if load else "its twin's load"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Media dashboards</title><style>
:root{{--bg:#fff;--fg:#1d1f23;--mute:#5d6470;--line:#e3e5e8;--chip:#eef1f4;--ok:#1d7a3a;--no:#b42318;--real:#2a78d6;--sim:#eb6834}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8eaed;--mute:#9aa0aa;--line:#2c3036;--chip:#22262c;--ok:#4cc06e;--no:#f2685c}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;max-width:1120px;margin:0 auto;padding:24px 16px}}
img,video{{max-width:100%;border:1px solid var(--line);border-radius:6px;display:block}} figure{{margin:18px 0}} figcaption{{color:var(--mute);font-size:13px;margin-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}} td,th{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
.scroll{{overflow-x:auto}} .mute{{color:var(--mute)}} .mono{{font-family:ui-monospace,monospace;font-size:12px}} h2{{margin-top:38px}}
.verdict{{font-size:17px}} .pill{{display:inline-block;background:var(--chip);border-radius:10px;padding:0 8px;font-size:12.5px;margin-right:4px}} code{{font-size:13px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} @media (max-width:760px){{.two{{grid-template-columns:1fr}}}} ul.tight li{{margin:3px 0}}
.real{{color:var(--real);font-weight:600}} .sim{{color:var(--sim);font-weight:600}}
</style></head><body>
<p class="verdict"><b>sim2real's cards open with a MuJoCo render of their own MJCF, every run page shows its station's link in 3D
(<span class="real">real</span>, each <span class="sim">model</span> and the command posed on the plots' clock), and the {len(clips):,} runs whose
session filmed their station play that camera beside the twin's render</b> — on <code>main</code> @ <code>{esc(shas.get('main', ''))}</code>; served on
:4700 after the rebuild. The other {len(runs) - len(clips):,} runs have no video: their sessions filmed no camera (no schedule session since 10-28 records one;
the recorder holds frames in RAM, 120 s at most), or not the one that sees their station. The plan for that is below and in
<code>docs/plan-camera-per-run-2026-11-07.md</code>.</p>
<p><span class="pill">site test {esc(tests['site'])}</span><span class="pill">{len(index.get('scenes', []))} renders</span><span class="pill">{len(index.get('stations', []))} station links</span>
<span class="pill">{m.get('links', 0):,} runs with link poses</span><span class="pill">{len(clips):,} runs with clips ({mb(clip_bytes)})</span><span class="pill">media {mb(index.get('counts', {}).get('bytes', 0))}, never in git</span></p>

<h2>Hero: the landing page → the rack's tile → a run the camera filmed (Play) → the link in 3D</h2>
<video src="{data_uri(shots['hero'], 'video/mp4')}" autoplay muted loop controls playsinline></video>{gif}
<p class="mute">The run: <code>{esc(run)}</code>. Recorded headless from the built site served on a free port (never :4700); shown at twice the speed.</p>

<h2>1. An image of the deployment on every card</h2>
<p>Each oracle example's card, and its page, opens with MuJoCo's offscreen render (EGL, MuJoCo {esc(index.get('renderer', {}).get('mujoco'))}) of the
example's own MJCF, composed exactly as sysid composes it (<code>sysid.describe.Description.spec</code>); the rack's tile and page show its cad2robot payload.
The picture adds only a floor, a light sky and a key light; for CAN 11, whose twin MJCF is a bare hinge with no visual geometry, it draws the link from the twin's
own load ({can11}). Each render names its files and their sha256 (the site test checks them against the files the descriptions name).</p>
<figure><figcaption>The landing page: the rack's tile and the six examples' tiles are their renders</figcaption>{img('home', 'home')}</figure>
<figure><figcaption>The oracle cards, each opening with its render and a line that says what you are looking at</figcaption>{img('cards', 'cards')}</figure>
<div class="two"><figure><figcaption>One card (the dual-arm cell, its head camera's body drawn)</figcaption>{img('card', 'card')}</figure>
<figure><figcaption>An example's page: the render on top</figcaption>{img('sysid', 'sysid page')}</figure></div>
<figure><figcaption>The rack's page: its CAD render beside what the page shows</figcaption>{img('deployment', 'deployment page')}</figure>
<div class="scroll"><table><thead><tr><th>card</th><th>what the picture is</th><th>files (sha256)</th><th>image</th></tr></thead><tbody>{scenes}</tbody></table></div>

<h2>2. A 3D view on every run page</h2>
<p>The run's existing 3D card (data-ui's <code>trajectory3d</code>) now also poses the station's output link at the clock's t for every series:
<span class="real">real</span> solid, each <span class="sim">model</span> translucent, the command a grey ghost, with the 100 mm marker's paths as before; scrub the
playback and they turn. The link poses (<code>links.json</code>, data-ui's robotics contract table) are a turn about the joint axis by each series' own q,
every {esc('≤ 30 Hz')} row a sample of the run (the site test recomputes them from the samples); the link (a GLB, one node) is drawn from the station's twin MJCF,
since no station's joint is in the CAD export yet. The frame is the joint's own with its y up, so a twin's gravity load hangs down.</p>
<div class="two"><figure><figcaption>CAN 12's 10-28 held-out sine: real, the command and four friction models on one link</figcaption>{img('three-models', '3D with models')}</figure>
<figure><figcaption>The filmed run's 3D card</figcaption>{img('three-clip', '3D on the filmed run')}</figure></div>
<div class="scroll"><table><thead><tr><th>station</th><th>its link, drawn from</th><th>GLB</th></tr></thead><tbody>{stations}</tbody></table></div>

<h2>3. The camera beside the twin's render, on one clock</h2>
<p>Where a run's session recorded the D405 that watches its station (bam_rack_twin's camera map), the session's recording is cut onto the run's clock: each frame
is the camera frame nearest a uniform 30 fps grid from 0.3 s before the run to 0.3 s after (data-ui gallery's rule), 640 × 360, brightened on its luma as the tag
detector sees it, the station's tag boxed in blue. Beside it, MuJoCo renders the station's link on the same frames: real at its encoder angle, each model at its
replayed angle, the command a ghost. Both are data-ui <code>video</code> cards following the run's clock; the site test seeks and plays them in the browser.
The render is a front view of the joint's own frame, not the camera's calibrated pinhole, so the two are side by side, never overlaid.</p>
<figure><figcaption>The camera (left) and the twin's render (right) at one instant of <code>{esc(run)}</code></figcaption>{img('pair', 'camera and render')}</figure>
<div class="two"><figure><figcaption>The filmed run's page: what you are looking at, above the playback</figcaption>{img('run-top', 'run page top')}</figure>
<figure><figcaption>390 px: the two clips stack, no sideways scroll</figcaption>{img('phone', 'phone')}</figure></div>
<p>{len(clips):,} runs have clips ({mb(clip_bytes)} for both clips of every run, under 150 kB/s each). The other {sum(why.values()):,}:</p>
<div class="scroll"><table><thead><tr><th>why a run has no clip</th><th>runs</th></tr></thead><tbody>{why_rows}</tbody></table></div>

<h2>4. More explanatory</h2>
<ul class="tight"><li>Every card, the rack's page and every run page carry a <b>"What you're looking at"</b> line: the station and motion, every series by name and colour, what the
3D card and the clips show, and, where there is no video, why.</li>
<li>Each oracle example states <b>what its model is</b> (its MJCF and the type-card rungs sysid fits) above its table of true / nominal / recovered values.</li>
<li>Each run page lists <b>the models it plays</b>, each with a sentence and its parameters: {with_params} of the {len(models)} distinct models are read from the twin's
own MJCF (inertia, viscous, LuGre's five, the gear gap, the gravity load) or, for the 10-28 study's four friction models, the identification file's points. Real
hardware has no hidden truth, so a rack model's table has no "true" column.</li></ul>
<figure><figcaption>Models in this run (CAN 12's held-out sine)</figcaption>{img('models', 'models section')}</figure>

<h2>5. Components scoped to an entity (for the run page's redesign)</h2>
<p>The 3D view, the clips and the "what you're looking at" words are components of their own (<code>site/components.py</code>), each scoped to an
entity: <code>joint_3d</code> (a joint: its station's link model, its frame's poses, its link poses), <code>camera_clip</code> (a camera: its clip of the
run), <code>joint_render</code> (a joint: MuJoCo's render of its link), <code>what_joint</code> / <code>what_camera</code> (the words). Each is a data-ui
<code>.base</code> fragment whose every dataset is the run's and filtered to its entity; <code>compose()</code> drops it into a page, and
<code>views/components/&lt;name&gt;.base</code> is the same component as a dashboard of its own (its own clock over its entity's samples), its entity in
the URL's query. The run page is composed of exactly these views; <code>/components/</code> mounts each one alone for a real entity. A page with an
entity tree on the left drops them in at the level picked; an arm is <code>joint_3d</code> with its links once a producer writes them.</p>
<figure><figcaption>/components/: each component mounted alone for its entity</figcaption>{img('components', 'components page')}</figure>

<h2>Stock parts used</h2>
<div class="scroll"><table><thead><tr><th>element</th><th>stock part</th><th>ours</th></tr></thead><tbody>
<tr><td>Card renders</td><td>MuJoCo 3.11 offscreen <code>Renderer</code> (EGL), <code>MjSpec</code>; <code>sysid.describe.Description.spec</code> composes each example; the cad2robot payload's MJCF</td><td>the staging (floor, sky, key light) and framing</td></tr>
<tr><td>3D view</td><td>data-ui <code>trajectory3d</code> with <code>robots</code> (three.js GLTFLoader, one robot per series, CONTRACT §32), the robotics contract's <code>links</code> table</td><td>the link poses (a turn by q) and the link drawn from the twin's numbers</td></tr>
<tr><td>Link model</td><td>glTF 2.0 binary as data-ui's gallery <code>build_robot.py</code> writes it</td><td>its geometry (disc, marker, the twin's load)</td></tr>
<tr><td>Clips on the clock</td><td>data-ui <code>video</code> cards (<code>followVideo</code>: exact seek paused, rate nudge playing), PEP 0005 media rows</td><td>—</td></tr>
<tr><td>The cut</td><td>data-ui gallery <code>build_replays.py</code>'s nearest-stamp 30 fps rule; bam_rack_twin's camera map (<code>docs/dataset_clips.py</code> VIEW) and ArUco detector; ffmpeg / libx264</td><td>one decode pass per session for all its runs</td></tr>
<tr><td>Twin render video</td><td>MuJoCo offscreen <code>Renderer</code>; ffmpeg</td><td>the station scene (plate, motor, one hinge per series)</td></tr>
<tr><td>traj_compare</td><td>the reference for the side-by-side camera card and the posed robot (its RobotDisplay split: poses in Python, the viewer only poses)</td><td>not imported: the site is data-ui's</td></tr>
</tbody></table></div>

<h2>The recorder: a compressed video per run from now on (a plan, not built)</h2>
<p>bam_ws's worktree for this lane was on <code>claude/otherday-heldout-1107</code> with a peer's uncommitted changes, so per the brief nothing in bam_ws was
written. What the archive shows: <code>bam_rack_twin.hardware.record</code> already writes an H.264 mp4 per camera beside its raw npz, but holds every frame in RAM
(120 s at most), so no schedule session since 10-28 names a camera. The plan (<code>docs/plan-camera-per-run-2026-11-07.md</code>): an <code>--mp4-only</code>
recorder mode with no RAM ceiling, a <code>camera_mode</code> in session plans (schedule sessions in <code>mp4</code>), and the per-run cut moved next to each run's
npz, each test-first. Needs Zach: whether schedule sessions may drop the raw grey frames (recommended: yes for schedule sessions, no for calibration sessions).</p>

<h2>Decided, left, not done</h2>
<ul class="tight">
<li>Decided: media are a cache folder (<code>~/.cache/sim2real/media</code>, {mb(index.get('counts', {}).get('bytes', 0))}), linked at <code>/media/</code> by
<code>site/build.py</code>; only builder code is committed. Undo: <code>git revert</code> the media commits (the site builds without them as before).</li>
<li>Decided: clips side by side, not overlaid (the render is not the camera's calibrated view; the as-built camera poses are valid only before 10-21 18:00).</li>
<li>Decided: the whole camera view with the tag boxed, not a crop (bam_rack_twin's own rule: a crop missed CAN 11's link).</li>
<li>Decided: the 3D card's frame is the joint's own with y up (the twins' gravity is their −y).</li>
<li>Left: an overlay of camera and render needs each day's camera pose (calibration); a per-run sign check of the render against the camera's tag angle.</li>
<li>Left: the model tables for <code>twin · full</code>, <code>refit R1</code> and <code>twin A / C1</code> where no twin scene carries their digest.</li>
{('<li>The site test\'s failures, every one a pre-existing data-freshness check (the archive moved on today; none touches the media):<ul>' + failed + '</ul></li>') if failed else ''}
</ul>
<p class="mute">{sha_line}</p>
</body></html>"""


def re_why(text: str | None) -> str:
    """Group a run's why-no-clip by its kind (the serial and station named in it dropped)."""
    import re  # noqa: PLC0415

    text = text or "not cut"
    text = re.sub(r"camera \d+, the one that sees CAN \d+", "the camera that sees its station", text)
    text = re.sub(r"no camera sees CAN \d+", "no camera sees its station", text)
    text = re.sub(r"a [\d.]+ s hole", "a hole", text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, default=SITE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--site-tests", help="the site test's log (its PASS / FAIL lines are counted)")
    args = parser.parse_args()
    site = args.site.resolve()
    media = args.out.parent
    media.mkdir(parents=True, exist_ok=True)
    root = (site / "media").resolve()
    index = json.loads((root / "index.json").read_text())
    index["_root"] = str(root)
    build = json.loads((site / ".sim2real-build.json").read_text())
    run = clip_run(site, index)
    shots = capture(site, media, run)
    shas = {"main": subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
            "branch": subprocess.run(["git", "-C", str(REPO), "branch", "--show-current"], capture_output=True, text=True).stdout.strip(),
            "media index": index.get("written_at", ""), "site build": str(site)}
    tests = {"site": test_count(args.site_tests), "fails": fails_of(args.site_tests)}
    args.out.write_text(render(shots, index, build, run, tests, shas), encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
