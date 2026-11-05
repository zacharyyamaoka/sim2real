"""The landing page's system-ID oracle: six robot descriptions in, a better model out, each checked against a hidden truth.

Zach, PROJECT - Sim2Real, Nov 5 2026: "I want to basically show some examples on the landing page ... In all the cases its just Robot
Description in. and then a better model out." Stdlib only: everything here is read from sysid/results/*.json (written by
`python -m sysid run --all --write` and `python -m sysid drift all --write`, held to the code by sysid/tests/test_oracle.py), never
recomputed. One card per example on the home page (description in, typed tree, schedule coverage, parameters true / nominal /
recovered, held-out error before -> after); one page per example at /sysid/<id>/ with every parameter and, for the servo and the
cell, the drift demos.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from catalog_workbench.html import e

REPO = Path(__file__).resolve().parents[1]
# WHY committed results and never a computation here: docs/decision-sysid-oracle-2026-11-05.md (the site stays stdlib, and every
# number it shows is one the oracle test holds to the code)
RESULTS = REPO / "sysid" / "results"
EXAMPLES = ("pendulum_can11", "ur5e", "ur5e_2f85", "conveyor", "dual_arm_cell", "linescan_cell")
DRIFT_OF = {"pendulum_can11": "drift_backlash_wear", "dual_arm_cell": "drift_camera_knock"}
CARD_ROWS = 5  # parameters shown on a card (the page lists them all)


def load() -> dict[str, dict]:
    out = {}
    for name in EXAMPLES + tuple(DRIFT_OF.values()):
        path = RESULTS / f"{name}.json"
        if path.is_file():
            out[name] = json.loads(path.read_text(encoding="utf-8"))
    return out


def url(example: str) -> str:
    return f"/sysid/{example}/"


# --- numbers --------------------------------------------------------------------------------------------------------------------

def display(value, unit: str) -> tuple[float | None, str]:
    """A value in the unit a person reads it in: small angles in mrad, small lengths in mm (never silently rounded away)."""
    if value is None:
        return None, unit
    if unit == "rad" and abs(value) < 0.2:
        return value * 1e3, "mrad"
    if unit == "rad/h":
        return value * 1e3, "mrad/h"
    if unit == "m" and abs(value) < 0.5:
        return value * 1e3, "mm"
    return value, unit


def num(value, digits: int = 4) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "0"
    magnitude = math.floor(math.log10(abs(value)))
    decimals = max(0, digits - 1 - magnitude)
    text = f"{value:,.{decimals}f}"
    return text


def quantity(value, unit: str, digits: int = 4) -> str:
    v, u = display(value, unit)
    u = "" if u == "1" else u  # a dimensionless number prints bare (a depth scale of "1.008", not "1.008 1")
    return f"{num(v, digits)} {e(u)}".strip() if v is not None else "—"


def ci_text(row: dict) -> str:
    if not row.get("ci95"):
        return ""
    lo, _ = display(row["ci95"][0], row["unit"])
    hi, u = display(row["ci95"][1], row["unit"])
    return f"[{num(lo, 3)}, {num(hi, 3)}]"


def verdict_chip(doc: dict) -> str:
    v = doc["verdict"]
    status = v["status"]
    word = "PASS" if status == "pass" else "FAIL"
    return (f'<span class="s2r-ex-verdict s2r-ex-{status}" data-verdict="{status}">{word} · {v["parameters_pass"]}/{v["parameters"]} within tolerance · '
            f'{v["metrics_pass"]}/{v["metrics"]} held-out factors</span>')


def mark(ok) -> str:
    if ok is None:
        return '<span class="s2r-ex-mark">·</span>'
    return '<span class="s2r-ex-mark s2r-ex-ok" title="within tolerance">✓</span>' if ok else '<span class="s2r-ex-mark s2r-ex-no" title="outside tolerance">✗</span>'


# --- the card -------------------------------------------------------------------------------------------------------------------

def model_line(doc: dict) -> str:
    model = doc["description"]["model"]
    if model.get("path"):
        name = Path(model["path"]).name
        attach = doc["description"].get("attach") or []
        extra = "".join(f" + <code>{e(Path(a['path']).name)}</code>" for a in attach)
        return f"<code>{e(name)}</code>{extra}"
    parts = doc["description"]["model"].get("parts") or doc["description"].get("model", {}).get("parts") or []
    parts = doc["description"].get("model", {}).get("parts", parts)
    names = [Path(p["path"]).name for p in parts]
    cams = doc["description"]["model"].get("cameras") or []
    return " + ".join(f"<code>{e(n)}</code>" for n in names) + (f" + {len(cams)} camera{'s' if len(cams) != 1 else ''}" if cams else "")


def tree_list(doc: dict, limit: int | None = None) -> str:
    rows = [r for r in doc["tree"] if r["group"] != "structure" or r["depth"] > 0]
    shown = rows if limit is None else rows[:limit]
    items = []
    for r in shown:
        typed = (f'<a href="/types/{e(r["type"])}/">{e(r["type_title"])}</a>' if r["type_source"] == "type_cards" else
                 f'<span class="s2r-ex-adapter" title="{e(r["type_source"])}">{e(r["type_title"])}</span>')
        items.append(f'<li style="--d:{r["depth"]}" data-type="{e(r["type"])}"><span class="s2r-ex-comp">{e(r["title"])}</span> <span class="s2r-ex-arrow">→</span> {typed}</li>')
    more = f'<li class="s2r-ex-more">+ {len(rows) - len(shown)} more</li>' if len(shown) < len(rows) else ""
    return f'<ul class="s2r-ex-tree">{"".join(items)}{more}</ul>'


def coverage_line(doc: dict) -> str:
    """Train coverage; the card's coverage gate (its gate_pct) is compared only where the number IS that card's own coverage function (the servo's,
    the arm's): sysid's adapter rules (image cells, line bins, belt speed x acceleration) are labelled as such, never held to it."""
    cov = doc["schedule"]["coverage"]
    train = cov["train"]
    pct = train["pct"]
    own = str(cov.get("function", "")).startswith("type_cards")
    gate = coverage_gate_pct(doc["example"]) if own else None
    own = own and gate is not None
    bar = f'<i style="left:{gate:.0f}%" title="the {COVERAGE_CARD[doc["example"]]} card\'s coverage gate, {gate:g} %"></i>' if own else ""
    verdict = (f'<span class="s2r-ex-{"ok" if pct >= gate else "no"}">({"≥" if pct >= gate else "<"} the card\'s {gate:g} % gate)</span>' if own
               else '<span class="s2r-ex-rule" title="sysid\'s own coverage rule; the card\'s gate is on its own axes">(sysid\'s rule)</span>')
    return (f'<div class="s2r-ex-cov" data-coverage="{pct}"><div class="s2r-ex-bar"><span style="width:{min(100.0, pct):.1f}%"></span>{bar}</div>'
            f'<span>train <b>{num(pct, 3)} %</b> of {train["reachable"]:,} cells {verdict}'
            f' · held out {num(cov["held_out"]["pct"], 3)} %</span></div>')


# the card whose own coverage function an example's schedule is scored with (its gate_pct is the gate the card shows)
COVERAGE_CARD = {"pendulum_can11": "servo", "ur5e": "arm_6dof", "ur5e_2f85": "arm_6dof"}


def coverage_gate_pct(example: str) -> float | None:
    card = COVERAGE_CARD.get(example)
    if card is None:
        return None
    from type_cards import registry as reg  # noqa: PLC0415

    return reg.CARDS[card].coverage.gate_pct


def schedule_line(doc: dict) -> str:
    s = doc["schedule"]
    def part(d):
        keys = [k for k in ("runs", "poses", "excitations", "profiles", "views", "passes", "dots", "rgbd_frames", "arm_poses", "belt_travels") if k in d]
        return ", ".join(f"{d[k]:,} {k.replace('_', ' ')}" for k in keys[:3])
    return f"train {part(s['train'])} · held out {part(s['held_out'])}"


UNIT_SUFFIXES = ("_kg_m2", "_nm_s_rad", "_n_s_m", "_rad_s", "_rad", "_nm", "_kg", "_px", "_m", "_n")


def short_name(key: str) -> str:
    """A parameter key without its unit suffix (the unit is printed beside it, in the unit it is shown in)."""
    for suffix in UNIT_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def parameter_rows(doc: dict, limit: int | None = None) -> str:
    rows = doc["parameters"]
    shown = rows if limit is None else pick_rows(rows, limit)
    body = []
    for r in shown:
        unit = display(r["true"] if r["true"] is not None else r["recovered"], r["unit"])[1]
        cells = [num(display(r[k], r["unit"])[0]) for k in ("true", "nominal", "recovered")]
        body.append(f'<tr data-key="{e(r["key"])}"><th scope="row" title="{e(r["key"])}">{e(short_name(r["key"]))} <small>{e(unit)}</small></th>'
                    f'<td>{cells[0]}</td><td>{cells[1]}</td><td><b>{cells[2]}</b></td><td class="s2r-ex-m">{mark(r["pass"])}</td></tr>')
    more = "" if len(shown) == len(rows) else f'<tr class="s2r-ex-more"><td colspan="5"><a href="{url(doc["example"])}#parameters">all {len(rows)} parameters</a></td></tr>'
    return (f'<table class="s2r-ex-params"><thead><tr><th scope="col">parameter</th><th scope="col">true</th><th scope="col">nominal</th>'
            f'<th scope="col">recovered</th><th scope="col" class="s2r-ex-m"><span class="sr">within tolerance</span></th></tr></thead><tbody>{"".join(body)}{more}</tbody></table>')


def pick_rows(rows: list[dict], limit: int) -> list[dict]:
    """The card's rows: one of each kind of parameter first (so a 50-row camera shows its geometry, a gain, a dark and the D435)."""
    seen, first, rest = set(), [], []
    for r in rows:
        kind = r["name"].rstrip("0123456789").rstrip("_b") if r["name"].startswith(("gain_b", "dark_b")) else r["name"]
        group = (r["component"], kind) if r["component"] in ("hsi", "rgbd", "head_camera") else kind
        (first if group not in seen else rest).append(r)
        seen.add(group)
    return (first + rest)[:limit]


def metric_rows(doc: dict) -> str:
    out = []
    for m in doc["metrics"]:
        if not m.get("gated"):
            continue
        out.append(f'<li data-metric="{e(m["id"])}"><span class="s2r-ex-mt">{e(m["title"])}</span> '
                   f'<span class="s2r-ex-ba"><b class="s2r-ex-before">{num(m["before"], 3)}</b> → <b class="s2r-ex-after">{num(m["after"], 3)}</b> {e(m["unit"])}</span> '
                   f'<span class="s2r-ex-factor">{num(m["factor"], 3)}× better (needs {num(m["factor_needed"], 2)}×)</span> {mark(m["pass"])}</li>')
    return f'<ul class="s2r-ex-metrics">{"".join(out)}</ul>'


def card(doc: dict) -> str:
    ex = doc["example"]
    return f"""<article class="s2r-ex" data-example="{e(ex)}" data-params="{doc['verdict']['parameters']}" data-params-pass="{doc['verdict']['parameters_pass']}">
<header><h3><a href="{url(ex)}">{e(doc['title'])}</a></h3><p class="s2r-ex-sub">{e(doc.get('subtitle', ''))}</p>{verdict_chip(doc)}</header>
<section><h4>Description in</h4><p class="s2r-ex-model">{model_line(doc)}</p></section>
<section><h4>Typed tree</h4>{tree_list(doc, 7)}</section>
<section><h4>Schedule and coverage</h4><p class="s2r-ex-sched">{e(schedule_line(doc))}</p>{coverage_line(doc)}</section>
<section><h4>Parameters: true / nominal / recovered</h4>{parameter_rows(doc, CARD_ROWS)}</section>
<section><h4>Held-out error, before → after</h4>{metric_rows(doc)}</section>
<p class="s2r-ex-open"><a href="{url(ex)}">Open the example</a></p>
</article>"""


def section(docs: dict) -> str:
    examples = [docs[x] for x in EXAMPLES if x in docs]
    if not examples:
        return ""
    passing = sum(d["verdict"]["status"] == "pass" for d in examples)
    params = sum(d["verdict"]["parameters"] for d in examples)
    params_pass = sum(d["verdict"]["parameters_pass"] for d in examples)
    drift = drift_lines(docs)
    return f"""<section id="oracle" class="s2r-oracle" aria-labelledby="oracle-h">
<h2 id="oracle-h">Robot description in, a better model out</h2>
<p class="lede">The base oracle for system ID: each example's simulator plays the real hardware from <b>hidden</b> true parameters; identification starts from
the description's nominal values, never sees the truth, and must land every hidden value inside its stated tolerance and improve the held-out error by its
stated factor (sysid/acceptance.json). <b>{passing} of {len(examples)} examples pass</b>; {params_pass} of {params} hidden values recovered.</p>
{drift}
<div class="s2r-ex-grid">
{''.join(card(d) for d in examples)}
</div>
</section>"""


def drift_lines(docs: dict) -> str:
    out = []
    w = docs.get("drift_backlash_wear")
    if w:
        out.append(f'<li data-drift="backlash_wear"><a href="{url("pendulum_can11")}#drift">Backlash wear on CAN 11</a>: the wear rate recovered '
                   f'{num(w["rate_recovered"] * 1e3, 3)} mrad/h (true {num(w["rate_true"] * 1e3, 3)}); at hour {num(w["predicted_at_h"], 3)} the wear-aware twin '
                   f'forecast the drift threshold at hour <b>{num(w["predicted_crossing_h"], 3)}</b>; it crossed at hour <b>{num(w["actual_crossing_h"], 3)}</b>, '
                   f'and the plain detector warned at hour {num(w["detector_alarm_h"], 3)}.</li>')
    k = docs.get("drift_camera_knock")
    if k:
        out.append(f'<li data-drift="camera_knock"><a href="{url("dual_arm_cell")}#drift">The head camera knocked at hour {num(k["knock_h"], 3)}</a>: '
                   f'warned at hour <b>{num(k["alarm_h"], 3)}</b> (no warning before), recalibrated to {num(k["recalibrated"]["ratio"], 3)}× its calibrated error.</li>')
    return f'<ul class="s2r-ex-drift">{"".join(out)}</ul>' if out else ""


def tiles(docs: dict):
    """(href, name, count, picture) per example for the home's Choose column."""
    out = []
    for ex in EXAMPLES:
        if ex in docs:
            d = docs[ex]
            out.append((url(ex), d["title"], d["verdict"]["parameters"], f'<span class="pic s2r-ex-pic" data-verdict="{d["verdict"]["status"]}">{ICON.get(ex, "")}</span>'))
    return out


ICON = {
    "pendulum_can11": '<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="9" r="4"/><path d="M20 9 L28 31"/><circle cx="28" cy="31" r="4"/></svg>',
    "ur5e": '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M8 34h12M14 34V24l8-10 8 6"/><circle cx="14" cy="24" r="2.5"/><circle cx="22" cy="14" r="2.5"/></svg>',
    "ur5e_2f85": '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M8 34h12M14 34V24l8-10 6 4"/><path d="M28 18l5 2M28 18l2 5"/><circle cx="14" cy="24" r="2.5"/></svg>',
    "conveyor": '<svg viewBox="0 0 40 40" aria-hidden="true"><rect x="6" y="18" width="28" height="7" rx="3.5"/><circle cx="10" cy="21.5" r="1.5"/><circle cx="30" cy="21.5" r="1.5"/><path d="M16 15h8"/></svg>',
    "dual_arm_cell": '<svg viewBox="0 0 40 40" aria-hidden="true"><rect x="16" y="6" width="8" height="18"/><path d="M16 12l-8 8 3 6M24 12l8 8-3 6"/><path d="M6 32h28"/></svg>',
    "linescan_cell": '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M6 30h28M10 8h20M20 8l-9 22M20 8l9 22"/></svg>',
}


# --- one page per example -------------------------------------------------------------------------------------------------------

def page_body(doc: dict, docs: dict) -> str:
    ex = doc["example"]
    v = doc["verdict"]
    params = doc["parameters"]
    full = []
    for r in params:
        err = None if r["recovered"] is None or r["true"] is None else r["recovered"] - r["true"]
        tol = r.get("tolerance") or {}
        tol_text = (f"± {quantity(tol['value'], r['unit'], 3)}" if tol.get("kind") == "abs" else f"± {num(100 * tol['value'], 3)} %") if tol else "—"
        place = f"{e(r['card'])} {e(r['rung'])}" if r.get("card") else "—"
        full.append(f'<tr data-key="{e(r["key"])}"><th scope="row">{e(r["key"])}</th><td>{place}<br><small>{e(r.get("card_parameter") or "")}</small></td>'
                    f'<td>{quantity(r["true"], r["unit"])}</td><td>{quantity(r["nominal"], r["unit"])}</td>'
                    f'<td><b>{quantity(r["recovered"], r["unit"])}</b><br><small>{ci_text(r)}</small></td>'
                    f'<td>{quantity(err, r["unit"], 3) if err is not None else "—"}</td><td>{tol_text}</td><td>{mark(r["pass"])}</td></tr>')
    metrics = "".join(f'<tr data-metric="{e(m["id"])}"><th scope="row">{e(m["title"])}</th><td>{num(m["before"], 4)}</td><td>{num(m["after"], 4)}</td><td>{e(m["unit"])}</td>'
                      f'<td>{num(m["factor"], 3)}×</td><td>{num(m["factor_needed"], 2) + "×" if m.get("factor_needed") else "observed"}</td><td>{mark(m["pass"])}</td>'
                      f'<td><small>{e(m.get("note", ""))}</small></td></tr>' for m in doc["metrics"])
    sensors = "".join(f"<li><b>{e(s['id'])}</b> ({e(s['kind'])}) on {e(s['on'])}: {e(s['measures'])}</li>" for s in doc["description"].get("sensors", []))
    tree = "".join(f'<tr><td style="padding-left:{8 + 16 * r["depth"]}px">{e(r["title"])}</td><td>{e(r["word"])}</td>'
                   f'<td>{(chr(60) + "a href=" + chr(34) + "/types/" + e(r["type"]) + "/" + chr(34) + ">" + e(r["type_title"]) + "</a>") if r["type_source"] == "type_cards" else e(r["type_title"])}</td>'
                   f'<td><small>{e(SOURCE_WORD.get(r["type_source"], r["type_source"]))}</small></td><td><small>{e(", ".join(r["parameters"])[:160])}</small></td></tr>' for r in doc["tree"])
    ladders = ladders_html(doc)
    extra = servo_extra(doc) if ex == "pendulum_can11" else ""
    drift = drift_html(docs.get(DRIFT_OF.get(ex, ""), None), ex) if ex in DRIFT_OF else ""
    notes = "".join(f"<li>{e(n)}</li>" for n in doc.get("notes", []))
    cov = doc["schedule"]["coverage"]
    prov = doc.get("provenance", {})
    return f"""<h1>{e(doc['title'])} <small>{e(doc.get('subtitle', ''))}</small></h1>
<p class="lede">{e(doc.get('summary', ''))}</p>
<p>{verdict_chip(doc)}</p>
<h2 id="description">Description in</h2>
<p>Model: {model_line(doc)} · {e(doc['description']['model'].get('source', ''))}<br>Manifest: <code>{e(doc['description']['manifest'])}</code></p>
<ul class="s2r-ex-sensors">{sensors}</ul>
<h2 id="tree">Typed tree</h2>
<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th>component</th><th>description's word</th><th>type</th><th>typed by</th><th>its parameters</th></tr></thead><tbody>{tree}</tbody></table></div>
<h2 id="schedule">Schedule and coverage</h2>
<p>{e(schedule_line(doc))}</p>{coverage_line(doc)}
<p><small>{e(cov.get('function', ''))}. Rule: {e(cov.get('rule', ''))}.</small></p>
{plane_svg(cov)}
<h2 id="parameters">Parameters ({v['parameters_pass']} of {v['parameters']} within tolerance)</h2>
<div class="s2r-scroll"><table class="s2r-table s2r-ex-full"><thead><tr><th>parameter</th><th>card · rung</th><th>true (hidden)</th><th>nominal</th><th>recovered [95 %]</th><th>error</th><th>tolerance</th><th></th></tr></thead><tbody>{''.join(full)}</tbody></table></div>
<h2 id="metrics">Held-out error, before → after</h2>
<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th>metric</th><th>before (nominal)</th><th>after (fitted)</th><th>unit</th><th>better by</th><th>needs</th><th></th><th></th></tr></thead><tbody>{metrics}</tbody></table></div>
{extra}
{drift}
<h2 id="ladders">Where the values sit on the type cards</h2>
{ladders}
<h2 id="notes">Notes</h2><ul>{notes}</ul>
<p><small>Code {e(str(prov.get('code', '')))} · {e(str(prov.get('seconds', '')))} s · identification ran with the world sealed: {e(str(prov.get('identify_sealed')))}{imports_line(prov)}</small></p>"""


def imports_line(prov: dict) -> str:
    """The checkouts outside sim2real the run used in place (sysid.result.provenance): name, branch, the last commit that touched
    what was used, +dirty when that had uncommitted changes."""
    stamps = prov.get("imports") or []
    if not stamps:
        return ""
    words = " · ".join(f"{s['name']} {s['branch']} @ {s['commit']}{' +dirty' if s['dirty'] else ''}" for s in stamps)
    return f"<br>Checkouts used in place (by the modules loaded in the process that computed this, and the description's files): {e(words)}"


SOURCE_WORD = {"type_cards": "type card", "sysid adapter (no card yet)": "sysid adapter", "structural": "structure"}


def ladders_html(doc: dict) -> str:
    out = []
    for lad in doc.get("card_ladders", []):
        rows = "".join(f'<tr class="{"s2r-ex-hit" if r["identified"] else ""}"><td class="s2r-ex-key"><b>{e(r["key"])}</b></td><td>{e(r["name"])}</td><td>{r["n_parameters"]:,}</td>'
                       f'<td><small>{e(", ".join(r.get("added", [])))}</small></td><td><small>{e(", ".join(r["identified"]))}</small></td></tr>' for r in lad["rungs"])
        out.append(f'<h3><a href="/types/{e(lad["card"])}/">{e(lad["title"])}</a></h3><div class="s2r-scroll"><table class="s2r-table"><thead><tr><th>rung</th><th>model</th>'
                   f'<th>parameters</th><th>adds</th><th>identified here</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return "".join(out) or "<p>No type card ladder applies.</p>"


def servo_extra(doc: dict) -> str:
    rungs = [r for r in doc.get("rungs", []) if r.get("held_out_ratio") is not None]
    rows = "".join(f'<tr data-rung="{e(r["key"])}"><td><b>{e(r["key"])}</b></td><td>{e(r["name"])}</td><td>{num(r["held_out_ratio"], 3)}× floor</td>'
                   f'<td>{num(r["link_mrad"], 3)} mrad</td><td>{"selected" if r["key"] == doc.get("selected_rung") else ""}</td></tr>' for r in rungs)
    stock = doc.get("stock_fit", {}).get("estimates", {})
    srows = "".join(f'<tr><td>{e(k)}</td><td>{num(s.get("value"), 4)}</td><td>{num(s.get("true"), 4)}</td><td>{num(s.get("error_pct"), 3) + " %" if s.get("error_pct") is not None else "—"}</td>'
                    f'<td><small>{e(s.get("refused") or "")}</small></td></tr>' for k, s in stock.items())
    return f"""<h2 id="rungs">The servo's ladder on held-out data</h2>
<p>The selection rule (type_cards): the lowest rung whose held-out fidelity reaches the floor (≤ 1.5×). Selected: <b data-selected="{e(str(doc.get('selected_rung')))}">{e(str(doc.get('selected_rung')))}</b>, the rung whose structure the hidden truth has.</p>
<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th>rung</th><th>model</th><th>held-out link fidelity</th><th>RMS</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
<h3>The stock quasi-static fits on the same train runs (bam_rack_twin.identify)</h3>
<p>Under CAN 11's ki 16000 the joint limit-cycles through its slow sweeps, so the stock gravity fit reads inertia as load; sysid's one regression over
every train run does not. Reported, not gated.</p>
<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th>estimate</th><th>stock value</th><th>true</th><th>error</th><th>refused</th></tr></thead><tbody>{srows}</tbody></table></div>"""


def drift_html(d: dict | None, example: str) -> str:
    if not d:
        return ""
    if d["name"] == "backlash_wear":
        rec = d.get("recalibrated") or {}
        return f"""<h2 id="drift">Drift: backlash wear, detected vs forecast</h2>
<p>Every {num(d['check_every_h'], 3)} deployment hours the joint runs its daily motions ({e(d['check'])}) on the wearing joint; the hidden gap grows as
b(h) = b0 + k h. <b>Wear rate</b> recovered from the early-life checks (to hour {num(d['early_life_h'], 3)}): <b data-rate="{d['rate_recovered']}">{num(d['rate_recovered'] * 1e3, 4)} mrad/h</b>
(true {num(d['rate_true'] * 1e3, 4)}; 95 % {num(d['rate_ci95'][0] * 1e3, 3)} to {num(d['rate_ci95'][1] * 1e3, 3)}). The servo card's M5.wear law is Archard's: at this
check's duty of {num(d['wear']['duty_nm_rev_per_h'], 3)} N·m·rev per hour that is {num(d['wear']['rate_recovered_per_nm_rev'] * 1e6, 3)} µrad per N·m·rev.</p>
<ul class="s2r-ex-wear">
<li><b>Forecast</b> (the wear-aware twin, at hour {num(d['predicted_at_h'], 3)}): the threshold at hour <b data-predicted="{d['predicted_crossing_h']}">{num(d['predicted_crossing_h'], 4)}</b>, {num(d['remaining_h_at_prediction'], 3)} hours ahead (a gap of {num(d['gap_at_threshold_rad'] * 1e3, 3)} mrad)</li>
{f'<li><b>Plan by</b> hour <b data-plan-by="{d["plan_by_h"]}">{num(d["plan_by_h"], 4)}</b>: the same forecast at the wear line&#39;s upper 95 % band, the early edge maintenance schedules against</li>' if d.get('plan_by_h') is not None else ''}
<li><b>Actual crossing</b> in the sim: hour <b data-actual="{d['actual_crossing_h']}">{num(d['actual_crossing_h'], 4)}</b></li>
<li><b>Plain detector</b> (the servo card's drift check, "{e(d['diagnostic']['message'])}"): warned at hour <b data-alarm="{d['detector_alarm_h']}">{num(d['detector_alarm_h'], 4)}</b>, after the fact</li>
<li>The card's own trend forecast (the drift ratio's history alone, at hour {num(d['predicted_at_h'], 3)}): {num(d['card_trend_remaining_h'], 3) if d.get('card_trend_remaining_h') is not None else 'no crossing in sight'} hours left</li>
<li><b>Recalibrated</b> at the warning (the gap re-measured): the drift ratio back to {num(rec.get('ratio'), 3)}×</li>
</ul>
{wear_svg(d)}
<p><small>Threshold: {e(d['threshold_rule'])}.</small></p>"""
    rec = d.get("recalibrated") or {}
    rows = "".join(f"<tr><td>{e(k)}</td><td>{quantity(d['shift_true'][k], 'm' if k.endswith('_m') else 'rad', 3)}</td><td>{quantity(d['shift_recovered'].get(k), 'm' if k.endswith('_m') else 'rad', 3)}</td></tr>"
                   for k in d["shift_true"])
    return f"""<h2 id="drift">Drift: the head camera knocked out of pose</h2>
<p>Every {num(d['check_every_h'], 3)} hours the belt carries its printed tags past the head camera. At hour {num(d['knock_h'], 3)} the camera is knocked. The camera card's drift check
warned at hour <b data-alarm="{d['alarm_h']}">{num(d['alarm_h'], 3)}</b> and never before; a short recalibration (belt tags and the arms' tags, the camera's six pose numbers) brought the
ratio back to <b>{num(rec.get('ratio'), 3)}×</b>.</p>
{knock_svg(d)}
<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th>the knock</th><th>true</th><th>recovered</th></tr></thead><tbody>{rows}</tbody></table></div>"""


# --- charts (inline SVG: tokens only, readable in both themes) --------------------------------------------------------------------

def _axes(x0, x1, y0, y1, w=640, h=230, pad=(44, 14, 24, 30)):
    left, right, top, bottom = pad
    sx = lambda x: left + (x - x0) / (x1 - x0) * (w - left - right)  # noqa: E731
    sy = lambda y: h - bottom - (y - y0) / (y1 - y0) * (h - top - bottom)  # noqa: E731
    return sx, sy, w, h, left, right, top, bottom


def wear_svg(d: dict) -> str:
    checks = d["checks"]
    xmax = d["horizon_h"]
    ymax = max(max(c["ratio"] for c in checks), d["threshold"]) * 1.1
    sx, sy, w, h, left, right, top, bottom = _axes(0, xmax, 0, ymax)
    pts = " ".join(f"{sx(c['h']):.1f},{sy(c['ratio']):.1f}" for c in checks)
    dots = "".join(f'<circle cx="{sx(c["h"]):.1f}" cy="{sy(c["ratio"]):.1f}" r="2.6" class="{"s2r-svg-warn" if c["status"] == "warning" else "s2r-svg-real"}"/>' for c in checks)
    thr = sy(d["threshold"])
    pred, act, alarm, early = d["predicted_crossing_h"], d["actual_crossing_h"], d["detector_alarm_h"], d["early_life_h"]
    ticks = "".join(f'<text x="{sx(t):.1f}" y="{h - 10}" class="s2r-svg-tick" text-anchor="middle">{t:g}</text>' for t in range(0, int(xmax) + 1, 96))
    yt = "".join(f'<text x="{left - 6}" y="{sy(t) + 4:.1f}" class="s2r-svg-tick" text-anchor="end">{t:g}×</text>' for t in (1, 2, 3, 4, 5, 6) if t < ymax)
    marks = ""
    if pred is not None:
        marks += f'<line x1="{sx(pred):.1f}" x2="{sx(pred):.1f}" y1="{top}" y2="{h - bottom}" class="s2r-svg-pred"/><text x="{sx(pred) - 4:.1f}" y="{top + 10}" class="s2r-svg-lab" text-anchor="end">forecast {pred:.0f} h</text>'
    if act is not None:
        marks += f'<line x1="{sx(act):.1f}" x2="{sx(act):.1f}" y1="{top + 14}" y2="{h - bottom}" class="s2r-svg-act"/><text x="{sx(act) + 4:.1f}" y="{top + 24}" class="s2r-svg-lab">crossed {act:.0f} h</text>'
    if alarm is not None:
        # below the threshold line, clear of the forecast and crossing labels at the top
        marks += f'<text x="{sx(alarm) + 4:.1f}" y="{thr + 16:.1f}" class="s2r-svg-lab s2r-svg-warntext">detector {alarm:.0f} h</text>'
    return f"""<figure class="s2r-ex-fig"><svg viewBox="0 0 {w} {h}" role="img" aria-label="drift ratio against deployment hours">
<rect x="{sx(0):.1f}" y="{top}" width="{sx(early) - sx(0):.1f}" height="{h - top - bottom}" class="s2r-svg-early"/>
<text x="{sx(early / 2):.1f}" y="{h - bottom - 6}" class="s2r-svg-lab" text-anchor="middle">early life (rate fitted)</text>
<line x1="{left}" x2="{w - right}" y1="{thr:.1f}" y2="{thr:.1f}" class="s2r-svg-thr"/><text x="{w - right}" y="{thr - 4:.1f}" class="s2r-svg-lab" text-anchor="end">threshold {d['threshold']:.2f}×</text>
<polyline points="{pts}" class="s2r-svg-line"/>{dots}{marks}{ticks}{yt}
<text x="{(left + w - right) / 2:.0f}" y="{h - 1}" class="s2r-svg-tick" text-anchor="middle">deployment hours</text></svg>
<figcaption>Drift ratio (live fidelity ÷ calibrated) at every check: dots past the threshold are the detector's warnings. The forecast line was drawn at hour {early:g} from the gap's early-life trend.</figcaption></figure>"""


def knock_svg(d: dict) -> str:
    checks = d["checks"]
    xmax = d["horizon_h"]
    ymax = max(c["ratio"] for c in checks) * 1.1
    sx, sy, w, h, left, right, top, bottom = _axes(0, xmax, 0.5, ymax)

    def y(v):
        return sy(max(0.5, v))

    pts = " ".join(f"{sx(c['h']):.1f},{y(c['ratio']):.1f}" for c in checks)
    dots = "".join(f'<circle cx="{sx(c["h"]):.1f}" cy="{y(c["ratio"]):.1f}" r="2.6" class="{"s2r-svg-warn" if c["status"] == "warning" else "s2r-svg-real"}"/>' for c in checks)
    thr = y(d["threshold"])
    knock = sx(d["knock_h"])
    rec = d.get("recalibrated") or {}
    rec_dot = f'<circle cx="{sx(rec["h"]) + 6:.1f}" cy="{y(rec["ratio"]):.1f}" r="4" class="s2r-svg-recal"/><text x="{sx(rec["h"]) + 12:.1f}" y="{y(rec["ratio"]) - 6:.1f}" class="s2r-svg-lab">recalibrated {rec["ratio"]:.2f}×</text>' if rec else ""
    ticks = "".join(f'<text x="{sx(t):.1f}" y="{h - 10}" class="s2r-svg-tick" text-anchor="middle">{t:g}</text>' for t in range(0, int(xmax) + 1, 96))
    return f"""<figure class="s2r-ex-fig"><svg viewBox="0 0 {w} {h}" role="img" aria-label="reprojection drift ratio against hours">
<line x1="{knock:.1f}" x2="{knock:.1f}" y1="{top}" y2="{h - bottom}" class="s2r-svg-act"/><text x="{knock - 4:.1f}" y="{top + 10}" class="s2r-svg-lab" text-anchor="end">knocked at {d['knock_h']:.0f} h</text>
<line x1="{left}" x2="{w - right}" y1="{thr:.1f}" y2="{thr:.1f}" class="s2r-svg-thr"/><text x="{left + 4}" y="{thr - 4:.1f}" class="s2r-svg-lab">threshold {d['threshold']:.2f}×</text>
<polyline points="{pts}" class="s2r-svg-line"/>{dots}{rec_dot}{ticks}
<text x="{(left + w - right) / 2:.0f}" y="{h - 1}" class="s2r-svg-tick" text-anchor="middle">deployment hours</text></svg>
<figcaption>Reprojection error of the belt tags ÷ the calibrated error, every check. A knock is a step, not wear: there is nothing to forecast, so the detector is the tool.</figcaption></figure>"""


def plane_svg(cov: dict) -> str:
    plane = cov.get("plane")
    if not plane:
        return ""
    counts = plane["counts"]
    rows, cols = len(counts), len(counts[0])
    cw, ch = 30, 14
    w, h = 60 + cols * cw, 30 + rows * ch
    peak = max(max(r) for r in counts) or 1
    cells = []
    for i, row in enumerate(counts):
        for j, n in enumerate(row):
            if n:
                cells.append(f'<rect x="{50 + j * cw}" y="{8 + (rows - 1 - i) * ch}" width="{cw - 1}" height="{ch - 1}" class="s2r-svg-cell" style="opacity:{0.15 + 0.85 * math.log1p(n) / math.log1p(peak):.2f}"/>')
    return f"""<figure class="s2r-ex-fig s2r-ex-plane"><svg viewBox="0 0 {w} {h}" role="img" aria-label="train coverage, q by qd">{''.join(cells)}
<text x="4" y="{8 + rows * ch / 2:.0f}" class="s2r-svg-tick">q</text><text x="{50 + cols * cw / 2:.0f}" y="{h - 4}" class="s2r-svg-tick" text-anchor="middle">qd</text></svg>
<figcaption>The train split's targets on the (q, qd) plane, cell by cell (darker: more samples), the schedule's own edges.</figcaption></figure>"""


def index_body(docs: dict) -> str:
    rows = "".join(f'<tr data-example="{e(x)}"><td><a href="{url(x)}">{e(docs[x]["title"])}</a></td><td>{e(docs[x].get("subtitle", ""))}</td><td>{verdict_chip(docs[x])}</td></tr>'
                   for x in EXAMPLES if x in docs)
    return f"""<h1>System-ID oracle</h1><p class="lede">Six robot descriptions in, a better model out, each against a hidden truth (sysid/).</p>
{drift_lines(docs)}
<div class="s2r-scroll"><table class="s2r-table"><thead><tr><th>example</th><th>what</th><th>verdict</th></tr></thead><tbody>{rows}</tbody></table></div>"""
