"""Capture every proposal at its five walkthrough steps (the same labels in every variant) and record each one's click-through.

The steps are real states of the running prototypes: each is a URL (the selection lives in the hash) plus, where a view is
a remembered preference (a folded dock, an open sheet), the localStorage key the page itself writes. The click-through
video drives the page with real clicks only (no hash jumps), so it shows the interaction, not a slideshow.

    env -u VIRTUAL_ENV taskset -c 2-5,16,17 uv run --isolated --no-project --with playwright python tools/capture.py [v1 ...] [--no-video]

Writes /home/bam/sim2real/reports/media/deployment-page-proposals-2026-11-17/<v>/s<k>.png and <v>/walk.mp4 (gitignored media).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parents[1]
OUT = Path("/home/bam/sim2real/reports/media/deployment-page-proposals-2026-11-17")
EXE = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell"
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
VIEW = {"width": 1440, "height": 900}
D = "#/d/one-dof-test-rack"
STEP_LABELS = ["The rack: 3D + typed tree", "CAN 11: metrics and gates", "Nested table", "Before fit vs now", "Deployments"]
STATIONS = ["can1", "can11", "can12", "can13", "can14", "can15"]
SERVOS = [s + "/servo" for s in STATIONS]

# (hash, {localStorage key suffix: value}, js to run after load or None)
STEPS = {
    "v1": [(D, {}, None), (D + "?n=can11", {}, None), (D + "?n=can11&view=table", {"table.folded": [s for s in SERVOS if s != "can11/servo"]}, None),
           (D + "?n=can11&round=r0", {}, None), ("#/", {}, None)],
    "v2": [(D, {"dock.folded": False}, None), (D + "?n=can11&q=twin", {"dock.folded": False}, None),
           (D + "?n=can11", {"dock.folded": True, "folded": [s for s in SERVOS if s != "can11/servo"]}, None),
           (D + "?n=can11&q=twin", {"dock.folded": False}, "document.getElementById('insp').scrollTop = document.querySelector('#insp h3').offsetTop - 8"), ("#/", {}, None)],
    "v3": [(D, {}, None), (D + "?n=can11", {}, None), (D + "?n=can11", {"sheet.open": True, "sheet.folded": [s for s in SERVOS if s != "can11/servo"]}, None),
           (D + "?n=can11&round=r0", {}, None), ("#/", {}, None)],
    "v4": [(D, {}, None), (D + "?n=can11&q=twin", {}, None), (D + "?n=can11", {"insp.folded": True, "folded": [s for s in SERVOS if s != "can11/servo"]}, None),
           (D + "?mode=changed", {"insp.folded": True}, None), ("#/", {}, None)],
    "v5": [(D, {}, None), (D + "?n=can11", {}, None), (D, {"grid.folded": [s for s in STATIONS if s != "can11"]}, None),
           (D + "?n=can11&rung=0.4", {}, "document.getElementById('page').scrollTop = document.getElementById('body').offsetTop"), ("#/", {}, None)],
}
EXTRA = {  # supporting stills, one decision each
    "v1": [("ladder", D + "?n=can11&tab=ladder", {}, None), ("definition", D + "?n=can11/servo&tab=def", {}, None)],
    "v2": [("ledger", D + "?n=can11/servo", {"dock.folded": False}, "document.querySelector('details.rows').open = true; document.getElementById('insp').scrollTop = document.querySelector('details.rows').offsetTop - 8")],
    "v3": [("exploded", D + "?n=can11/servo/motor", {}, None)],
    "v4": [("ladder", D + "?n=can11", {}, None)],
    "v5": [("servo", D + "?n=can11/servo", {}, None)],
}


def storage_script(variant: str, store: dict) -> str:
    sets = "".join(f"localStorage.setItem({json.dumps('s2r.deployment-page.' + variant + '.' + k)}, {json.dumps(json.dumps(v))});" for k, v in store.items())
    return "try{localStorage.clear();" + sets + "}catch(e){}"


def shoot(browser, variant: str, hash_: str, store: dict, js: str | None, out: Path, errors: list[str]) -> None:
    ctx = browser.new_context(viewport=VIEW, color_scheme="dark")
    ctx.add_init_script(storage_script(variant, store))
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"{variant} {hash_}: {e}"))
    page.on("console", lambda m: errors.append(f"{variant} {hash_}: {m.text}") if m.type == "error" else None)
    page.goto((HERE / variant / "index.html").as_uri() + hash_)
    page.wait_for_timeout(1100)
    if js:
        page.evaluate(js)
        page.wait_for_timeout(300)
    page.screenshot(path=str(out))
    ctx.close()


def click_tree(page, node_id: str) -> None:
    page.locator(f'li[data-id="{node_id}"] > .trow').first.click()


WALKS = {  # real clicks only; each ends where its before/after shows
    "v1": [lambda p: p.locator('a.drow[href*="one-dof-test-rack"]').click(), lambda p: click_tree(p, "can11"), lambda p: p.locator('[data-tab="metrics"]').click(),
           lambda p: p.locator('#round button[data-r="r0"]').click(), lambda p: p.locator('#round button[data-r="r8"]').click(), lambda p: p.locator('.railbtn[data-v="table"]').click(),
           lambda p: p.locator('tr[data-id="can11/servo"]').click()],
    "v2": [lambda p: p.locator('tr[data-href*="one-dof-test-rack"]').click(), lambda p: p.locator('tr[data-id="can11"] td[data-q="twin"]').click(),
           lambda p: p.locator('tr[data-id="can12"] td[data-q="job"]').click(), lambda p: p.locator('tr[data-id="can11/servo"] [data-tw]').click(), lambda p: p.locator('tr[data-id="can11/servo/motor"] td[data-q="twin"]').click()],
    "v3": [lambda p: p.locator('a.tile[href*="one-dof-test-rack"]').click(), lambda p: p.locator('.s-label[data-id="can11"]').click(), lambda p: p.locator('.parts .p[data-go="can11/servo"]').click(),
           lambda p: p.locator('.parts .p[data-go="can11/servo/motor"]').click(), lambda p: p.locator("#time").press("ArrowLeft"), lambda p: p.locator("#time").press("ArrowRight"), lambda p: p.locator("#sheetBtn").click()],
    "v4": [lambda p: p.locator('tr[data-href*="one-dof-test-rack"]').click(), lambda p: p.locator("#cause").click(), lambda p: p.locator('.step[data-q="floor"]').click(),
           lambda p: p.locator('#mode button[data-m="changed"]').click(), lambda p: p.locator('#mode button[data-m="r8"]').click(), lambda p: p.locator('tr[data-id="can15"] td.nm .in b').click()],
    "v5": [lambda p: p.locator('a.drow[href*="one-dof-test-rack"]').click(), lambda p: p.locator('td.cell[data-id="can11"][data-rung="0.4"]').click(),
           lambda p: p.evaluate("document.getElementById('page').scrollTo({top: 360, behavior: 'smooth'})"), lambda p: click_tree(p, "can11/servo"), lambda p: p.locator("#overlay").click(), lambda p: p.locator("#overlay").click()],
}


def walk(browser, variant: str, out: Path, errors: list[str]) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="walk-", dir=str(OUT)))
    ctx = browser.new_context(viewport=VIEW, color_scheme="dark", record_video_dir=str(tmp), record_video_size={"width": 1440, "height": 900})
    ctx.add_init_script(storage_script(variant, {}))
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"{variant} walk: {e}"))
    page.goto((HERE / variant / "index.html").as_uri() + "#/")
    page.wait_for_timeout(1400)
    for step in WALKS[variant]:
        step(page)
        page.wait_for_timeout(1700)
    page.wait_for_timeout(600)
    video = page.video.path()
    ctx.close()
    # WHY h264 mp4 at 1280 wide: plays in every browser and in the desktop preview; the webm Playwright writes does not everywhere
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", "scale=1280:-2,fps=20", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "30", "-preset", "medium", "-movflags", "+faststart", "-an", str(out)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(out), "-vf", "fps=6,scale=720:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer",
                    str(out.with_suffix(".gif"))], check=True)
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    variants = [a for a in sys.argv[1:] if a.startswith("v")] or list(STEPS)
    video = "--no-video" not in sys.argv
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=ARGS, executable_path=EXE)
        for v in variants:
            d = OUT / v
            d.mkdir(parents=True, exist_ok=True)
            for k, (h, store, js) in enumerate(STEPS[v], 1):
                shoot(browser, v, h, store, js, d / f"s{k}.png", errors)
            for name, h, store, js in EXTRA.get(v, []):
                shoot(browser, v, h, store, js, d / f"x_{name}.png", errors)
            if video:
                walk(browser, v, d / "walk.mp4", errors)
            print(v, "captured", flush=True)
        browser.close()
    print("\n".join(errors) or "no console errors")


if __name__ == "__main__":
    main()
