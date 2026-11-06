"""sim2real on catalog-workbench, clicked through headless: the acceptance checks of the migration.

    python3 /home/bam/sim2real/site/build.py
    uv run --no-project --with playwright python /home/bam/sim2real/site/tests/test_site_flow.py
    uv run --no-project --with playwright python /home/bam/sim2real/site/tests/test_site_flow.py --record /abs/capture/dir

Since data-ui 006e9d5 (2026-10-29, PEP 0010 P3 / P5, CONTRACT §33 and §35) also the views it adopts, each measured as drawn: the
gate matrix (cells, columns' x, tones), its peek, the KPI trend against its target, the rack roll-up, threshold bands (Vega's own
guides and y scale), the evidence peek and its link, the path overlay (the scene's painted segments and tube), the verdict voxels
(every drawn cell's value), and a run picked from the runs table (the network log, the clock, Back and Forward).

Since 2026-11-05 also the system-ID oracle on the landing page (site/landing.py over sysid/results): six example cards, each with its
description in, typed tree, schedule coverage, parameters true / nominal / recovered and held-out error before -> after, every number
the committed result's; one page per example at /sysid/<id>/ with every parameter row and, for CAN 11 and the cell, the drift demos.

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
import math
import os
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


BAM_RIG = Path("/archive/datasets/bam_rig")


def newest_triage() -> tuple[Path, dict] | None:
    """The newest bam_rack_twin gate triage in the archive, by its own written_at: read here independently of the producer."""
    best = None
    for path in BAM_RIG.glob("rack_2026-*/analysis/gates_triage*.json"):
        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and doc.get("written_at") and (best is None or doc["written_at"] > best[1]["written_at"]):
            best = (path, doc)
    return best


def triage_checks(data: Path, path: Path, doc: dict) -> None:
    """Rack leftovers, 2026-11-05 (written before gates_triage_7.json reached the site): the Why it fails page served gates_triage_6.json's
    CAN 11 / CAN 21 lines, written against an older acceptance, each labelled "written for an earlier result". Oracle: the newest triage
    and the newest acceptance in the archive, read here. Every non-passing cell's served explanation carries the triage's words as the
    same result, and those words state the displayed acceptance's own number for the cell."""
    found = newest_triage()
    check(found is not None, "a gate triage is in the archive")
    if found is None:
        return
    tpath, triage = found
    check(Path(str(triage.get("acceptance"))).name == path.name,
          f"the triage the site serves ({tpath.name}) was written against the acceptance it shows ({path.name}; the triage names {Path(str(triage.get('acceptance'))).name})")
    cells = {(c["station"], c["gate"]): c for c in triage.get("cells", [])}
    gates = {(f"can{can}", g["id"]): g for can, st in doc["stations"].items() for g in st["gates"]}
    rows = {(r["station"], r["gate_id"]): r for r in json.loads((data / "why.json").read_text())["rows"]}
    stale, uncited, missing = [], [], []
    for key, gate in gates.items():
        if gate["status"] == "pass":
            continue
        row, cell = rows.get(key), cells.get(key)
        if row is None or cell is None:
            missing.append(f"{key[0]} {key[1]}")
            continue
        served = " ".join(str(row.get(f) or "") for f in ("why", "next", "evidence"))
        if f"[from {tpath.name}" not in served or "written for an earlier result" in served or "not triaged yet" in served:
            stale.append(f"{key[0]} {key[1]}")
        value = gate.get("value")
        number = f"{value:.2f}" if isinstance(value, float) else (str(value) if value is not None else gate["status"])
        if number not in str(cell.get("what_closes_it")) or number not in served:
            uncited.append(f"{key[0]} {key[1]} ({number})")
    check(not missing, f"every non-passing cell has a served row and a triage entry ({missing[:5]})")
    check(not stale, f"every non-passing cell's served explanation carries {tpath.name}'s words as the same result, never 'written for an earlier "
                     f"result' or 'not triaged yet' ({len(stale)}: {stale[:5]})")
    check(not uncited, f"every non-passing cell's explanation cites {path.name}'s own number for it, in the triage and as served ({uncited[:5]})")


def rack_roots(entry: dict) -> tuple[list[Path], list[Path]]:
    """(every folder whose runs are the rack's, the kept builds' folders) from the registry entry and the schedule index it names, read
    here: the archive days, and each LIVE station's runs/ (index.json stations' out); a kept build (index.json kept) holds copies of runs
    its live folder keeps (checked 2026-11-05: all of CAN 12's and CAN 4's), so it is never a root."""
    index = json.loads(Path(entry["schedule_index"]).read_text())
    live = [Path(row["out"]) / "runs" for row in sorted(index["stations"], key=lambda row: row["can_id"]) if (Path(row["out"]) / "runs").is_dir()]
    return [Path(a) for a in entry["archive"]] + live, [Path(k["out"]) for k in index.get("kept", [])]


def station_runs_checks(data: Path, entry: dict) -> None:
    """Rack leftovers, 2026-11-05 (written before the registry indexed them): the run registry listed CAN 11's schedule runs only, so CAN
    21's sessions C and D (t2_ident_heldout-59aa0a41, t2_record_ff_fb-9f67bfd7), CAN 12's and CAN 4's schedule sessions and the 11-05
    warm session were missing from the Runs tab. Oracle: the schedule index and the archive days on disk, read here."""
    rows = json.loads((data / "runs.json").read_text())["rows"]
    indexed = {Path(r["npz"]) for r in rows if r.get("npz")}
    roots, kept = rack_roots(entry)
    want = set()
    for root in roots:
        for npz in root.rglob("*.npz"):
            meta = npz.with_suffix(".json")
            if meta.is_file() and json.loads(meta.read_text()).get("can_id") is not None:
                want.add(npz)
    lost = sorted(str(p) for p in want - indexed)
    check(not lost, f"every recorded run under the archive days and every live station's runs/ is indexed ({len(want)} recorded, {len(indexed)} indexed; "
                    f"missing {len(lost)}: {lost[:3]})")
    per_station = {}
    for root in roots[len(entry["archive"]):]:
        sessions = {p.relative_to(root).parts[0] for p in want if p.is_relative_to(root)}
        per_station[root.parent.name] = (len(sessions), sum(1 for p in indexed if p.is_relative_to(root)))
    check(len(per_station) >= 4 and all(n for _, n in per_station.values()), f"every live station (CAN 4, 11, 12, 21 have runs/ today)'s schedule sessions are indexed ({per_station})")
    can21 = {p.relative_to(roots[0].parent).parts[4] for p in indexed if "schedules/one-dof-test-rack/can21/runs/" in str(p)}
    check({"t2_ident_heldout-59aa0a41", "t2_record_ff_fb-9f67bfd7"} <= can21, f"CAN 21's sessions C and D are indexed ({sorted(can21)})")
    copies = [str(p) for p in indexed if any(p.is_relative_to(k) for k in kept)]
    check(not copies, f"no kept build's copy of a run is indexed beside the live one ({len(copies)}: {copies[:2]})")
    days = sorted(p for p in BAM_RIG.glob("rack_2026-*") if p.is_dir() and p.name >= Path(entry["archive"][0]).name and any(p.rglob("*.npz")))
    listed = {Path(a) for a in entry["archive"]}
    check(all(d in listed for d in days), f"every rack day since the first listed one is an archive day ({[d.name for d in days if d not in listed]} not listed)")


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
KPI_JS = r"""(name) => { const s = (%s)(name); if (!s) return null; return [...s.querySelectorAll('data-kpi')].map((card) => {
  const ch = card.querySelector('.dv-kpi-history .dv-view-chart'); const v = ch && ch.vegaView; const pts = []; const rules = [];
  const walk = (n) => { if (!n) return; if (n.marktype === 'line' && n.role === 'mark') for (const i of n.items || []) if (i.datum && i.datum.passing !== undefined) pts.push(i.datum.passing);
    if (n.marktype === 'rule' && n.role === 'mark') for (const i of n.items || []) rules.push(i.y); for (const i of n.items || []) if (i.items) walk(i); };
  if (v) walk(v.scenegraph().root);
  // a grouped card draws its history as an SVG sparkline: each reading's mark, read back through its range (aria-label "N readings, lo to hi")
  const svg = card.querySelector('.dv-kpi-spark svg.dv-spark'); let spark = [];
  if (svg) { const m = /([\d.]+) to ([\d.]+)/.exec(svg.getAttribute('aria-label') || ''); const ys = [...svg.querySelectorAll('circle')].map((c) => Number(c.getAttribute('cy')));
    if (m && ys.length) { const lo = Number(m[1]), hi = Number(m[2]), top = Math.min(...ys), bot = Math.max(...ys);
      spark = ys.map((y) => (bot === top ? lo : Math.round(lo + (bot - y) / (bot - top) * (hi - lo)))); } }
  if (!pts.length) pts.push(...spark); const r = (ch || svg || card).getBoundingClientRect();
  return { label: (card.querySelector('.dv-kpi-label') || {}).textContent || '', value: (card.querySelector('.dv-kpi-value') || {}).textContent || '',
           text: card.textContent, points: pts, rules: rules.length, width: r.width, height: r.height }; }); }""" % VIEW_JS
# a tree table's status cells: every row's id and the word and state its `worst` cell draws
TREE_JS = """(name) => { const s = (%s)(name); if (!s) return null; return [...s.querySelectorAll('tbody tr[data-id]')].map((tr) => {
  const b = tr.querySelector('td[data-col="worst"] .dv-state'); const label = tr.querySelector('td[data-col="label"]');
  return { label: label ? label.textContent.trim() : '', state: b ? b.dataset.state : null, word: b ? (b.querySelector('.dv-state-word') || {}).textContent : null,
           glyph: b ? (b.querySelector('.dv-state-glyph') || {}).textContent : null, shown: b ? b.getBoundingClientRect().width > 0 : false }; }); }""" % VIEW_JS
# a tree table's roll-up number columns: every row's label and its passing and cells cells as drawn
ROLLUP_COLS_JS = """(name) => { const s = (%s)(name); if (!s) return null; return [...s.querySelectorAll('tbody tr[data-id]')].map((tr) => {
  const t = (c) => ((tr.querySelector('td[data-col="' + c + '"]') || {}).textContent || '').replace(/[^\\d.]/g, '');
  return { label: ((tr.querySelector('td[data-col="label"]') || {}).textContent || '').trim(), passing: t('passing'), cells: t('cells') }; }); }""" % VIEW_JS
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


def as_hex(css) -> str | None:
    """'#B42318' or 'rgb(180, 35, 24)' -> '#b42318' (the scene reports hex, the tokens computed CSS)."""
    if not isinstance(css, str):
        return None
    if css.startswith("#"):
        return css.lower()[:7]
    nums = [round(float(x)) for x in re.findall(r"[\d.]+", css)[:3]]
    return "#" + "".join(f"{v:02x}" for v in nums) if len(nums) == 3 else None


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
    hues = {v: [] for v in ("pass", "partial", "fail")}
    for k, v in served.items():
        if v in hues and k in cells:
            hues[v].append(rgb_hue(cells[k]["bg"]))  # the cell is filled in its tone; its glyph is drawn on it in white
    green = all(80 <= h <= 170 and s > 0.2 for h, s in hues["pass"])
    amber = all(25 <= h <= 55 and s > 0.3 for h, s in hues["partial"])
    red = all((h <= 15 or h >= 340) and s > 0.3 for h, s in hues["fail"])
    check(not wrong and green and amber and red and hues["pass"] and hues["fail"] and hues["partial"],
          f"{where}: the cells wear RobotDx's status tones (pass good, partial warn, not run muted, fail bad; {len(wrong)} wrong), measured fills: "
          f"pass green {sorted({round(h) for h, _s in hues['pass']})}, partial amber {sorted({round(h) for h, _s in hues['partial']})}, "
          f"fail red {sorted({round(h) for h, _s in hues['fail']})}")


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


