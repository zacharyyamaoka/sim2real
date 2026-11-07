"""The overnight sim2real v3 report (2026-11-07): the one page Zach opens in the morning.

    python3 -m http.server 4795 --bind 127.0.0.1 --directory /home/bam/.cache/sim2real/site
    uv run --no-project --with playwright python /home/bam/sim2real/docs/build_report_sim2real_v3.py --base http://127.0.0.1:4795

Without --base it serves --site itself on a free port in 4711-4799 (never 4700 or Stable's 4820) and stops that server by the PID it
started. It records the hero click-through (deployments -> the rack -> a station -> a filmed run's entity tree -> the servo's models ->
routines -> parameters, errors only -> metrics with ticked rows -> reports) and the stills from the served build, cuts the hero to the
moments each page is ready (H.264, muted loop, a GIF fallback), and writes one self-contained page to
/home/bam/sim2real/reports/media/sim2real-v3-2026-11-07/report.html (reports/media/ is gitignored). --reuse skips the browser and builds
from the media already captured; --check renders the written page headless in dark mode at 1280 and 390 px and reports any sideways scroll.

WHY every table number is read here, not typed: the noise ladder, the drift alarm hours, the routine counts, the build record, the Stable
release and the rack's frame check come from their files (sysid/results, the site build, the switcher's state, /archive), so a re-run
after the data moves says what is true then. The words around them come from the decision records and PEPs this page cites.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path("/home/bam/sim2real")
BAM_WS = Path("/home/bam/bam_ws")
SITE = Path.home() / ".cache" / "sim2real" / "site"
MEDIA = REPO / "reports" / "media" / "sim2real-v3-2026-11-07"
OUT = MEDIA / "report.html"
STABLE = "http://127.0.0.1:4820"
SPS_STATE = Path.home() / ".local" / "state" / "stable-preview-switcher" / "sim2real"
ARCHIVE = Path("/archive/datasets/bam_rig")
DEP = "one-dof-test-rack"
# The hero's run: CAN 14's longest filmed waypoints run (its tag mid-frame on the GIM43 plate, in the camera's best light; the media
# lane's pick, docs/build_report_media_dashboards.py clip_run).
RUN = "2026-10-24~ratio~can14~runs~s01_can14_waypoints"
STATION_PAGE = "/deployments/one-dof-test-rack/fdcanusb-272813EF/can14/"
# The v3 work's two merges (git logs of 2026-11-07); checked to exist before the page names them.
SIM2REAL_MERGE = "d54a5f9"
BAM_WS_MERGE = "b8f60c85"
EXE = None  # resolved lazily: the newest Playwright headless shell

MIME = {".webp": "image/webp", ".png": "image/png", ".gif": "image/gif", ".mp4": "video/mp4", ".jpg": "image/jpeg"}


def esc(x) -> str:
    return html.escape(str(x))


def data_uri(path: Path) -> str:
    return f"data:{MIME[path.suffix]};base64,{base64.b64encode(path.read_bytes()).decode()}"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def headless_shell() -> str:
    return str(max(Path.home().glob(".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
                   key=lambda p: int(p.parts[-3].rsplit("-", 1)[1])))


def free_port(lo: int = 4711, hi: int = 4799) -> int:
    for port in range(lo, hi + 1):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("no free port in 4711-4799")


# ------------------------------------------------------------------------------------------------------------------------------ sources
# One entry per source; cite("key", ...) writes the bare numbers, comma-joined, linked to the Source Index at the bottom.

SOURCES: list[tuple[str, str, str]] = [
    ("asks", "Zach's asks: PROJECT - Sim2Real, \"Feedback on how it is right now\" to \"Comparing runs?\" (lines 388-633)",
     "obsidian://advanced-uri?vault=zach_brain&filepath=PROJECT%20-%20Sim2Real.md&openmode=true"),
    ("bench", "Zach's asks: Daily Note - Nov 6 2026, \"Bench marking the different methods of identify the parmaters\"",
     "obsidian://advanced-uri?vault=zach_brain&filepath=Sources%2FDaily%20Notes%2FDaily%20Note%20-%20Nov%206%202026.md&openmode=true"),
    ("audit", "The Codex audit of v3 (GPT-6.1 Sol, read-only): reports/media/audits/2026-11-07-sim2real-v3-audit.md",
     "../audits/2026-11-07-sim2real-v3-audit.md"),
    ("prompt", "The audit's prompt: reports/media/audits/2026-11-07-sim2real-v3-prompt.md", "../audits/2026-11-07-sim2real-v3-prompt.md"),
    ("d-domain", "Decision: domain model v3 (docs/decision-domain-model-v3-2026-11-07.md)", "/home/bam/sim2real/docs/decision-domain-model-v3-2026-11-07.md"),
    ("d-deploy", "Decision: the deployments pages (docs/decision-deployments-pages-2026-11-07.md)", "/home/bam/sim2real/docs/decision-deployments-pages-2026-11-07.md"),
    ("d-run", "Decision: the run page (docs/decision-run-page-2026-11-07.md)", "/home/bam/sim2real/docs/decision-run-page-2026-11-07.md"),
    ("d-models", "Decision: models, routines and parameters, with the finding-8 addendum (docs/decision-models-routines-parameters-2026-11-07.md)",
     "/home/bam/sim2real/docs/decision-models-routines-parameters-2026-11-07.md"),
    ("d-metrics", "Decision: metrics, diagnostics, coverage and reports (docs/decision-metrics-reports-2026-11-07.md)",
     "/home/bam/sim2real/docs/decision-metrics-reports-2026-11-07.md"),
    ("d-media", "Decision: media as entity-scoped components (docs/decision-media-components-2026-11-07.md)",
     "/home/bam/sim2real/docs/decision-media-components-2026-11-07.md"),
    ("d-cal", "Decision: calibration routines and the noise ladder, with the drift-alarm addendum and update (docs/decision-calibration-routines-2026-11-07.md)",
     "/home/bam/sim2real/docs/decision-calibration-routines-2026-11-07.md"),
    ("plan-cam", "Plan: a camera video beside every rack run (docs/plan-camera-per-run-2026-11-07.md)", "/home/bam/sim2real/docs/plan-camera-per-run-2026-11-07.md"),
    ("ladder", "sysid/results/noise_ladder.json (every check at 0x, 1x, 3x, 10x and the 1x perturbations)", "/home/bam/sim2real/sysid/results/noise_ladder.json"),
    ("routines", "sysid/results/calibration_routines.json (the routines table both ways)", "/home/bam/sim2real/sysid/results/calibration_routines.json"),
    ("drift", "sysid/results/drift_backlash_wear.json (CAN 11's wear demo)", "/home/bam/sim2real/sysid/results/drift_backlash_wear.json"),
    ("pep16", "bam_ws PEP 0016: held out from another day (with the 2026-11-07 runs, re-run and CAN 13)",
     "/home/bam/bam_ws/docs/peps/0016-held-out-from-another-day.md"),
    ("pep17", "bam_ws PEP 0017: a session moves only boards in their last known frame (amended for audit finding 1)",
     "/home/bam/bam_ws/docs/peps/0017-session-moves-only-boards-in-their-last-known-frame.md"),
    ("git-s2r", "git -C /home/bam/sim2real log --since=2026-11-06T18:00 (129 commits; merges cb01503 and d54a5f9 carry the audit fixes)", ""),
    ("git-bam", "git -C /home/bam/bam_ws log main --since=2026-11-06T18:00 (merges 8c73fe3a, 37d37335, 761434a6, b8f60c85)", ""),
    ("triage", "gates_triage_14.json: the open gate cells and what each needs from Zach (/archive/.../rack_2026-10-28/analysis/)",
     "/archive/datasets/bam_rig/rack_2026-10-28/analysis/gates_triage_14.json"),
    ("frames", "The rack's frame evidence: frame_check_060135.json and the CAN 4 / CAN 12 frame-accept receipts of 11:54Z",
     "/archive/datasets/bam_rig/rack_2026-11-07/frames/frame_check_060135.json"),
    ("stable", "The Stable / Preview switcher's state: channels.json and each release's manifest.json", str(SPS_STATE / "channels.json")),
    ("build", "The site build record: ~/.cache/sim2real/site/.sim2real-build.json", str(SITE / ".sim2real-build.json")),
    ("cal-report", "The calibration routines report of 2026-11-07 (reports/calibration-routines-2026-11-07.html)", "../../calibration-routines-2026-11-07.html"),
    ("lanes", "The lanes' own screenshots: reports/media/{w2a-deployments,w2b-runpage,w2c-models,w2d-metrics-reports,media-dashboards}", ""),
]
SRC_N = {key: i + 1 for i, (key, _l, _h) in enumerate(SOURCES)}


def cite(*keys: str) -> str:
    return "<span class=c>" + ",".join(f'<a href="#s{SRC_N[k]}">{SRC_N[k]}</a>' for k in keys) + "</span>"


def stable(path: str, label: str | None = None) -> str:
    return f'<a href="{STABLE}{path}">{esc(label or path)}</a>'


def vault(rel: str, label: str) -> str:
    from urllib.parse import quote  # noqa: PLC0415
    return f'<a href="obsidian://advanced-uri?vault=zach_brain&filepath={quote(rel, safe="")}&openmode=true">{esc(label)}</a>'


# ------------------------------------------------------------------------------------------------------------------------------ data

def fmt(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "—"
    if x == 0:
        return "0"
    if abs(x) < 1e-3:
        return f"{x:.1e}"
    return f"{x:.{digits}g}"


def load_ladder() -> dict:
    """Per check: its rows at 0x 1x 3x 10x and the 1x perturbation, each the worst |error| / tolerance over the parameters it recovered,
    the ladder's verdict, and how many it claims but did not return (sysid/results/noise_ladder.json)."""
    d = json.loads((REPO / "sysid" / "results" / "noise_ladder.json").read_text())
    routines = json.loads((REPO / "sysid" / "results" / "calibration_routines.json").read_text())
    titles = {r["routine"]: r["title"].split(":")[0].split(" (")[0] for r in routines["rows"]}
    cards = json.loads((SITE / "data" / "deployment-cards.json").read_text())
    examples = {row["id"]: row["title"] for row in cards["rows"]}
    checks = []
    for c in d["checks"]:
        cells: dict = {"variants": []}
        for row in c["rows"]:
            vals = [abs(p["error_over_tolerance"]) for p in row["parameters"] if p.get("error_over_tolerance") is not None]
            missing = sum(1 for p in row["parameters"] if p.get("recovered") is None)
            cell = {"worst": max(vals) if vals else None, "pass": bool(row["pass"]), "missing": missing,
                    "raised": not vals and missing == len(row["parameters"]), "variant": row["variant"], "held_out": row.get("held_out") or {},
                    "recovered": {p["key"]: p.get("recovered") for p in row["parameters"]}}
            if row["variant"]:
                cells["variants"].append(cell)
            else:
                cells[row["level"]] = cell
        checks.append({"id": c["id"], "routine": c["routine"], "example": c["example"], "title": titles.get(c["routine"], c["routine"]),
                       "where": examples.get(c["example"], c["example"]), "owner": c["owner"], "cells": cells, "not_at": c.get("not_at") or {}})
    counts = {}
    for level in ("0x", "1x", "3x", "10x"):
        ran = [ch for ch in checks if level in ch["cells"]]
        counts[level] = (sum(1 for ch in ran if ch["cells"][level]["pass"]), len(ran))
    by_level = {}
    for r in routines["rows"]:
        for level, v in (r.get("recovery") or {}).items():
            if v.get("checks"):
                ok, n = by_level.get(level, (0, 0))
                by_level[level] = (ok + (1 if v["pass"] else 0), n + 1)
    return {"checks": checks, "variants": d["variants"], "counts": counts, "routine_counts": by_level,
            "routines": routines, "exact_fraction": d.get("exact_fraction")}


