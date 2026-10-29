"""sim2real on catalog-workbench, clicked through headless: the acceptance checks of the migration.

    python3 /home/bam/sim2real-worktrees/catalog-workbench/site/build.py
    uv run --no-project --with playwright python /home/bam/sim2real-worktrees/catalog-workbench/site/tests/test_site_flow.py
    uv run --no-project --with playwright python /home/bam/sim2real-worktrees/catalog-workbench/site/tests/test_site_flow.py --record /abs/capture/dir

Since data-ui 006e9d5 (2026-10-29, PEP 0010 P3 / P5, CONTRACT §33 and §35) also the views it adopts, each measured as drawn: the
gate matrix (cells, columns' x, tones), its peek, the KPI trend against its target, the rack roll-up, threshold bands (Vega's own
guides and y scale), the evidence peek and its link, the path overlay (the scene's painted segments and tube), the verdict voxels
(every drawn cell's value), and a run picked from the runs table (the network log, the clock, Back and Forward).

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
import contextlib
import hashlib
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[1]
REPO = SITE.parent
sys.path.insert(0, str(SITE))
sys.path.insert(1, str(SITE / "vendor"))
# WHY the newest installed shell, not a pinned build: 1243 was cleaned out of the cache on 2026-10-29 and the run died at launch
EXE = str(max(Path.home().glob(".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
              key=lambda p: int(p.parts[-3].rsplit("-", 1)[1])))
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


def acceptance_history() -> list[tuple[Path, str, dict]]:
    """Every acceptance file of all eight stations, oldest first: (path, generated_at, {(device, gate): status})."""
    out = []
    for path in Path("/archive/datasets/bam_rig").glob("rack_2026-*/analysis/acceptance*.json"):
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and str(doc.get("schema", "")).startswith("bam_rack_twin.acceptance/") and doc.get("generated_at") and len(doc.get("stations") or {}) >= 8:
            out.append((path, doc["generated_at"], {(f"CAN {can}", g["id"]): g["status"] for can, st in doc["stations"].items() for g in st["gates"]}))
    return sorted(out, key=lambda x: x[1])


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


# ---- data-ui 006e9d5 (PEP 0010 P3 / P5, CONTRACT §33, §35): what the views drew, read from the page --------------------------
# A visible panel's <data-views> by its view's name (the open tab's: a hidden tab's dashboard is not measured).
VIEW_JS = """(name) => [...document.querySelectorAll('.dd-panel[data-panel]')].find((s) => { const e = s.querySelector(':scope > data-views');
    return e && e.view && e.view.name === name && s.getClientRects().length > 0; })"""
# the gate matrix as drawn: its column headers, and per row its header and every cell (state, tone, glyph, label, box, colours)
MATRIX_JS = """([scope, name]) => { const root = document.querySelector(scope) || document; const s = [...root.querySelectorAll('.dd-panel[data-panel]')]
    .find((x) => { const e = x.querySelector(':scope > data-views'); return e && e.view && e.view.name === name && x.getClientRects().length > 0; });
  const g = s && s.querySelector('[role=grid]'); if (!g) return null; const box = (e) => { const r = e.getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; };
  return { heads: [...g.querySelectorAll('[role=columnheader][data-column]')].map((h) => ({ column: h.dataset.column, text: h.textContent.trim(), box: box(h) })),
    rows: [...g.querySelectorAll('[role=row]')].filter((r) => r.querySelector('[role=gridcell]')).map((r) => ({ label: (r.querySelector('[role=rowheader]') || {}).textContent?.trim() || '',
      cells: [...r.querySelectorAll('[role=gridcell]')].map((c) => { const gl = c.querySelector('.dv-tracker-glyph'); const cs = getComputedStyle(c);
        return { column: c.dataset.column, state: c.dataset.state ?? null, na: c.hasAttribute('data-na'), id: c.dataset.id ?? null, aria: c.getAttribute('aria-label'),
                 tone: (c.className.match(/dv-tone-(\\w+)/) || [])[1] || null, glyph: gl ? gl.textContent.trim() : '', box: box(c), bg: cs.backgroundColor, fg: gl ? getComputedStyle(gl).color : cs.color }; }) })) }; }"""
# a timeseries card's limit guides (CONTRACT §35: the Vega dataset `guides`) and its y scale at each limit
GUIDES_JS = """(name) => { const s = (%s)(name); const t = s && s.querySelector('.dv-view-timeseries'); const v = t && t.vegaView; if (!v) return null;
  let data; try { data = v.data('guides'); } catch (e) { return { missing: String(e) }; } const y = v.scale('y'); const h = v.height();
  return { limits: data.filter((d) => /^limit:/.test(d.guide)).map((d) => ({ guide: d.guide, series: d.series ?? null, value: d.value, py: y(d.value) })),
           zones: data.filter((d) => /^zone:/.test(d.guide)).length, height: h }; }""" % VIEW_JS
# a KPI card's sparkline points (its Vega line), its big number, label and target text
KPI_JS = """(name) => { const s = (%s)(name); if (!s) return null; return [...s.querySelectorAll('data-kpi')].map((card) => {
  const ch = card.querySelector('.dv-kpi-history .dv-view-chart'); const v = ch && ch.vegaView; const pts = []; const rules = [];
  const walk = (n) => { if (!n) return; if (n.marktype === 'line' && n.role === 'mark') for (const i of n.items || []) if (i.datum && i.datum.passing !== undefined) pts.push(i.datum.passing);
    if (n.marktype === 'rule' && n.role === 'mark') for (const i of n.items || []) rules.push(i.y); for (const i of n.items || []) if (i.items) walk(i); };
  if (v) walk(v.scenegraph().root); const r = (ch || card).getBoundingClientRect();
  return { label: (card.querySelector('.dv-kpi-label') || {}).textContent || '', value: (card.querySelector('.dv-kpi-value') || {}).textContent || '',
           text: card.textContent, points: pts, rules: rules.length, width: r.width, height: r.height }; }); }""" % VIEW_JS
# a tree table's status cells: every row's id and the word and state its `worst` cell draws
TREE_JS = """(name) => { const s = (%s)(name); if (!s) return null; return [...s.querySelectorAll('tbody tr[data-id]')].map((tr) => {
  const b = tr.querySelector('td[data-col="worst"] .dv-state'); const label = tr.querySelector('td[data-col="label"]');
  return { label: label ? label.textContent.trim() : '', state: b ? b.dataset.state : null, word: b ? (b.querySelector('.dv-state-word') || {}).textContent : null,
           glyph: b ? (b.querySelector('.dv-state-glyph') || {}).textContent : null, shown: b ? b.getBoundingClientRect().width > 0 : false }; }); }""" % VIEW_JS
PEEK_JS = """() => { const p = [...document.querySelectorAll('.dv-peek')].find((x) => !x.hidden && x.getClientRects().length > 0); if (!p) return null;
  const a = p.querySelector('a.dv-peek-link'); const r = p.getBoundingClientRect();
  return { text: p.textContent, link: a ? a.href : null, linkText: a ? a.textContent : null, box: [r.left, r.right, r.top, r.bottom],
           sections: [...p.querySelectorAll('.dv-peek-view[data-section]')].map((x) => { const e = x.querySelector('data-views'); const m = e && e.model;
             return { name: x.dataset.section, rows: m ? m.rows.length : null, height: x.getBoundingClientRect().height }; }) }; }"""
SCENE_JS = """(name) => { const s = (%s)(name); const el = s && s.querySelector('.dv-scene3d'); const h = el && el.scene3d; if (!h || !h.renders()) return null;
  const out = { text: s.textContent }; for (const k of ['overlay', 'tube', 'ramp', 'cellColours']) { try { out[k] = typeof h[k] === 'function' ? h[k]() : null; } catch (e) { out[k] = String(e); } }
  const t = s.querySelector(':scope > data-views').tokens(); out.tone = t.tone || null; out.s1 = t.series ? t.series[0] : null; return out; }""" % VIEW_JS
RANK = {"pass": 0, "partial": 1, "warn": 1, "not_run": 2, "fail": 4}  # RobotDx's ranks (data-ui STATUS_ORDER), the test's own copy
RANK_WORD = {0: "pass", 1: "warn", 2: "not run", 4: "fail"}
TONE = {"pass": "good", "partial": "warn", "warn": "warn", "fail": "bad", "not_run": "muted"}


def rgb_hue(css: str) -> tuple[float, float]:
    """(hue in degrees, saturation) of a computed CSS colour (rgb()/rgba()/color(srgb …))."""
    nums = [float(x) for x in re.findall(r"[\d.]+", css)[:3]]
    if "color(" in css:
        nums = [v * 255 for v in nums]
    h, _l, s = colorsys.rgb_to_hls(*(v / 255 for v in nums))
    return h * 360, s


@contextlib.contextmanager
def guard(what: str):
    """A block of checks that fails as one check if the page throws (a view missing), so the run goes on to the next block."""
    try:
        yield
    except Exception as error:  # noqa: BLE001
        check(False, f"{what}: stopped by {type(error).__name__}: {str(error).splitlines()[0][:200]}")


def soft_wait(page, js: str, arg=None, timeout: int = 30000) -> bool:
    """page.wait_for_function that reports instead of raising, so a missing view fails its own check and the run goes on."""
    try:
        page.wait_for_function(js, arg=arg, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_view(page, name: str, ready: str = "true", timeout: int = 30000) -> bool:
    """Wait until the visible panel of that view exists and `ready` (a JS expression over s, its section) holds."""
    try:
        page.wait_for_function(f"(name) => {{ const s = ({VIEW_JS})(name); return !!s && ({ready}); }}", arg=name, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001  (a check reports it)
        return False


def matrix_check(m, served: dict, where: str) -> None:
    """The drawn matrix against the served gate rows: T1-T11 in order, one row per station, each cell its verdict (88 cells),
    each column one x in every row (getBoundingClientRect, 0.5 px), a glyph and an accessible name in every cell."""
    if not m:
        check(False, f"{where}: data-ui's gate matrix is drawn ([role=grid] not found)")
        return
    heads = [h["text"] for h in m["heads"]]
    cells = {(r["label"], c["column"]): c for r in m["rows"] for c in r["cells"] if not c["na"]}
    differ = sorted(k for k in served.keys() | cells.keys() if served.get(k) != (cells.get(k) or {}).get("state"))
    check(heads == [f"T{i}" for i in range(1, 12)] and len(m["rows"]) == 8 and not differ,
          f"{where}: data-ui's gate matrix is stations × T1-T11 with every cell its verdict ({len(cells)} of {len(served)} cells; columns {heads}; differ {differ[:4]})")
    lefts = {}
    for r in m["rows"]:
        for c in r["cells"]:
            lefts.setdefault(c["column"], []).append(c["box"][0])
    spread = max((max(v) - min(v)) for v in lefts.values()) if lefts else 99
    bare = [c["aria"] for r in m["rows"] for c in r["cells"] if not c["glyph"] or not c["aria"]]
    check(spread <= 0.5 and not bare, f"{where}: each gate column is one x in every row (spread {spread:.2f} px) and every cell has a glyph and a name ({len(bare)} bare)")
    tones = {(r["label"], c["column"]): c["tone"] for r in m["rows"] for c in r["cells"] if not c["na"]}
    wrong = sorted(k for k, v in served.items() if tones.get(k) != TONE.get(v))
    hues = {v: [] for v in ("pass", "fail")}
    for k, v in served.items():
        if v in hues and k in cells:
            hues[v].append(rgb_hue(cells[k]["fg"]))
    green = all(80 <= h <= 170 and s > 0.2 for h, s in hues["pass"])
    red = all((h <= 20 or h >= 340) and s > 0.3 for h, s in hues["fail"])
    check(not wrong and green and red and hues["pass"] and hues["fail"],
          f"{where}: the cells wear RobotDx's status tones (pass good, partial warn, not run muted, fail bad; {len(wrong)} wrong), "
          f"measured: pass glyphs green {sorted({round(h) for h, _s in hues['pass']})}, fail glyphs red {sorted({round(h) for h, _s in hues['fail']})}")


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
            # WHY changed (data-ui 006e9d5): the home's matrix is data-ui's gate_matrix once the kit loads (the static one is its
            # fallback), so its cells are read as data-ui draws them ([role=gridcell] data-state under its row and column headers)
            served = {(c["device"], c["gate"].split()[0]): c["verdict"] for c in json.loads((data / "gates.json").read_text())["rows"]}
            soft_wait(page, "() => document.querySelectorAll('#where [role=grid] [role=gridcell]').length >= 88")
            page.wait_for_timeout(500)
            home_m = page.evaluate(MATRIX_JS, ["#where", "Stations × gates"])
            cells = [(r["label"], c["column"], c["state"]) for r in (home_m or {}).get("rows", []) for c in r["cells"] if not c["na"]]
            check(len(cells) == len(served) and all(served.get((d, g)) == v for d, g, v in cells),
                  f"the home's Where it fails matrix shows every gate cell with its verdict ({len(cells)} of {len(served)})")
            matrix_check(home_m, served, "the home")
            still("1b-home-gate-matrix")
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

            # 5b. data-ui 006e9d5 on the Gates tab: gate_matrix, its peek, kpi_trend against every cell, rollup_tree
            with guard("the Gates tab's gate views"):
                wait_view(page, "Stations × gates", "s.querySelectorAll('[role=gridcell]').length >= 88")
                page.wait_for_timeout(500)
                matrix_check(page.evaluate(MATRIX_JS, ["[role=tabpanel][data-tab=gates]", "Stations × gates"]), served, "the deployment's Gates tab")
                page.locator("[role=tabpanel][data-tab=gates] [role=gridcell][aria-label^='CAN 12 · T3']").first.click()
                soft_wait(page, f"() => !!({PEEK_JS})()", timeout=10000)
                peek = page.evaluate(PEEK_JS) or {}
                still("4b-gate-peek")
                check("T3" in (peek.get("text") or "") and "fail" in (peek.get("text") or "") and (peek.get("link") or "").endswith("/analysis/why-it-fails/#can12-T3"),
                      f"a matrix cell opens its gate in the side peek, its why one link away (CAN 12 T3: link {peek.get('link')})")
                page.keyboard.press("Escape")
                history = acceptance_history()
                wait_view(page, "Gate cells passing", "!!s.querySelector('data-kpi .dv-kpi-history .dv-view-chart')")
                page.wait_for_timeout(800)
                rack_card = (page.evaluate(KPI_JS, "Gate cells passing") or [{}])[0]
                want_rack = [sum(1 for v in cells_.values() if v == "pass") for _p, _d, cells_ in history]
                check(rack_card.get("points") == want_rack and re.search(r"\b32\b", rack_card.get("value") or "") and "88" in (rack_card.get("text") or "")
                      and rack_card.get("rules", 0) >= 1 and rack_card.get("width", 0) > 100,
                      f"kpi_trend: the rack's cells passing is the newest acceptance's, its trend every acceptance file's ({rack_card.get('points')} vs {want_rack}), "
                      f"88 cells its target ({rack_card.get('value')!r}, {rack_card.get('rules')} target rule, {rack_card.get('width', 0):.0f} px wide)")
                station_cards = page.evaluate(KPI_JS, "Passing per station · history") or []
                order = ["CAN 1", "CAN 4", "CAN 11", "CAN 12", "CAN 13", "CAN 14", "CAN 15", "CAN 21"]
                want_station = [[sum(1 for (d, _g), v in cells_.items() if d == dev and v == "pass") for _p, _d, cells_ in history] for dev in order]
                check([c.get("points") for c in station_cards] == want_station and all("11" in c.get("text", "") for c in station_cards),
                      f"kpi_trend per station: 8 cards, each its station's cells passing per acceptance file against its 11 cells ({len(station_cards)} cards)")
                wait_view(page, "The rack", "s.querySelectorAll('td[data-col=worst] .dv-state').length > 0")
                page.wait_for_timeout(500)
                tree = page.evaluate(TREE_JS, "The rack") or []
                gate_rows = json.loads((data / "gates.json").read_text())["rows"]
                dev_rows = json.loads((data / "devices.json").read_text())["rows"]
                plate = lambda text: "GIM43 plate" if text.split(",", 1)[0].strip().endswith("GIM43 plate") else text.split(",", 1)[0].strip()  # noqa: E731
                worst_dev = {d["device"]: max(RANK[g["verdict"]] for g in gate_rows if g["device"] == d["device"]) for d in dev_rows}
                want_tree = {"One Dof Test Rack": max(worst_dev.values())}
                for d in dev_rows:
                    want_tree[plate(d["station"])] = max(want_tree.get(plate(d["station"]), 0), worst_dev[d["device"]])
                got_tree = {}
                for r in tree:
                    key = r["label"].split(" · ")[0] if r["label"].startswith("CAN ") else r["label"]
                    got_tree[key] = r["word"]
                want_words = {**{k: RANK_WORD[v] for k, v in want_tree.items()}, **{k: RANK_WORD[v] for k, v in worst_dev.items()}}
                check(got_tree == want_words and all(r["glyph"] and r["shown"] for r in tree),
                      f"rollup_tree: the rack, its plates and stations each show the worst gate under them, word and glyph ({len(tree)} rows; "
                      f"differ {sorted(k for k in want_words if got_tree.get(k) != want_words[k])[:4]})")
                still("4c-gates-trend-rollup")
            open_tab(page, "runs")
            page.wait_for_timeout(800)
            check(not matrix.is_visible() and panel(page, "Runs · newest first").is_visible(), "the Runs tab hides the gate matrix again")

            # WHY: Zach (2026-10-29): "The filter bar should always be on the left hand side" - measured, not class-asserted
            rail_side = page.evaluate("""() => { const d = [...document.querySelectorAll('data-dashboard .dd-body.dd-has-rail')]
                .find(b => b.offsetParent); const r = d.querySelector(':scope > .dd-rail').getBoundingClientRect();
                return {rail_right: r.right, panels_left: d.querySelector(':scope > .dd-main').getBoundingClientRect().left}; }""")
            check(rail_side["rail_right"] <= rail_side["panels_left"] + 1,
                  f"the filter rail sits left of the panels (rail ends {rail_side['rail_right']:.0f} px, panels start {rail_side['panels_left']:.0f} px)")

            count_js = """(p, rgb) => { let n = 0; for (const c of p.querySelectorAll('canvas')) { let d; try { d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; } catch { continue; }
                for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - rgb[0]) + Math.abs(d[i + 1] - rgb[1]) + Math.abs(d[i + 2] - rgb[2]) < 40 && d[i + 3] > 200) n++; } return n; }"""
            # 5c. PEP 0010 P3 (CONTRACT §33): one run's samples load on a pick, a row click picks, Back and Forward restore the pick and t
            with guard('P3 navigation on the Runs tab'):
                sample_reqs: list[str] = []
                page.on("request", lambda r: sample_reqs.append(r.url) if re.search(r"/runs/[^/]+/samples\.json", r.url) else None)
                page.goto(f"{base}/{DEP}/")
                page.wait_for_load_state("load")
                runs_panel = panel(page, "Runs · newest first")
                runs_panel.locator("tbody tr").first.wait_for(timeout=30000)
                page.wait_for_timeout(1500)
                DASH = "document.querySelector('[role=tabpanel][data-tab=runs] data-dashboard')"
                waiting = page.evaluate(f"() => {{ const s = ({VIEW_JS})('Angle · the picked run'); return s ? s.getAttribute('data-wait') : 'no panel'; }}")
                check(waiting == "pick" and not sample_reqs, f"nothing picked: the picked-run panel asks for a pick (data-wait {waiting!r}) and no run's samples are read ({len(sample_reqs)})")
                run_rows = runs_panel.locator("tbody tr")
                ids = []
                for i in (0, 2):
                    before_n = len(sample_reqs)
                    run_rows.nth(i).locator("td").first.click()
                    soft_wait(page, f"() => {{ const c = {DASH}.clock; return !!c && c.end !== null && c.end !== undefined && c.end !== Infinity; }}")
                    page.wait_for_timeout(1200)
                    picked = page.evaluate(f"() => Object.values({DASH}.state.select).flatMap((s) => s.values || [])")
                    ids.append(picked[0] if len(picked) == 1 else None)
                    fetched = [u.rsplit("/runs/", 1)[1].split("/")[0] for u in sample_reqs[before_n:]]
                    if i == 0:
                        first_fetch = fetched
                        page.evaluate(f"() => {{ const c = {DASH}.clock; c.pause(); c.seek(Math.round((c.start + 0.4 * (c.end - c.start)) * 1000) / 1000); }}")
                        page.wait_for_timeout(800)
                        t_a = page.evaluate(f"() => {DASH}.clock.t")
                span = lambda run: (lambda ts: [min(ts), max(ts)])([r["t"] for r in json.loads((data / "runs" / run / "samples.json").read_text())["rows"]])  # noqa: E731
                clock = page.evaluate(f"() => {{ const c = {DASH}.clock; return [c.start, c.end, c.t]; }}")
                check(None not in ids and ids[0] != ids[1] and first_fetch == [ids[0]] and fetched == [ids[1]] and abs(clock[0] - span(ids[1])[0]) < 1e-6
                      and abs(clock[1] - span(ids[1])[1]) < 1e-6,
                      f"a runs-table row click picks the run and reads only its samples (fetched {first_fetch} then {fetched}); the clock spans its t ({clock[:2]} vs {span(ids[1]) if ids[1] else '?'})")
                angle_pick = panel(page, "Angle · the picked run")
                blue = angle_pick.evaluate(count_js, [0x2a, 0x78, 0xd6]) if angle_pick.count() else 0
                still("4d-picked-run")
                check(ids[1] is not None and ids[1] in unquote(page.url) and blue > 50, f"the URL names the pick and the picked run's angle is drawn, real in blue ({blue} blue px)")
                n_fetch = len(sample_reqs)
                page.go_back()
                page.wait_for_timeout(2500)
                back = page.evaluate(f"() => {{ const c = {DASH}.clock; return [Object.values({DASH}.state.select).flatMap((s) => s.values || []), c.start, c.end, c.t]; }}")
                check(back[0] == [ids[0]] and abs(back[1] - span(ids[0])[0]) < 1e-6 and abs(back[2] - span(ids[0])[1]) < 1e-6 and abs(back[3] - t_a) < 1e-3
                      and len(sample_reqs) == n_fetch,
                      f"Back restores the first pick and its t ({back[0]}, t {back[3]} vs {t_a}; its file not fetched again: {len(sample_reqs) - n_fetch} new)")
                page.go_forward()
                page.wait_for_timeout(2500)
                fwd = page.evaluate(f"() => {{ const c = {DASH}.clock; return [Object.values({DASH}.state.select).flatMap((s) => s.values || []), c.start, c.end]; }}")
                check(fwd[0] == [ids[1]] and abs(fwd[2] - span(ids[1])[1]) < 1e-6, f"Forward restores the second pick ({fwd[0]})")
            page.goto(f"{base}/{DEP}/")
            page.wait_for_load_state("load")
            panel(page, "Runs · newest first").locator("tbody tr").first.wait_for(timeout=30000)
            page.wait_for_timeout(1500)

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

            # 6b. threshold_band and path_overlay on the run (CONTRACT §35): T4's stop allocation and T2's 1.5x floor drawn as the
            # station's limits, per series; the output link coloured by its distance from the target, T4 at the marker as a tube
            with guard("the run's limits and path overlay"):
                slug = re.search(r"/runs/([^/]+)/", page.url).group(1)
                device = next(r["device"] for r in json.loads((data / "runs.json").read_text())["rows"] if r["run"] == slug)
                t4_text = next(g["target"] for g in json.loads((data / "gates.json").read_text())["rows"] if g["device"] == device and g["gate"].startswith("T4"))
                t4 = float(re.search(r"p90\s*<=\s*([\d.]+)\s*mrad", t4_text).group(1))
                t2 = next(g["error_hi"] for g in json.loads((data / "run_gates.json").read_text())["rows"]
                          if g["device"] == device and g["diagnostic"] == "stock.model_error" and g.get("error_hi"))
                for title, lim, what in (("Error against the target (target − each)", t4, "T4's stop allocation"),
                                         ("Model error against real (real − model)", t2, "T2's 1.5× floor")):
                    target_panel = panel(page, title)
                    target_panel.scroll_into_view_if_needed()
                    wait_view(page, title, "!!s.querySelector('.dv-view-timeseries') && !!s.querySelector('.dv-view-timeseries').vegaView")
                    page.wait_for_timeout(1200)
                    g = page.evaluate(GUIDES_JS, title) or {}
                    limits_drawn = g.get("limits") or []
                    series = {x["series"] for x in limits_drawn}
                    per_series_ok = bool(series) and all({round(x["value"], 6) for x in limits_drawn if x["series"] == s_} == {round(-lim, 6), round(lim, 6)} for s_ in series)
                    inside = all(0 <= x["py"] <= g.get("height", 0) for x in limits_drawn)
                    check(per_series_ok and inside and g.get("zones", 0) > 0,
                          f"threshold_band on {title!r}: {what} ±{lim:.4g} mrad drawn per series ({len(series)} series, {len(limits_drawn)} limit points, "
                          f"{g.get('zones')} zone points, every limit's y inside the plot: {inside})")
                still("5c-run-limits")
                p3d = panel(page, "Output link · distance from the target")
                p3d.scroll_into_view_if_needed()
                wait_view(page, "Output link · distance from the target", "!!s.querySelector('.dv-scene3d') && !!s.querySelector('.dv-scene3d').scene3d && s.querySelector('.dv-scene3d').scene3d.renders() > 0")
                page.wait_for_timeout(1500)
                sc = page.evaluate(SCENE_JS, "Output link · distance from the target") or {}
                ov, tube = sc.get("overlay") or {}, sc.get("tube") or {}
                poses = [r for r in json.loads((data / "runs" / slug / "poses.json").read_text())["rows"] if r["body"] == "marker_100mm" and r["situation"] != "target"]
                errs = [r["err_mm"] for r in poses if r.get("err_mm") is not None]
                check(ov.get("color") == "err_mm" and len(ov.get("segments") or []) > 10 and errs and abs(ov.get("min", -1) - min(errs)) < 1e-9 and abs(ov.get("max", -1) - max(errs)) < 1e-9,
                      f"path_overlay colour: the paths are painted by err_mm over its drawn range ({len(ov.get('segments') or [])} segments, "
                      f"{ov.get('min')}..{ov.get('max')} vs the poses' {min(errs) if errs else None}..{max(errs) if errs else None} mm)")
                check(tube.get("radius") is not None and abs(tube["radius"] - round(t4 * 0.1, 4)) < 1e-9 and len(tube.get("rings") or []) >= 2
                      and f"± {round(t4 * 0.1, 4):g} mm" in sc.get("text", ""),
                      f"path_overlay tolerance: T4's {t4:g} mrad at the 100 mm marker is the target's tube (radius {tube.get('radius')} mm, {len(tube.get('rings') or [])} rings, legend '± … mm')")
                still("5d-path-overlay")
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

            # 8c. a station's Gates tab (CONTRACT §35): T2's 1.5x floor as each model's band over its whole-run errors, and the run
            # checks' evidence in the side peek, whose link lands on the run's playback at its window
            with guard("CAN 12's Gates tab"):
                page.goto(f"{base}/{DEP}/can12/#gates")
                page.wait_for_load_state("load")
                rg = json.loads((data / "run_gates.json").read_text())["rows"]
                mine = [g for g in rg if g["device"] == "CAN 12" and g["diagnostic"] == "stock.model_error"]
                wait_view(page, "Model error per run · T2", "!!s.querySelector('.dv-view-timeseries') && !!s.querySelector('.dv-view-timeseries').vegaView")
                page.wait_for_timeout(1500)
                g = page.evaluate(GUIDES_JS, "Model error per run · T2") or {}
                want = {(r["title"], round(r["error_hi"], 6)) for r in mine}
                got = {(x["series"], round(x["value"], 6)) for x in g.get("limits") or [] if x["guide"] == "limit:error_hi"}
                check(mine and got == want and all(0 <= x["py"] <= g.get("height", 0) for x in g.get("limits") or []),
                      f"threshold_band per series on CAN 12's whole-run model errors: each model's T2 limit is its rows' 1.5× floor ({sorted(got)[:2]}… vs {sorted(want)[:2]}…)")
                still("8c-station-t2")
                wait_view(page, "Run checks", "s.querySelectorAll('[role=gridcell][data-id]').length > 0")
                page.wait_for_timeout(800)
                cell = page.locator("[role=tabpanel][data-tab=gates] [role=gridcell][data-id][data-column='tracking error rms']").first
                cell.scroll_into_view_if_needed()
                aria = cell.get_attribute("aria-label")
                cell.click()
                soft_wait(page, f"() => {{ const p = ({PEEK_JS})(); return !!p && p.link && p.sections.length > 0 && p.sections.every((x) => x.rows !== null); }}", timeout=15000)
                page.wait_for_timeout(800)
                peek = page.evaluate(PEEK_JS) or {}
                still("8d-evidence-peek")
                link = peek.get("link") or ""
                run_of = re.search(r"/runs/([^/]+)/#t=([\d.]+)", link)
                section = next((x for x in peek.get("sections") or [] if x["name"] == "Evidence"), {})
                want_rows = sum(1 for r in rg if r["device"] == "CAN 12" and r["diagnostic"] in ("stock.model_error", "stock.tracking_error")
                                and run_of and r["run"] == unquote(run_of.group(1)))
                check(bool(run_of) and section.get("rows") == want_rows and section.get("height", 0) > 100 and peek.get("box", [0, 0])[1] > peek.get("box", [0, 0])[0],
                      f"evidence: a run-check cell ({aria}) opens the side peek with its evidence link (#t=) and the run's own checks ({section.get('rows')} of {want_rows} rows)")
                page.locator(".dv-peek a.dv-peek-link").first.click()
                page.wait_for_url(re.compile(r"/runs/"), timeout=20000)
                readout = page.locator(".dv-pb-time").first
                readout.wait_for(timeout=30000)
                page.wait_for_timeout(2500)
                now = float(re.match(r"[\d.]+", readout.inner_text()).group())
                check(run_of and abs(now - float(run_of.group(2))) < 0.05 and page.locator("[role=tabpanel][data-tab=playback]").get_attribute("hidden") is None,
                      f"the evidence link lands on the run's Playback at its window (clock {now:.3f} s vs #t={run_of.group(2) if run_of else '?'})")

            # 8d. verdict voxels on Coverage (CONTRACT §32, §35): runs per (q, qd) cell, every station on its own 24 x 24 grid over the range it ran
            with guard("the Coverage tab's voxels"):
                page.goto(f"{base}/{DEP}/#coverage")
                page.wait_for_load_state("load")
                name = "Runs per cell · every station"
                wait_view(page, name, "!!s.querySelector('.dv-scene3d') && !!s.querySelector('.dv-scene3d').scene3d && !!s.querySelector('.dv-scene3d').scene3d.ramp()", timeout=60000)
                page.wait_for_timeout(1500)
                panel(page, name).scroll_into_view_if_needed()
                sc = page.evaluate(SCENE_JS, name) or {}
                cov = [r for r in json.loads((data / "coverage.json").read_text())["rows"] if r.get("layer") == "path" and r.get("q_deg") is not None and r.get("qd_deg_s") is not None]
                lo = {}
                for r in cov:
                    a_ = lo.setdefault(r["device"], [r["q_deg"], r["q_deg"], r["qd_deg_s"], r["qd_deg_s"]])
                    a_[0], a_[1], a_[2], a_[3] = min(a_[0], r["q_deg"]), max(a_[1], r["q_deg"]), min(a_[2], r["qd_deg_s"]), max(a_[3], r["qd_deg_s"])
                at = lambda v, a_, b_: min(23, int((v - a_) / (b_ - a_) * 24)) if b_ > a_ else 0  # noqa: E731
                per_cell = {}
                for r in cov:
                    s_ = lo[r["device"]]
                    per_cell.setdefault((at(r["q_deg"], s_[0], s_[1]), at(r["qd_deg_s"], s_[2], s_[3])), set()).add(r["run"])
                counts = {k: len(v) for k, v in per_cell.items()}
                ramp, drawn = sc.get("ramp") or {}, sc.get("cellColours") or []
                tone = sc.get("tone") or {}
                ends_ok = bool(ramp) and tone and ramp.get("lo", "").lower() == str(tone.get("bad", "")).lower() and ramp.get("hi", "").lower() == str(tone.get("good", "")).lower()
                check(ramp and ramp.get("domain") == [min(counts.values()), max(counts.values())] and len(drawn) == len(counts)
                      and sorted(c[3] for c in drawn) == sorted(counts.values()),
                      f"voxels value: runs counts the whole rack's runs per cell ({len(drawn)} cells drawn of {len(counts)}, domain {ramp.get('domain')} vs "
                      f"[{min(counts.values())}, {max(counts.values())}] runs; {len(set(r['run'] for r in cov))} runs)")
                check(ends_ok, f"scale: verdict: few runs in the bad tone, many in the good ({ramp.get('lo')} .. {ramp.get('hi')} vs {tone.get('bad')} .. {tone.get('good')})")
                still("8e-coverage-voxels")

            # 9. the Analysis area: Why it fails as one readable report
            page.goto(f"{base}/analysis/why-it-fails/")
            report_cells = page.evaluate("[...document.querySelectorAll('.s2r-why [data-cell]')].map(r => r.dataset.cell)")
            check(set(report_cells) >= {f"{d} {g}" for d, g in open_cells} and page.locator("aside[data-resizable]").count() == 1,
                  f"Analysis › Why it fails lists every open cell ({len(set(report_cells))} rows), beside a resizable contents column")
            still("11-analysis-why")

            # 10. a phone: no sideways scroll anywhere on the click path, the search still in the bar
            page.set_viewport_size({"width": 390, "height": 844})
            for url in ("/", f"/{DEP}/", f"/{DEP}/runs/{run_slug}/", f"/{DEP}/can12/", f"/{DEP}/can11/#schedule", "/analysis/why-it-fails/",
                        f"/{DEP}/#gates", f"/{DEP}/can12/#gates"):
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
