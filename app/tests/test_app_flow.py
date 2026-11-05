"""The sim2real app, clicked through headless: deployments -> the rack -> a run with models -> playback.

    uv run --no-project --with playwright python /home/bam/sim2real/app/tests/test_app_flow.py
    uv run --no-project --with playwright python /home/bam/sim2real/app/tests/test_app_flow.py --record /home/bam/sim2real/reports/media/app-flow-2026-10-28/capture

Starts its own serve.py on a free port in 4701-4799 (never 4700, which Zach may be using) and stops it by the PID it
started. Needs the app's data (tools/build_app.py). Asserts, measured in the page:
- the deployments list opens the One Dof Test Rack;
- the runs are ordered newest first (every visible Started cell, and the whole runs.json file);
- the gates layer toggles on (the station gate matrix appears, URL layer=gates) and off again;
- a run with models opens from its Open link, and its legend's real swatch is blue and every model swatch orange
  (hue measured from the rendered swatch colour; green and red are reserved for pass/fail);
- the two trajectory3d panels (3D and the top face) draw a non-blank canvas with a real (blue) and a model (orange) series;
- a legend click hides that series on the chart and a second click shows it again (pixels of its colour counted);
- Play moves the clock (the readout and the playhead advance);
- the gate matrix is the newest acceptance file's, cell by cell (found independently by generated_at), and the page names it;
- "Why it fails" has one row per cell that acceptance does not pass, each with a number, a why and a next step; its explanation
  cells sit inside the viewport at 1280 and 390 px; a T2 row opens its worst held-out window with the decomposition plots.
With --record it also writes a video of the click-through and stills of each step for the report.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
EXE = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"
REAL_HUES = (195.0, 230.0)  # data-ui series slot 1, blue
SIM_HUES = (8.0, 40.0)  # data-ui series slot 2, orange, and its lighter/darker members
FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILS.append(what)


def free_port() -> int:
    busy = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True).stdout
    taken = {int(m) for m in re.findall(r":(\d+)\s", busy)}
    for port in range(4701, 4800):
        if port in taken:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise SystemExit("no free port in 4701-4799")


def hue(css: str) -> tuple[float, float]:
    """(hue in degrees, saturation) of a #rrggbb or rgb() colour."""

    m = re.fullmatch(r"#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})(?:[0-9a-f]{2})?", css.strip().lower())
    rgb = [int(x, 16) for x in m.groups()] if m else [float(x) for x in re.findall(r"[\d.]+", css)[:3]]
    h, _l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    return h * 360, s


def newest_acceptance() -> tuple[Path, dict]:
    """The newest bam_rack_twin acceptance file in the archive, by its own generated_at: read here independently of the producer."""
    best = None
    for path in Path("/archive/datasets/bam_rig").glob("rack_2026-*/analysis/acceptance*.json"):
        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("bam_rack_twin.acceptance/") and doc.get("generated_at"):
            if best is None or doc["generated_at"] > best[1]["generated_at"]:
                best = (path, doc)
    return best


def gates_match_newest() -> tuple[bool, str]:
    """The gate matrix the app shows (gates.json) against the newest acceptance, cell by cell."""
    path, doc = newest_acceptance()
    want = {(f"CAN {can}", g["id"]): g["status"] for can, st in doc["stations"].items() for g in st["gates"]}
    shown = {(c["device"], c["gate"].split()[0]): c["verdict"] for c in json.loads((REPO / "app/data/one-dof-test-rack/gates.json").read_text())["rows"]}
    differ = sorted(k for k in want.keys() | shown.keys() if want.get(k) != shown.get(k))
    passing = sum(1 for v in want.values() if v == "pass")
    return not differ, f"{path.name} ({doc['generated_at']}): {passing}/{len(want)} pass; differing cells {differ[:5]}"


