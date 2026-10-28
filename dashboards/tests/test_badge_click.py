"""Visual home -> Type catalog click-through, driven in a real headless Chromium. Fails (exit 1) on the first broken claim.

    uv run --no-project --with playwright python /home/bam/sim2real/dashboards/tests/test_badge_click.py --port 4781
    (add --shots <dir> to also save the rack's before/after screenshots: badge-click-{before,after}.png)

Starts `serve.py` on --port itself (refuses a port something already listens on) and stops it by pid at the end.
For every device of every scale (rack, arm, suite) it: opens Visual home, clicks the device's badge, asserts the URL, the
switcher, the selected device (the type's panels filtered to it where the type has a rail, the marked badge always), that the type's block is
in view, and that browser Back returns to Visual home; for the first device of a scale it also uses the "← Visual home" link.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time
import urllib.parse

from playwright.sync_api import expect, sync_playwright

REPO = pathlib.Path(__file__).resolve().parents[2]
CHROME = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"
HOME, TARGET = "1-visual-home", "2-type-catalog"
MANIFEST = json.loads((REPO / "dashboards" / "proposals.json").read_text(encoding="utf-8"))


def listening(port: int) -> bool:
    out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True, check=True).stdout
    return any(line.split()[3].endswith(f":{port}") for line in out.splitlines())


def query(url: str) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)
    print("  ok:", message)


def open_home(page, base: str, scale: str, devices: dict):
    page.goto(f"{base}/dashboards/?proposal={HOME}&scale={scale}")
    # every badge is decorated as a link once data-ui has drawn it
    expect(page.locator(".dv-kpi-card[data-s2r-link]")).to_have_count(len(devices), timeout=20000)


def click_through(page, base: str, scale: str, device: str, devices: dict, rails: list, blocks: dict, shot_dir=None):
    type_ = devices[device]
    open_home(page, base, scale, devices)
    home_url = page.url
    check(query(home_url)["proposal"] == HOME and query(home_url)["scale"] == scale, f"{scale}: Visual home URL names its proposal and scale")
    if shot_dir:
        page.wait_for_timeout(2500)  # the 3D card and the still draw after the badges
        page.screenshot(path=str(shot_dir / "badge-click-before.png"))
    card = page.locator(".dv-kpi-card[data-s2r-link]", has=page.locator(".dv-kpi-label", has_text=device)).filter(
        has=page.get_by_text(device, exact=True))
    expect(card).to_have_count(1)
    card.click()

    page.wait_for_url(lambda url: query(url).get("proposal") == TARGET, timeout=20000)
    params = query(page.url)
    check(params["scale"] == scale, f"{scale}/{device}: same scale after the click")
    check(params["focus"] == device and params["from"] == HOME, f"{scale}/{device}: URL carries focus={device!r} and from={HOME}")
    if type_ in rails:
        rail_value = urllib.parse.unquote(params[f"{type_}.device"])
        check(rail_value == device, f"{scale}/{device}: URL selects the device in the {type_} rail ({rail_value!r})")
    else:
        check(f"{type_}.device" not in params, f"{scale}/{device}: {type_} has no rail, so no rail param")

    expect(page.locator("#pick-proposal")).to_have_value(TARGET)
    expect(page.locator("#pick-scale")).to_have_value(scale)
    check(True, f"{scale}/{device}: the switcher shows {TARGET} / {scale}")
    marked = page.locator("[data-s2r-focus]")
    expect(marked).to_have_count(1, timeout=20000)
    expect(marked).to_contain_text(device)
    check(True, f"{scale}/{device}: its badge is marked selected on the Type catalog")
    if type_ in rails:
        # WHY the panels' filters and not the rail's radio: with two rails on a page (suite: servo + camera) data-ui draws the
        # servo rail with no radio checked even at its default, though the filter is applied (a data-ui gap, not this link)
        applied = page.evaluate("() => JSON.stringify(document.getElementById('dash').panelFilters())")
        check(f'device == \\"{device}\\"' in applied, f"{scale}/{device}: the {type_} panels are filtered to {device}")

    heading = page.locator(".dd-panel-text h4", has_text=blocks[type_]).first
    # the scroll lands once the panels have settled; poll the geometry rather than sleep
    deadline = time.time() + 10
    box = None
    while time.time() < deadline:
        box = page.evaluate(
            """([blockTitle]) => {
                const h = [...document.querySelectorAll('.dd-panel-text h4')].find((x) => x.textContent.trim() === blockTitle);
                const c = document.querySelector('[data-s2r-focus]');
                const a = h.getBoundingClientRect(), b = c.getBoundingClientRect();
                return { heading: a.top, card: b.bottom, bar: document.querySelector('.bar').getBoundingClientRect().bottom, vh: innerHeight };
            }""", [blocks[type_]])
        if 0 <= box["heading"] - box["bar"] < 200 and box["card"] <= box["vh"]:
            break
        page.wait_for_timeout(250)
    expect(heading).to_be_visible()
    check(box["heading"] >= box["bar"] and box["card"] <= box["vh"],
          f"{scale}/{device}: the {blocks[type_]!r} block is in view under the header (heading y={box['heading']:.0f}, badge bottom y={box['card']:.0f} of {box['vh']})")
    back = page.locator("#back-link")
    expect(back).to_be_visible()
    expect(back).to_have_text("← Visual home")
    check(True, f"{scale}/{device}: a visible '← Visual home' link")
    if shot_dir:
        page.wait_for_timeout(1500)
        page.screenshot(path=str(shot_dir / "badge-click-after.png"))
    return home_url


def run(base: str, shot_dir):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for scale in MANIFEST["scales"]:
            scale_id = scale["id"]
            info = MANIFEST["click_through"][scale_id]
            devices, rails, blocks = info["devices"], info["rails"], info["blocks"]
            print(f"scale {scale_id}: {len(devices)} devices, rails {rails}")
            for position, device in enumerate(devices):
                shots = shot_dir if (shot_dir and scale_id == "rack" and position == 0) else None
                home_url = click_through(page, base, scale_id, device, devices, rails, blocks, shots)
                if position == 0:
                    page.locator("#back-link").click()
                    page.wait_for_url(lambda url: query(url).get("proposal") == HOME, timeout=20000)
                    expect(page.locator("#pick-proposal")).to_have_value(HOME)
                    check(query(page.url)["scale"] == scale_id, f"{scale_id}/{device}: the '← Visual home' link returns to Visual home, same scale")
                    page.go_back()  # the Type catalog again, then the browser Back below
                    page.wait_for_url(lambda url: query(url).get("proposal") == TARGET, timeout=20000)
                page.go_back()
                page.wait_for_url(lambda url: query(url).get("proposal") == HOME, timeout=20000)
                expect(page.locator("#pick-proposal")).to_have_value(HOME)
                expect(page.locator("#pick-scale")).to_have_value(scale_id)
                expect(page.locator(".dv-kpi-card[data-s2r-link]")).to_have_count(len(devices), timeout=20000)
                check(page.url == home_url, f"{scale_id}/{device}: browser Back returns to the exact Visual home URL")
        check(not errors, f"no uncaught page errors {errors[:2]}")
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True, help="a free port in 4700-4799 (checked with ss -ltn)")
    parser.add_argument("--shots", type=pathlib.Path, help="directory for the rack's badge-click-{before,after}.png")
    args = parser.parse_args()
    if not 4700 <= args.port <= 4799 or listening(args.port):
        print(f"port {args.port} is outside 4700-4799 or already has a listener", file=sys.stderr)
        return 2
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, str(REPO / "serve.py"), "--port", str(args.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        while not listening(args.port) and time.time() < deadline:
            time.sleep(0.1)
        run(f"http://127.0.0.1:{args.port}", args.shots)
        print("PASS")
        return 0
    except (AssertionError, Exception) as error:  # noqa: BLE001 (any failure is a failed test; the server is still stopped)
        print("FAIL:", error, file=sys.stderr)
        return 1
    finally:
        server.terminate()  # the pid this script started, never "whatever is on the port"
        server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
