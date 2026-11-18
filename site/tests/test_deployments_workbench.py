"""The Deployments workbench (/deployments/), clicked through in headless Chromium on the built site: the acceptance of 2026-11-17.

    env -u VIRTUAL_ENV uv run --isolated --no-project --with-editable /home/bam/robot_msgs python /home/bam/sim2real/site/build.py
    env -u VIRTUAL_ENV taskset -c 2-5,16,17 uv run --isolated --no-project --with playwright python /home/bam/sim2real/site/tests/test_deployments_workbench.py
    ... test_deployments_workbench.py --out /abs/site --record /abs/capture/dir      (stills s01..s15 and the click-through walk.webm)

Zach's journey (Daily Note 2026-11-17: "Sim2Real at the top level we seperate it into DEPLOYMENTS. When I click into each deployment I
should bring up the 3D viewer of that deployment AND the tree should be the typed component tree. then If I click on any of the things in
that tree than I can see the dat relevant to that level"; "# Ok": "performance is first and up center"; "Runs are the atomic unit ...
drill into a particular run (rerun)"), each step measured, never a screenshot-only claim:

  Deployments -> the One Dof Test Rack: performance leads (all six to 0.9 of top speed, 67 of 72 real performance gates, the top gap at
  full speed), fidelity under it (CAN 11's twin 2.14x) -> the round-by-round chart with its goal line and the stations x speed grid ->
  CAN 11 in the tree: performance first, fidelity 2.14x beside round 0's 4.27x -> its Metrics tab, performance and fidelity as two groups
  with round 0 · now · change -> the Table view's five question columns -> "What changed" -> the servo: driver, motor, gearbox and encoder
  under it, motor and gearbox "not observable on this rack", the 3D pulled apart -> Runs: round 8's 252 runs, a summary on top, every
  recording a working link (the launcher answers HEAD 200 and data_recorder.runlink resolves the id to the file; nothing is opened).
  And the panels: the tree's boundary drags +70 px, survives a reload, resets on double-click; the 3D strip drags; the inspector folds;
  a click on a station's mesh in 3D selects it; no console error anywhere.

Then Obsidian's frame (Zach 2026-11-17: "the left toolbar sidebar like Obsidian ... 3 primary views could be the Scene View, the Sheet
view and the Workbench-like view"), measured with getBoundingClientRect: the ribbon 44 px at the far left with its icons (18 px in 30 x 26
buttons, 4 px apart, Runs in a group of its own) and their tooltips to the right; the sidebar toggle in the ribbon's 40 px header cell;
the sidebar 300 px, collapsed and reopened, its width and its state remembered; Scene (the 3D filling the page, every station's
performance in place, CAN 11 clicked in 3D, the time bar to round 0) -> Sheet (CAN 11 and round 0 carried; performance round 0 · now ·
change first, fidelity beside it, the 3D and inspector docked) -> Workbench (CAN 11's page, as found) -> Runs (CAN 11 still selected,
its 42 runs one click away; a tree pick filters); the servo pulled apart in the Scene, motor and gearbox "not observable on this rack";
the right inspector folds and the 3D takes the room.

Serves OUT with `python3 -m http.server` on a free port in 4711-4799 and stops it by the PID it started. Exits 1 on any FAIL.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path.home() / ".cache" / "sim2real" / "site"
EXE = str(max(Path.home().glob(".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
              key=lambda p: int(p.parts[-3].rsplit("-", 1)[1])))
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
DEP = "/deployments/?d=one-dof-test-rack"
FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILS.append(what)


def free_port(lo: int = 4711, hi: int = 4799) -> int:
    for port in range(lo, hi + 1):
        with contextlib.closing(socket.socket()) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit("no free port in 4711-4799")


@contextlib.contextmanager
def serve(out: Path):
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            with contextlib.closing(socket.socket()) as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def text(page, selector: str) -> str:
    el = page.query_selector(selector)
    return el.inner_text() if el else ""


def width(page, selector: str) -> float:
    return page.evaluate(f"document.querySelector('{selector}').getBoundingClientRect().width")


def height(page, selector: str) -> float:
    return page.evaluate(f"document.querySelector('{selector}').getBoundingClientRect().height")


def head_status(url: str) -> int:
    """HEAD the launcher like a local program (no Fetch Metadata): it answers without opening a viewer (bam_trackio.replay_link)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return 0


def resolves(url: str) -> Path | None:
    src = Path("/home/bam/data_recorder/src")
    if str(src) not in sys.path:
        sys.path.append(str(src))
    from data_recorder import runlink  # noqa: PLC0415

    return runlink.resolve(url.rstrip("/").rsplit("/", 1)[-1])


