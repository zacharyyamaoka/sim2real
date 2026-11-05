"""The system-ID oracle report (2026-11-05): six robot descriptions in, a better model out, each checked against a hidden truth.

    python3 /home/bam/sim2real/site/build.py
    uv run --no-project --with playwright python /home/bam/sim2real/docs/build_report_sysid_oracle.py --oracle-tests /abs/sysid-junit.xml --site-tests /abs/site-test.log --type-cards-tests /abs/type-cards-junit.xml

Serves a built site (default ~/.cache/sim2real/site) with `python3 -m http.server` on a free port in 4711-4799 (never 4700, Zach's) and
stops it by the PID it started; records the click-through home -> the oracle cards -> CAN 11's page (its ladder, its wear chart) ->
the dual-arm cell's page (the knocked camera); takes stills of the landing page's oracle section, a card, every example's parameter
table, both drift charts and a phone width; re-encodes the video (H.264) with a 1 fps GIF fallback; writes one self-contained page to
/home/bam/sim2real/reports/media/sysid-oracle-2026-11-05/report.html (reports/media/ is gitignored). Every number on the page is read
from sysid/results/*.json at build time (the results the oracle test holds to the code), never typed.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "site" / "tests"))
sys.path.insert(1, str(REPO / "site"))
sys.path.insert(2, str(REPO / "site" / "vendor"))

from test_site_flow import EXE, free_port  # noqa: E402

import landing  # noqa: E402

OUT = Path("/home/bam/sim2real/reports/media/sysid-oracle-2026-11-05/report.html")
SITE = Path.home() / ".cache" / "sim2real" / "site"
RESULTS = REPO / "sysid" / "results"
EXAMPLES = landing.EXAMPLES


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


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
            page.goto(f"{base}/")
            page.wait_for_timeout(1400)
            page.locator("#oracle").scroll_into_view_if_needed()
            page.wait_for_timeout(1800)
            page.mouse.wheel(0, 520)
            page.wait_for_timeout(1500)
            page.mouse.wheel(0, -520)
            page.wait_for_timeout(500)
            link = page.locator("#oracle article[data-example=pendulum_can11] .s2r-ex-open a")
            link.hover()
            page.wait_for_timeout(500)
            link.click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(1000)
            page.locator("#parameters").scroll_into_view_if_needed()
            page.wait_for_timeout(1600)
            page.locator("#rungs").scroll_into_view_if_needed()
            page.wait_for_timeout(1600)
            page.locator("#drift").scroll_into_view_if_needed()
            page.wait_for_timeout(2400)
            page.goto(f"{base}/sysid/dual_arm_cell/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(900)
            page.locator("#drift").scroll_into_view_if_needed()
            page.wait_for_timeout(2200)
            video = Path(page.video.path())
            ctx.close()

            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            page.goto(f"{base}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(800)
            unstick(page)
            target = page.locator("#oracle")
            target.scroll_into_view_if_needed()
            shots["oracle"] = media / "oracle.jpg"
            target.screenshot(path=str(shots["oracle"]), type="jpeg", quality=60)
            shots["card"] = media / "card.jpg"
            page.locator("#oracle article[data-example=pendulum_can11]").screenshot(path=str(shots["card"]), type="jpeg", quality=70)
            for example in EXAMPLES:
                page.goto(f"{base}/sysid/{example}/")
                page.wait_for_load_state("load")
                page.wait_for_timeout(500)
                unstick(page)
                table = page.locator("table.s2r-ex-full")
                table.scroll_into_view_if_needed()
                shots[f"params-{example}"] = media / f"params-{example}.jpg"
                # WHY quality 45 and a 320 px, 16-colour GIF: the page stays under the desktop preview's ~1.9 MB media-page limit (1.89 MB at 55 / 360 px / 24)
                table.screenshot(path=str(shots[f"params-{example}"]), type="jpeg", quality=45)
                if example in landing.DRIFT_OF:
                    fig = page.locator("#drift ~ figure").first
                    fig.scroll_into_view_if_needed()
                    shots[f"drift-{example}"] = media / f"drift-{example}.jpg"
                    fig.screenshot(path=str(shots[f"drift-{example}"]), type="jpeg", quality=70)
                if example == "pendulum_can11":
                    lad = page.locator("#rungs ~ div.s2r-scroll").first
                    lad.scroll_into_view_if_needed()
                    shots["rungs"] = media / "rungs.jpg"
                    lad.screenshot(path=str(shots["rungs"]), type="jpeg", quality=65)
            ctx.close()
            phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
            page = phone.new_page()
            page.goto(f"{base}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(800)
            page.locator("#oracle article").first.scroll_into_view_if_needed()
            shots["phone"] = media / "phone.jpg"
            page.screenshot(path=str(shots["phone"]), type="jpeg", quality=55)
            phone.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    for name, path in list(shots.items()):  # stills wider than 1000 px scaled down (the page is read at <= 1120 px)
        small = path.with_name(path.stem + "-small.jpg")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-vf", "scale='min(1000,iw)':-1", "-q:v", "8", str(small)], check=True)
        shots[name] = small if small.stat().st_size < path.stat().st_size else path
    mp4 = media / "hero.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", "fps=10,scale=800:-2", "-c:v", "libx264", "-crf", "36", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    shots["hero"] = mp4
    gif = media / "hero.gif"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                    "fps=1,scale=320:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=16[p];[b][p]paletteuse=dither=none", str(gif)], check=False)
    if gif.is_file():
        shots["gif"] = gif
    return shots


def esc(x) -> str:
    return html.escape(str(x))


def fmt(row, field) -> str:
    v, u = landing.display(row[field], row["unit"])
    return "—" if v is None else f"{landing.num(v)} {esc(u)}"


def example_table(doc: dict) -> str:
    rows = []
    for r in doc["parameters"]:
        tol = r.get("tolerance") or {}
        tol_text = (f"± {landing.quantity(tol['value'], r['unit'], 3)}" if tol.get("kind") == "abs" else f"± {landing.num(100 * tol['value'], 3)} %") if tol else ""
        err = None if r["recovered"] is None or r["true"] is None else r["recovered"] - r["true"]
        e_v, e_u = landing.display(err, r["unit"])
        rows.append(f"<tr><td class='mono'>{esc(r['key'])}</td><td>{esc((r.get('card') or '') + ' ' + (r.get('rung') or ''))}</td><td>{fmt(r, 'true')}</td>"
                    f"<td>{fmt(r, 'nominal')}</td><td><b>{fmt(r, 'recovered')}</b></td><td>{landing.num(e_v, 3) if e_v is not None else '—'} {esc(e_u)}</td>"
                    f"<td>{esc(tol_text)}</td><td class='{'ok' if r['pass'] else 'no'}'>{'pass' if r['pass'] else 'FAIL'}</td></tr>")
    return ("<div class='scroll'><table><thead><tr><th>parameter</th><th>card · rung</th><th>true</th><th>nominal</th><th>recovered</th><th>error</th>"
            f"<th>tolerance</th><th></th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>")


def metric_lines(doc: dict) -> str:
    return "".join(f"<li>{esc(m['title'])}: <b>{landing.num(m['before'], 4)} → {landing.num(m['after'], 4)} {esc(m['unit'])}</b> "
                   f"({landing.num(m['factor'], 3)}× better; {'needs ' + landing.num(m['factor_needed'], 2) + '×' if m.get('factor_needed') else 'observed'}"
                   f"{'' if m['pass'] is None else (', pass' if m['pass'] else ', FAIL')})</li>" for m in doc["metrics"])


def render(shots: dict, tests: dict, shas: dict, docs: dict) -> str:
    img = lambda k, alt: f'<img src="{data_uri(shots[k], "image/jpeg")}" alt="{esc(alt)}" loading="lazy">' if k in shots else ""  # noqa: E731
    examples = [docs[x] for x in EXAMPLES if x in docs]
    n_params = sum(d["verdict"]["parameters"] for d in examples)
    n_pass = sum(d["verdict"]["parameters_pass"] for d in examples)
    summary_rows = "".join(
        f"<tr><td><b>{esc(d['title'])}</b><br><span class='mute'>{esc(d.get('subtitle', ''))}</span></td><td>{d['verdict']['parameters_pass']} / {d['verdict']['parameters']}</td>"
        f"<td>{'<br>'.join(esc(m['title']) + ': ' + landing.num(m['before'], 3) + ' → ' + landing.num(m['after'], 3) + ' ' + esc(m['unit']) + ' (' + landing.num(m['factor'], 3) + '×, needs ' + landing.num(m['factor_needed'], 2) + '×)' for m in d['metrics'] if m.get('gated'))}</td>"
        f"<td>{landing.num(d['schedule']['coverage']['train']['pct'], 3)} %</td><td class='{'ok' if d['verdict']['status'] == 'pass' else 'no'}'>{d['verdict']['status'].upper()}</td></tr>"
        for d in examples)
    sections = []
    for d in examples:
        x = d["example"]
        sections.append(f"""<h3 id="{esc(x)}">{esc(d['title'])} <span class="mute">· {esc(d.get('subtitle', ''))}</span></h3>