# ---- audit round 2 (2026-10-29, gaps 2 and 3): every number on a failure explanation is the displayed result's -----------------
NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)")
RATIO = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?[×x](?![\w])")
OLDER = re.compile(r"\s*(calibration C\b|the twin of record|not counted|v1\b|v2 replaces|stale\b)")
LABELLED = re.compile(r"\[from [^\]\[]*?\.json[^\]\[]*?\]")


def cell_numbers(can: str, gate: dict, facts: dict) -> list[float]:
    """Every number the acceptance file itself states for this cell: its value, limit, judged statistics and limits, its target and
    detail, and the station's facts' own *_source lines (where the study named its model and the other numbers it saw)."""
    out = []
    for v in [gate.get("value"), gate.get("limit")] + [x for j in gate.get("judged") or [] for x in (j.get("value"), j.get("limit"))]:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    # WHY the older-model clauses are dropped (mutation 2026-10-30: an unlabelled "3.93×" on CAN 21 T9 passed, because the source line
    # itself says "calibration C 3.93x"): a number the study reports for another model is exactly what must stay labelled
    texts = [str(gate.get("target") or ""), str(gate.get("detail") or "")] + [str(v) for k, v in facts.items() if k.endswith("_source")]
    kept = [c for t in texts for c in re.split(r"[;(]", t) if not OLDER.match(c) or not RATIO.search(c)]
    out += [float(x) for c in kept for x in NUM.findall(c)]
    return out


def matches(printed: str, allowed: list[float]) -> bool:
    """`printed` equals one allowed value at the precision it was printed with."""
    decimals = len(printed.split(".")[1]) if "." in printed else 0
    x = float(printed)
    return any(abs(x - v) <= 0.5 * 10 ** -decimals + 1e-9 for v in allowed)


def explanation_checks(data: Path, path: Path, doc: dict, out: Path) -> None:
    """Gaps 2 and 3 of the round-2 audit, read from the archive here (an oracle outside tools/build_app.py)."""
    rows = json.loads((data / "why.json").read_text())["rows"]
    bad_head, bad_stat, unlabelled, none_written, repeated, no_model = [], [], [], [], [], []
    for r in rows:
        can = r["device"].split()[1]
        station = doc["stations"][can]
        gate = next(g for g in station["gates"] if g["id"] == r["gate_id"])
        allowed = cell_numbers(can, gate, station["facts"])
        strict = [float(v) for v in [gate.get("value"), gate.get("limit")] + [x for j in gate.get("judged") or [] for x in (j.get("value"), j.get("limit"))]
                  if isinstance(v, (int, float)) and not isinstance(v, bool)]
        cell = f"{r['device']} {r['gate_id']}"
        head = re.sub(r"\bT\d+\b", "", r["explain"].split(" Why:")[0])
        for text in (r["measured"], head):
            wrong = [n for n in NUM.findall(text) if not matches(n, strict)]
            if wrong:
                bad_head.append(f"{cell}: {wrong} in {text!r}")
        want = [(j["name"], j["value"], j["limit"], j["passes"]) for j in gate.get("judged") or []]
        got = [(j["name"], j["value"], j["limit"], j["passes"]) for j in r.get("statistic") or []]
        if got != want or r.get("limit") != gate.get("limit"):
            bad_stat.append(f"{cell}: {got} / {r.get('limit')} vs {want} / {gate.get('limit')}")
        for field in ("why", "evidence", "floor_rules", "next"):
            rest = LABELLED.sub("", r.get(field) or "")
            stray = [n for n in RATIO.findall(rest) if not matches(n, allowed)]
            if stray:
                unlabelled.append(f"{cell} {field}: {stray}")
        if "none written" in r["measured"] + r["explain"]:
            none_written.append(cell)
        for block in LABELLED.findall(" ".join(str(r.get(f) or "") for f in ("why", "evidence", "floor_rules", "next", "earlier"))):
            if not re.search(r"\d{4}-\d{2}-\d{2}", block) or "model" not in block:
                unlabelled.append(f"{cell}: a labelled block without its date or model: {block[:80]}")
        sentences = {f: {x.strip().lower() for x in re.split(r"(?<=[.;:])\s+", str(r.get(f) or "")) if len(x.strip()) >= 25} for f in ("why", "evidence", "next")}
        dup = (sentences["why"] & sentences["evidence"]) | (sentences["why"] & sentences["next"]) | (sentences["evidence"] & sentences["next"])
        if dup:
            repeated.append(f"{cell}: {sorted(dup)[0][:70]}")
        if not r.get("model"):
            no_model.append(cell)
    check(not bad_head, f"every number in each explanation's headline and statistic is the displayed acceptance's ({path.name}) for that cell "
                        f"({len(rows)} rows; wrong: {bad_head[:3]})")
    check(not bad_stat, f"each row's judged statistics and limit are the acceptance's judged entries and limit, exactly ({bad_stat[:3]})")
    check(not unlabelled, f"no ratio from another file appears unlabelled: any number the acceptance does not state sits in a [from <file>.json, <date>, model ...] block ({unlabelled[:3]})")
    check(not none_written, f"no row says 'limit: none written' ({none_written[:5]})")
    check(not repeated, f"Why, Evidence and Next never repeat the same sentence ({repeated[:3]})")
    check(not no_model, f"every row names the model of the result it shows ({no_model[:5]})")
    pick = lambda d, g: next(r for r in rows if (r["device"], r["gate_id"]) == (d, g))  # noqa: E731
    for d, g in (("CAN 21", "T9"), ("CAN 14", "T10"), ("CAN 21", "T2")):
        r = pick(d, g)
        print(f"     {d} {g}: {r['measured']}")

    # gap 4: coverage paths at exactly 1/n, and the page says what is drawn
    n_runs = {}
    for r in json.loads((data / "runs.json").read_text())["rows"]:
        n_runs[r["device"]] = n_runs.get(r["device"], 0) + 1
    total = sum(n_runs.values())
    off = set()
    for r in json.loads((data / "coverage.json").read_text())["rows"]:
        if r.get("layer") == "workspace":
            continue
        n = n_runs[r["device"]]
        if abs(r["path_opacity"] - 1 / n) > 1e-3 / n or abs(r["path_opacity_all"] - 1 / total) > 1e-3 / total:
            off.add((r["device"], r["path_opacity"], round(1 / n, 6)))
    check(not off, f"every coverage path is drawn at exactly 1/n (n = its station's runs; 1/{total} on Angle over time), no floor ({sorted(off)[:3]})")
    texts = {name: (out / "views" / name).read_text() for name in ("station-coverage.base", "deployment-coverage.base")}
    honest = {name: "1/n" in t and "0.04" not in t and "Runs per cell" in t and "fade" in t for name, t in texts.items()}
    check(all(honest.values()), f"the coverage pages say what is drawn: exact 1/n, no floor, and that the Runs per cell voxels count runs where paths fade out ({honest})")


WORKTREE_MARKS = (".claude/worktrees/", "sim2real-worktrees/")
TEXT_SUFFIXES = {".json", ".html", ".base", ".js", ".css", ".md", ".txt", ".svg"}