def find(ladder: dict, check_id: str) -> dict:
    return next(c for c in ladder["checks"] if c["id"] == check_id)


def variant(cells: dict, name: str) -> dict:
    return next(v for v in cells["variants"] if v["variant"] == name)


def load_facts() -> dict:
    f: dict = {}
    for repo, sha in ((REPO, SIM2REAL_MERGE), (BAM_WS, BAM_WS_MERGE)):
        git(repo, "cat-file", "-e", sha + "^{commit}")
    f["s2r_main"] = git(REPO, "rev-parse", "--short=7", "main")
    f["bam_main"] = git(BAM_WS, "rev-parse", "--short=8", "main")
    f["s2r_commits"] = len(git(REPO, "log", "--since=2026-11-06T18:00", "--oneline", SIM2REAL_MERGE).splitlines())
    f["bam_commits"] = len(git(BAM_WS, "log", "--since=2026-11-06T18:00", "--oneline", BAM_WS_MERGE).splitlines())
    ch = json.loads((SPS_STATE / "channels.json").read_text())
    rel = lambda rid: json.loads((SPS_STATE / "releases" / rid / "manifest.json").read_text())  # noqa: E731
    f["stable"] = rel(ch["stable"])
    f["previous"] = rel(ch["previous"]) if ch.get("previous") else None
    f["stable_pages"] = sorted(p.name for p in (SPS_STATE / "releases" / ch["stable"] / "site").iterdir() if p.is_dir())
    f["build"] = json.loads((SITE / ".sim2real-build.json").read_text())
    try:
        fc = json.loads((ARCHIVE / "rack_2026-11-07" / "frames" / "frame_check_060135.json").read_text())
        f["frame_check"] = {"utc": fc["utc"], "verdicts": fc["verdicts"]}
    except OSError:
        f["frame_check"] = None
    f["receipts"] = sorted(p.name for p in (ARCHIVE / "rack_2026-10-28" / "config_backups").glob("*-20261107T*Z-frame-*.json")) \
        if (ARCHIVE / "rack_2026-10-28" / "config_backups").is_dir() else []
    return f


# ------------------------------------------------------------------------------------------------------------------------------ capture

def capture(base: str, media: Path) -> dict:
    """The hero and the stills, from the served build. The hero keeps only the moments a page is ready (each segment's start and end
    are marked on the page's own clock and cut from Playwright's recording), so a slow page load never fills the clip."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    exe = headless_shell()
    shots: dict[str, Path] = {}
    raw = Path(tempfile.mkdtemp(prefix="s2r-v3-"))
    segments: list[tuple[float, float]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, record_video_dir=str(raw),
                                  record_video_size={"width": 1280, "height": 800})
        page = ctx.new_page()
        t0 = time.monotonic()
        clock = lambda: time.monotonic() - t0  # noqa: E731
        pane = "() => document.querySelector('.mpane') || document.scrollingElement"

        def ready(url: str, js: str | None = None, settle: int = 900) -> float:
            page.goto(base + url)
            page.wait_for_load_state("load")
            if js:
                page.wait_for_function(js, timeout=60000)
            page.wait_for_timeout(settle)
            return clock()

        def smooth(dy: int, wait: int = 900) -> None:
            page.evaluate(f"(() => {{ const p = ({pane})(); p.scrollBy({{top: {dy}, behavior: 'smooth'}}); }})()")
            page.wait_for_timeout(wait)

        # 1. the deployments index, filtered by kind, then the rack's card
        a = ready("/deployments/", "() => document.querySelectorAll('a.dv-open-link').length >= 8", 1200)
        page.wait_for_timeout(700)
        page.locator("label", has_text="physical").first.click()
        page.wait_for_timeout(1300)
        card = page.locator("a.dv-open-link[href$='/deployments/one-dof-test-rack/']").first
        card.hover()
        page.wait_for_timeout(300)
        card.click()
        segments.append((a, clock()))
        # 2. the rack's page: its tree, render, coverage; then a station
        page.wait_for_load_state("load")
        page.wait_for_timeout(1300)
        a = clock()
        page.wait_for_timeout(1100)
        node = page.locator(f"a[href='{STATION_PAGE}']").first
        node.hover()
        page.wait_for_timeout(300)
        node.click()
        segments.append((a, clock()))
        # 3. the station's page: its numbers over all its runs and its link in 3D
        page.wait_for_load_state("load")
        page.wait_for_function("() => [...document.querySelectorAll('.dv-scene3d')].some((e) => e.scene3d && e.scene3d.robot().state === 'ready')",
                               timeout=60000)
        page.wait_for_timeout(600)
        a = clock()
        page.wait_for_timeout(900)
        smooth(330, 1500)
        segments.append((a, clock()))
        # 4. a filmed run: the entity tree, the camera's level (its clip playing), then the station's (camera beside the twin, playing)
        a = ready(f"/{DEP}/runs/{RUN}/", "() => document.querySelectorAll('a.s2r-tree-name').length > 3", 900)
        cam = page.locator("a.s2r-tree-name", has_text="Intel RealSense").first
        cam.hover()
        page.wait_for_timeout(300)
        cam.click()
        page.wait_for_timeout(700)
        page.locator("video:visible").first.scroll_into_view_if_needed()
        page.evaluate(f"(() => {{ const p = ({pane})(); p.scrollBy(0, 120); }})()")
        page.wait_for_function("() => [...document.querySelectorAll('video')].some((v) => v.offsetParent && v.readyState >= 2)", timeout=30000)
        page.locator("button.dv-pb-play:visible").first.click()
        page.wait_for_timeout(2600)
        st = page.locator("a.s2r-tree-name", has_text="CAN 14").first
        st.hover()
        page.wait_for_timeout(250)
        st.click()
        page.wait_for_timeout(700)
        page.locator("[role=tabpanel][data-tab=playback] video[data-t0]").first.wait_for(timeout=30000)
        page.evaluate(f"""(() => {{ const bar = [...document.querySelectorAll('.dv-pb-time')].find((e) => e.offsetParent);
            const p = ({pane})(); if (bar) p.scrollBy({{top: bar.getBoundingClientRect().top - 130, behavior: 'smooth'}}); }})()""")
        page.wait_for_function("() => [...document.querySelectorAll('[role=tabpanel][data-tab=playback] video[data-t0]')].every((v) => v.readyState >= 2)",
                               timeout=30000)
        page.wait_for_timeout(500)
        page.locator("button.dv-pb-play:visible").first.click()
        page.wait_for_timeout(4200)
        segments.append((a, clock()))
        # 5. the servo's models, by family
        a = ready("/models/integrated_servo/", None, 700)
        page.wait_for_timeout(700)
        smooth(360, 1300)
        segments.append((a, clock()))
        # 6. the routines, all four noise levels
        a = ready("/routines/", "() => document.querySelectorAll('data-views tbody tr').length > 10", 900)
        page.wait_for_timeout(1500)
        segments.append((a, clock()))
        # 7. the parameters, Errors only
        a = ready("/parameters/", "() => document.querySelectorAll('data-views tbody tr').length > 10", 700)
        page.locator("button.dv-vtab", has_text="Errors only").first.click()
        page.wait_for_timeout(2000)
        segments.append((a, clock()))
        # 8. metrics over a selection: tick rows across stations, the numbers follow
        a = ready(f"/metrics/{DEP}/", "() => window.s2rMetrics && window.s2rMetrics.ready && document.querySelectorAll('#metrics-runs tbody tr').length > 0", 900)
        listed = page.evaluate("() => [...document.querySelectorAll('#metrics-runs tbody tr')].map((tr, i) => [i, tr.textContent])") or []
        picks, seen = [], set()
        for i, text in listed:
            dev = next((d for d in ("CAN 21", "CAN 11", "CAN 12") if d in text), None)
            if dev and dev not in seen:
                picks.append(i)
                seen.add(dev)
        for i in picks[:3]:
            page.locator("#metrics-runs tbody tr").nth(i).locator(".dv-selbox").first.click()
            page.wait_for_timeout(900)
        page.wait_for_timeout(1300)
        segments.append((a, clock()))
        # 9. the reports
        a = ready("/reports/", None, 500)
        page.wait_for_timeout(1700)
        segments.append((a, clock()))
        video = Path(page.video.path())
        ctx.close()

        # ---------------------------------------------------------------- stills, 1280 x 860
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        page = ctx.new_page()

        def still(name: str, locator=None, full: bool = False) -> None:
            path = raw / f"{name}.png"
            (locator.screenshot(path=str(path)) if locator is not None else page.screenshot(path=str(path), full_page=full))
            shots[name] = path

        def go(url: str, js: str | None = None, settle: int = 1200) -> None:
            page.goto(base + url)
            page.wait_for_load_state("load")
            if js:
                page.wait_for_function(js, timeout=60000)
            page.wait_for_timeout(settle)

        go("/deployments/", "() => document.querySelectorAll('a.dv-open-link').length >= 8", 2500)
        still("deployments")
        go("/deployments/one-dof-test-rack/", None, 2000)
        still("rack")
        go(STATION_PAGE, "() => [...document.querySelectorAll('.dv-scene3d')].some((e) => e.scene3d && e.scene3d.robot().state === 'ready')", 1500)
        page.evaluate(f"(() => {{ const p = ({pane})(); p.scrollBy(0, 300); }})()")
        page.wait_for_timeout(1500)
        still("station")
        go(f"/{DEP}/runs/{RUN}/?entity=one-dof-test-rack%2Fcamera-218622274411", "() => document.querySelectorAll('a.s2r-tree-name').length > 3", 1500)
        page.locator("video:visible").first.scroll_into_view_if_needed()
        page.evaluate(f"(() => {{ const p = ({pane})(); p.scrollBy(0, 200); }})()")
        page.wait_for_function("() => [...document.querySelectorAll('video')].some((v) => v.offsetParent && v.readyState >= 2)", timeout=30000)
        page.evaluate("() => { for (const d of document.querySelectorAll('data-dashboard')) if (d.offsetParent && d.clock) { d.clock.pause(); d.clock.seek(9.5); } }")
        page.wait_for_timeout(1500)
        still("run-camera")
        go(f"/{DEP}/runs/{RUN}/", "() => document.querySelectorAll('a.s2r-tree-name').length > 3", 1200)
        still("run-top")
        page.locator("[role=tabpanel][data-tab=playback] video[data-t0]").first.wait_for(timeout=30000)
        page.evaluate(f"""(() => {{ const bar = [...document.querySelectorAll('.dv-pb-time')].find((e) => e.offsetParent);
            const p = ({pane})(); if (bar) p.scrollBy(0, bar.getBoundingClientRect().top - 120); }})()""")
        page.wait_for_function("() => [...document.querySelectorAll('[role=tabpanel][data-tab=playback] video[data-t0]')].every((v) => v.readyState >= 2)", timeout=30000)
        page.evaluate("() => { const d = document.querySelector('[role=tabpanel][data-tab=playback] data-dashboard'); if (d && d.clock) { d.clock.pause(); d.clock.seek(d.clock.start + 0.55 * (d.clock.end - d.clock.start)); } }")
        page.wait_for_timeout(1800)
        still("run-playback")
        go("/models/integrated_servo/", None, 1200)
        still("models")
        go("/routines/", "() => document.querySelectorAll('data-views tbody tr').length > 10", 1500)
        still("routines")
        go("/parameters/", "() => document.querySelectorAll('data-views tbody tr').length > 10", 1000)
        page.locator("button.dv-vtab", has_text="Errors only").first.click()
        page.wait_for_timeout(2200)
        still("parameters")
        go(f"/metrics/{DEP}/", "() => window.s2rMetrics && window.s2rMetrics.ready && document.querySelectorAll('#metrics-runs tbody tr').length > 0", 1200)
        listed = page.evaluate("() => [...document.querySelectorAll('#metrics-runs tbody tr')].map((tr, i) => [i, tr.textContent])") or []
        picks, seen = [], set()
        for i, text in listed:
            dev = next((d for d in ("CAN 21", "CAN 11", "CAN 12") if d in text), None)
            if dev and dev not in seen:
                picks.append(i)
                seen.add(dev)
        for i in picks[:3]:
            page.locator("#metrics-runs tbody tr").nth(i).locator(".dv-selbox").first.click()
            page.wait_for_timeout(500)
        page.wait_for_timeout(1500)
        still("metrics")
        go("/reports/", None, 1000)
        still("reports")
        go("/reports/otherday-sessions-1107/", None, 1500)
        still("report-page")
        go("/sysid/pendulum_can11/", "() => !!document.querySelector('svg[data-chart=wear]')", 1200)
        wear = page.locator("figure:has(svg[data-chart=wear])").first
        wear.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        still("wear", wear)
        ctx.close()
        browser.close()

    media.mkdir(parents=True, exist_ok=True)
    # WHY WebP at <= 1000 px, quality 68: the page carries a video, so it must stay under the desktop preview's ~1.9 MB media-page limit
    for name, path in list(shots.items()):
        webp = media / f"{name}.webp"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-vf", "scale='min(1000,iw)':-1", "-c:v", "libwebp",
                        "-quality", "68", "-compression_level", "6", str(webp)], check=True)
        shots[name] = webp
    # WHY keep the raw recording (gitignored, beside the page): --recut re-encodes the hero without driving the browser again
    shutil.copyfile(video, media / "hero-raw.webm")
    (media / "segments.json").write_text(json.dumps({"segments": segments}, indent=1))
    hero_cut(media / "hero-raw.webm", segments, media)
    shutil.rmtree(raw, ignore_errors=True)
    return shots


def hero_cut(video: Path, segments: list[tuple[float, float]], media: Path, target_s: float = 17.0) -> None:
    """Keep each page's ready moments, played at one speed so the whole lands near target_s (never slower than real time)."""
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True, check=True).stdout.strip() or 0)
    segs = [(max(0.0, a + 0.1), min(dur, b + 0.15)) for a, b in segments if b > a]
    kept = sum(b - a for a, b in segs)
    speed = max(1.0, kept / target_s)
    sel = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in segs)
    chain = f"fps=25,select='{sel}',setpts=N/({25 * speed:.3f})/TB,fps=12"
    # WHY 880 px, CRF 34, 12 fps: the hero is a third of the page's ~1.9 MB budget; text at 880 px still reads
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", f"{chain},scale=880:-2", "-c:v", "libx264", "-crf", "34",
                    "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(media / "hero.mp4")], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                    f"fps=25,select='{sel}',setpts=N/({25 * speed:.3f})/TB,fps=0.8,scale=320:-1:flags=lanczos,"
                    "split[a][b];[a]palettegen=max_colors=24[p];[b][p]paletteuse=dither=none", str(media / "hero.gif")], check=True)
    (media / "hero.json").write_text(json.dumps({"kept_s": round(kept, 2), "speed": round(speed, 3), "seconds": round(kept / speed, 2)}))