def run(base: str, record: Path | None) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=EXE, args=ARGS)
        video = {"record_video_dir": str(record), "record_video_size": {"width": 1440, "height": 900}} if record else {}
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark", **video)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        def still(name: str) -> None:
            if record:
                page.screenshot(path=str(record / f"{name}.png"))

        def ready() -> None:
            page.wait_for_function("document.getElementById('dw') && document.getElementById('dw').dataset.ready === '1'", timeout=20000)

        def pause(ms: int = 900) -> None:
            page.wait_for_timeout(ms if record else 250)

        # 0. a clean slate: no remembered panel sizes or folds
        page.goto(base + "/deployments/")
        page.evaluate("Object.keys(localStorage).filter((k) => k.startsWith('s2r.deployments-workbench.')).forEach((k) => localStorage.removeItem(k))")
        page.reload()
        ready()
        pause(1200)

        # 1. Deployments: every deployment; the rack opens the workbench, a virtual one its own page
        rows = page.eval_on_selector_all(".dw-drow", "els => els.map((a) => [a.dataset.dep, a.getAttribute('href')])")
        rack = [h for d, h in rows if d == "one-dof-test-rack"]
        virtual = [h for d, h in rows if d == "pendulum_can11"]
        check(len(rows) == 8 and rack and "d=one-dof-test-rack" in rack[0] and virtual == ["/deployments/pendulum_can11/"],
              f"/deployments/ lists the 8 deployments; the rack opens the workbench, a virtual one its page ({len(rows)}: {rows[:2]})")
        check("67 of 72 performance gates" in text(page, '.dw-drow[data-dep="one-dof-test-rack"]'),
              "the rack's row leads with performance: 67 of 72 real performance gates (was 28)")
        still("s01-deployments")

        # 2. the rack: performance first, the top gap, fidelity under it
        page.click('.dw-drow[data-dep="one-dof-test-rack"]')
        page.wait_for_selector(".dw-answer .row.lead")
        pause(1500)
        lead = text(page, ".dw-answer .row.lead")
        rows_text = page.eval_on_selector_all(".dw-answer .row", "els => els.map((e) => e.querySelector('.lab').textContent)")
        check(rows_text[:1] == ["Performance"] and "All six stations track" in lead and "67 of 72" in lead,
              f"the rack's answer leads with performance ({rows_text}; {lead[:120]!r})")
        gap = text(page, ".dw-answer .row:nth-child(2)")
        check("top gap" in gap.lower() and "full speed" in gap and "CAN 1, CAN 12, CAN 13, CAN 14, CAN 15" in gap,
              f"the top performance gap is named: tracking at full speed on five stations ({gap[:140]!r})")
        fid = text(page, ".dw-answer .row.fid")
        check(rows_text[-1] == "Fidelity" and "CAN 11" in fid and "2.14×" in fid and "4.27×" in fid,
              f"fidelity sits under performance: CAN 11's twin 2.14x, as found 4.27x ({fid[:140]!r})")
        check("Worst stop" in rows_text and "0.4, 0.9, 1.0" in text(page, ".dw-answer"),
              "CAN 11's worst stop over 1 mm at the 0.4, 0.9 and 1.0 rungs is shown beside the median")
        still("s02-rack-performance")
        page.evaluate("document.getElementById('dw-tabbody').scrollIntoView()")
        pause(800)
        svg_text = page.eval_on_selector_all("#dw-tabbody svg text", "els => els.map((e) => e.textContent)")
        check(any(t == "GOOD ≤ 0.5°" for t in svg_text) and any(t == "GOOD ≤ 1 mm" for t in svg_text),
              "the round-by-round charts draw the goal line: GOOD ≤ 0.5° and GOOD ≤ 1 mm")
        cells = page.eval_on_selector_all("table.dw-grid2 tbody tr", "trs => trs.map((tr) => [...tr.querySelectorAll('td')].map((td) => td.className))")
        fails_at_full = sum(1 for r in cells if r and r[-1] == "fail")
        check(len(cells) == 6 and fails_at_full == 5, f"the stations x speed grid: 6 stations, 5 miss tracking at full speed ({len(cells)} rows, {fails_at_full})")
        still("s03-rack-round-by-round")

        # 3. a click on CAN 12's mesh in 3D selects it (the joint's projected point, not its label)
        page.evaluate("document.getElementById('dw-entity').scrollTop = 0")
        pause(400)
        pt = page.evaluate("(() => window.__dwRack.screenOf('can12'))()")
        page.mouse.click(pt["x"], pt["y"] + 2)
        pause(700)
        check(page.url.endswith("n=can12"), f"a click on CAN 12's station in 3D selects the station ({page.url[-40:]})")

        # 4. CAN 11 in the tree: performance first, fidelity 2.14x with round 0 beside it
        page.click('.dw-tree li[data-id="can11"] > .dw-trow')
        page.wait_for_function("location.search.includes('n=can11')")
        pause(1500)
        lead = text(page, ".dw-answer .row.lead")
        fid = text(page, ".dw-answer .row.fid")
        check("Tracks and stops up to 1.0 of top speed" in lead and "worst 1.14 mm" in lead,
              f"CAN 11 leads with performance: to 1.0 of top speed, worst stop 1.14 mm ({lead[:120]!r})")
        check("2.14×" in fid and "fails" in fid and "as found: 4.27×" in fid, f"CAN 11's fidelity: twin 2.14x, fails, round 0 4.27x ({fid[:120]!r})")
        still("s04-can11")
        page.click('.dw-tabs button[data-tab="metrics"]')
        pause(900)
        groups = page.eval_on_selector_all("#dw-tabbody table.dw-mt tr.grp td", "els => els.map((e) => e.firstChild.textContent)")
        twin = page.eval_on_selector("#dw-tabbody tr[data-m='twin_over_floor']", "tr => [...tr.querySelectorAll('td')].map((td) => td.textContent.trim())")
        check(groups == ["Performance", "Fidelity", "Evidence"], f"CAN 11's metrics: performance first, then fidelity, apart ({groups})")
        check(twin[1].endswith("4.27×") and twin[2].endswith("2.14×") and "better" in twin[3],
              f"twin ÷ floor: round 0 4.27x · now 2.14x · better ({twin[:4]})")
        page.evaluate("document.querySelector('#dw-tabbody table.dw-mt').scrollIntoView({block: 'start'})")
        pause(600)
        still("s05-can11-metrics")

        # 5. the Sheet (the Table view, renamed; view=table still opens it): the five question columns, then What changed
        page.evaluate("document.getElementById('dw-entity').scrollTop = 0")
        page.click('.dw-view[data-v="sheet"]')
        page.wait_for_selector("table.dw-tt")
        pause(900)
        still("s06-table-performance")
        page.click('[data-cols="questions"]')
        pause(900)
        # the question columns are now a group after the performance columns: found by what they are (th[data-q]), no longer by position
        heads = page.eval_on_selector_all("table.dw-tt thead th[data-q]", "els => els.slice(0, 5).map((e) => e.firstChild.textContent.trim())")
        check(heads == ["1 Floor", "2 Data", "3 Routines", "4 Twin", "5 Job"], f"the Table view's five question columns, in order ({heads})")
        twin_cell = page.eval_on_selector("tr[data-id='can11'] td[data-q='twin']", "td => [td.className, td.textContent.trim()]")
        check("fail" in twin_cell[0] and "2.14×" in twin_cell[1], f"CAN 11's Twin cell fails at 2.14x ({twin_cell})")
        if record:  # the question group sits right of performance and fidelity: bring it into the still
            page.evaluate("document.querySelector(\"tr[data-id='can11'] td[data-q='twin']\").scrollIntoView({block: 'nearest', inline: 'center'})")
        still("s07-table-questions")
        page.click('#dw-round button[data-r="changed"]')
        pause(900)
        changed = page.eval_on_selector("tr[data-id='can11'] td[data-q='twin']", "td => td.textContent.trim()")
        check("mode=changed" in page.url and "4.27×" in changed and "→" in changed and "2.14×" in changed,
              f"What changed: CAN 11's Twin reads 4.27x → 2.14x ({changed!r})")
        same = page.eval_on_selector_all("table.dw-tt tbody tr.same", "els => els.length")
        check(same > 0, f"rows that did not move are dimmed ({same})")
        if record:
            page.evaluate("document.querySelector(\"tr[data-id='can11'] td[data-q='twin']\").scrollIntoView({block: 'nearest', inline: 'center'})")
        still("s08-table-what-changed")
        # the inspector folds and comes back
        w_insp = width(page, "#dw-insp")
        page.keyboard.press("Escape")
        pause(300)
        folded = page.evaluate("document.getElementById('dw-insp').hidden")
        page.click("#dw-unfold")
        pause(300)
        check(w_insp >= 300 and folded and not page.evaluate("document.getElementById('dw-insp').hidden"),
              f"the inspector ({w_insp:.0f} px) folds on Esc and comes back")

        # 6. the servo: its four parts, motor and gearbox not observable on this rack, the 3D pulled apart
        page.click('.dw-view[data-v="page"]')
        page.wait_for_selector(".dw-tree")
        page.click('.dw-tree li[data-id="can11/servo"] > .dw-trow')
        page.wait_for_function("location.search.includes('n=can11%2Fservo') || location.search.includes('n=can11/servo')")
        pause(1800)
        kids = page.eval_on_selector_all(".dw-childs .dw-crow", "els => els.map((e) => [e.dataset.node, e.textContent])")
        names = [k[0].rsplit("/", 1)[-1] for k in kids]
        check(names == ["driver", "motor", "gearbox", "encoder"], f"the servo shows driver, motor, gearbox and encoder under it ({names})")
        motor = next((k[1] for k in kids if k[0].endswith("/motor")), "")
        gearbox = next((k[1] for k in kids if k[0].endswith("/gearbox")), "")
        check("not observable on this rack" in motor.lower() and "not observable on this rack" in gearbox.lower(),
              f"motor and gearbox say 'not observable on this rack' ({motor[-90:]!r} / {gearbox[-60:]!r})")
        tree_kids = page.eval_on_selector_all('.dw-tree li[data-id="can11/servo"] > ul > li', "els => els.map((e) => e.dataset.id)")
        check(len(tree_kids) == 4, f"the tree opens the servo on its parts ({tree_kids})")
        check(page.evaluate("window.__dwRack.exploded()") == "can11", "the 3D pulls CAN 11's servo apart")
        page.evaluate("document.querySelector('.dw-childs').scrollIntoView({block: 'center'})")
        pause(700)
        still("s09-servo-parts")
        page.evaluate("document.getElementById('dw-entity').scrollTop = 0")
        page.click('.dw-childs .dw-crow[data-node="can11/servo/gearbox"]')
        pause(1000)
        check("Not observable on this rack" in text(page, ".dw-answer"), "the gearbox's own page says it is not observable on this rack")

        # 7. Runs: round 8 by default, the summary first, every recording a working link
        page.click('.dw-view[data-v="runs"]')
        page.wait_for_selector("table.dw-rt tbody tr")
        pause(1200)
        n_rows = page.eval_on_selector_all("table.dw-rt tbody tr", "els => els.length")
        summary = text(page, ".dw-rsum")
        check(n_rows == 252 and "runs in round 8" in summary.lower() and "252" in summary, f"Runs: round 8's 252 runs, a summary on top ({n_rows})")
        still("s10-runs")
        page.click('.dw-rst button[data-st="can11"]')
        pause(800)
        links = page.eval_on_selector_all("table.dw-rt a.rr", "els => els.map((a) => [a.href, a.target])")
        check(len(links) > 0 and all(t == "_blank" for _h, t in links) and all(h.startswith("http://127.0.0.1:8771/f/") for h, _t in links),
              f"CAN 11's runs: each opens its Rerun recording through the 8771 launcher, in a new tab ({len(links)} links)")
        sample = [links[0][0], links[len(links) // 2][0], links[-1][0]] if links else []
        ok = [(head_status(u), resolves(u)) for u in sample]
        check(len(ok) == 3 and all(s == 200 and f is not None and f.suffix == ".rrd" and f.is_file() for s, f in ok),
              f"3 links: the launcher answers HEAD 200 and runlink resolves each id to its .rrd ({[(s, f.name if f else None) for s, f in ok]})")
        page.click('.dw-rtop button[data-rr="0"]')
        pause(900)
        r0 = page.eval_on_selector_all("table.dw-rt tbody tr", "els => els.length")
        no_rec = page.eval_on_selector_all("table.dw-rt tbody td span.muted", "els => els.filter((e) => e.textContent === 'no recording yet').length")
        check(r0 > 0 and "rr=0" in page.url, f"the round picker shows round 0's runs ({r0} of CAN 11's; {no_rec} without a recording say so)")
        page.click('table.dw-rt th[data-sort="tracking_rms_deg"]')
        pause(300)
        rms = page.eval_on_selector_all("table.dw-rt tbody tr td:nth-child(6)", "els => els.map((e) => parseFloat(e.textContent))")
        rms = [x for x in rms if x == x]
        check(rms == sorted(rms) and len(rms) > 2, "a heading sorts the runs (tracking RMS, ascending)")

        # 8. panels: the tree's boundary drags, is remembered, resets; the 3D strip drags
        page.goto(base + DEP + "&n=can11")
        ready()
        pause(800)
        w0 = width(page, "#dw-left")
        box = page.locator("#dw-sashL").bounding_box()
        sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx + 70, sy, steps=6)
        page.mouse.up()
        w1 = width(page, "#dw-left")
        page.reload()
        ready()
        pause(600)
        w2 = width(page, "#dw-left")
        page.locator("#dw-sashL").dblclick()
        w3 = width(page, "#dw-left")
        check(abs((w1 - w0) - 70) <= 3 and abs(w2 - w1) <= 3 and abs(w3 - w0) <= 3,
              f"the tree's boundary drags +70 px, survives a reload, resets on double-click ({[round(w0), round(w1), round(w2), round(w3)]})")
        h0 = height(page, "#dw-sceneWrap")
        box = page.locator("#dw-sashS").bounding_box()
        sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx, sy + 60, steps=6)
        page.mouse.up()
        h1 = height(page, "#dw-sceneWrap")
        page.locator("#dw-sashS").dblclick()
        check(abs((h1 - h0) - 60) <= 3, f"the 3D strip's boundary drags +60 px ({round(h0)} -> {round(h1)})")

        # 9. the old index moved, still working
        page.goto(base + "/deployments/all/")
        page.wait_for_load_state("load")
        check(page.query_selector('data-views#deployments-views') is not None, "the filter-bar index of deployment cards lives on at /deployments/all/")

        # 10. Obsidian's frame (Zach 2026-11-17: "update it so it has the left toolbar sidebar like Obsidian. And then I think 3 primary
        # views could be the Scene View, the Sheet view and the Workbench-like view"), every claim measured
        page.goto(base + DEP)
        page.evaluate("Object.keys(localStorage).filter((k) => k.startsWith('s2r.deployments-workbench.')).forEach((k) => localStorage.removeItem(k))")
        page.reload()
        ready()
        pause(700)
        rb = page.evaluate("""(() => {
          const r = document.getElementById('dw-ribbon').getBoundingClientRect(), head = document.querySelector('.dw-rb-head').getBoundingClientRect();
          const t = document.getElementById('dw-sidetoggle').getBoundingClientRect();
          const items = [...document.querySelectorAll('.dw-rb')].map((a) => { const b = a.getBoundingClientRect(), s = a.querySelector('svg').getBoundingClientRect();
            return {v: a.dataset.v, x: b.left, y: b.top, w: b.width, h: b.height, sw: s.width, sh: s.height}; });
          return {left: r.left, w: r.width, top: r.top, bottom: r.bottom, vh: innerHeight, head: head.height, tx: t.left, tr: t.right, tb: t.bottom,
                  seps: document.querySelectorAll('.dw-rb-sep').length, items}; })()""")
        views = [i["v"] for i in rb["items"]]
        check(rb["left"] == 0 and abs(rb["w"] - 44) < 0.5 and abs(rb["bottom"] - rb["vh"]) < 1,
              f"the ribbon: a 44 px strip at the far left, down to the bottom (left {rb['left']}, width {rb['w']:.1f}, bottom {rb['bottom']:.0f} of {rb['vh']})")
        sizes = sorted({(round(i["w"]), round(i["h"]), round(i["sw"]), round(i["sh"])) for i in rb["items"]})
        gaps = [round(rb["items"][k + 1]["y"] - rb["items"][k]["y"] - rb["items"][k]["h"]) for k in range(len(rb["items"]) - 1)]
        check(views == ["home", "scene", "sheet", "page", "runs"] and rb["seps"] == 2 and gaps[1:3] == [4, 4] and gaps[0] > 4 and gaps[3] > 4,
              f"its icons: Deployments, then the three views Scene · Sheet · Workbench 4 px apart, then Runs in a group of its own ({views}, gaps {gaps})")
        check(sizes == [(30, 26, 18, 18)] and all(abs(i["x"] + i["w"] / 2 - 22) < 1 for i in rb["items"]),
              f"Obsidian's icon geometry: an 18 px icon in a 30 x 26 button, centred in the strip ({sizes})")
        check(abs(rb["head"] - 40) < 1 and rb["tx"] >= 0 and rb["tr"] <= 44 and rb["tb"] <= rb["top"] + 40,
              f"the sidebar toggle sits in the ribbon's 40 px header cell, where Obsidian puts it (cell {rb['head']:.1f} px)")
        tips = []
        for sel in [f'.dw-rb[data-v="{v}"]' for v in views] + ["#dw-sidetoggle"]:
            page.mouse.move(5, 700)
            pause(150)
            page.hover(sel)
            page.wait_for_selector("#dw-tip:not([hidden])", timeout=3000)
            tips.append(page.evaluate("""(sel) => { const el = document.querySelector(sel), b = el.getBoundingClientRect(), tp = document.getElementById('dw-tip'), r = tp.getBoundingClientRect();
                return [tp.textContent, el.dataset.tip, r.left - b.right, (r.top + r.height / 2) - (b.top + b.height / 2), r.width]; }""", sel))
            if sel.endswith('"scene"]'):
                pause(500)
                still("s11-ribbon-tooltip")
        page.mouse.move(700, 700)
        check(len(tips) == 6 and all(t[0] == t[1] and t[0] and 4 <= t[2] <= 12 and abs(t[3]) <= 1.5 and t[4] > 40 for t in tips),
              f"every ribbon icon and the toggle show their tooltip to the right, centred on them ({[t[0] for t in tips]})")

        # the sidebar: 300 px by default; the toggle collapses it (the view takes the room) and the choice survives a reload; its width
        # drags, survives a collapse and a reload, and resets on double-click
        side0, work0 = width(page, "#dw-left"), width(page, ".dw-work")
        page.click("#dw-sidetoggle")
        pause(300)
        closed = page.evaluate("[document.getElementById('dw-left').hidden, document.getElementById('dw-left').getBoundingClientRect().width, document.getElementById('dw-sidetoggle').getAttribute('aria-expanded')]")
        work1 = width(page, ".dw-work")
        page.reload()
        ready()
        pause(400)
        still_closed = page.evaluate("document.getElementById('dw-left').hidden")
        page.click("#dw-sidetoggle")
        pause(300)
        side1 = width(page, "#dw-left")
        check(abs(side0 - 300) <= 1 and closed[0] and closed[1] == 0 and closed[2] == "false" and work1 - work0 >= side0 - 1 and still_closed and abs(side1 - side0) <= 1,
              f"the toggle collapses the sidebar ({side0:.0f} -> 0 px, the view grows {work1 - work0:.0f} px), it stays collapsed after a reload, and opens again at {side1:.0f} px")
        box = page.locator("#dw-sashL").bounding_box()
        sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(sx, sy)
        page.mouse.down()
        page.mouse.move(sx + 50, sy, steps=6)
        page.mouse.up()
        wa = width(page, "#dw-left")
        page.click("#dw-sidetoggle")
        pause(200)
        page.click("#dw-sidetoggle")
        pause(200)
        wb = width(page, "#dw-left")
        page.reload()
        ready()
        pause(400)
        wc = width(page, "#dw-left")
        page.locator("#dw-sashL").dblclick()
        wd = width(page, "#dw-left")
        check(abs(wa - side0 - 50) <= 3 and abs(wb - wa) <= 1 and abs(wc - wa) <= 1 and abs(wd - 300) <= 1,
              f"the sidebar's width drags +50 px and is remembered through a collapse and a reload; double-click resets it ({[round(wa), round(wb), round(wc), round(wd)]})")

        # Scene: the 3D is the page, each station wearing its performance; a click on CAN 11 in 3D selects it
        page.click('.dw-rb[data-v="scene"]')
        page.wait_for_selector("#dw-scene:not([hidden]) #dw-stage canvas")
        pause(1400)
        sc = page.evaluate("""(() => { const st = document.getElementById('dw-stage').getBoundingClientRect(), cv = document.querySelector('#dw-stage canvas').getBoundingClientRect();
          const shown = ['dw-home', 'dw-dep', 'dw-scene', 'dw-table', 'dw-runs'].filter((id) => !document.getElementById(id).hidden);
          const labels = [...document.querySelectorAll('#dw-stage .s-label:not(.s-plabel)')].filter((l) => !l.hidden && l.style.display !== 'none').map((l) => {
            const r = l.getBoundingClientRect(); return [l.dataset.id, l.querySelector('.dot').className, r.left >= st.left && r.right <= st.right && r.top >= st.top && r.bottom <= st.bottom]; });
          return {shown, sw: st.width, sh: st.height, cw: cv.width, ch: cv.height, labels, cur: document.querySelector('.dw-rb[aria-current]').dataset.v,
                  time: !!document.querySelector('#dw-timebar input[type=range]'), title: document.getElementById('dw-vtitle').textContent}; })()""")
        check(sc["shown"] == ["dw-scene"] and sc["cur"] == "scene" and "view=scene" in page.url and sc["title"].startswith("Scene") and sc["cw"] >= sc["sw"] - 2 and sc["ch"] >= sc["sh"] - 2 and sc["time"],
              f"Scene: the ribbon's Scene icon renders it, the 3D filling the page ({sc['cw']:.0f} x {sc['ch']:.0f} of {sc['sw']:.0f} x {sc['sh']:.0f}), a time bar under it")
        check(len(sc["labels"]) == 6 and all("pass" in c and inside for _i, c, inside in sc["labels"]),
              f"Scene: all 6 stations wear their performance in place, inside the view (now all pass: {[(i, c.split()[-1]) for i, c, _x in sc['labels']]})")
        pt = page.evaluate("window.__dwRack.screenOf('can11')")
        page.mouse.click(pt["x"], pt["y"] + 2)
        page.wait_for_function("new URLSearchParams(location.search).get('n') === 'can11'", timeout=5000)
        pause(1500)
        ins = page.evaluate("""(() => [document.querySelector('#dw-insp .dw-insp-head b').textContent, [...document.querySelectorAll('#dw-insp .dw-answer .row .lab')].map((e) => e.textContent),
            document.querySelector('.dw-tree li[aria-selected=true]').dataset.id, new URLSearchParams(location.search).get('view')])()""")
        check(ins[0].startswith("CAN 11") and ins[1] == ["Performance", "Fidelity"] and ins[2] == "can11" and ins[3] == "scene",
              f"Scene: a click on CAN 11 in 3D selects it, the tree follows, the inspector leads with performance, then fidelity ({ins})")
        still("s12-scene-can11")
        page.focus("#dw-time")
        page.keyboard.press("Home")
        page.wait_for_function("new URLSearchParams(location.search).get('round') === 'r0'", timeout=5000)
        pause(700)
        lab0 = text(page, '#dw-stage .s-label[data-id="can11"]')
        check("no rung" in lab0, f"Scene: the time bar moves to round 0 and CAN 11's label reads as found ({lab0!r})")

        # the selection (CAN 11) and the round (as found) carry across the views
        page.click('.dw-rb[data-v="sheet"]')
        page.wait_for_selector("#dw-table:not([hidden]) table.dw-tt")
        pause(1200)
        sh = page.evaluate("""(() => { const cell = (c, r) => (document.querySelector(`tr[data-id='can11'] td[data-c='${c}'][data-r='${r}']`) || {}).textContent;
          const chg = (c) => document.querySelector(`tr[data-id='can11'] td[data-c='${c}'][data-r='r8']`).nextElementSibling.className;
          const dock = document.querySelector('#dw-insp #dw-dock3d canvas'), insp = document.getElementById('dw-insp').getBoundingClientRect(), tbl = document.getElementById('dw-tablewrap').getBoundingClientRect();
          return {sel: (document.querySelector('table.dw-tt tr.sel') || {dataset: {}}).dataset.id, title: document.querySelector('#dw-insp .dw-insp-head b').textContent,
                  round: document.querySelector('#dw-round button[aria-pressed=true]').dataset.r, tree: document.querySelector('.dw-tree li[aria-selected=true]').dataset.id,
                  groups: [...document.querySelectorAll('table.dw-tt thead th.grp')].map((e) => e.textContent), q: document.querySelectorAll('table.dw-tt th[data-q]').length,
                  rung: [cell('rung', 'r0'), cell('rung', 'r8'), chg('rung')], twin: [cell('twin', 'r0'), cell('twin', 'r8'), chg('twin')],
                  dock: !!dock, docked: insp.left >= tbl.right - 8}; })()""")
        check(sh["sel"] == "can11" and sh["title"].startswith("CAN 11") and sh["tree"] == "can11" and sh["round"] == "r0",
              f"Scene -> Sheet: CAN 11 stays selected (row, inspector, tree) and the round stays as found ({sh['sel']}, {sh['tree']}, {sh['round']})")
        check(sh["groups"][:2] == ["Performance · real vs the target", "Fidelity · real vs sim"] and sh["q"] == 0,
              f"Sheet: the performance columns come first, fidelity beside them; the five questions an optional group, off by default ({sh['groups']}, {sh['q']} question columns)")
        check(sh["rung"][:2] == ["none", "1.0"] and "up" in sh["rung"][2] and sh["twin"][:2] == ["4.27×", "2.14×"] and "up" in sh["twin"][2],
              f"Sheet: round 0 · now · change side by side: CAN 11's highest rung none -> 1.0, its twin 4.27x -> 2.14x, both better ({sh['rung']}, {sh['twin']})")
        check(sh["dock"] and sh["docked"], "Sheet: the 3D and the inspector are docked on the right")
        still("s13-sheet")
        page.click('.dw-rb[data-v="page"]')
        page.wait_for_selector("#dw-dep:not([hidden]) .dw-title")
        pause(1000)
        wbn = page.evaluate("""(() => [document.querySelector('#dw-dep .dw-title').textContent, document.querySelector('.dw-tree li[aria-selected=true]').dataset.id,
            document.querySelector('#dw-round button[aria-pressed=true]').dataset.r, new URLSearchParams(location.search).get('view'), document.querySelector('.dw-rb[aria-current]').dataset.v])()""")
        check("CAN 11" in wbn[0] and wbn[1] == "can11" and wbn[2] == "r0" and wbn[3] is None and wbn[4] == "page",
              f"Sheet -> Workbench: CAN 11's page, as found ({wbn})")
        page.click('#dw-round button[data-r="r8"]')
        pause(500)
        page.click('.dw-rb[data-v="runs"]')
        page.wait_for_selector("#dw-runs:not([hidden]) table.dw-rt tbody tr")
        pause(900)
        rn = page.evaluate("""(() => [document.querySelector('.dw-tree li[aria-selected=true]').dataset.id, (document.querySelector('.dw-rfilters button[data-st]') || {}).textContent,
            document.querySelectorAll('table.dw-rt tbody tr').length])()""")
        page.click('.dw-rfilters button[data-st="can11"]')
        pause(700)
        only = page.eval_on_selector_all("table.dw-rt tbody tr td:first-child", "els => els.map((e) => e.textContent)")
        check(rn[0] == "can11" and "CAN 11" in (rn[1] or "") and rn[2] == 252 and len(only) == 42 and set(only) == {"CAN 11"},
              f"Workbench -> Runs: CAN 11 still selected; one click shows only its runs ({rn}; {len(only)} rows, {sorted(set(only))})")
        page.click('.dw-tree li[data-id="can12"] > .dw-trow')
        pause(700)
        only12 = page.eval_on_selector_all("table.dw-rt tbody tr td:first-child", "els => els.map((e) => e.textContent)")
        check("view=runs" in page.url and set(only12) == {"CAN 12"}, f"Runs: a pick in the tree filters the runs to its station ({sorted(set(only12))})")
        still("s15-runs-selected")

        # Scene: the servo pulled apart into its parts, each named in place; the inspector folds and the 3D takes the room
        page.click('.dw-tree li[data-id="can11"] > .dw-trow')
        page.click('.dw-rb[data-v="scene"]')
        page.wait_for_selector("#dw-scene:not([hidden])")
        page.click('.dw-tree li[data-id="can11/servo"] > .dw-trow')
        page.wait_for_function("new URLSearchParams(location.search).get('n') === 'can11/servo'", timeout=5000)
        pause(1900)
        parts = page.evaluate("""(() => { const st = document.getElementById('dw-stage').getBoundingClientRect();
          return [...document.querySelectorAll('#dw-stage .s-plabel')].filter((l) => !l.hidden && l.style.display !== 'none').map((l) => { const r = l.getBoundingClientRect();
            return [l.dataset.id.split('/').pop(), l.textContent, r.left >= st.left && r.right <= st.right && r.top >= st.top && r.bottom <= st.bottom]; }); })()""")
        named = {k: t for k, t, _in in parts}
        check(page.evaluate("window.__dwRack.exploded()") == "can11" and sorted(named) == ["driver", "encoder", "gearbox", "motor"] and all(i for _k, _t, i in parts)
              and "not observable on this rack" in named.get("motor", "") and "not observable on this rack" in named.get("gearbox", ""),
              f"Scene: CAN 11's servo pulls apart into driver, motor, gearbox, encoder, each named inside the view; motor and gearbox 'not observable on this rack' ({named})")
        still("s14-scene-servo")
        sw0 = width(page, "#dw-stage")
        page.click("#dw-unfold")
        pause(400)
        folded_r = page.evaluate("[document.getElementById('dw-insp').hidden, document.getElementById('dw-unfold').getAttribute('aria-expanded')]")
        sw1 = width(page, "#dw-stage")
        page.click("#dw-unfold")
        pause(400)
        sw2 = width(page, "#dw-stage")
        check(folded_r == [True, "false"] and sw1 - sw0 >= 300 and abs(sw2 - sw0) <= 1,
              f"Scene: the right inspector folds from the bar's toggle and the 3D takes the room ({round(sw0)} -> {round(sw1)} -> {round(sw2)} px)")

        # from the Deployments list, a view icon opens the deployment in that view (no dead icon on the home view)
        page.click('.dw-rb[data-v="home"]')
        page.wait_for_selector("#dw-home:not([hidden]) .dw-drow")
        home_ok = page.evaluate("[document.getElementById('dw-left').hidden, document.getElementById('dw-sidetoggle').hidden, document.querySelector('.dw-rb[aria-current]').dataset.v]")
        page.click('.dw-rb[data-v="sheet"]')
        page.wait_for_selector("#dw-table:not([hidden]) table.dw-tt")
        check(home_ok == [True, True, "home"] and "d=one-dof-test-rack" in page.url and "view=sheet" in page.url,
              f"Deployments: no tree to show, so no sidebar and no toggle; its Sheet icon opens the rack in the Sheet ({home_ok}, {page.url[-40:]})")

        check(not errors, f"no console error on the way ({errors[:3]})")
        ctx.close()
        browser.close()
        if record:
            videos = sorted(record.glob("*.webm"), key=lambda p: p.stat().st_mtime)
            if videos:
                videos[-1].rename(record / "walk.webm")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"the built site (site/build.py's OUT; default {DEFAULT_OUT})")
    parser.add_argument("--base", help="an already-running server's base URL instead of serving --out")
    parser.add_argument("--record", type=Path, help="write stills and the click-through video here")
    args = parser.parse_args()
    if args.record:
        args.record.mkdir(parents=True, exist_ok=True)
    if not (args.base or (args.out / "data" / "deployments-workbench.json").is_file()):
        raise SystemExit(f"no workbench data in {args.out}: build the site first (site/build.py)")
    if args.base:
        run(args.base.rstrip("/"), args.record)
    else:
        with serve(args.out) as base:
            run(base, args.record)
    print(f"{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failing check(s)")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
