"""Open one proposal at a state in headless Chromium and save a screenshot, plus the console errors (development helper).

    env -u VIRTUAL_ENV uv run --isolated --no-project --with playwright python tools/shoot.py v1 '#/d/one-dof-test-rack?n=can11' out.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parents[1]
EXE = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell"
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def shoot(variant: str, hash_: str, out: str, width: int = 1440, height: int = 900, wait_ms: int = 900, scheme: str = "dark") -> list[str]:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=ARGS, executable_path=EXE)
        page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.goto((HERE / variant / "index.html").as_uri() + hash_)
        page.wait_for_timeout(wait_ms)
        page.screenshot(path=out)
        browser.close()
    return errors


if __name__ == "__main__":
    errs = shoot(sys.argv[1], sys.argv[2], sys.argv[3])
    print("\n".join(errs) or "no console errors")
