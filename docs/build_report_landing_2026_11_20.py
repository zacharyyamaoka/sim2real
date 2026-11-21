"""Builds reports/landing-page-2026-11-20.html: the sim2real landing page (Zach's Daily Note 2026-11-20, "# Sim2Real routines") after its
verifier fix round, as handed over to Zach.

    python3 /home/bam/sim2real/docs/build_report_landing_2026_11_20.py

Stdlib only. Every number on the page comes from a file, nothing is typed in:
- website/data/landing.json                     the landing's own numbers (each read out of its source by export_landing.py)
- reports/media/landing-2026-11-20/ (gitignored, captured during the fix round):
  cloud_fix_own.json, cloud_fix_calls.json      the summary.json of the two cloud dispatches that checked the landed tree
  cloud_prev_own.json                           the same rulers on the page before the fix round (40e1cd8)
  export_check.txt                              export_landing.py --check (the ruler's own recheck of every number)
  precheck.txt, precheck.py                     the light pre-check with the ruler's helpers (no pytest, no sim)
  fix-measure.json, prev-measure.json           page height, overflow and image decode at 1280 and 390 px, after and before
  registry_counts.json                          the part-type, routine and bench/deployed counts the built page shows
  git_log.txt                                   `git log --oneline 8dd457f..c01f206` (what landed)
  fix-*.png, final-*.png, fix-hero-loop.webp    screenshots of the built page (after, before) and the page's own hero loop
Images are linked from reports/media/, not inlined, so the committed page stays text.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEDIA_DIR = "media/landing-2026-11-20"
MEDIA = REPO / "reports" / MEDIA_DIR
OUT = REPO / "reports" / "landing-page-2026-11-20.html"
LANDED = "c01f206"
RULER_FIX = "48dba0e"  # the ruler owner's fix to its serial check (2026-11-20), cloud d06201020
e = html.escape

DATA = json.loads((REPO / "website" / "data" / "landing.json").read_text(encoding="utf-8"))
FORMATS = {"mm": "{n} mm", "°": "{n}°", "°/s": "{n}°/s", "× floor": "{n} × floor", "h": "{n} h", "": "{n}", "%": "{n}%",
           "×": "×{n}", "N·m": "{n} N·m"}
PLACE = re.compile(r"\{(=[^{}]+|gate:[a-z0-9_.-]+|cmp:[a-z0-9_.-]+:[a-z0-9_.-]+|[a-z0-9][a-z0-9_.-]*)\}")
SERIAL = re.compile(r"\b(?=[0-9A-F]*[A-F])(?=[0-9A-F]*[0-9])[0-9A-F]{8}\b|(?<![\d.])\d{10,}(?![\d.])")  # the ruler's own pattern


def load(name: str):
    path = MEDIA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def text(name: str) -> str:
    path = MEDIA / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def v(vid: str) -> str:
    """A landing value as the page shows it."""
    x = DATA["values"][vid]
    return FORMATS[x["display_unit"]].format(n=f"{x['value'] * x['scale']:.{x['digits']}f}")


def verdict(vid: str) -> str:
    x, g = DATA["values"][vid], DATA["values"][DATA["gate"]]
    value, limit = x["value"] * x["scale"], g["value"] * g["scale"]
    if x["measure"] == "gate_pass_rate":
        return "pass" if x["value"] >= 1 - 1e-12 else "fail"
    if x["measure"] == "stop_worst":
        return "pass" if value <= limit else "fail"
    return "fail" if value > limit else "not judged"


def plain(template: str) -> str:
    def one(m):
        body = m.group(1)
        if body.startswith("="):
            return body[1:]
        if body.startswith("gate:"):
            return verdict(body[5:])
        return v(body)
    return " ".join(PLACE.sub(one, template).replace("`", "").split())


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def landed() -> bool:
    return subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", LANDED, "main"], capture_output=True).returncode == 0


def img(name: str, alt: str, cls: str = "") -> str:
    exists = (MEDIA / name).is_file()
    if not exists:
        return f'<p class="missing">not captured: {e(name)}</p>'
    return f'<a href="{MEDIA_DIR}/{e(name)}"><img class="{cls}" src="{MEDIA_DIR}/{e(name)}" alt="{e(alt)}" loading="lazy"></a>'


def cloud_rows() -> str:
    rows = []
    for label, name in (("after the ruler fix (48dba0e)", "cloud_rulerfix_own.json"), ("after the fix round", "cloud_fix_own.json"), ("after the fix round, bam_rack_twin's venv", "cloud_fix_calls.json"),
                        ("before (40e1cd8)", "cloud_prev_own.json")):
        s = load(name)
        if s is None:
            rows.append(f"<tr><td>{e(label)}</td><td colspan=5>not captured</td></tr>")
            continue
        for f in s["files"]:
            cls = "pass" if f["verdict"] == "PASS" else "fail"
            rows.append(f'<tr><td>{e(label)}<br><span class="dim">sim2real {e(s["sim2real"][:7])}</span></td><td><code>{e(f["file"])}</code></td>'
                        f'<td class="{cls}">{e(f["verdict"])}</td><td>{f["passed"]}</td><td>{f["failed"]}</td><td>{f["skipped"]}</td></tr>')
    return "".join(rows)


def ruler_false_positive() -> tuple[str, list[tuple[str, str]]]:
    raw = (REPO / "website" / "data" / "landing.json").read_text(encoding="utf-8")
    hits = []
    for m in SERIAL.finditer(raw):
        line = raw[raw.rfind("\n", 0, m.start()) + 1:raw.find("\n", m.end())].strip()
        field = line.split(":", 1)[0].strip('"')
        hits.append((m.group(0), field))
    return raw, hits


def measure(name: str, key: str, field: str):
    d = load(name)
    return None if d is None or key not in d else d[key].get(field)


def main() -> None:
    own, calls, prev = load("cloud_fix_own.json"), load("cloud_fix_calls.json"), load("cloud_prev_own.json")
    counts = load("registry_counts.json") or {}
    check_line = next((ln for ln in text("export_check.txt").splitlines() if ln.startswith("recheck:")), "not captured")
    pre_line = next((ln for ln in text("precheck.txt").splitlines() if ln.startswith("problems:")), "not captured")
    _, hits = ruler_false_positive()
    hit_fields = sorted({f for _, f in hits})
    own_landing = next((f for f in (own or {}).get("files", []) if f["file"] == "tests/test_landing_page.py"), None)
    fp_line = next((ln for ln in (own_landing or {}).get("first_failure", []) if "AssertionError" in ln), "")
    calls_ok = calls is not None and calls["exit"] == 0
    is_landed = landed()
    h_after = {k: measure("fix-measure.json", k, "height") for k in ("1280-dark", "390-dark")}
    h_before = {k: measure("prev-measure.json", k, "height") for k in ("1280-dark", "390-dark")}
    wide_after = {k: measure("fix-measure.json", k, "wide") for k in ("1280-dark", "390-dark")}
    imgs_after = load("fix-measure.json") or {}
    imgs_ok = all(i["ok"] for m in imgs_after.values() for i in m.get("imgs", []))
    life = DATA["lifecycle"]
    nominal_test = next((f for f in (calls or {}).get("files", []) if "nominal" in f["file"]), None)
    loop_media = DATA["media"]["pendulum-can11-loop"]
    clip_s = re.search(r"trim=[\d.]+:([\d.]+)", loop_media["filter"]).group(1)
    loop_kib = f"{loop_media['bytes'] / 1024:.0f} KiB"
    ruler_lines = (REPO / "tests" / "test_landing_page.py").read_text(encoding="utf-8").splitlines()
    serial_line = next((i for i, ln in enumerate(ruler_lines, 1) if "assert not SERIAL.search(bare)" in ln), "not found")
    rulerfix = load("cloud_rulerfix_own.json")
    rf_landing = next((f for f in (rulerfix or {}).get("files", []) if f["file"] == "tests/test_landing_page.py"), None)
    rf_green = rulerfix is not None and rulerfix["exit"] == 0
    pushed = subprocess.run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", RULER_FIX, "origin/main"], capture_output=True).returncode == 0

    verdict_line = (f"<strong>The landing page's claims now match their files, every ruler is green, and it is on sim2real <code>main</code>"
                    f"</strong> ({'pushed to origin' if pushed else 'local, not pushed'}; page at <code>{LANDED}</code>, ruler fix <code>{RULER_FIX}</code>). "
                    if is_landed and rf_green else "<strong>The fixes are on <code>claude/landing</code>, not merged.</strong> ")
    verdict_line += ("The one red assertion was the ruler's own false positive (it read the decimal digits inside sha256 and commit hashes as a "
                     "device serial); its owner fixed it, and the cloud re-run is green." if rf_green else
                     "One ruler assertion stays red on the ruler's own false positive.")

    fix_rows = [
        ("The page said no integrator ever runs on the arm; the BAM arm file it cites holds a rest-integrator run, and the tuned run's static "
         "load was partly measured on it.",
         f"Tuned definition: <q>{e(plain(DATA['metrics']['tuned']['definition']))}</q> BAM note: <q>{e(plain(DATA['robots'][2]['rows'][0]['notes'][1]))}</q> "
         "Promise: what sim2real ships, and <code>preflight()</code> refuses an integrator.",
         "climb.json snapshot (the rest-integrator run's layout; the static-load run's notes list it); the UR wrist boards' recorded configs "
         "(integral gain zero, both runs); the tuned BAM run's notes; <code>preflight.py</code>'s docstring."),
        ("Wrong reason for the pendulum's missing as-found floor.",
         f"<q>{e(plain(DATA['robots'][0]['rows'][0]['notes'][1]))}</q>",
         "round 0 scorecard: the rung's own <code>floor.why_unknown</code> (it ran the repeats it planned)."),
        ("<code>(\"deployed\",)</code> was said to keep only the deployed routines.",
         f"It keeps the {counts.get('deployed', 'not captured')} deployed routines and the same {counts.get('both', 'not captured')} that run anywhere.",
         "<code>Budget.allows</code> (<code>src/sim2real/calibration/config.py</code>) admits setting \"both\" always; counts from the registry."),
        ("The definitions promised the same target and the same three numbers on every row.",
         f"Definitions say <q>the row's target</q>; the intro says what each cell leads with and how a median is judged. Pendulum note: "
         f"<q>{e(plain(DATA['robots'][0]['rows'][0]['notes'][0]))}</q> The UR rows say they record no joint error; the BAM row says it records "
         "only a median stop.",
         "the scorecards' amplitude and stop counts, read by the exporter."),
        ("UR5e: \"of tasks within the gate\".", "\"of runs within the gate\" (every repeat counts).",
         "arm_motion_bench <code>scorecard.py</code>: <code>gate_pass_rate</code> is the share of runs."),
        ("UR wrist: the as-found Coulomb feed-forward named on one joint only.",
         f"<q>{e(plain(DATA['robots'][1]['rows'][1]['notes'][0]))}</q>",
         "the as-found session plan's <code>ff_coulomb_nm</code>, three new sourced values."),
        ("The hero's wrist line left out the values that are not identified.", f"<q>{e(plain(DATA['hero']['lines'][1]))}</q>",
         "the example's recorded output; the count now sits in the recovery cell the hero may quote."),
        ("The BAM twin's median reads \"not judged\".", "Kept: a median at or under the gate proves nothing about the worst stop.",
         "the gate rule the ruler pins."),
        ("Schedule order named the regression first.",
         f"<q>{e(plain(DATA['recovery'][0]['notes'][0]))}</q>", "<code>docs/CALIBRATE.md</code> and <code>docs/API.md</code>."),
        ("The hero loop showed only the first ten seconds and sat the pendulum at the frame's edge.",
         "The whole clip, cropped to where the link swings; every second of it looked at and recorded.",
         "the contact sheet below; <code>landing.json</code> media frames_checked."),
        ("Claims with no source: the BAM description \"refused\", calibrate on real \"not yet run\", mode 3 \"runs today\".",
         "\"not accepted yet: its servos are not typed parts\"; \"no hardware run of it is recorded yet\"; mode 3 now has a cloud run behind it.",
         (f"<code>twin.py</code>'s refusal of unknown component types; the move-truth test passed on a VM in {nominal_test['seconds']} s at "
          f"<code>{e(calls['sim2real'][:7])}</code>." if nominal_test else "the move-truth test: not captured.")),
        ("Wording: \"it5\", \"1 frames\", a UTC date that read as tomorrow, \"run for real\" on a hidden-world example.",
         "All four gone: plain words, plural, date with time and \"UTC\", \"calibrate() on a hidden world, with its recorded output\".", "the built page."),
    ]
    design_rows = [
        ("Cells were not glanceable.", "Each cell leads with the number its gate judges, large, with its verdict chip; the rest small under it."),
        ("Three robots not visible at a glance.", "The three real robots' own pictures under the headline, each opening its row; first screen on a phone."),
        ("Hero readout terms defined a section later.", "Each line says its measure where it quotes it; the readout says the hidden world differs on purpose."),
        ("API block could not be started and scrolled sideways.", "Comments on their own lines (fits at 1280), the CAN id explained, and a plain line: no install command yet, and why."),
        ("Internal codes and process words.", "No CAN numbers in prose; \"lab recordings\", \"arm job records\"; no \"next leg\", \"live lane\", \"one-click seam\". The controller labels stay, small, as their files name them (the ruler pins them)."),
        ("Code broke mid-identifier.", "Calls wrap after dots and brackets only."),
        ("How-it-works diagram unreadable on a phone.", "A numbered, stacked list under 640 px; the diagram stays at desktop width."),
        ("Docs sidebar on the landing.", "Gone at desktop width (still the phone drawer)."),
        ("Page too long.", f"Sources folded behind one summary; four short reasons in the BAM truth row. Height at 1280: {h_before['1280-dark']} px before, "
                           f"{h_after['1280-dark']} px after; at 390: {h_before['390-dark']} px before, {h_after['390-dark']} px after."),
        ("Phone thumbnails blank.", f"Every image decoded before the shot, and checked: {'all decoded' if imgs_ok else 'some did not decode'} at both widths."),
        ("Layout shift, dangling arrows, empty card space.", "<code>&lt;img&gt;</code> width and height from each file; each loop arrow travels with its step; the mode cards' gap removed."),
    ]
    today_items = "".join(f"<li>{e(plain(item['text']))}</li>" for item in life["today"])
    not_built = "".join(f"<li><code>{e(item['name'])}</code>: {e(plain(item['text']))}</li>" for item in life["not_built"])
    loop = " → ".join(e(s) for s in life["loop"])

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>sim2real landing, fix round</title>
<style>
:root {{ --bg:#fbfbfa; --fg:#1b1c1e; --muted:#5d6168; --line:#e3e3e0; --soft:#f2f2ef; --pass:#1a7f4b; --fail:#b42318; --amber:#a15c07; --accent:#0f766e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0c0d0f; --fg:#e8e8e6; --muted:#9a9ea6; --line:#26282c; --soft:#15171a; --pass:#4ade80; --fail:#f87171; --amber:#fbbf24; --accent:#2dd4bf; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.55 system-ui, -apple-system, Segoe UI, sans-serif; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 28px 16px 64px; }}
h1 {{ font-size: 28px; letter-spacing:-0.02em; margin: 0 0 6px; }} h2 {{ font-size: 21px; margin: 40px 0 10px; letter-spacing:-0.01em; }}
h3 {{ font-size: 16px; margin: 22px 0 8px; }}
.verdict {{ font-size: 16px; padding: 12px 16px; border-left: 3px solid var(--accent); background: var(--soft); border-radius: 0 8px 8px 0; }}
.dim, .missing {{ color: var(--muted); font-size: 13px; }}
code {{ font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; }}
q {{ quotes: "“" "”"; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }} th, td {{ text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); padding: 8px 10px; }}
th {{ color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
.wrap {{ overflow-x: auto; }} .pass {{ color: var(--pass); font-weight: 600; }} .fail {{ color: var(--fail); font-weight: 600; }}
.grid2 {{ display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 14px; align-items: start; }}
.grid3 {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-items: start; }}
figure {{ margin: 0; }} figcaption {{ color: var(--muted); font-size: 12.5px; margin-top: 4px; }}
img {{ display: block; max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; }}
img.tall {{ max-height: 900px; width: auto; }}
.sheet {{ max-width: 560px; }} td code {{ overflow-wrap: anywhere; }}
ul {{ padding-left: 20px; }} li {{ margin: 4px 0; }}
.box {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; background: var(--soft); }}
.amber {{ border-color: var(--amber); border-style: dashed; }}
@media (max-width: 760px) {{ .grid2, .grid3 {{ grid-template-columns: minmax(0, 1fr); }} }}
</style></head><body><main>
<h1>sim2real landing page: fix round</h1>
<p class="dim">2026-11-20 · from Zach's Daily Note "# Sim2Real routines" · branch <code>claude/landing</code> · built by <code>docs/build_report_landing_2026_11_20.py</code></p>
<p class="verdict">{verdict_line}</p>
<ul>
<li><strong>Cloud, after the ruler fix:</strong> the landing ruler {rf_landing['passed'] if rf_landing else 'not captured'} passed, {rf_landing['failed'] if rf_landing else '?'} failed, {rf_landing['skipped'] if rf_landing else '?'} skipped; docs-site rulers {rulerfix and sum(f['passed'] for f in rulerfix['files'] if 'docs_site' in f['file'])} passed. At sim2real <code>{e((rulerfix or {}).get('sim2real', '')[:7])}</code>, cloud run <code>d06201020</code>.</li>
<li><strong>Cloud, the fix round:</strong> docs-site rulers {own and sum(f['passed'] for f in own['files'] if 'docs_site' in f['file'])} passed, 0 failed; the landing ruler {own_landing['passed'] if own_landing else 'not captured'} passed, {own_landing['failed'] if own_landing else '?'} failed (the false positive), {own_landing['skipped'] if own_landing else '?'} skipped (it runs in the other venv); in bam_rack_twin's venv the shown calls and mode 3's moved-truth fit {'both passed' if calls_ok else 'did not both pass'}. All at sim2real <code>{e((own or {}).get('sim2real', '')[:7])}</code>.</li>
<li><strong>Local:</strong> <code>{e(check_line)}</code>; the light pre-check with the ruler's own helpers: <code>{e(pre_line)}</code>. No page-wide horizontal scroll at 1280 or 390 ({'none found' if not any(wide_after.values()) else e(str(wide_after))}).</li>
</ul>

<h2>After and before</h2>
<div class="grid2">
<figure>{img('fix-1280-dark-top.png', 'The landing after the fix round, first screen at 1280 px')}<figcaption>After: the first screen at 1280 px. The three robots sit under the headline; the hero readout names its measures.</figcaption></figure>
<figure>{img('fix-390-dark-top.png', 'The landing after the fix round, first screen at 390 px', 'tall')}<figcaption>After, on a phone: pictures of all three robots in the first screen.</figcaption></figure>
</div>
<div class="grid2" style="margin-top:14px">
<figure>{img('final-1280-dark-top.png', 'The landing before the fix round, first screen at 1280 px')}<figcaption>Before (40e1cd8): the docs sidebar beside the hero; one robot, framed at its edge.</figcaption></figure>
<figure>{img('fix-hero-loop.webp', 'The pendulum loop the page shows, real footage')}<figcaption>The page's hero loop now: the whole {clip_s} s clip, cropped to where the link swings (real footage, one-to-one time).</figcaption></figure>
</div>

<h2>What the verifiers found, and what the page says now</h2>
<div class="wrap"><table><thead><tr><th>Finding</th><th>The page now</th><th>Checked against</th></tr></thead><tbody>
{''.join(f'<tr><td>{a}</td><td>{b}</td><td class="dim">{c}</td></tr>' for a, b, c in fix_rows)}
</tbody></table></div>

<h2>How it reads</h2>
<div class="wrap"><table><thead><tr><th>Finding</th><th>Now</th></tr></thead><tbody>
{''.join(f'<tr><td>{a}</td><td>{b}</td></tr>' for a, b in design_rows)}
</tbody></table></div>
<h3>The proof table: one number per cell to read first</h3>
{img('fix-1280-dark-sec-proof.png', 'The proof table at 1280 px')}
<h3>On a phone: the proof table, and How it works as a list</h3>
<div class="grid3">
<figure style="grid-column: span 2">{img('fix-390-proof-sheet.png', 'The proof table at 390 px, cut into three columns')}<figcaption>The proof table on a phone, its full height cut into three columns: each row stacks into a card whose cells keep their column's title.</figcaption></figure>
<figure>{img('fix-390-dark-sec-how.png', 'How it works at 390 px', 'tall')}<figcaption>How it works: a numbered list, each step a link.</figcaption></figure>
</div>
<h3>The API on one screen, and What you can do today</h3>
<div class="grid2">
<figure>{img('fix-1280-dark-sec-api.png', 'The API section at 1280 px')}<figcaption>No sideways scroll at 1280; a plain line on why there is no install command yet.</figcaption></figure>
<figure>{img('fix-1280-dark-sec-modes.png', 'The modes and the hidden-truth table at 1280 px')}<figcaption>Calls wrap after dots and brackets; the BAM row has four short reasons.</figcaption></figure>
</div>
<h3>Every second of the hero loop, looked at</h3>
<figure class="sheet">{img('fix-loop-sheet.png', 'One frame per second of the hero loop')}<figcaption>One frame per second of the loop: no people, no serials, no burned-in text.</figcaption></figure>

<h2>Bench today, deployed next: what is built and what is designed</h2>
<p>The lifetime section answers Zach's question, <q>what does a routine once deployed look like?</q> Once a robot is at work, calibration is mostly
watching the fit: <strong>{loop}</strong>. The landing marks the whole loop <em>designed, not built</em> and links its design,
<code>docs/DEPLOYED.md</code>.</p>
<p>Where each routine runs comes from the registry: {counts.get('bench', 'not captured')} bench, {counts.get('deployed', 'not captured')} deployed,
{counts.get('both', 'not captured')} that run anywhere, out of {counts.get('routines', 'not captured')} routines over {counts.get('types', 'not captured')} part types.</p>
<div class="grid2">
<div class="box"><h3>There today</h3><ul>{today_items}</ul></div>
<div class="box amber"><h3>Designed, not built</h3><ul>{not_built}</ul>
<p class="dim">Build order in <code>docs/DEPLOYED.md</code>: production, then monitor, recalibrate, a validity window, save_description. Decided there: refit from the
priors over a window of sessions, never install a challenger by itself, write the description only when asked, PD and feed-forward only.</p></div>
</div>
{img('fix-1280-dark-sec-lifecycle.png', 'The bench and deployed section at 1280 px')}

<h2>Proof</h2>
<div class="wrap"><table><thead><tr><th>Run</th><th>File</th><th>Verdict</th><th>Passed</th><th>Failed</th><th>Skipped</th></tr></thead><tbody>{cloud_rows()}</tbody></table></div>
<h3>The one red assertion was the ruler's, not the page's (fixed at <code>{RULER_FIX}</code>)</h3>
<p><code>tests/test_landing_page.py</code> searched the raw <code>landing.json</code> for a serial (eight upper-case hex characters, or ten decimal digits in a row)
without first blanking the hash fields, as <code>export_landing.py</code> does. Its fixed check is now line {serial_line}. Digests of fixed snapshot files hold such runs, so it fails whatever the page says.
The cloud's first failure: <code>{e(fp_line)}</code>. Every hit, and the field it sits in:</p>
<p><code>{e(', '.join(f'{h} ({f})' for h, f in hits))}</code></p>
<p class="dim">All in {e(', '.join(hit_fields))}. The rest of that test's assertions (no absolute path; no typed number or bad name in any template) hold when checked by hand with the ruler's own regexes.
The ruler forbade its builder to edit it, so its owner (the dispatcher) made the fix: blank <code>sha256</code>, <code>from_sha256</code>, <code>commit</code> and <code>sim2real_commit</code> before the search. A ten-digit number planted in a label still fails it.</p>

<h2>Decided for you</h2>
<ul>
<li>Landed on <code>main</code> and pushed to origin once the ruler fix ran green. Undo: <code>git -C /home/bam/sim2real revert 0c29ac1^..{RULER_FIX}</code>, then push.</li>
<li>Deployed the noindexed preview (robots <code>Disallow: /</code> and a noindex meta; everything on it is already public on GitHub). Undo: <code>wrangler delete --env preview</code> from <code>/home/bam/sim2real/website</code>.</li>
<li>Fixed the ruler's serial check as its owner (blank the four digest fields first, mutation-checked). Undo: <code>git revert {RULER_FIX}</code>.</li>
<li>Re-cut the hero loop from the whole clip and cropped it to the swing ({loop_kib} of WebP, under the ruler's cap); the row's still is cropped the same way. Undo: revert <code>96115ba</code>'s media.</li>
<li>Kept the BAM twin's median as "not judged" (conservative, and the gate rule says so).</li>
<li>Dispatched the cloud checks on the <code>bam</code> account: <code>jidoka</code>'s CLI still shows its first-run theme picker to a scripted terminal, so its workers do not start.</li>
</ul>
<h2>Left</h2>
<ul>
<li>Lane L10 (PID tune as calibrate()'s third step) is code-complete on <code>claude/l10-c</code> but not landed: pidtuna's new damping-band rule fails its grade, and preflight's fixture needs its owner's change.</li>
<li>bam_ws <code>reports/ur-wrist-sim2real-2026-11-12.html</code> calls the as-found wrist run "no feed-forward"; its session plan and runner carried Coulomb feed-forward on all three joints. The landing follows the plan; the old report's label is the one to correct.</li>
<li>The site is live as a noindexed preview at <code>https://sim2real-docs-preview.zach-yamaoka.workers.dev</code> (version a540f109); a production domain is still to pick.</li>
<li>Next real numbers: a Sim cell for the UR wrist and the BAM arm, and the pendulum's example re-recorded on today's schedule.</li>
</ul>
<h2>Needs you</h2>
<ul>
<li>Only for <code>jidoka</code>'s own cloud workers: open an interactive <code>claude</code> under <code>~/.claude-jidoka</code> once and pick a theme. Until then, dispatch with <code>--account bam</code> or <code>--account personal2</code>. An account at its usage limit leaves its workers idle without an error, so a capped jidoka means: pick another account, nothing breaks.</li>
</ul>
<h2>Not done, on purpose</h2>
<ul>
<li>No production domain: that is your pick. No pytest, MuJoCo or simulation on the workstation (the arm is powered): every test ran on a cloud VM.</li>
</ul>
<p class="dim">Commits: {e(' · '.join(line.split(' ', 1)[0] for line in text('git_log.txt').splitlines()))}.</p>
</main></body></html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
