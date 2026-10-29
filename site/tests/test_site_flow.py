"""sim2real on catalog-workbench, clicked through headless: the acceptance checks of the migration.

    python3 /home/bam/sim2real-worktrees/catalog-workbench/site/build.py
    uv run --no-project --with playwright python /home/bam/sim2real-worktrees/catalog-workbench/site/tests/test_site_flow.py
    uv run --no-project --with playwright python /home/bam/sim2real-worktrees/catalog-workbench/site/tests/test_site_flow.py --record /abs/capture/dir

Since 2026-10-29 also a station's Schedule tab (bam_rack_twin.schedule's plan, before anything runs), its checks written before
the tab. A port of app/tests/test_app_flow.py's 25 checks onto the migrated site (every one keeps its meaning; where a step moved,
the check says where to), plus the checks that the shell IS the workbench's: the same bar (wordmark, one centred search,
Account), the same trail, record pages with tabs, and every side panel resizable (data-resizable, dragged and measured).
Spatial claims are measured with getBoundingClientRect in headless Chromium, at 1280 and 390 px.

Serves the built site (site/build.py's OUT) with `python3 -m http.server` on a free port in 4711-4799 (never 4700,
Zach's) and stops it by the PID it started. WHY written before the site (the migration brief, 2026-10-29): this file is
the ruler; site/ was built until it passed.
"""

from __future__ import annotations

import argparse
import base64
import colorsys
import hashlib
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parent
sys.path.insert(0, str(SITE))
sys.path.insert(1, str(SITE / "vendor"))
EXE = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"
REAL_HUES = (195.0, 230.0)  # data-ui series slot 1, blue
SIM_HUES = (8.0, 40.0)  # data-ui series slot 2, orange, and its lighter/darker members
DEP = "one-dof-test-rack"
FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILS.append(what)


def free_port() -> int:
    busy = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True).stdout
    taken = {int(m) for m in re.findall(r":(\d+)\s", busy)}
    for port in range(4711, 4800):
        if port in taken:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise SystemExit("no free port in 4711-4799")


def hue(css: str) -> tuple[float, float]:
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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def panel(page, title: str):
    """A data-ui view panel by its header title (or its tab's name in a tabbed panel)."""
    return page.locator(".dd-panel").filter(has=page.locator(f".dd-panel-h:has-text('{title}'), [role=tab][data-name='{title}']")).first


def open_tab(page, key: str) -> None:
    page.click(f"nav.tabs [role=tab][href='#{key}']")
    page.wait_for_function(f"document.querySelector('[role=tabpanel][data-tab=\"{key}\"]') && !document.querySelector('[role=tabpanel][data-tab=\"{key}\"]').hidden")


def no_sideways_scroll(page) -> tuple[bool, str]:
    sw, vw = page.evaluate("[document.scrollingElement.scrollWidth, innerWidth]")
    return sw <= vw + 1, f"scrollWidth {sw} vs {vw}"


def shell_checks(page, where: str) -> None:
    """The workbench's bar and trail, measured: wordmark left, ONE search centred in the bar, Account right; a breadcrumb."""
    m = page.evaluate("""() => {
        const r = (s) => { const el = document.querySelector(s); if (!el) return null; const b = el.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom]; };
        return {bar: r('header.top .bar'), word: r('header.top .wordmark'), find: r('header.top form.find'), acct: r('header.top .quick .acct'),
                q: document.querySelectorAll('header.top input#site-q[type=search]').length, crumbs: [...document.querySelectorAll('.trail nav.crumbs a:not(.back)')].map(a => a.textContent.trim()),
                vw: innerWidth};
    }""")
    centred = m["find"] and abs((m["find"][0] + m["find"][1]) / 2 - (m["bar"][0] + m["bar"][1]) / 2) < 2
    order = m["word"] and m["acct"] and m["word"][1] <= m["find"][0] and m["find"][1] <= m["acct"][0]
    check(m["q"] == 1 and centred and order and len(m["crumbs"]) >= 1 and m["crumbs"][0] == "Home",
          f"{where}: the workbench bar (wordmark | one centred search | Account) and trail ({' › '.join(m['crumbs'])}; search centre off by "
          f"{round(abs((m['find'][0] + m['find'][1]) / 2 - (m['bar'][0] + m['bar'][1]) / 2), 1) if m['find'] else '?'} px)")