def portability_checks(out: Path) -> None:
    """The built site depends on no worktree (Codex round 3, gap 1, 2026-11-04: the delivered build linked its data into a
    retired worktree, so coverage, a run's samples and the decomposition were 404s). Written before the fix."""
    broken, named, links = [], [], 0
    for root, dirs, files in os.walk(out, followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink():
                links += 1
                target = os.readlink(path)
                if not path.exists():
                    broken.append(f"{path.relative_to(out)} -> {target}")
                if any(m in str(path.resolve()) or m in target for m in WORKTREE_MARKS):
                    named.append(f"{path.relative_to(out)} -> {target}")
        for name in files:  # regular files and linked files (a linked folder's contents are its producer's: only its target is checked)
            path = Path(root) / name
            if path.suffix in TEXT_SUFFIXES or name.startswith(".sim2real"):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                hits = [m for m in WORKTREE_MARKS if m in text]
                if hits:
                    named.append(f"{path.relative_to(out)} names {hits[0]}")
    check(not broken, f"no symlink in the built site is broken ({links} links; broken: {broken[:5]})")
    check(not named, f"no built file, link or command names a .claude/worktrees/ or sim2real-worktrees/ path ({len(named)}: {named[:5]})")


SCHEDULE_CAN11 = Path("/archive/datasets/bam_rig/schedules/one-dof-test-rack/can11/schedule.json")


def types_served_checks(out: Path) -> None:
    """Zach's Nov 5 workflow, as served (no browser; written before the pages, 2026-11-05): every card's page carries its whole
    ladder (each rung's key, kind and parameter count), its drift warning in Zach's words and its test types; /types/ carries every
    calibration package. Oracle: type_cards/registry.py, imported here, never the page's own numbers."""
    from html import unescape  # noqa: PLC0415
    sys.path.append(str(REPO))
    from type_cards import registry  # noqa: PLC0415

    missing = []
    for cid, card in registry.CARDS.items():
        text = unescape((out / "types" / cid / "index.html").read_text(encoding="utf-8"))
        for r in card.rungs:
            if f'data-rung="{r.key}" data-kind="{r.kind}" data-n-params="{r.n_parameters}"' not in text:
                missing.append(f"{cid} {r.key}")
        missing += [f"{cid} {t.id}" for t in card.tests if f'data-test="{t.id}"' not in text]
        if registry.DRIFT_MESSAGE not in text:
            missing.append(f"{cid} drift message")
    check(not missing, f"every type card's page serves its whole ladder (key, kind, parameter count), its test types and the drift warning "
                       f"'{registry.DRIFT_MESSAGE}' ({sum(len(c.rungs) for c in registry.CARDS.values())} rungs on {len(registry.CARDS)} cards; missing {missing[:5]})")
    listing = unescape((out / "types" / "index.html").read_text(encoding="utf-8"))
    absent = [p.id for p in registry.CALIBRATION_PACKAGES if f'data-package="{p.id}"' not in listing]
    check(not absent, f"/types/ serves every calibration package ({len(registry.CALIBRATION_PACKAGES)}; absent {absent})")


def types_checks(page, base: str, still) -> None:
    """The Types area, measured: every card listed, the station -> type link inside the station's header, the six tabs, every
    metric and parameter row of the Servo card, and CAN 11's planned coverage: the number is schedule.py's own (stored in the
    producer's schedule.json) and the drawn q × qd cells are its q_qd plane's visited cells, cell by cell.

    Since 2026-11-05 (Zach's Nov 5 workflow, written before the pages): /types/ shows each card's ladder and the calibration
    packages with their code homes; Models shows every rung (key, kind, count, names, references as links, today's marked) and the
    union of their parameters; Metrics splits the two families and lists every diagnostic and gate (the drift warning in Zach's
    words); Tests lists every test type by setting; Coverage gives each axis's bin size and the coverage gate CAN 11 passes."""
    sys.path.append(str(REPO))
    from type_cards import registry  # noqa: PLC0415

    page.goto(f"{base}/types/")
    page.wait_for_load_state("load")
    listed = page.evaluate("[...document.querySelectorAll('.s2r-types [data-type]')].map(r => [r.dataset.type, r.querySelector('a').getAttribute('href')])")
    check(sorted(t for t, _h in listed) == sorted(registry.CARDS) and all(h == f"/types/{t}/" for t, h in listed),
          f"/types/ lists every type card of the registry, each linking to its page ({len(listed)} of {len(registry.CARDS)})")
    go = page.evaluate("[...document.querySelectorAll('#sm a.go')].map(a => a.getAttribute('href'))")
    check("/types/" in go, f"the search menu's Go to lists the Types area ({go})")
    ladders = page.evaluate("[...document.querySelectorAll('.s2r-types [data-type]')].map(r => [r.dataset.type, +r.dataset.rungs, (r.querySelector('[data-col=rungs]') || {}).textContent || ''])")
    bad = [t for t, n, text in ladders if n != len(registry.CARDS[t].rungs)
           or not all(f"{r.key} {r.n_parameters:,}" in text for r in registry.CARDS[t].rungs)]
    check(len(ladders) == len(registry.CARDS) and not bad, f"/types/ shows every card's ladder: each rung's key with its parameter count ({len(ladders)} cards; wrong {bad})")
    packages = page.evaluate("""[...document.querySelectorAll('.s2r-packages tr[data-package]')].map(r => [r.dataset.package, r.dataset.status,
        [...r.querySelectorAll('a[href^="/types/"]')].map(a => a.getAttribute('href')), r.textContent])""")
    want = [[p.id, p.status, [f"/types/{c}/" for c in p.serves]] for p in registry.CALIBRATION_PACKAGES]
    named = all(Path(h.path).name in text for p, (_i, _s, _h, text) in zip(registry.CALIBRATION_PACKAGES, packages) for h in p.code)
    check([row[:3] for row in packages] == want and named,
          f"/types/ lists Zach's calibration packages, the types each serves (linked) and every file its code lives in ({len(packages)} of {len(want)})")
    still("13-types")

    page.goto(f"{base}/{DEP}/can11/")
    page.wait_for_load_state("load")
    link = page.locator(".phead a.s2r-type-link")
    box = link.bounding_box() if link.count() == 1 else None
    head = page.locator(".phead").bounding_box()
    check(link.count() == 1 and link.get_attribute("href") == "/types/servo/" and box and head and box["y"] >= head["y"] and box["y"] + box["height"] <= head["y"] + head["height"] + 0.5
          and box["width"] > 0, f"CAN 11's station header links to its type card, the Servo card ({box})")
    link.click()
    page.wait_for_load_state("load")
    check(page.url.endswith("/types/servo/"), f"the link opens the Servo card ({page.url})")
    tabs = page.evaluate("[...document.querySelectorAll('nav.tabs [role=tab]')].map(t => t.textContent.trim())")
    # Ruler change, named (2026-11-05): Model became Models (a ladder of rungs) and Tests is new (Zach's "3. Test Type")
    check(tabs == ["Metrics", "Models", "Tests", "Coverage", "View", "Procedure"], f"a type card's tabs are Metrics, Models, Tests, Coverage, View, Procedure ({tabs})")
    card = registry.CARDS["servo"]

    open_tab(page, "metrics")
    rows = page.evaluate("[...document.querySelectorAll('[data-tab=metrics] tr[data-metric]')].map(r => [r.dataset.metric, r.dataset.family, r.dataset.robotdx || '', r.dataset.status])")
    check(rows == [[m.id, m.family, m.robotdx or "", registry.metric_status(card, m.id)] for m in card.metrics],
          f"the Metrics tab shows every metric, its family, its RobotDx id and whether a gate reads it ({len(rows)} of {len(card.metrics)})")
    families = page.evaluate("[...document.querySelectorAll('[data-tab=metrics] table[data-family]')].map(t => [t.dataset.family, [...t.querySelectorAll('tr[data-metric]')].map(r => r.dataset.family)])")
    check([f for f, _ in families] == ["performance", "fidelity"] and all(all(x == f for x in xs) and xs for f, xs in families),
          f"the two families sit in their own tables, performance (real vs target) then fidelity (twin vs real) ({[(f, len(xs)) for f, xs in families]})")
    gate_of = {g.diagnostic: g for g in card.gates}
    dxs = page.evaluate("[...document.querySelectorAll('[data-tab=metrics] tr[data-diagnostic]')].map(r => [r.dataset.diagnostic, r.dataset.kind, r.dataset.gate || '', r.textContent])")
    check([row[:3] for row in dxs] == [[d.id, d.kind, gate_of[d.id].id if d.id in gate_of else ""] for d in card.diagnostics],
          f"every diagnostic (a metric + a threshold) and the gate on it (+ a target) is listed ({len(dxs)} diagnostics, {len(card.gates)} gates)")
    drift = next((text for _i, kind, _g, text in dxs if kind == "drift"), "")
    t2 = next((text for _i, _k, g, text in dxs if g and gate_of.get(_i) and gate_of[_i].acceptance == "T2"), "")
    check(registry.DRIFT_MESSAGE in drift and "1.25" in drift and "T2" in t2 and "1.5" in t2,
          f"the drift diagnostic warns '{registry.DRIFT_MESSAGE}' past 1.25× its calibrated value, and T2 gates fidelity at 1.5× the floor")

    open_tab(page, "model")
    # a rung's row is tr[data-rung][data-kind]: a parameter's row names the rung it enters (data-rung) and has no kind
    ladder = page.evaluate("[...document.querySelectorAll('[data-tab=model] tr[data-rung][data-kind]')].map(r => [r.dataset.rung, r.dataset.kind, +r.dataset.nParams, r.dataset.current === 'true', r.textContent])")
    names_shown = all(all(n in text for n in r.parameter_names) for r, (*_x, text) in zip(card.rungs, ladder))
    check([row[:4] for row in ladder] == [[r.key, r.kind, r.n_parameters, r.current] for r in card.rungs] and names_shown,
          f"the Models tab shows the servo's ladder: each rung's key, kind, parameter count and names, today's (M4) marked ({[r[0] for r in ladder]})")
    hrefs = set(page.evaluate("[...document.querySelectorAll('[data-tab=model] a[href^=\"http\"]')].map(a => a.getAttribute('href'))"))
    cited = {ref.url for r in card.rungs for ref in r.references if ref.url}
    check(cited <= hrefs and "https://doi.org/10.1126/scirobotics.aau5872" in hrefs,
          f"every reference the ladder cites is a link to learn the model (Hwangbo 2019 among them; {len(cited & hrefs)} of {len(cited)})")
    arch = page.locator("[data-tab=model] tr[data-arch='M7']")
    check(arch.count() == 1 and all(x in arch.inner_text() for x in ("32 × 32 × 32", "softsign", "2,369", "10 ms")),
          f"the actuator net's architecture is shown: 3 × 32 softsign over 3 samples 10 ms apart, 2,369 weights ({arch.inner_text() if arch.count() else None})")
    union = []
    for r in card.rungs:
        union += [p for p in r.parameters if p.name not in {q.name for q in union}]
    params = page.evaluate("[...document.querySelectorAll('[data-tab=model] tr[data-param]')].map(r => [r.dataset.param, r.dataset.observable, r.dataset.rung])")
    first = {}
    for r in card.rungs:
        for p in r.parameters:
            first.setdefault(p.name, r.key)
    # Ruler change, named (2026-11-05): the table lists every rung's parameters once, in ladder order (today's model's 16 among them)
    check(params == [[p.name, p.observable, first[p.name]] for p in union] and ["backlash_rad", "no", "M4"] in params
          and {p.name for p in card.model.parameters} <= {row[0] for row in params},
          f"the Models tab lists every parameter once with the rung it enters and whether the outputs see it, backlash encoder-blind ({len(params)} of {len(union)})")
    still("14-types-servo-model")

    open_tab(page, "tests")
    tests = page.evaluate("[...document.querySelectorAll('[data-tab=tests] tr[data-test]')].map(r => [r.dataset.test, r.dataset.setting, r.dataset.recalibration === 'true'])")
    check(tests == [[t.id, t.setting, t.recalibration] for t in card.tests] and {s for _t, s, _r in tests} == set(registry.SETTINGS),
          f"the Tests tab lists every test type with its setting (bench, deployed) and whether it recalibrates ({len(tests)} of {len(card.tests)})")
    served = page.evaluate("[...document.querySelectorAll('[data-tab=tests] [data-package]')].map(r => r.dataset.package)")
    check(served == [p.id for p in registry.packages_for(card)], f"and the calibration packages that serve the servo ({served})")
    still("14b-types-servo-tests")

    open_tab(page, "coverage")
    sched = json.loads(SCHEDULE_CAN11.read_text())
    row = page.locator("[data-tab=coverage] tr[data-station='can11']")
    pct = row.get_attribute("data-train-pct") if row.count() == 1 else None
    want = sched["coverage"]["train"]["pct_reachable"]
    check(pct is not None and float(pct) == want and f"{want} %" in row.inner_text() and row.locator(f"a[href='/{DEP}/can11/#schedule']").count() == 1,
          f"the Servo card's Coverage tab shows CAN 11's planned train coverage, schedule.py's own {want} % ({pct}), linked to its Schedule tab")
    from type_cards import coverage as tcov  # noqa: PLC0415
    q_edges = tcov.joint_edges(sched["description"])[0]
    q_bin = f"{q_edges[1] - q_edges[0]:.4g} rad"
    check(row.get_attribute("data-q-bin") == f"{q_edges[1] - q_edges[0]:.4g}" and q_bin in row.inner_text(),
          f"CAN 11's row states its own q cell, computed from its schedule's range ({q_bin}; shown {row.get_attribute('data-q-bin')})")
    axes = page.evaluate("[...document.querySelectorAll('[data-tab=coverage] tr[data-axis]')].map(r => [r.dataset.axis, r.dataset.binSize || '', r.dataset.marginal === 'true'])")
    check(axes == [[a.name, "" if a.bin_size is None else f"{a.bin_size:g}", a.marginal] for a in card.coverage.axes],
          f"each coverage axis shows its bin size and whether it is a marginal ({axes})")
    gate_el = page.locator("[data-tab=coverage] [data-coverage-gate]")
    gate_pct = card.coverage.gate_pct
    check(gate_el.count() == 1 and float(gate_el.get_attribute("data-coverage-gate")) == gate_pct and f"{gate_pct:g} %" in gate_el.inner_text()
          and row.get_attribute("data-gate") == registry.coverage_gate(card, type("R", (), {"pct": want})()) == "pass",
          f"the coverage gate (covers >= {gate_pct:g} % of reachable cells) is stated and CAN 11's plan passes it ({row.get_attribute('data-gate')})")
    # WHY per station (2026-11-04, one schedule for every servo): with eight schedules the card drew the first station's map under a
    # hard-coded "CAN 11" label; every planned station now has its own map, named for itself
    maps = page.evaluate("""[...document.querySelectorAll('[data-tab=coverage] figure.s2r-covfig')].map(f => [f.dataset.station, f.querySelector('figcaption').textContent])""")
    rows_planned = page.evaluate("""[...document.querySelectorAll('[data-tab=coverage] tr[data-station]')].map(r => r.dataset.station)""")
    check(sorted(m[0] for m in maps) == sorted(rows_planned) and len(maps) > 1 and all(cap.startswith(f"CAN {key[3:]} ") for key, cap in maps),
          f"the Coverage tab draws one q × qd map per planned station, each labelled with its own station ({[m[0] for m in maps]})")
    drawn = page.evaluate("""[...document.querySelectorAll('[data-tab=coverage] figure.s2r-covfig[data-station=can11] svg.s2r-cov rect[data-i]')].map(r => [+r.dataset.i, +r.dataset.j, +r.dataset.samples])""")
    plane = {(c["i"], c["j"]) for c in sched["coverage"]["planes"]["q_qd"] if c["split"] == "train" and c["samples"] > 0}
    check({(i, j) for i, j, n in drawn if n > 0} == plane and len(drawn) == 12 * 13,
          f"its q × qd map draws schedule.py's visited train cells, cell by cell ({sum(1 for d in drawn if d[2] > 0)} drawn, {len(plane)} in the plane, {len(drawn)} cells)")
    cov_box = page.locator("[data-tab=coverage] figure.s2r-covfig[data-station=can11] svg.s2r-cov").bounding_box()
    check(cov_box and cov_box["width"] > 200 and cov_box["height"] > 100, f"the map is drawn at a readable size ({cov_box})")
    still("15-types-servo-coverage")
    open_tab(page, "procedure")
    steps = page.evaluate("[...document.querySelectorAll('[data-tab=procedure] [data-step]')].map(r => [r.dataset.step, r.dataset.status])")
    check([s for s, _ in steps] == [s.key for s in registry.STEPS] and all(st in ("exists", "proposed") for _, st in steps),
          f"the Procedure tab shows the seven shared steps with this type's tool ({steps})")
    page.goto(f"{base}/types/motor/")
    page.wait_for_load_state("load")
    check(page.locator(".phead").get_by_text("needs").count() > 0 or "dyno" in page.locator(".phead").inner_text().lower(),
          "the Motor card says what it needs before it can be measured (a dyno)")
    page.goto(f"{base}/types/conveyor/#model")
    page.wait_for_load_state("load")
    conveyor = page.evaluate("[...document.querySelectorAll('[data-tab=model] tr[data-rung][data-kind]')].map(r => r.dataset.rung)")
    check(conveyor == [r.key for r in registry.CARDS["conveyor"].rungs], f"the Conveyor card (new, for the landing-page examples) shows its ladder ({conveyor})")


# a sentence that says the runner cannot do something it can (Codex round 5, gap 1: CAN 11 T4 said "the runner has no path" for gravity
# feed-forward after bam_ws 48dd5b4c gave it one)
NO_RUNNER_PATH = re.compile(r"(runner has no path|no runner path|has no path for|no path for (a|one) (gravity )?feed-forward)", re.I)


def served_explanation_checks(out: Path) -> None:
    """Codex round 5, gap 1 (2026-11-04): the explanations as served, not the producer's constants. Oracle: the delivered schedule of
    each station (its modes' runner status and its description's gravity amplitude, range and torque allowance). Written before the fix:
    red on the build that still served gates_triage_2.json's CAN 11 lines."""
    from html import unescape  # noqa: PLC0415

    page = out / "analysis" / "why-it-fails" / "index.html"
    html = page.read_text() if page.is_file() else ""
    articles = {m.group(1): re.sub(r"<[^>]+>", " ", unescape(m.group(2)))
                for m in re.finditer(r'<article class="s2r-whyrow[^"]*" id="([^"]+)"[^>]*>(.*?)</article>', html, re.S)}
    claims, served = [], {}
    for dep_dir in sorted(p for p in (out / "data").iterdir() if (p / "why.json").is_file()):
        modes = {}
        for summary in sorted((dep_dir / "schedule").glob("*/summary.json")):
            doc = json.loads(summary.read_text())
            modes[summary.parent.name] = doc
        for r in json.loads((dep_dir / "why.json").read_text())["rows"]:
            key = f"{r['station']}-{r['gate_id']}"
            texts = {"why.json": " ".join(str(r.get(f) or "") for f in ("explain", "why", "evidence", "next")), "page": articles.get(key, "")}
            served[key] = texts
            sched = modes.get(r["station"])
            runnable = [m for m, v in (sched or {}).get("modes", {}).items() if m.startswith("ff") and v["runner"]["status"] == "runnable"]
            for where, text in texts.items():
                if runnable and NO_RUNNER_PATH.search(text):
                    claims.append(f"{key} ({where}): {NO_RUNNER_PATH.search(text).group(0)!r} while {runnable} are runnable")
    check(not claims, f"no served explanation says the runner has no path for a mode its station's schedule marks runnable ({claims[:3]})")

    sched = json.loads((out / "data" / DEP / "schedule" / "can11" / "summary.json").read_text())
    d = sched["description"]
    amplitude, allowance = f"{d['gravity_nm']:.2f}", float(d["torque_limit_nm"])
    gravity_max = d["gravity_nm"] * max(abs(math.sin(x)) for x in d["range_rad"])
    ff = [m for m in ("ff_fb", "ff_weakfb") if sched["modes"][m]["runner"]["status"] == "runnable"]
    for gate in ("T4", "T7"):
        texts = served.get(f"can11-{gate}", {})
        check(set(texts) == {"why.json", "page"} and all(texts.values()), f"CAN 11 {gate}'s explanation is served in why.json and on the Why it fails page")
        for where, text in texts.items():
            bare = [m.group(0) for m in re.finditer(rf"{re.escape(amplitude)} N\.?m(?! in amplitude)[^.;]{{0,40}}", text)]
            check(not bare and "gravity load" not in text and not re.search(r"gravity[^.;]{0,40}exceeds", text),
                  f"CAN 11 {gate} ({where}) names {amplitude} N.m only as gravity's amplitude, never a load that exceeds the board ({bare[:2]})")
        if gate == "T4":
            for where, text in texts.items():
                demand = re.search(r"planned demand[^.;]*?peaks at (\d+\.\d+) N\.m against the runner's (\d+\.\d+) N\.m allowance", text)
                gmax = re.search(rf"{re.escape(amplitude)} N\.m in amplitude[^.;]*?at most (\d+\.\d+) N\.m", text)
                check(bool(ff) and all(m in text for m in ff) and "feed-forward" in text and "no feed-forward plan" not in text,
                      f"CAN 11 T4 ({where}) says the runner's {'/'.join(ff)} feed-forward plans exist, not that FF is missing")
                check(bool(demand) and float(demand.group(1)) < float(demand.group(2)) and abs(float(demand.group(2)) - allowance) < 0.006,
                      f"CAN 11 T4 ({where}) states the planned demand against the {allowance:.2f} N.m allowance the schedule declares "
                      f"({demand.groups() if demand else 'no such sentence'})")
                check(bool(gmax) and abs(float(gmax.group(1)) - gravity_max) < 0.006,
                      f"CAN 11 T4 ({where}) gives gravity's maximum over the scheduled range as {gravity_max:.2f} N.m "
                      f"({gmax.group(1) if gmax else 'not stated'})")


def run_set_checks(data: Path, out: Path) -> None:
    """A schedule session is one run set (2026-11-05, CAN 11's frozen schedule): every run carrying a schedule stamp is in the set named
    for its station, digest, mode and session, the set holds exactly the session's completed steps, its replayed runs play the twin
    beside real, and the served runs list filters by it (the Run set facet, the rows' run_set)."""
    rows = json.loads((data / "runs.json").read_text())["rows"]
    stamped = [r for r in rows if r.get("split")]
    sets: dict[str, list[dict]] = {}
    for r in stamped:
        sets.setdefault(r["run_set"], []).append(r)
    check(bool(sets) and all("· schedule " in name for name in sets), f"every schedule-stamped run sits in a named run set ({sorted(sets)})")
    # WHY per session, not per set (2026-11-05, CAN 11's integral study): one session can hold several sets, one per (schedule digest, mode)
    # its runs carry (the study ran ff_fb and ff_weakfb steps of 2f32ddbc and sweeps stamped with its own 818bd730), so the sets of a session
    # together hold exactly its completed runs, and each run sits in the set its own stamp names
    by_session: dict[Path, list[dict]] = {}
    for r in stamped:
        by_session.setdefault(Path(r["npz"]).parent.parent, []).append(r)
    for session, members in by_session.items():
        steps = [st for st in json.loads((session / "session.json").read_text())["steps"] if st["kind"] != "pause" and st["status"] == "complete"]
        check(len(members) == len(steps) and {r["npz"] for r in members} == {str(session / f) for st in steps for f in st["files"] if f.endswith(".npz")},
              f"session {session.name}'s run sets hold exactly its {len(steps)} completed runs ({len(members)} in {len({r['run_set'] for r in members})} sets)")
        stamps = {r["npz"]: json.loads(Path(r["npz"]).with_suffix(".json").read_text())["schedule"] for r in members}
        check(all(r["run_set"].split(" · ")[1] == f"schedule {stamps[r['npz']]['digest'][:8]}" and r["run_set"].split(" · ")[2] == stamps[r["npz"]]["mode"]
                  for r in members), f"session {session.name}: every run sits in the set its own stamp names (digest and mode)")
    for name, members in sets.items():
        played = [r for r in members if r["models"]]
        check(len(played) == len(members) and all("twin of record" in r["situations"] for r in played),
              f"run set {name!r}: every run plays the twin of record beside real ({len(played)} of {len(members)})")
    modes = {r["mode"] for r in stamped}
    check(all(name.split(" · ")[2] == members[0]["mode"] and {r["mode"] for r in members} == {members[0]["mode"]} for name, members in sets.items()),
          f"a run set is one mode and says so ({sorted(modes)})")
    base = (out / "views" / "runs.base").read_text()
    served = json.loads((out / "data" / "search.json").read_text())["rows"]
    check("property: run_set, label: Run set" in base and "property: mode, label: Mode" in base and sum(1 for r in served if r.get("run_set") in sets) == len(stamped),
          f"the runs list filters by run set (the facet, and {len(stamped)} served rows carry it)")


def station_key_of(device: str) -> str:
    return device.lower().replace(" ", "")


def schedule_freshness_checks(out: Path, schedules_root: Path) -> None:
    """The delivered schedule is the producer's current one (Codex round 4, gaps 2 and 4, 2026-11-04: the site showed 9.7 runnable
    minutes and a plan file that no longer existed, after bam_ws e8fb212c rebuilt the producer). Written before the fix."""
    stale, missing, n_commands = [], [], 0
    delivered = sorted((out / "data").glob("*/schedule/*"))
    for folder in delivered:
        source = schedules_root / folder.parent.parent.name / folder.name / "site"
        for name in sorted({p.name for p in source.glob("*.json")} | {p.name for p in folder.glob("*.json")}):
            a, b = folder / name, source / name
            if not (a.is_file() and b.is_file() and a.read_bytes() == b.read_bytes()):
                stale.append(f"{folder.name}/{name}")
        for c in json.loads((folder / "commands.json").read_text()) if (folder / "commands.json").is_file() else []:
            n_commands += 1
            plan = re.search(r"--plan (\S+)", c["command"])
            for path in {c.get("plan"), plan.group(1) if plan else None} - {None}:
                if not Path(path).is_file():
                    missing.append(path)
    stations = {f.parent.parent.name: {station_key_of(r["device"]) for r in json.loads((f.parent.parent / "devices.json").read_text())["rows"]} for f in delivered}
    strays = [f"{f.parent.parent.name}/{f.name}" for f in delivered if f.name not in stations[f.parent.parent.name]]
    check(not strays, f"only a station's own schedule folder is delivered, never a producer's backup beside it (strays: {strays})")
    check(delivered and not stale, f"every delivered schedule file equals the producer's site/ file, summary.json included ({len(delivered)} stations; stale: {stale[:5]})")
    check(n_commands > 0 and not missing, f"every schedule command's --plan file exists ({n_commands} commands; missing: {missing[:3]})")


# ---- the deployment tree, the run tags and the configuration snapshot (Zach, PROJECT - Sim2Real, Nov 5 2026), written before them --
# "each deployment, should have a tree, I guess simlar to the RobotDx Entity tree ... we can see like how the matching is at that
# level"; "tag a run as bench vs real"; "record the current configuration values ... so ideally we can reproduce". Every expectation
# below is read here from the primary files (the registry, the bam_rack_twin record, the newest acceptance in the archive, each run's
# own session.json), never from the site's tree.json.
ENVIRONMENTS = ("sim", "bench", "real")
SETTINGS = ("bench", "deployed")  # type_cards SETTINGS (sim2real.type_cards/2 CONTRACT: a run is tagged with its setting)
# a tree facet's buttons as data-ui draws them in a visible rail: level, value, label, count, pressed (data-ui CONTRACT §7 `tree`)
TREE_NODES_JS = """(scope) => { const root = document.querySelector(scope) || document; const rail = [...root.querySelectorAll('.dd-rail, data-facets')]
  .find((r) => r.getClientRects().length > 0 && r.querySelector('.df-tree')); if (!rail) return null; const tree = rail.querySelector('.df-tree');
  const group = tree.closest('[role=group], section, fieldset, details, .df-facet') || tree.parentElement;
  const r = rail.getBoundingClientRect(), t = tree.getBoundingClientRect();
  return { first: [...rail.querySelectorAll('.df-tree, .df-values, .df-list, input, select, .df-range, .df-chips')].indexOf(tree) === 0 || rail.querySelector('.df-tree') === rail.querySelector('ul, .df-values, input'),
           heading: group ? (group.querySelector('h3, h4, legend, summary, .df-h, .df-title') || {}).textContent || '' : '',
           rail: [r.left, r.right], box: [t.left, t.right, t.top, t.bottom],
           nodes: [...tree.querySelectorAll('button.df-node')].map((b) => ({ level: Number(b.dataset.level), value: b.dataset.value,
             label: (b.querySelector('.df-label') || {}).textContent || '', count: Number(((b.querySelector('.df-count') || {}).textContent || '').replace(/[^\\d]/g, '')),
             pressed: b.getAttribute('aria-pressed') === 'true', shown: b.getBoundingClientRect().width > 0,
             clipped: (() => { const l = b.querySelector('.df-label'); return !!l && l.scrollWidth > l.clientWidth + 1; })() })) }; }"""
# the rows a dashboard panel's view holds after every filter (its data-views model), and the first rows' cells as drawn
PANEL_ROWS_JS = """([name, column]) => { const s = (%s)(name); const e = s && s.querySelector(':scope > data-views'); const m = e && e.model; if (!m) return null;
  const heads = [...s.querySelectorAll('thead th')].map((h) => h.textContent.trim()); const i = heads.findIndex((h) => h.startsWith(column));
  return { n: m.matched ?? (m.rows ? m.rows.length : null), cells: i < 0 ? [] : [...s.querySelectorAll('tbody tr')].slice(0, 40).map((tr) => (tr.querySelectorAll('td')[i] || {}).textContent || '').map((x) => x.trim()).filter(Boolean) }; }""" % VIEW_JS


def rack_layout(registry_path: Path) -> tuple[dict, dict[str, str]]:
    """(the rack's registry entry, {device: adapter serial}) from app/registry.json and the bam_rack_twin record it names."""
    entry = next(d for d in json.loads(registry_path.read_text())["deployments"] if d["id"] == DEP)
    record = json.loads(Path(entry["record"]).read_text())
    return entry, {f"CAN {c['can_id']}": c["adapter_serial"] for c in record["components"] if c.get("can_id") is not None}


def session_of(npz: Path) -> Path | None:
    """A run's bam_rack_twin.hardware session.json: <session>/runs/<run>.npz beside <session>/session.json (the test's own copy)."""
    folder = npz.parent.parent if npz.parent.name == "runs" else npz.parent
    return folder / "session.json" if (folder / "session.json").is_file() else None


def snapshot_of(npz: Path, can_id: int, cache: dict) -> bool:
    """Whether the run's session recorded its board's whole config: board_configs[can_id] names a file whose key lines hash to it."""
    session = session_of(npz)
    if session is None:
        return False
    if session not in cache:
        cache[session] = json.loads(session.read_text())
    entry = (cache[session].get("board_configs") or {}).get(str(can_id)) or {}
    path = session.parent / entry["file"] if entry.get("file") and not entry.get("error") else None
    if path is None or not path.is_file():
        return False
    keys = "".join(line + "\n" for line in path.read_text(encoding="latin1").splitlines() if line and not line.startswith("#"))
    return hashlib.sha256(keys.encode("latin1")).hexdigest() == entry.get("sha256")


def deploy_tree_checks(data: Path, out: Path, doc: dict) -> dict:
    """The rack's tree, every node's match and every run's tags and config, against the primary files. Returns what the browser
    checks click: {adapter: (node id, stations, runs)}, the station node ids and the runs per station."""
    entry, adapter_of = rack_layout(REPO / "app" / "registry.json")
    rows = json.loads((data / "runs.json").read_text())["rows"]
    want = {(f"CAN {can}", g["id"]): g["status"] for can, st in doc["stations"].items() for g in st["gates"]}
    runs_of = {}
    for r in rows:
        runs_of[r["device"]] = runs_of.get(r["device"], 0) + 1
    tree_path = data / "tree.json"
    check(tree_path.is_file(), f"the rack's tree is served ({tree_path.relative_to(out)})")
    if not tree_path.is_file():
        return {}
    nodes = json.loads(tree_path.read_text())["rows"]
    by_id = {n["id"]: n for n in nodes}
    roots = [n for n in nodes if not n.get("parent")]
    adapters = sorted(set(adapter_of.values()))
    shape = {}
    for n in nodes:
        if n.get("parent") in by_id and by_id[n["parent"]] in roots:
            shape[n["label"]] = sorted(c["device"] for c in nodes if c.get("parent") == n["id"])
    want_shape = {f"fdcanusb {serial}": sorted(d for d, s in adapter_of.items() if s == serial) for serial in adapters}
    check(len(roots) == 1 and roots[0]["label"] == entry["title"] and shape == want_shape and len(nodes) == 1 + len(adapters) + len(adapter_of),
          f"the rack's tree is its record's wiring, as RobotDx draws it: {entry['title']} → {len(adapters)} fdcanusb adapters → {len(adapter_of)} stations "
          f"({shape})")
    # every node's match: the gate cells of the stations under it, read from the newest acceptance
    wrong = []
    for n in nodes:
        under = [d for d in adapter_of if n.get("device") == d or (n in roots) or n.get("label") == f"fdcanusb {adapter_of[d]}"]
        cells = [v for (d, _g), v in want.items() if d in under]
        if (n.get("cells"), n.get("passing"), n.get("worst")) != (len(cells), sum(v == "pass" for v in cells), RANK_WORD[max(RANK[v] for v in cells)]):
            wrong.append((n["label"], n.get("passing"), n.get("cells"), n.get("worst"), sum(v == "pass" for v in cells), len(cells)))
        if n.get("runs") != sum(runs_of.get(d, 0) for d in under):
            wrong.append((n["label"], "runs", n.get("runs")))
    check(not wrong, f"every tree node carries the gate cells under it from the newest acceptance (passing, cells, worst) and its runs ({len(nodes)} nodes; wrong {wrong[:3]})")
    if str(REPO) not in sys.path:
        sys.path.append(str(REPO))  # appended, as types_checks does: the repo's site/ folder never shadows the stdlib's `site`
    from type_cards import registry as reg  # noqa: PLC0415  (CONTRACT.md: one import)
    servo = reg.card_for("servo")
    cards = {n["label"]: n.get("card") for n in nodes}
    check(servo is not None and all(cards[d] == servo.id for d in adapter_of) and not any(cards[f"fdcanusb {s}"] for s in adapters),
          f"each station node carries its type card (type_cards card_for(devices.json type) = {servo.id if servo else None}); an adapter has none")

    # every run sits under its station, its adapter and the rack (node_0 … node_2), each level labelled with its node's match
    fields = {f["name"]: f for f in json.loads((data / "runs.json").read_text())["schema"]["fields"]}
    station_node = {n["device"]: n for n in nodes if n.get("device")}
    misplaced = [r["run"] for r in rows if (r.get("node_0"), r.get("node_1"), r.get("node_2")) != (
        roots[0]["id"], station_node[r["device"]]["parent"], station_node[r["device"]]["id"])]
    labels_ok = all(f"{n['passing']}/{n['cells']}" in str((fields.get(f"node_{n['depth']}", {}).get("labels") or {}).get(n["id"], "")) for n in nodes)
    check(not misplaced and labels_ok and all(f"node_{k}" in fields for k in range(3)),
          f"every run sits under its station, its adapter and the rack (node_0..node_2), each level's label naming its node's passing/cells "
          f"({len(rows)} runs, {len(misplaced)} misplaced; labels {labels_ok})")

    # tags: a run is bench (and set at the bench) when it is a real recording in the rack's archive; anything else stays unknown
    # ruler changed 2026-11-05 (rack leftovers): the rack's own recordings lie under the archive days AND every live station's schedule
    # runs/ (rack_roots, read from the schedule index here), not the registry's listed folders alone; intent stands
    roots_ = rack_roots(entry)[0]
    real = [r for r in rows if r.get("basis") == "real" and r.get("npz") and any(Path(r["npz"]).is_relative_to(a) for a in roots_)]
    want_env = {r["run"]: (entry.get("environment") if r in real else "unknown") for r in rows}
    want_set = {r["run"]: (entry.get("setting") if r in real else "unknown") for r in rows}
    env = {r["run"]: r.get("environment") for r in rows}
    setting = {r["run"]: r.get("setting") for r in rows}
    counts = {v: sum(1 for x in env.values() if x == v) for v in (*ENVIRONMENTS, "unknown")}
    check(entry.get("environment") == "bench" and entry.get("setting") == "bench" and env == want_env and setting == want_set
          and set(env.values()) <= {*ENVIRONMENTS, "unknown"} and set(setting.values()) <= {*SETTINGS, "unknown"},
          f"every run is tagged truthfully: the rack's own recordings bench (environment) and bench (setting, type_cards SETTINGS), the rest "
          f"unknown ({counts})")
    check(all(r.get("test_type") == "not recorded" or r["test_type"] in {t.id for c in reg.CARDS.values() for t in c.tests} for r in rows),
          "a run's test type is a type_cards TestType id it recorded, else 'not recorded' (nothing is inferred)")

    # the configuration snapshot: full only where the run's own session recorded its board's whole config, hashed
    cache = {}
    want_full = {r["run"]: snapshot_of(Path(r["npz"]), int(r["device"].split()[1]), cache) for r in rows}
    got = {r["run"]: r.get("config") for r in rows}
    full = sum(want_full.values())
    check(got == {k: ("full" if v else "not recorded") for k, v in want_full.items()} and all(r.get("config_detail") for r in rows)
          and all(r.get("full_config_pct") == (100 if want_full[r["run"]] else 0) for r in rows),
          f"every run's configuration snapshot is read from its own session: full where board_configs names a file whose key lines hash to it, "
          f"else 'not recorded' with what is recorded ({full} of {len(rows)} full)")
    page = (out / DEP / "index.html").read_text()
    pct = f"{100 * full / len(rows):.0f} %"
    check(f"{full:,} of {len(rows):,} runs" in page and pct in page and "Config snapshots" in page,
          f"the deployment's header states its config-snapshot coverage ({full:,} of {len(rows):,} runs, {pct})")
    return {"adapters": {f"fdcanusb {s}": (next(n["id"] for n in nodes if n.get("label") == f"fdcanusb {s}"), want_shape[f"fdcanusb {s}"],
                                           sum(runs_of.get(d, 0) for d in want_shape[f"fdcanusb {s}"])) for s in adapters},
            "stations": {d: n["id"] for d, n in station_node.items()}, "runs_of": runs_of, "env": counts, "full": full, "total": len(rows)}


def config_snapshot_unit_checks(tmp: Path) -> None:
    """site/deploy_tree.config_of on a session written the way bam_rack_twin.hardware.session writes one: full, a tampered file,
    a board the session failed to read, and a run with no session at all."""
    import deploy_tree  # noqa: PLC0415
    keys = "servo.pid_position.kp 200\nservo.default_accel_limit 100\n"
    sha_ = hashlib.sha256(keys.encode("latin1")).hexdigest()
    session = tmp / "s1"
    (session / "runs").mkdir(parents=True, exist_ok=True)
    (session / "board_configs").mkdir(exist_ok=True)
    (session / "board_configs" / "can11.cfg").write_text("# CAN 11 whole config\n" + keys, encoding="latin1")
    (session / "session.json").write_text(json.dumps({"package_version": "0.1.0", "git_head": "f" * 40, "plan_sha256": "a" * 64, "board_configs": {
        "11": {"file": "board_configs/can11.cfg", "sha256": sha_, "keys": 2, "firmware": "657b5c5" + "0" * 33},
        "12": {"error": "conf enumerate: TimeoutError"}}}))
    full = deploy_tree.config_of(session / "runs" / "s01.npz", 11, {})
    failed = deploy_tree.config_of(session / "runs" / "s02.npz", 12, {})
    (session / "board_configs" / "can11.cfg").write_text("# CAN 11 whole config\n" + keys.replace("200", "150"), encoding="latin1")
    tampered = deploy_tree.config_of(session / "runs" / "s01.npz", 11, {})
    alone = deploy_tree.config_of(tmp / "loose" / "x.npz", 11, {})
    check(full["config"] == "full" and full["config_sha256"] == sha_ and full["full_config_pct"] == 100
          and all(x["config"] == "not recorded" and x["full_config_pct"] == 0 for x in (failed, tampered, alone))
          and "TimeoutError" in failed["config_detail"] and "sha256" in tampered["config_detail"] and "no session" in alone["config_detail"],
          "config_of: full only for a snapshot whose key lines hash to session.json's sha256; a failed read, a tampered file and a run "
          "with no session read 'not recorded' and say why")


def tree_rail_checks(page, base: str, data: Path, layout: dict, still) -> None:
    """The deployment's Runs tab: the tree is the rail's first facet, on the left; a node filters the runs to its level, and its
    children open under it (data-ui's `tree` facet, CONTRACT §7), each node labelled with its match."""
    page.goto(f"{base}/{DEP}/")
    page.wait_for_load_state("load")
    panel(page, "Runs · newest first").locator("tbody tr").first.wait_for(timeout=30000)
    page.wait_for_timeout(1500)
    scope = "[role=tabpanel][data-tab=runs]"
    t0 = page.evaluate(TREE_NODES_JS, scope) or {}
    level0 = [n for n in t0.get("nodes", []) if n["level"] == 0 and n["shown"]]
    want0 = {node_id: (name, runs) for name, (node_id, _st, runs) in layout["adapters"].items()}
    check(bool(t0) and {n["value"] for n in level0} == set(want0) and all(n["count"] == want0[n["value"]][1] and n["label"].startswith(want0[n["value"]][0])
                                                                          and re.search(r" · \d+/\d+$", n["label"]) for n in level0),
          f"the Runs tab's rail opens on the rack's tree: its adapters, each labelled with its match and counting its runs "
          f"({[(n['label'], n['count']) for n in level0]})")
    panels_left = page.evaluate(f"""() => {{ const d = [...document.querySelectorAll('{scope} data-dashboard .dd-body.dd-has-rail')].find(b => b.offsetParent);
        return d ? d.querySelector(':scope > .dd-main').getBoundingClientRect().left : null; }}""")
    check(t0.get("rail") and panels_left is not None and t0["rail"][1] <= panels_left + 1 and t0.get("first"),
          f"the tree is the first facet of the filter rail, left of the runs (rail ends {t0.get('rail', [0, 0])[1]:.0f} px, panels start {panels_left} px)")
    still("13-tree-rail")
    name, (adapter_id, stations, runs) = next((k, v) for k, v in layout["adapters"].items() if "0607623A" in k)
    page.locator(f"{scope} .dd-rail button.df-node[data-level='0'][data-value='{adapter_id}']").first.click()
    soft_wait(page, f"([name, n]) => {{ const s = ({VIEW_JS})(name); const e = s && s.querySelector(':scope > data-views'); return !!e && !!e.model && (e.model.matched ?? e.model.rows.length) === n; }}",
              ["Runs", runs], timeout=20000)
    page.wait_for_timeout(1200)
    got = page.evaluate(PANEL_ROWS_JS, ["Runs", "Station"]) or {}
    t1 = page.evaluate(TREE_NODES_JS, scope) or {}
    kids = [n for n in t1.get("nodes", []) if n["level"] == 1 and n["shown"]]
    want_kids = {layout["stations"][d]: layout["runs_of"].get(d, 0) for d in stations}
    check(got.get("n") == runs and got.get("cells") and set(got["cells"]) <= set(stations),
          f"a click on {name} filters the runs to its stations ({got.get('n')} of {runs} runs; stations drawn {sorted(set(got.get('cells') or []))})")
    check({n["value"]: n["count"] for n in kids} == want_kids and all(re.search(r" · \d+/\d+$", n["label"]) for n in kids)
          and any(n["pressed"] and n["value"] == adapter_id for n in t1.get("nodes", [])),
          f"{name} opens under it: its {len(want_kids)} stations, each with its match and its runs ({[(n['label'], n['count']) for n in kids]})")
    clipped = [n["label"] for n in t0.get("nodes", []) + t1.get("nodes", []) if n["shown"] and n["clipped"]]
    check(not clipped, f"no node's words are clipped in the rail at 1280 px (each label's scrollWidth within its box; clipped: {clipped})")
    still("13b-tree-adapter")
    can11 = layout["stations"]["CAN 11"]
    page.locator(f"{scope} .dd-rail button.df-node[data-level='1'][data-value='{can11}']").first.click()
    n11 = layout["runs_of"]["CAN 11"]
    soft_wait(page, f"([name, n]) => {{ const s = ({VIEW_JS})(name); const e = s && s.querySelector(':scope > data-views'); return !!e && !!e.model && (e.model.matched ?? e.model.rows.length) === n; }}",
              ["Runs", n11], timeout=20000)
    page.wait_for_timeout(1200)
    got = page.evaluate(PANEL_ROWS_JS, ["Runs", "Station"]) or {}
    check(got.get("n") == n11 and set(got.get("cells") or []) == {"CAN 11"} and "node_2" in unquote(page.url),
          f"a click on CAN 11 filters the runs to it ({got.get('n')} of {n11}), and the URL names the pick ({unquote(page.url).split('?', 1)[-1][:120]})")
    still("13c-tree-station")
    page.locator(f"{scope} .dd-rail button.df-node[data-level='0'][data-value='{adapter_id}']").first.click()
    soft_wait(page, f"([name, n]) => {{ const s = ({VIEW_JS})(name); const e = s && s.querySelector(':scope > data-views'); return !!e && !!e.model && (e.model.matched ?? e.model.rows.length) === n; }}",
              ["Runs", sum(layout["runs_of"].values())], timeout=20000)
    got = page.evaluate(PANEL_ROWS_JS, ["Runs", "Station"]) or {}
    check(got.get("n") == sum(layout["runs_of"].values()), f"a second click on {name} gives every run back ({got.get('n')})")
    kpi = page.evaluate(KPI_JS, "Config recorded") or [{}]
    # ruler changed 2026-11-05: the KPI shows the share at data-ui's own precision ('0.906%~ derived' once bam_rack_twin's session t2_ff_fb-43c126ce
    # brought the first 17 runs with a whole board config, of 1,877); the integer-rounded substring ('1') only ever matched a share of 0 %. The
    # shown number must equal the share rounded to the digits it shows; intent stands: the KPI says how many runs carry a full config snapshot
    want = 100 * layout["full"] / layout["total"]
    shown = re.search(r"(\d+(?:\.(\d+))?)\s*%", kpi[0].get("value") or "")
    digits = len(shown.group(2) or "") if shown else 0
    check(shown is not None and float(shown.group(1)) == round(want, digits) and "config" in (kpi[0].get("label") or "").lower(),
          f"the Runs tab's KPI says how many runs carry a full config snapshot ({kpi[0].get('label')!r}: {kpi[0].get('value')!r} vs {want:.3g} %)")


def flat_runs_checks(page, base: str, layout: dict, still) -> None:
    """/runs/: every run flat, faceted by type, deployment kind, the tree (deployment at its root), environment, setting, test type
    and config snapshot; a tag narrows the list."""
    page.goto(f"{base}/runs/")
    page.wait_for_load_state("load")
    page.locator("data-views tbody tr").first.wait_for(timeout=30000)
    page.wait_for_timeout(1500)
    headings = page.evaluate("[...document.querySelectorAll('aside data-facets h3, aside data-facets h4, aside data-facets legend, aside data-facets summary, aside data-facets .df-h')].map(h => h.textContent.trim())")
    want = ("Deployment tree", "Environment", "Setting", "Test type", "Type", "Deployment kind", "Config snapshot")
    check(all(any(h.startswith(w) for h in headings) for w in want), f"/runs/ facets every run flat by {', '.join(want)} ({headings})")
    t0 = page.evaluate(TREE_NODES_JS, "aside") or {}
    roots = [n for n in t0.get("nodes", []) if n["level"] == 0]
    check(len(roots) >= 1 and any(n["value"] == DEP and n["count"] == layout["total"] and re.search(r" · \d+/\d+$", n["label"]) for n in roots),
          f"/runs/'s tree starts at the deployments, each with its match and runs ({[(n['label'], n['count']) for n in roots]})")
    page.locator("aside data-facets label", has_text=re.compile(r"^\s*bench")).first.click()
    page.wait_for_timeout(1500)
    shown = page.evaluate("(() => { const v = document.getElementById('parts-views'); return v && v.model ? v.model.matched : null; })()")
    check(shown == layout["env"]["bench"], f"Environment · bench narrows /runs/ to the bench runs ({shown} of {layout['env']['bench']})")
    still("14-runs-flat")


def run_config_checks(page, base: str, data: Path) -> None:
    """A run says whether its configuration was recorded: 'config not recorded' where its session kept no board config."""
    rows = json.loads((data / "runs.json").read_text())["rows"]
    bare = next((r for r in rows if r.get("config") == "not recorded"), None)
    if bare is None:
        check(True, "every run has a full config snapshot (no 'config not recorded' to show)")
        return
    page.goto(f"{base}/{DEP}/runs/{bare['run']}/")
    page.wait_for_load_state("load")
    head = page.locator(".phead, header, h1").first.evaluate("el => (el.closest('.phead') || el.parentElement).textContent")
    open_tab(page, "evidence")
    ev = page.locator("[role=tabpanel][data-tab=evidence]").inner_text()
    check("config not recorded" in head and "Configuration" in ev and bare["config_detail"].split(".")[0] in ev,
          f"a run whose session kept no board config says 'config not recorded' in its header and what is recorded on Evidence ({bare['run'][:60]})")


ORACLE_EXAMPLES = ("pendulum_can11", "ur5e", "ur5e_2f85", "conveyor", "dual_arm_cell", "linescan_cell")


def oracle_results() -> dict:
    """The committed sysid results, read here from the repo (the ruler), not from the built site."""
    out = {}
    for path in sorted((REPO / "sysid" / "results").glob("*.json")):
        out[path.stem] = json.loads(path.read_text())
    return out


def oracle_data_checks(out: Path) -> None:
    """No browser: the site serves the committed results byte for byte, and the landing page and every example page print the
    result's own numbers (landing.num of the displayed value: the same formatter the page uses, never a re-derivation)."""
    import landing  # noqa: PLC0415

    results = oracle_results()
    served = {p.stem for p in (out / "data" / "sysid").glob("*.json")}
    same = [name for name in results if (out / "data" / "sysid" / f"{name}.json").read_bytes() == (REPO / "sysid" / "results" / f"{name}.json").read_bytes()]
    check(served == set(results) and len(same) == len(results), f"the site serves sysid/results byte for byte ({len(same)} of {len(results)} files)")
    home = (out / "index.html").read_text()
    section = home[home.find('id="oracle"'):]
    cards = re.findall(r'<article class="s2r-ex" data-example="([^"]+)" data-params="(\d+)" data-params-pass="(\d+)"', section)
    want = [(x, str(results[x]["verdict"]["parameters"]), str(results[x]["verdict"]["parameters_pass"])) for x in ORACLE_EXAMPLES if x in results]
    check(cards == want and len(cards) == 6, f"the landing page has one card per example in order, each with its verdict counts ({[c[0] for c in cards]})")
    for x in ORACLE_EXAMPLES:
        doc = results.get(x)
        if doc is None:
            continue
        start = section.find(f'data-example="{x}"')
        card_html = section[start: section.find("</article>", start)]
        model = doc["description"]["model"]
        files = [Path(model["path"]).name] if model.get("path") else [Path(pt["path"]).name for pt in model.get("parts", [])]
        metrics = [m for m in doc["metrics"] if m.get("gated")]
        nums = [landing.num(m["before"], 3) for m in metrics] + [landing.num(m["after"], 3) for m in metrics]
        coverage = landing.num(doc["schedule"]["coverage"]["train"]["pct"], 3)
        missing = [t for t in [doc["title"]] + files + nums + [coverage] if t not in card_html]
        types = re.findall(r'data-type="([^"]+)"', card_html)
        check(not missing and types and all(t == r["type"] for t, r in zip(types, [r for r in doc["tree"] if r["group"] != "structure" or r["depth"] > 0])),
              f"the {x} card shows its description in, its typed tree, its coverage and its held-out before -> after (missing {missing[:4]})")
        page_html = (out / "sysid" / x / "index.html").read_text()
        keys = re.findall(r'<tr data-key="([^"]+)"', page_html)
        # each row's own recovered cell (its bold value), not anywhere on the page: a recovered value that rounds like the true one
        # would otherwise be found in the true column (mutation-tested 2026-11-05: an altered conveyor radius slipped past)
        row_html = dict(re.findall(r'<tr data-key="([^"]+)">(.*?)</tr>', page_html, re.S))
        bold = {k: (re.search(r"<b>([^<]*)</b>", v) or [None, ""])[1] for k, v in row_html.items()}
        printed = [r for r in doc["parameters"] if landing.num(landing.display(r["recovered"], r["unit"])[0]) + " " not in bold.get(r["key"], "") + " "]
        check(keys == [r["key"] for r in doc["parameters"]] and not printed,
              f"/sysid/{x}/ lists every parameter ({len(keys)} of {len(doc['parameters'])}) with its recovered value printed (unprinted {[r['key'] for r in printed][:3]})")
    wear, knock = results.get("drift_backlash_wear"), results.get("drift_camera_knock")
    if wear:
        html = (out / "sysid" / "pendulum_can11" / "index.html").read_text()
        got = {k: re.search(rf'data-{k}="([^"]+)"', html) for k in ("predicted", "actual", "alarm", "rate")}
        want_w = {"predicted": wear["predicted_crossing_h"], "actual": wear["actual_crossing_h"], "alarm": wear["detector_alarm_h"], "rate": wear["rate_recovered"]}
        check(all(got[k] and float(got[k].group(1)) == float(v) for k, v in want_w.items()),
              f"CAN 11's page carries the wear demo's forecast, crossing, alarm and rate as committed ({ {k: g.group(1) if g else None for k, g in got.items()} })")
    if knock:
        html = (out / "sysid" / "dual_arm_cell" / "index.html").read_text()
        m = re.search(r'data-alarm="([^"]+)"', html)
        check(bool(m) and float(m.group(1)) == float(knock["alarm_h"]), f"the cell's page carries the camera knock's alarm hour ({m.group(1) if m else None} vs {knock['alarm_h']})")


def oracle_checks(page, base: str, still) -> None:
    """In the browser: the oracle section on the landing page lays its six cards out in a grid (measured), each card's parts are
    drawn, and a card opens its example's page."""
    results = oracle_results()
    page.goto(f"{base}/")
    page.wait_for_load_state("load")
    page.locator("#oracle").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    boxes = page.evaluate("""[...document.querySelectorAll('#oracle article.s2r-ex')].map(a => { const r = a.getBoundingClientRect();
        return {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
                parts: [...a.querySelectorAll('h4')].map(h => h.textContent.trim()), rows: a.querySelectorAll('.s2r-ex-params tbody tr[data-key]').length}; })""")
    columns = len({b["x"] for b in boxes})
    parts = ["Description in", "Typed tree", "Schedule and coverage", "Parameters: true / nominal / recovered", "Held-out error, before → after"]
    check(len(boxes) == 6 and columns >= 2 and all(b["w"] >= 300 and b["h"] > 200 for b in boxes) and all(b["parts"] == parts for b in boxes)
          and all(b["rows"] >= 4 for b in boxes),
          f"the landing page draws six oracle cards in {columns} columns, each at least 300 px wide with its five parts and its parameter rows "
          f"({[(b['w'], b['rows']) for b in boxes]})")
    still("20-oracle-cards")
    page.locator("#oracle article[data-example=pendulum_can11] .s2r-ex-open a").click()
    page.wait_for_url(re.compile(r"/sysid/pendulum_can11/$"), timeout=20000)
    page.wait_for_load_state("load")
    rows = page.locator("table.s2r-ex-full tbody tr").count()
    drift_fig = page.locator("#drift ~ figure svg polyline").count()
    check(rows == len(results["pendulum_can11"]["parameters"]) and drift_fig >= 1,
          f"a card opens its example: /sysid/pendulum_can11/ lists {rows} parameters and draws the wear chart ({drift_fig} line)")
    still("21-oracle-can11")


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
    explanation_checks(data, path, doc, out)
    triage_checks(data, path, doc)
    station_runs_checks(data, rack_layout(REPO / "app" / "registry.json")[0])
    portability_checks(out)
    schedule_freshness_checks(out, adapter.SCHEDULES)
    served_explanation_checks(out)
    types_served_checks(out)
    whole = [r["started"] for r in json.loads((data / "runs.json").read_text())["rows"]]
    check(whole == sorted(whole, reverse=True), f"runs.json is newest first ({len(whole)} runs)")
    run_set_checks(data, out)
    oracle_data_checks(out)
    # the deployment tree, the run tags and the configuration snapshot (Zach, PROJECT - Sim2Real, Nov 5 2026)
    layout = deploy_tree_checks(data, out, doc)
    import tempfile  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as scratch:
        config_snapshot_unit_checks(Path(scratch))

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
            # the data the dashboards read is served (Codex round 3, gap 1): the newest run's samples and the coverage set, fetched by the page
            newest_run = json.loads((data / "runs.json").read_text())["rows"][0]["run"]
            loads = page.evaluate("""async (urls) => Promise.all(urls.map(async u => { try { const r = await fetch(u); const j = r.ok ? await r.json() : null;
                return [u, r.status, j && Array.isArray(j.rows) ? j.rows.length : (Array.isArray(j) ? j.length : -1)]; } catch (e) { return [u, String(e), -1]; } }))""",
                                  [f"/data/{DEP}/runs/{newest_run}/samples.json", f"/data/{DEP}/coverage.json"])
            check(all(status == 200 and n > 0 for _u, status, n in loads), f"the newest run's samples and coverage.json load in the browser ({loads})")
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
                check(rack_card.get("points") == want_rack and re.search(rf"\b{want_rack[-1]}\b", rack_card.get("value") or "") and "88" in (rack_card.get("text") or "")
                      and rack_card.get("rules", 0) >= 1 and rack_card.get("width", 0) > 100,
                      f"kpi_trend: the rack's cells passing is the newest acceptance's, its trend every acceptance file's ({rack_card.get('points')} vs {want_rack}), "
                      f"88 cells its target ({rack_card.get('value')!r}, {rack_card.get('rules')} target rule, {rack_card.get('width', 0):.0f} px wide)")
                station_cards = page.evaluate(KPI_JS, "Passing per station · history") or []
                order = ["CAN 1", "CAN 4", "CAN 11", "CAN 12", "CAN 13", "CAN 14", "CAN 15", "CAN 21"]
                want_station = {dev: [sum(1 for (d, _g), v in cells_.items() if d == dev and v == "pass") for _p, _d, cells_ in history] for dev in order}
                check({c.get("label"): c.get("points") for c in station_cards} == want_station and all("target 11" in c.get("text", "") for c in station_cards),
                      f"kpi_trend per station: 8 cards, each its station's cells passing per acceptance file against its 11 cells ({len(station_cards)} cards)")
                wait_view(page, "The rack", "s.querySelectorAll('td[data-col=worst] .dv-state').length > 0")
                page.wait_for_timeout(500)
                tree = page.evaluate(TREE_JS, "The rack") or []
                gate_rows = json.loads((data / "gates.json").read_text())["rows"]
                dev_rows = json.loads((data / "devices.json").read_text())["rows"]
                # WHY adapters, not plates (ruler change, named; Zach, PROJECT - Sim2Real, Nov 5 2026: each deployment's tree is like
                # RobotDx's entity tree, host -> adapter -> board): the rack's middle level is each fdcanusb the record wires its boards to
                _entry, adapter_of = rack_layout(REPO / "app" / "registry.json")
                plate = lambda device: f"fdcanusb {adapter_of[device]}"  # noqa: E731
                worst_dev = {d["device"]: max(RANK[g["verdict"]] for g in gate_rows if g["device"] == d["device"]) for d in dev_rows}
                want_tree = {"One Dof Test Rack": max(worst_dev.values())}
                for d in dev_rows:
                    want_tree[plate(d["device"])] = max(want_tree.get(plate(d["device"]), 0), worst_dev[d["device"]])
                got_tree = {}
                for r in tree:
                    label = re.sub(r"^[▾▸]\s*", "", r["label"])
                    key = label.split(" · ")[0] if label.startswith("CAN ") else re.sub(r"\d+$", "", label)  # a group's row ends in its count
                    got_tree[key] = r["word"]
                want_words = {**{k: RANK_WORD[v] for k, v in want_tree.items()}, **{k: RANK_WORD[v] for k, v in worst_dev.items()}}
                check(got_tree == want_words and all(r["glyph"] and r["shown"] for r in tree),
                      f"rollup_tree: the rack, its adapters and stations each show the worst gate under them, word and glyph ({len(tree)} rows; "
                      f"differ {sorted(k for k in want_words if got_tree.get(k) != want_words[k])[:4]})")
                # each node's match in numbers too: the cells passing of every cell under it (data-ui's roll-up: Sum and Count of passes)
                cols = page.evaluate(ROLLUP_COLS_JS, "The rack") or []
                acc = {(f"CAN {can}", g["id"]): g["status"] for can, st in doc["stations"].items() for g in st["gates"]}
                under = lambda key: [d for d in adapter_of if key in (d, plate(d), "One Dof Test Rack")]  # noqa: E731
                want_cols = {key: (sum(1 for (d, _g), v in acc.items() if d in under(key) and v == "pass"), sum(1 for (d, _g) in acc if d in under(key)))
                             for key in want_tree.keys() | set(adapter_of)}
                got_cols = {}
                for r in cols:
                    label = re.sub(r"^[▾▸]\s*", "", r["label"])
                    key = label.split(" · ")[0] if label.startswith("CAN ") else re.sub(r"\d+$", "", label)
                    got_cols[key] = (int(float(r["passing"] or -1)), int(float(r["cells"] or -1)))
                check(got_cols == want_cols, f"rollup_tree: every node counts the gate cells passing under it, of all of them, from the newest acceptance "
                                             f"(differ {sorted((k, got_cols.get(k), v) for k, v in want_cols.items() if got_cols.get(k) != v)[:3]})")
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
                poses = [r for r in json.loads((data / "runs" / slug / "poses.json").read_text())["rows"] if r["body"] == "marker_100mm" and r["source"] == "real"]
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
            check(sum(1 for r in rows if r["next"].startswith("blocked on Zach")) > 0 and any(r.get("floor_rules") and "the gates use the pooled floor" in r["floor_rules"] for r in rows),
                  "rows name what is blocked on Zach, and the floor rule in force where the verdict depends on it (pooled, the 2026-11-04 default)")
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
            check(all(x in caveat_text for x in ("1.72×", "2.28×", "The gates use the safer pick")),
                  "the caveats name the pick rules on CAN 11 with both numbers (safer 1.72×, declared 2.28×) and the rule in force (safer, the 2026-11-04 default)")
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

            # 8a. CAN 11's T4 and T7 rows on the Why it fails page, read as the browser draws them (Codex round 5, gaps 1 and 3)
            page.goto(f"{base}/analysis/why-it-fails/#can11-T4")
            page.wait_for_load_state("load")
            drawn_rows = {}
            for gid in ("T4", "T7"):
                art = page.locator(f"article#can11-{gid}")
                art.wait_for(timeout=30000)
                art.scroll_into_view_if_needed()
                drawn_rows[gid] = art.inner_text()
                if args.record:
                    art.screenshot(path=str(args.record / f"11-why-can11-{gid}.png"))
            t4, t7 = drawn_rows["T4"], drawn_rows["T7"]
            check(not NO_RUNNER_PATH.search(t4 + t7) and "ff_fb" in t4 and "against the runner's 2.64 N.m allowance" in t4
                  and "4.66 N.m in amplitude" in t4 and "4.66 N.m in amplitude" in t7 and "exceeds" not in t4 + t7,
                  "the browser draws CAN 11 T4 with the runner's ff_fb / ff_weakfb plans and the planned demand against its allowance, and T7 "
                  "with 4.66 N.m as gravity's amplitude, never a cap it exceeds")

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
            if args.record:
                sched.locator(".s2r-commands").first.scroll_into_view_if_needed()
                sched.locator(".s2r-commands").first.screenshot(path=str(args.record / "12-schedule-commands.png"))
                page.screenshot(path=str(args.record / "12b-schedule-tab.png"), full_page=False)
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
            # 8b'. every station with a delivered schedule (bam_rack_twin.schedule build-rack, 2026-11-04: one schedule for every servo)
            # has its own Schedule tab listing its own plans' commands, not only CAN 11
            served = sorted(p.name for p in (data / "schedule").iterdir() if (p / "summary.json").is_file())
            shown = {}
            for key in served:
                own = json.loads((data / "schedule" / key / "summary.json").read_text())
                page.goto(f"{base}/{DEP}/{key}/")
                page.wait_for_load_state("load")
                tabs_here = page.evaluate("[...document.querySelectorAll('nav.tabs [role=tab]')].map(t => t.textContent.trim())")
                if "Schedule" not in tabs_here:
                    shown[key] = "no Schedule tab"
                    continue
                open_tab(page, "schedule")
                pres = page.locator("[role=tabpanel][data-tab=schedule] .s2r-commands pre").all_inner_texts()
                shown[key] = len(pres) == len(own["commands"]) and all(f"--plan /" in t and f"/{key}/plans/" in t for t in pres)
            check(len(served) > 1 and all(v is True for v in shown.values()),
                  f"every station with a delivered schedule has a Schedule tab with its own plans' commands ({len(served)} stations: {shown})")

            # 8c. a station's Gates tab (CONTRACT §35): the run checks' evidence in the side peek, whose link lands on the run's
            # playback at its window
            with guard("CAN 12's Gates tab"):
                page.goto(f"{base}/{DEP}/can12/#gates")
                page.wait_for_load_state("load")
                rg = json.loads((data / "run_gates.json").read_text())["rows"]
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
                panel(page, name).scroll_into_view_if_needed()  # the scene draws once it is on screen
                wait_view(page, name, "!!s.querySelector('.dv-scene3d') && !!s.querySelector('.dv-scene3d').scene3d && !!s.querySelector('.dv-scene3d').scene3d.ramp() && s.querySelector('.dv-scene3d').scene3d.renders() > 0", timeout=60000)
                page.wait_for_timeout(1500)
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
                ends_ok = bool(ramp) and tone and as_hex(ramp.get("lo")) == as_hex(tone.get("bad")) and as_hex(ramp.get("hi")) == as_hex(tone.get("good"))
                check(ramp and ramp.get("domain") == [0, max(counts.values())] and len(drawn) == len(counts)
                      and sorted(c[3] for c in drawn) == sorted(counts.values()),
                      f"voxels value: runs counts the whole rack's runs per cell, every drawn cell's count equal to coverage.json's ({len(drawn)} cells drawn of "
                      f"{len(counts)}, ramp 0..{ramp.get('domain', [None, None])[1]} vs the busiest cell's {max(counts.values())} runs; {len(set(r['run'] for r in cov))} runs)")
                check(ends_ok, f"scale: verdict: few runs in the bad tone, many in the good ({ramp.get('lo')} .. {ramp.get('hi')} vs {tone.get('bad')} .. {tone.get('good')})")
                still("8e-coverage-voxels")

            # 9. the Analysis area: Why it fails as one readable report
            page.goto(f"{base}/analysis/why-it-fails/")
            report_cells = page.evaluate("[...document.querySelectorAll('.s2r-why [data-cell]')].map(r => r.dataset.cell)")
            check(set(report_cells) >= {f"{d} {g}" for d, g in open_cells} and page.locator("aside[data-resizable]").count() == 1,
                  f"Analysis › Why it fails lists every open cell ({len(set(report_cells))} rows), beside a resizable contents column")
            still("11-analysis-why")

            # 11. Types (2026-11-04, written before the area): one card per part type from type_cards/registry.py, a station links to
            # its type card, and the Servo card's Coverage tab shows CAN 11's planned coverage, the number schedule.py computes
            with guard("the Types area"):
                types_checks(page, base, still)

            # 14. the system-ID oracle on the landing page (sysid/, site/landing.py; Zach's Nov 5 examples)
            with guard("the oracle cards"):
                oracle_checks(page, base, still)

            # 13. the deployment tree in the rail, every run flat, a run's configuration (Zach, PROJECT - Sim2Real, Nov 5 2026)
            with guard("the deployment tree in the rail"):
                tree_rail_checks(page, base, data, layout, still)
            with guard("every run flat on /runs/"):
                flat_runs_checks(page, base, layout, still)
            with guard("a run's configuration snapshot"):
                run_config_checks(page, base, data)

            # 10. a phone: no sideways scroll anywhere on the click path, the search still in the bar
            page.set_viewport_size({"width": 390, "height": 844})
            for url in ("/", f"/{DEP}/", f"/{DEP}/runs/{run_slug}/", f"/{DEP}/can12/", f"/{DEP}/can11/#schedule", "/analysis/why-it-fails/",
                        f"/{DEP}/#gates", f"/{DEP}/can12/#gates", "/types/", "/types/servo/#coverage", "/types/servo/#model", "/types/servo/#tests",
                        "/types/servo/#metrics", "/types/conveyor/#model", "/runs/", "/sysid/pendulum_can11/", "/sysid/linescan_cell/"):
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