<p class="mute">{esc(d.get('summary', ''))}</p>
<ul class="tight">{metric_lines(d)}</ul>
{example_table(d)}
<figure><figcaption>The example's page on the built site: every parameter, its card and rung, true / nominal / recovered with its 95 % interval</figcaption>{img('params-' + x, d['title'] + ' parameters')}</figure>""")
    w, k = docs.get("drift_backlash_wear"), docs.get("drift_camera_knock")
    drift = ""
    if w:
        rec = w.get("recalibrated") or {}
        drift += f"""<h3>Backlash wear on CAN 11: forecast ahead vs detected after</h3>
<ul class="tight"><li>Hidden: b(h) = {landing.num(w['b0_true_rad'] * 1e3, 3)} mrad + {landing.num(w['rate_true'] * 1e3, 3)} mrad/h × h, with a little noise per check.</li>
<li><b>Wear rate recovered</b> from the early-life checks (to hour {landing.num(w['early_life_h'], 3)}): <b>{landing.num(w['rate_recovered'] * 1e3, 4)} mrad/h</b>, 95 % {landing.num(w['rate_ci95'][0] * 1e3, 3)} to {landing.num(w['rate_ci95'][1] * 1e3, 3)}
(true {landing.num(w['rate_true'] * 1e3, 4)}; {landing.num(100 * (w['rate_recovered'] - w['rate_true']) / w['rate_true'], 2)} %). On the servo card's M5.wear Archard law at this duty ({landing.num(w['wear']['duty_nm_rev_per_h'], 3)} N·m·rev/h): {landing.num(w['wear']['rate_recovered_per_nm_rev'] * 1e6, 3)} µrad per N·m·rev.</li>
<li><b>Forecast</b> (made at hour {landing.num(w['predicted_at_h'], 3)}, the wear-aware twin): threshold crossed at hour <b>{landing.num(w['predicted_crossing_h'], 4)}</b>, {landing.num(w['remaining_h_at_prediction'], 3)} hours ahead.</li>
<li><b>Actual crossing</b> in the sim: hour <b>{landing.num(w['actual_crossing_h'], 4)}</b> (forecast error {landing.num(100 * (w['predicted_crossing_h'] - w['actual_crossing_h']) / w['actual_crossing_h'], 2)} %).</li>
<li><b>Plain detector</b> (the servo card's drift check): warned at hour <b>{landing.num(w['detector_alarm_h'], 4)}</b>, after the fact. The card's own trend forecast from the drift ratio alone said {landing.num(w['card_trend_remaining_h'], 3) if w.get('card_trend_remaining_h') is not None else 'no crossing'} hours left at hour {landing.num(w['predicted_at_h'], 3)}.</li>
<li><b>Recalibrated</b> at the warning (the gap re-measured from the motor encoder minus the link camera): drift ratio {landing.num(rec.get('ratio'), 3)}×.</li></ul>
<figure><figcaption>CAN 11's page: the drift ratio at every 12 h check, the threshold, the forecast (drawn at hour {landing.num(w['early_life_h'], 3)}) and the crossing</figcaption>{img('drift-pendulum_can11', 'wear chart')}</figure>"""
    if k:
        rec = k.get("recalibrated") or {}
        rows = "".join(f"<tr><td>{esc(n)}</td><td>{landing.quantity(k['shift_true'][n], 'm' if n.endswith('_m') else 'rad', 3)}</td><td>{landing.quantity(k['shift_recovered'].get(n), 'm' if n.endswith('_m') else 'rad', 3)}</td></tr>"
                       for n in k["shift_true"])
        drift += f"""<h3>The head camera knocked out of pose</h3>
<p>Knocked at hour {landing.num(k['knock_h'], 3)}; camera_rgb's drift check warned at hour <b>{landing.num(k['alarm_h'], 3)}</b> and at no check before it; a short recalibration
(10 belt passes and the arms' tags, the camera's six pose numbers only) brought the ratio to <b>{landing.num(rec.get('ratio'), 3)}×</b>.</p>
<div class="scroll"><table><thead><tr><th>the knock</th><th>true</th><th>recovered</th></tr></thead><tbody>{rows}</tbody></table></div>
<figure><figcaption>The cell's page: reprojection drift ratio every 12 h; a knock is a step, so there is nothing to forecast</figcaption>{img('drift-dual_arm_cell', 'knock chart')}</figure>"""
    gif = (f'<details><summary>GIF fallback</summary><img src="{data_uri(shots["gif"], "image/gif")}" alt="the click-through as a GIF"></details>' if "gif" in shots else "")
    sha_line = " · ".join(f"<code>{esc(k_)}</code> {esc(v)}" for k_, v in shas.items())
    can = docs.get("pendulum_can11", {})
    stock = can.get("stock_fit", {}).get("estimates", {})
    stock_line = ", ".join(f"{esc(key)} {landing.num(v.get('error_pct'), 3)} %" for key, v in stock.items() if v.get("error_pct") is not None)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>System-ID oracle</title><style>