def main() -> int:
    import build as site_build  # noqa: PLC0415
    import adapter  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=site_build.DEFAULT_OUT, help="the built site (site/build.py --out)")
    parser.add_argument("--record", type=Path, help="write the click-through video and stills here")
    args = parser.parse_args()
    out = args.out.resolve()
    data = out / "data" / DEP

    # ---- 0. no browser: the data the site serves, and the shell is the workbench's ---------------------------------------
    path, doc = newest_acceptance()
    want = {(f"CAN {can}", g["id"]): g["status"] for can, st in doc["stations"].items() for g in st["gates"]}
    shown = {(c["device"], c["gate"].split()[0]): c["verdict"] for c in json.loads((data / "gates.json").read_text())["rows"]}
    differ = sorted(k for k in want.keys() | shown.keys() if want.get(k) != shown.get(k))
    check(not differ, f"the gate matrix shown is the newest acceptance, cell by cell: {path.name} ({doc['generated_at']}): "
                      f"{sum(1 for v in want.values() if v == 'pass')}/{len(want)} pass; differing cells {differ[:5]}")
    whole = [r["started"] for r in json.loads((data / "runs.json").read_text())["rows"]]
    check(whole == sorted(whole, reverse=True), f"runs.json is newest first ({len(whole)} runs)")

    vendored = SITE / "vendor" / "catalog_workbench"
    manifest = json.loads((vendored / "MANIFEST.json").read_text())["files"]
    pin = json.loads((vendored / "VENDOR.json").read_text())
    edited = sorted(name for name, digest in manifest.items() if sha((vendored / name).read_bytes()) != digest)
    check(not edited and sha((vendored / "MANIFEST.json").read_bytes()) == pin["manifest_sha256"],
          f"the vendored workbench is catalog-workbench {pin['version']} @ {pin['commit'][:7]}, unedited ({len(manifest)} files, edited: {edited})")
    statics = {name: subprocess.run(["git", "-C", str(adapter.ROBOTPARTS_REPO), "show", f"{adapter.SHELL_COMMIT}:site/static/{name}"],
                                    capture_output=True, check=True).stdout for name in adapter.SHELL_STATIC}
    differ_static = [name for name, blob in statics.items() if (out / "static" / name).read_bytes() != blob]
    check(not differ_static, f"the shell's scripts and styles are robotparts' at {adapter.SHELL_COMMIT[:7]}, byte for byte ({', '.join(statics)}; differ: {differ_static})")
    import catalog  # noqa: PLC0415
    from catalog_workbench import shell  # noqa: PLC0415
    site = adapter.load(out / "data")
    home_html = (out / "index.html").read_text()
    header = shell.site_header(catalog.CATALOG, site, "/")
    run_row = next(r for r in site.runs if "t2~heldout" in r["run"])
    run_html = (out / adapter.run_url(run_row).strip("/") / "index.html").read_text()
    check(header in home_html and shell.site_header(catalog.CATALOG, site, adapter.run_url(run_row)) in run_html,
          "the home's and a run page's bar are exactly catalog_workbench.shell.site_header (the same bar, search and Account menu)")

    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
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
            browser = p.chromium.launch(executable_path=EXE)
            options = {"viewport": {"width": 1280, "height": 900}}
            if args.record:
                args.record.mkdir(parents=True, exist_ok=True)
                options["record_video_dir"] = str(args.record)
                options["record_video_size"] = {"width": 1280, "height": 900}
            context = browser.new_context(**options)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            still = lambda name: args.record and page.screenshot(path=str(args.record / f"{name}.png"))  # noqa: E731

            # 1. the home: the workbench's bar, tiles of deployments and stations, the Choose column resizable
            page.goto(f"{base}/")
            page.wait_for_load_state("load")
            page.wait_for_timeout(600)
            still("1-home")
            shell_checks(page, "home at 1280")
            tiles = page.evaluate("[...document.querySelectorAll('.groups .tile .tn')].map(t => t.textContent.trim())")
            check("One Dof Test Rack" in tiles and sum(1 for t in tiles if t.startswith("CAN ")) == 8,
                  f"the home is tiles of deployments and stations ({len(tiles)} tiles: {tiles[:3]}…)")
            cells = page.evaluate("[...document.querySelectorAll('#where [data-verdict]')].map(c => [c.dataset.device, c.dataset.gate, c.dataset.verdict])")
            served = {(c["device"], c["gate"].split()[0]): c["verdict"] for c in json.loads((data / "gates.json").read_text())["rows"]}
            check(len(cells) == len(served) and all(served.get((d, g)) == v for d, g, v in cells),
                  f"the home's Where it fails matrix shows every gate cell with its verdict ({len(cells)} of {len(served)})")
            handle = page.locator("nav.choose[data-resizable]")
            w0 = handle.evaluate("el => el.getBoundingClientRect().width")
            box = handle.bounding_box()
            page.mouse.move(box["x"] + box["width"] - 1, box["y"] + 40)
            grip = page.evaluate("""(x) => { const el = document.elementFromPoint(x, %d); return el ? el.className || el.tagName : null; }""" % int(box["y"] + 40), box["x"] + box["width"] - 1)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] + 119, box["y"] + 40, steps=8)
            page.mouse.up()
            w1 = handle.evaluate("el => el.getBoundingClientRect().width")
            check(abs((w1 - w0) - 120) < 4, f"the home's Choose column is data-resizable: dragged 120 px wider ({w0:.0f} -> {w1:.0f} px; grip {grip})")
            page.evaluate("localStorage.clear()")

            # 2. the search: a station suggestion, then the results page
            page.click("#site-q")
            page.keyboard.type("CAN 12")
            page.wait_for_selector("#sm .sm-typed a.sg", timeout=10000)
            hrefs = page.evaluate("[...document.querySelectorAll('#sm .sm-typed a.sg')].map(a => [a.getAttribute('href'), a.textContent])")
            check(any(h == f"/{DEP}/can12/" for h, _t in hrefs) and any("/runs/" in h for h, _t in hrefs),
                  f"typing 'CAN 12' suggests the station and its runs ({[h for h, _t in hrefs][:4]})")
            still("2-search")
            page.keyboard.press("Enter")
            page.wait_for_url(re.compile(r"/search/\?q=CAN"), timeout=20000)
            page.locator("data-views tbody tr, data-views .dv-row, data-views [role=row]").first.wait_for(timeout=30000)
            page.wait_for_timeout(1200)
            texts = page.evaluate("[...document.querySelectorAll('data-views tbody tr')].slice(0, 12).map(r => r.textContent)")
            check(len(texts) > 0 and all("CAN 12" in t for t in texts), f"Enter opens /search/ with the runs of CAN 12 ({len(texts)} rows checked)")

            # 3. home -> the deployment (a tile), its record page and tabs
            page.goto(f"{base}/")
            page.locator(".groups .tile", has_text="One Dof Test Rack").first.click()
            page.wait_for_url(re.compile(rf"/{DEP}/$"), timeout=20000)
            check(page.url.endswith(f"/{DEP}/"), "the home's deployment tile opens the One Dof Test Rack")
            dep_tabs = page.evaluate("[...document.querySelectorAll('nav.tabs [role=tab]')].map(t => t.textContent.trim())")
            check(dep_tabs[:5] == ["Runs", "Gates", "Why it fails", "Coverage", "Evidence"], f"the deployment is a record page with tabs ({dep_tabs})")
            shell_checks(page, "deployment")

            # 4. runs, newest first (the Runs tab)
            runs = panel(page, "Runs · newest first")
            runs.locator("tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            still("3-deployment")
            headers = [h.strip() for h in runs.locator("thead th").all_inner_texts()]
            column = next(i for i, h in enumerate(headers) if h.startswith("Started"))
            started = [cells[column].strip() for cells in runs.locator("tbody tr").evaluate_all(
                "rows => rows.map(r => [...r.querySelectorAll('td')].map(td => td.textContent))") if len(cells) > column and cells[column].strip()]
            check(len(started) >= 5 and started == sorted(started, reverse=True), f"the visible runs are newest first ({len(started)} rows: {started[0]} ... {started[-1]})")

            # 5. the gates (was the gates layer switch): the Gates tab shows the matrix, the Runs tab hides it again
            open_tab(page, "gates")
            matrix = panel(page, "Stations × gates")
            matrix.wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            check(page.url.endswith("#gates") and matrix.is_visible(), "the Gates tab shows the station gate matrix (#gates)")
            still("4-gates")
            open_tab(page, "runs")
            page.wait_for_timeout(800)
            check(not matrix.is_visible() and panel(page, "Runs · newest first").is_visible(), "the Runs tab hides the gate matrix again")

            # WHY: Zach (2026-10-29): "The filter bar should always be on the left hand side" - measured, not class-asserted
            rail_side = page.evaluate("""() => { const d = [...document.querySelectorAll('data-dashboard .dd-body.dd-has-rail')]
                .find(b => b.offsetParent); const r = d.querySelector(':scope > .dd-rail').getBoundingClientRect();
                return {rail_right: r.right, panels_left: d.querySelector(':scope > .dd-main').getBoundingClientRect().left}; }""")
            check(rail_side["rail_right"] <= rail_side["panels_left"] + 1,
                  f"the filter rail sits left of the panels (rail ends {rail_side['rail_right']:.0f} px, panels start {rail_side['panels_left']:.0f} px)")

            # 6. a run with models, from its Open link
            page.locator(".dd-rail label", has_text="real + 4 models").first.click()
            page.wait_for_timeout(1500)
            link = panel(page, "Runs · newest first").locator("a[href*='/runs/']").first
            link.scroll_into_view_if_needed()
            href = link.get_attribute("href")
            link.click()
            page.wait_for_url(re.compile(rf"/{DEP}/runs/"), timeout=20000)
            check("t2~heldout" in page.url, f"a run with models opens ({href})")
            run_tabs = page.evaluate("[...document.querySelectorAll('nav.tabs [role=tab]')].map(t => t.textContent.trim())")
            check(run_tabs == ["Playback", "Gates", "Why it fails", "Diagnostics", "Evidence"], f"the run page's tabs ({run_tabs})")
            crumbs = page.evaluate("[...document.querySelectorAll('.trail nav.crumbs a:not(.back)')].map(a => a.textContent.trim())")
            check(crumbs[:2] == ["Home", "One Dof Test Rack"] and re.fullmatch(r"CAN \d+", crumbs[2] or "") and len(crumbs) == 4,
                  f"the run's trail is Home › deployment › station › run ({' › '.join(crumbs)})")
            angle = panel(page, "Angle · real vs models")
            angle.locator(".dv-timeseries-key").first.wait_for(timeout=30000)
            page.wait_for_timeout(2000)
            still("5-run-playback")
            keys = angle.locator(".dv-timeseries-key").evaluate_all(
                "ks => ks.map(k => ({name: k.textContent.trim(), color: getComputedStyle(k.querySelector('i')).getPropertyValue('--dv-ts-c') || getComputedStyle(k.querySelector('i')).backgroundColor}))")
            real = [k for k in keys if k["name"] == "real"]
            sims = [k for k in keys if k["name"].startswith("twin")]
            check(len(real) == 1 and REAL_HUES[0] <= hue(real[0]["color"])[0] <= REAL_HUES[1], f"the real swatch is blue ({real[0]['color'] if real else None})")
            check(len(sims) >= 2 and all(SIM_HUES[0] <= hue(k["color"])[0] <= SIM_HUES[1] and hue(k["color"])[1] > 0.35 for k in sims),
                  "every model swatch is orange (" + ", ".join(f"{k['name']} {k['color']}" for k in sims) + ")")

            count_js = """(p, rgb) => { let n = 0; for (const c of p.querySelectorAll('canvas')) { let d; try { d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; } catch { continue; }
                for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - rgb[0]) + Math.abs(d[i + 1] - rgb[1]) + Math.abs(d[i + 2] - rgb[2]) < 40 && d[i + 3] > 200) n++; } return n; }"""
            key = angle.locator(".dv-legend-key[data-legend-series='twin D · LuGre']").first
            twin_d = (0xeb, 0x68, 0x34)
            shown_px = angle.evaluate(count_js, list(twin_d))
            key.click()
            page.wait_for_timeout(600)
            hidden = angle.evaluate(count_js, list(twin_d))
            pressed = key.get_attribute("aria-pressed")
            key.click()
            page.wait_for_timeout(600)
            back = angle.evaluate(count_js, list(twin_d))
            check(pressed == "false" and back > 50 and hidden < 0.1 * back and key.get_attribute("aria-pressed") == "true",
                  f"a legend click hides the series and a second shows it (twin D pixels {shown_px} -> {hidden} -> {back})")

            measure_js = """async ([png, colours]) => {
                const img = new Image(); img.src = 'data:image/png;base64,' + png; await img.decode();
                const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
                const g = c.getContext('2d'); g.drawImage(img, 0, 0); const d = g.getImageData(0, 0, c.width, c.height).data;
                const bg = [d[0], d[1], d[2]]; const near = (i, rgb, tol) => Math.abs(d[i] - rgb[0]) + Math.abs(d[i + 1] - rgb[1]) + Math.abs(d[i + 2] - rgb[2]) < tol;
                const out = {ink: 0}; for (const k of Object.keys(colours)) out[k] = 0;
                for (let i = 0; i < d.length; i += 4) { const x = (i / 4) % c.width, y = Math.floor(i / 4 / c.width);
                  if (x > 0.75 * c.width && y < 0.3 * c.height) continue;
                  if (!near(i, bg, 24)) out.ink++; for (const [k, rgb] of Object.entries(colours)) if (near(i, rgb, 60)) out[k]++; }
                return out; }"""
            page.evaluate("history.replaceState(null, '', '#t=4'); dispatchEvent(new HashChangeEvent('hashchange'))")
            page.wait_for_timeout(1000)
            for title in ("Output link · 3D in its joint frame", "Output link · top (down the joint axis)"):
                p3 = panel(page, title)
                p3.scroll_into_view_if_needed()
                p3.locator("canvas").first.wait_for(timeout=30000)
                page.wait_for_timeout(1500)
                canvas = max(p3.locator("canvas").all(), key=lambda c: (c.bounding_box() or {"width": 0})["width"] * (c.bounding_box() or {"height": 0})["height"])
                png = base64.b64encode(canvas.screenshot()).decode()
                found = page.evaluate(measure_js, [png, {"real": [0x2a, 0x78, 0xd6], "model": [0xeb, 0x68, 0x34]}])
                bb = canvas.bounding_box()
                check(found["ink"] > 0.002 * bb["width"] * bb["height"] and found["real"] > 20 and found["model"] > 20,
                      f"{title}: a non-blank canvas with a real (blue) and a model (orange) series drawn ({found})")
            still("5b-trajectory3d")
            angle.scroll_into_view_if_needed()

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
            page.locator("button[aria-label*='Pause' i]").first.click()

            # 7. the run's Gates and Diagnostics tabs (was the run's gates layer)
            run_slug = re.search(r"/runs/([^/]+)/", page.url).group(1)
            run_dir = data / "runs" / run_slug
            open_tab(page, "gates")
            page.wait_for_timeout(400)
            gate_cells = page.evaluate("[...document.querySelectorAll('[data-tab=gates] [data-verdict]')].length")
            check(gate_cells >= 11, f"the run's Gates tab shows its station's gate cells ({gate_cells})")
            still("6-run-gates")
            open_tab(page, "diagnostics")
            dx_rows = page.evaluate("document.querySelectorAll('[data-tab=diagnostics] table.s2r-dx tbody tr').length")
            want_dx = len(json.loads((run_dir / "diagnostics.json").read_text())["rows"])
            check(dx_rows == want_dx and want_dx > 0, f"the run's Diagnostics tab lists every diagnostic of this run ({dx_rows} of {want_dx})")
            still("7-run-diagnostics")

            # 8. why it fails: one row per gate cell the newest acceptance does not pass, explained without scrolling sideways
            page.goto(f"{base}/{DEP}/#why")
            why = panel(page, "Why it fails")
            why.locator("tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            why.scroll_into_view_if_needed()
            still("8-why-it-fails")
            open_cells = {(f"CAN {can}", g["id"]) for can, st in doc["stations"].items() for g in st["gates"] if g["status"] != "pass"}
            rows = json.loads((data / "why.json").read_text())["rows"]
            listed = {(r["device"], r["gate_id"]) for r in rows if r["status"] != "pass"}
            check(listed == open_cells and all(r.get("next") and r.get("why") and r.get("measured") for r in rows),
                  f"Why it fails has one row per cell {path.name} does not pass ({len(listed)} of {len(open_cells)}), each with a number, a why and a next step")
            check(("CAN 12", "T3") in listed and next(r for r in rows if (r["device"], r["gate_id"]) == ("CAN 12", "T3"))["status"] == "fail",
                  "CAN 12 T3 is listed as a fail (the stale acceptance had it passing)")
            check(sum(1 for r in rows if r["next"].startswith("blocked on Zach")) > 0 and any(r.get("floor_rules") and "pending" in r["floor_rules"] for r in rows),
                  "rows name what is blocked on Zach, and the floor rules where the verdict depends on them")
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
            page.set_viewport_size({"width": 1280, "height": 900})
            page.wait_for_timeout(1000)
            evidence_text = panel(page, "Evidence files").inner_text()
            check(path.name in evidence_text.replace("…", "") or doc["generated_at"] in evidence_text,
                  f"the page names its gates' source and date ({path.name}, {doc['generated_at']})")
            panel(page, "Caveats").scroll_into_view_if_needed()
            caveat_text = panel(page, "Caveats").inner_text()
            check(all(x in caveat_text for x in ("1.72×", "2.28×", "Zach's decision, pending")),
                  "the caveats name the pick rule on CAN 11 with both numbers (safer 1.72×, declared 2.28×) and that the rule is pending")
            gains = {r["session"]: r["gains"] for r in json.loads((data / "runs.json").read_text())["rows"] if r["device"] == "CAN 11"}
            steps = ("can11_hold_kp100", "can11_hold_kp150", "can11_hold_kp200", "can11_hold_il0.25", "can11_hold_il0.5")
            check(all(s in gains for s in steps) and len({gains[s] for s in steps}) == 5,
                  "the 10-29 CAN 11 gain steps each show their own board gains (" + "; ".join(gains.get(s, "?") for s in steps) + ")")
            # a row with a worst window opens that run's playback there (the Playback tab, its clock at the window)
            expected = next(r for r in rows if r["gate_id"] == "T2" and r.get("page") and "tr=" in r["page"])
            t0, t1 = (float(x) for x in re.search(r"tr=([\d.]+),([\d.]+)", expected["page"]).groups())
            why.scroll_into_view_if_needed()
            cell = why.locator("tbody td", has_text=re.compile(rf"^\s*T2 fidelity — {expected['status']}")).filter(has_text=expected["measured"].split(" ·")[0]).first
            cell.click()
            worst = re.search(r"/runs/([^/]+)/", expected["page"]).group(1)
            page.wait_for_url(re.compile(re.escape(worst)), timeout=20000)
            readout = page.locator(".dv-pb-time").first
            readout.wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            now = float(re.match(r"[\d.]+", readout.inner_text()).group())
            check(abs(now - t0) < 0.05 and page.locator("[role=tabpanel][data-tab=playback]").get_attribute("hidden") is None,
                  f"{expected['device']} T2 opens its worst held-out window on the Playback tab ({worst}, clock {now:.2f} s, window {t0:.2f}-{t1:.2f} s)")
            still("9-why-run")
            open_tab(page, "why")
            torque = panel(page, "Torque gap by term family")
            torque.wait_for(timeout=30000)
            page.wait_for_timeout(2500)
            check(torque.locator("canvas, svg").count() > 0 and panel(page, "Move error by phase").count() == 1,
                  "the run's Why it fails tab shows the station's residual-decomposition plots")
            still("10-run-why")

            # 8b. a station's Schedule tab (2026-10-29, bam_rack_twin.schedule): the plan before anything runs - targets grey dashed,
            # the twin's orange model curve, coverage heatmaps train vs held-out, and the run commands; every run "not run yet"
            sched_dir = data / "schedule" / "can11"
            summary = json.loads((sched_dir / "summary.json").read_text())
            check(summary["schema"] == "bam_rack_twin.schedule/1" and summary["station"] == "can11" and summary["status"] == "not run yet",
                  f"CAN 11's schedule is served beside the deployment's data ({summary['trajectories']} trajectories, {summary['runs']} runs, not run yet)")
            sys.path.insert(0, str(REPO / "vendor" / "data-ui" / "dist" / "python"))
            import data_ui_base  # noqa: PLC0415
            view = data_ui_base.loads((out / "views" / "station-schedule.base").read_text())
            planned = next(v for v in view["views"] if v["name"] == "Planned trajectories")
            dash = planned["chart"]["encoding"]["strokeDash"]
            colors = planned["chart"]["encoding"]["color"]["scale"]
            check(dash["field"] == "series" and colors["domain"][0] == "target" and colors["range"][0] == "#8b9099"
                  and all(r == "var(--data-series-2)" or "data-series-2" in r for r in colors["range"][1:]),
                  "the planned trajectories draw the target grey dashed and each model orange (the site's colour convention)")
            page.goto(f"{base}/{DEP}/can11/")
            page.wait_for_load_state("load")
            st_tabs = page.evaluate("[...document.querySelectorAll('nav.tabs [role=tab]')].map(t => t.textContent.trim())")
            check("Schedule" in st_tabs, f"CAN 11's station page has a Schedule tab ({st_tabs})")
            open_tab(page, "schedule")
            sched = page.locator("[role=tabpanel][data-tab=schedule]")
            commands = sched.locator(".s2r-commands pre")
            n_commands = commands.count()
            texts = commands.all_inner_texts()
            check(n_commands == len(summary["commands"]) and all("--plan /" in t and "\n" not in t.strip() for t in texts),
                  f"the Schedule tab lists one one-line run command per plan ({n_commands} of {len(summary['commands'])})")
            check(sched.get_by_text("not run yet").count() > 0 and sched.locator(".s2r-commands [data-runner=runnable]").count() >= 1
                  and sched.locator(".s2r-commands [data-runner=unsupported]").count() >= 1,
                  "the Schedule tab says the schedule has not run yet, and which plans the runner can play today")
            heat = {name: panel(page, name) for name in ("Coverage · q × qd · train", "Coverage · q × qd · held-out",
                                                         "Coverage · qd × qdd · train", "Coverage · qd × qdd · held-out")}
            lines = panel(page, "Planned trajectories")
            lines.wait_for(timeout=30000)
            for item in heat.values():
                item.wait_for(timeout=30000)
            page.wait_for_timeout(3000)
            drawn = {name: item.locator("canvas, svg").count() > 0 and item.evaluate("el => el.getBoundingClientRect().height") > 120 for name, item in heat.items()}
            check(all(drawn.values()) and lines.locator("canvas, svg").count() > 0,
                  f"the planned trajectories and four coverage heatmaps are drawn ({drawn})")
            boxes = {name: item.evaluate("el => { const b = el.getBoundingClientRect(); return [b.left, b.right, b.top]; }") for name, item in heat.items()}
            side = boxes["Coverage · q × qd · train"][1] <= boxes["Coverage · q × qd · held-out"][0] + 1 and \
                abs(boxes["Coverage · q × qd · train"][2] - boxes["Coverage · q × qd · held-out"][2]) < 2
            check(side, f"train and held-out coverage sit side by side, train left ({boxes['Coverage · q × qd · train']} | {boxes['Coverage · q × qd · held-out']})")
            # data-ui charts draw on canvas, so the colours are measured in the pixels, not read from a legend's text
            lines.scroll_into_view_if_needed()
            page.wait_for_timeout(800)
            canvas = max(lines.locator("canvas").all(), key=lambda c: (c.bounding_box() or {"width": 0})["width"] * (c.bounding_box() or {"height": 0})["height"])
            found = page.evaluate(measure_js, [base64.b64encode(canvas.screenshot()).decode(), {"target": [0x8b, 0x90, 0x99], "model": [0xeb, 0x68, 0x34]}])
            check(found["target"] > 50 and found["model"] > 50, f"the planned trajectories draw grey target pixels and orange model pixels ({found})")
            rail = page.evaluate("""() => { const d = [...document.querySelectorAll('[data-tab=schedule] data-dashboard .dd-body.dd-has-rail')]
                .find(b => b.offsetParent); if (!d) return null; const r = d.querySelector(':scope > .dd-rail').getBoundingClientRect();
                return {rail_right: r.right, panels_left: d.querySelector(':scope > .dd-main').getBoundingClientRect().left}; }""")
            check(rail is not None and rail["rail_right"] <= rail["panels_left"] + 1,
                  f"the Schedule tab's filter rail sits left of its panels ({rail})")
            runs_panel = panel(page, "Planned runs")
            runs_panel.locator("tbody tr").first.wait_for(timeout=30000)
            row_text = runs_panel.locator("tbody tr").first.inner_text()
            check("not run yet" in row_text, f"every planned run's status reads not run yet ({row_text[:80]!r})")
            still("8b-schedule")

            # 9. the Analysis area: Why it fails as one readable report
            page.goto(f"{base}/analysis/why-it-fails/")
            report_cells = page.evaluate("[...document.querySelectorAll('.s2r-why [data-cell]')].map(r => r.dataset.cell)")
            check(set(report_cells) >= {f"{d} {g}" for d, g in open_cells} and page.locator("aside[data-resizable]").count() == 1,
                  f"Analysis › Why it fails lists every open cell ({len(set(report_cells))} rows), beside a resizable contents column")
            still("11-analysis-why")

            # 10. a phone: no sideways scroll anywhere on the click path, the search still in the bar
            page.set_viewport_size({"width": 390, "height": 844})
            for url in ("/", f"/{DEP}/", f"/{DEP}/runs/{run_slug}/", f"/{DEP}/can12/", f"/{DEP}/can11/#schedule", "/analysis/why-it-fails/"):
                page.goto(base + url)
                page.wait_for_load_state("load")
                page.wait_for_timeout(1500)
                ok, detail = no_sideways_scroll(page)
                q = page.evaluate("(() => { const b = document.querySelector('#site-q').getBoundingClientRect(); return [b.left, b.right, innerWidth]; })()")
                check(ok and q[0] >= 0 and q[1] <= q[2] + 0.5, f"at 390 px {url} has no sideways scroll ({detail}) and the search fits ({round(q[0])}-{round(q[1])})")
                if url == "/":
                    still("12-home-390")
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
