#!/usr/bin/env python3
"""Record the hero video of reports/one-click-calibration-2026-11-15.html's mock, clicked through once, plus review stills.

Run (headless Chromium, never fronts a window):
    env -u VIRTUAL_ENV uv run --offline --no-project --with playwright python docs/record_one_click_summary_hero.py [--stills DIR]

Writes reports/media/one-click-calibration-2026-11-15/{hero.mp4, hero.gif, poster.jpg}. The video is the mock's own behaviour
in a real browser — not a calibration run.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "reports" / "one-click-calibration-2026-11-15.html"
MEDIA = ROOT / "reports" / "media" / "one-click-calibration-2026-11-15"
ONLY_MOCK = "main>*:not(#mock){display:none!important} main{padding:14px!important;max-width:none!important} .mock{margin:0!important}"


def record(browser) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="hero-"))
    context = browser.new_context(viewport={"width": 1120, "height": 700}, record_video_dir=str(tmp),
                                  record_video_size={"width": 1120, "height": 700}, color_scheme="light")
    page = context.new_page()
    page.goto(PAGE.as_uri())
    page.add_style_tag(content=ONLY_MOCK)
    page.wait_for_timeout(1600)
    page.click("text=Next: plug it in")
    page.wait_for_selector("#m-to-cal:not([disabled])")
    page.wait_for_timeout(900)
    page.click("#m-to-cal")
    page.wait_for_timeout(700)
    page.click(".seg button[data-on=real]")
    page.wait_for_timeout(2200)
    page.click(".seg button[data-on=sim]")
    page.wait_for_timeout(500)
    page.click("#m-cal")
    page.wait_for_selector(".mpanel[data-panel='3'].on", timeout=30000)
    page.wait_for_timeout(3600)
    video = Path(page.video.path())
    context.close()
    return video


def stills(browser, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, viewport, scheme in [("desktop", {"width": 1280, "height": 900}, "light"),
                                   ("dark", {"width": 1280, "height": 900}, "dark"),
                                   ("phone", {"width": 390, "height": 844}, "light")]:
        context = browser.new_context(viewport=viewport, color_scheme=scheme, device_scale_factor=1)
        page = context.new_page()
        page.goto(PAGE.as_uri())
        page.wait_for_timeout(400)
        page.screenshot(path=str(out / f"{name}-full.png"), full_page=True)
        width = page.evaluate("document.documentElement.scrollWidth")
        print(name, "scrollWidth", width, "viewport", viewport["width"])
        if name != "phone":
            for step in range(4):
                if step == 1:
                    page.click("text=Next: plug it in")
                    page.wait_for_selector("#m-to-cal:not([disabled])")
                if step == 2:
                    page.click("#m-to-cal")
                if step == 3:
                    page.click("#m-cal")
                    page.wait_for_selector(".mpanel[data-panel='3'].on", timeout=30000)
                page.wait_for_timeout(300)
                page.locator("#mock").screenshot(path=str(out / f"{name}-mock-{step}.png"))
        context.close()


def main() -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # WHY a fallback executable: the uv-cached playwright may expect a newer browser build than ~/.cache/ms-playwright holds,
        # and downloading one isn't needed for a headless capture.
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001
            shells = sorted(Path.home().glob(".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))
            browser = p.chromium.launch(headless=True, executable_path=str(shells[-1]))
        if "--stills" in sys.argv:
            stills(browser, Path(sys.argv[sys.argv.index("--stills") + 1]))
        webm = record(browser)
        browser.close()
    mp4, gif, poster = MEDIA / "hero.mp4", MEDIA / "hero.gif", MEDIA / "poster.jpg"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.4", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "27", "-preset", "slow", "-movflags", "+faststart", "-an", str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-1.5", "-i", str(mp4), "-frames:v", "1", "-q:v", "4", str(poster)],
                   check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                    "fps=8,scale=760:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                    str(gif)], check=True)
    for f in (mp4, gif, poster):
        print(f, f"{f.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
