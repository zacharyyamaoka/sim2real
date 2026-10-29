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
- a legend click hides that series on the chart and a second click shows it again (pixels of its colour counted);
- Play moves the clock (the readout and the playhead advance);
- "Why it fails" lists the 8 stations, and clicking CAN 1 opens its worst held-out window (the clock at the window's start) with the
  residual-decomposition plots.
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


def panel(page, title: str):
    """A view panel by its title (a text panel can mention the same words, so match the panel header, not the body)."""
    return page.locator(".dd-panel").filter(has=page.locator(".dd-panel-h", has_text=title)).first


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", type=Path, help="write the click-through video and stills here")
    args = parser.parse_args()
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

            # 6. why it fails: one row per station; CAN 1's row opens its worst held-out window in playback
            page.goto(f"{base}/app/?d=one-dof-test-rack")
            why = panel(page, "Why it fails")
            why.locator("tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            why.scroll_into_view_if_needed()
            still("8-why-it-fails")
            stations = why.locator("tbody tr").evaluate_all("rows => rows.map(r => r.querySelector('td')?.textContent.trim())")
            check(sorted(stations) == sorted(f"CAN {c}" for c in (1, 4, 11, 12, 13, 14, 15, 21)), f"the Why it fails panel lists the 8 stations ({stations})")
            panel(page, "Caveats").scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            still("8b-caveats")
            caveat_text = panel(page, "Caveats").inner_text()
            check(all(x in caveat_text for x in ("1.72×", "2.28×", "Zach's decision, pending")),
                  "the caveats name the pick rule on CAN 11 with both numbers (safer 1.72×, declared 2.28×) and that the rule is pending")
            gains = {r["session"]: r["gains"] for r in json.loads((REPO / "app/data/one-dof-test-rack/runs.json").read_text())["rows"] if r["device"] == "CAN 11"}
            check(all(s in gains for s in ("can11_hold_kp100", "can11_hold_kp150", "can11_hold_kp200", "can11_hold_il0.25", "can11_hold_il0.5"))
                  and len({gains[s] for s in ("can11_hold_kp100", "can11_hold_kp150", "can11_hold_kp200", "can11_hold_il0.25", "can11_hold_il0.5")}) == 5,
                  "the 10-29 CAN 11 gain steps each show their own board gains (" + "; ".join(gains.get(s, "?") for s in ("can11_hold_kp100", "can11_hold_kp150", "can11_hold_kp200", "can11_hold_il0.25", "can11_hold_il0.5")) + ")")
            expected = next(r for r in json.loads((REPO / "app/data/one-dof-test-rack/why.json").read_text())["rows"] if r["device"] == "CAN 1")
            t0, t1 = (float(x) for x in re.search(r"tr=([\d.]+),([\d.]+)", expected["page"]).groups())
            row = why.locator("tbody tr").filter(has=page.locator("td", has_text=re.compile(r"^\s*CAN 1\s*$"))).first
            row.locator("td").nth(2).click()
            page.wait_for_url(re.compile(r"why=can1(#|&|$)"), timeout=20000)
            readout = page.locator(".dv-pb-time").first
            readout.wait_for(timeout=30000)
            panel(page, "Torque gap by term family").wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            now = float(re.match(r"[\d.]+", readout.inner_text()).group())
            check(expected["worst_run"] in page.url and abs(now - t0) < 0.05,
                  f"CAN 1 opens its worst held-out window ({expected['worst_run']}, clock {now:.2f} s, window {t0:.2f}-{t1:.2f} s)")
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
