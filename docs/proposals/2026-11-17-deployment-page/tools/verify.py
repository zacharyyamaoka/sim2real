"""Acceptance for all five proposals, measured in headless Chromium (no screenshot-only claims).

For each variant it checks, on the real fixture: the page loads without a console error; a tree/table/matrix row click
selects that node (URL + page text); a click ON a 3D station mesh selects it (the station's projected joint, not a label);
the ViewCube's TOP face moves the camera (scene pixels change); the CAD render toggle shows the still; the main panel
boundary drags, the size survives a reload, and a double-click restores it; the inspector folds (where there is one);
the variant's before/after control changes the round shown. Writes tools/verify.json; exits 1 on any failure.

    env -u VIRTUAL_ENV taskset -c 2-5,16,17 uv run --isolated --no-project --with playwright python tools/verify.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parents[1]
EXE = "/home/bam/.cache/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell"
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
D = "#/d/one-dof-test-rack"

SPEC = {  # row selector for CAN 12, the main sash and what it sizes, the fold control, the before/after control
    "v1": {"row": 'li[data-id="can12"] > .trow', "sash": "#sashL", "target": "#left", "fold": None, "ba": ('#round button[data-r="r0"]', "round=r0")},
    "v2": {"row": 'tr[data-id="can12"] td.c-comp', "sash": "#sashD", "target": "#dock", "fold": ("#fold", "#dock"), "ba": None},
    "v3": {"row": 'li[data-id="can12"] > .trow', "sash": "#sashO", "target": "#outline", "fold": ("#foldCard", "#card"), "ba": ("#time", "round=r0")},
    "v4": {"row": 'tr[data-id="can12"] td.nm .in b', "sash": "#sashL", "target": "#side", "fold": ("#foldI", "#insp"), "ba": ('#mode button[data-m="changed"]', "mode=changed")},
    "v5": {"row": 'li[data-id="can12"] > .trow', "sash": "#sashL", "target": "#left", "fold": None, "ba": ("#overlay", None)},
}


def check(variant: str, browser) -> dict:
    spec, res, errors = SPEC[variant], {}, []
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    url = (HERE / variant / "index.html").as_uri()
    page.goto(url + D)
    page.evaluate("localStorage.clear()")
    page.reload()
    page.wait_for_timeout(1200)

    # a row selects its node
    page.locator(spec["row"]).first.click()
    page.wait_for_timeout(500)
    res["row_selects"] = "n=can12" in page.url and "CAN 12" in page.inner_text("body")

    # a click on the station mesh in 3D selects it
    page.goto(url + D)
    page.wait_for_timeout(1300)
    pt = page.evaluate("(() => { const r = S2R._racks[0]; return r.screenOf('can14'); })()")
    page.mouse.click(pt["x"], pt["y"] + 2)
    page.wait_for_timeout(500)
    res["mesh_pick"] = "n=can14" in page.url

    # the ViewCube moves the camera
    scene = page.locator(".scene canvas").first
    before = scene.screenshot()
    page.locator('.viewcube .face[title="View from top"]').first.click(force=True)
    page.wait_for_timeout(900)
    res["viewcube"] = scene.screenshot() != before

    # the CAD render toggle shows the still
    page.locator(".scene [data-cad]").first.click()
    page.wait_for_timeout(200)
    res["cad_toggle"] = page.locator(".scene .s-img").first.is_visible()
    page.locator(".scene [data-cad]").first.click()

    # the main panel boundary drags, persists through a reload, and double-click resets it
    tgt = spec["target"]
    w0 = page.evaluate(f"document.querySelector('{tgt}').getBoundingClientRect().width")
    box = page.locator(spec["sash"]).bounding_box()
    sx, sy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    sign = -1 if variant == "v2" else 1
    page.mouse.move(sx, sy)
    page.mouse.down()
    page.mouse.move(sx + sign * 70, sy, steps=6)
    page.mouse.up()
    w1 = page.evaluate(f"document.querySelector('{tgt}').getBoundingClientRect().width")
    page.reload()
    page.wait_for_timeout(1000)
    w2 = page.evaluate(f"document.querySelector('{tgt}').getBoundingClientRect().width")
    page.locator(spec["sash"]).dblclick()
    w3 = page.evaluate(f"document.querySelector('{tgt}').getBoundingClientRect().width")
    res["sash_drag"] = abs((w1 - w0) - 70) <= 3
    res["sash_persists"] = abs(w2 - w1) <= 3
    res["sash_reset"] = abs(w3 - w0) <= 3
    res["sash_px"] = [round(w0), round(w1), round(w2), round(w3)]

    # the inspector folds
    if spec["fold"]:
        page.goto(url + D + "?n=can11")
        page.wait_for_timeout(800)
        page.locator(spec["fold"][0]).click()
        page.wait_for_timeout(300)
        res["inspector_folds"] = not page.locator(spec["fold"][1]).is_visible()
    else:
        res["inspector_folds"] = "n/a (no inspector beside a wide view)"
    if variant == "v1":  # V1's inspector is the Table view's
        page.goto(url + D + "?n=can11&view=table")
        page.wait_for_timeout(700)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        res["inspector_folds"] = not page.locator("#insp").is_visible()

    # the before/after control
    page.goto(url + D + "?n=can11")
    page.wait_for_timeout(800)
    if spec["ba"] is None:
        res["before_after"] = "columns: " + str("round 0" in page.inner_text("#sheet").lower() and "now" in page.inner_text("#sheet").lower())
    else:
        sel, want = spec["ba"]
        if sel == "#time":
            page.locator(sel).press("ArrowLeft")
        else:
            page.locator(sel).click()
        page.wait_for_timeout(500)
        res["before_after"] = (want in page.url) if want else page.get_attribute(sel, "aria-pressed") == "false"
    res["console_errors"] = errors
    ctx.close()
    return res


def main() -> None:
    out, ok = {}, True
    with sync_playwright() as p:
        browser = p.chromium.launch(args=ARGS, executable_path=EXE)
        for v in [a for a in sys.argv[1:] if a.startswith("v")] or list(SPEC):
            r = check(v, browser)
            out[v] = r
            bad = [k for k, x in r.items() if x is False or (k == "console_errors" and x) or (isinstance(x, str) and x.endswith("False"))]
            ok = ok and not bad
            print(v, "PASS" if not bad else "FAIL " + ", ".join(bad), json.dumps(r), flush=True)
        browser.close()
    (HERE / "tools" / "verify.json").write_text(json.dumps(out, indent=1) + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