# ------------------------------------------------------------------------------------------------------------------------------ page

CSS = """
:root{--bg:#fbfbfa;--card:#ffffff;--fg:#1f2328;--mute:#5d646d;--line:#e3e5e8;--soft:#f2f3f4;--accent:#2f6fde;--sim:#d9692b;
--ok:#1d7f46;--ok-bg:#e3f4ea;--bad:#b42318;--bad-bg:#fde8e6;--warn:#8a5a00;--warn-bg:#fdf1d6;--na:#8a9099;--code:#f0f1f3;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171a;--card:#1c1f23;--fg:#e6e8eb;--mute:#9aa3ad;--line:#2d3238;
--soft:#22262b;--accent:#6ea0ff;--sim:#f08d55;--ok:#5fd08f;--ok-bg:#163525;--bad:#ff8a7e;--bad-bg:#3d1b18;--warn:#f0c060;--warn-bg:#3a2e12;
--na:#7c848e;--code:#262a30;color-scheme:dark}}
:root[data-theme=dark]{--bg:#15171a;--card:#1c1f23;--fg:#e6e8eb;--mute:#9aa3ad;--line:#2d3238;--soft:#22262b;--accent:#6ea0ff;--sim:#f08d55;
--ok:#5fd08f;--ok-bg:#163525;--bad:#ff8a7e;--bad-bg:#3d1b18;--warn:#f0c060;--warn-bg:#3a2e12;--na:#7c848e;--code:#262a30;color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Noto Sans",sans-serif}
main{max-width:1120px;margin:0 auto;padding:28px 16px 80px;overflow-wrap:break-word}
h1{font-size:26px;line-height:1.25;margin:0 0 6px}
h2{font-size:20px;margin:44px 0 10px;padding-top:6px;border-top:1px solid var(--line)}
h3{font-size:16px;margin:24px 0 8px}
p{margin:8px 0}
a{color:var(--accent);overflow-wrap:anywhere}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);padding:1px 4px;border-radius:4px;overflow-wrap:anywhere}
.mute{color:var(--mute)}
.meta{color:var(--mute);font-size:13px}
.c{font-size:.72em;vertical-align:super;line-height:0;margin-left:1px;white-space:nowrap}
.c a{color:var(--mute);text-decoration:none}
.c a:hover{color:var(--accent);text-decoration:underline}
.verdict{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--ok);border-radius:8px;padding:14px 18px;margin:18px 0}
.verdict p{margin:6px 0}
.verdict .big{font-size:17px;font-weight:650}
ul{padding-left:20px;margin:8px 0}
li{margin:3px 0}
nav.toc{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;margin:10px 0 0}
nav.toc a{color:var(--mute)}
.tbl{width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--card);margin:10px 0}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-weight:600;background:var(--soft);font-size:12.5px;color:var(--mute)}
tr:last-child td{border-bottom:0}
.pill{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:1px 9px;white-space:nowrap}
.done{background:var(--ok-bg);color:var(--ok)}
.part{background:var(--warn-bg);color:var(--warn)}
.fail{background:var(--bad-bg);color:var(--bad)}
.hero{margin:18px 0 6px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px}
.hero video,.hero img{display:block;width:100%;height:auto;border-radius:6px;background:#000}
.cap{font-size:13px;color:var(--mute);margin:6px 2px 0}
.page{margin:12px 0 4px}
.page figure{margin:0}
.page ul{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;list-style:none;padding:0;margin:10px 0 0}
.page li{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:9px 12px;margin:0;font-size:14px}
.page img,.wide img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:8px;background:var(--card)}
.wide{margin:12px 0}
.page figure.fit img{width:auto;max-width:100%}
figcaption{font-size:12.5px;color:var(--mute);margin-top:4px}
.ladder td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ladder td.lab{min-width:220px}
.cell-ok{background:var(--ok-bg);color:var(--ok)}
.cell-bad{background:var(--bad-bg);color:var(--bad);font-weight:600}
.cell-na{color:var(--na)}
.ladder td.vs{padding:4px 6px;min-width:170px}
.ladder .v{border-radius:4px;padding:2px 6px;margin:2px 0;white-space:nowrap}
.ladder .v span{font-weight:400;opacity:.85;font-size:12px}
.legend{font-size:12.5px;color:var(--mute)}
.need{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:10px 0}
.need h3{margin:0 0 4px}
.sources ol{font-size:13px;padding-left:24px}
.sources li{margin:4px 0;overflow-wrap:anywhere}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi b{display:block;font-size:20px}
.kpi span{font-size:12.5px;color:var(--mute)}
@media (max-width:720px){
 table.stack thead{display:none}
 table.stack,table.stack tbody,table.stack tr,table.stack td{display:block;width:100%}
 table.stack tr{border-bottom:1px solid var(--line);padding:8px 0}
 table.stack td{border:0;padding:3px 12px}
 table.stack td::before{content:attr(data-h);display:block;font-size:11.5px;font-weight:600;color:var(--mute);text-transform:uppercase;letter-spacing:.02em}
 h1{font-size:22px}
}
"""


