"""Real is blue, sim is orange, in light and dark, read off the rendered legends in a real headless Chromium. Exit 1 on the first broken claim.

    uv run --no-project --with playwright python /home/bam/sim2real/dashboards/tests/test_colours.py --port 4781
    (add --shots <dir> to also save the arm's Visual home as colours-after-{light,dark}.png)

Zach (2026-10-28): "We want to train the eye to know what is real and what is sim. Blue and orange ... leaves green and red
for elsewhere." Starts `serve.py` on --port itself (refuses a port something already listens on) and stops it by pid.
For one rack page, one arm page and one suite page it reads the legend swatches data-ui drew (the 3D card's chips and every
time series card's keys) and asserts: real and real B are blue-family, twin and twin x20 orange-family, target and floor
grey, the eight rack motors (six arm joints) on the "Joint gap" card have pairwise distinct swatches; the host's real /
stand-in chip is blue / orange with WCAG AA text; and switching the system theme live re-resolves the swatches.
"""

from __future__ import annotations

import argparse
import colorsys
import pathlib
import re
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parents[2]
CHROME = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"
# (scale, proposal): every page that draws a real-vs-sim pair as series. Visual home: the 3D card and the gap cards;
# Run inspector: the time series of every situation.
PAGES = [("rack", "1-visual-home"), ("rack", "4-run-inspector"), ("arm", "1-visual-home"), ("arm", "4-run-inspector"),
         ("suite", "1-visual-home"), ("suite", "4-run-inspector")]
MOTOR_CARD = "Joint gap"
READ_LEGENDS = """() => [...document.querySelectorAll('.dv-timeseries-key, .dv-scene3d-key')].map((key) => {
  const swatch = key.querySelector('i');
  const style = swatch ? swatch.getAttribute('style') || '' : '';
  const own = (swatch && (swatch.style.getPropertyValue('--c') || swatch.style.getPropertyValue('--dv-ts-c'))) || '';
  const probe = document.createElement('canvas').getContext('2d');
  probe.fillStyle = '#000'; probe.fillStyle = own.trim();
  const card = key.closest('.dd-panel');
  return { card: card ? card.textContent.trim().slice(0, 40) : '', name: key.textContent.trim(), raw: own.trim(), hex: probe.fillStyle, style };
})"""
READ_CHIP = """() => { const chip = document.getElementById('scale-chip'); const s = getComputedStyle(chip);
  return { text: chip.textContent, fg: s.color, bg: s.backgroundColor, basis: chip.dataset.basis }; }"""


def listening(port: int) -> bool:
    out = subprocess.run(["ss", "-ltnH"], capture_output=True, text=True, check=True).stdout
    return any(line.split()[3].endswith(f":{port}") for line in out.splitlines())


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)
    print("  ok:", message)


def rgb(text: str) -> tuple[int, int, int]:
    """'#rrggbb' or 'rgb(r, g, b)' / 'rgba(r, g, b, a)' as 0-255 channels."""

    if text.startswith("#"):
        return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))
    return tuple(int(float(v)) for v in re.findall(r"[\d.]+", text)[:3])


def hue_sat(channels) -> tuple[float, float]:
    h, _l, s = colorsys.rgb_to_hls(*(c / 255 for c in channels))
    return h * 360, s


def is_blue(channels) -> bool:
    hue, sat = hue_sat(channels)
    return 195 <= hue <= 235 and sat >= 0.3


def is_orange(channels) -> bool:
    hue, sat = hue_sat(channels)
    return 8 <= hue <= 30 and sat >= 0.3


def is_grey(channels) -> bool:
    return hue_sat(channels)[1] <= 0.2