def panel(page, title: str):
    """A view panel by its title (a text panel can mention the same words, so match the panel header, not the body); a tabbed
    panel has no header, so its tab's name counts too."""
    return page.locator(".dd-panel").filter(has=page.locator(f".dd-panel-h:has-text('{title}'), [role=tab][data-name='{title}']")).first


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", type=Path, help="write the click-through video and stills here")
    args = parser.parse_args()
    ok, detail = gates_match_newest()
    check(ok, f"the gate matrix shown is the newest acceptance, cell by cell: {detail}")
    port = free_port()
    server = subprocess.Popen([sys.executable, str(REPO / "serve.py"), "--port", str(port)], stdout=subprocess.PIPE, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        server.stdout.readline()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=EXE)
            options = {"viewport": {"width": 1440, "height": 900}}
            if args.record:
                args.record.mkdir(parents=True, exist_ok=True)
                options["record_video_dir"] = str(args.record)
                options["record_video_size"] = {"width": 1440, "height": 900}
            context = browser.new_context(**options)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            still = lambda name: args.record and page.screenshot(path=str(args.record / f"{name}.png"))  # noqa: E731

            # 1. deployments
            page.goto(f"{base}/app/")
            row = page.locator("tr", has_text="One Dof Test Rack").first
            row.wait_for(timeout=20000)
            page.wait_for_timeout(800)
            still("1-deployments")
            row.locator("td").first.click()
            page.wait_for_url(re.compile(r"[?&]d=one-dof-test-rack"), timeout=20000)
            check("d=one-dof-test-rack" in page.url, "the deployments list opens the One Dof Test Rack")

            # 2. runs, newest first
            runs = panel(page, "Runs · newest first")
            runs.locator("tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            still("2-deployment")
            headers = [h.strip() for h in runs.locator("thead th").all_inner_texts()]
            column = next(i for i, h in enumerate(headers) if h.startswith("Started"))
            started = [cells[column].strip() for cells in runs.locator("tbody tr").evaluate_all(
                "rows => rows.map(r => [...r.querySelectorAll('td')].map(td => td.textContent))") if len(cells) > column and cells[column].strip()]
            check(len(started) >= 5 and started == sorted(started, reverse=True), f"the visible runs are newest first ({len(started)} rows: {started[0]} ... {started[-1]})")
            whole = [r["started"] for r in json.loads((REPO / "app/data/one-dof-test-rack/runs.json").read_text())["rows"]]
            check(whole == sorted(whole, reverse=True), f"runs.json is newest first ({len(whole)} runs)")
            page.locator(".dd-panel", has_text="Phase space").first.scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
            still("3-coverage")
            page.evaluate("window.scrollTo(0, 0)")

            # 3. the gates layer toggles
            page.click("#layer")
            page.wait_for_url(re.compile(r"layer=gates"), timeout=20000)
            matrix = panel(page, "Stations × gates")
            matrix.wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            check(page.get_attribute("#layer", "aria-pressed") == "true" and matrix.is_visible(), "the gates layer turns on (gate matrix shown, layer=gates)")
            still("4-gates-layer")
            page.click("#layer")
            page.wait_for_function("!location.search.includes('layer=gates')", timeout=20000)
            panel(page, "Runs · newest first").locator("tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            check(page.locator(".dd-panel", has_text="Stations × gates").count() == 0 and page.get_attribute("#layer", "aria-pressed") == "false",
                  "the gates layer turns off again (no gate matrix)")

            # 4. a run with models, from its Open link
            page.locator(".dd-rail label", has_text="real + 4 models").first.click()
            page.wait_for_timeout(1500)
            link = panel(page, "Runs · newest first").locator("a[href*='&run=']").first
            link.scroll_into_view_if_needed()
            href = link.get_attribute("href")
            link.click()
            page.wait_for_url(re.compile(r"&run="), timeout=20000)
            check("&run=" in page.url and "t2~heldout" in page.url, f"a run with models opens ({href})")
            angle = panel(page, "Angle · real vs models")
            angle.locator(".dv-timeseries-key").first.wait_for(timeout=30000)
            page.wait_for_timeout(2000)
            still("5-run")
            keys = angle.locator(".dv-timeseries-key").evaluate_all(
                "ks => ks.map(k => ({name: k.textContent.trim(), color: getComputedStyle(k.querySelector('i')).getPropertyValue('--dv-ts-c') || getComputedStyle(k.querySelector('i')).backgroundColor}))")
            real = [k for k in keys if k["name"] == "real"]
            sims = [k for k in keys if k["name"].startswith("twin")]
            check(len(real) == 1 and REAL_HUES[0] <= hue(real[0]["color"])[0] <= REAL_HUES[1], f"the real swatch is blue ({real[0]['color'] if real else None})")
            check(len(sims) >= 2 and all(SIM_HUES[0] <= hue(k["color"])[0] <= SIM_HUES[1] and hue(k["color"])[1] > 0.35 for k in sims),
                  "every model swatch is orange (" + ", ".join(f"{k['name']} {k['color']}" for k in sims) + ")")

            # 4b. the legend toggles a series (data-ui legend-toggle, vendored at dd53748): measured as that series' pixels on the chart
            count_js = """(p, rgb) => { let n = 0; for (const c of p.querySelectorAll('canvas')) { let d; try { d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; } catch { continue; }
                for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - rgb[0]) + Math.abs(d[i + 1] - rgb[1]) + Math.abs(d[i + 2] - rgb[2]) < 40 && d[i + 3] > 200) n++; } return n; }"""
            key = angle.locator(".dv-legend-key[data-legend-series='twin D · LuGre']").first
            twin_d = (0xeb, 0x68, 0x34)
            shown = angle.evaluate(count_js, list(twin_d))
            key.click()
            page.wait_for_timeout(600)
            hidden = angle.evaluate(count_js, list(twin_d))
            pressed = key.get_attribute("aria-pressed")
            key.click()
            page.wait_for_timeout(600)
            back = angle.evaluate(count_js, list(twin_d))
            # WHY the shown-again count is the baseline: before the click twin D is drawn under the other models (the first count is small);
            # re-shown it is drawn last, on top
            check(pressed == "false" and back > 50 and hidden < 0.1 * back and key.get_attribute("aria-pressed") == "true",
                  f"a legend click hides the series and a second shows it (twin D pixels {shown} -> {hidden} -> {back})")

            # 4c. the trajectory3d panels (data-ui P1b): the output link's marker arc in its joint frame, drawn on a WebGL canvas.
            # Measured from a screenshot of the canvas itself (a WebGL buffer cannot be read back after it is shown), decoded in the
            # page: how many pixels differ from the canvas background, and how many are real blue and model orange
            measure_js = """async ([png, colours]) => {
                const img = new Image(); img.src = 'data:image/png;base64,' + png; await img.decode();
                const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
                const g = c.getContext('2d'); g.drawImage(img, 0, 0); const d = g.getImageData(0, 0, c.width, c.height).data;
                const bg = [d[0], d[1], d[2]]; const near = (i, rgb, tol) => Math.abs(d[i] - rgb[0]) + Math.abs(d[i + 1] - rgb[1]) + Math.abs(d[i + 2] - rgb[2]) < tol;
                const out = {ink: 0}; for (const k of Object.keys(colours)) out[k] = 0;
                // WHY the top-right corner is skipped: the view cube's RGB axes (Z blue, X red) sit there and match the series' hues
                for (let i = 0; i < d.length; i += 4) { const x = (i / 4) % c.width, y = Math.floor(i / 4 / c.width);
                  if (x > 0.75 * c.width && y < 0.3 * c.height) continue;
                  if (!near(i, bg, 24)) out.ink++; for (const [k, rgb] of Object.entries(colours)) if (near(i, rgb, 60)) out[k]++; }
                return out; }"""
            import base64
            # WHY seek first: at t = 0 a decay trail is only each series' head; 4 s in it is a second of arc per series
            page.evaluate("location.hash = 't=4'")
            page.wait_for_timeout(1000)
            for title in ("Output link · 3D in its joint frame", "Output link · top (down the joint axis)"):
                p3 = panel(page, title)
                p3.scroll_into_view_if_needed()
                p3.locator("canvas").first.wait_for(timeout=30000)
                page.wait_for_timeout(1500)
                canvas = max(p3.locator("canvas").all(), key=lambda c: (c.bounding_box() or {"width": 0})["width"] * (c.bounding_box() or {"height": 0})["height"])
                png = base64.b64encode(canvas.screenshot()).decode()
                found = page.evaluate(measure_js, [png, {"real": [0x2a, 0x78, 0xd6], "model": [0xeb, 0x68, 0x34]}])
                box = canvas.bounding_box()
                check(found["ink"] > 0.002 * box["width"] * box["height"] and found["real"] > 20 and found["model"] > 20,
                      f"{title}: a non-blank canvas with a real (blue) and a model (orange) series drawn ({found})")
            panel(page, "Output link · 3D in its joint frame").scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            still("5b-trajectory3d")
            angle.scroll_into_view_if_needed()

            # 5. playback
            readout = page.locator(".dv-pb-time").first
            before = readout.inner_text()
            playhead = angle.locator("[data-playhead]").first
            x0 = playhead.bounding_box()["x"] if playhead.count() else None
            page.locator("button[aria-label*='Play' i]").first.click()
            page.wait_for_timeout(1800)
            after = readout.inner_text()
            x1 = playhead.bounding_box()["x"] if playhead.count() else None
            t_before, t_after = (float(re.match(r"[\d.]+", text).group()) for text in (before, after))
            check(t_after > t_before + 0.5, f"Play moves the clock ({before} -> {after})")
            check(x0 is not None and x1 is not None and x1 > x0 + 20, f"the playhead moves on the angle chart (x {x0} -> {x1})")
            page.wait_for_timeout(1500)
            still("6-playback")
            page.locator("button[aria-label*='Pause' i]").first.click()
            page.click("#layer")
            page.locator(".dd-panel", has_text="Diagnostics of this run").first.wait_for(timeout=30000)
            page.wait_for_timeout(2000)
            still("7-run-gates")

            # 6. why it fails: one row per gate cell the newest acceptance does not pass, explained without scrolling sideways
            page.goto(f"{base}/app/?d=one-dof-test-rack")
            why = panel(page, "Why it fails")
            why.locator("tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            why.scroll_into_view_if_needed()
            still("8-why-it-fails")
            newest_path, newest_doc = newest_acceptance()
            open_cells = {(f"CAN {can}", g["id"]) for can, st in newest_doc["stations"].items() for g in st["gates"] if g["status"] != "pass"}
            rows = json.loads((REPO / "app/data/one-dof-test-rack/why.json").read_text())["rows"]
            listed = {(r["device"], r["gate_id"]) for r in rows if r["status"] != "pass"}
            check(listed == open_cells and all(r.get("next") and r.get("why") and r.get("measured") for r in rows),
                  f"Why it fails has one row per cell {newest_path.name} does not pass ({len(listed)} of {len(open_cells)}), each with a number, a why and a next step")
            check(("CAN 12", "T3") in listed and next(r for r in rows if (r["device"], r["gate_id"]) == ("CAN 12", "T3"))["status"] == "fail",
                  "CAN 12 T3 is listed as a fail (the stale acceptance had it passing)")
            check(sum(1 for r in rows if r["next"].startswith("blocked on Zach")) > 0 and any(r.get("floor_rules") and "the gates use the pooled floor" in r["floor_rules"] for r in rows),
                  "rows name what is blocked on Zach, and the floor rule in force where the verdict depends on it (pooled, the 2026-11-04 default)")
            # the explanation sits inside the viewport, no sideways scroll, at 1280 and 390 px
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 900})
                page.wait_for_timeout(1200)
                why.scroll_into_view_if_needed()
                page.wait_for_timeout(800)
                boxes = why.locator("tbody td").evaluate_all(
                    "tds => tds.filter(td => td.textContent.includes('Why:')).slice(0, 6).map(td => { const r = td.getBoundingClientRect(); return [r.left, r.right, innerWidth]; })")
                check(len(boxes) >= 3 and all(left >= 0 and right <= vw + 0.5 for left, right, vw in boxes),
                      f"at {width} px the explanation cells sit inside the viewport ({[(round(a), round(b)) for a, b, _ in boxes[:3]]}, width {boxes[0][2] if boxes else '?'})")
                if width == 390:
                    still("8c-why-390")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(1000)
            evidence_text = panel(page, "Evidence files").inner_text()
            check(newest_path.name in evidence_text.replace("…", "") or newest_doc["generated_at"] in evidence_text,
                  f"the page names its gates' source and date ({newest_path.name}, {newest_doc['generated_at']})")
            panel(page, "Caveats").scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            still("8b-caveats")
            caveat_text = panel(page, "Caveats").inner_text()
            check(all(x in caveat_text for x in ("1.72×", "2.28×", "The gates use the safer pick")),
                  "the caveats name the pick rules on CAN 11 with both numbers (safer 1.72×, declared 2.28×) and the rule in force (safer, the 2026-11-04 default)")
            gains = {r["session"]: r["gains"] for r in json.loads((REPO / "app/data/one-dof-test-rack/runs.json").read_text())["rows"] if r["device"] == "CAN 11"}
            check(all(s in gains for s in ("can11_hold_kp100", "can11_hold_kp150", "can11_hold_kp200", "can11_hold_il0.25", "can11_hold_il0.5"))
                  and len({gains[s] for s in ("can11_hold_kp100", "can11_hold_kp150", "can11_hold_kp200", "can11_hold_il0.25", "can11_hold_il0.5")}) == 5,
                  "the 10-29 CAN 11 gain steps each show their own board gains (" + "; ".join(gains.get(s, "?") for s in ("can11_hold_kp100", "can11_hold_kp150", "can11_hold_kp200", "can11_hold_il0.25", "can11_hold_il0.5")) + ")")
            # a row with a worst window opens playback there (CAN 1 passes T2 since the follow-up, so the first such row now: CAN 11 T2)
            expected = next(r for r in rows if r["gate_id"] == "T2" and r.get("page") and "tr=" in r["page"])
            t0, t1 = (float(x) for x in re.search(r"tr=([\d.]+),([\d.]+)", expected["page"]).groups())
            why.scroll_into_view_if_needed()
            cell = why.locator("tbody td", has_text=re.compile(rf"^\s*T2 fidelity — {expected['status']}")).filter(has_text=expected["measured"].split(" ·")[0]).first
            cell.click()
            page.wait_for_url(re.compile(rf"why={expected['station']}(#|&|$)"), timeout=20000)
            readout = page.locator(".dv-pb-time").first
            readout.wait_for(timeout=30000)
            panel(page, "Torque gap by term family").wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            now = float(re.match(r"[\d.]+", readout.inner_text()).group())
            worst = re.search(r"run=([^&#]+)", expected["page"]).group(1)
            check(worst in page.url and abs(now - t0) < 0.05,
                  f"{expected['device']} T2 opens its worst held-out window ({worst}, clock {now:.2f} s, window {t0:.2f}-{t1:.2f} s)")
            check(panel(page, "Torque gap by term family").locator("canvas, svg").count() > 0 and panel(page, "Move error by phase").count() == 1,
                  "the run opened from Why shows the residual-decomposition plots")
            still("9-why-run")
            check(not errors, f"no page errors ({errors[:3]})")
            context.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
    print(f"{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