def stack_table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f'<td data-h="{esc(h)}">{c}</td>' for h, c in zip(headers, r)) + "</tr>" for r in rows)
    return f'<div class="tbl"><table class="stack {cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def pill(kind: str) -> str:
    return {"done": '<span class="pill done">Done</span>', "part": '<span class="pill part">Partial</span>',
            "fail": '<span class="pill fail">Missing</span>'}[kind]


def ladder_table(L: dict) -> str:
    var_word = {"camera_late": "camera 10 ms late", "encoder_quantised": "encoder at its quantum", "torque_late": "torque 2 ms late",
                "tracker_late": "tracker 10 ms late", "pixel_integer": "whole-pixel detections", "encoder_14bit_9to1": "14-bit encoder, 9:1"}
    rows = []
    for ch in L["checks"]:
        tds = [f'<td class="lab"><b>{esc(ch["title"])}</b><br><span class="mute">{esc(ch["where"])}</span></td>']
        word = lambda cell: "raised" if cell["raised"] else fmt(cell["worst"]) + "×" + (  # noqa: E731
            f' <span title="parameters claimed but not returned">+{cell["missing"]} missing</span>' if cell["missing"] else "")
        for level in ("0x", "1x", "3x", "10x"):
            cell = ch["cells"].get(level)
            if cell is None:
                why = ch["not_at"].get(level, "")
                tds.append(f'<td class="n cell-na" title="{esc(why)}">not run</td>')
                continue
            tds.append(f'<td class="n {"cell-ok" if cell["pass"] else "cell-bad"}">{word(cell)}</td>')
        vs = "".join(f'<div class="v {"cell-ok" if v["pass"] else "cell-bad"}">{word(v)} <span>{esc(var_word.get(v["variant"], v["variant"]))}</span></div>'
                     for v in ch["cells"]["variants"])
        tds.append(f'<td class="n vs">{vs or "<span class=cell-na>none</span>"}</td>')
        rows.append("<tr>" + "".join(tds) + "</tr>")
    head = "<tr><th>Routine · where it is graded</th><th>0×</th><th>1×</th><th>3×</th><th>10×</th><th>1× + one realistic fault each</th></tr>"
    return f'<div class="tbl"><table class="ladder"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def render(shots: dict[str, Path], facts: dict, L: dict) -> str:
    st, prev, build = facts["stable"], facts["previous"], facts["build"]
    hero = json.loads((MEDIA / "hero.json").read_text()) if (MEDIA / "hero.json").is_file() else {}
    img = lambda name, alt: f'<img src="{data_uri(shots[name])}" alt="{esc(alt)}" loading="lazy">'  # noqa: E731
    c_ = L["counts"]
    rc = L["routine_counts"]
    R = L["routines"]["rows"]
    n_routines = len(R)
    n_impl = sum(1 for r in R if r["status"] == "implemented")
    n_checked = sum(1 for r in R if r["oracle"]["status"] == "checked")
    stock = find(L, "pendulum_can11:servo.stock_quasistatic")["cells"]
    t10 = find(L, "pendulum_can11:servo.live_reid_t10")["cells"]
    reg = find(L, "pendulum_can11:servo.dynamics_regression")["cells"]
    rev = find(L, "pendulum_can11:servo.backlash_reversals_camera")["cells"]
    urb = find(L, "ur5e_backlash:arm.backlash_gravity_sweep")["cells"]
    conv = find(L, "conveyor:conveyor.radius_tracker")["cells"]
    urdyn = find(L, "ur5e:arm.dynamics_excitation")["cells"]
    ur2dyn = find(L, "ur5e_2f85:arm.dynamics_excitation")["cells"]
    geom = find(L, "linescan_cell:linescan.geometry_dot_card")["cells"]
    bundle = find(L, "dual_arm_cell:cell.tags_bundle_adjustment")["cells"]
    rgbd = find(L, "linescan_cell:rgbd.dot_card")["cells"]
    gap = find(L, "pendulum_can11:servo.gap_check_forecast")["cells"]
    gh = {lv: gap[lv]["held_out"] for lv in ("1x", "3x", "10x") if lv in gap}
    fc = facts["frame_check"]
    # CAN 13's two candidate frames and its proven window's low edge, its low stop (PEP 0016, "CAN 13, not moved")
    c13_low, c13_one, c13_two = 0.2, 0.410, 1.038
    deg = lambda q: (q - c13_low) * 180 / 3.141592653589793  # noqa: E731
    s = []
    w = s.append

    # ---------------------------------------------------------------- header and verdict
    w(f"""<header><h1>Sim2Real v3: what landed overnight</h1>
<div class="meta">2026-11-06 18:00 to 2026-11-07 05:02 MST · {facts['s2r_commits']} sim2real commits, {facts['bam_commits']} bam_ws commits{cite('git-s2r', 'git-bam')}
· media recorded fresh from the build of sim2real main served read-only · written by the scribe (Claude Opus 5.5)</div>
<nav class="toc"><a href="#asks">The nine asks</a><a href="#hero">Hero</a><a href="#pages">Page by page</a><a href="#ladder">Routines and the noise ladder</a>
<a href="#rack">The rack overnight</a><a href="#audit">Audit</a><a href="#decided">Decided for you</a><a href="#needs">Needs you</a><a href="#left">Left</a><a href="#src">Sources</a></nav></header>""")
    w(f"""<section class="verdict">
<p class="big">All nine asks are built and working in sim2real, and every one of the audit's nine findings has a fix on main;
three asks stay partial until more data or hardware exists.</p>
<p>The v3 work is on sim2real <code>main</code> @ <code>{SIM2REAL_MERGE}</code> and the rack fixes on bam_ws <code>main</code> @ <code>{BAM_WS_MERGE}</code>.
Stable was promoted to <code>{st['commit'][:7]}</code> at {st['builtAt'][11:16]} MST{cite('stable')}, so the dock icon opens v3 (models, parameters,
metrics and reports were missing from the old Stable{cite('audit')}). Undo: right-click sim2real → <b>Roll Stable Back</b>, which returns to
<code>{prev['commit'][:7] if prev else '?'}</code>.</p>
<ul>
<li><b>Partial, for want of data:</b> virtual deployments have no runs; only {build['tree'][DEP]['config']['full']:,} of {build['runs']:,} rack runs carry a full
config snapshot; per-run metrics exist for the servo's stop error and the board's saturation and rate, not yet for the motor, gearbox or encoder;
{build['media']['clips']} of {build['runs']:,} runs have camera video{cite('build', 'audit', 'd-metrics')}.</li>
<li><b>The rack:</b> every board on adapter 0607623A had re-latched by whole rotor turns without a reset. CAN 11 and 21 were put back (RAM only) and
their other-day sessions recorded; CAN 4 and 12 were accepted as in frame; <b>CAN 13 waits on you</b> (one look at the link){cite('pep16', 'pep17', 'frames')}.</li>
</ul></section>""")

    # ---------------------------------------------------------------- the nine asks
    w(f'<h2 id="asks">The nine asks</h2><p class="mute">Your words from the project note and the Nov 6 daily note{cite("asks", "bench")}; '
      f'the audit\'s verdicts{cite("audit")}; what the audit-fix lane changed{cite("git-s2r")}. Links open in Stable, '
      f'<code>{STABLE}</code>, once the sim2real app is running.</p>')
    asks = [
        ["1. “install sim to real and a desktop app with stable preview switch so I can easily launch it myself”",
         f"The <b>sim2real</b> dock app: Stable on :4820, Preview on :4821; right-click for Open Preview, Make Preview Stable, Roll Stable Back{cite('stable')}.",
         f"{pill('done')} Audit said partial: Stable still held the Nov 6 build{cite('audit')}. Fixed: Stable is now <code>{st['commit'][:7]}</code>, with "
         f"{', '.join(p for p in facts['stable_pages'] if p in ('models', 'parameters', 'metrics', 'reports', 'routines', 'deployments'))} in it.",
         "Nothing open."],
        ["2. “I like organizing this around Deployments … virtual or like actuall physical … the first level of filtering … type of dpeloyment”",
         f"{stable('/deployments/')}: kind and tags on the left, a card with its render per deployment; a page for every node of every tree "
         f"({build['domain']['deployments']} deployments, {build['domain']['nodes']} nodes){cite('d-deploy', 'build')}.",
         f"{pill('done')} Audit: achieved{cite('audit')}.",
         f"A physical deployment has two pages, its v3 page and its old record page (gates, why it fails), linked both ways{cite('d-deploy')}."],
        ["3. “all runs should be tagged with the current configuration values … natural response or driven … On the left should be like an entity tree”",
         f"Every run tagged driven / free response / mixed, closed loop, offline scope and its config hash; the run page is the entity tree on the left and the "
         f"picked level's dashboard on the right ({stable(f'/{DEP}/runs/{RUN}/', 'a filmed CAN 14 run')}){cite('d-run', 'd-domain')}.",
         f"{pill('part')} Audit: partial, and it still holds{cite('audit')}.",
         f"Virtual deployments have no runs. {build['tree'][DEP]['config']['full']:,} of {build['runs']:,} runs carry a full config snapshot "
         f"(older runs never recorded one). Most level dots are hollow rings: only the board and the stop error have per-run values{cite('build', 'd-run', 'd-metrics')}."],
        ["4. “organize all of the models related to a particular part type into a ladder … the type here is more generic … MO.kinematics.X MO.dynamics.X”",
         f"{stable('/models/')}: eleven generic types (rigid body chain, integrated servo, BLDC motor, gearbox, FOC controller, …), each a ladder per family "
         f"<code>M&lt;k&gt;.kinematics</code> / <code>.dynamics</code> / <code>.measurement</code>, with where each model is used{cite('d-domain', 'd-models')}.",
         f"{pill('done')} Audit: achieved{cite('audit')}.",
         f"Authoring still happens on the v2 type cards and v3 is derived by an explicit map. Every rack twin label maps to the servo's "
         f"<code>M4.dynamics.twin</code>{cite('d-domain', 'd-models')}."],
        ["5. “a table of calibration routines … and then the parameters that they identify. Another way … parameters in the first column and all the ROUTINES” · “check these vs an orcale in simulation”",
         f"{stable('/routines/')}: {n_routines} routines both ways with where they run, time, equipment cost, and recovery at 0×, 1×, 3× and 10× noise; "
         f"the UR backlash scenario is now a deployment, and its joint gaps are parameter rows{cite('routines', 'd-cal')}.",
         f"{pill('done')} Audit said partial: the table showed only 1× and 3×, and the backlash scenario was missing from Parameters (finding 5). "
         f"Both fixed{cite('audit', 'git-s2r')}.",
         f"{n_checked} of {n_routines} routines are graded against a hidden truth; {n_routines - n_impl} are not implemented or only partly. "
         f"Code the oracle cannot import (the clamp test, DH, the homing seek) is cited, not graded{cite('routines', 'd-cal')}."],
        ["6. “in the parameter view. lets use DATA-UI … the Winning model(s) … each model … its own Recovered error toerlance colum”",
         f"{stable('/parameters/')}: {build['domain']['parameter_rows']:,} rows in data-ui, presets All / Winning model / With results / Errors only, one "
         f"recovered · error · tolerance · ✓ group per model ({build['domain']['result_columns']} groups), best per row marked{cite('d-models', 'build')}.",
         f"{pill('done')} Audit said partial: an unmeasured part lost rows (finding 4); All and Winning showed only the fit (finding 8). Both fixed{cite('audit', 'git-s2r')}.",
         f"All parameters is wide at 1280 px until a rail pick narrows it. sim2real still vendors an older data-ui kit with §49 backported, not data-ui main{cite('d-models')}."],
        ["7. “Each entity type has Metrics … DIAGONISTICS … metrics + gate that reports warning or error … we want to make sure that the runs have good coverage”",
         f"{stable(f'/metrics/{DEP}/')}: tick runs or filter them, and every station's pinned metrics, diagnostics with levels and coverage recompute in the "
         f"browser, held to Python's numbers{cite('d-metrics')}.",
         f"{pill('part')} Audit: partial, and it still holds{cite('audit')}.",
         f"Only five metrics have per-run sources, and recorded coverage exists for the servo type only. The motor, gearbox and encoder need "
         f"instruments the rack does not have yet: commanded current, an output encoder, a load cell, a dyno{cite('audit', 'd-metrics')}."],
        ["8. “Reports … that is how we kinda like ‘freeze it’ … even as you add more data”",
         f"{stable('/reports/')}: {build['domain']['reports']} frozen reports, each with a digest that verifies; any metrics selection writes its freeze command{cite('d-metrics', 'build')}.",
         f"{pill('done')} Audit said partial: a frozen page read today's titles (finding 7), and a typo'd run id froze an empty report (finding 9). Both fixed{cite('audit', 'git-s2r')}.",
         f"The three reports frozen before the fix still read their parts' titles from today, and their pages say so; they were labelled, not re-frozen{cite('d-metrics')}."],
        ["9. “I would like the runs to be a bit more media rich … video data saved so I could quickly see it”",
         f"A MuJoCo render on every deployment card, the link in 3D on every run, the camera clip beside the twin's render on filmed runs{cite('d-media')}.",
         f"{pill('part')} Audit: achieved where footage exists{cite('audit')}.",
         f"{build['media']['clips']} of {build['runs']:,} runs have a clip: sessions only filmed on 10-23 to 10-25. The new camera-per-run recorder is on bam_ws "
         f"main but has not run on a session yet{cite('build', 'plan-cam', 'git-bam')}."],
    ]
    w(stack_table(["The ask, in your words", "What exists now", "Verdict after the audit fixes", "What is still partial"], asks, "asks"))

    # ---------------------------------------------------------------- hero
    gif = data_uri(MEDIA / "hero.gif") if (MEDIA / "hero.gif").is_file() else ""
    w(f"""<h2 id="hero">The click-through</h2>
<div class="hero"><video autoplay muted loop playsinline controls preload="auto" aria-label="sim2real v3 click-through">
<source src="{data_uri(MEDIA / 'hero.mp4')}" type="video/mp4"><img src="{gif}" alt="sim2real v3 click-through (GIF fallback)"></video>
<p class="cap">{hero.get('seconds', '?')} s, played at {float(hero.get('speed', 0)):.1f}× and cut to the moments each page is ready. Deployments filtered to physical → the rack →
CAN 14 → a filmed run: the camera's node (its clip plays), then the station (camera beside the twin's render, playing) → the servo's models → routines →
parameters, Errors only → metrics, ticking a run from CAN 21, 11 and 12 → reports. Recorded headless from the main build.</p></div>""")

    # ---------------------------------------------------------------- page by page
    w('<h2 id="pages">Page by page</h2><p class="mute">Each still is the current build at 1280 px. Three bullets on how to read it.</p>')
    pages = [
        ("deployments", "Deployments", stable("/deployments/"), [
            "Left rail: <b>Kind</b> (virtual = only in simulation, physical = hardware whose runs are recordings), then <b>Tags</b> (oracle example, uses camera, noise-ladder scenario, …). Tick to filter.",
            f"One card per deployment with its MuJoCo render: {build['domain']['deployments']} today, 1 physical (the rack) and the sysid examples plus the UR backlash scenario{cite('d-deploy', 'build')}.",
            "The Table tab is the same rows; click a card for its page."]),
        ("rack", "A deployment's page: the rack", stable("/deployments/one-dof-test-rack/"), [
            "Left: its whole tree (adapter → station → motor, driver, gearbox, encoder; the cameras). Every node is a deployment with its own page.",
            "Right: one calm answer first (runs, how many stations meet their twin gate), the render, then sub-deployments, coverage per joint against its 40 % gate, pinned metrics, models per type and the runs.",
            f"Every number is <code>selection.compute</code> over exactly the runs under that node{cite('d-deploy')}."]),
        ("station", "A station: CAN 14", stable(STATION_PAGE), [
            "Its headline numbers over all its runs: tracking RMS, stop error p90, twin ÷ floor against the ≤ 1.5× gate, coverage of its reachable cells.",
            "The link in 3D on its newest replayed run: real solid blue, each model translucent orange, the command a grey ghost; scrub to move them.",
            "The tree keeps your place: the parts under CAN 14 are their own pages."]),
        ("run-top", "The run page: the entity tree", stable(f"/{DEP}/runs/{RUN}/"), [
            "Left: the run's tree (the rack, its adapter, the station and its parts, and the camera that filmed it). A filled dot is a level from a per-run diagnostic; a hollow ring means no per-run value yet.",
            "Under the title, the run's tags: driven, closed loop, offline scope, and whether its config was recorded; the grey box says what offline replay can and cannot judge.",
            f"Right: the picked level's dashboard: pinned metrics, diagnostics with limits, coverage, then models apart from the numbers{cite('d-run')}."]),
        ("run-camera", "The run page: the camera's level", stable(f"/{DEP}/runs/{RUN}/?entity=one-dof-test-rack%2Fcamera-218622274411"), [
            "Pick the camera in the tree and the right side becomes its level: what it watches and its clip of this run, on its own clock.",
            "Where the camera found the station's tag, it is boxed in blue. The 10-23/24 recordings are dark, so the clips are brightened as the tag detector sees them.",
            "A link (<code>?entity=…</code>) per level, so Back returns."]),
        ("run-playback", "The run page: the station's playback", stable(f"/{DEP}/runs/{RUN}/#playback"), [
            "The camera (left) and MuJoCo's render of the twin (right) on the plots' clock: Play moves both and every plot below.",
            "Side by side, never overlaid: the render is the joint's own frame, not the camera's calibrated view, so an overlay would not register.",
            f"Under them, the link in 3D for every model at once{cite('d-media')}."]),
        ("models", "Models: the integrated servo", stable("/models/integrated_servo/"), [
            "One ladder per family; each rung holds everything below it and adds its own terms (the <b>adds</b> column).",
            "<b>Identified here</b>: every value a routine recovered, per deployment. <b>Used on</b>: where the model runs, an oracle example or a rack station.",
            f"Every rack twin label maps to <code>M4.dynamics.twin</code>, with where it departs from the rung recorded{cite('d-models')}."]),
        ("routines", "Routines", stable("/routines/"), [
            "Two tabs: routine → the parameters it identifies, and parameter → every routine that can identify it.",
            "Per routine: where it runs, wall time, hands-on time, equipment cost, then recovery at 0×, 1×, 3× and 10× noise: worst error over tolerance and a pass / fail / not run badge.",
            f"{n_checked} of {n_routines} are graded against a hidden truth; the rest say why not{cite('routines')}."]),
        ("parameters", "Parameters, Errors only", stable("/parameters/"), [
            "Errors only puts every model's error side by side and marks each row's least |error|: which routine and model got closest.",
            "All parameters and Winning model show the fit, then every model's recovered · error · tolerance · ✓ group; the rail narrows to a deployment, type or model.",
            "Units are per row (mrad for rad, mm for m), so a row's errors compare directly."]),
        ("metrics", "Metrics over a selection", stable(f"/metrics/{DEP}/"), [
            "Tick runs in the table (or filter on the left; nothing ticked means every filtered run). Each station's card on the right recomputes live.",
            "Per station: pinned tracking RMS and stop error, twin ÷ floor per model with its level, coverage against the 40 % gate, then each part's diagnostics.",
            f"The browser's numbers are held to Python's <code>selection.compute</code> by the site test for three selections{cite('d-metrics')}."]),
        ("reports", "Reports", stable("/reports/"), [
            "A report is a named, frozen set of runs with everything computed over them when frozen; its digest says it has not moved.",
            "Make one from any metrics selection: the page writes the <code>python3 -m type_cards.report freeze …</code> command.",
            "Open one to see the frozen numbers; <code>?report=&lt;id&gt;</code> on the metrics page ticks its runs, so today's numbers are one click away."]),
        ("report-page", "A report: the other-day sessions", stable("/reports/otherday-sessions-1107/"), [
            f"CAN 11, 12 and 21's held-out sessions recorded on another day than their training (the rule in PEP 0016){cite('pep16')}.",
            "Per station: its numbers as frozen, which parts' titles come from the snapshot, and which (for the three older reports) are today's.",
            f"Same-day vs other day, from the metrics decision: twin of record 1.42× → 1.35× floor on CAN 11, 3.09× → 2.78× on CAN 12, 2.53× → 2.39× on CAN 21; "
            f"coverage 13–18 % of each joint's cells against 39–42 % same-day{cite('d-metrics')}."]),
    ]
    for key, title, link, bullets in pages:
        w(f'<h3>{esc(title)} · {link}</h3><div class="page"><figure>{img(key, title)}</figure><ul>{"".join(f"<li>{b}</li>" for b in bullets)}</ul></div>')

    # ---------------------------------------------------------------- calibration routines and the noise ladder
    w(f"""<h2 id="ladder">Calibration routines and the noise ladder</h2>
<p>Each graded routine was run against the simulator's hidden true values with the sensor noise at 0×, 1×, 3× and 10× its committed level (one
draw, scaled), plus 1× with one realistic fault such as a late timestamp. A cell is the worst error ÷ tolerance among the parameters the routine
returned. The bound was declared before any run: a tenth of the tolerance at 0×, k tolerances at k×{cite('d-cal', 'ladder')}. Green is within it,
red is not. The full write-up is the <a href="../../calibration-routines-2026-11-07.html">calibration routines report</a>{cite('cal-report')}.</p>
<div class="kpis">
<div class="kpi"><b>{c_['0x'][0]} / {c_['0x'][1]}</b><span>checks within bound at 0×</span></div>
<div class="kpi"><b>{c_['1x'][0]} / {c_['1x'][1]}</b><span>at 1×</span></div>
<div class="kpi"><b>{c_['3x'][0]} / {c_['3x'][1]}</b><span>at 3×</span></div>
<div class="kpi"><b>{c_['10x'][0]} / {c_['10x'][1]}</b><span>at 10×</span></div></div>
{ladder_table(L)}
<p class="legend">From <code>sysid/results/noise_ladder.json</code>{cite('ladder')}. “raised”: the routine threw. “+N missing”: parameters it claims but did not
return, which fail the row. “not run”: the ladder skips that level, with its reason on hover.</p>
<h3>What the ladder says</h3>
<ul>
<li><b>At 0×, a model that lacks a term misses by the same amount at every level.</b> The stock quasi-static sweeps put CAN 11's damping
{fmt(stock['0x']['worst'])}× tolerance off with no noise and {fmt(stock['10x']['worst'])}× at 10×: they fit a negative viscous term because their model has
no Stribeck dip. The rack's live re-identification (T10) sits at {fmt(t10['0x']['worst'])}× at every level (a tanh Coulomb against a Stribeck truth){cite('d-cal', 'ladder')}.</li>
<li><b>A matched model can still be a biased routine.</b> The UR gravity sweep fits the truth's own gap model, yet with no noise it reads the elbow's
10 arcmin gap as {urb['0x']['recovered']['elbow.backlash_rad'] * 180 / 3.141592653589793 * 60:.1f} arcmin ({fmt(urb['0x']['worst'])}×), and it never returns
wrists 1 and 2 (no pose where gravity beats their friction); the pan and wrist 3 cannot be loaded by gravity at all. All six UR gaps need a reversal or
clamp routine{cite('d-cal')}. CAN 11's regression carries {fmt(reg['0x']['worst'])}× on gravity with no noise: it misses the 0× bar, then passes 1× and 3×.</li>
<li><b>One late timestamp costs more than ten times the noise.</b> The belt tracker 10 ms late puts the drum radius at {fmt(variant(conv, 'tracker_late')['worst'])}× tolerance,
against {fmt(conv['10x']['worst'])}× at 10× noise. The link camera 10 ms late puts CAN 11's gap at {fmt(variant(rev, 'camera_late')['worst'])}× (a fail), against
{fmt(rev['3x']['worst'])}× at 3×. Torque 2 ms late puts the UR armature at {fmt(variant(urdyn, 'torque_late')['worst'])}× (1×: {fmt(urdyn['1x']['worst'])}×). Whole-pixel
detections fail the line camera's geometry at {fmt(variant(geom, 'pixel_integer')['worst'])}×. The encoders' real quanta cost nothing measurable
(CAN 11's regression {fmt(variant(reg, 'encoder_quantised')['worst'])}× against {fmt(reg['1x']['worst'])}×){cite('ladder', 'd-cal')}.</li>
<li><b>At 10×, the camera fits and the arm dynamics break.</b> Tag bundle adjustment {fmt(bundle['10x']['worst'])}×, line-scan geometry
{fmt(geom['10x']['worst'])}×, the RGBD dot card {fmt(rgbd['10x']['worst'])}×, UR dynamics {fmt(urdyn['10x']['worst'])}× and {fmt(ur2dyn['10x']['worst'])}× (the speed noise sits in the
regressor, and least squares on a noisy regressor is biased), CAN 11's gap from reversals {fmt(rev['10x']['worst'])}×. CAN 11's regression raises outright: its fitted Stribeck
slope makes the twin unstable, so the rack's twin builder refuses it. The conveyor, gripper, UR zero offsets and radiometry hold{cite('ladder', 'd-cal')}.</li>
<li><b>How real is 1×?</b> It is each simulated world's committed noise, not a measurement. The rack's D405 reads a station tag at 2–11 mrad a frame,
so even 10× here is quieter than the rack's camera; read a routine's 3× and 10× rows before trusting it on that sensor{cite('d-cal')}.</li>
</ul>
<h3>The drift alarm at 1×, 3× and 10×</h3>
<p>CAN 11's wear demo: the hidden gear gap grows 1.8 µrad/h and a check runs every 12 h on the day's motions. The alarm now warns on either of two
checks, whichever is first: the gap's growth past the station's allowance (T5's 2 arcmin, {gh['1x']['allowance_mrad']:.3f} mrad), or the twin's fidelity
over the camera's floor{cite('d-cal', 'drift')}.</p>""")
    drift_rows = []
    for lv in ("1x", "3x", "10x"):
        h = gh.get(lv, {})
        alarm = h.get("detector_alarm_h")
        by = "fidelity ratio" if alarm is not None and alarm == h.get("ratio_alarm_h") and h.get("ratio_alarm_h") != h.get("gap_alarm_h") else ("gap check" if alarm is not None else "—")
        drift_rows.append([lv.replace("x", "×"), f"<b>{fmt(alarm, 4) + ' h' if alarm is not None else 'never inside 480 h'}</b>", by,
                           f"{fmt(h.get('gap_alarm_h'), 4) + ' h' if h.get('gap_alarm_h') is not None else 'never'}",
                           f"{fmt(h.get('ratio_alarm_h'), 4) + ' h' if h.get('ratio_alarm_h') is not None else 'never'}",
                           f"{fmt(h.get('actual_crossing_h'), 4) + ' h' if h.get('actual_crossing_h') is not None else 'never'}",
                           f"{h.get('commissioned_gap_mrad', 0):.3f} mrad"])
    w(stack_table(["Noise", "Alarm", "Fired by", "Gap check alone", "Ratio alone", "Hidden gap crossed", "Commissioned gap (true 2.000)"], drift_rows))
    w(f"""<div class="page"><figure class="fit">{img('wear', 'The wear chart on the pendulum oracle page')}<figcaption>The wear chart on
{stable('/sysid/pendulum_can11/', '/sysid/pendulum_can11/')}: each check's gap growth against the allowance line, the ratio as the second series, each dot carrying the alarm status.</figcaption></figure>
<ul><li><b>1×:</b> the ratio warns first at {fmt(gh['1x']['detector_alarm_h'], 4)} h, {fmt(gh['1x']['actual_crossing_h'] - gh['1x']['detector_alarm_h'], 3)} h before the hidden gap
crosses; the gap check alone would wait to {fmt(gh['1x']['gap_alarm_h'], 4)} h{cite('ladder')}.</li>
<li><b>3×:</b> the ratio goes deaf (its denominator is the camera's floor, which grows with the noise); the gap check fires at {fmt(gh['3x']['gap_alarm_h'], 4)} h,
within a check of the crossing at {fmt(gh['3x']['actual_crossing_h'], 4)} h{cite('ladder', 'd-cal')}.</li>
<li><b>10×:</b> never inside 480 h. Not the check's fault: the reversals routine commissions a {gh['10x']['commissioned_gap_mrad']:.2f} mrad gap on a 2.0 mrad
truth, so everything counted from it is off{cite('ladder', 'd-cal')}.</li>
<li>The 1× → 3× gap between alarms is 60 h, not the 33 h estimated: commissioning reads the same gap 0.117 mrad apart at the two noise levels{cite('d-cal')}.</li></ul></div>""")

    # ---------------------------------------------------------------- the rack overnight
    fc_line = ""
    if fc:
        inframe = [k for k, v in fc["verdicts"].items() if not v["refused"]]
        refused = [f"CAN {k} ({v['turns']:+d} turn)" for k, v in fc["verdicts"].items() if v["refused"]]
        res = [abs(v["residual_rad"]) * 1000 for v in fc["verdicts"].values() if not v["refused"]]
        fc_line = (f"{fc['utc'][11:16]}Z read-only frame check of all five boards on 0607623A: CAN {', '.join(inframe)} in frame "
                   f"({min(res):.3f}–{max(res):.3f} mrad); refused: {', '.join(refused)}{cite('frames', 'pep17')}")
    accepted = [r.split("-")[0].upper().replace("CAN", "CAN ") for r in facts["receipts"] if "frame-accept" in r]
    timeline = [
        ["01:36–01:42Z", f"The other-day sessions (PEP 0016). CAN 12 recorded. CAN 11 and CAN 21 refused at preflight before anything moved: each read one rotor turn off where 11-06 left it{cite('pep16')}."],
        ["03:07–03:12Z", f"Read-only probes: every board on 0607623A up 25.2 days, home state 1. Their position tracking had re-latched by whole turns <b>without a power cycle</b>; CAN 13 too. Cause not found (the host rebooted at 18:54Z){cite('pep16')}."],
        ["03:25Z, 03:27Z", f"CAN 11 moved back −1 turn and CAN 21 +1 turn, RAM only (moteus set-output-nearest keeps the encoder's fraction; nothing flashed), each after the turn was proven by the rotor encoder and the proven window, read back within 1 mrad{cite('pep16')}."],
        ["03:28–03:34Z", f"Their declared other-day sessions recorded again, byte-identical plans, 14 of 14 runs each{cite('pep16')}."],
        ["05:59Z", f"CAN 13 probe: one rotor turn off, but its window holds both +1 and +2 and it has no gravity load to choose. Nothing written{cite('pep16')}."],
        ["06:01Z", fc_line or "Frame check of all five boards (see PEP 0017)."],
        ["after the audit", f"PEP 0017 amended (audit finding 1): every motion entry point checks the frame, and only a checked run or a receipt counts as a last known frame. Merged as <code>{BAM_WS_MERGE}</code>{cite('pep17', 'git-bam')}."],
        ["11:54Z", f"{' and '.join(accepted) if accepted else 'CAN 4 and CAN 12'} accepted as in frame (receipts only; nothing written to the boards): both read within 0.04 mrad of their newest runs and did not move across the re-latch{cite('frames', 'pep17')}."],
    ]
    w(f'<h2 id="rack">The rack overnight</h2><p class="mute">Times are UTC. MST is UTC−7.</p>')
    w(stack_table(["When", "What happened"], timeline))
    w(f"""<h3>The other-day rule and its outcome</h3>
<p>A refit or learned head is adopted only if it wins on held-out sessions recorded on a <b>different UTC day</b> from every training session. Learner v2's
four adoptions were all same-day, so all four were refused until judged on another day{cite('pep16')}.</p>""")
    w(stack_table(["Head", "Same-day held-out (11-06)", "Other-day held-out (11-07)", "Verdict"], [
        ["CAN 12 q (torque)", "2.270 → 1.790 mrad", "2.179 → 1.876 mrad, every family better", '<span class="pill done">adopted</span>'],
        ["CAN 12 tau (torque)", "0.2277 → 0.2008 N·m", "0.2227 → 0.2083 N·m; pick-and-place +5.3 %", '<span class="pill fail">refused</span>'],
        ["CAN 11 q (torque)", "3.323 → 3.234 mrad", "3.708 → 3.713 mrad; dither +10.2 %, pick-and-place +8.8 %", '<span class="pill fail">refused</span>'],
        ["CAN 21 tau (torque)", "0.0271 → 0.0226 N·m", "0.0257 → 0.0238 N·m; cycle +26.5 %", '<span class="pill fail">refused</span>'],
    ]))
    w(f"""<ul><li>The acceptance stays at <b>32 of 88 cells</b>. CAN 12's adopted head made its T2, T9 and T10 cells worse (2.69× → 3.07×, 1.81× → 1.99×,
1.75× → 1.99×), all still failing: its gain carried to another day's identification session but not to the acceptance tapes{cite('pep16')}.</li>
<li>The twin of record now sits beside real for the nine live identification sessions (155 runs) on the run pages{cite('git-bam')}.</li></ul>
<h3>The frame interlock</h3>
<ul><li>Before anything moves, from any entry point (a session or a single <code>sine</code> / <code>tape</code>), each board's output frame is compared with its
last <b>verified</b> frame: a run whose own frame check passed, or a receipt. A whole number of turns refuses and names the command that undoes it; a board
that opens without a pass refuses to move{cite('pep17')}.</li>
<li>The check never fixes a frame: a re-latch and a joint turned by hand read the same, so a turn is proven first, as for CAN 11 and 21{cite('pep17')}.</li>
<li>Today: CAN 4, 11, 12 and 21 pass; CAN 13 is refused (one turn off, ambiguous); CAN 1, 14 and 15 on the unpowered 272813EF bus have only unchecked
runs and will be refused at their next motion until accepted{cite('pep17', 'frames')}.</li></ul>
<h3>A camera on every run</h3>
<ul><li><code>record --mp4-only</code> writes the H.264 as frames arrive and keeps only the stamps, so there is no 120 s RAM ceiling; schedule sessions name both
D405s with <code>camera_mode: "mp4"</code>, and each run gets its own 640×360 clip beside its data. Calibration sessions keep the raw frames{cite('git-bam', 'plan-cam')}.</li>
<li>Audit finding 2 fixed: a camera whose encoder fails stops, so no stamp names a missing frame, and every camera's files are finished whatever fails{cite('audit', 'git-bam')}.</li>
<li>Not used on a real session yet: the 272813EF bus is unpowered and the room is too dark for the tag stops (T4){cite('triage')}.</li></ul>""")

    # ---------------------------------------------------------------- audit
    w(f"""<h2 id="audit">The audit</h2>
<p>Codex (GPT-6.1 Sol, read-only) audited v3 at 03:22 MST, against your nine asks{cite('prompt', 'audit')}. <b>Its verdict: PARTIAL.</b> Three asks achieved
(deployments, generic model ladders, media where footage exists), six partial; 72 selected tests and 14 fake-board checks passed; all 20 preset selections agreed
with Python; 49 static metric values matched their sources. It could not open a browser{cite('audit')}. Every finding was fixed test first:</p>""")
    w(stack_table(["#", "Finding", "What was done", "Proof"], [
        ["1 · P1", "The single-experiment CLI moved boards without the frame check, and its run then became the last known frame, hiding a shift.",
         "Every motion kind checks the frame; a Board refuses to open without a pass; only verified runs or receipts are a last known frame (PEP 0017 amended).",
         f"bam_ws <code>2228454d</code>; 27 new tests, red first at <code>f33762c2</code>, <code>687af466</code>{cite('git-bam', 'pep17')}"],
        ["2 · P1", "On an encoder failure the recorder kept stamps for frames it never wrote (104 stamps for 2 frames), and a disk-full save could leave an mp4 unfinished.",
         "A failing mp4-only camera stops; both files carry how many frames the mp4 holds; each camera's files are finished on their own.",
         f"bam_ws <code>960b3259</code>; 6 tests, red first at <code>0fa6160b</code>{cite('git-bam')}"],
        ["3 · P1", "The dock icon still opened the Nov 6 build, without models, parameters, metrics or reports.",
         f"Stable promoted to <code>{st['commit'][:7]}</code> (release <code>{st['releaseId']}</code>).",
         f"Its release holds {len(facts['stable_pages'])} page folders including models, parameters, metrics and reports{cite('stable')}"],
        ["4 · P2", "An unmeasured servo beside measured ones lost 3 of its 22 parameter rows.",
         "Each value is bound to the part it belongs to, so a part nobody measured keeps every row.", f"<code>127dc98</code>, test first <code>b76b1b3</code>{cite('git-s2r')}"],
        ["5 · P2", "The routine table showed only 1× and 3×; the UR backlash scenario never reached Parameters.",
         "All four levels with verdicts and not-run reasons; ur5e_backlash is a virtual deployment and its gaps are parameter rows.",
         f"<code>dbac1b7</code>, <code>757354d</code>, <code>373d83a</code>; tests first <code>ed9f62e</code>, <code>c48dad1</code>{cite('git-s2r')}"],
        ["6 · P2", "The fresh-result tests compared recovered values only, so a changed interval, alarm or held-out score passed.",
         "Every field is compared, only declared volatile provenance aside; mutation-tested. The slow CAN 11 and arm checks stay opt-in.",
         f"<code>01f8f58</code>, <code>0681fd5</code>; tests first <code>da71e6d</code>, <code>f023813</code>{cite('git-s2r')}"],
        ["7 · P2", "A “frozen” report read today's part titles and model labels.",
         "New snapshots freeze their titles and label map under the digest; the three older reports are labelled as reading today's.",
         f"<code>d281bd5</code>, <code>d26b11f</code>; test first <code>c2598db</code>{cite('git-s2r', 'd-metrics')}"],
        ["8 · P2", "All and Winning presets showed only the fit, though the contract promised every model's group.",
         "Every preset shows every model's group (the decision's addendum scores both options).", f"<code>2ed2b8b</code>{cite('git-s2r', 'd-models')}"],
        ["9 · P2", "<code>--runs typo</code> froze a report of nothing, with a digest that verified.",
         "A new report refuses a run id the data does not hold, before anything is written.", f"<code>b4576b7</code>, test first <code>c92d491</code>{cite('git-s2r')}"],
    ]))
    w(f"""<p class="mute">After the fixes: type_cards 182 passed, sysid 100 passed (3 skipped), the site test 447 PASS{cite('git-s2r')}. One test file changed
inside a fix branch: bam_ws <code>tests/test_framecheck.py</code>'s fixture now writes runs stamped as checked, in the commit that added the new tests,
before the fix; no assertion changed{cite('git-bam')}.</p>""")

    # ---------------------------------------------------------------- decided for you
    w(f'<h2 id="decided">Decided for you</h2><p class="mute">Every call made instead of asking you. Each one is undone with the command beside it.</p>')
    w(stack_table(["Decision", "Why", "Undo"], [
        [f"Stable promoted to <code>{st['commit'][:7]}</code>", "Finding 3: the dock icon opened an older product.", "Right-click sim2real → <b>Roll Stable Back</b>"],
        ["Deployments are <b>virtual</b> or <b>physical</b>; every node is a deployment; no separate sub-deployment record",
         f"Your words, and the digital-twin pair; “real” and “sim” already mean other things on a run{cite('d-domain')}.", "Edit <code>DEPLOYMENT_KINDS</code>; or <code>git revert -m 1 6db7d0b</code>"],
        ["Eleven generic types; the three cameras stay three types; model ids <code>M&lt;k&gt;.&lt;family&gt;.&lt;name&gt;</code>, k counted per family",
         f"Pinhole, stereo depth and line-scan are different measurement models; your example has an M0 in each family{cite('d-domain')}.", "A local edit of the map in <code>type_cards/domain.py</code>"],
        ["Every rack twin label is the servo's <code>M4.dynamics.twin</code>, departures recorded", f"M4 is the “Rack twin” rung; M5 would overstate (no motor electrics){cite('d-models')}.", "<code>git revert -m 1 7bed016</code>"],
        ["Cross-run numbers are medians; a selection's gate verdict is the gate's target on that median",
         f"The browser can compute the same number with data-ui's own summaries{cite('d-domain', 'd-metrics')}.", "Change the summary rule in <code>type_cards/selection.py</code>; or <code>git revert -m 1 6db7d0b</code> (domain v3)"],
        ["Deployment pages sit beside the old record pages (two pages per physical deployment)", f"Nothing that worked breaks; linked both ways{cite('d-deploy')}.", "<code>git revert -m 1 fe172c1</code>"],
        ["One run page with levels in place (<code>?entity=</code>)", f"The tree stays beside every level and old links keep working{cite('d-run')}.", "<code>git revert -m 1 4826760</code>"],
        ["sim2real vendors data-ui d5ede93 + §49 backported; §49 (best per row, group show/hide) landed on data-ui main @ 998a2d93",
         f"data-ui main's §47 toolbar breaks the site test at 390 px{cite('d-models')}.", "<code>git -C /home/bam/data-ui revert -m 1 998a2d93</code>; re-vendor per VENDOR.md"],
        ["Every parameters preset shows every model's group (finding 8)", f"Meets both musts: each model its own group, pick which show{cite('d-models')}.", "<code>git revert 2ed2b8b</code>"],
        ["The three pre-fix reports are labelled, not re-frozen", f"Re-freezing would recompute their numbers on today's data{cite('d-metrics')}.", "Re-freeze with <code>python3 -m type_cards.report freeze</code>"],
        ["Routines are typed records in type_cards; the oracle's numbers live in sysid", f"A computed number belongs where a test holds it to the code{cite('d-cal')}.", "<code>git revert -m 1 ce78132</code>"],
        ["The noise ladder: one draw, scaled; bounds 0× a tenth of tolerance, k× k tolerances; UR backlash as a ladder-only scenario",
         f"Levels exactly comparable; folding the gap into the arm examples would move every committed UR number{cite('d-cal')}.", "<code>git revert -m 1 ce78132</code>"],
        ["The drift alarm counts the gap in its own units (T5's 2 arcmin) and warns on either check", f"The ratio alone goes deaf at 3×; the gap alone is 96 h later at 1×{cite('d-cal')}.",
         "<code>git revert -m 1 ac0f589</code> (either check); <code>git revert -m 1 b9d000a</code> (gap units)"],
        ["Media are build outputs in <code>~/.cache</code>, never git; camera and render side by side, never overlaid", f"~0.4 GB and growing; the render is not in the camera's frame{cite('d-media')}.", "Revert the media lane's commits"],
        ["Schedule sessions record mp4 only; calibration sessions keep raw frames", f"The raw grey frames are what forced the 120 s ceiling{cite('plan-cam', 'git-bam')}.", "<code>camera_mode: \"full\"</code> in a plan, or <code>git revert d37c1bb8</code>"],
        ["PEP 0017 and its amendment: check every board's frame before any motion", f"A whole-turn shift can read inside CAN 13's window{cite('pep17')}.", "<code>git revert 2228454d 687af466 f33762c2</code>; then <code>a476b1e7 79169306 6b917e4f</code>"],
        ["CAN 11 −1 turn and CAN 21 +1 turn re-referenced (RAM only), then their sessions re-run", f"The turn was proven by encoder and window; one candidate each{cite('pep16')}.",
         "A power cycle, or <code>frame-reference --turns +1</code> (CAN 11) / <code>--turns -1</code> (CAN 21)"],
        ["CAN 4 and CAN 12 frames accepted", f"Both within 0.04 mrad of their newest runs, unchanged across the re-latch{cite('frames')}.", "Move the receipt out of <code>config_backups/</code>"],
        ["PEP 0016 verdicts: CAN 12's q head adopted; the other three heads refused", f"The other-day rule as written{cite('pep16')}.", "The revert list in PEP 0016's Undo"],
    ]))

    # ---------------------------------------------------------------- needs Zach
    w(f"""<h2 id="needs">Needs you (physical only)</h2>
<div class="need"><h3>1. CAN 13: look at the link</h3><p>Its rotor encoder proves the frame slipped by whole turns, but two candidates fit its proven
window [{c13_low}, 1.56] rad and the bare link has no gravity load to tell them apart: the joint sits at {c13_one} rad (+1 turn) or {c13_two} rad (+2, meaning the link was also
turned by hand since 10-29). Its low stop is the window's low edge. If the link sits about <b>{deg(c13_one):.0f}° above its low stop</b> it is +1; about
<b>{deg(c13_two):.0f}°</b>, +2{cite('pep16')}. Tell an agent which; the fix is a RAM-only frame reference, nothing flashed. Default if you say nothing: CAN 13 stays refused.</p></div>
<div class="need"><h3>2. Power the GIM43 bus (fdcanusb 272813EF)</h3><p>CAN 1, 14 and 15 did not answer discovery on 11-06{cite('triage')}. Once powered, each
needs one <code>frame-check --can-id N --accept</code> from rest before it moves; an agent can run those{cite('pep17')}.</p></div>
<div class="need"><h3>3. Light the room</h3><p>The camera sessions that grade the stops (T4 on CAN 1, 14 and 15) need light; the 10-23/24 footage is dark enough that the clips are
brightened by software{cite('triage', 'plan-cam')}.</p></div>
<div class="need"><h3>4. T7 (top speed) near the hard stops</h3><p>CAN 4 would need ~240 rad/s against its 30 rad/s ceiling, about 12 ms edge to edge at speed; CAN 12's
2.29 rad window leaves ~16 ms at speed where a plateau needs 50 ms{cite('triage')}. Recommendation: keep the ceilings beside the stops, and redefine T7 for joints
whose window is too short (grade the back-EMF and current limits at speeds the window allows). Default: the ceilings stay and T7 stays not run.</p></div>""")

    # ---------------------------------------------------------------- left
    w(f"""<h2 id="left">Left / next</h2>
<ul><li><b>Merge the two tree components</b> (<code>entity_tree</code> on the deployments pages, <code>status_tree</code> on the run page): three lanes' pages and checks
read them by their own classes, so it is its own change{cite('d-metrics', 'd-run')}.</li>
<li><b>Move sim2real to data-ui main</b> and take §47's one-row toolbar: the site test's locators, the pages' toolbars and the old app's flow test move with it{cite('d-models')}.</li>
<li><b>The slow ladder checks were not re-run</b> after the comparator fix: CAN 11 and the arms only run with <code>SYSID_LADDER_SLOW=1</code>{cite('audit', 'git-s2r')}.</li>
<li><b>Motor, gearbox and encoder metrics need instruments</b>: commanded current, an output angle apart from the rotor's, a load cell, a dyno, a tag angle per run{cite('d-metrics')}.</li>
<li>Runs for virtual deployments, a map from older runs to config snapshots, and the camera-per-run recorder's first real session (after items 2 and 3 above).</li></ul>""")

    # ---------------------------------------------------------------- sources
    items = "".join(f'<li id="s{i + 1}">{esc(label)}' + (f' · <a href="{esc(href)}">{esc(href if not href.startswith("obsidian") else "open in Obsidian")}</a>' if href else "") + "</li>"
                    for i, (_k, label, href) in enumerate(SOURCES))
    w(f"""<h2 id="src">Source index</h2><div class="sources"><ol>{items}</ol>
<p class="mute">Related notes: {vault('PROJECT - Sim2Real.md', 'PROJECT - Sim2Real')} · {vault('World Model/Chunks & Concepts/C - Digital Twin.md', 'C - Digital Twin')} ·
{vault('World Model/Chunks & Concepts/C - Backlash.md', 'C - Backlash')} · {vault('Maps & Views/MOC/MOC - System Identification.md', 'MOC - System Identification')} ·
{vault('Projects/BAM Robotics/Notes/Sim2Real Type Cards v2 — Model Rungs, Diagnostics, Test Types and Calibration Packages (2026-11-05).md', 'Sim2Real Type Cards v2')} ·
{vault('PROJECT - Data UI.md', 'PROJECT - Data UI')}</p>
<p class="mute">Built by <code>docs/build_report_sim2real_v3.py</code> from the site build of {build.get('seconds', '?')} s ({build['files']:,} files) and the files above.</p></div>""")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sim2Real v3 overnight</title><style>{CSS}</style></head><body><main>{''.join(s)}</main></body></html>"""


# ------------------------------------------------------------------------------------------------------------------------------ check

def check(out: Path, media: Path) -> None:
    """The written page, headless, dark, at 1280 and 390 px: a full-page screenshot each and any sideways scroll."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=headless_shell())
        for width in (1280, 390):
            ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme="dark", device_scale_factor=1)
            page = ctx.new_page()
            page.goto(out.as_uri())
            page.wait_for_load_state("load")
            page.wait_for_timeout(1500)
            dims = page.evaluate("() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, height: document.documentElement.scrollHeight,"
                                 " bg: getComputedStyle(document.body).backgroundColor,"
                                 " wide: [...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1"
                                 " && !e.closest('.tbl')).slice(0, 5).map((e) => e.tagName + '.' + e.className)})")
            page.screenshot(path=str(media / f"check-{width}-dark.png"), full_page=True)
            print(f"{width}px dark: scrollWidth {dims['scroll']} clientWidth {dims['client']} height {dims['height']} bg {dims['bg']} "
                  f"{'NO sideways scroll' if dims['scroll'] <= dims['client'] else 'SIDEWAYS SCROLL'} overflowing {dims['wide']}")
            ctx.close()
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="an already-served build, e.g. http://127.0.0.1:4795 (else --site is served on a free port)")
    ap.add_argument("--site", type=Path, default=SITE)
    ap.add_argument("--reuse", action="store_true", help="skip the browser; build from the media already captured")
    ap.add_argument("--recut", action="store_true", help="with --reuse: re-encode the hero from hero-raw.webm and segments.json")
    ap.add_argument("--check", action="store_true", help="render the written page dark at 1280 and 390 px and report sideways scroll")
    args = ap.parse_args()

    names = ["deployments", "rack", "station", "run-top", "run-camera", "run-playback", "models", "routines", "parameters", "metrics", "reports",
             "report-page", "wear"]
    if args.reuse:
        shots = {n: MEDIA / f"{n}.webp" for n in names}
        if args.recut:
            hero_cut(MEDIA / "hero-raw.webm", [tuple(x) for x in json.loads((MEDIA / "segments.json").read_text())["segments"]], MEDIA)
    else:
        server = None
        base = args.base
        if not base:
            port = free_port()
            server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(args.site)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            base = f"http://127.0.0.1:{port}"
            time.sleep(0.8)
        try:
            shots = capture(base.rstrip("/"), MEDIA)
        finally:
            if server is not None:
                server.terminate()
                server.wait(timeout=10)
    facts = load_facts()
    ladder = load_ladder()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(shots, facts, ladder), encoding="utf-8")
    size = OUT.stat().st_size
    print(f"wrote {OUT} ({size / 1e6:.2f} MB{'; over the 1.9 MB media-page limit' if size > 1.9e6 else ''})")
    if args.check:
        check(OUT, MEDIA)


if __name__ == "__main__":
    main()