def luminance(channels) -> float:
    lin = [c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def wait_for_legends(page):
    page.wait_for_function("() => document.querySelectorAll('.dv-timeseries-key, .dv-scene3d-key').length > 0", timeout=30000)
    page.wait_for_timeout(2500)  # every card draws its own legend; give the slow ones (3D, video) their turn


def family_of(name: str) -> str | None:
    if name in ("real", "real B"):
        return "blue"
    if name in ("twin", "twin ×20"):
        return "orange"
    if name in ("target", "floor", "floor −"):
        return "grey"
    return None


def assert_pair_colours(legends: list[dict], where: str):
    seen = set()
    for item in legends:
        family = family_of(item["name"])
        if family is None:
            continue
        seen.add(item["name"])
        channels = rgb(item["hex"])
        ok = {"blue": is_blue, "orange": is_orange, "grey": is_grey}[family](channels)
        check(ok, f"{where}: legend '{item['name']}' ({item['card']!r}) is {family}-family, drawn {item['hex']}")
    return seen


def run(base: str, shots: pathlib.Path | None):
    by_scheme = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME)
        for scheme in ("light", "dark"):
            context = browser.new_context(color_scheme=scheme, viewport={"width": 1400, "height": 1000})
            page = context.new_page()
            problems = []
            page.on("pageerror", lambda error: problems.append(str(error)))
            colours = {}
            for scale, proposal in PAGES:
                where = f"{scheme} · {scale} · {proposal}"
                page.goto(f"{base}/dashboards/?proposal={proposal}&scale={scale}")
                wait_for_legends(page)
                legends = page.evaluate(READ_LEGENDS)
                check(bool(legends), f"{where}: {len(legends)} legend entries drawn")
                check(all(not item["raw"].startswith("var(") for item in legends), f"{where}: no legend still holds an unresolved var()")
                seen = assert_pair_colours(legends, where)
                check("real" in seen and ("twin" in seen or "twin ×20" in seen), f"{where}: the page draws a real and a sim series ({sorted(seen)})")
                colours[(scale, proposal)] = {item["name"]: item["hex"] for item in legends}
                # blue and orange mean real and sim, so no other series may wear them (data-ui's 8 hues force two rack motors to)
                strays = [item["name"] for item in legends if family_of(item["name"]) is None
                          and (is_blue(rgb(item["hex"])) or is_orange(rgb(item["hex"]))) and item["name"] not in ("CAN 15", "CAN 21")]
                check(not strays, f"{where}: no other series is blue or orange ({strays})")

                chip = page.evaluate(READ_CHIP)
                fg, bg = rgb(chip["fg"]), rgb(chip["bg"])
                family_ok = is_blue(fg) if chip["basis"] == "real" else is_orange(fg)
                check(family_ok, f"{where}: chip '{chip['text']}' is {'blue' if chip['basis'] == 'real' else 'orange'}-family text ({chip['fg']})")
                check(contrast(fg, bg) >= 4.5, f"{where}: chip text contrast {contrast(fg, bg):.2f}:1 >= 4.5 (WCAG AA)")

                if proposal == "1-visual-home":
                    motors = [item for item in legends if item["card"].startswith(MOTOR_CARD) and family_of(item["name"]) is None]
                    want = 8 if scale == "rack" else 6
                    check(len(motors) == want, f"{where}: '{MOTOR_CARD}' card lists {want} devices ({[m['name'] for m in motors]})")
                    swatches = [m["hex"] for m in motors]
                    check(len(set(swatches)) == want, f"{where}: its {want} swatches are pairwise distinct ({swatches})")
                    if scale != "rack":
                        check(not any(is_orange(rgb(h)) or is_blue(rgb(h)) for h in swatches), f"{where}: no joint swatch is blue or orange")
                    else:
                        loud = [m["name"] for m in motors if is_orange(rgb(m["hex"])) or is_blue(rgb(m["hex"]))]
                        check(len(loud) <= 2, f"{where}: only {loud} had to take blue or orange (data-ui's palette has 8 hues, 4 reserved)")
                    if shots and scale == "arm":
                        page.screenshot(path=str(shots / f"colours-after-{scheme}.png"), full_page=True)
            check(not problems, f"{scheme}: no page errors ({problems[:1]})")
            # light and dark resolve to different pixels of the same two slots
            by_scheme[scheme] = colours
            context.close()

        light, dark = by_scheme["light"], by_scheme["dark"]
        for key in light:
            for name in ("real", "twin ×20"):
                if name in light[key]:
                    check(light[key][name] != dark[key][name], f"{key[0]} {key[1]} '{name}': {light[key][name]} (light) and {dark[key][name]} (dark) differ")

        # badges: blue/orange only on real/sim values, green/red only on pass/fail values (data-ui badge slot classes dv-h1, dv-h2, dv-h3, dv-h8)
        expected = {1: {"real", "real B", "real-camera"}, 2: {"twin", "stand-in", "sim-render", "illustrative"},
                    3: {"twinned", "inside share", "pass"}, 8: {"not twinned", "over share", "fail"}}
        context = browser.new_context(color_scheme="light", viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        for scale in ("rack", "arm", "suite"):
            for proposal in ("2-type-catalog", "3-gate-matrix", "4-run-inspector", "5-error-budget"):
                page.goto(f"{base}/dashboards/?proposal={proposal}&scale={scale}")
                page.wait_for_selector(".dv-badge", timeout=30000)
                page.wait_for_timeout(2000)
                badges = page.evaluate("() => [...document.querySelectorAll('.dv-badge')].map((b) => [b.textContent.trim(), b.className])")
                wrong = sorted({f"{text!r} {cls}" for text, cls in badges
                                for slot in (1, 2, 3, 8) if f"dv-h{slot}" in cls.split() and text not in expected[slot]})
                check(not wrong, f"{scale} {proposal}: {len(badges)} badges, none wears a reserved colour without its meaning ({wrong[:3]})")
        context.close()

        # a live theme switch re-resolves the palette: no reload by the reviewer
        context = browser.new_context(color_scheme="light", viewport={"width": 1400, "height": 1000})
        page = context.new_page()
        page.goto(f"{base}/dashboards/?proposal=4-run-inspector&scale=arm")
        wait_for_legends(page)
        first = page.evaluate(READ_LEGENDS)
        before = {item["name"]: item["hex"] for item in first}
        before["raw"] = next(item["raw"] for item in first if item["name"] == "real")
        page.emulate_media(color_scheme="dark")
        page.wait_for_function(
            "(was) => [...document.querySelectorAll('.dv-timeseries-key')].some((key) => key.textContent.trim() === 'real' && key.querySelector('i').style.getPropertyValue('--dv-ts-c').trim() !== was)",
            arg=before["raw"], timeout=20000)
        after = {item["name"]: item["hex"] for item in page.evaluate(READ_LEGENDS)}
        check(after["real"] != before["real"] and is_blue(rgb(after["real"])), f"live theme switch: real {before['real']} -> {after['real']}, still blue")
        check(after["twin"] != before["twin"] and is_orange(rgb(after["twin"])), f"live theme switch: twin {before['twin']} -> {after['twin']}, still orange")
        context.close()
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, required=True, help="a free port in 4700-4799")
    parser.add_argument("--shots", type=pathlib.Path, help="save the arm Visual home as colours-after-{light,dark}.png here")
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