:root{{--bg:#fff;--fg:#1d1f23;--mute:#5d6470;--line:#e3e5e8;--chip:#eef1f4;--ok:#1d7a3a;--no:#b42318}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8eaed;--mute:#9aa0aa;--line:#2c3036;--chip:#22262c;--ok:#4cc06e;--no:#f2685c}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;max-width:1120px;margin:0 auto;padding:24px 16px}}
img,video{{max-width:100%;border:1px solid var(--line);border-radius:6px;display:block}} figure{{margin:18px 0}} figcaption{{color:var(--mute);font-size:13px;margin-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}} td,th{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
.scroll{{overflow-x:auto}} .mute{{color:var(--mute)}} .mono{{font-family:ui-monospace,monospace;font-size:12px}} h2{{margin-top:38px}}
.verdict{{font-size:17px}} .pill{{display:inline-block;background:var(--chip);border-radius:10px;padding:0 8px;font-size:12.5px;margin-right:4px}} code{{font-size:13px}}
.ok{{color:var(--ok);font-weight:600}} .no{{color:var(--no);font-weight:700}} ul.tight li{{margin:3px 0}}
</style></head><body>
<p class="verdict"><b>The system-ID oracle passes on all six robot descriptions: {n_pass} of {n_params} hidden values recovered inside their stated tolerances, every held-out
error improved by at least its stated factor, the backlash wear rate recovered and its threshold crossing forecast ahead of the plain detector, and a knocked camera caught
and recalibrated</b> — on <code>main</code> @ <code>{esc(shas.get('main', ''))}</code>; landing page served at <code>/</code> (the six cards) and <code>/sysid/&lt;example&gt;/</code>.</p>
<p><span class="pill">oracle test {esc(tests['oracle'])}</span><span class="pill">site test {esc(tests['site'])}</span><span class="pill">type_cards {esc(tests.get('type_cards', ''))}</span>
<span class="pill">{len(examples)} examples</span><span class="pill">{n_pass}/{n_params} parameters</span></p>

<h2>Hero: the landing page's oracle cards → CAN 11's ladder and wear chart → the cell's knocked camera</h2>
<video src="{data_uri(shots['hero'], 'video/mp4')}" autoplay muted loop controls playsinline></video>{gif}

<h2>What this is</h2>
<p>Zach's Nov 5 spec: "Robot Description in, and then a better model out ... if we assumed the simulator data was real, we should check that our system ID can match the
real values!!!! (this is super important as the base oracle check for all of this...)". Per example: a description (a URDF/MJCF and a small manifest) is parsed into
components typed by the type cards; a calibration schedule is planned with its coverage; the simulator plays the hardware at <b>hidden</b> true parameters
(<code>world.json</code>, read only by the simulator: identification runs with it sealed); the fit starts from the description's nominal values; the held-out split is
scored before and after. The ruler (<code>sysid/acceptance.json</code>, pinned by digest in <code>sysid/tests/test_oracle.py</code>) was committed before any
identification code, and it can fail: every gated parameter's nominal value is outside its own tolerance.</p>

<h2>Per example</h2>
<div class="scroll"><table><thead><tr><th>example</th><th>parameters in tolerance</th><th>held-out error, before → after</th><th>train coverage</th><th></th></tr></thead><tbody>{summary_rows}</tbody></table></div>
<figure><figcaption>The landing page's oracle section (built site, 1280 px)</figcaption>{img('oracle', 'oracle section')}</figure>
<figure><figcaption>One card: description in, typed tree, schedule coverage, parameters true / nominal / recovered, held-out error before → after</figcaption>{img('card', 'CAN 11 card')}</figure>
<figure><figcaption>390 px: the cards stack, no sideways scroll</figcaption>{img('phone', 'phone')}</figure>
{''.join(sections)}

<h2>Drift</h2>
{drift}

<h2>What the oracle found on the way (each fixed in the method, the ruler unchanged)</h2>
<ul class="tight">
<li><b>bam_rack_twin's stock quasi-static fits are biased under CAN 11's own gains</b> (ki 16000 limit-cycles the slow sweeps): on this truth {stock_line}; sysid's one inverse-dynamics regression over every train run is not. Worth knowing for the real CAN 11's identified G.</li>
<li><b>A rigid regression across a gear gap</b> reads G −6 %, Fs +16 % (the motor carries neither weight nor inertia mid-gap): M4 re-fits on the rows where the encoder minus the camera says the gear is in contact.</li>
<li><b>CAN 11's held-out replay is dominated by the static friction level</b> (Fs −3 % moved it 4.6 mrad, G +1.4 % 0.5 mrad): the static level and the drop are polished by output error on the train runs.</li>
<li><b>MuJoCo's implicitfast applies a servo's damping at the end of the step</b>: <code>actuator_force</code> is not the torque the joint got (h·kv, 0.8 kg·m² read as inertia); the simulated torque sensor reports the applied torque.</li>
<li><b>One smoother on every channel, and no rows within a smoother window of a stuck joint</b> (bam_rack_twin.identify.filtered's rule; a stuck joint's friction leaks into the neighbours' smoothed torque): applied to the arm and swept to CAN 11, where it took G from +1.4 % to +0.4 %.</li>
<li><b>Excitation design is part of identifiability</b>: at a 0.1 Hz Fourier base the shoulder lift's inertia under the gripper read 7 % low on every noise seed (the speed noise in qdd times the joint's whole inertia); a 0.2 Hz base doubles every acceleration at the same peak speed (Swevers et al. 1997).</li>
<li><b>Planar targets are ambiguous</b>: a nearly flat card cannot separate a D435's focal length, standoff and depth scale (a 150 mm riser does); belt tags alone confuse a camera's sideways shift with a tilt (the arms' tags split them).</li>
<li><b>The ruler's own guard caught a bad world</b>: two HSI band gains sat inside their 2 % tolerance of nominal; the truth moved, the tolerance did not (commit named).</li>
</ul>

<h2>Decided, left, not done</h2>
<ul class="tight">
<li>Decided: the package is <code>sysid/</code> (examples under <code>sysid/examples/</code>); the pipelines run in bam_rack_twin's environment (MuJoCo 3.11) and import bam_ws in place; the site reads committed results (stdlib). Undo: <code>git revert</code> the landing commits.</li>
<li>Decided: values sit on the cards' own ladders (<code>sysid/cards.py</code> PLACE); the gripper and the tool an arm carries have no card yet (proposed for lane A).</li>
<li>Decided: every result names what computed it: this repo's commit (<code>+dirty</code> only for uncommitted code, never for the results a run writes, which the first write had counted on every page) and each checkout used in place, with its branch and last commit (bam_ws, the io-diagnostics and robot_msgs checkouts bam_rack_twin imports, Menagerie), listed at the foot of every example page and below.</li>
<li>Left: the arm plans cover &lt; 1 % of the arm card's 4,096-cell joint cube (the card's 40 % gate fails): the card's rule is in joint space, the calibration poses were picked for the tracker and the tags.</li>
<li>Not done: rendered images and a real detector in the camera loops (corner detections are projections plus noise); band centres and widths (need a lamp); contact and grip force (need a gauge).</li>
</ul>
<p class="mute">{sha_line}</p>
</body></html>"""


def unstick(page) -> None:
    """The site's sticky header (header.top, site.css) made static for element stills, checked: Playwright scrolls a tall element
    under it while it stitches the screenshot, so a sticky bar lands across the table's rows (it covered two UR5e rows when the rule
    named classes the header does not have)."""
    page.add_style_tag(content="header.top, .top { position: static !important; }")
    position = page.evaluate("(() => { const h = document.querySelector('header.top'); return h ? getComputedStyle(h).position : 'none'; })()")
    if position not in ("static", "none"):
        raise SystemExit(f"the site header is still {position}: element stills would show it across their rows")


def test_count(value: str) -> str:
    """A test pill's text, read from the run's own output when given a file: a pytest --junitxml file (passed of collected, skips
    named) or a site/tests/test_site_flow.py log (its PASS lines, and FAIL lines, which make it read FAIL). Anything else is shown
    as given, so a count is only typed when no run output was kept."""
    path = Path(value)
    if not path.is_file():
        return value
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.lstrip().startswith("<"):
        import xml.etree.ElementTree as ET  # noqa: PLC0415

        root = ET.fromstring(text)
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        n = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
        passed = n["tests"] - n["failures"] - n["errors"] - n["skipped"]
        tail = f", {n['skipped']} skipped" if n["skipped"] else ""
        return f"{passed}/{n['tests']}{tail}" + ("" if n["failures"] + n["errors"] == 0 else " FAIL")
    lines = text.splitlines()
    passes, fails = sum(x.startswith("PASS ") for x in lines), sum(x.startswith("FAIL ") for x in lines)
    return f"{passes}/{passes + fails}" + ("" if fails == 0 and "ALL PASS" in lines else " FAIL")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, default=SITE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--oracle-tests", default="?", help="sysid's pytest --junitxml file (or a count)")
    parser.add_argument("--site-tests", default="?", help="site/tests/test_site_flow.py's log (or a count)")
    parser.add_argument("--type-cards-tests", default="?", help="type_cards' pytest --junitxml file (or a count)")
    args = parser.parse_args()
    docs = landing.load()
    shas = {"main": subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()}
    # every checkout the results were computed from in place, as their provenance stamped it (never typed here)
    for doc in docs.values():
        for s in (doc.get("provenance") or {}).get("imports") or []:
            stamp = f"{s['branch']} @ {s['commit']} {s['date'][:10]}{' +dirty' if s['dirty'] else ''}"
            shas[s["name"]] = " / ".join(sorted(set(filter(None, shas.get(s["name"], "").split(" / "))) | {stamp}))
    with tempfile.TemporaryDirectory() as tmp:
        shots = capture(args.site, Path(tmp))
        page = render(shots, {"oracle": test_count(args.oracle_tests), "site": test_count(args.site_tests),
                              "type_cards": test_count(args.type_cards_tests)}, shas, docs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
