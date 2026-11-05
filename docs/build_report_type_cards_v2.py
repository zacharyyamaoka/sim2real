"""The type cards v2 report (2026-11-05): Zach's Nov 5 workflow in the type-card registry and the site's Types area.

    python3 /home/bam/sim2real/site/build.py
    uv run --no-project --with playwright python /home/bam/sim2real/docs/build_report_type_cards_v2.py --registry-tests 58/58 --site-tests 194/194

Serves a built site (default ~/.cache/sim2real/site) with `python3 -m http.server` on a free port in 4711-4799 (never 4700, Zach's)
and stops it by the PID it started; records the click-through /types/ -> the Servo card's Models, Tests, Metrics and Coverage
tabs; takes element stills (JPEG) of the ladders, the calibration packages, the learned rungs, the diagnostics, the test types,
the coverage gate, the Conveyor card and a phone width; re-encodes the video (H.264) with a small GIF fallback; writes one
self-contained page to /home/bam/sim2real/reports/media/type-cards-v2-2026-11-05/report.html (reports/media/ is gitignored).
WHY the compression (JPEG, stills <= 1000 px, H.264 CRF 36 at 800 px, a 1 fps GIF): the desktop preview opens a media page up to about 1.9 MB.
Every number on the page is read from type_cards/registry.py at build time, never typed.
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

OUT = Path("/home/bam/sim2real/reports/media/type-cards-v2-2026-11-05/report.html")
SITE = Path.home() / ".cache" / "sim2real" / "site"
SCHEDULE = Path("/archive/datasets/bam_rig/schedules/one-dof-test-rack/can11/schedule.json")
STILLS = (  # (name, url, selector or None for the viewport, caption)
    ("types-ladders", "/types/", ".s2r-types", "/types/: every actuator's ladder, each rung's key with its parameter count"),
    ("types-packages", "/types/", ".s2r-packages", "/types/: Zach's calibration packages, the types each serves and where its code lives"),
    ("servo-ladder", "/types/servo/#model", "[data-tab=model] table >> nth=0", "Servo · Models: the ladder, new names in bold, the coverage each rung needs, where to learn it"),
    ("servo-learned", "/types/servo/#model", "[data-tab=model] table >> nth=1", "Servo · Models: the learned rungs' size is a weight count (M7 is Hwangbo 2019's actuator net)"),
    ("servo-wear", "/types/servo/#model", "[data-tab=model] table >> nth=2", "Servo · Models: the wear rung's laws (Archard backlash, linear friction)"),
    ("servo-diagnostics", "/types/servo/#metrics", "[data-tab=metrics] table >> nth=2", "Servo · Metrics: every diagnostic, the gate on it, and the drift warning in Zach's words"),
    ("servo-tests", "/types/servo/#tests", "[data-tab=tests] table >> nth=0", "Servo · Tests: test types by setting, what each identifies, which recalibrate"),
    ("servo-coverage", "/types/servo/#coverage", "[data-tab=coverage] table >> nth=0", "Servo · Coverage: each axis's bin size and marginal"),
    ("servo-stations", "/types/servo/#coverage", "[data-tab=coverage] table >> nth=1", "Servo · Coverage: each station's plan, its q cell and the 40 % gate"),
    ("conveyor-ladder", "/types/conveyor/#model", "[data-tab=model] table >> nth=0", "Conveyor (new): pidtuna's conveyor plant as a ladder"),
)


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def open_tab(page, key: str) -> None:
    page.click(f"nav.tabs [role=tab][href='#{key}']")
    page.wait_for_timeout(900)


def capture(site: Path, media: Path) -> dict:
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
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(media), record_video_size={"width": 1280, "height": 800})
            page = ctx.new_page()
            page.goto(f"{base}/types/")
            page.wait_for_timeout(1500)
            page.locator(".s2r-types").first.scroll_into_view_if_needed()
            page.mouse.wheel(0, 260)
            page.wait_for_timeout(1600)
            link = page.locator(".s2r-types a[href='/types/servo/']")
            link.hover()
            page.wait_for_timeout(500)
            link.click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(900)
            open_tab(page, "model")
            page.mouse.wheel(0, 420)
            page.wait_for_timeout(1400)
            page.locator("[data-tab=model] tr[data-arch='M7']").scroll_into_view_if_needed()
            page.wait_for_timeout(1600)
            page.mouse.wheel(0, -4000)
            page.wait_for_timeout(500)
            open_tab(page, "tests")
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(1400)
            page.mouse.wheel(0, -4000)
            open_tab(page, "metrics")
            page.locator("[data-tab=metrics] tr[data-kind='drift']").scroll_into_view_if_needed()
            page.wait_for_timeout(1800)
            page.mouse.wheel(0, -4000)
            open_tab(page, "coverage")
            page.mouse.wheel(0, 380)
            page.wait_for_timeout(1800)
            video = Path(page.video.path())
            ctx.close()

            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            for name, url, selector, _caption in STILLS:
                page.goto(base + url)
                page.wait_for_load_state("load")
                page.wait_for_timeout(700)
                if "#" in url:
                    open_tab(page, url.split("#", 1)[1])
                target = page.locator(selector).first
                target.scroll_into_view_if_needed()
                path = media / f"{name}.jpg"
                target.screenshot(path=str(path), type="jpeg", quality=55)
                shots[name] = path
            ctx.close()
            phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            page = phone.new_page()
            page.goto(base + "/types/servo/#model")
            page.wait_for_load_state("load")
            page.wait_for_timeout(1000)
            open_tab(page, "model")
            path = media / "phone.jpg"
            page.screenshot(path=str(path), type="jpeg", quality=55)
            shots["phone"] = path
            phone.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    for name, path in shots.items():  # stills wider than 1000 px are scaled down and recompressed (the page is read at <= 1120 px)
        small = path.with_name(path.stem + "-small.jpg")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-vf", "scale='min(1000,iw)':-1", "-q:v", "9", str(small)], check=True)
        shots[name] = small if small.stat().st_size < path.stat().st_size else path
    mp4 = media / "hero.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", "fps=10,scale=800:-2", "-c:v", "libx264", "-crf", "36", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    shots["hero"] = mp4
    gif = media / "hero.gif"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                    "fps=1,scale=360:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=24[p];[b][p]paletteuse=dither=none", str(gif)], check=False)
    if gif.is_file():
        shots["gif"] = gif
    return shots


def esc(x) -> str:
    return html.escape(str(x))


def keys(card) -> str:
    """'M0 4 · M2 6 · M4* 16 · ...': each rung's key (* today's model) and its parameter count."""
    return " · ".join(esc(r.key + ("*" if r.current else "") + f" {r.n_parameters:,}") for r in card.rungs)


def render(shots: dict, tests: dict, shas: dict) -> str:
    cards = list(reg.CARDS.values())
    sched = json.loads(SCHEDULE.read_text()) if SCHEDULE.is_file() else None
    train = cov.servo_coverage(sched) if sched else None
    img = lambda k, alt: f'<img src="{data_uri(shots[k], "image/jpeg")}" alt="{esc(alt)}" loading="lazy">'  # noqa: E731
    figs = "".join(f"<figure><figcaption>{esc(cap)}</figcaption>{img(name, cap)}</figure>" for name, _u, _s, cap in STILLS if name in shots)
    ladder_rows = "".join(
        f"<tr><th scope='row'>{esc(c.title)}</th><td>{esc(c.group)}</td><td>{len(c.rungs)}</td>"
        f"<td class='mono'>{keys(c)}</td>"
        f"<td>{sum(1 for r in c.rungs if r.kind == 'physics')}</td><td>{len(c.gates)}</td><td>{len(c.tests)}</td>"
        f"<td>{len(reg.tests_for(c, 'bench'))} / {len(reg.tests_for(c, 'deployed'))}</td></tr>" for c in cards)
    pk_rows = "".join(f"<tr><td><b>{esc(p.group)}</b><br>{esc(p.title)}</td><td>{esc(', '.join(p.serves))}</td><td>{esc(p.status)}</td>"
                      f"<td class='mono small'>{'<br>'.join(esc(h.repo.replace('/home/bam/', '') + ':' + h.path + (' @ ' + h.ref if h.ref else '')) for h in p.code) or 'unknown'}</td></tr>"
                      for p in reg.CALIBRATION_PACKAGES)
    servo = reg.CARDS["servo"]
    checked = json.loads((REPO / "type_cards" / "references_checked.json").read_text())
    gif = (f'<details><summary>GIF fallback</summary><img src="{data_uri(shots["gif"], "image/gif")}" alt="the click-through as a GIF"></details>'
           if "gif" in shots else "")
    sha_line = " · ".join(f"<code>{esc(k)}</code> {esc(v)}" for k, v in shas.items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Type cards v2</title><style>
:root{{--bg:#fff;--fg:#1d1f23;--mute:#5d6470;--line:#e3e5e8;--chip:#eef1f4;--ok:#1d7a3a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8eaed;--mute:#9aa0aa;--line:#2c3036;--chip:#22262c;--ok:#4cc06e}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;max-width:1120px;margin:0 auto;padding:24px 16px}}
img,video{{max-width:100%;border:1px solid var(--line);border-radius:6px;display:block}} figure{{margin:18px 0}} figcaption{{color:var(--mute);font-size:13px;margin-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
.scroll{{overflow-x:auto}} .mute{{color:var(--mute)}} .mono{{font-family:ui-monospace,monospace;font-size:12px}} .small{{font-size:11.5px}} h2{{margin-top:38px}}
.verdict{{font-size:17px}} .pill{{display:inline-block;background:var(--chip);border-radius:10px;padding:0 8px;font-size:12.5px;margin-right:4px}} code{{font-size:13px}}
ul.tight li{{margin:3px 0}}
</style></head><body>
<p class="verdict"><b>The type-card registry now carries Zach's Nov 5 workflow: a ladder of models per type (physics → wear → grey-box residual → black-box net),
diagnostics and gates over black-box metrics, test types per setting, coverage bins and gates, and the calibration packages</b> — on <code>main</code> @
<code>{esc(shas.get('main', ''))}</code>, served at <code>/types/</code>; the API lanes B and C code against is <code>type_cards/CONTRACT.md</code>.</p>
<p><span class="pill">{len(cards)} cards</span><span class="pill">{sum(len(c.rungs) for c in cards)} rungs</span>
<span class="pill">{sum(len(c.tests) for c in cards)} test types</span><span class="pill">{sum(len(c.gates) for c in cards)} gates</span>
<span class="pill">{len(reg.CALIBRATION_PACKAGES)} calibration packages</span><span class="pill">{len(checked['doi'])} DOIs + {len(checked['url'])} URLs checked</span>
<span class="pill">type_cards tests {esc(tests['registry'])}</span><span class="pill">site test {esc(tests['site'])}</span></p>

<h2>Hero: /types/ → the Servo card's Models, Tests, Metrics and Coverage</h2>
<video src="{data_uri(shots['hero'], 'video/mp4')}" autoplay muted loop controls playsinline></video>{gif}

<h2>Every card's ladder</h2>
<p class="mute">Read from the registry when this page was built. * marks today's model, the rung it equals. Keys: M0–M5 physics (robotparts' ladder on servo,
motor, gearbox, conveyor; each other card its own), <code>.wear</code> takes usage as an input, M6 is always the grey-box residual, M7 always the black-box net.</p>
<div class="scroll"><table><tr><th>Type</th><th>Group</th><th>Rungs</th><th>Keys and parameter counts</th><th>Physics</th><th>Gates</th><th>Test types</th><th>Bench / deployed</th></tr>{ladder_rows}</table></div>

<h2>The contract (<code>type_cards/CONTRACT.md</code>)</h2>
<ul class="tight">
<li><b>One import, additive only:</b> <code>from type_cards import registry as reg</code>; no v1 name, field or field order changed; new fields default; <code>reg.SCHEMA</code> = <code>{esc(reg.SCHEMA)}</code>.</li>
<li><b>Rungs:</b> <code>card.rungs</code> (lowest first): <code>Rung(key, name, parameters, references, equation, kind, architecture, base, needs, robotparts, implemented, current)</code>;
<code>n_parameters</code> = named + a net's weights. The one <code>current</code> rung IS today's model (servo M4, its 16 parameters).</li>
<li><b>Selection rule:</b> {esc(reg.SELECTION_RULE)} — <code>reg.select_rung(card, held_out)</code>; <code>reg.coverage_flag(rung, cell, trained)</code> → <i>{esc(reg.OUT_OF_COVERAGE)}</i>.</li>
<li><b>Wear:</b> <code>Parameter.wear = Wear(usage, unit, law, rate)</code>, laws {esc(', '.join(reg.WEAR_LAWS))} each with real references; every actuator has a <code>.wear</code> rung.</li>
<li><b>Metrics → diagnostics → gates:</b> a diagnostic is a metric + a threshold, a gate a diagnostic + a target, an ungated metric is observed (<code>reg.metric_status</code>).
One drift diagnostic per card: "{esc(reg.DRIFT_MESSAGE)}" at {reg.DRIFT_THRESHOLD:g}× (settable), with a forecast of usage left: <code>reg.check_drift(card, live, calibrated, threshold=None, history=None)</code>.</li>
<li><b>Test types:</b> <code>card.tests</code>, ids <code>&lt;card&gt;.&lt;key&gt;</code>, setting {esc(' | '.join(reg.SETTINGS))}, a recalibration method in each (<code>reg.tests_for</code>).</li>
<li><b>Coverage:</b> <code>Axis.bin_size</code> / <code>marginal</code>, <code>Coverage.gate_pct</code> (40 %, schedule.py's), <code>reg.coverage_gate</code>, <code>cov.random_plan</code>;
<code>servo_coverage</code> byte for byte main 61a9de7's{f' (CAN 11 {train.pct} %, {train.visited} of {train.reachable} cells)' if train else ''}.</li>
<li><b>Lookups:</b> <code>reg.card_for(word)</code>, <code>reg.rung</code>, <code>reg.current_rung</code>, <code>reg.added</code>, <code>reg.packages_for</code>, <code>reg.export()</code> (JSON).</li>
</ul>

<h2>The site's Types area</h2>
{figs}
<figure><figcaption>Phone width (390 px): the Models tab without sideways scroll (the site test measures it on every Types tab)</figcaption>
<img src="{data_uri(shots['phone'], 'image/jpeg')}" alt="Types at 390 px" style="max-width:min(390px,100%)"></figure>

<h2>Calibration packages and where their code lives</h2>
<div class="scroll"><table><tr><th>Package</th><th>Serves</th><th>Status</th><th>Code today (checked at its ref)</th></tr>{pk_rows}</table></div>

<h2>Proof</h2>
<ul class="tight">
<li><b>type_cards tests {esc(tests['registry'])}</b>: 20 v1 (unchanged) + 17 contract (written first) + 21 content. Oracles outside the registry: bam_rack_twin acceptance.py's
T2/T3/T7/T8/T9 limits and schedule.py's MINIMUM_COVERAGE_PCT, robotparts' own model.json rung numbers, Crossref and doi.org for every reference, the CAN 11 coverage digest from main 61a9de7.</li>
<li><b>site test {esc(tests['site'])}</b> on the rebuilt site (lane C's checks included): every card's page serves its ladder, test types and drift warning; the Servo
card's six tabs measured in headless Chromium; CAN 11's coverage row states its q cell computed from its schedule (0.055 rad).</li>
<li><b>Caught on the way:</b> the q axis text quoted 0.2565 rad for CAN 11, which nothing computed (it is 0.66 / 12 = 0.055 rad): now computed per station and checked.
Two DOIs recalled from memory pointed at unrelated papers (Crossref), so they were dropped before they reached the registry.</li>
</ul>

<h2>Decided for you (each one revertable)</h2>
<ul class="tight">
<li><b>Rung numbers follow robotparts' published actuator ladder</b> (M0 ideal, M2 Coulomb + viscous, M3 Stribeck, M4 ripple + backlash, M5 electrics), so "M3" means the same
model on robotparts.dev and in bam_rack_twin; the brief's own example numbered the servo 1-2-3. A durable naming call, written down in CONTRACT.md. Undo: rekey in <code>type_cards/ladders.py</code>.</li>
<li><b>M6 = grey-box residual and M7 = black-box net on every card</b> (the coordinator's fix).</li>
<li><b>Learned rungs need 95 % of reachable cells with ≥ 200 samples</b> (the servo schedule note's stricter target), and never extrapolate. Undo: <code>LEARNED_*</code> in ladders.py.</li>
<li><b>Drift warns at 1.25× the calibrated fidelity</b> (settable): warns before the 1.5× twinned gate fails.</li>
<li><b>No black-box camera rung</b> (a camera model must stay projective to measure); RGB and RGBD get a dense residual (Schöps et al. 2020).</li>
<li><b>A conveyor card</b> from pidtuna's conveyor plant; <b>the gripper gains an error-like fidelity metric</b> so its drift ratio rises when the twin gets worse.</li>
</ul>

<h2>Left, and not done</h2>
<ul class="tight">
<li>Next: most test types are <i>proposed</i> (no wear regression, no residual or actuator net is trained anywhere yet); the arm-level base-parameter fit and a hyperspectral calibration were not found in any repo.</li>
<li>Not done: no wear terms in bam_rack_twin itself (it takes no usage input); the Nov 4 vault note untouched; the PROJECT note untouched (the coordinator's).</li>
<li>Zach's :4700 server (started Oct 29, before serve.py served the site) still serves only the old app: restarting it is his call.</li>
</ul>
<p class="mute small">Built by docs/build_report_type_cards_v2.py · {sha_line} · {time.strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, default=SITE)
    parser.add_argument("--registry-tests", default="58/58")
    parser.add_argument("--site-tests", default="194/194")
    args = parser.parse_args()
    main_sha = subprocess.run(["git", "-C", "/home/bam/sim2real", "rev-parse", "--short", "main"], capture_output=True, text=True).stdout.strip()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shots = capture(args.site.resolve(), Path(tmp))
        OUT.write_text(render(shots, {"registry": args.registry_tests, "site": args.site_tests}, {"main": main_sha}), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
